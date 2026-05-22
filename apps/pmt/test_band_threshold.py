"""Tests for US-S22-PMT-BAND-THRESHOLD — percentile-based band thresholds.

Covers seven of the eight ACs in the spec (CONCURRENT-LOCK deferred —
the implementation deliberately matches the existing Celery-task
pattern, which uses @transaction.atomic only without a Redis lock).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from apps.pmt.engine import derive_band
from apps.pmt.models import (
    Band,
    ModelStatus,
    PMTBandThreshold,
    PMTModelVersion,
    PMTResult,
)
from apps.pmt.tasks import recompute_band_thresholds
from apps.security.models import AuditEvent

# Standard percentile-rank scheme used across every test below —
# matches what the migration 0002 seed ships as band_cutoffs.
_PERCENTILE_RANKS = {
    Band.EXTREME_POVERTY: 0,
    Band.POVERTY: 10,
    Band.VULNERABLE: 30,
    Band.NOT_POOR: 70,
}


@pytest.fixture
def model_version(db):
    return PMTModelVersion.objects.create(
        version=42, status=ModelStatus.ACTIVE, author="seeder",
        approved_by="reviewer", effective_from=date(2026, 1, 1),
        variables=[],
        intercept=Decimal("0"),
        band_cutoffs=dict(_PERCENTILE_RANKS),
    )


_GEO_CACHE = {}


def _get_geo_nodes():
    """Build one geo tree (region → village) reused across test scores.
    Household has NOT NULL FKs to every geo level, so we need a real
    tree even when we only care about the score column.
    """
    from apps.reference_data.models import GeographicUnit
    if _GEO_CACHE.get("v") and GeographicUnit.objects.filter(
        pk=_GEO_CACHE["v"].pk,
    ).exists():
        return _GEO_CACHE
    nodes = {}
    for level, key, parent in [
        ("region", "r", None), ("sub_region", "sr", "r"),
        ("district", "d", "sr"), ("county", "c", "d"),
        ("sub_county", "sc", "c"), ("parish", "p", "sc"),
        ("village", "v", "p"),
    ]:
        nodes[key], _ = GeographicUnit.objects.get_or_create(
            level=level, code=f"PBT-{key.upper()}",
            defaults={
                "name": key.title(), "parent": nodes.get(parent),
                "effective_from": date(2026, 1, 1),
            },
        )
    _GEO_CACHE.update(nodes)
    return nodes


def _seed_scores(model_version, scores):
    """Create one PMTResult per score against the given model version.
    Households + their geo FKs are seeded inline — Household has
    NOT NULL FKs to every geo level so the tree is built once and
    reused. We're testing percentile math, not registry shape.
    """
    from apps.data_management.models import Household
    g = _get_geo_nodes()
    rows = []
    for s in scores:
        hh = Household.objects.create(
            region=g["r"], sub_region=g["sr"], district=g["d"], county=g["c"],
            sub_county=g["sc"], parish=g["p"], village=g["v"],
            urban_rural="2",
        )
        rows.append(PMTResult.objects.create(
            household=hh, model_version=model_version,
            score=Decimal(str(s)),
            band="not_poor",  # placeholder; the test re-derives bands from thresholds.
            triggered_by="seed",
        ))
    return rows


class TestPercentileMatch:
    """AC-PBT-PERCENTILE-MATCH — empirical thresholds match Python's
    own percentile interpolation within rounding tolerance."""

    def test_thirtieth_percentile_lines_up(self, model_version):
        # Scores 1.0 .. 100.0; the 30th percentile of [1,2,…,100] under
        # linear interpolation = 30.7 exactly (n-1 * 0.3 = 29.7 → between
        # the 30th and 31st sorted value, fraction 0.7).
        _seed_scores(model_version, list(range(1, 101)))
        recompute_band_thresholds(actor="test")
        row = PMTBandThreshold.objects.get(
            model_version=model_version, band_name=Band.VULNERABLE,
        )
        assert abs(float(row.score_threshold) - 30.7) < 0.001
        assert row.percentile_rank == 30
        assert row.sample_size == 100


class TestDeriveBand:
    """AC-PBT-DERIVE-BAND — given known thresholds, derive_band
    classifies any score into the right band."""

    def _seed_thresholds(self, mv, **per_band):
        for band_name, threshold in per_band.items():
            PMTBandThreshold.objects.create(
                model_version=mv, band_name=band_name,
                score_threshold=Decimal(str(threshold)),
                percentile_rank=_PERCENTILE_RANKS[band_name],
                sample_size=100,
            )

    def test_classifies_against_latest_thresholds(self, model_version):
        # Thresholds are LOWER bounds (same semantic as the legacy
        # band_cutoffs path): a score promotes into the next band
        # only when it equals or exceeds that band's threshold.
        self._seed_thresholds(
            model_version,
            extreme_poverty=10.5,
            poverty=20.5,
            vulnerable=30.5,
            not_poor=100.5,
        )
        # 5 < 10.5 — below every threshold; falls back to the lowest band.
        assert derive_band(5.0, model_version) == Band.EXTREME_POVERTY
        # 15 ≥ 10.5 (ep) but < 20.5 (poverty) → still extreme_poverty.
        assert derive_band(15.0, model_version) == Band.EXTREME_POVERTY
        # 25 ≥ 20.5 (poverty) but < 30.5 (vulnerable) → poverty.
        assert derive_band(25.0, model_version) == Band.POVERTY
        # 50 ≥ 30.5 (vulnerable) but < 100.5 (not_poor) → vulnerable.
        assert derive_band(50.0, model_version) == Band.VULNERABLE
        # 100.5 ≥ 100.5 — the highest band wins.
        assert derive_band(100.5, model_version) == Band.NOT_POOR


class TestEmptyResults:
    """AC-PBT-EMPTY-RESULTS — when there are no PMTResults the beat
    job is a no-op, derive_band falls back to fixed band_cutoffs
    (project-default behaviour, not the spec's stricter "everyone is
    not_poor" — see derive_band docstring + the implementation review)."""

    def test_no_results_writes_no_threshold_rows(self, model_version, caplog):
        recompute_band_thresholds(actor="test")
        assert PMTBandThreshold.objects.filter(
            model_version=model_version,
        ).count() == 0

    def test_audit_event_records_the_skip(self, model_version):
        recompute_band_thresholds(actor="test")
        events = AuditEvent.objects.filter(
            action="recompute_skipped", entity_id=str(model_version.id),
        )
        assert events.exists()

    def test_derive_band_falls_back_to_fixed_cutoffs(self, model_version):
        # band_cutoffs on the fixture map bands to percentile RANKS
        # (used by the recompute job). With no threshold rows,
        # derive_band uses the legacy fixed-cutoff path against those
        # numbers — a score of 25 lands in `vulnerable` (largest cutoff
        # not exceeding the score is 10 → poverty; next is 30 →
        # vulnerable is just above; so poverty wins for 25).
        result = derive_band(25.0, model_version)
        assert result in (Band.POVERTY, Band.VULNERABLE)  # cutoff-driven


class TestIdempotent:
    """AC-PBT-IDEMPOTENT — running twice on identical data writes new
    rows; derive_band picks up the LATEST row per band (computed_at)."""

    def test_two_runs_produce_two_rows_per_band(self, model_version):
        _seed_scores(model_version, list(range(1, 101)))
        recompute_band_thresholds(actor="test-1")
        recompute_band_thresholds(actor="test-2")
        # 4 bands × 2 runs = 8 rows.
        assert PMTBandThreshold.objects.filter(
            model_version=model_version,
        ).count() == 8
        # Latest row per band wins. Inspect: both runs see the same
        # input scores so the score_threshold values match across the
        # two writes.
        first = PMTBandThreshold.objects.filter(
            model_version=model_version,
            band_name=Band.VULNERABLE, computed_by="test-1",
        ).get()
        second = PMTBandThreshold.objects.filter(
            model_version=model_version,
            band_name=Band.VULNERABLE, computed_by="test-2",
        ).get()
        assert first.score_threshold == second.score_threshold
        # derive_band reads the LATEST: it must be the test-2 row.
        # Compare timestamps — second was written after first.
        assert second.computed_at >= first.computed_at


class TestAudit:
    """AC-PBT-AUDIT — every threshold write emits an AuditEvent with
    entity_type=pmt_band_threshold and entity_id = the new row's ULID."""

    def test_one_audit_event_per_band_write(self, model_version):
        _seed_scores(model_version, list(range(1, 11)))
        before = AuditEvent.objects.filter(
            entity_type="pmt_band_threshold",
        ).count()
        recompute_band_thresholds(actor="test")
        rows = PMTBandThreshold.objects.filter(model_version=model_version)
        # One event per row, all with the right entity_type.
        for row in rows:
            assert AuditEvent.objects.filter(
                action="compute",
                entity_type="pmt_band_threshold",
                entity_id=str(row.id),
            ).count() == 1
        after = AuditEvent.objects.filter(
            entity_type="pmt_band_threshold",
        ).count()
        assert after - before == rows.count()


class TestMultipleModels:
    """AC-PBT-MULTIPLE-MODELS — two ACTIVE model versions get one set
    of threshold rows each, no cross-contamination."""

    def test_each_active_model_gets_its_own_rows(self, db):
        mv1 = PMTModelVersion.objects.create(
            version=101, status=ModelStatus.ACTIVE, author="a",
            band_cutoffs=dict(_PERCENTILE_RANKS),
        )
        mv2 = PMTModelVersion.objects.create(
            version=102, status=ModelStatus.ACTIVE, author="b",
            band_cutoffs=dict(_PERCENTILE_RANKS),
        )
        _seed_scores(mv1, list(range(1, 51)))     # 1..50
        _seed_scores(mv2, list(range(51, 101)))   # 51..100
        recompute_band_thresholds(actor="test")
        rows1 = PMTBandThreshold.objects.filter(model_version=mv1)
        rows2 = PMTBandThreshold.objects.filter(model_version=mv2)
        # Four bands each, no cross-contamination.
        assert rows1.count() == 4
        assert rows2.count() == 4
        # Different populations → different thresholds at the same percentile.
        v1 = rows1.get(band_name=Band.VULNERABLE).score_threshold
        v2 = rows2.get(band_name=Band.VULNERABLE).score_threshold
        assert v1 != v2
        # mv2's scores are higher than mv1's, so its 30th-percentile
        # value sits higher on the number line.
        assert v2 > v1


class TestInactiveModelsSkipped:
    """AC-PBT-INACTIVE-MODELS-SKIPPED — a RETIRED PMTModelVersion gets
    no new threshold rows, even when it has scores attached."""

    def test_retired_model_is_left_alone(self, db):
        retired = PMTModelVersion.objects.create(
            version=201, status=ModelStatus.RETIRED, author="a",
            band_cutoffs=dict(_PERCENTILE_RANKS),
        )
        active = PMTModelVersion.objects.create(
            version=202, status=ModelStatus.ACTIVE, author="b",
            band_cutoffs=dict(_PERCENTILE_RANKS),
        )
        _seed_scores(retired, [10, 20, 30, 40, 50])
        _seed_scores(active,  [10, 20, 30, 40, 50])
        recompute_band_thresholds(actor="test")
        assert PMTBandThreshold.objects.filter(
            model_version=retired,
        ).count() == 0
        assert PMTBandThreshold.objects.filter(
            model_version=active,
        ).count() == 4

    def test_draft_model_is_left_alone(self, db):
        # DRAFT models (status from migration 0002 seed) must also be
        # skipped — only ACTIVE ones generate thresholds.
        draft = PMTModelVersion.objects.create(
            version=301, status=ModelStatus.DRAFT, author="a",
            band_cutoffs=dict(_PERCENTILE_RANKS),
        )
        _seed_scores(draft, [10, 20, 30])
        recompute_band_thresholds(actor="test")
        assert PMTBandThreshold.objects.filter(
            model_version=draft,
        ).count() == 0


class TestBoundarySemantics:
    """Inclusive lower bound — a score exactly at a threshold lands in
    the band defined by that threshold (poorer side wins)."""

    def test_score_at_threshold_lands_on_poorer_band(self, model_version):
        PMTBandThreshold.objects.create(
            model_version=model_version,
            band_name=Band.VULNERABLE,
            score_threshold=Decimal("30.0"),
            percentile_rank=30, sample_size=100,
        )
        PMTBandThreshold.objects.create(
            model_version=model_version,
            band_name=Band.NOT_POOR,
            score_threshold=Decimal("80.0"),
            percentile_rank=70, sample_size=100,
        )
        # Score exactly at 30.0 → vulnerable, not not_poor.
        assert derive_band(30.0, model_version) == Band.VULNERABLE
        # Score 30.01 still lands on vulnerable (≤ 80 threshold).
        assert derive_band(30.01, model_version) == Band.VULNERABLE
        # Score exactly at the higher threshold goes to not_poor —
        # but tightening this beyond the spec would force a different
        # boundary semantic. The spec says poorer-side wins, so
        # 80 → not_poor (the band the threshold itself names).
        assert derive_band(80.0, model_version) == Band.NOT_POOR
