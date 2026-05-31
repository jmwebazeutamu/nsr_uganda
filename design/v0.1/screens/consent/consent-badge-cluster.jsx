/* global React, Icon, ConsentStateChip, AuditDrawer */
// NSR MIS — Consent badge cluster (US-CONSENT-08)
// =====================================================
// Reusable chip row showing a member's per-purpose consent at a glance.
// Mounted on household detail, member detail, DDUP compare, and the UPD
// reviewer. Reads GET /api/v1/consent/members/{member_id} (cache 60s) and
// renders one ConsentStateChip per purpose at caption size. Clicking a chip
// opens the per-purpose history side panel (the existing AuditDrawer).

const { useState: useStateBadge, useEffect: useEffectBadge } = React;

// Pure: project the matrix API response into the chip list the cluster
// renders. Un-captured purposes (state === null) are dropped so the row shows
// only purposes the member has actually acted on. Exported for unit testing.
function projectConsentMatrix(matrix) {
  const purposes = (matrix && matrix.purposes) || [];
  return purposes
    .filter(p => p.state)  // drop un-captured
    .map(p => ({
      code: p.purpose_code,
      name: p.name,
      state: p.state_label || p.state,
      withdrawable: !!p.withdrawable,
    }));
}

// 60s in-memory cache keyed by member id (per the design — avoids re-fetching
// the matrix every time a badge cluster mounts on a busy reviewer screen).
const _consentMatrixCache = {};
const CONSENT_MATRIX_TTL_MS = 60_000;

function _now() {
  return (typeof performance !== "undefined" && performance.now)
    ? performance.now() : 0;
}

const ConsentBadgeCluster = ({ memberId, size }) => {
  const [chips, setChips] = useStateBadge([]);
  const [openCode, setOpenCode] = useStateBadge(null);

  useEffectBadge(() => {
    if (!memberId) return undefined;
    let live = true;
    const cached = _consentMatrixCache[memberId];
    if (cached && (_now() - cached.at) < CONSENT_MATRIX_TTL_MS) {
      setChips(projectConsentMatrix(cached.data));
      return undefined;
    }
    fetch(`/api/v1/consent/members/${memberId}`, { credentials: "same-origin" })
      .then(r => (r.ok ? r.json() : null))
      .then(data => {
        if (!live || !data) return;
        _consentMatrixCache[memberId] = { data, at: _now() };
        setChips(projectConsentMatrix(data));
      })
      .catch(() => {});
    return () => { live = false; };
  }, [memberId]);

  if (!chips.length) return null;
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
      {chips.map(c => (
        <button
          key={c.code}
          onClick={() => setOpenCode(c.code)}
          title={`${c.name} — ${c.state}${c.withdrawable ? "" : " (locked)"}`}
          style={{ border: "none", background: "none", padding: 0, cursor: "pointer", fontSize: "13px" }}>
          <ConsentStateChip state={c.state} size={size || "sm"}/>
        </button>
      ))}
      {openCode && typeof AuditDrawer !== "undefined" && (
        <AuditDrawer
          entityType="consent.record"
          entityId={`${memberId}:${openCode}`}
          onClose={() => setOpenCode(null)}/>
      )}
    </div>
  );
};

// DPPA lawful-basis enum → human label (the matrix API returns the raw enum).
const BASIS_LABELS = {
  CONSENT: "Consent", PUBLIC_TASK: "Public task", CONTRACT: "Contract",
  VITAL_INTEREST: "Vital interest", LEGAL_OBLIGATION: "Legal obligation",
  STATISTICAL_EXEMPTION: "Statistical exemption",
};

// ConsentStatusCard — the full per-purpose consent breakdown for a member
// (US-CONSENT-08 detail). Renders every ACTIVE purpose with its current state
// (Granted / Refused / Withdrawn / Pending …), lawful basis, and capture date.
// Reads GET /api/v1/consent/members/{memberId} (shares the 60s cache with the
// badge cluster). Renders a "module dark / nothing captured" note rather than
// disappearing, so the card is always present on the Consent tab.
const ConsentStatusCard = ({ memberId, title }) => {
  const [matrix, setMatrix] = useStateBadge(null);
  const [state, setState] = useStateBadge("loading"); // loading | ready | error

  useEffectBadge(() => {
    if (!memberId) { setState("error"); return undefined; }
    let live = true;
    const apply = (data) => {
      if (!live) return;
      _consentMatrixCache[memberId] = { data, at: _now() };
      setMatrix(data); setState("ready");
    };
    const cached = _consentMatrixCache[memberId];
    if (cached && (_now() - cached.at) < CONSENT_MATRIX_TTL_MS) {
      setMatrix(cached.data); setState("ready"); return undefined;
    }
    fetch(`/api/v1/consent/members/${memberId}`, { credentials: "same-origin" })
      .then(r => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(apply)
      .catch(() => { if (live) setState("error"); });
    return () => { live = false; };
  }, [memberId]);

  const purposes = (matrix && matrix.purposes) || [];
  const stateChip = (p) => {
    if (!p.state) return <span className="muted" style={{ fontSize: 12 }}>Not captured</span>;
    if (typeof window.ConsentStateChip === "function") {
      return React.createElement(window.ConsentStateChip, { state: p.state_label || p.state, size: "sm" });
    }
    return <span style={{ fontSize: 12 }}>{p.state_label || p.state}</span>;
  };

  return (
    <div style={{
      border: "1px solid var(--neutral-200)", borderRadius: 6,
      background: "var(--neutral-0)", overflow: "hidden",
    }}>
      <div style={{
        padding: "12px 16px", borderBottom: "1px solid var(--neutral-200)",
        display: "flex", alignItems: "center", gap: 8,
      }}>
        <Icon name="shield" size={14} color="var(--accent-system, #37474F)"/>
        <strong style={{ fontSize: 13.5 }}>{title || "Consent detail · per purpose"}</strong>
      </div>
      {state === "loading" && (
        <div className="muted t-bodysm" style={{ padding: 16 }}>Loading consent…</div>
      )}
      {state === "error" && (
        <div className="muted t-bodysm" style={{ padding: 16 }}>
          No per-purpose consent on record yet (or the consent module is not enabled).
        </div>
      )}
      {state === "ready" && (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ textAlign: "left", color: "var(--neutral-500)" }}>
              <th style={{ padding: "8px 16px", fontWeight: 600 }}>Purpose</th>
              <th style={{ padding: "8px 16px", fontWeight: 600 }}>Lawful basis</th>
              <th style={{ padding: "8px 16px", fontWeight: 600 }}>Status</th>
              <th style={{ padding: "8px 16px", fontWeight: 600 }}>Last captured</th>
            </tr>
          </thead>
          <tbody>
            {purposes.map(p => (
              <tr key={p.purpose_code} style={{ borderTop: "1px solid var(--neutral-100)" }}>
                <td style={{ padding: "8px 16px" }}>
                  {p.name}
                  {!p.withdrawable && (
                    <Icon name="lock" size={11} color="var(--neutral-400)"
                          style={{ marginLeft: 6, verticalAlign: "middle" }}/>
                  )}
                </td>
                <td style={{ padding: "8px 16px", color: "var(--neutral-600)" }}>
                  {BASIS_LABELS[p.lawful_basis] || p.lawful_basis || "—"}
                </td>
                <td style={{ padding: "8px 16px" }}>{stateChip(p)}</td>
                <td style={{ padding: "8px 16px", color: "var(--neutral-500)" }}>
                  {p.captured_at ? String(p.captured_at).slice(0, 10) : "—"}
                </td>
              </tr>
            ))}
            {!purposes.length && (
              <tr><td colSpan={4} className="muted" style={{ padding: 16 }}>
                No active purposes in the catalogue.
              </td></tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
};

Object.assign(window, { ConsentBadgeCluster, ConsentStatusCard, projectConsentMatrix });
