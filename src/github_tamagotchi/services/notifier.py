"""Notification channels for sending alerts."""

from typing import Any

import httpx
import structlog

from github_tamagotchi.core.config import settings
from github_tamagotchi.models.alert import AlertSeverity

logger = structlog.get_logger()

SEVERITY_EMOJI = {
    AlertSeverity.CRITICAL: "\U0001f6a8",  # rotating light
    AlertSeverity.WARNING: "\u26a0\ufe0f",  # warning sign
}


def _build_slack_payload(
    severity: str,
    alert_type: str,
    message: str,
    details: str | None,
) -> dict[str, Any]:
    """Build a Slack-compatible webhook payload."""
    emoji = SEVERITY_EMOJI.get(AlertSeverity(severity), "\u2139\ufe0f")
    severity_label = severity.upper()

    text = f"{emoji} *GitHub Tamagotchi Alert*\n\n*{alert_type}* ({severity_label})\n{message}"
    if details:
        text += f"\n\n```{details}```"

    return {"text": text}


def _build_discord_payload(
    severity: str,
    alert_type: str,
    message: str,
    details: str | None,
) -> dict[str, Any]:
    """Build a Discord-compatible webhook payload."""
    emoji = SEVERITY_EMOJI.get(AlertSeverity(severity), "\u2139\ufe0f")
    severity_label = severity.upper()

    description = message
    if details:
        description += f"\n```{details}```"

    color = 0xFF0000 if severity == AlertSeverity.CRITICAL else 0xFFA500

    return {
        "embeds": [
            {
                "title": f"{emoji} {alert_type} ({severity_label})",
                "description": description,
                "color": color,
            }
        ]
    }


async def send_alert_notification(
    severity: str,
    alert_type: str,
    message: str,
    details: str | None = None,
) -> bool:
    """Send alert to all configured notification channels.

    Returns True if at least one succeeded.
    """
    if not settings.alerting_enabled:
        return False

    sent = False

    async with httpx.AsyncClient(timeout=10.0) as client:
        if settings.alert_slack_webhook:
            try:
                payload = _build_slack_payload(severity, alert_type, message, details)
                resp = await client.post(settings.alert_slack_webhook, json=payload)
                resp.raise_for_status()
                sent = True
                logger.info("alert_sent_slack", alert_type=alert_type)
            except Exception as e:
                logger.error("alert_slack_failed", error=str(e), exc_info=True)

        if settings.alert_discord_webhook:
            try:
                payload = _build_discord_payload(severity, alert_type, message, details)
                resp = await client.post(settings.alert_discord_webhook, json=payload)
                resp.raise_for_status()
                sent = True
                logger.info("alert_sent_discord", alert_type=alert_type)
            except Exception as e:
                logger.error("alert_discord_failed", error=str(e), exc_info=True)

    return sent


async def send_resolved_notification(
    alert_type: str,
    message: str,
) -> bool:
    """Send a resolved notification to all configured channels."""
    if not settings.alerting_enabled:
        return False

    text = f"\u2705 *Resolved*: {alert_type}\n{message}"
    sent = False

    async with httpx.AsyncClient(timeout=10.0) as client:
        if settings.alert_slack_webhook:
            try:
                resp = await client.post(settings.alert_slack_webhook, json={"text": text})
                resp.raise_for_status()
                sent = True
            except Exception as e:
                logger.error("resolved_slack_failed", error=str(e), exc_info=True)

        if settings.alert_discord_webhook:
            try:
                payload = {
                    "embeds": [
                        {
                            "title": f"\u2705 Resolved: {alert_type}",
                            "description": message,
                            "color": 0x00FF00,
                        }
                    ]
                }
                resp = await client.post(settings.alert_discord_webhook, json=payload)
                resp.raise_for_status()
                sent = True
            except Exception as e:
                logger.error("resolved_discord_failed", error=str(e), exc_info=True)

    return sent
