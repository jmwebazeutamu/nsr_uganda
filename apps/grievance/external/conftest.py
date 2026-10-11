"""Isolation both STAAC test modules need, defined once.

The choice-list resolvers are `lru_cache`d, and a cache outlives the
transaction a test is rolled back with. Without this, a test that
approves a category binding leaves it visible to the next test —
which is precisely how "an unmapped category is held" would pass
while being wrong, and it caught me once already.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _forget_resolved_bindings():
    from apps.reference_data.services import clear_resolver_cache

    clear_resolver_cache()
    yield
    clear_resolver_cache()


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch):
    """Retries are real seconds otherwise, and the 5xx tests use the
    whole budget."""
    from nsr_mis.common import http as shared_http

    monkeypatch.setattr(shared_http.time, "sleep", lambda _s: None)
