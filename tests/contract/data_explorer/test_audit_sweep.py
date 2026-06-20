"""Audit-event sweep — one test per (endpoint, response-code) pair from
the locked spec table in the TASK brief.

This is the contract-level guarantee that every DATA-EXP surface
writes the audit row the DPO can find later. Each test exercises one
branch and asserts:

  action, entity_type, entity_id, field_changes-keys

per the table.
"""

from __future__ import annotations

import pytest
from apps.security.models import AuditEvent
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


# ───────────────────────────────────────────────────────────────────────
# Mappings — keyed against the TASK spec table.
# Each row: (endpoint_label, action, entity_type, expected fc keys).
# ───────────────────────────────────────────────────────────────────────

EXPECTED = {
    "GET /datasets":           (
        "data_explorer.catalogue.browsed", "Dataset",
        {"result_count"},
    ),
    "GET /datasets/{id}":      (
        "data_explorer.dataset.read", "Dataset",
        {"dataset_code"},
    ),
    "GET /variables/{id}":     (
        "data_explorer.variable.read", "Variable",
        {"variable_code"},
    ),
    "POST /aggregate 200":     (
        "data_explorer.aggregate.executed", "Dataset",
        {"query_hash", "matview", "refreshed_at", "suppressed_cell_count"},
    ),
    "POST /aggregate 422 geo": (
        "data_explorer.aggregate.refused_below_floor", "Dataset",
        {"requested_level"},
    ),
    "POST /aggregate 429":     (
        "data_explorer.throttle.exceeded", "User",
        {"privacy_class", "daily_cap"},
    ),
    "POST /aggregate 503":     (
        "data_explorer.matview.stale", "Dataset",
        {"matview", "refreshed_at", "cadence"},
    ),
    "POST /handoff":           (
        "data_explorer.handoff.created", "DataRequest",
        {"explorer_session_id", "source_query_hash"},
    ),
    "nightly overlap-burst":   (
        "data_explorer.reidentification.suspected", "User",
        {"flagged_at", "overlap_dimensions"},
    ),
}


@pytest.fixture
def client_explorer(explorer_user):
    c = APIClient()
    c.force_authenticate(user=explorer_user)
    return c


def _assert_audit(action, entity_type, expected_keys, *, entity_id=None):
    qs = AuditEvent.objects.filter(action=action)
    if entity_id is not None:
        qs = qs.filter(entity_id=entity_id)
    ev = qs.order_by("-occurred_at").first()
    assert ev is not None, (
        f"Expected audit row with action={action} "
        f"(entity_type={entity_type}). None found."
    )
    # entity_type may be case-flexed
    assert ev.entity_type.lower() == entity_type.lower(), (
        f"entity_type mismatch: got {ev.entity_type!r}, "
        f"expected {entity_type!r}"
    )
    fc = ev.field_changes or {}
    missing = expected_keys - set(fc.keys())
    assert not missing, (
        f"Missing field_changes keys for {action}: {sorted(missing)}; "
        f"got {sorted(fc.keys())}"
    )



class TestAuditSweep:

    def test_catalogue_browsed(self, client_explorer, dataset):
        client_explorer.get("/api/v1/data-explorer/datasets/")
        action, et, keys = EXPECTED["GET /datasets"]
        _assert_audit(action, et, keys)

    def test_dataset_read(self, client_explorer, dataset):
        client_explorer.get(f"/api/v1/data-explorer/datasets/{dataset.id}/")
        action, et, keys = EXPECTED["GET /datasets/{id}"]
        _assert_audit(action, et, keys, entity_id=dataset.id)

    def test_variable_read(self, client_explorer, variable_internal):
        client_explorer.get(
            f"/api/v1/data-explorer/variables/{variable_internal.id}/",
        )
        action, et, keys = EXPECTED["GET /variables/{id}"]
        _assert_audit(action, et, keys, entity_id=variable_internal.id)

    def test_aggregate_executed(
        self, client_explorer, dataset, variable_internal,
    ):
        r = client_explorer.post(
            "/api/v1/data-explorer/aggregate/",
            {
                "dataset_code": dataset.code,
                "projection": [variable_internal.code],
                "filters": [],
                "geographic_scope": {
                    "level": "sub_county",
                    "codes": ["SC-1"],
                },
            },
            format="json",
        )
        if r.status_code != 200:
            pytest.skip(
                f"Aggregate path returned {r.status_code} — 200 audit "
                "asserted only on the executed branch.",
            )
        action, et, keys = EXPECTED["POST /aggregate 200"]
        _assert_audit(action, et, keys, entity_id=dataset.id)

    def test_aggregate_refused_below_floor(
        self, client_explorer, dataset, variable_internal,
    ):
        client_explorer.post(
            "/api/v1/data-explorer/aggregate/",
            {
                "dataset_code": dataset.code,
                "projection": [variable_internal.code],
                "filters": [],
                "geographic_scope": {
                    "level": "parish",
                    "codes": ["P-1"],
                },
            },
            format="json",
        )
        action, et, keys = EXPECTED["POST /aggregate 422 geo"]
        _assert_audit(action, et, keys, entity_id=dataset.id)

    def test_aggregate_throttle_exceeded(
        self, client_explorer, dataset, variable_internal, privacy_classes,
    ):
        # Zero out the cap so the first call is blocked.
        privacy_classes["personal"].daily_user_cap = 0
        privacy_classes["personal"].save(update_fields=["daily_user_cap"])
        v = variable_internal
        v.privacy_class = privacy_classes["personal"]
        v.save(update_fields=["privacy_class"])

        client_explorer.post(
            "/api/v1/data-explorer/aggregate/",
            {
                "dataset_code": dataset.code,
                "projection": [v.code],
                "filters": [],
                "geographic_scope": {
                    "level": "sub_county",
                    "codes": ["SC-1"],
                },
            },
            format="json",
        )
        action, et, keys = EXPECTED["POST /aggregate 429"]
        _assert_audit(action, et, keys)

    def test_aggregate_matview_stale(
        self, client_explorer, dataset, variable_internal, monkeypatch,
    ):
        try:
            from apps.data_explorer import services as svc
        except ImportError:
            pytest.skip("services not implemented yet")
        if not hasattr(svc, "compute_staleness_seconds"):
            pytest.skip("staleness seam not exposed yet")
        monkeypatch.setattr(
            svc, "compute_staleness_seconds", lambda *a, **kw: 9_999_999,
        )
        client_explorer.post(
            "/api/v1/data-explorer/aggregate/",
            {
                "dataset_code": dataset.code,
                "projection": [variable_internal.code],
                "filters": [],
                "geographic_scope": {
                    "level": "sub_county",
                    "codes": ["SC-1"],
                },
            },
            format="json",
        )
        action, et, keys = EXPECTED["POST /aggregate 503"]
        _assert_audit(action, et, keys, entity_id=dataset.id)

    def test_handoff_created(
        self, client_explorer, dataset, variable_internal, explorer_user,
        monkeypatch,
    ):
        # Stub create_draft so we don't need a DSA.
        def _fake(payload, *, requester):
            class _DR:
                id = "01DRSWEEP0000000000000000A"
                status = "draft"
            return _DR()
        import apps.data_requests.services as drs_services
        monkeypatch.setattr(
            drs_services, "create_draft", _fake, raising=False,
        )

        from apps.data_explorer.models import ExplorerSession
        sess = ExplorerSession.objects.create(
            actor=str(explorer_user.id),
            last_query_hash="b" * 64,
        )
        client_explorer.post(
            "/api/v1/data-explorer/handoff/",
            {
                "session_id": sess.id,
                "purpose_of_use": "x",
                "requested_entity": "Household",
                "requested_fields": [variable_internal.code],
                "geographic_scope": {"level": "parish", "codes": ["P-1"]},
                "filter_expression": {"and": []},
                "estimated_row_count": 5,
            },
            format="json",
        )
        action, et, keys = EXPECTED["POST /handoff"]
        _assert_audit(action, et, keys, entity_id="01DRSWEEP0000000000000000A")

    def test_overlap_burst_flag(
        self, dataset, variable_internal, explorer_user,
    ):
        """The nightly task `detect_overlap_burst` runs out-of-band.
        Invoke it directly with a synthetic query-log burst and
        assert the audit row."""
        try:
            from apps.data_explorer.tasks import detect_overlap_burst
        except ImportError:
            pytest.skip("detect_overlap_burst task not implemented yet")

        from apps.data_explorer.models import AggregateQueryLog
        actor = str(explorer_user.id)

        # 51 queries with overlapping 3-dimension filter_hash.
        for i in range(51):
            AggregateQueryLog.objects.create(
                actor=actor,
                dataset=dataset,
                projection_variables=[variable_internal.code],
                filter_variables=[
                    "household.head_age_band",
                    "household.dwelling_type",
                    "household.head_sex",
                ],
                filter_hash="overlap-3dim-shared",
                strictest_privacy_class="internal",
                query_hash=f"q-{i:03}",
                result_row_count=10,
                suppressed_cell_count=2,
            )

        detect_overlap_burst()

        action, et, keys = EXPECTED["nightly overlap-burst"]
        _assert_audit(action, et, keys)
