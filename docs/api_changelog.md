# NSR MIS API — Changelog

Notable changes to outbound API contracts. Entries are dated and tied to the commit / story that introduced them. Partner MDAs subscribed to the DRS contract should treat every entry as a candidate for downstream rework.

---

## 2026-05-19 — US-S25 / ADR-0014 — Programme registration wizard wired (POST /api/v1/programmes/)

**Affected endpoints**: new `/api/v1/programmes/` namespace and the
convenience `/api/v1/partners/{id}/programmes/` lister. Extends
`/api/v1/reference-data/choice-list-bundle/` with 8 new lists.

### New endpoints

| Method | Path | Purpose |
|---|---|---|
| GET    | `/api/v1/programmes/`                       | List programmes. Filters: `partner`, `status`, `kind`, `q`. ABAC-scoped per `PartnerScopedQuerysetMixin`. |
| POST   | `/api/v1/programmes/`                       | Create a draft Programme. Gated by `PARTNERS_MODULE_ENABLED`. |
| GET    | `/api/v1/programmes/{id}/`                  | Retrieve. |
| PATCH  | `/api/v1/programmes/{id}/`                  | Update. |
| GET    | `/api/v1/partners/{id}/programmes/`         | Convenience lister for the partner detail screen. |

### POST shape

The wizard submits a single JSON payload. Required: `partner`,
`name`, `kind`. Optional fields drive the cohort, disbursement,
geographic, lifecycle, and webhook strips:

```json
{
  "partner":             "01J...",
  "code":                "MGLSD-DVA",
  "name":                "Direct Income Support · vulnerable adolescents",
  "summary":             "Monthly cash to female-headed HHs",
  "kind":                "cash_transfer",
  "dsa":                 "01J...",
  "unit_of_enrolment":   "household",
  "cohort_target":       18000,
  "sex_filter":          "2",
  "age_min":             14,
  "age_max":             18,
  "pmt_bands":           ["poorest_20", "poorest_40"],
  "composition_flags":   ["female_headed"],
  "amount_ugx":          75000,
  "disbursement_cycle":  "monthly",
  "duration_months":     24,
  "channel":             "MTN MoMo · agent",
  "start_month":         "Aug 2026",
  "geographic_units":    ["01J...","01J..."],
  "exit_codes_allowed":  ["10","20","30","40","50","60","70"],
  "auto_exit_triggers":  ["age_out","deceased","pmt_shift"],
  "suspend_on_grievance": true,
  "webhook_url":         "https://partner.example.go.ug/webhook"
}
```

The create response echoes every coded field with its resolved
`<field>_label` (Cash transfer, Household, Female, Monthly, …) per
the ADR-0010 contract. The response also carries
`webhook_secret_cleartext` — a one-shot field returned at create
time only; only `sha256(secret)` is persisted on the row.

### New ChoiceLists seeded at v1 / active

```
programme_unit_of_enrolment   (household, member, group)
programme_disbursement_cycle  (monthly, quarterly, semi_annual, annual, one_off)
programme_pmt_band            (poorest_20, poorest_40, middle_40, top_20)
programme_exit_reason         (10..99 — graduated, transferred, deceased, ...)
programme_composition_flag    (female_headed, under_five, elderly, pregnant, disabled, orphan)
programme_auto_exit_trigger   (age_out, deceased, pmt_shift, missed_3)
programme_webhook_event       (referral.sent, referral.accepted, enrolment.created, ...)
programme_sex_filter          (any, 1=Male, 2=Female)
```

Two new options appended to existing `programme_kind`: `grant`, `subsidy`.
Consumers caching the bundle offline pick them up via the ETag.

### New audit-event action

- `programme_created` — fired on every successful create. The
  `field_changes` payload is structured:
  `{partner_id, partner_code, code, kind, cohort_target}`. Same
  shape as the Sprint 23 dashboard activity feed.

### Feature flag

`PARTNERS_MODULE_ENABLED` gates writes (POST / PATCH). Reads are
open under the standard `IsAuthenticated` permission.

### Unique-code semantics

`Programme.code` is unique per partner *only when non-empty*. The
serializer skips DRF's auto-generated `UniqueTogetherValidator`
(which would mark `code` as required) and does a manual partial-
uniqueness check in `validate()`. Empty-string `code` is permitted
so partner Data Stewards can park a draft before naming it.

---

## 2026-05-19 — US-S24 / ADR-0013 — DRS-side Partner + DSA endpoints removed; consolidated under /api/v1/partners/ and /api/v1/dsas/

**Affected endpoints**:

| Removed | Replacement |
|---|---|
| `GET /api/v1/drs/partners/` | `GET /api/v1/partners/` (US-S23-008) |
| `GET /api/v1/drs/partners/{id}/` | `GET /api/v1/partners/{id}/` |
| `GET /api/v1/drs/agreements/` | `GET /api/v1/dsas/` (US-S23-010) |
| `GET /api/v1/drs/agreements/{id}/` | `GET /api/v1/dsas/{id}/` |

### What changed

- Two parallel `DataSharingAgreement` (and two `Partner`) classes coexisted on `main` after Sprint 23 — one in `apps/data_requests/` (pre-existing US-S19), one in `apps/partners/` (Sprint 23). ADR-0013 consolidates onto `apps/partners/`. The DRS-side classes are deleted; their endpoints with them.
- `DataRequest.dsa` FK now targets `apps.partners.DataSharingAgreement`. Response shapes for `GET /api/v1/drs/requests/...` are unchanged (the FK reference is opaque to the consumer).
- The canonical endpoints already carry the same ABAC scoping (`PartnerScopedQuerysetMixin`) the DRS-side endpoints did. Partner-affiliated users see only their own partner; NSR Unit / national / superuser see all.

### DSA scope shape change

The canonical DSA shape differs from the legacy DRS-side one. External consumers that GET a DSA see a different JSON:

| Legacy field | Canonical field |
|---|---|
| `allowed_scopes.fields` | `field_scope` dict (`{"household": true, "member": true}`) |
| `allowed_scopes.sub_region_codes` | `geographic_scope` M2M to GeographicUnit (response includes resolved sub_region codes) |
| `allowed_scopes.programme_codes` | `entities_scope.programmes_allowed` until the structured Programme M2M lands |
| `allowed_scopes.max_rows_per_request` | `monthly_row_budget` |
| `valid_from` / `valid_to` | `effective_from` / `effective_to` |

### Field-scope granularity (read carefully)

The canonical `field_scope` gates at **group level** (`household`, `member`, `pmt`, ...) rather than per-field. A DSA granting the `member` group exposes every `member.*` field in `apps/data_requests/builder_schema.FIELD_CATALOGUE` — including the masked `nin_hash` / `nin_last4`. The legacy `allowed_scopes.fields` supported per-field gating.

Partners with sensitive per-field requirements: please raise; a tighter gating story is `OI-S24-3` in ADR-0013.

### New audit-event actions

Two new AuditEvent action codes land:

- `dsa_scope_violation` — fired by the validator when a request asks for a field group, sub-region, or programme outside the DSA.
- `dsa_budget_exceeded` — fired when trailing-30d rows + this request's `max_rows` would push the partner over their `monthly_row_budget`.
- `data_request_delivered` — renamed from `deliver`. The `field_changes` payload is now structured: `{partner_code, partner_id, dsa_reference, rows_delivered, manifest_sha256, expires_at}`. Consumers reading the audit chain should expect both names during the transition window and switch to `data_request_delivered` going forward.

### New gates (Partners module)

- **Partner-status gate**: `POST /api/v1/drs/requests/{id}/submit/` returns 400 with `detail: "Partner X is suspended"` when the partner's status is `suspended`. The DPO operationally pauses a partner by setting the status via `/admin/partners/partner/`.
- **Budget gate**: returns 400 with `detail: "trailing-30d usage N + this request M would exceed DSA budget B"` when the submit would breach the partner's monthly row budget.

---

## 2026-05-19 — US-S23 — Partners + DSA registry API

**Affected endpoints**: new namespace under `/api/v1/partners/` and `/api/v1/dsas/`. Also extends `/api/v1/reference-data/choice-list-bundle/`.

### New endpoints

| Method | Path | Purpose |
|---|---|---|
| GET    | `/api/v1/partners/`                 | List partners; filters `q`, `type`, `status`, `sector`. |
| POST   | `/api/v1/partners/`                 | Create a partner. Gated by `PARTNERS_MODULE_ENABLED`. |
| GET    | `/api/v1/partners/{id}/`            | Retrieve. |
| PATCH  | `/api/v1/partners/{id}/`            | Update. |
| GET    | `/api/v1/partners/summary/`         | KPI counts for the dashboard. |
| GET    | `/api/v1/partners/renewals/?days=`  | DSAs by days-until-expiry. |
| GET    | `/api/v1/partners/sector-mix/`      | Partner counts + rows-delivered per sector. |
| GET    | `/api/v1/partners/top-consumers/?n=`| Top N requesters by 30d row volume. |
| GET    | `/api/v1/partners/{id}/activity/`   | Activity feed projection over `AuditEvent`. |
| GET    | `/api/v1/partners/{id}/usage/?days=`| Per-day usage rollup. |
| GET    | `/api/v1/dsas/`                     | List DSAs; filters `partner`, `status`. |
| POST   | `/api/v1/dsas/`                     | Create a draft DSA. |
| GET    | `/api/v1/dsas/{id}/`                | Retrieve with embedded signatures. |
| PATCH  | `/api/v1/dsas/{id}/`                | Update. |
| POST   | `/api/v1/dsas/{id}/submit-for-signoff/` | Workflow trigger (ADR-0012). |

### Bundle endpoint extension

`GET /api/v1/reference-data/choice-list-bundle/?lists=a,b,c` — new `lists` query param trims the bundle to the named ChoiceLists. The wizard fetches just the option sets it needs (`partner_type`, `partner_sector`, `partner_contact_role`, `programme_kind`, `dsa_signer_role`, `signature_method`, `sensitive_data_handling`, `dsa_wizard_step`) instead of the full 60-list catalogue. ETag differs per `lists` allowlist, so each slice caches independently.

### ChoiceList catalogue additions

14 new ChoiceLists seeded at v1/ACTIVE — these are the option sets every partner-module dropdown reads from:

```
partner_type, partner_sector, partner_status, ui_tone,
partner_contact_role, programme_kind, programme_status,
dsa_status, sensitive_data_handling, dsa_signer_role,
signature_method, signature_status, partner_activity_kind,
dsa_wizard_step
```

External consumers that resolve labels via the bundle endpoint pick them up automatically. Consumers caching the catalogue offline must re-fetch (ETag changes).

### Coded-field response shape

Every coded field on every partner-module response carries both raw `<field>` and resolved `<field>_label` — same contract as the household-detail payload from US-S22-005. For example:

```json
{
  "id": "01...",
  "code": "OPM",
  "type": "ministry",
  "type_label": "Ministry",
  "sector": "social_protection",
  "sector_label": "Social Protection",
  "status": "active",
  "status_label": "Active",
  ...
}
```

### Workflow contract

`POST /api/v1/dsas/{id}/submit-for-signoff/` accepts `partner_signer_email`, `nsr_unit_lead_email`, `dpo_email` (and optional name fields). The three emails must be distinct (self-sign-off prohibition). Creates three `DsaSignature` rows; dispatches the first DocuSign envelope (or the stub, depending on `PARTNERS_DOCUSIGN_ENABLED`); emits `AuditEvent`s per ADR-0012.

### Feature flag

`PARTNERS_MODULE_ENABLED` (default `True` in dev; toggleable in production deployment settings) gates write endpoints (POST/PATCH). Reads remain open under the standard `IsAuthenticated` permission.

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
