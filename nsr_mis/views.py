"""Tiny landing view at /."""

from django.http import HttpResponse

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
