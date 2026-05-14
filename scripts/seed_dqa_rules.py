"""Seed the three Sprint 0 wired DQA rules end-to-end.

Per CLAUDE.md Sprint 0 item 4 and SAD §4.2.5 (initial rule catalogue):

  AC-MANDATORY     — every mandatory field is present (blocking)
  AC-NIN-FORMAT    — NIN matches the NIRA regex ^(CM|CF)[A-Z0-9]{12}$ (blocking)
  AC-GPS-ACCURACY  — GPS accuracy reading is 10m or better (blocking)

The seed walks the dual-approval workflow: each rule is authored by one
operator account and approved by a different one, exercising the
'author != approved_by' rule that apps.dqa.services enforces.

Usage:
  .venv/bin/python scripts/seed_dqa_rules.py
"""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

import django

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nsr_mis.settings")
django.setup()

from apps.dqa.models import DqaRule, RuleStatus, Severity  # noqa: E402
from apps.dqa.services import approve, submit_for_approval  # noqa: E402


AUTHOR = "seed-author"
APPROVER = "seed-approver"


RULES = [
    {
        "rule_id": "AC-MANDATORY-MEMBER-NAME",
        "description": "Member surname and first name must be present (subset of SAD AC-MANDATORY scoped to Sprint 0).",
        "severity": Severity.BLOCKING,
        "applicability_filter": {"entity": "member"},
        "expression": {
            "all_of": [
                {"field": "surname", "op": "not_null"},
                {"field": "first_name", "op": "not_null"},
            ],
        },
        "error_message_template": "Member name is incomplete: surname='{surname}', first_name='{first_name}'.",
    },
    {
        "rule_id": "AC-NIN-FORMAT",
        "description": "NIN must match the NIRA regex when present. DQA-O-02 tracks NIRA sign-off.",
        "severity": Severity.BLOCKING,
        "applicability_filter": {"entity": "member"},
        "expression": {
            "any_of": [
                {"field": "nin_value_str", "op": "is_null"},
                {"field": "nin_value_str", "op": "regex", "value": r"^(CM|CF)[A-Z0-9]{12}$"},
            ],
        },
        "error_message_template": "NIN '{nin_value_str}' does not match the NIRA format ^(CM|CF)[A-Z0-9]{{12}}$.",
    },
    {
        "rule_id": "AC-GPS-ACCURACY",
        "description": "GPS accuracy reading must be 10 metres or better when GPS is captured.",
        "severity": Severity.BLOCKING,
        "applicability_filter": {"entity": "household"},
        "expression": {
            "any_of": [
                {"field": "gps_accuracy_m", "op": "is_null"},
                {"field": "gps_accuracy_m", "op": "le", "value": 10},
            ],
        },
        "error_message_template": "GPS accuracy {gps_accuracy_m}m exceeds the 10m threshold; retry capture.",
    },
]


def seed() -> int:
    """Idempotent: re-running leaves the existing ACTIVE rule untouched."""
    created = 0
    for spec in RULES:
        existing = DqaRule.objects.filter(
            rule_id=spec["rule_id"], status=RuleStatus.ACTIVE,
        ).first()
        if existing:
            print(f"  {spec['rule_id']} already ACTIVE (v{existing.version}) — skipping")
            continue
        rule = DqaRule.objects.create(
            rule_id=spec["rule_id"],
            version=1,
            description=spec["description"],
            severity=spec["severity"],
            applicability_filter=spec["applicability_filter"],
            expression=spec["expression"],
            error_message_template=spec["error_message_template"],
            effective_from=date(2026, 1, 1),
            status=RuleStatus.DRAFT,
            author=AUTHOR,
        )
        submit_for_approval(rule)
        approve(rule, approver=APPROVER)
        print(f"  {spec['rule_id']} v{rule.version} -> ACTIVE  (author={AUTHOR}, approver={APPROVER})")
        created += 1
    return created


if __name__ == "__main__":
    n = seed()
    print(f"\nseeded {n} new rule(s); total ACTIVE rules: {DqaRule.objects.filter(status=RuleStatus.ACTIVE).count()}")
