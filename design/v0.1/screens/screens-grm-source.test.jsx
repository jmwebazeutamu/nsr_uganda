/* Where a case came from, on the case panel.
 *
 * An officer asked "what happened to C-26-057528-8" had nothing on
 * this screen to answer with. The case carried the partner's tracking
 * number and the API did not even serve it, so the number a
 * complainant was read back before they hung up existed in the
 * database and nowhere a human could see.
 *
 * The property worth protecting here is not that the block renders —
 * it is that the console never learns what a source is CALLED. The
 * name comes from the source register, server-side. A
 * {"STAAC_GRM": "STAAC"} table in this file would be a vocabulary
 * living nowhere, and renaming a partner would mean a deploy.
 */

import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

const grm = fs.readFileSync(
  path.join(process.cwd(), "design/v0.1/screens/screens-grm.jsx"), "utf8",
);
const code = grm
  .replace(/\/\*[\s\S]*?\*\//g, "")
  .split("\n").map(l => l.replace(/(^|\s)\/\/.*$/, "$1")).join("\n");

describe("the case panel names its source", () => {
  it("carries the source and their reference through the mapper", () => {
    expect(code).toContain("source_system: g.source_system");
    expect(code).toContain("external_reference: g.external_reference");
  });

  it("renders the server's name, not one of its own", () => {
    expect(code).toContain("source_label: g.source_system_label");
    expect(code).toMatch(/\{current\.source_label\}/);
  });

  it("shows their reference beside it", () => {
    expect(code).toMatch(/\{current\.external_reference\}/);
  });

  it("says whose number it is, so it is not read as ours", () => {
    expect(code).toContain("not this registry's case number");
  });
});

describe("the console holds no source vocabulary", () => {
  it("maps no code to a display name", () => {
    // The register owns the names. Any object literal in this file
    // keying a source code to a word is the thing this test exists
    // to stop.
    expect(code).not.toMatch(/STAAC_GRM\s*:\s*["']/);
    expect(code).not.toMatch(/["']NSR-WEB["']\s*:/);
  });

  it("prints no partner name as a literal", () => {
    // "STAAC" must never be written here. If it appears, somebody has
    // started deciding in JSX what the register already says.
    expect(code).not.toMatch(/\bSTAAC\b/);
  });

  it("falls back to the code, never to an invented name", () => {
    // A source the register has no row for shows its code. Showing
    // "Unknown" or "Other" would be this file naming something.
    expect(code).toContain(
      "source_label: g.source_system_label || g.source_system",
    );
  });
});
