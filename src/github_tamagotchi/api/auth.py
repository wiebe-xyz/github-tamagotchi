"""GitHub OAuth authentication routes."""

import logging
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.core.config import settings
from github_tamagotchi.core.database import get_session
from github_tamagotchi.core.telemetry import get_tracer
from github_tamagotchi.crud.user import create_or_update_user, get_user_by_id
from github_tamagotchi.models.user import User
from github_tamagotchi.services.token_encryption import encrypt_token

logger = logging.getLogger(__name__)
_tracer = get_tracer(__name__)

auth_router = APIRouter(prefix="/auth", tags=["auth"])

DbSession = Annotated[AsyncSession, Depends(get_session)]

# In-memory state store for CSRF protection during OAuth flow.
# Values are (created_at, optional_claim_target). claim_target is "owner/repo"
# when the OAuth flow was initiated from a badge "click to claim" link.
_oauth_states: dict[str, tuple[datetime, str | None]] = {}
_STATE_TTL_MINUTES = 10

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"


class UserResponse(BaseModel):
    """Public user info response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    github_id: int
    github_login: str
    github_avatar_url: str | None


def _create_jwt(user_id: int) -> str:
    """Create a JWT token for the given user."""
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(UTC) + timedelta(minutes=settings.jwt_expire_minutes),
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def _decode_jwt(token: str) -> dict[str, object]:
    """Decode and validate a JWT token."""
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])


def _cleanup_expired_states() -> None:
    """Remove expired OAuth states."""
    now = datetime.now(UTC)
    max_age = _STATE_TTL_MINUTES * 60
    expired = [
        k for k, (created, _claim) in _oauth_states.items()
        if (now - created).total_seconds() > max_age
    ]
    for k in expired:
        del _oauth_states[k]


_CLAIM_RE = re.compile(r"^[\w.-]{1,100}/[\w.-]{1,100}$")


def _parse_claim(claim: str | None) -> str | None:
    """Validate `owner/repo` shape; return normalised value or None."""
    if not claim:
        return None
    if not _CLAIM_RE.match(claim):
        return None
    return claim


async def get_current_user(
    session: DbSession,
    session_token: str | None = Cookie(None),
) -> User:
    """Dependency to get the current authenticated user from JWT cookie."""
    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    try:
        payload = _decode_jwt(session_token)
        user_id = int(str(payload["sub"]))
    except (jwt.InvalidTokenError, KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc

    user = await get_user_by_id(session, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    # Sync is_admin from config on every request so nav links and gates stay consistent
    should_be_admin = user.github_login in settings.admin_github_logins
    if user.is_admin != should_be_admin:
        user.is_admin = should_be_admin
        await session.commit()
    return user


async def get_admin_user(user: Annotated[User, Depends(get_current_user)]) -> User:
    """Dependency to require admin access."""
    is_admin = user.is_admin or (user.github_login in settings.admin_github_logins)
    if not is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


async def get_optional_user(
    session: DbSession,
    session_token: str | None = Cookie(None),
) -> User | None:
    """Dependency to optionally get the current user (returns None if not authenticated)."""
    if not session_token:
        return None
    try:
        payload = _decode_jwt(session_token)
        user_id = int(str(payload["sub"]))
    except (jwt.InvalidTokenError, KeyError, ValueError):
        return None
    user = await get_user_by_id(session, user_id)
    if user is not None:
        # Keep is_admin in sync with config so nav links stay consistent
        should_be_admin = user.github_login in settings.admin_github_logins
        if user.is_admin != should_be_admin:
            user.is_admin = should_be_admin
            await session.commit()
    return user


class _ClaimError(Exception):
    """Raised when an OAuth claim cannot be completed."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def _verify_github_repo_access(access_token: str, owner: str, repo: str) -> bool:
    """Return True if the OAuth user can see this repo via GitHub's API.

    A 200 from `GET /repos/{owner}/{repo}` is enough — for private repos this
    requires the user have at least read access. We don't require push, on the
    assumption that anyone who can see the repo has a legitimate interest in
    its tamagotchi (and the API today allows anonymous pet creation anyway).
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
            },
        )
    return resp.status_code == 200


async def _claim_placeholder_for_user(
    *,
    session: AsyncSession,
    user: User,
    access_token: str,
    claim_target: str,
) -> tuple[str, str]:
    """Bind the placeholder pet for claim_target to `user`, queueing first image.

    Returns (owner, repo) on success. Raises _ClaimError with a reason slug
    that the caller can surface in a redirect query string.
    """
    from github_tamagotchi.models.pet import PetStage
    from github_tamagotchi.services import image_queue
    from github_tamagotchi.services import pet as pet_service

    owner, repo = claim_target.split("/", 1)

    pet = await pet_service.get_by_repo(session, owner, repo)
    if pet is None:
        raise _ClaimError("not_found")
    if not pet.is_placeholder and pet.user_id is not None:
        if pet.user_id == user.id:
            return owner, repo  # idempotent: already mine
        raise _ClaimError("already_claimed")

    if not await _verify_github_repo_access(access_token, owner, repo):
        raise _ClaimError("no_access")

    await pet_service.claim_placeholder(session, pet, user_id=user.id)
    try:
        await image_queue.create_job(session, pet.id, PetStage.EGG.value)
    except ValueError:
        # Image generation not configured — leave pet unclaimed-image; user can regenerate later.
        logger.info(
            "claim_image_enqueue_skipped pet_id=%s reason=no_provider",
            pet.id,
        )
    return owner, repo


@auth_router.get("/github")
async def login_github(response: Response, claim: str | None = None) -> Response:
    """Redirect to GitHub OAuth authorization page.

    When `claim=owner/repo` is provided (from a badge "click to claim" link),
    the value is bound to the OAuth state and consumed in /auth/callback to
    finish binding the placeholder pet to the authenticated user.
    """
    if not settings.github_oauth_client_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub OAuth is not configured",
        )

    _cleanup_expired_states()
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = (datetime.now(UTC), _parse_claim(claim))

    params = {
        "client_id": settings.github_oauth_client_id,
        "redirect_uri": settings.oauth_redirect_uri,
        "scope": "repo,read:user,read:org",
        "state": state,
    }
    redirect_url = f"{GITHUB_AUTHORIZE_URL}?{urlencode(params)}"
    return Response(
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        headers={"location": redirect_url},
    )


@auth_router.get("/callback")
async def oauth_callback(
    session: DbSession,
    code: str | None = None,
    state: str | None = None,
) -> Response:
    """Handle GitHub OAuth callback."""
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing authorization code",
        )
    if not state or state not in _oauth_states:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OAuth state",
        )
    _state_created, claim_target = _oauth_states[state]
    del _oauth_states[state]

    if not settings.github_oauth_client_id or not settings.github_oauth_client_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub OAuth is not configured",
        )

    with _tracer.start_as_current_span(
        "api.auth.oauth_callback",
    ) as span:
        # Exchange code for access token
        async with httpx.AsyncClient() as client:
            token_response = await client.post(
                GITHUB_TOKEN_URL,
                data={
                    "client_id": settings.github_oauth_client_id,
                    "client_secret": (
                        settings.github_oauth_client_secret
                    ),
                    "code": code,
                    "redirect_uri": settings.oauth_redirect_uri,
                },
                headers={"Accept": "application/json"},
            )
            if token_response.status_code != 200:
                logger.error(
                    "GitHub token exchange failed: %s",
                    token_response.text,
                )
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Failed to exchange code for token",
                )

            token_data = token_response.json()
            access_token = token_data.get("access_token")
            if not access_token:
                error = token_data.get(
                    "error_description",
                    token_data.get("error", "unknown"),
                )
                logger.error("GitHub OAuth error: %s", error)
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"GitHub OAuth error: {error}",
                )

            # Fetch user info from GitHub
            user_response = await client.get(
                GITHUB_USER_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
            )
            if user_response.status_code != 200:
                logger.error(
                    "GitHub user info fetch failed: %s",
                    user_response.text,
                )
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=(
                        "Failed to fetch user info from GitHub"
                    ),
                )

            github_user = user_response.json()

        span.set_attribute(
            "auth.github_login", github_user["login"]
        )

        # Encrypt token before storage
        encrypted = None
        if settings.token_encryption_key:
            try:
                encrypted = encrypt_token(access_token)
            except Exception:
                logger.exception(
                    "Failed to encrypt token"
                    " — storing without encryption"
                )
                encrypted = None

        # Create or update user in database
        user = await create_or_update_user(
            session,
            github_id=github_user["id"],
            github_login=github_user["login"],
            github_avatar_url=github_user.get("avatar_url"),
            encrypted_token=encrypted,
        )

        # Set admin flag based on configured logins
        user.is_admin = (
            github_user["login"] in settings.admin_github_logins
        )
        await session.commit()

        span.set_attribute("auth.user_id", str(user.id))
        span.set_attribute("auth.is_admin", user.is_admin)

        # If the OAuth flow was initiated from a "click to claim" badge,
        # verify GitHub access and bind the placeholder pet to this user.
        redirect_target = "/register"
        if claim_target:
            try:
                bound = await _claim_placeholder_for_user(
                    session=session,
                    user=user,
                    access_token=access_token,
                    claim_target=claim_target,
                )
            except _ClaimError as claim_exc:
                logger.warning(
                    "oauth_claim_failed: %s — claim_target=%s user=%s",
                    claim_exc.reason,
                    claim_target,
                    user.github_login,
                )
                redirect_target = f"/?claim_error={claim_exc.reason}&repo={claim_target}"
            else:
                owner, repo = bound
                redirect_target = f"/pets/{owner}/{repo}"

        # Create JWT session token
        token = _create_jwt(user.id)

        response = Response(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"location": redirect_target},
        )
        response.set_cookie(
            key="session_token",
            value=token,
            httponly=True,
            secure=not settings.debug,
            samesite="lax",
            max_age=settings.jwt_expire_minutes * 60,
        )
        return response


@auth_router.get("/me", response_model=UserResponse)
async def get_me(
    user: Annotated[User, Depends(get_current_user)],
) -> UserResponse:
    """Get the currently authenticated user's info."""
    return UserResponse.model_validate(user)


@auth_router.post("/logout")
async def logout() -> Response:
    """Log out by clearing the session cookie."""
    response = Response(status_code=status.HTTP_200_OK)
    response.delete_cookie("session_token")
    return response
