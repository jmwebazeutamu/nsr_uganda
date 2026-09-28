"""Resolve a payload key to the canonical field it answers, at runtime.

`canonical_fields.py` is the seed table — question to the payload keys
that feed it — and after seeding `FormQuestion` is the source of truth.
This reads that truth back: given `water_source`, it answers
`drinking_water_source`.

Why it exists
-------------
`ingestion_hub.services` restated the correspondence instead of asking.
`_create_dwelling` read `payload["dwelling"]` and pulled
`sect.get("total_rooms")`. Real payloads carry the section as `housing`
and the key as `rooms_total`, so the section lookup returned `{}`, the
function returned early, and households were promoted with a complete
housing block and no Dwelling row — no error, no audit event, nothing
to notice. Seven other keys disagreed the same way: `water_source`,
`toilet_type`, `share_toilet`, `share_toilet_households`,
`lighting_source`, `rooms_sleeping`, `livelihood_source`.

Every one of those pairs is already recorded on `FormQuestion`. Nothing
needed inventing; the code just had to ask.

`apps.pmt.coded_operands` and `apps.pmt.variable_catalogue` each built
their own copy of this index before this module existed. Both now call
`question_index()` here.

What this does NOT do
---------------------
It does not guess. A key with no `canonical_field` and no declared alias
resolves to nothing and is reported, not matched by similarity —
`rooms_total`/`total_rooms` and `sleeping_rooms`/`rooms_sleeping` are
exactly the pairs a fuzzy match gets confidently wrong, and
`canonical_fields.py` says outright that prefix-stripping "resolves 57
of 185 questions and silently mismaps the rest".
"""

from __future__ import annotations


def question_index() -> dict[str, object]:
    """Every payload key the questionnaire knows -> its FormQuestion.

    Aliases first, then canonical names, so a question's own
    `canonical_field` can never be shadowed by another question's alias.
    """
    from .models import FormQuestion

    index: dict[str, object] = {}
    questions = list(
        FormQuestion.objects
        .exclude(canonical_field="")
        .select_related("choice_list_ref")
        .order_by("section__order", "order_in_section")
    )
    for question in questions:
        for alias in (question.payload_aliases or []):
            if alias:
                index.setdefault(str(alias), question)
    for question in questions:
        index[str(question.canonical_field)] = question
    return index


def canonical_key(payload_key: str, index: dict | None = None) -> str:
    """The registry's name for `payload_key`, or "" when unknown."""
    index = question_index() if index is None else index
    question = index.get(str(payload_key))
    return question.canonical_field if question is not None else ""


def _scalars(source: dict) -> dict:
    return {
        key: value for key, value in source.items()
        if not isinstance(value, (dict, list))
    }


def _names_for(question) -> list[str]:
    """Every spelling the question is known by, canonical first."""
    return [
        str(question.canonical_field),
        *[str(a) for a in (question.payload_aliases or []) if a],
    ]


def map_payload_to_fields(
    payload: dict,
    field_names: set[str],
    *,
    index: dict | None = None,
) -> dict[str, object]:
    """Collect the values in `payload` that belong to `field_names`.

    Every dict-valued section is walked rather than one named section.
    The section name is its own vocabulary — this registry has seen the
    same block arrive as `dwelling`, as nested `housing.dwelling` and as
    flat `housing` — and none of those names is recorded anywhere
    canonical, so keying off them is precisely how the data got dropped.
    What IS canonical is which field a key answers, and that alone is
    enough to route it.

    Two shapes need more than the bare key:

    * a nested block keys its leaves by the part that varies —
      `food_groups.staples.days` and `food_groups.fruits.days` are
      different questions and `days` alone cannot tell them apart — so
      `<parent>_<key>` is tried as well. `canonical_fields.py` records
      the aliases in exactly that joined form.
    * a question's canonical name is not always the column's. The
      questionnaire calls it `pulses_nuts_days`; the model column is
      `pulses_days`. Both are spellings of the one question, so once the
      question is found the spelling the model uses is the one taken.

    The first non-empty value wins, so a section carrying a key without
    an answer cannot mask a section that has one.
    """
    index = question_index() if index is None else index
    out: dict[str, object] = {}

    def _resolve(key: str) -> str:
        # A key that IS the column name is already canonical and needs
        # no question to say so. Not a fallback to guessing — an exact
        # identity — and it is what keeps promotion working where the
        # instrument has not been loaded. Without it an empty
        # FormQuestion table makes promotion fail CLOSED and drop every
        # detail row silently, a worse failure than the aliasing bug
        # this module exists to fix.
        if key in field_names:
            return key
        question = index.get(key)
        if question is None:
            return ""
        for name in _names_for(question):
            if name in field_names:
                return name
        return ""

    def _walk(source: dict, prefix: str = "") -> None:
        for key, value in source.items():
            if isinstance(value, dict):
                _walk(value, prefix=str(key))
                continue
            if isinstance(value, list) or value in (None, ""):
                continue
            for candidate in ([str(key)] if not prefix
                              else [str(key), f"{prefix}_{key}"]):
                name = _resolve(candidate)
                if name and name not in out:
                    out[name] = value
                    break

    if isinstance(payload, dict):
        _walk(payload)
    return out


def unmapped_keys(payload: dict, *, index: dict | None = None) -> list[str]:
    """Scalar payload keys the questionnaire has never heard of.

    A key nothing canonical describes is a missing schema dependency to
    report, not an invitation to match on similarity.
    """
    index = question_index() if index is None else index
    seen: set[str] = set()

    def _walk(source: dict) -> None:
        for key, value in source.items():
            if isinstance(value, dict):
                _walk(value)
            elif not isinstance(value, list) and not canonical_key(key, index):
                seen.add(str(key))

    if isinstance(payload, dict):
        _walk(payload)
    return sorted(seen)
