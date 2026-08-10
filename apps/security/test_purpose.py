"""Purpose limitation (G2 / US-014, first half).

The audit trail could say who read what and when, but not *why* — the question
DPPA 2019 purpose limitation turns on, and the attribute that separates ABAC
from scope-bounded RBAC.

The purpose is written twice on purpose: into `reason`, which is inside the
trigger's hashed payload and is therefore the tamper-evident record, and into
an indexed `purpose` column, which is what makes "every access under RESEARCH"
a real query. These tests pin both, and pin that the vocabulary stays the
consent catalogue rather than a second list.
"""

import pytest

from apps.security.audit import emit
from apps.security.models import AuditEvent
from apps.security.purpose import known_purpose_codes, resolve_purpose


class _View:
    """Stand-in for a viewset; only the declaration attributes matter."""

    def __init__(self, purpose=None, mapping=None, action=None):
        if purpose is not None:
            self.access_purpose = purpose
        if mapping is not None:
            self.access_purpose_map = mapping
        self.action = action


class TestResolution:

    def test_declared_purpose_is_used(self):
        assert resolve_purpose(None, _View(purpose="REFERRAL")) == "REFERRAL"

    def test_undeclared_is_empty_not_an_error(self):
        """A missing purpose is permitted — forcing every surface to name one
        would produce fictions rather than evidence."""
        assert resolve_purpose(None, _View()) == ""

    def test_per_action_map_wins(self):
        v = _View(purpose="REFERRAL", mapping={"export": "RESEARCH"},
                  action="export")
        assert resolve_purpose(None, v) == "RESEARCH"

    def test_map_falls_through_for_other_actions(self):
        v = _View(purpose="REFERRAL", mapping={"export": "RESEARCH"},
                  action="list")
        assert resolve_purpose(None, v) == "REFERRAL"

    def test_explicit_blank_abstains(self):
        assert resolve_purpose(None, _View(purpose="")) == ""


@pytest.mark.django_db
class TestAuditRecordsThePurpose:

    def test_purpose_lands_in_the_indexed_column(self):
        e = emit("read", "household", "H1", actor="op", purpose="RESEARCH")
        assert AuditEvent.objects.get(pk=e.pk).purpose == "RESEARCH"

    def test_purpose_is_also_inside_the_hashed_reason(self):
        """The column sits OUTSIDE the trigger's payload, so it is not
        tamper-evident on its own. `reason` is inside it — that is where the
        evidence lives; the column is a denormalisation for querying."""
        e = emit("read", "household", "H2", actor="op", purpose="RESEARCH")
        assert "purpose=RESEARCH" in AuditEvent.objects.get(pk=e.pk).reason

    def test_existing_reason_is_preserved(self):
        e = emit("read", "household", "H3", actor="op",
                 purpose="ELIGIBILITY", reason="page=2 size=25")
        row = AuditEvent.objects.get(pk=e.pk)
        assert "purpose=ELIGIBILITY" in row.reason
        assert "page=2" in row.reason

    def test_no_purpose_leaves_both_clean(self):
        e = emit("read", "household", "H4", actor="op", reason="page=1")
        row = AuditEvent.objects.get(pk=e.pk)
        assert row.purpose == ""
        assert "purpose=" not in row.reason

    def test_the_column_is_queryable(self):
        emit("read", "household", "H5", actor="op", purpose="RESEARCH")
        emit("read", "household", "H6", actor="op", purpose="ELIGIBILITY")
        assert AuditEvent.objects.filter(purpose="RESEARCH").count() == 1


@pytest.mark.django_db
class TestVocabularyIsTheConsentCatalogue:

    def test_declared_purposes_are_real_codes(self):
        """A typo would attribute access to a purpose nobody approved, which
        reads as evidence and is not."""
        known = known_purpose_codes()
        assert known, "the ConsentPurpose catalogue should be seeded"
        for code in ("REFERRAL", "GRIEVANCE_CONTACT", "ELIGIBILITY"):
            assert code in known

    def test_the_system_check_passes_as_shipped(self):
        from apps.security.checks import check_access_purposes_are_known
        assert check_access_purposes_are_known(None) == []

    def test_the_check_catches_an_unknown_code(self, monkeypatch):
        """A check that cannot fail is not a check."""
        from apps.security import checks as c

        monkeypatch.setattr(
            "apps.security.purpose.known_purpose_codes", lambda: {"ONLY_THIS"})
        errors = c.check_access_purposes_are_known(None)
        assert [e.id for e in errors] == ["security.E006"]
        assert "REFERRAL" in errors[0].msg


@pytest.mark.django_db
class TestDeclarationsOnRealViewsets:

    @pytest.mark.parametrize("dotted,expected", [
        ("apps.referral.api.ReferralViewSet", "REFERRAL"),
        ("apps.referral.api.ProgrammeEnrolmentViewSet", "REFERRAL"),
        ("apps.grievance.api.GrievanceViewSet", "GRIEVANCE_CONTACT"),
        ("apps.pmt.api.PMTResultViewSet", "ELIGIBILITY"),
    ])
    def test_viewset_declares_its_purpose(self, dotted, expected):
        module_path, cls_name = dotted.rsplit(".", 1)
        module = __import__(module_path, fromlist=[cls_name])
        assert getattr(module, cls_name).access_purpose == expected

    def test_household_reads_stay_unattributed(self):
        """Deliberate: the core case-management read serves several purposes at
        once and its lawful basis is not consent, so attributing every read to
        one code would be a fiction."""
        from apps.data_management.api import HouseholdViewSet
        assert getattr(HouseholdViewSet, "access_purpose", "") == ""
