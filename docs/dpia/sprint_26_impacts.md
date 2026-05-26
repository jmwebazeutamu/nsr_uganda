# DPIA — Sprint 26 Impact Recording

**Status**: For DPO review.
**Last updated**: 2026-05-20.
**Covers**: US-S26 — `apps.referral.Programme` consolidation +
`/api/v1/beneficiaries/` listing (commits 001–008).
**Parent document**: `/docs/dpia.md` (initial DPIA, 2026-05-14).
**Previous instalment**: `/docs/dpia/sprint_25_impacts.md` (Sprint 25).

---

## Sprint 26 stories with personal-data impact

### US-S26-001 — ADR-0015 (no processing impact)

Architecture decision record. No code change.

### US-S26-002 — `referral_status` ChoiceList seeded

Reference data only. No personal data. One new ChoiceList
(5 codes: sent, accepted, enrolled, rejected, exited) seeded
under author tag `system-migration-referral`. Forward-only.

### US-S26-003 — Strip TextChoices, align enrolment codes

- **Processing activity**: `Referral.status` and
  `ProgrammeEnrolment.status` lose their `choices=` declaration
  and now resolve against ChoiceLists per ADR-0010. Existing
  ProgrammeEnrolment rows with status `enrolled` are data-migrated
  to `active` to match the seeded ChoiceList vocabulary.
- **Personal-data categories touched**: None. The migration
  rewrites a string code column in-place; the rows themselves
  (which DO carry household FK references) are not otherwise
  altered.
- **No production impact** — zero rows in dev / staging at the time
  of the migration.
- **For DPO note**: the API response shape for
  `/api/v1/ref/referrals/` and `/api/v1/ref/enrolments/` now carries
  `status_label` companion fields per ADR-0010. Consumers reading
  the labels in English see the same human-readable strings as
  before; consumers caching the raw codes see `active` where
  `enrolled` used to appear.

### US-S26-004 — Lift `apps.referral.Programme` rows to canonical

- **Processing activity**: Data migration
  `apps/referral/migrations/0003_lift_referral_programmes_to_partners.py`
  copies every row from the legacy `apps.referral.Programme` model
  into the canonical `apps.partners.Programme`. The webhook secret
  cleartext moves into `Programme.webhook_secret_encrypted` (an
  `EncryptedBinaryField` — the same column-level encryption already
  used for `PartnerContact.nin_value`).
- **Personal-data categories touched**: None. Programme-level
  metadata only — `code`, `name`, `webhook_url`, free-text
  `dsa_reference`. No beneficiary fields touched.
- **Encrypted column — for DPO consideration**: ADR-0014 §"webhook
  secret" originally stored only `sha256(secret)` with one-shot
  cleartext disclosure. ADR-0015 §"Decision 3" introduces the
  encrypted cleartext column as a documented exception because
  HMAC signing of outbound webhooks needs the cleartext at send
  time. The encrypted column uses the same KMS path as NIN
  encryption (NSR-O-04). Cleartext disclosure to operators remains
  one-shot via the registration wizard. `WebhookCredential`
  factoring (OI-S26-3) is the long-term replacement.
- **Empty in dev today** — production lift is the only scenario where
  data actually moves. ADR-0015 §"Decision 2" documents the
  three-step attribution chain (existing canonical → code-prefix
  Partner match → `GoU-LEGACY` placeholder).

### US-S26-005 — Schema swap: repoint FKs, drop legacy Programme

- **Processing activity**: `Referral.programme` and
  `ProgrammeEnrolment.programme` FKs now target
  `apps.partners.Programme`. The legacy `apps.referral.Programme`
  model is deleted along with the read-only `/api/v1/ref/programmes/`
  endpoint. No row contents change; only the FK target column does.
- **Personal-data categories touched**: None. The FK values
  re-point to canonical Programme IDs; the underlying Household /
  Member / Referral / Enrolment rows are unchanged.
- **API surface deletion**: `/api/v1/ref/programmes/` removed
  outright (no consumers; the design harness already reads
  `/api/v1/programmes/` from the partners app). Documented in the
  API changelog.

### US-S26-006 — `/api/v1/beneficiaries/` listing endpoint

- **Processing activity**: New read-only endpoint joining
  `ProgrammeEnrolment + Referral + Household + Member +
  Programme + Partner` into one row per (household, programme).
  Returns a beneficiary's name, household sub_region/district/
  parish, PMT score, enrolment status, exit reason, and the
  programme they're enrolled in. This is the most beneficiary-
  identifiable surface added in this sprint.
- **Personal-data categories touched**:
  - **Household head name** (Member.surname + first_name)
  - **PMT score** (Household.current_pmt_score)
  - **Geographic location** (sub_region, district, parish names)
  - **Sex of the head** (Member.sex code)
- **No new collection — only re-projection of existing data.** All
  fields are already stored elsewhere in the registry. The
  beneficiary endpoint surfaces them in one place.
- **ABAC**: Combined partner + geographic scope. Partner analysts
  see only their partner's programmes' beneficiaries; sub-region
  operators see beneficiaries whose households fall in their geo;
  national / superuser see all; unscoped users fail closed (empty
  response). Tests at `tests/integration/test_beneficiaries_list.py`
  assert each scope variant.
- **For DPO note — beneficiary visibility**: a partner analyst at
  UNICEF can now see every UNICEF beneficiary's name, sub_region,
  district, parish, and PMT score via this endpoint. This was
  already implicit through the DRS request flow but is now a
  direct read surface. The DPIA's existing partner-visibility
  framing covers this (each partner's DSA enumerates the field
  groups they can see; this endpoint respects the same partition
  via Programme.partner). Confirm the catalogue covers this
  read surface explicitly.
- **No new audit-event actions**. Beneficiary reads emit the
  standard read-side audit row via `AuditReadMixin`.

### US-S26-007 — Wire Beneficiary Registry screen

- **UI only**. `screens-beneficiaries.jsx` replaces the static
  `DEMO_BENEFICIARIES` fixture with the live endpoint. No new data
  collected; the screen now displays real beneficiary rows scoped
  by the operator's ABAC.
- **Personal-data categories touched**: None new. The screen
  renders the same fields the endpoint exposes.

### US-S26-008 — End-to-end test + this DPIA + changelog + memory

- **No processing impact**. Documentation + a sealing test.

### US-S11-021 — Console "Run connector" button (2026-05-26)

- **Processing activity**: New REST endpoint `POST
  /api/v1/dih/source-systems/{id}/trigger-run/` lets the System Admin
  > Connector runs tab launch a Kobo pull from the console. The
  endpoint mirrors the existing
  `pull_kobo_submissions_action` Django admin action — same DPA
  precheck, same credential decryption, same `RawLanding` →
  `StageRecord` → DQA/IDV/DDUP pipeline. No new personal data is
  collected; the pull route is **operator-surface change only**, not
  data-flow change.
- **Personal-data categories touched**: Same as the admin action it
  generalises — names, NIN-hashed identifiers, GPS, members,
  consent attestation. Already covered by the active DPA on every
  Kobo SourceSystem (`AC-DIH-DPA-REQUIRED`).
- **Lawful basis**: Unchanged — the DPA covers operator-initiated
  imports identically to scheduled imports.
- **Access control**: New DRF permission `IsDihTrigger` restricts
  the trigger to Sys Admin (`nsr_admin` group) and NSR Unit
  Coordinator (`nsr_unit_coordinator`, seeded by
  `ingestion_hub.0006_seed_nsr_unit_coordinator_group`). Anonymous
  callers and authenticated members of any other group get 403.
- **Audit**: Three new actions emitted per call —
  `dih.connector.triggered` (always, pre-call),
  `dih.connector.trigger_succeeded` or
  `dih.connector.trigger_rejected` (one of, post-call). Same
  AuditEvent table; no schema change.
- **Concurrency guard**: The endpoint refuses if a `PENDING` or
  `RUNNING` ConnectorRun exists for the source so two operators
  clicking the button at the same time can't produce overlapping
  pulls (the DB-level guarantee is still the `ConnectorRun` PK).
- **Dry-run option**: A `dry_run=true` request opens the
  ConnectorRun as `run_type=TEST`, exercises credentials +
  `list_forms`, iterates `pull_submissions` for metadata only, and
  writes **no** `RawLanding`. Useful for verifying credentials and
  the form list without persisting personal data — a deliberate
  hardening over the previous admin-action-only path.
- **For DPO note**: the operator-side change widens *who* can
  trigger a pull (from `is_staff` admins to two named groups) but
  does not widen *what* the pull touches. The DPA-required gate
  still fires inside `start_connector_run`.

- [ ] **Beneficiary listing as a new read surface** (US-S26-006)
  — confirm that partner-affiliated users seeing household head
  name + PMT score + parish/district names through this endpoint
  is within the DSA scope they already hold. None of these fields
  is new collection.
- [ ] **Encrypted webhook secret column** (US-S26-004 / ADR-0015
  §3) — confirm `Programme.webhook_secret_encrypted` is acceptable
  as a documented exception to ADR-0014's hash-only stance, with
  `WebhookCredential` factoring (OI-S26-3) as the planned
  successor.
- [ ] **`GoU-LEGACY` placeholder partner** — confirm the
  attribution SLA (OI-S26-1: operations re-attributes within 30
  days of any lift that lands rows there) is acceptable.
- [ ] **`/api/v1/ref/programmes/` removal** — confirm no partner
  MDA had this URL in their contract (none today; documented in
  the API changelog).

---

## Sign-off

- DPO: ____________________ Date: __________
- Engineering Lead: ____________________ Date: __________
- Architecture Team: ____________________ Date: __________
