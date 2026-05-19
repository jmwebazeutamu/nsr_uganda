# DPIA — Sprint 25 Impact Recording

**Status**: For DPO review.
**Last updated**: 2026-05-19.
**Covers**: US-S25 — Programme registration wizard wired to the
canonical Partner + DSA model (commits 001–005).
**Parent document**: `/docs/dpia.md` (initial DPIA, 2026-05-14).
**Previous instalment**: `/docs/dpia/sprint_24_impacts.md` (Sprint 24).

---

## Sprint 25 stories with personal-data impact

### US-S25-001 — Programme-wizard ChoiceLists seeded

- **Processing activity**: Reference data only — 8 new ChoiceLists
  (`programme_unit_of_enrolment`, `programme_disbursement_cycle`,
  `programme_pmt_band`, `programme_exit_reason`,
  `programme_composition_flag`, `programme_auto_exit_trigger`,
  `programme_webhook_event`, `programme_sex_filter`) plus two new
  options on `programme_kind` (`grant`, `subsidy`). No personal data
  touched. Forward-only seed migration with named author tag
  (`system-migration-programmes`) so a Sprint 25 rollback is safe.
- **Personal-data categories touched**: None.

### US-S25-002 — Programme model extension

- **Processing activity**: Extends `apps.partners.Programme` with
  17 new columns covering identity, cohort targeting, disbursement
  details, lifecycle policy, and a webhook callback. Existing rows
  inherit defaults (NULL / empty list). No backfill of personal
  data; the wizard creates new rows going forward.
- **Personal-data categories touched**: None new. The wizard captures
  programme *configuration* (eligibility filters, disbursement
  amounts, channels), not personal data about beneficiaries. The
  beneficiary roster lands separately via the enrolment flow.
- **PMT band, composition flag, age range, sex filter — note for DPO**:
  These are *eligibility criteria*, not individual personal data.
  Storing them on the Programme means the registry holds a record of
  which adolescent-girl, female-headed, Karamoja-resident cohort the
  partner is targeting. This carries an obligation to declare the
  targeting in the DPIA at the *partner level* per DPPA 2019. The
  Programme record itself is not personal data; the join to
  individual records is via referrals + enrolments downstream.

### US-S25-003 — Programme CRUD endpoint

- **Processing activity**: `POST /api/v1/programmes/` creates a
  draft Programme. The endpoint is ABAC-scoped via
  `PartnerScopedQuerysetMixin`: partner-affiliated users see only
  programmes belonging to their own Partner; NSR Unit / national /
  superuser see all. Write actions respect the
  `PARTNERS_MODULE_ENABLED` feature flag.
- **Personal-data categories touched**: None. No beneficiary fields
  on this surface.
- **New audit-event action**: `programme_created` lands with
  structured `field_changes`: `{partner_id, partner_code, code, kind,
  cohort_target}`. Same shape as the Sprint 23 dashboard activity
  feed; no PII in the payload.
- **Webhook secret handling**: A 32-byte cryptographically random
  secret is generated at create-time. Only `sha256(secret)` is
  persisted on `Programme.webhook_secret_hash`. The cleartext is
  returned exactly once in the create response under
  `webhook_secret_cleartext` and never persisted. **DPO consideration**:
  the audit row's `field_changes` does NOT include the cleartext or
  the hash, by design. Rotation is `OI-S25-3` (a future endpoint).

### US-S25-004 — Wizard JSX wired to the live API

- **Processing activity**: UI only. Replaces every hardcoded option
  array on `design/v0.1/screens/screens-programme-new.jsx` with a
  `useChoiceList` lookup; replaces `PARTNER_OPTIONS` with
  `GET /api/v1/partners/?status=active`; replaces `SUB_REGIONS` with
  `GET /api/v1/reference-data/geographic-units/` filtered to
  `level="sub_region"`. The partner-pick step also fetches the
  selected partner's active DSA to constrain the geographic scope.
- **Personal-data categories touched**: None.

### US-S25-005 — Lint gate + integration tests + this DPIA

- The `scripts/lint/no_hardcoded_choice_lists.py` gate is extended
  to cover `screens-programme-new.jsx` and the seven new banned
  identifiers (`PROG_KINDS`, `PROG_UNITS`, `PROG_CYCLES`,
  `PMT_BANDS`, `SUB_REGIONS`, `EXIT_REASONS_LIST`,
  `PARTNER_OPTIONS`). Future PRs reintroducing inline arrays fail CI.
- Integration tests at `tests/integration/test_programme_wizard.py`
  walk an end-to-end submit, asserting label resolution, geo M2M
  wiring, webhook-hash semantics, and the `programme_created`
  AuditEvent.
- **Personal-data categories touched**: None.

---

## DPO review checklist

- [ ] **Eligibility-criteria storage** — confirm that storing
  PMT bands + composition flags + age + sex on the Programme record
  meets the DPIA declaration obligation at the partner level
  (per Sprint 23 partner DPIA, expand to programme-level if needed).
- [ ] **Webhook secret one-shot disclosure** — confirm the create
  response is allowed to carry `webhook_secret_cleartext` once.
  Alternative is an OOB delivery channel (email to partner IT/Sec
  contact); we kept it on the response for the wizard's UX.
- [ ] **No backfill of personal data** — confirm that defaulted
  rows from US-S23-005 carrying NULL targeting (no
  `composition_flags`, no `pmt_bands`, etc.) need no migration
  treatment.
- [ ] **Programme audit volume** — the create endpoint emits one
  AuditEvent per call. No retry coalescing; this is a low-volume
  endpoint (a few writes per partner per month at most).

---

## Sign-off

- DPO: ____________________ Date: __________
- Engineering Lead: ____________________ Date: __________
- Architecture Team: ____________________ Date: __________
