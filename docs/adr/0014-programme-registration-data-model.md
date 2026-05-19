# ADR-0014 — Programme registration data model

**Status**: Proposed
**Date**: 2026-05-19
**Authors**: NSR Unit engineering
**Sprint**: 25
**Stories**: US-S25-001, US-S25-002, US-S25-003

## Context

The Programme registration wizard at
`design/v0.1/screens/screens-programme-new.jsx` collects a richer
record than the original `apps.partners.Programme` carried after
US-S23-005 (which had only `partner`, `name`, `kind`, `status`,
`scope_text`, `geographic_units`, `beneficiary_estimate`, `start_date`,
`end_date`). The wizard also captures:

- **Identity**: short `code` (unique per partner), `summary`
- **Linked DSA**: FK to `DataSharingAgreement` (geo + entity cap)
- **Cohort & targeting**: `unit_of_enrolment`, `cohort_target`,
  `sex_filter`, `age_min`/`age_max`, `pmt_bands`,
  `composition_flags`
- **Disbursement**: `amount_ugx`, `disbursement_cycle`,
  `duration_months`, `channel`, `start_month`
- **Lifecycle**: `exit_codes_allowed`, `auto_exit_triggers`,
  `suspend_on_grievance`
- **Webhook callback**: `webhook_url`, `webhook_secret_hash`

Two related concerns:

1. **A separate `apps.referral.Programme` model exists** with its
   own `code`, `webhook_url`, `webhook_secret`, `dsa_reference`,
   plus referral and enrolment FKs. Two Programme rows for the
   same partner programme is the same antipattern ADR-0013 resolved
   for Partner + DSA. The two should consolidate; the wizard
   doesn't have to wait for it.
2. **Every coded field on the wizard must read from the DB**, per
   the project-wide ChoiceList rule (ADR-0010). The wizard's screen
   had inline arrays for kinds, units, cycles, PMT bands, exit
   reasons, composition flags, auto-exit triggers, webhook events,
   sub-regions, and partner picker rows.

## Decision

### 1. Extend `apps.partners.Programme` with the wizard's columns

The model now carries every field listed above. Coded fields stay
plain `CharField(max_length=32)` with empty `choices=`; their lists
are seeded in US-S25-001 and registered in
`apps/partners/choice_field_map.py`. The
`data_management.E001` system check fails CI if any of them grows
a `choices=` argument by accident.

JSON-array fields hold lists of ChoiceOption **codes** verbatim:
`pmt_bands`, `composition_flags`, `exit_codes_allowed`,
`auto_exit_triggers`. The serializer doesn't normalise — the wizard
reads them back exactly as it submitted, simplifying the round-trip.

`webhook_secret_hash` stores `sha256(cleartext)`. The cleartext is
returned exactly once in the create response under
`webhook_secret_cleartext` (a write-only synthetic field) and is
never persisted. Rotation is out-of-scope for US-S25; the operator
can recreate the programme or wait for the rotation story.

### 2. Linked DSA is an optional FK, not a M2M-only join

`Programme.dsa` is a nullable FK to `DataSharingAgreement`. The
canonical many-to-many on `DataSharingAgreement.programmes` from
US-S23-006 stays; the FK is a convenience for the wizard's single-
DSA picker and for the "active DSA at registration time" pointer.
A future story can converge the two if needed; the data model
tolerates both.

### 3. Unique constraint is partial — `(partner, code)` where code is non-empty

`UniqueConstraint(fields=["partner", "code"], condition=Q(code__gt=""))`.
The wizard allows a partner programme to be saved as a draft before
the operator has settled on a short code, so an empty-string `code`
must not collide with another empty-string `code` on the same partner.
The serializer skips DRF's auto-generated `UniqueTogetherValidator`
(it would mark `code` as required) and does the partial-uniqueness
check manually in `validate()`.

### 4. `apps.referral.Programme` consolidation is deferred

The wizard writes to `apps.partners.Programme`. `apps.referral.Programme`
keeps its existing Referral and ProgrammeEnrolment FKs; the two
Programme classes still coexist. A Sprint 26 follow-up will repeat
the Sprint 24 path-C consolidation pattern: data migration to lift
referral.Programme rows into apps.partners.Programme (matching by
code), repoint Referral.programme / ProgrammeEnrolment.programme FKs,
drop the referral-side model.

This deferral is explicit because referral.Programme still has
TextChoices (`ReferralStatus`, `EnrolmentStatus`) — converting those
to ChoiceList-backed coded fields is part of the same consolidation.
It's larger than the wizard wiring slice.

### 5. The wizard's geographic constraint reads the active DSA

The geo step at `design/v0.1/screens/screens-programme-new.jsx`
fetches `GET /api/v1/dsas/?partner=<id>&status=active` for the
selected partner, takes the first row, and reads its
`geographic_scope` (list of GeographicUnit IDs). Sub-region buttons
outside that allowlist render as disabled. The user can still
select them, but the wizard surfaces a "N regions outside the DSA
scope" warning and `outOfScopeGeo` is non-empty — the API does not
yet block the create on this; that lands as a follow-up validation
in the `ProgrammeViewSet.perform_create` path (`OI-S25-1`).

## Consequences

**Gains**

- The wizard is wire-able end-to-end against the live API without
  any data normalisation step in JSX.
- Every coded selector reads from the DB; adding a new programme
  kind or exit reason is a single ChoiceList row, no code change.
- The audit chain captures `programme_created` events with
  structured `field_changes` (partner_code, code, kind,
  cohort_target) — same shape the Sprint 23 dashboard activity
  feed already consumes.

**Costs**

- The Programme model has gained 17 new columns (code, summary,
  dsa FK, unit_of_enrolment, cohort_target, sex_filter,
  age_min/age_max, amount_ugx, disbursement_cycle, duration_months,
  channel, start_month, pmt_bands, composition_flags,
  exit_codes_allowed, auto_exit_triggers, suspend_on_grievance,
  webhook_url, webhook_secret_hash). It's a deliberately wide row;
  splitting into `Programme + ProgrammeCohort + ProgrammeSchedule`
  was rejected for over-engineering at this stage.
- `webhook_secret_hash` is non-rotatable today. A small follow-up
  needs to land before the wizard's webhook contract is ready for
  the partner MIS to consume.
- Two Programme classes still coexist (see decision 4). New code
  that needs the canonical Programme writes to
  `apps.partners.Programme`. The referral side stays as-is.

## Migration policy

Forward-only per ADR-0003. The reverse plan removes the 17 new
columns and the partial-unique constraint; the JSON-array fields
fall back to empty default. Existing rows from US-S23-005 inherit
the new columns at their default values (NULL / empty list).

## Open items

- **OI-S25-1**: server-side reject when `geographic_units` includes
  IDs outside the parent DSA's `geographic_scope`. Today the wizard
  surfaces it, the API tolerates it.
- **OI-S25-2**: programme signature workflow (mirroring ADR-0012's
  DSA signature chain — partner Data Steward sign-off before a
  draft becomes active). The wizard's submit modal advertises the
  three-step chain but the workflow itself isn't shipped.
- **OI-S25-3**: webhook secret rotation endpoint.
- **OI-S25-4**: consolidate `apps.referral.Programme` into
  `apps.partners.Programme` (Sprint 26 candidate).

## References

- ADR-0010 — Coded fields via ChoiceList
- ADR-0011 — Partners module
- ADR-0012 — DSA signature workflow
- ADR-0013 — Canonical Partner + DSA in apps.partners
