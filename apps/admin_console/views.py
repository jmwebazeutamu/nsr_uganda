"""Admin Console views — HTML shell + the API for the PMT screens
this sprint ships (Dashboard + Configuration).

The HTML shell is a thin Django wrapper around the existing
design-harness files (same pattern as `nsr_mis.views.console`); the
shell's only job is to gate the bundle and inject session context.
React routing happens client-side.
"""

from __future__ import annotations

from pathlib import Path

from django.http import FileResponse, Http404, HttpResponseForbidden

from apps.admin_console.permissions import user_can_admin_console

# Reuse the existing design/ directory — admin shell loads the same
# components.jsx and admin-only screen files. A dedicated HTML
# entry point (design/nsr-mis-admin-console.html) keeps the admin
# bundle from pulling in operator screens.
DESIGN_DIR = Path(__file__).resolve().parent.parent.parent / "design"


def admin_console(request, path: str = "nsr-mis-admin-console.html"):
    """Serve the admin-console HTML harness. Gated on group
    membership per HANDOFF §2.1. 403 (not redirect) so a misrouted
    operator notices loudly."""
    if not user_can_admin_console(request.user):
        return HttpResponseForbidden(
            "Admin Console access requires membership in one of: "
            "nsr_admin / mglsd_statistics / dpo / nsr_dba / nsr_security.",
        )
    target = (DESIGN_DIR / path).resolve()
    try:
        target.relative_to(DESIGN_DIR)
    except ValueError as exc:
        raise Http404("path outside design root") from exc
    if not target.is_file():
        raise Http404(f"design asset not found: {path}")
    return FileResponse(open(target, "rb"))  # noqa: SIM115
