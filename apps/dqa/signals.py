"""US-080 — re-evaluate DQA rules when a ChangeRequest applies.

Connected in apps/dqa/apps.py::ready. Without this hook, rules only
fire during initial ingestion via apps.ingestion_hub.services — UPD
edits to existing Household / Member rows silently bypass the rule
pack, which means a new constraint added after a record was first
captured never gets evaluated against that record.

Behaviour:
- post_change_committed fires with (change_request, target). We
  project `target` into the same dict shape the engine expects
  (model_to_dict) and call evaluate_all().
- For every failed evaluation, we append a DqaResult row. We do
  NOT delete prior results — DqaResult is append-only history and
  the violations dashboard reads "most recent per (rule, record)".
- Emits an audit event so the DPO anomaly feed surfaces the
  re-evaluation alongside the change-request audit row.

Idempotent in the practical sense — committing the same CR twice
isn't possible (status → COMMITTED is a terminal transition), so
duplicate re-evaluations don't happen. If the same record gets
multiple successive CRs committed, each commit appends its own
batch of results, which is the historical record we want.
"""

from __future__ import annotations

import logging

from django.forms.models import model_to_dict

from apps.security.audit import emit as emit_audit
from apps.update_workflow.models import EntityType
from apps.update_workflow.services import post_change_committed

from .engine import evaluate_all
from .models import DqaResult

logger = logging.getLogger(__name__)


def _project_target(target, record_type: str) -> dict:
    """Build the record dict the DQA engine evaluates against. Uses
    Django's model_to_dict to capture concrete fields; the engine's
    expression DSL reads by field name."""
    payload = model_to_dict(target)
    # Convert non-JSON-friendly types where the engine cares. Most
    # rules read scalar fields directly; UUIDs/Decimal/dates are
    # rendered to string for comparison.
    for k, v in list(payload.items()):
        if v is None or isinstance(v, (str, int, float, bool, list, dict)):
            continue
        payload[k] = str(v)
    # The legacy ingestion path passes member dicts that include a
    # `line_number` key; the engine's per-member rules sometimes
    # read it. CR-applied members carry the same shape after
    # model_to_dict, but if downstream rules reach for it, surface
    # it explicitly.
    if record_type == "member" and "line_number" not in payload:
        payload["line_number"] = getattr(target, "line_number", "")
    return payload


def _record_id_for(target, record_type: str) -> str:
    """Stable per-record identifier for DqaResult.record_id. Mirrors
    the ingest path: households are keyed by their pk; members by
    "<household_id>:<line_number>" so the dashboard groups all
    of a household's member rows cleanly."""
    if record_type == "household":
        return str(target.pk)
    line = getattr(target, "line_number", None) or ""
    hh = getattr(target, "household_id", None) or "?"
    return f"{hh}:{line}"


def on_change_committed(sender, *, change_request, target, **kwargs):
    """Re-evaluate every applicable DqaRule against `target` after
    a CR commits. Writes failure rows to DqaResult; counts and
    severities ride into the audit event."""
    if change_request.entity_type == EntityType.HOUSEHOLD:
        record_type = "household"
    elif change_request.entity_type == EntityType.MEMBER:
        record_type = "member"
    else:
        logger.debug(
            "dqa.on_change_committed: skipping unknown entity_type %r",
            change_request.entity_type,
        )
        return

    record = _project_target(target, record_type)
    record_id = _record_id_for(target, record_type)
    evaluations = evaluate_all(
        record, record_type=record_type, record_id=record_id,
    )

    new_rows = [
        DqaResult(
            rule=ev.rule, record_type=record_type, record_id=record_id,
            passed=False, severity=ev.rule.severity, reason=ev.reason,
        )
        for ev in evaluations if not ev.passed
    ]
    if new_rows:
        DqaResult.objects.bulk_create(new_rows, batch_size=50)

    by_severity = {"blocking": 0, "warning": 0, "info": 0}
    for ev in evaluations:
        if ev.passed:
            continue
        by_severity[ev.rule.severity] = by_severity.get(ev.rule.severity, 0) + 1

    emit_audit(
        action="rules_re_evaluated", entity_type=f"dat.{record_type}",
        entity_id=record_id,
        actor=change_request.approver or "system",
        reason=(
            f"upd_commit {change_request.id} → "
            f"{sum(by_severity.values())} failure(s)"
        ),
        field_changes={
            "change_request": change_request.id,
            "evaluations_total": len(evaluations),
            "failures_blocking": by_severity["blocking"],
            "failures_warning": by_severity["warning"],
            "failures_info": by_severity["info"],
        },
    )


post_change_committed.connect(
    on_change_committed, dispatch_uid="dqa.on_change_committed",
)


def connect() -> None:
    """Retained for explicit re-connect during tests."""
    post_change_committed.connect(
        on_change_committed, dispatch_uid="dqa.on_change_committed",
    )
