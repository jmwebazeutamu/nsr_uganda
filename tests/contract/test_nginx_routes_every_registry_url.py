"""nginx must route every registry URL prefix to the registry container.

Production serves ONE hostname from TWO containers. nginx path-routes a
fixed list of prefixes to the registry and sends everything else to the
public site, which runs `ROOT_URLCONF=nsr_mis.urls_public` and therefore
has almost no routes at all.

So a URL added to `nsr_mis/urls.py` but not to the nginx config does not
fail loudly — it falls through to the public container and returns **404**,
while working perfectly in every test that uses the Django test client,
because the test client never goes through nginx.

That is exactly how `/profile/` shipped broken: the view worked, its own
tests passed, and the page 404'd in production.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.urls import get_resolver

REPO = Path(__file__).resolve().parent.parent.parent
CONFS = [
    REPO / "infrastructure" / "nginx" / "nsr-sris.http.conf",
    REPO / "infrastructure" / "nginx" / "nsr-sris.ssl.conf",
]

#: Prefixes the PUBLIC container is meant to answer. "" is the public
#: landing page — nginx's catch-all sends it there deliberately.
PUBLIC_OWNED = {""}


def _nginx_prefixes(conf: Path) -> set[str]:
    """Prefixes nginx proxies to the registry upstream."""
    text = conf.read_text()
    found = set()
    for m in re.finditer(
        r'location\s+(?:=\s+)?(/[^\s{]*)\s*\{[^}]*?proxy_pass\s+http://nsr_registry',
        text, re.S,
    ):
        found.add(m.group(1).strip("/"))
    return found


def _registry_top_level() -> set[str]:
    """Top-level path prefixes the registry URLconf actually serves."""
    out = set()
    for p in get_resolver().url_patterns:
        pat = str(getattr(p, "pattern", ""))
        if not pat or pat.startswith("^"):
            continue
        out.add(pat.split("/")[0].strip("/"))
    return {p for p in out if p and "<" not in p}


@pytest.mark.parametrize("conf", CONFS, ids=lambda c: c.name)
def test_every_registry_prefix_is_routed_by_nginx(conf):
    routed = _nginx_prefixes(conf)
    needed = _registry_top_level() - PUBLIC_OWNED
    missing = sorted(p for p in needed if p not in routed)
    assert not missing, (
        f"{conf.name} does not route {missing} to the registry container. "
        f"Those URLs will fall through to the public site and return 404 in "
        f"production, while passing every Django test-client test. Add a "
        f"`location /<prefix>/` block proxying to nsr_registry."
    )


@pytest.mark.parametrize("conf", CONFS, ids=lambda c: c.name)
def test_the_public_catch_all_strips_cookies(conf):
    """The public route must not receive an operator's session cookie.

    nginx matches the LONGEST prefix, so every registry prefix above beats
    `location /` and keeps its cookies; only what falls through to the
    public site is stripped. That is why this needs no negative lookahead,
    unlike the Apache vhost on the training box — but the strip itself has
    to be there, or an operator session reaches the public process
    (LP-O-10).
    """
    text = conf.read_text()
    # The TLS config has two `location /` blocks: the :80 server redirects
    # to https, the :443 server is the public catch-all. Only the one that
    # proxies to the public site is in scope here.
    blocks = re.findall(r"location\s+/\s*\{(.*?)\n    \}", text, re.S)
    public = [b for b in blocks if "proxy_pass http://nsr_public" in b]
    assert public, (
        f"{conf.name}: no catch-all `location /` proxying to the public site"
    )
    for block in public:
        assert re.search(r'proxy_set_header\s+Cookie\s+""', block), (
            f"{conf.name}: the public catch-all does not strip cookies, so an "
            f"operator's session would reach the public process (LP-O-10)."
        )
