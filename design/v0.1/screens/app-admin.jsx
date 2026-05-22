/* global React, ReactDOM, PmtDashboardScreen, PmtConfigurationScreen */
// NSR MIS — Admin shell
// =====================================================
// Wraps the two new PMT screens (Dashboard, Configuration) plus
// future Admin children (Reference data, Approvals, etc.). Uses
// a left sidebar so Admin reads as its own section.
//
// Honours window.__defaultScreen:
//   "admin-pmt-dashboard"     → Dashboard (default)
//   "admin-pmt-configuration" → Configuration

const { useState: useStateAdmin } = React;

const initialFromHost = (typeof window !== "undefined" && window.__defaultScreen) || "admin-pmt-dashboard";

const NAV_GROUPS = [
  {
    label: "Eligibility",
    items: [
      { id: "admin-pmt-dashboard",     label: "PMT Dashboard",      icon: "eligibility" },
      { id: "admin-pmt-configuration", label: "PMT Configuration",  icon: "sliders" },
    ],
  },
  {
    label: "Reference data",
    items: [
      { id: "admin-refdata-choicelists", label: "Choice lists", icon: "database", disabled: true },
      { id: "admin-refdata-geo",         label: "Geography",    icon: "globe",    disabled: true },
    ],
  },
  {
    label: "Workflow",
    items: [
      { id: "admin-dqa", label: "DQA rules",     icon: "shield",  disabled: true },
      { id: "admin-ddup", label: "DDUP model",   icon: "users",   disabled: true },
    ],
  },
  {
    label: "Security",
    items: [
      { id: "admin-roles", label: "Roles & scopes", icon: "lock",     disabled: true },
      { id: "admin-audit", label: "Audit chain",    icon: "file",     disabled: true },
    ],
  },
];

const AdminApp = () => {
  const [screen, setScreen] = useStateAdmin(initialFromHost);

  return (
    <div style={{ minHeight: "100vh", background: "var(--neutral-50)", display: "flex" }}>
      {/* Sidebar */}
      <aside style={{
        width: 248, flex: "0 0 248px",
        background: "var(--primary-900)",
        color: "var(--neutral-0)",
        padding: "20px 0",
        position: "sticky", top: 0, height: "100vh", overflow: "auto",
      }}>
        <div style={{ padding: "0 20px 20px", borderBottom: "1px solid rgba(255,255,255,0.1)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{
              width: 30, height: 30, borderRadius: 6,
              background: "var(--neutral-0)",
              color: "var(--primary-900)",
              display: "grid", placeItems: "center",
              fontSize: 13, fontWeight: 700,
            }}>NSR</div>
            <div>
              <div style={{ fontSize: 14, fontWeight: 600 }}>Admin Console</div>
              <div style={{ fontSize: 11, opacity: 0.7 }}>Uganda NSR MIS</div>
            </div>
          </div>
        </div>

        <nav style={{ padding: "16px 0" }}>
          {NAV_GROUPS.map(group => (
            <div key={group.label} style={{ marginBottom: 18 }}>
              <div style={{
                padding: "0 20px 6px",
                fontSize: 10, fontWeight: 600,
                letterSpacing: "0.08em", textTransform: "uppercase",
                opacity: 0.5,
              }}>{group.label}</div>
              {group.items.map(it => {
                const active = it.id === screen;
                return (
                  <button key={it.id}
                    disabled={it.disabled}
                    onClick={() => !it.disabled && setScreen(it.id)}
                    style={{
                      display: "flex", alignItems: "center", gap: 10,
                      width: "100%", padding: "8px 20px",
                      border: 0, background: active ? "rgba(255,255,255,0.15)" : "transparent",
                      borderLeft: active ? "3px solid var(--neutral-0)" : "3px solid transparent",
                      color: it.disabled ? "rgba(255,255,255,0.35)" : active ? "var(--neutral-0)" : "rgba(255,255,255,0.85)",
                      fontSize: 13.5, fontWeight: active ? 600 : 500,
                      cursor: it.disabled ? "not-allowed" : "pointer",
                      textAlign: "left",
                    }}>
                    <Icon name={it.icon} size={14}/>
                    <span style={{ flex: 1 }}>{it.label}</span>
                    {it.disabled && <span style={{ fontSize: 9, opacity: 0.6 }}>soon</span>}
                  </button>
                );
              })}
            </div>
          ))}
        </nav>

        <div style={{
          position: "absolute", bottom: 0, left: 0, right: 0,
          padding: "12px 20px",
          borderTop: "1px solid rgba(255,255,255,0.1)",
          fontSize: 11, opacity: 0.6,
        }}>
          Akello P. · NSR Coordinator
        </div>
      </aside>

      {/* Main content */}
      <main style={{ flex: 1, minWidth: 0, overflow: "auto" }}>
        <div style={{ maxWidth: 1440, margin: "0 auto", padding: "24px 24px 64px" }}>
          {screen === "admin-pmt-dashboard" && (
            <PmtDashboardScreen onOpenConfig={() => setScreen("admin-pmt-configuration")}/>
          )}
          {screen === "admin-pmt-configuration" && (
            <PmtConfigurationScreen onBack={() => setScreen("admin-pmt-dashboard")}/>
          )}
        </div>
      </main>
    </div>
  );
};

ReactDOM.createRoot(document.getElementById("app")).render(<AdminApp/>);
