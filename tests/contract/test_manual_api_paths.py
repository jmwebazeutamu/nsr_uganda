"""Every API path the user manual cites resolves.

The manual is what an integrator reads before writing a client, and
what an operator reads when something looks wrong. On 25 September 2026
a sweep found **40 of the 122 paths it cited did not exist**:

  * the IDV page documented `/api/v1/idv/verify/` and
    `/api/v1/idv/results/{id}/`; the module serves one route, a sandbox
    mock, and nothing else;
  * the PMT page documented `configurations/` and
    `scores/{household_id}/`; the resources are `model-versions` and
    `results`.

Nobody had written a client against them, as far as anyone knows. That
is luck, not a control.

Prose drifts from code silently — that is what prose does. The console
has the same guard in `test_console_api_paths.py`, for the same reason
and after the same kind of incident.

Pages may legitimately cite a path that does not exist yet: a module
still being designed. Those go in PLANNED with the reason, so the
exception is visible in review rather than invisible in a file nobody
re-reads.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.urls import Resolver404, resolve

MANUAL = Path("docs/user-manual/docs")

#: The changelog records what a page USED to say, including the paths
#: and entities that turned out not to exist. Checking it would make
#: the correction unwritable — and a correction nobody can write down
#: is how the manual got into this state.
HISTORY = {"about/changelog.md"}

#: path -> why the manual names a route that does not resolve.
#:
#: Two kinds live here: a path documented ahead of being built, and a
#: path the manual has always named that was never built. The second
#: kind must be struck through on the page and labelled, so a reader
#: is not left believing in it — the entry here only stops the test
#: failing on a row that already tells the truth.
PLANNED: dict[str, str] = {
    "/api/v1/upd/change-requests/{id}/commit/":
        "never built — the commit runs in-process on approval. Struck "
        "through and labelled on modules/upd.md.",
    "/api/v1/data-management/households/{id}/versions/":
        "never built — HouseholdVersion rows exist but nothing serves "
        "the chain. Struck through and labelled on modules/dat.md.",
}

_PLACEHOLDER = re.compile(r"\{[^}]+\}|<[^>]+>")


#: A path that is nothing but a placeholder — `/api/v1/<module>/` in
#: the pages that describe the URL convention — is a template, not a
#: claim that an endpoint exists.
_TEMPLATE = re.compile(r"^/api/v1/<[^>]+>/?\.{0,3}$")


def cited_paths() -> dict[str, set[str]]:
    """Every `/api/v1/...` in backticks, and which pages cite it."""
    found: dict[str, set[str]] = {}
    for page in sorted(MANUAL.rglob("*.md")):
        if str(page.relative_to(MANUAL)) in HISTORY:
            continue
        for path in re.findall(r"`(/api/v1/[^`\s]*)`", page.read_text()):
            if _TEMPLATE.match(path):
                continue
            found.setdefault(path, set()).add(str(page.relative_to(MANUAL)))
    return found


def probes(path: str) -> list[str]:
    """The documented path with its placeholders filled in.

    Both with and without a trailing slash: some routes are registered
    without one (`/api/v1/idv/nira-mock/verify`), and a manual that
    writes it either way is not wrong about whether the endpoint
    exists.
    """
    bare = _PLACEHOLDER.sub("01ABCDEFGHIJKLMNOPQRSTUVWX", path).split("?")[0]
    return [bare.rstrip("/"), bare.rstrip("/") + "/"]


ALL = cited_paths()


def test_the_manual_cites_api_paths_at_all():
    """A regex that stopped matching would make the case below pass
    vacuously, which is how sweeps like this go wrong."""
    assert len(ALL) > 80, f"only found {len(ALL)} — has the format changed?"


@pytest.mark.parametrize("path", sorted(ALL))
def test_the_path_exists(path):
    if path in PLANNED:
        pytest.skip(f"documented ahead of build: {PLANNED[path]}")
    for candidate in probes(path):
        try:
            resolve(candidate)
            return
        except Resolver404:
            continue
    else:
        pytest.fail(
            f"{path} is documented in "
            f"{', '.join(sorted(ALL[path]))} and does not resolve.\n"
            "Fix the page, or add it to PLANNED with the reason it is "
            "documented before it is built."
        )


# --- entities -------------------------------------------------------

#: Names in backticks that are not models and are not claimed to be:
#: Python classes, DRF permission classes, settings, enum members,
#: JSX constants. Everything else is checked.
NOT_A_MODEL = {
    "APIView", "AuditReadMixin", "CATEGORIES", "CharField", "COUNTY",
    "ChangeType", "DEBUG", "DateField", "False", "Granted",
    "IsAdminConsoleUser", "IsAuthenticated", "MERGED", "Refused",
    "Withdrawn",
}

#: Names the manual mentions *in order to say they do not exist* —
#: "this page used to list X; it was never built". Flagging those
#: would make the correction impossible to write down, and the whole
#: point of the correction is that a reader who believed the old page
#: finds out.
KNOWN_ABSENT = {
    "BuilderSchema", "ChangeRequestDiff", "Delivery",
    "ProgrammeLifecycleEvent", "ReferralStatus", "Relationship",
    "RoutingDecision", "SourceCredential", "StagedRecord",
    "VitalEvent",  # named on modules/idv.md only to say it is absent
}


def cited_entities() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for page in sorted(MANUAL.rglob("*.md")):
        if str(page.relative_to(MANUAL)) in HISTORY:
            continue
        for name in re.findall(r"`([A-Z][A-Za-z]{4,30})`", page.read_text()):
            if name in NOT_A_MODEL or name in KNOWN_ABSENT:
                continue
            found.setdefault(name, set()).add(str(page.relative_to(MANUAL)))
    return found


def test_the_manual_names_entities_that_exist():
    """The manual described `ChangeRequestDiff`, `RoutingDecision`,
    `MatchCandidate`, `MatchModel`, `PmtConfiguration`, `PmtScore`,
    `IdvResult`, `RawRecord`, `Delivery`, `BuilderSchema` and
    `ProgrammeLifecycleEvent`. None of them was ever built.

    A reader cannot tell an invented entity from a real one, and a
    developer given this page as a spec would implement the wrong
    model. Checked against the app registry rather than against
    memory.
    """
    from django.apps import apps

    real = {m.__name__ for m in apps.get_models()}
    cited = cited_entities()
    assert len(cited) > 20, f"only found {len(cited)} — has the format changed?"

    invented = {n: w for n, w in cited.items() if n not in real}
    assert invented == {}, "\n" + "\n".join(
        f"  `{n}` is described in {', '.join(sorted(w))} and is not a model"
        for n, w in sorted(invented.items())
    )
