"""End-to-end signature workflow tests — US-S23-010 / ADR-0012."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.partners.models import (
    DataSharingAgreement,
    Partner,
)
from apps.partners.services import signature as signature_service
from apps.reference_data.services import clear_resolver_cache
from apps.security.models import AuditEvent

URL_DSAS = "/api/v1/dsas/"


@pytest.fixture(autouse=True)
def _flush():
    clear_resolver_cache()
    yield
    clear_resolver_cache()


@pytest.fixture
def api(settings, db):
    settings.PARTNERS_MODULE_ENABLED = True
    user_cls = get_user_model()
    # Sprint 24 / ADR-0013: Partner + DSA viewsets are ABAC-scoped via
    # PartnerScopedQuerysetMixin. A regular user with no OperatorScope
    # gets a fail-closed empty queryset. Superuser bypasses scope.
    u = user_cls.objects.create_superuser(username="dsa-tester", password="p")
    c = APIClient()
    c.force_authenticate(user=u)
    return c, u


@pytest.fixture
def partner(db):
    return Partner.objects.create(
        code="OPM", name="OPM", type="ministry",
        sector="social_protection", status="active", tone="system",
    )


@pytest.fixture
def draft_dsa(db, partner):
    return DataSharingAgreement.objects.create(
        reference="DSA-OPM-2026-001", partner=partner, status="draft",
    )


@pytest.mark.django_db
class TestSubmitForSignoff:
    def test_creates_three_signatures_and_sets_pending(self, draft_dsa):
        signature_service.submit_for_signoff(
            draft_dsa,
            actor="atim.florence",
            partner_signer_email="ps@opm.go.ug",
            nsr_unit_lead_email="lead@nsr.go.ug",
            dpo_email="dpo@mglsd.go.ug",
        )
        draft_dsa.refresh_from_db()
        assert draft_dsa.status == "pending_signature"
        sigs = list(draft_dsa.signatures.order_by("sequence_order"))
        assert [s.sequence_order for s in sigs] == [1, 2, 3]
        assert sigs[0].method == "docusign"
        assert sigs[1].method == "in_console"
        assert sigs[2].signer_role == "dpo"
        # Envelope ID dispatched on the first signature via the stub.
        assert sigs[0].docusign_envelope_id.startswith("stub-env-")

    def test_emits_submit_and_envelope_sent_audit_events(self, draft_dsa):
        signature_service.submit_for_signoff(
            draft_dsa,
            actor="atim.florence",
            partner_signer_email="ps@opm.go.ug",
            nsr_unit_lead_email="lead@nsr.go.ug",
            dpo_email="dpo@mglsd.go.ug",
        )
        # submit on the DSA, envelope_sent on the first signature.
        submit = AuditEvent.objects.filter(
            entity_type="dsa", action="submit",
            entity_id=draft_dsa.id,
        )
        envelope = AuditEvent.objects.filter(
            entity_type="dsa_signature", action="envelope_sent",
        )
        assert submit.count() == 1
        assert envelope.count() == 1

    def test_rejects_self_signoff_email_clash(self, draft_dsa):
        with pytest.raises(signature_service.SignatureError,
                           match="Self sign-off"):
            signature_service.submit_for_signoff(
                draft_dsa, actor="x",
                partner_signer_email="same@x.go.ug",
                nsr_unit_lead_email="same@x.go.ug",  # clash
                dpo_email="dpo@mglsd.go.ug",
            )

    def test_rejects_when_not_draft(self, draft_dsa):
        draft_dsa.status = "active"
        draft_dsa.save()
        with pytest.raises(signature_service.SignatureError,
                           match="not in draft"):
            signature_service.submit_for_signoff(
                draft_dsa, actor="x",
                partner_signer_email="a@x.go.ug",
                nsr_unit_lead_email="b@x.go.ug",
                dpo_email="c@x.go.ug",
            )

    def test_via_drf_action(self, api, draft_dsa):
        c, _ = api
        r = c.post(
            f"{URL_DSAS}{draft_dsa.id}/submit-for-signoff/",
            {
                "partner_signer_email": "ps@opm.go.ug",
                "nsr_unit_lead_email": "lead@nsr.go.ug",
                "dpo_email": "dpo@mglsd.go.ug",
            }, format="json",
        )
        assert r.status_code == 200, r.data
        assert r.data["status"] == "pending_signature"
        assert len(r.data["signatures"]) == 3


@pytest.mark.django_db
class TestSignProgression:
    def _submitted(self, dsa):
        signature_service.submit_for_signoff(
            dsa, actor="x",
            partner_signer_email="a@x.go.ug",
            nsr_unit_lead_email="b@x.go.ug",
            dpo_email="c@x.go.ug",
        )

    def test_first_sign_progresses_to_second_envelope(self, draft_dsa):
        self._submitted(draft_dsa)
        sig1 = draft_dsa.signatures.get(sequence_order=1)
        signature_service.record_signature(sig1, actor="atim.florence")
        sig2 = draft_dsa.signatures.get(sequence_order=2)
        # In-console method doesn't carry an envelope id; the audit
        # event still fires for envelope_sent on docusign signatures.
        assert sig2.status == "pending"

    def test_third_sign_activates_dsa(self, draft_dsa):
        self._submitted(draft_dsa)
        for seq in (1, 2, 3):
            sig = draft_dsa.signatures.get(sequence_order=seq)
            signature_service.record_signature(sig, actor=f"signer-{seq}")
        draft_dsa.refresh_from_db()
        assert draft_dsa.status == "active"
        assert draft_dsa.signed_at is not None
        # Audit chain
        assert AuditEvent.objects.filter(
            entity_type="dsa", action="activate",
            entity_id=draft_dsa.id,
        ).count() == 1


@pytest.mark.django_db
class TestDecline:
    def _submitted(self, dsa):
        signature_service.submit_for_signoff(
            dsa, actor="x",
            partner_signer_email="a@x.go.ug",
            nsr_unit_lead_email="b@x.go.ug",
            dpo_email="c@x.go.ug",
        )

    def test_decline_reverts_dsa_to_draft(self, draft_dsa):
        self._submitted(draft_dsa)
        sig2 = draft_dsa.signatures.get(sequence_order=2)
        signature_service.decline_signature(
            sig2, actor="lead", reason="scope too broad",
        )
        draft_dsa.refresh_from_db()
        assert draft_dsa.status == "draft"
        sig2.refresh_from_db()
        assert sig2.status == "declined"
        assert sig2.decline_reason == "scope too broad"


@pytest.mark.django_db
class TestDsaSigningNotifications:
    """Each chain transition emails the right parties. Step 1 uses
    DocuSign in production, but the default stub path still emits a
    workflow email so the partner signatory sees the submit event.
    In-console signers (sequences 2 + 3) get our email. Activation
    emails every signer + the partner's primary contact. Decline does
    the same with the verbatim reason."""

    def _submitted(self, dsa):
        signature_service.submit_for_signoff(
            dsa, actor="x",
            partner_signer_email="signer1@partner.go.ug",
            nsr_unit_lead_email="lead@nsr.go.ug",
            dpo_email="dpo@mglsd.go.ug",
        )

    def test_first_sign_emails_in_console_lead(self, draft_dsa):
        from django.core import mail
        self._submitted(draft_dsa)
        mail.outbox.clear()
        sig1 = draft_dsa.signatures.get(sequence_order=1)
        signature_service.record_signature(sig1, actor="signer1@partner.go.ug")
        assert len(mail.outbox) == 1
        msg = mail.outbox[0]
        assert msg.to == ["lead@nsr.go.ug"]
        assert "awaits your signature" in msg.subject

    def test_submit_emails_partner_signatory_when_docusign_disabled(self, draft_dsa):
        from django.core import mail
        self._submitted(draft_dsa)
        submit_mails = [m for m in mail.outbox if "awaits your signature" in m.subject]
        assert len(submit_mails) == 1
        msg = submit_mails[0]
        assert msg.to == ["signer1@partner.go.ug"]
        assert "step 1 of 3" in msg.body
        sig1 = draft_dsa.signatures.get(sequence_order=1)
        assert AuditEvent.objects.filter(
            action="dsa.signoff.notified",
            entity_type="dsa_signature",
            entity_id=sig1.id,
        ).count() == 1

    def test_activation_emails_all_signers_plus_partner(self, draft_dsa):
        from django.core import mail
        self._submitted(draft_dsa)
        for seq in (1, 2, 3):
            sig = draft_dsa.signatures.get(sequence_order=seq)
            signature_service.record_signature(sig, actor=f"signer-{seq}")
        # Find the activation notification — it's the most recent
        # mail whose subject contains "ACTIVE".
        activations = [m for m in mail.outbox if "ACTIVE" in m.subject]
        assert len(activations) == 1
        # All three signers receive it. Partner primary_email is
        # empty on this fixture; helper dedupes and drops blanks.
        assert set(activations[0].to) == {
            "signer1@partner.go.ug",
            "lead@nsr.go.ug",
            "dpo@mglsd.go.ug",
        }

    def test_decline_emails_everyone_with_reason(self, draft_dsa):
        from django.core import mail
        self._submitted(draft_dsa)
        mail.outbox.clear()
        sig2 = draft_dsa.signatures.get(sequence_order=2)
        signature_service.decline_signature(
            sig2, actor="lead", reason="scope too broad",
        )
        declines = [m for m in mail.outbox if "DECLINED" in m.subject]
        assert len(declines) == 1
        msg = declines[0]
        # Every signer on the chain (all 3) is notified — even the
        # pending DPO step, so they don't sit waiting for an
        # envelope that's no longer coming.
        assert set(msg.to) >= {
            "signer1@partner.go.ug",
            "lead@nsr.go.ug",
            "dpo@mglsd.go.ug",
        }
        assert "scope too broad" in msg.body


@pytest.mark.django_db
class TestDsaApiEndpoints:
    def test_list_filter_by_partner(self, api, partner, draft_dsa):
        c, _ = api
        # Second partner + DSA
        other = Partner.objects.create(
            code="X", name="X", type="ngo", status="active",
        )
        DataSharingAgreement.objects.create(
            reference="DSA-X-2026-001", partner=other, status="draft",
        )
        r = c.get(URL_DSAS, {"partner": partner.id})
        codes = [d["partner_code"] for d in r.data["results"]]
        assert codes == ["OPM"]

    def test_dsa_response_carries_labels(self, api, draft_dsa):
        c, _ = api
        r = c.get(f"{URL_DSAS}{draft_dsa.id}/")
        assert r.status_code == 200
        assert r.data["status_label"] == "Draft"
        assert r.data["sensitive_data_handling_label"] == "None"


@pytest.mark.django_db
class TestActivityEndpoint:
    def test_returns_partner_activity(self, api, partner, draft_dsa):
        c, _ = api
        signature_service.submit_for_signoff(
            draft_dsa, actor="x",
            partner_signer_email="a@x.go.ug",
            nsr_unit_lead_email="b@x.go.ug",
            dpo_email="c@x.go.ug",
        )
        r = c.get(f"/api/v1/partners/{partner.id}/activity/")
        assert r.status_code == 200
        kinds = {item["kind"] for item in r.data["items"]}
        # submit_for_signoff emits action=submit on the DSA and
        # action=envelope_sent on the first signature.
        assert "partner_onboarding" in kinds  # mapped from "submit"
