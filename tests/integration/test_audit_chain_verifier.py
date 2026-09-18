"""The chain verifier must detect tampering, not report forks as tampering.

Before this, `verify_audit_chain` walked rows in `(occurred_at, id)` order
and flagged every row whose `prev_hash` did not match the previous row in
that ordering. The chain is not built in that order: `occurred_at` is
`auto_now_add`, set in Python before the INSERT, so under any concurrency
timestamp order and insert order differ.

On production that reported **840 breaks** for a chain with:

    82,359 rows recomputed — 0 content mismatches
    0 rows whose prev_hash matches no row (nothing deleted)
    0 duplicate self_hash
    1 genesis row
    23 fork points, all dated before the ADR-0029 fix, 0 since

A verifier that cries wolf on a healthy chain is worse than none: a real
break would be lost among hundreds of false ones, and the console showed
"✗ breaks found" permanently.

These tests pin the distinction. Postgres-only — the trigger that builds
the chain does not exist on SQLite.
"""

from __future__ import annotations

import pytest
from apps.security.integrity import verify_audit_chain
from apps.security.models import AuditEvent
from django.db import connection

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(connection.vendor != "postgresql",
                       reason="the chain trigger is Postgres-only"),
]


def _emit(action="read", entity_id="E1"):
    return AuditEvent.objects.create(
        actor_id="tester", actor_kind="user", action=action,
        entity_type="household", entity_id=entity_id, reason="chain test",
    )


def test_a_healthy_chain_verifies():
    for i in range(5):
        _emit(entity_id=f"E{i}")
    report = verify_audit_chain()
    assert report.ok, f"a freshly written chain did not verify: {report.breaks}"
    assert report.mode == "verified"
    assert report.rows_scanned >= 5


def test_altering_a_row_is_detected():
    """The property that matters: an edited row must fail verification.

    UPDATE is blocked by the append-only trigger, so tampering is
    simulated the way it would really happen — by going around Django and
    disabling the guard, as someone with database access could.
    """
    rows = [_emit(entity_id=f"T{i}") for i in range(3)]
    victim = rows[1]
    with connection.cursor() as cur:
        cur.execute("ALTER TABLE security_auditevent DISABLE TRIGGER security_auditevent_immutable_upd")
        try:
            cur.execute(
                "UPDATE security_auditevent SET reason = %s WHERE id = %s",
                ["tampered", victim.id],
            )
        finally:
            cur.execute("ALTER TABLE security_auditevent ENABLE TRIGGER security_auditevent_immutable_upd")

    report = verify_audit_chain()
    assert not report.ok, "an altered audit row was not detected"
    assert any(b.event_id == victim.id for b in report.breaks), (
        "the altered row was not named in the report"
    )


def test_deleting_a_row_is_detected():
    rows = [_emit(entity_id=f"D{i}") for i in range(3)]
    victim = rows[1]
    with connection.cursor() as cur:
        cur.execute("ALTER TABLE security_auditevent DISABLE TRIGGER security_auditevent_immutable_del")
        try:
            cur.execute("DELETE FROM security_auditevent WHERE id = %s", [victim.id])
        finally:
            cur.execute("ALTER TABLE security_auditevent ENABLE TRIGGER security_auditevent_immutable_del")

    report = verify_audit_chain()
    assert not report.ok, "a deleted audit row left the chain looking intact"


def test_a_fork_is_reported_separately_and_does_not_read_as_tampering():
    """Forks weaken the total-order claim but are not evidence of edits.

    23 of them exist on production, all predating the ADR-0029 fix and
    deliberately preserved. They must be visible and counted, without
    making every subsequent row look broken.
    """
    # Three rows: g is the genesis, a chains off g, b chains off a.
    # Re-pointing b at g makes g have two children — a real fork.
    g, a, b = _emit(entity_id="F0"), _emit(entity_id="F1"), _emit(entity_id="F2")
    with connection.cursor() as cur:
        cur.execute("ALTER TABLE security_auditevent DISABLE TRIGGER security_auditevent_immutable_upd")
        try:
            cur.execute(
                "UPDATE security_auditevent SET prev_hash = "
                "(SELECT self_hash FROM security_auditevent WHERE id = %s) WHERE id = %s",
                [g.id, b.id],
            )
        finally:
            cur.execute("ALTER TABLE security_auditevent ENABLE TRIGGER security_auditevent_immutable_upd")

    report = verify_audit_chain()
    assert report.forks, "the fork was not reported"
    # Editing prev_hash also changes what the row hashes to, so this row is
    # legitimately a content mismatch too; what must NOT happen is hundreds
    # of unrelated rows being reported.
    assert len(report.breaks) < 5, (
        f"one fork produced {len(report.breaks)} breaks — the verifier is "
        f"still reporting cascade failures from a single divergence."
    )
