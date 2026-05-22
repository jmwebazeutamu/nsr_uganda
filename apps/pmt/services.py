"""PMT services — dual-approved activation + recompute pipeline.

The recompute is wired to two events:
- DIH promotion (called directly from apps.ingestion_hub.services after
  promote_stage_record creates a household).
- UPD commit of a pmt_relevant ChangeRequest (subscribes to
  apps.update_workflow.services.post_change_committed in signals.py).
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.data_management.models import Household
from apps.security.audit import emit as emit_audit

from .constants import PMT_TRIGGER_MANUAL
from .engine import compute_pmt
from .models import ModelStatus, PMTModelVersion, PMTResult


class PMTApprovalError(Exception):
    """The model-version transition is forbidden."""


@transaction.atomic
def activate_model_version(version: PMTModelVersion, *, approver: str) -> PMTModelVersion:
    """AC-PMT-MODEL-VERSION dual approval. Activating retires any prior ACTIVE."""
    if version.status not in (ModelStatus.DRAFT, ModelStatus.PENDING_APPROVAL):
        raise PMTApprovalError(f"cannot activate from {version.status}")
    if not approver or approver == version.author:
        raise PMTApprovalError("approver must differ from author")
    PMTModelVersion.objects.filter(status=ModelStatus.ACTIVE).update(status=ModelStatus.RETIRED)
    version.status = ModelStatus.ACTIVE
    version.approved_by = approver
    version.approved_at = timezone.now()
    version.save()
    emit_audit(
        "activate", "pmt_model_version", version.id, actor=approver,
        reason=f"v{version.version} activated",
    )
    return version


def get_active_model_version() -> PMTModelVersion | None:
    return PMTModelVersion.objects.filter(status=ModelStatus.ACTIVE).first()


# ───────────────────────────────────────────────────────────────
# 3-step sign-off chain (HANDOFF — Admin Console + PMT §4.3)
# ───────────────────────────────────────────────────────────────
#
# Author submission → MGLSD Steward → Director General · UBOS.
# Mirrors apps.partners.services.programme_lifecycle (which itself
# mirrors apps.update_workflow.services). Three steps instead of
# four because PMT calibration is a narrower audience.

_MIN_REJECT_REASON = 20


@transaction.atomic
def submit_for_approval(
    version: PMTModelVersion,
    *,
    actor: str,
    mglsd_steward_email: str,
    ubos_dg_email: str,
    author_email: str = "",
) -> PMTModelVersion:
    """DRAFT → PENDING_APPROVAL.

    Creates three `PMTModelSignOff` rows. The author's step is
    pre-signed (step=1 → SIGNED, author_email = author) because
    submitting IS the author's act of approval — they're not signing
    their own model in any meaningful sense; the next two
    independent signatures are what activates it.

    The two reviewer emails MUST be distinct and MUST NOT match the
    author (AC-PMT-NO-SELF-APPROVE).
    """
    from apps.pmt.models import PMTModelSignOff

    if version.status != ModelStatus.DRAFT:
        raise PMTApprovalError(
            f"PMT v{version.version} is not DRAFT (got {version.status!r}).",
        )

    author = _norm_email(author_email or version.author)
    steward = _norm_email(mglsd_steward_email)
    dg = _norm_email(ubos_dg_email)

    if not steward or not dg:
        raise PMTApprovalError(
            "Both MGLSD Steward and UBOS DG emails are required.",
        )
    if steward == dg:
        raise PMTApprovalError(
            "Reviewer emails must be distinct (AC-PMT-NO-SELF-APPROVE).",
        )
    if author and (author == steward or author == dg):
        raise PMTApprovalError(
            "The author cannot also be a reviewer (AC-PMT-NO-SELF-APPROVE).",
        )

    # Wipe any prior rows for this revision so a resubmit after
    # rejection starts fresh.
    PMTModelSignOff.objects.filter(
        model_version=version, revision=version.version,
    ).delete()

    now = timezone.now()
    PMTModelSignOff.objects.create(
        model_version=version, revision=version.version, step=1,
        expected_role=PMTModelSignOff.ROLE_AUTHOR,
        expected_email=author,
        actual_email=author,
        status=PMTModelSignOff.SIGNED,
        decided_at=now,
        decision_note="submitted",
    )
    PMTModelSignOff.objects.create(
        model_version=version, revision=version.version, step=2,
        expected_role=PMTModelSignOff.ROLE_MGLSD_STEWARD,
        expected_email=steward,
        status=PMTModelSignOff.PENDING,
    )
    PMTModelSignOff.objects.create(
        model_version=version, revision=version.version, step=3,
        expected_role=PMTModelSignOff.ROLE_UBOS_DG,
        expected_email=dg,
        status=PMTModelSignOff.PENDING,
    )

    version.status = ModelStatus.PENDING_APPROVAL
    version.save(update_fields=["status", "updated_at"])

    emit_audit(
        "pmt.model.submit", "pmt_model_version", version.id,
        actor=actor,
        reason=f"submitted for sign-off · v{version.version}",
        field_changes={"steward": steward, "ubos_dg": dg},
    )
    return version


@transaction.atomic
def sign_step(
    version: PMTModelVersion,
    step: int,
    *,
    actor_email: str,
    note: str = "",
) -> PMTModelVersion:
    """Sign the chain at `step` (2 or 3). The 3rd sign flips the
    model to ACTIVE via `activate_model_version` (which also retires
    any prior ACTIVE)."""
    from apps.pmt.models import PMTModelSignOff

    if version.status != ModelStatus.PENDING_APPROVAL:
        raise PMTApprovalError(
            f"PMT v{version.version} is not awaiting sign-off "
            f"(got {version.status!r}).",
        )

    actor = _norm_email(actor_email)
    if not actor:
        raise PMTApprovalError("actor_email is required.")

    if _norm_email(version.author) == actor:
        raise PMTApprovalError(
            "The author cannot sign their own model "
            "(AC-PMT-NO-SELF-APPROVE).",
        )

    try:
        row = PMTModelSignOff.objects.select_for_update().get(
            model_version=version, revision=version.version, step=step,
        )
    except PMTModelSignOff.DoesNotExist as exc:
        raise PMTApprovalError(
            f"No sign-off row for step {step}.",
        ) from exc
    if row.status != PMTModelSignOff.PENDING:
        raise PMTApprovalError(
            f"Step {step} is not pending (status={row.status!r}).",
        )
    if row.expected_email and row.expected_email != actor:
        raise PMTApprovalError(
            f"Step {step} expects {row.expected_email}; got {actor}.",
        )

    prior = set(
        PMTModelSignOff.objects.filter(
            model_version=version,
            revision=version.version,
            status=PMTModelSignOff.SIGNED,
        ).values_list("actual_email", flat=True),
    )
    if actor in prior:
        raise PMTApprovalError(
            "Sign-off steps must be signed by distinct approvers "
            "(AC-PMT-NO-SELF-APPROVE).",
        )

    row.status = PMTModelSignOff.SIGNED
    row.actual_email = actor
    row.decided_at = timezone.now()
    row.decision_note = note
    row.save()

    audit_event = emit_audit(
        "pmt.model.signoff.signed", "pmt_model_version", version.id,
        actor=actor,
        reason=f"step={step} role={row.expected_role}",
        field_changes={"note": note},
    )
    if audit_event is not None:
        row.audit_event_id = str(audit_event.id)
        row.save(update_fields=["audit_event_id", "updated_at"])

    # Last sign — activate via the existing service so the
    # AC-PMT-MODEL-VERSION audit row + prior-active-retirement
    # invariants stay centralised.
    remaining = PMTModelSignOff.objects.filter(
        model_version=version,
        revision=version.version,
        status=PMTModelSignOff.PENDING,
    ).exists()
    if not remaining:
        activate_model_version(version, approver=actor)
        emit_audit(
            "pmt.model.activated", "pmt_model_version", version.id,
            actor=actor,
            reason="all sign-off steps signed",
        )

    return version


@transaction.atomic
def reject_step(
    version: PMTModelVersion,
    step: int,
    *,
    actor_email: str,
    reason: str,
) -> PMTModelVersion:
    """Reject the chain at `step`. Rolls the model back to DRAFT.
    Reason is mandatory (≥ 20 chars) — same threshold as
    update_workflow.reject_change_request + programme_lifecycle."""
    from apps.pmt.models import PMTModelSignOff

    if version.status != ModelStatus.PENDING_APPROVAL:
        raise PMTApprovalError(
            f"PMT v{version.version} is not awaiting sign-off "
            f"(got {version.status!r}).",
        )
    if not reason or len(reason.strip()) < _MIN_REJECT_REASON:
        raise PMTApprovalError(
            f"Rejection reason must be at least "
            f"{_MIN_REJECT_REASON} characters.",
        )

    actor = _norm_email(actor_email)
    if _norm_email(version.author) == actor:
        raise PMTApprovalError(
            "The author cannot reject their own model "
            "(AC-PMT-NO-SELF-APPROVE).",
        )

    try:
        row = PMTModelSignOff.objects.select_for_update().get(
            model_version=version, revision=version.version, step=step,
        )
    except PMTModelSignOff.DoesNotExist as exc:
        raise PMTApprovalError(
            f"No sign-off row for step {step}.",
        ) from exc
    if row.status != PMTModelSignOff.PENDING:
        raise PMTApprovalError(
            f"Step {step} is not pending (status={row.status!r}).",
        )

    now = timezone.now()
    row.status = PMTModelSignOff.REJECTED
    row.actual_email = actor
    row.decided_at = now
    row.decision_note = reason
    row.save()
    PMTModelSignOff.objects.filter(
        model_version=version,
        revision=version.version,
        status=PMTModelSignOff.PENDING,
    ).update(
        status=PMTModelSignOff.SKIPPED,
        decided_at=now,
        decision_note=f"chain rejected at step {step}",
    )

    version.status = ModelStatus.DRAFT
    version.save(update_fields=["status", "updated_at"])
    emit_audit(
        "pmt.model.signoff.rejected", "pmt_model_version", version.id,
        actor=actor,
        reason=reason,
        field_changes={"step": step, "rolled_back_to": "draft"},
    )
    return version


def _norm_email(value: str) -> str:
    if not value:
        return ""
    return value.strip().lower()


@transaction.atomic
def recompute_for_household(
    household: Household, *,
    triggered_by: str = PMT_TRIGGER_MANUAL,
    actor: str = "system",
) -> PMTResult | None:
    """Compute the PMT against the current ACTIVE model and persist a
    PMTResult. Returns None when no ACTIVE model exists (the pipeline
    is harmless in dev before any model is approved).

    US-S22-DE-06: refetch via the prefetch chain so compute_pmt's
    walk over detail entities is N+1-free. The AC-DE-PMT-NO-N-PLUS-1
    test caps query count at 12 for a 10-member household."""
    model = get_active_model_version()
    if model is None:
        return None
    # US-S22-DE-06 prefetch chain. select_related joins one-to-ones
    # onto the Household SELECT; prefetch_related batches the M2M-like
    # repeats. Per-Member reverse-OneToOnes are bulk-loaded INSIDE
    # _household_features (4 queries independent of member count) —
    # cheaper than the equivalent prefetch_related which fires extra
    # per-instance SELECTs when a member has no child row.
    household = (
        Household.objects
        .select_related(
            "dwelling", "utilities", "livelihood",
            "food_security", "food_consumption",
            "head_member",
            "head_member__education", "head_member__employment",
        )
        .prefetch_related(
            "members",
            "assets", "livestock", "crops",
            "shocks", "coping_strategies",
        )
        .get(pk=household.pk)
    )
    score, band, snapshot = compute_pmt(household, model)
    result = PMTResult.objects.create(
        household=household, model_version=model,
        score=score, band=band,
        inputs_snapshot=snapshot, triggered_by=triggered_by,
    )
    Household.objects.filter(pk=household.pk).update(
        current_pmt_score=score, current_vulnerability_band=band,
    )
    emit_audit(
        "recompute", "pmt", household.id, actor=actor,
        reason=f"triggered_by={triggered_by}",
        field_changes={"score": str(score), "band": band, "model_version": model.version},
    )
    return result
