"""Tests for GitHub App installation tokens."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import httpx
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from github_tamagotchi.services import github_app


@pytest.fixture(autouse=True)
def _app_configured() -> Iterator[None]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    github_app._installation_ids.clear()
    github_app._tokens.clear()
    with (
        patch.object(github_app.settings, "github_app_id", "123"),
        patch.object(github_app.settings, "github_app_private_key", pem),
    ):
        yield
    github_app._installation_ids.clear()
    github_app._tokens.clear()


def _expiry(minutes: int = 60) -> str:
    return (datetime.now(UTC) + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


async def test_returns_none_when_not_configured() -> None:
    with patch.object(github_app.settings, "github_app_id", None):
        assert await github_app.installation_token_for("o", "r") is None


@respx.mock
async def test_mints_installation_token_for_repo() -> None:
    respx.get("https://api.github.com/repos/o/r/installation").mock(
        return_value=httpx.Response(200, json={"id": 77})
    )
    mint = respx.post("https://api.github.com/app/installations/77/access_tokens").mock(
        return_value=httpx.Response(201, json={"token": "ghs_abc", "expires_at": _expiry()})
    )

    assert await github_app.installation_token_for("o", "r") == "ghs_abc"
    # Cached: a second call makes no further requests.
    assert await github_app.installation_token_for("o", "r") == "ghs_abc"
    assert mint.call_count == 1


@respx.mock
async def test_repo_without_installation_returns_none_and_is_cached() -> None:
    lookup = respx.get("https://api.github.com/repos/o/r/installation").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )

    assert await github_app.installation_token_for("o", "r") is None
    assert await github_app.installation_token_for("o", "r") is None
    assert lookup.call_count == 1


@respx.mock
async def test_each_repo_gets_its_own_installation_token() -> None:
    """A token minted for one installation is never handed out for another repo."""
    respx.get("https://api.github.com/repos/a/one/installation").mock(
        return_value=httpx.Response(200, json={"id": 1})
    )
    respx.get("https://api.github.com/repos/b/two/installation").mock(
        return_value=httpx.Response(200, json={"id": 2})
    )
    respx.post("https://api.github.com/app/installations/1/access_tokens").mock(
        return_value=httpx.Response(201, json={"token": "tok-1", "expires_at": _expiry()})
    )
    respx.post("https://api.github.com/app/installations/2/access_tokens").mock(
        return_value=httpx.Response(201, json={"token": "tok-2", "expires_at": _expiry()})
    )

    assert await github_app.installation_token_for("a", "one") == "tok-1"
    assert await github_app.installation_token_for("b", "two") == "tok-2"


@respx.mock
async def test_github_error_falls_back_to_none() -> None:
    respx.get("https://api.github.com/repos/o/r/installation").mock(
        return_value=httpx.Response(500)
    )

    assert await github_app.installation_token_for("o", "r") is None


@respx.mock
async def test_expired_token_is_refreshed() -> None:
    respx.get("https://api.github.com/repos/o/r/installation").mock(
        return_value=httpx.Response(200, json={"id": 77})
    )
    mint = respx.post("https://api.github.com/app/installations/77/access_tokens").mock(
        side_effect=[
            httpx.Response(201, json={"token": "old", "expires_at": _expiry(2)}),
            httpx.Response(201, json={"token": "new", "expires_at": _expiry()}),
        ]
    )

    # Inside the refresh margin, so it is not cached.
    assert await github_app.installation_token_for("o", "r") == "old"
    assert await github_app.installation_token_for("o", "r") == "new"
    assert mint.call_count == 2
