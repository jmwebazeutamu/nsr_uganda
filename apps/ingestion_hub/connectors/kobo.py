"""Kobo Toolbox connector (US-S11-003a).

Talks to a Kobo Toolbox instance through its REST API (default
target: the OCHA humanitarian instance, `https://kobo.humanitarian
response.info`, which is what the project's first pilot runs
against).

Three live methods on top of the canonicalisation contract from
US-S8-005:

- test_connection(creds) — cheap GET against /api/v2/assets.json
  to confirm the token works and report round-trip latency. The
  Admin UI's "Test connection" button calls this before save.
- list_forms(creds) — enumerate the assets (forms) the token has
  read access to.
- pull_submissions(creds, form_id, since) — paginate through
  /api/v2/assets/{form_id}/data/ and yield each submission as a
  raw dict. The canonical mapper (kobo_to_canonical, when wired)
  will consume these per-record.

Credentials are passed in as a dict the caller has decrypted from
the KoboCredential row — the connector NEVER reads the DB
directly. Expected keys:
    {
      "server_url": "https://kobo.humanitarianresponse.info",
      "token": "abcdef…",   # Kobo Knox token, captured by the
                              # admin form's password-to-token
                              # exchange in commit 2
    }

For first-time setup (no token yet) the credentials dict carries
{"server_url", "username", "password"} and the connector exchanges
them via the token endpoint. Password is held only in this
function's local scope and never persisted as-is — the caller
writes the returned token back to KoboCredential and discards the
password. See acquire_token() below.

The httpx-vs-requests decision: `requests` was chosen so this
ships without a new ADR (option 5 of the BUG-S11-002 design
discussion). Retries use a small in-process loop rather than
urllib3.util.retry so the timing signal in ConnectionTestResult
.latency_ms reflects the full attempt sequence including backoffs.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from typing import Any

import requests
from requests.exceptions import RequestException

from .base import ConnectionTestResult, register_connector

logger = logging.getLogger(__name__)

# Retry policy: tight enough that a "Test connection" call doesn't
# block the admin form for more than ~30s in the worst case, loose
# enough that a transient 503 doesn't fail it. Three attempts at
# 1s/3s backoff equals at most ~19s of waits + the per-attempt
# read timeout.
DEFAULT_TIMEOUT = (5, 15)  # (connect, read), seconds
RETRY_BACKOFFS = (1.0, 3.0)  # waits between attempts 1->2 and 2->3
MAX_ATTEMPTS = 1 + len(RETRY_BACKOFFS)


def _request_with_retry(
    method: str, url: str, *, session: requests.Session,
    timeout: tuple[int, int] = DEFAULT_TIMEOUT,
    **kwargs: Any,
) -> requests.Response:
    """Wrap session.request with bounded retries on 5xx + network
    errors. 4xx responses (incl. 401/403) are returned immediately —
    those are authentication problems the caller surfaces to the
    Admin UI as `error=auth_failed`, not infrastructure flakiness."""
    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            response = session.request(method, url, timeout=timeout, **kwargs)
            if response.status_code < 500:
                return response
            last_error = RequestException(
                f"upstream {response.status_code} on {method} {url}",
            )
        except RequestException as e:
            last_error = e
        # Last attempt — stop retrying.
        if attempt == MAX_ATTEMPTS - 1:
            break
        time.sleep(RETRY_BACKOFFS[attempt])
    # Exhausted retries — caller turns this into a test-failure result.
    raise last_error or RequestException("retry budget exhausted")


def _new_session() -> requests.Session:
    """Build a per-call session. Sharing a process-level session
    would pool connections nicely BUT leak token Authorization
    headers between credential profiles, which is a security
    surface we don't need to manage today."""
    s = requests.Session()
    s.headers.update({"Accept": "application/json"})
    return s


def acquire_token(
    server_url: str, username: str, password: str,
    *, session: requests.Session | None = None,
) -> str:
    """Exchange username+password for a Kobo Knox token.

    Used ONCE, by the admin form's "Save" handler in commit 2.
    The password lives in the caller's stack frame and the
    returned token is what gets encrypted onto KoboCredential.
    This function deliberately never logs the password and never
    returns it.

    POST /token/?format=json
        body: { username, password }
        -> 200 { token: "..." }
        -> 401 on bad credentials (caller turns into auth_failed)
    """
    session = session or _new_session()
    url = f"{server_url.rstrip('/')}/token/?format=json"
    response = _request_with_retry(
        "POST", url, session=session,
        data={"username": username, "password": password},
    )
    if response.status_code == 401:
        raise RequestException("Kobo rejected credentials (401)")
    response.raise_for_status()
    token = response.json().get("token")
    if not token:
        raise RequestException("Kobo /token/ returned no token field")
    return token


class KoboConnector:
    """Kobo Toolbox HTTP connector.

    Registered under code "KOBO-PILOT" to match the SourceSystem.code
    seeded in scripts/seed_dih_sources.py. When a second Kobo instance
    is onboarded (e.g., MGLSD's own deployment), the second registration
    re-uses this class with a different SourceSystem code, and the
    Admin form passes its credentials in — connector instances are
    stateless across calls so one class can serve multiple SourceSystems
    pointing at different Kobo URLs.
    """

    code = "KOBO-PILOT"

    # The canonicalisation-only methods from US-S8-005 stay set to
    # None — Kobo's canonical mapping for submissions isn't part of
    # this story (see "Out of scope" in the prompt). When it lands,
    # it joins as a new module-level kobo_to_canonical and this
    # canonicalize attribute switches to it.
    canonicalize = None
    process = None

    def test_connection(self, credentials: dict) -> ConnectionTestResult:
        """Cheapest possible smoke test — list one asset, time it,
        read X-OpenRosa-Version if present."""
        server_url = credentials.get("server_url", "").rstrip("/")
        token = credentials.get("token")
        if not server_url or not token:
            return ConnectionTestResult(
                ok=False, latency_ms=0,
                error="server_url and token required",
            )

        session = _new_session()
        session.headers["Authorization"] = f"Token {token}"
        url = f"{server_url}/api/v2/assets.json?limit=1"
        started = time.perf_counter()
        try:
            response = _request_with_retry("GET", url, session=session)
        except RequestException as e:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return ConnectionTestResult(
                ok=False, latency_ms=latency_ms, error=str(e),
            )

        latency_ms = int((time.perf_counter() - started) * 1000)
        if response.status_code == 401:
            return ConnectionTestResult(
                ok=False, latency_ms=latency_ms,
                error="auth_failed: token rejected by upstream",
            )
        if response.status_code >= 400:
            return ConnectionTestResult(
                ok=False, latency_ms=latency_ms,
                error=f"upstream {response.status_code}",
            )
        # Kobo's response headers carry a server-version-ish field on
        # some deployments; capture it best-effort.
        server_version = (
            response.headers.get("X-OpenRosa-Version")
            or response.headers.get("Server")
        )
        return ConnectionTestResult(
            ok=True, latency_ms=latency_ms, server_version=server_version,
        )

    def list_forms(self, credentials: dict) -> list[dict]:
        """Return [{uid, name, asset_type, deployment__active}]."""
        server_url = credentials["server_url"].rstrip("/")
        session = _new_session()
        session.headers["Authorization"] = f"Token {credentials['token']}"
        url = f"{server_url}/api/v2/assets.json"
        response = _request_with_retry("GET", url, session=session)
        response.raise_for_status()
        return [
            {
                "uid": a.get("uid"),
                "name": a.get("name"),
                "asset_type": a.get("asset_type"),
                "deployed": bool(a.get("deployment__active")),
            }
            for a in response.json().get("results", [])
        ]

    def pull_submissions(
        self, credentials: dict, *, form_id: str, since: str | None = None,
    ) -> Iterator[dict]:
        """Yield each submission dict; paginates via the `next` link.

        `since` is forwarded to Kobo as a filter on _submission_time;
        Kobo's query DSL is mongo-style so the value is wrapped in
        a tiny shim. Future stories can extend this to richer
        filters when the schedule-builder lands.
        """
        server_url = credentials["server_url"].rstrip("/")
        session = _new_session()
        session.headers["Authorization"] = f"Token {credentials['token']}"
        url = f"{server_url}/api/v2/assets/{form_id}/data.json"
        params: dict[str, Any] = {}
        if since:
            # Kobo accepts a mongo-style JSON query in the `query` param.
            params["query"] = (
                '{"_submission_time": {"$gte": "' + since + '"}}'
            )
        while url:
            response = _request_with_retry(
                "GET", url, session=session, params=params,
            )
            response.raise_for_status()
            body = response.json()
            yield from body.get("results", [])
            # Subsequent pages come back with `next` already containing
            # the encoded query, so we drop our params from page 2 on.
            url = body.get("next")
            params = {}


register_connector(KoboConnector())
