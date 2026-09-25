/* global React, Icon, Chip, PageHeader, AuditDrawer, Modal, ReasonModal, ActionBar, Toast,
   navCountsChanged, OpenGrievanceModal,
   useWideView, WideViewButtons, WideShell */
// NSR MIS — GRM workbench (US-S8-006 / US-S21-002 live wiring).
// Parity-or-better with the Django admin from S4-005 + S6-001: list
// + SLA badge + bulk assign/escalate/resolve/close. As of US-S21-002
// the screen fetches /api/v1/grm/grievances/ on mount and routes
// every action through the matching POST endpoint. Mock data below
// is the offline fallback for design previews.

const { useState: useStateGrm, useMemo: useMemoGrm, useEffect: useEffectGrm } = React;

const _grmDownloadCsv = (filename, rows) => {
  const csv = rows.map(row => row.map(v => `"${String(v ?? "").replace(/"/g, '""')}"`).join(",")).join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
};

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
// True when the case will accept `action`.
//
// `allowed_actions` is null for a row that did not come from the API —
// the offline preview — and there the console must not start refusing
// things on its own authority, so an unknown answer is yes. When the
// server HAS answered, its answer is the answer.
const _grmAllows = (row, action) => {
  if (!row) return false;
  if (!row.allowed_actions) return true;
  return row.allowed_actions.includes(action);
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
    // Dropped here until now, so `current.linked_change_request_id`
    // was always undefined: the case panel never offered the link to
    // an update that existed, and kept offering to open a NEW one —
    // a second DRAFT on every click.
    linked_change_request_id: g.linked_change_request_id || "",
    // What the case will currently accept, from the server's own state
    // machine (apps/grievance/visibility.allowed_actions). Carried so
    // the console does not keep a second copy of the rules and offer a
    // button the server is going to refuse.
    allowed_actions: g.allowed_actions || null,
  };
};

// GRM_CATEGORIES and GRM_TIERS now live in
// v0.1/data/grm-vocabulary.jsx — screens-household.jsx had its own
// copies under different labels, so the same grievance read
// differently depending on which screen raised it.

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
// GRM_MOCK_ROWS removed — it was fabricated records that nothing rendered.
// See docs/console_mock_data_audit.md.
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
// An audit row's action, in the words the chain uses. `action` is the
// verb ("create" / "update"); `reason` carries what it was, because the
// service layer writes it there ("assigned", "escalated: ...",
// "resolved", "closed").
const _grmAuditLabel = (e) => {
  const reason = (e.reason || "").toLowerCase();
  if (e.action === "create" && e.entity_type === "grievance") return "opened the grievance";
  if (e.entity_type === "grievance.task") return e.action === "create" ? "added a task" : "moved a task";
  if (e.entity_type === "grievance.comment") return "added a note";
  if (reason.startsWith("assigned")) return "assigned it";
  if (reason.startsWith("escalated")) return "escalated it";
  if (reason.startsWith("resolved")) return "resolved it";
  if (reason.startsWith("closed")) return "closed it";
  if (e.action === "list_read" || e.action === "read") return "viewed it";
  return e.action;
};

// Fallback detail when an event carries no reason — say what moved
// rather than showing an empty line.
const _grmFieldSummary = (changes) => {
  if (!changes || typeof changes !== "object") return "";
  return Object.entries(changes)
    .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(" \u2192 ") : v}`)
    .join(" · ");
};


// The case timeline, read from the audit chain.
//
// This used to be reconstructed from the grievance's CURRENT state,
// which meant it was wrong in three separate ways at once. "Assigned
// to X" was stamped with `opened_at` — the time the case was RAISED,
// not the time it was handed over. Escalated, Resolved and Closed
// carried the literal string "—" where a timestamp belongs, because
// the row it was reading from does not record when those happened.
// And an escalation was annotated "Tier reset · SLA window restarted"
// whether or not that is what occurred.
//
// The order was the order this function happened to push things in,
// so a task created before an assignment appeared after it.
//
// The chain has all of it, with times, in the order it happened.
const _grmTimelineTone = (e) => {
  const reason = (e.reason || "").toLowerCase();
  if (e.entity_type === "grievance.task") return "data";
  if (e.entity_type === "grievance.comment") return "neutral";
  if (e.entity_type === "change_request") return "update";
  if (reason.startsWith("escalated")) return "update";
  if (reason.startsWith("resolved") || reason.startsWith("closed")) return "eligibility";
  if (reason.startsWith("assigned")) return "user";
  return "data";
};

const _grmTimelineFor = (auditRows) => (auditRows || [])
  // Reads are access, not case history. They belong in the audit
  // drawer, which shows the chain unfiltered; a timeline of who
  // glanced at the case tells the handler nothing about the case.
  .filter(e => e.action !== "read" && e.action !== "list_read")
  .map(e => ({
    label: `${_grmAuditLabel(e)} — ${e.actor_id || "unknown"}`,
    detail: e.reason || _grmFieldSummary(e.field_changes),
    at: _grmFmtTime(e.occurred_at),
    tone: _grmTimelineTone(e),
  }));


// Quick filters. Each predicate takes the row AND the signed-in
// username, because two of these say "me" and one of them used to mean
// nothing of the sort: "Assigned to me" tested `assigned_to !== ""`,
// which is assigned to ANYONE. On a queue where most cases have an
// owner it matched nearly all of them, and the count on the chip —
// computed from the same predicate — agreed with the wrong list, so
// the two numbers never disagreed in a way that would show it up.
//
// An empty `me` (no session, or the file:// preview) matches nothing
// rather than everything: with no one signed in, no case is mine.
const QUICK_FILTERS_GRM = [
  { id: "breach",    label: "Past SLA (any tier)",       icon: "alert",      tone: "danger",  predicate: r => r.hours_to_breach < 0 && r.status !== "resolved" && r.status !== "closed" },
  { id: "open_l1",   label: "Open L1 — Parish Chief",    icon: "users",      tone: "data",    predicate: r => r.tier === "l1_parish_chief" && r.status === "open" },
  // Was "Escalated — needs me", which it never checked. It is every
  // escalated case; the label now says that.
  { id: "escalated", label: "Escalated",                 icon: "arrowUp",    tone: "update",  predicate: r => r.status === "escalated" },
  { id: "mine",      label: "Assigned to me",            icon: "user",       tone: "programme", predicate: (r, me) => Boolean(me) && r.assigned_to === me && r.status !== "closed" },
];

const GRMScreen = ({ onNavigate, initialGrievance = null,
                     selectGrievanceId = null }) => {
  // Wide view (ADR-0030). Declared here, above every early return in
  // this component: a hook that some renders skip changes the hook
  // order, which React treats as a different component.
  const wide = useWideView("grm");
  // Live state. allRows is the canonical roster (live or mock); rows
  // is the visible subset after quick-filter. dataSource drives the
  // eyebrow indicator so an operator can see whether they're looking
  // at real data or the offline-preview fallback.
  // Data comes from the API or it is not shown. The screen used to
// initialise from a fabricated fixture and only replace it if the fetch
// succeeded, so a slow or failing API left an operator reading invented
// people — names, NINs and ULIDs — with only a small "mock" chip to say
// so. It now starts empty and says which state it is in.
  const [allRows, setAllRows] = useStateGrm([]);
  const [dataSource, setDataSource] = useStateGrm("loading");
  const [selectedRow, setSelectedRow] = useStateGrm(null);
  const [selection, setSelection] = useStateGrm(new Set());
  const [quickFilter, setQuickFilter] = useStateGrm(null);
  // 'assign' | 'escalate' | 'resolve' | 'close' | 'open_grievance' | 'add_task'
  const [modal, setModal] = useStateGrm(null);
  const [assignee, setAssignee] = useStateGrm(null);
  const [taskAssignee, setTaskAssignee] = useStateGrm(null);
  // Closing a task asks what was done. The note becomes a comment on
  // the grievance, so the case has one timeline rather than a thread
  // plus a set of closing notes filed on tasks nobody opens.
  const [closingTask, setClosingTask] = useStateGrm(null);
  const [closingNote, setClosingNote] = useStateGrm("");
  const [comments, setComments] = useStateGrm([]);
  const [commentDraft, setCommentDraft] = useStateGrm("");
  const [busy, setBusy] = useStateGrm(false);
  // What the last bulk action did, per row. A toast cannot carry it:
  // "7/12 succeeded" tells the operator five cases did not move and
  // not which five, so there is nothing to act on. Same shape as the
  // UPD workbench's bulk panel (screens-upd.jsx) rather than a second
  // way of saying the same thing.
  const [bulkResult, setBulkResult] = useStateGrm(null);
  const [caseDrawer, setCaseDrawer] = useStateGrm(false);
  const [auditOpen, setAuditOpen] = useStateGrm(false);
  const [auditRaw, setAuditRaw] = useStateGrm([]);
  const [auditLoading, setAuditLoading] = useStateGrm(false);
  // Bumped after any action, so the timeline shows what just happened
  // rather than the case's history as of when it was selected.
  const [auditReloadKey, setAuditReloadKey] = useStateGrm(0);
  const [toast, setToast] = useStateGrm("");
  // US-S21-003c — tasks for the currently-selected grievance, plus
  // role flag from the /me endpoint. Officer-status drives whether
  // "+ Add task" and "Open grievance" affordances render.
  const [tasks, setTasks] = useStateGrm([]);
  const [me, setMe] = useStateGrm({ username: "", is_officer: false });
  // Form state for the Add-Task modal.
  const [taskForm, setTaskForm] = useStateGrm({
    title: "", description: "", assigned_to: "",
  });

  // Record-detail screens hand off here with their household/member
  // identifiers already bound; the dialog takes them as `initial` and
  // locks the household when there is one. The GRM endpoint remains
  // the single writer, so SLA and audit stamping stay server-side.
  useEffectGrm(() => {
    if (!initialGrievance) return;
    setModal("open_grievance");
  }, [initialGrievance]);

  // Open one specific grievance, by id.
  //
  // "Open in GRM" on the household toast used to navigate to a bare
  // list, leaving the operator to find the row they had just created.
  // When the list came back empty — which it did for every non-officer
  // before the visibility fix — it read as though nothing had been
  // created at all.
  useEffectGrm(() => {
    if (!selectGrievanceId) return;
    setQuickFilter(null);
    setSelectedRow(selectGrievanceId);
  }, [selectGrievanceId]);

  // Locked when the caller supplied the household — the operator is
  // raising this FROM that record, so re-picking it is not a choice
  // they should have to make or be able to get wrong.
  const lockedHousehold = Boolean(
    initialGrievance && initialGrievance.household_id,
  );

  // Refresh the roster from the API. Used on mount + after every
  // successful action. On unreachable API (file:// preview) it
  // marks dataSource so the eyebrow reflects it.
  // Tell the sidebar its grievance badge is out of date.
  //
  // The badge refreshed on a 60-second timer only, so an operator who
  // closed the last open grievance watched it read "1" for up to a
  // minute. The obvious reading of that is that the close did not
  // take. Guarded because the screens also run in the file:// design
  // preview, where the shell that owns the badge is not mounted.
  const badgeStale = () => {
    if (typeof navCountsChanged === "function") navCountsChanged();
  };

  // Refreshing the roster refreshes the badge with it: they count the
  // same thing, and an operator pressing Refresh because a number
  // looked wrong should not be left with the other one stale.
  const refresh = () => {
    badgeStale();
    return fetch(
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
  };

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
  const refreshComments = (grievanceId) => {
    if (!grievanceId) { setComments([]); return Promise.resolve(); }
    return fetch(
      `/api/v1/grm/grievances/${encodeURIComponent(grievanceId)}/comments/`,
      { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(data => { setComments(Array.isArray(data) ? data : (data.results || [])); })
      .catch(() => { setComments([]); });
  };

  const postComment = () => {
    const body = commentDraft.trim();
    if (!body || !current) return;
    setBusy(true);
    fetch(`/api/v1/grm/grievances/${current.id}/comments/`, {
      method: "POST", credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": _grmCsrf(),
        Accept: "application/json",
      },
      body: JSON.stringify({ body }),
    })
      .then(async r => {
        if (r.ok) return r.json();
        const j = await r.json().catch(() => ({ detail: r.status }));
        throw new Error(j.detail || `HTTP ${r.status}`);
      })
      .then(() => {
        setCommentDraft("");
        refreshComments(current.id);
        setAuditReloadKey(k => k + 1);
      })
      .catch(e => setToast(`Comment failed: ${e.message}`))
      .finally(() => setBusy(false));
  };

  useEffectGrm(() => {
    if (dataSource === "live" || dataSource === "live-empty") {
      refreshTasks(selectedRow);
      refreshComments(selectedRow);
    }
    /* eslint-disable-next-line */
  }, [selectedRow, dataSource]);

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
        setAuditReloadKey(k => k + 1);
        badgeStale();
        return refreshTasks(current.id);
      })
      .catch(e => setToast(`Add task failed: ${e.message}`))
      .finally(() => setBusy(false));
  };

  // Transition a task's status (open ↔ in_progress, → closed).
  const transitionTask = (taskId, new_status, note = "") => {
    setBusy(true);
    fetch(`/api/v1/grm/tasks/${taskId}/transition/`, {
      method: "POST", credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": _grmCsrf(),
        Accept: "application/json",
      },
      body: JSON.stringify({ new_status, note }),
    })
      .then(async r => {
        if (r.ok) return r.json();
        const j = await r.json().catch(() => ({ detail: r.status }));
        throw new Error(j.detail || `HTTP ${r.status}`);
      })
      .then(() => {
        refreshTasks(current?.id);
        setAuditReloadKey(k => k + 1);
        // A task transition can close the last one holding a case
        // open, which changes what the badge counts.
        badgeStale();
        // A closing note lands on the grievance thread, so refresh it.
        if (new_status === "closed") refreshComments(current?.id);
      })
      .catch(e => setToast(`Transition failed: ${e.message}`))
      .finally(() => { setBusy(false); setClosingTask(null); });
  };

  // Narrow view shows the panel inline, so a drawer left open in wide
  // view must not follow the operator back.
  useEffectGrm(() => {
    if (!wide.isWide) setCaseDrawer(false);
  }, [wide.isWide]);

  // Load the chain whenever a case is selected.
  //
  // It was gated on the audit drawer being open, because the chain is
  // a click the operator asked for rather than something to fetch for
  // every row they arrow past. Then the case panel's timeline started
  // reading the same events (P3.14), and the timeline is always on
  // screen — so the fetch moved alongside the tasks and comments the
  // panel already loads per case, and the drawer reads what is
  // already there. One request, two consumers.
  //
  // The server-side read event is deduped per case per window, so
  // clicking back and forth does not write a row each time, while a
  // different case is always a different read.
  useEffectGrm(() => {
    if (!selectedRow) { setAuditRaw([]); return; }
    let live = true;
    setAuditLoading(true);
    fetch(`/api/v1/grm/grievances/${selectedRow}/audit/`, {
      credentials: "same-origin", headers: { Accept: "application/json" },
    })
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(data => { if (live) setAuditRaw(data.results || data || []); })
      .catch(() => { if (live) setAuditRaw([]); })
      .finally(() => { if (live) setAuditLoading(false); });
    return () => { live = false; };
  }, [selectedRow, auditReloadKey]);

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
    return def ? allRows.filter(r => def.predicate(r, me.username)) : allRows;
  }, [allRows, quickFilter, me.username]);

  const exportCsv = () => {
    _grmDownloadCsv("grievances.csv", [
      ["id", "category", "tier", "status", "household_id", "member_id", "reporter", "relationship", "assigned_to", "opened_at", "hours_to_breach"],
      ...rows.map(r => [r.id, GRM_CATEGORIES[r.category] || r.category, GRM_TIERS[r.tier]?.label || r.tier, GRM_STATUSES[r.status]?.label || r.status, r.household_id, r.member_id, r.reporter_name, r.relationship, r.assigned_to, r.opened_at, r.hours_to_breach ?? ""]),
    ]);
    setToast(`Exported ${rows.length} grievance row(s).`);
  };

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
  // What a confirmed action will actually touch. One definition, read
  // by fire() and by every dialog's record list, so the dialog cannot
  // name one case while the action changes twelve.
  const targetIds = selection.size > 0
    ? [...selection]
    : current ? [current.id] : [];

  const fire = (kind, opts = {}) => {
    if (dataSource === "offline" || dataSource === "loading") {
      // No live API to write to. The action is acknowledged but NOT
      // persisted, and the toast says so rather than implying success.
      const map = {
        assign:   `${selection.size || 1} grievance(s) assigned. (preview — not persisted)`,
        escalate: `${selection.size || 1} grievance(s) escalated. (preview — not persisted)`,
        resolve:  `Grievance resolved. (preview — not persisted)`,
        close:    `${selection.size || 1} grievance(s) closed. (preview — not persisted)`,
        "open-change-request":
          "Update opened in the Updates Queue. (preview — not persisted)",
      };
      setToast(map[kind] || "Done.");
      setModal(null); setSelection(new Set());
      return;
    }
    // `opts.ids` overrides the selection. "Assign to me" acts on the
    // case in the panel: with rows ticked for a bulk action, falling
    // back to the selection would take one person's case and hand them
    // everything that happened to be ticked.
    const ids = opts.ids || targetIds;
    if (ids.length === 0) {
      setToast("No grievance selected.");
      setModal(null);
      return;
    }
    const body = { actor: "console-operator", ...(opts.body || {}) };
    setBusy(true);
    setBulkResult(null);
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
          // The toast is the headline; the panel below the queue is
          // where the operator finds out WHICH rows refused and why.
          // It used to print the first two reasons with no ids
          // attached, so "7/12 succeeded · grievance is closed" left
          // five cases to find by hand.
          setToast(
            `${ids.length - failures.length} of ${ids.length} done — ` +
            `${failures.length} refused, listed below the queue.`,
          );
        }
        if (failures.length > 0 || ids.length > 1) {
          const failed = new Set(failures.map(f => f.id));
          setBulkResult({
            action: kind,
            ok: ids.filter(id => !failed.has(id)),
            failed: failures,
          });
        }
        // The action just wrote to the chain; the timeline reads it.
        setAuditReloadKey(k => k + 1);
        return refresh();
      })
      .finally(() => {
        setBusy(false);
        setModal(null);
        // An action given its own ids did not read the selection, so it
        // must not clear it: "Assign to me" on the open case would
        // otherwise drop the rows the operator had ticked for a bulk
        // action they had not performed yet.
        if (!opts.ids) setSelection(new Set());
        setAssignee("");
      });
  };

  // Who the assign modal may offer.
  //
  // The picker searched the whole user directory — every account,
  // active or not, whatever their role or area. An L3 District case
  // could be handed to an enumerator in another sub-region: someone
  // with neither the authority to decide it nor the scope to open it.
  // For one case the server can answer this exactly, so ask it.
  //
  // A bulk selection spanning different tiers or households has no
  // single answer; the rule is enforced per case on submit and the
  // result reports what it refused, so the modal says so rather than
  // pretending to a list it cannot compute.
  const assignTargets = selection.size > 0
    ? allRows.filter(r => selection.has(r.id))
    : (current ? [current] : []);
  const oneKindOfTarget = assignTargets.length > 0 && assignTargets.every(
    r => r.tier === assignTargets[0].tier
      && r.household_id === assignTargets[0].household_id,
  );
  const assigneeEndpoint = oneKindOfTarget
    ? `/api/v1/grm/grievances/${assignTargets[0].id}/assignable/`
    : undefined;

  // Real audit-chain events for this grievance.
  //
  // This block used to fabricate them from the CURRENT state: "Via
  // parish channel" for any case with a phone, "Tier L2 window from
  // open" on a case opened at L1, "System GRM escalated tier, SLA
  // breach auto-escalator, 48h later" on an escalation a person had
  // just performed by hand, and audit ids of the form
  // A-2026-05-<last two chars of the grievance id>-001. None of it had
  // happened. The chain is the record; it is read, not reconstructed.
  // How many of the selected cases would actually accept each bulk
  // action, from allowed_actions.
  //
  // Bulk Close was offered whenever anything was ticked, and close
  // only applies to a RESOLVED case — so on a queue of open cases the
  // button was live, the dialog asked for a reason and a note, and
  // every row came back refused. The button now says how many it can
  // move, and disables when that is none.
  const selectedRows = allRows.filter(r => selection.has(r.id));
  const bulkEligible = (action) =>
    selectedRows.filter(r => _grmAllows(r, action)).length;

  // What to warn about in a bulk dialog: how many of the ticked rows
  // the server is going to refuse. The toolbar button says it too,
  // but the dialog is where the operator has stopped to read.
  const bulkNotice = (action) => {
    if (selection.size === 0) return null;
    const skipped = selection.size - bulkEligible(action);
    if (skipped <= 0) return null;
    return `${skipped} of the ${selection.size} selected will be refused — `
      + "they are listed below the queue afterwards, with the reason.";
  };

  const timeline = _grmTimelineFor(auditRaw);
  const auditEvents = (auditRaw || []).map(e => ({
    who: e.actor_id || "unknown",
    action: _grmAuditLabel(e),
    detail: e.reason || _grmFieldSummary(e.field_changes),
    time: _grmFmtTime(e.occurred_at),
    audit: (e.self_hash || e.id || "").slice(0, 12),
    tone: e.actor_kind === "system" ? "system" : "user",
  }));

  // The case panel, hoisted so wide view can put it somewhere
  // other than under the list.
  //
  // In wide view the split grid collapses to a single column so
  // the list gets the whole width — and the panel, still the
  // second grid child, went below it. With a full queue that is
  // several screens down: the panel was reported missing, and for
  // any practical purpose it was. Wide view puts it in a drawer
  // instead, which is where a 380px rail belongs when the thing
  // beside it is 1600px wide.
  const casePanel = current ? (
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

              {current.household_id ? (
                <>
                  <div className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)", margin:"14px 0 6px"}}>SUBJECT</div>
                  <button type="button" className="link-btn t-bodysm"
                          style={{padding:0, textAlign:"left"}}
                          onClick={() => onNavigate && onNavigate("household", { householdId: current.household_id })}>
                    Open household {current.household_id.slice(0, 12)}…
                  </button>
                  {current.member_id && <div className="t-mono muted" style={{fontSize:11, marginTop:2}}>member: {current.member_id.slice(0,18)}…</div>}
                </>
              ) : (
                <>
                  <div className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)", margin:"14px 0 6px"}}>SUBJECT</div>
                  <div className="t-bodysm muted">Not about a specific household.</div>
                </>
              )}

              {/* GRM -> UPD. SAD §4.4: a grievance that resolves to a
                  data correction opens a linked update. The service
                  has done this since US-S21 and nothing exposed it,
                  so the Updates Queue and the grievance that caused
                  the update were two screens with no path between
                  them. */}
              {current.category === "data_correction" && (
                <>
                  <div className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)", margin:"14px 0 6px"}}>DATA UPDATE</div>
                  {current.linked_change_request_id ? (
                    <button type="button" className="link-btn t-bodysm"
                            style={{padding:0, textAlign:"left"}}
                            onClick={() => onNavigate && onNavigate("upd", { changeRequestId: current.linked_change_request_id })}>
                      Open update {current.linked_change_request_id.slice(0, 12)}… in the Updates Queue
                    </button>
                  ) : _grmAllows(current, "open_change_request") ? (
                    <>
                      <button className="btn sm" disabled={busy}
                              onClick={() => fire("open-change-request", {
                                ids: [current.id], body: {},
                              })}>
                        Open an update from this grievance
                      </button>
                      <div className="t-cap muted" style={{marginTop:4}}>
                        Creates a DRAFT in the Updates Queue, linked both ways.
                        Approval still happens there.
                      </div>
                    </>
                  ) : (
                    <div className="t-bodysm muted">
                      Name the household first — an update has to be
                      about a record.
                    </div>
                  )}
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

          {/* The running thread. A grievance is worked over days or
              weeks; before this it carried the intake narrative and,
              eventually, a resolution, with nothing in between — so
              the resolution had to summarise from memory. Comments
              are append-only: a correction is another comment. */}
          {(dataSource === "live" || dataSource === "live-empty") && (
            <div className="card">
              <div className="card-header" style={{padding:"12px 16px"}}>
                <div className="t-cap" style={{fontWeight:600, color:"var(--neutral-700)"}}>
                  <Icon name="message" size={11}/> CASE NOTES
                  {comments.length > 0 && (
                    <Chip size="sm" tone="data" style={{marginLeft:6}}>{comments.length}</Chip>
                  )}
                </div>
              </div>
              <div style={{padding:"12px 16px"}}>
                {comments.length === 0 && (
                  <div className="t-bodysm muted" style={{fontStyle:"italic", marginBottom:10}}>
                    {_grmAllows(current, "comment")
                      ? <>Nothing recorded yet. Add a note as the case moves —
                          a visit made, a call, a document still missing.</>
                      : <>Nothing was recorded on this case.</>}
                  </div>
                )}
                {comments.map(c => (
                  <div key={c.id} style={{
                    borderLeft: "2px solid var(--neutral-200)",
                    padding: "0 0 0 10px", margin: "0 0 12px",
                  }}>
                    <div className="row gap-2" style={{alignItems:"baseline"}}>
                      <span className="t-bodysm" style={{fontWeight:600}}>{c.author}</span>
                      <span className="t-cap muted">{_grmFmtTime(c.created_at)}</span>
                      {c.kind === "task_closed" && (
                        <Chip size="sm" tone="quality">task closed</Chip>
                      )}
                    </div>
                    <div className="t-bodysm" style={{color:"var(--neutral-800)", whiteSpace:"pre-wrap"}}>
                      {c.body}
                    </div>
                  </div>
                ))}
                {/* A closed case is read-only, its thread included.
                    The composer stayed on screen over an endpoint that
                    now refuses it, which is a box you can type a
                    paragraph into and lose. */}
                {_grmAllows(current, "comment") ? (
                  <>
                    <textarea className="field-text"
                              style={{width:"100%", minHeight:56, padding:8, fontFamily:"inherit"}}
                              placeholder="Add a note — what happened, what is still outstanding."
                              value={commentDraft}
                              onChange={(e) => setCommentDraft(e.target.value)}/>
                    <div className="row gap-2" style={{justifyContent:"flex-end", marginTop:6}}>
                      <button className="btn sm" disabled={busy || !commentDraft.trim()}
                              onClick={postComment}>
                        {busy ? "Saving…" : "Add note"}
                      </button>
                    </div>
                  </>
                ) : (
                  <div className="t-cap muted" style={{
                    marginTop: 4, padding: "8px 10px", borderRadius: 6,
                    background: "var(--neutral-50)",
                    border: "1px solid var(--neutral-200)",
                  }}>
                    <Icon name="lock" size={11}/> This case is closed and
                    read-only. The closing narrative is the last word on
                    it — if there is more to record, raise a new grievance.
                  </div>
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
                {me.is_officer && _grmAllows(current, "add_task") && (
                  <button className="btn" onClick={() => {
                            setTaskAssignee(null);
                            setTaskForm({title:"", description:"", assigned_to:""});
                            setModal("add_task");
                          }}>
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
                  // A closed case is read-only, tasks included — and
                  // the server refuses the transition, so offering it
                  // is offering an error. Reachable only for a task
                  // left open on a case closed out of band; the
                  // lifecycle cannot produce one.
                  const canTransition = (isMine || me.is_officer)
                    && _grmAllows(current, "add_task");
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
                                    onClick={() => { setClosingNote(""); setClosingTask(t); }}
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
                  {timeline.length === 0 && (
                    <li className="t-cap muted" style={{padding:"6px 0 6px 14px"}}>
                      {auditLoading ? "Loading the case history…"
                                    : "No recorded events for this case yet."}
                    </li>
                  )}
                  {timeline.map((ev, i) => (
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
                {/* "Assign to me" opened the assignee picker, which is
                    the one thing it should not have had to do — the
                    operator had already said who. It posts the
                    assignment now, and "Assign…" is the separate
                    button for giving it to somebody else.

                    Both only appear while the case will accept an
                    assignment, from the server's own allowed_actions
                    rather than a second copy of the state machine
                    here. Whether THIS operator may take it is the
                    other half of the question (their role must carry
                    the tier and their scope reach the household) and
                    only the server can answer it; a refusal comes back
                    as the toast, naming what was wrong. */}
                {_grmAllows(current, "assign") && me.username
                  && current.assigned_to !== me.username && (
                  <button className="btn" disabled={busy}
                          onClick={() => fire("assign", {
                            ids: [current.id],
                            body: { assigned_to: me.username },
                          })}>
                    <Icon name="user" size={13}/> Assign to me
                  </button>
                )}
                {_grmAllows(current, "assign") && (
                  <button className="btn" onClick={() => setModal("assign")}>
                    <Icon name="users" size={13}/> Assign…
                  </button>
                )}
                {/* Was `status !== resolved && status !== closed &&
                    tier !== l4_nsr_unit`, which is the server's rule
                    copied out by hand — and a copy drifts. L4 is the
                    top of the ladder, and the server says so. */}
                {_grmAllows(current, "escalate") && (
                  <button className="btn" onClick={() => setModal("escalate")}>
                    <Icon name="arrowUp" size={13}/> Escalate one tier
                  </button>
                )}
                {(() => {
                  // Resolve is the one action with two reasons to be
                  // unavailable, and they deserve different treatment.
                  // The server withholds it both when the status
                  // forbids it and when a task is still open
                  // (US-S21-003); hiding it outright in the second
                  // case would take away the only place that says
                  // WHY. So: hidden when the case is past resolving,
                  // shown and disabled with the count when it is the
                  // open tasks holding it up.
                  const openTasks = tasks.filter(t => t.status !== "closed").length;
                  const allowed = _grmAllows(current, "resolve");
                  const heldByTasks = !allowed && openTasks > 0;
                  if (!allowed && !heldByTasks) return null;
                  return (
                    <button className="btn primary"
                            disabled={!allowed}
                            title={heldByTasks ? `${openTasks} task(s) still open — close them first` : undefined}
                            onClick={() => setModal("resolve")}>
                      <Icon name="check" size={13}/> Resolve with narrative
                      {heldByTasks && <span style={{fontSize: 11, opacity: 0.8}}> · {openTasks} open task(s)</span>}
                    </button>
                  );
                })()}
                {_grmAllows(current, "close") && (
                  <button className="btn primary" onClick={() => setModal("close")}>
                    <Icon name="lock" size={13}/> Close grievance
                  </button>
                )}
                {/* "Open linked UPD" used to synthesise an id —
                    "01HXYUPD" + the tail of the grievance id — and
                    hand it to the Updates Queue, which then showed
                    whatever unrelated CR that matched, or nothing.
                    The DATA UPDATE block above navigates to the real
                    linked_change_request_id and offers to open one
                    when there is none, so this button had no job
                    left but to be wrong. */}
                {current.category === "data_correction"
                  && current.status !== "closed"
                  && current.linked_change_request_id && (
                  <button className="btn" onClick={() => onNavigate?.(
                    "upd", { changeRequestId: current.linked_change_request_id },
                  )}>
                    <Icon name="edit" size={13}/> Open linked UPD
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
  ) : null;

  return (
    <WideShell wide={wide}>
    <div className="page" style={{paddingBottom:0, position:'relative'}}>
      <PageHeader
        eyebrow={dataSource === "live"
          ? "GRM WORKBENCH · US-S8-006 · LIVE"
          : dataSource === "live-empty"
            ? "GRM WORKBENCH · US-S8-006 · live (0 in scope)"
            : dataSource === "offline"
              ? "GRM WORKBENCH · US-S8-006 · COULD NOT LOAD"
              : "GRM WORKBENCH · US-S8-006 · loading…"}
        title={<>Grievance management <Chip>{allRows.filter(r => r.status !== "closed" && r.status !== "resolved").length} active</Chip></>}
        sub={dataSource === "live"
          ? "Live ABAC-scoped data. SLA = 24h L1 / 48h L2 / 72h L3 / 7d L4 (per SAD §11.1)."
          : "Triage, assign, escalate, resolve. SLA = 24h L1 / 48h L2 / 72h L3 / 7d L4 (per SAD §11.1)."}
        right={<>
          <WideViewButtons wide={wide} label="grievances"/>
          <button className="btn" onClick={() => setAuditOpen(true)}><Icon name="history"/> Audit chain</button>
          <button className="btn" onClick={() => refresh()} disabled={busy}>
            <Icon name="refreshCw"/> {busy ? "…" : "Refresh"}
          </button>
          <button className="btn" onClick={exportCsv}><Icon name="download"/> Export CSV</button>
          {me.is_officer && (
            <button className="btn primary" onClick={() => {
                      setAboutHousehold(null);
                      setPickedHousehold(null);
                      setOpenForm(f => ({...f, household_id: "", member_id: ""}));
                      setModal("open_grievance");
                    }}>
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
            // The same predicate the list uses, so the chip cannot
            // count one thing and open another.
            const count = allRows.filter(r => f.predicate(r, me.username)).length;
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

      {/* List + detail split. Wide view stacks them so the list gets the
          full width; the 380px rail is right beside a narrow list and
          wrong beside a wide one. */}
      <div style={wide.isWide
        ? { display: "grid", gridTemplateColumns: "1fr", gap: 16 }
        : { display: "grid", gridTemplateColumns: "1fr 380px", gap: 16 }}>
        <div className="card">
          <div className="card-toolbar">
            <strong className="t-bodysm">
              {selection.size > 0
                ? <>{selection.size} selected of {rows.length}</>
                : <>{rows.length} grievances</>}
            </strong>
            <div style={{flex:1}}/>
            {wide.isWide && current && !caseDrawer && (
              <button className="btn" onClick={() => setCaseDrawer(true)}>
                <Icon name="message" size={13}/> Open case
              </button>
            )}
            {selection.size > 0 && (
              <div className="row gap-2">
                {[
                  { id: "assign", icon: "user", label: "Assign",
                    why: "None of the selected cases will accept an assignment — they are resolved or closed." },
                  { id: "escalate", icon: "arrowUp", label: "Escalate",
                    why: "None of the selected cases can be escalated — they are at L4, resolved, or closed." },
                  { id: "close", icon: "check", label: "Close",
                    why: "Close applies to a resolved case. None of the selected cases is resolved yet." },
                ].map(a => {
                  const n = bulkEligible(a.id);
                  return (
                    <button key={a.id} className="btn"
                            disabled={n === 0}
                            title={n === 0 ? a.why
                              : n < selection.size
                                ? `${selection.size - n} of the ${selection.size} selected will be skipped`
                                : undefined}
                            onClick={() => setModal(a.id)}>
                      <Icon name={a.icon} size={13}/> {a.label}
                      {n > 0 && n < selection.size && (
                        <span style={{fontSize:11, opacity:0.8}}> · {n} of {selection.size}</span>
                      )}
                    </button>
                  );
                })}
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
                onClick={() => { setSelectedRow(r.id); setCaseDrawer(true); }}
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

          {/* What the last bulk action did, row by row. The toast can
              only carry a headline; five refusals inside "7/12
              succeeded" are five cases the operator has to find by
              hand. Same shape as the UPD workbench's panel. */}
          {bulkResult && (
            <div style={{padding:"10px 16px", background:"var(--neutral-50)",
                          borderTop:"1px solid var(--neutral-200)", fontSize:13}}>
              <div className="row gap-2" style={{marginBottom:6}}>
                <Chip tone="data" size="sm">last bulk: {bulkResult.action}</Chip>
                <span className="t-bodysm muted">
                  {bulkResult.ok.length} done · {bulkResult.failed.length} refused
                </span>
                <div style={{flex:1}}/>
                <button className="btn btn-sm" onClick={() => setBulkResult(null)}>
                  Dismiss
                </button>
              </div>
              {bulkResult.failed.length > 0 && (
                <ul style={{margin:"4px 0 0 18px", padding:0,
                             color:"var(--neutral-700)", maxHeight:160,
                             overflowY:"auto"}}>
                  {bulkResult.failed.map(f => (
                    <li key={f.id} style={{padding:"1px 0"}}>
                      <button type="button" className="link-btn t-mono"
                              style={{padding:0, fontSize:12}}
                              onClick={() => { setSelectedRow(f.id); setCaseDrawer(true); }}>
                        {f.id}
                      </button>
                      {" — "}{f.detail}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>

        {!wide.isWide && casePanel}
      </div>

      {/* Wide view: the panel as a drawer over the list, not a strip
          below it. Opened by picking a row, and by the toolbar button
          for when it has been closed. */}
      {wide.isWide && (
        <>
          <div className={`drawer-backdrop ${caseDrawer && current ? "open" : ""}`}
               onClick={() => setCaseDrawer(false)}/>
          <aside className={`drawer ${caseDrawer && current ? "open" : ""}`}
                 aria-hidden={!(caseDrawer && current)}>
            <div className="drawer-header">
              <div>
                <div className="t-cap">CASE DETAIL</div>
                <h3 className="t-h2" style={{margin:"2px 0 0"}}>
                  {current ? GRM_CATEGORIES[current.category] : ""}
                </h3>
              </div>
              <button className="icon-btn" onClick={() => setCaseDrawer(false)}>
                <Icon name="x"/>
              </button>
            </div>
            <div className="drawer-body" style={{padding:12}}>
              {casePanel}
            </div>
          </aside>
        </>
      )}

      {/* Modal stack — wired to canned reason lists from the service guards.
          ReasonModal in components.jsx expects open + reasonOptions +
          onClose + onConfirm({reason, note}); the chosen reason is
          forwarded as `reason` (escalate / close) or `narrative`
          (resolve) into the action body. */}
      <ReasonModal
        open={modal === "escalate"}
        title="Escalate to next tier"
        intent="update"
        confirmLabel="Escalate"
        notice={bulkNotice("escalate")}
        recordLabels={targetIds}
        reasonOptions={reasonsEscalate}
        onClose={() => setModal(null)}
        onConfirm={({ reason, note }) => fire("escalate", {
          body: { reason: [reason, note].filter(Boolean).join(" — ") },
        })}/>

      <ReasonModal
        open={modal === "resolve"}
        title="Resolve grievance"
        intent="success"
        confirmLabel="Resolve"
        recordLabels={targetIds}
        reasonOptions={reasonsResolve}
        onClose={() => setModal(null)}
        onConfirm={({ reason, note }) => fire("resolve", {
          body: { narrative: [reason, note].filter(Boolean).join(" — ") || reason || "resolved via console" },
        })}/>

      <ReasonModal
        open={modal === "close"}
        title={selection.size > 1 ? `Close ${selection.size} grievances` : "Close grievance"}
        confirmLabel={selection.size > 1 ? `Close ${selection.size} grievances` : "Close grievance"}
        notice={bulkNotice("close")}
        recordLabels={targetIds}
        reasonOptions={reasonsClose}
        onClose={() => setModal(null)}
        onConfirm={({ reason, note }) => fire("close", {
          body: { narrative: [reason, note].filter(Boolean).join(" — ") },
        })}/>

      {/* Closing a task asks what was done. A grievance cannot resolve
          until every task is closed, so a task closed with no
          explanation is how a case reaches resolution with nothing
          recorded about the work. */}
      <Modal
        width={520}
        open={Boolean(closingTask)}
        title={closingTask ? `Close task: ${closingTask.title}` : "Close task"}
        onClose={() => !busy && setClosingTask(null)}
        footer={<>
          <button className="btn" disabled={busy}
                  onClick={() => setClosingTask(null)}>Cancel</button>
          <button className="btn btn-primary"
                  disabled={busy || !closingNote.trim()}
                  onClick={() => transitionTask(closingTask.id, "closed", closingNote.trim())}>
            {busy ? "Closing…" : "Close task"}
          </button>
        </>}>
        <div className="t-bodysm" style={{marginBottom:10}}>
          What was done? If the task is being dropped, say why.
        </div>
        <textarea className="field-text"
                  style={{width:"100%", minHeight:90, padding:8, fontFamily:"inherit"}}
                  placeholder="e.g. Visited the reporter on 12 Oct; NIN confirmed against the card."
                  value={closingNote}
                  onChange={(e) => setClosingNote(e.target.value)}/>
        <div className="t-cap muted" style={{marginTop:6}}>
          This goes on the grievance's case notes, under your name.
        </div>
      </Modal>

      <Modal
        width={520}
        open={modal === "assign"}
        title="Assign grievance(s)"
        onClose={() => setModal(null)}
        footer={<>
          <button className="btn" onClick={() => setModal(null)}>Cancel</button>
          <button className="btn btn-primary" disabled={!assignee || busy}
                  onClick={() => fire("assign", {
                    body: { assigned_to: assignee ? assignee.username : "" },
                  })}>
            {busy ? "Assigning…" : "Assign"}
          </button>
        </>}>
        <div className="t-bodysm" style={{marginBottom:12}}>
          Assign {selection.size > 1 ? `${selection.size} grievances` : "this grievance"} to:
        </div>
        {/* The assign modal is a plain Modal, not a ReasonModal, so
            the warning is inline. Same sentence either way. */}
        {bulkNotice("assign") && (
          <div className="t-bodysm" style={{
            marginBottom: 12, padding:"8px 10px", borderRadius:6,
            background:"var(--neutral-50)",
            border:"1px solid var(--accent-quality)",
          }}>
            <Icon name="alert" size={12}/> {bulkNotice("assign")}
          </div>
        )}
        {selection.size > 0 && (
          <ul className="t-mono" style={{
            margin:"0 0 12px", padding:"6px 8px", listStyle:"none",
            maxHeight:110, overflowY:"auto", fontSize:11.5,
            border:"1px solid var(--neutral-200)", borderRadius:4,
            background:"var(--neutral-50)", color:"var(--neutral-900)",
          }}>
            {targetIds.map(id => <li key={id} style={{padding:"1px 0"}}>{id}</li>)}
          </ul>
        )}
        {/* This was a <select> of four invented people — "Adong
            Florence · CDO Tapac" and friends. None of them had an
            account, so the string went into assigned_to and the
            grievance sat with nobody working it. The server now
            refuses an assignee that is not an active MIS user, and
            this searches the real directory. */}
        <UserPicker
          value={assignee} onChange={setAssignee}
          endpoint={assigneeEndpoint}
          emptyHint={oneKindOfTarget
            ? "Nobody holds this tier's role with access to this household. Escalate, or grant the scope first."
            : "No users match."}/>
        {oneKindOfTarget ? (
          <div className="t-cap muted" style={{marginTop:6}}>
            Showing the people whose role carries this tier and whose area
            covers the household.
          </div>
        ) : (
          <div className="t-cap muted" style={{marginTop:6}}>
            These grievances are at different tiers or about different
            households, so one eligible list cannot be shown. Each
            assignment is checked on submit and any that are refused are
            listed back.
          </div>
        )}
        {assignee && !assignee.email && (
          <div className="t-cap muted" style={{marginTop:8}}>
            {assignee.display_name || assignee.username} has no email on
            file, so they will not receive the assignment alert. The
            grievance will still appear in their queue.
          </div>
        )}
      </Modal>

      {/* One dialog, shared with the household and member screens
          (v0.1/components/open-grievance.jsx). This screen's own copy
          could not name a MEMBER, so a complaint about one person in a
          household of nine was filed against the household. */}
      <OpenGrievanceModal
        open={modal === "open_grievance"}
        onClose={() => setModal(null)}
        household={lockedHousehold ? {
          id: initialGrievance.household_id,
          label: (initialGrievance.household || {}).head
            || initialGrievance.household_label
            || "The record this was raised from",
        } : null}
        initial={initialGrievance || null}
        onOpened={(g) => {
          setToast(`Grievance ${g.id.slice(0, 8)}… opened.`);
          refresh().then(() => setSelectedRow(g.id));
        }}/>

      {/* US-S21-003c — Add Task modal. Officer-only POSTs to
          /api/v1/grm/tasks/. The new task lands in OPEN status. */}
      <Modal
        width={560}
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
          <UserPicker
                 value={taskAssignee}
                 endpoint={current
                   ? `/api/v1/grm/grievances/${current.id}/assignable/`
                   : undefined}
                 emptyHint="Nobody holds this tier's role with access to this household."
                 onChange={(u) => {
                   setTaskAssignee(u);
                   setTaskForm({...taskForm, assigned_to: u ? u.username : ""});
                 }}/>
          <div className="t-bodysm muted" style={{fontSize:11}}>
            The assignee will see this grievance in their queue until the
            task is closed. Resolve is blocked while any task is open.
          </div>
        </div>
      </Modal>

      <AuditDrawer open={auditOpen} events={auditEvents} onClose={() => setAuditOpen(false)}/>
      {toast && <Toast message={toast} onDone={() => setToast("")}/>}
    </div>
    </WideShell>
  );
};
