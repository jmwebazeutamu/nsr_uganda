"""URLconf for the public site process.

The public zone routes the public landing page and its static assets and
nothing else. No console, no admin, no /api/. Spec LP-O-10 recommends the
public site sit in a network zone with no route to the registry network;
this is the application-level half of that guarantee, and
tests/contract/test_public_site.py asserts it.

Run it with:
    ROOT_URLCONF=nsr_mis.urls_public python manage.py runserver 0.0.0.0:8020
"""

from apps.reporting.public_views import public_landing
from django.http import HttpResponse
from django.urls import path


def _healthz(_request):
    """Container healthcheck.

    Returns the literal string "ok" and reads nothing, so it discloses no
    more than the fact that a process is up. Without it the healthcheck
    would have to poll "/", which runs the aggregate queries every 15
    seconds once figures are live.
    """
    return HttpResponse("ok")


urlpatterns = [
    path("", public_landing, name="public-landing"),
    path("public-site/01_landing_page_mockup.html", public_landing),
    path("healthz", _healthz, name="public-healthz"),
]
