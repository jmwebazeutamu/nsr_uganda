/* global React, Icon, Chip, PageHeader, KPI, useApi, nsrApi */
// NSR MIS — Admin · Reference data · Choice lists
// ===========================================================
// Versioned code-lists used by every questionnaire and downstream
// report. Each `list_name` (relationship, marital_status, …) has
// many versions; one is ACTIVE at a time. Same lifecycle shape as
// DqaRule + PMTModelVersion + DdupModelVersion: DRAFT →
// PENDING_APPROVAL → ACTIVE → RETIRED, with REJECTED as a side
// terminal. AC-CHOICELIST-NO-SELF-APPROVE applies (mirrors DQA).
//
// Maps to:
//   apps.reference_data.models.ChoiceList   (versioned header)
//   apps.reference_data.models.ChoiceOption (options inside a version)
//   apps.reference_data.services            (submit / approve / retire)
//   apps.security.audit                     (lifecycle events)

const { useState: useStateCL, useMemo: useMemoCL, useEffect: useEffectCL, useCallback: useCallbackCL } = React;

/* ===========================================================
   Sample data
   =========================================================== */
const CL_LIST_STATUS_TONE = {
  draft: "quality",
  pending_approval: "update",
  active: "data",
  retired: "neutral",
  rejected: "danger",
};
const CL_LIST_STATUS_LABEL = {
  draft: "Draft",
  pending_approval: "Pending approval",
  active: "Active",
  retired: "Retired",
  rejected: "Rejected",
};

// CL_LISTS, CL_OPTIONS_EDU and CL_VERSIONS_EDU removed.
//
// They were the fallback whenever the admin refdata API was unreachable,
// and between them they invented: eighteen choice lists with version
// numbers, option counts and "last updated" dates; an education-level
// option set that rendered under whichever list the operator had opened;
// and a version history whose v4 and v3 carried approvals by
// "Director General · UBOS" on stated dates. Reference-data approvals are
// governance records. Showing ones that were never given, on the screen
// an administrator uses to check them, is the most misleading thing this
// file could have done. See docs/console_mock_data_audit.md.

/* ===========================================================
   Live data overlay — project /api/v1/admin/refdata/choice-lists/
   onto the shape the JSX below renders. When the API isn't reachable
   this returns null and the screen reports that, rather than rendering
   a fixture.
   =========================================================== */
const _projectChoiceLists = (results) => {
  if (!Array.isArray(results) || results.length === 0) return null;
  return results.map(r => ({
    listName: r.list_name,
    label: r.list_name.replace(/_/g, " "),
    activeVersion: r.active_version,
    draftVersion: r.draft_version,
    optionsCount: r.options_count,
    cascading: false,
    lastUpdated: r.last_updated ? r.last_updated.slice(0, 10) : "",
    uses: r.uses || [],
    pii: !!r.is_pii_classified,
  }));
};

/* ===========================================================
   Choice lists — top-level
   =========================================================== */
const AdminChoiceListsScreen = () => {
  // Live overlay: fetch once on mount, fall back to mocks on error.
  const [resp] = (typeof useApi === "function")
    ? useApi("/api/v1/admin/refdata/choice-lists/")
    : [null];
  // eslint-disable-next-line no-shadow
  // No fixture fallback: an unreachable API yields an empty list and the
  // screen says so, rather than eighteen lists that do not exist.
  const CL_LISTS_LIVE = _projectChoiceLists(resp && resp.results) || [];

  const [view, setView] = useStateCL("list"); // list | detail
  const [selected, setSelected] = useStateCL(null);
  // Carries the live meta row through to the detail screen so it can
  // render the correct list's badges and options.
  const [selectedMeta, setSelectedMeta] = useStateCL(null);

  const [q, setQ] = useStateCL("");
  const [piiFilter, setPiiFilter] = useStateCL("");
  const [statusFilter, setStatusFilter] = useStateCL("");

  const rows = useMemoCL(() => CL_LISTS_LIVE.filter(l => {
    if (q && !(l.listName.includes(q.toLowerCase()) || l.label.toLowerCase().includes(q.toLowerCase()))) return false;
    if (piiFilter === "pii" && !l.pii) return false;
    if (piiFilter === "nonpii" && l.pii) return false;
    if (statusFilter === "draft" && !l.draftVersion) return false;
    return true;
  }), [q, piiFilter, statusFilter, CL_LISTS_LIVE]);

  const total = CL_LISTS_LIVE.length;
  const drafts = CL_LISTS_LIVE.filter(l => l.draftVersion).length;
  const piiCount = CL_LISTS_LIVE.filter(l => l.pii).length;
  const totalOptions = CL_LISTS_LIVE.reduce((a, l) => a + l.optionsCount, 0);

  if (view === "detail" && selected) {
    return <CLDetail
      listName={selected}
      meta={selectedMeta}
      onBack={() => { setView("list"); setSelected(null); setSelectedMeta(null); }}
    />;
  }

  return (
    <div className="page">
      <PageHeader
        eyebrow="ADMIN · REFERENCE DATA · choice lists"
        title="Choice lists"
        sub="Versioned code-lists used by every questionnaire and downstream report. Each list_name is stable across versions; lifecycle: draft → pending → active → retired."
        right={<>
          <button className="btn"><Icon name="download" size={14}/> Export all (CSV)</button>
          <button className="btn btn-primary"><Icon name="plus" size={14}/> New list</button>
        </>}
      />

      <div className="grid grid-4">
        <KPI title="Choice lists" value={total} foot={`${drafts} with pending drafts`}/>
        <KPI title="Active options" value={totalOptions.toLocaleString()} foot="Across all active lists"/>
        <KPI title="PII-classified" value={piiCount} foot="Personal sensitivity — DPO review on submit"/>
        <KPI title="Versions in registry" value="68" foot="Across all lists" trend="up" trendValue="+5 this quarter"/>
      </div>

      <div className="card mt-5" style={{ padding: '14px 16px' }}>
        <div className="row gap-3" style={{ flexWrap: 'wrap' }}>
          <div className="search" style={{ maxWidth: 380, height: 34, background: 'var(--neutral-0)' }}>
            <Icon name="search" size={16} color="var(--neutral-500)"/>
            <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search list name, label, or option code…"/>
          </div>
          <select className="field-select" style={{ height: 34, width: 'auto', minWidth: 140 }} value={piiFilter} onChange={e => setPiiFilter(e.target.value)}>
            <option value="">Any sensitivity</option>
            <option value="pii">PII / Personal</option>
            <option value="nonpii">Non-PII</option>
          </select>
          <select className="field-select" style={{ height: 34, width: 'auto', minWidth: 140 }} value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
            <option value="">Any status</option>
            <option value="draft">Has draft version</option>
          </select>
          <div style={{ flex: 1 }}/>
          <span className="t-cap">{rows.length} of {total} lists</span>
        </div>
      </div>

      <div className="card mt-4">
        <table className="tbl">
          <thead>
            <tr>
              <th>List name · label</th>
              <th>Active version</th>
              <th>Draft</th>
              <th>Options</th>
              <th>Sensitivity</th>
              <th>Consumed by</th>
              <th>Last updated</th>
              <th className="col-actions"></th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr><td colSpan="8" className="muted t-cap" style={{ padding: 14 }}>
                {total === 0
                  ? "No choice lists loaded. The reference-data API returned nothing — log into /admin/ first if this is a local session."
                  : "No choice list matches these filters."}
              </td></tr>
            )}
            {rows.map(l => (
              <tr key={l.listName} style={{ cursor: 'pointer' }} onClick={() => { setSelected(l.listName); setSelectedMeta(l); setView("detail"); }}>
                <td>
                  <div className="t-mono" style={{ fontSize: 12.5, fontWeight: 600 }}>{l.listName}</div>
                  <div className="t-cap">{l.label}</div>
                </td>
                <td>
                  <div className="row gap-2">
                    <Chip size="sm" tone="data">v{l.activeVersion}</Chip>
                  </div>
                </td>
                <td>
                  {l.draftVersion
                    ? <Chip size="sm" tone="quality">v{l.draftVersion} · draft</Chip>
                    : <span className="muted t-cap">—</span>}
                </td>
                <td className="t-num">{l.optionsCount}</td>
                <td>
                  {l.pii
                    ? <Chip size="sm" tone="quality"><Icon name="shield" size={10}/> PII</Chip>
                    : <Chip size="sm">Public</Chip>}
                </td>
                <td>
                  <div className="t-mono t-cap" style={{ fontSize: 11, color: 'var(--neutral-600)' }}>
                    {l.uses.slice(0, 1).join(', ')}
                    {l.uses.length > 1 && <span className="muted"> +{l.uses.length - 1}</span>}
                  </div>
                </td>
                <td className="t-cap" style={{ whiteSpace: 'nowrap' }}>{l.lastUpdated}</td>
                <td className="col-actions"><Icon name="chevronRight" size={16} color="var(--neutral-500)"/></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

/* ===========================================================
   Detail
   ===========================================================
   Live data path:
     GET  /api/v1/admin/refdata/choice-lists/<list_name>/versions/
     GET  /api/v1/admin/refdata/choice-lists/<list_name>/versions/<v>/options/
     POST /api/v1/admin/refdata/choice-lists/<list_name>/clone/
     POST /api/v1/admin/refdata/choice-lists/<list_name>/versions/<v>/options/
     PATCH .../options/<code>/
   Falls back to the education_level mock shape when the API is
   unreachable so the design preview still renders end-to-end.
   =========================================================== */
const CLDetail = ({ listName, meta: metaProp, onBack }) => {
  // The live row passed from the list view. There is no fixture to fall
  // back to; without it the screen renders the version history alone.
  const meta = metaProp || null;

  const [search, setSearch] = useStateCL("");
  const [showDeprecated, setShowDeprecated] = useStateCL(true);

  // Live versions for THIS list (not hardcoded EDU).
  const [versionsLive, setVersionsLive] = useStateCL(null);
  // Currently-viewed version number. Defaults to draft (so edit
  // affordances are immediately visible) when one exists, else active.
  const [viewVersion, setViewVersion] = useStateCL(null);
  // Detail (incl. options) for the selected version.
  const [detail, setDetail] = useStateCL(null);
  const [detailLoading, setDetailLoading] = useStateCL(false);
  const [detailError, setDetailError] = useStateCL(null);
  // Cloning busy flag for the "New draft" CTA.
  const [cloning, setCloning] = useStateCL(false);

  const apiAvailable = typeof nsrApi !== "undefined" && nsrApi && typeof nsrApi.get === "function";

  // Fetch versions on mount.
  useEffectCL(() => {
    if (!apiAvailable) return undefined;
    let cancelled = false;
    nsrApi.get(`/api/v1/admin/refdata/choice-lists/${encodeURIComponent(listName)}/versions/`)
      .then(d => {
        if (cancelled) return;
        const list = (d && d.versions) || [];
        setVersionsLive(list);
        // Land on the draft if one exists (so Add option / Edit
        // surface immediately), otherwise on the active version.
        const draft = list.find(v => v.status === "draft");
        const active = list.find(v => v.status === "active");
        const initial = (draft && draft.version) || (active && active.version) || (list[0] && list[0].version);
        if (initial != null) setViewVersion(initial);
      })
      .catch(() => { /* fall through to mocks */ });
    return () => { cancelled = true; };
  }, [listName, apiAvailable]);

  // Fetch the selected version's detail (options) whenever it changes.
  const refreshDetail = useCallbackCL(async () => {
    if (!apiAvailable || viewVersion == null) return;
    setDetailLoading(true);
    setDetailError(null);
    try {
      const d = await nsrApi.get(
        `/api/v1/admin/refdata/choice-lists/${encodeURIComponent(listName)}/versions/${viewVersion}/options/`
      );
      setDetail(d);
    } catch (err) {
      setDetailError(String(err.message || err));
    } finally {
      setDetailLoading(false);
    }
  }, [listName, viewVersion, apiAvailable]);

  useEffectCL(() => { refreshDetail(); }, [refreshDetail]);

  // Project the live data onto the shape the rest of the JSX expects,
  // falling back to the EDU mocks when the API isn't reachable.
  const versions = useMemoCL(() => {
    if (versionsLive && versionsLive.length) {
      return versionsLive.map(v => ({
        version: v.version,
        status: v.status,
        optionsCount: v.options_count,
        author: v.author,
        approvedBy: v.approved_by,
        approvedAt: v.approved_at ? String(v.approved_at).slice(0, 10) : null,
        effectiveFrom: v.approved_at ? String(v.approved_at).slice(0, 10) : null,
        updatedAt: v.updated_at ? String(v.updated_at).slice(0, 16).replace("T", " ") : "",
        note: "",
      }));
    }
    return [];
  }, [versionsLive]);

  const selectedVersion = useMemoCL(() => {
    if (viewVersion != null) {
      const hit = versions.find(v => v.version === viewVersion);
      if (hit) return hit;
    }
    return versions[0];
  }, [versions, viewVersion]);

  const liveOptions = useMemoCL(() => {
    if (!detail || !Array.isArray(detail.options)) return null;
    return detail.options.map(o => ({
      code: o.code,
      label: o.label,
      language: o.language || "en",
      sort: o.sort_order != null ? o.sort_order : 0,
      status: o.status || "active",
    }));
  }, [detail]);

  const options = useMemoCL(() => {
    let opts = liveOptions || [];
    if (!showDeprecated) opts = opts.filter(o => o.status === "active");
    if (search) opts = opts.filter(o => o.code.includes(search) || o.label.toLowerCase().includes(search.toLowerCase()));
    return opts;
  }, [liveOptions, search, showDeprecated]);

  const optionsTotal = (liveOptions || []).length;
  const isDraft = selectedVersion && selectedVersion.status === "draft";

  // Inline editor state:
  //   editingCode === null  → no editor open
  //   editingCode === "__new__" → Add-option form open
  //   editingCode === "<code>" → Edit-row form for that option
  const [editingCode, setEditingCode] = useStateCL(null);
  const [editForm, setEditForm] = useStateCL({ code: "", label: "", sort_order: 0 });
  const [editBusy, setEditBusy] = useStateCL(false);

  const openAddOption = () => {
    setEditForm({ code: "", label: "", sort_order: optionsTotal });
    setEditingCode("__new__");
  };
  const openEditOption = (o) => {
    setEditForm({ code: o.code, label: o.label, sort_order: o.sort });
    setEditingCode(o.code);
  };
  const cancelEdit = () => { setEditingCode(null); };

  const submitOption = async () => {
    if (!apiAvailable || !isDraft || editBusy) return;
    const code = (editForm.code || "").trim();
    const label = (editForm.label || "").trim();
    if (!code || !label) {
      // eslint-disable-next-line no-alert
      alert("Code and label are required.");
      return;
    }
    setEditBusy(true);
    try {
      const base = `/api/v1/admin/refdata/choice-lists/${encodeURIComponent(listName)}/versions/${viewVersion}/options/`;
      if (editingCode === "__new__") {
        await nsrApi.post(base, { code, label, sort_order: Number(editForm.sort_order) || 0 });
      } else {
        await nsrApi.patch(`${base}${encodeURIComponent(editingCode)}/`, {
          label, sort_order: Number(editForm.sort_order) || 0,
        });
      }
      setEditingCode(null);
      await refreshDetail();
    } catch (err) {
      // eslint-disable-next-line no-alert
      alert(`Could not save option: ${err.body && err.body.detail ? err.body.detail : err.message || err}`);
    } finally {
      setEditBusy(false);
    }
  };

  const deprecateOption = async (o) => {
    if (!apiAvailable || !isDraft || editBusy) return;
    // eslint-disable-next-line no-alert
    if (!confirm(`Mark option ${o.code} as deprecated? Past responses keep referring to it.`)) return;
    setEditBusy(true);
    try {
      await nsrApi.patch(
        `/api/v1/admin/refdata/choice-lists/${encodeURIComponent(listName)}/versions/${viewVersion}/options/${encodeURIComponent(o.code)}/`,
        { status: "deprecated" },
      );
      await refreshDetail();
    } catch (err) {
      // eslint-disable-next-line no-alert
      alert(`Could not deprecate: ${err.body && err.body.detail ? err.body.detail : err.message || err}`);
    } finally {
      setEditBusy(false);
    }
  };

  // Submit the current draft for approval (DRAFT → PENDING_APPROVAL).
  // Other approvers pick it up from the Approvals dashboard.
  const [submitting, setSubmitting] = useStateCL(false);
  const onSubmitForApproval = async () => {
    if (!apiAvailable || !isDraft || submitting) return;
    // eslint-disable-next-line no-alert
    if (!confirm("Submit this draft for approval? You will not be able to edit it further until an approver signs or rejects.")) return;
    setSubmitting(true);
    try {
      await nsrApi.post(
        `/api/v1/admin/refdata/choice-lists/${encodeURIComponent(listName)}/versions/${viewVersion}/submit/`,
        {},
      );
      // Refresh versions; the current draft now has status pending_approval.
      const v = await nsrApi.get(
        `/api/v1/admin/refdata/choice-lists/${encodeURIComponent(listName)}/versions/`
      );
      setVersionsLive((v && v.versions) || []);
      await refreshDetail();
    } catch (err) {
      // eslint-disable-next-line no-alert
      alert(`Could not submit: ${err.body && err.body.detail ? err.body.detail : err.message || err}`);
    } finally {
      setSubmitting(false);
    }
  };

  // "Discard" — no destructive endpoint exists (audit trail integrity).
  // We just snap the view back to the active version so the user
  // visibly leaves the draft tab without throwing anything away.
  const onDiscardEdits = () => {
    const active = versions.find(v => v.status === "active");
    if (active) setViewVersion(active.version);
  };

  // Clone the latest version into a new DRAFT and switch to it.
  const onCloneDraft = async () => {
    if (!apiAvailable || cloning) return;
    setCloning(true);
    try {
      const created = await nsrApi.post(
        `/api/v1/admin/refdata/choice-lists/${encodeURIComponent(listName)}/clone/`,
        {},
      );
      // Refresh versions, then jump to the new draft.
      const v = await nsrApi.get(
        `/api/v1/admin/refdata/choice-lists/${encodeURIComponent(listName)}/versions/`
      );
      const list = (v && v.versions) || [];
      setVersionsLive(list);
      const newVer = (created && created.version)
        || (list.find(x => x.status === "draft") || {}).version;
      if (newVer != null) setViewVersion(newVer);
    } catch (err) {
      // eslint-disable-next-line no-alert
      alert(`Could not create draft: ${err.body && err.body.detail ? err.body.detail : err.message || err}`);
    } finally {
      setCloning(false);
    }
  };

  // Nothing loaded: say which state this is instead of rendering a
  // version history. All hooks above have run, so this early return is
  // safe — it is the last statement before the main tree.
  if (!selectedVersion) {
    return (
      <div className="page">
        <PageHeader
          back={{ label: "Choice lists", onClick: onBack }}
          eyebrow={<>ADMIN · REFERENCE DATA · CHOICE LIST · <span className="t-mono">{listName}</span></>}
          title={meta?.label || listName}
          sub="Version history"/>
        <div className="card mt-4" style={{ padding: 24 }}>
          <div className="t-bodysm muted">
            {detailError
              ? `Could not load this list: ${detailError}`
              : !apiAvailable
              ? "The reference-data API is not reachable from here. Log in via /admin/ first — session-cookie auth carries through to the API."
              : detailLoading || versionsLive === null
              ? "Loading versions…"
              : "No versions exist for this choice list yet."}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <PageHeader
        back={{ label: "Choice lists", onClick: onBack }}
        eyebrow={<>ADMIN · REFERENCE DATA · CHOICE LIST · <span className="t-mono">{listName}</span></>}
        title={meta?.label || listName}
        sub={<>Versioned · stable across revisions · last activated <strong>{selectedVersion.effectiveFrom || '—'}</strong></>}
        right={<>
          {meta?.draftVersion
            ? <button className="btn" disabled title="A draft already exists for this list — switch to it to edit options">
                <Icon name="edit" size={14}/> Draft v{meta?.draftVersion} exists
              </button>
            : <button className="btn btn-primary" onClick={onCloneDraft} disabled={cloning || !apiAvailable}
                      title={apiAvailable ? "Clone the current active version into a new editable draft" : "API not reachable"}>
                <Icon name="plus" size={14}/> {cloning ? "Creating draft…" : "New draft from this"}
              </button>}
        </>}
      />

      {/* Version selector + meta */}
      <div className="card" style={{ padding: 0 }}>
        <div style={{ padding: '18px 20px', display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 18, alignItems: 'flex-start' }}>
          <div>
            <div className="t-cap">List name</div>
            <div className="t-mono" style={{ fontWeight: 600, fontSize: 16, marginTop: 2 }}>{listName}</div>
            <div className="t-cap mt-1">{meta?.label}</div>
          </div>
          <div>
            <div className="t-cap">Active version</div>
            <Chip tone="data" style={{ marginTop: 4 }}>v{meta?.activeVersion}</Chip>
            <div className="t-cap mt-2">{meta?.optionsCount} options</div>
          </div>
          <div>
            <div className="t-cap">Pending draft</div>
            {meta?.draftVersion
              ? <>
                  <Chip tone="quality" style={{ marginTop: 4 }}>v{meta?.draftVersion} · draft</Chip>
                  <div className="t-cap mt-2">{meta?.draftAuthor}</div>
                </>
              : <div className="t-bodysm muted mt-1">none</div>}
          </div>
          <div>
            <div className="t-cap">Consumed by</div>
            <div className="t-mono t-cap mt-2" style={{ fontSize: 11, color: 'var(--neutral-700)' }}>
              {(meta?.uses || []).length
                ? (meta?.uses || []).map(u => <div key={u} style={{ marginBottom: 3 }}>{u}</div>)
                : <span className="muted">—</span>}
            </div>
          </div>
        </div>

        {/* Version chooser */}
        <div style={{ borderTop: '1px solid var(--neutral-200)', padding: '0 20px', display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <span className="t-cap" style={{ marginRight: 8 }}>VIEWING</span>
          {versions.map(v => {
            const active = v.version === (selectedVersion && selectedVersion.version);
            return (
              <button key={v.version} onClick={() => setViewVersion(v.version)} style={{
                padding: '12px 14px', border: 0, background: 'transparent',
                borderBottom: active ? '2px solid var(--primary-900)' : '2px solid transparent',
                marginBottom: -1, cursor: 'pointer',
                color: active ? 'var(--primary-900)' : 'var(--neutral-700)',
                fontWeight: active ? 600 : 500, fontSize: 13,
              }}>
                v{v.version} <Chip size="sm" tone={CL_LIST_STATUS_TONE[v.status]}>{CL_LIST_STATUS_LABEL[v.status]}</Chip>
              </button>
            );
          })}
        </div>
      </div>

      {/* Version meta band */}
      <div className="card mt-4" style={{ padding: 0, borderLeft: `3px solid var(--accent-${CL_LIST_STATUS_TONE[selectedVersion.status]})` }}>
        <div style={{ padding: 16, display: 'grid', gridTemplateColumns: '160px 1fr', rowGap: 6, fontSize: 13 }}>
          <div className="muted">Author</div><div>{selectedVersion.author}</div>
          <div className="muted">Status</div><div><Chip size="sm" tone={CL_LIST_STATUS_TONE[selectedVersion.status]}>{CL_LIST_STATUS_LABEL[selectedVersion.status]}</Chip></div>
          {selectedVersion.approvedBy && <>
            <div className="muted">Approved by</div><div>{selectedVersion.approvedBy} · {selectedVersion.approvedAt}</div>
          </>}
          {selectedVersion.effectiveFrom && <>
            <div className="muted">Effective from</div><div>{selectedVersion.effectiveFrom}</div>
          </>}
          <div className="muted">Note</div><div className="t-bodysm">{selectedVersion.note}</div>
        </div>
        {selectedVersion.status === "draft" && <>
          <div className="tint-update" style={{ borderTop: '1px solid var(--neutral-200)', borderLeft: '3px solid var(--accent-update)', padding: '10px 16px', display: 'flex', alignItems: 'center', gap: 12 }}>
            <Icon name="edit" size={13} color="var(--accent-update)"/>
            <span className="t-bodysm">Draft version — options below are editable. Submit for approval to lock and queue it on the Approvals dashboard.</span>
            <div style={{ flex: 1 }}/>
            <button className="btn btn-sm" onClick={onDiscardEdits} disabled={submitting}
                    title="Leaves the draft intact (audit trail) but returns you to the active version.">
              Leave draft
            </button>
            <button className="btn btn-sm btn-primary" onClick={onSubmitForApproval}
                    disabled={submitting || !apiAvailable || editingCode !== null}
                    title={editingCode !== null ? "Save or cancel the row editor first" : ""}>
              <Icon name="upload" size={12}/> {submitting ? "Submitting…" : "Submit for approval"}
            </button>
          </div>
        </>}
        {selectedVersion.status === "pending_approval" && (
          <div style={{ borderTop: '1px solid var(--neutral-200)', borderLeft: '3px solid var(--accent-update)', background: 'var(--update-50, var(--neutral-50))', padding: '10px 16px', display: 'flex', alignItems: 'center', gap: 12 }}>
            <Icon name="clock" size={13} color="var(--accent-update)"/>
            <span className="t-bodysm">Pending approval — awaiting sign-off on the Approvals dashboard. Cannot be edited.</span>
          </div>
        )}
      </div>

      {/* Options table */}
      <div className="card mt-4" style={{ padding: 0 }}>
        <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--neutral-200)', display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <strong className="t-bodysm">Options</strong>
          <span className="t-cap">{options.length} of {optionsTotal}</span>
          {detailLoading && <span className="t-cap muted">· loading…</span>}
          {detailError && <span className="t-cap" style={{ color: 'var(--accent-danger)' }}>· {detailError}</span>}
          <div className="search" style={{ maxWidth: 280, height: 30, marginLeft: 12 }}>
            <Icon name="search" size={13} color="var(--neutral-500)"/>
            <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search code or label…"/>
          </div>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <input type="checkbox" checked={showDeprecated} onChange={e => setShowDeprecated(e.target.checked)}/>
            <span className="t-bodysm">Show deprecated</span>
          </label>
          <div style={{ flex: 1 }}/>
          {isDraft && <>
            <button className="btn btn-sm" disabled title="CSV import — coming soon"><Icon name="upload" size={12}/> Import CSV</button>
            <button className="btn btn-sm btn-primary" onClick={openAddOption} disabled={editBusy || editingCode === "__new__"}>
              <Icon name="plus" size={12}/> Add option
            </button>
          </>}
          {!isDraft && apiAvailable && (
            <button className="btn btn-sm" onClick={onCloneDraft} disabled={cloning || !!meta?.draftVersion}
                    title={meta?.draftVersion
                      ? `Switch to the v${meta?.draftVersion} draft tab above to edit`
                      : "Active versions are read-only — clone to a draft to add or edit options"}>
              <Icon name="plus" size={12}/> {meta?.draftVersion ? `Edit in draft v${meta.draftVersion}` : "Clone to draft to edit"}
            </button>
          )}
        </div>
        <table className="tbl" style={{ boxShadow: 'none' }}>
          <thead>
            <tr>
              <th style={{ width: 80 }}>Code</th>
              <th>Label</th>
              <th style={{ width: 80 }}>Language</th>
              <th style={{ width: 80 }}>Sort</th>
              <th style={{ width: 120 }}>Status</th>
              {selectedVersion.status === "draft" && <th className="col-actions"></th>}
            </tr>
          </thead>
          <tbody>
            {isDraft && editingCode === "__new__" && (
              <tr style={{ background: 'var(--neutral-50)' }}>
                <td><input className="field-input" style={{ height: 28, width: 70 }}
                           placeholder="code" value={editForm.code}
                           onChange={e => setEditForm(f => ({ ...f, code: e.target.value }))}/></td>
                <td><input className="field-input" style={{ height: 28, width: '100%' }}
                           placeholder="Label shown to enumerators" value={editForm.label}
                           onChange={e => setEditForm(f => ({ ...f, label: e.target.value }))}/></td>
                <td><Chip size="sm">en</Chip></td>
                <td><input className="field-input" style={{ height: 28, width: 60 }}
                           type="number" value={editForm.sort_order}
                           onChange={e => setEditForm(f => ({ ...f, sort_order: e.target.value }))}/></td>
                <td><Chip size="sm" tone="quality">New</Chip></td>
                <td className="col-actions">
                  <button className="btn btn-sm btn-primary" onClick={submitOption} disabled={editBusy}>Save</button>
                  <button className="btn btn-sm" onClick={cancelEdit} disabled={editBusy}>Cancel</button>
                </td>
              </tr>
            )}
            {options.map(o => {
              const editing = isDraft && editingCode === o.code;
              if (editing) {
                return (
                  <tr key={o.code} style={{ background: 'var(--neutral-50)' }}>
                    <td className="t-mono">{o.code}</td>
                    <td><input className="field-input" style={{ height: 28, width: '100%' }}
                               value={editForm.label}
                               onChange={e => setEditForm(f => ({ ...f, label: e.target.value }))}/></td>
                    <td><Chip size="sm">{o.language}</Chip></td>
                    <td><input className="field-input" style={{ height: 28, width: 60 }}
                               type="number" value={editForm.sort_order}
                               onChange={e => setEditForm(f => ({ ...f, sort_order: e.target.value }))}/></td>
                    <td>
                      {o.status === "active"
                        ? <Chip size="sm" tone="data">Active</Chip>
                        : <Chip size="sm">Deprecated</Chip>}
                    </td>
                    <td className="col-actions">
                      <button className="btn btn-sm btn-primary" onClick={submitOption} disabled={editBusy}>Save</button>
                      <button className="btn btn-sm" onClick={cancelEdit} disabled={editBusy}>Cancel</button>
                    </td>
                  </tr>
                );
              }
              return (
                <tr key={o.code} style={o.status === "deprecated" ? { opacity: 0.55 } : null}>
                  <td className="t-mono">{o.code}</td>
                  <td className="t-bodysm">{o.label}</td>
                  <td><Chip size="sm">{o.language}</Chip></td>
                  <td className="t-num t-bodysm">{o.sort}</td>
                  <td>
                    {o.status === "active"
                      ? <Chip size="sm" tone="data">Active</Chip>
                      : <Chip size="sm">Deprecated</Chip>}
                  </td>
                  {isDraft && <td className="col-actions">
                    <button className="icon-btn" title="Edit" onClick={() => openEditOption(o)} disabled={editBusy || editingCode !== null}>
                      <Icon name="edit" size={12}/>
                    </button>
                    {o.status === "active" && (
                      <button className="icon-btn" title="Deprecate (cannot delete — only hidden from new intakes)" onClick={() => deprecateOption(o)} disabled={editBusy}>
                        <Icon name="minus" size={12}/>
                      </button>
                    )}
                  </td>}
                </tr>
              );
            })}
            {options.length === 0 && !detailLoading && (
              <tr><td colSpan={isDraft ? 6 : 5} className="t-cap muted" style={{ padding: 16, textAlign: 'center' }}>
                {search ? "No options match your search." : "This version has no options yet."}
              </td></tr>
            )}
          </tbody>
        </table>
        <div className="tint-update" style={{
          padding: '10px 16px', borderTop: '1px solid var(--neutral-200)',
          borderLeft: '3px solid var(--accent-update)',
        }}>
          <div className="row gap-2" style={{ marginBottom: 2 }}>
            <Icon name="info" size={12} color="var(--accent-update)"/>
            <strong className="t-bodysm">No deletes — only deprecate</strong>
          </div>
          <div className="t-bodysm muted">
            Past intake responses must remain interpretable. Removing an option is impossible by design;
            mark it <span className="t-mono">deprecated</span> instead and it's no longer selectable on new
            intakes while remaining readable on historical records.
          </div>
        </div>
      </div>
    </div>
  );
};

Object.assign(window, { AdminChoiceListsScreen });
