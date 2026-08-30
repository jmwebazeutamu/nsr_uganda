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
