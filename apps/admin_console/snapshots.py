"""Recompute the PMT dashboard snapshot tables.

Called from the "Run now" admin button + the nightly Celery beat
job (`recompute_dashboard_snapshots_task` — wiring deferred until
the beat schedule lands). One PMTRecomputeJobRun row per execution
so the dashboard's recent-runs table is queryable.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.pmt.models import (
    PMTBandSnapshot,
    PMTCoverageSnapshot,
    PMTModelVersion,
    PMTRecomputeJobRun,
    PMTResult,
    PMTSubregionSnapshot,
    PMTVariableInfluence,
)


@transaction.atomic
def recompute_dashboard_snapshots(actor: str = "celery-beat") -> PMTRecomputeJobRun:
    """Re-materialise every PMT dashboard snapshot table from the
    current PMTResult / Household population. Returns the
    PMTRecomputeJobRun row recording the execution."""
    run = PMTRecomputeJobRun.objects.create(actor=actor, status="ok")
    rows_written = 0
    sample_size = 0
    try:
        # Band distribution (active model only — the dashboard view
        # focuses on what's currently in production).
        active = PMTModelVersion.objects.filter(status="active").first()
        if active is not None:
            band_rows = (
                PMTResult.objects
                .filter(model_version=active)
                .values("band")
                .annotate(c=Count("*"))
            )
            total = sum(r["c"] for r in band_rows) or 1
            sample_size = total
            for r in band_rows:
                PMTBandSnapshot.objects.create(
                    model_version=active,
                    band=r["band"], count=r["c"],
                    pct=Decimal(str(round(r["c"] * 100 / total, 2))),
                )
                rows_written += 1
            rows_written += _refresh_subregion_snapshots(active)
            rows_written += _refresh_variable_influence(active)
        rows_written += _refresh_coverage_snapshot()
    except Exception as exc:  # noqa: BLE001
        run.status = PMTRecomputeJobRun.FAILED
        run.note = str(exc)[:1000]
    run.finished_at = timezone.now()
    run.rows_written = rows_written
    run.sample_size = sample_size
    run.save()
    return run


def _refresh_subregion_snapshots(active: PMTModelVersion) -> int:
    """Snapshot per-sub-region poverty rates. Joins PMTResult ↔
    Household.sub_region_code (the denormalised partition key — no
    geographic-unit table join required)."""
    from apps.data_management.models import Household

    written = 0
    # Households by sub-region.
    hh_by_sr = dict(
        Household.objects.filter(is_deleted=False)
        .values("sub_region_code")
        .annotate(c=Count("*"))
        .values_list("sub_region_code", "c"),
    )
    # PMTResult join — count of scored + in-poverty households per
    # sub-region. The "latest result per household" projection runs
    # via a subquery; for snapshot purposes we approximate via "any
    # active-model result counts once per household."
    scored_qs = (
        PMTResult.objects
        .filter(model_version=active)
        .values("household__sub_region_code")
        .annotate(
            scored=Count("household_id", distinct=True),
            poor=Count(
                "household_id",
                filter=Q(band__in=["extreme_poverty", "poverty"]),
                distinct=True,
            ),
        )
    )
    for r in scored_qs:
        sr_code = r["household__sub_region_code"] or ""
        total = hh_by_sr.get(sr_code, 0)
        rate = Decimal("0")
        if r["scored"] > 0:
            rate = Decimal(str(round(r["poor"] * 100.0 / r["scored"], 2)))
        PMTSubregionSnapshot.objects.create(
            model_version=active,
            sub_region_code=sr_code,
            sub_region_name="",  # populated from reference_data in a follow-up
            total_households=total,
            scored_households=r["scored"],
            in_poverty_count=r["poor"],
            poverty_rate=rate,
        )
        written += 1
    return written


def _refresh_variable_influence(active: PMTModelVersion) -> int:
    """Capture per-variable influence = |weight| × sample_mean. For
    DRAFT placeholders with weight 0 the influence is 0; the
    dashboard still lists them so the analyst sees the surface."""
    written = 0
    # Pull the per-variable means from the latest PMTResult.inputs_snapshot.
    # Inputs_snapshot is a dict keyed by variable name (DSL) or by path
    # (legacy). Average each variable's "value" / "transformed" /
    # "contribution" across the snapshot. For active models with no
    # results yet, sample_mean stays 0.
    means: dict[str, float] = {}
    counts: dict[str, int] = {}
    for r in PMTResult.objects.filter(model_version=active).values("inputs_snapshot"):
        snap = r["inputs_snapshot"] or {}
        for name, entry in snap.items():
            if not isinstance(entry, dict):
                continue
            v = entry.get("value")
            if v is None:
                v = entry.get("transformed")
            if v is None:
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            means[name] = means.get(name, 0.0) + fv
            counts[name] = counts.get(name, 0) + 1
    for var in (active.variables or []):
        weight = float(var.get("weight", 0))
        name = var.get("name") or var.get("variable") or ""
        n = counts.get(name, 0)
        avg = means.get(name, 0.0) / n if n else 0.0
        PMTVariableInfluence.objects.create(
            model_version=active,
            variable_name=name,
            weight=Decimal(str(weight)),
            sample_mean=Decimal(str(round(avg, 4))),
            influence=Decimal(str(round(abs(weight) * abs(avg), 4))),
        )
        written += 1
    return written


def _refresh_coverage_snapshot() -> int:
    """Registry-wide coverage tile data."""
    from apps.data_management.models import Household

    now = timezone.now()
    total = Household.objects.filter(is_deleted=False).count()
    scored_30d = (
        PMTResult.objects
        .filter(computed_at__gte=now - timedelta(days=30))
        .values_list("household_id", flat=True).distinct().count()
    )
    scored_90d = (
        PMTResult.objects
        .filter(computed_at__gte=now - timedelta(days=90))
        .values_list("household_id", flat=True).distinct().count()
    )
    scored = (
        PMTResult.objects.values_list("household_id", flat=True).distinct().count()
    )
    stale_12mo = total - (
        PMTResult.objects
        .filter(computed_at__gte=now - timedelta(days=365))
        .values_list("household_id", flat=True).distinct().count()
    )
    PMTCoverageSnapshot.objects.create(
        total_households=total, scored=scored,
        scored_30d=scored_30d, scored_90d=scored_90d,
        stale_12mo=max(0, stale_12mo),
    )
    return 1
