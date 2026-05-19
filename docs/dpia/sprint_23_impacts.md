# DPIA — Sprint 23 Impact Recording

**Status**: For DPO review.
**Last updated**: 2026-05-19.
**Covers**: US-S23 — partners module (commits 001–015).
**Parent document**: `/docs/dpia.md` (initial DPIA, 2026-05-14).
**Previous instalment**: `/docs/dpia/sprint_22_impacts.md` (Sprint 22).

---

## Sprint 23 stories with personal-data impact

### US-S23-004 / 005 — Partner + PartnerContact models

- **New processing activity**: A new `apps/partners/` app introduces persistent storage for partner organisations and their named contacts. The `Partner` row carries operational metadata only — no individual-level PII. The `PartnerContact` row carries the personal data of the four required contacts on the partner side: Authorised Signatory, Data Steward, Partner DPO, IT/Security contact.
- **Personal-data categories touched (PartnerContact)**:
  - **Identification** — `full_name`, `title`, `email`, `phone_e164`. Personal data.
  - **Identification + sensitive** — `nin_value` (encrypted at rest per ADR-0002), `nin_hash`, `nin_last4`, `nin_verified_at`. The NIN itself is the sensitive value; the trio mirrors `Member.nin_*` so the same DPIA controls (column-level AES-256, hash for joins, last-4 for display) apply.
- **Lawful basis**: Public task. Capturing the signatory's NIN is the legal foundation of the DSA — DPPA 2019 §§17, 21 require positive identification of the data controller's representative.
- **Data minimisation**: NIN is optional on `PartnerContact` (not every partner contact is Ugandan). When present it is the only sensitive value collected for the contact.
- **Retention**: Mirrors `Member.nin_*` policy (SAD §8.5).
- **Subject-access**: PartnerContact rows respond to DSAR like any operator record. The encrypted `nin_value` is returned only via the NIN-trio helper, never plaintext.

### US-S23-006 — DataSharingAgreement + DsaSignature

- **Processing activity**: The DSA carries the legal envelope; the DsaSignature rows carry per-step signatory metadata (`signer_name`, `signer_email`, optionally `decline_reason`).
- **Personal-data categories touched (DsaSignature)**:
  - **Identification + Contact** — `signer_name`, `signer_email`. Personal data; routed via DocuSign (Partner Authorised Signatory) or in-console click action (NSR Unit Lead, DPO).
  - **Operational metadata** — `docusign_envelope_id`, `signed_at`, `decline_reason`. Not personal data on its own; reads as a single audit row.
- **Lawful basis**: Public task. The three-step sign-off chain is a DPPA 2019 §17 record-of-processing artefact.
- **Self-sign-off prohibition**: ADR-0012 §"Self-sign-off prohibition" — the service layer rejects identical `signer_email` across the three signatures on a DSA. Both a service check at submit-for-signoff and a database-level `UniqueConstraint(dsa, signer_email)` enforce this.
- **Audit chain**: Every state change (`submit`, `envelope_sent`, `sign`, `decline`, `activate`, `suspend`) writes an `AuditEvent`. Verified end-to-end in `tests/integration/test_partners_e2e.py::TestPartnerWizardE2E`.

### US-S23-010 — DSA signature workflow

- **DocuSign integration**: Provider abstracted behind `SignatureProvider`; the default `StubSignatureProvider` keeps PII inside the registry (no external network call) for dev and CI. The concrete `DocuSignProvider` is gated by `PARTNERS_DOCUSIGN_ENABLED` (default false). When enabled it transmits the signer's `signer_name`, `signer_email`, the DSA reference, and the rendered DSA PDF to DocuSign. DocuSign is the data processor under a separately-signed agreement with MGLSD; **scope**: identification + contact data of the three signatories per envelope.
- **For DPO decision**: confirm the DocuSign data-processor agreement covers EU GDPR + Uganda DPPA 2019. The flag stays off in production until the agreement is in place.

### US-S23-007 — PartnerUsageDaily + activity projection

- **Processing activity**: Per-day rollup of rows delivered + requests count per partner, populated by a Celery beat task (lands in US-S23-017). The rollup table aggregates DRS deliveries — it never stores individual household IDs. The activity projection over `AuditEvent` (`apps/partners/services/activity.py`) is a read-side view; no new storage.
- **Personal-data categories touched**: None new. Aggregate counts + audit-event metadata.

### US-S23-008 / 009 — API surface

- **Read endpoints** emit `record_read` / `dashboard_read` AuditEvents through `AuditReadMixin` for `/api/v1/partners/`, `/api/v1/dsas/`. Aggregation endpoints (`/summary/`, `/renewals/`, `/sector-mix/`, `/top-consumers/`) read against the rollup table and `DataSharingAgreement` only — no per-row PII reads — so they do not need additional audit instrumentation beyond the standard request log.

### US-S23-014 / 015 — Lint gate + end-to-end tests

- No personal-data impact. The CI gate and integration tests increase the confidence that future edits stay within the rules described above.

---

## DPO review checklist

- [ ] **DocuSign DPA in place** before `PARTNERS_DOCUSIGN_ENABLED` is flipped on in production.
- [ ] **NIN-on-PartnerContact policy**: confirm that capturing the four signatory NINs at onboarding (and not at every operator-side action) satisfies the principle of data minimisation. Recommendation: NIN is optional for non-Ugandan signatories; required for the three GoU-side roles (NSR Unit Lead, DPO).
- [ ] **Cross-border data transfer**: DocuSign processes data in the US/EU; the partner's signer_name + signer_email cross borders during envelope dispatch. Confirm the DSA template informs the signatory.
- [ ] **Retention pledge on DSA**: the `retention_days` field defaults to 180. Confirm whether the existing 180-day registry policy applies, or whether DSA-specific retention should differ.

---

## Sign-off

- DPO: ____________________ Date: __________
- Engineering Lead: ____________________ Date: __________
- Architecture Team: ____________________ Date: __________
