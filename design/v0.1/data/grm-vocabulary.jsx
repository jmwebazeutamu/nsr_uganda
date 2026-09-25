/* global window */
// The GRM vocabulary — categories and tiers — in one place.
//
// There were four copies. screens-grm.jsx held GRM_CATEGORIES and
// GRM_TIERS as objects; screens-household.jsx held _GRM_CATEGORIES and
// _GRM_TIERS as arrays with different labels for the same codes
// ("Wrongly excluded" against "Exclusion error"), so the same
// grievance read differently depending on which screen raised it.
//
// Both shapes are served from here: the workbench looks codes up by
// key to label a row, the modals iterate to build a <select>. One set
// of facts, two views of it, rather than two sets.
//
// The codes mirror apps/grievance/models.py Category and Tier. A code
// that is not in the server's enum is refused on POST, which is the
// backstop; this is what stops the console offering it in the first
// place.

const GRM_CATEGORIES = {
  data_correction:  "Data correction",
  exclusion_error:  "Wrongly excluded",
  inclusion_error:  "Wrongly included",
  programme_issue:  "Programme issue",
  operator_conduct: "Operator conduct",
  other:            "Other",
};

// sla_hours is the DEFAULT ladder from SAD §5.1, shown so an operator
// picking a tier can see what they are committing to. The deadline is
// stamped server-side from GrmTierRule, which operations can retune —
// so this is a hint in a dropdown, never the number a screen reports
// a case against.
const GRM_TIERS = {
  l1_parish_chief: { short: "L1", label: "Parish Chief", sla_hours: 24 },
  l2_cdo:          { short: "L2", label: "CDO",          sla_hours: 48 },
  l3_district:     { short: "L3", label: "District",     sla_hours: 72 },
  l4_nsr_unit:     { short: "L4", label: "NSR Unit",     sla_hours: 168 },
};

const GRM_CATEGORY_OPTIONS = Object.entries(GRM_CATEGORIES)
  .map(([value, label]) => ({ value, label }));

const GRM_TIER_OPTIONS = Object.entries(GRM_TIERS)
  .map(([value, t]) => ({
    value, label: `${t.short} — ${t.label}`, sla_hours: t.sla_hours,
  }));

window.GRM_CATEGORIES = GRM_CATEGORIES;
window.GRM_TIERS = GRM_TIERS;
window.GRM_CATEGORY_OPTIONS = GRM_CATEGORY_OPTIONS;
window.GRM_TIER_OPTIONS = GRM_TIER_OPTIONS;
