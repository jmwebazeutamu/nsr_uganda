"""KoboConnector unit tests (US-S11-003a).

Mocks the outbound `requests` layer with the `responses` library —
no live Kobo calls. The integration smoke test that hits a real
Kobo instance lives separately and is gated on KOBO_TEST_URL +
KOBO_TEST_TOKEN environment variables (see test_kobo_live.py once
US-S11-003b lands).

Coverage target: ≥90% of apps/ingestion_hub/connectors/kobo.py.
The branches we exercise here:
- successful test_connection with X-OpenRosa-Version
- 401 token rejection -> ok=False, error='auth_failed:...'
- network error -> ok=False, error=str(exception)
- 5xx with retry budget exhausted -> ok=False
- 5xx then success -> ok=True with latency reflecting the retry wait
- missing server_url/token -> early-out with no HTTP call
- list_forms pagination shape
- pull_submissions paginates via `next` and forwards `since` once
- acquire_token success + 401
"""

from __future__ import annotations

import pytest
import responses
from requests.exceptions import RequestException

from apps.ingestion_hub.connectors import base as base_module
from apps.ingestion_hub.connectors import kobo as kobo_module
from apps.ingestion_hub.connectors.base import ConnectionTestResult
from apps.ingestion_hub.connectors.kobo import KoboConnector, acquire_token

# Tests use these placeholder values throughout. The real humanitarian
# Kobo URL is `https://kobo.humanitarianresponse.info`, but we use a
# synthetic host here so a misconfigured `responses` mock fails noisily
# instead of accidentally reaching the live service.
TEST_URL = "https://kobo.test.invalid"
TEST_TOKEN = "test-token"  # noqa: S105 — synthetic test placeholder


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch):
    """Stub the retry sleep so the 5xx-retry test doesn't wait 4
    seconds of real wall-clock per run."""
    monkeypatch.setattr(kobo_module.time, "sleep", lambda _s: None)


class TestRegistry:
    def test_kobo_registered_under_pilot_code(self):
        """KoboConnector registers under 'KOBO-PILOT' to match the
        SourceSystem seed in scripts/seed_dih_sources.py."""
        c = base_module.get_connector("KOBO-PILOT")
        assert c is not None
        assert isinstance(c, KoboConnector)

    def test_kobo_protocol_methods_present(self):
        c = base_module.get_connector("KOBO-PILOT")
        assert callable(c.test_connection)
        assert callable(c.list_forms)
        assert callable(c.pull_submissions)
        # canonicalize wired in US-S11-011; process stays None
        # (Kobo uses the generic DIH run path, not a side-effecting
        # driver like NIRA reverse-feed).
        assert callable(c.canonicalize)
        assert c.process is None


class TestTestConnection:
    @responses.activate
    def test_success_returns_ok_with_latency_and_version(self):
        responses.add(
            responses.GET,
            f"{TEST_URL}/api/v2/assets.json?limit=1",
            json={"results": []},
            status=200,
            headers={"X-OpenRosa-Version": "1.0"},
        )
        result = KoboConnector().test_connection(
            {"server_url": TEST_URL, "token": TEST_TOKEN},
        )
        assert isinstance(result, ConnectionTestResult)
        assert result.ok is True
        assert result.latency_ms >= 0
        assert result.server_version == "1.0"
        assert result.error is None

    @responses.activate
    def test_auth_failure_returns_auth_failed(self):
        responses.add(
            responses.GET, f"{TEST_URL}/api/v2/assets.json?limit=1",
            json={"detail": "Invalid token."}, status=401,
        )
        result = KoboConnector().test_connection(
            {"server_url": TEST_URL, "token": "wrong-token"},
        )
        assert result.ok is False
        assert result.error is not None and "auth_failed" in result.error

    @responses.activate
    def test_4xx_other_than_401_returns_upstream_error(self):
        responses.add(
            responses.GET, f"{TEST_URL}/api/v2/assets.json?limit=1",
            json={"detail": "Forbidden"}, status=403,
        )
        result = KoboConnector().test_connection(
            {"server_url": TEST_URL, "token": TEST_TOKEN},
        )
        assert result.ok is False
        assert "403" in (result.error or "")

    @responses.activate
    def test_network_error_returns_failure(self):
        # responses raises ConnectionError when no matching mock is found
        # AND assert_all_requests_are_fired=False; cleaner: explicit body.
        responses.add(
            responses.GET, f"{TEST_URL}/api/v2/assets.json?limit=1",
            body=RequestException("connection refused"),
        )
        result = KoboConnector().test_connection(
            {"server_url": TEST_URL, "token": TEST_TOKEN},
        )
        assert result.ok is False
        assert result.error is not None

    @responses.activate
    def test_5xx_retries_and_recovers(self):
        """Two 503s then a 200 — retry budget is 3 attempts."""
        url = f"{TEST_URL}/api/v2/assets.json?limit=1"
        responses.add(responses.GET, url, status=503)
        responses.add(responses.GET, url, status=503)
        responses.add(
            responses.GET, url, json={"results": []}, status=200,
        )
        result = KoboConnector().test_connection(
            {"server_url": TEST_URL, "token": TEST_TOKEN},
        )
        assert result.ok is True

    @responses.activate
    def test_5xx_exhausts_retry_budget(self):
        url = f"{TEST_URL}/api/v2/assets.json?limit=1"
        for _ in range(kobo_module.MAX_ATTEMPTS):
            responses.add(responses.GET, url, status=503)
        result = KoboConnector().test_connection(
            {"server_url": TEST_URL, "token": TEST_TOKEN},
        )
        assert result.ok is False
        assert result.error is not None

    def test_missing_credentials_short_circuits(self):
        result = KoboConnector().test_connection({})
        assert result.ok is False
        assert result.latency_ms == 0
        assert result.error == "server_url and token required"

    def test_missing_token_short_circuits(self):
        result = KoboConnector().test_connection({"server_url": TEST_URL})
        assert result.ok is False
        assert result.latency_ms == 0


class TestListForms:
    @responses.activate
    def test_normalises_assets_response(self):
        responses.add(
            responses.GET, f"{TEST_URL}/api/v2/assets.json",
            json={
                "results": [
                    {"uid": "aXyZ", "name": "Pilot survey",
                     "asset_type": "survey", "deployment__active": True},
                    {"uid": "bMnO", "name": "Draft form",
                     "asset_type": "survey", "deployment__active": False},
                ],
            },
            status=200,
        )
        forms = KoboConnector().list_forms(
            {"server_url": TEST_URL, "token": TEST_TOKEN},
        )
        assert forms == [
            {"uid": "aXyZ", "name": "Pilot survey",
             "asset_type": "survey", "deployed": True},
            {"uid": "bMnO", "name": "Draft form",
             "asset_type": "survey", "deployed": False},
        ]

    @responses.activate
    def test_propagates_http_errors(self):
        responses.add(
            responses.GET, f"{TEST_URL}/api/v2/assets.json",
            status=401, json={"detail": "bad token"},
        )
        with pytest.raises(RequestException):
            KoboConnector().list_forms(
                {"server_url": TEST_URL, "token": "bad"},
            )


class TestPullSubmissions:
    @responses.activate
    def test_paginates_through_next_link(self):
        page1 = {
            "results": [{"_id": 1}, {"_id": 2}],
            "next": f"{TEST_URL}/api/v2/assets/FORM/data.json?cursor=p2",
        }
        page2 = {"results": [{"_id": 3}], "next": None}
        responses.add(
            responses.GET, f"{TEST_URL}/api/v2/assets/FORM/data.json",
            json=page1, status=200,
        )
        responses.add(
            responses.GET, f"{TEST_URL}/api/v2/assets/FORM/data.json",
            json=page2, status=200,
        )
        rows = list(KoboConnector().pull_submissions(
            {"server_url": TEST_URL, "token": TEST_TOKEN},
            form_id="FORM",
        ))
        assert [r["_id"] for r in rows] == [1, 2, 3]

    @responses.activate
    def test_forwards_since_filter_on_first_call(self):
        responses.add(
            responses.GET, f"{TEST_URL}/api/v2/assets/FORM/data.json",
            json={"results": [], "next": None}, status=200,
        )
        list(KoboConnector().pull_submissions(
            {"server_url": TEST_URL, "token": TEST_TOKEN},
            form_id="FORM", since="2026-05-01T00:00:00",
        ))
        # The first (and only) recorded call must carry the query param.
        call = responses.calls[0].request
        assert "_submission_time" in call.url
        assert "2026-05-01" in call.url


class TestAcquireToken:
    @responses.activate
    def test_success_returns_token(self):
        responses.add(
            responses.POST, f"{TEST_URL}/token/?format=json",
            json={"token": "freshly-minted-token"}, status=200,
        )
        token = acquire_token(TEST_URL, "user", "secret")
        assert token == "freshly-minted-token"

    @responses.activate
    def test_401_raises(self):
        responses.add(
            responses.POST, f"{TEST_URL}/token/?format=json",
            json={"non_field_errors": ["Unable to log in"]}, status=401,
        )
        with pytest.raises(RequestException, match="rejected credentials"):
            acquire_token(TEST_URL, "user", "wrong")

    @responses.activate
    def test_missing_token_field_raises(self):
        responses.add(
            responses.POST, f"{TEST_URL}/token/?format=json",
            json={"unexpected": "shape"}, status=200,
        )
        with pytest.raises(RequestException, match="no token field"):
            acquire_token(TEST_URL, "user", "secret")


# --- US-S11-011 — canonical mapper -------------------------------------


# A realistic Kobo submission shaped like the NSR socio-economic
# questionnaire v2 (March 2026). Kept lean — only the fields the
# canonical mapper touches — but uses the exact field-code names so
# the mapper's structural assumptions get exercised.
SAMPLE_KOBO_PAYLOAD = {
    "_id": 753454740,
    "_uuid": "seed-00010",
    "_xform_id_string": "aRpVGbQLmPbVo3e4XUjSGe",
    "_submission_time": "2026-05-15T15:37:47",
    "_submitted_by": "tester_a",
    "a0_region": "western",
    "a1_subregion": "kigezi",
    "a2_district_city": "412",
    "a3_county_municipality": "412_02",
    "a4_subcounty_division_tc": "412_02_05",
    "a5_parish_ward": "412_02_05_01",
    "a6_lc1_village_cell": "Akello Village",
    "a7_rural_urban": "1",
    "a8_enumeration_area": "EA-767",
    "a9_household_number": "HH-00010",
    "a11_12_gps": "-0.237755 31.087186 0 9",
    "b3_address": "KABWOMA, NYAKAGYEME",
    "household_members": [
        {
            "household_members/member_index": "1",
            "household_members/c1_full_name": "Nakalema Daniel",
            "household_members/c2_relationship": "01",
            "household_members/c4_sex": "1",
            "household_members/c5_date_of_birth": "1966-10-16",
            "household_members/c6_age_years": "60",
            "household_members/c8_nin_status": "2",
            "household_members/c11_residency_status": "01",
        },
        {
            "household_members/member_index": "2",
            "household_members/c1_full_name": "Tumusiime Joseph",
            "household_members/c2_relationship": "05",
            "household_members/c4_sex": "1",
            "household_members/c5_date_of_birth": "1997-02-04",
            "household_members/c6_age_years": "29",
            "household_members/c8_nin_status": "1",
            "household_members/c9_nin": "CM738402535720",
            "household_members/c17_has_phone": "1",
            "household_members/c18_telephone_1": "0398272759",
            "household_members/c11_residency_status": "02",
        },
        {
            "household_members/member_index": "3",
            "household_members/c1_full_name": "Achen Brian",
            "household_members/c2_relationship": "10",
            "household_members/c4_sex": "1",
            "household_members/c6_age_years": "7",
            "household_members/c8_nin_status": "3",
        },
    ],
}


class TestKoboCanonicalMapper:
    def test_canonicalize_wired_on_connector(self):
        """KoboConnector.canonicalize must point at kobo_to_canonical;
        the US-S8-005 framework dispatch goes through this attribute."""
        from apps.ingestion_hub.connectors.base import get_connector
        c = get_connector("KOBO-PILOT")
        assert c.canonicalize is not None
        # Smoke test the dispatch — same module-level function.
        from apps.ingestion_hub.connectors.kobo import kobo_to_canonical
        assert c.canonicalize is kobo_to_canonical

    def test_geographic_codes_translated_to_nsr_canonical(self):
        """The Kobo form writes lowercase names + underscore codes;
        the canonical mapper translates to the NSR convention used by
        load_ubos_geography (R-/SR- prefixed for region/sub-region,
        dot-separated for district downstream, fabricated village
        code from parish + slug(village_name))."""
        from apps.ingestion_hub.connectors.kobo import kobo_to_canonical
        out = kobo_to_canonical(SAMPLE_KOBO_PAYLOAD)
        assert out["geographic"] == {
            "region": "R-WESTERN",
            "sub_region": "SR-KIGEZI-WESTERN",
            "district": "412",
            "county": "412.02",
            "sub_county": "412.02.05",
            "parish": "412.02.05.01",
            "village": "412.02.05.01.AKELLO-VILLAGE",
        }

    def test_geo_source_keys_capture_original_form_values(self):
        """Pre-canonicalisation values stay in _source_keys for the
        UPD reviewer to inspect."""
        from apps.ingestion_hub.connectors.kobo import kobo_to_canonical
        out = kobo_to_canonical(SAMPLE_KOBO_PAYLOAD)
        sk = out["_source_keys"]
        assert sk["kobo_region_name"] == "western"
        assert sk["kobo_subregion_name"] == "kigezi"
        assert sk["kobo_village_name"] == "Akello Village"

    def test_urban_rural_code_maps_to_seed_code(self):
        # Post-ADR-0010, canonical_payload carries the ChoiceOption.code
        # from the seeded rural_urban list (1=Urban, 2=Rural). Kobo's
        # a7_rural_urban is inverted on the questionnaire instrument:
        # "2" means urban, "1" means rural.
        from apps.ingestion_hub.connectors.kobo import kobo_to_canonical
        out = kobo_to_canonical(SAMPLE_KOBO_PAYLOAD)
        assert out["urban_rural"] == "2"  # a7_rural_urban = "1" → Rural (seed 2)

        urban = {**SAMPLE_KOBO_PAYLOAD, "a7_rural_urban": "2"}
        assert kobo_to_canonical(urban)["urban_rural"] == "1"  # Urban (seed 1)

    def test_gps_string_parses_lat_lng_accuracy(self):
        from apps.ingestion_hub.connectors.kobo import kobo_to_canonical
        out = kobo_to_canonical(SAMPLE_KOBO_PAYLOAD)
        assert out["gps_lat"] == pytest.approx(-0.237755)
        assert out["gps_lng"] == pytest.approx(31.087186)
        assert out["gps_accuracy_m"] == pytest.approx(9.0)

    def test_gps_missing_yields_none(self):
        from apps.ingestion_hub.connectors.kobo import kobo_to_canonical
        without_gps = {k: v for k, v in SAMPLE_KOBO_PAYLOAD.items() if k != "a11_12_gps"}
        out = kobo_to_canonical(without_gps)
        assert out["gps_lat"] is None and out["gps_lng"] is None

    def test_household_head_detection_uses_relationship_code(self):
        from apps.ingestion_hub.connectors.kobo import kobo_to_canonical
        out = kobo_to_canonical(SAMPLE_KOBO_PAYLOAD)
        heads = [m for m in out["members"] if m["is_head"]]
        assert len(heads) == 1
        assert heads[0]["surname"] == "Nakalema"
        assert heads[0]["first_name"] == "Daniel"

    def test_member_name_split_surname_first(self):
        from apps.ingestion_hub.connectors.kobo import kobo_to_canonical
        out = kobo_to_canonical(SAMPLE_KOBO_PAYLOAD)
        names = [(m["surname"], m["first_name"]) for m in out["members"]]
        assert names == [
            ("Nakalema", "Daniel"),
            ("Tumusiime", "Joseph"),
            ("Achen", "Brian"),
        ]

    def test_sex_code_passthrough_to_seed_code(self):
        # Post-ADR-0010, the canonical_payload carries the raw
        # ChoiceOption.code from the seeded sex list (1=Male, 2=Female).
        # Kobo's UBOS coding is identical, so the connector is a
        # passthrough — no translation to "M"/"F".
        from apps.ingestion_hub.connectors.kobo import kobo_to_canonical
        out = kobo_to_canonical(SAMPLE_KOBO_PAYLOAD)
        assert all(m["sex"] == "1" for m in out["members"])

    def test_nin_populated_only_when_status_indicates_card(self):
        """c8_nin_status='1' (has card) → nin field populated.
        '2' (applied) or '3' (not applied) → nin stays blank even if
        c9_nin happens to be present."""
        from apps.ingestion_hub.connectors.kobo import kobo_to_canonical
        out = kobo_to_canonical(SAMPLE_KOBO_PAYLOAD)
        ninify = {m["line_number"]: m["nin"] for m in out["members"]}
        assert ninify == {1: "", 2: "CM738402535720", 3: ""}

    def test_age_years_coerced_to_int(self):
        from apps.ingestion_hub.connectors.kobo import kobo_to_canonical
        out = kobo_to_canonical(SAMPLE_KOBO_PAYLOAD)
        ages = [m["age_years"] for m in out["members"]]
        assert ages == [60, 29, 7]

    def test_source_keys_capture_lineage(self):
        from apps.ingestion_hub.connectors.kobo import kobo_to_canonical
        out = kobo_to_canonical(SAMPLE_KOBO_PAYLOAD)
        sk = out["_source_keys"]
        assert sk["kobo_submission_id"] == "753454740"
        assert sk["kobo_uuid"] == "seed-00010"
        assert sk["kobo_form_id"] == "aRpVGbQLmPbVo3e4XUjSGe"
        assert sk["kobo_household_number"] == "HH-00010"

    def test_missing_geography_raises_keyerror(self):
        from apps.ingestion_hub.connectors.kobo import kobo_to_canonical
        broken = {k: v for k, v in SAMPLE_KOBO_PAYLOAD.items() if k != "a2_district_city"}
        with pytest.raises(KeyError, match="a2_district_city"):
            kobo_to_canonical(broken)

    def test_empty_roster_raises_keyerror(self):
        from apps.ingestion_hub.connectors.kobo import kobo_to_canonical
        rosterless = {**SAMPLE_KOBO_PAYLOAD, "household_members": []}
        with pytest.raises(KeyError, match="household_members"):
            kobo_to_canonical(rosterless)
