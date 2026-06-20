from types import SimpleNamespace

from apps.data_explorer.query_builder import _apply_filters, _apply_geographic_scope


class _FakeModel:
    age = None
    score = None
    sex = None
    sub_county_code = None


class _FakeQuerySet:
    model = _FakeModel

    def __init__(self):
        self.calls = []

    def filter(self, **kwargs):
        self.calls.append(("filter", kwargs))
        return self

    def exclude(self, **kwargs):
        self.calls.append(("exclude", kwargs))
        return self


def test_apply_filters_honours_operator_payloads():
    qs = _FakeQuerySet()
    variables = [
        SimpleNamespace(code="age", source_field="age"),
        SimpleNamespace(code="score", source_field="score"),
        SimpleNamespace(code="sex", source_field="sex"),
    ]

    _apply_filters(qs, variables, [
        {"variable": "age", "op": "gte", "value": 18},
        {"variable": "score", "op": "between", "value": "0.2, 0.8"},
        {"variable": "sex", "op": "neq", "value": None},
    ])

    assert qs.calls == [
        ("filter", {"age__gte": 18}),
        ("filter", {"score__gte": "0.2", "score__lte": "0.8"}),
        ("exclude", {"sex": None}),
    ]


def test_apply_filters_keeps_legacy_list_values_as_in_filters():
    qs = _FakeQuerySet()
    variables = [SimpleNamespace(code="sex", source_field="sex")]

    _apply_filters(qs, variables, {"sex": ["F", "M"]})

    assert qs.calls == [("filter", {"sex__in": ["F", "M"]})]


def test_apply_geographic_scope_accepts_legacy_subcounty_alias():
    qs = _FakeQuerySet()

    _apply_geographic_scope(qs, {"level": "subcounty", "codes": ["SC001"]})

    assert qs.calls == [("filter", {"sub_county_code__in": ["SC001"]})]
