"""Decorative dot-grid motif generator (soft tints from the theme's motif block).

Rules enforced here (carried over from the adopted engine):
  * Light grid rings, mostly surface dots, soft tints only (ratio shares tint A vs B).
  * The grid trails in on a gradual diagonal from one corner, tinted to its leading edge.
  * NO TEXT MAY OVERLAP THE GRID. Pass every text block as a keep-out rectangle;
    any dot whose ring would touch a keep-out (plus gutter) is dropped.

Colors are parameters: render_lib feeds them from the theme's ``motif`` block
(``line``, ``tints_a``, ``tints_b``, ``ratio``); the defaults below are the
neutral palette, kept so the module still self-tests standalone.

Fills are inline styles, so the SVG renders correctly in any HTML page without extra CSS.
Each dot carries class="hx" and --hd (0-20) so the deck CSS can animate it in.

Usage:
    from motif import motif, COVER_KEEPOUTS
    svg = motif()                                   # 1280x720 deck cover, bottom-right
    svg = motif(480, 200, corner="top-right",       # page header art cell (no text inside it)
                keepouts=[], edge=0.62, r=26)
CLI self-test:  python3 motif.py
"""
import math, random

DEFAULT_LINE = "#E0E0E0"
DEFAULT_TINT_A = ["#EEF2FF", "#EEF2FF", "#EEF2FF", "#E0E7FF", "#E0E7FF", "#E0E7FF", "#C7D2FE", "#C7D2FE"]  # indigo family
DEFAULT_TINT_B = ["#F8FAFC", "#F8FAFC", "#E2E8F0", "#E2E8F0", "#F1F5F9", "#CBD5E1"]                          # slate family

# Deck cover keep-outs in the 1280x720 slide coordinate space (cover CSS: body inset 8cqw, text column
# max 46cqw => text spans x 102..691; the gutter below adds the visible gap).
COVER_KEEPOUTS = [
    (0, 0, 700, 580),     # eyebrow, title (<=3 lines), subtitle, meta line
    (0, 650, 480, 720),   # cover footer text row
]

# Dot geometry: staggered circle grid. ``r`` is the cell radius; the visible ring
# and the tinted inner dot are fractions of it.
_RING = 0.66   # outer ring radius / r
_DOT = 0.42    # inner tint dot radius / r
_DX = 1.75     # column spacing / r
_DY = 1.6      # row spacing / r

def _hits(cx, cy, rad, rects, gutter):
    x0, x1, y0, y1 = cx - rad, cx + rad, cy - rad, cy + rad
    for (a, b, c, d) in rects:
        if x1 > a - gutter and x0 < c + gutter and y1 > b - gutter and y0 < d + gutter:
            return True
    return False

def _fit_edge(width, height, corner, keepouts, gutter, r, slope, start):
    """Smallest diagonal threshold whose grid clears every keep-out (keeps a clean diagonal edge)."""
    e = start
    ring = r * _RING
    while e < 3:
        ok = True
        col, x, dx, dy = 0, -r, _DX * r, _DY * r
        while ok and x < width + 2 * r:
            y = (dy / 2 if col % 2 else 0) - dy
            while y < height + dy:
                if _score(x, y, width, height, corner, slope) > e and _hits(x, y, ring, keepouts, gutter):
                    ok = False; break
                y += dy
            x += dx; col += 1
        if ok: return e
        e += 0.01
    return e

def _score(x, y, width, height, corner, slope):
    u, v = x / width, y / height
    if "left" in corner: u = 1 - u
    if "top" in corner: v = 1 - v
    return u + v * slope

def motif(width=1280, height=720, *, corner="bottom-right", keepouts=None, gutter=40, edge=None,
          slope=0.33, r=31.0, seed=11, tint_a_share=0.65, css_class="motif", return_stats=False,
          line=DEFAULT_LINE, tints_a=None, tints_b=None):
    """Return an aria-hidden <svg> dot grid sized width x height (viewBox units = px).

    corner: where the grid anchors - bottom-right | top-right | bottom-left | top-left.
    keepouts: list of (x0, y0, x1, y1) text rectangles in the same px space. Defaults to the deck
              cover layout when width x height is 1280x720, else no keep-outs (then place the SVG
              in its own element that holds no text).
    edge: diagonal threshold (higher = smaller grid). Default None = auto-fit: the whole diagonal
          is pushed back until it clears every keep-out + gutter, so the edge stays a gradual diagonal
          (never a vertical cutoff) and no dot is ever dropped mid-pattern.
    slope: how far the leading edge travels across per slide height (0.33 puts ~80% across at the
           top and ~45% at the bottom).
    line / tints_a / tints_b / tint_a_share: colors and tint mix from the theme's motif block.
    """
    if tints_a is None: tints_a = DEFAULT_TINT_A
    if tints_b is None: tints_b = DEFAULT_TINT_B
    if keepouts is None:
        keepouts = COVER_KEEPOUTS if (width, height) == (1280, 720) else []
    if edge is None:
        edge = _fit_edge(width, height, corner, keepouts, gutter, r, slope, 0.3)
    rnd = random.Random(seed)
    ring, dot = r * _RING, r * _DOT
    dx, dy = _DX * r, _DY * r
    out, cells, filled, a_n = [], 0, 0, 0
    col, x = 0, -r
    while x < width + 2 * r:
        y = (dy / 2 if col % 2 else 0) - dy
        while y < height + dy:
            score = _score(x, y, width, height, corner, slope)
            if score > edge and not _hits(x, y, ring, keepouts, gutter):
                p = min(.55, .34 + (score - edge) * 1.4)   # tints reach all the way to the leading edge
                d = int(min(1, (score - edge) / 0.5) * 14) + rnd.randint(0, 6)
                out.append(f'<circle class="hx hx-o" style="fill:var(--rf-surface);stroke:{line};stroke-width:1.5;--hd:{d}" '
                           f'cx="{x:.1f}" cy="{y:.1f}" r="{ring:.1f}"/>')
                cells += 1
                if rnd.random() < p:
                    is_a = rnd.random() < tint_a_share
                    fill = rnd.choice(tints_a if is_a else tints_b)
                    a_n += is_a; filled += 1
                    out.append(f'<circle class="hx hx-fill" style="fill:{fill};stroke:none;--hd:{d}" '
                               f'cx="{x:.1f}" cy="{y:.1f}" r="{dot:.1f}"/>')
            y += dy
        x += dx; col += 1
    svg = (f'<svg class="{css_class}" aria-hidden="true" '
           f'viewBox="0 0 {width} {height}" preserveAspectRatio="xMidYMid slice">' + "".join(out) + "</svg>")
    if return_stats:
        return svg, {"cells": cells, "filled": filled, "edge": round(edge, 2), "tint_a_share": round(a_n / filled, 2) if filled else 0}
    return svg

if __name__ == "__main__":
    import re
    svg, st = motif(return_stats=True)
    # verify no outer ring touches a keep-out
    bad = 0
    for m in re.finditer(r'hx-o" style="[^"]*" cx="([-\d.]+)" cy="([-\d.]+)" r="([\d.]+)"', svg):
        cx, cy, rad = float(m.group(1)), float(m.group(2)), float(m.group(3))
        for (a, b, c, d) in COVER_KEEPOUTS:
            if cx + rad > a and cx - rad < c and cy + rad > b and cy - rad < d: bad += 1
    assert "<polygon" not in svg, "hexagon cells must not return"
    approved = set(DEFAULT_TINT_A + DEFAULT_TINT_B + [DEFAULT_LINE, "#FFFFFF"])
    colors = set(re.findall(r"#[0-9A-Fa-f]{6}", svg))
    print("cover:", st, "| dots touching text zones:", bad, "| off-palette:", colors - approved)
    band, st2 = motif(480, 200, corner="top-right", keepouts=[], edge=0.62, r=26, return_stats=True,
                      line="#DDE7DD", tints_a=["#E9F4EC", "#D2E7D8"], tints_b=["#F2F4F1"], tint_a_share=0.5)
    assert "#DDE7DD" in band and "#E9F4EC" in band, "theme colors must flow into the motif"
    print("header band:", st2)
