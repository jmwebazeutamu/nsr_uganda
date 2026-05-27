"""PMTModelSignOff lifecycle tests (HANDOFF — Admin Console + PMT §4.3).

Mirrors apps/partners/test_programme_lifecycle.py — same shape, three
steps instead of four. Author submission auto-signs step 1; the two
reviewer signatures (steps 2 + 3) activate the model.
"""

from __future__ import annotations

import pytest

from apps.pmt.models import (
    ModelStatus,
    PMTModelSignOff,
    PMTModelVersion,
)
from apps.pmt.services import (
    PMTApprovalError,
    reject_step,
    sign_step,
    submit_for_approval,
)


@pytest.fixture
def draft_version(db):
    # version=900+ avoids colliding with the production v1 seed.
    # See [[feedback_test_pmt_version_900_pattern]].
    return PMTModelVersion.objects.create(
        version=910, status=ModelStatus.DRAFT,
        author="analyst@nsr.go.ug",
        intercept=0, variables=[],
    )


@pytest.fixture
def emails():
    return {
        "mglsd_steward_email": "steward@mglsd.go.ug",
        "ubos_dg_email":       "dg@ubos.go.ug",
    }


# ───────────────────────────────────────────────────────────────
# submit_for_approval
# ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestSubmit:

    def test_creates_three_rows_flips_to_pending(self, draft_version, emails):
        submit_for_approval(
            draft_version, actor="analyst@nsr.go.ug", **emails,
        )
        draft_version.refresh_from_db()
        assert draft_version.status == ModelStatus.PENDING_APPROVAL
        rows = list(
            PMTModelSignOff.objects.filter(model_version=draft_version)
            .order_by("step"),
        )
        assert [r.step for r in rows] == [1, 2, 3]
        # Step 1 auto-signed (the author's submit IS their sign).
        assert rows[0].status == PMTModelSignOff.SIGNED
        assert rows[1].status == PMTModelSignOff.PENDING
        assert rows[2].status == PMTModelSignOff.PENDING

    def test_rejects_non_draft(self, draft_version, emails):
        draft_version.status = ModelStatus.ACTIVE
        draft_version.save(update_fields=["status"])
        with pytest.raises(PMTApprovalError, match="not DRAFT"):
            submit_for_approval(
                draft_version, actor="x", **emails,
            )

    def test_rejects_duplicate_reviewer_emails(self, draft_version, emails):
        emails["ubos_dg_email"] = emails["mglsd_steward_email"]
        with pytest.raises(PMTApprovalError, match="distinct"):
            submit_for_approval(
                draft_version, actor="analyst@nsr.go.ug", **emails,
            )

    def test_rejects_author_as_reviewer(self, draft_version, emails):
        emails["mglsd_steward_email"] = "analyst@nsr.go.ug"
        with pytest.raises(PMTApprovalError, match="author cannot"):
            submit_for_approval(
                draft_version, actor="analyst@nsr.go.ug", **emails,
            )

    def test_rejected_version_cannot_be_resubmitted(
        self, draft_version, emails,
    ):
        """Once rejected, a version is terminally REJECTED — the
        author must clone a fresh DRAFT to revise (preserves the
        audit chain). submit_for_approval rejects any non-DRAFT."""
        submit_for_approval(
            draft_version, actor="analyst@nsr.go.ug", **emails,
        )
        reject_step(
            draft_version, 2,
            actor_email=emails["mglsd_steward_email"],
            reason="Coefficient drift exceeds threshold.",
        )
        draft_version.refresh_from_db()
        assert draft_version.status == ModelStatus.REJECTED
        with pytest.raises(PMTApprovalError):
            submit_for_approval(
                draft_version, actor="analyst@nsr.go.ug", **emails,
            )


# ───────────────────────────────────────────────────────────────
# sign_step — happy path + AC-PMT-NO-SELF-APPROVE
# ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestSign:

    def test_two_distinct_signers_activate(self, draft_version, emails):
        submit_for_approval(
            draft_version, actor="analyst@nsr.go.ug", **emails,
        )
        sign_step(
            draft_version, 2,
            actor_email=emails["mglsd_steward_email"], note="approved",
        )
        sign_step(
            draft_version, 3,
            actor_email=emails["ubos_dg_email"], note="approved",
        )
        draft_version.refresh_from_db()
        assert draft_version.status == ModelStatus.ACTIVE
        assert draft_version.approved_by == emails["ubos_dg_email"]

    def test_author_cannot_sign(self, draft_version, emails):
        submit_for_approval(
            draft_version, actor="analyst@nsr.go.ug", **emails,
        )
        with pytest.raises(PMTApprovalError, match="author cannot sign"):
            sign_step(
                draft_version, 2,
                actor_email="analyst@nsr.go.ug", note="self",
            )

    def test_email_must_match_expected_role(
        self, draft_version, emails,
    ):
        submit_for_approval(
            draft_version, actor="analyst@nsr.go.ug", **emails,
        )
        with pytest.raises(PMTApprovalError, match="expects"):
            sign_step(
                draft_version, 2,
                actor_email=emails["ubos_dg_email"],  # wrong role
                note="bad",
            )

    def test_cannot_sign_when_not_pending_approval(
        self, draft_version, emails,
    ):
        # Already active — sign refuses.
        submit_for_approval(
            draft_version, actor="analyst@nsr.go.ug", **emails,
        )
        sign_step(
            draft_version, 2,
            actor_email=emails["mglsd_steward_email"], note="ok",
        )
        sign_step(
            draft_version, 3,
            actor_email=emails["ubos_dg_email"], note="ok",
        )
        draft_version.refresh_from_db()
        # Try to sign again — refuses (now ACTIVE).
        with pytest.raises(PMTApprovalError, match="not awaiting"):
            sign_step(
                draft_version, 2,
                actor_email=emails["mglsd_steward_email"], note="late",
            )

    def test_distinct_signers_enforced(self, draft_version, emails):
        # Force step 3's expected_email to match step 2's signer
        # (the operator UI normally prevents this; the engine still
        # guards it).
        submit_for_approval(
            draft_version, actor="analyst@nsr.go.ug", **emails,
        )
        sign_step(
            draft_version, 2,
            actor_email=emails["mglsd_steward_email"], note="ok",
        )
        row3 = PMTModelSignOff.objects.get(
            model_version=draft_version, step=3,
        )
        row3.expected_email = emails["mglsd_steward_email"]
        row3.save(update_fields=["expected_email"])
        with pytest.raises(
            PMTApprovalError, match="distinct approvers",
        ):
            sign_step(
                draft_version, 3,
                actor_email=emails["mglsd_steward_email"],
                note="double",
            )


# ───────────────────────────────────────────────────────────────
# reject_step
# ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestReject:

    def test_terminal_rejected_skips_remaining(
        self, draft_version, emails,
    ):
        submit_for_approval(
            draft_version, actor="analyst@nsr.go.ug", **emails,
        )
        reject_step(
            draft_version, 2,
            actor_email=emails["mglsd_steward_email"],
            reason="Coefficients flagged by validation review.",
        )
        draft_version.refresh_from_db()
        # Rejection is terminal — version does NOT roll back to DRAFT.
        # Signoffs + audit row remain so the chain is reconstructable.
        assert draft_version.status == ModelStatus.REJECTED
        rows = list(
            PMTModelSignOff.objects.filter(model_version=draft_version)
            .order_by("step"),
        )
        # step 1 stays SIGNED (was the author's submit); step 2
        # REJECTED; step 3 SKIPPED.
        assert rows[0].status == PMTModelSignOff.SIGNED
        assert rows[1].status == PMTModelSignOff.REJECTED
        assert rows[2].status == PMTModelSignOff.SKIPPED

    def test_reason_minimum_length(self, draft_version, emails):
        submit_for_approval(
            draft_version, actor="analyst@nsr.go.ug", **emails,
        )
        with pytest.raises(PMTApprovalError, match="at least"):
            reject_step(
                draft_version, 2,
                actor_email=emails["mglsd_steward_email"],
                reason="too short",
            )

    def test_author_cannot_reject(self, draft_version, emails):
        submit_for_approval(
            draft_version, actor="analyst@nsr.go.ug", **emails,
        )
        with pytest.raises(PMTApprovalError, match="author cannot reject"):
            reject_step(
                draft_version, 2,
                actor_email="analyst@nsr.go.ug",
                reason="self-reject attempt long enough",
            )


# ───────────────────────────────────────────────────────────────
# Email notifications — each lifecycle transition emails the right
# party. SMTP backend is `locmem` in tests, so we read django.core.mail.outbox.
# ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestSignoffNotifications:

    def test_submit_emails_the_steward(self, draft_version, emails):
        from django.core import mail
        mail.outbox.clear()
        submit_for_approval(
            draft_version, actor="analyst@nsr.go.ug", **emails,
        )
        # Only the steward gets emailed on submit — the UBOS DG
        # waits until the steward signs (chain advances one-at-a-time).
        assert len(mail.outbox) == 1
        msg = mail.outbox[0]
        assert msg.to == ["steward@mglsd.go.ug"]
        assert f"v{draft_version.version}" in msg.subject
        assert "step 2 of 3" in msg.body

    def test_steward_signing_emails_the_dg(self, draft_version, emails):
        from django.core import mail
        submit_for_approval(
            draft_version, actor="analyst@nsr.go.ug", **emails,
        )
        mail.outbox.clear()
        sign_step(
            draft_version, 2,
            actor_email="steward@mglsd.go.ug",
            note="approved · seven-day calibration sample",
        )
        # Chain advanced — DG gets the "awaits your signature" mail.
        assert len(mail.outbox) == 1
        msg = mail.outbox[0]
        assert msg.to == ["dg@ubos.go.ug"]
        assert "awaits your signature" in msg.subject

    def test_final_signing_emails_author_and_prior_signers(
        self, draft_version, emails,
    ):
        from django.core import mail
        submit_for_approval(
            draft_version, actor="analyst@nsr.go.ug", **emails,
        )
        sign_step(draft_version, 2, actor_email="steward@mglsd.go.ug")
        mail.outbox.clear()
        sign_step(draft_version, 3, actor_email="dg@ubos.go.ug")
        # Chain complete — author + steward both get the "ACTIVE" mail.
        assert len(mail.outbox) == 1
        msg = mail.outbox[0]
        assert "ACTIVE" in msg.subject
        assert set(msg.to) == {"analyst@nsr.go.ug", "steward@mglsd.go.ug"}

    def test_rejection_emails_the_author_with_reason(
        self, draft_version, emails,
    ):
        from django.core import mail
        submit_for_approval(
            draft_version, actor="analyst@nsr.go.ug", **emails,
        )
        mail.outbox.clear()
        reject_step(
            draft_version, 2,
            actor_email="steward@mglsd.go.ug",
            reason="validation R² below acceptance threshold",
        )
        assert len(mail.outbox) == 1
        msg = mail.outbox[0]
        assert msg.to == ["analyst@nsr.go.ug"]
        assert "REJECTED" in msg.subject
        # Reason is included verbatim so the author can act on it.
        assert "validation R² below acceptance threshold" in msg.body
