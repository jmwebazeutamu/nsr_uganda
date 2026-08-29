"""The audit chain must not fork under concurrent writes (F6).

The trigger reads the current tail and links to it. Two transactions inserting
at the same moment both read the same tail before either commits, so both link
to it — the chain forks, one branch becomes unreachable from the head, and
nothing raises.

This is a real-concurrency test: separate threads, separate connections,
committed rows. A single-threaded test cannot reproduce the defect, which is
exactly why it survived 73k rows unnoticed.
"""

import threading

import pytest
from apps.security.audit import emit
from apps.security.models import AuditEvent
from django.db import connections

pytestmark = pytest.mark.postgres

WRITERS = 8
PER_WRITER = 6


def _write_events(n, tag, errors):
    """Each thread gets its own connection, as a separate request would."""
    try:
        for i in range(n):
            emit("read", "concurrency-probe", f"{tag}-{i}",
                 actor=f"writer-{tag}", reason=f"i={i}")
    except Exception as exc:  # noqa: BLE001 — surfaced by the assertion below
        errors.append(exc)
    finally:
        connections.close_all()


def _chain_shape():
    """Structural check: a sound chain is ONE linked list.

    Counting is not enough — a forked chain still has the right number of rows.
    """
    rows = list(AuditEvent.objects.values_list("id", "prev_hash", "self_hash"))
    total = len(rows)
    heads = sum(1 for _, prev, _ in rows if prev is None)
    prevs = [bytes(p) for _, p, _ in rows if p is not None]
    selfs = {bytes(s) for _, _, s in rows if s is not None}
    forks = len(prevs) - len(set(prevs))
    dangling = sum(1 for p in prevs if p not in selfs)
    return {"total": total, "heads": heads, "forks": forks,
            "dangling": dangling, "distinct_self": len(selfs)}


@pytest.mark.django_db(transaction=True)
def test_concurrent_writers_do_not_fork_the_chain():
    AuditEvent.objects.all().delete()  # empty table: DELETE fires no row trigger

    errors: list[Exception] = []
    threads = [
        threading.Thread(target=_write_events, args=(PER_WRITER, str(t), errors))
        for t in range(WRITERS)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert not errors, f"writer thread raised: {errors[:3]}"

    shape = _chain_shape()
    assert shape["total"] == WRITERS * PER_WRITER

    # The property under test. Without the advisory lock in the trigger this
    # reports several forks; with it, none.
    assert shape["forks"] == 0, (
        f"the chain forked under {WRITERS} concurrent writers: {shape}. "
        "Two transactions read the same tail before either committed."
    )
    assert shape["heads"] == 1, f"expected exactly one head, got {shape}"
    assert shape["dangling"] == 0, f"unreachable prev_hash values: {shape}"
    assert shape["distinct_self"] == shape["total"], (
        f"duplicate self_hash values: {shape}"
    )


@pytest.mark.django_db(transaction=True)
def test_the_chain_is_walkable_end_to_end():
    """Every row reachable by following prev_hash from the head.

    This is the claim a forked chain quietly loses: an auditor walking forward
    still finds the right number of rows in the table, but not all of them in
    the chain.
    """
    AuditEvent.objects.all().delete()

    errors: list[Exception] = []
    threads = [
        threading.Thread(target=_write_events, args=(4, f"w{t}", errors))
        for t in range(6)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not errors

    rows = list(AuditEvent.objects.values_list("prev_hash", "self_hash"))
    by_prev = {}
    head = None
    for prev, own in rows:
        key = bytes(prev) if prev is not None else None
        if key is None:
            head = bytes(own)
        else:
            by_prev[key] = bytes(own)

    assert head is not None, "no head row"
    walked, cursor = 1, head
    while cursor in by_prev:
        cursor = by_prev[cursor]
        walked += 1

    assert walked == len(rows), (
        f"walked {walked} of {len(rows)} rows — the rest are unreachable from "
        "the head, which is what forking costs"
    )
