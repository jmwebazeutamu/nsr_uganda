/* The Updates link points at the update that exists.
 *
 * "Open linked UPD" built an id by concatenating the literal
 * "01HXYUPD" with the tail of the grievance id, then navigated to it.
 * The view mapper meanwhile dropped `linked_change_request_id`, so the
 * case panel never saw a real link and kept offering to open another
 * draft; and the Updates queue had no tab that asked for drafts, which
 * is the status a GRM-raised update starts in.
 */

import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

const read = (p) => fs.readFileSync(path.join(process.cwd(), p), "utf8");

// Comments are stripped before the "never synthesises" check: the
// removal is documented in the very comment that would trip it.
const code = (source) => source
  .replace(/\/\*[\s\S]*?\*\//g, "")
  .split("\n")
  .map(line => line.replace(/(^|\s)\/\/.*$/, "$1"))
  .join("\n");

const grm = code(read("design/v0.1/screens/screens-grm.jsx"));
const upd = code(read("design/v0.1/screens/screens-upd.jsx"));

describe("the linked update is the one that exists", () => {
  it("never synthesises a change-request id", () => {
    expect(grm).not.toContain("01HXYUPD");
  });

  it("carries linked_change_request_id through the view mapper", () => {
    // Without this the case panel's DATA UPDATE block never saw a link
    // and kept offering to open a second draft.
    expect(grm).toContain("linked_change_request_id: g.linked_change_request_id");
  });

  it("navigates to the id the server gave it", () => {
    expect(grm).toMatch(
      /changeRequestId: current\.linked_change_request_id/,
    );
  });
});

describe("the Updates queue has somewhere for a GRM draft to land", () => {
  it("has a tab that asks for drafts", () => {
    expect(upd).toMatch(/drafts:\s*"draft"/);
    expect(upd).toContain('{ id: "drafts", label: "Drafts" }');
  });

  it("does not show an SLA clock on a request that has not started one", () => {
    expect(upd).toMatch(/tab === "drafts" \?/);
  });
});
