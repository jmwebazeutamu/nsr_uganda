# ADR-0012: DSA signature workflow — three-step sign-off chain via DocuSign + console

- **Status**: Proposed
- **Date**: 19 May 2026
- **Owner**: NSR MIS Architecture Team
- **Decision-makers**: NSR Unit Coordinator, Data Protection Officer, Legal Counsel (MGLSD)
- **References**: SAD v0.6 §11.6 (Partner & DSA registry); ADR-0011 (Partners module); DPPA 2019 §§17, 21; design/v0.1/partners-source/screens-partners.jsx (StepReview, SigStep, submitOpen modal); US-S23 sprint pack.

---

## Context

A Data Sharing Agreement (DSA) between MGLSD's NSR Unit and an external partner is a legal contract under DPPA 2019. It binds the partner to the scope, retention, and breach-notification terms; it binds NSR to delivering only what the contract authorises. The contract must be signed by three parties before it goes live:

1. The **Partner Authorised Signatory** — the legally-empowered representative of the partner (Permanent Secretary for a ministry, Country Director for a multilateral, CEO for a private rail).
2. The **NSR Unit Lead** — the head of the NSR Unit at MGLSD, who confirms the contract conforms to the Unit's policy.
3. The **Data Protection Officer (MGLSD)** — the DPO, who confirms compliance with DPPA 2019 (lawful basis, sensitive-data clauses, retention, breach SLA).

The wizard's Review step (`SigStep` in `screens-partners.jsx`) renders this as a numbered chain. The mock JSX uses statuses "Pending DocuSign" and "Queued" — those are the lifecycle states this ADR formalises.

## Decision

A `DsaSignature` row is created for each of the three required signatures at DSA-draft time. Each row carries `sequence_order` (1, 2, 3), `signer_role` (a code from the `dsa_signer_role` ChoiceList: `partner_auth_signatory`, `nsr_unit_lead`, `dpo`), and `status` (a code from `signature_status`: `pending`, `signed`, `declined`).

### Lifecycle

```
DSA.status = draft                      ← created by the wizard
    │
    │ POST /api/v1/dsas/{id}/submit-for-signoff/
    ▼
DSA.status = pending_signature          ← signatures table now drives the flow
DsaSignature(seq=1).status = pending    ← envelope sent to partner via DocuSign
    │
    │ DocuSign webhook (partner signs)
    ▼
DsaSignature(seq=1).status = signed
DsaSignature(seq=2).status = pending    ← appears in NSR Unit Lead's queue
    │
    │ Console action by NSR Unit Lead
    ▼
DsaSignature(seq=2).status = signed
DsaSignature(seq=3).status = pending    ← appears in DPO's queue
    │
    │ Console action by DPO
    ▼
DsaSignature(seq=3).status = signed
DSA.status = active                     ← signed_at timestamp set
```

Any signature can transition to `declined` (with `decline_reason`); the DSA goes to `draft` and downstream signatures stay at `pending`. The wizard surfaces the decline reason so the originator can revise and resubmit.

### DocuSign integration shape

Per the decision in ADR-0011 (single account, per-OrganisationType template), the DocuSign integration lives behind an interface:

- `apps/partners/services/signature.py` defines the abstract `SignatureProvider` with `send_envelope`, `cancel_envelope`, and `handle_callback`. The in-memory `StubSignatureProvider` is the default and what CI uses.
- `apps/partners/integrations/docusign.py` contains the concrete client. It is feature-flagged via `PARTNERS_DOCUSIGN_ENABLED` (set in env / settings). In `DEBUG=True` and in CI the flag is off; the stub provider auto-completes envelopes synchronously, mirroring the production callback shape.
- The DocuSign template is selected at envelope-creation time by reading `template_key` from the active `partner_type` ChoiceOption row for the partner's type. This means the steward can swap templates (Ministry vs. NGO vs. Multilateral) through the dual-approval workflow without a code deploy — same pattern as ADR-0010's coded fields.

### Audit chain

Every state change writes an `AuditEvent`. The events the auditor needs to reconstruct the chain:

| Trigger | action | entity_type | reason |
|---|---|---|---|
| Wizard submit | `submit` | `dsa` | "submit-for-signoff: NN signatures pending" |
| DocuSign envelope sent | `envelope_sent` | `dsa_signature` | "<docusign_envelope_id>" |
| Partner signs (webhook) | `sign` | `dsa_signature` | "partner_auth_signatory · <signer_email>" |
| NSR Unit Lead signs | `sign` | `dsa_signature` | "nsr_unit_lead · <signer_username>" |
| DPO signs | `sign` | `dsa_signature` | "dpo · <signer_username>" |
| Any party declines | `decline` | `dsa_signature` | "<role> · <decline_reason>" |
| DSA activates | `activate` | `dsa` | "all three signatures complete" |
| DSA expires | `expire` | `dsa` | "effective_to passed" |
| DSA suspended | `suspend` | `dsa` | "<actor> · <reason>" |

The `dsa` AuditEvents thread through the partner's `PartnerActivityEvent` projection so the dashboard's ActivityFeed renders them.

### Self-sign-off prohibition

The same actor cannot occupy two roles in the chain on a single DSA. The service layer enforces `signer_email` uniqueness across the three signatures per DSA. Specifically, the NSR Unit Lead account cannot also be the DPO account — the constraint is checked at `submit-for-signoff` and at each sign action.

### Reminders

A Celery beat task `apps.partners.tasks.dsa_signature_reminder` runs daily. It picks up `pending` signatures older than the SLA in the spec (5 working days for the partner; 2 for NSR Unit Lead; 3 for DPO) and emits a reminder email + a `PartnerActivityEvent(kind=dpia_reminder)` row.

## Consequences

### Positive

- The wizard's "Submit for sign-off" button now does something concrete: it creates three `DsaSignature` rows and dispatches the first envelope. The mocked sequence in the JSX maps 1:1 to the production state machine.
- The audit trail is complete and reconstructable from `AuditEvent` alone — no signature evidence lives only in DocuSign.
- DocuSign can be swapped (e.g., DocuSign → SignNow, → in-console wet-ink only) by implementing the `SignatureProvider` interface. The rest of the workflow doesn't change.
- The decline path is a first-class transition. A DPO who flags a problem doesn't need to ask the partner to "send it again" — they decline with a reason; the DSA goes back to draft; the wizard reopens with the reason at the top.

### Negative

- Three signatures per DSA, three audit events per signature plus envelope/sign/activate — the AuditEvent volume grows. With 50 DSAs/year and 3 sigs each that's ~150 sig audit rows + ~50 activate rows = ~200/year. Trivial volume; flagged for completeness.
- DocuSign webhooks introduce an external trust boundary. The webhook handler verifies the DocuSign signature header and rejects unsigned or stale callbacks. Webhook secret is rotated quarterly per security policy.
- A partner whose authorised signatory rotates mid-flow has to restart the envelope. We accept this; the alternative (re-routable envelopes) puts non-trivial logic in the integration we don't want to maintain.

### Neutral

- Wet-ink scanned signatures are supported via `method=wet_ink_scanned` for partners that refuse DocuSign. The state machine is unchanged — the envelope step is skipped and the scanned PDF is attached as `evidence_doc`. Used sparingly; flagged in the dashboard with a chip so the DPO can review.

## Out of scope

- DSA renewal automation. The expiring DSA fires `PartnerActivityEvent(kind=dsa_renewal_initiated)`, and the renewal becomes a NEW DSA on the same partner. Cross-DSA carryover lives in a follow-up story.
- Multi-party amendments mid-flight. A signed DSA that needs a scope change becomes a v2 (`DSA.version` increments); the v1 keeps its audit trail.
- Bulk signing. Each DSA flows independently.

## Open items

None — the integration shape, sign-off chain, and decline path were locked with ADR-0011's four open-item decisions. Future operational tuning (reminder cadences, escalation policy) lives in runbooks under `infrastructure/runbooks/dsa-signatures.md`.

---

Signed off by:

- NSR Unit Coordinator: ____________________ Date: __________
- Data Protection Officer: ____________________ Date: __________
- Legal Counsel (MGLSD): ____________________ Date: __________
- Architecture Team: ____________________ Date: __________

End of ADR-0012.
