"""Human case references for grievances: GRM-2026-0001.

`Grievance.id` is a ULID — `01M3AT4JSSXFYG02CXC8S6K20X`. That is the
right primary key and ADR-0002 keeps it. It is the wrong thing to say
out loud: a Parish Chief reads a case number back to a citizen over the
phone, writes it in a ledger, and quotes it on a follow-up visit two
weeks later, and twenty-six ungrouped characters do not survive that.

The reference is the number for that job. A year and a running count
inside it, restarting each January:

    GRM-2026-0001, GRM-2026-0002, ... GRM-2026-00012, ... GRM-2027-0001

Four digits is a minimum, not a cap: the 10,000th case of a year is
GRM-2026-10000, not an error.

**Why a sequence, given CLAUDE.md forbids sequential externally-visible
identifiers.** The rule is there because a running number is guessable
and leaks volume. Both remain true here:

  * Guessable — but guessing is not a way in. `?q=` filters what
    `visible_grievances` already returned, and the detail route applies
    the same rule, so a number you were not given opens nothing you
    could not already see. The sequence costs confidentiality of
    *volume*, not of records.
  * Volume — two references disclose how many grievances the registry
    took between them.

Against that: this is a number a distressed citizen has to keep hold of
and repeat accurately. The registry owner weighed the two and chose
readability, which is a decision about their own service to make. See
ADR-0038, which also amends the CLAUDE.md rule rather than leaving it
quietly broken.

Numbers come from GrmReferenceSequence under `select_for_update`, so
two cases opened at the same moment cannot take the same one, and a
rolled-back transaction releases its number rather than burning it.
"""

from __future__ import annotations

import re

PREFIX = "GRM"
PAD = 4

#: What people write instead of what they meant. A reference read over
#: a phone and typed back is where these happen.
CONFUSABLES = {"O": "0", "I": "1", "L": "1"}

_CANONICAL = re.compile(r"^(\d{4})(\d+)$")


def format_reference(year: int, number: int) -> str:
    return f"{PREFIX}-{year:04d}-{number:0{PAD}d}"


def normalise(raw: str) -> str:
    """Turn what somebody typed into the stored form, or "".

    Accepts it lower-case, without the prefix, without the dashes, with
    spaces, and with O written for zero or I/l for one — which is what
    a reference read aloud and typed back looks like. Returns "" when
    there is nothing usable, so a caller can treat it as "not a
    reference" rather than guessing.
    """
    if not raw:
        return ""
    text = "".join(str(raw).upper().split())
    text = text.replace("-", "").replace("/", "").replace("_", "")
    if text.startswith(PREFIX):
        text = text[len(PREFIX):]
    text = "".join(CONFUSABLES.get(c, c) for c in text)
    match = _CANONICAL.match(text)
    if not match:
        return ""
    year, number = int(match.group(1)), int(match.group(2))
    # A four-digit year that is not a plausible one is somebody's
    # phone number, not a case.
    if not (2000 <= year <= 2999):
        return ""
    return format_reference(year, number)


def looks_like_a_reference(raw: str) -> bool:
    return bool(normalise(raw))


def year_of(reference: str) -> int | None:
    parts = (reference or "").split("-")
    return int(parts[1]) if len(parts) == 3 and parts[1].isdigit() else None


def next_reference(year: int) -> str:
    """Take the next number for `year`.

    `select_for_update` holds the row for the rest of the caller's
    transaction, so concurrent creates queue rather than collide. The
    unique constraint on Grievance.reference is the backstop.
    """
    from .models import GrmReferenceSequence

    row, _ = GrmReferenceSequence.objects.select_for_update().get_or_create(
        year=year, defaults={"last_number": 0},
    )
    row.last_number += 1
    row.save(update_fields=["last_number"])
    return format_reference(year, row.last_number)


def assign(grievance) -> str:
    """The reference for `grievance`, numbered in the year it was
    opened — so a case raised on 31 December keeps a number from the
    year it happened, whatever day the row is written."""
    from django.utils import timezone

    opened = getattr(grievance, "opened_at", None) or timezone.now()
    return next_reference(timezone.localtime(opened).year)
