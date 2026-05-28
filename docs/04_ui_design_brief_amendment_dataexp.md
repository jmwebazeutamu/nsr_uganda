# UI Design Brief — Amendment: Data Explorer status vocabulary

**Anchored to:** ADR-0023 §D8, US-DATA-EXP-001.
**Amends:** `/docs/04_ui_design_brief.md` §8 (status vocabulary and badge mapping).
**Status:** Proposed — pending design-team sign-off.
**Date:** 27 May 2026.

---

## Context

The Data Explorer surface (`apps/data_explorer`, ADR-0023) introduces two
visual states that have no current home in §8 of the design brief:

1. A cell in an aggregate result whose count falls below the k-anonymity
   floor and must therefore render as suppressed (not zero, not missing).
2. A dataset or variable whose `PrivacyClass` disallows record-level
   discovery from the Explorer (Sensitive, or a Personal entry whose
   matview only aggregates at sub-region).

The brief's existing chip vocabulary is sufficient for **lifecycle**
(`Provisional` / `Pending` / `Registered`) and for **sensitivity at the
field level** (`Public` / `Internal` / `Personal` / `Sensitive`). It does
not cover **system-side outcomes of a privacy-preserving query**, which
is what these two badges express. Adding them inline as one-off hex
values would fragment the vocabulary; routing them through the brief's
amendment process keeps a single source of truth.

## Proposed additions

### 1. `Suppressed` badge

Appears on each cell of an aggregate result whose count is below the
strictest-class k-anonymity floor. The cell renders `—` in the count
column with this chip alongside; the chart bar renders as a hatched
outline (no fill height).

**Why it's needed.** The Explorer's suppression is a feature, not an
error. Without a chip the user reads "—" as "the query failed" or
"no data here" and either retries pointlessly or contacts the DPO. The
chip names the rule (`Suppressed`), and the tooltip points to ADR-0023.
This is the registry working correctly under the privacy floor, and it
should look that way — calm, neutral, not alarming.

**Proposed token mapping** (per ADR-0023 §D8):

| Layer       | Token         |
|-------------|---------------|
| Foreground  | `--neutral-700` |
| Background  | `--neutral-100` |
| Border      | `--neutral-700` (1px) |
| Icon        | `lock` (16px inline) |

Mirrors the `Voided` treatment in §8 of the brief — same neutral grey,
same calm read. The lock icon distinguishes it from a soft-deleted
record without introducing a new colour family.

**Where it appears.** Aggregate-builder results pane only — both the
table row's count cell (next to the `—` glyph) and, as an `aria-label`
+ `<title>`, the corresponding chart bar.

### 2. `Aggregated-only` badge

Appears on a dataset or variable card whose `PrivacyClass` disallows
record-level discovery from the Explorer. The user can still browse
the catalogue, build aggregates, and see the dictionary entry — but
the "Request record-level data" CTA on the dataset-detail screen is
disabled with the tooltip "Record-level access requires DSA. Contact
your DPO."

**Why it's needed.** The catalogue is permissive on purpose — every
EXPLORER-roled user sees every visible dataset, including those where
the next step (record-level extract) is gated. Without a chip the user
discovers the gate only when they click the disabled CTA. The
`Aggregated-only` chip surfaces the constraint up front, on the card,
so the user routes their question correctly (aggregate here, DSA
request elsewhere) before clicking.

**Proposed token mapping** (per ADR-0023 §D8):

| Layer       | Token                  |
|-------------|------------------------|
| Foreground  | `--accent-system`      |
| Background  | `--accent-system-bg`   |
| Border      | `--accent-system` (1px) |
| Icon        | `lock` (16px inline)   |

The system accent already encodes "internal infrastructure constraint"
in the brief's accent vocabulary (it backs API, SEC, RPT). Re-using it
for "this dataset is constrained by the registry, not by you" keeps
the meaning consistent across modules.

**Where it appears.** Catalogue screen (dataset cards) and
dataset-detail screen (header strip, alongside the PrivacyClass chip).

## Single-source-of-truth requirement

Both badges' tokens and labels are served at runtime by
`GET /api/v1/data-explorer/privacy-classes` and
`GET /api/v1/data-explorer/suppression-vocabulary`, not hardcoded
in the JSX. The JSX reads `{token_fg, token_bg, label}` from the
response. This means:

- A fifth `PrivacyClass` introduced by the architect (e.g. a
  `Restricted` tier) ships without a UI deploy.
- The design team can adjust the token mapping post-launch by
  changing the seed fixture, not the screen code.
- i18n-localised labels flow through Django's translation framework
  on the backend before they reach the client.

## Open items

- **OPEN-A1.** Should `Suppressed` carry a dot indicator in addition
  to the lock icon, matching `Voided`'s dot? Brief §8 uses dots for
  lifecycle chips, not for system-state chips — proposed default:
  no dot, lock icon only.
- **OPEN-A2.** Should `Aggregated-only` use a different icon (e.g.
  `barchart`) to signal "aggregate is fine, record-level is not"?
  Proposed default: `lock` — same icon as Sensitive, but with the
  system accent — so the affordance hierarchy reads
  Sensitive (danger lock) > Aggregated-only (system lock) >
  unmarked (no lock).

The final visual treatment of both badges is the design team's call.
This amendment locks the vocabulary (the two labels, the two token
mappings, and the runtime-from-API rule) but does not lock the
rendering details — padding, dot vs no-dot, icon choice, hover
behaviour, etc. — which the design team should iterate on the
mockups produced from ADR-0023.

---

End of amendment. Author: NSR MIS UI Designer (US-DATA-EXP-001 build
agent). Routed through the design-brief amendment process (§8 of the
brief) per ADR-0023 §D8.
