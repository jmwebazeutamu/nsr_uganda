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


# Policy ceiling for the auto-reverse rate. When a model version
# crosses this, the admin merge_summary surfaces a "TUNE UP" hint and
# the threshold-tuning actions become operationally relevant. The
# 5% value comes from the DPIA Sprint 8 follow-up — every reverse is
# a personal-data event for two households (audit cost), so we want
# the false-merge rate well under the SAD §11.5.4 NFR.
AUTO_REVERSE_RATE_CEILING = 0.05

# Calibration step size for the threshold-tuning admin actions.
# Small enough that operators can converge gradually; bigger steps
# are still possible by editing the JSON directly.
THRESHOLD_NUDGE_STEP = 0.05

# Bounds — anything outside this range is operationally meaningless
# (1.0 means "auto-merge nothing"; below 0.5 means "auto-merge
# almost-anything"). The admin actions clamp into this corridor.
THRESHOLD_FLOOR = 0.50
THRESHOLD_CEILING = 1.00

# Policy-default auto_merge_threshold — what the Sprint 8 ADR-ish
# calibration landed on. Used as the "Set safe default" action's
# target. Stored as a string here so JSON round-trip stays exact.
SAFE_DEFAULT_THRESHOLD = 0.95


@transaction.atomic
def clone_with_threshold_delta(
    source: DdupModelVersion, *, delta: float, actor: str, reason: str,
) -> DdupModelVersion:
    """Calibration action (US-S11-005): copy `source` into a new
    DRAFT DdupModelVersion with `config['tier3']['auto_merge_
    threshold']` adjusted by `delta`. The new version still requires
    dual approval (via `activate_model_version`) before it goes live
    — this function only creates the draft.

    Why a new version instead of mutating the existing one?
    Per AC-DDUP-MODEL-VERSION every config change is auditable and
    reversible: the DPO + DDUP lead must approve before any new
    threshold reaches Member rows. Mutating in place would silently
    re-define what "auto-merge" means for already-decided merges
    against this version. New version = clean audit boundary.
    """
    current_config = source.config or {}
    tier3 = dict(current_config.get("tier3") or {})
    current_threshold = float(tier3.get("auto_merge_threshold", SAFE_DEFAULT_THRESHOLD))
    new_threshold = max(THRESHOLD_FLOOR, min(THRESHOLD_CEILING, current_threshold + delta))
    if new_threshold == current_threshold:
        raise DdupApprovalError(
            f"threshold already at clamp boundary ({current_threshold:.2f}); "
            f"cannot move by {delta:+.2f}",
        )

    tier3["auto_merge_threshold"] = new_threshold
    new_config = {**current_config, "tier3": tier3}

    next_version = (
        DdupModelVersion.objects.order_by("-version").values_list("version", flat=True).first() or 0
    ) + 1
    draft = DdupModelVersion.objects.create(
        version=next_version,
        description=(
            f"Calibration {delta:+.2f} of v{source.version}. "
            f"auto_merge_threshold: {current_threshold:.2f} -> {new_threshold:.2f}. "
            f"Reason: {reason}"
        ),
        config=new_config,
        status=ModelStatus.DRAFT,
        author=actor,
    )
    _emit_audit(
        "calibrate", "ddup_model_version", draft.id, actor=actor,
        reason=reason,
        field_changes={
            "from_version": source.version,
            "to_version": next_version,
            "auto_merge_threshold_before": current_threshold,
            "auto_merge_threshold_after": new_threshold,
            "delta": delta,
        },
    )
    return draft


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


def discover_probabilistic_pairs(*, actor: str = "system") -> list[MatchPair]:
    """Tier 3: weighted-similarity matching within village blocks.

    Reads weights + threshold from active DdupModelVersion.config[
    "tier3"]. Default config (used when the model version doesn't
    provide its own) weights surname + first_name highest because
    they're the strongest individual signals; DOB year + village
    are cheaper checks that prevent obviously-different rows from
    crossing the threshold.

    Per SAD §4.3.1 tier 3. Blocking is by Household.village_id so
    the comparison is O(N²) within each village, not across the
    country (Uganda has ~10,800 villages; biggest realistic block
    is < 1000 members).

    Tier 1 / Tier 2 pairs are preserved by the (record_type, a, b)
    uniqueness constraint — same logic as tier 2 over tier 1.
    """
    from collections import defaultdict
    from decimal import Decimal

    from .similarity import (
        composite_score,
        exact,
        jaro_winkler,
        year_proximity,
    )

    model = get_active_model_version()
    cfg = (model.config or {}).get("tier3") or {}
    weights = cfg.get("weights") or {
        "surname": 0.30,
        "first_name": 0.30,
        "date_of_birth": 0.15,
        "sex": 0.10,
        "village": 0.15,
    }
    threshold = cfg.get("threshold", 0.85)

    # Block by village to keep the comparison tractable.
    by_village: dict[str, list] = defaultdict(list)
    qs = (
        Member.objects
        .filter(is_deleted=False)
        .select_related("household")
        .only(
            "id", "surname", "first_name", "date_of_birth", "sex",
            "household__village_id",
        )
    )
    for m in qs:
        by_village[m.household.village_id].append(m)

    created: list[MatchPair] = []
    for members in by_village.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda x: x.id)
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = members[i], members[j]
                scores = {
                    "surname": jaro_winkler(a.surname or "", b.surname or ""),
                    "first_name": jaro_winkler(
                        a.first_name or "", b.first_name or "",
                    ),
                    "date_of_birth": year_proximity(
                        a.date_of_birth, b.date_of_birth,
                    ),
                    "sex": exact(a.sex, b.sex),
                    "village": exact(
                        a.household.village_id, b.household.village_id,
                    ),
                }
                composite = composite_score(
                    [(weights.get(k, 0.0), s) for k, s in scores.items()],
                )
                if composite < threshold:
                    continue
                pair = _record_pair(
                    record_a_id=a.id, record_b_id=b.id,
                    tier=3, match_reason="probabilistic",
                    model=model, actor=actor,
                )
                if pair is not None:
                    # Persist the breakdown so reviewers see why the
                    # pair fired.
                    pair.composite_score = Decimal(f"{composite:.3f}")
                    pair.per_field_scores = {
                        k: round(s, 3) for k, s in scores.items()
                    }
                    pair.save(update_fields=[
                        "composite_score", "per_field_scores", "updated_at",
                    ])
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

    # US-CONSENT-15 — reconcile consent records between loser and survivor
    # (union of grants; any withdrawal wins; GRANTED-vs-REFUSED conflicts raise
    # and roll back the whole merge). Inert when CONSENT_MODULE_ENABLED is off.
    from apps.consent import services as consent_services
    consent_services.reconcile_consent_on_merge(
        surviving=surviving, loser=loser, actor=actor)

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
    - decision.action must be MERGE or DISCARD_LOSER. Both wrote a
      pre_merge_snapshot + reverse_window_until; the on-disk effect
      of a discard is a strict subset of a merge (loser soft-deleted,
      household head-pointers repointed, no field overrides), so the
      same code path reverses both.
    - timezone.now() must be <= reverse_window_until.
    - decision must not already be reversed.
    - reason must be non-empty (DPPA accountability — every un-merge
      needs a defensible trail).
    """
    if decision.action not in (MergeAction.MERGE, MergeAction.DISCARD_LOSER):
        raise MergeError(
            f"only MERGE / DISCARD_LOSER decisions can be reversed "
            f"(got {decision.action})",
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


def auto_merge_high_confidence_pairs(
    *, actor: str = "ddup-auto-merge",
) -> dict[str, int]:
    """Sweep PENDING tier-3 pairs whose composite_score >= the active
    DdupModelVersion's auto_merge_threshold (default 0.95) and merge
    them with no manual intervention.

    Per-pair surviving_id selection: the older Member wins
    (lexicographic ULID order ascending — ULIDs are time-sortable, so
    this picks the earlier-registered record). chosen_field_values is
    empty: the survivor's existing field values are preserved, only
    the loser is soft-deleted and the pair is closed.

    Each merge runs through the existing merge_member_pair() service
    so audit chain, pre_merge_snapshot, and the 30-day reverse window
    (S5-003) all apply identically to manual merges. Additionally
    emits one auto_merge audit event per pair so the QA team can
    distinguish automatic from manual merges in the audit feed.

    Returns counts dict {processed, merged, skipped}. Idempotent —
    re-runs see no PENDING tier-3 rows above threshold (they were
    merged on the previous run) so the second run is a no-op.
    """
    model = get_active_model_version()
    cfg = (model.config or {}).get("tier3") or {}
    auto_threshold = cfg.get("auto_merge_threshold", 0.95)

    qs = MatchPair.objects.filter(
        status=PairStatus.PENDING,
        record_type="member",
        tier=3,
        composite_score__gte=auto_threshold,
    ).order_by("created_at")

    processed = 0
    merged = 0
    skipped = 0
    for pair in qs:
        processed += 1
        # ULIDs are time-sortable; pick the earlier record as survivor.
        survivor_id = min(pair.record_a_id, pair.record_b_id)
        try:
            merge_member_pair(
                pair, surviving_id=survivor_id, chosen_field_values={},
                actor=actor,
                note=(
                    f"auto-merge tier-3 composite={pair.composite_score} "
                    f">= threshold {auto_threshold}"
                ),
            )
            _emit_audit(
                action="auto_merge", entity_type="match_pair",
                entity_id=pair.id, actor=actor,
                reason=f"composite={pair.composite_score}",
                field_changes={
                    "threshold": float(auto_threshold),
                    "surviving": survivor_id,
                },
            )
            merged += 1
        except MergeError:
            # Race with manual reviewer or already-merged pair —
            # skip without aborting the batch.
            skipped += 1
    return {"processed": processed, "merged": merged, "skipped": skipped}


@transaction.atomic
def discard_duplicate(
    pair: MatchPair,
    *,
    surviving_id: str,
    actor: str,
    reason: str,
) -> MergeDecision:
    """Both records ARE the same person, but the loser is bad data
    (test entry, accidental re-submission, corrupted re-capture).

    On-disk effect mirrors merge_member_pair with empty
    chosen_field_values: survivor's fields stay untouched, loser is
    soft-deleted with merged_into=survivor, Household.head_member
    references on the loser flip to the survivor. The pair lands in
    MERGED state — still a duplicate-resolved outcome. The 30-day
    reverse_merge_decision window applies (action=DISCARD_LOSER is
    distinguishable in audit, but reversal does the same thing).

    Reason is mandatory (>= 6 chars) so the audit chain always
    carries a why — matches reject_pair's discipline.
    """
    if pair.record_type != "member":
        raise MergeError("discard_duplicate only handles member pairs")
    if pair.status != PairStatus.PENDING:
        raise MergeError(
            f"pair is {pair.status}; only PENDING pairs can be discarded",
        )
    if surviving_id not in (pair.record_a_id, pair.record_b_id):
        raise MergeError("surviving_id must be one of the pair members")
    if len(reason.strip()) < 6:
        raise MergeError("discard requires a reason of at least 6 characters")

    losing_id = (
        pair.record_b_id if surviving_id == pair.record_a_id else pair.record_a_id
    )
    surviving = Member.objects.select_for_update().get(id=surviving_id)
    loser = Member.objects.select_for_update().get(id=losing_id)
    if loser.is_deleted:
        raise MergeError("loser already soft-deleted")

    # Soft-delete the loser. No field copying — that's the whole
    # point of this code path versus merge_member_pair.
    loser.is_deleted = True
    loser.deleted_at = timezone.now()
    loser.merged_into = surviving
    loser.save(update_fields=[
        "is_deleted", "deleted_at", "merged_into", "updated_at",
    ])

    # Re-point any Household.head_member references on the loser.
    from apps.data_management.models import Household
    repointed_household_ids = list(
        Household.objects.filter(head_member=loser).values_list("id", flat=True),
    )
    Household.objects.filter(head_member=loser).update(head_member=surviving)

    pair.status = PairStatus.MERGED
    pair.save(update_fields=["status", "updated_at"])

    decision = MergeDecision.objects.create(
        match_pair=pair, action=MergeAction.DISCARD_LOSER,
        surviving_record_id=surviving.id, losing_record_id=loser.id,
        chosen_field_values={}, reason=reason,
        decided_by=actor,
        reverse_window_until=timezone.now() + timezone.timedelta(days=30),
        pre_merge_snapshot={
            # No surviving_overrides — survivor was never written.
            "surviving_overrides": {},
            "households_repointed_to_survivor": repointed_household_ids,
        },
    )

    _emit_audit(
        action="discard_loser", entity_type="match_pair", entity_id=pair.id,
        actor=actor, reason=reason,
        field_changes={
            "surviving": surviving.id, "discarded": loser.id,
            "households_repointed": repointed_household_ids,
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
