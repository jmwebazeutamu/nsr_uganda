/* global React, Icon, Chip, PageHeader */
// NSR MIS — Admin — User management
// =========================================================
// The console route for the account lifecycle, so adding a user or
// resetting a password does not require the Django admin. The Django
// admin stays available and unchanged; this is the safer path, not a
// replacement.
//
// Reads and writes /api/v1/security/user-accounts/ — NOT users/, which
// is the scope picker's search endpoint with a different shape.
//
// Gated on nsr_admin alone. The admin console admits five groups; a DPO
// or statistics user opening it will not see this screen, and the API
// refuses them too — the nav entry is a convenience, never the control.
//
// What this screen will not do, and why:
//
//   * It does not define roles. The catalogue is code (roles.py,
//     ADR-0028) and synced into Groups by manage.py sync_roles, so the
//     realm, the groups and the TOR cannot drift. Membership changes
//     here; the catalogue does not.
//   * It does not delete accounts. The audit chain references users by
//     username, so a deleted user leaves the trail pointing at nobody.
//     Deactivate is the equivalent that keeps the history readable.
//   * It does not manage superusers, and does not let an admin change
//     their own roles. Both are refused by the API; the screen greys
//     them out so the refusal is visible before it is attempted.
//   * It does not grant geographic scope. Operator scopes already owns
//     that, with its own audit trail — this links there rather than
//     offering a second surface that could disagree with the first.

const { useState: useStateUM, useEffect: useEffectUM, useMemo: useMemoUM } = React;

const UM_API = "/api/v1/security/user-accounts/";

// Scope grants go to the endpoint that already owns them. A second
// implementation here could disagree with Operator scopes about what a
// grant means, and the two would drift the way every other pair of
// vocabularies in this system has.
const UM_SCOPE_API = "/api/v1/security/operator-scopes/bulk-grant/";

// From ScopeLevel. `national` is the wildcard and takes no codes — the
// API rejects codes alongside it rather than ignoring them.
const UM_SCOPE_LEVELS = [
  { value: "", label: "No scope yet — grant later" },
  { value: "national", label: "National (all records)", codes: false },
  { value: "district", label: "District", codes: true },
  { value: "sub_county", label: "Sub-county", codes: true },
  { value: "parish", label: "Parish", codes: true },
  { value: "partner", label: "Partner (non-geographic)", codes: true },
];

const _umCsrf = () => {
  const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return m ? m[1] : "";
};

const _umPost = (url, body) =>
  fetch(url, {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "Accept": "application/json",
      "X-CSRFToken": _umCsrf(),
    },
    body: JSON.stringify(body),
  }).then(async (r) => {
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    return data;
  });

const _umGet = (url) =>
  fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } })
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))));

/* A reason is required by the API on every change. Asking for it in the
   same dialog as the action keeps the audit entry meaningful instead of
   "updated via console". */
const UmReasonField = ({ value, onChange, placeholder }) => (
  <label style={{ display: "block", marginTop: 12 }}>
    <span className="t-cap" style={{ fontWeight: 600 }}>REASON (RECORDED IN THE AUDIT CHAIN)</span>
    <input className="field-input" style={{ width: "100%", marginTop: 6 }}
           value={value} onChange={(e) => onChange(e.target.value)}
           placeholder={placeholder}/>
  </label>
);

/* Shown once, and never again: the API does not store it in readable
   form and there is no endpoint that will hand it back. */
const UmSecretOnce = ({ label, secret, onDone }) => (
  <div className="card" style={{ padding: 16, borderLeft: "3px solid var(--accent-quality)" }}>
    <strong>{label}</strong>
    <p className="t-bodysm" style={{ color: "var(--neutral-700)" }}>
      Copy it now and give it to the user directly. It is shown once —
      nothing stores it in readable form, so if it is lost the only way
      forward is another reset.
    </p>
    <div className="t-mono" style={{
      fontSize: 18, padding: "10px 14px", marginTop: 8,
      background: "var(--neutral-100)", borderRadius: 6, userSelect: "all",
    }}>{secret}</div>
    <div className="row gap-2" style={{ marginTop: 12 }}>
      <button className="btn" onClick={() => navigator.clipboard?.writeText(secret)}>Copy</button>
      <button className="btn primary" onClick={onDone}>Done</button>
    </div>
  </div>
);

const AdminUsersScreen = ({ onNavigate }) => {
  const [rows, setRows] = useStateUM([]);
  const [roles, setRoles] = useStateUM([]);
  const [query, setQuery] = useStateUM("");
  const [stateFilter, setStateFilter] = useStateUM("");
  const [loading, setLoading] = useStateUM(true);
  const [error, setError] = useStateUM(null);
  const [dialog, setDialog] = useStateUM(null);   // {kind, user}
  const [reason, setReason] = useStateUM("");
  const [secret, setSecret] = useStateUM(null);   // {label, value}
  const [busy, setBusy] = useStateUM(false);
  const [me, setMe] = useStateUM(null);

  const load = () => {
    const params = new URLSearchParams();
    if (query.trim()) params.set("q", query.trim());
    if (stateFilter) params.set("state", stateFilter);
    setLoading(true);
    _umGet(`${UM_API}${params.toString() ? "?" + params : ""}`)
      .then((d) => { setRows(d.results || d); setError(null); })
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false));
  };

  useEffectUM(() => { load(); }, [query, stateFilter]);
  useEffectUM(() => {
    _umGet(`${UM_API}roles/`).then((d) => setRoles(d.roles || [])).catch(() => setRoles([]));
    _umGet("/api/v1/security/users/me/").then(setMe).catch(() => setMe(null));
  }, []);

  const closeDialog = () => { setDialog(null); setReason(""); setBusy(false); };

  const act = (fn) => {
    setBusy(true);
    fn()
      .then(() => { closeDialog(); load(); })
      .catch((e) => { setError(String(e.message || e)); setBusy(false); });
  };

  // An admin cannot change their own roles; the API refuses it. Showing
  // the control and then refusing the click is a worse experience than
  // not offering it.
  const isSelf = (u) => me && (u.username === me.username);

  return (
    <div>
      <PageHeader title="User management" right={
        <button className="btn primary" onClick={() => { setDialog({ kind: "create" }); setReason(""); }}>
          <Icon name="plus" size={14}/> New account
        </button>
      }/>

      <div className="card" style={{ padding: 12, marginBottom: 16, borderLeft: "3px solid var(--accent-quality)" }}>
        <div className="t-bodysm" style={{ color: "var(--neutral-700)" }}>
          <strong>Roles are membership only.</strong> The catalogue is defined in
          {" "}<span className="t-mono">apps/security/roles.py</span> and synced into
          Django groups by <span className="t-mono">manage.py sync_roles</span> (ADR-0028),
          so the realm, the groups and the TOR cannot drift apart. To change which
          records an operator can see, grant a scope in{" "}
          <button className="linklike" onClick={() => onNavigate && onNavigate("admin-operator-scopes")}>
            Operator scopes
          </button>. Accounts are deactivated, never deleted — the audit chain
          refers to users by name.
        </div>
      </div>

      {error && (
        <div className="card" style={{ padding: 12, marginBottom: 16, borderLeft: "3px solid var(--accent-danger)" }}>
          <div className="row gap-2" style={{ alignItems: "flex-start" }}>
            <Icon name="alert-triangle" size={15} color="var(--accent-danger)"/>
            <div className="t-bodysm">{error}</div>
          </div>
        </div>
      )}

      {secret && (
        <div style={{ marginBottom: 16 }}>
          <UmSecretOnce label={secret.label} secret={secret.value} onDone={() => setSecret(null)}/>
        </div>
      )}

      <div className="card" style={{ padding: "12px 16px", marginBottom: 16 }}>
        <div className="row gap-3" style={{ flexWrap: "wrap" }}>
          <input className="field-input" placeholder="Search name, username or email"
                 value={query} onChange={(e) => setQuery(e.target.value)}
                 style={{ minWidth: 260 }}/>
          <select className="field-input" aria-label="Filter by account status"
                  value={stateFilter}
                  onChange={(e) => setStateFilter(e.target.value)}>
            <option value="">All accounts</option>
            <option value="active">Active only</option>
            <option value="inactive">Deactivated only</option>
          </select>
        </div>
      </div>

      <div className="card" style={{ padding: 0 }}>
        <table className="tbl" style={{ boxShadow: "none", marginBottom: 0 }}>
          <thead>
            <tr>
              <th>Account</th><th>Name</th><th>Roles</th>
              <th>Status</th><th>Last login</th><th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan={6} className="t-cap" style={{ padding: 16 }}>Loading…</td></tr>
            )}
            {!loading && rows.length === 0 && (
              <tr><td colSpan={6} className="t-cap" style={{ padding: 16, color: "var(--neutral-500)" }}>
                No accounts match.
              </td></tr>
            )}
            {!loading && rows.map((u) => (
              <tr key={u.id} style={{ opacity: u.is_active ? 1 : 0.55 }}>
                <td className="t-mono">{u.username}</td>
                <td>{`${u.first_name || ""} ${u.last_name || ""}`.trim() || "—"}
                  {u.email && <div className="t-cap" style={{ color: "var(--neutral-500)" }}>{u.email}</div>}
                </td>
                <td>{(u.roles || []).length
                  ? u.roles.map((r) => <Chip key={r} size="sm">{r}</Chip>)
                  : <span className="muted">none</span>}</td>
                <td>
                  {u.is_superuser
                    ? <Chip tone="danger" size="sm">superuser</Chip>
                    : <Chip tone={u.is_active ? "ok" : "warn"} size="sm">
                        {u.is_active ? "active" : "deactivated"}
                      </Chip>}
                </td>
                <td className="t-cap">{u.last_login ? u.last_login.slice(0, 10) : "never"}</td>
                <td>
                  {!u.manageable ? (
                    <span className="t-cap muted"
                          title="Superuser accounts are managed in the Django admin, which stays available. Nothing here can change one.">
                      <Icon name="shield" size={11}/> not managed here
                    </span>
                  ) : (
                    <div className="row gap-2">
                      <button className="btn sm" onClick={() => { setDialog({ kind: "edit", user: u }); setReason(""); }}>
                        Edit
                      </button>
                      <button className="btn sm" onClick={() => { setDialog({ kind: "reset", user: u }); setReason(""); }}>
                        Reset password
                      </button>
                      <button className="btn sm"
                              disabled={isSelf(u)}
                              title={isSelf(u) ? "You cannot change your own roles." : ""}
                              onClick={() => { setDialog({ kind: "roles", user: u, roles: u.roles || [] }); setReason(""); }}>
                        Roles
                      </button>
                      <button className="btn sm"
                              disabled={isSelf(u) && u.is_active}
                              title={isSelf(u) && u.is_active ? "You cannot deactivate your own account." : ""}
                              onClick={() => { setDialog({ kind: "active", user: u }); setReason(""); }}>
                        {u.is_active ? "Deactivate" : "Reactivate"}
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {dialog && (
        <UmDialog dialog={dialog} roles={roles} reason={reason} setReason={setReason}
                  busy={busy} onClose={closeDialog}
                  onCreate={({ scope, ...payload }) => act(() =>
                    _umPost(`${UM_API}create/`, { ...payload, reason })
                      .then(async (d) => {
                        setSecret({
                          label: `Account ${d.user.username} created — temporary password`,
                          value: d.temporary_password,
                        });
                        // An account with no scope sees nothing: the
                        // list queries intersect against active scopes,
                        // so "created successfully" and "cannot see a
                        // single record" is the default outcome without
                        // this step.
                        if (scope && scope.level) {
                          await _umPost(UM_SCOPE_API, {
                            user_id: d.user.id,
                            scope_level: scope.level,
                            scope_codes: scope.level === "national"
                              ? []
                              : scope.codes.split(",").map(c => c.trim()).filter(Boolean),
                            note: reason,
                          });
                        }
                      }))}
                  onRoles={(codes) => act(() =>
                    _umPost(`${UM_API}${dialog.user.id}/roles/`, { roles: codes, reason }))}
                  onEdit={(payload) => act(() =>
                    _umPost(`${UM_API}${dialog.user.id}/profile/`, { ...payload, reason }))}
                  onActive={() => act(() =>
                    _umPost(`${UM_API}${dialog.user.id}/set-active/`,
                            { active: !dialog.user.is_active, reason }))}
                  onReset={(method) => act(() =>
                    _umPost(`${UM_API}${dialog.user.id}/reset-password/`, { method, reason })
                      .then((d) => {
                        if (d.method === "temporary") {
                          setSecret({
                            label: `Temporary password for ${dialog.user.username}`,
                            value: d.temporary_password,
                          });
                        } else {
                          setSecret(null);
                          setError(null);
                        }
                      }))}/>
      )}
    </div>
  );
};

const UmDialog = ({ dialog, roles, reason, setReason, busy, onClose,
                    onCreate, onRoles, onActive, onReset, onEdit }) => {
  const u = dialog.user;
  const [form, setForm] = useStateUM(
    dialog.kind === "edit"
      ? { username: u.username, first_name: u.first_name || "",
          last_name: u.last_name || "", email: u.email || "" }
      : { username: "", first_name: "", last_name: "", email: "" },
  );
  const [selected, setSelected] = useStateUM(dialog.roles || []);
  const [method, setMethod] = useStateUM("temporary");
  const [scope, setScope] = useStateUM({ level: "", codes: "" });
  const needsReason = reason.trim().length > 0;
  const scopeLevel = UM_SCOPE_LEVELS.find(l => l.value === scope.level);
  const scopeIncomplete = !!(scopeLevel && scopeLevel.codes && !scope.codes.trim());

  const toggle = (code) =>
    setSelected(selected.includes(code)
      ? selected.filter((c) => c !== code)
      : [...selected, code]);

  return (
    <div className="card" style={{ padding: 16, marginTop: 16, borderLeft: "3px solid var(--accent-data)" }}>
      {dialog.kind === "create" && (<>
        <strong>New account</strong>
        <p className="t-bodysm" style={{ color: "var(--neutral-700)" }}>
          The account is created with a temporary password, shown once. It has no
          Django admin access and no roles beyond those chosen here.
        </p>
        {["username", "first_name", "last_name", "email"].map((f) => (
          <label key={f} style={{ display: "block", marginTop: 10 }}>
            <span className="t-cap" style={{ fontWeight: 600 }}>{f.replace("_", " ").toUpperCase()}</span>
            <input className="field-input" style={{ width: "100%", marginTop: 6 }}
                   value={form[f]} onChange={(e) => setForm({ ...form, [f]: e.target.value })}/>
          </label>
        ))}
        <UmRolePicker roles={roles} selected={selected} toggle={toggle}/>
        <UmScopePicker roles={roles} selected={selected} scope={scope} setScope={setScope}/>
      </>)}

      {dialog.kind === "edit" && (<>
        <strong>Edit {u.username}</strong>
        <p className="t-bodysm" style={{ color: "var(--neutral-700)" }}>
          Name and email only. The username cannot be changed: the audit
          chain records who did what by username, so renaming an account
          would leave every entry it has already written pointing at a
          name that no longer exists.
        </p>
        <label style={{ display: "block", marginTop: 10 }}>
          <span className="t-cap" style={{ fontWeight: 600 }}>USERNAME</span>
          <input className="field-input" style={{ width: "100%", marginTop: 6 }}
                 value={form.username} disabled readOnly/>
        </label>
        {["first_name", "last_name", "email"].map((f) => (
          <label key={f} style={{ display: "block", marginTop: 10 }}>
            <span className="t-cap" style={{ fontWeight: 600 }}>{f.replace("_", " ").toUpperCase()}</span>
            <input className="field-input" style={{ width: "100%", marginTop: 6 }}
                   value={form[f]} onChange={(e) => setForm({ ...form, [f]: e.target.value })}/>
          </label>
        ))}
      </>)}

      {dialog.kind === "roles" && (<>
        <strong>Roles for {u.username}</strong>
        <p className="t-bodysm" style={{ color: "var(--neutral-700)" }}>
          Membership only. Saving replaces the whole set, so unticking a role
          revokes it.
        </p>
        <UmRolePicker roles={roles} selected={selected} toggle={toggle}/>
      </>)}

      {dialog.kind === "active" && (<>
        <strong>{u.is_active ? "Deactivate" : "Reactivate"} {u.username}</strong>
        <p className="t-bodysm" style={{ color: "var(--neutral-700)" }}>
          {u.is_active
            ? "The account stays in the registry and keeps its history; it simply cannot sign in."
            : "The account will be able to sign in again with its existing password."}
        </p>
      </>)}

      {dialog.kind === "reset" && (<>
        <strong>Reset password for {u.username}</strong>
        <div className="row gap-3" style={{ marginTop: 10, flexWrap: "wrap" }}>
          <label className="row gap-2">
            <input type="radio" checked={method === "temporary"}
                   onChange={() => setMethod("temporary")}/>
            <span>Temporary password, shown once</span>
          </label>
          <label className="row gap-2">
            <input type="radio" checked={method === "link"}
                   onChange={() => setMethod("link")}
                   disabled={!u.email}/>
            <span title={u.email ? "" : "This account has no email address."}>
              Email a reset link{u.email ? "" : " (no address on file)"}
            </span>
          </label>
        </div>
        <p className="t-bodysm" style={{ color: "var(--neutral-700)", marginTop: 8 }}>
          {method === "temporary"
            ? "You will see the password once and pass it on yourself."
            : "The user sets their own password; you never see it."}
        </p>
      </>)}

      <UmReasonField value={reason} onChange={setReason}
                     placeholder="Why this change is being made"/>

      <div className="row gap-2" style={{ marginTop: 14 }}>
        <button className="btn primary"
                disabled={busy || !needsReason || scopeIncomplete}
                title={
                  !needsReason ? "A reason is required."
                  : scopeIncomplete ? "Enter at least one code for that scope level, or choose no scope."
                  : ""
                }
                onClick={() => {
                  if (dialog.kind === "create") onCreate({ ...form, roles: selected, scope });
                  else if (dialog.kind === "edit") onEdit({
                    first_name: form.first_name, last_name: form.last_name,
                    email: form.email,
                  });
                  else if (dialog.kind === "roles") onRoles(selected);
                  else if (dialog.kind === "active") onActive();
                  else onReset(method);
                }}>
          {busy ? "Working…" : "Confirm"}
        </button>
        <button className="btn" onClick={onClose} disabled={busy}>Cancel</button>
      </div>
    </div>
  );
};

const UmRolePicker = ({ roles, selected, toggle }) => (
  <div style={{ marginTop: 12 }}>
    <span className="t-cap" style={{ fontWeight: 600 }}>ROLES</span>
    <div className="row gap-2" style={{ flexWrap: "wrap", marginTop: 8 }}>
      {roles.map((r) => (
        <button key={r.code} type="button"
                onClick={() => r.assignable && toggle(r.code)}
                disabled={!r.assignable}
                title={r.assignable
                  ? (r.privileged ? "Privileged role — the grant is flagged in the audit chain." : "")
                  : "In the catalogue but not yet synced into a group. Run manage.py sync_roles."}
                style={{
                  padding: "6px 10px", borderRadius: 16, fontSize: 12.5,
                  border: `1px solid ${selected.includes(r.code) ? "var(--accent-data)" : "var(--neutral-300)"}`,
                  background: selected.includes(r.code) ? "var(--accent-data-bg)" : "var(--neutral-0)",
                  opacity: r.assignable ? 1 : 0.45,
                }}>
          {r.label}
          {r.privileged && <span className="t-cap" style={{ marginLeft: 6 }}>privileged</span>}
        </button>
      ))}
    </div>
  </div>
);

/* Scope at creation, because an account without one sees nothing.
   List queries intersect against active scopes, so a new operator with
   no scope signs in successfully and finds an empty registry — which
   reads as a broken system rather than a missing grant.

   The level defaults from the first chosen role's default_scope, which
   is already in the catalogue, so the common case is one click. Grants
   go to the Operator scopes endpoint; this is a shortcut into it, not a
   second implementation of it. */
const UmScopePicker = ({ roles, selected, scope, setScope }) => {
  const suggested = (roles.find(r => r.code === selected[0]) || {}).default_scope || "";
  const level = UM_SCOPE_LEVELS.find(l => l.value === scope.level);
  return (
    <div style={{ marginTop: 14 }}>
      <span className="t-cap" style={{ fontWeight: 600 }}>INITIAL SCOPE</span>
      <div className="row gap-2" style={{ marginTop: 8, flexWrap: "wrap" }}>
        <select className="field-input" aria-label="Initial scope level"
                value={scope.level}
                onChange={(e) => setScope({ ...scope, level: e.target.value })}>
          {UM_SCOPE_LEVELS.map(l => (
            <option key={l.value} value={l.value}>{l.label}</option>
          ))}
        </select>
        {level && level.codes && (
          <input className="field-input" style={{ minWidth: 240 }}
                 placeholder="Codes, comma separated (e.g. 304, 305)"
                 value={scope.codes}
                 onChange={(e) => setScope({ ...scope, codes: e.target.value })}/>
        )}
        {suggested && scope.level !== suggested && (
          <button type="button" className="btn sm"
                  onClick={() => setScope({ ...scope, level: suggested })}>
            Use {suggested} (this role's default)
          </button>
        )}
      </div>
      <p className="t-bodysm" style={{ color: "var(--neutral-700)", marginTop: 6 }}>
        {scope.level
          ? "Granted through Operator scopes, with its own audit entry."
          : "Without a scope this account will sign in and see no records at all. You can grant one later in Operator scopes."}
      </p>
    </div>
  );
};

window.AdminUsersScreen = AdminUsersScreen;
