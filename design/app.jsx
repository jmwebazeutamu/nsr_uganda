/* global React, ReactDOM, Icon, Chip, HomeScreen, KitScreen, CaptureScreen, ReceiptScreen, DIHScreen, DedupScreen, UPDScreen, DRSScreen, GRMScreen, PartnerDRSScreen, PartnersScreen, PartnerRegistrationScreen, PartnerDetailScreen, ProgrammeRegistrationScreen, BeneficiariesScreen, ReportsScreen, AdminScreen, RegistryScreen, HouseholdScreen, ROLE_CONTENT, TweaksPanel, useTweaks, TweakSection, TweakSelect, TweakToggle, TweakRadio */
// NSR MIS — App shell + router

const { useState: useStateApp, useEffect: useEffectApp } = React;

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "density": "comfortable",
  "role": "nsr-unit",
  "stretchStrings": false
}/*EDITMODE-END*/;

const NAV = [
  { id: "home",    label: "Home",          icon: "home" },
  { id: "kit",     label: "Design system", icon: "sliders" },
  { section: "WORKFLOWS" },
  { id: "capture", label: "Captures",      icon: "users",     count: 14, screen: true },
  { id: "dih",     label: "DIH review",    icon: "inbox",     count: 342 },
  { id: "upd",     label: "Updates",       icon: "edit",      count: 23 },
  { id: "dedup",   label: "Duplicates",    icon: "duplicate", count: 47 },
  { id: "grm",     label: "Grievances",    icon: "message",   count: 7 },
  { section: "DATA" },
  { id: "registry", label: "Registry",     icon: "users",     screen: true },
  { id: "drs",     label: "Data Requests", icon: "download",  count: 9 },
  { id: "partner-drs", label: "My requests", icon: "download", count: 5 },
  { id: "receipt", label: "Receipt slip",  icon: "print" },
  { section: "PARTNERS" },
  { id: "partners", label: "Partners",     icon: "users",     screen: true },
];

function App() {
  const [tweaks, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const [screen, setScreen] = useStateApp("home");
  const [device, setDevice] = useStateApp("desktop");
  // Cross-screen handoff payload — set by `navigate(screen, payload)`,
  // consumed by the destination screen on mount, cleared when the
  // user navigates away. Lets GRM → UPD pass a changeRequestId
  // without inventing a real URL router for the mockup harness.
  const [screenPayload, setScreenPayload] = useStateApp(null);

  const navigate = (nextScreen, payload = null) => {
    setScreen(nextScreen);
    setScreenPayload(payload);
  };

  // sync tweaks → DOM attrs
  useEffectApp(() => {
    document.documentElement.setAttribute('data-density', tweaks.density);
    document.documentElement.setAttribute('data-stretch', tweaks.stretchStrings ? '1' : '0');
  }, [tweaks.density, tweaks.stretchStrings]);

  // Role label gates which Home variant + person we show
  const role = tweaks.role;
  const roleData = ROLE_CONTENT[role] || ROLE_CONTENT["nsr-unit"];

  // Role-aware nav: hide things outside role scope.
  // Partner roles see ONLY their portal — they have no business in
  // the operator-side workflows.
  const visibleNav = NAV.filter(n => {
    if (n.section) {
      if (role === "partner-analyst" && n.section === "WORKFLOWS") return false;
      if (role === "partner-analyst" && n.section === "PARTNERS") return false;
      return true;
    }
    if (role === "parish" && ["dih","drs","dedup","partner-drs","partners"].includes(n.id)) return false;
    if (role === "dpo"    && ["capture","upd","dedup","grm","receipt","partner-drs"].includes(n.id)) return false;
    if (role === "cdo"    && ["dih","drs","partner-drs","partners"].includes(n.id)) return false;
    if (role === "nsr-unit" && n.id === "partner-drs") return false;
    if (role === "partner-analyst" && !["home","partner-drs","kit"].includes(n.id)) return false;
    // Registry is operator-only — partners use the DRS portal to
    // request data, not browse the registry directly.
    if (n.id === "registry" && role === "partner-analyst") return false;
    return true;
  });

  return (
    <div className="app-shell">
      {/* Topbar */}
      <header className="topbar">
        <div className="topbar-brand">
          <div className="brand-mark">NSR</div>
          <div style={{display:'flex', flexDirection:'column', lineHeight:1.15}}>
            <span style={{fontSize:13.5, fontWeight:700, color:'var(--primary-900)'}}>National Social Registry</span>
            <span className="t-cap">MGLSD · Republic of Uganda</span>
          </div>
        </div>

        <div className="search">
          <Icon name="search" size={16} color="var(--neutral-500)"/>
          <input placeholder="Search households, members, Registry IDs, NIN…"/>
          <kbd>⌘K</kbd>
        </div>

        <div className="topbar-spacer"/>

        <div className="topbar-actions">
          <span className="role-chip"><span className="muted">Role</span> <strong>{roleData.name}</strong></span>
          <button className="icon-btn" title="Notifications"><Icon name="bell" size={18}/><span className="dot"/></button>
          <button className="icon-btn" title="Settings"><Icon name="settings" size={18}/></button>
          <button className="avatar" title={roleData.person}>{roleData.person.split(' ').map(p => p[0]).slice(0,2).join('')}</button>
        </div>
      </header>

      {/* Side nav */}
      <nav className="sidenav">
        {visibleNav.map((n, i) => {
          if (n.section) {
            return <div key={i} className="nav-section-label">{n.section}</div>;
          }
          const active = n.id === screen;
          return (
            <button key={n.id} className={`nav-item ${active ? 'active' : ''}`} onClick={() => navigate(n.id)}>
              <Icon name={n.icon} size={18}/>
              <span className="nav-label">{n.label}</span>
              {n.count !== undefined && <span className="nav-count">{n.count}</span>}
            </button>
          );
        })}

        {/* Sub-nav under capture for receipt etc */}
        <div className="nav-section-label">SYSTEM</div>
        <button className={`nav-item ${screen === "reports" ? "active" : ""}`}
                onClick={() => navigate("reports")}>
          <Icon name="barchart" size={18}/>
          <span className="nav-label">Reports</span>
        </button>
        {role !== "partner-analyst" && (
          <button className={`nav-item ${screen === "admin" ? "active" : ""}`}
                  onClick={() => navigate("admin")}>
            <Icon name="shield" size={18}/>
            <span className="nav-label">Admin</span>
          </button>
        )}
      </nav>

      {/* Main */}
      <main className="main">
        {screen === "home"    && <HomeScreen role={role} onNavigate={navigate}/>}
        {screen === "kit"     && <KitScreen/>}
        {screen === "capture" && <CaptureScreen device={device} onChangeDevice={setDevice}/>}
        {screen === "receipt" && <ReceiptScreen/>}
        {screen === "dih"     && <DIHScreen/>}
        {screen === "dedup"   && <DedupScreen/>}
        {screen === "upd"     && <UPDScreen changeRequestId={screenPayload?.changeRequestId}/>}
        {screen === "drs"     && <DRSScreen/>}
        {screen === "grm"     && <GRMScreen onNavigate={navigate}/>}
        {screen === "partner-drs" && <PartnerDRSScreen/>}
        {screen === "reports" && <ReportsScreen role={role}/>}
        {screen === "admin"   && <AdminScreen/>}
        {screen === "registry" && <RegistryScreen onNavigate={navigate}/>}
        {screen === "household" && <HouseholdScreen householdId={screenPayload?.householdId} onNavigate={navigate}/>}
        {screen === "partners" && <PartnersScreen
            onRegister={() => navigate("partner-new")}
            onOpen={(partnerId) => navigate("partner-detail", { partnerId })}
            onNavigate={navigate}/>}
        {screen === "partner-new" && <PartnerRegistrationScreen
            onBack={() => navigate("partners")}
            onCreated={() => navigate("partners")}/>}
        {screen === "partner-detail" && <PartnerDetailScreen
            partnerId={screenPayload?.partnerId}
            onBack={() => navigate("partners")}
            onRegisterProgramme={() => navigate("programme-new")}/>}
        {screen === "programme-new" && <ProgrammeRegistrationScreen
            onBack={() => navigate("partners")}/>}
        {screen === "beneficiaries" && <BeneficiariesScreen
            onOpenHousehold={(rid) => navigate("household", { householdId: rid })}
            onNewProgramme={() => navigate("programme-new")}/>}
      </main>

      {/* Tweaks */}
      <TweaksPanel title="Tweaks">
        <TweakSection label="Operator role">
          <TweakSelect label="Role" value={tweaks.role} onChange={(v) => setTweak('role', v)}
            options={[
              { value: "nsr-unit",        label: "NSR Unit Coordinator" },
              { value: "parish",          label: "Parish Chief" },
              { value: "cdo",             label: "Community Development Officer" },
              { value: "dpo",             label: "Data Protection Officer" },
              { value: "partner-analyst", label: "Partner Analyst (PDM/NUSAF/WFP)" },
            ]}/>
        </TweakSection>

        <TweakSection label="Table density">
          <TweakRadio label="Rows" value={tweaks.density} onChange={(v) => setTweak('density', v)}
            options={[
              { value: "comfortable", label: "Comfort" },
              { value: "compact",     label: "Compact" },
            ]}/>
        </TweakSection>

        <TweakSection label="Bilingual stress test">
          <TweakToggle label="Stretch strings 130%" value={tweaks.stretchStrings} onChange={(v) => setTweak('stretchStrings', v)}/>
        </TweakSection>
      </TweaksPanel>
    </div>
  );
}

const root = ReactDOM.createRoot(document.getElementById('app'));
root.render(<App/>);
