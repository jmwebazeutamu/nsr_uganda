"""The HTTP half: talk to STAAC, return dictionaries.

Nothing here knows what a grievance is. It authenticates, pages, and
hands back what the partner said, so the mapping can be tested without
a socket and this can be tested without a database.

Five places where the served API differs from the written spec, each
found by reading STAAC's code rather than its documentation, and each
handled here so the mapping layer never sees the difference:

* `source.received_at` is `+00:00`-offset, not `Z`, because the
  snapshot is frozen with `datetime.isoformat()`. The list endpoint's
  timestamps *are* `Z`. `parse_datetime` accepts both, so both are
  simply parsed rather than pattern-matched.
* `location.display_name` is `str(Parish)`, which is
  `"BUJUMBA [101.1.01.01]"` and not the bare name the spec shows. It
  is carried through untouched and never used as a name — this
  registry resolves its own labels.
* `location.parish_key` is the deepest key the case was coded to, so
  it may name a district, county, sub-county, parish or village, or
  be empty. Nothing here assumes four components.
* `shared_data.fields` arrives alphabetically sorted by STAAC's admin
  view, so it is compared as a set wherever it is compared at all.
* The cursor is signed with no expiry, so the one thing that
  invalidates it is a key change on STAAC's side — which surfaces as
  a 400. That is treated as "start from the beginning", not an error,
  because the alternative is a pull that can never resume.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from requests.exceptions import RequestException

from nsr_mis.common.http import (
    DEFAULT_TIMEOUT,
    json_session,
    request_with_retry,
)

#: Spec §4: base path under the partner's origin.
PARTNER_PATH = "/api/v1/integration/partners/handovers/"

#: Spec §5 asks for backoff with jitter on 429. 5xx is retried by the
#: shared loop already.
RETRY_STATUSES = (429,)

#: Spec §4.1: "Integer 1-200; default 100."
MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 100

#: A page count no legitimate collection will reach, so a cursor that
#: fails to advance ends the run instead of looping forever. STAAC
#: orders by availability time and id and returns null at the end; a
#: cursor that returns itself is a bug on one side or the other, and
#: an infinite loop is the worst way to find out.
MAX_PAGES = 1000


class StaacError(Exception):
    """The partner could not be read. Carries the status where there
    was one, so a caller can tell "stop and call the IG" (401/403)
    from "try again later" (5xx)."""

    def __init__(self, message: str, *, status: int | None = None):
        self.status = status
        super().__init__(message)


class CursorRejected(StaacError):
    """STAAC refused the stored cursor. Recoverable by restarting the
    collection from the beginning — see the module docstring."""


def _version(raw) -> int:
    """The exchange version STAAC sent, refusing to invent one.

    It is half the idempotency key. Defaulting a missing value to 1
    would make two genuinely different snapshots of one case collide
    on `(handover_id, 1)`, and the second would be recognised as
    already held and never fetched — a re-offered complaint discarded
    in silence, which is the failure this whole design exists to
    prevent.
    """
    try:
        version = int(raw)
    except (TypeError, ValueError):
        version = 0
    if version < 1:
        raise StaacError(
            f"STAAC sent exchange_version {raw!r}, which cannot be half of "
            "an idempotency key. Refusing rather than assuming 1.",
        )
    return version


@dataclass(frozen=True)
class HandoverRef:
    """A row from the collection. Operational metadata only: the list
    endpoint never carries identity, narrative, location, category or
    severity, by design."""

    handover_id: str
    exchange_version: int
    tracking_number: str = ""
    programme_code: str = ""
    state: str = ""
    available_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class Snapshot:
    """A detail response, plus what the transport said about it.

    `body` is kept verbatim: it is the thing this registry stores as
    its immutable landing, and anything derived from it can be
    re-derived.
    """

    handover_id: str
    exchange_version: int
    body: dict
    etag: str = ""
    correlation_id: str = ""
    not_modified: bool = False

    @property
    def fields_manifest(self) -> list[str]:
        shared = self.body.get("shared_data") or {}
        return list(shared.get("fields") or [])


@dataclass
class StaacClient:
    """A pull client bound to one credential.

    `token` is never logged, never placed in a URL, and never put in
    an exception message — spec §7. The session carries it and is
    built per call, so it cannot outlive the request or be reused by
    another credential.
    """

    base_url: str
    token: str
    #: The shared default, not a copy of it. A third spelling of
    #: (5, 15) is exactly what moving the loop to `common.http` was
    #: for.
    timeout: tuple[int, int] = DEFAULT_TIMEOUT
    #: Overridable so a caller can correlate a whole run. STAAC
    #: returns the value, or issues one when absent.
    correlation_id: str = field(default="")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            # Spec §4.3: handover payloads carry approved identity and
            # narrative, so they must not land in a shared cache.
            "Cache-Control": "no-store",
            "X-Correlation-ID": self.correlation_id or str(uuid.uuid4()),
        }

    def _url(self, suffix: str = "") -> str:
        return f"{self.base_url.rstrip('/')}{PARTNER_PATH}{suffix}"

    def _get(self, url: str, *, params=None, extra_headers=None):
        session = json_session()
        headers = {**self._headers(), **(extra_headers or {})}
        try:
            return request_with_retry(
                "GET", url, session=session, timeout=self.timeout,
                retry_statuses=RETRY_STATUSES, params=params, headers=headers,
            )
        except RequestException as e:
            # The message may carry the URL but never the token: the
            # token travels in a header, and the header is not echoed.
            raise StaacError(f"STAAC was unreachable: {e}") from e
        finally:
            session.close()

    @staticmethod
    def _refuse(response) -> None:
        """Turn a non-200 into the error the spec's table prescribes."""
        status = response.status_code
        if status == 200:
            return
        if status == 400:
            raise CursorRejected(
                "STAAC rejected the request as invalid (400) — if a cursor "
                "was sent it is no longer valid and the collection must be "
                "read from the beginning",
                status=400,
            )
        if status == 401:
            raise StaacError(
                "STAAC refused the credential (401). It is missing, expired, "
                "revoked, or this registry is calling from an address the IG "
                "has not approved. Stop and contact the IG.",
                status=401,
            )
        if status == 403:
            raise StaacError(
                "The credential lacks the capability for this call (403). "
                "Stop and contact the IG administrator.",
                status=403,
            )
        if status == 404:
            raise StaacError(
                "STAAC has no such handover (404) — unknown, withdrawn, or "
                "belonging to another programme.",
                status=404,
            )
        if status == 406:
            raise StaacError(
                "STAAC did not accept the request's Accept header (406).",
                status=406,
            )
        raise StaacError(f"STAAC returned {status}.", status=status)

    def list_page(
        self, *, cursor: str = "", limit: int = DEFAULT_PAGE_SIZE,
        changed_since: str = "",
    ) -> tuple[list[HandoverRef], str]:
        """One page of the collection, and the cursor after it.

        Returns `(refs, next_cursor)`; an empty `next_cursor` means
        the collection is exhausted. `changed_since` is first-request
        only and the spec forbids sending it with a cursor, so it is
        dropped when one is present rather than sent and refused.
        """
        params: dict[str, Any] = {"limit": max(1, min(int(limit), MAX_PAGE_SIZE))}
        if cursor:
            params["cursor"] = cursor
        elif changed_since:
            params["changed_since"] = changed_since

        response = self._get(self._url(), params=params)
        self._refuse(response)
        body = response.json() or {}
        refs = [
            HandoverRef(
                handover_id=str(row.get("handover_id") or ""),
                exchange_version=_version(row.get("exchange_version")),
                tracking_number=str(row.get("tracking_number") or ""),
                programme_code=str(row.get("programme_code") or ""),
                state=str(row.get("state") or ""),
                available_at=str(row.get("available_at") or ""),
                updated_at=str(row.get("updated_at") or ""),
            )
            for row in (body.get("items") or [])
            if row.get("handover_id")
        ]
        return refs, str(body.get("next_cursor") or "")

    def iter_refs(
        self, *, cursor: str = "", limit: int = DEFAULT_PAGE_SIZE,
        changed_since: str = "",
    ) -> Iterator[tuple[list[HandoverRef], str]]:
        """Walk the collection page by page.

        Yields `(refs, cursor_after_this_page)` rather than individual
        rows, because the caller may only persist a cursor once every
        record on its page is stored — spec §"What the NSR team must
        build", step 5. Yielding rows would make that impossible to
        honour.
        """
        seen: set[str] = set()
        for _ in range(MAX_PAGES):
            refs, next_cursor = self.list_page(
                cursor=cursor, limit=limit, changed_since=changed_since,
            )
            yield refs, next_cursor
            if not next_cursor:
                return
            if next_cursor in seen:
                raise StaacError(
                    "STAAC returned a cursor it had already returned; "
                    "stopping rather than paging forever.",
                )
            seen.add(next_cursor)
            cursor = next_cursor
            changed_since = ""
        raise StaacError(
            f"The collection did not end within {MAX_PAGES} pages.",
        )

    def fetch(self, handover_id: str, *, etag: str = "") -> Snapshot:
        """One immutable snapshot.

        Sending `If-None-Match` lets STAAC answer 304 for a snapshot
        already held, which is the whole point of storing the ETag:
        re-reading a handover to reconcile should not re-transfer a
        complainant's identity.
        """
        headers = {"If-None-Match": etag} if etag else None
        response = self._get(self._url(f"{handover_id}/"), extra_headers=headers)
        correlation = str(response.headers.get("X-Correlation-ID") or "")
        if response.status_code == 304:
            # Version intentionally absent: a 304 carries no body, so
            # there is no version to report and the caller keeps the
            # one it already holds.
            return Snapshot(
                handover_id=str(handover_id), exchange_version=0, body={},
                etag=etag, correlation_id=correlation, not_modified=True,
            )
        self._refuse(response)
        body = response.json() or {}
        return Snapshot(
            handover_id=str(body.get("handover_id") or handover_id),
            exchange_version=_version(body.get("exchange_version")),
            body=body,
            etag=str(response.headers.get("ETag") or ""),
            correlation_id=correlation,
        )
