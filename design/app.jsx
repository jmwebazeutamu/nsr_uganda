/* global React, ReactDOM, Icon, Chip, HomeScreen, KitScreen, CaptureScreen, ReceiptScreen, DIHScreen, DedupScreen, UPDScreen, DRSScreen, GRMScreen, PartnerDRSScreen, PartnersScreen, PartnerRegistrationScreen, PartnerDetailScreen, ProgrammeRegistrationScreen, ProgrammesScreen, ProgrammeDetailScreen, BeneficiariesScreen, ReportsScreen, AdminScreen, RegistryScreen, HouseholdScreen, MemberDetailScreen, DsasScreen, DsaDetailScreen, DsaCreateWizard, DsaQuickFind, MyDsaScreen, MyProgrammesScreen, ROLE_CONTENT, TweaksPanel, useTweaks, TweakSection, TweakSelect, TweakToggle, TweakRadio, useNavCounts, ErrorBoundary */
// NSR MIS — App shell + router

const { useState: useStateApp, useEffect: useEffectApp } = React;

// CSRF helper for the impersonation Stop button (US-S11-042). Same
// pattern as _getCsrfToken in screens-dih / _adminCsrfToken in
// screens-admin — read Django's csrftoken cookie, fall back to "".
const _appCsrfToken = () => {
  if (typeof document === "undefined") return "";
  const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return m ? m[1] : "";
};

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
  { id: "dih",     label: "DIH review",    icon: "inbox",     count: 342 },
  { id: "upd",     label: "Updates",       icon: "edit",      count: 23 },
  { id: "dedup",   label: "Duplicates",    icon: "duplicate", count: 47 },
  { id: "grm",     label: "Grievances",    icon: "message",   count: 7 },
  { section: "DATA" },
  { id: "registry",         label: "Social Registry", icon: "users", screen: true },
  { id: "registry-members", label: "Members",         icon: "user",  screen: true, indent: 1 },
  { id: "programmes",       label: "Programmes",      icon: "book",  screen: true },
  { id: "beneficiaries",    label: "Beneficiaries",   icon: "book",  screen: true },
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
  // Data Sharing Agreements lives under Admin → Partners & DSAs.
  // Removed from the sidebar so the workspace is discoverable from
  // the admin index rather than competing as a top-level entry.
];

function App() {
  const [tweaks, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const [screen, setScreen] = useStateApp("home");
  const [device, setDevice] = useStateApp("desktop");
  // Live nav counters keyed by nav id. Falls back to NAV.count when
  // the API is unreachable so the design preview still renders.
  const [navCounts] = useNavCounts();
  // Identity of the actually-authenticated session user. The
  // Tweaks "Role" dropdown is a rendering override; this is the
  // ground truth from /api/v1/security/users/me/. Used to:
  //  - show real username + partner in the topbar
  //  - auto-pick a sensible Tweaks role when first mounting (so
  //    opm-analyst doesn't land on an NSR-Unit-themed home).
  const [me, setMe] = useStateApp(null);
  useEffectApp(() => {
    let cancelled = false;
    fetch("/api/v1/security/users/me/", {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(d => { if (!cancelled) setMe(d); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);
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

  // When /me/ resolves and the Tweaks role still matches the
  // TWEAK_DEFAULTS seed (i.e. the user hasn't manually overridden
  // it yet), align the rendering role to the actual session. This
  // is what makes "log in as opm-analyst" produce a partner-analyst
  // sidebar without a second click in Tweaks.
  useEffectApp(() => {
    if (!me || !me.role) return;
    if (tweaks.role === TWEAK_DEFAULTS.role && me.role !== tweaks.role) {
      setTweak("role", me.role);
    }
  }, [me]);

  // Role label gates which Home variant + person we show. The Tweaks
  // dropdown is a rendering override; it does NOT change auth.
  const role = tweaks.role;
  const roleData = ROLE_CONTENT[role] || ROLE_CONTENT["nsr-unit"];
  // Topbar identity — prefer the live /me/ payload; fall back to the
  // hardcoded persona only when the endpoint hasn't responded yet.
  const identityName = me?.display_name || me?.username || roleData.person;
  const identityOrg  = me?.partner?.name || roleData.org;
  const identityRoleLabel = me?.partner
    ? `${roleData.name} · ${me.partner.code}`
    : roleData.name;
  const identityInitials = identityName
    .split(/\s+/).filter(Boolean).map(p => p[0]).slice(0, 2).join("").toUpperCase()
    || "?";

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
    if (role === "parish" && ["dih","drs","dedup","partners","beneficiaries"].includes(n.id)) return false;
    if (role === "dpo"    && ["capture","upd","dedup","grm","receipt"].includes(n.id)) return false;
    if (role === "cdo"    && ["dih","drs","partners"].includes(n.id)) return false;
    if (role === "partner-analyst" && !["home","partner-drs","my-dsa","my-programmes","kit"].includes(n.id)) return false;
    // Registry + Beneficiaries are operator-only — partners use the
    // DRS portal to request data, not browse the registry directly.
    if (["registry","registry-members","programmes","beneficiaries"].includes(n.id) && role === "partner-analyst") return false;
    return true;
  });

  // US-S11-042 — when /me/ returns an impersonator block we're acting
  // as another user. The banner across the top makes that visible on
  // every page so the admin can't forget; the read-only-writes
  // middleware also enforces the safety net server-side.
  const impersonator = me?.impersonator || null;
  const stopImpersonating = () => {
    fetch("/api/v1/security/impersonate/stop/", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "X-CSRFToken": _appCsrfToken(),
      },
    })
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(() => { window.location.reload(); })
      .catch(() => alert("Stop impersonating failed — try logging out + back in."));
  };

  return (
    <div className="app-shell">
      {impersonator && (
        <div
          role="alert"
          style={{
            background: "var(--accent-quality)",
            color: "white", padding: "8px 16px",
            display: "flex", alignItems: "center", gap: 12,
            fontSize: 13, fontWeight: 500,
          }}
        >
          <Icon name="shield" size={16}/>
          <span>
            Impersonating <strong>{me.username}</strong> ({identityRoleLabel}) as{" "}
            <strong>{impersonator.username}</strong>.{" "}
            <span style={{opacity:0.85}}>Writes are disabled in this session.</span>
          </span>
          <span className="t-cap" style={{opacity:0.85}} title={impersonator.reason}>
            reason: {impersonator.reason || "(none)"}
          </span>
          <div style={{flex:1}}/>
          <button
            type="button"
            onClick={stopImpersonating}
            style={{
              background:"white", color:"var(--accent-quality)",
              border:"none", padding:"4px 12px", borderRadius:4,
              fontSize:12, fontWeight:600, cursor:"pointer",
            }}
          >
            Stop impersonating
          </button>
        </div>
      )}
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
          <span className="role-chip" title={me ? `Authenticated as ${me.username}` : "Loading session…"}>
            <span className="muted">Role</span> <strong>{identityRoleLabel}</strong>
          </span>
          {role !== "partner-analyst" && (
            <button className="icon-btn" title="Find a DSA"
                    onClick={() => setDsaFindOpen(true)}>
              <Icon name="file" size={18}/>
            </button>
          )}
          <button className="icon-btn" title="Notifications"><Icon name="bell" size={18}/><span className="dot"/></button>
          <button className="icon-btn" title="Settings"><Icon name="settings" size={18}/></button>
          <button className="avatar" title={`${identityName}${identityOrg ? " · " + identityOrg : ""}${me?.username ? " (" + me.username + ")" : ""}`}>{identityInitials}</button>
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
            <button key={n.id}
                    className={`nav-item ${active ? 'active' : ''}`}
                    style={n.indent ? { paddingLeft: 32 } : undefined}
                    onClick={() => navigate(n.id)}>
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
        <ErrorBoundary>
        {screen === "home"    && <HomeScreen role={role} onNavigate={navigate}/>}
        {screen === "kit"     && <KitScreen/>}
        {screen === "capture" && <CaptureScreen
          device={device} onChangeDevice={setDevice}
          onPromoted={() => setScreen("dih")}/>}
        {screen === "receipt" && <ReceiptScreen/>}
        {screen === "dih"     && <DIHScreen/>}
        {screen === "dedup"   && <DedupScreen/>}
        {screen === "upd"     && <UPDScreen changeRequestId={screenPayload?.changeRequestId} onNavigate={navigate}/>}
        {screen === "drs"     && <DRSScreen onNavigate={navigate}/>}
        {screen === "grm"     && <GRMScreen onNavigate={navigate}/>}
        {screen === "partner-drs" && <PartnerDRSScreen/>}
        {screen === "my-dsa" && <MyDsaScreen/>}
        {screen === "my-programmes" && <MyProgrammesScreen/>}
        {screen === "reports" && <ReportsScreen role={role}/>}
        {screen === "admin"   && <AdminScreen onNavigate={navigate}/>}
        {(screen === "registry" || screen === "registry-members") && <RegistryScreen
            initialView={screen === "registry-members" ? "members" : (screenPayload?.initialView)}
            onOpen={(rid) => navigate("household", { householdId: rid })}
            onOpenMember={(mid) => navigate("registry-member-detail", { memberId: mid })}
            onNavigate={navigate}/>}
        {screen === "household" && <HouseholdScreen householdId={screenPayload?.householdId} onNavigate={navigate}/>}
        {screen === "registry-member-detail" && <MemberDetailScreen
            memberId={screenPayload?.memberId}
            onBack={() => navigate("registry", { initialView: "members" })}
            onOpenHousehold={(rid) => navigate("household", { householdId: rid })}/>}
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
        {screen === "programmes" && <ProgrammesScreen
            onOpen={(programmeId) => navigate("programme-detail", { programmeId })}
            onRegister={() => navigate("programme-new")}/>}
        {screen === "programme-detail" && <ProgrammeDetailScreen
            programmeId={screenPayload?.programmeId}
            onBack={() => navigate("programmes")}
            onOpenPartner={(partnerId) => navigate("partner-detail", { partnerId })}
            onOpenHousehold={(rid) => navigate("household", { householdId: rid })}/>}
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
        </ErrorBoundary>
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
        {/* Authenticated identity — surfaces the gap that previously
            confused users: the dropdown below is a RENDER override
            only; the real session is whoever is logged in via /admin/. */}
        <TweakSection label="Authenticated as">
          <div style={{
            padding: "8px 10px", border: "1px solid var(--neutral-200)",
            borderRadius: 6, background: "var(--neutral-50)",
            fontSize: 13, lineHeight: 1.4,
          }}>
            {me ? (
              <>
                <div><strong className="t-mono">{me.username}</strong>{me.is_superuser ? " · superuser" : ""}</div>
                <div className="t-cap" style={{color: "var(--neutral-700)", marginTop: 2}}>
                  Role from session: <strong>{me.role}</strong>
                  {me.partner && <> · partner <strong className="t-mono">{me.partner.code}</strong> ({me.partner.name})</>}
                </div>
              </>
            ) : (
              <span className="t-cap muted">Not signed in · log in at <span className="t-mono">/admin/</span></span>
            )}
          </div>
        </TweakSection>

        <TweakSection label="Render as (preview only)">
          <TweakSelect label="Role" value={tweaks.role} onChange={(v) => setTweak('role', v)}
            options={[
              { value: "nsr-unit",        label: "NSR Unit Coordinator" },
              { value: "sr-manager",      label: "Social Registry Manager" },
              { value: "parish",          label: "Parish Chief" },
              { value: "cdo",             label: "Community Development Officer" },
              { value: "dpo",             label: "Data Protection Officer" },
              { value: "partner-analyst", label: "Partner Analyst" + (me?.partner ? ` · ${me.partner.code}` : "") },
            ]}/>
          <div className="t-cap" style={{color: "var(--neutral-600)", marginTop: 6, lineHeight: 1.4}}>
            Switches the rendering only — sidebar items, home dashboard
            persona, queue projections. The authenticated session above
            is what the server enforces.
          </div>
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
