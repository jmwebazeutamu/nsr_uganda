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
/* ───────────────────────────────────────────────────────────────
   Field vocabulary comes from the registry, never from this file
   ───────────────────────────────────────────────────────────────
   This module used to carry two literal maps — thirty-nine field
   labels and twenty-seven field-to-choice-list pairs. They were a
   second vocabulary for fields the instrument already defines, and a
   second vocabulary is one that drifts: the registry codes a question
   by its place on the form (`g6_wall_material`, `h8_title_deed`) while
   the payload names the fact (`wall_material`, `land_title`), and
   nothing kept the two in step.

   Both maps are now served by /api/v1/intake/field-dictionary/, built
   from the active FormVersion's FormQuestion rows. `dictionary` below
   is that response. A field the registry does not define is reported as
   a missing schema dependency and rendered as one — the old behaviour,
   title-casing the key into a plausible label, made a gap look like an
   answer. */

/** Resolve one payload key against the served dictionary.
 *
 *  Returns { label, choiceList, missing, source, questionName }.
 *  `missing: true` means no FormQuestion maps to this key: the screen
 *  shows the raw key and flags it, so the gap is visible to whoever can
 *  close it rather than hidden behind a guess. */
const resolveField = (key, dictionary, path = "") => {
  const fields = (dictionary && dictionary.fields) || null;
  // Kobo nests the food groups — food_security.food_groups.staples.days —
  // so "days" alone is ambiguous across nine groups and only the parent
  // segment distinguishes them. The wizard flattens the same fact to
  // "staples_days", which is the alias the registry holds, so trying the
  // parent-qualified form resolves both shapes from one entry.
  let entry = fields ? fields[key] : null;
  if (!entry && fields && path) {
    const segments = String(path).split(".");
    const parent = segments.length >= 2 ? segments[segments.length - 2] : "";
    if (parent && !/^\d+$/.test(parent)) entry = fields[`${parent}_${key}`] || null;
  }
  if (entry) {
    return {
      label: entry.label || String(key),
      questionLabel: entry.question_label || entry.label || "",
      choiceList: entry.choice_list || null,
      type: entry.type || "",
      questionName: entry.question_name || "",
      section: entry.section || "",
      source: entry.source || "instrument",
      missing: false,
    };
  }
  return {
    label: String(key),
    questionLabel: "",
    choiceList: null,
    type: "",
    questionName: "",
    section: "",
    source: "unmapped",
    missing: true,
  };
};

/** "sleeping_rooms" → "Sleeping rooms". Never returns empty.
 *
 *  Presentation of the key itself, for keys the registry does not
 *  define. It asserts nothing about meaning — a field resolved this way
 *  is flagged `missing` by resolveField and rendered as unmapped. */
const humaniseKey = (key) => {
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
const rowsFrom = (obj, prefix, { skip = new Set(), dictionary = null } = {}) => {
  const rows = [];
  if (!obj || typeof obj !== "object") return rows;
  for (const [key, value] of Object.entries(obj)) {
    if (skip.has(key)) continue;
    const path = prefix ? `${prefix}.${key}` : key;
    if (value && typeof value === "object" && !Array.isArray(value)) {
      rows.push(...rowsFrom(value, path, { skip, dictionary }));
      continue;
    }
    const field = resolveField(key, dictionary, path);
    rows.push({
      path,
      key,
      label: field.missing ? humaniseKey(key) : field.label,
      title: field.questionLabel,
      value,
      choiceList: field.choiceList,
      type: field.type,
      missing: field.missing,
      source: field.source,
      questionName: field.questionName,
      empty: isEmpty(value),
    });
  }
  return rows;
};

/** A repeat group (assets, crops, livestock, shocks, coping) as a table. */
const tableFrom = (list, prefix, dictionary = null) => {
  if (!Array.isArray(list) || list.length === 0) return null;
  const columns = [...new Set(list.flatMap(r => Object.keys(r || {})))];
  return {
    columns: columns.map((c) => {
      const field = resolveField(c, dictionary, `${prefix}.${c}`);
      return {
        key: c,
        label: field.missing ? humaniseKey(c) : field.label,
        title: field.questionLabel,
        choiceList: field.choiceList,
        type: field.type,
        missing: field.missing,
        source: field.source,
      };
    }),
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

   Thresholds are read from the served dictionary, which takes them
   from the active DQA rules' parameters (head >= 12 is AC-HOH-AGE.
   min_head_age; 12-17 is AC-HOH-AGE-CHILD-LED.max_age_inclusive; the
   child boundary is AC-ORPHAN-FLAG.max_age). They were literals here
   until now, which meant editing a rule moved the boundary the engine
   enforced but not the one this panel drew.

   The elderly boundary is the exception: nothing in the registry
   defines it. It was 60 here on no authority at all. The dictionary
   returns null for it and names what would fix it, so the band is
   omitted and the gap is stated rather than guessed.

   Where the questionnaire does not establish something, the answer is
   "unknown", never a default. */

const MISSING_ELDERLY_NOTE =
  "No DQA rule or configuration entry defines where 'elderly' begins, so "
  + "this is not shown rather than assumed. Define it as a rule parameter "
  + "(for example AC-ELDERLY-HEAD.min_age) and the band returns.";

/** A threshold the registry supplied, or null. Never coerces a missing
 *  value to a number — 0 and null mean different things here. */
const _hrNum = (v) => (v === null || v === undefined || v === "" || Number.isNaN(Number(v)))
  ? null : Number(v);

const composition = (members, thresholds = {}) => {
  const list = Array.isArray(members) ? members.filter(Boolean) : [];
  const age = (m) => (m.age_years === null || m.age_years === undefined || m.age_years === "")
    ? null : Number(m.age_years);
  const head = list.find(m => m.is_head === true)
    || list.find(m => String(m.relationship_to_head || "") === "01")
    || null;
  const headAge = head ? age(head) : null;
  const ages = list.map(age);
  const known = ages.filter(a => a !== null && !Number.isNaN(a));
  // Null means the registry did not supply the boundary. Bands that
  // depend on a missing boundary are not computed from a stand-in.
  const headMin = _hrNum(thresholds.head_min_age);
  const childMax = _hrNum(thresholds.child_max_age);
  const orphanMax = _hrNum(thresholds.orphan_max_age);
  const elderlyMin = _hrNum(thresholds.elderly_min_age);
  const adultFrom = orphanMax === null ? null : orphanMax;

  const under18 = adultFrom === null ? null : known.filter(a => a < adultFrom).length;
  const over59 = elderlyMin === null ? null : known.filter(a => a >= elderlyMin).length;
  const working = (adultFrom === null || elderlyMin === null)
    ? null
    : known.filter(a => a >= adultFrom && a < elderlyMin).length;
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
         : (headMin !== null && headAge < headMin)
           ? `Under ${headMin} — AC-HOH-AGE blocks promotion.`
         : (headMin !== null && childMax !== null && headAge <= childMax)
           ? `${headMin}–${childMax}: child-headed household (AC-HOH-AGE-CHILD-LED).`
         : (elderlyMin !== null && headAge >= elderlyMin)
           ? `${elderlyMin} or over: elderly-headed household.` : ""),
    flag("Child-headed",
         headAge === null ? "unknown"
         : (headMin === null || childMax === null) ? "not configured"
         : (headAge >= headMin && headAge <= childMax ? "yes" : "no"),
         (headMin === null || childMax === null)
           ? "AC-HOH-AGE / AC-HOH-AGE-CHILD-LED supply this boundary and "
             + "neither is active, so it cannot be decided here."
           : ""),
    flag("Elderly-headed",
         headAge === null ? "unknown"
         : elderlyMin === null ? "not configured"
         : (headAge >= elderlyMin ? "yes" : "no"),
         elderlyMin === null ? MISSING_ELDERLY_NOTE : ""),
    adultFrom === null
      ? flag("Members under the adult age", "not configured",
             "AC-ORPHAN-FLAG.max_age defines the child boundary and is not active.")
      : flag(`Members under ${adultFrom}`,
             unknownAges ? `${under18} (+${unknownAges} age unknown)` : under18, ""),
    elderlyMin === null
      ? flag("Members at the elderly age and over", "not configured", MISSING_ELDERLY_NOTE)
      : flag(`Members ${elderlyMin} and over`,
             unknownAges ? `${over59} (+${unknownAges} age unknown)` : over59, ""),
    working === null
      ? flag("Dependency ratio", "not configured",
             "The ratio needs both the child and the elderly boundary. "
             + MISSING_ELDERLY_NOTE)
      : flag("Dependency ratio",
             working > 0 ? ((under18 + over59) / working).toFixed(2)
             : (under18 + over59) > 0 ? "no working-age members" : "unknown",
             `Dependants (under ${adultFrom} or ${elderlyMin}+) per working-age member. `
             + (unknownAges ? `${unknownAges} member(s) have no age, so this is a floor, not a fact.` : "")),
  ];
};

/* ───────────────────────────────────────────────────────────────
   The model
   ─────────────────────────────────────────────────────────────── */

const SECTION_SPECS = [
  { id: "interview", title: "Interview & respondent",
    from: (p, dictionary) => rowsFrom(p.interview, "interview", { dictionary: dictionary })
      .concat(rowsFrom({
        respondent_name: p.respondent_name, contact_phone: p.contact_phone,
        consent: p.consent, source_channel: p.source_channel,
        reported_household_size: p.reported_household_size,
      }, "", { dictionary }))
      // Per-purpose consent. Claimed by this section and, until the
      // coverage check said so, never actually rendered — eleven
      // consent decisions an operator could not see on the screen
      // built for seeing everything.
      .concat(rowsFrom(p.consent_block, "consent_block", { dictionary: dictionary })),
    claims: ["interview", "respondent_name", "contact_phone", "consent",
             "source_channel", "reported_household_size", "consent_block"] },

  { id: "location", title: "Location",
    from: (p, dictionary) => rowsFrom(p.geographic, "geographic", { dictionary: dictionary, skip: new Set(["_labels"]) })
      .concat(rowsFrom({
        address_narrative: p.address_narrative, urban_rural: p.urban_rural,
        gps_lat: p.gps_lat, gps_lng: p.gps_lng, gps_accuracy_m: p.gps_accuracy_m,
      }, "", { dictionary })),
    claims: ["geographic", "address_narrative", "urban_rural",
             "gps_lat", "gps_lng", "gps_accuracy_m"] },

  { id: "housing", title: "Dwelling & utilities",
    // Flat (Kobo) and nested (wizard) both land here.
    from: (p, dictionary) => {
      const h = p.housing || {};
      return rowsFrom(h.dwelling, "housing.dwelling", { dictionary: dictionary })
        .concat(rowsFrom(h.utilities, "housing.utilities", { dictionary: dictionary }))
        .concat(rowsFrom(h, "housing", { dictionary,
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
    from: (p, dictionary) => rowsFrom((p.housing || {}).livelihood, "housing.livelihood")
      .concat(rowsFrom(p.agriculture, "agriculture", { dictionary: dictionary })),
    claims: ["agriculture"] },

  { id: "food", title: "Food security",
    from: (p, dictionary) => rowsFrom((p.food_shocks || {}).food_security, "food_shocks.food_security")
      .concat(rowsFrom((p.food_shocks || {}).food_consumption, "food_shocks.food_consumption", { dictionary }))
      .concat(rowsFrom((p.food_security || {}).fies, "food_security.fies", { dictionary }))
      .concat(rowsFrom((p.food_security || {}).food_groups, "food_security.food_groups", { dictionary }))
      .concat(rowsFrom(p.food_security, "food_security", { dictionary,
        skip: new Set(["fies", "food_groups"]),
      })),
    claims: ["food_security"] },

  { id: "shocks", title: "Shocks & coping",
    from: (p, dictionary) => rowsFrom((p.shocks_coping || {}).coping, "shocks_coping.coping")
      .concat(rowsFrom((p.shocks_coping || {}).shocks, "shocks_coping.shocks", { dictionary }))
      .concat(rowsFrom(p.shocks_coping, "shocks_coping", { dictionary,
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
const memberDetail = (payload, member, index, dictionary) => {
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
    const rows = rowsFrom(source, prefix, { dictionary });
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
/** Build the review model for `payload`.
 *
 *  `dictionary` is the /api/v1/intake/field-dictionary/ response. It is
 *  optional so the model stays callable in tests and before the fetch
 *  resolves; without it every field reports as unmapped, which is the
 *  honest rendering of "the registry has not answered yet" and is what
 *  the screen shows while loading. */
const buildReviewModel = (payload, dictionary = null) => {
  const p = (payload && typeof payload === "object") ? payload : {};
  const members = Array.isArray(p.members) ? p.members.filter(Boolean) : [];

  const sections = SECTION_SPECS
    .map(spec => ({ id: spec.id, title: spec.title, rows: spec.from(p, dictionary) }))
    .filter(s => s.rows.length > 0);

  const tables = TABLE_SPECS
    .map(spec => ({ id: spec.id, title: spec.title, table: tableFrom(spec.get(p), spec.path, dictionary) }))
    .filter(t => t.table);

  const claimed = _claimedKeys();
  const other = rowsFrom(
    Object.fromEntries(Object.entries(p).filter(([k]) => !claimed.has(k))), "",
    { dictionary },
  );

  return {
    sections,
    tables,
    members: members.map((m, i) => ({
      member: m,
      index: i,
      identity: rowsFrom(m, `members.${i}`, {
        dictionary,
        skip: new Set(["health", "education", "employment", "disability", "_source_keys"]),
      }),
      // What the source sent for this member, beside what the connector
      // made of it. This is where a mapping fault shows up: the raw
      // c8_nin_status saying one thing and the mapped nin_status
      // another is exactly the anomaly no rule would catch.
      lineage: rowsFrom(m._source_keys, `members.${i}._source_keys`, { dictionary: dictionary }),
      detail: memberDetail(p, m, i, dictionary),
    })),
    composition: composition(members, (dictionary && dictionary.thresholds) || {}),
    lineage: rowsFrom(p._source_keys, "_source_keys", { dictionary: dictionary }),
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
  resolveField,
});
