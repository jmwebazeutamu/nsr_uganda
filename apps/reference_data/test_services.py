"""Unit tests for the code-to-label resolver service (US-S22-005b).

The resolver runs against the seeded ChoiceList catalogue, so these
tests rely on the data migration that populates the 46 legacy lists.
A test marked `seeded` is an integration-shaped unit test in that
sense — fast (SQLite), but anchored to the canonical seed.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from apps.reference_data.models import (
    ChoiceList,
    ChoiceListStatus,
    ChoiceOption,
)
from apps.reference_data.services import (
    clear_resolver_cache,
    resolve_label,
    resolve_labels,
    resolve_options,
)


@pytest.fixture(autouse=True)
def _flush_resolver_cache():
    """Each test starts and ends with a clean lru_cache — otherwise
    the seed loaded by django_db can leak between modules."""
    clear_resolver_cache()
    yield
    clear_resolver_cache()


@pytest.mark.django_db
class TestKnownCodes:
    def test_sex_codes_resolve(self):
        assert resolve_label("sex", "1") == "Male"
        assert resolve_label("sex", "2") == "Female"

    def test_tenure_code_from_bug_report(self):
        # User's bug report: "Tenure 13" should render the actual label.
        assert resolve_label("tenure", "13") == "Free - private"

    def test_roof_material_code_from_bug_report(self):
        assert resolve_label("roof_material", "14") == "Concrete"

    def test_relationship_zero_padded_code(self):
        # XLSForm convention: codes are strings, often zero-padded.
        # The resolver coerces non-strings via str(), but DOES NOT
        # synthesize padding — "1" and "01" are distinct codes.
        assert resolve_label("relationship", "01") == "Head"
        assert resolve_label("relationship", 1) == "1"  # unmapped — no zero pad

    def test_empty_or_none_returns_empty_string(self):
        assert resolve_label("sex", None) == ""
        assert resolve_label("sex", "") == ""


@pytest.mark.django_db
class TestUnknownCodes:
    def test_unknown_code_returns_raw(self, caplog):
        with caplog.at_level("WARNING"):
            out = resolve_label("sex", "99")
        assert out == "99"
        assert any(
            r.message == "ref_data.unmapped_code" for r in caplog.records
        )

    def test_unknown_list_returns_raw(self, caplog):
        with caplog.at_level("WARNING"):
            out = resolve_label("never_seen_list", "1")
        assert out == "1"
        assert any(
            r.message == "ref_data.unmapped_list" for r in caplog.records
        )

    def test_context_metadata_surfaces_in_log(self, caplog):
        with caplog.at_level("WARNING"):
            resolve_label("sex", "99", context={"household_id": "HH-1"})
        rec = next(r for r in caplog.records if r.message == "ref_data.unmapped_code")
        assert rec.household_id == "HH-1"
        assert rec.list_name == "sex"
        assert rec.code == "99"


@pytest.mark.django_db
class TestAsOfVersioning:
    def test_old_version_returns_old_label(self):
        """A historical record (as_of in the past) gets the label
        from the ChoiceList version active at that date, even after
        a newer version is approved with a different label."""
        today = date.today()
        last_year = today - timedelta(days=400)
        ten_days_ago = today - timedelta(days=10)

        # Take an existing seeded list and retroactively narrow its
        # window so it was active "yesterday" but not today.
        seeded = ChoiceList.objects.get(list_name="sex", version=1)
        seeded.effective_from = last_year
        seeded.effective_to = ten_days_ago
        seeded.save()

        # Ship a v2 ACTIVE from ten_days_ago onwards, with a
        # different label for code "1".
        v2 = ChoiceList.objects.create(
            list_name="sex",
            version=2,
            status=ChoiceListStatus.ACTIVE,
            effective_from=ten_days_ago,
            effective_to=None,
            author="test",
            approved_by="reviewer",
        )
        ChoiceOption.objects.create(
            choice_list=v2, code="1", label="Man", language="en",
        )
        ChoiceOption.objects.create(
            choice_list=v2, code="2", label="Woman", language="en",
        )

        # Today's resolver picks v2.
        assert resolve_label("sex", "1") == "Man"
        # A historical date inside v1's window picks v1.
        a_year_ago = today - timedelta(days=180)
        assert resolve_label("sex", "1", as_of=a_year_ago) == "Male"

    def test_inactive_list_is_not_resolved(self, caplog):
        cl = ChoiceList.objects.get(list_name="sex", version=1)
        cl.status = ChoiceListStatus.RETIRED
        cl.save()
        with caplog.at_level("WARNING"):
            out = resolve_label("sex", "1")
        assert out == "1"
        assert any(
            r.message == "ref_data.unmapped_list" for r in caplog.records
        )


@pytest.mark.django_db
class TestMultiSelect:
    def test_resolve_labels_from_list(self):
        # asset_type uses string codes per the questionnaire.
        out = resolve_labels("asset_type", ["radio", "phone"])
        assert out == ["Radio", "Mobile phone"]

    def test_resolve_labels_from_xlsform_string(self):
        # XLSForm select_multiple stores codes as a space-separated
        # string. The resolver accepts either.
        out = resolve_labels("asset_type", "radio phone tv")
        assert out == ["Radio", "Mobile phone", "Television"]

    def test_resolve_labels_empty(self):
        assert resolve_labels("asset_type", "") == []
        assert resolve_labels("asset_type", None) == []


@pytest.mark.django_db
class TestLanguageFallback:
    def test_missing_language_falls_back_to_en(self, caplog):
        # No lg rows exist for sex in the seed — should silently fall
        # back to en without warning.
        with caplog.at_level("WARNING"):
            out = resolve_label("sex", "1", language="lg")
        assert out == "Male"

    def test_language_overrides_en_when_present(self):
        cl = ChoiceList.objects.get(list_name="sex", version=1)
        ChoiceOption.objects.create(
            choice_list=cl, code="1", label="Omusajja", language="lg",
        )
        clear_resolver_cache()
        assert resolve_label("sex", "1", language="lg") == "Omusajja"
        # English still resolves to the en row.
        assert resolve_label("sex", "1", language="en") == "Male"


@pytest.mark.django_db
class TestResolveOptions:
    def test_returns_active_option_set(self):
        options = resolve_options("sex")
        codes = [o["code"] for o in options]
        labels = [o["label"] for o in options]
        assert codes == ["1", "2"]
        assert labels == ["Male", "Female"]

    def test_missing_list_returns_empty(self):
        assert resolve_options("totally_missing") == []


@pytest.mark.django_db
class TestCacheInvalidation:
    def test_save_invalidates_cache(self):
        assert resolve_label("sex", "1") == "Male"
        # Mutate the seeded label and confirm next read picks it up.
        opt = ChoiceOption.objects.get(
            choice_list__list_name="sex",
            choice_list__version=1,
            code="1",
            language="en",
        )
        opt.label = "Mutated"
        opt.save()
        assert resolve_label("sex", "1") == "Mutated"
