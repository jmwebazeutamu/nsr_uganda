/* QA P3.20 — one "Open a grievance" dialog.
 *
 * There were two, and they disagreed about what a grievance is. The
 * workbench's could not name a MEMBER at all, so a complaint about one
 * person in a household of nine was filed against the household and
 * whoever picked it up had to read the narrative to find out who. The
 * household screen's did offer the roster, but drew its categories and
 * tiers from its own copy of the vocabulary under different labels
 * ("Wrongly excluded" against "Exclusion error"), so the same
 * grievance read differently depending on which screen raised it.
 */

import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

let OpenGrievanceModal;

beforeAll(async () => {
  const React = await import("react").then(m => m.default || m);
  globalThis.React = React;
  globalThis.window = globalThis;
  globalThis.useState = React.useState;
  globalThis.useEffect = React.useEffect;
  globalThis.useRef = React.useRef;
  globalThis.useMemo = React.useMemo;
  await import("../../components.jsx");
  await import("../data/grm-vocabulary.jsx");
  await import("./search-picker.jsx");
  await import("./open-grievance.jsx");
  ({ OpenGrievanceModal } = globalThis);
});

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const ROSTER = [
  { id: "01MEM1", line_number: 1, first_name: "Grace", surname: "Akello" },
  { id: "01MEM2", line_number: 2, first_name: "Peter", surname: "Okot" },
];

const stubFetch = (impl) => {
  globalThis.fetch = vi.fn(impl);
  return globalThis.fetch;
};

const rosterFetch = (extra) => stubFetch((url, opts) => {
  if (String(url).includes("/members/")) {
    return Promise.resolve({ ok: true, json: () => Promise.resolve({ results: ROSTER }) });
  }
  return extra ? extra(url, opts) : Promise.reject(new Error(`unexpected ${url}`));
});

const HOUSEHOLD = { id: "01HH", label: "Nsubuga Ruth", sub: "Kanyantorogo · Kanungu" };

const showLocked = (props = {}) => render(
  <OpenGrievanceModal open household={HOUSEHOLD}
                      onClose={() => {}} onOpened={() => {}} {...props}/>,
);

describe("the dialog names a person, not just a household", () => {
  it("offers the household's roster", async () => {
    rosterFetch();
    showLocked();
    await waitFor(() => {
      expect(screen.getByText("Line 1 · Grace Akello")).toBeTruthy();
    });
    expect(screen.getByText("Line 2 · Peter Okot")).toBeTruthy();
  });

  it("defaults to the household as a whole", async () => {
    rosterFetch();
    showLocked();
    const select = await screen.findByLabelText?.("WHO IS IT ABOUT?").catch(() => null)
      || screen.getByText("— The household as a whole —").closest("select");
    expect(select.value).toBe("");
  });

  it("sends the chosen member with the grievance", async () => {
    let posted = null;
    const f = rosterFetch((url, opts) => {
      posted = JSON.parse(opts.body);
      return Promise.resolve({ status: 201, json: () => Promise.resolve({ id: "01G" }) });
    });
    showLocked();
    await waitFor(() => screen.getByText("Line 2 · Peter Okot"));

    fireEvent.change(
      screen.getByText("— The household as a whole —").closest("select"),
      { target: { value: "01MEM2" } },
    );
    fireEvent.change(screen.getByPlaceholderText(/Describe the grievance/), {
      target: { value: "Peter's date of birth is wrong on the roster." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Open grievance" }));

    await waitFor(() => expect(posted).not.toBeNull());
    expect(posted.member_id).toBe("01MEM2");
    expect(posted.household_id).toBe("01HH");
    expect(f).toHaveBeenCalled();
  });

  it("still allows a household-level grievance", async () => {
    let posted = null;
    rosterFetch((url, opts) => {
      posted = JSON.parse(opts.body);
      return Promise.resolve({ status: 201, json: () => Promise.resolve({ id: "01G" }) });
    });
    showLocked();
    await waitFor(() => screen.getByText("Line 1 · Grace Akello"));
    fireEvent.change(screen.getByPlaceholderText(/Describe the grievance/), {
      target: { value: "The household was left off the programme list." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Open grievance" }));
    await waitFor(() => expect(posted).not.toBeNull());
    expect(posted.member_id).toBe("");
  });
});

describe("one vocabulary", () => {
  it("offers the shared categories, not a second spelling", () => {
    rosterFetch();
    showLocked();
    const labels = [...screen.getByDisplayValue("Data correction").options]
      .map(o => o.textContent);
    expect(labels).toEqual(Object.values(globalThis.GRM_CATEGORIES));
  });

  it("offers every tier with its default SLA", () => {
    rosterFetch();
    showLocked();
    expect(screen.getByText("L1 — Parish Chief (24h SLA)")).toBeTruthy();
    expect(screen.getByText("L4 — NSR Unit (168h SLA)")).toBeTruthy();
  });
});

describe("the household question", () => {
  it("is not asked when the caller already knows it", () => {
    rosterFetch();
    showLocked();
    expect(screen.getByText(/raised from this record/)).toBeTruthy();
    expect(screen.queryByRole("radio")).toBeNull();
  });

  it("is asked, and unanswered, when it does not", () => {
    rosterFetch();
    render(<OpenGrievanceModal open onClose={() => {}} onOpened={() => {}}/>);
    const radios = screen.getAllByRole("radio");
    expect(radios).toHaveLength(2);
    expect(radios.every(r => !r.checked)).toBe(true);
  });

  it("refuses to submit while it is unanswered", async () => {
    const f = rosterFetch();
    render(<OpenGrievanceModal open onClose={() => {}} onOpened={() => {}}/>);
    fireEvent.change(screen.getByPlaceholderText(/Describe the grievance/), {
      target: { value: "Something happened at the parish office." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Open grievance" }));
    await waitFor(() => {
      expect(screen.getByText(/Say whether this is about a household/)).toBeTruthy();
    });
    expect(f).not.toHaveBeenCalled();
  });

  it("refuses to submit an empty narrative", async () => {
    const f = rosterFetch();
    showLocked();
    fireEvent.click(screen.getByRole("button", { name: "Open grievance" }));
    await waitFor(() => {
      expect(screen.getByText(/Describe the grievance —/)).toBeTruthy();
    });
    expect(f.mock.calls.filter(c => !String(c[0]).includes("/members/"))).toHaveLength(0);
  });
});

describe("what it does with the result", () => {
  it("hands the created grievance back to the caller", async () => {
    rosterFetch(() => Promise.resolve({
      status: 201, json: () => Promise.resolve({ id: "01NEWG" }),
    }));
    const onOpened = vi.fn();
    showLocked({ onOpened });
    fireEvent.change(screen.getByPlaceholderText(/Describe the grievance/), {
      target: { value: "A complaint that needs recording." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Open grievance" }));
    await waitFor(() => expect(onOpened).toHaveBeenCalledWith({ id: "01NEWG" }));
  });

  it("shows the server's refusal rather than swallowing it", async () => {
    rosterFetch(() => Promise.resolve({
      status: 400, json: () => Promise.resolve({ detail: "household_id does not exist" }),
    }));
    showLocked();
    fireEvent.change(screen.getByPlaceholderText(/Describe the grievance/), {
      target: { value: "A complaint that needs recording." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Open grievance" }));
    await waitFor(() => {
      expect(screen.getByText(/household_id does not exist/)).toBeTruthy();
    });
  });
});
