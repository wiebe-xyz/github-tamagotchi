"""Structured logging configuration.

Configures structlog with a processor pipeline that:
- Renders JSON in production (DEBUG=false) or colorized output in development
- Routes through Python's stdlib logging so Sentry's LoggingIntegration captures events
- Forwards all log events to BugBarn as breadcrumbs (errors also captured as exceptions)
"""

import logging
import os
from typing import Any

import structlog


def _bugbarn_processor(
    logger: object, method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Bridge structlog events into BugBarn breadcrumbs and exception capture."""
    try:
        import bugbarn  # imported lazily — not initialized at module load time

        level = str(event_dict.get("level", "info"))
        message = str(event_dict.get("event", ""))
        data = {
            k: str(v)
            for k, v in event_dict.items()
            if k not in ("event", "level", "logger", "timestamp", "_record", "_from_structlog")
        }

        bugbarn.add_breadcrumb(
            category=str(event_dict.get("logger", "app")),
            message=message,
            level=level,
            data=data or None,
        )

        # Capture error-level events with exception context as full BugBarn events
        if level in ("error", "critical"):
            exc_info = event_dict.get("exc_info")
            if exc_info and exc_info is not True:
                exc_val = exc_info[1] if isinstance(exc_info, tuple) else exc_info
                if isinstance(exc_val, BaseException):
                    bugbarn.capture_exception(exc_val, extra=data or None)
    except Exception:
        pass  # never let the logging pipeline raise

    return event_dict


def configure_logging() -> None:
    """Configure structlog and stdlib logging for the application.

    Call this once at application startup, before any loggers are used.
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
    # Remove any existing handlers to avoid duplicate output
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    # Suppress noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
