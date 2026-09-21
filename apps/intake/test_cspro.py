"""CSPro .dcf parser (ADR-0034).

UBOS owns the instrument and MGLSD cannot refuse a wave, so the parser's
contract is unusual: it must read a file we do not control, preserve
what it does not understand, and refuse only what genuinely cannot be
used. These cases are organised around that contract rather than around
the grammar.

No database — the parser is a pure function, and keeping it that way is
what lets the wave review be tested against hundreds of instrument
permutations in milliseconds.
"""

from __future__ import annotations

import pytest

from apps.intake.cspro import (
    CsproParseError,
    parse_dictionary,
    parse_value,
)

# A dictionary in the shape UBOS's tool produces: an id key, a household
# record, a repeating person record, and coded items with value sets.
NSR_DCF = """\
[Dictionary]
Version=CSPro 7.7
Label=NSR Household Questionnaire
Name=NSRHH
RecordTypeStart=1
RecordTypeLen=1

[Level]
Label=Household
Name=HH_LEVEL

[IdItems]

[Item]
Label=District code
Name=DISTRICT
Start=2
Len=3
DataType=Numeric

[Item]
Label=Household number
Name=HH_NUMBER
Start=5
Len=4
DataType=Numeric

[Record]
Label=Housing
Name=HOUSING_REC
RecordTypeValue='2'
Required=Yes
MaxRecords=1

[Item]
Label=Roof material
Name=ROOF_MATERIAL
Start=9
Len=2
DataType=Numeric

[ValueSet]
Label=Roof material
Name=ROOF_MATERIAL_VS
Value=11;Iron sheets
Value=12;Tiles
Value=14;Concrete
Value=16;Thatch/Dry leaves

[Item]
Label=Number of sleeping rooms
Name=SLEEPING_ROOMS
Start=11
Len=2
DataType=Numeric

[ValueSet]
Label=Plausible room count
Name=SLEEPING_ROOMS_VS
Value=0:30;Rooms

[Item]
Label=Address description
Name=ADDRESS_NARRATIVE
Start=13
Len=80
DataType=Alpha

[Record]
Label=Person
Name=PERSON_REC
RecordTypeValue='3'
Required=Yes
MaxRecords=20

[Item]
Label=Sex
Name=SEX
Start=93
Len=1
DataType=Numeric

[ValueSet]
Label=Sex
Name=SEX_VS
Value=1;Male
Value=2;Female

[Item]
Label=Chronic illness types
Name=CHRONIC_TYPES
Start=94
Len=2
DataType=Numeric
Occurrences=5
"""


@pytest.fixture(scope="module")
def dct():
    return parse_dictionary(NSR_DCF)


# ---------------------------------------------------------------------------
# Structure


class TestDictionaryStructure:
    def test_reads_the_dictionary_header(self, dct):
        assert dct.name == "NSRHH"
        assert dct.label == "NSR Household Questionnaire"
        assert dct.version == "CSPro 7.7"
        assert dct.record_type_start == 1
        assert dct.record_type_len == 1

    def test_reads_levels_and_records(self, dct):
        assert [level.name for level in dct.levels] == ["HH_LEVEL"]
        assert [r.name for r in dct.records()][1:] == ["HOUSING_REC", "PERSON_REC"]

    def test_id_items_become_their_own_record(self, dct):
        id_rec = dct.records()[0]
        assert id_rec.is_id_items
        assert [i.name for i in id_rec.items] == ["DISTRICT", "HH_NUMBER"]

    def test_record_attributes(self, dct):
        person = next(r for r in dct.records() if r.name == "PERSON_REC")
        assert person.record_type_value == "3"   # quotes stripped
        assert person.required is True
        assert person.max_records == 20

    def test_item_attributes(self, dct):
        roof = dct.item_map()["ROOF_MATERIAL"]
        assert roof.label == "Roof material"
        assert roof.start == 9
        assert roof.length == 2
        assert roof.data_type == "Numeric"
        assert roof.is_alpha is False

    def test_an_alpha_item_is_recognised(self, dct):
        addr = dct.item_map()["ADDRESS_NARRATIVE"]
        assert addr.is_alpha is True

    def test_a_repeating_item_is_recognised(self, dct):
        assert dct.item_map()["CHRONIC_TYPES"].is_repeating is True
        assert dct.item_map()["SEX"].is_repeating is False


# ---------------------------------------------------------------------------
# Nesting by order — getting this wrong reassigns answer codes to the
# wrong question, silently.


class TestNestingIsByOrder:
    def test_each_value_set_attaches_to_its_own_item(self, dct):
        items = dct.item_map()
        assert items["ROOF_MATERIAL"].primary_value_set.name == "ROOF_MATERIAL_VS"
        assert items["SEX"].primary_value_set.name == "SEX_VS"

    def test_an_item_with_no_value_set_has_none(self, dct):
        assert dct.item_map()["ADDRESS_NARRATIVE"].primary_value_set is None

    def test_items_attach_to_the_record_above_them(self, dct):
        housing = next(r for r in dct.records() if r.name == "HOUSING_REC")
        assert [i.name for i in housing.items] == [
            "ROOF_MATERIAL", "SLEEPING_ROOMS", "ADDRESS_NARRATIVE",
        ]

    def test_a_value_set_before_any_item_is_refused(self):
        with pytest.raises(CsproParseError, match="no preceding"):
            parse_dictionary("[Dictionary]\nName=X\n\n[ValueSet]\nName=ORPHAN_VS\n")

    def test_an_item_before_any_record_becomes_an_id_item(self):
        """Some generators omit the [IdItems] header. The item still has
        to land somewhere addressable rather than being dropped."""
        d = parse_dictionary(
            "[Dictionary]\nName=X\n\n[Level]\nName=L\n\n"
            "[Item]\nName=KEY\nStart=1\nLen=3\n",
        )
        assert d.item_map()["KEY"].start == 1
        assert d.records()[0].is_id_items


# ---------------------------------------------------------------------------
# Value sets — a code list and a numeric bound are not the same thing.


class TestValueSets:
    def test_discrete_codes_read_as_a_code_list(self, dct):
        vs = dct.item_map()["ROOF_MATERIAL"].primary_value_set
        assert vs.is_code_list is True
        assert [(v.code, v.label) for v in vs.values] == [
            ("11", "Iron sheets"), ("12", "Tiles"),
            ("14", "Concrete"), ("16", "Thatch/Dry leaves"),
        ]

    def test_a_range_is_not_a_code_list(self, dct):
        """`Value=0:30;Rooms` is a validation bound. Treating it as a
        choice list would manufacture 31 answer codes for a number
        nobody is choosing from a list."""
        item = dct.item_map()["SLEEPING_ROOMS"]
        vs = item.value_sets[0]
        assert vs.values[0].is_range is True
        assert vs.is_code_list is False
        assert item.primary_value_set is None

    def test_a_mixed_set_keeps_only_the_discrete_codes_as_choices(self):
        d = parse_dictionary(
            "[Dictionary]\nName=X\n\n[Record]\nName=R\n\n"
            "[Item]\nName=AGE\nStart=1\nLen=3\n\n"
            "[ValueSet]\nName=AGE_VS\n"
            "Value=0:120;Age in years\n"
            "Value=998;Don't know\n"
            "Value=999;Refused\n",
        )
        vs = d.item_map()["AGE"].primary_value_set
        assert vs.is_code_list is True
        assert [v.code for v in vs.discrete_values] == ["998", "999"]

    @pytest.mark.parametrize("raw,code,label,is_range", [
        ("11;Iron sheets", "11", "Iron sheets", False),
        ("1:5;Low", "1", "Low", True),
        ("'A';Alpha code", "A", "Alpha code", False),
        ("96;Other arrangements", "96", "Other arrangements", False),
        ("11;Label with; a semicolon", "11", "Label with; a semicolon", False),
        ("07;", "07", "", False),
    ])
    def test_value_line_shapes(self, raw, code, label, is_range):
        v = parse_value(raw)
        assert (v.code, v.label, v.is_range) == (code, label, is_range)

    def test_an_empty_value_line_is_dropped_not_stored_as_blank(self):
        assert parse_value("") is None
        assert parse_value("   ") is None

    def test_leading_zeros_are_preserved(self):
        """'07' and '7' are different answer codes. Reading codes as
        integers is how a code frame quietly loses its padding."""
        d = parse_dictionary(
            "[Dictionary]\nName=X\n\n[Record]\nName=R\n\n"
            "[Item]\nName=Q\nStart=1\nLen=2\n\n"
            "[ValueSet]\nName=Q_VS\nValue=07;Liquid fuel stove\n",
        )
        code = d.item_map()["Q"].primary_value_set.values[0].code
        assert code == "07"
        assert isinstance(code, str)


# ---------------------------------------------------------------------------
# The condition that produced ADR-0032.


class TestCompetingValueSets:
    DUAL_FRAME = """\
[Dictionary]
Name=X

[Record]
Name=R

[Item]
Label=Roof material
Name=ROOF_MATERIAL
Start=1
Len=2

[ValueSet]
Label=Roof material (UBOS 2024)
Name=ROOF_2024
Value=11;Iron sheets
Value=12;Tiles

[ValueSet]
Label=Roof material (legacy)
Name=ROOF_LEGACY
Value=1;Iron sheets
Value=2;Tiles
"""

    def test_two_code_frames_on_one_item_are_detected(self):
        """Six housing lists once carried two code frames at the same
        time, so "Iron sheets" was selectable as both 1 and 11 and no
        analysis could tell the two apart. It was found by eye, months
        later. The parser has to be able to say this out loud."""
        d = parse_dictionary(self.DUAL_FRAME)
        item = d.item_map()["ROOF_MATERIAL"]
        assert item.has_competing_value_sets is True
        assert len(item.value_sets) == 2

    def test_the_first_discrete_set_is_the_primary(self):
        d = parse_dictionary(self.DUAL_FRAME)
        assert d.item_map()["ROOF_MATERIAL"].primary_value_set.name == "ROOF_2024"

    def test_a_single_frame_is_not_flagged(self, dct):
        assert dct.item_map()["ROOF_MATERIAL"].has_competing_value_sets is False


# ---------------------------------------------------------------------------
# Tolerance — the instrument belongs to someone else.


class TestToleranceOfTheUnknown:
    def test_an_unknown_item_attribute_is_preserved(self):
        d = parse_dictionary(
            "[Dictionary]\nName=X\n\n[Record]\nName=R\n\n"
            "[Item]\nName=Q\nStart=1\nLen=2\nZeroFill=Yes\nSomeNewThing=42\n",
        )
        extra = d.item_map()["Q"].extra
        assert extra["zerofill"] == ["Yes"]
        # Kept verbatim so the diff can report it as a change rather
        # than the parser deciding it did not matter.
        assert extra["somenewthing"] == ["42"]

    def test_an_unknown_section_does_not_break_the_nesting_around_it(self):
        d = parse_dictionary(
            "[Dictionary]\nName=X\n\n[Record]\nName=R\n\n"
            "[Item]\nName=Q1\nStart=1\nLen=2\n\n"
            "[SomeFutureSection]\nFoo=bar\n\n"
            "[Item]\nName=Q2\nStart=3\nLen=2\n",
        )
        assert [i.name for i in d.records()[0].items] == ["Q1", "Q2"]
        assert d.item_map()["Q2"].start == 3

    def test_strict_mode_refuses_an_unknown_section(self):
        with pytest.raises(CsproParseError, match="unrecognised section"):
            parse_dictionary(
                "[Dictionary]\nName=X\n\n[SomeFutureSection]\nFoo=bar\n",
                strict=True,
            )

    def test_windows_line_endings_and_a_bom(self):
        d = parse_dictionary("﻿[Dictionary]\r\nName=X\r\nLabel=Y\r\n")
        assert (d.name, d.label) == ("X", "Y")

    def test_blank_lines_and_comments_are_ignored(self):
        d = parse_dictionary(
            "[Dictionary]\n# a comment\nName=X\n\n\n; another\nLabel=Y\n",
        )
        assert (d.name, d.label) == ("X", "Y")

    def test_keys_are_case_insensitive(self):
        d = parse_dictionary("[Dictionary]\nNAME=X\nlabel=Y\n")
        assert (d.name, d.label) == ("X", "Y")


# ---------------------------------------------------------------------------
# What it refuses, and only what it refuses.


class TestRefusals:
    def test_text_that_is_not_a_dictionary(self):
        with pytest.raises(CsproParseError, match="does not look like"):
            parse_dictionary("name,age\nAkello,47\n")

    def test_none(self):
        with pytest.raises(CsproParseError):
            parse_dictionary(None)

    def test_a_dictionary_with_no_name(self):
        with pytest.raises(CsproParseError, match="no Name"):
            parse_dictionary("[Dictionary]\nLabel=Nameless\n")

    def test_an_item_with_no_name(self):
        """A nameless item cannot be diffed, mapped or stored against."""
        with pytest.raises(CsproParseError, match="item with no Name"):
            parse_dictionary(
                "[Dictionary]\nName=X\n\n[Record]\nName=R\n\n"
                "[Item]\nLabel=I have no name\nStart=1\nLen=2\n",
            )

    def test_a_duplicate_item_name(self):
        """The diff is keyed on item name. Two items sharing one name
        makes every later comparison arbitrary."""
        with pytest.raises(CsproParseError, match="duplicate item name"):
            parse_dictionary(
                "[Dictionary]\nName=X\n\n"
                "[Record]\nName=R1\n\n[Item]\nName=Q\nStart=1\nLen=2\n\n"
                "[Record]\nName=R2\n\n[Item]\nName=Q\nStart=1\nLen=2\n",
            )

    def test_a_missing_label_is_not_a_refusal(self):
        """An unlabelled item is a fact about the instrument for the
        diff to report, not a reason to refuse to read the wave."""
        d = parse_dictionary(
            "[Dictionary]\nName=X\n\n[Record]\nName=R\n\n"
            "[Item]\nName=Q\nStart=1\nLen=2\n",
        )
        assert d.item_map()["Q"].label == ""

    def test_an_item_with_no_value_set_is_not_a_refusal(self, dct):
        assert dct.item_map()["ADDRESS_NARRATIVE"].value_sets == []
