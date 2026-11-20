"""Admin Console · AI oversight (ADR-0045).

Read-only. Shows, for each AI feature, where it stands (off / shadow /
advisory), which model drives it, how it measures against reviewer
decisions, and what it last scored.

This is the OVERSIGHT view for the people who decide whether a feature
leaves shadow, so it shows suggestions in every state and says plainly
whether reviewers can see them (`shown_to_reviewers`). It is not the
reviewer-facing surface: reviewers get a suggestion only when the feature is
advisory, through `apps.ai_services.services.visible_suggestions`.

No write endpoint. Who may change a feature's state is open item AI-O-06;
until it is answered the switch is `manage.py ai_feature`.
"""

from __future__ import annotations

from rest_framework import status as drf_status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.admin_console.permissions import IsAdminConsoleUser
from apps.ai_services import services as ai
from apps.ai_services.models import (
    AiFeature,
    AiRun,
    AiSuggestion,
    FeatureCode,
    FeatureState,
)
from apps.ddup.models import MatchPair, MergeAction, MergeDecision

#: feature state -> `ui_tone` code. The one place AI code translates a state
#: to a tone (SSOT register, "Status tone"); the console renders the code.
STATE_TONE = {
    FeatureState.OFF: "neutral",
    FeatureState.SHADOW: "reference",
    FeatureState.ADVISORY: "system",
}

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def _model(row):
    m = row.model_version if row else None
    if m is None:
        return None
    return {
        "id": m.id, "name": m.name, "version": m.version, "status": m.status,
        "owner": m.owner, "validated_on": m.validated_on,
        "approved_by": m.approved_by, "approved_at": m.approved_at,
        "runtime": m.runtime,
    }


def _state(code: str) -> dict:
    return {"code": code, "label": FeatureState(code).label, "tone": STATE_TONE[FeatureState(code)]}


def _evaluation(code: str) -> dict:
    ev = ai.evaluate_feature(code)
    return {
        "labelled": ev.labelled, "above_cutoff": ev.above_cutoff,
        "precision": ev.precision, "meets_gate": ev.meets_gate, "reasons": ev.reasons,
    }


@api_view(["GET"])
@permission_classes([IsAdminConsoleUser])
def ai_overview(request):
    features = []
    for code, label in FeatureCode.choices:
        row = AiFeature.objects.select_related("model_version").filter(code=code).first()
        stored = FeatureState(row.state) if row else FeatureState.OFF
        effective = ai.feature_state(code)
        last = AiRun.objects.filter(feature=code).order_by("-started_at").first()
        features.append({
            "code": code,
            "label": label,
            "stored_state": _state(stored),
            "effective_state": _state(effective),
            "shown_to_reviewers": effective == FeatureState.ADVISORY,
            "model": _model(row),
            "gate_config": (row.gate_config if row else None) or {},
            "evaluation": _evaluation(code),
            "last_run": None if last is None else {
                "id": last.id, "started_at": last.started_at, "state": last.state,
                "scored": last.scored, "skipped": last.skipped, "note": last.note,
            },
            "changed_by": row.changed_by if row else "",
            "changed_at": row.changed_at if row else None,
        })
    return Response({
        "master_enabled": ai.master_enabled(),
        "features": features,
    })


@api_view(["GET"])
@permission_classes([IsAdminConsoleUser])
def ai_suggestions(request):
    """The newest run's suggestions for one feature, highest score first."""
    code = request.query_params.get("feature", "")
    if code not in FeatureCode.values:
        return Response(
            {"detail": f"feature must be one of {list(FeatureCode.values)}"},
            status=drf_status.HTTP_400_BAD_REQUEST,
        )
    try:
        limit = max(1, min(int(request.query_params.get("limit", DEFAULT_LIMIT)), MAX_LIMIT))
    except ValueError:
        return Response({"detail": "limit must be an integer"}, status=drf_status.HTTP_400_BAD_REQUEST)

    effective = ai.feature_state(code)
    run = AiRun.objects.filter(feature=code).order_by("-started_at").first()
    rows = []
    total = 0
    if run is not None:
        qs = AiSuggestion.objects.filter(run=run).order_by("-score", "id")
        total = qs.count()
        suggestions = list(qs[:limit])
        outcomes = {}
        if code == FeatureCode.DDUP_RANK:
            # Read by join, never copied (ADR-0045 D7).
            outcomes = dict(
                MergeDecision.objects.filter(
                    match_pair_id__in=[s.subject_id for s in suggestions],
                ).values_list("match_pair_id", "action")
            )
            statuses = dict(
                MatchPair.objects.filter(id__in=[s.subject_id for s in suggestions])
                .values_list("id", "status")
            )
        for s in suggestions:
            outcome = outcomes.get(s.subject_id)
            rows.append({
                "id": s.id,
                "subject_type": s.subject_type,
                "subject_id": s.subject_id,
                "score": s.score,
                "details": s.details,
                "reviewer_outcome": (
                    None if outcome is None
                    else {"code": outcome, "label": MergeAction(outcome).label}
                ),
                "subject_status": statuses.get(s.subject_id) if code == FeatureCode.DDUP_RANK else None,
            })
    return Response({
        "feature": code,
        "effective_state": _state(effective),
        "shown_to_reviewers": effective == FeatureState.ADVISORY,
        "run": None if run is None else {
            "id": run.id, "started_at": run.started_at, "state": run.state,
            "scored": run.scored, "skipped": run.skipped,
        },
        "total": total,
        "results": rows,
    })
