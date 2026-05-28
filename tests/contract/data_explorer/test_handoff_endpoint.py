"""Contract test for POST /api/v1/data-explorer/handoff.

ADR-0023 D1 + sequence diagram (c):
- 200 → emits `data_explorer.handoff.created`, response carries
  `redirect: /data-requests/<id>` and the new DataRequest id.
- Calls apps.data_requests.services.create_draft under the hood.
"""

from __future__ import annotations

import pytest
from apps.security.models import AuditEvent
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


HANDOFF_URL = "/api/v1/data-explorer/handoff/"


@pytest.fixture
def client_explorer(explorer_user):
    c = APIClient()
    c.force_authenticate(user=explorer_user)
    return c


@pytest.fixture
def session(dataset, variable_internal, explorer_user):
    from apps.data_explorer.models import ExplorerSession
    return ExplorerSession.objects.create(
        actor=str(explorer_user.id),
        last_query_hash="a" * 64,
        purpose_of_use="study",
    )


def _payload(session, variable):
    return {
        "session_id": session.id,
        "purpose_of_use": "Karamoja study",
        "requested_entity": "Household",
        "requested_fields": [variable.code],
        "geographic_scope": {"level": "parish", "codes": ["P-1"]},
        "filter_expression": {"and": []},
        "estimated_row_count": 12,
    }



class TestHandoffEndpoint:

    def test_anonymous_blocked(self, session, variable_internal):
        r = APIClient().post(
            HANDOFF_URL, _payload(session, variable_internal), format="json",
        )
        assert r.status_code in (401, 403)

    def test_non_explorer_blocked(
        self, session, variable_internal, non_explorer_user,
    ):
        c = APIClient()
        c.force_authenticate(user=non_explorer_user)
        r = c.post(
            HANDOFF_URL, _payload(session, variable_internal), format="json",
        )
        assert r.status_code == 403

    def test_happy_path_response_shape(
        self, client_explorer, session, variable_internal, monkeypatch,
    ):
        # Stub create_draft so the test doesn't need a real DSA.
        captured = {}

        def _fake_create_draft(payload, *, requester):
            captured["payload"] = payload
            class _DR:
                id = "01DRHANDOFFCONTRACT0000000A"
                status = "draft"
            return _DR()

        import apps.data_requests.services as drs_services
        monkeypatch.setattr(
            drs_services, "create_draft", _fake_create_draft, raising=False,
        )

        r = client_explorer.post(
            HANDOFF_URL, _payload(session, variable_internal), format="json",
        )
        assert r.status_code in (200, 201)
        body = r.json()
        # OpenAPI shape: { "redirect": "/data-requests/<id>",
        # "data_request_id": "<ULID>" }
        assert "redirect" in body
        assert "data-requests" in body["redirect"]
        assert body.get("data_request_id") or body.get("id")

    def test_handoff_emits_audit(
        self, client_explorer, session, variable_internal, monkeypatch,
        explorer_user,
    ):
        def _fake_create_draft(payload, *, requester):
            class _DR:
                id = "01DRHANDOFFAUDIT0000000000A"
                status = "draft"
            return _DR()

        import apps.data_requests.services as drs_services
        monkeypatch.setattr(
            drs_services, "create_draft", _fake_create_draft, raising=False,
        )

        client_explorer.post(
            HANDOFF_URL, _payload(session, variable_internal), format="json",
        )
        ev = AuditEvent.objects.filter(
            action="data_explorer.handoff.created",
        ).order_by("-occurred_at").first()
        assert ev is not None
        assert ev.entity_type == "DataRequest"
        # entity_id should be the new DR id
        assert ev.entity_id == "01DRHANDOFFAUDIT0000000000A"
        fc = ev.field_changes or {}
        assert fc.get("explorer_session_id") == session.id
        assert "source_query_hash" in fc
        assert len(fc["source_query_hash"]) == 64
