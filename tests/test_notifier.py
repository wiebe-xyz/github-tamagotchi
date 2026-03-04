"""Tests for the notification channels."""

from collections.abc import Iterator
from unittest.mock import patch

import httpx
import pytest
import respx

from github_tamagotchi.services.notifier import (
    _build_discord_payload,
    _build_slack_payload,
    send_alert_notification,
    send_resolved_notification,
)


class TestSlackPayload:
    def test_builds_payload_with_details(self) -> None:
        payload = _build_slack_payload(
            severity="critical",
            alert_type="poll_failed",
            message="Poll has failed 3 times.",
            details="Threshold: 2",
        )
        assert "poll_failed" in payload["text"]
        assert "CRITICAL" in payload["text"]
        assert "Threshold: 2" in payload["text"]

    def test_builds_payload_without_details(self) -> None:
        payload = _build_slack_payload(
            severity="warning",
            alert_type="high_error_rate",
            message="Error rate is high.",
            details=None,
        )
        assert "high_error_rate" in payload["text"]
        assert "```" not in payload["text"]


class TestDiscordPayload:
    def test_builds_embed_with_critical_color(self) -> None:
        payload = _build_discord_payload(
            severity="critical",
            alert_type="poll_failed",
            message="Poll has failed.",
            details=None,
        )
        assert payload["embeds"][0]["color"] == 0xFF0000

    def test_builds_embed_with_warning_color(self) -> None:
        payload = _build_discord_payload(
            severity="warning",
            alert_type="high_error_rate",
            message="Error rate high.",
            details="Some details",
        )
        assert payload["embeds"][0]["color"] == 0xFFA500
        assert "Some details" in payload["embeds"][0]["description"]


@pytest.fixture
def _enable_alerting() -> Iterator[None]:
    with patch("github_tamagotchi.services.notifier.settings") as mock_settings:
        mock_settings.alerting_enabled = True
        mock_settings.alert_slack_webhook = "https://hooks.slack.test/webhook"
        mock_settings.alert_discord_webhook = None
        yield


@pytest.fixture
def _disable_alerting() -> Iterator[None]:
    with patch("github_tamagotchi.services.notifier.settings") as mock_settings:
        mock_settings.alerting_enabled = False
        mock_settings.alert_slack_webhook = None
        mock_settings.alert_discord_webhook = None
        yield


@respx.mock
@pytest.mark.usefixtures("_enable_alerting")
async def test_send_alert_notification_slack() -> None:
    respx.post("https://hooks.slack.test/webhook").mock(
        return_value=httpx.Response(200)
    )
    result = await send_alert_notification(
        severity="critical",
        alert_type="poll_failed",
        message="Test message",
    )
    assert result is True


@respx.mock
@pytest.mark.usefixtures("_enable_alerting")
async def test_send_alert_notification_slack_failure() -> None:
    respx.post("https://hooks.slack.test/webhook").mock(
        return_value=httpx.Response(500)
    )
    result = await send_alert_notification(
        severity="critical",
        alert_type="poll_failed",
        message="Test message",
    )
    assert result is False


@pytest.mark.usefixtures("_disable_alerting")
async def test_send_alert_disabled() -> None:
    result = await send_alert_notification(
        severity="critical",
        alert_type="poll_failed",
        message="Test message",
    )
    assert result is False


@respx.mock
@pytest.mark.usefixtures("_enable_alerting")
async def test_send_resolved_notification() -> None:
    respx.post("https://hooks.slack.test/webhook").mock(
        return_value=httpx.Response(200)
    )
    result = await send_resolved_notification(
        alert_type="poll_failed",
        message="Poll recovered.",
    )
    assert result is True


@pytest.mark.usefixtures("_disable_alerting")
async def test_send_resolved_disabled() -> None:
    result = await send_resolved_notification(
        alert_type="poll_failed",
        message="Poll recovered.",
    )
    assert result is False
