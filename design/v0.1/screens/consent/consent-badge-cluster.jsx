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

Object.assign(window, { ConsentBadgeCluster, projectConsentMatrix });
