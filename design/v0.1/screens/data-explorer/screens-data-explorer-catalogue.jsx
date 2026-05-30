/* global React, ReactDOM,
   Icon, Chip, PageHeader,
   DE_DATASETS, DE_VARIABLES_BY_DATASET, DE_PRIVACY, DE_PRIVACY_ORDER,
   PrivacyChip, DEShell, ScreenJumpTweak,
   useDePublicCatalogue, useDeMe, RoleGateBanner,
   TweaksPanel, useTweaks, TweakSection */

// NSR MIS — Data Explorer · Catalogue browse (screen 1 of 5)
// =========================================================
// Left rail: datasets grouped by privacy class. Right pane:
// the selected dataset's variable list with class chips per row.
// Search box filters across both panes.

const { useState: useCat, useMemo: useCatM } = React;

// Rail grouping for the transparency catalogue — by questionnaire
// entity. "Roster member" collects every member-level section.
const ENTITY_GROUPS = [
  { key: "household", label: "Household", icon: "home" },
  { key: "member", label: "Roster member", icon: "users" },
];

const CatalogueScreen = () => {
  const [t, setTweak] = useTweaks({ screen: "catalogue" });
  const [q, setQ] = useCat("");
  const [activePrivacy, setActivePrivacy] = useCat("");
  const [activeId, setActiveId] = useCat("ds_hh_profile");

  const me = useDeMe();
  // Browse is the transparency dictionary: always the full questionnaire
  // (all sections + fields), for everyone — not the gated aggregate
  // slices. Aggregatable fields are flagged for the Builder.
  const [datasets, dsMeta, varsBySection] = useDePublicCatalogue();
  const liveVars = varsBySection[activeId] || [];

  // Keep a valid selection: the hardcoded default id won't match the
  // section keys, so snap to the first available once the catalogue
  // resolves.
  React.useEffect(() => {
    if (datasets.length && !datasets.some(d => d.id === activeId || d.code === activeId)) {
      setActiveId(datasets[0].id);
    }
  }, [datasets]);

  const filteredDs = useCatM(() => datasets.filter(d => {
    if (activePrivacy && d.privacy !== activePrivacy) return false;
    if (!q) return true;
    const needle = q.toLowerCase();
    return d.code.toLowerCase().includes(needle)
      || d.label.toLowerCase().includes(needle)
      || (d.desc || "").toLowerCase().includes(needle);
  }), [q, activePrivacy, datasets]);

  // Group the rail by questionnaire entity so the roster's sections
  // (member, health, disability, education, employment) sit together
  // instead of scattering across privacy buckets.
  const grouped = useCatM(() => {
    const g = Object.fromEntries(ENTITY_GROUPS.map(grp => [grp.key, []]));
    filteredDs.forEach(d => {
      const key = g[d.entity] ? d.entity : ENTITY_GROUPS[0].key;
      g[key].push(d);
    });
    return g;
  }, [filteredDs]);

  const ds = datasets.find(d => d.id === activeId || d.code === activeId);
  const vars = useCatM(() => {
    const list = liveVars && liveVars.length ? liveVars : (DE_VARIABLES_BY_DATASET[activeId] || []);
    if (!q) return list;
    const n = q.toLowerCase();
    return list.filter(v =>
      v.code.toLowerCase().includes(n) || (v.label || "").toLowerCase().includes(n)
      || (v.domain || "").toLowerCase().includes(n));
  }, [activeId, q, liveVars]);

  const totals = useCatM(() => {
    const c = { public:0, internal:0, personal:0, sensitive:0 };
    datasets.forEach(d => { if (c[d.privacy] !== undefined) c[d.privacy]++; });
    return c;
  }, [datasets]);

  return (
    <DEShell active="catalogue" refreshed_at={ds?.refreshed_at || "28 May 2026 06:00 UTC"}
             publicLive={dsMeta.isPublic}>
      {dsMeta.isPublic ? <PublicCatalogueBanner/> : <RoleGateBanner me={me}/>}
      <PageHeader
        eyebrow="DATA EXPLORER · CATALOGUE BROWSE"
        title="Browse datasets & variables"
        sub={<>The full questionnaire data dictionary — every field the registry captures, with its privacy class on each row. Aggregatable fields preview in the builder; record-level access happens in the DRS console.</>}
        right={<>
          <button className="btn"><Icon name="download" size={14}/> Export catalogue</button>
          <button className="btn btn-primary" onClick={() => location.href="Data Explorer - Aggregate Builder.html"}>
            <Icon name="sliders" size={14}/> Build an aggregate
          </button>
        </>}
      />

      {/* Search + privacy filter strip */}
      <div className="card" style={{padding:"12px 16px", marginBottom:16,
        display:"grid", gridTemplateColumns:"1fr auto auto", gap:12, alignItems:"center"}}>
        <div className="search" style={{maxWidth:"none", margin:0}}>
          <Icon name="search" size={14} color="var(--neutral-500)"/>
          <input value={q} onChange={(e) => setQ(e.target.value)}
            placeholder="Search datasets, variables, codes, domains…"/>
          {q && <button className="icon-btn" onClick={() => setQ("")}><Icon name="x" size={12}/></button>}
        </div>
        <div style={{display:"flex", alignItems:"center", gap:6}}>
          <span className="t-cap" style={{marginRight:6}}>PRIVACY:</span>
          <button className={`cat-filter-btn ${activePrivacy === "" ? "on" : ""}`}
            onClick={() => setActivePrivacy("")}>All <span className="t-cap">{datasets.length}</span></button>
          {DE_PRIVACY_ORDER.map(k => (
            <button key={k}
              className={`cat-filter-btn ${activePrivacy === k ? "on" : ""}`}
              style={activePrivacy === k ? { background: DE_PRIVACY[k].bg, borderColor: DE_PRIVACY[k].accent, color: DE_PRIVACY[k].accent } : undefined}
              onClick={() => setActivePrivacy(activePrivacy === k ? "" : k)}>
              <span style={{width:6, height:6, borderRadius:"50%", background: DE_PRIVACY[k].accent}}/>
              {DE_PRIVACY[k].label.toLowerCase()}
              <span className="t-cap">{totals[k]}</span>
            </button>
          ))}
        </div>
        <span className="t-cap">{filteredDs.length} of {datasets.length} datasets</span>
      </div>

      {/* Main: rail + variable pane */}
      <div style={{display:"grid", gridTemplateColumns:"380px minmax(0, 1fr)", gap:16, alignItems:"flex-start"}}>
        {/* Left rail — datasets grouped by privacy */}
        <div className="card" style={{padding:0, position:"sticky", top:120, maxHeight:"calc(100vh - 140px)", overflowY:"auto"}}>
          <div className="card-toolbar">
            <strong className="t-bodysm">Questionnaire sections</strong>
            <div style={{flex:1}}/>
            <span className="t-cap">grouped by section</span>
          </div>
          {ENTITY_GROUPS.map(grp => {
            const list = grouped[grp.key] || [];
            if (!list.length) return null;
            const fieldTotal = list.reduce((n, d) => n + (Number(d.variables) || 0), 0);
            return (
              <div key={grp.key}>
                <div style={{
                  padding:"8px 14px",
                  display:"flex", alignItems:"center", gap:8,
                  background:"var(--neutral-50)",
                  borderTop:"1px solid var(--neutral-200)",
                  borderBottom:"1px solid var(--neutral-200)",
                }}>
                  <Icon name={grp.icon} size={13} color="var(--neutral-600)"/>
                  <strong className="t-cap" style={{color:"var(--neutral-800)", fontWeight:600, letterSpacing:"0.04em"}}>{grp.label.toUpperCase()}</strong>
                  <div style={{flex:1}}/>
                  <span className="t-cap">{list.length} sections · {fieldTotal} fields</span>
                </div>
                {list.map(d => {
                  const isActive = d.id === activeId;
                  const accent = (DE_PRIVACY[d.privacy] || {}).accent || "var(--primary-700)";
                  return (
                    <button key={d.id} onClick={() => setActiveId(d.id)} style={{
                      display:"block", width:"100%", textAlign:"left",
                      padding:"12px 14px",
                      border:0, borderBottom:"1px solid var(--neutral-200)",
                      background: isActive ? "var(--primary-100)" : "transparent",
                      cursor:"pointer",
                      borderLeft: isActive ? `3px solid ${accent}` : "3px solid transparent",
                    }}>
                      <div style={{display:"flex", alignItems:"center", gap:8, marginBottom:4}}>
                        <span className="t-mono" style={{fontSize:11.5, color:"var(--neutral-700)"}}>{d.code}</span>
                        {d.featured && <Chip size="sm" tone="data">featured</Chip>}
                        <div style={{flex:1}}/>
                        <PrivacyChip klass={d.privacy} size="sm"/>
                      </div>
                      <div style={{fontWeight:500, fontSize:13.5, color:"var(--neutral-900)"}}>{d.label}</div>
                      <div className="t-cap mt-1">{d.variables} fields</div>
                    </button>
                  );
                })}
              </div>
            );
          })}
          {filteredDs.length === 0 && (
            <div style={{padding:30, textAlign:"center"}} className="t-cap">No datasets match.</div>
          )}
        </div>

        {/* Right pane — selected dataset detail */}
        <div>
          {ds && <DatasetDetail ds={ds} vars={vars} searchActive={!!q}/>}
        </div>
      </div>

      <TweaksPanel title="Tweaks">
        <TweakSection label="Navigate">
          <ScreenJumpTweak active="catalogue"/>
        </TweakSection>
      </TweaksPanel>

      <style>{`
        .cat-filter-btn {
          display: inline-flex; align-items: center; gap: 6px;
          height: 28px; padding: 0 10px;
          border: 1px solid var(--neutral-300);
          border-radius: 14px;
          background: var(--neutral-0);
          color: var(--neutral-700);
          font-size: 12.5px; font-weight: 500;
          cursor: pointer;
        }
        .cat-filter-btn.on:not([style*="background"]) {
          background: var(--neutral-900); color: #fff; border-color: var(--neutral-900);
        }
        .cat-filter-btn .t-cap { color: inherit; opacity: 0.7; }
        .cat-filter-btn:hover { border-color: var(--neutral-500); }
      `}</style>
    </DEShell>
  );
};

/* ================================================================
   Right pane — dataset header + variable list
   ================================================================ */
const DatasetDetail = ({ ds, vars, searchActive }) => {
  const cfg = DE_PRIVACY[ds.privacy];

  // Group variables by domain
  const domains = {};
  vars.forEach(v => { (domains[v.domain] = domains[v.domain] || []).push(v); });
  const domainKeys = Object.keys(domains);

  // A questionnaire section (transparency catalogue) has no matview /
  // rows / refresh — those are aggregate-dataset concepts. Show
  // questionnaire-relevant facts instead of dead dashes.
  const isQuestionnaire = !!ds._public;
  const entityLabel = ds.entity === "member" ? "Roster member" : "Household";
  const aggCount = vars.filter(v => v.aggregatable).length;

  return (
    <>
      {/* Header card */}
      <div className="card" style={{padding:0, marginBottom:16, borderTop: `3px solid ${cfg.accent}`}}>
        <div style={{padding:"18px 22px", borderBottom:"1px solid var(--neutral-200)"}}>
          <div style={{display:"flex", alignItems:"flex-start", gap:14}}>
            <div style={{flex:1, minWidth:0}}>
              <div style={{display:"flex", alignItems:"center", gap:8, marginBottom:4}}>
                <span className="t-mono" style={{fontSize:12, color:"var(--neutral-700)"}}>{ds.code}</span>
                <PrivacyChip klass={ds.privacy} showFloor/>
                <Chip size="sm" tone="neutral">{ds.refresh}</Chip>
              </div>
              <h2 className="t-h2" style={{margin:0}}>{ds.label}</h2>
              <div className="t-bodysm muted mt-1">{ds.desc}</div>
            </div>
            <button className="btn btn-primary" onClick={() => location.href="Data Explorer - Aggregate Builder.html"}>
              <Icon name="sliders" size={14}/> Use in builder
            </button>
            <button className="btn"
              onClick={() => location.href=`Data Explorer - Synthetic Sample.html?dataset=${encodeURIComponent(ds.id)}`}>
              <Icon name="database" size={14}/> Synthetic sample
            </button>
          </div>
          {isQuestionnaire ? (
            <div style={{display:"grid", gridTemplateColumns:"repeat(4, 1fr)", gap:16, marginTop:18}}>
              <Fact label="Fields" big={ds.variables}/>
              <Fact label="Captured on" big={entityLabel}/>
              <Fact label="Questionnaire" big={ds.questionnaire_section
                ? <>Section <span className="t-mono">{ds.questionnaire_section}</span></>
                : "—"}/>
              <Fact label="Aggregatable" big={<>{aggCount} <span className="t-cap">of {ds.variables}</span></>}/>
            </div>
          ) : (
            <div style={{display:"grid", gridTemplateColumns:"repeat(5, 1fr)", gap:16, marginTop:18}}>
              <Fact label="Rows" big={ds.rows}/>
              <Fact label="Variables" big={ds.variables}/>
              <Fact label="Matview" big={<span className="t-mono" style={{fontSize:13}}>{ds.matview}</span>}/>
              <Fact label="Refresh cadence" big={ds.refresh}/>
              <Fact label="Refreshed" big={<span className="t-mono" style={{fontSize:12}}>{ds.refreshed_at}</span>}/>
            </div>
          )}
        </div>

        {/* Privacy rules card */}
        <div style={{padding:"14px 22px", background: cfg.bg, borderTop:`1px solid ${cfg.accent}`,
          display:"grid", gridTemplateColumns:"auto 1fr auto", gap:14, alignItems:"center"}}>
          <div style={{
            width:36, height:36, borderRadius:6,
            background: cfg.accent, color:"#fff",
            display:"grid", placeItems:"center",
          }}>
            <Icon name={cfg.icon || "shield"} size={18}/>
          </div>
          <div>
            <div style={{fontWeight:600, color: cfg.accent, fontSize:13.5}}>{cfg.label} privacy class</div>
            <div className="t-bodysm" style={{color:"var(--neutral-700)", marginTop:2}}>
              {cfg.blurb}
              {cfg.daily_cap && <> Daily caps: <strong>{cfg.daily_cap.user}/user · {cfg.daily_cap.org}/org</strong>.</>}
            </div>
          </div>
          <div className="t-cap" style={{color: cfg.accent, fontWeight:600}}>
            k_floor {cfg.k_floor ?? "—"} · floor {cfg.geo_floor}
          </div>
        </div>
      </div>

      {/* Variables list */}
      <div className="card" style={{padding:0}}>
        <div className="card-toolbar">
          <strong className="t-bodysm">Variables</strong>
          <span className="t-cap">{vars.length} {searchActive ? "match search" : "variables"}</span>
          <div style={{flex:1}}/>
          <span className="t-cap">grouped by domain</span>
        </div>

        {ds.privacy === "sensitive" && (
          <div style={{padding:"12px 18px", background:"var(--accent-danger-bg)",
            display:"flex", alignItems:"center", gap:10,
            borderBottom:"1px solid var(--accent-danger)"}}>
            <Icon name="lock" size={14} color="var(--accent-danger)"/>
            <span className="t-bodysm" style={{color:"var(--accent-danger)"}}>
              <strong>Aggregate blocked — record-level only.</strong>
              {" "}This dataset can be accessed through the DRS request workflow under an active DSA.
            </span>
            <div style={{flex:1}}/>
            <button className="btn btn-danger">
              <Icon name="arrowRight" size={13}/> Open DRS draft
            </button>
          </div>
        )}

        {domainKeys.length === 0 && (
          <div style={{padding:40, textAlign:"center"}} className="t-cap">No variables match.</div>
        )}

        {domainKeys.map(dom => (
          <div key={dom}>
            <div style={{
              padding:"8px 18px",
              background:"var(--neutral-50)",
              borderBottom:"1px solid var(--neutral-200)",
              borderTop:"1px solid var(--neutral-200)",
              display:"flex", alignItems:"center", gap:8,
            }}>
              <strong className="t-cap" style={{color:"var(--neutral-700)", fontWeight:600, letterSpacing:"0.06em"}}>
                {dom.toUpperCase()}
              </strong>
              <span className="t-cap">{domains[dom].length}</span>
            </div>
            {domains[dom].map(v => <VariableRow key={v.code} v={v}/>)}
          </div>
        ))}
      </div>
    </>
  );
};

/* Shown when the screen is rendering the live, anonymous public
   questionnaire catalogue (metadata only) rather than the EXPLORER-gated
   aggregate datasets. Frames the transparency purpose + the route to
   actual access. */
const PublicCatalogueBanner = () => (
  <div style={{
    background: "var(--accent-update-bg)",
    borderBottom: "1px solid var(--accent-update)",
    padding: "8px 24px",
    display: "flex", alignItems: "center", gap: 10, fontSize: 12.5,
  }}>
    <Icon name="info" size={14} color="var(--accent-update)"/>
    <strong style={{color: "var(--accent-update)"}}>Public catalogue.</strong>
    <span style={{color: "var(--neutral-700)"}}>
      The full questionnaire data dictionary — every field the National
      Social Registry captures, with its privacy class. It holds no
      household records or counts. Aggregatable fields can be queried in
      the Aggregate Builder; record-level data is granted only under a
      Data Sharing Agreement.
    </span>
  </div>
);

const Fact = ({ label, big }) => (
  <div>
    <div className="t-cap">{label.toUpperCase()}</div>
    <div style={{fontWeight:600, fontSize:15, marginTop:2}}>{big}</div>
  </div>
);

const VariableRow = ({ v }) => {
  const isSensitive = v.privacy === "sensitive";
  return (
    <div style={{
      display:"grid",
      gridTemplateColumns:"minmax(180px, 1.3fr) 90px minmax(160px, 1.4fr) minmax(140px, 1fr) auto",
      gap:14, alignItems:"center",
      padding:"12px 18px",
      borderBottom:"1px solid var(--neutral-200)",
      background: isSensitive ? "var(--accent-danger-bg)" : undefined,
    }}>
      <div style={{minWidth:0}}>
        <div style={{display:"flex", alignItems:"center", gap:6}}>
          {isSensitive && <Icon name="lock" size={12} color="var(--accent-danger)"/>}
          <span style={{fontWeight:500, fontSize:13.5, color:"var(--neutral-900)"}}>{v.label}</span>
        </div>
        <div className="t-cap t-mono mt-1">{v.code}</div>
      </div>
      <div>
        <Chip size="sm" tone="neutral">{v.type}</Chip>
      </div>
      <div className="t-bodysm" style={{color:"var(--neutral-700)"}}>
        {v.desc}
        {isSensitive && (
          <div className="t-cap mt-1" style={{color:"var(--accent-danger)", fontWeight:500}}>
            Aggregate blocked — record-level only
          </div>
        )}
      </div>
      <div className="t-cap" style={{fontSize:11.5}}>{v.values}</div>
      <div>
        <PrivacyChip klass={v.privacy} size="sm"/>
      </div>
    </div>
  );
};

ReactDOM.createRoot(document.getElementById("app")).render(<CatalogueScreen/>);
