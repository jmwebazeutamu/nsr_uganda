# DPIA — Sprint 22 Impact Recording

**Status**: For DPO review.
**Last updated**: 2026-05-19.
**Covers**: Stories merged to `main` during Sprint 22 — UPD workbench
  live-wiring (US-S22-001 → 004) and the coded-fields-via-ChoiceList
  programme (US-S22-005a → 005k).
**Parent document**: `/docs/dpia.md` (initial DPIA, 2026-05-14).
**Previous instalment**: `/docs/dpia/sprint_19_impacts.md` (Sprint 19).

---

## Sprint 22 stories with personal-data impact

### US-S22-005c — Drop TextChoices on coded fields

- **Processing activity**: Forward-only data migration `0005_coded_fields_to_choiceoption_codes` rewrote three columns in-place across every row in the registry:
  - `Member.sex`: `M`/`F` → `1`/`2`
  - `Member.nin_status`: `has_card`/`lost`/`not_issued`/`no`/`unknown` → `1`/`2`/`3`/`4`/`8`
  - `Household.urban_rural`: `urban`/`rural` → `1`/`2`
  Mirror columns in `MemberVersion.nin_status` and `HouseholdVersion.urban_rural` rewritten with the same maps. The migration validates that every distinct pre-migration value has a seed mapping and aborts if not.
- **Personal-data categories touched**:
  - **Identification** — `Member.sex` (personal data, used for demographic reporting and PMT features).
  - **Identification + sensitive** — `Member.nin_status` (NIN trio per ADR-0002; the column itself is metadata about NIN possession, not the NIN value, but adjacent to sensitive data).
  - **Demographic** — `Household.urban_rural` (urban/rural classification, low-sensitivity proxy).
- **Lawful basis**: Public task. The migration changes representation, not the underlying processing purpose.
- **Data minimisation**: No new fields collected. Column-width widened from `max_length=1` (sex) / `max_length=16` (nin_status) to `max_length=32` to accommodate the seed-code contract; widening alone does not increase PII surface.
- **Audit chain**: The bulk `UPDATE` was run inside the Django migration framework — no per-row `AuditEvent` was emitted. This is consistent with the existing pattern for schema-bearing migrations (no audit on the 0001 initial creation either). **For DPO decision**: should operational PII rewrites emit a per-entity audit row? Recommendation is to add a single migration-level `AuditEvent` (entity_type=`migration`, entity_id=`0005_coded_fields_to_choiceoption_codes`, action=`bulk_rewrite`, reason with row counts) in a follow-up so the audit trail acknowledges the rewrite without bloating per-row.
- **DSAR / right to access**: Subject-access exports continue to return the current column value. Pre-migration values are recoverable from the reverse script `/scripts/reverse/us_s22_005c.py` + the inverse maps documented in ADR-0010. If a subject queries pre-migration historical state, the registry's audit chain (event log of writes) is unaffected; only the live column is rewritten.
- **DSAR impact on exports**: External recipients of household exports (DRS, Section 7 below) will now see numeric codes where they previously saw enum strings. The first DRS export after this migration carries the new code system; downstream consumers must resolve codes via the `choice-list-bundle` endpoint or the published ChoiceList catalogue. The standing DRS contract template doesn't pin the value format, so this isn't a contract breach, but the operations team should give partner MDAs a notice in the next DPA quarterly update.
- **Retention**: Unchanged. The DPPA retention windows (SAD §8.5) apply to the row, not the value-format inside it.

### US-S22-005b/d/e/f/g — Resolver, serializer label fields, bundle endpoint, JSX wiring

- **Processing activity**: New read-path code that resolves stored codes to human-readable labels at serialise time. No new write or storage activity. The resolver service in `apps/reference_data/services.py` is read-only against the `ChoiceList`/`ChoiceOption` catalogue.
- **Personal-data categories touched**: Indirect. The resolver runs over `Household.source_payload` (a JSONB snapshot of the questionnaire intake) when an authenticated user requests the household-detail endpoint. The audit blob (`source_payload`) is bit-for-bit identical to what DIH ingested; labels are computed into a parallel `source_payload_labels` tree at read time, never persisted.
- **Lawful basis**: Public task — operator-facing UX over data already collected.
- **Data minimisation**: The labels tree contains the same semantic content as the codes — no new attributes. Label resolution does not require the resolver to read PII (it operates on codes and the catalogue alone).
- **Audit chain**: Read requests against `/api/v1/data-management/households/{id}/` continue to emit `record_read` events through `AuditReadMixin`. The label resolution itself is an internal transformation and does not emit additional audit events.
- **New endpoint**: `GET /api/v1/reference-data/choice-list-bundle/` returns the active ChoiceList catalogue. No personal data is returned; only code-to-label mappings. The endpoint requires authentication (default DRF permission class). Bundle ETag enables CAPI / web intake clients to skip downloads when nothing has changed — reduces bandwidth on rural cellular links.

### US-S22-005h/i/j — Connectors, registry JSX, UPD field catalog corrections

- **Processing activity**: Post-005 regression fixes. The intake pipeline (Kobo, PDM, NUSAF, WFP Scope connectors) now emits seed `ChoiceOption.code` strings in the canonical_payload instead of legacy enum strings. The Operator-facing UPD modal proposes seed codes for `urban_rural` and `sex`.
- **Personal-data categories touched**: None new. These are correctness fixes ensuring new intake data conforms to the contract established in 005c.
- **DPO review checklist**:
  - [ ] Confirm bulk-rewrite-without-AuditEvent precedent is acceptable; if not, schedule the per-migration audit row described under 005c.
  - [ ] Approve the API-changelog notice to partner MDAs (one round-trip; legal review not required if scoped to value-format reformatting only).
  - [ ] Confirm OI-S22-3 (Washington Group disability ChoiceList) tracking: WG dimensions currently render raw codes until `wg_disability` is seeded through dual approval.

### US-S22-001 → 004 — UPD workbench live + Open-CR modal

- **Processing activity**: Operators now interact with `ChangeRequest` rows over a live endpoint (previously mock data). The Open-CR modal can stack multiple field changes across categories into one CR, posted to `POST /api/v1/upd/change-requests/bundle/`.
- **Personal-data categories touched**: Identification + demographic + dwelling + assets (the field catalog covers Identity / Location / Roster / Health & Disability / Education / Employment / Housing & Assets / Food & Shocks).
- **Lawful basis**: Public task. The change request mechanism is the legally-mandated correction channel under DPPA 2019 §17 (right to rectification).
- **Audit chain**: Every CR submit and commit emits `AuditEvent` with action `submit` / `commit` / `reject`. Verified in `apps/update_workflow/tests.py::TestAutoCommit::test_auto_commit_emits_audit_chain`.
- **Bundle endpoint**: Member-entity CR submissions return 400 today (member picker is a follow-up); `all_members` entity folds to the household with intent stored in `requester_note`. Both behaviours are documented in `project_open_cr_architecture` memory and the bundle endpoint OpenAPI.

---

## Cumulative DPIA changes flagged for Sprint 22 DPO review

1. **Per-migration audit row policy.** Recommend extending the standard so future PII-bearing migrations land a single `AuditEvent` row pinning entity_type=`migration`, entity_id=`<migration label>`, action=`<bulk verb>`, reason=`<row counts>`. Document the precedent here and in `/docs/CLAUDE.md` so future stories don't reinvent the pattern.
2. **API-changelog notice to partner MDAs.** First DRS export with the new code values is the partner-visible signal. Schedule the email + DPA appendix update for the next quarterly DPA review.
3. **Washington-Group disability labels** (`OI-S22-3`). Until `wg_disability` ChoiceList is authored and approved, the JSX renders raw codes for the six WG dimensions. Operator UX impact only; no PII exposure changes.

## Sign-off

- DPO: ____________________ Date: __________
- Engineering Lead: ____________________ Date: __________
- Architecture Team: ____________________ Date: __________
