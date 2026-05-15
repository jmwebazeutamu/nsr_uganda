# NSR MIS — Design Acceptance Map (v0.1)

Each design mockup is anchored to one or more user stories from `/docs/03_backlog.xlsx`. When engineering builds the screen, the design and the story share the same acceptance criteria. This file is the single source of "is this design done and correct".

---

## Priority screens (build order)

Screens are React components inside the module JSX files under `v0.1/screens/`. State variants (device, role, wizard step) are props, not separate files. The harness (`/design/nsr-mis-console.html`) routes to each by component name.

| # | Screen | Anchored to | Built in | Status |
|---|---|---|---|---|
| 1 | Parish operator household capture (desktop) | US-088, US-112 | `screens-capture.jsx` → `<CaptureScreen device="desktop">` | built |
| 1b | Parish operator household capture (CAPI tablet) | US-088, US-112 | `screens-capture.jsx` → `<CaptureScreen device="capi">` (renders `<CapturePadCAPI>`) | built |
| 2 | Provisional Registry ID receipt slip | US-112 | `screens-capture.jsx` → `<ReceiptScreen>` / `<ReceiptSlipA6>` | built |
| 2b | SMS preview | US-112 | `screens-capture.jsx` → inside `<ReceiptScreen>` | built |
| 3 | NSR Unit DIH review queue | US-109 | `screens-dih.jsx` → `<DIHScreen>` (Review tab) | built |
| 4 | DIH ConnectorRun dashboard | US-107 | `screens-dih.jsx` → `<DIHScreen>` (Runs tab) | built |
| 5 | Dedup Operator side-by-side compare | US-083 | `screens-dedup.jsx` → `<DedupScreen>` | built |
| 6 | UPD reviewer with PMT preview | US-090 | `screens-upd.jsx` → `<UPDScreen>` | built |
| 7 | DRS Query Builder | US-097 | `screens-drs.jsx` → `<DRSScreen>` (Build step) | built |
| 7b | DRS Field Selector | US-098 | `screens-drs.jsx` → `<FieldStep>` | built |
| 7c | DRS Preview pane | US-098 | `screens-drs.jsx` → `<PreviewStep>` | built |
| 7d | DRS Delivery method choice | US-099, US-100, US-101 | `screens-drs.jsx` → `<SubmitStep>` | built |
| 8 | DPO cumulative volume console | US-103 | `screens-dpo.jsx` → `<DPOScreen>` | built |
| 9 | Household detail (registry view) | US-005, US-090 | `screens-household.jsx` → `<HouseholdScreen>` | built |
| 10 | Home dashboard (role-aware) | (general) | `screens-home.jsx` → `<HomeScreen role="…">` for each of `ROLES` (Parish Chief, CDO, District M&E, NSR Unit Coordinator, DPO) | built |
| 11 | GRM workbench (triage + lifecycle) | US-S2-008, US-S3-004, US-S4-005, US-S7-001 | `screens-grm.jsx` → `<GRMScreen>` | built |
| 12 | Partner DRS portal (my requests + download) | US-S3-002, US-S7-004, US-S8-003, US-S9-003 | `screens-partner-drs.jsx` → `<PartnerDRSScreen>` | built |

---

## Per-screen acceptance gates

Each screen must satisfy the acceptance criteria of its anchored user story PLUS the design-level gates below.

### 1. Parish operator household capture (US-088, US-112)

| AC | Pass when |
|---|---|
| AC-UPD-DIFF analogue at capture | n/a (this is initial capture, no diff yet) |
| UI-Capture-1 | Top progress stepper renders all 7 sections with completion ticks |
| UI-Capture-2 | Left rail section navigator is keyboard-reachable; arrow keys move between sections |
| UI-Capture-3 | Right rail helper panel shows skip-logic hints AND live DQA preview ("N warnings, M blocking failures") |
| UI-Capture-4 | Photo capture button opens device camera (mock OK in mockup); evidence_ref appears in the form state |
| UI-Capture-5 | GPS capture button shows lat/lng/accuracy; if accuracy > 10m the value is shown in red with "Move to an open area and retry" |
| UI-Capture-6 | Submit for promotion is disabled until all required fields are filled and zero blocking failures |
| UI-Capture-7 | On submit, the next screen is the receipt slip with a generated provisional Registry ID |
| UI-Capture-CAPI-1 | CAPI variant renders one question per screen at 720px landscape |
| UI-Capture-CAPI-2 | Bottom bar Back/Next/Save & Exit is reachable with the thumb at any device orientation |
| UI-Capture-CAPI-3 | Offline indicator appears when navigator.onLine = false |

### 2. Receipt slip (US-112)

| AC | Pass when |
|---|---|
| AC-DIH-PROVISIONAL-ID | Provisional Registry ID printed in monospace, ULID format |
| UI-Receipt-1 | A6 layout (105mm x 148mm) at 200dpi thermal-printer friendly |
| UI-Receipt-2 | All 7 content blocks present in order (per Brief §11.2) |
| UI-Receipt-3 | DPPA 2019 footer line present |
| UI-Receipt-4 | SMS preview at exactly 160 characters or fewer |

### 3. DIH review queue (US-109)

| AC | Pass when |
|---|---|
| AC-DIH-DDUP-DISCOVERY | Column 2 populates when a candidate ≥ 0.80 exists; "No registry match found" empty state otherwise |
| AC-DIH-FT-AUTO | Quick filter "Walk-in fast-tracked" is present |
| UI-Review-1 | Three columns: Staged record / Registry match / Decision panel |
| UI-Review-2 | DQA badges, IDV outcome, DDUP candidate list visible in Decision panel |
| UI-Review-3 | Action bar (Promote, Promote-as-merge, Hold, Reject); each opens a reason modal |
| UI-Review-4 | Bulk approve only enabled when every selected record has zero warnings and zero candidates |
| UI-Review-5 | Audit chain side panel reachable from a button in the header |

### 4. ConnectorRun dashboard (US-107)

| AC | Pass when |
|---|---|
| UI-CR-1 | KPI strip: Active runs, Records 24h, Quarantined, Pending review |
| UI-CR-2 | Table with the 12 columns from Brief §11.4 |
| UI-CR-3 | Live counts poll every 5s when run status is Running |
| UI-CR-4 | Row click opens side panel with run detail and log tail |

### 5. Dedup compare (US-083)

| AC | Pass when |
|---|---|
| AC-DDUP-NIN | Pair-metadata header shows when NIN match is the deterministic reason |
| AC-DDUP-MERGE-COMMIT | Commit button disabled until every field has a chosen value AND note is non-empty |
| UI-Dedup-1 | Three columns; four if three-way match |
| UI-Dedup-2 | Per-field radios A/B/Both, with Both disabled for non-list fields and a tooltip |
| UI-Dedup-3 | Per-field similarity score visible on hover |
| UI-Dedup-4 | After commit, toast shows surviving ID and loser ID; PMT recompute confirmation |

### 6. UPD reviewer (US-090)

| AC | Pass when |
|---|---|
| AC-UPD-DIFF | Side-by-side before/after with every changed field highlighted (left border `--accent-update`) |
| AC-UPD-PMT-PREVIEW | Current PMT score+band AND recomputed score+band visible for `pmt_relevant` changes |
| AC-UPD-NO-SELF-APPROVE | Approve disabled with tooltip when current user = capturer |
| UI-UPD-1 | "Show all fields" toggle expands unchanged fields |
| UI-UPD-2 | Evidence chips clickable to preview attached photo or document |
| UI-UPD-3 | SLA badge in header turns amber when ≤ 24h to breach, red when breached |

### 7. DRS Query Builder + Field Selector + Preview + Delivery (US-097, US-098, US-099, US-100, US-101)

| AC | Pass when |
|---|---|
| AC-DRS-DSA-SCOPE | Field Selector hides forbidden options; out-of-scope attempts show toast naming the DSA clause |
| AC-DRS-PREVIEW | 10-row preview returns from server, total matched count visible |
| AC-DRS-PREVIEW-MASK | NIN masked to last 4 chars in the preview |
| AC-DRS-DELIVERY-EXCEL | Excel delivery option shows expected file size and TTL |
| AC-DRS-DELIVERY-CSV | CSV delivery option labelled "encrypted 7z archive" |
| AC-DRS-DELIVERY-API | API delivery option shows the endpoint URL pattern and OAuth scope |
| UI-DRS-1 | Six-step indicator: Scope → Build → Field Selector → Preview → Delivery → Submit |
| UI-DRS-2 | AND/OR group toggle in Build; depth limit 3 enforced |
| UI-DRS-3 | Save selection as template button on Field Selector |

### 8. DPO cumulative volume console (US-103)

| AC | Pass when |
|---|---|
| AC-DRS-CUMULATIVE | Cumulative 7d / 30d / 90d shown per requester vs DSA budget |
| UI-DPO-1 | Anomaly flag (red triangle) appears when 30d volume exceeds budget by > 10% or day-over-day acceleration > 50% |
| UI-DPO-2 | Drill into requester shows full extract history with query hashes |
| UI-DPO-3 | Per-requester actions: Pause, Force re-approval, Revoke active download links |

### 9. Household detail (US-005, US-090)

| AC | Pass when |
|---|---|
| UI-HH-1 | Header shows Registry ID, status chip (`Registered`), head name, village, current PMT score + band |
| UI-HH-2 | Tabs: Overview, Roster, Health & Disability, Education, Employment, Housing & Assets, Food & Shocks, Updates History, Grievances, Programmes, Consent, Audit |
| UI-HH-3 | No edit-in-place; edits open an UPD ChangeRequest |

### 10. Home dashboard

| Role | Pass when |
|---|---|
| Parish Chief | Captures today, drafts expiring, parish GRM L1 cases |
| CDO | UPD review queue, GRM L2, programme referrals pending |
| District M&E | SLA Breach dashboard, sample audits, PMT-band shift alerts |
| NSR Unit Coordinator | DIH review queue depth, fast-track auto-promote rate, bulk batches awaiting two-person approval, DSAs expiring 30d |
| DPO | Anomaly alerts, erasure requests, DPIA review tasks |

### 12. Partner DRS portal (US-S3-002, US-S7-004, US-S8-003, US-S9-003)

The first partner-facing surface. Reads through
`/api/v1/drs/requests/mine/` (S7-004 PartnerScopedQuerysetMixin) and
downloads through `/api/v1/drs/requests/{id}/download/` (S8-003)
which is rate-limited per S9-003. Role-gated to `PARTNER_ANALYST`
and `PARTNER_DPO` per ADR-0006.

| AC | Pass when |
|---|---|
| UI-PDRS-1 | Status filter strip (All / Pending approval / Approved / Delivered) with live counts |
| UI-PDRS-2 | List columns: request id (monospace), DSA reference, status chip, row count (right-aligned monospace, em-dash when not yet delivered), submitted date, expires date, inline Download button |
| UI-PDRS-3 | Inline Download button enabled only when status=DELIVERED AND download_url is present; emits the future endpoint pattern `/api/v1/drs/requests/{id}/download/` |
| UI-PDRS-4 | Detail rail shows DSA reference, fields requested (each as a chip — programme-toned for `member.*`, otherwise neutral), geography chips when scoped, row cap |
| UI-PDRS-5 | Rejected rows surface the decision_reason in a red-tinted callout — partners can see WHY without contacting the NSR Unit |
| UI-PDRS-6 | Delivered rows show: row count, full 64-char manifest SHA-256 (monospace, wraps cleanly), expiry date. Partners verify integrity by re-hashing the downloaded NDJSON |
| UI-PDRS-7 | "About this portal" hint card explains: scope, 10/min download rate limit (S9-003), 30d bundle TTL (S5-002), audit on every read/download |
| UI-PDRS-8 | Empty state (no rows match filter) shows the calm inbox icon — no marketing copy |
| UI-PDRS-9 | Role visibility: hidden from all operator roles (Parish Chief, CDO, NSR Unit, DPO); visible to PARTNER_ANALYST + PARTNER_DPO; partner role sees ONLY this screen + Home in the side nav |
| UI-PDRS-10 | Audit drawer shows the lifecycle: submitted → approved/rejected → rendered+delivered |
| UI-PDRS-11 | Tokens-only — no hex colours hardcoded outside tokens.css |
| UI-PDRS-BUILDER-1 | "New request" button switches to a builder mode within the same screen (no router change); back/cancel returns to the list |
| UI-PDRS-BUILDER-2 | Fields panel grouped by prefix (household.* / member.*); each row is a checkbox with the dotted-key field name in monospace; "Select all" + "Clear" affordances |
| UI-PDRS-BUILDER-3 | Geography panel uses chip-buttons sourced from DSA.allowed_scopes.sub_region_codes; empty selection explained as "uses all DSA-scoped regions" (matches validate_against_dsa semantics — absent key = no constraint) |
| UI-PDRS-BUILDER-4 | Row cap input bounded by DSA.allowed_scopes.max_rows_per_request; live validation warning when exceeded |
| UI-PDRS-BUILDER-5 | Right rail shows the exact JSON request_payload that will POST — same shape as validate_against_dsa expects (apps/data_requests/services.py); reduces round-trip when partners ask for fields outside scope |
| UI-PDRS-BUILDER-6 | Validation checklist: green/red bullets for "at least one field selected", "row cap within DSA limit"; amber note when `member.*` fields are requested (reminds partner those will be scrutinised) |
| UI-PDRS-BUILDER-7 | "Submit for approval" button disabled until all required validations pass |
| UI-PDRS-BUILDER-8 | "Next steps" card explains the lifecycle (submit → reviewer → manifest + TTL → download) so the partner knows what to expect |

### 11. GRM workbench (US-S2-008, US-S3-004, US-S4-005, US-S7-001)

The first React screen — parity-or-better with the Django admin
GRM surface from S4-005 + S6-001. Reads + writes through the
existing `/api/v1/grm/grievances/` viewset.

| AC | Pass when |
|---|---|
| UI-GRM-1 | Quick-filter bar with Past-SLA / Open-L1 / Escalated / Mine; counts update when a filter is active |
| UI-GRM-2 | List columns: subject + reporter, tier (L1/L2/L3/L4 short), status chip, SLA chip, assigned-to, opened-at |
| UI-GRM-3 | SLA chip mirrors the `format_html` badge from `apps/grievance/admin.py`: red OVERDUE when `hours_to_breach < 0`, amber `≤ 6h to breach`, green within window, neutral `—` for RESOLVED/CLOSED |
| UI-GRM-4 | Multi-select row checkboxes; bulk Assign / Escalate / Close appear in the toolbar only when ≥ 1 row is selected |
| UI-GRM-5 | Detail rail shows category, narrative, reporter, subject (household_id + member_id when present), assignment state |
| UI-GRM-6 | Per-row actions exposed contextually: Assign-to-me only when unassigned; Escalate only when tier ≠ L4 and status ∉ {RESOLVED, CLOSED}; Resolve only when status ∉ {RESOLVED, CLOSED}; Close only when status == RESOLVED |
| UI-GRM-7 | Escalate / Resolve / Close trigger `ReasonModal` with canned reasons that mirror service-layer guard messages from `apps/grievance/services.py`; reason + 6+ char note required |
| UI-GRM-8 | DATA_CORRECTION rows expose an "Open linked UPD" action — clicking jumps to the UPD screen with the linked ChangeRequest pre-loaded; the UPD page header shows "OPENED FROM GRM" eyebrow + a "linked from grievance" chip so the reviewer knows the context (cross-screen handoff, wired in S9-004) |
| UI-GRM-9 | Audit drawer shows the full lifecycle: opened → SLA computed → assigned → escalated (when applicable) → resolved (when applicable) |
| UI-GRM-10 | Empty state (no rows match filter) shows a calm inbox icon with "No grievances match this filter" — no marketing copy |
| UI-GRM-11 | Role visibility: hidden from DPO (read-only-everything, no workflow); visible to Parish Chief, CDO, District M&E, NSR Unit |

---

## Cross-cutting acceptance (applies to every screen)

| Gate | Pass when |
|---|---|
| Tokens-only | No hex colour hardcoded outside `tokens.css` |
| Status vocab exhausted | Every chip variant in Brief §8 appears at least once across the screens |
| Keyboard | Every interactive element reachable by Tab; focus ring visible |
| Contrast | Contrast ratio ≥ 4.5:1 for body, ≥ 3:1 for large text |
| Density | Tables render in both `comfortable` and `compact` density |
| Empty state | Every list/table/queue has a calm grey empty state with a clear next action |
| Government tone | No hero illustrations, no celebratory animations, no marketing copy |
| Bilingual-ready | Layouts hold at 130% string length |

---

## Sign-off

Design pass v0.1 is accepted when:

1. All priority screens 1 through 10 have a corresponding exported React component in `/design/v0.1/screens/` and render in the harness without console errors.
2. Every per-screen gate above is met.
3. Every cross-cutting gate is met.
4. The NSR Unit Coordinator and the engineering lead both sign off on a 30-minute design walk-through.

Signed off by:

- NSR Unit Coordinator: ____________________ Date: __________
- Engineering Lead: ____________________ Date: __________
- Architecture Team: ____________________ Date: __________

---

End of acceptance.md, v0.1.
