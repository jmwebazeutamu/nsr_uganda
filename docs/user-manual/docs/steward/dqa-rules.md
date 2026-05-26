# DQA Rule Editor

!!! info "Status"
    **Built and in use** — rule CRUD, rule preview, dual-approval, and rule evaluation on ingest are live (US-076, US-077, US-078, US-079). The Rule Editor admin surface follows [ADR-0009-dqa](../appendices/adrs.md).

The DQA engine decides whether a record can promote. You author the rules.

## Rule lifecycle

```
draft → pending_approval → active → superseded
                      ↘ rejected
```

A rule starts as `draft`. You submit it for approval. A different operator approves it. It becomes `active`. When you replace it, the old version becomes `superseded` and the new one becomes `active`.

The system enforces:

- **Author ≠ approver** (`apps.dqa.services.approve` rejects same-actor approvals).
- **No editing an active rule**. To change it, create a new version, submit, and approve. The old version supersedes when the new one activates.

## The rule model

| Field | Meaning |
|---|---|
| `rule_id` | Stable code, e.g. `AC-MANDATORY-MEMBER-NAME` |
| `version` | Auto-incremented per rule_id |
| `severity` | `blocking` (cannot promote) or `warning` (promote with acknowledgement) |
| `module` | The module the rule applies to (`DAT`, `DIH`, `UPD`, ...) |
| `expression` | The rule body (see below) |
| `message_en` and `message_lg` | What the reviewer sees, in English and Luganda |
| `effective_from` | When the rule starts firing |
| `status` | `draft`, `pending_approval`, `active`, `superseded`, `rejected` |

## Rule expression

Rules are evaluated against the staged record dictionary (before promotion). The Sprint 0 rules use simple Python expressions; richer DSL is Planned (US-080).

| Rule ID | Severity | Expression |
|---|---|---|
| `AC-MANDATORY-MEMBER-NAME` | blocking | every required field in the member row is non-empty |
| `AC-NIN-FORMAT` | blocking | `re.match(r'^(CM\|CF)[A-Z0-9]{12}$', nin)` |
| `AC-GPS-ACCURACY` | blocking | `gps_accuracy_m <= 10` |

## Authoring a new rule

In the console:

1. Open the **DQA Rule Editor**. Screen: `/design/v0.1/screens/screens-admin-workflow-dqa.jsx → AdminWorkflowDqa`.
2. Click **New rule**.
3. Fill in `rule_id`, `module`, `severity`, both messages, the expression.
4. Use **Preview** to dry-run the rule against a sample staged record.
5. Click **Submit for approval**. The rule moves to `pending_approval`.
6. Tell a different DQA officer to approve it.

From a script:

```bash
python manage.py shell
```
```python
from apps.dqa.services import submit_for_approval, approve
from apps.dqa.models import DqaRule, Severity, RuleStatus

r = DqaRule.objects.create(
    rule_id="AC-DOB-PLAUSIBLE",
    version=1,
    module="DAT",
    severity=Severity.BLOCKING,
    expression="member.dob >= date(1900,1,1) and member.dob <= today()",
    message_en="Date of birth is outside the plausible range",
    message_lg="Olunaku lw'okuzaalibwa terikkirizibwa",
    effective_from=date.today(),
    status=RuleStatus.DRAFT,
    author="author-username",
)
submit_for_approval(r, actor="author-username", reason="initial draft")
# different operator:
approve(r, actor="approver-username", reason="reviewed and ready")
```

## Approving a rule

In the console:

1. Open the **Pending approvals** tab.
2. Read the rule, the expression, the message, the preview output.
3. Type a reason (e.g. "Matches NIRA spec v3.2").
4. Click **Approve** or **Reject**. Approval is rejected if you are the rule's author.

Approval writes one `AuditEvent` with action `dqa_rule_approved`.

## Where the rule fires

- **DIH staging**: every connector run evaluates active rules. A `blocking` failure quarantines the record. A `warning` lets the record continue, with the warning attached for steward visibility.
- **UPD review**: the same rules re-evaluate against the proposed new state before commit.
- **CAPI tablet**: a subset of rules (those marked `client_side_safe`) ship to the tablet so the enumerator sees errors live, not at sync.

## Rule pack rebuild

When the questionnaire version changes (US-119), the rule pack rebuilds automatically. The fan-out: questionnaire activation → MappingRule draft → DqaRule refresh → connector run reload. This is Planned for S20+ (US-116 to US-120 not started).

## Related

- [DQA Violations Dashboard](dqa-violations.md)
- [DIH review queue](dih-review-queue.md)
- ADR-0009-dqa — Rule Editor UI
- [DAT-DQA module reference](../modules/dat-dqa.md)
