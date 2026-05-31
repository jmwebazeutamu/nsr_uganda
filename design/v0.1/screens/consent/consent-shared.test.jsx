/* Tests for the consent module's canonical vocabulary + admin stub exports.
 *
 * The most important assertion is the CONSENT-O-01 reconciliation (locked
 * 2026-05-30, ADR-0024): the frontend PURPOSES must carry ELIGIBILITY (the
 * PMT-gating purpose) and must NOT carry the designer's inferred
 * IDENTITY_VERIFICATION, so the backend catalogue and the screens agree.
 */

import { beforeAll, describe, expect, it } from "vitest";

let PURPOSES;
let PURPOSE_BY_CODE;
let CONSENT_STATE_TONE;
let TICKET_STATE_TONE;
let LANGUAGES;

beforeAll(async () => {
  globalThis.React = await import("react").then(m => m.default || m);
  // UI primitives referenced by the vocabulary + stub modules.
  globalThis.Icon = () => null;
  globalThis.Chip = () => null;
  globalThis.KPI = () => null;
  globalThis.PageHeader = () => null;
  globalThis.window = globalThis;

  await import("./consent-shared.jsx");
  ({ PURPOSES, PURPOSE_BY_CODE, CONSENT_STATE_TONE, TICKET_STATE_TONE, LANGUAGES } = globalThis);
});

describe("consent-shared PURPOSES (CONSENT-O-01)", () => {
  it("carries the scope-doc nine including ELIGIBILITY", () => {
    expect(PURPOSES).toHaveLength(9);
    const codes = PURPOSES.map(p => p.code);
    expect(codes).toContain("ELIGIBILITY");
    expect(codes).toContain("REGISTRATION");
    expect(codes).toContain("GRIEVANCE_CONTACT");
  });

  it("does NOT carry the designer's inferred IDENTITY_VERIFICATION", () => {
    expect(PURPOSE_BY_CODE.IDENTITY_VERIFICATION).toBeUndefined();
  });

  it("marks STATISTICS non-withdrawable (statistical exemption)", () => {
    expect(PURPOSE_BY_CODE.STATISTICS.withdrawable).toBe(false);
  });

  it("ELIGIBILITY is a withdrawable consent purpose", () => {
    expect(PURPOSE_BY_CODE.ELIGIBILITY.basis).toBe("Consent");
    expect(PURPOSE_BY_CODE.ELIGIBILITY.withdrawable).toBe(true);
  });
});

describe("consent-shared tone maps + languages", () => {
  it("exposes the five consent states the backend emits as labels", () => {
    expect(Object.keys(CONSENT_STATE_TONE)).toEqual(
      expect.arrayContaining(["Granted", "Refused", "Withdrawn", "Pending review", "Pending re-consent"]));
  });

  it("exposes the six withdrawal ticket states", () => {
    expect(Object.keys(TICKET_STATE_TONE)).toHaveLength(6);
  });

  it("lists the seven statement languages", () => {
    expect(LANGUAGES).toHaveLength(7);
    expect(LANGUAGES[0].code).toBe("en");
  });
});

describe("consent admin stub screens", () => {
  it("export the three S27 admin stub components", async () => {
    await import("./screens-consent-admin-stubs.jsx");
    expect(typeof globalThis.ConsentPurposesScreen).toBe("function");
    expect(typeof globalThis.ConsentStatementsScreen).toBe("function");
    expect(typeof globalThis.ConsentCoverageScreen).toBe("function");
  });
});

describe("consent badge cluster (US-CONSENT-08)", () => {
  let projectConsentMatrix;
  beforeAll(async () => {
    globalThis.ConsentStateChip = () => null;
    globalThis.AuditDrawer = () => null;
    await import("./consent-badge-cluster.jsx");
    ({ projectConsentMatrix } = globalThis);
    expect(typeof globalThis.ConsentBadgeCluster).toBe("function");
  });

  it("drops un-captured purposes and keeps acted-on ones", () => {
    const chips = projectConsentMatrix({
      member_id: "M1",
      purposes: [
        { purpose_code: "REGISTRATION", name: "Registration", state: "GRANTED", state_label: "Granted", withdrawable: true },
        { purpose_code: "RESEARCH", name: "Research", state: null, state_label: null, withdrawable: true },
        { purpose_code: "STATISTICS", name: "National statistics", state: "GRANTED", state_label: "Granted", withdrawable: false },
      ],
    });
    expect(chips.map(c => c.code)).toEqual(["REGISTRATION", "STATISTICS"]);
    expect(chips[0].state).toBe("Granted");
    expect(chips[1].withdrawable).toBe(false);
  });

  it("returns an empty list for an empty / missing matrix", () => {
    expect(projectConsentMatrix(null)).toEqual([]);
    expect(projectConsentMatrix({ purposes: [] })).toEqual([]);
  });
});
