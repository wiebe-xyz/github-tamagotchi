"""Tests for the browser telemetry proxy (POST /api/v1/telemetry/api/v1/spans)."""

from collections.abc import Iterator
from unittest.mock import patch

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from httpx import AsyncClient

from github_tamagotchi.api.routes.v1 import telemetry

URL = "/api/v1/telemetry/api/v1/spans"
SPAN = {"traceId": "a" * 32, "spanId": "b" * 16, "name": "page /", "service": "web"}


@pytest.fixture(autouse=True)
def _configured() -> Iterator[None]:
    telemetry._recent.clear()
    with (
        patch.object(telemetry.settings, "spanbarn_api_key", "server-key"),
        patch.object(telemetry.settings, "otel_exporter_otlp_endpoint", "https://sb.test"),
    ):
        yield
    telemetry._recent.clear()


@respx.mock
async def test_forwards_spans_with_server_side_key(async_client: AsyncClient) -> None:
    upstream = respx.post("https://sb.test/api/v1/spans").mock(return_value=httpx.Response(202))

    response = await async_client.post(URL, json={"spans": [SPAN]})

    assert response.status_code == 204
    sent = upstream.calls.last.request
    assert sent.headers["X-SpanBarn-Api-Key"] == "server-key"
    assert b'"page /"' in sent.content


@respx.mock
async def test_browser_supplied_key_is_never_forwarded(async_client: AsyncClient) -> None:
    upstream = respx.post("https://sb.test/api/v1/spans").mock(return_value=httpx.Response(202))

    await async_client.post(
        URL, json={"spans": [SPAN]}, headers={"X-SpanBarn-Api-Key": "attacker-key"}
    )

    assert upstream.calls.last.request.headers["X-SpanBarn-Api-Key"] == "server-key"


@respx.mock
async def test_disabled_without_config_makes_no_upstream_call(async_client: AsyncClient) -> None:
    upstream = respx.post("https://sb.test/api/v1/spans")
    with patch.object(telemetry.settings, "spanbarn_api_key", None):
        response = await async_client.post(URL, json={"spans": [SPAN]})

    assert response.status_code == 204
    assert not upstream.called


@pytest.mark.parametrize(
    "payload",
    [{"spans": []}, {"spans": "x"}, {"spans": [1]}, {"nope": 1}, [SPAN], {"spans": [SPAN] * 101}],
)
async def test_rejects_malformed_payloads(async_client: AsyncClient, payload: object) -> None:
    response = await async_client.post(URL, json=payload)
    assert response.status_code == 422


async def test_rejects_non_json(async_client: AsyncClient) -> None:
    response = await async_client.post(URL, content=b"not json")
    assert response.status_code == 422


async def test_rejects_oversized_body(async_client: AsyncClient) -> None:
    big = {"spans": [{**SPAN, "attributes": {"k": "x" * (telemetry.MAX_BODY_BYTES + 1)}}]}
    response = await async_client.post(URL, json=big)
    assert response.status_code == 413


@respx.mock
async def test_rate_limits_a_noisy_client(async_client: AsyncClient) -> None:
    respx.post("https://sb.test/api/v1/spans").mock(return_value=httpx.Response(202))

    codes = [
        (await async_client.post(URL, json={"spans": [SPAN]})).status_code
        for _ in range(telemetry.RATE_LIMIT_REQUESTS + 1)
    ]

    assert codes[: telemetry.RATE_LIMIT_REQUESTS] == [204] * telemetry.RATE_LIMIT_REQUESTS
    assert codes[-1] == 429


@respx.mock
async def test_upstream_failure_is_reported_not_raised(async_client: AsyncClient) -> None:
    respx.post("https://sb.test/api/v1/spans").mock(return_value=httpx.Response(500))

    response = await async_client.post(URL, json={"spans": [SPAN]})

    assert response.status_code == 502


def test_pages_load_the_browser_sdk_only_when_enabled(client: TestClient) -> None:
    import sys

    templates = sys.modules["github_tamagotchi.main"].templates
    try:
        templates.env.globals["spanbarn_web_enabled"] = True
        enabled = client.get("/graveyard").text
        templates.env.globals["spanbarn_web_enabled"] = False
        disabled = client.get("/graveyard").text
    finally:
        templates.env.globals["spanbarn_web_enabled"] = telemetry.is_enabled()

    assert "/static/js/spanbarn.iife.js" in enabled
    assert "/static/js/spanbarn-init.js" in enabled
    assert "spanbarn" not in disabled
