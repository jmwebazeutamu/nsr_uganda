# ADR-0044 — A partner grievance is received by GRM, not promoted through DIH

Status: accepted
Date: 11 October 2026
Supersedes: nothing. Clarifies the scope of the rule in ADR-0001 and `CLAUDE.md`.

## Context

NSR is to receive approved grievances from STAAC's GRM over a partner
pull API (`NSR_STAAC_GRM_API_SPECIFICATION_v1.md`, v1.1). Records
arrive from outside the registry, which brings two project rules into
contact with each other:

* `CLAUDE.md`: *"Every record entering the registry passes through
  DIH. Direct writes to DAT are not allowed."* And: *"Do not bypass
  DIH. Even Parish Chief walk-in submissions land in DIH first."*
* `docs/ssot_register.md:36`: external ingestion means *"DIH raw
  landing, registered source-schema version, and approved mappings…
  Unknown values remain staged/unmapped."*

Read literally and together, those put a STAAC grievance through
`SourceSystem → Connector → ConnectorRun → RawLanding → StageRecord →
promotion`. Read with the SAD, they do not, and the question had never
been settled in writing for an entity that is not a household.

## Decision

**A partner grievance is received by GRM. It does not pass through
DIH.** The obligations `ssot_register.md:36` places on external
ingestion — an immutable landing of exactly what arrived, and an
approved, versioned mapping of every external code — are met inside
GRM rather than waived.

The pull client lives in `apps/grievance/external/`; the landing is
`apps.grievance.models.StaacHandover`; the mapping is
`ChoiceOption.canonical_code` on the `staac_grievance_category` and
`staac_complainant_gender` lists, approved through the ChoiceList
workflow exactly as any other external code binding.

## Why

**DIH's mandate is DAT, and the SAD says so in the same breath.** SAD
§4.6 describes DIH as staging for *"raw landing, mapping to canonical
NSR shape, normalisation, pre-registry DQA, identity verification,
dedup discovery, and a final NSR Unit approval"*, with the module
table naming its output *"promotion to DAT"*. Every stage is a
household/member operation. A grievance has no NIN to verify against
NIRA and no household to deduplicate; running one through IDV and
DDUP would be running it through nothing.

**The code says the same thing more plainly than the prose.**
`promote_stage_record()` returns a `Household` and keys idempotency on
`Household.pk == provisional_registry_id`. `StageRecordState` is an
`idv_pending → ddup_review → …` ladder. `trigger_connector_pull()`
refuses anything that is not `SourceSystemKind.KOBO`. ADR-0001 states
that DIH reaches the registry through exactly one endpoint,
`POST /internal/dih/promote`. Putting grievances through DIH means
adding a second promotion target to a module defined as having one,
and a second meaning to a state machine that currently has one.

**The sentence that reads as universal names its own target.** "Every
record entering the registry passes through DIH" is followed by
"Direct writes to DAT are not allowed", and the walk-in example it
cites is a household submission handled by
`submit_walk_in_capture()`. The rule is about the registry of
households, which is the thing the rule exists to protect: the
promoted record set that PMT scores and programmes draw from.

**The precedent is already in the repository.** The STAAC grievance
intake merged in `apps/grievance/intake.py` — the category and gender
resolvers, `Grievance.source_system` / `external_reference` /
`reported_at` — creates domain records from an external source and
does not touch DIH.

## What this decision costs, and what pays for it

It costs the thing DIH is good at: one place to ask "what arrived from
outside, when, and what happened to it". Two answers now live in two
places, and an operator looking for inbound data has to know which.

What pays for it is that both halves of the DIH discipline are kept
rather than assumed:

* **The landing is immutable and separate from the interpretation.**
  `StaacHandover` stores the snapshot verbatim with
  `(handover_id, exchange_version)` — the partner's own idempotency
  key — plus the ETag, correlation id, retrieval time and the
  `shared_data.fields` manifest that records what STAAC was permitted
  to disclose for that handover. The `Grievance` is the
  interpretation; the snapshot is the evidence, and a mapping
  corrected next month is re-applied to what was actually received.
* **Unknown values are held, not guessed and not dropped.** An
  unmapped category or an unresolvable place leaves the snapshot
  stored with `outcome = HELD` and a sentence saying why, visible in
  the admin and re-filable with `pull_staac_handovers --file-held`
  once the binding is approved. This is DIH's "unknown values remain
  staged/unmapped", spelled in GRM's vocabulary.

Holding rather than refusing is the one place this differs from
`resolve_category`'s behaviour at a console form, and deliberately.
Refusing in front of an operator tells someone. Refusing inside a
server-to-server pull tells nobody: there is no operator, STAAC will
not offer the record again, and the collection moves past it. The
complaint would be lost in silence — the exact failure shape this
registry keeps finding in its own pipelines.

## Consequences

* A second inbound path exists and must be operable: the admin lists
  held snapshots and names the reason, and the management command
  reports counts per run.
* If a second partner GRM appears, this is the pattern to extend, not
  to re-decide. If instead partner intake grows beyond grievances —
  households from a partner MIS, say — that record goes through DIH,
  because it is a DAT record and this ADR does not touch that.
* `ssot_register.md:36` should be read as naming obligations, not a
  module. A future edit of that row can say so.
