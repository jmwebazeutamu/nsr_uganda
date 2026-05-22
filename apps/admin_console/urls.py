"""URL conf for the Admin Console.

Two kinds of routes:
- /admin-console/(.*)       → React HTML shell (gated on group)
- /api/v1/admin/...         → API endpoints (registered separately
                              in nsr_mis/urls.py)
"""

from __future__ import annotations

from django.urls import path

from apps.admin_console.views import admin_console

urlpatterns = [
    path("", admin_console, name="admin-console-home"),
    path("<path:path>", admin_console, name="admin-console-asset"),
]
