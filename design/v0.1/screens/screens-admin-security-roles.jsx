/* global React, Icon, Chip, PageHeader, KPI */
// NSR MIS — Admin · Security · Roles & Scopes
// =========================================================
// Manages who can see what. Two complementary axes:
//   ROLE — auth.Group membership controls *which screens* they can open
//   SCOPE — apps.security.OperatorScope rows control *which rows*
//           they can see at any geographic level
//
// Maps to:
//   django.contrib.auth.Group  (roles — set elsewhere; this screen
//                               surfaces and toggles membership)
//   apps.security.OperatorScope (one row per scope assignment; user
//                               may hold many; "national" = wildcard)
//   apps.reference_data.GeographicUnit (scope_code is a code at the
//                                       matching level)

const { useState: useStateSEC, useMemo: useMemoSEC } = React;

const SEC_ROLES = [
  { id: "parish_coordinator",    label: "Parish Coordinator",        category: "operator",   users: 1218, desc: "First-level review of UPDs and intakes within their parish.", screens: ["console.registry","console.upd"], adminConsole: false },
  { id: "cdo",                   label: "Community Dev't Officer",   category: "operator",   users: 412,  desc: "Sub-county-level review; can approve PMT-relevant changes.", screens: ["console.registry","console.upd","console.programmes"], adminConsole: false },
  { id: "nsr_unit_coordinator",  label: "NSR Unit Coordinator",      category: "operator",   users: 18,   desc: "National-level review and policy.",                          screens: ["console.*"], adminConsole: false },
  { id: "dpo",                   label: "Data Protection Officer",   category: "security",   users: 4,    desc: "Audit chain + DSA scope reviews. Sign-off on PMT activation.", screens: ["console.audit","admin.audit","admin.security"], adminConsole: true },
  { id: "mglsd_statistics",      label: "MGLSD Statistics Unit",     category: "admin",      users: 8,    desc: "PMT model authoring + recalibration.",                       screens: ["admin.pmt","admin.refdata"], adminConsole: true },
  { id: "nsr_admin",             label: "NSR Admin",                 category: "admin",      users: 6,    desc: "Full admin console access.",                                 screens: ["admin.*"], adminConsole: true },
  { id: "nsr_dba",               label: "NSR DBA",                   category: "admin",      users: 3,    desc: "Database operations; data fix workflows.",                   screens: ["admin.refdata","admin.audit"], adminConsole: true },
  { id: "nsr_security",          label: "NSR Security",              category: "security",   users: 2,    desc: "Role + scope management; security incidents.",                screens: ["admin.security","admin.audit"], adminConsole: true },
  { id: "partner_steward",       label: "Partner Data Steward",      category: "partner",    users: 38,   desc: "Per-partner — sees DRS requests + lifecycle webhook events.", screens: ["console.partners","console.drs"], adminConsole: false },
];

const SEC_USERS = [
  { id: "u-akello-p",     name: "Akello P.",        username: "akello.p",     email: "akello.p@mglsd.go.ug",     status: "active",  lastLogin: "22 May · 14:01", mfa: true,  groups: ["nsr_unit_coordinator","dpo"], scopes: [{ level: "national", code: "" }], onboardedAt: "12 Sep 2023" },
  { id: "u-bahati-e",     name: "Bahati Esther",    username: "bahati.e",     email: "bahati.e@opm.go.ug",       status: "active",  lastLogin: "22 May · 12:48", mfa: true,  groups: ["partner_steward"],          scopes: [{ level: "partner", code: "OPM" }], onboardedAt: "04 Jan 2026" },
  { id: "u-adong-f",      name: "Adong F.",         username: "adong.f",      username2:"", email: "adong.f@mglsd.go.ug",      status: "active",  lastLogin: "22 May · 11:32", mfa: true,  groups: ["cdo"],                       scopes: [{ level: "sub_county", code: "SC-TAPAC" }, { level: "sub_county", code: "SC-RUPA" }], onboardedAt: "12 Mar 2024" },
  { id: "u-nakanwagi-d",  name: "Dr. Nakanwagi",    username: "nakanwagi.d",  email: "nakanwagi.d@mglsd.go.ug",  status: "active",  lastLogin: "22 May · 09:18", mfa: true,  groups: ["mglsd_statistics"],          scopes: [{ level: "national", code: "" }], onboardedAt: "01 Dec 2024" },
  { id: "u-otieno-j",     name: "Otieno J.",        username: "otieno.j",     email: "otieno.j@mglsd.go.ug",     status: "active",  lastLogin: "22 May · 08:42", mfa: true,  groups: ["dpo","nsr_security"],        scopes: [{ level: "national", code: "" }], onboardedAt: "08 Sep 2023" },
  { id: "u-mukasa-r",     name: "Mutebi R.",        username: "mutebi.r",     email: "mutebi.r@mglsd.go.ug",     status: "active",  lastLogin: "21 May · 16:01", mfa: true,  groups: ["nsr_admin"],                 scopes: [{ level: "national", code: "" }], onboardedAt: "05 Jan 2023" },
  { id: "u-namutebi-s",   name: "Namutebi S.",      username: "namutebi.s",   email: "namutebi.s@lyantonde.go.ug", status: "active", lastLogin: "20 May · 13:12", mfa: false, groups: ["parish_coordinator"],        scopes: [{ level: "parish", code: "PAR-KIBALINGA" }], onboardedAt: "14 Feb 2025" },
  { id: "u-okello-j",     name: "Okello James",     username: "okello.j",     email: "okello.j@gulu.go.ug",      status: "active",  lastLogin: "19 May · 09:08", mfa: true,  groups: ["parish_coordinator"],        scopes: [{ level: "parish", code: "PAR-PAGEYA" }], onboardedAt: "08 Apr 2025" },
  { id: "u-acheng-m",     name: "Acheng M.",        username: "acheng.m",     email: "acheng.m@npm.go.ug",       status: "active",  lastLogin: "18 May · 11:42", mfa: true,  groups: ["cdo"],                       scopes: [{ level: "sub_county", code: "SC-LOKOPO" }], onboardedAt: "12 Jun 2024" },
  { id: "u-suspended-x",  name: "Test User X",      username: "test.x",       email: "test.x@example.com",       status: "suspended", lastLogin: "18 Mar · 09:00", mfa: false, groups: ["parish_coordinator"],      scopes: [{ level: "parish", code: "PAR-OBSOLETE" }], onboardedAt: "22 Feb 2024", suspendedReason: "Test account — flagged by security review 2026-03-18" },
];

const SCOPE_LEVELS = ["national","region","sub_region","district","sub_county","parish","village","partner"];
const SCOPE_LEVEL_LABEL = {
  national:"National (wildcard)", region:"Region", sub_region:"Sub-region", district:"District",
  sub_county:"Sub-county", parish:"Parish", village:"Village", partner:"Partner",
};
const ROLE_TONE = { operator:"data", security:"danger", admin:"system", partner:"programme" };

const AdminSecurityRolesScreen = () => {
  const [tab, setTab] = useStateSEC("users");
  const [q, setQ] = useStateSEC("");
  const [roleFilter, setRoleFilter] = useStateSEC("");
  const [statusFilter, setStatusFilter] = useStateSEC("");

  const users = useMemoSEC(() => SEC_USERS.filter(u => {
    if (q && !(u.name.toLowerCase().includes(q.toLowerCase()) || u.username.includes(q.toLowerCase()) || u.email.includes(q.toLowerCase()))) return false;
    if (roleFilter && !u.groups.includes(roleFilter)) return false;
    if (statusFilter && u.status !== statusFilter) return false;
    return true;
  }), [q, roleFilter, statusFilter]);

  // KPIs
  const totalUsers = SEC_USERS.length;
  const adminUsers = SEC_USERS.filter(u => u.groups.some(g => SEC_ROLES.find(r => r.id === g)?.adminConsole)).length;
  const nationalScope = SEC_USERS.filter(u => u.scopes.some(s => s.level === "national")).length;
  const noMfa = SEC_USERS.filter(u => !u.mfa).length;

  return (
    <div className="page">
      <PageHeader
        eyebrow="ADMIN · SECURITY · roles & scopes"
        title="Roles & scopes"
        sub="Who can see what. ROLE controls which screens; SCOPE controls which records within a screen."
        right={<>
          <button className="btn"><Icon name="download" size={14}/> Export users</button>
          <button className="btn btn-primary"><Icon name="plus" size={14}/> Add user</button>
        </>}
      />

      <div className="grid grid-4">
        <KPI title="Active users" value={totalUsers - SEC_USERS.filter(u => u.status === "suspended").length} foot={`${SEC_USERS.filter(u => u.status === "suspended").length} suspended`}/>
        <KPI title="Admin Console access" value={adminUsers} foot="In one of 5 admin groups"/>
        <KPI title="National wildcard scope" value={nationalScope} foot="See every household — DPO + NSR Coordinator only"/>
        <KPI title="MFA not enrolled" value={noMfa} foot="Will be force-enrolled at next login"  trend="down" trendValue="-3 this wk"/>
      </div>

      <div role="tablist" style={{ display: 'flex', borderBottom: '1px solid var(--neutral-300)', marginTop: 24, flexWrap: 'wrap' }}>
        {[
          { id: "users", label: `Users (${totalUsers})` },
          { id: "roles", label: `Roles (${SEC_ROLES.length})` },
          { id: "matrix", label: "Permission matrix" },
        ].map(t => {
          const active = t.id === tab;
          return (
            <button key={t.id} onClick={() => setTab(t.id)} style={{
              padding: '10px 16px', border: 0, background: 'transparent', cursor: 'pointer',
              borderBottom: active ? '2px solid var(--primary-900)' : '2px solid transparent',
              marginBottom: -1,
              color: active ? 'var(--primary-900)' : 'var(--neutral-700)',
              fontWeight: active ? 600 : 500, fontSize: 13.5,
            }}>{t.label}</button>
          );
        })}
      </div>

      {tab === "users" && (
        <>
          <div className="card mt-4" style={{ padding: '14px 16px' }}>
            <div className="row gap-3" style={{ flexWrap: 'wrap' }}>
              <div className="search" style={{ maxWidth: 320, height: 34, background: 'var(--neutral-0)' }}>
                <Icon name="search" size={16} color="var(--neutral-500)"/>
                <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search name, username, email…"/>
              </div>
              <select className="field-select" style={{ height: 34, width: 'auto', minWidth: 180 }} value={roleFilter} onChange={e => setRoleFilter(e.target.value)}>
                <option value="">Any role</option>
                {SEC_ROLES.map(r => <option key={r.id} value={r.id}>{r.label}</option>)}
              </select>
              <select className="field-select" style={{ height: 34, width: 'auto', minWidth: 140 }} value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
                <option value="">Any status</option>
                <option value="active">Active</option>
                <option value="suspended">Suspended</option>
              </select>
              <div style={{ flex: 1 }}/>
              <span className="t-cap">{users.length} of {totalUsers}</span>
            </div>
          </div>

          <div className="card mt-4">
            <table className="tbl">
              <thead>
                <tr>
                  <th>User</th>
                  <th>Roles</th>
                  <th>Scopes</th>
                  <th>MFA</th>
                  <th>Last login</th>
                  <th>Status</th>
                  <th className="col-actions"></th>
                </tr>
              </thead>
              <tbody>
                {users.map(u => (
                  <tr key={u.id} style={{ cursor: 'pointer' }}>
                    <td>
                      <div className="row gap-3">
                        <div style={{
                          width: 30, height: 30, borderRadius: '50%',
                          background: 'var(--primary-100)', color: 'var(--primary-900)',
                          display: 'grid', placeItems: 'center', fontSize: 11, fontWeight: 600,
                        }}>{u.name.split(' ').map(w => w[0]).slice(0, 2).join('')}</div>
                        <div>
                          <div style={{ fontWeight: 500 }}>{u.name}</div>
                          <div className="t-cap t-mono" style={{ fontSize: 11 }}>{u.username}</div>
                        </div>
                      </div>
                    </td>
                    <td>
                      <div className="row-wrap" style={{ gap: 4 }}>
                        {u.groups.map(g => {
                          const r = SEC_ROLES.find(x => x.id === g);
                          return r ? <Chip key={g} size="sm" tone={ROLE_TONE[r.category]}>{r.label}</Chip> : <Chip key={g} size="sm">{g}</Chip>;
                        })}
                      </div>
                    </td>
                    <td>
                      <div className="row-wrap" style={{ gap: 4 }}>
                        {u.scopes.map((s, i) => (
                          <Chip key={i} size="sm" tone={s.level === "national" ? "danger" : s.level === "partner" ? "programme" : "data"}>
                            {s.level === "national" ? "national" : `${s.level} · ${s.code}`}
                          </Chip>
                        ))}
                      </div>
                    </td>
                    <td>
                      {u.mfa
                        ? <Chip size="sm" tone="data"><Icon name="check" size={10}/> on</Chip>
                        : <Chip size="sm" tone="danger">off</Chip>}
                    </td>
                    <td className="t-cap" style={{ whiteSpace: 'nowrap' }}>{u.lastLogin}</td>
                    <td>
                      {u.status === "active"
                        ? <Chip size="sm" tone="data">Active</Chip>
                        : <Chip size="sm" tone="quality">Suspended</Chip>}
                    </td>
                    <td className="col-actions"><Icon name="chevronRight" size={16} color="var(--neutral-500)"/></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {tab === "roles" && (
        <div className="card mt-4">
          <table className="tbl">
            <thead><tr><th>Role</th><th>Category</th><th>Users</th><th>Description</th><th>Screen scope</th><th>Admin Console</th></tr></thead>
            <tbody>
              {SEC_ROLES.map(r => (
                <tr key={r.id}>
                  <td>
                    <div style={{ fontWeight: 600 }}>{r.label}</div>
                    <div className="t-cap t-mono">{r.id}</div>
                  </td>
                  <td><Chip size="sm" tone={ROLE_TONE[r.category]}>{r.category}</Chip></td>
                  <td className="t-num">{r.users.toLocaleString()}</td>
                  <td className="t-bodysm" style={{ maxWidth: 320 }}>{r.desc}</td>
                  <td>
                    <div className="row-wrap" style={{ gap: 4 }}>
                      {r.screens.map(s => <Chip key={s} size="sm">{s}</Chip>)}
                    </div>
                  </td>
                  <td>
                    {r.adminConsole
                      ? <Chip size="sm" tone="data"><Icon name="check" size={10}/> yes</Chip>
                      : <span className="muted t-cap">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === "matrix" && (
        <div className="card mt-4" style={{ padding: 20 }}>
          <strong className="t-bodysm">Permission matrix — roles × screens</strong>
          <div className="t-cap mt-1 mb-3">A ✓ means users in that role can open that screen subject to their geographic scope.</div>
          <table className="tbl" style={{ boxShadow: 'none' }}>
            <thead>
              <tr>
                <th>Screen</th>
                {SEC_ROLES.filter(r => r.adminConsole || r.id === "nsr_unit_coordinator").slice(0, 5).map(r => (
                  <th key={r.id} style={{ textAlign: 'center', minWidth: 90 }}>
                    <div className="t-cap">{r.label.split(' ')[0]}</div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {[
                ["PMT Dashboard",          [false, true,  true,  false, false]],
                ["PMT Configuration",      [false, true,  true,  false, false]],
                ["Choice lists",           [false, true,  true,  false, false]],
                ["Geography",              [false, false, true,  true,  false]],
                ["UPD routing",            [true,  false, true,  false, false]],
                ["DQA rules",              [false, true,  true,  false, false]],
                ["DDUP model",             [false, false, true,  false, false]],
                ["Roles & scopes",         [false, false, true,  false, true]],
                ["Audit chain",            [true,  false, true,  false, true]],
              ].map(([screen, perms]) => (
                <tr key={screen}>
                  <td className="t-bodysm" style={{ fontWeight: 500 }}>{screen}</td>
                  {perms.map((ok, i) => (
                    <td key={i} style={{ textAlign: 'center' }}>
                      {ok
                        ? <Icon name="check" size={14} color="var(--accent-data)"/>
                        : <span className="muted">—</span>}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="tint-update mt-5" style={{ padding: 14, borderRadius: 6, borderLeft: '3px solid var(--accent-update)' }}>
        <div className="row gap-2" style={{ marginBottom: 4 }}>
          <Icon name="shield" size={13} color="var(--accent-update)"/>
          <strong className="t-bodysm">ABAC scope (SAD §8.2)</strong>
        </div>
        <div className="t-bodysm muted">
          Scope is enforced at every list query — Households are partitioned by sub-region (ADR-0005); a user without
          national wildcard sees only rows whose <span className="t-mono">sub_region_code</span> matches one of their
          OperatorScope entries. The PARTNER scope is non-geographic; it gates DataRequests under DSAs that belong to
          the named Partner.
        </div>
      </div>
    </div>
  );
};

Object.assign(window, { AdminSecurityRolesScreen });
