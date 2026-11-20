# ADR-0045: AI services are an advisory layer with a registry, a kill switch and one audit event per run

- **Status**: Proposed — needs Data Protection Officer sign-off on D2 and D5 before any feature leaves `shadow`
- **Date**: 20 November 2026
- **Owner**: NSR MIS Architecture Team
- **Decision-makers**: NSR Unit Coordinator, Data Protection Officer, Engineering Lead
- **References**: SAD §4.2 (DQA), §4.3 (DDUP), §8.4 (audit); ADR-0021 (chatbot); ADR-0022 (DQA rule language); ADR-0029 and ADR-0043 (audit chain); `docs/ssot_register.md`; DPPA 2019

---

## Context

The registry holds personal data on households under DPPA 2019. We want
machine-learned help in two places where reviewers already make a
recorded decision: ranking duplicate candidates (DAT-DDUP) and flagging
statistical anomalies (DAT-DQA). Both already have a human decision that
doubles as a label, and both are advisory by nature.

Four facts in the repository shape the decision:

1. **Rules, thresholds and model versions are already approved
   configuration** (`DqaRule`, `DdupModelVersion`, `PMTModelVersion`) with
   dual approval. An AI model is a fourth instance of the same thing and
   must not become a way around it.
2. **The audit chain serialises every write on one row** (ADR-0029). The
   8 October load test measured the cost: 30,000 events in one
   transaction took 14.4 s, and throughput falls as writers are added.
   One audit event per scored item would reproduce the discovery-scan
   problem ADR-0043 describes.
3. **ADR-0021 already sends content to an external provider** (Anthropic)
   for the staff assistant. That is acceptable for manuals. It must not
   become the path personal data takes.
4. **The labelled data is small.** The registry held about sixteen
   duplicate pairs when last counted, and a few hundred households. A
   learned model trained on that would be noise. The framework is worth
   building now; activation has to wait for labels.

## Decision

### D1. AI is advisory. It never writes registry state

Model output is stored as `AiSuggestion` rows and read by the existing
review screens. It does not write `Household`, `Member`,
`MatchPair.status` or `DqaResult`, and it cannot approve, reject, merge
or block. The reviewer's decision stays the system of record. DIH
remains the only door in; nothing here bypasses it.

### D2. Personal data reaches only models run inside our own boundary

Runtime `local` runs the model in the application or Celery process. A
model that needs a separate serving endpoint (a large language model, for
example) is a new runtime, needs its own ADR and a hosting decision, and
is out of scope. Until that ADR exists there is no HTTP model endpoint
and no `http` runtime. The external provider in ADR-0021 stays limited to
non-personal content. **ADR-0021 CHB-O-02 and its "later sprints extend
retrieval to dataset summaries" sentence must be re-read against this
decision before that extension is built.**

### D3. Models are registered, versioned and dual-approved

`AiModelVersion` carries name, version, task, owner, validation date,
artifact checksum, runtime and status, with the same lifecycle as
`DdupModelVersion`: draft, pending approval, active, retired, author not
equal to approver, one active version per name enforced by the database.
Weights are a JSON artifact stored in the approved row and verified
against its checksum when loaded. No pickle, no model loaded by file path.

### D4. A feature is `off`, `shadow` or `advisory`, and fails closed

- `AI_SERVICES_ENABLED` (settings, default `False` in every environment,
  not tied to `DEBUG`) is the master switch.
- `AiFeature.state` is the per-feature switch, changeable at runtime by
  an authorised operator without a deploy, audited every time.
- `shadow` computes and stores suggestions that no screen shows, so they
  can be measured against reviewer decisions first.
- `advisory` lets screens show them.
- A missing row, a missing or inactive model, or the master switch off
  all read as `off`. Turning a feature off stops new runs immediately and
  hides existing suggestions.

### D5. One audit event per run, not per item

Each run writes one `AiRun` row and one `ai.inference.batch` event
through `apps.security.audit.emit`, carrying the run id, feature, model
name and version, state, item count and subject type. It carries no
personal data. Per-item detail lives in `AiSuggestion`, which is
reachable from the event by `run_id`. Changes to a feature's state and
model lifecycle each emit their own event. `AuditEvent.action` is free
text up to 64 characters, so the new action names need no migration.

**For the DPO:** this reads SAD §8.4 as "every read or write of personal
data is traceable to an event", which per-run events with item rows
satisfy, rather than as "one event per record scored". If the DPO reads
it the stricter way, ADR-0043's asynchronous sealing is a prerequisite.

### D6. Promotion from `shadow` to `advisory` is gated by approved configuration

`AiFeature.gate_config` holds the thresholds a feature must meet:
minimum labelled reviewer decisions, minimum precision against them, and
so on. **They have no defaults, and this ADR does not choose them.** A
feature cannot enter `advisory` while `gate_config` is empty or the
measured evaluation does not meet it. The numbers are a policy call for
the NSR Unit and the DPO.

### D7. Evaluation joins to the reviewer's recorded decision

For DDUP ranking the label is `MergeDecision.action` on the pair,
read by join at evaluation time. It is not copied onto the suggestion:
a copy is a second record of the same decision and would drift. For DQA
anomaly flags there is **no recorded reviewer disposition of an AI flag
yet**. Until one exists that feature cannot produce an evaluation, so it
cannot meet its gate and stays in `shadow`. That is a missing
dependency, reported rather than worked around.

### D8. Vocabulary is owned by the existing modules

- DDUP model features are the keys of `MatchPair.per_field_scores`, which
  come from the active `DdupModelVersion` tier 3 config. A model that
  names a feature the pairs do not carry is rejected at approval.
- DQA anomaly fields are paths in the payload produced by
  `apps.dqa.pipeline.household_to_dqa_payload`. A model that names a path
  that payload does not carry is rejected at approval.
- Tier numbering: in code, tier 1 is NIN, tier 2 is phone and tier 3 is
  probabilistic. The AI ranker re-orders pairs from any tier and is named
  `ddup.rank`. It is not "tier 2".

Each rule gets a contract test that asserts against both originals.

### D9. The pipeline: chained ranking, watermarked scoring

- **DDUP ranking** runs when the nightly `discover_pairs_task` succeeds, via
  a Celery `task_success` handler in `apps.ai_services`. It is not given a
  beat slot, which could fire before discovery finishes, and DDUP does not
  import this app.
- **DQA anomaly scoring** runs hourly at :45, from a watermark (the newest
  `Household.updated_at` a run covered), at most `AI_ANOMALY_BATCH_SIZE`
  households per run. An idle hour writes no run row and no audit event.
- Both tasks check the switch first and return `{"status": "off"}` when the
  feature is off, so a kill switch is not a Celery failure.

**Known gap.** `household_to_dqa_payload` reads `age`, but `Member` stores
`age_years`, so a model on `members.*.age` validates (the key is in the
payload) and then scores nothing on real rows. The vocabulary check in D8
proves a name exists in the producer, not that the producer fills it. A test
pins the behaviour. The fix belongs in the DQA payload producer, and the
`AC-HOH-AGE` family of rules reads the same key, so it is not changed here.

## Consequences

- Nothing a model says changes a record. The worst case is a wasted
  review.
- Shadow mode produces the measurements the DPO and NSR Unit need before
  anything is shown, at no risk to reviewers.
- A feature stays dark until real labels exist. With the current volume
  that means DDUP ranking and DQA anomaly stay in `shadow` for some time.
  That is the intended outcome, not a gap.
- Per-run audit weakens the literal per-item reading of §8.4 (see D5).
- Weights as JSON limit model families to those that serialise that way
  (linear and robust-statistics models). Tree ensembles need either a
  JSON serialisation or a safe artifact format and a new ADR.

## Open items

| Id | Item | Owner |
|---|---|---|
| AI-O-01 | DPO reading of SAD §8.4 for per-run events (D5) | DPO |
| AI-O-02 | `gate_config` thresholds per feature (D6) | NSR Unit, DPO |
| AI-O-03 | Whether any use case needs a hosted model endpoint, and where | Engineering Lead, NITA-U |
| AI-O-04 | Re-read ADR-0021 CHB-O-02 against D2 | DPO |
| AI-O-05 | Training labels: count of reviewer decisions per feature, measured on production | Engineering Lead |
| AI-O-06 | Who may change a feature's state (proposed: NSR Unit coordinator role) | NSR Unit |
