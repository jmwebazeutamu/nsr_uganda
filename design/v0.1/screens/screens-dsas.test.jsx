/* Tests for screens-dsas.jsx helpers — the pure pieces that don't
 * need a DOM:
 *
 *   _dsaDaysToExpiry     — handles missing/garbage effective_to,
 *                           returns negative for already-expired DSAs.
 *   buildCreateDsaPayload — builds the JSON the POST /api/v1/dsas/
 *                           endpoint accepts, coerces numbers, drops
 *                           empty strings to nulls / sensible defaults.
 */

import { beforeAll, describe, expect, it } from "vitest";

let _dsaDaysToExpiry;
let buildCreateDsaPayload;
let DSA_STATUSES;

beforeAll(async () => {
  // The screen body references several global UI primitives. Stub
  // each one so the module evaluates cleanly under jsdom.
  globalThis.React = await import("react").then(m => m.default || m);
  globalThis.Icon       = () => null;
  globalThis.Chip       = () => null;
  globalThis.KPI        = () => null;
  globalThis.PageHeader = () => null;
  globalThis.Modal      = () => null;
  globalThis.Field      = () => null;
  globalThis.Toast      = () => null;
  globalThis.useApi     = () => [null, { loading: false, error: null, refresh: () => {} }];
  globalThis.nsrApi     = { get: async () => null, post: async () => null };
  globalThis.ScopeEditModal = () => null;
  globalThis.window = globalThis;

  await import("./screens-dsas.jsx");
  ({
    _dsaDaysToExpiry,
    buildCreateDsaPayload,
    DSA_STATUSES,
  } = globalThis);
});


describe("_dsaDaysToExpiry", () => {
  it("returns null when effective_to is missing", () => {
    expect(_dsaDaysToExpiry({ effective_to: null })).toBeNull();
    expect(_dsaDaysToExpiry({})).toBeNull();
    expect(_dsaDaysToExpiry(null)).toBeNull();
  });

  it("returns null when effective_to is unparseable", () => {
    expect(_dsaDaysToExpiry({ effective_to: "not a date" })).toBeNull();
  });

  it("returns a positive integer when the DSA expires in the future", () => {
    const future = new Date(Date.now() + 10 * 24 * 60 * 60 * 1000);
    const iso = future.toISOString().slice(0, 10);
    const d = _dsaDaysToExpiry({ effective_to: iso });
    // The day count rounds, so allow ±1 day for execution timing.
    expect(d).toBeGreaterThanOrEqual(9);
    expect(d).toBeLessThanOrEqual(11);
  });

  it("returns a negative integer when the DSA is already expired", () => {
    const past = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000);
    const iso = past.toISOString().slice(0, 10);
    const d = _dsaDaysToExpiry({ effective_to: iso });
    expect(d).toBeLessThan(0);
  });
});


describe("buildCreateDsaPayload", () => {
  const baseForm = {
    partner_id: "01ABC",
    reference: "  DSA-NEW-1  ",      // trims whitespace
    effective_from: "2026-01-01",
    effective_to: "2026-12-31",
    monthly_row_budget: "100000",   // coerces to Number
    entities: { household: true, member: true, referral: false },
    fields:   { Identifiers: true, PMT: false, Roster: true },
    sensitive_data_handling: "none",
    retention_days: "180",
    classification: "Restricted",
    dpia_document_ref: "DPIA-001",
    breach_sla_hours: "72",
  };

  it("creates a DRAFT row by default", () => {
    const p = buildCreateDsaPayload(baseForm);
    expect(p.status).toBe("draft");
  });

  it("trims the reference and forwards the partner id", () => {
    const p = buildCreateDsaPayload(baseForm);
    expect(p.reference).toBe("DSA-NEW-1");
    expect(p.partner).toBe("01ABC");
  });

  it("coerces budget + retention + sla to numbers", () => {
    const p = buildCreateDsaPayload(baseForm);
    expect(p.monthly_row_budget).toBe(100000);
    expect(p.retention_days).toBe(180);
    expect(p.breach_sla_hours).toBe(72);
  });

  it("empty monthly budget translates to null (unbounded)", () => {
    const p = buildCreateDsaPayload({ ...baseForm, monthly_row_budget: "" });
    expect(p.monthly_row_budget).toBeNull();
  });

  it("missing retention / SLA defaults to 180 / 72", () => {
    const p = buildCreateDsaPayload({
      ...baseForm, retention_days: "", breach_sla_hours: "",
    });
    expect(p.retention_days).toBe(180);
    expect(p.breach_sla_hours).toBe(72);
  });

  it("clones entities + field_scope (no shared reference)", () => {
    const p = buildCreateDsaPayload(baseForm);
    expect(p.entities_scope).toEqual({ household: true, member: true, referral: false });
    expect(p.field_scope).toEqual({ Identifiers: true, PMT: false, Roster: true });
    // Mutating the payload doesn't affect the source form.
    p.entities_scope.household = false;
    expect(baseForm.entities.household).toBe(true);
  });

  it("missing dates fall through as null", () => {
    const p = buildCreateDsaPayload({
      ...baseForm, effective_from: "", effective_to: "",
    });
    expect(p.effective_from).toBeNull();
    expect(p.effective_to).toBeNull();
  });
});


describe("DSA_STATUSES catalogue", () => {
  it("exposes every status the workspace filter offers", () => {
    const ids = DSA_STATUSES.map(s => s.id);
    expect(ids).toEqual([
      "draft", "pending_signature", "active",
      "expiring", "expired", "suspended", "renewed",
    ]);
  });

  it("every entry carries a label + tone", () => {
    for (const s of DSA_STATUSES) {
      expect(s.label).toBeTruthy();
      expect(s.tone).toBeTruthy();
    }
  });
});
