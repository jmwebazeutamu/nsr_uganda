/* The admin console opens on Approvals.
 *
 * It opened on the PMT dashboard. Approvals is the first item in the
 * first nav group and the only screen in the shell that is a queue —
 * rule versions, choice lists and PMT models waiting on a decision that
 * blocks other people's work.
 *
 * It was not a cosmetic choice. Three DQA rule versions sat pending
 * approval on production while every quality_failed record was blocked
 * on the rule they superseded, and the screen that would have shown them
 * was one click away from where the console opened.
 */

import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SOURCE = fs.readFileSync(path.join(HERE, "app-admin.jsx"), "utf8");

describe("the admin shell's default screen", () => {
  it("is Approvals, not the PMT dashboard", () => {
    expect(SOURCE).toMatch(/ADMIN_DEFAULT_SCREEN\s*=\s*"admin-approvals"/);
  });

  it("still lets a host page choose, so the default is a fallback", () => {
    // window.__defaultScreen is how a deep link or a future route would
    // open the shell somewhere else. Hard-coding the landing screen would
    // take that away.
    expect(SOURCE).toMatch(/window\.__defaultScreen/);
    expect(SOURCE).toMatch(/window\.__defaultScreen\s*\)\s*\|\|\s*ADMIN_DEFAULT_SCREEN/s);
  });

  it("names a screen the shell can actually render", () => {
    // A default pointing at an id with no branch renders a blank shell.
    expect(SOURCE).toMatch(/screen === "admin-approvals"\s*&&/);
  });

  it("is the first item in the first nav group", () => {
    // Landing somewhere other than where the eye starts is its own
    // small confusion.
    const firstItem = SOURCE.indexOf('{ id: "admin-approvals"');
    const pmtItem = SOURCE.indexOf('{ id: "admin-pmt-dashboard"');
    expect(firstItem).toBeGreaterThan(-1);
    expect(firstItem).toBeLessThan(pmtItem);
  });
});
