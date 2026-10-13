"""Translate an external grievance into this registry's vocabulary.

NSR receives grievances from STAAC's GRM. The two systems classify
differently — STAAC has sixteen codes under its own versioned ruleset,
NSR has six — and the correspondence between them is a policy
statement, not a derivation. "C07 Targeting and selection irregularity"
is an `exclusion_error` when a household was left out and an
`inclusion_error` when one was wrongly included, and the category alone
does not say which.

So nothing here guesses. The mapping lives on
`ChoiceOption.canonical_code` in the `staac_grievance_category` list,
which is versioned and approved like every other code binding in the
registry, and `reference_data.resolve_canonical_code` reads it. Until
somebody sets a binding, the code resolves to nothing and the case is
refused with the code named.

Refusing is the point. The alternative — defaulting an unmapped
category to `other` — accepts the case and loses the classification
silently, which is the failure this registry keeps finding in its own
pipelines: a value nothing could interpret, written as though it had
been.

The payload sends a label
------------------------
STAAC's intake payload carries `category` as display text
("Targeting and selection irregularity"), not the code (`C07`). A label
is the one part of a vocabulary that is expected to change without the
code changing, so matching on it is fragile by construction. Both are
accepted here — the code directly, the label through the list's own
labels — and `label_lookup_used` says which, so a caller can report
that STAAC should be sending codes.

Gender is translated, not refused
---------------------------------
`complainant.gender` needs the same treatment for a stronger reason:
in STAAC it is `parties.PartyBase.sex`, an encrypted free-text field
with no vocabulary behind it at all, so what arrives is whatever an
intake officer typed. NSR records sex as a code from the `sex`
ChoiceList. Nothing may cross that gap by assumption, so
`staac_complainant_gender` holds the binding and `resolve_gender`
reads it.

But `resolve_gender` returns rather than raising, which is the one
place this module treats a value differently from the category, and
the asymmetry is deliberate. A category is what the case IS — a
grievance that cannot be classified cannot be routed, worked or
counted, so accepting it unclassified is worse than refusing it. Sex
is one thing ABOUT the complainant, used for disaggregation; throwing
away a real complaint because an officer typed "F" instead of "female"
is the worse trade in the other direction.

So the unresolved value comes back with the result, named and flagged,
for the caller to report. What makes that safe rather than silent is
the column: `open_grievance` refuses a `reporter_gender` the `sex`
list does not carry, so an untranslated value cannot be written as
though it had been understood. The failure mode is a blank column and
a result the caller was handed — not a `sex` column holding "F".
"""

from __future__ import annotations

from dataclasses import dataclass

#: The ChoiceList holding STAAC's category codes and their bindings.
STAAC_CATEGORY_LIST = "staac_grievance_category"

#: The ChoiceList binding STAAC's complainant gender to a `sex` code.
STAAC_GENDER_LIST = "staac_complainant_gender"

#: Where NSR records a person's sex. `Member.sex` holds a code from
#: this list and so does `Grievance.reporter_gender`.
NSR_SEX_LIST = "sex"

#: Where a STAAC grievance comes from, as stored on
#: `Grievance.source_system`.
STAAC_SOURCE_SYSTEM = "STAAC_GRM"


class UnmappedCategoryError(Exception):
    """STAAC sent a category this registry cannot classify.

    Carries the code so the message can name it, and `recognised` to
    separate "we have never heard of this code" from "we know it and
    nobody has decided what it means here" — different problems with
    different owners.
    """

    def __init__(self, value: str, *, recognised: bool):
        self.value = value
        self.recognised = recognised
        if recognised:
            message = (
                f"STAAC category {value!r} is registered but has no approved "
                f"binding to an NSR category; set canonical_code on the "
                f"{STAAC_CATEGORY_LIST} option before accepting these cases"
            )
        else:
            message = (
                f"STAAC category {value!r} is not in {STAAC_CATEGORY_LIST}; "
                f"the category list has changed and needs reseeding"
            )
        super().__init__(message)


@dataclass(frozen=True)
class ResolvedCategory:
    staac_code: str
    nsr_category: str
    label_lookup_used: bool


def _code_for_label(label: str, list_name: str = STAAC_CATEGORY_LIST) -> str:
    """The code whose label matches, or "".

    Exact after normalising case and inner whitespace, and ambiguous
    labels resolve to nothing — `reference_data.code_for_label`'s own
    rule, reused rather than restated.

    This used to also retry against labels with a trailing
    " (Severity)" stripped, because migration 0026 had decorated the
    seeded labels with STAAC's severity. Migration 0028 removed the
    decoration, so there is nothing left to undo: the labels are now
    character-for-character the names STAAC sends, and the match is
    the plain one.
    """
    from apps.reference_data.services import code_for_label

    return code_for_label(list_name, label)


def resolve_category(value: str) -> ResolvedCategory:
    """The NSR category a STAAC category means.

    Raises `UnmappedCategoryError` rather than returning a default, so an
    unclassifiable case is refused at the door instead of filed as
    `other` and discovered by whoever later wonders why targeting
    complaints stopped appearing.
    """
    from apps.reference_data.services import resolve_canonical_code

    from .models import Category

    raw = str(value or "").strip()
    if not raw:
        raise UnmappedCategoryError("", recognised=False)

    by_label = False
    code = raw
    found, canonical = resolve_canonical_code(STAAC_CATEGORY_LIST, code)
    if not found:
        code = _code_for_label(raw)
        by_label = bool(code)
        if code:
            found, canonical = resolve_canonical_code(STAAC_CATEGORY_LIST, code)

    if not found:
        raise UnmappedCategoryError(raw, recognised=False)
    if not canonical:
        raise UnmappedCategoryError(code, recognised=True)
    if canonical not in Category.values:
        # A binding pointing at a category this registry does not have
        # is a configuration error, not an intake one, and saying so
        # beats writing the value and failing on insert.
        raise UnmappedCategoryError(code, recognised=True)

    return ResolvedCategory(
        staac_code=code, nsr_category=canonical, label_lookup_used=by_label,
    )


@dataclass(frozen=True)
class ResolvedGender:
    """What a STAAC gender value means here, and what it was.

    `nsr_code` is a `sex` ChoiceList code, or "" when nothing resolved
    — including when nothing was sent, which is the ordinary case for
    an anonymous complaint.

    `received` carries the value verbatim whenever one was sent, so a
    caller reporting `unmapped` can name it. That is the whole point of
    returning instead of raising: the fact that a value arrived and
    could not be used travels with the result rather than being lost
    between the two systems.
    """

    nsr_code: str
    received: str
    recognised: bool
    label_lookup_used: bool

    @property
    def unmapped(self) -> bool:
        """A value was sent and this registry could not use it."""
        return bool(self.received) and not self.nsr_code


def resolve_gender(value: str) -> ResolvedGender:
    """The `sex` code a STAAC gender value means.

    Never raises. See the module docstring for why this and
    `resolve_category` differ: an unusable category makes the case
    unworkable, an unusable gender makes one count less precise.

    A binding that points at a code the `sex` list does not carry is
    treated as unresolved rather than returned, because returning it
    would put a value in the column that nothing can read back as a
    word — the failure this registry keeps finding in its own
    pipelines.
    """
    from apps.reference_data.services import (
        has_active_option,
        resolve_canonical_code,
    )

    raw = str(value or "").strip()
    if not raw:
        return ResolvedGender("", "", recognised=True, label_lookup_used=False)

    by_label = False
    code = raw
    found, canonical = resolve_canonical_code(STAAC_GENDER_LIST, code)
    if not found:
        code = _code_for_label(raw, STAAC_GENDER_LIST)
        by_label = bool(code)
        if code:
            found, canonical = resolve_canonical_code(STAAC_GENDER_LIST, code)

    if not found:
        return ResolvedGender(
            "", raw, recognised=False, label_lookup_used=by_label,
        )
    if not canonical:
        # Registered, nobody has bound it. Same state as an unmapped
        # category and the same owner; the difference is only what it
        # costs.
        return ResolvedGender(
            "", raw, recognised=True, label_lookup_used=by_label,
        )
    if not has_active_option(NSR_SEX_LIST, canonical):
        return ResolvedGender(
            "", raw, recognised=True, label_lookup_used=by_label,
        )
    return ResolvedGender(
        str(canonical), raw, recognised=True, label_lookup_used=by_label,
    )
