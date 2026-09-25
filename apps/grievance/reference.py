"""Human case references for grievances.

`Grievance.id` is a ULID — `01M3AT4JSSXFYG02CXC8S6K20X`. That is the
right primary key and ADR-0002 keeps it: unique without coordination,
sortable by creation time, and no sequence to leak how many cases the
registry holds.

It is the wrong thing to say out loud. A Parish Chief reads a case
number back to a citizen over the phone, writes it in a ledger, and
quotes it in a follow-up visit. Twenty-six characters with no grouping
cannot survive that. Every transcription is a chance to drop a
character, and nothing about the string tells you when you have.

So a grievance now also carries a **reference**: `GRM-7K4P-2QX9`.

Eight significant characters, Crockford base32 — the same alphabet the
ULID uses, so nothing new has to be explained — grouped in fours.

Crockford's alphabet is the point. It omits I, L, O and U, so there is
no I/1 or O/0 to confuse, and no U, which keeps accidental words out.
Its decoder also maps the mistakes people actually make: someone who
writes O for 0, or I or l for 1, still resolves to the right case. That
is what `normalise` does, and it is why this is worth having over a
plain random string.

**Random, not sequential.** A running number would be easier still to
read, and it would tell anyone who saw two references how many
grievances the registry took between them — and let them walk the range.
CLAUDE.md forbids sequential externally-visible identifiers for exactly
that reason. 32^8 is about 1.1 x 10^12, and the column is unique, so a
collision is a retry rather than a problem.

The reference is for people. The ULID stays the key, stays in the URLs
and stays in the audit chain; nothing about the record's identity
changes.
"""

from __future__ import annotations

import secrets

#: Crockford base32: no I, L, O or U.
ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

PREFIX = "GRM"
GROUP = 4
GROUPS = 2
LENGTH = GROUP * GROUPS

#: What people write instead of what they meant. Crockford's own
#: decoding rules: O is zero; I and L are one.
CONFUSABLES = {"O": "0", "I": "1", "L": "1"}


def generate() -> str:
    """A new reference. `secrets`, not `random`: this is an identifier
    people will quote, and a predictable one invites guessing even
    where the scope check is what actually protects the record."""
    body = "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))
    return format_reference(body)


def format_reference(body: str) -> str:
    """Group the significant characters for reading aloud."""
    groups = [body[i:i + GROUP] for i in range(0, len(body), GROUP)]
    return "-".join([PREFIX, *groups])


def normalise(raw: str) -> str:
    """Turn what somebody typed into the stored form, or "".

    Accepts it lower-case, without the prefix, without the dashes, with
    spaces, and with the confusable characters written wrongly — all of
    which is what a reference read over a phone and typed back looks
    like. Returns "" when there is nothing usable, so a caller can
    treat it as "not a reference" rather than guessing.
    """
    if not raw:
        return ""
    text = "".join(raw.upper().split())
    text = text.replace("-", "").replace("_", "")
    if text.startswith(PREFIX):
        text = text[len(PREFIX):]
    text = "".join(CONFUSABLES.get(c, c) for c in text)
    if len(text) != LENGTH or any(c not in ALPHABET for c in text):
        return ""
    return format_reference(text)


def looks_like_a_reference(raw: str) -> bool:
    return bool(normalise(raw))


def assign(grievance, *, attempts: int = 8) -> str:
    """Give `grievance` a reference nobody else has.

    Collision at 32^8 needs roughly a million cases before it is worth
    thinking about, and the column is unique either way — so this
    retries rather than reserving anything.
    """
    from .models import Grievance

    for _ in range(attempts):
        candidate = generate()
        if not Grievance.objects.filter(reference=candidate).exists():
            return candidate
    raise RuntimeError(
        "could not find a free grievance reference in "
        f"{attempts} attempts — the keyspace may be exhausted",
    )
