"""AuditReadMixin tests — every personal-data viewset emits a read event."""

from __future__ import annotations

from datetime import date

import pytest
from rest_framework.test import APIClient

from apps.data_management.models import Household, Member
from apps.reference_data.models import GeographicUnit
from apps.security.models import AuditEvent


@pytest.fixture
def auth_client(db, django_user_model):
    user = django_user_model.objects.create_user(username="reader", password="r-pass")
    c = APIClient()
    c.force_authenticate(user=user)
    return c, user


@pytest.fixture
def household(db):
    nodes = {}
    for level, key, parent in [
        ("region", "r", None), ("sub_region", "sr", "r"), ("district", "d", "sr"),
        ("county", "c", "d"), ("sub_county", "sc", "c"),
        ("parish", "p", "sc"), ("village", "v", "p"),
    ]:
        nodes[key] = GeographicUnit.objects.create(
            level=level, code=f"RA-{key.upper()}", name=key.title(),
            parent=nodes.get(parent), effective_from=date(2026, 1, 1),
        )
    return Household.objects.create(
        region=nodes["r"], sub_region=nodes["sr"], district=nodes["d"],
        county=nodes["c"], sub_county=nodes["sc"], parish=nodes["p"], village=nodes["v"],
        urban_rural="rural",
    )


class TestAuditReadMixinOnHousehold:
    def test_retrieve_emits_read_event(self, auth_client, household):
        client, user = auth_client
        before = AuditEvent.objects.filter(action="read", entity_type="household").count()
        r = client.get(f"/api/v1/data-management/households/{household.id}/")
        assert r.status_code == 200
        events = AuditEvent.objects.filter(action="read", entity_type="household")
        assert events.count() == before + 1
        ev = events.order_by("-occurred_at").first()
        assert ev.actor_id == user.username
        assert ev.entity_id == household.id

    def test_list_emits_list_read_event(self, auth_client, household):
        client, _ = auth_client
        before = AuditEvent.objects.filter(action="list_read",
                                           entity_type="household").count()
        r = client.get("/api/v1/data-management/households/")
        assert r.status_code == 200
        after = AuditEvent.objects.filter(action="list_read",
                                          entity_type="household").count()
        assert after == before + 1
        ev = AuditEvent.objects.filter(action="list_read",
                                       entity_type="household").order_by("-occurred_at").first()
        # entity_id encodes page + size for anomaly-detection downstream.
        assert "size=" in ev.entity_id

    def test_unauthenticated_does_not_emit(self, db, household):
        client = APIClient()
        before = AuditEvent.objects.count()
        r = client.get(f"/api/v1/data-management/households/{household.id}/")
        assert r.status_code == 403  # IsAuthenticated default
        assert AuditEvent.objects.count() == before  # no row written for refused reads


class TestAuditReadMixinOnMember:
    def test_member_retrieve_emits_event_with_member_entity_type(self, auth_client, household):
        client, _ = auth_client
        m = Member.objects.create(
            household=household, line_number=1, surname="Okot", first_name="J", sex="M",
        )
        before = AuditEvent.objects.filter(action="read", entity_type="member").count()
        r = client.get(f"/api/v1/data-management/members/{m.id}/")
        assert r.status_code == 200
        assert AuditEvent.objects.filter(
            action="read", entity_type="member", entity_id=m.id,
        ).count() == before + 1


class TestAuditCapturesRequestMetadata:
    def test_ip_and_user_agent_recorded(self, auth_client, household):
        client, _ = auth_client
        r = client.get(
            f"/api/v1/data-management/households/{household.id}/",
            HTTP_USER_AGENT="pytest-client/1.0", REMOTE_ADDR="10.0.0.42",
        )
        assert r.status_code == 200
        ev = AuditEvent.objects.filter(
            action="read", entity_type="household", entity_id=household.id,
        ).order_by("-occurred_at").first()
        assert ev.user_agent == "pytest-client/1.0"
        # ip_address is GenericIPAddressField — Django stores as string.
        assert str(ev.ip_address) == "10.0.0.42"


class TestNonPersonalDataDoesNotEmit:
    def test_geographic_units_do_not_emit_read_events(self, auth_client):
        client, _ = auth_client
        before = AuditEvent.objects.count()
        r = client.get("/api/v1/reference-data/geographic-units/")
        assert r.status_code == 200
        # Reference data isn't personal — no AuditEvent row.
        assert AuditEvent.objects.count() == before
