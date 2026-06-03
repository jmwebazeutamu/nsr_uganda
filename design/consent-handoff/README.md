# NSR Consent Management — Developer Handoff

This bundle contains the **hi-fi design prototypes** for the National Social
Registry (NSR) Consent Management screens, plus everything needed to run them
and build production code from them.

These are **clickable HTML/React prototypes**, not production code. They are the
visual + interaction contract: build the real thing to match what these render
and do.

---

## 1. What's in this folder

| File | Role |
|---|---|
| `Consent - Intake Capture.html` | **Screen 1** preview — open in a browser |
| `Consent - Citizen Dashboard.html` | **Screens 2 & 3** preview |
| `Consent - DPO Withdrawal Queue.html` | **Screen 4** preview |
| `screens-consent-capture.jsx` | Screen 1 component (intake consent capture) |
| `screens-consent-citizen.jsx` | Screens 2 + 3 (citizen dashboard + withdrawal modal) |
| `screens-consent-dpo-queue.jsx` | Screen 4 (DPO withdrawal review queue) |
| `consent-shared.jsx` | Shared consent vocabulary: the 9 purposes, status chips, lawful bases, languages, reason lists, statement copy, helper components |
| `app-consent.jsx` | Minimal preview router (mounts a screen by `window.__defaultScreen`) |
| `consent-boot.js` | Boot diagnostic — prints on-screen if a script fails to mount (dev aid only; not needed in production) |
| `components.jsx` | **Existing NSR design-system kit** (Icon, Chip, KPI, Modal, Field, PageHeader, AuditDrawer, ActionBar, Toast). Dependency — do not fork. |
| `styles.css` | **Existing NSR design tokens + base styles.** All colors/spacing/type come from here. |
| `SPEC - consent_management_design_prompt.md` | The original design brief these screens implement |

---

## 2. How to run the prototypes

No build step. Each `.html` file loads React + Babel from a CDN and compiles the
`.jsx` in the browser. Just:

1. Serve this folder over HTTP (Babel won't fetch `.jsx` over `file://`):
   ```
   npx serve .        # or:  python3 -m http.server
   ```
2. Open `http://localhost:<port>/Consent - Intake Capture.html`

> If a screen is blank, open the browser console. `consent-boot.js` will also
> print the failure reason on the page (which script errored, whether React /
> Babel loaded, whether the screen component is defined).

### Load order (every HTML follows this)
```
styles.css
→ React, ReactDOM, Babel (CDN, pinned versions w/ integrity hashes)
→ components.jsx        (design-system kit — defines window.Icon, Chip, …)
→ consent-shared.jsx    (consent vocabulary — defines window.PURPOSES, ConsentStateChip, …)
→ screens-consent-*.jsx (the screen — defines e.g. window.ConsentIntakeScreen)
→ app-consent.jsx       (router — reads window.__defaultScreen, mounts the screen)
```
Each `.jsx` runs in its own Babel scope and shares components via `window`
(`Object.assign(window, {…})` at the bottom of each file). Keep that pattern.

---

## 3. The 4 screens (and the user stories they anchor)

| # | Screen | Anchor story | Context |
|---|---|---|---|
| **S1** | Intake consent capture | `US-S26-CONSENT-CAPTURE-WEB` / `-CAPI` | Enumerator/CDO, before any personal data is captured |
| **S2** | Citizen consent dashboard | `US-S26-CONSENT-CITIZEN-VIEW` | Citizen self-service portal / Parish Chief assisted |
| **S3** | Withdrawal request flow | `US-S26-CONSENT-CITIZEN-WITHDRAW` | Two-step modal launched from S2 |
| **S4** | DPO withdrawal queue | `US-S26-CONSENT-DPO-WITHDRAWAL-QUEUE` | Data Protection Officer back-office |

### Key behaviours to preserve in production
- **S1** — Consent is captured *before* any personal data. The primary
  Registration Yes/No is a hard gate; "No" routes to a controlled-reason refusal
  that ends the intake with a **Declined consent** outcome (still audit-logged).
  Optional purposes are individually toggleable. Capture method
  (signature / thumbprint / verbal-witnessed / digital) drives a method-specific
  capture step; verbal requires a witness name + role.
- **S2** — Per-member, per-purpose consent table. `Withdraw` is only offered for
  purposes that are **withdrawable AND currently Granted**. Public-task /
  statistical-exemption purposes are **not withdrawable** (shown locked, with the
  DPPA provision in a tooltip).
- **S3** — Two steps: (1) plain-language consequences + optional reason →
  (2) confirmation with the **30-day statutory decision clock** and a ticket ID.
  Submit is idempotent (retry must not create a duplicate ticket).
- **S4** — Queue with SLA countdown bars, three-column detail
  (consent history · withdrawal impact · decision panel). Decisions: Confirm /
  Override (public-task) / Request clarification / Hold. **Bulk Confirm** is
  enabled only when all selected tickets share one Consent-basis purpose, have
  zero active referrals, and are ≤ 50; > 1000 requires a second approver.

---

## 4. Data model used by the prototypes

### The 9 consent purposes (`consent-shared.jsx → PURPOSES`)
| Code | Name | Lawful basis | Withdrawable |
|---|---|---|---|
| `REGISTRATION` | Registration | Consent | yes (primary) |
| `REFERRAL` | Programme referral | Consent | yes |
| `PAYMENTS` | Payments | Consent | yes |
| `COMMUNICATIONS_SMS` | SMS notifications | Consent | yes |
| `COMMUNICATIONS_USSD` | USSD self-service | Consent | yes |
| `RESEARCH` | Research | Consent | yes |
| `GRIEVANCE_CONTACT` | Grievance contact | Consent | yes |
| `IDENTITY_VERIFICATION` | Identity verification | **Public task** (DPPA §7(2)(b)(i)) | **no** |
| `STATISTICS` | National statistics | **Statistical exemption** (DPPA §7(2)(e)) | **no** |

> ⚠️ **Open question for the product owner:** the brief names 7 consent purposes
> explicitly; the last two (`IDENTITY_VERIFICATION`, `STATISTICS`) were
> **inferred** to complete the set of nine and to demonstrate the non-withdrawable
> public-task path. **Confirm these against `consent_management_scope.md`** before
> building.

### Consent record states → chip tone (`CONSENT_STATE_TONE`)
`Granted` (green/data) · `Refused` (red/danger) · `Withdrawn` (neutral) ·
`Pending review` (amber/quality) · `Pending re-consent` (blue/update)

### Withdrawal ticket states (`TICKET_STATE_TONE`)
`Open` · `In DPO review` · `Confirmed` · `Public-task override` ·
`Clarification requested` · `Closed`

### Languages (`LANGUAGES`)
English (real copy) + Luganda, Runyankole, Acholi, Lusoga, Lugbara, Ateso.
The switcher is functional; non-English statement bodies are **placeholders** —
supply real translations of statement v3 for production.

All sample households, members, tickets, and audit events in the screen files are
**mock data** for the prototype. Replace with API-backed data.

---

## 5. Design system — do NOT invent styles

Everything visual derives from **`styles.css`** (the NSR token set) and
**`components.jsx`** (the shared kit). Reuse them; don't introduce new colors,
spacing, or one-off components.

- Module family for consent is **SEC (security)** → accent `--accent-system`
  (`#37474F`) on `--accent-system-bg` (`#F0F4F8`).
- Status is **never** signalled by color alone — a text label always accompanies
  the chip (WCAG 2.1 AA).
- Lawful basis renders as a quiet outline chip (`BasisChip`) so it reads as
  read-only metadata, not a toggleable state.

---

## 6. Console integration

In the source project these consent screens are wired into the navigable
**Admin Console** under a new **"Consent (SEC)"** sidebar group:
- **Withdrawal queue** → live (Screen 4)
- **Purpose catalogue / Statement versions / Coverage dashboard** → roadmap
  stubs (Screens 5, 6, 9 — not yet built)

---

## 7. Status / scope

**Built (this pass):** S1, S2, S3, S4 — desktop primary states, polished.

**Not yet built (next passes):**
- Responsive states: CAPI tablet (one-question-per-screen), mobile portal
- Empty / error / loading / audit-detail states per screen
- Screens 5–9 (purpose catalogue, statement versioning, re-consent campaign,
  coverage dashboard, etc.)

**Open questions to resolve before/while building:**
1. Confirm the two inferred purposes (§4 above) against the scope document.
2. Confirm the consent screens' production home in the console nav (prototype
   places the DPO queue under Admin → Consent (SEC)).
3. Supply real translated statement copy for the 6 non-English languages.
