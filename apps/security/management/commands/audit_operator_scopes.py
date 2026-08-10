"""Report accounts whose roles and scopes do not line up.

The ABAC mixins fail closed, so the failure modes here are silent: an operator
with a role and no scope sees an empty screen, not an error, and a scope left
behind after a role is dropped grants visibility nobody is tracking.

    manage.py audit_operator_scopes            # report
    manage.py audit_operator_scopes --fix      # grant the scopes roles fully determine
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.security import roles as role_catalogue
from apps.security.models import OperatorScope
from apps.security.scope_provisioning import ensure_default_scopes


class Command(BaseCommand):
    help = "Report (and optionally fix) role/scope mismatches."

    def add_arguments(self, parser):
        parser.add_argument(
            "--fix", action="store_true",
            help="Create the scopes a role fully determines (national only). "
                 "Never invents a district/parish/partner code.",
        )

    def handle(self, *args, **opts):
        user_model = get_user_model()
        blind, manual, orphans, fixed = [], [], [], []

        for user in user_model.objects.prefetch_related("groups").order_by("username"):
            if user.is_superuser:
                continue  # bypasses ABAC by design

            codes = set(user.groups.values_list("name", flat=True))
            known = {c for c in codes if c in role_catalogue.ROLE_CODES}
            scopes = list(OperatorScope.objects.filter(user=user, active=True))

            if opts["fix"] and known:
                result = ensure_default_scopes(user, actor="audit_operator_scopes")
                if result.granted:
                    fixed.append((user.get_username(), result.granted))
                    scopes = list(
                        OperatorScope.objects.filter(user=user, active=True))

            if known and not scopes:
                blind.append((user.get_username(), sorted(known)))
            elif known:
                for code in sorted(known):
                    role = role_catalogue.BY_CODE[code]
                    if not any(s.scope_level == role.default_scope for s in scopes):
                        manual.append(
                            (user.get_username(), code, role.default_scope))

            if scopes and not known:
                orphans.append(
                    (user.get_username(),
                     [f"{s.scope_level}:{s.scope_code or '*'}" for s in scopes]))

        if fixed:
            self.stdout.write(self.style.SUCCESS("Granted:"))
            for name, roles in fixed:
                self.stdout.write(f"  {name}: national scope for {', '.join(roles)}")

        self.stdout.write(self.style.MIGRATE_HEADING(
            "\nBLIND — holds a role, has no active scope, sees nothing"))
        for name, roles in blind:
            self.stdout.write(f"  {name:24} {', '.join(roles)}")
        if not blind:
            self.stdout.write("  none")

        self.stdout.write(self.style.MIGRATE_HEADING(
            "\nSCOPE LEVEL MISMATCH — role expects a level the account lacks"))
        for name, code, level in manual:
            self.stdout.write(f"  {name:24} {code} expects {level}")
        if not manual:
            self.stdout.write("  none")

        self.stdout.write(self.style.MIGRATE_HEADING(
            "\nORPHANED SCOPES — scope but no catalogue role (ADR-0006 DPO sweep)"))
        for name, scopes in orphans:
            self.stdout.write(f"  {name:24} {', '.join(scopes)}")
        if not orphans:
            self.stdout.write("  none")

        if blind or manual:
            self.stdout.write(self.style.WARNING(
                "\nScoped roles (district/parish/partner) cannot be fixed "
                "automatically — they need the specific code. Use "
                "`manage.py create_operator` for new accounts, or the "
                "OperatorScope inline in the user admin.",
            ))
