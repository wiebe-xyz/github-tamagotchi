"""Web push notification service for unhappy pet alerts."""

import asyncio
import base64
import json
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any

import structlog
from pywebpush import WebPushException, webpush
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.core.config import settings
from github_tamagotchi.models.pet import Pet, PetMood
from github_tamagotchi.models.push_subscription import PushSubscription

logger = structlog.get_logger()

# Minimum hours between notifications per subscription per pet
NOTIFY_COOLDOWN_HOURS = 4

MOOD_MESSAGES: dict[str, str] = {
    PetMood.HUNGRY: "hasn't been fed — push some commits before it starves!",
    PetMood.WORRIED: "is anxious about a long-open PR. Can you close it?",
    PetMood.LONELY: "feels ignored. That old issue needs some attention.",
    PetMood.SICK: "is ill from stale dependencies. Time for an update!",
}

MOOD_EMOJI: dict[str, str] = {
    PetMood.HUNGRY: "🍖",
    PetMood.WORRIED: "😟",
    PetMood.LONELY: "😢",
    PetMood.SICK: "🤒",
}


def get_vapid_public_key() -> str | None:
    """Return the base64url-encoded uncompressed EC public key for the frontend."""
    if settings.vapid_public_key:
        return settings.vapid_public_key
    if not settings.vapid_private_key:
        return None
    try:
        from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1  # noqa: F401
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            PublicFormat,
            load_der_private_key,
        )

        # Pad to a valid base64url string
        padded = settings.vapid_private_key + "=="
        private_der = base64.urlsafe_b64decode(padded)
        private_key = load_der_private_key(private_der, password=None)
        pub_bytes = private_key.public_key().public_bytes(
            Encoding.X962, PublicFormat.UncompressedPoint
        )
        return base64.urlsafe_b64encode(pub_bytes).rstrip(b"=").decode()
    except Exception:
        logger.exception("vapid_public_key_derivation_failed")
        return None


def _send_webpush_sync(
    endpoint: str,
    p256dh: str,
    auth: str,
    payload: str,
    vapid_private_key: str,
    contact_email: str,
) -> None:
    webpush(
        subscription_info={"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}},
        data=payload,
        vapid_private_key=vapid_private_key,
        vapid_claims={"sub": f"mailto:{contact_email}"},
        ttl=3600 * NOTIFY_COOLDOWN_HOURS,
    )


async def _send_to_subscription(sub: PushSubscription, data: dict[str, Any]) -> bool | None:
    """
    Send a push notification to one subscription.

    Returns True on success, None if the subscription is expired (caller should delete it),
    or False on a transient error.
    """
    if not settings.vapid_private_key:
        return False

    payload = json.dumps(data)
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            partial(
                _send_webpush_sync,
                sub.endpoint,
                sub.p256dh,
                sub.auth,
                payload,
                settings.vapid_private_key,
                settings.vapid_contact_email,
            ),
        )
        return True
    except WebPushException as exc:
        status = exc.response.status_code if exc.response else None
        if status in (404, 410):
            return None  # subscription expired — caller should delete it
        logger.warning("push_send_failed", sub_id=sub.id, status=status, error=str(exc))
        return False
    except Exception as exc:
        logger.error("push_send_error", sub_id=sub.id, error=str(exc), exc_info=True)
        return False


async def notify_unhappy_pets(session: AsyncSession) -> int:
    """
    Send push notifications for all unhappy pets whose subscribers haven't been
    notified recently. Called at the end of each poll cycle.

    Returns the number of notifications sent.
    """
    if not settings.vapid_private_key:
        return 0

    unhappy_moods = [
        m.value for m in (PetMood.HUNGRY, PetMood.WORRIED, PetMood.LONELY, PetMood.SICK)
    ]
    cooldown_cutoff = datetime.now(UTC) - timedelta(hours=NOTIFY_COOLDOWN_HOURS)

    result = await session.execute(
        select(PushSubscription)
        .join(Pet, PushSubscription.pet_id == Pet.id)
        .where(
            Pet.is_dead.is_(False),
            Pet.mood.in_(unhappy_moods),
            or_(
                PushSubscription.last_notified_at.is_(None),
                PushSubscription.last_notified_at < cooldown_cutoff,
            ),
        )
        .with_for_update(skip_locked=True)
    )
    subscriptions = result.scalars().all()

    if not subscriptions:
        return 0

    # Load pets in a single query to avoid N+1
    pet_ids = list({sub.pet_id for sub in subscriptions})
    pets_result = await session.execute(select(Pet).where(Pet.id.in_(pet_ids)))
    pets_by_id = {p.id: p for p in pets_result.scalars().all()}

    sent = 0
    to_delete: list[PushSubscription] = []

    for sub in subscriptions:
        pet = pets_by_id.get(sub.pet_id)
        if not pet:
            continue

        emoji = MOOD_EMOJI.get(pet.mood, "😔")
        message = MOOD_MESSAGES.get(pet.mood, "needs your attention.")
        payload = {
            "title": f"{emoji} {pet.name} needs you!",
            "body": f"{pet.name} {message}",
            "icon": f"/api/v1/pets/{pet.repo_owner}/{pet.repo_name}/image/{pet.stage}",
            "url": f"/pet/{pet.repo_owner}/{pet.repo_name}",
            "tag": f"pet-{pet.id}",
        }

        send_result = await _send_to_subscription(sub, payload)
        if send_result is True:
            sub.last_notified_at = datetime.now(UTC)
            sent += 1
        elif send_result is None:
            to_delete.append(sub)

    for sub in to_delete:
        await session.delete(sub)
        logger.info("push_subscription_removed_expired", sub_id=sub.id)

    if sent > 0 or to_delete:
        await session.commit()

    if sent > 0:
        logger.info("push_notifications_sent", count=sent)

    return sent
