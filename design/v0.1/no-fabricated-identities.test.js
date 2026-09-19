/* Guard: no fabricated identity data in the files the consoles ship.
 *
 * Why this exists
 * ---------------
 * The mock-data cleanup ran three times and missed the same screen twice.
 * Each pass searched for *the fixture named in the previous finding*, so
 * once `OPERATOR_SCOPE_OPTIONS` was gone from the Roles & scopes screen the
 * file read as clean — while `SEC_USERS`, ten invented operator accounts
 * with @mglsd.go.ug addresses, sat forty lines above it and was what the
 * user table actually rendered.
 *
 * A human sweep keyed on names cannot be repeated reliably. This one is
 * mechanical: it takes the two console HTML manifests, reads every .jsx
 * they load, and fails on the literal shapes that only ever appear in
 * fabricated records — Ugandan NINs, +256 subscriber numbers, and
 * government e-mail addresses.
 *
 * Adding an entry to ALLOWED is deliberate and must carry a reason. That
 * is the point: the exception becomes visible in review rather than
 * invisible in a file nobody re-reads.
 */

import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const DESIGN = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const MANIFESTS = ["nsr-mis-console.html", "nsr-mis-admin-console.html"];

const PATTERNS = {
  // Uganda NIN: CM/CF + 12 alphanumerics. Never legitimately hardcoded.
  nin: /\b(?:CM|CF)[0-9A-Z]{10,}\b/,
  // A +256 number with a full subscriber part — a real-looking phone.
  phone: /\+256[\s-]?\d{2,3}[\s-]?\d{3}[\s-]?\d{3}/,
  // Government mailbox: an operator identity, not UI copy.
  govEmail: /[\w.+-]+@(?:[a-z0-9-]+\.)*go\.ug/,
};

/** file → patterns it may contain, each with the reason it is not a record. */
const ALLOWED = {
  "v0.1/screens/screens-drs-fieldselector.jsx": {
    nin: "Field-picker preview: `example: \"CM12345678ABCD\"` shows the NIN "
       + "column's format next to its sensitivity label. Sequential digits, "
       + "no person attached, never rendered as a record.",
  },
  "v0.1/screens/screens-home.jsx": {
    phone: "KitScreen is the component gallery — it demonstrates a filled "
         + "text input. It is not a record view and reads no API.",
  },
};

const shippedFiles = () => {
  const files = new Set();
  for (const manifest of MANIFESTS) {
    const html = fs.readFileSync(path.join(DESIGN, manifest), "utf8");
    for (const [, src] of html.matchAll(/src="([^"]+\.jsx)"/g)) {
      files.add(src.replace(/^\.\//, ""));
    }
  }
  return [...files].sort();
};

describe("shipped console files carry no fabricated identities", () => {
  const files = shippedFiles();

  it("finds the console manifests and the files they load", () => {
    // A manifest that stops resolving would make every case below pass
    // vacuously — which is how the previous sweeps went wrong.
    expect(files.length).toBeGreaterThan(40);
  });

  it.each(files)("%s", (relative) => {
    const full = path.join(DESIGN, relative);
    expect(fs.existsSync(full), `${relative} is listed in a manifest but missing`).toBe(true);
    const lines = fs.readFileSync(full, "utf8").split("\n");
    const allowed = ALLOWED[relative] || {};
    const findings = [];

    for (const [name, pattern] of Object.entries(PATTERNS)) {
      if (allowed[name]) continue;
      lines.forEach((line, i) => {
        const hit = line.match(pattern);
        if (hit) findings.push(`${relative}:${i + 1} [${name}] ${hit[0]} — ${line.trim().slice(0, 90)}`);
      });
    }

    expect(
      findings,
      `Fabricated identity data in a file the console ships:\n${findings.join("\n")}\n\n`
      + "Wire the screen to its API and start empty, or — if this really is "
      + "UI copy rather than a record — add it to ALLOWED in this file with "
      + "the reason.",
    ).toEqual([]);
  });
});
