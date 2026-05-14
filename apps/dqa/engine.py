"""DAT-DQA in-process Python rules engine.

SAD §4.2.1 picks Python-evaluated JSON-DSL over Drools. The DSL has two
node shapes:

    leaf node:     {"field": "<path>", "op": "<name>", "value": <any>}
    composite:     {"all_of": [<node>, ...]} | {"any_of": [<node>, ...]}

Field paths walk the record dict (`address.street`) or use attribute access
when the record is a Django model instance. Operators in this Sprint 0 set:

    not_null, is_null, eq, neq, in, not_in, regex, gt, lt, ge, le, between

The remaining operators from SAD §4.2.3 (within_polygon, accuracy_le,
count_eq, count_neq, cross_field_eq, references_existing) land alongside
the rule that first needs each one. Unknown operators raise DSLError.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

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


@_op("gt")
def _op_gt(field_value, value):
    return field_value is not None and field_value > value


@_op("lt")
def _op_lt(field_value, value):
    return field_value is not None and field_value < value


@_op("ge")
def _op_ge(field_value, value):
    return field_value is not None and field_value >= value


@_op("le")
def _op_le(field_value, value):
    return field_value is not None and field_value <= value


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
