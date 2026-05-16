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


class MemberPagination(DefaultPagination):
    """Tighter cap on the Member endpoint specifically (US-S16-003).

    Member rows carry the highest-sensitivity PII surface — encrypted
    NIN ciphertext, NIN last4, phone, DoB, sex, GPS via household FK.
    A 500-row pull on this endpoint is several thousand PII fields in
    one round-trip; the DPO recommended a tighter cap. 100 rows still
    covers legitimate consumers (a household roster fits in 100 by
    construction — the largest known household in Uganda has 26
    members per UBOS) while reducing enumeration blast radius 5×.

    Closes ADR-0008 OI-PAG-01.
    """

    max_page_size = 100
