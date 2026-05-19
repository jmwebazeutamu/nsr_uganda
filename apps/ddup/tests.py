"""DDUP tier 1 + merge transaction tests.

References: SAD §4.3.6 acceptance criteria.
"""

from __future__ import annotations

from datetime import date

import pytest

from apps.data_management.models import Household, Member
from apps.ddup.models import (
    DdupModelVersion,
    MergeAction,
    MergeDecision,
    ModelStatus,
    PairStatus,
)
from apps.ddup.phone import to_e164
from apps.ddup.services import (
    DdupApprovalError,
    MergeError,
    activate_model_version,
    discover_nin_pairs,
    discover_phone_pairs,
    merge_member_pair,
    reject_pair,
    reverse_merge_decision,
)
from apps.reference_data.models import GeographicUnit
from apps.security.hashing import nin_hash
from apps.security.models import AuditEvent

# --- Fixtures ---------------------------------------------------------------

@pytest.fixture
def geo(db):
    """Minimal 7-level ladder for FK satisfaction."""
    nodes = {}
    for level, key, parent_key in [
        ("region", "r", None), ("sub_region", "sr", "r"), ("district", "d", "sr"),
        ("county", "c", "d"), ("sub_county", "sc", "c"),
        ("parish", "p", "sc"), ("village", "v", "p"),
    ]:
        nodes[key] = GeographicUnit.objects.create(
            level=level, code=f"T-{key.upper()}", name=key.title(),
            parent=nodes.get(parent_key), effective_from=date(2026, 1, 1),
        )
    return nodes


@pytest.fixture
def household(db, geo):
    return Household.objects.create(
        region=geo["r"], sub_region=geo["sr"], district=geo["d"], county=geo["c"],
        sub_county=geo["sc"], parish=geo["p"], village=geo["v"],
        urban_rural="2",
    )


@pytest.fixture
def active_model(db):
    v = DdupModelVersion.objects.create(
        version=1, description="tier1 NIN deterministic",
        config={"tier1": {"member": "nin", "household": "head_nin+village"}},
        author="archer",
    )
    activate_model_version(v, approver="bob")
    v.refresh_from_db()
    return v


def _hash(nin: str) -> bytes:
    # Use the canonical project hash so the DB-side rows match what
    # apps.ingestion_hub.services._discover_stage_candidates would compute.
    return nin_hash(nin)


# --- Model-version dual approval -------------------------------------------

class TestModelVersionApproval:
    def test_activate_happy_path(self, db):
        v = DdupModelVersion.objects.create(version=1, config={}, author="alice")
        activate_model_version(v, approver="bob")
        v.refresh_from_db()
        assert v.status == ModelStatus.ACTIVE
        assert v.approved_by == "bob"

    def test_author_cannot_approve_own(self, db):
        v = DdupModelVersion.objects.create(version=1, config={}, author="alice")
        with pytest.raises(DdupApprovalError, match="differ"):
            activate_model_version(v, approver="alice")

    def test_activating_v2_retires_v1(self, db):
        v1 = DdupModelVersion.objects.create(version=1, config={}, author="alice")
        activate_model_version(v1, approver="bob")
        v2 = DdupModelVersion.objects.create(version=2, config={}, author="alice")
        activate_model_version(v2, approver="bob")
        v1.refresh_from_db()
        v2.refresh_from_db()
        assert v1.status == ModelStatus.RETIRED
        assert v2.status == ModelStatus.ACTIVE


# --- AC-DDUP-NIN discovery --------------------------------------------------

class TestNinDiscovery:
    def test_two_members_with_same_nin_hash_create_pair(self, household, active_model):
        h = _hash("CM1234567890AB")
        m1 = Member.objects.create(household=household, line_number=1, surname="A",
                                   first_name="One", sex="1", nin_hash=h)
        m2 = Member.objects.create(household=household, line_number=2, surname="B",
                                   first_name="Two", sex="2", nin_hash=h)
        created = discover_nin_pairs(actor="system")
        assert len(created) == 1
        pair = created[0]
        assert pair.tier == 1
        assert pair.match_reason == "nin"
        assert {pair.record_a_id, pair.record_b_id} == {m1.id, m2.id}
        assert pair.status == PairStatus.PENDING

    def test_idempotent(self, household, active_model):
        h = _hash("CM1234567890AB")
        Member.objects.create(household=household, line_number=1, surname="A", first_name="One",
                              sex="1", nin_hash=h)
        Member.objects.create(household=household, line_number=2, surname="B", first_name="Two",
                              sex="2", nin_hash=h)
        first = discover_nin_pairs(actor="system")
        second = discover_nin_pairs(actor="system")
        assert len(first) == 1
        assert second == []

    def test_three_way_creates_three_pairs(self, household, active_model):
        h = _hash("CM1234567890AB")
        for i in range(3):
            Member.objects.create(household=household, line_number=i + 1,
                                  surname=f"S{i}", first_name=f"F{i}", sex="1", nin_hash=h)
        created = discover_nin_pairs(actor="system")
        assert len(created) == 3  # 3-choose-2

    def test_soft_deleted_member_ignored(self, household, active_model):
        h = _hash("CM1234567890AB")
        Member.objects.create(household=household, line_number=1, surname="A", first_name="One",
                              sex="1", nin_hash=h)
        Member.objects.create(household=household, line_number=2, surname="B",
                              first_name="Two", sex="2", nin_hash=h, is_deleted=True)
        created = discover_nin_pairs(actor="system")
        assert created == []

    def test_no_nin_hash_excluded(self, household, active_model):
        Member.objects.create(household=household, line_number=1, surname="A", first_name="One",
                              sex="1", nin_hash=None)
        Member.objects.create(household=household, line_number=2, surname="B", first_name="Two",
                              sex="2", nin_hash=None)
        assert discover_nin_pairs(actor="system") == []


# --- AC-DDUP-MERGE-COMMIT ---------------------------------------------------

class TestMergeCommit:
    def _build_pair(self, household):
        h = _hash("CM1234567890AB")
        a = Member.objects.create(household=household, line_number=1, surname="OLDsurname",
                                  first_name="James", sex="1", nin_hash=h, nin_last4="00AB",
                                  telephone_1="+256700000001")
        b = Member.objects.create(household=household, line_number=2, surname="Okot",
                                  first_name="James", sex="1", nin_hash=h, nin_last4="00AB",
                                  telephone_1="+256700000002")
        return discover_nin_pairs(actor="system")[0], a, b

    def test_merge_keeps_survivor_and_soft_deletes_loser(self, household, active_model):
        pair, a, b = self._build_pair(household)
        survivor_id = b.id  # pick b as the cleaner record
        merge_member_pair(pair, surviving_id=survivor_id,
                          chosen_field_values={"surname": "Okot", "telephone_1": "+256700000002"},
                          actor="op-1", note="single NIN match")

        survivor = Member.objects.get(id=survivor_id)
        loser = Member.objects.get(id=a.id if survivor_id == b.id else b.id)
        pair.refresh_from_db()

        assert survivor.is_deleted is False
        assert survivor.surname == "Okot"
        assert loser.is_deleted is True
        assert loser.deleted_at is not None
        assert loser.merged_into_id == survivor.id
        assert pair.status == PairStatus.MERGED

    def test_household_head_member_re_points_to_survivor(self, household, active_model):
        pair, a, b = self._build_pair(household)
        household.head_member = a
        household.save()
        merge_member_pair(pair, surviving_id=b.id, chosen_field_values={},
                          actor="op-1", note="")
        household.refresh_from_db()
        assert household.head_member_id == b.id

    def test_merge_writes_audit_event(self, household, active_model):
        pair, a, b = self._build_pair(household)
        prior = AuditEvent.objects.count()
        merge_member_pair(pair, surviving_id=b.id, chosen_field_values={},
                          actor="op-1", note="audit-test")
        new_events = AuditEvent.objects.order_by("occurred_at")[prior:]
        merge_events = [e for e in new_events if e.action == "merge"]
        assert len(merge_events) == 1
        assert merge_events[0].actor_id == "op-1"
        assert merge_events[0].entity_id == b.id

    def test_merge_decision_records_reverse_window(self, household, active_model):
        pair, a, b = self._build_pair(household)
        decision = merge_member_pair(pair, surviving_id=b.id, chosen_field_values={},
                                     actor="op-1", note="")
        assert decision.action == MergeAction.MERGE
        assert decision.reverse_window_until is not None

    def test_cannot_merge_a_non_pending_pair(self, household, active_model):
        pair, a, b = self._build_pair(household)
        merge_member_pair(pair, surviving_id=b.id, chosen_field_values={}, actor="op-1")
        with pytest.raises(MergeError, match="PENDING"):
            merge_member_pair(pair, surviving_id=b.id, chosen_field_values={}, actor="op-1")

    def test_surviving_id_must_be_in_pair(self, household, active_model):
        pair, a, b = self._build_pair(household)
        with pytest.raises(MergeError, match="surviving_id"):
            merge_member_pair(pair, surviving_id="01OUTSIDETHEPAIR0000000000",
                              chosen_field_values={}, actor="op-1")


# --- AC-DDUP-REJECT-LEARN ---------------------------------------------------

class TestReject:
    def test_reject_records_reason_and_prevents_requeue(self, household, active_model):
        h = _hash("CM1234567890AB")
        Member.objects.create(household=household, line_number=1, surname="A", first_name="One",
                              sex="1", nin_hash=h)
        Member.objects.create(household=household, line_number=2, surname="B", first_name="Two",
                              sex="2", nin_hash=h)
        pair = discover_nin_pairs(actor="system")[0]
        reject_pair(pair, actor="op-1", reason="legitimate-name-sharing")
        pair.refresh_from_db()
        assert pair.status == PairStatus.REJECTED

        # Re-discovery does not create a new pair for the same two members.
        again = discover_nin_pairs(actor="system")
        assert again == []

    def test_reject_requires_reason(self, household, active_model):
        h = _hash("CM1234567890AB")
        Member.objects.create(household=household, line_number=1, surname="A", first_name="One",
                              sex="1", nin_hash=h)
        Member.objects.create(household=household, line_number=2, surname="B", first_name="Two",
                              sex="2", nin_hash=h)
        pair = discover_nin_pairs(actor="system")[0]
        with pytest.raises(MergeError, match="reason"):
            reject_pair(pair, actor="op-1", reason="")


# --- Tier 2 phone normalisation + discovery (US-S2-007) --------------------

class TestPhoneNormalisation:
    @pytest.mark.parametrize("raw,expected", [
        ("+256700000001", "+256700000001"),
        ("0700000001",    "+256700000001"),
        ("256700000001",  "+256700000001"),
        ("+256 700 000 001", "+256700000001"),
        ("0700-000-001",  "+256700000001"),
    ])
    def test_accepts_valid_forms(self, raw, expected):
        assert to_e164(raw) == expected

    @pytest.mark.parametrize("raw", [
        "", None,
        "+1 555 555 5555",        # non-UG
        "0500000001",             # 5 isn't an accepted Ugandan prefix
        "07000000",               # too short
        "07000000012",            # too long
        "abc",                    # non-numeric
    ])
    def test_rejects_invalid(self, raw):
        assert to_e164(raw) is None


class TestPhoneDiscovery:
    def test_two_members_with_same_phone_create_tier2_pair(self, household, active_model):
        Member.objects.create(household=household, line_number=1, surname="A", first_name="One",
                              sex="1", telephone_1="+256700000001")
        Member.objects.create(household=household, line_number=2, surname="B", first_name="Two",
                              sex="2", telephone_1="0700000001")  # equivalent normalised
        created = discover_phone_pairs(actor="system")
        assert len(created) == 1
        assert created[0].tier == 2
        assert created[0].match_reason == "phone"

    def test_unparseable_phone_excluded(self, household, active_model):
        Member.objects.create(household=household, line_number=1, surname="A", first_name="One",
                              sex="1", telephone_1="abc")
        Member.objects.create(household=household, line_number=2, surname="B", first_name="Two",
                              sex="2", telephone_1="abc")
        assert discover_phone_pairs(actor="system") == []

    def test_idempotent(self, household, active_model):
        Member.objects.create(household=household, line_number=1, surname="A", first_name="One",
                              sex="1", telephone_1="+256700000001")
        Member.objects.create(household=household, line_number=2, surname="B", first_name="Two",
                              sex="2", telephone_1="+256700000001")
        first = discover_phone_pairs(actor="system")
        second = discover_phone_pairs(actor="system")
        assert len(first) == 1 and second == []

    def test_tier1_pair_not_redisco_as_tier2(self, household, active_model):
        # Same NIN AND same phone → tier 1 wins; the (a,b) uniqueness
        # constraint blocks a second tier-2 row for the same pair.
        h = _hash("CM1234567890AB")
        Member.objects.create(household=household, line_number=1, surname="A", first_name="One",
                              sex="1", nin_hash=h, telephone_1="+256700000001")
        Member.objects.create(household=household, line_number=2, surname="B", first_name="Two",
                              sex="2", nin_hash=h, telephone_1="+256700000001")
        tier1 = discover_nin_pairs(actor="system")
        tier2 = discover_phone_pairs(actor="system")
        assert len(tier1) == 1 and tier1[0].tier == 1
        assert tier2 == []  # already represented as a tier-1 pair


# --- SAD §4.3.2 — 30-day un-merge window ----------------------------------

class TestReverseMerge:
    """Within the 30-day reverse window, a MERGE decision can be undone:
    loser restored, surviving's fields rolled back, household head
    pointers restored. Outside the window — locked."""

    def _make_merge(self, household, active_model, *, with_overrides=False):
        from apps.security.hashing import nin_hash as _nin_hash
        h = _nin_hash("CM1234567890AB")
        a = Member.objects.create(
            household=household, line_number=1, surname="OriginalSurname",
            first_name="James", sex="1", nin_hash=h, nin_last4="00AB",
        )
        b = Member.objects.create(
            household=household, line_number=2, surname="Okot",
            first_name="James", sex="1", nin_hash=h, nin_last4="00AB",
        )
        pair = discover_nin_pairs(actor="system")[0]
        # b is the survivor; capture the surviving's pre-merge surname
        # so the test can verify reverse restores it.
        chosen = {"surname": "ChosenSurname"} if with_overrides else {}
        decision = merge_member_pair(
            pair, surviving_id=b.id, chosen_field_values=chosen,
            actor="op-1", note="initial merge",
        )
        return pair, decision, a, b

    def test_reverse_restores_loser(self, household, active_model):
        pair, decision, a, b = self._make_merge(household, active_model)
        reverse_merge_decision(
            decision, actor="reviewer-1", reason="enumerator misidentified pair",
        )
        a.refresh_from_db()
        b.refresh_from_db()
        pair.refresh_from_db()
        assert a.is_deleted is False
        assert a.deleted_at is None
        assert a.merged_into_id is None
        # b is still active (survivor was b).
        assert b.is_deleted is False
        # Pair flipped back to PENDING for re-decision.
        assert pair.status == PairStatus.PENDING

    def test_reverse_restores_surviving_overrides(self, household, active_model):
        pair, decision, a, b = self._make_merge(
            household, active_model, with_overrides=True,
        )
        b.refresh_from_db()
        assert b.surname == "ChosenSurname"
        reverse_merge_decision(
            decision, actor="reviewer-1", reason="wrong field choice",
        )
        b.refresh_from_db()
        # The surviving member's surname is restored to its pre-merge value.
        assert b.surname == "Okot"

    def test_reverse_restores_household_head_pointer(
        self, household, active_model,
    ):
        # Set household head BEFORE merge so merge re-points it.
        from apps.security.hashing import nin_hash as _nin_hash
        h = _nin_hash("CM1234567890AB")
        a = Member.objects.create(
            household=household, line_number=1, surname="X", first_name="A",
            sex="1", nin_hash=h, nin_last4="00AB",
        )
        b = Member.objects.create(
            household=household, line_number=2, surname="X", first_name="B",
            sex="1", nin_hash=h, nin_last4="00AB",
        )
        household.head_member = a
        household.save()
        pair = discover_nin_pairs(actor="system")[0]
        decision = merge_member_pair(
            pair, surviving_id=b.id, chosen_field_values={},
            actor="op-1", note="",
        )
        household.refresh_from_db()
        assert household.head_member_id == b.id  # re-pointed

        reverse_merge_decision(
            decision, actor="reviewer-1", reason="head identity wrong",
        )
        household.refresh_from_db()
        assert household.head_member_id == a.id  # restored

    def test_reverse_records_actor_reason_timestamp(
        self, household, active_model,
    ):
        _, decision, _, _ = self._make_merge(household, active_model)
        reverse_merge_decision(
            decision, actor="reviewer-1", reason="ambiguous identity",
        )
        decision.refresh_from_db()
        assert decision.reversed_at is not None
        assert decision.reversed_by == "reviewer-1"
        assert "ambiguous" in decision.reversed_reason

    def test_reverse_emits_unmerge_audit_event(self, household, active_model):
        pair, decision, _, _ = self._make_merge(household, active_model)
        reverse_merge_decision(decision, actor="rv", reason="r")
        ev = AuditEvent.objects.filter(
            action="unmerge", entity_type="match_pair", entity_id=pair.id,
        ).first()
        assert ev is not None
        assert ev.actor_id == "rv"

    def test_cannot_reverse_outside_window(self, household, active_model):
        from datetime import timedelta

        from django.utils import timezone
        _, decision, _, _ = self._make_merge(household, active_model)
        # Push reverse_window_until into the past.
        decision.reverse_window_until = timezone.now() - timedelta(seconds=1)
        decision.save(update_fields=["reverse_window_until"])
        with pytest.raises(MergeError, match="window closed"):
            reverse_merge_decision(decision, actor="late", reason="too late")

    def test_cannot_reverse_already_reversed(self, household, active_model):
        _, decision, _, _ = self._make_merge(household, active_model)
        reverse_merge_decision(decision, actor="rv", reason="first")
        with pytest.raises(MergeError, match="already reversed"):
            reverse_merge_decision(decision, actor="rv", reason="second")

    def test_reverse_requires_reason(self, household, active_model):
        _, decision, _, _ = self._make_merge(household, active_model)
        with pytest.raises(MergeError, match="non-empty reason"):
            reverse_merge_decision(decision, actor="rv", reason="")

    def test_cannot_reverse_a_reject_decision(self, household, active_model):
        from apps.ddup.services import reject_pair
        from apps.security.hashing import nin_hash as _nin_hash
        h = _nin_hash("CM1234567890AB")
        Member.objects.create(household=household, line_number=1, surname="X",
                              first_name="A", sex="1", nin_hash=h)
        Member.objects.create(household=household, line_number=2, surname="X",
                              first_name="B", sex="1", nin_hash=h)
        pair = discover_nin_pairs(actor="system")[0]
        decision = reject_pair(pair, actor="op", reason="not duplicates")
        with pytest.raises(MergeError, match="only MERGE"):
            reverse_merge_decision(decision, actor="rv", reason="r")


# --- US-S6-001 — reverse-merge surface (API + admin) -----------------------

class TestReverseMergeApi:
    """Per US-S6-001: POST /api/v1/ddup/merge-decisions/{id}/reverse/
    triggers the same reverse_merge_decision() service that S5-003
    shipped. Guards (window, double-reverse, reason) surface as 400."""

    def _make_merge(self, household, active_model):
        from apps.ddup.services import merge_member_pair
        from apps.security.hashing import nin_hash as _nin_hash
        h = _nin_hash("CM1234567890AB")
        Member.objects.create(household=household, line_number=1, surname="A",
                              first_name="X", sex="1", nin_hash=h, nin_last4="00AB")
        b = Member.objects.create(household=household, line_number=2, surname="B",
                                  first_name="Y", sex="1", nin_hash=h, nin_last4="00AB")
        pair = discover_nin_pairs(actor="system")[0]
        return merge_member_pair(pair, surviving_id=b.id,
                                 chosen_field_values={}, actor="op-1", note="")

    def test_reverse_via_api(self, household, active_model, django_user_model):
        from rest_framework.test import APIClient
        decision = self._make_merge(household, active_model)
        u = django_user_model.objects.create_user(
            username="reviewer", password="p", is_superuser=True,
        )
        c = APIClient()
        c.force_authenticate(user=u)
        r = c.post(
            f"/api/v1/ddup/merge-decisions/{decision.id}/reverse/",
            data={"actor": "reviewer-2", "reason": "id mismatch"},
            format="json",
        )
        assert r.status_code == 200, r.data
        assert r.data["reversed_at"] is not None
        assert r.data["reversed_by"] == "reviewer-2"
        assert "mismatch" in r.data["reversed_reason"]

    def test_reverse_api_400_outside_window(
        self, household, active_model, django_user_model,
    ):
        from datetime import timedelta

        from django.utils import timezone
        from rest_framework.test import APIClient
        decision = self._make_merge(household, active_model)
        decision.reverse_window_until = timezone.now() - timedelta(seconds=1)
        decision.save(update_fields=["reverse_window_until"])
        u = django_user_model.objects.create_user(
            username="late", password="p", is_superuser=True,
        )
        c = APIClient()
        c.force_authenticate(user=u)
        r = c.post(
            f"/api/v1/ddup/merge-decisions/{decision.id}/reverse/",
            data={"actor": "late", "reason": "too late"},
            format="json",
        )
        assert r.status_code == 400
        assert "window closed" in r.data["detail"]

    def test_reverse_api_requires_reason(
        self, household, active_model, django_user_model,
    ):
        from rest_framework.test import APIClient
        decision = self._make_merge(household, active_model)
        u = django_user_model.objects.create_user(
            username="lazy", password="p", is_superuser=True,
        )
        c = APIClient()
        c.force_authenticate(user=u)
        # Empty reason -> DRF serializer rejects (CharField required-non-blank).
        r = c.post(
            f"/api/v1/ddup/merge-decisions/{decision.id}/reverse/",
            data={"actor": "lazy", "reason": ""},
            format="json",
        )
        assert r.status_code == 400


class TestMergePairApi:
    """Per US-S14-001: POST /api/v1/ddup/match-pairs/{id}/merge/
    and /reject/ wrap the existing merge_member_pair + reject_pair
    services. Guards (dual-actor, non-pending pair, wrong survivor)
    surface as 400."""

    def _build_pending_pair(self, household):
        from apps.security.hashing import nin_hash as _nh
        h = _nh("CM1234567890AB")
        Member.objects.create(household=household, line_number=1, surname="A",
                              first_name="X", sex="1", nin_hash=h, nin_last4="00AB")
        b = Member.objects.create(household=household, line_number=2, surname="B",
                                  first_name="Y", sex="1", nin_hash=h, nin_last4="00AB")
        pair = discover_nin_pairs(actor="system")[0]
        return pair, b

    def test_merge_via_api(self, household, active_model, django_user_model):
        from rest_framework.test import APIClient
        pair, b = self._build_pending_pair(household)
        u = django_user_model.objects.create_user(
            username="reviewer", password="p", is_superuser=True,
        )
        c = APIClient()
        c.force_authenticate(user=u)
        r = c.post(
            f"/api/v1/ddup/match-pairs/{pair.id}/merge/",
            data={
                "surviving_id": b.id,
                "chosen_field_values": {"surname": "B", "telephone_1": "+256700000000"},
                "actor": "reviewer-2",
                "note": "decided via React Merge button",
            },
            format="json",
        )
        assert r.status_code == 200, r.data
        assert r.data["action"] == "merge"
        assert r.data["surviving_record_id"] == b.id
        # chosen_field_values on MergeDecision stores the raw chosen
        # dict (the "applied" {old, new} diff is internal to the merge
        # service for audit emission, not on the decision row).
        assert r.data["chosen_field_values"]["surname"] == "B"

    def test_merge_via_api_wrong_survivor_rejects(
        self, household, active_model, django_user_model,
    ):
        from rest_framework.test import APIClient
        pair, b = self._build_pending_pair(household)
        u = django_user_model.objects.create_user(
            username="reviewer", password="p", is_superuser=True,
        )
        c = APIClient()
        c.force_authenticate(user=u)
        r = c.post(
            f"/api/v1/ddup/match-pairs/{pair.id}/merge/",
            data={
                "surviving_id": "01OUTSIDETHEPAIR0000000000",
                "actor": "reviewer-2",
            },
            format="json",
        )
        assert r.status_code == 400
        assert "surviving_id" in r.data["detail"]

    def test_reject_via_api(self, household, active_model, django_user_model):
        from rest_framework.test import APIClient
        pair, _b = self._build_pending_pair(household)
        u = django_user_model.objects.create_user(
            username="reviewer", password="p", is_superuser=True,
        )
        c = APIClient()
        c.force_authenticate(user=u)
        r = c.post(
            f"/api/v1/ddup/match-pairs/{pair.id}/reject/",
            data={"actor": "reviewer-2", "reason": "different households"},
            format="json",
        )
        assert r.status_code == 200, r.data
        assert r.data["action"] == "reject"
        # Pair flipped to REJECTED.
        pair.refresh_from_db()
        from apps.ddup.models import PairStatus
        assert pair.status == PairStatus.REJECTED


class TestReverseMergeAdmin:
    """The admin bulk action wraps the same service so audit chain and
    guards are identical to the API surface."""

    @pytest.fixture
    def admin_client(self, db, django_user_model):
        from django.test import Client
        u = django_user_model.objects.create_user(
            username="reviewer-admin", password="p",
            is_staff=True, is_superuser=True,
        )
        c = Client()
        c.force_login(u)
        return c

    def test_bulk_reverse_flips_pair_back_to_pending(
        self, admin_client, household, active_model,
    ):
        from apps.ddup.services import merge_member_pair
        from apps.security.hashing import nin_hash as _nin_hash
        h = _nin_hash("CM1234567890AB")
        Member.objects.create(household=household, line_number=1, surname="A",
                              first_name="X", sex="1", nin_hash=h, nin_last4="00AB")
        b = Member.objects.create(household=household, line_number=2, surname="B",
                                  first_name="Y", sex="1", nin_hash=h, nin_last4="00AB")
        pair = discover_nin_pairs(actor="system")[0]
        decision = merge_member_pair(pair, surviving_id=b.id,
                                     chosen_field_values={}, actor="op-1", note="")
        r = admin_client.post("/admin/ddup/mergedecision/", data={
            "action": "admin_reverse_merge",
            "_selected_action": [decision.id],
        })
        assert r.status_code in (200, 302)
        decision.refresh_from_db()
        pair.refresh_from_db()
        assert decision.reversed_at is not None
        assert pair.status == PairStatus.PENDING

    def test_bulk_reverse_skips_non_merge_actions(
        self, admin_client, household, active_model,
    ):
        from apps.ddup.services import reject_pair
        from apps.security.hashing import nin_hash as _nin_hash
        h = _nin_hash("CM1234567890AB")
        Member.objects.create(household=household, line_number=1, surname="A",
                              first_name="X", sex="1", nin_hash=h)
        Member.objects.create(household=household, line_number=2, surname="B",
                              first_name="Y", sex="1", nin_hash=h)
        pair = discover_nin_pairs(actor="system")[0]
        decision = reject_pair(pair, actor="op", reason="not duplicates")
        admin_client.post("/admin/ddup/mergedecision/", data={
            "action": "admin_reverse_merge",
            "_selected_action": [decision.id],
        })
        decision.refresh_from_db()
        # REJECT decision unchanged — admin action skipped it.
        assert decision.reversed_at is None


# --- US-S7-003 — tier 3 probabilistic discovery ---------------------------


class TestModelVersionFeedbackCounters:
    """S10-002 — DdupModelVersion exposes live counters for the
    auto/manual merge × reverse cross-tab. An auto-merged pair that
    gets reversed is the strongest signal the threshold was wrong."""

    def _build_pair_for_merge(self, household, active_model, h):
        m1 = Member.objects.create(
            household=household, line_number=1, surname="X",
            first_name="A", sex="1", nin_hash=h,
        )
        # Second member needs to exist in the DB so discover_nin_pairs
        # picks them up as a pair; the variable is for clarity only.
        Member.objects.create(
            household=household, line_number=2, surname="X",
            first_name="B", sex="1", nin_hash=h,
        )
        from apps.ddup.services import discover_nin_pairs, merge_member_pair
        pair = discover_nin_pairs(actor="system")[0]
        return merge_member_pair(
            pair, surviving_id=m1.id, chosen_field_values={},
            actor="op", note="manual decision",
        ), pair

    def test_zero_state(self, db, active_model):
        assert active_model.auto_merge_count == 0
        assert active_model.manual_merge_count == 0
        assert active_model.auto_reverse_count == 0
        assert active_model.auto_reverse_rate is None  # 0/0 -> None

    def test_manual_merge_counted_as_manual(self, household, active_model):
        h = _hash("CM1234567890AB")
        self._build_pair_for_merge(household, active_model, h)
        active_model.refresh_from_db()
        assert active_model.manual_merge_count == 1
        assert active_model.auto_merge_count == 0

    def test_auto_merge_marker_picked_up(self, household, active_model):
        """A MergeDecision whose reason starts with the auto-merge
        marker counts as auto, not manual. The counter logic is what
        we test here; the full sweep behaviour is in
        TestAutoMergeHighConfidence above."""
        from apps.ddup.models import MergeAction
        from apps.ddup.services import discover_nin_pairs
        h = _hash("CM1234567890AB")
        m1 = Member.objects.create(
            household=household, line_number=1, surname="X",
            first_name="A", sex="1", nin_hash=h,
        )
        m2 = Member.objects.create(
            household=household, line_number=2, surname="X",
            first_name="B", sex="1", nin_hash=h,
        )
        pair = discover_nin_pairs(actor="system")[0]
        MergeDecision.objects.create(
            match_pair=pair, action=MergeAction.MERGE,
            surviving_record_id=m1.id, losing_record_id=m2.id,
            reason="auto-merge tier-3 composite=0.98 >= threshold 0.95",
            decided_by="ddup-auto-merge",
        )
        active_model.refresh_from_db()
        assert active_model.auto_merge_count == 1
        assert active_model.manual_merge_count == 0
        assert active_model.auto_reverse_rate == 0.0  # no reverses yet

    def test_reverse_count_separates_auto_and_manual(self, household, active_model):
        """Reverse a manual merge — auto_reverse_count stays 0,
        manual_reverse_count goes to 1."""
        from apps.ddup.services import reverse_merge_decision
        h = _hash("CM1234567890AB")
        decision, _pair = self._build_pair_for_merge(household, active_model, h)
        reverse_merge_decision(decision, actor="reviewer", reason="wrong match")
        active_model.refresh_from_db()
        assert active_model.manual_reverse_count == 1
        assert active_model.auto_reverse_count == 0

    def test_counters_exposed_in_api(self, db, active_model, django_user_model):
        from rest_framework.test import APIClient
        u = django_user_model.objects.create_user(
            username="su", password="p", is_superuser=True,
        )
        c = APIClient()
        c.force_authenticate(user=u)
        r = c.get(f"/api/v1/ddup/model-versions/{active_model.id}/")
        assert r.status_code == 200
        for key in ("auto_merge_count", "manual_merge_count",
                    "auto_reverse_count", "manual_reverse_count",
                    "auto_reverse_rate"):
            assert key in r.data, f"{key} missing from serializer output"
        # Empty state -> rate is null in JSON (None in Python).
        assert r.data["auto_reverse_rate"] is None

    def test_auto_reverse_rate_computed(self, household, active_model):
        """Plant two auto-merge decisions, mark one reversed —
        rate = 0.5. We write the MergeDecisions directly so the test
        focuses on the counter logic, not the merge pipeline."""
        from django.utils import timezone

        from apps.ddup.models import MatchPair, MergeAction

        h1 = _hash("CM1111111111AB")
        h2 = _hash("CM2222222222AB")
        # Pair 1: two members on h1.
        m1a = Member.objects.create(household=household, line_number=1,
                                     surname="A", first_name="X1", sex="1",
                                     nin_hash=h1)
        m1b = Member.objects.create(household=household, line_number=2,
                                     surname="A", first_name="X2", sex="1",
                                     nin_hash=h1)
        # Pair 2: two members on h2.
        m2a = Member.objects.create(household=household, line_number=3,
                                     surname="B", first_name="Y1", sex="1",
                                     nin_hash=h2)
        m2b = Member.objects.create(household=household, line_number=4,
                                     surname="B", first_name="Y2", sex="1",
                                     nin_hash=h2)
        pair1 = MatchPair.objects.create(
            record_type="member",
            record_a_id=min(m1a.id, m1b.id), record_b_id=max(m1a.id, m1b.id),
            tier=1, match_reason="nin", model_version=active_model,
        )
        pair2 = MatchPair.objects.create(
            record_type="member",
            record_a_id=min(m2a.id, m2b.id), record_b_id=max(m2a.id, m2b.id),
            tier=1, match_reason="nin", model_version=active_model,
        )
        MergeDecision.objects.create(
            match_pair=pair1, action=MergeAction.MERGE,
            surviving_record_id=m1a.id, losing_record_id=m1b.id,
            reason="auto-merge tier-3 composite=0.98",
            decided_by="bot",
            reversed_at=timezone.now(), reversed_by="reviewer",
        )
        MergeDecision.objects.create(
            match_pair=pair2, action=MergeAction.MERGE,
            surviving_record_id=m2a.id, losing_record_id=m2b.id,
            reason="auto-merge tier-3 composite=0.97",
            decided_by="bot",
        )
        active_model.refresh_from_db()
        assert active_model.auto_merge_count == 2
        assert active_model.auto_reverse_count == 1
        assert active_model.auto_reverse_rate == 0.5


class TestMatchPairAdminScoresTable:
    """S9-001 — admin readonly display renders per_field_scores as a
    small coloured table. Mirrors the corridor signal: green ≥0.9,
    amber 0.5-0.9, red <0.5."""

    def _make_tier3_pair_with_scores(self, household, active_model, scores):
        from apps.ddup.models import MatchPair, PairStatus
        m1 = Member.objects.create(household=household, line_number=1,
                                    surname="OKELLO", first_name="X", sex="1")
        m2 = Member.objects.create(household=household, line_number=2,
                                    surname="OKELLO", first_name="Y", sex="1")
        a, b = sorted([m1.id, m2.id])
        return MatchPair.objects.create(
            record_type="member", record_a_id=a, record_b_id=b,
            tier=3, match_reason="probabilistic",
            model_version=active_model,
            composite_score="0.920",
            per_field_scores=scores,
            status=PairStatus.PENDING,
        )

    def test_scores_table_renders_each_field(self, household, active_model):
        from apps.ddup.admin import MatchPairAdmin
        pair = self._make_tier3_pair_with_scores(
            household, active_model,
            {"surname": 1.0, "first_name": 0.94,
             "date_of_birth": 1.0, "sex": 1.0, "village": 1.0},
        )
        from apps.ddup.models import MatchPair
        a = MatchPairAdmin(MatchPair, admin_site=None)
        html = str(a.scores_table(pair))
        # Each field shows on its own row.
        for field in ("surname", "first_name", "date_of_birth", "sex", "village"):
            assert field in html
        # Scores formatted to 3 dp.
        assert "1.000" in html
        assert "0.940" in html

    def test_high_score_uses_green_colour(self, household, active_model):
        from apps.ddup.admin import MatchPairAdmin
        pair = self._make_tier3_pair_with_scores(
            household, active_model, {"surname": 0.95},
        )
        from apps.ddup.models import MatchPair
        html = str(MatchPairAdmin(MatchPair, admin_site=None).scores_table(pair))
        # Green hex from _score_colour.
        assert "#198754" in html

    def test_mid_score_uses_amber_colour(self, household, active_model):
        from apps.ddup.admin import MatchPairAdmin
        pair = self._make_tier3_pair_with_scores(
            household, active_model, {"first_name": 0.75},
        )
        from apps.ddup.models import MatchPair
        html = str(MatchPairAdmin(MatchPair, admin_site=None).scores_table(pair))
        assert "#b87410" in html

    def test_low_score_uses_red_colour(self, household, active_model):
        from apps.ddup.admin import MatchPairAdmin
        pair = self._make_tier3_pair_with_scores(
            household, active_model, {"date_of_birth": 0.0},
        )
        from apps.ddup.models import MatchPair
        html = str(MatchPairAdmin(MatchPair, admin_site=None).scores_table(pair))
        assert "#a93226" in html

    def test_empty_scores_renders_placeholder(self, household, active_model):
        from apps.ddup.admin import MatchPairAdmin
        pair = self._make_tier3_pair_with_scores(
            household, active_model, {},
        )
        from apps.ddup.models import MatchPair
        html = str(MatchPairAdmin(MatchPair, admin_site=None).scores_table(pair))
        assert "no per-field scores recorded" in html


class TestSimilarityPrimitives:
    """Self-contained similarity functions in apps.ddup.similarity.
    These are the building blocks composite_score combines into a
    weighted match score."""

    def test_jaro_winkler_exact_match(self):
        from apps.ddup.similarity import jaro_winkler
        assert jaro_winkler("OKELLO", "OKELLO") == 1.0

    def test_jaro_winkler_close_variants(self):
        """OCHELLO vs OKELLO should score high — same length, single
        substitution, common prefix."""
        from apps.ddup.similarity import jaro_winkler
        assert jaro_winkler("OCHELLO", "OKELLO") > 0.85

    def test_jaro_winkler_empty_strings(self):
        from apps.ddup.similarity import jaro_winkler
        assert jaro_winkler("", "") == 1.0
        assert jaro_winkler("X", "") == 0.0
        assert jaro_winkler("", "Y") == 0.0

    def test_year_proximity_same_year(self):
        from datetime import date

        from apps.ddup.similarity import year_proximity
        assert year_proximity(date(1980, 1, 1), date(1980, 12, 31)) == 1.0

    def test_year_proximity_one_year_apart(self):
        from datetime import date

        from apps.ddup.similarity import year_proximity
        # max_years=2 -> 1 year apart = 0.5
        assert year_proximity(date(1980, 1, 1), date(1981, 1, 1)) == 0.5

    def test_year_proximity_missing_dob_yields_zero(self):
        from datetime import date

        from apps.ddup.similarity import year_proximity
        assert year_proximity(None, date(1980, 1, 1)) == 0.0
        assert year_proximity(date(1980, 1, 1), None) == 0.0

    def test_exact_treats_empty_as_missing(self):
        from apps.ddup.similarity import exact
        # Two empties should NOT be a match — would collapse blank villages.
        assert exact("", "") == 0.0
        assert exact(None, None) == 0.0
        assert exact("V1", "V1") == 1.0
        assert exact("V1", "V2") == 0.0

    def test_composite_score_weighted_average(self):
        from apps.ddup.similarity import composite_score
        # 0.5 weight at 1.0 + 0.5 weight at 0.0 = 0.5
        assert composite_score([(0.5, 1.0), (0.5, 0.0)]) == 0.5
        # Empty -> 0.0 not divide-by-zero
        assert composite_score([]) == 0.0
        # All-zero weights -> 0.0 defensively
        assert composite_score([(0, 0.5), (0, 1.0)]) == 0.0


class TestProbabilisticDiscovery:
    """Tier 3: composite-score matching within village blocks.
    Different households (so neither NIN nor phone tier 1/2 fires)
    but same village + very similar names + same DOB year + same sex
    should cross the 0.85 default threshold."""

    @pytest.fixture
    def two_households_same_village(self, db, geo):
        # Two households sharing the same village node from `geo`.
        h1 = Household.objects.create(
            region=geo["r"], sub_region=geo["sr"], district=geo["d"],
            county=geo["c"], sub_county=geo["sc"], parish=geo["p"],
            village=geo["v"], urban_rural="2",
        )
        h2 = Household.objects.create(
            region=geo["r"], sub_region=geo["sr"], district=geo["d"],
            county=geo["c"], sub_county=geo["sc"], parish=geo["p"],
            village=geo["v"], urban_rural="2",
        )
        return h1, h2

    @pytest.fixture
    def other_village_household(self, db, geo):
        # A second village, same parish — for the blocking test.
        v2 = GeographicUnit.objects.create(
            level="village", code="T-V2", name="other-village",
            parent=geo["p"], effective_from=date(2026, 1, 1),
        )
        return Household.objects.create(
            region=geo["r"], sub_region=geo["sr"], district=geo["d"],
            county=geo["c"], sub_county=geo["sc"], parish=geo["p"],
            village=v2, urban_rural="2",
        )

    def test_high_similarity_pair_within_village(
        self, two_households_same_village, active_model,
    ):
        from apps.ddup.services import discover_probabilistic_pairs
        h1, h2 = two_households_same_village
        m1 = Member.objects.create(
            household=h1, line_number=1, surname="OKELLO",
            first_name="JAMES", sex="1", date_of_birth=date(1980, 1, 1),
        )
        m2 = Member.objects.create(
            household=h2, line_number=1, surname="OKELLO",
            first_name="JAMES", sex="1", date_of_birth=date(1980, 6, 15),
        )
        created = discover_probabilistic_pairs(actor="system")
        assert len(created) == 1
        pair = created[0]
        assert pair.tier == 3
        assert pair.match_reason == "probabilistic"
        # Composite is recorded and at/above threshold.
        assert pair.composite_score is not None
        assert float(pair.composite_score) >= 0.85
        # Per-field breakdown stored for reviewer transparency.
        assert pair.per_field_scores["surname"] == 1.0
        assert pair.per_field_scores["village"] == 1.0
        # Both members in scope.
        assert {pair.record_a_id, pair.record_b_id} == {m1.id, m2.id}

    def test_low_similarity_pair_skipped(
        self, two_households_same_village, active_model,
    ):
        from apps.ddup.services import discover_probabilistic_pairs
        h1, h2 = two_households_same_village
        Member.objects.create(
            household=h1, line_number=1, surname="OKELLO",
            first_name="JAMES", sex="1", date_of_birth=date(1980, 1, 1),
        )
        Member.objects.create(
            household=h2, line_number=1, surname="NAKATO",
            first_name="ALICE", sex="2", date_of_birth=date(1995, 1, 1),
        )
        assert discover_probabilistic_pairs(actor="system") == []

    def test_village_blocking_prevents_cross_village_pair(
        self, two_households_same_village, other_village_household,
        active_model,
    ):
        """Two identical-looking members in different villages should
        NOT pair via tier 3 — the blocking is by village_id."""
        from apps.ddup.services import discover_probabilistic_pairs
        h1, _ = two_households_same_village
        h_other = other_village_household
        Member.objects.create(
            household=h1, line_number=1, surname="OKELLO",
            first_name="JAMES", sex="1", date_of_birth=date(1980, 1, 1),
        )
        Member.objects.create(
            household=h_other, line_number=1, surname="OKELLO",
            first_name="JAMES", sex="1", date_of_birth=date(1980, 1, 1),
        )
        # Each village now has 1 member — no within-village comparison
        # possible.
        assert discover_probabilistic_pairs(actor="system") == []

    def test_tier1_pair_not_redisco_as_tier3(
        self, two_households_same_village, active_model,
    ):
        """Same NIN -> tier 1 wins; the (a,b) uniqueness constraint
        blocks a tier-3 row for the same pair."""
        from apps.ddup.services import (
            discover_nin_pairs,
            discover_probabilistic_pairs,
        )
        h1, h2 = two_households_same_village
        h = _hash("CM1234567890AB")
        Member.objects.create(
            household=h1, line_number=1, surname="OKELLO",
            first_name="JAMES", sex="1", date_of_birth=date(1980, 1, 1),
            nin_hash=h,
        )
        Member.objects.create(
            household=h2, line_number=1, surname="OKELLO",
            first_name="JAMES", sex="1", date_of_birth=date(1980, 1, 1),
            nin_hash=h,
        )
        tier1 = discover_nin_pairs(actor="system")
        tier3 = discover_probabilistic_pairs(actor="system")
        assert len(tier1) == 1 and tier1[0].tier == 1
        assert tier3 == []  # already represented as tier 1

    def test_idempotent(self, two_households_same_village, active_model):
        from apps.ddup.services import discover_probabilistic_pairs
        h1, h2 = two_households_same_village
        for hh in (h1, h2):
            Member.objects.create(
                household=hh, line_number=1, surname="OKELLO",
                first_name="JAMES", sex="1", date_of_birth=date(1980, 1, 1),
            )
        first = discover_probabilistic_pairs(actor="system")
        second = discover_probabilistic_pairs(actor="system")
        assert len(first) == 1
        assert second == []

    def test_threshold_overridable_via_model_config(
        self, two_households_same_village, db,
    ):
        """A more permissive threshold should pull in pairs that the
        default 0.85 misses."""
        from apps.ddup.services import (
            activate_model_version,
            discover_probabilistic_pairs,
        )
        permissive = DdupModelVersion.objects.create(
            version=2, author="archer",
            config={"tier3": {"threshold": 0.5}},
        )
        activate_model_version(permissive, approver="bob")
        h1, h2 = two_households_same_village
        # Names diverge enough to score < 0.85 but probably > 0.5.
        Member.objects.create(
            household=h1, line_number=1, surname="OKELLO",
            first_name="JAMES", sex="1", date_of_birth=date(1980, 1, 1),
        )
        Member.objects.create(
            household=h2, line_number=1, surname="OKELO",
            first_name="JAMS", sex="1", date_of_birth=date(1985, 1, 1),
        )
        created = discover_probabilistic_pairs(actor="system")
        assert len(created) == 1


# --- US-S8-002 — auto-merge high-confidence tier-3 pairs ------------------


class TestAutoMergeHighConfidence:
    """Tier-3 pairs above the auto_merge_threshold (default 0.95)
    merge without manual review. Below-threshold pairs stay PENDING."""

    def _make_two_high_confidence_members(self, db, geo):
        # Two identical-looking members in different households, same
        # village -> tier-3 composite will be very high (~1.0).
        h1 = Household.objects.create(
            region=geo["r"], sub_region=geo["sr"], district=geo["d"],
            county=geo["c"], sub_county=geo["sc"], parish=geo["p"],
            village=geo["v"], urban_rural="2",
        )
        h2 = Household.objects.create(
            region=geo["r"], sub_region=geo["sr"], district=geo["d"],
            county=geo["c"], sub_county=geo["sc"], parish=geo["p"],
            village=geo["v"], urban_rural="2",
        )
        m1 = Member.objects.create(
            household=h1, line_number=1, surname="OKELLO",
            first_name="JAMES", sex="1", date_of_birth=date(1980, 1, 1),
        )
        m2 = Member.objects.create(
            household=h2, line_number=1, surname="OKELLO",
            first_name="JAMES", sex="1", date_of_birth=date(1980, 1, 1),
        )
        return m1, m2

    def test_above_threshold_pair_auto_merges(self, db, geo, active_model):
        from apps.ddup.services import (
            auto_merge_high_confidence_pairs,
            discover_probabilistic_pairs,
        )
        m1, m2 = self._make_two_high_confidence_members(db, geo)
        discover_probabilistic_pairs(actor="system")
        # Identical attributes -> composite ~= 1.0, above 0.95 default.
        counts = auto_merge_high_confidence_pairs()
        assert counts["merged"] == 1
        # Older ULID (m1, created first) is the survivor.
        m1.refresh_from_db()
        m2.refresh_from_db()
        assert m1.is_deleted is False
        assert m2.is_deleted is True
        assert m2.merged_into_id == m1.id

    def test_below_threshold_pair_stays_pending(self, db, geo):
        """Permissive threshold pulls in mid-similarity pairs but
        keeps the auto-merge cutoff high — they should stay PENDING."""
        from apps.ddup.services import (
            activate_model_version,
            auto_merge_high_confidence_pairs,
            discover_probabilistic_pairs,
        )
        permissive = DdupModelVersion.objects.create(
            version=3, author="archer",
            config={"tier3": {"threshold": 0.5,
                              "auto_merge_threshold": 0.95}},
        )
        activate_model_version(permissive, approver="bob")
        h1 = Household.objects.create(
            region=geo["r"], sub_region=geo["sr"], district=geo["d"],
            county=geo["c"], sub_county=geo["sc"], parish=geo["p"],
            village=geo["v"], urban_rural="2",
        )
        h2 = Household.objects.create(
            region=geo["r"], sub_region=geo["sr"], district=geo["d"],
            county=geo["c"], sub_county=geo["sc"], parish=geo["p"],
            village=geo["v"], urban_rural="2",
        )
        Member.objects.create(
            household=h1, line_number=1, surname="OKELLO",
            first_name="JAMES", sex="1", date_of_birth=date(1980, 1, 1),
        )
        Member.objects.create(
            household=h2, line_number=1, surname="OKELO",
            first_name="JAMS", sex="1", date_of_birth=date(1985, 1, 1),
        )
        created = discover_probabilistic_pairs(actor="system")
        assert len(created) == 1
        # Composite is in [0.5, 0.95) -> stays PENDING after sweep.
        counts = auto_merge_high_confidence_pairs()
        assert counts == {"processed": 0, "merged": 0, "skipped": 0}
        created[0].refresh_from_db()
        assert created[0].status == PairStatus.PENDING

    def test_emits_auto_merge_audit_event(self, db, geo, active_model):
        from apps.ddup.services import (
            auto_merge_high_confidence_pairs,
            discover_probabilistic_pairs,
        )
        m1, m2 = self._make_two_high_confidence_members(db, geo)
        discover_probabilistic_pairs(actor="system")
        auto_merge_high_confidence_pairs()
        # Two audit events for the pair now: merge (from merge_member_pair)
        # AND auto_merge (the additional distinguishing tag).
        actions = list(
            AuditEvent.objects.filter(
                entity_type="match_pair",
            ).values_list("action", flat=True),
        )
        assert "auto_merge" in actions

    def test_threshold_overridable_via_model_config(self, db, geo):
        """A model-version that lowers auto_merge_threshold should
        pull in pairs the 0.95 default would skip."""
        from apps.ddup.services import (
            activate_model_version,
            auto_merge_high_confidence_pairs,
            discover_probabilistic_pairs,
        )
        v = DdupModelVersion.objects.create(
            version=4, author="archer",
            config={"tier3": {"threshold": 0.5,
                              "auto_merge_threshold": 0.6}},
        )
        activate_model_version(v, approver="bob")
        h1 = Household.objects.create(
            region=geo["r"], sub_region=geo["sr"], district=geo["d"],
            county=geo["c"], sub_county=geo["sc"], parish=geo["p"],
            village=geo["v"], urban_rural="2",
        )
        h2 = Household.objects.create(
            region=geo["r"], sub_region=geo["sr"], district=geo["d"],
            county=geo["c"], sub_county=geo["sc"], parish=geo["p"],
            village=geo["v"], urban_rural="2",
        )
        Member.objects.create(
            household=h1, line_number=1, surname="OKELLO",
            first_name="JAMES", sex="1", date_of_birth=date(1980, 1, 1),
        )
        Member.objects.create(
            household=h2, line_number=1, surname="OKELO",
            first_name="JAMS", sex="1", date_of_birth=date(1985, 1, 1),
        )
        discover_probabilistic_pairs(actor="system")
        counts = auto_merge_high_confidence_pairs()
        # Permissive auto-threshold should pick this one up.
        assert counts["merged"] == 1

    def test_idempotent(self, db, geo, active_model):
        from apps.ddup.services import (
            auto_merge_high_confidence_pairs,
            discover_probabilistic_pairs,
        )
        self._make_two_high_confidence_members(db, geo)
        discover_probabilistic_pairs(actor="system")
        first = auto_merge_high_confidence_pairs()
        second = auto_merge_high_confidence_pairs()
        assert first["merged"] == 1
        # Already MERGED -> excluded from the second sweep.
        assert second == {"processed": 0, "merged": 0, "skipped": 0}

    def test_celery_task_runs(self, db, geo, active_model):
        from apps.ddup.services import discover_probabilistic_pairs
        from apps.ddup.tasks import auto_merge_high_confidence_pairs_task
        self._make_two_high_confidence_members(db, geo)
        discover_probabilistic_pairs(actor="system")
        result = auto_merge_high_confidence_pairs_task.run()
        assert result["merged"] == 1

    def test_beat_schedule_includes_auto_merge(self):
        from nsr_mis.celery import app
        tasks = {entry["task"] for entry in app.conf.beat_schedule.values()}
        assert (
            "apps.ddup.tasks.auto_merge_high_confidence_pairs_task"
            in tasks
        )


# --- US-S11-005 — threshold calibration ----------------------------------


class TestThresholdCalibration:
    """`clone_with_threshold_delta` must (a) mint a new DRAFT row with
    the updated config, (b) preserve the rest of the source config,
    (c) clamp to [0.50, 1.00], and (d) emit an audit event."""

    def _make_v1(self, *, threshold=0.95):
        return DdupModelVersion.objects.create(
            version=1,
            config={"tier3": {"auto_merge_threshold": threshold,
                              "weights": {"surname": 0.30, "first_name": 0.30}}},
            author="alice",
        )

    def test_nudge_up_creates_new_draft(self, db):
        from apps.ddup.services import clone_with_threshold_delta
        v1 = self._make_v1(threshold=0.85)
        draft = clone_with_threshold_delta(
            v1, delta=0.05, actor="dpo-bot", reason="ceiling breach",
        )
        assert draft.version == 2
        assert draft.status == ModelStatus.DRAFT
        assert draft.config["tier3"]["auto_merge_threshold"] == pytest.approx(0.90)
        # Other config fields preserved.
        assert draft.config["tier3"]["weights"]["surname"] == 0.30

    def test_nudge_down_creates_new_draft(self, db):
        from apps.ddup.services import clone_with_threshold_delta
        v1 = self._make_v1(threshold=0.95)
        draft = clone_with_threshold_delta(
            v1, delta=-0.05, actor="dpo-bot", reason="backlog",
        )
        assert draft.config["tier3"]["auto_merge_threshold"] == pytest.approx(0.90)

    def test_clamp_at_ceiling(self, db):
        from apps.ddup.services import clone_with_threshold_delta
        v1 = self._make_v1(threshold=1.00)
        with pytest.raises(DdupApprovalError, match="boundary"):
            clone_with_threshold_delta(
                v1, delta=0.05, actor="dpo-bot", reason="x",
            )

    def test_clamp_at_floor(self, db):
        from apps.ddup.services import clone_with_threshold_delta
        v1 = self._make_v1(threshold=0.50)
        with pytest.raises(DdupApprovalError, match="boundary"):
            clone_with_threshold_delta(
                v1, delta=-0.05, actor="dpo-bot", reason="x",
            )

    def test_emits_calibrate_audit_event(self, db):
        from apps.ddup.services import clone_with_threshold_delta
        v1 = self._make_v1(threshold=0.85)
        clone_with_threshold_delta(
            v1, delta=0.05, actor="dpo-bot", reason="ceiling breach",
        )
        events = AuditEvent.objects.filter(action="calibrate")
        assert events.count() == 1
        e = events.first()
        assert e.entity_type == "ddup_model_version"
        # field_changes records the before/after threshold.
        changes = e.field_changes
        assert changes["auto_merge_threshold_before"] == 0.85
        assert changes["auto_merge_threshold_after"] == pytest.approx(0.90)

    def test_new_draft_requires_separate_activation(self, db):
        """The drafted clone is NOT auto-activated — AC-DDUP-MODEL-
        VERSION dual-approval still applies."""
        from apps.ddup.services import clone_with_threshold_delta
        v1 = self._make_v1(threshold=0.85)
        activate_model_version(v1, approver="bob")
        v1.refresh_from_db()
        draft = clone_with_threshold_delta(
            v1, delta=0.05, actor="dpo-bot", reason="x",
        )
        # v1 still active; draft is DRAFT.
        v1.refresh_from_db()
        assert v1.status == ModelStatus.ACTIVE
        assert draft.status == ModelStatus.DRAFT

    def test_version_number_increments_from_max(self, db):
        from apps.ddup.services import clone_with_threshold_delta
        DdupModelVersion.objects.create(
            version=1, config={"tier3": {"auto_merge_threshold": 0.85}},
            author="alice",
        )
        v5 = DdupModelVersion.objects.create(
            version=5, config={"tier3": {"auto_merge_threshold": 0.85}},
            author="alice",
        )
        draft = clone_with_threshold_delta(
            v5, delta=0.05, actor="dpo-bot", reason="x",
        )
        assert draft.version == 6
