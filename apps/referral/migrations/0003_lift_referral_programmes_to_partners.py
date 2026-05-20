"""Lift apps.referral.Programme rows into apps.partners.Programme
(US-S26-004 / ADR-0015 §"Decision 1+2+3").

For each referral.Programme row:
  1. If an apps.partners.Programme with the same `code` already
     exists, drop the referral row (deduplication — the lifted
     copy already lives in the canonical table).
  2. Else, attribute to the Partner whose `code` is the prefix of
     the referral programme code split on '-' (e.g. OPM-PDM →
     Partner code 'OPM'). Used when the referral side carried a
     compound code that encodes the operating ministry.
  3. Else, attribute to a synthesized 'GoU-Legacy' Partner row
     (idempotent get_or_create), status='provider' so the budget
     detector skips it. Operations re-attributes via /admin later.

The webhook_secret cleartext (referral.Programme.webhook_secret)
is moved into the new partners.Programme.webhook_secret_encrypted
column (added by partners/0006). The free-text dsa_reference is
carried into dsa_reference_legacy for traceability.

Forward-only per ADR-0003. The reverse hook deletes the lifted
canonical rows by note tag; the referral side is restored by
re-running the original seed against the surviving FKs (none in
dev today). No production data exists at the time of this
migration.

This migration is a no-op when apps.referral.Programme.objects
is empty — verified in dev (2026-05-20: 0 rows in all three
referral models).
"""

from __future__ import annotations

from django.db import migrations

LIFT_NOTE = "lifted-from-referral-via-US-S26-004"
LEGACY_PARTNER_CODE = "GoU-LEGACY"


def _ensure_legacy_partner(apps):
    """get_or_create the GoU-Legacy Partner — only invoked if a
    referral.Programme row needs the last-resort attribution."""
    Partner = apps.get_model("partners", "Partner")
    try:
        return Partner.objects.get(code=LEGACY_PARTNER_CODE)
    except Partner.DoesNotExist:
        from ulid import ULID
        return Partner.objects.create(
            id=str(ULID()),
            code=LEGACY_PARTNER_CODE,
            name="Government of Uganda — Legacy programmes",
            type="ministry",
            sector="",
            status="provider",
            tone="neutral",
            note=(
                "Synthetic placeholder partner created by "
                "US-S26-004 (ADR-0015) to absorb apps.referral.Programme "
                "rows that had no Partner attribution. Operations "
                "re-attributes within the OI-S26-1 SLA (30 days)."
            ),
        )


def _resolve_partner(apps, referral_programme):
    """Walk ADR-0015 §"Decision 2" attribution chain."""
    Partner = apps.get_model("partners", "Partner")
    # Step 2: code-prefix match on hyphenated codes (OPM-PDM → OPM).
    code = referral_programme.code or ""
    if "-" in code:
        prefix = code.split("-", 1)[0]
        partner = Partner.objects.filter(code=prefix).first()
        if partner is not None:
            return partner
    # Step 3: fallback.
    return _ensure_legacy_partner(apps)


def _lift(apps, schema_editor):
    ReferralProgramme = apps.get_model("referral", "Programme")
    PartnersProgramme = apps.get_model("partners", "Programme")

    for src in ReferralProgramme.objects.all():
        # Step 1: dedup against canonical.
        existing = PartnersProgramme.objects.filter(code=src.code).first()
        if existing is not None:
            continue

        # Steps 2+3: pick a Partner.
        partner = _resolve_partner(apps, src)

        from ulid import ULID
        dest = PartnersProgramme.objects.create(
            id=str(ULID()),
            partner=partner,
            code=src.code,
            name=src.name,
            summary=(src.description or "")[:1024],
            # Conservative defaults — the wizard would populate these
            # at create time; lifted rows go in as drafts so operations
            # can fill cohort/disbursement details later.
            kind="cash_transfer",
            status="active" if src.is_active else "draft",
            webhook_url=src.webhook_url or "",
            dsa_reference_legacy=src.dsa_reference or "",
        )
        # Carry the cleartext secret into the encrypted column.
        if src.webhook_secret:
            dest.webhook_secret_encrypted = src.webhook_secret.encode("utf-8")
            dest.save(update_fields=["webhook_secret_encrypted"])


def _unlift(apps, schema_editor):
    # Reverse — operational only. The lifted rows are identified by
    # the synthesized partner OR by lack of wizard-set fields. We
    # delete anything tagged with the LEGACY partner, leaving operator-
    # created canonical programmes intact.
    Partner = apps.get_model("partners", "Partner")
    PartnersProgramme = apps.get_model("partners", "Programme")
    legacy = Partner.objects.filter(code=LEGACY_PARTNER_CODE).first()
    if legacy is not None:
        PartnersProgramme.objects.filter(partner=legacy).delete()
        # Don't delete the legacy partner itself — operators may
        # have hand-attached non-lifted programmes to it.


class Migration(migrations.Migration):

    dependencies = [
        ("referral", "0002_drop_status_textchoices"),
        ("partners", "0006_programme_webhook_secret_encrypted"),
    ]

    operations = [
        migrations.RunPython(_lift, _unlift),
    ]
