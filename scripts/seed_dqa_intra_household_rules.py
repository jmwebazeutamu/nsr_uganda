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
  .venv/bin/python scripts/seed_dqa_intra_household_rules.py --revise

`--revise` is for an environment that already has these rules ACTIVE and
whose definitions here have since changed. It authors the new definition
as the next version, DRAFT, parented to the current one, and submits it
for approval. It approves nothing and never edits an ACTIVE row in
place: an active rule is an approved artefact, so the audit chain has to
show a supersession rather than a mutation, and the approver has to be
someone other than its author (apps/dqa/services.approve).
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

# ─────────────────────────────────────────────────────────────────────
# How a canonical payload designates the head of household.
#
# Every connector normalises the head to `is_head: True` and blanks that
# member's own relationship code, because a head's relationship to
# themselves is not a question the questionnaire asks — see
# `apps/ingestion_hub/connectors/kobo.py` ("" if is_head else …), and
# the same line in nusaf.py and pdm.py. The registry agrees:
# `Household.clean()` accepts "" or "01" on the head member, because the
# designation is the `head_member` FK, not the code.
#
# The three head rules below originally matched on
# `relationship_to_head == "01"` alone — a shape no connector has ever
# produced. The effect was total: on the dev registry, 367 staged heads
# carried `is_head: True` and a blank code, none carried "01", and
# AC-HOH-EXISTS therefore blocked every record in the queue with
# "Exactly 1 member must be flagged as Head; found 0" while the roster
# beside it displayed a head. The rules' own test fixtures used the
# coded shape, so they passed against a payload the system never builds.
#
# Accept either signal: the canonical flag, or the code from a source
# that supplies one. `_head_predicate()` returns a fresh copy so the
# three specs never share a mutable dict.
def _head_predicate() -> dict:
    return {
        "op": "or",
        "args": [
            {"op": "eq", "args": ["$.is_head", True]},
            {"op": "eq", "args": [
                "$.relationship_to_head", "$parameters.head_code",
            ]},
        ],
    }


AC_HOH_EXISTS = {
    "rule_id": "AC-HOH-EXISTS",
    "description": (
        "Exactly one household member must be designated head — either "
        "the canonical `is_head` flag every connector sets, or "
        "relationship_to_head == \"01\" from a source that codes it. "
        "Blocks if the count is zero or more than one — both surface as "
        "routine data-capture errors the enumerator can fix at the "
        "parish office."
    ),
    "severity": Severity.BLOCK,
    "parameters": {"expected_count": 1, "head_code": "01"},
    "applies_to": {
        "fields": ["members.*.is_head", "members.*.relationship_to_head"],
    },
    "expression": {
        "op": "count_where",
        "predicate": _head_predicate(),
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
            # The shape every connector actually emits: flagged head,
            # blank code. This is the fixture whose absence let the
            # rule ship broken.
            "input": {"members": [
                {"id": "01M1", "line_number": 1, "is_head": True,
                 "relationship_to_head": ""},
                {"id": "01M2", "line_number": 2, "is_head": False,
                 "relationship_to_head": "02"},
            ]},
            "expected_outcome": "pass",
        },
        {
            # A source that codes the head instead of flagging it.
            "input": {"members": [
                {"id": "01M1", "line_number": 1, "relationship_to_head": "01"},
                {"id": "01M2", "line_number": 2, "relationship_to_head": "02"},
            ]},
            "expected_outcome": "pass",
        },
        {
            "input": {"members": [
                {"id": "01M1", "line_number": 1, "is_head": False,
                 "relationship_to_head": "02"},
                {"id": "01M2", "line_number": 2, "is_head": False,
                 "relationship_to_head": "03"},
            ]},
            "expected_outcome": "fail",
        },
        {
            # Two heads is as wrong as none, and is what a merge or a
            # re-capture tends to produce.
            "input": {"members": [
                {"id": "01M1", "line_number": 1, "is_head": True,
                 "relationship_to_head": ""},
                {"id": "01M2", "line_number": 2, "is_head": True,
                 "relationship_to_head": ""},
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
        "the head designation or correct the age."
    ),
    "severity": Severity.BLOCK,
    "parameters": {"min_head_age": 12, "head_code": "01"},
    "applies_to": {
        "fields": [
            "members.*.is_head",
            "members.*.relationship_to_head",
            "members.*.age_years",
        ],
    },
    "expression": {
        "op": "count_where",
        "predicate": {"op": "and", "args": [
            _head_predicate(),
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
        {
            # Connector shape: flagged head, blank code, under age.
            "input": {"members": [
                {"id": "01M1", "line_number": 1, "is_head": True,
                 "relationship_to_head": "", "age_years": 9},
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
            "members.*.is_head",
            "members.*.relationship_to_head",
            "members.*.age_years",
        ],
    },
    "expression": {
        "op": "count_where",
        "predicate": {"op": "and", "args": [
            _head_predicate(),
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
            # Connector shape: flagged head, blank code, 15 years old.
            "input": {"members": [
                {"id": "01M1", "line_number": 1, "is_head": True,
                 "relationship_to_head": "", "age_years": 15},
            ]},
            "expected_outcome": "fail",
        },
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

# ─────────────────────────────────────────────────────────────────────
# OPEN — this rule checks for a contradiction the pipeline cannot
# produce, and is deliberately left DRAFT until MGLSD decides what it
# should check instead.
#
# It reads `wg_disability_flag` and `wg_seeing`/`wg_hearing`/… on the
# member. The canonical payload has neither: D3-D8 land in the member's
# `health` section as `seeing`, `hearing`, `walking`, `remembering`,
# `self_care`, `communicating` (see kobo.py and
# update_workflow.MEMBER_PAYLOAD_FIELD_PATHS), and the flag is not a
# captured field at all — `Disability.save()` computes it from those
# values, True when any is "03" (a lot of difficulty) or "04" (cannot
# do at all).
#
# So the flag cannot disagree with the detail: it is derived from it.
# Repointing the paths would make the rule run and find nothing.
#
# The check the questionnaire does imply is a different one: D3-D8 is
# asked of members aged 2 and above, so WG detail on a younger member
# is the real inconsistency. That is a rule change, not a path fix, and
# it needs the DQA owner's sign-off.
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

# ─────────────────────────────────────────────────────────────────────
# OPEN — `orphan_flag` has no writer, so this rule currently compares a
# captured value against a column nothing fills.
#
# The questionnaire asks C12 and C13 (is the biological mother/father
# alive) but never asks whether a member is an orphan; `Member.
# orphan_flag` is nullable and no connector or promote path sets it.
# Deriving it — both parents not alive, member under 18 — is a
# defensible reading, but who counts as an orphan is a programme
# eligibility definition, so MGLSD owns it rather than this seed.
#
# C12-C15 now reach the registry (they were dropped by the Kobo
# mapping until 2026-09-20), so the parental half of this rule has real
# data behind it for the first time.
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


#: Fields a revision may change. Identity (rule_id), lifecycle
#: (status/approved_by) and provenance (author, parent) are not
#: revisable — a change to those is a different operation.
REVISABLE_FIELDS = (
    "description", "severity", "parameters", "applies_to", "expression",
    "test_fixtures", "error_message_template", "message_template_i18n_key",
)


def _differs(rule: DqaRule, spec: dict) -> list[str]:
    """Field names where the stored rule and the seeded spec disagree."""
    changed = []
    for field in REVISABLE_FIELDS:
        if field not in spec:
            continue
        if getattr(rule, field) != spec[field]:
            changed.append(field)
    return changed


def revise(actor: str = SEED_AUTHOR) -> int:
    """Author a new DRAFT version of every rule whose definition changed.

    Returns the number of versions authored. Prints one line per rule so
    the operator can see what is now waiting for approval.
    """
    from apps.dqa.services import submit_for_approval

    authored = 0
    for spec in ALL_RULES:
        latest = (
            DqaRule.objects.filter(rule_id=spec["rule_id"])
            .order_by("-version").first()
        )
        if latest is None:
            print(f"  {spec['rule_id']} not seeded yet — run without --revise")
            continue
        changed = _differs(latest, spec)
        if not changed:
            print(f"  {spec['rule_id']} v{latest.version} matches — nothing to do")
            continue
        if latest.status == RuleStatus.PENDING_APPROVAL:
            # Somebody is already reviewing this one. Authoring another
            # version underneath a pending review would mean approving a
            # diff nobody read.
            print(
                f"  {spec['rule_id']} v{latest.version} is PENDING_APPROVAL "
                f"— leaving it alone (changed: {', '.join(changed)})"
            )
            continue
        if latest.status == RuleStatus.DRAFT:
            # Never approved, so there is nothing to supersede.
            for field in changed:
                setattr(latest, field, spec[field])
            latest.save(update_fields=[*changed, "updated_at"])
            submit_for_approval(latest, actor=actor)
            print(
                f"  {spec['rule_id']} v{latest.version} DRAFT updated + "
                f"submitted ({', '.join(changed)})"
            )
            authored += 1
            continue

        new_version = DqaRule.objects.create(
            rule_id=latest.rule_id,
            version=latest.version + 1,
            parent_rule=latest,
            category=latest.category,
            scope=latest.scope,
            expression_type=latest.expression_type,
            stages=latest.stages,
            applicability_filter=latest.applicability_filter,
            status=RuleStatus.DRAFT,
            author=actor,
            **{field: spec[field] for field in REVISABLE_FIELDS if field in spec},
        )
        submit_for_approval(new_version, actor=actor)
        print(
            f"  {spec['rule_id']} v{new_version.version} DRAFT authored from "
            f"v{latest.version} {latest.status} + submitted "
            f"({', '.join(changed)})"
        )
        authored += 1
    return authored


if __name__ == "__main__":
    if "--revise" in sys.argv:
        count = revise()
        print(
            f"\nauthored {count} revision(s), all PENDING_APPROVAL.\n"
            "Nothing is live yet: approve them in the Rule Editor "
            "(Admin > Workflow > DQA rules). The approver must not be "
            f"{SEED_AUTHOR!r}."
        )
        sys.exit(0)
    n = seed()
    total = DqaRule.objects.filter(category=RuleCategory.INTRA_HOUSEHOLD).count()
    print(f"\nseeded {n} new rule(s); total INTRA_HOUSEHOLD rules: {total}")
