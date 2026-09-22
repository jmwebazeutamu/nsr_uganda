/* The DIH working queue is defined once, on the server.
 *
 * The sidebar badge counted state=pending_promotion and read 0 while the
 * screen it pointed at held twelve records. The queue screen listed five
 * states, the home card four, the badge one — three spellings of one
 * concept, which is this project's most common defect.
 *
 * Every caller now asks for ?queue=review. This fails if one starts
 * spelling the list out again.
 */

import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(HERE, "..");

const CALLERS = [
  "v0.1/data/use-nav-counts.jsx",
  "v0.1/screens/screens-dih.jsx",
  "v0.1/screens/screens-home.jsx",
];

// A stage-record fetch that names two or more states in its query string
// is a second definition of the queue.
const HARDCODED = /stage-records\/\?[^"'`]*state=[a-z_]+(?:,[a-z_]+)+/g;

describe("one queue definition", () => {
  it.each(CALLERS)("%s does not spell the state list out", (rel) => {
    const src = fs.readFileSync(path.join(ROOT, rel), "utf8");
    const code = src
      .split("\n")
      .filter((line) => !line.trim().startsWith("//"))
      .join("\n");
    const found = code.match(HARDCODED) || [];
    expect(found, `${rel} names the queue states itself:\n${found.join("\n")}\n`
      + "Use ?queue=review — the server owns the definition.").toEqual([]);
  });

  it("every counter asks the server the same question", () => {
    for (const rel of CALLERS) {
      const src = fs.readFileSync(path.join(ROOT, rel), "utf8");
      expect(src, `${rel} no longer queries the review queue`)
        .toContain("queue=review");
    }
  });
});
