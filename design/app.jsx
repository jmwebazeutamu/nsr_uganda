/* global React, ReactDOM, Icon, Chip, HomeScreen, KitScreen, CaptureScreen, ReceiptScreen, DIHScreen, DedupScreen, UPDScreen, DRSScreen, GRMScreen, ROLE_CONTENT, TweaksPanel, useTweaks, TweakSection, TweakSelect, TweakToggle, TweakRadio */
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
  { id: "drs",     label: "Data Requests", icon: "download",  count: 9 },
  { id: "receipt", label: "Receipt slip",  icon: "print" },
];

function App() {
  const [tweaks, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const [screen, setScreen] = useStateApp("home");
  const [device, setDevice] = useStateApp("desktop");

  // sync tweaks → DOM attrs
  useEffectApp(() => {
    document.documentElement.setAttribute('data-density', tweaks.density);
    document.documentElement.setAttribute('data-stretch', tweaks.stretchStrings ? '1' : '0');
  }, [tweaks.density, tweaks.stretchStrings]);

  // Role label gates which Home variant + person we show
  const role = tweaks.role;
  const roleData = ROLE_CONTENT[role] || ROLE_CONTENT["nsr-unit"];

  // Role-aware nav: hide things outside role scope
  const visibleNav = NAV.filter(n => {
    if (n.section) return true;
    if (role === "parish" && ["dih","drs","dedup"].includes(n.id)) return false;
    if (role === "dpo"    && ["capture","upd","dedup","grm","receipt"].includes(n.id)) return false;
    if (role === "cdo"    && ["dih","drs"].includes(n.id)) return false;
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
            <button key={n.id} className={`nav-item ${active ? 'active' : ''}`} onClick={() => setScreen(n.id)}>
              <Icon name={n.icon} size={18}/>
              <span className="nav-label">{n.label}</span>
              {n.count !== undefined && <span className="nav-count">{n.count}</span>}
            </button>
          );
        })}

        {/* Sub-nav under capture for receipt etc */}
        <div className="nav-section-label">SYSTEM</div>
        <button className="nav-item" onClick={() => alert('Reports — out of scope for this design pass')}>
          <Icon name="barchart" size={18}/>
          <span className="nav-label">Reports</span>
        </button>
        <button className="nav-item" onClick={() => alert('Admin — out of scope for this design pass')}>
          <Icon name="shield" size={18}/>
          <span className="nav-label">Admin</span>
        </button>
      </nav>

      {/* Main */}
      <main className="main">
        {screen === "home"    && <HomeScreen role={role} onNavigate={setScreen}/>}
        {screen === "kit"     && <KitScreen/>}
        {screen === "capture" && <CaptureScreen device={device} onChangeDevice={setDevice}/>}
        {screen === "receipt" && <ReceiptScreen/>}
        {screen === "dih"     && <DIHScreen/>}
        {screen === "dedup"   && <DedupScreen/>}
        {screen === "upd"     && <UPDScreen/>}
        {screen === "drs"     && <DRSScreen/>}
        {screen === "grm"     && <GRMScreen/>}
      </main>

      {/* Tweaks */}
      <TweaksPanel title="Tweaks">
        <TweakSection label="Operator role">
          <TweakSelect label="Role" value={tweaks.role} onChange={(v) => setTweak('role', v)}
            options={[
              { value: "nsr-unit", label: "NSR Unit Coordinator" },
              { value: "parish",   label: "Parish Chief" },
              { value: "cdo",      label: "Community Development Officer" },
              { value: "dpo",      label: "Data Protection Officer" },
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
