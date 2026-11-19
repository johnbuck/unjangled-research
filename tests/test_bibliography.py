"""Unit tests for scripts/bibliography.py — the shared bibliography rule (E1-R1).

Every entry form and the code-span exclusion are covered, plus the two
views (density window vs reader-facing) and the section-end rule.
"""
import sys

sys.path.insert(0, "scripts")
from bibliography import (
    BIB_HEADING_RE,
    body_before_bibliography,
    count_refs,
    extract_citations,
    mask_code,
    parse_entries,
    reader_facing_text,
    split_bibliography,
    strip_code,
)

FIX = "tests/fixtures/bibliography"


def test_no_bibliography():
    text = "# T\n\n## Finding\n\nPlain body prose with a citation [1].\n"
    before, section = split_bibliography(text)
    assert section is None, "no heading means no bibliography"
    assert before == text
    assert body_before_bibliography(text) == text
    assert reader_facing_text(text) == text


def test_heading_must_be_exact():
    not_a_start = [
        "### Sources of funding",       # three hashes
        "## Sources of funding",        # trailing words
        "## Bibliography of classics",  # trailing words
        "#### Bibliography",            # four hashes
        "##Bibliography",               # no space after hashes
        "Text mentioning ## Bibliography mid-line",  # not at line start
    ]
    for line in not_a_start:
        assert BIB_HEADING_RE.search(line) is None, f"must not match: {line!r}"
        text = f"# T\n\n## Finding\n\nBody [1].\n\n{line}\n\n[1] Entry.\n"
        assert split_bibliography(text)[1] is None, f"must not split at: {line!r}"


def test_heading_allows_trailing_spaces_and_alias():
    for heading in ("## Bibliography", "## Sources", "## Bibliography  ", "## Sources\t"):
        text = f"# T\n\nBody [1].\n\n{heading}\n\n[1] Entry.\n"
        before, section = split_bibliography(text)
        assert section is not None, f"must split at: {heading!r}"
        assert "[1] Entry." in section


def test_crlf_heading_matches():
    text = "# T\r\n\r\n## Body\r\n\r\nProse [1].\r\n\r\n## Bibliography\r\n\r\n[1] Entry.\r\n"
    before, section = split_bibliography(text)
    assert section is not None and "[1] Entry." in section
    assert "Prose [1]." in before


def test_fence_inside_bibliography_does_not_end_section():
    doc = (
        "# T\n\n## Body\n\nProse [1].\n\n## Bibliography\n\n[1] A.\n\n"
        "```\n## Example heading inside a fence\n```\n\n[2] B.\n"
    )
    before, section = split_bibliography(doc)
    assert "[2] B." in section, "a '## ' line inside a fence must not end the section"
    assert "[2] B." not in reader_facing_text(doc)
    assert "[1] A." not in reader_facing_text(doc)


def test_fence_in_body_does_not_start_bibliography():
    doc = (
        "# T\n\n## Body\n\nExample format:\n\n```\n## Bibliography\n[1] Sample.\n```\n\n"
        "Real prose continues here [1].\n\n## Bibliography\n\n[1] A.\n"
    )
    before, section = split_bibliography(doc)
    assert "Real prose continues" in before, "a fenced example must not start the split"
    assert "[1] Sample." not in section, "fenced sample entries are not bibliography"
    assert "[1] A." in section


def test_tab_separated_atx_headings():
    doc = "# T\n\n## Body\n\nProse [1].\n\n##\tBibliography\n\n[1] A.\n\n##\tAppendix\n\nKeep.\n"
    before, section = split_bibliography(doc)
    assert section is not None and "[1] A." in section
    assert "Keep." not in section, "a tab-form '##' heading still ends the section"
    assert "Keep." in reader_facing_text(doc)
    assert "Keep." not in body_before_bibliography(doc)


def test_section_runs_to_eof_when_last():
    text = "# T\n\n## Body\n\nProse [1].\n\n## Bibliography\n\n[1] Entry.\n"
    before, section = split_bibliography(text)
    assert "Prose [1]." in before and "[1] Entry." not in before
    assert section is not None and "[1] Entry." in section
    assert body_before_bibliography(text) == before
    assert reader_facing_text(text) == before, "bib last: reader-facing is the body only"


def test_section_ends_at_next_h2_and_appendix_kept():
    text = (
        "# T\n\n## Body\n\nProse [1].\n\n## Bibliography\n\n[1] Entry.\n\n"
        "### Note inside\n\nNote text [2].\n\n## Appendix\n\nAppendix text [3].\n"
    )
    before, section = split_bibliography(text)
    assert "[1] Entry." in section and "Note text [2]." in section, (
        "only a '## ' heading ends the section; '###' does not"
    )
    assert "Appendix text" not in section
    rf = reader_facing_text(text)
    assert "Prose [1]." in rf and "Appendix text [3]." in rf
    assert "[1] Entry." not in rf and "Note text [2]." not in rf
    assert "Appendix text" not in body_before_bibliography(text)


def test_parse_entry_forms():
    section = (
        "[1] Alpha Org (2024). First. https://example.com/a\n"
        "- [2] Beta Org (2024). Second. https://example.com/b\n"
        "* [3] Gamma Org (2024). Third. https://example.com/c\n"
        "  [4] Indented entry (2024). Fourth.\n"
    )
    entries = parse_entries(section)
    assert [n for n, _ in entries] == [1, 2, 3, 4]
    assert entries[0][1] == "Alpha Org (2024). First. https://example.com/a"
    assert entries[1][1] == "Beta Org (2024). Second. https://example.com/b"


def test_parse_skips_non_entries():
    section = (
        "\n[1] Real entry.\n\n---\n\n### A subsection note\n\n"
        "Prose line without a marker.\n[1234] Four digits is not an entry.\n"
    )
    entries = parse_entries(section)
    assert entries == [(1, "Real entry.")]


def test_extract_citations_forms_and_order():
    text = "First [1] then a comma chain [2, 3] and a tight one [4,5] at the end [12]."
    assert extract_citations(text) == [1, 2, 3, 4, 5, 12]


def test_year_and_long_numbers_not_citations():
    assert extract_citations("Published [2024] and arXiv [2401.12345] too.") == []
    assert count_refs("The paper [2024] says little.") == 0


def test_inline_code_spans_excluded():
    text = "Real [1] but hidden `see [7]` and ``double tick [8]``."
    assert extract_citations(text) == [1]


def test_unmatched_backtick_is_prose():
    # A lone backtick has no closing partner: it renders literally, so a
    # citation after it stays in prose and counts.
    text = "Lone ` backtick keeps [9] visible as prose."
    assert extract_citations(text) == [9]


def test_fenced_blocks_excluded():
    text = "Real [1].\n\n```\ncode block citation [9] must not count\n```\n\nMore [2]."
    assert extract_citations(text) == [1, 2]
    tildes = "Real [1].\n\n~~~\ncitation [9] hidden\n~~~\n"
    assert extract_citations(tildes) == [1]


def test_unclosed_fence_runs_to_eof():
    text = "Real [1].\n\n```\nunclosed fence swallows [9] and [10] forever"
    assert extract_citations(text) == [1]


def test_strip_code_keeps_prose():
    text = "keep `drop` keep\n\n```\ndrop all\n```\n\nkeep"
    out = strip_code(text)
    assert "keep" in out and "drop" not in out


def test_mask_code_preserves_offsets_and_hides_code():
    """mask_code excludes the same code as strip_code but keeps every
    offset: same length, newlines in place, prose untouched, so a match
    found on the masked text slices the original at the same position."""
    text = (
        "Prose [1] with `inline [2]` span.\n\n"
        "```\nfenced [3]\n`unpaired\n```\n\n"
        "Tail [4] and ``double [5] tick`` end.\n"
    )
    masked = mask_code(text)
    assert len(masked) == len(text)
    assert [i for i, c in enumerate(masked) if c == "\n"] == [
        i for i, c in enumerate(text) if c == "\n"
    ], "newlines stay where they were"
    assert extract_citations(masked) == extract_citations(text) == [1, 4]
    import re
    for m in re.finditer(r"\[(\d)\]", masked):
        assert text[m.start():m.end()] == m.group(0), "offsets map to the original"
    assert "inline" not in masked and "fenced" not in masked and "double" not in masked
    assert masked.startswith("Prose [1] with ") and "Tail [4] and " in masked
    # The fence's stray backtick must not pair with a span outside it.
    assert "`unpaired" not in masked


def test_mask_code_unclosed_fence_masks_to_eof():
    text = "Real [1].\n\n```\nunclosed [9]"
    masked = mask_code(text)
    assert len(masked) == len(text) and extract_citations(masked) == [1]


def test_count_refs_matches_extract():
    s = "One sentence citing several works [1, 2] plus another [3]."
    assert count_refs(s) == len(extract_citations(s)) == 3


def test_funding_fixture_split():
    """The verify scenario: '### Sources of funding' is body, not a split point."""
    text = open(f"{FIX}/funding_subsection_report.md").read()
    before, section = split_bibliography(text)
    assert section is not None, "real '## Bibliography' must be found"
    assert "### Sources of funding" in before
    assert "Matching gift programs" in before, "funding subsection content is body"
    assert "[1] Alpha Institute" in section and "Alpha Institute" not in before
    assert reader_facing_text(text) == before, "bib is last: nothing follows it"


def test_entry_forms_fixture():
    text = open(f"{FIX}/entry_forms_report.md").read()
    before, section = split_bibliography(text)
    assert "## Sources" not in before and "Body prose" in before
    entries = dict(parse_entries(section))
    assert sorted(entries) == [1, 2, 3]
    assert entries[2].startswith("Beta Org")
    assert "Curated note" in section, "'###' must not end the sources section"
    rf = reader_facing_text(text)
    assert "Post-bibliography appendix material" in rf
    assert "Curated note" not in rf, "in-section notes are dropped as bibliography"
    assert "Appendix" not in body_before_bibliography(text)


def test_code_fixture_document():
    text = open(f"{FIX}/code_citations.md").read()
    assert extract_citations(text) == [1, 2, 3, 4]
    assert count_refs(text) == 4


def test_crlf_fence_closes_and_bibliography_still_splits():
    """Review fix: a CRLF closing fence must close, or the fence mask runs
    to EOF and hides the bibliography heading (entries become body)."""
    text = (
        "Body [1].\r\n```\r\ncode [9]\r\n```\r\nMore prose [2].\r\n"
        "## Bibliography\r\n[1] A\r\n[2] B\r\n## Appendix\r\nApp.\r\n"
    )
    before, section = split_bibliography(text)
    assert section is not None, "CRLF fence must not mask the heading"
    assert "More prose [2]." in before
    assert parse_entries(section) == [(1, "A"), (2, "B")]
    assert "App." in reader_facing_text(text)
    assert extract_citations(before) == [1, 2], "fenced [9] still excluded"


def test_first_bibliography_heading_wins():
    """Two bibliography headings: the first is the bibliography; a later
    '## Sources' is an ordinary section (kept in reader-facing text)."""
    text = "Body [1].\n## Bibliography\n[1] A\n## Sources\n[2] B\n"
    before, section = split_bibliography(text)
    assert before == "Body [1].\n"
    assert parse_entries(section) == [(1, "A")]
    assert "[2] B" in reader_facing_text(text)


def test_sources_consulted_is_body():
    """discovery-catalog prescribes a '## Sources Consulted' audit-trail
    section before '## Bibliography'; it is body prose, not a bibliography."""
    text = (
        "Body.\n## Sources Consulted\nEnumerated lists [6] [7].\n"
        "## Bibliography\n[6] A\n[7] B\n"
    )
    before = body_before_bibliography(text)
    assert "Enumerated lists [6] [7]." in before
    assert extract_citations(before) == [6, 7]


def test_ranges_and_other_separators_not_citations():
    """Ranges are forbidden by reference/quality-gates.md and appear in
    templates only as placeholders ('[3-5 areas ...]'); they are not
    citations. Only '[N]' and comma chains count."""
    for t in ("[3-5]", "[3\u20135]", "[3; 4]", "[ 3 ]", "[3, 2024]"):
        assert extract_citations(t) == [], t
    assert extract_citations("[1][2] and [3, 4]") == [1, 2, 3, 4]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"all {len(tests)} bibliography tests ran and passed")
