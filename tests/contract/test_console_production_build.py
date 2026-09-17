"""The operator console must be served precompiled, with no third party.

`/console/` returned 404 in production for the whole of Sprint 0: the view
served raw files out of `design/`, and `design/` was excluded from the
Docker build context, so in a container those files simply did not exist.
`/admin/` worked, nothing else did.

The fix precompiles the console at image build time
(scripts/build_console.mjs) and renders a shell template that loads the
output. These tests pin the properties that made the fix worth doing, so
a later change cannot quietly reintroduce the browser-side Babel or the
CDN calls.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

REPO = Path(__file__).resolve().parent.parent.parent
HARNESS = REPO / "design" / "nsr-mis-console.html"
BUILD_SCRIPT = REPO / "scripts" / "build_console.mjs"
TEMPLATE = REPO / "nsr_mis" / "templates" / "console" / "index.html"
MANIFEST = REPO / "static" / "console" / "manifest.json"

pytestmark = pytest.mark.django_db


@pytest.fixture
def operator(db):
    user_model = get_user_model()
    return user_model.objects.create_user(
        "console-tester", password="not-a-real-password",
    )


@pytest.fixture
def client_in(operator):
    c = Client()
    c.force_login(operator)
    return c


# --- the build itself --------------------------------------------------

def test_build_script_exists():
    assert BUILD_SCRIPT.is_file(), (
        "scripts/build_console.mjs is missing — the Dockerfile's console-build "
        "stage runs it, so the image build would fail."
    )


def test_dockerfile_builds_and_copies_the_console():
    df = (REPO / "Dockerfile").read_text()
    assert "AS console-build" in df, "the console build stage is gone"
    assert "build_console.mjs" in df, "the Dockerfile never runs the console build"
    assert "COPY --from=console-build" in df, (
        "the compiled console is never copied into the runtime image, so "
        "/console/ will 404 exactly as it did before."
    )


def test_design_is_in_the_build_context():
    """design/ must reach the build stage or there is nothing to compile."""
    lines = [
        ln.strip()
        for ln in (REPO / ".dockerignore").read_text().splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    assert "design" not in lines, (
        "'design' is excluded by .dockerignore, so the console-build stage "
        "has no sources. This is the original cause of the /console/ 404."
    )


# --- no third parties, no browser-side compile -------------------------

def _markup() -> str:
    """The template with its {% comment %} block stripped.

    That block documents exactly what this change removed — unpkg, Babel,
    the development React builds — so scanning the raw file would match
    the prose describing the problem rather than the markup causing it.
    """
    html = TEMPLATE.read_text()
    return re.sub(r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}", "",
                  html, flags=re.S)


def test_template_loads_no_third_party_resources():
    html = _markup()
    for host in ("unpkg.com", "fonts.googleapis.com", "fonts.gstatic.com",
                 "cdn.jsdelivr.net", "cdnjs.cloudflare.com"):
        assert host not in html, (
            f"the console template requests {host}. The console renders "
            f"personal data; an external request discloses every operator's "
            f"IP to that third party."
        )


def test_template_does_not_ship_babel_or_text_babel():
    html = _markup()
    assert "babel" not in html.lower(), (
        "Babel is back in the console page — the JSX compile belongs at "
        "build time, not in the operator's browser."
    )
    assert 'type="text/babel"' not in html


def test_template_uses_react_production_builds():
    html = _markup()
    assert "react-18.3.1.production.min.js" in html
    assert "react-dom-18.3.1.production.min.js" in html
    # Match the filename, not the word: an HTML comment legitimately
    # mentions "development" to explain what the harness does differently.
    assert ".development.js" not in html, (
        "a React development build is referenced; those are larger, slower "
        "and emit dev-only warnings."
    )


# --- the manifest is the single source of load order -------------------

@pytest.mark.skipif(not MANIFEST.is_file(),
                    reason="console not built in this checkout (CI builds it in the image)")
def test_manifest_matches_the_harness_script_order():
    """Load order is load-bearing: the sources declare globals and depend
    on evaluation order. If the harness gains a screen and the manifest is
    stale, that screen is silently missing in production."""
    harness = HARNESS.read_text()
    srcs = re.findall(r'<script\s+type="text/babel"\s+src="([^"]+)"', harness)
    expected = [s.replace(".jsx", "").replace("/", "-") + ".js" for s in srcs]
    actual = json.loads(MANIFEST.read_text())["scripts"]
    assert actual == expected, (
        "the built console is out of step with the harness. Re-run "
        "`node scripts/build_console.mjs`."
    )


# --- the view ----------------------------------------------------------

def test_console_requires_authentication():
    resp = Client().get("/console/")
    assert resp.status_code == 302
    assert "/login/" in resp["Location"]


@pytest.mark.skipif(not MANIFEST.is_file(),
                    reason="console not built in this checkout")
def test_built_console_renders_the_shell(client_in):
    resp = client_in.get("/console/")
    assert resp.status_code == 200, (
        "the built console did not render — this is the 404 the whole change "
        "exists to fix."
    )
    body = resp.content.decode()
    assert 'id="app"' in body
    assert "unpkg.com" not in body
    assert "babel" not in body.lower()
    # Every manifest script must actually be referenced by the page.
    for name in json.loads(MANIFEST.read_text())["scripts"]:
        assert name in body, f"{name} is built but never loaded by the page"


@pytest.mark.skipif(not MANIFEST.is_file(),
                    reason="console not built in this checkout")
@pytest.mark.skipif(not (REPO / "design" / "app.jsx").is_file(),
                    reason="no design/ in this checkout (a built image has none)")
def test_sub_paths_still_reach_the_harness_in_a_dev_checkout(client_in):
    """Building the console must not take the harness away from developers.

    Only the console ROOT renders the built shell; any sub-path still falls
    through to design/. Other contract tests fetch /console/app.jsx to
    assert on component source, and those must keep working. In a built
    image design/ is absent and such a request 404s, which is correct —
    there is no JSX to serve there.
    """
    resp = client_in.get("/console/app.jsx")
    assert resp.status_code == 200, (
        "sub-path passthrough broke; the design harness is no longer "
        "reachable in a dev checkout."
    )
