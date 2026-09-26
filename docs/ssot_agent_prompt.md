# SSOT digest — for agent prompting

A short, pasteable form of `docs/ssot_register.md`, for dropping into an agent
or subagent prompt where the full register is too long.

**`docs/ssot_register.md` is authoritative.** This file is a digest of it. If the
two disagree, the register wins and this file is the bug.
`tests/contract/test_ssot_digest.py` asserts that every path and symbol named
below still resolves, so the digest cannot rot silently — but a *stale rule* is
not something a test can catch. Re-read the register when the wording matters.

---

## Paste from here

```
CANONICAL SOURCES (NSR MIS). Read docs/ssot_register.md before implementing.
Use the named source. Do not hardcode, re-derive, mirror, or alias it. If the
contract you need does not exist, stop and report a missing schema dependency
rather than inventing a local field, enum, threshold, or list.

Geography            apps.reference_data.models.GeographicUnit
                     Ladder: Region > Sub-region > District > County >
                     Sub-county > Parish > Village (GeographicUnit.Level).
                     Household geo columns: Household.GEO_CODE_FIELDS.
Geo labels           apps.reference_data.code_frames.resolve_geographic_labels
                     Arrives as the `_labels` projection. Clients render it.
                     Never map a code to a name client-side; never build an
                     option list from the codes present in a page of rows.
Choice values        apps.reference_data.models.ChoiceList / ChoiceOption
                     Persist codes, display labels. Status tone = `ui_tone` list.
Questionnaire vars   apps.intake.models.FormQuestion
DRS field defs       apps.intake.models.DataRequestFieldDefinition
                     Server contract: apps.data_requests.builder_schema
                     .build_schema() and .field_catalogue(). No UI fallbacks.
DSA field groups     apps.data_requests.field_groups.canonical_groups()
                     / .catalogue(). No group list in JSX. (ADR-0040)
Household registry   apps.data_management.models.Household, Member, detail
                     entities. Do not flatten or duplicate into UI models.
PMT config           apps.pmt.models.PMTModelVersion, PMTBandThreshold
                     Weights, band_strategy, band_cutoffs, thresholds are
                     approved persisted config. Scores are PMTResult.
Partners / DSA       apps.partners.models.Partner, DataSharingAgreement
                     Server-side DRS scope validation is authoritative.
Programmes           apps.partners.models.Programme and
                     apps.referral.models.ProgrammeEnrolment (note the split)
Data requests        apps.data_requests.models.DataRequest + service layer
Roles                apps.security.roles.ROLES / ROLE_CODES
                     No role-name literals in JSX, fixtures or routing tables.
Scope / authz        apps.security.abac (scope_q_for_field,
                     user_can_access_household). Server-side. Never weaken a
                     scope or permission check to make a test pass.
Audit                apps.security.models.AuditEvent via
                     apps.security.audit.emit. Hash-linked, append-only
                     (self_hash, occurred_at). Never insert rows directly.
DQA / DDUP           apps.dqa, apps.ddup models + services. Shared services,
                     called by both DIH and the registry. One implementation.
Update workflow      apps.update_workflow.models.ChangeRequest, UpdRoutingRule
                     Routing, SLA and reviewer policy are configuration.
Grievance policy     apps.grievance.models.GrmTierRule and
                     apps.grievance.visibility.allowed_actions. A closed case
                     allows nothing. UI renders the set, never decides it.
                     (ADR-0035, ADR-0036)
Case references      apps.reference_data.models.ReferenceSequence via
                     apps.reference_data.references.next_reference.
                     GRM-/UPD-/DRS-/REF- from one counter. Never format a
                     reference locally or derive one from a primary key.
                     (ADR-0038, ADR-0039)
External ingestion   DIH raw landing + registered source-schema version +
                     approved mappings. Never depend on column position,
                     labels, or option order. Unknown values stay unmapped.

RULES
1. Absolute zero hardcoding of geography, programme rules, PMT bands and
   thresholds, choice lists, roles, validation rules, statuses, mappings or
   operational limits. Fail safely and report missing config.
2. No parallel models or duplicate structures. Reuse the existing model,
   serializer, service and API. The UI consumes server-derived canonical data;
   it may format, it may not decide policy.
3. Server enforcement. Validation, eligibility, scope, authorization and
   lifecycle live in a shared server-side policy service. A UI pre-check must
   use the same contract, and server validation detail is shown verbatim.
4. Persist and exchange canonical codes, never labels or list order.

BEFORE IMPLEMENTING, report: the SSOT paths in play, the data flow, schema
dependencies and breaking changes, and whether a migration, fixture or API
change is needed.
AFTER IMPLEMENTING: add regression tests for the canonical path AND a failure
case, verify each test fails when the fix is removed, then run the backend
suite, the UI suite, `manage.py check` and `git diff --check`. State which
files changed and what remains unstaged.
```

## Stop here

### Known open violations

These are reported, not fixed — an agent given the digest above will flag them
again, which is correct. Do not treat them as precedent.

| Where | Violation |
| --- | --- |
| `design/v0.1/screens/screens-registry.jsx` | CSV export drops region / county / sub_county |
| `design/v0.1/screens/data-explorer-shared.jsx` | `DE_COVERAGE_ROWS` — fabricated coverage whose geo codes do not overlap the registry |
| `design/consent-handoff/components.jsx` | Hardcoded `GEO` tree |
| `design/v0.1/screens/screens-admin-workflow-routing.jsx` | ~20 role literals instead of `ROLE_CODES` |
| Console, several screens | ~19 local status vocabularies instead of `ui_tone` |
| `design/v0.1/screens/screens-partner-drs.jsx` | Drops `scope_violations` from the server response |
| `apps/data_requests/field_groups.py` | `DESCRIPTIONS` is a hardcoded group→sentence map |
| Data dictionary | `Shock` has no disclosure group, so shock fields are ungrantable |
