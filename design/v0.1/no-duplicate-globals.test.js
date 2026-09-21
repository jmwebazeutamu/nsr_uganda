/* Two files must not declare the same top-level name.
 *
 * The console shells load their files as CLASSIC scripts, which share
 * one global scope. A top-level `const X` in one file and a top-level
 * `const X` in another is not two things — it is one thing, and which
 * one you get depends on manifest load order. The later file wins, for
 * every reference in every file.
 *
 * That is not theoretical. `household-review.jsx` declared
 * `ReviewSection`; `app-change-request.jsx` declares a different
 * `ReviewSection` taking `{ scope, member, rows, ... }` and loads 13
 * files later. So every `<ReviewSection>` in the household review
 * resolved to that one, whose first statement is
 * `const fieldCount = rows.length` — and opening a detailed review
 * crashed the screen with "Cannot read properties of undefined
 * (reading 'length')".
 *
 * Nothing caught it: the Vitest suites import files as ES modules,
 * where each file's top-level scope is its own, so the collision cannot
 * happen there. It only exists in the browser, and only through the
 * build. Which is precisely why this check reads the MANIFESTS rather
 * than trusting the test environment.
 *
 * scripts/build_console.mjs has documented these as a latent bug since
 * the production build was written. KNOWN below is that backlog,
 * frozen: the list may shrink, never grow.
 */

import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

// design/ — the shells and every file they name live here.
const DESIGN = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SHELLS = ["nsr-mis-console.html", "nsr-mis-admin-console.html"];

/** Top-level declarations only — a line starting at column zero. A
 *  nested one is inside a function scope and cannot collide. */
const DECL = /^(?:const|let|var|function|class)\s+([A-Za-z_$][\w$]*)/;

/** Pre-existing collisions, as of the household-review fix.
 *
 *  Each is a real hazard of the same kind, not an exemption on merit:
 *  whichever file loads last silently defines the name for the whole
 *  application. They are frozen here so the count can only go down —
 *  renaming any of them changes which definition ~30 other files
 *  resolve to, which is its own piece of work.
 */
const KNOWN = new Set([
  "KPI", "initials", "ScopeCard", "Fact", "_humanize", "_deriveColumns",
  "_projectProgramme", "EXIT_TONE", "Toggle", "KIND_TONE",
]);

const duplicatesIn = (shell) => {
  const html = fs.readFileSync(path.join(DESIGN, shell), "utf8");
  const files = [...html.matchAll(/src="([^"]+\.jsx)"/g)]
    .map(m => m[1].replace(/^\.\//, ""));
  const owners = new Map();
  for (const rel of files) {
    const source = fs.readFileSync(path.join(DESIGN, rel), "utf8");
    const seen = new Set();
    for (const line of source.split("\n")) {
      const m = DECL.exec(line);
      if (!m || seen.has(m[1])) continue;
      seen.add(m[1]);
      if (!owners.has(m[1])) owners.set(m[1], []);
      owners.get(m[1]).push(rel);
    }
  }
  return [...owners].filter(([, f]) => f.length > 1);
};

describe.each(SHELLS)("%s", (shell) => {
  it("declares no NEW top-level name twice", () => {
    const found = duplicatesIn(shell)
      .filter(([name]) => !KNOWN.has(name))
      .map(([name, files]) => `${name}: ${files.join(" and ")}`);
    expect(found, "these names resolve to whichever file loads last:\n"
      + found.join("\n")).toEqual([]);
  });

  it("does not silently accumulate known collisions", () => {
    // If a KNOWN name stops colliding, remove it from the list rather
    // than leaving a permitted duplicate that no longer exists.
    const colliding = new Set(duplicatesIn(shell).map(([name]) => name));
    const stale = [...KNOWN].filter(n => !colliding.has(n));
    if (shell !== "nsr-mis-console.html") return;   // KNOWN is that shell's
    expect(stale, `no longer collide — drop from KNOWN: ${stale.join(", ")}`)
      .toEqual([]);
  });
});

describe("the household review specifically", () => {
  it("prefixes its components so they cannot be shadowed", () => {
    // This is the collision that crashed the review.
    const source = fs.readFileSync(
      path.join(DESIGN, "v0.1", "components", "household-review.jsx"), "utf8");
    for (const generic of ["ReviewSection", "ReviewRow", "CodedCell", "RepeatTable"]) {
      expect(source, `${generic} is too generic for a shared global scope`)
        .not.toMatch(new RegExp(`^const ${generic}\\b`, "m"));
    }
    expect(source).toMatch(/^const HhReviewSection\b/m);
  });
});
