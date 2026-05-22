"""US-S22-DE-09 — coverage for the v1 ACTIVE PMT seed (ADR-0025).

The migration writes the canonical model. These tests pin its shape
so a future schema/policy change can't silently drop a variable or
break the AC-DE-PMT-COEFFICIENTS-ACTIVE acceptance criterion.
"""

from __future__ import annotations

import pytest

from apps.pmt.feature_evaluator import validate_feature
from apps.pmt.models import PMTModelVersion


@pytest.mark.django_db
class TestV1ActiveSeed:

    def test_v1_exists_and_is_active(self):
        mv = PMTModelVersion.objects.get(version=1)
        assert mv.status == "active"
        assert mv.author == "system"
        assert mv.approved_by == "system"

    def test_v1_calibration_provenance(self):
        mv = PMTModelVersion.objects.get(version=1)
        assert float(mv.intercept) == pytest.approx(13.973)
        assert float(mv.validation_r_squared) == pytest.approx(0.551)
        assert mv.calibration_dataset == "UNHS 2023/24"
        assert mv.calibration_year_end == 2024
        assert mv.band_strategy == "percentile"

    def test_v1_has_25_variables(self):
        mv = PMTModelVersion.objects.get(version=1)
        assert len(mv.variables) == 25, (
            f"v1 must have 25 variables per spec §4.5 (got {len(mv.variables)})"
        )

    def test_v1_band_cutoffs_are_percentile_ranks(self):
        mv = PMTModelVersion.objects.get(version=1)
        # Percentile ranks (0-100), not score thresholds.
        assert mv.band_cutoffs == {
            "extreme_poverty": 10,
            "poverty":         20,
            "vulnerable":      30,
            "not_poor":        100,
        }

    def test_every_variable_has_a_dsl_feature_block(self):
        mv = PMTModelVersion.objects.get(version=1)
        for var in mv.variables:
            assert "feature" in var, (
                f"variable {var.get('name')} missing DSL feature block"
            )
            assert isinstance(var["feature"], dict)

    def test_every_variable_validates_clean(self):
        mv = PMTModelVersion.objects.get(version=1)
        for var in mv.variables:
            errors = validate_feature(var["feature"])
            assert errors == [], (
                f"variable {var['name']} has validation errors: {errors}"
            )

    def test_v1_uses_every_dsl_handler_we_advertise(self):
        # Sanity-check spec §4.5 — the seeded variables exercise at
        # least the headline DSL handlers. If a future edit drops one,
        # this test flags that drift.
        mv = PMTModelVersion.objects.get(version=1)
        types_used = {v["feature"]["type"] for v in mv.variables}
        assert {
            "direct", "equality", "inequality", "membership",
            "ratio", "share_where", "presence_in_collection",
            "aggregate_any",
        }.issubset(types_used)

    def test_ac_de_pmt_features_dsl_no_hardcoded_names_in_engine(self):
        # AC-DE-PMT-FEATURES-DSL — grep the engine for any policy-
        # specific variable name (head_is_female / owns_television /
        # rooms_per_capita / etc.) and assert zero matches. Some
        # variable names overlap with legitimate feature-graph keys
        # the engine produces (`member_count`, `dependency_ratio`);
        # those are *not* hardcoded policy — they're pre-computed
        # scalars that any active model can reference. Skip those by
        # name.
        from pathlib import Path
        engine_src = Path(__file__).resolve().parent / "engine.py"
        text = engine_src.read_text()
        # Names the engine intentionally surfaces in the feature
        # graph. Anything else is a policy variable that MUST live
        # only in PMTModelVersion.variables (ADR-0025).
        graph_keys = {
            "member_count", "disabled_member_count",
            "chronic_ill_member_count", "school_age_out_of_school_count",
            "dependency_ratio",
        }
        mv = PMTModelVersion.objects.get(version=1)
        for var in mv.variables:
            if var["name"] in graph_keys:
                continue
            assert var["name"] not in text, (
                f"AC-DE-PMT-FEATURES-DSL: engine.py contains "
                f"variable name {var['name']!r} — variable names "
                f"must live only in PMTModelVersion.variables."
            )
