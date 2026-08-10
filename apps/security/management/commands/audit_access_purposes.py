"""Report which personal-data surfaces declare an access purpose (G2).

Purpose limitation is opt-in per surface: a missing declaration is permitted
and recorded as "not attributed", because forcing every viewset to name a
purpose would produce fictions rather than evidence. This shows where the gaps
are so they are a decision rather than an oversight.

    manage.py audit_access_purposes
"""

from __future__ import annotations

from django.apps import apps as django_apps
from django.core.management.base import BaseCommand

from apps.security.purpose import known_purpose_codes


class Command(BaseCommand):
    help = "Report access_purpose coverage across read-audited viewsets."

    def handle(self, *args, **opts):
        known = known_purpose_codes()
        declared, undeclared = [], []

        for cfg in django_apps.get_app_configs():
            if not cfg.name.startswith("apps."):
                continue
            try:
                module = __import__(f"{cfg.name}.api", fromlist=["api"])
            except Exception:
                continue
            for attr in sorted(dir(module)):
                obj = getattr(module, attr, None)
                if not isinstance(obj, type) or not attr.endswith("ViewSet"):
                    continue
                bases = {b.__name__ for b in getattr(obj, "__mro__", ())}
                if "AuditReadMixin" not in bases:
                    continue
                code = getattr(obj, "access_purpose", "") or ""
                mapped = getattr(obj, "access_purpose_map", None) or {}
                if code or mapped:
                    declared.append((f"{cfg.label}.{attr}", code or f"map:{sorted(mapped)}"))
                else:
                    undeclared.append(f"{cfg.label}.{attr}")

        self.stdout.write(self.style.MIGRATE_HEADING("DECLARED"))
        for name, code in declared:
            flag = "" if (not known or code in known or code.startswith("map:")) else "  <-- UNKNOWN CODE"
            self.stdout.write(f"  {name:44} {code}{flag}")
        if not declared:
            self.stdout.write("  none")

        self.stdout.write(self.style.MIGRATE_HEADING(
            "\nNOT ATTRIBUTED — reads are audited without a purpose"))
        for name in undeclared:
            self.stdout.write(f"  {name}")
        if not undeclared:
            self.stdout.write("  none")

        total = len(declared) + len(undeclared)
        if total:
            self.stdout.write(
                f"\ncoverage: {len(declared)}/{total} read-audited viewsets")
        self.stdout.write(
            "\nAn undeclared surface is not a bug by itself. Household/Member "
            "reads serve several purposes at once and their lawful basis is not "
            "consent, so attributing them to one code would be a fiction.")
