"""Structured logging configuration and BugBarn sink.

Configures structlog with a processor pipeline that:
- Renders JSON in production or colorized output in development
- Routes through Python stdlib logging so Sentry's LoggingIntegration captures events
- Ships every log entry to BugBarn POST /api/v1/logs with the project header
- Ships error-level events with exception context to BugBarn POST /api/v1/events
- Attaches log events as breadcrumbs on BugBarn exceptions
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import queue
import ssl
import threading
import urllib.error
import urllib.request

# BugBarn sits behind Cloudflare which handles SSL; direct server connections
# use Traefik's self-signed default cert, so we skip verification for this
# internal telemetry channel. The API key provides authentication.
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE
from datetime import UTC, datetime
from typing import Any

import structlog
from bugbarn.client import Envelope
from bugbarn.client import Transport as _BugBarnTransport


class _ProjectedTransport(_BugBarnTransport):  # type: ignore[misc]
    """BugBarn event transport that injects X-BugBarn-Project on every request."""

    def __init__(self, api_key: str, endpoint: str, project: str) -> None:
        super().__init__(api_key=api_key, endpoint=endpoint)
        self._project = project

    def _send(self, event: Envelope) -> None:
        payload = json.dumps(event.to_payload()).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=payload,
            method="POST",
            headers={
                "content-type": "application/json",
                "x-bugbarn-api-key": self.api_key,
                "x-bugbarn-project": self._project,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=2, context=_SSL_CTX) as response:
                response.read()
        except urllib.error.URLError:
            return


class _LogTransport:
    """Batching log shipper to BugBarn POST /api/v1/logs."""

    def __init__(self, endpoint: str, api_key: str, project: str) -> None:
        # Derive logs endpoint from events endpoint
        self._endpoint = endpoint.replace("/api/v1/events", "/api/v1/logs")
        self._api_key = api_key
        self._project = project
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1024)
        self._closed = threading.Event()
        self._worker = threading.Thread(
            target=self._run, name="bugbarn-logs", daemon=True
        )
        self._worker.start()

    def submit(self, level: str, message: str, data: dict[str, Any] | None) -> None:
        entry: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": level,
            "message": message,
        }
        if data:
            entry["data"] = data
        with contextlib.suppress(queue.Full):
            self._queue.put_nowait(entry)

    def _run(self) -> None:
        while not self._closed.is_set():
            batch: list[dict[str, Any]] = []
            try:
                batch.append(self._queue.get(timeout=0.5))
                self._queue.task_done()
                # Drain any additional queued entries to send in one batch
                while True:
                    try:
                        batch.append(self._queue.get_nowait())
                        self._queue.task_done()
                    except queue.Empty:
                        break
                self._send_batch(batch)
            except queue.Empty:
                pass

    def _send_batch(self, entries: list[dict[str, Any]]) -> None:
        payload = json.dumps({"logs": entries}).encode("utf-8")
        request = urllib.request.Request(
            self._endpoint,
            data=payload,
            method="POST",
            headers={
                "content-type": "application/json",
                "x-bugbarn-api-key": self._api_key,
                "x-bugbarn-project": self._project,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=5, context=_SSL_CTX) as response:
                response.read()
        except urllib.error.URLError:
            pass

    def close(self) -> None:
        self._closed.set()
        self._worker.join(timeout=2.0)


_log_transport: _LogTransport | None = None


def setup_bugbarn_sink(
    endpoint: str, api_key: str, project: str
) -> _ProjectedTransport:
    """Initialize BugBarn sinks and return a project-aware event transport.

    Call this before bugbarn.init(). Pass the returned transport to
    bugbarn.init(transport=...) so all exception events also carry the project header.
    """
    global _log_transport
    _log_transport = _LogTransport(endpoint=endpoint, api_key=api_key, project=project)
    return _ProjectedTransport(api_key=api_key, endpoint=endpoint, project=project)


def _bugbarn_processor(
    logger: object, method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Ship log entries to BugBarn and attach events as breadcrumbs on exceptions."""
    level = str(event_dict.get("level", "info"))
    message = str(event_dict.get("event", ""))
    data = {
        k: str(v)
        for k, v in event_dict.items()
        if k
        not in (
            "event",
            "level",
            "logger",
            "timestamp",
            "_record",
            "_from_structlog",
        )
    }

    # Ship to /api/v1/logs (active once setup_bugbarn_sink() has been called)
    if _log_transport is not None:
        _log_transport.submit(level, message, data or None)

    # Attach as breadcrumb so it appears as context on exception detail pages
    try:
        import bugbarn

        bugbarn.add_breadcrumb(
            category=str(event_dict.get("logger", "app")),
            message=message,
            level=level,
            data=data or None,
        )

        # Error-level events with exception info → full BugBarn exception event
        if level in ("error", "critical"):
            exc_info = event_dict.get("exc_info")
            if exc_info and exc_info is not True:
                exc_val = exc_info[1] if isinstance(exc_info, tuple) else exc_info
                if isinstance(exc_val, BaseException):
                    bugbarn.capture_exception(exc_val, extra=data or None)
    except Exception:
        pass

    return event_dict


def configure_logging() -> None:
    """Configure structlog and stdlib logging for the application.

    Call this once at application startup before any loggers are used.
    """
    is_dev = os.getenv("DEBUG", "").lower() in ("1", "true", "yes")

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        _bugbarn_processor,
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer() if is_dev else structlog.processors.JSONRenderer(),
        ],
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    # Suppress noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
