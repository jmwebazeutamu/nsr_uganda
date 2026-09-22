/* global React, Icon, Chip, buildReviewModel, useChoiceList */
// Household detailed review (US-S24-DIH-REVIEW)
// =====================================================
// Everything collected about one household, on one screen, so an
// operator can check the record against itself before promoting it into
// the national registry — verify the composition flags, and spot the
// anomaly no rule was written to catch.
//
// Presentation, deliberately. The screen makes no judgement: it does not
// highlight outliers, rank suspicion or hide anything it thinks is
// uninteresting. If the system can reliably detect a problem it belongs
// in a DQA rule that runs on every record, not as a hint on one screen.
// What this adds is that a human can finally SEE all of it.
//
// Two things follow from that, and they are the whole design:
//
//   NOTHING IS HIDDEN. A field the model has no home for is still
//   rendered, raw, under "Other collected data" — a screen for finding
//   what the rules missed cannot quietly drop what it does not
//   recognise. household-review-model.jsx proves it with
//   reviewCoverage(); the tests run it over real payloads of both
//   shapes and assert nothing is missing.
//
//   EDITABILITY IS HONEST. The server's whitelist is the authority on
//   what may be corrected (EDITABLE_PATH_PATTERNS). A field outside it
//   renders read-only WITH THE REASON, rather than offering an input
//   that fails on save.

const { useState: useStateHR, useMemo: useMemoHR } = React;

/* The server's editable-path whitelist, mirrored.
 *
 * Mirrored, not guessed: apps/ingestion_hub/test_household_review.py
 * asserts these patterns agree with EDITABLE_PATH_PATTERNS, so a
 * server-side policy change that this file misses fails CI rather than
 * showing an operator an input whose save is rejected.
 *
 * Three categories are out of bounds by policy, not oversight:
 *   NIN        legal identity — re-capture only
 *   geographic chain integrity — re-capture only
 *   consent    legal, and urban_rural drives PMT semantics
 */
const EDITABLE_PATTERNS = [
  /^gps_(?:lat|lng|accuracy_m)$/,
  /^address_narrative$/,
  /^reported_household_size$/,
  /^members\.\d+\.(?:surname|first_name|other_name|date_of_birth|age_years|telephone_1|telephone_2)$/,
  /^members\.\d+\.(?:health|education|employment|disability)\.\w+$/,
  /^(?:health|education|employment)\.\d+\.\w+(?:\.\w+)?$/,
  /^housing\.(?:dwelling|utilities|livelihood)\.\w+$/,
  /^housing\.(?!assets|crops|livestock)\w+(?:\.\w+)?$/,
  /^agriculture\.\w+$/,
  /^food_shocks\.(?:food_security|food_consumption)\.\w+$/,
  /^food_security\.(?:fies|food_groups)\.\w+(?:\.\w+)?$/,
  /^shocks_coping\.(?:coping|shocks)\.\w+$/,
  /^interview\.(?!consent$)\w+$/,
];

//: Leaf names never correctable, wherever they appear. Mirrors
//: _PROTECTED_LEAF_PREFIXES: the generic patterns use \w+ for leaf
//: segments, so one could swallow a protected field sitting somewhere
//: unexpected. Stated once rather than as a lookahead in every pattern.
const PROTECTED_LEAF_PREFIXES = ["nin"];

const isEditablePath = (path) => {
  const leaf = String(path).split(".").pop();
  if (PROTECTED_LEAF_PREFIXES.some(prefix => leaf.startsWith(prefix))) return false;
  return EDITABLE_PATTERNS.some(p => p.test(path));
};

/** Why a field cannot be corrected here. Never "it just can't". */
const notEditableReason = (path) => {
  if (/^geographic\./.test(path)) {
    return "The geographic chain is re-capture only — correcting it here "
         + "would break the lineage the record was promoted under.";
  }
  if (/nin/i.test(path)) {
    return "NIN is legal identity and is re-capture only.";
  }
  if (/^consent/.test(path) || path === "urban_rural" || path === "interview.consent") {
    return "Consent and urban/rural carry legal and PMT meaning and cannot "
         + "be corrected by an operator.";
  }
  if (/^housing\.(assets|crops|livestock)\./.test(path)
      || /^food_shocks\.(shocks|coping)\./.test(path)) {
    return "Rows in a repeat group are added and removed, not edited in "
         + "place — that is a separate correction.";
  }
  if (/^_source_keys|_source_keys\./.test(path)) {
    return "This is what the source sent. The raw landing is append-only "
         + "(AC-DIH-LANDING-IMMUTABLE) — it records what arrived, not what "
         + "we wish had arrived.";
  }
  return "Not in the correctable set. If this needs changing, the "
       + "household is re-captured.";
};

/** A stored code as its label, with the code kept visible.
 *
 *  Both halves matter here. The label is what a reviewer reads; the
 *  code is what they cross-check against the questionnaire and what
 *  they quote when something is wrong. Showing only one of them has
 *  already gone wrong twice on this product.
 */
//: These components are declared at the top level of a CLASSIC script,
//: so they share one global scope with 40-odd other files — the last
//: declaration of a name wins, across files, by load order.
//:
//: An unprefixed `ReviewSection` here was shadowed by a DIFFERENT
//: `ReviewSection` in app-change-request.jsx, which loads later and
//: takes `{ scope, member, rows, ... }`. Every `<ReviewSection>` in the
//: household review resolved to that one, whose first line is
//: `const fieldCount = rows.length` — so opening the detailed review
//: crashed the screen with "Cannot read properties of undefined
//: (reading 'length')".
//:
//: Prefixed for that reason, not for style.
//: design/v0.1/no-duplicate-globals.test.js now fails on a new
//: collision rather than leaving it to be found in a browser.
const HhCodedCell = ({ listName, value, type = "" }) => {
  // include_deprecated: this is a review surface. A household coded
  // against a retired frame — and the ones captured before the UBOS 2024
  // migration are — would otherwise render as a bare number, which is
  // exactly the record an operator most needs to read. The retired label
  // is shown and marked as retired rather than withheld.
  const [options] = (listName && typeof useChoiceList === "function")
    ? useChoiceList(listName, { includeDeprecated: true })
    : [[]];
  if (value === null || value === undefined || value === "") {
    return <span className="muted">—</span>;
  }
  const decode = (code) => (options || []).find(o => String(o.code) === String(code));

  // A select_multiple answer is a space-separated list of codes. Decoding
  // the whole string as one code finds nothing, so the screen showed the
  // raw "phone radio bed mattress" — every selection undecoded on the
  // one field where the operator most wants to read the selections.
  if (type === "select_multiple" && String(value).trim().includes(" ")) {
    const codes = String(value).trim().split(/\s+/);
    return (
      <span>
        {codes.map((code, i) => {
          const one = decode(code);
          return (
            <span key={code + i}>
              {i > 0 && ", "}
              {one ? one.label : <span className="t-mono">{code}</span>}
              <span className="t-cap t-mono"> ({code})</span>
              {one && one.status && one.status !== "active" && (
                <span className="t-cap muted" title="Coded against a retired frame.">
                  {" "}<Icon name="clock" size={10}/>
                </span>
              )}
            </span>
          );
        })}
      </span>
    );
  }

  const hit = decode(value);
  if (!hit) {
    // No option carries this code in any frame, current or retired. The
    // value is shown as stored and flagged, because a code that decodes
    // to nothing is a data fault, not a display one.
    return (
      <span>
        <span className="t-mono">{String(value)}</span>
        <span className="t-cap muted" style={{ marginLeft: 6 }}
              title={
                `No option in "${listName}" carries the code ${value}, in the `
                + "current frame or any retired one, so it cannot be shown as "
                + "words. The stored value is what was captured."
              }>
          <Icon name="alert-triangle" size={11}/> unknown code
        </span>
      </span>
    );
  }
  const retired = hit.status && hit.status !== "active";
  return (
    <span>
      {hit.label} <span className="t-cap t-mono">({String(value)})</span>
      {retired && (
        <span className="t-cap muted" style={{ marginLeft: 6 }}
              title={
                "This answer was coded against a retired code frame. The "
                + "label is the one that applied when it was captured; the "
                + "current frame uses different codes."
              }>
          <Icon name="clock" size={11}/> retired code
        </span>
      )}
    </span>
  );
};

const HhReviewRow = ({ row, draft, onEdit }) => {
  const editable = isEditablePath(row.path);
  const dirty = Object.prototype.hasOwnProperty.call(draft || {}, row.path);
  const shown = dirty ? draft[row.path] : row.value;
  return (
    <div className="review-row" style={{
      background: dirty ? "var(--accent-update-bg)" : undefined,
    }}>
      <div className="review-row-label"
           title={row.title ? `${row.title}\n${row.path}` : row.path}>
        {row.label}
        {row.missing && (
          <span className="t-cap muted" style={{ marginLeft: 6 }}
                title={
                  "No question in the active questionnaire produces this field, "
                  + "so the name shown is the raw key the payload used and any "
                  + "code it holds cannot be turned into words. Either the "
                  + "connector is sending something the questionnaire does not "
                  + "ask, or the question exists but nothing records that it "
                  + "feeds this field. Both are fixed in Questionnaire "
                  + "Authoring, not here."
                }>
            <Icon name="alert-triangle" size={11}/> not in questionnaire
          </span>
        )}
      </div>
      <div className="review-row-value">
        {editable && onEdit ? (
          <input
            className="field-input"
            aria-label={`${row.label} (${row.path})`}
            value={shown === null || shown === undefined ? "" : String(shown)}
            onChange={(e) => onEdit(row.path, e.target.value)}/>
        ) : row.choiceList ? (
          <HhCodedCell listName={row.choiceList} value={shown} type={row.type}/>
        ) : (
          <span className={row.empty ? "muted" : ""}>
            {row.empty ? "—" : String(shown)}
          </span>
        )}
      </div>
      <div className="review-row-flag">
        {!editable && (
          <span className="t-cap" title={notEditableReason(row.path)}>
            <Icon name="shield" size={11}/> read-only
          </span>
        )}
        {dirty && <Chip tone="update" size="sm">edited</Chip>}
      </div>
    </div>
  );
};

// Every section starts collapsed. The review opens on a list of what the
// record contains and how much of it, so an operator chooses where to
// look rather than scrolling past two sections that were opened for
// them.
const HhReviewSection = ({ title, children, count, defaultOpen = false, tone = "data" }) => {
  const [open, setOpen] = useStateHR(defaultOpen);
  return (
    <div className="card" style={{ marginTop: 12, borderLeft: `3px solid var(--accent-${tone})` }}>
      <button onClick={() => setOpen(!open)}
        aria-expanded={open}
        style={{
          width: "100%", display: "flex", alignItems: "center", gap: 8,
          padding: "10px 14px", border: 0, background: "var(--neutral-50)",
          cursor: "pointer", textAlign: "left",
        }}>
        <Icon name={open ? "chevronDown" : "chevronRight"} size={14}/>
        <strong className="t-bodysm" style={{ flex: 1 }}>{title}</strong>
        {count != null && <span className="t-cap">{count}</span>}
      </button>
      {open && <div style={{ padding: 14 }}>{children}</div>}
    </div>
  );
};

const HhRepeatTable = ({ table }) => (
  <table className="tbl" style={{ fontSize: 12.5 }}>
    <thead>
      <tr>{table.columns.map(c => (
        <th key={c.key} title={c.title || c.key}>
          {c.label}
          {c.missing && (
            <span className="t-cap muted" style={{ marginLeft: 4 }}
                  title={
                    "No question in the active questionnaire produces this "
                    + "column, so its codes cannot be turned into words."
                  }>
              <Icon name="alert-triangle" size={10}/>
            </span>
          )}
        </th>
      ))}</tr>
    </thead>
    <tbody>
      {table.rows.map((row, i) => (
        <tr key={i}>
          {table.columns.map(c => (
            <td key={c.key}>
              {c.choiceList
                ? <HhCodedCell listName={c.choiceList} value={row[c.key]} type={c.type}/>
                : (row[c.key] === null || row[c.key] === undefined || row[c.key] === ""
                    ? <span className="muted">—</span> : String(row[c.key]))}
            </td>
          ))}
        </tr>
      ))}
    </tbody>
  </table>
);

/* ───────────────────────────────────────────────────────────────
   The field dictionary
   ───────────────────────────────────────────────────────────────
   Labels and choice lists come from the active instrument, not from
   this file. One fetch per session, cached at module scope: the
   dictionary changes when a new FormVersion is activated, which is an
   administrative act, not something that happens mid-review.

   While it is in flight the review still renders — every field reports
   as unmapped, which is what "the registry has not answered yet"
   honestly looks like, and resolves as soon as the fetch lands. */

let _dictionaryCache = null;
let _dictionaryEtag = "";
let _dictionaryPromise = null;

const _fetchFieldDictionary = (force = false) => {
  if (!_dictionaryPromise || force) {
    const headers = { Accept: "application/json" };
    // Conditional GET. Without it the cache never expires for the life
    // of the tab, so activating a new FormVersion or correcting a field
    // mapping leaves every open console showing the old answer with
    // nothing to suggest it is stale — which is exactly how a screen
    // ends up reporting eighteen questions as "not in questionnaire"
    // minutes after they were mapped.
    if (_dictionaryEtag && !force) headers["If-None-Match"] = _dictionaryEtag;
    _dictionaryPromise = fetch("/api/v1/intake/field-dictionary/", {
      headers, credentials: "same-origin",
    })
      .then((r) => {
        if (r.status === 304 && _dictionaryCache) return _dictionaryCache;
        if (!r.ok) throw new Error(`field-dictionary HTTP ${r.status}`);
        _dictionaryEtag = r.headers.get("ETag") || "";
        return r.json().then((body) => { _dictionaryCache = body; return body; });
      })
      .catch((err) => { _dictionaryPromise = null; throw err; });
  }
  return _dictionaryPromise;
};

window._nsrFieldDictionaryClear = () => {
  _dictionaryCache = null; _dictionaryPromise = null; _dictionaryEtag = "";
};

const useFieldDictionary = () => {
  const [state, setState] = React.useState(
    () => ({ dictionary: _dictionaryCache, loading: !_dictionaryCache, error: null }),
  );
  React.useEffect(() => {
    let live = true;
    // Stale-while-revalidate: render what is cached immediately, then
    // revalidate. A 304 costs nothing and a changed dictionary lands
    // without the operator knowing to reload.
    _dictionaryPromise = null;
    _fetchFieldDictionary()
      .then((d) => { if (live) setState({ dictionary: d, loading: false, error: null }); })
      .catch((e) => {
        if (live) {
          setState((prev) => ({
            // Keep showing the cached dictionary if we have one: labels
            // that are possibly stale beat no labels at all.
            dictionary: prev.dictionary || _dictionaryCache,
            loading: false,
            error: String(e.message || e),
          }));
        }
      });
    return () => { live = false; };
  }, []);
  return state;
};

/* ───────────────────────────────────────────────────────────────
   The review
   ─────────────────────────────────────────────────────────────── */

const HouseholdReview = ({
  payload, canEdit = false, draft = {}, onEdit, editBlockedReason = "",
  dictionary: dictionaryProp = null,
}) => {
  // A caller that already holds the dictionary passes it in rather than
  // making the screen fetch it again; the hook is the fallback.
  const fetched = useFieldDictionary();
  const dictionary = dictionaryProp || fetched.dictionary;
  const dictLoading = dictionaryProp ? false : fetched.loading;
  const dictError = dictionaryProp ? null : fetched.error;
  const model = useMemoHR(
    () => (typeof buildReviewModel === "function"
      ? buildReviewModel(payload, dictionary) : null),
    [payload, dictionary],
  );
  // An absent payload and an empty one are different: the first has
  // nothing to show, the second is a record that arrived carrying
  // nothing, which is itself worth seeing. buildReviewModel tolerates
  // both, so the emptiness is decided here rather than by it.
  const hasPayload = !!(payload && typeof payload === "object"
    && Object.keys(payload).length > 0);
  if (!model || !hasPayload) {
    return <div className="t-bodysm muted" style={{ padding: 20 }}>No record loaded.</div>;
  }
  const edit = canEdit ? onEdit : null;

  // Count what the dictionary could not answer for THIS record, so the
  // notice is about the record in front of the operator rather than the
  // instrument in general.
  const unmappedFields = React.useMemo(() => {
    const names = new Set();
    for (const section of (model.sections || [])) {
      for (const row of (section.rows || [])) if (row.missing) names.add(row.key);
    }
    for (const table of (model.tables || [])) {
      for (const col of ((table.table && table.table.columns) || [])) {
        if (col.missing) names.add(col.key);
      }
    }
    for (const m of (model.members || [])) {
      for (const row of (m.identity || [])) if (row.missing) names.add(row.key);
      for (const section of (m.detail || [])) {
        for (const row of (section.rows || [])) if (row.missing) names.add(row.key);
      }
    }
    return [...names].sort();
  }, [model]);

  const missingThresholds = Object.entries(
    (dictionary && dictionary.missing_thresholds) || {},
  );

  return (
    <div>
      {dictError && (
        <div className="card" style={{ padding: 12, borderLeft: "3px solid var(--accent-danger)" }}>
          <div className="row gap-2" style={{ alignItems: "flex-start" }}>
            <Icon name="alert-triangle" size={15} color="var(--accent-danger)"/>
            <div className="t-bodysm" style={{ color: "var(--neutral-700)" }}>
              <strong>Field dictionary unavailable.</strong> Field names below are
              raw payload keys and coded answers are shown as their stored codes.
              Nothing here is wrong, but it is unlabelled — do not read a code as
              a value. ({dictError})
            </div>
          </div>
        </div>
      )}
      {!dictError && !dictLoading && (unmappedFields.length > 0 || missingThresholds.length > 0) && (
        <div className="card" style={{ padding: 12, borderLeft: "3px solid var(--accent-quality)" }}>
          <div className="row gap-2" style={{ alignItems: "flex-start" }}>
            <Icon name="info" size={15} color="var(--accent-quality)"/>
            <div className="t-bodysm" style={{ color: "var(--neutral-700)" }}>
              <strong>Not in the questionnaire.</strong>{" "}
              {unmappedFields.length > 0 && (
                <span>
                  {unmappedFields.length} field
                  {unmappedFields.length === 1 ? " on this record is" : "s on this record are"}
                  {" "}not produced by any question in the active questionnaire
                  {" "}({unmappedFields.slice(0, 6).join(", ")}
                  {unmappedFields.length > 6 ? `, +${unmappedFields.length - 6} more` : ""}),
                  {" "}so they show the raw key the payload used and their codes
                  {" "}are not turned into words.{" "}
                </span>
              )}
              {missingThresholds.map(([key, why]) => (
                <span key={key}><em>{key}</em>: {why} </span>
              ))}
            </div>
          </div>
        </div>
      )}
      {!canEdit && editBlockedReason && (
        <div className="card" style={{ padding: 12, borderLeft: "3px solid var(--accent-quality)" }}>
          <div className="row gap-2" style={{ alignItems: "flex-start" }}>
            <Icon name="info" size={15} color="var(--accent-quality)"/>
            <div className="t-bodysm" style={{ color: "var(--neutral-700)" }}>
              <strong>Read-only.</strong> {editBlockedReason}
            </div>
          </div>
        </div>
      )}

      {/* Composition first: it is the summary of the household that
          programme targeting acts on, and every number in it is derived
          from the roster immediately below — so the conclusion and its
          evidence are read together. */}
      <HhReviewSection title="Household composition" tone="programme"
        count={`${model.members.length} members`}>
        <div className="t-cap" style={{ marginBottom: 10 }}>
          Derived from the roster, not asked. Check these against the members below.
        </div>
        {model.composition.map((flag, i) => (
          <div className="review-row" key={i}>
            <div className="review-row-label">{flag.label}</div>
            <div className="review-row-value"><strong>{String(flag.value)}</strong></div>
            <div className="review-row-flag">
              {flag.detail && (
                <span className="t-cap" title={flag.detail}>
                  <Icon name="info" size={11}/>
                </span>
              )}
            </div>
          </div>
        ))}
      </HhReviewSection>

      <HhReviewSection title="Members" tone="identity"
        count={`${model.members.length}`}>
        {model.members.map((m) => (
          <div key={m.index} style={{
            marginBottom: 14, paddingBottom: 14,
            borderBottom: "1px solid var(--neutral-200)",
          }}>
            <div className="row gap-2" style={{ marginBottom: 8 }}>
              <strong className="t-bodysm">
                #{m.member.line_number ?? m.index + 1}{" "}
                {`${m.member.first_name || ""} ${m.member.surname || ""}`.trim() || "(unnamed)"}
              </strong>
              {m.member.is_head && <Chip tone="programme" size="sm">Head</Chip>}
            </div>
            {m.identity.map(row => (
              <HhReviewRow key={row.path} row={row} draft={draft} onEdit={edit}/>
            ))}
            {m.detail.map(d => (
              <div key={d.id} style={{ marginTop: 10 }}>
                <div className="t-cap" style={{ marginBottom: 4 }}>{d.title}</div>
                {d.rows.map(row => (
                  <HhReviewRow key={row.path} row={row} draft={draft} onEdit={edit}/>
                ))}
              </div>
            ))}
            {m.lineage.length > 0 && (
              <details style={{ marginTop: 10 }}>
                <summary className="t-cap" style={{ cursor: "pointer" }}>
                  As the source sent it ({m.lineage.length} fields)
                </summary>
                <div style={{ marginTop: 6 }}>
                  {m.lineage.map(row => (
                    <HhReviewRow key={row.path} row={row} draft={draft} onEdit={null}/>
                  ))}
                </div>
              </details>
            )}
          </div>
        ))}
      </HhReviewSection>

      {model.sections.map(section => (
        <HhReviewSection key={section.id} title={section.title} count={`${section.rows.length} fields`}>
          {section.rows.map(row => (
            <HhReviewRow key={row.path} row={row} draft={draft} onEdit={edit}/>
          ))}
        </HhReviewSection>
      ))}

      {model.tables.map(t => (
        <HhReviewSection key={t.id} title={t.title} count={`${t.table.rows.length} rows`}>
          <HhRepeatTable table={t.table}/>
        </HhReviewSection>
      ))}

      {model.lineage.length > 0 && (
        <HhReviewSection title="Source lineage" tone="system"
          count={`${model.lineage.length} fields`}>
          <div className="t-cap" style={{ marginBottom: 8 }}>
            What the source system sent. Append-only — this records what
            arrived, not what we wish had arrived.
          </div>
          {model.lineage.map(row => (
            <HhReviewRow key={row.path} row={row} draft={draft} onEdit={null}/>
          ))}
        </HhReviewSection>
      )}

      {/* The catch-all. Anything the model has no home for still gets
          shown — a screen for spotting what the rules missed cannot
          quietly drop what IT does not recognise either. */}
      {model.other.length > 0 && (
        <HhReviewSection title="Other collected data" tone="quality"
          count={`${model.other.length} fields`}>
          <div className="t-cap" style={{ marginBottom: 8 }}>
            Collected for this household but not part of a known section.
            Shown raw rather than dropped.
          </div>
          {model.other.map(row => (
            <HhReviewRow key={row.path} row={row} draft={draft} onEdit={edit}/>
          ))}
        </HhReviewSection>
      )}
    </div>
  );
};

Object.assign(window, {
  HouseholdReview, isEditablePath, notEditableReason,
  PROTECTED_LEAF_PREFIXES,
  EDITABLE_PATTERNS, HhCodedCell, HhReviewRow, HhReviewSection,
});
