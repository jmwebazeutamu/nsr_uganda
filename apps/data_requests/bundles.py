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

from apps.data_management.models import Household, Member

from .models import DataRequest
from .storage import get_bundle_storage

# Default exportable Household fields, dotted-keyed. The full set is
# what an unrestricted DSA gets; allowed_scopes.fields trims this.
_HOUSEHOLD_DEFAULT_FIELDS = (
    "household.id",
    "household.sub_region_code",
    "household.urban_rural",
    "household.current_vulnerability_band",
    "household.current_pmt_score",
)

# Default exportable Member fields. NIN columns (nin_hash, nin_last4)
# are SENSITIVE — included in the default set so an unrestricted DSA
# gets them, but a partner-facing DSA will normally not whitelist
# member.* fields at all, and most member.* DSAs will exclude the NIN
# columns explicitly. Either way the DSA scope is the gate.
_MEMBER_DEFAULT_FIELDS = (
    "member.id",
    "member.line_number",
    "member.surname",
    "member.first_name",
    "member.other_name",
    "member.sex",
    "member.date_of_birth",
    "member.age_years",
    "member.relationship_to_head",
    "member.telephone_1",
    "member.telephone_2",
    "member.nin_hash",
    "member.nin_last4",
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


def _member_to_dict(m: Member, allowed_fields: list[str] | None) -> dict:
    """Project a live Member to its dotted-key dict, then filter to
    the allowed member.* subset. None means 'unrestricted' defaults.

    nin_hash is bytes on the model; we surface it as a hex string for
    JSON portability. Soft-deleted members are excluded upstream
    (render_bundle filters is_deleted=False)."""
    row: dict[str, Any] = {
        "member.id": m.id,
        "member.line_number": m.line_number,
        "member.surname": m.surname or "",
        "member.first_name": m.first_name or "",
        "member.other_name": m.other_name or "",
        "member.sex": m.sex or "",
        "member.date_of_birth": (
            m.date_of_birth.isoformat() if m.date_of_birth else None
        ),
        "member.age_years": m.age_years,
        "member.relationship_to_head": m.relationship_to_head or "",
        "member.telephone_1": m.telephone_1 or "",
        "member.telephone_2": m.telephone_2 or "",
        "member.nin_hash": (bytes(m.nin_hash).hex() if m.nin_hash else ""),
        "member.nin_last4": m.nin_last4 or "",
    }
    if allowed_fields is None:
        return row
    return {k: v for k, v in row.items() if k in allowed_fields}


def _includes_member_fields(allowed_fields: list[str] | None) -> bool:
    """True if the DSA either grants member.* explicitly or is
    unrestricted (allowed_fields is None). Unrestricted DSAs get
    members embedded by default — that's what 'unrestricted' means."""
    if allowed_fields is None:
        return True
    return any(f.startswith("member.") for f in allowed_fields)


def render_bundle(req: DataRequest) -> tuple[bytes, int]:
    """Build an NDJSON bundle for `req`, scoped by its parent DSA.

    Returns (bytes, row_count). Empty queryset → b"" and row_count=0
    (still a valid delivery — partner gets confirmation that the
    cohort is empty under their criteria).

    Per ADR-0013 the DSA is the canonical one from apps.partners;
    field_scope, geographic_scope M2M, and monthly_row_budget drive
    the clipping. Legacy 'household.id' / 'member.name' style fields
    in request_payload.fields are mapped to canonical groups by
    prefix at render time.
    """
    payload = req.request_payload or {}
    dsa = req.dsa

    # Canonical field scope. Empty field_scope means unrestricted.
    field_groups = {k for k, v in (dsa.field_scope or {}).items() if v}
    # `allowed_fields` is the legacy-shaped list the projection helpers
    # below consume; build it from FIELD_CATALOGUE filtered by group.
    if field_groups:
        from .builder_schema import FIELD_CATALOGUE
        allowed_fields = [
            cat["key"] for cat in FIELD_CATALOGUE
            if cat["key"].partition(".")[0] in field_groups
            or cat["group"] in field_groups
        ]
    else:
        allowed_fields = None  # unrestricted

    # Canonical geographic scope. Sub-region codes from the M2M.
    dsa_sub_regions = list(
        dsa.geographic_scope
        .filter(level="sub_region")
        .values_list("code", flat=True),
    )
    payload_sub_regions = payload.get("sub_region_codes")
    dsa_cap = dsa.monthly_row_budget
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

    embed_members = _includes_member_fields(allowed_fields)
    member_allowed = (
        [f for f in allowed_fields if f.startswith("member.")]
        if allowed_fields is not None else None
    )

    # US-CONSENT-14 — row-level consent gate. The DSA scope may map to one or
    # more consent purposes (e.g. a RESEARCH-scoped DSA → RESEARCH). Members who
    # withdrew or refused any mapped purpose are excluded at the SQL layer so an
    # application-layer bug cannot leak un-consented rows (CR7). Inert when the
    # DSA declares no consent_purposes or CONSENT_MODULE_ENABLED is off. A
    # STATISTICS-scoped DSA serves aggregates only (Data Explorer), so it never
    # reaches this record-level path and declares no consent_purposes here.
    from apps.consent import services as consent_services
    consent_purposes = list((dsa.entities_scope or {}).get("consent_purposes", []))
    blocked_member_ids: set[str] = set()
    for _pc in consent_purposes:
        blocked_member_ids.update(consent_services.blocked_member_ids(_pc))

    rows: list[dict] = []
    for hh in qs:
        row = _household_to_row(hh, allowed_fields)
        if embed_members:
            members = (
                Member.objects.filter(household=hh, is_deleted=False)
                .exclude(id__in=blocked_member_ids)
                .order_by("line_number")
            )
            row["members"] = [
                _member_to_dict(m, member_allowed) for m in members
            ]
        rows.append(row)

    body = b"\n".join(
        json.dumps(r, sort_keys=True, default=str).encode("utf-8")
        for r in rows
    )
    return body, len(rows)


def put_bundle(manifest_sha256: str, body: bytes) -> None:
    """Persist a rendered bundle keyed by its manifest hash. Idempotent:
    re-puts of the same hash leave the existing bytes alone (the hash
    is content-addressable, so identical bytes are guaranteed).
    Backend selected by settings.DRS_BUNDLE_STORAGE."""
    get_bundle_storage().put(manifest_sha256, body)


def get_bundle(manifest_sha256: str) -> bytes | None:
    return get_bundle_storage().get(manifest_sha256)


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
