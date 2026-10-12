"""GitHub App installation tokens for repos the app-wide token cannot see.

The poller asks `installation_token_for` per repo. It returns None when no App
is configured, the repo has no installation, or GitHub cannot be reached, and
the caller then keeps using the app-wide token. No user token is involved.
"""

import time
from datetime import UTC, datetime

import httpx
import jwt
import structlog

from github_tamagotchi.core.config import settings

logger = structlog.get_logger()

_API = "https://api.github.com"
_JWT_TTL_SECONDS = 540
_REFRESH_MARGIN_SECONDS = 300
_INSTALLATION_TTL_SECONDS = 3600
_NO_INSTALLATION_TTL_SECONDS = 900

# "owner/repo" -> (installation id or None, monotonic expiry)
_installation_ids: dict[str, tuple[int | None, float]] = {}
# installation id -> (token, monotonic expiry)
_tokens: dict[int, tuple[str, float]] = {}


def is_configured() -> bool:
    return bool(settings.github_app_id and settings.github_app_private_key)


def _app_jwt() -> str:
    now = int(time.time())
    key = (settings.github_app_private_key or "").replace("\\n", "\n")
    return jwt.encode(
        {"iat": now - 60, "exp": now + _JWT_TTL_SECONDS, "iss": str(settings.github_app_id)},
        key,
        algorithm="RS256",
    )


def _headers(bearer: str) -> dict[str, str]:
    return {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {bearer}"}


def _token_ttl_seconds(expires_at: str | None) -> float:
    """Seconds to keep a token, ending shortly before GitHub expires it."""
    if not expires_at:
        return 0.0
    expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    return max(0.0, (expiry - datetime.now(UTC)).total_seconds() - _REFRESH_MARGIN_SECONDS)


async def _installation_id(client: httpx.AsyncClient, owner: str, repo: str) -> int | None:
    cache_key = f"{owner}/{repo}".lower()
    cached = _installation_ids.get(cache_key)
    if cached and cached[1] > time.monotonic():
        return cached[0]

    resp = await client.get(
        f"{_API}/repos/{owner}/{repo}/installation", headers=_headers(_app_jwt())
    )
    if resp.status_code == 404:
        _installation_ids[cache_key] = (None, time.monotonic() + _NO_INSTALLATION_TTL_SECONDS)
        return None
    resp.raise_for_status()
    installation_id = int(resp.json()["id"])
    _installation_ids[cache_key] = (installation_id, time.monotonic() + _INSTALLATION_TTL_SECONDS)
    return installation_id


async def installation_token_for(owner: str, repo: str) -> str | None:
    """A token for the App installation covering `owner/repo`, or None."""
    if not is_configured():
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            installation_id = await _installation_id(client, owner, repo)
            if installation_id is None:
                return None

            cached = _tokens.get(installation_id)
            if cached and cached[1] > time.monotonic():
                return cached[0]

            resp = await client.post(
                f"{_API}/app/installations/{installation_id}/access_tokens",
                headers=_headers(_app_jwt()),
            )
            resp.raise_for_status()
            data = resp.json()
            ttl = _token_ttl_seconds(data.get("expires_at"))
            _tokens[installation_id] = (data["token"], time.monotonic() + ttl)
            return str(data["token"])
    except Exception as e:
        logger.warning(
            "github_app_token_failed",
            repo=f"{owner}/{repo}",
            error=str(e),
            message="Falling back to the app-wide token",
        )
        return None
