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
  // The `sex` codes come from the one ChoiceList that holds them, the
  // same way every other coded select in the console reads one.
  globalThis.useChoiceList = () => [
    [{ code: "1", label: "Male" }, { code: "2", label: "Female" }],
    { loading: false },
  ];
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

// Two reads the dialog makes on its own, answered here so a test only
// has to care about the POST. The limits come from the server because
// they are the blob store's — a copy in the dialog would be a second
// policy, free to disagree with the one that refuses.
const LIMITS = {
  max_files: 3,
  max_file_bytes: 5 * 1024 * 1024,
  max_total_bytes: 15 * 1024 * 1024,
  allowed_content_types: ["application/pdf", "image/jpeg", "image/png"],
};

const _isDialogRead = (url) => String(url).includes("/members/")
  || String(url).includes("attachment-limits");

const rosterFetch = (extra) => stubFetch((url, opts) => {
  if (String(url).includes("/members/")) {
    return Promise.resolve({ ok: true, json: () => Promise.resolve({ results: ROSTER }) });
  }
  if (String(url).includes("attachment-limits")) {
    return Promise.resolve({ ok: true, json: () => Promise.resolve(LIMITS) });
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
    fireEvent.click(screen.getByRole("button", { name: "Create grievance" }));

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
    fireEvent.click(screen.getByRole("button", { name: "Create grievance" }));
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
    fireEvent.click(screen.getByRole("button", { name: "Create grievance" }));
    await waitFor(() => {
      expect(screen.getByText(/Say whether this is about a household/)).toBeTruthy();
    });
    expect(f.mock.calls.filter(c => !_isDialogRead(c[0]))).toHaveLength(0);
  });

  it("refuses to submit an empty narrative", async () => {
    const f = rosterFetch();
    showLocked();
    fireEvent.click(screen.getByRole("button", { name: "Create grievance" }));
    await waitFor(() => {
      expect(screen.getByText(/Describe the grievance —/)).toBeTruthy();
    });
    expect(f.mock.calls.filter(c => !_isDialogRead(c[0]))).toHaveLength(0);
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
    fireEvent.click(screen.getByRole("button", { name: "Create grievance" }));
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
    fireEvent.click(screen.getByRole("button", { name: "Create grievance" }));
    await waitFor(() => {
      expect(screen.getByText(/household_id does not exist/)).toBeTruthy();
    });
  });
});

describe("who complained", () => {
  const fillAndSend = () => {
    fireEvent.change(screen.getByPlaceholderText(/Describe the grievance/), {
      target: { value: "Omitted from the posted list." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create grievance" }));
  };

  it("offers the sex codes from the ChoiceList, not its own pair", () => {
    rosterFetch();
    showLocked();
    const select = screen.getByLabelText("Reporter sex");
    const options = [...select.options].map(o => [o.value, o.textContent]);
    expect(options).toEqual([
      ["", "— Not stated —"], ["1", "Male"], ["2", "Female"],
    ]);
  });

  it("sends the code, not the label", async () => {
    let posted = null;
    rosterFetch((url, opts) => {
      posted = JSON.parse(opts.body);
      return Promise.resolve({ status: 201, json: () => Promise.resolve({ id: "01G" }) });
    });
    showLocked();
    fireEvent.change(screen.getByLabelText("Reporter sex"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Reporter age in years"), {
      target: { value: "64" },
    });
    fillAndSend();
    await waitFor(() => expect(posted).not.toBeNull());
    expect(posted.reporter_gender).toBe("2");
    expect(posted.reporter_age_years).toBe(64);
  });

  it("sends no age as null, never as nought", async () => {
    let posted = null;
    rosterFetch((url, opts) => {
      posted = JSON.parse(opts.body);
      return Promise.resolve({ status: 201, json: () => Promise.resolve({ id: "01G" }) });
    });
    showLocked();
    fillAndSend();
    await waitFor(() => expect(posted).not.toBeNull());
    // A complainant who did not say their age is not a newborn, and an
    // unanswered question must not be counted as an answer.
    expect(posted.reporter_age_years).toBeNull();
    expect(posted.reporter_gender).toBe("");
  });
});

describe("the evidence", () => {
  const pdf = (name = "list.pdf", bytes = "the posted list") =>
    new File([bytes], name, { type: "application/pdf" });

  it("states the limits the server gave it, not its own", async () => {
    rosterFetch();
    showLocked();
    // 3 and 5 MB are the blob store's numbers, fetched. A copy in the
    // dialog would be a second policy free to disagree with the one
    // that actually refuses.
    await waitFor(() => {
      expect(screen.getByText(/Up to 3, 5 MB each/)).toBeTruthy();
    });
  });

  it("sends the chosen file with the case, in one request", async () => {
    let posted = null;
    rosterFetch((url, opts) => {
      posted = JSON.parse(opts.body);
      return Promise.resolve({ status: 201, json: () => Promise.resolve({ id: "01G" }) });
    });
    showLocked();
    fireEvent.change(screen.getByTestId("og-file-input"), {
      target: { files: [pdf()] },
    });
    await waitFor(() => expect(screen.getByText("list.pdf")).toBeTruthy());
    fireEvent.change(screen.getByPlaceholderText(/Describe the grievance/), {
      target: { value: "Omitted from the posted list." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create grievance" }));
    await waitFor(() => expect(posted).not.toBeNull());
    expect(posted.documents).toHaveLength(1);
    expect(posted.documents[0].filename).toBe("list.pdf");
    expect(posted.documents[0].content_type).toBe("application/pdf");
    // base64 of the bytes, not the bytes and not a data: URL — the
    // server decodes exactly this.
    expect(posted.documents[0].data_base64)
      .toBe(Buffer.from("the posted list").toString("base64"));
  });

  it("lets a file be taken back off before sending", async () => {
    rosterFetch();
    showLocked();
    fireEvent.change(screen.getByTestId("og-file-input"), {
      target: { files: [pdf()] },
    });
    await waitFor(() => expect(screen.getByText("list.pdf")).toBeTruthy());
    fireEvent.click(screen.getByLabelText("Remove list.pdf"));
    await waitFor(() => expect(screen.queryByText("list.pdf")).toBeNull());
  });

  it("does not list the same file twice", async () => {
    rosterFetch();
    showLocked();
    const input = screen.getByTestId("og-file-input");
    fireEvent.change(input, { target: { files: [pdf()] } });
    await waitFor(() => expect(screen.getByText("list.pdf")).toBeTruthy());
    fireEvent.change(input, { target: { files: [pdf()] } });
    await waitFor(() => {
      expect(screen.getAllByText("list.pdf")).toHaveLength(1);
    });
  });

  it("sends no documents key content when none were chosen", async () => {
    let posted = null;
    rosterFetch((url, opts) => {
      posted = JSON.parse(opts.body);
      return Promise.resolve({ status: 201, json: () => Promise.resolve({ id: "01G" }) });
    });
    showLocked();
    fireEvent.change(screen.getByPlaceholderText(/Describe the grievance/), {
      target: { value: "Omitted from the posted list." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create grievance" }));
    await waitFor(() => expect(posted).not.toBeNull());
    expect(posted.documents).toEqual([]);
  });

  it("clears what was chosen when the dialog is reopened", async () => {
    rosterFetch();
    // Closed and reopened on the SAME mounted dialog, which is how the
    // workbench uses it — a fresh mount would have fresh state whether
    // the reset existed or not, and would prove nothing.
    const { rerender } = render(
      <OpenGrievanceModal open household={HOUSEHOLD}
                          onClose={() => {}} onOpened={() => {}}/>,
    );
    fireEvent.change(screen.getByTestId("og-file-input"), {
      target: { files: [pdf()] },
    });
    await waitFor(() => expect(screen.getByText("list.pdf")).toBeTruthy());
    rerender(
      <OpenGrievanceModal open={false} household={HOUSEHOLD}
                          onClose={() => {}} onOpened={() => {}}/>,
    );
    rerender(
      <OpenGrievanceModal open household={HOUSEHOLD}
                          onClose={() => {}} onOpened={() => {}}/>,
    );
    // A document attached to the last complaint must not ride along on
    // the next one.
    await waitFor(() => expect(screen.queryByText("list.pdf")).toBeNull());
  });
});
