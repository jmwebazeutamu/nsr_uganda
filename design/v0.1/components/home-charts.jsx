/* global React, Icon */
// Home-screen chart band (US-S24-HOME-CHARTS)
// =====================================================
// Five aggregate series on the operator console home screen, serving
// two readers at once: the NSR Unit Coordinator orienting themselves
// during the week, and whoever they print or screenshot it for.
//
// Form
// ----
// Every chart here is a horizontal bar list, because every one of them
// asks the same question — compare magnitude across a handful of
// long-named categories. Vertical columns would turn "AC-MANDATORY-
// MEMBER-NAME" into a rotated label nobody reads.
//
// Colour carries MAGNITUDE ONLY; it never distinguishes one bar from
// another. The module accent tokens are a categorical palette for chips
// and borders and are not usable as series colours — validated, not
// assumed: --accent-data against --accent-quality is ΔE 3.8 under
// protanopia, less than half the ΔE 8 floor, so two such bars are the
// same bar to a protanopic reader. Identity is the visible label beside
// every bar instead, which also means the chart survives being
// photocopied.
//
// The PMT band charts are the one exception, and are still single-hue:
// their bands are an ORDERED scale, so they use the --chart-seq-* ramp
// (light → dark, more deprived = darker). That encodes the order rather
// than inventing identities.
//
// Zero vs unknown
// ---------------
// These must never look alike. A bar of length zero says "we counted,
// and it is none"; a chart that could not load says so in words. The
// home screen's rule since the fabricated-KPI cleanup is that a number
// the API did not supply renders as an em dash, never a plausible
// stand-in, and it holds here.

const { useState: useStateHC, useEffect: useEffectHC } = React;

//: The sequential ramp, darkest first. Only for ordered scales.
const CHART_SEQ = [
  "var(--chart-seq-1)", "var(--chart-seq-2)",
  "var(--chart-seq-3)", "var(--chart-seq-4)",
];

const _num = (n) => (typeof n === "number" ? n.toLocaleString() : "—");

/** One horizontal bar list.
 *
 *  `rows` is [{key, label, count}]. `ramp` true uses the sequential
 *  ramp by position (ordered scales only); otherwise every bar is the
 *  same hue and length is the whole encoding.
 */
const HomeBarChart = ({ rows, ramp = false, emptyText = "Nothing to show." }) => {
  if (!rows || rows.length === 0) {
    return <div className="t-bodysm muted" style={{ padding: "18px 0" }}>{emptyText}</div>;
  }
  // Scale to the largest bar, not to a round number: these are counts
  // with no meaningful ceiling, and padding the axis to 1,000 would make
  // a registry of 288 households look empty.
  const max = Math.max(...rows.map(r => r.count || 0), 1);
  return (
    <div>
      {rows.map((row, i) => {
        const count = row.count || 0;
        // A non-zero bar keeps a visible stub so "one household" cannot
        // render as the same nothing as "no households".
        const pct = count ? Math.max((count / max) * 100, 2) : 0;
        const fill = ramp ? CHART_SEQ[Math.min(i, CHART_SEQ.length - 1)] : "var(--chart-bar)";
        return (
          <div className="chart-row" key={row.key || row.label || i}>
            <div className="chart-row-label" title={row.label}>{row.label}</div>
            {/* Decorative: the row already reads as "<label> <count>"
                to a screen reader, which is the table view. */}
            <div className="chart-bar-track" aria-hidden="true">
              <div className="chart-bar-fill" style={{ width: `${pct}%`, background: fill }}/>
            </div>
            <div className="chart-row-value t-mono">{_num(row.count)}</div>
          </div>
        );
      })}
    </div>
  );
};

/** A titled card around one chart.
 *
 *  `scopeNote` is not decoration. This screen gets printed and handed
 *  to people, and a chart covering one sub-region that reads as
 *  national is wrong in a way the reader cannot detect. Every card
 *  states the scope it is showing.
 */
const HomeChartCard = ({ title, sub, scopeNote, state, children }) => (
  <div className="card">
    <div className="card-header" style={{ padding: "12px 16px", alignItems: "flex-start" }}>
      <div>
        <h3 className="t-h3" style={{ margin: 0 }}>{title}</h3>
        {sub && <div className="t-cap">{sub}</div>}
      </div>
      {scopeNote && <span className="t-cap" style={{ whiteSpace: "nowrap" }}>{scopeNote}</span>}
    </div>
    <div style={{ padding: "4px 16px 16px" }}>
      {state === "loading" && (
        <div className="t-bodysm muted" style={{ padding: "18px 0" }}>Loading…</div>
      )}
      {state === "error" && (
        <div className="t-bodysm" style={{ padding: "18px 0", color: "var(--accent-danger)" }}>
          <Icon name="alert" size={13}/> Could not load — not shown rather than shown wrong.
        </div>
      )}
      {state === "ready" && children}
    </div>
  </div>
);

/** Fetch the five series in one round-trip, following the drill-down. */
const useHomeCharts = (region) => {
  const [data, setData] = useStateHC(null);
  const [state, setState] = useStateHC("loading");

  useEffectHC(() => {
    let cancelled = false;
    setState("loading");
    const qs = region ? `?region=${encodeURIComponent(region)}` : "";
    fetch(`/api/v1/rpt/dashboards/home-charts/${qs}`, { credentials: "same-origin" })
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(payload => {
        if (cancelled) return;
        setData(payload);
        setState("ready");
      })
      .catch(() => {
        if (cancelled) return;
        // Deliberately no fallback series. An invented chart on an
        // operator surface is a decision made about households that
        // were never counted.
        setData(null);
        setState("error");
      });
    return () => { cancelled = true; };
  }, [region]);

  return [data, state];
};

const HomeChartBand = ({ region, regionLabel }) => {
  const [data, state] = useHomeCharts(region);
  const scopeNote = region ? (regionLabel || region) : "All regions in scope";
  const series = (name) => (data && data[name]) || [];

  return (
    <div className="mt-5">
      <div className="row gap-2" style={{ marginBottom: 12, alignItems: "baseline" }}>
        <h2 className="t-h3" style={{ margin: 0 }}>Registry at a glance</h2>
        <span className="t-cap">
          {state === "ready"
            ? `live · ${scopeNote}`
            : state === "error" ? "could not load" : "loading…"}
        </span>
      </div>

      <div className="grid grid-2" style={{ gap: 20 }}>
        <HomeChartCard
          title="Households by PMT band"
          sub="Scored households only"
          scopeNote={scopeNote} state={state}>
          <HomeBarChart rows={series("households_by_pmt_band")} ramp
            emptyText="No households have been scored in this scope."/>
        </HomeChartCard>

        <HomeChartCard
          title="Members by PMT band"
          sub="People, counted by their household's band"
          scopeNote={scopeNote} state={state}>
          <HomeBarChart rows={series("members_by_pmt_band")} ramp
            emptyText="No scored households in this scope."/>
        </HomeChartCard>

        <HomeChartCard
          title="Records held before promotion"
          sub="What is holding each one"
          scopeNote={scopeNote} state={state}>
          <HomeBarChart rows={series("dih_backlog_by_reason")}
            emptyText="Nothing is held."/>
        </HomeChartCard>

        <HomeChartCard
          title="DQA findings by rule"
          sub="Failures raised in the last 30 days — a count, not a failure rate"
          scopeNote={scopeNote} state={state}>
          <HomeBarChart rows={series("dqa_failures_by_rule")}
            emptyText="No DQA failures recorded in this window."/>
        </HomeChartCard>

        <HomeChartCard
          title="Households enrolled, by programme"
          sub="Active enrolments. Enrolment is per household, not per person."
          scopeNote={scopeNote} state={state}>
          <HomeBarChart rows={series("enrolments_by_programme")}
            emptyText="No active enrolments in this scope."/>
        </HomeChartCard>
      </div>
    </div>
  );
};

Object.assign(window, { HomeChartBand, HomeBarChart, HomeChartCard, useHomeCharts, CHART_SEQ });
