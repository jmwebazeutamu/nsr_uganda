/* global React, Icon, Chip, PageHeader,
   PMT_ACTIVE, PMT_VARIABLES_TOP, BandChip */
// NSR MIS — PMT Configuration (Admin · PMT)
// =========================================================
// Manage PMT model versions: registry of all versions, variable
// + weight editor for drafts, band strategy + cutoffs editor,
// activation workflow (dual approval per AC-PMT-MODEL-VERSION).
//
// Maps to:
//   apps.pmt.models.PMTModelVersion (status DRAFT → PENDING_APPROVAL → ACTIVE → RETIRED)
//   apps.pmt.services.activate_model_version
//   apps.security.audit (model.create, model.submit, model.activate)

const {
  useState: useStatePCfg,
  useMemo: useMemoPCfg,
  useEffect: useEffectPCfg,
  useRef: useRefPCfg,
} = React;

/* ============================================================
   Sample data — mirrors PMTModelVersion shape; replace with API
   ============================================================ */
const PCFG_VERSIONS = [
  {
    id: "01HXM12Z4F7N6P0V8K9TB2QXJK",
    version: 2,
    status: "draft",
    description: "v2 calibration — UDHS 2024 spike-in. Adds livestock & cooking-fuel variables.",
    author: "Dr. Nakanwagi · MGLSD Statistics",
    approvedBy: null, approvedAt: null,
    effectiveFrom: null,
    variablesCount: 27,
    intercept: 2.9842,
    validationRSquared: 0.668,
    bandStrategy: "percentile",
    bandCutoffs: { extreme_poverty: 10, poverty: 20, vulnerable: 30, not_poor: 100 },
    calibrationDataset: "UNHS 2023/24 + UDHS 2024 spike-in",
    calibrationYearEnd: 2024,
    createdAt: "12 May 2026",
    updatedAt: "21 May 2026 · 11:08 EAT",
  },
  {
    id: "01HX91KPNRMQ0F2B7K6FZRWS01",
    version: 1,
    status: "active",
    description: "Uganda PMT v1 — UNHS 2019/20 + UDHS 2022 calibration. 25-variable model; ADR-0025 DSL.",
    author: "MGLSD Statistics Unit · Dr. Nakanwagi",
    approvedBy: "Director General · UBOS",
    approvedAt: "02 Jan 2026",
    effectiveFrom: "04 Jan 2026",
    variablesCount: 25,
    intercept: 3.0185,
    validationRSquared: 0.642,
    bandStrategy: "percentile",
    bandCutoffs: { extreme_poverty: 10, poverty: 20, vulnerable: 30, not_poor: 100 },
    calibrationDataset: "UNHS 2023/24",
    calibrationYearEnd: 2024,
    createdAt: "02 Dec 2025",
    updatedAt: "04 Jan 2026 · 09:14 EAT",
  },
  {
    id: "01H8M9QR4N1P0V8B7K6FZRWS00",
    version: 0,
    status: "retired",
    description: "Legacy PMT (UNHS 2016/17). Retired on v1 activation.",
    author: "MGLSD legacy",
    approvedBy: "Director General · UBOS",
    approvedAt: "10 Aug 2023",
    effectiveFrom: "01 Sep 2023",
    variablesCount: 22,
    intercept: 2.9100,
    validationRSquared: 0.582,
    bandStrategy: "threshold",
    bandCutoffs: { extreme_poverty: 0, poverty: 30, vulnerable: 50, not_poor: 100 },
    calibrationDataset: "UNHS 2016/17",
    calibrationYearEnd: 2017,
    createdAt: "20 Jul 2023",
    updatedAt: "04 Jan 2026 · 09:14 EAT",
  },
];

// Full 25-variable list of the active v1 model (and stub for v2 draft)
const PCFG_VARIABLES_V1 = [
  { name: "member_count",                 weight: -0.077, transform: "identity",        group: "Composition" },
  { name: "share_children_under_15",      weight: -0.117, transform: "identity",        group: "Composition" },
  { name: "head_is_female",               weight: +0.038, transform: "present_as_one",  group: "Head" },
  { name: "head_edu_completed_primary",   weight: +0.099, transform: "present_as_one",  group: "Education" },
  { name: "head_edu_secondary",           weight: +0.154, transform: "present_as_one",  group: "Education" },
  { name: "head_edu_tertiary",            weight: +0.312, transform: "present_as_one",  group: "Education" },
  { name: "floor_tiles_terrazzo",         weight: +0.326, transform: "present_as_one",  group: "Dwelling" },
  { name: "floor_cement_or_brick",        weight: +0.130, transform: "present_as_one",  group: "Dwelling" },
  { name: "roof_metal_or_tile",           weight: +0.138, transform: "present_as_one",  group: "Dwelling" },
  { name: "wall_uncovered_adobe",         weight: +0.052, transform: "present_as_one",  group: "Dwelling" },
  { name: "wall_stone_lime_cement",       weight: +0.099, transform: "present_as_one",  group: "Dwelling" },
  { name: "wall_other_finished",          weight: +0.050, transform: "present_as_one",  group: "Dwelling" },
  { name: "rooms_per_capita",             weight: +0.292, transform: "identity",        group: "Dwelling" },
  { name: "electricity_for_lighting",     weight: +0.112, transform: "present_as_one",  group: "Utilities" },
  { name: "piped_water_to_premises",      weight: +0.075, transform: "present_as_one",  group: "Utilities" },
  { name: "lighting_kerosene",            weight: -0.034, transform: "present_as_one",  group: "Utilities" },
  { name: "open_defecation",              weight: -0.128, transform: "present_as_one",  group: "Sanitation" },
  { name: "owns_car_or_van",              weight: +0.294, transform: "present_as_one",  group: "Assets" },
  { name: "owns_television",              weight: +0.228, transform: "present_as_one",  group: "Assets" },
  { name: "owns_motorcycle",              weight: +0.213, transform: "present_as_one",  group: "Assets" },
  { name: "any_cellphone",                weight: +0.185, transform: "present_as_one",  group: "Assets" },
  { name: "owns_refrigerator",            weight: +0.157, transform: "present_as_one",  group: "Assets" },
  { name: "owns_computer",                weight: +0.141, transform: "present_as_one",  group: "Assets" },
  { name: "owns_radio",                   weight: +0.107, transform: "present_as_one",  group: "Assets" },
  { name: "is_renting",                   weight: +0.108, transform: "present_as_one",  group: "Tenure" },
];

const PCFG_TRANSFORMS = [
  { id: "identity",       label: "identity",       desc: "Pass-through — multiply value × weight" },
  { id: "present_as_one", label: "present_as_one", desc: "Binary — 1 if present, 0 otherwise" },
  { id: "log1p",          label: "log1p",          desc: "log(1 + value) — for asset counts" },
  { id: "zscore",         label: "zscore",         desc: "Standardised to dataset mean / σ" },
];

const STATUS_TONE = {
  draft: "quality",
  pending_approval: "update",
  active: "data",
  retired: "neutral",
  rejected: "danger",
};
const STATUS_LABEL = {
  draft: "Draft",
  pending_approval: "Pending approval",
  active: "Active",
  retired: "Retired",
  rejected: "Rejected",
};

const PCFG_API_ROOT = "/api/v1/admin/pmt/versions/";

const pcfgStatus = (value) => String(value || "draft").toLowerCase();
const pcfgNum = (value, fallback = 0) => {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
};
const pcfgVariableName = (v) => v.name || v.variable || v.path || "";
const pcfgVariableGroup = (v) => v.group || v.category || "DSL";
const pcfgVariableTransform = (v) => v.transform || (v.feature && v.feature.type) || "direct";
const pcfgVersionLabelDate = (value) => {
  if (!value) return "";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString();
};
const pcfgNormalizeVersion = (raw) => {
  const status = pcfgStatus(raw.status);
  const variables = Array.isArray(raw.variables) ? raw.variables : [];
  return {
    id: raw.id,
    version: raw.version,
    status,
    description: raw.description || "",
    author: raw.author || "",
    approvedBy: raw.approved_by || raw.approvedBy || "",
    approvedAt: pcfgVersionLabelDate(raw.approved_at || raw.approvedAt),
    effectiveFrom: raw.effective_from || raw.effectiveFrom || "",
    variables,
    variablesCount: raw.variables_count ?? raw.variablesCount ?? variables.length,
    intercept: pcfgNum(raw.intercept),
    validationRSquared: raw.validation_r_squared ?? raw.validationRSquared,
    bandStrategy: raw.band_strategy || raw.bandStrategy || "threshold",
    bandCutoffs: raw.band_cutoffs || raw.bandCutoffs || {},
    calibrationDataset: raw.calibration_dataset || raw.calibrationDataset || "",
    calibrationYearEnd: raw.calibration_year_end || raw.calibrationYearEnd || "",
    createdAt: pcfgVersionLabelDate(raw.created_at || raw.createdAt),
    updatedAt: pcfgVersionLabelDate(raw.updated_at || raw.updatedAt),
    signoffs: raw.signoffs || [],
  };
};

const pcfgParseCsvVariables = (text) => {
  const lines = String(text || "").split(/\r?\n/).map(l => l.trim()).filter(Boolean);
  if (!lines.length) return [];
  const header = lines[0].split(",").map(h => h.trim().toLowerCase());
  const rows = header.includes("name") || header.includes("variable") ? lines.slice(1) : lines;
  return rows.map(line => {
    const cols = line.split(",").map(c => c.trim());
    const get = (name, fallbackIndex) => {
      const i = header.indexOf(name);
      return cols[i >= 0 ? i : fallbackIndex] || "";
    };
    const name = get("name", 0) || get("variable", 0);
    return {
      name,
      weight: pcfgNum(get("weight", 1), 0),
      group: get("group", 3) || "Imported",
      transform: get("transform", 2) || "direct",
      feature: { type: get("transform", 2) || "direct", path: name },
    };
  }).filter(v => v.name);
};

/* ============================================================
   PCfgSection — small content shell
   ============================================================ */
const PCfgSection = ({ title, sub, action, children }) => (
  <div className="card mt-4" style={{ padding: 0 }}>
    <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--neutral-200)', display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
      <div>
        <h3 className="t-h3" style={{ margin: 0 }}>{title}</h3>
        {sub && <div className="t-cap mt-1">{sub}</div>}
      </div>
      <div style={{ flex: 1 }}/>
      {action}
    </div>
    {children}
  </div>
);

/* ============================================================
   PMT Configuration
   ============================================================ */
const PmtConfigurationScreen = ({ onBack }) => {
  // Which version is selected in the right pane.
  const [selectedId, setSelectedId] = useStatePCfg(PCFG_VERSIONS[0].id);
  const [tab, setTab] = useStatePCfg("variables");
  const [varSearch, setVarSearch] = useStatePCfg("");
  const [varGroupFilter, setVarGroupFilter] = useStatePCfg("All");
  const [versions, setVersions] = useStatePCfg(PCFG_VERSIONS);
  const [loading, setLoading] = useStatePCfg(true);
  const [error, setError] = useStatePCfg("");
  const [saving, setSaving] = useStatePCfg("");
  const [notice, setNotice] = useStatePCfg("");
  const [addModalOpen, setAddModalOpen] = useStatePCfg(false);
  const [variablePickSearch, setVariablePickSearch] = useStatePCfg("");
  const fileInputRef = useRefPCfg(null);

  const fetchVersions = async (preferredId = selectedId) => {
    const api = typeof window !== "undefined" ? window.nsrApi : null;
    if (!api) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const list = await api.get(PCFG_API_ROOT);
      const summaries = Array.isArray(list?.results) ? list.results : [];
      const detailRows = await Promise.all(
        summaries.map(row => api.get(`${PCFG_API_ROOT}${row.id}/`).catch(() => row))
      );
      const next = detailRows.map(pcfgNormalizeVersion);
      if (next.length) {
        setVersions(next);
        const keepId = next.some(v => v.id === preferredId) ? preferredId : next[0].id;
        setSelectedId(keepId);
      }
    } catch (err) {
      setError(err?.body?.detail || err?.message || "Could not load PMT model versions.");
    } finally {
      setLoading(false);
    }
  };

  useEffectPCfg(() => {
    fetchVersions();
  }, []);

  const selected = useMemoPCfg(
    () => versions.find(v => v.id === selectedId) || versions[0] || PCFG_VERSIONS[0],
    [selectedId, versions]
  );
  const variables = (selected.variables && selected.variables.length)
    ? selected.variables
    : selected.version === 1 ? PCFG_VARIABLES_V1
      : selected.version === 2 ? PCFG_VARIABLES_V1
      : PCFG_VARIABLES_V1.slice(0, 22);

  const filteredVariables = useMemoPCfg(() => {
    const q = varSearch.trim().toLowerCase();
    return variables.filter(v => {
      const name = pcfgVariableName(v);
      if (varGroupFilter !== "All" && pcfgVariableGroup(v) !== varGroupFilter) return false;
      if (q && !name.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [variables, varSearch, varGroupFilter]);

  const groups = [...new Set(variables.map(v => pcfgVariableGroup(v)))];

  const isEditable = selected.status === "draft";
  const totalAbsWeight = variables.reduce((a, v) => a + Math.abs(pcfgNum(v.weight)), 0);
  const existingVariableNames = new Set(variables.map(v => pcfgVariableName(v)));
  const databaseVariableCatalog = useMemoPCfg(() => {
    const byName = new Map();
    versions.forEach(version => {
      (version.variables || []).forEach(variable => {
        const name = pcfgVariableName(variable);
        if (!name || byName.has(name)) return;
        byName.set(name, {
          ...variable,
          name,
          sourceVersion: version.version,
          sourceStatus: version.status,
        });
      });
    });
    return [...byName.values()].sort((a, b) => pcfgVariableName(a).localeCompare(pcfgVariableName(b)));
  }, [versions]);
  const filteredDatabaseVariables = useMemoPCfg(() => {
    const q = variablePickSearch.trim().toLowerCase();
    if (!q) return databaseVariableCatalog;
    return databaseVariableCatalog.filter(v => {
      const haystack = [
        pcfgVariableName(v),
        pcfgVariableGroup(v),
        pcfgVariableTransform(v),
        v.comment || "",
      ].join(" ").toLowerCase();
      return haystack.includes(q);
    });
  }, [databaseVariableCatalog, variablePickSearch]);

  const patchSelected = async (body, successMessage) => {
    const api = typeof window !== "undefined" ? window.nsrApi : null;
    if (!api || !selected?.id) return;
    setSaving("patch");
    setError("");
    try {
      const updated = await api.patch(`${PCFG_API_ROOT}${selected.id}/`, body);
      const normalized = pcfgNormalizeVersion(updated);
      setVersions(prev => prev.map(v => v.id === normalized.id ? normalized : v));
      setSelectedId(normalized.id);
      setNotice(successMessage);
    } catch (err) {
      setError(err?.body?.detail || err?.message || "Could not save PMT model version.");
    } finally {
      setSaving("");
    }
  };

  const createVersion = async () => {
    const api = typeof window !== "undefined" ? window.nsrApi : null;
    if (!api) return;
    const description = window.prompt("Description for the new PMT model version:", "New PMT model draft");
    if (description === null) return;
    setSaving("create");
    setError("");
    try {
      const created = await api.post(PCFG_API_ROOT, {
        description,
        variables: [],
        intercept: selected?.intercept || 0,
        band_cutoffs: selected?.bandCutoffs || {},
        band_strategy: selected?.bandStrategy || "threshold",
        calibration_dataset: selected?.calibrationDataset || "",
        calibration_year_end: selected?.calibrationYearEnd || null,
      });
      await fetchVersions(created.id);
      setNotice(`Created PMT v${created.version} draft.`);
    } catch (err) {
      setError(err?.body?.detail || err?.message || "Could not create PMT model version.");
    } finally {
      setSaving("");
    }
  };

  const cloneVersion = async () => {
    const api = typeof window !== "undefined" ? window.nsrApi : null;
    if (!api || !selected?.id) return;
    setSaving("clone");
    setError("");
    try {
      const created = await api.post(`${PCFG_API_ROOT}${selected.id}/clone/`, {});
      await fetchVersions(created.id);
      setNotice(`Cloned PMT v${selected.version} into draft v${created.version}.`);
    } catch (err) {
      setError(err?.body?.detail || err?.message || "Could not clone PMT model version.");
    } finally {
      setSaving("");
    }
  };

  // Resolve which sign-off step is currently awaiting a decision.
  // PMT uses a three-step chain (author → MGLSD steward → UBOS DG)
  // tracked in PMTModelSignOff. The actionable step is the lowest
  // `step` with status === "pending" within the latest revision.
  const currentPendingStep = (() => {
    const offs = (selected && selected.signoffs) || [];
    if (!offs.length) return null;
    const maxRev = offs.reduce((m, s) => Math.max(m, Number(s.revision) || 1), 1);
    const pending = offs
      .filter(s => Number(s.revision || 1) === maxRev && s.status === "pending")
      .sort((a, b) => Number(a.step) - Number(b.step));
    return pending.length ? Number(pending[0].step) : null;
  })();

  const signVersion = async () => {
    const api = typeof window !== "undefined" ? window.nsrApi : null;
    if (!api || !selected?.id) return;
    const step = currentPendingStep;
    if (!step) {
      setError("Nothing to sign — no pending step on this version.");
      return;
    }
    const actorEmail = window.prompt(
      `Sign step ${step} — your email (server enforces no-self-approve):`, "",
    );
    if (actorEmail === null) return;
    if (!actorEmail.trim()) {
      setError("Approver email is required to sign.");
      return;
    }
    const note = window.prompt("Approval note (optional):", "") || "";
    setSaving("sign");
    setError("");
    try {
      const updated = await api.post(`${PCFG_API_ROOT}${selected.id}/sign/${step}/`, {
        actor_email: actorEmail.trim(),
        note,
      });
      const normalized = pcfgNormalizeVersion(updated);
      setVersions(prev => prev.map(v => v.id === normalized.id ? normalized : v));
      setNotice(`Signed step ${step} on PMT v${selected.version}.`);
    } catch (err) {
      setError(err?.body?.detail || err?.message || `Could not sign step ${step}.`);
    } finally {
      setSaving("");
    }
  };

  const rejectVersion = async () => {
    const api = typeof window !== "undefined" ? window.nsrApi : null;
    if (!api || !selected?.id) return;
    const step = currentPendingStep;
    if (!step) {
      setError("Nothing to reject — no pending step on this version.");
      return;
    }
    const actorEmail = window.prompt(
      `Reject step ${step} — your email:`, "",
    );
    if (actorEmail === null) return;
    if (!actorEmail.trim()) {
      setError("Approver email is required to reject.");
      return;
    }
    const reason = window.prompt("Rejection reason (required):", "") || "";
    if (!reason.trim()) {
      setError("Rejection reason is required.");
      return;
    }
    setSaving("reject");
    setError("");
    try {
      const updated = await api.post(`${PCFG_API_ROOT}${selected.id}/reject/${step}/`, {
        actor_email: actorEmail.trim(),
        reason: reason.trim(),
      });
      const normalized = pcfgNormalizeVersion(updated);
      setVersions(prev => prev.map(v => v.id === normalized.id ? normalized : v));
      // Rejection is terminal. The version stays on the audit chain
      // but disappears from the default list — the operator effectively
      // sees it as deleted. Refresh so the sidebar drops it.
      await fetchVersions();
      setNotice(
        `Rejected step ${step} on PMT v${selected.version}. ` +
        `Version is terminally REJECTED — clone an active version to start a fresh draft.`,
      );
    } catch (err) {
      setError(err?.body?.detail || err?.message || `Could not reject step ${step}.`);
    } finally {
      setSaving("");
    }
  };

  const submitVersion = async () => {
    const api = typeof window !== "undefined" ? window.nsrApi : null;
    if (!api || !selected?.id) return;
    const author = window.prompt("Author email:", selected.author || "");
    if (author === null) return;
    const steward = window.prompt("MGLSD Data Steward email:", "steward@mglsd.go.ug");
    if (steward === null) return;
    const dg = window.prompt("UBOS Director General email:", "dg@ubos.go.ug");
    if (dg === null) return;
    setSaving("submit");
    setError("");
    try {
      const updated = await api.post(`${PCFG_API_ROOT}${selected.id}/submit/`, {
        author_email: author,
        mglsd_steward_email: steward,
        ubos_dg_email: dg,
      });
      const normalized = pcfgNormalizeVersion(updated);
      setVersions(prev => prev.map(v => v.id === normalized.id ? normalized : v));
      setNotice(`Submitted PMT v${selected.version} for approval.`);
    } catch (err) {
      setError(err?.body?.detail || err?.message || "Could not submit PMT model version.");
    } finally {
      setSaving("");
    }
  };

  const addVariableFromCatalog = (catalogVariable) => {
    const name = pcfgVariableName(catalogVariable);
    if (!name || existingVariableNames.has(name)) return;
    const nextVariable = {
      ...catalogVariable,
      name,
      weight: pcfgNum(catalogVariable.weight),
    };
    delete nextVariable.sourceVersion;
    delete nextVariable.sourceStatus;
    patchSelected({ variables: [...variables, nextVariable] }, `Added variable ${name}.`);
    setAddModalOpen(false);
    setVariablePickSearch("");
  };

  const editVariable = (variable) => {
    const name = pcfgVariableName(variable);
    const nextWeight = window.prompt(`Weight for ${name}:`, String(variable.weight ?? 0));
    if (nextWeight === null) return;
    const nextGroup = window.prompt(`Group for ${name}:`, pcfgVariableGroup(variable));
    if (nextGroup === null) return;
    const nextTransform = window.prompt(`Transform / DSL type for ${name}:`, pcfgVariableTransform(variable));
    if (nextTransform === null) return;
    const nextVariables = variables.map(v => {
      if (pcfgVariableName(v) !== name) return v;
      return {
        ...v,
        weight: pcfgNum(nextWeight),
        group: nextGroup || pcfgVariableGroup(v),
        transform: nextTransform || pcfgVariableTransform(v),
        feature: v.feature || { type: nextTransform || "direct", path: name },
      };
    });
    patchSelected({ variables: nextVariables }, `Updated variable ${name}.`);
  };

  const importCsv = async (event) => {
    const file = event.target.files && event.target.files[0];
    event.target.value = "";
    if (!file) return;
    const text = await file.text();
    const imported = pcfgParseCsvVariables(text);
    if (!imported.length) {
      setError("CSV did not contain any variables. Use columns: name,weight,transform,group.");
      return;
    }
    patchSelected({ variables: [...variables, ...imported] }, `Imported ${imported.length} variables from CSV.`);
  };

  return (
    <div className="page">
      <PageHeader
        eyebrow="ADMIN · PMT · configuration"
        title="PMT Configuration"
        sub="Model registry — draft, calibrate, and activate PMT model versions. Activation requires dual approval (AC-PMT-MODEL-VERSION)."
        right={<>
          <button className="btn" onClick={onBack}><Icon name="chevronLeft" size={14}/> Back to dashboard</button>
          <button className="btn btn-primary" onClick={createVersion} disabled={!!saving}>
            <Icon name="plus" size={14}/> New model version
          </button>
        </>}
      />
      {(loading || error || notice) && (
        <div className={error ? "tint-quality" : "tint-update"} style={{
          padding: "10px 14px",
          borderRadius: 6,
          borderLeft: `3px solid ${error ? "var(--accent-quality)" : "var(--accent-update)"}`,
          marginBottom: 14,
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}>
          <Icon name={error ? "x" : loading ? "clock" : "check"} size={13}/>
          <span className="t-bodysm">
            {error || (loading ? "Loading PMT model versions from the live API..." : notice)}
          </span>
        </div>
      )}
      <input
        ref={fileInputRef}
        type="file"
        accept=".csv,text/csv"
        onChange={importCsv}
        style={{ display: "none" }}
      />

      {/* Two-pane: version list + version editor */}
      <div className="grid" style={{ gridTemplateColumns: '320px 1fr', gap: 16 }}>
        {/* Version registry */}
        <div className="card" style={{ padding: 0, alignSelf: 'start' }}>
          <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--neutral-200)' }}>
            <strong className="t-bodysm">Model versions</strong>
            <div className="t-cap">{versions.length} in registry · {versions.filter(v => v.status === 'active').length} active</div>
          </div>
          {versions.map(v => {
            const active = v.id === selectedId;
            return (
              <div key={v.id}
                onClick={() => setSelectedId(v.id)}
                style={{
                  padding: '12px 16px',
                  borderBottom: '1px solid var(--neutral-200)',
                  borderLeft: active ? '3px solid var(--accent-eligibility)' : '3px solid transparent',
                  background: active ? 'var(--neutral-50)' : 'transparent',
                  cursor: 'pointer',
                }}>
                <div className="row gap-2" style={{ alignItems: 'baseline' }}>
                  <strong style={{ fontSize: 15 }}>v{v.version}</strong>
                  <Chip size="sm" tone={STATUS_TONE[v.status]}>{STATUS_LABEL[v.status]}</Chip>
                  {v.status === 'active' && <Icon name="check" size={12} color="var(--accent-data)"/>}
                </div>
                <div className="t-cap mt-1" style={{ color: 'var(--neutral-600)' }}>{v.description.slice(0, 60)}{v.description.length > 60 ? '…' : ''}</div>
                <div className="t-cap mt-2 row gap-2">
                  <span>{v.variablesCount} vars</span>
                  {v.validationRSquared !== null && v.validationRSquared !== undefined && <span>· R² {pcfgNum(v.validationRSquared).toFixed(3)}</span>}
                </div>
              </div>
            );
          })}
        </div>

        {/* Version editor */}
        <div>
          {/* Version header card */}
          <div className="card" style={{ padding: 0 }}>
            <div style={{ padding: '18px 20px', display: 'grid', gridTemplateColumns: '64px 1fr auto', gap: 16, alignItems: 'flex-start' }}>
              <div style={{
                width: 64, height: 64, borderRadius: 8,
                background: 'var(--accent-eligibility-bg, var(--neutral-100))',
                color: 'var(--accent-eligibility)',
                display: 'grid', placeItems: 'center',
                fontSize: 22, fontWeight: 700,
              }}>v{selected.version}</div>
              <div style={{ minWidth: 0 }}>
                <div className="row gap-2" style={{ marginBottom: 4, alignItems: 'baseline' }}>
                  <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>PMT v{selected.version}</h2>
                  <Chip tone={STATUS_TONE[selected.status]}>{STATUS_LABEL[selected.status]}</Chip>
                </div>
                <div className="t-bodysm" style={{ color: 'var(--neutral-700)' }}>{selected.description}</div>
                <div className="t-cap mt-2">
                  Author: <strong>{selected.author}</strong>
                  {selected.approvedBy && <> · Approved by <strong>{selected.approvedBy}</strong> on {selected.approvedAt}</>}
                </div>
              </div>
              <div className="row gap-2">
                {selected.status === 'draft' && <>
                  <button className="btn" onClick={cloneVersion} disabled={!!saving}><Icon name="copy" size={13}/> Clone</button>
                  <button className="btn btn-primary" onClick={submitVersion} disabled={!!saving}><Icon name="upload" size={13}/> Submit for approval</button>
                </>}
                {selected.status === 'pending_approval' && <>
                  <button className="btn" onClick={rejectVersion}
                          disabled={!!saving || currentPendingStep === null}
                          title={currentPendingStep === null
                            ? "No pending step on this version"
                            : `Reject sign-off step ${currentPendingStep} — terminal: the version moves to REJECTED and disappears from the default list. Clone an active version to start a fresh draft.`}>
                    <Icon name="x" size={13}/> {saving === "reject" ? "Rejecting…" : `Reject step ${currentPendingStep || ""}`.trim()}
                  </button>
                  <button className="btn btn-primary" onClick={signVersion}
                          disabled={!!saving || currentPendingStep === null}
                          title={currentPendingStep === null
                            ? "No pending step on this version"
                            : `Sign sign-off step ${currentPendingStep}. The server enforces AC-PMT-NO-SELF-APPROVE.`}>
                    <Icon name="check" size={13}/> {saving === "sign"
                      ? "Signing…"
                      : currentPendingStep === 3
                        ? "Sign step 3 & activate"
                        : `Sign step ${currentPendingStep || ""}`.trim()}
                  </button>
                </>}
                {selected.status === 'active' && <>
                  <button className="btn" onClick={cloneVersion} disabled={!!saving}><Icon name="copy" size={13}/> Clone as draft</button>
                </>}
                {selected.status === 'retired' && <>
                  <button className="btn" onClick={cloneVersion} disabled={!!saving}><Icon name="copy" size={13}/> Clone as draft</button>
                </>}
                {selected.status === 'rejected' && (
                  <span className="t-cap muted" title="Rejected versions are terminal — preserved on the audit chain but no further actions available. Clone an active version to revise.">
                    Terminal — no further actions
                  </span>
                )}
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', borderTop: '1px solid var(--neutral-200)' }}>
              {[
                ['Variables',          selected.variablesCount],
                ['Intercept',          pcfgNum(selected.intercept).toFixed(4)],
                ['Validation R²',      selected.validationRSquared === null || selected.validationRSquared === undefined ? "—" : pcfgNum(selected.validationRSquared).toFixed(3)],
                ['Calibration year',   selected.calibrationYearEnd || "—"],
              ].map(([k, v], i) => (
                <div key={k} style={{
                  padding: '10px 16px',
                  borderRight: i < 3 ? '1px solid var(--neutral-200)' : 0,
                }}>
                  <div className="t-cap">{k}</div>
                  <div className="t-num" style={{ fontSize: 18, fontWeight: 600, marginTop: 2 }}>{v}</div>
                </div>
              ))}
            </div>

            {selected.status === 'draft' && (
              <div className="tint-update" style={{
                padding: '10px 20px',
                borderTop: '1px solid var(--neutral-200)',
                borderLeft: '3px solid var(--accent-update)',
                display: 'flex', alignItems: 'center', gap: 10,
              }}>
                <Icon name="info" size={13} color="var(--accent-update)"/>
                <span className="t-bodysm">
                  This draft is editable. <strong>Submit for approval</strong> to lock variables/weights and start the dual-approval workflow.
                </span>
              </div>
            )}
            {selected.status === 'active' && (
              <div className="tint-update" style={{
                padding: '10px 20px',
                borderTop: '1px solid var(--neutral-200)',
                borderLeft: '3px solid var(--accent-data)',
                background: 'var(--accent-data-bg, var(--neutral-50))',
                display: 'flex', alignItems: 'center', gap: 10,
              }}>
                <Icon name="check" size={13} color="var(--accent-data)"/>
                <span className="t-bodysm">
                  Active model — read-only. To change variables or weights, clone as draft.
                </span>
              </div>
            )}
          </div>

          {/* Tabs */}
          <div role="tablist" style={{
            display: 'flex', gap: 0,
            borderBottom: '1px solid var(--neutral-300)',
            marginTop: 16, flexWrap: 'wrap',
          }}>
            {[
              { id: 'variables', label: 'Variables & weights' },
              { id: 'bands',     label: 'Bands & strategy' },
              { id: 'calib',     label: 'Calibration' },
              { id: 'workflow',  label: 'Approval & lifecycle' },
              { id: 'sim',       label: 'Simulator' },
            ].map(t => {
              const active = t.id === tab;
              return (
                <button key={t.id} onClick={() => setTab(t.id)} style={{
                  display: 'inline-flex', alignItems: 'center', gap: 6,
                  padding: '10px 16px', border: 0, marginBottom: -1,
                  borderBottom: active ? '2px solid var(--primary-900)' : '2px solid transparent',
                  background: 'transparent', cursor: 'pointer',
                  color: active ? 'var(--primary-900)' : 'var(--neutral-700)',
                  fontWeight: active ? 600 : 500, fontSize: 13.5,
                }}>{t.label}</button>
              );
            })}
          </div>

          {/* Tab content */}
          {tab === 'variables' && (
            <div className="card" style={{ borderTopLeftRadius: 0, borderTopRightRadius: 0, padding: 0 }}>
              <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--neutral-200)', display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                <div className="search" style={{ maxWidth: 300, height: 32, background: 'var(--neutral-0)' }}>
                  <Icon name="search" size={14} color="var(--neutral-500)"/>
                  <input value={varSearch} onChange={e => setVarSearch(e.target.value)} placeholder="Search variable name…"/>
                </div>
                <select className="field-select" value={varGroupFilter} onChange={e => setVarGroupFilter(e.target.value)} style={{ height: 32, width: 'auto', minWidth: 140 }}>
                  <option value="All">All groups</option>
                  {groups.map(g => <option key={g}>{g}</option>)}
                </select>
                <span className="t-cap">{filteredVariables.length} of {variables.length}</span>
                <div style={{ flex: 1 }}/>
                {isEditable && <>
                  <button className="btn btn-sm" onClick={() => fileInputRef.current && fileInputRef.current.click()} disabled={!!saving}>
                    <Icon name="upload" size={12}/> Import CSV
                  </button>
                  <button className="btn btn-sm" onClick={() => setAddModalOpen(true)} disabled={!!saving}>
                    <Icon name="plus" size={12}/> Add variable
                  </button>
                </>}
              </div>
              <table className="tbl" style={{ boxShadow: 'none' }}>
                <thead>
                  <tr>
                    <th>Variable</th>
                    <th>Group</th>
                    <th>Transform</th>
                    <th style={{ textAlign: 'right' }}>Weight (β)</th>
                    <th style={{ width: '20%' }}>Magnitude</th>
                    {isEditable && <th className="col-actions"></th>}
                  </tr>
                </thead>
                <tbody>
                  {filteredVariables.map(v => {
                    const name = pcfgVariableName(v);
                    const group = pcfgVariableGroup(v);
                    const transform = pcfgVariableTransform(v);
                    const weight = pcfgNum(v.weight);
                    const max = Math.max(...variables.map(x => Math.abs(pcfgNum(x.weight))), 0.001);
                    const isNeg = weight < 0;
                    return (
                      <tr key={name}>
                        <td className="t-mono" style={{ fontSize: 12.5 }}>{name}</td>
                        <td><Chip size="sm">{group}</Chip></td>
                        <td className="t-mono t-cap">{transform}</td>
                        <td className="t-num t-bodysm" style={{ textAlign: 'right', fontWeight: 600, color: isNeg ? 'var(--accent-quality)' : 'var(--accent-data)' }}>
                          {weight >= 0 ? '+' : ''}{weight.toFixed(3)}
                        </td>
                        <td>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <div style={{
                              flex: 1, height: 6, background: 'var(--neutral-100)', borderRadius: 3, overflow: 'hidden',
                              position: 'relative',
                            }}>
                              <div style={{
                                position: 'absolute', left: '50%',
                                width: '1px', height: '100%', background: 'var(--neutral-300)',
                              }}/>
                              <div style={{
                                position: 'absolute',
                                left: isNeg ? `${50 - (Math.abs(weight)/max)*50}%` : '50%',
                                width: `${(Math.abs(weight)/max)*50}%`, height: '100%',
                                background: isNeg ? 'var(--accent-quality)' : 'var(--accent-data)',
                              }}/>
                            </div>
                          </div>
                        </td>
                        {isEditable && <td className="col-actions">
                          <button className="icon-btn" title="Edit" onClick={() => editVariable(v)} disabled={!!saving}>
                            <Icon name="edit" size={12}/>
                          </button>
                        </td>}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <div style={{
                padding: '12px 16px',
                borderTop: '1px solid var(--neutral-200)',
                background: 'var(--neutral-50)',
                display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap',
              }}>
                <span className="t-cap">Intercept</span>
                <span className="t-mono" style={{ fontWeight: 600 }}>{pcfgNum(selected.intercept).toFixed(4)}</span>
                <span style={{ width: 1, height: 16, background: 'var(--neutral-200)' }}/>
                <span className="t-cap">Σ |β|</span>
                <span className="t-num" style={{ fontWeight: 600 }}>{totalAbsWeight.toFixed(3)}</span>
                <div style={{ flex: 1 }}/>
                <span className="t-cap">
                  Engine: <span className="t-mono">apps.pmt.engine.compute_pmt</span> ·
                  Feature evaluator: <span className="t-mono">apps.pmt.feature_evaluator</span>
                </span>
              </div>
            </div>
          )}

          {tab === 'bands' && (
            <div className="card" style={{ borderTopLeftRadius: 0, borderTopRightRadius: 0, padding: 20 }}>
              <div className="row gap-3 mb-3" style={{ alignItems: 'flex-start', flexWrap: 'wrap' }}>
                <div style={{ flex: '1 1 320px' }}>
                  <strong>Band strategy</strong>
                  <div className="t-cap mt-1">
                    How a household's <code className="t-mono">score</code> maps to a band.
                    Switching strategies requires resubmitting the model for approval.
                  </div>
                </div>
                <div className="row gap-2">
                  {[
                    ['threshold',  'Fixed score thresholds', 'Cut on score values declared on the model'],
                    ['percentile', 'Population percentiles', 'Cut on population percentile ranks; thresholds recompute daily'],
                  ].map(([id, label, desc]) => {
                    const active = selected.bandStrategy === id;
                    return (
                      <div key={id} style={{
                        padding: 12, borderRadius: 6, width: 220,
                        border: `2px solid ${active ? 'var(--accent-eligibility)' : 'var(--neutral-200)'}`,
                        background: active ? 'var(--accent-eligibility-bg, var(--neutral-50))' : 'var(--neutral-0)',
                        cursor: isEditable ? 'pointer' : 'default',
                        opacity: isEditable || active ? 1 : 0.7,
                      }}>
                        <div className="row gap-2" style={{ alignItems: 'center' }}>
                          <span style={{
                            width: 14, height: 14, borderRadius: '50%',
                            border: `2px solid ${active ? 'var(--accent-eligibility)' : 'var(--neutral-400)'}`,
                            background: active ? 'var(--accent-eligibility)' : 'transparent',
                          }}/>
                          <strong className="t-bodysm">{label}</strong>
                        </div>
                        <div className="t-cap mt-2">{desc}</div>
                      </div>
                    );
                  })}
                </div>
              </div>

              <div style={{
                marginTop: 18, padding: 16, borderRadius: 6,
                border: '1px solid var(--neutral-200)',
              }}>
                <div className="row gap-2 mb-3">
                  <strong>Band cutoffs</strong>
                  <Chip size="sm" tone="data">{selected.bandStrategy}</Chip>
                  <span className="t-cap">— {selected.bandStrategy === 'percentile' ? 'population percentile ranks (0–100)' : 'score thresholds'}</span>
                </div>
                <table className="tbl" style={{ boxShadow: 'none' }}>
                  <thead><tr><th>Band</th><th>{selected.bandStrategy === 'percentile' ? 'Upper percentile rank' : 'Upper score threshold'}</th><th>Daily empirical threshold</th><th>Notes</th></tr></thead>
                  <tbody>
                    {Object.entries(selected.bandCutoffs).map(([band, cutoff]) => (
                      <tr key={band}>
                        <td><BandChip band={band}/></td>
                        <td className="t-num">{cutoff}{selected.bandStrategy === 'percentile' ? '%' : ''}</td>
                        <td className="t-mono t-bodysm">
                          {selected.status === 'active' && PMT_ACTIVE.thresholdsLatest[band]
                            ? `≤ ${PMT_ACTIVE.thresholdsLatest[band].toFixed(3)}`
                            : <span className="muted">—</span>}
                        </td>
                        <td className="t-cap">
                          {band === 'extreme_poverty' && 'MGLSD floor — SCG eligibility'}
                          {band === 'poverty'         && 'OPM-PDM primary cohort'}
                          {band === 'vulnerable'      && 'Programme co-targeting cohort'}
                          {band === 'not_poor'        && 'Default — excluded from targeted programmes'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {selected.bandStrategy === 'percentile' && (
                  <div className="tint-update" style={{
                    marginTop: 14, padding: 12, borderRadius: 4,
                    borderLeft: '3px solid var(--accent-update)',
                  }}>
                    <div className="row gap-2" style={{ marginBottom: 4 }}>
                      <Icon name="info" size={13} color="var(--accent-update)"/>
                      <strong className="t-bodysm">Percentile band thresholds</strong>
                    </div>
                    <div className="t-bodysm muted">
                      The score-thresholds shown in the third column are recomputed daily by{' '}
                      <span className="t-mono">apps.pmt.tasks.recompute_band_thresholds_task</span>{' '}
                      against the full PMTResult population. The cutoffs above are policy values — the
                      empirical thresholds drift as the registry grows.
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {tab === 'calib' && (
            <div className="card" style={{ borderTopLeftRadius: 0, borderTopRightRadius: 0, padding: 20, display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 16 }}>
              <div>
                <h4 className="t-h3" style={{ margin: '0 0 10px' }}>Calibration provenance</h4>
                <table className="tbl" style={{ boxShadow: 'none' }}>
                  <tbody>
                    <tr><td className="muted" style={{ width: 200 }}>Calibration dataset</td><td>{selected.calibrationDataset}</td></tr>
                    <tr><td className="muted">Latest year of dataset</td><td className="t-num">{selected.calibrationYearEnd || "—"}</td></tr>
                    <tr><td className="muted">Sample size</td><td className="t-num">{(34091).toLocaleString()} households</td></tr>
                    <tr><td className="muted">Validation R²</td><td className="t-num">{selected.validationRSquared === null || selected.validationRSquared === undefined ? "—" : pcfgNum(selected.validationRSquared).toFixed(3)}</td></tr>
                    <tr><td className="muted">Mean absolute error</td><td className="t-num">0.412</td></tr>
                    <tr><td className="muted">Targeting accuracy (bottom-30%)</td><td className="t-num">82.4%</td></tr>
                    <tr><td className="muted">Calibration method</td><td>OLS · ADR-0025 DSL</td></tr>
                  </tbody>
                </table>
              </div>
              <div className="tint-update" style={{
                padding: 14, borderRadius: 6, borderLeft: '3px solid var(--accent-update)',
                alignSelf: 'start',
              }}>
                <div className="row gap-2" style={{ marginBottom: 6 }}>
                  <Icon name="info" size={13} color="var(--accent-update)"/>
                  <strong className="t-bodysm">Recalibration cadence (ADR-0023)</strong>
                </div>
                <div className="t-bodysm muted" style={{ lineHeight: 1.55 }}>
                  PMT models recalibrate every 3 years after the latest year of the source dataset.
                  Calibration year-end <strong>{selected.calibrationYearEnd || "not set"}</strong>
                  {selected.calibrationYearEnd ? <> means recalibration is due in{' '}
                  <strong>{2027 - selected.calibrationYearEnd} year{2027 - selected.calibrationYearEnd === 1 ? '' : 's'}</strong>{' '}
                  ({selected.calibrationYearEnd + 3}).</> : " must be set before approval."}
                </div>
                <div style={{
                  marginTop: 12, padding: '8px 12px',
                  background: 'var(--neutral-0)', borderRadius: 4,
                  border: '1px solid var(--neutral-200)',
                  fontSize: 12, fontFamily: 'var(--font-mono)',
                }}>
                  Trigger: <span style={{ color: 'var(--accent-quality)' }}>year_now - calibration_year_end ≥ 3</span>
                </div>
              </div>
            </div>
          )}

          {tab === 'workflow' && (
            <div className="card" style={{ borderTopLeftRadius: 0, borderTopRightRadius: 0, padding: 20 }}>
              <h4 className="t-h3" style={{ margin: '0 0 14px' }}>Approval & lifecycle</h4>
              <div style={{
                display: 'flex', alignItems: 'center', gap: 4,
                padding: '14px 0', overflowX: 'auto',
              }}>
                {[
                  { id: 'draft',            label: 'Draft',            icon: 'edit'  },
                  { id: 'pending_approval', label: 'Pending approval', icon: 'clock' },
                  { id: 'active',           label: 'Active',           icon: 'check' },
                  { id: 'retired',          label: 'Retired',          icon: 'archive' },
                ].map((s, i, arr) => {
                  const reached = ['draft','pending_approval','active','retired'].indexOf(selected.status) >= i;
                  const current = selected.status === s.id;
                  return (
                    <React.Fragment key={s.id}>
                      <div style={{
                        padding: '10px 14px',
                        borderRadius: 6,
                        border: current ? '2px solid var(--primary-900)' : `1px solid ${reached ? 'var(--accent-data)' : 'var(--neutral-300)'}`,
                        background: current ? 'var(--primary-100)' : reached ? 'var(--accent-data-bg, var(--neutral-50))' : 'var(--neutral-0)',
                        color: current ? 'var(--primary-900)' : reached ? 'var(--accent-data)' : 'var(--neutral-500)',
                        fontWeight: current ? 600 : 500, fontSize: 13,
                        display: 'inline-flex', alignItems: 'center', gap: 6,
                        flex: '0 0 auto',
                      }}>
                        <Icon name={reached && !current ? 'check' : s.icon} size={12}/>
                        {s.label}
                      </div>
                      {i < arr.length - 1 && (
                        <div style={{ flex: 1, height: 1, minWidth: 24, background: reached ? 'var(--accent-data)' : 'var(--neutral-300)' }}/>
                      )}
                    </React.Fragment>
                  );
                })}
              </div>

              {/* Dual approval chain */}
              <div className="mt-4">
                <strong className="t-bodysm">Dual approval chain (AC-PMT-MODEL-VERSION)</strong>
                <div className="row gap-3 mt-3" style={{ flexWrap: 'wrap' }}>
                  {[
                    { step: 1, role: 'Author', who: selected.author, status: 'signed', at: selected.createdAt },
                    { step: 2, role: 'MGLSD Data Steward', who: selected.status !== 'draft' ? 'Statistics review · MGLSD' : 'awaiting submission', status: selected.status === 'draft' ? 'pending' : 'signed', at: selected.approvedAt },
                    { step: 3, role: 'Director General · UBOS', who: selected.approvedBy || 'awaiting steward sign-off', status: selected.status === 'active' || selected.status === 'retired' ? 'signed' : 'pending', at: selected.approvedAt },
                  ].map(s => (
                    <div key={s.step} style={{
                      flex: '1 1 240px', minWidth: 220,
                      padding: 14, borderRadius: 6,
                      border: '1px solid var(--neutral-200)',
                      borderLeft: `3px solid ${s.status === 'signed' ? 'var(--accent-data)' : 'var(--accent-quality)'}`,
                      background: 'var(--neutral-0)',
                    }}>
                      <div className="row gap-2" style={{ marginBottom: 6 }}>
                        <div style={{
                          width: 22, height: 22, borderRadius: '50%',
                          background: s.status === 'signed' ? 'var(--accent-data-bg, var(--neutral-100))' : 'var(--neutral-100)',
                          color: s.status === 'signed' ? 'var(--accent-data)' : 'var(--neutral-500)',
                          display: 'grid', placeItems: 'center', fontSize: 11, fontWeight: 600,
                        }}>{s.step}</div>
                        {s.status === 'signed'
                          ? <Chip size="sm" tone="data"><Icon name="check" size={10}/> signed</Chip>
                          : <Chip size="sm" tone="quality"><Icon name="clock" size={10}/> pending</Chip>}
                      </div>
                      <div className="t-bodysm" style={{ fontWeight: 600 }}>{s.role}</div>
                      <div className="t-cap mt-1">{s.who}</div>
                      {s.at && <div className="t-cap mt-1">{s.at}</div>}
                    </div>
                  ))}
                </div>
              </div>

              <div className="tint-update mt-4" style={{
                padding: 12, borderRadius: 4, borderLeft: '3px solid var(--accent-update)',
              }}>
                <div className="row gap-2" style={{ marginBottom: 4 }}>
                  <Icon name="shield" size={13} color="var(--accent-update)"/>
                  <strong className="t-bodysm">No self-approval (AC-PMT-NO-SELF-APPROVE)</strong>
                </div>
                <div className="t-bodysm muted">
                  The model's author cannot sign off the steward or director steps. Activation atomically
                  retires the previous active version and writes an audit row (<span className="t-mono">apps.pmt.services.activate_model_version</span>).
                </div>
              </div>
            </div>
          )}

          {tab === 'sim' && (
            <div className="card" style={{ borderTopLeftRadius: 0, borderTopRightRadius: 0, padding: 20 }}>
              <h4 className="t-h3" style={{ margin: '0 0 4px' }}>Score simulator</h4>
              <div className="t-cap mb-3">Plug in a household input set, see the score + band this model would assign.</div>

              <div className="grid" style={{ gridTemplateColumns: '1fr 1fr', gap: 16, alignItems: 'flex-start' }}>
                <div style={{
                  padding: 16, borderRadius: 6, border: '1px solid var(--neutral-200)',
                  background: 'var(--neutral-50)',
                }}>
                  <strong className="t-bodysm">Household inputs</strong>
                  <div style={{ marginTop: 10, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                    {[
                      ['Member count',          '6'],
                      ['Rooms',                 '2'],
                      ['Floor material',        'Earth'],
                      ['Roof material',         'Metal'],
                      ['Has electricity',       'No'],
                      ['Owns motorcycle',       'No'],
                      ['Owns television',       'No'],
                      ['Has cellphone',         'Yes'],
                      ['Head education',        'Primary completed'],
                      ['Open defecation',       'Yes'],
                    ].map(([k, v]) => (
                      <label key={k} style={{ display: 'flex', flexDirection: 'column', fontSize: 12, gap: 4 }}>
                        <span className="muted">{k}</span>
                        <input className="field-input" defaultValue={v} style={{ padding: '4px 6px', height: 28, fontSize: 13 }}/>
                      </label>
                    ))}
                  </div>
                  <button className="btn btn-primary mt-3"><Icon name="play" size={13}/> Recompute</button>
                </div>

                <div style={{
                  padding: 16, borderRadius: 6,
                  border: '1px solid var(--neutral-200)',
                  borderLeft: '3px solid var(--accent-eligibility)',
                  background: 'var(--neutral-0)',
                }}>
                  <div className="t-cap" style={{ color: 'var(--accent-eligibility)', fontWeight: 600 }}>SIMULATED SCORE</div>
                  <div style={{ fontSize: 36, fontWeight: 700, marginTop: 6 }}>2.84</div>
                  <div className="row gap-2 mt-2">
                    <BandChip band="extreme_poverty"/>
                    <span className="t-cap">band at percentile 8.2%</span>
                  </div>
                  <div style={{ marginTop: 14, padding: '10px 12px', background: 'var(--neutral-50)', borderRadius: 4 }}>
                    <div className="t-cap">Contributing variables (top 5)</div>
                    {[
                      ['open_defecation',         -0.128, -0.128],
                      ['share_children_under_15', -0.117, -0.094],
                      ['rooms_per_capita',        +0.292, +0.097],
                      ['head_edu_completed_primary', +0.099, +0.099],
                      ['any_cellphone',           +0.185, +0.185],
                    ].map(([n, w, c]) => (
                      <div key={n} className="row gap-2 mt-2" style={{ alignItems: 'baseline' }}>
                        <span className="t-mono" style={{ fontSize: 12, flex: 1, minWidth: 0, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{n}</span>
                        <span className="t-cap">β {w >= 0 ? '+' : ''}{w.toFixed(3)}</span>
                        <Chip size="sm" tone={c >= 0 ? 'data' : 'quality'}>{c >= 0 ? '+' : ''}{c.toFixed(3)}</Chip>
                      </div>
                    ))}
                  </div>
                  <div className="t-cap mt-3">Simulator is sandboxed — it does not write a PMTResult row.</div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="t-cap mt-4" style={{ textAlign: 'center' }}>
        Configuration changes are audit-logged. Activation atomically retires the prior active version
        and queues a population-wide rescore (<span className="t-mono">apps.pmt.tasks</span>).
      </div>

      {addModalOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Add PMT variable"
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 80,
            background: "rgba(15, 23, 42, 0.35)",
            display: "grid",
            placeItems: "center",
            padding: 24,
          }}
        >
          <div className="card" style={{ width: "min(880px, 100%)", maxHeight: "82vh", padding: 0, overflow: "hidden" }}>
            <div style={{
              padding: "14px 18px",
              borderBottom: "1px solid var(--neutral-200)",
              display: "flex",
              alignItems: "center",
              gap: 12,
            }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <h3 className="t-h3" style={{ margin: 0 }}>Add variable</h3>
                <div className="t-cap mt-1">
                  Select from variables already stored on PMT model versions in the database.
                </div>
              </div>
              <button className="icon-btn" title="Close" onClick={() => setAddModalOpen(false)}>
                <Icon name="x" size={16}/>
              </button>
            </div>
            <div style={{ padding: "12px 18px", borderBottom: "1px solid var(--neutral-200)", display: "flex", gap: 10, alignItems: "center" }}>
              <div className="search" style={{ maxWidth: 420, height: 34, background: "var(--neutral-0)" }}>
                <Icon name="search" size={14} color="var(--neutral-500)"/>
                <input
                  value={variablePickSearch}
                  onChange={e => setVariablePickSearch(e.target.value)}
                  placeholder="Search database variables..."
                  autoFocus
                />
              </div>
              <span className="t-cap">{filteredDatabaseVariables.length} available</span>
            </div>
            <div style={{ maxHeight: "58vh", overflow: "auto" }}>
              <table className="tbl" style={{ boxShadow: "none" }}>
                <thead>
                  <tr>
                    <th>Variable</th>
                    <th>Source</th>
                    <th>Transform</th>
                    <th style={{ textAlign: "right" }}>Weight (β)</th>
                    <th className="col-actions"></th>
                  </tr>
                </thead>
                <tbody>
                  {filteredDatabaseVariables.map(variable => {
                    const name = pcfgVariableName(variable);
                    const alreadySelected = existingVariableNames.has(name);
                    const weight = pcfgNum(variable.weight);
                    return (
                      <tr key={name}>
                        <td>
                          <div className="t-mono" style={{ fontSize: 12.5 }}>{name}</div>
                          {variable.comment && <div className="t-cap mt-1">{variable.comment}</div>}
                        </td>
                        <td>
                          <div className="row gap-2">
                            <Chip size="sm">v{variable.sourceVersion}</Chip>
                            <Chip size="sm" tone={STATUS_TONE[variable.sourceStatus]}>{STATUS_LABEL[variable.sourceStatus]}</Chip>
                          </div>
                        </td>
                        <td className="t-mono t-cap">{pcfgVariableTransform(variable)}</td>
                        <td className="t-num t-bodysm" style={{ textAlign: "right", fontWeight: 600 }}>
                          {weight >= 0 ? "+" : ""}{weight.toFixed(3)}
                        </td>
                        <td className="col-actions">
                          <button
                            className="btn btn-sm"
                            disabled={alreadySelected || !!saving}
                            onClick={() => addVariableFromCatalog(variable)}
                          >
                            {alreadySelected ? "Added" : "Use variable"}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                  {filteredDatabaseVariables.length === 0 && (
                    <tr>
                      <td colSpan="5" className="muted" style={{ padding: 24, textAlign: "center" }}>
                        No database variables match this search.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

Object.assign(window, { PmtConfigurationScreen, PCFG_VERSIONS });
