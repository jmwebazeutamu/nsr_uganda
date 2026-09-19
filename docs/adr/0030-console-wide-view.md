# ADR-0030: A wide view for the console's list screens

- **Status**: Accepted
- **Date**: 19 September 2026
- **Owner**: NSR MIS Architecture Team
- **Decision-makers**: NSR Unit Coordinator, Engineering Lead
- **References**: SAD §7 (operator surfaces), ADR-0009 (admin and console UI strategy); `design/v0.1/components/wide-view.jsx`, `design/app.jsx`, `design/v0.1/screens/screens-dih.jsx`

---

## Context

The console's list screens stack a table over a detail rail. On the DIH
review queue the table sits in a scroll box fixed at 280px — about five rows
— with the staged record, DDUP candidates and decision panel beneath it. With
82 records in the queue an operator scanning for SLA breaches pages through
seventeen screenfuls of five.

That shape is right for reviewing *a record*: the list is context, the record
is the work. It is wrong for triage, where the list is the work. Both happen
on the same screen, and at 12 million households the second will dominate.

Three things were considered and rejected as the primary fix:

- **Just make the box taller.** It helps on a large monitor and does nothing
  on a laptop, because the space is spent on the detail rail that is always
  rendered whether or not the operator is reading a record.
- **Collapse the detail rail.** Cheapest, but it makes the common case worse:
  the operator who *is* reviewing records now has a panel to re-open
  constantly, and the screen has two modes with no name for either.
- **Pagination.** A different problem. Paging controls the number of rows
  fetched; they do not change how many of the fetched rows are visible, which
  is what an operator is complaining about when five of 82 are on screen.

## Decision

### D1. One pattern, two entry points.

`design/v0.1/components/wide-view.jsx` gives any list screen:

| | |
|---|---|
| **Maximise** | An in-page overlay (`.wide-shell`, `position: fixed; inset: 0`) over the masthead and sidebar. Nothing navigates, so no state is lost, no popup blocker is involved, and Escape restores it. |
| **Pop out** | A second browser window at `?wide=<screen>`, which the app shell recognises at boot and renders with no nav and no masthead. |

Both set `isWide`, so a screen writes one branch. What differs is who
supplies the chrome.

### D2. The pop-out is the same application, not a copy of the table.

It loads the console at a URL, on the same session cookie, and mounts the
real screen component. Every action works because it *is* the screen —
selection, bulk promote, opening a record, the audit drawer — rather than a
rendered snapshot that would quietly go stale and could not write.

The alternative — cloning the table's DOM into `window.open` — is smaller and
wrong: it produces a surface that looks like the console, shows personal data,
and cannot act on it.

### D3. State passes one way, at open time.

The pop-out URL carries the current filters as a JSON query parameter. After
that the windows are independent and each refetches from the API.

Live cross-window sync (BroadcastChannel) was considered. It is a real
distributed-state problem — two windows, two caches, two operators' worth of
optimistic updates over an audit-bearing queue — and the benefit over "both
windows refetch" is small. Not now; ADR this if it is ever wanted.

Inherited filters are validated before use: anything that is not a plain JSON
object is ignored rather than applied. The URL is user-editable, and a queue
of personal data should not filter itself on whatever a query string says.

### D4. In the wide view the detail becomes a right-hand drawer.

Selecting a row opens `.drawer.drawer-wide` (min(1180px, 94vw)) over the
table, carrying exactly the markup and handlers the stacked rail has. The
operator keeps their place in the list; the decision panel is one click away
rather than one scroll.

Entering the wide view clears the current selection. The queue auto-selects
its first row on load so the stacked rail is never empty — carried into wide
mode, that would open the drawer over the list the operator just asked to see.

Escape closes the drawer before it leaves the overlay: one key, least
destructive thing first.

### D5. Screens opt in, and the ones that have not say so.

`WIDE_SCREENS` in `design/app.jsx` maps a screen id to its renderer. A
`?wide=` for anything else renders a plain statement that the screen has no
wide view yet, rather than a normal-width screen in a window the operator
opened expressly to get a wider one.

### D6. A blocked pop-out falls back to maximising.

`window.open` returning null is indistinguishable from a broken button. The
operator asked for a wider view, so they get the one that cannot be blocked.

## Consequences

**Good**

- The queue table's scroll box goes from a fixed 280px to
  `calc(100vh - 240px)`. A queue row is about 71px at comfortable density
  (two lines: head and parish) and about 50px at compact, so on a 900px-tall
  laptop that is roughly four rows before and nine after, or thirteen
  compact; on a 1440px monitor, seventeen and twenty-four. Two to four times
  more of the queue, not an order of magnitude — the row height is the
  remaining constraint, and shortening it is a separate design question.
- The pop-out can sit on a second screen beside the decision panel, which is
  the case the in-page overlay cannot serve at all.
- Nothing changes for a screen that does not opt in, and nothing changes in
  the normal layout of a screen that does. `WideShell` and `WideDetailHost`
  are transparent when the wide view is off, which is what makes the rollout
  to the remaining lists a per-screen change rather than a rewrite.
- No new API, no new endpoint, no change to what is fetched or audited. The
  popped window's reads are ordinary authenticated API reads and are audited
  exactly as the console's are.

**Costs and limits**

- A second window is a second live session on the same account. It is subject
  to the same permissions and the same audit trail, but two windows mean two
  views of a queue that can move underneath them; a record promoted in one
  window remains listed in the other until that window refetches. This is the
  price of D3 and is visible to the operator as a stale row, not as a failed
  action — the API rejects a second decision on the same record.
- The wide view does not change how many rows are fetched. A page still caps
  at what the screen requests, and pagination remains its own piece of work.
- `?wide=` is the console's first URL-addressable state. It is deliberately
  not a router: it is read once at boot and never written. Introducing real
  routing is a larger decision and should have its own ADR.

## Rollout — complete, 20 September 2026

Proven on the DIH review queue, then applied to the rest. Eight ids are
registered: `dih`, `registry`, `registry-members`, `dedup`, `grm`, `drs`,
`beneficiaries`, `partners`.

Three shapes turned up, and the pattern bent to each rather than the
other way round:

| Shape | Screens | What the wide view does |
|---|---|---|
| Table over a detail rail | DIH queue, Duplicates | Detail becomes the drawer; the table takes the window |
| Table, row opens another screen | Social Registry, Members, Beneficiaries, Partners | No drawer needed — the table takes the window, and a pop-out can open the record in its own window (see below) |
| List beside a 380px detail column | Grievances, Data Requests | The split stacks: a fixed rail beside a wide list wastes the width the operator just asked for |

Two things the first pass did not anticipate:

- **A pop-out has to be able to open what it lists.** A wide list is for
  triage, and triage means opening the thing you find. `WIDE_DETAILS`
  gives the wide window a short stack — the list is the root, a record
  opens over it, Back returns — covering household, member and partner
  detail. Anything else says where to go rather than rendering a screen
  without the props it needs.
- **The hook must sit above every early return.** Most of these screens
  return early while loading or when a different view is selected. A
  `useWideView` below that parses cleanly and then changes hook order
  between renders, which React treats as a different component — and it
  only shows up on the branch that returns early. Every hook is declared
  at the top of its component, and a test asserts it.

`design/v0.1/wide-view-rollout.test.js` holds the registry to its
promise: every id in `WIDE_SCREENS` is claimed by a shipped screen that
renders the buttons and wraps itself in `WideShell`, the module loads
before its callers, the detail targets exist, and no hook sits below a
top-level return.

## Tested by

- `design/v0.1/components/wide-view.test.jsx` — 22 cases: the URL contract,
  what it refuses to inherit, the overlay, the drawer, Escape layering, the
  blocked-popup fallback.
- `design/v0.1/screens/screens-dih-wide-view.test.jsx` — 8 cases on the
  review queue itself, including that the normal layout is unchanged.
- `tests/contract/test_console_wide_view.py` — 9 cases: manifest load order
  in both shells, survival of the production build, and that `?wide=` is
  served to a session and refused without one.
