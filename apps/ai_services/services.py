"""AI services: model lifecycle, the kill switch, runs and evaluation.

ADR-0045. Everything here fails closed: if anything needed to run a model is
missing, the answer is "off", not a default.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.security.audit import emit

from .artifacts import (
    ArtifactError,
    LinearScorer,
    RobustZScorer,
    checksum,
    validate_artifact,
)
from .models import (
    AiFeature,
    AiModelVersion,
    AiRun,
    AiSuggestion,
    FeatureCode,
    FeatureState,
    ModelStatus,
)

# Keys a feature's gate_config must carry before it can be advisory. The
# VALUES are an NSR Unit / DPO decision (ADR-0045 D6); only the key names
# are code.
GATE_KEYS = ("min_labelled_decisions", "min_precision", "score_cutoff")


class AiDisabledError(Exception):
    """The feature is off (master switch, no row, no active model, or state)."""


class ModelLifecycleError(Exception):
    """The model-version transition is forbidden."""


class GateError(Exception):
    """The feature cannot be promoted: its gate is unset or not met."""


def _emit(action: str, entity_type: str, entity_id: str, *, actor: str, field_changes: dict,
          reason: str = "") -> None:
    emit(action, entity_type, entity_id, actor=actor, reason=reason, field_changes=field_changes)


# --- model lifecycle -------------------------------------------------------


@transaction.atomic
def register_model(*, name: str, task: str, owner: str, artifact: dict, actor: str,
                   description: str = "", validated_on=None,
                   validation_report_ref: str = "") -> AiModelVersion:
    if not owner:
        raise ModelLifecycleError("a model needs a named owner")
    try:
        validate_artifact(task, artifact)
    except ArtifactError as exc:
        raise ModelLifecycleError(str(exc)) from exc
    latest = (
        AiModelVersion.objects.filter(name=name).order_by("-version")
        .values_list("version", flat=True).first() or 0
    )
    model = AiModelVersion.objects.create(
        name=name, version=latest + 1, task=task, owner=owner, description=description,
        validated_on=validated_on, validation_report_ref=validation_report_ref,
        artifact=artifact, artifact_sha256=checksum(artifact), author=actor,
    )
    _emit("ai.model.registered", "ai_model_version", model.id, actor=actor,
          field_changes={"name": name, "version": model.version, "task": task,
                         "artifact_sha256": model.artifact_sha256})
    return model


@transaction.atomic
def submit_model(model: AiModelVersion, *, actor: str) -> AiModelVersion:
    if model.status != ModelStatus.DRAFT:
        raise ModelLifecycleError(f"cannot submit from {model.status}")
    if model.validated_on is None:
        raise ModelLifecycleError("a model must record a validation date before approval")
    model.status = ModelStatus.PENDING_APPROVAL
    model.save(update_fields=["status", "updated_at"])
    _emit("ai.model.submitted", "ai_model_version", model.id, actor=actor,
          field_changes={"name": model.name, "version": model.version})
    return model


@transaction.atomic
def approve_model(model: AiModelVersion, *, approver: str) -> AiModelVersion:
    """Dual approval: the approver is not the author. Re-validates, because
    the vocabulary the artifact was checked against can change after it was
    drafted, and re-verifies the checksum."""
    if model.status != ModelStatus.PENDING_APPROVAL:
        raise ModelLifecycleError(f"cannot approve from {model.status}")
    if not approver or approver == model.author:
        raise ModelLifecycleError("approver must differ from author")
    if checksum(model.artifact) != model.artifact_sha256:
        raise ModelLifecycleError("artifact does not match its recorded checksum")
    try:
        validate_artifact(model.task, model.artifact)
    except ArtifactError as exc:
        raise ModelLifecycleError(str(exc)) from exc
    AiModelVersion.objects.filter(name=model.name, status=ModelStatus.ACTIVE).update(
        status=ModelStatus.RETIRED,
    )
    model.status = ModelStatus.ACTIVE
    model.approved_by = approver
    model.approved_at = timezone.now()
    model.save()
    _emit("ai.model.approved", "ai_model_version", model.id, actor=approver,
          field_changes={"name": model.name, "version": model.version,
                         "author": model.author, "artifact_sha256": model.artifact_sha256})
    return model


@transaction.atomic
def retire_model(model: AiModelVersion, *, actor: str, reason: str) -> AiModelVersion:
    if not reason:
        raise ModelLifecycleError("retiring a model needs a reason")
    model.status = ModelStatus.RETIRED
    model.save(update_fields=["status", "updated_at"])
    _emit("ai.model.retired", "ai_model_version", model.id, actor=actor, reason=reason,
          field_changes={"name": model.name, "version": model.version})
    return model


# --- the kill switch -------------------------------------------------------


def master_enabled() -> bool:
    return bool(getattr(settings, "AI_SERVICES_ENABLED", False))


def feature_state(code: str) -> str:
    """Effective state. Fails closed on every missing piece."""
    if not master_enabled():
        return FeatureState.OFF
    row = AiFeature.objects.select_related("model_version").filter(code=code).first()
    if row is None or row.model_version is None:
        return FeatureState.OFF
    if row.model_version.status != ModelStatus.ACTIVE:
        return FeatureState.OFF
    return FeatureState(row.state)


@transaction.atomic
def attach_model(code: str, model: AiModelVersion, *, actor: str) -> AiFeature:
    """Point a feature at an active model. A new model has to prove itself
    again, so an ADVISORY feature drops to SHADOW."""
    if model.task != code:
        raise ModelLifecycleError(f"model task {model.task} is not for feature {code}")
    if model.status != ModelStatus.ACTIVE:
        raise ModelLifecycleError("only an active model can be attached")
    row, _ = AiFeature.objects.select_for_update().get_or_create(code=code)
    previous = row.state
    row.model_version = model
    if row.state == FeatureState.ADVISORY:
        row.state = FeatureState.SHADOW
    row.changed_by, row.changed_at = actor, timezone.now()
    row.save()
    _emit("ai.feature.model_attached", "ai_feature", code, actor=actor,
          field_changes={"model": f"{model.name} v{model.version}",
                         "state_before": previous, "state_after": row.state})
    return row


@transaction.atomic
def set_gate_config(code: str, gate_config: dict, *, actor: str) -> AiFeature:
    missing = [k for k in GATE_KEYS if gate_config.get(k) is None]
    if missing:
        raise GateError(f"gate_config is missing {missing}")
    row, _ = AiFeature.objects.select_for_update().get_or_create(code=code)
    row.gate_config = gate_config
    row.changed_by, row.changed_at = actor, timezone.now()
    row.save()
    _emit("ai.feature.gate_set", "ai_feature", code, actor=actor, field_changes=gate_config)
    return row


@transaction.atomic
def set_feature_state(code: str, state: str, *, actor: str, reason: str) -> AiFeature:
    """Move a feature. OFF is always allowed and needs no reason beyond
    being recorded. Anything else needs the master switch, an active attached
    model, and for ADVISORY a met gate."""
    if not reason:
        raise GateError("changing a feature's state needs a reason")
    row, _ = AiFeature.objects.select_for_update().get_or_create(code=code)
    if state != FeatureState.OFF:
        if not master_enabled():
            raise AiDisabledError("AI_SERVICES_ENABLED is off")
        if row.model_version is None or row.model_version.status != ModelStatus.ACTIVE:
            raise GateError("no active model attached")
    if state == FeatureState.ADVISORY:
        ev = evaluate_feature(code)
        if not ev.meets_gate:
            raise GateError("gate not met: " + "; ".join(ev.reasons))
    before = row.state
    row.state = state
    row.changed_by, row.changed_at = actor, timezone.now()
    row.save()
    _emit("ai.feature.state_changed", "ai_feature", code, actor=actor, reason=reason,
          field_changes={"from": before, "to": state})
    return row


# --- running ---------------------------------------------------------------


def load_scorer(code: str):
    """(scorer, model) for a feature that is not off. Re-verifies the
    checksum on every load so an edited artifact cannot run."""
    state = feature_state(code)
    if state == FeatureState.OFF:
        raise AiDisabledError(f"{code} is off")
    model = AiFeature.objects.select_related("model_version").get(code=code).model_version
    if checksum(model.artifact) != model.artifact_sha256:
        raise ModelLifecycleError(f"{model} artifact does not match its checksum")
    scorer = (LinearScorer if model.task == FeatureCode.DDUP_RANK else RobustZScorer)
    return scorer.from_artifact(model.artifact), model


@transaction.atomic
def record_run(code: str, model: AiModelVersion, items: list[dict], *, subject_type: str,
               actor: str, skipped: int = 0, note: str = "", watermark=None) -> AiRun:
    """Persist a batch and emit ONE audit event for it (ADR-0045 D5).

    `items` are {subject_id, score, details}. Re-checks the state so a switch
    thrown mid-run stops the write.
    """
    state = feature_state(code)
    if state == FeatureState.OFF:
        raise AiDisabledError(f"{code} is off")
    run = AiRun.objects.create(
        feature=code, model_version=model, state=state, subject_type=subject_type,
        scored=len(items), skipped=skipped, note=note, actor=actor, watermark=watermark,
    )
    AiSuggestion.objects.bulk_create([
        AiSuggestion(run=run, feature=code, subject_type=subject_type,
                     subject_id=i["subject_id"], score=i["score"], details=i.get("details", {}))
        for i in items
    ])
    _emit("ai.inference.batch", "ai_run", run.id, actor=actor,
          field_changes={"feature": code, "model": f"{model.name} v{model.version}",
                         "state": state, "subject_type": subject_type,
                         "scored": len(items), "skipped": skipped})
    return run


def visible_suggestions(code: str, subject_type: str, subject_ids=None):
    """What a screen may show. Empty unless the feature is ADVISORY."""
    qs = AiSuggestion.objects.filter(feature=code, subject_type=subject_type)
    if feature_state(code) != FeatureState.ADVISORY:
        return qs.none()
    if subject_ids is not None:
        qs = qs.filter(subject_id__in=list(subject_ids))
    return qs


# --- evaluation ------------------------------------------------------------


@dataclass
class Evaluation:
    labelled: int = 0
    above_cutoff: int = 0
    precision: float | None = None
    meets_gate: bool = False
    reasons: list[str] = field(default_factory=list)


def gate_verdict(code: str, labelled: int, above_cutoff: int, positives_above: int) -> Evaluation:
    """Apply the feature's approved gate to measured numbers."""
    row = AiFeature.objects.filter(code=code).first()
    gate = (row.gate_config if row else None) or {}
    ev = Evaluation(labelled=labelled, above_cutoff=above_cutoff)
    if above_cutoff:
        ev.precision = positives_above / above_cutoff
    missing = [k for k in GATE_KEYS if gate.get(k) is None]
    if missing:
        ev.reasons.append(f"gate_config not set ({', '.join(missing)})")
        return ev
    if labelled < gate["min_labelled_decisions"]:
        ev.reasons.append(f"{labelled} labelled decisions, {gate['min_labelled_decisions']} required")
    if ev.precision is None:
        ev.reasons.append("no labelled suggestion at or above the cutoff")
    elif ev.precision < gate["min_precision"]:
        ev.reasons.append(f"precision {ev.precision:.3f} below {gate['min_precision']}")
    ev.meets_gate = not ev.reasons
    return ev


def evaluate_feature(code: str) -> Evaluation:
    if code == FeatureCode.DDUP_RANK:
        from .ddup_ranking import evaluate
        return evaluate()
    # dqa.anomaly: no recorded reviewer disposition of an AI flag exists
    # yet (ADR-0045 D7), so there is nothing to measure against.
    ev = gate_verdict(code, 0, 0, 0)
    ev.meets_gate = False
    ev.reasons.append("no reviewer disposition is recorded for this feature; nothing to evaluate")
    return ev
