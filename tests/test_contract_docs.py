"""Contract docs (epic-truthful-docs entry 3): the docs this entry owns
state epic-gate-integrity's data and tool contracts as the code on this
branch implements them. Checked here: every `python3 scripts/X.py ...`
command the docs name parses against that script's (sub)command --help;
the schema field names and forms the docs cite (manifest `format` enum
and `qa_notes`, source `published_at` pattern, evidence_type values)
exist in schemas/ and match the enforcing scripts' own constants; the
facet heading convention in contested-topics.md and both comprehensive
templates is the one validate_report.py's label regex accepts; the
bibliography format in citations.md and every template skeleton is the
one citation_manager._format_bib_entry writes and bibliography.ENTRY_RE
parses (and the markdown-link form is not an entry); no owned doc says
`python `; the source_evaluator CLI output holds the fields methodology
names (average_overall included). Read-only: this test writes nothing
and needs no network."""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
SCRIPTS = os.path.join(ROOT, "scripts")
SCHEMAS = os.path.join(ROOT, "schemas")

DOCS = [
    os.path.join(ROOT, "reference", "methodology.md"),
    os.path.join(ROOT, "reference", "html-generation.md"),
    os.path.join(ROOT, "references", "citations.md"),
    os.path.join(ROOT, "references", "contested-topics.md"),
    os.path.join(ROOT, "references", "format-selection.md"),
] + sorted(
    os.path.join(ROOT, "references", "report-templates", n)
    for n in os.listdir(os.path.join(ROOT, "references", "report-templates"))
    if n.endswith(".md")
) + [os.path.join(ROOT, "templates", "report_template.md")]

sys.path.insert(0, SCRIPTS)
from bibliography import ENTRY_RE  # noqa: E402
from evidence_store import VALID_EVIDENCE_TYPES  # noqa: E402
from citation_manager import _format_bib_entry  # noqa: E402
from validate_report import _FACET_LABEL_RE  # noqa: E402


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def load_schema(name):
    with open(os.path.join(SCHEMAS, name), encoding="utf-8") as f:
        return json.load(f)


def run_command(cmd):
    return subprocess.run(
        [sys.executable] + cmd, capture_output=True, text=True,
        timeout=60, cwd=ROOT,
    )


COMMAND_RE = re.compile(r"python3 (scripts/[A-Za-z0-9_]+\.py[^\n`]*)")
FLAG_RE = re.compile(r"--[A-Za-z][A-Za-z0-9_-]*")
SUBCOMMAND_RE = re.compile(r"^[a-z][a-z-]*$")


def doc_commands():
    """(doc, script, subcommand_or_None, flags, raw) for every runnable
    command the owned docs name."""
    found = []
    for doc in DOCS:
        for raw in COMMAND_RE.findall(read(doc)):
            parts = raw.split()
            script, rest = parts[0], parts[1:]
            sub = rest[0] if rest and SUBCOMMAND_RE.match(rest[0]) else None
            flags = [f for f in FLAG_RE.findall(raw)]
            found.append((doc, script, sub, flags, raw.strip()))
    return found


_HELP_CACHE = {}


def help_text(script, sub):
    key = (script, sub)
    if key not in _HELP_CACHE:
        cmd = [os.path.join(ROOT, script), "--help"]
        if sub:
            cmd = [os.path.join(ROOT, script), sub, "--help"]
        proc = run_command(cmd)
        assert proc.returncode == 0, (script, sub, proc.stderr)
        _HELP_CACHE[key] = proc.stdout
    return _HELP_CACHE[key]


def test_no_bare_python():
    bad = re.compile(r"\bpython\s(?!3)")
    for doc in DOCS:
        for i, line in enumerate(read(doc).splitlines(), 1):
            assert not bad.search(line), (doc, i, line)


def test_doc_commands_parse_against_help():
    commands = doc_commands()
    assert len(commands) >= 8, "expected the docs to name CLI commands"
    for doc, script, sub, flags, raw in commands:
        text = help_text(script, sub)
        for flag in flags:
            assert flag in text, (doc, raw, flag)


def test_manifest_fields_named_and_real():
    schema = load_schema("run_manifest.schema.json")
    props = schema["properties"]
    fmt_enum = props["format"]["enum"]
    assert fmt_enum == [
        "comparison", "comprehensive-report", "discovery-catalog",
        "quick-brief", "research-summary",
    ], fmt_enum
    assert props["qa_notes"]["type"] == ["string", "null"]
    html = read(os.path.join(ROOT, "reference", "html-generation.md"))
    assert "manifest's `format` field" in html
    assert "`qa_notes`" in html
    for name in fmt_enum:
        assert name in html, name


def test_published_at_forms_match_schema():
    pattern = load_schema("source.schema.json")["properties"]["published_at"]
    assert pattern["type"] == ["string", "null"]
    rx = re.compile(pattern["pattern"])
    for good in ("2024", "2024-01", "2024-01-15",
                 "2024-01-15T09:30:00Z", "2024-01-15T09:30:00+02:00"):
        assert rx.match(good), good
    for bad_value in ("January 2024", "2024-1", "20240115", "2024-13"):
        assert not rx.match(bad_value), bad_value
    for doc_name in ("references/citations.md", "reference/methodology.md"):
        text = read(os.path.join(ROOT, doc_name))
        for form in ("YYYY-MM-DD", "YYYY-MM", "YYYY"):
            assert form in text, (doc_name, form)


def test_evidence_types_doc_schema_and_script_agree():
    schema_enum = load_schema("evidence.schema.json")["properties"][
        "evidence_type"]["enum"]
    expected = [
        "direct_quote", "paraphrase", "data_point", "figure_reference",
        "methodology",
    ]
    assert list(schema_enum) == expected, schema_enum
    assert list(VALID_EVIDENCE_TYPES) == expected, VALID_EVIDENCE_TYPES
    for doc_name in ("references/citations.md", "reference/methodology.md"):
        text = read(os.path.join(ROOT, doc_name))
        for value in expected:
            assert value in text, (doc_name, value)


def test_facet_heading_convention():
    # The code's rule: an explicit 'Facet N' label (in manifest order);
    # an unlabelled heading never matches by position.
    assert _FACET_LABEL_RE.match("Facet 3: Economic impact on consumers")
    assert _FACET_LABEL_RE.match("facet #2 — harms")
    assert _FACET_LABEL_RE.match("Economic impact on consumers") is None
    for rel in (
        "references/contested-topics.md",
        "references/report-templates/comprehensive-report.md",
        "templates/report_template.md",
    ):
        text = re.sub(r"\s+", " ", read(os.path.join(ROOT, rel)))
        assert "Facet N" in text, rel
        assert "named after the facet" in text, rel


def test_bibliography_format_doc_and_exporter_agree():
    entry = _format_bib_entry(
        1, {"authors": ["Min, S."], "year": "2023",
            "title": "FActScore.", "raw_url": "https://arxiv.org/abs/x"})
    assert entry == '[1] Min, S. (2023). "FActScore". https://arxiv.org/abs/x'
    no_meta = _format_bib_entry(2, {"title": "Untitled Study",
                                    "raw_url": "https://example.com/y"})
    assert no_meta == '[2] (n.d.). "Untitled Study". https://example.com/y'
    # The documented entry forms are exactly the ones the shared rule parses.
    for form in ("[1] Author (2026). \"T\". https://e.com/t",
                 "- [1] Author (2026). \"T\". https://e.com/t",
                 "* [1] Author (2026). \"T\". https://e.com/t"):
        assert ENTRY_RE.match(form), form
    # A markdown link is NOT an entry — templates must not prescribe it.
    assert ENTRY_RE.match("- [Source Title](url)") is None
    citations = read(os.path.join(ROOT, "references", "citations.md"))
    assert '[N] Author (Year). "Title". URL' in citations


def test_templates_show_numbered_bibliographies():
    skeletons = [
        p for p in DOCS
        if p.endswith("report_template.md")
        or os.path.basename(p) != "contested-topics.md" and
        os.path.dirname(p).endswith("report-templates")
    ]
    assert len(skeletons) == 6, skeletons
    for path in skeletons:
        text = read(path)
        assert "- [Source Title](url)" not in text, path
        section = text[text.index("## Bibliography"):]
        section = section.split("\n## ")[0]
        assert any(ENTRY_RE.match(line)
                   for line in section.splitlines()), path


def test_gate_chain_anchor_used():
    for rel in ("references/citations.md", "references/format-selection.md",
                "reference/methodology.md"):
        text = read(os.path.join(ROOT, rel))
        assert "reference/quality-gates.md#phase-8-gate-chain" in text, rel


def test_source_evaluator_cli_contract():
    one = run_command([
        "scripts/source_evaluator.py", "--url", "https://example.com/report",
        "--title", "Example", "--date", "2024",
    ])
    assert one.returncode == 0, one.stderr
    score = json.loads(one.stdout)
    assert set(score) == {
        "source_id", "url", "title", "domain", "overall_score",
        "domain_authority", "recency", "expertise", "bias_score",
        "factors", "recommendation",
    }, sorted(score)
    run_dir = os.path.join("tests", "fixtures", "source_evaluator", "run")
    whole = run_command(["scripts/source_evaluator.py", "--dir", run_dir])
    assert whole.returncode == 0, whole.stderr
    run_json = json.loads(whole.stdout)
    for key in ("dir", "count", "average_overall", "sources", "defects"):
        assert key in run_json, key
    assert run_json["count"] == 3, run_json["count"]
    assert isinstance(run_json["average_overall"], float)
    methodology = read(os.path.join(ROOT, "reference", "methodology.md"))
    for needed in ("--url", "--dir", "average_overall",
                   "Exit codes: 0 scored", "1 defect", "2 usage"):
        assert needed in methodology, needed


def test_template_bodies_cite_by_number():
    # A skeleton that cites with markdown links in its body fails the
    # structure gate when followed ("No citations found in report",
    # every bibliography entry uncited), as quick-brief.md's Key Points
    # did. Every skeleton cites by [N] before its bibliography.
    link_cite = re.compile(r"\]\((?:url|https?://)[^)]*\)")
    for path in DOCS:
        if not (path.endswith("report_template.md")
                or os.path.dirname(path).endswith("report-templates")):
            continue
        text = read(path)
        body = text[:text.index("## Bibliography")]
        assert not link_cite.search(body), (path, link_cite.search(body).group(0))
        assert re.search(r"\[(?:N|\d{1,3})\]", body), path


def test_export_year_comes_from_year_field():
    # export-bibliography reads the source row's `year`, never
    # published_at, so the register-source example must pass `year`.
    entry = _format_bib_entry(1, {"title": "T", "published_at": "2026-01",
                                  "raw_url": "https://e.com/t"})
    assert entry == '[1] (n.d.). "T". https://e.com/t', entry
    methodology = read(os.path.join(ROOT, "reference", "methodology.md"))
    register = [line for line in methodology.splitlines()
                if "citation_manager.py register-source" in line]
    assert register and all('"year"' in line for line in register), register
    citations = read(os.path.join(ROOT, "references", "citations.md"))
    assert "`published_at` does not feed it" in citations


def test_gate_exit_codes_stated_in_full():
    html = re.sub(r"\s+", " ", read(
        os.path.join(ROOT, "reference", "html-generation.md")))
    fmt = re.sub(r"\s+", " ", read(
        os.path.join(ROOT, "references", "format-selection.md")))
    for text, name in ((html, "html-generation.md"),
                       (fmt, "format-selection.md")):
        assert "exit 2" in text and "still a pass" in text, name
        assert "exit 3 (textstat unavailable) also blocks delivery" in text, name
    assert "exit 2 = the theme could not be loaded" in html


if __name__ == "__main__":
    test_no_bare_python()
    test_doc_commands_parse_against_help()
    test_manifest_fields_named_and_real()
    test_published_at_forms_match_schema()
    test_evidence_types_doc_schema_and_script_agree()
    test_facet_heading_convention()
    test_bibliography_format_doc_and_exporter_agree()
    test_templates_show_numbered_bibliographies()
    test_gate_chain_anchor_used()
    test_source_evaluator_cli_contract()
    test_template_bodies_cite_by_number()
    test_export_year_comes_from_year_field()
    test_gate_exit_codes_stated_in_full()
    print("all 13 contract-docs tests ran and passed")
