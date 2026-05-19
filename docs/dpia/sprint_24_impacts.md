# DPIA — Sprint 24 Impact Recording

**Status**: For DPO review.
**Last updated**: 2026-05-19.
**Covers**: US-S24 — canonical Partner + DSA consolidation (commits 001–006).
**Parent document**: `/docs/dpia.md` (initial DPIA, 2026-05-14).
**Previous instalment**: `/docs/dpia/sprint_23_impacts.md` (Sprint 23).

---

## Sprint 24 stories with personal-data impact

### US-S24-002 — Lift DRS-local rows to canonical (apps.partners)

- **Processing activity**: Data migration `apps/data_requests/migrations/0002_lift_drs_dsas_to_partners_canonical.py` lifts any `apps.data_requests.DataSharingAgreement` rows (and their parent `Partner` rows) into the canonical `apps.partners.*` tables. ULID preserved across the move so downstream `DataRequest.dsa` FK references stay valid in the schema migration.
- **Personal-data categories touched**:
  - **Partner metadata** — `name`, `contact_email`. No individual-level PII on the DRS-local Partner model (no NIN, no signatory data).
  - **DSA reference + signed_at + signed_by** — operational metadata only, not personal data.
- **Lawful basis**: Public task; no new collection. The lift is a representation change, not a new processing activity.
- **Empty in dev / staging today** — production lift is the only scenario where data actually moves.
- **Reverse hook is a no-op** — by design. ADR-0013 §"Migration policy" documents that the reverse path is operational rollback only, not part of the migration itself.

### US-S24-003 + 004 — Schema swap + canonical enforcement

- **Processing activity**: `DataRequest.dsa` FK repointed to `apps.partners.DataSharingAgreement`. The `validate_against_dsa()` and `render_bundle()` enforcement paths rewrite to read the canonical fields (`field_scope` dict, `geographic_scope` M2M, `monthly_row_budget`, `partner.status`). No change to what data is collected from data subjects.
- **Personal-data categories touched**: None new. The change is a representation refactor.
- **Audit chain enrichment**: The `deliver_data_request()` AuditEvent's `field_changes` payload grew to `{partner_code, partner_id, dsa_reference, rows_delivered, manifest_sha256, expires_at}`. The audit chain now reconstructs partner attribution for every delivery without parsing free-text `reason`. The Sprint 23 usage-rollup task in `apps/partners/tasks.py` reads from this structured payload going forward.
- **New audit actions**: `dsa_scope_violation` and `dsa_budget_exceeded` AuditEvents land when a partner submits a request outside their DSA. Both carry the DSA id and the field that triggered the violation. **For DPO consideration**: violation audit rows accumulate every time a misconfigured client retries; consider a sliding-window dedupe at the validator if this becomes noisy in production.
- **New gates**:
  - Partner-status: `submit_data_request()` rejects when `partner.status == "suspended"`. AuditEvent + DrsError exception. The DPO operationally pauses a partner by editing the canonical Partner row via `/admin/partners/partner/`.
  - Trailing-30d budget: `submit_data_request()` rejects when `trailing_30d_rows + max_rows > monthly_row_budget`. Provider-status partners (NIRA et al.) have `monthly_row_budget = NULL` and are skipped per ADR-0011 decision 3.

### Surface deletions

- `/api/v1/drs/partners/` and `/api/v1/drs/agreements/` endpoints removed. The canonical replacements at `/api/v1/partners/` and `/api/v1/dsas/` were landed in US-S23-008/010 and now carry the same ABAC scoping (`PartnerScopedQuerysetMixin`) that the DRS-side endpoints had. External consumers (none in production today) migrate to the canonical URLs; documented in the API changelog.

### Field-scope coarseness — explicit DPIA risk

The canonical `field_scope` gates at field-group level (`household`, `member`, `pmt`, ...) rather than per-field. A DSA granting the `member` group exposes every `member.*` field listed in `apps/data_requests/builder_schema.FIELD_CATALOGUE` to delivery — including the `nin_hash` and `nin_last4` fields. The DRS-local `allowed_scopes` JSON used to support per-field gating.

**For DPO decision**: are partners ever to be granted partial member-data access (e.g., `member.first_name` but not `member.nin_*`)? If yes, the tighter gating is `OI-S24-3` and lands as a schema follow-up. The current behaviour is documented; the operator-facing field catalogue still flags `nin_hash` / `nin_last4` as `Sensitive` in the builder schema response.

---

## DPO review checklist

- [ ] **Coarse-vs-fine field gating** (above) — confirm per-group is acceptable for the partner classes shipped at launch, or schedule the tighter version.
- [ ] **Violation audit volume** — agree on whether dedupe is needed at the validator if a misconfigured client retries every minute.
- [ ] **Partner-status as the operational pause control** — confirm that a DPO editing `partner.status = "suspended"` is the correct operational pause; we're not adding a separate `paused` field.
- [ ] **API URL deprecation** — confirm partner MDA contracts don't reference `/api/v1/drs/partners/` or `/api/v1/drs/agreements/` directly. None do today; this is forward planning.

---

## Sign-off

- DPO: ____________________ Date: __________
- Engineering Lead: ____________________ Date: __________
- Architecture Team: ____________________ Date: __________
