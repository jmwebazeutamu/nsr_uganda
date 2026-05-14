# ADR-0004: CAPI form runtime — build vs buy decision deferred to Sprint 1

- **Status**: Proposed (decision deferred to Sprint 1)
- **Date**: 14 May 2026
- **Owner**: NSR MIS Architecture Team
- **References**: SAD v0.6 §3.2 (CAPI row), §12 open item DDUP-O-02, ADR-0001

---

## Context

The CAPI (Computer-Assisted Personal Interviewing) channel is the dominant field intake surface for the NSR. Parish Chiefs, sub-county operators, and Field Enumerators capture household data on Android tablets in conditions that include long offline windows (Karamoja, islands, mountain zones), low-bandwidth sync (2G or 3G), and harsh outdoor environments.

The CAPI app needs:

1. **Offline-first form runtime** that can render the full NSR questionnaire (currently 7 sections, hundreds of fields, with skip logic) without network access.
2. **Encrypted local store** for captured data (SQLCipher per SAD §8.3).
3. **Queued sync** that resumes after long offline windows and handles conflicts.
4. **GPS, camera, barcode scan** for evidence capture.
5. **Form versioning**: every submission carries the FormVersion ID it was captured under.
6. **Offline DQA**: the rule pack must be applied locally so the operator does not capture data that will be rejected on sync (US-081).
7. **Provisional Registry ID** assigned at capture, printed on the receipt (US-112).
8. **Localisation** for English first, Luganda/Runyankole/Acholi/Lusoga in Phase 2.

We have three credible options. Each is a different bet on how much we build versus how much we buy.

## Decision

**Decision is deferred to Sprint 1.** This ADR exists to frame the trade-off, lock in the evaluation criteria, and constrain what each option means in code.

In the meantime, **Sprint 0 work assumes a thin Android shell that wraps whichever form runtime we pick**. The submission API contract, the rule pack format, the SQLCipher local store schema, and the sync protocol are designed to be runtime-agnostic. We do not block on this decision to start Sprint 0.

The Sprint 1 spike picks one of:

- **Option A**: Custom Android (Kotlin) with a hand-rolled form runtime.
- **Option B**: ODK-X (or ODK Collect with extensions).
- **Option C**: SurveyCTO (commercial).

## Evaluation criteria (Sprint 1 spike must produce evidence on each)

Weight each criterion 1 to 5, score each option 1 to 5, compute weighted total. The criteria and weights are:

| # | Criterion | Weight | What "good" looks like |
|---|---|---|---|
| 1 | Offline reliability across 14-day windows | 5 | Captures and syncs after a 2-week offline pilot test without data loss |
| 2 | Integration with our submission API and rule pack | 5 | Hooks for posting StageRecords, applying RulePack JSON locally, attaching provisional Registry ID |
| 3 | Encrypted local store (SQLCipher) | 5 | Encrypted at rest with a device PIN; remote wipe via MDM |
| 4 | Form versioning and skip logic fidelity | 4 | The questionnaire renders identically in Field Enumerator and Parish Chief flows; skip logic matches the master FormVersion |
| 5 | Customisation cost in our hands | 4 | Time to add a new section, change skip logic, or add a new field is under 1 day for an engineer who has not seen the codebase before |
| 6 | Total cost of ownership over 5 years | 4 | License fees, hosting cost, maintenance hours; modelled across 5,000 device-years |
| 7 | DPPA 2019 alignment | 4 | Local store encryption, audit log integration, no third-party data egress |
| 8 | Localisation effort (4 Ugandan languages) | 3 | Resource bundles or equivalent; not hardcoded English |
| 9 | Operator UX on Section 11.1 of the UI Design Brief | 3 | Stepper, photo capture, GPS capture, receipt slip integration |
| 10 | Vendor lock-in risk | 3 | If we leave the platform, exporting captured submissions is documented and tested |

Maximum weighted score: 200. The option above 150 with no criterion scored below 3 wins. If no option clears the bar, we restart the spike with a narrowed shortlist.

## Options framed in detail

### Option A: Custom Android (Kotlin)

Build a native Android app from scratch with a Jetpack Compose form runtime, SQLCipher local store, and a thin sync layer.

- **Pros**: Maximum control over UX, full alignment with the UI Design Brief, native performance, no vendor dependency, easy MDM integration.
- **Cons**: Highest upfront engineering cost. Reinvents work that ODK and SurveyCTO have done for years. Long tail of edge cases (network flakiness, OS upgrades, OEM quirks) that mature platforms have already absorbed.
- **Cost shape**: 3 to 4 person-months engineering for MVP runtime, then ongoing maintenance at 0.5 engineers continuously.
- **Risk profile**: Highest engineering risk; lowest operational risk.

### Option B: ODK-X (or ODK Collect)

Adopt an Open Data Kit variant. Forms authored in XLSForm or ODK-X table specs, runtime is the ODK Collect app or a forked variant. Sync to our server via the OpenRosa API or a custom bridge.

- **Pros**: Mature offline-first runtime, large user community in Ugandan public sector and humanitarian sector (UBOS, WFP, UNICEF teams already use ODK derivatives), free, open source. Operators trained on ODK can be redeployed.
- **Cons**: XLSForm is restrictive for our skip logic complexity. UX is functional but not branded. Integrating SQLCipher requires a fork (ODK Collect uses Android SQLite, not SQLCipher by default). Provisional Registry ID generation is not a native concept. Watermarked receipt slip needs to be added.
- **Cost shape**: 1 to 1.5 person-months to fork, integrate, and brand; ongoing 0.25 engineers for maintenance and upstream tracking.
- **Risk profile**: Medium engineering risk (fork maintenance); low UX risk if we accept the ODK look-and-feel; low operational risk.

### Option C: SurveyCTO (commercial)

Adopt SurveyCTO as a managed survey platform. Pay per device or per submission. Use their Android app, their server, and bridge into our backend via their API.

- **Pros**: Lowest engineering effort. Mature platform widely used by World Bank, IPA, and J-PAL field operations. Strong offline support, encryption built in, professional support.
- **Cons**: Vendor lock-in. Captured data sits in SurveyCTO's servers before reaching our backend, which raises a DPPA 2019 issue (data leaving Uganda before entering the NSR custody chain). Per-device or per-submission fees at 12M household scale are non-trivial. We cannot deeply customise the receipt slip flow.
- **Cost shape**: Low engineering, high recurring license. Need a quote at our scale.
- **Risk profile**: Lowest engineering risk; highest data-residency and vendor risk.

## Spike plan (Sprint 1)

The spike is one engineer for two weeks. Output is a written evaluation against the criteria table plus a working prototype for the leading option.

Specifically:

1. Build a stripped-down household intake in each option (Identification section only, 15 fields, 1 photo, GPS, NIN entry, submit to a mock backend).
2. Run each prototype in a 5-day offline test on a Karamoja-equivalent device (low-end Android, intermittent power).
3. Compare against the criteria table, score, and recommend.
4. Surface a single open question for the Architecture Team to resolve at the end of the spike, if any criterion remains unclear.

## What is locked regardless of choice

The following are independent of the runtime choice. Sprint 0 builds these on the server side and they will work with any of the three options:

- **Submission API contract** at `POST /intake/submissions`, JSON body, OAuth 2.0 client_credentials for the device, idempotency key per submission.
- **Rule pack format** as a versioned JSON document tied to a FormVersion. CAPI fetches it on sign-in.
- **Local store schema** for SQLCipher: tables for `submission_draft`, `submission_queued`, `submission_synced`, `rule_pack_cache`, `geographic_unit_cache`.
- **Sync protocol**: append-only queue, exponential backoff, conflict resolution via the server's optimistic lock per household (per ADR-0001 and SAD §4.4.9 AC-UPD-CONCURRENT).
- **Provisional Registry ID generation** server-side at first submit; the device receives the ID in the submit response and prints it on the receipt slip.
- **MDM hooks** for remote wipe.
- **Encryption-at-rest** mandated for the local store regardless of runtime.

## Consequences of deferring

- Sprint 0 cannot start on the CAPI client codebase. This is acceptable; Sprint 0 is server-heavy (DIH scaffold, DAT-DQA wired, DAT-DDUP tier 1, repo scaffold) and the CAPI client is not on the critical path.
- The team building the server-side intake must keep the API and rule pack format runtime-agnostic. This is recorded as a constraint above.
- If the spike picks Option B or C, the team will need to onboard new tools mid-Sprint 1. Mitigation: the spike engineer is also the eventual CAPI lead, so context does not transfer.

## Alternatives considered (for the framing)

### Web-only intake (drop CAPI)

Rejected. The Framework explicitly relies on CAPI for mass enumeration and parish-level on-demand. Web cannot reach offline.

### Progressive Web App (PWA)

Considered. Rejected because IndexedDB and Service Worker storage limits on Android are not predictable enough at the 14-day offline mark. Native is safer.

### Cross-platform (Flutter, React Native)

Considered. Adds a third option to the spike but with the same trade-off shape as Option A (custom build) plus a runtime dependency. Not in the shortlist because we are Android-only for the field tier; iOS is not in scope.

## Re-open triggers

1. The Sprint 1 spike completes (this ADR moves to Accepted with the chosen option).
2. A national e-government framework standardises a form runtime that NSR is mandated to adopt.
3. DPPA 2019 implementing regulations rule that SurveyCTO-style data residency is unacceptable, eliminating Option C.

## Status changes log

| Date | Change | Author |
|---|---|---|
| 14 May 2026 | Proposed; decision deferred to Sprint 1 spike | NSR MIS Architecture Team |

---

End of ADR-0004. Place at `/docs/adr/0004-capi-form-runtime.md`.
