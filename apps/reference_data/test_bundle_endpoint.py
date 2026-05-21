"""Contract tests for the ChoiceList bundle endpoint (US-S22-005e).

The bundle is what the questionnaire runtime fetches — Android CAPI
on every sync, web intake on form load. It must be:

* Deterministic — same bundle bytes for same (as_of, lang).
* ETag-stable — sha256 of the canonical JSON; supports If-None-Match.
* Versioned — as_of selects the historically-active ChoiceList row.
* Language-aware — `lang=lg` overlays lg labels, falls back to en.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.reference_data.models import (
    ChoiceList,
    ChoiceListStatus,
    ChoiceOption,
)
from apps.reference_data.services import clear_resolver_cache

URL = "/api/v1/reference-data/choice-list-bundle/"


@pytest.fixture
def api(db):
    user_cls = get_user_model()
    u = user_cls.objects.create_user(username="bundle-test", password="p")
    c = APIClient()
    c.force_authenticate(user=u)
    return c


@pytest.fixture(autouse=True)
def _flush():
    clear_resolver_cache()
    yield
    clear_resolver_cache()


@pytest.mark.django_db
class TestBundleSchema:
    def test_returns_200_with_bundle_shape(self, api):
        r = api.get(URL)
        assert r.status_code == 200
        assert "as_of" in r.data
        assert "lang" in r.data
        assert isinstance(r.data["lists"], list)
        assert r.data["lang"] == "en"

    def test_each_list_has_required_keys(self, api):
        r = api.get(URL)
        # Find tenure (we know it's seeded).
        tenure = next(lst for lst in r.data["lists"] if lst["list_name"] == "tenure")
        assert tenure["version"] == 1
        first_opt = tenure["options"][0]
        for key in ("code", "label", "sort_order", "parent_code"):
            assert key in first_opt

    def test_includes_all_seeded_lists(self, api):
        # 46 legacy + 14 partner (US-S23-002) + 8 programme wizard
        # (US-S25-001) + 1 beneficiary (US-S25-006) + 1 referral
        # (US-S26-002) + 24 detail-entities (US-S22-DE-02) = 94.
        r = api.get(URL)
        assert len(r.data["lists"]) == 94

    def test_sex_options_resolved(self, api):
        r = api.get(URL)
        sex = next(lst for lst in r.data["lists"] if lst["list_name"] == "sex")
        codes = [o["code"] for o in sex["options"]]
        labels = [o["label"] for o in sex["options"]]
        assert codes == ["1", "2"]
        assert labels == ["Male", "Female"]


@pytest.mark.django_db
class TestETag:
    def test_etag_header_is_strong_quoted_hex(self, api):
        r = api.get(URL)
        etag = r["ETag"]
        assert etag.startswith('"') and etag.endswith('"')
        # 64 hex chars between the quotes.
        assert len(etag) == 66

    def test_etag_stable_across_calls(self, api):
        a = api.get(URL)["ETag"]
        b = api.get(URL)["ETag"]
        assert a == b

    def test_if_none_match_returns_304(self, api):
        first = api.get(URL)
        etag = first["ETag"]
        r = api.get(URL, HTTP_IF_NONE_MATCH=etag)
        assert r.status_code == 304
        assert r["ETag"] == etag

    def test_etag_changes_after_option_edit(self, api):
        a = api.get(URL)["ETag"]
        # Approve a new option on tenure — the cache signal flushes
        # and the bundle should re-compute to a fresh ETag.
        tenure = ChoiceList.objects.get(list_name="tenure", version=1)
        ChoiceOption.objects.create(
            choice_list=tenure, code="99", label="Bundle-edit test option",
            language="en", sort_order=99,
        )
        b = api.get(URL)["ETag"]
        assert a != b


@pytest.mark.django_db
class TestAsOfFiltering:
    def test_invalid_as_of_returns_400(self, api):
        r = api.get(URL, {"as_of": "not-a-date"})
        assert r.status_code == 400

    def test_explicit_as_of_today_matches_default(self, api):
        a = api.get(URL).data["lists"]
        today = date.today().isoformat()
        b = api.get(URL, {"as_of": today}).data["lists"]
        assert a == b

    def test_old_as_of_picks_old_version(self, api):
        today = date.today()
        ten_days_ago = today - timedelta(days=10)
        last_year = today - timedelta(days=400)

        # Narrow v1's window to be active in the past only.
        seeded = ChoiceList.objects.get(list_name="sex", version=1)
        seeded.effective_from = last_year
        seeded.effective_to = ten_days_ago
        seeded.save()

        # Land a v2 active from ten_days_ago with relabelled options.
        v2 = ChoiceList.objects.create(
            list_name="sex", version=2,
            status=ChoiceListStatus.ACTIVE,
            effective_from=ten_days_ago, effective_to=None,
            author="test", approved_by="reviewer",
        )
        ChoiceOption.objects.create(
            choice_list=v2, code="1", label="Man", language="en",
        )
        ChoiceOption.objects.create(
            choice_list=v2, code="2", label="Woman", language="en",
        )
        clear_resolver_cache()

        today_data = api.get(URL).data
        old_data = api.get(URL, {"as_of": (today - timedelta(days=180)).isoformat()}).data

        sex_today = next(lst for lst in today_data["lists"] if lst["list_name"] == "sex")
        sex_old = next(lst for lst in old_data["lists"] if lst["list_name"] == "sex")
        assert sex_today["version"] == 2
        assert sex_today["options"][0]["label"] == "Man"
        assert sex_old["version"] == 1
        assert sex_old["options"][0]["label"] == "Male"


@pytest.mark.django_db
class TestListsFilter:
    """US-S23-011 — ?lists=a,b,c trims the bundle to the named
    ChoiceLists. ETag still stable per (lists, as_of, lang)."""

    def test_lists_filter_returns_only_named(self, api):
        r = api.get(URL, {"lists": "sex,partner_type"})
        names = {lst["list_name"] for lst in r.data["lists"]}
        assert names == {"sex", "partner_type"}

    def test_empty_lists_param_returns_full_bundle(self, api):
        a = api.get(URL).data["lists"]
        b = api.get(URL, {"lists": ""}).data["lists"]
        assert len(a) == len(b)

    def test_unknown_list_silently_omitted(self, api):
        r = api.get(URL, {"lists": "sex,not_a_list"})
        names = [lst["list_name"] for lst in r.data["lists"]]
        assert names == ["sex"]

    def test_etag_differs_when_lists_filter_differs(self, api):
        full = api.get(URL)["ETag"]
        scoped = api.get(URL, {"lists": "sex"})["ETag"]
        assert full != scoped


@pytest.mark.django_db
class TestLanguageFallback:
    def test_missing_language_falls_back_to_en(self, api):
        r = api.get(URL, {"lang": "lg"})
        assert r.status_code == 200
        # No lg rows in the seed — labels should still be the en labels.
        sex = next(lst for lst in r.data["lists"] if lst["list_name"] == "sex")
        assert sex["options"][0]["label"] == "Male"

    def test_lang_overrides_en_when_present(self, api):
        cl = ChoiceList.objects.get(list_name="sex", version=1)
        ChoiceOption.objects.create(
            choice_list=cl, code="1", label="Omusajja", language="lg",
        )
        r = api.get(URL, {"lang": "lg"})
        sex = next(lst for lst in r.data["lists"] if lst["list_name"] == "sex")
        # Lookup option with code "1"
        opt1 = next(o for o in sex["options"] if o["code"] == "1")
        assert opt1["label"] == "Omusajja"

    def test_default_language_unchanged_by_lg_row(self, api):
        cl = ChoiceList.objects.get(list_name="sex", version=1)
        ChoiceOption.objects.create(
            choice_list=cl, code="1", label="Omusajja", language="lg",
        )
        r = api.get(URL)  # default en
        sex = next(lst for lst in r.data["lists"] if lst["list_name"] == "sex")
        opt1 = next(o for o in sex["options"] if o["code"] == "1")
        assert opt1["label"] == "Male"
