"""Re-apply the role catalogue to Django Groups.

The migration does this once; this command exists for when the catalogue
changes (a new role, or a changed permission set) without a schema change, and
for inspecting the matrix.

    manage.py sync_roles            # apply
    manage.py sync_roles --dry-run  # show the matrix and what would change
"""

from __future__ import annotations

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from apps.security.roles import PERMISSIONS, ROLES, sync_groups


class Command(BaseCommand):
    help = "Sync Django Groups + permissions from apps.security.roles."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Print the matrix and pending changes; write nothing.")

    def handle(self, *args, **opts):
        codes = sorted(PERMISSIONS)
        width = max(len(r.code) for r in ROLES) + 2

        self.stdout.write(self.style.MIGRATE_HEADING("Role → permission matrix"))
        header = " " * width + "".join(c.replace("data_", "")[:6].ljust(9) for c in codes)
        self.stdout.write(header)
        for role in ROLES:
            row = role.code.ljust(width)
            row += "".join(("  x".ljust(9) if c in role.permissions else "   ".ljust(9))
                           for c in codes)
            tag = "" if role.in_tor else "  (operational)"
            self.stdout.write(f"{row}{role.default_scope}{tag}")

        existing = set(Group.objects.values_list("name", flat=True))
        missing = sorted({r.code for r in ROLES} - existing)
        extra = sorted(existing - {r.code for r in ROLES})

        self.stdout.write("")
        self.stdout.write(f"groups to create : {missing or 'none'}")
        self.stdout.write(f"groups not in the catalogue (left alone): {extra or 'none'}")

        if opts["dry_run"]:
            self.stdout.write(self.style.WARNING("dry run — nothing written"))
            return

        result = sync_groups()
        self.stdout.write(self.style.SUCCESS(
            f"synced {result['roles']} roles, created {result['groups_created']} "
            f"groups, {result['permissions']} permissions",
        ))
