/* Bulk actions must report the SERVER's problem, not the parser's.
 *
 * Reported from the console:
 *
 *   Promoted failed: SyntaxError: Unexpected token 'I', "IntegrityE"...
 *     is not valid JSON
 *
 * The call did `r.json()` unconditionally, so a 500 returning Django's
 * HTML error page threw on the first character. The one word that would
 * have explained it — IntegrityError — survived only as debris inside a
 * parser message.
 */

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

let DIHScreen;

const STAGE = (id, over = {}) => ({
  id,
  provisional_registry_id: id,
  state: "pending_promotion",
  canonical_payload: {
    members: [{ is_head: true, surname: "Okello", first_name: "Santo",
                line_number: 1, sex: "1", relationship_to_head: "01" }],
    geographic: { region: "R-NORTHERN", parish: "304.1.01.01" },
  },
  dqa_summary: { blocking_failures: [], warnings: [], info: [] },
  ddup_candidates: [],
  idv_outcome: "",
  created_at: new Date().toISOString(),
  ...over,
});

const DJANGO_500 = `<!DOCTYPE html>
<html lang="en"><head><title>IntegrityError at /api/v1/dih/stage-records/bulk-promote/</title>
</head><body><h1>IntegrityError</h1></body></html>`;

beforeAll(async () => {
  const React = await import("react").then(m => m.default || m);
  globalThis.React = React;
  globalThis.window = globalThis;
  globalThis.Icon = () => null;
  globalThis.Chip = ({ children }) => React.createElement("span", null, children);
  globalThis.KPI = () => null;
  globalThis.PageHeader = ({ title, right }) => React.createElement("div", null, title, right);
  globalThis.AuditDrawer = () => null;
  globalThis.ActionBar = ({ left, children }) => React.createElement("div", null, left, children);
  globalThis.ReasonModal = () => null;
  globalThis.Modal = ({ open, children }) => (open ? React.createElement("div", null, children) : null);
  globalThis.Toast = ({ message }) => (message ? React.createElement("div", { role: "status" }, message) : null);
  globalThis.useNavCounts = () => [{}];
  globalThis.useChoiceList = () => [[], { loading: false, error: null }];
  await import("../components/wide-view.jsx");
  await import("../components/idv-outcomes.jsx");
  await import("./screens-dih.jsx");
  ({ DIHScreen } = globalThis);
});

const listResponse = (rows) => Promise.resolve({
  ok: true, status: 200,
  json: () => Promise.resolve({ results: rows }),
  text: () => Promise.resolve(JSON.stringify({ results: rows })),
});

/** Queue loads normally; the bulk POST answers however the case wants. */
const withBulkResponse = (bulk) => {
  globalThis.fetch = vi.fn((url, init) => {
    if (init && init.method === "POST") return Promise.resolve(bulk);
    if (String(url).includes("stage-records")) {
      return listResponse([STAGE("01BULKAAAAAAAAAAAAAAAAAAAA")]);
    }
    return listResponse([]);
  });
};

beforeEach(() => { document.cookie = "csrftoken=t"; });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const promoteSelected = async () => {
  render(<DIHScreen/>);
  await waitFor(() => expect(screen.getAllByText("Okello Santo").length).toBeGreaterThan(0));

  // Tick the row, which is what reveals the bulk action bar.
  fireEvent.click(document.querySelector('input[type="checkbox"]'));
  const openBulk = await waitFor(() => {
    const btn = [...document.querySelectorAll("button")]
      .find(b => /promote/i.test(b.textContent));
    expect(btn).toBeTruthy();
    return btn;
  });
  fireEvent.click(openBulk);

  // The modal refuses to submit without a reason — the audit chain
  // records one per bulk action, so there is always something to type.
  const reason = await waitFor(() => {
    const el = document.querySelector("textarea");
    expect(el).toBeTruthy();
    return el;
  });
  fireEvent.change(reason, { target: { value: "reviewed and approved" } });
  fireEvent.submit(reason.closest("form"));
};

const toast = async (match) =>
  waitFor(() => expect(screen.getByRole("status").textContent).toMatch(match));


describe("a 500 with an HTML body", () => {
  it("names the exception instead of the parse failure", async () => {
    withBulkResponse({
      ok: false, status: 500,
      text: () => Promise.resolve(DJANGO_500),
      json: () => Promise.reject(new SyntaxError("Unexpected token 'I'")),
    });
    await promoteSelected();
    await toast(/IntegrityError/);
  });

  it("never shows the operator a JSON parser error", async () => {
    withBulkResponse({
      ok: false, status: 500,
      text: () => Promise.resolve(DJANGO_500),
      json: () => Promise.reject(new SyntaxError("Unexpected token 'I'")),
    });
    await promoteSelected();
    await waitFor(() => {
      const text = screen.getByRole("status").textContent;
      expect(text).not.toMatch(/SyntaxError/);
      expect(text).not.toMatch(/is not valid JSON/);
      expect(text).not.toMatch(/Unexpected token/);
    });
  });

  it("falls back to the status when the body says nothing", async () => {
    withBulkResponse({
      ok: false, status: 502,
      text: () => Promise.resolve(""),
      json: () => Promise.reject(new SyntaxError("boom")),
    });
    await promoteSelected();
    await toast(/HTTP 502/);
  });
});


describe("a structured API error", () => {
  it("shows DRF's detail", async () => {
    withBulkResponse({
      ok: false, status: 400,
      text: () => Promise.resolve(JSON.stringify({ detail: "bad request body" })),
      json: () => Promise.resolve({ detail: "bad request body" }),
    });
    await promoteSelected();
    await toast(/bad request body/);
  });

  it("shows per-field serializer errors", async () => {
    const body = { stage_ids: ["This list may not be empty."] };
    withBulkResponse({
      ok: false, status: 400,
      text: () => Promise.resolve(JSON.stringify(body)),
      json: () => Promise.resolve(body),
    });
    await promoteSelected();
    await toast(/stage_ids: This list may not be empty\./);
  });
});


describe("a 200 that skipped rows", () => {
  it("says why the first one was skipped", async () => {
    // The call is 200 whether every row worked or none did. "Promoted 0
    // · skipped 12" with no reason sends the operator to open twelve
    // records one at a time.
    const body = {
      succeeded: 0, skipped: 1,
      results: [{
        stage_id: "01BULKAAAAAAAAAAAAAAAAAAAA", ok: false,
        state: "quarantined",
        detail: "state is 'quarantined', not pending_promotion",
      }],
    };
    withBulkResponse({
      ok: true, status: 200,
      text: () => Promise.resolve(JSON.stringify(body)),
      json: () => Promise.resolve(body),
    });
    await promoteSelected();
    await toast(/not pending_promotion/);
  });

  it("stays quiet about reasons when everything worked", async () => {
    const body = {
      succeeded: 1, skipped: 0,
      results: [{ stage_id: "01BULKAAAAAAAAAAAAAAAAAAAA", ok: true,
                  state: "promoted", detail: "promoted" }],
    };
    withBulkResponse({
      ok: true, status: 200,
      text: () => Promise.resolve(JSON.stringify(body)),
      json: () => Promise.resolve(body),
    });
    await promoteSelected();
    await toast(/Promoted 1 · skipped 0/);
    expect(screen.getByRole("status").textContent).not.toMatch(/first skipped/);
  });
});
