"""Webhook endpoint: GitHub event receiver."""

import logging

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from github_tamagotchi import metrics as metrics_service
from github_tamagotchi.api.dependencies import DbSession
from github_tamagotchi.core.telemetry import get_tracer
from github_tamagotchi.models.webhook_event import WebhookEvent
from github_tamagotchi.services.webhook import (
    EVENT_HANDLERS,
    is_cloudflare_address,
    is_github_webhook_source,
)

logger = logging.getLogger(__name__)
_tracer = get_tracer(__name__)

router: APIRouter = APIRouter(prefix="/api/v1", tags=["webhooks"])


class WebhookResponse(BaseModel):
    status: str
    message: str


def _client_ip(request: Request) -> str | None:
    """The real origin IP behind our own proxy chain (Cloudflare, then Traefik).

    Traefik sets the last X-Forwarded-For entry to the peer that connected to
    it. When that peer is a Cloudflare edge address, Cloudflare vouches for
    the client address in Cf-Connecting-Ip, which it overwrites on every
    request. A request that reaches Traefik directly has a non-Cloudflare
    peer, so a forged Cf-Connecting-Ip from it is never read.

    Without that header, the header is walked from the right, skipping
    Cloudflare hops; entries further left are client-supplied and unused.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded:
        return request.client.host if request.client else None

    hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
    if hops and is_cloudflare_address(hops[-1]):
        connecting = request.headers.get("cf-connecting-ip", "").strip()
        if connecting:
            return connecting
    for hop in reversed(hops):
        if not is_cloudflare_address(hop):
            return hop
    return None


@router.post("/webhooks/github", response_model=WebhookResponse)
async def github_webhook(request: Request, session: DbSession) -> WebhookResponse:
    """Receive GitHub webhook events and update pet state."""
    client_ip = _client_ip(request)
    if not await is_github_webhook_source(client_ip):
        logger.warning("webhook rejected: source %s is not a GitHub address", client_ip)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Request does not originate from GitHub",
        )

    event_type = request.headers.get("X-GitHub-Event", "")
    if not event_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-GitHub-Event header",
        )

    metrics_service.webhooks_received_total.labels(event_type=event_type).inc()

    if event_type == "ping":
        return WebhookResponse(status="ok", message="pong")

    handler = EVENT_HANDLERS.get(event_type)
    if not handler:
        return WebhookResponse(
            status="ignored",
            message=f"event type '{event_type}' is not handled",
        )

    payload = await request.json()

    repo = payload.get("repository", {})
    repo_owner = repo.get("owner", {}).get("login", "") if isinstance(repo, dict) else ""
    repo_name = repo.get("name", "") if isinstance(repo, dict) else ""
    action = payload.get("action") if isinstance(payload, dict) else None

    with _tracer.start_as_current_span(
        "api.webhooks.process",
        attributes={
            "webhook.event_type": event_type,
            "webhook.action": action or "",
            "pet.repo_owner": repo_owner,
            "pet.repo_name": repo_name,
        },
    ) as span:
        payload_summary: str | None = None
        try:
            if event_type == "push":
                commits = payload.get("commits", [])
                branch = payload.get("ref", "").removeprefix("refs/heads/")
                payload_summary = f"pushed {len(commits)} commit(s) to {branch}"
            elif event_type == "pull_request":
                pr = payload.get("pull_request", {})
                pr_number = pr.get("number", "?")
                pr_title = pr.get("title", "")
                payload_summary = f"{action} PR #{pr_number}: {pr_title}"
            elif event_type == "issues":
                issue = payload.get("issue", {})
                issue_number = issue.get("number", "?")
                issue_title = issue.get("title", "")
                payload_summary = f"{action} issue #{issue_number}: {issue_title}"
            elif event_type == "check_run":
                check_run = payload.get("check_run", {})
                name = check_run.get("name", "")
                conclusion = check_run.get("conclusion") or check_run.get("status", "")
                payload_summary = f"check run '{name}' {conclusion}"
        except Exception:
            pass

        processed = False
        try:
            message = await handler(payload, session)
            processed = True
            metrics_service.webhooks_processed_total.inc()
        except Exception:
            metrics_service.webhooks_failed_total.inc()
            raise

        span.set_attribute("webhook.processed", processed)

        try:
            event_log = WebhookEvent(
                repo_owner=repo_owner,
                repo_name=repo_name,
                event_type=event_type,
                action=action,
                payload_summary=payload_summary,
                processed=processed,
            )
            session.add(event_log)
            await session.commit()
        except Exception:
            logger.exception("Failed to log webhook event")

        return WebhookResponse(status="processed", message=message)
