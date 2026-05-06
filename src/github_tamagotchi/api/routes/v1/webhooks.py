"""Webhook endpoint: GitHub event receiver."""

import logging

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

import github_tamagotchi.api.routes as _api_routes  # for test-patch-compatible symbol lookup
from github_tamagotchi import metrics as metrics_service
from github_tamagotchi.api.dependencies import DbSession
from github_tamagotchi.core.telemetry import get_tracer
from github_tamagotchi.models.webhook_event import WebhookEvent
from github_tamagotchi.services.webhook import EVENT_HANDLERS, verify_signature

logger = logging.getLogger(__name__)
_tracer = get_tracer(__name__)

router: APIRouter = APIRouter(prefix="/api/v1", tags=["webhooks"])


class WebhookResponse(BaseModel):
    status: str
    message: str


@router.post("/webhooks/github", response_model=WebhookResponse)
async def github_webhook(request: Request, session: DbSession) -> WebhookResponse:
    """Receive GitHub webhook events and update pet state."""
    body = await request.body()

    if _api_routes.settings.github_webhook_secret:
        signature = request.headers.get("X-Hub-Signature-256", "")
        secret = _api_routes.settings.github_webhook_secret
        if not signature or not verify_signature(body, signature, secret):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature",
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
    repo_owner = (
        repo.get("owner", {}).get("login", "")
        if isinstance(repo, dict)
        else ""
    )
    repo_name = (
        repo.get("name", "") if isinstance(repo, dict) else ""
    )
    action = (
        payload.get("action")
        if isinstance(payload, dict)
        else None
    )

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
                branch = (
                    payload.get("ref", "")
                    .removeprefix("refs/heads/")
                )
                payload_summary = (
                    f"pushed {len(commits)} commit(s)"
                    f" to {branch}"
                )
            elif event_type == "pull_request":
                pr = payload.get("pull_request", {})
                pr_number = pr.get("number", "?")
                pr_title = pr.get("title", "")
                payload_summary = (
                    f"{action} PR #{pr_number}: {pr_title}"
                )
            elif event_type == "issues":
                issue = payload.get("issue", {})
                issue_number = issue.get("number", "?")
                issue_title = issue.get("title", "")
                payload_summary = (
                    f"{action} issue #{issue_number}:"
                    f" {issue_title}"
                )
            elif event_type == "check_run":
                check_run = payload.get("check_run", {})
                name = check_run.get("name", "")
                conclusion = (
                    check_run.get("conclusion")
                    or check_run.get("status", "")
                )
                payload_summary = (
                    f"check run '{name}' {conclusion}"
                )
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
            await session.flush()
        except Exception:
            logger.exception("Failed to log webhook event")

        return WebhookResponse(
            status="processed", message=message
        )
