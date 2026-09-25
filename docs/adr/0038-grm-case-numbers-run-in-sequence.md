# ADR-0038: GRM case numbers run in sequence, and CLAUDE.md is amended to allow it

- **Status**: Accepted
- **Date**: 25 September 2026
- **Owner**: NSR MIS Architecture Team
- **Decision-makers**: Registry owner (jmwebaze), GRM Lead (MGLSD), Engineering Lead, Data Protection Officer (to note)
- **Supersedes**: [ADR-0037](0037-a-case-number-people-can-use.md)
- **References**: ADR-0002 (identifier strategy); CLAUDE.md anti-patterns; `apps/grievance/reference.py`, `apps/grievance/models.py` (`GrmReferenceSequence`)

---

## Context

ADR-0037 gave grievances a short random reference, `GRM-7K4P-2QX9`,
specifically to avoid a sequence — because CLAUDE.md says:

> Do not use sequential primary keys for any entity exposed externally.

It shipped. The registry owner's response was immediate and specific:

> *GRM Nos - use something GRM-Year-0001, this year would be
> GRM-2026-0001, then GRM-2026-00012 next year GRM-2027-0001 etc -
> these are easy to remember and pass them on to complainers.*

That names the actual user. Not an operator with the case on screen,
but **a complainant** — often distressed, frequently on a borrowed
phone, sometimes writing the number on the back of something — who has
to keep hold of it and repeat it accurately weeks later. Eight random
characters are better than twenty-six. A year and a count are better
than eight random characters, because the year carries meaning and the
count is a small number.

## Decision

**`GRM-<year>-<n>`**, the count restarting each January:
`GRM-2026-0001`, `GRM-2026-0002`, … `GRM-2027-0001`.

Four digits is a minimum and not a cap — the ten-thousandth case of a
year is `GRM-2026-10000`.

Numbers come from `GrmReferenceSequence`, one row per year, taken under
`select_for_update` inside the transaction that creates the grievance.
Concurrent creates queue rather than collide, and a rolled-back
transaction releases its number instead of burning it, so a year's
references stay contiguous — which is most of why they are worth
reading.

A case is numbered in **the year it was opened**, not the year the row
was written, so a grievance raised at 23:00 on 31 December keeps a
number from the year it happened.

### CLAUDE.md is amended, not quietly broken

The anti-pattern now reads:

> Do not use sequential primary keys for any entity exposed externally.
> `Grievance.reference` is the one sequential identifier in the
> registry and it is not a key — see ADR-0038.

Writing code that contradicts a standing rule and saying nothing is how
a rule stops meaning anything. The exception is narrow, written down,
and attached to its reasoning.

## What this costs, stated plainly

The rule exists for two reasons and both still apply.

**It is guessable.** Anyone holding `GRM-2026-0042` can write down
`GRM-2026-0041`.

**It leaks volume.** Two references disclose how many grievances the
registry took between them — and with dates, a rate.

### Why that is acceptable here, and what makes it so

Guessing a reference is not a way into a record. `?q=` filters the
queryset `visible_grievances` has already scoped, and the detail route
applies the same rule, so a number nobody gave you opens nothing you
could not already open. A guessed reference outside your scope returns
an empty list and a 404 — the same as one that does not exist.

**That is the whole mitigation, so it is pinned by tests**
(`TestItIsASequenceAndWhatThatCosts`), including the case of an
operator who holds one reference and guesses the next. If those ever
stop passing, this amendment stops being defensible and the format
should go back to random.

The residual exposure is **volume**, not records: how many grievances
the registry has taken. For a public social registry that is closer to
a statistic than a secret — RPT reports it — but the DPO should be
aware that it is now inferable by anyone holding two case numbers, and
it is listed here rather than left to be discovered.

## Consequences

**The eight live grievances were renumbered** as `GRM-2026-0001`
upward, in the order they were opened. Renumbering is safe only because
it was immediate: ADR-0037's references had been in production for
under an hour and none had been given to anyone. **A reference is a
promise that a number keeps meaning the same case**, and after this
there is no renumbering.

**Migration 0010 was made self-contained.** It imported the
reference module to do its backfill, and when that module changed under
it the migration failed on the first fresh database. A migration
reproduces the state as of when it ran; it does not follow the code
forward.

**Still GRM only.** ChangeRequest, DataRequest and Referral have the
same readability problem and ADR-0037's note about that stands. Each is
its own decision about what its users actually quote, and each would
need this trade made again.

**Normalisation survives from ADR-0037.** A reference is accepted
lower-case, without the prefix, without the dashes, with spaces, and
with O typed for zero or I/l for one — the mistakes people make copying
a number off a slip. Digits cannot be ambiguous, but people who learned
the old alphabet still type them.
