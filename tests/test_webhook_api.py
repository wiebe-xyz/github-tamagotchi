"""Tests for the webhook API endpoint."""

import hashlib
import hmac
import json
from unittest.mock import patch

from httpx import AsyncClient


def _sign_payload(payload: dict[str, object], secret: str) -> tuple[bytes, str]:
    """Helper to create a signed payload and its signature."""
    body = json.dumps(payload).encode()
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return body, f"sha256={digest}"


WEBHOOK_SECRET = "test-webhook-secret"


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


class TestWebhookSignatureValidation:
    """Tests for webhook signature verification at the API level."""

    async def test_valid_signature_accepted(self, async_client: AsyncClient) -> None:
        """Request with valid signature should be accepted."""
        payload = {"repository": {"name": "testrepo", "owner": {"login": "testuser"}}}
        body, signature = _sign_payload(payload, WEBHOOK_SECRET)

        with patch(
            "github_tamagotchi.api.routes.settings"
        ) as mock_settings:
            mock_settings.github_webhook_secret = WEBHOOK_SECRET

            response = await async_client.post(
                "/api/v1/webhooks/github",
                content=body,
                headers={
                    "X-GitHub-Event": "ping",
                    "X-Hub-Signature-256": signature,
                    "Content-Type": "application/json",
                },
            )
            assert response.status_code == 200

    async def test_invalid_signature_rejected(self, async_client: AsyncClient) -> None:
        """Request with invalid signature should return 401."""
        with patch(
            "github_tamagotchi.api.routes.settings"
        ) as mock_settings:
            mock_settings.github_webhook_secret = WEBHOOK_SECRET

            response = await async_client.post(
                "/api/v1/webhooks/github",
                content=b'{"test": true}',
                headers={
                    "X-GitHub-Event": "push",
                    "X-Hub-Signature-256": "sha256=invalid",
                    "Content-Type": "application/json",
                },
            )
            assert response.status_code == 401
            assert "Invalid webhook signature" in response.json()["detail"]

    async def test_missing_signature_rejected(self, async_client: AsyncClient) -> None:
        """Request without signature when secret is set should return 401."""
        with patch(
            "github_tamagotchi.api.routes.settings"
        ) as mock_settings:
            mock_settings.github_webhook_secret = WEBHOOK_SECRET

            response = await async_client.post(
                "/api/v1/webhooks/github",
                content=b'{"test": true}',
                headers={
                    "X-GitHub-Event": "push",
                    "Content-Type": "application/json",
                },
            )
            assert response.status_code == 401

    async def test_no_secret_configured_accepts_all(self, async_client: AsyncClient) -> None:
        """When no secret is configured, all requests should be accepted."""
        response = await async_client.post(
            "/api/v1/webhooks/github",
            content=b"{}",
            headers={"X-GitHub-Event": "ping"},
        )
        assert response.status_code == 200

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
