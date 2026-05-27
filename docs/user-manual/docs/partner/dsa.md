# Data Sharing Agreement (DSA)

!!! info "Status"
    **Built and in use** — DSA lifecycle, scope edit, renewal (ADR-0012, 0013, 0016) live. DocuSign integration is gated behind `PARTNERS_DOCUSIGN_ENABLED`.

A DSA scopes what you can pull. One DSA per purpose. Multiple DSAs per partner are fine.

## The DSA lifecycle

```
draft → pending_signature → active → expiring_soon → expired
                          ↘ rejected                ↘ renewed → active
```

| State | Who acts | Next |
|---|---|---|
| `draft` | NSR Unit + you on scope agreement | `pending_signature` |
| `pending_signature` | You sign; NSR Unit countersigns | `active` |
| `active` | Used in every DRS request | `expiring_soon` (30 days before expiry) |
| `expiring_soon` | You renew or let it expire | `renewed` or `expired` |
| `expired` | Terminal; no new requests | n/a |

The renewal flow (ADR-0016) carries the same scope forward unless you change it explicitly.

## Fields

| Field | Notes |
|---|---|
| `partner` | FK to `Partner` |
| `purpose` | Free text. Pinned at signature; changes need a renewal |
| `field_scope` | M2M of canonical field codes |
| `geographic_scope` | M2M of `GeographicUnit` at any level |
| `programme_scope` | M2M of `Programme` |
| `sensitivity_ceiling` | `public` / `internal` / `personal` / `sensitive` |
| `volume_cap_per_month` | Optional row-count ceiling |
| `effective_from` | Date the DSA goes live |
| `expiry_date` | Date it stops |
| `signed_at` | UTC timestamp of countersign |
| `docusign_envelope_id` | When DocuSign is enabled |

## Scope edit (ADR-0016)

You can edit scope on an active DSA without a full renewal, with constraints:

- **Narrowing** (removing fields, geographies, programmes) takes effect immediately on save.
- **Widening** (adding) requires a fresh signature from your DSA signatory and a DPO countersign. Until both sign, the new scope sits in `pending_signature`, and the original active scope is still enforced.

This is so partners can drop scope freely (DPPA minimisation principle) but can't unilaterally expand it.

## What the system does with the DSA

Every DataRequest you submit is validated against your active DSA scope:

| Check | Effect when violated |
|---|---|
| Requested fields ⊆ field scope | Field Selector greys out, validator rejects on submit |
| Requested geographies ⊆ geographic scope (per UBOS level) | Validator rejects with `geo_out_of_scope` |
| Requested programmes ⊆ programme scope | Validator rejects with `programme_out_of_scope` |
| Sensitivity of any requested field ≤ ceiling | Field Selector greys out |
| Row count ≤ remaining monthly cap | Validator rejects with `volume_cap_exceeded` |
| Current date in `[effective_from, expiry_date]` | Validator rejects with `dsa_inactive` |

See US-S27-016 in `/docs/api_changelog.md` for the geographic-scope enforcement details.

## DPO sign-off triggers

Some requests need a DPO countersign before the file generates:

- Sensitivity level `sensitive` selected.
- Row count above the DSA's `dpo_review_threshold` (default 1000).
- Geographic scope narrower than parish (i.e. village-level extracts).

The DPO Console (`screens-dpo.jsx → DPOScreen`) is where DPOs see the queue.

## DSA in the audit chain

Every DataRequest carries the DSA ID it was validated against. The audit chain records:

- `data_request_submitted` with the DSA snapshot at submit time.
- `data_request_approved` with the approver username.
- `data_request_delivered` with the row count, file size, and delivery target.

Reviewing your historical extracts is a `data_request_read` action on your account.

## Email notifications (v0.3)

You'll receive email at every milestone of the DSA lifecycle. Make sure `Partner.primary_email` is set to a monitored inbox — the system uses it as the partner-side recipient.

| Event | What we send | When |
|---|---|---|
| DocuSign envelope | DocuSign-branded "Please sign" email to your Authorized Signatory | When NSR Unit submits the DSA for sign-off (handled by DocuSign, not NSR MIS) |
| Step advances to NSR Unit Lead / DPO | "DSA awaits your signature" — internal-only | After step 1 / step 2 signs |
| **DSA ACTIVATED** | "DSA `<ref>` is now ACTIVE" — to every signer + `Partner.primary_email` | When step 3 (DPO) signs |
| **DSA DECLINED** | "DSA `<ref>` was DECLINED at step `<N>`" with verbatim reason — to every signer + `Partner.primary_email` | When any signer declines. The DSA reverts to DRAFT for revision. |

Every notification attempt is itself in the audit chain (`dsa.signoff.notified` / `dsa.activation.notified` / `dsa.decline.notified`). If an email fails to send, the DSA still activates / declines on the audit side — the system never blocks the workflow on a flaky relay.

## Related

- [Partner portal](partner-portal.md) — where you see your DSA status
- [DRS Query Builder](query-builder.md)
- [Partners module reference](../modules/partners.md)
- ADR-0011, ADR-0012, ADR-0013, ADR-0016
