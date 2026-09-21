/* global React, Icon, Chip, PageHeader, Field */
// NSR MIS — Reference data · Questionnaire (instrument) wave review
// =====================================================
// ADR-0034. UBOS collects the national household data on a CSPro
// instrument it owns, and delivers it to MGLSD in periodic waves. The
// instrument changes between waves — questions added, answer-code lists
// revised — and MGLSD cannot refuse a wave.
//
// So the only defence against a change arriving unnoticed is to read the
// dictionary and compare it with the last one accepted. This screen is
// that comparison.
//
// It is READ-ONLY and stateless. It records no decision and stores
// nothing; it is the surface a reviewer reads. Capturing what they
// decided needs the persisted FormVersion and the dual-approval
// workflow, which is a separate build.
//
// The headline it exists to surface is `code.relabelled`: an answer code
// whose meaning changed while its value stayed the same. `3 = Wood`
// becoming `3 = Concrete` reclassifies every household already coded 3,
// nothing errors, and two dictionaries side by side will not show it to
// a person. That is why BREAKING sorts first and why the count sits at
// the top of the screen rather than at the bottom of a list.

const { useState: useStateInstr, useCallback: useCallbackInstr } = React;

const SEVERITY_TONE = {
  breaking: "danger",
  review: "quality",
  info: "data",
};

const SEVERITY_LABEL = {
  breaking: "Needs a decision",
  review: "Review",
  info: "Informational",
};

// A dropped file or a pasted body. Both are offered because a reviewer
// comparing two builds of the tool has files, while someone checking a
// single suspect value set has a fragment.
const DictionaryInput = ({ id, title, hint, value, onChange, fileName, onFile }) => (
  <div className="card" style={{ padding: 0 }}>
    <div className="card-header" style={{ padding: "12px 16px" }}>
      <div>
        <h3 className="t-h3" style={{ margin: 0 }}>{title}</h3>
        <div className="t-cap">{hint}</div>
      </div>
      {fileName && <Chip tone="data">{fileName}</Chip>}
    </div>
    <div style={{ padding: 16 }}>
      <Field label={`${title} — .dcf file`}>
        <input type="file" accept=".dcf,.txt,text/plain"
          onChange={(e) => onFile(e.target.files && e.target.files[0])}/>
      </Field>
      <Field label={`${title} — or paste the dictionary text`}
        hint="Pasting overrides the file above.">
        <textarea className="field-input" rows={8} id={id}
          style={{ fontFamily: "var(--font-mono, monospace)", fontSize: 12 }}
          placeholder={"[Dictionary]\nName=NSRHH\nVersion=2026.1\n…"}
          value={value}
          onChange={(e) => onChange(e.target.value)}/>
      </Field>
    </div>
  </div>
);

const ChangeRow = ({ change }) => {
  const tone = SEVERITY_TONE[change.severity] || "data";
  return (
    <div style={{
      padding: "14px 16px",
      borderLeft: `3px solid var(--accent-${tone})`,
      background: change.severity === "breaking" ? `var(--accent-${tone}-bg)` : "var(--neutral-0)",
      borderBottom: "1px solid var(--neutral-200)",
    }}>
      <div className="row gap-3" style={{ alignItems: "flex-start" }}>
        <Chip tone={tone} size="sm">{SEVERITY_LABEL[change.severity]}</Chip>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 600, fontSize: 13.5 }}>{change.summary}</div>
          {(change.old || change.new) && (
            <div className="t-mono" style={{ fontSize: 12, marginTop: 6, color: "var(--neutral-700)" }}>
              {change.old || "(none)"}
              <Icon name="arrowRight" size={12}/>
              {change.new || "(none)"}
            </div>
          )}
          {change.detail && (
            <div className="t-bodysm" style={{ marginTop: 6, color: "var(--neutral-700)", lineHeight: 1.6 }}>
              {change.detail}
            </div>
          )}
        </div>
        <span className="t-cap t-mono" style={{ whiteSpace: "nowrap" }}>{change.kind}</span>
      </div>
    </div>
  );
};

const AdminInstrumentReviewScreen = () => {
  const [oldText, setOldText] = useStateInstr("");
  const [newText, setNewText] = useStateInstr("");
  const [oldFile, setOldFile] = useStateInstr(null);
  const [newFile, setNewFile] = useStateInstr(null);
  const [result, setResult] = useStateInstr(null);
  const [error, setError] = useStateInstr(null);
  const [busy, setBusy] = useStateInstr(false);
  const [filter, setFilter] = useStateInstr("");   // "" | severity

  const canCompare = !!((oldText.trim() || oldFile) && (newText.trim() || newFile));

  const compare = useCallbackInstr(async () => {
    setBusy(true); setError(null); setResult(null);
    try {
      // Multipart so a .dcf can be uploaded without the reviewer having
      // to open it in an editor first.
      const body = new FormData();
      if (oldText.trim()) body.append("old_text", oldText);
      else if (oldFile) body.append("old_file", oldFile);
      if (newText.trim()) body.append("new_text", newText);
      else if (newFile) body.append("new_file", newFile);

      const csrf = (document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/) || [])[1] || "";
      const r = await fetch("/api/v1/intake/cspro/diff/", {
        method: "POST",
        headers: csrf ? { "X-CSRFToken": csrf } : {},
        credentials: "same-origin",
        body,
      });
      const payload = await r.json().catch(() => null);
      if (!r.ok) {
        // The API returns per-field parse errors. Show them verbatim —
        // "old: duplicate item name 'ROOF'" is actionable; "failed" is not.
        const detail = payload && typeof payload === "object"
          ? Object.entries(payload).map(([k, v]) => `${k}: ${[].concat(v).join(", ")}`).join(" · ")
          : `HTTP ${r.status}`;
        throw new Error(detail);
      }
      setResult(payload);
    } catch (err) {
      setError(String((err && err.message) || err));
    } finally {
      setBusy(false);
    }
  }, [oldText, newText, oldFile, newFile]);

  const shown = result
    ? (filter ? result.changes.filter(c => c.severity === filter) : result.changes)
    : [];

  return (
    <div className="page">
      <PageHeader
        eyebrow="REFERENCE DATA · ADR-0034"
        title="Questionnaire wave review"
        sub={"Compare an incoming UBOS instrument against the last one accepted. "
           + "Read-only — nothing here is stored, and no decision is recorded."}
        right={
          <button className="btn btn-primary" disabled={!canCompare || busy}
            title={canCompare ? "Compare the two dictionaries"
                              : "Supply both dictionaries first"}
            onClick={compare}>
            <Icon name="check" size={14}/>{busy ? "Comparing…" : "Compare"}
          </button>
        }
      />

      {/* This pane once read "the instrument the registry is already
          interpreting", which the system cannot confirm: it is whatever
          file the reviewer picked. Comparing against the wrong .dcf
          produces a diff that is wrong and looks authoritative, and a
          clean changeset would then mean nothing at all.

          US-121 makes the accepted instrument a stored FormVersion, so
          this side comes from the registry instead of from a file
          somebody remembered to keep. Until then the claim is retracted
          rather than quietly left standing. */}
      <div className="card" style={{ padding: 14, borderLeft: "3px solid var(--accent-quality)" }}>
        <div className="row gap-2" style={{ alignItems: "flex-start" }}>
          <Icon name="info" size={15} color="var(--accent-quality)"/>
          <div className="t-bodysm" style={{ color: "var(--neutral-700)", lineHeight: 1.6 }}>
            <strong>Both sides are supplied by you.</strong> The registry does not
            yet store the accepted instrument, so it cannot confirm that the
            dictionary on the left is the one it is actually interpreting.
            Check you are comparing against the right wave &mdash; a diff against
            the wrong <code>.dcf</code> is wrong and looks authoritative.
          </div>
        </div>
      </div>

      <div className="grid grid-2 mt-4" style={{ gap: 20 }}>
        <DictionaryInput id="dcf-old" title="Previous instrument"
          hint="Whichever .dcf this wave should be compared against."
          value={oldText} onChange={setOldText}
          fileName={oldFile && oldFile.name}
          onFile={(f) => { setOldFile(f); setOldText(""); }}/>
        <DictionaryInput id="dcf-new" title="Incoming wave"
          hint="The dictionary delivered with this wave's data."
          value={newText} onChange={setNewText}
          fileName={newFile && newFile.name}
          onFile={(f) => { setNewFile(f); setNewText(""); }}/>
      </div>

      {error && (
        <div className="card mt-5 tint-danger" style={{ padding: 16, borderLeft: "3px solid var(--accent-danger)" }}>
          <div className="row gap-2">
            <Icon name="alert" size={16} color="var(--accent-danger)"/>
            <div>
              <strong className="t-bodysm">Could not compare these dictionaries</strong>
              <div className="t-bodysm" style={{ marginTop: 4, color: "var(--neutral-700)" }}>{error}</div>
            </div>
          </div>
        </div>
      )}

      {result && (
        <>
          <div className="card mt-5">
            <div className="card-header">
              <div>
                <h3 className="t-h3" style={{ margin: 0 }}>
                  {result.old.version || result.old.name}
                  {" → "}
                  {result.new.version || result.new.name}
                </h3>
                <div className="t-cap">
                  {result.old.items} items → {result.new.items} items
                </div>
              </div>
              {result.is_clean
                ? <Chip tone="eligibility">Nothing needs a decision</Chip>
                : <Chip tone="danger">{result.counts.breaking} need a decision</Chip>}
            </div>
            {/* These carry the same words as the severity chips on the
                rows below, so without a group name and a per-button
                label a screen reader reads "Needs a decision" twice and
                cannot tell the filter from the status. */}
            <div className="row gap-3" style={{ padding: 16, flexWrap: "wrap" }}
              role="group" aria-label="Filter by severity">
              {[
                ["", "All", result.changes.length],
                ["breaking", SEVERITY_LABEL.breaking, result.counts.breaking],
                ["review", SEVERITY_LABEL.review, result.counts.review],
                ["info", SEVERITY_LABEL.info, result.counts.info],
              ].map(([key, label, count]) => (
                <button key={key || "all"}
                  onClick={() => setFilter(key)}
                  aria-pressed={filter === key}
                  aria-label={key ? `Show only: ${label} (${count})`
                                  : `Show all changes (${count})`}
                  className="btn btn-sm"
                  style={filter === key ? {
                    background: "var(--accent-data-bg)",
                    borderColor: "var(--accent-data)",
                    color: "var(--accent-data)",
                  } : undefined}>
                  {label} <strong style={{ marginLeft: 6 }}>{count}</strong>
                </button>
              ))}
            </div>
          </div>

          {!result.is_clean && (
            <div className="card mt-4 tint-danger" style={{ padding: 16, borderLeft: "3px solid var(--accent-danger)" }}>
              <div className="t-bodysm" style={{ color: "var(--neutral-900)", lineHeight: 1.65 }}>
                <strong>{result.counts.breaking} change{result.counts.breaking === 1 ? "" : "s"} need
                a decision before this wave&rsquo;s data can be interpreted.</strong>
                {" "}None of them may be resolved by picking the nearest matching
                code. Where an old code has no equivalent in the new frame,
                record that it has none &mdash; a guess becomes a PMT band, and a
                wrong PMT band is a household that does not receive a transfer.
              </div>
            </div>
          )}

          <div className="card mt-4" style={{ padding: 0, overflow: "hidden" }}>
            {shown.length === 0 && (
              <div className="t-bodysm muted" style={{ padding: "28px 20px", textAlign: "center" }}>
                {result.changes.length === 0
                  ? "The two dictionaries are identical."
                  : "No changes at this severity."}
              </div>
            )}
            {shown.map((change, i) => <ChangeRow key={i} change={change}/>)}
          </div>
        </>
      )}

      {!result && !error && (
        <div className="card mt-5" style={{ padding: 28, textAlign: "center" }}>
          <Icon name="inbox" size={28} color="var(--neutral-300)"/>
          <div className="t-bodysm muted mt-2">
            Supply both dictionaries and press Compare.
          </div>
          <div className="t-cap" style={{ marginTop: 8, maxWidth: 560, margin: "8px auto 0" }}>
            The <code>.dcf</code> data dictionary is the machine-readable
            definition of every question and every answer code. For CSPro&rsquo;s
            native fixed-width export it is not optional &mdash; the data file
            cannot be parsed without it.
          </div>
        </div>
      )}
    </div>
  );
};

Object.assign(window, { AdminInstrumentReviewScreen });
