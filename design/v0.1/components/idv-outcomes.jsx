/* global React, Icon, Chip */
// IDV outcome vocabulary — one declaration, every surface
// =====================================================
// StageRecord.idv_outcome records what identity verification said about
// a record. It is written in nine places across apps/ingestion_hub and
// apps/identity_verification, and was READ in two places that each
// invented their own spelling of it.
//
// The queue column compared against "Matched" / "Mismatch" — capitalised
// display words the backend has never written. Both branches were
// unreachable, so every record fell through to a default amber
// "Pending": a NIRA MISMATCH, an operator's manual acceptance, and a
// household that never offered a NIN all rendered identically, and all
// of them rendered as something that had not happened yet.
//
// The direction of that failure is what made it serious. It failed
// benign: the one outcome a reviewer must not miss — a NIN that did not
// match NIRA — was displayed as routine waiting, on the panel used to
// decide whether to promote a household into the national registry.
//
// So: one table, consulted by the column, the decision panel and the
// filter. A value the backend can write and this table cannot explain
// is a visible defect, never a quiet fallback — see `idvOutcome`.
//
// The codes here are asserted against the Python source by
// apps/ingestion_hub/test_idv_vocabulary.py, so adding an outcome on the
// server without teaching the console to render it fails CI.

//: code -> how the console renders it.
//  `label`  short, for the queue column chip
//  `tone`   Chip tone; danger is reserved for "a human must look"
//  `detail` the sentence the decision panel shows
const IDV_OUTCOMES = {
  "": {
    label: "Not run",
    tone: "neutral",
    detail: "No NIN was offered for any member, so there was nothing to verify.",
  },
  match: {
    label: "Matched",
    tone: "identity",
    detail: "NIRA confirmed this NIN against the person's details.",
  },
  mismatch: {
    label: "Mismatch",
    tone: "danger",
    detail: "NIRA holds this NIN but the details do not agree. "
          + "Reconcile before promoting — the household may not be who the record says.",
  },
  no_match: {
    label: "Not found",
    tone: "danger",
    detail: "NIRA has no record of this NIN. Check it was transcribed correctly "
          + "before treating it as a false identity.",
  },
  bad_format: {
    label: "Bad format",
    tone: "danger",
    detail: "The NIN is not a valid NIRA identifier, so it was never checked. "
          + "Usually a capture error; correct it and re-run the gates.",
  },
  service_unavailable: {
    label: "NIRA unreachable",
    tone: "quality",
    detail: "NIRA could not be reached. Nothing is known to be wrong with this "
          + "record — the check simply has not happened. Re-run the gates later.",
  },
  manual_accept: {
    label: "Accepted by operator",
    tone: "update",
    detail: "An operator accepted this identity on paper or in-person evidence, "
          + "without a NIRA match. The acceptance is in the audit chain.",
  },
  nin_partial: {
    label: "Last 4 only",
    tone: "quality",
    detail: "A NIN card was seen and the last 4 digits recorded. NIRA needs the "
          + "full number — collect it at the IDV step, then re-run the gates.",
  },
  unknown: {
    label: "Unrecognised",
    tone: "quality",
    detail: "NIRA returned a status this system does not recognise. Treat the "
          + "identity as unverified until someone has looked at it.",
  },
};

/** How to render one outcome code.
 *
 *  A code with no entry is rendered AS ITSELF and flagged, never folded
 *  into a friendly default. Silently defaulting is exactly what turned
 *  a NIRA mismatch into "Pending"; a value the console does not
 *  understand should look like something went wrong, because it did.
 */
const idvOutcome = (code) => {
  const key = (code === null || code === undefined) ? "" : String(code).trim();
  if (Object.prototype.hasOwnProperty.call(IDV_OUTCOMES, key)) {
    return { code: key, known: true, ...IDV_OUTCOMES[key] };
  }
  return {
    code: key,
    known: false,
    label: key,
    tone: "danger",
    detail: `The registry recorded an identity outcome of "${key}", which this `
          + "console has no rendering for. Do not read it as verified.",
  };
};

/** The queue column's chip. */
const IdvChip = ({ outcome, size = "sm" }) => {
  const o = idvOutcome(outcome);
  return (
    <Chip tone={o.tone} size={size} title={o.detail}>
      {o.known && o.code === "match" && <Icon name="check" size={11}/>}
      {!o.known && <Icon name="alert" size={11}/>}
      {o.label || "—"}
    </Chip>
  );
};

Object.assign(window, { IDV_OUTCOMES, idvOutcome, IdvChip });
