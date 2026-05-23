"""ChoiceList lifecycle (dual-approval) service.

Single source of truth for ChoiceList status transitions. Admin REST
endpoints and management commands go through here so the
author-cannot-approve rule (AC-CHOICELIST-NO-SELF-APPROVE) and the
atomic retire-previous semantics can't be bypassed by talking to the
ORM directly.

Mirrors apps/dqa/services.py — same dual-approval shape, same audit
emission discipline, same @transaction.atomic boundaries.
"""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.security.audit import emit as emit_audit

from .models import ChoiceList, ChoiceListStatus, ChoiceOption, GeographicUnit


class ChoiceListApprovalError(Exception):
    """The requested ChoiceList transition is forbidden."""


def _emit(
    cl: ChoiceList,
    *,
    action: str,
    actor: str,
    before: str,
    after: str,
    payload: dict | None = None,
) -> None:
    changes = {"before": before, "after": after}
    if payload:
        changes.update(payload)
    emit_audit(
        action=action,
        entity_type="reference_data.choice_list",
        entity_id=cl.id,
        actor=actor or "system",
        actor_kind="user" if actor else "system",
        reason=f"list_name={cl.list_name} version={cl.version}",
        field_changes=changes,
    )


@transaction.atomic
def submit_for_approval(cl: ChoiceList, *, actor: str = "") -> ChoiceList:
    if cl.status != ChoiceListStatus.DRAFT:
        raise ChoiceListApprovalError(
            f"can only submit a DRAFT ChoiceList (got {cl.status})"
        )
    before = cl.status
    cl.status = ChoiceListStatus.PENDING_APPROVAL
    cl.submitted_at = timezone.now()
    cl.save(update_fields=["status", "submitted_at", "updated_at"])
    _emit(
        cl,
        action="choicelist.submitted",
        actor=actor or cl.author,
        before=before,
        after=cl.status,
    )
    return cl


@transaction.atomic
def sign(
    cl: ChoiceList,
    *,
    approver: str,
    note: str = "",
    actor: str = "",
) -> ChoiceList:
    """Activate a PENDING_APPROVAL ChoiceList and atomically retire the
    previous active row for the same list_name."""
    if cl.status != ChoiceListStatus.PENDING_APPROVAL:
        raise ChoiceListApprovalError(
            f"can only sign a PENDING_APPROVAL ChoiceList (got {cl.status})"
        )
    if not approver:
        raise ChoiceListApprovalError("approver must be supplied")
    if approver == cl.author:
        # AC-CHOICELIST-NO-SELF-APPROVE
        raise ChoiceListApprovalError(
            f"the author of a ChoiceList cannot approve it (author={cl.author})"
        )
    if not note or not note.strip():
        raise ChoiceListApprovalError("approval note is required")

    # Retire the previous active row for the same logical list.
    prior = (
        ChoiceList.objects
        .select_for_update()
        .filter(list_name=cl.list_name, status=ChoiceListStatus.ACTIVE)
        .exclude(pk=cl.pk)
    )
    for old in prior:
        old_before = old.status
        old.status = ChoiceListStatus.RETIRED
        old.save(update_fields=["status", "updated_at"])
        _emit(
            old,
            action="choicelist.retired",
            actor=actor or approver,
            before=old_before,
            after=old.status,
            payload={"superseded_by": cl.id},
        )

    before = cl.status
    cl.status = ChoiceListStatus.ACTIVE
    cl.approved_by = approver
    cl.approved_at = timezone.now()
    cl.approval_note = note.strip()
    cl.save(
        update_fields=[
            "status", "approved_by", "approved_at",
            "approval_note", "updated_at",
        ]
    )
    _emit(
        cl,
        action="choicelist.signed",
        actor=actor or approver,
        before=before,
        after=cl.status,
        payload={"approver": approver, "note": cl.approval_note},
    )
    return cl


@transaction.atomic
def reject(
    cl: ChoiceList,
    *,
    approver: str,
    reason: str = "",
    actor: str = "",
) -> ChoiceList:
    if cl.status != ChoiceListStatus.PENDING_APPROVAL:
        raise ChoiceListApprovalError(
            f"can only reject a PENDING_APPROVAL ChoiceList (got {cl.status})"
        )
    if approver == cl.author:
        raise ChoiceListApprovalError(
            "the author of a ChoiceList cannot reject it"
        )
    if not reason or not reason.strip():
        raise ChoiceListApprovalError("rejection reason is required")
    before = cl.status
    cl.status = ChoiceListStatus.DRAFT
    cl.rejection_reason = reason.strip()
    cl.save(update_fields=["status", "rejection_reason", "updated_at"])
    _emit(
        cl,
        action="choicelist.rejected",
        actor=actor or approver,
        before=before,
        after=cl.status,
        payload={"approver": approver, "reason": cl.rejection_reason},
    )
    return cl


@transaction.atomic
def deprecate_option(
    option: ChoiceOption,
    *,
    actor: str = "",
    reason: str = "",
) -> ChoiceOption:
    """Soft-delete a ChoiceOption — status flips to DEPRECATED, never
    hard-deleted (past intake answers must remain readable)."""
    before = option.status
    if before == ChoiceOption.Status.DEPRECATED:
        return option
    option.status = ChoiceOption.Status.DEPRECATED
    option.save(update_fields=["status", "updated_at"])
    emit_audit(
        action="choiceoption.deprecated",
        entity_type="reference_data.choice_option",
        entity_id=option.id,
        actor=actor or "system",
        actor_kind="user" if actor else "system",
        reason=reason or f"list={option.choice_list.list_name} code={option.code}",
        field_changes={"before": before, "after": option.status},
    )
    return option


@transaction.atomic
def clone_to_draft(src: ChoiceList, *, author: str) -> ChoiceList:
    """Create a new DRAFT version cloning src's options. The new
    version is max(version)+1 for the same list_name."""
    if not author:
        raise ChoiceListApprovalError("author is required to clone a ChoiceList")
    next_version = (
        (ChoiceList.objects
         .filter(list_name=src.list_name)
         .order_by("-version")
         .values_list("version", flat=True)
         .first() or 0)
        + 1
    )
    draft = ChoiceList.objects.create(
        list_name=src.list_name,
        version=next_version,
        description=src.description,
        status=ChoiceListStatus.DRAFT,
        author=author,
        is_pii_classified=getattr(src, "is_pii_classified", False),
    )
    bulk = [
        ChoiceOption(
            choice_list=draft,
            code=o.code,
            label=o.label,
            language=o.language,
            parent_code=o.parent_code,
            sort_order=o.sort_order,
            status=ChoiceOption.Status.ACTIVE,
        )
        for o in src.options.filter(status=ChoiceOption.Status.ACTIVE)
    ]
    ChoiceOption.objects.bulk_create(bulk)
    emit_audit(
        action="choicelist.cloned",
        entity_type="reference_data.choice_list",
        entity_id=draft.id,
        actor=author,
        reason=f"list_name={src.list_name} from_v{src.version} to_v{next_version}",
        field_changes={
            "source_id": src.id,
            "source_version": src.version,
            "new_version": next_version,
            "options_copied": len(bulk),
        },
    )
    return draft


# ───────────────────────────────────────────────────────────────
# GeographicUnit — versioned write (replace-supersede)
# ───────────────────────────────────────────────────────────────

class GeographicUnitReplaceError(Exception):
    """The requested GeographicUnit replacement is forbidden."""


@transaction.atomic
def replace_geographic_unit(
    current: GeographicUnit,
    *,
    actor: str,
    name: str | None = None,
    parent: GeographicUnit | None = ...,
    effective_from=None,
) -> GeographicUnit:
    """Atomically supersede `current` with a new active row.

    Rules (per HANDOFF Cat 1.2 versioned-write semantics):
    1. `current` flips to status=superseded with effective_to=yesterday.
    2. New row inserted with effective_from=today (or `effective_from`),
       status=active, same level + code; name and parent may change.
    3. AuditEvent `geo_unit.replaced` emitted with before/after diff.

    `parent=...` (Ellipsis sentinel) means "leave parent unchanged".
    Passing `parent=None` is allowed (national-level root).
    """
    if current.status != GeographicUnit.Status.ACTIVE:
        raise GeographicUnitReplaceError(
            f"can only replace an ACTIVE GeographicUnit (got {current.status})"
        )
    if not actor:
        raise GeographicUnitReplaceError("actor is required")

    today = timezone.localdate()
    new_eff_from = effective_from or today
    if new_eff_from <= current.effective_from:
        raise GeographicUnitReplaceError(
            "new effective_from must be later than the current row's"
        )

    new_name = name if name is not None else current.name
    if parent is ...:
        new_parent = current.parent
    else:
        new_parent = parent

    if new_name == current.name and (new_parent.id if new_parent else None) == current.parent_id:
        raise GeographicUnitReplaceError(
            "nothing changed — provide a new name or parent"
        )

    # Supersede the current row.
    current.status = GeographicUnit.Status.SUPERSEDED
    current.effective_to = new_eff_from - timedelta(days=1)
    current.save(update_fields=["status", "effective_to"])

    # Insert the new active row.
    new_row = GeographicUnit.objects.create(
        level=current.level,
        code=current.code,
        name=new_name,
        parent=new_parent,
        effective_from=new_eff_from,
        status=GeographicUnit.Status.ACTIVE,
    )

    emit_audit(
        action="geo_unit.replaced",
        entity_type="reference_data.geographic_unit",
        entity_id=new_row.id,
        actor=actor,
        reason=f"level={current.level} code={current.code}",
        field_changes={
            "before": {
                "id": current.id,
                "name": current.name,
                "parent_id": current.parent_id,
                "effective_from": current.effective_from.isoformat(),
            },
            "after": {
                "id": new_row.id,
                "name": new_row.name,
                "parent_id": new_row.parent_id,
                "effective_from": new_row.effective_from.isoformat(),
            },
            "superseded_id": current.id,
        },
    )
    return new_row


def recompute_children_count(unit_id: int) -> int:
    """Recompute children_count_cached for one unit. Returns the new
    value. Called from the post-save signal whenever a unit's parent
    FK is set, changed, or its status flips to a non-active state."""
    count = GeographicUnit.objects.filter(parent_id=unit_id).count()
    GeographicUnit.objects.filter(id=unit_id).update(
        children_count_cached=count,
    )
    return count
