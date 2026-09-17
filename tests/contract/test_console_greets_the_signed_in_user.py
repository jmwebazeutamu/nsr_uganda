"""The console must greet the user who is actually signed in.

A user signed in as `isaac` and the home screen said "Good afternoon,
Johnson" — `ROLE_CONTENT[role].person` is demo data baked into the design
harness, and `HomeScreen` used it directly instead of the session identity
the shell had already resolved from /api/v1/security/users/me/.

Showing one operator another operator's name on a registry of personal
data is not a cosmetic bug: it makes the active session ambiguous at a
glance, in a system where every read is audited against a named actor.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
APP = REPO / "design" / "app.jsx"
HOME = REPO / "design" / "v0.1" / "screens" / "screens-home.jsx"


def test_home_screen_receives_the_real_identity():
    src = APP.read_text()
    assert re.search(r"<HomeScreen[^>]*operatorName=\{identityName\}", src), (
        "app.jsx no longer passes the signed-in identity to HomeScreen, so "
        "the greeting falls back to ROLE_CONTENT demo data and every "
        "operator sees the same hardcoded name."
    )


def test_greeting_prefers_the_signed_in_user_over_demo_data():
    src = HOME.read_text()
    assert "operatorName || r.person" in src, (
        "the greeting must prefer the signed-in user; r.person is demo data "
        "and is only a harness fallback."
    )


def test_greeting_is_not_hardcoded_to_one_time_of_day():
    src = HOME.read_text()
    body = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    assert '"Good afternoon"' not in body.replace(
        'if (h < 17) return "Good afternoon";', ""
    ), "the greeting is hardcoded to a single time of day again"
    assert "_greeting()" in body, "the time-aware greeting helper is gone"


def test_no_real_person_is_hardcoded_into_the_greeting_path():
    """ROLE_CONTENT may keep demo names for the standalone harness, but the
    rendered greeting must not reach them when a session exists."""
    src = HOME.read_text()
    greeting_line = [ln for ln in src.splitlines() if "_greeting()" in ln and "title=" in ln]
    assert greeting_line, "greeting render line not found"
    assert "operatorName" in greeting_line[0], (
        "the rendered greeting does not consult the signed-in identity"
    )
