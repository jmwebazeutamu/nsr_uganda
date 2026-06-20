# DQA Rule Editor

!!! info "Status"
    **Built and in use** — rule CRUD, real Run preview against the live registry, dual-approval lifecycle, Clone/Submit/Approve/Reject/Retire all wired (US-076, US-077, US-078, US-079, US-S11-044). Backed by `apps/dqa/services.py` + `apps/admin_console/workflow_api.py`. The screen lives at Admin Console → **Workflow → DQA rules**.

The DQA engine decides whether a record can promote, gets flagged for review, or is silently logged. You author the rules.

## Rule lifecycle

```
draft → pending_approval → active → retired
                      ↘ rejected
```

A rule starts as `draft`. You submit it for approval. A different operator approves it. It becomes `active`. When you replace it, the old version is auto-superseded when the new one activates; you can also explicitly **Retire** an active version.

The system enforces:

- **Author ≠ approver** (`apps.dqa.services.approve` returns 409 on same-actor approvals).
- **No editing an active rule.** Use **Clone as draft** to start a new version, edit it, and walk it through the lifecycle.
- **Note required on approve, reason required on reject.** Both are written to the audit chain.

## Severity vocabulary

Four severities decide what happens when the rule fails:

| Severity | Behaviour |
|---|---|
| `block` | Refuses promotion at `dih_promote`. The staged record stays in the queue until the failure is resolved. |
| `reject_with_override` | Refuses promotion unless the operator supplies an explicit override reason (audited). |
| `flag` | Promotes the record but emits a `dqa.household.flag` AuditEvent so the UPD reactor opens a review case. |
| `info` | Logged only — no abort, no review case. Useful for soft signals. |

Legacy aliases (`blocking` → `block`, `warning` → `flag`) still parse, but new rules should use the new vocabulary.

## The rule model

| Field | Meaning |
|---|---|
| `rule_id` | Stable code, e.g. `AC-MEMBER-AGE-MAX` |
| `version` | Auto-incremented per `rule_id` |
| `severity` | One of `block` / `reject_with_override` / `flag` / `info` |
| `applicability_filter` | e.g. `{"entity": "member"}` for member-scope rules |
| `expression` | The rule body (DSL — see below) |
| `error_message_template` | Rendered against the failing record; shown to reviewers |
| `effective_from` | When the rule starts firing |
| `status` | `draft`, `pending_approval`, `active`, `retired`, `rejected` |

## Active rule pack (as of this snapshot)

### Legacy entity-filtered (`apps.dqa.engine`)

| Rule ID | Severity | Scope | What it checks |
|---|---|---|---|
| `AC-MANDATORY-MEMBER-NAME` | block | member | surname + first_name both present |
| `AC-NIN-FORMAT` | block | member | `^(CM|CF)[A-Z0-9]{12}$` when present |
| `AC-GPS-ACCURACY` | block | household | `gps_accuracy_m ≤ 10` when GPS is captured |
| `AC-MEMBER-AGE-MAX` | flag | member | `today() − date_of_birth ≤ 120 years` (any older → flag) |

### Intra-household (`apps.dqa.household_evaluator`, seeded DRAFT)

| Rule ID | Severity | What it checks |
|---|---|---|
| `AC-HOH-EXISTS` | block | Exactly one head per household |
| `AC-HOH-AGE` | block | Head ≥ 12 years old |
| `AC-HOH-AGE-CHILD-LED` | flag | Head < 18 — child-led household, surface for review |
| `AC-SPOUSE-PAIR` | flag | Spouse relation symmetry |
| `AC-PARENT-AGE` | flag | Parent ≥ 12 years older than child |
| `AC-MEMBER-COUNT-MATCH` | flag | Reported household size matches roster length |
| `AC-DUPLICATE-MEMBER` | block | No duplicate NIN within a household |
| `AC-DISABILITY-CONSISTENCY` | flag | WG-SS responses internally consistent |
| `AC-ORPHAN-FLAG` | flag | Orphan flag agrees with parental fields |

The intra-household rules ship as DRAFT so you exercise the dual-approval flow when activating them.

## Rule expression DSL

The legacy engine reads expressions like:

```json
{
  "any_of": [
    {"field": "date_of_birth", "op": "is_null"},
    {"field": "date_of_birth", "op": "age_le", "value": 120}
  ]
}
```

Operators available: `not_null`, `is_null`, `eq`, `neq`, `regex`, `gt`, `lt`, `ge`, `le`, `between`, `in`, `not_in`, `accuracy_le`, `age_le`, `count_eq`, `count_neq`, `references_existing`, `cross_field_eq`. Composites: `all_of`, `any_of`.

`age_le` is the dates-friendly comparator: it accepts a `DateField`, datetime, or ISO-8601 string and computes years against `today()` at evaluation time — so an active "max age 120" rule keeps catching cohorts as they age, without needing a re-seed.

Intra-household rules use a richer DSL — see `apps/dqa/household_evaluator.py` for the operator surface (`count_where`, `for_each_member`, aggregate refs).

## Changing the severity of an active rule

Active rules are immutable. The flow to flip e.g. `AC-MEMBER-AGE-MAX` from FLAG to BLOCK:

1. Open the rule. Top-right → **Clone as draft**. Backend: `POST /api/v1/admin/workflow/dqa/rules/{rule_id}/clone/`. Returns a new DRAFT at v+1.
2. From the rules list, filter `status = draft` and open the new version.
3. The Severity cell renders as a dropdown on DRAFT rules. Pick the new severity. Backend: `PATCH /api/v1/admin/workflow/dqa/rules/{rule_id}/` with `{severity: "block"}`.
4. Click **Submit for approval**. Backend: `POST .../v{version}/submit/`. No body required.
5. A **different** operator opens the rule, clicks **Approve & activate**, supplies the required approval note in the in-app modal. Backend: `POST .../v{version}/sign/` with `{note}`. The new version goes ACTIVE; the prior version is auto-superseded.

## Running preview

The **Run preview** button on a rule's Preview tab sweeps the live registry to estimate fail rate before activation.

- Sweep target: **the social registry (`Household.objects`)**, not DIH. DIH staging is transient; the population at risk is the 12 M households already in DAT.
- Sample: deterministic `ORDER BY id LIMIT 1000`. Two consecutive runs against the same snapshot return identical counts + failing IDs.
- The preview run row records the sample size, pass/fail counts, and up to 10 failing household IDs. **No PII is persisted** — only IDs and counts. `DqaRulePreviewRun` is the audit table.

Endpoint: `POST /api/v1/admin/workflow/dqa/rules/{rule_id}/preview/` with `{sample_size: 1000}`.

## Where the rule fires (and what gets emitted)

| Stage | Engine path | Aborts? | Audit events |
|---|---|---|---|
| `dih_ingest` | both | never | `dqa.household.flag` if FLAG severity fails; `DqaResult` row per failure regardless |
| `dih_promote` | intra-household only | `block` aborts; `reject_with_override` aborts unless overridden | `dqa.household.override` on accepted override |
| `registry_post_promote` | both | never | `dqa.household.flag` on FLAG-severity failure (since 2026-05-30); `rules_re_evaluated` per CR commit |

The UPD reactor listens on `dqa.household.flag` and opens a household review case for the relevant rule code list. Both ingest and post-commit paths emit the same shape, so a FLAG rule covers a record whether the violation entered via a connector or via a UPD edit.

## Authoring a new rule from a script

```bash
python manage.py shell
```

```python
from datetime import date
from apps.dqa.services import submit_for_approval, approve
from apps.dqa.models import DqaRule, Severity, RuleStatus

r = DqaRule.objects.create(
    rule_id="AC-DOB-PLAUSIBLE",
    version=1,
    description="Date of birth in plausible range",
    severity=Severity.FLAG,
    applicability_filter={"entity": "member"},
    expression={"all_of": [
        {"field": "date_of_birth", "op": "not_null"},
        {"field": "date_of_birth", "op": "age_le", "value": 120},
    ]},
    error_message_template="DOB {date_of_birth} is implausible.",
    effective_from=date.today(),
    status=RuleStatus.DRAFT,
    author="author-username",
)
submit_for_approval(r, actor="author-username")
# Different operator:
approve(r, approver="approver-username", note="reviewed; ready for activation")
```

For bulk seeds, see `scripts/seed_dqa_rules.py` (legacy entity-filtered) and
`scripts/seed_dqa_intra_household_rules.py` (intra-household).

## Mock-only rules

The design console screen ships a handful of design-only rules (e.g. `AC-VITAL-MARRIAGE-AGE`) that aren't seeded into the database. When you open one, a yellow banner reads:

> **Design-preview rule.** This rule isn't in the live database, so lifecycle actions are disabled. Author it via the Rule Editor (or seed it) to make it real.

All lifecycle buttons grey out and the severity dropdown reverts to a read-only chip. To make a mock-rule real, add it to `scripts/seed_dqa_rules.py` (or compose a new draft in the Rule Editor) and re-run the seeder.

## Related

- [DQA Violations Dashboard](dqa-violations.md)
- [DIH review queue](dih-review-queue.md)
- [UPD reviewer](upd-review.md) — consumes `dqa.household.flag` events
- ADR-0009-dqa — Rule Editor UI
- [DAT-DQA module reference](../modules/dat-dqa.md)
