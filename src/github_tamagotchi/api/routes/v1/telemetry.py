"""Browser telemetry proxy: forwards SDK spans to SpanBarn with the API key added server-side."""

import time
from collections import defaultdict, deque
from typing import Any

import httpx
import structlog
from fastapi import APIRouter, Request, Response, status

from github_tamagotchi.core.config import settings

logger = structlog.get_logger()

router: APIRouter = APIRouter(prefix="/api/v1", tags=["telemetry"])

MAX_BODY_BYTES = 64 * 1024
MAX_SPANS_PER_REQUEST = 100
# Public pages post here without a session, so each client address gets a modest budget.
RATE_LIMIT_REQUESTS = 60
RATE_LIMIT_WINDOW_SECONDS = 60.0

_recent: dict[str, deque[float]] = defaultdict(deque)


def is_enabled() -> bool:
    return bool(settings.spanbarn_api_key and settings.otel_exporter_otlp_endpoint)


def _rate_limited(client: str) -> bool:
    now = time.monotonic()
    hits = _recent[client]
    while hits and now - hits[0] > RATE_LIMIT_WINDOW_SECONDS:
        hits.popleft()
    if not hits:
        # Drop idle clients so the table cannot grow without bound.
        _recent.pop(client, None)
        hits = _recent[client]
    if len(hits) >= RATE_LIMIT_REQUESTS:
        return True
    hits.append(now)
    return False


def _valid_spans(payload: Any) -> list[dict[str, Any]] | None:
    if not isinstance(payload, dict):
        return None
    spans = payload.get("spans")
    if not isinstance(spans, list) or not spans or len(spans) > MAX_SPANS_PER_REQUEST:
        return None
    if not all(isinstance(s, dict) for s in spans):
        return None
    return spans


@router.post("/telemetry/api/v1/spans", status_code=status.HTTP_204_NO_CONTENT)
async def forward_spans(request: Request) -> Response:
    """Accept spans from the browser SDK (its transport posts to `<endpoint>/api/v1/spans`)."""
    if not is_enabled():
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    client = request.client.host if request.client else "unknown"
    if _rate_limited(client):
        return Response(status_code=status.HTTP_429_TOO_MANY_REQUESTS)

    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        return Response(status_code=status.HTTP_413_CONTENT_TOO_LARGE)
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        return Response(status_code=status.HTTP_413_CONTENT_TOO_LARGE)

    try:
        spans = _valid_spans(await request.json())
    except ValueError:
        spans = None
    if spans is None:
        return Response(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)

    base = (settings.otel_exporter_otlp_endpoint or "").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=5.0) as http:
            resp = await http.post(
                f"{base}/api/v1/spans",
                json={"spans": spans},
                headers={"X-SpanBarn-Api-Key": settings.spanbarn_api_key or ""},
            )
        if resp.status_code >= 400:
            logger.warning("telemetry_forward_rejected", status=resp.status_code)
            return Response(status_code=status.HTTP_502_BAD_GATEWAY)
    except httpx.HTTPError as e:
        logger.warning("telemetry_forward_failed", error=str(e))
        return Response(status_code=status.HTTP_502_BAD_GATEWAY)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
