/* global React, Icon, Chip, PageHeader, KPI */
// NSR MIS - Admin - Security - Roles & Scopes
// =========================================================
// ROLE controls which screens a user can open.
// SCOPE controls which records a user can see inside those screens.

const { useState: useStateSEC, useMemo: useMemoSEC } = React;

const secDownloadCsv = (filename, rows) => {
  const csv = rows.map(row => row.map(v => `"${String(v ?? "").replace(/"/g, '""')}"`).join(",")).join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
};

const SEC_ROLES = [
  { id: "parish_coordinator", label: "Parish Coordinator", category: "operator", users: 1218, desc: "First-level review of UPDs and intakes within their parish.", screens: ["console.registry", "console.upd"], adminConsole: false },
  { id: "cdo", label: "Community Dev't Officer", category: "operator", users: 412, desc: "Sub-county-level review; can approve PMT-relevant changes.", screens: ["console.registry", "console.upd", "console.programmes"], adminConsole: false },
  { id: "nsr_unit_coordinator", label: "NSR Unit Coordinator", category: "operator", users: 18, desc: "National-level review and policy.", screens: ["console.*"], adminConsole: false },
  { id: "dpo", label: "Data Protection Officer", category: "security", users: 4, desc: "Audit chain and DSA scope reviews. Sign-off on PMT activation.", screens: ["console.audit", "admin.audit", "admin.security"], adminConsole: true },
  { id: "mglsd_statistics", label: "MGLSD Statistics Unit", category: "admin", users: 8, desc: "PMT model authoring and recalibration.", screens: ["admin.pmt", "admin.refdata"], adminConsole: true },
  { id: "nsr_admin", label: "NSR Admin", category: "admin", users: 6, desc: "Full admin console access.", screens: ["admin.*"], adminConsole: true },
  { id: "nsr_dba", label: "NSR DBA", category: "admin", users: 3, desc: "Database operations; data fix workflows.", screens: ["admin.refdata", "admin.audit"], adminConsole: true },
  { id: "nsr_security", label: "NSR Security", category: "security", users: 2, desc: "Role and scope management; security incidents.", screens: ["admin.security", "admin.audit"], adminConsole: true },
  { id: "partner_steward", label: "Partner Data Steward", category: "partner", users: 38, desc: "Per-partner - sees DRS requests and lifecycle webhook events.", screens: ["console.partners", "console.drs"], adminConsole: false },
];

const SEC_USERS = [
  { id: "u-akello-p", name: "Akello P.", username: "akello.p", email: "akello.p@mglsd.go.ug", phone: "+256 772 410 001", status: "active", lastLogin: "22 May - 14:01", mfa: true, mfaMethod: "TOTP", groups: ["nsr_unit_coordinator", "dpo"], scopes: [{ level: "national", code: "", active: true, note: "National oversight" }], onboardedAt: "12 Sep 2023", lastPasswordReset: "08 Mar 2026", sessionCount24h: 2 },
  { id: "u-bahati-e", name: "Bahati Esther", username: "bahati.e", email: "bahati.e@opm.go.ug", phone: "+256 772 410 002", status: "active", lastLogin: "22 May - 12:48", mfa: true, mfaMethod: "TOTP", groups: ["partner_steward"], scopes: [{ level: "partner", code: "OPM", active: true, note: "OPM DRS workspace" }], onboardedAt: "04 Jan 2026", lastPasswordReset: "18 Feb 2026", sessionCount24h: 1 },
  { id: "u-adong-f", name: "Adong F.", username: "adong.f", email: "adong.f@mglsd.go.ug", phone: "+256 772 412 089", status: "active", lastLogin: "22 May - 11:32", mfa: true, mfaMethod: "TOTP", groups: ["cdo"], scopes: [{ level: "sub_county", code: "SC-TAPAC", active: true, note: "Tapac workload" }, { level: "sub_county", code: "SC-RUPA", active: true, note: "Rupa workload" }], onboardedAt: "12 Mar 2024", lastPasswordReset: "08 Mar 2026", sessionCount24h: 3 },
  { id: "u-nakanwagi-d", name: "Dr. Nakanwagi", username: "nakanwagi.d", email: "nakanwagi.d@mglsd.go.ug", phone: "+256 772 410 004", status: "active", lastLogin: "22 May - 09:18", mfa: true, mfaMethod: "WebAuthn", groups: ["mglsd_statistics"], scopes: [{ level: "national", code: "", active: true, note: "PMT calibration" }], onboardedAt: "01 Dec 2024", lastPasswordReset: "02 Apr 2026", sessionCount24h: 2 },
  { id: "u-otieno-j", name: "Otieno J.", username: "otieno.j", email: "otieno.j@mglsd.go.ug", phone: "+256 772 410 005", status: "active", lastLogin: "22 May - 08:42", mfa: true, mfaMethod: "TOTP", groups: ["dpo", "nsr_security"], scopes: [{ level: "national", code: "", active: true, note: "Security and privacy oversight" }], onboardedAt: "08 Sep 2023", lastPasswordReset: "19 Feb 2026", sessionCount24h: 4 },
  { id: "u-mukasa-r", name: "Mutebi R.", username: "mutebi.r", email: "mutebi.r@mglsd.go.ug", phone: "+256 772 410 006", status: "active", lastLogin: "21 May - 16:01", mfa: true, mfaMethod: "TOTP", groups: ["nsr_admin"], scopes: [{ level: "national", code: "", active: true, note: "System administration" }], onboardedAt: "05 Jan 2023", lastPasswordReset: "12 Jan 2026", sessionCount24h: 2 },
  { id: "u-namutebi-s", name: "Namutebi S.", username: "namutebi.s", email: "namutebi.s@lyantonde.go.ug", phone: "+256 772 410 007", status: "active", lastLogin: "20 May - 13:12", mfa: false, mfaMethod: "", groups: ["parish_coordinator"], scopes: [{ level: "parish", code: "PAR-KIBALINGA", active: true, note: "Parish walk-in desk" }], onboardedAt: "14 Feb 2025", lastPasswordReset: "04 Apr 2026", sessionCount24h: 0 },
  { id: "u-okello-j", name: "Okello James", username: "okello.j", email: "okello.j@gulu.go.ug", phone: "+256 772 410 008", status: "active", lastLogin: "19 May - 09:08", mfa: true, mfaMethod: "SMS fallback", groups: ["parish_coordinator"], scopes: [{ level: "parish", code: "PAR-PAGEYA", active: true, note: "Pageya parish" }], onboardedAt: "08 Apr 2025", lastPasswordReset: "22 Mar 2026", sessionCount24h: 1 },
  { id: "u-acheng-m", name: "Acheng M.", username: "acheng.m", email: "acheng.m@npm.go.ug", phone: "+256 772 410 009", status: "active", lastLogin: "18 May - 11:42", mfa: true, mfaMethod: "TOTP", groups: ["cdo"], scopes: [{ level: "sub_county", code: "SC-LOKOPO", active: true, note: "Lokopo workload" }], onboardedAt: "12 Jun 2024", lastPasswordReset: "15 Mar 2026", sessionCount24h: 0 },
  { id: "u-suspended-x", name: "Test User X", username: "test.x", email: "test.x@example.com", phone: "", status: "suspended", lastLogin: "18 Mar - 09:00", mfa: false, mfaMethod: "", groups: ["parish_coordinator"], scopes: [{ level: "parish", code: "PAR-OBSOLETE", active: false, note: "Retired test scope" }], onboardedAt: "22 Feb 2024", lastPasswordReset: "18 Mar 2026", sessionCount24h: 0, suspendedReason: "Test account - flagged by security review 2026-03-18" },
];

const SCOPE_LEVELS = ["national", "region", "sub_region", "district", "sub_county", "parish", "village", "partner"];
const SCOPE_LEVEL_LABEL = {
  national: "National (wildcard)", region: "Region", sub_region: "Sub-region", district: "District",
  sub_county: "Sub-county", parish: "Parish", village: "Village", partner: "Partner",
};
const ROLE_TONE = { operator: "data", security: "danger", admin: "system", partner: "programme" };
const ROLE_CATEGORIES = ["operator", "security", "admin", "partner"];
const PERMISSION_SCREENS = [
  "console.registry", "console.upd", "console.programmes", "console.audit", "console.partners",
  "console.drs", "admin.pmt", "admin.refdata", "admin.security", "admin.audit", "admin.*", "console.*",
];
const OPERATOR_SCOPE_OPTIONS = {
  region: [
    { code: "R-NORTHERN", name: "Northern Region" },
    { code: "R-EASTERN", name: "Eastern Region" },
    { code: "R-CENTRAL", name: "Central Region" },
    { code: "R-WESTERN", name: "Western Region" },
  ],
  sub_region: [
    { code: "SR-KARAMOJA", name: "Karamoja" },
    { code: "SR-ACHOLI", name: "Acholi" },
    { code: "SR-LANGO", name: "Lango" },
    { code: "SR-WEST-NILE", name: "West Nile" },
    { code: "SR-BUGANDA-SOUTH", name: "Buganda South" },
    { code: "SR-BUGANDA-NORTH", name: "Buganda North" },
    { code: "SR-TESO", name: "Teso" },
    { code: "SR-BUKEDI", name: "Bukedi" },
    { code: "SR-ANKOLE", name: "Ankole" },
    { code: "SR-KIGEZI", name: "Kigezi" },
    { code: "SR-BUNYORO", name: "Bunyoro" },
    { code: "SR-RWENZORI", name: "Rwenzori" },
  ],
  district: [
    { code: "DST-MOROTO", name: "Moroto" },
    { code: "DST-NAPAK", name: "Napak" },
    { code: "DST-NAKAPIRIPIRIT", name: "Nakapiripirit" },
    { code: "DST-KOTIDO", name: "Kotido" },
    { code: "DST-KAABONG", name: "Kaabong" },
    { code: "DST-ABIM", name: "Abim" },
    { code: "DST-AMUDAT", name: "Amudat" },
    { code: "DST-KARENGA", name: "Karenga" },
    { code: "DST-NABILATUK", name: "Nabilatuk" },
    { code: "DST-GULU", name: "Gulu" },
    { code: "DST-ARUA", name: "Arua" },
    { code: "DST-LYANTONDE", name: "Lyantonde" },
    { code: "DST-LIRA", name: "Lira" },
    { code: "DST-KAMPALA", name: "Kampala" },
    { code: "DST-MUKONO", name: "Mukono" },
    { code: "DST-MBARARA", name: "Mbarara" },
    { code: "DST-KABALE", name: "Kabale" },
    { code: "DST-HOIMA", name: "Hoima" },
    { code: "DST-KASESE", name: "Kasese" },
    { code: "DST-SOROTI", name: "Soroti" },
    { code: "DST-TORORO", name: "Tororo" },
  ],
  sub_county: [
    { code: "SC-TAPAC", name: "Tapac" },
    { code: "SC-RUPA", name: "Rupa" },
    { code: "SC-LOKOPO", name: "Lokopo" },
    { code: "SC-KATIKEKILE", name: "Katikekile" },
    { code: "SC-LYANTONDE-TC", name: "Lyantonde Town Council" },
  ],
  parish: [
    { code: "PAR-NAKILORO", name: "Nakiloro" },
    { code: "PAR-KIBALINGA", name: "Kibalinga" },
    { code: "PAR-PAGEYA", name: "Pageya" },
    { code: "PAR-LOKOPO", name: "Lokopo" },
    { code: "PAR-ADEKOKWOK", name: "Adekokwok" },
  ],
  village: [
    { code: "VLG-NAKILORO-A", name: "Nakiloro A" },
    { code: "VLG-LOPUWAPUWA-A", name: "Lopuwapuwa A" },
    { code: "VLG-KAKINGOL", name: "Kakingol" },
    { code: "VLG-OKELLO", name: "Okello Village" },
    { code: "VLG-AYWEE", name: "Aywee" },
  ],
  partner: [
    { code: "OPM", name: "Office of the Prime Minister" },
    { code: "WFP", name: "World Food Programme" },
    { code: "NUSAF", name: "NUSAF" },
    { code: "PDM", name: "Parish Development Model" },
  ],
};

const secInitials = (name) => String(name || "?").split(" ").map(w => w[0]).slice(0, 2).join("").toUpperCase();
const secClone = (value) => JSON.parse(JSON.stringify(value));
const secSlug = (value) => String(value || "").trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
const secRoleLabel = (roles, id) => roles.find(r => r.id === id)?.label || id;
const secScopeLabel = (scope) => scope.level === "national" ? "national" : `${scope.level}:${scope.code || "*"}`;
const secScopeOptions = (level) => OPERATOR_SCOPE_OPTIONS[level] || [];
const secScopeName = (scope) => secScopeOptions(scope.level).find(opt => opt.code === scope.code)?.name || "";
const secDefaultScopeCode = (level) => level === "national" ? "" : (secScopeOptions(level)[0]?.code || "");
const secFilteredScopeOptions = (scope) => {
  const query = String(scope.search || "").trim().toLowerCase();
  const options = secScopeOptions(scope.level);
  if (!query) return options;
  return options.filter(opt => `${opt.name} ${opt.code}`.toLowerCase().includes(query));
};
const secRoleCounts = (users) => users.reduce((acc, user) => {
  user.groups.forEach(group => { acc[group] = (acc[group] || 0) + 1; });
  return acc;
}, {});

const secBlankUser = (roles) => ({
  id: `u-${Date.now()}`,
  name: "",
  username: "",
  email: "",
  phone: "",
  status: "active",
  lastLogin: "Never",
  mfa: false,
  mfaMethod: "",
  groups: roles[0] ? [roles[0].id] : [],
  scopes: [{ level: "parish", code: secDefaultScopeCode("parish"), active: true, note: "" }],
  onboardedAt: "26 May 2026",
  lastPasswordReset: "Never",
  sessionCount24h: 0,
  suspendedReason: "",
});

const secBlankRole = () => ({
  id: "",
  label: "",
  category: "operator",
  users: 0,
  desc: "",
  screens: ["console.registry"],
  adminConsole: false,
});

const SecDetailRow = ({ label, children }) => (
  <div style={{ display: "grid", gridTemplateColumns: "128px 1fr", gap: 12, padding: "8px 0", borderBottom: "1px solid var(--neutral-100)" }}>
    <div className="t-cap">{label}</div>
    <div className="t-bodysm">{children || <span className="muted">-</span>}</div>
  </div>
);

const SecField = ({ label, children, hint }) => (
  <label className="field">
    <span className="field-label">{label}</span>
    {children}
    {hint && <span className="field-help">{hint}</span>}
  </label>
);

const SEC_MASTER_DETAIL_STYLE = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(420px, 1fr))",
  gap: 16,
  alignItems: "start",
};
const SEC_DETAIL_CARD_STYLE = {
  padding: 0,
  position: "sticky",
  top: 16,
  maxHeight: "calc(100vh - 56px)",
  overflow: "auto",
};
const SEC_COMPACT_FIELD_GRID = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))",
  gap: "12px 14px",
};
const SEC_SCOPE_EDITOR_STYLE = {
  display: "grid",
  gridTemplateColumns: "minmax(120px, 0.9fr) 86px 34px",
  gap: 8,
  alignItems: "center",
  padding: 10,
  border: "1px solid var(--neutral-200)",
  borderRadius: 4,
  background: "var(--neutral-0)",
};
const SEC_SCOPE_SEARCH_LIST_STYLE = {
  gridColumn: "1 / -1",
  border: "1px solid var(--neutral-200)",
  borderRadius: 4,
  background: "var(--neutral-50)",
  maxHeight: 180,
  overflowY: "auto",
  padding: 6,
  display: "grid",
  gap: 4,
};

const AdminSecurityRolesScreen = () => {
  const [tab, setTab] = useStateSEC("users");
  const [q, setQ] = useStateSEC("");
  const [roleFilter, setRoleFilter] = useStateSEC("");
  const [statusFilter, setStatusFilter] = useStateSEC("");
  const [usersState, setUsersState] = useStateSEC(() => secClone(SEC_USERS));
  const [rolesState, setRolesState] = useStateSEC(() => secClone(SEC_ROLES));
  const [selectedUserId, setSelectedUserId] = useStateSEC(SEC_USERS[0]?.id || "");
  const [selectedRoleId, setSelectedRoleId] = useStateSEC(SEC_ROLES[0]?.id || "");
  const [mode, setMode] = useStateSEC("view");
  const [draft, setDraft] = useStateSEC(null);
  const [toast, setToast] = useStateSEC("");

  const roleCounts = useMemoSEC(() => secRoleCounts(usersState), [usersState]);
  const users = useMemoSEC(() => usersState.filter(u => {
    const query = q.trim().toLowerCase();
    if (query && !(`${u.name} ${u.username} ${u.email}`.toLowerCase().includes(query))) return false;
    if (roleFilter && !u.groups.includes(roleFilter)) return false;
    if (statusFilter && u.status !== statusFilter) return false;
    return true;
  }), [usersState, q, roleFilter, statusFilter]);

  const selectedUser = usersState.find(u => u.id === selectedUserId) || usersState[0] || null;
  const selectedRole = rolesState.find(r => r.id === selectedRoleId) || rolesState[0] || null;
  const totalUsers = usersState.length;
  const activeUsers = usersState.filter(u => u.status === "active").length;
  const adminUsers = usersState.filter(u => u.groups.some(g => rolesState.find(r => r.id === g)?.adminConsole)).length;
  const nationalScope = usersState.filter(u => u.scopes.some(s => s.level === "national" && s.active !== false)).length;
  const noMfa = usersState.filter(u => !u.mfa).length;

  const startCreateUser = () => {
    setTab("users");
    setMode("createUser");
    setDraft(secBlankUser(rolesState));
    setToast("");
  };
  const startEditUser = (user = selectedUser) => {
    if (!user) return;
    setTab("users");
    setSelectedUserId(user.id);
    setMode("editUser");
    setDraft(secClone(user));
    setToast("");
  };
  const startCreateRole = () => {
    setTab("roles");
    setMode("createRole");
    setDraft(secBlankRole());
    setToast("");
  };
  const startEditRole = (role = selectedRole) => {
    if (!role) return;
    setTab("roles");
    setSelectedRoleId(role.id);
    setMode("editRole");
    setDraft(secClone({ ...role, users: roleCounts[role.id] || 0 }));
    setToast("");
  };
  const cancelEdit = () => {
    setMode("view");
    setDraft(null);
    setToast("");
  };

  const saveUser = () => {
    const clean = {
      ...draft,
      name: draft.name.trim(),
      username: draft.username.trim(),
      email: draft.email.trim(),
      phone: draft.phone.trim(),
      scopes: draft.scopes.map(s => ({
        level: s.level,
        code: s.level === "national" ? "" : String(s.code || secDefaultScopeCode(s.level) || "").trim(),
        active: s.active !== false,
        note: String(s.note || "").trim(),
      })),
    };
    if (!clean.name || !clean.username || !clean.email) {
      setToast("Name, username, and email are required.");
      return;
    }
    setUsersState(prev => mode === "createUser" ? [clean, ...prev] : prev.map(u => u.id === clean.id ? clean : u));
    setSelectedUserId(clean.id);
    setMode("view");
    setDraft(null);
    setToast(`${clean.name} saved.`);
  };

  const saveRole = () => {
    const clean = {
      ...draft,
      id: secSlug(draft.id || draft.label),
      label: draft.label.trim(),
      desc: draft.desc.trim(),
      screens: draft.screens.filter(Boolean),
      users: roleCounts[draft.id] || 0,
    };
    if (!clean.id || !clean.label || clean.screens.length === 0) {
      setToast("Role id, label, and at least one screen are required.");
      return;
    }
    if (mode === "createRole" && rolesState.some(r => r.id === clean.id)) {
      setToast("Role id already exists.");
      return;
    }
    const previousId = mode === "editRole" ? selectedRoleId : clean.id;
    setRolesState(prev => mode === "createRole" ? [clean, ...prev] : prev.map(r => r.id === previousId ? clean : r));
    if (previousId !== clean.id) {
      setUsersState(prev => prev.map(u => ({ ...u, groups: u.groups.map(g => g === previousId ? clean.id : g) })));
    }
    setSelectedRoleId(clean.id);
    setMode("view");
    setDraft(null);
    setToast(`${clean.label} saved.`);
  };

  const deleteUser = (user = selectedUser) => {
    if (!user) return;
    const remaining = usersState.filter(u => u.id !== user.id);
    setUsersState(remaining);
    setSelectedUserId(remaining[0]?.id || "");
    setMode("view");
    setDraft(null);
    setToast(`${user.name} deleted from this workspace.`);
  };

  const deleteRole = (role = selectedRole) => {
    if (!role) return;
    const remainingRoles = rolesState.filter(r => r.id !== role.id);
    setRolesState(remainingRoles);
    setUsersState(prev => prev.map(u => ({ ...u, groups: u.groups.filter(g => g !== role.id) })));
    setSelectedRoleId(remainingRoles[0]?.id || "");
    setMode("view");
    setDraft(null);
    setToast(`${role.label} deleted; assignments were removed.`);
  };

  const updateUserScope = (index, patch) => {
    setDraft({
      ...draft,
      scopes: draft.scopes.map((scope, i) => i === index ? { ...scope, ...patch } : scope),
    });
  };
  const addUserScope = () => setDraft({ ...draft, scopes: [...draft.scopes, { level: "parish", code: secDefaultScopeCode("parish"), active: true, note: "" }] });
  const removeUserScope = (index) => setDraft({ ...draft, scopes: draft.scopes.filter((_, i) => i !== index) });
  const changeUserScopeLevel = (index, level) => {
    updateUserScope(index, {
      level,
      code: secDefaultScopeCode(level),
      search: "",
    });
  };
  const toggleUserRole = (roleId) => {
    const groups = draft.groups.includes(roleId)
      ? draft.groups.filter(id => id !== roleId)
      : [...draft.groups, roleId];
    setDraft({ ...draft, groups });
  };
  const toggleRoleScreen = (screen) => {
    const screens = draft.screens.includes(screen)
      ? draft.screens.filter(id => id !== screen)
      : [...draft.screens, screen];
    setDraft({ ...draft, screens });
  };

  const roleTone = (id) => ROLE_TONE[rolesState.find(r => r.id === id)?.category] || "neutral";

  const renderUserDetail = () => {
    const editing = mode === "editUser" || mode === "createUser";
    const u = editing ? draft : selectedUser;
    if (!u) return null;
    return (
      <div className="card" style={SEC_DETAIL_CARD_STYLE}>
        <div style={{ padding: "16px 18px", borderBottom: "1px solid var(--neutral-200)", display: "flex", gap: 12, alignItems: "center" }}>
          <div style={{ width: 42, height: 42, borderRadius: "50%", background: "var(--primary-100)", color: "var(--primary-900)", display: "grid", placeItems: "center", fontSize: 13, fontWeight: 700 }}>
            {secInitials(u.name)}
          </div>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontWeight: 700 }}>{editing ? (mode === "createUser" ? "New user" : "Edit user") : u.name}</div>
            <div className="t-cap t-mono">{u.username || u.id}</div>
          </div>
          <div style={{ flex: 1 }}/>
          {editing ? (
            <>
              <button className="btn btn-sm" onClick={cancelEdit}>Cancel</button>
              <button className="btn btn-sm btn-primary" onClick={saveUser}><Icon name="save" size={12}/> Save</button>
            </>
          ) : (
            <>
              <button className="btn btn-sm" onClick={() => startEditUser(u)}><Icon name="edit" size={12}/> Edit</button>
              <button className="btn btn-sm btn-danger" onClick={() => deleteUser(u)}><Icon name="trash" size={12}/> Delete</button>
            </>
          )}
        </div>

        <div style={{ padding: 18 }}>
          {editing ? (
            <div style={{ display: "grid", gap: 14 }}>
              <div style={SEC_COMPACT_FIELD_GRID}>
                <SecField label="Full name"><input className="field-input" value={u.name} onChange={e => setDraft({ ...u, name: e.target.value })}/></SecField>
                <SecField label="Username"><input className="field-input t-mono" value={u.username} onChange={e => setDraft({ ...u, username: e.target.value })}/></SecField>
                <SecField label="Email"><input className="field-input" value={u.email} onChange={e => setDraft({ ...u, email: e.target.value })}/></SecField>
                <SecField label="Phone"><input className="field-input" value={u.phone} onChange={e => setDraft({ ...u, phone: e.target.value })}/></SecField>
                <SecField label="Status">
                  <select className="field-select" value={u.status} onChange={e => setDraft({ ...u, status: e.target.value })}>
                    <option value="active">active</option>
                    <option value="suspended">suspended</option>
                  </select>
                </SecField>
                <SecField label="MFA method">
                  <select className="field-select" value={u.mfaMethod || ""} onChange={e => setDraft({ ...u, mfaMethod: e.target.value, mfa: !!e.target.value })}>
                    <option value="">off</option>
                    <option value="TOTP">TOTP</option>
                    <option value="WebAuthn">WebAuthn</option>
                    <option value="SMS fallback">SMS fallback</option>
                  </select>
                </SecField>
              </div>

              {u.status === "suspended" && (
                <SecField label="Suspension reason">
                  <textarea className="field-textarea" value={u.suspendedReason || ""} onChange={e => setDraft({ ...u, suspendedReason: e.target.value })}/>
                </SecField>
              )}

              <div>
                <div className="row" style={{ marginBottom: 8 }}>
                  <strong className="t-bodysm">Role assignments</strong>
                  <div style={{ flex: 1 }}/>
                  <span className="t-cap">{u.groups.length} selected</span>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 8 }}>
                  {rolesState.map(role => {
                    const checked = u.groups.includes(role.id);
                    return (
                      <label key={role.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 10px", border: "1px solid var(--neutral-200)", borderRadius: 4, background: checked ? "var(--accent-system-bg)" : "var(--neutral-0)", cursor: "pointer" }}>
                        <input type="checkbox" checked={checked} onChange={() => toggleUserRole(role.id)}/>
                        <span style={{ flex: 1 }}>
                          <span className="t-bodysm" style={{ fontWeight: 600 }}>{role.label}</span>
                          <span className="t-cap t-mono" style={{ display: "block" }}>{role.id}</span>
                        </span>
                      </label>
                    );
                  })}
                </div>
              </div>

              <div>
                <div className="row" style={{ marginBottom: 8 }}>
                  <strong className="t-bodysm">OperatorScope rows</strong>
                  <div style={{ flex: 1 }}/>
                  <button className="btn btn-sm" onClick={addUserScope}><Icon name="plus" size={12}/> Add scope</button>
                </div>
                <div style={{ display: "grid", gap: 8 }}>
                  {u.scopes.map((scope, index) => (
                    <div key={index} style={SEC_SCOPE_EDITOR_STYLE}>
                      <select className="field-select" value={scope.level} onChange={e => changeUserScopeLevel(index, e.target.value)}>
                        {SCOPE_LEVELS.map(level => <option key={level} value={level}>{level}</option>)}
                      </select>
                      <select className="field-select" value={scope.active === false ? "false" : "true"} onChange={e => updateUserScope(index, { active: e.target.value === "true" })}>
                        <option value="true">active</option>
                        <option value="false">inactive</option>
                      </select>
                      <button className="icon-btn" title="Remove scope" onClick={() => removeUserScope(index)}><Icon name="trash" size={12}/></button>
                      {scope.level === "national" ? (
                        <div className="tint-update" style={{ gridColumn: "1 / -1", padding: 10, borderRadius: 4 }}>
                          <div className="t-bodysm" style={{ fontWeight: 600 }}>All Uganda</div>
                          <div className="t-cap">National wildcard scope; no geographic code is stored.</div>
                        </div>
                      ) : (
                        <>
                          <div style={{ gridColumn: "1 / -1" }}>
                            <div className="row gap-2" style={{ marginBottom: 6 }}>
                              <Chip size="sm" tone={scope.level === "partner" ? "programme" : "data"}>
                                Selected {SCOPE_LEVEL_LABEL[scope.level] || scope.level}
                              </Chip>
                              <span className="t-mono t-cap">{scope.code || secDefaultScopeCode(scope.level)}</span>
                              <span className="t-cap">{secScopeName(scope)}</span>
                            </div>
                            <div className="search" style={{ height: 34, background: "var(--neutral-0)", maxWidth: "100%" }}>
                              <Icon name="search" size={15} color="var(--neutral-500)"/>
                              <input
                                value={scope.search || ""}
                                onChange={e => updateUserScope(index, { search: e.target.value })}
                                placeholder={`Search ${SCOPE_LEVEL_LABEL[scope.level] || scope.level} by name or code`}
                              />
                            </div>
                          </div>
                          <div style={SEC_SCOPE_SEARCH_LIST_STYLE}>
                            {secFilteredScopeOptions(scope).slice(0, 40).map(opt => {
                              const picked = (scope.code || secDefaultScopeCode(scope.level)) === opt.code;
                              return (
                                <button key={opt.code} type="button" onClick={() => updateUserScope(index, { code: opt.code, search: "" })} style={{
                                  display: "grid",
                                  gridTemplateColumns: "1fr auto",
                                  gap: 8,
                                  alignItems: "center",
                                  textAlign: "left",
                                  border: picked ? "1px solid var(--primary-700)" : "1px solid transparent",
                                  borderRadius: 4,
                                  padding: "7px 8px",
                                  background: picked ? "var(--primary-50, var(--neutral-0))" : "var(--neutral-0)",
                                  cursor: "pointer",
                                }}>
                                  <span>
                                    <span className="t-bodysm" style={{ fontWeight: 600 }}>{opt.name}</span>
                                    <span className="t-cap t-mono" style={{ display: "block" }}>{opt.code}</span>
                                  </span>
                                  {picked && <Icon name="check" size={13} color="var(--accent-data)"/>}
                                </button>
                              );
                            })}
                            {secFilteredScopeOptions(scope).length === 0 && (
                              <div className="muted t-cap" style={{ padding: 8 }}>No matching scope options.</div>
                            )}
                          </div>
                        </>
                      )}
                      <input className="field-input" value={scope.note || ""} onChange={e => updateUserScope(index, { note: e.target.value })} placeholder="note" style={{ gridColumn: "1 / -1" }}/>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <>
              <SecDetailRow label="Email">{u.email}</SecDetailRow>
              <SecDetailRow label="Phone">{u.phone}</SecDetailRow>
              <SecDetailRow label="Status"><Chip size="sm" tone={u.status === "active" ? "data" : "quality"}>{u.status}</Chip></SecDetailRow>
              <SecDetailRow label="MFA">{u.mfa ? <Chip size="sm" tone="data"><Icon name="check" size={10}/> {u.mfaMethod}</Chip> : <Chip size="sm" tone="danger">off</Chip>}</SecDetailRow>
              <SecDetailRow label="Onboarded">{u.onboardedAt}</SecDetailRow>
              <SecDetailRow label="Last login">{u.lastLogin}</SecDetailRow>
              <SecDetailRow label="Password reset">{u.lastPasswordReset}</SecDetailRow>
              <SecDetailRow label="Sessions 24h"><span className="t-num">{u.sessionCount24h}</span></SecDetailRow>
              {u.suspendedReason && <div className="tint-update mt-3" style={{ padding: 10, borderRadius: 4 }}>{u.suspendedReason}</div>}
              <div className="mt-4">
                <strong className="t-bodysm">Roles</strong>
                <div className="row-wrap mt-2">
                  {u.groups.length ? u.groups.map(g => <Chip key={g} size="sm" tone={roleTone(g)}>{secRoleLabel(rolesState, g)}</Chip>) : <span className="muted t-cap">No roles assigned</span>}
                </div>
              </div>
              <div className="mt-4">
                <strong className="t-bodysm">Scopes</strong>
                <table className="tbl mt-2" style={{ boxShadow: "none" }}>
                  <thead><tr><th>Level</th><th>Code</th><th>Status</th><th>Note</th></tr></thead>
                  <tbody>
                    {u.scopes.map((scope, index) => (
                      <tr key={index}>
                        <td><Chip size="sm" tone={scope.level === "national" ? "danger" : scope.level === "partner" ? "programme" : "data"}>{SCOPE_LEVEL_LABEL[scope.level] || scope.level}</Chip></td>
                        <td>
                          <div className="t-mono">{scope.code || "*"}</div>
                          {secScopeName(scope) && <div className="t-cap">{secScopeName(scope)}</div>}
                        </td>
                        <td>{scope.active === false ? <Chip size="sm" tone="quality">inactive</Chip> : <Chip size="sm" tone="data">active</Chip>}</td>
                        <td className="t-bodysm">{scope.note || <span className="muted">-</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      </div>
    );
  };

  const renderRoleDetail = () => {
    const editing = mode === "editRole" || mode === "createRole";
    const role = editing ? draft : selectedRole;
    if (!role) return null;
    const assignedUsers = usersState.filter(user => user.groups.includes(role.id));
    return (
      <div className="card" style={SEC_DETAIL_CARD_STYLE}>
        <div style={{ padding: "16px 18px", borderBottom: "1px solid var(--neutral-200)", display: "flex", gap: 12, alignItems: "center" }}>
          <div>
            <div style={{ fontWeight: 700 }}>{editing ? (mode === "createRole" ? "New role" : "Edit role") : role.label}</div>
            <div className="t-cap t-mono">{role.id || "new_role"}</div>
          </div>
          <div style={{ flex: 1 }}/>
          {editing ? (
            <>
              <button className="btn btn-sm" onClick={cancelEdit}>Cancel</button>
              <button className="btn btn-sm btn-primary" onClick={saveRole}><Icon name="save" size={12}/> Save</button>
            </>
          ) : (
            <>
              <button className="btn btn-sm" onClick={() => startEditRole(role)}><Icon name="edit" size={12}/> Edit</button>
              <button className="btn btn-sm btn-danger" onClick={() => deleteRole(role)}><Icon name="trash" size={12}/> Delete</button>
            </>
          )}
        </div>
        <div style={{ padding: 18 }}>
          {editing ? (
            <div style={{ display: "grid", gap: 14 }}>
              <div style={SEC_COMPACT_FIELD_GRID}>
                <SecField label="Role label"><input className="field-input" value={role.label} onChange={e => setDraft({ ...role, label: e.target.value, id: role.id || secSlug(e.target.value) })}/></SecField>
                <SecField label="Role id" hint="Stored as auth.Group name in this console model.">
                  <input className="field-input t-mono" value={role.id} onChange={e => setDraft({ ...role, id: secSlug(e.target.value) })}/>
                </SecField>
                <SecField label="Category">
                  <select className="field-select" value={role.category} onChange={e => setDraft({ ...role, category: e.target.value })}>
                    {ROLE_CATEGORIES.map(cat => <option key={cat} value={cat}>{cat}</option>)}
                  </select>
                </SecField>
                <SecField label="Admin console access">
                  <select className="field-select" value={role.adminConsole ? "true" : "false"} onChange={e => setDraft({ ...role, adminConsole: e.target.value === "true" })}>
                    <option value="false">no</option>
                    <option value="true">yes</option>
                  </select>
                </SecField>
              </div>
              <SecField label="Description">
                <textarea className="field-textarea" rows={3} value={role.desc} onChange={e => setDraft({ ...role, desc: e.target.value })}/>
              </SecField>
              <div>
                <div className="row" style={{ marginBottom: 8 }}>
                  <strong className="t-bodysm">Screen permissions</strong>
                  <div style={{ flex: 1 }}/>
                  <span className="t-cap">{role.screens.length} selected</span>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))", gap: 8 }}>
                  {PERMISSION_SCREENS.map(screen => {
                    const checked = role.screens.includes(screen);
                    return (
                      <label key={screen} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 10px", border: "1px solid var(--neutral-200)", borderRadius: 4, background: checked ? "var(--accent-data-bg)" : "var(--neutral-0)", cursor: "pointer" }}>
                        <input type="checkbox" checked={checked} onChange={() => toggleRoleScreen(screen)}/>
                        <span className="t-mono t-cap">{screen}</span>
                      </label>
                    );
                  })}
                </div>
              </div>
            </div>
          ) : (
            <>
              <SecDetailRow label="Category"><Chip size="sm" tone={ROLE_TONE[role.category]}>{role.category}</Chip></SecDetailRow>
              <SecDetailRow label="Assigned users"><span className="t-num">{assignedUsers.length.toLocaleString()}</span></SecDetailRow>
              <SecDetailRow label="Description">{role.desc}</SecDetailRow>
              <SecDetailRow label="Admin console">{role.adminConsole ? <Chip size="sm" tone="data"><Icon name="check" size={10}/> yes</Chip> : <span className="muted">no</span>}</SecDetailRow>
              <div className="mt-4">
                <strong className="t-bodysm">Screen scope</strong>
                <div className="row-wrap mt-2">{role.screens.map(screen => <Chip key={screen} size="sm">{screen}</Chip>)}</div>
              </div>
              <div className="mt-4">
                <strong className="t-bodysm">Assigned users</strong>
                <table className="tbl mt-2" style={{ boxShadow: "none" }}>
                  <thead><tr><th>User</th><th>Status</th><th>Scopes</th></tr></thead>
                  <tbody>
                    {assignedUsers.slice(0, 8).map(user => (
                      <tr key={user.id}>
                        <td>
                          <div style={{ fontWeight: 600 }}>{user.name}</div>
                          <div className="t-cap t-mono">{user.username}</div>
                        </td>
                        <td><Chip size="sm" tone={user.status === "active" ? "data" : "quality"}>{user.status}</Chip></td>
                        <td className="t-cap">{user.scopes.map(s => `${s.level}:${s.code || "*"}`).join(", ")}</td>
                      </tr>
                    ))}
                    {assignedUsers.length === 0 && <tr><td colSpan="3" className="muted t-cap">No users assigned.</td></tr>}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      </div>
    );
  };

  const exportUsers = () => {
    const rows = usersState.map(user => [
      user.username,
      user.name,
      user.email,
      user.status,
      user.groups.map(g => rolesState.find(r => r.id === g)?.label || g).join("; "),
      user.scopes.map(s => `${s.level}:${s.code || "*"}`).join("; "),
      user.mfa ? "yes" : "no",
      user.lastLogin,
    ]);
    secDownloadCsv("security-users-roles-scopes.csv", [
      ["username", "name", "email", "status", "roles", "scopes", "mfa", "last_login"],
      ...rows,
    ]);
    setToast(`Exported ${rows.length} user row(s).`);
  };

  return (
    <div className="page">
      <PageHeader
        eyebrow="ADMIN - SECURITY - roles & scopes"
        title="Roles & scopes"
        sub="Who can see what. ROLE controls which screens; SCOPE controls which records within a screen."
        right={<>
          <button className="btn" onClick={exportUsers}><Icon name="download" size={14}/> Export users</button>
          <button className="btn" onClick={startCreateRole}><Icon name="plus" size={14}/> Add role</button>
          <button className="btn btn-primary" onClick={startCreateUser}><Icon name="plus" size={14}/> Add user</button>
        </>}
      />

      {toast && (
        <div className="tint-update mb-3" style={{ padding: 10, borderRadius: 4, display: "flex", alignItems: "center", gap: 8 }}>
          <Icon name={toast.includes("required") || toast.includes("exists") ? "xCircle" : "check"} size={13}/>
          <span className="t-bodysm">{toast}</span>
        </div>
      )}

      <div className="grid grid-4">
        <KPI title="Active users" value={activeUsers} foot={`${totalUsers - activeUsers} suspended`}/>
        <KPI title="Admin Console access" value={adminUsers} foot="Users in admin-enabled roles"/>
        <KPI title="National wildcard scope" value={nationalScope} foot="See every household"/>
        <KPI title="MFA not enrolled" value={noMfa} foot="Will be force-enrolled at next login" trend="down" trendValue="-3 this wk"/>
      </div>

      <div role="tablist" style={{ display: "flex", borderBottom: "1px solid var(--neutral-300)", marginTop: 24, flexWrap: "wrap" }}>
        {[
          { id: "users", label: `Users (${totalUsers})` },
          { id: "roles", label: `Roles (${rolesState.length})` },
          { id: "matrix", label: "Permission matrix" },
        ].map(item => {
          const active = item.id === tab;
          return (
            <button key={item.id} onClick={() => { setTab(item.id); cancelEdit(); }} style={{
              padding: "10px 16px", border: 0, background: "transparent", cursor: "pointer",
              borderBottom: active ? "2px solid var(--primary-900)" : "2px solid transparent",
              marginBottom: -1, color: active ? "var(--primary-900)" : "var(--neutral-700)",
              fontWeight: active ? 600 : 500, fontSize: 13.5,
            }}>{item.label}</button>
          );
        })}
      </div>

      {tab === "users" && (
        <>
          <div className="card mt-4" style={{ padding: "14px 16px" }}>
            <div className="row gap-3" style={{ flexWrap: "wrap" }}>
              <div className="search" style={{ maxWidth: 320, height: 34, background: "var(--neutral-0)" }}>
                <Icon name="search" size={16} color="var(--neutral-500)"/>
                <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search name, username, email..."/>
              </div>
              <select className="field-select" style={{ height: 34, width: "auto", minWidth: 180 }} value={roleFilter} onChange={e => setRoleFilter(e.target.value)}>
                <option value="">Any role</option>
                {rolesState.map(role => <option key={role.id} value={role.id}>{role.label}</option>)}
              </select>
              <select className="field-select" style={{ height: 34, width: "auto", minWidth: 140 }} value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
                <option value="">Any status</option>
                <option value="active">Active</option>
                <option value="suspended">Suspended</option>
              </select>
              <div style={{ flex: 1 }}/>
              <span className="t-cap">{users.length} of {totalUsers}</span>
            </div>
          </div>

          <div className="mt-4" style={SEC_MASTER_DETAIL_STYLE}>
            <div className="card" style={{ overflowX: "auto" }}>
              <table className="tbl">
                <thead>
                  <tr><th>User</th><th>Roles</th><th>Primary scope</th><th>Status</th><th className="col-actions"></th></tr>
                </thead>
                <tbody>
                  {users.map(user => {
                    const active = selectedUserId === user.id && mode !== "createUser";
                    const firstScope = user.scopes[0];
                    const extraScopes = Math.max(0, user.scopes.length - 1);
                    return (
                      <tr key={user.id} onClick={() => { setSelectedUserId(user.id); setMode("view"); setDraft(null); }} style={{ cursor: "pointer", background: active ? "var(--neutral-50)" : "transparent" }}>
                        <td>
                          <div className="row gap-3">
                            <div style={{ width: 30, height: 30, borderRadius: "50%", background: "var(--primary-100)", color: "var(--primary-900)", display: "grid", placeItems: "center", fontSize: 11, fontWeight: 600 }}>{secInitials(user.name)}</div>
                            <div>
                              <div style={{ fontWeight: 500 }}>{user.name}</div>
                              <div className="t-cap t-mono" style={{ fontSize: 11 }}>{user.username}</div>
                            </div>
                          </div>
                        </td>
                        <td><div className="row-wrap" style={{ gap: 4 }}>{user.groups.map(g => <Chip key={g} size="sm" tone={roleTone(g)}>{secRoleLabel(rolesState, g)}</Chip>)}</div></td>
                        <td>
                          {firstScope
                            ? <div className="row gap-2">
                                <Chip size="sm" tone={firstScope.level === "national" ? "danger" : firstScope.level === "partner" ? "programme" : "data"}>{secScopeLabel(firstScope)}</Chip>
                                {extraScopes > 0 && <span className="t-cap">+{extraScopes}</span>}
                              </div>
                            : <span className="muted t-cap">No scope</span>}
                        </td>
                        <td>{user.status === "active" ? <Chip size="sm" tone="data">Active</Chip> : <Chip size="sm" tone="quality">Suspended</Chip>}</td>
                        <td className="col-actions"><Icon name="chevronRight" size={16} color="var(--neutral-500)"/></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {renderUserDetail()}
          </div>
        </>
      )}

      {tab === "roles" && (
        <div className="mt-4" style={SEC_MASTER_DETAIL_STYLE}>
          <div className="card" style={{ overflowX: "auto" }}>
            <table className="tbl">
              <thead><tr><th>Role</th><th>Category</th><th>Users</th><th>Permissions</th><th>Admin</th><th className="col-actions"></th></tr></thead>
              <tbody>
                {rolesState.map(role => {
                  const active = selectedRoleId === role.id && mode !== "createRole";
                  const extraScreens = Math.max(0, role.screens.length - 2);
                  return (
                    <tr key={role.id} onClick={() => { setSelectedRoleId(role.id); setMode("view"); setDraft(null); }} style={{ cursor: "pointer", background: active ? "var(--neutral-50)" : "transparent" }}>
                      <td><div style={{ fontWeight: 600 }}>{role.label}</div><div className="t-cap t-mono">{role.id}</div></td>
                      <td><Chip size="sm" tone={ROLE_TONE[role.category]}>{role.category}</Chip></td>
                      <td className="t-num">{(roleCounts[role.id] || 0).toLocaleString()}</td>
                      <td>
                        <div className="row-wrap" style={{ gap: 4 }}>
                          {role.screens.slice(0, 2).map(screen => <Chip key={screen} size="sm">{screen}</Chip>)}
                          {extraScreens > 0 && <span className="t-cap">+{extraScreens}</span>}
                        </div>
                      </td>
                      <td>{role.adminConsole ? <Chip size="sm" tone="data"><Icon name="check" size={10}/> yes</Chip> : <span className="muted t-cap">-</span>}</td>
                      <td className="col-actions"><Icon name="chevronRight" size={16} color="var(--neutral-500)"/></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {renderRoleDetail()}
        </div>
      )}

      {tab === "matrix" && (
        <div className="card mt-4" style={{ padding: 20 }}>
          <div className="row" style={{ marginBottom: 12 }}>
            <div>
              <strong className="t-bodysm">Permission matrix - roles x screens</strong>
              <div className="t-cap mt-1">A check means users in that role can open that screen subject to their data scope.</div>
            </div>
            <div style={{ flex: 1 }}/>
            <button className="btn btn-sm" onClick={startCreateRole}><Icon name="plus" size={12}/> Add role</button>
          </div>
          <div style={{ overflowX: "auto" }}>
            <table className="tbl" style={{ boxShadow: "none", minWidth: 860 }}>
              <thead>
                <tr>
                  <th>Screen</th>
                  {rolesState.map(role => <th key={role.id} style={{ textAlign: "center", minWidth: 110 }}><div className="t-cap">{role.label}</div></th>)}
                </tr>
              </thead>
              <tbody>
                {PERMISSION_SCREENS.map(screen => (
                  <tr key={screen}>
                    <td className="t-mono t-bodysm" style={{ fontWeight: 500 }}>{screen}</td>
                    {rolesState.map(role => {
                      const ok = role.screens.includes(screen) || role.screens.includes("admin.*") && screen.startsWith("admin.") || role.screens.includes("console.*") && screen.startsWith("console.");
                      return (
                        <td key={role.id} style={{ textAlign: "center" }}>
                          {ok ? <Icon name="check" size={14} color="var(--accent-data)"/> : <span className="muted">-</span>}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="tint-update mt-5" style={{ padding: 14, borderRadius: 6, borderLeft: "3px solid var(--accent-update)" }}>
        <div className="row gap-2" style={{ marginBottom: 4 }}>
          <Icon name="shield" size={13} color="var(--accent-update)"/>
          <strong className="t-bodysm">ABAC scope</strong>
        </div>
        <div className="t-bodysm muted">
          Scope is enforced at list-query time. A user without national wildcard sees only rows whose geographic hierarchy
          intersects one of their active OperatorScope entries. PARTNER is non-geographic and gates DataRequests under DSAs
          for the named partner.
        </div>
      </div>
    </div>
  );
};

Object.assign(window, { AdminSecurityRolesScreen });
