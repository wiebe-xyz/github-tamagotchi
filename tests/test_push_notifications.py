"""Tests for push notification services."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.models.pet import Pet, PetMood
from github_tamagotchi.models.push_subscription import PushSubscription
from github_tamagotchi.services.push_notifications import (
    notify_dying_and_dead_pets,
    notify_unhappy_pets,
)


@pytest.fixture
async def hungry_pet_with_sub(test_db: AsyncSession) -> tuple[Pet, PushSubscription]:
    """Create a hungry pet with a push subscription."""
    pet = Pet(
        repo_owner="owner",
        repo_name="repo",
        name="Hungry",
        health=30,
        experience=0,
        stage="egg",
        mood=PetMood.HUNGRY.value,
    )
    test_db.add(pet)
    await test_db.flush()

    sub = PushSubscription(
        pet_id=pet.id,
        endpoint="https://push.example.com/sub1",
        p256dh="key1",
        auth="auth1",
    )
    test_db.add(sub)
    await test_db.commit()
    return pet, sub


@pytest.fixture
async def dying_pet_with_sub(test_db: AsyncSession) -> tuple[Pet, PushSubscription]:
    """Create a pet in grace period with a push subscription."""
    pet = Pet(
        repo_owner="owner",
        repo_name="dying-repo",
        name="DyingPet",
        health=0,
        experience=100,
        stage="baby",
        mood=PetMood.SICK.value,
        grace_period_started=datetime.now(UTC) - timedelta(days=2),
    )
    test_db.add(pet)
    await test_db.flush()

    sub = PushSubscription(
        pet_id=pet.id,
        endpoint="https://push.example.com/sub2",
        p256dh="key2",
        auth="auth2",
    )
    test_db.add(sub)
    await test_db.commit()
    return pet, sub


@pytest.fixture
async def dead_pet_with_sub(test_db: AsyncSession) -> tuple[Pet, PushSubscription]:
    """Create a recently dead pet with a push subscription."""
    pet = Pet(
        repo_owner="owner",
        repo_name="dead-repo",
        name="DeadPet",
        health=0,
        experience=50,
        stage="egg",
        mood=PetMood.SICK.value,
        is_dead=True,
        died_at=datetime.now(UTC) - timedelta(hours=1),
        cause_of_death="neglect",
    )
    test_db.add(pet)
    await test_db.flush()

    sub = PushSubscription(
        pet_id=pet.id,
        endpoint="https://push.example.com/sub3",
        p256dh="key3",
        auth="auth3",
    )
    test_db.add(sub)
    await test_db.commit()
    return pet, sub


@patch("github_tamagotchi.services.push_notifications.settings")
@patch("github_tamagotchi.services.push_notifications._send_to_subscription")
async def test_notify_unhappy_pets_sends_for_hungry(
    mock_send: AsyncMock,
    mock_settings: AsyncMock,
    test_db: AsyncSession,
    hungry_pet_with_sub: tuple[Pet, PushSubscription],
) -> None:
    mock_settings.vapid_private_key = "fake-key"
    mock_send.return_value = True

    sent = await notify_unhappy_pets(test_db)
    assert sent == 1
    mock_send.assert_called_once()

    payload = mock_send.call_args[0][1]
    assert "Hungry" in payload["title"]
    assert "hasn't been fed" in payload["body"]


@patch("github_tamagotchi.services.push_notifications.settings")
@patch("github_tamagotchi.services.push_notifications._send_to_subscription")
async def test_notify_unhappy_pets_skips_without_vapid(
    mock_send: AsyncMock,
    mock_settings: AsyncMock,
    test_db: AsyncSession,
    hungry_pet_with_sub: tuple[Pet, PushSubscription],
) -> None:
    mock_settings.vapid_private_key = None
    sent = await notify_unhappy_pets(test_db)
    assert sent == 0
    mock_send.assert_not_called()


@patch("github_tamagotchi.services.push_notifications.settings")
@patch("github_tamagotchi.services.push_notifications._send_to_subscription")
async def test_notify_unhappy_pets_cooldown(
    mock_send: AsyncMock,
    mock_settings: AsyncMock,
    test_db: AsyncSession,
    hungry_pet_with_sub: tuple[Pet, PushSubscription],
) -> None:
    mock_settings.vapid_private_key = "fake-key"
    mock_send.return_value = True

    # First call sends
    sent = await notify_unhappy_pets(test_db)
    assert sent == 1

    # Second call should be cooled down
    sent = await notify_unhappy_pets(test_db)
    assert sent == 0


@patch("github_tamagotchi.services.push_notifications.settings")
@patch("github_tamagotchi.services.push_notifications._send_to_subscription")
async def test_notify_dying_pets_grace_period(
    mock_send: AsyncMock,
    mock_settings: AsyncMock,
    test_db: AsyncSession,
    dying_pet_with_sub: tuple[Pet, PushSubscription],
) -> None:
    mock_settings.vapid_private_key = "fake-key"
    mock_send.return_value = True

    sent = await notify_dying_and_dead_pets(test_db)
    assert sent == 1

    payload = mock_send.call_args[0][1]
    assert "dying" in payload["title"].lower()
    assert "DyingPet" in payload["body"]


@patch("github_tamagotchi.services.push_notifications.settings")
@patch("github_tamagotchi.services.push_notifications._send_to_subscription")
async def test_notify_dead_pets(
    mock_send: AsyncMock,
    mock_settings: AsyncMock,
    test_db: AsyncSession,
    dead_pet_with_sub: tuple[Pet, PushSubscription],
) -> None:
    mock_settings.vapid_private_key = "fake-key"
    mock_send.return_value = True

    sent = await notify_dying_and_dead_pets(test_db)
    assert sent == 1

    payload = mock_send.call_args[0][1]
    assert "died" in payload["title"].lower()
    assert "neglect" in payload["body"]


@patch("github_tamagotchi.services.push_notifications.settings")
@patch("github_tamagotchi.services.push_notifications._send_to_subscription")
async def test_notify_removes_expired_subscription(
    mock_send: AsyncMock,
    mock_settings: AsyncMock,
    test_db: AsyncSession,
    hungry_pet_with_sub: tuple[Pet, PushSubscription],
) -> None:
    mock_settings.vapid_private_key = "fake-key"
    mock_send.return_value = None  # Expired subscription

    sent = await notify_unhappy_pets(test_db)
    assert sent == 0

    # Subscription should be deleted
    _, sub = hungry_pet_with_sub
    from sqlalchemy import select

    result = await test_db.execute(
        select(PushSubscription).where(PushSubscription.id == sub.id)
    )
    assert result.scalar_one_or_none() is None
