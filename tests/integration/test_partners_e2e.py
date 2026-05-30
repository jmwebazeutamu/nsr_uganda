"""End-to-end integration tests for the partners module — US-S23-015.

Two scenarios, mirroring the spec's ACCEPTANCE block:

1. Wizard happy path. POST a Partner, POST a draft DSA, submit
   for sign-off, walk the three signatures through to ACTIVE,
   verify the audit chain reconstructs the workflow.

2. Add a new ChoiceOption via the admin path, hit the bundle
   endpoint, confirm the new option appears, instantiate a partner
   with the new code, confirm the resolved label flows through.
   Demonstrates the "no code deploy" loop.
"""

from __future__ import annotations

import pytest
from apps.partners.models import (
    DataSharingAgreement,
    DsaSignature,
)
from apps.partners.services import signature as signature_service
from apps.reference_data.models import (
    ChoiceList,
    ChoiceOption,
)
from apps.reference_data.services import clear_resolver_cache
from apps.security.models import AuditEvent
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


@pytest.fixture(autouse=True)
def _flush():
    clear_resolver_cache()
    yield
    clear_resolver_cache()


@pytest.fixture
def api(settings, db):
    settings.PARTNERS_MODULE_ENABLED = True
    user_cls = get_user_model()
    u = user_cls.objects.create_superuser(username="e2e-partners", password="p")
    c = APIClient()
    c.force_authenticate(user=u)
    return c


@pytest.mark.django_db
class TestPartnerWizardE2E:
    """Reproduces the wizard flow end-to-end via the API:

        POST /api/v1/partners/                          → draft Partner
        POST /api/v1/dsas/                              → draft DSA
        POST /api/v1/dsas/{id}/submit-for-signoff/      → pending_signature
        record_signature() x3                           → DSA active

    Asserts the audit chain captures the right events in the right order.
    """

    def test_wizard_to_active_dsa(self, api):
        # 1. Create the Partner.
        r = api.post("/api/v1/partners/", {
            "code": "IRC",
            "name": "International Rescue Committee",
            "type": "multilateral",
            "sector": "humanitarian",
            "status": "onboarding",
            "tone": "update",
            "primary_email": "uganda@rescue.org",
        }, format="json")
        assert r.status_code == 201, r.data
        partner_id = r.data["id"]
        assert r.data["type_label"] == "Multilateral"
        assert r.data["sector_label"] == "Humanitarian"

        # 2. Create the draft DSA.
        r = api.post("/api/v1/dsas/", {
            "reference": "DSA-IRC-2026-001",
            "partner": partner_id,
            "status": "draft",
            "monthly_row_budget": 250_000,
            "sensitive_data_handling": "none",
            "entities_scope": {"household": True, "member": False},
            "field_scope": {"Identifiers": True, "PMT": True},
            "retention_days": 180,
            "breach_sla_hours": 72,
        }, format="json")
        assert r.status_code == 201, r.data
        dsa_id = r.data["id"]
        assert r.data["status_label"] == "Draft"

        # 3. Submit for sign-off.
        r = api.post(
            f"/api/v1/dsas/{dsa_id}/submit-for-signoff/",
            {
                "partner_signer_email": "ceo@rescue.org",
                "partner_signer_name": "Country Director",
                "nsr_unit_lead_email": "lead@nsr.go.ug",
                "nsr_unit_lead_name": "Akello Patience",
                "dpo_email": "dpo@mglsd.go.ug",
                "dpo_name": "Mukasa Robert",
            },
            format="json",
        )
        assert r.status_code == 200, r.data
        assert r.data["status"] == "pending_signature"
        sig_ids = [s["id"] for s in sorted(
            r.data["signatures"], key=lambda s: s["sequence_order"],
        )]
        assert len(sig_ids) == 3

        # 4. Walk the three signatures through. Mirrors the
        # DocuSign webhook (partner_auth_signatory) + the in-console
        # actions for the NSR Unit Lead + DPO.
        for sig_id in sig_ids:
            sig = DsaSignature.objects.get(pk=sig_id)
            signature_service.record_signature(sig, actor=sig.signer_email)

        # 5. The DSA is now ACTIVE.
        dsa = DataSharingAgreement.objects.get(pk=dsa_id)
        assert dsa.status == "active"
        assert dsa.signed_at is not None
        assert all(s.status == "signed" for s in dsa.signatures.all())

        # 6. Audit chain reconstruction — ordered by occurred_at.
        events = list(
            AuditEvent.objects
            .filter(entity_type__in=("dsa", "dsa_signature"))
            .filter(
                entity_id__in=[dsa_id, *sig_ids],
            )
            .order_by("occurred_at", "id")
            .values_list("action", "entity_type", flat=False),
        )
        action_seq = [a for a, _ in events]
        assert action_seq[0] == "submit"           # DSA
        assert "envelope_sent" in action_seq
        assert action_seq.count("sign") == 3       # one per signature
        assert "activate" in action_seq            # DSA closing event
        # Activation emits a follow-on notification, so the terminal
        # event is `dsa.activation.notified`; `activate` immediately
        # precedes it.
        assert action_seq[-1] == "dsa.activation.notified"
        assert action_seq.index("activate") < action_seq.index("dsa.activation.notified")


@pytest.mark.django_db
class TestAddOptionNoDeploy:
    """The spec's acceptance: add a ChoiceOption via the admin path,
    approve it (status=ACTIVE), hit the bundle endpoint, confirm the
    new option appears. Wizard renders it on next mount without a
    code deploy."""

    def test_new_partner_type_flows_through_bundle_and_resolver(self, api):
        # Before: bundle includes the seeded partner_type options.
        before = api.get(
            "/api/v1/reference-data/choice-list-bundle/",
            {"lists": "partner_type"},
        )
        etag_before = before["ETag"]
        codes_before = {
            o["code"] for o in (
                next(
                    lst for lst in before.data["lists"]
                    if lst["list_name"] == "partner_type"
                )["options"]
            )
        }
        assert "international_org" not in codes_before

        # Steward approves a new option on the active partner_type list.
        # In production this comes through the dual-approval workflow
        # described in ADR-0011 §7; the post-approval state is what
        # the bundle + resolver see, so we land it directly here.
        active = ChoiceList.objects.get(
            list_name="partner_type", version=1, status="active",
        )
        ChoiceOption.objects.create(
            choice_list=active, code="international_org",
            label="International Organisation", language="en",
            sort_order=99,
        )

        # After: bundle ETag flips, the new option appears.
        after = api.get(
            "/api/v1/reference-data/choice-list-bundle/",
            {"lists": "partner_type"},
        )
        assert after["ETag"] != etag_before
        codes_after = {
            o["code"] for o in (
                next(
                    lst for lst in after.data["lists"]
                    if lst["list_name"] == "partner_type"
                )["options"]
            )
        }
        assert "international_org" in codes_after

        # Resolver picks it up — a Partner with the new code renders
        # the new label via the API.
        r = api.post("/api/v1/partners/", {
            "code": "IOM",
            "name": "International Organization for Migration",
            "type": "international_org",  # the new code
            "status": "onboarding",
        }, format="json")
        assert r.status_code == 201, r.data
        assert r.data["type_label"] == "International Organisation"

        # The data_management.E001 system check still passes — the
        # field doesn't carry choices=.
        from apps.data_management.checks import (
            check_no_textchoices_on_mapped_fields,
        )
        assert check_no_textchoices_on_mapped_fields(app_configs=None) == []
