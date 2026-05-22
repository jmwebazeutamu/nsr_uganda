"""Programme lifecycle + sign-off tests (US-180 / US-182).

Mirrors the no-self-approve coverage in
apps.update_workflow.tests.TestNoSelfApprove and the multi-step
sign-off coverage in apps.partners.test_dsa_signature. Every
transition through the lifecycle service is exercised here.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.partners.models import (
    Partner,
    Programme,
    ProgrammeSignOff,
)
from apps.partners.services import programme_lifecycle
from apps.partners.services.programme_lifecycle import (
    ACTIVE,
    CLOSING,
    DRAFT,
    PENDING_APPROVAL,
    SUSPENDED,
    ProgrammeLifecycleError,
)
from apps.reference_data.services import clear_resolver_cache


@pytest.fixture(autouse=True)
def _flush_choice_cache():
    clear_resolver_cache()
    yield
    clear_resolver_cache()


@pytest.fixture
def api(db):
    user_cls = get_user_model()
    u = user_cls.objects.create_superuser(username="prog-lifecycle", password="p")
    c = APIClient()
    c.force_authenticate(user=u)
    return c


@pytest.fixture
def partner(db):
    return Partner.objects.create(code="OPM", name="OPM")


@pytest.fixture
def draft_programme(db, partner):
    return Programme.objects.create(
        partner=partner,
        code="TEST-1",
        name="Test Programme",
        kind="cash_transfer",
        status=DRAFT,
        created_by="florence",
    )


@pytest.fixture
def emails():
    return {
        "nsr_coordinator_email": "coordinator@nsr.go.ug",
        "partner_steward_email": "steward@opm.go.ug",
        "dpo_email":             "dpo@nsr.go.ug",
        "director_email":        "director@nsr.go.ug",
    }


def _walk_to_active(programme, emails, *, last_signer_offset=0):
    """Sign all four steps with distinct approvers and return the
    programme refreshed from the DB. Useful as a setup helper for
    suspend / close tests."""
    role_email = [
        emails["nsr_coordinator_email"],
        emails["partner_steward_email"],
        emails["dpo_email"],
        emails["director_email"],
    ]
    for step_idx, email in enumerate(role_email, start=1):
        programme_lifecycle.sign_step(
            programme, step_idx, actor_email=email, note=f"step{step_idx}",
        )
    programme.refresh_from_db()
    return programme


# ───────────────────────────────────────────────────────────────
# submit_for_signoff
# ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestSubmitForSignoff:

    def test_creates_four_pending_rows_and_flips_to_pending_approval(
        self, draft_programme, emails,
    ):
        programme_lifecycle.submit_for_signoff(
            draft_programme, actor="florence", **emails,
        )
        draft_programme.refresh_from_db()
        assert draft_programme.status == PENDING_APPROVAL
        rows = list(
            ProgrammeSignOff.objects.filter(
                programme=draft_programme,
                revision=draft_programme.current_revision,
            ).order_by("step"),
        )
        assert len(rows) == 4
        assert [r.step for r in rows] == [1, 2, 3, 4]
        assert all(r.status == ProgrammeSignOff.PENDING for r in rows)
        assert [r.expected_role for r in rows] == [
            ProgrammeSignOff.ROLE_NSR_COORDINATOR,
            ProgrammeSignOff.ROLE_PARTNER_STEWARD,
            ProgrammeSignOff.ROLE_DPO,
            ProgrammeSignOff.ROLE_DIRECTOR,
        ]

    def test_rejects_non_draft_status(self, draft_programme, emails):
        draft_programme.status = ACTIVE
        draft_programme.save(update_fields=["status"])
        with pytest.raises(ProgrammeLifecycleError, match="not in DRAFT"):
            programme_lifecycle.submit_for_signoff(
                draft_programme, actor="florence", **emails,
            )

    def test_rejects_duplicate_emails(self, draft_programme, emails):
        # Set DPO email to be the same as NSR coordinator — must reject.
        emails["dpo_email"] = emails["nsr_coordinator_email"]
        with pytest.raises(ProgrammeLifecycleError, match="distinct"):
            programme_lifecycle.submit_for_signoff(
                draft_programme, actor="florence", **emails,
            )

    def test_rejects_creator_as_approver(self, draft_programme, emails):
        # The programme's `created_by` IS the NSR coordinator → reject.
        draft_programme.created_by = emails["nsr_coordinator_email"]
        draft_programme.save(update_fields=["created_by"])
        with pytest.raises(
            ProgrammeLifecycleError, match="programme creator cannot",
        ):
            programme_lifecycle.submit_for_signoff(
                draft_programme, actor=draft_programme.created_by, **emails,
            )

    def test_rejects_missing_email(self, draft_programme, emails):
        emails["dpo_email"] = ""
        with pytest.raises(ProgrammeLifecycleError, match="required"):
            programme_lifecycle.submit_for_signoff(
                draft_programme, actor="florence", **emails,
            )

    def test_resubmit_after_reject_clears_old_rows(
        self, draft_programme, emails,
    ):
        # Submit → reject → resubmit. The old rejected rows should be
        # cleared and four fresh pending rows created.
        programme_lifecycle.submit_for_signoff(
            draft_programme, actor="florence", **emails,
        )
        programme_lifecycle.reject_step(
            draft_programme, 1,
            actor_email=emails["nsr_coordinator_email"],
            reason="A" * 30,
        )
        draft_programme.refresh_from_db()
        assert draft_programme.status == DRAFT
        programme_lifecycle.submit_for_signoff(
            draft_programme, actor="florence", **emails,
        )
        pending = ProgrammeSignOff.objects.filter(
            programme=draft_programme,
            status=ProgrammeSignOff.PENDING,
        )
        assert pending.count() == 4


# ───────────────────────────────────────────────────────────────
# sign_step — happy path + AC-PROG-NO-SELF-APPROVE
# ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestSignStep:

    def test_four_distinct_signers_flip_to_active(
        self, draft_programme, emails,
    ):
        programme_lifecycle.submit_for_signoff(
            draft_programme, actor="florence", **emails,
        )
        for step, role_key in enumerate([
            "nsr_coordinator_email", "partner_steward_email",
            "dpo_email", "director_email",
        ], start=1):
            programme_lifecycle.sign_step(
                draft_programme, step,
                actor_email=emails[role_key], note=f"step{step}",
            )
        draft_programme.refresh_from_db()
        assert draft_programme.status == ACTIVE
        assert draft_programme.activated_at is not None
        # Every row is signed; actual_email == expected_email
        rows = list(
            ProgrammeSignOff.objects.filter(programme=draft_programme)
            .order_by("step"),
        )
        for r in rows:
            assert r.status == ProgrammeSignOff.SIGNED
            assert r.actual_email == r.expected_email
            assert r.audit_event_id

    def test_creator_cannot_sign_any_step(
        self, draft_programme, emails,
    ):
        # AC-PROG-NO-SELF-APPROVE — lifted from update_workflow.
        programme_lifecycle.submit_for_signoff(
            draft_programme, actor="florence", **emails,
        )
        draft_programme.refresh_from_db()
        # `created_by` == "florence". Try to sign as florence (even
        # supplying the right role email is moot because florence's
        # username doesn't match any expected_email).
        with pytest.raises(
            ProgrammeLifecycleError, match="creator cannot sign",
        ):
            programme_lifecycle.sign_step(
                draft_programme, 1,
                actor_email="florence", note="self",
            )

    def test_step_email_must_match_expected_role(
        self, draft_programme, emails,
    ):
        programme_lifecycle.submit_for_signoff(
            draft_programme, actor="florence", **emails,
        )
        with pytest.raises(ProgrammeLifecycleError, match="expects"):
            programme_lifecycle.sign_step(
                draft_programme, 1,
                actor_email=emails["dpo_email"],  # DPO trying to sign step 1
                note="wrong role",
            )

    def test_cannot_skip_an_earlier_pending_step(
        self, draft_programme, emails,
    ):
        programme_lifecycle.submit_for_signoff(
            draft_programme, actor="florence", **emails,
        )
        with pytest.raises(ProgrammeLifecycleError, match="before steps"):
            programme_lifecycle.sign_step(
                draft_programme, 3,
                actor_email=emails["dpo_email"], note="skip 1&2",
            )

    def test_signer_cannot_sign_twice_across_steps(
        self, draft_programme, emails,
    ):
        # If the same email shows up twice in the chain, the second
        # sign attempt MUST refuse. (submit_for_signoff already
        # refuses duplicate emails — this guards a future case where
        # the email matched expected_email but the chain configuration
        # somehow let two distinct expected_emails collapse to the
        # same actor on sign-time.) Force the situation by patching
        # the step-2 expected_email to match the step-1 signer.
        programme_lifecycle.submit_for_signoff(
            draft_programme, actor="florence", **emails,
        )
        row1 = ProgrammeSignOff.objects.get(
            programme=draft_programme, step=1,
        )
        row2 = ProgrammeSignOff.objects.get(
            programme=draft_programme, step=2,
        )
        # Sign step 1 normally.
        programme_lifecycle.sign_step(
            draft_programme, 1,
            actor_email=row1.expected_email, note="ok",
        )
        # Force step 2 to expect the same email as step 1.
        row2.expected_email = row1.expected_email
        row2.save(update_fields=["expected_email"])
        # The lifecycle service must reject the cross-step reuse.
        with pytest.raises(
            ProgrammeLifecycleError, match="distinct approvers",
        ):
            programme_lifecycle.sign_step(
                draft_programme, 2,
                actor_email=row1.expected_email, note="reuse",
            )

    def test_cannot_sign_when_not_pending_approval(
        self, draft_programme, emails,
    ):
        # ACTIVE programmes refuse sign attempts.
        programme_lifecycle.submit_for_signoff(
            draft_programme, actor="florence", **emails,
        )
        _walk_to_active(draft_programme, emails)
        with pytest.raises(ProgrammeLifecycleError, match="not awaiting"):
            programme_lifecycle.sign_step(
                draft_programme, 1,
                actor_email=emails["nsr_coordinator_email"], note="post",
            )


# ───────────────────────────────────────────────────────────────
# reject_step
# ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestRejectStep:

    def test_rolls_programme_back_to_draft_and_skips_remaining(
        self, draft_programme, emails,
    ):
        programme_lifecycle.submit_for_signoff(
            draft_programme, actor="florence", **emails,
        )
        programme_lifecycle.reject_step(
            draft_programme, 2,
            actor_email=emails["partner_steward_email"],
            reason="Cohort target too aggressive; needs cap.",
        )
        draft_programme.refresh_from_db()
        assert draft_programme.status == DRAFT
        rows = list(
            ProgrammeSignOff.objects.filter(programme=draft_programme)
            .order_by("step"),
        )
        # step 2 = rejected, others = skipped
        assert rows[0].status == ProgrammeSignOff.SKIPPED
        assert rows[1].status == ProgrammeSignOff.REJECTED
        assert rows[2].status == ProgrammeSignOff.SKIPPED
        assert rows[3].status == ProgrammeSignOff.SKIPPED

    def test_reason_required_minimum_length(
        self, draft_programme, emails,
    ):
        programme_lifecycle.submit_for_signoff(
            draft_programme, actor="florence", **emails,
        )
        with pytest.raises(ProgrammeLifecycleError, match="at least"):
            programme_lifecycle.reject_step(
                draft_programme, 1,
                actor_email=emails["nsr_coordinator_email"],
                reason="short",
            )

    def test_creator_cannot_reject(self, draft_programme, emails):
        programme_lifecycle.submit_for_signoff(
            draft_programme, actor="florence", **emails,
        )
        with pytest.raises(
            ProgrammeLifecycleError, match="creator cannot reject",
        ):
            programme_lifecycle.reject_step(
                draft_programme, 1,
                actor_email="florence",
                reason="self-rejection attempt long enough",
            )


# ───────────────────────────────────────────────────────────────
# suspend + close
# ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestSuspendAndClose:

    def test_suspend_requires_active_status(self, draft_programme):
        with pytest.raises(ProgrammeLifecycleError, match="not ACTIVE"):
            programme_lifecycle.suspend_programme(
                draft_programme, actor="dpo",
                reason="A" * 30,
            )

    def test_suspend_flips_active_to_suspended(
        self, draft_programme, emails,
    ):
        programme_lifecycle.submit_for_signoff(
            draft_programme, actor="florence", **emails,
        )
        _walk_to_active(draft_programme, emails)
        programme_lifecycle.suspend_programme(
            draft_programme, actor="dpo",
            reason="Partner missed quarterly reconciliation.",
        )
        draft_programme.refresh_from_db()
        assert draft_programme.status == SUSPENDED

    def test_suspend_reason_minimum_length(
        self, draft_programme, emails,
    ):
        programme_lifecycle.submit_for_signoff(
            draft_programme, actor="florence", **emails,
        )
        _walk_to_active(draft_programme, emails)
        with pytest.raises(ProgrammeLifecycleError, match="at least"):
            programme_lifecycle.suspend_programme(
                draft_programme, actor="dpo", reason="short",
            )

    def test_close_flips_active_to_closing(
        self, draft_programme, emails,
    ):
        programme_lifecycle.submit_for_signoff(
            draft_programme, actor="florence", **emails,
        )
        _walk_to_active(draft_programme, emails)
        programme_lifecycle.close_programme(
            draft_programme, actor="director",
            reason="Final cycle disbursed; cohort exiting normally.",
        )
        draft_programme.refresh_from_db()
        assert draft_programme.status == CLOSING
        assert draft_programme.closed_at is not None


# ───────────────────────────────────────────────────────────────
# DRF action surface — happy paths + guards via HTTP
# ───────────────────────────────────────────────────────────────

URL_PROG = "/api/v1/programmes/"


@pytest.mark.django_db
class TestProgrammeActionEndpoints:

    @pytest.fixture(autouse=True)
    def _enable_flag(self, settings):
        settings.PARTNERS_MODULE_ENABLED = True

    def test_submit_then_sign_round_trip_to_active(
        self, api, draft_programme, emails,
    ):
        r = api.post(
            f"{URL_PROG}{draft_programme.id}/submit-for-signoff/",
            emails, format="json",
        )
        assert r.status_code == 200, r.data
        assert r.data["status"] == PENDING_APPROVAL

        # Walk all four steps.
        for step, email in enumerate([
            emails["nsr_coordinator_email"],
            emails["partner_steward_email"],
            emails["dpo_email"],
            emails["director_email"],
        ], start=1):
            r = api.post(
                f"{URL_PROG}{draft_programme.id}/sign/{step}/",
                {"actor_email": email, "note": f"step{step}"},
                format="json",
            )
            assert r.status_code == 200, (step, r.data)
        assert r.data["status"] == ACTIVE

    def test_submit_rejects_duplicate_emails(
        self, api, draft_programme, emails,
    ):
        bad = {**emails, "dpo_email": emails["nsr_coordinator_email"]}
        r = api.post(
            f"{URL_PROG}{draft_programme.id}/submit-for-signoff/",
            bad, format="json",
        )
        assert r.status_code == 400
        assert "distinct" in r.data["detail"].lower()

    def test_sign_creator_blocked_400(
        self, api, draft_programme, emails,
    ):
        api.post(
            f"{URL_PROG}{draft_programme.id}/submit-for-signoff/",
            emails, format="json",
        )
        r = api.post(
            f"{URL_PROG}{draft_programme.id}/sign/1/",
            {"actor_email": "florence", "note": "self-sign"},
            format="json",
        )
        assert r.status_code == 400
        assert "creator" in r.data["detail"].lower()

    def test_reject_endpoint_rolls_back_status(
        self, api, draft_programme, emails,
    ):
        api.post(
            f"{URL_PROG}{draft_programme.id}/submit-for-signoff/",
            emails, format="json",
        )
        r = api.post(
            f"{URL_PROG}{draft_programme.id}/reject/1/",
            {
                "actor_email": emails["nsr_coordinator_email"],
                "reason": "Targeting expression doesn't match the DSA scope.",
            },
            format="json",
        )
        assert r.status_code == 200, r.data
        assert r.data["status"] == DRAFT

    def test_suspend_endpoint_requires_active(
        self, api, draft_programme,
    ):
        r = api.post(
            f"{URL_PROG}{draft_programme.id}/suspend/",
            {"reason": "Test suspension reason long enough"},
            format="json",
        )
        assert r.status_code == 400
        assert "not active" in r.data["detail"].lower()


# ───────────────────────────────────────────────────────────────
# Aggregates + signoffs read endpoints
# ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestProgrammeReadEndpoints:

    @pytest.fixture(autouse=True)
    def _enable_flag(self, settings):
        settings.PARTNERS_MODULE_ENABLED = True

    def test_aggregates_returns_total_by_status_by_kind(
        self, api, partner,
    ):
        Programme.objects.create(
            partner=partner, code="P1", name="P1",
            kind="cash_transfer", status="draft",
        )
        Programme.objects.create(
            partner=partner, code="P2", name="P2",
            kind="cash_transfer", status="active",
        )
        Programme.objects.create(
            partner=partner, code="P3", name="P3",
            kind="service", status="active",
        )
        r = api.get(f"{URL_PROG}aggregates/")
        assert r.status_code == 200, r.data
        assert r.data["total"] == 3
        assert r.data["by_status"] == {"draft": 1, "active": 2}
        assert r.data["by_kind"] == {"cash_transfer": 2, "service": 1}

    def test_aggregates_honours_list_filters(
        self, api, partner,
    ):
        Programme.objects.create(
            partner=partner, code="P1", name="P1",
            kind="cash_transfer", status="active",
        )
        Programme.objects.create(
            partner=partner, code="P2", name="P2",
            kind="service", status="active",
        )
        r = api.get(f"{URL_PROG}aggregates/?kind=service")
        assert r.data["total"] == 1
        assert r.data["by_kind"] == {"service": 1}

    def test_signoffs_lists_current_revision_rows_in_step_order(
        self, api, draft_programme, emails,
    ):
        programme_lifecycle.submit_for_signoff(
            draft_programme, actor="florence", **emails,
        )
        r = api.get(f"{URL_PROG}{draft_programme.id}/signoffs/")
        assert r.status_code == 200, r.data
        assert r.data["revision"] == 1
        assert r.data["current_revision"] == 1
        steps = [item["step"] for item in r.data["items"]]
        assert steps == [1, 2, 3, 4]
        # All pending, expected_email round-trips
        statuses = {item["status"] for item in r.data["items"]}
        assert statuses == {"pending"}
        assert r.data["items"][0]["expected_email"] == emails["nsr_coordinator_email"]

    def test_signoffs_explicit_revision_query_param(
        self, api, draft_programme, emails,
    ):
        # No chain on revision 99 — returns an empty list, not 404.
        r = api.get(
            f"{URL_PROG}{draft_programme.id}/signoffs/?revision=99",
        )
        assert r.status_code == 200
        assert r.data["revision"] == 99
        assert r.data["items"] == []
