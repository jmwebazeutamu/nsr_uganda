"""NIRA mock tests."""

from __future__ import annotations

import pytest

from apps.identity_verification.mock import NiraError, verify_nin


class TestVerifyNin:
    def test_match_returns_demographics(self):
        result = verify_nin("CM1234567890AB")
        assert result["status"] == "match"
        demo = result["demographics"]
        assert demo["nin"] == "CM1234567890AB"
        assert demo["sex"] == "M"

    def test_female_prefix_returns_f(self):
        assert verify_nin("CF1234567890AB")["demographics"]["sex"] == "F"

    def test_no_match_suffix(self):
        assert verify_nin("CM1234567890NM") == {"status": "no_match"}

    def test_mismatch_suffix(self):
        result = verify_nin("CM1234567890MM")
        assert result["status"] == "mismatch"

    def test_service_unavailable_suffix_raises(self):
        with pytest.raises(NiraError):
            verify_nin("CM1234567890SU")

    def test_bad_format(self):
        result = verify_nin("BADNIN")
        assert result["status"] == "bad_format"


class TestVerifyApi:
    @pytest.fixture(autouse=True)
    def enable_debug(self, settings):
        settings.DEBUG = True

    @pytest.fixture
    def auth_client(self, db, client, django_user_model):
        user = django_user_model.objects.create_user(username="t-user", password="t-pass")
        client.force_login(user)
        return client

    def test_endpoint_returns_match(self, auth_client):
        r = auth_client.post("/api/v1/idv/nira-mock/verify",
                             data='{"nin": "CM1234567890AB"}',
                             content_type="application/json")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "match"

    def test_endpoint_service_unavailable(self, auth_client):
        r = auth_client.post("/api/v1/idv/nira-mock/verify",
                             data='{"nin": "CM1234567890SU"}',
                             content_type="application/json")
        assert r.status_code == 503

    def test_endpoint_disabled_outside_debug(self, auth_client, settings):
        settings.DEBUG = False
        r = auth_client.post("/api/v1/idv/nira-mock/verify",
                             data='{"nin": "CM1234567890AB"}',
                             content_type="application/json")
        assert r.status_code == 404

    def test_endpoint_refuses_unauthenticated(self, db, client):
        # Sprint 1 security gate: no auth -> 403.
        r = client.post("/api/v1/idv/nira-mock/verify",
                        data='{"nin": "CM1234567890AB"}',
                        content_type="application/json")
        assert r.status_code == 403
