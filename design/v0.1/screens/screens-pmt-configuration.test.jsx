import { beforeAll, describe, expect, it } from "vitest";

let canDiscardPmtDraft;

beforeAll(async () => {
  globalThis.React = await import("react").then(m => m.default || m);
  globalThis.Icon = () => null;
  globalThis.Chip = () => null;
  globalThis.PageHeader = () => null;
  globalThis.window = globalThis;

  await import("./screens-pmt-configuration.jsx");
  ({ canDiscardPmtDraft } = globalThis);
});

describe("canDiscardPmtDraft", () => {
  it("offers discard only for an unsubmitted canonical draft", () => {
    expect(canDiscardPmtDraft({ status: "draft" })).toBe(true);
    expect(canDiscardPmtDraft({ status: "pending_approval" })).toBe(false);
    expect(canDiscardPmtDraft({ status: "active" })).toBe(false);
    expect(canDiscardPmtDraft({ status: "rejected" })).toBe(false);
    expect(canDiscardPmtDraft(null)).toBe(false);
  });
});
