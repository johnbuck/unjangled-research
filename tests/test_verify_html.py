"""verify_html: the post-render completeness gate for the themed renderer.

The script must exit 0 on a valid neutral-theme render of every report
fixture (E2-R7), and exit 1 naming each loss on HTML that lost content:
a dropped '### Sources…' subsection, a lost link URL, a lost '| x | --- |'
table row, and a dropped bibliography note — including on the 65ea2cd
renderer's output (renderer files are identical to 4ce5be8, the epic
base), saved here as HTML fixtures. House style: plain asserts, no
pytest; nothing writes inside the skill directory (renders and mutated
HTML go to a system temp dir).
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
FIXTURES = os.path.join(HERE, "fixtures", "render")
FORMATS = os.path.join(HERE, "fixtures", "formats")

# The committed report fixtures (an explicit list, not a glob: parallel
# tickets add fixtures to this directory while they build).
REPORTS = [
    os.path.join(FIXTURES, "fidelity_report.md"),
    os.path.join(FIXTURES, "bibliography_rule_report.md"),
    os.path.join(FIXTURES, "facet_match_report.md"),
    os.path.join(FIXTURES, "verify_html_report.md"),
    # 2.8's fixture: links inside list items and 'text (URL)' summary
    # links (crashed the list-marker slicing before the review fix)
    os.path.join(FIXTURES, "link_fidelity_report.md"),
    os.path.join(FORMATS, "comparison.md"),
    os.path.join(FORMATS, "discovery_catalog.md"),
    os.path.join(FORMATS, "quick_brief.md"),
    os.path.join(FORMATS, "research_summary.md"),
]


def _render(md, out_dir):
    out = os.path.join(out_dir, os.path.basename(md).replace(".md", ".html"))
    r = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, "render_report.py"),
         "--report", md, "--theme", "neutral", "--out", out],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    with open(out, encoding="utf-8") as f:
        return f.read(), out


def _verify(html_path, md_path):
    r = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, "verify_html.py"),
         "--html", html_path, "--md", md_path],
        capture_output=True, text=True,
    )
    return r.returncode, r.stdout + r.stderr


def test_valid_renders_pass():
    """A neutral-theme render of every report fixture verifies clean
    (fails on 4ce5be8, whose script errors on every themed report)."""
    with tempfile.TemporaryDirectory() as d:
        for md in REPORTS:
            _, out = _render(md, d)
            rc, text = _verify(out, md)
            assert rc == 0, f"{md}:\n{text}"
            assert "PASS" in text


def test_old_renderer_fidelity_names_each_loss():
    """The 65ea2cd render of entry 1's fixture lost the funding
    subsection's text, the link and the '| x | --- |' row; each is
    named (plus the escaped-text and citation losses)."""
    rc, text = _verify(
        os.path.join(FIXTURES, "fidelity_report_65ea2cd.html"),
        os.path.join(FIXTURES, "fidelity_report.md"))
    assert rc == 1
    for needle in (
        "Funding came from three public grants",
        "lost link: 'protocol page' (https://example.com/protocol)",
        "lost table row: | dashes | x | --- |",
        "citation [2] missing from the rendered body",
    ):
        assert needle in text, needle


def test_old_renderer_fixture_names_note_loss():
    """The 65ea2cd render of the verify_html fixture also lost the
    bibliography note; it is named with the other losses."""
    rc, text = _verify(
        os.path.join(FIXTURES, "verify_html_report_65ea2cd.html"),
        os.path.join(FIXTURES, "verify_html_report.md"))
    assert rc == 1
    for needle in (
        "bibliography note lost: All URLs verified March 2026.",
        "Support came from two fellowships",
        "lost link: 'protocol page' (https://example.com/protocol)",
        "lost table row: | dashes | x | --- |",
    ):
        assert needle in text, needle


def test_hand_edited_render_names_lost_section_and_entry():
    """Surgically removing a subsection and a bibliography row from an
    otherwise valid render fails, naming both."""
    import re
    with tempfile.TemporaryDirectory() as d:
        html, out = _render(os.path.join(FIXTURES, "verify_html_report.md"), d)
        html = re.sub(
            r"<h3[^>]*>Sources of support</h3>.*?</section>", "", html, flags=re.S)
        html = re.sub(r'<div class="rf-ref" id="ref-2">.*?</div>', "", html,
                      flags=re.S)
        mutated = os.path.join(d, "mutated.html")
        with open(mutated, "w", encoding="utf-8") as f:
            f.write(html)
        rc, text = _verify(mutated, os.path.join(FIXTURES, "verify_html_report.md"))
        assert rc == 1
        assert "Support came from two fellowships" in text
        assert "bibliography entry [2]" in text


def test_stripped_anchor_fails():
    """Collapsing the body's https anchor back to plain text (the old
    renderer's loss) fails, naming the link and its URL."""
    with tempfile.TemporaryDirectory() as d:
        html, out = _render(os.path.join(FIXTURES, "verify_html_report.md"), d)
        html = html.replace(
            '<a href="https://example.com/protocol">protocol page</a>',
            "protocol page")
        mutated = os.path.join(d, "stripped.html")
        with open(mutated, "w", encoding="utf-8") as f:
            f.write(html)
        rc, text = _verify(mutated, os.path.join(FIXTURES, "verify_html_report.md"))
        assert rc == 1
        assert "lost link: 'protocol page' (https://example.com/protocol)" in text


def test_summary_link_url_loss_is_reported():
    """2.6 review fix 2: a summary link whose URL was deleted from the
    rendered HTML is a real loss (since 2.8, strip_md renders summary
    links as 'text (URL)', so text alone means the URL was lost). With
    the pre-fix summary leniency (link text accepted without its URL),
    this mutated render passes and the loss goes unreported."""
    with tempfile.TemporaryDirectory() as d:
        html, out = _render(os.path.join(FIXTURES, "link_fidelity_report.md"), d)
        # the summary paragraph holds the plain-text form; the body's copy
        # is a live anchor, so this replacement touches only the summary
        assert html.count("protocol page (https://example.com/protocol)") == 1
        html = html.replace("protocol page (https://example.com/protocol)",
                            "protocol page")
        mutated = os.path.join(d, "summary-url-lost.html")
        with open(mutated, "w", encoding="utf-8") as f:
            f.write(html)
        rc, text = _verify(mutated, os.path.join(FIXTURES, "link_fidelity_report.md"))
        assert rc == 1
        assert "lost link: 'protocol page' (https://example.com/protocol)" in text


def test_rf_doc_loss_not_hidden_by_summary_or_kpi_copy():
    """2.6 review fix 3: a link deleted from the rf-doc region is
    reported even though the summary still holds the same text, and a
    summary link's URL deleted from the summary is reported even though
    a KPI card still holds it. With body lines checked against the whole
    page (the pre-fix scope), every copy of the lost link sits outside
    the region it vanished from and hides the loss."""
    md = os.path.join(FIXTURES, "link_fidelity_report.md")
    with tempfile.TemporaryDirectory() as d:
        html, out = _render(md, d)
        # the mirror literal exists in the summary and once in rf-doc;
        # delete only the rf-doc copy (its scope) — the summary keeps one
        assert html.count("mirror (http://example.com/mirror)") == 2
        d0 = html.find('<div class="rf-doc"')
        d1 = html.find('<section class="rf-bib"', d0)
        doc = html[d0:d1].replace("mirror (http://example.com/mirror)",
                                  "mirror", 1)
        html = html[:d0] + doc + html[d1:]
        # the registry literal exists in the summary paragraph and in a
        # KPI card label; delete only the summary-paragraph copy — the
        # KPI card keeps one
        assert html.count("cohort registry (https://example.com/registry)") == 2
        s0 = html.find('<div class="rf-summary-body">')
        s1 = html.find("</div>", s0)
        summary = html[s0:s1].replace(
            "cohort registry (https://example.com/registry)", "cohort registry", 1)
        html = html[:s0] + summary + html[s1:]
        mutated = os.path.join(d, "doc-loss-hidden.html")
        with open(mutated, "w", encoding="utf-8") as f:
            f.write(html)
        rc, text = _verify(mutated, md)
        assert rc == 1
        assert "lost link: 'mirror' (http://example.com/mirror)" in text
        assert ("lost link: 'cohort registry' (https://example.com/registry)"
                in text)


def test_missing_html_file_exits_1():
    rc, text = _verify(
        os.path.join(FIXTURES, "no-such-file.html"),
        os.path.join(FIXTURES, "verify_html_report.md"))
    assert rc == 1
    assert "not found" in text


if __name__ == "__main__":
    test_valid_renders_pass()
    test_old_renderer_fidelity_names_each_loss()
    test_old_renderer_fixture_names_note_loss()
    test_hand_edited_render_names_lost_section_and_entry()
    test_stripped_anchor_fails()
    test_summary_link_url_loss_is_reported()
    test_rf_doc_loss_not_hidden_by_summary_or_kpi_copy()
    test_missing_html_file_exits_1()
    print("all 8 verify_html tests ran and passed")
