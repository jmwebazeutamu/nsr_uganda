"""Handoff to API-DRS — DATA-EXP → apps.data_requests.

ADR-0023 D1 payload shape:
{
  "source_module": "data_explorer",
  "source_query_hash": "<sha256>",
  "purpose_of_use": "<free text>",
  "requested_entity": "Household" | "Member" | ...,
  "requested_fields": ["<variable.code>", ...],
  "geographic_scope": {"level": "...", "codes": [...]},
  "filter_expression": { ... },
  "estimated_row_count": <int>,
  "explorer_session_id": "<ULID>"
}

The handoff:
1. Creates / updates the ExplorerSession (so abandoned drafts are
   observable; OPEN-6 default = yes, DPO sees abandoned drafts).
2. Translates the explorer payload to the canonical DRS Query JSON
   (the legacy shape: fields[], sub_region_codes[], etc.).
3. Calls apps.data_requests.services.create_draft(...).
4. Returns {data_request_id, redirect_url, explorer_session_id}.

A small helper translates explorer geographic_scope → the
{region_codes, sub_region_codes, district_codes, ...} keys DRS
already validates against the DSA scope.
"""

from __future__ import annotations

from dataclasses import dataclass

_GEO_PAYLOAD_KEY = {
    "region": "region_codes",
    "sub_region": "sub_region_codes",
    "district": "district_codes",
    "county": "county_codes",
    "sub_county": "sub_county_codes",
    "parish": "parish_codes",
    "village": "village_codes",
}


@dataclass
class HandoffResult:
    data_request_id: str
    redirect_url: str
    explorer_session_id: str


def _translate_geographic_scope(scope: dict) -> dict:
    if not scope:
        return {}
    level = (scope.get("level") or "").lower()
    codes = list(scope.get("codes") or [])
    key = _GEO_PAYLOAD_KEY.get(level)
    if not key or not codes:
        return {}
    return {key: codes}


def _build_drs_payload(*, requested_fields: list[str],
                       geographic_scope: dict,
                       filter_expression: dict,
                       estimated_row_count: int,
                       requested_entity: str,
                       purpose_of_use: str) -> dict:
    payload = {
        "fields": list(requested_fields or []),
        "purpose_of_use": purpose_of_use or "",
        "entity": requested_entity or "",
        "filter_expression": filter_expression or {},
        "max_rows": int(estimated_row_count or 0),
    }
    payload.update(_translate_geographic_scope(geographic_scope))
    return payload


def perform_handoff(*, actor: str, dsa_id: str,
                    purpose_of_use: str,
                    requested_entity: str,
                    requested_fields: list[str],
                    geographic_scope: dict,
                    filter_expression: dict,
                    estimated_row_count: int,
                    source_query_hash: str = "",
                    explorer_session_id: str | None = None,
                    requester_note: str = "") -> HandoffResult:
    """Seed a DRS DataRequest from the explorer aggregate view. Creates
    an ExplorerSession if one isn't supplied so the audit trail
    references a stable anchor."""
    from apps.data_requests.services import create_draft

    from .models import ExplorerSession, HandoffStatus

    if explorer_session_id:
        session = (
            ExplorerSession.objects.filter(id=explorer_session_id).first()
        )
        if session is None:
            session = ExplorerSession.objects.create(
                id=explorer_session_id,
                actor=actor,
                purpose_of_use=purpose_of_use,
            )
    else:
        session = ExplorerSession.objects.create(
            actor=actor,
            purpose_of_use=purpose_of_use,
        )

    drs_payload = _build_drs_payload(
        requested_fields=requested_fields,
        geographic_scope=geographic_scope,
        filter_expression=filter_expression,
        estimated_row_count=estimated_row_count,
        requested_entity=requested_entity,
        purpose_of_use=purpose_of_use,
    )
    drs_payload["requested_entity"] = requested_entity

    # Positional-dict form — works with both the production
    # create_draft + contract-test monkeypatches that accept
    # (payload, *, requester).
    req = create_draft(
        {
            "dsa_id": dsa_id,
            "requester_note": requester_note,
            "request_payload": drs_payload,
            "source_module": "data_explorer",
            "explorer_session_id": str(session.id),
            "source_query_hash": source_query_hash,
        },
        requester=actor,
    )

    session.handoff_status = HandoffStatus.SUBMITTED
    session.data_request_id = str(req.id)
    session.purpose_of_use = purpose_of_use or session.purpose_of_use
    session.last_query_hash = source_query_hash or session.last_query_hash
    session.save(update_fields=[
        "handoff_status", "data_request_id",
        "purpose_of_use", "last_query_hash", "last_query_at",
    ])

    return HandoffResult(
        data_request_id=str(req.id),
        # UI deep-link convention (ADR §sequence-c): `/data-requests/<id>`.
        # The DRS API endpoint lives at `/api/v1/drs/requests/<id>/`,
        # but the operator console mounts the DRS workbench at
        # `/data-requests/` so we hand the operator a console URL,
        # not an API URL.
        redirect_url=f"/data-requests/{req.id}/",
        explorer_session_id=str(session.id),
    )
