"""Detail and compare views must not render specimen records.

A queue fixture shows the wrong count. A DETAIL view shows a whole
record — a head's name, a NIN, a GPS fix, a PMT band, a roster — which is
the shape an operator reads as "this is the household in front of me".
Three of them carried fabricated records:

  * DIH compare — a full household plus a five-member roster, and a 0.83
    duplicate match against a named household. A reviewer decides whether
    to PROMOTE a record into the registry from exactly that panel.
  * UPD detail — a complete change request with submitter, reviewer, SLA
    clock and a twelve-row diff including a PMT band shift.
  * change-request — a household context strip, a member roster, five
    prior decisions attributed to a named reviewer, and seeded evidence.

The change-request screen also had a live-fire hazard: its submit payload
read `household_id: householdId || HH.id`, and that fixture id EXISTS in
production. Submitting from a screen opened without a household would
have filed a change request against a real household the operator was
never looking at, and audited it as theirs.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
SCREENS = REPO / "design" / "v0.1" / "screens"

FILES = [
    "screens-dih.jsx",
    "screens-upd.jsx",
    "change-request/screens-change-request.jsx",
    "change-request/app-change-request.jsx",
]

# Identities and NIN-shaped strings from the design fixtures.
NAMES = ["Lokol Naume", "Akello Grace", "Okello Charles", "Onyango David",
         "Nakato Sarah", "Nsubuga Ruth", "Adong Florence", "Lokwang Peter",
         "Tumusiime Samuel"]
NIN = re.compile(r'"CM[0-9A-Z]{8,}"')


def _body(rel: str) -> str:
    src = (SCREENS / rel).read_text()
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"^\s*//.*$", "", src, flags=re.M)


@pytest.mark.parametrize("rel", FILES)
def test_no_fabricated_identities(rel):
    body = _body(rel)
    found = [n for n in NAMES if n in body] + NIN.findall(body)
    assert not found, (
        f"{rel} renders fabricated identities again: {sorted(set(found))}"
    )


@pytest.mark.parametrize("rel,fixture", [
    ("screens-upd.jsx", "UPD"),
    ("change-request/screens-change-request.jsx", "HH"),
    ("change-request/screens-change-request.jsx", "ROSTER"),
    ("change-request/screens-change-request.jsx", "HISTORY"),
    ("change-request/screens-change-request.jsx", "SEED_DOCS"),
])
def test_fixture_is_gone(rel, fixture):
    body = _body(rel)
    assert not re.search(rf"^const {fixture} = ", body, re.M), (
        f"{rel}: the {fixture} fixture is back."
    )


def test_change_request_cannot_submit_without_a_household():
    """The live-fire hazard: the fixture id exists in production."""
    body = _body("change-request/app-change-request.jsx")
    assert "householdId || HH.id" not in body, (
        "the submit payload falls back to the HH fixture id again. That id "
        "exists in production — a submit would file a change request "
        "against a real household the operator was not looking at."
    )
    assert "!!householdId" in body, (
        "canSubmit no longer requires a household, so a change request can "
        "be submitted with no household context."
    )
    assert "No household" in body, (
        "the operator is not told why they cannot submit."
    )


def test_change_request_history_comes_from_the_api():
    body = _body("change-request/app-change-request.jsx")
    assert "/api/v1/upd/change-requests/?entity_id=" in body, (
        "the change-history rail no longer reads real prior change requests."
    )


def test_upd_audit_drawer_shows_real_events():
    body = _body("screens-upd.jsx")
    assert "/api/v1/security/audit-events/?entity_id=" in body, (
        "the UPD audit drawer no longer reads the real audit chain."
    )
    assert "A-2026-" not in body, (
        "fabricated audit reference numbers are back in the UPD drawer."
    )
