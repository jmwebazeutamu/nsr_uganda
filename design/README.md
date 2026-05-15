# /design — NSR MIS Design Handoff

This folder holds the design source-of-truth for the NSR MIS operator console and CAPI tablet UI. It is structured as a **runnable React preview harness at the root** plus a **versioned design snapshot under `v0.1/`** that the engineering team builds against.

## Layout

```
/design
├── README.md                       # this file
├── nsr-mis-console.html            # preview harness — open in a browser to view all screens
├── styles.css                      # harness stylesheet; consumes v0.1/tokens.css variables
├── app.jsx                         # harness shell: routing, role switcher, layout chrome
├── components.jsx                  # shared component library (Chip, KPI, PageHeader, Field, …)
├── tweaks-panel.jsx                # design-time controls (device, role, density)
└── v0.1/                           # versioned design snapshot — engineering builds against this
    ├── tokens.css                  # design tokens (colours, type, spacing, shape) — §4 of the brief
    ├── components.md               # component library contract for the dev team
    ├── acceptance.md               # screen → user story map + per-screen acceptance gates
    └── screens/                    # screens, organised by module (one JSX file per module)
        ├── screens-home.jsx        # HomeScreen, KitScreen — role-aware dashboard (row 10)
        ├── screens-capture.jsx     # CaptureScreen, ReceiptScreen, ReceiptOverlay (rows 1, 1b, 2, 2b)
        ├── screens-dih.jsx         # DIHScreen — review queue + connector runs (rows 3, 4)
        ├── screens-dedup.jsx       # DedupScreen — side-by-side compare (row 5)
        ├── screens-upd.jsx         # UPDScreen — reviewer with PMT preview (row 6)
        └── screens-drs.jsx         # DRSScreen — DRS wizard, 6 steps (rows 7, 7b, 7c, 7d)
```

**Why JSX-by-module, not one HTML per screen.** A real registry screen is a stateful, branching surface — Capture is one component with desktop and CAPI variants driven by a `device` prop; Home is one component with a `role` prop; DRS is one component with six wizard steps. Splitting these into per-state static HTML files lost the state and doubled the maintenance. The acceptance gates in `v0.1/acceptance.md` are anchored to the **screen state**, not the file name; the component is the unit of delivery.

## How to view the preview

Serve `/design` over a local HTTP server, then open the harness in a browser. **Opening the HTML file directly does NOT work** — modern browsers (Chrome, Safari with default settings, Firefox) block the `<script src="*.jsx">` fetches under the `file://` protocol because Babel-standalone needs to load them via XHR.

From a terminal:

```
cd /Users/johnsonmwebaze/nsr_sris_dev/design
python3 -m http.server 8765
```

Then in your browser visit:

```
http://localhost:8765/nsr-mis-console.html
```

Leave the terminal window open while you preview; `Ctrl+C` to stop the server. If port `8765` is in use, pick another (`8000`, `9000`, etc.).

**One-shot shell alias** (drop this in `~/.zshrc` so it's one command next time):

```sh
alias nsr-preview='cd /Users/johnsonmwebaze/nsr_sris_dev/design && python3 -m http.server 8765'
```

Then `nsr-preview` from any new terminal, and open `http://localhost:8765/nsr-mis-console.html`.

The harness loads `v0.1/tokens.css` first (defining the CSS variables), then `styles.css`, then the JSX files via Babel-standalone.

The tweaks panel (bottom-right, dev-only) toggles device (desktop / CAPI tablet), role (Parish Chief, CDO, District M&E, NSR Unit Coordinator, DPO), and density (comfortable / compact). Use it to satisfy the cross-cutting acceptance gates in one session.

## Source documents

- **Brief that generated this folder**: `/docs/04_ui_design_brief.md`.
- **Architecture sections the screens must conform to**: `/docs/01_solution_architecture.docx` §4 (modules) and §8 (NFRs incl. accessibility).
- **User stories anchored to each screen**: `/docs/03_backlog.xlsx`.

## How to add a new screen

1. Pick a user story from the backlog. Confirm priority is Must or Should.
2. Add a row to `v0.1/acceptance.md` mapping the screen to the user story, listing the target JSX file and exported component.
3. If the screen belongs to an existing module, extend that `screens-<module>.jsx`. Only create a new file when adding a new module.
4. Export the screen via `Object.assign(window, { <ComponentName> })` so the harness can route to it.
5. Use only `var(--…)` references for colour, font, type, and spacing — never hard-code a hex, px, or font family outside `tokens.css`.
6. Wire it into `app.jsx` routing and into the tweaks panel where state variants exist.
7. Run the local server (`nsr-preview`) and open `http://localhost:8765/nsr-mis-console.html` at 1366 wide; run the per-screen acceptance gates in `v0.1/acceptance.md`.
8. Commit with message `[US-XXX] design(<screen>): add <ComponentName>`.

## How to revise an existing screen

1. Bump the design version: copy `v0.1/` to `v0.2/` and revise there. Keep `v0.1/` immutable for the engineering team that built against it.
2. Document the diff in `v0.2/CHANGELOG.md`.
3. Update the harness `<script>` and `<link>` paths in `nsr-mis-console.html` to point at the new version.
4. Update `/CLAUDE.md`'s `/design` layout block to point at the new version.

## What this folder is NOT

- It is not a working frontend. The engineering team builds Vue or React components that match this contract.
- It is not the final implementation pixel-by-pixel. Engineering may make small adjustments to fit the framework idiom, but tokens, status vocabulary, and acceptance gates are binding.
- It is not a place for marketing pages, hero illustrations, or anything not anchored to a user story.

## Known gaps in v0.1

- **Screen 8 (DPO cumulative volume console, US-103)** — not yet built.
- **Screen 9 (Household detail registry view, US-005, US-090)** — not yet built.

Both are listed in `v0.1/acceptance.md` with their gates; the components themselves remain to be added before v0.1 can be signed off.

## Version

0.1 — 14 May 2026. Owner: NSR MIS Architecture Team.
