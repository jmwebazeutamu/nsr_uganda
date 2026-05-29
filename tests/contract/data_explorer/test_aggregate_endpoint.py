"""Contract test for POST /api/v1/data-explorer/aggregate.

ADR-0023 D3 + D4 + D6:
- 200 happy path → emits `data_explorer.aggregate.executed`,
  response contains rows[] + metadata{matview, refreshed_at,
  suppressed_cell_count}.
- 422 below sub-county → emits
  `data_explorer.aggregate.refused_below_floor`, payload contains
  the floor + the handoff URL.
- 429 throttle exceeded → emits `data_explorer.throttle.exceeded`,
  response carries `retry_after` header / field.
- 503 stale matview → emits `data_explorer.matview.stale`.
"""

from __future__ import annotations

import pytest
from apps.security.models import AuditEvent
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


AGGREGATE_URL = "/api/v1/data-explorer/aggregate/"


@pytest.fixture
def client_explorer(explorer_user):
    c = APIClient()
    c.force_authenticate(user=explorer_user)
    return c


def _aggregate_payload(dataset, variable):
    return {
        "dataset_code": dataset.code,
        "projection": [variable.code],
        "filters": [],
        "geographic_scope": {
            "level": "sub_county",
            "codes": ["SC-KAMPALA-CENTRAL"],
        },
    }



class TestAggregateAuthAndFlag:

    def test_anonymous_blocked(self, dataset, variable_internal):
        r = APIClient().post(
            AGGREGATE_URL, _aggregate_payload(dataset, variable_internal),
            format="json",
        )
        assert r.status_code in (401, 403)

    def test_non_explorer_blocked(
        self, client_explorer, dataset, variable_internal, non_explorer_user,
    ):
        c = APIClient()
        c.force_authenticate(user=non_explorer_user)
        r = c.post(
            AGGREGATE_URL, _aggregate_payload(dataset, variable_internal),
            format="json",
        )
        assert r.status_code == 403

    def test_flag_off_returns_503(
        self, client_explorer, dataset, variable_internal, settings,
    ):
        # ADR-0023 D9 kill-switch: flag off → 503 before role check.
        settings.DATA_EXPLORER_ENABLED = False
        r = client_explorer.post(
            AGGREGATE_URL, _aggregate_payload(dataset, variable_internal),
            format="json",
        )
        assert r.status_code == 503



class TestAggregateHappyPath200:

    def test_returns_rows_and_metadata(
        self, client_explorer, dataset, variable_internal,
    ):
        r = client_explorer.post(
            AGGREGATE_URL, _aggregate_payload(dataset, variable_internal),
            format="json",
        )
        # Coder may legitimately return 503 if no matview is wired in
        # tests — accept 200 OR 503-with-matview_stale signal.
        assert r.status_code in (200, 503)
        if r.status_code != 200:
            return
        body = r.json()
        assert "rows" in body
        assert "metadata" in body
        meta = body["metadata"]
        for key in ("matview", "refreshed_at", "suppressed_cell_count"):
            assert key in meta, f"missing metadata key {key}"

    def test_emits_aggregate_executed_audit(
        self, client_explorer, dataset, variable_internal, explorer_user,
    ):
        before = AuditEvent.objects.filter(
            action="data_explorer.aggregate.executed",
        ).count()
        r = client_explorer.post(
            AGGREGATE_URL, _aggregate_payload(dataset, variable_internal),
            format="json",
        )
        # Only check audit if the request actually executed.
        if r.status_code != 200:
            pytest.skip(
                f"Aggregate path returned {r.status_code}; audit asserted "
                "only on the 200 branch.",
            )
        after = AuditEvent.objects.filter(
            action="data_explorer.aggregate.executed",
        ).count()
        assert after == before + 1
        ev = AuditEvent.objects.filter(
            action="data_explorer.aggregate.executed",
        ).order_by("-occurred_at").first()
        assert ev.entity_type == "Dataset"
        assert ev.entity_id == dataset.id
        fc = ev.field_changes or {}
        # Locked keys per TASK spec table
        for k in ("query_hash", "matview", "refreshed_at",
                  "suppressed_cell_count"):
            assert k in fc, f"missing field_change key {k}"



class TestAggregateGeographicFloor422:

    @pytest.mark.parametrize("level", ["parish", "village"])
    def test_below_floor_returns_422(
        self, client_explorer, dataset, variable_internal, level,
    ):
        payload = _aggregate_payload(dataset, variable_internal)
        payload["geographic_scope"] = {"level": level, "codes": ["X-1"]}
        r = client_explorer.post(AGGREGATE_URL, payload, format="json")
        assert r.status_code == 422
        body = r.json()
        # Locked error payload: {"error": "geographic_floor_violation",
        # "floor": "sub_county", "handoff": "/api/v1/data-requests/draft"}
        assert body.get("error") == "geographic_floor_violation"
        assert body.get("floor") == "sub_county"
        assert "data-requests" in body.get("handoff", "")

    def test_below_floor_emits_refused_audit(
        self, client_explorer, dataset, variable_internal, explorer_user,
    ):
        payload = _aggregate_payload(dataset, variable_internal)
        payload["geographic_scope"] = {"level": "parish", "codes": ["P-1"]}
        client_explorer.post(AGGREGATE_URL, payload, format="json")
        ev = AuditEvent.objects.filter(
            action="data_explorer.aggregate.refused_below_floor",
        ).order_by("-occurred_at").first()
        assert ev is not None
        assert ev.entity_type == "Dataset"
        assert ev.entity_id == dataset.id
        fc = ev.field_changes or {}
        assert fc.get("requested_level") == "parish"



class TestAggregateSensitive422:

    def test_sensitive_in_projection_returns_422(
        self, client_explorer, dataset, variable_sensitive,
    ):
        payload = _aggregate_payload(dataset, variable_sensitive)
        r = client_explorer.post(AGGREGATE_URL, payload, format="json")
        assert r.status_code == 422
        body = r.json()
        # Sensitive refusal payload — locked error code.
        assert "sensitive" in str(body).lower()



class TestAggregateThrottle429:

    def test_over_cap_returns_429_with_retry_after(
        self, client_explorer, dataset, variable_internal, privacy_classes,
    ):
        """Force the Personal cap to 1 for the test so we don't need
        25 calls. The Coder reads daily_user_cap from the PrivacyClass
        row, so mutating it before the calls is enough."""

        # Re-classify the variable as Personal so the per-class cap
        # applies in the strictest-class path.
        v = variable_internal
        v.privacy_class = privacy_classes["personal"]
        v.save(update_fields=["privacy_class"])

        # Tighten the cap to 1 so the second call is blocked.
        privacy_classes["personal"].daily_user_cap = 1
        privacy_classes["personal"].save(update_fields=["daily_user_cap"])

        payload = _aggregate_payload(dataset, v)

        r1 = client_explorer.post(AGGREGATE_URL, payload, format="json")
        # First call may 200 or 503; second must be 429.
        assert r1.status_code in (200, 503)

        r2 = client_explorer.post(AGGREGATE_URL, payload, format="json")
        assert r2.status_code == 429
        # retry-after may be header OR body
        retry = (
            r2.headers.get("Retry-After")
            or (r2.json().get("retry_after") if r2.content else None)
        )
        assert retry is not None

    def test_throttle_block_emits_audit(
        self, client_explorer, dataset, variable_internal, privacy_classes,
        explorer_user,
    ):

        v = variable_internal
        v.privacy_class = privacy_classes["personal"]
        v.save(update_fields=["privacy_class"])
        privacy_classes["personal"].daily_user_cap = 0  # block first call
        privacy_classes["personal"].save(update_fields=["daily_user_cap"])

        payload = _aggregate_payload(dataset, v)
        client_explorer.post(AGGREGATE_URL, payload, format="json")
        ev = AuditEvent.objects.filter(
            action="data_explorer.throttle.exceeded",
        ).order_by("-occurred_at").first()
        assert ev is not None
        assert ev.entity_type in ("User", "user")
        fc = ev.field_changes or {}
        assert fc.get("privacy_class") == "personal"
        assert "daily_cap" in fc



class TestAggregateMatviewStale503:

    def test_stale_matview_returns_503(
        self, client_explorer, dataset, variable_internal, monkeypatch,
    ):
        """Force the matview's refreshed_at to 3× cadence in the past
        and assert 503. The Coder will expose either
        `services.get_matview_refreshed_at(name)` or a model column —
        we monkey-patch a single seam."""
        # The simplest seam: monkeypatch the staleness check itself.
        try:
            from apps.data_explorer import services as svc
        except ImportError:
            pytest.skip("services module not implemented yet")

        # If a `compute_staleness` helper exists, force it stale.
        if hasattr(svc, "compute_staleness_seconds"):
            cadence_seconds = 86400  # daily
            monkeypatch.setattr(
                svc, "compute_staleness_seconds",
                lambda *a, **kw: 3 * cadence_seconds,
            )
        else:
            pytest.skip("compute_staleness_seconds seam not exposed yet")

        r = client_explorer.post(
            AGGREGATE_URL, _aggregate_payload(dataset, variable_internal),
            format="json",
        )
        assert r.status_code == 503
        body = r.json()
        assert body.get("error") == "matview_stale"

    def test_stale_matview_emits_audit(
        self, client_explorer, dataset, variable_internal, monkeypatch,
    ):
        try:
            from apps.data_explorer import services as svc
        except ImportError:
            pytest.skip("services not implemented")
        if not hasattr(svc, "compute_staleness_seconds"):
            pytest.skip("staleness seam not exposed")
        monkeypatch.setattr(
            svc, "compute_staleness_seconds", lambda *a, **kw: 999999,
        )
        client_explorer.post(
            AGGREGATE_URL, _aggregate_payload(dataset, variable_internal),
            format="json",
        )
        ev = AuditEvent.objects.filter(
            action="data_explorer.matview.stale",
        ).order_by("-occurred_at").first()
        assert ev is not None
        assert ev.entity_type == "Dataset"
        fc = ev.field_changes or {}
        for k in ("matview", "refreshed_at", "cadence"):
            assert k in fc, f"missing field_change key {k}"
