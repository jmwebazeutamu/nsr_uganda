"""Audit chain integrity verifier (US-S16-004).

SAD §8.4 + ADR-0003 promise an append-only audit chain with detectable
tampering. The Postgres trigger (migration 0002, hardened by 0009 per
ADR-0029) writes the chain on every insert and refuses UPDATE/DELETE.
This module is the *detection* half.

What it checks, and why it changed
----------------------------------
The original verifier walked rows in `(occurred_at, id)` order and
flagged any row whose `prev_hash` did not equal the previous row's
`self_hash`. **The chain is not built in that order.** `occurred_at` is
`auto_now_add` — set in Python before the INSERT — so under any
concurrency, timestamp order and insert order differ. The trigger chains
by insert order; the verifier read by timestamp order.

On production that reported **840 breaks** against a chain that was
demonstrably intact:

    82,359 rows recomputed          -> 0 content mismatches
    rows whose prev_hash is unknown -> 0   (nothing deleted)
    duplicate self_hash values      -> 0
    genesis rows                    -> 1
    fork points                     -> 23, all dated before the
                                       ADR-0029 fix; 0 in the 8,426
                                       rows written since

A verifier that cries wolf is worse than none: a real break would be
lost among hundreds of false ones, and the console reported "breaks
found" permanently, which is how a genuine one would have been ignored.

So it now checks the two properties the chain actually guarantees:

1. **Content integrity** — recompute every row's `self_hash` from its own
   payload and its own stored `prev_hash`, using the trigger's formula.
   A mismatch means the row was edited after insert. This is the tamper
   test, and it is order-independent.
2. **Link integrity** — every non-null `prev_hash` must resolve to a real
   row's `self_hash`. A dangling link means a row was deleted.

**Forks** — two rows sharing a `prev_hash` — are reported separately in
`forks`. They weaken the *total-order* claim (an auditor walking forward
from the head will not reach every row) but they are not evidence of
editing, and the 23 on production are documented and deliberately
preserved (see docs/audit/2026-08-10_audit_chain_concurrency.md). They
are surfaced, counted, and do not turn every later row into a break.

SQLite-friendly: with no trigger the hash columns stay NULL and the
verifier returns `ok=True, mode="no_chain"` rather than falsely
reassuring.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.db import connection

from .models import AuditEvent

#: The trigger's payload expression, kept byte-identical to
#: migrations/0002_auditevent_chain_trigger.py. Recomputing in SQL rather
#: than Python is deliberate: reproducing Postgres' rendering of
#: timestamptz and jsonb in Python is a source of false mismatches, and a
#: false mismatch on this particular check would read as tampering.
_PAYLOAD_SQL = """
    concat_ws('|', id, occurred_at::text, actor_id, actor_kind, action,
              entity_type, entity_id, coalesce(field_changes::text, ''),
              coalesce(reason, ''), coalesce(host(ip_address), ''),
              coalesce(user_agent, ''))
"""

_CONTENT_CHECK_SQL = f"""
SELECT id, occurred_at
  FROM security_auditevent
 WHERE self_hash IS DISTINCT FROM digest(
         coalesce(prev_hash, ''::bytea) || convert_to({_PAYLOAD_SQL}, 'UTF8'),
         'sha256')
 ORDER BY occurred_at, id
"""

_DANGLING_SQL = """
SELECT e.id, e.occurred_at, e.prev_hash
  FROM security_auditevent e
 WHERE e.prev_hash IS NOT NULL
   AND NOT EXISTS (
        SELECT 1 FROM security_auditevent p WHERE p.self_hash = e.prev_hash)
 ORDER BY e.occurred_at, e.id
"""

_FORKS_SQL = """
SELECT prev_hash, count(*) AS n, min(occurred_at) AS first_seen
  FROM security_auditevent
 WHERE prev_hash IS NOT NULL
 GROUP BY prev_hash
HAVING count(*) > 1
 ORDER BY first_seen
"""


@dataclass
class ChainBreak:
    """A row that fails tamper detection: edited content, or a link to a
    row that no longer exists."""
    event_id: str
    expected_prev_hash: bytes | None
    actual_prev_hash: bytes | None
    occurred_at: str  # ISO string — easier to surface in audit reason
    kind: str = "content"  # "content" | "dangling"


@dataclass
class ChainFork:
    """Two or more rows sharing a prev_hash. Not tampering — see the
    module docstring and ADR-0029."""
    prev_hash: bytes | None
    children: int
    first_seen: str


@dataclass
class ChainReport:
    ok: bool
    mode: str  # "verified" | "no_chain" | "empty"
    rows_scanned: int = 0
    breaks: list[ChainBreak] = field(default_factory=list)
    forks: list[ChainFork] = field(default_factory=list)


def _iso(value) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value or "")


def verify_audit_chain(*, limit: int | None = None) -> ChainReport:
    """Verify the audit chain's content and links.

    `ok` is True when no row has been edited and no row's predecessor has
    been deleted. Forks are reported in `forks` and do NOT set `ok=False`:
    they weaken the total-order claim but are not evidence of tampering,
    and the ones on production predate the ADR-0029 fix.

    `limit` caps how many rows are scanned, newest first, for an
    on-demand check; None (the default) scans everything.
    """
    total = AuditEvent.objects.count()
    if not total:
        return ChainReport(ok=True, mode="empty")

    # No trigger (SQLite dev) — every hash is NULL. Saying "verified"
    # here would be a false reassurance.
    if not AuditEvent.objects.exclude(self_hash=None).exists():
        return ChainReport(ok=True, mode="no_chain", rows_scanned=total)

    if connection.vendor != "postgresql":
        return ChainReport(ok=True, mode="no_chain", rows_scanned=total)

    breaks: list[ChainBreak] = []
    forks: list[ChainFork] = []
    scanned = total

    with connection.cursor() as cur:
        content_sql = _CONTENT_CHECK_SQL
        if limit is not None:
            content_sql += " LIMIT %s"
            cur.execute(content_sql, [limit])
        else:
            cur.execute(content_sql)
        for row_id, occurred in cur.fetchall():
            breaks.append(ChainBreak(
                event_id=row_id, expected_prev_hash=None, actual_prev_hash=None,
                occurred_at=_iso(occurred), kind="content",
            ))

        cur.execute(_DANGLING_SQL)
        for row_id, occurred, prev in cur.fetchall():
            breaks.append(ChainBreak(
                event_id=row_id, expected_prev_hash=None,
                actual_prev_hash=bytes(prev) if prev is not None else None,
                occurred_at=_iso(occurred), kind="dangling",
            ))

        cur.execute(_FORKS_SQL)
        for prev, n, first_seen in cur.fetchall():
            forks.append(ChainFork(
                prev_hash=bytes(prev) if prev is not None else None,
                children=n, first_seen=_iso(first_seen),
            ))

    return ChainReport(
        ok=not breaks, mode="verified",
        rows_scanned=scanned, breaks=breaks, forks=forks,
    )
