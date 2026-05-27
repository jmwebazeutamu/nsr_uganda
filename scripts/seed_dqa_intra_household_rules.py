"""Seed the 8 INTRA_HOUSEHOLD DQA rules (US-S11-044).

Each rule is upserted as DRAFT (INACTIVE) — activation goes through
the Rule Editor's dual-approval workflow per the spec. The seed is
the bootstrap-once point that puts the rule shapes on disk; the
dual-approval audit trail is exercised from day one.

Rules:
  AC-HOH-EXISTS              block      exactly one head per household
  AC-HOH-AGE                 block      head must be >= 12 years old
  AC-HOH-AGE-CHILD-LED       flag       head 12..17 → child-headed flag
  AC-SPOUSE-PAIR             flag       at most one declared spouse (v1)
  AC-PARENT-AGE              flag       parent ≥ N years older than child
  AC-MEMBER-COUNT-MATCH      flag       roster size = reported size
  AC-DUPLICATE-MEMBER        block      no two members share NIN hash
  AC-DISABILITY-CONSISTENCY  flag       no disability detail when flag=false
  AC-ORPHAN-FLAG             flag       orphan flag set when both parents dead + age<18

Usage:
  .venv/bin/python scripts/seed_dqa_intra_household_rules.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import django

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nsr_mis.settings")
django.setup()

from apps.dqa.models import (  # noqa: E402, I001
    DqaRule,
    ExpressionType,
    RuleCategory,
    RuleScope,
    RuleStage,
    RuleStatus,
    Severity,
)


SEED_AUTHOR = "seed-bootstrap"

# Every rule applies at all three stages by default. The spec allows
# narrowing per-rule via Rule Editor before activation.
ALL_STAGES = [
    RuleStage.DIH_INGEST.value,
    RuleStage.DIH_PROMOTE.value,
    RuleStage.REGISTRY_POST_PROMOTE.value,
]


# ─────────────────────────────────────────────────────────────────────
# AC-HOH-EXISTS — exactly one head of household.

AC_HOH_EXISTS = {
    "rule_id": "AC-HOH-EXISTS",
    "description": (
        "Exactly one household member must be flagged as head "
        "(relationship_to_head == \"01\"). Blocks if count is zero or "
        "more than one — both surface as routine data-capture errors "
        "that the enumerator can fix at the parish office."
    ),
    "severity": Severity.BLOCK,
    "parameters": {"expected_count": 1, "head_code": "01"},
    "applies_to": {
        "fields": ["members.*.relationship_to_head"],
    },
    "expression": {
        "op": "count_where",
        "predicate": {"op": "eq", "args": [
            "$.relationship_to_head", "$parameters.head_code",
        ]},
        "_fail_when": {"op": "neq", "args": [
            "$", "$parameters.expected_count",
        ]},
    },
    "error_message_template": (
        "Exactly {expected_count} member must be flagged as Head; "
        "found {expression_result}."
    ),
    "message_template_i18n_key": "dqa.ac_hoh_exists.message",
    "test_fixtures": [
        {
            "input": {"members": [
                {"id": "01M1", "line_number": 1, "relationship_to_head": "01"},
                {"id": "01M2", "line_number": 2, "relationship_to_head": "02"},
            ]},
            "expected_outcome": "pass",
        },
        {
            "input": {"members": [
                {"id": "01M1", "line_number": 1, "relationship_to_head": "02"},
                {"id": "01M2", "line_number": 2, "relationship_to_head": "03"},
            ]},
            "expected_outcome": "fail",
        },
    ],
}


# ─────────────────────────────────────────────────────────────────────
# AC-HOH-AGE — head must be ≥ 12 years old.

AC_HOH_AGE = {
    "rule_id": "AC-HOH-AGE",
    "description": (
        "The head of household must be at least 12 years old. A "
        "younger 'head' is almost always a data-entry mistake — fix "
        "the relationship_to_head code or correct the age."
    ),
    "severity": Severity.BLOCK,
    "parameters": {"min_head_age": 12, "head_code": "01"},
    "applies_to": {
        "fields": [
            "members.*.relationship_to_head",
            "members.*.age_years",
        ],
    },
    "expression": {
        "op": "count_where",
        "predicate": {"op": "and", "args": [
            {"op": "eq", "args": [
                "$.relationship_to_head", "$parameters.head_code",
            ]},
            {"op": "lt", "args": [
                "$.age_years", "$parameters.min_head_age",
            ]},
        ]},
        "_fail_when": {"op": "gt", "args": ["$", 0]},
    },
    "error_message_template": (
        "Head of household must be at least {min_head_age} years old."
    ),
    "message_template_i18n_key": "dqa.ac_hoh_age.message",
    "test_fixtures": [
        {
            "input": {"members": [
                {"id": "01M1", "line_number": 1,
                 "relationship_to_head": "01", "age_years": 30},
            ]},
            "expected_outcome": "pass",
        },
        {
            "input": {"members": [
                {"id": "01M1", "line_number": 1,
                 "relationship_to_head": "01", "age_years": 9},
            ]},
            "expected_outcome": "fail",
        },
    ],
}


# ─────────────────────────────────────────────────────────────────────
# AC-HOH-AGE-CHILD-LED — head age 12..17 (child-headed household flag).

AC_HOH_AGE_CHILD_LED = {
    "rule_id": "AC-HOH-AGE-CHILD-LED",
    "description": (
        "Head of household between 12 and 17 inclusive — a "
        "child-headed household. Flagged for referral pathway "
        "review (UNICEF + MGLSD vulnerability protocol)."
    ),
    "severity": Severity.FLAG,
    "parameters": {
        "min_age": 12, "max_age_inclusive": 17, "head_code": "01",
    },
    "applies_to": {
        "fields": [
            "members.*.relationship_to_head",
            "members.*.age_years",
        ],
    },
    "expression": {
        "op": "count_where",
        "predicate": {"op": "and", "args": [
            {"op": "eq", "args": [
                "$.relationship_to_head", "$parameters.head_code",
            ]},
            {"op": "gte", "args": ["$.age_years", "$parameters.min_age"]},
            {"op": "lte", "args": [
                "$.age_years", "$parameters.max_age_inclusive",
            ]},
        ]},
        "_fail_when": {"op": "gt", "args": ["$", 0]},
    },
    "error_message_template": (
        "Child-headed household — head is between {min_age} and "
        "{max_age_inclusive}. Refer to UNICEF protocol."
    ),
    "message_template_i18n_key": "dqa.ac_hoh_age_child_led.message",
    "test_fixtures": [
        {
            "input": {"members": [
                {"id": "01M1", "line_number": 1,
                 "relationship_to_head": "01", "age_years": 15},
            ]},
            "expected_outcome": "fail",  # child-headed → flagged
        },
        {
            "input": {"members": [
                {"id": "01M1", "line_number": 1,
                 "relationship_to_head": "01", "age_years": 35},
            ]},
            "expected_outcome": "pass",
        },
    ],
}


# ─────────────────────────────────────────────────────────────────────
# AC-SPOUSE-PAIR — at most one declared spouse (v1).
# Strict pointer-check is a v2 follow-up once Member.spouse_line_number
# is captured by CAPI — see ADR-0022 follow-ups.

AC_SPOUSE_PAIR = {
    "rule_id": "AC-SPOUSE-PAIR",
    "description": (
        "At most one household member may be declared as the head's "
        "spouse (relationship_to_head == \"02\"). The strict "
        "pointer-back-to-spouse check is deferred until "
        "Member.spouse_line_number is captured by CAPI."
    ),
    "severity": Severity.FLAG,
    "parameters": {"max_count": 1, "spouse_code": "02"},
    "applies_to": {"fields": ["members.*.relationship_to_head"]},
    "expression": {
        "op": "count_where",
        "predicate": {"op": "eq", "args": [
            "$.relationship_to_head", "$parameters.spouse_code",
        ]},
        "_fail_when": {"op": "gt", "args": [
            "$", "$parameters.max_count",
        ]},
    },
    "error_message_template": (
        "More than {max_count} declared spouse(s) in this household "
        "(found {expression_result}). Reconcile relationship codes."
    ),
    "message_template_i18n_key": "dqa.ac_spouse_pair.message",
    "test_fixtures": [
        {
            "input": {"members": [
                {"id": "01M1", "line_number": 1, "relationship_to_head": "01"},
                {"id": "01M2", "line_number": 2, "relationship_to_head": "02"},
            ]},
            "expected_outcome": "pass",
        },
        {
            "input": {"members": [
                {"id": "01M1", "line_number": 1, "relationship_to_head": "01"},
                {"id": "01M2", "line_number": 2, "relationship_to_head": "02"},
                {"id": "01M3", "line_number": 3, "relationship_to_head": "02"},
            ]},
            "expected_outcome": "fail",
        },
    ],
}


# ─────────────────────────────────────────────────────────────────────
# AC-PARENT-AGE — each parent ≥ N years older than each linked child.

AC_PARENT_AGE = {
    "rule_id": "AC-PARENT-AGE",
    "description": (
        "For every member with a parent pointer "
        "(mother_line_number / father_line_number), the linked "
        "parent must be at least min_diff_years older. Members "
        "without parent pointers are skipped — the rule degrades "
        "gracefully until CAPI populates the pointers."
    ),
    "severity": Severity.FLAG,
    "parameters": {"min_diff_years": 12},
    "applies_to": {
        "fields": [
            "members.*.mother_line_number",
            "members.*.father_line_number",
            "members.*.age_years",
        ],
    },
    "expression": {
        "op": "for_each_member",
        "predicate": {"op": "or", "args": [
            # Mother branch — only when the pointer exists.
            {"op": "and", "args": [
                {"op": "not_null", "args": ["$.mother_line_number"]},
                {"op": "lt", "args": [
                    {"op": "sub", "args": [
                        {"op": "attr", "args": [
                            {"op": "lookup_member", "by": "line_number",
                             "value": "$.mother_line_number"},
                            "age_years",
                        ]},
                        "$.age_years",
                    ]},
                    "$parameters.min_diff_years",
                ]},
            ]},
            # Father branch.
            {"op": "and", "args": [
                {"op": "not_null", "args": ["$.father_line_number"]},
                {"op": "lt", "args": [
                    {"op": "sub", "args": [
                        {"op": "attr", "args": [
                            {"op": "lookup_member", "by": "line_number",
                             "value": "$.father_line_number"},
                            "age_years",
                        ]},
                        "$.age_years",
                    ]},
                    "$parameters.min_diff_years",
                ]},
            ]},
        ]},
        "_fail_when": {"op": "gt", "args": ["$", 0]},
    },
    "error_message_template": (
        "Linked parent must be at least {min_diff_years} years older "
        "than the child."
    ),
    "message_template_i18n_key": "dqa.ac_parent_age.message",
    "test_fixtures": [
        {
            "input": {"members": [
                {"id": "01M1", "line_number": 1, "age_years": 40},
                {"id": "01M2", "line_number": 2, "age_years": 10,
                 "mother_line_number": 1},
            ]},
            "expected_outcome": "pass",
        },
        {
            "input": {"members": [
                {"id": "01M1", "line_number": 1, "age_years": 18},
                {"id": "01M2", "line_number": 2, "age_years": 12,
                 "mother_line_number": 1},
            ]},
            "expected_outcome": "fail",
        },
    ],
}


# ─────────────────────────────────────────────────────────────────────
# AC-MEMBER-COUNT-MATCH — roster size = reported size.

AC_MEMBER_COUNT_MATCH = {
    "rule_id": "AC-MEMBER-COUNT-MATCH",
    "description": (
        "Roster member count must equal the operator-reported "
        "household size. Mismatch is usually an omitted roster entry — "
        "fix the roster, not the reported number."
    ),
    "severity": Severity.FLAG,
    "parameters": {},
    "applies_to": {
        "fields": ["reported_household_size", "members"],
    },
    "expression": {
        # count_where with always-true predicate = roster length.
        "op": "count_where",
        "predicate": {"op": "eq", "args": [1, 1]},
        "_fail_when": {"op": "neq", "args": [
            "$", "$reported_household_size",
        ]},
    },
    "error_message_template": (
        "Roster has {expression_result} member(s); reported "
        "household size doesn't match."
    ),
    "message_template_i18n_key": "dqa.ac_member_count_match.message",
    "test_fixtures": [
        {
            "input": {
                "reported_household_size": 2,
                "members": [
                    {"id": "01M1", "line_number": 1},
                    {"id": "01M2", "line_number": 2},
                ],
            },
            "expected_outcome": "pass",
        },
        {
            "input": {
                "reported_household_size": 3,
                "members": [
                    {"id": "01M1", "line_number": 1},
                    {"id": "01M2", "line_number": 2},
                ],
            },
            "expected_outcome": "fail",
        },
    ],
}


# ─────────────────────────────────────────────────────────────────────
# AC-DUPLICATE-MEMBER — no two members share NIN hash (v1: NIN-exact only).

AC_DUPLICATE_MEMBER = {
    "rule_id": "AC-DUPLICATE-MEMBER",
    "description": (
        "Two members in the same household must not share the same "
        "NIN. The fuzzy branch (name + DOB + sex) is deferred until "
        "the DDUP team confirms a name-normalisation spec."
    ),
    "severity": Severity.BLOCK,
    "parameters": {},
    "applies_to": {"fields": ["members.*.nin_hash"]},
    "expression": {
        "op": "duplicates_by",
        "field": "nin_hash",
        "_fail_when": {"op": "gt", "args": ["$", 0]},
    },
    "error_message_template": (
        "Duplicate NIN within this household — {expression_result} "
        "members collide. Reconcile before promotion."
    ),
    "message_template_i18n_key": "dqa.ac_duplicate_member.message",
    "test_fixtures": [
        {
            "input": {"members": [
                {"id": "01M1", "line_number": 1, "nin_hash": "abc"},
                {"id": "01M2", "line_number": 2, "nin_hash": "def"},
            ]},
            "expected_outcome": "pass",
        },
        {
            "input": {"members": [
                {"id": "01M1", "line_number": 1, "nin_hash": "abc"},
                {"id": "01M2", "line_number": 2, "nin_hash": "abc"},
            ]},
            "expected_outcome": "fail",
        },
    ],
}


# ─────────────────────────────────────────────────────────────────────
# AC-DISABILITY-CONSISTENCY — detail fields populated only if flag = yes.

AC_DISABILITY_CONSISTENCY = {
    "rule_id": "AC-DISABILITY-CONSISTENCY",
    "description": (
        "A member whose wg_disability_flag is False must not carry "
        "captured disability detail values. Catches the operator "
        "captured wg_seeing/wg_hearing/etc but forgot to set the "
        "flag (or vice versa)."
    ),
    "severity": Severity.FLAG,
    "parameters": {},
    "applies_to": {
        "fields": [
            "members.*.wg_disability_flag",
            "members.*.wg_seeing",
            "members.*.wg_hearing",
            "members.*.wg_walking",
            "members.*.wg_remembering",
            "members.*.wg_self_care",
            "members.*.wg_communicating",
        ],
    },
    "expression": {
        "op": "for_each_member",
        "predicate": {"op": "and", "args": [
            {"op": "eq", "args": ["$.wg_disability_flag", False]},
            {"op": "or", "args": [
                {"op": "not_null", "args": ["$.wg_seeing"]},
                {"op": "not_null", "args": ["$.wg_hearing"]},
                {"op": "not_null", "args": ["$.wg_walking"]},
                {"op": "not_null", "args": ["$.wg_remembering"]},
                {"op": "not_null", "args": ["$.wg_self_care"]},
                {"op": "not_null", "args": ["$.wg_communicating"]},
            ]},
        ]},
        "_fail_when": {"op": "gt", "args": ["$", 0]},
    },
    "error_message_template": (
        "Disability detail captured but wg_disability_flag is False. "
        "Reconcile the flag or clear the detail fields."
    ),
    "message_template_i18n_key": "dqa.ac_disability_consistency.message",
    "test_fixtures": [
        {
            "input": {"members": [
                {"id": "01M1", "line_number": 1,
                 "wg_disability_flag": False},
            ]},
            "expected_outcome": "pass",
        },
        {
            "input": {"members": [
                {"id": "01M1", "line_number": 1,
                 "wg_disability_flag": False, "wg_seeing": "03"},
            ]},
            "expected_outcome": "fail",
        },
    ],
}


# ─────────────────────────────────────────────────────────────────────
# AC-ORPHAN-FLAG — orphan_flag must be true when both parents dead and age<18.

AC_ORPHAN_FLAG = {
    "rule_id": "AC-ORPHAN-FLAG",
    "description": (
        "Members under 18 whose mother and father are both marked "
        "deceased must have orphan_flag = True. Drives the referral "
        "pathway for orphan care programmes."
    ),
    "severity": Severity.FLAG,
    "parameters": {"max_age": 18},
    "applies_to": {
        "fields": [
            "members.*.age_years",
            "members.*.mother_alive_flag",
            "members.*.father_alive_flag",
            "members.*.orphan_flag",
        ],
    },
    "expression": {
        "op": "for_each_member",
        "predicate": {"op": "and", "args": [
            {"op": "lt", "args": [
                "$.age_years", "$parameters.max_age",
            ]},
            {"op": "eq", "args": ["$.mother_alive_flag", False]},
            {"op": "eq", "args": ["$.father_alive_flag", False]},
            {"op": "neq", "args": ["$.orphan_flag", True]},
        ]},
        "_fail_when": {"op": "gt", "args": ["$", 0]},
    },
    "error_message_template": (
        "Member under {max_age} with both parents deceased "
        "must have orphan_flag = True."
    ),
    "message_template_i18n_key": "dqa.ac_orphan_flag.message",
    "test_fixtures": [
        {
            "input": {"members": [
                {"id": "01M1", "line_number": 1, "age_years": 10,
                 "mother_alive_flag": False, "father_alive_flag": False,
                 "orphan_flag": True},
            ]},
            "expected_outcome": "pass",
        },
        {
            "input": {"members": [
                {"id": "01M1", "line_number": 1, "age_years": 10,
                 "mother_alive_flag": False, "father_alive_flag": False,
                 "orphan_flag": False},
            ]},
            "expected_outcome": "fail",
        },
    ],
}


# ─────────────────────────────────────────────────────────────────────
# Driver

ALL_RULES = [
    AC_HOH_EXISTS,
    AC_HOH_AGE,
    AC_HOH_AGE_CHILD_LED,
    AC_SPOUSE_PAIR,
    AC_PARENT_AGE,
    AC_MEMBER_COUNT_MATCH,
    AC_DUPLICATE_MEMBER,
    AC_DISABILITY_CONSISTENCY,
    AC_ORPHAN_FLAG,
]


def seed() -> int:
    """Upsert each rule as v1 DRAFT. Re-running is idempotent: existing
    rule_id rows are left alone (any active version stays active; any
    draft stays as-is). Activation goes through the Rule Editor's
    dual-approval workflow.
    """
    created = 0
    for spec in ALL_RULES:
        existing = DqaRule.objects.filter(rule_id=spec["rule_id"]).first()
        if existing:
            print(
                f"  {spec['rule_id']} already seeded "
                f"(v{existing.version} {existing.status}) — skipping"
            )
            continue
        DqaRule.objects.create(
            rule_id=spec["rule_id"],
            version=1,
            description=spec["description"],
            severity=spec["severity"],
            category=RuleCategory.INTRA_HOUSEHOLD,
            scope=RuleScope.HOUSEHOLD,
            expression_type=ExpressionType.DSL,
            stages=ALL_STAGES,
            parameters=spec["parameters"],
            applies_to=spec["applies_to"],
            expression=spec["expression"],
            test_fixtures=spec.get("test_fixtures", []),
            applicability_filter={"entity": "household"},
            error_message_template=spec["error_message_template"],
            message_template_i18n_key=spec["message_template_i18n_key"],
            status=RuleStatus.DRAFT,
            author=SEED_AUTHOR,
        )
        print(
            f"  {spec['rule_id']} v1 DRAFT "
            f"(severity={spec['severity']}, scope=household)"
        )
        created += 1
    return created


if __name__ == "__main__":
    n = seed()
    total = DqaRule.objects.filter(category=RuleCategory.INTRA_HOUSEHOLD).count()
    print(f"\nseeded {n} new rule(s); total INTRA_HOUSEHOLD rules: {total}")
