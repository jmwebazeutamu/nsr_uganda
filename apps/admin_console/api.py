"""Admin Console DRF surface (HANDOFF — Admin Console + PMT §5).

All endpoints mounted under /api/v1/admin/. Group-gated via
`apps.admin_console.permissions.IsAdminConsoleUser`. The dashboard
endpoint assembles the prototype's union shape from the PMT
snapshot tables + the active model + recent audit events.
"""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Count
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response

from apps.admin_console.permissions import IsAdminConsoleUser
from apps.pmt.models import (
    PMTBandSnapshot,
    PMTBandThreshold,
    PMTCoverageSnapshot,
    PMTModelSignOff,
    PMTModelVersion,
    PMTRecomputeJobRun,
    PMTResult,
    PMTSubregionSnapshot,
    PMTVariableInfluence,
)
from apps.security.models import AuditEvent

# ───────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────

def _active_model_payload() -> dict:
    """Top card on the dashboard — active model + latest threshold
    per band + staleness flags per ADR-0023."""
    mv = (
        PMTModelVersion.objects
        .filter(status="active")
        .order_by("-version")
        .first()
    )
    if mv is None:
        return {}
    year = timezone.now().year
    cal_end = mv.calibration_year_end or 0
    thresholds_latest: dict[str, float] = {}
    thresholds_at = ""
    sample_size = 0
    for row in (
        PMTBandThreshold.objects
        .filter(model_version=mv)
        .order_by("band_name", "-computed_at")
    ):
        if row.band_name not in thresholds_latest:
            thresholds_latest[row.band_name] = float(row.score_threshold)
            thresholds_at = row.computed_at.isoformat()
            sample_size = max(sample_size, row.sample_size)
    return {
        "id": str(mv.id),
        "version": mv.version,
        "status": mv.status,
        "description": mv.description,
        "author": mv.author,
        "approved_by": mv.approved_by,
        "approved_at": mv.approved_at.isoformat() if mv.approved_at else "",
        "effective_from": mv.effective_from.isoformat() if mv.effective_from else "",
        "band_strategy": mv.band_strategy,
        "intercept": float(mv.intercept) if mv.intercept is not None else 0,
        "validation_r_squared":
            float(mv.validation_r_squared) if mv.validation_r_squared else None,
        "calibration_dataset": mv.calibration_dataset,
        "calibration_year_end": mv.calibration_year_end,
        "calibration_stale": bool(cal_end and year - cal_end >= 3),
        "years_to_stale": max(0, (cal_end + 3 - year)) if cal_end else None,
        "variables_count": len(mv.variables or []),
        "band_cutoffs_percentile": mv.band_cutoffs or {},
        "thresholds_latest": thresholds_latest,
        "thresholds_computed_at": thresholds_at,
        "thresholds_sample_size": sample_size,
    }


def _bands_payload(mv: PMTModelVersion | None) -> list:
    """Latest PMTBandSnapshot rows for the active model. Falls back
    to a live aggregation off PMTResult when no snapshot exists."""
    if mv is None:
        return []
    latest = (
        PMTBandSnapshot.objects
        .filter(model_version=mv)
        .order_by("band", "-taken_at")
    )
    seen: dict[str, dict] = {}
    for row in latest:
        if row.band in seen:
            continue
        seen[row.band] = {
            "band": row.band,
            "count": row.count,
            "pct": float(row.pct),
        }
    if seen:
        return list(seen.values())
    # No snapshot yet — aggregate live.
    rows = (
        PMTResult.objects
        .filter(model_version=mv)
        .values("band")
        .annotate(c=Count("*"))
    )
    total = sum(r["c"] for r in rows) or 1
    return [
        {
            "band": r["band"],
            "count": r["c"],
            "pct": round(r["c"] * 100.0 / total, 2),
        }
        for r in rows
    ]


def _coverage_payload() -> dict:
    snap = PMTCoverageSnapshot.objects.order_by("-taken_at").first()
    if snap is None:
        return {
            "total_households": 0, "scored": 0,
            "scored_30d": 0, "scored_90d": 0, "stale_12mo": 0,
            "taken_at": "",
        }
    return {
        "total_households": snap.total_households,
        "scored": snap.scored,
        "scored_30d": snap.scored_30d,
        "scored_90d": snap.scored_90d,
        "stale_12mo": snap.stale_12mo,
        "taken_at": snap.taken_at.isoformat(),
    }


def _variables_top_payload(mv: PMTModelVersion | None, limit: int = 10) -> list:
    if mv is None:
        return []
    rows = (
        PMTVariableInfluence.objects
        .filter(model_version=mv)
        .order_by("-influence")[:limit]
    )
    return [
        {
            "name": r.variable_name,
            "weight": float(r.weight),
            "sample_mean": float(r.sample_mean),
            "influence": float(r.influence),
        }
        for r in rows
    ]


def _geo_payload(mv: PMTModelVersion | None, limit: int = 20) -> list:
    if mv is None:
        return []
    latest = (
        PMTSubregionSnapshot.objects
        .filter(model_version=mv)
        .order_by("sub_region_code", "-taken_at")
    )
    seen: dict[str, dict] = {}
    for row in latest:
        if row.sub_region_code in seen:
            continue
        seen[row.sub_region_code] = {
            "sub_region_code": row.sub_region_code,
            "sub_region_name": row.sub_region_name,
            "total_households": row.total_households,
            "scored_households": row.scored_households,
            "in_poverty_count": row.in_poverty_count,
            "poverty_rate": float(row.poverty_rate),
        }
    return list(seen.values())[:limit]


def _drift_payload(mv: PMTModelVersion | None, weeks: int = 6) -> list:
    """Threshold drift history. Reads PMTBandThreshold rows over
    the last N ISO weeks; groups by week + band."""
    if mv is None:
        return []
    cutoff = timezone.now() - timedelta(weeks=weeks + 1)
    rows = (
        PMTBandThreshold.objects
        .filter(model_version=mv, computed_at__gte=cutoff)
        .order_by("computed_at")
    )
    by_week: dict[str, dict] = {}
    for r in rows:
        iso_year, iso_week, _ = r.computed_at.isocalendar()
        wk = f"{iso_year}-W{iso_week:02d}"
        bucket = by_week.setdefault(wk, {"wk": wk})
        # Last value of the week per band wins.
        bucket[r.band_name] = float(r.score_threshold)
    return list(by_week.values())


def _triggers_payload(days: int = 90) -> list:
    cutoff = timezone.now() - timedelta(days=days)
    rows = (
        PMTResult.objects
        .filter(computed_at__gte=cutoff)
        .values("triggered_by")
        .annotate(c=Count("*"))
        .order_by("-c")
    )
    total = sum(r["c"] for r in rows) or 1
    return [
        {
            "code": r["triggered_by"] or "manual",
            "count": r["c"],
            "share": round(r["c"] * 100.0 / total, 2),
        }
        for r in rows
    ]


def _job_payload() -> dict:
    last = PMTRecomputeJobRun.objects.order_by("-started_at").first()
    recent = list(
        PMTRecomputeJobRun.objects
        .order_by("-started_at")
        .values(
            "id", "started_at", "finished_at", "status",
            "rows_written", "sample_size", "actor",
        )[:5]
    )
    for r in recent:
        r["id"] = str(r["id"])
        r["started_at"] = r["started_at"].isoformat() if r["started_at"] else ""
        r["finished_at"] = r["finished_at"].isoformat() if r["finished_at"] else ""
    return {
        "last_run": {
            "status": last.status if last else "",
            "started_at": last.started_at.isoformat() if last else "",
            "finished_at": last.finished_at.isoformat() if (last and last.finished_at) else "",
            "rows_written": last.rows_written if last else 0,
            "sample_size": last.sample_size if last else 0,
        } if last else {},
        "recent_runs": recent,
    }


def _recent_events_payload(limit: int = 6) -> list:
    rows = (
        AuditEvent.objects
        .filter(entity_type__in=[
            "pmt_model_version", "pmt_result", "pmt_band_threshold",
        ])
        .order_by("-occurred_at")[:limit]
    )
    return [
        {
            "id": str(e.id),
            "actor": e.actor_id,
            "action": e.action,
            "entity_type": e.entity_type,
            "entity_id": e.entity_id,
            "occurred_at": e.occurred_at.isoformat(),
            "reason": e.reason or "",
        }
        for e in rows
    ]


# ───────────────────────────────────────────────────────────────
# Dashboard endpoint
# ───────────────────────────────────────────────────────────────

@extend_schema(
    tags=["admin-console"],
    summary="PMT Dashboard union payload",
    description=(
        "Single round-trip read for the PMT Dashboard screen "
        "(HANDOFF §4.1). Reads from PMTModelVersion + the snapshot "
        "tables (PMTBandSnapshot / PMTSubregionSnapshot / "
        "PMTCoverageSnapshot / PMTVariableInfluence / "
        "PMTRecomputeJobRun) + PMTBandThreshold drift + recent "
        "AuditEvents. Snapshots are written nightly by the "
        "recompute_dashboard_snapshots Celery beat job."
    ),
)
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated, IsAdminConsoleUser])
def pmt_dashboard(request):
    mv = (
        PMTModelVersion.objects
        .filter(status="active")
        .order_by("-version")
        .first()
    )
    return Response({
        "active": _active_model_payload(),
        "bands": _bands_payload(mv),
        "coverage": _coverage_payload(),
        "variables_top": _variables_top_payload(mv),
        "geo": _geo_payload(mv),
        "drift": _drift_payload(mv),
        "triggers": _triggers_payload(),
        "job": _job_payload(),
        "recent_events": _recent_events_payload(),
    })


@extend_schema(
    tags=["admin-console"],
    summary="Trigger an ad-hoc band-threshold + dashboard-snapshot recompute",
)
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated, IsAdminConsoleUser])
def pmt_recompute_run_now(request):
    """Synchronous run for now (Celery wiring deferred). Writes a
    PMTRecomputeJobRun row, re-aggregates the snapshot tables, and
    re-runs the empirical band-threshold percentile pass."""
    from apps.admin_console.snapshots import recompute_dashboard_snapshots
    actor = str(request.user.username or request.user.id)
    run = recompute_dashboard_snapshots(actor=actor)
    return Response({
        "id": str(run.id),
        "status": run.status,
        "rows_written": run.rows_written,
        "sample_size": run.sample_size,
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else "",
        # report_url is what the dashboard's "Download report" button
        # points at after a successful Run-now.
        "report_url": f"/api/v1/admin/pmt/recompute/runs/{run.id}/report/",
    }, status=status.HTTP_202_ACCEPTED)


@extend_schema(
    tags=["admin-console"],
    summary="Downloadable report for a single recompute run",
    description=(
        "Returns the computational artefacts of a single "
        "PMTRecomputeJobRun: run metadata, active-model context at "
        "run time, the PMTBandThreshold rows written during the run "
        "(filtered by computed_at ∈ [started_at, finished_at]), and "
        "a distribution summary (min / p25 / median / p75 / max) of "
        "the PMTResult.score population the run percentiled across. "
        "Pass ?as=csv for a flat CSV download; default response is "
        "JSON. (`format` is reserved by DRF for content negotiation, "
        "so we use `as` here.) Operators use this for audit / sign-off."
    ),
)
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated, IsAdminConsoleUser])
def pmt_recompute_run_report(request, run_id: str):
    """Build the report for one PMTRecomputeJobRun."""
    from apps.pmt.models import (
        PMTBandThreshold,
        PMTModelVersion,
        PMTRecomputeJobRun,
        PMTResult,
    )
    try:
        run = PMTRecomputeJobRun.objects.get(id=run_id)
    except PMTRecomputeJobRun.DoesNotExist:
        return Response({"detail": "run not found"}, status=status.HTTP_404_NOT_FOUND)

    mv = PMTModelVersion.objects.filter(status="active").order_by("-version").first()
    model_ctx = {}
    if mv is not None:
        model_ctx = {
            "id": str(mv.id),
            "version": mv.version,
            "band_strategy": mv.band_strategy,
            "band_cutoffs": mv.band_cutoffs or {},
            "calibration_dataset": mv.calibration_dataset or "",
            "calibration_year_end": mv.calibration_year_end,
            "intercept": float(mv.intercept) if mv.intercept is not None else None,
            "validation_r_squared":
                float(mv.validation_r_squared)
                if mv.validation_r_squared is not None else None,
            "variables_count": len(mv.variables or []),
        }

    # Threshold rows written during this run. computed_at must fall
    # within the run's wall-clock window. Inclusive of the start so
    # the same-instant row (timestamp == started_at) is included.
    rows: list[dict] = []
    if mv is not None and run.finished_at is not None:
        qs = PMTBandThreshold.objects.filter(
            model_version=mv,
            computed_at__gte=run.started_at,
            computed_at__lte=run.finished_at,
        ).order_by("percentile_rank")
        for r in qs:
            rows.append({
                "band_name": r.band_name,
                "percentile_rank": r.percentile_rank,
                "score_threshold": float(r.score_threshold),
                "sample_size": r.sample_size,
                "computed_at": r.computed_at.isoformat(),
            })

    # Distribution summary for context — same population the run
    # percentiled across. Cheap to recompute since sample_size is
    # the gating factor anyway.
    distribution: dict = {}
    if mv is not None:
        scores = sorted(
            float(s) for s in
            PMTResult.objects
            .filter(model_version=mv, household__is_deleted=False)
            .values_list("score", flat=True)
        )
        if scores:
            n = len(scores)
            def _q(rank: int) -> float:
                pos = (rank / 100.0) * (n - 1)
                lo = int(pos)
                hi = min(lo + 1, n - 1)
                frac = pos - lo
                return scores[lo] + (scores[hi] - scores[lo]) * frac
            distribution = {
                "n": n,
                "min": scores[0],
                "p25": _q(25),
                "median": _q(50),
                "p75": _q(75),
                "max": scores[-1],
            }

    payload = {
        "run": {
            "id": str(run.id),
            "actor": run.actor,
            "status": run.status,
            "started_at": run.started_at.isoformat(),
            "finished_at": run.finished_at.isoformat() if run.finished_at else "",
            "duration_ms": (
                int((run.finished_at - run.started_at).total_seconds() * 1000)
                if run.finished_at else None
            ),
            "rows_written": run.rows_written,
            "sample_size": run.sample_size,
            "note": run.note or "",
        },
        "active_model": model_ctx,
        "thresholds_written": rows,
        "distribution": distribution,
    }

    if (request.query_params.get("as") or "").lower() == "csv":
        return _render_report_as_csv(payload)
    return Response(payload)


def _render_report_as_csv(payload: dict):
    """Flat CSV for ops download. One section per logical block,
    blank-line separated — Excel renders this cleanly without
    needing a workbook generator."""
    import csv
    import io

    from django.http import HttpResponse

    buf = io.StringIO()
    w = csv.writer(buf)

    run = payload["run"]
    w.writerow(["section", "run"])
    w.writerow(["run_id", run["id"]])
    w.writerow(["actor", run["actor"]])
    w.writerow(["status", run["status"]])
    w.writerow(["started_at", run["started_at"]])
    w.writerow(["finished_at", run["finished_at"]])
    w.writerow(["duration_ms", run["duration_ms"] if run["duration_ms"] is not None else ""])
    w.writerow(["rows_written", run["rows_written"]])
    w.writerow(["sample_size", run["sample_size"]])
    w.writerow(["note", run["note"]])
    w.writerow([])

    mc = payload["active_model"] or {}
    w.writerow(["section", "active_model"])
    for k in ("id", "version", "band_strategy", "calibration_dataset",
              "calibration_year_end", "intercept", "validation_r_squared",
              "variables_count"):
        if k in mc:
            w.writerow([k, mc[k] if mc[k] is not None else ""])
    cutoffs = mc.get("band_cutoffs") or {}
    for band, rank in cutoffs.items():
        w.writerow([f"band_cutoffs.{band}", rank])
    w.writerow([])

    w.writerow(["section", "thresholds_written"])
    w.writerow(["band_name", "percentile_rank", "score_threshold",
                "sample_size", "computed_at"])
    for r in payload["thresholds_written"]:
        w.writerow([
            r["band_name"], r["percentile_rank"],
            f'{r["score_threshold"]:.6f}',
            r["sample_size"], r["computed_at"],
        ])
    w.writerow([])

    dist = payload["distribution"] or {}
    w.writerow(["section", "distribution"])
    for k in ("n", "min", "p25", "median", "p75", "max"):
        if k in dist:
            v = dist[k]
            w.writerow([k, f"{v:.6f}" if isinstance(v, float) else v])

    response = HttpResponse(buf.getvalue(), content_type="text/csv")
    filename = f"pmt-recompute-{run['id']}.csv"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# ───────────────────────────────────────────────────────────────
# Configuration endpoints (PMTModelVersion CRUD + sign-off + sim)
# ───────────────────────────────────────────────────────────────

class PMTModelVersionAdminViewSet(viewsets.ViewSet):
    """Admin-side CRUD for PMTModelVersion (HANDOFF §5.2).

    DRAFT rows are editable; ACTIVE rows refuse PATCH (must clone).
    Sign-off transitions delegate to apps.pmt.services.
    """

    permission_classes = [permissions.IsAuthenticated, IsAdminConsoleUser]

    def list(self, request):
        # REJECTED versions are kept on the audit chain but hidden
        # from the default listing so the operator UI behaves as if
        # they were deleted. Pass ?include_rejected=1 to surface them
        # (e.g. for audit / forensics views).
        qs = PMTModelVersion.objects.all()
        include_rejected = request.query_params.get("include_rejected")
        if not include_rejected or include_rejected in ("0", "false", "no"):
            qs = qs.exclude(status="rejected")
        rows = qs.order_by("-version")
        return Response({
            "results": [_version_summary(mv) for mv in rows],
            "count": rows.count(),
        })

    def retrieve(self, request, pk=None):
        mv = PMTModelVersion.objects.get(pk=pk)
        return Response(_version_detail(mv))

    def create(self, request):
        # New DRAFT. Caller supplies description / author / etc.;
        # version auto-bumps to max+1.
        data = request.data
        next_v = (
            PMTModelVersion.objects.order_by("-version").first()
        )
        mv = PMTModelVersion.objects.create(
            version=(next_v.version + 1) if next_v else 1,
            status="draft",
            description=data.get("description", ""),
            author=data.get("author") or request.user.username,
            variables=data.get("variables", []),
            intercept=data.get("intercept", 0),
            band_cutoffs=data.get("band_cutoffs", {}),
            band_strategy=data.get("band_strategy", "threshold"),
            calibration_dataset=data.get("calibration_dataset", ""),
            calibration_year_end=data.get("calibration_year_end"),
        )
        return Response(_version_detail(mv), status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        mv = PMTModelVersion.objects.get(pk=pk)
        if mv.status != "draft":
            return Response({
                "detail": "Model is not draft — clone it to edit.",
            }, status=status.HTTP_409_CONFLICT)
        for field in (
            "description", "variables", "intercept",
            "band_cutoffs", "band_strategy",
            "calibration_dataset", "calibration_year_end",
        ):
            if field in request.data:
                setattr(mv, field, request.data[field])
        mv.save()
        return Response(_version_detail(mv))

    @action(detail=True, methods=["post"], url_path="clone")
    def clone(self, request, pk=None):
        src = PMTModelVersion.objects.get(pk=pk)
        next_v = PMTModelVersion.objects.order_by("-version").first()
        new = PMTModelVersion.objects.create(
            version=(next_v.version + 1) if next_v else 1,
            status="draft",
            description=(
                f"Clone of v{src.version}: {src.description or ''}".strip(": ")
            )[:1000],
            author=request.user.username or "admin",
            variables=list(src.variables or []),
            intercept=src.intercept,
            band_cutoffs=dict(src.band_cutoffs or {}),
            band_strategy=src.band_strategy or "threshold",
            calibration_dataset=src.calibration_dataset,
            calibration_year_end=src.calibration_year_end,
        )
        return Response(_version_detail(new), status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="submit")
    def submit(self, request, pk=None):
        from apps.pmt.services import (
            PMTApprovalError,
            submit_for_approval,
        )
        mv = PMTModelVersion.objects.get(pk=pk)
        try:
            submit_for_approval(
                mv,
                actor=request.user.username or "admin",
                mglsd_steward_email=request.data.get("mglsd_steward_email", ""),
                ubos_dg_email=request.data.get("ubos_dg_email", ""),
                author_email=request.data.get("author_email") or mv.author,
            )
        except PMTApprovalError as exc:
            return Response({"detail": str(exc)},
                            status=status.HTTP_400_BAD_REQUEST)
        mv.refresh_from_db()
        return Response(_version_detail(mv))

    @action(detail=True, methods=["post"], url_path=r"sign/(?P<step>[1-3])")
    def sign(self, request, pk=None, step=None):
        from apps.pmt.services import PMTApprovalError, sign_step
        mv = PMTModelVersion.objects.get(pk=pk)
        try:
            sign_step(
                mv, int(step),
                actor_email=request.data.get("actor_email", ""),
                note=request.data.get("note", ""),
            )
        except PMTApprovalError as exc:
            return Response({"detail": str(exc)},
                            status=status.HTTP_400_BAD_REQUEST)
        mv.refresh_from_db()
        return Response(_version_detail(mv))

    @action(detail=True, methods=["post"], url_path=r"reject/(?P<step>[1-3])")
    def reject(self, request, pk=None, step=None):
        from apps.pmt.services import PMTApprovalError, reject_step
        mv = PMTModelVersion.objects.get(pk=pk)
        try:
            reject_step(
                mv, int(step),
                actor_email=request.data.get("actor_email", ""),
                reason=request.data.get("reason", ""),
            )
        except PMTApprovalError as exc:
            return Response({"detail": str(exc)},
                            status=status.HTTP_400_BAD_REQUEST)
        mv.refresh_from_db()
        return Response(_version_detail(mv))

    @action(detail=True, methods=["post"], url_path="simulate")
    def simulate(self, request, pk=None):
        """Score simulator — runs compute_pmt against an arbitrary
        feature dict. No PMTResult row written, no audit event for
        the simulation itself (would flood the chain — HANDOFF §4.4)."""
        from apps.pmt.feature_evaluator import evaluate_feature
        mv = PMTModelVersion.objects.get(pk=pk)
        try:
            features = request.data.get("features") or {}
        except (TypeError, AttributeError):
            return Response({"detail": "features must be an object"},
                            status=status.HTTP_400_BAD_REQUEST)
        score = float(mv.intercept or 0)
        contributions = []
        for var in (mv.variables or []):
            weight = float(var.get("weight", 0))
            name = var.get("name") or var.get("variable") or ""
            feat = var.get("feature")
            if isinstance(feat, dict):
                try:
                    value = evaluate_feature(feat, features)
                except Exception as exc:  # noqa: BLE001
                    contributions.append({
                        "name": name, "value": 0, "weight": weight,
                        "contribution": 0, "error": str(exc),
                    })
                    continue
            else:
                # Legacy {variable, weight} shape — direct path read.
                from apps.pmt.feature_evaluator import resolve_path
                raw = resolve_path(features, var.get("variable", ""))
                try:
                    value = float(raw) if raw is not None else 0.0
                except (TypeError, ValueError):
                    value = 0.0
            contribution = weight * value
            score += contribution
            contributions.append({
                "name": name, "value": value, "weight": weight,
                "contribution": contribution,
            })
        # Top 5 by absolute contribution
        top5 = sorted(
            contributions, key=lambda c: -abs(c.get("contribution", 0)),
        )[:5]
        return Response({
            "score": score,
            "intercept": float(mv.intercept or 0),
            "contributing_variables": top5,
            "all_variables": contributions,
        })


def _version_summary(mv: PMTModelVersion) -> dict:
    return {
        "id": str(mv.id),
        "version": mv.version,
        "status": mv.status,
        "author": mv.author,
        "approved_by": mv.approved_by,
        "approved_at": mv.approved_at.isoformat() if mv.approved_at else "",
        "validation_r_squared":
            float(mv.validation_r_squared) if mv.validation_r_squared else None,
        "calibration_year_end": mv.calibration_year_end,
        "variables_count": len(mv.variables or []),
        "created_at": mv.created_at.isoformat(),
    }


def _version_detail(mv: PMTModelVersion) -> dict:
    signoffs = [
        {
            "id": str(s.id),
            "revision": s.revision,
            "step": s.step,
            "expected_role": s.expected_role,
            "expected_email": s.expected_email,
            "actual_email": s.actual_email,
            "status": s.status,
            "decided_at": s.decided_at.isoformat() if s.decided_at else "",
            "decision_note": s.decision_note,
        }
        for s in (
            PMTModelSignOff.objects
            .filter(model_version=mv, revision=mv.version)
            .order_by("step")
        )
    ]
    return {
        **_version_summary(mv),
        "description": mv.description,
        "intercept": float(mv.intercept) if mv.intercept is not None else 0,
        "band_strategy": mv.band_strategy,
        "band_cutoffs": mv.band_cutoffs or {},
        "calibration_dataset": mv.calibration_dataset,
        "variables": mv.variables or [],
        "signoffs": signoffs,
    }


@extend_schema(
    tags=["admin-console"],
    summary="List registered feature transforms (for the Configuration editor)",
)
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated, IsAdminConsoleUser])
def pmt_transforms(request):
    """Surface the @register'd feature function names for the
    Configuration screen's dropdown."""
    from apps.pmt.registry import registered_names
    return Response({
        "registered_functions": registered_names(),
        "dsl_types": [
            "direct", "equality", "inequality", "membership",
            "comparison", "ratio", "count_where", "share_where",
            "presence_in_collection", "aggregate_any",
            "registered_function",
        ],
    })


@extend_schema(
    tags=["admin-console"],
    summary="Paginated PMT-scoped AuditEvent feed",
)
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated, IsAdminConsoleUser])
def pmt_events(request):
    cursor = request.query_params.get("cursor")
    qs = AuditEvent.objects.filter(entity_type__in=[
        "pmt_model_version", "pmt_result", "pmt_band_threshold",
    ]).order_by("-occurred_at")
    if cursor:
        qs = qs.filter(occurred_at__lt=cursor)
    rows = list(qs[:50])
    return Response({
        "items": [
            {
                "id": str(e.id),
                "actor": e.actor_id,
                "action": e.action,
                "entity_type": e.entity_type,
                "entity_id": e.entity_id,
                "occurred_at": e.occurred_at.isoformat(),
                "reason": e.reason or "",
            }
            for e in rows
        ],
        "next_cursor": rows[-1].occurred_at.isoformat() if rows else None,
    })
