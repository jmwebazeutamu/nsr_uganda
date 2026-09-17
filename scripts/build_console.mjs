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
 * Usage:  node scripts/build_console.mjs
 * Output: static/console/
 */

import { readFile, writeFile, mkdir, copyFile, rm } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import * as esbuild from "esbuild";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const DESIGN = path.join(ROOT, "design");
const HARNESS = path.join(DESIGN, "nsr-mis-console.html");
const OUT_DIR = path.join(ROOT, "static", "console");
const JS_DIR = path.join(OUT_DIR, "js");

/** The babel script srcs from the harness, in load order. Order is the
 *  dependency graph — there is no other one. */
async function scriptOrder() {
  const html = await readFile(HARNESS, "utf8");
  const re = /<script\s+type="text\/babel"\s+src="([^"]+)"\s*><\/script>/g;
  const files = [];
  let m;
  while ((m = re.exec(html)) !== null) files.push(m[1]);
  if (!files.length) {
    throw new Error(`no <script type="text/babel"> tags found in ${HARNESS}`);
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
  const files = await scriptOrder();
  await rm(JS_DIR, { recursive: true, force: true });
  await mkdir(JS_DIR, { recursive: true });

  const manifest = [];
  let bytesIn = 0;
  let bytesOut = 0;

  for (const rel of files) {
    const abs = path.join(DESIGN, rel);
    if (!existsSync(abs)) {
      throw new Error(`harness references a missing file: ${rel}`);
    }
    let src = await readFile(abs, "utf8");
    bytesIn += Buffer.byteLength(src);

    if (INLINE_FLAGS[rel]) src = `${INLINE_FLAGS[rel]}\n${src}`;

    // React and ReactDOM are UMD globals here, never imports, so the JSX
    // factory has to name them explicitly.
    const out = await esbuild.transform(src, {
      loader: "jsx",
      jsx: "transform",
      jsxFactory: "React.createElement",
      jsxFragment: "React.Fragment",
      target: "es2019",
      minify: true,
      legalComments: "none",
      sourcefile: rel,
    });
    for (const w of out.warnings) {
      console.warn(`  warn ${rel}: ${w.text}`);
    }

    const name = outName(rel);
    await writeFile(path.join(JS_DIR, name), out.code, "utf8");
    bytesOut += Buffer.byteLength(out.code);
    manifest.push(name);
  }

  // The template renders script tags from this, so load order survives
  // in data rather than being retyped into HTML and silently drifting.
  await writeFile(
    path.join(OUT_DIR, "manifest.json"),
    JSON.stringify({ scripts: manifest }, null, 2),
    "utf8",
  );

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

  const kb = (n) => (n / 1024).toFixed(0) + " KB";
  console.log(`  sources     : ${files.length} files, ${kb(bytesIn)}`);
  console.log(`  compiled    : ${manifest.length} files, ${kb(bytesOut)} (minified)`);
  console.log(`  console.css : ${kb(Buffer.byteLength(css))}`);
  console.log(`  -> ${path.relative(ROOT, OUT_DIR)}`);
  console.log(`  browser no longer downloads Babel (3.1 MB) or compiles JSX`);
}

build().catch((err) => {
  console.error("console build FAILED:", err.message);
  process.exit(1);
});
