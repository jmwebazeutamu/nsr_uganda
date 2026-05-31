"""Seed the seven statement languages and the v3 REGISTRATION statement
(US-CONSENT-02). English carries real copy; the six Ugandan languages get
placeholder bodies flagged via ``placeholder_languages`` until translation
lands. The statement is seeded ACTIVE on REGISTRATION (seed sentinels for
author/approver, the production-seed precedent).

No legacy backfill statement is seeded — per the locked decision
(2026-05-30) migration 0004 (household backfill) is intentionally absent, so
there is no v1 LEGACY statement to FK against.
"""

from django.db import migrations
from django.utils import timezone

LANGUAGES = [
    ("en", "English", "English", True, 1),
    ("lg", "Luganda", "Luganda", False, 2),
    ("nyn", "Runyankole", "Runyankole", False, 3),
    ("ach", "Acholi", "Acholi", False, 4),
    ("xog", "Lusoga", "Lusoga", False, 5),
    ("lgg", "Lugbara", "Lugbara", False, 6),
    ("teo", "Ateso", "Ateso", False, 7),
]

REGISTRATION_STATEMENT_EN = (
    "The National Social Registry (NSR) is run by the Ministry of Gender, "
    "Labour and Social Development. We are asking to record information about "
    "you and the people in your household so that government and partner "
    "programmes can find and support families who need help.\n\n"
    "We will keep your information safe and use it only for the purposes you "
    "agree to. You can change your mind later. Withdrawing your consent will "
    "not affect support you are already receiving.\n\n"
    "Your information is protected under the Data Protection and Privacy Act, "
    "2019. You have the right to see your record, ask us to correct it, and "
    "ask us to stop using it for any purpose that depends on your consent."
)

_PLACEHOLDER_CODES = ["lg", "nyn", "ach", "xog", "lgg", "teo"]


def seed(apps, schema_editor):
    ConsentLanguage = apps.get_model("consent", "ConsentLanguage")
    ConsentPurpose = apps.get_model("consent", "ConsentPurpose")
    ConsentStatementVersion = apps.get_model("consent", "ConsentStatementVersion")
    now = timezone.now()

    for code, label, native, ready, order in LANGUAGES:
        ConsentLanguage.objects.update_or_create(
            code=code,
            defaults=dict(label=label, native_label=native,
                          is_ready=ready, display_order=order),
        )

    text_i18n = {"en": REGISTRATION_STATEMENT_EN}
    for code in _PLACEHOLDER_CODES:
        text_i18n[code] = f"[{code}] Translation pending — English text applies."

    try:
        registration = ConsentPurpose.objects.get(code="REGISTRATION")
    except ConsentPurpose.DoesNotExist:
        return  # purpose seed must have run; nothing to attach to otherwise

    ConsentStatementVersion.objects.update_or_create(
        purpose=registration, version=3,
        defaults=dict(
            text_i18n=text_i18n,
            placeholder_languages=_PLACEHOLDER_CODES,
            is_material=False, status="ACTIVE",
            effective_from=now.date(),
            author="system-seed", approved_by="dpo-seed", approved_at=now,
            approval_note="Seeded statement v3 EN (US-CONSENT-02, ADR-0024).",
        ),
    )


def unseed(apps, schema_editor):
    ConsentLanguage = apps.get_model("consent", "ConsentLanguage")
    ConsentStatementVersion = apps.get_model("consent", "ConsentStatementVersion")
    ConsentStatementVersion.objects.filter(
        purpose__code="REGISTRATION", version=3).delete()
    ConsentLanguage.objects.filter(
        code__in=[lng[0] for lng in LANGUAGES]).delete()


class Migration(migrations.Migration):
    dependencies = [("consent", "0002_seed_purposes")]
    operations = [migrations.RunPython(seed, unseed)]
