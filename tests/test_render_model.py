"""Render model builder: every fixture yields a schema-valid model whose
key_stats are verbatim report numbers, the bibliography stays out of
sections, and a contested manifest yields facets with two sides each."""
import json
import os
import re
import string
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

from build_render_model import (  # noqa: E402
    CONNECTOR_WORDS,
    _stat_label,
    build_model,
    build_bibliography,
    build_sources,
    parse_report,
    sentences,
    strip_md,
)

from schema_validator import schema_errors  # noqa: E402

FORMATS_DIR = os.path.join(HERE, "fixtures", "formats")
CONTESTED_DIR = os.path.join(HERE, "fixtures", "contested")
RENDER_DIR = os.path.join(HERE, "fixtures", "render")
SCHEMA_PATH = os.path.join(HERE, "..", "schemas", "render_model.schema.json")

CASES = [
    (os.path.join(FORMATS_DIR, "quick_brief.md"), "quick-brief"),
    (os.path.join(FORMATS_DIR, "comparison.md"), "comparison"),
    (os.path.join(FORMATS_DIR, "research_summary.md"), "research-summary"),
    (os.path.join(FORMATS_DIR, "discovery_catalog.md"), "discovery-catalog"),
    (os.path.join(HERE, "fixtures", "valid_report.md"), "comprehensive-report"),
]

MODEL_KEYS = [
    "title", "subtitle", "date", "format", "executive_summary", "key_stats",
    "sections", "findings", "contested_facets", "sources",
]


def validate_model(model):
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        schema = json.load(f)
    return schema_errors(schema, model)


def build(path, manifest=None, fmt=None):
    with open(path, encoding="utf-8") as f:
        return build_model(f.read(), manifest, fmt)


def test_model_builds_for_every_fixture():
    for path, fmt in CASES:
        model = build(path)
        assert sorted(model.keys()) == sorted(MODEL_KEYS), path
        assert model["title"], path
        assert model["format"] == fmt, (path, model["format"], fmt)
        assert model["sources"], path


def test_format_precedence():
    path = os.path.join(FORMATS_DIR, "research_summary.md")
    with open(os.path.join(RENDER_DIR, "manifest_format.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    assert build(path)["format"] == "research-summary"
    assert build(path, manifest)["format"] == "research-summary"
    assert build(path, manifest, fmt="quick-brief")["format"] == "quick-brief"
    assert build(path, fmt="comparison")["format"] == "comparison"


def test_date_from_manifest():
    path = os.path.join(FORMATS_DIR, "research_summary.md")
    with open(os.path.join(RENDER_DIR, "manifest_format.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    assert build(path)["date"] is None
    assert build(path, manifest)["date"] == "2026-10-02"


def test_each_model_passes_schema():
    for path, fmt in CASES:
        model = build(path)
        errors = validate_model(model)
        assert not errors, (path, errors)


def test_key_stats_verbatim_and_bounded():
    for path, fmt in CASES:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        model = build(path)
        assert len(model["key_stats"]) <= 6, path
        for stat in model["key_stats"]:
            assert stat["value"] in text, (path, stat)
            assert stat["label"], (path, stat)
            assert len(stat["label"].split()) >= 3, (path, stat)
            assert stat["ref"] is None or (
                f"[{stat['ref']}]" in text), (path, stat)


def test_stat_label_handles_quote_opened_before_value():
    sent = (
        'Google\'s launch post announced "a new, open protocol called '
        'Agent2Agent (A2A), with support and contributions from more than '
        '50 technology partners" in April 2025'
    )
    label = _stat_label(sent, "50 technology partners")
    assert label, "a2a-shaped sentence must yield a label"
    words = label.split()
    assert len(words) >= 3, label
    assert label.count('"') % 2 == 0, f"unbalanced quotes: {label!r}"
    assert label.count("(") == label.count(")"), label
    assert words[-1].lower() not in CONNECTOR_WORDS, label
    assert words[0].lower() not in CONNECTOR_WORDS, label
    assert "support" in words or "contributions" in words, label


def _edge_word(word):
    return word.strip(string.punctuation).lower()


def _normalize_sentence(sent):
    text = re.sub(r"\s*\[E:[^\]]*\]", "", strip_md(sent))
    return re.sub(r"\s*\[\d+\]", "", text)


def test_stat_captions_are_contiguous_source_phrases():
    """Every caption is one contiguous 3-8-word run of its source
    sentence (markdown and citation markers removed) — never words
    joined across the removed value — and never opens or closes on a
    connector."""
    for path, fmt in CASES:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
        model = build(path)
        for stat in model["key_stats"]:
            caption = re.sub(r"\s+", " ", stat["label"]).strip()
            words = caption.split()
            assert 3 <= len(words) <= 8, (path, stat, caption)
            assert _edge_word(words[0]) not in CONNECTOR_WORDS, (path, stat, caption)
            assert _edge_word(words[-1]) not in CONNECTOR_WORDS, (path, stat, caption)
            assert stat["value"] not in caption, (path, stat, caption)
            sources = []
            for line in lines:
                s = re.sub(r"^\s*[-*]\s+", "", line.strip())
                for sent in sentences(s):
                    norm = re.sub(r"\s+", " ", _normalize_sentence(sent))
                    if stat["value"] in norm:
                        sources.append(norm)
            assert sources, (path, stat, caption)
            assert any(caption in norm for norm in sources), \
                (path, stat, caption, sources)


def test_stat_label_not_spliced_across_value():
    """A value in the middle of its clause must not yield a caption
    spliced from the words on either side of it: the screen-time shape
    ('Among free of baseline symptoms') and the discovery shape
    ('GitHub mirror carries and a release')."""
    screen_time = (
        "Among 2,587 tenth-graders free of baseline symptoms, each "
        "additional high-frequency digital media activity raised the "
        "odds of later ADHD symptoms, OR 1.11, or 1.10 after covariate "
        "adjustment [5]."
    )
    label = _stat_label(screen_time, "2,587 tenth-graders")
    assert label == "tenth-graders free of baseline symptoms", label

    discovery = "The GitHub mirror carries 9,200 stars and a release this month [2]."
    label = _stat_label(discovery, "9,200 stars")
    assert label is None, label


def test_stat_label_strips_edge_punctuation_and_parenthetical():
    """The a2a shape: the span beside the value opens on a parenthetical
    fragment followed by a comma. The fragment and the dangling comma are
    stripped at the edge, the stopword trim and the 3-8-word rule are
    re-applied, and what survives must not start or end on punctuation,
    a bracket fragment, or a connector."""
    sent = (
        'Google\'s launch post announced "a new, open protocol called '
        'Agent2Agent (A2A), with support and contributions from more than '
        '50 technology partners" in April 2025'
    )
    label = _stat_label(sent, "50 technology partners")
    assert label == "support and contributions", label
    words = label.split()
    assert label[0] not in "([,;:.!?\"'", label
    assert label[-1] not in "([,;:.!?\"'", label
    assert _edge_word(words[0]) not in CONNECTOR_WORDS, label
    assert _edge_word(words[-1]) not in CONNECTOR_WORDS, label


def test_stat_dropped_when_no_clean_caption():
    """A sentence with no contiguous 3-8-word span beside the value
    yields no caption, and the stat is left out of the model rather
    than shown with a fragment."""
    sent = ("The largest meta-analysis, in JAMA Psychiatry in 2022, "
            "pooled 87 studies and 159,425 children [14].")
    assert _stat_label(sent, "87 studies") is None
    report = (
        "# Title\n\n"
        "## Summary\n\n" + sent + "\n\n"
        "## Key Findings\n\nSomething qualitative happened.\n\n"
        "## Bibliography\n\n[1] A (2024). Some publisher. J.\n"
    )
    model = build_model(report)
    values = [s["value"] for s in model["key_stats"]]
    assert "87 studies" not in values, values


def test_key_stats_skip_methodology_and_criteria():
    for path in (os.path.join(HERE, "fixtures", "valid_report.md"),
                 os.path.join(FORMATS_DIR, "discovery_catalog.md")):
        model = build(path)
        values = [s["value"] for s in model["key_stats"]]
        for banned in ("10 peer-reviewed sources", "3 independent sources", "300 stars"):
            assert banned not in values, (path, banned, values)


def test_bibliography_excluded_from_sections():
    for path, fmt in CASES:
        model = build(path)
        headings = {s["heading"].strip().lower() for s in model["sections"]}
        assert "bibliography" not in headings, path
        assert "sources" not in headings, path
        for section in model["sections"]:
            assert "bib-entry" not in section["html"], path
            assert "bibliography-content" not in section["html"], path
        ns = [s["n"] for s in model["sources"]]
        assert ns, path
        assert sorted(ns) == list(range(1, len(ns) + 1)), (path, ns)


def test_findings_extracted():
    rs = build(os.path.join(FORMATS_DIR, "research_summary.md"))
    assert len(rs["findings"]) >= 4, rs["findings"]
    assert rs["findings"][0]["refs"] == [1], rs["findings"][0]
    for f in rs["findings"]:
        assert f["headline"] and f["body"], f
        assert not re.match(r"(?i)^finding\s+\d+", f["headline"]), f["headline"]

    vr = build(os.path.join(HERE, "fixtures", "valid_report.md"))
    assert len(vr["findings"]) == 3, vr["findings"]
    assert vr["findings"][0]["refs"] == [1, 2, 3], vr["findings"][0]

    dc = build(os.path.join(FORMATS_DIR, "discovery_catalog.md"))
    assert len(dc["findings"]) >= 3, dc["findings"]


def test_contested_facets_from_manifest():
    with open(os.path.join(CONTESTED_DIR, "manifest_with_facets.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    model = build(os.path.join(CONTESTED_DIR, "report_with_perspectives.md"), manifest)
    assert len(model["contested_facets"]) == 2, model["contested_facets"]
    for facet in model["contested_facets"]:
        assert facet["facet"], facet
        assert len(facet["sides"]) >= 2, facet
        for side in facet["sides"]:
            assert side["label"], facet
            assert side["summary"], facet
    no_manifest = build(os.path.join(CONTESTED_DIR, "report_with_perspectives.md"))
    assert no_manifest["contested_facets"] == []


def test_facet_matching_survives_heading_rewording():
    """A manifest facet worded 'Alpha vs. beta: ...' must pair with a
    subsection headed 'Alpha versus beta' (vs-forms normalized, token
    overlap), carry the subsection's converted html, and extract one side
    per house-style paragraph — the substring match dropped this content
    and the sentence scan put both sides in one paragraph."""
    with open(os.path.join(RENDER_DIR, "facet_match_manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    model = build(os.path.join(RENDER_DIR, "facet_match_report.md"), manifest)
    assert not validate_model(model)
    assert len(model["contested_facets"]) == 1, model["contested_facets"]
    facet = model["contested_facets"][0]
    assert facet["html"], facet
    for needle in ("heavier alpha exposure tracks more beta problems",
                   "vanishes under controls for household factors"):
        assert needle in facet["html"], (needle, facet["html"])
    # one side per paragraph, 'X case' labels, each summary from its own paragraph
    sides = facet["sides"]
    assert len(sides) == 2, sides
    assert [s["label"] for s in sides] == ["Alpha-causation case", "Confounded-record case"], sides
    para1_only = "consistent direction across instruments"
    para2_only = "household factors and reverse causation"
    assert para1_only in sides[0]["summary"] and para2_only not in sides[0]["summary"], sides
    assert para2_only in sides[1]["summary"] and para1_only not in sides[1]["summary"], sides
    for side in sides:
        assert side["summary"], side


def test_facet_positional_fallback_when_counts_agree():
    """No token overlap, but facet count equals subsection count: the facet
    still matches positionally and carries the subsection's html."""
    report = (
        "# T\n\n"
        "## Perspectives\n\n"
        "### One completely different label\n\n"
        "The strongest case for x harm assembles the cohorts [1]. "
        "The strongest case for y null assembles the reanalyses [2].\n\n"
        "## Bibliography\n\n[1] A (2024). S1. J.\n[2] B (2023). S2. J.\n"
    )
    model = build_model(report, {"contested_facets": ["Speed of light: is it constant?"]})
    facet = model["contested_facets"][0]
    assert facet["html"], facet
    assert len(facet["sides"]) >= 2, facet


def test_sections_html_converted():
    for path, fmt in CASES:
        model = build(path)
        assert model["sections"], path
        for section in model["sections"]:
            assert section["level"] in (2, 3), (path, section)
            assert "<" in section["html"], (path, section["heading"])


BIB_RULE_REPORT = os.path.join(RENDER_DIR, "bibliography_rule_report.md")


def test_lowercase_sources_heading_stays_body_section():
    """The helper's heading rule is case-sensitive: '## sources' is a body
    section and nothing from it reaches model['sources'] (fails on
    4ce5be8, where BIBLIOGRAPHY_HEADINGS matched case-insensitively)."""
    model = build(BIB_RULE_REPORT)
    sec = next(s for s in model["sections"] if s["heading"] == "sources")
    assert "stays a body section under the case-sensitive rule" in sec["html"]
    joined = " ".join(s["title"] for s in model["sources"])
    assert "stays a body section" not in joined
    # Alone in a report, it is still only a section, never a bibliography.
    model = build_model(
        "# T\n\n## sources\n\nBody of the sources section [1].\n"
    )
    assert [s["heading"] for s in model["sections"]] == ["sources"]
    assert model["sources"] == []


def test_exact_capitalised_sources_heading_starts_bibliography():
    report = (
        "# T\n\n## Body\n\nText [1].\n\n"
        "## Sources\n\n[1] A (2024). \"S\". https://e.com/s\n"
    )
    model = build_model(report)
    assert [s["heading"] for s in model["sections"]] == ["Body"]
    assert [s["n"] for s in model["sources"]] == [1]


def test_fenced_bibliography_heading_does_not_start_bibliography():
    """A '## Bibliography' line inside a code fence is body content: it
    neither starts the bibliography nor becomes a model section."""
    with open(BIB_RULE_REPORT, encoding="utf-8") as f:
        parsed = parse_report(f.read())
    summary = next(s for s in parsed["sections"] if s["heading"] == "Summary")
    assert any("## Bibliography" in line for line in summary["lines"])
    headings = {s["heading"] for s in parsed["sections"]}
    assert "Bibliography" not in headings
    model = build(BIB_RULE_REPORT)
    assert [s["n"] for s in model["sources"]][:5] == [1, 2, 3, 4, 5]
    joined = " ".join(s["html"] for s in model["sections"])
    assert "arxiv.org/abs/2305.14251" not in joined


def test_export_format_entries_parse_clean():
    """Epic 1's export format '[N] Author (Year). "Title". URL': the right
    title and URL, publisher None for every author shape — never
    '& Park, M' or 'Org (n.d.)' (fails on 4ce5be8)."""
    model = build(BIB_RULE_REPORT)
    by_n = {s["n"]: s for s in model["sources"]}
    assert by_n[1] == {
        "n": 1, "title": "FActScore",
        "url": "https://arxiv.org/abs/2305.14251", "publisher": None,
    }
    assert by_n[2]["title"] == "Feedback frequency for stable curricula"
    assert by_n[2]["publisher"] is None
    assert by_n[2]["url"] == "https://example.com/gamma"
    assert by_n[3] == {
        "n": 3, "title": "Anonymous field notes on spacing",
        "url": "https://example.com/anon", "publisher": None,
    }
    for src in model["sources"]:
        assert src["publisher"] not in ("& Park, M", "Gamma Teaching Quarterly (n.d.)",
                                        "(n.d.)"), src


def test_export_title_with_internal_period_or_quotes():
    """A quoted title containing '. ' splits the naive segment scan, and
    inner quote marks must stay in the title (the period case fails on
    4ce5be8 with a truncated quoted-title and 'question\"' as publisher).
    A title holding '"X". ' runs to the last closing quote, never
    'Intro to "X' with 'Part 2"' as publisher."""
    model = build(BIB_RULE_REPORT)
    by_n = {s["n"]: s for s in model["sources"]}
    assert by_n[4]["title"] == "Retention, pace, and the 3 p.m. question"
    assert by_n[4]["publisher"] is None
    assert by_n[5]["title"] == 'The "A2A" protocol survey'
    assert by_n[5]["publisher"] is None
    assert by_n[6] == {
        "n": 6, "title": 'Intro to "X". Part 2',
        "url": "https://example.com/intro", "publisher": None,
    }


def test_old_quoted_form_keeps_publisher():
    """'Author, I. (Year). \"Title\". Publisher. URL' keeps its publisher
    (it sits after the quoted title) and unquoted forms are unchanged."""
    sources = build_sources(
        '[1] Smith, J. (2025). "Test Research Advances". Journal of Testing. '
        'https://example.com/paper1\n'
        '[2] Author, D. (2023). Structured phonics sequences in early '
        'intervention. Reading Research Annual.\n'
        '[3] GitHub. Joplin repo metrics, retrieved 2026-10-06. '
        'https://github.com/laurent22/joplin\n'
    )
    assert sources[0]["title"] == "Test Research Advances"
    assert sources[0]["publisher"] == "Journal of Testing"
    assert sources[1]["title"] == "Structured phonics sequences in early intervention"
    assert sources[1]["publisher"] == "Reading Research Annual"
    assert sources[2]["title"] == "Joplin repo metrics, retrieved 2026-10-06"
    assert sources[2]["publisher"] == "GitHub"


def test_bibliography_notes_kept_unnumbered():
    """Non-entry lines in the bibliography are authored words: they reach
    the model as unnumbered bib_notes, placed after the rows that preceded
    them; only blank lines and thematic rules drop (fails on 4ce5be8,
    which skipped every non-entry line). A note never takes a number, so
    it can never be mistaken for, or shadow, a cited source."""
    model = build(BIB_RULE_REPORT)
    assert model["bib_notes"] == [
        {"text": "All URLs verified March 2026.", "after": 6},
        {"text": "Primary sources", "after": 6},
    ]
    titles = [s["title"] for s in model["sources"]]
    assert "All URLs verified March 2026." not in titles
    assert "Primary sources" not in titles
    assert "---" not in titles
    assert not any(n["text"] == "---" for n in model["bib_notes"])
    # A report with no notes carries no bib_notes key (models unchanged).
    plain = build_model("# T\n\n## Bibliography\n\n[1] A (2024). \"S\". https://e.com/a\n")
    assert "bib_notes" not in plain


def test_note_before_link_entries_does_not_shift_numbers():
    """A lead-in line above link-form entries must not take [1]: body
    citations [1]/[2] point at the link entries, as on 4ce5be8."""
    sources, notes = build_bibliography(
        "The following were consulted:\n\n"
        "- [Alpha study](https://a.org)\n- [Beta study](https://b.org)\n"
    )
    assert [(s["n"], s["title"]) for s in sources] == [
        (1, "Alpha study"), (2, "Beta study")]
    assert notes == [{"text": "The following were consulted:", "after": 0}]


def test_link_entries_autonumber_past_entries():
    """A markdown link entry beside '[N]' entries gets an auto number
    past the last real one — never a duplicate n (4ce5be8 restarted at 1
    and collided with entry [1])."""
    model = build(BIB_RULE_REPORT)
    glossary = next(s for s in model["sources"] if s["title"] == "Glossary")
    assert glossary == {
        "n": 7, "title": "Glossary",
        "url": "https://example.com/glossary", "publisher": None,
    }
    ns = [s["n"] for s in model["sources"]]
    assert ns == [1, 2, 3, 4, 5, 6, 7], ns
    sources = build_sources(
        '[1] A (2024). "S". https://e.com/a\n- [Extra](https://e.com/x)\n'
    )
    assert [s["n"] for s in sources] == [1, 2]


def test_report_renders_bib_notes_unnumbered():
    """render_report places each note in order, with no [N] and no ref-N
    anchor, so in-text citations only ever link to real entries."""
    from render_report import render_report
    model = build(BIB_RULE_REPORT)
    html = render_report(model)
    bib = html[html.index('id="refs"'):]
    assert '<p class="rf-ref-note">All URLs verified March 2026.</p>' in bib
    assert '<p class="rf-ref-note">Primary sources</p>' in bib
    assert bib.index('id="ref-6"') < bib.index("All URLs verified") \
        < bib.index("Primary sources") < bib.index('id="ref-7"')
    assert re.findall(r'id="ref-(\d+)"', bib) == [str(n) for n in range(1, 8)]
    assert "[8]" not in bib


def test_post_bibliography_sections_stay_in_body():
    model = build(BIB_RULE_REPORT)
    headings = [s["heading"] for s in model["sections"]]
    assert headings[-1] == "Appendix: After the Bibliography"
    assert "Post-bibliography sections stay in the body" in model["sections"][-1]["html"]


def test_bibliography_rule_fixture_model_passes_schema():
    model = build(BIB_RULE_REPORT)
    errors = validate_model(model)
    assert not errors, errors


LINK_FIDELITY_REPORT = os.path.join(RENDER_DIR, "link_fidelity_report.md")


def test_strip_md_keeps_link_urls_every_scheme():
    """Plain-text contexts keep a link's URL beside its text for every
    scheme (E2-R3): the summary, findings, bullets and stat captions
    never collapse a link to bare text (fails on 164ef39)."""
    text = ("See the [protocol](https://e.com/p?a=1&b=2), the [mirror](http://e.com/m), "
            "the [hook](javascript:alert(1)) and a [note](../drafts/n.md).")
    out = strip_md(text)
    assert "protocol (https://e.com/p?a=1&b=2)" in out
    assert "mirror (http://e.com/m)" in out
    assert "hook (javascript:alert(1))" in out
    assert "note (../drafts/n.md)" in out
    assert "](" not in out


def test_link_fidelity_fixture_keeps_urls_in_plain_text_paths():
    """The summary paragraphs, finding bodies and stat captions of the
    link-fidelity fixture each keep every link's URL as 'text (URL)'
    (fails on 164ef39, where strip_md dropped the URL)."""
    model = build(LINK_FIDELITY_REPORT)
    assert model["format"] == "research-summary"
    summary = " ".join(model["executive_summary"])
    assert "protocol page (https://example.com/protocol)" in summary
    assert "mirror (http://example.com/mirror)" in summary
    assert "demo hook (javascript:alert(1))" in summary
    assert "cohort registry (https://example.com/registry)" in summary
    bodies = " ".join(f["body"] for f in model["findings"])
    assert "release note (https://example.com/release)" in bodies
    assert "insecure mirror (http://example.com/insecure)" in bodies
    assert "script link (javascript:alert(1))" in bodies
    labels = " ".join(s["label"] for s in model["key_stats"])
    assert "(https://example.com/registry)" in labels
    assert "](http" not in bodies and "](https" not in bodies
    assert "](javascript" not in summary + bodies


if __name__ == "__main__":
    test_model_builds_for_every_fixture()
    test_format_precedence()
    test_date_from_manifest()
    test_each_model_passes_schema()
    test_key_stats_verbatim_and_bounded()
    test_stat_label_handles_quote_opened_before_value()
    test_stat_captions_are_contiguous_source_phrases()
    test_stat_label_not_spliced_across_value()
    test_stat_label_strips_edge_punctuation_and_parenthetical()
    test_stat_dropped_when_no_clean_caption()
    test_key_stats_skip_methodology_and_criteria()
    test_bibliography_excluded_from_sections()
    test_findings_extracted()
    test_contested_facets_from_manifest()
    test_facet_matching_survives_heading_rewording()
    test_facet_positional_fallback_when_counts_agree()
    test_sections_html_converted()
    test_lowercase_sources_heading_stays_body_section()
    test_exact_capitalised_sources_heading_starts_bibliography()
    test_fenced_bibliography_heading_does_not_start_bibliography()
    test_export_format_entries_parse_clean()
    test_export_title_with_internal_period_or_quotes()
    test_old_quoted_form_keeps_publisher()
    test_bibliography_notes_kept_unnumbered()
    test_note_before_link_entries_does_not_shift_numbers()
    test_link_entries_autonumber_past_entries()
    test_report_renders_bib_notes_unnumbered()
    test_post_bibliography_sections_stay_in_body()
    test_bibliography_rule_fixture_model_passes_schema()
    test_strip_md_keeps_link_urls_every_scheme()
    test_link_fidelity_fixture_keeps_urls_in_plain_text_paths()
    print("all 31 render-model tests ran and passed")
