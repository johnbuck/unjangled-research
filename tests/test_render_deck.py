"""Deck renderer (E3-R1): every format fixture and valid_report.md render
under neutral and the alt theme with the required slide sequence — cover
first, sources last, at most 12 content slides, stat-tile values verbatim
from the report, data-notes on every slide, no empty slide-main anywhere,
and check_theme.py exiting 0 on each output. Synthetic models prove the
12-slide cap's omitted-count note, contested-facet slides, and the
no-sides facet fallback that condenses the matched subsection."""
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

from build_render_model import build_model  # noqa: E402
from render_deck import CONTENT_SLIDE_CAP, render_deck  # noqa: E402

FORMATS_DIR = os.path.join(HERE, "fixtures", "formats")
RENDER_DIR = os.path.join(HERE, "fixtures", "render")
THEMES = ["neutral", os.path.join(HERE, "fixtures", "themes", "alt")]
REPORT_PATHS = sorted(
    os.path.join(FORMATS_DIR, f) for f in os.listdir(FORMATS_DIR) if f.endswith(".md")
) + [os.path.join(HERE, "fixtures", "valid_report.md")]

OPEN_TAG_RE = re.compile(r'<section class="slide[^"]*"[^>]*>')
STAT_NUM_RE = re.compile(r'<p class="stat-num">(.*?)</p>', re.S)
STAT_SMALL_RE = re.compile(r"<small>(.*?)</small>", re.S)
SLIDE_MAIN_RE = re.compile(r'<main class="slide-main[^"]*"[^>]*>(.*?)</main>', re.S)


def slides_of(html):
    """Each slide's HTML chunk, cover included."""
    opens = list(OPEN_TAG_RE.finditer(html))
    assert opens, "no slides rendered"
    return [html[m.start():opens[i + 1].start() if i + 1 < len(opens) else len(html)]
            for i, m in enumerate(opens)]


def stat_values(html):
    """Stat-tile values rebuilt as num + unit suffix (verbatim model values)."""
    values = []
    for m in STAT_NUM_RE.finditer(html):
        inner = m.group(1)
        small = STAT_SMALL_RE.search(inner)
        if small:
            values.append(re.sub(r"\s+", " ",
                                 inner[:small.start()].strip() + " " + small.group(1).strip()))
        else:
            values.append(re.sub(r"\s+", " ", inner.strip()))
    return values


def run_check_theme(path, theme):
    r = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, "check_theme.py"), path, "--theme", theme],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, (path, theme, r.stdout, r.stderr)
    return r.stdout


def check_deck_shape(slides, where):
    assert 'class="slide cover"' in slides[0], ("first slide is not the cover", where)
    assert re.search(r'class="slide[^"]*\bsources', slides[-1]), ("last slide is not sources", where)
    content = len(slides) - 2
    assert 0 <= content <= CONTENT_SLIDE_CAP, ("content slide cap exceeded", where, content)
    for s in slides:
        assert re.search(r'<section class="slide[^"]*"[^>]*\bdata-notes="', s), \
            ("slide without data-notes", where)
        m = SLIDE_MAIN_RE.search(s)
        assert m and m.group(1).strip(), ("slide with empty slide-main", where)


def test_fixture_decks_both_themes():
    for path in REPORT_PATHS:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        model = build_model(text)
        with tempfile.TemporaryDirectory() as d:
            for theme in THEMES:
                html = render_deck(model, theme=theme)
                slides = slides_of(html)
                check_deck_shape(slides, (path, theme))
                expected = [re.sub(r"\s+", " ", str(s["value"])).strip()
                            for s in model["key_stats"][:3]]
                assert stat_values(html) == expected, (path, theme)
                for value in stat_values(html):
                    assert value in text, ("stat value not verbatim in report", path, value)
                out = os.path.join(d, f"deck-{os.path.basename(path)}-{os.path.basename(theme)}.html")
                with open(out, "w", encoding="utf-8") as f:
                    f.write(html)
                run_check_theme(out, theme)


def test_section_fallback_when_no_findings():
    """comparison.md has no extractable findings, so the deck falls back to
    one slide per top-level section."""
    path = os.path.join(FORMATS_DIR, "comparison.md")
    with open(path, encoding="utf-8") as f:
        model = build_model(f.read())
    assert model["findings"] == [], model["findings"]
    html = render_deck(model)
    assert "Finding 01" not in html
    assert "Section 01" in html
    top_level = [s for s in model["sections"] if s["level"] == 2]
    assert html.count('class="slide" data-notes') == 1 + len(top_level), top_level


def _synthetic_model(findings=(), facets=()):
    return {
        "title": "Synthetic model",
        "subtitle": None,
        "date": "2026-11-01",
        "format": "research-summary",
        "executive_summary": ["One synthetic summary sentence. A second sentence follows."],
        "key_stats": [{"value": "42 things", "label": "of synthetic cases", "ref": 1}],
        "sections": [{"heading": "Main Analysis", "level": 2,
                      "html": '<h2 class="section-title">Main Analysis</h2><p>Text.</p>'}],
        "findings": list(findings),
        "contested_facets": list(facets),
        "sources": [{"n": n, "title": f"Source {n}", "url": None, "publisher": "Publisher"}
                    for n in range(1, 3)],
    }


def test_cap_and_omitted_note():
    findings = [{"headline": f"Synthetic finding {i}", "refs": [1],
                 "body": f"Body sentence for finding {i}. " * 3} for i in range(1, 21)]
    model = _synthetic_model(findings=findings)
    assert len(model["findings"]) == 20
    with tempfile.TemporaryDirectory() as d:
        model_path = os.path.join(d, "model.json")
        with open(model_path, "w", encoding="utf-8") as f:
            json.dump(model, f)
        out = os.path.join(d, "deck.html")
        r = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "render_deck.py"),
             "--model", model_path, "--out", out],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, r.stderr
        with open(out, encoding="utf-8") as f:
            html = f.read()
    slides = slides_of(html)
    check_deck_shape(slides, "cap model")
    assert len(slides) == 1 + CONTENT_SLIDE_CAP + 1, len(slides)
    assert "Synthetic finding 11" in html          # statement + findings 1-11 fill the cap
    assert "Synthetic finding 12" not in html
    last_kept = slides[CONTENT_SLIDE_CAP]           # slides[0] is the cover
    assert "Deck capped at 12 content slides" in last_kept, last_kept[:400]
    assert re.search(r"Deck capped at 12 content slides; 9 later", last_kept), last_kept[:400]


def test_contested_facet_slides():
    facets = [{"facet": "Effect size of the intervention",
               "sides": [{"label": "Camp for harm", "summary": "Harm summary [1]."},
                         {"label": "Camp for null", "summary": "Null summary [2]."}]},
              {"facet": "Measurement validity",
               "sides": [{"label": "Side A", "summary": "A [1]."},
                         {"label": "Side B", "summary": "B [2]."},
                         {"label": "Side C", "summary": "C [3]."}]}]
    html = render_deck(_synthetic_model(facets=facets))
    slides = slides_of(html)
    check_deck_shape(slides, "facet model")
    assert html.count('class="facet-grid ') == 2
    assert 'facet-grid cols-2"' in html and 'facet-grid cols-3"' in html
    for label in ("Camp for harm", "Camp for null", "Side C"):
        assert label in html, label
    facet_slide = next(s for s in slides if "facet-grid" in s)
    assert "Effect size of the intervention" in facet_slide
    assert re.search(r'<section class="slide[^"]*"[^>]*\bdata-notes="', facet_slide)


def test_facet_fixture_deck_preserves_subsection():
    """Regression (story 3.2 review): the manifest facet 'Alpha vs. beta:'
    pairs with the '### Alpha versus beta' subsection; the deck's facet
    slide shows both camps and its notes carry the subsection text."""
    with open(os.path.join(RENDER_DIR, "facet_match_manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    with open(os.path.join(RENDER_DIR, "facet_match_report.md"), encoding="utf-8") as f:
        model = build_model(f.read(), manifest)
    facet = model["contested_facets"][0]
    assert len(facet["sides"]) >= 2 and facet["html"], facet
    html = render_deck(model)
    slides = slides_of(html)
    check_deck_shape(slides, "facet fixture deck")
    facet_slide = next(s for s in slides if "facet-grid" in s)
    for side in facet["sides"]:
        assert side["label"] in facet_slide, side
    assert "heavier alpha exposure tracks more beta problems" in facet_slide, \
        "subsection text missing from facet-slide notes"


def test_facet_slide_without_sides_condenses_subsection_html():
    """A facet with no extracted sides renders up to three bullets from the
    matched subsection's text; the slide-main is never empty and the notes
    carry the full subsection text."""
    facets = [{"facet": "Effect size of the intervention", "sides": [],
               "html": '<h3 class="subsection-title">Effect size</h3>'
                       "<p>First claim sentence one. Second claim sentence two. "
                       "Third claim sentence three. Fourth claim lives only in notes [1].</p>"}]
    html = render_deck(_synthetic_model(facets=facets))
    slides = slides_of(html)
    check_deck_shape(slides, "facet no-sides model")
    facet_slide = next(s for s in slides if "Contested facet" in s and "facet-grid" not in s)
    assert '<ul class="ticks">' in facet_slide
    assert "First claim sentence one." in facet_slide
    assert "Fourth claim lives only in notes" not in re.search(
        r'<main class="slide-main[^"]*"[^>]*>(.*?)</main>', facet_slide, re.S).group(1)
    assert "Fourth claim lives only in notes" in facet_slide  # data-notes carry it


def test_cli_report_path_alt_theme():
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "deck.html")
        r = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "render_deck.py"),
             "--report", os.path.join(HERE, "fixtures", "valid_report.md"),
             "--theme", THEMES[1], "--out", out],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, r.stderr
        run_check_theme(out, THEMES[1])
        with open(out, encoding="utf-8") as f:
            html = f.read()
    check_deck_shape(slides_of(html), "cli alt deck")


if __name__ == "__main__":
    test_fixture_decks_both_themes()
    test_section_fallback_when_no_findings()
    test_cap_and_omitted_note()
    test_contested_facet_slides()
    test_facet_fixture_deck_preserves_subsection()
    test_facet_slide_without_sides_condenses_subsection_html()
    test_cli_report_path_alt_theme()
    print("all 7 render-deck tests ran and passed")
