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

    # Severity-aware failure counter. Reads through severity_bucket
    # so a legacy `warning` rule and a new-vocabulary `flag` rule
    # both land in the same `flag` bucket — previously they were
    # split and the counter mis-totalled for the audit row.
    # Lazy import — severity_bucket lives in dqa.models alongside the Severity
    # enum; importing it at module top-level created a circular-import cycle
    # that surfaced under the CI full-suite collection order (coverage +
    # analytics replica). Deferring to call time breaks it.
    from .models import severity_bucket

    by_bucket = {"block": [], "flag": [], "info": []}
    for ev in evaluations:
        if ev.passed:
            continue
        bucket = severity_bucket(ev.rule.severity)
        by_bucket[bucket].append(ev.rule.rule_id)

    # Resolve the parent household_id for FLAG audit emission. CR
    # entity_type=member commits write the result row keyed by the
    # member; the UPD reactor still needs to know which household to
    # open a review case against, so we walk through to it.
    flagged_codes = sorted(set(by_bucket["flag"]))
    if flagged_codes:
        household_id = (
            str(target.pk) if record_type == "household"
            else str(getattr(target, "household_id", "") or "")
        )
        if household_id:
            emit_audit(
                action="dqa.household.flag",
                entity_type="household",
                entity_id=household_id,
                actor=change_request.approver or "system",
                reason=(
                    f"stage=registry_post_promote "
                    f"change_request={change_request.id}"
                ),
                field_changes={
                    "stage": "registry_post_promote",
                    "change_request": change_request.id,
                    "flagged_codes": flagged_codes,
                },
            )

    emit_audit(
        action="rules_re_evaluated", entity_type=f"dat.{record_type}",
        entity_id=record_id,
        actor=change_request.approver or "system",
        reason=(
            f"upd_commit {change_request.id} → "
            f"{sum(len(v) for v in by_bucket.values())} failure(s)"
        ),
        field_changes={
            "change_request": change_request.id,
            "evaluations_total": len(evaluations),
            # Legacy keys (blocking / warning) kept for back-compat
            # of any consumer that reads the old shape; the new
            # bucket keys are the authoritative values.
            "failures_blocking": len(by_bucket["block"]),
            "failures_warning": len(by_bucket["flag"]),
            "failures_block": len(by_bucket["block"]),
            "failures_flag": len(by_bucket["flag"]),
            "failures_info": len(by_bucket["info"]),
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
