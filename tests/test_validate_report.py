"""Known-answer tests for validate_report's bibliography adoption and
facet coverage (E1-R2, E1-R3): uncited entries, bracketed years,
appendix citations, the '## Sources' alias, and code-span exclusion."""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures", "validate_report")
SCRIPT = os.path.join(HERE, "..", "scripts", "validate_report.py")


def run(report, fmt="comprehensive-report", manifest=None):
    cmd = [sys.executable, SCRIPT, "--report", os.path.join(FIX, report),
           "--format", fmt]
    if manifest:
        cmd += ["--manifest", os.path.join(FIX, manifest)]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_uncited_entry_fails_naming_entry():
    r = run("report_uncited_entry.md")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "Uncited bibliography entries (never cited in the body): [4]" in r.stdout, \
        "the uncited entry [4] must be named in the errors"


def test_year_brackets_are_not_citations():
    r = run("report_year_brackets.md")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "2024" not in "".join(
        l for l in r.stdout.splitlines() if "citations" in l.lower()
    ), "a bracketed year in prose must never be treated as a citation"


def test_appendix_citation_counts_as_cited():
    r = run("report_appendix_citation.md")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Uncited" not in r.stdout, \
        "a [4] cited in a post-bibliography appendix is cited in the body"


def test_uncovered_facet_fails_naming_facet():
    r = run("report_uncovered_facet.md", manifest="manifest_two_facets.json")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "Perspectives section does not cover listed contested facets" in r.stdout
    assert "replication across cohorts" in r.stdout, \
        "the uncovered facet must be named in the error"


def test_covered_facet_passes():
    r = run("report_uncovered_facet.md", manifest="manifest_one_facet.json")
    assert r.returncode == 0, r.stdout + r.stderr


def test_no_positional_fallback():
    """Two listed facets and two unrelated subsections must NOT pass: the
    matcher has no positional fallback (F3's defect class)."""
    text = open(os.path.join(FIX, "report_uncovered_facet.md")).read()
    persp = (
        "## Perspectives on the Contested Facets\n\n"
        "### The harm camp\n\nCase one [1].\n\n"
        "### The null camp\n\nCase two [2].\n\n"
    )
    assert "## Perspectives on the Contested Facets" in text
    body = text.replace(
        "## Perspectives on the Contested Facets\n\n"
        "### Facet: effect size of screen time on attention\n\n"
        "The strongest case for real harm assembles the cohort evidence "
        "with consistent direction across instruments [1]. The strongest "
        "case for null assembles the controlled studies where effects "
        "vanish under covariate adjustment [2].\n\n",
        persp,
    )
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(body)
        path = f.name
    try:
        r = subprocess.run(
            [sys.executable, SCRIPT, "--report", path,
             "--format", "comprehensive-report",
             "--manifest", os.path.join(FIX, "manifest_two_facets.json")],
            capture_output=True, text=True,
        )
        assert r.returncode == 1, r.stdout + r.stderr
        assert "does not cover" in r.stdout
        assert "effect size of screen time on attention" in r.stdout
        assert "replication across cohorts" in r.stdout
    finally:
        os.unlink(path)


def test_sources_alias_bibliography_parses():
    """'## Sources' is a bibliography per the shared rule (E1-R1): its
    entries parse and every-entry-cited runs. The report still fails the
    section gate (which wants a 'Bibliography' heading), never with
    'Missing 'Bibliography' section' or an uncited/gap error."""
    src = open(os.path.join(HERE, "fixtures", "formats", "quick_brief.md")).read()
    body = src.split("## Bibliography")[0]
    bib = ("## Sources\n"
           "[1] Author, A. (2024). One. Journal.\n"
           "- [2] Author, B. (2023). Two. Journal.\n"
           "* [3] Author, C. (2022). Three. Journal.\n")
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(body + bib)
        path = f.name
    try:
        r = subprocess.run(
            [sys.executable, SCRIPT, "--report", path, "--format", "quick-brief"],
            capture_output=True, text=True,
        )
        assert r.returncode == 1, "the section gate must still fail (no Bibliography heading)"
        assert "Missing sections" in r.stdout
        assert "Missing 'Bibliography' section" not in r.stdout
        assert "Uncited bibliography entries" not in r.stdout
        assert "gaps in numbering" not in r.stdout
    finally:
        os.unlink(path)


def test_code_span_citation_not_counted():
    """A citation inside a code span is not a body citation, so its entry
    must surface as uncited (shared rule: code excluded)."""
    src = open(os.path.join(FIX, "report_uncited_entry.md")).read()
    body = src.replace(
        "A third cohort series reports intermediate effects that shrink "
        "with better controls [3].",
        "A third cohort series reports intermediate effects that shrink "
        "with better controls `[3]`.",
    )
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(body)
        path = f.name
    try:
        r = subprocess.run(
            [sys.executable, SCRIPT, "--report", path,
             "--format", "comprehensive-report"],
            capture_output=True, text=True,
        )
        assert r.returncode == 1, r.stdout + r.stderr
        assert "never cited in the body): [3], [4]" in r.stdout
    finally:
        os.unlink(path)


def test_body_phrase_needs_whole_tokens():
    """A substring crossing token boundaries is not coverage: prose about
    'screen timeout policies' must not cover the facet 'screen time'."""
    text = open(os.path.join(FIX, "report_uncovered_facet.md")).read()
    body = text.replace(
        "### Facet: effect size of screen time on attention\n\n"
        "The strongest case for real harm assembles the cohort evidence "
        "with consistent direction across instruments [1]. The strongest "
        "case for null assembles the controlled studies where effects "
        "vanish under covariate adjustment [2].",
        "### The camps\n\n"
        "Screen timeout policies varied by district, and the camps read "
        "the same cohorts differently [1] [2].",
    )
    assert body != text, "fixture drift: perspectives subsection not found"
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(body)
        path = f.name
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        f.write('{"version": "1.0", "query": "q", "mode": "deep", '
                '"contested_facets": ["screen time"]}')
        mpath = f.name
    try:
        r = subprocess.run(
            [sys.executable, SCRIPT, "--report", path,
             "--format", "comprehensive-report", "--manifest", mpath],
            capture_output=True, text=True,
        )
        assert r.returncode == 1, r.stdout + r.stderr
        assert "does not cover" in r.stdout and "screen time" in r.stdout
    finally:
        os.unlink(path)
        os.unlink(mpath)


def _uncovered(facets, headings, text=""):
    sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
    from validate_report import ReportValidator
    return ReportValidator._uncovered_facets(facets, text, headings)


def test_facet_label_covers_paraphrased_facet():
    """Real-report shape (a11y and PS runs, 2026-10/11): a long question-
    form facet, paraphrased in a '### Facet N:' heading, is covered by its
    explicit ordinal label. Unlabelled, the same paraphrase is not."""
    facet = ("Whether a PlayStation can join the home server with NO inbound "
             "port and NO third-party tunnel by riding Xbox Live / NetherNet "
             "relays (community hope vs. documented NetherNet architecture)")
    other = "Whether playit.gg's free tier is sound as the primary exposure"
    heads = ["Facet 1: Can Xbox Live relays replace the public endpoint entirely?",
             "Facet 2: Is playit.gg's free tier sound as the primary exposure?"]
    assert _uncovered([facet, other], heads) == []
    assert _uncovered([facet, other],
                      [h.split(": ", 1)[1] for h in heads]) == [facet]


def test_facet_parenthetical_gloss_ignored():
    """A '(x vs y framings)' gloss frames the sides; it is not part of the
    facet's name, so a heading naming the facet covers it."""
    facet = ("How much of WCAG conformance automated testing covers "
             "(issue-volume vs criterion-coverage framings)")
    assert _uncovered([facet], ["How much of WCAG conformance can "
                                "automated testing cover?"]) == []


def test_one_heading_covers_one_facet():
    """Two facets differing in one key word and one heading for only one
    of them: the other stays uncovered (no double counting)."""
    facets = ["Economic impact on workers", "Economic impact on consumers"]
    assert _uncovered(facets, ["Economic impact on consumers"]) == \
        ["Economic impact on workers"]
    assert _uncovered(facets, ["Economic impact on consumers",
                               "Economic impact on workers"]) == []


def test_out_of_range_or_duplicate_label_does_not_cover():
    assert _uncovered(["Alpha topic", "Beta topic"],
                      ["Facet 3: x", "Facet 1: y"]) == ["Beta topic"]
    assert _uncovered(["Alpha topic", "Beta topic"],
                      ["Facet 1: x", "Facet 1: y"]) == ["Beta topic"]


def test_facet_label_end_to_end_and_hint():
    """Through the CLI: '### Facet 2:' covers the second facet; without
    it, the error names the facet and says how to label it."""
    text = open(os.path.join(FIX, "report_uncovered_facet.md")).read()
    add = ("### Facet 2: Do the cohorts agree with each other?\n\n"
           "The replication camp's strongest case rests on the second cohort [2].\n\n"
           "## Limitations")
    body = text.replace("## Limitations", add, 1)
    assert body != text, "fixture drift: Limitations heading not found"
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(body)
        path = f.name
    try:
        r = subprocess.run(
            [sys.executable, SCRIPT, "--report", path,
             "--format", "comprehensive-report",
             "--manifest", os.path.join(FIX, "manifest_two_facets.json")],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, r.stdout + r.stderr
    finally:
        os.unlink(path)
    r = run("report_uncovered_facet.md", manifest="manifest_two_facets.json")
    assert "labelled '### Facet N: ...' in manifest order" in r.stdout


if __name__ == "__main__":
    test_uncited_entry_fails_naming_entry()
    test_year_brackets_are_not_citations()
    test_appendix_citation_counts_as_cited()
    test_uncovered_facet_fails_naming_facet()
    test_covered_facet_passes()
    test_no_positional_fallback()
    test_sources_alias_bibliography_parses()
    test_code_span_citation_not_counted()
    test_body_phrase_needs_whole_tokens()
    test_facet_label_covers_paraphrased_facet()
    test_facet_parenthetical_gloss_ignored()
    test_one_heading_covers_one_facet()
    test_out_of_range_or_duplicate_label_does_not_cover()
    test_facet_label_end_to_end_and_hint()
    print("all 14 validate_report tests ran and passed")
