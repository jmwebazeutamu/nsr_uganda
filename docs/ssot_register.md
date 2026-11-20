# NSR MIS — Single Source of Truth Register

This register is mandatory for all implementation, review, migration, fixture,
and UI work. It supplements the solution architecture; it does not replace it.

## Required delivery discipline

Before modifying code, identify the applicable SSOT, state how the change
propagates to its consumers, and identify any API, schema, migration, fixture,
or compatibility impact. Add regression coverage for the canonical path.

- Do not hardcode scoring parameters, validation thresholds, choice values,
  lookup lists, geographic ladders, or policy enums in application or UI code.
- Do not introduce duplicate state, projections, tables, client fixtures, or
  mappings for an existing domain concept.
- Persist and exchange canonical codes/identifiers, not labels or list order.
- If a required canonical definition does not exist, stop and report a missing
  schema/configuration dependency rather than creating a local substitute.

## Canonical bindings

| Domain | Canonical source | Required consumers / rule |
| --- | --- | --- |
| Geography | `apps.reference_data.models.GeographicUnit` | Geographic hierarchy and effective units come from `GeographicUnit.Level`; household code columns derive from `Household.GEO_CODE_FIELDS`. Never map geographic names or duplicate the ladder. |
| Questionnaire variables | `apps.intake.models.FormQuestion` | Variables must retain their registered code, data type, and question provenance. |
| Data-request fields | `apps.intake.models.DataRequestFieldDefinition` | `apps.data_requests.builder_schema.build_schema()` is the server contract for DRS field selection, field groups, types, and choice bindings. UI must not use field fallbacks. |
| Choice values | `apps.reference_data.models.ChoiceList` and `ChoiceOption` | Persist canonical option codes; use labels only for display. External mappings must be versioned and explicit. |
| Household registry | `apps.data_management.models.Household`, `Member`, and owned detail entities | Do not flatten or duplicate household/member detail state in workflow or UI models. |
| PMT configuration | `apps.pmt.models.PMTModelVersion` and `PMTBandThreshold` | Weights, transforms, strategy, bands, and thresholds must be approved persisted configuration. Scores are `PMTResult` plus the current Household projection. |
| DSA and partner scope | `apps.partners.models.Partner` and `DataSharingAgreement` | Resolve active/effective DSAs from lifecycle, dates, and canonical clauses. Server-side DRS validation is authoritative. |
| Programme enrolment | `apps.partners.models.Programme` and `apps.referral.models.ProgrammeEnrolment` | Beneficiaries, Household → Programmes, and Programme → Enrolment read the same enrolment rows. Note the split: the programme definition lives in `partners`, the enrolment rows in `referral`. |
| Data-request lifecycle | `apps.data_requests.models.DataRequest` and service layer | Build, estimate, validation, preview, submit, counts, and inbox data must use the same server-derived request/DSA contract. |
| Security and operator scope | `apps.security` models and `apps.security.abac` | Roles and geographic scope enforcement are server-side and derive geography fields from `Household.GEO_CODE_FIELDS`. |
| DQA and DDUP | `apps.dqa` and `apps.ddup` domain models/services | Rules, tiers, thresholds, candidates, and decisions must be approved configuration and shared services—not module-local copies. |
| Update workflow | `apps.update_workflow.models.ChangeRequest` and `UpdRoutingRule` | Lifecycle, routing, SLA, reviewer policy, and persisted decisions are server-authoritative. |
| External ingestion | DIH raw landing, registered source-schema version, and approved mappings | Map external source variable/option/geography codes to canonical definitions. Never depend on spreadsheet column position, labels, or option ordering. Unknown values remain staged/unmapped. | A partner GRIEVANCE is the exception and is received by GRM, not promoted through DIH — the obligations in this row (an immutable landing of what arrived, approved versioned mappings, unknown values held rather than guessed) still bind and are met in `apps.grievance.external` and `StaacHandover`. See ADR-0044.
| Audit trail | `apps.security.models.AuditEvent` via `apps.security.audit.emit` | Every read or write of personal data emits through `emit`; the chain is hash-linked and append-only (`self_hash`, `occurred_at`). Never write `AuditEvent` rows directly and never backfill. List reads de-duplicate via `AUDIT_LIST_READ_DEDUPE_SECONDS`. |
| Roles | `apps.security.roles.ROLES` / `ROLE_CODES` | The role vocabulary is this tuple. UI and routing configuration reference role codes from the server; no role-name literals in JSX, fixtures, or routing tables. |
| Geographic labels | `apps.reference_data.code_frames.resolve_geographic_labels` | Code → display name resolution happens server-side and arrives as the `_labels` projection. Clients render `_labels`; they never map codes to names, infer names, or rebuild an option list from the codes present in a page. |
| Case reference numbers | `apps.reference_data.models.ReferenceSequence` via `apps.reference_data.references` | `GRM-`/`UPD-`/`DRS-`/`REF-` numbers come from `next_reference` under `select_for_update`. One counter, four prefixes. See ADR-0038, ADR-0039. Never format a reference locally or derive one from a primary key. |
| DSA field groups | `apps.data_requests.field_groups` | The disclosure-group vocabulary is derived from `builder_schema.field_catalogue()`. The console renders `catalogue()` and stores canonical group names; `LEGACY_ALIASES` exists only so signed agreements keep their meaning. No group list in JSX. See ADR-0040. |
| Grievance policy | `apps.grievance.models.GrmTierRule` and `apps.grievance.visibility.allowed_actions` | Tier ladder, required role, and SLA are configuration. The set of actions available on a case comes from `allowed_actions`; a closed case returns none. The UI renders that set and does not decide it. See ADR-0035, ADR-0036. |
| AI model registry | `apps.ai_services.models.AiModelVersion` | Every model that influences a registry workflow is a registered, dual-approved, versioned row: name, version, owner, validation date, artifact checksum. No model is loaded by path, environment variable or hardcoded name. Weights live in the approved row, not in code. See ADR-0045. |
| AI feature switches | `apps.ai_services.models.AiFeature` via `apps.ai_services.services.feature_state` | Whether an AI feature is `off`, `shadow` or `advisory` is this row, behind the master `AI_SERVICES_ENABLED` setting. Fails closed: missing row, inactive model or master flag off all read as `off`. Promotion thresholds (`gate_config`) are approved configuration with no defaults; a feature cannot reach `advisory` until they are set and met. See ADR-0045. |
| AI suggestions and runs | `apps.ai_services.models.AiSuggestion` and `AiRun` | Model output is advisory data keyed by subject. It never writes `Household`, `Member`, `MatchPair.status` or `DqaResult`; the reviewer's decision (`MergeDecision`, DQA flag handling) stays the system of record and is the evaluation label. One `ai.inference.batch` audit event per `AiRun` through `apps.security.audit.emit`, never one per item. See ADR-0045. |
| Status tone | `ui_tone` `ChoiceList` | Status → visual tone mapping is reference data. Screens must not carry their own status-to-colour tables. |

## Enforcement expectations

1. Backend contracts expose canonical data; clients consume those contracts.
2. A UI pre-check may improve usability, but it must be derived from the same
   server contract and server validation remains final.
3. A change to a canonical source requires reviewing every named consumer in
   this register and adding targeted regression tests.
4. New source-schema versions, choice options, questions, or geographic units
   require versioned configuration/mapping approval before promotion.
