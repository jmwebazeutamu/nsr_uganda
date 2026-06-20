/* global React, Icon, Chip, PageHeader */
// NSR MIS — Admin · Record detail & edit views
// =========================================================
// Sibling screens to the list views — opened from the admin
// console when a row is clicked. Edits create a new draft / new
// active version where appropriate (never destructive).
//
// Exposes:
//   AdminGeoUnitDetailScreen     — view + edit a GeographicUnit
//   AdminUpdRoutingRuleEditScreen — edit a UpdRoutingRule (writes new active row)
//   AdminUserDetailScreen        — view + edit a user (roles + OperatorScope)
//   AdminDdupPairDetailScreen    — side-by-side merge resolution UI
//   AdminChoiceListOptionEditScreen — edit a single ChoiceOption inside a draft

const { useState: useStateAD } = React;

/* ===========================================================
   GEOGRAPHIC UNIT — view + edit
   =========================================================== */
const AdminGeoUnitDetailScreen = ({ unit, onBack, onSave }) => {
  const u = unit || {
    code: "DST-MOROTO", name: "Moroto", level: "district",
    parent: { code: "SR-KARAMOJA", name: "Karamoja", level: "sub_region" },
    status: "active", effectiveFrom: "01 Jan 2020", effectiveTo: null,
    pCodeUbos: "UG7501", pCodeOcha: "UG-401",
    centroidLat: 2.5333, centroidLng: 34.6667,
    households: 42101,
    children: [
      { code: "SC-TAPAC", name: "Tapac", status: "active" },
      { code: "SC-RUPA", name: "Rupa", status: "active" },
      { code: "SC-KATIKEKILE", name: "Katikekile", status: "active" },
      { code: "SC-MOROTO-NORTH", name: "Moroto North", status: "superseded" },
      { code: "SC-TEPETH", name: "Tepeth", status: "active" },
    ],
    notes: "Capital town of Karamoja sub-region. Boundary review pending for 2026 split with Napak.",
  };

  const [edit, setEdit] = useStateAD(false);
  const [draft, setDraft] = useStateAD({ name: u.name, notes: u.notes, status: u.status, effectiveTo: u.effectiveTo });

  return (
    <div className="page">
      <PageHeader
        back={{ label: "Geography", onClick: onBack }}
        eyebrow={<>ADMIN · REF · GEOGRAPHY · <span className="t-mono">{u.code}</span></>}
        title={<>{u.name} <span className="t-bodysm" style={{ fontWeight: 400, color: 'var(--accent-data)', marginLeft: 8 }}>· {u.level}</span></>}
        sub={<>Inside <strong>{u.parent.name}</strong> ({u.parent.level}) · {u.households.toLocaleString()} households scored</>}
        right={<>
          {!edit
            ? <button className="btn btn-primary" onClick={() => setEdit(true)}><Icon name="edit" size={14}/> Edit unit</button>
            : <>
                <button className="btn" onClick={() => setEdit(false)}>Cancel</button>
                <button className="btn btn-primary" onClick={() => { onSave?.(draft); setEdit(false); }}>
                  <Icon name="check" size={14}/> Save changes
                </button>
              </>}
        </>}
      />

      <div className="grid" style={{ gridTemplateColumns: '1.4fr 1fr', gap: 16 }}>
        {/* Identity */}
        <div className="card" style={{ padding: 0 }}>
          <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--neutral-200)' }}>
            <strong>Identity</strong>
          </div>
          <div style={{ padding: 16, display: 'grid', gridTemplateColumns: '160px 1fr', rowGap: 10, fontSize: 13 }}>
            <div className="muted">Code</div>
            <div className="t-mono">{u.code} <span className="t-cap">· stable across versions</span></div>
            <div className="muted">Name</div>
            <div>
              {edit
                ? <input className="field-input" value={draft.name} onChange={e => setDraft({ ...draft, name: e.target.value })} style={{ height: 30, padding: '4px 10px', width: 280 }}/>
                : u.name}
            </div>
            <div className="muted">Level</div><div><Chip size="sm" tone="data">{u.level}</Chip></div>
            <div className="muted">Parent</div>
            <div>
              <span className="t-mono">{u.parent.code}</span> · {u.parent.name}{' '}
              <Chip size="sm">{u.parent.level}</Chip>
            </div>
            <div className="muted">UBOS P-code</div><div className="t-mono">{u.pCodeUbos}</div>
            <div className="muted">OCHA P-code</div><div className="t-mono">{u.pCodeOcha}</div>
            <div className="muted">Centroid (lat, lng)</div>
            <div className="t-mono">{u.centroidLat.toFixed(4)}, {u.centroidLng.toFixed(4)}</div>
            <div className="muted">Households scored</div><div className="t-num">{u.households.toLocaleString()}</div>
          </div>
        </div>

        {/* Lifecycle */}
        <div className="card" style={{ padding: 0, borderTop: '3px solid var(--accent-eligibility)' }}>
          <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--neutral-200)' }}>
            <strong>Lifecycle</strong>
          </div>
          <div style={{ padding: 16, display: 'grid', gridTemplateColumns: '140px 1fr', rowGap: 10, fontSize: 13 }}>
            <div className="muted">Status</div>
            <div>
              {edit
                ? <select className="field-select" value={draft.status} onChange={e => setDraft({ ...draft, status: e.target.value })} style={{ height: 30, width: 180 }}>
                    <option value="active">active</option>
                    <option value="superseded">superseded</option>
                    <option value="retired">retired</option>
                  </select>
                : <Chip size="sm" tone={u.status === 'active' ? 'data' : u.status === 'superseded' ? 'quality' : 'neutral'}>{u.status}</Chip>}
            </div>
            <div className="muted">Effective from</div><div>{u.effectiveFrom}</div>
            <div className="muted">Effective to</div>
            <div>
              {edit
                ? <input type="date" className="field-input" value={draft.effectiveTo || ''} onChange={e => setDraft({ ...draft, effectiveTo: e.target.value })} style={{ height: 30, padding: '4px 10px', width: 180 }}/>
                : (u.effectiveTo || <span className="muted">—</span>)}
            </div>
          </div>
          <div className="tint-update" style={{ borderTop: '1px solid var(--neutral-200)', borderLeft: '3px solid var(--accent-update)', padding: 12 }}>
            <div className="row gap-2" style={{ marginBottom: 4 }}>
              <Icon name="info" size={12} color="var(--accent-update)"/>
              <strong className="t-bodysm">Versioned change</strong>
            </div>
            <div className="t-bodysm muted">
              Renaming or restructuring writes a new row with <code>effective_from = today</code> and supersedes the
              current row (status → <span className="t-mono">superseded</span>, <code>effective_to = today − 1</code>).
              Historical intake remains interpretable.
            </div>
          </div>
        </div>

        {/* Children */}
        <div className="card" style={{ padding: 0, gridColumn: '1 / -1' }}>
          <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--neutral-200)', display:'flex', alignItems:'center', gap:10 }}>
            <strong>Children</strong>
            <span className="t-cap">{u.children.length} sub-counties · drill in to manage</span>
            <div style={{ flex: 1 }}/>
            <button className="btn btn-sm"><Icon name="plus" size={12}/> Add sub-county</button>
          </div>
          <table className="tbl" style={{ boxShadow: 'none' }}>
            <thead><tr><th>Code</th><th>Name</th><th>Status</th><th className="col-actions"></th></tr></thead>
            <tbody>
              {u.children.map(c => (
                <tr key={c.code} style={{ cursor: 'pointer', opacity: c.status !== 'active' ? 0.7 : 1 }}>
                  <td className="t-mono">{c.code}</td>
                  <td>{c.name}</td>
                  <td><Chip size="sm" tone={c.status === 'active' ? 'data' : c.status === 'superseded' ? 'quality' : 'neutral'}>{c.status}</Chip></td>
                  <td className="col-actions"><Icon name="chevronRight" size={16} color="var(--neutral-500)"/></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Notes */}
        <div className="card" style={{ padding: 0, gridColumn: '1 / -1' }}>
          <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--neutral-200)' }}>
            <strong>Notes</strong>
          </div>
          <div style={{ padding: 16 }}>
            {edit
              ? <textarea className="field-input" value={draft.notes} onChange={e => setDraft({ ...draft, notes: e.target.value })} style={{ width: '100%', minHeight: 80, padding: 10, fontFamily: 'inherit' }}/>
              : <span className="t-bodysm">{u.notes}</span>}
          </div>
        </div>
      </div>
    </div>
  );
};

/* ===========================================================
   UPD ROUTING — edit (versioned write)
   =========================================================== */
const AdminUpdRoutingRuleEditScreen = ({ rule, onBack, onSave }) => {
  const r = rule || {
    changeType: "addition", pmtRelevant: false,
    requiredRole: "cdo", slaHours: 48,
    isActive: true, updatedAt: "12 Mar 2026", note: "Backlog rebalance — was 72h",
  };

  const [draft, setDraft] = useStateAD({
    requiredRole: r.requiredRole, slaHours: r.slaHours, note: r.note,
  });

  const ROLES = [
    { id: "parish_coordinator",    label: "Parish Coordinator" },
    { id: "cdo",                   label: "Community Dev't Officer (CDO)" },
    { id: "nsr_unit_coordinator",  label: "NSR Unit Coordinator" },
    { id: "dpo",                   label: "Data Protection Officer (DPO)" },
    { id: "auto_committed",        label: "Auto-committed (no human review)" },
  ];

  return (
    <div className="page">
      <PageHeader
        back={{ label: "UPD routing", onClick: onBack }}
        eyebrow={<>ADMIN · WORKFLOW · UPD ROUTING · edit</>}
        title={<>{r.changeType} <span className="t-bodysm" style={{ fontWeight: 400, color: 'var(--accent-data)', marginLeft: 8 }}>· pmt_relevant = {r.pmtRelevant ? 'true' : 'false'}</span></>}
        sub={<>Last updated <strong>{r.updatedAt}</strong>. Edits write a new active row and supersede this one.</>}
        right={<>
          <button className="btn btn-primary" onClick={() => onSave?.(draft)}><Icon name="check" size={14}/> Save (creates new active rule)</button>
        </>}
      />

      <div className="grid" style={{ gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <div className="card" style={{ padding: 0 }}>
          <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--neutral-200)' }}>
            <strong>Tuple (immutable)</strong>
            <div className="t-cap">This is the cell in the matrix; not editable.</div>
          </div>
          <div style={{ padding: 16, display: 'grid', gridTemplateColumns: '160px 1fr', rowGap: 10, fontSize: 13 }}>
            <div className="muted">change_type</div><div className="t-mono">{r.changeType}</div>
            <div className="muted">pmt_relevant</div><div className="t-mono">{r.pmtRelevant ? 'true' : 'false'}</div>
          </div>
        </div>

        <div className="card" style={{ padding: 0, borderTop: '3px solid var(--accent-update)' }}>
          <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--neutral-200)' }}>
            <strong>New routing</strong>
            <div className="t-cap">Required role + SLA. SLA is hours from CR creation to expected decision.</div>
          </div>
          <div style={{ padding: 16, display: 'grid', gridTemplateColumns: '160px 1fr', rowGap: 14, fontSize: 13 }}>
            <div className="muted">required_role</div>
            <div>
              <select className="field-select" value={draft.requiredRole} onChange={e => setDraft({ ...draft, requiredRole: e.target.value })} style={{ height: 34, width: '100%', maxWidth: 320 }}>
                {ROLES.map(o => <option key={o.id} value={o.id}>{o.label}</option>)}
              </select>
            </div>
            <div className="muted">sla_hours</div>
            <div>
              <input type="number" min={0} max={1000} value={draft.slaHours} onChange={e => setDraft({ ...draft, slaHours: parseInt(e.target.value) || 0 })} className="field-input" style={{ height: 34, width: 120, padding: '4px 10px', fontFamily: 'var(--font-mono)' }}/>
              <span className="t-cap" style={{ marginLeft: 8 }}>{draft.requiredRole === "auto_committed" ? '— ignored for auto-commit (1% sample audited)' : 'hours from CR creation'}</span>
            </div>
            <div className="muted">change note</div>
            <div>
              <textarea className="field-input" value={draft.note} onChange={e => setDraft({ ...draft, note: e.target.value })} placeholder="e.g. SLA tightened after Q1 ops review" style={{ width: '100%', minHeight: 60, padding: 10, fontFamily: 'inherit' }}/>
            </div>
          </div>
        </div>

        <div className="tint-update" style={{ gridColumn: '1 / -1', padding: 14, borderRadius: 6, borderLeft: '3px solid var(--accent-update)' }}>
          <div className="row gap-2" style={{ marginBottom: 4 }}>
            <Icon name="info" size={13} color="var(--accent-update)"/>
            <strong className="t-bodysm">What "Save" does</strong>
          </div>
          <div className="t-bodysm muted">
            Saving inserts a new row with <code>is_active=true</code>, flips this row to{' '}
            <code>is_active=false</code>, and writes an <span className="t-mono">apps.security.AuditEvent</span> of
            action <span className="t-mono">upd_routing.replaced</span>. The constraint{' '}
            <span className="t-mono">upd_routing_unique_active_per_tuple</span> guarantees at most one active rule per
            (change_type × pmt_relevant) at all times.
          </div>
        </div>
      </div>
    </div>
  );
};

/* ===========================================================
   USER DETAIL — view + edit (roles + scopes)
   =========================================================== */
const AdminUserDetailScreen = ({ user, onBack, onSave }) => {
  const u = user || {
    id: "u-adong-f", name: "Adong F.", username: "adong.f",
    email: "adong.f@mglsd.go.ug", phone: "+256 772 412 089",
    status: "active", lastLogin: "22 May · 11:32",
    mfa: true, mfaMethod: "TOTP",
    groups: ["cdo"],
    scopes: [{ level: "sub_county", code: "SC-TAPAC" }, { level: "sub_county", code: "SC-RUPA" }],
    onboardedAt: "12 Mar 2024",
    lastPasswordReset: "08 Mar 2026",
    sessionCount24h: 3,
    recentActions: [
      { time: "22 May · 11:33", action: "view", entity: "household", id: "01KRPPW6WR…", ip: "41.78.12.4" },
      { time: "21 May · 16:48", action: "update", entity: "change_request", id: "UPD-2026-05-21-00188", ip: "41.78.12.4" },
      { time: "21 May · 11:08", action: "merge", entity: "member", id: "M-01KRPPW6WR-002", ip: "41.78.12.4" },
    ],
  };
  const [edit, setEdit] = useStateAD(false);
  const [draft, setDraft] = useStateAD({ groups: u.groups, scopes: u.scopes, status: u.status });

  const ROLES = [
    { id: "parish_coordinator", label: "Parish Coordinator" },
    { id: "cdo", label: "Community Dev't Officer" },
    { id: "nsr_unit_coordinator", label: "NSR Unit Coordinator" },
    { id: "dpo", label: "Data Protection Officer" },
    { id: "mglsd_statistics", label: "MGLSD Statistics" },
    { id: "nsr_admin", label: "NSR Admin" },
    { id: "nsr_dba", label: "NSR DBA" },
    { id: "nsr_security", label: "NSR Security" },
    { id: "partner_steward", label: "Partner Data Steward" },
  ];
  const toggleRole = (id) => {
    setDraft({ ...draft, groups: draft.groups.includes(id) ? draft.groups.filter(g => g !== id) : [...draft.groups, id] });
  };
  const addScope = () => setDraft({ ...draft, scopes: [...draft.scopes, { level: "parish", code: "" }] });
  const removeScope = (i) => setDraft({ ...draft, scopes: draft.scopes.filter((_, j) => j !== i) });
  const updateScope = (i, patch) => setDraft({ ...draft, scopes: draft.scopes.map((s, j) => j === i ? { ...s, ...patch } : s) });

  return (
    <div className="page">
      <PageHeader
        back={{ label: "Roles & scopes", onClick: onBack }}
        eyebrow={<>ADMIN · SECURITY · USERS · <span className="t-mono">{u.id}</span></>}
        title={<>{u.name} <span className="t-bodysm" style={{ fontWeight: 400, color: 'var(--accent-data)', marginLeft: 8 }}>· {u.username}</span></>}
        sub={<>{u.email} · onboarded {u.onboardedAt}</>}
        right={<>
          {!edit
            ? <>
                <button className="btn"><Icon name="refresh" size={14}/> Reset password</button>
                <button className="btn btn-primary" onClick={() => setEdit(true)}><Icon name="edit" size={14}/> Edit user</button>
              </>
            : <>
                <button className="btn" onClick={() => setEdit(false)}>Cancel</button>
                <button className="btn btn-primary" onClick={() => { onSave?.(draft); setEdit(false); }}>
                  <Icon name="check" size={14}/> Save
                </button>
              </>}
        </>}
      />

      {/* Summary */}
      <div className="card" style={{ padding: 0 }}>
        <div style={{ padding: '18px 20px', display: 'grid', gridTemplateColumns: '64px 1fr 1fr 1fr', gap: 16, alignItems: 'flex-start' }}>
          <div style={{
            width: 64, height: 64, borderRadius: '50%',
            background: 'var(--primary-100)', color: 'var(--primary-900)',
            display: 'grid', placeItems: 'center', fontSize: 20, fontWeight: 600,
          }}>{u.name.split(' ').map(w => w[0]).slice(0, 2).join('')}</div>
          <div>
            <div className="t-cap">Status</div>
            <div className="mt-1">{edit
              ? <select className="field-select" value={draft.status} onChange={e => setDraft({ ...draft, status: e.target.value })} style={{ height: 28, width: 140 }}>
                  <option value="active">active</option>
                  <option value="suspended">suspended</option>
                </select>
              : <Chip tone={u.status === 'active' ? 'data' : 'quality'}>{u.status}</Chip>}</div>
            <div className="t-cap mt-2">Last login: {u.lastLogin}</div>
          </div>
          <div>
            <div className="t-cap">MFA</div>
            <div className="mt-1">{u.mfa
              ? <Chip tone="data"><Icon name="check" size={10}/> {u.mfaMethod}</Chip>
              : <Chip tone="danger">off</Chip>}</div>
            <div className="t-cap mt-2">Last password reset: {u.lastPasswordReset}</div>
          </div>
          <div>
            <div className="t-cap">Sessions (24h)</div>
            <div className="t-num" style={{ fontSize: 22, fontWeight: 600, marginTop: 2 }}>{u.sessionCount24h}</div>
            <button className="btn btn-sm mt-2" style={{ color: 'var(--accent-danger)' }}><Icon name="x" size={11}/> Force sign-out</button>
          </div>
        </div>
      </div>

      <div className="grid mt-4" style={{ gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {/* Roles */}
        <div className="card" style={{ padding: 0 }}>
          <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--neutral-200)' }}>
            <strong>Roles</strong>
            <div className="t-cap">Each role grants access to a set of screens.</div>
          </div>
          <div style={{ padding: 14, display: 'flex', flexDirection: 'column', gap: 8 }}>
            {ROLES.map(role => {
              const checked = edit ? draft.groups.includes(role.id) : u.groups.includes(role.id);
              return (
                <label key={role.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px', borderRadius: 4, background: checked ? 'var(--accent-system-bg)' : 'transparent', border: '1px solid var(--neutral-200)', cursor: edit ? 'pointer' : 'default' }}>
                  <input type="checkbox" checked={checked} disabled={!edit} onChange={() => toggleRole(role.id)}/>
                  <div style={{ flex: 1 }}>
                    <div className="t-bodysm" style={{ fontWeight: 500 }}>{role.label}</div>
                    <div className="t-cap t-mono" style={{ fontSize: 10 }}>{role.id}</div>
                  </div>
                  {checked && <Chip size="sm" tone="data">assigned</Chip>}
                </label>
              );
            })}
          </div>
        </div>

        {/* Scopes */}
        <div className="card" style={{ padding: 0 }}>
          <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--neutral-200)', display: 'flex', alignItems: 'center' }}>
            <div>
              <strong>Geographic scopes</strong>
              <div className="t-cap">Each row restricts visibility to a level + code. NATIONAL is wildcard.</div>
            </div>
            <div style={{ flex: 1 }}/>
            {edit && <button className="btn btn-sm" onClick={addScope}><Icon name="plus" size={12}/> Add scope</button>}
          </div>
          <div style={{ padding: 14, display: 'flex', flexDirection: 'column', gap: 8 }}>
            {(edit ? draft.scopes : u.scopes).map((s, i) => (
              <div key={i} style={{ display: 'grid', gridTemplateColumns: '140px 1fr auto', gap: 8, alignItems: 'center', padding: '8px 10px', borderRadius: 4, background: 'var(--neutral-50)' }}>
                {edit
                  ? <>
                      <select className="field-select" value={s.level} onChange={e => updateScope(i, { level: e.target.value })} style={{ height: 30 }}>
                        <option value="national">national</option>
                        <option value="region">region</option>
                        <option value="sub_region">sub_region</option>
                        <option value="district">district</option>
                        <option value="sub_county">sub_county</option>
                        <option value="parish">parish</option>
                        <option value="village">village</option>
                        <option value="partner">partner</option>
                      </select>
                      <input className="field-input" value={s.code} onChange={e => updateScope(i, { code: e.target.value })} placeholder={s.level === "national" ? "(blank for wildcard)" : "code"} style={{ height: 30, padding: '4px 10px', fontFamily: 'var(--font-mono)' }}/>
                      <button className="icon-btn" onClick={() => removeScope(i)} title="Remove" style={{ color: 'var(--accent-danger)' }}><Icon name="x" size={12}/></button>
                    </>
                  : <>
                      <Chip size="sm" tone={s.level === "national" ? "danger" : "data"}>{s.level}</Chip>
                      <span className="t-mono t-bodysm">{s.code || '(wildcard)'}</span>
                      <span></span>
                    </>}
              </div>
            ))}
            {(edit ? draft.scopes : u.scopes).length === 0 && (
              <div className="muted t-cap" style={{ padding: 16, textAlign: 'center' }}>No scopes — user can see nothing.</div>
            )}
          </div>
        </div>
      </div>

      {/* Recent actions */}
      <div className="card mt-4" style={{ padding: 0 }}>
        <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--neutral-200)' }}>
          <strong>Recent actions</strong>
          <div className="t-cap">Most recent 3 entries from the audit chain.</div>
        </div>
        <table className="tbl" style={{ boxShadow: 'none' }}>
          <thead><tr><th>Time</th><th>Action</th><th>Entity</th><th>IP</th></tr></thead>
          <tbody>
            {u.recentActions.map((a, i) => (
              <tr key={i}>
                <td className="t-cap" style={{ whiteSpace: 'nowrap' }}>{a.time}</td>
                <td><Chip size="sm">{a.action}</Chip></td>
                <td>
                  <div className="t-mono t-cap">{a.entity}</div>
                  <div className="t-mono t-cap" style={{ color: 'var(--accent-system)' }}>{a.id}</div>
                </td>
                <td className="t-mono t-cap">{a.ip}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

/* ===========================================================
   DDUP MATCH PAIR — side-by-side merge resolution
   =========================================================== */
const AdminDdupPairDetailScreen = ({ pair, onBack, onMerge, onReject, onHold }) => {
  const p = pair || {
    id: "01HXR9P2K7N6FB7K6FZRWS01",
    type: "member",
    tier: 3, score: 0.94, status: "pending", ageHours: 2,
    reason: "name + village + DoB",
    fields: [
      { field: "full_name",     a: "Lokol Naume",   b: "Lokol Naome",   similarity: 0.92, match: true },
      { field: "date_of_birth", a: "1995-03-14",    b: "1995-03-14",    similarity: 1.00, match: true },
      { field: "sex",           a: "F",             b: "F",             similarity: 1.00, match: true },
      { field: "village_code",  a: "VLG-LOPUWAPUWA-A", b: "VLG-LOPUWAPUWA-A", similarity: 1.00, match: true },
      { field: "nin_value",     a: "—",             b: "CM95031411XYZW", similarity: 0.00, match: false },
      { field: "phone",         a: "+256 772 412…", b: "—",             similarity: 0.00, match: false },
      { field: "household_id",  a: "01HXY7K3B2…",   b: "01HXP02CN5…",   similarity: 0.00, match: false },
    ],
    contextA: { id: "M-01HXY7K3B2-001", household: "Lokol household · Moroto", confirmed: "Confirmed", line: 1, role: "Head" },
    contextB: { id: "M-01HXP02CN5-099", household: "Onyango household · Arua", confirmed: "Provisional", line: 4, role: "Daughter" },
  };

  const [survivor, setSurvivor] = useStateAD("A");
  const [reason, setReason] = useStateAD("");

  return (
    <div className="page">
      <PageHeader
        back={{ label: "DDUP model", onClick: onBack }}
        eyebrow={<>ADMIN · WORKFLOW · DDUP · MATCH PAIR · <span className="t-mono">{p.id.slice(0, 16)}…</span></>}
        title={<>{p.type === 'household' ? 'Household' : 'Member'} match · Tier {p.tier} · score {p.score.toFixed(2)}</>}
        sub={<>Pending {p.ageHours}h · reason: <strong>{p.reason}</strong></>}
      />

      {/* Survivor picker */}
      <div className="card" style={{ padding: 0 }}>
        <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--neutral-200)' }}>
          <strong>Choose surviving record</strong>
          <div className="t-cap">The other record's data merges into the survivor. Both IDs remain in the audit chain.</div>
        </div>
        <div style={{ padding: 18, display: 'grid', gridTemplateColumns: '1fr 60px 1fr', gap: 12, alignItems: 'stretch' }}>
          {[
            { id: "A", ctx: p.contextA },
            null,
            { id: "B", ctx: p.contextB },
          ].map((slot, idx) => {
            if (slot === null) {
              return <div key="vs" style={{ display: 'grid', placeItems: 'center' }}>
                <div style={{
                  width: 48, height: 48, borderRadius: '50%',
                  background: 'var(--neutral-100)',
                  display: 'grid', placeItems: 'center',
                  fontSize: 18, fontWeight: 700, color: 'var(--neutral-500)',
                }}>↔</div>
              </div>;
            }
            const active = survivor === slot.id;
            return (
              <button key={slot.id} onClick={() => setSurvivor(slot.id)} style={{
                textAlign: 'left',
                padding: 16, borderRadius: 6,
                border: active ? '2px solid var(--accent-data)' : '2px solid var(--neutral-200)',
                background: active ? 'var(--accent-data-bg, var(--neutral-50))' : 'var(--neutral-0)',
                cursor: 'pointer',
              }}>
                <div className="row gap-2" style={{ alignItems: 'center' }}>
                  <Chip size="sm" tone={active ? 'data' : 'neutral'}>Record {slot.id}</Chip>
                  {active && <Chip size="sm" tone="data"><Icon name="check" size={10}/> survivor</Chip>}
                </div>
                <div className="t-mono mt-2" style={{ fontSize: 12.5 }}>{slot.ctx.id}</div>
                <div className="t-bodysm mt-1">{slot.ctx.household}</div>
                <div className="t-cap mt-1">Line {slot.ctx.line} · {slot.ctx.role} · {slot.ctx.confirmed}</div>
              </button>
            );
          })}
        </div>
      </div>

      {/* Field-by-field diff */}
      <div className="card mt-4" style={{ padding: 0 }}>
        <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--neutral-200)' }}>
          <strong>Field-by-field comparison</strong>
          <div className="t-cap">{p.fields.filter(f => f.match).length} of {p.fields.length} fields match · click a row to flag a discrepancy for the audit.</div>
        </div>
        <table className="tbl" style={{ boxShadow: 'none' }}>
          <thead>
            <tr>
              <th>Field</th>
              <th>Record A</th>
              <th>Record B</th>
              <th>Similarity</th>
              <th>Result</th>
            </tr>
          </thead>
          <tbody>
            {p.fields.map(f => (
              <tr key={f.field} style={{ background: !f.match ? 'var(--neutral-50)' : 'transparent' }}>
                <td className="t-mono t-bodysm">{f.field}</td>
                <td className="t-bodysm" style={{ fontWeight: survivor === "A" ? 600 : 400 }}>{f.a}</td>
                <td className="t-bodysm" style={{ fontWeight: survivor === "B" ? 600 : 400 }}>{f.b}</td>
                <td>
                  <div className="row gap-2" style={{ alignItems: 'center' }}>
                    <div style={{ width: 60, height: 6, background: 'var(--neutral-100)', borderRadius: 3, overflow: 'hidden' }}>
                      <div style={{ width: `${f.similarity * 100}%`, height: '100%', background: f.similarity >= 0.85 ? 'var(--accent-data)' : f.similarity >= 0.5 ? 'var(--accent-update)' : 'var(--accent-danger)' }}/>
                    </div>
                    <span className="t-num t-cap" style={{ minWidth: 40, textAlign: 'right' }}>{f.similarity.toFixed(2)}</span>
                  </div>
                </td>
                <td>
                  {f.match
                    ? <Chip size="sm" tone="data"><Icon name="check" size={10}/> match</Chip>
                    : <Chip size="sm" tone="quality">divergent</Chip>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Decision */}
      <div className="card mt-4" style={{ padding: 0 }}>
        <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--neutral-200)' }}>
          <strong>Decision</strong>
          <div className="t-cap">Reason is required for merge and reject. 30-day un-merge window applies.</div>
        </div>
        <div style={{ padding: 16, display: 'grid', gridTemplateColumns: '1fr auto', gap: 12, alignItems: 'flex-start' }}>
          <textarea className="field-input" value={reason} onChange={e => setReason(e.target.value)} placeholder="State your reasoning — surfaces in the audit chain and the un-merge approval flow." style={{ width: '100%', minHeight: 90, padding: 10, fontFamily: 'inherit' }}/>
          <div className="col gap-2">
            <button className="btn btn-primary" onClick={() => onMerge?.({ survivor, reason })} disabled={reason.length < 10}>
              <Icon name="check" size={14}/> Merge (survivor: {survivor})
            </button>
            <button className="btn" onClick={() => onHold?.({ reason })}>
              <Icon name="clock" size={14}/> Put on hold
            </button>
            <button className="btn" onClick={() => onReject?.({ reason })} style={{ color: 'var(--accent-danger)' }} disabled={reason.length < 10}>
              <Icon name="x" size={14}/> Reject — not a duplicate
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

/* ===========================================================
   CHOICE LIST OPTION — edit a single ChoiceOption in a draft
   =========================================================== */
const AdminChoiceListOptionEditScreen = ({ option, onBack, onSave }) => {
  const o = option || {
    listName: "education_level", listLabel: "Education level",
    listVersion: 5, // draft
    code: "T6", label: "Doctorate / PhD",
    language: "en", sort: 20, status: "active",
    description: "ISCED 2024 level 8 — research doctorate.",
    parentCode: null,
  };
  const [draft, setDraft] = useStateAD({ code: o.code, label: o.label, language: o.language, sort: o.sort, status: o.status, description: o.description });

  return (
    <div className="page">
      <PageHeader
        back={{ label: "Choice lists", onClick: onBack }}
        eyebrow={<>ADMIN · REF · CHOICE LIST · <span className="t-mono">{o.listName}</span> · v{o.listVersion} (draft)</>}
        title={<>Edit option <span className="t-mono" style={{ marginLeft: 8 }}>{o.code}</span></>}
        sub={<>Inside <strong>{o.listLabel}</strong> · draft version — locks on submit-for-approval.</>}
        right={<>
          <button className="btn btn-primary" onClick={() => onSave?.(draft)}><Icon name="check" size={14}/> Save</button>
        </>}
      />

      <div className="grid" style={{ gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <div className="card" style={{ padding: 0 }}>
          <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--neutral-200)' }}>
            <strong>Option fields</strong>
          </div>
          <div style={{ padding: 16, display: 'grid', gridTemplateColumns: '120px 1fr', rowGap: 14, fontSize: 13 }}>
            <div className="muted">Code</div>
            <input className="field-input" value={draft.code} onChange={e => setDraft({ ...draft, code: e.target.value })} style={{ height: 32, padding: '4px 10px', fontFamily: 'var(--font-mono)', width: 160 }}/>
            <div className="muted">Label</div>
            <input className="field-input" value={draft.label} onChange={e => setDraft({ ...draft, label: e.target.value })} style={{ height: 32, padding: '4px 10px', width: '100%', maxWidth: 480 }}/>
            <div className="muted">Language</div>
            <select className="field-select" value={draft.language} onChange={e => setDraft({ ...draft, language: e.target.value })} style={{ height: 32, width: 160 }}>
              <option value="en">English (en)</option>
              <option value="lug">Luganda (lug)</option>
              <option value="ach">Acholi (ach)</option>
              <option value="nyn">Runyankole (nyn)</option>
            </select>
            <div className="muted">Sort</div>
            <input type="number" min={0} max={9999} value={draft.sort} onChange={e => setDraft({ ...draft, sort: parseInt(e.target.value) || 0 })} className="field-input" style={{ height: 32, padding: '4px 10px', width: 120, fontFamily: 'var(--font-mono)' }}/>
            <div className="muted">Status</div>
            <select className="field-select" value={draft.status} onChange={e => setDraft({ ...draft, status: e.target.value })} style={{ height: 32, width: 200 }}>
              <option value="active">active</option>
              <option value="deprecated">deprecated</option>
            </select>
            <div className="muted">Description</div>
            <textarea className="field-input" value={draft.description} onChange={e => setDraft({ ...draft, description: e.target.value })} style={{ width: '100%', minHeight: 80, padding: 10, fontFamily: 'inherit' }}/>
          </div>
        </div>

        <div className="tint-update" style={{ padding: 14, borderRadius: 6, borderLeft: '3px solid var(--accent-update)', alignSelf: 'start' }}>
          <div className="row gap-2" style={{ marginBottom: 6 }}>
            <Icon name="info" size={13} color="var(--accent-update)"/>
            <strong className="t-bodysm">Codes are forever</strong>
          </div>
          <div className="t-bodysm muted" style={{ lineHeight: 1.55 }}>
            Codes never repeat across an option's lifetime. If you change <code>code</code>, you are renaming this option —
            past intake responses using the old code remain readable. Deleting is forbidden; mark as{' '}
            <span className="t-mono">deprecated</span> and the option drops out of new questionnaires.
          </div>
        </div>
      </div>
    </div>
  );
};

Object.assign(window, {
  AdminGeoUnitDetailScreen,
  AdminUpdRoutingRuleEditScreen,
  AdminUserDetailScreen,
  AdminDdupPairDetailScreen,
  AdminChoiceListOptionEditScreen,
});
