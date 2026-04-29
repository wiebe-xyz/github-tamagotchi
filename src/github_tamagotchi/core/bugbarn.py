"""BugBarn integration matching the setup-page API.

Provides init(), capture_error(), and capture_message() with the interface
described at /api/v1/setup/github-tamagotchi. Internally uses the installed
bugbarn-python SDK with a project-scoped transport.
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from typing import Any

import bugbarn as _sdk
from bugbarn.client import Envelope
from bugbarn.client import Transport as _Transport

# SSL context for direct layer7 connections (Cloudflare proxy bypassed via hostAliases;
# layer7 serves Traefik's self-signed cert on direct connections).
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

_project_slug: str = ""
_environment: str = "production"
_events_url: str = ""
_logs_url: str = ""
_api_key: str = ""


class _ProjectTransport(_Transport):  # type: ignore[misc]
    """SDK transport that injects X-BugBarn-Project and uses unverified SSL."""

    def __init__(self, api_key: str, endpoint: str, project: str) -> None:
        super().__init__(api_key=api_key, endpoint=endpoint)
        self._project = project

    def _send(self, event: Envelope) -> None:
        payload = json.dumps(event.to_payload()).encode()
        req = urllib.request.Request(
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
            with urllib.request.urlopen(req, timeout=2, context=_SSL_CTX) as r:
                r.read()
        except urllib.error.URLError:
            return


def init(
    *,
    api_key: str,
    endpoint: str,
    project_slug: str,
    environment: str = "production",
    install_excepthook: bool = False,
) -> None:
    """Initialise BugBarn for the project. Call once at application startup."""
    global _project_slug, _environment, _events_url, _logs_url, _api_key

    _project_slug = project_slug
    _environment = environment
    _api_key = api_key
    _events_url = f"{endpoint.rstrip('/')}/api/v1/events"
    _logs_url = f"{endpoint.rstrip('/')}/api/v1/logs"

    transport = _ProjectTransport(
        api_key=api_key,
        endpoint=_events_url,
        project=project_slug,
    )
    _sdk.init(
        api_key=api_key,
        endpoint=_events_url,
        install_excepthook=install_excepthook,
        transport=transport,
    )


def capture_error(
    exc: BaseException | str | object,
    *,
    extra: dict[str, Any] | None = None,
) -> bool:
    """Capture an exception and send it to BugBarn."""
    attributes: dict[str, Any] = {"environment": _environment}
    if extra:
        attributes.update(extra)
    return bool(_sdk.capture_exception(exc, attributes=attributes))


def capture_message(
    message: str,
    level: str = "info",
    data: dict[str, Any] | None = None,
) -> None:
    """Send a structured log message to BugBarn /api/v1/logs."""
    if not _api_key or not _logs_url:
        return
    entry: dict[str, Any] = {"level": level, "message": message}
    if data:
        entry["data"] = data
    payload = json.dumps({"logs": [entry]}).encode()
    req = urllib.request.Request(
        _logs_url,
        data=payload,
        method="POST",
        headers={
            "content-type": "application/json",
            "x-bugbarn-api-key": _api_key,
            "x-bugbarn-project": _project_slug,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=2, context=_SSL_CTX) as r:
            r.read()
    except urllib.error.URLError:
        pass
