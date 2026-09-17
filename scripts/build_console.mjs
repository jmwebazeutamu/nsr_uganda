/**
 * Precompile the operator console for production.
 *
 * Why this exists
 * ---------------
 * The console is a design harness: 47 JSX files loaded as
 * `<script type="text/babel">` and compiled IN THE BROWSER by a 3.1 MB
 * Babel-standalone, with React, ReactDOM and d3 fetched from unpkg. Fine
 * for design review on a laptop; not fine for the operator surface of a
 * national registry:
 *
 *   - 3.1 MB of Babel downloaded and a full JSX compile on every load,
 *     over the connectivity a district office actually has;
 *   - React and ReactDOM pulled as DEVELOPMENT builds — larger, slower,
 *     and shipping dev-only warnings;
 *   - four third-party requests (unpkg x3, Google Fonts) on a page that
 *     renders personal data, disclosing every operator's IP. The public
 *     site already self-hosts its font precisely to avoid this;
 *   - d3 requested as `@7` — a FLOATING major version with NO integrity
 *     hash — so whatever unpkg serves that day executes in the console.
 *
 * What it does, and deliberately does not do
 * ------------------------------------------
 * It compiles each JSX file to plain JS and emits ONE OUTPUT FILE PER
 * SOURCE FILE, loaded by the production page as ordinary <script> tags
 * in the harness's order.
 *
 * It does NOT concatenate them into a single bundle, and it does NOT
 * convert the sources to ES modules. Not one of the 55 JSX files uses
 * `export`; they declare globals and depend on being evaluated as
 * separate classic scripts. Concatenation looked obvious and is wrong:
 * building it that way failed on 11 duplicate top-level declarations
 * (`initials` and `KPI` in components.jsx are redeclared in
 * screens-change-request.jsx and screens-data-explorer-coverage.jsx,
 * `_humanize` and `_deriveColumns` twice inside data-explorer). Merging
 * them into one script changes which declarations collide, so the safe
 * transformation is the one that keeps the script boundaries exactly
 * where they are.
 *
 * (Those duplicates are a pre-existing latent bug — see
 * docs/console_production_build.md. This build neither fixes nor worsens
 * them; it just refuses to pretend they are not there.)
 *
 * The only thing that moves is WHERE the JSX compile happens: build time
 * instead of the operator's browser.
 *
 * Two harnesses, one output
 * ------------------------
 * There are two shells — the operator console (nsr-mis-console.html, 47
 * scripts) and the admin console (nsr-mis-admin-console.html, 21). They
 * overlap by only 6 files, so each unique source is compiled ONCE into a
 * shared js/ directory and each harness gets its own manifest naming the
 * files it loads, in its own order.
 *
 * Usage:  node scripts/build_console.mjs
 * Output: static/console/
 */

import { readFile, writeFile, mkdir, copyFile, rm } from "node:fs/promises";
import vm from "node:vm";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import * as esbuild from "esbuild";
import * as Babel from "@babel/standalone";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const DESIGN = path.join(ROOT, "design");
const OUT_DIR = path.join(ROOT, "static", "console");
const JS_DIR = path.join(OUT_DIR, "js");

/** The shells to build. `manifest` is what the matching Django view reads. */
const HARNESSES = [
  { name: "operator console", html: "nsr-mis-console.html", manifest: "manifest.json" },
  { name: "admin console", html: "nsr-mis-admin-console.html", manifest: "manifest-admin.json" },
];

/** The babel script srcs from the harness, in load order. Order is the
 *  dependency graph — there is no other one. */
async function scriptOrder(harnessFile) {
  const html = await readFile(path.join(DESIGN, harnessFile), "utf8");
  const re = /<script\s+type="text\/babel"\s+src="([^"]+)"\s*><\/script>/g;
  const files = [];
  let m;
  while ((m = re.exec(html)) !== null) files.push(m[1]);
  if (!files.length) {
    throw new Error(`no <script type="text/babel"> tags found in ${harnessFile}`);
  }
  return files;
}

/** Inline flags the harness sets between script tags. NSR_EMBEDDED_CONSOLE
 *  makes the data-explorer screens export their components instead of
 *  taking over #app, and must be set before those files evaluate. */
const INLINE_FLAGS = {
  "v0.1/screens/data-explorer/data-explorer-shared.jsx":
    "window.NSR_EMBEDDED_CONSOLE = true;",
};

/** Output path for a source file: v0.1/screens/foo.jsx -> v0.1-screens-foo.js */
const outName = (rel) => rel.replace(/\.jsx$/, "").replace(/[\/]/g, "-") + ".js";

async function build() {
  // Every harness's file list, and the union to compile.
  const lists = [];
  for (const h of HARNESSES) {
    lists.push({ ...h, files: await scriptOrder(h.html) });
  }
  const unique = [...new Set(lists.flatMap((l) => l.files))];

  await rm(JS_DIR, { recursive: true, force: true });
  await mkdir(JS_DIR, { recursive: true });

  let bytesIn = 0;
  let bytesOut = 0;

  // Compile each source ONCE — the two shells share six files.
  for (const rel of unique) {
    const abs = path.join(DESIGN, rel);
    if (!existsSync(abs)) {
      throw new Error(`a harness references a missing file: ${rel}`);
    }
    let src = await readFile(abs, "utf8");
    bytesIn += Buffer.byteLength(src);

    if (INLINE_FLAGS[rel]) src = `${INLINE_FLAGS[rel]}\n${src}`;

    // Transform with @babel/standalone using the SAME presets the harness
    // uses at runtime — ["react", "env"] — not with esbuild.
    //
    // This is a correctness choice, not a stylistic one. The `env` preset
    // downlevels top-level `const` to `var`. The sources carry TEN
    // duplicate top-level declarations across files (`Fact` in both
    // data-explorer-catalogue and screens-household, `KPI` in both
    // components and data-explorer-coverage, and eight more). As `var`
    // those redeclarations are legal and silently overwrite. As `const`
    // in a classic script they throw "Identifier has already been
    // declared" — and the ENTIRE file fails to evaluate, taking its
    // screens with it.
    //
    // Compiling with esbuild at target es2019 kept `const`, so eight
    // screens — household detail among them — silently stopped rendering
    // in production while still working in dev. Matching the harness's
    // transform removes that whole class of divergence: the deployed
    // console runs the same JavaScript the harness produces, compiled
    // ahead of time instead of in the browser.
    //
    // The duplicate names are still a real latent bug — last definition
    // wins, across files, by load order. Renaming them would change which
    // definition ~30 other files resolve to, so that is separate work.
    // See docs/console_production_build.md.
    const transformed = Babel.transform(src, {
      presets: ["react", "env"],
      filename: rel,
      compact: false,
      sourceType: "script",
    });

    // esbuild remains the minifier: fast, and semantics-neutral here
    // because Babel has already downlevelled.
    const out = await esbuild.transform(transformed.code, {
      target: "es5",
      minify: true,
      legalComments: "none",
      sourcefile: rel,
    });
    for (const w of out.warnings) console.warn(`  warn ${rel}: ${w.text}`);

    await writeFile(path.join(JS_DIR, outName(rel)), out.code, "utf8");
    bytesOut += Buffer.byteLength(out.code);
  }

  // One manifest per shell. The template renders script tags from it, so
  // load order lives in data and cannot drift from the harness.
  for (const l of lists) {
    await writeFile(
      path.join(OUT_DIR, l.manifest),
      JSON.stringify({ scripts: l.files.map(outName) }, null, 2),
      "utf8",
    );
  }

  // Styles: the harness loads tokens.css then styles.css, in that order.
  const css = [
    await readFile(path.join(DESIGN, "v0.1", "tokens.css"), "utf8"),
    await readFile(path.join(DESIGN, "styles.css"), "utf8"),
  ].join("\n");
  await writeFile(path.join(OUT_DIR, "console.css"), css, "utf8");

  // Map data the coverage screens fetch at runtime.
  const geo = path.join(DESIGN, "assets", "maps", "uganda-adm2.geojson");
  if (existsSync(geo)) {
    await mkdir(path.join(OUT_DIR, "maps"), { recursive: true });
    await copyFile(geo, path.join(OUT_DIR, "maps", "uganda-adm2.geojson"));
  }

  // --- verify the output can actually run --------------------------------
  // The bug this guards against was invisible: eight screens, household
  // detail among them, silently failed to evaluate in production while
  // working in dev, because a duplicate top-level `const` throws in a
  // classic script and kills the whole file. Nothing in the build or the
  // page reported it — the screen simply never rendered.
  //
  // So the build now runs every shell's scripts in one shared context,
  // exactly as a browser evaluates consecutive <script> tags, and FAILS
  // if any of them throws. A console that cannot load cannot be built.
  for (const l of lists) {
    const sandbox = {
      document: {
        createElement: () => ({ style: {}, setAttribute() {}, appendChild() {} }),
        addEventListener() {}, querySelector: () => null,
        getElementById: () => ({}), head: { appendChild() {} },
        body: { appendChild() {} }, cookie: "",
      },
      React: new Proxy(function () {}, {
        get: (t, k) => (k === "Component" ? class {} : () => null),
        apply: () => null,
      }),
      ReactDOM: { createRoot: () => ({ render() {} }), render() {} },
      d3: new Proxy(function () {}, { get: () => () => null, apply: () => null }),
      fetch: () => Promise.resolve({ json: () => ({}), ok: true }),
      console: { log() {}, warn() {}, error() {}, info() {} },
      setTimeout, clearTimeout, setInterval, clearInterval,
      localStorage: { getItem() {}, setItem() {}, removeItem() {} },
      location: { href: "", pathname: "/console/" }, navigator: {},
    };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    sandbox.self = sandbox;
    const ctx = vm.createContext(sandbox);

    const broken = [];
    for (const f of l.files.map(outName)) {
      const code = await readFile(path.join(JS_DIR, f), "utf8");
      try {
        vm.runInContext(code, ctx, { filename: f });
      } catch (err) {
        broken.push(`${f}: ${String(err.message).split("\n")[0]}`);
      }
    }
    if (broken.length) {
      console.error(`\n  ${l.name}: ${broken.length} script(s) FAIL to evaluate:`);
      for (const b of broken) console.error(`    ${b}`);
      throw new Error(
        `${l.name} would not load in a browser. A duplicate top-level ` +
        `declaration across two files is the usual cause — the second ` +
        `file throws and every screen in it disappears silently.`,
      );
    }
    console.log(`  ${l.name.padEnd(17)}: all ${l.files.length} scripts evaluate cleanly`);
  }

  const kb = (n) => (n / 1024).toFixed(0) + " KB";
  for (const l of lists) {
    console.log(`  ${l.name.padEnd(17)}: ${String(l.files.length).padStart(2)} scripts -> ${l.manifest}`);
  }
  console.log(`  unique sources   : ${unique.length} files, ${kb(bytesIn)}`);
  console.log(`  compiled         : ${unique.length} files, ${kb(bytesOut)} (minified)`);
  console.log(`  console.css      : ${kb(Buffer.byteLength(css))}`);
  console.log(`  -> ${path.relative(ROOT, OUT_DIR)}`);
  console.log(`  browser no longer downloads Babel (3.1 MB) or compiles JSX`);
}

build().catch((err) => {
  console.error("console build FAILED:", err.message);
  process.exit(1);
});
