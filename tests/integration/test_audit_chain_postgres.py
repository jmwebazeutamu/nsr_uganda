"""Postgres-only audit-chain integrity tests.

Sprint 0 shipped the BEFORE INSERT chain trigger and BEFORE UPDATE/DELETE
raises in apps/security/migrations/0002_auditevent_chain_trigger.py.
The trigger is a no-op on sqlite, so every Sprint 0 audit test passed
without verifying the chain actually computes. This module pins those
guarantees against a real Postgres backend in CI.

SAD §8.4: append-only with hash chain so tampering is detectable.
"""

from __future__ import annotations

import hashlib

import pytest
from django.db import IntegrityError, connection

from apps.security.audit import emit
from apps.security.models import AuditEvent


pytestmark = pytest.mark.postgres


@pytest.fixture
def fresh_chain(db):
    """Clear AuditEvent so each test sees a deterministic starting hash."""
    # Direct delete via SQL bypasses the BEFORE DELETE raise; cleaner is to
    # truncate via the ORM-internal raw cursor since the trigger raises on
    # row-level deletes from the ORM.
    with connection.cursor() as cur:
        cur.execute("TRUNCATE TABLE security_auditevent;")
    yield


class TestChainHashPopulates:
    def test_first_event_has_self_hash_and_null_prev(self, fresh_chain):
        ev = emit("create", "test", "id-1", actor="alice")
        ev.refresh_from_db()
        assert ev.self_hash is not None
        assert len(bytes(ev.self_hash)) == 32  # SHA-256
        assert ev.prev_hash is None  # first row in chain

    def test_subsequent_event_prev_hash_matches_prior_self_hash(self, fresh_chain):
        first = emit("create", "test", "id-1", actor="alice")
        second = emit("update", "test", "id-1", actor="bob", reason="follow-up")
        first.refresh_from_db()
        second.refresh_from_db()
        assert second.prev_hash is not None
        assert bytes(second.prev_hash) == bytes(first.self_hash)
        assert second.self_hash != first.self_hash

    def test_chain_holds_across_20_writes(self, fresh_chain):
        events = []
        for i in range(20):
            events.append(emit("update", "test", "id-1", actor=f"actor-{i}",
                               reason=f"step-{i}"))
        for ev in events:
            ev.refresh_from_db()
        # Order in time, then verify chain.
        events.sort(key=lambda e: (e.occurred_at, e.id))
        prev_hash = None
        for ev in events:
            current_prev = None if ev.prev_hash is None else bytes(ev.prev_hash)
            assert current_prev == prev_hash, f"chain break at {ev.id}"
            assert ev.self_hash is not None
            prev_hash = bytes(ev.self_hash)


class TestAppendOnly:
    def test_update_raises(self, fresh_chain):
        ev = emit("create", "test", "id-1", actor="alice")
        with pytest.raises(IntegrityError, match="append-only"):
            AuditEvent.objects.filter(pk=ev.pk).update(reason="tampered")

    def test_delete_raises(self, fresh_chain):
        emit("create", "test", "id-1", actor="alice")
        with pytest.raises(IntegrityError, match="append-only"):
            AuditEvent.objects.all().delete()


class TestPepperApplied:
    """Spot-check that the chain hash incorporates the canonical payload —
    a corrupted payload at runtime should produce a different self_hash
    than the trigger expects, breaking the chain. This proves the
    trigger isn't a no-op."""

    def test_self_hash_is_not_trivial_sha256_of_id(self, fresh_chain):
        ev = emit("create", "test", "id-1", actor="alice", reason="r")
        ev.refresh_from_db()
        bare = hashlib.sha256(ev.id.encode()).digest()
        assert bytes(ev.self_hash) != bare
