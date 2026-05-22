/* global React, Icon, Chip, PageHeader, KPI, useApi, useChoiceList */
// NSR MIS — Registry · Members listing (US-005 sibling)
// =========================================================
// Per-individual browse across every household in the registry.
// Sister view to RegistryScreen (the household list). Same chrome,
// same filter bar grammar, but rows are members.
//
// Live data:
//   GET /api/v1/data-management/members/?...        — list rows
//   GET /api/v1/data-management/members/aggregates/ — KPI strip
//   GET /api/v1/reference-data/geographic-units/?level=sub_region
//                                                  — sub-region picker
//   GET /api/v1/reference-data/choice-list-bundle/?lists=...
//                                                  — relationship + nin
//                                                    + sex pickers
//
// MemberSerializer (US-005) nests household_sub_region_name /
// district_name / parish_name / village_name / pmt_band so the row
// projection below can read location off each member without
// follow-up fetches.

const { useState: useStateMem, useMemo: useMemoMem } = React;

const _MEM_API_BASE = "/api/v1/data-management/members/";

const _memQS = (params) => {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params || {})) {
    if (v != null && v !== "") qs.set(k, String(v));
  }
  return qs.toString();
};

const _buildMemberListUrl = (filters, page, pageSize) => {
  const s = _memQS({ ...filters, page, page_size: pageSize });
  return s ? `${_MEM_API_BASE}?${s}` : _MEM_API_BASE;
};

const _buildMemberAggregatesUrl = (filters) => {
  const s = _memQS(filters);
  return s ? `${_MEM_API_BASE}aggregates/?${s}` : `${_MEM_API_BASE}aggregates/`;
};

// Backend stores Disability flag per domain on the Disability one-
// to-one (seeing/hearing/walking/memory/selfcare/communication). The
// row projection picks the FIRST domain with a code of 03/04 ("a
// lot of difficulty" / "cannot do at all") consistent with how
// wg_disability_flag is computed in apps.data_management.models.
const _DISAB_DOMAINS_ORDERED = [
  "seeing", "hearing", "walking", "memory", "selfcare", "communication",
];

const _worstDisabilityDomain = (disab) => {
  if (!disab || !disab.wg_disability_flag) return "none";
  for (const d of _DISAB_DOMAINS_ORDERED) {
    const v = disab[d];
    if (v === "03" || v === "04") return d;
  }
  return "none";
};

// Coarse age-band bucket. Mirrors apps.data_management.api._AGE_BANDS
// so the prototype's chips read the same buckets the server filters
// against.
const _ageBandFor = (years) => {
  if (years == null) return "";
  if (years < 5)  return "<5";
  if (years < 10) return "5-9";
  if (years < 15) return "10-14";
  if (years < 20) return "15-19";
  if (years < 30) return "20-29";
  if (years < 40) return "30-39";
  if (years < 50) return "40-49";
  if (years < 60) return "50-59";
  return "60+";
};

// Project a live Member payload (MemberSerializer shape) onto the
// row shape the existing Members table renders. Names follow the
// "<surname> <first_name>" convention used elsewhere in the harness.
// nin status carries the raw code; NinPill resolves the chip tone.
const _projectMember = (m) => ({
  id: m.id,
  line: m.line_number,
  name: `${m.surname || ""} ${m.first_name || ""}`.trim() || "—",
  rel: m.relationship_to_head || "",
  relLabel: m.relationship_to_head_label || m.relationship_to_head || "—",
  // ChoiceList: 1=Male, 2=Female. Keep the code on the row so the
  // sex chip stays in lockstep with the backend filter param.
  sex: m.sex || "",
  age: m.age_years,
  ageBand: _ageBandFor(m.age_years),
  ninStatus: m.nin_status || "",
  ninLast4: m.nin_last4 || "",
  // List-view PII rule (HANDOFF §4): NIN value is never serialised
  // by MemberSerializer.get_nin_value (returns null). The display
  // uses nin_last4 + the verified flag for an at-a-glance preview.
  disability: _worstDisabilityDomain(m.disability),
  householdId: m.household,
  subreg: m.household_sub_region_name || "",
  district: m.household_district_name || "",
  parish: m.household_parish_name || "",
  village: m.household_village_name || "",
  pmtBand: m.household_pmt_band || "",
  status: "Confirmed",  // post-promotion baseline (matches Household.status)
  lastUpdate: (m.updated_at || "").slice(0, 10),
  // ProgrammeEnrolment lives on Household — wire via a follow-up
  // when the serializer carries enrolment summary onto Member.
  programmes: [],
});

// Kept as a static fallback for the test export so any consumer
// that pulled MEMBERS off window still resolves to an empty list
// rather than undefined. The live screen no longer reads this.
const MEMBERS = [];

const _LEGACY_MEMBERS_UNUSED = [
  // Nsubuga household (Buganda South · Lyantonde · Kibalinga)
  { mid:"M-01KRPPW6WR-001", line:1, name:"Nsubuga Ruth",       rel:"Head",      sex:"F", age:42, ageBand:"40–49", nin:"verified", ninShort:"CM84050213ABCD", disability:"none", hh:"01KRPPW6WRGRJZY0N4XN8R1YC2", subreg:"Buganda South", district:"Lyantonde", parish:"Kibalinga", village:"Okello Village", pmtBand:"Poorest 40%", programmes:["OPM-PDM"],     status:"Confirmed", lastUpdate:"22 Apr 2026" },
  { mid:"M-01KRPPW6WR-002", line:2, name:"Tumusiime Samuel",   rel:"Spouse",    sex:"M", age:46, ageBand:"40–49", nin:"verified", ninShort:"CM80020412EFGH", disability:"none", hh:"01KRPPW6WRGRJZY0N4XN8R1YC2", subreg:"Buganda South", district:"Lyantonde", parish:"Kibalinga", village:"Okello Village", pmtBand:"Poorest 40%", programmes:["OPM-PDM"],     status:"Confirmed", lastUpdate:"22 Apr 2026" },
  { mid:"M-01KRPPW6WR-003", line:3, name:"Okello James",       rel:"Son",       sex:"M", age:14, ageBand:"10–14", nin:"pending",  ninShort:"—",              disability:"none", hh:"01KRPPW6WRGRJZY0N4XN8R1YC2", subreg:"Buganda South", district:"Lyantonde", parish:"Kibalinga", village:"Okello Village", pmtBand:"Poorest 40%", programmes:["OPM-PDM"],     status:"Confirmed", lastUpdate:"20 Apr 2026" },
  { mid:"M-01KRPPW6WR-006", line:6, name:"Achen Rebecca",      rel:"Daughter",  sex:"F", age:6,  ageBand:"5–9",   nin:"none",     ninShort:"—",              disability:"none", hh:"01KRPPW6WRGRJZY0N4XN8R1YC2", subreg:"Buganda South", district:"Lyantonde", parish:"Kibalinga", village:"Okello Village", pmtBand:"Poorest 40%", programmes:["OPM-PDM"],     status:"Confirmed", lastUpdate:"22 Apr 2026" },

  // Lokol household (Karamoja · Moroto)
  { mid:"M-01HXY7K3B2-001", line:1, name:"Lokol Naume",        rel:"Head",      sex:"F", age:31, ageBand:"30–39", nin:"verified", ninShort:"CM94070118JKLM", disability:"none",         hh:"01HXY7K3B2N9PVQE4M6FZRWS18", subreg:"Karamoja", district:"Moroto", parish:"Nakiloro", village:"Lopuwapuwa A", pmtBand:"Poorest 20%", programmes:[], status:"Provisional", lastUpdate:"14 May 2026" },
  { mid:"M-01HXY7K3B2-002", line:2, name:"Lokol Peter",        rel:"Son",       sex:"M", age:9,  ageBand:"5–9",   nin:"none",     ninShort:"—",              disability:"mobility",     hh:"01HXY7K3B2N9PVQE4M6FZRWS18", subreg:"Karamoja", district:"Moroto", parish:"Nakiloro", village:"Lopuwapuwa A", pmtBand:"Poorest 20%", programmes:[], status:"Provisional", lastUpdate:"14 May 2026" },
  { mid:"M-01HXY7K3B2-003", line:3, name:"Lokol Esther",       rel:"Daughter",  sex:"F", age:4,  ageBand:"<5",    nin:"none",     ninShort:"—",              disability:"none",         hh:"01HXY7K3B2N9PVQE4M6FZRWS18", subreg:"Karamoja", district:"Moroto", parish:"Nakiloro", village:"Lopuwapuwa A", pmtBand:"Poorest 20%", programmes:[], status:"Provisional", lastUpdate:"14 May 2026" },

  // Akello household (Acholi · Gulu)
  { mid:"M-01HXZ9MR4N-001", line:1, name:"Akello Grace",       rel:"Head",      sex:"F", age:35, ageBand:"30–39", nin:"verified", ninShort:"CM90031128NOPQ", disability:"none",   hh:"01HXZ9MR4N8P2QFB7K6FZRWS33", subreg:"Acholi", district:"Gulu", parish:"Pageya", village:"Aywee", pmtBand:"Poorest 40%", programmes:[], status:"Pending", lastUpdate:"14 May 2026" },
  { mid:"M-01HXZ9MR4N-002", line:2, name:"Akello Jenipher",    rel:"Daughter",  sex:"F", age:16, ageBand:"15–19", nin:"pending",  ninShort:"—",              disability:"none",   hh:"01HXZ9MR4N8P2QFB7K6FZRWS33", subreg:"Acholi", district:"Gulu", parish:"Pageya", village:"Aywee", pmtBand:"Poorest 40%", programmes:[], status:"Pending", lastUpdate:"14 May 2026" },
  { mid:"M-01HXZ9MR4N-003", line:3, name:"Akello Faith",       rel:"Daughter",  sex:"F", age:11, ageBand:"10–14", nin:"none",     ninShort:"—",              disability:"none",   hh:"01HXZ9MR4N8P2QFB7K6FZRWS33", subreg:"Acholi", district:"Gulu", parish:"Pageya", village:"Aywee", pmtBand:"Poorest 40%", programmes:[], status:"Pending", lastUpdate:"14 May 2026" },

  // Mukasa Patrick (West Nile · Arua)
  { mid:"M-01HXP02CN4-001", line:1, name:"Mukasa Patrick",     rel:"Head",      sex:"M", age:51, ageBand:"50–59", nin:"verified", ninShort:"CM75081401RSTU", disability:"none",        hh:"01HXP02CN4QFB7K6FZRWS00111", subreg:"West Nile", district:"Arua", parish:"Anyiribu", village:"Anyiribu A", pmtBand:"Poorest 40%", programmes:["NUSAF","OPM-PDM"], status:"Confirmed", lastUpdate:"03 May 2026" },
  { mid:"M-01HXP02CN4-002", line:2, name:"Mukasa Joyce",       rel:"Spouse",    sex:"F", age:48, ageBand:"40–49", nin:"verified", ninShort:"CM78110312VWXY", disability:"hearing",     hh:"01HXP02CN4QFB7K6FZRWS00111", subreg:"West Nile", district:"Arua", parish:"Anyiribu", village:"Anyiribu A", pmtBand:"Poorest 40%", programmes:["NUSAF","OPM-PDM"], status:"Confirmed", lastUpdate:"03 May 2026" },
  { mid:"M-01HXP02CN4-003", line:3, name:"Mukasa Daniel",      rel:"Son",       sex:"M", age:20, ageBand:"20–29", nin:"verified", ninShort:"CM06041122ZABC", disability:"none",        hh:"01HXP02CN4QFB7K6FZRWS00111", subreg:"West Nile", district:"Arua", parish:"Anyiribu", village:"Anyiribu A", pmtBand:"Poorest 40%", programmes:["OPM-PDM"], status:"Confirmed", lastUpdate:"03 May 2026" },

  // Onyango David
  { mid:"M-01HXP02CN5-001", line:1, name:"Onyango David",      rel:"Head",      sex:"M", age:39, ageBand:"30–39", nin:"verified", ninShort:"CM87021018DEFG", disability:"none",  hh:"01HXP02CN4QFB7K6FZRWS00118", subreg:"West Nile", district:"Arua", parish:"Logiri",   village:"Logiri Central", pmtBand:"Poorest 40%", programmes:[], status:"Pending", lastUpdate:"14 May 2026" },
  { mid:"M-01HXP02CN5-004", line:4, name:"Onyango Tabitha",    rel:"Daughter",  sex:"F", age:2,  ageBand:"<5",    nin:"none",     ninShort:"—",              disability:"none",  hh:"01HXP02CN4QFB7K6FZRWS00118", subreg:"West Nile", district:"Arua", parish:"Logiri",   village:"Logiri Central", pmtBand:"Poorest 40%", programmes:[], status:"Pending", lastUpdate:"14 May 2026" },

  // Mugisha James (Karamoja · Napak)
  { mid:"M-01HY02FNQ9-001", line:1, name:"Mugisha James",      rel:"Head",      sex:"M", age:44, ageBand:"40–49", nin:"verified", ninShort:"CM82051603HIJK", disability:"none",       hh:"01HY02FNQ9P8MN6FB7K6FZRWS67", subreg:"Karamoja", district:"Napak", parish:"Lokopo", village:"Lorengedwat", pmtBand:"Poorest 20%", programmes:[], status:"Pending", lastUpdate:"14 May 2026" },
  { mid:"M-01HY02FNQ9-002", line:2, name:"Mugisha Susan",      rel:"Spouse",    sex:"F", age:41, ageBand:"40–49", nin:"verified", ninShort:"CM85091921LMNO", disability:"seeing",     hh:"01HY02FNQ9P8MN6FB7K6FZRWS67", subreg:"Karamoja", district:"Napak", parish:"Lokopo", village:"Lorengedwat", pmtBand:"Poorest 20%", programmes:[], status:"Pending", lastUpdate:"14 May 2026" },

  // Auma Beatrice
  { mid:"M-01HY04MQR0-001", line:1, name:"Auma Beatrice",      rel:"Head",      sex:"F", age:38, ageBand:"30–39", nin:"verified", ninShort:"CM87090517PQRS", disability:"none",   hh:"01HY04MQR0N8P2FB7K6FZRWS73", subreg:"Karamoja", district:"Napak", parish:"Lokopo", village:"Apeitolim", pmtBand:"Poorest 40%", programmes:[], status:"Pending", lastUpdate:"14 May 2026" },
  { mid:"M-01HY04MQR0-005", line:5, name:"Auma Sarah",         rel:"Daughter",  sex:"F", age:13, ageBand:"10–14", nin:"none",     ninShort:"—",              disability:"cognition", hh:"01HY04MQR0N8P2FB7K6FZRWS73", subreg:"Karamoja", district:"Napak", parish:"Lokopo", village:"Apeitolim", pmtBand:"Poorest 40%", programmes:[], status:"Pending", lastUpdate:"14 May 2026" },

  // Lopuwa John
  { mid:"M-01HY09KRS1-001", line:1, name:"Lopuwa John",        rel:"Head",      sex:"M", age:36, ageBand:"30–39", nin:"verified", ninShort:"CM89030412TUVW", disability:"none",   hh:"01HY09KRS1P9MN6FB7K6FZRWS84", subreg:"Karamoja", district:"Moroto", parish:"Tapac", village:"Kakingol", pmtBand:"Poorest 40%", programmes:["OPM-PDM"], status:"Confirmed", lastUpdate:"11 May 2026" },

  // Acheng Rose (Acholi · Gulu)
  { mid:"M-01HY0AMNT8-001", line:1, name:"Acheng Rose",        rel:"Head",      sex:"F", age:64, ageBand:"60+",   nin:"verified", ninShort:"CM61081019XYZA", disability:"mobility", hh:"01HY0AMNT8P2N6FB7K6FZRWS92", subreg:"Acholi", district:"Gulu", parish:"Bobi", village:"Aywee", pmtBand:"Middle 40%", programmes:["NUSAF","SCG"], status:"Confirmed", lastUpdate:"30 Apr 2026" },
  { mid:"M-01HY0AMNT8-002", line:2, name:"Acheng Margaret",    rel:"Daughter",  sex:"F", age:32, ageBand:"30–39", nin:"verified", ninShort:"CM93040621BCDE", disability:"none",     hh:"01HY0AMNT8P2N6FB7K6FZRWS92", subreg:"Acholi", district:"Gulu", parish:"Bobi", village:"Aywee", pmtBand:"Middle 40%", programmes:["NUSAF"],       status:"Confirmed", lastUpdate:"30 Apr 2026" },

  // Byaruhanga Charles
  { mid:"M-01HX91KPN1-001", line:1, name:"Byaruhanga Charles", rel:"Head",      sex:"M", age:55, ageBand:"50–59", nin:"verified", ninShort:"CM70010505FGHI", disability:"none",         hh:"01HX91KPNRMQ0F2B7K6FZRWS10", subreg:"Buganda South", district:"Lyantonde", parish:"Kibalinga", village:"Okello Village", pmtBand:"Poorest 40%", programmes:["OPM-PDM"], status:"Confirmed", lastUpdate:"17 Mar 2026" },
  { mid:"M-01HX91KPN1-004", line:4, name:"Byaruhanga Doreen",  rel:"Daughter",  sex:"F", age:17, ageBand:"15–19", nin:"verified", ninShort:"CM08121113JKLM", disability:"none",         hh:"01HX91KPNRMQ0F2B7K6FZRWS10", subreg:"Buganda South", district:"Lyantonde", parish:"Kibalinga", village:"Okello Village", pmtBand:"Poorest 40%", programmes:["OPM-PDM"], status:"Confirmed", lastUpdate:"17 Mar 2026" },

  // Namutebi Sarah
  { mid:"M-01HX91KPN4-001", line:1, name:"Namutebi Sarah",     rel:"Head",      sex:"F", age:29, ageBand:"20–29", nin:"verified", ninShort:"CM96080318NOPQ", disability:"none",        hh:"01HX91KPNRMQ0F2B7K6FZRWS44", subreg:"Buganda South", district:"Lyantonde", parish:"Kibalinga", village:"Okello Village", pmtBand:"Poorest 20%", programmes:["OPM-PDM","WFP"], status:"Confirmed", lastUpdate:"21 Apr 2026" },
  { mid:"M-01HX91KPN4-002", line:2, name:"Namutebi Junior",    rel:"Son",       sex:"M", age:7,  ageBand:"5–9",   nin:"none",     ninShort:"—",              disability:"none",        hh:"01HX91KPNRMQ0F2B7K6FZRWS44", subreg:"Buganda South", district:"Lyantonde", parish:"Kibalinga", village:"Okello Village", pmtBand:"Poorest 20%", programmes:["OPM-PDM","WFP"], status:"Confirmed", lastUpdate:"21 Apr 2026" },

  // Apio Joyce (Lango · Lira)
  { mid:"M-01HX91KPN6-001", line:1, name:"Apio Joyce",         rel:"Head",      sex:"F", age:43, ageBand:"40–49", nin:"verified", ninShort:"CM82061818RSTU", disability:"none",       hh:"01HX91KPNRMQ0F2B7K6FZRWS66", subreg:"Lango", district:"Lira", parish:"Adekokwok", village:"Adekokwok B", pmtBand:"Poorest 40%", programmes:["NUSAF"], status:"Confirmed", lastUpdate:"08 May 2026" },
  { mid:"M-01HX91KPN6-002", line:2, name:"Apio Brian",         rel:"Son",       sex:"M", age:19, ageBand:"15–19", nin:"verified", ninShort:"CM07020412VWXY", disability:"none",       hh:"01HX91KPNRMQ0F2B7K6FZRWS66", subreg:"Lango", district:"Lira", parish:"Adekokwok", village:"Adekokwok B", pmtBand:"Poorest 40%", programmes:["NUSAF"], status:"Confirmed", lastUpdate:"08 May 2026" },
  { mid:"M-01HX91KPN6-005", line:5, name:"Apio Ruth",          rel:"Daughter",  sex:"F", age:3,  ageBand:"<5",    nin:"none",     ninShort:"—",              disability:"none",       hh:"01HX91KPNRMQ0F2B7K6FZRWS66", subreg:"Lango", district:"Lira", parish:"Adekokwok", village:"Adekokwok B", pmtBand:"Poorest 40%", programmes:["NUSAF"], status:"Confirmed", lastUpdate:"08 May 2026" },

  // Kintu Ronald
  { mid:"M-01HX91KPN7-001", line:1, name:"Kintu Ronald",       rel:"Head",      sex:"M", age:48, ageBand:"40–49", nin:"verified", ninShort:"CM77051929ZABC", disability:"none",      hh:"01HX91KPNRMQ0F2B7K6FZRWS77", subreg:"Buganda South", district:"Lyantonde", parish:"Kibalinga", village:"Lwemiyaga", pmtBand:"Poorest 40%", programmes:["OPM-PDM"], status:"Confirmed", lastUpdate:"14 Apr 2026" },
  { mid:"M-01HX91KPN7-006", line:6, name:"Kintu Aisha",        rel:"Daughter",  sex:"F", age:1,  ageBand:"<5",    nin:"none",     ninShort:"—",              disability:"none",      hh:"01HX91KPNRMQ0F2B7K6FZRWS77", subreg:"Buganda South", district:"Lyantonde", parish:"Kibalinga", village:"Lwemiyaga", pmtBand:"Poorest 40%", programmes:["OPM-PDM"], status:"Confirmed", lastUpdate:"14 Apr 2026" },

  // Tumuhairwe Peter
  { mid:"M-01HX91KPN5-001", line:1, name:"Tumuhairwe Peter",   rel:"Head",      sex:"M", age:65, ageBand:"60+",   nin:"verified", ninShort:"CM60101204DEFG", disability:"mobility",  hh:"01HX91KPNRMQ0F2B7K6FZRWS55", subreg:"Buganda South", district:"Lyantonde", parish:"Kasaana", village:"Kasaana A", pmtBand:"Middle 40%", programmes:["SCG"], status:"Confirmed", lastUpdate:"02 Feb 2026" },
  { mid:"M-01HX91KPN5-003", line:3, name:"Tumuhairwe Edith",   rel:"Daughter",  sex:"F", age:25, ageBand:"20–29", nin:"verified", ninShort:"CM00021105HIJK", disability:"none",      hh:"01HX91KPNRMQ0F2B7K6FZRWS55", subreg:"Buganda South", district:"Lyantonde", parish:"Kasaana", village:"Kasaana A", pmtBand:"Middle 40%", programmes:[],       status:"Confirmed", lastUpdate:"02 Feb 2026" },
];

// Age-band keys MUST match apps.data_management.api._AGE_BANDS so
// the dropdown round-trips cleanly through `?age_band=`.
const MEM_AGE_BANDS = ["<5", "5-9", "10-14", "15-19", "20-29", "30-39", "40-49", "50-59", "60+"];

// nin_status code → chip tone + icon. ChoiceList seed (US-S22-005c):
// 1=has_card (verified), 2=lost, 3=not_issued (pending), 4=no, 8=unknown.
const _NIN_CHIP = {
  "1": { tone:"data",    icon:"check" },
  "2": { tone:"quality", icon:"alert" },
  "3": { tone:"quality", icon:"clock" },
  "4": { tone:"neutral", icon:"minus" },
  "8": { tone:"neutral", icon:"minus" },
};

// NinPill — code-driven. `status` is the raw ChoiceList code; `label`
// is the resolved label from MemberSerializer.nin_status_label (or a
// hardcoded fallback). `ninLast4` shows only when verified so the
// list view satisfies HANDOFF §4 (sensitive: redacted in list).
const NinPill = ({ status, label, ninLast4 }) => {
  const m = _NIN_CHIP[status] || _NIN_CHIP["8"];
  return (
    <div style={{display:"flex", flexDirection:"column", gap:2, minWidth:0}}>
      <Chip size="sm" tone={m.tone}>
        <Icon name={m.icon} size={10}/> {label || status || "—"}
      </Chip>
      {status === "1" && ninLast4 && (
        <span className="t-mono t-cap" style={{fontSize:10, color:"var(--neutral-500)", letterSpacing:"0.02em"}}>
          ••••{ninLast4}
        </span>
      )}
    </div>
  );
};

// DisabilityPill — `kind` is one of the WG-SS domain names returned
// by _worstDisabilityDomain (`seeing`, `hearing`, `walking`, etc.)
// or `none`.
const DisabilityPill = ({ kind }) => {
  if (kind === "none" || !kind) return <span className="muted t-cap">none</span>;
  return <Chip size="sm" tone="quality" title={`Washington Group: a lot of difficulty (${kind}).`}>
    <Icon name="shield" size={10}/> {kind}
  </Chip>;
};

const MembersListView = ({ onOpenHousehold, onOpenMember }) => {
  const [q, setQ] = useStateMem("");
  // Filters are keyed off the same codes the backend accepts so the
  // URL is round-trippable. sex/nin_status carry ChoiceList codes;
  // sub_region carries GeographicUnit.code; relationship_to_head
  // carries the relationship code.
  const [sex, setSex] = useStateMem("");
  const [ageBand, setAgeBand] = useStateMem("");
  const [rel, setRel] = useStateMem("");
  const [subreg, setSubreg] = useStateMem("");
  const [disab, setDisab] = useStateMem("");
  const [nin, setNin] = useStateMem("");
  const [prog, setProg] = useStateMem("");
  const [sortBy, setSortBy] = useStateMem("lastUpdate");
  const [page, setPage] = useStateMem(0);
  const pageSize = 12;

  const _filters = {
    q,
    sex,
    age_band: ageBand,
    relationship_to_head: rel,
    sub_region: subreg,
    disability: disab,
    nin_status: nin,
    programme: prog,
  };
  const _orderingMap = {
    lastUpdate: "-updated_at",
    name: "surname",
    ageAsc: "age_years",
    ageDesc: "-age_years",
  };
  const listUrl = _buildMemberListUrl(
    { ..._filters, ordering: _orderingMap[sortBy] || undefined },
    page + 1, pageSize,
  );
  const aggUrl = _buildMemberAggregatesUrl(_filters);

  const [listResp, listMeta] = useApi(listUrl);
  const [aggResp] = useApi(aggUrl);
  const [subregResp] = useApi(
    "/api/v1/reference-data/geographic-units/?level=sub_region&status=active&page_size=500",
  );

  // Choice-list pickers — relationship_to_head + nin_status + sex.
  // The useChoiceList hook caches the bundle by ETag (US-S23-012).
  const [, , clMeta] = useChoiceList
    ? useChoiceList(["relationship_to_head", "nin_status", "sex"])
    : [[], {}, {}];
  const relOptions = (clMeta && clMeta.allLists && clMeta.allLists.relationship_to_head) || [];
  const ninOptions = (clMeta && clMeta.allLists && clMeta.allLists.nin_status) || [];
  const sexOptions = (clMeta && clMeta.allLists && clMeta.allLists.sex) || [];

  const liveRows = ((listResp && listResp.results) || []).map(_projectMember);
  const liveCount = (listResp && typeof listResp.count === "number")
    ? listResp.count
    : liveRows.length;
  const totalPages = Math.max(1, Math.ceil(liveCount / pageSize));

  const subregs = (subregResp && subregResp.results) || subregResp || [];

  const reset = () => {
    setQ(""); setSex(""); setAgeBand(""); setRel(""); setSubreg("");
    setDisab(""); setNin(""); setProg(""); setPage(0);
  };

  // KPIs read off the aggregates endpoint — same filter params, so
  // the strip reflects the visible slice (HANDOFF §5).
  const total = aggResp?.total_individuals ?? 0;
  const under18 = aggResp?.children_under_18 ?? 0;
  const elder60 = aggResp?.elderly_60_plus ?? 0;
  const withDis = aggResp?.with_disability_wgss ?? 0;
  const female = aggResp?.female ?? 0;
  const ninVer = aggResp?.nin_verified ?? 0;

  const activeFilters = [q, sex, ageBand, rel, subreg, disab, nin, prog].filter(Boolean);

  return (
    <div>
      {/* Headline KPIs — registry-wide numbers, not the demo sample */}
      <div className="grid grid-4">
        <KPI title="Total individuals"
             value="48,116,802"
             foot={`Sample: ${total.toLocaleString()} rows · avg HH size 4.89`}
             spark={[40,42,43,44,45,46,47,48]}/>
        <KPI title="Children under 18"
             value="22,140,389"
             trend="up" trendValue="46%"
             foot={`Sample: ${under18} of ${total} (${Math.round(under18/total*100)}%)`}
             spark={[19,19,20,20,21,21,22,22]}/>
        <KPI title="Elderly 60+"
             value="3,071,540"
             foot={`Sample: ${elder60} of ${total} · SCG eligibility cohort`}
             spark={[2.4,2.5,2.6,2.7,2.8,2.9,3.0,3.07]}/>
        <KPI title="With disability (WG-SS)"
             value="1,809,408"
             trend="up" trendValue="3.8%"
             foot={`Sample: ${withDis} of ${total} flagged`}
             spark={[1.3,1.4,1.5,1.6,1.7,1.7,1.8,1.81]}/>
      </div>

      {/* Filter bar */}
      <div className="card mt-5" style={{padding:'14px 16px'}}>
        <div className="row gap-3" style={{flexWrap:'wrap'}}>
          <div className="search" style={{maxWidth:380, height:34, background:'var(--neutral-0)'}}>
            <Icon name="search" size={16} color="var(--neutral-500)"/>
            <input value={q} onChange={(e) => { setQ(e.target.value); setPage(0); }}
              placeholder="Search by name, NIN, household ID, parish…"/>
          </div>

          <select className="field-select" style={{height:34, width:'auto', minWidth:110}} value={sex} onChange={(e) => { setSex(e.target.value); setPage(0); }}>
            <option value="">Any sex</option>
            {sexOptions.length
              ? sexOptions.map(o => <option key={o.code} value={o.code}>{o.label}</option>)
              : <><option value="2">Female</option><option value="1">Male</option></>}
          </select>
          <select className="field-select" style={{height:34, width:'auto', minWidth:130}} value={ageBand} onChange={(e) => { setAgeBand(e.target.value); setPage(0); }}>
            <option value="">Any age band</option>
            {MEM_AGE_BANDS.map(b => <option key={b} value={b}>{b}</option>)}
          </select>
          <select className="field-select" style={{height:34, width:'auto', minWidth:170}} value={rel} onChange={(e) => { setRel(e.target.value); setPage(0); }}>
            <option value="">Any relationship</option>
            {relOptions.map(o => <option key={o.code} value={o.code}>{o.label}</option>)}
          </select>
          <select className="field-select" style={{height:34, width:'auto', minWidth:200}} value={subreg} onChange={(e) => { setSubreg(e.target.value); setPage(0); }}>
            <option value="">Any sub-region</option>
            {subregs.map(s => <option key={s.id || s.code} value={s.code}>{s.name}</option>)}
          </select>
          <select className="field-select" style={{height:34, width:'auto', minWidth:150}} value={disab} onChange={(e) => { setDisab(e.target.value); setPage(0); }}>
            <option value="">Any disability</option>
            <option value="any">Any flag set</option>
            <option value="seeing">Seeing</option>
            <option value="hearing">Hearing</option>
            <option value="walking">Walking</option>
            <option value="memory">Memory</option>
            <option value="selfcare">Self-care</option>
            <option value="communication">Communication</option>
          </select>
          <select className="field-select" style={{height:34, width:'auto', minWidth:140}} value={nin} onChange={(e) => { setNin(e.target.value); setPage(0); }}>
            <option value="">Any NIN status</option>
            {ninOptions.length
              ? ninOptions.map(o => <option key={o.code} value={o.code}>{o.label}</option>)
              : <>
                  <option value="1">Verified</option>
                  <option value="3">Pending</option>
                  <option value="4">No NIN</option>
                  <option value="8">Unknown</option>
                </>}
          </select>
          <input
            type="text" value={prog}
            onChange={(e) => { setProg(e.target.value); setPage(0); }}
            placeholder="Programme code (HH)"
            className="field-input"
            style={{height:34, width:'auto', minWidth:160}}/>

          <div style={{flex:1}}/>
          <button className="btn btn-sm btn-ghost" onClick={reset}><Icon name="x" size={13}/> Reset</button>
          <div style={{width:1, height:24, background:'var(--neutral-200)'}}/>
          <span className="t-cap">Sort:</span>
          <select className="field-select" style={{height:30, width:'auto'}} value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
            <option value="lastUpdate">Most recent</option>
            <option value="name">Name (A→Z)</option>
            <option value="ageAsc">Age (young→old)</option>
            <option value="ageDesc">Age (old→young)</option>
          </select>
        </div>
      </div>

      {/* Active filter chips */}
      {activeFilters.length > 0 && (
        <div className="row gap-2 mt-3" style={{flexWrap:'wrap'}}>
          <span className="t-cap">Active filters:</span>
          {q && <Chip size="sm">"{q}"</Chip>}
          {sex && <Chip size="sm">{
            sexOptions.find(o => o.code === sex)?.label
              || (sex === "1" ? "Male" : sex === "2" ? "Female" : sex)
          }</Chip>}
          {ageBand && <Chip size="sm">Age {ageBand}</Chip>}
          {rel && <Chip size="sm">{
            relOptions.find(o => o.code === rel)?.label || rel
          }</Chip>}
          {subreg && <Chip size="sm">{
            subregs.find(s => s.code === subreg)?.name || subreg
          }</Chip>}
          {disab && <Chip size="sm" tone="quality">Disability: {disab}</Chip>}
          {nin && <Chip size="sm">NIN: {
            ninOptions.find(o => o.code === nin)?.label || nin
          }</Chip>}
          {prog && <Chip size="sm" tone="programme">{prog}</Chip>}
        </div>
      )}

      {/* Results table */}
      <div className="card mt-4">
        <div className="card-toolbar">
          <strong className="t-bodysm">{liveCount.toLocaleString()} members</strong>
          <span className="t-cap">
            {listMeta.loading ? "Loading…" : `Page ${page+1} of ${totalPages} · click any row to open the member record`}
          </span>
          <div style={{flex:1}}/>
          <span className="t-cap" style={{display:"flex", alignItems:"center", gap:6}}>
            <span style={{width:8, height:8, borderRadius:2, background:"var(--accent-system)"}}/>
            {female} F · {total - female} M
          </span>
          <div style={{width:1, height:18, background:'var(--neutral-200)'}}/>
          <span className="t-cap" style={{display:"flex", alignItems:"center", gap:6}}>
            <Icon name="check" size={11} color="var(--accent-data)"/>
            {ninVer} NIN-verified {total ? `(${Math.round(ninVer/total*100)}%)` : ""}
          </span>
          <button className="btn btn-sm btn-ghost"><Icon name="sliders" size={14}/> Columns</button>
        </div>
        {listMeta.error && (
          <div style={{padding:'12px 16px', color:'var(--accent-danger)'}} className="t-bodysm">
            Couldn’t load members: {listMeta.error}
          </div>
        )}
        <table className="tbl">
          <thead>
            <tr>
              <th>Member ID</th>
              <th>Name</th>
              <th>Sex</th>
              <th>Age</th>
              <th>Relationship</th>
              <th>NIN</th>
              <th>Disability</th>
              <th>Household</th>
              <th>Location</th>
              <th>Programmes (HH)</th>
              <th className="col-actions"></th>
            </tr>
          </thead>
          <tbody>
            {liveRows.length === 0 && !listMeta.loading && (
              <tr><td colSpan={11} style={{padding:'20px', textAlign:'center'}} className="muted t-bodysm">
                No members match the current filters.
              </td></tr>
            )}
            {liveRows.map(m => (
              <tr key={m.id} style={{cursor:'pointer'}} onClick={() => onOpenMember?.(m.id)}>
                <td className="col-id">{m.id.slice(0, 16)}…</td>
                <td>
                  <div className="row gap-3">
                    <div style={{
                      width:28, height:28, borderRadius:'50%',
                      background: m.sex === '2' ? 'var(--accent-eligibility-bg, var(--primary-100))' : 'var(--primary-100)',
                      color: 'var(--primary-900)',
                      display:'grid', placeItems:'center', fontSize:11, fontWeight:600,
                    }}>{m.name !== "—" ? m.name.split(' ').map(w => w[0]).slice(0,2).join('') : "—"}</div>
                    <div style={{minWidth:0}}>
                      <div style={{fontWeight: m.rel === "01" ? 600 : 500, whiteSpace:'nowrap'}}>
                        {m.name}
                        {m.rel === "01" && (
                          <span className="t-cap" style={{marginLeft:8, color:'var(--accent-identity, var(--primary-900))'}}>head</span>
                        )}
                      </div>
                      <div className="t-cap">line {m.line} · {m.status}</div>
                    </div>
                  </div>
                </td>
                <td><Chip size="sm">{m.sex === "2" ? "F" : m.sex === "1" ? "M" : "—"}</Chip></td>
                <td>
                  <div className="t-num" style={{fontWeight:500}}>{m.age != null ? m.age : "—"}</div>
                  <div className="t-cap">{m.ageBand}</div>
                </td>
                <td className="t-bodysm">{m.relLabel}</td>
                <td><NinPill status={m.ninStatus} label={
                  ninOptions.find(o => o.code === m.ninStatus)?.label
                } ninLast4={m.ninLast4}/></td>
                <td><DisabilityPill kind={m.disability}/></td>
                <td onClick={(e) => { e.stopPropagation(); onOpenHousehold?.(m.householdId); }}
                    style={{cursor:'pointer'}} title="Open household detail">
                  <div className="t-mono" style={{fontSize:11, color:'var(--accent-system, var(--primary-900))', whiteSpace:'nowrap'}}>
                    {m.householdId ? `${m.householdId.slice(0, 16)}…` : "—"}
                  </div>
                  <div className="t-cap">{m.pmtBand || "—"}</div>
                </td>
                <td>
                  <div className="t-bodysm" style={{whiteSpace:'nowrap'}}>{m.parish || "—"} · {m.district || "—"}</div>
                  <div className="t-cap">{m.subreg || "—"} · {m.village || "—"}</div>
                </td>
                <td>
                  {m.programmes.length === 0
                    ? <span className="muted t-cap">—</span>
                    : <div className="row-wrap">{m.programmes.map(p => <Chip key={p} size="sm" tone="programme">{p}</Chip>)}</div>}
                </td>
                <td className="col-actions"><Icon name="chevronRight" size={16} color="var(--neutral-500)"/></td>
              </tr>
            ))}
          </tbody>
        </table>

        {/* Pagination */}
        <div className="row gap-2" style={{padding:'12px 16px', borderTop:'1px solid var(--neutral-200)', justifyContent:'space-between'}}>
          <span className="t-cap">
            {liveCount === 0
              ? "0 results"
              : `Showing ${page*pageSize + 1}–${Math.min((page+1)*pageSize, liveCount)} of ${liveCount.toLocaleString()}`}
          </span>
          <div className="row gap-2">
            <button className="btn btn-sm" disabled={page === 0} onClick={() => setPage(0)}><Icon name="chevronsLeft" size={14}/></button>
            <button className="btn btn-sm" disabled={page === 0} onClick={() => setPage(p => p - 1)}><Icon name="chevronLeft" size={14}/></button>
            <span className="t-bodysm" style={{padding:'0 8px'}}>{page+1} / {totalPages}</span>
            <button className="btn btn-sm" disabled={page >= totalPages - 1} onClick={() => setPage(p => p + 1)}><Icon name="chevronRight" size={14}/></button>
            <button className="btn btn-sm" disabled={page >= totalPages - 1} onClick={() => setPage(totalPages - 1)}><Icon name="chevronsRight" size={14}/></button>
          </div>
        </div>
      </div>

      <div className="t-cap mt-4" style={{textAlign:'center'}}>
        Read-only registry view (AC-UPD-VERSION). All edits open a UPD ChangeRequest against the
        member's household. Audit chain available under the household's Audit tab.
      </div>
    </div>
  );
};

Object.assign(window, { MembersListView, MEMBERS });
