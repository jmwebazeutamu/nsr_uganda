"""HouseholdRuleEvaluator — pure-function intra-household DQA (US-S11-044).

Per the spec + ADR-0022, this module is the household-scope counterpart
to apps.dqa.engine. The interpreter is a small DSL with three
household-aware operators (`count_where`, `for_each_member`,
`lookup_member`) plus the usual comparisons and boolean composition.

Design contract:
- `evaluate_household` is a pure function: rules + payload → result dict.
  No I/O. Tests can run thousands of permutations in microseconds.
- `persist_household_evaluation` is a thin wrapper that loads active
  rules, calls the pure evaluator, writes a DqaEvaluation row, and
  emits an AuditEvent. Persistence is the only side-effecting layer.
- Time-dependent rules accept `now` so tests are deterministic.

DSL shape:
    "$.<path>"                  — value on current scope (member or hh)
    "$members[<i>].<path>"      — member by index
    "$parameters.<key>"         — rule parameter
    "$reported_household_size"  — hh shortcut
    "$now"                      — utcnow at evaluation time

    {"op": "<name>", "args": [<expr>, <expr>]}
        ops: eq / neq / lt / gt / lte / gte / in / not_in / not_null
             / is_null / and / or / not / sub / add

    {"op": "count_where", "predicate": <expr>}
        — int, count of members where predicate is true

    {"op": "for_each_member", "predicate": <expr>}
        — list of {member, idx, predicate_result, offenders[]}
        — the rule's fail_when reads .count; offenders bubble up

    {"op": "lookup_member", "by": "<field>", "value": <expr>}
        — member dict or null

Top-level rule shape:
    {
        "expression":  <expression returning bool | int | list>,
        "fail_when":   <predicate over the expression result; default "truthy">
    }

Result returned by `evaluate_household`:
    {
        "outcome": "pass" | "review" | "block",
        "stage":   <stage>,
        "evaluator_service_version": "1.0",
        "results": [
            {
                "rule_code": "AC-HOH-EXISTS",
                "rule_version": 3,
                "status": "pass" | "fail",
                "severity": "block" | ...,
                "message": "<interpolated>",
                "offending_member_ids": [...],
                "parameters_used": {...},
            },
            ...
        ],
    }
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

EVALUATOR_SERVICE_VERSION = "1.0"


class DslError(Exception):
    """The household-scope rule expression is malformed or references
    an undeclared parameter."""


# ---------------------------------------------------------------------------
# Scope: the runtime context an expression evaluates against.

@dataclass
class _Scope:
    """Resolution context for `$`-prefixed references. `current` is the
    member (inside `for_each_member` / `count_where`) or the household
    (top level). Members, parameters, now are passed verbatim. Empty
    `offending_member_ids` accumulates as `for_each_member` runs."""

    current: dict
    household: dict
    members: list[dict]
    parameters: dict
    now: datetime
    offending_member_ids: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Reference resolution

def _resolve_ref(ref: str, scope: _Scope) -> Any:
    """Resolve a `$`-prefixed string against the scope. Unknown prefixes
    raise; bare `$` returns the current scope item. Strings without `$`
    aren't refs and the caller hands them back unchanged."""
    if ref == "$":
        return scope.current
    if ref == "$now":
        return scope.now
    if ref.startswith("$parameters."):
        key = ref[len("$parameters."):]
        if key not in scope.parameters:
            raise DslError(f"undeclared parameter: {key}")
        return scope.parameters[key]
    if ref == "$reported_household_size":
        return scope.household.get("reported_household_size")
    if ref.startswith("$.")  :
        return _walk_path(scope.current, ref[2:])
    if ref.startswith("$members["):
        # $members[<idx_or_lineno>].<rest>
        rest = ref[len("$members["):]
        close = rest.index("]")
        idx_str = rest[:close]
        tail = rest[close + 1:]
        if tail.startswith("."):
            tail = tail[1:]
        try:
            idx = int(idx_str)
        except ValueError as exc:
            raise DslError(f"$members[…] index must be int: {idx_str!r}") from exc
        member = scope.members[idx] if 0 <= idx < len(scope.members) else None
        if not tail:
            return member
        if member is None:
            return None
        return _walk_path(member, tail)
    raise DslError(f"unknown reference: {ref!r}")


def _walk_path(obj: Any, path: str) -> Any:
    """Dotted-path walk. Returns None when any segment misses."""
    cur = obj
    for seg in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(seg)
        else:
            cur = getattr(cur, seg, None)
    return cur


def _arg(node: Any, scope: _Scope) -> Any:
    """An arg is either a literal or a $-ref (string) or a nested
    expression (dict). Numbers / bools / lists / None come back as-is."""
    if isinstance(node, str) and node.startswith("$"):
        return _resolve_ref(node, scope)
    if isinstance(node, dict) and "op" in node:
        return _eval_expr(node, scope)
    return node


# ---------------------------------------------------------------------------
# Operators

def _op_eq(a, b):  return a == b
def _op_neq(a, b): return a != b
def _op_lt(a, b):  return a is not None and b is not None and a < b
def _op_gt(a, b):  return a is not None and b is not None and a > b
def _op_lte(a, b): return a is not None and b is not None and a <= b
def _op_gte(a, b): return a is not None and b is not None and a >= b
def _op_in(a, b):  return a in (b or [])
def _op_not_in(a, b): return a not in (b or [])
def _op_not_null(a, _): return a is not None and a != ""
def _op_is_null(a, _):  return a is None or a == ""
def _op_sub(a, b): return (a or 0) - (b or 0)
def _op_add(a, b): return (a or 0) + (b or 0)

_BINARY_OPS = {
    "eq": _op_eq, "neq": _op_neq,
    "lt": _op_lt, "gt": _op_gt, "lte": _op_lte, "gte": _op_gte,
    "in": _op_in, "not_in": _op_not_in,
    "sub": _op_sub, "add": _op_add,
}
_UNARY_OPS = {
    "not_null": _op_not_null, "is_null": _op_is_null,
}


# ---------------------------------------------------------------------------
# Expression interpreter

def _eval_expr(node: Any, scope: _Scope) -> Any:
    if not isinstance(node, dict) or "op" not in node:
        raise DslError(f"expression node must be {{op:..., args:...}}; got {node!r}")
    op = node["op"]

    # Boolean composition.
    if op == "and":
        return all(_arg(a, scope) for a in node.get("args", []))
    if op == "or":
        return any(_arg(a, scope) for a in node.get("args", []))
    if op == "not":
        return not _arg(node["args"][0], scope)

    # Unary value predicates.
    if op in _UNARY_OPS:
        a = _arg(node["args"][0], scope)
        return _UNARY_OPS[op](a, None)

    # Binary comparisons.
    if op in _BINARY_OPS:
        args = node.get("args", [])
        if len(args) != 2:
            raise DslError(f"op {op!r} needs exactly 2 args")
        return _BINARY_OPS[op](_arg(args[0], scope), _arg(args[1], scope))

    # Aggregates over members.
    if op == "count_where":
        predicate = node.get("predicate")
        if predicate is None:
            raise DslError("count_where requires `predicate`")
        n = 0
        for m in scope.members:
            sub_scope = _scope_with_current(scope, m)
            if _arg(predicate, sub_scope):
                n += 1
                _capture_offender(scope, m)
        return n

    if op == "for_each_member":
        predicate = node.get("predicate")
        if predicate is None:
            raise DslError("for_each_member requires `predicate`")
        offenders = []
        for m in scope.members:
            sub_scope = _scope_with_current(scope, m)
            if _arg(predicate, sub_scope):
                offenders.append(_member_id(m))
        # Bubble offenders up so the rule result can capture them.
        scope.offending_member_ids.extend(offenders)
        return len(offenders)

    if op == "lookup_member":
        by = node.get("by")
        value_node = node.get("value")
        if not by or value_node is None:
            raise DslError("lookup_member requires `by` + `value`")
        target = _arg(value_node, scope)
        for m in scope.members:
            if _walk_path(m, by) == target:
                return m
        return None

    raise DslError(f"unknown op: {op!r}")


def _scope_with_current(scope: _Scope, current: dict) -> _Scope:
    return _Scope(
        current=current,
        household=scope.household,
        members=scope.members,
        parameters=scope.parameters,
        now=scope.now,
        offending_member_ids=scope.offending_member_ids,
    )


def _member_id(m: dict) -> str:
    """Stable id for offending-member lists. Prefer the canonical
    `id` (ULID); fall back to `line_number` cast to string so the
    chain works for pre-promotion payloads where ids don't yet exist."""
    if m.get("id"):
        return str(m["id"])
    if m.get("line_number") is not None:
        return f"line:{m['line_number']}"
    return "?"


def _capture_offender(scope: _Scope, m: dict) -> None:
    mid = _member_id(m)
    if mid not in scope.offending_member_ids:
        scope.offending_member_ids.append(mid)


# ---------------------------------------------------------------------------
# Rule evaluation

def _interpolate(template: str, parameters: dict, extras: dict | None = None) -> str:
    """{key} placeholders filled from parameters + extras. Missing keys
    render as themselves so a malformed template surfaces visibly
    rather than silently."""
    if not template:
        return ""
    pool = dict(parameters)
    if extras:
        pool.update(extras)
    out = template
    for k, v in pool.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def evaluate_rule(
    rule: dict, payload: dict, *, now: datetime | None = None,
) -> dict:
    """Evaluate one rule against one household payload. Pure function.

    `rule` is a dict carrying the columns the household evaluator
    reads — designed to be either a serialised DqaRule row or a
    test fixture without DB I/O.
    """
    now = now or datetime.now(UTC)
    parameters = rule.get("parameters") or {}
    household = payload  # the top-level dict IS the household
    members = household.get("members") or []
    scope = _Scope(
        current=household, household=household,
        members=members, parameters=parameters, now=now,
    )

    expression = rule.get("expression") or {}
    fail_when = rule.get("fail_when") or {"op": "gt", "args": ["$", 0]}

    try:
        result_value = _eval_expr(expression, scope)
    except DslError as exc:
        # An invalid rule surfaces as a soft fail with the message so
        # the Rule Editor's test-fixture runner can show authors why.
        return _build_result(
            rule, status="error", offenders=[],
            extras={"error": str(exc), "expression_result": None},
        )

    # fail_when operates against the expression result; bind it to "$"
    # so the same operators work.
    fail_scope = _Scope(
        current=result_value, household=household, members=members,
        parameters=parameters, now=now,
    )
    failed = bool(_eval_expr(fail_when, fail_scope))

    return _build_result(
        rule,
        status="fail" if failed else "pass",
        offenders=list(scope.offending_member_ids),
        extras={"expression_result": result_value},
    )


def _build_result(rule: dict, *, status: str, offenders: list[str], extras: dict) -> dict:
    parameters = rule.get("parameters") or {}
    template = rule.get("error_message_template", "")
    if status == "error":
        # Surface the DSL error verbatim so the Rule Editor's test-
        # fixture runner can show authors why their expression broke.
        message = f"rule error: {extras.get('error', 'unknown')}"
    elif status != "pass":
        message = _interpolate(template, parameters, extras)
    else:
        message = ""
    return {
        "rule_code": rule.get("rule_id", ""),
        "rule_version": rule.get("version", 0),
        "status": status,
        "severity": rule.get("severity", "info"),
        "message": message,
        "offending_member_ids": offenders,
        "parameters_used": parameters,
    }


# ---------------------------------------------------------------------------
# Aggregate: household-level evaluation across N rules

def _aggregate_outcome(rule_results: list[dict]) -> str:
    """BLOCK if any blocking failure, REVIEW if any flag, PASS otherwise."""
    fails = [r for r in rule_results if r["status"] in ("fail", "error")]
    if not fails:
        return "pass"
    severities = {r["severity"] for r in fails}
    if {"block", "reject_with_override"} & severities:
        return "block"
    if "flag" in severities:
        return "review"
    return "pass"  # info-only failures don't escalate the aggregate


def evaluate_household(
    rules: list[dict], payload: dict, *,
    stage: str, now: datetime | None = None,
) -> dict:
    """Pure: run every rule (in order) over the household payload.

    Caller filters `rules` to those active + matching `stage` BEFORE
    calling; the evaluator doesn't decide which rules apply. This
    keeps the function deterministic for tests + replayable from
    historical evaluations.
    """
    now = now or datetime.now(UTC)
    results = [evaluate_rule(r, payload, now=now) for r in rules]
    return {
        "stage": stage,
        "outcome": _aggregate_outcome(results),
        "evaluator_service_version": EVALUATOR_SERVICE_VERSION,
        "results": results,
    }


# ---------------------------------------------------------------------------
# Persistence wrapper — the only I/O surface

def load_active_household_rules(stage: str) -> list[dict]:
    """Pull the active intra-household rules that include `stage` in
    their stages list. Returns dicts shaped for `evaluate_household`.
    """
    from .models import DqaRule, RuleCategory, RuleScope, RuleStatus

    qs = DqaRule.objects.filter(
        category=RuleCategory.INTRA_HOUSEHOLD,
        scope=RuleScope.HOUSEHOLD,
        status=RuleStatus.ACTIVE,
    ).order_by("rule_id", "-version")

    # Dedup by rule_id keeping highest version (which is .first() per
    # the ordering above).
    seen: set[str] = set()
    out: list[dict] = []
    for rule in qs:
        if rule.rule_id in seen:
            continue
        stages = rule.stages or []
        if stage and stage not in stages:
            continue
        seen.add(rule.rule_id)
        out.append({
            "rule_id": rule.rule_id,
            "version": rule.version,
            "severity": rule.severity,
            "parameters": rule.parameters or {},
            "expression": rule.expression or {},
            "fail_when": (rule.expression or {}).get(
                "_fail_when",
                {"op": "gt", "args": ["$", 0]},
            ),
            "error_message_template": rule.error_message_template,
        })
    return out


def persist_household_evaluation(
    payload: dict, *, stage: str, actor: str,
    household_id: str, household_version: int | None = None,
    now: datetime | None = None,
):
    """Load rules + evaluate + write a DqaEvaluation row + emit
    AuditEvent. Returns the persisted DqaEvaluation instance.

    `household_id` is required even at DIH_INGEST (use the provisional
    Registry ID), so the evaluation chain is queryable end-to-end.
    """
    from apps.security.audit import emit as emit_audit

    from .models import DqaEvaluation

    rules = load_active_household_rules(stage)
    aggregate = evaluate_household(rules, payload, stage=stage, now=now)

    eval_row = DqaEvaluation.objects.create(
        household_id=household_id,
        household_version=household_version,
        stage=stage,
        outcome=aggregate["outcome"],
        results=aggregate["results"],
        evaluator_service_version=aggregate["evaluator_service_version"],
        actor=actor or "system",
    )

    emit_audit(
        "dqa.household.evaluated", "household", household_id,
        actor=actor or "system",
        reason=f"stage={stage} outcome={aggregate['outcome']} rules={len(rules)}",
        field_changes={
            "evaluation_id": eval_row.id,
            "stage": stage,
            "outcome": aggregate["outcome"],
            "failed_rule_codes": [
                r["rule_code"] for r in aggregate["results"]
                if r["status"] in ("fail", "error")
            ],
        },
    )
    return eval_row
