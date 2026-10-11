"""The run: walk the collection, fetch each snapshot, file or hold.

The cursor discipline is the part worth reading. Spec step 5 says to
"persist the final cursor only after all records on that page have
been stored successfully", and that ordering is the whole difference
between a resumable pull and one that can skip a complaint. Saving the
cursor first and storing after means a crash between the two loses
every record on that page permanently — STAAC will not offer them
again, because from its side they were delivered.

So: store the page, then save the cursor. A crash re-reads a page this
registry has already stored, and `(handover_id, exchange_version)`
makes that re-read free.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from django.utils import timezone

from apps.security.audit import emit as emit_audit

from ..models import HandoverOutcome, StaacCredential
from .client import CursorRejected, StaacClient, StaacError
from .service import file_snapshot


@dataclass
class PullReport:
    """What a run did, in the terms an operator asks about."""

    listed: int = 0
    fetched: int = 0
    filed: int = 0
    held: int = 0
    already_held: int = 0
    pages: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    correlation_id: str = ""
    restarted_from_beginning: bool = False

    def summary(self) -> str:
        return (
            f"{self.pages} page(s), {self.listed} listed, "
            f"{self.fetched} fetched, {self.filed} filed, {self.held} held, "
            f"{self.already_held} already had"
        )


def credential_for(environment: str = "") -> StaacCredential:
    """The active credential, decrypted in exactly one place."""
    qs = StaacCredential.objects.filter(is_active=True)
    if environment:
        qs = qs.filter(environment=environment)
    credential = qs.order_by("environment").first()
    if credential is None:
        raise StaacError(
            "No active STAAC credential is configured. The IG issues one "
            "through STAAC's partner-access workspace; it is stored here "
            "encrypted, never in settings or the environment.",
        )
    return credential


def _token(credential: StaacCredential) -> str:
    from apps.security.encryption import decrypt

    raw = credential.token_encrypted
    if not raw:
        raise StaacError(
            f"The STAAC credential for {credential.environment!r} has no "
            "token stored.",
        )
    return decrypt(bytes(raw)).decode("utf-8")


def pull(
    *, environment: str = "", limit: int = 100, changed_since: str = "",
    restart: bool = False, actor: str = "staac-pull",
    client: StaacClient | None = None,
) -> PullReport:
    """Run one pull cycle.

    `client` is injectable so the whole cycle can be exercised against
    a mocked partner; in production it is built from the stored
    credential.
    """
    # The credential is resolved whether or not the client is
    # injected, because the cursor lives on it. Tying cursor state to
    # "did the caller supply a client" would mean the resumable path
    # is the one path never exercised by a test.
    credential: StaacCredential | None = None
    try:
        credential = credential_for(environment)
    except StaacError:
        if client is None:
            raise
    correlation = str(uuid.uuid4())
    if client is None:
        client = StaacClient(
            base_url=credential.base_url,
            token=_token(credential),
            correlation_id=correlation,
        )
    report = PullReport(correlation_id=client.correlation_id or correlation)

    cursor = "" if (restart or credential is None) else credential.cursor

    emit_audit(
        "read", "staac.pull", correlation, actor=actor, actor_kind="system",
        reason="partner handover pull started",
        field_changes={
            "environment": getattr(credential, "environment", "") or "injected",
            "resumed_from_cursor": bool(cursor),
            "changed_since": changed_since,
        },
    )

    try:
        report = _walk(
            client, report, cursor=cursor, limit=limit,
            changed_since=changed_since, credential=credential, actor=actor,
        )
    except CursorRejected as exc:
        # The cursor is signed by STAAC with no expiry, so the thing
        # that invalidates it is a key change on their side. Starting
        # again is correct and cheap — every record already stored is
        # recognised by its idempotency key and skipped.
        report.restarted_from_beginning = True
        report.warnings.append(f"{exc} — restarted from the beginning")
        if credential is not None:
            credential.cursor = ""
            credential.save(update_fields=["cursor", "updated_at"])
        report = _walk(
            client, report, cursor="", limit=limit,
            changed_since=changed_since, credential=credential, actor=actor,
        )

    if credential is not None:
        credential.last_pulled_at = timezone.now()
        credential.save(update_fields=["last_pulled_at", "updated_at"])

    emit_audit(
        "read", "staac.pull", correlation, actor=actor, actor_kind="system",
        reason=f"partner handover pull finished: {report.summary()}",
        field_changes={
            "listed": report.listed, "fetched": report.fetched,
            "filed": report.filed, "held": report.held,
            "pages": report.pages, "errors": len(report.errors),
        },
    )
    return report


def _walk(
    client: StaacClient, report: PullReport, *, cursor: str, limit: int,
    changed_since: str, credential: StaacCredential | None, actor: str,
) -> PullReport:
    for refs, next_cursor in client.iter_refs(
        cursor=cursor, limit=limit, changed_since=changed_since,
    ):
        report.pages += 1
        report.listed += len(refs)
        page_complete = True
        for ref in refs:
            try:
                _take(ref, client, report, actor=actor)
            except StaacError as exc:
                # One unreadable handover must not abandon the page's
                # cursor — but it must not let the cursor advance past
                # it either, or the record is skipped forever.
                page_complete = False
                report.errors.append(f"{ref.handover_id}: {exc}")

        # Cursor last, and only when the page is whole.
        if credential is not None and page_complete:
            credential.cursor = next_cursor
            credential.save(update_fields=["cursor", "updated_at"])
        if not page_complete:
            report.warnings.append(
                "A record on this page could not be stored, so the cursor "
                "was not advanced; the next run re-reads this page.",
            )
            break
    return report


def _take(ref, client: StaacClient, report: PullReport, *, actor: str) -> None:
    """Fetch and file one handover, counting what happened."""
    from ..models import StaacHandover

    if StaacHandover.objects.filter(
        handover_id=ref.handover_id, exchange_version=ref.exchange_version,
    ).exists():
        # Reconciliation re-lists what we already hold. Not fetched
        # again: re-reading a snapshot re-reads a complainant's
        # identity for nothing.
        report.already_held += 1
        return

    snapshot = client.fetch(ref.handover_id)
    report.fetched += 1
    result = file_snapshot(
        snapshot.body,
        handover_id=snapshot.handover_id,
        exchange_version=snapshot.exchange_version or ref.exchange_version,
        etag=snapshot.etag,
        correlation_id=snapshot.correlation_id,
        actor=actor,
    )
    report.warnings.extend(result.warnings)
    if result.handover.outcome == HandoverOutcome.FILED:
        report.filed += 1
    else:
        report.held += 1
