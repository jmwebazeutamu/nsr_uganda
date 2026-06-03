/* global React, ReactDOM,
   PmtDashboardScreen, PmtConfigurationScreen,
   AdminChoiceListsScreen, AdminGeographyScreen,
   AdminUpdRoutingScreen, AdminDqaRulesScreen, AdminDdupScreen,
   AdminSecurityRolesScreen, AdminAuditScreen,
   AdminGeoUnitDetailScreen, AdminUpdRoutingRuleEditScreen,
   AdminUserDetailScreen, AdminDdupPairDetailScreen,
   AdminChoiceListOptionEditScreen,
   AdminApprovalsScreen,
   ChatbotAssistantScreen,
   ConsentPurposesScreen, ConsentStatementsScreen,
   ConsentCoverageScreen, DpoWithdrawalQueueScreen,
   ErrorBoundary, Icon */
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
    label: "Queue",
    items: [
      { id: "admin-approvals", label: "Approvals", icon: "checkCircle" },
    ],
  },
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
      { id: "admin-refdata-choicelists", label: "Choice lists", icon: "database" },
      { id: "admin-refdata-geo",         label: "Geography",    icon: "globe" },
    ],
  },
  {
    label: "Workflow",
    items: [
      { id: "admin-workflow-routing", label: "UPD routing",   icon: "filter" },
      { id: "admin-workflow-dqa",     label: "DQA rules",     icon: "shield" },
      { id: "admin-workflow-ddup",    label: "DDUP model",    icon: "users" },
    ],
  },
  {
    label: "Security",
    items: [
      { id: "admin-security-roles", label: "Roles & scopes", icon: "lock" },
      { id: "admin-security-audit", label: "Audit chain",    icon: "file" },
    ],
  },
  {
    // US-CONSENT — Consent Management (SEC). Withdrawal queue is the built
    // Screen 4; Purposes / Statement versions / Coverage are S27 stubs.
    label: "Consent (SEC)",
    items: [
      { id: "consent-purposes",         label: "Purposes",           icon: "shield" },
      { id: "consent-statements",       label: "Statement versions", icon: "file" },
      { id: "consent-withdrawal-queue", label: "Withdrawal queue",   icon: "inbox" },
      { id: "consent-coverage",         label: "Coverage dashboard", icon: "eligibility" },
    ],
  },
  {
    label: "Assistant",
    items: [
      { id: "chatbot-assistant", label: "Chatbot", icon: "message" },
    ],
  },
  {
    label: "Examples (record views)",
    items: [
      { id: "admin-detail-geo-unit",      label: "Geographic unit",   icon: "globe" },
      { id: "admin-detail-routing-edit",  label: "UPD routing · edit", icon: "edit" },
      { id: "admin-detail-user",          label: "User",              icon: "user" },
      { id: "admin-detail-ddup-pair",     label: "DDUP match pair",   icon: "users" },
      { id: "admin-detail-choice-option", label: "Choice option · edit", icon: "edit" },
    ],
  },
];

const AdminApp = () => {
  const [screen, setScreen] = useStateAdmin(initialFromHost);

  return (
    <div style={{
      minHeight: "100vh",
      background: "var(--neutral-50)",
      display: "flex",
      flexDirection: "column",
    }}>
      {/* National masthead — Uganda Coat of Arms on a white tile, navy
          bar with 3px gold rule, sticky over every admin route. Same
          chrome as the operator console so the two stay visually one
          state app. The sidebar below picks up its branding from the
          masthead; its header now just labels the console. */}
      <header className="topbar">
        <div className="topbar-brand">
          <span className="brand-mark">
            <img src="assets/Coat_of_arms_of_Uganda.png" alt="Coat of Arms of Uganda"/>
          </span>
          <div style={{display:'flex', flexDirection:'column', lineHeight:1.15}}>
            <span className="brand-wordmark">National Social Registry</span>
            <span className="brand-sub">Ministry of Gender, Labour and Social Development</span>
          </div>
        </div>
        <div className="topbar-spacer"/>
        <div className="topbar-actions">
          <span className="role-chip">
            <span>Admin Console</span>
          </span>
        </div>
      </header>

      <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
      {/* Sidebar. Uses the shared .sidenav / .nav-item classes so it
          inherits the light-rail palette + navy active accent the
          operator console adopted. Flex column so the nav scrolls
          internally while the footer keeps its own slot — earlier
          this screen used a position:absolute footer over a scrolling
          nav, and the footer rendered ON TOP of the last items
          (Chatbot, Examples) when the nav was taller than the
          viewport. */}
      <aside className="sidenav" style={{
        width: 248, flex: "0 0 248px",
        position: "sticky", top: 84, height: "calc(100vh - 84px)",
        display: "flex", flexDirection: "column",
        padding: 0,                                            /* override .sidenav default; group header has its own pad */
      }}>
        <div style={{
          padding: "16px 20px",
          borderBottom: "1px solid var(--neutral-200)",
        }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: "var(--neutral-900)" }}>Admin Console</div>
            <div style={{ fontSize: 11, color: "var(--neutral-500)" }}>Uganda NSR MIS</div>
          </div>
        </div>

        <nav style={{ flex: 1, overflow: "auto", padding: "10px 8px" }}>
          {NAV_GROUPS.map(group => (
            <div key={group.label} style={{ marginBottom: 8 }}>
              <div className="nav-section-label">{group.label}</div>
              {group.items.map(it => {
                const active = it.id === screen;
                const cls = `nav-item${active ? " active" : ""}`;
                return (
                  <button key={it.id}
                    className={cls}
                    disabled={it.disabled}
                    onClick={() => !it.disabled && setScreen(it.id)}
                    style={it.disabled ? {
                      color: "var(--neutral-400)",
                      cursor: "not-allowed",
                    } : undefined}>
                    <Icon name={it.icon} size={14}/>
                    <span style={{ flex: 1 }}>{it.label}</span>
                    {it.disabled && (
                      <span style={{
                        fontSize: 9, fontWeight: 600,
                        textTransform: "uppercase", letterSpacing: "0.06em",
                        color: "var(--neutral-500)",
                        background: "var(--neutral-100)",
                        padding: "1px 6px", borderRadius: 8,
                      }}>soon</span>
                    )}
                  </button>
                );
              })}
            </div>
          ))}
        </nav>

        <div style={{
          flex: "0 0 auto",
          padding: "12px 20px",
          borderTop: "1px solid var(--neutral-200)",
          fontSize: 11, color: "var(--neutral-500)",
        }}>
          Akello P. · NSR Coordinator
        </div>
      </aside>

      {/* Main content */}
      <main style={{ flex: 1, minWidth: 0, overflow: "auto" }}>
        <div style={{ maxWidth: 1440, margin: "0 auto", padding: "24px 24px 64px" }}>
          <ErrorBoundary>
          {screen === "admin-pmt-dashboard" && (
            <PmtDashboardScreen onOpenConfig={() => setScreen("admin-pmt-configuration")}/>
          )}
          {screen === "admin-pmt-configuration" && (
            <PmtConfigurationScreen onBack={() => setScreen("admin-pmt-dashboard")}/>
          )}
          {screen === "admin-approvals"            && <AdminApprovalsScreen onNavigate={setScreen}/>}
          {screen === "admin-refdata-choicelists"  && <AdminChoiceListsScreen/>}
          {screen === "admin-refdata-geo"          && <AdminGeographyScreen/>}
          {screen === "admin-workflow-routing"     && <AdminUpdRoutingScreen/>}
          {screen === "admin-workflow-dqa"         && <AdminDqaRulesScreen/>}
          {screen === "admin-workflow-ddup"        && <AdminDdupScreen/>}
          {screen === "admin-security-roles"       && <AdminSecurityRolesScreen/>}
          {screen === "admin-security-audit"       && <AdminAuditScreen/>}
          {screen === "consent-purposes"           && <ConsentPurposesScreen/>}
          {screen === "consent-statements"         && <ConsentStatementsScreen/>}
          {screen === "consent-withdrawal-queue"   && <DpoWithdrawalQueueScreen/>}
          {screen === "consent-coverage"           && <ConsentCoverageScreen/>}
          {screen === "chatbot-assistant"          && <ChatbotAssistantScreen/>}

          {/* Record detail / edit screens — opened from list rows */}
          {screen === "admin-detail-geo-unit"      && <AdminGeoUnitDetailScreen onBack={() => setScreen("admin-refdata-geo")}/>}
          {screen === "admin-detail-routing-edit"  && <AdminUpdRoutingRuleEditScreen onBack={() => setScreen("admin-workflow-routing")}/>}
          {screen === "admin-detail-user"          && <AdminUserDetailScreen onBack={() => setScreen("admin-security-roles")}/>}
          {screen === "admin-detail-ddup-pair"     && <AdminDdupPairDetailScreen onBack={() => setScreen("admin-workflow-ddup")}/>}
          {screen === "admin-detail-choice-option" && <AdminChoiceListOptionEditScreen onBack={() => setScreen("admin-refdata-choicelists")}/>}
          </ErrorBoundary>
        </div>
      </main>
      </div>
    </div>
  );
};

ReactDOM.createRoot(document.getElementById("app")).render(<AdminApp/>);
