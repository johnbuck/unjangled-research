"""PowerPoint renderer (E4-R3) checks: every format fixture and
valid_report.md render under the neutral theme and the motif-off alt
theme with the planned slide count, every planned title and bullet text
inside an <a:t> run on its slide, a non-empty notes page on every slide,
cover motif ellipses only when the theme enables the motif, hyperlinks
as the only external relationships, and byte-deterministic output. The
facet-match fixture proves both facet side labels land on the facet
slide.

Slide-list decks (E5-R3): the all-layouts fixture renders under both
themes with every text field of every slide in an <a:t> run on its slide
(and its notes lines on its notes page), bars produce one fill rectangle
per bar with widths ordered and scaled like the values, shape geometry
follows the HTML rules (divider bar under the centered title, content-
height panels, notes after their content, one closing rule per step, and
a schema-max bars slide shrinks uniformly instead of overflowing), the
sources
slide's hyperlinks are External hyperlink relationships only, output is
byte-deterministic, a minimal deck exercises the deck-level defaults and
the bullets/facet fallbacks, and the --slides CLI validates before it
renders."""
import json
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
SCRIPTS = os.path.join(ROOT, "scripts")
ALT = os.path.join(HERE, "fixtures", "themes", "alt")

NS_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
NS_P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
NS_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"

sys.path.insert(0, SCRIPTS)
from build_render_model import build_model  # noqa: E402
from render_pptx import render_pptx, render_pptx_slides  # noqa: E402
from slide_plan import plan_slides, stat_parts  # noqa: E402
from theme import footer_label, load_theme  # noqa: E402

FORMATS_DIR = os.path.join(HERE, "fixtures", "formats")
RENDER_DIR = os.path.join(HERE, "fixtures", "render")
THEMES = ["neutral", ALT]
REPORT_PATHS = sorted(
    os.path.join(FORMATS_DIR, f) for f in os.listdir(FORMATS_DIR) if f.endswith(".md")
) + [os.path.join(HERE, "fixtures", "valid_report.md")]
FIXTURE_DECK = os.path.join(HERE, "fixtures", "decks", "all_layouts.json")

SLIDE_PART_RE = re.compile(r"^ppt/slides/slide(\d+)\.xml$")


def read_parts(path):
    with zipfile.ZipFile(path) as zf:
        return {name: zf.read(name) for name in zf.namelist()}


def slide_runs(parts, i):
    """Each <a:t> run's unescaped text on slide i."""
    slide = ET.fromstring(parts[f"ppt/slides/slide{i}.xml"])
    return [t.text or "" for t in slide.iter(f"{NS_A}t")]


def notes_text(parts, i):
    note = ET.fromstring(parts[f"ppt/notesSlides/notesSlide{i}.xml"])
    return "".join(t.text or "" for t in note.iter(f"{NS_A}t"))


def external_rels(parts):
    """(rels part name, Relationship element) for every External target."""
    out = []
    for name in sorted(n for n in parts if n.endswith(".rels")):
        for rel in ET.fromstring(parts[name]).findall(f"{NS_REL}Relationship"):
            if rel.get("TargetMode") == "External":
                out.append((name, rel))
    return out


def render_fixture(model, theme, d, label):
    out = os.path.join(d, f"deck-{label}.pptx")
    render_pptx(model, out, theme=theme)
    return out


def test_fixture_decks_both_themes():
    for path in REPORT_PATHS:
        with open(path, encoding="utf-8") as f:
            model = build_model(f.read())
        specs = plan_slides(model)
        with tempfile.TemporaryDirectory() as d:
            for theme in THEMES:
                out = render_fixture(model, theme, d,
                                     f"{os.path.basename(path)}-{os.path.basename(theme)}")
                assert zipfile.is_zipfile(out), out
                parts = read_parts(out)
                slide_nums = sorted(int(m.group(1)) for m in
                                    (SLIDE_PART_RE.match(n) for n in parts) if m)
                assert slide_nums == list(range(1, len(specs) + 1)), \
                    (path, theme, slide_nums, len(specs))
                for spec in specs:
                    i = spec["number"]
                    texts = slide_runs(parts, i)
                    assert spec["title"] in texts, (path, theme, i, spec["title"])
                    for bullet in spec.get("bullets") or []:
                        assert bullet["text"] in texts, (path, theme, i, bullet["text"])
                    assert notes_text(parts, i).strip(), (path, theme, i)
                cover = parts["ppt/slides/slide1.xml"].decode("utf-8")
                ellipses = cover.count('prst="ellipse"')
                if load_theme(theme)["motif"]["enabled"]:
                    assert ellipses > 0, (path, theme, "motif enabled but no ellipses")
                else:
                    assert ellipses == 0, (path, theme, "motif disabled but ellipses present")
                for name, rel in external_rels(parts):
                    assert rel.get("Type", "").endswith("/hyperlink"), (name, rel.get("Type"))


def test_source_hyperlinks():
    """valid_report's ten sources all carry URLs, so the sources slide's
    rels hold exactly ten external hyperlink relationships."""
    with open(os.path.join(HERE, "fixtures", "valid_report.md"), encoding="utf-8") as f:
        model = build_model(f.read())
    specs = plan_slides(model)
    src = next(s for s in specs if s["kind"] == "sources")
    with tempfile.TemporaryDirectory() as d:
        parts = read_parts(render_fixture(model, "neutral", d, "sources"))
    rels = parts[f"ppt/slides/_rels/slide{src['number']}.xml.rels"].decode("utf-8")
    hyper = [rel for rel in ET.fromstring(rels).findall(f"{NS_REL}Relationship")
             if rel.get("TargetMode") == "External"]
    expected = len([s for s in src["sources"] if s.get("url")])
    assert expected > 0 and len(hyper) == expected, (len(hyper), expected)


def test_deterministic_output():
    with open(os.path.join(HERE, "fixtures", "valid_report.md"), encoding="utf-8") as f:
        model = build_model(f.read())
    with tempfile.TemporaryDirectory() as d:
        for theme in THEMES:
            a = render_fixture(model, theme, d, f"once-{os.path.basename(theme)}")
            b = render_fixture(model, theme, d, f"twice-{os.path.basename(theme)}")
            with open(a, "rb") as f1, open(b, "rb") as f2:
                assert f1.read() == f2.read(), (theme, "two renders differ")


def test_facet_fixture_side_labels():
    """The screen-time-style facet fixture: the facet slide carries both
    extracted side labels as slide text."""
    with open(os.path.join(RENDER_DIR, "facet_match_manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    with open(os.path.join(RENDER_DIR, "facet_match_report.md"), encoding="utf-8") as f:
        model = build_model(f.read(), manifest)
    specs = plan_slides(model)
    facet = next(s for s in specs if s["kind"] == "facet")
    assert len(facet["sides"]) >= 2, facet["sides"]
    with tempfile.TemporaryDirectory() as d:
        parts = read_parts(render_fixture(model, "neutral", d, "facet"))
    texts = slide_runs(parts, facet["number"])
    for side in facet["sides"]:
        assert side["label"] in texts, (side["label"], texts)


def test_cli_report_path_alt_theme():
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "deck.pptx")
        r = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "render_pptx.py"),
             "--report", os.path.join(HERE, "fixtures", "valid_report.md"),
             "--theme", ALT, "--out", out],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, r.stderr
        assert zipfile.is_zipfile(out)
        parts = read_parts(out)
        cover = parts["ppt/slides/slide1.xml"].decode("utf-8")
        assert cover.count('prst="ellipse"') == 0, "alt theme must render no motif"


# ---------- slide-list decks (E5-R3) ----------

def _section_default(slide, deck):
    return (slide.get("section") or deck.get("footer_section")
            or slide["layout"].replace("_", " ").title())


def _expected_slide_texts(slide, deck, theme):
    """Every string the renderer must emit verbatim in an <a:t> run on
    this slide, with the renderer's transforms applied (uppercase eyebrow,
    date, tag, attribution; stat values split by stat_parts)."""
    out = []

    def add(text):
        if text:
            out.append(str(text))

    layout = slide["layout"]
    if layout != "cover":
        add((slide.get("eyebrow") or _section_default(slide, deck)).upper())
    if layout == "cover":
        add(slide["title"])
        add((slide.get("eyebrow") or deck.get("eyebrow") or "").upper())
        sub = slide["subtitle"] if slide.get("subtitle") is not None \
            else (deck.get("subtitle") or "")
        add(sub)
        date = slide["date"] if slide.get("date") is not None else (deck.get("date") or "")
        add(str(date).upper())
    elif layout == "section":
        add(slide["title"])
        add(slide.get("sub"))
    elif layout == "agenda":
        add(slide["title"])
        for j, item in enumerate(slide["items"]):
            add(f"{j + 1:02d}")
            add(item["title"])
            add(item.get("desc"))
    elif layout == "statement":
        add(slide["headline"])
        for stat in slide.get("stats") or []:
            num, unit = stat_parts(stat["value"])
            add(num)
            add(" " + unit if unit else None)
            add(stat["label"])
            if stat.get("ref") is not None:
                add(f"  [{stat['ref']}]")
    elif layout == "bullets":
        add(slide["title"])
        for bullet in slide.get("bullets") or []:
            add(bullet["text"])
    elif layout == "two_column":
        add(slide["title"])
        for key in ("left", "right"):
            add(slide[key]["title"])
            if slide[key].get("body") is not None:
                add(slide[key]["body"])
            else:
                for bullet in slide[key].get("bullets") or []:
                    add(bullet["text"])
    elif layout == "three_values":
        add(slide["title"])
        for j, value in enumerate(slide["values"]):
            add(f"{j + 1:02d}")
            add(value["title"])
            add(value["body"])
        add(slide.get("note"))
    elif layout == "compare":
        add(slide["title"])
        for j, option in enumerate(slide["options"]):
            add((option.get("tag") or f"Option {'AB'[j]}").upper())
            add(option["name"])
            for row in option["rows"]:
                add(row)
            add(option.get("kicker"))
    elif layout == "bars":
        add(slide["title"])
        for bar in slide["bars"]:
            add(bar["label"])
            add(bar["display"])
        add(slide.get("note"))
    elif layout == "facet":
        add(slide["title"])
        for side in slide.get("sides") or []:
            add(side["label"])
            add(side["summary"])
        for bullet in slide.get("bullets") or []:
            add(bullet["text"])
    elif layout == "quote":
        add(slide.get("title"))
        add(slide["quote"])
        add(slide.get("attribution").upper() if slide.get("attribution") else None)
    elif layout == "sources":
        add(slide["title"])
        for src in slide["sources"]:
            add(f"[{src['n']}]  ")
            add(src["title"])
            if src.get("publisher"):
                add(f" — {src['publisher']}")
        if slide.get("more_sources"):
            add(f"+{slide['more_sources']} more in the full report")
    elif layout == "closing":
        add(slide["headline"])
        for j, step in enumerate(slide["steps"]):
            add(f"{j + 1:02d}")
            add(step)
    if layout != "cover":
        section = _section_default(slide, deck)
        add(footer_label(load_theme(theme), deck["title"], section).upper())
    return out


def _slide_names_and_extents(parts, i):
    """(name, cx EMU) for every shape on slide i, in document order."""
    root = ET.fromstring(parts[f"ppt/slides/slide{i}.xml"])
    out = []
    for sp in root.iter(f"{NS_P}sp"):
        cNvPr = sp.find(f"{NS_P}nvSpPr/{NS_P}cNvPr")
        ext = sp.find(f".//{NS_A}xfrm/{NS_A}ext")
        if cNvPr is not None and ext is not None:
            out.append((cNvPr.get("name"), int(ext.get("cx"))))
    return out


EMU_PER_PX = 9525


def _shape_geo(parts, i):
    """{name: (x, y, cx, cy) in deck px} for every shape (sp or cxnSp) on
    slide i."""
    root = ET.fromstring(parts[f"ppt/slides/slide{i}.xml"])
    out = {}
    for sp in list(root.iter(f"{NS_P}sp")) + list(root.iter(f"{NS_P}cxnSp")):
        cNvPr = sp.find(f".//{NS_P}cNvPr")
        off = sp.find(f".//{NS_A}xfrm/{NS_A}off")
        ext = sp.find(f".//{NS_A}xfrm/{NS_A}ext")
        if cNvPr is None or off is None or ext is None:
            continue
        out[cNvPr.get("name")] = (int(off.get("x")) / EMU_PER_PX,
                                  int(off.get("y")) / EMU_PER_PX,
                                  int(ext.get("cx")) / EMU_PER_PX,
                                  int(ext.get("cy")) / EMU_PER_PX)
    return out


def test_all_layouts_deck_both_themes():
    with open(FIXTURE_DECK, encoding="utf-8") as f:
        deck = json.load(f)
    with tempfile.TemporaryDirectory() as d:
        for theme in THEMES:
            out = os.path.join(d, f"all-layouts-{os.path.basename(theme)}.pptx")
            render_pptx_slides(deck, out, theme=theme)
            parts = read_parts(out)
            slide_nums = sorted(int(m.group(1)) for m in
                                (SLIDE_PART_RE.match(n) for n in parts) if m)
            assert slide_nums == list(range(1, len(deck["slides"]) + 1)), \
                (theme, slide_nums, len(deck["slides"]))
            for i, slide in enumerate(deck["slides"], start=1):
                texts = slide_runs(parts, i)
                for expected in _expected_slide_texts(slide, deck, theme):
                    assert expected in texts, (theme, i, slide["layout"], expected)
                if slide.get("notes"):
                    note = notes_text(parts, i)
                    for line in slide["notes"].split("|"):
                        assert line in note, (theme, i, line)
            cover = parts["ppt/slides/slide1.xml"].decode("utf-8")
            ellipses = cover.count('prst="ellipse"')
            if load_theme(theme)["motif"]["enabled"]:
                assert ellipses > 0, (theme, "motif enabled but no ellipses")
            else:
                assert ellipses == 0, (theme, "motif disabled but ellipses present")
            for name, rel in external_rels(parts):
                assert rel.get("Type", "").endswith("/hyperlink"), (name, rel.get("Type"))


def test_all_layouts_bars_one_rect_per_bar():
    """The bars slide draws exactly one fill rectangle per bar, its width
    proportional to the bar's value (scaled to the max)."""
    with open(FIXTURE_DECK, encoding="utf-8") as f:
        deck = json.load(f)
    bars_slide = next(s for s in deck["slides"] if s["layout"] == "bars")
    number = deck["slides"].index(bars_slide) + 1
    values = [b["value"] for b in bars_slide["bars"]]
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "bars.pptx")
        render_pptx_slides(deck, out, theme="neutral")
        parts = read_parts(out)
    fills = {name: cx for name, cx in _slide_names_and_extents(parts, number)
             if re.fullmatch(r"Bar (\d+) fill", name)}
    assert sorted(int(re.match(r"Bar (\d+) fill", n).group(1)) for n in fills) \
        == list(range(1, len(values) + 1)), sorted(fills)
    widths = [fills[f"Bar {j + 1} fill"] for j in range(len(values))]
    top = max(values)
    for width, value in zip(widths, values):
        expect = widths[0] * value / top
        assert abs(width - expect) <= 2 * 9525, (width, expect)   # 2px slack
    assert all(a >= b for a, b in zip(widths, widths[1:])), widths


def test_all_layouts_layout_geometry_follows_html():
    """The new builders' shapes sit where the HTML rules put them: the
    divider bar rides under the centered title block, two-column panels
    hug their content at a shared height, the values and bars notes follow
    their content instead of pinning above the footer, and closing steps
    each carry a hairline rule with the block inside the body region."""
    with open(FIXTURE_DECK, encoding="utf-8") as f:
        deck = json.load(f)
    layout_of = {i: s["layout"] for i, s in enumerate(deck["slides"], start=1)}
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "geo.pptx")
        render_pptx_slides(deck, out, theme="neutral")
        parts = read_parts(out)

    def num(i, prefix):
        geo = _shape_geo(parts, i)
        return {name: geo[name] for name in geo if name.startswith(prefix)}

    # section (slide 2): bar below the title block, well above the footer.
    bar = num(2, "Divider bar")["Divider bar"]
    assert 340 <= bar[1] <= 560, bar

    # two_column (slide 6): panels share one content-height row, centered.
    left, right = num(6, "Column panel left")["Column panel left"], \
        num(6, "Column panel right")["Column panel right"]
    assert left[1] == right[1] and left[3] == right[3], (left, right)
    assert 120 <= left[3] < 444, left
    assert left[1] >= 206 and left[1] + left[3] <= 650, left
    for j in (1, 2):
        body = num(6, f"Column body {j}") or num(6, f"Column bullets {j}")
        (name, geo), = body.items()
        assert geo[1] >= left[1] and geo[1] + geo[3] <= left[1] + left[3], (name, geo)

    # three_values (slide 7): note below the estimated grid, above 600.
    note = num(7, "Values note")["Values note"]
    assert 350 < note[1] <= 600, note

    # bars (slide 9): note directly after the last row's track.
    tracks = num(9, "Bar track")
    note = num(9, "Bars note")["Bars note"]
    last_track = max(geo[1] for geo in tracks.values())
    assert last_track < note[1] <= last_track + 40, (last_track, note)

    # closing (slide 13): one rule per step, each above its number and
    # text, with the block inside the body region.
    geo = _shape_geo(parts, 13)
    step_count = len(deck["slides"][12]["steps"])
    rules = sorted((g for n, g in geo.items()
                    if re.fullmatch(r"Closing step rule \d+", n)), key=lambda g: g[1])
    numbers = sorted((g for n, g in geo.items()
                      if re.fullmatch(r"Closing step number \d+", n)),
                     key=lambda g: g[1])
    texts = sorted((g for n, g in geo.items()
                    if re.fullmatch(r"Closing step \d+", n)), key=lambda g: g[1])
    assert len(rules) == len(numbers) == len(texts) == step_count, \
        (len(rules), len(numbers), len(texts), step_count)
    for rule, number, text in zip(rules, numbers, texts):
        assert rule[1] < number[1] and rule[1] < text[1], (rule, number, text)
    assert 140 <= rules[0][1] and rules[-1][1] < 674, (rules[0], rules[-1])


def test_all_layouts_bars_overflow_is_contained():
    """A schema-max 6-bar slide with a note stays inside the bars region,
    with the note attached below the last row."""
    deck = {"title": "Dense bars", "slides": [
        {"layout": "cover", "title": "Dense bars"},
        {"layout": "bars", "title": "Six bars", "note": "Sample data.",
         "bars": [{"label": f"Row {j + 1}", "value": 100 - j * 5,
                   "display": f"{100 - j * 5}%"} for j in range(6)]},
    ]}
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "dense.pptx")
        render_pptx_slides(deck, out, theme="neutral")
        parts = read_parts(out)
    geo = _shape_geo(parts, 2)
    tops = [g[1] for n, g in geo.items() if n.startswith("Bar label")]
    bottoms = [g[1] + g[3] for n, g in geo.items() if n.startswith("Bar label")]
    assert min(tops) >= 206, min(tops)
    assert max(bottoms) <= 630, max(bottoms)
    note = geo["Bars note"]
    assert note[1] >= max(bottoms) and note[1] + note[3] <= 660, note
    widths = [geo[f"Bar {j + 1} fill"][2] for j in range(6)]
    assert all(a >= b for a, b in zip(widths, widths[1:])), widths


def test_all_layouts_sources_hyperlinks():
    with open(FIXTURE_DECK, encoding="utf-8") as f:
        deck = json.load(f)
    sources_slide = next(s for s in deck["slides"] if s["layout"] == "sources")
    number = deck["slides"].index(sources_slide) + 1
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "sources.pptx")
        render_pptx_slides(deck, out, theme="neutral")
        parts = read_parts(out)
    rels = parts[f"ppt/slides/_rels/slide{number}.xml.rels"].decode("utf-8")
    hyper = [rel for rel in ET.fromstring(rels).findall(f"{NS_REL}Relationship")
             if rel.get("TargetMode") == "External"]
    expected = len([s for s in sources_slide["sources"] if s.get("url")])
    assert expected > 0 and len(hyper) == expected, (len(hyper), expected)
    for rel in hyper:
        assert rel.get("Type", "").endswith("/hyperlink"), rel.get("Type")


def test_all_layouts_deterministic():
    with open(FIXTURE_DECK, encoding="utf-8") as f:
        deck = json.load(f)
    with tempfile.TemporaryDirectory() as d:
        for theme in THEMES:
            a = os.path.join(d, f"once-{os.path.basename(theme)}.pptx")
            b = os.path.join(d, f"twice-{os.path.basename(theme)}.pptx")
            render_pptx_slides(deck, a, theme=theme)
            render_pptx_slides(deck, b, theme=theme)
            with open(a, "rb") as f1, open(b, "rb") as f2:
                assert f1.read() == f2.read(), (theme, "two renders differ")


MINIMAL_DECK = {
    "title": "Defaults check",
    "subtitle": "Deck subtitle default",
    "date": "March 2026",
    "eyebrow": "Deck eyebrow",
    "footer_section": "Intro",
    "slides": [
        {"layout": "cover", "title": "Defaults check"},
        {"layout": "bullets", "title": "No bullets, refs only", "bullets": [], "refs": [2, 5]},
        {"layout": "facet", "title": "Facet fallback",
         "bullets": [{"text": "Fallback bullet."}]},
        {"layout": "quote", "title": "Titled quote", "quote": "Short quoted line.",
         "attribution": "A. Person"},
    ],
}


def test_minimal_deck_defaults_and_fallbacks():
    """Cover fields fall back to the deck defaults, a bullets slide with
    no bullets shows the Evidence refs line, and a facet without sides
    falls back to its bullets."""
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "minimal.pptx")
        render_pptx_slides(MINIMAL_DECK, out, theme="neutral")
        parts = read_parts(out)
        cover = slide_runs(parts, 1)
        assert "DECK EYEBROW" in cover
        assert "Deck subtitle default" in cover
        assert "MARCH 2026" in cover
        bullets = " ".join(slide_runs(parts, 2))
        assert "Evidence: [2] [5]" in bullets
        facet = slide_runs(parts, 3)
        assert "Fallback bullet." in facet
        quote = slide_runs(parts, 4)
        assert "Titled quote" in quote and "A. PERSON" in quote


def test_cli_slides_path():
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "deck.pptx")
        r = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "render_pptx.py"),
             "--slides", FIXTURE_DECK, "--theme", ALT, "--out", out],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, r.stderr
        assert zipfile.is_zipfile(out)
        parts = read_parts(out)
        cover = parts["ppt/slides/slide1.xml"].decode("utf-8")
        assert cover.count('prst="ellipse"') == 0, "alt theme must render no motif"

        bad = os.path.join(d, "bad.json")
        with open(bad, "w", encoding="utf-8") as f:
            json.dump({"slides": [{"layout": "cover", "title": "No deck title"}]}, f)
        r = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "render_pptx.py"),
             "--slides", bad, "--out", os.path.join(d, "bad.pptx")],
            capture_output=True, text=True,
        )
        assert r.returncode == 1, (r.returncode, r.stderr)
        assert "deck.title" in r.stderr

        r = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "render_pptx.py"),
             "--slides", FIXTURE_DECK, "--manifest", "x.json",
             "--out", os.path.join(d, "none.pptx")],
            capture_output=True, text=True,
        )
        assert r.returncode == 2, (r.returncode, r.stderr)


if __name__ == "__main__":
    test_fixture_decks_both_themes()
    test_source_hyperlinks()
    test_deterministic_output()
    test_facet_fixture_side_labels()
    test_cli_report_path_alt_theme()
    test_all_layouts_deck_both_themes()
    test_all_layouts_bars_one_rect_per_bar()
    test_all_layouts_layout_geometry_follows_html()
    test_all_layouts_bars_overflow_is_contained()
    test_all_layouts_sources_hyperlinks()
    test_all_layouts_deterministic()
    test_minimal_deck_defaults_and_fallbacks()
    test_cli_slides_path()
    print("all 13 render-pptx tests ran and passed")
