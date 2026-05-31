# Consent (SEC) — Consent Management

!!! info "Status"
    **Built, behind a feature flag.** Epic 19 (US-CONSENT-01..18) landed 31 May 2026 (PR #1, ADR-0024). The whole surface is gated by `CONSENT_MODULE_ENABLED` and stays off in production until DPO sign-off; when off, every gate is a transparent no-op so existing flows are unchanged.

Consent Management records, governs, and honours **per-member, per-purpose** consent under the Data Protection and Privacy Act, 2019 (Uganda). It replaces the legacy single `current_consent_state` boolean with nine governed purposes, versioned statement text, a withdrawal workflow, and full audit-chain coverage.

## What it does

- Holds the **purpose catalogue** (dual-approved) and the **versioned statement text** (i18n) subjects consent against.
- **Captures** consent per purpose at intake (Web/CAPI walk-in and Kobo), and via the citizen portal.
- Runs a **withdrawal workflow** with a 30-day SLA and a DPO review queue.
- **Propagates** consent into PMT, REF, DRS, DDUP, UPD, and DIH so the registry never acts on withdrawn consent.
- Writes every state change to the **SEC audit chain**.

## Where it lives

| Path | What |
|---|---|
| `apps/consent/` | Django app (models, services, api, tasks, checks) |
| `/api/v1/consent/` | DRF surface |
| `design/v0.1/screens/consent/` | Screens: capture block, citizen dashboard, DPO queue, badge cluster, admin stubs |
| `design/nsr-mis-consent-portal.html` | Citizen portal harness (stub auth) |
| `docs/adr/0024-consent-management-module.md`, `docs/dpia.md` §14 | Governance |

## The nine purposes

| Purpose | Lawful basis | Withdrawable |
|---|---|---|
| REGISTRATION | Consent | Yes (hard gate at intake) |
| ELIGIBILITY | Consent | Yes (PMT gate) |
| REFERRAL | Consent | Yes (REF gate) |
| PAYMENTS | Consent | Yes |
| COMMUNICATIONS_SMS | Consent | Yes |
| COMMUNICATIONS_USSD | Consent | Yes |
| RESEARCH | Consent | Yes (DRS gate) |
| GRIEVANCE_CONTACT | Consent | Yes |
| STATISTICS | Statistical exemption | **No** (aggregate-only) |

NIRA identity verification is a **public-task activity** (IDV), not a consent purpose (DPIA §14.2).

## Capture states

`Granted` · `Refused` · `Withdrawn` · `Pending review` · `Pending re-consent` — plus a display-only **inferred** state on the household card for legacy households that gave the broad interview consent but have no per-purpose record yet.

## Endpoints

| Endpoint | Verb | Purpose |
|---|---|---|
| `/api/v1/consent/purposes/` | GET, POST | Purpose catalogue (dual-approval actions: submit / activate / reject / retire) |
| `/api/v1/consent/statements/` | GET, POST | Statement versions (submit / activate; `reconsent_count`) |
| `/api/v1/consent/members/{id}` | GET | Per-purpose consent matrix |
| `/api/v1/consent/members/{id}/capture` | POST | Capture consent (runs AC-CONSENT-* checks) |
| `/api/v1/consent/members/{id}/withdraw` | POST | Open a withdrawal ticket (idempotent per day) |
| `/api/v1/consent/members/{id}/history` | GET | Append-only consent history (audit-linked) |
| `/api/v1/consent/withdrawal-tickets/` | GET | DPO withdrawal queue; `/{id}/decide/` records a decision |
| `/api/v1/consent/coverage` | GET | DPO coverage KPIs |

The OpenAPI contract is at `docs/openapi/consent.yaml`.

## How operators use it

- **Walk-in / CAPI capture** — the Household capture form's *Consent* section captures the registration gate (a refusal ends the intake with `declined_consent` — no record is created), the optional per-purpose toggles, and the capture method (verbal requires a witness).
- **Household detail → Consent tab** — shows the live per-purpose status card and a **Manage / capture consent** action that opens the citizen consent screen wired to that household's members (capture, withdraw, history).
- **Admin Console → Consent (SEC)** — Purposes, Statement versions, the DPO **Withdrawal queue**, and the Coverage dashboard.
- **Citizen portal** (`/portal/consent/`, stub auth) — the citizen dashboard and intake capture screens.

## Key gates (inert until the flag is on)

| Module | Gate |
|---|---|
| INT | REGISTRATION refused → intake terminated (`declined_consent`) |
| DIH | Promotion writes captured/fast-track consent; unratified DPA holds fast-track |
| PMT | Recompute blocked when head ELIGIBILITY is Withdrawn / Pending re-consent |
| REF | `send_referral` blocked when REFERRAL is Withdrawn/Refused |
| DRS | Extract excludes members lacking the DSA-mapped purpose (SQL-layer) |
| DDUP | Merge reconciles consent (union of grants; any withdrawal wins; conflicts block) |
| UPD | Head-change opens a REGISTRATION re-capture sub-task |

## DQA rules

`AC-CONSENT-MANDATORY`, `AC-CONSENT-METHOD-VALID`, `AC-CONSENT-PURPOSE-VERSION-CURRENT`, `AC-CONSENT-CAPTURE-TIMESTAMP-PLAUSIBLE`, `AC-CONSENT-MINOR-PROXY-PRESENT` — seeded **DRAFT** by `scripts/seed_dqa_consent_rules.py`; the DPO ratifies before activation (`--activate`).

## Before it goes live

The flag flips on in production only after the DPO signs off on the seeded purpose catalogue + statement texts (CONSENT-O-01), the 30-day SLA (CONSENT-O-03), and DPA scopes for any fast-track source (CONSENT-O-08); the seeded DQA rules are activated; and the audit-chain integrity job covers `consent_record_version`.

## See also

- [SEC — Security](sec.md) for the audit chain this module writes into.
- ADR-0024 and DPIA §14 for the governance record.
