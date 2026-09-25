# DAT — Data Management

!!! info "Status"
    **Built and in use** — Household, Member, versioning, audit trigger, detail entities. The canonical store for every promoted household.

DAT is the canonical store for the National Social Registry. Every other module reads from DAT or writes to DAT through DIH and UPD.

## What it does

Stores `Household` and `Member`, each with a `*Version` history table, and the detail entities the questionnaire collects: `Dwelling`, `Utilities`, `AssetOwnership`, `FoodConsumption`, `FoodSecurity`, `Shock`, `CopingStrategy`, `Health`, `Disability`, `Education`, `Employment`, `Livelihood`, `Livestock` and `Crop` — every one of them versioned too.

!!! note "There is no `Relationship` table"
    This page listed one. Relationships between members are held as
    `Member.relationship_to_head`, not as their own model. Provides versioned reads. Emits audit events on every read and write.

## Geography is denormalised onto the household

A household holds a foreign key to each of the seven geographic levels
**and** a copy of each one's code:

| | |
|---|---|
| `region` … `village` | the foreign keys |
| `region_code` … `village_code` | the codes, copied on save |

The codes are what ABAC filters on and what the explorer matviews
project, so a scope check is one indexed comparison rather than a join
up the ladder. `Household.GEO_CODE_FIELDS` is the map between the two,
and `sync_geography_codes()` keeps them in step on every save.

!!! warning "Both sides have to agree"
    Two copies of one fact is a thing that can drift. It is kept
    honest by tests rather than by care — see
    `apps/data_management/test_household_geography_denorm.py`.

    Earlier builds filtered on the foreign key in one place and the
    code in another, which is how a county-scoped query came to return
    the whole country.

## Where it lives

| Path | What |
|---|---|
| `apps/data_management/` | Django app |
| `/api/v1/data-management/` | DRF surface |
| `/design/v0.1/screens/screens-registry.jsx`, `screens-household.jsx` | List + detail |

## Endpoints

| Endpoint | Verb | Purpose |
|---|---|---|
| `/api/v1/data-management/households/` | GET, POST | List, create (ABAC-scoped). `?q=` searches the head's name, the district, sub-county, parish and village names, and the geography codes |
| `/api/v1/data-management/households/{id}/` | GET, PATCH, DELETE | Read, update, void |
| ~~`/api/v1/data-management/households/{id}/versions/`~~ | — | **Not exposed.** `HouseholdVersion` rows exist and the audit chain is readable, but no route serves the version chain. Documented here and never built. |
| `/api/v1/data-management/members/` | GET, POST | List, create |
| `/api/v1/data-management/members/{id}/` | GET, PATCH | Read, update |

## Key entities

| Entity | Notes |
|---|---|
| `Household` | Primary key is ULID (the Registry ID). FKs to GeographicUnit at all 7 levels. |
| `HouseholdVersion` | Paired version table; effective-from / effective-to. |
| `Member` | Primary key is ULID. NIN encrypted at rest (Fernet) + `nin_hash` for joins. |
| `MemberVersion` | Same versioning model. |
| `Relationship` | Member ↔ Member (head/spouse/child/other). |
| Detail tables | Each is its own table per ADR-0017. Each has a version chain per ADR-0018 (repeat groups as child tables). |

## Audit trigger

The PostgreSQL trigger `security/0002_auditevent_chain_trigger.py` enforces hash chain integrity at INSERT into `AuditEvent`. Postgres-only. The `security.E004` check blocks production boot on non-Postgres.

## ADRs

- [ADR-0002](../appendices/adrs.md) — Identifier strategy (ULID + encrypted NIN)
- [ADR-0003](../appendices/adrs.md) — Migration policy (reversible through Sprint 5)
- [ADR-0005](../appendices/adrs.md) — Sub-region partitioning
- [ADR-0017](../appendices/adrs.md) — Detail entities as tables
- [ADR-0018](../appendices/adrs.md) — Repeat groups as child tables
- [ADR-0019](../appendices/adrs.md) — Sensitive health encryption
- [ADR-0020](../appendices/adrs.md) — FIES / FCS computed columns

## Stories

US-011, US-012, US-013, US-014, US-015, US-016 plus every sprint that added detail entities (S22 detail entities, US-S22-005, US-S22-005c).
