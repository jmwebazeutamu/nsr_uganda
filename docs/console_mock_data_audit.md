# Console mock-data audit

**Date:** 18 September 2026 · **Scope:** all 62 source files the two consoles load
**Against:** `acfb859` · **Method:** static analysis + live endpoint probes

---

## Why this exists

The home screen shipped to production showing fabricated KPIs — "DIH review
queue 342", "Fast-track auto-promote 61.4%" — against a registry holding 284
households, and greeted every operator by a hardcoded name. Those are fixed.
This audit answers the obvious next question: **where else?**

The dangerous pattern is not a screen that is obviously a mock. It is a screen
that fetches live data *and* keeps fabricated data as its initial state or
fallback. It looks correct, until the API is slow or fails, at which point it
shows invented people with real-looking names, NINs and ULIDs — with nothing to
signal that anything changed.

## Method

1. Every file both harnesses load (62), not just the ones named `screens-*`.
2. For each, find top-level constants whose literal contains fake identities —
   ULID-shaped ids, `Firstname Lastname` pairs, `CM…` NINs.
3. **Check whether the constant is referenced at all.** This matters: the
   first pass flagged `screens-registry-members.jsx` as the worst file in the
   codebase (37 names, 22 NINs) before reachability analysis showed the array
   is `_LEGACY_MEMBERS_UNUSED` — dead code, already retired.
4. For the survivors, classify by *how* they are used, then probe the live
   endpoint that should replace them.

## Summary

| | Count |
|---|---|
| Files analysed | 62 |
| Fabricated fixtures still **referenced** | 20 |
| Fixtures already retired (`_LEGACY_*_UNUSED`) | 3 |
| Screens where mock is a **fallback** behind live data | 5 |
| Screens rendering mock **unconditionally** | 6 |

There is already a convention for retiring this data — `_LEGACY_*_UNUSED` —
used in `screens-registry-members.jsx`, `screens-programme-detail.jsx` and
`screens-programmes.jsx`. New work should follow it rather than inventing
another.

---

## A. Mock as a fallback behind live data — **highest risk**

These fetch real data, but initialise state from a fixture. Until the first
response lands — or if it never does — the operator is looking at invented
records, presented identically to real ones.

| Screen | Fixture | Live calls | How |
|---|---|---|---|
| `screens-dih.jsx` | `MOCK_DIH_ROWS` (13 identities) | 8 | `useState(MOCK_DIH_ROWS)` |
| `screens-upd.jsx` | `UPD_QUEUE` (11) | 5 | `useState(UPD_QUEUE)` |
| `screens-grm.jsx` | `GRM_MOCK_ROWS` (11) | 7 | `useState(GRM_MOCK_ROWS)` |
| `screens-household.jsx` | `DEMO_HH` (4) | 9 | `liveHh \|\| DEMO_HH` |
| `consent/screens-consent-citizen.jsx` | `HOUSEHOLD` (4) | 2 | ternary fallback |

**Fix:** initialise to `null`, render a loading state, and on error show the
error — never the fixture. This is what the home screen and the sidebar badges
now do.

## B. Mock rendered unconditionally — no live fetch at all

| Screen | Fixture | Real endpoint available? |
|---|---|---|
| `screens-admin-security-audit.jsx` | `AUD_EVENTS` (13 fake audit events) | **yes — `/api/v1/security/audit-events/` has 81,709 real events** |
| `screens-admin-refdata-geography.jsx` | `GEO_TREE` | **yes — `/api/v1/reference-data/geographic-units/`, 5 regions / 13,951 units** |
| `screens-admin-security-roles.jsx` | `OPERATOR_SCOPE_OPTIONS` | **yes — `/api/v1/security/operator-scopes/`, 5 rows** |
| `screens-pmt-configuration.jsx` | `PCFG_VERSIONS` | **yes — `/api/v1/admin/pmt/versions/`, 2 rows** |
| `change-request/screens-change-request.jsx` | `ROSTER`, `HH` | partly — `/api/v1/upd/change-requests/` |
| `consent/screens-consent-dpo-queue.jsx` | `TICKETS` | no — `/api/v1/consent/withdrawal-tickets/` returns 503 while `CONSENT_MODULE_ENABLED=False` |

### The one to fix first

`screens-admin-security-audit.jsx` renders **fabricated audit events**, while
81,709 real ones sit behind an endpoint that already answers 200.

Everything this system claims about integrity rests on the hash-linked audit
chain (SAD §8.4). An audit viewer showing invented events undermines precisely
the control it exists to expose — and an auditor or the DPO is the most likely
person to open it.

### The consent DPO queue is a different case

Its mock has no live source because the consent module is deliberately off
(`CONSENT_MODULE_ENABLED=False`, ADR-0024, pending DPO sign-off). The fix there
is not to wire it but to have the screen say the module is disabled, rather
than show a queue of invented withdrawal tickets.

## C. Flagged but clean

Worth recording so the next audit does not re-raise them:

- ~~`screens-pmt-dashboard.jsx` — `PMT_GEO` / `PMT_RECENT_EVENTS` are destructured
  from the live `dash` response (`const PMT_GEO = dash.geo`), not fixtures.~~
  **Wrong — corrected 18 Sep 2026.** The destructuring is real, but it reads
  `usePmtDashboard()`, whose *initial state* was the nine module fixtures
  (`PMT_ACTIVE`, `PMT_BANDS`, `PMT_COVERAGE`, `PMT_VARIABLES_TOP`, `PMT_GEO`,
  `PMT_DRIFT`, `PMT_TRIGGERS`, `PMT_JOB`, `PMT_RECENT_EVENTS`). Before the
  fetch landed, and after any failure, the screen showed a complete invented
  picture of the engine that decides eligibility. Two of the fixtures also
  survived as `||` fallbacks inside the success path, so even a live response
  could render a fabricated coverage total or recompute job.

  This is the audit's **second** method failure, and a different one from the
  inline-JSX blind spot. Checking whether a name resolves to a fixture at its
  point of use is not enough: a hook can shadow a fixture name with live state
  and still be seeded from the fixture. **The question to ask is what the
  screen renders in the first frame and after a failed fetch, not where a name
  is bound.**

  The same fixture leaked across files: `screens-pmt-configuration.jsx` read
  `PMT_ACTIVE.thresholdsLatest` off `window` for its "Daily empirical
  threshold" column, so every version displayed the same four invented score
  cutoffs — the scores at which a household stops being eligible. Fixed by
  adding `thresholds_latest` to the version-detail serializer and reading it
  from the selected version.
- `screens-drs.jsx` — `_PREVIEW_ULIDS` are placeholder ids in a field-preview
  widget, not records.
- `screens-drs-fieldselector.jsx` — `FS_FIELDS` is a field catalogue
  (configuration), not fabricated people.
- `screens-registry-members.jsx`, `screens-programme-detail.jsx`,
  `screens-programmes.jsx` — fixtures already retired as `_LEGACY_*_UNUSED`.

---

## Recommended order

1. **`screens-admin-security-audit.jsx`** — wire to `/api/v1/security/audit-events/`.
   Integrity-bearing and the endpoint is ready.
2. **The five fallback screens (A)** — DIH, UPD, GRM, household, consent-citizen.
   Mechanical: `useState(null)` plus a loading and an error state. These are the
   ones that mislead silently.
3. **Geography, roles, PMT config** — endpoints exist and return real rows.
4. **Consent DPO queue** — show "module disabled" rather than a fake queue.
5. **Delete the retired `_LEGACY_*_UNUSED` arrays.** They still ship ~110 fake
   identities in the bundle and are one edit from being rendered again.

A contract test per screen, in the shape of
`tests/contract/test_home_kpis_are_real.py`, keeps each one fixed.

---

## Progress (18 September 2026)

| Item | State |
|---|---|
| 1. Security audit screen | **done** — reads the real chain and reports what the verifier returns, instead of claiming "✓ verified" unconditionally. (The 816 breaks it first reported were a verifier defect, not chain damage — see `apps/security/integrity.py`; the chain verifies clean.) |
| 2. Five fallback screens | **done** — DIH, UPD, GRM, household, consent-citizen start empty |
| 3. Geography, roles, PMT config | **partly — reopened 19 Sep 2026.** Geography and PMT config read live endpoints. The roles screen does not: removing `OPERATOR_SCOPE_OPTIONS` left `SEC_USERS` in the same file, and that is what the user list renders from. See the reopened item below. |
| 4. Consent DPO queue | **done** — reports the module as disabled rather than inventing tickets |
| 5. Retired `_LEGACY_*` arrays | **done** — 8 fixtures, 377 lines, 151 identities deleted |
| 6. DIH / UPD / change-request detail views | **done** — no specimen record in any of the three |
| 7. Admin console (21 scripts) | **partly** — DDUP model versions, the DDUP pair detail, the PMT dashboard and the five record views are done. `screens-admin-security-roles.jsx` was wrongly counted as live; see below. |
| 8. PMT configuration band cutoffs | **done** — empirical thresholds now come from the selected version, not the dashboard fixture |

Referenced fabricated fixtures: **20 → 10**. Dead fixtures: **8 → 0**. The
ten that remain are the known-clean set (`ROLE_CONTENT` identity fallback,
`NAV`, `PMT_GEO`, `FS_FIELDS`, `_PREVIEW_ULIDS`, `UPD`) plus
change-request's `ROSTER` and `HH`.

## A third pattern: `prop || specimen` in a screen nothing passes a prop to

Found while doing the admin console (item 7), and the most complete miss of
the three.

`screens-admin-details.jsx` holds five record views — geographic unit, UPD
routing rule, user account, DDUP match pair, choice-list option. Each opened
with `const u = unit || { …specimen… }`, which reads as an ordinary default:
the caller passes a record, the specimen is a design-time convenience.

No caller passes a record. The only route into all five was an admin sidebar
group labelled **"Examples (record views)"**, which rendered them with
`onBack` and nothing else. So the fallback was not a fallback — it was the
entire screen, in production, for every visit. The `onSave` and `onMerge`
handlers were equally absent, so the Save and Merge buttons did nothing,
which is the only reason this was harmless.

What they showed:

| Screen | Specimen |
|---|---|
| User | `adong.f@mglsd.go.ug`, MFA state, two sub-county scopes, three IP-stamped audit entries |
| Geographic unit | Moroto district, 42,101 households, five sub-counties, UBOS/OCHA p-codes |
| DDUP match pair | two members at 0.94 similarity, with a Merge button |
| Routing rule / choice option | invented workflow and reference-data configuration |

Fixed by making all five require their record and moving the guard into a
wrapper component — a guard inside the body would put the record view's
`useState` calls behind a condition, which React rejects when the prop
arrives later. The "Examples" nav group is gone; the routes remain, for the
list rows to use once those lists are wired to open a record.

**What to check for next time:** not just "does this name resolve to a
fixture" but "what does this screen render when its data is missing, and how
often is it missing". A default that is always taken is not a default.

## What this audit missed, and the next piece of work

Deleting the dead arrays exposed a gap in the method above. It looked for
**top-level constants** holding three or more fabricated identities. It
therefore did not see fabricated records written **inline in JSX**, which
is where a detail or compare view naturally puts them.

That table has since been worked through. **Re-swept 19 September 2026**
against the shipped manifests, looking for NIN-shaped literals, `+256`
phone numbers and person-name fields:

| Screen | Shipped? | What is left | Assessment |
|---|---|---|---|
| `screens-admin-security-roles.jsx` | yes | `SEC_USERS` — **10 fabricated operator accounts** | **reopened — the real one** |
| `screens-home.jsx` | yes | 9 — `ROLE_CONTENT.person` + KitScreen gallery | intended, documented |
| `screens-drs-querybuilder.jsx` | yes | 2 — "Buganda North/South" | sub-region names, not people |
| `screens-household.jsx` | yes | 1 — `reporter_name` in a sample | needs a look |
| `screens-capture.jsx` | yes | a `+256` number in an SMS notice and a field default | UI sample, not a record |
| `screens-drs-fieldselector.jsx` | yes | a NIN-shaped literal | `_PREVIEW_ULIDS`, a field-preview placeholder |
| `_redesign_reference.jsx`, `*.test.jsx` | **no** | 12 between them | not in either manifest |

DIH, UPD and change-request are clear.

### Reopened: `screens-admin-security-roles.jsx`

Item 3 removed `OPERATOR_SCOPE_OPTIONS` from this file and the screen was
marked done. A **second** fixture in the same file survived and was never
looked at:

```js
const SEC_USERS = [
  { id: "u-akello-p", name: "Akello P.", email: "akello.p@mglsd.go.ug", … },
  …ten of them
];
const [usersState, setUsersState] = useStateSEC(() => secClone(SEC_USERS));
```

The screen's only `fetch` is for geographic units. **There is no fetch for
users at all**, so the user-administration screen of the admin console shows
ten invented operators, always — with plausible government addresses at
`@mglsd.go.ug`, `@opm.go.ug`, `@gulu.go.ug`, `@lyantonde.go.ug` and
`@npm.go.ug`, each with a role, scopes and an MFA state.

This is the screen on which an administrator grants and revokes access. It is
the same defect class as the five record views, and worse in one respect:
those had no `onSave` wired, whereas this one manages local state as though
edits mean something.

`/api/v1/security/users/` (`user_search`) already exists and answers, so the
fix is to wire it, start empty, and guard — the pattern used everywhere else.

**Why the audit missed it twice:** both sweeps keyed on *the fixture named in
the previous finding*. Once `OPERATOR_SCOPE_OPTIONS` was gone the file looked
clean. One fixture per file was never a safe assumption.
