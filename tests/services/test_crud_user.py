"""Unit tests for User CRUD operations."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.crud import user as user_crud


async def test_get_user_by_github_id_not_found(test_db: AsyncSession) -> None:
    """Returns None when no user exists with that GitHub ID."""
    result = await user_crud.get_user_by_github_id(test_db, 99999)
    assert result is None


async def test_get_user_by_id_not_found(test_db: AsyncSession) -> None:
    """Returns None when no user exists with that internal ID."""
    result = await user_crud.get_user_by_id(test_db, 99999)
    assert result is None


async def test_create_or_update_user_creates_new(test_db: AsyncSession) -> None:
    """Creates a new user record on first call."""
    user = await user_crud.create_or_update_user(
        test_db,
        github_id=1001,
        github_login="alice",
        github_avatar_url="https://example.com/alice.png",
        encrypted_token="tok_abc",
    )

    assert user.id is not None
    assert user.github_id == 1001
    assert user.github_login == "alice"
    assert user.github_avatar_url == "https://example.com/alice.png"
    assert user.encrypted_token == "tok_abc"


async def test_create_or_update_user_updates_existing(test_db: AsyncSession) -> None:
    """Updates login, avatar, and token on subsequent call for same github_id."""
    await user_crud.create_or_update_user(
        test_db,
        github_id=2001,
        github_login="bob",
        github_avatar_url="https://example.com/bob.png",
        encrypted_token="tok_original",
    )

    updated = await user_crud.create_or_update_user(
        test_db,
        github_id=2001,
        github_login="bob-renamed",
        github_avatar_url="https://example.com/bob2.png",
        encrypted_token="tok_new",
    )

    assert updated.github_login == "bob-renamed"
    assert updated.github_avatar_url == "https://example.com/bob2.png"
    assert updated.encrypted_token == "tok_new"


async def test_create_or_update_user_does_not_overwrite_token_when_none(
    test_db: AsyncSession,
) -> None:
    """Passing encrypted_token=None on update leaves the existing token unchanged."""
    await user_crud.create_or_update_user(
        test_db,
        github_id=3001,
        github_login="carol",
        github_avatar_url=None,
        encrypted_token="tok_keep_me",
    )

    updated = await user_crud.create_or_update_user(
        test_db,
        github_id=3001,
        github_login="carol",
        github_avatar_url=None,
        encrypted_token=None,  # should NOT overwrite
    )

    assert updated.encrypted_token == "tok_keep_me"


async def test_get_user_by_github_id_returns_created_user(test_db: AsyncSession) -> None:
    """get_user_by_github_id returns the user after creation."""
    await user_crud.create_or_update_user(
        test_db,
        github_id=4001,
        github_login="dave",
        github_avatar_url=None,
        encrypted_token=None,
    )

    user = await user_crud.get_user_by_github_id(test_db, 4001)

    assert user is not None
    assert user.github_login == "dave"


async def test_get_user_by_id_returns_created_user(test_db: AsyncSession) -> None:
    """get_user_by_id returns the user after creation."""
    created = await user_crud.create_or_update_user(
        test_db,
        github_id=5001,
        github_login="eve",
        github_avatar_url=None,
        encrypted_token=None,
    )

    user = await user_crud.get_user_by_id(test_db, created.id)

    assert user is not None
    assert user.github_id == 5001


async def test_create_or_update_user_with_null_avatar(test_db: AsyncSession) -> None:
    """Creates a user with no avatar URL (nullable field)."""
    user = await user_crud.create_or_update_user(
        test_db,
        github_id=6001,
        github_login="frank",
        github_avatar_url=None,
        encrypted_token=None,
    )

    assert user.github_avatar_url is None
    assert user.encrypted_token is None


async def test_create_or_update_user_updates_avatar_to_none(test_db: AsyncSession) -> None:
    """Avatar URL can be cleared on update."""
    await user_crud.create_or_update_user(
        test_db,
        github_id=7001,
        github_login="grace",
        github_avatar_url="https://example.com/grace.png",
        encrypted_token=None,
    )

    updated = await user_crud.create_or_update_user(
        test_db,
        github_id=7001,
        github_login="grace",
        github_avatar_url=None,
        encrypted_token=None,
    )

    assert updated.github_avatar_url is None


async def test_create_or_update_user_different_users_isolated(test_db: AsyncSession) -> None:
    """Two different GitHub IDs result in two independent user records."""
    user_a = await user_crud.create_or_update_user(
        test_db,
        github_id=8001,
        github_login="heidi",
        github_avatar_url=None,
        encrypted_token=None,
    )
    user_b = await user_crud.create_or_update_user(
        test_db,
        github_id=8002,
        github_login="ivan",
        github_avatar_url=None,
        encrypted_token=None,
    )

    assert user_a.id != user_b.id
    assert user_a.github_id != user_b.github_id

    fetched_a = await user_crud.get_user_by_github_id(test_db, 8001)
    fetched_b = await user_crud.get_user_by_github_id(test_db, 8002)

    assert fetched_a is not None
    assert fetched_b is not None
    assert fetched_a.github_login == "heidi"
    assert fetched_b.github_login == "ivan"
