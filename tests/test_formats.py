"""Format-aware verification: each template's fixture passes its own
format's validation, readability gate, HTML conversion, and claim
extraction — and fails comprehensive-format validation (proving the
validator actually distinguishes formats)."""
import subprocess
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures", "formats")

CASES = [
    ("quick_brief.md", "quick-brief"),
    ("comparison.md", "comparison"),
    ("research_summary.md", "research-summary"),
]


def run_validator(fixture, fmt):
    r = subprocess.run(
        [sys.executable, os.path.join(HERE, "..", "scripts", "validate_report.py"),
         "--report", os.path.join(FIXTURES, fixture), "--format", fmt],
        capture_output=True, text=True,
    )
    return r.returncode == 0


def test_each_fixture_passes_own_format():
    for fixture, fmt in CASES:
        assert run_validator(fixture, fmt), f"{fixture} must pass as {fmt}"


def test_each_fixture_fails_comprehensive_default():
    for fixture, fmt in CASES:
        assert not run_validator(fixture, "comprehensive-report"), (
            f"{fixture} must FAIL comprehensive validation — otherwise the "
            f"format-awareness is not discriminating"
        )


def test_readability_gate_passes_each_format():
    sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
    from readability_check import measure, evaluate
    for fixture, fmt in CASES:
        m = measure(open(os.path.join(FIXTURES, fixture)).read())
        fails, warns, advisories = evaluate(m)
        assert not fails, f"{fixture}: {fails}"


def test_html_conversion_each_format():
    sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
    from md_to_html import convert_markdown_to_html
    markers = {
        "quick_brief.md": "Key Points",
        "comparison.md": "Overview",
        "research_summary.md": "Executive Summary",
    }
    for fixture, fmt in CASES:
        text = open(os.path.join(FIXTURES, fixture)).read()
        content_html, bib_html = convert_markdown_to_html(text)
        assert markers[fixture] in content_html, fixture
        assert "[1]" in bib_html or "Bibliography" in bib_html, fixture


def test_claims_exclude_bibliography_each_format():
    sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
    from extract_claims import extract_sentences
    for fixture, fmt in CASES:
        text = open(os.path.join(FIXTURES, fixture)).read()
        sents = extract_sentences(text)
        assert not any(s.startswith("[") for s in sents), fixture
        assert not any("Journal" in s and "(202" in s for s in sents), fixture


if __name__ == "__main__":
    test_each_fixture_passes_own_format()
    test_each_fixture_fails_comprehensive_default()
    test_readability_gate_passes_each_format()
    test_html_conversion_each_format()
    test_claims_exclude_bibliography_each_format()
    print("all 5 format tests ran and passed (3 fixtures x 5 checks)")
