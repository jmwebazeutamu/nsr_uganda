# SEC — Security

!!! info "Status"
    **Built and in use** — audit emitter, hash-chain trigger, read-side mixin with poll de-duplication, ABAC, the role catalogue, NIN encryption + hash, system checks, integrity helpers. Revised 25 September 2026.

SEC is the cross-cutting module every other module depends on. Audit, ABAC, encryption.

## What it does

Provides the helpers everything else uses. Emits `AuditEvent` rows on every personal-data read and write. Enforces the hash chain via a Postgres trigger. Narrows querysets by operator scope. Encrypts NIN at rest and computes the join hash. Surfaces fail-closed Django system checks.

## Where it lives

| Path | What |
|---|---|
| `apps/security/` | Django app |
| `apps/security/audit.py` | `emit(action, entity, ...)` |
| `apps/security/abac.py` | `scope_q_for_field(user, field)`, `user_can_access_household(user, id)` |
| `apps/security/audit_views.py` | `AuditReadMixin` — emits on every read, and de-duplicates polls |
| `apps/security/roles.py` | the role catalogue (ADR-0028) — one definition, from which the Django Groups and the Keycloak realm are both derived |
| `apps/security/encryption.py` | NIN encrypt / decrypt helpers |
| `apps/security/hashing.py` | NIN peppered hash |
| `apps/security/integrity.py` | Chain verification helpers |
| `apps/security/checks.py` | Fail-closed system checks |
| `/api/v1/security/audit-events/` | Audit reader (DPO) |

## Key entities

| Entity | Columns that matter |
|---|---|
| `AuditEvent` | `id`, `occurred_at`, `actor_id`, `actor_kind`, `action`, `entity_type`, `entity_id`, `field_changes`, `reason`, `purpose`, `ip_address`, `user_agent`, `prev_hash`, `self_hash` |
| `OperatorScope` | operator → (scope level, scope code) |

!!! warning "Two column names on this page were wrong"
    It said `row_hash` and `created_at`. They are **`self_hash`** and
    **`occurred_at`**. If you have a query or a report built from the
    old names it has never worked. Corrected 25 September 2026.

## Reads are audited — and polls are folded together

`AuditReadMixin` writes an `AuditEvent` on every read of personal data:
`read` on a detail route, `list_read` on a list.

Taken literally that buries the chain. The console polls five endpoints
for its sidebar badges about every thirty seconds, and on this database
that produced **124,285 of 137,187 audit rows — 91% of the chain was
one browser tab counting things.**

So an identical repeat read inside a five-minute window is folded into
the first one:

| | |
|---|---|
| Window | `AUDIT_LIST_READ_DEDUPE_SECONDS`, default 300 |
| Matched on | actor + entity type + the stored reason (which carries the request's filters) |
| Always written | the first read in each window |
| Never folded | a list request carrying a filter outside the audited set — that is a different read |

De-duplicated **server-side**, deliberately. A client header saying "do
not audit this one" would let any caller opt out of the record of their
own access.

Single-record reads are folded only where a surface is re-entered as
somebody moves around — the GRM case chain is the one that opts in. An
ordinary `retrieve` is a deliberate act and is never folded.

## System checks

| Check ID | Triggers |
|---|---|
| `security.E001` | `NSR_NIN_PEPPER` still on dev default in production |
| `security.E002` | `NSR_DATA_KEY` still on dev default in production |
| `security.E003` | `DJANGO_SECRET_KEY` still on dev default in production |
| `security.E004` | Non-Postgres `DATABASE_URL` in production |
| `security.E005` | The Keycloak realm export and `roles.py` disagree, or the export cannot be read |
| `security.E006` | A viewset declares an access purpose that is not in the ConsentPurpose catalogue — do not start a second vocabulary beside the consent one |
| `security.W001` | A role in the catalogue has no Django Group — run `manage.py migrate security` |
| `security.W007` | A non-DEBUG deployment is on a discarding email backend |
| `security.W008` | `DEFAULT_FROM_EMAIL` is not the mailbox the relay will let you send as |

## ADRs

- [ADR-0002](../appendices/adrs.md) — Identifier and encryption strategy
- [ADR-0006](../appendices/adrs.md) — Keycloak realm design
- [ADR-0019](../appendices/adrs.md) — Sensitive health encryption
- [ADR-0026](../appendices/adrs.md) — Multi-level ABAC geographic scope
- [ADR-0028](../appendices/adrs.md) — One role catalogue
- [ADR-0029](../appendices/adrs.md) — Serialising audit-chain appends

## Stories

US-063, US-064, US-065, US-066, US-067, US-068, US-071, US-072.
