"""US-S20-004 — push a FormVersion's XLSForm to Kobo.

Closes the manual "download xlsx, open Kobo web UI, click Import"
loop. Operators with a published Kobo SourceSystem can now click
"Publish to Kobo" on the FormVersion changeform; the service builds
the xlsx (via apps.intake.xlsform_export), uploads it through the
existing KoboConnector (apps.ingestion_hub.connectors.kobo), and
stores the resulting asset_uid back on FormVersion so re-publishes
land on the same Kobo asset (history preserved).

Atomic by transaction: if the Kobo call succeeds but the FormVersion
save fails, the asset is orphaned upstream. We accept this — Kobo
is the external system here and we cannot roll its state back. The
audit event captures the upstream uid even in that case so the
operator can reconcile manually.

Deferred-external-dep semantics: if there is no KoboCredential for
any KOBO_PILOT SourceSystem in the DB, publish_form_version raises
KoboPushUnavailable rather than hitting the network. Per the
project's "defer external-dep tickets honestly" rule, this lets
the feature be discoverable in the admin without requiring every
dev environment to have a Kobo token wired.
"""

from __future__ import annotations

from django.db import transaction

from apps.ingestion_hub.connectors.kobo import KoboConnector
from apps.ingestion_hub.models import KoboCredential, SourceSystem, SourceSystemKind
from apps.security.audit import emit as emit_audit

from .models import FormVersion
from .xlsform_export import export_to_xlsx


class KoboPushError(Exception):
    """Push refused or upstream rejected."""


class KoboPushUnavailable(KoboPushError):  # noqa: N818 — semantic name beats Error suffix here
    """No KoboCredential configured — feature is dormant in this env."""


def _resolve_credentials() -> dict:
    """Decrypt the active KoboCredential into a dict the connector
    accepts. Picks the first active KOBO_PILOT SourceSystem — the
    multi-Kobo case (MGLSD + OCHA) is a Sprint 21+ concern."""
    src = (
        SourceSystem.objects
        .filter(kind=SourceSystemKind.KOBO, is_active=True)
        .first()
    )
    if src is None:
        raise KoboPushUnavailable("no active KOBO SourceSystem")
    cred = KoboCredential.objects.filter(source_system=src).first()
    if cred is None:
        raise KoboPushUnavailable(
            f"SourceSystem {src.code!r} has no KoboCredential — "
            "configure one in the admin before publishing.",
        )
    return {
        "server_url": cred.server_url,
        # EncryptedBinaryField returns decrypted bytes on read.
        "token": bytes(cred.token_encrypted).decode("utf-8"),
    }


def publish_form_version(
    form_version: FormVersion, *,
    actor: str,
    connector: KoboConnector | None = None,
    credentials: dict | None = None,
    deploy: bool = True,
) -> dict:
    """Build the FormVersion's xlsx and push it to Kobo. If the
    FormVersion already has a kobo_asset_uid, replaces that asset's
    content (new Kobo version on same asset); otherwise creates a
    new asset.

    Returns the connector's report augmented with the FormVersion id
    and the asset_uid that was persisted.
    """
    if not actor:
        raise KoboPushError("actor required for publish")
    if form_version.status != "active":
        # Pushing a draft to Kobo would let the field team capture
        # against an unapproved form; refuse. Approve first.
        raise KoboPushError(
            f"FormVersion v{form_version.version} is {form_version.status!r}; "
            "only active forms can be published.",
        )

    creds = credentials or _resolve_credentials()
    conn = connector or KoboConnector()
    xlsx = export_to_xlsx(form_version)
    name = f"{form_version.name} v{form_version.version}"

    report = conn.publish_xlsform(
        creds,
        xlsx_bytes=xlsx, name=name,
        destination_uid=form_version.kobo_asset_uid or None,
        deploy=deploy,
    )

    # Persist the asset_uid + audit even on partial failure (status
    # != complete) so the operator can reconcile. The FormVersion's
    # own state isn't downgraded — Kobo is the external system.
    asset_uid = report.get("asset_uid", "") or ""
    if asset_uid and asset_uid != form_version.kobo_asset_uid:
        with transaction.atomic():
            form_version.kobo_asset_uid = asset_uid
            form_version.save(update_fields=["kobo_asset_uid", "updated_at"])

    emit_audit(
        action="kobo_publish", entity_type="intake.form_version",
        entity_id=form_version.id, actor=actor,
        reason=(
            f"v{form_version.version} → kobo "
            f"({report.get('status', 'unknown')})"
        ),
        field_changes={
            "kobo_asset_uid": asset_uid,
            "kobo_import_uid": report.get("import_uid", ""),
            "kobo_deployed": report.get("deployed", False),
            "kobo_status": report.get("status", ""),
        },
    )

    return {
        **report,
        "form_version_id": form_version.id,
        "version": form_version.version,
    }
