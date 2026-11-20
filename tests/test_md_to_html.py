"""md_to_html: report text is html-escaped before the markdown rules run
(E2-R1), the bibliography split and entry parsing come from the shared
helper (E2-R2), and build_sections still matches escaped headings, so a
hostile report renders escaped and whole through the themed renderer.
House style: plain asserts, no pytest; nothing writes inside the skill
directory (renders go to a system temp dir)."""
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

from md_to_html import convert_markdown_to_html  # noqa: E402
from build_render_model import build_model  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "render", "fidelity_report.md")


def _plain(html):
    """Tag-stripped, entity-unescaped, whitespace-normalized text."""
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", html)))


def _render_fixture():
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "fidelity_report.html")
        r = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "render_report.py"),
             "--report", FIXTURE, "--out", out],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, r.stderr
        with open(out, encoding="utf-8") as f:
            return f.read()


def test_fixture_renders_escaped_and_whole():
    """The Done-when-2 fixture through render_report.py --report: hostile
    markup is escaped text, never a live tag, and every authored section
    and the funding subsection's text survive (fails on 4ce5be8)."""
    html = _render_fixture()
    assert "&lt;script&gt;" in html
    assert "&lt;img onerror=" in html
    assert not re.search(r"<script[\s>]", html, re.I)
    assert not re.search(r"<img[\s>]", html, re.I)
    assert not re.search(r"<[^>]*\son\w+\s*=", html)
    plain = _plain(html)
    for needle in (
        "Funding came from three public grants and no industry body",
        "Sources of funding",
        "official protocol page",
        "List<T>",
        "Bold survives, italic survives",
    ):
        assert needle in plain, needle
    for heading in ("Executive Summary", "Key Points", "Main Analysis",
                    "Findings", "Comparison Table", "Limitations",
                    "Appendix: Reproduction"):
        assert heading in plain, heading


def test_escape_happens_before_markdown_rules():
    md = (
        "# T\n\n"
        "## S\n\n"
        "- <script>alert(1)</script>\n"
        "- `List<T>` and **bold**\n"
    )
    content, bib = convert_markdown_to_html(md)
    assert "&lt;script&gt;" in content
    assert "<code>List&lt;T&gt;</code>" in content
    assert "<strong>bold</strong>" in content
    assert "<li>" in content
    assert not re.search(r"<script[\s>]", content)
    assert bib == ""


def test_funding_subsection_and_fenced_bibliography_stay_body():
    md = (
        "# T\n\n"
        "## Body\n\n"
        "### Sources of funding\n\n"
        "Funding text stays [1].\n\n"
        "```\n## Bibliography\n```\n\n"
        "After the fence.\n\n"
        "## Bibliography\n\n"
        "[1] A (2024). Entry text. https://example.com/s\n"
    )
    content, bib = convert_markdown_to_html(md)
    assert "Sources of funding" in content
    assert "Funding text stays" in content
    assert "After the fence." in content
    assert "https://example.com/s" in bib
    assert "https://example.com/s" not in content


def test_postbib_sections_stay_in_body():
    md = (
        "# T\n\n"
        "## A\n\n"
        "Body A.\n\n"
        "## Bibliography\n\n"
        "[1] X. https://e.com/x\n\n"
        "## B\n\n"
        "Body B.\n"
    )
    content, bib = convert_markdown_to_html(md)
    assert "Body A." in content
    assert "Body B." in content
    assert "https://e.com/x" in bib
    assert "https://e.com/x" not in content
    assert '<span class="bib-number">[1]</span>' in bib
    no_bib = convert_markdown_to_html("# T\n\n## A\n\nOnly body.\n")
    assert "Only body." in no_bib[0]
    assert no_bib[1] == ""


def test_bibliography_entries_parsed_and_escaped():
    md = (
        "# T\n\n"
        "## Body\n\n"
        "Text [1].\n\n"
        "## Bibliography\n\n"
        "[1] Title <b>raw</b> - https://e.com/x?a=1&b=2\n"
        "- [2] Author, B. (2023). \"Quoted & Kept\". Journal.\n"
    )
    _, bib = convert_markdown_to_html(md)
    assert '<span class="bib-number">[1]</span>' in bib
    assert 'href="https://e.com/x?a=1&amp;b=2"' in bib
    assert "Title &lt;b&gt;raw&lt;/b&gt;" in bib
    assert '[2]' in bib
    assert "&quot;Quoted &amp; Kept&quot;" in bib


def test_build_sections_matches_escaped_headings():
    """Headings render escaped (`&` becomes `&amp;`), so build_sections
    must unescape before matching; a missed level-3 fragment renders an
    empty body."""
    md = (
        "# T\n\n"
        "## Main\n\n"
        "Intro.\n\n"
        "### Scope & Methodology\n\n"
        "The ampersand heading must keep its body.\n\n"
        "## R&D\n\n"
        "Another ampersand heading body.\n"
    )
    model = build_model(md)
    by_heading = {(s["level"], s["heading"]): s["html"] for s in model["sections"]}
    sub = by_heading[(3, "Scope & Methodology")]
    assert "The ampersand heading must keep its body." in sub
    assert "Scope &amp; Methodology" in sub
    h2 = by_heading[(2, "R&D")]
    assert "Another ampersand heading body." in h2
    assert "R&amp;D" in h2


def test_bibliography_keeps_non_entry_lines_escaped():
    """Notes, subsection labels and link-form entries inside the
    bibliography are authored text: they stay as escaped paragraphs.
    Blank lines and thematic rules are the only lines dropped."""
    md = (
        "# T\n\n"
        "## Body\n\n"
        "Text [1].\n\n"
        "## Bibliography\n\n"
        "### Primary sources\n\n"
        "[1] A (2024). Entry. https://e.com/a\n\n"
        "---\n\n"
        "Note: <i>two</i> sources were retracted & replaced.\n"
        "- [Link entry](https://e.com/link)\n"
    )
    _, bib = convert_markdown_to_html(md)
    assert '<span class="bib-number">[1]</span>' in bib
    assert "### Primary sources" in bib
    assert "Note: &lt;i&gt;two&lt;/i&gt; sources were retracted &amp; replaced." in bib
    assert "[Link entry](https://e.com/link)" in bib
    assert "<i>" not in bib
    assert "---" not in bib


def test_ampersand_heading_is_escaped_exactly_once():
    """A heading with '&' shows '&' in the browser: one '&amp;' in the
    rendered page, never '&amp;amp;'. A literal '&amp;' typed by the
    author renders as the five characters it is."""
    md = (
        "# T\n\n"
        "## Scope & Methods\n\n"
        "Body one.\n\n"
        "### Tools &amp; Kits\n\n"
        "Body two.\n"
    )
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "r.md")
        out = os.path.join(d, "r.html")
        with open(src, "w", encoding="utf-8") as f:
            f.write(md)
        r = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "render_report.py"),
             "--report", src, "--out", out],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, r.stderr
        with open(out, encoding="utf-8") as f:
            html = f.read()
    assert "Scope &amp; Methods" in html
    assert "Scope &amp;amp; Methods" not in html
    assert "Tools &amp;amp; Kits" in html
    assert "&amp;amp;amp;" not in html
    plain = _plain(html)
    assert "Scope & Methods" in plain
    assert "Tools &amp; Kits" in plain
    assert "Body one." in plain and "Body two." in plain


def test_prose_links_render_per_scheme():
    """E2-R3: an https target becomes an escaped anchor (already-escaped
    groups pass through, never escaped twice); http:, javascript:, file:,
    data: and relative targets become plain text with the URL in round
    brackets: no anchor, no raw markdown (fails on 4ce5be8)."""
    md = (
        "# T\n\n## Body\n\n"
        "A [protocol](https://e.com/p?a=1&b=2) link, an [insecure](http://e.com/i) "
        "link, a [script](javascript:alert(1)) link, a [local](file:///etc/x) link, "
        "a [data link](data:text/plain,x) link and a [note](../drafts/note.md) link [1].\n"
    )
    content, _ = convert_markdown_to_html(md)
    assert '<a href="https://e.com/p?a=1&amp;b=2">protocol</a>' in content
    assert "insecure (http://e.com/i)" in content
    assert "script (javascript:alert(1))" in content
    assert "local (file:///etc/x)" in content
    assert "data link (data:text/plain,x)" in content
    assert "note (../drafts/note.md)" in content
    assert not re.search(r'<a href="(?!https://)', content)
    for raw in ("](http", "](javascript", "](file", "](data", "](../drafts"):
        assert raw not in content, raw


def test_prose_link_scheme_case_and_escaped_text():
    """The scheme check is case-insensitive; entity-bearing text and URLs
    stay escaped exactly once inside the anchor."""
    md = (
        "# T\n\n## Body\n\n"
        "An [upper](HTTPS://E.COM/P) target still anchors, and "
        "[text with & entities](https://e.com/x?a=1&b=2) stays escaped once.\n"
    )
    content, _ = convert_markdown_to_html(md)
    assert '<a href="HTTPS://E.COM/P">upper</a>' in content
    assert '<a href="https://e.com/x?a=1&amp;b=2">text with &amp; entities</a>' in content


def test_links_inside_bullets_and_table_cells():
    md = (
        "# T\n\n## Body\n\n"
        "- See the [guide](https://e.com/g) for details.\n\n"
        "| Case | Link |\n|---|---|\n| one | [ref](https://e.com/r) |\n"
    )
    content, _ = convert_markdown_to_html(md)
    assert '<li>See the <a href="https://e.com/g">guide</a> for details.</li>' in content
    assert '<td><a href="https://e.com/r">ref</a></td>' in content


def test_table_separator_is_only_strict_second_row():
    """E2-R3: a data row containing --- is kept; a --- row anywhere but
    directly after the header is data; colon alignment cells still
    separate (4ce5be8 dropped every row containing ---)."""
    md = (
        "# T\n\n## Body\n\n"
        "| Case | Note |\n"
        "|---|---|\n"
        "| alpha | normal row |\n"
        "| Beta | --- (not published) |\n"
        "| omega | normal row |\n\n"
        "| A | B |\n"
        "| one | two |\n"
        "| --- | --- |\n\n"
        "| C | D |\n"
        "| :--- | ---: |\n"
        "| three | four |\n"
    )
    content, _ = convert_markdown_to_html(md)
    assert "<td>alpha</td>" in content
    assert "<td>Beta</td>" in content and "<td>--- (not published)</td>" in content
    assert "<td>omega</td>" in content
    assert "<td>one</td>" in content and "<td>two</td>" in content
    assert "<td>---</td>" in content
    assert "<td>three</td>" in content and "<td>four</td>" in content
    assert content.count("<th>") == 6
    assert content.count("<table>") == 3


def test_fixture_links_and_separator_row_survive():
    """Ticket 2.2 verify, end to end: on the shared fixture the https
    link is a live escaped anchor, javascript:/relative/http targets are
    plain text with no anchor and no raw markdown, and the --- data row
    is a <td> row (each assertion fails on 4ce5be8)."""
    html = _render_fixture()
    assert '<a href="https://example.com/protocol">protocol page</a>' in html
    for raw in ("[protocol page]", "[script link](", "[draft note](",
                "[insecure link](", "](javascript", "](../drafts",
                "](http://example.com"):
        assert raw not in html, raw
    assert not re.search(r'<a href="(?!https://|#)', html)
    plain = _plain(html)
    assert "script link (javascript:alert(1))" in plain
    assert "draft note (../drafts/note.md)" in plain
    assert "insecure link (http://example.com/insecure)" in plain
    assert "<td>dashes</td>" in html and "<td>---</td>" in html


def test_pipe_in_link_or_cell_never_straddles_cells():
    """A link carrying a pipe in its text or target stays literal text in
    its split cell: the converter never emits an anchor that opens in
    one <td> and closes in another (review finding on the first cut)."""
    md = (
        "# T\n\n## Body\n\n"
        "A [x](https://e.com/a|b) target pipe and a [a|b](https://e.com) text pipe.\n\n"
        "| Case | Note |\n|---|---|\n| [x](https://e.com/a|b) | y |\n"
    )
    content, _ = convert_markdown_to_html(md)
    assert "<a " not in content
    assert "<td>[x](https://e.com/a</td>" in content and "<td>b)</td>" in content
    assert "<td>y</td>" in content


def test_separator_needs_header_width():
    """A dash row directly after the header is dropped only at the
    header's cell count (GFM delimiter rows match it); any other width
    is a kept data row (review finding on the first cut)."""
    md = (
        "# T\n\n## Body\n\n"
        "| A | B |\n"
        "|---|\n"
        "| a | b |\n\n"
        "| C | D |\n"
        "|---|---|---|\n"
        "| c | d |\n"
    )
    content, _ = convert_markdown_to_html(md)
    assert "<td>a</td>" in content and "<td>b</td>" in content
    assert "<td>c</td>" in content and "<td>d</td>" in content
    assert "<td>---</td>" in content  # wrong-width dash rows are data
    assert content.count("<table>") == 2


def test_links_in_code_spans_stay_literal():
    """A link inside a code span is code text: no anchor, no rewrite,
    no bold/italic, in prose and in a table cell (review finding: the
    first cut anchored them)."""
    md = (
        "# T\n\n## Body\n\n"
        "Write `[c](https://e.com/code)` or `[j](javascript:x)` or `**b**` literally.\n\n"
        "| Case | Code |\n|---|---|\n| one | `[lit](https://e.com/lit)` |\n"
    )
    content, _ = convert_markdown_to_html(md)
    assert "<a " not in content
    assert "<code>[c](https://e.com/code)</code>" in content
    assert "<code>[j](javascript:x)</code>" in content
    assert "<code>**b**</code>" in content
    assert "<td><code>[lit](https://e.com/lit)</code></td>" in content


def test_link_targets_keep_parens_stars_and_never_break_out():
    """A target with balanced parentheses or `*` keeps its whole URL in
    the href, and a quote or angle bracket in a target stays escaped
    inside the quoted attribute (review finding: the first cut cut the
    href at the first ')' and turned '*b*' into <em> inside the href)."""
    md = (
        "# T\n\n## Body\n\n"
        "See [wiki](https://en.wikipedia.org/wiki/Foo_(bar)), "
        "[star](https://e.com/a*b*c), "
        "[q](https://e.com/\"onmouseover=\"alert(1)) and "
        "[lt](https://e.com/<script>x</script>).\n"
    )
    content, _ = convert_markdown_to_html(md)
    assert '<a href="https://en.wikipedia.org/wiki/Foo_(bar)">wiki</a>,' in content
    assert '<a href="https://e.com/a*b*c">star</a>' in content
    assert ('<a href="https://e.com/&quot;onmouseover=&quot;alert(1)">q</a>'
            in content)
    assert ('<a href="https://e.com/&lt;script&gt;x&lt;/script&gt;">lt</a>'
            in content)
    for href in re.findall(r'<a href="([^"]*)"', content):
        assert "<" not in href and ">" not in href, href


def test_row_without_trailing_pipe_keeps_every_cell():
    """A table row written '| a | b' (no trailing pipe) keeps its last
    cell, and a separator row written without its trailing pipe still
    has the header's width and separates (fails on 164ef39)."""
    md = (
        "# T\n\n## Body\n\n"
        "| A | B |\n"
        "|---|---\n"
        "| a | b\n"
        "| c | d |\n"
    )
    content, _ = convert_markdown_to_html(md)
    assert "<th>A</th>" in content and "<th>B</th>" in content
    assert "<td>a</td>" in content and "<td>b</td>" in content
    assert "<td>c</td>" in content and "<td>d</td>" in content
    assert "<td>---</td>" not in content


if __name__ == "__main__":
    test_fixture_renders_escaped_and_whole()
    test_escape_happens_before_markdown_rules()
    test_funding_subsection_and_fenced_bibliography_stay_body()
    test_postbib_sections_stay_in_body()
    test_bibliography_entries_parsed_and_escaped()
    test_build_sections_matches_escaped_headings()
    test_bibliography_keeps_non_entry_lines_escaped()
    test_ampersand_heading_is_escaped_exactly_once()
    test_prose_links_render_per_scheme()
    test_prose_link_scheme_case_and_escaped_text()
    test_links_inside_bullets_and_table_cells()
    test_table_separator_is_only_strict_second_row()
    test_fixture_links_and_separator_row_survive()
    test_pipe_in_link_or_cell_never_straddles_cells()
    test_separator_needs_header_width()
    test_links_in_code_spans_stay_literal()
    test_link_targets_keep_parens_stars_and_never_break_out()
    test_row_without_trailing_pipe_keeps_every_cell()
    print("all 18 md_to_html tests ran and passed")
