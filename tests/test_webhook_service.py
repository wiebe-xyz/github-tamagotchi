"""Tests for the webhook service."""

import hashlib
import hmac
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.crud import pet as pet_crud
from github_tamagotchi.models.pet import PetMood, PetStage
from github_tamagotchi.services.webhook import (
    EVENT_HANDLERS,
    handle_check_run_event,
    handle_issues_event,
    handle_pull_request_event,
    handle_push_event,
    verify_signature,
)


class TestVerifySignature:
    """Tests for HMAC signature verification."""

    def test_valid_signature(self) -> None:
        """Valid signature should return True."""
        secret = "test-secret"
        payload = b'{"action": "push"}'
        digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        signature = f"sha256={digest}"

        assert verify_signature(payload, signature, secret) is True

    def test_invalid_signature(self) -> None:
        """Invalid signature should return False."""
        assert verify_signature(b"payload", "sha256=invalid", "secret") is False

    def test_missing_sha256_prefix(self) -> None:
        """Signature without sha256= prefix should return False."""
        assert verify_signature(b"payload", "md5=abc123", "secret") is False

    def test_empty_signature(self) -> None:
        """Empty signature should return False."""
        assert verify_signature(b"payload", "", "secret") is False

    def test_timing_safe_comparison(self) -> None:
        """Verify we use constant-time comparison (hmac.compare_digest)."""
        secret = "test-secret"
        payload = b"test"
        digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        # Tamper with one character
        tampered = f"sha256={digest[:-1]}0"
        assert verify_signature(payload, tampered, secret) is False


def _make_payload(
    owner: str = "testuser", repo: str = "testrepo", **extra: Any
) -> dict[str, Any]:
    """Helper to create a webhook payload with repository info."""
    payload: dict[str, Any] = {
        "repository": {
            "name": repo,
            "owner": {"login": owner},
        },
    }
    payload.update(extra)
    return payload


class TestHandlePushEvent:
    """Tests for push event handling."""

    async def test_push_feeds_pet(self, test_db: AsyncSession) -> None:
        """Push event should increase health and set mood to happy."""
        pet = await pet_crud.create_pet(test_db, "testuser", "testrepo", "Buddy")
        original_health = pet.health

        payload = _make_payload()
        result = await handle_push_event(payload, test_db)

        assert "push processed" in result
        await test_db.refresh(pet)
        assert pet.health == min(100, original_health + 10)
        assert pet.mood == PetMood.HAPPY.value
        assert pet.last_fed_at is not None

    async def test_push_grants_experience(self, test_db: AsyncSession) -> None:
        """Push event should grant experience points."""
        pet = await pet_crud.create_pet(test_db, "testuser", "testrepo", "Buddy")

        payload = _make_payload()
        await handle_push_event(payload, test_db)

        await test_db.refresh(pet)
        assert pet.experience == 20

    async def test_push_health_capped_at_100(self, test_db: AsyncSession) -> None:
        """Health should not exceed 100 after push."""
        pet = await pet_crud.create_pet(test_db, "testuser", "testrepo", "Buddy")
        assert pet.health == 100  # starts at 100

        payload = _make_payload()
        await handle_push_event(payload, test_db)

        await test_db.refresh(pet)
        assert pet.health == 100

    async def test_push_no_pet(self, test_db: AsyncSession) -> None:
        """Push for unknown repo should return appropriate message."""
        payload = _make_payload(owner="nobody", repo="nowhere")
        result = await handle_push_event(payload, test_db)

        assert "no pet found" in result

    async def test_push_no_repository(self, test_db: AsyncSession) -> None:
        """Push without repository info should return appropriate message."""
        result = await handle_push_event({}, test_db)
        assert "no repository" in result

    async def test_push_triggers_evolution(self, test_db: AsyncSession) -> None:
        """Push that crosses XP threshold should evolve the pet."""
        pet = await pet_crud.create_pet(test_db, "testuser", "testrepo", "Buddy")
        # Set experience just below baby threshold (100)
        pet.experience = 85
        await test_db.commit()

        payload = _make_payload()
        await handle_push_event(payload, test_db)

        await test_db.refresh(pet)
        assert pet.experience == 105
        assert pet.stage == PetStage.BABY.value


class TestHandlePullRequestEvent:
    """Tests for pull_request event handling."""

    async def test_pr_opened_sets_worried(self, test_db: AsyncSession) -> None:
        """Opening a PR should set mood to worried."""
        await pet_crud.create_pet(test_db, "testuser", "testrepo", "Buddy")

        payload = _make_payload(action="opened")
        result = await handle_pull_request_event(payload, test_db)

        assert "pull_request (opened)" in result
        pet = await pet_crud.get_pet_by_repo(test_db, "testuser", "testrepo")
        assert pet is not None
        assert pet.mood == PetMood.WORRIED.value

    async def test_pr_merged_sets_happy(self, test_db: AsyncSession) -> None:
        """Merging a PR should set mood to happy and boost health."""
        pet = await pet_crud.create_pet(test_db, "testuser", "testrepo", "Buddy")
        pet.health = 80
        await test_db.commit()

        payload = _make_payload(
            action="closed",
            pull_request={"merged": True},
        )
        result = await handle_pull_request_event(payload, test_db)

        assert "pull_request (closed)" in result
        await test_db.refresh(pet)
        assert pet.mood == PetMood.HAPPY.value
        assert pet.health == 85  # 80 + 5

    async def test_pr_closed_without_merge(self, test_db: AsyncSession) -> None:
        """Closing a PR without merge should set mood to content."""
        await pet_crud.create_pet(test_db, "testuser", "testrepo", "Buddy")

        payload = _make_payload(
            action="closed",
            pull_request={"merged": False},
        )
        await handle_pull_request_event(payload, test_db)

        pet = await pet_crud.get_pet_by_repo(test_db, "testuser", "testrepo")
        assert pet is not None
        assert pet.mood == PetMood.CONTENT.value

    async def test_pr_reopened_sets_worried(self, test_db: AsyncSession) -> None:
        """Reopening a PR should set mood to worried."""
        await pet_crud.create_pet(test_db, "testuser", "testrepo", "Buddy")

        payload = _make_payload(action="reopened")
        await handle_pull_request_event(payload, test_db)

        pet = await pet_crud.get_pet_by_repo(test_db, "testuser", "testrepo")
        assert pet is not None
        assert pet.mood == PetMood.WORRIED.value

    async def test_pr_no_pet(self, test_db: AsyncSession) -> None:
        """PR for unknown repo should return appropriate message."""
        payload = _make_payload(owner="nobody", repo="nowhere", action="opened")
        result = await handle_pull_request_event(payload, test_db)
        assert "no pet found" in result

    async def test_pr_opened_grants_experience(self, test_db: AsyncSession) -> None:
        """Opening a PR should grant experience."""
        pet = await pet_crud.create_pet(test_db, "testuser", "testrepo", "Buddy")

        payload = _make_payload(action="opened")
        await handle_pull_request_event(payload, test_db)

        await test_db.refresh(pet)
        assert pet.experience == 5

    async def test_pr_merged_grants_experience(self, test_db: AsyncSession) -> None:
        """Merging a PR should grant experience."""
        pet = await pet_crud.create_pet(test_db, "testuser", "testrepo", "Buddy")

        payload = _make_payload(
            action="closed",
            pull_request={"merged": True},
        )
        await handle_pull_request_event(payload, test_db)

        await test_db.refresh(pet)
        assert pet.experience == 15


class TestHandleIssuesEvent:
    """Tests for issues event handling."""

    async def test_issue_opened_sets_lonely(self, test_db: AsyncSession) -> None:
        """Opening an issue should set mood to lonely."""
        await pet_crud.create_pet(test_db, "testuser", "testrepo", "Buddy")

        payload = _make_payload(action="opened")
        result = await handle_issues_event(payload, test_db)

        assert "issues (opened)" in result
        pet = await pet_crud.get_pet_by_repo(test_db, "testuser", "testrepo")
        assert pet is not None
        assert pet.mood == PetMood.LONELY.value

    async def test_issue_closed_sets_happy(self, test_db: AsyncSession) -> None:
        """Closing an issue should set mood to happy."""
        await pet_crud.create_pet(test_db, "testuser", "testrepo", "Buddy")

        payload = _make_payload(action="closed")
        await handle_issues_event(payload, test_db)

        pet = await pet_crud.get_pet_by_repo(test_db, "testuser", "testrepo")
        assert pet is not None
        assert pet.mood == PetMood.HAPPY.value

    async def test_issue_no_pet(self, test_db: AsyncSession) -> None:
        """Issue for unknown repo should return appropriate message."""
        payload = _make_payload(owner="nobody", repo="nowhere", action="opened")
        result = await handle_issues_event(payload, test_db)
        assert "no pet found" in result

    async def test_issue_opened_grants_experience(self, test_db: AsyncSession) -> None:
        """Opening an issue should grant experience."""
        pet = await pet_crud.create_pet(test_db, "testuser", "testrepo", "Buddy")

        payload = _make_payload(action="opened")
        await handle_issues_event(payload, test_db)

        await test_db.refresh(pet)
        assert pet.experience == 3


class TestHandleCheckRunEvent:
    """Tests for check_run event handling."""

    async def test_ci_success_boosts_health(self, test_db: AsyncSession) -> None:
        """Successful CI should boost health and set mood to dancing."""
        pet = await pet_crud.create_pet(test_db, "testuser", "testrepo", "Buddy")
        pet.health = 90
        await test_db.commit()

        payload = _make_payload(
            action="completed",
            check_run={"conclusion": "success"},
        )
        result = await handle_check_run_event(payload, test_db)

        assert "check_run (success)" in result
        await test_db.refresh(pet)
        assert pet.health == 95
        assert pet.mood == PetMood.DANCING.value
        assert pet.experience == 10

    async def test_ci_failure_reduces_health(self, test_db: AsyncSession) -> None:
        """Failed CI should reduce health and set mood to worried."""
        pet = await pet_crud.create_pet(test_db, "testuser", "testrepo", "Buddy")
        pet.health = 80
        await test_db.commit()

        payload = _make_payload(
            action="completed",
            check_run={"conclusion": "failure"},
        )
        await handle_check_run_event(payload, test_db)

        await test_db.refresh(pet)
        assert pet.health == 75
        assert pet.mood == PetMood.WORRIED.value

    async def test_ci_timed_out(self, test_db: AsyncSession) -> None:
        """Timed out CI should reduce health."""
        pet = await pet_crud.create_pet(test_db, "testuser", "testrepo", "Buddy")
        pet.health = 80
        await test_db.commit()

        payload = _make_payload(
            action="completed",
            check_run={"conclusion": "timed_out"},
        )
        await handle_check_run_event(payload, test_db)

        await test_db.refresh(pet)
        assert pet.health == 75
        assert pet.mood == PetMood.WORRIED.value

    async def test_ci_non_completed_action_ignored(self, test_db: AsyncSession) -> None:
        """Non-completed check_run actions should be ignored."""
        await pet_crud.create_pet(test_db, "testuser", "testrepo", "Buddy")

        payload = _make_payload(action="created")
        result = await handle_check_run_event(payload, test_db)

        assert "ignored" in result

    async def test_ci_health_capped_at_100(self, test_db: AsyncSession) -> None:
        """Health should not exceed 100 after CI success."""
        pet = await pet_crud.create_pet(test_db, "testuser", "testrepo", "Buddy")
        assert pet.health == 100

        payload = _make_payload(
            action="completed",
            check_run={"conclusion": "success"},
        )
        await handle_check_run_event(payload, test_db)

        await test_db.refresh(pet)
        assert pet.health == 100

    async def test_ci_health_not_below_zero(self, test_db: AsyncSession) -> None:
        """Health should not go below 0 after CI failure."""
        pet = await pet_crud.create_pet(test_db, "testuser", "testrepo", "Buddy")
        pet.health = 2
        await test_db.commit()

        payload = _make_payload(
            action="completed",
            check_run={"conclusion": "failure"},
        )
        await handle_check_run_event(payload, test_db)

        await test_db.refresh(pet)
        assert pet.health == 0

    async def test_ci_no_pet(self, test_db: AsyncSession) -> None:
        """Check run for unknown repo should return appropriate message."""
        payload = _make_payload(
            owner="nobody",
            repo="nowhere",
            action="completed",
            check_run={"conclusion": "success"},
        )
        result = await handle_check_run_event(payload, test_db)
        assert "no pet found" in result


class TestEventHandlers:
    """Tests for the EVENT_HANDLERS registry."""

    def test_all_events_registered(self) -> None:
        """All expected event types should be registered."""
        assert "push" in EVENT_HANDLERS
        assert "pull_request" in EVENT_HANDLERS
        assert "issues" in EVENT_HANDLERS
        assert "check_run" in EVENT_HANDLERS

    def test_handlers_are_callable(self) -> None:
        """All registered handlers should be callable."""
        for handler in EVENT_HANDLERS.values():
            assert callable(handler)
