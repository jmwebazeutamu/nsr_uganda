"""Regression tests for the client-supplied-actor defect (2026-08-08 audit F5).

Approve / reject / merge / promote endpoints used to read the acting identity
out of the request body:

    actor = serializers.CharField(max_length=64)
    commit_change_request(req, approver=ser.validated_data["actor"])

which meant (a) the requester could approve their own record by naming
somebody else, defeating every author-cannot-approve rule, and (b) the
hash-chained AuditEvent log recorded an identity the server never
authenticated, so the chain could not support non-repudiation.

These tests assert the two properties that fix depends on:
  * a spoofed `actor` in the body cannot dodge the no-self-approve guard;
  * the AuditEvent records the authenticated user, not the payload.
"""

from datetime import date

import pytest
from apps.data_management.models import Household
from apps.reference_data.models import GeographicUnit
from apps.security.models import AuditEvent
from apps.update_workflow.models import (
    ChangeRequest,
    ChangeType,
    EntityType,
    SourceChannel,
)
from apps.update_workflow.services import submit_change_request
from rest_framework.test import APIClient


@pytest.fixture
def household(db):
    # Mirrors the geo + household fixtures in apps/update_workflow/tests.py,
    # which are module-local rather than shared via conftest.
    nodes = {}
    for level, key, parent in [
        ("region", "r", None), ("sub_region", "sr", "r"), ("district", "d", "sr"),
        ("county", "c", "d"), ("sub_county", "sc", "c"),
        ("parish", "p", "sc"), ("village", "v", "p"),
    ]:
        nodes[key] = GeographicUnit.objects.create(
            level=level, code=f"A-{key.upper()}", name=key.title(),
            parent=nodes.get(parent), effective_from=date(2026, 1, 1),
        )
    return Household.objects.create(
        region=nodes["r"], sub_region=nodes["sr"], district=nodes["d"],
        county=nodes["c"], sub_county=nodes["sc"], parish=nodes["p"],
        village=nodes["v"], urban_rural="2", address_narrative="Plot 1",
    )


@pytest.fixture
def operator(db, django_user_model):
    return django_user_model.objects.create_user(
        username="operator-a", password="pw", is_staff=True, is_superuser=True,
    )


@pytest.fixture
def client(operator):
    c = APIClient()
    c.force_authenticate(user=operator)
    return c


def _pending(household, requester):
    req = ChangeRequest.objects.create(
        entity_type=EntityType.HOUSEHOLD, entity_id=household.id,
        change_type=ChangeType.CORRECTION, pmt_relevant=False,
        source_channel=SourceChannel.PARISH,
        requester=requester, changes={"assets.radio": {"old": "0", "new": "1"}},
        requester_note="regression fixture",
    )
    submit_change_request(req)
    return req


@pytest.mark.django_db
class TestActorCannotBeSpoofed:

    def test_requester_cannot_self_approve_by_naming_someone_else(
        self, household, client, operator,
    ):
        """The core bypass: raise it yourself, then approve it while
        claiming to be a different person."""
        req = _pending(household, requester=operator.username)

        r = client.post(
            f"/api/v1/upd/change-requests/{req.id}/approve/",
            data={"actor": "some-other-reviewer", "reason": "looks fine"},
            format="json",
        )

        assert r.status_code == 400, (
            "a requester approved their own change request by supplying a "
            f"different actor in the body (got {r.status_code})"
        )
        assert "NO-SELF-APPROVE" in str(r.data)
        req.refresh_from_db()
        assert req.status != "committed"

    def test_audit_records_the_authenticated_user_not_the_payload(
        self, household, client, operator,
    ):
        """Attribution must survive a caller lying about who they are."""
        req = _pending(household, requester="someone-else")

        # Reject rather than approve: the commit path has a concurrent-edit
        # guard that needs a live-value fixture, and attribution is the
        # property under test, not the merge itself.
        r = client.post(
            f"/api/v1/upd/change-requests/{req.id}/reject/",
            data={"actor": "not-me", "reason": "needs evidence"},
            format="json",
        )
        assert r.status_code == 200, r.data

        events = AuditEvent.objects.filter(
            entity_type="change_request", entity_id=req.id, action="reject",
        )
        assert events.exists()
        actors = {e.actor_id for e in events}
        assert actors == {operator.username}, (
            f"audit attributed the decision to {actors} — the payload value "
            "'not-me' must never reach the audit chain"
        )

        req.refresh_from_db()
        assert req.approver == operator.username

    def test_anonymous_caller_is_refused(self, household):
        req = _pending(household, requester="someone-else")
        r = APIClient().post(
            f"/api/v1/upd/change-requests/{req.id}/approve/",
            data={"actor": "ghost"}, format="json",
        )
        assert r.status_code in (401, 403)
        req.refresh_from_db()
        assert req.status != "committed"
