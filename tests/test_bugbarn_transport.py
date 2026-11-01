"""The BugBarn transport keeps sending after a request times out."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from bugbarn.client import Envelope

from github_tamagotchi.core.bugbarn import _ProjectTransport


class _StallOnce:
    """Ingest that never answers its first request, then accepts every other one."""

    def __init__(self) -> None:
        self.received: list[str] = []
        self.first = threading.Event()
        self.release = threading.Event()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                self.rfile.read(int(self.headers.get("content-length", 0)))
                if not owner.first.is_set():
                    owner.first.set()
                    owner.release.wait(timeout=10)
                    return
                owner.received.append(self.path)
                self.send_response(202)
                self.end_headers()

            def log_message(self, *args: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/api/v1/events"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.release.set()
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def ingest() -> Iterator[_StallOnce]:
    server = _StallOnce()
    yield server
    server.close()


def _wait_for(condition: Callable[[], bool], seconds: float = 8.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.05)
    return False


def _event() -> Envelope:
    return Envelope(
        timestamp="2026-10-24T00:00:00Z",
        severityText="ERROR",
        body="boom",
        exception_type="RuntimeError",
        exception_message="boom",
    )


def test_event_is_sent_after_an_earlier_request_timed_out(ingest: _StallOnce) -> None:
    transport = _ProjectTransport(api_key="k", endpoint=ingest.url, project="p")
    try:
        transport.submit(_event())
        assert _wait_for(ingest.first.is_set)
        # The stalled request times out after the 2 s read limit.
        transport.submit(_event())
        assert _wait_for(lambda: bool(ingest.received)), "nothing sent after the timeout"
        assert transport._worker.is_alive()
    finally:
        transport.close()


def test_a_full_queue_is_logged_once(capsys: pytest.CaptureFixture[str]) -> None:
    transport = _ProjectTransport(
        api_key="k", endpoint="http://127.0.0.1:9/api/v1/events", project="p"
    )
    transport._closed.set()  # no worker draining: the queue stays full
    transport._worker.join(timeout=1)
    transport.queue.maxsize = 1
    assert transport.submit(_event())
    assert not transport.submit(_event())
    assert not transport.submit(_event())
    assert capsys.readouterr().err.count("queue full") == 1
