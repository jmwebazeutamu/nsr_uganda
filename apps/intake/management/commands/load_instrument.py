"""Load the questionnaire instrument from the committed snapshot.

The instrument used to be built by scripts/import_legacy_questionnaire.py
from k-forms/build_nsr_xlsform.py — a file that is not in the repository.
The 191 questions in the running databases therefore could not be rebuilt
from a clean checkout, which makes a new environment, a rebuilt test
database or a disaster recovery a problem nobody had noticed yet.

apps/intake/fixtures/instrument_v1.json is that instrument, captured from
the database it already lives in. Choice lists are referenced by name
rather than by primary key, because the ULIDs differ per environment —
referencing them by key is what made a plain Django fixture unloadable.

Idempotent: re-running updates in place and leaves ids alone.
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.intake.models import FormQuestion, FormSection, FormVersion
from apps.reference_data.models import ChoiceList

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "instrument_v1.json"


class Command(BaseCommand):
    help = "Load the questionnaire instrument from the committed snapshot."

    def add_arguments(self, parser):
        parser.add_argument("--path", default=str(FIXTURE))
        parser.add_argument(
            "--quiet", action="store_true",
            help="Suppress the summary (used by the test fixture).",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        data = json.loads(Path(options["path"]).read_text())

        versions = {}
        for row in data["form_versions"]:
            version, _ = FormVersion.objects.update_or_create(
                version=row["version"],
                defaults={k: v for k, v in row.items() if k != "version"},
            )
            versions[row["version"]] = version

        sections = {}
        for row in data["sections"]:
            section, _ = FormSection.objects.update_or_create(
                form_version=versions[row["form_version"]], code=row["code"],
                defaults={
                    k: v for k, v in row.items()
                    if k not in ("form_version", "code")
                },
            )
            sections[(row["form_version"], row["code"])] = section

        # One query for the whole choice-list vocabulary rather than one
        # per question.
        choice_lists = {
            c.list_name: c
            for c in ChoiceList.objects.filter(version=1)
        }

        created = updated = unresolved = 0
        missing_lists = set()
        for row in data["questions"]:
            section = sections[(row["form_version"], row["section"])]
            list_name = row.get("choice_list")
            choice_list = choice_lists.get(list_name) if list_name else None
            if list_name and choice_list is None:
                # A coded question whose list is not seeded would silently
                # become a free-text question. Counted and reported.
                missing_lists.add(list_name)
                unresolved += 1
            defaults = {
                k: v for k, v in row.items()
                if k not in ("form_version", "section", "name", "choice_list")
            }
            defaults["choice_list_ref"] = choice_list
            _, was_created = FormQuestion.objects.update_or_create(
                section=section, name=row["name"], defaults=defaults,
            )
            created += was_created
            updated += not was_created

        if not options["quiet"]:
            self.stdout.write(
                f"instrument loaded: {len(versions)} version(s), "
                f"{len(sections)} section(s), {created} question(s) created, "
                f"{updated} updated"
            )
            if missing_lists:
                self.stdout.write(self.style.WARNING(
                    f"{unresolved} question(s) reference choice lists that are "
                    f"not seeded, so their answers cannot be decoded: "
                    f"{sorted(missing_lists)}"
                ))
