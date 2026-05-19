# ADR-0011: Partners module — registry of partner organisations, DSAs, and programmes

- **Status**: Proposed
- **Date**: 19 May 2026
- **Owner**: NSR MIS Architecture Team
- **Decision-makers**: NSR Unit Coordinator, Data Protection Officer, Engineering Lead, Partner Affairs Lead
- **References**: SAD v0.6 §11.6 (Partner & DSA registry), §11.7 (DRS); ADR-0009 (admin floor / console ramp); ADR-0010 (coded fields via ChoiceList); ADR-0012 (DSA signature workflow); US-S23 (this sprint pack); design/v0.1/partners-source/.

---

## Context

A "partner" in NSR MIS is any external organisation that exchanges data with the registry under a signed Data Sharing Agreement (DSA): line ministries (OPM, MoH, MoES), agencies (UBOS, NIRA), multilaterals (WFP, UNICEF, World Bank), NGOs (Red Cross, BRAC), private operators (banks acting as cash rails), academics, and offices of constitutional bodies. Today there is no structured record of who they are, what programmes they operate, what data they receive, or whether they are within their DSA budget. Operationally this is tracked on a spreadsheet by the Partner Affairs Lead; the DSA documents themselves live in shared drives.

The design at `design/v0.1/partners-source/` introduces a Partners dashboard and a 6-step registration wizard (Organisation → Signatories → Programmes → DSA scope → Compliance → Review & sign). The mock data in the JSX defines the entities, the lifecycle states, and the surfaces operators interact with — that mock is the design contract this module implements against.

## Decision

A new Django app `apps/partners/` houses the registry. It owns six concepts:

- **Partner** — the organisation. Coded `type`, `sector`, `status`, `tone` fields.
- **PartnerContact** — the people on the partner side: Authorised Signatory, Data Steward, Partner DPO, IT/Security contact. Coded `role` field. NIN encrypted at rest per ADR-0002.
- **Programme** — what the partner runs that consumes NSR data: cash transfer, service, in-kind, voucher, study. Coded `kind` and `status`. Geographic scope at any level via M2M to `GeographicUnit`.
- **DataSharingAgreement (DSA)** — the legal envelope. Coded `status`, `sensitive_data_handling`. M2M to `Programme` and to `GeographicUnit`. Entity and field scope as JSON. Optional `monthly_row_budget` (nullable for providers).
- **DsaSignature** — the three-step sign-off chain on the DSA, with `signer_role`, `method`, `status`, `sequence_order`. The workflow is detailed in ADR-0012.
- **PartnerUsageDaily** — a per-day rollup of rows delivered + requests count, populated by a Celery beat task. The dashboard's `UsageBar` and `RenewalTimeline` read 30 days from this table.

**`PartnerActivityEvent` is not a new table.** Activity is a read-side projection over `apps.security.AuditEvent`, filtered by entity_type and shaped into the JSX feed's expected fields. This honours the "audit on everything personal" CLAUDE.md rule without duplicating storage.

### The four open-item decisions

1. **DocuSign account: single shared account, per-OrganisationType template.** One DocuSign account simplifies ops; each row in the `partner_type` ChoiceList carries a `template_key` payload identifying the right branded envelope template. NGO templates look different from Ministry templates; the template_key field on the option lets the steward extend the catalogue without touching code.

2. **`monthly_row_budget` counts rows DELIVERED.** Post-filter, post-quality-check rows actually returned by DRS. That's what AC-DPO-VOL governs — actual PII flow. Requested-rows can be observed separately from API access logs if it ever becomes interesting.

3. **API-provider partners (NIRA) skip the budget/usage path entirely.** Status `provider` means data flows IN to NSR, not OUT. `monthly_row_budget` is nullable; no `PartnerUsageDaily` rows are produced; breach detection skips them. The model documents this with a `pre_save` invariant: `status == "provider"` ⇒ `monthly_row_budget IS NULL`.

4. **Geographic scope is M2M to `GeographicUnit` at any level.** A DSA can list "Karamoja sub-region" (one row at sub_region level), "Pader + Gulu districts" (two rows at district level), or a mix. The DRS scope check resolves household membership by walking up the geo tree. The wizard surfaces sub-region selection as the default but lets the operator drop to district when needed.

### Coded fields are DB-driven

Per ADR-0010 §1, every coded field on every model in this app is a plain `CharField(max_length=32)` storing the raw `ChoiceOption.code`. The single source of truth lives in `apps/reference_data/`. The 14 new ChoiceLists this sprint seeds are listed in `apps/reference_data/seeds/choice_lists_v1.json`:

```
partner_type, partner_sector, partner_status, ui_tone, partner_contact_role,
programme_kind, programme_status, dsa_status, sensitive_data_handling,
dsa_signer_role, signature_method, signature_status, partner_activity_kind,
dsa_wizard_step
```

Field-map entries in `apps/data_management/choice_field_map.py` register each coded field. A new system check `data_management.E001` (US-S23-003) fails CI if any field declared in the map carries `choices=`, closing the door on new `TextChoices` introductions across the whole codebase.

### Audit chain

Every state change on Partner, Programme, DSA, and DsaSignature writes an `AuditEvent` with `entity_type` = the lowercase model name, `entity_id` = the ULID, `action` ∈ {`create`, `submit`, `sign`, `decline`, `activate`, `suspend`, `breach_detected`, `renew`, …}, and a `reason` describing the trigger. The console screen reads the audit chain via the `PartnerActivityEvent` projection. Auditors and DPO consume the same data through the admin's AuditEvent changelist (per ADR-0009 §1).

### API surface

A focused read/write surface lands at `/api/v1/partners/` and `/api/v1/dsas/`. The dashboards (`/summary/`, `/renewals/`, `/sector-mix/`, `/top-consumers/`) are aggregation endpoints — they read the registry plus the usage table. The signature pipeline is exposed via `POST /api/v1/dsas/{id}/submit-for-signoff/`; downstream transitions are driven by DocuSign callbacks (ADR-0012) and console actions by the NSR Unit Lead and DPO.

The choice-list bundle endpoint at `/api/v1/reference-data/choice-list-bundle/` (US-S22-005e) is extended to accept a `?lists=` filter so the wizard fetches just the option sets it needs. The wizard never holds hardcoded option arrays; a `useChoiceList` React hook is the only path to dropdown data.

## Consequences

### Positive

- Single source of truth for partners, DSAs, and programmes; eliminates the spreadsheet.
- DSA budgets become enforceable: the breach detector emits `PartnerActivityEvent(kind=dsa_breach)` and flips the partner to status `alert` automatically.
- The 6-step wizard becomes a real workflow: each step persists to the database; abandoned drafts can be resumed.
- The partner's own portal (US-S12-010) can read the same registry through ABAC filters scoped to their own ULID.
- Auditors and the DPO see partner activity in the same `AuditEvent` chain as every other registry operation.

### Negative

- New surface to maintain: 7 models, ~12 API endpoints, 14 ChoiceLists, plus the signature workflow. We mitigate by feature-flagging behind `PARTNERS_MODULE` so the rollout is gated.
- DocuSign is a new external dependency. The integration is stubbed behind an interface (`apps/partners/services/signature.py`) per ADR-0012; the concrete client at `apps/partners/integrations/docusign.py` is feature-flagged and the in-memory stub is the default in CI.
- Migrating existing partner records from the spreadsheet is operational work for the Partner Affairs Lead — out of scope for this ADR.

### Neutral

- The Provider partner pattern (NIRA-only today) is documented but unused beyond that one row. Future identity / data feeds that follow the same shape (e.g., URSB, KCCA) will reuse it.
- The Programme model's `kind` ChoiceList overlaps slightly with the existing `gov_programme` list in the questionnaire seed; we deliberately keep them separate — `gov_programme` is what a household reports being enrolled in, `programme_kind` is what a partner runs. Different surfaces, different governance.

## Out of scope

- The partner-facing portal (US-S12-010). This ADR covers only the MGLSD-internal side.
- DRS scope enforcement against the new DSA fields. That logic lives in `apps/data_requests/` and lands in a follow-up story (US-S23-XXX, TBD). The Partners module surfaces the contract; DRS reads it.
- PMT, DDUP, DQA. Unchanged. The CLAUDE.md anti-pattern about not running PMT in DIH continues to hold; partners do not get to see raw PMT scores unless their DSA's `field_scope` explicitly includes the PMT group.

## Open items

None — the four items the user-facing spec flagged ("stop and ask before deciding") were resolved before authoring this ADR.

---

Signed off by:

- NSR Unit Coordinator: ____________________ Date: __________
- Data Protection Officer: ____________________ Date: __________
- Engineering Lead: ____________________ Date: __________
- Partner Affairs Lead: ____________________ Date: __________

End of ADR-0011.
