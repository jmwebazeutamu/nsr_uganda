"""US-119 — sync the FormVersion-authored constraint pack into DAT-DQA.

When a FormVersion approaches ACTIVE, the registry's runtime DQA
engine needs the matching rule rows. Authoring lives in
apps.intake (FormSection + FormQuestion + FormConstraint +
FormSkipLogic); evaluation lives in apps.dqa (DqaRule, evaluated
by apps.dqa.engine).

This module bridges the two — for each FormQuestion that carries
a structured FormConstraint (JSON-DSL), it creates or updates a
matching DqaRule:

    rule_id              = AC-FORM-<form_version>-<question_name>
    version              = form_version.version
    description          = "Auto-generated from FormVersion v… question …"
    severity             = blocking (constraints are hard rules at intake)
    expression           = FormConstraint.dsl
    error_message_template = FormConstraint.message
    applicability_filter = {entity, form_version}
    status               = active
    author/approved_by   = "system-sync"

Atomic — wrapped in @transaction.atomic so a partial failure
rolls back the whole sync; partial activations are worse than
none. Idempotent — re-runs upsert in place on (rule_id, version).

Returns a small report dict for tests + the admin status panel.
The FormVersion's approval workflow (US-117 lifecycle) calls
sync_rule_pack on its way through `approve` so by the time a
FormVersion is ACTIVE the rule pack matches it.
"""

from __future__ import annotations

from django.db import transaction

from apps.dqa.models import DqaRule, RuleStatus, Severity
from apps.security.audit import emit as emit_audit

from .models import FormVersion


def _rule_id_for(fv: FormVersion, question_name: str) -> str:
    """The DqaRule.rule_id we use for auto-synced rules. Stable across
    runs so update_or_create maps cleanly."""
    return f"AC-FORM-{fv.version}-{question_name}"


@transaction.atomic
def sync_rule_pack(form_version: FormVersion, *, actor: str = "system-sync") -> dict:
    """Idempotent sync. Returns {created, updated, deleted, audit_event_id}."""
    created = 0
    updated = 0

    sections = form_version.sections.prefetch_related(
        "questions__constraints", "questions__skip_logic",
    )

    for section in sections:
        # entity inference: roster sections (C, D, E, F) target
        # Member-level evaluation; everything else is household-level.
        entity = "member" if section.code in {"C", "D", "E", "F"} else "household"
        for question in section.questions.all():
            constraint = question.constraints.first()
            if not constraint or not constraint.dsl:
                continue
            rule_id = _rule_id_for(form_version, question.name)
            _, was_created = DqaRule.objects.update_or_create(
                rule_id=rule_id, version=form_version.version,
                defaults={
                    "description": (
                        f"Auto-synced from FormVersion v{form_version.version} "
                        f"section {section.code} question {question.name}"
                    ),
                    "severity": Severity.BLOCKING,
                    "applicability_filter": {
                        "entity": entity, "form_version": form_version.version,
                    },
                    "expression": constraint.dsl,
                    "error_message_template": (
                        constraint.message or question.constraint_message
                        or f"validation failed for {question.name}"
                    ),
                    "status": RuleStatus.ACTIVE,
                    "author": actor,
                    "approved_by": actor,
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1

    # Single audit row for the whole fan-out — operators (and the
    # DPO) see one event per activation, not N per question. The
    # event's field_changes carries the count so anomaly detection
    # can flag unusual surges.
    ev = emit_audit(
        action="rule_pack_synced",
        entity_type="intake.form_version",
        entity_id=form_version.id,
        actor=actor or "system-sync",
        actor_kind="system",
        reason=(
            f"version={form_version.version} created={created} updated={updated}"
        ),
        field_changes={"created": created, "updated": updated},
    )

    return {
        "form_version_id": form_version.id,
        "form_version_version": form_version.version,
        "created": created,
        "updated": updated,
        "audit_event_id": ev.id,
    }
