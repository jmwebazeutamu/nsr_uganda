"""Schema swap: Referral.programme + ProgrammeEnrolment.programme
now point at apps.partners.Programme; drop apps.referral.Programme
(US-S26-005 / ADR-0015).

Sequence is hand-crafted because the auto-detector can't produce
the relax-then-remap pattern needed for non-empty tables (none in
dev today, but production must survive it):

  1. AlterField on both FKs with db_constraint=False so we can set
     values that don't yet resolve against the current target.
  2. RunPython to update programme_id values from the referral.Programme
     ID space to the canonical apps.partners.Programme ID space,
     matched by `code`. No-op for an empty table.
  3. AlterField on both FKs to repoint at apps.partners.Programme
     (db_constraint=True by default).
  4. DeleteModel for apps.referral.Programme.

Forward-only per ADR-0003. The reverse hook is a no-op (operational
restore from the partners.Programme rows + a manual rebuild of
the referral.Programme table would be required, which is acceptable
because no production data exists at the time of this migration).
"""

from __future__ import annotations

from django.db import migrations, models


def _remap_fks(apps, schema_editor):
    """Walk every Referral and ProgrammeEnrolment, look up the
    canonical Programme by code, set programme_id to the canonical
    ULID. No-op for an empty referral.Programme table."""
    ReferralProgramme = apps.get_model("referral", "Programme")
    PartnersProgramme = apps.get_model("partners", "Programme")
    Referral = apps.get_model("referral", "Referral")
    ProgrammeEnrolment = apps.get_model("referral", "ProgrammeEnrolment")

    # Build code → canonical.id mapping once.
    code_to_canonical: dict[str, str] = {
        p.code: p.id for p in PartnersProgramme.objects.all() if p.code
    }
    if not code_to_canonical:
        return

    # Referral rows
    for ref in Referral.objects.all():
        src_prog = ReferralProgramme.objects.filter(pk=ref.programme_id).first()
        if src_prog is None:
            # FK value already canonical; nothing to do.
            continue
        canonical_id = code_to_canonical.get(src_prog.code)
        if canonical_id is None:
            raise RuntimeError(
                f"No canonical Programme for referral code {src_prog.code!r} "
                f"(Referral pk={ref.pk}). Did US-S26-004 run?"
            )
        Referral.objects.filter(pk=ref.pk).update(programme_id=canonical_id)

    # Enrolment rows
    for enr in ProgrammeEnrolment.objects.all():
        src_prog = ReferralProgramme.objects.filter(pk=enr.programme_id).first()
        if src_prog is None:
            continue
        canonical_id = code_to_canonical.get(src_prog.code)
        if canonical_id is None:
            raise RuntimeError(
                f"No canonical Programme for enrolment code {src_prog.code!r} "
                f"(ProgrammeEnrolment pk={enr.pk}). Did US-S26-004 run?"
            )
        ProgrammeEnrolment.objects.filter(pk=enr.pk).update(programme_id=canonical_id)


class Migration(migrations.Migration):

    dependencies = [
        ("referral", "0003_lift_referral_programmes_to_partners"),
        ("partners", "0006_programme_webhook_secret_encrypted"),
    ]

    operations = [
        # 1. Relax db-level FK constraint so we can stage canonical IDs.
        migrations.AlterField(
            model_name="referral",
            name="programme",
            field=models.ForeignKey(
                to="referral.Programme",
                on_delete=models.PROTECT,
                related_name="referrals",
                db_constraint=False,
            ),
        ),
        migrations.AlterField(
            model_name="programmeenrolment",
            name="programme",
            field=models.ForeignKey(
                to="referral.Programme",
                on_delete=models.PROTECT,
                related_name="enrolments",
                db_constraint=False,
            ),
        ),

        # 2. Remap programme_id values.
        migrations.RunPython(_remap_fks, migrations.RunPython.noop),

        # 3. Repoint FK target.
        migrations.AlterField(
            model_name="referral",
            name="programme",
            field=models.ForeignKey(
                to="partners.Programme",
                on_delete=models.PROTECT,
                related_name="referrals",
            ),
        ),
        migrations.AlterField(
            model_name="programmeenrolment",
            name="programme",
            field=models.ForeignKey(
                to="partners.Programme",
                on_delete=models.PROTECT,
                related_name="enrolments",
            ),
        ),

        # 4. Drop the legacy model.
        migrations.DeleteModel(name="Programme"),
    ]
