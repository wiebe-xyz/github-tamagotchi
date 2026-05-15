"""Tests for telemetry resilience helpers.

The OTel SDK logs span-export failures from several internal sites with
distinct messages — each becomes a separate BugBarn issue (GT-16/20/21 are
three fingerprints for the same upstream condition).

The fix has two parts:
1. `_make_resilient_exporter` — emits one warning per failed batch via our
   project logger so BugBarn groups them all under a single fingerprint.
   Events on that one issue are useful signal (volume, timing) and not a
   problem to reduce further.
2. `_detach_noisy_otel_loggers_from_bugbarn` — keeps the SDK's per-site logs
   visible in stdout/`kubectl logs` for upstream-health debugging but stops
   them propagating into the structlog → BugBarn pipeline.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

from opentelemetry.sdk.trace.export import SpanExportResult

from github_tamagotchi.core.telemetry import (
    _NOISY_OTEL_LOGGERS,
    _detach_noisy_otel_loggers_from_bugbarn,
    _make_resilient_exporter,
)


class _StubExporter:
    """Stand-in for OTLPSpanExporter — lets us pick the return value."""

    def __init__(self, result: SpanExportResult, **_: object) -> None:
        self._result = result

    def export(self, _spans: object) -> SpanExportResult:
        return self._result


def _make(result: SpanExportResult) -> object:
    return _make_resilient_exporter(_StubExporter)(result=result)


def test_success_does_not_log_warning() -> None:
    exporter = _make(SpanExportResult.SUCCESS)
    with patch("github_tamagotchi.core.telemetry.logger") as mock_logger:
        out = exporter.export([object(), object()])
        assert out == SpanExportResult.SUCCESS
        mock_logger.warning.assert_not_called()


def test_failure_emits_exactly_one_warning() -> None:
    exporter = _make(SpanExportResult.FAILURE)
    with patch("github_tamagotchi.core.telemetry.logger") as mock_logger:
        out = exporter.export([object(), object(), object()])
        assert out == SpanExportResult.FAILURE
        mock_logger.warning.assert_called_once()
        # The single log carries the batch size so BugBarn aggregates show volume
        kwargs = mock_logger.warning.call_args.kwargs
        assert kwargs.get("span_count") == 3


def test_repeated_failures_share_one_fingerprint() -> None:
    """Each failed batch is its own event but they all share one BugBarn fingerprint.

    Multiple events on a single issue are useful signal (volume, recency) — the
    invariant we care about is that all of them have the *same* message text so
    BugBarn groups them under one issue instead of opening new ones per call site.
    """
    exporter = _make(SpanExportResult.FAILURE)
    with patch("github_tamagotchi.core.telemetry.logger") as mock_logger:
        for _ in range(5):
            exporter.export([object()])
        assert mock_logger.warning.call_count == 5
        messages = {c.args[0] for c in mock_logger.warning.call_args_list}
        assert messages == {"Span batch dropped to spanbarn"}


def test_wrapped_exporter_subclasses_the_base() -> None:
    """Sanity: the resilient wrapper IS the base type, so SDK type checks pass."""
    cls = _make_resilient_exporter(_StubExporter)
    inst = cls(result=SpanExportResult.SUCCESS)
    assert isinstance(inst, _StubExporter)


def test_detach_stops_propagation_to_bugbarn_pipeline() -> None:
    """Noisy SDK loggers must not propagate to the root (where BugBarn lives)."""
    _detach_noisy_otel_loggers_from_bugbarn()
    for name in _NOISY_OTEL_LOGGERS:
        lg = logging.getLogger(name)
        assert lg.propagate is False, f"{name} should not propagate to root"


def test_detach_preserves_stdout_visibility() -> None:
    """Each detached logger gets a stream handler so logs still hit stdout/stderr."""
    _detach_noisy_otel_loggers_from_bugbarn()
    for name in _NOISY_OTEL_LOGGERS:
        lg = logging.getLogger(name)
        assert any(
            isinstance(h, logging.StreamHandler) for h in lg.handlers
        ), f"{name} should retain a StreamHandler for kubectl-logs visibility"


def test_detach_is_idempotent() -> None:
    """Re-running detach must not stack duplicate handlers."""
    _detach_noisy_otel_loggers_from_bugbarn()
    before = {name: len(logging.getLogger(name).handlers) for name in _NOISY_OTEL_LOGGERS}
    _detach_noisy_otel_loggers_from_bugbarn()
    _detach_noisy_otel_loggers_from_bugbarn()
    after = {name: len(logging.getLogger(name).handlers) for name in _NOISY_OTEL_LOGGERS}
    assert before == after
