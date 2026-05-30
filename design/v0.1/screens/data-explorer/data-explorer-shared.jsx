/* global React, Icon, Chip, PageHeader */
// NSR MIS — Data Explorer (US-DATA-EXP-001) shared module
// =========================================================
// Catalogue data, privacy-class taxonomy, geographic frame,
// suppression vocabulary, top-tab shell. Loaded by every
// Data Explorer screen HTML before the screen-specific JSX.

/* ================================================================
   Privacy classes — sourced from /privacy-classes/ in production.
   k_floor, geo floor, and badge tone come from ADR-0023 §D6.
   ================================================================ */
const DE_PRIVACY = {
  public: {
    code: "public",
    label: "Public",
    k_floor: 0,
    geo_floor: "sub-county",
    daily_cap: null,
    tone: "data",         // green
    accent: "var(--accent-data)",
    bg: "var(--accent-data-bg)",
    badge: "aggregate-ok",
    blurb: "No suppression. Fine to share externally.",
  },
  internal: {
    code: "internal",
    label: "Internal",
    k_floor: 5,
    geo_floor: "sub-county",
    daily_cap: { user: 100, org: 5000 },
    tone: "update",        // blue
    accent: "var(--accent-update)",
    bg: "var(--accent-update-bg)",
    badge: "aggregate-ok",
    blurb: "Suppress cells under k=5. NSR-internal use only.",
  },
  personal: {
    code: "personal",
    label: "Personal",
    k_floor: 10,
    geo_floor: "sub-region",
    daily_cap: { user: 25, org: 500 },
    tone: "quality",       // amber
    accent: "var(--accent-quality)",
    bg: "var(--accent-quality-bg)",
    badge: "aggregate-ok",
    blurb: "Suppress cells under k=10. Aggregate not finer than sub-region.",
  },
  sensitive: {
    code: "sensitive",
    label: "Sensitive",
    k_floor: null,
    geo_floor: "aggregate blocked",
    daily_cap: null,
    tone: "danger",        // red
    accent: "var(--accent-danger)",
    bg: "var(--accent-danger-bg)",
    badge: "aggregate-blocked",
    blurb: "Aggregate blocked — record-level only via DRS.",
    icon: "lock",
  },
};

const DE_PRIVACY_ORDER = ["public", "internal", "personal", "sensitive"];

/* ================================================================
   Datasets catalogue — household-context sample matching the
   registry seed (Nsubuga Ruth's household lives in HH_PROFILE).
   ================================================================ */
const DE_DATASETS = [
  {
    id: "ds_hh_roster_pub",
    code: "ROSTER_PUB",
    label: "Household roster — public summary",
    privacy: "public",
    floor: "sub-county",
    refresh: "Daily",
    refreshed_at: "28 May 2026 06:00 UTC",
    matview: "mv_de_roster_pub_v3",
    rows: "12.1M",
    variables: 8,
    desc: "Roster size and sex/age composition by area. No identifiers, no housing details.",
    domains: ["Roster", "Identification"],
  },
  {
    id: "ds_hh_profile",
    code: "HH_PROFILE",
    label: "Household profile",
    privacy: "internal",
    floor: "sub-county",
    refresh: "Daily",
    refreshed_at: "28 May 2026 06:00 UTC",
    matview: "mv_de_hh_profile_v7",
    rows: "12.1M",
    variables: 17,
    desc: "Housing, water, sanitation, livelihoods. Released to NSR-internal staff.",
    domains: ["Location", "Housing", "Assets", "PMT", "Identification"],
    featured: true,
  },
  {
    id: "ds_hh_shocks",
    code: "HH_SHOCKS",
    label: "Shocks & coping (12-month)",
    privacy: "internal",
    floor: "sub-county",
    refresh: "Monthly",
    refreshed_at: "01 May 2026 06:00 UTC",
    matview: "mv_de_hh_shocks_v2",
    rows: "12.1M",
    variables: 9,
    desc: "Self-reported shocks (drought, flood, illness) and coping strategies.",
    domains: ["Food & Shocks"],
  },
  {
    id: "ds_hh_prog",
    code: "HH_PROG",
    label: "Programme enrolments",
    privacy: "internal",
    floor: "sub-county",
    refresh: "Daily",
    refreshed_at: "28 May 2026 06:00 UTC",
    matview: "mv_de_hh_prog_v4",
    rows: "3.8M",
    variables: 6,
    desc: "Active enrolments by programme (OPM-PDM, NUSAF, WFP, etc).",
    domains: ["Programmes"],
  },
  {
    id: "ds_hh_pmt",
    code: "HH_PMT",
    label: "Household PMT scores",
    privacy: "personal",
    floor: "sub-region",
    refresh: "Weekly",
    refreshed_at: "26 May 2026 22:00 UTC",
    matview: "mv_de_hh_pmt_v5",
    rows: "12.1M",
    variables: 7,
    desc: "PMT score and band per household. Re-computed weekly.",
    domains: ["PMT"],
  },
  {
    id: "ds_member_health",
    code: "MEM_HEALTH",
    label: "Member health & disability",
    privacy: "personal",
    floor: "sub-region",
    refresh: "Weekly",
    refreshed_at: "26 May 2026 22:00 UTC",
    matview: "mv_de_mem_health_v3",
    rows: "48.1M",
    variables: 11,
    desc: "WG-SS disability domains, chronic illness flags. Member-level.",
    domains: ["Health & Disability"],
  },
  {
    id: "ds_hh_nin_link",
    code: "HH_NIN_LINK",
    label: "Household ↔ NIN linkage",
    privacy: "sensitive",
    floor: "aggregate blocked",
    refresh: "Daily",
    refreshed_at: "28 May 2026 06:00 UTC",
    matview: "—",
    rows: "11.4M",
    variables: 4,
    desc: "Bridge from NIN to household ID. Aggregate use blocked; record-level via DRS only.",
    domains: ["Identification"],
  },
];

/* ================================================================
   Variables — focus on HH_PROFILE (used by Builder & Results demos)
   ================================================================ */
const DE_VARIABLES_BY_DATASET = {
  ds_hh_profile: [
    { code: "hh_size",        label: "Household size",         type: "integer",     privacy: "public",    domain: "Roster",          desc: "Total members on roster", values: "1–14" },
    { code: "head_sex",       label: "Head sex",               type: "categorical", privacy: "public",    domain: "Identification",  desc: "Sex of the head of household", values: "F · M" },
    { code: "head_age_band",  label: "Head age band",          type: "categorical", privacy: "public",    domain: "Identification",  desc: "10-year age band of head", values: "18–29 · 30–39 · 40–49 · 50–59 · 60+" },
    { code: "subregion",      label: "Sub-region",             type: "geo",         privacy: "public",    domain: "Location",        desc: "Statistical sub-region (UBOS)", values: "15 sub-regions" },
    { code: "district",       label: "District",               type: "geo",         privacy: "public",    domain: "Location",        desc: "Administrative district",       values: "146 districts" },
    { code: "subcounty",      label: "Sub-county",             type: "geo",         privacy: "internal",  domain: "Location",        desc: "Administrative sub-county",     values: "1,447 sub-counties" },
    { code: "parish",         label: "Parish",                 type: "geo",         privacy: "internal",  domain: "Location",        desc: "Administrative parish",         values: "10,594 parishes" },
    { code: "urban_rural",    label: "Urban / rural",          type: "categorical", privacy: "public",    domain: "Location",        desc: "Settlement classification", values: "Urban · Rural · Peri-urban" },
    { code: "roof_material",  label: "Roof material",          type: "categorical", privacy: "internal",  domain: "Housing",         desc: "Predominant roof material", values: "Iron · Tiles · Thatch · Concrete · Other" },
    { code: "wall_material",  label: "Wall material",          type: "categorical", privacy: "internal",  domain: "Housing",         desc: "Predominant wall material", values: "Mud+sticks · Bricks · Cement · Other" },
    { code: "water_source",   label: "Water source",           type: "categorical", privacy: "internal",  domain: "Housing",         desc: "Primary drinking water source", values: "Piped · Borehole · Open well · River" },
    { code: "toilet_type",    label: "Toilet type",            type: "categorical", privacy: "internal",  domain: "Housing",         desc: "Sanitation facility used by household", values: "Flush · VIP · Pit · None" },
    { code: "fuel_type",      label: "Cooking fuel",           type: "categorical", privacy: "internal",  domain: "Housing",         desc: "Primary fuel for cooking", values: "Electricity · LPG · Charcoal · Firewood · Other" },
    { code: "land_acres",     label: "Land owned (acres)",     type: "continuous",  privacy: "internal",  domain: "Assets",          desc: "Total land owned, in acres", values: "0–250" },
    { code: "cattle_count",   label: "Cattle owned",           type: "integer",     privacy: "internal",  domain: "Assets",          desc: "Head of cattle owned",         values: "0–80" },
    { code: "pmt_score",      label: "PMT score",              type: "continuous",  privacy: "personal",  domain: "PMT",             desc: "Proxy-Means-Test score (0–1)", values: "0.000–1.000" },
    { code: "pmt_band",       label: "PMT band",               type: "categorical", privacy: "personal",  domain: "PMT",             desc: "PMT decile band",              values: "Poorest 20% · Poorest 40% · Middle 40% · Richest 20%" },
    { code: "head_nin",       label: "Head NIN",               type: "string",      privacy: "sensitive", domain: "Identification",  desc: "Verified National ID number — aggregate use blocked", values: "—" },
  ],
};

/* ================================================================
   Geographic frame — used by scope picker
   ================================================================ */
const DE_GEO_LEVELS = [
  { code: "country",    label: "Country (national)", units: 1 },
  { code: "subregion",  label: "Sub-region",         units: 15 },
  { code: "district",   label: "District",           units: 146 },
  { code: "subcounty",  label: "Sub-county",         units: 1447 },
  { code: "parish",     label: "Parish",             units: 10594 },
  { code: "village",    label: "Village",            units: 71000 },
];

// Floor ordering — anything finer than the floor is a violation.
const DE_GEO_INDEX = Object.fromEntries(DE_GEO_LEVELS.map((g, i) => [g.code, i]));
const violatesFloor = (level, floor) => {
  const map = { "sub-region": "subregion", "sub-county": "subcounty", "national": "country" };
  const floorKey = map[floor] || floor;
  if (!(floorKey in DE_GEO_INDEX) || !(level in DE_GEO_INDEX)) return false;
  return DE_GEO_INDEX[level] > DE_GEO_INDEX[floorKey];
};

/* ================================================================
   Suppression vocabulary — text shown on hover over "—" cells.
   ================================================================ */
const DE_SUPPRESSION = {
  short: "Suppressed",
  long: "This cell is suppressed to protect privacy.",
  detail: "Counts below the dataset's k-floor are replaced with the suppression glyph. No approximation, no rounding — the underlying figure cannot be released at this geographic level.",
  vocab_id: "vocab.suppression.k_floor_v1",
};

/* ================================================================
   Screen tab list — used by every Data Explorer HTML
   ================================================================ */
const DE_SCREENS = [
  { id: "catalogue", label: "Catalogue",         icon: "book",     href: "Data Explorer - Catalogue.html" },
  { id: "builder",   label: "Aggregate builder", icon: "sliders",  href: "Data Explorer - Aggregate Builder.html" },
  { id: "results",   label: "Results",           icon: "barchart", href: "Data Explorer - Results.html" },
  { id: "coverage",  label: "Coverage",          icon: "mapPin",   href: "Data Explorer - Coverage.html" },
  { id: "synthetic", label: "Synthetic sample",  icon: "database", href: "Data Explorer - Synthetic Sample.html" },
];

/* ================================================================
   PrivacyChip — color-coded per the ADR-0023 table.
   ================================================================ */
const PrivacyChip = ({ klass, size = "md", showFloor = false }) => {
  const cfg = DE_PRIVACY[klass];
  if (!cfg) return null;
  return (
    <span className={`chip chip-${cfg.tone} ${size === "sm" ? "chip-sm" : ""}`} title={cfg.blurb}>
      {cfg.icon === "lock" && <Icon name="lock" size={size === "sm" ? 9 : 11}/>}
      {cfg.label.toLowerCase()}
      {showFloor && cfg.geo_floor !== "aggregate blocked" && (
        <span style={{opacity:0.7, marginLeft:4, fontWeight:400}}> · {cfg.geo_floor}</span>
      )}
      {showFloor && cfg.geo_floor === "aggregate blocked" && (
        <span style={{opacity:0.85, marginLeft:4, fontWeight:400}}> · blocked</span>
      )}
    </span>
  );
};

/* ================================================================
   DEShell — top bar + screen tabs + matview-freshness indicator
   ================================================================ */
const DEShell = ({ active, refreshed_at, children, right, publicLive }) => {
  // Drive the role chip + avatar from the live gate so the header
  // never claims a signed-in EXPLORER while the body is showing mock
  // data. `live` means a reachable API AND an EXPLORER session AND the
  // flag on — the same condition RoleGateBanner uses to stay hidden.
  // `publicLive` (passed by the catalogue screen) means the body is
  // showing the live anonymous transparency catalogue, not mock.
  const gate = useDeMe();
  const live = !gate.loading && gate.hasRole && gate.flagOn && !!gate.me;
  const _initials = () => {
    if (!live) return "·";
    const n = (gate.me.display_name || gate.me.username || "").trim();
    const parts = n.split(/\s+/).filter(Boolean);
    if (!parts.length) return "?";
    return (parts[0][0] + (parts[1] ? parts[1][0] : "")).toUpperCase();
  };
  return (
  <div style={{minHeight:"100vh", background:"var(--neutral-100)"}}>
    {/* Topbar */}
    <header style={{
      background:"var(--neutral-0)",
      borderBottom:"1px solid var(--neutral-300)",
      position:"sticky", top:0, zIndex:20,
    }}>
      <div style={{
        maxWidth: 1600, margin: "0 auto",
        padding: "10px 24px",
        display:"flex", alignItems:"center", gap:16,
      }}>
        <div style={{display:"flex", alignItems:"center", gap:10, minWidth:240}}>
          <div style={{
            width:28, height:28, borderRadius:4,
            background:"var(--primary-900)", color:"#fff",
            display:"grid", placeItems:"center", fontSize:11, fontWeight:700,
          }}>NSR</div>
          <div style={{lineHeight:1.1}}>
            <div style={{fontWeight:700, color:"var(--primary-900)", fontSize:14}}>Data Explorer</div>
            <div className="t-cap" style={{fontSize:10.5, letterSpacing:"0.04em"}}>NSR MIS · US-DATA-EXP-001</div>
          </div>
        </div>
        <div style={{flex:1}}/>
        {/* Freshness indicator */}
        <div style={{
          display:"flex", alignItems:"center", gap:8,
          padding:"4px 10px",
          border:"1px solid var(--neutral-200)",
          borderRadius:14,
          background:"var(--neutral-50)",
          color:"var(--neutral-700)",
          fontSize:12,
        }}>
          <span style={{width:6, height:6, borderRadius:"50%", background:"var(--accent-data)"}}/>
          Last matview refresh: <strong style={{color:"var(--neutral-900)"}}>{refreshed_at}</strong>
        </div>
        {live ? (
          <div className="role-chip" style={{margin:0}}>
            <span>Role:</span><strong>EXPLORER</strong>
          </div>
        ) : publicLive ? (
          <div className="role-chip" style={{margin:0, opacity:0.85}}
               title="Live public data dictionary — metadata only">
            <span>Public</span><strong>catalogue</strong>
          </div>
        ) : (
          <div className="role-chip" style={{margin:0, opacity:0.6}}
               title="Not a live EXPLORER session — showing mock data">
            <span>Preview</span><strong>mock</strong>
          </div>
        )}
        <div style={{
          width:32, height:32, borderRadius:"50%",
          background: live ? "var(--primary-700)" : "var(--neutral-400)", color:"#fff",
          display:"grid", placeItems:"center", fontSize:12, fontWeight:600,
        }} title={live ? (gate.me.display_name || gate.me.username || "") : "No authenticated session"}>{_initials()}</div>
      </div>
      {/* Tabs */}
      <div style={{
        maxWidth: 1600, margin: "0 auto",
        padding: "0 24px",
        display:"flex", alignItems:"flex-end", gap:0,
      }}>
        {DE_SCREENS.map(s => {
          const isActive = s.id === active;
          return (
            <a key={s.id} href={s.href} style={{
              display:"inline-flex", alignItems:"center", gap:8,
              padding:"10px 16px",
              borderBottom: isActive ? "2px solid var(--primary-900)" : "2px solid transparent",
              color: isActive ? "var(--primary-900)" : "var(--neutral-700)",
              fontWeight: isActive ? 600 : 500, fontSize:13.5,
              textDecoration:"none",
              marginBottom:-1,
            }}>
              <Icon name={s.icon} size={14}/>
              {s.label}
            </a>
          );
        })}
        <div style={{flex:1}}/>
        {right}
      </div>
    </header>

    {/* Main */}
    <main style={{
      maxWidth: 1600, margin: "0 auto",
      padding: "20px 24px 40px",
    }}>{children}</main>
  </div>
  );
};

/* ================================================================
   ScopeTweak — every screen's Tweaks panel uses this so the user
   can hop between the five HTML files from any screen.
   ================================================================ */
const ScreenJumpTweak = ({ active }) => {
  const [val, setVal] = React.useState(active);
  const onChange = (next) => {
    setVal(next);
    const screen = DE_SCREENS.find(s => s.id === next);
    if (screen) window.location.href = screen.href;
  };
  return (
    <TweakRadio
      label="Active screen"
      value={val}
      onChange={onChange}
      options={DE_SCREENS.map(s => ({ value: s.id, label: s.label.replace("Aggregate ", "").replace(" sample","") }))}
      hint="Jumps between Data Explorer screens."/>
  );
};

/* ================================================================
   StrictestClassChip — computed live as variables are added
   ================================================================ */
const strictestClass = (codes) => {
  const order = { public: 0, internal: 1, personal: 2, sensitive: 3 };
  let best = "public";
  codes.forEach(c => { if (order[c] > order[best]) best = c; });
  return best;
};

/* ================================================================
   Suppressed cell — dash glyph with hover tooltip
   ================================================================ */
const SuppressedCell = () => (
  <span title={`${DE_SUPPRESSION.long}\n\n${DE_SUPPRESSION.detail}\n\nVocab: ${DE_SUPPRESSION.vocab_id}`}
    style={{
      display:"inline-flex", alignItems:"center", gap:4,
      padding:"2px 8px",
      background:"var(--neutral-100)",
      color:"var(--neutral-500)",
      borderRadius:3,
      fontFamily:"'JetBrains Mono', ui-monospace, monospace",
      fontSize:13,
      cursor:"help",
      borderBottom:"1px dotted var(--neutral-500)",
    }}>—</span>
);

/* ================================================================
   FloorViolationBanner — 422 response on /aggregate/
   ================================================================ */
const FloorViolationBanner = ({ violation, onRequestHandoff }) => (
  <div style={{
    background:"var(--accent-quality-bg)",
    border:"1px solid var(--accent-quality)",
    borderLeft:"4px solid var(--accent-quality)",
    borderRadius:6,
    padding:"14px 18px",
    display:"flex", gap:14, alignItems:"flex-start",
    marginBottom:16,
  }}>
    <div style={{
      width:36, height:36, borderRadius:"50%",
      background:"var(--accent-quality)", color:"#fff",
      display:"grid", placeItems:"center", flex:"0 0 auto",
    }}>
      <Icon name="alert" size={18}/>
    </div>
    <div style={{flex:1, minWidth:0}}>
      <div style={{display:"flex", alignItems:"center", gap:8, marginBottom:2}}>
        <strong style={{color:"var(--accent-quality)", fontSize:14}}>Geographic floor violation</strong>
        <span className="t-cap t-mono">HTTP 422 · geographic_floor_violation</span>
      </div>
      <div className="t-bodysm" style={{color:"var(--neutral-700)", marginBottom:8}}>
        {violation.scope_label} is finer than the dataset's <strong>{violation.floor}</strong> floor.
        Aggregate cannot be returned for <span className="t-mono">{violation.requested_level}</span>{" "}
        ({violation.requested_codes.length} codes). Request record-level data via DRS, or coarsen the scope to {violation.floor} or higher.
      </div>
      <div style={{display:"flex", gap:10}}>
        <button className="btn btn-warn" onClick={onRequestHandoff}>
          <Icon name="arrowRight" size={14}/> Request record-level data
        </button>
        <button className="btn btn-ghost">
          <Icon name="info" size={14}/> Why this floor?
        </button>
      </div>
    </div>
  </div>
);

/* ================================================================
   Result-row sample — Used by Results & Synthetic. Built from
   the registry household sample (Nsubuga Ruth area + ten others).
   ================================================================ */
const DE_RESULT_ROWS = [
  // Public + internal aggregate: count by district × roof × water
  { subregion:"Buganda South", district:"Lyantonde", roof:"Iron sheets",   water:"Piped — public tap",  count: 4218,  pmt_avg: 0.518 },
  { subregion:"Buganda South", district:"Lyantonde", roof:"Iron sheets",   water:"Borehole < 1 km",    count: 11842, pmt_avg: 0.402 },
  { subregion:"Buganda South", district:"Lyantonde", roof:"Iron sheets",   water:"Open well",          count: 2380,  pmt_avg: 0.331 },
  { subregion:"Buganda South", district:"Lyantonde", roof:"Tiles",         water:"Piped — public tap",  count: 612,   pmt_avg: 0.687 },
  { subregion:"Buganda South", district:"Lyantonde", roof:"Thatch / grass",water:"Borehole < 1 km",    count: 1108,  pmt_avg: 0.298 },
  { subregion:"Buganda South", district:"Lyantonde", roof:"Thatch / grass",water:"Open well",          count: null,  pmt_avg: null, suppressed: true },
  { subregion:"Buganda South", district:"Lyantonde", roof:"Concrete",      water:"Piped — public tap",  count: null,  pmt_avg: null, suppressed: true },
  { subregion:"Karamoja",      district:"Moroto",    roof:"Iron sheets",   water:"Borehole < 1 km",    count: 8492,  pmt_avg: 0.341 },
  { subregion:"Karamoja",      district:"Moroto",    roof:"Thatch / grass",water:"Borehole < 1 km",    count: 14076, pmt_avg: 0.276 },
  { subregion:"Karamoja",      district:"Moroto",    roof:"Thatch / grass",water:"Open well",          count: 6204,  pmt_avg: 0.262 },
  { subregion:"Karamoja",      district:"Moroto",    roof:"Thatch / grass",water:"River / pond",       count: 2811,  pmt_avg: 0.241 },
  { subregion:"Karamoja",      district:"Napak",     roof:"Thatch / grass",water:"Borehole < 1 km",    count: 9614,  pmt_avg: 0.288 },
  { subregion:"Karamoja",      district:"Napak",     roof:"Iron sheets",   water:"Borehole < 1 km",    count: 3122,  pmt_avg: 0.354 },
  { subregion:"West Nile",     district:"Arua",      roof:"Iron sheets",   water:"Borehole < 1 km",    count: 6440,  pmt_avg: 0.421 },
  { subregion:"West Nile",     district:"Arua",      roof:"Thatch / grass",water:"Open well",          count: 5117,  pmt_avg: 0.342 },
  { subregion:"West Nile",     district:"Yumbe",     roof:"Iron sheets",   water:"Borehole < 1 km",    count: 4881,  pmt_avg: 0.398 },
  { subregion:"West Nile",     district:"Yumbe",     roof:"Thatch / grass",water:"River / pond",       count: null,  pmt_avg: null, suppressed: true },
  { subregion:"Acholi",        district:"Gulu",      roof:"Iron sheets",   water:"Piped — public tap",  count: 3604,  pmt_avg: 0.488 },
  { subregion:"Acholi",        district:"Gulu",      roof:"Iron sheets",   water:"Borehole < 1 km",    count: 7211,  pmt_avg: 0.411 },
  { subregion:"Acholi",        district:"Gulu",      roof:"Thatch / grass",water:"Borehole < 1 km",    count: 4326,  pmt_avg: 0.323 },
];

/* ================================================================
   Coverage rows — per-area completeness for HH_PROFILE
   ================================================================ */
const DE_COVERAGE_ROWS = [
  { geo_level: "subregion", geo_code: "SR-BUGANDA-S",  geo_label: "Buganda South",  completeness: 0.96, rows: 1842117, last_capture: "27 May 2026" },
  { geo_level: "subregion", geo_code: "SR-KARAMOJA",   geo_label: "Karamoja",       completeness: 0.78, rows: 488221,  last_capture: "27 May 2026" },
  { geo_level: "subregion", geo_code: "SR-WEST-NILE",  geo_label: "West Nile",      completeness: 0.84, rows: 720418,  last_capture: "27 May 2026" },
  { geo_level: "subregion", geo_code: "SR-ACHOLI",     geo_label: "Acholi",         completeness: 0.81, rows: 612338,  last_capture: "27 May 2026" },
  { geo_level: "subregion", geo_code: "SR-LANGO",      geo_label: "Lango",          completeness: 0.88, rows: 824114,  last_capture: "27 May 2026" },
  { geo_level: "subregion", geo_code: "SR-TESO",       geo_label: "Teso",           completeness: 0.85, rows: 711204,  last_capture: "27 May 2026" },
  { geo_level: "subregion", geo_code: "SR-BUSOGA",     geo_label: "Busoga",         completeness: 0.94, rows: 1422311, last_capture: "27 May 2026" },
  { geo_level: "subregion", geo_code: "SR-BUNYORO",    geo_label: "Bunyoro",        completeness: 0.91, rows: 1041221, last_capture: "27 May 2026" },
  { geo_level: "subregion", geo_code: "SR-TOORO",      geo_label: "Tooro",          completeness: 0.89, rows: 924178,  last_capture: "27 May 2026" },
  { geo_level: "subregion", geo_code: "SR-RWENZORI",   geo_label: "Rwenzori",       completeness: 0.83, rows: 422118,  last_capture: "27 May 2026" },
  { geo_level: "subregion", geo_code: "SR-ANKOLE",     geo_label: "Ankole",         completeness: 0.93, rows: 1128221, last_capture: "27 May 2026" },
  { geo_level: "subregion", geo_code: "SR-KIGEZI",     geo_label: "Kigezi",         completeness: 0.92, rows: 644118,  last_capture: "27 May 2026" },
  { geo_level: "subregion", geo_code: "SR-BUKEDI",     geo_label: "Bukedi",         completeness: 0.79, rows: 511408,  last_capture: "27 May 2026" },
  { geo_level: "subregion", geo_code: "SR-ELGON",      geo_label: "Elgon",          completeness: 0.86, rows: 692114,  last_capture: "27 May 2026" },
  { geo_level: "subregion", geo_code: "SR-KAMPALA",    geo_label: "Kampala",        completeness: 0.97, rows: 482211,  last_capture: "27 May 2026" },
];

/* ================================================================
   Synthetic sample rows — explicitly fake households
   ================================================================ */
const DE_SYNTHETIC_ROWS = [
  { synth_id: "synth-0001", hh_size: 6, head_sex: "F", head_age_band: "30–39", subregion: "Buganda South", district: "Lyantonde", roof_material: "Iron sheets",   water_source: "Borehole < 1 km", pmt_band: "Poorest 40%" },
  { synth_id: "synth-0002", hh_size: 4, head_sex: "M", head_age_band: "40–49", subregion: "Karamoja",      district: "Moroto",    roof_material: "Thatch / grass", water_source: "River / pond",   pmt_band: "Poorest 20%" },
  { synth_id: "synth-0003", hh_size: 8, head_sex: "F", head_age_band: "50–59", subregion: "West Nile",     district: "Arua",      roof_material: "Iron sheets",   water_source: "Borehole < 1 km", pmt_band: "Poorest 40%" },
  { synth_id: "synth-0004", hh_size: 3, head_sex: "M", head_age_band: "60+",   subregion: "Acholi",        district: "Gulu",      roof_material: "Iron sheets",   water_source: "Piped — public tap", pmt_band: "Middle 40%" },
  { synth_id: "synth-0005", hh_size: 5, head_sex: "F", head_age_band: "30–39", subregion: "Lango",         district: "Lira",      roof_material: "Iron sheets",   water_source: "Borehole < 1 km", pmt_band: "Poorest 40%" },
  { synth_id: "synth-0006", hh_size: 7, head_sex: "F", head_age_band: "40–49", subregion: "Buganda South", district: "Lyantonde", roof_material: "Iron sheets",   water_source: "Borehole < 1 km", pmt_band: "Poorest 20%" },
  { synth_id: "synth-0007", hh_size: 2, head_sex: "F", head_age_band: "60+",   subregion: "Karamoja",      district: "Napak",     roof_material: "Thatch / grass", water_source: "Borehole < 1 km", pmt_band: "Poorest 20%" },
  { synth_id: "synth-0008", hh_size: 9, head_sex: "M", head_age_band: "40–49", subregion: "West Nile",     district: "Yumbe",     roof_material: "Iron sheets",   water_source: "Borehole < 1 km", pmt_band: "Poorest 40%" },
  { synth_id: "synth-0009", hh_size: 6, head_sex: "F", head_age_band: "30–39", subregion: "Buganda South", district: "Lyantonde", roof_material: "Tiles",         water_source: "Piped — public tap", pmt_band: "Middle 40%" },
  { synth_id: "synth-0010", hh_size: 4, head_sex: "M", head_age_band: "50–59", subregion: "Acholi",        district: "Gulu",      roof_material: "Iron sheets",   water_source: "Borehole < 1 km", pmt_band: "Poorest 40%" },
];

/* ================================================================
   Live data hooks — wrap window.useApi (loaded by api-client.jsx).
   Each hook returns [data, meta] where meta = { loading, error,
   isLive }. When the API isn't reachable (preview under file://
   or backend down), `data` falls back to the in-module mock so the
   harness still renders something useful and isLive = false.

   Shape mapping: the backend API responses don't carry the
   demo-friendly fields the screens render (refresh cadence label,
   row counts, domain tags). Where we can't infer them from the
   response, we leave the live row with the literal API value and
   the screen formats it.
   ================================================================ */

const _DE_API_PREFIX = "/api/v1/data-explorer";

const _mergeMock = (live, mock, keyFn) => {
  /* Fill missing display-only fields on `live` from `mock` keyed by
     keyFn (e.g. d => d.code). This keeps the rich demo copy on screen
     while preserving the canonical id/code/privacy_class from the API. */
  if (!Array.isArray(live)) return mock;
  const byKey = new Map(mock.map(m => [keyFn(m), m]));
  return live.map(l => {
    const m = byKey.get(keyFn(l)) || {};
    return { ...m, ...l };
  });
};

const _normaliseDataset = (raw) => {
  /* Backend ships either flattened (privacy_class_code) or nested
     (privacy_class: {code}). The screens want a flat `privacy` field. */
  if (!raw) return raw;
  const privacy = raw.privacy
    || (raw.privacy_class && raw.privacy_class.code)
    || raw.privacy_class_code
    || "internal";
  const floor = raw.floor
    || raw.geographic_floor
    || (DE_PRIVACY[privacy] && DE_PRIVACY[privacy].geo_floor)
    || "sub-county";
  return { ...raw, privacy, floor };
};

/* Public questionnaire catalogue (anonymous, metadata-only). Sections
   map onto the dataset shape and fields onto the variable shape so the
   catalogue screen renders the whole questionnaire with no changes. */
const _DE_PUBLIC_URL = `${_DE_API_PREFIX}/catalogue/public/`;
const _STRICTNESS = ["public", "internal", "personal", "sensitive"];

const _sectionStrictest = (fields) =>
  (fields || []).reduce(
    (acc, f) =>
      _STRICTNESS.indexOf(f.privacy_class) > _STRICTNESS.indexOf(acc)
        ? f.privacy_class : acc,
    "public",
  );

const _sectionToDataset = (s) => ({
  id: s.key, code: s.key, label: s.label,
  desc: `${s.field_count} field${s.field_count === 1 ? "" : "s"} captured in the `
    + `${s.label} section`
    + (s.questionnaire_section ? ` · questionnaire ${s.questionnaire_section}` : "")
    + ".",
  privacy: _sectionStrictest(s.fields),
  // Metadata only — no counts/matview on the transparency surface.
  rows: "—", variables: s.field_count,
  refresh: "questionnaire", matview: "—", refreshed_at: "—",
  _public: true,
});

const _fieldToVar = (f, sectionKey) => ({
  code: f.field_id, label: f.label, type: f.type,
  privacy: f.privacy_class, domain: sectionKey,
  desc: f.aggregatable
    ? "Aggregatable — counts only, with k-anonymity suppression."
    : "Sensitive — record-level only, via a Data Sharing Agreement.",
  values: f.choice_list ? `coded · ${f.choice_list}` : (f.pmt_relevant ? "PMT-relevant" : ""),
});

const useDeCatalogue = () => {
  const useApi = (typeof window !== "undefined" && window.useApi) || null;
  if (!useApi) {
    return [DE_DATASETS, { loading: false, error: null, isLive: false, isPublic: false }];
  }
  // Call both unconditionally so hook order is stable across renders.
  const [resp, meta] = useApi(`${_DE_API_PREFIX}/datasets/`);
  const [pubResp, pubMeta] = useApi(_DE_PUBLIC_URL);
  const rows = (resp && (resp.datasets || resp.results || resp)) || null;
  // 1. EXPLORER-gated aggregate datasets win when reachable.
  if (!meta.loading && !meta.error && Array.isArray(rows) && rows.length) {
    const merged = _mergeMock(rows.map(_normaliseDataset), DE_DATASETS, d => d.code);
    return [merged, { loading: false, error: null, isLive: true, isPublic: false }];
  }
  // 2. Public questionnaire catalogue — anonymous-readable transparency.
  const sections = (pubResp && pubResp.sections) || null;
  if (!pubMeta.loading && !pubMeta.error && Array.isArray(sections) && sections.length) {
    return [sections.map(_sectionToDataset),
            { loading: false, error: null, isLive: true, isPublic: true }];
  }
  // 3. Still loading, or fully offline → mock.
  if (meta.loading || pubMeta.loading) {
    return [DE_DATASETS, { loading: true, error: null, isLive: false, isPublic: false }];
  }
  return [DE_DATASETS,
          { loading: false, error: meta.error || pubMeta.error, isLive: false, isPublic: false }];
};

const useDeDataset = (datasetId) => {
  /* Returns the dataset detail (with variables[]) for the given id.
     Cascade mirrors useDeCatalogue: gated dataset → public section →
     mock by id/code. */
  const useApi = (typeof window !== "undefined" && window.useApi) || null;
  const mockDs = DE_DATASETS.find(d => d.id === datasetId || d.code === datasetId);
  const mockVars = DE_VARIABLES_BY_DATASET[mockDs?.id] || [];
  if (!useApi || !datasetId) {
    return [{ dataset: mockDs, variables: mockVars },
            { loading: false, error: null, isLive: false }];
  }
  const [resp, meta] = useApi(`${_DE_API_PREFIX}/datasets/${datasetId}/`);
  const [pubResp, pubMeta] = useApi(_DE_PUBLIC_URL);
  if (!meta.loading && !meta.error && resp) {
    return [{ dataset: _normaliseDataset(resp), variables: resp.variables || mockVars },
            { loading: false, error: null, isLive: true }];
  }
  const sections = (pubResp && pubResp.sections) || null;
  if (!pubMeta.loading && !pubMeta.error && Array.isArray(sections)) {
    const sec = sections.find(s => s.key === datasetId);
    if (sec) {
      return [{ dataset: _sectionToDataset(sec),
                variables: sec.fields.map(f => _fieldToVar(f, sec.key)) },
              { loading: false, error: null, isLive: true }];
    }
  }
  if (meta.loading || pubMeta.loading) {
    return [{ dataset: mockDs, variables: mockVars }, { loading: true, error: null, isLive: false }];
  }
  return [{ dataset: mockDs, variables: mockVars },
          { loading: false, error: meta.error || pubMeta.error, isLive: false }];
};

const useDeCoverage = (datasetId) => {
  const useApi = (typeof window !== "undefined" && window.useApi) || null;
  if (!useApi || !datasetId) return [DE_COVERAGE_ROWS, { loading: false, error: null, isLive: false }];
  const [resp, meta] = useApi(`${_DE_API_PREFIX}/coverage/${datasetId}/`);
  const rows = (resp && (resp.rows || resp.results || resp)) || null;
  if (meta.loading) return [DE_COVERAGE_ROWS, { ...meta, isLive: false }];
  if (meta.error || !Array.isArray(rows) || rows.length === 0) {
    return [DE_COVERAGE_ROWS, { loading: false, error: meta.error, isLive: false }];
  }
  return [rows, { loading: false, error: null, isLive: true }];
};

const useDeSynthetic = (datasetId) => {
  const useApi = (typeof window !== "undefined" && window.useApi) || null;
  if (!useApi || !datasetId) return [DE_SYNTHETIC_ROWS, { loading: false, error: null, isLive: false }];
  const [resp, meta] = useApi(`${_DE_API_PREFIX}/synthetic-sample/${datasetId}/`);
  const rows = (resp && (resp.rows || resp.results || resp)) || null;
  if (meta.loading) return [DE_SYNTHETIC_ROWS, { ...meta, isLive: false }];
  if (meta.error || !Array.isArray(rows) || rows.length === 0) {
    return [DE_SYNTHETIC_ROWS, { loading: false, error: meta.error, isLive: false }];
  }
  return [rows, { loading: false, error: null, isLive: true }];
};

const useDeMe = () => {
  /* Role + feature-flag gate. Returns { hasRole, flagOn, me, loading,
     error }. EXPLORER role required + data_explorer_enabled feature
     flag required to "live" mode. When the API is unreachable, we
     report flagOn=false so the UI shows a "preview mode" banner. */
  const useApi = (typeof window !== "undefined" && window.useApi) || null;
  if (!useApi) return { hasRole: false, flagOn: false, me: null, loading: false, error: null };
  // The identity endpoint lives under the security app's mount, not a
  // bare /api/v1/users/. Calling the wrong path 404s, which the gate
  // reports as "API unreachable" even on a healthy, signed-in session.
  const [resp, meta] = useApi("/api/v1/security/users/me/");
  if (meta.loading) {
    return { hasRole: false, flagOn: false, me: null, loading: true, error: null };
  }
  if (meta.error || !resp) {
    return { hasRole: false, flagOn: false, me: null, loading: false, error: meta.error };
  }
  const roles = Array.isArray(resp.roles) ? resp.roles : [];
  const flags = (resp.feature_flags || {});
  return {
    hasRole: roles.includes("EXPLORER"),
    flagOn: Boolean(flags.data_explorer_enabled),
    me: resp,
    loading: false,
    error: null,
  };
};

const submitAggregate = async (payload) => {
  /* POST the aggregate query. Returns the parsed response or throws.
     Caller is responsible for stashing the result in sessionStorage
     so the Results page can render it. */
  if (typeof window === "undefined" || !window.nsrApi) {
    throw new Error("nsrApi unavailable — load api-client.jsx first");
  }
  return window.nsrApi.post(`${_DE_API_PREFIX}/aggregate/`, payload);
};

const submitHandoff = async (payload) => {
  /* POST /handoff/ — converts an aggregate context into a DRS draft.
     Backend response carries { redirect, redirect_url } deep-linking
     to /data-requests/{id}/ in the operator console. */
  if (typeof window === "undefined" || !window.nsrApi) {
    throw new Error("nsrApi unavailable — load api-client.jsx first");
  }
  return window.nsrApi.post(`${_DE_API_PREFIX}/handoff/`, payload);
};

/* ================================================================
   HandoffPrompt — modal-ish overlay that collects purpose_of_use
   (DPPA 2019 purpose-limitation principle) and submits to /handoff/.
   On 201, navigates the user to the DRS draft in a new tab.
   ================================================================ */
const HandoffPrompt = ({ open, context, onClose }) => {
  const [purpose, setPurpose] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState(null);
  if (!open) return null;

  const validPurpose = (purpose || "").trim().length >= 30;
  const submit = async () => {
    if (!validPurpose || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const lastAgg = (() => {
        try { return JSON.parse(sessionStorage.getItem("de_last_aggregate") || "null"); }
        catch (e) { return null; }
      })();
      const payload = {
        session_id: lastAgg?.response?.session_id,  // backend creates if absent
        purpose_of_use: purpose.trim(),
        requested_entity: context.requested_entity || "Household",
        requested_fields: context.requested_fields || [],
        geographic_scope: context.geographic_scope || { level: "sub_county", codes: [] },
        filter_expression: context.filter_expression || { and: [] },
        estimated_row_count: context.estimated_row_count || null,
        source_query_hash: context.source_query_hash || lastAgg?.response?.metadata?.query_hash,
      };
      const resp = await submitHandoff(payload);
      const url = resp?.redirect_url || resp?.redirect;
      if (url) {
        window.open(url, "_blank", "noopener");
      }
      onClose({ ok: true, response: resp });
    } catch (err) {
      const noBackend = err && (err.status === 404 || /Failed to fetch/i.test(String(err.message || "")));
      if (noBackend) {
        // Preview-mode fall-through: pretend it succeeded so the
        // designer can review the flow without a live backend.
        onClose({ ok: true, response: null, preview: true });
        return;
      }
      setError(String(err.body?.error || err.message || err));
      setSubmitting(false);
    }
  };

  return (
    <div style={{
      position:"fixed", top:0, left:0, right:0, bottom:0,
      background:"rgba(15, 23, 42, 0.5)",
      display:"grid", placeItems:"center",
      zIndex:50,
    }} onClick={() => !submitting && onClose({ ok: false })}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background:"var(--neutral-0)",
        borderRadius:8,
        boxShadow:"0 12px 36px rgba(15, 23, 42, 0.3)",
        width:540, maxWidth:"90vw", maxHeight:"90vh",
        overflowY:"auto",
        padding:0,
      }}>
        <div style={{
          padding:"16px 20px",
          borderBottom:"1px solid var(--neutral-300)",
          display:"flex", alignItems:"center", gap:10,
        }}>
          <Icon name="arrowRight" size={18} color="var(--primary-900)"/>
          <strong style={{fontSize:15}}>Request record-level data</strong>
          <div style={{flex:1}}/>
          <button className="icon-btn" onClick={() => !submitting && onClose({ ok: false })}>
            <Icon name="x" size={14}/>
          </button>
        </div>

        <div style={{padding:"16px 20px"}}>
          <div style={{
            background:"var(--accent-update-bg)",
            border:"1px solid var(--accent-update)",
            borderLeft:"4px solid var(--accent-update)",
            padding:"10px 14px", borderRadius:6, marginBottom:14,
            fontSize:12.5, color:"var(--neutral-700)",
          }}>
            This opens a DRS draft pre-filled with your query context. A DPO
            reviews every record-level request before it can be exported.
            Audited per DPPA 2019 §3(b) (purpose limitation).
          </div>

          <div style={{marginBottom:12}}>
            <label className="t-cap" style={{display:"block", marginBottom:4}}>
              DATASET / ENTITY
            </label>
            <div className="t-mono" style={{fontSize:13}}>
              {context.dataset_label || context.dataset_code || "—"} → {context.requested_entity || "Household"}
            </div>
          </div>

          <div style={{marginBottom:12}}>
            <label className="t-cap" style={{display:"block", marginBottom:4}}>
              PURPOSE OF USE <span style={{color:"var(--accent-danger)"}}>*</span>
            </label>
            <textarea
              value={purpose}
              onChange={(e) => setPurpose(e.target.value)}
              placeholder="e.g. SAGE benefit eligibility re-targeting in Karamoja sub-region, programme cycle 2026-Q3. Linked to MGLSD M&E plan §4.2."
              rows={4}
              disabled={submitting}
              style={{
                width:"100%",
                padding:"8px 10px",
                border:`1px solid ${validPurpose ? "var(--neutral-300)" : "var(--accent-quality)"}`,
                borderRadius:4,
                fontSize:13,
                resize:"vertical",
                fontFamily:"inherit",
              }}/>
            <div className="t-cap" style={{marginTop:4, color: validPurpose ? "var(--neutral-500)" : "var(--accent-quality)"}}>
              {purpose.trim().length} of 30 characters minimum (DPPA 2019 — purpose limitation)
            </div>
          </div>

          {error && (
            <div style={{
              background:"var(--accent-danger-bg)",
              border:"1px solid var(--accent-danger)",
              borderRadius:4, padding:"8px 12px", marginBottom:12,
              fontSize:12.5, color:"var(--accent-danger)",
            }}>
              <strong>Handoff rejected.</strong> <span style={{color:"var(--neutral-700)"}}>{error}</span>
            </div>
          )}
        </div>

        <div style={{
          padding:"12px 20px",
          borderTop:"1px solid var(--neutral-300)",
          display:"flex", justifyContent:"flex-end", gap:8,
          background:"var(--neutral-50)",
        }}>
          <button className="btn" disabled={submitting} onClick={() => onClose({ ok: false })}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={!validPurpose || submitting} onClick={submit}>
            <Icon name={submitting ? "loader" : "arrowRight"} size={14}/>
            {submitting ? " Creating draft…" : " Create DRS draft"}
          </button>
        </div>
      </div>
    </div>
  );
};

const RoleGateBanner = ({ me }) => {
  /* Renders a stripe at the top of the screen when:
     - The API is unreachable (preview mode), or
     - The user lacks the EXPLORER role, or
     - The data_explorer_enabled flag is off.
     Doesn't render when everything checks out. */
  if (me.loading) return null;
  if (me.hasRole && me.flagOn) return null;
  let label, tone, detail;
  if (me.error || !me.me) {
    // A 401/403 means the API is reachable but the browser has no
    // authenticated session — a different fix from a true network
    // failure, so say which one it is.
    const unauth = /\b(401|403)\b/.test(String(me.error || ""));
    tone = "info";
    if (unauth) {
      label = "Not signed in";
      detail = "The API is reachable but this browser has no authenticated EXPLORER session. Open this page through the Django console (same origin, /console/…) and sign in; showing mock data meanwhile.";
    } else {
      label = "Preview mode";
      detail = "Showing the in-bundle mock data — the API is unreachable. Serve this page same-origin from Django (/console/…) with DATA_EXPLORER_ENABLED on and an EXPLORER session to see live data.";
    }
  } else if (!me.flagOn) {
    label = "Feature flag off";
    tone = "warn";
    detail = "DATA_EXPLORER_ENABLED is false in this environment. Showing mock data; live data not exposed.";
  } else if (!me.hasRole) {
    label = "Role missing";
    tone = "warn";
    detail = `Your session (${me.me.username || "—"}) lacks the EXPLORER realm role. Live data is read-only for EXPLORER users; see the DPIA addendum for the activation gate.`;
  }
  const bg = tone === "warn" ? "var(--accent-quality-bg)" : "var(--accent-update-bg)";
  const fg = tone === "warn" ? "var(--accent-quality)" : "var(--accent-update)";
  return (
    <div style={{
      background: bg,
      borderBottom: `1px solid ${fg}`,
      padding: "8px 24px",
      display: "flex", alignItems: "center", gap: 10,
      fontSize: 12.5,
    }}>
      <Icon name="info" size={14} color={fg}/>
      <strong style={{color: fg}}>{label}.</strong>
      <span style={{color: "var(--neutral-700)"}}>{detail}</span>
    </div>
  );
};

Object.assign(window, {
  DE_PRIVACY, DE_PRIVACY_ORDER,
  DE_DATASETS, DE_VARIABLES_BY_DATASET,
  DE_GEO_LEVELS, violatesFloor,
  DE_SUPPRESSION, DE_SCREENS,
  DE_RESULT_ROWS, DE_COVERAGE_ROWS, DE_SYNTHETIC_ROWS,
  PrivacyChip, DEShell, ScreenJumpTweak,
  strictestClass, SuppressedCell, FloorViolationBanner,
  // Live-data wiring (US-DATA-EXP-001):
  useDeCatalogue, useDeDataset, useDeCoverage, useDeSynthetic,
  useDeMe, submitAggregate, submitHandoff,
  RoleGateBanner, HandoffPrompt,
});
