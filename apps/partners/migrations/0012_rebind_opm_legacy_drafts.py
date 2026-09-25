"""Rebind resumable OPM drafts from the retired fixture agreement.

Submitted and later records remain immutable audit history.  A draft has not
entered the approval workflow, so it can safely follow the canonical OPM DSA
when resumed.
"""

from django.db import migrations


def rebind_opm_legacy_drafts(apps, schema_editor):
    Partner = apps.get_model("partners", "Partner")
    Dsa = apps.get_model("partners", "DataSharingAgreement")
    DataRequest = apps.get_model("data_requests", "DataRequest")

    opm = Partner.objects.filter(code="OPM").first()
    if opm is None:
        return
    canonical = Dsa.objects.filter(
        partner=opm, reference="DSA-OPM-2026-001",
    ).order_by("-version").first()
    legacy = Dsa.objects.filter(
        partner=opm, reference="NUFI-1-TEST",
    ).order_by("-version").first()
    if canonical is None or legacy is None:
        return
    DataRequest.objects.filter(dsa=legacy, status="draft").update(dsa=canonical)


class Migration(migrations.Migration):
    dependencies = [
        ("partners", "0011_reconcile_opm_canonical_dsa"),
        # DataRequest.dsa points at the canonical partners DSA only after
        # the ADR-0013 consolidation migrations have completed.
        ("data_requests", "0003_drop_drs_partner_and_dsa_dupes"),
    ]

    operations = [migrations.RunPython(rebind_opm_legacy_drafts, migrations.RunPython.noop)]
