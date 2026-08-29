"""Consent as an access attribute — reusable query-layer gates.

`apps.consent.services` already answers "is this member blocked for this
purpose?" (`is_blocked`, `blocked_member_ids`). What was missing is the
household-level answer and a single idiom for applying either to a queryset —
so each surface hand-rolled it and the DRS extract ended up filtering only the
*embedded member* rows while emitting the household row regardless.

Two rules, both deliberately narrow:

**Member-level.** A member whose consent for any of the given purposes is
WITHDRAWN or REFUSED is excluded. Un-captured consent is *not* blocking — the
registry's core function does not rest on per-record consent, and
`ConsentRecord` is empty for every household captured before consent capture
existed. Blocking on absence would empty the registry.

**Household-level.** A household is excluded when its **head** is blocked.
This follows the precedent already set by `apps.referral.services`, which gates
new referrals on the head's REFERRAL consent. Household-level data — location,
GPS, PMT band, assets — is the head's to speak for; using "all members
blocked" instead would let a single consenting member expose the household, and
"any member blocked" would over-block a household because one adult opted out.

Both are inert when `CONSENT_MODULE_ENABLED` is off, and when no purposes are
supplied — a caller that passes nothing gets no filtering, which is why callers
that *should* filter need a test proving they pass something.
"""

from __future__ import annotations

from collections.abc import Iterable

from apps.consent import services as consent_services


def blocked_member_ids(purpose_codes: Iterable[str]) -> set[str]:
    """Member ids blocked for ANY of `purpose_codes` (WITHDRAWN / REFUSED)."""
    blocked: set[str] = set()
    for code in purpose_codes or ():
        blocked.update(consent_services.blocked_member_ids(code))
    return blocked


def blocked_household_ids(purpose_codes: Iterable[str]) -> set[str]:
    """Household ids whose HEAD is blocked for any of `purpose_codes`.

    Households with no head recorded are never blocked: absence of a head is a
    data-completeness problem, not a withdrawal, and treating it as one would
    silently drop records from extracts.
    """
    member_ids = blocked_member_ids(purpose_codes)
    if not member_ids:
        return set()

    # Import here so this module stays importable from migrations.
    from apps.data_management.models import Household

    return set(
        Household.objects
        .filter(head_member_id__in=member_ids)
        .values_list("id", flat=True),
    )


def exclude_blocked_members(qs, purpose_codes: Iterable[str], *,
                            field: str = "id"):
    """Exclude blocked members from a Member queryset (or a related path)."""
    ids = blocked_member_ids(purpose_codes)
    return qs.exclude(**{f"{field}__in": ids}) if ids else qs


def exclude_blocked_households(qs, purpose_codes: Iterable[str], *,
                               field: str = "id"):
    """Exclude households whose head is blocked, from a Household queryset."""
    ids = blocked_household_ids(purpose_codes)
    return qs.exclude(**{f"{field}__in": ids}) if ids else qs
