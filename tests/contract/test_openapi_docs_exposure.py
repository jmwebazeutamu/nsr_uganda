"""Contract test for F1 — the OpenAPI spec must not be world-readable on a
deployed host.

Regression guard for the 2026-08-08 security audit finding: /api/schema/ and
/api/docs/ were unconditionally AllowAny, so a production host published 259
paths (~375 KB) including nin / nin_value / date_of_birth / surname / gps
field names to anonymous callers.
"""

import pytest
from django.test import override_settings
from django.urls import clear_url_caches, reverse
from rest_framework.test import APIClient


def _fresh_client():
    # permission_classes are bound at import time in nsr_mis.urls, so the
    # module must be re-imported for an override to take effect.
    import importlib

    import nsr_mis.urls
    importlib.reload(nsr_mis.urls)
    clear_url_caches()
    return APIClient()


@pytest.mark.django_db
class TestOpenApiDocsExposure:

    @override_settings(NSR_PUBLIC_API_DOCS=False, ROOT_URLCONF="nsr_mis.urls")
    def test_schema_requires_auth_when_not_public(self):
        client = _fresh_client()
        r = client.get("/api/schema/")
        assert r.status_code in (401, 403), (
            f"/api/schema/ returned {r.status_code} to an anonymous caller — "
            "the full API surface must not be world-readable on a deployed host"
        )

    @override_settings(NSR_PUBLIC_API_DOCS=False, ROOT_URLCONF="nsr_mis.urls")
    def test_swagger_requires_auth_when_not_public(self):
        client = _fresh_client()
        r = client.get("/api/docs/")
        assert r.status_code in (401, 403)

    @override_settings(NSR_PUBLIC_API_DOCS=True, ROOT_URLCONF="nsr_mis.urls")
    def test_schema_public_when_explicitly_opted_in(self):
        client = _fresh_client()
        r = client.get("/api/schema/")
        assert r.status_code == 200

    @override_settings(NSR_PUBLIC_API_DOCS=False, ROOT_URLCONF="nsr_mis.urls")
    def test_authenticated_user_still_reads_the_schema(self, django_user_model):
        django_user_model.objects.create_user(username="schema-reader", password="pw")
        client = _fresh_client()
        client.login(username="schema-reader", password="pw")
        r = client.get("/api/schema/")
        assert r.status_code == 200

    def test_healthz_stays_anonymous(self):
        # The container healthcheck and reverse proxy depend on it.
        client = APIClient()
        assert client.get(reverse("healthz")).status_code == 200
