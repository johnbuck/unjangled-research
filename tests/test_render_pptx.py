"""PowerPoint renderer (E4-R3) checks: every format fixture and
valid_report.md render under the neutral theme and the motif-off alt
theme with the planned slide count, every planned title and bullet text
inside an <a:t> run on its slide, a non-empty notes page on every slide,
cover motif ellipses only when the theme enables the motif, hyperlinks
as the only external relationships, and byte-deterministic output. The
facet-match fixture proves both facet side labels land on the facet
slide."""
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
NS_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"

sys.path.insert(0, SCRIPTS)
from build_render_model import build_model  # noqa: E402
from render_pptx import render_pptx  # noqa: E402
from slide_plan import plan_slides  # noqa: E402
from theme import load_theme  # noqa: E402

FORMATS_DIR = os.path.join(HERE, "fixtures", "formats")
RENDER_DIR = os.path.join(HERE, "fixtures", "render")
THEMES = ["neutral", ALT]
REPORT_PATHS = sorted(
    os.path.join(FORMATS_DIR, f) for f in os.listdir(FORMATS_DIR) if f.endswith(".md")
) + [os.path.join(HERE, "fixtures", "valid_report.md")]

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


if __name__ == "__main__":
    test_fixture_decks_both_themes()
    test_source_hyperlinks()
    test_deterministic_output()
    test_facet_fixture_side_labels()
    test_cli_report_path_alt_theme()
    print("all 5 render-pptx tests ran and passed")
