"""Project-wide pytest conftest.

Auto-skip @pytest.mark.postgres tests when the configured DB isn't
PostgreSQL — these exercise the audit-chain trigger and other features
that only run on Postgres (sqlite is the local dev fallback).
"""

from __future__ import annotations

import pytest
from django.db import connection


def pytest_collection_modifyitems(config, items):
    if connection.vendor == "postgresql":
        return
    skip_pg = pytest.mark.skip(reason="needs PostgreSQL backend (see @pytest.mark.postgres)")
    for item in items:
        if "postgres" in item.keywords:
            item.add_marker(skip_pg)
