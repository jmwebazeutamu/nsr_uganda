"""The audit-chain screen must never assert anything the server did not say.

It previously rendered ten fabricated audit events beneath KPIs claiming
412,890,221 events in the chain and a flat "Chain integrity ✓ verified".

The real chain holds ~81,800 events and does NOT verify — 816 broken
links. So the screen was not merely showing sample data; it was showing
the opposite of the truth, on the one control the registry's integrity
claim rests on (SAD §8.4), to the two people most likely to open it: an
auditor and the DPO.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

REPO = Path(__file__).resolve().parent.parent.parent
SCREEN = REPO / "design" / "v0.1" / "screens" / "screens-admin-security-audit.jsx"
LIST_URL = "/api/v1/security/audit-events/"
VERIFY_URL = "/api/v1/security/audit-events/verify-chain/"


def _body() -> str:
    src = SCREEN.read_text()
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"^\s*//.*$", "", src, flags=re.M)


@pytest.fixture
def auditor(db):
    user_model = get_user_model()
    user = user_model.objects.create_user("auditor-probe", password="not-a-real-password")
    user.is_superuser = user.is_staff = True
    user.save()
    return user


def test_the_fabricated_event_fixture_is_gone():
    body = _body()
    assert "AUD_EVENTS" not in body, (
        "the fabricated audit-event fixture is back on the audit screen."
    )


def test_the_invented_headline_numbers_are_gone():
    body = _body()
    for invented in ("412,890,221", "1,408,221", "16.3k/hour"):
        assert invented not in body, (
            f"{invented!r} is back — an invented figure on the audit screen."
        )


def test_chain_integrity_is_never_asserted_without_the_server():
    """The KPI must not read '✓ verified' unless verifyResult says so."""
    body = _body()
    assert 'value="✓ verified"' not in body, (
        "the chain-integrity KPI hardcodes '✓ verified' again. The chain "
        "currently has breaks; this claim would be false as well as invented."
    )
    assert "verifyResult ? (verifyResult.ok" in body, (
        "chain integrity must be driven by the server's verification result."
    )


def test_screen_reads_the_live_endpoints():
    body = _body()
    assert LIST_URL in body, "the audit screen no longer fetches real events"
    assert VERIFY_URL in body, "the audit screen no longer calls verify-chain"


def test_no_preview_fallback_on_verification():
    body = _body()
    assert 'mode: "preview"' not in body, (
        "verifyChain falls back to a fabricated 'ok' result again."
    )


def test_failure_is_shown_not_hidden():
    body = _body()
    assert "loadError" in body and "Could not load audit events" in body, (
        "a failed fetch must be visible; an empty table makes an outage look "
        "like a quiet audit log."
    )


@pytest.mark.django_db
def test_the_list_endpoint_the_screen_uses_actually_answers(auditor):
    client = Client()
    client.force_login(auditor)
    response = client.get(f"{LIST_URL}?ordering=-occurred_at&page_size=5")
    assert response.status_code == 200
    payload = response.json()
    results = payload["results"] if isinstance(payload, dict) else payload
    if results:
        # The projector reads these names; a rename would empty the table.
        for field in ("id", "occurred_at", "actor_id", "actor_kind", "action",
                      "entity_type", "entity_id", "ip_address", "self_hash"):
            assert field in results[0], (
                f"the audit serializer no longer returns {field!r}, which the "
                f"screen's projector reads."
            )


@pytest.mark.django_db
def test_verify_chain_endpoint_answers_and_reports_honestly(auditor):
    client = Client()
    client.force_login(auditor)
    response = client.post(VERIFY_URL, data="{}", content_type="application/json")
    assert response.status_code == 200
    payload = response.json()
    assert "ok" in payload and "rows_scanned" in payload and "breaks" in payload, (
        "verify-chain no longer returns the shape the screen renders."
    )
