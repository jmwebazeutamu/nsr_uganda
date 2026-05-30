"""Contract test for GET /api/v1/data-explorer/catalogue/public/.

ADR-0023 public-discovery extension (US-DATA-EXP-001): a citizen-facing,
anonymous, metadata-only data dictionary of the ENTIRE questionnaire.

Locked behaviour:
- Anonymous (no session) → 200. No EXPLORER role required.
- Body lists every questionnaire section and field, each badged with a
  privacy_class; sensitive fields ARE listed (full transparency).
- Metadata only — no record data and no cell counts anywhere in the body.
- DATA_EXPLORER_ENABLED off → 503 (the kill-switch still applies).
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

PUBLIC_URL = "/api/v1/data-explorer/catalogue/public/"


def test_anonymous_allowed():
    r = APIClient().get(PUBLIC_URL)
    assert r.status_code == 200


def test_lists_every_questionnaire_section():
    from apps.update_workflow import field_catalog

    r = APIClient().get(PUBLIC_URL)
    body = r.json()
    got = {s["key"] for s in body["sections"]}
    expected = field_catalog.category_keys()
    assert expected.issubset(got), f"missing sections: {expected - got}"
    assert body["totals"]["sections"] == len(body["sections"])


def test_fields_are_badged_and_sensitive_is_shown():
    r = APIClient().get(PUBLIC_URL)
    body = r.json()
    all_fields = [f for s in body["sections"] for f in s["fields"]]
    assert all_fields, "no fields exposed"
    # Every field carries a privacy class + aggregatable flag.
    for f in all_fields:
        assert f["privacy_class"] in {"public", "internal", "personal", "sensitive"}
        assert "aggregatable" in f
        assert "label" in f and "field_id" in f
    # Full-transparency decision: sensitive fields are present, and are
    # never aggregatable.
    sensitive = [f for f in all_fields if f["privacy_class"] == "sensitive"]
    assert sensitive, "expected at least one sensitive field (e.g. hiv_status)"
    assert all(f["aggregatable"] is False for f in sensitive)


def test_no_record_data_or_counts_leak():
    """The transparency surface must never carry household data or cell
    counts — only the metadata dictionary."""
    r = APIClient().get(PUBLIC_URL)
    body = r.json()
    for s in body["sections"]:
        # Section summaries describe the dictionary, never row counts.
        assert "row_count" not in s
        for f in s["fields"]:
            for forbidden in ("count", "value", "values", "rows", "data"):
                assert forbidden not in f, f"leaked {forbidden!r} in {f['field_id']}"


def test_flag_off_returns_503(settings):
    settings.DATA_EXPLORER_ENABLED = False
    r = APIClient().get(PUBLIC_URL)
    assert r.status_code == 503
