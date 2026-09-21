/* global React, Icon, Chip, KPI, PageHeader, Field, GeoTreePicker, Modal, ReasonModal, ActionBar,
   useChoiceList, CAPTURE_CHOICE_LISTS,
   useWideView, WideViewButtons, WideShell,
   RosterSection, HealthDisabilitySection, EducationSection, EmploymentSection,
   HousingSection, FoodShocksSection, memberDetailGaps, ageFromDateOfBirth */
// NSR MIS — 11.1 Parish capture + 11.2 Receipt slip

const { useState: useStateCap, useEffect: useEffectCap } = React;

/* ============================================================
   Clock — EAT rendering of a real instant
   ============================================================
   CLAUDE.md: persist as UTC, render as EAT (UTC+3). Africa/Kampala is
   the canonical tz id for Uganda.

   Every timestamp on this screen used to be the literal string
   "14 May 2026 · 14:34 EAT" — the date the screen was written. It was
   on the form, in the header, in the status strip, and on both printed
   slips, so every respondent went home with a receipt dated four months
   in the past. */

const EAT_TZ = "Africa/Kampala";

const _eatDate = (d) => new Intl.DateTimeFormat("en-GB", {
  timeZone: EAT_TZ, day: "numeric", month: "long", year: "numeric",
}).format(d);

const _eatTime = (d) => new Intl.DateTimeFormat("en-GB", {
  timeZone: EAT_TZ, hour: "2-digit", minute: "2-digit", hour12: false,
}).format(d);

/** "19 September 2026 · 14:34 EAT" */
const formatEatStamp = (value) => {
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return `${_eatDate(d)} · ${_eatTime(d)} EAT`;
};

/** "14:34 EAT" */
const formatEatTime = (value) => {
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return `${_eatTime(d)} EAT`;
};

/* ============================================================
   The household contact number
   ============================================================
   ONE field, decided in ADR-0033: the head member's `telephone_1`.

   Identification used to carry its own "Phone (E.164)" box, marked
   required, bound to nothing — an uncontrolled <input> whose value was
   never read into state and never posted. So a household captured with
   a phone number typed there arrived at the registry with Phone —,
   while a household that happened to also have the roster's Telephone
   filled in appeared to work. Two boxes, one of them a decoy.

   `Member.telephone_1` is the column the registry already indexes, that
   the roster collects, and that the review panel reads. The
   Identification box now edits THAT value rather than a parallel one,
   so there is one number and it cannot diverge from itself. */

/** The number the registry will contact this household on, or "". */
const householdContactPhone = (members) => {
  const head = (members || []).find(m => m && m.line_number === 1)
    || (members || [])[0];
  return ((head && head.telephone_1) || "").trim();
};

/** A ticking "now", so a wizard left open over a shift does not keep
    reporting the minute it was opened. One update a minute. */
const useEatClock = () => {
  const [now, setNow] = useStateCap(() => new Date());
  useEffectCap(() => {
    const t = setInterval(() => setNow(new Date()), 60000);
    return () => clearInterval(t);
  }, []);
  return now;
};

const SECTIONS = [
  { id: "id",    label: "Identification",     tint: "data",     icon: "mapPin" },
  { id: "rost",  label: "Roster",             tint: "identity", icon: "users" },
  { id: "hd",    label: "Health & Disability",tint: "danger",   icon: "shield" },
  { id: "ed",    label: "Education",          tint: "update",   icon: "book" },
  { id: "emp",   label: "Employment",         tint: "programme",icon: "users" },
  { id: "hous",  label: "Housing",            tint: "eligibility",icon:"home" },
  { id: "food",  label: "Food & Shocks",      tint: "grm",      icon: "alert" },
];

/* ============================================================
   Per-section validators
   ============================================================
   Each validator returns an array of human-readable error strings.
   Empty array = section is good to leave. The stepper colours the
   tab red and shows a count when errors are present; the "Next"
   button is disabled when the current section's array is non-empty.

   Validation policy:
   - Section 1 (Identification): full geo chain to village + consent.
   - Section 2 (Roster): at least one member, head has surname +
     first_name + sex + DoB-or-age, every member has surname +
     first_name + sex + relationship_to_head.
   - Sections 3–5 (per member): EVERY member above the section's age
     threshold must have the section's required answers — not just the
     one whose chip happens to be selected. Validating only the visible
     member let a 3-member household walk from section 3 to Submit with
     two members untouched, and the section never even lost its
     completion tick.
   - Sections 6–7 (household-level): advisory — the model accepts
     partials and the post-promotion edit flow can fill the rest. Their
     step indicator still shows what is unfilled.

   The per-member required set is declared once, in
   screens-capture-sections.jsx (PER_MEMBER_REQUIRED), and read from
   here via memberDetailGaps() so the validators and the member chips
   cannot disagree. AC-MEMBER-DETAIL-REQUIRED is the server-side
   counterpart that fails the staged record on the same gaps. */

const _validateId = ({ geo, consent }) => {
  const errs = [];
  if (!geo.region)    errs.push("Region is required");
  if (!geo.sub_region) errs.push("Sub-region is required");
  if (!geo.district)  errs.push("District is required");
  if (!geo.county)    errs.push("County is required");
  if (!geo.sub_county) errs.push("Sub-county is required");
  if (!geo.parish)    errs.push("Parish is required");
  // Village is optional — the UBOS frame doesn't carry village rows
  // for every parish, and field ops report village often unknown at
  // capture time. Parish is the lowest mandatory level.
  // Unset is its own failure, distinct from refused: "not asked yet" and
  // "the respondent said no" must never collapse into one state.
  if (!consent) errs.push("Registration consent has not been recorded — ask the respondent");
  else if (consent !== "yes") errs.push("Registration consent was refused — the intake cannot continue");
  return errs;
};

const _validateRoster = ({ members }) => {
  const errs = [];
  if (!members || members.length === 0) {
    errs.push("Add at least one member (the head of household)");
    return errs;
  }
  const hasHead = members.some(m => m.relationship_to_head === "01");
  if (!hasHead) errs.push("Person 1 must be marked as the head of household");
  members.forEach((m, i) => {
    const tag = `Person ${m.line_number || i + 1}`;
    if (!m.surname)              errs.push(`${tag}: surname is required`);
    if (!m.first_name)           errs.push(`${tag}: first name is required`);
    if (!m.sex)                  errs.push(`${tag}: sex is required`);
    if (!m.relationship_to_head) errs.push(`${tag}: relationship to head is required`);
    if (!m.date_of_birth && (m.age_years == null || m.age_years === ""))
      errs.push(`${tag}: date of birth OR age is required`);
  });
  return errs;
};

// Sections 6–7 (household-level) stay advisory. Returning empty keeps
// the Next button enabled; the stepper still shows what's unfilled.
const _validateAdvisory = () => [];

// Per-member sections: one error per member still missing a required
// answer, naming the member so the operator knows where to go.
const _validatePerMember = (sectionId, dataKey) => (state) => {
  const gaps = (typeof memberDetailGaps === "function")
    ? memberDetailGaps(sectionId, state.members, state[dataKey])
    : [];
  return gaps.map(g => `#${g.line_number} ${g.label}: ${g.missing.join(", ")} required`);
};

const SECTION_VALIDATORS = {
  id:   _validateId,
  rost: _validateRoster,
  hd:   _validatePerMember("hd", "healthData"),
  ed:   _validatePerMember("ed", "educationData"),
  emp:  _validateAdvisory,
  hous: _validateAdvisory,
  food: _validateAdvisory,
};

const CaptureScreen = ({ device = "desktop", onChangeDevice, onPromoted }) => {
  const [active, setActive] = useStateCap("id");
  // Real time, not the date this screen was written.
  const now = useEatClock();
  // Start-of-capture instant, frozen: the "Date captured" the record
  // carries is when the interview started, not when it was rendered.
  const [startedAt] = useStateCap(() => new Date());
  // #14 — the form column collapses to ~250px at 1104px wide while the
  // left half of the window is empty. The registry list already has this
  // control (design/v0.1/components/wide-view.jsx, ADR-0030); the
  // wizard, which is the screen an enumerator spends the whole
  // interview in, had none.
  const wide = (typeof useWideView === "function") ? useWideView("capture") : null;
  // One request for every lookup the wizard will need, fired before the
  // first section renders — see CAPTURE_CHOICE_LISTS in
  // screens-capture-sections.jsx for why. Guarded the same way every
  // other useChoiceList call in these screens is, so the hook count per
  // render does not depend on which guard branch was taken.
  const [, _lookupsMeta] = (typeof useChoiceList === "function")
    ? useChoiceList(
        (typeof CAPTURE_CHOICE_LISTS !== "undefined") ? CAPTURE_CHOICE_LISTS : [])
    : [[], { loading: false, error: null }];
  const lookupsLoading = !!_lookupsMeta.loading;
  // Empty geo state — operator drills the live GeographicUnit
  // hierarchy starting from Region. Each level resets descendants on
  // change (see GeoTreePicker). 7-level chain matches the UBOS model.
  const [geo, setGeo] = useStateCap({
    region: "", sub_region: "", district: "",
    county: "", sub_county: "", parish: "", village: "",
  });
  // US-CONSENT-03 — per-purpose consent (consent_block). `consent` ("yes"/"no")
  // is derived from REGISTRATION for the submission gate + backward compat.
  //
  // Starts UNSET. A consent control that opens pre-answered "Yes" records
  // a decision the respondent never made; under DPPA 2019 consent must be
  // a freely given, specific, informed indication — a default is none of
  // those. The Identification validator refuses to advance until the
  // operator has actually asked. See ADR-0031.
  const _newConsentBlock = () => (window.defaultConsentBlock
    ? window.defaultConsentBlock() : { REGISTRATION: "" });
  const [consentBlock, setConsentBlock] = useStateCap(_newConsentBlock);
  const consent = consentBlock.REGISTRATION === "GRANTED" ? "yes"
    : (consentBlock.REGISTRATION === "REFUSED" ? "no" : "");
  const [urbanRural, setUR] = useStateCap("2"); // "1"=Urban, "2"=Rural per rural_urban list
  // Household.address_narrative exists on the model and promotion already
  // writes it (`payload.get("address_narrative")`) — nothing ever
  // collected it, so the DIH panel showed "Address —" on every record.
  const [addressNarrative, setAddressNarrative] = useStateCap("");
  // GPS is what the operator reads off the device. It used to be three
  // uncontrolled inputs showing 2.49423 / 34.65103 / 6.00, while the
  // submit handler sent those same three literals for every walk-in
  // regardless of what was typed — so every household captured here
  // landed in the registry on one fabricated point in Karamoja.
  const [gps, setGps] = useStateCap({ lat: "", lng: "", accuracy: "" });
  const [submitOpen, setSubmitOpen] = useStateCap(false);
  const [showReceipt, setShowReceipt] = useStateCap(false);
  // Receipt carries the real provisional_registry_id returned by
  // /api/v1/dih/walk-in-submissions/. Null when the API call hasn't
  // landed (or fell back to the mock receipt under file://).
  const [provisionalId, setProvisionalId] = useStateCap(null);
  const [submitting, setSubmitting] = useStateCap(false);
  const [submitError, setSubmitError] = useStateCap(null);

  // ----- detail-entity state (per US-S22-DE models) -----
  // Start with an empty roster. Operators add members via the
  // Roster tab's "+ Add member" button.
  const [members, setMembers] = useStateCap([]);
  // Who answered the questions. Distinct from the head of household:
  // a neighbour or an adult child often gives the interview. Carried on
  // the canonical payload for the audit trail; the CONTACT NUMBER is
  // not stored here — see the head-telephone binding below.
  const [respondentName, setRespondentName] = useStateCap("");
  const [healthData, setHealthData] = useStateCap({});       // { line_number: { health: {...}, disability: {...} } }
  const [educationData, setEducationData] = useStateCap({}); // { line_number: { ... } }
  const [employmentData, setEmploymentData] = useStateCap({}); // { line_number: { ... } }
  const [housing, setHousing] = useStateCap({
    dwelling: {}, utilities: {}, livelihood: {},
    assets: [], crops: [], livestock: [],
  });
  const [foodShocks, setFoodShocks] = useStateCap({
    food_security: {}, food_consumption: {},
    shocks: [], coping: [],
  });

  // Per-section validation — runs in real time against the wizard
  // state. Section errors gate the Next button + colour the stepper.
  const _sectionState = {
    geo, consent, members,
    healthData, educationData, employmentData, housing, foodShocks,
  };
  const SECTION_ERRORS = Object.fromEntries(
    Object.entries(SECTION_VALIDATORS).map(
      ([sid, fn]) => [sid, fn(_sectionState)],
    ),
  );
  const _currentErrors = SECTION_ERRORS[active] || [];
  const _canAdvance = _currentErrors.length === 0;

  // Derived per-section progress — `done` when the section's
  // validator returns zero errors AND the operator has touched it
  // (we infer "touched" from having any data in the slice).
  const _touched = {
    id: !!(geo.region || geo.village || consent),
    rost: members.length > 0,
    hd: Object.keys(healthData).length > 0,
    ed: Object.keys(educationData).length > 0,
    emp: Object.keys(employmentData).length > 0,
    hous: !!(housing.dwelling.tenure || housing.utilities.cooking_fuel),
    food: !!(foodShocks.food_security.worried_food || foodShocks.shocks.length),
  };
  const SECTION_PROG = Object.fromEntries(
    SECTIONS.map(s => {
      const errs = SECTION_ERRORS[s.id] || [];
      if (errs.length > 0) return [s.id, "error"];
      if (_touched[s.id])  return [s.id, "done"];
      return [s.id, s.id === active ? "active" : "todo"];
    }),
  );
  const _doneCount = Object.values(SECTION_PROG).filter(s => s === "done").length;
  const _progPct = Math.round((_doneCount / 7) * 100);
  const _sectionOrder = ["id", "rost", "hd", "ed", "emp", "hous", "food"];
  const _sectionIdx = _sectionOrder.indexOf(active);
  const _onLastSection = _sectionIdx === _sectionOrder.length - 1;
  const _nextSectionId = _onLastSection ? null : _sectionOrder[_sectionIdx + 1];
  // On section 7 of 7 the button used to read "Next: Food & Shocks"
  // while the operator was already on Food & Shocks, and clicking it
  // did nothing. There is nowhere further to go, so it says so.
  const _nextSectionLabel = _onLastSection
    ? "Review"
    : (SECTIONS.find(s => s.id === _nextSectionId)?.label || "Done");
  const _totalErrors = Object.values(SECTION_ERRORS).reduce((n, arr) => n + arr.length, 0);

  if (device === "capi") {
    return <CapturePadCAPI onChangeDevice={onChangeDevice}/>;
  }

  const _body = (
    <div className="page" style={{paddingBottom:0}}>
      <PageHeader
        eyebrow="CAPTURES · US-088, US-112"
        title="Household capture"
        sub={`Capturing office: Parish Office, Nakiloro · Operator: Lokwang Peter (PCH-7411) · Draft saved ${formatEatTime(now)}`}
        right={<>
          <div className="seg" role="tablist" aria-label="Device variant">
            <button className="on" onClick={() => onChangeDevice?.('desktop')}>Desktop</button>
            <button onClick={() => onChangeDevice?.('capi')}>CAPI tablet</button>
          </div>
          {wide && typeof WideViewButtons === "function"
            ? <WideViewButtons wide={wide} label="capture form"/> : null}
          <button className="btn"><Icon name="history"/> Resume draft</button>
        </>}
      />

      {/* Progress stepper */}
      <div className="card" style={{padding:'14px 20px', display:'flex', alignItems:'center', gap:0, position:'sticky', top:56, zIndex:10}}>
        {SECTIONS.map((s, i) => {
          const state = SECTION_PROG[s.id];
          const isActive = s.id === active;
          const done = state === "done";
          const hasError = state === "error";
          const errCount = (SECTION_ERRORS[s.id] || []).length;
          // Active wins the colour even when it has errors; the
          // operator's currently editing — they don't need the
          // stepper screaming red at them while they type. Other
          // tabs with errors render in danger.
          const tabColor = isActive
            ? "var(--accent-data)"
            : hasError ? "var(--accent-danger)"
            : done ? "var(--neutral-700)"
            : "var(--neutral-500)";
          const circleBg = isActive
            ? "var(--accent-data)"
            : hasError ? "var(--accent-danger-bg)"
            : done ? "var(--accent-data-bg)"
            : "var(--neutral-100)";
          const circleFg = isActive
            ? "white"
            : hasError ? "var(--accent-danger)"
            : done ? "var(--accent-data)"
            : "var(--neutral-500)";
          const circleBorder = isActive ? "0"
            : `1px solid ${hasError ? "var(--accent-danger)" : done ? "var(--accent-data)" : "var(--neutral-300)"}`;
          return (
            <React.Fragment key={s.id}>
              <button onClick={() => setActive(s.id)}
                title={hasError ? `${errCount} error${errCount === 1 ? "" : "s"} on this step` : ""}
                style={{
                display:'flex', alignItems:'center', gap:8,
                padding:'6px 10px', border:0, background:'transparent',
                color: tabColor,
                fontWeight: isActive ? 600 : 500, fontSize: 13,
              }}>
                <span style={{
                  width:22, height:22, borderRadius:'50%',
                  display:'grid', placeItems:'center',
                  background: circleBg, color: circleFg,
                  fontSize:11, fontWeight:600,
                  border: circleBorder,
                }}>
                  {done ? <Icon name="check" size={12}/>
                   : hasError ? <Icon name="alert" size={12}/>
                   : i+1}
                </span>
                <span className="stretchable">{s.label}</span>
              </button>
              {i < SECTIONS.length - 1 && <div style={{flex:1, height:1, background:'var(--neutral-300)', minWidth:14}}/>}
            </React.Fragment>
          );
        })}
      </div>

      {/* 3-column form layout — see .capture-grid in styles.css for why
          the middle column has a floor and which rail drops first. */}
      <div className="capture-grid">
        {/* Left rail — section nav */}
        <div className="card capture-section-rail" style={{padding:8, alignSelf:'start', position:'sticky', top: 140}}>
          {SECTIONS.map((s) => {
            const state = SECTION_PROG[s.id];
            const isActive = s.id === active;
            const hasError = state === "error";
            const errCount = (SECTION_ERRORS[s.id] || []).length;
            return (
              <button key={s.id} onClick={() => setActive(s.id)}
                title={hasError ? `${errCount} error${errCount === 1 ? "" : "s"} on this step` : ""}
                style={{
                display:'flex', alignItems:'center', gap:10, width:'100%',
                padding:'10px 12px', border:0,
                background: isActive ? 'var(--accent-data-bg)' : 'transparent',
                borderLeft: isActive ? '3px solid var(--accent-data)'
                          : hasError ? '3px solid var(--accent-danger)'
                          : '3px solid transparent',
                color: isActive ? 'var(--accent-data)'
                     : hasError ? 'var(--accent-danger)'
                     : 'var(--neutral-900)',
                textAlign:'left', borderRadius:4, cursor:'pointer',
                fontWeight: isActive ? 600 : 500, fontSize:13,
              }}>
                <Icon name={s.icon} size={16}/>
                <span style={{flex:1}} className="stretchable">{s.label}</span>
                {state === 'done' && <Icon name="check" size={14} color="var(--accent-data)"/>}
                {hasError && (
                  <span style={{
                    minWidth: 18, height: 18, padding: "0 5px",
                    background: "var(--accent-danger)",
                    color: "white", borderRadius: 9,
                    display: "grid", placeItems: "center",
                    fontSize: 10, fontWeight: 700,
                  }}>{errCount}</span>
                )}
              </button>
            );
          })}
          <div className="divider"/>
          <div style={{padding:'8px 12px'}} className="t-cap">
            <div>Progress <strong style={{color:'var(--neutral-900)'}}>{_doneCount} of 7</strong></div>
            <div style={{height:4, background:'var(--neutral-200)', borderRadius:2, marginTop:6}}>
              <div style={{width:`${_progPct}%`, height:'100%', background:'var(--accent-data)', borderRadius:2}}/>
            </div>
          </div>
        </div>

        {/* Main form — switches body by active section */}
        <div className="card">
          {_currentErrors.length > 0 && (
            <div className="tint-danger" style={{
              margin: 16, padding: 14, borderRadius: 6,
              borderLeft: "3px solid var(--accent-danger)",
            }}>
              <div className="row gap-2" style={{ marginBottom: 6 }}>
                <Icon name="alert" size={14} color="var(--accent-danger)"/>
                <strong className="t-bodysm">
                  {_currentErrors.length} item{_currentErrors.length === 1 ? "" : "s"} to fix before continuing
                </strong>
              </div>
              <ul className="t-bodysm" style={{
                margin: "4px 0 0 22px", color: "var(--neutral-700)",
                lineHeight: 1.65,
              }}>
                {_currentErrors.slice(0, 8).map((msg, i) => <li key={i}>{msg}</li>)}
                {_currentErrors.length > 8 && (
                  <li style={{ color: "var(--neutral-500)" }}>
                    …and {_currentErrors.length - 8} more
                  </li>
                )}
              </ul>
            </div>
          )}
          {active === "id" && (
            <IdentificationSection
              capturedAt={startedAt}
              geo={geo} setGeo={setGeo}
              urbanRural={urbanRural} setUR={setUR}
              consentBlock={consentBlock} setConsentBlock={setConsentBlock}
              gps={gps} setGps={setGps}
              members={members} setMembers={setMembers}
              addressNarrative={addressNarrative} setAddressNarrative={setAddressNarrative}
              respondentName={respondentName} setRespondentName={setRespondentName}
            />
          )}
          {active === "rost" && (
            <RosterSection members={members} setMembers={setMembers}/>
          )}
          {active === "hd" && (
            <HealthDisabilitySection
              members={members}
              healthData={healthData} setHealthData={setHealthData}
            />
          )}
          {active === "ed" && (
            <EducationSection
              members={members}
              educationData={educationData} setEducationData={setEducationData}
            />
          )}
          {active === "emp" && (
            <EmploymentSection
              members={members}
              employmentData={employmentData} setEmploymentData={setEmploymentData}
            />
          )}
          {active === "hous" && (
            <HousingSection housing={housing} setHousing={setHousing}/>
          )}
          {active === "food" && (
            <FoodShocksSection foodShocks={foodShocks} setFoodShocks={setFoodShocks}/>
          )}
        </div>

        {/* Right rail — helper */}
        <div className="col gap-4 capture-helper-rail" style={{alignSelf:'start', position:'sticky', top:140}}>
          {/* DQA runs server-side on submission (apps.ingestion_hub
              _run_staging_gates), so there is nothing to preview here. The
              card used to show a fixed "3 warnings · 0 blocking" and three
              invented rule outcomes beside the operator's real entry. */}
          <div className="card">
            <div className="card-header" style={{padding:'12px 16px'}}>
              <h3 className="t-h3" style={{margin:0}}>Data quality checks</h3>
            </div>
            <div style={{padding:16}}>
              <div className="t-bodysm muted">
                The wizard checks each section as you go — errors appear on the
                tab and block <strong>Next</strong>. The full DQA ruleset runs
                on the server when you submit; its outcome appears on the
                record in the DIH review queue.
              </div>
            </div>
          </div>

          {/* Photo evidence */}
          <div className="card">
            <div className="card-header" style={{padding:'12px 16px'}}>
              <h3 className="t-h3" style={{margin:0}}>Evidence photos</h3>
              <button className="btn btn-sm btn-ghost"><Icon name="camera" size={14}/> Add</button>
            </div>
            <div style={{padding:16, display:'grid', gridTemplateColumns:'repeat(2,1fr)', gap:8}}>
              {[
                ["Dwelling exterior","var(--accent-eligibility-bg)"],
                ["NIRA card (head)","var(--accent-identity-bg)"],
                ["Household roster","var(--accent-update-bg)"],
                ["Add photo","var(--neutral-100)"],
              ].map(([label, bg], i) => (
                <div key={i} style={{aspectRatio:'1', background:bg, borderRadius:4, border:'1px dashed var(--neutral-300)', display:'grid', placeItems:'center', textAlign:'center', padding:6, fontSize:11, color:'var(--neutral-700)'}}>
                  {i === 3 ? <Icon name="plus" size={20} color="var(--neutral-500)"/> : <Icon name="camera" size={20} color="var(--neutral-500)"/>}
                  <div style={{marginTop:4}} className="stretchable">{label}</div>
                </div>
              ))}
            </div>
          </div>

          {/* The "SKIP-FS-URBAN" hint that used to sit here promised that
              choosing Urban would drop 4 questions from Food & Shocks. No
              such rule exists — not in the questionnaire (docs/06), not in
              the SAD, not in the DQA ruleset, not anywhere in the code. It
              was never wired up, and it should not be: Food & Shocks is
              FIES (8 items) and FCS (9 food groups), both standardised
              scales whose raw scores are only comparable when every item
              is asked. Dropping 4 items by settlement type would make the
              urban and rural halves of the registry incommensurable.

              Removed rather than implemented. If MGLSD does want a
              settlement-conditional instrument, it is a questionnaire
              change with an ADR and a new FormVersion, not a UI hint. */}

          {/* Offline indicator (informational) */}
          <div className="row gap-2 t-cap" style={{padding:'0 4px'}}>
            <div style={{width:8,height:8,borderRadius:'50%',background:'var(--accent-data)'}}/>
            Online · last sync {formatEatTime(now)} · 0 queued
            {lookupsLoading && <span> · loading lookups…</span>}
          </div>
        </div>
      </div>

      {/* Action bar */}
      <div style={{margin:'20px -24px 0', position:'sticky', bottom:0, zIndex:20}}>
        <ActionBar left={<>
          Section {SECTIONS.findIndex(s => s.id === active) + 1} of 7 · {_progPct}% complete
          {_totalErrors > 0 && (
            <span style={{
              marginLeft: 10, padding: "2px 8px",
              background: "var(--accent-danger-bg)",
              color: "var(--accent-danger)",
              borderRadius: 10, fontSize: 11, fontWeight: 600,
            }}>
              {_totalErrors} unresolved
            </span>
          )}
          {" · "}<span className="stretchable">Auto-saved {formatEatTime(now)}</span>
        </>}>
          <button className="btn"><Icon name="save" size={14}/> Save draft</button>
          <button className="btn"
            disabled={!_canAdvance || _onLastSection}
            title={
              _onLastSection
                ? "This is the last section — use Submit for promotion"
                : _canAdvance
                  ? `Advance to ${_nextSectionLabel}`
                  : `Fix ${_currentErrors.length} issue${_currentErrors.length === 1 ? "" : "s"} on this step first`
            }
            onClick={() => _canAdvance && _nextSectionId && setActive(_nextSectionId)}>
            <Icon name="arrowRight" size={14}/>
            {_onLastSection ? "Review" : `Next: ${_nextSectionLabel}`}
          </button>
          <button className="btn btn-primary"
            disabled={_totalErrors > 0}
            title={_totalErrors > 0
              ? `${_totalErrors} unresolved error${_totalErrors === 1 ? "" : "s"} across the wizard — fix them before submitting`
              : "Submit for promotion"
            }
            onClick={() => _totalErrors === 0 && setSubmitOpen(true)}>
            <Icon name="check" size={14}/> Submit for promotion
          </button>
        </ActionBar>
      </div>

      {/* Submit modal */}
      <Modal open={submitOpen} onClose={() => setSubmitOpen(false)} title="Submit for promotion?"
        footer={<>
          <button className="btn" onClick={() => setSubmitOpen(false)} disabled={submitting}>Cancel</button>
          <button className="btn btn-primary"
            disabled={submitting}
            onClick={async () => {
              setSubmitError(null);
              setSubmitting(true);
              // Canonical payload assembled from the wizard state.
              // Shape matches what apps.ingestion_hub.services.
              // submit_walk_in_capture lands as canonical_payload —
              // the connector accepts the wizard shape directly so
              // no client-side mapping is needed.
              const payload = {
                geographic: geo,
                urban_rural: urbanRural,
                address_narrative: addressNarrative,
                consent: consent,
                consent_block: consentBlock,
                respondent_name: respondentName,
                // The household contact number of record. Derived, not
                // separately entered: it IS the head member's
                // telephone_1, which is the column the registry indexes
                // and the review panel reads. Sent explicitly so the
                // receipt can name the number it used without
                // re-deriving it. See ADR-0033.
                contact_phone: householdContactPhone(members),
                ...(gps.lat && gps.lng ? {
                  gps_lat: gps.lat,
                  gps_lng: gps.lng,
                  gps_accuracy_m: gps.accuracy || null,
                } : {}),
                members: members,
                health: healthData,
                education: educationData,
                employment: employmentData,
                housing: housing,
                food_shocks: foodShocks,
                source_channel: "parish_walkin",
              };
              try {
                const api = (typeof window !== "undefined") ? window.nsrApi : null;
                if (api && typeof api.post === "function") {
                  const resp = await api.post("/api/v1/dih/walk-in-submissions/", payload);
                  setProvisionalId(resp.provisional_registry_id || null);
                } else {
                  // No data layer (file:// preview). Show mock receipt.
                  setProvisionalId(null);
                }
                setSubmitting(false);
                setSubmitOpen(false);
                setShowReceipt(true);
              } catch (err) {
                setSubmitting(false);
                setSubmitError(String(err && err.message ? err.message : err));
              }
            }}>
            <Icon name="check" size={14}/>{submitting ? "Submitting…" : "Confirm submission"}
          </button>
        </>}>
        <div className="col gap-3">
          <p style={{margin:0}}>This household will be assigned a <strong>provisional Registry ID</strong> and queued for NSR Unit promotion (AC-DIH-PROMOTE).</p>
          <div className="tint-quality" style={{padding:12, borderRadius:6, borderLeft:'3px solid var(--accent-quality)'}}>
            <div className="row gap-2" style={{marginBottom:6}}><Icon name="alert" size={14} color="var(--accent-quality)"/><strong className="t-bodysm">DQA runs on submission</strong></div>
            <div className="t-bodysm" style={{color:'var(--neutral-700)'}}>
              Any warnings or blocking failures are raised server-side and shown
              against this record in the DIH review queue.
            </div>
          </div>
          {/* ADR-0031. The provisional-Registry-ID message is the one
              transactional SMS: it carries the respondent's own tracking
              number, is sent once at submission on a public-task basis,
              and is named in the registration consent statement they just
              heard. Every other SMS honours COMMUNICATIONS_SMS.

              The dialog used to assert flatly that "An SMS will be sent",
              with the apostrophe written as a literal \u2019 escape
              rendered as text, on a household whose SMS purpose was OFF. */}
          <div className="t-cap">
            An audit entry will be written.
            {" "}
            {!householdContactPhone(members)
              ? "No household contact number has been recorded, so no SMS will be sent — the printed slip will be the respondent's only copy of the Registry ID."
              : consentBlock.COMMUNICATIONS_SMS === "GRANTED"
              ? "One SMS will carry the provisional Registry ID, and the respondent has agreed to further SMS updates."
              : consentBlock.COMMUNICATIONS_SMS === "REFUSED"
                ? "One SMS will carry the provisional Registry ID — a service message sent as part of registration. No other SMS will be sent: the respondent declined SMS notifications."
                : "One SMS will carry the provisional Registry ID — a service message sent as part of registration. SMS notifications were not asked, so no other SMS will be sent."}
          </div>
          {submitError && (
            <div className="tint-danger" style={{padding:10, borderRadius:6, borderLeft:'3px solid var(--accent-danger)'}}>
              <strong className="t-bodysm">Submission failed:</strong> <span className="t-bodysm">{submitError}</span>
            </div>
          )}
        </div>
      </Modal>

      {/* Receipt overlay — on Done we reset form state to blank and
          tell the shell to navigate away (default: DIH review tab,
          since the household lands in DIH staging next). */}
      {showReceipt && (
        <ReceiptOverlay provisionalId={provisionalId}
          captured={{
            at: startedAt,
            issuedAt: new Date(),
            geo,
            smsConsent: consentBlock.COMMUNICATIONS_SMS || "",
            contactPhone: householdContactPhone(members),
          }}
          onClose={() => {
          // Reset every capture slot so a return lands on a fresh form.
          setShowReceipt(false);
          setActive("id");
          setGeo({
            region: "", sub_region: "", district: "",
            county: "", sub_county: "", parish: "", village: "",
          });
          setConsentBlock(_newConsentBlock());
          setUR("2");
          setAddressNarrative("");
          setRespondentName("");
          setMembers([]);
          setHealthData({});
          setEducationData({});
          setEmploymentData({});
          setHousing({ dwelling: {}, utilities: {}, livelihood: {}, assets: [], crops: [], livestock: [] });
          setFoodShocks({ food_security: {}, food_consumption: {}, shocks: [], coping: [] });
          // Notify the shell so it can leave the capture screen.
          onPromoted && onPromoted();
        }}/>
      )}
    </div>
  );

  return (wide && typeof WideShell === "function")
    ? <WideShell wide={wide}>{_body}</WideShell>
    : _body;
};

/* ============================================================
   Section 1 — Identification (extracted for the conditional shell)
   ============================================================ */
const IdentificationSection = ({
  capturedAt, geo, setGeo, urbanRural, setUR, consentBlock, setConsentBlock,
  gps, setGps, members, setMembers, addressNarrative, setAddressNarrative,
  respondentName, setRespondentName,
}) => {
  const [urOpts] = (typeof useChoiceList === "function")
    ? useChoiceList("rural_urban")
    : [[]];
  const head = (members || []).find(m => m && m.line_number === 1) || null;
  const headName = head
    ? `${head.first_name || ""} ${head.surname || ""}`.trim()
    : "";
  // Writes through to the head member — the single household contact
  // number (ADR-0033), not a copy of it.
  const setHeadPhone = (value) => {
    if (!head || !setMembers) return;
    setMembers((members || []).map(m => (
      m.line_number === head.line_number ? { ...m, telephone_1: value } : m
    )));
  };
  return (
    <>
      <div className="card-header">
        <div>
          <div className="t-cap">SECTION 1 OF 7 · ACTIVE</div>
          <h3 className="t-h2" style={{ margin: 0 }}>Identification</h3>
        </div>
        <Chip>Draft</Chip>
      </div>
      <div style={{ padding: 20 }}>
        <h4 className="t-h3" style={{ margin: '0 0 16px' }}>Location</h4>
        <GeoTreePicker value={geo} onChange={setGeo}/>

        <div className="divider mt-5"/>

        <h4 className="t-h3" style={{ margin: '8px 0 16px' }}>Household identifiers</h4>
        <div className="field-row-3">
          <Field label="Household number" required hint="Auto-generated on first save">
            <input className="field-input" defaultValue="HH-7411-002-0148" readOnly/>
          </Field>
          <Field label="Urban / Rural" required>
            <div className="seg">
              {(urOpts.length ? urOpts : [{ code: "1", label: "Urban" }, { code: "2", label: "Rural" }]).map(o => (
                <button key={o.code}
                  className={urbanRural === o.code ? 'on' : ''}
                  aria-pressed={urbanRural === o.code}
                  onClick={() => setUR(o.code)}>
                  {o.label}
                </button>
              ))}
            </div>
          </Field>
          <Field label="Date captured">
            <div className="row gap-2"><Icon name="clock" size={14} color="var(--neutral-500)"/><span className="t-bodysm">{formatEatStamp(capturedAt)}</span></div>
          </Field>
        </div>

        <div className="divider mt-5"/>

        <h4 className="t-h3" style={{ margin: '8px 0 16px' }}>GPS reading</h4>
        <div className="field-row-3">
          <Field label="Latitude">
            <input className="field-input t-mono" value={gps.lat} placeholder="e.g. 0.31628"
                   onChange={e => setGps({ ...gps, lat: e.target.value })}/>
          </Field>
          <Field label="Longitude">
            <input className="field-input t-mono" value={gps.lng} placeholder="e.g. 32.58219"
                   onChange={e => setGps({ ...gps, lng: e.target.value })}/>
          </Field>
          <Field label="Accuracy" hint="Must be ≤ 10m (AC-GPS-ACCURACY)"
                 error={gps.accuracy !== "" && Number(gps.accuracy) > 10
                   ? `${gps.accuracy} m — above the 10 m limit`
                   : undefined}>
            <div className="input-affix">
              <input className="t-mono" value={gps.accuracy} placeholder="m"
                     onChange={e => setGps({ ...gps, accuracy: e.target.value })}/>
              <span className="affix">m</span>
            </div>
          </Field>
        </div>
        <div className="t-cap mt-2" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <Icon name="mapPin" size={12} color="var(--neutral-500)"/>
          {gps.lat && gps.lng
            ? `Will be submitted as ${gps.lat}, ${gps.lng}${gps.accuracy ? ` · accuracy ${gps.accuracy} m` : " · no accuracy given"}`
            : "No position entered — the record will be submitted without GPS and flagged by AC-GPS-ACCURACY."}
        </div>

        <div className="divider mt-5"/>

        <h4 className="t-h3" style={{ margin: '8px 0 16px' }}>Respondent</h4>
        <div className="field-row-3">
          <Field label="Respondent name" required
            hint="Who answered the questions — not necessarily the head">
            <input className="field-input" placeholder="As given by the respondent"
              value={respondentName || ""}
              onChange={(e) => setRespondentName && setRespondentName(e.target.value)}/>
          </Field>
          {/* Household contact number — the SAME value as Person 1's
              Telephone on the Roster tab (ADR-0033). Editing either
              edits the head member's telephone_1; there is no second
              number to fall out of step. */}
          <Field label="Household phone (E.164)" required
            hint={head
              ? "Format: +256 XXX XXXXXX · same field as Person 1's Telephone"
              : "Add the head of household on the Roster tab first"}>
            <input className="field-input" placeholder="+256 XXX XXXXXX"
              disabled={!head}
              value={(head && head.telephone_1) || ""}
              onChange={(e) => setHeadPhone(e.target.value)}/>
          </Field>
          <Field label="Head of household" hint="From Roster Person 01">
            <input className="field-input" readOnly
              value={headName}
              placeholder="—"
              style={{ background: 'var(--neutral-50)', color: 'var(--neutral-700)' }}/>
          </Field>
        </div>

        <div className="divider mt-5"/>

        <h4 className="t-h3" style={{ margin: '8px 0 16px' }}>Address</h4>
        <Field label="Address narrative"
          hint="Landmarks and directions, as given. Free text — the coded location is the geographic chain above.">
          <input className="field-input"
            placeholder="e.g. third homestead past Burcoro trading centre, blue gate"
            value={addressNarrative || ""}
            onChange={(e) => setAddressNarrative && setAddressNarrative(e.target.value)}/>
        </Field>

        <div className="divider mt-5"/>

        <h4 className="t-h3" style={{ margin: '8px 0 16px' }}>Consent <span style={{ color: 'var(--accent-danger)' }}>*</span></h4>
        {typeof window !== 'undefined' && typeof window.ConsentCaptureBlock === 'function' ? (
          React.createElement(window.ConsentCaptureBlock, { value: consentBlock, onChange: setConsentBlock })
        ) : (
          // Fallback to the legacy single toggle if the consent module bundle
          // is not loaded.
          <div className="tint-update" style={{ padding: 16, borderRadius: 6, borderLeft: '3px solid var(--accent-update)' }}>
            <div className="seg">
              <button className={(consentBlock || {}).REGISTRATION === 'GRANTED' ? 'on' : ''} onClick={() => setConsentBlock({ ...(consentBlock || {}), REGISTRATION: 'GRANTED' })}><Icon name="check" size={12}/> Yes — consented</button>
              <button className={(consentBlock || {}).REGISTRATION === 'REFUSED' ? 'on' : ''} onClick={() => setConsentBlock({ ...(consentBlock || {}), REGISTRATION: 'REFUSED' })}>No</button>
            </div>
          </div>
        )}
      </div>
    </>
  );
};

const DQARow = ({ tone, rule, detail }) => (
  <div style={{padding:'8px 10px', borderLeft:`3px solid var(--accent-${tone})`, background:`var(--accent-${tone}-bg)`, borderRadius:4, marginBottom:8}}>
    <div className="row gap-2" style={{justifyContent:'space-between', marginBottom:2}}>
      <span className="t-mono" style={{fontSize:11, color:`var(--accent-${tone})`, fontWeight:600}}>{rule}</span>
      <Chip tone={tone} size="sm">{tone === 'quality' ? 'Warning' : tone === 'danger' ? 'Blocking' : 'Info'}</Chip>
    </div>
    <div className="t-bodysm" style={{color:'var(--neutral-700)'}}>{detail}</div>
  </div>
);

/* ============================================================
   CAPI tablet variant — single question per screen
   ============================================================ */
const CapturePadCAPI = ({ onChangeDevice }) => {
  const now = useEatClock();
  return (
    <div className="page" style={{display:'grid', placeItems:'center', minHeight:'80vh'}}>
      <div className="row gap-3" style={{marginBottom:16}}>
        <span className="t-cap">CAPI variant · 720×540 landscape · offline-first runtime</span>
        <div className="seg">
          <button onClick={() => onChangeDevice?.('desktop')}>Desktop</button>
          <button className="on">CAPI tablet</button>
        </div>
      </div>

      <div style={{width:720, height:540, background:'var(--neutral-0)', borderRadius:24, overflow:'hidden', boxShadow:'0 24px 60px rgba(0,0,0,0.18), 0 0 0 8px #1A1A1A, 0 0 0 10px #2A2A2A', display:'grid', gridTemplateRows:'auto 1fr auto'}}>
        {/* CAPI status bar */}
        <div style={{padding:'10px 16px', background:'var(--primary-900)', color:'white', display:'flex', alignItems:'center', justifyContent:'space-between', fontSize:12}}>
          <div className="row gap-3">
            <strong>NSR CAPI</strong>
            <span style={{opacity:0.7}}>HH-7411-002-0148 · Section 1/7</span>
          </div>
          <div className="row gap-3">
            <span style={{opacity:0.8}}><Icon name="mapPin" size={12}/> GPS 6m</span>
            <span style={{display:'inline-flex', alignItems:'center', gap:4, opacity:0.8}}>
              <span style={{width:6,height:6,borderRadius:'50%',background:'#FFB300'}}/> Offline · 3 queued
            </span>
            <span style={{opacity:0.8}}>92%</span>
            <span>{_eatTime(now)}</span>
          </div>
        </div>

        {/* Progress */}
        <div style={{padding:'24px 32px', display:'grid', gridTemplateRows:'auto auto 1fr', gap:16}}>
          <div>
            <div className="t-cap">Section 1 · Identification · Q 4 of 9</div>
            <div style={{height:6, background:'var(--neutral-200)', borderRadius:3, marginTop:6}}>
              <div style={{width:'14%', height:'100%', background:'var(--accent-data)', borderRadius:3}}/>
            </div>
          </div>

          <h2 className="t-h1" style={{margin:0, fontSize:22, lineHeight:'30px'}}>What is the respondent's primary phone number?</h2>
          <div className="t-bodysm muted" style={{margin:'-8px 0 0'}}>Used for SMS receipt and status notifications. Format: +256 XXX XXXXXX.</div>

          <div className="col gap-4">
            <div className="input-affix" style={{height:56, fontSize:18}}>
              <span className="affix" style={{fontSize:16, padding:'0 14px'}}>+256</span>
              <input className="t-mono" style={{fontSize:18}} defaultValue="786 234567"/>
            </div>
            <div className="row gap-2"><Icon name="info" size={14} color="var(--neutral-500)"/><span className="t-bodysm muted">SMS will be sent at submission · operator hours 06:00 — 22:00 EAT</span></div>
          </div>
        </div>

        {/* CAPI bottom bar */}
        <div style={{padding:'12px 16px', borderTop:'1px solid var(--neutral-200)', display:'flex', alignItems:'center', justifyContent:'space-between', background:'var(--neutral-50)'}}>
          <button className="btn btn-lg"><Icon name="chevronLeft"/> Back</button>
          <button className="btn btn-lg btn-ghost"><Icon name="save"/> Save & exit</button>
          <button className="btn btn-lg btn-primary">Next <Icon name="chevronRight"/></button>
        </div>
      </div>
      <div className="t-cap mt-3" style={{maxWidth:640, textAlign:'center'}}>
        Touch target ≥ 48 dp · Talkback enabled · large-text mode toggle in profile · drafts persist for 14 days
      </div>
    </div>
  );
};

/* ============================================================
   11.2 Receipt slip overlay
   ============================================================ */
const ReceiptOverlay = ({ onClose, provisionalId, captured }) => {
  // ONE source of truth: the provisional Registry ID the server
  // persisted on the StageRecord and returned from
  // /api/v1/dih/walk-in-submissions/. The slip, the SMS preview and the
  // DIH queue row all render THIS value.
  //
  // There is deliberately no invented fallback. A slip that prints a
  // plausible-looking ID the registry has never heard of is worse than a
  // slip that says the ID could not be issued: the respondent walks away
  // holding a tracking number nobody can look up.
  const displayId = provisionalId || null;
  const capturedAt = captured || {};
  const contactPhone = (capturedAt.contactPhone || "").trim();
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" style={{maxWidth:980, display:'grid', gridTemplateColumns:'1fr 1fr', gap:0, padding:0}} onClick={(e) => e.stopPropagation()}>
        {/* Left — A6 slip */}
        <div style={{padding:24, borderRight:'1px solid var(--neutral-200)', background:'var(--neutral-100)'}}>
          <div className="t-cap" style={{marginBottom:8}}>A6 PRINT · 105 × 148 mm · THERMAL-FRIENDLY</div>
          <ReceiptSlipA6 provisionalId={displayId} captured={capturedAt}/>
        </div>
        {/* Right — SMS + actions */}
        <div style={{padding:24}}>
          <div className="row gap-2" style={{marginBottom:6}}>
            <Chip>Provisional</Chip>
            <span className="t-cap">Generated {formatEatTime(capturedAt.issuedAt || new Date())}</span>
          </div>
          <h2 className="t-h2" style={{margin:'4px 0 8px'}}>
            {displayId ? "Provisional Registry ID issued" : "No Registry ID was issued"}
          </h2>
          {displayId ? (
            <p className="t-body" style={{color:'var(--neutral-700)', marginTop:0}}>
              Hand the printed slip to the respondent.
              {" "}
              {/* Name the number, or say plainly that there isn't one.
                  "queued to the number recorded for this household" was
                  asserted on a household whose record held no number at
                  all — so either nothing was sent, or something was sent
                  somewhere the record cannot account for. ADR-0033. */}
              {contactPhone ? (<>
                One SMS carrying this ID has been queued to{" "}
                <strong className="t-mono">{contactPhone}</strong>, the household
                contact number on this record.
                {" "}
                {capturedAt.smsConsent === "GRANTED"
                  ? "The respondent has agreed to further SMS updates."
                  : "It is a service message sent as part of registration (ADR-0031); no other SMS will follow, because the respondent did not agree to SMS notifications."}
              </>) : (<>
                <strong>No SMS has been sent.</strong> This record holds no
                household contact number, so there is nowhere to send one.
                The printed slip is the respondent's only copy of this ID —
                make sure they leave with it. A number can be added to the
                head of household on the record, and the SMS re-sent, from
                the DIH review queue.
              </>)}
            </p>
          ) : (
            <div className="tint-danger" style={{padding:12, borderRadius:6, borderLeft:'3px solid var(--accent-danger)'}}>
              <div className="t-bodysm">
                The submission did not return a Registry ID, so there is nothing to
                print and nothing to send. <strong>Do not hand out a slip.</strong>{" "}
                Find the household in the DIH review queue and re-issue from there.
              </div>
            </div>
          )}

          {displayId && (
          <div className="card" style={{padding:14, marginTop:12}}>
            <div className="t-cap" style={{marginBottom:6}}>SMS PREVIEW · 160 char</div>
            <div className="t-mono" style={{fontSize:12.5, lineHeight:1.55, padding:10, background:'var(--neutral-50)', borderRadius:4, color:'var(--neutral-900)'}}>
              MGLSD NSR: Your provisional Registry ID is {displayId}. Pending approval. Track via parish office or SMS HELP to 8800.
            </div>
            <div className="t-cap mt-2">
              {`MGLSD NSR: Your provisional Registry ID is ${displayId}. Pending approval. Track via parish office or SMS HELP to 8800.`.length} / 160 characters · UTF-8 safe
            </div>
          </div>
          )}

          <div className="card mt-4" style={{padding:14}}>
            <div className="t-cap" style={{marginBottom:6}}>NEXT IN THE PIPELINE</div>
            <div className="col gap-2">
              <div className="row gap-3"><span style={{width:18,height:18,borderRadius:'50%',background:'var(--accent-data-bg)',color:'var(--accent-data)',display:'grid',placeItems:'center',fontSize:11,fontWeight:600}}>1</span><span className="t-bodysm">Captured at parish · <strong>now</strong></span></div>
              <div className="row gap-3"><span style={{width:18,height:18,borderRadius:'50%',background:'var(--accent-update-bg)',color:'var(--accent-update)',display:'grid',placeItems:'center',fontSize:11,fontWeight:600}}>2</span><span className="t-bodysm">DIH staging · DQA + IDV checks · ~10 min</span></div>
              <div className="row gap-3"><span style={{width:18,height:18,borderRadius:'50%',background:'var(--accent-quality-bg)',color:'var(--accent-quality)',display:'grid',placeItems:'center',fontSize:11,fontWeight:600}}>3</span><span className="t-bodysm">NSR Unit review · within 24 hours (walk-in SLA)</span></div>
              <div className="row gap-3"><span style={{width:18,height:18,borderRadius:'50%',background:'var(--neutral-100)',color:'var(--neutral-500)',display:'grid',placeItems:'center',fontSize:11,fontWeight:600}}>4</span><span className="t-bodysm muted">Promoted to <strong>Registered</strong> · same ID, no re-issue</span></div>
            </div>
          </div>

          <div className="row gap-3 mt-4">
            <button className="btn"><Icon name="print"/> Print A6</button>
            <button className="btn"><Icon name="phone"/> Resend SMS</button>
            <button className="btn"><Icon name="download"/> Save PDF</button>
            <div style={{flex:1}}/>
            <button className="btn btn-primary" onClick={onClose}>Done</button>
          </div>
        </div>
      </div>
    </div>
  );
};

const ReceiptSlipA6 = ({ provisionalId, captured } = {}) => {
  const c = captured || {};
  const labels = (c.geo && c.geo._labels) || {};
  // The household's OWN place, from the geographic chain the operator
  // drilled — not the office they happened to be standing in. The slip
  // used to print "Captured at: Parish Office, Nakiloro · Moroto" for
  // households in Gulu and Isingiro, with nothing on it to say where the
  // household actually was.
  const householdPlace = [labels.parish, labels.sub_county, labels.district]
    .filter(Boolean).join(" · ");
  const issued = c.issuedAt || c.at || new Date();
  return (
  <div style={{
    width: 380, height: 540,
    background:'white', boxShadow:'0 8px 24px rgba(0,0,0,0.12)',
    padding:'18px 22px', fontFamily:'Calibri, "Segoe UI", sans-serif',
    fontSize:11, lineHeight:1.5, color:'#111',
    display:'flex', flexDirection:'column', gap:8,
    border:'1px solid var(--neutral-300)',
  }}>
    <div className="row" style={{gap:8, borderBottom:'1px solid #111', paddingBottom:8}}>
      <div style={{width:28, height:28, background:'#111', color:'white', display:'grid', placeItems:'center', fontSize:9, fontWeight:700, letterSpacing:'.04em'}}>MGLSD</div>
      <div style={{flex:1}}>
        <div style={{fontWeight:700, fontSize:11, letterSpacing:'.02em'}}>MGLSD — NATIONAL SOCIAL REGISTRY</div>
        <div style={{fontSize:9, color:'#444'}}>Ministry of Gender, Labour and Social Development · Republic of Uganda</div>
      </div>
    </div>

    <div>
      <div style={{fontSize:9, color:'#444', letterSpacing:'.06em', textTransform:'uppercase'}}>Provisional Registry ID</div>
      <div style={{fontFamily:'"JetBrains Mono", ui-monospace, monospace', fontSize:12.5, letterSpacing:'.02em', wordBreak:'break-all', fontWeight:700, marginTop:2}}>
        {provisionalId || "— NOT ISSUED — do not hand out this slip —"}
      </div>
    </div>

    <div style={{display:'grid', gridTemplateColumns:'104px 1fr', rowGap:3, columnGap:6, marginTop:2}}>
      <div style={{color:'#666'}}>Household at:</div><div>{householdPlace || "—"}</div>
      <div style={{color:'#666'}}>Captured by office:</div><div>Parish Office, Nakiloro · Moroto</div>
      <div style={{color:'#666'}}>Date:</div><div>{formatEatStamp(issued)}</div>
      <div style={{color:'#666'}}>Contact number:</div><div>{c.contactPhone || "none recorded"}</div>
      <div style={{color:'#666'}}>Operator:</div><div>Lokwang Peter (PCH-7411)</div>
      <div style={{color:'#666'}}>Status:</div><div style={{fontWeight:700}}>Pending NSR Unit approval</div>
    </div>

    <div style={{borderTop:'1px solid #ccc', paddingTop:8, marginTop:4}}>
      <div style={{fontWeight:700, fontSize:10, marginBottom:4, letterSpacing:'.02em', textTransform:'uppercase'}}>Track your status</div>
      <ul style={{margin:0, paddingLeft:14, fontSize:10, lineHeight:1.55}}>
        <li>Quote your Provisional Registry ID at any parish office.</li>
        <li>SMS HELP to 8800 for status (operator hours).</li>
        <li>You will receive an SMS within 24 hours confirming Registered status, or a reason if the application is held.</li>
      </ul>
    </div>

    <div style={{fontSize:9.5, color:'#222', borderTop:'1px solid #ccc', paddingTop:8, marginTop:'auto'}}>
      Your Provisional Registry ID <strong>becomes</strong> your confirmed Registry ID on approval. Same number, no re-issue.
    </div>

    <div className="row" style={{justifyContent:'space-between', gap:12, borderTop:'1px solid #111', paddingTop:8, alignItems:'flex-end'}}>
      <div style={{fontSize:8.5, color:'#444', flex:1}}>
        Collected and processed under the Data Protection and Privacy Act 2019 (Uganda). Controller: MGLSD-NSR. Data subject rights: see mglsd.go.ug/nsr/privacy.
      </div>
      {/* QR placeholder */}
      <div style={{width:56, height:56, background:'repeating-linear-gradient(45deg, #111 0 4px, #fff 4px 8px)', border:'1px solid #111'}}/>
    </div>
  </div>
  );
};

const ReceiptScreen = () => (
  <div className="page">
    <PageHeader
      eyebrow="CAPTURES · US-112"
      title="Provisional Registry ID receipt"
      sub="A6 printable slip and matching SMS for the citizen."
      right={<>
        <button className="btn"><Icon name="phone"/> Resend SMS</button>
        <button className="btn"><Icon name="print"/> Print A6</button>
        <button className="btn btn-primary"><Icon name="download"/> Save as PDF</button>
      </>}
    />
    <div style={{display:'grid', gridTemplateColumns:'420px 1fr', gap:24}}>
      <div className="col gap-3">
        <div className="t-cap">A6 PRINT PREVIEW · 105 × 148 mm</div>
        <ReceiptSlipA6/>
      </div>
      <div className="col gap-4">
        <div className="card">
          <div className="card-header" style={{padding:'12px 16px'}}><h3 className="t-h3" style={{margin:0}}>SMS template</h3><span className="t-cap">160 char limit</span></div>
          <div style={{padding:16}}>
            <div className="t-mono" style={{padding:12, background:'var(--neutral-50)', borderRadius:4, fontSize:13, lineHeight:1.55, border:'1px solid var(--neutral-200)'}}>
              MGLSD NSR: Your provisional Registry ID is &#123;provisional_registry_id&#125;. Pending approval. Track via parish office or SMS HELP to 8800.
            </div>
            <div className="t-cap mt-2">
              Template. The ID is substituted from the persisted
              StageRecord.provisional_registry_id at send time — never
              re-derived, never re-generated.
            </div>
          </div>
        </div>

        <div className="card">
          <div className="card-header" style={{padding:'12px 16px'}}>
            <h3 className="t-h3" style={{margin:0}}>Content blocks (Section 11.2)</h3>
            <Chip>Approved</Chip>
          </div>
          <div style={{padding:16}}>
            {(() => { const _blocks = [
              "MGLSD wordmark and full programme name",
              "Provisional Registry ID (ULID, monospace)",
              "Household at — the household's own Parish · Sub-county · District",
              "Captured by office — the capturing office, labelled as such",
              "Date and time (East Africa Time, at capture)",
              "Operator name and code",
              "Status: Pending NSR Unit approval",
              "Track your status — three numbered actions",
              "Provisional → confirmed clarification (same number)",
              "Data Protection and Privacy Act 2019 footer",
            ]; return _blocks.map((line, i) => (
              <div key={i} className="row gap-3" style={{padding:'6px 0', borderBottom: i < _blocks.length - 1 ? '1px solid var(--neutral-200)' : 'none'}}>
                <span style={{width:22, height:22, borderRadius:'50%', background:'var(--accent-data-bg)', color:'var(--accent-data)', display:'grid', placeItems:'center', fontSize:11, fontWeight:600}}>{i+1}</span>
                <span className="t-bodysm">{line}</span>
              </div>
            )); })()}
          </div>
        </div>

        <div className="card" style={{borderLeft:'3px solid var(--accent-update)'}}>
          <div style={{padding:16}}>
            <div className="row gap-2" style={{marginBottom:8}}>
              <Icon name="info" size={16} color="var(--accent-update)"/>
              <strong className="t-bodysm">Lifecycle reminder</strong>
            </div>
            <p className="t-bodysm" style={{margin:0, color:'var(--neutral-700)'}}>
              The provisional Registry ID is real. On approval it is promoted to <strong>Registered</strong> without re-issue. On rejection, the ID is voided and the citizen receives an SMS with a reason.
            </p>
          </div>
        </div>
      </div>
    </div>
  </div>
);

Object.assign(window, {
  CaptureScreen, ReceiptScreen, ReceiptOverlay, ReceiptSlipA6,
  householdContactPhone, formatEatStamp, formatEatTime,
});
