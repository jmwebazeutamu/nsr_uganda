"""Tiny landing view at / plus a same-origin shim that serves the
React design harness from /console/ so it can hit /api/v1/... with
the existing Django session cookie (no CORS dance required)."""

from pathlib import Path

from django.http import FileResponse, Http404, HttpResponse

DESIGN_DIR = Path(__file__).resolve().parent.parent / "design"


def console(_request, path: str = "nsr-mis-console.html"):
    """Serve files out of /design/ under /console/{path}. Dev-only
    convenience for US-S11-013 — the same files the static HTTP
    server on :8765 serves, but same-origin with the Django runserver
    so fetch() can carry the session cookie."""
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


def home(_request):
    return HttpResponse(HOME_HTML)
