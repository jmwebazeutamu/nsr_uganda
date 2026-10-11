import { beforeAll, describe, expect, it } from "vitest";

let buildMemberListUrl;
let memberFilterChoiceLists;

beforeAll(async () => {
  globalThis.React = await import("react").then(m => m.default || m);
  globalThis.window = globalThis;
  await import("./screens-registry-members.jsx");
  buildMemberListUrl = globalThis._buildMemberListUrl;
  memberFilterChoiceLists = globalThis.MEMBER_FILTER_CHOICE_LISTS;
});

describe("Registry member filter contracts", () => {
  it("uses the Reference Data relationship ChoiceList", () => {
    expect(memberFilterChoiceLists).toContain("relationship");
    expect(memberFilterChoiceLists).not.toContain("relationship_to_head");
  });

  it("sends a member-ID query to the canonical member endpoint", () => {
    expect(buildMemberListUrl({ q: "01MEMBERID" }, 1, 12))
      .toContain("q=01MEMBERID");
  });
});
