"""Web push subscription endpoints."""

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.api.auth import get_optional_user
from github_tamagotchi.core.database import get_session
from github_tamagotchi.core.telemetry import get_tracer
from github_tamagotchi.models.pet import Pet
from github_tamagotchi.models.push_subscription import PushSubscription
from github_tamagotchi.models.user import User
from github_tamagotchi.services.push_notifications import get_vapid_public_key

logger = structlog.get_logger()
_tracer = get_tracer(__name__)

router = APIRouter(prefix="/api/v1/push", tags=["push"])


class SubscribeRequest(BaseModel):
    endpoint: str
    p256dh: str
    auth: str
    pet_owner: str
    pet_name: str


class UnsubscribeRequest(BaseModel):
    endpoint: str
    pet_owner: str
    pet_name: str


@router.get("/vapid-public-key")
async def vapid_public_key() -> dict[str, str | None]:
    return {"publicKey": get_vapid_public_key()}


@router.get("/subscription/{pet_owner}/{pet_name}")
async def get_subscription_status(
    pet_owner: str,
    pet_name: str,
    endpoint: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, bool]:
    """Check whether a browser endpoint is subscribed to a pet."""
    pet = await _get_pet_or_404(session, pet_owner, pet_name)
    result = await session.execute(
        select(PushSubscription).where(
            PushSubscription.pet_id == pet.id,
            PushSubscription.endpoint == endpoint,
        )
    )
    return {"subscribed": result.scalar_one_or_none() is not None}


@router.post("/subscribe", status_code=201)
async def subscribe(
    body: SubscribeRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User | None, Depends(get_optional_user)],
) -> dict[str, str]:
    if get_vapid_public_key() is None:
        raise HTTPException(
            status_code=503,
            detail="Push notifications not configured",
        )

    pet = await _get_pet_or_404(
        session, body.pet_owner, body.pet_name
    )

    with _tracer.start_as_current_span(
        "api.push.subscribe",
        attributes={
            "pet.owner": body.pet_owner,
            "pet.name": body.pet_name,
            "pet.id": str(pet.id),
        },
    ) as span:
        # Upsert: update keys if already subscribed
        result = await session.execute(
            select(PushSubscription).where(
                PushSubscription.pet_id == pet.id,
                PushSubscription.endpoint == body.endpoint,
            )
        )
        sub = result.scalar_one_or_none()
        is_update = sub is not None
        if sub:
            sub.p256dh = body.p256dh
            sub.auth = body.auth
            if user:
                sub.user_id = user.id
        else:
            sub = PushSubscription(
                pet_id=pet.id,
                user_id=user.id if user else None,
                endpoint=body.endpoint,
                p256dh=body.p256dh,
                auth=body.auth,
            )
            session.add(sub)

        await session.commit()
        span.set_attribute("push.is_update", is_update)
        logger.info(
            "push_subscribed",
            pet=f"{body.pet_owner}/{body.pet_name}",
            user_id=user.id if user else None,
        )
        return {"status": "subscribed"}


@router.delete("/subscribe")
async def unsubscribe(
    body: UnsubscribeRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, str]:
    pet = await _get_pet_or_404(
        session, body.pet_owner, body.pet_name
    )

    with _tracer.start_as_current_span(
        "api.push.unsubscribe",
        attributes={
            "pet.owner": body.pet_owner,
            "pet.name": body.pet_name,
            "pet.id": str(pet.id),
        },
    ) as span:
        result = await session.execute(
            select(PushSubscription).where(
                PushSubscription.pet_id == pet.id,
                PushSubscription.endpoint == body.endpoint,
            )
        )
        sub = result.scalar_one_or_none()
        found = sub is not None
        if sub:
            await session.delete(sub)
            await session.commit()
            logger.info(
                "push_unsubscribed",
                pet=f"{body.pet_owner}/{body.pet_name}",
            )
        span.set_attribute("push.found", found)

    return {"status": "unsubscribed"}


async def _get_pet_or_404(session: AsyncSession, owner: str, name: str) -> Pet:
    result = await session.execute(
        select(Pet).where(
            Pet.repo_owner == owner,
            Pet.repo_name == name,
        )
    )
    pet = result.scalar_one_or_none()
    if pet is None:
        raise HTTPException(status_code=404, detail="Pet not found")
    return pet
