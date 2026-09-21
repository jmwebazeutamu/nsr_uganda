# ADR-0034: Stage the instrument, not just the records — UBOS field waves

- **Status**: Proposed
- **Date**: 21 September 2026
- **Owner**: NSR MIS Architecture Team
- **Decision-makers**: NSR Unit Coordinator, MGLSD–UBOS liaison, Data Protection Officer, Engineering Lead
- **References**: SAD §4.6 (DIH); ADR-0007 (connector framework); ADR-0010 (choice lists and coded fields); ADR-0032 (one choice code frame); `apps/ingestion_hub/`, `apps/intake/models.py` (`FormVersion`), `apps/reference_data/models.py` (`ChoiceList`)

---

## Context

For the first phase of national registration, **UBOS is the sole
collector**. Household data is gathered in the field on a CSPro
instrument that UBOS owns and develops, and delivered to MGLSD in
**periodic waves**. The first wave is expected **late October /
November 2026**. Once the NSR is established, NSR's own channels take
over exclusions and updates, but they do not collect the baseline.

Two things follow from that, and they pull in opposite directions.

**The instrument will change between waves.** Questions get added,
reworded, dropped; answer-code lists get revised. This is normal for a
survey operation of this size and is entirely within UBOS's remit.

**MGLSD cannot refuse a wave.** UBOS owns the instrument. The registry
has to accept and interpret whatever arrives; there is no version of
this where MGLSD tells the national statistical authority that its
questionnaire is unacceptable and declines the data.

Today, only the *data* is expected to arrive. The instrument can be
asked for — the CSPro tool is still in development — but nobody has
asked yet, and there is **no Data Provision Agreement with UBOS**.

### Why this matters, concretely

This has already happened once, and nothing caught it.

Six housing lists and two employment lists ended up carrying two
competing answer-code frames simultaneously — a legacy single-digit
frame beside the UBOS 2024 frame — so the capture wizard offered
"Detached" (1) beside "Detached house (Bungalow)" (11), and "Hut" twice.
Two enumerators coding the same hut produced different values, and no
analysis downstream could tell whether a difference between two
households was real. It was found by a person noticing a duplicate
label in a dropdown, months after both frames were in the data
(ADR-0032). 562 employment rows were affected; 48 still cannot be
mapped at all and are waiting on an MGLSD decision.

That is what an unreviewed instrument change looks like. Nothing
alerted; nothing failed; the data simply became ambiguous.

### What already exists

More than a fresh start, and worth being precise about.

- **Record staging is complete.** DIH lands every inbound payload raw
  and immutable (`RawLanding`, AC-DIH-LANDING-IMMUTABLE), maps it
  through a versioned `MappingRuleVersion`, stages it as a
  `StageRecord` with a provisional Registry ID, and admits it to the
  registry only through the promotion API. There is no other write path
  into DAT.
- **A questionnaire registry exists.** `apps.intake.FormVersion` holds a
  versioned instrument with first-class `FormSection` / `FormQuestion` /
  `FormSkipLogic` / `FormConstraint` children and a draft → submitted →
  approved lifecycle (`author`, `approved_by`, `approved_at`).
  `FormQuestion.choice_list_ref` points at `ChoiceList`.
- **Answer codes are already governed.** `ChoiceList` is versioned and
  approvable; `ChoiceOption` has `active` / `deprecated` states, where
  deprecated means "readable for historical records, not selectable on
  new intake".
- **Inbound agreements are modelled and enforced.**
  `start_connector_run` refuses to open a run without an active
  `DataProvisionAgreement` (AC-DIH-DPA-REQUIRED).

**What does not exist**: any CSPro support anywhere in the codebase, any
diff between one instrument version and the next, and any surface on
which a change is reviewed before its data is interpreted.

### A finding uncovered while writing this

All six `DataProvisionAgreement` rows are Sprint 0 placeholders:
`signed_at` is NULL, `approved_by` is empty, `scope` is `{}`, and the
`purpose` field reads "Sprint 0 baseline DPA — replac[e]…". One of them
is `DPA-UBOS-BULK-2026`, valid to 2031.

`_has_active_dpa()` tests only the validity dates. So the control that
exists to stop data being ingested without an agreement is currently
**satisfied by an unsigned seed row**, for every source including UBOS.

## Decision

### 1. Stage the instrument inside DIH. Do not build a second platform.

The request that prompted this was "can we have a data staging
platform?". The answer is that the record-staging platform already
exists and is sound; what is missing sits one level up, at the
instrument.

A separate platform would mean a second place household data rests and
a second route toward the registry, which is the precise anti-pattern
CLAUDE.md names ("Do not bypass DIH. Even Parish Chief walk-in
submissions land in DIH first"). The instrument layer is added to the
pipeline that exists.

### 2. The CSPro data dictionary is a condition of supply, in the DPA

There is no DPA with UBOS yet, so this costs nothing to include now and
is expensive to retrofit later. MGLSD asks for, and the DPA names:

1. **The `.dcf` data dictionary for every wave, versioned.** This is the
   one that matters. It is the machine-readable definition of every item
   and every value set, in a parseable text format. For CSPro's native
   flat-file export it is not optional — the file cannot be parsed at all
   without it, because the dictionary is what defines the column
   positions. Even from a CSV or JSON export, answer codes arrive as
   bare numbers with nothing stating what they mean.
2. **The `.ent` / `.apc` application and logic**, for skip patterns and
   validations. Valuable, not essential.
3. **A change note per wave**: what changed against the previous
   version, and the intended mapping. UBOS made the change and already
   knows what it means; capturing it at source turns NSR's job from
   archaeology into review. This is the cheapest artefact in the list
   and the highest value.
4. **Delivered before or with the data, never after.** This is the
   clause people drop, and dropping it converts the whole arrangement
   from a control into a post-mortem.

None of this asks UBOS to change its instrument or seek approval for it.
It asks only that the definition travel with the data it defines.

### 3. "Unmapped" is a first-class, countable state. Never coerce.

This is the load-bearing decision, and it follows directly from being
unable to refuse a wave.

Every inbound coded value is either **mapped by an approved rule**, or
**held as unmapped** — stored, preserved, counted and visible on the
record — and never silently resolved to the nearest plausible code.

There is no "best guess" path. ADR-0032 established the pattern for the
legacy frames (an `EXACT` map for pairs that mean the same thing, an
`AMBIGUOUS` list for everything else, with the ambiguous values left
alone and reported); this generalises it to every wave. The reasoning is
unchanged: these fields feed the Proxy Means Test, and a fabricated
answer becomes a wrong PMT band, which becomes a household that does not
receive a transfer.

The system's job is to make "we do not know what this means" impossible
to overlook, not to make it go away.

### 4. MGLSD absorbs the wave. It does not promote blind.

"Cannot refuse" is precise, and its precision is what makes the rest
workable:

| | |
|---|---|
| **The wave is accepted** | The delivery is never rejected. The payload lands in `RawLanding` whole and immutable, the run is recorded, UBOS is not blocked or asked to resubmit. |
| **Records still stage** | Landing is not promotion. A record carrying an unmapped code stages and waits, exactly as a record with a DQA finding does today. |
| **Promotion still requires interpretation** | A value nobody can interpret does not enter the registry as though it had been understood. |

This is the existing DIH contract, not a new power. UBOS's authority
over the instrument is real and is not in question here; it does not
extend to placing an uninterpretable value into the national registry
under MGLSD's name.

### 5. A UBOS value-set change becomes a new `ChoiceList` version

Not a parallel vocabulary store. The CSPro value sets *are* choice
lists, and `ChoiceList` already has versioning, an approval workflow and
`deprecated` option semantics that mean precisely "still readable, no
longer selectable".

The importer authors a new `ChoiceList` version as **draft**; NSR Unit
data staff approve it. Retired codes are deprecated, never deleted —
past responses must remain interpretable (ADR-0010, ADR-0032).

### 6. NSR Unit data staff decide the mapping, under dual approval

The mapping decision is a statistical judgement, not an engineering one,
and it belongs to the NSR Unit's data staff. It therefore needs a
**review-and-approve screen**, not a mapping file in a pull request,
following the author-cannot-approve pattern already used by `DqaRule`,
`ChoiceList` and `FormVersion`.

**Interim, stated plainly**: that screen will not exist by late October.
If wave 1 lands first, engineering performs the mapping as a reviewed
code change in the shape of `apps/reference_data/legacy_code_frames.py`,
and the ADR for that wave records who decided each mapping and why. That
is a stopgap with an expiry, not the design.

### 7. Build order

Driven by the wave date, not by tidiness:

**Before wave 1 (must):** DPA with UBOS including the clauses in §2; a
CSPro `.dcf` parser producing a `FormVersion`; unmapped-value capture in
the mapping layer so nothing is coerced; replace the placeholder
`DPA-UBOS-BULK-2026` row.

**Before wave 2 (should):** the instrument diff against the last
accepted version, as a report; the unmapped-value report, in the shape
of `manage.py report_legacy_choice_codes`.

**Phase 2 (when NSR begins collecting):** the review-and-approve screen;
the accepted `FormVersion` becomes the definition NSR's own capture
channels are generated from, rather than a second instrument maintained
alongside it.

## Consequences

- **The accepted `FormVersion` is not per-wave throwaway work.** It
  accumulates into the canonical definition that NSR's own collection
  must conform to in phase 2. Getting the registry right early is worth
  more than it appears while UBOS is the only collector.
- **`DPA-UBOS-BULK-2026` must be replaced before wave 1** with a real,
  signed agreement. Until then the system will ingest UBOS data believing
  it is covered.
- **`_has_active_dpa()` should also require `signed_at`.** One line. It
  will fail every seeded source in development until the seeds are
  fixed, which is the correct outcome and the reason it is proposed here
  rather than applied silently.
- **Wave 1's mapping will likely be manual.** Better to plan for that
  than to discover it in November.
- If the `.dcf` does not arrive with wave 1, the fallback is inferring
  the instrument from the payload. It is worse in every respect — value
  labels are unrecoverable, and a code that has been *redefined* rather
  than added is undetectable. Naming it here so the cost of not asking
  is on the record.

## Open items

| Ref | Item | Owner | By |
|---|---|---|---|
| OI-UBOS-01 | Draft and sign the UBOS DPA, including the §2 supply clauses | MGLSD–UBOS liaison, DPO | Before wave 1 |
| OI-UBOS-02 | Confirm the CSPro export format UBOS will use (native flat file / CSV / JSON) — it decides the parser | Engineering Lead | Oct 2026 |
| OI-UBOS-03 | Expected wave size and delivery mechanism (SFTP, physical media, API) | NSR Unit Coordinator | Oct 2026 |
| OI-UBOS-04 | Name the NSR Unit data staff who own mapping decisions, and their approver | NSR Unit Coordinator | Before wave 1 |
| OI-UBOS-05 | Decide whether `_has_active_dpa()` gains the `signed_at` requirement, and reseed | Engineering Lead | — |

## Alternatives considered

**A separate staging platform, outside the MIS.** It is what was
originally asked for, and it is the wrong shape: household data would
rest in two places with two routes toward the registry, and the
immutable-landing and promotion guarantees would have to be rebuilt or
abandoned. What was missing was never a second platform, only the
instrument layer above the one that exists.

**Block the wave until the change is reviewed.** Not available — UBOS
owns the instrument — and §4 gets most of the protection without
requiring an authority MGLSD does not have.

**Auto-map by nearest matching label.** Superficially attractive and
directly responsible for the incident in the Context: it produces a
clean-looking registry in which some values mean something nobody
decided. Rejected.

**Handle each wave as a one-off engineering task.** Which is the status
quo, and it is the interim position for wave 1. As a permanent answer it
puts a statistical judgement in an engineer's hands, leaves no approval
trail, and produces nothing phase 2 can generate NSR's own instrument
from.
