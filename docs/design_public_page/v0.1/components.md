# NSR MIS — Component Library

**Source**: UI Design Brief §5. **Tokens**: `tokens.css`. **Version**: 0.1, 14 May 2026.

This file is the dev-team handoff contract. For each component: props, states, accessibility notes, where it is used. The mockups produced by Claude Design implement these components. Frontend implementation (Vue or React) must match.

---

## 5.1 Chip / Status badge

A pill-shaped label.

| Prop | Type | Notes |
|---|---|---|
| `variant` | enum | `provisional`, `pending`, `registered`, `rejected`, `voided`, `blocking`, `warning`, `info`, `public`, `internal`, `personal`, `sensitive`, `module-<code>` |
| `label` | string | Required. Never colour-only. |
| `icon` | optional | Only for `sensitive` (lock) by default |

**States**: default; hover (slight darken on background, +5%); focus-visible (outline ring per `--focus-ring`).

**Accessibility**: each chip carries both colour and label (Section 10).

**Where used**: tables (Captures, Updates, Duplicates, Grievances, Data Requests), record detail headers, audit panel rows, DRS Field Selector sensitivity badges.

**CSS classes**: `.chip .chip--{variant}`.

---

## 5.2 Field-level diff card

Two-column before/after card. Used in UPD review and dedup compare.

| Prop | Type | Notes |
|---|---|---|
| `field` | string | Field label (i18n key) |
| `before` | any | Renderable as text |
| `after` | any | Renderable as text |
| `similarity` | optional number 0–1 | Shown on hover (dedup only) |
| `changed` | boolean | When true, left border in `--accent-update`, background tint `--accent-update-bg` |

**States**: unchanged (collapsed by default in UPD; toggle "Show all fields" expands), changed (highlighted), conflicting (when A and B differ in a dedup three-way match).

**Accessibility**: each diff row is a `<dl>` with `<dt>` for the field label and two `<dd>` siblings. Screen reader announces "Field X. Before: Y. After: Z".

---

## 5.3 Side-by-side compare component

Three columns (or up to four for three-way matches): Candidate A, Candidate B, Merge Result.

| Prop | Type | Notes |
|---|---|---|
| `candidates` | array[Record] | 2 or 3 candidates |
| `fields` | array[FieldSpec] | Each field with `name`, `type`, `is_list_like` |
| `onSelect` | (field, choice) => void | choice is `A`, `B`, or `Both` |
| `note` | string | Required before commit |
| `onCommit` | () => void | Disabled until every field has a chosen value AND note is non-empty |

**States**: per-field selection (A / B / Both); `Both` disabled with tooltip for non-list fields; `Add note` textarea always visible; `Commit merge` disabled until ready.

**Accessibility**: radios are grouped with `role="radiogroup"` per field. Tab moves between rows; arrow keys move within a row.

**Where used**: DAT-DDUP merge (US-083), DIH review queue Promote-as-merge (US-109).

---

## 5.4 Audit chain side panel

A right-rail drawer.

| Prop | Type | Notes |
|---|---|---|
| `recordId` | ULID | Target record |
| `recordType` | string | `household`, `member`, `change_request`, `match_pair`, etc. |
| `filter` | object | Optional filter by actor, action, date range |

**States**: collapsed (closed), expanded (open at 360px), per-event detail expand on click.

**Accessibility**: drawer is a `<aside>` with `aria-label="Audit chain"`. ESC closes it. Sticky filter at the top is keyboard-reachable.

**Where used**: every detail screen that touches personal data; mandatory on DIH review queue and UPD reviewer.

---

## 5.5 Data table with toolbar

The default operator table.

| Prop | Type | Notes |
|---|---|---|
| `columns` | array[ColumnSpec] | Each column has `key`, `label`, `sortable`, `width`, `align`, `formatter` |
| `rows` | array[Record] | |
| `density` | enum | `comfortable` or `compact` |
| `selectionMode` | enum | `none`, `single`, `multi` |
| `bulkActions` | array[Action] | Only shown when `selectionMode === 'multi'` |
| `onRowClick` | (row) => void | |
| `csvExport` | boolean | |
| `pagination` | cursor or offset | |

**States**: empty (with a message and a primary call-to-action), loading (skeleton rows), error, populated.

**Accessibility**: column headers are `<th scope="col">`. Sort icons have `aria-sort`. Row selection has `aria-checked`.

**Where used**: Captures queue, Updates queue, Duplicates queue, Grievances, DRS request queue, Connector runs.

---

## 5.6 KPI card

A 1x1 metric card.

| Prop | Type | Notes |
|---|---|---|
| `title` | string | Caption-size |
| `value` | number or string | Display-size |
| `trend` | optional object | `{ direction: 'up'\|'down'\|'flat', delta_pct: number }` |
| `sparkline` | optional array[number] | Last 30 datapoints |
| `link` | optional URL | Card click navigates here |

**States**: default, hover (subtle background tint), focus-visible.

**Accessibility**: the whole card is a single link or button. Trend direction is announced as text ("up 12 percent vs last week"), not just an icon.

**Where used**: Home dashboard (every role), DIH ConnectorRun KPI strip, DPO cumulative volume console.

---

## 5.7 Form field

The default form field.

| Prop | Type | Notes |
|---|---|---|
| `label` | string | Always required |
| `name` | string | |
| `type` | enum | `text`, `number`, `date`, `phone`, `nin`, `gps`, `geo_picker`, `choice`, `multi_choice`, `currency`, `textarea`, `file`, `photo` |
| `value` | any | |
| `onChange` | (v) => void | |
| `required` | boolean | Red asterisk + `aria-required` |
| `helperText` | string | |
| `errorText` | string | Replaces helperText when set |
| `mask` | optional regex | For NIN, phone |

**States**: empty, focused, valid, invalid (with error text), disabled (with tooltip explaining why), readonly.

**Accessibility**: label `<label for="...">`. Error text linked via `aria-describedby` and `aria-invalid`. Placeholder never replaces label.

---

## 5.8 Approval action bar

A sticky bottom bar on review screens.

| Prop | Type | Notes |
|---|---|---|
| `actions` | array[Action] | Each action has `id`, `label`, `variant` (`danger`, `neutral`, `primary`), `disabled`, `disabledReason` |
| `currentUserCanApprove` | boolean | If false (no-self-approve), Approve is disabled with tooltip |
| `onAction` | (id) => Promise<void> | Resolves after modal confirms |

**States**: idle, modal open, action in flight.

**Accessibility**: keyboard shortcuts: Cmd/Ctrl+Enter approves, Cmd/Ctrl+Backspace rejects. Reach via Tab; ESC dismisses modal.

**Where used**: DIH review queue (US-109), UPD reviewer (US-090), DRS approval queue (US-102), Dedup compare (US-083).

---

## 5.9 Geographic tree picker

A nested combobox.

| Prop | Type | Notes |
|---|---|---|
| `value` | object | `{ region_id, sub_region_id, district_id, county_id, sub_county_id, parish_id, village_id }` |
| `onChange` | (v) => void | |
| `maxLevel` | enum | Default `village`. Set to `parish` if village not required. |
| `scope` | optional array | Restrict to operator's geographic scope from RBAC |
| `disabled` | boolean | |

**States**: empty, partial selection, fully selected. Each level disabled until parent is chosen.

**Accessibility**: combobox pattern per WAI-ARIA. Each level is a separate combobox with `aria-controls` pointing to its child.

**Where used**: Parish operator capture (US-088), DRS Query Builder (US-097), filter rows on every queue.

---

## 5.10 Sensitivity badge (DRS)

Specialised chip for the Field Selector.

| Prop | Type | Notes |
|---|---|---|
| `sensitivity` | enum | `public`, `internal`, `personal`, `sensitive` |
| `dsaClause` | optional string | Shown in tooltip for disabled `sensitive` fields |

**Where used**: DRS Field Selector (US-098) only.

---

## Components Claude Design may have added

If Claude Design produced any of the following, they should be reviewed and either renamed to match this catalogue or accepted as new components with a new section in this file:

- **Stepper** (multi-step form progress) — accept; used in Section 11.1 and 11.7.
- **Side-rail navigator** (section-by-section completion ticks on capture) — accept; used in Section 11.1.
- **Diff JSON viewer** (raw JSON expand on UPD detail) — accept.
- **Receipt slip preview** — accept; printable A6 layout.
- **PMT preview card** — accept; used in UPD reviewer (Section 11.6).
- **Empty-state card** — accept across many screens.

For anything else (hero strips, marketing cards, decorative gradients), do not accept; ask Claude Design to remove. Reference: design principle 1 ("government tone, not consumer playfulness").

---

## How to review the Claude Design output

When the design folder lands, run through this checklist:

1. Every chip uses the `.chip` + `.chip--{variant}` class pattern from `tokens.css`. No hex colours hardcoded.
2. Every screen renders at 1366 wide without horizontal scroll.
3. Every Critical Action button (Approve, Reject, Commit Merge, Submit Request, Promote) opens a modal that demands a reason.
4. Status vocabulary in §8 of the brief is exhausted: every chip type appears at least once across the screens.
5. The audit chain side panel appears on at least two screens.
6. Components above appear at least once and behave per the props table.
7. No marketing language, no hero illustrations, no celebratory animations.
8. WCAG 2.1 AA: keyboard navigation works, focus rings visible, contrast at 4.5:1 minimum.

If any of these fail, request a refinement from Claude Design before handoff to engineering.

---

End of components.md, v0.1.
