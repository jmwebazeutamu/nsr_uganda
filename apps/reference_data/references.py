"""Case numbers people can use: GRM-2026-0001, UPD-2026-0001, …

Every externally-referenced entity in the registry has a ULID primary
key — `01M3AT4JSSXFYG02CXC8S6K20X` — per ADR-0002. That is the right
key and the wrong thing to say out loud. A Parish Chief reads a case
number back to a citizen over the phone; a partner quotes a data
request in an email; a programme officer writes a referral number in a
ledger. Twenty-six ungrouped characters do not survive any of that, and
nothing in the string says when a character has been dropped.

So four entities carry a **reference** beside their id:

    Grievance      GRM-2026-0001
    ChangeRequest  UPD-2026-0001
    DataRequest    DRS-2026-0001
    Referral       REF-2026-0001

The prefix is the module code from SAD §4, so the number says which
queue to look in before anyone has typed it anywhere.

**One implementation, four callers.** This module and the single
`ReferenceSequence` table are the whole of it. Four copies of "take the
next number for this year" would drift — and the first thing that
drifts in a numbering scheme is whether a rolled-back transaction burns
its number, which is not something anyone notices until the numbers
have gaps and nobody can say why.

Sequential, which CLAUDE.md otherwise forbids for externally-visible
identifiers. ADR-0038 records that exception and what it costs: the
numbers are guessable and they disclose volume. Guessing is not a way
in — every list and detail route applies the caller's scope first — so
the exposure is how many records exist, not what is in them. That
argument is per-module and has to hold for each: see ADR-0039.
"""

from __future__ import annotations

import re

PAD = 4

#: Module codes from SAD §4. The prefix tells an operator which queue a
#: number belongs to before they have typed it anywhere.
GRIEVANCE = "GRM"
CHANGE_REQUEST = "UPD"
DATA_REQUEST = "DRS"
REFERRAL = "REF"

PREFIXES = (GRIEVANCE, CHANGE_REQUEST, DATA_REQUEST, REFERRAL)

#: What people write instead of what they meant. A number read over a
#: phone and typed back is where these happen. Digits cannot really be
#: ambiguous, but people who have typed ULIDs all day still do it.
CONFUSABLES = {"O": "0", "I": "1", "L": "1"}

_CANONICAL = re.compile(r"^([A-Z]{3})(\d{4})(\d+)$")


def format_reference(prefix: str, year: int, number: int) -> str:
    return f"{prefix}-{year:04d}-{number:0{PAD}d}"


def normalise(raw: str, *, prefix: str | None = None) -> str:
    """Turn what somebody typed into the stored form, or "".

    Accepts it lower-case, without the dashes, with spaces or slashes,
    and with O typed for zero or I/l for one. The prefix may be omitted
    only when the caller says which one it wants — a bare "2026-0001"
    is four different records otherwise, and guessing between them is
    worse than asking.

    Returns "" when there is nothing usable, so a caller can treat it
    as "not a reference" rather than as a failed lookup.
    """
    if not raw:
        return ""
    text = "".join(str(raw).upper().split())
    for junk in ("-", "/", "_", "."):
        text = text.replace(junk, "")
    if prefix and not text.startswith(prefix) and text[:1].isdigit():
        text = prefix + text
    # Confusables apply to the digits, never to the prefix — "DRS"
    # contains no confusable, but "REF" would lose its I-less E to
    # nothing and GRM is safe; guard anyway by only mapping the tail.
    head, tail = text[:3], text[3:]
    tail = "".join(CONFUSABLES.get(c, c) for c in tail)
    match = _CANONICAL.match(head + tail)
    if not match:
        return ""
    found_prefix, year, number = match.group(1), int(match.group(2)), int(match.group(3))
    if found_prefix not in PREFIXES:
        return ""
    if prefix and found_prefix != prefix:
        return ""
    # A four-digit run that is not a plausible year is somebody's phone
    # number, not a case.
    if not (2000 <= year <= 2999):
        return ""
    return format_reference(found_prefix, year, number)


def looks_like_a_reference(raw: str, *, prefix: str | None = None) -> bool:
    return bool(normalise(raw, prefix=prefix))


def prefix_of(reference: str) -> str | None:
    parts = (reference or "").split("-")
    return parts[0] if len(parts) == 3 and parts[0] in PREFIXES else None


def year_of(reference: str) -> int | None:
    parts = (reference or "").split("-")
    return int(parts[1]) if len(parts) == 3 and parts[1].isdigit() else None


def next_reference(prefix: str, year: int) -> str:
    """Take the next number for `prefix` in `year`.

    `select_for_update` holds the row for the rest of the caller's
    transaction, so concurrent creates queue rather than collide, and
    because the increment happens inside the creating transaction a
    rollback releases the number instead of burning it. The unique
    constraint on each model's `reference` column is the backstop.
    """
    if prefix not in PREFIXES:
        raise ValueError(f"unknown reference prefix {prefix!r}")

    from .models import ReferenceSequence

    row, _ = ReferenceSequence.objects.select_for_update().get_or_create(
        prefix=prefix, year=year, defaults={"last_number": 0},
    )
    row.last_number += 1
    row.save(update_fields=["last_number"])
    return format_reference(prefix, year, row.last_number)


def assign(instance, prefix: str, *, date_field: str = "created_at") -> str:
    """The reference for `instance`, numbered in the year it was raised.

    `date_field` is whichever column records when the thing happened —
    `opened_at` for a grievance, `created_at` for the rest — so a record
    raised at 23:00 on 31 December keeps a number from the year it
    happened, whatever day the row is written.
    """
    from django.utils import timezone

    raised = getattr(instance, date_field, None) or timezone.now()
    return next_reference(prefix, timezone.localtime(raised).year)
