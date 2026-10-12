"""Tests for the webhook API endpoint."""

from unittest.mock import patch

import pytest
from httpx import AsyncClient

_IS_GITHUB_SOURCE = "github_tamagotchi.api.routes.v1.webhooks.is_github_webhook_source"


@pytest.fixture(autouse=True)
def _trusted_source():
    """Most tests here exercise event-processing logic, not the source-IP
    gate itself -- default every request to a verified GitHub source so
    they don't each need their own patch. TestWebhookSourceVerification
    overrides this per-test to exercise the gate directly."""
    with patch(_IS_GITHUB_SOURCE, return_value=True) as mock:
        yield mock


class TestWebhookEndpoint:
    """Tests for POST /api/v1/webhooks/github."""

    async def test_ping_event(self, async_client: AsyncClient) -> None:
        """Ping event should return pong."""
        response = await async_client.post(
            "/api/v1/webhooks/github",
            content=b"{}",
            headers={"X-GitHub-Event": "ping"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["message"] == "pong"

    async def test_missing_event_header(self, async_client: AsyncClient) -> None:
        """Missing X-GitHub-Event header should return 400."""
        response = await async_client.post(
            "/api/v1/webhooks/github",
            content=b"{}",
        )
        assert response.status_code == 400
        assert "Missing X-GitHub-Event" in response.json()["detail"]

    async def test_unhandled_event_type(self, async_client: AsyncClient) -> None:
        """Unhandled event type should return 200 with ignored status."""
        response = await async_client.post(
            "/api/v1/webhooks/github",
            content=b"{}",
            headers={"X-GitHub-Event": "star"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ignored"

    async def test_push_event_creates_pet_update(self, async_client: AsyncClient) -> None:
        """Push event should update an existing pet."""
        # Create a pet first
        await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "testuser", "repo_name": "testrepo", "name": "Buddy"},
        )

        payload = {
            "repository": {
                "name": "testrepo",
                "owner": {"login": "testuser"},
            },
        }

        response = await async_client.post(
            "/api/v1/webhooks/github",
            json=payload,
            headers={"X-GitHub-Event": "push"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "processed"
        assert "push processed" in data["message"]

        # Verify pet was updated
        pet_response = await async_client.get("/api/v1/pets/testuser/testrepo")
        pet_data = pet_response.json()
        assert pet_data["mood"] == "happy"
        assert pet_data["last_fed_at"] is not None

    async def test_pr_event_updates_mood(self, async_client: AsyncClient) -> None:
        """Pull request event should update pet mood."""
        await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "testuser", "repo_name": "testrepo", "name": "Buddy"},
        )

        payload = {
            "action": "opened",
            "repository": {
                "name": "testrepo",
                "owner": {"login": "testuser"},
            },
        }

        response = await async_client.post(
            "/api/v1/webhooks/github",
            json=payload,
            headers={"X-GitHub-Event": "pull_request"},
        )
        assert response.status_code == 200

        pet_response = await async_client.get("/api/v1/pets/testuser/testrepo")
        assert pet_response.json()["mood"] == "worried"

    async def test_issue_event_updates_mood(self, async_client: AsyncClient) -> None:
        """Issues event should update pet mood."""
        await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "testuser", "repo_name": "testrepo", "name": "Buddy"},
        )

        payload = {
            "action": "opened",
            "repository": {
                "name": "testrepo",
                "owner": {"login": "testuser"},
            },
        }

        response = await async_client.post(
            "/api/v1/webhooks/github",
            json=payload,
            headers={"X-GitHub-Event": "issues"},
        )
        assert response.status_code == 200

        pet_response = await async_client.get("/api/v1/pets/testuser/testrepo")
        assert pet_response.json()["mood"] == "lonely"

    async def test_check_run_event_updates_health(self, async_client: AsyncClient) -> None:
        """Check run success should update pet health and mood."""
        await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "testuser", "repo_name": "testrepo", "name": "Buddy"},
        )

        payload = {
            "action": "completed",
            "check_run": {"conclusion": "success"},
            "repository": {
                "name": "testrepo",
                "owner": {"login": "testuser"},
            },
        }

        response = await async_client.post(
            "/api/v1/webhooks/github",
            json=payload,
            headers={"X-GitHub-Event": "check_run"},
        )
        assert response.status_code == 200

        pet_response = await async_client.get("/api/v1/pets/testuser/testrepo")
        assert pet_response.json()["mood"] == "dancing"


class TestWebhookSourceVerification:
    """Tests for the GitHub-source-IP gate at the API level (issues #278/#279:
    no shared secret required, but the request must actually come from GitHub)."""

    async def test_untrusted_source_rejected(self, async_client: AsyncClient) -> None:
        """A request that doesn't verify as coming from GitHub is rejected,
        even for an otherwise-harmless event like ping."""
        with patch(_IS_GITHUB_SOURCE, return_value=False):
            response = await async_client.post(
                "/api/v1/webhooks/github",
                content=b"{}",
                headers={"X-GitHub-Event": "ping"},
            )
            assert response.status_code == 403
            assert "does not originate from GitHub" in response.json()["detail"]

    async def test_trusted_source_accepted(self, async_client: AsyncClient) -> None:
        """A request verified as coming from GitHub is processed normally."""
        with patch(_IS_GITHUB_SOURCE, return_value=True):
            response = await async_client.post(
                "/api/v1/webhooks/github",
                content=b"{}",
                headers={"X-GitHub-Event": "ping"},
            )
            assert response.status_code == 200

    async def test_source_check_receives_last_forwarded_hop(
        self, async_client: AsyncClient
    ) -> None:
        """The gate is checked against the last X-Forwarded-For entry (the
        one our own reverse proxy appended), not an earlier, client-supplied
        one -- a client claiming to be some other IP shouldn't be trusted."""
        with patch(_IS_GITHUB_SOURCE, return_value=True) as mock:
            await async_client.post(
                "/api/v1/webhooks/github",
                content=b"{}",
                headers={
                    "X-GitHub-Event": "ping",
                    "X-Forwarded-For": "1.2.3.4, 140.82.112.3",
                },
            )
            mock.assert_awaited_once_with("140.82.112.3")

    async def test_source_check_skips_cloudflare_edge_hop(self, async_client: AsyncClient) -> None:
        """Behind Cloudflare then Traefik, the last hop is a Cloudflare edge
        address. The gate must be checked against the entry before it, which
        is the address Cloudflare saw."""
        with patch(_IS_GITHUB_SOURCE, return_value=True) as mock:
            await async_client.post(
                "/api/v1/webhooks/github",
                content=b"{}",
                headers={
                    "X-GitHub-Event": "ping",
                    "X-Forwarded-For": "9.9.9.9, 140.82.112.3, 172.69.10.20",
                },
            )
            mock.assert_awaited_once_with("140.82.112.3")

    async def test_spoofed_github_ip_before_real_client_not_trusted(
        self, async_client: AsyncClient
    ) -> None:
        """A client that prepends a GitHub address still gets checked as its
        own address, which Cloudflare appended after the spoofed entry."""
        with patch(_IS_GITHUB_SOURCE, return_value=False) as mock:
            response = await async_client.post(
                "/api/v1/webhooks/github",
                content=b"{}",
                headers={
                    "X-GitHub-Event": "ping",
                    "X-Forwarded-For": "140.82.112.3, 203.0.113.7, 172.69.10.20",
                },
            )
            mock.assert_awaited_once_with("203.0.113.7")
            assert response.status_code == 403

    async def test_forwarded_chain_of_only_cloudflare_hops_rejected(
        self, async_client: AsyncClient
    ) -> None:
        with patch(_IS_GITHUB_SOURCE, return_value=False) as mock:
            response = await async_client.post(
                "/api/v1/webhooks/github",
                content=b"{}",
                headers={
                    "X-GitHub-Event": "ping",
                    "X-Forwarded-For": "172.69.10.20, 104.16.1.1",
                },
            )
            mock.assert_awaited_once_with(None)
            assert response.status_code == 403

    async def test_cf_connecting_ip_used_when_peer_is_cloudflare(
        self, async_client: AsyncClient
    ) -> None:
        """Traefik drops Cloudflare's forwarded chain, so the app only sees the
        edge address in X-Forwarded-For; the client is in Cf-Connecting-Ip."""
        with patch(_IS_GITHUB_SOURCE, return_value=True) as mock:
            await async_client.post(
                "/api/v1/webhooks/github",
                content=b"{}",
                headers={
                    "X-GitHub-Event": "ping",
                    "X-Forwarded-For": "162.158.159.13",
                    "Cf-Connecting-Ip": "140.82.115.33",
                },
            )
            mock.assert_awaited_once_with("140.82.115.33")

    async def test_forged_cf_connecting_ip_ignored_when_peer_not_cloudflare(
        self, async_client: AsyncClient
    ) -> None:
        """A request that bypasses Cloudflare cannot claim a GitHub address."""
        with patch(_IS_GITHUB_SOURCE, return_value=False) as mock:
            response = await async_client.post(
                "/api/v1/webhooks/github",
                content=b"{}",
                headers={
                    "X-GitHub-Event": "ping",
                    "X-Forwarded-For": "203.0.113.7",
                    "Cf-Connecting-Ip": "140.82.115.33",
                },
            )
            mock.assert_awaited_once_with("203.0.113.7")
            assert response.status_code == 403

    async def test_push_event_for_unknown_repo(self, async_client: AsyncClient) -> None:
        """Push for non-existent pet should return processed with message."""
        payload = {
            "repository": {
                "name": "nonexistent",
                "owner": {"login": "nobody"},
            },
        }

        response = await async_client.post(
            "/api/v1/webhooks/github",
            json=payload,
            headers={"X-GitHub-Event": "push"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "processed"
        assert "no pet found" in data["message"]
