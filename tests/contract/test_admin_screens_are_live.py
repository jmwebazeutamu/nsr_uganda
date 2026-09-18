"""Geography, roles, PMT config and the consent DPO queue read real data.

Each rendered a fixture that described a different registry:

  * geography — four regions against the registry's five, invented
    sub-regions, household counts in the millions. Granting an operator a
    scope code that does not exist yields an account that sees nothing,
    with no error to explain why.
  * PMT configuration — a fabricated v2 calibration. A model version is
    an approval-gated artefact; an invented one invites sign-off on
    something that was never submitted.
  * consent DPO queue — nine invented citizens asking to withdraw
    consent. Acting on one would mean processing a real person's data on
    the strength of a request they never made.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

REPO = Path(__file__).resolve().parent.parent.parent
SCREENS = REPO / "design" / "v0.1" / "screens"

REMOVED = {
    "screens-admin-refdata-geography.jsx": "GEO_TREE",
    "screens-admin-security-roles.jsx": "OPERATOR_SCOPE_OPTIONS",
    "screens-pmt-configuration.jsx": "PCFG_VERSIONS",
    "consent/screens-consent-dpo-queue.jsx": "TICKETS",
}


def _body(rel: str) -> str:
    src = (SCREENS / rel).read_text()
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"^\s*//.*$", "", src, flags=re.M)


@pytest.mark.parametrize("rel,fixture", REMOVED.items(), ids=lambda v: v if isinstance(v, str) else "")
def test_fixture_is_gone(rel, fixture):
    body = _body(rel)
    assert f"const {fixture}" not in body, (
        f"{rel}: the {fixture} fixture is back."
    )


def test_geography_does_not_fall_back_when_a_level_is_empty():
    body = _body("screens-admin-refdata-geography.jsx")
    assert "resp.results.length" not in body, (
        "geography requires a non-empty response again, so a level with no "
        "children falls through to fabricated units."
    )


def test_consent_queue_reports_the_module_being_disabled():
    body = _body("consent/screens-consent-dpo-queue.jsx")
    assert "503" in body and '"disabled"' in body, (
        "the DPO queue no longer distinguishes 'consent module is off' from "
        "'no tickets', so a disabled module looks like an empty queue."
    )


def test_pmt_configuration_handles_having_no_versions():
    body = _body("screens-pmt-configuration.jsx")
    assert "if (!selected)" in body, (
        "PMT configuration dereferences the selected version without a "
        "guard; with no versions it would crash instead of saying so."
    )


# --- the endpoints these screens depend on ------------------------------

@pytest.fixture
def admin_user(db):
    user_model = get_user_model()
    user = user_model.objects.create_user("admin-probe", password="not-a-real-password")
    user.is_superuser = user.is_staff = True
    user.save()
    return user


@pytest.mark.django_db
@pytest.mark.parametrize("url", [
    "/api/v1/admin/refdata/geography/?level=region",
    "/api/v1/reference-data/geographic-units/?level=region&page_size=5",
    "/api/v1/admin/pmt/versions/",
])
def test_endpoint_answers(admin_user, url):
    client = Client()
    client.force_login(admin_user)
    assert client.get(url).status_code == 200, (
        f"{url} does not answer; the screen that reads it renders empty."
    )


@pytest.mark.django_db
def test_geography_endpoint_returns_the_fields_the_screen_projects(admin_user):
    client = Client()
    client.force_login(admin_user)
    payload = client.get("/api/v1/admin/refdata/geography/?level=region").json()
    rows = payload.get("results", payload)
    if rows:
        for field in ("code", "name", "status", "effective_from",
                      "children_count", "households_count"):
            assert field in rows[0], (
                f"the geography serializer no longer returns {field!r}, which "
                f"_projectGeoRow reads."
            )
