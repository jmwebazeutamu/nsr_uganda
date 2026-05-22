/* global React, ReactDOM, Icon, Chip, HomeScreen, KitScreen, CaptureScreen, ReceiptScreen, DIHScreen, DedupScreen, UPDScreen, DRSScreen, GRMScreen, PartnerDRSScreen, PartnersScreen, PartnerRegistrationScreen, PartnerDetailScreen, ProgrammeRegistrationScreen, BeneficiariesScreen, ReportsScreen, AdminScreen, RegistryScreen, HouseholdScreen, DsasScreen, DsaDetailScreen, DsaCreateWizard, DsaQuickFind, MyDsaScreen, MyProgrammesScreen, ROLE_CONTENT, TweaksPanel, useTweaks, TweakSection, TweakSelect, TweakToggle, TweakRadio, useNavCounts */
// NSR MIS — App shell + router

const { useState: useStateApp, useEffect: useEffectApp } = React;

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "density": "comfortable",
  "role": "nsr-unit",
  "stretchStrings": false
}/*EDITMODE-END*/;

// `count` here is just the fallback shown when the live counter hook
// (useNavCounts → /api/v1/...) hasn't responded or the endpoint isn't
// reachable. Live values replace these at render time. `capture` has
// no API yet so it stays on the fallback until the intake endpoint
// lands.
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
  { id: "registry",      label: "Social Registry", icon: "users", screen: true },
  { id: "beneficiaries", label: "Beneficiaries",   icon: "book",  screen: true },
  { id: "drs",     label: "Data Requests", icon: "download",  count: 9 },
  { id: "partner-drs", label: "My requests", icon: "download", count: 5 },
  // Partner self-service surfaces — visible only when role is
  // partner-analyst (see role-filter below). Read-only views of the
  // partner's own DSA + programmes register.
  { id: "my-dsa",        label: "My DSA",        icon: "file" },
  { id: "my-programmes", label: "My programmes", icon: "book" },
  { id: "receipt", label: "Receipt slip",  icon: "print" },
  { section: "PARTNERS" },
  { id: "partners", label: "Partners",     icon: "users",     screen: true },
  { id: "dsas",     label: "Data Sharing Agreements", icon: "file", screen: true },
];

function App() {
  const [tweaks, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const [screen, setScreen] = useStateApp("home");
  const [device, setDevice] = useStateApp("desktop");
  // Live nav counters keyed by nav id. Falls back to NAV.count when
  // the API is unreachable so the design preview still renders.
  const [navCounts] = useNavCounts();
  // Cross-screen handoff payload — set by `navigate(screen, payload)`,
  // consumed by the destination screen on mount, cleared when the
  // user navigates away. Lets GRM → UPD pass a changeRequestId
  // without inventing a real URL router for the mockup harness.
  const [screenPayload, setScreenPayload] = useStateApp(null);
  // Console quick-find overlay — global affordance to jump to a DSA
  // from anywhere in the app. ⌘/Ctrl-K opens it; clicking a result
  // navigates to the DSA detail screen.
  const [dsaFindOpen, setDsaFindOpen] = useStateApp(false);

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
    // The partner self-service tiles only make sense for the
    // partner-analyst role — operator-side roles never use them.
    const PARTNER_ONLY = new Set(["partner-drs", "my-dsa", "my-programmes"]);
    if (role !== "partner-analyst" && PARTNER_ONLY.has(n.id)) return false;
    if (role === "parish" && ["dih","drs","dedup","partners","beneficiaries","dsas"].includes(n.id)) return false;
    if (role === "dpo"    && ["capture","upd","dedup","grm","receipt"].includes(n.id)) return false;
    if (role === "cdo"    && ["dih","drs","partners","dsas"].includes(n.id)) return false;
    if (role === "partner-analyst" && !["home","partner-drs","my-dsa","my-programmes","kit"].includes(n.id)) return false;
    // Registry + Beneficiaries are operator-only — partners use the
    // DRS portal to request data, not browse the registry directly.
    if (["registry","beneficiaries"].includes(n.id) && role === "partner-analyst") return false;
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
          {role !== "partner-analyst" && (
            <button className="icon-btn" title="Find a DSA"
                    onClick={() => setDsaFindOpen(true)}>
              <Icon name="file" size={18}/>
            </button>
          )}
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
          // Live counter takes priority over the hardcoded fallback.
          // We only render the badge if the original NAV entry had one
          // (i.e. it's a workflow link, not a plain navigation link).
          const liveCount = navCounts ? navCounts[n.id] : undefined;
          const displayCount = liveCount !== undefined ? liveCount : n.count;
          return (
            <button key={n.id} className={`nav-item ${active ? 'active' : ''}`} onClick={() => navigate(n.id)}>
              <Icon name={n.icon} size={18}/>
              <span className="nav-label">{n.label}</span>
              {n.count !== undefined && <span className="nav-count">{displayCount}</span>}
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
        {screen === "drs"     && <DRSScreen onNavigate={navigate}/>}
        {screen === "grm"     && <GRMScreen onNavigate={navigate}/>}
        {screen === "partner-drs" && <PartnerDRSScreen/>}
        {screen === "my-dsa" && <MyDsaScreen/>}
        {screen === "my-programmes" && <MyProgrammesScreen/>}
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
            onRegisterProgramme={() => navigate("programme-new")}
            onNavigate={navigate}/>}
        {screen === "programme-new" && <ProgrammeRegistrationScreen
            onBack={() => navigate("partners")}/>}
        {screen === "beneficiaries" && <BeneficiariesScreen
            onOpenHousehold={(rid) => navigate("household", { householdId: rid })}
            onNewProgramme={() => navigate("programme-new")}/>}
        {screen === "dsas" && <DsasScreen
            onOpen={(dsaId) => navigate("dsa-detail", { dsaId })}
            onNew={() => navigate("dsa-new")}
            onNavigate={navigate}/>}
        {screen === "dsa-detail" && <DsaDetailScreen
            dsaId={screenPayload?.dsaId}
            onBack={() => navigate("dsas")}
            onNavigate={navigate}/>}
        {screen === "dsa-new" && <DsaCreateWizard
            prefillPartnerId={screenPayload?.partnerId}
            onBack={() => navigate("dsas")}
            onCreated={(dsa) => navigate("dsa-detail", { dsaId: dsa.id })}/>}
      </main>

      {/* Global DSA quick-find overlay — wired from the topbar icon
          and (later) ⌘K. Same surface from every screen. */}
      <DsaQuickFind
        open={dsaFindOpen}
        onClose={() => setDsaFindOpen(false)}
        onPick={(dsa) => {
          setDsaFindOpen(false);
          navigate("dsa-detail", { dsaId: dsa.id });
        }}
      />

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
