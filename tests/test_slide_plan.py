"""Slide plan (E4-R1): plan_slides produces the plain-data specs both deck
renderers build from — cover first and sources last on every fixture, at
most 12 content slides with the omitted-count note when a 20-finding model
overflows the cap, stat values verbatim in the source report with parts
that rebuild each value, facet specs carrying sides (empty, with bullets,
in the no-sides fallback), the section fallback when findings are missing,
no empty titles, and a JSON-serialisable plan throughout."""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from build_render_model import build_model  # noqa: E402
from slide_plan import CONTENT_SLIDE_CAP, plan_slides  # noqa: E402

FORMATS_DIR = os.path.join(HERE, "fixtures", "formats")
REPORT_PATHS = sorted(
    os.path.join(FORMATS_DIR, f) for f in os.listdir(FORMATS_DIR) if f.endswith(".md")
) + [os.path.join(HERE, "fixtures", "valid_report.md")]


def _model(path):
    with open(path, encoding="utf-8") as f:
        return build_model(f.read())


def _text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _assert_plain_json(specs, where):
    assert json.loads(json.dumps(specs)) == specs, where


def test_fixture_plan_shape():
    for path in REPORT_PATHS:
        specs = plan_slides(_model(path))
        assert specs, path
        assert specs[0]["kind"] == "cover", (path, specs[0]["kind"])
        assert specs[-1]["kind"] == "sources", (path, specs[-1]["kind"])
        content = [s for s in specs if s["kind"] not in ("cover", "sources")]
        assert 0 <= len(content) <= CONTENT_SLIDE_CAP, (path, len(content))
        for i, spec in enumerate(specs, 1):
            for key in ("kind", "title", "notes", "number"):
                assert key in spec, (path, i, key)
            assert spec["title"], (path, i, spec.get("title"))
            assert spec["number"] == i, (path, i, spec["number"])
        for key in ("eyebrow", "subtitle", "date"):
            assert key in specs[0], (path, key)
        _assert_plain_json(specs, path)


def test_statement_stats_verbatim():
    for path in REPORT_PATHS:
        text = _text(path)
        specs = plan_slides(_model(path))
        statements = [s for s in specs if s["kind"] == "statement"]
        assert statements, (path, "no statement spec")
        for spec in statements:
            for stat in spec["stats"]:
                value = re.sub(r"\s+", " ", str(stat["value"])).strip()
                assert value and value in text, (path, value)
                assert " ".join(p for p in stat["parts"] if p) == value, (path, stat)


def test_section_fallback_when_no_findings():
    path = os.path.join(FORMATS_DIR, "comparison.md")
    model = _model(path)
    assert model["findings"] == [], model["findings"]
    kinds = [s["kind"] for s in plan_slides(model)]
    assert "finding" not in kinds, kinds
    assert "section" in kinds, kinds


def test_cap_and_omitted_note():
    findings = [{"headline": f"Synthetic finding {i}", "refs": [1],
                 "body": f"Body sentence for finding {i}. " * 3}
                for i in range(1, 21)]
    specs = plan_slides(_synthetic_model(findings=findings))
    _assert_plain_json(specs, "cap model")
    assert specs[0]["kind"] == "cover" and specs[-1]["kind"] == "sources"
    content = [s for s in specs if s["kind"] not in ("cover", "sources")]
    assert len(content) == CONTENT_SLIDE_CAP, len(content)
    assert len(specs) == 1 + CONTENT_SLIDE_CAP + 1, len(specs)
    assert content[0]["kind"] == "statement"
    titles = " | ".join(s["title"] for s in content)
    assert "Synthetic finding 11" in titles          # statement + findings 1-11 fill the cap
    assert "Synthetic finding 12" not in titles
    assert f"Deck capped at {CONTENT_SLIDE_CAP} content slides; " \
           f"9 later content slide(s) omitted." in content[-1]["notes"]


def test_facet_specs_carry_sides():
    facets = [{"facet": "Effect size of the intervention",
               "sides": [{"label": "Camp for harm", "summary": "Harm summary [1]."},
                         {"label": "Camp for null", "summary": "Null summary [2]."}]},
              {"facet": "Measurement validity",
               "sides": [{"label": "Side A", "summary": "A [1]."},
                         {"label": "Side B", "summary": "B [2]."},
                         {"label": "Side C", "summary": "C [3]."}]}]
    specs = plan_slides(_synthetic_model(facets=facets))
    _assert_plain_json(specs, "facet model")
    facet_specs = [s for s in specs if s["kind"] == "facet"]
    assert len(facet_specs) == 2, len(facet_specs)
    for spec, facet in zip(facet_specs, facets):
        assert "sides" in spec, spec["title"]
        assert [s["label"] for s in spec["sides"]] == \
            [s["label"] for s in facet["sides"]], spec["title"]
        assert all(s["summary"] for s in spec["sides"]), spec["title"]
        assert "bullets" not in spec, spec["title"]


def test_facet_without_sides_falls_back_to_bullets():
    facets = [{"facet": "Effect size of the intervention", "sides": [],
               "html": "<h3 class=\"subsection-title\">Effect size</h3>"
                       "<p>First claim sentence one. Second claim sentence two. "
                       "Third claim sentence three. Fourth claim lives only in notes [1].</p>"}]
    specs = plan_slides(_synthetic_model(facets=facets))
    spec = next(s for s in specs if s["kind"] == "facet")
    assert spec["sides"] == [], spec
    assert [b["text"] for b in spec["bullets"]] == [
        "First claim sentence one.",
        "Second claim sentence two.",
        "Third claim sentence three."], spec["bullets"]
    assert "Fourth claim lives only in notes" in spec["notes"], spec["notes"]


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


if __name__ == "__main__":
    test_fixture_plan_shape()
    test_statement_stats_verbatim()
    test_section_fallback_when_no_findings()
    test_cap_and_omitted_note()
    test_facet_specs_carry_sides()
    test_facet_without_sides_falls_back_to_bullets()
    print("all 6 slide-plan tests ran and passed")
