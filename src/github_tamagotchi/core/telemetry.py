"""OpenTelemetry tracing setup with auto-instrumentation and graceful degradation."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = structlog.get_logger()

_provider: Any = None

# The OTel SDK logs span-export failures at ERROR from several internal sites
# ("Failed to export span batch code: ...", "Failed to export span batch due to
# timeout, max retries or shutdown.", etc.). Each unique message becomes a
# separate BugBarn fingerprint, which spams the issue tracker with multiple
# entries for what is one upstream condition. We silence those specific loggers
# and consolidate the signal into a single log emitted by
# `_ResilientOTLPSpanExporter` below.
_NOISY_OTEL_LOGGERS = (
    "opentelemetry.exporter.otlp.proto.http.trace_exporter",
    "opentelemetry.sdk.trace.export",
)


def _detach_noisy_otel_loggers_from_bugbarn() -> None:
    """Stop the OTel SDK's per-site export-failure logs from feeding BugBarn.

    Each distinct message ("Failed to export span batch code: 404…",
    "Failed to export span batch due to timeout…", etc.) is a separate BugBarn
    fingerprint, which is why one upstream condition surfaced as three issues
    (GT-16, GT-20, GT-21). We set `propagate=False` so these loggers no longer
    flow into the root structlog/BugBarn pipeline, and attach a plain stderr
    handler so `kubectl logs` still shows them for upstream-health debugging.
    The single BugBarn signal for "spans dropped" is then emitted by
    `_make_resilient_exporter` below.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    for name in _NOISY_OTEL_LOGGERS:
        lg = logging.getLogger(name)
        lg.propagate = False
        if not lg.handlers:
            lg.addHandler(handler)


def _make_resilient_exporter(base_cls: type) -> type:
    """Factory for a span exporter that consolidates failures into one log.

    The OTel SDK's own exporter logs span-export failures at ERROR from several
    internal sites, each becoming a distinct BugBarn fingerprint. The returned
    subclass calls `base_cls.export()` and emits exactly one warning log via
    our project logger when the result is FAILURE — letting BugBarn group all
    upstream spanbarn outages under a single fingerprint.
    """
    from opentelemetry.sdk.trace.export import SpanExportResult

    class _ResilientExporter(base_cls):  # type: ignore[misc]
        def export(self, spans: Any) -> Any:
            result = super().export(spans)
            if result == SpanExportResult.FAILURE:
                logger.warning(
                    "Span batch dropped to spanbarn",
                    span_count=len(spans),
                )
            return result

    return _ResilientExporter


def init_telemetry(app: FastAPI) -> None:
    """Initialize OpenTelemetry tracing. No-op when disabled or packages missing."""
    global _provider

    from github_tamagotchi.core.config import settings

    if not settings.otel_enabled:
        logger.info("OpenTelemetry disabled")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
    except ImportError:
        logger.warning("OpenTelemetry packages not installed, tracing disabled")
        return

    resource = Resource.create({
        "service.name": settings.otel_service_name,
        "deployment.environment": os.getenv("ENVIRONMENT", "production"),
    })

    sampler = TraceIdRatioBased(settings.otel_traces_sample_rate)
    _provider = TracerProvider(resource=resource, sampler=sampler)

    _detach_noisy_otel_loggers_from_bugbarn()

    exporter = _make_resilient_exporter(OTLPSpanExporter)(timeout=5)
    _provider.add_span_processor(BatchSpanProcessor(
        exporter,
        max_export_batch_size=128,
        export_timeout_millis=5000,
    ))
    trace.set_tracer_provider(_provider)

    FastAPIInstrumentor.instrument_app(app)

    from github_tamagotchi.core.database import engine
    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)

    HTTPXClientInstrumentor().instrument()

    endpoint = os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT", ""
    )
    logger.info(
        "OpenTelemetry initialized",
        endpoint=endpoint,
        sample_rate=settings.otel_traces_sample_rate,
    )


def shutdown_telemetry() -> None:
    """Flush and shut down the tracer provider."""
    global _provider
    if _provider is None:
        return
    try:
        _provider.force_flush()
        _provider.shutdown()
    except Exception:
        logger.warning("OpenTelemetry shutdown error", exc_info=True)
    _provider = None


def get_tracer(name: str) -> Any:
    """Return a tracer for the given module. Returns a no-op tracer when OTel is disabled."""
    try:
        from opentelemetry import trace
        return trace.get_tracer(name)
    except ImportError:
        return _NoOpTracer()


class _NoOpSpan:
    """Minimal no-op span for when OTel is not installed."""

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        pass

    def set_status(self, status: Any, description: str | None = None) -> None:
        pass

    def __enter__(self) -> _NoOpSpan:
        return self

    def __exit__(self, *args: Any) -> None:
        pass


class _NoOpTracer:
    """Minimal no-op tracer for when OTel is not installed."""

    def start_as_current_span(self, name: str, **kwargs: Any) -> _NoOpSpan:
        return _NoOpSpan()
