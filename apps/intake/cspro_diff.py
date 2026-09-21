"""What changed between two CSPro instrument versions (ADR-0034).

The wave review question is not "what does this instrument contain?" —
it is "what is different about it, and which differences change the
meaning of data already in the registry?". A national household
dictionary runs to hundreds of items; a wave might touch four of them.
Handing a reviewer the whole instrument is the same as handing them
nothing.

So the output here is a CHANGESET, classified by what it costs:

    BREAKING  the meaning of a value changed, or can no longer be
              resolved. Data cannot be interpreted until someone
              decides the mapping.
    REVIEW    something new arrived, or wording moved. Interpretable,
              but a person should look before it lands.
    INFO      cosmetic or positional. Recorded, needs no decision.

The classification is the product. Everything else is bookkeeping.

The one that matters most
-------------------------
A code whose LABEL changed while its value stayed the same is the
worst change this file detects, and the one a human reading two
dictionaries side by side is least likely to spot. `3 = Wood` becoming
`3 = Timber` is harmless. `3 = Wood` becoming `3 = Concrete` silently
reclassifies every household already coded 3. Nothing errors, nothing
fails a check, and the registry is simply wrong from that wave onward.

This module cannot tell those two apart — only a person can — so it
refuses to guess and raises every relabel as BREAKING. A reviewer
dismissing "Wood → Timber" costs seconds. The alternative costs a PMT
band, which costs a household its transfer.

Pure: two parsed dictionaries in, a changeset out. No database, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from apps.intake.cspro import CsproDictionary, CsproItem, CsproValueSet


class Severity(StrEnum):
    BREAKING = "breaking"
    REVIEW = "review"
    INFO = "info"


#: Ordering for report output — worst first, because a reviewer reads
#: from the top and a 400-line changeset buries its own headline.
_SEVERITY_ORDER = {Severity.BREAKING: 0, Severity.REVIEW: 1, Severity.INFO: 2}


@dataclass(frozen=True)
class Change:
    """One difference, in terms a reviewer can act on."""

    kind: str                  # stable machine key, e.g. "code.relabelled"
    severity: Severity
    item: str                  # CSPro item name, or "" for record-level
    summary: str               # one line, reads on its own
    detail: str = ""           # what to do about it, when not obvious
    old: str = ""
    new: str = ""

    @property
    def needs_decision(self) -> bool:
        return self.severity is Severity.BREAKING


@dataclass
class InstrumentDiff:
    old_version: str
    new_version: str
    changes: list[Change] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.changes)

    @property
    def breaking(self) -> list[Change]:
        return [c for c in self.changes if c.severity is Severity.BREAKING]

    @property
    def review(self) -> list[Change]:
        return [c for c in self.changes if c.severity is Severity.REVIEW]

    @property
    def info(self) -> list[Change]:
        return [c for c in self.changes if c.severity is Severity.INFO]

    @property
    def is_clean(self) -> bool:
        """No change needs a human decision. NOT the same as no change."""
        return not self.breaking

    def sorted_changes(self) -> list[Change]:
        return sorted(
            self.changes,
            key=lambda c: (_SEVERITY_ORDER[c.severity], c.item, c.kind),
        )

    def counts(self) -> dict[str, int]:
        return {
            "breaking": len(self.breaking),
            "review": len(self.review),
            "info": len(self.info),
        }


# ---------------------------------------------------------------------------


def _codes(vs: CsproValueSet | None) -> dict[str, str]:
    """code -> label, discrete codes only. Ranges are validation bounds,
    not answers, and comparing them as if they were answer codes
    produces noise that buries the real changes."""
    if vs is None:
        return {}
    return {v.code: v.label for v in vs.discrete_values}


def _norm(label: str) -> str:
    """Labels for comparison: case and whitespace do not carry meaning,
    so a re-capitalisation should not consume a reviewer's attention."""
    return " ".join((label or "").split()).casefold()


def _type_signature(item: CsproItem) -> str:
    kind = "alpha" if item.is_alpha else "numeric"
    return f"{kind}({item.length}{f',{item.decimal}' if item.decimal else ''})"


def diff_dictionaries(
    old: CsproDictionary, new: CsproDictionary,
) -> InstrumentDiff:
    """Classify every difference between two parsed instruments."""
    diff = InstrumentDiff(
        old_version=old.version or old.name,
        new_version=new.version or new.name,
    )
    add = diff.changes.append

    old_items = old.item_map()
    new_items = new.item_map()
    old_record_of = {i.name: r.name for r in old.records() for i in r.items}
    new_record_of = {i.name: r.name for r in new.records() for i in r.items}

    # ---- records ----------------------------------------------------
    old_recs = {r.name for r in old.records()}
    new_recs = {r.name for r in new.records()}
    for name in sorted(new_recs - old_recs):
        add(Change(
            kind="record.added", severity=Severity.REVIEW, item="",
            summary=f"New record {name!r}.",
            detail="Its items are listed separately below.",
            new=name,
        ))
    for name in sorted(old_recs - new_recs):
        add(Change(
            kind="record.removed", severity=Severity.BREAKING, item="",
            summary=f"Record {name!r} is gone from the instrument.",
            detail=(
                "Households already carrying its items keep them. Confirm "
                "whether this wave simply stops collecting them, or whether "
                "the data moved elsewhere in the dictionary."
            ),
            old=name,
        ))

    # ---- items ------------------------------------------------------
    for name in sorted(set(new_items) - set(old_items)):
        item = new_items[name]
        coded = item.primary_value_set is not None
        add(Change(
            kind="item.added", severity=Severity.REVIEW, item=name,
            summary=(
                f"New question {name!r} ({item.label or 'no label'})"
                + (" with a coded answer list." if coded else ".")
            ),
            detail=(
                "Its answer codes need somewhere to land in the registry "
                "before this wave's values can be stored."
                if coded else
                "Nothing existing is affected; it needs a home in the "
                "registry schema."
            ),
            new=name,
        ))

    for name in sorted(set(old_items) - set(new_items)):
        add(Change(
            kind="item.removed", severity=Severity.BREAKING, item=name,
            summary=(
                f"Question {name!r} ({old_items[name].label or 'no label'}) "
                "is no longer collected."
            ),
            detail=(
                "Existing values stay in the registry and stay valid. "
                "Confirm this is a deliberate retirement and not a rename — "
                "a rename looks identical from here, and treating one as "
                "the other orphans the history."
            ),
            old=name,
        ))

    # ---- items present in both --------------------------------------
    for name in sorted(set(old_items) & set(new_items)):
        _diff_item(old_items[name], new_items[name], name, add)
        if old_record_of.get(name) != new_record_of.get(name):
            add(Change(
                kind="item.moved", severity=Severity.INFO, item=name,
                summary=(
                    f"{name!r} moved from record "
                    f"{old_record_of.get(name)!r} to {new_record_of.get(name)!r}."
                ),
                old=old_record_of.get(name, ""),
                new=new_record_of.get(name, ""),
            ))

    return diff


def _diff_item(old: CsproItem, new: CsproItem, name: str, add) -> None:
    # Wording. Cheap to dismiss, expensive to miss: a reworded question
    # is a different question asked under the same name, and the
    # registry cannot tell the two apart from the payload.
    if _norm(old.label) != _norm(new.label):
        add(Change(
            kind="item.relabelled", severity=Severity.REVIEW, item=name,
            summary=f"{name!r} was reworded.",
            detail=(
                "Confirm it still asks the same thing. If the question "
                "changed, values from before and after this wave are not "
                "comparable and should not share a column."
            ),
            old=old.label, new=new.label,
        ))

    # Storage shape.
    if _type_signature(old) != _type_signature(new):
        widened = (
            not old.is_alpha and not new.is_alpha
            and (new.length or 0) > (old.length or 0)
            and new.decimal == old.decimal
        )
        add(Change(
            kind="item.type_changed",
            severity=Severity.REVIEW if widened else Severity.BREAKING,
            item=name,
            summary=(
                f"{name!r} changed shape: {_type_signature(old)} → "
                f"{_type_signature(new)}."
            ),
            detail=(
                "A wider field of the same type holds everything the old one "
                "did; confirm the registry column is wide enough."
                if widened else
                "Existing stored values may not be representable in the new "
                "shape, or may change meaning. Needs a decision before load."
            ),
            old=_type_signature(old), new=_type_signature(new),
        ))

    if old.is_repeating != new.is_repeating:
        add(Change(
            kind="item.occurrence_changed", severity=Severity.BREAKING, item=name,
            summary=(
                f"{name!r} changed between single and repeating "
                f"({old.occurrences} → {new.occurrences})."
            ),
            detail=(
                "One answer per household and many answers per household are "
                "different shapes in the registry. Needs a decision."
            ),
            old=str(old.occurrences), new=str(new.occurrences),
        ))
    elif old.occurrences != new.occurrences:
        add(Change(
            kind="item.occurrence_count_changed", severity=Severity.REVIEW,
            item=name,
            summary=f"{name!r} repeat count {old.occurrences} → {new.occurrences}.",
            old=str(old.occurrences), new=str(new.occurrences),
        ))

    # Two code frames on one item is the ADR-0032 condition, arriving
    # from upstream this time instead of from a stale seed.
    if new.has_competing_value_sets and not old.has_competing_value_sets:
        add(Change(
            kind="item.competing_value_sets", severity=Severity.BREAKING, item=name,
            summary=f"{name!r} now carries more than one answer-code frame.",
            detail=(
                "Two frames on one question means two enumerators can code "
                "the same answer differently and nothing downstream can tell "
                "a real difference from a coding difference. Establish which "
                "frame this wave's data uses before loading it."
            ),
            new=", ".join(vs.name for vs in new.value_sets if vs.is_code_list),
        ))

    _diff_codes(old, new, name, add)


def _diff_codes(old: CsproItem, new: CsproItem, name: str, add) -> None:
    old_codes = _codes(old.primary_value_set)
    new_codes = _codes(new.primary_value_set)

    if not old_codes and not new_codes:
        return

    if old_codes and not new_codes:
        add(Change(
            kind="codes.removed_entirely", severity=Severity.BREAKING, item=name,
            summary=f"{name!r} no longer has a coded answer list.",
            detail=(
                "It was a closed question and is now open. Values arriving "
                "in this wave cannot be validated against the registry's "
                "choice list."
            ),
            old=f"{len(old_codes)} codes",
        ))
        return

    if new_codes and not old_codes:
        add(Change(
            kind="codes.added_entirely", severity=Severity.REVIEW, item=name,
            summary=f"{name!r} gained a coded answer list ({len(new_codes)} codes).",
            detail="It needs a choice list in the registry before load.",
            new=f"{len(new_codes)} codes",
        ))
        return

    for code in sorted(set(new_codes) - set(old_codes)):
        add(Change(
            kind="code.added", severity=Severity.REVIEW, item=name,
            summary=f"{name!r}: new answer code {code} = {new_codes[code]!r}.",
            detail=(
                "Values arriving with this code have nowhere to land until "
                "the registry's choice list gains it."
            ),
            new=f"{code}={new_codes[code]}",
        ))

    for code in sorted(set(old_codes) - set(new_codes)):
        add(Change(
            kind="code.removed", severity=Severity.BREAKING, item=name,
            summary=f"{name!r}: answer code {code} = {old_codes[code]!r} withdrawn.",
            detail=(
                "Households already coded this way keep the value and it must "
                "stay readable — deprecate the option, never delete it. Decide "
                "whether it maps onto a surviving code or has no equivalent; "
                "if it has none, say so rather than choosing the nearest."
            ),
            old=f"{code}={old_codes[code]}",
        ))

    # The silent one.
    for code in sorted(set(old_codes) & set(new_codes)):
        if _norm(old_codes[code]) == _norm(new_codes[code]):
            continue
        add(Change(
            kind="code.relabelled", severity=Severity.BREAKING, item=name,
            summary=(
                f"{name!r}: code {code} now means {new_codes[code]!r} "
                f"(was {old_codes[code]!r})."
            ),
            detail=(
                "Same code, different label. If this is a rewording, dismiss "
                "it. If the code was REUSED for a different answer, every "
                "household already coded {code} is now misclassified and the "
                "two waves must not share a column. Nothing downstream can "
                "detect this on its own.".replace("{code}", code)
            ),
            old=f"{code}={old_codes[code]}",
            new=f"{code}={new_codes[code]}",
        ))
