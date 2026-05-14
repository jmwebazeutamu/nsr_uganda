"""UPD workflow tests."""

from __future__ import annotations

from datetime import date

import pytest

from apps.data_management.models import Household, HouseholdVersion, Member, MemberVersion
from apps.reference_data.models import GeographicUnit
from apps.security.models import AuditEvent
from apps.update_workflow.models import (
    ChangeRequest,
    ChangeStatus,
    ChangeType,
    EntityType,
    SourceChannel,
)
from apps.update_workflow.services import (
    UpdError,
    commit_change_request,
    compute_diff,
    post_change_committed,
    reject_change_request,
    submit_change_request,
)

# --- Fixtures ---------------------------------------------------------------

@pytest.fixture
def geo(db):
    nodes = {}
    for level, key, parent in [
        ("region", "r", None), ("sub_region", "sr", "r"), ("district", "d", "sr"),
        ("county", "c", "d"), ("sub_county", "sc", "c"),
        ("parish", "p", "sc"), ("village", "v", "p"),
    ]:
        nodes[key] = GeographicUnit.objects.create(
            level=level, code=f"U-{key.upper()}", name=key.title(),
            parent=nodes.get(parent), effective_from=date(2026, 1, 1),
        )
    return nodes


@pytest.fixture
def household(db, geo):
    return Household.objects.create(
        region=geo["r"], sub_region=geo["sr"], district=geo["d"], county=geo["c"],
        sub_county=geo["sc"], parish=geo["p"], village=geo["v"],
        urban_rural="rural", address_narrative="Plot 1",
    )


@pytest.fixture
def member(db, household):
    return Member.objects.create(
        household=household, line_number=1, surname="Okot", first_name="James",
        sex="M", telephone_1="+256700000001",
    )


_DEFAULT_CHANGE = {"surname": {"old": "Okot", "new": "Okello"}}


def _draft(member, *, requester="enum-1", changes=_DEFAULT_CHANGE,
           pmt=False, ctype=ChangeType.CORRECTION):
    return ChangeRequest.objects.create(
        entity_type=EntityType.MEMBER, entity_id=member.id,
        change_type=ctype, pmt_relevant=pmt,
        changes=changes,
        source_channel=SourceChannel.PARISH, requester=requester,
    )


# --- compute_diff -----------------------------------------------------------

class TestDiff:
    def test_diff_picks_up_changed_field(self, member):
        d = compute_diff(EntityType.MEMBER, member.id,
                         proposed={"surname": "Okello", "first_name": "James"})
        assert d == {"surname": {"old": "Okot", "new": "Okello"}}

    def test_diff_empty_when_no_change(self, member):
        assert compute_diff(EntityType.MEMBER, member.id,
                            proposed={"surname": "Okot"}) == {}

    def test_diff_unknown_field_raises(self, member):
        with pytest.raises(UpdError, match="unknown field"):
            compute_diff(EntityType.MEMBER, member.id, proposed={"not_a_field": "x"})


# --- submit -----------------------------------------------------------------

class TestSubmit:
    def test_submit_sets_status_role_and_sla(self, member):
        req = _draft(member, pmt=False, ctype=ChangeType.CORRECTION)
        submit_change_request(req)
        req.refresh_from_db()
        assert req.status == ChangeStatus.PENDING_APPROVAL
        assert req.required_role == "supervisor"
        assert req.sla_deadline is not None

    def test_pmt_relevant_routes_to_cdo_with_tighter_sla(self, member):
        req = _draft(member, pmt=True, ctype=ChangeType.CORRECTION)
        submit_change_request(req)
        req.refresh_from_db()
        assert req.required_role == "cdo"

    def test_cannot_submit_empty_changes(self, member):
        req = _draft(member, changes={})
        with pytest.raises(UpdError, match="AC-UPD-DIFF"):
            submit_change_request(req)

    def test_cannot_resubmit(self, member):
        req = _draft(member)
        submit_change_request(req)
        with pytest.raises(UpdError, match="DRAFT"):
            submit_change_request(req)


# --- reject -----------------------------------------------------------------

class TestReject:
    def test_reject_records_decision(self, member):
        req = _draft(member, requester="alice")
        submit_change_request(req)
        reject_change_request(req, approver="bob", reason="evidence missing")
        req.refresh_from_db()
        assert req.status == ChangeStatus.REJECTED
        assert req.approver == "bob"
        assert req.decision_reason == "evidence missing"

    def test_no_self_reject(self, member):
        req = _draft(member, requester="alice")
        submit_change_request(req)
        with pytest.raises(UpdError, match="AC-UPD-NO-SELF-APPROVE"):
            reject_change_request(req, approver="alice", reason="x")

    def test_reject_requires_reason(self, member):
        req = _draft(member, requester="alice")
        submit_change_request(req)
        with pytest.raises(UpdError, match="non-empty reason"):
            reject_change_request(req, approver="bob", reason="")


# --- commit -----------------------------------------------------------------

class TestCommit:
    def test_commit_applies_changes_and_writes_version(self, member):
        req = _draft(member, requester="alice")
        submit_change_request(req)
        commit_change_request(req, approver="bob")
        member.refresh_from_db()
        req.refresh_from_db()
        assert member.surname == "Okello"
        assert req.status == ChangeStatus.COMMITTED
        # Paired version row created with effective_from set, effective_to NULL.
        versions = MemberVersion.objects.filter(member=member).order_by("version_number")
        assert versions.count() == 1
        assert versions[0].surname == "Okello"
        assert versions[0].effective_to is None
        assert versions[0].change_request_id == req.id

    def test_second_commit_closes_prior_version_window(self, member):
        req1 = _draft(member, requester="alice",
                      changes={"surname": {"old": "Okot", "new": "Okello"}})
        submit_change_request(req1)
        commit_change_request(req1, approver="bob")
        member.refresh_from_db()

        req2 = _draft(member, requester="alice",
                      changes={"surname": {"old": "Okello", "new": "Okoth"}})
        submit_change_request(req2)
        commit_change_request(req2, approver="bob")
        versions = MemberVersion.objects.filter(member=member).order_by("version_number")
        assert versions.count() == 2
        assert versions[0].effective_to is not None  # window closed
        assert versions[1].effective_to is None      # current

    def test_no_self_approve_on_commit(self, member):
        req = _draft(member, requester="alice")
        submit_change_request(req)
        with pytest.raises(UpdError, match="AC-UPD-NO-SELF-APPROVE"):
            commit_change_request(req, approver="alice")

    def test_concurrent_edit_detected(self, member):
        req = _draft(member, requester="alice",
                     changes={"surname": {"old": "Okot", "new": "Okello"}})
        submit_change_request(req)
        # Simulate another writer landing first.
        member.surname = "Stolen"
        member.save(update_fields=["surname", "updated_at"])
        with pytest.raises(UpdError, match="concurrent edit"):
            commit_change_request(req, approver="bob")

    def test_commit_emits_audit_event(self, member):
        req = _draft(member, requester="alice")
        submit_change_request(req)
        before = AuditEvent.objects.filter(action="commit", entity_type="change_request").count()
        commit_change_request(req, approver="bob")
        assert AuditEvent.objects.filter(
            action="commit", entity_type="change_request",
        ).count() == before + 1

    def test_commit_fires_post_change_committed_signal(self, member):
        captured = []

        def listener(sender, **kwargs):
            captured.append(kwargs)

        post_change_committed.connect(listener, dispatch_uid="t")
        try:
            req = _draft(member, requester="alice")
            submit_change_request(req)
            commit_change_request(req, approver="bob")
        finally:
            post_change_committed.disconnect(dispatch_uid="t")
        assert len(captured) == 1
        assert captured[0]["change_request"].id == req.id


# --- household path (versioning is symmetric) -------------------------------

class TestHouseholdCommit:
    def test_household_change_writes_household_version(self, household):
        req = ChangeRequest.objects.create(
            entity_type=EntityType.HOUSEHOLD, entity_id=household.id,
            change_type=ChangeType.CORRECTION, pmt_relevant=False,
            changes={"address_narrative": {"old": "Plot 1", "new": "Plot 1A"}},
            source_channel=SourceChannel.PARISH, requester="alice",
        )
        submit_change_request(req)
        commit_change_request(req, approver="bob")
        household.refresh_from_db()
        assert household.address_narrative == "Plot 1A"
        versions = HouseholdVersion.objects.filter(household=household)
        assert versions.count() == 1
        assert versions.first().address_narrative == "Plot 1A"
