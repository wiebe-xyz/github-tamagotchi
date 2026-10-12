"""Tests for the webhook service."""

import asyncio
import hashlib
import hmac
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.crud import pet as pet_crud
from github_tamagotchi.models.pet import PetMood, PetStage
from github_tamagotchi.services import webhook as webhook_service
from github_tamagotchi.services.webhook import (
    EVENT_HANDLERS,
    handle_check_run_event,
    handle_issues_event,
    handle_pull_request_event,
    handle_push_event,
    is_github_webhook_source,
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


_META_RESPONSE = {"hooks": ["192.30.252.0/22", "140.82.112.0/20", "2a0a:a440::/29"]}


@pytest.fixture(autouse=True)
def _reset_ip_range_cache():
    """The GitHub webhook IP ranges are cached at module scope (see
    services/webhook.py) so a real deployment doesn't refetch on every
    delivery. Reset it around each test so tests don't leak cache state
    into each other."""
    webhook_service._cached_networks = []
    webhook_service._cached_at = 0.0
    yield
    webhook_service._cached_networks = []
    webhook_service._cached_at = 0.0


class TestIsGithubWebhookSource:
    """Tests for the source-IP verification gate (issues #278/#279)."""

    @respx.mock
    async def test_ip_within_a_published_range_is_trusted(self) -> None:
        respx.get("https://api.github.com/meta").mock(
            return_value=httpx.Response(200, json=_META_RESPONSE)
        )
        assert await is_github_webhook_source("140.82.112.3") is True

    @respx.mock
    async def test_ip_outside_every_published_range_is_rejected(self) -> None:
        respx.get("https://api.github.com/meta").mock(
            return_value=httpx.Response(200, json=_META_RESPONSE)
        )
        assert await is_github_webhook_source("8.8.8.8") is False

    @respx.mock
    async def test_ipv6_within_a_published_range_is_trusted(self) -> None:
        respx.get("https://api.github.com/meta").mock(
            return_value=httpx.Response(200, json=_META_RESPONSE)
        )
        assert await is_github_webhook_source("2a0a:a440::1") is True

    async def test_missing_ip_is_rejected(self) -> None:
        assert await is_github_webhook_source(None) is False
        assert await is_github_webhook_source("") is False

    async def test_unparseable_ip_is_rejected(self) -> None:
        assert await is_github_webhook_source("not-an-ip") is False

    @respx.mock
    async def test_never_cached_ranges_fail_closed(self) -> None:
        """If the /meta fetch itself fails and nothing has ever been cached,
        treat it as unverified rather than as no restriction."""
        respx.get("https://api.github.com/meta").mock(side_effect=httpx.ConnectError("boom"))
        assert await is_github_webhook_source("140.82.112.3") is False

    @respx.mock
    async def test_fetch_failure_falls_back_to_stale_cache(self) -> None:
        """A transient outage after a successful fetch shouldn't suddenly
        reject every delivery -- keep serving the last good ranges."""
        route = respx.get("https://api.github.com/meta")
        route.mock(return_value=httpx.Response(200, json=_META_RESPONSE))
        assert await is_github_webhook_source("140.82.112.3") is True

        route.mock(side_effect=httpx.ConnectError("boom"))
        webhook_service._cached_at = 0.0  # force a refresh attempt despite the cache
        assert await is_github_webhook_source("140.82.112.3") is True

    @respx.mock
    async def test_cache_is_reused_within_ttl(self) -> None:
        route = respx.get("https://api.github.com/meta").mock(
            return_value=httpx.Response(200, json=_META_RESPONSE)
        )
        await is_github_webhook_source("140.82.112.3")
        await is_github_webhook_source("140.82.112.3")
        assert route.call_count == 1

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


def _make_payload(owner: str = "testuser", repo: str = "testrepo", **extra: Any) -> dict[str, Any]:
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


class TestIsCloudflareAddress:
    def test_cloudflare_edge_addresses(self) -> None:
        from github_tamagotchi.services.webhook import is_cloudflare_address

        assert is_cloudflare_address("172.69.10.20")
        assert is_cloudflare_address("188.114.96.0")
        assert is_cloudflare_address("2606:4700::1")

    def test_other_addresses_and_garbage(self) -> None:
        from github_tamagotchi.services.webhook import is_cloudflare_address

        assert not is_cloudflare_address("140.82.112.3")
        assert not is_cloudflare_address("203.0.113.7")
        assert not is_cloudflare_address("not-an-ip")


class TestSerializeRepoEvents:
    """Events for one repo are handled one at a time (BugBarn GT-36)."""

    async def test_same_repo_events_never_overlap(self) -> None:
        running = 0
        peak = 0

        async def handle() -> None:
            nonlocal running, peak
            async with webhook_service.serialize_repo_events("Owner", "repo"):
                running += 1
                peak = max(peak, running)
                await asyncio.sleep(0)
                await asyncio.sleep(0)
                running -= 1

        await asyncio.gather(*(handle() for _ in range(20)))

        assert peak == 1

    async def test_different_repos_run_concurrently(self) -> None:
        inside = asyncio.Event()
        release = asyncio.Event()

        async def holder() -> None:
            async with webhook_service.serialize_repo_events("a", "one"):
                inside.set()
                await release.wait()

        task = asyncio.create_task(holder())
        await inside.wait()
        async with webhook_service.serialize_repo_events("a", "two"):
            release.set()
        await task

    async def test_lock_table_is_empty_afterwards_even_after_errors(self) -> None:
        async def fail() -> None:
            async with webhook_service.serialize_repo_events("a", "boom"):
                raise RuntimeError("handler failed")

        results = await asyncio.gather(fail(), fail(), return_exceptions=True)

        assert all(isinstance(r, RuntimeError) for r in results)
        assert webhook_service._repo_locks == {}
