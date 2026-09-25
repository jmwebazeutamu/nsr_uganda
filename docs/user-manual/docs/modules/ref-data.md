# REF-DATA — Reference Data

!!! info "Status"
    **Built.** All seven geographic levels are loaded — region through village — and the ChoiceList catalogue is the system of record for coded fields. The ChoiceList *authoring tool* remains Planned (US-116 to US-120). Revised 25 September 2026.

REF-DATA owns the things every other module reads but rarely writes: UBOS geography, the ChoiceList catalogue (income source, education level, disability type, shock type, and so on), and the counter behind every case number in the registry.

## What it does

Maintains the **GeographicUnit** hierarchy (7 levels, versioned). Maintains **ChoiceList + ChoiceOption** as the system of record for coded fields ([ADR-0010](../appendices/adrs.md)). Owns **ReferenceSequence**, the counter that issues every case number. Exposes geography and choice lists to other modules via DRF read endpoints.

!!! warning "The UPD routing matrix is not here"
    This page used to say REF-DATA maintained it "as a ChoiceList". It
    never did. Routing lives in `apps.update_workflow.UpdRoutingRule` —
    see [UPD](upd.md#routing). Corrected 25 September 2026.

## Where it lives

| Path | What |
|---|---|
| `apps/reference_data/` | Django app |
| `/api/v1/reference-data/` | DRF surface |
| `/design/v0.1/screens/screens-admin-refdata-geography.jsx`, `screens-admin-refdata-choicelists.jsx` | Admin Console UIs |

## Endpoints

| Endpoint | Verb | Purpose |
|---|---|---|
| `/api/v1/reference-data/geographic-units/` | GET | UBOS hierarchy. Filter `?level=<level>&status=active&parent=<code>` |
| `/api/v1/reference-data/choice-lists/` | GET | ChoiceList catalogue |
| `/api/v1/reference-data/choice-lists/{id}/` | GET | Options for a list |

`get_queryset` was fixed in 2026-05-21 (US-S27-016) so the level / status / parent filters actually work. Before that, `filterset_fields` required `django-filter` (not installed) and was silently a no-op.

## The geographic ladder

Seven levels, and all seven carry data:

```mermaid
flowchart LR
    R["Region"] --> SR["Sub-region"] --> D["District"] --> C["County"]
    C --> SC["Sub-county"] --> P["Parish"] --> V["Village"]
```

!!! note "County is a real level, not a gap"
    An earlier build derived the ladder from the ABAC scope enum, which
    had no `COUNTY` — so a county-scoped query silently returned the
    whole country. The ladder is derived from `GeographicUnit.Level`
    now, which is the only list with all seven.

## Key entities

| Entity | Notes |
|---|---|
| `GeographicUnit` | Level enum (region → village), versioned by `(level, code, effective_from)`. Active at most once per `(level, code)`. |
| `ChoiceList` | Versioned, dual-approved. |
| `ChoiceOption` | One row per allowed value. |
| `ReferenceSequence` | One row per (module prefix, year). The running count behind `GRM-2026-0001`, `UPD-`, `DRS-` and `REF-` numbers. |

## Case numbers

`apps/reference_data/references.py` issues every case number in the
registry, and `ReferenceSequence` is the counter behind it. One
implementation, four callers — GRM, UPD, DRS and REF.

Numbers are taken under `select_for_update` inside the transaction that
creates the record, so concurrent creates queue rather than collide and
a rolled-back transaction gives its number back instead of burning it.
That is what keeps a year's numbering contiguous.

Four copies of this would drift, and the first thing to drift is
exactly that rollback behaviour — which nobody notices until a year has
gaps and nobody can say why. See [ADR-0038 and
ADR-0039](../appendices/adrs.md).

!!! note "Two senses of one word"
    "Reference data" here means geography and choice lists.
    "Reference" on a Grievance or ChangeRequest means the case number
    people quote. Same word, different jobs.

## Loaders

| Script | Use |
|---|---|
| `scripts/load_ubos_geography.py` | District to parish from the UBOS workbook |
| `scripts/seed_geo_from_stages.py` | Sub-region + region rollup |
| `scripts/seed_kigezi_geo.py` | Pilot sub-region |

## ADRs

- [ADR-0010](../appendices/adrs.md) — Coded fields via ChoiceList

## Stories

US-116, US-119, US-S22-005, US-S22-005c (TextChoices removal migration).
