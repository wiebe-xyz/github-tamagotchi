"""Tests for ComfyUI service."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from github_tamagotchi.services.comfyui import ComfyUIService


@pytest.fixture
def comfyui_service() -> ComfyUIService:
    """Create a ComfyUI service with test URL."""
    return ComfyUIService(url="https://comfyui.test.local")


@pytest.fixture
def comfyui_service_with_auth() -> ComfyUIService:
    """Create a ComfyUI service with Cloudflare Access credentials."""
    return ComfyUIService(
        url="https://comfyui.test.local",
        cf_access_client_id="test-client-id",
        cf_access_client_secret="test-client-secret",
    )


async def test_check_health_success(comfyui_service: ComfyUIService) -> None:
    """ComfyUI health check should return available status on success."""
    mock_request = httpx.Request("GET", "https://comfyui.test.local/system_stats")
    mock_response = httpx.Response(
        200,
        json={
            "devices": [{"type": "cuda", "name": "NVIDIA GeForce RTX 4090"}],
            "exec_info": {"queue_remaining": 0},
        },
        request=mock_request,
    )

    with patch.object(
        httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_response
    ):
        status = await comfyui_service.check_health()

    assert status.available is True
    assert status.queue_remaining == 0
    assert status.cuda_available is True


async def test_check_health_cpu_only(comfyui_service: ComfyUIService) -> None:
    """ComfyUI health check should detect CPU-only mode."""
    mock_request = httpx.Request("GET", "https://comfyui.test.local/system_stats")
    mock_response = httpx.Response(
        200,
        json={
            "devices": [{"type": "cpu", "name": "CPU"}],
            "exec_info": {"queue_remaining": 5},
        },
        request=mock_request,
    )

    with patch.object(
        httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_response
    ):
        status = await comfyui_service.check_health()

    assert status.available is True
    assert status.queue_remaining == 5
    assert status.cuda_available is False


async def test_check_health_timeout(comfyui_service: ComfyUIService) -> None:
    """ComfyUI health check should return unavailable on timeout."""
    with patch.object(
        httpx.AsyncClient,
        "get",
        new_callable=AsyncMock,
        side_effect=httpx.TimeoutException("Connection timed out"),
    ):
        status = await comfyui_service.check_health()

    assert status.available is False


async def test_check_health_http_error(comfyui_service: ComfyUIService) -> None:
    """ComfyUI health check should return unavailable on HTTP error."""
    mock_response = httpx.Response(503)
    mock_response._request = httpx.Request("GET", "https://comfyui.test.local")

    with patch.object(
        httpx.AsyncClient,
        "get",
        new_callable=AsyncMock,
        side_effect=httpx.HTTPStatusError(
            "Service Unavailable", request=mock_response.request, response=mock_response
        ),
    ):
        status = await comfyui_service.check_health()

    assert status.available is False


async def test_check_health_no_url_configured() -> None:
    """ComfyUI health check should return unavailable when URL not configured."""
    service = ComfyUIService(url=None)
    status = await service.check_health()

    assert status.available is False


async def test_cloudflare_access_headers(
    comfyui_service_with_auth: ComfyUIService,
) -> None:
    """ComfyUI service should include Cloudflare Access headers when configured."""
    headers = comfyui_service_with_auth._get_headers()

    assert headers["CF-Access-Client-Id"] == "test-client-id"
    assert headers["CF-Access-Client-Secret"] == "test-client-secret"


async def test_no_auth_headers_when_not_configured(
    comfyui_service: ComfyUIService,
) -> None:
    """ComfyUI service should not include auth headers when not configured."""
    headers = comfyui_service._get_headers()

    assert "CF-Access-Client-Id" not in headers
    assert "CF-Access-Client-Secret" not in headers
