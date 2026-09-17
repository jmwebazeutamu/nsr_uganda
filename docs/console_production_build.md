# Operator console — production build

**Date:** 17 September 2026
**Status:** implemented
**References:** ADR-0009 (admin/console UI strategy), `scripts/build_console.mjs`,
`tests/contract/test_console_production_build.py`

---

## The problem this fixes

`/console/` returned **404 in production** for the whole of Sprint 0, on both
the training box and the MGLSD production server. `/admin/` worked; nothing
else did.

The cause was not a deployment error. `nsr_mis.views.console` served raw
files out of `design/`, and `design/` has been excluded from the Docker
build context since the first Sprint-0 commit (`243f89b`). In a container
those files do not exist, so the view could only raise
`Http404("design asset not found: ...")`. `/admin-console/` failed the same
way (same directory), and `/manual/` too (its MkDocs output is both
gitignored and excluded).

ADR-0009 describes the console as *"a runnable design harness, not a
deployed app"* while also anticipating it being *"served by nginx in
production"*. The second half was never built. This is that work.

## Why the harness could not just be shipped

Copying `design/` into the image would have made `/console/` return 200, and
would have been the wrong fix. The harness:

- downloads **3.1 MB of Babel-standalone** and compiles 47 JSX files **in the
  browser**, on every page load, over whatever connectivity a district
  office has;
- loads React and ReactDOM as **development** builds — larger, slower, and
  emitting dev-only warnings;
- makes **four third-party requests** (unpkg ×3, Google Fonts) from a page
  that renders personal data. Each one discloses an operator's IP address to
  that third party. The public site already self-hosts its font specifically
  to avoid this processing under the DPPA 2019; the console was doing the
  thing the public site was careful not to;
- requests **d3 as `@7`** — a floating major version with **no integrity
  hash**. Whatever unpkg served that day executed in a console rendering
  registry data.

The last point is a supply-chain exposure, not a performance note.

## What was built

`scripts/build_console.mjs` compiles the JSX at **image build time** and
emits `static/console/`. A `console-build` stage in the Dockerfile runs it;
only the compiled output crosses into the runtime image, so the final image
contains no JSX, no Babel and no node.

There are **two** shells, not one: the operator console
(`nsr-mis-console.html`, 47 scripts) and the admin console
(`nsr-mis-admin-console.html`, 21). They overlap by only six files, so
each unique source is compiled once into a shared `js/` directory and
each shell gets its own manifest — `manifest.json` and
`manifest-admin.json` — naming the files it loads, in its own order.
Loading the operator list in the admin shell would pull in screens it
does not have and miss the ones it does.

`nsr_mis/templates/console/index.html` is the production shell, used by
both; they differ only in the script list and the page title. It loads the
compiled scripts, React/ReactDOM **production** builds, a pinned local d3
`7.9.0`, and a self-hosted Inter. **It makes no third-party request at all.**

`nsr_mis.views.console` chooses between them by what is on disk — the
presence of `static/console/manifest.json` — not by `DEBUG`, so a developer
who runs the build sees exactly what operators see. Sub-paths
(`/console/app.jsx`) still fall through to the harness in a dev checkout,
which other contract tests rely on.

## What was deliberately NOT done

**The sources were not converted to ES modules.** Not one of the 55 JSX
files uses `export`; they declare globals and depend on being evaluated in
the order the harness lists them. Converting them would touch every file and
every screen for no user-visible gain.

**The output is not a single bundle.** That was the first attempt and it was
wrong. Concatenating the files failed on **11 duplicate top-level
declarations**, and the failure is informative: with separate `<script>`
tags each file's top-level `const` lands in the shared global lexical
environment, so merging them changes which declarations collide. The safe
transformation keeps the script boundaries exactly where the harness has
them. One compiled file per source file, loaded in the same order.

The only thing that moves is **where the JSX compile happens**.

## Latent bug this surfaced (not fixed here)

The build revealed duplicate top-level `const` declarations across files:

| Symbol | Declared in |
|---|---|
| `initials` | `components.jsx`, `change-request/screens-change-request.jsx` |
| `KPI` | `components.jsx`, `data-explorer/screens-data-explorer-coverage.jsx` |
| `_humanize` | `data-explorer/screens-data-explorer-synthetic.jsx`, `...-results.jsx` |
| `_deriveColumns` | same two data-explorer files |
| `ScopeCard` | `change-request/app-change-request.jsx` (+ another) |

Top-level `const` in a classic script goes into the **global** lexical
environment, shared by every script on the page. A redeclaration throws
`SyntaxError: Identifier 'X' has already been declared`, and the **entire
second file fails to evaluate** — silently, taking all of its components
with it.

This behaviour is identical before and after this change: the same files
load in the same order into the same environment. The build neither
introduces nor fixes it. It is recorded here because it is worth a story of
its own — the affected screens (change-request, data-explorer coverage,
data-explorer results/synthetic) should be checked for components that never
render.

## Rebuilding

```bash
npm ci
node scripts/build_console.mjs      # -> static/console/
```

The output is gitignored; the image builds it. `manifest.json` records the
load order, and a contract test fails if it drifts from the harness — so a
screen added to the harness but not rebuilt cannot silently go missing.

## Still outstanding

- `/manual/` 404s for the same reason. It needs `mkdocs build` run and the
  output shipped; the build directory is currently gitignored.
- `apps/intake/static/intake/vendor/babel-7.29.0.min.js` (3.1 MB) remains in
  the image for the FormVersion interactive preview admin template. Separate,
  pre-existing, out of scope here.
