/* global React, Icon */
// NSR MIS — App-level ErrorBoundary
// =====================================================
// Catches synchronous render errors so a single crash doesn't blank
// the whole screen (the failure mode that hit us in commit 1fdfd16
// when a `.replace()` on undefined slipped past). Without this, any
// child throw leaves React with no choice but to unmount the entire
// tree.
//
// Class component is required — React doesn't expose componentDidCatch
// to hooks. Wrap the main content of both consoles (operator shell
// in app.jsx, admin shell in app-admin.jsx).

const ErrorBoundary = class extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null, info: null, key: 0 };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // Log to console so the operator can paste it into a support
    // ticket. The stack trace is in `info.componentStack`.
    // eslint-disable-next-line no-console
    console.error("NSR ErrorBoundary caught:", error, info && info.componentStack);
    this.setState({ info });
  }

  reset = () => {
    // Bumping `key` remounts the child subtree — clears any wedged
    // state that triggered the crash.
    this.setState((s) => ({ error: null, info: null, key: s.key + 1 }));
  };

  goHome = () => {
    if (typeof window !== "undefined" && window.location) {
      // Fall back to a clean reload at the operator console root.
      window.location.href = window.location.pathname;
    }
  };

  render() {
    if (!this.state.error) {
      return React.createElement(
        React.Fragment, { key: this.state.key }, this.props.children,
      );
    }

    const err = this.state.error;
    const msg = (err && (err.message || String(err))) || "Unknown error";
    const stack = (this.state.info && this.state.info.componentStack) || "";

    return (
      <div className="page" style={{ padding: 40, maxWidth: 880, margin: "60px auto" }}>
        <div className="card" style={{ padding: 0, borderTop: "3px solid var(--accent-danger)" }}>
          <div className="card-header" style={{ padding: "16px 24px" }}>
            <div>
              <div className="t-cap" style={{ color: "var(--accent-danger)" }}>
                <Icon name="alert" size={11}/> SCREEN CRASHED
              </div>
              <h2 className="t-h2" style={{ margin: "4px 0 0" }}>
                Something went wrong rendering this view
              </h2>
              <div className="t-cap mt-1">
                Your work is not lost — drafts persist server-side. Try the actions below.
              </div>
            </div>
          </div>
          <div style={{ padding: 24 }}>
            <div className="tint-danger" style={{
              padding: 12, borderRadius: 6,
              borderLeft: "3px solid var(--accent-danger)",
              marginBottom: 16,
            }}>
              <div className="t-cap" style={{ marginBottom: 4 }}>ERROR MESSAGE</div>
              <code style={{
                fontFamily: '"JetBrains Mono", ui-monospace, monospace',
                fontSize: 12.5, color: "var(--neutral-900)",
                wordBreak: "break-word",
              }}>{msg}</code>
            </div>

            <details style={{ marginBottom: 20 }}>
              <summary className="t-cap" style={{ cursor: "pointer", userSelect: "none" }}>
                Show component stack (for support)
              </summary>
              <pre style={{
                marginTop: 8, padding: 12,
                background: "var(--neutral-50)",
                border: "1px solid var(--neutral-200)",
                borderRadius: 4, fontSize: 11.5, lineHeight: 1.5,
                overflowX: "auto", maxHeight: 280,
                color: "var(--neutral-700)",
              }}>{stack.trim() || "(no stack)"}</pre>
            </details>

            <div className="row gap-3">
              <button className="btn" onClick={this.reset}>
                <Icon name="refresh" size={14}/> Retry this screen
              </button>
              <button className="btn" onClick={this.goHome}>
                <Icon name="home" size={14}/> Back to home
              </button>
              <button className="btn" onClick={() => window.location.reload()}>
                <Icon name="reset" size={14}/> Reload page
              </button>
            </div>

            <div className="t-cap mt-4">
              If this keeps happening, paste the error message above into a
              support ticket. The component stack pinpoints which screen
              tripped.
            </div>
          </div>
        </div>
      </div>
    );
  }
};

if (typeof window !== "undefined") {
  window.ErrorBoundary = ErrorBoundary;
}
