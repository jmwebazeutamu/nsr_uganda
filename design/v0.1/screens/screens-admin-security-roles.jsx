/* global React, Icon, Chip, PageHeader, KPI */
// NSR MIS - Admin - Security - Roles & scopes
// =========================================================
// ROLE controls what a user may do.   SCOPE controls which records
// they may do it to.
//
// Everything on this screen is read from the registry:
//
//   /api/v1/security/users/           accounts, groups, status, last login
//   /api/v1/security/operator-scopes/ the ABAC scope rows per account
//   /api/v1/security/roles/           the ADR-0028 role catalogue
//
// It used to read from `SEC_USERS` and `SEC_ROLES` — ten invented
// operator accounts with government e-mail addresses, and nine roles
// that were not the ones the system actually has. There was no user
// fetch at all. On the screen where an administrator checks who holds
// access, that is the most consequential place in the console for
// fabricated data to sit, and it survived two cleanup passes because
// each one keyed on the single fixture named in the previous finding.
//
// Read-only, deliberately:
//
//   * Roles are defined in code (`apps/security/roles.py`, ADR-0028 D1)
//     precisely so the Django Groups, the Keycloak realm and the TOR
//     cannot drift apart. A role editor here would reintroduce the
//     drift that ADR removed. The catalogue is shown, not edited.
//   * Scope grants and revocations already have a working surface with
//     an audit trail — the Operator scopes tab (US-S11-028). This
//     screen links to it rather than offering a second one.
//   * The previous Save / Delete buttons wrote to React state and
//     nothing else: "Akello P. deleted from this workspace" left the
//     account untouched and told the administrator otherwise.
//
// Four fields the design mock carried are gone because the system has
// no such data: MFA state and method, phone number, last password
// reset, and sessions-in-24h. There is no MFA implementation anywhere
// in this codebase. A security screen reporting an MFA posture that
// nothing enforces is worse than one that stays silent about it.

const { useState: useStateSEC, useMemo: useMemoSEC, useEffect: useEffectSEC } = React;

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

const SCOPE_LEVEL_LABEL = {
  national: "National (wildcard)", region: "Region", sub_region: "Sub-region", district: "District",
  sub_county: "Sub-county", parish: "Parish", village: "Village", partner: "Partner",
};

// The eight TOR permissions (ADR-0028). Labels only — the catalogue
// endpoint is authoritative for which role holds which.
const PERMISSION_LABEL = {
  data_view: "View", data_entry: "Entry", data_modify: "Modify", data_delete: "Delete",
  data_approve: "Approve", data_export: "Export", data_download: "Download", data_upload: "Upload",
};
const PERMISSION_ORDER = [
  "data_view", "data_entry", "data_modify", "data_delete",
  "data_approve", "data_export", "data_download", "data_upload",
];

// Tone tracks reach: the wider the default scope, the louder the chip.
const secRoleTone = (role) =>
  role.external ? "programme" : role.default_scope === "national" ? "danger" : "data";

const secInitials = (name) => String(name || "?").split(" ").map(w => w[0]).slice(0, 2).join("").toUpperCase();

// EAT (UTC+3) for display; the wire is UTC. Never invents a value —
// an account that has never signed in reads "Never", not a date.
const secDateTime = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("en-GB", {
    timeZone: "Africa/Kampala", day: "2-digit", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit", hour12: false,
  });
};
const secDate = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("en-GB", {
    timeZone: "Africa/Kampala", day: "2-digit", month: "short", year: "numeric",
  });
};

const secJson = (url) =>
  fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } })
    .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
    .then(d => Array.isArray(d) ? d : (d.results || []));

// Scope rows arrive flat, one per grant. Index them by user id so each
// account carries its own; an account with no grants gets [], which the
// UI reports as "No scope" rather than leaving the column blank.
const secScopesByUser = (scopeRows) => {
  const byUser = {};
  (scopeRows || []).forEach(row => {
    (byUser[row.user] = byUser[row.user] || []).push(row);
  });
  return byUser;
};

const secScopeLabelShort = (scope) =>
  scope.scope_level === "national" ? "national" : `${scope.scope_level}:${scope.scope_code || "*"}`;

const SecDetailRow = ({ label, children }) => (
  <div style={{ display: "grid", gridTemplateColumns: "128px 1fr", gap: 12, padding: "8px 0", borderBottom: "1px solid var(--neutral-100)" }}>
    <div className="t-cap">{label}</div>
    <div className="t-bodysm">{children || <span className="muted">-</span>}</div>
  </div>
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

const AdminSecurityRolesScreen = () => {
  // null = still loading. [] = loaded and genuinely empty. The
  // distinction is the whole point: the old screen could not tell an
  // empty registry from a failed request, because it never asked.
  const [users, setUsers] = useStateSEC(null);
  const [scopes, setScopes] = useStateSEC(null);
  const [roles, setRoles] = useStateSEC(null);
  const [loadErrors, setLoadErrors] = useStateSEC([]);

  const [tab, setTab] = useStateSEC("users");
  const [q, setQ] = useStateSEC("");
  const [roleFilter, setRoleFilter] = useStateSEC("");
  const [statusFilter, setStatusFilter] = useStateSEC("");
  const [selectedUserId, setSelectedUserId] = useStateSEC(null);
  const [selectedRoleCode, setSelectedRoleCode] = useStateSEC(null);
  const [toast, setToast] = useStateSEC("");

  useEffectSEC(() => {
    let cancelled = false;
    const fail = (source, err) => {
      if (cancelled) return;
      setLoadErrors(prev => [...prev, `${source}: ${err.message || String(err)}`]);
    };
    // Each source is reported separately. A partial failure — roles up,
    // users down — must not render as a complete picture.
    secJson("/api/v1/security/users/?page_size=500")
      .then(d => { if (!cancelled) setUsers(d); })
      .catch(err => { fail("users", err); if (!cancelled) setUsers([]); });
    secJson("/api/v1/security/operator-scopes/?page_size=1000")
      .then(d => { if (!cancelled) setScopes(d); })
      .catch(err => { fail("operator scopes", err); if (!cancelled) setScopes([]); });
    secJson("/api/v1/security/roles/")
      .then(d => { if (!cancelled) setRoles(d); })
      .catch(err => { fail("role catalogue", err); if (!cancelled) setRoles([]); });
    return () => { cancelled = true; };
  }, []);

  const loading = users === null || scopes === null || roles === null;
  const userList = users || [];
  const roleList = roles || [];
  const scopesByUser = useMemoSEC(() => secScopesByUser(scopes), [scopes]);

  const roleByCode = useMemoSEC(() => {
    const map = {};
    roleList.forEach(r => { map[r.code] = r; });
    return map;
  }, [roleList]);

  const secRoleLabel = (code) => roleByCode[code]?.label || code;
  const roleTone = (code) => roleByCode[code] ? secRoleTone(roleByCode[code]) : "neutral";

  const userScopes = (user) => scopesByUser[user.id] || [];
  const activeScopes = (user) => userScopes(user).filter(s => s.active !== false);

  const filteredUsers = useMemoSEC(() => userList.filter(u => {
    const query = q.trim().toLowerCase();
    if (query && !(`${u.display_name} ${u.username} ${u.email || ""}`.toLowerCase().includes(query))) return false;
    if (roleFilter && !(u.groups || []).includes(roleFilter)) return false;
    if (statusFilter === "active" && !u.is_active) return false;
    if (statusFilter === "disabled" && u.is_active) return false;
    return true;
  }), [userList, q, roleFilter, statusFilter]);

  const selectedUser = userList.find(u => u.id === selectedUserId) || null;
  const selectedRole = roleList.find(r => r.code === selectedRoleCode) || null;

  const totalUsers = userList.length;
  const activeUsers = userList.filter(u => u.is_active).length;
  const nationalScope = userList.filter(u => activeScopes(u).some(s => s.scope_level === "national")).length;
  // A superuser bypasses scope checks, so "no scope" is only a finding
  // for everyone else. Counting them here would report a problem that
  // is not one.
  const noScope = userList.filter(u => !u.is_superuser && activeScopes(u).length === 0).length;

  const exportUsers = () => {
    const rows = userList.map(user => [
      user.username,
      user.display_name,
      user.email || "",
      user.is_active ? "active" : "disabled",
      (user.groups || []).map(g => secRoleLabel(g)).join("; "),
      userScopes(user).map(s => `${secScopeLabelShort(s)}${s.active === false ? " (inactive)" : ""}`).join("; "),
      user.last_login ? secDateTime(user.last_login) : "Never",
      secDate(user.date_joined),
    ]);
    secDownloadCsv("security-users-roles-scopes.csv", [
      ["username", "display_name", "email", "status", "roles", "scopes", "last_login_eat", "joined_eat"],
      ...rows,
    ]);
    setToast(`Exported ${rows.length} account${rows.length === 1 ? "" : "s"}.`);
  };

  const renderUserDetail = () => {
    const u = selectedUser;
    if (!u) {
      return (
        <div className="card" style={{ ...SEC_DETAIL_CARD_STYLE, padding: 24 }}>
          <div className="muted t-bodysm">Select an account to see its roles and scopes.</div>
        </div>
      );
    }
    const rows = userScopes(u);
    return (
      <div className="card" style={SEC_DETAIL_CARD_STYLE}>
        <div style={{ padding: "16px 18px", borderBottom: "1px solid var(--neutral-200)", display: "flex", gap: 12, alignItems: "center" }}>
          <div style={{ width: 42, height: 42, borderRadius: "50%", background: "var(--primary-100)", color: "var(--primary-900)", display: "grid", placeItems: "center", fontSize: 13, fontWeight: 700 }}>
            {secInitials(u.display_name)}
          </div>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontWeight: 700 }}>{u.display_name}</div>
            <div className="t-cap t-mono">{u.username}</div>
          </div>
        </div>

        <div style={{ padding: 18 }}>
          <SecDetailRow label="Email">{u.email}</SecDetailRow>
          <SecDetailRow label="Status">
            {u.is_active ? <Chip size="sm" tone="data">active</Chip> : <Chip size="sm" tone="quality">disabled</Chip>}
          </SecDetailRow>
          {u.is_superuser && (
            <SecDetailRow label="Superuser">
              <Chip size="sm" tone="danger">bypasses scope checks</Chip>
            </SecDetailRow>
          )}
          <SecDetailRow label="Last login">{u.last_login ? secDateTime(u.last_login) : <span className="muted">Never</span>}</SecDetailRow>
          <SecDetailRow label="Joined">{secDate(u.date_joined)}</SecDetailRow>

          <div className="mt-4">
            <strong className="t-bodysm">Roles</strong>
            <div className="row-wrap mt-2">
              {(u.groups || []).length
                ? u.groups.map(g => <Chip key={g} size="sm" tone={roleTone(g)}>{secRoleLabel(g)}</Chip>)
                : <span className="muted t-cap">No roles assigned</span>}
            </div>
            {(u.groups || []).some(g => !roleByCode[g]) && (
              <div className="t-cap muted mt-2">
                Groups shown without a catalogue entry exist in the database but
                not in <span className="t-mono">roles.py</span>. `sync_roles`
                leaves such groups alone rather than deleting access.
              </div>
            )}
          </div>

          <div className="mt-4">
            <strong className="t-bodysm">Scopes</strong>
            {rows.length === 0 ? (
              <div className="t-cap muted mt-2">
                {u.is_superuser
                  ? "None granted — a superuser sees every record regardless."
                  : "None granted. This account sees no household records."}
              </div>
            ) : (
              <table className="tbl mt-2" style={{ boxShadow: "none" }}>
                <thead><tr><th>Level</th><th>Scope</th><th>Status</th><th>Granted</th></tr></thead>
                <tbody>
                  {rows.map(scope => (
                    <tr key={scope.id}>
                      <td>
                        <Chip size="sm" tone={scope.scope_level === "national" ? "danger" : scope.scope_level === "partner" ? "programme" : "data"}>
                          {SCOPE_LEVEL_LABEL[scope.scope_level] || scope.scope_level}
                        </Chip>
                      </td>
                      <td>
                        <div className="t-mono">{scope.scope_code || "*"}</div>
                        {scope.scope_label && <div className="t-cap">{scope.scope_label}</div>}
                      </td>
                      <td>{scope.active === false ? <Chip size="sm" tone="quality">inactive</Chip> : <Chip size="sm" tone="data">active</Chip>}</td>
                      <td className="t-cap">
                        {secDate(scope.granted_at)}
                        {scope.granted_by && <div className="muted">by {scope.granted_by}</div>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    );
  };

  const renderRoleDetail = () => {
    const role = selectedRole;
    if (!role) {
      return (
        <div className="card" style={{ ...SEC_DETAIL_CARD_STYLE, padding: 24 }}>
          <div className="muted t-bodysm">Select a role to see its permissions and members.</div>
        </div>
      );
    }
    const assigned = userList.filter(user => (user.groups || []).includes(role.code));
    return (
      <div className="card" style={SEC_DETAIL_CARD_STYLE}>
        <div style={{ padding: "16px 18px", borderBottom: "1px solid var(--neutral-200)" }}>
          <div style={{ fontWeight: 700 }}>{role.label}</div>
          <div className="t-cap t-mono">{role.code}</div>
        </div>
        <div style={{ padding: 18 }}>
          <SecDetailRow label="Default scope">
            <Chip size="sm" tone={secRoleTone(role)}>{SCOPE_LEVEL_LABEL[role.default_scope] || role.default_scope}</Chip>
          </SecDetailRow>
          <SecDetailRow label="Members"><span className="t-num">{role.member_count.toLocaleString()}</span></SecDetailRow>
          <SecDetailRow label="In the TOR 18">{role.in_tor ? "yes" : <span className="muted">no - operational role</span>}</SecDetailRow>
          <SecDetailRow label="External">{role.external ? <Chip size="sm" tone="programme">partner-affiliated</Chip> : <span className="muted">no</span>}</SecDetailRow>
          <SecDetailRow label="Realm role">{role.adr0006 ? <span className="t-mono">{role.adr0006}</span> : <span className="muted">not in ADR-0006</span>}</SecDetailRow>
          {role.notes && <SecDetailRow label="Notes">{role.notes}</SecDetailRow>}

          <div className="mt-4">
            <strong className="t-bodysm">Permissions</strong>
            <div className="row-wrap mt-2">
              {role.permissions.length
                ? role.permissions.map(p => <Chip key={p} size="sm" tone="data">{PERMISSION_LABEL[p] || p}</Chip>)
                : <span className="muted t-cap">None</span>}
            </div>
          </div>

          <div className="mt-4">
            <strong className="t-bodysm">Members ({assigned.length})</strong>
            {assigned.length === 0 ? (
              <div className="t-cap muted mt-2">
                {role.member_count > 0
                  ? `${role.member_count} in the group; none in the loaded account window.`
                  : "No account holds this role."}
              </div>
            ) : (
              <table className="tbl mt-2" style={{ boxShadow: "none" }}>
                <thead><tr><th>User</th><th>Status</th><th>Scopes</th></tr></thead>
                <tbody>
                  {assigned.slice(0, 8).map(user => (
                    <tr key={user.id}>
                      <td>
                        <div style={{ fontWeight: 600 }}>{user.display_name}</div>
                        <div className="t-cap t-mono">{user.username}</div>
                      </td>
                      <td>{user.is_active ? <Chip size="sm" tone="data">active</Chip> : <Chip size="sm" tone="quality">disabled</Chip>}</td>
                      <td className="t-cap">
                        {activeScopes(user).map(s => secScopeLabelShort(s)).join(", ") || <span className="muted">none</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {assigned.length > 8 && <div className="t-cap muted mt-2">+{assigned.length - 8} more</div>}
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="page">
      <PageHeader
        eyebrow="ADMIN - SECURITY - roles & scopes"
        title="Roles & scopes"
        sub="Who can see what. ROLE controls what a user may do; SCOPE controls which records they may do it to."
        right={<>
          <button className="btn" onClick={exportUsers} disabled={!userList.length}>
            <Icon name="download" size={14}/> Export accounts
          </button>
        </>}
      />

      {/* State is always explicit, per source. The version this replaced
          rendered ten invented accounts whether or not anything loaded. */}
      {loadErrors.length > 0 && (
        <div className="tint-danger mb-3" style={{ padding: 10, borderRadius: 4 }}>
          <strong className="t-bodysm">Could not load {loadErrors.length === 1 ? "one source" : `${loadErrors.length} sources`}</strong>
          <div className="t-cap mt-1">
            {loadErrors.join(" · ")} · nothing is shown for those rather than sample data.
          </div>
        </div>
      )}
      {loading && loadErrors.length === 0 && (
        <div className="tint-data mb-3" style={{ padding: 10, borderRadius: 4 }}>
          <span className="t-bodysm">Loading accounts, scopes and the role catalogue…</span>
        </div>
      )}
      {!loading && totalUsers === 0 && loadErrors.length === 0 && (
        <div className="tint-data mb-3" style={{ padding: 10, borderRadius: 4 }}>
          <span className="t-bodysm">No operator accounts exist yet.</span>
        </div>
      )}

      {toast && (
        <div className="tint-update mb-3" style={{ padding: 10, borderRadius: 4, display: "flex", alignItems: "center", gap: 8 }}>
          <Icon name="check" size={13}/>
          <span className="t-bodysm">{toast}</span>
        </div>
      )}

      <div className="grid grid-4">
        <KPI title="Accounts" value={loading ? "—" : String(totalUsers)} foot={loading ? "loading" : `${totalUsers - activeUsers} disabled`}/>
        <KPI title="Active" value={loading ? "—" : String(activeUsers)} foot="Can sign in"/>
        <KPI title="National wildcard scope" value={loading ? "—" : String(nationalScope)} foot="See every household"/>
        <KPI title="No scope granted" value={loading ? "—" : String(noScope)} foot="Non-superuser accounts that see no records"/>
      </div>

      <div role="tablist" style={{ display: "flex", borderBottom: "1px solid var(--neutral-300)", marginTop: 24, flexWrap: "wrap" }}>
        {[
          { id: "users", label: `Accounts (${totalUsers})` },
          { id: "roles", label: `Roles (${roleList.length})` },
          { id: "matrix", label: "Permission matrix" },
        ].map(item => {
          const active = item.id === tab;
          return (
            <button key={item.id} onClick={() => setTab(item.id)} style={{
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
                {roleList.map(role => <option key={role.code} value={role.code}>{role.label}</option>)}
              </select>
              <select className="field-select" style={{ height: 34, width: "auto", minWidth: 140 }} value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
                <option value="">Any status</option>
                <option value="active">Active</option>
                <option value="disabled">Disabled</option>
              </select>
              <div style={{ flex: 1 }}/>
              <span className="t-cap">{filteredUsers.length} of {totalUsers}</span>
            </div>
          </div>

          <div className="mt-4" style={SEC_MASTER_DETAIL_STYLE}>
            <div className="card" style={{ overflowX: "auto" }}>
              <table className="tbl">
                <thead>
                  <tr><th>Account</th><th>Roles</th><th>Primary scope</th><th>Status</th><th className="col-actions"></th></tr>
                </thead>
                <tbody>
                  {filteredUsers.map(user => {
                    const active = selectedUserId === user.id;
                    const rows = activeScopes(user);
                    const firstScope = rows[0];
                    const extraScopes = Math.max(0, rows.length - 1);
                    return (
                      <tr key={user.id} onClick={() => setSelectedUserId(user.id)} style={{ cursor: "pointer", background: active ? "var(--neutral-50)" : "transparent" }}>
                        <td>
                          <div className="row gap-3">
                            <div style={{ width: 30, height: 30, borderRadius: "50%", background: "var(--primary-100)", color: "var(--primary-900)", display: "grid", placeItems: "center", fontSize: 11, fontWeight: 600 }}>{secInitials(user.display_name)}</div>
                            <div>
                              <div style={{ fontWeight: 500 }}>{user.display_name}</div>
                              <div className="t-cap t-mono" style={{ fontSize: 11 }}>{user.username}</div>
                            </div>
                          </div>
                        </td>
                        <td>
                          <div className="row-wrap" style={{ gap: 4 }}>
                            {(user.groups || []).length
                              ? user.groups.map(g => <Chip key={g} size="sm" tone={roleTone(g)}>{secRoleLabel(g)}</Chip>)
                              : <span className="muted t-cap">none</span>}
                          </div>
                        </td>
                        <td>
                          {firstScope
                            ? <div className="row gap-2">
                                <Chip size="sm" tone={firstScope.scope_level === "national" ? "danger" : firstScope.scope_level === "partner" ? "programme" : "data"}>{secScopeLabelShort(firstScope)}</Chip>
                                {extraScopes > 0 && <span className="t-cap">+{extraScopes}</span>}
                              </div>
                            : <span className="muted t-cap">{user.is_superuser ? "superuser" : "No scope"}</span>}
                        </td>
                        <td>{user.is_active ? <Chip size="sm" tone="data">Active</Chip> : <Chip size="sm" tone="quality">Disabled</Chip>}</td>
                        <td className="col-actions"><Icon name="chevronRight" size={16} color="var(--neutral-500)"/></td>
                      </tr>
                    );
                  })}
                  {!loading && filteredUsers.length === 0 && (
                    <tr><td colSpan="5" className="muted t-cap" style={{ padding: 14 }}>
                      {totalUsers === 0 ? "No operator accounts exist yet." : "No account matches these filters."}
                    </td></tr>
                  )}
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
              <thead><tr><th>Role</th><th>Default scope</th><th>Members</th><th>Permissions</th><th>Source</th><th className="col-actions"></th></tr></thead>
              <tbody>
                {roleList.map(role => {
                  const active = selectedRoleCode === role.code;
                  const extraPerms = Math.max(0, role.permissions.length - 3);
                  return (
                    <tr key={role.code} onClick={() => setSelectedRoleCode(role.code)} style={{ cursor: "pointer", background: active ? "var(--neutral-50)" : "transparent" }}>
                      <td><div style={{ fontWeight: 600 }}>{role.label}</div><div className="t-cap t-mono">{role.code}</div></td>
                      <td><Chip size="sm" tone={secRoleTone(role)}>{SCOPE_LEVEL_LABEL[role.default_scope] || role.default_scope}</Chip></td>
                      <td className="t-num">{role.member_count.toLocaleString()}</td>
                      <td>
                        <div className="row-wrap" style={{ gap: 4 }}>
                          {role.permissions.slice(0, 3).map(p => <Chip key={p} size="sm">{PERMISSION_LABEL[p] || p}</Chip>)}
                          {extraPerms > 0 && <span className="t-cap">+{extraPerms}</span>}
                        </div>
                      </td>
                      <td className="t-cap">{role.in_tor ? "TOR" : "operational"}{role.external ? " · external" : ""}</td>
                      <td className="col-actions"><Icon name="chevronRight" size={16} color="var(--neutral-500)"/></td>
                    </tr>
                  );
                })}
                {!loading && roleList.length === 0 && (
                  <tr><td colSpan="6" className="muted t-cap" style={{ padding: 14 }}>The role catalogue did not load.</td></tr>
                )}
              </tbody>
            </table>
          </div>
          {renderRoleDetail()}
        </div>
      )}

      {tab === "matrix" && (
        <div className="card mt-4" style={{ padding: 20 }}>
          <div style={{ marginBottom: 12 }}>
            <strong className="t-bodysm">Permission matrix - roles x the eight TOR permissions</strong>
            <div className="t-cap mt-1">
              Read from the catalogue in <span className="t-mono">apps/security/roles.py</span> (ADR-0028).
              A check means the role grants that action; which <em>records</em> it applies to is the scope, not the role.
            </div>
          </div>
          <div style={{ overflowX: "auto" }}>
            <table className="tbl" style={{ boxShadow: "none", minWidth: 860 }}>
              <thead>
                <tr>
                  <th>Role</th>
                  {PERMISSION_ORDER.map(p => <th key={p} style={{ textAlign: "center", minWidth: 92 }}><div className="t-cap">{PERMISSION_LABEL[p]}</div></th>)}
                  <th style={{ textAlign: "center" }}><div className="t-cap">Members</div></th>
                </tr>
              </thead>
              <tbody>
                {roleList.map(role => (
                  <tr key={role.code}>
                    <td>
                      <div className="t-bodysm" style={{ fontWeight: 600 }}>{role.label}</div>
                      <div className="t-cap t-mono">{role.code}</div>
                    </td>
                    {PERMISSION_ORDER.map(p => (
                      <td key={p} style={{ textAlign: "center" }}>
                        {role.permissions.includes(p)
                          ? <Icon name="check" size={14} color="var(--accent-data)"/>
                          : <span className="muted">-</span>}
                      </td>
                    ))}
                    <td className="t-num" style={{ textAlign: "center" }}>{role.member_count}</td>
                  </tr>
                ))}
                {!loading && roleList.length === 0 && (
                  <tr><td colSpan={PERMISSION_ORDER.length + 2} className="muted t-cap" style={{ padding: 14 }}>The role catalogue did not load.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="tint-update mt-5" style={{ padding: 14, borderRadius: 6, borderLeft: "3px solid var(--accent-update)" }}>
        <div className="row gap-2" style={{ marginBottom: 4 }}>
          <Icon name="shield" size={13} color="var(--accent-update)"/>
          <strong className="t-bodysm">This screen is read-only</strong>
        </div>
        <div className="t-bodysm muted">
          Roles are defined in <span className="t-mono">apps/security/roles.py</span> and materialised into
          Django Groups by <span className="t-mono">manage.py sync_roles</span> — one catalogue, so the realm,
          the groups and the TOR cannot drift apart (ADR-0028). To change what an operator can see, grant or
          revoke a scope in <strong>Operator scopes</strong>, which records the change in the audit chain.
          Scope is enforced at list-query time: an account without the national wildcard sees only rows whose
          geographic hierarchy intersects one of its active scopes. PARTNER is non-geographic and gates
          DataRequests under DSAs for the named partner.
        </div>
      </div>
    </div>
  );
};

Object.assign(window, {
  AdminSecurityRolesScreen,
  // Exported for the unit tests.
  _secScopesByUser: secScopesByUser,
  _secRoleTone: secRoleTone,
  _secScopeLabelShort: secScopeLabelShort,
  _secDateTime: secDateTime,
});
