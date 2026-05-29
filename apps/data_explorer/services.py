"""DATA-EXP service facade — the public, stable entry-points the rest
of the system (and the test suite) call into. ADR-0023.

The underlying logic already lives in the focused modules:

- privacy-class ranking → validators._strictest
- aggregate execution + staleness → query_builder
- DRS handoff → handoff.perform_handoff

This module re-exposes that behaviour behind names the ADR locks and
adds the two things that didn't have a home yet:

1. `strictest_class(codes)` — the code-only ranking helper (validators
   works on PrivacyClass instances; callers that only hold codes use
   this).
2. `canonical_query_hash(query)` — order-independent sha256 over a
   logical query so two reorderings of the same filter correlate to
   one AggregateQueryLog row (a re-identification-correlation property,
   not a convenience).
3. `compute_staleness_seconds(matview_model, cadence_seconds)` — the
   single staleness seam. query_builder consults this so the stale-
   matview 503 path is testable without a live matview.
4. `create_handoff(...)` — keyword-shaped wrapper over
   handoff.perform_handoff that computes the canonical query hash for
   the caller.

No raw SQL. No writes against DAT.
"""

from __future__ import annotations

import hashlib
import json

# Privacy-class rank — Sensitive strictest, Public loosest. Mirrors
# validators._strictest but keyed on the code string so callers that
# only hold codes (not PrivacyClass rows) can rank without a DB hit.
_CLASS_RANK = {"public": 0, "internal": 1, "personal": 2, "sensitive": 3}


def strictest_class(codes: list[str]) -> str:
    """Return the strictest privacy-class code in `codes`.

    Sensitive > Personal > Internal > Public. Unknown codes rank as
    Public (0) so a stray value never silently loosens the result.
    """
    if not codes:
        return "public"
    return max(codes, key=lambda c: _CLASS_RANK.get(c, 0))


def _canonical(obj):
    """Recursively canonicalise for hashing: sort dict keys AND sort
    list elements. List-order independence is deliberate — a filter of
    {dwelling=thatch AND head_sex=F} is the same logical query as
    {head_sex=F AND dwelling=thatch}, so both must hash identically."""
    if isinstance(obj, dict):
        return {k: _canonical(obj[k]) for k in sorted(obj)}
    if isinstance(obj, list):
        items = [_canonical(x) for x in obj]
        return sorted(items, key=lambda x: json.dumps(x, sort_keys=True, default=str))
    return obj


def canonical_query_hash(query: dict) -> str:
    """sha256 hex over the canonical (key- and element-sorted) JSON of
    `query`. Stable across key/element reorderings of the same logical
    query."""
    canon = json.dumps(_canonical(query), sort_keys=True, default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def compute_staleness_seconds(matview_model, cadence_seconds: int = 0) -> int:
    """Seconds since the matview was last refreshed (0 when empty / no
    refreshed_at). The single staleness seam — query_builder.execute
    calls this so the stale-matview 503 branch can be forced in tests
    without a populated matview."""
    from .query_builder import _matview_freshness

    _refreshed_at, staleness = _matview_freshness(matview_model, cadence_seconds)
    return staleness


def create_handoff(*, session_id: str, actor: str, purpose_of_use: str,
                   requested_entity: str, requested_fields: list[str],
                   geographic_scope: dict, filter_expression: dict,
                   estimated_row_count: int, dsa_id: str = "",
                   requester_note: str = ""):
    """Seed a DRS draft from an aggregate view. Computes the canonical
    query hash for the caller, then delegates to
    handoff.perform_handoff (which builds the DRS payload, calls
    apps.data_requests.services.create_draft, and updates the
    ExplorerSession). Returns the HandoffResult.
    """
    from .handoff import perform_handoff

    source_query_hash = canonical_query_hash({
        "requested_entity": requested_entity,
        "requested_fields": requested_fields,
        "geographic_scope": geographic_scope,
        "filter_expression": filter_expression,
    })

    return perform_handoff(
        actor=actor,
        dsa_id=dsa_id,
        purpose_of_use=purpose_of_use,
        requested_entity=requested_entity,
        requested_fields=requested_fields,
        geographic_scope=geographic_scope,
        filter_expression=filter_expression,
        estimated_row_count=estimated_row_count,
        source_query_hash=source_query_hash,
        explorer_session_id=session_id,
        requester_note=requester_note,
    )
