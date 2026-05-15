"""API-DRS export-bundle rendering.

Sprint 3 (S3-002) shipped the DataRequest lifecycle, scope validation,
and manifest-locking on delivery — but never actually rendered a
bundle. This module fills that gap: render_bundle(req) emits NDJSON
shaped by the parent DSA's allowed_scopes, prepare_and_deliver(req)
hashes the bytes + persists to the bundle store + flips the status.

Storage today is an in-process `BUNDLE_STORE` dict keyed by
manifest_sha256. Production swaps it for a MinIO client behind the
same get_bundle()/put_bundle() interface so call sites don't change.

NDJSON (newline-delimited JSON) chosen over CSV because:
- preserves nested types (lists, dicts) without flattening
- streaming-friendly for partners with large extracts
- single-line records are trivially scriptable on the partner side
- self-describing (each line is a complete JSON object)

Scope contract — render_bundle obeys ALL of these from
DSA.allowed_scopes, intersected with DataRequest.request_payload:
- `fields`: the exact dotted field keys allowed; absent = all defaults
- `sub_region_codes`: filter Households to this set; absent = all
- `programme_codes`: enforced upstream at submit; rendering ignores
- `max_rows_per_request`: hard cap on rows produced

Per-call AuditEvent is emitted by deliver_data_request (the lifecycle
service); this module is silent.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from apps.data_management.models import Household

from .models import DataRequest

# In-process bundle store. Maps manifest_sha256 -> bytes. Swap for a
# MinIO client when the object store lands; the interface
# (put/get/exists) is the seam.
BUNDLE_STORE: dict[str, bytes] = {}


# Default exportable Household fields, dotted-keyed. The full set is
# what an unrestricted DSA gets; allowed_scopes.fields trims this.
# NIN columns (nin_hash, nin_last4) are deliberately NOT on Household
# — they live on Member and require a separate, narrower DSA grant.
_HOUSEHOLD_DEFAULT_FIELDS = (
    "household.id",
    "household.sub_region_code",
    "household.urban_rural",
    "household.current_vulnerability_band",
    "household.current_pmt_score",
)


def _household_to_row(hh: Household, allowed_fields: list[str] | None) -> dict:
    """Project a Household to its dotted-key dict, then filter to the
    allowed_fields set. None means 'unrestricted' (all defaults)."""
    row: dict[str, Any] = {
        "household.id": hh.id,
        "household.sub_region_code": hh.sub_region_code or "",
        "household.urban_rural": hh.urban_rural or "",
        "household.current_vulnerability_band": hh.current_vulnerability_band or "",
        "household.current_pmt_score": (
            float(hh.current_pmt_score) if hh.current_pmt_score is not None else None
        ),
    }
    if allowed_fields is None:
        return row
    return {k: v for k, v in row.items() if k in allowed_fields}


def render_bundle(req: DataRequest) -> tuple[bytes, int]:
    """Build an NDJSON bundle for `req`, scoped by its parent DSA.

    Returns (bytes, row_count). Empty queryset → b"" and row_count=0
    (still a valid delivery — partner gets confirmation that the
    cohort is empty under their criteria).
    """
    scopes = req.dsa.allowed_scopes or {}
    payload = req.request_payload or {}
    allowed_fields = scopes.get("fields")
    dsa_sub_regions = scopes.get("sub_region_codes")
    payload_sub_regions = payload.get("sub_region_codes")
    dsa_cap = scopes.get("max_rows_per_request")
    payload_cap = payload.get("max_rows")

    qs = Household.objects.all().order_by("id")
    # DSA-side geographic restriction (mandatory if set).
    if dsa_sub_regions:
        qs = qs.filter(sub_region_code__in=dsa_sub_regions)
    # Request-side narrowing (must be subset; submit-time validation
    # already rejected supersets so this is a safe intersection).
    if payload_sub_regions:
        qs = qs.filter(sub_region_code__in=payload_sub_regions)

    # Row cap = min(DSA cap, request cap) — both default to no cap.
    caps = [c for c in (dsa_cap, payload_cap) if c is not None]
    if caps:
        qs = qs[:min(caps)]

    rows = [_household_to_row(hh, allowed_fields) for hh in qs]
    body = b"\n".join(
        json.dumps(r, sort_keys=True, default=str).encode("utf-8")
        for r in rows
    )
    return body, len(rows)


def put_bundle(manifest_sha256: str, body: bytes) -> None:
    """Persist a rendered bundle keyed by its manifest hash. Idempotent:
    re-puts of the same hash leave the existing bytes alone (the hash
    is content-addressable, so identical bytes are guaranteed)."""
    BUNDLE_STORE.setdefault(manifest_sha256, body)


def get_bundle(manifest_sha256: str) -> bytes | None:
    return BUNDLE_STORE.get(manifest_sha256)


def prepare_and_deliver(req: DataRequest, *, actor: str) -> DataRequest:
    """Render the bundle, hash it, persist it, mark the request delivered.

    Single seam used by the API action and by management commands /
    Celery tasks. Wraps render_bundle + put_bundle + the existing
    deliver_data_request lifecycle service so the audit chain is
    unchanged.
    """
    from .services import deliver_data_request  # local: cycle safety

    body, row_count = render_bundle(req)
    sha = hashlib.sha256(body).hexdigest()
    put_bundle(sha, body)
    return deliver_data_request(
        req, manifest_sha256=sha, row_count=row_count, actor=actor,
    )
