"""Seed the consent purpose catalogue (US-CONSENT-01, CONSENT-O-01).

The agreed list is the scope-doc nine INCLUDING ``ELIGIBILITY`` (the purpose
PMT recompute gates on, US-CONSENT-12) and EXCLUDING the designer's inferred
``IDENTITY_VERIFICATION`` — the DPIA treats NIRA identity verification as a
public-task activity, not a consent purpose. Decision logged with the user
2026-05-30 and in ADR-0024.

Seeded rows are ACTIVE production rows (author/approver = seed sentinels, the
PMTModelVersion v1 precedent). Tests MUST NOT create purposes with these
production codes — use sentinel codes to avoid the unique-key collision
(project memory: version=900 / sentinel fixture pattern).
"""

from django.db import migrations
from django.utils import timezone

# code, name, lawful_basis, withdrawable, default_on, is_primary, is_optional,
# blurb, basis_note, display_order
PURPOSES = [
    ("REGISTRATION", "Registration", "CONSENT", True, True, True, False,
     "Create and maintain your household's record in the National Social Registry.",
     "", 1),
    ("ELIGIBILITY", "Eligibility assessment", "CONSENT", True, True, False, True,
     "Use your record to compute your household's eligibility score (PMT) for "
     "social programmes.",
     "", 2),
    ("REFERRAL", "Programme referral", "CONSENT", True, True, False, True,
     "Share your record with social programmes you may be eligible for.",
     "", 3),
    ("PAYMENTS", "Payments", "CONSENT", True, True, False, True,
     "Use your record to deliver cash or in-kind transfers to your household.",
     "", 4),
    ("COMMUNICATIONS_SMS", "SMS notifications", "CONSENT", True, False, False, True,
     "Receive SMS messages about your registration status and benefits.",
     "", 5),
    ("COMMUNICATIONS_USSD", "USSD self-service", "CONSENT", True, False, False, True,
     "Check your status yourself using the *234# USSD menu on any phone.",
     "", 6),
    ("RESEARCH", "Research", "CONSENT", True, False, False, True,
     "Allow de-identified use of your data for approved policy research.",
     "", 7),
    ("GRIEVANCE_CONTACT", "Grievance contact", "CONSENT", True, True, False, True,
     "Let grievance officers contact you about complaints you file.",
     "", 8),
    ("STATISTICS", "National statistics", "STATISTICAL_EXEMPTION", False, True, False, False,
     "Produce anonymous national poverty statistics with UBOS.",
     "Statistical exemption under DPPA 2019 §7(2)(e). Not withdrawable.", 9),
]


def seed(apps, schema_editor):
    ConsentPurpose = apps.get_model("consent", "ConsentPurpose")
    now = timezone.now()
    for (code, name, basis, withdrawable, default_on, is_primary, is_optional,
         blurb, basis_note, order) in PURPOSES:
        ConsentPurpose.objects.update_or_create(
            code=code,
            defaults=dict(
                name=name, lawful_basis=basis, withdrawable=withdrawable,
                default_on=default_on, is_primary=is_primary,
                is_optional=is_optional, blurb=blurb, basis_note=basis_note,
                display_order=order, status="ACTIVE",
                author="system-seed", approved_by="dpo-seed",
                approved_at=now,
                approval_note="Seeded catalogue v1 (CONSENT-O-01, ADR-0024).",
            ),
        )


def unseed(apps, schema_editor):
    ConsentPurpose = apps.get_model("consent", "ConsentPurpose")
    ConsentPurpose.objects.filter(
        code__in=[p[0] for p in PURPOSES]).delete()


class Migration(migrations.Migration):
    dependencies = [("consent", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
