# Reference data loaders

!!! info "Status"
    **Built and in use** for the UBOS geographic hierarchy, the three Sprint 0 DQA rules, and the four MVP DIH source systems. Village polygons and the full ChoiceList catalogue are Planned (US-116).

Reference data is anything the rest of the system reads but rarely writes. Loading it once correctly is your first job after `migrate`.

## Loaders at a glance

| Script | What it does | When to run |
|---|---|---|
| `scripts/load_ubos_geography.py` | UBOS administrative hierarchy (district → parish) | Once, then on every new UBOS supply |
| `scripts/seed_dqa_rules.py` | Three Sprint 0 DQA rules with dual-approval | Once per environment |
| `scripts/seed_dih_sources.py` | Four MVP DIH source systems with DPAs | Once per environment |
| `scripts/seed_kigezi_geo.py` | Kigezi sub-region geography (pilot) | If your pilot covers Kigezi |
| `scripts/seed_geo_from_stages.py` | Sub-region + region rollup from staged sheet | When the UBOS sub-region sheet lands |
| `scripts/import_legacy_questionnaire.py` | Imports the v2 questionnaire (March 2026) | Once per questionnaire version |

## Loading UBOS geography

The script reads the UBOS workbook with district, county, sub-county, and parish columns. The May 2026 supply has 10,854 rows across four levels.

```bash
python scripts/load_ubos_geography.py /path/to/Goegraphy_final_with_codes.xlsx
```

### What you get

Seven levels are supported in the schema. The May 2026 supply only carries four. The loader leaves region, sub-region, and village empty.

| Level | Loaded? | How codes look |
|---|---|---|
| Region | No (supply gap) | n/a |
| Sub-region | No (supply gap) | n/a |
| District | Yes | `101` |
| County | Yes | `101.1` |
| Sub-county | Yes | `101.1.01` |
| Parish | Yes | `101.1.01.01` |
| Village | No (waiting on DQA-O-03 — UBOS village polygons) | n/a |

### Idempotency

The unique constraint on `(level, code, effective_from)` lets you re-run the loader. Existing rows are skipped, not duplicated.

### Sub-region rollup

Once UBOS ships the sub-region sheet, run `seed_geo_from_stages.py` to populate the two missing levels. The script also backfills `sub_region` foreign keys on households loaded before the rollup.

## Seeding the three Sprint 0 DQA rules

This script exercises the dual-approval workflow: each rule is authored by `seed-author` and approved by `seed-approver`. The `apps.dqa.services` layer rejects same-actor approvals.

```bash
python scripts/seed_dqa_rules.py
```

You get three blocking rules:

| Rule ID | What it checks |
|---|---|
| `AC-MANDATORY-MEMBER-NAME` | Every mandatory field is present |
| `AC-NIN-FORMAT` | NIN matches the NIRA regex `^(CM\|CF)[A-Z0-9]{12}$` |
| `AC-GPS-ACCURACY` | GPS accuracy reading is 10 m or better |

Confirm in the admin at `/admin/dqa/dqarule/`.

## Seeding the four MVP DIH source systems

Each source gets a `SourceSystem`, a `Connector`, and an active `DataProvisionAgreement` so connector runs can start (rule `AC-DIH-DPA-REQUIRED`).

```bash
python scripts/seed_dih_sources.py
```

| Source code | Kind | Connector | DPA residence |
|---|---|---|---|
| `UBOS-BULK` | `ubos` | `ubos-historic-load` | 90 days |
| `CAPI-WALKIN` | `capi_walkin` | `capi-default` | 30 days |
| `WEB-OD` | `web` | `web-od-default` | 30 days |
| `KOBO` | `kobo` | `kobo-pilot` | 30 days |

Confirm at `/admin/ingestion_hub/sourcesystem/`.

The PDM, NUSAF, WFP-SCOPE, and NIRA-Vital connectors land separately as their MoUs sign. Each ships as a Python class under `apps/ingestion_hub/connectors/` plus a SourceSystem row.

## Loading the v2 questionnaire (legacy import)

Until US-116 to US-120 ship the in-system questionnaire authoring tool, this script imports the v2 (March 2026) form structure.

```bash
python scripts/import_legacy_questionnaire.py /path/to/questionnaire_v2.xlsx
```

Once US-116 ships, ChoiceList and ChoiceOption become the system-of-record and this script retires.

## Related

- [Install and run](install.md) — your first-run checklist references this page
- [DIH connectors](connectors.md)
- ADR-0010 — Coded fields via ChoiceList
- `/scripts/` — all loaders live here
