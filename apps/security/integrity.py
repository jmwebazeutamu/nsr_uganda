"""Audit chain integrity verifier (US-S16-004).

SAD §8.4 + ADR-0003 promise an append-only audit chain with
detectable tampering. The Postgres trigger in migration 0002 writes
the chain on every insert and refuses UPDATE/DELETE. This module
adds the *detection* half — a function that walks the chain in
time order and verifies each row's `prev_hash` matches the prior
row's `self_hash`.

`verify_audit_chain()` returns a `ChainReport` dataclass. The
companion Celery task in apps/security/tasks.py runs it on a
schedule and emits an AuditEvent with the result. On detected
breaks it ALSO writes a `chain_integrity_break` audit row so the
DPO anomaly feed surfaces it without polling a separate channel.

SQLite-friendly: when self_hash and prev_hash are all NULL (dev
backend has no trigger), the verifier returns `ok=True` with
`mode="no_chain"` rather than erroring. Production Postgres will
always have populated columns and runs the real check.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import AuditEvent


@dataclass
class ChainBreak:
    event_id: str
    expected_prev_hash: bytes | None
    actual_prev_hash: bytes | None
    occurred_at: str  # ISO string — easier to surface in audit reason


@dataclass
class ChainReport:
    ok: bool
    mode: str  # "verified" | "no_chain" | "empty"
    rows_scanned: int = 0
    breaks: list[ChainBreak] = field(default_factory=list)


def verify_audit_chain(*, limit: int | None = None) -> ChainReport:
    """Walk AuditEvent rows in (occurred_at, id) order and confirm
    each row's `prev_hash` equals the prior row's `self_hash`.

    `limit` is for incremental sweeps — pass None to scan the whole
    chain (the default; correct but expensive at scale). The Celery
    schedule passes None at off-peak hours; on-demand admin actions
    can pass a smaller limit.

    Returns a ChainReport. `mode="no_chain"` means the trigger isn't
    installed (SQLite dev). `mode="empty"` means no rows yet.
    `mode="verified"` is the production happy path.
    """
    qs = AuditEvent.objects.all().order_by("occurred_at", "id")
    if limit is not None:
        qs = qs[:limit]

    rows = list(qs)
    if not rows:
        return ChainReport(ok=True, mode="empty")

    # SQLite: trigger is a no-op, all hashes are NULL. The chain
    # check would trivially "pass" by NULL == NULL but that's a
    # false reassurance, so report it as no_chain to the caller.
    if all(r.self_hash is None and r.prev_hash is None for r in rows):
        return ChainReport(ok=True, mode="no_chain", rows_scanned=len(rows))

    breaks: list[ChainBreak] = []
    expected_prev: bytes | None = None
    for row in rows:
        actual_prev = bytes(row.prev_hash) if row.prev_hash is not None else None
        if actual_prev != expected_prev:
            breaks.append(ChainBreak(
                event_id=row.id,
                expected_prev_hash=expected_prev,
                actual_prev_hash=actual_prev,
                occurred_at=row.occurred_at.isoformat() if row.occurred_at else "",
            ))
        # Advance the expected pointer regardless — if the chain
        # already broke, we still want to surface every subsequent
        # mismatch (not just the first one).
        expected_prev = bytes(row.self_hash) if row.self_hash is not None else None

    return ChainReport(
        ok=not breaks, mode="verified",
        rows_scanned=len(rows), breaks=breaks,
    )
