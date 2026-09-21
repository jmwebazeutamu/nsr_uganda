"""CSPro data dictionary (.dcf) parser.

UBOS collects the national household data on a CSPro instrument and
delivers it to MGLSD in periodic waves. The instrument is UBOS's to
change, and it will change between waves — questions added, answer-code
lists revised. MGLSD cannot refuse a wave, so the only defence against a
change arriving unnoticed is to read the instrument itself and compare
it with the last one (ADR-0034).

The `.dcf` data dictionary is that instrument. It is the machine-readable
definition of every item and every value set, and for CSPro's native
fixed-width export it is not optional — the file cannot be parsed at all
without it, because the dictionary is what defines the column positions.

This module is the READ side and nothing else: text in, dataclasses out.
No Django, no database, no I/O. `apps.intake.services.import_cspro_*`
turns the result into a draft FormVersion; the diff between two parsed
dictionaries is what the wave review reads.

Format
------
A .dcf is a flat INI-ish file: `[Section]` headers and `Key=Value` lines,
where nesting is implied by ORDER rather than by punctuation.

    [Dictionary]
    Version=CSPro 7.7
    Label=NSR Household Questionnaire
    Name=NSRHH

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

    [Record]
    Label=Housing
    Name=HOUSING_REC
    RecordTypeValue='2'

    [Item]
    Label=Roof material
    Name=ROOF_MATERIAL
    Start=20
    Len=2

    [ValueSet]
    Label=Roof material
    Name=ROOF_MATERIAL_VS
    Value=11;Iron sheets
    Value=12;Tiles

An `[Item]` attaches to the most recent `[Record]` (or to `[IdItems]`);
a `[ValueSet]` attaches to the most recent `[Item]`. Getting that
association wrong silently reassigns answer codes to the wrong question,
so the parser tracks it explicitly rather than inferring it later.

Deliberately tolerant
---------------------
A dictionary that this parser rejects is a wave that cannot be reviewed,
and the wave arrives whether or not the review happens. So unknown
sections and unknown keys are PRESERVED rather than rejected — an
attribute this parser has never seen is kept on `extra` and surfaces in
the diff as a change, which is the correct behaviour for a format owned
by someone else. `strict=True` is available for testing a dictionary we
control.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


class CsproParseError(ValueError):
    """The text is not a usable CSPro dictionary."""


# ---------------------------------------------------------------------------
# Value sets


@dataclass(frozen=True)
class CsproValue:
    """One `Value=` line.

    CSPro allows a single code (`Value=11;Iron sheets`) or a RANGE
    (`Value=1:5;Low`), where every code in the range carries the label.
    A range is kept as a range rather than expanded: expanding
    `Value=0:150;Age in years` would manufacture 151 answer codes for
    what is a numeric bound, and the difference between "a coded answer"
    and "a validation range" is exactly what the importer needs in order
    to decide whether this item is a select_one or an integer.
    """

    code: str
    label: str
    to_code: str = ""          # non-empty only for ranges

    @property
    def is_range(self) -> bool:
        return bool(self.to_code)


@dataclass
class CsproValueSet:
    name: str
    label: str = ""
    values: list[CsproValue] = field(default_factory=list)
    extra: dict[str, list[str]] = field(default_factory=dict)

    @property
    def is_code_list(self) -> bool:
        """True when this reads as a list of discrete answer codes.

        A value set that is entirely ranges is a validation bound, not a
        choice list, and must not become a ChoiceList — the registry
        would gain a coded vocabulary nobody is answering from.
        """
        return bool(self.values) and any(not v.is_range for v in self.values)

    @property
    def discrete_values(self) -> list[CsproValue]:
        return [v for v in self.values if not v.is_range]


# ---------------------------------------------------------------------------
# Items, records, levels


@dataclass
class CsproItem:
    name: str
    label: str = ""
    start: int | None = None
    length: int | None = None
    data_type: str = "Numeric"     # Numeric | Alpha
    decimal: int = 0
    occurrences: int = 1
    item_type: str = "Item"        # Item | SubItem
    value_sets: list[CsproValueSet] = field(default_factory=list)
    extra: dict[str, list[str]] = field(default_factory=dict)

    @property
    def is_alpha(self) -> bool:
        return self.data_type.strip().lower().startswith("alpha")

    @property
    def is_repeating(self) -> bool:
        return (self.occurrences or 1) > 1

    @property
    def primary_value_set(self) -> CsproValueSet | None:
        """The value set that defines this item's answer codes, if any.

        CSPro permits several value sets on one item (alternative code
        frames for the same question). The first discrete one is the
        item's own vocabulary; the rest are recorded and reported,
        because an item that has grown a second code frame is precisely
        the condition that produced two competing housing frames in the
        registry (ADR-0032).
        """
        for vs in self.value_sets:
            if vs.is_code_list:
                return vs
        return None

    @property
    def has_competing_value_sets(self) -> bool:
        return sum(1 for vs in self.value_sets if vs.is_code_list) > 1


@dataclass
class CsproRecord:
    name: str
    label: str = ""
    record_type_value: str = ""
    required: bool = False
    max_records: int = 1
    items: list[CsproItem] = field(default_factory=list)
    extra: dict[str, list[str]] = field(default_factory=dict)

    @property
    def is_id_items(self) -> bool:
        """The `[IdItems]` pseudo-record: the key every record carries."""
        return self.name == ID_ITEMS_NAME


@dataclass
class CsproLevel:
    name: str
    label: str = ""
    records: list[CsproRecord] = field(default_factory=list)
    extra: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class CsproDictionary:
    name: str
    label: str = ""
    version: str = ""
    record_type_start: int | None = None
    record_type_len: int | None = None
    levels: list[CsproLevel] = field(default_factory=list)
    extra: dict[str, list[str]] = field(default_factory=dict)

    # ---- convenience views, used by the importer and the diff ----

    def records(self) -> list[CsproRecord]:
        return [rec for level in self.levels for rec in level.records]

    def items(self) -> list[CsproItem]:
        return [item for rec in self.records() for item in rec.items]

    def item_map(self) -> dict[str, CsproItem]:
        """Items keyed by name. CSPro item names are unique within a
        dictionary, which is what makes a name-keyed diff meaningful."""
        return {item.name: item for item in self.items()}

    def value_sets(self) -> list[CsproValueSet]:
        return [vs for item in self.items() for vs in item.value_sets]


ID_ITEMS_NAME = "__ID_ITEMS__"

#: Section headers this parser understands. Anything else is kept.
_KNOWN_SECTIONS = {
    "dictionary", "level", "iditems", "record", "item", "valueset",
    "relation", "languages", "relationpart",
}

_SECTION_RE = re.compile(r"^\[(?P<name>[^\]]+)\]\s*$")
_KEYVAL_RE = re.compile(r"^(?P<key>[A-Za-z0-9_]+)\s*=\s*(?P<value>.*)$")
#: `Value=11;Iron sheets`, `Value=1:5;Low`, `Value='A';Alpha code`
_VALUE_RE = re.compile(
    r"^(?P<lo>[^;:]*?)(?::(?P<hi>[^;]*?))?(?:;(?P<label>.*))?$",
)


def _unquote(raw: str) -> str:
    s = raw.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        return s[1:-1]
    return s


def _as_int(raw: str, default: int | None = None) -> int | None:
    try:
        return int(_unquote(raw))
    except (TypeError, ValueError):
        return default


def _as_bool(raw: str) -> bool:
    return _unquote(raw).strip().lower() in ("yes", "true", "1")


def parse_value(raw: str) -> CsproValue | None:
    """One `Value=` payload into a CsproValue, or None if unusable."""
    m = _VALUE_RE.match(raw.strip())
    if not m:
        return None
    lo = _unquote(m.group("lo") or "")
    hi = _unquote(m.group("hi") or "")
    label = (m.group("label") or "").strip()
    if lo == "" and hi == "":
        return None
    return CsproValue(code=lo, label=label, to_code=hi)


def parse_dictionary(text: str, *, strict: bool = False) -> CsproDictionary:
    """Parse `.dcf` text into a CsproDictionary.

    `strict` raises on an unrecognised section header instead of keeping
    it. Off by default: see the module docstring on why a dictionary we
    do not own must still parse.
    """
    if text is None:
        raise CsproParseError("no dictionary text supplied")
    # CSPro writes Windows line endings and frequently a UTF-8 BOM.
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    if "[Dictionary]" not in text:
        raise CsproParseError(
            "no [Dictionary] section — this does not look like a CSPro "
            "data dictionary (.dcf)",
        )

    dictionary: CsproDictionary | None = None
    level: CsproLevel | None = None
    record: CsproRecord | None = None
    item: CsproItem | None = None
    value_set: CsproValueSet | None = None

    # Where a bare `Key=Value` currently lands. Order is what defines
    # nesting in this format, so this is the whole parser's state.
    scope: str = ""
    pending: dict[str, list[str]] = {}

    def _flush() -> None:
        """Apply the accumulated keys to whatever is open."""
        nonlocal pending
        target = {
            "dictionary": dictionary, "level": level, "record": record,
            "item": item, "valueset": value_set,
        }.get(scope)
        if target is not None:
            _apply(scope, target, pending)
        pending = {}

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue

        header = _SECTION_RE.match(line)
        if header:
            _flush()
            name = header.group("name").strip().lower().replace(" ", "")
            if strict and name not in _KNOWN_SECTIONS:
                raise CsproParseError(f"unrecognised section [{header.group('name')}]")

            if name == "dictionary":
                dictionary = CsproDictionary(name="")
                level = record = item = value_set = None
            elif name == "level":
                if dictionary is None:
                    raise CsproParseError("[Level] before [Dictionary]")
                level = CsproLevel(name="")
                dictionary.levels.append(level)
                record = item = value_set = None
            elif name == "iditems":
                level = _ensure_level(dictionary, level)
                record = CsproRecord(name=ID_ITEMS_NAME, label="Id items")
                level.records.append(record)
                item = value_set = None
            elif name == "record":
                level = _ensure_level(dictionary, level)
                record = CsproRecord(name="")
                level.records.append(record)
                item = value_set = None
            elif name == "item":
                if record is None:
                    # An [Item] before any [Record] belongs to the id
                    # items — some generators omit the [IdItems] header.
                    level = _ensure_level(dictionary, level)
                    record = CsproRecord(name=ID_ITEMS_NAME, label="Id items")
                    level.records.append(record)
                item = CsproItem(name="")
                record.items.append(item)
                value_set = None
            elif name == "valueset":
                if item is None:
                    raise CsproParseError("[ValueSet] with no preceding [Item]")
                value_set = CsproValueSet(name="")
                item.value_sets.append(value_set)
            # Any other section: keys are collected under a scope that
            # resolves to no target, so they are skipped without
            # disturbing the item/record nesting around them.
            scope = name if name in (
                "dictionary", "level", "record", "item", "valueset",
            ) else ""
            continue

        kv = _KEYVAL_RE.match(line)
        if not kv:
            continue  # continuation or free text; nothing addressable
        pending.setdefault(kv.group("key").strip().lower(), []).append(
            kv.group("value"),
        )

    _flush()

    if dictionary is None:  # pragma: no cover — guarded by the check above
        raise CsproParseError("no [Dictionary] section")
    _validate(dictionary)
    return dictionary


def _ensure_level(dictionary: CsproDictionary | None, level: CsproLevel | None):
    """CSPro allows a single-level dictionary to omit [Level]."""
    if dictionary is None:
        raise CsproParseError("section before [Dictionary]")
    if level is not None:
        return level
    implied = CsproLevel(name="LEVEL_1", label="Level 1")
    dictionary.levels.append(implied)
    return implied


def _apply(scope: str, target, keys: dict[str, list[str]]) -> None:
    """Move accumulated `Key=Value` pairs onto the open object.

    Anything not consumed here lands on `target.extra` verbatim, so a
    dictionary using an attribute this parser has never seen still
    round-trips into the diff rather than being silently dropped.
    """
    consumed: set[str] = set()

    def take(key: str) -> str | None:
        vals = keys.get(key)
        if not vals:
            return None
        consumed.add(key)
        return vals[0]

    if scope == "dictionary":
        target.name = _unquote(take("name") or "")
        target.label = _unquote(take("label") or "")
        target.version = _unquote(take("version") or "")
        target.record_type_start = _as_int(take("recordtypestart") or "")
        target.record_type_len = _as_int(take("recordtypelen") or "")
    elif scope == "level":
        target.name = _unquote(take("name") or "")
        target.label = _unquote(take("label") or "")
    elif scope == "record":
        name = _unquote(take("name") or "")
        if name:
            target.name = name
        target.label = _unquote(take("label") or "")
        target.record_type_value = _unquote(take("recordtypevalue") or "")
        target.required = _as_bool(take("required") or "")
        target.max_records = _as_int(take("maxrecords") or "", 1) or 1
    elif scope == "item":
        target.name = _unquote(take("name") or "")
        target.label = _unquote(take("label") or "")
        target.start = _as_int(take("start") or "")
        target.length = _as_int(take("len") or "")
        target.data_type = _unquote(take("datatype") or "") or "Numeric"
        target.decimal = _as_int(take("decimal") or "", 0) or 0
        target.occurrences = _as_int(take("occurrences") or "", 1) or 1
        target.item_type = _unquote(take("itemtype") or "") or "Item"
    elif scope == "valueset":
        target.name = _unquote(take("name") or "")
        target.label = _unquote(take("label") or "")
        for raw in keys.get("value", []):
            parsed = parse_value(raw)
            if parsed is not None:
                target.values.append(parsed)
        consumed.add("value")

    leftover = {k: v for k, v in keys.items() if k not in consumed}
    if leftover:
        target.extra.update(leftover)


def _validate(dictionary: CsproDictionary) -> None:
    """Refuse a dictionary that cannot be used, and only that.

    A nameless item cannot be diffed, mapped or stored, so it is fatal.
    A duplicate item name breaks the name-keyed diff, so it is fatal
    too. Everything else — a missing label, an item with no value set,
    an unfamiliar attribute — is a fact about the instrument, reported
    by the diff, not a reason to refuse to read it.
    """
    if not dictionary.name:
        raise CsproParseError("[Dictionary] has no Name")

    seen: dict[str, str] = {}
    for rec in dictionary.records():
        for item in rec.items:
            if not item.name:
                raise CsproParseError(
                    f"item with no Name in record {rec.name!r} "
                    f"(label={item.label!r})",
                )
            if item.name in seen:
                raise CsproParseError(
                    f"duplicate item name {item.name!r} in records "
                    f"{seen[item.name]!r} and {rec.name!r} — item names must "
                    "be unique for the instrument diff to be meaningful",
                )
            seen[item.name] = rec.name
