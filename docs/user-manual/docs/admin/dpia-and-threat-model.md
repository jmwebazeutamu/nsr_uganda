# DPIA and threat model

!!! info "Status"
    **Built and in use** — 19 sprint DPIA files and 1 threat model live. Live DPO sign-off workflow in the admin console is **Partial**.

The Data Protection and Privacy Act, 2019 (DPPA 2019) requires a DPIA for any processing that is likely to result in high risk to the rights and freedoms of individuals. The NSR MIS produces a DPIA for every sprint that touches personal data.

## Where DPIAs live

`/docs/dpia/` holds one file per sprint that touched personal data.

| File | Sprint(s) |
|---|---|
| `sprint_2_3_impacts.md` | S2, S3 |
| `sprint_5_6_impacts.md` | S5, S6 |
| `sprint_7_impacts.md` | S7 |
| `sprint_8_impacts.md` | S8 |
| `sprint_9_impacts.md` | S9 |
| `sprint_10_11_impacts.md` | S10, S11 |
| `sprint_12_impacts.md` | S12 |
| `sprint_13_impacts.md` | S13 |
| `sprint_14_impacts.md` | S14 |
| `sprint_15_impacts.md` | S15 |
| `sprint_16_impacts.md` | S16 |
| `sprint_17_18_impacts.md` | S17, S18 |
| `sprint_19_impacts.md` | S19 |
| `sprint_22_impacts.md` and `sprint_22_detail_entities_impacts.md` | S22 |
| `sprint_23_impacts.md` | S23 |
| `sprint_24_impacts.md` | S24 |
| `sprint_25_impacts.md` | S25 |
| `sprint_26_impacts.md` | S26 |

`/docs/dpia.md` is the consolidated top-level DPIA.

## When to file a DPIA

For each story, ask:

1. Does it create, read, or write personal data? If no, no DPIA needed.
2. Does it introduce a new processing purpose? If yes, full DPIA section.
3. Does it change retention, sharing, or pseudonymisation? If yes, full DPIA section.
4. Does it touch sensitive data (health, disability, child-headed status)? If yes, escalate to the DPO before merge.

The Definition of Done (per `/CLAUDE.md` §11.5) requires a DPIA impact entry for every personal-data story.

## DPIA template

Each sprint file follows this shape:

```markdown
# Sprint X — DPIA impacts

## Stories that touch personal data
- US-XXX — short description

## Per-story impact assessment

### US-XXX — short description
- **Purpose of processing**: ...
- **Lawful basis**: DPPA 2019 §<section>
- **Data categories**: ...
- **Subjects**: ...
- **Retention**: ...
- **Risks introduced**: ...
- **Mitigations applied**: ...
- **Residual risk**: low / medium / high
- **DPO sign-off**: pending / signed by <name> on <date>
```

## Threat model

`/docs/threat_model.md` holds the system-level threat model produced in the Sprint 0 workshop (per CLAUDE.md §11.4 item 10). Threats are tracked by ID (T1, T2, ...). Each links to the mitigations and the AuditEvent action that surfaces it.

| Threat | Mitigation today | Target sprint |
|---|---|---|
| T1 — Bulk personal-data exfiltration by a logged-in operator | Audit chain + ABAC | Anomaly detection in S9 |
| T2 — Connector credential theft | Fernet encryption at rest | KMS rotation in S8 |
| T3 — DDUP misjoin merging two real people | Dual-approval on the merge, side-by-side compare | Probabilistic tier-3 review in S5 |
| T4 — DSA scope drift (partner sees data outside their scope) | Partner-side ABAC, `validate_against_dsa` | Continuous monitoring in S9 |
| T5 — Audit-chain tamper | Postgres trigger enforces hash chain at INSERT | Off-site append-only mirror Planned S8 |

## Cross-references

| Story type | DPIA file to update | Other files |
|---|---|---|
| New DAT entity | Current sprint DPIA | Add to consolidated `/docs/dpia.md` |
| New DIH connector | Current sprint DPIA | Update DPA scope on the SourceSystem |
| New DRS field | Current sprint DPIA | Update DRS sensitivity badge in catalogue |
| New audit action | Current sprint DPIA | Add an example row to the threat model T1 mitigations table |

## Related

- ADR-0019 — Sensitive health encryption
- `/docs/audit/2026-05-21_source_of_truth_audit.md` — the most recent source-of-truth audit
- [Observability](observability.md) — the audit chain in operation
