"""DAT-DDUP services: tier 1 NIN matcher and the merge-commit transaction.

Cross-app calls are allowed per ADR-0001 ("internal Python APIs"); this
module imports Member from apps.data_management directly. PMT recompute and
audit emission are placeholders that will wire up when those modules land.

References:
- SAD §4.3.1 (matching strategy), §4.3.2 (merge operation), §4.3.6 (ACs)
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.data_management.models import Member
from apps.security.audit import emit as emit_audit

from .models import (
    DdupModelVersion,
    MatchPair,
    MergeAction,
    MergeDecision,
    ModelStatus,
    PairStatus,
)
from .phone import to_e164

# ---------------------------------------------------------------------------
# Model version lifecycle


class DdupApprovalError(Exception):
    """The model-version transition is forbidden."""


@transaction.atomic
def activate_model_version(version: DdupModelVersion, *, approver: str) -> DdupModelVersion:
    """Per AC-DDUP-MODEL-VERSION: dual approval required, author != approver."""
    if version.status not in (ModelStatus.DRAFT, ModelStatus.PENDING_APPROVAL):
        raise DdupApprovalError(f"cannot activate from {version.status}")
    if not approver or approver == version.author:
        raise DdupApprovalError("approver must differ from author")
    DdupModelVersion.objects.filter(status=ModelStatus.ACTIVE).update(status=ModelStatus.RETIRED)
    version.status = ModelStatus.ACTIVE
    version.approved_by = approver
    version.approved_at = timezone.now()
    version.save()
    return version


def get_active_model_version() -> DdupModelVersion:
    return DdupModelVersion.objects.get(status=ModelStatus.ACTIVE)


# ---------------------------------------------------------------------------
# Tier 1 NIN matcher


def _pair_key(a: str, b: str) -> tuple[str, str]:
    """Order by ULID so (a,b) and (b,a) collapse to one row."""
    return (a, b) if a < b else (b, a)


def _emit_audit(action: str, entity_type: str, entity_id: str, *, actor: str, reason: str = "",
                field_changes: dict | None = None) -> None:
    """Thin wrapper around the shared emitter — kept for call-site clarity."""
    emit_audit(action, entity_type, entity_id, actor=actor, actor_kind="user",
               reason=reason, field_changes=field_changes)


def _record_pair(
    *, record_a_id: str, record_b_id: str, tier: int, match_reason: str,
    model: DdupModelVersion, actor: str,
) -> MatchPair | None:
    """Insert a PENDING pair if (record_type=member, a, b) doesn't already
    exist. Returns the new MatchPair, or None when the pair was already
    present (idempotent re-discovery)."""
    a, b = _pair_key(record_a_id, record_b_id)
    pair, was_created = MatchPair.objects.get_or_create(
        record_type="member",
        record_a_id=a, record_b_id=b,
        defaults=dict(
            tier=tier, match_reason=match_reason,
            composite_score=None, per_field_scores=None,
            model_version=model, status=PairStatus.PENDING,
        ),
    )
    if was_created:
        _emit_audit(
            action="create", entity_type="match_pair", entity_id=pair.id,
            actor=actor, reason=f"tier{tier}-{match_reason}-discovery",
            field_changes={"a": a, "b": b, "tier": tier, "reason": match_reason},
        )
        return pair
    return None


@transaction.atomic
def discover_nin_pairs(*, actor: str = "system") -> list[MatchPair]:
    """Find every set of Member rows sharing nin_hash and create pending pairs.

    Per AC-DDUP-NIN: any two members sharing the same NIN appear in the
    merge queue regardless of other differences. Blocking until resolved.

    Returns newly-created MatchPair rows (idempotent re-runs return []).
    """
    model = get_active_model_version()
    nin_groups: dict[bytes, list[str]] = {}
    qs = (
        Member.objects
        .filter(is_deleted=False, nin_hash__isnull=False)
        .values_list("id", "nin_hash")
    )
    for member_id, nin_hash in qs:
        if not nin_hash:
            continue
        key = bytes(nin_hash)
        nin_groups.setdefault(key, []).append(member_id)

    created: list[MatchPair] = []
    for ids in nin_groups.values():
        if len(ids) < 2:
            continue
        ids = sorted(ids)
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                pair = _record_pair(
                    record_a_id=ids[i], record_b_id=ids[j],
                    tier=1, match_reason="nin", model=model, actor=actor,
                )
                if pair:
                    created.append(pair)
    return created


@transaction.atomic
def discover_phone_pairs(*, actor: str = "system") -> list[MatchPair]:
    """Tier 2: exact match on Member.telephone_1 normalised to E.164.

    Per SAD §4.3.1 tier 2 and §11.1 MVP scope. Tier 1 (NIN) takes
    precedence — pairs already discovered there are preserved by the
    (record_type, a, b) uniqueness constraint and not re-queued.

    Returns newly-created MatchPair rows.
    """
    model = get_active_model_version()
    by_phone: dict[str, list[str]] = {}
    qs = (
        Member.objects
        .filter(is_deleted=False)
        .exclude(telephone_1="")
        .values_list("id", "telephone_1")
    )
    for member_id, phone in qs:
        e164 = to_e164(phone)
        if not e164:
            continue
        by_phone.setdefault(e164, []).append(member_id)

    created: list[MatchPair] = []
    for ids in by_phone.values():
        if len(ids) < 2:
            continue
        ids = sorted(ids)
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                pair = _record_pair(
                    record_a_id=ids[i], record_b_id=ids[j],
                    tier=2, match_reason="phone", model=model, actor=actor,
                )
                if pair:
                    created.append(pair)
    return created


# ---------------------------------------------------------------------------
# Merge-commit transaction


class MergeError(Exception):
    """The merge cannot be committed under current state."""


@transaction.atomic
def merge_member_pair(
    pair: MatchPair,
    *,
    surviving_id: str,
    chosen_field_values: dict,
    actor: str,
    note: str = "",
) -> MergeDecision:
    """AC-DDUP-MERGE-COMMIT: atomic merge.

    - Surviving Member keeps its id; chosen field values applied.
    - Loser Member is_deleted=True, deleted_at=now, merged_into=surviving.
    - Child rows are re-pointed (Sprint 0 surface: any Household.head_member
      pointing at the loser flips to the survivor).
    - PMT recompute is a TODO once the PMT module lands.
    - Audit chain entry written.
    """
    if pair.record_type != "member":
        raise MergeError("merge_member_pair only handles member pairs")
    if pair.status != PairStatus.PENDING:
        raise MergeError(f"pair is {pair.status}; only PENDING pairs can be merged")
    if surviving_id not in (pair.record_a_id, pair.record_b_id):
        raise MergeError("surviving_id must be one of the pair members")

    surviving_id_, losing_id = surviving_id, (
        pair.record_b_id if surviving_id == pair.record_a_id else pair.record_a_id
    )
    surviving = Member.objects.select_for_update().get(id=surviving_id_)
    loser = Member.objects.select_for_update().get(id=losing_id)
    if loser.is_deleted:
        raise MergeError("loser already soft-deleted")

    # Apply chosen field values on survivor.
    settable = {
        "surname", "first_name", "other_name", "relationship_to_head",
        "marital_status", "nationality", "residency_status",
        "birth_certificate_status", "telephone_1", "telephone_2",
        "nin_last4",
    }
    applied: dict[str, dict] = {}
    for field, value in chosen_field_values.items():
        if field not in settable:
            continue
        applied[field] = {"old": getattr(surviving, field), "new": value}
        setattr(surviving, field, value)
    surviving.save()

    # Soft-delete the loser.
    loser.is_deleted = True
    loser.deleted_at = timezone.now()
    loser.merged_into = surviving
    loser.save(update_fields=["is_deleted", "deleted_at", "merged_into", "updated_at"])

    # Re-point any Household.head_member references to the loser.
    from apps.data_management.models import Household
    repointed_household_ids = list(
        Household.objects.filter(head_member=loser).values_list("id", flat=True),
    )
    Household.objects.filter(head_member=loser).update(head_member=surviving)

    # Mark the pair merged.
    pair.status = PairStatus.MERGED
    pair.save(update_fields=["status", "updated_at"])

    # Record the decision with a pre-merge snapshot — the snapshot is
    # the source of truth for reverse_merge_decision() within the 30-day
    # un-merge window (SAD §4.3.2).
    decision = MergeDecision.objects.create(
        match_pair=pair, action=MergeAction.MERGE,
        surviving_record_id=surviving.id, losing_record_id=loser.id,
        chosen_field_values=chosen_field_values, reason=note,
        decided_by=actor,
        reverse_window_until=timezone.now() + timezone.timedelta(days=30),
        pre_merge_snapshot={
            "surviving_overrides": {f: c["old"] for f, c in applied.items()},
            "households_repointed_to_survivor": repointed_household_ids,
        },
    )

    # AC-DDUP-AUDIT: emit audit chain entry.
    _emit_audit(
        action="merge", entity_type="member", entity_id=surviving.id,
        actor=actor, reason=note,
        field_changes={
            "surviving": surviving.id, "loser": loser.id,
            "pair_id": pair.id, "applied_field_values": applied,
            "model_version_id": pair.model_version_id,
        },
    )

    # TODO: PMT recompute. Triggered when apps.pmt lands.
    # TODO: notify enrolled programmes via apps.referral.

    return decision


@transaction.atomic
def reverse_merge_decision(
    decision: MergeDecision, *, actor: str, reason: str,
) -> MergeDecision:
    """SAD §4.3.2 — un-merge within the 30-day window.

    Restores the loser Member (clears is_deleted / deleted_at /
    merged_into), undoes the surviving Member's overrides using the
    pre_merge_snapshot, restores Household.head_member references
    that were re-pointed at merge time, flips MatchPair back to
    PENDING, and records reversed_at/reversed_by/reversed_reason on
    the decision. Emits AuditEvent action=unmerge.

    Guards:
    - decision.action must be MERGE (other actions have nothing to
      reverse).
    - timezone.now() must be <= reverse_window_until.
    - decision must not already be reversed.
    - reason must be non-empty (DPPA accountability — every un-merge
      needs a defensible trail).
    """
    if decision.action != MergeAction.MERGE:
        raise MergeError(
            f"only MERGE decisions can be reversed (got {decision.action})",
        )
    if decision.reversed_at is not None:
        raise MergeError(
            f"decision {decision.id} already reversed at {decision.reversed_at}",
        )
    if not reason:
        raise MergeError("reverse requires a non-empty reason")
    now = timezone.now()
    if decision.reverse_window_until and now > decision.reverse_window_until:
        raise MergeError(
            f"reverse window closed at {decision.reverse_window_until.isoformat()}",
        )

    pair = decision.match_pair
    surviving = Member.objects.select_for_update().get(id=decision.surviving_record_id)
    loser = Member.objects.select_for_update().get(id=decision.losing_record_id)

    snapshot = decision.pre_merge_snapshot or {}
    overrides = snapshot.get("surviving_overrides", {})
    repointed_household_ids = snapshot.get(
        "households_repointed_to_survivor", [],
    )

    # Restore the surviving member's fields from the pre-merge snapshot.
    for field, old_value in overrides.items():
        setattr(surviving, field, old_value)
    if overrides:
        surviving.save(update_fields=list(overrides.keys()) + ["updated_at"])

    # Un-soft-delete the loser.
    loser.is_deleted = False
    loser.deleted_at = None
    loser.merged_into = None
    loser.save(update_fields=[
        "is_deleted", "deleted_at", "merged_into", "updated_at",
    ])

    # Restore household head_member references that we re-pointed.
    if repointed_household_ids:
        from apps.data_management.models import Household
        Household.objects.filter(id__in=repointed_household_ids).update(
            head_member=loser,
        )

    # Flip the pair back to PENDING so the operator can re-decide.
    pair.status = PairStatus.PENDING
    pair.save(update_fields=["status", "updated_at"])

    # Record the reversal on the decision row (immutable except for
    # these three fields, per the model docstring).
    decision.reversed_at = now
    decision.reversed_by = actor
    decision.reversed_reason = reason
    decision.save(update_fields=[
        "reversed_at", "reversed_by", "reversed_reason",
    ])

    _emit_audit(
        action="unmerge", entity_type="match_pair", entity_id=pair.id,
        actor=actor, reason=reason,
        field_changes={
            "surviving": surviving.id, "restored_loser": loser.id,
            "decision_id": decision.id,
            "households_restored": repointed_household_ids,
        },
    )
    return decision


@transaction.atomic
def reject_pair(pair: MatchPair, *, actor: str, reason: str) -> MergeDecision:
    """AC-DDUP-REJECT-LEARN: rejecting a pair records the reason and prevents
    re-queueing unless one of the pair's fields changes after the rejection
    date. The 'don't re-queue' part is enforced by discover_nin_pairs only
    pairing PENDING-or-absent pairs (existing REJECTED rows are preserved
    and not re-evaluated)."""
    if pair.status != PairStatus.PENDING:
        raise MergeError(f"pair is {pair.status}; only PENDING pairs can be rejected")
    if not reason:
        raise MergeError("reject requires a non-empty reason")

    pair.status = PairStatus.REJECTED
    pair.save(update_fields=["status", "updated_at"])
    decision = MergeDecision.objects.create(
        match_pair=pair, action=MergeAction.REJECT,
        reason=reason, decided_by=actor,
    )
    _emit_audit(
        action="reject", entity_type="match_pair", entity_id=pair.id,
        actor=actor, reason=reason,
    )
    return decision
