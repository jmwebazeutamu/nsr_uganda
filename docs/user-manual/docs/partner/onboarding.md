# Partner onboarding

!!! info "Status"
    **Built and in use** — Partner model + DSA workflow live (ADR-0011/12/13). DocuSign integration is behind the `PARTNERS_DOCUSIGN_ENABLED` flag (default off); the in-memory stub is the default.

This is the one-time checklist to get your MDA on the NSR.

## Step 1 — Sponsor and lawful basis

Confirm internally:

- Your **sponsor** at MGLSD. Usually the NSR Unit Coordinator.
- Your **lawful basis** for receiving NSR data under DPPA 2019. Most MDA flows use the public-task basis (DPPA 2019 §11).
- Your **purpose**. The DSA pins this. Vague purposes ("for analysis") will be sent back.

## Step 2 — Partner record

The NSR Unit creates a `Partner` row.

| Field | Example |
|---|---|
| `code` | `MOH` (your stable identifier) |
| `name` | Ministry of Health |
| `type` | `mda` (MDA, NGO, donor, research) |
| `lawful_basis_ref` | DPPA 2019 §11 |
| `dpia_url` | Link to your DPIA |
| `contact_email` | DSA-signing contact |
| `data_protection_officer` | Your DPO name + email |

Visible in the Admin Console at `/admin-console/partners/`.

## Step 3 — DSA scope

You and the NSR Unit agree the scope. The DSA carries:

- **Field scope**: which canonical fields you can request. Pulled from the catalogue.
- **Geographic scope**: M2M against `GeographicUnit` at any level (region, sub-region, district, county, sub-county, parish, village). If you list rows at any level, that level is restricted to those codes; levels with no rows are unrestricted.
- **Programme scope**: which programmes the household must be active in.
- **Sensitivity ceiling**: `public` / `internal` / `personal` / `sensitive`.
- **Expiry date** and **renewal cadence**.

See [Data Sharing Agreement (DSA)](dsa.md) for the lifecycle.

## Step 4 — Identity federation

SAML 2.0. Your IdM publishes the metadata; the NSR Unit imports it into the Keycloak `nsr-mis` realm.

| SAML attribute | Maps to |
|---|---|
| `eduPersonAffiliation` | Realm role `PARTNER_ANALYST` or `PARTNER_DPO` |
| `eduPersonOrgDN` | Realm custom attribute resolving to `Partner.code` |

Once federation is live, your users sign in at `/console/login` with their existing org credentials.

## Step 5 — Test with the sandbox DSA

Every partner gets a `sandbox` DSA on a synthetic dataset. Use it to:

- Verify your IdM mapping carries the right Partner code.
- Walk through the Query Builder end-to-end.
- Confirm your delivery target (portal download or webhook) works.

The sandbox dataset is regenerated nightly from a synthetic seed. It does not contain real personal data.

## Step 6 — Sign the production DSA

The Admin Console DSA tab kicks off the signature flow. Today's default is the in-memory stub (you click "Mark as signed"); production runs through DocuSign once `PARTNERS_DOCUSIGN_ENABLED=True` and the MoU lands. See [ADR-0012](../appendices/adrs.md).

When the DSA is `active`, your users can submit production DataRequests.

## Status check

| What | Where to verify |
|---|---|
| Partner row exists | `/admin-console/partners/<your-code>/` |
| DSA is active | `/admin-console/partners/<your-code>/dsas/` |
| Your SAML user can log in | `/console/login` |
| Sandbox DataRequest succeeds | `/console/drs` |

## Related

- [Data Sharing Agreement (DSA)](dsa.md)
- [Partner portal](partner-portal.md)
- ADR-0011 — Partners module
- ADR-0013 — Canonical Partner and DSA models
