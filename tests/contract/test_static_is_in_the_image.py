"""Every STATICFILES_DIRS entry must be COPYed into the container image.

This exists because of a real failure: `static/` was added to the repo and
to STATICFILES_DIRS, but the Dockerfile COPYs named paths rather than the
whole tree, so the directory was absent in the image. Django only *warns*
about a missing STATICFILES_DIRS entry, collectstatic silently collected
nothing, and the public site shipped to production with no stylesheet and
no font — a 404 per asset and a page that renders as unstyled HTML.

Nothing else catches it: it passes locally and in CI, because both have
the directory. Only the built image is wrong. So assert the build recipe.
"""

import re
from pathlib import Path

from django.conf import settings

REPO = Path(settings.BASE_DIR)


def _copied_paths() -> list[str]:
    text = (REPO / "Dockerfile").read_text()
    out = []
    for line in text.splitlines():
        m = re.match(r"\s*COPY\s+(?:--\S+\s+)?(\S+)\s+(\S+)", line)
        if m:
            out.append(m.group(1))
    return out


def test_every_staticfiles_dir_is_copied_into_the_image():
    copied = _copied_paths()
    for entry in settings.STATICFILES_DIRS:
        rel = Path(entry).relative_to(REPO).as_posix()
        assert any(c.rstrip("/") == rel or c == "." for c in copied), (
            f"STATICFILES_DIRS contains {rel!r}, but the Dockerfile never "
            f"COPYs it. collectstatic will silently collect nothing and every "
            f"/static/{rel}/... URL will 404 in the container. COPY lines "
            f"found: {copied}"
        )


def test_the_public_sites_own_assets_are_findable():
    """The two files the public landing page references by name."""
    from django.contrib.staticfiles import finders
    for asset in ("public-site/tokens.css",
                  "public-site/fonts/inter-latin-var.woff2"):
        assert finders.find(asset), f"{asset} is not on the staticfiles path"


def test_the_manual_is_built_into_the_image():
    """`/manual/` is served from docs/user-manual/site/, which is
    MkDocs output and is gitignored.

    Nothing built it in the image, so production answered every
    /manual/ URL with "Manual not built" from the day the view was
    added. The manual existed only on whichever machine had last run
    mkdocs by hand — which is to say, on one laptop.

    Same failure the console had before its build stage: output that
    is gitignored and not generated in the image is output that does
    not exist in production.
    """
    dockerfile = (REPO / "Dockerfile").read_text()

    assert "AS manual-build" in dockerfile, (
        "no stage builds the user manual — /manual/ will 503 in the image"
    )
    assert "mkdocs build" in dockerfile, (
        "the manual stage does not run mkdocs"
    )
    assert "--strict" in dockerfile, (
        "build the manual with --strict, so a dead cross-link fails the "
        "build instead of shipping"
    )
    assert "docs/user-manual/site" in dockerfile, (
        "the rendered manual is never copied into the runtime image"
    )

    from nsr_mis.views import MANUAL_DIR

    served = MANUAL_DIR.relative_to(REPO).as_posix()
    assert f"./{served}" in dockerfile or served in dockerfile, (
        f"the view serves {served} but the Dockerfile copies somewhere else"
    )


def test_the_manual_toolchain_is_pinned():
    """An unpinned docs toolchain is a build that starts failing on a
    day nobody changed anything."""
    import re

    dockerfile = (REPO / "Dockerfile").read_text()
    line = next(
        l for l in dockerfile.splitlines() if "mkdocs" in l and "pip install" in l
    )
    for package in ("mkdocs", "mkdocs-material"):
        assert re.search(rf"{re.escape(package)}==\d", line), (
            f"{package} is not pinned in the manual build stage: {line.strip()}"
        )
