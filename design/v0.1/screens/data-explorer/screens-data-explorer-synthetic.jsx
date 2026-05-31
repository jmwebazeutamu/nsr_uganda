/* global React, ReactDOM,
   Icon, Chip, PageHeader,
   DE_DATASETS, DE_PRIVACY, DE_SYNTHETIC_ROWS,
   PrivacyChip, DEShell, ScreenJumpTweak,
   useDeCatalogue, useDeSynthetic, useDeMe, RoleGateBanner,
   TweaksPanel, useTweaks, TweakSection */

// NSR MIS — Data Explorer · Synthetic sample (screen 5 of 5)
// =========================================================
// Same column shape as a real result, banner-warned, tinted
// background. Rows are generated and DO NOT correspond to any
// real beneficiary. Used by analysts to learn the dataset shape
// before composing a real aggregate query.

const { useState: useSyn } = React;

// Columns are NOT hardcoded — they're derived from the rows the API
// returns (or, offline, from the mock rows). Display hints (mono / num
// / chip) are inferred from the key name + value type.
const _humanize = (k) => String(k).replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
const _deriveColumns = (rows) => {
  if (!Array.isArray(rows) || !rows.length) return [];
  return Object.keys(rows[0]).map(k => ({
    key: k,
    label: _humanize(k),
    num: typeof rows[0][k] === "number",
    mono: /(_id$|^id$|hash|^synth)/i.test(k),
    chip: /(band|class|status|tier)/i.test(k),
  }));
};

// Deep-link support: the Catalogue's "Synthetic sample" button lands
// here with ?dataset=<section/dataset id>.
const _datasetParam = () => {
  try {
    return new URLSearchParams(window.location.search).get("dataset") || "";
  } catch (e) {
    return "";
  }
};

const SyntheticScreen = () => {
  const [t, setTweak] = useTweaks({ screen: "synthetic" });
  const [datasetId, setDatasetId] = useSyn(() => _datasetParam() || "ds_hh_profile");
  const [requestedParam] = useSyn(_datasetParam);   // remembered deep-link target
  const [rowCount, setRowCount] = useSyn(10);
  const [seed, setSeed] = useSyn("ug-nsr-2026-05-28");

  const me = useDeMe();
  const [datasets] = useDeCatalogue();
  const list = (datasets && datasets.length) ? datasets : DE_DATASETS;
  // Never let ds be undefined. A deep-link to a questionnaire section
  // this screen can't render yet (the household-shaped sample is per
  // aggregate dataset — per-section samples are US-DATA-EXP-002) falls
  // back to the first serveable dataset instead of blanking the page.
  const ds = list.find(d => d.id === datasetId || d.code === datasetId)
    || list[0] || DE_DATASETS[0];
  const deepLinkMissing = !!requestedParam
    && !list.some(d => d.id === requestedParam || d.code === requestedParam);
  const [rows] = useDeSynthetic(ds?.id || ds?.code || datasetId);
  const visible = rows.slice(0, rowCount);
  const columns = _deriveColumns(rows);

  return (
    <DEShell active="synthetic" refreshed_at={ds?.refreshed_at}>
      <RoleGateBanner me={me}/>
      <PageHeader
        eyebrow="DATA EXPLORER · SYNTHETIC SAMPLE"
        title="Synthetic sample"
        sub={<>Sample rows that match the catalogue shape — useful for previewing column names, value distributions, and downstream parsing without touching real beneficiary data.</>}
        right={<>
          <button className="btn"><Icon name="refresh" size={14}/> Regenerate</button>
          <button className="btn"><Icon name="download" size={14}/> Export CSV</button>
        </>}
      />

      {deepLinkMissing && (
        <div style={{
          background:"var(--accent-update-bg)",
          border:"1px solid var(--accent-update)",
          borderRadius:6, padding:"10px 16px", marginBottom:16,
          display:"flex", alignItems:"center", gap:10, fontSize:12.5,
        }}>
          <Icon name="info" size={14} color="var(--accent-update)"/>
          <span style={{color:"var(--neutral-800)"}}>
            A synthetic sample for the <strong>{requestedParam}</strong> questionnaire
            section isn't available yet (tracked as US-DATA-EXP-002). Showing{" "}
            <strong>{ds.label}</strong> instead — pick another dataset below.
          </span>
        </div>
      )}

      {/* The big banner — required by spec */}
      <div style={{
        background:"var(--accent-danger-bg)",
        border:"1px solid var(--accent-danger)",
        borderLeft:"4px solid var(--accent-danger)",
        borderRadius:6,
        padding:"14px 18px",
        display:"flex", gap:14, alignItems:"center",
        marginBottom:16,
      }}>
        <div style={{
          width:40, height:40, borderRadius:"50%",
          background:"var(--accent-danger)", color:"#fff",
          display:"grid", placeItems:"center", flex:"0 0 auto",
        }}>
          <Icon name="alert" size={20}/>
        </div>
        <div style={{flex:1, minWidth:0}}>
          <div style={{fontWeight:700, color:"var(--accent-danger)", fontSize:14, marginBottom:2}}>
            Synthetic — not real beneficiaries
          </div>
          <div className="t-bodysm" style={{color:"var(--neutral-900)"}}>
            These rows were generated from the dataset's value distributions and may not be exported, shared, or treated as
            real data under any circumstance. Use them to preview column shape, value formats, and downstream parsing only.
          </div>
        </div>
        <span className="t-mono" style={{
          padding:"4px 10px", borderRadius:3,
          background:"var(--accent-danger)", color:"#fff",
          fontSize:11, fontWeight:600, letterSpacing:"0.04em",
          alignSelf:"flex-start",
        }}>SYNTHETIC</span>
      </div>

      {/* Selector strip */}
      <div className="card" style={{padding:"16px 20px", marginBottom:16,
        display:"grid", gridTemplateColumns:"1.5fr 1fr 1fr 1fr", gap:24, alignItems:"center"}}>
        <div>
          <div className="t-cap">DATASET</div>
          <div style={{display:"flex", alignItems:"center", gap:10, marginTop:4}}>
            <select className="field-select" style={{maxWidth:320}}
              value={ds.id} onChange={(e) => setDatasetId(e.target.value)}>
              {datasets.filter(d => d.privacy !== "sensitive").map(d =>
                <option key={d.id} value={d.id}>{d.code} — {d.label}</option>
              )}
            </select>
            <PrivacyChip klass={ds.privacy} size="sm"/>
          </div>
          <div className="t-cap mt-1">column shape mirrors the live dataset</div>
        </div>
        <div>
          <div className="t-cap">SAMPLE SIZE</div>
          <div style={{display:"flex", alignItems:"center", gap:8, marginTop:8}}>
            <input type="range" min={3} max={Math.max(3, rows.length)} step={1}
              value={rowCount} onChange={(e) => setRowCount(parseInt(e.target.value, 10))}
              style={{flex:1}}/>
            <span className="t-mono" style={{width:44, fontSize:13, fontWeight:600}}>{rowCount}</span>
          </div>
          <div className="t-cap mt-1">rows · capped at {rows.length}</div>
        </div>
        <div>
          <div className="t-cap">SEED</div>
          <input className="field-input" style={{marginTop:6}}
            value={seed} onChange={(e) => setSeed(e.target.value)}/>
          <div className="t-cap mt-1">deterministic — same seed produces same rows</div>
        </div>
        <div>
          <div className="t-cap">SOURCE</div>
          <div style={{display:"flex", alignItems:"center", gap:8, marginTop:6}}>
            <Icon name="database" size={14} color="var(--neutral-700)"/>
            <span className="t-mono" style={{fontSize:12}}>GET /synthetic-sample/{ds.id}/</span>
          </div>
          <div className="t-cap mt-1">distributions estimated from {ds.refreshed_at}</div>
        </div>
      </div>

      {/* Tinted sample table */}
      <div className="card" style={{padding:0, overflow:"hidden",
        outline:"1.5px solid var(--accent-danger)", outlineOffset:-1}}>
        <div className="card-toolbar" style={{background:"var(--accent-danger-bg)", borderBottom:"1px solid var(--accent-danger)"}}>
          <Icon name="alert" size={13} color="var(--accent-danger)"/>
          <strong className="t-bodysm" style={{color:"var(--accent-danger)"}}>Synthetic sample · {ds.code}</strong>
          <span className="t-cap" style={{color:"var(--accent-danger)"}}>{visible.length} fake rows</span>
          <div style={{flex:1}}/>
          <span className="t-cap" style={{color:"var(--accent-danger)"}}>seed: <span className="t-mono">{seed}</span></span>
        </div>

        <div style={{overflowX:"auto", background:"repeating-linear-gradient(45deg, #fff, #fff 14px, var(--accent-danger-bg) 14px, var(--accent-danger-bg) 15px)"}}>
          <table className="tbl" style={{minWidth:1000, background:"rgba(255,255,255,0.92)"}}>
            <thead>
              <tr>
                {columns.map(c => (
                  <th key={c.key} style={{textAlign: c.num ? "right" : "left"}}>{c.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visible.map((row, i) => (
                <tr key={i}>
                  {columns.map(c => {
                    const v = row[c.key];
                    return (
                      <td key={c.key} style={{
                        textAlign: c.num ? "right" : "left",
                        fontFamily: c.mono || c.num ? "'JetBrains Mono', monospace" : undefined,
                        fontSize: c.mono ? 12 : 13.5,
                      }}>
                        {c.chip ? <Chip size="sm" tone={
                          v === "Poorest 20%" ? "danger" :
                          v === "Poorest 40%" ? "quality" :
                          v === "Middle 40%" ? "update" : "data"
                        }>{v}</Chip> : v}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div style={{
          padding:"10px 20px",
          borderTop:"1px solid var(--accent-danger)",
          background:"var(--accent-danger-bg)",
          display:"flex", alignItems:"center", gap:14,
          fontSize:12, color:"var(--accent-danger)", fontWeight:500,
        }}>
          <Icon name="shield" size={12}/>
          <span>
            Every row is generated. Synthetic IDs use the <span className="t-mono">synth-NNNN</span> prefix so they can never be confused with the registry's <span className="t-mono">M-</span>/<span className="t-mono">01H…</span> identifiers.
          </span>
        </div>
      </div>

      {/* Distribution preview */}
      <div className="card" style={{marginTop:16, padding:0}}>
        <div className="card-toolbar">
          <strong className="t-bodysm">Column distributions</strong>
          <span className="t-cap">simulated from live matview</span>
          <div style={{flex:1}}/>
        </div>
        <div style={{padding:18, display:"grid", gridTemplateColumns:"repeat(3, 1fr)", gap:18}}>
          <DistCard label="hh_size" type="integer"
            bars={[{l:"1–3", v:0.18},{l:"4–6", v:0.42},{l:"7–9", v:0.28},{l:"10+", v:0.12}]}/>
          <DistCard label="roof_material" type="categorical"
            bars={[{l:"Iron sheets", v:0.62},{l:"Thatch / grass", v:0.28},{l:"Tiles", v:0.05},{l:"Concrete", v:0.03},{l:"Other", v:0.02}]}/>
          <DistCard label="water_source" type="categorical"
            bars={[{l:"Borehole < 1 km", v:0.51},{l:"Open well", v:0.18},{l:"Piped — public tap", v:0.14},{l:"River / pond", v:0.10},{l:"Other", v:0.07}]}/>
        </div>
      </div>

      <TweaksPanel title="Tweaks">
        <TweakSection label="Navigate">
          <ScreenJumpTweak active="synthetic"/>
        </TweakSection>
      </TweaksPanel>
    </DEShell>
  );
};

const DistCard = ({ label, type, bars }) => (
  <div style={{border:"1px solid var(--neutral-200)", borderRadius:4, padding:14}}>
    <div style={{display:"flex", alignItems:"center", gap:6, marginBottom:8}}>
      <span className="t-mono" style={{fontSize:12, fontWeight:600}}>{label}</span>
      <Chip size="sm" tone="neutral">{type}</Chip>
    </div>
    {bars.map(b => (
      <div key={b.l} style={{marginBottom:6}}>
        <div style={{display:"flex", justifyContent:"space-between", fontSize:12, marginBottom:2}}>
          <span>{b.l}</span>
          <span className="t-mono" style={{color:"var(--neutral-500)"}}>{(b.v * 100).toFixed(0)}%</span>
        </div>
        <div style={{height:6, background:"var(--neutral-100)", borderRadius:3, overflow:"hidden"}}>
          <div style={{width: `${b.v * 100}%`, height:"100%", background:"var(--primary-700)"}}/>
        </div>
      </div>
    ))}
  </div>
);

ReactDOM.createRoot(document.getElementById("app")).render(<SyntheticScreen/>);
