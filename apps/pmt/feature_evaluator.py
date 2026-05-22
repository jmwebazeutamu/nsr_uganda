"""PMT feature DSL evaluator (US-S22-DE / ADR-0025).

The PMT engine no longer hardcodes variable names. Each variable on
`PMTModelVersion.variables` carries a `feature` block describing
*how* to compute its value from the household feature graph. This
module is the pure (no DB) evaluator that walks those blocks.

Supported `feature.type` values (spec §4.1):

    direct                  — raw attribute value cast to float.
    equality                — 1 if value equals operand else 0.
    inequality              — 1 if value not equal to operand else 0.
    membership              — 1 if value in operand (list) else 0.
    comparison              — 1 if value `op` operand else 0
                              (op in gt/gte/lt/lte/eq/ne).
    ratio                   — numerator / denominator, fallback `default`
                              on zero-division.
    count_where             — count of rows in `collection` passing
                              `filter` (Django-orm style key__op=val).
    share_where             — count_where / total count of the
                              collection, fallback `default` if empty.
    presence_in_collection  — 1 if any row in `collection` passes
                              `filter` AND `field` `operator` operand,
                              else 0.
    aggregate_any           — 1 if any row in `collection` has a
                              non-empty value at `path`, else 0.
    registered_function     — escape hatch: call a function decorated
                              with @apps.pmt.registry.register("name").

Path resolution walks dotted segments (`head_member.education.highest_grade`).
Each segment supports dict-key OR attribute access on the running
value. A missing segment short-circuits to None, which the numeric
coercion below maps to 0.

The evaluator is pure: callers are expected to have pre-built the
feature graph via `apps.pmt.engine._household_features` so this
module never issues a database query.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any


class FeatureEvaluationError(ValueError):
    """Raised for malformed feature blocks. The engine converts this
    into a contribution of 0 (with an audit row) rather than aborting
    the whole score — one bad variable shouldn't kill a household's
    classification."""


# ───────────────────────────────────────────────────────────────
# Path resolution + coercion
# ───────────────────────────────────────────────────────────────

def resolve_path(features: Any, path: str) -> Any:
    """Walk a dotted path against the feature graph. Returns None if
    any segment is missing. Supports dict-key OR attribute access at
    each step so the same path works against a dict-shaped feature
    record or a Django model instance."""
    if path in ("", None):
        return None
    cur = features
    for part in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            cur = getattr(cur, part, None)
    return cur


def _as_float(value: Any) -> float:
    """Coerce a value to float. None / non-numeric strings / falsy
    return 0.0 so a missing column doesn't blow up a sum."""
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _equal(a: Any, b: Any) -> bool:
    """Loose-equality helper. ChoiceList codes round-trip as strings
    ("1", "01", "11") but tests + seed data sometimes write ints —
    compare both forms to avoid spurious mismatches."""
    if a == b:
        return True
    if a is None or b is None:
        return False
    return str(a) == str(b)


# ───────────────────────────────────────────────────────────────
# Filter mini-language for collection-aware handlers
# ───────────────────────────────────────────────────────────────
#
# `filter` on count_where / share_where / presence_in_collection is a
# dict of {"field__op": value} pairs, Django-ORM style:
#
#   {"age_years__lt": 15}         → row.age_years < 15
#   {"asset_type__in": ["car"]}   → row.asset_type in ["car"]
#   {"is_deleted": False}         → equality (no __op suffix)
#
# Each row must pass EVERY filter clause (AND semantics).
# ───────────────────────────────────────────────────────────────

_OPS = {
    "eq":     lambda a, b: _equal(a, b),
    "ne":     lambda a, b: not _equal(a, b),
    "gt":     lambda a, b: _as_float(a) >  _as_float(b),
    "gte":    lambda a, b: _as_float(a) >= _as_float(b),
    "lt":     lambda a, b: _as_float(a) <  _as_float(b),
    "lte":    lambda a, b: _as_float(a) <= _as_float(b),
    "in":     lambda a, b: a in (b or []) or str(a) in [str(x) for x in (b or [])],
    "nin":    lambda a, b: a not in (b or []) and str(a) not in [str(x) for x in (b or [])],
}


def _row_passes(row: Any, criteria: dict[str, Any]) -> bool:
    """Apply a Django-ORM-style filter dict to a single row."""
    for key, expected in (criteria or {}).items():
        if "__" in key:
            field, op = key.rsplit("__", 1)
            op_fn = _OPS.get(op)
            if op_fn is None:
                raise FeatureEvaluationError(f"unknown filter op {op!r} in {key!r}")
        else:
            field, op_fn = key, _OPS["eq"]
        actual = resolve_path(row, field)
        if not op_fn(actual, expected):
            return False
    return True


def _collection(features: Any, name: str) -> list:
    """Resolve `collection` path to a list. Treats None as []."""
    raw = resolve_path(features, name)
    if raw is None:
        return []
    if isinstance(raw, dict):
        # Some legacy shapes carry collections as dicts keyed by code.
        # Iterate the values so filter/count semantics still apply.
        return list(raw.values())
    return list(raw)


# ───────────────────────────────────────────────────────────────
# Public entry point
# ───────────────────────────────────────────────────────────────

def evaluate_feature(feature: dict, features: Any) -> float:
    """Dispatch one feature block to its handler. Always returns a
    float — boolean handlers return 0.0 / 1.0; collection handlers
    return ints cast to float; missing paths return 0.0."""
    if not isinstance(feature, dict):
        raise FeatureEvaluationError(
            f"feature must be a dict, got {type(feature).__name__}",
        )
    ftype = feature.get("type")
    handler = _HANDLERS.get(ftype)
    if handler is None:
        raise FeatureEvaluationError(f"unknown feature type {ftype!r}")
    return float(handler(feature, features))


def validate_feature(feature: dict) -> list[str]:
    """Static-check a feature block. Returns a list of error strings
    (empty when valid). Used by the Rule Editor admin to refuse
    malformed JSON before it lands on an active model version."""
    errors: list[str] = []
    if not isinstance(feature, dict):
        return [f"feature must be a dict, got {type(feature).__name__}"]
    ftype = feature.get("type")
    if ftype not in _HANDLERS:
        errors.append(f"unknown feature type {ftype!r}")
        return errors
    required = _REQUIRED_KEYS.get(ftype, ())
    for k in required:
        if k not in feature:
            errors.append(f"{ftype} requires key {k!r}")
    if ftype == "comparison":
        op = feature.get("operator")
        if op not in _OPS:
            errors.append(f"comparison.operator must be one of {sorted(_OPS)}; got {op!r}")
    if ftype == "registered_function":
        # Lazy import — apps.pmt.registry is built on a Django startup
        # check that ensures every reference exists when the model
        # activates; here we just confirm the spelling exists today.
        from apps.pmt.registry import is_registered
        name = feature.get("function")
        if name and not is_registered(name):
            errors.append(
                f"registered_function {name!r} is not registered "
                f"(see apps.pmt.registered_features).",
            )
    return errors


# ───────────────────────────────────────────────────────────────
# Handler implementations
# ───────────────────────────────────────────────────────────────

def _h_direct(feature: dict, features: Any) -> float:
    return _as_float(resolve_path(features, feature.get("path", "")))


def _h_equality(feature: dict, features: Any) -> float:
    actual = resolve_path(features, feature.get("path", ""))
    return 1.0 if _equal(actual, feature.get("operand")) else 0.0


def _h_inequality(feature: dict, features: Any) -> float:
    actual = resolve_path(features, feature.get("path", ""))
    return 1.0 if (actual is not None and not _equal(actual, feature.get("operand"))) else 0.0


def _h_membership(feature: dict, features: Any) -> float:
    actual = resolve_path(features, feature.get("path", ""))
    if actual is None:
        return 0.0
    operand = feature.get("operand") or []
    operand_str = [str(x) for x in operand]
    return 1.0 if (actual in operand or str(actual) in operand_str) else 0.0


def _h_comparison(feature: dict, features: Any) -> float:
    actual = resolve_path(features, feature.get("path", ""))
    op_fn = _OPS.get(feature.get("operator", "eq"))
    if op_fn is None:
        raise FeatureEvaluationError(
            f"comparison.operator must be one of {sorted(_OPS)}",
        )
    return 1.0 if op_fn(actual, feature.get("operand")) else 0.0


def _h_ratio(feature: dict, features: Any) -> float:
    num = _as_float(resolve_path(features, feature.get("numerator", "")))
    den = _as_float(resolve_path(features, feature.get("denominator", "")))
    default = _as_float(feature.get("default", 0))
    if den == 0:
        return default
    return num / den


def _h_count_where(feature: dict, features: Any) -> float:
    rows = _collection(features, feature.get("collection", ""))
    crit = feature.get("filter") or {}
    return float(sum(1 for r in rows if _row_passes(r, crit)))


def _h_share_where(feature: dict, features: Any) -> float:
    rows = _collection(features, feature.get("collection", ""))
    if not rows:
        return _as_float(feature.get("default", 0))
    crit = feature.get("filter") or {}
    matched = sum(1 for r in rows if _row_passes(r, crit))
    return matched / len(rows)


def _h_presence_in_collection(feature: dict, features: Any) -> float:
    rows = _collection(features, feature.get("collection", ""))
    crit = feature.get("filter") or {}
    field = feature.get("field")
    operator = feature.get("operator", "gt")
    operand = feature.get("operand", 0)
    op_fn = _OPS.get(operator)
    if op_fn is None:
        raise FeatureEvaluationError(
            f"presence_in_collection.operator must be one of {sorted(_OPS)}",
        )
    for r in rows:
        if not _row_passes(r, crit):
            continue
        if field is None:
            # No extra field-level constraint — passing the filter is enough.
            return 1.0
        if op_fn(resolve_path(r, field), operand):
            return 1.0
    return 0.0


def _h_aggregate_any(feature: dict, features: Any) -> float:
    rows = _collection(features, feature.get("collection", ""))
    path = feature.get("path", "")
    for r in rows:
        v = resolve_path(r, path)
        if v not in (None, "", 0, False):
            return 1.0
    return 0.0


def _h_registered_function(feature: dict, features: Any) -> float:
    from apps.pmt.registry import call_registered
    name = feature.get("function")
    if not name:
        raise FeatureEvaluationError(
            "registered_function requires a `function` key.",
        )
    return _as_float(call_registered(name, features))


_HANDLERS = {
    "direct":                 _h_direct,
    "equality":               _h_equality,
    "inequality":             _h_inequality,
    "membership":             _h_membership,
    "comparison":             _h_comparison,
    "ratio":                  _h_ratio,
    "count_where":            _h_count_where,
    "share_where":            _h_share_where,
    "presence_in_collection": _h_presence_in_collection,
    "aggregate_any":          _h_aggregate_any,
    "registered_function":    _h_registered_function,
}

_REQUIRED_KEYS = {
    "direct":                 ("path",),
    "equality":               ("path", "operand"),
    "inequality":             ("path", "operand"),
    "membership":             ("path", "operand"),
    "comparison":             ("path", "operator", "operand"),
    "ratio":                  ("numerator", "denominator"),
    "count_where":            ("collection", "filter"),
    "share_where":            ("collection", "filter"),
    "presence_in_collection": ("collection", "filter"),
    "aggregate_any":          ("collection", "path"),
    "registered_function":    ("function",),
}
