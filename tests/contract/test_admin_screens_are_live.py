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
  * DDUP model versions — an ACTIVE v2 matcher with a 0.90 auto-merge
    threshold and 18,421 auto-merges already applied, approved by a named
    official. None of it existed.
  * the DDUP pair detail — two near-identical members at 0.94 similarity,
    on a screen whose primary action is an irreversible merge.
  * the PMT dashboard — a complete picture of the engine that decides
    eligibility: active model, band thresholds, coverage, recompute job.
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
    "screens-admin-workflow-ddup.jsx": "_DDUP_VERSIONS_MOCK",
}

# The PMT dashboard carried nine fixtures, one per panel.
PMT_DASHBOARD_FIXTURES = [
    "PMT_ACTIVE", "PMT_BANDS", "PMT_COVERAGE", "PMT_VARIABLES_TOP",
    "PMT_GEO", "PMT_DRIFT", "PMT_TRIGGERS", "PMT_JOB", "PMT_RECENT_EVENTS",
]


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


@pytest.mark.parametrize("fixture", PMT_DASHBOARD_FIXTURES)
def test_pmt_dashboard_fixture_is_gone(fixture):
    body = _body("screens-pmt-dashboard.jsx")
    assert f"const {fixture} = {{" not in body and f"const {fixture} = [" not in body, (
        f"screens-pmt-dashboard.jsx: the {fixture} fixture is back. Inside "
        f"the component these names are bound to live state, so a fixture "
        f"at module scope is invisible at the point of use."
    )


def test_pmt_dashboard_guards_an_absent_model():
    body = _body("screens-pmt-dashboard.jsx")
    assert "if (!PMT_ACTIVE || !PMT_COVERAGE || !PMT_JOB)" in body, (
        "the PMT dashboard dereferences the active model, coverage totals "
        "and recompute job without a guard; with the fixtures gone, a "
        "loading or failed fetch crashes the screen."
    )


def test_pmt_dashboard_does_not_announce_a_mock_preview():
    body = _body("screens-pmt-dashboard.jsx")
    assert "MOCK PREVIEW" not in body, (
        "the dashboard still has a MOCK PREVIEW mode; there is no mock left "
        "to preview."
    )


def test_pmt_configuration_reads_thresholds_from_its_own_version():
    """The empirical band cutoff is the score at which a household stops
    being eligible. The Configuration screen used to read it off the
    dashboard's fixture, so every version showed the same invented numbers.
    """
    body = _body("screens-pmt-configuration.jsx")
    assert "PMT_ACTIVE" not in body, (
        "PMT configuration reads the dashboard's PMT_ACTIVE fixture again."
    )
    assert "selected.thresholdsLatest" in body, (
        "PMT configuration no longer reads thresholdsLatest off the selected "
        "version."
    )


# Every record view in screens-admin-details.jsx took `record || {specimen}`.
# Nothing passes the prop, so each one only ever rendered its specimen: an
# invented district with household counts, an MGLSD user account with an MFA
# state and three IP-stamped audit entries, a DDUP pair at 0.94 similarity
# awaiting merge. All five are editable and offer a Save or Merge button.
RECORD_SCREENS = {
    "AdminGeoUnitDetailScreenRecord": "unit",
    "AdminUpdRoutingRuleEditScreenRecord": "rule",
    "AdminUserDetailScreenRecord": "user",
    "AdminChoiceListOptionEditScreenRecord": "option",
    "AdminDdupPairDetailScreenRecord": "pair",
}


@pytest.mark.parametrize("component,prop", RECORD_SCREENS.items())
def test_record_view_has_no_specimen_fallback(component, prop):
    body = _body("screens-admin-details.jsx")
    idx = body.index(f"const {component} = ")
    head = body[idx:idx + 600]
    assert f"= {prop} || {{" not in head, (
        f"{component} substitutes a specimen record again; nothing passes "
        f"`{prop}`, so the specimen is all anyone would ever see."
    )


@pytest.mark.parametrize("component,prop", RECORD_SCREENS.items())
def test_record_view_is_guarded_outside_its_hooks(component, prop):
    """The guard must sit in a wrapper. Returning early inside the record
    component would put its useState calls behind a condition, and React
    throws when the hook count changes between renders.
    """
    body = _body("screens-admin-details.jsx")
    wrapper = component[:-len("Record")]
    idx = body.index(f"const {wrapper} = (props) =>")
    head = body[idx:idx + 200]
    assert f"!props.{prop}" in head, (
        f"{wrapper} no longer guards on `{prop}` before delegating."
    )

    record = body.index(f"const {component} = ")
    end = body.index("\n};", record)
    assert f"if (!" not in body[record:record + 300], (
        f"{component} guards inside the component body, so its hooks are "
        f"called conditionally."
    )


def test_admin_nav_has_no_examples_group():
    body = _body("app-admin.jsx")
    assert "Examples (record views)" not in body, (
        "the admin console ships an 'Examples' nav group again; the record "
        "screens behind it have no record to show."
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


@pytest.mark.django_db
def test_version_detail_carries_its_own_empirical_thresholds(admin_user):
    """The Configuration screen projects `thresholds_latest` off the version
    it is showing. If the serializer stops sending it, the band-cutoff
    table silently shows an em dash for a model that has real thresholds.
    """
    from apps.pmt.models import PMTBandThreshold, PMTModelVersion

    mv = PMTModelVersion.objects.create(
        version=9901, status="active", band_strategy="percentile",
        band_cutoffs={"extreme_poverty": 10, "poverty": 30},
    )
    PMTBandThreshold.objects.create(
        model_version=mv, band_name="poverty", score_threshold="3.245000",
        percentile_rank=30, sample_size=1000,
    )

    client = Client()
    client.force_login(admin_user)
    resp = client.get(f"/api/v1/admin/pmt/versions/{mv.id}/")
    assert resp.status_code == 200, resp.status_code
    payload = resp.json()
    assert "thresholds_latest" in payload, (
        "the version detail no longer carries thresholds_latest."
    )
    assert payload["thresholds_latest"]["poverty"] == pytest.approx(3.245)
