"""Pagination policy for the NSR MIS REST surface (ADR-0008).

Why this lives in apps.security: pagination *is* a security concern —
without a `max_page_size` cap, a client can request `?page_size=10000`
and turn a list endpoint into an enumeration tool. The default DRF
`PageNumberPagination` ignores the query param entirely (page_size is
fixed at PAGE_SIZE), which is safe but means React screens that
already pass `?page_size=4` (home queue panels) are over-fetching
the global default of 50.

Policy locked in ADR-0008:
- Consumers may pass `?page_size=` to request a different page size.
- The server caps it at `MAX_PAGE_SIZE` (default 500). Requests above
  the cap silently clamp — DRF's contract.
- The global PAGE_SIZE (50) remains the default when the client
  doesn't pass anything.
"""

from __future__ import annotations

from rest_framework.pagination import PageNumberPagination


class DefaultPagination(PageNumberPagination):
    """The pagination class wired in via REST_FRAMEWORK[
    'DEFAULT_PAGINATION_CLASS']. Honours `?page_size=` (cap 500)
    and `?page=` (1-indexed)."""

    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 500
