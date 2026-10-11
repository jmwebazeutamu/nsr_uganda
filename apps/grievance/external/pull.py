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
from . import CONNECTOR_NAME, PULL_ACTOR, SOURCE_CODE
from .client import (
    DEFAULT_PAGE_SIZE,
    CursorRejected,
    StaacClient,
    StaacError,
)
from .service import file_snapshot


def connector_for_staac():
    """The registered connector this pull runs under.

    Its existence is what makes `start_connector_run` enforce
    AC-DIH-DPA-REQUIRED on a partner's personal data, and what gives
    the run a queryable record instead of a line of stdout.
    """
    from apps.ingestion_hub.models import Connector

    connector = Connector.objects.filter(
        source_system__code=SOURCE_CODE, name=CONNECTOR_NAME, is_active=True,
    ).select_related("source_system").first()
    if connector is None:
        raise StaacError(
            f"No active connector {CONNECTOR_NAME!r} for source "
            f"{SOURCE_CODE!r}. Migration grievance.0017 registers it.",
        )
    return connector


@dataclass
class PullReport:
    """What a run did, in the terms an operator asks about.

    The durable record is the `ConnectorRun` this carries; these
    fields are the same counts in the vocabulary of the command's own
    output, so an operator reads "filed" rather than "promoted".
    """

    run_id: str = ""
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
    found = list(qs.order_by("environment")[:5])
    if not found:
        raise StaacError(
            "No active STAAC credential is configured. The IG issues one "
            "through STAAC's partner-access workspace; it is stored here "
            "encrypted, never in settings or the environment.",
        )
    if len(found) > 1:
        # Picking one would pick it alphabetically, and "production"
        # sorts before "sandbox": an operator testing without the flag
        # would have reached production. Naming the environment is one
        # word; guessing it is a live partner call nobody asked for.
        names = ", ".join(c.environment for c in found)
        raise StaacError(
            f"More than one active STAAC credential ({names}). Name the "
            "one to use with --environment rather than letting the "
            "command choose.",
        )
    return found[0]


def _token(credential: StaacCredential) -> str:
    """The bearer token, as plaintext.

    `EncryptedBinaryField` is the seam: its contract is "writes accept
    plaintext, reads return plaintext, the column holds ciphertext",
    so there is nothing to decrypt here. This function used to call
    `decrypt()` on a value the field had already decrypted, and the
    admin form compensated by encrypting before assigning. The pair
    worked only together: any writer following the documented
    contract — a fixture, a data migration, a shell create — produced
    a credential that raised `InvalidToken`, which is not a
    `StaacError` and so escaped the command's handler as a traceback.
    It would also have survived the NSR-O-04 KMS swap un-decryptable,
    being the one column wrapped twice.

    `ingestion_hub.connection_test.credentials_for()` does the same
    thing the same way; this is the second caller of one convention,
    not a second convention.
    """
    raw = credential.token_encrypted
    if not raw:
        raise StaacError(
            f"The STAAC credential for {credential.environment!r} has no "
            "token stored.",
        )
    return bytes(raw).decode("utf-8")


def pull(
    *, environment: str = "", limit: int = DEFAULT_PAGE_SIZE,
    changed_since: str = "",
    restart: bool = False, actor: str = PULL_ACTOR,
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

    # AC-DIH-DPA-REQUIRED, reached through the registry's own gate
    # rather than restated: no agreement covering this source, no run,
    # and therefore no personal data received.
    from apps.ingestion_hub.services import DihError, start_connector_run

    connector = connector_for_staac()
    try:
        run = start_connector_run(connector, actor=actor)
    except DihError as exc:
        raise StaacError(
            f"{exc}. A partner's grievances carry complainant identity, so "
            "the agreement authorising receipt has to be recorded here "
            "before the first call — not taken from the snapshot.",
        ) from exc
    report.run_id = run.id

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
            client, report, run=run, cursor=cursor, limit=limit,
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
            client, report, run=run, cursor="", limit=limit,
            changed_since=changed_since, credential=credential, actor=actor,
        )

    _close_run(run, report)

    if credential is not None and not report.errors:
        # Only a clean run sets it. Stamping it regardless would show
        # an operator a fresh "last pulled" for a run that imported
        # nothing, which is the reassuring kind of wrong.
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


def _close_run(run, report: PullReport) -> None:
    """Write the run's counters, in ConnectorRun's own vocabulary.

    `records_received` is what the collection listed, `records_landed`
    what was fetched and stored, `records_promoted` what became a
    grievance, `records_quarantined` what is held awaiting
    configuration, `records_rejected` what could not be read at all.
    A second counters table would have been a second answer to "did
    last night's run work".
    """
    from django.db.models import F

    from apps.ingestion_hub.models import ConnectorRun, ConnectorRunStatus

    ConnectorRun.objects.filter(pk=run.pk).update(
        status=(
            ConnectorRunStatus.FAILED if report.errors
            else ConnectorRunStatus.SUCCEEDED
        ),
        finished_at=timezone.now(),
        note=report.summary()[:500],
        records_promoted=F("records_promoted") + report.filed,
        records_quarantined=F("records_quarantined") + report.held,
        records_rejected=F("records_rejected") + len(report.errors),
    )


def _walk(
    client: StaacClient, report: PullReport, *, run, cursor: str, limit: int,
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
                _take(ref, client, report, run=run, actor=actor)
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


def _take(
    ref, client: StaacClient, report: PullReport, *, run, actor: str,
) -> None:
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
        run=run,
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


@dataclass
class DryRunRow:
    """One handover, and what a real pull would do with it."""

    handover_id: str = ""
    tracking_number: str = ""
    staac_category: str = ""
    parish_key: str = ""
    verdict: str = ""          # "file", "hold", or "already held"
    nsr_category: str = ""
    held_reason: str = ""
    held_source_code: str = ""
    detail: str = ""
    warnings: tuple = ()


@dataclass
class DryRunReport:
    """What a pull would do, having done none of it."""

    listed: int = 0
    examined: int = 0
    would_file: int = 0
    would_hold: int = 0
    already_held: int = 0
    rows: list = field(default_factory=list)
    blockers: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"{self.listed} listed, {self.examined} examined, "
            f"{self.would_file} would file, {self.would_hold} would be "
            f"held, {self.already_held} already held"
        )


def test_connection(
    *, environment: str = "", client: StaacClient | None = None,
) -> "ConnectionTestResult":
    """Can we reach STAAC, and does the credential work?

    Returns DIH's own `ConnectionTestResult` rather than a shape of
    its own: the console already renders that for the Kobo connector,
    and a second result type would be a second thing to render.

    Reads one row and files nothing. The agreement is NOT required —
    a connection test that refuses to run until the paperwork is in
    order cannot tell you whether the paperwork is the problem.
    """
    import time

    from apps.ingestion_hub.connectors.base import ConnectionTestResult

    started = time.monotonic()
    try:
        if client is None:
            credential = credential_for(environment)
            client = StaacClient(
                base_url=credential.base_url, token=_token(credential),
            )
        refs, _cursor = client.list_page(limit=1)
    except StaacError as exc:
        return ConnectionTestResult(
            ok=False,
            latency_ms=int((time.monotonic() - started) * 1000),
            error=str(exc),
        )
    return ConnectionTestResult(
        ok=True,
        latency_ms=int((time.monotonic() - started) * 1000),
        server_version=f"{len(refs)} handover(s) on the first page",
    )


def dry_run(
    *, environment: str = "", limit: int = DEFAULT_PAGE_SIZE,
    client: StaacClient | None = None, max_records: int = 50,
) -> DryRunReport:
    """Walk the collection and report what a real pull would do.

    Writes nothing — no ConnectorRun, no landing, no grievance, not
    even a cursor — which is why it deliberately does NOT require an
    agreement to be in force. A dry run whose first act is to refuse
    for want of configuration cannot tell an operator which
    configuration is missing. Instead every blocker it meets is
    reported, so one run answers "what do I still have to set up".

    Each snapshot is judged by `service.assess`, the same function the
    real filing uses, so the preview cannot promise something the run
    will not do.
    """
    from .service import assess

    report = DryRunReport()
    if client is None:
        credential = credential_for(environment)
        client = StaacClient(
            base_url=credential.base_url, token=_token(credential),
        )

    # Configuration problems a record-by-record view would repeat
    # once per record, said once instead.
    for blocker in configuration_blockers():
        report.blockers.append(blocker)

    from ..models import StaacHandover

    try:
        for refs, _next_cursor in client.iter_refs(limit=limit):
            report.listed += len(refs)
            for ref in refs:
                if report.examined >= max_records:
                    continue
                if StaacHandover.objects.filter(
                    handover_id=ref.handover_id,
                    exchange_version=ref.exchange_version,
                ).exists():
                    report.already_held += 1
                    report.rows.append(DryRunRow(
                        handover_id=ref.handover_id,
                        tracking_number=ref.tracking_number,
                        verdict="already held",
                    ))
                    continue
                try:
                    snapshot = client.fetch(ref.handover_id)
                except StaacError as exc:
                    report.errors.append(f"{ref.handover_id}: {exc}")
                    continue
                report.examined += 1
                verdict = assess(snapshot.body)
                row = DryRunRow(
                    handover_id=ref.handover_id,
                    tracking_number=verdict.tracking_number
                    or ref.tracking_number,
                    staac_category=verdict.staac_category,
                    parish_key=verdict.parish_key,
                    verdict="file" if verdict.will_file else "hold",
                    nsr_category=verdict.nsr_category,
                    held_reason=verdict.held_reason,
                    held_source_code=verdict.held_source_code,
                    detail=verdict.detail,
                    warnings=verdict.warnings,
                )
                report.rows.append(row)
                if verdict.will_file:
                    report.would_file += 1
                else:
                    report.would_hold += 1
    except StaacError as exc:
        report.errors.append(str(exc))
    return report


def configuration_blockers() -> list[str]:
    """Everything standing between this registry and a working pull.

    Answered without calling STAAC, so it is also what a settings
    screen shows before anyone presses anything.
    """
    from datetime import date

    from django.db.models import Q

    from apps.ingestion_hub.models import DataProvisionAgreement
    from apps.reference_data.models import ChoiceOption

    from ..intake import STAAC_CATEGORY_LIST
    from ..models import StaacCredential

    out: list[str] = []
    if not StaacCredential.objects.filter(is_active=True).exists():
        out.append(
            "No active credential. The IG issues one through STAAC's "
            "partner-access workspace; store it here, never in settings.",
        )
    today = date.today()
    if not DataProvisionAgreement.objects.filter(
        source_system__code=SOURCE_CODE, valid_from__lte=today,
    ).filter(Q(valid_to__isnull=True) | Q(valid_to__gte=today)).exists():
        out.append(
            "No data-provision agreement in force for this source. The "
            "pull will not open a run, so no personal data is received.",
        )
    unbound = ChoiceOption.objects.filter(
        choice_list__list_name=STAAC_CATEGORY_LIST,
        canonical_code__isnull=True,
    ).count()
    if unbound:
        out.append(
            f"{unbound} STAAC category/categories have no approved "
            "binding. Cases carrying them are held, not lost, and file "
            "once the binding is approved.",
        )
    return out
