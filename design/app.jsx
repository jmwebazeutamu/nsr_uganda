/* global React, ReactDOM, Icon, Chip, HomeScreen, KitScreen, CaptureScreen, ReceiptScreen, DIHScreen, DedupScreen, UPDScreen, DRSScreen, DataExplorerConsoleScreen, GRMScreen, PartnerDRSScreen, PartnersScreen, PartnerRegistrationScreen, PartnerDetailScreen, ProgrammeRegistrationScreen, ProgrammesScreen, ProgrammeDetailScreen, BeneficiariesScreen, ReportsScreen, AdminScreen, RegistryScreen, HouseholdScreen, MemberDetailScreen, DsasScreen, DsaDetailScreen, DsaCreateWizard, DsaQuickFind, MyDsaScreen, MyProgrammesScreen, CatalogueScreen, DatasetDetailScreen, VariableDetailScreen, AggregateBuilderScreen, HandoffConfirmScreen, ChangeRequestScreen, ROLE_CONTENT, TweaksPanel, useTweaks, TweakSection, TweakSelect, TweakToggle, TweakRadio, useNavCounts, ErrorBoundary, useWideView, _wideRequestedScreen, WideViewButtons */
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

// A wide window (ADR-0030) is this same application opened at
// `?wide=<screen>` — a real second window on the same session, not a
// copy of the table. It renders one screen with no sidebar and no
// masthead, because the point of it is vertical space.
//
// Screens opt in by handling `wide` themselves; anything not listed
// here says so rather than rendering a normal-width screen in a window
// the operator opened expressly to get a wider one.
const WIDE_SCREENS = {
  dih:      { label: "DIH review queue", render: () => <DIHScreen/> },
  registry: {
    label: "Social Registry",
    render: (nav) => <RegistryScreen
      initialView="households"
      onOpen={(rid) => nav("household", { householdId: rid })}
      onOpenMember={(mid) => nav("registry-member-detail", { memberId: mid })}
      onNavigate={nav}/>,
  },
  "registry-members": {
    label: "Members",
    render: (nav) => <RegistryScreen
      initialView="members"
      onOpen={(rid) => nav("household", { householdId: rid })}
      onOpenMember={(mid) => nav("registry-member-detail", { memberId: mid })}
      onNavigate={nav}/>,
  },
  dedup:    { label: "Duplicates",    render: () => <DedupScreen/> },
  grm:      { label: "Grievances",    render: (nav) => <GRMScreen onNavigate={nav}/> },
  drs:      { label: "Data Requests", render: (nav) => <DRSScreen onNavigate={nav}/> },
  beneficiaries: {
    label: "Beneficiaries",
    render: (nav) => <BeneficiariesScreen
      onOpenHousehold={(rid) => nav("household", { householdId: rid })}
      onNewProgramme={() => nav("programme-new")}/>,
  },
  partners: {
    label: "Partners",
    render: (nav) => <PartnersScreen
      onOpen={(partnerId) => nav("partner-detail", { partnerId })}
      onNavigate={nav}/>,
  },
};

// Records a wide list can open without leaving the window.
//
// A wide list is for triage, and triage means opening the thing you
// found. Without these, a row click in a popped-out window either did
// nothing or dropped the operator back to the main console — so the
// second monitor could show a list and not act on it.
//
// This is a short stack, not a router: the list is the root, a record
// opens over it, and Back returns. Anything not here says where to go
// rather than rendering a screen without the props it needs.
const WIDE_DETAILS = {
  household: {
    label: "Household",
    render: (nav, payload) => <HouseholdScreen
      householdId={payload?.householdId} onNavigate={nav}/>,
  },
  "registry-member-detail": {
    label: "Member",
    render: (nav, payload) => <MemberDetailScreen
      memberId={payload?.memberId}
      onBack={() => nav("registry-members")}
      onOpenHousehold={(rid) => nav("household", { householdId: rid })}
      onNavigate={nav}/>,
  },
  "partner-detail": {
    label: "Partner",
    render: (nav, payload) => <PartnerDetailScreen
      partnerId={payload?.partnerId}
      onBack={() => nav("partners")}
      onRegisterProgramme={() => nav("programme-new")}
      onNavigate={nav}/>,
  },
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
  // Data Explorer — discovery + aggregate surface (ADR-0023,
  // US-DATA-EXP-001). Embedded same-origin so the API client uses the
  // authenticated console session. Gated on the data_explorer.enabled
  // feature flag AND the user's EXPLORER realm role; hidden (not
  // greyed) when either fails, per design brief §6.
  { id: "data-explorer", label: "Data Explorer", icon: "database",
    featureFlag: "data_explorer_enabled", requireRole: "EXPLORER" },
  { section: "WORKFLOWS" },
  { id: "dih",     label: "DIH review",    icon: "inbox" },
  { id: "upd",     label: "Updates",       icon: "edit" },
  { id: "dedup",   label: "Duplicates",    icon: "duplicate" },
  { id: "grm",     label: "Grievances",    icon: "message" },
  { section: "DATA" },
  { id: "registry",         label: "Social Registry", icon: "users", screen: true },
  { id: "registry-members", label: "Members",         icon: "user",  screen: true, indent: 1 },
  { id: "programmes",       label: "Programmes",      icon: "book",  screen: true },
  { id: "beneficiaries",    label: "Beneficiaries",   icon: "book",  screen: true },
  { id: "drs",     label: "Data Requests", icon: "download" },
  { id: "partner-drs", label: "My requests", icon: "download" },
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
    // Feature-flag gating — for nav entries that declare a flag,
    // the entry only renders if me.feature_flags[flag] is true.
    // The /api/v1/security/users/me/ response ships the flag map.
    // Per ADR-0023 §D9: hidden when off, not greyed (design brief §6).
    // Until /me/ resolves, we render the entry so dev/staging users
    // aren't blocked by a race with the initial fetch — once /me/
    // returns with the flag off, the entry disappears.
    if (n.featureFlag) {
      const flags = (me && me.feature_flags) || null;
      if (flags && !flags[n.featureFlag]) return false;
    }
    // Realm-role gating — same hidden-not-greyed rule. me.roles is
    // populated from /api/v1/security/users/me/ (Keycloak realm roles).
    // Mirror the feature-flag pattern: keep the entry visible until
    // /me/ resolves so the initial render doesn't race the fetch.
    if (n.requireRole) {
      // The "Render as" persona overrides the live session for preview:
      // selecting the EXPLORER analyst surfaces EXPLORER-gated entries
      // even when the authenticated /me/ lacks the realm role.
      const previewGrantsRole = role === "explorer" && n.requireRole === "EXPLORER";
      if (!previewGrantsRole && me && Array.isArray(me.roles)
          && !me.roles.includes(n.requireRole)) {
        return false;
      }
    }
    // The partner self-service tiles only make sense for the
    // partner-analyst role — operator-side roles never use them.
    const PARTNER_ONLY = new Set(["partner-drs", "my-dsa", "my-programmes"]);
    if (role !== "partner-analyst" && PARTNER_ONLY.has(n.id)) return false;
    if (role === "parish" && ["dih","drs","dedup","partners","beneficiaries","data-explorer"].includes(n.id)) return false;
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

  // Which screen, if any, this document was opened as a wide window for.
  const wideWindowScreen = typeof window !== "undefined"
    ? _wideRequestedScreen(window.location.search)
    : null;
  // The wide window's own short stack: the list it was opened at, plus
  // whatever record the operator opens from it.
  const [wideScreen, setWideScreen] = useStateApp(wideWindowScreen);
  const [widePayload, setWidePayload] = useStateApp(null);
  const wideNavigate = (next, payload = null) => {
    setWideScreen(next);
    setWidePayload(payload);
  };
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

  // ── Wide window ───────────────────────────────────────────────────
  if (wideWindowScreen) {
    const current = wideScreen || wideWindowScreen;
    const root = WIDE_SCREENS[wideWindowScreen];
    const entry = WIDE_SCREENS[current] || WIDE_DETAILS[current];
    const atRoot = current === wideWindowScreen;
    return (
      <div className="wide-window">
        <div className="wide-window-bar">
          {atRoot ? (
            <Icon name="maximize" size={14} color="var(--neutral-500)"/>
          ) : (
            <button className="btn btn-sm" onClick={() => wideNavigate(wideWindowScreen)}
                    title={`Back to ${root ? root.label : "the list"}`}>
              <Icon name="chevronLeft" size={13}/> {root ? root.label : "Back"}
            </button>
          )}
          <span className="t-bodysm" style={{fontWeight:600}}>
            {entry ? entry.label : "Wide view"}
          </span>
          <span className="t-cap">wide window · {identityName}</span>
          {impersonator && (
            <span className="t-cap" style={{color:"var(--accent-quality)", fontWeight:600}}>
              <Icon name="shield" size={11}/> impersonating {me?.username} — writes disabled
            </span>
          )}
          <div style={{flex:1}}/>
          <button className="btn btn-sm" onClick={() => window.close()}
                  title="Close this window and go back to the console">
            <Icon name="x" size={13}/> Close window
          </button>
        </div>
        <ErrorBoundary>
          {entry
            ? entry.render(wideNavigate, widePayload)
            : (
              <div className="card" style={{padding:32}}>
                <h3 className="t-h3" style={{marginTop:0}}>
                  {atRoot ? "No wide view for this screen" : "Not available in a wide window"}
                </h3>
                <p className="muted t-bodysm" style={{marginBottom:0}}>
                  <span className="t-mono">{current}</span>{" "}
                  {atRoot
                    ? "does not support the wide view yet. Close this window and use the console tab."
                    : "opens in the main console window — this one holds the list."}
                </p>
                {!atRoot && (
                  <button className="btn mt-3" onClick={() => wideNavigate(wideWindowScreen)}>
                    <Icon name="chevronLeft" size={13}/> Back to {root ? root.label : "the list"}
                  </button>
                )}
              </div>
            )}
        </ErrorBoundary>
      </div>
    );
  }

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
      {/* National masthead — Uganda Coat of Arms on a white tile, navy
          bar with a 3px gold rule, sticky over every route. Search
          and ⌘K affordance removed with this redesign. */}
      <header className="topbar">
        {/* The masthead is the way back to the welcome screen. A real
            anchor, not an onClick handler: it is keyboard reachable, it
            shows its target in the status bar, and middle-click and
            open-in-new-tab behave the way people expect a masthead to.
            It leaves the console deliberately — /home/ is the
            server-rendered welcome screen, not the in-console Home tab,
            which the sidebar still owns. */}
        <a className="topbar-brand" href="/home/" title="Back to the welcome screen">
          <span className="brand-mark">
            <img src="assets/Coat_of_arms_of_Uganda.png" alt="Coat of Arms of Uganda"/>
          </span>
          <div style={{display:'flex', flexDirection:'column', lineHeight:1.15}}>
            <span className="brand-wordmark">National Social Registry</span>
            <span className="brand-sub">Ministry of Gender, Labour and Social Development</span>
          </div>
        </a>

        <div className="topbar-spacer"/>

        <div className="topbar-actions">
          {/* The two consoles are separate pages served by separate
              views, so this is a real anchor: keyboard reachable,
              middle-clickable, and it shows its target in the status
              bar. Shown only to users the Admin Console will admit —
              the same five groups its own view checks. */}
          {window.nsrCanAdminConsole && window.nsrCanAdminConsole(me) && (
            <a className="topbar-switch" href="/admin-console/"
               title="Switch to the Admin Console">
              <Icon name="sliders" size={14}/> Admin Console
            </a>
          )}
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
          <button className="icon-btn" title="My profile" onClick={() => window.nsrProfile()}>
            <Icon name="settings" size={18}/>
          </button>
          <button className="avatar" title={`Open profile for ${identityName}${identityOrg ? " · " + identityOrg : ""}${me?.username ? " (" + me.username + ")" : ""}`} onClick={() => window.nsrProfile()}>{identityInitials}</button>
          <button className="icon-btn" title="Sign out" aria-label="Sign out" onClick={() => window.nsrSignOut()}>
            <Icon name="x" size={18}/>
          </button>
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
          // Live only. A badge appears when an endpoint has returned a
          // number for it and disappears otherwise — there is no
          // hardcoded fallback to fall back TO any more.
          const displayCount = navCounts ? navCounts[n.id] : null;
          if (n.externalHref) {
            return (
              <a key={n.id}
                 className="nav-item"
                 style={n.indent ? { paddingLeft: 32, textDecoration: "none" } : { textDecoration: "none" }}
                 href={n.externalHref}
                 target="_blank"
                 rel="noopener noreferrer">
                <Icon name={n.icon} size={18}/>
                <span className="nav-label">{n.label}</span>
                <Icon name="externalLink" size={12}/>
              </a>
            );
          }
          return (
            <button key={n.id}
                    className={`nav-item ${active ? 'active' : ''}`}
                    style={n.indent ? { paddingLeft: 32 } : undefined}
                    onClick={() => navigate(n.id)}>
              <Icon name={n.icon} size={18}/>
              <span className="nav-label">{n.label}</span>
              {typeof displayCount === "number" && <span className="nav-count">{displayCount}</span>}
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
        {/* The sidebar's Admin is the operator-side admin section (DIH
            sources, operator scopes). The Admin Console linked in the
            masthead is a separate application; the button title says so. */}
        {role !== "partner-analyst" && (
          <button className={`nav-item ${screen === "admin" ? "active" : ""}`}
                  onClick={() => navigate("admin")}
                  title="Operator admin tools. The full Admin Console is linked in the masthead.">
            <Icon name="shield" size={18}/>
            <span className="nav-label">Admin</span>
          </button>
        )}
      </nav>

      {/* Main */}
      <main className="main">
        <ErrorBoundary>
        {/* operatorName is the REAL signed-in identity from
            /api/v1/security/users/me/. Without it HomeScreen falls back to
            ROLE_CONTENT[role].person, which is demo data — so every
            operator was greeted by the same hardcoded name. */}
        {screen === "home"    && <HomeScreen role={role} onNavigate={navigate} operatorName={identityName}/>}
        {screen === "kit"     && <KitScreen/>}
        {screen === "capture" && <CaptureScreen
          device={device} onChangeDevice={setDevice}
          onPromoted={() => setScreen("dih")}/>}
        {screen === "receipt" && <ReceiptScreen/>}
        {screen === "dih"     && <DIHScreen/>}
        {screen === "dedup"   && <DedupScreen/>}
        {screen === "upd"     && <UPDScreen changeRequestId={screenPayload?.changeRequestId} onNavigate={navigate}/>}
        {screen === "drs"     && <DRSScreen onNavigate={navigate}/>}
        {screen === "data-explorer" && <DataExplorerConsoleScreen/>}
        {screen === "grm"     && <GRMScreen
            onNavigate={navigate}
            initialGrievance={screenPayload?.initialGrievance}/>}
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
        {screen === "change-request" && <ChangeRequestScreen
            householdId={screenPayload?.householdId}
            initialScope={screenPayload?.initialScope || "household"}
            roster={screenPayload?.roster || null}
            household={screenPayload?.household || null}
            me={me}
            onBack={() => navigate("household", { householdId: screenPayload?.householdId })}
            onSuccess={() => navigate("household", { householdId: screenPayload?.householdId })}/>}
        {screen === "registry-member-detail" && <MemberDetailScreen
            memberId={screenPayload?.memberId}
            onBack={() => navigate("registry", { initialView: "members" })}
            onOpenHousehold={(rid) => navigate("household", { householdId: rid })}
            onNavigate={navigate}/>}
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

      {/* Global DSA quick-find overlay — wired from the topbar icon.
          Same surface from every screen. */}
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
              { value: "explorer",        label: "Data Explorer Analyst (EXPLORER)" },
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
