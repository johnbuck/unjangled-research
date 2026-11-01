"""Report renderer: every format fixture plus valid_report.md renders under
the neutral theme and the alt theme fixture with the header title present,
sections in model order, every body [N] linked to a matching ref-N anchor,
the KPI strip absent when key_stats is empty, a Perspectives block per
contested facet that preserves the matched subsection's every sentence,
every source heading preserved in the body, a TOC only for long reports,
and no external references except the bibliography's source links.
House style: plain asserts, no pytest."""
import json
import os
import re
import subprocess
import sys
import tempfile
from html import unescape

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

from build_render_model import build_model, sentences, strip_md  # noqa: E402
from render_report import render_report, FORMAT_DISPLAY  # noqa: E402

FORMATS_DIR = os.path.join(HERE, "fixtures", "formats")
CONTESTED_DIR = os.path.join(HERE, "fixtures", "contested")
RENDER_DIR = os.path.join(HERE, "fixtures", "render")
ALT_THEME = os.path.join(HERE, "fixtures", "themes", "alt")

CASES = {
    os.path.join(FORMATS_DIR, "quick_brief.md"): "quick-brief",
    os.path.join(FORMATS_DIR, "comparison.md"): "comparison",
    os.path.join(FORMATS_DIR, "research_summary.md"): "research-summary",
    os.path.join(FORMATS_DIR, "discovery_catalog.md"): "discovery-catalog",
    os.path.join(HERE, "fixtures", "valid_report.md"): "comprehensive-report",
}
THEMES = ("neutral", ALT_THEME)

_CITE_A_RE = re.compile(r'<a class="rf-cite" href="#ref-(\d+)">\[\d+\]</a>')
_SEC_ID_RE = re.compile(r'id="sec-(\d+)"')


def _build(path, manifest=None):
    with open(path, encoding="utf-8") as f:
        return build_model(f.read(), manifest, None)


def _rendered(manifest_by_path=None):
    """[(path, theme, model, html)] for every fixture under both themes."""
    out = []
    for path in CASES:
        manifest = None
        if manifest_by_path and path in manifest_by_path:
            with open(manifest_by_path[path], encoding="utf-8") as f:
                manifest = json.load(f)
        model = _build(path, manifest)
        for theme in THEMES:
            out.append((path, theme, model, render_report(model, theme=theme)))
    return out


def _body_without_bib(html):
    """The html minus the bibliography section and minus cite links, tags
    stripped: any [N] left here is an unlinked body citation."""
    text = re.sub(r'<section class="rf-bib".*?</section>', "", html, flags=re.S)
    text = _CITE_A_RE.sub("", text)
    return re.sub(r"<[^>]+>", "", text)


def _plain_text(html):
    """Tag-stripped, entity-unescaped, whitespace-normalized body text."""
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", html)))


def _md_headings(text):
    """h2/h3 heading texts from the source markdown, bibliography excluded."""
    headings = []
    in_fence = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = re.match(r"^#{2,3}\s+(.*)$", line)
        if not m:
            continue
        heading = re.sub(r"\s+", " ", strip_md(m.group(1))).strip()
        if heading.lower() not in ("bibliography", "sources"):
            headings.append(heading)
    return headings


def test_header_title_subtitle_date_eyebrow():
    for path, theme, model, html in _rendered():
        assert f"<h1>{model['title']}</h1>" in html, (path, theme)
        assert f'<p class="rf-eyebrow">{FORMAT_DISPLAY[model["format"]]}</p>' in html, (path, theme)
        if model["subtitle"]:
            assert model["subtitle"] in html, (path, theme)
        if model["date"]:
            assert f'<p class="rf-meta">{model["date"]}</p>' in html, (path, theme)
        assert model["title"] in re.search(r"<title>(.*?)</title>", html).group(1), (path, theme)


def test_sections_in_model_order():
    for path, theme, model, html in _rendered():
        ids = [int(n) for n in _SEC_ID_RE.findall(html)]
        assert ids == sorted(ids), (path, theme, ids)
        assert len(ids) == len(set(ids)), (path, theme, ids)
        h2_indexes = [i for i, s in enumerate(model["sections"]) if s["level"] == 2]
        assert set(ids) <= set(h2_indexes), (path, theme)
        # every h2 section except the one rendered as the executive summary block
        assert len(ids) >= len(h2_indexes) - 1, (path, theme)


def test_citations_linked_to_matching_anchors():
    for path, theme, model, html in _rendered():
        anchors = set(re.findall(r'id="ref-(\d+)"', html))
        for n in _CITE_A_RE.findall(html):
            assert n in anchors, (path, theme, n)
        assert anchors, (path, theme)
        leftovers = re.findall(r"\[(\d{1,3})\]", _body_without_bib(html))
        assert not leftovers, (path, theme, leftovers)


def test_kpi_strip_matches_key_stats():
    for path, theme, model, html in _rendered():
        if not model["key_stats"]:
            assert 'class="rf-kpis"' not in html, (path, theme)
            continue
        cards = re.findall(r'<div class="rf-kpi">.*?</div>', html, re.S)
        assert len(cards) == len(model["key_stats"]), (path, theme)
        for stat, card in zip(model["key_stats"], cards):
            assert stat["value"] in card, (path, theme, stat)
            assert stat["label"] in card, (path, theme)
            if stat["ref"] is not None:
                assert f'href="#ref-{stat["ref"]}"' in card, (path, theme, stat)
            else:
                assert 'href="#ref-' not in card, (path, theme, stat)


def test_bibliography_numbered_with_anchor_links():
    for path, theme, model, html in _rendered():
        rows = re.findall(r'<div class="rf-ref" id="ref-(\d+)">', html)
        assert [int(n) for n in rows] == [s["n"] for s in model["sources"]], (path, theme)
        for src in model["sources"]:
            row = re.search(rf'<div class="rf-ref" id="ref-{src["n"]}">(.*?)</span></div>', html, re.S)
            assert row, (path, theme, src)
            assert src["title"] in row.group(1), (path, theme, src)
            if src["url"]:
                assert f'<a class="rf-ref-link" href="{src["url"]}">{src["title"]}</a>' in row.group(1), (path, theme, src)


def test_no_external_references_except_bibliography_links():
    for path, theme, model, html in _rendered():
        stripped = re.sub(r'<a class="rf-ref-link" href="[^"]+">.*?</a>', "", html)
        assert not re.search(r'(?:src|href)\s*=\s*["\']https?://', stripped), (path, theme)
        assert "@import" not in html, (path, theme)
        assert not re.search(r"url\(\s*['\"]?https?://", html, re.I), (path, theme)


def test_toc_only_for_long_reports():
    for path, theme, model, html in _rendered():
        h2_count = sum(1 for s in model["sections"] if s["level"] == 2)
        if h2_count > 4:
            assert '<nav class="rf-toc"' in html, (path, theme)
            toc_links = re.findall(r'<a href="#(sec-\d+|refs)">', html)
            ids = set(_SEC_ID_RE.findall(html)) | {"refs"}
            for anchor in toc_links:
                assert anchor.split("-")[-1] in ids, (path, theme, anchor)
        else:
            assert '<nav class="rf-toc"' not in html, (path, theme)


def test_alt_theme_swaps_footer_and_motif():
    for path in CASES:
        model = _build(path)
        neutral = render_report(model, theme="neutral")
        alt = render_report(model, theme=ALT_THEME)
        assert "— Research report" in neutral and "Research report ·" in alt, path
        assert 'class="motif"' in neutral, path
        assert 'class="motif"' not in alt, path
        assert 'src="data:image/svg+xml' in alt, path


def test_executive_summary_rendered_once():
    for path, theme, model, html in _rendered():
        if not model["executive_summary"]:
            continue
        assert '<section class="rf-summary"' in html, (path, theme)
        plain = re.sub(r'<a class="rf-cite"[^>]*>(\[\d+\])</a>', r"\1", html)
        first_para = model["executive_summary"][0]
        assert first_para in plain, (path, theme)
        assert plain.count(first_para) == 1, (path, theme)


def test_perspectives_block_per_contested_facet():
    manifest_path = os.path.join(CONTESTED_DIR, "manifest_with_facets.json")
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    with_manifest = _build(os.path.join(CONTESTED_DIR, "report_with_perspectives.md"), manifest)
    html = render_report(with_manifest)
    assert '<section class="rf-sec rf-persp"' in html
    for facet in with_manifest["contested_facets"]:
        assert f'<h3 class="rf-persp-facet-title">{facet["facet"]}</h3>' in html, facet
        assert len(re.findall(r'class="rf-persp-side [ab]"', html)) >= 2 * len(
            with_manifest["contested_facets"])
    for side_label in ("real harm", "null", "harm literature", "Critics"):
        assert side_label in html, side_label
    plain = _build(os.path.join(CONTESTED_DIR, "report_with_perspectives.md"))
    no_facets = render_report(plain)
    assert 'class="rf-persp-side' not in no_facets
    assert "Facet: effect size of screen time on attention" in no_facets


def test_perspectives_subsection_content_preserved():
    """Regression (story 3.2 review): a manifest facet worded 'Alpha vs.
    beta: ...' pairs with a subsection headed 'Alpha versus beta', and the
    rendered report keeps EVERY sentence of that subsection in its body —
    the Perspectives block may condense, never drop."""
    with open(os.path.join(RENDER_DIR, "facet_match_manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    report_path = os.path.join(RENDER_DIR, "facet_match_report.md")
    model = _build(report_path, manifest)
    facet = model["contested_facets"][0]
    assert len(facet["sides"]) >= 2 and facet["html"], facet
    for theme in THEMES:
        plain = _plain_text(render_report(model, theme=theme))
        with open(report_path, encoding="utf-8") as f:
            text = f.read()
        body = text.split("### Alpha versus beta", 1)[1].split("## Limitations", 1)[0]
        for para in re.split(r"\n\s*\n", body):
            para = re.sub(r"\s+", " ", strip_md(para)).strip()
            for sent in sentences(para):
                assert sent in plain, (theme, sent)
        for side in facet["sides"]:
            assert side["label"] in plain, (theme, side)


def test_source_headings_preserved_in_body():
    """Content preservation, general: every h2/h3 heading text in the source
    markdown (bibliography excluded) appears in the rendered body text."""
    paths = list(CASES) + [
        os.path.join(CONTESTED_DIR, "report_with_perspectives.md"),
        os.path.join(RENDER_DIR, "facet_match_report.md"),
    ]
    for path in paths:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        plain = _plain_text(render_report(_build(path)))
        for heading in _md_headings(text):
            assert heading in plain, (path, heading)


def test_cli_model_and_report_paths():
    with tempfile.TemporaryDirectory() as d:
        model_path = os.path.join(d, "model.json")
        out1 = os.path.join(d, "from-model.html")
        out2 = os.path.join(d, "from-report.html")
        model = _build(os.path.join(HERE, "fixtures", "valid_report.md"))
        with open(model_path, "w", encoding="utf-8") as f:
            json.dump(model, f)
        for argv in (
            [sys.executable, os.path.join(SCRIPTS, "render_report.py"),
             "--model", model_path, "--out", out1],
            [sys.executable, os.path.join(SCRIPTS, "render_report.py"),
             "--report", os.path.join(HERE, "fixtures", "valid_report.md"),
             "--theme", ALT_THEME, "--out", out2],
        ):
            r = subprocess.run(argv, capture_output=True, text=True)
            assert r.returncode == 0, r.stderr
        for out in (out1, out2):
            html = open(out, encoding="utf-8").read()
            assert "<h1>Research Report: Test Topic</h1>" in html, out
            assert 'id="ref-10"' in html, out
        assert "Research Report: Test Topic — Research report" in open(out1, encoding="utf-8").read()
        assert "Research report · Research Report: Test Topic" in open(out2, encoding="utf-8").read()


def test_print_rules_keep_citations_as_text():
    with open(os.path.join(ROOT, "assets", "render", "page.css"), encoding="utf-8") as f:
        css = f.read()
    print_block = css[css.rfind("@media print"):]
    assert ".rf-cite" in print_block and "text-decoration:none" in print_block
    assert "attr(href)" not in css


if __name__ == "__main__":
    test_header_title_subtitle_date_eyebrow()
    test_sections_in_model_order()
    test_citations_linked_to_matching_anchors()
    test_kpi_strip_matches_key_stats()
    test_bibliography_numbered_with_anchor_links()
    test_no_external_references_except_bibliography_links()
    test_toc_only_for_long_reports()
    test_alt_theme_swaps_footer_and_motif()
    test_executive_summary_rendered_once()
    test_perspectives_block_per_contested_facet()
    test_perspectives_subsection_content_preserved()
    test_source_headings_preserved_in_body()
    test_cli_model_and_report_paths()
    test_print_rules_keep_citations_as_text()
    print("all 14 render-report tests ran and passed")
