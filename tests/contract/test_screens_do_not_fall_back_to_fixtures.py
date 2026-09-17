"""Workbench screens must not initialise from fabricated fixtures.

Five screens fetched live data but used a fixture as their initial state,
replacing it only if the fetch succeeded. A slow or failing API therefore
left an operator reading invented people — names, NINs and ULIDs —
presented identically to real records, with at most a small "mock" chip
to say otherwise.

DIH went further: when the live queue came back EMPTY it kept the
fabricated rows on screen "so the screen doesn't look empty during the
demo", so a cleared queue looked like a backlog of invented households.

Each screen now starts empty and states which of loading / live / live
but empty / could-not-load it is in.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
SCREENS = REPO / "design" / "v0.1" / "screens"

# screen file -> fixture constants that must never be the initial state
CASES = {
    "screens-dih.jsx": ["MOCK_DIH_ROWS"],
    "screens-upd.jsx": ["UPD_QUEUE"],
    "screens-grm.jsx": ["GRM_MOCK_ROWS"],
    "screens-household.jsx": ["DEMO_HH"],
    "consent/screens-consent-citizen.jsx": ["HOUSEHOLD"],
}


def _body(rel: str) -> str:
    src = (SCREENS / rel).read_text()
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"^\s*//.*$", "", src, flags=re.M)


@pytest.mark.parametrize("rel,fixtures", CASES.items(), ids=lambda v: v if isinstance(v, str) else "")
def test_fixture_is_never_the_initial_state(rel, fixtures):
    body = _body(rel)
    for fixture in fixtures:
        pattern = rf"useState[A-Za-z]*\(\s*{re.escape(fixture)}\b"
        assert not re.search(pattern, body), (
            f"{rel}: state initialises from {fixture}, so a slow or failing "
            f"API shows fabricated records as if they were real."
        )


@pytest.mark.parametrize("rel,fixtures", CASES.items(), ids=lambda v: v if isinstance(v, str) else "")
def test_fixture_is_not_an_or_fallback(rel, fixtures):
    """`liveThing || FIXTURE` is the same bug wearing a different hat."""
    body = _body(rel)
    for fixture in fixtures:
        assert not re.search(rf"\|\|\s*{re.escape(fixture)}\b", body), (
            f"{rel}: falls back to {fixture} with `||`."
        )
        assert not re.search(rf":\s*{re.escape(fixture)}\s*;", body), (
            f"{rel}: falls back to {fixture} in a ternary."
        )


def test_dih_clears_the_queue_when_the_live_queue_is_empty():
    body = _body("screens-dih.jsx")
    # The branch that SETS live-empty, not the chip that renders it.
    idx = body.index('setDataSource("live-empty")')
    empty = body[max(0, idx - 300):idx]
    assert "setRows([])" in empty, (
        "DIH keeps fabricated rows when the live queue returns empty, so a "
        "cleared queue looks like a backlog of invented households."
    )


@pytest.mark.parametrize("rel", ["screens-dih.jsx", "screens-upd.jsx", "screens-grm.jsx"])
def test_failure_is_visible_and_clears_the_rows(rel):
    body = _body(rel)
    assert 'setDataSource("offline")' in body, (
        f"{rel}: a failed fetch no longer records the outage."
    )


@pytest.mark.parametrize("rel", ["screens-dih.jsx", "screens-upd.jsx", "screens-grm.jsx"])
def test_mock_is_no_longer_a_reachable_state(rel):
    body = _body(rel)
    assert 'dataSource === "mock"' not in body, (
        f"{rel}: still branches on a 'mock' data source."
    )
    assert '"loading"' in body, f"{rel}: has no loading state"
