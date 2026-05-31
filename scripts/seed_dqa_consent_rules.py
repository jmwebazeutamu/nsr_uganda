"""Seed the AC-CONSENT-* DQA rule family (US-CONSENT-09).

Five rules covering the consent-capture invariants. They are seeded as DRAFT
and MUST be ratified by the DPO (dual-approval, author != approver) before
activation — the prompt requires DPO ratification of the rule pack before the
feature flag flips on. Capture-time enforcement of the same intent already
lives in apps.consent.dqa_hooks (so a bad record never lands); these are the
versioned, auditable definitions the rule engine evaluates at promotion.

Severity follows the four-tier vocabulary in 04_ui_design_brief.md §8.

Usage:
  .venv/bin/python scripts/seed_dqa_consent_rules.py            # seed DRAFT
  .venv/bin/python scripts/seed_dqa_consent_rules.py --activate # seed + approve
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nsr_mis.settings")

AUTHOR = "seed-author"
APPROVER = "seed-approver"

# rule_id, severity, applicability_filter, expression, message, scope
RULES = [
    {
        "rule_id": "AC-CONSENT-MANDATORY",
        "severity": "block",
        "description": (
            "REGISTRATION consent must be GRANTED for the household head before "
            "the record can be promoted to the registry."),
        "applicability_filter": {"entity": "member", "purpose": "REGISTRATION"},
        "expression": {"field": "consent.REGISTRATION", "op": "eq", "args": ["$", "GRANTED"]},
        "error_message_template": "REGISTRATION consent is mandatory before promotion.",
    },
    {
        "rule_id": "AC-CONSENT-METHOD-VALID",
        "severity": "block",
        "description": (
            "Verbal-witnessed consent requires a witness name and role "
            "(guards against coerced verbal consent, CR1)."),
        "applicability_filter": {"entity": "consent"},
        "expression": {
            "implies": [
                {"field": "capture_method", "op": "eq", "args": ["$", "VERBAL_WITNESSED"]},
                {"all_of": [
                    {"field": "witness_name", "op": "not_blank"},
                    {"field": "witness_role", "op": "not_blank"},
                ]},
            ],
        },
        "error_message_template": "Verbal consent requires a witness name and role.",
    },
    {
        "rule_id": "AC-CONSENT-PURPOSE-VERSION-CURRENT",
        "severity": "reject_with_override",
        "description": (
            "The statement version consented against must have been ACTIVE at "
            "the moment of capture."),
        "applicability_filter": {"entity": "consent"},
        "expression": {"field": "statement_version_active_at_capture", "op": "is_true"},
        "error_message_template": "Consent captured against a non-current statement version.",
    },
    {
        "rule_id": "AC-CONSENT-CAPTURE-TIMESTAMP-PLAUSIBLE",
        "severity": "flag",
        "description": (
            "The capture timestamp must fall within a plausible window "
            "(not in the future, not before the registry epoch)."),
        "applicability_filter": {"entity": "consent"},
        "expression": {"field": "captured_at", "op": "within_window",
                       "args": ["$", "registry_epoch", "now"]},
        "error_message_template": "Consent capture timestamp is implausible.",
    },
    {
        "rule_id": "AC-CONSENT-MINOR-PROXY-PRESENT",
        "severity": "block",
        "description": (
            "A member under 18 granting consent must have a proxy relationship "
            "(parent/guardian) recorded."),
        "applicability_filter": {"entity": "member"},
        "expression": {
            "implies": [
                {"field": "age_years", "op": "lt", "args": ["$", 18]},
                {"field": "proxy_relationship", "op": "not_blank"},
            ],
        },
        "error_message_template": "Members under 18 require a proxy relationship for consent.",
    },
]


def seed(*, author: str = AUTHOR, approver: str = APPROVER, activate: bool = False) -> list:
    """Create the AC-CONSENT-* rules as DRAFT (optionally ratify them).
    Idempotent on (rule_id, version=1). Returns the rule rows."""
    from apps.dqa.models import DqaRule, RuleCategory, RuleStatus
    from apps.dqa.services import approve, submit_for_approval

    rows = []
    for spec in RULES:
        rule, _ = DqaRule.objects.update_or_create(
            rule_id=spec["rule_id"], version=1,
            defaults=dict(
                description=spec["description"],
                severity=spec["severity"],
                category=RuleCategory.FIELD_LEVEL,
                applicability_filter=spec["applicability_filter"],
                expression=spec["expression"],
                error_message_template=spec["error_message_template"],
                status=RuleStatus.DRAFT,
                author=author,
            ),
        )
        if activate and rule.status == RuleStatus.DRAFT:
            submit_for_approval(rule, actor=author)
            approve(rule, approver=approver, note="Seed ratification (US-CONSENT-09).")
        rows.append(rule)
    return rows


if __name__ == "__main__":
    import django

    django.setup()
    activate = "--activate" in sys.argv
    created = seed(activate=activate)
    print(f"Seeded {len(created)} AC-CONSENT-* rules "
          f"({'ACTIVE' if activate else 'DRAFT'}).")
