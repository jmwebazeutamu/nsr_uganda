"""Manually ``REFRESH`` the Data Explorer materialised views.

Operational counterpart to the ``data_explorer.refresh_matviews`` beat
task — handy for the first post-deploy population (the migration creates
them ``WITH NO DATA``) and for ad-hoc refreshes during incidents.

    python manage.py refresh_explorer_matviews
    python manage.py refresh_explorer_matviews --concurrently
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import connection

from apps.data_management.matviews import refresh_explorer_matviews


class Command(BaseCommand):
    help = "REFRESH the Data Explorer mv_explorer_* materialised views."

    def add_arguments(self, parser):
        parser.add_argument(
            "--concurrently",
            action="store_true",
            help=(
                "Use REFRESH ... CONCURRENTLY (no read lock). Downgrades to a "
                "plain refresh for matviews not yet populated."
            ),
        )

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            self.stdout.write(
                self.style.WARNING(
                    f"Backend is {connection.vendor}, not Postgres — matviews are "
                    "shadowed by concrete tables and need no refresh."
                )
            )
            return
        names = refresh_explorer_matviews(concurrently=options["concurrently"])
        if not names:
            self.stdout.write(
                self.style.WARNING(
                    "No matviews found to refresh — run migrations first "
                    "(0010_data_explorer_matviews)."
                )
            )
            return
        self.stdout.write(
            self.style.SUCCESS(f"Refreshed {len(names)} matviews: {', '.join(names)}")
        )
