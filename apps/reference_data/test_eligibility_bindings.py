"""Regression coverage for ChoiceOption eligibility crosswalks."""

import pytest

from apps.reference_data.services import resolve_canonical_code


@pytest.mark.django_db
def test_programme_pmt_and_sex_options_resolve_from_reference_data():
    """Programme targeting never owns a copy of PMT or sex values."""
    assert resolve_canonical_code("programme_pmt_band", "middle_40") == (True, "vulnerable")
    assert resolve_canonical_code("programme_sex_filter", "any") == (True, "")


@pytest.mark.django_db
def test_unbound_option_remains_distinct_from_an_explicit_unrestricted_mapping():
    assert resolve_canonical_code("programme_pmt_band", "not-an-approved-option") == (False, None)
