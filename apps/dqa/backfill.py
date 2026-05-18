"""US-080b — backfill DQA evaluation across stored records.

Sister to apps.dqa.signals (US-080), which catches NEW UPD edits.
This module sweeps EVERY existing record so a rule added today is
evaluated against every Household / Member captured before today.
Without it, a newly-approved constraint would only flag records
that happen to be edited downstream.

Public entry points:
- backfill_rule(rule, *, actor, batch_size=500) — sweep one rule.
- backfill_all(*, actor, batch_size=500, entity=None) — sweep
  every ACTIVE rule. Optional entity filter ("household" / "member")
  for partial runs.

Both return a report dict. Both wrap each rule's sweep in a
single audit event (`rules_backfilled`). Bulk-inserts DqaResult
rows in batches so memory stays bounded at scale.
"""

from __future__ import annotations

import logging
from typing import Any

from django.db import transaction
from django.forms.models import model_to_dict

from apps.security.audit import emit as emit_audit

from .engine import evaluate
from .models import DqaResult, DqaRule, RuleStatus

logger = logging.getLogger(__name__)


def _entity_to_queryset(entity: str):
    """Map applicability_filter.entity → the Django queryset of
    records to scan. Unknown entities raise so a typo doesn't
    silently no-op the backfill."""
    if entity == "household":
        from apps.data_management.models import Household
        return Household.objects.all(), "household"
    if entity == "member":
        from apps.data_management.models import Member
        return Member.objects.select_related("household"), "member"
    raise ValueError(f"unknown applicability entity: {entity!r}")


def _record_id_for(target, record_type: str) -> str:
    """Matches the convention used by apps.dqa.signals and the
    ingest path: household → str(pk); member → "<hh>:<line>"."""
    if record_type == "household":
        return str(target.pk)
    line = getattr(target, "line_number", None) or ""
    hh = getattr(target, "household_id", None) or "?"
    return f"{hh}:{line}"


def _project_target(target) -> dict[str, Any]:
    """Same projection apps.dqa.signals uses. Coerces non-JSON
    field values to str so the engine's expression DSL evaluates
    them as strings (which is what the legacy ingest dict shape
    looks like)."""
    payload = model_to_dict(target)
    for k, v in list(payload.items()):
        if v is None or isinstance(v, (str, int, float, bool, list, dict)):
            continue
        payload[k] = str(v)
    return payload


def backfill_rule(
    rule: DqaRule, *,
    actor: str = "system-backfill",
    batch_size: int = 500,
    dry_run: bool = False,
) -> dict:
    """Evaluate `rule` against every stored record matching its
    applicability_filter.entity. Appends DqaResult rows for
    failures. Does NOT delete prior results — DqaResult is
    append-only and the violations dashboard reads the latest
    per (rule, record).

    Returns:
        {records_scanned, evaluations, failures, batches, dry_run}
    """
    if rule.status != RuleStatus.ACTIVE:
        raise ValueError(
            f"backfill_rule: refusing inactive rule {rule.rule_id} "
            f"(status={rule.status!r}); activate it first.",
        )
    entity = (rule.applicability_filter or {}).get("entity")
    if not entity:
        raise ValueError(
            f"rule {rule.rule_id} has no applicability_filter.entity; "
            "cannot determine which records to scan.",
        )
    qs, record_type = _entity_to_queryset(entity)

    records_scanned = 0
    failures = 0
    batches = 0
    pending: list[DqaResult] = []

    def _flush():
        if pending and not dry_run:
            DqaResult.objects.bulk_create(pending, batch_size=batch_size)
        pending.clear()

    for target in qs.iterator(chunk_size=batch_size):
        records_scanned += 1
        record = _project_target(target)
        record_id = _record_id_for(target, record_type)
        ev = evaluate(rule, record, record_type=record_type, record_id=record_id)
        if not ev.passed:
            failures += 1
            pending.append(DqaResult(
                rule=rule, record_type=record_type, record_id=record_id,
                passed=False, severity=rule.severity, reason=ev.reason,
            ))
        if len(pending) >= batch_size:
            _flush()
            batches += 1
    _flush()
    if pending == [] and failures > 0:
        batches += 1  # the final partial batch counts

    emit_audit(
        action="rules_backfilled", entity_type="dqa.rule",
        entity_id=rule.rule_id, actor=actor,
        reason=(
            f"backfill v{rule.version} → {records_scanned} {entity}(s) "
            f"scanned, {failures} failure(s)"
        ),
        field_changes={
            "rule_id": rule.rule_id, "rule_version": rule.version,
            "records_scanned": records_scanned,
            "failures": failures, "dry_run": dry_run,
        },
    )

    return {
        "rule_id": rule.rule_id, "rule_version": rule.version,
        "entity": entity, "record_type": record_type,
        "records_scanned": records_scanned,
        "failures": failures, "batches": batches,
        "dry_run": dry_run,
    }


@transaction.atomic
def backfill_all(
    *,
    actor: str = "system-backfill",
    batch_size: int = 500,
    entity: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Backfill every ACTIVE rule (optionally filtered by entity).
    Wrapped in @transaction.atomic so a mid-sweep crash leaves no
    partial DqaResult rows. For a 12M-row production sweep this
    would belong in Celery; the synchronous path is fine for the
    Sprint 20 demo + the typical dev rule-pack size."""
    rules = DqaRule.objects.filter(status=RuleStatus.ACTIVE)
    if entity is not None:
        rules = [
            r for r in rules
            if (r.applicability_filter or {}).get("entity") == entity
        ]
    reports = []
    for rule in rules:
        try:
            reports.append(backfill_rule(
                rule, actor=actor, batch_size=batch_size, dry_run=dry_run,
            ))
        except ValueError as exc:
            logger.warning("backfill_all skipped %s: %s", rule.rule_id, exc)
            reports.append({
                "rule_id": rule.rule_id, "skipped": True,
                "reason": str(exc),
            })
    return {
        "rules_processed": len(reports),
        "total_records": sum(r.get("records_scanned", 0) for r in reports),
        "total_failures": sum(r.get("failures", 0) for r in reports),
        "reports": reports,
    }
