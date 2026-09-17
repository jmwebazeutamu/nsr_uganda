"""Every number on the console home screen must come from the API.

The home screen shipped with a full set of hardcoded KPIs per role —
"DIH review queue 342", "Fast-track auto-promote 61.4%", "Bulk batches
awaiting dual-approval 4" — with sparklines and week-on-week trends, all
fabricated, against a registry holding 284 households. A live overlay
existed, but most fields mapped to null and the fallback quietly rendered
the fiction, so an operator could not tell which numbers were real.

These tests keep it honest: every KPI must name a field the
operator-kpis endpoint actually returns, and no invented series may come
back.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

REPO = Path(__file__).resolve().parent.parent.parent
HOME = REPO / "design" / "v0.1" / "screens" / "screens-home.jsx"
ENDPOINT = "/api/v1/rpt/dashboards/operator-kpis/"


def _kpi_block() -> str:
    src = HOME.read_text()
    start = src.index("const HOME_KPIS_BY_ROLE")
    return src[start:src.index("ROLE config", start)]


def _declared_fields() -> set[str]:
    return set(re.findall(r'field:\s*"([^"]+)"', _kpi_block()))


@pytest.mark.django_db
def test_every_home_kpi_field_is_returned_by_the_endpoint():
    """The check that would have caught the fabricated cards."""
    user_model = get_user_model()
    user = user_model.objects.create_user("kpi-probe", password="not-a-real-password")
    user.is_superuser = user.is_staff = True
    user.save()
    client = Client()
    client.force_login(user)

    response = client.get(ENDPOINT)
    assert response.status_code == 200, (
        f"{ENDPOINT} is unreachable, so every home KPI would render as an "
        f"em dash."
    )
    payload = response.json()

    declared = _declared_fields()
    assert declared, "no KPI fields declared — has the screen been rewritten?"
    missing = sorted(f for f in declared if f not in payload)
    assert not missing, (
        f"the home screen reads {missing} from {ENDPOINT}, which does not "
        f"return them. Those cards would show an em dash forever. Add the "
        f"field to the serializer, or drop the card."
    )


def test_no_fabricated_series_on_the_home_kpis():
    """spark/trend were invented week-long series drawn from a single
    point. They may only return when a real history endpoint is wired."""
    block = _kpi_block()
    for banned in ("spark:", "trend:", "trendValue:"):
        assert banned not in block, (
            f"{banned} is back on the home KPIs. The endpoint returns one "
            f"point; a series drawn from it is invented data."
        )


def test_kpis_are_not_read_from_the_demo_role_content():
    """ROLE_CONTENT may keep demo content for the standalone harness, but
    the rendered cards must not come from it."""
    src = HOME.read_text()
    assert "r.kpis.map" not in src, (
        "the home screen is rendering ROLE_CONTENT.kpis again — those are "
        "hardcoded demo numbers."
    )
    assert "HOME_KPIS_BY_ROLE[role]" in src


def test_unwired_queues_are_dropped_not_faked():
    src = HOME.read_text()
    assert "r.queues.filter(q => HOME_QUEUE_LIVE_MAP[q.title])" in src, (
        "queues without a live endpoint are being rendered again; they fall "
        "back to invented households with real-looking names and ULIDs."
    )


# --- sidebar badges -----------------------------------------------------

APP = REPO / "design" / "app.jsx"
NAV_HOOK = REPO / "design" / "v0.1" / "data" / "use-nav-counts.jsx"


def test_nav_badges_have_no_hardcoded_counts():
    """The sidebar badges showed 342 / 23 / 47 / 7 on every screen.

    Worse than the home cards, because they are visible everywhere and
    look like a live work queue.
    """
    src = APP.read_text()
    nav = src[src.index("const NAV = ["):src.index("]", src.index("my-programmes")) + 1]
    assert "count:" not in nav, (
        "the NAV list has hardcoded badge counts again; they render whenever "
        "the live fetch has not returned."
    )


def test_nav_count_hook_has_no_mock_fallback():
    src = NAV_HOOK.read_text()
    assert "NAV_COUNT_MOCK" not in src, (
        "the nav-count hook falls back to fixture values again. A fabricated "
        "'342' next to DIH review is worse than no badge: an operator cannot "
        "tell it is invented and will plan work around it."
    )
    assert "NAV_COUNT_INITIAL" in src


def test_nav_badge_renders_only_for_a_real_number():
    src = APP.read_text()
    assert 'typeof displayCount === "number"' in src, (
        "the badge no longer checks that it has a real number, so a null or "
        "undefined count could render."
    )
