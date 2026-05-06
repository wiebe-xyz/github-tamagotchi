"""Structured logging configuration with BugBarn and Sentry sinks.

Configures structlog with a processor pipeline that:
- Renders JSON in production or colorized output in development
- Routes through Python stdlib logging so Sentry's LoggingIntegration captures events
- Ships every log entry to BugBarn /api/v1/logs via the project-aware wrapper
- Captures error-level events with exception context as BugBarn exceptions
- Attaches log events as breadcrumbs on BugBarn exception detail pages
"""

from __future__ import annotations

import contextlib
import logging
import os
import queue
import ssl
import threading
from datetime import UTC, datetime
from typing import Any

import structlog

# SSL context for direct layer7 connections — see core/bugbarn.py for rationale.
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

# Module-level log transport, set by setup_log_transport().
_log_transport: _LogTransport | None = None


class _LogTransport:
    """Batching background shipper to BugBarn POST /api/v1/logs."""

    def __init__(self, logs_url: str, api_key: str, project: str) -> None:
        import json
        import urllib.error
        import urllib.request

        self._url = logs_url
        self._api_key = api_key
        self._project = project
        self._json = json
        self._urllib_request = urllib.request
        self._urllib_error = urllib.error

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
        payload = self._json.dumps({"logs": entries}).encode()
        req = self._urllib_request.Request(
            self._url,
            data=payload,
            method="POST",
            headers={
                "content-type": "application/json",
                "x-bugbarn-api-key": self._api_key,
                "x-bugbarn-project": self._project,
            },
        )
        try:
            with self._urllib_request.urlopen(req, timeout=5, context=_SSL_CTX) as r:
                r.read()
        except self._urllib_error.URLError:
            pass

    def flush(self) -> None:
        """Drain remaining entries and send them before shutdown."""
        batch: list[dict[str, Any]] = []
        while True:
            try:
                batch.append(self._queue.get_nowait())
                self._queue.task_done()
            except queue.Empty:
                break
        if batch:
            self._send_batch(batch)

    def close(self) -> None:
        self._closed.set()
        self._worker.join(timeout=2.0)
        self.flush()


def setup_log_transport(logs_url: str, api_key: str, project: str) -> None:
    """Start the background log shipper. Call after bugbarn.init()."""
    global _log_transport
    _log_transport = _LogTransport(logs_url=logs_url, api_key=api_key, project=project)


def shutdown_log_transport() -> None:
    """Flush and stop the background log shipper. Call on app shutdown."""
    global _log_transport
    if _log_transport is not None:
        _log_transport.close()
        _log_transport = None


def _bugbarn_processor(
    logger: object, method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Ship log entries to BugBarn and attach events as breadcrumbs."""
    level = str(event_dict.get("level", "info"))
    message = str(event_dict.get("event", ""))
    data = {
        k: str(v)
        for k, v in event_dict.items()
        if k
        not in ("event", "level", "logger", "timestamp", "_record", "_from_structlog", "exc_info")
    }

    if _log_transport is not None:
        _log_transport.submit(level, message, data or None)

    try:
        import bugbarn as _sdk

        _sdk.add_breadcrumb(
            category=str(event_dict.get("logger", "app")),
            message=message,
            level=level,
            data=data or None,
        )

        if level in ("warning", "error", "critical"):
            exc_info = event_dict.get("exc_info")
            if exc_info and exc_info is not True:
                exc_val = exc_info[1] if isinstance(exc_info, tuple) else exc_info
                if isinstance(exc_val, BaseException):
                    from github_tamagotchi.core.bugbarn import capture_error

                    capture_error(exc_val, extra={"level": level, **(data or {})})
            elif level in ("error", "critical"):
                from github_tamagotchi.core.bugbarn import capture_error

                capture_error(message, extra=data or None)
    except Exception as proc_exc:
        import sys

        print(f"bugbarn processor error: {proc_exc}", file=sys.stderr)

    return event_dict


def _otel_trace_processor(
    logger: object, method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Inject OpenTelemetry trace/span IDs into every log entry."""
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx and ctx.trace_id != 0:
            event_dict["trace_id"] = format(ctx.trace_id, "032x")
            event_dict["span_id"] = format(ctx.span_id, "016x")
    except ImportError:
        pass
    return event_dict


def configure_logging() -> None:
    """Configure structlog and stdlib logging. Call once at application startup."""
    is_dev = os.getenv("DEBUG", "").lower() in ("1", "true", "yes")

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        _otel_trace_processor,
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

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
