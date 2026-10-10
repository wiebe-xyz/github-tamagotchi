"""Long-lived MCP sessions on top of FastMCP's GitHub OAuth proxy.

FastMCP's stock GitHubProvider ties the MCP session to the upstream GitHub
token. A GitHub OAuth App returns no refresh token and no expiry, so the
stock proxy issues a one-year access token, no refresh token, and calls
GitHub's API on every request to check the GitHub token is still alive.
Two things then force a new browser login:

- The one-year access token runs out, and there is nothing to refresh with.
- GitHub revokes the token. It keeps at most ten tokens per
  user/app/scope and revokes the oldest. The website login uses the same
  OAuth App and the same scopes, so ten website logins revoke the MCP
  session's GitHub token and every MCP request turns into a 401.

LongLivedGitHubProvider keeps the browser login and the GitHub callback as
they are and replaces how tokens are issued and checked:

- Access tokens live ACCESS_TOKEN_TTL_SECONDS (1 hour).
- Every login gets a refresh token. Each refresh rotates it and starts a new
  REFRESH_TOKEN_IDLE_TTL_SECONDS (365 days) window, so a session that is
  used at least once a year never expires. A rotated token stays usable for
  REFRESH_REUSE_GRACE_SECONDS so two concurrent refreshes both succeed;
  replaying it after that revokes the whole grant.
- Checking an access token reads the database only. GitHub is consulted at
  refresh time: if GitHub reports the token revoked, the newest GitHub token
  stored for the same user (written by the website login and by MCP logins)
  takes its place. Only when no valid token exists, meaning the user revoked
  the app, does the session end. A GitHub outage never ends a session.
- Grants, refresh tokens and access-token records live in the
  oauth_kv_store table (Postgres in production), so restarts and the
  blue/green switch keep every session. The JWT signing key is derived from
  the GitHub OAuth client secret, which is the same in every pod.
- Deleting a row revokes: the "mcp-grants" row ends the whole session,
  a "mcp-session-refresh-tokens" row ends that refresh token.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from typing import Any

import httpx
import structlog
from fastmcp.server.auth.auth import AccessToken
from fastmcp.server.auth.providers.github import GitHubProvider
from key_value.aio.adapters.pydantic import PydanticAdapter
from mcp.server.auth.provider import AccessToken as SdkAccessToken
from mcp.server.auth.provider import AuthorizationCode, RefreshToken, TokenError
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import async_sessionmaker

from github_tamagotchi.core import database
from github_tamagotchi.core.config import settings
from github_tamagotchi.repositories.user import create_or_update_user, get_user_by_github_id
from github_tamagotchi.services.token_encryption import decrypt_token, encrypt_token

logger = structlog.get_logger(__name__)

ACCESS_TOKEN_TTL_SECONDS = 60 * 60
REFRESH_TOKEN_IDLE_TTL_SECONDS = 365 * 24 * 60 * 60
REFRESH_REUSE_GRACE_SECONDS = 120
# How long a rotated refresh token is remembered, so a replay after the
# grace window is recognised as reuse and revokes the grant.
ROTATED_REFRESH_RETENTION_SECONDS = 30 * 24 * 60 * 60

GITHUB_USER_URL = "https://api.github.com/user"
_GITHUB_TIMEOUT_SECONDS = 10

_GRANTS = "mcp-grants"
_REFRESH_TOKENS = "mcp-session-refresh-tokens"
_ACCESS_TOKENS = "mcp-session-access-tokens"


class McpGrant(BaseModel):
    """One completed browser login: who the user is and their GitHub token."""

    grant_id: str
    client_id: str
    scopes: list[str]
    github_token: str
    github_token_encrypted: bool
    github_scopes: list[str]
    claims: dict[str, Any]
    created_at: float
    last_refreshed_at: float


class McpRefreshRecord(BaseModel):
    """A refresh token, stored under the SHA-256 of the token."""

    grant_id: str
    client_id: str
    scopes: list[str]
    expires_at: int
    rotated_at: float | None = None


class McpAccessRecord(BaseModel):
    """Maps an access token's jti to its grant."""

    grant_id: str


class _GitHubCheck(BaseModel):
    status: str  # "valid" | "revoked" | "unknown"
    claims: dict[str, Any] = {}
    scopes: list[str] = []


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _seal(github_token: str) -> tuple[str, bool]:
    if settings.token_encryption_key:
        return encrypt_token(github_token), True
    return github_token, False


def _unseal(grant: McpGrant) -> str:
    return decrypt_token(grant.github_token) if grant.github_token_encrypted else grant.github_token


class LongLivedGitHubProvider(GitHubProvider):
    """GitHubProvider with short access tokens and sliding refresh tokens."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        # Same late lookup as DatabaseKeyValueStore: tests patch the
        # module-level factory after this provider is built at import time.
        self._session_factory_override = session_factory
        self._grant_store: PydanticAdapter[McpGrant] = PydanticAdapter[McpGrant](
            key_value=self._client_storage,
            pydantic_model=McpGrant,
            default_collection=_GRANTS,
            raise_on_validation_error=True,
        )
        self._session_refresh_store: PydanticAdapter[McpRefreshRecord] = PydanticAdapter[
            McpRefreshRecord
        ](
            key_value=self._client_storage,
            pydantic_model=McpRefreshRecord,
            default_collection=_REFRESH_TOKENS,
            raise_on_validation_error=True,
        )
        self._session_access_store: PydanticAdapter[McpAccessRecord] = PydanticAdapter[
            McpAccessRecord
        ](
            key_value=self._client_storage,
            pydantic_model=McpAccessRecord,
            default_collection=_ACCESS_TOKENS,
            raise_on_validation_error=True,
        )

    # ------------------------------------------------------------------
    # Authorization code -> first token pair
    # ------------------------------------------------------------------

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        code_model = await self._code_store.get(key=authorization_code.code)
        if code_model is None:
            raise TokenError("invalid_grant", "Authorization code not found")
        await self._code_store.delete(key=authorization_code.code)
        if client.client_id is None:
            raise TokenError("invalid_client", "Client ID is required")

        github_token = code_model.idp_tokens.get("access_token")
        if not github_token:
            raise TokenError("invalid_grant", "GitHub returned no access token")

        check = await self._check_github_token(github_token)
        if check.status != "valid":
            raise TokenError("invalid_grant", "Could not verify the GitHub login")
        if self.required_scopes and not set(self.required_scopes) <= set(check.scopes):
            raise TokenError("invalid_grant", "GitHub token lacks the required scopes")

        sealed, encrypted = _seal(github_token)
        now = time.time()
        grant = McpGrant(
            grant_id=secrets.token_urlsafe(32),
            client_id=client.client_id,
            scopes=authorization_code.scopes,
            github_token=sealed,
            github_token_encrypted=encrypted,
            github_scopes=check.scopes,
            claims=check.claims,
            created_at=now,
            last_refreshed_at=now,
        )
        await self._store_user_token(grant, github_token)
        logger.info(
            "mcp_login",
            client_id=client.client_id,
            github_login=check.claims.get("login"),
        )
        return await self._issue(grant)

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> RefreshToken | None:
        record = await self._session_refresh_store.get(key=_hash(refresh_token))
        if record is None or record.client_id != client.client_id:
            return None
        return RefreshToken(
            token=refresh_token,
            client_id=record.client_id,
            scopes=record.scopes,
            expires_at=record.expires_at,
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        try:
            payload = self.jwt_issuer.verify_token(refresh_token.token)
        except Exception as exc:
            raise TokenError("invalid_grant", "Invalid refresh token") from exc
        if payload.get("token_use") != "refresh":
            raise TokenError("invalid_grant", "Not a refresh token")

        token_hash = _hash(refresh_token.token)
        record = await self._session_refresh_store.get(key=token_hash)
        if record is None or record.client_id != client.client_id:
            raise TokenError("invalid_grant", "Refresh token not found")

        now = time.time()
        if record.rotated_at is not None and now - record.rotated_at > REFRESH_REUSE_GRACE_SECONDS:
            # A rotated token replayed after the grace window: treat it as
            # stolen and end the whole session.
            await self._grant_store.delete(key=record.grant_id)
            await self._session_refresh_store.delete(key=token_hash)
            logger.warning("mcp_refresh_token_reuse", client_id=client.client_id)
            raise TokenError("invalid_grant", "Refresh token was already used")

        grant = await self._grant_store.get(key=record.grant_id)
        if grant is None:
            raise TokenError("invalid_grant", "Session was revoked")

        grant = await self._recheck_github(grant)
        if grant is None:
            await self._grant_store.delete(key=record.grant_id)
            await self._session_refresh_store.delete(key=token_hash)
            raise TokenError("invalid_grant", "GitHub access was revoked")

        if record.rotated_at is None:
            record.rotated_at = now
            await self._session_refresh_store.put(
                key=token_hash, value=record, ttl=ROTATED_REFRESH_RETENTION_SECONDS
            )

        grant.last_refreshed_at = now
        return await self._issue(grant, scopes=scopes)

    # ------------------------------------------------------------------
    # Access token check (every MCP request)
    # ------------------------------------------------------------------

    async def load_access_token(self, token: str) -> AccessToken | None:
        try:
            payload = self.jwt_issuer.verify_token(token)
        except Exception:
            return None
        if payload.get("token_use") == "refresh":
            return None

        record = await self._session_access_store.get(key=str(payload.get("jti", "")))
        if record is None:
            return None
        grant = await self._grant_store.get(key=record.grant_id)
        if grant is None:
            return None

        return AccessToken(
            token=_unseal(grant),
            client_id=str(grant.claims.get("sub", grant.client_id)),
            scopes=grant.github_scopes,
            expires_at=int(payload["exp"]) if payload.get("exp") else None,
            claims=grant.claims,
        )

    async def revoke_token(self, token: SdkAccessToken | RefreshToken) -> None:
        if isinstance(token, RefreshToken):
            record = await self._session_refresh_store.get(key=_hash(token.token))
            if record is not None:
                await self._grant_store.delete(key=record.grant_id)
            await self._session_refresh_store.delete(key=_hash(token.token))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _issue(self, grant: McpGrant, scopes: list[str] | None = None) -> OAuthToken:
        """Save the grant with a fresh idle window and mint a token pair."""
        scopes = scopes or grant.scopes
        await self._grant_store.put(
            key=grant.grant_id, value=grant, ttl=REFRESH_TOKEN_IDLE_TTL_SECONDS
        )

        access_jti = secrets.token_urlsafe(32)
        access_token = self.jwt_issuer.issue_access_token(
            client_id=grant.client_id,
            scopes=scopes,
            jti=access_jti,
            expires_in=ACCESS_TOKEN_TTL_SECONDS,
        )
        await self._session_access_store.put(
            key=access_jti,
            value=McpAccessRecord(grant_id=grant.grant_id),
            ttl=ACCESS_TOKEN_TTL_SECONDS,
        )

        refresh_token = self.jwt_issuer.issue_refresh_token(
            client_id=grant.client_id,
            scopes=scopes,
            jti=secrets.token_urlsafe(32),
            expires_in=REFRESH_TOKEN_IDLE_TTL_SECONDS,
        )
        await self._session_refresh_store.put(
            key=_hash(refresh_token),
            value=McpRefreshRecord(
                grant_id=grant.grant_id,
                client_id=grant.client_id,
                scopes=scopes,
                expires_at=int(time.time()) + REFRESH_TOKEN_IDLE_TTL_SECONDS,
            ),
            ttl=REFRESH_TOKEN_IDLE_TTL_SECONDS,
        )

        return OAuthToken(
            access_token=access_token,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_TTL_SECONDS,
            refresh_token=refresh_token,
            scope=" ".join(scopes),
        )

    async def _recheck_github(self, grant: McpGrant) -> McpGrant | None:
        """Return the grant with a working GitHub token, or None if GitHub
        access is gone for good."""
        check = await self._check_github_token(_unseal(grant))
        if check.status == "valid":
            grant.claims = check.claims
            grant.github_scopes = check.scopes or grant.github_scopes
            return grant
        if check.status == "unknown":
            logger.warning("mcp_refresh_github_unreachable", client_id=grant.client_id)
            return grant

        replacement = await self._newest_user_token(grant)
        if replacement is None:
            logger.warning(
                "mcp_refresh_github_token_revoked",
                github_login=grant.claims.get("login"),
            )
            return None
        token, check = replacement
        grant.github_token, grant.github_token_encrypted = _seal(token)
        grant.claims = check.claims
        grant.github_scopes = check.scopes or grant.github_scopes
        logger.info("mcp_refresh_github_token_replaced", github_login=grant.claims.get("login"))
        return grant

    async def _newest_user_token(self, grant: McpGrant) -> tuple[str, _GitHubCheck] | None:
        """The GitHub token last stored on the user row, if it still works
        and belongs to the same GitHub account."""
        github_id = grant.claims.get("sub")
        if github_id is None or not settings.token_encryption_key:
            return None
        async with self._open_session() as session:
            user = await get_user_by_github_id(session, int(github_id))
        if user is None or not user.encrypted_token:
            return None
        try:
            token = decrypt_token(user.encrypted_token)
        except Exception:
            return None
        if token == _unseal(grant):
            return None
        check = await self._check_github_token(token)
        if check.status != "valid" or check.claims.get("sub") != str(github_id):
            return None
        return token, check

    async def _store_user_token(self, grant: McpGrant, github_token: str) -> None:
        """Record the MCP login's GitHub token on the user row too, so the
        user row always holds the newest token from either login path."""
        github_id = grant.claims.get("sub")
        login = grant.claims.get("login")
        if github_id is None or login is None or not settings.token_encryption_key:
            return
        async with self._open_session() as session:
            await create_or_update_user(
                session,
                github_id=int(github_id),
                github_login=str(login),
                github_avatar_url=grant.claims.get("avatar_url"),
                encrypted_token=encrypt_token(github_token),
            )

    def _open_session(self) -> Any:
        factory = self._session_factory_override or database.async_session_factory
        return factory()

    async def _check_github_token(self, token: str) -> _GitHubCheck:
        try:
            async with httpx.AsyncClient(timeout=_GITHUB_TIMEOUT_SECONDS) as client:
                response = await client.get(
                    GITHUB_USER_URL,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                        "User-Agent": "github-tamagotchi-mcp",
                    },
                )
        except httpx.HTTPError:
            return _GitHubCheck(status="unknown")

        if response.status_code == 401:
            return _GitHubCheck(status="revoked")
        if response.status_code != 200:
            return _GitHubCheck(status="unknown")

        user = response.json()
        scopes = [
            s.strip() for s in response.headers.get("x-oauth-scopes", "").split(",") if s.strip()
        ]
        return _GitHubCheck(
            status="valid",
            scopes=scopes,
            claims={
                "sub": str(user["id"]),
                "login": user.get("login"),
                "name": user.get("name"),
                "email": user.get("email"),
                "avatar_url": user.get("avatar_url"),
            },
        )
