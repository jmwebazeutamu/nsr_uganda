"""P1.3 — the linked update, and where a GRM-raised draft goes.

"Open linked UPD" synthesised an id: the literal string "01HXYUPD"
concatenated with the tail of the grievance id. The Updates Queue was
handed that and showed an unrelated change request, or nothing.

Underneath it, two real gaps. The console's view mapper dropped
`linked_change_request_id`, so the case panel never knew an update
existed and kept offering to open another one — a fresh DRAFT per
click. And the queue's three tabs asked for pending_approval, on_hold
and committed,rejected. A grievance opens its update as a DRAFT.
Nothing ever asked for a draft, so the correction went to a status no
screen looked at.
"""

from __future__ import annotations

import pytest

from apps.grievance.services import open_change_request_for_grievance
from apps.grievance.test_audit_endpoint import (  # noqa: F401 — fixtures
    _admin, _client, _household, worked_case,
)

pytestmark = pytest.mark.django_db


class TestTheLinkedUpdateIsReachable:

    def test_the_grievance_carries_the_real_change_request_id(
        self, worked_case, django_user_model,
    ):
        g = worked_case["grievance"]
        cr = open_change_request_for_grievance(
            g, requester="cdo.aine",
            changes={"household": {"village": "the right one"}},
        )
        r = _client(_admin(django_user_model)).get(
            f"/api/v1/grm/grievances/{g.id}/",
        )
        assert r.status_code == 200
        assert r.data["linked_change_request_id"] == str(cr.id)
        assert not str(cr.id).startswith("01HXYUPD")

    def test_a_grm_raised_update_lands_as_a_draft(
        self, worked_case, django_user_model,
    ):
        cr = open_change_request_for_grievance(
            worked_case["grievance"], requester="cdo.aine",
            changes={"household": {"village": "the right one"}},
        )
        assert cr.status == "draft"

    def test_the_queue_can_ask_for_drafts(self, worked_case, django_user_model):
        """The tab the console now has. Without it the row exists and
        no screen shows it."""
        cr = open_change_request_for_grievance(
            worked_case["grievance"], requester="cdo.aine",
            changes={"household": {"village": "the right one"}},
        )
        client = _client(_admin(django_user_model))

        drafts = client.get("/api/v1/upd/change-requests/", {"status": "draft"})
        assert drafts.status_code == 200
        assert str(cr.id) in {row["id"] for row in drafts.data["results"]}

        for tab in ("pending_approval", "on_hold", "committed,rejected"):
            other = client.get("/api/v1/upd/change-requests/", {"status": tab})
            assert str(cr.id) not in {row["id"] for row in other.data["results"]}, (
                f"a draft showed up under {tab} — the tab filters are wrong"
            )
