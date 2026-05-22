"""Admin Console Django app — second front-end bundle behind the
same Django backend (HANDOFF — Admin Console + PMT 2026-05-22).

Mounted at /admin-console/. Gated on the five admin groups:
nsr_admin, mglsd_statistics, dpo, nsr_dba, nsr_security. Audience is
the Statistics Unit, MGLSD policy team, DPO, DBA, security admins —
NOT operators. Different audience, different mental model, same
backend.

This sprint ships the PMT Dashboard + PMT Configuration screens.
Reference data, DQA rules, DDUP model, roles & scopes, audit chain
arrive in follow-up tickets — they're already in the sidebar nav as
disabled placeholders.
"""

from __future__ import annotations

from django.apps import AppConfig


class AdminConsoleConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.admin_console"
    label = "admin_console"
    verbose_name = "Admin Console"
