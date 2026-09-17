"""Tiny landing view at / plus a same-origin shim that serves the
React design harness from /console/ so it can hit /api/v1/... with
the existing Django session cookie (no CORS dance required).

The /manual/ route mirrors the same pattern for the MkDocs-built
user manual under /docs/user-manual/site/."""

import logging
from pathlib import Path

from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import redirect, render

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
DESIGN_DIR = REPO_ROOT / "design"
MANUAL_DIR = REPO_ROOT / "docs" / "user-manual" / "site"

#: Built console manifest, produced by scripts/build_console.mjs. Its
#: presence is what distinguishes a deployed image from a dev checkout:
#: `design/` is excluded from the Docker build context (.dockerignore),
#: so in a container the harness files simply do not exist and the
#: passthrough below can only 404 — which is exactly what /console/ did
#: in production before this build existed.
CONSOLE_MANIFEST = REPO_ROOT / "static" / "console" / "manifest.json"
#: Built console output. Sub-path requests (`/console/assets/...`) are
#: served from here once the console has been built.
CONSOLE_BUILD_DIR = REPO_ROOT / "static" / "console"


def console_asset(path: str):
    """A file from the built console, or None.

    The screens reference assets RELATIVELY — `assets/Coat_of_arms_of_Uganda.png`
    in both app shells, `assets/maps/<file>` in data-explorer coverage. Under
    the harness those resolve to /console/assets/... and are served out of
    design/. A built image has no design/, so the request 404s and the image
    silently vanishes — which is how the coat of arms disappeared from the
    top-left of both consoles with no error logged anywhere.

    Serving the same relative paths out of the build directory keeps one URL
    working in both environments without editing any screen.
    """
    if not CONSOLE_MANIFEST.is_file():
        return None
    target = (CONSOLE_BUILD_DIR / path).resolve()
    try:
        target.relative_to(CONSOLE_BUILD_DIR.resolve())
    except ValueError:
        return None          # traversal attempt
    return target if target.is_file() else None


def console_scripts(manifest_name: str = "manifest.json"):
    """Script filenames in dependency order, or None if not built.

    Order is load-bearing: the sources declare globals and rely on being
    evaluated in the harness's order, so it is read from the manifest
    rather than restated in the template. Shared with
    apps.admin_console.views, which passes "manifest-admin.json" — both
    shells are built by the same run of scripts/build_console.mjs.
    """
    try:
        import json
        path = CONSOLE_MANIFEST.parent / manifest_name
        return json.loads(path.read_text())["scripts"]
    except (OSError, ValueError, KeyError):
        return None


#: Backwards-compatible alias for the operator shell.
def _console_scripts():
    return console_scripts("manifest.json")


@login_required
def console(request, path: str = "nsr-mis-console.html"):
    """Serve the operator console.

    Two modes, chosen by what is actually on disk rather than by DEBUG,
    so a developer who has run the build gets the same page operators do:

    * BUILT (production) — render the precompiled shell. No Babel, no
      CDN, React production builds. See scripts/build_console.mjs.
    * HARNESS (dev) — pass files straight out of design/, compiled in the
      browser by Babel-standalone. US-S11-013's same-origin convenience,
      so fetch() carries the session cookie.

    A request for a sub-path (/console/foo.jsx) is only meaningful for the
    harness; in a built deployment those assets are served from /static/.
    """
    scripts = _console_scripts()
    if scripts is not None:
        if path in ("", "nsr-mis-console.html"):
            return render(request, "console/index.html",
                          {"console_scripts": scripts})
        built = console_asset(path)
        if built is not None:
            return FileResponse(open(built, "rb"))  # noqa: SIM115
    # Defence against ".." traversal — the resolved path must still
    # live under DESIGN_DIR.
    target = (DESIGN_DIR / path).resolve()
    try:
        target.relative_to(DESIGN_DIR)
    except ValueError as exc:
        raise Http404("path outside design root") from exc
    if not target.is_file():
        raise Http404(f"design asset not found: {path}")
    # Babel + JSX use text/javascript via the type='text/babel'
    # script tag; serving as the right MIME type avoids browser
    # warnings.
    return FileResponse(open(target, "rb"))  # noqa: SIM115


@login_required
def manual(_request, path: str = ""):
    """Serve the MkDocs-built user manual under /manual/{path}.

    MkDocs uses use_directory_urls=True so every page is foo/index.html,
    not foo.html. This view resolves directory-style URLs to the
    index.html inside them.

        /manual/                          -> site/index.html
        /manual/admin/                    -> site/admin/index.html
        /manual/admin/install/            -> site/admin/install/index.html
        /manual/assets/stylesheets/x.css  -> site/assets/stylesheets/x.css

    Rebuild with:  cd docs/user-manual && mkdocs build
    Dev-only; production should serve these static files through nginx."""
    if not MANUAL_DIR.is_dir():
        return HttpResponse(
            "<h1>Manual not built</h1>"
            "<p>Run <code>cd docs/user-manual && mkdocs build</code> "
            "then reload this page.</p>",
            status=503,
            content_type="text/html",
        )

    clean = path.strip("/")
    candidate = (MANUAL_DIR / clean) if clean else MANUAL_DIR
    if candidate.is_dir():
        candidate = candidate / "index.html"
    target = candidate.resolve()

    # Defence against ".." traversal — the resolved path must still
    # live under MANUAL_DIR.
    try:
        target.relative_to(MANUAL_DIR)
    except ValueError as exc:
        raise Http404("path outside manual root") from exc
    if not target.is_file():
        raise Http404(f"manual asset not found: {path}")

    return FileResponse(open(target, "rb"))  # noqa: SIM115

HOME_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>NSR MIS — entry points</title>
<style>
 body { font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        max-width: 720px; margin: 4rem auto; padding: 0 1rem; color: #1a1a1a; }
 h1 { margin-bottom: 0.25rem; }
 .sub { color: #555; margin-bottom: 2rem; }
 ul { list-style: none; padding: 0; }
 li { padding: 0.6rem 0; border-bottom: 1px solid #eee; }
 a { color: #1F3864; text-decoration: none; font-weight: 600; }
 a:hover { text-decoration: underline; }
 .desc { color: #555; font-weight: 400; }
</style>
</head>
<body>
<h1>NSR MIS</h1>
<p class="sub">Uganda National Social Registry — Sprint 0 baseline.</p>
<ul>
 <li><a href="/manual/">/manual/</a> &middot; <span class="desc">User manual (MkDocs site)</span></li>
 <li><a href="/admin/">/admin/</a> &middot; <span class="desc">Django admin (login required)</span></li>
 <li><a href="/api/docs/">/api/docs/</a> &middot; <span class="desc">Swagger UI</span></li>
 <li><a href="/api/schema/">/api/schema/</a> &middot; <span class="desc">OpenAPI 3.1 JSON</span></li>
 <li>
   <a href="/api/v1/reference-data/geographic-units/?level=region">/api/v1/reference-data/geographic-units/</a>
   &middot; <span class="desc">UBOS hierarchy</span>
 </li>
 <li><a href="/api/v1/data-management/households/">/api/v1/data-management/households/</a></li>
 <li><a href="/api/v1/dqa/rules/">/api/v1/dqa/rules/</a></li>
 <li><a href="/api/v1/ddup/match-pairs/">/api/v1/ddup/match-pairs/</a></li>
 <li><a href="/api/v1/dih/stage-records/">/api/v1/dih/stage-records/</a></li>
 <li><a href="/api/v1/security/audit-events/">/api/v1/security/audit-events/</a></li>
</ul>
</body>
</html>
"""


def home(request):
    """Public landing page — the only unauthenticated surface.

    Everything else (console, admin console, manual, API) requires a session.
    Signed-in users get role-appropriate entry points rather than a menu of
    places they will be refused from.

    Registry figures are rendered for signed-in users ONLY. Household
    counts and sub-region coverage are official statistics about a
    named population; publishing them on the unauthenticated surface
    would be an outbound disclosure decision for the DPO and a DSA, not
    a layout choice. The anonymous page therefore stays figure-free.

    The signed-in figures come from the same ABAC-scoped aggregator the
    /api/v1/reporting/dashboards/operator-kpis/ endpoint uses, so a
    sub-region operator sees their sub-region and a national role sees
    the nation — the page cannot widen anyone's view.
    """
    from apps.admin_console.permissions import user_can_admin_console

    roles_held: list[str] = []
    can_admin = False
    kpis = None
    coverage: list[dict] = []
    coverage_max = 0
    scope_label = None

    if request.user.is_authenticated:
        roles_held = sorted(request.user.groups.values_list("name", flat=True))
        can_admin = user_can_admin_console(request.user)

        from apps.reporting.dashboard_views import (
            compute_operator_kpis,
            households_by_sub_region,
        )
        from apps.security.audit import emit as emit_audit
        from apps.security.audit_views import _client_ip

        try:
            kpis = compute_operator_kpis(request.user)
            coverage = households_by_sub_region(request.user)
            coverage_max = max((r["count"] for r in coverage), default=0)
            # Say out loud whose numbers these are. A sub-region operator
            # reading "Households registered" must not take it for the
            # national figure.
            from apps.security.abac import _scoped_codes
            codes = _scoped_codes(request.user)
            scope_label = None if codes is None else ", ".join(sorted(codes))
        except Exception:
            # This route is also the sign-in gate's destination. A
            # failing aggregate must degrade to a figure-free page
            # rather than 500 somebody out of the system; the console
            # dashboards surface the error properly.
            logger.exception("landing KPIs unavailable; rendering without figures")
            kpis = None
            coverage = []
        else:
            emit_audit(
                "dashboard_read", "rpt_dashboard", "landing_kpis",
                actor=request.user.get_username(),
                reason=f"households_total={kpis['households_total']}",
                ip_address=_client_ip(request),
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
            )

    return render(request, "landing.html", {
        "roles": roles_held,
        "can_admin_console": can_admin,
        "kpis": kpis,
        "coverage": coverage,
        "coverage_max": coverage_max,
        "scope_label": scope_label,
    })


class LogoutConfirmView(auth_views.LogoutView):
    """Sign out, with a GET that renders a confirmation instead of a 405.

    Django 5 dropped GET logout, correctly: a link-prefetching browser or
    an <img> tag could otherwise sign a user out. But the bare 405 that
    replaces it is what a person sees whenever they bookmark /logout/ or
    type it, which they do. So GET renders a one-button page carrying a
    fresh CSRF token, and only POST actually ends the session.

    A fresh token also happens to be the cure for the other way people
    reach this URL in a broken state: a tab left open long enough for its
    token to go stale, whose Sign out then fails CSRF.
    """

    http_method_names = ["get", "post", "options"]
    template_name = "registration/logout_confirm.html"

    def get(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("/")
        return render(request, self.template_name)


def csrf_failure(request, reason=""):
    """Friendly CSRF failure page.

    Django's default is a bare 403 that tells a district officer their
    "Referer header" was wrong. The common cause is mundane — a page left
    open until its token expired — so say that, and give them the link
    that fixes it. `reason` is deliberately not echoed: it is diagnostic
    text, and it belongs in the log rather than on the screen.
    """
    logger.warning("CSRF failure on %s: %s", request.path, reason)
    return render(request, "csrf_failure.html", {"path": request.path}, status=403)
