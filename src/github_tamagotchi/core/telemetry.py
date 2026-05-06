"""OpenTelemetry tracing setup with auto-instrumentation and graceful degradation."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = structlog.get_logger()

_provider: Any = None


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

    exporter = OTLPSpanExporter()
    _provider.add_span_processor(BatchSpanProcessor(exporter))
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
