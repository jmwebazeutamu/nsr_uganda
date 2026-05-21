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
