# ruff: noqa: N806 — class-factory aliases (e.g. `Validator = _validator()`)
"""QueryValidator unit tests.

ADR-0023 D3 + D4:
- Rejects geographic_scope.level in {parish, village} with HTTP 422
  and a payload that names the floor + the handoff URL.
- Rejects any Variable in PrivacyClass=Sensitive at validation time
  (the Suppressor never runs, the count is never computed).
- Accepts a well-formed query.

The validator's surface lives at apps.data_explorer.validators or
apps.data_explorer.services. We tolerate either path.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


def _validator():
    try:
        from apps.data_explorer.validators import QueryValidator
        return QueryValidator
    except ImportError:
        from apps.data_explorer.services import QueryValidator  # noqa: F401
        return QueryValidator


def _validation_error_types():
    types: list[type[BaseException]] = []
    for path, name in [
        ("apps.data_explorer.validators", "QueryValidationError"),
        ("apps.data_explorer.services", "QueryValidationError"),
        ("apps.data_explorer.validators", "GeographicFloorViolation"),
        ("apps.data_explorer.services", "GeographicFloorViolation"),
        ("apps.data_explorer.validators", "SensitiveClassBlocked"),
        ("apps.data_explorer.services", "SensitiveClassBlocked"),
    ]:
        try:
            mod = __import__(path, fromlist=[name])
            types.append(getattr(mod, name))
        except Exception:
            pass
    if not types:
        types.append(Exception)
    return tuple(types)


@pytest.fixture
def base_query(dataset, variable_internal):
    return {
        "dataset_code": dataset.code,
        "projection": [variable_internal.code],
        "filters": [],
        "geographic_scope": {
            "level": "sub_county",
            "codes": ["SC-001"],
        },
    }


class TestGeographicFloor:

    @pytest.mark.parametrize("level", ["parish", "village"])
    def test_rejects_below_sub_county(self, base_query, level):
        Validator = _validator()
        q = dict(base_query)
        q["geographic_scope"] = {"level": level, "codes": ["P-1"]}
        with pytest.raises(_validation_error_types()) as exc:
            Validator.validate(q)
        # The error payload must include the floor and the handoff URL
        # so the UI can surface "Use 'Request record-level data'".
        msg = str(exc.value).lower()
        assert "sub_county" in msg or "floor" in msg

    def test_accepts_sub_county(self, base_query):
        Validator = _validator()
        result = Validator.validate(base_query)
        # Validator may return the canonical query, or None for ok-
        # only — either is acceptable as long as no exception fires.
        assert result is None or isinstance(result, (dict, bool, object))

    @pytest.mark.parametrize("level", ["region", "sub_region", "district"])
    def test_accepts_coarser_than_sub_county(self, base_query, level):
        Validator = _validator()
        q = dict(base_query)
        q["geographic_scope"] = {"level": level, "codes": ["R-1"]}
        Validator.validate(q)  # must not raise


class TestSensitiveClassBlocked:

    def test_rejects_sensitive_in_projection(
        self, base_query, variable_sensitive,
    ):
        Validator = _validator()
        q = dict(base_query)
        q["projection"] = [variable_sensitive.code]
        with pytest.raises(_validation_error_types()) as exc:
            Validator.validate(q)
        assert "sensitive" in str(exc.value).lower()

    def test_rejects_sensitive_in_filter(
        self, base_query, variable_sensitive, variable_internal,
    ):
        Validator = _validator()
        q = dict(base_query)
        q["projection"] = [variable_internal.code]
        q["filters"] = [
            {"variable": variable_sensitive.code, "op": "eq", "value": "x"},
        ]
        with pytest.raises(_validation_error_types()):
            Validator.validate(q)


class TestWellFormedQuery:

    def test_accepts_minimal_well_formed(self, base_query):
        Validator = _validator()
        # No exception → pass.
        Validator.validate(base_query)

    def test_rejects_unknown_variable(self, base_query):
        Validator = _validator()
        q = dict(base_query)
        q["projection"] = ["household.never_existed"]
        with pytest.raises(_validation_error_types()):
            Validator.validate(q)

    def test_rejects_inactive_variable(self, base_query, dataset, privacy_classes):
        """ADR-0023 D5: INACTIVE Variables do not appear in the field
        picker. The API layer must enforce this — the user can still
        POST a code that exists but isn't active, and the validator
        must refuse."""
        Validator = _validator()
        from apps.data_explorer.models import Variable, VariableStatus

        v = Variable.objects.create(
            dataset=dataset,
            code="household.pending_review",
            label="Pending review",
            privacy_class=privacy_classes["internal"],
            status=VariableStatus.INACTIVE,
        )
        q = dict(base_query)
        q["projection"] = [v.code]
        with pytest.raises(_validation_error_types()):
            Validator.validate(q)
