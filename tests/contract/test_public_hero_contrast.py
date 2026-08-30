"""Hero legibility on the public site.

Regression guard for a shipped bug: `.slot`, the placeholder-copy marker,
set a cream background and no foreground. On the light sections it
inherited dark ink and read fine. In the hero it inherited
--public-hero-fg (white) onto that cream fill — 1.08:1 — so the
standfirst, the counter values and the "as at" captions rendered as blank
cream rectangles. The H1 and eyebrow escaped only because they carry
their own colour.

The general rule this pins: a class that supplies its own background must
supply its own foreground. Inheriting one half of a colour pair is what
makes a rule that is fine on one surface invisible on another.

Ratios come from spec §4.2 / §11.1: 4.5:1 for body text, 3:1 for large
text and UI components.
"""

import re
from pathlib import Path

import pytest
from django.conf import settings

TEMPLATE = Path(settings.BASE_DIR) / "nsr_mis/templates/public_site/landing.html"
TOKENS = Path(settings.BASE_DIR) / "static/public-site/tokens.css"

BODY_MIN, LARGE_MIN = 4.5, 3.0


# --- colour maths ---------------------------------------------------------

def _lin(c):
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _lum(rgb):
    r, g, b = rgb
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def ratio(fg, bg):
    a, b = _lum(fg), _lum(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def _hex(h):
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _over(fg_rgba, bg):
    """Composite rgba(...) over an opaque background."""
    (r, g, b, a) = fg_rgba
    return tuple(
        round(a * c + (1 - a) * d)
        for c, d in zip((r, g, b), bg, strict=True)
    )


# --- token resolution -----------------------------------------------------

def _tokens():
    text = TEMPLATE.read_text() + "\n" + TOKENS.read_text()
    raw = dict(re.findall(r"(--[\w-]+)\s*:\s*([^;\n}]+)", text))
    return {k: v.strip() for k, v in raw.items()}


def resolve(value, tokens, depth=0):
    """Resolve var(--x) chains to a literal colour value."""
    value = value.strip()
    for _ in range(10):
        m = re.fullmatch(r"var\((--[\w-]+)\)", value)
        if not m:
            break
        value = tokens[m.group(1)].strip()
    return value


def as_rgb(value, tokens, *, over=None):
    v = resolve(value, tokens)
    if v.startswith("#"):
        return _hex(v)
    m = re.fullmatch(r"rgba?\(([^)]+)\)", v)
    if m:
        parts = [p.strip() for p in m.group(1).split(",")]
        rgb = tuple(int(float(p)) for p in parts[:3])
        if len(parts) == 4:
            alpha = float(parts[3])
            assert over is not None, f"{v} needs a backdrop to composite over"
            return _over((*rgb, alpha), over)
        return rgb
    raise AssertionError(f"cannot resolve colour {value!r} -> {v!r}")


def rule(selector):
    """The declaration body of a CSS rule, by exact selector text."""
    src = TEMPLATE.read_text()
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", src)
    assert m, f"no CSS rule for {selector!r}"
    return m.group(1)


def decl(selector, prop):
    body = rule(selector)
    m = re.search(rf"(?<![\w-]){prop}\s*:\s*([^;]+)", body)
    return m.group(1).strip() if m else None


# --- the guard ------------------------------------------------------------

class TestAFillAlwaysCarriesAForeground:
    """The class of bug, not just the instance."""

    def test_slot_declares_its_own_colour(self):
        assert decl(".slot", "color"), (
            ".slot sets a background but no color, so it inherits one. That "
            "is exactly the bug: fine on light sections, 1.08:1 in the hero."
        )

    def test_slot_is_legible_on_its_own_fill(self):
        t = _tokens()
        fg = as_rgb(decl(".slot", "color"), t)
        bg = as_rgb(decl(".slot", "background"), t)
        assert ratio(fg, bg) >= BODY_MIN, f"{ratio(fg, bg):.2f}:1 on the cream fill"

    def test_the_dark_surfaces_get_their_own_slot_rule(self):
        assert decl(".hero .slot,\n.dark .slot", "color") or decl(
            ".hero .slot", "color"), "no dark-surface override for .slot"


class TestHeroContrast:
    """Every hero pair, measured. Placeholder state is the failing one."""

    @pytest.fixture
    def t(self):
        return _tokens()

    @pytest.fixture
    def hero_bg(self, t):
        # The gradient runs --public-hero-bg -> --public-hero-bg-deep; the
        # lighter stop is the worst case for white text.
        return as_rgb("var(--public-hero-bg)", t)

    def test_placeholder_text_in_the_hero(self, t, hero_bg):
        body = rule(".hero .slot,\n.dark .slot")
        fg_v = re.search(r"(?<![\w-])color\s*:\s*([^;]+)", body).group(1)
        bg_v = re.search(r"background\s*:\s*([^;]+)", body).group(1)
        bg = as_rgb(bg_v, t, over=hero_bg)
        fg = as_rgb(fg_v, t, over=bg)
        r = ratio(fg, bg)
        assert r >= BODY_MIN, f"placeholder text in the hero is {r:.2f}:1"

    def test_no_hero_text_sits_on_a_light_fill(self, t, hero_bg):
        """Acceptance: nothing in the hero on a background lighter than #767676."""
        limit = _lum(_hex("#767676"))
        body = rule(".hero .slot,\n.dark .slot")
        bg_v = re.search(r"background\s*:\s*([^;]+)", body).group(1)
        bg = as_rgb(bg_v, t, over=hero_bg)
        assert _lum(bg) <= limit, (
            f"hero placeholder fill {bg} is lighter than #767676"
        )

    def test_counter_values_have_no_fill_at_all(self, t):
        """Spec §6 S1: white on the navy card, no fill behind the number."""
        body = rule(".counter .slot")
        bg = re.search(r"background\s*:\s*([^;]+)", body).group(1).strip()
        assert bg in {"none", "transparent"}, (
            f"counter placeholder still paints a fill ({bg}); the spec calls "
            f"for white on navy with nothing behind the digits"
        )

    def test_standfirst_and_captions_are_legible(self, t, hero_bg):
        for sel, prop, min_r in (
            (".hero-standfirst", "color", BODY_MIN),
            (".counter-n", "color", LARGE_MIN),
            (".counter-l", "color", BODY_MIN),
        ):
            fg = as_rgb(decl(sel, prop), t, over=hero_bg)
            r = ratio(fg, hero_bg)
            assert r >= min_r, f"{sel} is {r:.2f}:1 on the hero"


@pytest.mark.django_db
class TestBothRenderedStates:
    """The bug only appeared with placeholders, so exercise both."""

    @pytest.fixture
    def public(self, settings):
        settings.ROOT_URLCONF = "nsr_mis.urls_public"
        settings.ALLOWED_HOSTS = ["*"]
        return settings

    @staticmethod
    def _hero(html):
        """The rendered hero markup.

        Slice from the <section>, not from the first 'S2' match: the CSS
        comments name the sections too and sit above the markup.
        """
        start = html.index('<section class="hero">')
        end = html.index("<!-- ============ S2", start)
        hero = html[start:end]
        assert "hero-standfirst" in hero, "sliced the wrong region"
        return hero

    def test_placeholder_state_renders_slots_in_the_hero(self, public, client):
        public.NSR_PUBLIC_STATS_LIVE = False
        hero = self._hero(client.get("/").content.decode())
        assert 'class="slot"' in hero
        assert "counter-n slot" in hero, "counters should be marked unfilled"

    def test_live_state_puts_real_digits_in_the_counters(self, public, client):
        public.NSR_PUBLIC_STATS_LIVE = True
        hero = self._hero(client.get("/").content.decode())
        assert "counter-n slot" not in hero, (
            "live counters must not wear the placeholder marker"
        )
