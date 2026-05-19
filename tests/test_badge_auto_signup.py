"""Tests for the badge-driven auto-signup funnel.

Embedding the pet badge in a README counts as high-intent — first fetch
lazy-creates a placeholder, the badge nudges to "click to claim", and the
OAuth callback binds the placeholder once the user proves access to the repo.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.api import auth as auth_mod
from github_tamagotchi.models.pet import Pet
from github_tamagotchi.models.user import User
from github_tamagotchi.repositories import pet as pet_repo
from github_tamagotchi.services import pet as pet_service


async def _count_pets(session: AsyncSession, owner: str, repo: str) -> int:
    result = await session.execute(
        select(Pet).where(Pet.repo_owner == owner, Pet.repo_name == repo)
    )
    return len(result.scalars().all())


# ----- Badge endpoint -----


@pytest.mark.asyncio
async def test_badge_for_unknown_repo_creates_placeholder_and_serves_seedling(
    async_client: AsyncClient,
) -> None:
    resp = await async_client.get("/api/v1/pets/octocat/unbadged/badge.svg")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/svg+xml")
    body = resp.text
    assert "click to claim" in body
    assert "octocat/unbadged" in body  # repo label visible on placeholder


@pytest.mark.asyncio
async def test_badge_fetch_is_idempotent(async_client: AsyncClient) -> None:
    """Repeated fetches for the same unknown repo must not create duplicates."""
    for _ in range(3):
        resp = await async_client.get("/api/v1/pets/octocat/repeated/badge.svg")
        assert resp.status_code == 200

    from tests.conftest import test_session_factory
    async with test_session_factory() as session:
        assert await _count_pets(session, "octocat", "repeated") == 1


@pytest.mark.asyncio
async def test_badge_for_existing_pet_returns_normal_badge(
    async_client: AsyncClient,
) -> None:
    from tests.conftest import test_session_factory
    async with test_session_factory() as session:
        await pet_repo.create_pet(
            session, "octocat", "real", name="Pixel", is_placeholder=False
        )

    resp = await async_client.get("/api/v1/pets/octocat/real/badge.svg")
    assert resp.status_code == 200
    body = resp.text
    assert "click to claim" not in body
    assert "Pixel" in body


# ----- get_or_create_placeholder service -----


@pytest.mark.asyncio
async def test_get_or_create_placeholder_creates_once(test_db: AsyncSession) -> None:
    pet1, created1 = await pet_service.get_or_create_placeholder(
        test_db, "octocat", "lazycat"
    )
    pet2, created2 = await pet_service.get_or_create_placeholder(
        test_db, "octocat", "lazycat"
    )
    assert created1 is True
    assert created2 is False
    assert pet1.id == pet2.id
    assert pet1.is_placeholder is True
    assert pet1.user_id is None


# ----- Scheduler skips placeholders -----


@pytest.mark.asyncio
async def test_listings_skip_placeholders(test_db: AsyncSession) -> None:
    await pet_repo.create_pet(test_db, "a", "real", name="Real", is_placeholder=False)
    await pet_repo.create_pet(
        test_db, "b", "placeholder", name="Seedling", is_placeholder=True
    )

    pets, total = await pet_repo.get_pets(test_db, page=1, per_page=10)
    names = {p.name for p in pets}
    assert names == {"Real"}
    assert total == 1

    all_pets = await pet_repo.get_all(test_db)
    assert {p.name for p in all_pets} == {"Real"}


# ----- POST /pets claims a placeholder -----


@pytest.mark.asyncio
async def test_create_pet_via_post_claims_existing_placeholder(
    test_db: AsyncSession,
) -> None:
    placeholder = await pet_repo.create_pet(
        test_db, "octocat", "to-claim", name="Seedling", is_placeholder=True
    )

    upgraded = await pet_service.create(
        test_db, "octocat", "to-claim", "Pixel", user_id=42, style="kawaii"
    )

    assert upgraded.id == placeholder.id  # same row
    assert upgraded.is_placeholder is False
    assert upgraded.user_id == 42
    assert upgraded.name == "Pixel"
    assert upgraded.claimed_at is not None


# ----- OAuth claim helper -----


def _fake_user(*, id: int = 7, login: str = "alice") -> User:
    user = User(github_id=1, github_login=login, github_avatar_url=None)
    user.id = id
    return user


@pytest.mark.asyncio
async def test_claim_helper_happy_path(test_db: AsyncSession) -> None:
    await pet_repo.create_pet(
        test_db, "alice", "myrepo", name="Seedling", is_placeholder=True
    )

    with (
        patch.object(
            auth_mod,
            "_verify_github_repo_access",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "github_tamagotchi.services.image_queue.create_job",
            new=AsyncMock(return_value=MagicMock(id=1)),
        ),
    ):
        owner, repo = await auth_mod._claim_placeholder_for_user(
            session=test_db,
            user=_fake_user(),
            access_token="tok",
            claim_target="alice/myrepo",
        )

    assert (owner, repo) == ("alice", "myrepo")
    pet = await pet_repo.get_pet_by_repo(test_db, "alice", "myrepo")
    assert pet is not None
    assert pet.is_placeholder is False
    assert pet.user_id == 7
    assert pet.claimed_at is not None


@pytest.mark.asyncio
async def test_claim_helper_no_access_raises(test_db: AsyncSession) -> None:
    await pet_repo.create_pet(
        test_db, "alice", "private", name="Seedling", is_placeholder=True
    )
    with patch.object(
        auth_mod,
        "_verify_github_repo_access",
        new=AsyncMock(return_value=False),
    ), pytest.raises(auth_mod._ClaimError) as excinfo:
        await auth_mod._claim_placeholder_for_user(
            session=test_db,
            user=_fake_user(),
            access_token="tok",
            claim_target="alice/private",
        )
    assert excinfo.value.reason == "no_access"

    pet = await pet_repo.get_pet_by_repo(test_db, "alice", "private")
    assert pet is not None and pet.is_placeholder is True


@pytest.mark.asyncio
async def test_claim_helper_already_claimed_by_other_user_raises(
    test_db: AsyncSession,
) -> None:
    pet = await pet_repo.create_pet(
        test_db, "alice", "taken", name="Seedling", is_placeholder=True
    )
    await pet_repo.claim_placeholder(test_db, pet, user_id=99)

    with pytest.raises(auth_mod._ClaimError) as excinfo:
        await auth_mod._claim_placeholder_for_user(
            session=test_db,
            user=_fake_user(id=7),
            access_token="tok",
            claim_target="alice/taken",
        )
    assert excinfo.value.reason == "already_claimed"


@pytest.mark.asyncio
async def test_claim_helper_idempotent_for_same_user(test_db: AsyncSession) -> None:
    pet = await pet_repo.create_pet(
        test_db, "alice", "mine", name="Seedling", is_placeholder=True
    )
    await pet_repo.claim_placeholder(test_db, pet, user_id=7)

    owner, repo = await auth_mod._claim_placeholder_for_user(
        session=test_db,
        user=_fake_user(id=7),
        access_token="tok",
        claim_target="alice/mine",
    )
    assert (owner, repo) == ("alice", "mine")


@pytest.mark.asyncio
async def test_claim_helper_not_found_raises(test_db: AsyncSession) -> None:
    with pytest.raises(auth_mod._ClaimError) as excinfo:
        await auth_mod._claim_placeholder_for_user(
            session=test_db,
            user=_fake_user(),
            access_token="tok",
            claim_target="ghost/repo",
        )
    assert excinfo.value.reason == "not_found"


# ----- /auth/github accepts and validates claim param -----


def test_parse_claim_accepts_well_formed_owner_repo() -> None:
    assert auth_mod._parse_claim("foo/bar") == "foo/bar"
    assert auth_mod._parse_claim("foo-bar/baz.qux") == "foo-bar/baz.qux"


def test_parse_claim_rejects_garbage() -> None:
    for bad in (None, "", "no-slash", "a/b/c", "a/", "/a", "a/b c", "a/" + "x" * 200):
        assert auth_mod._parse_claim(bad) is None
