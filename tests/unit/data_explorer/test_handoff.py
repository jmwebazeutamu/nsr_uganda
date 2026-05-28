"""DataRequestDraft serialiser + handoff service unit tests.

ADR-0023 D1: when the user clicks 'Request record-level data' on an
aggregate view, DATA-EXP serialises a DataRequestDraft and POSTs it
to apps.data_requests.services.create_draft. The payload shape is
locked by the ADR.

The handoff:
- Carries the parish/village geographic scope the user actually wanted
  (so the DPO sees original intent even if the aggregate was clipped
  to sub-county).
- Carries the explorer_session_id (ULID) so DRS can back-trace the
  discovery trail.
- Carries the source_query_hash (sha256) so DRS can correlate the
  draft with the AggregateQueryLog row.
"""

from __future__ import annotations

import hashlib
import json

import pytest


pytestmark = pytest.mark.django_db


def _handoff_service():
    """Locate the handoff entry-point. The Coder will name it
    create_handoff() under .services or .handoff."""
    for path in ("apps.data_explorer.services",
                 "apps.data_explorer.handoff"):
        try:
            mod = __import__(path, fromlist=["create_handoff"])
            if hasattr(mod, "create_handoff"):
                return mod.create_handoff
        except Exception:
            continue
    pytest.skip("create_handoff service not yet implemented")


def _draft_serializer():
    """The serializer-class that produces the payload shape. May
    live under .serializers or .schemas."""
    for path in ("apps.data_explorer.serializers",
                 "apps.data_explorer.schemas"):
        try:
            mod = __import__(path, fromlist=["DataRequestDraftSerializer"])
            if hasattr(mod, "DataRequestDraftSerializer"):
                return mod.DataRequestDraftSerializer
        except Exception:
            continue
    return None


class TestDraftSerialiserShape:

    def test_payload_has_all_locked_keys(
        self, dataset, variable_internal, explorer_user,
    ):
        """ADR-0023 D1 specifies the exact key set:
        source_module, source_query_hash, purpose_of_use,
        requested_entity, requested_fields, geographic_scope,
        filter_expression, estimated_row_count, explorer_session_id."""
        Serializer = _draft_serializer()
        if Serializer is None:
            pytest.skip("DataRequestDraftSerializer not yet implemented")

        from apps.data_explorer.models import ExplorerSession

        sess = ExplorerSession.objects.create(
            actor=str(explorer_user.id),
            last_query_hash="a" * 64,
            purpose_of_use="Karamoja elderly-headed HH study",
        )

        input_payload = {
            "session_id": sess.id,
            "purpose_of_use": "Karamoja elderly-headed HH study",
            "requested_entity": "Household",
            "requested_fields": [variable_internal.code],
            "geographic_scope": {
                "level": "parish",          # below the floor — the
                "codes": ["P-MOROTO-001"],  # user's original intent
            },
            "filter_expression": {
                "and": [
                    {"variable": variable_internal.code, "op": "eq", "value": "thatch"},
                ],
            },
            "estimated_row_count": 12,
        }
        out = Serializer(input_payload).data \
            if hasattr(Serializer(), "data") \
            else Serializer.serialize(input_payload)  # tolerate either API

        locked_keys = {
            "source_module",
            "source_query_hash",
            "purpose_of_use",
            "requested_entity",
            "requested_fields",
            "geographic_scope",
            "filter_expression",
            "estimated_row_count",
            "explorer_session_id",
        }
        assert locked_keys.issubset(set(out.keys()))
        assert out["source_module"] == "data_explorer"
        assert out["explorer_session_id"] == sess.id


class TestHandoffServiceIntegration:

    def test_create_handoff_calls_drs_create_draft(
        self, dataset, variable_internal, explorer_user, monkeypatch,
    ):
        """ADR-0023 D1: 'POSTs to apps.data_requests.services.
        create_draft'. We monkeypatch create_draft and assert the
        handoff service calls it with the locked-shape payload."""
        create_handoff = _handoff_service()

        # If the Coder hasn't implemented create_draft yet, the handoff
        # still must reach for it — assert via monkeypatched stub.
        captured = {}

        def _fake_create_draft(payload, *, requester):
            captured["payload"] = payload
            captured["requester"] = requester
            # Return a mock DataRequest-shaped object.
            class _DR:
                id = "01DRTESTHANDOFF000000000000"
                status = "draft"
            return _DR()

        # Patch wherever the Coder imports create_draft from.
        import apps.data_requests.services as drs_services
        monkeypatch.setattr(
            drs_services, "create_draft", _fake_create_draft, raising=False,
        )

        from apps.data_explorer.models import ExplorerSession
        sess = ExplorerSession.objects.create(
            actor=str(explorer_user.id),
            last_query_hash="a" * 64,
        )

        result = create_handoff(
            session_id=sess.id,
            actor=str(explorer_user.id),
            purpose_of_use="x",
            requested_entity="Household",
            requested_fields=[variable_internal.code],
            geographic_scope={"level": "parish", "codes": ["P-1"]},
            filter_expression={"and": []},
            estimated_row_count=12,
        )

        # The handoff must propagate the session id and produce a
        # query hash matching the canonical JSON encoding.
        assert "payload" in captured, (
            "create_handoff did not call data_requests.services.create_draft"
        )
        payload = captured["payload"]
        assert payload["source_module"] == "data_explorer"
        assert payload["explorer_session_id"] == sess.id
        # query hash is sha256 over the canonical filter — assert
        # 64-char hex.
        assert len(payload["source_query_hash"]) == 64

    def test_explorer_session_id_propagates(
        self, dataset, variable_internal, explorer_user, monkeypatch,
    ):
        create_handoff = _handoff_service()
        captured = {}

        def _fake_create_draft(payload, *, requester):
            captured["payload"] = payload
            class _DR:
                id = "01DRSESS00000000000000000A"
                status = "draft"
            return _DR()

        import apps.data_requests.services as drs_services
        monkeypatch.setattr(
            drs_services, "create_draft", _fake_create_draft, raising=False,
        )

        from apps.data_explorer.models import ExplorerSession
        sess = ExplorerSession.objects.create(
            actor=str(explorer_user.id),
            last_query_hash="b" * 64,
        )

        create_handoff(
            session_id=sess.id,
            actor=str(explorer_user.id),
            purpose_of_use="x",
            requested_entity="Household",
            requested_fields=[variable_internal.code],
            geographic_scope={"level": "sub_county", "codes": ["SC-1"]},
            filter_expression={"and": []},
            estimated_row_count=200,
        )

        assert captured["payload"]["explorer_session_id"] == sess.id

        # Session row updated with the data_request_id from DRS.
        sess.refresh_from_db()
        assert sess.handoff_status in ("submitted", "draft")
        if sess.handoff_status == "submitted":
            assert sess.data_request_id


class TestQueryHashCanonical:

    def test_query_hash_is_canonical_json_sha256(
        self, dataset, variable_internal, explorer_user, monkeypatch,
    ):
        """Different key orderings of the same logical query must
        produce the same hash — sha256 over canonical (sorted) JSON."""
        create_handoff = _handoff_service()

        seen_hashes = []

        def _fake_create_draft(payload, *, requester):
            seen_hashes.append(payload["source_query_hash"])
            class _DR:
                id = "01DRHASH000000000000000000"
                status = "draft"
            return _DR()

        import apps.data_requests.services as drs_services
        monkeypatch.setattr(
            drs_services, "create_draft", _fake_create_draft, raising=False,
        )

        from apps.data_explorer.models import ExplorerSession
        sess_a = ExplorerSession.objects.create(actor=str(explorer_user.id))
        sess_b = ExplorerSession.objects.create(actor=str(explorer_user.id))

        # Same logical filter, keys in different order
        f1 = {"and": [
            {"variable": variable_internal.code, "op": "eq", "value": "thatch"},
            {"variable": "household.head_sex", "op": "eq", "value": "F"},
        ]}
        f2 = {"and": [
            {"value": "F", "op": "eq", "variable": "household.head_sex"},
            {"value": "thatch", "op": "eq", "variable": variable_internal.code},
        ]}

        for sess, f in [(sess_a, f1), (sess_b, f2)]:
            create_handoff(
                session_id=sess.id,
                actor=str(explorer_user.id),
                purpose_of_use="x",
                requested_entity="Household",
                requested_fields=[variable_internal.code],
                geographic_scope={"level": "sub_county", "codes": ["SC-1"]},
                filter_expression=f,
                estimated_row_count=10,
            )

        assert len(seen_hashes) == 2
        # Canonical hashing → identical hashes despite the reorder.
        assert seen_hashes[0] == seen_hashes[1], (
            "source_query_hash must be over canonical (sorted) JSON; "
            "key-order leaked into the hash."
        )
