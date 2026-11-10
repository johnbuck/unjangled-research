"""Deck slide-list format (E5-R1/E5-R2/E5-R4): schemas/deck_spec.schema.json
and scripts/deck_spec.py define the authored deck format; the all-layouts
fixture validates and uses every layout once; validation errors name the
slide index and field; the plan-export CLI writes a valid slide list that
round-trips — rendering the export is byte-identical to rendering the same
report through --report (neutral and alt, formats fixture, and the
facet-matching manifest fixture); every layout renders with its content
text present under both themes; and check_theme.py exits 0 on the
all-layouts deck under both themes; the --check CLI prints
'valid: N slides' or one error line per faulty slide, and writes no file."""
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

from deck_spec import (COMMON_FIELDS, LAYOUTS, LAYOUT_FIELDS,  # noqa: E402
                       DeckError, load_deck, validate_deck)
from render_deck import render_slides  # noqa: E402

SCHEMA_PATH = os.path.join(ROOT, "schemas", "deck_spec.schema.json")
FIXTURE_DECK = os.path.join(HERE, "fixtures", "decks", "all_layouts.json")
ALT_THEME = os.path.join(HERE, "fixtures", "themes", "alt")
THEMES = ["neutral", ALT_THEME]
VALID_REPORT = os.path.join(HERE, "fixtures", "valid_report.md")
COMPARISON = os.path.join(HERE, "fixtures", "formats", "comparison.md")
FACET_REPORT = os.path.join(HERE, "fixtures", "render", "facet_match_report.md")
FACET_MANIFEST = os.path.join(HERE, "fixtures", "render", "facet_match_manifest.json")


def _run(args):
    return subprocess.run([sys.executable] + args, capture_output=True, text=True)


def _export_and_render(report, out_dir, theme="neutral", manifest=None):
    """Run the export CLI then render the export; return the deck HTML path."""
    stem = os.path.splitext(os.path.basename(report))[0]
    slides = os.path.join(out_dir, f"{stem}.slides.json")
    deck_html = os.path.join(out_dir, f"{stem}.from-slides.html")
    export_args = [os.path.join(SCRIPTS, "deck_spec.py"), "--report", report,
                   "--out", slides]
    if manifest:
        export_args += ["--manifest", manifest]
    export = _run(export_args)
    assert export.returncode == 0, (report, export.stderr, export.stdout)
    render = _run([os.path.join(SCRIPTS, "render_deck.py"), "--slides", slides,
                   "--theme", theme, "--out", deck_html])
    assert render.returncode == 0, (slides, render.stderr, render.stdout)
    return slides, deck_html


def _direct_render(report, out_dir, theme="neutral", manifest=None):
    stem = os.path.splitext(os.path.basename(report))[0]
    deck_html = os.path.join(out_dir, f"{stem}.direct.html")
    args = [os.path.join(SCRIPTS, "render_deck.py"), "--report", report,
            "--theme", theme, "--out", deck_html]
    if manifest:
        args += ["--manifest", manifest]
    render = _run(args)
    assert render.returncode == 0, (report, render.stderr, render.stdout)
    return deck_html


def test_schema_matches_validator():
    """The schema's oneOf branches and the validator's LAYOUT_FIELDS agree."""
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        schema = json.load(f)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    branches = schema["$defs"]["slide"]["oneOf"]
    by_layout = {}
    for branch in branches:
        layout = branch["properties"]["layout"]["const"]
        by_layout[layout] = branch
    assert sorted(by_layout) == sorted(LAYOUTS), (sorted(by_layout), sorted(LAYOUTS))
    for layout, branch in by_layout.items():
        required, optional = LAYOUT_FIELDS[layout]
        assert set(branch["required"]) == required | {"layout"}, layout
        props = set(branch["properties"]) - {"layout"}
        assert props == required | optional | set(COMMON_FIELDS), layout


def test_all_layouts_fixture_valid():
    deck = load_deck(FIXTURE_DECK)
    assert deck["title"]
    used = [s["layout"] for s in deck["slides"]]
    assert sorted(set(used)) == sorted(LAYOUTS), used
    assert used[0] == "cover"


def test_validation_errors_name_slide_and_field():
    def bad(mutate):
        deck = load_deck(FIXTURE_DECK)
        mutate(deck)
        try:
            validate_deck(deck)
        except DeckError as exc:
            return str(exc)
        raise AssertionError("validation unexpectedly passed")

    def at(slide_index, **changes):
        def apply(deck):
            deck["slides"][slide_index].update(changes)
        return apply

    def drop(slide_index, field):
        def apply(deck):
            del deck["slides"][slide_index][field]
        return apply

    cases = [
        (drop(1, "title"), r"slide 2 \(section\)\.title: required"),
        (at(1, layout="dividre"), r"slide 2\.layout: expected one of"),
        (at(4, bullets=None), r"slide 5 \(bullets\)\.bullets"),
        (at(4, bullets=[{"text": "x", "refs": [0]}]), r"slide 5 \(bullets\)\.bullets\[0\]\.refs\[0\]"),
        (at(5, left={"title": "No content"}), r"slide 6 \(two_column\)\.left: needs body or bullets"),
        (at(8, bars=[{"label": "L", "value": -1, "display": "x"},
                     {"label": "M", "value": 3, "display": "y"}]),
         r"slide 9 \(bars\)\.bars\[0\]\.value: expected a number >= 0"),
        (drop(9, "sides"), r"slide 10 \(facet\): needs sides or bullets"),
        (at(9, sides=[]), r"slide 10 \(facet\)\.sides: expected 1 to 4"),
        (at(3, statss=[]), r"slide 4 \(statement\): unknown field\(s\) statss"),
        (at(2, items=[{"title": "only one"}]), r"slide 3 \(agenda\)\.items: expected 2 to 5"),
    ]
    for mutate, pattern in cases:
        message = bad(mutate)
        assert re.search(pattern, message), (pattern, message)

    try:
        validate_deck({"title": "T", "slides": []})
    except DeckError as exc:
        assert "deck.slides" in str(exc)
    else:
        raise AssertionError("empty deck passed validation")


def test_layout_limits_keep_slides_inside_1280x720():
    """Every tightened layout cap rejects one-over content, naming the field;
    the caps come from rendered-geometry measurement (1280x720, both themes):
    at the caps each layout's tallest content stays above its footer."""
    def first_error(mutate):
        deck = load_deck(FIXTURE_DECK)
        mutate(deck)
        try:
            validate_deck(deck)
        except DeckError as exc:
            return str(exc)
        raise AssertionError("validation unexpectedly passed")

    over = [
        # slide 3 agenda (index 2)
        (lambda d: d["slides"][2].update(title="x" * 31),
         r"slide 3 \(agenda\)\.title: longer than 30"),
        (lambda d: d["slides"][2]["items"].append({"title": "Sixth row"}),
         r"slide 3 \(agenda\)\.items: expected 2 to 5"),
        (lambda d: d["slides"][2]["items"][0].update(title="x" * 21),
         r"slide 3 \(agenda\)\.items\[0\]\.title: longer than 20"),
        (lambda d: d["slides"][2]["items"][0].update(desc="x" * 56),
         r"slide 3 \(agenda\)\.items\[0\]\.desc: longer than 55"),
        # slide 4 statement (index 3)
        (lambda d: d["slides"][3].update(headline="x" * 151),
         r"slide 4 \(statement\)\.headline: longer than 150"),
        (lambda d: d["slides"][3]["stats"][0].update(label="x" * 91),
         r"slide 4 \(statement\)\.stats\[0\]\.label: longer than 90"),
        # slide 6 two_column (index 5)
        (lambda d: d["slides"][5]["left"].update(body="x" * 351),
         r"slide 6 \(two_column\)\.left\.body: longer than 350"),
        (lambda d: d["slides"][5]["right"].update(
            bullets=[{"text": "x" * 120}] * 4),
         r"slide 6 \(two_column\)\.right\.bullets: at most 3"),
        (lambda d: d["slides"][5]["right"]["bullets"][0].update(text="x" * 121),
         r"slide 6 \(two_column\)\.right\.bullets\[0\]\.text: longer than 120"),
        # slide 7 three_values (index 6)
        (lambda d: d["slides"][6].update(title="x" * 43),
         r"slide 7 \(three_values\)\.title: longer than 42"),
        (lambda d: d["slides"][6].update(note="x" * 101),
         r"slide 7 \(three_values\)\.note: longer than 100"),
        (lambda d: d["slides"][6]["values"][0].update(title="x" * 46),
         r"slide 7 \(three_values\)\.values\[0\]\.title: longer than 45"),
        (lambda d: d["slides"][6]["values"][0].update(body="x" * 201),
         r"slide 7 \(three_values\)\.values\[0\]\.body: longer than 200"),
        # slide 8 compare (index 7)
        (lambda d: d["slides"][7].update(title="x" * 36),
         r"slide 8 \(compare\)\.title: longer than 35"),
        (lambda d: d["slides"][7]["options"][0].update(tag="x" * 31),
         r"slide 8 \(compare\)\.options\[0\]\.tag: longer than 30"),
        (lambda d: d["slides"][7]["options"][0].update(name="x" * 46),
         r"slide 8 \(compare\)\.options\[0\]\.name: longer than 45"),
        (lambda d: d["slides"][7]["options"][0].update(rows=["x" * 60] * 4),
         r"slide 8 \(compare\)\.options\[0\]\.rows: expected 1 to 3"),
        (lambda d: d["slides"][7]["options"][0].update(rows=["x" * 61, "y", "z"]),
         r"slide 8 \(compare\)\.options\[0\]\.rows\[0\]: longer than 60"),
        (lambda d: d["slides"][7]["options"][0].update(kicker="x" * 81),
         r"slide 8 \(compare\)\.options\[0\]\.kicker: longer than 80"),
        # slide 9 bars (index 8): the note cap stays at 200 here
        (lambda d: d["slides"][8].update(note="x" * 201),
         r"slide 9 \(bars\)\.note: longer than 200"),
        # slide 10 facet (index 9)
        (lambda d: d["slides"][9]["sides"][0].update(label="x" * 41),
         r"slide 10 \(facet\)\.sides\[0\]\.label: longer than 40"),
        (lambda d: d["slides"][9]["sides"][0].update(summary="x" * 201),
         r"slide 10 \(facet\)\.sides\[0\]\.summary: longer than 200"),
        # slide 11 quote (index 10)
        (lambda d: d["slides"][10].update(title="x" * 36),
         r"slide 11 \(quote\)\.title: longer than 35"),
        (lambda d: d["slides"][10].update(title=None),
         r"slide 11 \(quote\)\.title: expected a string, got NoneType"),
        (lambda d: d["slides"][10].update(quote="x" * 401),
         r"slide 11 \(quote\)\.quote: longer than 400"),
        (lambda d: d["slides"][10].update(attribution="x" * 121),
         r"slide 11 \(quote\)\.attribution: longer than 120"),
        # slide 12 sources (index 11)
        (lambda d: d["slides"][11].update(title="x" * 41),
         r"slide 12 \(sources\)\.title: longer than 40"),
        (lambda d: d["slides"][11]["sources"][0].update(title="x" * 71),
         r"slide 12 \(sources\)\.sources\[0\]\.title: longer than 70"),
        (lambda d: d["slides"][11]["sources"][0].update(publisher="x" * 61),
         r"slide 12 \(sources\)\.sources\[0\]\.publisher: longer than 60"),
        # slide 13 closing (index 12)
        (lambda d: d["slides"][12].update(headline="x" * 91),
         r"slide 13 \(closing\)\.headline: longer than 90"),
        (lambda d: d["slides"][12].update(steps=["x" * 121] * 5),
         r"slide 13 \(closing\)\.steps\[0\]: longer than 120"),
    ]
    for mutate, pattern in over:
        message = first_error(mutate)
        assert re.search(pattern, message), (pattern, message)


def test_plan_export_clips_oversized_statement_headline():
    """A plan whose 20-word statement headline exceeds the layout's 150-char
    fit limit exports clipped, so every export validates (E5-R1)."""
    from build_render_model import build_model
    from deck_spec import slides_from_plan

    model = build_model(open(VALID_REPORT, encoding="utf-8").read(), None, None)
    model["executive_summary"] = [
        "The district library trustees reviewed comprehensive evening opening "
        "hours throughout every considerable suburban branch building and "
        "discovered that weekend attendance significantly exceeds weekday "
        "attendance throughout whatever periods were measured"
    ]
    deck = slides_from_plan(model)
    statement = next(s for s in deck["slides"] if s["layout"] == "statement")
    assert len(statement["headline"]) <= 150, statement["headline"]
    assert statement["headline"].endswith("…")


def test_plan_export_round_trips():
    """The export CLI writes a valid slide list whose render is byte-identical
    to the --report render of the same fixture (formats, manifest, alt theme)."""
    with tempfile.TemporaryDirectory() as d:
        for report, manifest in [(VALID_REPORT, None), (COMPARISON, None),
                                 (FACET_REPORT, FACET_MANIFEST)]:
            slides, from_slides = _export_and_render(report, d, manifest=manifest)
            exported = load_deck(slides)          # the export itself validates
            assert exported["slides"]
            direct = _direct_render(report, d, manifest=manifest)
            with open(from_slides, encoding="utf-8") as f:
                got = f.read()
            with open(direct, encoding="utf-8") as f:
                want = f.read()
            assert got == want, (report, "export render differs from --report")
        # alt theme: export once, render under both paths with the same theme
        slides, from_slides = _export_and_render(VALID_REPORT, d, theme=ALT_THEME)
        direct = _direct_render(VALID_REPORT, d, theme=ALT_THEME)
        assert open(from_slides, encoding="utf-8").read() \
            == open(direct, encoding="utf-8").read()


NEEDLES = {   # one content needle per layout, from the fixture
    "cover": "Sample layout tour",
    "section": "The layouts",
    "agenda": "What this deck shows",
    "statement": "One format now covers every generic slide layout",
    "bullets": "What a bullets slide holds",
    "two_column": "Write it as data",
    "three_values": "Three values in numbered columns",
    "compare": "Hand-built slides vs. a slide list",
    "bars": "Ranked bars with values",
    "facet": "One contested facet, two sides",
    "quote": "The slide list is the deck",
    "sources": "Sampling atlas, 4th ed.",
    "closing": "Compose the deck, then check it",
}
LAYOUT_CLASSES = {
    "cover": 'class="slide cover"',
    "section": "layout-divider",
    "agenda": "layout-agenda",
    "statement": "statement-title",
    "bullets": 'class="ticks"',
    "two_column": "two-col-panels",
    "three_values": "layout-three",
    "compare": "layout-compare",
    "bars": 'class="barriers"',
    "facet": "facet-grid cols-2",
    "quote": "quote-text",
    "sources": 'class="slide sources',
    "closing": "layout-closing",
}


def test_every_layout_renders_its_content():
    deck = load_deck(FIXTURE_DECK)
    for theme in THEMES:
        html = render_slides(deck, theme=theme)
        for layout, needle in NEEDLES.items():
            assert needle in html, (theme, layout, needle)
            assert LAYOUT_CLASSES[layout] in html, (theme, layout)
        assert "<small>%</small>" not in html or "64%" in html  # bars display verbatim
        assert html.count('class="agenda-row"') == 5 and html.count('class="value-col"') == 3
        assert html.count('class="compare-card') == 2 and html.count('class="brow') == 4
        assert html.count('class="step"') == 4
        assert "+2 more in the full report" in html
        for pgnum in ("02", "07", "13"):
            assert f'<span class="pgnum">{pgnum}</span>' in html, (theme, pgnum)
        # every slide carries speaker notes and a non-empty slide-main
        for section in re.findall(r'<section class="slide[^>]*>', html):
            assert "data-notes" in section
        assert not re.search(r'<main class="slide-main[^>]*>\s*</main>', html)


def test_check_theme_all_layouts_both_themes():
    deck = load_deck(FIXTURE_DECK)
    with tempfile.TemporaryDirectory() as d:
        for theme in THEMES:
            tname = "neutral" if theme == "neutral" else "alt"
            out = os.path.join(d, f"all-layouts-{tname}.html")
            with open(out, "w", encoding="utf-8") as f:
                f.write(render_slides(deck, theme=theme))
            r = _run([os.path.join(SCRIPTS, "check_theme.py"), out, "--theme", theme])
            assert r.returncode == 0, (theme, r.stdout, r.stderr)


def test_render_cli_rejects_invalid_slide_list():
    """render_deck.py --slides exits 1 with the slide and field named."""
    deck = load_deck(FIXTURE_DECK)
    deck["slides"][2]["items"] = [{"title": "only one row"}]
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "bad.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(deck, f)
        r = _run([os.path.join(SCRIPTS, "render_deck.py"), "--slides", path,
                  "--out", os.path.join(d, "out.html")])
        assert r.returncode == 1, (r.stdout, r.stderr)
        assert "ERROR" in r.stderr and "slide 3 (agenda).items" in r.stderr, r.stderr
        assert not os.path.exists(os.path.join(d, "out.html"))


def test_check_cli_reports_valid_and_every_error():
    """deck_spec.py --check prints 'valid: N slides' (exit 0) or one ERROR
    line per faulty slide naming the slide index and field (exit 1); it
    writes no file and takes a deck file only."""
    with tempfile.TemporaryDirectory() as d:
        good = os.path.join(d, "good.json")
        with open(good, "w", encoding="utf-8") as f:
            json.dump(load_deck(FIXTURE_DECK), f)
        r = _run([os.path.join(SCRIPTS, "deck_spec.py"), "--check", good])
        assert r.returncode == 0, (r.stdout, r.stderr)
        assert r.stdout.strip() == "valid: 13 slides", r.stdout
        assert not r.stderr, r.stderr

        deck = load_deck(FIXTURE_DECK)
        deck["slides"][2]["items"] = [{"title": "only one row"}]   # agenda rows
        deck["slides"][5]["left"] = {"title": "No content"}        # two_column panel
        deck["slides"][12].update(headline="x" * 91)               # closing headline
        bad = os.path.join(d, "bad.json")
        with open(bad, "w", encoding="utf-8") as f:
            json.dump(deck, f)
        r = _run([os.path.join(SCRIPTS, "deck_spec.py"), "--check", bad])
        assert r.returncode == 1, (r.stdout, r.stderr)
        for needle in ("slide 3 (agenda).items", "slide 6 (two_column).left",
                       "slide 13 (closing).headline"):
            assert needle in r.stderr, (needle, r.stderr)
        assert r.stdout == ""

        r = _run([os.path.join(SCRIPTS, "deck_spec.py"),
                  "--check", os.path.join(d, "missing.json")])
        assert r.returncode == 1 and "file not found" in r.stderr, r.stderr

        r = _run([os.path.join(SCRIPTS, "deck_spec.py"), "--check", good,
                  "--out", os.path.join(d, "nope.json")])
        assert r.returncode == 2 and "not allowed with" in r.stderr, r.stderr
        assert not os.path.exists(os.path.join(d, "nope.json"))


if __name__ == "__main__":
    test_schema_matches_validator()
    test_all_layouts_fixture_valid()
    test_validation_errors_name_slide_and_field()
    test_layout_limits_keep_slides_inside_1280x720()
    test_plan_export_clips_oversized_statement_headline()
    test_plan_export_round_trips()
    test_every_layout_renders_its_content()
    test_check_theme_all_layouts_both_themes()
    test_render_cli_rejects_invalid_slide_list()
    test_check_cli_reports_valid_and_every_error()
    print("all 10 deck-spec tests ran and passed")
