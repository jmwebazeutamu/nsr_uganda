"""IDV NIRA queue + retry orchestration.

queue_verification(nin) attempts a live verify_nin call; on success it
records SUCCEEDED with the result payload, on NiraError it records
QUEUED with a next_retry_at scheduled per the backoff table. Callers
never see NiraError — they get back the NiraVerificationAttempt row.

drain_queue() picks up QUEUED rows whose next_retry_at has lapsed,
retries each, and updates state. Designed to run from cron / systemd
timer or Celery beat (when the latter is wired). Idempotent.

Backoff schedule (per attempt count, in seconds):
    1 -> 60        (first retry one minute later)
    2 -> 300       (then five minutes)
    3 -> 3600      (then one hour)
    4 -> 86400     (then 24 hours)
    5 -> FAILED    (max attempts exhausted)

Why exponential: NIRA outages observed in pilot lasted between minutes
and hours; backing off this way clears the queue inside a day for
typical outages without hammering NIRA when it's already struggling.
"""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.security.audit import emit as emit_audit
from apps.security.hashing import nin_hash as compute_nin_hash

from .client import get_nira_client
from .mock import NiraError
from .models import AttemptStatus, NiraVerificationAttempt

# Backoff per attempt index (0-based: BACKOFF[0] is the wait after the
# initial failed attempt). MAX_ATTEMPTS is the hard ceiling.
BACKOFF_SECONDS: tuple[int, ...] = (60, 300, 3600, 86400)
MAX_ATTEMPTS = len(BACKOFF_SECONDS) + 1  # 5


def _next_retry_for(attempts: int) -> timedelta:
    """Lookup the wait time after `attempts` failed calls.

    attempts=1 -> BACKOFF_SECONDS[0] (wait after first failure).
    attempts >= MAX_ATTEMPTS -> raises IndexError; caller marks FAILED.
    """
    return timedelta(seconds=BACKOFF_SECONDS[attempts - 1])


@transaction.atomic
def queue_verification(
    nin: str, *, requester: str = "system",
) -> NiraVerificationAttempt:
    """Try verify_nin once; persist the outcome as an attempt row.

    Returns the row in either SUCCEEDED (call worked) or QUEUED (call
    raised NiraError; will retry) state. The raw NIN is NEVER stored —
    only its hash. Demographics from a successful call land in
    `result_payload`.
    """
    client = get_nira_client()
    now = timezone.now()
    attempt = NiraVerificationAttempt(
        nin_hash=compute_nin_hash(nin),
        requester=requester,
        attempts=1,
        next_retry_at=now,  # placeholder; reset below on outcome
    )
    try:
        result = client.verify_nin(nin)
    except NiraError as e:
        attempt.status = AttemptStatus.QUEUED
        attempt.last_error = str(e)[:256]
        attempt.next_retry_at = now + _next_retry_for(1)
        attempt.save()
        emit_audit(
            "queue", "nira_attempt", attempt.id, actor=requester,
            reason="nira_unavailable",
        )
        return attempt

    attempt.status = AttemptStatus.SUCCEEDED
    attempt.result_payload = result
    attempt.completed_at = now
    attempt.save()
    emit_audit(
        "succeed", "nira_attempt", attempt.id, actor=requester,
        reason="first_call",
    )
    return attempt


def drain_queue(resolve_nin) -> dict[str, int]:
    """Iterate every QUEUED attempt whose next_retry_at has lapsed,
    and call _retry_one(). `resolve_nin(nin_hash) -> str | None` is
    supplied by the caller (management command, Celery task) and
    returns the raw NIN matching the hash, or None when no Member
    carries it any more (e.g., the member was merged + soft-deleted
    after the request was queued; in that case the attempt is marked
    FAILED so it stops cycling).

    Returns counts {processed, succeeded, requeued, failed, unresolved}.
    Idempotent: leaves SUCCEEDED / FAILED rows untouched.
    """
    now = timezone.now()
    pending = NiraVerificationAttempt.objects.filter(
        status=AttemptStatus.QUEUED, next_retry_at__lte=now,
    ).order_by("next_retry_at")

    counts = {"processed": 0, "succeeded": 0, "requeued": 0,
              "failed": 0, "unresolved": 0}
    for attempt in pending:
        nin = resolve_nin(bytes(attempt.nin_hash))
        if nin is None:
            attempt.status = AttemptStatus.FAILED
            attempt.completed_at = now
            attempt.last_error = "NIN no longer resolvable (member merged?)"
            attempt.save(update_fields=[
                "status", "completed_at", "last_error", "updated_at",
            ])
            emit_audit(
                "fail", "nira_attempt", attempt.id, actor="drain-bot",
                reason="nin_unresolved",
            )
            counts["unresolved"] += 1
            counts["processed"] += 1
            continue
        _retry_one(attempt, nin)
        attempt.refresh_from_db()
        counts["processed"] += 1
        if attempt.status == AttemptStatus.SUCCEEDED:
            counts["succeeded"] += 1
        elif attempt.status == AttemptStatus.FAILED:
            counts["failed"] += 1
        else:
            counts["requeued"] += 1
    return counts


@transaction.atomic
def _retry_one(attempt: NiraVerificationAttempt, nin: str) -> NiraVerificationAttempt:
    """Call verify_nin once for an existing QUEUED attempt; update state.

    The raw NIN is passed in by the caller — drain_queue resolves it
    via the upstream callback wired by the queue's owner (today we
    accept it as a parameter; production wires a Member.nin_hash ->
    decryption lookup, behind an explicit privilege gate).
    """
    client = get_nira_client()
    now = timezone.now()
    attempt.attempts += 1
    try:
        result = client.verify_nin(nin)
    except NiraError as e:
        attempt.last_error = str(e)[:256]
        if attempt.attempts >= MAX_ATTEMPTS:
            attempt.status = AttemptStatus.FAILED
            attempt.completed_at = now
            attempt.next_retry_at = now  # column non-null
            attempt.save()
            emit_audit(
                "fail", "nira_attempt", attempt.id, actor="drain-bot",
                reason=f"exhausted after {attempt.attempts} attempts",
            )
            return attempt
        attempt.status = AttemptStatus.QUEUED
        attempt.next_retry_at = now + _next_retry_for(attempt.attempts)
        attempt.save()
        emit_audit(
            "retry_queued", "nira_attempt", attempt.id, actor="drain-bot",
            reason=f"attempt {attempt.attempts} failed",
        )
        return attempt

    attempt.status = AttemptStatus.SUCCEEDED
    attempt.result_payload = result
    attempt.completed_at = now
    attempt.save()
    emit_audit(
        "succeed", "nira_attempt", attempt.id, actor="drain-bot",
        reason=f"retry {attempt.attempts}",
    )
    return attempt
