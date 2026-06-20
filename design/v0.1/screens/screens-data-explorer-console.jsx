/* global React, Icon, PageHeader, Chip,
   DataExplorerCatalogueScreen, DataExplorerBuilderScreen,
   DataExplorerResultsScreen, DataExplorerCoverageScreen,
   DataExplorerSyntheticScreen */
// Data Explorer console host.
//
// The full Data Explorer still lives in its five-screen standalone
// harness because those screens own their tab shell and backend hooks.
// This host brings that harness back into the main NSR console so the
// sidebar route is live instead of opening an external tab.

const { useEffect: useDeConsoleEffect, useState: useDeConsoleState } = React;

const DATA_EXPLORER_CONSOLE_TABS = [
  {
    id: "catalogue",
    label: "Catalogue",
    icon: "book",
    href: "v0.1/screens/data-explorer/Data Explorer - Catalogue.html",
  },
  {
    id: "builder",
    label: "Builder",
    icon: "sliders",
    href: "v0.1/screens/data-explorer/Data Explorer - Aggregate Builder.html",
  },
  {
    id: "results",
    label: "Results",
    icon: "barchart",
    href: "v0.1/screens/data-explorer/Data Explorer - Results.html",
  },
  {
    id: "coverage",
    label: "Coverage",
    icon: "mapPin",
    href: "v0.1/screens/data-explorer/Data Explorer - Coverage.html",
  },
  {
    id: "synthetic",
    label: "Synthetic",
    icon: "database",
    href: "v0.1/screens/data-explorer/Data Explorer - Synthetic Sample.html",
  },
];

const DataExplorerConsoleScreen = () => {
  const [active, setActive] = useDeConsoleState(DATA_EXPLORER_CONSOLE_TABS[0]);
  const [navKey, setNavKey] = useDeConsoleState(0);

  useDeConsoleEffect(() => {
    window.NSR_DATA_EXPLORER_NAVIGATE = (id, params = {}) => {
      const next = DATA_EXPLORER_CONSOLE_TABS.find(tab => tab.id === id);
      if (!next) return;
      window.NSR_DATA_EXPLORER_PARAMS = params;
      setActive(next);
      setNavKey(k => k + 1);
    };
    return () => {
      delete window.NSR_DATA_EXPLORER_NAVIGATE;
      delete window.NSR_DATA_EXPLORER_PARAMS;
    };
  }, []);

  return (
    <div className="de-console-screen">
      <PageHeader
        eyebrow="DATA EXPLORER"
        title="Data Explorer console"
        sub="Live discovery, aggregate preview, coverage, and DRS handoff against the Data Explorer API."
        right={<>
          <Chip tone="data" size="sm">live backend</Chip>
          <a className="btn" href={active.href} target="_blank" rel="noopener noreferrer">
            <Icon name="externalLink" size={14}/> Open full screen
          </a>
        </>}
      />

      <div className="card de-console-card">
        <div className="de-console-tabs" role="tablist" aria-label="Data Explorer screens">
          {DATA_EXPLORER_CONSOLE_TABS.map((tab) => {
            const selected = tab.id === active.id;
            return (
              <button
                key={tab.id}
                type="button"
                className={`de-console-tab ${selected ? "active" : ""}`}
                role="tab"
                aria-selected={selected}
                onClick={() => {
                  window.NSR_DATA_EXPLORER_PARAMS = {};
                  setActive(tab);
                  setNavKey(k => k + 1);
                }}
              >
                <Icon name={tab.icon} size={15}/>
                <span>{tab.label}</span>
              </button>
            );
          })}
          <div className="de-console-tabs-spacer"/>
          <span className="t-cap">same-origin session · /api/v1/data-explorer/</span>
        </div>

        <div className="de-console-embedded" key={`${active.id}-${navKey}`}>
          {active.id === "catalogue" && <DataExplorerCatalogueScreen/>}
          {active.id === "builder" && <DataExplorerBuilderScreen/>}
          {active.id === "results" && <DataExplorerResultsScreen/>}
          {active.id === "coverage" && <DataExplorerCoverageScreen/>}
          {active.id === "synthetic" && <DataExplorerSyntheticScreen/>}
        </div>
      </div>
    </div>
  );
};

Object.assign(window, { DataExplorerConsoleScreen });
