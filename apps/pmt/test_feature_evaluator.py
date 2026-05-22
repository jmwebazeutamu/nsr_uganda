"""PMT feature DSL evaluator tests (ADR-0025).

One test per `type` handler + the path resolver + the filter mini-
language. The evaluator is pure (no DB) so these are unit tests that
run without django_db.
"""

from __future__ import annotations

import pytest

from apps.pmt.feature_evaluator import (
    FeatureEvaluationError,
    _row_passes,
    evaluate_feature,
    resolve_path,
    validate_feature,
)


class _Obj:
    """Tiny attribute-bag for path-resolution tests."""

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


# ───────────────────────────────────────────────────────────────
# Path resolution
# ───────────────────────────────────────────────────────────────

class TestResolvePath:

    def test_dict_segment(self):
        features = {"dwelling": {"floor_material": "11"}}
        assert resolve_path(features, "dwelling.floor_material") == "11"

    def test_attribute_segment(self):
        features = {"head_member": _Obj(sex="2")}
        assert resolve_path(features, "head_member.sex") == "2"

    def test_mixed_dict_attribute(self):
        features = {"head_member": _Obj(education=_Obj(highest_grade="8"))}
        assert resolve_path(features, "head_member.education.highest_grade") == "8"

    def test_missing_segment_returns_none(self):
        assert resolve_path({}, "dwelling.floor_material") is None
        assert resolve_path({"dwelling": None}, "dwelling.floor_material") is None
        assert resolve_path({"dwelling": _Obj()}, "dwelling.floor_material") is None

    def test_empty_or_none_path(self):
        assert resolve_path({"x": 1}, "") is None
        assert resolve_path({"x": 1}, None) is None


# ───────────────────────────────────────────────────────────────
# direct
# ───────────────────────────────────────────────────────────────

class TestDirect:

    def test_returns_raw_value_as_float(self):
        feature = {"type": "direct", "path": "member_count"}
        assert evaluate_feature(feature, {"member_count": 7}) == 7.0

    def test_missing_path_returns_zero(self):
        feature = {"type": "direct", "path": "member_count"}
        assert evaluate_feature(feature, {}) == 0.0


# ───────────────────────────────────────────────────────────────
# equality / inequality
# ───────────────────────────────────────────────────────────────

class TestEquality:

    def test_match_returns_one(self):
        feature = {"type": "equality", "path": "head_member.sex", "operand": "2"}
        features = {"head_member": _Obj(sex="2")}
        assert evaluate_feature(feature, features) == 1.0

    def test_mismatch_returns_zero(self):
        feature = {"type": "equality", "path": "head_member.sex", "operand": "2"}
        features = {"head_member": _Obj(sex="1")}
        assert evaluate_feature(feature, features) == 0.0

    def test_loose_equality_handles_int_vs_string(self):
        # ChoiceList codes sometimes round-trip as ints in tests.
        feature = {"type": "equality", "path": "n", "operand": "7"}
        assert evaluate_feature(feature, {"n": 7}) == 1.0


class TestInequality:

    def test_non_match_returns_one(self):
        feature = {"type": "inequality", "path": "dwelling.tenure", "operand": "11"}
        features = {"dwelling": _Obj(tenure="12")}
        assert evaluate_feature(feature, features) == 1.0

    def test_missing_value_returns_zero(self):
        # `actual is None` short-circuits — a missing value isn't
        # "not equal", it's unknown, so contribution stays 0.
        feature = {"type": "inequality", "path": "dwelling.tenure", "operand": "11"}
        assert evaluate_feature(feature, {}) == 0.0


# ───────────────────────────────────────────────────────────────
# membership
# ───────────────────────────────────────────────────────────────

class TestMembership:

    def test_in_list(self):
        feature = {
            "type": "membership",
            "path": "head_member.education.highest_grade",
            "operand": ["8", "17", "18"],
        }
        features = {"head_member": _Obj(education=_Obj(highest_grade="8"))}
        assert evaluate_feature(feature, features) == 1.0

    def test_not_in_list(self):
        feature = {
            "type": "membership",
            "path": "head_member.education.highest_grade",
            "operand": ["8", "17", "18"],
        }
        features = {"head_member": _Obj(education=_Obj(highest_grade="4"))}
        assert evaluate_feature(feature, features) == 0.0

    def test_string_coercion(self):
        # operand stored as ints; value as string. Membership matches
        # via the str-coerced comparison.
        feature = {"type": "membership", "path": "x", "operand": [1, 2, 3]}
        assert evaluate_feature(feature, {"x": "2"}) == 1.0


# ───────────────────────────────────────────────────────────────
# comparison
# ───────────────────────────────────────────────────────────────

class TestComparison:

    @pytest.mark.parametrize("op,actual,operand,expected", [
        ("gt", 10, 5, 1.0),
        ("gt", 5, 10, 0.0),
        ("gte", 5, 5, 1.0),
        ("lt", 3, 5, 1.0),
        ("lt", 5, 5, 0.0),
        ("lte", 5, 5, 1.0),
        ("eq", 5, 5, 1.0),
        ("ne", 5, 4, 1.0),
    ])
    def test_each_operator(self, op, actual, operand, expected):
        feature = {
            "type": "comparison", "path": "x",
            "operator": op, "operand": operand,
        }
        assert evaluate_feature(feature, {"x": actual}) == expected

    def test_unknown_op_raises(self):
        feature = {
            "type": "comparison", "path": "x",
            "operator": "fubar", "operand": 1,
        }
        with pytest.raises(FeatureEvaluationError):
            evaluate_feature(feature, {"x": 1})


# ───────────────────────────────────────────────────────────────
# ratio
# ───────────────────────────────────────────────────────────────

class TestRatio:

    def test_normal_division(self):
        feature = {
            "type": "ratio",
            "numerator": "dwelling.total_rooms",
            "denominator": "member_count",
            "default": 0,
        }
        features = {
            "dwelling": _Obj(total_rooms=4),
            "member_count": 8,
        }
        assert evaluate_feature(feature, features) == 0.5

    def test_zero_denominator_returns_default(self):
        feature = {
            "type": "ratio",
            "numerator": "dwelling.total_rooms",
            "denominator": "member_count",
            "default": -1,
        }
        features = {"dwelling": _Obj(total_rooms=4), "member_count": 0}
        assert evaluate_feature(feature, features) == -1.0

    def test_missing_numerator_returns_zero(self):
        # Numerator coerces to 0 → 0/N = 0 regardless of default.
        feature = {
            "type": "ratio",
            "numerator": "dwelling.total_rooms",
            "denominator": "member_count",
            "default": 99,
        }
        assert evaluate_feature(feature, {"member_count": 4}) == 0.0


# ───────────────────────────────────────────────────────────────
# count_where / share_where (filter mini-language)
# ───────────────────────────────────────────────────────────────

class TestRowPasses:

    def test_eq_default(self):
        row = _Obj(asset_type="radio")
        assert _row_passes(row, {"asset_type": "radio"}) is True
        assert _row_passes(row, {"asset_type": "car"}) is False

    def test_in(self):
        row = _Obj(asset_type="car")
        assert _row_passes(
            row, {"asset_type__in": ["car", "minibus", "bus"]},
        ) is True
        assert _row_passes(
            row, {"asset_type__in": ["radio", "tv"]},
        ) is False

    def test_numeric_lt(self):
        row = _Obj(age_years=12)
        assert _row_passes(row, {"age_years__lt": 15}) is True
        assert _row_passes(row, {"age_years__lt": 5}) is False

    def test_multiple_clauses_anded(self):
        row = _Obj(asset_type="radio", count=2)
        assert _row_passes(
            row, {"asset_type": "radio", "count__gt": 1},
        ) is True
        assert _row_passes(
            row, {"asset_type": "radio", "count__gt": 5},
        ) is False

    def test_unknown_op_raises(self):
        row = _Obj(x=1)
        with pytest.raises(FeatureEvaluationError):
            _row_passes(row, {"x__fubar": 1})


class TestCountWhere:

    def test_counts_matching_rows(self):
        feature = {
            "type": "count_where", "collection": "members",
            "filter": {"age_years__lt": 15},
        }
        features = {"members": [
            _Obj(age_years=8), _Obj(age_years=14),
            _Obj(age_years=25), _Obj(age_years=2),
        ]}
        assert evaluate_feature(feature, features) == 3.0

    def test_empty_collection_returns_zero(self):
        feature = {
            "type": "count_where", "collection": "members",
            "filter": {"age_years__lt": 15},
        }
        assert evaluate_feature(feature, {"members": []}) == 0.0


class TestShareWhere:

    def test_returns_proportion(self):
        feature = {
            "type": "share_where", "collection": "members",
            "filter": {"age_years__lt": 15}, "default": 0,
        }
        features = {"members": [
            _Obj(age_years=8), _Obj(age_years=14),
            _Obj(age_years=25), _Obj(age_years=2),
        ]}
        assert evaluate_feature(feature, features) == 0.75

    def test_empty_collection_returns_default(self):
        feature = {
            "type": "share_where", "collection": "members",
            "filter": {"age_years__lt": 15}, "default": -1,
        }
        assert evaluate_feature(feature, {"members": []}) == -1.0


# ───────────────────────────────────────────────────────────────
# presence_in_collection
# ───────────────────────────────────────────────────────────────

class TestPresenceInCollection:

    def test_match_returns_one(self):
        feature = {
            "type": "presence_in_collection",
            "collection": "assets",
            "filter": {"asset_type__in": ["car", "minibus", "bus", "truck"]},
            "field": "count", "operator": "gt", "operand": 0,
        }
        features = {"assets": [
            _Obj(asset_type="radio", count=1),
            _Obj(asset_type="car", count=2),
        ]}
        assert evaluate_feature(feature, features) == 1.0

    def test_no_match_returns_zero(self):
        feature = {
            "type": "presence_in_collection",
            "collection": "assets",
            "filter": {"asset_type__in": ["car"]},
            "field": "count", "operator": "gt", "operand": 0,
        }
        features = {"assets": [
            _Obj(asset_type="radio", count=1),
        ]}
        assert evaluate_feature(feature, features) == 0.0

    def test_match_filter_but_field_check_fails(self):
        feature = {
            "type": "presence_in_collection",
            "collection": "assets",
            "filter": {"asset_type": "car"},
            "field": "count", "operator": "gt", "operand": 0,
        }
        features = {"assets": [
            _Obj(asset_type="car", count=0),  # has the row but count=0
        ]}
        assert evaluate_feature(feature, features) == 0.0

    def test_iterates_dict_by_type_collection(self):
        # The engine's assets shape is dict-by-type for backward
        # compat — _collection iterates dict values so the same
        # feature block works.
        feature = {
            "type": "presence_in_collection",
            "collection": "assets",
            "filter": {"asset_type": "radio"},
            "field": "count", "operator": "gt", "operand": 0,
        }
        features = {"assets": {
            "radio": _Obj(asset_type="radio", count=2),
            "car":   _Obj(asset_type="car", count=1),
        }}
        assert evaluate_feature(feature, features) == 1.0


# ───────────────────────────────────────────────────────────────
# aggregate_any
# ───────────────────────────────────────────────────────────────

class TestAggregateAny:

    def test_any_non_empty_value_returns_one(self):
        feature = {
            "type": "aggregate_any",
            "collection": "members", "path": "telephone_1",
        }
        features = {"members": [
            _Obj(telephone_1=""), _Obj(telephone_1="+256770000"),
        ]}
        assert evaluate_feature(feature, features) == 1.0

    def test_all_empty_returns_zero(self):
        feature = {
            "type": "aggregate_any",
            "collection": "members", "path": "telephone_1",
        }
        features = {"members": [
            _Obj(telephone_1=""), _Obj(telephone_1=None),
        ]}
        assert evaluate_feature(feature, features) == 0.0


# ───────────────────────────────────────────────────────────────
# registered_function
# ───────────────────────────────────────────────────────────────

class TestRegisteredFunction:

    def test_calls_registered(self):
        from apps.pmt.registry import _clear_for_tests, register
        _clear_for_tests()
        try:
            @register("test_double")
            def _double(features):
                return float(features.get("x", 0)) * 2
            feature = {"type": "registered_function", "function": "test_double"}
            assert evaluate_feature(feature, {"x": 7}) == 14.0
        finally:
            _clear_for_tests()
            # Re-import to restore production decorations.
            import importlib

            import apps.pmt.registered_features as rf
            importlib.reload(rf)

    def test_missing_function_raises(self):
        from apps.pmt.registry import _clear_for_tests
        _clear_for_tests()
        try:
            feature = {
                "type": "registered_function",
                "function": "definitely_not_here",
            }
            with pytest.raises(LookupError):
                evaluate_feature(feature, {})
        finally:
            _clear_for_tests()
            import importlib

            import apps.pmt.registered_features as rf
            importlib.reload(rf)


# ───────────────────────────────────────────────────────────────
# Dispatch + validation
# ───────────────────────────────────────────────────────────────

class TestDispatchAndValidate:

    def test_unknown_type_raises_at_eval(self):
        with pytest.raises(FeatureEvaluationError):
            evaluate_feature({"type": "make_coffee"}, {})

    def test_non_dict_feature_raises(self):
        with pytest.raises(FeatureEvaluationError):
            evaluate_feature("not a dict", {})

    def test_validate_unknown_type(self):
        errors = validate_feature({"type": "make_coffee"})
        assert any("unknown" in e for e in errors)

    def test_validate_missing_required_keys(self):
        errors = validate_feature({"type": "membership"})
        # missing path + operand
        assert any("path" in e for e in errors)
        assert any("operand" in e for e in errors)

    def test_validate_clean_feature(self):
        ok = {
            "type": "membership",
            "path": "head_member.education.highest_grade",
            "operand": ["8"],
        }
        assert validate_feature(ok) == []

    def test_validate_registered_function_missing_name(self):
        from apps.pmt.registry import _clear_for_tests
        _clear_for_tests()
        try:
            errors = validate_feature({
                "type": "registered_function",
                "function": "not_registered",
            })
            assert any("not registered" in e for e in errors)
        finally:
            _clear_for_tests()
            import importlib

            import apps.pmt.registered_features as rf
            importlib.reload(rf)
