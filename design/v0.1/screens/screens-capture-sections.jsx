/* global React, Icon, Chip, Field, useChoiceList */
// NSR MIS — Household capture · Sections 2–7
// =====================================================
// Form components for the wizard's remaining tabs.
// Section 1 (Identification) stays in screens-capture.jsx because
// it's the entry point and uses GeoTreePicker / consent text.
//
// Mapping (questionnaire §A → model):
//   Section B/C → Roster (Member 1:N, mandatory)
//   Section D   → Health & Disability (Member 1:1 each)
//   Section E   → Education (Member 1:1)
//   Section F   → Employment (Member 1:1)
//   Section G/H → Housing (Dwelling + Utilities + Livelihood + Assets/Crops/Livestock)
//   Section I/K/L → Food & Shocks (FoodSecurity + FoodConsumption + Shock + CopingStrategy)
//
// Choice-list bindings come from apps/data_management/choice_field_map.py
// (ADR-0010). Every <select> reads through useChoiceList — no
// hardcoded <option> arrays.

const { useState: useStateSec, useMemo: useMemoSec } = React;

/* ───────────────────────────────────────────────────────────────
   Shared primitives
   ─────────────────────────────────────────────────────────────── */

// Native <select> bound to a ChoiceList. Empty value renders an
// "— Select —" placeholder. `lang` defaults to "en" via the hook.
const ChoiceSelect = ({ listName, value, onChange, allowBlank = true, disabled = false }) => {
  const [options, meta] = (typeof useChoiceList === "function")
    ? useChoiceList(listName)
    : [[], { loading: false, error: null }];
  return (
    <select
      className="field-input"
      value={value || ""}
      onChange={(e) => onChange && onChange(e.target.value)}
      disabled={disabled || (meta && meta.loading)}
      style={{ minWidth: 0 }}>
      {allowBlank && <option value="">{meta && meta.loading ? "Loading…" : "— Select —"}</option>}
      {options.map(o => (
        <option key={o.code} value={o.code}>{o.label}</option>
      ))}
    </select>
  );
};

// Yes / No segmented button bound to the seeded `yes_no` ChoiceList.
// The questionnaire uses code "1" for Yes, "2" for No (Uganda XLSForm
// convention) — surfacing the codes through useChoiceList means we
// don't hardcode them and the form stays correct if seeds shift.
const YesNoSeg = ({ value, onChange }) => {
  const [opts] = (typeof useChoiceList === "function")
    ? useChoiceList("yes_no")
    : [[]];
  return (
    <div className="seg">
      {(opts.length ? opts : [{ code: "1", label: "Yes" }, { code: "2", label: "No" }]).map(o => (
        <button key={o.code}
          className={value === o.code ? "on" : ""}
          onClick={() => onChange && onChange(o.code)}>
          {o.label}
        </button>
      ))}
    </div>
  );
};

// Heading + helper text under a section card.
const SectionHead = ({ title, sub, right }) => (
  <div className="card-header">
    <div>
      <div className="t-cap">{sub}</div>
      <h3 className="t-h2" style={{ margin: 0 }}>{title}</h3>
    </div>
    {right}
  </div>
);

// Member selector — used by per-member sections (Health, Education,
// Employment, Disability). Renders a horizontal chip strip; clicking
// a chip switches the active member for the section.
const MemberPicker = ({ members, value, onChange, minAge = 0 }) => {
  if (!members || members.length === 0) {
    return (
      <div className="tint-quality" style={{ padding: 12, borderRadius: 6, borderLeft: "3px solid var(--accent-quality)" }}>
        <div className="row gap-2"><Icon name="alert" size={14} color="var(--accent-quality)"/><span className="t-bodysm">Add members on the Roster tab first.</span></div>
      </div>
    );
  }
  const eligible = members.filter(m => (m.age_years || 0) >= minAge);
  return (
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap", padding: "0 0 12px" }}>
      {eligible.map(m => {
        const active = value === m.line_number;
        return (
          <button key={m.line_number}
            onClick={() => onChange && onChange(m.line_number)}
            style={{
              padding: "6px 12px", border: "1px solid",
              borderColor: active ? "var(--accent-data)" : "var(--neutral-300)",
              background: active ? "var(--accent-data-bg)" : "var(--neutral-0)",
              color: active ? "var(--accent-data)" : "var(--neutral-900)",
              borderRadius: 4, cursor: "pointer", fontSize: 12.5,
              fontWeight: active ? 600 : 500,
            }}>
            #{m.line_number} · {(m.first_name || "—")} {m.surname || ""}{m.age_years != null && ` · ${m.age_years}y`}
          </button>
        );
      })}
      {eligible.length === 0 && (
        <span className="t-cap">No members meet the age threshold ({minAge}+).</span>
      )}
    </div>
  );
};

/* ───────────────────────────────────────────────────────────────
   Section 2 — Roster  (Section B + C; mandatory)
   ─────────────────────────────────────────────────────────────── */

const _emptyMember = (line_number) => ({
  line_number,
  surname: "",
  first_name: "",
  other_name: "",
  relationship_to_head: line_number === 1 ? "01" : "",
  sex: "",
  date_of_birth: "",
  age_years: null,
  marital_status: "",
  nationality: "",
  residency_status: "",
  birth_certificate_status: "",
  nin_status: "8",
  nin_last4: "",
  telephone_1: "",
  telephone_2: "",
});

const RosterSection = ({ members, setMembers }) => {
  const [editing, setEditing] = useStateSec(members.length ? members[0].line_number : null);

  const add = () => {
    const next = (members[members.length - 1]?.line_number || 0) + 1;
    const updated = [...members, _emptyMember(next)];
    setMembers(updated);
    setEditing(next);
  };

  const remove = (line) => {
    if (line === 1) return; // head cannot be removed; replace via re-capture
    setMembers(members.filter(m => m.line_number !== line));
    setEditing(members[0]?.line_number || null);
  };

  const update = (line, patch) => {
    setMembers(members.map(m => m.line_number === line ? { ...m, ...patch } : m));
  };

  const current = members.find(m => m.line_number === editing);

  return (
    <>
      <SectionHead
        title="Household roster"
        sub="SECTION 2 OF 7 · MEMBERS (Section B + C)"
        right={<Chip tone={members.length > 0 ? "data" : "danger"}>{members.length || 0} member{members.length === 1 ? "" : "s"}</Chip>}
      />
      <div style={{ padding: 20 }}>
        <div className="row gap-3" style={{ marginBottom: 14, flexWrap: "wrap" }}>
          {members.map(m => {
            const active = m.line_number === editing;
            const isHead = m.line_number === 1;
            const display = `${m.first_name || "—"} ${m.surname || ""}`.trim();
            return (
              <button key={m.line_number}
                onClick={() => setEditing(m.line_number)}
                style={{
                  display: "flex", alignItems: "center", gap: 6,
                  padding: "8px 12px", border: "1px solid",
                  borderColor: active ? "var(--accent-data)" : "var(--neutral-300)",
                  background: active ? "var(--accent-data-bg)" : "var(--neutral-0)",
                  color: active ? "var(--accent-data)" : "var(--neutral-900)",
                  borderRadius: 4, cursor: "pointer", fontSize: 13,
                  fontWeight: active ? 600 : 500,
                }}>
                <span>#{m.line_number}</span>
                <span className="stretchable">{display || "(new)"}</span>
                {isHead && <Chip size="sm" tone="programme">Head</Chip>}
              </button>
            );
          })}
          <button className="btn btn-sm" onClick={add}>
            <Icon name="plus" size={14}/> Add member
          </button>
        </div>

        {current ? (
          <RosterMemberForm
            member={current}
            isHead={current.line_number === 1}
            onChange={(patch) => update(current.line_number, patch)}
            onRemove={() => remove(current.line_number)}
          />
        ) : (
          <div className="tint-update" style={{ padding: 14, borderRadius: 6, borderLeft: "3px solid var(--accent-update)" }}>
            Click <strong>Add member</strong> to enumerate the head of household first.
          </div>
        )}
      </div>
    </>
  );
};

const RosterMemberForm = ({ member, isHead, onChange, onRemove }) => (
  <div className="col gap-4">
    <h4 className="t-h3" style={{ margin: 0 }}>
      Person {member.line_number} {isHead && <Chip tone="programme">Head of household</Chip>}
    </h4>

    <div className="field-row-3">
      <Field label="Surname" required>
        <input className="field-input" value={member.surname || ""}
          onChange={(e) => onChange({ surname: e.target.value })}/>
      </Field>
      <Field label="First name" required>
        <input className="field-input" value={member.first_name || ""}
          onChange={(e) => onChange({ first_name: e.target.value })}/>
      </Field>
      <Field label="Other name(s)">
        <input className="field-input" value={member.other_name || ""}
          onChange={(e) => onChange({ other_name: e.target.value })}/>
      </Field>
    </div>

    <div className="field-row-3">
      <Field label="Sex" required>
        <ChoiceSelect listName="sex" value={member.sex}
          onChange={(v) => onChange({ sex: v })}/>
      </Field>
      <Field label="Relationship to head" required>
        <ChoiceSelect listName="relationship" value={member.relationship_to_head}
          onChange={(v) => onChange({ relationship_to_head: v })}
          disabled={isHead}/>
      </Field>
      <Field label="Marital status">
        <ChoiceSelect listName="marital_status" value={member.marital_status}
          onChange={(v) => onChange({ marital_status: v })}/>
      </Field>
    </div>

    <div className="field-row-3">
      <Field label="Date of birth" hint="YYYY-MM-DD; or supply age below">
        <input className="field-input t-mono" type="date" value={member.date_of_birth || ""}
          onChange={(e) => onChange({ date_of_birth: e.target.value })}/>
      </Field>
      <Field label="Age (years)" hint="Computed from DoB on save when both supplied">
        <input className="field-input t-num" type="number" min="0" max="120"
          value={member.age_years ?? ""}
          onChange={(e) => onChange({ age_years: e.target.value === "" ? null : Number(e.target.value) })}/>
      </Field>
      <Field label="Birth certificate status">
        <ChoiceSelect listName="birth_certificate" value={member.birth_certificate_status}
          onChange={(v) => onChange({ birth_certificate_status: v })}/>
      </Field>
    </div>

    <div className="field-row-3">
      <Field label="Nationality">
        <ChoiceSelect listName="nationality" value={member.nationality}
          onChange={(v) => onChange({ nationality: v })}/>
      </Field>
      <Field label="Residency status">
        <ChoiceSelect listName="residency_status" value={member.residency_status}
          onChange={(v) => onChange({ residency_status: v })}/>
      </Field>
      <Field label="NIN status">
        <ChoiceSelect listName="nin_status" value={member.nin_status}
          onChange={(v) => onChange({ nin_status: v })}/>
      </Field>
    </div>

    <div className="field-row-3">
      <Field label="NIN — last 4 digits" hint="Stored last-4 only; full NIN at IDV step">
        <input className="field-input t-mono" maxLength={4}
          value={member.nin_last4 || ""}
          onChange={(e) => onChange({ nin_last4: e.target.value.replace(/\D/g, "").slice(0, 4) })}/>
      </Field>
      <Field label="Telephone (E.164)" hint="+256 XXX XXXXXX">
        <input className="field-input" value={member.telephone_1 || ""}
          onChange={(e) => onChange({ telephone_1: e.target.value })}/>
      </Field>
      <Field label="Alternative telephone">
        <input className="field-input" value={member.telephone_2 || ""}
          onChange={(e) => onChange({ telephone_2: e.target.value })}/>
      </Field>
    </div>

    {!isHead && (
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button className="btn btn-sm" onClick={onRemove}
          style={{ color: "var(--accent-danger)" }}>
          <Icon name="trash" size={12}/> Remove member
        </button>
      </div>
    )}
  </div>
);

/* ───────────────────────────────────────────────────────────────
   Section 3 — Health & Disability (per member, age 2+)
   ─────────────────────────────────────────────────────────────── */

const HealthDisabilitySection = ({ members, healthData, setHealthData }) => {
  const [active, setActive] = useStateSec(members[0]?.line_number || null);
  const data = healthData[active] || { health: {}, disability: {} };

  const update = (slice, patch) => {
    setHealthData({
      ...healthData,
      [active]: {
        ...(healthData[active] || { health: {}, disability: {} }),
        [slice]: { ...((healthData[active] || {})[slice] || {}), ...patch },
      },
    });
  };

  return (
    <>
      <SectionHead title="Health & Disability"
        sub="SECTION 3 OF 7 · PER MEMBER (Section D · age 2+)"/>
      <div style={{ padding: 20 }}>
        <MemberPicker members={members} value={active} onChange={setActive} minAge={2}/>
        {active != null && (
          <>
            <h4 className="t-h3" style={{ margin: "8px 0 12px" }}>Health (D1–D2)</h4>
            <div className="field-row-3">
              <Field label="Has chronic illness?" required>
                <YesNoSeg value={data.health.chronic_illness_flag}
                  onChange={(v) => update("health", { chronic_illness_flag: v })}/>
              </Field>
              <Field label="Chronic illness types"
                hint="Encrypted at rest (ADR-0019); list of codes">
                <input className="field-input" disabled={data.health.chronic_illness_flag !== "1"}
                  placeholder={data.health.chronic_illness_flag !== "1" ? "Not applicable" : "01, 02, …"}
                  value={(data.health.chronic_illness_types || []).join(", ")}
                  onChange={(e) => update("health", {
                    chronic_illness_types: e.target.value.split(",").map(s => s.trim()).filter(Boolean),
                  })}/>
              </Field>
            </div>

            <div className="divider mt-5"/>

            <h4 className="t-h3" style={{ margin: "8px 0 12px" }}>Washington Group Short Set (D3–D8)</h4>
            <div className="tint-update" style={{ padding: 10, borderRadius: 6, borderLeft: "3px solid var(--accent-update)", marginBottom: 14 }}>
              <div className="row gap-2"><Icon name="info" size={13} color="var(--accent-update)"/>
              <span className="t-bodysm">Codes: 01=No difficulty · 02=Some · 03=A lot · 04=Cannot do at all. <code>wg_disability_flag</code> auto-derives from "03" or "04" on any column.</span></div>
            </div>
            {[
              ["seeing", "Seeing (D3)"],
              ["hearing", "Hearing (D4)"],
              ["walking", "Walking / climbing (D5)"],
              ["memory", "Remembering / concentrating (D6)"],
              ["selfcare", "Self-care (D7)"],
              ["communication", "Communicating (D8)"],
            ].map(([field, label]) => (
              <Field key={field} label={label}>
                <div className="seg" style={{ maxWidth: 520 }}>
                  {[["01", "None"], ["02", "Some"], ["03", "A lot"], ["04", "Cannot"]].map(([code, lbl]) => (
                    <button key={code}
                      className={data.disability[field] === code ? "on" : ""}
                      onClick={() => update("disability", { [field]: code })}>
                      {lbl}
                    </button>
                  ))}
                </div>
              </Field>
            ))}
          </>
        )}
      </div>
    </>
  );
};

/* ───────────────────────────────────────────────────────────────
   Section 4 — Education (per member, age 3+)
   ─────────────────────────────────────────────────────────────── */

const EducationSection = ({ members, educationData, setEducationData }) => {
  const [active, setActive] = useStateSec(members.find(m => (m.age_years || 0) >= 3)?.line_number || null);
  const data = educationData[active] || {};

  const update = (patch) => {
    setEducationData({ ...educationData, [active]: { ...(educationData[active] || {}), ...patch } });
  };

  return (
    <>
      <SectionHead title="Education"
        sub="SECTION 4 OF 7 · PER MEMBER (Section E · age 3+)"/>
      <div style={{ padding: 20 }}>
        <MemberPicker members={members} value={active} onChange={setActive} minAge={3}/>
        {active != null && (
          <div className="col gap-4">
            <Field label="Literacy status" required>
              <ChoiceSelect listName="literacy_status" value={data.literacy_status}
                onChange={(v) => update({ literacy_status: v })}/>
            </Field>
            <div className="field-row-3">
              <Field label="Ever attended school?">
                <YesNoSeg value={data.ever_attended}
                  onChange={(v) => update({ ever_attended: v })}/>
              </Field>
              <Field label="Highest grade attained">
                <ChoiceSelect listName="highest_grade" value={data.highest_grade}
                  onChange={(v) => update({ highest_grade: v })}
                  disabled={data.ever_attended !== "1"}/>
              </Field>
              <Field label="Currently attending?">
                <YesNoSeg value={data.currently_attending}
                  onChange={(v) => update({ currently_attending: v })}/>
              </Field>
            </div>
            <div className="field-row-3">
              <Field label="Reason never attended"
                hint="Only when 'Ever attended' is No">
                <ChoiceSelect listName="never_attended_reason" value={data.never_attended_reason}
                  onChange={(v) => update({ never_attended_reason: v })}
                  disabled={data.ever_attended !== "2"}/>
              </Field>
              <Field label="Reason stopped school"
                hint="Only when stopped after attending">
                <ChoiceSelect listName="why_stopped_school" value={data.why_stopped}
                  onChange={(v) => update({ why_stopped: v })}
                  disabled={data.currently_attending !== "2" || data.ever_attended !== "1"}/>
              </Field>
              <Field label=""/>
            </div>
          </div>
        )}
      </div>
    </>
  );
};

/* ───────────────────────────────────────────────────────────────
   Section 5 — Employment (per member, age 7+)
   ─────────────────────────────────────────────────────────────── */

const EmploymentSection = ({ members, employmentData, setEmploymentData }) => {
  const [active, setActive] = useStateSec(members.find(m => (m.age_years || 0) >= 7)?.line_number || null);
  const data = employmentData[active] || {};

  const update = (patch) => {
    setEmploymentData({ ...employmentData, [active]: { ...(employmentData[active] || {}), ...patch } });
  };

  return (
    <>
      <SectionHead title="Employment"
        sub="SECTION 5 OF 7 · PER MEMBER (Section F · age 7+)"/>
      <div style={{ padding: 20 }}>
        <MemberPicker members={members} value={active} onChange={setActive} minAge={7}/>
        {active != null && (
          <div className="col gap-4">
            <div className="field-row-3">
              <Field label="Main activity (last 30 days)">
                <ChoiceSelect listName="employment_main_activity"
                  value={data.main_activity_last_30d}
                  onChange={(v) => update({ main_activity_last_30d: v })}/>
              </Field>
              <Field label="Work frequency">
                <ChoiceSelect listName="work_frequency" value={data.work_frequency}
                  onChange={(v) => update({ work_frequency: v })}/>
              </Field>
              <Field label="Sector">
                <ChoiceSelect listName="employment_sector" value={data.sector}
                  onChange={(v) => update({ sector: v })}/>
              </Field>
            </div>
            <div className="field-row-3">
              <Field label="Employment status">
                <ChoiceSelect listName="employment_status" value={data.employment_status}
                  onChange={(v) => update({ employment_status: v })}/>
              </Field>
              <Field label="Reason not working">
                <ChoiceSelect listName="not_working_reason" value={data.not_working_reason}
                  onChange={(v) => update({ not_working_reason: v })}/>
              </Field>
              <Field label="Govt programme beneficiary?">
                <YesNoSeg value={data.is_govt_programme_beneficiary}
                  onChange={(v) => update({ is_govt_programme_beneficiary: v })}/>
              </Field>
            </div>
            <div className="field-row-3">
              <Field label="Currently benefiting?">
                <YesNoSeg value={data.currently_benefiting}
                  onChange={(v) => update({ currently_benefiting: v })}
                />
              </Field>
              <Field label="Made savings?">
                <YesNoSeg value={data.made_savings}
                  onChange={(v) => update({ made_savings: v })}/>
              </Field>
              <Field label="Savings location">
                <ChoiceSelect listName="savings_location" value={data.savings_location}
                  onChange={(v) => update({ savings_location: v })}
                  disabled={data.made_savings !== "1"}/>
              </Field>
            </div>
          </div>
        )}
      </div>
    </>
  );
};

/* ───────────────────────────────────────────────────────────────
   Section 6 — Housing  (Dwelling + Utilities + Livelihood + Assets)
   ─────────────────────────────────────────────────────────────── */

const HousingSection = ({ housing, setHousing }) => {
  const d = housing.dwelling || {};
  const u = housing.utilities || {};
  const l = housing.livelihood || {};
  const assets = housing.assets || [];
  const crops = housing.crops || [];
  const livestock = housing.livestock || [];

  const setSlice = (slice) => (patch) => setHousing({ ...housing, [slice]: { ...(housing[slice] || {}), ...patch } });
  const setList = (key) => (next) => setHousing({ ...housing, [key]: next });

  return (
    <>
      <SectionHead title="Housing · Utilities · Assets · Livelihood"
        sub="SECTION 6 OF 7 · HOUSEHOLD (Section G + H)"/>
      <div style={{ padding: 20 }} className="col gap-4">

        {/* Dwelling */}
        <h4 className="t-h3" style={{ margin: "0 0 4px" }}>Dwelling (G1–G7)</h4>
        <div className="field-row-3">
          <Field label="Tenure">
            <ChoiceSelect listName="dwelling_tenure" value={d.tenure}
              onChange={(v) => setSlice("dwelling")({ tenure: v })}/>
          </Field>
          <Field label="Dwelling type">
            <ChoiceSelect listName="dwelling_type" value={d.dwelling_type}
              onChange={(v) => setSlice("dwelling")({ dwelling_type: v })}/>
          </Field>
          <Field label="Total rooms">
            <input className="field-input t-num" type="number" min="0"
              value={d.total_rooms ?? ""}
              onChange={(e) => setSlice("dwelling")({ total_rooms: e.target.value === "" ? null : Number(e.target.value) })}/>
          </Field>
        </div>
        <div className="field-row-3">
          <Field label="Sleeping rooms">
            <input className="field-input t-num" type="number" min="0"
              value={d.sleeping_rooms ?? ""}
              onChange={(e) => setSlice("dwelling")({ sleeping_rooms: e.target.value === "" ? null : Number(e.target.value) })}/>
          </Field>
          <Field label="Roof material">
            <ChoiceSelect listName="roof_material" value={d.roof_material}
              onChange={(v) => setSlice("dwelling")({ roof_material: v })}/>
          </Field>
          <Field label="Wall material">
            <ChoiceSelect listName="wall_material" value={d.wall_material}
              onChange={(v) => setSlice("dwelling")({ wall_material: v })}/>
          </Field>
        </div>
        <div className="field-row-3">
          <Field label="Floor material">
            <ChoiceSelect listName="floor_material" value={d.floor_material}
              onChange={(v) => setSlice("dwelling")({ floor_material: v })}/>
          </Field>
          <Field label=""/>
          <Field label=""/>
        </div>

        <div className="divider mt-5"/>

        {/* Utilities */}
        <h4 className="t-h3" style={{ margin: "0 0 4px" }}>Utilities (G8–G14)</h4>
        <div className="field-row-3">
          <Field label="Cooking fuel">
            <ChoiceSelect listName="cooking_fuel" value={u.cooking_fuel}
              onChange={(v) => setSlice("utilities")({ cooking_fuel: v })}/>
          </Field>
          <Field label="Lighting energy">
            <ChoiceSelect listName="lighting_energy" value={u.lighting_energy}
              onChange={(v) => setSlice("utilities")({ lighting_energy: v })}/>
          </Field>
          <Field label="Drinking water source">
            <ChoiceSelect listName="drinking_water_source" value={u.drinking_water_source}
              onChange={(v) => setSlice("utilities")({ drinking_water_source: v })}/>
          </Field>
        </div>
        <div className="field-row-3">
          <Field label="Toilet facility">
            <ChoiceSelect listName="toilet_facility" value={u.toilet_facility}
              onChange={(v) => setSlice("utilities")({ toilet_facility: v })}/>
          </Field>
          <Field label="Toilet shared?">
            <YesNoSeg value={u.toilet_shared ? "1" : u.toilet_shared === false ? "2" : ""}
              onChange={(v) => setSlice("utilities")({ toilet_shared: v === "1" })}/>
          </Field>
          <Field label="HHs sharing toilet"
            hint="Only when shared">
            <input className="field-input t-num" type="number" min="0"
              disabled={!u.toilet_shared}
              value={u.households_sharing_toilet ?? ""}
              onChange={(e) => setSlice("utilities")({ households_sharing_toilet: e.target.value === "" ? null : Number(e.target.value) })}/>
          </Field>
        </div>
        <div className="field-row-3">
          <Field label="Waste disposal">
            <ChoiceSelect listName="waste_disposal" value={u.waste_disposal}
              onChange={(v) => setSlice("utilities")({ waste_disposal: v })}/>
          </Field>
          <Field label=""/>
          <Field label=""/>
        </div>

        <div className="divider mt-5"/>

        {/* Livelihood */}
        <h4 className="t-h3" style={{ margin: "0 0 4px" }}>Livelihood & land (Section H)</h4>
        <div className="field-row-3">
          <Field label="Main livelihood">
            <ChoiceSelect listName="main_livelihood" value={l.main_livelihood}
              onChange={(v) => setSlice("livelihood")({ main_livelihood: v })}/>
          </Field>
          <Field label="Agricultural purpose">
            <ChoiceSelect listName="agricultural_purpose" value={l.agricultural_purpose}
              onChange={(v) => setSlice("livelihood")({ agricultural_purpose: v })}/>
          </Field>
          <Field label="Land ownership">
            <ChoiceSelect listName="land_ownership" value={l.land_ownership}
              onChange={(v) => setSlice("livelihood")({ land_ownership: v })}/>
          </Field>
        </div>
        <div className="field-row-3">
          <Field label="Land title">
            <ChoiceSelect listName="land_title" value={l.land_title}
              onChange={(v) => setSlice("livelihood")({ land_title: v })}/>
          </Field>
          <Field label="Land hectares" hint="Decimal hectares">
            <input className="field-input t-num" type="number" min="0" step="0.001"
              value={l.land_hectares ?? ""}
              onChange={(e) => setSlice("livelihood")({ land_hectares: e.target.value === "" ? null : Number(e.target.value) })}/>
          </Field>
          <Field label=""/>
        </div>

        <div className="divider mt-5"/>

        {/* Assets repeat group */}
        <h4 className="t-h3" style={{ margin: "0 0 4px" }}>Assets owned (G15)</h4>
        <RepeatGroup
          rows={assets}
          onChange={setList("assets")}
          columns={[
            { key: "asset_type", label: "Asset", render: (v, onChange) => (
              <ChoiceSelect listName="asset_type" value={v}
                onChange={onChange}/>
            )},
            { key: "count", label: "Count", render: (v, onChange) => (
              <input className="field-input t-num" type="number" min="0"
                value={v ?? ""}
                onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}/>
            )},
          ]}
          emptyRow={() => ({ asset_type: "", count: 0 })}
        />

        <div className="divider mt-5"/>

        {/* Crops repeat group */}
        <h4 className="t-h3" style={{ margin: "0 0 4px" }}>Crops grown (H1–H4)</h4>
        <RepeatGroup
          rows={crops}
          onChange={setList("crops")}
          columns={[
            { key: "crop_name", label: "Crop", render: (v, onChange) => (
              <ChoiceSelect listName="crop_name" value={v}
                onChange={onChange}/>
            )},
            { key: "rank_order", label: "Rank", render: (v, onChange) => (
              <input className="field-input t-num" type="number" min="1" max="9"
                value={v ?? ""}
                onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}/>
            )},
          ]}
          emptyRow={() => ({ crop_name: "", rank_order: 1 })}
        />

        <div className="divider mt-5"/>

        {/* Livestock repeat group */}
        <h4 className="t-h3" style={{ margin: "0 0 4px" }}>Livestock owned (H5–H8)</h4>
        <RepeatGroup
          rows={livestock}
          onChange={setList("livestock")}
          columns={[
            { key: "livestock_type", label: "Type", render: (v, onChange) => (
              <ChoiceSelect listName="livestock_type" value={v}
                onChange={onChange}/>
            )},
            { key: "count", label: "Count", render: (v, onChange) => (
              <input className="field-input t-num" type="number" min="0"
                value={v ?? ""}
                onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}/>
            )},
          ]}
          emptyRow={() => ({ livestock_type: "", count: 0 })}
        />
      </div>
    </>
  );
};

/* ───────────────────────────────────────────────────────────────
   Section 7 — Food & Shocks  (Section I + K + L)
   ─────────────────────────────────────────────────────────────── */

const FOOD_GROUPS = [
  ["staples",    "Staples (cereals, roots, tubers)"],
  ["pulses",     "Pulses (beans, lentils, peas)"],
  ["dairy",      "Dairy"],
  ["meat",       "Meat / fish / eggs"],
  ["vegetables", "Vegetables"],
  ["fruits",     "Fruits"],
  ["oils",       "Oils / fats"],
  ["sugar",      "Sugar / sweets"],
  ["condiments", "Condiments / spices"],
];

const FoodShocksSection = ({ foodShocks, setFoodShocks }) => {
  const fs = foodShocks.food_security || {};
  const fc = foodShocks.food_consumption || {};
  const shocks = foodShocks.shocks || [];
  const coping = foodShocks.coping || [];

  const setSlice = (slice) => (patch) => setFoodShocks({ ...foodShocks, [slice]: { ...(foodShocks[slice] || {}), ...patch } });
  const setList = (key) => (next) => setFoodShocks({ ...foodShocks, [key]: next });

  // FIES raw score = count of "1" (yes) across the 8 questions.
  const fiesScore = useMemoSec(() => {
    return [fs.worried_food, fs.unhealthy_food, fs.limited_variety, fs.skipped_meal,
            fs.ate_less, fs.ran_out_food, fs.hungry_no_eat, fs.whole_day_no_eat]
      .filter(v => v === "1").length;
  }, [fs]);

  return (
    <>
      <SectionHead title="Food security · Shocks · Coping"
        sub="SECTION 7 OF 7 · HOUSEHOLD (Section I + K + L)"/>
      <div style={{ padding: 20 }} className="col gap-4">

        {/* FIES — 8 binary questions */}
        <div>
          <h4 className="t-h3" style={{ margin: "0 0 4px" }}>Food Insecurity Experience Scale (Section I, FIES)</h4>
          <div className="t-cap" style={{ marginBottom: 14 }}>
            Reference period: <strong>last 12 months</strong>. Each question is binary (Yes / No).
            <strong> Raw score: {fiesScore} / 8</strong>
            {fiesScore >= 6 && <Chip size="sm" tone="danger" style={{ marginLeft: 8 }}>Severe</Chip>}
            {fiesScore >= 3 && fiesScore < 6 && <Chip size="sm" tone="quality" style={{ marginLeft: 8 }}>Moderate</Chip>}
          </div>
          {[
            ["worried_food",     "I1 — Worried about not having enough food"],
            ["unhealthy_food",   "I2 — Unable to eat healthy / nutritious food"],
            ["limited_variety",  "I3 — Ate only a few kinds of food"],
            ["skipped_meal",     "I4 — Skipped a meal"],
            ["ate_less",         "I5 — Ate less than thought you should"],
            ["ran_out_food",     "I6 — Household ran out of food"],
            ["hungry_no_eat",    "I7 — Hungry but did not eat"],
            ["whole_day_no_eat", "I8 — Went a whole day without eating"],
          ].map(([field, label]) => (
            <div key={field} className="field-row-3" style={{ marginBottom: 8 }}>
              <Field label={label}>
                <YesNoSeg value={fs[field]}
                  onChange={(v) => setSlice("food_security")({ [field]: v })}/>
              </Field>
              <Field label=""/>
              <Field label=""/>
            </div>
          ))}
        </div>

        <div className="divider mt-5"/>

        {/* FCS — 9 food groups × (days last 7 + source) */}
        <h4 className="t-h3" style={{ margin: "0 0 4px" }}>Food Consumption Score (Section I9–I17, FCS)</h4>
        <div className="t-cap" style={{ marginBottom: 8 }}>
          For each food group, record <strong>number of days consumed in the last 7</strong> and the dominant source.
        </div>
        {FOOD_GROUPS.map(([key, label]) => (
          <div key={key} className="field-row-3">
            <Field label={label}>
              <input className="field-input t-num" type="number" min="0" max="7"
                value={fc[`${key}_days`] ?? ""}
                onChange={(e) => setSlice("food_consumption")({
                  [`${key}_days`]: e.target.value === "" ? null : Number(e.target.value),
                })}/>
            </Field>
            <Field label="Source">
              <ChoiceSelect listName="food_source"
                value={fc[`${key}_source`]}
                onChange={(v) => setSlice("food_consumption")({ [`${key}_source`]: v })}/>
            </Field>
            <Field label=""/>
          </div>
        ))}

        <div className="divider mt-5"/>

        {/* Shocks repeat group */}
        <h4 className="t-h3" style={{ margin: "0 0 4px" }}>Shock events (Section K)</h4>
        <RepeatGroup
          rows={shocks}
          onChange={setList("shocks")}
          columns={[
            { key: "shock_type", label: "Type", render: (v, onChange) => (
              <ChoiceSelect listName="shock_type" value={v} onChange={onChange}/>
            )},
            { key: "severity", label: "Severity", render: (v, onChange) => (
              <ChoiceSelect listName="severity_level" value={v} onChange={onChange}/>
            )},
            { key: "event_date", label: "Date", render: (v, onChange) => (
              <input className="field-input t-mono" type="date"
                value={v || ""} onChange={(e) => onChange(e.target.value)}/>
            )},
          ]}
          emptyRow={() => ({ shock_type: "", severity: "", event_date: "" })}
        />

        <div className="divider mt-5"/>

        {/* Coping repeat group */}
        <h4 className="t-h3" style={{ margin: "0 0 4px" }}>Coping strategies (Section L)</h4>
        <RepeatGroup
          rows={coping}
          onChange={setList("coping")}
          columns={[
            { key: "strategy_type", label: "Strategy", render: (v, onChange) => (
              <ChoiceSelect listName="coping_strategy_type" value={v} onChange={onChange}/>
            )},
            { key: "frequency", label: "Frequency", render: (v, onChange) => (
              <ChoiceSelect listName="coping_frequency" value={v} onChange={onChange}/>
            )},
            { key: "category", label: "Category (food/livelihood)", render: (v, onChange) => (
              <div className="seg" style={{ maxWidth: 220 }}>
                <button className={v === "food" ? "on" : ""} onClick={() => onChange("food")}>Food</button>
                <button className={v === "livelihood" ? "on" : ""} onClick={() => onChange("livelihood")}>Livelihood</button>
              </div>
            )},
          ]}
          emptyRow={() => ({ strategy_type: "", frequency: "", category: "food" })}
        />
      </div>
    </>
  );
};

/* ───────────────────────────────────────────────────────────────
   RepeatGroup — generic 1:N child row editor
   ─────────────────────────────────────────────────────────────── */

const RepeatGroup = ({ rows, onChange, columns, emptyRow }) => {
  const add = () => onChange([...(rows || []), emptyRow()]);
  const remove = (i) => onChange((rows || []).filter((_, j) => j !== i));
  const update = (i, key, val) => onChange((rows || []).map((r, j) => j === i ? { ...r, [key]: val } : r));

  return (
    <div className="card" style={{ padding: 0, background: "var(--neutral-50)" }}>
      <table className="tbl" style={{ boxShadow: "none", marginBottom: 0 }}>
        <thead>
          <tr>
            {columns.map(c => <th key={c.key}>{c.label}</th>)}
            <th style={{ width: 60 }}></th>
          </tr>
        </thead>
        <tbody>
          {(rows || []).map((row, i) => (
            <tr key={i}>
              {columns.map(c => (
                <td key={c.key}>{c.render(row[c.key], (v) => update(i, c.key, v))}</td>
              ))}
              <td style={{ textAlign: "right" }}>
                <button className="icon-btn" title="Remove" onClick={() => remove(i)}>
                  <Icon name="trash" size={12}/>
                </button>
              </td>
            </tr>
          ))}
          {(!rows || rows.length === 0) && (
            <tr><td colSpan={columns.length + 1} className="t-cap" style={{ padding: "10px 14px", color: "var(--neutral-500)" }}>
              No rows yet.
            </td></tr>
          )}
        </tbody>
      </table>
      <div style={{ padding: "8px 12px", borderTop: "1px solid var(--neutral-200)" }}>
        <button className="btn btn-sm" onClick={add}>
          <Icon name="plus" size={12}/> Add row
        </button>
      </div>
    </div>
  );
};

Object.assign(window, {
  RosterSection,
  HealthDisabilitySection,
  EducationSection,
  EmploymentSection,
  HousingSection,
  FoodShocksSection,
  ChoiceSelect,
  YesNoSeg,
  RepeatGroup,
});
