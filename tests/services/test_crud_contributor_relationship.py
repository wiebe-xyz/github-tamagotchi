"""Unit tests for ContributorRelationship CRUD operations."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.crud import contributor_relationship as cr_crud
from github_tamagotchi.crud import pet as pet_crud
from github_tamagotchi.models.contributor_relationship import ContributorStanding


async def _make_pet(db: AsyncSession, *, owner: str = "testuser", repo: str = "testrepo") -> object:
    """Helper to create and persist a pet."""
    pet = await pet_crud.create_pet(db, owner, repo, "TestPet")
    return pet


async def test_get_contributors_for_pet_empty(test_db: AsyncSession) -> None:
    """Returns an empty list when no relationships exist for a pet."""
    pet = await _make_pet(test_db)
    result = await cr_crud.get_contributors_for_pet(test_db, pet.id)
    assert result == []


async def test_get_contributors_for_pet_ordered_by_score(test_db: AsyncSession) -> None:
    """Results are ordered by score descending."""
    pet = await _make_pet(test_db)

    await cr_crud.upsert_contributor_relationship(
        test_db, pet.id, "alice", score=10, standing=ContributorStanding.GOOD,
        last_activity=None, good_deeds=[], sins=[],
    )
    await cr_crud.upsert_contributor_relationship(
        test_db, pet.id, "bob", score=50, standing=ContributorStanding.FAVORITE,
        last_activity=None, good_deeds=[], sins=[],
    )
    await cr_crud.upsert_contributor_relationship(
        test_db, pet.id, "carol", score=5, standing=ContributorStanding.NEUTRAL,
        last_activity=None, good_deeds=[], sins=[],
    )
    await test_db.commit()

    result = await cr_crud.get_contributors_for_pet(test_db, pet.id)

    assert len(result) == 3
    assert result[0].github_username == "bob"
    assert result[1].github_username == "alice"
    assert result[2].github_username == "carol"


async def test_upsert_contributor_relationship_insert(test_db: AsyncSession) -> None:
    """Inserts a new relationship when none exists."""
    pet = await _make_pet(test_db)
    now = datetime.now(UTC)

    rel = await cr_crud.upsert_contributor_relationship(
        test_db, pet.id, "alice", score=20, standing=ContributorStanding.GOOD,
        last_activity=now, good_deeds=["merged PR"], sins=[],
    )
    await test_db.commit()

    assert rel.pet_id == pet.id
    assert rel.github_username == "alice"
    assert rel.score == 20
    assert rel.standing == ContributorStanding.GOOD
    assert rel.last_activity == now
    assert rel.good_deeds == ["merged PR"]
    assert rel.sins == []


async def test_upsert_contributor_relationship_update(test_db: AsyncSession) -> None:
    """Updates an existing relationship on second upsert."""
    pet = await _make_pet(test_db)

    await cr_crud.upsert_contributor_relationship(
        test_db, pet.id, "alice", score=10, standing=ContributorStanding.NEUTRAL,
        last_activity=None, good_deeds=[], sins=[],
    )
    await test_db.commit()

    # Update the same contributor
    now = datetime.now(UTC)
    updated = await cr_crud.upsert_contributor_relationship(
        test_db, pet.id, "alice", score=99, standing=ContributorStanding.FAVORITE,
        last_activity=now, good_deeds=["big feature"], sins=["broke build"],
    )
    await test_db.commit()

    assert updated.score == 99
    assert updated.standing == ContributorStanding.FAVORITE
    assert updated.last_activity == now
    assert updated.good_deeds == ["big feature"]
    assert updated.sins == ["broke build"]


async def test_upsert_contributor_relationship_different_pets(test_db: AsyncSession) -> None:
    """Same username on different pets creates two separate records."""
    pet1 = await _make_pet(test_db, owner="user1", repo="repo1")
    pet2 = await _make_pet(test_db, owner="user2", repo="repo2")

    await cr_crud.upsert_contributor_relationship(
        test_db, pet1.id, "alice", score=5, standing=ContributorStanding.NEUTRAL,
        last_activity=None, good_deeds=[], sins=[],
    )
    await cr_crud.upsert_contributor_relationship(
        test_db, pet2.id, "alice", score=99, standing=ContributorStanding.FAVORITE,
        last_activity=None, good_deeds=[], sins=[],
    )
    await test_db.commit()

    rels1 = await cr_crud.get_contributors_for_pet(test_db, pet1.id)
    rels2 = await cr_crud.get_contributors_for_pet(test_db, pet2.id)

    assert len(rels1) == 1
    assert rels1[0].score == 5
    assert len(rels2) == 1
    assert rels2[0].score == 99


async def test_apply_score_delta_creates_new_relationship(test_db: AsyncSession) -> None:
    """apply_score_delta creates a minimal record when no relationship exists."""
    pet = await _make_pet(test_db)
    now = datetime.now(UTC)

    rel = await cr_crud.apply_score_delta(
        test_db, pet.id, "newguy", delta=10,
        event_description="opened a PR", now=now,
    )
    await test_db.commit()

    assert rel is not None
    assert rel.score == 10
    assert rel.last_activity == now
    assert rel.good_deeds == ["opened a PR"]
    assert rel.sins == []


async def test_apply_score_delta_updates_existing_positive(test_db: AsyncSession) -> None:
    """Positive delta increments score and records a good deed."""
    pet = await _make_pet(test_db)
    now = datetime.now(UTC)

    await cr_crud.upsert_contributor_relationship(
        test_db, pet.id, "alice", score=10, standing=ContributorStanding.NEUTRAL,
        last_activity=None, good_deeds=[], sins=[],
    )
    await test_db.commit()

    rel = await cr_crud.apply_score_delta(
        test_db, pet.id, "alice", delta=5, event_description="fixed a bug", now=now,
    )
    await test_db.commit()

    assert rel is not None
    assert rel.score == 15
    assert "fixed a bug" in rel.good_deeds
    assert rel.last_activity == now


async def test_apply_score_delta_updates_existing_negative(test_db: AsyncSession) -> None:
    """Negative delta decrements score and records a sin."""
    pet = await _make_pet(test_db)
    now = datetime.now(UTC)

    await cr_crud.upsert_contributor_relationship(
        test_db, pet.id, "alice", score=20, standing=ContributorStanding.GOOD,
        last_activity=None, good_deeds=[], sins=[],
    )
    await test_db.commit()

    rel = await cr_crud.apply_score_delta(
        test_db, pet.id, "alice", delta=-3, event_description="broke the build", now=now,
    )
    await test_db.commit()

    assert rel is not None
    assert rel.score == 17
    assert "broke the build" in rel.sins
    assert rel.good_deeds == []


async def test_apply_score_delta_good_deeds_capped_at_five(test_db: AsyncSession) -> None:
    """Good deeds list is capped at 5 entries, most recent first."""
    pet = await _make_pet(test_db)
    now = datetime.now(UTC)

    await cr_crud.upsert_contributor_relationship(
        test_db, pet.id, "alice", score=0, standing=ContributorStanding.NEUTRAL,
        last_activity=None,
        good_deeds=["deed1", "deed2", "deed3", "deed4", "deed5"],
        sins=[],
    )
    await test_db.commit()

    rel = await cr_crud.apply_score_delta(
        test_db, pet.id, "alice", delta=1, event_description="new deed", now=now,
    )
    await test_db.commit()

    assert rel is not None
    assert len(rel.good_deeds) == 5
    assert rel.good_deeds[0] == "new deed"


async def test_apply_score_delta_sins_capped_at_five(test_db: AsyncSession) -> None:
    """Sins list is capped at 5 entries, most recent first."""
    pet = await _make_pet(test_db)
    now = datetime.now(UTC)

    await cr_crud.upsert_contributor_relationship(
        test_db, pet.id, "alice", score=0, standing=ContributorStanding.NEUTRAL,
        last_activity=None, good_deeds=[],
        sins=["sin1", "sin2", "sin3", "sin4", "sin5"],
    )
    await test_db.commit()

    rel = await cr_crud.apply_score_delta(
        test_db, pet.id, "alice", delta=-1, event_description="new sin", now=now,
    )
    await test_db.commit()

    assert rel is not None
    assert len(rel.sins) == 5
    assert rel.sins[0] == "new sin"


async def test_apply_score_delta_uses_current_time_when_now_is_none(
    test_db: AsyncSession,
) -> None:
    """apply_score_delta uses current UTC time when `now` is not provided."""
    pet = await _make_pet(test_db)
    before = datetime.now(UTC)

    rel = await cr_crud.apply_score_delta(
        test_db, pet.id, "alice", delta=1, event_description="automated event",
    )
    await test_db.commit()

    after = datetime.now(UTC)

    assert rel is not None
    # last_activity should be approximately now
    assert rel.last_activity is not None
    # Compare as naive or aware consistently
    last_activity = rel.last_activity
    if last_activity.tzinfo is None:
        last_activity = last_activity.replace(tzinfo=UTC)
    before_naive = before.replace(tzinfo=None) if before.tzinfo else before
    after_naive = after.replace(tzinfo=None) if after.tzinfo else after
    last_naive = last_activity.replace(tzinfo=None)
    assert before_naive <= last_naive <= after_naive
