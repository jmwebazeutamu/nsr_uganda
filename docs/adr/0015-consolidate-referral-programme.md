# ADR-0015 — Consolidate `apps.referral.Programme` into `apps.partners.Programme`

**Status**: Proposed
**Date**: 2026-05-20
**Authors**: NSR Unit engineering
**Sprint**: 26
**Stories**: US-S26-001 (this ADR), US-S26-002 … US-S26-008
**Parent ADRs**: ADR-0010 (coded fields), ADR-0011 (partners module),
ADR-0013 (canonical Partner + DSA), ADR-0014 (programme registration model)

## Context

Two `Programme` model classes coexist in the codebase today:

| Model | Sprint introduced | Carries | FK dependents |
|---|---|---|---|
| `apps.referral.Programme` | Sprint 2 (pre-S22) | `code` (unique), `name`, `description`, `webhook_url`, `webhook_secret` (cleartext), `dsa_reference` (free-text), `is_active` | `Referral.programme`, `ProgrammeEnrolment.programme` |
| `apps.partners.Programme` | Sprint 23 (US-S23-005), extended in Sprint 25 (US-S25-002) | partner FK, code, name, kind/status (coded), DSA FK, cohort/disbursement/lifecycle/webhook columns | `DataSharingAgreement.programmes` (M2M) |

The duplication is the same antipattern ADR-0013 resolved for
`Partner` + `DataSharingAgreement` in Sprint 24. It is now blocking
two slices:

1. **The Beneficiary Registry screen** (US-S25-007) is wired to live
   ChoiceLists and partner-side programmes, but its enrolment ledger
   reads from a `DEMO_BENEFICIARIES` array — there is no joined
   listing endpoint because the FKs point at the wrong `Programme`.
2. **Two TextChoices remain in the active codepath** —
   `apps.referral.ReferralStatus` and `apps.referral.EnrolmentStatus`.
   ADR-0010 mandates ChoiceList-backed coded fields. These were
   skipped in earlier sprints because the consolidation was blocked
   on this ADR.

`apps.referral.Programme` is read-only at
`GET /api/v1/ref/programmes/` (basename `programme`). One external
write surface exists on `Referral` + `ProgrammeEnrolment`. No
production data exists yet — the dev DB has zero rows in any of
the three referral models.

## Decisions

### Decision 1 — Path C: lift rows to canonical, repoint FKs, drop legacy

Same recipe as ADR-0013 (Sprint 24, Partner + DSA consolidation):

1. Add canonical columns to `apps.partners.Programme` for fields the
   referral side carries but the partners side doesn't yet:
   `webhook_secret_encrypted`, `dsa_reference_legacy`, and the
   `is_active` ↔ `status="active"` boolean shim during the
   transition.
2. Data migration lifts every `apps.referral.Programme` row into
   `apps.partners.Programme` matching by `code`. ULID re-use is
   preserved where possible (the referral-side `id` becomes the
   partners-side `id` for new lifts; existing partners-side rows
   keep their ULIDs and the referral rows are dropped).
3. Schema swap repoints `Referral.programme` and
   `ProgrammeEnrolment.programme` FKs to
   `apps.partners.Programme`.
4. Delete the `apps.referral.Programme` model, its
   `ProgrammeViewSet`, its serializer, and the
   `/api/v1/ref/programmes/` route. Update `apps.referral.services`
   (`send_referral`, `accept_referral`, `enrol_household`,
   `exit_enrolment`) to import from `apps.partners.models`.

### Decision 2 — Partner attribution: greenfield with operator-driven seed

The referral side has no partner FK; the canonical row requires
one. **Production is greenfield today** (zero rows in
`apps.referral.Programme` per the 2026-05-20 inventory). The
migration is therefore a no-op against current data.

For future-proofing, the lift migration accepts an unattributed
referral.Programme row by:

1. Looking for an `apps.partners.Programme` with the same `code` —
   if one exists, the referral row is dropped without lifting
   (deduplication).
2. Else, looking for a Partner whose `code` is the prefix of the
   referral programme code (e.g. `OPM-PDM` → Partner code `OPM`).
3. Else, attributing to a "GoU-Legacy" Partner row (synthesized
   idempotently by the migration, status `provider`,
   `monthly_row_budget=NULL` so the budget detector skips it).
   Operations re-attributes the programme later through the admin.

This avoids inventing a "Legacy" Partner unless production actually
hits the third path.

### Decision 3 — Webhook signing: encrypted cleartext on canonical Programme

The referral side stores `webhook_secret` as a 64-char CharField
(cleartext). `apps.referral.services.send_referral_webhook` uses
it to HMAC-sign outbound payloads.

ADR-0014 stored only `sha256(secret)` on
`apps.partners.Programme.webhook_secret_hash`, with one-shot
cleartext disclosure on create. **HMAC signing needs the
cleartext.** Two reconciliation options:

- **(a)** Add `apps.partners.Programme.webhook_secret_encrypted`
  (an `EncryptedBinaryField`, same KMS path as
  `PartnerContact.nin_value`). The lift migration moves the
  cleartext into this column. New programmes from the wizard
  populate both `webhook_secret_encrypted` AND
  `webhook_secret_hash`; the cleartext disclosure remains
  one-shot, but the encrypted column lets the signing path
  decrypt-on-demand. **Cleanest end-state.**
- **(b)** Move the signing logic to a `WebhookCredential` model
  that owns the cleartext encrypted-at-rest. **Better separation
  of concerns, larger blast radius, slips Sprint 26 by ~2
  commits.**

**Adopting (a)** — the column-level encrypted field matches the
pattern already used elsewhere in the partners module, and the
data migration becomes a straight copy. The `WebhookCredential`
factoring (b) becomes `OI-S26-3`, deferred.

### Decision 4 — Status code alignment

`apps.referral.EnrolmentStatus` uses `enrolled / suspended /
exited`. The `programme_enrolment_status` ChoiceList seeded in
US-S25-006 uses `active / suspended / pending / exited`. The
screen at `design/v0.1/screens/screens-beneficiaries.jsx` uses
the ChoiceList vocabulary.

Resolution: the model field is renamed in data, `enrolled` →
`active`. `pending` is a derived state (not an enrolment state at
all): when a Referral exists in status `sent` or `accepted` but
no ProgrammeEnrolment has been created yet, the listing endpoint
projects it as `pending`. This keeps `programme_enrolment_status`
covering only the persisted states and lets the beneficiary
listing synthesize `pending` on the API surface.

`apps.referral.ReferralStatus` (`sent, accepted, enrolled,
rejected, exited`) lands as-is in a new `referral_status`
ChoiceList (US-S26-002).

### Decision 5 — Drop `/api/v1/ref/programmes/` outright; no deprecation window

External consumers: none. The endpoint has only ever been used
by the (still-unbuilt) referral workbench. The API changelog
records the removal. `/api/v1/ref/referrals/` and
`/api/v1/ref/enrolments/` stay; their response shapes change in
two ways: `status` now resolves a `<field>_label` companion per
ADR-0010, and `programme` (FK) now points at the canonical
partners-side row.

## Consequences

**Gains**

- Single `Programme` model across the registry. The Beneficiary
  Registry endpoint (US-S26-006) becomes a straight join.
- Last two live TextChoices declarations (`ReferralStatus`,
  `EnrolmentStatus`) leave the codebase.
- DSA scope cap, partner attribution, and the
  `programmes ↔ DSA` M2M from ADR-0011 now apply to every
  programme uniformly — no two-tier model where the referral side
  ignores DSA.

**Costs**

- The new `webhook_secret_encrypted` column on
  `apps.partners.Programme` is a deliberate exception to
  ADR-0014's hash-only stance. Documented; revisit when
  `WebhookCredential` (OI-S26-3) ships.
- Forward-only migration policy means rollback is operational
  (re-create the referral.Programme rows from the partners-side
  data) — not a Django reverse migration. Acceptable because no
  production data exists.

## Migration policy

Forward-only per ADR-0003. The reverse plan is documented but not
implemented; the partners-side rows are sufficient to reconstruct
the referral-side surface if rollback is ever needed (none of the
referral fields are append-only).

Migration order (one file per ticket, applied in this sequence):

1. US-S26-002 — `0007_seed_referral_choice_lists.py` in
   `apps.reference_data` (referral_status).
2. US-S26-003 — `0006_strip_textchoices_align_codes.py` in
   `apps.referral` (drops `choices=`, renames `enrolled` →
   `active`, registers choice_field_map).
3. US-S26-004 — `0006_programme_webhook_secret_encrypted.py` in
   `apps.partners` (adds the encrypted column) +
   `0007_lift_referral_programme.py` in `apps.referral` (lifts
   rows).
4. US-S26-005 — `0008_repoint_programme_fks.py` in
   `apps.referral` (alters FK target) +
   `0009_delete_referral_programme.py`.

## Open items

- **OI-S26-1** — When (if ever) a production environment lifts
  `apps.referral.Programme` rows with no matching Partner code
  prefix, operations must re-attribute the "GoU-Legacy"
  programmes within 30 days. Tracked in the runbook.
- **OI-S26-2** — Webhook signing path needs the
  `webhook_secret_encrypted` column populated for legacy
  programmes; the wizard's one-shot cleartext disclosure means
  new programmes populate it at create time. The signing service
  reads it via the EncryptedBinaryField in-process decryption.
  Document the key-rotation impact in the next DPIA.
- **OI-S26-3** — Factor webhook credentials into a separate
  `WebhookCredential` model with its own rotation lifecycle.
  Deferred to keep Sprint 26 scoped. The encrypted column on
  Programme is a temporary measure; this ADR will be amended
  when the credential model lands.
- **OI-S26-4** — `is_active` boolean on referral.Programme is
  dropped in favour of `status == "active"`. The
  `apps.referral.services.send_referral` guard now reads
  `programme.status != "active"`. Document for any external
  caller (none today).

## References

- ADR-0010 — Coded fields via ChoiceList
- ADR-0011 — Partners module
- ADR-0013 — Canonical Partner + DSA in apps/partners (the
  Path-C template this ADR follows)
- ADR-0014 — Programme registration data model
