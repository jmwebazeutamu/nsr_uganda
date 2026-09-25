/* global React, window */
// The DSA field-group vocabulary, from the server.
//
// Two screens used to carry their own copy — screens-dsas.jsx and
// components/scope-edit-modal.jsx — and both disagreed with the
// server. They offered `Roster`, `Housing` and `FoodShocks`; the
// request validator resolves a requested field to its group through
// the DRS field catalogue, which calls those `Members`, `Dwelling` +
// `Utilities`, and `Food consumption` + `Food security`.
//
// So an agreement written here granted `Roster`, and a partner asking
// for `member.surname` was refused as "outside DSA scope" — for a
// group their agreement did grant, in wording that blamed them.
//
// And `Geography` was never on the list at all, so no agreement
// written through this console could ever grant a partner the
// household's location.
//
// The list is now asked for. A console that cannot reach the API
// renders no checkboxes rather than a plausible wrong list: a scope
// picker that silently offers the wrong vocabulary is how the two
// production agreements came to be written.

const { useState: _fgState, useEffect: _fgEffect } = React;

const FIELD_GROUPS_API = "/api/v1/drs/requests/field-groups/";

const useFieldGroups = () => {
  const [groups, setGroups] = _fgState([]);
  const [state, setState] = _fgState("loading");

  _fgEffect(() => {
    let live = true;
    fetch(FIELD_GROUPS_API, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(data => {
        if (!live) return;
        setGroups((data && data.groups) || []);
        setState("live");
      })
      .catch(() => { if (live) { setGroups([]); setState("offline"); } });
    return () => { live = false; };
  }, []);

  return [groups, state];
};

window.useFieldGroups = useFieldGroups;
window.FIELD_GROUPS_API = FIELD_GROUPS_API;
