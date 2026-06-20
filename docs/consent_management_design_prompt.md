# Claude Design prompt — Consent Management screens

Paste the block below into a new project in **claude.ai/design**. Before sending it, upload these two files as project context:

1. `/docs/04_ui_design_brief.md` (the design system: tokens, components, vocabulary, status palette)
2. `/docs/consent_management_scope.md` (the module scope: purposes, data model, withdrawal handling, integrations)

Then send the prompt.

---

## PROMPT (copy from here)

You are designing the **Consent Management** module for the NSR MIS, the Uganda National Social Registry. Use the two uploaded files as the design system source. The brief in `04_ui_design_brief.md` defines tokens, components, status badges, breakpoints, and the vocabulary. The scope in `consent_management_scope.md` defines the purposes, data model, and behaviour.

Treat this module as an extension of the SEC (security) family. Use `--accent-system` (`#37474F`) on `--accent-system-bg` (`#F0F4F8`) as the module accent. Keep the calm government tone described in Section 2 of the brief.

### Audience

Three operator roles and one citizen role:

1. **Field Enumerator / Parish Chief** on CAPI (Android tablet) and Web. Captures consent at intake and at head-change.
2. **Data Protection Officer (DPO)** on Web. Runs the purpose catalogue, statement versions, and the withdrawal-review queue.
3. **NSR Unit Coordinator** on Web. Reads coverage reports, signs off on DPA-driven fast-track consent at DIH activation.
4. **Citizen** on the portal (Release 3) and assisted at the parish office. Views the consent matrix and requests withdrawal.

### Status vocabulary

Use these exact labels. Do not invent variants.

- Consent state: `Granted` (`--accent-data`), `Refused` (`--accent-danger`), `Withdrawn` (`--neutral-700` on `--neutral-100`), `Pending review` (`--accent-quality`), `Pending re-consent` (`--accent-update`).
- Withdrawal ticket: `Open`, `In DPO review`, `Confirmed`, `Public-task override`, `Clarification requested`, `Closed`.
- Statement version: `Draft`, `Active`, `Superseded`.
- Purpose: `Draft`, `Active`, `Retired`.
- Lawful basis chips (read-only): `Consent`, `Public task`, `Contract`, `Vital interest`, `Legal obligation`, `Statistical exemption`.

### Screens to design (in build order)

Match the format used in Section 11 of `04_ui_design_brief.md`. For each screen, produce: a desktop layout, a tablet/mobile layout where the screen is used in the field, the empty state, the most common error state, and the audit-trail surface.

---

**Screen 1. Intake consent capture (CAPI + Web)** — anchor stories US-010, US-S26-CONSENT-CAPTURE-CAPI, US-S26-CONSENT-CAPTURE-WEB.

The first screen of intake, before any personal-data fields. Show the statement text for `REGISTRATION` with the statement version stamp, language switcher (English, Luganda, Runyankole, Acholi, Lusoga, Lugbara, Ateso), and a clear Yes / No selection. Below the primary Yes / No, show a stack of secondary per-purpose toggles for the optional purposes (REFERRAL, PAYMENTS, COMMUNICATIONS_SMS, COMMUNICATIONS_USSD, RESEARCH, GRIEVANCE_CONTACT). Each toggle carries a one-line plain-language description and a `Consent` or `Optional` chip.

Capture method block: radio for Signature, Thumbprint, Verbal-witnessed, Digital. For Verbal-witnessed, reveal witness-name and witness-role fields below. For Signature and Thumbprint, reveal an inline capture pad (signature canvas on CAPI; file-upload on Web).

Footer action bar: `Refuse` (destructive secondary), `Capture consent and continue` (primary). Refuse opens a modal demanding a refusal reason from a controlled list and ends the intake with a `Declined consent` outcome.

Empty state is not applicable; this is always the first interaction. Error state: capture-method missing, witness missing for verbal, or statement language not selected.

CAPI: one question per screen with a sticky progress bar.

---

**Screen 2. Citizen consent dashboard** — anchor stories US-065, US-S26-CONSENT-CITIZEN-VIEW.

A single page the citizen reaches after authenticating to the portal, or that a Parish Chief reaches under assisted access. List every consent record for every member of the household the citizen heads.

Layout: header card with member selector (head defaults to self; other members listed below with relationship). Main body: table of consent records, one row per purpose. Columns: Purpose, Current state (chip), Lawful basis (chip, read-only), Granted on, Last change, Action. Action column shows a `Withdraw` link only when the purpose is withdrawable and the state is `Granted`. Disabled `Withdraw` links carry a tooltip explaining the lawful-basis reason ("Public task under DPPA 2019 §7(2)(b)(i). Contact the DPO for review.").

A subtle audit-trail link at the bottom opens the full history side panel for the selected member, listing every state change with timestamp and capture channel.

Empty state: "No consent records yet for this member." (Should not appear in production; surfaced for the design system.)

Mobile: stack the table into cards with the chip and action on the right.

---

**Screen 3. Withdrawal request flow** — anchor story US-S26-CONSENT-CITIZEN-WITHDRAW.

A two-step modal launched from the dashboard `Withdraw` action.

Step 1: Confirm the withdrawal. Show the purpose, the current statement version, plain-language consequences ("If you withdraw REFERRAL, NSR will stop sharing your record with new programmes. Active referrals will be notified you have withdrawn."), and a reason selector (optional). Primary action: `Submit withdrawal request`.

Step 2: Ticket confirmation. Show the ticket ID, the 30-day statutory clock with a deadline date, the next step ("DPO reviews and confirms within 30 days. You will receive an SMS when the decision is made."), and a print/save option. The ticket is also added to the dashboard with a `In DPO review` chip.

Error state: network failure during submission. Provide a clear retry path; the ticket is idempotent.

---

**Screen 4. DPO withdrawal queue** — anchor story US-S26-CONSENT-DPO-WITHDRAWAL-QUEUE.

Queue + detail, same pattern as the DIH review queue (Section 11.3 of the brief).

Top: filters (Purpose, Sub-region, Days remaining in SLA, Capture channel, Ticket state). Quick filters: `SLA breach risk (under 5 days)`, `Public-task purposes`, `Bulk DIH-origin`.

Main table: Ticket ID, Household, Member, Purpose, Captured via, Days open / SLA, Current state, Assigned to, Action. Row click opens a detail panel.

Detail panel: three columns. Column 1: the consent record history for the member (every prior state change with version pointer). Column 2: the impact summary (downstream effects, active programme referrals, SMS subscriptions, pending DRS extracts). Column 3: decision panel (radio for `Confirm withdrawal`, `Override (public task)`, `Request clarification`, `Hold for clarification`), required reason note, decision-document upload, signature line.

Bulk action: only enabled for `Confirm withdrawal` on tickets that share the same purpose and have zero active referrals. Up to 50 at a time. Bulk over 1000 requires a second approver.

Empty state: "No withdrawal tickets in your queue."

---

**Screen 5. Purpose catalogue editor (DPO)** — anchor story US-S26-CONSENT-PURPOSE-CRUD.

List + form pattern.

List view: table of purposes with columns Code, Display name, Lawful basis, Withdrawable, Default on, Status, Created by, Approved by. Status chip uses the same `Draft / Active / Retired` palette. Toolbar: `New purpose`, search, filter by status.

Detail / edit view: form with Code (uppercase snake, locked after create), Display name per language (tabs for English + Ugandan languages), Lawful basis selector (radio cards with the six options), Withdrawable toggle (greyed and forced off when lawful basis is `Statistical exemption`), Default on toggle, Description (rich text, citizen-facing).

Footer: dual-approval action bar. Author submits `Save as draft` or `Submit for approval`. A second DPO approves with `Activate` or `Request changes`. Approve disabled when current user is the author (no self-approval).

Audit panel on the side lists every state change.

Empty state: not applicable in production; design a system-default seed view showing the 9 purposes from the scope.

---

**Screen 6. Statement version editor (DPO)** — anchor story US-S26-CONSENT-STATEMENT-VERSIONING.

A versioning editor scoped to one purpose. Reached from the purpose detail.

Layout: left rail listing every version of the statement (Version 3 — Active, Version 2 — Superseded, Version 1 — Superseded). Selecting a version opens it on the right in read-only mode.

`New version` opens a side-by-side diff editor: left column is the current Active version (read-only); right column is the new draft (editable). Tabs across the top of each column switch language. Below the editor: an `Effective from` date picker, a `Mark as material change` toggle (forces re-consent of every existing GRANTED record on activation), and a textarea for change rationale.

Footer: `Save draft`, `Submit for approval`. A second DPO opens the same screen, reviews the diff, and clicks `Activate`. On activation, the prior version moves to `Superseded`. If `Mark as material change` was on, every member with a GRANTED record on that purpose is flagged for re-consent; show the operator the count before they click Activate ("Activating will flag 9.1M records for re-consent. Confirm.").

---

**Screen 7. Household / member consent badge surface (operator screens)** — anchor story US-S26-CONSENT-PROPAGATION-REF and US-S26-CONSENT-DQA-RULES.

Not a standalone screen. Design the badge cluster that appears at the top of every household detail and every member detail screen, embedded into the existing tabbed layout (Section 11.9 of the brief).

Show a row of small status chips, one per purpose, with the purpose code on the chip and the state colour. Hover or tap reveals a popover with the lawful basis and the date of last change. Click on a chip opens the consent history side panel for that purpose.

This component must render at 13/18 caption size so it fits the header without crowding the existing badges (Registry ID lifecycle, PMT band, IDV status).

Empty state: "No consent records." Should not appear in production.

---

**Screen 8. DIH fast-track consent attestation panel** — anchor story US-S26-CONSENT-DIH-FAST-TRACK.

Embedded into the DIH ConnectorRun detail (Section 11.4 of the brief). A new collapsible card titled "Consent attestation".

Content: source DPA reference (DPA-2026-UBOS-001, with link), DPA scope summary (which purposes are auto-granted under the DPA), DPO ratification status (`Ratified` chip with date + signer; `Pending DPO review` chip if not yet), and a per-batch count of synthetic consent records the run will create on promotion.

Action button (NSR Coordinator only): `Request DPO ratification` when status is pending. Opens a workflow ticket routed to the DPO.

---

**Screen 9. DPO consent coverage dashboard** — anchor story US-S26-CONSENT-REPORTING.

KPI grid + alert list (same pattern as Section 11.8 of the brief).

KPI cards: Total members with active REGISTRATION consent, Withdrawal rate (rolling 30 days), Records pending re-consent due to statement supersession, Average withdrawal SLA (days), Withdrawal tickets breaching SLA, Active purpose count, DPA fast-track count.

Charts: stacked area of granted / refused / withdrawn over 12 months, per purpose; map heat of withdrawal rate by sub-region; bar chart of withdrawal tickets by purpose.

Alert list: SLA breach tickets, statement versions awaiting DPO approval, purposes awaiting approval, DPA ratifications pending.

Empty state per card: "No data yet."

---

### Cross-cutting requirements

- Every state change has an audit-trail entry. Surface the audit through the side-panel pattern in Section 5.4 of the brief.
- Reason-required prompts on every destructive action (Refuse, Withdraw, Override, Retire).
- Plain-language statements rendered as Markdown with a serif body face within a content card; do not force operator-console typography on citizen-facing legal text.
- All citizen-facing text is bilingual-ready. Test layouts at 130% string length per Section 9 of the brief.
- WCAG 2.1 AA, 4.5:1 contrast on body text. Status chip colour is never the only cue; always include a label.
- Reduced motion respected.
- USSD is text-only menus; do not design pixel screens for USSD but include a one-screen wireframe of the menu tree (lookup current consent state, request callback for assisted withdrawal).

### Deliverables

For each screen above:

1. Desktop layout at 1440 px.
2. Tablet layout at 768 px (where the screen is used on CAPI or in the field).
3. Mobile layout at 360 px (citizen portal screens only).
4. Empty state.
5. The most common error state.
6. The audit-trail side panel where applicable.

Annotate each design with the user story it anchors. Highlight any deviation from the existing component library so the architecture team can decide whether to extend the library or adjust the design.

### Out of scope for this design pass

- USSD pixel-level screens.
- Programme-MIS-side consent UI. Partner programmes capture their own consent terms; NSR only records that a referral was made under a granted purpose.
- Hard-erasure execution UI. Handled by US-068 retention service.

End of prompt.

---

## After Claude Design responds

Walk the output past the DPO + NSR Coordinator. Specifically check:

- Does Screen 1 give the operator a way to capture verbal-with-witness without slowing the queue?
- Does Screen 4 give the DPO enough impact context to decide in under 5 minutes per ticket?
- Are the per-purpose toggles on Screen 1 understandable to a citizen at a parish desk who may have low literacy?

Iterate on those three before signing the design off into `/design/v0.2/`.
