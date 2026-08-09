"""Create an operator with a role and an ABAC scope in one step.

An account needs three things before it can see anything:

  1. the account itself,
  2. a ROLE  -- a Django Group from the apps.security.roles catalogue, which
     carries the TOR permissions (ADR-0028),
  3. an ATTRIBUTE -- an OperatorScope naming the geography (or Partner) the
     operator covers.

Miss the third and the account is not broken, it is *blind*: the ABAC mixins
fail closed, so every list returns zero rows and no error. Creating operators
by hand across two admin screens made that easy to do, so this does all three
together and refuses combinations that cannot work.

    manage.py create_operator alice --role parish_chief --scope-code KLA-CEN
    manage.py create_operator bob   --role nsr_unit_coordinator     # national
    manage.py create_operator carol --role programme_manager --scope-code PDM
    manage.py create_operator dan   --role cdo --scope-code KAMPALA --dry-run

The scope level is taken from the role's `default_scope`; override with
--scope-level. Passwords are never accepted as arguments (they would land in
shell history and process listings) -- an unusable password is set and you
either use --set-password to be prompted, or send a reset.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.security import roles as role_catalogue
from apps.security.models import OperatorScope, ScopeLevel


class Command(BaseCommand):
    help = "Create an operator with a role and an ABAC scope."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--role", required=True,
                            help="Role code from apps.security.roles.")
        parser.add_argument("--scope-code", default="",
                            help="GeographicUnit code, or Partner.code for "
                                 "external roles. Empty for national.")
        parser.add_argument("--scope-level", default=None,
                            help="Override the role's default scope level.")
        parser.add_argument("--email", default="")
        parser.add_argument("--staff", action="store_true",
                            help="Grant Django admin access (is_staff).")
        parser.add_argument("--set-password", action="store_true",
                            help="Prompt for a password interactively.")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **o):
        username = o["username"]
        code = o["role"]

        role = role_catalogue.BY_CODE.get(code)
        if role is None:
            raise CommandError(
                f"unknown role {code!r}. Known roles:\n  "
                + "\n  ".join(sorted(role_catalogue.ROLE_CODES)),
            )

        level = o["scope_level"] or role.default_scope
        valid_levels = {c for c, _ in ScopeLevel.choices}
        if level not in valid_levels:
            raise CommandError(
                f"unknown scope level {level!r}; expected one of "
                f"{sorted(valid_levels)}",
            )

        scope_code = o["scope_code"]
        if level == "national" and scope_code:
            raise CommandError(
                "national scope is the wildcard and takes no --scope-code",
            )
        if level != "national" and not scope_code:
            raise CommandError(
                f"role {code!r} is scoped at {level!r}, so --scope-code is "
                "required. Without it the account would see nothing at all "
                "(the ABAC mixins fail closed).",
            )

        user_model = get_user_model()
        if user_model.objects.filter(username=username).exists():
            raise CommandError(f"user {username!r} already exists")

        try:
            group = Group.objects.get(name=code)
        except Group.DoesNotExist as exc:
            raise CommandError(
                f"no Django Group named {code!r} — run `manage.py sync_roles`",
            ) from exc

        perms = sorted(role.permissions)
        self.stdout.write(f"username      : {username}")
        self.stdout.write(f"role          : {role.code}  ({role.label})")
        self.stdout.write(f"scope         : {level}={scope_code or '*'}")
        self.stdout.write(f"permissions   : {', '.join(perms) or 'none'}")
        self.stdout.write(f"django admin  : {'yes' if o['staff'] else 'no'}")

        if o["dry_run"]:
            self.stdout.write(self.style.WARNING("dry run — nothing written"))
            return

        with transaction.atomic():
            user = user_model.objects.create_user(
                username=username, email=o["email"], is_staff=o["staff"],
            )
            # No password argument by design: it would be captured in shell
            # history and visible in `ps`. Unusable until explicitly set.
            user.set_unusable_password()
            user.save(update_fields=["password"])
            user.groups.add(group)
            OperatorScope.objects.create(
                user=user, scope_level=level, scope_code=scope_code,
                granted_by="create_operator", active=True,
                note=f"seeded with role {role.code}",
            )

        if o["set_password"]:
            from django.core.management import call_command
            call_command("changepassword", username)
        else:
            self.stdout.write(self.style.WARNING(
                "password is unusable — run "
                f"`manage.py changepassword {username}` before handing it over",
            ))

        self.stdout.write(self.style.SUCCESS(f"created {username}"))
