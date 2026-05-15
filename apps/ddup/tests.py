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
        urban_rural="rural",
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
                                   first_name="One", sex="M", nin_hash=h)
        m2 = Member.objects.create(household=household, line_number=2, surname="B",
                                   first_name="Two", sex="F", nin_hash=h)
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
                              sex="M", nin_hash=h)
        Member.objects.create(household=household, line_number=2, surname="B", first_name="Two",
                              sex="F", nin_hash=h)
        first = discover_nin_pairs(actor="system")
        second = discover_nin_pairs(actor="system")
        assert len(first) == 1
        assert second == []

    def test_three_way_creates_three_pairs(self, household, active_model):
        h = _hash("CM1234567890AB")
        for i in range(3):
            Member.objects.create(household=household, line_number=i + 1,
                                  surname=f"S{i}", first_name=f"F{i}", sex="M", nin_hash=h)
        created = discover_nin_pairs(actor="system")
        assert len(created) == 3  # 3-choose-2

    def test_soft_deleted_member_ignored(self, household, active_model):
        h = _hash("CM1234567890AB")
        Member.objects.create(household=household, line_number=1, surname="A", first_name="One",
                              sex="M", nin_hash=h)
        Member.objects.create(household=household, line_number=2, surname="B",
                              first_name="Two", sex="F", nin_hash=h, is_deleted=True)
        created = discover_nin_pairs(actor="system")
        assert created == []

    def test_no_nin_hash_excluded(self, household, active_model):
        Member.objects.create(household=household, line_number=1, surname="A", first_name="One",
                              sex="M", nin_hash=None)
        Member.objects.create(household=household, line_number=2, surname="B", first_name="Two",
                              sex="F", nin_hash=None)
        assert discover_nin_pairs(actor="system") == []


# --- AC-DDUP-MERGE-COMMIT ---------------------------------------------------

class TestMergeCommit:
    def _build_pair(self, household):
        h = _hash("CM1234567890AB")
        a = Member.objects.create(household=household, line_number=1, surname="OLDsurname",
                                  first_name="James", sex="M", nin_hash=h, nin_last4="00AB",
                                  telephone_1="+256700000001")
        b = Member.objects.create(household=household, line_number=2, surname="Okot",
                                  first_name="James", sex="M", nin_hash=h, nin_last4="00AB",
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
                              sex="M", nin_hash=h)
        Member.objects.create(household=household, line_number=2, surname="B", first_name="Two",
                              sex="F", nin_hash=h)
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
                              sex="M", nin_hash=h)
        Member.objects.create(household=household, line_number=2, surname="B", first_name="Two",
                              sex="F", nin_hash=h)
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
                              sex="M", telephone_1="+256700000001")
        Member.objects.create(household=household, line_number=2, surname="B", first_name="Two",
                              sex="F", telephone_1="0700000001")  # equivalent normalised
        created = discover_phone_pairs(actor="system")
        assert len(created) == 1
        assert created[0].tier == 2
        assert created[0].match_reason == "phone"

    def test_unparseable_phone_excluded(self, household, active_model):
        Member.objects.create(household=household, line_number=1, surname="A", first_name="One",
                              sex="M", telephone_1="abc")
        Member.objects.create(household=household, line_number=2, surname="B", first_name="Two",
                              sex="F", telephone_1="abc")
        assert discover_phone_pairs(actor="system") == []

    def test_idempotent(self, household, active_model):
        Member.objects.create(household=household, line_number=1, surname="A", first_name="One",
                              sex="M", telephone_1="+256700000001")
        Member.objects.create(household=household, line_number=2, surname="B", first_name="Two",
                              sex="F", telephone_1="+256700000001")
        first = discover_phone_pairs(actor="system")
        second = discover_phone_pairs(actor="system")
        assert len(first) == 1 and second == []

    def test_tier1_pair_not_redisco_as_tier2(self, household, active_model):
        # Same NIN AND same phone → tier 1 wins; the (a,b) uniqueness
        # constraint blocks a second tier-2 row for the same pair.
        h = _hash("CM1234567890AB")
        Member.objects.create(household=household, line_number=1, surname="A", first_name="One",
                              sex="M", nin_hash=h, telephone_1="+256700000001")
        Member.objects.create(household=household, line_number=2, surname="B", first_name="Two",
                              sex="F", nin_hash=h, telephone_1="+256700000001")
        tier1 = discover_nin_pairs(actor="system")
        tier2 = discover_phone_pairs(actor="system")
        assert len(tier1) == 1 and tier1[0].tier == 1
        assert tier2 == []  # already represented as a tier-1 pair
