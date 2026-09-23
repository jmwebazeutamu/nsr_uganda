/* global window */
// The UBOS geographic ladder, once, for the design layer.
//
// Region → Sub-region → District → County → Sub-county → Parish →
// Village. This mirrors GeographicUnit.Level in
// apps/reference_data/models.py, and tests/contract/test_geo_levels.py
// asserts the two agree — the ladder is the backend's, this is the
// projection of it the screens render.
//
// It lives here because it was declared twice. `GEO_LEVELS` existed in
// screens-admin-refdata-geography.jsx as an array of STRINGS and in
// components/scope-edit-modal.jsx as an array of {value,label}
// OBJECTS. The console loads its JSX as classic scripts sharing one
// global scope, so the two did not merge — whichever file the page
// loaded last won, and the other silently read a shape it was not
// written for. Both files are on the admin console, which is what made
// no-duplicate-globals fail.

const GEO_LEVELS = [
  { value: "region",     label: "Region" },
  { value: "sub_region", label: "Sub-region" },
  { value: "district",   label: "District" },
  { value: "county",     label: "County" },
  { value: "sub_county", label: "Sub-county" },
  { value: "parish",     label: "Parish" },
  { value: "village",    label: "Village" },
];

// Codes only, coarse → fine. What a drill-down indexes into.
const GEO_LEVEL_CODES = GEO_LEVELS.map(l => l.value);

const GEO_LEVEL_LABEL = Object.fromEntries(
  GEO_LEVELS.map(l => [l.value, l.label]),
);

window.GEO_LEVELS = GEO_LEVELS;
window.GEO_LEVEL_CODES = GEO_LEVEL_CODES;
window.GEO_LEVEL_LABEL = GEO_LEVEL_LABEL;
