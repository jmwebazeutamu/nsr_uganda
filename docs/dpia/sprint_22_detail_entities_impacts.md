# DPIA impact — Sprint 22 detail-entity build (US-S22-DE)

**Status**: Initial assessment — Data Protection Officer review pending
**Build**: US-S22-DE-01 → US-S22-DE-14
**Lead**: NSR Unit engineering
**Filed**: 2026-05-21

## Summary

The detail-entity build promotes ~120 questionnaire fields per
household from `RawLanding.payload` (an opaque JSONField blob) into
**typed, indexable, audit-versioned columns** in the registry. None
of these fields are new collection — the questionnaire (v2,
2026-03) already asks them; only the persisted shape changes.

The build introduces 14 new tables (1066 → 1090 pytest count;
~50 new fields visible on `/api/v1/data-management/households/`).
This DPIA note captures the personal-data impact per DoD #6.

## New personal-data categories now indexed

The registry now exposes — as queryable, joinable columns instead
of opaque JSON — the following categories:

| Category | Sensitivity | New tables |
|---|---|---|
| Household dwelling characteristics (tenure, rooms, materials) | Public | `Dwelling` |
| Water / sanitation / energy | Public | `Utilities` |
| Agricultural livelihood (land hectares, ownership, title) | Public | `Livelihood` |
| Food security (FIES 8-question scale + raw score) | Internal | `FoodSecurity` |
| Food consumption frequency (FCS by food group + WFP-weighted score) | Internal | `FoodConsumption` |
| Asset ownership (radio, TV, motorcycle, livestock, etc.) | Internal | `AssetOwnership`, `Livestock` |
| Crop production | Internal | `Crop` |
| Shock events (drought, flood, theft, illness, death) | Personal | `Shock` |
| Coping strategies (sold asset, took loan, withdrew children from school) | Personal | `CopingStrategy` |
| **Health: chronic illness flag + types (HIV/TB possible)** | **Sensitive** | `Health` |
| **Disability: Washington Group Short Set + computed flag** | **Personal** | `Disability` |
| Education: literacy, attendance, highest grade, why stopped | Internal | `Education` |
| Employment: activity, sector, status, programme benefits, savings | Personal/Internal | `Employment` |

## Special category data — DPPA 2019 §§9–10

Two surfaces require the strongest protection:

1. **`Health.chronic_illness_types_encrypted`** — may include HIV
   and TB codes. Mitigations:
   - Column-level AES-256 via `EncryptedBinaryField`, same key path
     as `Member.nin_value` (ADR-0019 + ADR-0002).
   - Plaintext never appears on the DB column. Backups + replicas
     carry the encrypted bytes only.
   - DRS query builder flags the column as
     `requires_special_scope=True` (US-S22-DE-09). Partners need
     an explicit DSA clause to query against it; default DSAs do
     NOT extend to this field.
   - Admin surface hides the column from the write form;
     operators use the `Health.set_chronic_illness_types()`
     helper which decrypts/encrypts via the model's accessors.

2. **`Disability.*` (Washington Group)** — codes "03" / "04"
   record functional limitations (a lot of difficulty / cannot do
   at all). Sensitivity Personal, not Sensitive, because the
   categorical answers per WG short set are not health diagnoses.
   No encryption; ABAC + DSA scope enforced at the query layer.

## NIN-derived columns

Pre-existing but re-flagged in US-S22-DE-09:

- `Member.nin_hash` — sensitivity Sensitive
- `Member.nin_last4` — sensitivity Sensitive (last-4 digits visible
  to authorised operators only)

Both now carry `requires_special_scope=True` in the DRS
builder-schema response so the wizard surfaces a "needs scope
expansion" badge during query construction. The encrypted
`nin_value` column never appears on the wire.

## Retention

Inherits the existing Household retention policy: registry-lifetime
storage with the `is_deleted` soft-delete column for record-of-erasure
under DPPA 2019 §17 (right to erasure). Detail-entity rows follow
the parent Household — when a household is soft-deleted, the related
detail rows are NOT auto-cascaded (their `on_delete=PROTECT`
guards prevent accidental loss of the audit trail). A future
release ticket will define the cascade-on-final-erasure step.

## Data minimisation

No new collection. The detail entities surface answers the
questionnaire was already asking under the v1 form. The build is a
**representation change**: from opaque JSON to typed indexable
columns. The footprint of personal data captured per household is
unchanged.

## Access control

- **ABAC** (apps.security.abac) — already filters Household and
  Member by the operator's sub_region_code scope. The detail
  entities inherit `sub_region_code` from the parent on save
  (ADR-0005 partitioning + ABAC alignment) so the same filter
  applies transitively.
- **DSA scope** (apps.partners) — DRS queries against the registry
  are clipped to the partner's DSA `field_scope`. Adding the
  detail tail to the registry does NOT auto-extend any existing
  DSA. **Each active DSA needs an explicit renewal scoping the new
  detail fields before partners can query them.** Flag to legal
  team via the DPO (see "Open items" below).
- **Special category fields** (`Health.chronic_illness_types_encrypted`)
  — additionally gated by the `requires_special_scope` flag in the
  DRS builder-schema. Partners cannot select these columns from
  the wizard unless their DSA clause explicitly grants them.

## Audit chain

Every detail-entity create / update / soft-delete writes:

- An `AuditEvent` row via `apps.security.audit.emit(...)` with
  `entity_type="<lowercase_model>"` (Dwelling = "dwelling", etc.)
  and `action` in (create / update / soft_delete).
- A `_Version` snapshot row capturing the prior state per SAD §5.3.

The audit chain hashes are added by the Postgres trigger (per
ADR-0001, audit-chain trigger is Postgres-only — degrades to no-op
on SQLite local dev).

## Open items for the DPO

- **OI-DE-DPIA-1** — Existing DSAs do not auto-extend to the new
  detail fields. Each active DSA needs a renewal (ADR-0016
  scope-edit path) before partners can query the detail tail.
  Recommend: DPO drafts a model amendment clause covering health
  / disability / employment scoping for the partners team to
  propose at the next renewal window.
- **OI-DE-DPIA-2** — `chronic_illness_types_encrypted` is
  encrypted-at-rest but plaintext flows through the application
  layer briefly during a read. The current threat model considers
  this acceptable; a future hardening pass could move the
  decryption to a request-scoped policy check (DPO authorisation
  per-row) for tighter least-privilege.
- **OI-DE-DPIA-3** — Refugee / IDP status: today carried on
  `Member.residency_status` (a ChoiceList code). The MGLSD policy
  team should confirm whether UNHCR data-sharing requires a
  dedicated boolean column. Default for this build: no.

## Sign-off

- [ ] DPO review
- [ ] Legal team — DSA renewal clause language (OI-DE-DPIA-1)
- [ ] MGLSD policy team — UNHCR refugee flag question (OI-DE-DPIA-3)

## References

- DPPA 2019 (Uganda Data Protection and Privacy Act, 2019)
- ADR-0017 — detail entities as tables
- ADR-0018 — repeat-group child tables
- ADR-0019 — sensitive health encryption
- ADR-0020 — FIES + FCS computed columns
- Build prompt: `docs/build_prompts/US-S22-detail-entities_implementation_prompt.md`
