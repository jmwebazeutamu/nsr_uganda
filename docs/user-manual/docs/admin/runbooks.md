# Runbooks

!!! info "Status"
    **Planned** — runbook directory exists at `/infrastructure/runbooks/` but the pages are mostly empty. Pilot-grade runbooks land in Sprint 7.

A runbook is a step-by-step recovery procedure. One per failure mode. This page indexes the runbooks that exist and lists the ones we know we need.

## Runbooks that exist

| File | Covers |
|---|---|
| `/infrastructure/runbooks/` is mostly empty | (Planned) |

## Runbooks we need (target Sprint 7)

| Runbook | Trigger | Owner |
|---|---|---|
| `audit-chain-break.md` | `security.AuditEvent` hash chain mismatch alert | SA + DPO |
| `connector-stuck.md` | A ConnectorRun has been in `pending_review` > 24 h | NSR Unit |
| `dqa-rule-rollback.md` | A bad DQA rule made it through dual-approval | DQA lead |
| `ddup-misjoin.md` | A merge merged two real people | DDUP lead + DPO |
| `keycloak-down.md` | Keycloak unreachable, operators locked out | SA |
| `db-failover.md` | Primary PostgreSQL unreachable | SA + NITA-U |
| `dr-restore.md` | Full disaster recovery from off-site backups | SA + NITA-U |
| `drs-extract-leak.md` | A partner reports receiving data outside their DSA scope | DPO + Partner liaison |
| `nin-pepper-rotation.md` | Scheduled or compromise-driven NIN pepper rotation | SA + DPO |

## Runbook template

```markdown
# Runbook — <Title>

## Trigger
What alert, dashboard signal, or user report fires this runbook.

## Severity
SEV-1 / SEV-2 / SEV-3.

## Roles
Who you wake up. Phone numbers in the SOPs binder, not here.

## Detection
How to confirm the problem is real. Commands to run.

## Containment
First action to limit blast radius.

## Diagnosis
Step-by-step root cause investigation.

## Resolution
The fix.

## Recovery
Bring service back to normal.

## Post-incident
Postmortem template, audit chain verification, DPIA update if personal data was exposed.
```

## Incident management

Until full SEV-1 process lands, treat incidents like this:

1. **Page the SA on call.** Phone tree in the SOPs binder.
2. **Open a ticket** in the issue tracker with `incident/` prefix.
3. **Copy the DPO** if personal data is touched or might be exposed.
4. **Write the postmortem** within 5 business days.

## Related

- [Observability](observability.md) — the alerts that trigger runbooks
- [DPIA and threat model](dpia-and-threat-model.md) — for incidents that touch personal data
- `/CLAUDE.md` — escalation rules per the project memory
