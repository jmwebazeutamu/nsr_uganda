"""The public landing page.

Unauthenticated by definition. Everything it renders comes from
apps.reporting.public_aggregates, which applies the §8.3 disclosure floor
before returning anything, and only when NSR_PUBLIC_STATS_LIVE is on.

No AuditEvent is written here. AuditEvent records who touched personal
data; this view reads none, and writing a row per anonymous page view
would flood the chain the anomaly feed reads without recording anything
about a person.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.shortcuts import render

from . import public_aggregates as agg

logger = logging.getLogger(__name__)


def public_landing(request):
    ctx = {
        "live": agg.stats_are_live(),
        "signin_url": getattr(settings, "NSR_STAFF_SIGNIN_URL", "/login/"),
        "counters": None,
        "kpis": None,
        "coverage": None,
        "demog": None,
    }
    if ctx["live"]:
        try:
            ctx["counters"] = agg.headline_counters()
            ctx["kpis"] = agg.kpi_row()
            ctx["coverage"] = agg.coverage_by_sub_region()
            ctx["demog"] = agg.demographics()
        except Exception:
            # §15.5 — a failed aggregate renders the last good value with
            # its date, never a spinner and never zero. There is no cache
            # yet, so it degrades to the placeholder slots instead, which
            # are visibly placeholders rather than plausible wrong numbers.
            logger.exception("public aggregates unavailable; rendering slots")
            ctx["live"] = False
    return render(request, "public_site/landing.html", ctx)
