"""Outbound HTTP with bounded retries, in one place.

`pyproject.toml` says connectors "all share one client", and until now
that was true of the library and not of the policy: the only retry and
timeout rules in the repo lived inside
`apps/ingestion_hub/connectors/kobo.py`, private to it. A second live
integration had to either import a connector's private function or
write a third copy of the same loop. Both are the shape of defect this
registry keeps finding — one idea, two spellings, free to drift.

So the loop is here and the callers pass their policy in.

What it retries, and what it deliberately does not
--------------------------------------------------
Network errors and 5xx, because those are the upstream having a bad
moment. A 4xx comes straight back: 401 and 403 are credential problems
that must reach an operator rather than be hammered at, and 400 means
the request itself is wrong, so repeating it unchanged can only fail
again. Callers that need an exception add it through
`retry_statuses` — the STAAC partner API's 429, whose contract asks
for backoff with jitter.

Jitter matters when more than one client backs off at the same moment:
without it, two clients that hit the same rate limit retry in lockstep
and hit it together again. It is applied as a random extension of the
wait, never a reduction, so a `Retry-After` the server asked for is
always honoured in full.

The retries are an in-process loop rather than `urllib3.util.Retry`
because the caller times the whole attempt sequence — DIH reports it
as `ConnectionTestResult.latency_ms` — and urllib3's retries happen
below the layer that measurement wraps.
"""

from __future__ import annotations

import random
import time
from typing import Any

import requests
from requests.exceptions import RequestException

#: (connect, read) seconds. Tight enough that an operator pressing
#: "Test connection" is not left waiting ~30s in the worst case, loose
#: enough that a slow page of results is not mistaken for a failure.
DEFAULT_TIMEOUT = (5, 15)

#: Waits between attempts 1->2 and 2->3. Three attempts total.
DEFAULT_BACKOFFS = (1.0, 3.0)

#: How much a wait may be randomly extended by, as a fraction of
#: itself. Extends only — see the module docstring.
JITTER_FRACTION = 0.25

#: The longest a server's `Retry-After` is honoured before the caller
#: is told instead. A partner asking us to wait ten minutes inside a
#: scheduled job is not a wait, it is a failed run that should say so.
MAX_RETRY_AFTER_SECONDS = 60.0


def json_session(**headers: str) -> requests.Session:
    """A session for one call, not for the process.

    Sharing one session across callers would pool connections nicely
    and leak `Authorization` headers between credential profiles,
    which is a security surface worth not having. One session per
    call, built here so every caller gets the same `Accept`.
    """
    session = requests.Session()
    session.headers.update({"Accept": "application/json", **headers})
    return session


def _retry_after_seconds(response: requests.Response) -> float | None:
    """The server's own backoff instruction, in seconds, if usable.

    Only the delta-seconds form is read. The HTTP-date form is legal
    and rare, and parsing it wrong would produce a wait computed
    against a clock we do not share with the server.
    """
    raw = (response.headers.get("Retry-After") or "").strip()
    if not raw:
        return None
    try:
        seconds = float(raw)
    except ValueError:
        return None
    if seconds < 0:
        return None
    return min(seconds, MAX_RETRY_AFTER_SECONDS)


def request_with_retry(
    method: str,
    url: str,
    *,
    session: requests.Session,
    timeout: tuple[int, int] = DEFAULT_TIMEOUT,
    backoffs: tuple[float, ...] = DEFAULT_BACKOFFS,
    retry_statuses: tuple[int, ...] = (),
    **kwargs: Any,
) -> requests.Response:
    """Issue a request, retrying transient failures a bounded number
    of times, and raise the last error when the budget runs out.

    `backoffs` sets both the waits and the attempt count: n waits
    means n+1 attempts. `retry_statuses` adds specific non-5xx codes
    to the retryable set; a server-sent `Retry-After` on one of those
    replaces the backoff for that attempt.
    """
    attempts = 1 + len(backoffs)
    last_error: Exception | None = None
    for attempt in range(attempts):
        wait = backoffs[attempt] if attempt < len(backoffs) else 0.0
        try:
            response = session.request(method, url, timeout=timeout, **kwargs)
            status = response.status_code
            if status < 500 and status not in retry_statuses:
                return response
            last_error = RequestException(
                f"upstream {status} on {method} {url}",
            )
            asked = _retry_after_seconds(response)
            if asked is not None:
                wait = asked
        except RequestException as e:
            last_error = e
        if attempt == attempts - 1:
            break
        time.sleep(wait + random.random() * JITTER_FRACTION * wait)  # noqa: S311
    raise last_error or RequestException("retry budget exhausted")
