# ADR-0039: Case numbers for ChangeRequest, DataRequest and Referral

- **Status**: Accepted
- **Date**: 25 September 2026
- **Owner**: NSR MIS Architecture Team
- **Decision-makers**: Registry owner (jmwebaze), UPD/DRS/REF leads (MGLSD), Engineering Lead, Data Protection Officer (to note)
- **Extends**: [ADR-0038](0038-grm-case-numbers-run-in-sequence.md)
- **References**: ADR-0002 (identifier strategy); `apps/reference_data/references.py`, `apps/reference_data/models.py` (`ReferenceSequence`)

---

## Context

ADR-0038 gave grievances `GRM-2026-0001` because a ULID is not
something a complainant can keep hold of and repeat. ADR-0037 had
already noted that three other entities have the same problem, and the
registry owner then asked for the same treatment:

> *do the same for ChangeRequest, DataRequest and Referral*

Each is quoted to somebody outside the screen it lives on:

- **ChangeRequest** — ADR-0002 called its ULID "the citizen-facing
  reference code", which is precisely the claim that did not survive a
  Parish Chief reading one out.
- **DataRequest** — a partner quotes it in email; a DSA officer writes
  it in a decision note.
- **Referral** — a programme officer quotes it back when asking what
  happened to a household.

## Decision

The same scheme, with the SAD §4 module code as the prefix:

| | |
|---|---|
| `ChangeRequest.reference` | `UPD-2026-0001` |
| `DataRequest.reference` | `DRS-2026-0001` |
| `Referral.reference` | `REF-2026-0001` |

The prefix means a number says which queue to look in before anyone has
typed it anywhere.

**One implementation.** `apps/reference_data/references.py` and a single
`ReferenceSequence` table serve all four. GRM's own counter, added a few
hours earlier as `GrmReferenceSequence`, was migrated into it rather
than left as a fourth copy.

That is not tidiness. Four copies of "take the next number for this
year" would drift, and **the first thing that drifts is whether a
rolled-back transaction burns its number** — which nobody notices until
a year's numbering has gaps and nobody can say why. There is a test for
exactly that property, parametrised across all four prefixes.

**Numbered in the year the thing happened**, from whichever column
records it: `opened_at` for a grievance, `sent_at` for a referral,
`created_at` for the other two. A record raised at 23:00 on 31 December
keeps a number from the year it happened.

**A bare number is refused.** `normalise("2026-0001")` returns nothing,
because that string is four different records; the caller must say
which prefix it wants, or the number must carry one. Guessing between
four modules is worse than asking.

**ProgrammeEnrolment did not get one.** It is a programme-side record
that nobody rings the registry about. The test of whether an entity
needs a case number is whether a person quotes it, not whether it has a
ULID.

## Consequences

**The existing rows were backfilled** in creation order — four change
requests, nine data requests, no referrals yet. As with ADR-0038, that
is safe only because it happened before any number had been given to
anybody, and **there is no second renumbering**: a reference is a
promise that a number keeps meaning the same record.

**The volume disclosure now covers four counts, not one.** ADR-0038
accepted that a sequence tells anyone holding two references how many
records came between them. That now applies to updates, data requests
and referrals as well as grievances — and the counts are separated by
prefix, so each is readable on its own. For a public social registry
these are closer to statistics than secrets, and RPT reports most of
them, but the DPO should have all four written down rather than
discover them.

**The guessability argument has to hold per module.** It rests on every
list and detail route applying the caller's scope before anything else.
For grievances that is `visible_grievances`; for the other three it is
each viewset's own ABAC mixin. If any of those is ever loosened, the
case numbers stop being merely readable and start being an index.

**`?q=` on all four list endpoints** normalises before matching, using
the same module the number was issued from. A second implementation of
"O means 0" in JavaScript is how the two come to disagree, so the
console sends the raw string and lets the server decide.
