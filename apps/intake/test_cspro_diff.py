"""Instrument diff between two CSPro waves (ADR-0034).

The contract under test is the CLASSIFICATION, not the enumeration. A
changeset that lists every difference is only as useful as its ability
to tell a reviewer which four of them need a decision — so most of these
cases assert severity, and the ones that matter most assert that
something is BREAKING rather than merely noticed.
"""

from __future__ import annotations

import pytest

from apps.intake.cspro import parse_dictionary
from apps.intake.cspro_diff import Severity, diff_dictionaries


def _dcf(items: str, *, name: str = "NSRHH", version: str = "1") -> str:
    return f"[Dictionary]\nName={name}\nVersion={version}\n\n[Record]\nName=R\n\n{items}"


def _item(name, label="", start=1, length=2, extra="", values=None, vs_name=None):
    block = f"[Item]\nLabel={label}\nName={name}\nStart={start}\nLen={length}\n{extra}\n"
    if values is not None:
        block += f"\n[ValueSet]\nName={vs_name or name + '_VS'}\n"
        block += "".join(f"Value={c};{lbl}\n" for c, lbl in values)
    return block + "\n"


def _diff(old_items, new_items):
    return diff_dictionaries(
        parse_dictionary(_dcf(old_items, version="1")),
        parse_dictionary(_dcf(new_items, version="2")),
    )


def _kinds(diff):
    return {c.kind for c in diff.changes}


def _by_kind(diff, kind):
    return next(c for c in diff.changes if c.kind == kind)


# ---------------------------------------------------------------------------


class TestNoChange:
    def test_an_identical_instrument_produces_nothing(self):
        items = _item("ROOF", "Roof material", values=[("11", "Iron sheets")])
        diff = _diff(items, items)
        assert diff.changes == []
        assert bool(diff) is False
        assert diff.is_clean is True

    def test_capitalisation_and_spacing_are_not_changes(self):
        """A reviewer's attention is the scarce resource. Spending it on
        a re-capitalised label means less of it for a reused code."""
        old = _item("ROOF", "Roof material", values=[("11", "Iron sheets")])
        new = _item("ROOF", "Roof  Material", values=[("11", "IRON SHEETS")])
        assert _diff(old, new).changes == []


# ---------------------------------------------------------------------------
# The one that matters most.


class TestCodeRelabelled:
    def test_a_reused_code_is_breaking(self):
        """`3 = Wood` becoming `3 = Concrete` reclassifies every
        household already coded 3, and nothing downstream can detect it.
        This is the case the whole module exists for."""
        old = _item("WALL", "Wall material", values=[("3", "Wood")])
        new = _item("WALL", "Wall material", values=[("3", "Concrete")])
        diff = _diff(old, new)
        change = _by_kind(diff, "code.relabelled")
        assert change.severity is Severity.BREAKING
        assert change.needs_decision is True
        assert "3" in change.summary
        assert "Wood" in change.old and "Concrete" in change.new

    def test_it_says_what_the_reviewer_must_decide(self):
        old = _item("WALL", "Wall", values=[("3", "Wood")])
        new = _item("WALL", "Wall", values=[("3", "Concrete")])
        detail = _by_kind(_diff(old, new), "code.relabelled").detail
        assert "REUSED" in detail
        assert "misclassified" in detail

    def test_a_harmless_rewording_is_still_raised(self):
        """The module cannot tell a rewording from a reuse — only a
        person can — so it raises both and says so. Dismissing one costs
        seconds; missing the other costs a PMT band."""
        old = _item("WALL", "Wall", values=[("3", "Wood")])
        new = _item("WALL", "Wall", values=[("3", "Timber")])
        assert _by_kind(_diff(old, new), "code.relabelled").severity is Severity.BREAKING


# ---------------------------------------------------------------------------


class TestCodeListChanges:
    def test_a_new_code_needs_review_not_a_decision(self):
        old = _item("ROOF", "Roof", values=[("11", "Iron sheets")])
        new = _item("ROOF", "Roof", values=[("11", "Iron sheets"), ("17", "Tarpaulin")])
        change = _by_kind(_diff(old, new), "code.added")
        assert change.severity is Severity.REVIEW
        assert "17" in change.summary

    def test_a_withdrawn_code_is_breaking(self):
        old = _item("ROOF", "Roof", values=[("11", "Iron sheets"), ("15", "Tins")])
        new = _item("ROOF", "Roof", values=[("11", "Iron sheets")])
        change = _by_kind(_diff(old, new), "code.removed")
        assert change.severity is Severity.BREAKING
        assert "15" in change.old

    def test_a_withdrawn_code_says_deprecate_not_delete(self):
        """Households already coded that way keep the value, and it has
        to stay readable (ADR-0010, ADR-0032)."""
        old = _item("ROOF", "Roof", values=[("11", "Iron"), ("15", "Tins")])
        new = _item("ROOF", "Roof", values=[("11", "Iron")])
        detail = _by_kind(_diff(old, new), "code.removed").detail
        assert "deprecate" in detail.lower()
        assert "never delete" in detail.lower()
        assert "nearest" in detail.lower()   # do not guess a mapping

    def test_a_question_that_stops_being_coded_is_breaking(self):
        old = _item("ROOF", "Roof", values=[("11", "Iron sheets")])
        new = _item("ROOF", "Roof")
        assert _by_kind(_diff(old, new), "codes.removed_entirely").severity is Severity.BREAKING

    def test_a_question_that_becomes_coded_needs_review(self):
        old = _item("ROOF", "Roof")
        new = _item("ROOF", "Roof", values=[("11", "Iron sheets")])
        assert _by_kind(_diff(old, new), "codes.added_entirely").severity is Severity.REVIEW

    def test_a_validation_range_is_not_read_as_answer_codes(self):
        """`Value=0:30;Rooms` is a bound. Widening it to 0:40 must not
        surface as forty added answer codes."""
        old = _item("ROOMS", "Rooms", values=[("0:30", "Rooms")])
        new = _item("ROOMS", "Rooms", values=[("0:40", "Rooms")])
        diff = _diff(old, new)
        assert not any(k.startswith("code.") for k in _kinds(diff))


# ---------------------------------------------------------------------------


class TestItemChanges:
    def test_a_new_question_needs_review(self):
        diff = _diff(_item("A", "First"), _item("A", "First") + _item("B", "Second", start=3))
        change = _by_kind(diff, "item.added")
        assert change.severity is Severity.REVIEW
        assert change.item == "B"

    def test_a_new_coded_question_says_its_codes_need_a_home(self):
        diff = _diff(
            _item("A", "First"),
            _item("A", "First") + _item("B", "Second", start=3, values=[("1", "Yes")]),
        )
        assert "coded answer list" in _by_kind(diff, "item.added").summary

    def test_a_dropped_question_is_breaking_and_warns_about_renames(self):
        """A rename is indistinguishable from a drop-plus-add when the
        only key is the item name. Treating one as the other orphans the
        history, so the reviewer is told to check."""
        diff = _diff(_item("A", "First") + _item("B", "Second", start=3), _item("A", "First"))
        change = _by_kind(diff, "item.removed")
        assert change.severity is Severity.BREAKING
        assert "rename" in change.detail.lower()

    def test_a_reworded_question_needs_review(self):
        old = _item("Q", "Does the household own land?")
        new = _item("Q", "Does any member of the household own land?")
        change = _by_kind(_diff(old, new), "item.relabelled")
        assert change.severity is Severity.REVIEW
        assert "not comparable" in change.detail

    def test_a_widened_numeric_field_is_only_review(self):
        """Wider holds everything narrower did. Not a decision."""
        change = _by_kind(_diff(_item("Q", "Q", length=2), _item("Q", "Q", length=3)),
                          "item.type_changed")
        assert change.severity is Severity.REVIEW

    def test_a_narrowed_field_is_breaking(self):
        change = _by_kind(_diff(_item("Q", "Q", length=4), _item("Q", "Q", length=2)),
                          "item.type_changed")
        assert change.severity is Severity.BREAKING

    def test_numeric_to_alpha_is_breaking(self):
        old = _item("Q", "Q")
        new = _item("Q", "Q", extra="DataType=Alpha")
        assert _by_kind(_diff(old, new), "item.type_changed").severity is Severity.BREAKING

    def test_single_to_repeating_is_breaking(self):
        old = _item("Q", "Q")
        new = _item("Q", "Q", extra="Occurrences=5")
        change = _by_kind(_diff(old, new), "item.occurrence_changed")
        assert change.severity is Severity.BREAKING

    def test_a_repeat_count_change_is_only_review(self):
        old = _item("Q", "Q", extra="Occurrences=5")
        new = _item("Q", "Q", extra="Occurrences=8")
        assert _by_kind(_diff(old, new), "item.occurrence_count_changed").severity is Severity.REVIEW

    def test_moving_an_item_between_records_is_informational(self):
        old = "[Item]\nName=Q\nStart=1\nLen=2\n\n"
        new = "[Item]\nName=X\nStart=1\nLen=2\n\n[Record]\nName=R2\n\n[Item]\nName=Q\nStart=1\nLen=2\n\n"
        diff = diff_dictionaries(parse_dictionary(_dcf(old)), parse_dictionary(_dcf(new)))
        assert _by_kind(diff, "item.moved").severity is Severity.INFO


class TestRecordChanges:
    def test_a_new_record_needs_review(self):
        old = _dcf(_item("Q"))
        new = _dcf(_item("Q")) + "\n[Record]\nName=R2\n\n" + _item("Z", start=5)
        diff = diff_dictionaries(parse_dictionary(old), parse_dictionary(new))
        assert _by_kind(diff, "record.added").severity is Severity.REVIEW

    def test_a_dropped_record_is_breaking(self):
        old = _dcf(_item("Q")) + "\n[Record]\nName=R2\n\n" + _item("Z", start=5)
        new = _dcf(_item("Q"))
        diff = diff_dictionaries(parse_dictionary(old), parse_dictionary(new))
        assert _by_kind(diff, "record.removed").severity is Severity.BREAKING


class TestCompetingFrames:
    def test_a_second_code_frame_arriving_is_breaking(self):
        """ADR-0032 from upstream: one question, two frames, and no way
        to tell a real difference from a coding difference."""
        old = _item("ROOF", "Roof", values=[("11", "Iron sheets")])
        new = (
            "[Item]\nLabel=Roof\nName=ROOF\nStart=1\nLen=2\n\n"
            "[ValueSet]\nName=ROOF_2024\nValue=11;Iron sheets\n\n"
            "[ValueSet]\nName=ROOF_LEGACY\nValue=1;Iron sheets\n\n"
        )
        change = _by_kind(_diff(old, new), "item.competing_value_sets")
        assert change.severity is Severity.BREAKING
        assert "ROOF_2024" in change.new and "ROOF_LEGACY" in change.new


# ---------------------------------------------------------------------------
# The changeset as a review artefact.


class TestChangesetShape:
    @pytest.fixture
    def mixed(self):
        old = (
            _item("ROOF", "Roof material", values=[("11", "Iron"), ("15", "Tins")])
            + _item("WALL", "Wall material", start=3, values=[("3", "Wood")])
        )
        new = (
            _item("ROOF", "Roof material", values=[("11", "Iron"), ("17", "Tarpaulin")])
            + _item("WALL", "Wall material", start=3, values=[("3", "Concrete")])
            + _item("FLOOR", "Floor material", start=5, values=[("14", "Cement")])
        )
        return _diff(old, new)

    def test_it_separates_what_needs_a_decision(self, mixed):
        assert {c.kind for c in mixed.breaking} == {"code.removed", "code.relabelled"}
        assert {c.kind for c in mixed.review} == {"code.added", "item.added"}

    def test_a_wave_with_any_breaking_change_is_not_clean(self, mixed):
        assert mixed.is_clean is False
        assert mixed.counts() == {"breaking": 2, "review": 2, "info": 0}

    def test_worst_first(self, mixed):
        """A 400-line changeset buries its own headline unless the
        ordering does the work."""
        severities = [c.severity for c in mixed.sorted_changes()]
        assert severities == sorted(severities, key=lambda s: {
            Severity.BREAKING: 0, Severity.REVIEW: 1, Severity.INFO: 2}[s])
        assert severities[0] is Severity.BREAKING

    def test_a_wave_that_only_adds_is_clean(self):
        """Clean means "nothing needs deciding", not "nothing changed"."""
        old = _item("ROOF", "Roof", values=[("11", "Iron")])
        new = _item("ROOF", "Roof", values=[("11", "Iron"), ("17", "Tarpaulin")])
        diff = _diff(old, new)
        assert bool(diff) is True
        assert diff.is_clean is True

    def test_every_change_names_its_item_and_reads_on_its_own(self, mixed):
        for change in mixed.changes:
            assert change.summary.strip()
            assert change.summary.endswith(".")
            if not change.kind.startswith("record."):
                assert change.item, change.kind

    def test_versions_are_carried_for_the_audit_trail(self, mixed):
        assert (mixed.old_version, mixed.new_version) == ("1", "2")
