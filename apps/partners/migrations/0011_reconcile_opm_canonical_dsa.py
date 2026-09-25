"""Move the OPM operational clauses off the retired NUFI test agreement.

This is a one-time data correction for production-facing OPM workflow data.
The OPM DSA reference is the legal/canonical identifier; NUFI-1-TEST must
never be selected as OPM's active agreement.
"""

from django.db import migrations


def reconcile_opm_dsa(apps, schema_editor):
    Partner = apps.get_model("partners", "Partner")
    Dsa = apps.get_model("partners", "DataSharingAgreement")

    opm = Partner.objects.filter(code="OPM").first()
    if opm is None:
        return
    canonical = Dsa.objects.filter(
        partner=opm, reference="DSA-OPM-2026-001",
    ).order_by("-version").first()
    legacy = Dsa.objects.filter(
        partner=opm, reference="NUFI-1-TEST",
    ).order_by("-version").first()
    if canonical is None:
        return
    if legacy is not None:
        # The live clauses were accidentally attached to the fixture-like
        # agreement. Only fill blank canonical clauses; never overwrite a
        # subsequently amended legal OPM DSA.
        changed = []
        if not canonical.field_scope and legacy.field_scope:
            canonical.field_scope = legacy.field_scope
            changed.append("field_scope")
        if not canonical.entities_scope and legacy.entities_scope:
            canonical.entities_scope = legacy.entities_scope
            changed.append("entities_scope")
        if canonical.geographic_scope.count() == 0:
            canonical.geographic_scope.set(legacy.geographic_scope.all())
        if changed:
            canonical.save(update_fields=[*changed, "updated_at"])
        if legacy.status == "active":
            legacy.status = "suspended"
            legacy.save(update_fields=["status", "updated_at"])
    if canonical.status != "active":
        canonical.status = "active"
        canonical.save(update_fields=["status", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [("partners", "0010_dsa_signature_email_code")]

    operations = [migrations.RunPython(reconcile_opm_dsa, migrations.RunPython.noop)]
