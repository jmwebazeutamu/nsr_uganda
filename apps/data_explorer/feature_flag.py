"""Tiny helper for DATA_EXPLORER_ENABLED. Centralised so the permissions
class, the URL routes, and the admin views all read the same source.
"""

from __future__ import annotations

from django.conf import settings


def data_explorer_enabled(request=None) -> bool:
    """True when the DATA-EXP surface should answer. Per ADR-0023 D9
    default is False; dev/staging set it True. When False, every
    endpoint returns 503 and the sidebar link is hidden."""
    return bool(getattr(settings, "DATA_EXPLORER_ENABLED", False))
