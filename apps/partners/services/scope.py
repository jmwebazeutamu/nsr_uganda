"""DSA scope-edit + clone helpers — US-S27-003 / ADR-0016.

`edit_scope(dsa, *, actor, **changes)` is the single orchestrating
call the `/api/v1/dsas/{id}/edit-scope/` endpoint surfaces.

  - On a draft DSA: applies the requested changes in place and
    emits one `dsa_scope_changed` audit event with the before/after
    diff. No version bump, no signature requirement.

  - On an active DSA: clones v(N) into a fresh v(N+1) draft via
    `clone_to_draft`, applies the changes on the clone, and returns
    the new draft. v(N) is untouched. The caller is then expected
    to dispatch the new draft through the ADR-0012 sign-off chain.

ADR-0016 §"Decision 2" makes the version bump on an active DSA
mandatory because the original is a signed legal instrument under
DPPA 2019; any scope change creates a new instrument needing the
same three signatures.

`clone_to_draft(dsa, *, actor, reason)` is exported for reuse by
the renewal endpoint (US-S27-005). Both paths share the same
copy-the-scope-and-reset-signatures behaviour.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db import transaction

from apps.security.audit import emit as emit_audit

if TYPE_CHECKING:
    from apps.partners.models import DataSharingAgreement


# Fields the operator can change via /edit-scope/. Anything else
# the caller submits is ignored — keeps the API tight per
# ADR-0016 §"Decision 1". `programmes` is intentionally absent:
# attaching/detaching a programme is a different operation from
# changing the scope of an existing attachment.
_SCALAR_SCOPE_FIELDS = (
    "field_scope",
    "entities_scope",
    "monthly_row_budget",
    "sensitive_data_handling",
    "retention_days",
    "classification",
    "dpia_document_ref",
    "breach_sla_hours",
)

# Mutating an M2M requires its own dance — handled separately.
_M2M_SCOPE_FIELD = "geographic_scope_ids"

# DSA statuses for which /edit-scope/ has a defined behaviour.
# Anything else (pending_signature, expiring, expired, suspended,
# renewed) is rejected.
_EDITABLE_STATUSES = ("draft", "active")


class ScopeEditError(Exception):
    """Raised when /edit-scope/ refuses the operation. The viewset
    converts this into a 400 response."""


def _snapshot_scope(dsa: DataSharingAgreement) -> dict[str, Any]:
    """Capture the current scope as a JSON-friendly dict for the
    before/after audit diff. Geographic IDs are sorted so before/
    after comparisons are deterministic across test runs."""
    return {
        "field_scope": dict(dsa.field_scope or {}),
        "entities_scope": dict(dsa.entities_scope or {}),
        "monthly_row_budget": dsa.monthly_row_budget,
        "sensitive_data_handling": dsa.sensitive_data_handling,
        "retention_days": dsa.retention_days,
        "classification": dsa.classification,
        "dpia_document_ref": dsa.dpia_document_ref,
        "breach_sla_hours": dsa.breach_sla_hours,
        "geographic_scope_ids": sorted(
            str(u.id) for u in dsa.geographic_scope.all()
        ),
    }


def _apply_changes(
    dsa: DataSharingAgreement,
    changes: dict[str, Any],
) -> None:
    """Mutates `dsa` in place with the subset of `changes` that
    matches the allowed-fields list. Saves scalar fields first,
    then resets the M2M if `geographic_scope_ids` was given."""
    scalar_updates: list[str] = []
    for field in _SCALAR_SCOPE_FIELDS:
        if field in changes:
            setattr(dsa, field, changes[field])
            scalar_updates.append(field)
    if scalar_updates:
        scalar_updates.append("updated_at")
        dsa.save(update_fields=scalar_updates)

    if _M2M_SCOPE_FIELD in changes:
        ids = changes[_M2M_SCOPE_FIELD] or []
        dsa.geographic_scope.set(ids)


@transaction.atomic
def clone_to_draft(
    source: DataSharingAgreement,
    *,
    actor: str,
    reason: str = "",
) -> DataSharingAgreement:
    """Clone the source DSA into a v(N+1) draft. Same partner,
    same reference, version+1, signatures reset, effective dates
    NULL, signed_at NULL.

    Per ADR-0016 §"Decision 3" both edit-scope (active path) and
    renewal call this helper. The caller is responsible for
    emitting the appropriate `dsa_scope_changed` / `dsa_renewed`
    audit event afterwards — this helper stays single-purpose.
    """
    from apps.partners.models import DataSharingAgreement

    clone = DataSharingAgreement.objects.create(
        reference=source.reference,
        partner=source.partner,
        version=source.version + 1,
        status="draft",
        # effective_from / effective_to deliberately NULL — the
        # caller (operator for edit-scope, partner for renewal)
        # sets them on the new draft before submitting for
        # sign-off.
        monthly_row_budget=source.monthly_row_budget,
        entities_scope=dict(source.entities_scope or {}),
        field_scope=dict(source.field_scope or {}),
        sensitive_data_handling=source.sensitive_data_handling,
        retention_days=source.retention_days,
        classification=source.classification,
        dpia_document_ref=source.dpia_document_ref,
        breach_sla_hours=source.breach_sla_hours,
    )
    clone.programmes.set(source.programmes.all())
    clone.geographic_scope.set(source.geographic_scope.all())

    emit_audit(
        "clone",
        "dsa",
        str(clone.id),
        actor=actor,
        reason=reason or f"clone v{source.version} → v{clone.version}",
        field_changes={
            "source_dsa_id": str(source.id),
            "source_version": source.version,
            "new_version": clone.version,
        },
    )
    return clone


@transaction.atomic
def edit_scope(
    dsa: DataSharingAgreement,
    *,
    actor: str,
    **changes: Any,
) -> DataSharingAgreement:
    """Apply scope changes to a DSA per ADR-0016.

    Draft DSAs are mutated in place. Active DSAs are cloned to a
    v(N+1) draft and the changes are applied to the clone — v(N)
    is left untouched. The returned DSA is the row the caller
    should display to the operator.

    Allowed change keys: `field_scope`, `entities_scope`,
    `monthly_row_budget`, `sensitive_data_handling`,
    `retention_days`, `classification`, `dpia_document_ref`,
    `breach_sla_hours`, `geographic_scope_ids`. Any other key is
    ignored.
    """
    if dsa.status not in _EDITABLE_STATUSES:
        raise ScopeEditError(
            f"DSA {dsa.reference} v{dsa.version} cannot be scope-edited "
            f"in status {dsa.status!r}; allowed statuses are "
            f"{_EDITABLE_STATUSES}.",
        )

    target = (
        dsa
        if dsa.status == "draft"
        else clone_to_draft(
            dsa, actor=actor,
            reason=f"scope-edit clone v{dsa.version} → v{dsa.version + 1}",
        )
    )
    before = _snapshot_scope(target)
    _apply_changes(target, changes)
    target.refresh_from_db()
    after = _snapshot_scope(target)

    emit_audit(
        "dsa_scope_changed",
        "dsa",
        str(target.id),
        actor=actor,
        reason=(
            f"in-place scope edit on draft v{target.version}"
            if dsa.status == "draft"
            else f"scope edit cloned v{dsa.version} → v{target.version}"
        ),
        field_changes={
            "before": before,
            "after": after,
            "version": target.version,
            "editor": actor,
        },
    )
    return target
