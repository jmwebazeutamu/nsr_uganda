# UBOS wave intake — the instrument the registry is interpreting

**Epic:** 17. Questionnaire Authoring (US-121) · 16. Data Integration Hub (US-122)
**Module owners:** apps/intake, apps/reference_data, apps/ingestion_hub
**Status:** Not started.
**References:** ADR-0034, ADR-0032, ADR-0010; `apps/intake/cspro.py`, `apps/intake/cspro_diff.py`

## Context

UBOS is the sole collector for the first phase of national registration
and delivers household data to MGLSD in periodic waves, the first
expected late October / November 2026. The instrument is a CSPro
application UBOS owns and revises between waves, and **MGLSD cannot
refuse a wave** — so the only defence against a changed question or a
reused answer code arriving unnoticed is to read the dictionary, compare
it with the last one accepted, and never coerce a value nobody has
decided the meaning of.

Two of the four pieces are built and in use:

- `apps/intake/cspro.py` — the `.dcf` parser (pure, 39 tests)
- `apps/intake/cspro_diff.py` — the classified changeset (pure, 30 tests)
- `manage.py diff_cspro_dictionary` — command-line review
- **Admin Console → Reference data → Questionnaire** — the review screen

These two stories are the remaining halves. US-121 makes the comparison
trustworthy; US-122 makes the load safe. They are independent of each
other and can be taken in either order, but **US-122 is the one with a
deadline**: without it the review screen reports that a code changed
while the ingestion path maps it anyway.

---

### US-121 — The accepted instrument is stored, not supplied

**As an** NSR Unit data officer
**I want** the registry to hold the instrument it is currently
interpreting
**So that** a wave is compared against what is actually in force, rather
than against whichever file I happened to open

**Why this is not a convenience story.** The review screen today asks
for BOTH dictionaries. The left-hand pane cannot be verified by the
system: it is whatever the reviewer picked. Compare against the wrong
`.dcf` — an earlier wave, a draft, a colleague's copy — and the diff is
wrong *and looks authoritative*, so a clean changeset would mean
nothing. It also leaves the registry's own definition in a file somebody
has to remember to keep, which is precisely the drift US-116–120 exists
to end. The screen currently carries a visible caveat saying so; this
story removes the caveat by removing the cause.

**Acceptance criteria:**

- `import_cspro_dictionary(dcf_text, *, actor)` creates a **draft**
  `FormVersion` with `FormSection` per CSPro `[Record]` and
  `FormQuestion` per `[Item]`, mapping:
  - `DataType=Alpha` → `text`; `Numeric` with no discrete value set →
    `integer` / `decimal` (per `Decimal`); `Numeric` with a discrete
    value set → `select_one`.
  - `Occurrences > 1` → a repeat, matching the existing `begin_repeat`
    convention.
  - A value set that is **entirely ranges** is a validation bound and
    must NOT become a `ChoiceList` (`CsproValueSet.is_code_list`).
- Each discrete value set creates or versions a `ChoiceList` in
  REF-DATA, authored as **draft**, with `ChoiceOption.code` stored as a
  **string** — `07` and `7` are different answer codes.
- Retired codes are **deprecated, never deleted** (ADR-0010, ADR-0032).
- Import is idempotent and transactional: re-importing the same `.dcf`
  produces no second draft.
- The review screen's left-hand pane defaults to the **active**
  `FormVersion` and states which version it is; supplying a file
  overrides it and says that it has been overridden.
- The caveat banner ("Both sides are supplied by you") is removed only
  when the left side comes from the registry.
- An imported `FormVersion` records its provenance: source system,
  wave/run reference, the `.dcf` `Version` string, and who imported it.
- `FormVersion` approval follows the existing author-cannot-approve
  lifecycle. Approving is what makes it "the accepted instrument".

**Out of scope:** recording a mapping DECISION against a breaking
change. That is the review-and-approve workflow and needs this story
first.

---

### US-122 — An unknown answer code is never coerced

**As an** NSR Unit data officer
**I want** a value the registry cannot interpret to be held as unmapped
**So that** a guess never reaches a household's record, or its PMT band

**Why this one has the deadline.** MGLSD cannot refuse a wave, so the
mapping layer is the last place a wrong value can be stopped. Today an
unrecognised code has no defined behaviour in the DIH mapping path. The
review screen can report that code 3 changed meaning and the pipeline
will still map it.

This is ADR-0032's `EXACT` / `AMBIGUOUS` split generalised: the
legacy-frame cleanup left 48 `Employment.not_working_reason` rows on a
code with no UBOS equivalent, deliberately unmapped and reported rather
than rounded to the nearest plausible answer. That is the behaviour this
story makes routine.

**Acceptance criteria:**

- Every inbound coded value is resolved by an approved mapping, or
  recorded as **unmapped** — value preserved verbatim, never coerced,
  never dropped.
- Unmapped values are **countable and attributable**: which item, which
  code, how many records, which wave.
- A `StageRecord` carrying an unmapped value is visible as such in the
  DIH review queue. It does not read as clean. (Precedent:
  `AC-DIH-GATES-NOT-RUN` — an empty `dqa_summary` renders as
  "0 blocking, 0 warnings", so a record nothing has interpreted must not
  present like one that passed.)
- A DQA finding is raised for a record with an unmapped coded value, at
  a severity that keeps it out of the fast-track auto-promote.
- `manage.py report_unmapped_codes`, in the shape of
  `report_legacy_choice_codes`: what is unmapped, how many rows, and
  what decision is outstanding. `--format csv` for the sign-off pack.
- **Nothing in this path may choose a nearest-matching code.** Where an
  inbound code has no equivalent, the system records that it has none.
- Landing is unaffected: `RawLanding` stays append-only and complete
  (AC-DIH-LANDING-IMMUTABLE). The wave is always accepted; only
  promotion waits on interpretation.

**Out of scope:** the screen on which someone resolves an unmapped
value. Reporting is enough to start; resolution follows US-121.
