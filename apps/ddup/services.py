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
                a, b = _pair_key(ids[i], ids[j])
                pair, was_created = MatchPair.objects.get_or_create(
                    record_type="member",
                    record_a_id=a, record_b_id=b,
                    defaults=dict(
                        tier=1, match_reason="nin",
                        composite_score=None, per_field_scores=None,
                        model_version=model, status=PairStatus.PENDING,
                    ),
                )
                if was_created:
                    created.append(pair)
                    _emit_audit(
                        action="create", entity_type="match_pair", entity_id=pair.id,
                        actor=actor, reason="tier1-nin-discovery",
                        field_changes={"a": a, "b": b, "tier": 1, "reason": "nin"},
                    )
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
    Household.objects.filter(head_member=loser).update(head_member=surviving)

    # Mark the pair merged.
    pair.status = PairStatus.MERGED
    pair.save(update_fields=["status", "updated_at"])

    # Record the decision.
    decision = MergeDecision.objects.create(
        match_pair=pair, action=MergeAction.MERGE,
        surviving_record_id=surviving.id, losing_record_id=loser.id,
        chosen_field_values=chosen_field_values, reason=note,
        decided_by=actor,
        reverse_window_until=timezone.now() + timezone.timedelta(days=30),
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
