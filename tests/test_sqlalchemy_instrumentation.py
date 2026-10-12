"""The SQLAlchemy OpenTelemetry instrumentor must actually apply to the installed SQLAlchemy.

opentelemetry-instrumentation-sqlalchemy declares the SQLAlchemy range it supports and
silently instruments nothing outside it (BugBarn GT-38/GT-39: production ran SQLAlchemy
2.1.4 against a "<2.1.0" instrumentor, so no DB spans were produced).
"""

from collections.abc import Iterator

import pytest
from opentelemetry.instrumentation.dependencies import get_dependency_conflicts
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy import create_engine, text


def test_installed_sqlalchemy_is_inside_the_instrumentors_supported_range() -> None:
    conflict = get_dependency_conflicts(SQLAlchemyInstrumentor().instrumentation_dependencies())

    assert conflict is None, str(conflict)


@pytest.fixture
def spans() -> Iterator[InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    engine = create_engine("sqlite://")
    instrumentor = SQLAlchemyInstrumentor()
    instrumentor.instrument(engine=engine, tracer_provider=provider)
    with engine.connect() as conn:
        conn.execute(text("select 1"))
    instrumentor.uninstrument()
    yield exporter
    engine.dispose()


def test_instrumentor_emits_a_span_for_a_query(spans: InMemorySpanExporter) -> None:
    names = [s.name for s in spans.get_finished_spans()]

    assert names, "no database spans were produced"
