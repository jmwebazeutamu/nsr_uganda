# US-123–129 — Survey Data Hub completion and separation

**Status:** Proposed backlog addition  
**Source:** Survey Data Hub Build Specification (22 September 2026); ADR-0001; ADR-0007; ADR-0009; ADR-0034  
**Architecture decision:** The Survey Data Hub is the separately deployable evolution of the existing Data Integration Hub (DIH). It owns upstream survey ingestion, immutable raw data, review, mappings, and the outbound exchange. The NSR registry remains authoritative for household/person records, PMT, eligibility, enrolment, and case management.

## US-123 — Establish the deployable Hub boundary and NSR exchange contract

**Priority:** Must  
**Module:** DIH (ING), API Gateway, Platform  
**Actor:** NSR MIS Architecture Team

As the NSR MIS Architecture Team, I want the Survey Data Hub/DIH boundary and its versioned NSR exchange contract defined and deployed independently, so that survey-source churn cannot write directly into the registry.

### Acceptance criteria

- An ADR defines the Hub’s data ownership, trust boundary, service identity, network policy, failure handling, and retention responsibilities.
- The Hub runs with its own deployable process and logical database; it has no direct write access to registry household, person, PMT, eligibility, enrolment, or case-management tables.
- A versioned, authenticated internal API accepts only approved exchange records from the Hub.
- The exchange contract and its error responses are published in OpenAPI and protected by contract tests.
- The registry accepts an idempotency key, Hub record ID, source submission ID, Kobo form version, mapping version, and approval timestamp on every request.
- The contract has an explicit 12-month version/deprecation policy.

## US-124 — Preserve immutable Kobo submissions, attachments, and source lineage

**Priority:** Must  
**Module:** DIH (ING), Platform  
**Actor:** Source Admin

As a Source Admin, I want every Kobo submission and attachment preserved as an immutable, integrity-checked source record, so that collection history remains auditable despite later review or questionnaire changes.

### Acceptance criteria

- Each record retains Kobo asset/project ID, form ID, submission ID, collection/update timestamps, enumerator, device metadata, survey round, form version or form hash, payload, and deletion status.
- Duplicate polling/replay is idempotent on the Kobo source identity and does not create a second raw source record.
- A cryptographic source hash is stored and verified when the payload is read or exported for audit.
- Raw payloads and attachment bytes are archived in approved encrypted object storage; attachment metadata and object keys are stored separately.
- A database-level append-only control prevents UI, ORM, and direct SQL updates or deletes of raw records except through a documented retention/archive procedure.
- Access to raw PII, exact GPS, NINs, and attachments is restricted and audited.

## US-125 — Register and resolve Kobo form, version, and survey-round lineage

**Priority:** Must  
**Module:** DIH (ING), Intake, Reference Data  
**Actor:** Data Manager

As a Data Manager, I want Kobo forms, their archived definitions, versions, and survey rounds governed alongside the existing FormVersion catalogue, so that historical submissions render and validate against their real questionnaire.

### Acceptance criteria

- Kobo project/form identities link to a registered survey round and the relevant NSR FormVersion without replacing the existing questionnaire-authoring model.
- Every form version records effective dates, form hash, archived XLSForm/definition location, release notes, author, approver, and approval timestamp.
- When Kobo lacks a reliable version value, deterministic form-hash and effective-date resolution selects the historical version and records the rationale.
- Added, renamed, retired, and materially re-coded questions are represented as version changes; a rename never silently inherits a previous field meaning.
- Multiple versions can coexist in search, validation, and viewer rendering.
- Version and survey-round changes emit audit events and require Data Manager approval.

## US-126 — Turn DQA/DDUP results into a version-aware survey review workflow

**Priority:** Must  
**Module:** DIH (ING), DAT-DQA, DAT-DDUP  
**Actor:** Data-quality Reviewer

As a Data-quality Reviewer, I want configurable, form-aware validation issues and duplicate signals in an assigned review workflow, so that I can resolve, reject, or document exceptions without changing source records.

### Acceptance criteria

- Existing shared DQA and DDUP services remain the source of validation and matching logic; the Hub does not fork their implementations.
- Validation results create reviewable issues with rule/version, severity, field path, message, detected time, status, reviewer, and resolution note.
- Issue lifecycle supports open, in review, resolved, approved exception, and rejected; every transition is audited.
- Rules can be scoped to form/version, survey round, geography, and source system and require governed activation.
- Required-field, type/range, skip-logic, composition, geography, duplicate, enumerator/device, and NSR-exchange readiness checks are supported.
- Only the appropriate approval role may move a record to approved; the reviewer who edits a staged interpretation cannot approve it.

## US-127 — Deliver the secure submission viewer and reviewer queue

**Priority:** Must  
**Module:** DIH (ING), Console, Security  
**Actor:** Data-quality Reviewer, Supervisor, Analyst

As an authorized Hub user, I want a form-aware submission viewer and review queue, so that I can safely find, assess, and act on survey records across questionnaire versions.

### Acceptance criteria

- Django admin remains the audit-safe operational fallback while the production console is delivered; the existing JSX design harness is not treated as the production UI.
- Users can search and filter by submission/household identifiers, name, masked NIN/phone, enumerator, date, geography, survey round, form version, lifecycle state, and issue severity within their authorized scope.
- The viewer renders the relevant historical questionnaire labels, repeats, permitted attachments, exact GPS/map view, raw JSON/XML audit view, review history, and NSR synchronization outcome.
- Reviewer actions are stored separately from raw data with user, timestamp, decision, rationale, and issue history.
- Analyst views are de-identified by default; raw PII, NIN, exact GPS, and attachments require explicit role and ABAC checks.
- All sensitive reads, review actions, exports, and configuration changes emit audit events.

## US-128 — Govern approved-record transformation and idempotent NSR synchronization

**Priority:** Must  
**Module:** DIH (ING), API Gateway  
**Actor:** Data Manager, NSR MIS Integration Account

As a Data Manager, I want approved survey records transformed through an independently versioned NSR exchange mapping and synchronized idempotently, so that source-form changes cannot corrupt the registry.

### Acceptance criteria

- Inbound source-to-canonical mappings and approved canonical-to-NSR exchange mappings are separate governed artefacts.
- Each outbound mapping identifies source path, NSR target field, transformation, code translation, requiredness, mapping version, author, approver, and approval timestamp.
- A renamed Kobo question or changed response code requires a new approved mapping; no name-based equivalence is inferred at export time.
- Only approved submissions create an export event; rejected, held, or review-required records cannot call the NSR API.
- Requests are idempotent and persist safe request metadata, response status, returned NSR identifiers, retry count, timing, and protected error details.
- Temporary failures retry with bounded backoff; uncertain matches and permanent failures enter a manual reconciliation queue.

## US-129 — Operate the Hub safely at pilot scale

**Priority:** Should  
**Module:** DIH (ING), Security, Reporting, Platform  
**Actor:** System Administrator, DPO

As a System Administrator and DPO, I want monitoring, retention, recovery, and pilot controls for the Hub, so that Kobo collection can be introduced without creating an unmanaged shadow registry.

### Acceptance criteria

- Scheduled Kobo polling, future webhook ingestion, ingestion/sync failure alerts, and a reconciliation dashboard are operationally monitored.
- Backup, restore, retention, legal-hold, and incident-response procedures cover raw payloads, attachments, review records, mappings, and sync events.
- Hub-specific role permissions are enforced at API and UI layers, not only declared in the role catalogue.
- Load and recovery testing demonstrates at least 100,000 submissions without a schema redesign and validates replay/idempotency behavior.
- Pilot rollout proceeds through archive-only ingestion, reviewer-only validation, and a limited approved export cohort with reconciliation before broader promotion.
- Deployment, access-review, and DPO sign-off runbooks are version-controlled and linked from the pilot release checklist.

## Sequencing

1. US-123 and US-124 establish the security and integration boundary.
2. US-125 and US-126 make source history and review decisions trustworthy.
3. US-127 provides the operator surface over that governed workflow.
4. US-128 enables controlled registry transfer.
5. US-129 is the pilot-readiness gate; it must complete before production Kobo promotion.

