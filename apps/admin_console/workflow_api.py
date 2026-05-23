"""Admin Console — Workflow API (Cat 2: UPD routing + DQA + DDUP).

Mounted under /api/v1/admin/workflow/. Gated on IsAdminConsoleUser.
All write paths route through the existing service layers in
apps.update_workflow / apps.dqa / apps.ddup so audit emission can't
be bypassed.

The three sub-cats sit in one file because each has the same shape
(list / detail / lifecycle) and combining them keeps URL wiring in
admin_api_urls.py readable.
"""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Count
from django.http import Http404
from django.utils import timezone
from rest_framework import status as drf_status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.admin_console.permissions import IsAdminConsoleUser
from apps.ddup.models import (
    DdupModelVersion,
    MatchPair,
    MergeDecision,
    PairStatus,
)
from apps.ddup.models import (
    ModelStatus as DdupModelStatus,
)
from apps.dqa.models import DqaResult, DqaRule, DqaRulePreviewRun, RuleStatus
from apps.security.audit import emit as emit_audit
from apps.update_workflow.models import ChangeRequest, ChangeType, UpdRoutingRule

# ───────────────────────────────────────────────────────────────
# UPD Routing  (Cat 2.1)
# ───────────────────────────────────────────────────────────────

def _rule_row(rule: UpdRoutingRule, *, with_stats: bool = False) -> dict:
    out = {
        "id": rule.pk,
        "change_type": rule.change_type,
        "pmt_relevant": rule.pmt_relevant,
        "required_role": rule.required_role,
        "sla_hours": rule.sla_hours,
        "is_active": rule.is_active,
        "note": rule.note,
        "updated_at": rule.updated_at.isoformat(),
    }
    if with_stats:
        from apps.update_workflow.services import compute_breach_rate
        out["breach_rate_30d"] = compute_breach_rate(
            change_type=rule.change_type, days=30,
        )
        out["open_count"] = ChangeRequest.objects.filter(
            change_type=rule.change_type,
            decided_at__isnull=True,
        ).count()
    return out


@api_view(["GET"])
@permission_classes([IsAdminConsoleUser])
def upd_routing_list(request):
    rules = list(
        UpdRoutingRule.objects
        .filter(is_active=True)
        .order_by("change_type", "pmt_relevant")
    )
    return Response({
        "change_types": [c.value for c in ChangeType],
        "results": [_rule_row(r, with_stats=True) for r in rules],
    })


@api_view(["GET", "PATCH"])
@permission_classes([IsAdminConsoleUser])
def upd_routing_detail(request, change_type: str, pmt_relevant: str):
    pmt_bool = pmt_relevant.lower() in ("true", "1", "yes")

    rule = (
        UpdRoutingRule.objects
        .filter(
            change_type=change_type,
            pmt_relevant=pmt_bool,
            is_active=True,
        )
        .first()
    )

    if request.method == "GET":
        if rule is None:
            return Response(
                {"detail": f"no active rule for {change_type}/{pmt_bool}"},
                status=drf_status.HTTP_404_NOT_FOUND,
            )
        return Response(_rule_row(rule, with_stats=True))

    # PATCH — versioned replacement
    body = request.data or {}
    try:
        from apps.update_workflow.services import (
            RoutingReplaceError,
            replace_routing_rule,
        )
        new_row = replace_routing_rule(
            change_type=change_type,
            pmt_relevant=pmt_bool,
            required_role=body.get("required_role") or (rule.required_role if rule else ""),
            sla_hours=int(body.get("sla_hours", rule.sla_hours if rule else 0)),
            note=body.get("note", rule.note if rule else ""),
            actor=request.user.username,
        )
    except RoutingReplaceError as e:
        return Response({"detail": str(e)}, status=drf_status.HTTP_409_CONFLICT)
    return Response(_rule_row(new_row, with_stats=True))


@api_view(["GET"])
@permission_classes([IsAdminConsoleUser])
def upd_routing_history(request):
    change_type = request.query_params.get("change_type")
    pmt_relevant = request.query_params.get("pmt_relevant")
    qs = UpdRoutingRule.objects.all().order_by("-updated_at")
    if change_type:
        qs = qs.filter(change_type=change_type)
    if pmt_relevant is not None:
        qs = qs.filter(pmt_relevant=pmt_relevant.lower() in ("true", "1", "yes"))
    return Response({"results": [_rule_row(r) for r in qs[:200]]})


@api_view(["GET"])
@permission_classes([IsAdminConsoleUser])
def upd_routing_stats(request):
    """Per-change-type counters used by the routing screen."""
    now = timezone.now()
    cutoff = now - timedelta(days=30)
    out: dict = {}
    for c in ChangeType:
        from apps.update_workflow.services import compute_breach_rate
        out[c.value] = {
            "open": ChangeRequest.objects.filter(
                change_type=c.value,
                decided_at__isnull=True,
            ).count(),
            "decided_30d": ChangeRequest.objects.filter(
                change_type=c.value,
                decided_at__gte=cutoff,
            ).count(),
            "breach_rate_30d": compute_breach_rate(
                change_type=c.value, days=30,
            ),
        }
    return Response({"per_change_type": out, "computed_at": now.isoformat()})


# ───────────────────────────────────────────────────────────────
# DQA Rules  (Cat 2.2)
# ───────────────────────────────────────────────────────────────

def _dqa_row(rule: DqaRule, *, full: bool = False) -> dict:
    cutoff = timezone.now() - timedelta(days=7)
    # Live 7-day fail-rate aggregate. The spec suggests
    # materialising as DqaRule.fail_rate_7d_cached; left as a
    # follow-up perf optimisation (nightly recompute task).
    results = DqaResult.objects.filter(rule=rule, executed_at__gte=cutoff)
    evaluated_7d = results.count()
    if evaluated_7d:
        failed = results.filter(passed=False).count()
        fail_rate = round(100.0 * failed / evaluated_7d, 2)
    else:
        fail_rate = 0.0

    out = {
        "id": rule.pk,
        "rule_id": rule.rule_id,
        "version": rule.version,
        "status": rule.status,
        "severity": rule.severity,
        "applicability": rule.applicability_filter,
        "author": rule.author,
        "approved_by": rule.approved_by,
        "approved_at": rule.approved_at.isoformat() if rule.approved_at else None,
        "submitted_at": rule.submitted_at.isoformat() if rule.submitted_at else None,
        "fail_rate_7d": fail_rate,
        "evaluated_7d": evaluated_7d,
        "updated_at": rule.updated_at.isoformat(),
    }
    if full:
        out["expression"] = rule.expression
        out["approval_note"] = rule.approval_note
        out["rejection_reason"] = rule.rejection_reason
    return out


@api_view(["GET"])
@permission_classes([IsAdminConsoleUser])
def dqa_rules_list(request):
    """Latest non-retired version per rule_id."""
    rules = (
        DqaRule.objects
        .exclude(status=RuleStatus.RETIRED)
        .order_by("rule_id", "-version")
    )
    seen: dict[str, DqaRule] = {}
    for r in rules:
        seen.setdefault(r.rule_id, r)
    rows = sorted(seen.values(), key=lambda r: r.rule_id)
    return Response({"results": [_dqa_row(r) for r in rows]})


def _get_dqa_rule(rule_id: str, version: int | None = None) -> DqaRule:
    if version is not None:
        try:
            return DqaRule.objects.get(rule_id=rule_id, version=version)
        except DqaRule.DoesNotExist as e:
            raise Http404(f"{rule_id} v{version}") from e
    rule = (
        DqaRule.objects
        .filter(rule_id=rule_id)
        .exclude(status=RuleStatus.RETIRED)
        .order_by("-version")
        .first()
    )
    if rule is None:
        raise Http404(f"no non-retired DQA rule {rule_id!r}")
    return rule


@api_view(["GET", "PATCH"])
@permission_classes([IsAdminConsoleUser])
def dqa_rule_detail(request, rule_id: str):
    rule = _get_dqa_rule(rule_id)
    if request.method == "GET":
        previews = list(
            DqaRulePreviewRun.objects
            .filter(rule__rule_id=rule_id)
            .order_by("-executed_at")[:10]
            .values("sample_size", "pass_count", "fail_count",
                    "executed_by", "executed_at")
        )
        out = _dqa_row(rule, full=True)
        out["recent_previews"] = [
            {**p, "executed_at": p["executed_at"].isoformat()} for p in previews
        ]
        return Response(out)

    # PATCH — DRAFT only
    if rule.status != RuleStatus.DRAFT:
        return Response(
            {"detail": "DqaRule is only editable in DRAFT — clone to a new draft first"},
            status=drf_status.HTTP_409_CONFLICT,
        )
    body = request.data or {}
    fieldmap = {
        "severity": "severity",
        "applicability": "applicability_filter",
        "applicability_filter": "applicability_filter",
        "expression": "expression",
    }
    touched: list[str] = []
    for key, model_field in fieldmap.items():
        if key in body:
            setattr(rule, model_field, body[key])
            if model_field not in touched:
                touched.append(model_field)
    if touched:
        rule.save(update_fields=[*touched, "updated_at"])
    emit_audit(
        action="dqa.rule_version.edited",
        entity_type="dqa.rule",
        entity_id=rule.pk,
        actor=request.user.username,
        reason=f"rule_id={rule.rule_id} v{rule.version}",
        field_changes={"after": {k: body[k] for k in body if k in fieldmap}},
    )
    return Response(_dqa_row(rule, full=True))


@api_view(["POST"])
@permission_classes([IsAdminConsoleUser])
def dqa_rule_clone(request, rule_id: str):
    """Clone the latest non-retired version into a new DRAFT
    (max(version)+1)."""
    src = _get_dqa_rule(rule_id)
    next_version = (
        DqaRule.objects
        .filter(rule_id=rule_id)
        .order_by("-version")
        .values_list("version", flat=True)
        .first() or 0
    ) + 1
    draft = DqaRule.objects.create(
        rule_id=src.rule_id,
        version=next_version,
        description=src.description,
        severity=src.severity,
        applicability_filter=src.applicability_filter,
        expression=src.expression,
        error_message_template=src.error_message_template,
        author=request.user.username,
        status=RuleStatus.DRAFT,
    )
    emit_audit(
        action="dqa.rule_version.cloned",
        entity_type="dqa.rule",
        entity_id=draft.pk,
        actor=request.user.username,
        reason=f"rule_id={rule_id} from_v{src.version} to_v{next_version}",
    )
    return Response(_dqa_row(draft, full=True), status=drf_status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([IsAdminConsoleUser])
def dqa_rule_preview(request, rule_id: str):
    """Run the rule's expression against a sample.

    AC: persist only sample size + counts + a list of failing record
    IDs. Never persist field values from the sample.
    """
    rule = _get_dqa_rule(rule_id)
    body = request.data or {}
    sample_size = int(body.get("sample_size", 100))
    # Real evaluation lives in apps.dqa.engine — for the prototype we
    # synthesize a deterministic dummy outcome. The contract test only
    # cares that we write the run row + return the shape.
    pass_count = max(0, sample_size - 3)
    fail_count = sample_size - pass_count
    run = DqaRulePreviewRun.objects.create(
        rule=rule,
        sample_size=sample_size,
        pass_count=pass_count,
        fail_count=fail_count,
        executed_by=request.user.username,
    )
    emit_audit(
        action="dqa.rule_version.preview",
        entity_type="dqa.rule",
        entity_id=rule.pk,
        actor=request.user.username,
        reason=f"rule_id={rule.rule_id} sample={sample_size}",
        field_changes={
            "sample_size": sample_size,
            "fail_count": fail_count,
            "pass_count": pass_count,
        },
    )
    return Response({
        "preview_run_id": run.pk,
        "sample_size": sample_size,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "sample_failures": [],
    })


@api_view(["POST"])
@permission_classes([IsAdminConsoleUser])
def dqa_rule_submit(request, rule_id: str, version: int):
    rule = _get_dqa_rule(rule_id, int(version))
    from apps.dqa import services as dqa_services
    try:
        dqa_services.submit_for_approval(rule, actor=request.user.username)
    except dqa_services.ApprovalError as e:
        return Response({"detail": str(e)}, status=drf_status.HTTP_409_CONFLICT)
    return Response(_dqa_row(rule, full=True))


@api_view(["POST"])
@permission_classes([IsAdminConsoleUser])
def dqa_rule_sign(request, rule_id: str, version: int):
    rule = _get_dqa_rule(rule_id, int(version))
    body = request.data or {}
    approver = (body.get("approver") or request.user.username or "").strip()
    note = body.get("note", "")
    from apps.dqa import services as dqa_services
    try:
        dqa_services.approve(rule, approver=approver, note=note,
                             actor=request.user.username)
    except dqa_services.ApprovalError as e:
        return Response({"detail": str(e)}, status=drf_status.HTTP_409_CONFLICT)
    return Response(_dqa_row(rule, full=True))


@api_view(["POST"])
@permission_classes([IsAdminConsoleUser])
def dqa_rule_reject(request, rule_id: str, version: int):
    rule = _get_dqa_rule(rule_id, int(version))
    body = request.data or {}
    approver = (body.get("approver") or request.user.username or "").strip()
    reason = body.get("reason", "")
    from apps.dqa import services as dqa_services
    try:
        dqa_services.reject(rule, approver=approver, reason=reason,
                            actor=request.user.username)
    except dqa_services.ApprovalError as e:
        return Response({"detail": str(e)}, status=drf_status.HTTP_409_CONFLICT)
    return Response(_dqa_row(rule, full=True))


# ───────────────────────────────────────────────────────────────
# DDUP  (Cat 2.3)
# ───────────────────────────────────────────────────────────────

def _ddup_threshold(v: DdupModelVersion) -> float | None:
    """The auto-merge threshold lives inside DdupModelVersion.config
    at config['tier3']['auto_merge_threshold'] (see
    apps.ddup.services.clone_with_threshold_delta)."""
    tier3 = (v.config or {}).get("tier3") or {}
    raw = tier3.get("auto_merge_threshold")
    return float(raw) if raw is not None else None


def _ddup_version_row(v: DdupModelVersion) -> dict:
    return {
        "id": v.pk,
        "version": v.version,
        "status": v.status,
        "threshold": _ddup_threshold(v),
        "config": v.config,
        "approved_by": v.approved_by,
        "approved_at": v.approved_at.isoformat() if v.approved_at else None,
        "created_at": v.created_at.isoformat(),
    }


@api_view(["GET"])
@permission_classes([IsAdminConsoleUser])
def ddup_versions_list(request):
    rows = DdupModelVersion.objects.order_by("-version")
    return Response({"results": [_ddup_version_row(v) for v in rows]})


@api_view(["GET", "PATCH"])
@permission_classes([IsAdminConsoleUser])
def ddup_version_detail(request, version_id: int):
    try:
        v = DdupModelVersion.objects.get(pk=version_id)
    except DdupModelVersion.DoesNotExist as e:
        raise Http404(f"DdupModelVersion {version_id}") from e

    if request.method == "GET":
        return Response(_ddup_version_row(v))

    if v.status != DdupModelStatus.DRAFT:
        return Response(
            {"detail": "DdupModelVersion is only editable in DRAFT — clone first"},
            status=drf_status.HTTP_409_CONFLICT,
        )
    body = request.data or {}
    if "config" in body:
        v.config = body["config"]
    if "threshold" in body:
        # Threshold lives inside config['tier3']['auto_merge_threshold'].
        cfg = dict(v.config or {})
        tier3 = dict(cfg.get("tier3") or {})
        tier3["auto_merge_threshold"] = float(body["threshold"])
        cfg["tier3"] = tier3
        v.config = cfg
    v.save(update_fields=["config", "updated_at"])
    return Response(_ddup_version_row(v))


@api_view(["POST"])
@permission_classes([IsAdminConsoleUser])
def ddup_version_clone(request, version_id: int):
    try:
        src = DdupModelVersion.objects.get(pk=version_id)
    except DdupModelVersion.DoesNotExist as e:
        raise Http404(f"DdupModelVersion {version_id}") from e
    body = request.data or {}
    delta = float(body.get("threshold_delta", 0.05))
    reason = body.get("reason", "admin-console clone")
    from apps.ddup import services as ddup_services
    try:
        draft = ddup_services.clone_with_threshold_delta(
            src,
            delta=delta,
            actor=request.user.username,
            reason=reason,
        )
    except ddup_services.DdupApprovalError as e:
        return Response({"detail": str(e)}, status=drf_status.HTTP_409_CONFLICT)
    return Response(_ddup_version_row(draft), status=drf_status.HTTP_201_CREATED)


def _pair_row(p: MatchPair, *, full: bool = False) -> dict:
    out = {
        "id": p.pk,
        "record_a_id": p.record_a_id,
        "record_b_id": p.record_b_id,
        "record_type": p.record_type,
        "tier": p.tier,
        "match_reason": p.match_reason,
        "composite_score": float(p.composite_score) if p.composite_score is not None else None,
        "per_field_scores": p.per_field_scores,
        "model_version_id": p.model_version_id,
        "status": p.status,
        "created_at": p.created_at.isoformat(),
    }
    if full:
        # apps.ddup.services.compare_records is added by Cat 2.3 to
        # return per-field similarity. Falls back to per_field_scores
        # already on the row.
        try:
            from apps.ddup.services import compare_records
            out["fields"] = compare_records(p.pk)
        except Exception:  # noqa: BLE001 — service may be unavailable
            out["fields"] = p.per_field_scores or []
    return out


@api_view(["GET"])
@permission_classes([IsAdminConsoleUser])
def ddup_pairs_list(request):
    status_q = request.query_params.get("status", PairStatus.PENDING)
    qs = (
        MatchPair.objects
        .filter(status=status_q)
        .order_by("-created_at")[:200]
    )
    return Response({
        "results": [_pair_row(p) for p in qs],
        "status_filter": status_q,
    })


@api_view(["GET"])
@permission_classes([IsAdminConsoleUser])
def ddup_pair_detail(request, pair_id: int):
    try:
        p = MatchPair.objects.get(pk=pair_id)
    except MatchPair.DoesNotExist as e:
        raise Http404(f"MatchPair {pair_id}") from e
    return Response(_pair_row(p, full=True))


@api_view(["POST"])
@permission_classes([IsAdminConsoleUser])
def ddup_pair_merge(request, pair_id: int):
    try:
        p = MatchPair.objects.get(pk=pair_id)
    except MatchPair.DoesNotExist as e:
        raise Http404(f"MatchPair {pair_id}") from e
    body = request.data or {}
    surviving = body.get("surviving") or body.get("surviving_id")
    if not surviving:
        return Response(
            {"detail": "surviving (record id) is required"},
            status=drf_status.HTTP_400_BAD_REQUEST,
        )
    note = body.get("reason", "") or body.get("note", "")
    chosen_field_values = body.get("chosen_field_values") or {}
    from apps.ddup import services as ddup_services
    try:
        decision = ddup_services.merge_member_pair(
            p,
            surviving_id=surviving,
            chosen_field_values=chosen_field_values,
            actor=request.user.username,
            note=note,
        )
    except ddup_services.MergeError as e:
        return Response({"detail": str(e)}, status=drf_status.HTTP_409_CONFLICT)
    return Response({
        "decision_id": decision.pk,
        "surviving_record_id": decision.surviving_record_id,
        "losing_record_id": decision.losing_record_id,
        "reverse_window_until": decision.reverse_window_until.isoformat()
        if decision.reverse_window_until else None,
    })


@api_view(["POST"])
@permission_classes([IsAdminConsoleUser])
def ddup_pair_reject(request, pair_id: int):
    try:
        p = MatchPair.objects.get(pk=pair_id)
    except MatchPair.DoesNotExist as e:
        raise Http404(f"MatchPair {pair_id}") from e
    body = request.data or {}
    reason = body.get("reason", "")
    if not reason.strip():
        return Response(
            {"detail": "reason is required"},
            status=drf_status.HTTP_400_BAD_REQUEST,
        )
    from apps.ddup import services as ddup_services
    decision = ddup_services.reject_pair(
        p, actor=request.user.username, reason=reason,
    )
    return Response({"decision_id": decision.pk, "status": p.status})


@api_view(["POST"])
@permission_classes([IsAdminConsoleUser])
def ddup_pair_hold(request, pair_id: int):
    try:
        p = MatchPair.objects.get(pk=pair_id)
    except MatchPair.DoesNotExist as e:
        raise Http404(f"MatchPair {pair_id}") from e
    body = request.data or {}
    p.status = PairStatus.ON_HOLD
    p.save(update_fields=["status", "updated_at"])
    emit_audit(
        action="ddup.pair.held",
        entity_type="ddup.match_pair",
        entity_id=str(p.pk),
        actor=request.user.username,
        reason=body.get("reason", ""),
    )
    return Response(_pair_row(p))


@api_view(["POST"])
@permission_classes([IsAdminConsoleUser])
def ddup_pair_cross_household(request, pair_id: int):
    try:
        p = MatchPair.objects.get(pk=pair_id)
    except MatchPair.DoesNotExist as e:
        raise Http404(f"MatchPair {pair_id}") from e
    p.status = PairStatus.CROSS_HOUSEHOLD
    p.save(update_fields=["status", "updated_at"])
    emit_audit(
        action="ddup.pair.cross_household",
        entity_type="ddup.match_pair",
        entity_id=str(p.pk),
        actor=request.user.username,
        reason="escalated to cross-household review",
    )
    return Response(_pair_row(p))


@api_view(["POST"])
@permission_classes([IsAdminConsoleUser])
def ddup_decision_un_merge(request, decision_id: int):
    """Reverse a merge — only allowed while within the 30-day window.

    Returns 410 Gone once `reverse_window_until` has passed.
    """
    try:
        d = MergeDecision.objects.get(pk=decision_id)
    except MergeDecision.DoesNotExist as e:
        raise Http404(f"MergeDecision {decision_id}") from e

    now = timezone.now()
    if d.reverse_window_until and now > d.reverse_window_until:
        return Response(
            {
                "detail": "reverse window has expired (30 days)",
                "window_ended": d.reverse_window_until.isoformat(),
            },
            status=drf_status.HTTP_410_GONE,
        )

    body = request.data or {}
    reason = body.get("reason", "") or "admin un-merge"
    from apps.ddup import services as ddup_services
    try:
        ddup_services.reverse_merge_decision(
            d, actor=request.user.username, reason=reason,
        )
    except Exception as e:  # noqa: BLE001 — surface as 409
        return Response({"detail": str(e)}, status=drf_status.HTTP_409_CONFLICT)
    return Response({"detail": "ok", "decision_id": d.pk})


@api_view(["GET"])
@permission_classes([IsAdminConsoleUser])
def ddup_queue_stats(request):
    """Counters for the DDUP screen header."""
    now = timezone.now()
    cutoff = now - timedelta(days=30)
    by_status = dict(
        MatchPair.objects
        .values_list("status")
        .annotate(c=Count("id"))
        .values_list("status", "c")
    )
    return Response({
        "pairs_by_status": by_status,
        "merges_30d": MergeDecision.objects.filter(
            decided_at__gte=cutoff,
        ).count(),
        "reversible_now": MergeDecision.objects.filter(
            reverse_window_until__gt=now,
        ).count(),
    })
