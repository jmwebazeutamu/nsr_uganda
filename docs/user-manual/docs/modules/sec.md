# SEC — Security

!!! info "Status"
    **Built and in use** — audit emitter, hash-chain trigger, read-side middleware, ABAC, NIN encryption + hash, system checks, integrity helpers.

SEC is the cross-cutting module every other module depends on. Audit, ABAC, encryption.

## What it does

Provides the helpers everything else uses. Emits `AuditEvent` rows on every personal-data read and write. Enforces the hash chain via a Postgres trigger. Narrows querysets by operator scope. Encrypts NIN at rest and computes the join hash. Surfaces fail-closed Django system checks.

## Where it lives

| Path | What |
|---|---|
| `apps/security/` | Django app |
| `apps/security/audit.py` | `emit(action, entity, ...)` |
| `apps/security/abac.py` | `scope_q_for_field(field, user)` |
| `apps/security/encryption.py` | NIN encrypt / decrypt helpers |
| `apps/security/hashing.py` | NIN peppered hash |
| `apps/security/integrity.py` | Chain verification helpers |
| `apps/security/checks.py` | Fail-closed system checks |
| `/api/v1/security/audit-events/` | Audit reader (DPO) |

## Key entities

- `AuditEvent` — id, actor, action, entity, entity_id, reason, ip, ua, prev_hash, row_hash, created_at
- `OperatorScope` — operator → (level, scope_code) attribute(s)

## System checks

| Check ID | Triggers |
|---|---|
| `security.E001` | `NSR_NIN_PEPPER` still on dev default in production |
| `security.E002` | `NSR_DATA_KEY` still on dev default in production |
| `security.E003` | `DJANGO_SECRET_KEY` still on dev default in production |
| `security.E004` | Non-Postgres `DATABASE_URL` in production |

## ADRs

- [ADR-0002](../appendices/adrs.md) — Identifier and encryption strategy
- [ADR-0006](../appendices/adrs.md) — Keycloak realm design
- [ADR-0019](../appendices/adrs.md) — Sensitive health encryption

## Stories

US-063, US-064, US-065, US-066, US-067, US-068, US-071, US-072.
