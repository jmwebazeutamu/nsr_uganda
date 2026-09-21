/* global window */
// Household review model — one shape out of two shapes in
// =====================================================
// The DIH review rail showed a summary and a roster. Everything else
// the questionnaire collects — health, education, employment, housing,
// utilities, livelihood, assets, crops, livestock, food security,
// shocks, coping — was in `canonical_payload` and on no screen at all.
// An operator deciding whether to promote a household into the national
// registry could not see most of what had been collected about it.
//
// THE COMPLICATION
// ----------------
// `canonical_payload` is not canonical. Two producers write two
// incompatible shapes under the same name:
//
//   Kobo / bulk connectors      parish capture wizard
//   --------------------------  ---------------------------------
//   interview: {...}            (respondent fields inline)
//   agriculture: {...}          housing.livelihood: {...}
//   food_security: {fies, ...}  food_shocks.food_security: {...}
//   shocks_coping: {...}        food_shocks.shocks / .coping
//   housing: FLAT               housing.dwelling / .utilities
//   member.health               health: { "<line>": {...} }
//
// A review written against either one is blind to the other — 377
// records or 4, depending which you pick. So the payload is normalised
// into ONE review model here, the same move as
// normalise_geographic_keys and attach_per_member_details.
//
// THE RULE THAT MATTERS
// ---------------------
// Nothing is dropped. A screen whose entire purpose is "let me see what
// was collected, so I can spot what the rules missed" cannot quietly
// omit a field it does not recognise — that is precisely where an
// anomaly would hide. Anything the model does not have a home for is
// collected into an "Other collected data" section and shown raw.
//
// `reviewCoverage()` proves it: it walks every leaf in the payload and
// every leaf in the model and asserts they are the same set. The test
// suite runs it over real payloads of both shapes.

//: Keys that are lineage or bookkeeping rather than answers. Shown, but
//: in their own section, so they do not dilute the questionnaire.
const LINEAGE_KEYS = new Set(["_source_keys", "_labels"]);

//: snake_case / kobo-ish keys → readable. Unknown keys are humanised
//: rather than hidden, so a new question appears the day it arrives.
const FIELD_LABELS = {
  // interview / respondent
  start: "Interview started", end: "Interview ended",
  interviewer: "Interviewer", supervisor: "Supervisor",
  deviceid: "Device", hh_size: "Reported household size",
  head_name: "Head of household (as stated)",
  respondent_name: "Respondent", respondent_phone: "Respondent phone",
  interview_result: "Interview result", consent: "Consent",
  contact_phone: "Household contact number",
  reported_household_size: "Reported household size",
  source_channel: "Capture channel",
  // location
  address_narrative: "Address narrative", urban_rural: "Urban / rural",
  gps_lat: "Latitude", gps_lng: "Longitude", gps_accuracy_m: "GPS accuracy (m)",
  // dwelling
  tenure: "Tenure", dwelling_type: "Dwelling type",
  rooms_total: "Rooms (total)", total_rooms: "Rooms (total)",
  sleeping_rooms: "Sleeping rooms", roof_material: "Roof material",
  wall_material: "Wall material", floor_material: "Floor material",
  // utilities
  cooking_fuel: "Cooking fuel", lighting_energy: "Lighting",
  water_source: "Drinking water source", drinking_water_source: "Drinking water source",
  toilet_type: "Toilet facility", toilet_facility: "Toilet facility",
  share_toilet: "Toilet shared?", toilet_shared: "Toilet shared?",
  households_sharing_toilet: "Households sharing toilet",
  waste_disposal: "Waste disposal",
  // livelihood / agriculture
  main_livelihood: "Main livelihood", land_ownership: "Land ownership",
  land_title: "Land title", land_hectares: "Land (hectares)",
  ag_purpose: "Agricultural purpose", agricultural_purpose: "Agricultural purpose",
  crop_production: "Crop production", crops_grown: "Crops grown",
  livestock: "Livestock", livestock_counts: "Livestock counts",
  assets_owned: "Assets owned", asset_counts: "Asset counts",
  // per-member
  chronic_illness_flag: "Has chronic illness?",
  chronic_illness_types: "Chronic illness types",
  literacy_status: "Literacy", ever_attended: "Ever attended school?",
  highest_grade: "Highest grade", currently_attending: "Currently attending?",
  why_stopped: "Reason stopped school", never_attended_reason: "Reason never attended",
  main_activity_last_30d: "Main activity (30d)", work_frequency: "Work frequency",
  sector: "Sector", employment_status: "Employment status",
  not_working_reason: "Reason not working", made_savings: "Made savings?",
  savings_location: "Savings location",
  seeing: "Seeing", hearing: "Hearing", walking: "Walking / climbing",
  memory: "Remembering / concentrating", selfcare: "Self-care",
  communication: "Communicating",
};

//: field → seeded ChoiceList, so a stored code can be shown as what it
//: means. A field absent here renders its raw value, never a guess.
const FIELD_CHOICE_LISTS = {
  urban_rural: "rural_urban", tenure: "dwelling_tenure",
  dwelling_type: "dwelling_type", roof_material: "roof_material",
  wall_material: "wall_material", floor_material: "floor_material",
  cooking_fuel: "cooking_fuel", lighting_energy: "lighting_energy",
  water_source: "drinking_water_source", drinking_water_source: "drinking_water_source",
  toilet_type: "toilet_facility", toilet_facility: "toilet_facility",
  waste_disposal: "waste_disposal", main_livelihood: "main_livelihood",
  land_ownership: "land_ownership", land_title: "land_title",
  ag_purpose: "agricultural_purpose", agricultural_purpose: "agricultural_purpose",
  literacy_status: "literacy_status", highest_grade: "highest_grade",
  why_stopped: "why_stopped_school", never_attended_reason: "never_attended_reason",
  main_activity_last_30d: "employment_main_activity", work_frequency: "work_frequency",
  sector: "employment_sector", employment_status: "employment_status",
  not_working_reason: "not_working_reason", savings_location: "savings_location",
  chronic_illness_flag: "yes_no", ever_attended: "yes_no",
  currently_attending: "yes_no", made_savings: "yes_no",
  share_toilet: "yes_no", toilet_shared: "yes_no", consent: "yes_no",
  sex: "sex", relationship_to_head: "relationship",
  marital_status: "marital_status", nationality: "nationality",
  residency_status: "residency_status", nin_status: "nin_status",
  birth_certificate_status: "birth_certificate",
  seeing: "wg_difficulty_level", hearing: "wg_difficulty_level",
  walking: "wg_difficulty_level", memory: "wg_difficulty_level",
  selfcare: "wg_difficulty_level", communication: "wg_difficulty_level",
  shock_type: "shock_type", severity: "severity_level",
  strategy_type: "coping_strategy_type", frequency: "coping_frequency",
  asset_type: "asset_type", crop_name: "crop_name", livestock_type: "livestock_type",
};

/** "sleeping_rooms" → "Sleeping rooms". Never returns empty. */
const humaniseKey = (key) => {
  if (FIELD_LABELS[key]) return FIELD_LABELS[key];
  const words = String(key).replace(/^_+/, "").split(/[._]+/).filter(Boolean);
  if (!words.length) return String(key);
  const first = words[0];
  return [first.charAt(0).toUpperCase() + first.slice(1), ...words.slice(1)].join(" ");
};

const isEmpty = (v) =>
  v === null || v === undefined || v === "" ||
  (Array.isArray(v) && v.length === 0) ||
  (typeof v === "object" && !Array.isArray(v) && Object.keys(v).length === 0);

/** Flatten an object into review rows, recursing into nested objects.
 *  `prefix` builds the dotted path the edit endpoint speaks. */
const rowsFrom = (obj, prefix, { skip = new Set() } = {}) => {
  const rows = [];
  if (!obj || typeof obj !== "object") return rows;
  for (const [key, value] of Object.entries(obj)) {
    if (skip.has(key)) continue;
    const path = prefix ? `${prefix}.${key}` : key;
    if (value && typeof value === "object" && !Array.isArray(value)) {
      rows.push(...rowsFrom(value, path, { skip }));
      continue;
    }
    rows.push({
      path,
      key,
      label: humaniseKey(key),
      value,
      choiceList: FIELD_CHOICE_LISTS[key] || null,
      empty: isEmpty(value),
    });
  }
  return rows;
};

/** A repeat group (assets, crops, livestock, shocks, coping) as a table. */
const tableFrom = (list, prefix) => {
  if (!Array.isArray(list) || list.length === 0) return null;
  const columns = [...new Set(list.flatMap(r => Object.keys(r || {})))];
  return {
    columns: columns.map(c => ({ key: c, label: humaniseKey(c), choiceList: FIELD_CHOICE_LISTS[c] || null })),
    rows: list.map((r, i) => ({ _index: i, _path: `${prefix}.${i}`, ...(r || {}) })),
  };
};

/* ───────────────────────────────────────────────────────────────
   Household composition — the "flags" an operator verifies
   ───────────────────────────────────────────────────────────────
   Derived from the roster, not asked. These are the characteristics
   that drive programme targeting, so an operator checking a record
   needs to see BOTH the conclusion and the roster it came from — the
   two are shown together for exactly that reason.

   Thresholds follow the seeded DQA rules (head >= 12 is AC-HOH-AGE;
   12-17 is AC-HOH-AGE-CHILD-LED). Where the questionnaire does not
   establish something, the answer is "unknown", never a default. */

const composition = (members) => {
  const list = Array.isArray(members) ? members.filter(Boolean) : [];
  const age = (m) => (m.age_years === null || m.age_years === undefined || m.age_years === "")
    ? null : Number(m.age_years);
  const head = list.find(m => m.is_head === true)
    || list.find(m => String(m.relationship_to_head || "") === "01")
    || null;
  const headAge = head ? age(head) : null;
  const ages = list.map(age);
  const known = ages.filter(a => a !== null && !Number.isNaN(a));
  const under18 = known.filter(a => a < 18).length;
  const over59 = known.filter(a => a >= 60).length;
  const working = known.filter(a => a >= 18 && a < 60).length;
  const unknownAges = ages.length - known.length;

  const flag = (label, value, detail) => ({ label, value, detail });
  return [
    flag("Household size", list.length,
         "Members on the roster. The reported size, where the interview "
         + "recorded one, is shown in the Interview section — the two "
         + "disagreeing is what AC-MEMBER-COUNT-MATCH exists to raise."),
    flag("Head of household",
         head ? `${(head.first_name || "")} ${(head.surname || "")}`.trim() || "(unnamed)" : "none designated",
         head ? "" : "No member is flagged as head — AC-HOH-EXISTS blocks promotion."),
    flag("Head's age", headAge === null ? "unknown" : headAge,
         headAge === null ? "No age or date of birth recorded for the head."
         : headAge < 12 ? "Under 12 — AC-HOH-AGE blocks promotion."
         : headAge < 18 ? "12–17: child-headed household (AC-HOH-AGE-CHILD-LED)."
         : headAge >= 60 ? "60 or over: elderly-headed household." : ""),
    flag("Child-headed", headAge === null ? "unknown" : (headAge >= 12 && headAge < 18 ? "yes" : "no"), ""),
    flag("Elderly-headed", headAge === null ? "unknown" : (headAge >= 60 ? "yes" : "no"), ""),
    flag("Members under 18", unknownAges ? `${under18} (+${unknownAges} age unknown)` : under18, ""),
    flag("Members 60 and over", unknownAges ? `${over59} (+${unknownAges} age unknown)` : over59, ""),
    flag("Dependency ratio",
         working > 0 ? ((under18 + over59) / working).toFixed(2)
         : (under18 + over59) > 0 ? "no working-age members" : "unknown",
         "Dependants (under 18 or 60+) per working-age member. "
         + (unknownAges ? `${unknownAges} member(s) have no age, so this is a floor, not a fact.` : "")),
  ];
};

/* ───────────────────────────────────────────────────────────────
   The model
   ─────────────────────────────────────────────────────────────── */

const SECTION_SPECS = [
  { id: "interview", title: "Interview & respondent",
    from: (p) => rowsFrom(p.interview, "interview")
      .concat(rowsFrom({
        respondent_name: p.respondent_name, contact_phone: p.contact_phone,
        consent: p.consent, source_channel: p.source_channel,
        reported_household_size: p.reported_household_size,
      }, ""))
      // Per-purpose consent. Claimed by this section and, until the
      // coverage check said so, never actually rendered — eleven
      // consent decisions an operator could not see on the screen
      // built for seeing everything.
      .concat(rowsFrom(p.consent_block, "consent_block")),
    claims: ["interview", "respondent_name", "contact_phone", "consent",
             "source_channel", "reported_household_size", "consent_block"] },

  { id: "location", title: "Location",
    from: (p) => rowsFrom(p.geographic, "geographic", { skip: new Set(["_labels"]) })
      .concat(rowsFrom({
        address_narrative: p.address_narrative, urban_rural: p.urban_rural,
        gps_lat: p.gps_lat, gps_lng: p.gps_lng, gps_accuracy_m: p.gps_accuracy_m,
      }, "")),
    claims: ["geographic", "address_narrative", "urban_rural",
             "gps_lat", "gps_lng", "gps_accuracy_m"] },

  { id: "housing", title: "Dwelling & utilities",
    // Flat (Kobo) and nested (wizard) both land here.
    from: (p) => {
      const h = p.housing || {};
      return rowsFrom(h.dwelling, "housing.dwelling")
        .concat(rowsFrom(h.utilities, "housing.utilities"))
        .concat(rowsFrom(h, "housing", {
          // `assets` / `crops` / `livestock` are repeat groups and get
          // their own tables. `asset_counts` is NOT a repeat group —
          // it is an object of item → count, so it renders as rows
          // here. Skipping it lost it entirely.
          skip: new Set(["dwelling", "utilities", "livelihood",
                         "assets", "crops", "livestock"]),
        }));
    },
    claims: ["housing"] },

  { id: "livelihood", title: "Livelihood & agriculture",
    from: (p) => rowsFrom((p.housing || {}).livelihood, "housing.livelihood")
      .concat(rowsFrom(p.agriculture, "agriculture")),
    claims: ["agriculture"] },

  { id: "food", title: "Food security",
    from: (p) => rowsFrom((p.food_shocks || {}).food_security, "food_shocks.food_security")
      .concat(rowsFrom((p.food_shocks || {}).food_consumption, "food_shocks.food_consumption"))
      .concat(rowsFrom((p.food_security || {}).fies, "food_security.fies"))
      .concat(rowsFrom((p.food_security || {}).food_groups, "food_security.food_groups"))
      .concat(rowsFrom(p.food_security, "food_security", {
        skip: new Set(["fies", "food_groups"]),
      })),
    claims: ["food_security"] },

  { id: "shocks", title: "Shocks & coping",
    from: (p) => rowsFrom((p.shocks_coping || {}).coping, "shocks_coping.coping")
      .concat(rowsFrom((p.shocks_coping || {}).shocks, "shocks_coping.shocks"))
      .concat(rowsFrom(p.shocks_coping, "shocks_coping", {
        skip: new Set(["coping", "shocks"]),
      })),
    claims: ["shocks_coping"] },
];

//: Repeat groups, rendered as tables rather than key/value rows.
const TABLE_SPECS = [
  { id: "assets", title: "Assets owned", get: (p) => (p.housing || {}).assets, path: "housing.assets" },
  { id: "crops", title: "Crops grown", get: (p) => (p.housing || {}).crops, path: "housing.crops" },
  { id: "livestock", title: "Livestock", get: (p) => (p.housing || {}).livestock, path: "housing.livestock" },
  { id: "shock_rows", title: "Shock events", get: (p) => (p.food_shocks || {}).shocks, path: "food_shocks.shocks" },
  { id: "coping_rows", title: "Coping strategies", get: (p) => (p.food_shocks || {}).coping, path: "food_shocks.coping" },
];

/** Per-member detail, from whichever shape the payload uses. */
const memberDetail = (payload, member, index) => {
  const line = member.line_number;
  const keyed = (section) => {
    const bag = payload[section];
    if (!bag || typeof bag !== "object" || Array.isArray(bag)) return null;
    return bag[String(line)] ?? bag[line] ?? null;
  };
  const sections = [];
  for (const [name, title] of [
    ["health", "Health"], ["disability", "Disability (Washington Group)"],
    ["education", "Education"], ["employment", "Employment"],
  ]) {
    // On the member (Kobo) or in a top-level bag keyed by line (wizard).
    const onMember = member[name];
    const topLevel = keyed(name);
    // The wizard wraps health as {health:{...}, disability:{...}}.
    const wrapped = keyed("health");
    const source = onMember
      || topLevel
      || (wrapped && typeof wrapped === "object" ? wrapped[name] : null);
    if (!source || typeof source !== "object") continue;
    const prefix = onMember
      ? `members.${index}.${name}`
      : topLevel ? `${name}.${line}`
      : `health.${line}.${name}`;
    const rows = rowsFrom(source, prefix);
    if (rows.length) sections.push({ id: name, title, rows });
  }
  return sections;
};

/** Everything this model knows how to place. */
const _claimedKeys = () => {
  const claimed = new Set(["members"]);
  for (const spec of SECTION_SPECS) for (const k of spec.claims) claimed.add(k);
  for (const k of LINEAGE_KEYS) claimed.add(k);
  // Per-member bags, whichever shape.
  for (const k of ["health", "education", "employment", "disability", "food_shocks"]) claimed.add(k);
  return claimed;
};

/**
 * Turn a canonical_payload into the review model.
 *
 * Returns { sections, tables, members, composition, lineage, other }.
 * `other` holds every top-level key this model has no home for — shown,
 * never dropped, because the whole point is seeing what the rules
 * missed.
 */
const buildReviewModel = (payload) => {
  const p = (payload && typeof payload === "object") ? payload : {};
  const members = Array.isArray(p.members) ? p.members.filter(Boolean) : [];

  const sections = SECTION_SPECS
    .map(spec => ({ id: spec.id, title: spec.title, rows: spec.from(p) }))
    .filter(s => s.rows.length > 0);

  const tables = TABLE_SPECS
    .map(spec => ({ id: spec.id, title: spec.title, table: tableFrom(spec.get(p), spec.path) }))
    .filter(t => t.table);

  const claimed = _claimedKeys();
  const other = rowsFrom(
    Object.fromEntries(Object.entries(p).filter(([k]) => !claimed.has(k))), "",
  );

  return {
    sections,
    tables,
    members: members.map((m, i) => ({
      member: m,
      index: i,
      identity: rowsFrom(m, `members.${i}`, {
        skip: new Set(["health", "education", "employment", "disability", "_source_keys"]),
      }),
      // What the source sent for this member, beside what the connector
      // made of it. This is where a mapping fault shows up: the raw
      // c8_nin_status saying one thing and the mapped nin_status
      // another is exactly the anomaly no rule would catch.
      lineage: rowsFrom(m._source_keys, `members.${i}._source_keys`),
      detail: memberDetail(p, m, i),
    })),
    composition: composition(members),
    lineage: rowsFrom(p._source_keys, "_source_keys"),
    other,
  };
};

/* ───────────────────────────────────────────────────────────────
   Coverage — the property the screen depends on
   ─────────────────────────────────────────────────────────────── */

/** Every dotted leaf path in an object. */
const leafPaths = (obj, prefix = "", out = []) => {
  if (obj === null || obj === undefined) return out;
  if (Array.isArray(obj)) {
    obj.forEach((v, i) => leafPaths(v, prefix ? `${prefix}.${i}` : String(i), out));
    return out;
  }
  if (typeof obj === "object") {
    const entries = Object.entries(obj);
    if (!entries.length && prefix) out.push(prefix);
    for (const [k, v] of entries) leafPaths(v, prefix ? `${prefix}.${k}` : k, out);
    return out;
  }
  if (prefix) out.push(prefix);
  return out;
};

/**
 * What the payload holds versus what the model shows.
 *
 * `missing` is the list that must stay empty: a leaf in the payload
 * that reaches no part of the screen is a field an operator cannot see,
 * on a screen whose only job is letting them see everything.
 */
const reviewCoverage = (payload) => {
  const model = buildReviewModel(payload);
  const shown = new Set();
  const add = (rows) => rows.forEach(r => shown.add(r.path));
  model.sections.forEach(s => add(s.rows));
  model.members.forEach(m => {
    add(m.identity);
    add(m.lineage);
    m.detail.forEach(d => add(d.rows));
  });
  add(model.lineage);
  add(model.other);
  for (const t of model.tables) {
    for (const row of t.table.rows) {
      for (const col of t.table.columns) shown.add(`${row._path}.${col.key}`);
    }
  }
  const inPayload = leafPaths(payload);
  return {
    shown: [...shown],
    inPayload,
    missing: inPayload.filter(path => !shown.has(path)),
  };
};

Object.assign(window, {
  buildReviewModel, reviewCoverage, leafPaths,
  humaniseKey, composition,
  FIELD_LABELS, FIELD_CHOICE_LISTS,
});
