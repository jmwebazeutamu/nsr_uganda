from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Load the live DATA-EXP aggregate-variable metadata and "
        "activate it in the current database."
    )

    def handle(self, *args, **options):
        from apps.data_explorer import metadata_loader

        result = metadata_loader.refresh(quiet=False, activate=True)
        self.stdout.write(self.style.SUCCESS(str(result)))
