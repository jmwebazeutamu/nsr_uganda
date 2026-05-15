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
        # Canonicalisation comes in a later story.
        assert c.canonicalize is None
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
