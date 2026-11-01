"""Assemble self-contained themed HTML (pages/dashboards and motion decks).

Everything (CSS, JS, fonts, logo) is inlined so each file works offline with
no external requests. Colors and fonts come from a theme folder
(scripts/theme.py): every public builder takes ``theme=``, a bare theme name
resolved under themes/ or a path to a theme folder (default "neutral").

Page / dashboard:
    from render_lib import page, page_header, page_footer
    body = page_header("Pipeline · Q4 2026", "Partner Dashboard", "Weekly view of ...") + "<main>...</main>" \
         + page_footer(title="Partner Dashboard", section="Weekly view")
    html = page("Partner Dashboard", body, theme="neutral")

Motion deck:
    from render_lib import deck, cover_slide, slide_head, slide_foot
    slides = [cover_slide("Eyebrow", "Title", "Subtitle", "Meta line", "Footer note"),
              f'<section class="slide" data-notes="Note 1|Note 2"><div class="slide-body">{slide_head("Eyebrow","Title")}<main class="slide-main">...</main>{slide_foot("Deck name","Section",2)}</div></section>']
    html = deck("Deck title", slides)

Logo slots resolve from the theme first (its logo file, else its brand_name
text, else nothing); explicit logo_data_uri / brand_name arguments win over
the theme. Footers render the theme's footer label template
(footer.label, with {title} and {section}) whenever no literal label is
passed. A theme with "motif": {"enabled": false} renders no motif grid.
"""
import argparse, os, html as _h
from motif import motif
from theme import load_theme, css_vars, font_css, footer_label, motif_settings
from theme import logo_data_uri as _theme_logo_uri

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "..", "assets", "render")
def _read(*p): return open(os.path.join(ASSETS, *p), encoding="utf-8").read()
def esc(s): return _h.escape(str(s), quote=True)

_themes = {}
def _theme(name="neutral"):
    if name not in _themes:
        _themes[name] = load_theme(name)
    return _themes[name]

def _mark(theme_obj, logo_data_uri=None, brand_name=None, **cls):
    """Brand slot: explicit arguments win, else the theme's logo / brand_name."""
    return logo_img(logo_data_uri or _theme_logo_uri(theme_obj),
                    brand_name or theme_obj.get("brand_name"), **cls)

def _motif(theme_obj):
    """(settings, kwargs-for-motif) from the theme's motif block."""
    m = motif_settings(theme_obj)
    return m, dict(line=m["line"], tints_a=m["tints_a"], tints_b=m["tints_b"], tint_a_share=m["ratio"])

def logo_img(logo_data_uri=None, brand_name=None, cls="rf-logo", text_cls="rf-brand-name"):
    """Optional brand slot: embedded logo image, or brand-name text, or nothing."""
    if logo_data_uri:
        alt = esc(brand_name or "Logo")
        return f'<img class="{esc(cls)}" src="{esc(logo_data_uri)}" alt="{alt}">'
    if brand_name:
        return f'<span class="{esc(text_cls)}">{esc(brand_name)}</span>'
    return ""

# ---------- pages / dashboards ----------
def page_header(eyebrow, title, sub=None, meta=None, motif_art=True, seed=11, cell=13,
                logo_data_uri=None, brand_name=None, theme="neutral"):
    """Brand slot + text in the left cell; motif grid in its own right cell (never behind text).
    meta: optional small line under the subtitle (dates, confidentiality label from the source).
    cell: dot cell radius in the 480x200 art box. Approved page-header look = small, dense cells (13).
    theme: motif colors/tints and the logo slot come from it; motif.enabled false renders no art."""
    t = _theme(theme)
    art = ""
    m, mk = _motif(t)
    if motif_art and m["enabled"]:
        art = '<div class="rf-header-art" aria-hidden="true">' + motif(480, 200, corner="top-right", keepouts=[], edge=0.62, r=cell, seed=seed, **mk) + "</div>"
    s = f'<p class="rf-sub">{esc(sub)}</p>' if sub else ""
    m_line = f'<p class="rf-meta">{esc(meta)}</p>' if meta else ""
    return (f'<header class="rf-header"><div class="rf-header-text">{_mark(t, logo_data_uri, brand_name)}'
            f'<p class="rf-eyebrow">{esc(eyebrow)}</p><h1>{esc(title)}</h1>{s}{m_line}</div>{art}</header>')

def page_footer(label=None, right="", logo_data_uri=None, brand_name=None, theme="neutral",
                title="", section=""):
    """Footer rule: brand mark far left when one is supplied, then label; page/number alone far right.
    label: literal footer text; when None (default) the theme's footer.label template is
    formatted with title/section."""
    t = _theme(theme)
    if label is None:
        label = footer_label(t, title, section)
    mark = _mark(t, logo_data_uri, brand_name)
    cls = "rf-footer-left has-mark" if mark else "rf-footer-left"
    return (f'<footer class="rf-footer"><span class="{cls}">{mark}<span>{esc(label)}</span></span>'
            f'<span class="rf-footer-right">{esc(right)}</span></footer>')

def page(title, body, extra_css="", theme="neutral"):
    """Build a page from trusted builder-produced HTML and CSS fragments.

    ``body`` and ``extra_css`` are intentionally raw composition inputs because
    the page builder accepts arbitrary approved components. Never pass
    untrusted content through them; escape dynamic text before composing
    those fragments. The document head carries the theme's token block and
    embedded font CSS ahead of the layout stylesheet.
    """
    t = _theme(theme)
    css = css_vars(t) + "\n" + font_css(t) + "\n" + _read("page.css") + "\n" + extra_css
    return (f'<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1.0">'
            f'<title>{esc(title)}</title><style>{css}</style></head><body><div class="rf-page">{body}</div></body></html>')

# ---------- motion decks ----------
def slide_head(eyebrow, title, sub=None, theme="neutral"):
    """Slide header; theme is accepted for builder uniformity (no themed parts here)."""
    s = f'<p class="sub" data-a style="--d:2">{esc(sub)}</p>' if sub else ""
    return (f'<header class="slide-head"><p class="eyebrow" data-a style="--d:0">{esc(eyebrow)}</p>'
            f'<h2 data-a style="--d:1">{esc(title)}</h2>{s}</header>')

def slide_foot(deck_name, section, n, label=None, logo_data_uri=None, brand_name=None, theme="neutral"):
    """Footer rule: brand mark far left when one is supplied, page number alone far right.
    The footer text is the theme's footer.label template formatted with the deck name and
    section; a literal label, when passed, is kept as a prefix."""
    t = _theme(theme)
    mark = _mark(t, logo_data_uri, brand_name, cls="foot-logo", text_cls="foot-text brand-name")
    text = footer_label(t, deck_name, section)
    if label:
        text = f"{label} — {text}"
    cls = "foot-left has-mark" if mark else "foot-left"
    return (f'<footer class="slide-foot"><span class="{cls}">{mark}'
            f'<span class="foot-text">{esc(text)}</span></span>'
            f'<span class="foot-right"><span class="pgnum">{n:02d}</span></span></footer>')

def cover_slide(eyebrow, title, sub, meta, foot_note="", seed=11, notes="",
                logo_data_uri=None, brand_name=None, theme="neutral"):
    """Cover slide with the theme's motif (none when motif.enabled is false)."""
    t = _theme(theme)
    mark = _mark(t, logo_data_uri, brand_name, cls="cover-logo", text_cls="cover-brand")
    head = f'<header class="slide-head" data-a="fade" style="--d:0">{mark}</header>' if mark else ""
    m, mk = _motif(t)
    art = motif(seed=seed, **mk) if m["enabled"] else ""
    return (f'<section class="slide cover" data-notes="{esc(notes)}">{art}'
            f'<div class="slide-body">{head}'
            f'<main class="slide-main cover-main"><p class="eyebrow" data-a style="--d:1">{esc(eyebrow)}</p>'
            f'<h1 data-a style="--d:2">{esc(title)}</h1><p class="cover-sub" data-a style="--d:4">{esc(sub)}</p>'
            f'<p class="cover-meta" data-a style="--d:5">{esc(meta)}</p></main>'
            f'<footer class="slide-foot cover-foot"><span class="foot-text">{esc(foot_note)}</span><span class="foot-right"></span></footer>'
            f'</div></section>')

def deck(title, slides, extra_css="", research=True, theme="neutral"):
    """Build a deck from trusted builder-produced slide and CSS fragments.

    ``slides`` and ``extra_css`` are raw composition inputs for approved
    layouts. Escape all dynamic text before putting them in those fragments.
    The document head carries the theme's token block and embedded font CSS
    ahead of the layout stylesheets.
    """
    t = _theme(theme)
    css = css_vars(t) + "\n" + font_css(t) + "\n" + _read("deck.css") + ("\n" + _read("research.css") if research else "") + "\n" + extra_css
    js = _read("deck.js")
    return f'''<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(title)}</title>
<style>{css}</style></head>
<body>
<div class="deck-viewport">
<div class="deck-stage"><div class="deck"><div class="deck-track">
{"".join(slides)}
</div></div></div>
<footer class="media-bar">
<div class="notes" id="notes" hidden><ul id="notes-list"></ul></div>
<nav class="controls" aria-label="Slide controls">
<button id="prev" type="button" aria-label="Previous slide">←</button>
<span id="counter" aria-live="polite"></span>
<button id="next" type="button" aria-label="Next slide">→</button>
<span class="spacer"></span>
<button id="replay" type="button">Replay build</button>
<button id="notes-toggle" type="button" aria-expanded="false">Notes</button>
<button id="fullscreen" type="button">Fullscreen</button>
</nav>
</footer>
</div>
<script>{js}</script>
</body></html>'''

# ---------- demo (sample data) ----------
def demo_page(theme="neutral"):
    body = page_header(
        "Research fork · Sample data",
        "Sample Research Dashboard",
        "A demonstration of the adopted page engine: header motif, KPI cards, a table, and a footer.",
        meta="Generated 2026-11-01 · Sample data",
        motif_art=True, seed=7, theme=theme,
    )
    body += (
        '<section class="rf-kpis">'
        '<div class="rf-kpi"><span class="rf-kpi-label">Sources reviewed</span><span class="rf-kpi-num">128</span>'
        '<span class="rf-kpi-delta">▲ 12 vs. prior run</span><span class="rf-kpi-note">Sample window Oct 2026</span></div>'
        '<div class="rf-kpi"><span class="rf-kpi-label">Claims extracted</span><span class="rf-kpi-num">342</span>'
        '<span class="rf-kpi-delta">▲ 9% vs. prior run</span><span class="rf-kpi-note">Sample data</span></div>'
        '<div class="rf-kpi"><span class="rf-kpi-label">Undated claims</span><span class="rf-kpi-num">18%</span>'
        '<span class="rf-kpi-delta down">▼ 4 pts vs. prior run</span><span class="rf-kpi-note">Sample data</span></div>'
        '<div class="rf-kpi"><span class="rf-kpi-label">Contested facets</span><span class="rf-kpi-num">7</span>'
        '<span class="rf-kpi-note">Flagged for the debate section</span></div>'
        '</section>'
    )
    body += (
        '<section class="rf-grid"><div class="rf-card rf-span-12">'
        '<div class="rf-card-head"><h3>Sample source table</h3><span class="rf-fine">Sample data</span></div>'
        '<table class="rf-table"><thead><tr><th>Source</th><th>Publisher</th><th class="num">Claims</th>'
        '<th class="num">Confidence</th><th>Status</th></tr></thead><tbody>'
        '<tr><td>Sampling atlas, 4th ed.</td><td>Statprobe Sampling Group</td><td class="num">64</td>'
        '<td class="num">High</td><td><span class="rf-pill">Verified</span></td></tr>'
        '<tr><td>Quarterly methods digest</td><td>Ridgeline Analytics</td><td class="num">48</td>'
        '<td class="num">High</td><td><span class="rf-pill">Verified</span></td></tr>'
        '<tr><td>Field notes on claim dating</td><td>Meridian Review</td><td class="num">31</td>'
        '<td class="num">Medium</td><td><span class="rf-pill neutral">Partly verified</span></td></tr>'
        '<tr><td>Working paper on facets</td><td>Northline Institute</td><td class="num">12</td>'
        '<td class="num">Low</td><td><span class="rf-pill neutral">Contested</span></td></tr>'
        '</tbody></table></div></section>'
    )
    body += page_footer(right="Generated 2026-11-01", theme=theme,
                        title="Sample Research Dashboard", section="Sample data")
    return page("Sample Research Dashboard — Sample data", body, theme=theme)

def demo_deck(theme="neutral"):
    slides = [
        cover_slide(
            "Research fork · Sample data",
            "Sample findings review",
            "A demonstration of the adopted deck engine: cover motif, statement, finding, three values, sources.",
            "Sample data · Generated 2026-11-01",
            foot_note="Sample data — no real claims",
            seed=5,
            notes="Cover slide|All content on this deck is sample data",
            theme=theme,
        ),
        ('<section class="slide"><div class="slide-body">'
         + slide_head("Statement · Sample data", "What the sample shows", theme=theme)
         + '<main class="slide-main">'
         '<h2 class="statement-title" data-a style="--d:0">Three in four sampled pipelines <em>ship undated claims</em> downstream</h2>'
         '<p class="sub" data-a style="--d:1">Statement slide with three stat tiles beneath it — sample data.</p>'
         '<div class="stat-tiles">'
         '<article class="stat-tile" data-a style="--d:2"><p class="stat-num">76<small>%</small></p>'
         '<p class="stat-txt">of sampled reports carried at least one undated quantitative claim (sample data)</p></article>'
         '<article class="stat-tile" data-a style="--d:3"><p class="stat-num">2.4<small>×</small></p>'
         '<p class="stat-txt">more claims per source once dates are required at intake (sample data)</p></article>'
         '<article class="stat-tile" data-a style="--d:4"><p class="stat-num">18<small>%</small></p>'
         '<p class="stat-txt">of sample claims still reach the debate section without a date (sample data)</p></article>'
         '</div></main>'
         + slide_foot("Sample findings review", "Statement", 2, label="Sample data", theme=theme)
         + '</div></section>'),
        ('<section class="slide finding"><div class="slide-body">'
         + slide_head("Finding 01 · Sample data", "Ranked bars carry the comparison", theme=theme)
         + '<main class="slide-main">'
         '<div class="barriers">'
         '<div class="brow top"><span class="bname">Missing intake date</span>'
         '<span class="btrack"><span class="bfill" style="--w:64%;--d:0"></span></span><span class="bval">64%</span></div>'
         '<div class="brow"><span class="bname">No publisher listed</span>'
         '<span class="btrack"><span class="bfill" style="--w:41%;--d:1"></span></span><span class="bval">41%</span></div>'
         '<div class="brow"><span class="bname">Unsupported precision</span>'
         '<span class="btrack"><span class="bfill" style="--w:33%;--d:2"></span></span><span class="bval">33%</span></div>'
         '<div class="brow last"><span class="bname">Orphaned citation marker</span>'
         '<span class="btrack"><span class="bfill" style="--w:22%;--d:3"></span></span><span class="bval">22%</span></div>'
         '<p class="chart-note">Sample data — share of 128 sampled sources with each defect.</p>'
         '</div>'
         '<aside class="side">'
         '<div class="say" data-a style="--d:2"><p class="say-label">How to say it</p>'
         '<p class="say-text">Dates at intake cut undated claims before they spread through the report.</p>'
         '<p class="say-caveat"><strong>Caveat:</strong> sample data only; no real sources were reviewed.</p></div>'
         '<div class="mini" data-a style="--d:3"><span class="mini-num">2.4×</span>'
         '<p class="mini-txt">more claims per source once dates are required (sample data)</p></div>'
         '</aside></main>'
         + slide_foot("Sample findings review", "Finding", 3, label="Sample data", theme=theme)
         + '</div></section>'),
        ('<section class="slide layout-three"><div class="slide-body">'
         + slide_head("Why it matters · Sample data", "Three values the engine protects", theme=theme)
         + '<main class="slide-main"><div class="value-grid">'
         '<article class="value-col" data-a style="--d:2"><span class="value-line"></span><span class="value-num">01</span>'
         '<h3>Self-contained</h3><p>Every byte is inlined, so output opens offline with no external requests.</p></article>'
         '<article class="value-col" data-a style="--d:3"><span class="value-line"></span><span class="value-num">02</span>'
         '<h3>Theme-driven</h3><p>Colors, fonts, logo, and motif come from one theme folder.</p></article>'
         '<article class="value-col" data-a style="--d:4"><span class="value-line"></span><span class="value-num">03</span>'
         '<h3>Motion-safe</h3><p>Animation is opt-out through reduced-motion and print styles everywhere.</p></article>'
         '</div><p class="fine">Sample data — illustrative values.</p></main>'
         + slide_foot("Sample findings review", "Values", 4, label="Sample data", theme=theme)
         + '</div></section>'),
        ('<section class="slide"><div class="slide-body">'
         + slide_head("Sources · Sample data", "Sources behind the samples", theme=theme)
         + '<main class="slide-main"><dl class="facts">'
         '<div class="fact" data-a style="--d:0"><dt>[1] Sampling atlas, 4th ed.</dt><dd>Statprobe Sampling Group, 2026 — illustrative entry, sample data.</dd></div>'
         '<div class="fact" data-a style="--d:1"><dt>[2] Quarterly methods digest</dt><dd>Ridgeline Analytics, 2026 — illustrative entry, sample data.</dd></div>'
         '<div class="fact" data-a style="--d:2"><dt>[3] Field notes on claim dating</dt><dd>Meridian Review, 2026 — illustrative entry, sample data.</dd></div>'
         '<div class="fact" data-a style="--d:3"><dt>[4] Working paper on facets</dt><dd>Northline Institute, 2026 — illustrative entry, sample data.</dd></div>'
         '</dl></main>'
         + slide_foot("Sample findings review", "Sources", 5, label="Sample data", theme=theme)
         + '</div></section>'),
    ]
    return deck("Sample findings review — Sample data", slides, theme=theme)

def _cli():
    ap = argparse.ArgumentParser(description="Render the unjangled-research engine demo (sample data).")
    ap.add_argument("--demo", metavar="DIR", help="write demo-page.html and demo-deck.html into DIR")
    ap.add_argument("--theme", default="neutral", metavar="NAME_OR_PATH",
                    help="theme name under themes/ or a theme folder path (default: neutral)")
    args = ap.parse_args()
    if not args.demo:
        ap.error("--demo DIR is required")
    os.makedirs(args.demo, exist_ok=True)
    page_path = os.path.join(args.demo, "demo-page.html")
    deck_path = os.path.join(args.demo, "demo-deck.html")
    with open(page_path, "w", encoding="utf-8") as f:
        f.write(demo_page(args.theme))
    with open(deck_path, "w", encoding="utf-8") as f:
        f.write(demo_deck(args.theme))
    print(f"wrote {page_path}")
    print(f"wrote {deck_path}")

if __name__ == "__main__":
    _cli()
