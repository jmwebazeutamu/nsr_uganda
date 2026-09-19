"""The wide view must survive the production build and the URL it needs.

A list screen can be opened wide two ways (ADR-0030): maximised in place,
or popped out into a second window at `?wide=<screen>`. The pop-out is
the fragile one — it is a real navigation, so it depends on things that
live outside the JSX:

  * the module being in both console manifests, ahead of the screens
    that call it (the sources declare globals and are evaluated in
    manifest order, so a module loaded too late is simply absent);
  * `/console/` accepting a query string and still requiring a session,
    because the popped window renders the same personal data;
  * the file surviving `scripts/build_console.mjs`, which is what the
    container actually serves. `/console/` 404'd for the whole of
    Sprint 0 because a file existed in `design/` and nowhere else.

The behaviour itself is covered by the jsdom cases in
design/v0.1/components/wide-view.test.jsx.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

REPO = Path(__file__).resolve().parent.parent.parent
MODULE = REPO / "design" / "v0.1" / "components" / "wide-view.jsx"
HARNESSES = {
    "operator": REPO / "design" / "nsr-mis-console.html",
    "admin": REPO / "design" / "nsr-mis-admin-console.html",
}
MANIFESTS = {
    "operator": REPO / "static" / "console" / "manifest.json",
    "admin": REPO / "static" / "console" / "manifest-admin.json",
}
WIDE_FILE = "wide-view"

pytestmark = pytest.mark.django_db


@pytest.fixture
def signed_in():
    user_model = get_user_model()
    user_model.objects.create_user("wide-tester", password="not-a-real-password")
    client = Client()
    assert client.login(username="wide-tester", password="not-a-real-password")
    return client


def _script_order(html: Path) -> list[str]:
    return re.findall(r'src="([^"]+\.jsx)"', html.read_text())


def test_the_module_exists_and_exports_what_screens_call():
    src = MODULE.read_text()
    for name in ("useWideView", "WideViewButtons", "WideShell", "WideDetailHost"):
        assert f"{name}," in src or f"{name}\n" in src, f"{name} is no longer exported"


@pytest.mark.parametrize("shell", sorted(HARNESSES))
def test_loaded_before_any_screen_that_needs_it(shell):
    order = _script_order(HARNESSES[shell])
    wide = [i for i, s in enumerate(order) if WIDE_FILE in s]
    assert wide, f"the {shell} console no longer loads {WIDE_FILE}.jsx"
    screens = [i for i, s in enumerate(order) if "/screens/" in s]
    # Evaluated as classic scripts in this order: a screen calling
    # useWideView before the module has run gets a ReferenceError at
    # render, not a missing button.
    assert wide[0] < min(screens), (
        f"{WIDE_FILE}.jsx is loaded after the screens in the {shell} console"
    )


@pytest.mark.parametrize("shell", sorted(MANIFESTS))
def test_survives_the_production_build(shell):
    manifest = MANIFESTS[shell]
    if not manifest.is_file():
        pytest.skip("console not built in this checkout — CI builds before running")
    scripts = json.loads(manifest.read_text())["scripts"]
    assert any(WIDE_FILE in s for s in scripts), (
        f"{WIDE_FILE} is missing from the built {shell} console, so the "
        "wide view would exist in the harness and not in the container"
    )


def test_a_wide_window_url_is_served(signed_in):
    # The pop-out navigates here. A 404 or a redirect to the harness
    # would leave the operator with a blank second window.
    assert signed_in.get("/console/", {"wide": "dih"}).status_code == 200


def test_a_wide_window_still_requires_a_session():
    # It renders the same staged records as the console tab. Being a
    # second window earns it no exemption.
    response = Client().get("/console/", {"wide": "dih"})
    assert response.status_code in (302, 403), response.status_code
    if response.status_code == 302:
        assert "/login" in response["Location"] or "accounts" in response["Location"]


def test_filters_travel_in_the_url_without_breaking_the_route(signed_in):
    filters = json.dumps({"quick": "state_quality_failed", "source": "Kobo"})
    response = signed_in.get("/console/", {"wide": "dih", "filters": filters})
    assert response.status_code == 200


def test_the_shell_knows_which_screens_have_a_wide_view():
    # A screen not listed must say so rather than rendering a
    # normal-width page in a window opened expressly to be wider.
    src = (REPO / "design" / "app.jsx").read_text()
    assert "WIDE_SCREENS" in src
    assert "dih:" in src.split("WIDE_SCREENS")[1][:400]
    assert "No wide view for this screen" in src
