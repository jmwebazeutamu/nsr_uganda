# NSR MIS — delivery & code-health audit

**Date:** 2026-08-08
**Scope:** spec/delivery gap and code health & tests. Security, data-protection
and CLAUDE.md conformance were explicitly **out of scope** for this pass.
**Commit audited:** `f332b3c` (branch `us-consent-foundation`, tree clean)
**Environment:** `dev` Multipass VM, Postgres 16, full suite green except one
known failure.

---

## Headline

The **code is in good shape; the paperwork is not.** Coverage is 92.7% with
very low debt, but the delivery tracker misstates what has been built, backlog
IDs are not traceable to commits, and two declared quality gates (mypy strict,
e2e tests) do not run at all.

Nothing here is a data-integrity or correctness emergency. The main risk is
**managerial**: someone reading `08_sprint_plan.xlsx` today would materially
misjudge where the project is.

---

## 1. Delivery status is misstated

`docs/08_sprint_plan.xlsx` → *Backlog Status* is the project's own tracker.

| status | Must | Should | Could | total |
|---|---|---|---|---|
| Done | 57 | 10 | 0 | **67** |
| Partial | 7 | 0 | 0 | **7** |
| Not started | 44 | 18 | 1 | **63** |
| **total** | 108 | 28 | 1 | **137** |

The sheet was last updated **2026-05-31**. **54 commits landed after that**, and
the last commit is **2026-06-21 — seven weeks ago**.

### 1.1 Epic 17 (Questionnaire Authoring) is built but recorded as untouched

All five stories US-116…US-120 read *Not started*. The code disagrees:

- `apps/intake/` ships `xlsform_export.py`, `rule_pack_sync.py`, `kobo_push.py`,
  `pii_lint.py`, form models and an API
- the dev database holds **2 FormVersions, 12 FormSections, 191 FormQuestions**
- **27 commits** reference these five story IDs, including `[US-117e]`
- `docs/stories/US-116-120_questionnaire_authoring.md` exists

`Dependencies` is stale in the same direction: **D-19** ("US-116 ChoiceList
catalogue active") and **D-20** ("US-117 Questionnaire authoring active") are
both marked *Open* and listed as blocking US-118/119/120 and the S9 CAPI
runtime — while REF-DATA holds **97 ChoiceLists / 790 ChoiceOptions**.

If the CAPI runtime decision (ADR-0004 / DEP-15) is being held back because
D-19/D-20 look open, it is being held back on bad information.

> **RECONCILED 2026-08-08.** `08_sprint_plan.xlsx` has been updated. Each of the
> five stories was re-checked acceptance-criterion by acceptance-criterion against
> `f332b3c` rather than accepting the S19 claim — and three of the five turned out
> to be **Partial**, not Done:
>
> | story | new status | what is actually missing |
> |---|---|---|
> | US-116 | **Done** | — |
> | US-117 | **Done** | — |
> | US-118 | **Partial** | `export_xlsform` command; `GET /v1/intake/form-versions/{id}/xlsform`; pyxform round-trip test; k-forms not retired to `scripts/legacy/` |
> | US-119 | **Partial** | Listener 2 (DIH draft MappingRule) and Listener 3 (canonical migration + `deprecated_at`) absent; no `needs_review` flagging |
> | US-120 | **Partial** | `kobo_push` command; `ConnectorRun(mode="push")`; stubbed-Kobo contract tests |
>
> D-19 and D-20 → **Resolved**; `Forward` S8b → Done, S8c → Partial.
> Tracker now reads Done 69 / Partial 10 / Not started 58.
>
> Note the workbook was already **internally inconsistent**: its own `Status`
> sheet recorded S19 (2026-05-15) as Done delivering US-116..120, and `Story Map`
> agreed — only `Backlog Status`, `Dependencies` and `Forward` were left behind.
> The failure was not ignorance of the work but a partial update, which is the
> same failure mode §2 predicts when status cannot be derived from the repo.

### 1.2 Overall drift

**18 of the 63** *Not started* stories have implementation evidence in code,
UI or commit subjects. Beyond Epic 17 the clearest are US-080/US-081 (DQA,
7 commits between them), US-103 and US-112 (commit + 8 UI references each).

### 1.3 The genuine remaining gap

Filtering to **Must-priority, Not started, and no evidence anywhere** leaves
**28 stories**:

| epic | n | stories |
|---|---|---|
| 11. Single Registry / Beneficiary Data Exchange | 4 | US-058 US-059 US-060 US-062 |
| 5. Dynamic Updates & Recertification | 4 | US-028 US-029 US-030 US-093 |
| 16. Data Integration Hub | 3 | US-110 US-114 US-115 |
| 2. Household & Individual Data Management | 3 | US-013 US-015 US-016 |
| 1. Intake & Registration | 2 | US-002 US-004 |
| 3. Identity Verification (NIRA) | 2 | US-018 US-019 |
| 8. Interoperability & API Gateway | 2 | US-043 US-046 |
| 10. Data Requests & Sharing | 2 | US-055 US-056 |
| 15. Deduplication & Record Matching | 2 | US-085 US-086 |
| 4 / 6 / 12 / 13 | 1 each | US-024, US-036, US-067, US-070 |

**Epic 11 is 100% unstarted** — all 4 Must and the 1 Should. That matches the
runtime: `GET /api/v1/beneficiaries/` returns `count: 0` and no Beneficiary
rows have ever existed. Single Registry / beneficiary data exchange is a
headline capability in the TOR; treat it as not begun rather than partially
delivered.

Also worth noting inside the *Partial* set: **US-091 — "No-self-approve
enforcement pending."** That is a segregation-of-duties control on an
audit-bearing approval workflow, still open.

---

## 2. Backlog-to-code traceability is broken

CLAUDE.md: *"Anchor commits to user stories. Format: `[US-XXX] short
description`."*

Reality — only **3 commits in the entire history** use a `[US-nnn]` tag. The
convention actually in use is *session* IDs (`US-S2-006`, `sprint-0/schema`) or
module tags (`[SEC]`, `[deploy]`, `[DQA]`). The backlog↔session mapping exists
**only** in the spreadsheet's `Story Map` sheet.

Consequences:

- "Which code implements US-032?" is unanswerable from the repo alone.
- The one artefact that answers it is the same spreadsheet shown above to be
  stale — so traceability depends on a stale, hand-maintained, binary file.
- For a system under DPPA 2019 with an auditable trail as a design goal, an
  external spreadsheet is a weak provenance story.

This is the root cause of §1: status is tracked by hand because it cannot be
derived.

---

## 3. Document hygiene

- **CLAUDE.md is stale.** It states *"114 stories across 16 epics"*; the backlog
  is **138 stories across 19 epics**. Since CLAUDE.md is the file every session
  is primed with, this error propagates.
- **Duplicate ADR numbers:** `0009` twice (`admin-and-console-ui-strategy`,
  `dqa-rule-editor-ui`) and `0023` twice (`data-explorer`,
  `data-explorer-risk-probe`).
- **ADR-0025 does not exist** but is cited in five code locations
  (`apps/pmt/checks.py`, `engine.py`, `feature_evaluator.py`,
  `test_v1_active_seed.py`). The PMT feature-DSL decision is therefore
  undocumented while the code claims otherwise.
- **12 of 19 API-exposing apps have no `docs/openapi/{module}.yaml`**, which
  DoD item 3 requires: missing for partners, data_management, update_workflow,
  intake, pmt, data_requests, reporting, ddup, reference_data, grievance,
  referral, identity_verification. *Mitigating:* drf-spectacular generates a
  live schema and CI validates it, so the APIs are not undocumented — the gap
  is the committed per-module contract used for contract tests.

---

## 4. Tests and code health

### 4.1 Coverage — strong

**92.7%** overall (30,470 / 32,882 statements). No app below 82%.

Audit-bearing modules named in CLAUDE.md are all well covered:
data_management **96.1%**, ddup **95.3%**, ingestion_hub **94.6%**,
dqa **92.9%**, update_workflow **92.1%**.

Weakest: referral 82.4%, data_explorer 83.2%, intake 85.6%.
Weakest single files: `admin_console/workflow_api.py` 67.4% (341 stmts),
`data_explorer/api.py` 68.0%, `consent/api.py` 72.0%.

1,904 tests collected: **1,871 pass, 1 fails, 32 skip.**

### 4.2 mypy is declared strict and never runs

`pyproject.toml` sets `[tool.mypy] strict = true` with the django-stubs plugin,
and `django-stubs`/`mypy` are dev dependencies. **mypy appears nowhere in CI**
(the 7 jobs are ruff, code-list-lint, pytest, openapi, js-test, bandit,
pip-audit).

Running it now: **5,344 errors across 316 of 454 files.**

This is a declared standard with zero enforcement. Either wire it in (starting
non-strict and ratcheting) or drop the config — leaving it as-is implies a
guarantee the codebase does not meet.

### 4.3 No end-to-end tests execute

`tests/e2e/` contains one Playwright spec (`data_explorer.spec.js`) and a
`.gitkeep`. Playwright is not a dependency, and Vitest only collects
`design/**/*.test.{js,jsx}`, so the spec is never run. The file says so itself:
*"The Playwright runner is NOT yet wired into the project."*

The `/tests/e2e/` directory in the CLAUDE.md layout is, in practice, empty.

### 4.4 19 of 32 skipped tests skip for one avoidable reason

`k-forms/build_nsr_xlsform.py` "lives outside the repo by design (hard-coded
developer paths)". Nineteen intake tests skip without it — locally *and in CI*.
Intake questionnaire export is therefore never verified by an automated run on
any machine but one developer's.

Remaining skips: 4 awaiting the `seed_data_explorer_test_corpus` command
(US-DATA-EXP-002), 3 sqlite-only (correctly skipped on Postgres), 6 various
data_explorer matview conditions.

### 4.5 Debt is genuinely low

Across 95,351 Python LOC: **6 TODOs, 0 FIXME, 0 HACK.** The 17
`NotImplementedError`s are abstract-base-class contracts (storage backends,
NIRA client seam), not stubs. Ruff passes clean on 0.16. This is a well-kept
codebase.

Two TODOs carry the placeholder story ID `US-S23-XXX`
(`partners/integrations/docusign.py`, `partners/tasks.py`) — no real story to
schedule them against.

### 4.6 One failing test — pre-existing, will redden CI

`apps/update_workflow/tests.py::TestBundleEndpoint::test_documents_reject_oversized_file`.

`DATA_UPLOAD_MAX_MEMORY_SIZE` is never set, so it is Django's 2.5 MB default,
while the UPD bundle endpoint accepts base64 documents validated at "5 MB max
per file" (~6.7 MB encoded). Django rejects the body before DRF parses, so the
endpoint's own limit is unreachable **in production too**. Passes on Django
5.2.14, fails on 5.2.17; CI installs unpinned. Fix is a settings change
(raise to ~25 MB), not a test change.

---

## 5. Recommended order

1. **Reconcile the tracker** — Epic 17 and D-19/D-20 first; they may be
   blocking the CAPI runtime decision on false information. *(hours)*
2. **Fix the upload-size bug** — one settings line; stops CI going red. *(minutes)*
3. **Correct CLAUDE.md** story/epic counts; create the missing ADR-0025;
   renumber the duplicate 0009/0023. *(hours)*
4. **Decide on mypy** — wire in non-strict with a ratchet, or remove the
   config. Do not leave 5,344 errors under a `strict = true` banner. *(days)*
5. **Bring `k-forms/build_nsr_xlsform.py` into the repo** so 19 intake tests
   run in CI. *(hours, assuming the hard-coded paths can be parameterised)*
6. **Make traceability derivable** — either adopt `[US-nnn]` in commit subjects
   going forward, or generate the Story Map from a checked-in mapping file
   rather than maintaining it by hand in a binary spreadsheet. *(days)*
7. **Epic 11 (Single Registry)** — schedule it, or record a decision that it is
   deferred. Right now it is silently at zero.

---

## Method & caveats

Evidence: full pytest run with `--cov` under CI's env against Postgres;
`mypy apps nsr_mis`; git history; `openpyxl` reads of `03_backlog.xlsx` and
`08_sprint_plan.xlsx`; token-anchored greps over `apps/ tests/ nsr_mis/
scripts/ design/`; live row counts from the dev database.

Three false leads were found and discarded during this audit; they are recorded
so the numbers above are not re-derived incorrectly:

- A naive `US-\d{3}` grep matches **inside** unrelated tokens such as
  `DSA-SUS-002`. Story-ID searches must anchor on non-alphanumeric boundaries.
- `docs/user-manual/` is **generated** and enumerates every story ID regardless
  of status, so it is not evidence of implementation. It is excluded above.
- Counting test functions only under `apps/<name>/` undercounts badly —
  data_explorer looks like 11 tests there but has **113** once `/tests` is
  included. It is not under-tested.

Not assessed: security posture, DPPA/DPIA compliance, CLAUDE.md architectural
conformance (DIH bypass, raw-SQL boundaries, audit-event coverage, ULID usage,
i18n), performance against NFRs, and the frontend beyond test collection.
