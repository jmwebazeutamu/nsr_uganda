/* global React, Icon, Chip, PageHeader, KPI, useApi, nsrApi */
// NSR MIS — Admin · Reference data · Geography
// =========================================================
// UBOS administrative hierarchy. 7 levels (region → village),
// versioned for splits and the 2026 boundary review.
//
// Maps to: apps.reference_data.models.GeographicUnit
//   level · code · name · parent · effective_from/to · status
//   plus get_descendants() / get_ancestors() helpers.

const { useState: useStateGEO, useMemo: useMemoGEO } = React;

// GEO_LEVELS / GEO_LEVEL_LABEL come from v0.1/data/geo-levels.jsx —
// this file used to declare its own, as strings, while
// components/scope-edit-modal.jsx declared the same names as objects.
// One global scope, so the last file loaded won.
const GEO_STATUS_TONE = { active: "data", superseded: "quality", retired: "neutral" };

// Sample slice — anchored on Karamoja sub-region
// GEO_TREE removed — this screen reads /api/v1/admin/refdata/geography/.


// Project a /api/v1/admin/refdata/geography/ row onto the mock shape
// the JSX below renders against. children comes from
// children_count_cached, households from households_count_cached.
const _projectGeoRow = (r) => ({
  code: r.code,
  name: r.name,
  children: r.children_count || 0,
  status: r.status,
  effectiveFrom: r.effective_from || "",
  effectiveTo: r.effective_to || null,
  households: r.households_count || 0,
});

const AdminGeographyScreen = () => {
  // Breadcrumb stack — at most 7 levels deep
  const [path, setPath] = useStateGEO([{ level: "region", code: null, name: "Uganda" }]);
  const [q, setQ] = useStateGEO("");
  const [showRetired, setShowRetired] = useStateGEO(true);

  const currentLevel = path[path.length - 1].level;
  const currentParentCode = path[path.length - 1].code;

  // Live overlay — fetch the current level when the breadcrumb changes.
  const _url = `/api/v1/admin/refdata/geography/?level=${currentLevel}${
    currentParentCode ? `&parent_code=${encodeURIComponent(currentParentCode)}` : ""
  }${showRetired ? "&include_inactive=true" : ""}`;
  const [resp] = (typeof useApi === "function") ? useApi(_url) : [null];

  // Rows come from the API or the table is empty. The GEO_TREE fixture
  // that used to back this screen described a different country: four
  // regions against the registry's five, invented sub-regions, and
  // household counts in the millions. Worse, the old condition required
  // `resp.results.length`, so a level that legitimately has no children
  // fell through to the fixture and showed units that do not exist.
  const geoLoading = resp == null;
  const rows = (resp && Array.isArray(resp.results))
    ? resp.results.map(_projectGeoRow)
    : [];

  let filtered = rows;
  if (q) filtered = filtered.filter(r => r.code.toLowerCase().includes(q.toLowerCase()) || r.name.toLowerCase().includes(q.toLowerCase()));
  if (!showRetired) filtered = filtered.filter(r => r.status === "active");

  const drillTo = (row) => {
    const nextLevelIdx = GEO_LEVEL_CODES.indexOf(currentLevel) + 1;
    if (nextLevelIdx >= GEO_LEVEL_CODES.length) return;
    const nextLevel = GEO_LEVEL_CODES[nextLevelIdx];
    setQ("");
    setPath([...path, { level: nextLevel, code: row.code, name: row.name }]);
  };
  const goTo = (idx) => {
    setQ("");
    setPath(path.slice(0, idx + 1));
  };

  // KPIs — registry totals
  const totalUnits = 56 + 14 + 146 + 198 + 1602 + 10717 + 78293;

  return (
    <div className="page">
      <PageHeader
        eyebrow="ADMIN · REFERENCE DATA · geography"
        title="Geographic units"
        sub="UBOS administrative hierarchy. 7 levels, versioned for splits and the 2026 boundary review."
        right={<>
          <button className="btn"><Icon name="download" size={14}/> Export hierarchy</button>
          <button className="btn"><Icon name="upload" size={14}/> Import UBOS update</button>
          <button className="btn btn-primary"><Icon name="plus" size={14}/> New unit</button>
        </>}
      />

      <div className="grid grid-4">
        <KPI title="Geographic units" value={totalUnits.toLocaleString()} foot="All levels · 7 hierarchy depth"/>
        <KPI title="Districts" value="146" foot="9 added since 2022 boundary review" trend="up" trendValue="+9"/>
        <KPI title="Parishes" value="10,717" foot="Currently active across Uganda"/>
        <KPI title="Recently updated" value="312" foot="In the last 90 days" trend="up" trendValue="+2.1%"/>
      </div>

      {/* Breadcrumbs */}
      <div className="card mt-5" style={{ padding: '12px 16px' }}>
        <div className="row gap-2" style={{ flexWrap: 'wrap', alignItems: 'center' }}>
          {path.map((p, i) => (
            <React.Fragment key={i}>
              <button onClick={() => goTo(i)} style={{
                padding: '4px 10px', border: 0, borderRadius: 4,
                background: i === path.length - 1 ? 'var(--primary-100)' : 'transparent',
                color: i === path.length - 1 ? 'var(--primary-900)' : 'var(--accent-system)',
                fontSize: 13, fontWeight: i === path.length - 1 ? 600 : 500,
                cursor: 'pointer',
                display: 'inline-flex', alignItems: 'center', gap: 6,
              }}>
                <Icon name={i === 0 ? "globe" : "chevronRight"} size={12}/>
                <span>{p.name}</span>
                {p.code && <span className="t-mono t-cap" style={{ fontSize: 10, opacity: 0.7 }}>{p.code}</span>}
              </button>
              {i < path.length - 1 && <Icon name="chevronRight" size={11} color="var(--neutral-400)"/>}
            </React.Fragment>
          ))}
        </div>
      </div>

      {/* Filter */}
      <div className="card mt-4" style={{ padding: '12px 16px' }}>
        <div className="row gap-3" style={{ flexWrap: 'wrap', alignItems: 'center' }}>
          <Chip tone="data">{GEO_LEVEL_LABEL[currentLevel]}</Chip>
          <span className="t-cap">
            {geoLoading
              ? "loading\u2026"
              : rows.length === 0
                ? "no units at this level"
                : `${filtered.length} of ${rows.length}`}
          </span>
          <div className="search" style={{ maxWidth: 320, height: 32 }}>
            <Icon name="search" size={13} color="var(--neutral-500)"/>
            <input value={q} onChange={e => setQ(e.target.value)} placeholder={`Search ${GEO_LEVEL_LABEL[currentLevel].toLowerCase()} code or name…`}/>
          </div>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <input type="checkbox" checked={showRetired} onChange={e => setShowRetired(e.target.checked)}/>
            <span className="t-bodysm">Show retired / superseded</span>
          </label>
          <div style={{ flex: 1 }}/>
          {currentLevel !== "village" && <button className="btn btn-sm"><Icon name="download" size={12}/> Export this level</button>}
        </div>
      </div>

      {/* Table */}
      <div className="card mt-4">
        <table className="tbl">
          <thead>
            <tr>
              <th>Code</th>
              <th>Name</th>
              <th>{currentLevel === "village" ? "Households" : "Children"}</th>
              <th>Status</th>
              <th>Effective from</th>
              <th>Notes</th>
              <th className="col-actions"></th>
            </tr>
          </thead>
          <tbody>
            {filtered.map(r => (
              <tr key={r.code}
                onClick={() => r.children > 0 && drillTo(r)}
                style={{ cursor: r.children > 0 ? 'pointer' : 'default', opacity: r.status !== 'active' ? 0.7 : 1 }}>
                <td className="t-mono">{r.code}</td>
                <td>
                  <div style={{ fontWeight: 500 }}>{r.name}</div>
                  <div className="t-cap">{r.households.toLocaleString()} households scored</div>
                </td>
                <td className="t-num">{r.children}</td>
                <td><Chip size="sm" tone={GEO_STATUS_TONE[r.status]}>{r.status}</Chip></td>
                <td className="t-cap" style={{ whiteSpace: 'nowrap' }}>
                  {r.effectiveFrom}
                  {r.effectiveTo && <div className="t-cap" style={{ color: 'var(--accent-quality)' }}>→ {r.effectiveTo}</div>}
                </td>
                <td className="t-cap" style={{ color: 'var(--neutral-600)' }}>{r.note || '—'}</td>
                <td className="col-actions">
                  {r.children > 0 && <Icon name="chevronRight" size={16} color="var(--neutral-500)"/>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="tint-update mt-4" style={{
        padding: 14, borderRadius: 6, borderLeft: '3px solid var(--accent-update)',
      }}>
        <div className="row gap-2" style={{ marginBottom: 4 }}>
          <Icon name="info" size={13} color="var(--accent-update)"/>
          <strong className="t-bodysm">Versioning over deletion</strong>
        </div>
        <div className="t-bodysm muted">
          When UBOS splits a district or renames a sub-county, the old row becomes <span className="t-mono">superseded</span> with an{' '}
          <span className="t-mono">effective_to</span> date — it stays readable so historical intake data is interpretable. The new
          row gets <span className="t-mono">effective_from</span> = split date. <code>get_ancestors()</code> and{' '}
          <code>get_descendants()</code> respect the active-on-date for bulk walks.
        </div>
      </div>
    </div>
  );
};

Object.assign(window, { AdminGeographyScreen });
