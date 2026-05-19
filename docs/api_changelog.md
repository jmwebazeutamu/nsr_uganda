# NSR MIS API — Changelog

Notable changes to outbound API contracts. Entries are dated and tied to the commit / story that introduced them. Partner MDAs subscribed to the DRS contract should treat every entry as a candidate for downstream rework.

---

## 2026-05-19 — US-S22-005 — Coded fields now serialise as raw `ChoiceOption.code` strings

**Affected endpoints**: `GET /api/v1/data-management/households/{id}/` and `/members/{id}/`. Any DRS export bundle that includes these fields (per the active Data Sharing Agreement).

### What changed

Three column families now persist and return their raw `ChoiceOption.code` from the seeded `ChoiceList` catalogue instead of the legacy `TextChoices` strings:

| Field | Old value | New value | Seed list |
|---|---|---|---|
| `Member.sex` | `"M"`, `"F"` | `"1"`, `"2"` | `sex` (1=Male, 2=Female) |
| `Member.nin_status` | `"has_card"`, `"lost"`, `"not_issued"`, `"no"`, `"unknown"` | `"1"`, `"2"`, `"3"`, `"4"`, `"8"` | `nin_status` (1=Yes has card, 2=Yes lost, 3=Not issued, 4=No, 8=Don't know) |
| `Household.urban_rural` | `"urban"`, `"rural"` (and unused `"peri_urban"`) | `"1"`, `"2"` | `rural_urban` (1=Urban, 2=Rural) |

This applies to current rows (data migration 0005 rewrote in-place) and all future writes.

### What partner consumers need to do

Two paths, pick one:

1. **Resolve labels server-side via the bundle endpoint** (recommended for any consumer that renders the values to humans):
   ```
   GET /api/v1/reference-data/choice-list-bundle/?as_of=YYYY-MM-DD&lang=en
   ```
   Returns the full catalogue. ETag-cacheable. The response shape is `{as_of, lang, lists: [{list_name, version, options: [{code, label, sort_order, parent_code}]}]}`. Cache locally; re-fetch on ETag change.

2. **Read the `<field>_label` companion field** on the household / member payload itself:
   ```
   GET /api/v1/data-management/households/{id}/
   →  { ..., "urban_rural": "1", "urban_rural_label": "Urban", ... }
   ```
   Every coded column ships both the raw code and the resolved label. The label is computed against the `ChoiceList` version active at the household's intake date (StageRecord created_at), so historical records keep their historical labels.

### Audit-blob shape — unchanged

`source_payload` on the household detail endpoint remains bit-for-bit identical to what DIH ingested. Labels for the questionnaire payload live in the new parallel `source_payload_labels` tree alongside `source_payload`; the raw blob is never mutated. Consumers that hash `source_payload` for integrity continue to see the same hash.

### Reverse path

Operational rollback is not currently offered to consumers, but the inverse maps are documented in [ADR-0010](adr/0010-coded-fields-via-choicelist.md) and the rollback script lives at `scripts/reverse/us_s22_005c.py`. If a consumer needs a date range of historical state pre-2026-05-19, contact NSR Unit ops.

### Other notes from this slice

- New endpoint `GET /api/v1/reference-data/choice-list-bundle/` returns the active catalogue. Auth required. ETag = sha256 of canonical JSON. Cache-Control: private, max-age=60.
- `Household.dwelling_tenure` and `Household.residence_status` are now surfaced on the serializer with companion `_label` fields. They were previously absent from the response body.
- `Member` serializer companion `_label` fields shipped for: `relationship_to_head`, `sex`, `marital_status`, `nationality`, `residency_status`, `birth_certificate_status`, `nin_status`.
- Six Washington-Group disability dimensions (`seeing`, `hearing`, `walking`, `remembering`, `self_care`, `communicating`) currently render their raw payload codes — no label resolution until the `wg_disability` ChoiceList is seeded through the dual-approval workflow (`OI-S22-3`).

### Migration policy

The Django migrations (`0004_coded_fields_drop_textchoices` + `0005_coded_fields_to_choiceoption_codes`) are forward-only per ADR-0003. The reverse plan + inverse maps live in ADR-0010 §"Migration policy" and the rollback script. No production data has been lost — the rewrite is in-place and reversible.
