"""Personal API token management for MCP clients.

Web-session authenticated (cookie) — an MCP client can't drive a browser
OAuth redirect, so a user generates a token here first, then configures
their MCP client with it. See services/mcp_auth.py for how the token
itself gets verified on the MCP side.
"""

from datetime import datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.api.auth import get_current_user
from github_tamagotchi.core.database import get_session
from github_tamagotchi.models.mcp_token import McpToken
from github_tamagotchi.models.user import User
from github_tamagotchi.services.mcp_auth import generate_raw_token, hash_token

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/mcp-tokens", tags=["mcp-tokens"])


class CreateTokenRequest(BaseModel):
    label: str | None = None


class TokenSummary(BaseModel):
    id: int
    label: str | None
    created_at: datetime
    last_used_at: datetime | None

    model_config = {"from_attributes": True}


class CreatedToken(BaseModel):
    id: int
    label: str | None
    token: str  # only ever returned here, at creation


@router.get("", response_model=list[TokenSummary])
async def list_tokens(
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(get_current_user)],
) -> list[McpToken]:
    result = await session.execute(
        select(McpToken).where(McpToken.user_id == user.id).order_by(McpToken.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("", response_model=CreatedToken, status_code=201)
async def create_token(
    body: CreateTokenRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(get_current_user)],
) -> CreatedToken:
    raw = generate_raw_token()
    token = McpToken(user_id=user.id, token_hash=hash_token(raw), label=body.label)
    session.add(token)
    await session.commit()
    await session.refresh(token)

    logger.info("mcp_token_created", user_id=user.id, token_id=token.id)
    return CreatedToken(id=token.id, label=token.label, token=raw)


@router.delete("/{token_id}", status_code=204)
async def revoke_token(
    token_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(get_current_user)],
) -> None:
    result = await session.execute(
        delete(McpToken)
        .where(McpToken.id == token_id, McpToken.user_id == user.id)
        .returning(McpToken.id)
    )
    if result.first() is None:
        raise HTTPException(status_code=404, detail="Token not found")
    await session.commit()
    logger.info("mcp_token_revoked", user_id=user.id, token_id=token_id)
