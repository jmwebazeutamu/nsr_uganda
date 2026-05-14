# NSR MIS — UI Design Brief

**For submission to Claude Design (claude.ai/design)**

Version 0.1 · 14 May 2026 · Prepared by the NSR MIS Architecture Team for the Ministry of Gender, Labour and Social Development (MGLSD), Republic of Uganda.

This brief is the design-context document Claude Design should ingest at onboarding. Paste the whole file at the start of a new project, or upload it as the design system source. Sections 11 and 12 contain ready-to-paste prompts for each priority screen.

---

## 1. Project context

The National Social Registry (NSR) Management Information System is the digital platform that captures, validates, scores, and shares socio-economic data on households and individuals in Uganda. It serves as the single national entry point for social protection programmes operated by the Ministry of Gender, Labour and Social Development (MGLSD), the Office of the Prime Minister (OPM), the Parish Development Model (PDM), the Northern Uganda Social Action Fund (NUSAF), and partner agencies including WFP, UNICEF, and the World Bank.

Target scale at full national load: 12 million household records, covering 9 sub-regions and roughly 70,500 villages. Operating organisation: NSR Unit within MGLSD, hosted on the NITA-U Government Data Centre.

The platform is built around 12 modules plus 4 sub-modules. The UI must serve 11 distinct operator roles and three citizen-facing channels (parish walk-in receipt, USSD pre-registration in Release 2, web portal status check in Release 3).

Companion documents already produced: a 56-page Solution Architecture Document (SAD v0.6), a 5-page Entity Relationship Diagram (ERD v0.6), and a 114-story product backlog (16 epics). Excerpts and references appear throughout this brief.

---

## 2. Design principles

1. **Government tone, not consumer playfulness.** This is official infrastructure. Calm, confident, restrained. No celebratory animations, no marketing copy.
2. **Information density before whitespace.** Operators at parish offices need to see a lot at once on modest screens. Default to compact spacing.
3. **Tables are the primary surface.** Most operator screens are list-detail or table-comparison. Optimise tables first.
4. **Status before story.** Every record carries a status badge. The user should be able to scan a screen and know what state things are in within two seconds.
5. **Every action is auditable.** Provide reason-required prompts on rejection, approval, and override. Surface the audit trail in a side panel, not buried.
6. **Citizen-facing flows are short.** A walk-in citizen at a parish office should not wait while the operator does five clicks. Aim for one-page capture, one-page receipt.
7. **Provisional vs. confirmed.** The provisional Registry ID is real but pending. Show that clearly with the chip vocabulary in Section 8.
8. **Bilingual-ready.** English first; the layout must accommodate Luganda, Runyankole, Acholi, and Lusoga strings that can be 20% longer than English.
9. **Low-bandwidth friendly.** Avoid heavy hero images, video, or large icon sets that slow CAPI tablets on 2G or 3G.
10. **Accessibility is not optional.** WCAG 2.1 AA for the operator web console; large-text mode and Talkback on the CAPI Android app.

---

## 3. Audiences and roles

### Operator roles (web console)

| Role | Primary screens | Authorisation |
|---|---|---|
| Field Enumerator | CAPI capture, sync queue, receipt slip | Geographic: assigned EAs only |
| Parish Chief | Capture, queue of in-flight cases for the parish, GRM L1 intake | Geographic: parish only |
| Community Development Officer (CDO) | UPD reviewer, GRM L2, programme referral approver | Geographic: sub-county |
| District M&E Officer | UPD L3 approver, SLA breach dashboard, sample audit | Geographic: district |
| NSR Unit Coordinator | DIH review queue, promotion approvals, programme onboarding, partner DSA, system admin | National scope |
| Data Protection Officer (DPO) | Cumulative volume console, erasure approval, audit review, DPIA | National scope, including audit-only views of all data |
| Source Admin | SourceSystem registration, DPA management, MappingRule editor, ConnectorRun monitor | National scope (DIH only) |
| DRS Reviewer | Data request queue, DRS approval | National scope (DRS only) |
| Dedup Operator | Dedup dashboard, side-by-side compare, merge commit | Geographic: assigned regions |
| Programme User | Read household data for their programme, push enrolment/exit events | Per-DSA scope |
| System Administrator | User and role admin, rule editor, system settings, logs | National scope |

### Citizen-facing surfaces

| Surface | Channel | Purpose |
|---|---|---|
| Receipt slip | Printed at parish, plus SMS | Provisional Registry ID, tracking instructions |
| USSD pre-registration | Short code (Release 2) | Citizen-initiated pre-registration |
| Web portal status check | Browser (Release 3) | "What is the status of my registration?" |

---

## 4. Design system tokens

### Colour palette

| Token | Hex | Usage |
|---|---|---|
| `--primary-900` | `#1F3864` | Headings, primary nav background, primary button |
| `--primary-700` | `#2E74B5` | Secondary headings, INT module accent |
| `--primary-100` | `#F1F6FC` | Primary surface tint, INT module backgrounds |
| `--accent-data` | `#2E7D32` | DAT module accent, success states, confirmed Registry ID |
| `--accent-data-bg` | `#E8F4EA` | DAT module surface tint |
| `--accent-quality` | `#B8741A` | DAT-DQA module accent, warning states |
| `--accent-quality-bg` | `#FFF5E6` | DAT-DQA surface tint |
| `--accent-danger` | `#A93226` | DAT-DDUP module accent, errors, blocking failures |
| `--accent-danger-bg` | `#FFF0F0` | DAT-DDUP surface tint |
| `--accent-identity` | `#6A1B9A` | IDV module accent (NIRA, member detail) |
| `--accent-identity-bg` | `#F0E8F7` | IDV surface tint |
| `--accent-update` | `#1565C0` | UPD module accent, update workflow |
| `--accent-update-bg` | `#E8F1FA` | UPD surface tint |
| `--accent-eligibility` | `#8B6914` | PMT module accent |
| `--accent-eligibility-bg` | `#FFF8DC` | PMT surface tint |
| `--accent-programme` | `#0277BD` | REF module accent |
| `--accent-programme-bg` | `#E8F4F8` | REF surface tint |
| `--accent-grm` | `#D84315` | GRM module accent |
| `--accent-grm-bg` | `#FFEFE0` | GRM surface tint |
| `--accent-reference` | `#4527A0` | REF-DATA accent |
| `--accent-reference-bg` | `#EDE7F6` | REF-DATA surface tint |
| `--accent-system` | `#37474F` | API / SEC / RPT accent |
| `--accent-system-bg` | `#F0F4F8` | API surface tint |
| `--neutral-900` | `#212121` | Body text, audit |
| `--neutral-700` | `#444444` | Secondary text |
| `--neutral-500` | `#666666` | Tertiary text, metadata |
| `--neutral-300` | `#BFBFBF` | Borders, dividers |
| `--neutral-100` | `#F5F5F5` | Background surfaces |
| `--neutral-0` | `#FFFFFF` | Page background |

Module accent colours are reused across the SAD, the ERD, and the UI to create a single visual vocabulary. A user opening any DIH screen sees purple-grey trim and recognises the module by colour without reading.

### Typography

- **Primary font**: Inter (web fallback to system-ui, -apple-system, "Segoe UI", Roboto, sans-serif).
- **Document font**: Calibri (matches the SAD, used in PDF and PPTX exports).
- **Mobile (CAPI)**: Roboto for Android-native consistency.
- **Type scale** (px / line-height):
  - Display: 32 / 40, weight 700
  - H1: 24 / 32, weight 700
  - H2: 20 / 28, weight 600
  - H3: 16 / 24, weight 600
  - Body: 14 / 20, weight 400
  - Body small: 13 / 18, weight 400
  - Caption / metadata: 12 / 16, weight 400
  - Code / monospace: 13 / 18, weight 400 — JetBrains Mono or system monospace

### Spacing scale (4-point base)

`--space-1: 4px`, `--space-2: 8px`, `--space-3: 12px`, `--space-4: 16px`, `--space-5: 20px`, `--space-6: 24px`, `--space-7: 32px`, `--space-8: 40px`, `--space-9: 48px`, `--space-10: 64px`.

Default vertical rhythm: 8px. Section padding: 24px. Card padding: 16px. Table cell padding: 8/12px (vertical/horizontal).

### Shape and elevation

- Border radius: 4px default, 8px on cards, 2px on inline tags.
- Elevation: avoid heavy shadows. Use 1px borders and subtle surface tints to separate regions.
- Card elevation level 1: `0 1px 2px rgba(0,0,0,0.04), 0 0 0 1px var(--neutral-300)`.

### Icons

- Use Lucide or Material Symbols. Icon size 16px inline, 20px in toolbars, 24px in empty states.
- Avoid flag and currency emoji. Use neutral icons.

---

## 5. Component library

These are the components Claude Design should build first. Each is reused across many screens.

### 5.1 Status badge / chip

A pill-shaped label, height 22px, padding 4/8, font-size 12, weight 600. Background uses the module's surface tint with 1px border in the accent colour. Foreground uses the accent colour.

Status chips appear in tables, on detail screens, and on toast notifications.

### 5.2 Field-level diff card

Two columns side-by-side ("Before" / "After"). Each row is one field. Changed values are highlighted with a left border in `--accent-update`. Used in the UPD review screen and in the dedup compare.

### 5.3 Side-by-side compare component

Three columns, each carrying a candidate record summary plus a result column on the right. Per-field radio toggles between A / B / Both. Used in dedup (US-083), DIH review (US-109), and any future "promote-as-merge" decision.

### 5.4 Audit chain side panel

A right-rail drawer, 360px wide, that lists audit events for the current record in reverse-chronological order. Each event row: actor avatar, action verb, target field, timestamp, expandable detail. Sticky filter at the top.

### 5.5 Data table with toolbar

Default tables include: column header with sort affordance, optional filter row, sticky header on scroll, density toggle (comfortable / compact), CSV export. Selection checkboxes on the left when bulk actions are allowed.

### 5.6 KPI card

A 1x1 card showing a metric: title (caption size), big number (display size), trend arrow, sparkline. Used on the NSR Unit Coordinator landing page and the DPO console.

### 5.7 Form field

Single-row form fields with label above, input below, helper text and error text below the input. Required fields marked with a red asterisk and an `aria-required="true"` attribute. Type-aware controls: date picker, geographic tree picker, choice-list combobox, currency input.

### 5.8 Approval action bar

A sticky bottom bar that appears on review screens. Contains: Reject (danger), Hold for more info (neutral), Approve (primary). Each action opens a modal that demands a reason. The bar is keyboard-accessible: Cmd/Ctrl + Enter approves; Cmd/Ctrl + Backspace rejects.

### 5.9 Geographic tree picker

A nested combobox: Region → Sub-region → District → County → Sub-county → Parish → Village. Each level disables until the parent is chosen. Backed by UBOS reference data, versioned.

### 5.10 Sensitivity badge (DRS)

Used in the Field Selector. Tiny inline pill with one of four labels: Public, Internal, Personal, Sensitive. Sensitive is red with a lock icon.

---

## 6. Information architecture

The console is organised around modules. The left rail is the primary navigation. Top bar shows: workspace switcher (only one for now, "NSR"), search across households and members, notification bell, profile menu.

### Navigation (left rail, in order)

1. **Home** — role-aware dashboard.
2. **Households** — search, browse, detail view, history.
3. **Captures** — submissions queue (DIH staging filtered by source channel).
4. **Updates** — change request queue.
5. **Duplicates** — dedup pairs queue.
6. **Grievances** — case list.
7. **Programmes** — referrals and enrolments.
8. **Data Requests** — outbound DRS queue, my requests, partner requests.
9. **Reports** — operational dashboards, M&E indicators.
10. **Admin** — Sources, Connectors, Mapping Rules, DQA Rules, Match Models, DSAs, DPAs, Users, Roles, Settings, Audit. Visible only to System Admin, Source Admin, and DPO.

Role-aware: items the user cannot access are hidden, not greyed out. Showing forbidden items in grey is a security smell.

### Page layout

- 240px left rail (collapses to 64px on hover).
- 56px top bar.
- Main column flex; right-rail audit panel slides in over the main column when needed (does not narrow the main column permanently).
- Maximum content width: 1440px. Centered on wider displays.

### Tablet (CAPI Android)

- Single-column. Bottom navigation bar with 4 tabs: Capture, Queue, Sync, Profile.
- Forms span full width. One question per screen for offline form runtime.

---

## 7. Priority screens to design first

In recommended build order. Each is anchored to a user story from the backlog so the acceptance criteria are already drafted.

| # | Screen | Anchored to | Page type |
|---|---|---|---|
| 1 | Parish operator household capture | US-088 + US-112 | Multi-step form, mobile + web |
| 2 | Provisional Registry ID receipt slip | US-112 | Printable A6 slip + SMS |
| 3 | NSR Unit DIH review queue | US-109 | Queue + detail |
| 4 | DIH ConnectorRun dashboard | US-107 | Stats + table |
| 5 | Dedup Operator side-by-side compare | US-083 | Three-column compare |
| 6 | UPD reviewer with PMT preview | US-090 | Diff + sticky action bar |
| 7 | DRS Query Builder + Field Selector | US-097 | Builder + preview pane |
| 8 | DPO cumulative volume console | US-103 | KPI grid + alert list |
| 9 | Household detail (read-only registry view) | US-005, US-090 | Tabbed layout |
| 10 | Home — role-aware dashboard | US-013 / general | KPI cards + queues |

---

## 8. Status vocabulary and badge mapping

Use these exact labels. Do not invent variants.

### Registry ID lifecycle

| Status | Colour | Note |
|---|---|---|
| `Provisional` | `--accent-update` on `--accent-update-bg` | Captured, not yet promoted |
| `Pending` | `--accent-quality` on `--accent-quality-bg` | In NSR Unit review queue |
| `Registered` | `--accent-data` on `--accent-data-bg` | Confirmed in the registry |
| `Rejected` | `--accent-danger` on `--accent-danger-bg` | Promotion refused; ID voided |
| `Voided` | `--neutral-700` on `--neutral-100` | Soft-deleted |

### Submission / Change request

`Draft`, `Submitted`, `Pending QA`, `Accepted`, `Pending Approval`, `Approved`, `Rejected`, `Committed`, `Reversed`.

### Dedup pair

`Pending`, `Merged`, `Rejected`, `On hold`, `Cross-household`.

### Connector run

`Queued`, `Running`, `Completed`, `Failed`, `Cancelled`.

### DRS request

`Draft`, `Submitted`, `Pending DPO review`, `Approved`, `Generating`, `Delivered`, `Expired`, `Rejected`, `Revoked`.

### Grievance

`Open`, `In progress`, `Awaiting citizen response`, `Resolved`, `Closed`.

### DQA severity

`Blocking` (danger red), `Warning` (quality amber), `Info` (system grey).

### Sensitivity (DRS Field Selector)

`Public` (system grey), `Internal` (programme blue), `Personal` (eligibility gold), `Sensitive` (danger red with lock icon).

---

## 9. Language and tone

- Address the user with "you" and "your".
- Active voice. Short sentences. No marketing language.
- Error messages name the rule that failed (for example, "GPS accuracy 14 m exceeds the 10 m limit (AC-GPS-ACCURACY). Move to an open area and retry.").
- Confirmation messages name the action and the audit trail ("Approved. Audit ID #A-2026-05-14-00471.").
- Currency: Uganda Shillings (UGX), with USD in parentheses when meaningful.
- Dates: ISO 8601 in data exports; "14 May 2026" in UI strings.
- Times: East Africa Time (UTC+3) shown as "14:35 EAT".
- Phone numbers: Display in E.164 format with spaces, for example "+256 414 234567".

### Bilingual strings (Phase 2)

Keep room for up to 20% string expansion. The longest known label: "Operation Wealth Creation (OWC) Programme" in English. The Luganda equivalent of administrative section labels can run 25% longer. Test the UI at 130% string length to confirm layouts.

---

## 10. Accessibility and responsive behaviour

- **Web operator console**: WCAG 2.1 AA. Contrast ratio at least 4.5:1 for normal text, 3:1 for large text. All interactive elements reachable by keyboard. Focus rings visible at 2px width with a 2px offset.
- **CAPI Android**: Large-text mode toggle, Talkback support, minimum touch target 48dp, high-contrast mode for outdoor use.
- **Forms**: every input has a label; placeholder text never replaces a label.
- **Tables**: row hover state, but never relies solely on hover for an action.
- **Status colour is never the only cue**. Each chip carries both a colour and a label.
- **Reduced motion**: respect `prefers-reduced-motion`. Disable transitions on toasts and modals.

### Breakpoints

- Mobile portrait: 360–599 px (CAPI Android primary target).
- Mobile landscape / small tablet: 600–839 px.
- Tablet: 840–1199 px.
- Desktop: 1200–1599 px (parish office and sub-county desktop).
- Wide desktop: 1600+ px (NSR Unit M&E).

---

## 11. Screen specifications — detailed

Each screen below is ready to be sent to Claude Design as a single prompt. Copy the section, paste, and refine.

### 11.1 Parish operator household capture (US-088, US-112)

**Goal**: a parish chief or sub-county operator captures a household on a desktop or on a CAPI tablet, in 8 to 12 minutes for an average household.

**Layout (desktop)**:

- Top: progress stepper with 7 sections (Identification, Roster, Health & Disability, Education, Employment, Housing, Food & Shocks). Sticky.
- Left rail: section navigator with completion ticks.
- Main column: form for the active section. Sticky "Save draft" and "Submit for promotion" buttons at the bottom.
- Right rail: helper panel with skip-logic hints, photo capture for evidence, and a live DQA preview ("3 warnings, 0 blocking failures").

**Layout (CAPI)**:

- One question per screen.
- Sticky progress bar at the top showing section/total.
- Bottom: Back, Next, Save & Exit.
- Camera, GPS, and barcode scan available at relevant questions.

**Key fields shown in the Identification section**:

Region, Sub-region, District, County, Sub-county, Parish, Village (all via the Geographic Tree Picker), Urban/Rural, Enumeration Area, Household Number, GPS lat/lng/accuracy, Respondent name, Phone, Head of household name (auto-filled from Roster Person 01), Consent statement with explicit Yes/No.

**Provisional Registry ID** is generated immediately on Submit. The next screen is the Receipt Slip (Section 11.2).

**Empty states**:

- Offline indicator if the tablet has no network: "Offline. Submissions queue and sync when connectivity returns."
- "Draft expires in 14 days" countdown if the draft is older than 7 days.

---

### 11.2 Provisional Registry ID receipt slip (US-112)

**Goal**: hand the citizen a printable slip and send an SMS with the same content, so they leave the parish office with proof of submission and a tracking code.

**Layout**: A6 printable, optimised for thermal receipt printers; HTML preview in the operator console.

**Content (in this order, no decorations)**:

```
MGLSD — National Social Registry
Provisional Registry ID:   01HXY7K3B2N9PVQE4M6FZRWS18
Captured at:               Parish Office, [Parish Name], [District]
Date:                      14 May 2026, 14:35 EAT
Operator:                  [Operator name and code]
Status:                    Pending NSR Unit approval

Track your status:
  - Quote your Provisional Registry ID at any parish office.
  - SMS HELP to 8800 for status (operator hours).
  - You will receive an SMS within 24 hours confirming your
    Registered status, or a reason if the application is held.

Your Provisional Registry ID becomes your confirmed Registry ID
on approval. Same number, no re-issue.

Data protection: collected and processed under the Data Protection
and Privacy Act 2019 (Uganda).
```

**SMS template**: "MGLSD NSR: Your provisional Registry ID is 01HXY7K3B2N9PVQE4M6FZRWS18. Pending approval. Track via parish office or SMS HELP to 8800."

**Style**: monospace for the ID; otherwise body 14/20.

---

### 11.3 NSR Unit DIH review queue (US-109)

**Goal**: the NSR Unit Coordinator works through staged records and decides promote, promote-as-merge, reject, or hold.

**Layout**:

- Top: filters (Source, Sub-region, Channel, Quality flags, IDV state, DDUP candidates, Walk-in vs Bulk). Quick filter buttons: "Walk-in 24h SLA at risk", "Has DDUP match >= 0.90", "Bulk awaiting batch approval".
- Main: Three-column compare (Staged record | Registry match candidate(s) | Decision panel).
- Right rail: Audit chain.

**Three-column detail**:

- Column 1 ("Staged record"): household summary card at top (head, village, GPS), then collapsible sections for each entity (Roster, Health, Education, Employment, Housing, Food, Shocks). Highlight DQA flags inline.
- Column 2 ("Registry match candidate"): same shape as Column 1, but populated only if DDUP returned a candidate at >= 0.80. Per-field similarity score visible on hover. If no match, show empty state "No registry match found".
- Column 3 ("Decision panel"): DQA badges, IDV outcome, DDUP candidate list, action area (Promote, Promote-as-merge, Hold for more info, Reject). Each action opens a modal demanding a reason and a written note.

**Empty state**: "No records waiting for review." Calm grey, not celebratory.

**Bulk action**: select up to 50 records via checkbox; "Bulk approve" enabled only when every selected record has zero warnings and zero candidates. Bulk size > 10,000 requires a second approver (US-108 AC-DIH-BATCH-DUAL).

---

### 11.4 DIH ConnectorRun dashboard (US-107)

**Goal**: a Connector Runner watches one or many ConnectorRuns and operates ingestion against any source.

**Layout**:

- Top: KPI strip — Active runs, Records in last 24h, Quarantined, Pending review.
- Main: table of ConnectorRuns with columns: Run ID, Source, Connector, Started, Duration, Status (chip), Landed, Mapped, Quarantined, In review, Promoted, Rejected, Actions.
- Row click opens a side panel with the full run detail and a live log tail.

**Actions per run**: Pause, Resume, Cancel, View log, Re-run.

**Live counts**: poll every 5 seconds while a run is `Running`. After `Completed` or `Failed`, counts freeze and a summary email is dispatched.

**Empty state**: "No connector runs in the last 7 days. Configure a source under Admin > Sources."

---

### 11.5 Dedup Operator side-by-side compare (US-083)

**Goal**: a Dedup Operator decides which of two (or up to three) candidate records survives a merge.

**Layout**:

- Top: pair metadata (Pair ID, composite score, model version, queue, status chip), Reject and Save buttons on the right.
- Main: three columns (Candidate A | Candidate B | Merge Result), or four columns if a three-way match.
- Per-field row: A's value, B's value, radio toggle (A / B / Both for list-like fields), Merge Result value.
- Per-field hover: show per-field similarity score.
- Bottom: required Add-note textarea. "Commit merge" button enabled only when every field has a chosen value.

**Confirmations**:

- On commit, show a modal summarising the merge (surviving ID, soft-deleted ID, fields kept from A vs. B, fields combined). Operator confirms.
- After commit, show a toast: "Merged into 01HXY7K3.... Loser 01HZ9NK2... archived. PMT recompute queued."

**Empty state on queue**: "No pending pairs at composite score >= 0.90. Switch to Weak queue to review pairs 0.80 to 0.89."

---

### 11.6 UPD reviewer with PMT preview (US-090)

**Goal**: a CDO or District M&E Officer reviews a ChangeRequest with full before/after context and a PMT preview before approving.

**Layout**:

- Top: ChangeRequest header (ID, target household, change_type, pmt_impact chip, reason, evidence chips), SLA badge.
- Main: side-by-side before/after diff. Each changed field carries a left border in `--accent-update`. Unchanged fields are collapsed by default; "Show all fields" toggle expands.
- Right rail: PMT preview card (only when `pmt_impact = pmt_relevant`): current PMT score and band on top, recomputed-if-approved score and band below, delta arrow.
- Bottom: sticky approval action bar (Reject | Hold for more info | Escalate | Approve). No-self-approve is enforced server-side; if the current user captured the request, Approve is disabled with a tooltip.

**Confirmations**: Reject demands a reason from the controlled list. Approve writes the new HouseholdVersion and routes the next-stage workflow.

**Empty state**: "No pending updates for your scope."

---

### 11.7 DRS Query Builder + Field Selector (US-097, US-098)

**Goal**: a partner-MDA Data Requester builds a query against the registry under a DSA, previews 10 rows, and submits for approval.

**Layout**:

- Step indicator: Scope → Build → Field Selector → Preview → Delivery → Submit.
- Step 1 Scope: entity picker (Household / Member / Referral / Grievance summary), shown only entities allowed by the active DSA. DSA card on the right shows valid_from, valid_to, row budget remaining for this month.
- Step 2 Build: filter rows with type-aware operators. AND/OR groups with up to depth 3. Geographic tree picker. PMT band filter. Programme enrolment filter. Date range filter.
- Step 3 Field Selector: list of fields available under the DSA, each with a sensitivity badge. Sensitive fields disabled with a tooltip "Disabled by DSA clause 4.2.b. Request expansion via your data steward". Save selection as a template.
- Step 4 Preview: 10-row server-side preview, masked. Header card: "Matched 47,233 of 12.1M. 10 shown. Query hash a4e9...."
- Step 5 Delivery: radio choice (Excel password-protected, CSV 7z password-protected, paginated API). Each option shows expected file size and TTL.
- Step 6 Submit: purpose-of-use field (required), retention pledge, recipient list (must match DSA). Submit.

**Empty state on entity picker**: "Your DSA does not currently cover any entities. Contact your data steward to expand scope."

**Errors**: out-of-scope attempts show a clear toast "Field 'nin_value' is Sensitive under your active DSA. Choose another field or request scope expansion."

---

### 11.8 DPO cumulative volume console (US-103)

**Goal**: the Data Protection Officer detects the "small but repeated" extract pattern early.

**Layout**:

- Top: KPI cards — Active requesters, Rows shipped 7d, Rows shipped 30d, Anomaly alerts.
- Main: table of active requesters with rows shipped 7d / 30d / 90d versus DSA budget, anomaly flag (red triangle when 30-day volume exceeds budget by more than 10%, or when day-over-day acceleration > 50%).
- Row click opens a side panel with the requester's full extract history, query hashes, and identical-hash matches across requesters.
- Actions per requester: Pause, Force re-approval on next request, Revoke active download links.

**Empty state**: "No anomalies. 14 active requesters within DSA budgets."

---

### 11.9 Household detail (registry view) (US-005, US-090)

**Goal**: any authorised user reads a registered household record, with history and audit one click away.

**Layout**:

- Header: head name, Registry ID, status (`Registered`), village, GPS, current PMT score and band, programme enrolments (chips).
- Tabs: Overview, Roster, Health & Disability, Education, Employment, Housing & Assets, Food & Shocks, Updates History, Grievances, Programmes, Consent, Audit.
- Each tab shows the canonical data plus a quick action ("Open update", "Add note", "View raw").

**No edit-in-place**. Edits open a UPD ChangeRequest. This enforces the audit chain (AC-UPD-VERSION).

**Empty state on Updates History**: "No updates since registration on 14 May 2026."

---

### 11.10 Home dashboard (role-aware)

The Home page renders different KPI cards and queues by role.

| Role | Home content |
|---|---|
| Parish Chief | Today's captures, drafts about to expire, GRM L1 cases for my parish |
| CDO | UPD review queue, GRM L2 cases, programme referrals pending |
| District M&E | SLA Breach dashboard, sample audits to do, PMT-band shift alerts |
| NSR Unit Coordinator | DIH review queue depth, fast-track auto-promote rate, bulk batches awaiting two-person approval, partner DSAs expiring in 30 days |
| DPO | Anomaly alerts (US-103), erasure requests, DPIA review tasks |
| Source Admin | Last 24h ConnectorRuns, quarantine count, DPA renewals coming up |
| DRS Reviewer | DRS requests awaiting approval, rejected requests in last 7d |
| Dedup Operator | Pending pairs (Strong queue), false-positive rate last 7d, my decisions per day |
| Programme User | My programme enrolments, exits since last login, payment events to acknowledge |
| System Administrator | System health, error rate, login anomalies, recent admin actions |

Each card is a link to the matching screen.

---

## 12. Ready-to-paste prompts for Claude Design

Use these as the second message in a Claude Design session (the first message being the upload of this brief, or paste of Sections 4 and 5).

### 12.1 First prompt — onboarding

```
You are designing the operator web console for the National Social Registry
MIS for the Government of Uganda. Read the design brief I have uploaded and
build a design system from Sections 4 (tokens), 5 (components), and 8
(status vocabulary). Establish:
- Tailwind-like utility class names that map to the tokens in Section 4.
- A component library matching Section 5.
- A reusable status-chip component covering Section 8.
- A reusable side-by-side compare component (Section 5.3).
- A reusable approval action bar (Section 5.8).

Render a single landing-page screen showing all the chips, badges, KPI
cards, and a sample data table, so we can confirm the tokens before we
build screens. No marketing language. Government tone.
```

### 12.2 Second prompt — parish operator capture

```
Build the Parish Operator Household Capture screen per Section 11.1
of the brief, anchored to US-088 and US-112. Render the desktop variant
first (1280px wide), then the CAPI tablet variant (720px landscape).

The desktop layout must show:
- Top progress stepper with 7 sections (Identification, Roster, Health &
  Disability, Education, Employment, Housing, Food & Shocks).
- Left rail section navigator with completion ticks.
- Main column form for the active section (start with Identification).
- Right rail helper panel with skip-logic hints, photo capture, and a live
  DQA preview ("3 warnings, 0 blocking failures").
- Sticky bottom bar: Save draft, Submit for promotion.

Use Section 4 colour tokens. The DAT module accent green is the active
section colour on the stepper. The DQA amber is the warning chip colour
in the helper panel.
```

### 12.3 Third prompt — DIH review queue

```
Build the NSR Unit DIH Review Queue per Section 11.3, anchored to US-109.
Render a 1440px desktop layout with:
- Top filter row (Source, Sub-region, Channel, Quality flags, IDV state,
  DDUP candidates) plus quick filter buttons ("Walk-in 24h SLA at risk",
  "Has DDUP match >= 0.90", "Bulk awaiting batch approval").
- Main three-column compare: Staged record | Registry match candidate |
  Decision panel.
- Right rail collapsible audit chain.
- Sticky approval action bar at the bottom: Reject | Hold | Promote-as-merge
  | Promote. Each action opens a modal demanding a reason.

Use the DAT (green) accent for "Staged record", DAT-DDUP (red) for
candidate matches above 0.90, DAT-DQA (amber) for warning flags, and
IDV (purple) for NIRA outcomes. Show realistic placeholder data for a
household of 6 from Karamoja sub-region.
```

### 12.4 Fourth prompt — dedup compare

```
Build the Dedup Operator Side-by-Side Compare per Section 11.5, anchored
to US-083. Render 1440px desktop.

Layout:
- Top: pair metadata (Pair ID, composite score 0.92, model v3, Strong
  queue, status Pending), Reject and Save buttons on the right.
- Main: three columns (Candidate A | Candidate B | Merge Result).
- Each row is one field. Per-field radio A/B/Both. Both disabled for
  non-list fields with a tooltip. Hover shows per-field similarity score.
- Below: required Add-note textarea.
- Commit merge button enabled only when every field has a chosen value.

Use the DAT-DDUP (red) accent on the composite score and the queue chip.
Use realistic Ugandan name placeholders. Show one row where A and B
disagree on phone number (use Both), one where they disagree on date of
birth (must choose A or B), and one where the names are similar but not
identical (Soundex match).
```

### 12.5 Fifth prompt — DRS Query Builder

```
Build the DRS Query Builder per Section 11.7, anchored to US-097 and
US-098. Render the six-step flow (Scope → Build → Field Selector →
Preview → Delivery → Submit) with the Build and Field Selector steps
expanded in detail.

For Build, show: an entity picker fixed to Household, three filter rows
(Sub-region IN (Karamoja, West Nile), PMT band IN (poorest 40%),
Updated between 1 Apr 2026 and 14 May 2026), one AND/OR group toggle,
and a geographic tree picker on the side.

For Field Selector, show a list of ~20 fields with sensitivity badges.
Disable 3 fields (NIN, photo_ref, household_savings_amount) with the
tooltip "Disabled by DSA clause 4.2.b. Request expansion via your data
steward".

Preview row card: "Matched 47,233 of 12,089,442. 10 rows shown. Query
hash a4e9d2f1...". Show a 10-row preview table with NIN masked to last 4.

Use the API/SEC system grey throughout, with the danger red for the
Sensitive badge and the API blue for the active step.
```

### 12.6 Sixth prompt — receipt slip

```
Build the Provisional Registry ID Receipt Slip per Section 11.2,
anchored to US-112. Two variants:

1. A6 printable slip (105mm x 148mm), thermal-printer friendly,
monochrome, monospace for the Registry ID, body in Calibri 11pt.
2. SMS preview at 160 characters, showing the same provisional ID and
the tracking instruction.

The slip must include all 7 content blocks from Section 11.2 in order.
No graphics other than a small MGLSD wordmark at the top. Calm,
official tone.
```

---

## 13. Sample data and fixtures

Use these placeholder names and IDs throughout the mockups so screens look realistic and tell a coherent story.

| Entity | Placeholder |
|---|---|
| Sub-region | Karamoja |
| District | Moroto |
| Sub-county | Tapac |
| Parish | Nakiloro |
| Village | Lopuwapuwa |
| Head of household | Lokol Naume |
| Head NIN | CM12345678ABCD |
| Phone | +256 786 234567 |
| Household size | 6 |
| GPS | 2.49423, 34.65103, 6m accuracy |
| Registry ID (Provisional) | `01HXY7K3B2N9PVQE4M6FZRWS18` |
| Connector | UBOS-NUSAF-2026-BULK |
| Connector run | CR-2026-05-14-00471 |
| ChangeRequest | UPD-2026-05-14-00237 |
| Grievance | GRV-2026-05-14-00091 |
| DSA | DSA-OPM-PDM-2026 |
| Match pair | MP-2026-05-14-00045 |

---

## 14. Out of scope for this design pass

These exist in the SAD but should not be designed yet. Mark them as future work in the design system, but do not produce screens.

- USSD pre-registration flow (Release 2).
- Citizen self-service web portal (Release 3).
- Real-time multi-editor collaboration on reviews.
- Vector illustrations or marketing pages.
- Public-facing reporting portal (Release 2).
- Self-service partner onboarding (Release 3).

---

## 15. Acceptance for the design pass

A first pass of the design is accepted when:

1. Section 5 components exist and render as a kit page.
2. Sections 11.1, 11.2, 11.3, 11.5, 11.6, 11.7 each render as a working HTML mockup with realistic placeholder data.
3. Status vocabulary in Section 8 is exhausted across the screens (every chip type appears at least once).
4. The CAPI tablet variant of Section 11.1 renders at 720px landscape and passes a quick keyboard-only walkthrough.
5. Every Critical Action button (Approve, Reject, Commit Merge, Submit Request) opens a modal that demands a reason.
6. The audit chain side panel appears on at least two screens (DIH review queue and UPD reviewer).
7. Tokens from Section 4 are used everywhere; no hex colours hard-coded outside the tokens.

---

## 16. Handoff to engineering

Once the design pass is accepted, hand off to engineering as:

- Standalone HTML mockups, one per screen, exported from Claude Design.
- A `design-tokens.json` (or `tokens.css`) carrying the values from Section 4.
- A `components.md` mapping each Section 5 component to its props and states.
- An `acceptance.md` listing the screen-to-user-story map (Section 7 table).

These four files go into the NSR codebase under `/design/v0.1/` so the Django + Vue/React frontend has a clear translation target.

---

End of brief. Version 0.1, 14 May 2026. Owner: NSR MIS Architecture Team, MGLSD. For questions, contact the NSR Unit through the channels listed in the Framework for Implementing the NSR (2026).

Johnson Mwebaze
