"""DATA-EXP serialisers.

DataRequestDraftSerializer produces the ADR-0023 D1 record-level-
handoff payload — the exact, locked key set DRS expects when the user
clicks "Request record-level data" on an aggregate view.

The serialiser is deliberately a plain class (not a DRF ModelSerializer)
because the input is an in-memory query description, not a model
instance, and the output shape is contractually frozen by the ADR.
"""

from __future__ import annotations

from .services import canonical_query_hash

# ADR-0023 D1 locked key set.
LOCKED_KEYS = (
    "source_module",
    "source_query_hash",
    "purpose_of_use",
    "requested_entity",
    "requested_fields",
    "geographic_scope",
    "filter_expression",
    "estimated_row_count",
    "explorer_session_id",
)


class DataRequestDraftSerializer:
    """Build the locked DRS-draft payload from an explorer query.

    Usage: ``DataRequestDraftSerializer.serialize(input_payload)``.

    Input keys: session_id, purpose_of_use, requested_entity,
    requested_fields, geographic_scope, filter_expression,
    estimated_row_count.
    """

    def __init__(self, payload: dict | None = None):
        # Accept zero-arg construction so callers can feature-detect
        # the API without supplying data.
        self._payload = payload or {}

    @classmethod
    def serialize(cls, payload: dict) -> dict:
        filter_expression = payload.get("filter_expression") or {}
        geographic_scope = payload.get("geographic_scope") or {}
        requested_entity = payload.get("requested_entity") or ""
        requested_fields = list(payload.get("requested_fields") or [])

        return {
            "source_module": "data_explorer",
            "source_query_hash": canonical_query_hash({
                "requested_entity": requested_entity,
                "requested_fields": requested_fields,
                "geographic_scope": geographic_scope,
                "filter_expression": filter_expression,
            }),
            "purpose_of_use": payload.get("purpose_of_use") or "",
            "requested_entity": requested_entity,
            "requested_fields": requested_fields,
            "geographic_scope": geographic_scope,
            "filter_expression": filter_expression,
            "estimated_row_count": int(payload.get("estimated_row_count") or 0),
            "explorer_session_id": payload.get("session_id"),
        }
