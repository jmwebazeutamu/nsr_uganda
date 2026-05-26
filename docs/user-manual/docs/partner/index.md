# MDA Partner / API consumer guide

You are reading this because your Ministry, Department, or Agency consumes data from the National Social Registry. This guide walks you through onboarding, the Data Sharing Agreement (DSA) lifecycle, building a data request through the DRS Query Builder, and consuming the API.

!!! info "Status"
    Partner onboarding, DSA lifecycle (ADR-0011 to 0016), the DRS Query Builder (US-S27-013), and the DRS Field Selector (US-S27-014) are **Built and in use**. The DRS delivery slices (US-099 to US-104) are **Partial** — extract generation works, full delivery + SDK examples are Planned for S6.

## What you can do today

| Task | Page |
|---|---|
| Get your partner organisation onto NSR | [Partner onboarding](onboarding.md) |
| Sign or renew a Data Sharing Agreement | [Data Sharing Agreement (DSA)](dsa.md) |
| Build a data request | [DRS Query Builder](query-builder.md) |
| Pick the fields you want delivered | [DRS Field Selector](field-selector.md) |
| Track your requests and download deliveries | [Partner portal](partner-portal.md) |
| Hit the API directly | [API reference](api-reference.md) |

## Operating model in one paragraph

Your organisation signs a Data Sharing Agreement (DSA) with MGLSD. The DSA scopes which fields you can see, which geographies, which programmes, and for how long. Your authorised users log in via your existing identity provider (SAML federation). They build a request in the Query Builder, pick fields in the Field Selector, and submit. The request lands in the steward queue for review. Once approved and signed off (by a DPO for sensitive or large extracts), the system generates the file in your chosen format and delivers it through the partner portal or your registered webhook.

Every byte of personal data delivered to you is recorded in the audit chain.

## What you cannot do

- You cannot request fields outside your DSA scope. The Field Selector greys those out with a `disabled_reason`.
- You cannot request geographies outside your DSA scope. The validator rejects extras at any UBOS level.
- You cannot bypass DPO sign-off for sensitive or large extracts. Hard gate.
- You cannot push data back to NSR through DRS. Inbound is a different surface — see [DIH connectors](../admin/connectors.md). That requires a Data Provision Agreement (DPA), not a DSA.

## Vocabulary

| Term | What it means for you |
|---|---|
| Partner | Your organisation. One row in the `Partner` table. |
| Partner code | Your stable identifier. Used in SAML mappings and as your ABAC scope key. |
| DSA | Outbound legal agreement. Scopes fields, geographies, programmes, expiry. |
| DPA | Inbound legal agreement (only if you also supply data into NSR). |
| DataRequest | One request you submit. Has fields, criteria, format, delivery method. |
| Bundle | The file the system generates and delivers to you. |

## Related

- [Partners module reference](../modules/partners.md)
- [API-DRS module reference](../modules/api-drs.md)
- ADR-0011 — Partners module
- ADR-0012 — DSA signature workflow
- ADR-0013 — Canonical Partner and DSA models
