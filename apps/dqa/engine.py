"""DAT-DQA in-process Python rules engine.

SAD §4.2.1 picks Python-evaluated JSON-DSL over Drools. The DSL has two
node shapes:

    leaf node:     {"field": "<path>", "op": "<name>", "value": <any>}
    composite:     {"all_of": [<node>, ...]} | {"any_of": [<node>, ...]}

Field paths walk the record dict (`address.street`) or use attribute
access when the record is a Django model instance. The full operator
set per SAD §4.2.3:

    not_null, is_null, eq, neq, in, not_in, regex, gt, lt, ge, le,
    between, accuracy_le, count_eq, count_neq, cross_field_eq,
    references_existing, within_polygon

`cross_field_eq` is a special leaf shape that takes `left_field` and
`right_field` in place of the usual single `field` — used for
within-record cross-checks. Unknown operators raise DSLError.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .models import DqaResult, DqaRule, RuleStatus


class DSLError(Exception):
    """The rule expression is malformed."""


# --- Operator registry -----------------------------------------------------

OPERATORS: dict[str, Callable[[Any, Any], bool]] = {}


def _op(name: str):
    def deco(f: Callable[[Any, Any], bool]):
        OPERATORS[name] = f
        return f
    return deco


@_op("not_null")
def _op_not_null(field_value, _value):
    return field_value is not None and field_value != "" and field_value != b""


@_op("is_null")
def _op_is_null(field_value, _value):
    return field_value is None or field_value == "" or field_value == b""


@_op("eq")
def _op_eq(field_value, value):
    return field_value == value


@_op("neq")
def _op_neq(field_value, value):
    return field_value != value


@_op("regex")
def _op_regex(field_value, pattern):
    if field_value is None:
        return False
    return re.fullmatch(pattern, str(field_value)) is not None


def _numeric_pair(a, b):
    """Coerce both sides to float when one is a numeric string. Returns
    (a, b) on success or (None, None) when coercion is impossible.

    DIH staging payloads come from external sources (Kobo, partner MIS)
    that frequently emit decimals as strings; the engine must not type-
    error on those — the rule should evaluate normally."""
    if a is None:
        return None, None
    try:
        return float(a), float(b)
    except (TypeError, ValueError):
        return None, None


@_op("gt")
def _op_gt(field_value, value):
    a, b = _numeric_pair(field_value, value)
    return a is not None and a > b


@_op("lt")
def _op_lt(field_value, value):
    a, b = _numeric_pair(field_value, value)
    return a is not None and a < b


@_op("ge")
def _op_ge(field_value, value):
    a, b = _numeric_pair(field_value, value)
    return a is not None and a >= b


@_op("le")
def _op_le(field_value, value):
    a, b = _numeric_pair(field_value, value)
    return a is not None and a <= b


@_op("in")
def _op_in(field_value, values):
    return field_value in values


@_op("not_in")
def _op_not_in(field_value, values):
    return field_value not in values


@_op("between")
def _op_between(field_value, bounds):
    if field_value is None or not isinstance(bounds, (list, tuple)) or len(bounds) != 2:
        return False
    low, high = bounds
    return low <= field_value <= high


# DQA-3 / US-079 — SAD §4.2.3 operator completions ---------------------------

@_op("accuracy_le")
def _op_accuracy_le(field_value, value):
    """Explicit semantic for GPS accuracy rules.

    Behaviourally identical to `le` numerically, but a separate
    operator so the Rule Editor (US-076) can offer it specifically on
    geometry fields without ambiguity. Unlike `le`, a missing field
    here is treated as a FAIL (not a coerce-to-None silent pass) so
    that "GPS accuracy ≤ 10m" cannot be satisfied by an absent GPS
    reading; operators wanting "missing OR under N" wrap with any_of.
    """
    if field_value is None or field_value == "":
        return False
    a, b = _numeric_pair(field_value, value)
    return a is not None and a <= b


def _safe_len(field_value) -> int | None:
    """Return len(field_value) when it's list-like; else None.

    Treats strings as scalars (not lists) so {"members": "x"} doesn't
    accidentally count as len 1.
    """
    if isinstance(field_value, (list, tuple)):
        return len(field_value)
    return None


@_op("count_eq")
def _op_count_eq(field_value, value):
    n = _safe_len(field_value)
    return n is not None and n == value


@_op("count_neq")
def _op_count_neq(field_value, value):
    n = _safe_len(field_value)
    return n is not None and n != value


@_op("references_existing")
def _op_references_existing(field_value, model_label):
    """Resolve `model_label` ('app_label.ModelName') and confirm the
    field value resolves to an existing row.

    Errors (unknown model, bad app registry, malformed value) collapse
    to False — the rule should surface the data-quality failure, not
    crash the pipeline. The Rule Editor admin form validates model_
    label statically at save time so authors get an early signal.
    """
    if field_value is None or field_value == "":
        return False
    try:
        from django.apps import apps
        app_label, _, model_name = (model_label or "").partition(".")
        if not app_label or not model_name:
            return False
        model = apps.get_model(app_label, model_name)
        if model is None:
            return False
        return model.objects.filter(pk=field_value).exists()
    except Exception:
        # Lookup failed (LookupError, ValueError on bad pk type, etc.)
        # — rule reports failure; never crashes the pipeline.
        return False


_POLYGON_RE = re.compile(
    r"^\s*POLYGON\s*\(\s*\(([^()]+)\)\s*\)\s*$", re.IGNORECASE,
)
_POINT_RE = re.compile(r"^\s*POINT\s*\(\s*([^()]+)\s*\)\s*$", re.IGNORECASE)


def _parse_wkt_polygon(wkt: str) -> list[tuple[float, float]]:
    """Parse a single-ring WKT POLYGON into a list of (lng, lat) tuples.

    Raises DSLError on anything that isn't a closed simple polygon.
    NSR rules author closed boundary polygons (sub-region, parish,
    etc.); multi-polygon support is YAGNI today and would land
    alongside the first rule that needs it (per SAD §4.2.3 author
    flow).
    """
    m = _POLYGON_RE.match(wkt or "")
    if not m:
        raise DSLError(f"invalid polygon for within_polygon: {wkt!r}")
    raw_pairs = [p.strip() for p in m.group(1).split(",") if p.strip()]
    pts: list[tuple[float, float]] = []
    for pair in raw_pairs:
        bits = pair.split()
        if len(bits) != 2:
            raise DSLError(f"invalid coord in polygon: {pair!r}")
        try:
            pts.append((float(bits[0]), float(bits[1])))
        except ValueError as exc:
            raise DSLError(f"non-numeric coord: {pair!r}") from exc
    if len(pts) < 4 or pts[0] != pts[-1]:
        raise DSLError("polygon ring must be closed (≥ 3 vertices + repeat first)")
    return pts


def _point_from(field_value) -> tuple[float, float] | None:
    """Resolve a {lat, lng} dict or WKT POINT string into a (lng, lat)
    tuple. Returns None on bad input."""
    if isinstance(field_value, dict):
        lat = field_value.get("lat")
        lng = field_value.get("lng")
        if lat is None or lng is None:
            return None
        try:
            return (float(lng), float(lat))
        except (TypeError, ValueError):
            return None
    if isinstance(field_value, str):
        m = _POINT_RE.match(field_value)
        if not m:
            return None
        bits = m.group(1).split()
        if len(bits) != 2:
            return None
        try:
            return (float(bits[0]), float(bits[1]))
        except ValueError:
            return None
    return None


def _point_in_polygon(point: tuple[float, float],
                      ring: list[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon. Treats boundary as inside (matches
    PostGIS ST_Contains semantics for closed rings; deterministic at
    the vertex/edge boundary which is what rule authors expect)."""
    x, y = point
    inside = False
    n = len(ring) - 1  # ring closes on itself; iterate edges only
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if ((yi > y) != (yj > y)) and \
                (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


@_op("within_polygon")
def _op_within_polygon(field_value, polygon_wkt):
    """Field value (a point) must fall inside the polygon defined by
    `value` (a WKT polygon string).

    Implementation is pure Python (ray-casting). The DQA engine runs
    in-process per SAD §4.2.1, so pulling GEOS/GDAL into the rule
    path would couple the engine to a system-library dependency that
    has no benefit at this scale (Uganda's sub-region polygons are
    bounded by a few dozen vertices). The Rule Editor admin form
    validates polygon syntax at save time; this evaluator raises
    DSLError on malformed polygons.

    Boundary behaviour: PostGIS-compatible ST_Contains semantics —
    a point exactly on the ring is considered inside.
    """
    if field_value is None:
        return False
    ring = _parse_wkt_polygon(polygon_wkt)
    point = _point_from(field_value)
    if point is None:
        return False
    return _point_in_polygon(point, ring)


# --- Field resolution ------------------------------------------------------

_SENTINEL = object()


def get_field(record: Any, path: str) -> Any:
    """Walk a dotted path on a dict or model instance. Returns None if any
    intermediate hop is missing."""
    if not path:
        return None
    cur = record
    for part in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(part, _SENTINEL)
            if cur is _SENTINEL:
                return None
        else:
            cur = getattr(cur, part, _SENTINEL)
            if cur is _SENTINEL:
                return None
    return cur


# --- Evaluation ------------------------------------------------------------

def evaluate_expression(expression: dict, record: Any) -> bool:
    if "all_of" in expression:
        children = expression["all_of"]
        if not isinstance(children, list):
            raise DSLError("all_of expects a list")
        return all(evaluate_expression(c, record) for c in children)
    if "any_of" in expression:
        children = expression["any_of"]
        if not isinstance(children, list):
            raise DSLError("any_of expects a list")
        return any(evaluate_expression(c, record) for c in children)
    op = expression.get("op")
    if op == "cross_field_eq":
        # Special leaf shape: two fields from the same record compared
        # directly, no `value`. Surfaced as its own operator (not a
        # composite) because the Rule Editor renders it differently —
        # picking two fields from the same form, not field + literal.
        left = expression.get("left_field")
        right = expression.get("right_field")
        if not left or not right:
            raise DSLError(
                "cross_field_eq requires left_field and right_field",
            )
        return get_field(record, left) == get_field(record, right)
    field = expression.get("field")
    value = expression.get("value")
    if op not in OPERATORS:
        raise DSLError(f"unknown operator: {op!r}")
    field_value = get_field(record, field) if field else None
    return OPERATORS[op](field_value, value)


@dataclass
class Evaluation:
    """Result of evaluating a rule against a record, ready for persistence."""

    rule: DqaRule
    record_type: str
    record_id: str
    passed: bool
    reason: str

    def to_result(self) -> DqaResult:
        return DqaResult(
            rule=self.rule,
            record_type=self.record_type,
            record_id=self.record_id,
            passed=self.passed,
            severity=self.rule.severity,
            reason="" if self.passed else self.reason,
        )


def render_reason(rule: DqaRule, record: Any) -> str:
    """Format the rule's error_message_template against the record. Templates
    use Python's str.format with attribute access (e.g. '{nin_value}').
    Missing fields render as '<missing>'."""

    class _SafeMap(dict):
        def __missing__(self, key):
            return "<missing>"

    if isinstance(record, dict):
        ctx = _SafeMap(record)
    else:
        ctx = _SafeMap({
            k: getattr(record, k, "<missing>")
            for k in dir(record) if not k.startswith("_")
        })
    try:
        return rule.error_message_template.format_map(ctx)
    except (KeyError, IndexError):
        return rule.error_message_template


def evaluate(rule: DqaRule, record: Any, *, record_type: str, record_id: str) -> Evaluation:
    """Evaluate one rule. Does not write to the DB; caller persists via to_result()."""
    passed = evaluate_expression(rule.expression, record)
    return Evaluation(
        rule=rule, record_type=record_type, record_id=record_id,
        passed=passed, reason="" if passed else render_reason(rule, record),
    )


def evaluate_all(record: Any, *, record_type: str, record_id: str) -> list[Evaluation]:
    """Evaluate every ACTIVE rule whose applicability_filter.entity matches."""
    qs = DqaRule.objects.filter(status=RuleStatus.ACTIVE)
    evaluations: list[Evaluation] = []
    for rule in qs:
        entity = (rule.applicability_filter or {}).get("entity")
        if entity and entity != record_type:
            continue
        evaluations.append(evaluate(rule, record, record_type=record_type, record_id=record_id))
    return evaluations
