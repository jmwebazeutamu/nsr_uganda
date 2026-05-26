# REF-DATA — Reference Data

!!! info "Status"
    **Built (geography)**, **Scaffolded (ChoiceList)** — GeographicUnit loaded for district to parish; ChoiceList + ChoiceOption modelled (US-116 spec written) but the authoring tool itself is **Planned** alongside US-116 to US-120.

REF-DATA owns the things every other module reads but rarely writes: UBOS geography, the ChoiceList catalogue (income source, education level, disability type, shock type, etc.), and the UPD routing matrix.

## What it does

Maintains the **GeographicUnit** hierarchy (7 levels, versioned). Maintains **ChoiceList + ChoiceOption** as the system-of-record for coded fields ([ADR-0010](../appendices/adrs.md)). Maintains the **routing matrix** for UPD as a ChoiceList. Exposes both to other modules via DRF read endpoints.

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
| `/api/v1/reference-data/choice-lists/{code}/options/` | GET | Options for a list |

`get_queryset` was fixed in 2026-05-21 (US-S27-016) so the level / status / parent filters actually work. Before that, `filterset_fields` required `django-filter` (not installed) and was silently a no-op.

## Key entities

| Entity | Notes |
|---|---|
| `GeographicUnit` | Level enum (region → village), versioned by `(level, code, effective_from)`. Active at most once per `(level, code)`. |
| `ChoiceList` | Versioned, dual-approved. |
| `ChoiceOption` | One row per allowed value. |

## Loaders

| Script | Use |
|---|---|
| `scripts/load_ubos_geography.py` | District to parish from UBOS workbook |
| `scripts/seed_geo_from_stages.py` | Sub-region + region rollup when supplied |
| `scripts/seed_kigezi_geo.py` | Pilot sub-region |

## ADRs

- [ADR-0010](../appendices/adrs.md) — Coded fields via ChoiceList

## Stories

US-116, US-119, US-S22-005, US-S22-005c (TextChoices removal migration).
