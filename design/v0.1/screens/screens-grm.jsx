/* global React, Icon, Chip, PageHeader, AuditDrawer, Modal, ReasonModal, ActionBar, Toast */
// NSR MIS — GRM workbench (US-S8-006 / US-S21-002 live wiring).
// Parity-or-better with the Django admin from S4-005 + S6-001: list
// + SLA badge + bulk assign/escalate/resolve/close. As of US-S21-002
// the screen fetches /api/v1/grm/grievances/ on mount and routes
// every action through the matching POST endpoint. Mock data below
// is the offline fallback for design previews.

const { useState: useStateGrm, useMemo: useMemoGrm, useEffect: useEffectGrm } = React;

// CSRF cookie reader — required for DRF session-auth POSTs. Same
// pattern as screens-dih + screens-dedup. The Django admin login
// flow sets the cookie; file:// previews don't have it (the action
// fetches will 403 in that mode, by design).
const _grmCsrf = () => {
  const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return m ? m[1] : "";
};

// Project an /api/v1/grm/grievances/ row into the view-model the
// existing table renders. Field renames + derived fields:
//   reporter_relationship → relationship
//   description           → narrative
//   opened_at (ISO)       → "DD MMM HH:MM" (EAT-rendered)
//   sla_deadline + now    → hours_to_breach (positive = within SLA)
const _grmMonths = ["Jan","Feb","Mar","Apr","May","Jun",
                    "Jul","Aug","Sep","Oct","Nov","Dec"];
const _grmFmtTime = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(d.getDate())} ${_grmMonths[d.getMonth()]} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
};
const _grmApiToView = (g) => {
  // null hours_to_breach means "no SLA set" — slaChip renders it as
  // a dash. Computed positive = within SLA, negative = breached.
  let hours_to_breach = null;
  if (g.sla_deadline) {
    const ms = new Date(g.sla_deadline).getTime() - Date.now();
    hours_to_breach = Math.round(ms / 3_600_000);
  }
  return {
    id: g.id,
    category: g.category,
    tier: g.tier,
    status: g.status,
    household_id: g.household_id || "",
    member_id: g.member_id || "",
    reporter_name: g.reporter_name || "",
    reporter_phone: g.reporter_phone || "",
    relationship: g.reporter_relationship || "—",
    assigned_to: g.assigned_to || "",
    opened_at: _grmFmtTime(g.opened_at),
    hours_to_breach,
    narrative: g.description || "",
    // US-S21-005 — case-closeout fields used by the
    // Resolution & Closing block.
    resolution_narrative: g.resolution_narrative || "",
    resolved_at: _grmFmtTime(g.resolved_at),
    resolved_by: g.resolved_by || "",
    closing_narrative: g.closing_narrative || "",
    closed_at: _grmFmtTime(g.closed_at),
    closed_by: g.closed_by || "",
  };
};

// Tier vocabulary mirrors apps.grievance.models.Tier. Labels chosen
// for the workbench column header — operators speak "L1/L2/L3/L4"
// in the corridor; the long names live in the row detail.
const GRM_TIERS = {
  l1_parish_chief: { short: "L1", label: "Parish Chief", sla_hours: 24 },
  l2_cdo:          { short: "L2", label: "CDO",          sla_hours: 48 },
  l3_district:     { short: "L3", label: "District",     sla_hours: 72 },
  l4_nsr_unit:     { short: "L4", label: "NSR Unit",     sla_hours: 168 },
};

const GRM_CATEGORIES = {
  data_correction:  "Data correction",
  exclusion_error:  "Wrongly excluded",
  inclusion_error:  "Wrongly included",
  programme_issue:  "Programme issue",
  operator_conduct: "Operator conduct",
  other:            "Other",
};

const GRM_STATUSES = {
  open:        { label: "Open",         tone: "data" },
  in_progress: { label: "In progress",  tone: "update" },
  escalated:   { label: "Escalated",    tone: "danger" },
  resolved:    { label: "Resolved",     tone: "eligibility" },
  closed:      { label: "Closed",       tone: "neutral" },
};

// Offline-preview fallback rows mirroring GrievanceSerializer
// (apps/grievance/api.py). Used when /api/v1/grm/grievances/ is
// unreachable (file:// preview) or returns no rows (fresh DB).
// hours_to_breach is precomputed here; live rows compute it from
// sla_deadline via _grmApiToView.
const GRM_MOCK_ROWS = [
  { id: "01GRM2026051400001", category: "data_correction", tier: "l1_parish_chief", status: "open",        household_id: "01HXY7K3B2N9PVQE4M6FZRWS18", member_id: "01HXY7K3B2N9PVQE4M6FZRWS19", reporter_name: "Sarah Nakato",  reporter_phone: "+256 786 234 567", relationship: "Daughter",      assigned_to: "",                  opened_at: "14 May 09:12", hours_to_breach:  18, narrative: "Surname spelled OKELO instead of OKELLO on receipt slip." },
  { id: "01GRM2026051400002", category: "exclusion_error", tier: "l2_cdo",          status: "in_progress", household_id: "01HXZ9MR4N8P2QFB7K6FZRWS33", member_id: "",                              reporter_name: "Akello Grace", reporter_phone: "+256 772 991 234", relationship: "Self · head",   assigned_to: "Adong Florence",    opened_at: "13 May 17:40", hours_to_breach:  -3, narrative: "Household enumerated but not appearing in CDO register; PMT band missing." },
  { id: "01GRM2026051400003", category: "programme_issue", tier: "l3_district",     status: "escalated",   household_id: "01HXZBVK6QN8M2PFB7K6FZRWS41", member_id: "01HXZBVK6QN8M2PFB7K6FZRWS42", reporter_name: "Onyango David",reporter_phone: "+256 752 110 080", relationship: "Self · head",   assigned_to: "Twikirize J. · DM&E",opened_at: "12 May 11:05", hours_to_breach: -27, narrative: "Eligible for PDM SACCO; partner says NSR ID not on roster." },
  { id: "01GRM2026051400004", category: "operator_conduct",tier: "l2_cdo",          status: "open",        household_id: "",                                  member_id: "",                              reporter_name: "Anonymous",     reporter_phone: "",                  relationship: "—",              assigned_to: "",                  opened_at: "14 May 06:55", hours_to_breach:  41, narrative: "Enumerator requested money to register family. Tablet ID PCH-4421." },
  { id: "01GRM2026051400005", category: "data_correction", tier: "l1_parish_chief", status: "open",        household_id: "01HY09KRS1P9MN6FB7K6FZRWS84", member_id: "01HY09KRS1P9MN6FB7K6FZRWS85", reporter_name: "Lokwang Peter", reporter_phone: "+256 782 005 511", relationship: "Self · head",   assigned_to: "Akiteng L.",        opened_at: "13 May 16:30", hours_to_breach:  -1, narrative: "DOB recorded as 1985 but birth-cert shows 1987." },
  { id: "01GRM2026051400006", category: "inclusion_error", tier: "l4_nsr_unit",     status: "escalated",   household_id: "01HY02FNQ9P8MN6FB7K6FZRWS67", member_id: "",                              reporter_name: "Programme MIS · PDM", reporter_phone: "",          relationship: "—",              assigned_to: "Coordinator",       opened_at: "08 May 13:20", hours_to_breach:  19, narrative: "Household marked deceased by NIRA reverse-feed but still showing in PDM roster." },
  { id: "01GRM2026051400007", category: "data_correction", tier: "l1_parish_chief", status: "resolved",    household_id: "01HY04MQR0N8P2FB7K6FZRWS73", member_id: "01HY04MQR0N8P2FB7K6FZRWS74", reporter_name: "Auma Beatrice", reporter_phone: "+256 778 213 994", relationship: "Self · head",   assigned_to: "Akiteng L.",        opened_at: "12 May 08:00", hours_to_breach:   0, narrative: "Telephone updated; UPD 01HXYUPD20260512EFAB committed by CDO." },
];

// Hours-to-breach -> SLA chip. Mirrors the format_html badge from
// apps/grievance/admin.py — green/amber/red is the corridor signal.
const slaChip = (h, status) => {
  if (status === "resolved" || status === "closed") return <Chip size="sm" tone="neutral">—</Chip>;
  if (h === null || h === undefined) return <Chip size="sm" tone="neutral">no SLA</Chip>;
  if (h < 0)  return <Chip size="sm" tone="danger"><Icon name="clock" size={11}/> {Math.abs(h)}h overdue</Chip>;
  if (h <= 6) return <Chip size="sm" tone="quality"><Icon name="clock" size={11}/> {h}h to breach</Chip>;
  return <Chip size="sm" tone="data"><Icon name="clock" size={11}/> {h}h left</Chip>;
};

// US-S21-003c — synthetic timeline for the CASE DETAIL rail. Builds
// a chronological list of {label, detail, at, tone} events from the
// grievance fields + tasks state. Used inline instead of (or
// alongside) the Audit drawer.
const _grmTimelineFor = (g, tasks) => {
  if (!g) return [];
  const events = [];
  events.push({
    label: "Opened",
    detail: g.reporter_name ? `Reporter: ${g.reporter_name}` : "Anonymous channel",
    at: g.opened_at, tone: "data",
  });
  if (g.assigned_to) {
    events.push({
      label: `Assigned to ${g.assigned_to}`,
      at: g.opened_at, tone: "user",
    });
  }
  if (g.status === "escalated") {
    events.push({
      label: `Escalated to ${GRM_TIERS[g.tier]?.short || g.tier}`,
      detail: "Tier reset · SLA window restarted",
      at: "—", tone: "update",
    });
  }
  for (const t of (tasks || [])) {
    events.push({
      label: `Task created: ${t.title}`,
      detail: `assigned to ${t.assigned_to}`,
      at: _grmFmtTime(t.created_at), tone: "data",
    });
    if (t.status === "in_progress") {
      events.push({
        label: `Task started: ${t.title}`,
        at: _grmFmtTime(t.updated_at), tone: "update",
      });
    }
    if (t.closed_at) {
      events.push({
        label: `Task closed: ${t.title}`,
        detail: t.closed_by ? `by ${t.closed_by}` : "",
        at: _grmFmtTime(t.closed_at), tone: "eligibility",
      });
    }
  }
  if (g.status === "resolved" || g.status === "closed") {
    events.push({
      label: "Resolved",
      detail: g.narrative ? g.narrative.slice(0, 60) : "",
      at: "—", tone: "eligibility",
    });
  }
  if (g.status === "closed") {
    events.push({ label: "Closed", at: "—", tone: "neutral" });
  }
  return events;
};


const QUICK_FILTERS_GRM = [
  { id: "breach",    label: "Past SLA (any tier)",       icon: "alert",      tone: "danger",  predicate: r => r.hours_to_breach < 0 && r.status !== "resolved" && r.status !== "closed" },
  { id: "open_l1",   label: "Open L1 — Parish Chief",    icon: "users",      tone: "data",    predicate: r => r.tier === "l1_parish_chief" && r.status === "open" },
  { id: "escalated", label: "Escalated — needs me",      icon: "arrowUp",    tone: "update",  predicate: r => r.status === "escalated" },
  { id: "mine",      label: "Assigned to me",            icon: "user",       tone: "programme", predicate: r => r.assigned_to !== "" && r.status !== "closed" },
];

const GRMScreen = ({ onNavigate }) => {
  // Live state. allRows is the canonical roster (live or mock); rows
  // is the visible subset after quick-filter. dataSource drives the
  // eyebrow indicator so an operator can see whether they're looking
  // at real data or the offline-preview fallback.
  const [allRows, setAllRows] = useStateGrm(GRM_MOCK_ROWS);
  const [dataSource, setDataSource] = useStateGrm("mock");
  const [selectedRow, setSelectedRow] = useStateGrm(GRM_MOCK_ROWS[1].id);
  const [selection, setSelection] = useStateGrm(new Set());
  const [quickFilter, setQuickFilter] = useStateGrm(null);
  // 'assign' | 'escalate' | 'resolve' | 'close' | 'open_grievance' | 'add_task'
  const [modal, setModal] = useStateGrm(null);
  const [assignee, setAssignee] = useStateGrm("");
  const [busy, setBusy] = useStateGrm(false);
  const [auditOpen, setAuditOpen] = useStateGrm(false);
  const [toast, setToast] = useStateGrm("");
  // US-S21-003c — tasks for the currently-selected grievance, plus
  // role flag from the /me endpoint. Officer-status drives whether
  // "+ Add task" and "Open grievance" affordances render.
  const [tasks, setTasks] = useStateGrm([]);
  const [me, setMe] = useStateGrm({ username: "", is_officer: false });
  // Form state for the Open-Grievance modal.
  const [openForm, setOpenForm] = useStateGrm({
    category: "data_correction", description: "", tier: "l1_parish_chief",
    household_id: "", member_id: "",
    reporter_name: "", reporter_phone: "", reporter_relationship: "",
  });
  // Form state for the Add-Task modal.
  const [taskForm, setTaskForm] = useStateGrm({
    title: "", description: "", assigned_to: "",
  });

  // Refresh the roster from the API. Used on mount + after every
  // successful action. On unreachable API (file:// preview) it
  // marks dataSource so the eyebrow reflects it.
  const refresh = () => fetch(
    "/api/v1/grm/grievances/?page_size=100", {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
    .then(r => r.ok ? r.json() : Promise.reject(r.status))
    .then(data => {
      const list = (data.results || data || []).map(_grmApiToView);
      if (list.length === 0) {
        // Live but empty (fresh DB / no rows in operator's ABAC
        // scope). Keep mock visible so the design preview still
        // demos; the eyebrow tells the operator what's happening.
        setDataSource("live-empty");
        return;
      }
      setAllRows(list);
      setDataSource("live");
    })
    .catch(() => { setDataSource("offline"); });

  useEffectGrm(() => { refresh(); /* eslint-disable-line */ }, []);

  // Probe the /me endpoint on mount to learn whether this user is a
  // GRM Officer. Officer status gates the "Open grievance" + "Add
  // task" affordances. On a file:// preview (no Django session)
  // the call 401s and we leave is_officer=false — the preview demo
  // still works because the offline fallback in fire() doesn't
  // require an officer.
  useEffectGrm(() => {
    fetch("/api/v1/grm/grievances/me/", {
      credentials: "same-origin", headers: { Accept: "application/json" },
    })
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data) setMe(data); })
      .catch(() => {});
  }, []);

  // Refetch tasks whenever the selected grievance changes. Tasks are
  // visible-to-everyone on the row (the API narrows server-side); we
  // just render whatever the API returns.
  const refreshTasks = (grievanceId) => {
    if (!grievanceId) { setTasks([]); return Promise.resolve(); }
    return fetch(
      `/api/v1/grm/tasks/?grievance=${encodeURIComponent(grievanceId)}&page_size=100`,
      { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(data => { setTasks(data.results || data || []); })
      .catch(() => { setTasks([]); });
  };
  useEffectGrm(() => {
    if (dataSource === "live" || dataSource === "live-empty") {
      refreshTasks(selectedRow);
    }
    /* eslint-disable-next-line */
  }, [selectedRow, dataSource]);

  // Open a new grievance via POST /api/v1/grm/grievances/. The
  // server stamps SLA + audit; we just refresh on success.
  const submitOpenGrievance = () => {
    if (!openForm.category || !openForm.description) {
      setToast("Category and description are required.");
      return;
    }
    setBusy(true);
    fetch("/api/v1/grm/grievances/", {
      method: "POST", credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": _grmCsrf(),
        Accept: "application/json",
      },
      body: JSON.stringify(openForm),
    })
      .then(async r => {
        if (r.status === 201) return r.json();
        const j = await r.json().catch(() => ({ detail: r.status }));
        throw new Error(j.detail || `HTTP ${r.status}`);
      })
      .then(grievance => {
        setToast(`Grievance ${grievance.id.slice(0, 8)}… opened.`);
        setModal(null);
        setOpenForm({
          category: "data_correction", description: "", tier: "l1_parish_chief",
          household_id: "", member_id: "",
          reporter_name: "", reporter_phone: "", reporter_relationship: "",
        });
        return refresh().then(() => setSelectedRow(grievance.id));
      })
      .catch(e => setToast(`Open failed: ${e.message}`))
      .finally(() => setBusy(false));
  };

  // Create a task on the current grievance.
  const submitAddTask = () => {
    if (!current) return;
    if (!taskForm.title || !taskForm.assigned_to) {
      setToast("Task needs a title and an assignee.");
      return;
    }
    setBusy(true);
    fetch("/api/v1/grm/tasks/", {
      method: "POST", credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": _grmCsrf(),
        Accept: "application/json",
      },
      body: JSON.stringify({ ...taskForm, grievance: current.id }),
    })
      .then(async r => {
        if (r.status === 201) return r.json();
        const j = await r.json().catch(() => ({ detail: r.status }));
        throw new Error(j.detail || `HTTP ${r.status}`);
      })
      .then(() => {
        setToast(`Task assigned to ${taskForm.assigned_to}.`);
        setModal(null);
        setTaskForm({ title: "", description: "", assigned_to: "" });
        return refreshTasks(current.id);
      })
      .catch(e => setToast(`Add task failed: ${e.message}`))
      .finally(() => setBusy(false));
  };

  // Transition a task's status (open ↔ in_progress, → closed).
  const transitionTask = (taskId, new_status) => {
    setBusy(true);
    fetch(`/api/v1/grm/tasks/${taskId}/transition/`, {
      method: "POST", credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": _grmCsrf(),
        Accept: "application/json",
      },
      body: JSON.stringify({ new_status }),
    })
      .then(async r => {
        if (r.ok) return r.json();
        const j = await r.json().catch(() => ({ detail: r.status }));
        throw new Error(j.detail || `HTTP ${r.status}`);
      })
      .then(() => refreshTasks(current?.id))
      .catch(e => setToast(`Transition failed: ${e.message}`))
      .finally(() => setBusy(false));
  };

  // Keep selectedRow valid when allRows changes (e.g., after a live
  // fetch replaces mock IDs).
  useEffectGrm(() => {
    if (!allRows.find(r => r.id === selectedRow)) {
      setSelectedRow(allRows[0]?.id || "");
    }
  }, [allRows, selectedRow]);

  const rows = useMemoGrm(() => {
    if (!quickFilter) return allRows;
    const def = QUICK_FILTERS_GRM.find(f => f.id === quickFilter);
    return def ? allRows.filter(def.predicate) : allRows;
  }, [allRows, quickFilter]);

  const current = useMemoGrm(
    () => allRows.find(r => r.id === selectedRow),
    [allRows, selectedRow],
  );

  const toggleSel = (id) => {
    const next = new Set(selection);
    if (next.has(id)) next.delete(id); else next.add(id);
    setSelection(next);
  };
  const toggleAll = () => {
    if (selection.size === rows.length) setSelection(new Set());
    else setSelection(new Set(rows.map(r => r.id)));
  };

  // Reasons mirror the service-layer guards (apps.grievance.services).
  // Surfacing them as canned options reduces narrative-quality drift.
  const reasonsEscalate = [
    "L1 SLA breached without resolution",
    "Requires CDO authority (programme override)",
    "Citizen escalation request on record",
    "Other (specify in note)",
  ];
  const reasonsResolve = [
    "Data correction committed via linked UPD",
    "Operator follow-up — issue not substantiated",
    "Citizen withdrew complaint",
    "Other (specify in note)",
  ];
  const reasonsClose = [
    "Resolution confirmed by reporter",
    "30-day grace expired without dispute",
    "Other (specify in note)",
  ];

  // Route one action through the API. Each kind maps to a custom
  // detail-route on GrievanceViewSet (apps/grievance/api.py):
  //   assign   POST .../assign/   {actor, assigned_to}
  //   escalate POST .../escalate/ {actor, reason}
  //   resolve  POST .../resolve/  {actor, narrative}
  //   close    POST .../close/    {actor}
  // Returns a Promise so callers can chain a refresh.
  const _grmPost = (id, kind, body) => fetch(
    `/api/v1/grm/grievances/${id}/${kind}/`, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": _grmCsrf(),
        Accept: "application/json",
      },
      body: JSON.stringify(body),
    });

  // Fire `kind` against every selected id (or `current` if no
  // selection). After all calls settle, refresh the roster, toast,
  // and clear the selection.
  const fire = (kind, opts = {}) => {
    if (dataSource === "offline" || dataSource === "mock") {
      // No live API available — keep the demo behaviour so the
      // design preview still works under file://.
      const map = {
        assign:   `${selection.size || 1} grievance(s) assigned. (preview — not persisted)`,
        escalate: `${selection.size || 1} grievance(s) escalated. (preview — not persisted)`,
        resolve:  `Grievance resolved. (preview — not persisted)`,
        close:    `${selection.size || 1} grievance(s) closed. (preview — not persisted)`,
      };
      setToast(map[kind] || "Done.");
      setModal(null); setSelection(new Set());
      return;
    }
    const ids = selection.size > 0
      ? [...selection]
      : current ? [current.id] : [];
    if (ids.length === 0) {
      setToast("No grievance selected.");
      setModal(null);
      return;
    }
    const body = { actor: "console-operator", ...(opts.body || {}) };
    setBusy(true);
    Promise.all(ids.map(id => _grmPost(id, kind, body)
      .then(r => r.ok ? null : r.json().then(j => ({ id, detail: j.detail || r.status })))))
      .then(failures => failures.filter(Boolean))
      .then(failures => {
        if (failures.length === 0) {
          const map = {
            assign:   `${ids.length} grievance(s) assigned.`,
            escalate: `${ids.length} grievance(s) escalated one tier.`,
            resolve:  `Grievance resolved.`,
            close:    `${ids.length} grievance(s) closed.`,
          };
          setToast(map[kind] || "Done.");
        } else {
          setToast(
            `${ids.length - failures.length}/${ids.length} succeeded. ` +
            failures.slice(0, 2).map(f => f.detail).join(" · "),
          );
        }
        return refresh();
      })
      .finally(() => {
        setBusy(false);
        setModal(null);
        setSelection(new Set());
        setAssignee("");
      });
  };

  const auditEvents = current ? [
    { who: "Reporter",       action: "opened grievance",     detail: `Via ${current.reporter_phone ? 'parish channel · ' + current.reporter_phone : 'anonymous web form'}`, time: current.opened_at, audit: `A-2026-05-${current.id.slice(-2)}-001`, tone: "user" },
    { who: "System GRM",     action: "computed SLA",         detail: `Tier ${GRM_TIERS[current.tier].short} window = ${GRM_TIERS[current.tier].sla_hours}h from open`, time: current.opened_at, audit: `A-2026-05-${current.id.slice(-2)}-002`, tone: "system" },
    ...(current.assigned_to ? [{ who: "Supervisor", action: "assigned to",       detail: current.assigned_to, time: "12m later", audit: `A-2026-05-${current.id.slice(-2)}-003`, tone: "user" }] : []),
    ...(current.status === "escalated" ? [{ who: "System GRM", action: "escalated tier", detail: "SLA breach auto-escalator (US-S7-001 pattern)", time: `${Math.abs(current.hours_to_breach)}h later`, audit: `A-2026-05-${current.id.slice(-2)}-004`, tone: "system" }] : []),
    ...(current.status === "resolved" ? [{ who: "CDO",        action: "resolved with",     detail: "Linked UPD 01HXYUPD20260512EFAB · awaiting commit", time: "later", audit: `A-2026-05-${current.id.slice(-2)}-005`, tone: "user" }] : []),
  ] : [];

  return (
    <div className="page" style={{paddingBottom:0, position:'relative'}}>
      <PageHeader
        eyebrow={dataSource === "live"
          ? "GRM WORKBENCH · US-S8-006 · LIVE"
          : dataSource === "live-empty"
            ? "GRM WORKBENCH · US-S8-006 · live (0 in scope)"
            : dataSource === "offline"
              ? "GRM WORKBENCH · US-S8-006 · offline preview"
              : "GRM WORKBENCH · US-S8-006"}
        title={<>Grievance management <Chip>{allRows.filter(r => r.status !== "closed" && r.status !== "resolved").length} active</Chip></>}
        sub={dataSource === "live"
          ? "Live ABAC-scoped data. SLA = 24h L1 / 48h L2 / 72h L3 / 7d L4 (per SAD §11.1)."
          : "Triage, assign, escalate, resolve. SLA = 24h L1 / 48h L2 / 72h L3 / 7d L4 (per SAD §11.1)."}
        right={<>
          <button className="btn" onClick={() => setAuditOpen(true)}><Icon name="history"/> Audit chain</button>
          <button className="btn" onClick={() => refresh()} disabled={busy}>
            <Icon name="refreshCw"/> {busy ? "…" : "Refresh"}
          </button>
          <button className="btn"><Icon name="download"/> Export CSV</button>
          {me.is_officer && (
            <button className="btn primary" onClick={() => setModal("open_grievance")}>
              <Icon name="plus"/> Open grievance
            </button>
          )}
        </>}
      />

      {/* Quick-filter bar */}
      <div className="card" style={{padding:"14px 20px", marginBottom:16}}>
        <div className="row gap-3" style={{flexWrap:"wrap"}}>
          <span className="t-cap" style={{fontWeight:600}}>QUICK FILTERS</span>
          {QUICK_FILTERS_GRM.map(f => {
            const count = allRows.filter(f.predicate).length;
            const active = quickFilter === f.id;
            return (
              <button
                key={f.id}
                className={`chip-btn ${active ? "active" : ""}`}
                onClick={() => setQuickFilter(active ? null : f.id)}
                style={{
                  display:"inline-flex", alignItems:"center", gap:6,
                  padding:"6px 10px", borderRadius:8, fontSize:13, fontWeight:500,
                  border: active ? `1px solid var(--accent-${f.tone})` : "1px solid var(--neutral-300)",
                  background: active ? `var(--accent-${f.tone}-bg)` : "white",
                  color: active ? `var(--accent-${f.tone})` : "var(--neutral-800)",
                  cursor:"pointer",
                }}>
                <Icon name={f.icon} size={13}/>
                {f.label}
                <span style={{
                  marginLeft:4, padding:"1px 6px", borderRadius:10, fontSize:11,
                  background: active ? `var(--accent-${f.tone})` : "var(--neutral-200)",
                  color: active ? "white" : "var(--neutral-700)",
                }}>{count}</span>
              </button>
            );
          })}
          {quickFilter && (
            <button className="btn ghost" onClick={() => setQuickFilter(null)}>
              <Icon name="x" size={13}/> Clear
            </button>
          )}
        </div>
      </div>

      {/* List + detail split */}
      <div style={{display:"grid", gridTemplateColumns:"1fr 380px", gap:16}}>
        <div className="card">
          <div className="card-toolbar">
            <strong className="t-bodysm">
              {selection.size > 0
                ? <>{selection.size} selected of {rows.length}</>
                : <>{rows.length} grievances</>}
            </strong>
            <div style={{flex:1}}/>
            {selection.size > 0 && (
              <div className="row gap-2">
                <button className="btn" onClick={() => setModal("assign")}>
                  <Icon name="user" size={13}/> Assign
                </button>
                <button className="btn" onClick={() => setModal("escalate")}>
                  <Icon name="arrowUp" size={13}/> Escalate
                </button>
                <button className="btn" onClick={() => setModal("close")}>
                  <Icon name="check" size={13}/> Close
                </button>
              </div>
            )}
          </div>

          {/* Header */}
          <div style={{display:"grid", gridTemplateColumns:"32px 1fr 110px 100px 130px 140px 130px", borderBottom:"1px solid var(--neutral-200)", background:"var(--neutral-50)", fontSize:11, fontWeight:600, letterSpacing:"0.06em", textTransform:"uppercase", color:"var(--neutral-700)"}}>
            <div style={{padding:"10px 8px", textAlign:"center"}}>
              <input type="checkbox" checked={selection.size === rows.length && rows.length > 0} onChange={toggleAll}/>
            </div>
            <div style={{padding:"10px 16px"}}>Subject / Reporter</div>
            <div style={{padding:"10px 8px"}}>Tier</div>
            <div style={{padding:"10px 8px"}}>Status</div>
            <div style={{padding:"10px 8px"}}>SLA</div>
            <div style={{padding:"10px 8px"}}>Assigned</div>
            <div style={{padding:"10px 8px"}}>Opened</div>
          </div>

          {rows.map(r => {
            const sel = selection.has(r.id);
            const active = selectedRow === r.id;
            const status = GRM_STATUSES[r.status];
            const tier = GRM_TIERS[r.tier];
            return (
              <div
                key={r.id}
                onClick={() => setSelectedRow(r.id)}
                style={{
                  display:"grid", gridTemplateColumns:"32px 1fr 110px 100px 130px 140px 130px",
                  borderBottom:"1px solid var(--neutral-200)",
                  background: active ? "var(--accent-data-bg)" : sel ? "var(--neutral-50)" : "white",
                  cursor:"pointer",
                  alignItems:"center",
                }}>
                <div style={{padding:"12px 8px", textAlign:"center"}} onClick={(e) => { e.stopPropagation(); toggleSel(r.id); }}>
                  <input type="checkbox" checked={sel} onChange={() => {}}/>
                </div>
                <div style={{padding:"12px 16px"}}>
                  <div style={{fontSize:13, fontWeight:500, color:"var(--neutral-900)"}}>
                    {GRM_CATEGORIES[r.category]}
                    {r.household_id && <span className="t-mono muted" style={{marginLeft:8, fontSize:11}}>· hh {r.household_id.slice(0,12)}…</span>}
                  </div>
                  <div className="t-bodysm muted" style={{marginTop:2}}>
                    {r.reporter_name}{r.relationship !== "—" && ` · ${r.relationship}`}{r.reporter_phone && ` · ${r.reporter_phone}`}
                  </div>
                </div>
                <div style={{padding:"12px 8px"}}>
                  <Chip size="sm" tone="data" title={tier.label}>{tier.short}</Chip>
                </div>
                <div style={{padding:"12px 8px"}}>
                  <Chip size="sm" tone={status.tone}>{status.label}</Chip>
                </div>
                <div style={{padding:"12px 8px"}}>
                  {slaChip(r.hours_to_breach, r.status)}
                </div>
                <div style={{padding:"12px 8px", fontSize:12, color: r.assigned_to ? "var(--neutral-800)" : "var(--neutral-500)"}}>
                  {r.assigned_to || <em>unassigned</em>}
                </div>
                <div style={{padding:"12px 8px", fontSize:12, color:"var(--neutral-700)"}}>
                  {r.opened_at}
                </div>
              </div>
            );
          })}

          {rows.length === 0 && (
            <div style={{padding:48, textAlign:"center", color:"var(--neutral-500)"}}>
              <Icon name="inbox" size={32} color="var(--neutral-300)"/>
              <div className="t-bodysm mt-2">No grievances match this filter.</div>
            </div>
          )}
        </div>

        {/* Detail rail */}
        {current && (
          <div className="col gap-3">
            <div className="card" style={{borderTop:"3px solid var(--accent-data)"}}>
              <div className="card-header" style={{padding:"12px 16px"}}>
                <div>
                  <div className="t-cap"><Icon name="message" size={11}/> CASE DETAIL</div>
                  <h3 className="t-h3" style={{margin:"2px 0 0"}}>{GRM_CATEGORIES[current.category]}</h3>
                </div>
                <Chip tone={GRM_STATUSES[current.status].tone}>{GRM_STATUSES[current.status].label}</Chip>
              </div>
              <div style={{padding:16}}>
                <div className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)", marginBottom:6}}>ID</div>
                <div className="t-mono" style={{fontSize:12}}>{current.id}</div>

                <div className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)", margin:"14px 0 6px"}}>TIER + SLA</div>
                <div className="row gap-2">
                  <Chip tone="data">{GRM_TIERS[current.tier].short} · {GRM_TIERS[current.tier].label}</Chip>
                  {slaChip(current.hours_to_breach, current.status)}
                </div>

                <div className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)", margin:"14px 0 6px"}}>NARRATIVE</div>
                <div className="t-bodysm" style={{color:"var(--neutral-800)", lineHeight:1.5}}>
                  {current.narrative}
                </div>

                <div className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)", margin:"14px 0 6px"}}>REPORTER</div>
                <div className="t-bodysm" style={{color:"var(--neutral-800)"}}>{current.reporter_name}</div>
                <div className="t-bodysm muted">{current.relationship}</div>
                {current.reporter_phone && <div className="t-bodysm muted t-mono" style={{fontSize:12}}>{current.reporter_phone}</div>}

                {current.household_id && (
                  <>
                    <div className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)", margin:"14px 0 6px"}}>SUBJECT</div>
                    <div className="t-mono" style={{fontSize:12}}>{current.household_id}</div>
                    {current.member_id && <div className="t-mono muted" style={{fontSize:11, marginTop:2}}>member: {current.member_id.slice(0,18)}…</div>}
                  </>
                )}

                <div className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)", margin:"14px 0 6px"}}>ASSIGNED</div>
                <div className="t-bodysm" style={{color: current.assigned_to ? "var(--neutral-800)" : "var(--neutral-500)"}}>
                  {current.assigned_to || <em>unassigned — pick this case up</em>}
                </div>
              </div>
            </div>

            {/* US-S21-005 — Resolution & Closing block. Surfaces
                the captured narrative + actor + timestamp pair for
                each lifecycle close-out so the operator doesn't have
                to dig into the audit drawer. Renders only when
                the grievance has actually been resolved or closed. */}
            {current && (current.status === "resolved" || current.status === "closed") && (
              <div className="card" style={{borderTop:"3px solid var(--accent-eligibility)"}}>
                <div style={{padding:"12px 16px"}}>
                  <div className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)", marginBottom:8}}>
                    <Icon name="check" size={11}/> RESOLUTION
                    <Chip size="sm" tone="eligibility" style={{marginLeft:6}}>
                      Resolved
                    </Chip>
                  </div>
                  {current.resolution_narrative ? (
                    <div className="t-bodysm" style={{
                      color:"var(--neutral-800)",
                      lineHeight:1.5,
                      whiteSpace:"pre-wrap",
                      padding:"8px 10px",
                      background:"var(--accent-eligibility-bg)",
                      borderRadius:4,
                    }}>
                      {current.resolution_narrative}
                    </div>
                  ) : (
                    <div className="t-bodysm muted" style={{fontStyle:"italic"}}>
                      No narrative captured.
                    </div>
                  )}
                  <div className="t-bodysm muted" style={{fontSize:11, marginTop:6}}>
                    by <strong>{current.resolved_by || "—"}</strong>
                    {current.resolved_at && <> · {current.resolved_at}</>}
                  </div>

                  {current.status === "closed" && (
                    <>
                      <div className="t-cap" style={{
                        fontWeight:600, color:"var(--neutral-700)",
                        margin:"14px 0 8px",
                      }}>
                        <Icon name="lock" size={11}/> CLOSING
                        <Chip size="sm" tone="neutral" style={{marginLeft:6}}>
                          Closed
                        </Chip>
                      </div>
                      {current.closing_narrative ? (
                        <div className="t-bodysm" style={{
                          color:"var(--neutral-800)",
                          lineHeight:1.5,
                          whiteSpace:"pre-wrap",
                          padding:"8px 10px",
                          background:"var(--neutral-100)",
                          borderRadius:4,
                        }}>
                          {current.closing_narrative}
                        </div>
                      ) : (
                        <div className="t-bodysm muted" style={{fontStyle:"italic"}}>
                          No closing note captured.
                        </div>
                      )}
                      <div className="t-bodysm muted" style={{fontSize:11, marginTop:6}}>
                        by <strong>{current.closed_by || "—"}</strong>
                        {current.closed_at && <> · {current.closed_at}</>}
                      </div>
                    </>
                  )}
                </div>
              </div>
            )}

            {/* US-S21-003c — Tasks panel. GRM Officer scopes the work
                into tasks; the assignee transitions them; the resolve
                action below is disabled until every task is closed. */}
            {(dataSource === "live" || dataSource === "live-empty") && (
              <div className="card">
                <div className="card-header" style={{padding:"12px 16px"}}>
                  <div className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)"}}>
                    <Icon name="check" size={11}/> TASKS
                    {tasks.length > 0 && (
                      <Chip size="sm" tone="data" style={{marginLeft:6}}>
                        {tasks.filter(t => t.status !== "closed").length} open · {tasks.length} total
                      </Chip>
                    )}
                  </div>
                  {me.is_officer && current.status !== "resolved" && current.status !== "closed" && (
                    <button className="btn" onClick={() => setModal("add_task")}>
                      <Icon name="plus" size={12}/> Add task
                    </button>
                  )}
                </div>
                <div style={{padding: tasks.length === 0 ? 16 : 0}}>
                  {tasks.length === 0 && (
                    <div className="t-bodysm muted" style={{fontStyle:"italic"}}>
                      No tasks yet.
                      {me.is_officer && " Use Add task to scope the work."}
                    </div>
                  )}
                  {tasks.map(t => {
                    const isMine = me.username && t.assigned_to === me.username;
                    const canTransition = isMine || me.is_officer;
                    const statusTone = t.status === "closed" ? "neutral"
                      : t.status === "in_progress" ? "update" : "data";
                    return (
                      <div key={t.id} style={{
                        padding: "10px 16px",
                        borderTop: "1px solid var(--neutral-200)",
                        display: "flex", alignItems: "flex-start", gap: 8,
                      }}>
                        <div style={{flex: 1, minWidth: 0}}>
                          <div className="t-bodysm" style={{fontWeight: 500, color: "var(--neutral-900)"}}>
                            {t.title}
                          </div>
                          {t.description && (
                            <div className="t-bodysm muted" style={{marginTop: 2, fontSize: 12}}>
                              {t.description}
                            </div>
                          )}
                          <div className="t-bodysm muted" style={{fontSize: 11, marginTop: 4}}>
                            {t.assigned_to}{isMine && " · you"}
                            {t.closed_at && ` · closed by ${t.closed_by || "—"}`}
                          </div>
                        </div>
                        <div style={{display: "flex", flexDirection: "column", gap: 4, alignItems: "flex-end"}}>
                          <Chip size="sm" tone={statusTone}>
                            {t.status === "in_progress" ? "in progress" : t.status}
                          </Chip>
                          {canTransition && t.status !== "closed" && (
                            <div style={{display: "flex", gap: 4}}>
                              {t.status === "open" && (
                                <button className="btn ghost" disabled={busy}
                                        title="Mark in progress"
                                        onClick={() => transitionTask(t.id, "in_progress")}
                                        style={{padding: "2px 6px", fontSize: 11}}>
                                  Start
                                </button>
                              )}
                              <button className="btn ghost" disabled={busy}
                                      title="Close task"
                                      onClick={() => transitionTask(t.id, "closed")}
                                      style={{padding: "2px 6px", fontSize: 11}}>
                                Close
                              </button>
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* US-S21-003c — Timeline. Synthetic chronology built from
                the grievance fields + tasks state. Surfaces work-log
                progression inline rather than only via the audit drawer. */}
            {(dataSource === "live" || dataSource === "live-empty") && (
              <div className="card">
                <div style={{padding: "12px 16px"}}>
                  <div className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)", marginBottom: 8}}>
                    <Icon name="history" size={11}/> TIMELINE
                  </div>
                  <ul style={{margin: 0, padding: 0, listStyle: "none", borderLeft: "2px solid var(--neutral-200)"}}>
                    {_grmTimelineFor(current, tasks).map((ev, i) => (
                      <li key={i} style={{padding: "6px 0 6px 14px", position: "relative"}}>
                        <span style={{
                          position: "absolute", left: -5, top: 10,
                          width: 8, height: 8, borderRadius: 4,
                          background: `var(--accent-${ev.tone || "data"})`,
                        }}/>
                        <div className="t-bodysm" style={{color: "var(--neutral-900)", fontWeight: 500}}>
                          {ev.label}
                        </div>
                        <div className="t-bodysm muted" style={{fontSize: 11}}>
                          {ev.detail && <>{ev.detail} · </>}
                          {ev.at}
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            )}

            {/* Per-row actions */}
            <div className="card">
              <div style={{padding:"12px 16px"}}>
                <div className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)", marginBottom:8}}>ACTIONS</div>
                <div className="col gap-2">
                  {!current.assigned_to && (
                    <button className="btn" onClick={() => setModal("assign")}>
                      <Icon name="user" size={13}/> Assign to me
                    </button>
                  )}
                  {current.status !== "resolved" && current.status !== "closed" && current.tier !== "l4_nsr_unit" && (
                    <button className="btn" onClick={() => setModal("escalate")}>
                      <Icon name="arrowUp" size={13}/> Escalate one tier
                    </button>
                  )}
                  {current.status !== "resolved" && current.status !== "closed" && (() => {
                    // US-S21-003 — resolve is gated by every task being closed.
                    const openTasks = tasks.filter(t => t.status !== "closed").length;
                    const disabled = openTasks > 0 && (dataSource === "live" || dataSource === "live-empty");
                    return (
                      <button className="btn primary"
                              disabled={disabled}
                              title={disabled ? `${openTasks} task(s) still open — close them first` : undefined}
                              onClick={() => setModal("resolve")}>
                        <Icon name="check" size={13}/> Resolve with narrative
                        {disabled && <span style={{fontSize: 11, opacity: 0.8}}> · {openTasks} open task(s)</span>}
                      </button>
                    );
                  })()}
                  {current.status === "resolved" && (
                    <button className="btn primary" onClick={() => setModal("close")}>
                      <Icon name="lock" size={13}/> Close grievance
                    </button>
                  )}
                  {current.category === "data_correction" && current.status !== "closed" && (
                    <button className="btn" onClick={() => onNavigate?.(
                      "upd",
                      // The real linked_change_request_id comes from
                      // Grievance.linked_change_request_id; the mock
                      // doesn't carry it so we generate a stable
                      // pseudo-id from the grievance id.
                      { changeRequestId: `01HXYUPD${current.id.slice(-16)}` },
                    )}>
                      <Icon name="edit" size={13}/> Open linked UPD
                    </button>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Modal stack — wired to canned reason lists from the service guards.
          ReasonModal in components.jsx expects open + reasonOptions +
          onClose + onConfirm({reason, note}); the chosen reason is
          forwarded as `reason` (escalate / close) or `narrative`
          (resolve) into the action body. */}
      <ReasonModal
        open={modal === "escalate"}
        title="Escalate to next tier"
        intent="update"
        recordLabel={current?.id}
        reasonOptions={reasonsEscalate}
        onClose={() => setModal(null)}
        onConfirm={({ reason, note }) => fire("escalate", {
          body: { reason: [reason, note].filter(Boolean).join(" — ") },
        })}/>

      <ReasonModal
        open={modal === "resolve"}
        title="Resolve grievance"
        intent="success"
        recordLabel={current?.id}
        reasonOptions={reasonsResolve}
        onClose={() => setModal(null)}
        onConfirm={({ reason, note }) => fire("resolve", {
          body: { narrative: [reason, note].filter(Boolean).join(" — ") || reason || "resolved via console" },
        })}/>

      <ReasonModal
        open={modal === "close"}
        title={selection.size > 1 ? `Close ${selection.size} grievances` : "Close grievance"}
        recordLabel={current?.id}
        reasonOptions={reasonsClose}
        onClose={() => setModal(null)}
        onConfirm={({ reason, note }) => fire("close", {
          body: { narrative: [reason, note].filter(Boolean).join(" — ") },
        })}/>

      <Modal
        open={modal === "assign"}
        title="Assign grievance(s)"
        onClose={() => setModal(null)}
        footer={<>
          <button className="btn" onClick={() => setModal(null)}>Cancel</button>
          <button className="btn btn-primary" disabled={!assignee || busy}
                  onClick={() => fire("assign", {
                    body: { assigned_to: assignee },
                  })}>
            {busy ? "Assigning…" : "Assign"}
          </button>
        </>}>
        <div className="t-bodysm" style={{marginBottom:12}}>
          Assign {selection.size > 1 ? `${selection.size} grievances` : "this grievance"} to:
        </div>
        <select className="field-select" style={{width:"100%"}}
                value={assignee}
                onChange={(e) => setAssignee(e.target.value)}>
          <option value="">— pick an assignee —</option>
          <option value="Adong Florence · CDO Tapac">Adong Florence · CDO Tapac</option>
          <option value="Akiteng Lillian · Parish Chief, Nakiloro">Akiteng Lillian · Parish Chief, Nakiloro</option>
          <option value="Twikirize J. · District M&E">Twikirize J. · District M&amp;E</option>
          <option value="NSR Unit duty officer">NSR Unit duty officer</option>
        </select>
      </Modal>

      {/* US-S21-003c — Open Grievance modal. POSTs to
          /api/v1/grm/grievances/; the server stamps SLA + audit. */}
      <Modal
        open={modal === "open_grievance"}
        title="Open a new grievance"
        onClose={() => setModal(null)}
        footer={<>
          <button className="btn" onClick={() => setModal(null)}>Cancel</button>
          <button className="btn btn-primary" disabled={busy}
                  onClick={submitOpenGrievance}>
            {busy ? "Opening…" : "Open grievance"}
          </button>
        </>}>
        <div className="col gap-2">
          <label className="t-cap" style={{fontWeight:600}}>CATEGORY</label>
          <select className="field-select" style={{width:"100%"}}
                  value={openForm.category}
                  onChange={(e) => setOpenForm({...openForm, category: e.target.value})}>
            {Object.entries(GRM_CATEGORIES).map(([code, label]) => (
              <option key={code} value={code}>{label}</option>
            ))}
          </select>

          <label className="t-cap" style={{fontWeight:600, marginTop:8}}>TIER</label>
          <select className="field-select" style={{width:"100%"}}
                  value={openForm.tier}
                  onChange={(e) => setOpenForm({...openForm, tier: e.target.value})}>
            {Object.entries(GRM_TIERS).map(([code, t]) => (
              <option key={code} value={code}>{t.short} · {t.label} ({t.sla_hours}h SLA)</option>
            ))}
          </select>

          <label className="t-cap" style={{fontWeight:600, marginTop:8}}>NARRATIVE</label>
          <textarea className="field-text"
                    style={{width:"100%", minHeight:80, padding:8, fontFamily:"inherit"}}
                    placeholder="Describe the grievance. What happened, when, who reported it."
                    value={openForm.description}
                    onChange={(e) => setOpenForm({...openForm, description: e.target.value})}/>

          <div className="row gap-2" style={{marginTop:8}}>
            <div style={{flex:1}}>
              <label className="t-cap" style={{fontWeight:600}}>HOUSEHOLD ID <span className="muted">(optional)</span></label>
              <input className="field-text" type="text"
                     style={{width:"100%", padding:6, fontFamily:"ui-monospace, monospace", fontSize:12}}
                     placeholder="01HXY7K3B2N9PVQE4M6FZRWS18"
                     value={openForm.household_id}
                     onChange={(e) => setOpenForm({...openForm, household_id: e.target.value})}/>
            </div>
            <div style={{flex:1}}>
              <label className="t-cap" style={{fontWeight:600}}>MEMBER ID <span className="muted">(optional)</span></label>
              <input className="field-text" type="text"
                     style={{width:"100%", padding:6, fontFamily:"ui-monospace, monospace", fontSize:12}}
                     value={openForm.member_id}
                     onChange={(e) => setOpenForm({...openForm, member_id: e.target.value})}/>
            </div>
          </div>

          <label className="t-cap" style={{fontWeight:600, marginTop:8}}>REPORTER</label>
          <div className="row gap-2">
            <input className="field-text" type="text" placeholder="Name"
                   style={{flex:2, padding:6}}
                   value={openForm.reporter_name}
                   onChange={(e) => setOpenForm({...openForm, reporter_name: e.target.value})}/>
            <input className="field-text" type="text" placeholder="Phone (+256…)"
                   style={{flex:2, padding:6}}
                   value={openForm.reporter_phone}
                   onChange={(e) => setOpenForm({...openForm, reporter_phone: e.target.value})}/>
            <input className="field-text" type="text" placeholder="Relationship"
                   style={{flex:1, padding:6}}
                   value={openForm.reporter_relationship}
                   onChange={(e) => setOpenForm({...openForm, reporter_relationship: e.target.value})}/>
          </div>
        </div>
      </Modal>

      {/* US-S21-003c — Add Task modal. Officer-only POSTs to
          /api/v1/grm/tasks/. The new task lands in OPEN status. */}
      <Modal
        open={modal === "add_task"}
        title={current ? `Add task to ${current.id.slice(0, 12)}…` : "Add task"}
        onClose={() => setModal(null)}
        footer={<>
          <button className="btn" onClick={() => setModal(null)}>Cancel</button>
          <button className="btn btn-primary" disabled={busy || !taskForm.title || !taskForm.assigned_to}
                  onClick={submitAddTask}>
            {busy ? "Adding…" : "Add task"}
          </button>
        </>}>
        <div className="col gap-2">
          <label className="t-cap" style={{fontWeight:600}}>TITLE</label>
          <input className="field-text" type="text"
                 style={{width:"100%", padding:6}}
                 placeholder="e.g. Visit reporter and verify NIN"
                 value={taskForm.title}
                 onChange={(e) => setTaskForm({...taskForm, title: e.target.value})}/>

          <label className="t-cap" style={{fontWeight:600, marginTop:8}}>DESCRIPTION</label>
          <textarea className="field-text"
                    style={{width:"100%", minHeight:60, padding:8, fontFamily:"inherit"}}
                    placeholder="What needs to happen and how the assignee should report back."
                    value={taskForm.description}
                    onChange={(e) => setTaskForm({...taskForm, description: e.target.value})}/>

          <label className="t-cap" style={{fontWeight:600, marginTop:8}}>ASSIGNED TO</label>
          <input className="field-text" type="text"
                 style={{width:"100%", padding:6, fontFamily:"ui-monospace, monospace"}}
                 placeholder="username (e.g. parish-chief-3)"
                 value={taskForm.assigned_to}
                 onChange={(e) => setTaskForm({...taskForm, assigned_to: e.target.value})}/>
          <div className="t-bodysm muted" style={{fontSize:11}}>
            The assignee will see this grievance in their queue until the
            task is closed. Resolve is blocked while any task is open.
          </div>
        </div>
      </Modal>

      <AuditDrawer open={auditOpen} events={auditEvents} onClose={() => setAuditOpen(false)}/>
      {toast && <Toast message={toast} onDone={() => setToast("")}/>}
    </div>
  );
};
