#!/usr/bin/env python3
"""Canonical Phase 8 gate chain tests (epic-truthful-docs entry 3.1,
E3-R1/E3-R3, findings F5, F6, F11, F18).

Part 1 (doc truth): reference/quality-gates.md holds the one canonical chain
under the heading `## Phase 8 gate chain`; every command's script exists and
every flag (and subcommand) appears in that script's real --help output; the
chain's order is pinned by EXPECTED_CHAIN; the per-format table matches
validate_report.FORMATS; the readability gate documents its real exit codes
and the vendored textstat.

Part 2 (chain execution, initiative Done when 3): the doc's own chain
commands, placeholders filled in and run in the documented order on a
fixture run directory with urllib.request.urlopen mocked, execute every
gate — on a complete fixture and on a realistic provisional draft (numbers
in registration order, one registered source never cited, full provisional
bibliography) — and known-bad variants (an uncited entry, an uncited claim,
a fabricated quote) fail at the gates that must catch them.

Offline: both network verifiers run in-process against a patched urlopen.
Everything writes inside temp run dirs only. No pip dependencies.
Entry 4's divergence test imports CHAIN_HEADING, DOC_PATH and ordered_gates()
from this module.
"""

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
DOC_PATH = os.path.join(ROOT, "reference", "quality-gates.md")
FIXTURE_DIR = os.path.join(HERE, "fixtures", "gate_chain")

CHAIN_HEADING = "## Phase 8 gate chain"

# The canonical chain: (script, subcommand, flags) in run order. Entry 4's
# divergence test compares SKILL.md and report-assembly.md against this.
# Numbering runs first: the draft carries provisional (registration-order)
# numbers and may list uncited sources, which only renumber-report repairs;
# the structure gate before it would fail on "Uncited bibliography entries".
# extract/link run twice: once on the draft (renumber-report needs them),
# once on the renumbered report (claim text carries the [N] markers).
EXPECTED_CHAIN = [
    ("citation_manager.py", "assign-display-numbers", ("--dir",)),
    ("extract_claims.py", "extract", ("--report", "--dir")),
    ("verify_claim_support.py", "link", ("--dir",)),
    ("citation_manager.py", "renumber-report", ("--dir",)),
    ("citation_manager.py", "export-bibliography", ("--dir", "--style")),
    ("extract_claims.py", "extract", ("--report", "--dir")),
    ("verify_claim_support.py", "link", ("--dir",)),
    ("verify_claim_support.py", "verify", ("--dir", "--strict")),
    ("validate_report.py", None, ("--report", "--format", "--manifest")),
    ("readability_check.py", None, ()),
    ("verify_citations.py", None, ("--report",)),
    ("verify_citations_v2.py", None, ("--dir",)),
    ("render_report.py", None, ("--report", "--manifest", "--format", "--out")),
    ("verify_html.py", None, ("--html", "--md")),
    ("check_theme.py", None, ()),
]

_SUB_RE = re.compile(r"^[a-z][a-z0-9-]*$")


def read_doc() -> str:
    with open(DOC_PATH, encoding="utf-8") as f:
        return f.read()


def chain_section(text: str | None = None) -> str:
    """The text between the chain heading and the next `## ` heading."""
    text = text if text is not None else read_doc()
    start = text.index(CHAIN_HEADING)
    rest = text[start + len(CHAIN_HEADING):]
    nxt = rest.find("\n## ")
    return rest[:nxt] if nxt != -1 else rest


def chain_commands(text: str | None = None) -> list[str]:
    """The chain's commands, one per numbered step, in documented order."""
    sec = chain_section(text)
    chunks = re.split(r"(?m)^(?=\d+\.\s)", sec)
    cmds = []
    for chunk in chunks[1:]:  # chunks[0] is the section intro
        m = re.search(r"```bash\n[ \t]*(\S.*)\n", chunk)
        assert m, f"numbered step without a bash command: {chunk.splitlines()[0]}"
        cmds.append(m.group(1).strip())
    return cmds


def parse_gate(command: str) -> dict:
    """{command, script, subcommand, flags} for one chain command line."""
    tokens = command.split()
    assert len(tokens) >= 2 and tokens[0] == "python3", command
    script = tokens[1]
    assert script.startswith("scripts/") and script.endswith(".py"), command
    rest = tokens[2:]
    sub = rest[0] if rest and _SUB_RE.match(rest[0]) else None
    flags = tuple(t for t in rest if t.startswith("-"))
    return {"command": command, "script": os.path.basename(script),
            "subcommand": sub, "flags": flags}


def ordered_gates(text: str | None = None) -> list[dict]:
    """The chain's gates, parsed from the doc, in documented order. The
    public surface entry 4's divergence test compares against."""
    return [parse_gate(c) for c in chain_commands(text)]


def script_help(script: str, subcommand: str | None) -> str:
    """Real --help output of scripts/<script> [subcommand]."""
    argv = [sys.executable, os.path.join(SCRIPTS, script)]
    if subcommand:
        argv.append(subcommand)
    argv.append("--help")
    result = subprocess.run(argv, capture_output=True, text=True)
    assert result.returncode == 0, f"{argv}: {result.stderr}"
    return result.stdout


# ---------------------------------------------------------------------------
# Part 1: the doc tells the truth
# ---------------------------------------------------------------------------

class TestChainSection(unittest.TestCase):
    def test_heading_appears_exactly_once(self):
        self.assertEqual(read_doc().count(CHAIN_HEADING), 1)

    def test_every_step_starts_with_python3(self):
        self.assertTrue(chain_commands())
        for cmd in chain_commands():
            self.assertTrue(cmd.startswith("python3 scripts/"), cmd)

    def test_chain_order_matches_expected(self):
        gates = ordered_gates()
        got = [(g["script"], g["subcommand"], g["flags"]) for g in gates]
        self.assertEqual(got, [tuple(e) for e in EXPECTED_CHAIN])

    def test_every_script_flag_and_subcommand_exists_in_help(self):
        for gate in ordered_gates():
            path = os.path.join(SCRIPTS, gate["script"])
            self.assertTrue(os.path.isfile(path), gate["script"])
            help_text = script_help(gate["script"], gate["subcommand"])
            for flag in gate["flags"]:
                self.assertIn(flag, help_text,
                              f"{flag} missing from {gate['script']} --help")
            if gate["subcommand"]:
                self.assertIn(gate["subcommand"], help_text,
                              f"subcommand {gate['subcommand']} missing from "
                              f"{gate['script']} --help")

    def test_claim_support_and_manifest_and_strict_are_in_the_chain(self):
        commands = " ".join(chain_commands())
        # F5: the claim-support steps exist.
        self.assertIn("extract_claims.py extract", commands)
        self.assertIn("verify_claim_support.py link", commands)
        self.assertIn("verify --dir <run_dir> --strict", commands)
        # F6: validate runs with --manifest.
        self.assertIn("validate_report.py --report <run_dir>/report.md "
                      "--format <format> --manifest", commands)


class TestChainOrder(unittest.TestCase):
    """The order is what makes a provisional draft pass: numbering first,
    claims re-read after renumbering, gates on the final report."""

    def setUp(self):
        self.keys = [(g["script"], g["subcommand"]) for g in ordered_gates()]

    def index(self, key, start=0):
        return self.keys.index(key, start)

    def test_numbering_runs_before_every_report_gate(self):
        renumber = self.index(("citation_manager.py", "renumber-report"))
        for gate in ("validate_report.py", "readability_check.py",
                     "verify_citations.py", "render_report.py"):
            self.assertLess(renumber, self.index((gate, None)), gate)

    def test_renumber_has_a_fresh_extract_and_link_before_it(self):
        renumber = self.index(("citation_manager.py", "renumber-report"))
        assign = self.index(("citation_manager.py", "assign-display-numbers"))
        extract = self.index(("extract_claims.py", "extract"))
        link = self.index(("verify_claim_support.py", "link"))
        self.assertLess(assign, extract)
        self.assertLess(extract, link)
        self.assertLess(link, renumber)

    def test_verify_reads_claims_extracted_after_renumbering(self):
        renumber = self.index(("citation_manager.py", "renumber-report"))
        verify = self.index(("verify_claim_support.py", "verify"))
        extract = self.index(("extract_claims.py", "extract"), renumber)
        link = self.index(("verify_claim_support.py", "link"), extract)
        self.assertLess(link, verify)

    def test_render_completeness_and_theme_close_the_chain(self):
        self.assertEqual(self.keys[-3:], [("render_report.py", None),
                                          ("verify_html.py", None),
                                          ("check_theme.py", None)])


class TestFormatTable(unittest.TestCase):
    """F18: the per-format table is validate_report.FORMATS, all of it."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, SCRIPTS)
        import validate_report
        cls.formats = validate_report.FORMATS
        rows = {}
        collecting = False
        for line in read_doc().splitlines():
            if not line.startswith("|"):
                if collecting:
                    break  # the format table's block ended
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if not collecting:
                if "Format" in cells and "Source floor" in cells:
                    collecting = True
                continue
            if set(cells[0]) <= set("-: "):
                continue  # separator row
            if len(cells) >= 4:
                rows[cells[0]] = cells
            else:
                break
        cls.rows = rows

    def test_every_format_has_a_row_and_vice_versa(self):
        self.assertEqual(set(self.rows), set(self.formats),
                         "table rows and FORMATS keys differ")

    def test_row_matches_the_dict(self):
        for fmt, spec in self.formats.items():
            cells = self.rows[fmt]
            sections, words, floor = cells[1], cells[2], cells[3]
            lo, hi = spec["word_range"]
            self.assertEqual(words, f"{lo}+" if hi is None else f"{lo}-{hi}", fmt)
            self.assertEqual(floor, str(spec["min_sources"]), fmt)
            for required in spec["required"]:
                for name in required.split("|"):
                    self.assertIn(name, sections, f"{fmt}: {name} missing")


class TestReadabilityContract(unittest.TestCase):
    """F11: real exit codes, vendored textstat, no pip line, python3."""

    def test_exit_codes_documented(self):
        doc = read_doc()
        self.assertIn("exit 2 = warnings only (still a pass)", doc)
        self.assertIn("exit 3 =", doc)
        self.assertIn("textstat unavailable", doc)
        self.assertNotIn("Must exit 0", doc)

    def test_no_pip_install_and_vendor_mentioned(self):
        doc = read_doc()
        # Every "pip install" mention must be a negation ("no pip install");
        # whitespace-normalized so line wrapping cannot hide or fake it.
        normalized = re.sub(r"\s+", " ", doc)
        self.assertEqual(normalized.count("pip install"),
                         normalized.count("no pip install"))
        self.assertIn("vendor/", doc)

    def test_no_bare_python_commands(self):
        self.assertNotIn("python scripts/", read_doc())


# ---------------------------------------------------------------------------
# Part 1b (entry 3.7, E3-R8): every ERROR check_theme.py can emit is named
# in quality-gates.md. The inventory is derived from the code (every string
# appended to an `errs` list), so a new ERROR message without a doc phrase
# fails the coverage assert.
# ---------------------------------------------------------------------------

def check_theme_error_templates() -> list[str]:
    """Every distinct ERROR message template scripts/check_theme.py can
    emit (strings appended to an `errs` list; interpolations as {…};
    non-literal arguments skipped)."""
    import ast
    with open(os.path.join(SCRIPTS, "check_theme.py"), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    templates = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "append"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "errs"):
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                templates.append(arg.value)
            elif isinstance(arg, ast.JoinedStr):
                parts = [v.value if isinstance(v, ast.Constant) else "{…}"
                         for v in arg.values]
                templates.append("".join(parts))
    return sorted(set(t.strip() for t in templates if t.strip()))


# template -> the phrase quality-gates.md must contain for it (whitespace
# runs collapse on both sides before matching).
DOC_PHRASES = {
    "javascript: URL in <{…}> {…}= ({…})": "javascript: URL in <",
    "data: document URL in <{…}> {…}= ({…})": "data: document URL in <",
    "injected script element (unclosed <script> tag)":
        "injected script element (unclosed <script> tag)",
    "injected script element (src= on the renderer's deck.js script loads "
    "other code)":
        "injected script element (src= on the renderer's deck.js",
    "injected script element (not the renderer's deck.js: {…})":
        "injected script element (not the renderer's deck.js:",
    "event handler attribute {…}= in <{…}>": "event handler attribute",
    "inline document attribute srcdoc= in <{…}>":
        "inline document attribute srcdoc= in <",
    "package is missing {…}": "package is missing",
    "{…} cannot be read ({…})": "cannot be read",
    "{…} is not valid XML ({…})": "is not valid XML",
    "forbidden color {…} in {…} ({…})": "forbidden color",
    "forbidden color {…} ({…})": "forbidden color",
    "typeface '{…}' in {…} is not declared in theme '{…}'":
        "is not declared in theme",
    "font-family '{…}' is not declared in theme '{…}'":
        "is not declared in theme",
    "slide {…} has no text": "has no text",
    "external relationship of type {…} in {…} ({…})":
        "external relationship of type",
    "hyperlink target contains a control character in {…} ({…})":
        "hyperlink target contains a control character in",
    "hyperlink target is not http(s) in {…} ({…})":
        "hyperlink target is not http(s) in",
    "external resource in src= ({…})": "external resource in src=",
    "external resource in <{…}> href= ({…})":
        "external resource in <tag> href=",
    "@import loads an external resource ({…})":
        "@import loads an external resource",
    "external resource in url() ({…})": "external resource in url()",
    "text element inside motif svg": "text element inside motif svg",
}

# Messages that reach the output without an `errs.append` call: the motif
# keep-out overlap message is built in an `overlaps` list first, and the
# unreadable-input messages are `return`ed directly by check_pptx/check_file.
# Pinned here so the doc names them too.
INDIRECT_ERRORS = {
    "motif cell ({…})-({…}) overlaps the cover text keep-out":
        "overlaps the cover text keep-out",
    "not a PowerPoint package (not a valid zip archive)":
        "not a PowerPoint package (not a valid zip archive)",
    "cannot read file ({…})": "cannot read file",
}


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text)


class TestThemeQAErrorsDocumented(unittest.TestCase):
    """E3-R8: epic-render-fidelity's theme QA errors are documented."""

    def test_every_code_error_is_covered_by_a_doc_phrase(self):
        templates = check_theme_error_templates()
        self.assertTrue(templates)
        missing = [t for t in templates
                   if t not in DOC_PHRASES and t not in INDIRECT_ERRORS]
        self.assertEqual(
            missing, [],
            "check_theme.py gained ERROR message(s) with no doc phrase; "
            "document them in reference/quality-gates.md and add them to "
            "DOC_PHRASES: %s" % missing)

    def test_every_doc_phrase_appears_in_quality_gates(self):
        doc = _squash(read_doc())
        for table in (DOC_PHRASES, INDIRECT_ERRORS):
            for template, phrase in table.items():
                self.assertIn(_squash(phrase), doc,
                              f"quality-gates.md does not name {template!r}")


# ---------------------------------------------------------------------------
# Part 2: the chain runs, exactly as documented
# ---------------------------------------------------------------------------

PAGES = {
    "https://example.com/alpha":
        "<html><body><p>Daily two-question exit tickets lifted retention of "
        "covered material across the trial classrooms in 2024.</p></body></html>",
    "https://example.com/gamma":
        "<html><body><p>Weekly checks suited stable curricula, and teachers "
        "tuned feedback frequency to the calendar.</p></body></html>",
    "https://example.com/beta":
        "<html><body><p>Completion stayed under three minutes whenever each "
        "formative ticket held two questions.</p></body></html>",
    "https://example.com/delta":
        "<html><body><p>Marginal notes on ticket trials that the brief never "
        "relies on.</p></body></html>",
}
QUOTES = {
    "https://example.com/alpha":
        "Daily two-question exit tickets lifted retention of covered material "
        "across the trial classrooms in 2024.",
    "https://example.com/gamma":
        "Weekly checks suited stable curricula, and teachers tuned feedback "
        "frequency to the calendar.",
    "https://example.com/beta":
        "Completion stayed under three minutes whenever each formative ticket "
        "held two questions.",
    "https://example.com/delta":
        "Marginal notes on ticket trials that the brief never relies on.",
}
FABRICATED_QUOTE = ("This sentence appears on none of the canned pages and "
                    "was never published anywhere.")
UNCITED_SENTENCE = ("The district also mandated a ninety-second cap for every "
                    "grade level in 2025.")
SOURCE_META = {
    "https://example.com/alpha": ("Alpha Analytics",
                                  "Retention pace in classroom practice", "2024"),
    "https://example.com/beta": ("Beta Education Notes",
                                 "Time cost of formative checks", "2023"),
    "https://example.com/gamma": ("Gamma Teaching Quarterly",
                                  "Feedback frequency for stable curricula", "2022"),
    "https://example.com/delta": ("Delta Education Press",
                                  "Uncited marginalia in ticket trials", "2021"),
}
FORMAT = "quick-brief"
FINAL_BIBLIOGRAPHY = (
    '[1] Gamma Teaching Quarterly (2022). "Feedback frequency for stable '
    'curricula". https://example.com/gamma\n'
    '[2] Alpha Analytics (2024). "Retention pace in classroom practice". '
    'https://example.com/alpha\n'
    '[3] Beta Education Notes (2023). "Time cost of formative checks". '
    'https://example.com/beta\n')


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200):
        self._body, self.status = body, status

    def read(self, n: int = -1) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeUrlopen:
    """url -> (status, body); status >= 400 raises HTTPError."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls = []

    def __call__(self, req, timeout=None):
        url = req.full_url
        self.calls.append(url)
        status, body = self.routes.get(url, (404, b""))
        if status >= 400:
            raise urllib.error.HTTPError(url, status, "canned error", None, None)
        return FakeResponse(body, status)


ROUTES = {url: (200, body.encode("utf-8")) for url, body in PAGES.items()}

sys.path.insert(0, SCRIPTS)
import citation_manager  # noqa: E402
import check_theme  # noqa: E402
import extract_claims  # noqa: E402
import readability_check  # noqa: E402
import render_report  # noqa: E402
import validate_report  # noqa: E402
import verify_citations  # noqa: E402
import verify_citations_v2  # noqa: E402
import verify_claim_support  # noqa: E402
import verify_html  # noqa: E402

MODULES = {
    "citation_manager.py": citation_manager,
    "check_theme.py": check_theme,
    "extract_claims.py": extract_claims,
    "readability_check.py": readability_check,
    "render_report.py": render_report,
    "validate_report.py": validate_report,
    "verify_citations.py": verify_citations,
    "verify_citations_v2.py": verify_citations_v2,
    "verify_claim_support.py": verify_claim_support,
    "verify_html.py": verify_html,
}
# Exit codes each gate counts as a pass (readability: 2 = warnings only).
PASS_CODES = {"readability_check.py": (0, 2)}


def run_gate(module, argv, mock_network=False):
    """Run one gate's main() in-process; return (exit_code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    old_argv, sys.argv = sys.argv, argv
    patcher = (unittest.mock.patch("urllib.request.urlopen", FakeUrlopen(ROUTES))
               if mock_network else contextlib.nullcontext())
    try:
        with patcher, contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            try:
                ret = module.main()
                code = 0 if ret is None else ret  # main() may return the code
            except SystemExit as e:
                code = e.code if e.code is not None else 0
    finally:
        sys.argv = old_argv
    return code, out.getvalue(), err.getvalue()


class ChainRunCase(unittest.TestCase):
    """A temp run folder at the end of assembly, before Phase 8: sources
    registered, the provisional (registration-order) map saved, the draft
    written with those numbers, evidence captured."""

    FIXTURE = None        # report fixture file name
    REGISTRATION = ()     # source URLs in registration order

    def setUp(self):
        self.run_dir = tempfile.mkdtemp(prefix="gate_chain_")
        self.addCleanup(shutil.rmtree, self.run_dir, ignore_errors=True)
        self.report = os.path.join(self.run_dir, "report.md")
        self.manifest = os.path.join(self.run_dir, "run_manifest.json")
        c, _, e = run_gate(citation_manager, [
            "citation_manager", "init-run", "--out-dir", self.run_dir,
            "--query", "exit-ticket cadence", "--mode", "quick"])
        assert c == 0, e
        self.ids = {}
        for url in self.REGISTRATION:
            org, title, year = SOURCE_META[url]
            c, o, e = run_gate(citation_manager, [
                "citation_manager", "register-source", "--dir", self.run_dir,
                "--json", json.dumps({"raw_url": url, "title": title,
                                      "authors": [org], "year": year})])
            assert c == 0, e
            self.ids[url] = json.loads(o)["source_id"]
        c, _, e = run_gate(citation_manager, [
            "citation_manager", "assign-display-numbers", "--dir", self.run_dir])
        assert c == 0, e
        shutil.copy(os.path.join(FIXTURE_DIR, self.FIXTURE), self.report)
        with open(os.path.join(self.run_dir, "evidence.jsonl"), "w") as f:
            for i, url in enumerate(self.REGISTRATION, 1):
                f.write(json.dumps({
                    "evidence_id": f"ev_{i:03}",
                    "source_id": self.ids[url],
                    "quote": QUOTES[url],
                    "evidence_type": "direct_quote",
                }) + "\n")

    def documented_argv(self, command: str) -> list[str]:
        """A chain command from the doc, placeholders filled in."""
        tokens = command.replace("<run_dir>", self.run_dir) \
                        .replace("<format>", FORMAT).split()
        return [os.path.splitext(os.path.basename(tokens[1]))[0]] + tokens[2:]

    def run_chain(self):
        """Run the doc's chain commands, in the doc's order, with the network
        mocked. Returns [(step_no, script, subcommand, code, stdout, stderr)]."""
        results = []
        for i, gate in enumerate(ordered_gates(), 1):
            code, out, err = run_gate(MODULES[gate["script"]],
                                      self.documented_argv(gate["command"]),
                                      mock_network=True)
            results.append((i, gate["script"], gate["subcommand"], code, out, err))
        return results

    @staticmethod
    def first_failure(results):
        for row in results:
            if row[3] not in PASS_CODES.get(row[1], (0,)):
                return row
        return None

    def assert_chain_passes(self, results):
        failed = self.first_failure(results)
        if failed:
            self.fail(f"step {failed[0]} {failed[1]} {failed[2] or ''} "
                      f"exited {failed[3]}:\n{failed[4]}\n{failed[5]}")
        self.assertEqual(len(results), len(EXPECTED_CHAIN))

    def read_report(self) -> str:
        with open(self.report, encoding="utf-8") as f:
            return f.read()



class TestChainRunsOnFixture(ChainRunCase):
    """The builder's fixture: every source cited, bibliography complete,
    citation order (gamma first) differs from registration order."""

    FIXTURE = "quick_brief_chain.md"
    REGISTRATION = ("https://example.com/alpha", "https://example.com/beta",
                    "https://example.com/gamma")

    def test_run_gate_captures_returned_exit_codes(self):
        """readability_check.main() and check_theme.main() return their code
        instead of raising SystemExit; the harness must see a real failure."""
        bad = os.path.join(self.run_dir, "too_short.md")
        with open(bad, "w", encoding="utf-8") as f:
            f.write("# T\n\nOk [1].\n")
        code, out, _ = run_gate(readability_check, ["readability_check", bad])
        self.assertEqual(code, 1)
        self.assertIn("no measurable prose", out)

    def test_every_gate_passes_in_documented_order(self):
        self.assert_chain_passes(self.run_chain())
        self.assertTrue(os.path.isfile(os.path.join(self.run_dir, "report.html")))
        # The numbering steps really ran: the fixture cites gamma [3] first,
        # so after renumber-report gamma is [1] in body and bibliography.
        text = self.read_report()
        self.assertIn("cadence trial [1].", text)
        self.assertIn(FINAL_BIBLIOGRAPHY, text)

    def test_uncited_entry_fails_the_structure_gate(self):
        self.assert_chain_passes(self.run_chain())
        with open(self.report, "a", encoding="utf-8") as f:
            f.write('[4] Delta Education Press (2021). "Uncited marginalia in '
                    'ticket trials". https://example.com/delta\n')
        code, out, _ = run_gate(validate_report, [
            "validate_report", "--report", self.report,
            "--format", FORMAT, "--manifest", self.manifest])
        self.assertEqual(code, 1)
        self.assertIn("Uncited bibliography entries", out)
        self.assertIn("[4]", out)

    def test_lost_section_fails_at_the_verify_html_gate(self):
        """E3-R8: verify_html is the chain's render-completeness step. A
        delivered report that lost a section must fail there, exit 1,
        with the loss named. (The chain itself cannot be re-run to see
        this: step 13 re-renders report.html from the markdown, healing
        any corruption — so the gate runs directly on a lossy render.)"""
        self.assert_chain_passes(self.run_chain())
        html_path = os.path.join(self.run_dir, "report.html")
        with open(html_path, encoding="utf-8") as f:
            html = f.read()
        corrupted, n = re.subn(
            r'<h2 class="section-title"[^>]*>Key Points</h2>\s*', "", html)
        self.assertEqual(n, 1, "fixture render lost its Key Points heading")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(corrupted)
        code, out, _ = run_gate(verify_html, [
            "verify_html", "--html", html_path, "--md", self.report])
        self.assertEqual(code, 1)
        self.assertIn("missing heading in HTML: Key Points", out)
        self.assertIn("verify_html: FAIL", out)


class TestChainOnProvisionalDraft(ChainRunCase):
    """The realistic Phase 8 input: four sources registered alpha, delta,
    gamma, beta; the draft is written with the provisional numbers
    (alpha [1], delta [2], gamma [3], beta [4]), cites gamma first and
    never cites delta, and its bibliography lists all four."""

    FIXTURE = "provisional_draft.md"
    REGISTRATION = ("https://example.com/alpha", "https://example.com/delta",
                    "https://example.com/gamma", "https://example.com/beta")

    def test_structure_gate_on_the_raw_draft_fails(self):
        """Why numbering runs first: validate on the draft as written fails
        on the uncited provisional entry, which renumber-report repairs."""
        code, out, _ = run_gate(validate_report, [
            "validate_report", "--report", self.report,
            "--format", FORMAT, "--manifest", self.manifest])
        self.assertEqual(code, 1)
        self.assertIn("Uncited bibliography entries", out)
        self.assertIn("[2]", out)

    def test_every_gate_passes_in_documented_order(self):
        self.assert_chain_passes(self.run_chain())
        text = self.read_report()
        self.assertNotIn("Delta Education Press", text)
        self.assertIn(FINAL_BIBLIOGRAPHY, text)
        self.assertIn("cadence trial [1].", text)
        with open(os.path.join(self.run_dir, "display_numbers.json")) as f:
            saved = json.load(f)
        self.assertEqual(saved, {
            self.ids["https://example.com/gamma"]: 1,
            self.ids["https://example.com/alpha"]: 2,
            self.ids["https://example.com/beta"]: 3,
        })
        self.assertTrue(os.path.isfile(os.path.join(self.run_dir, "report.html")))

    def test_chain_is_safe_to_re_run(self):
        self.assert_chain_passes(self.run_chain())
        first = self.read_report()
        self.assert_chain_passes(self.run_chain())
        self.assertEqual(self.read_report(), first)

    def test_uncited_claim_fails_at_strict_verify(self):
        text = self.read_report().replace(
            "\n## Action Items", f"\n{UNCITED_SENTENCE}\n\n## Action Items")
        with open(self.report, "w", encoding="utf-8") as f:
            f.write(text)
        failed = self.first_failure(self.run_chain())
        self.assertIsNotNone(failed)
        self.assertEqual((failed[1], failed[2]),
                         ("verify_claim_support.py", "verify"))
        self.assertEqual(json.loads(failed[4])["factual_unsupported"], 1)

    def test_fabricated_quote_fails_quote_fidelity(self):
        with open(os.path.join(self.run_dir, "evidence.jsonl"), "a",
                  encoding="utf-8") as f:
            f.write(json.dumps({
                "evidence_id": "ev_fabricated",
                "source_id": self.ids["https://example.com/alpha"],
                "quote": FABRICATED_QUOTE,
                "evidence_type": "direct_quote",
            }) + "\n")
        failed = self.first_failure(self.run_chain())
        self.assertIsNotNone(failed)
        self.assertEqual(failed[1], "verify_citations_v2.py")
        self.assertEqual(failed[3], 1)
        self.assertIn("1 misses", failed[4])


# ---------------------------------------------------------------------------
# Part 3 (entry 3.4, E3-R2/E3-R9): the other Phase 8 docs point at the one
# chain — SKILL.md, report-assembly.md, continuation.md and (entry 3.8)
# html-generation.md link the anchor, carry no gate order of their own, and
# name no gate command quality-gates.md does not document. Sequences are
# compared as sequences everywhere: the canonical chain runs extract and
# link twice, and set comparison would collapse those duplicates and hide a
# partial copy of the chain.
# ---------------------------------------------------------------------------

PHASE8_DOCS = {
    "SKILL.md": os.path.join(ROOT, "SKILL.md"),
    "reference/report-assembly.md": os.path.join(ROOT, "reference",
                                                 "report-assembly.md"),
    "reference/continuation.md": os.path.join(ROOT, "reference",
                                              "continuation.md"),
    "reference/html-generation.md": os.path.join(ROOT, "reference",
                                                 "html-generation.md"),
}
CHAIN_ANCHOR = "quality-gates.md#phase-8-gate-chain"

_INVOCATION_RE = re.compile(
    r"`?python(3)?\s+scripts/([a-z_0-9]+\.py)((?:\s+[^\n`]*)?)`?")
_NUMBERED_RE = re.compile(r"^\s*\d+\.\s+(.*)$")
_BULLET_RE = re.compile(r"^\s*-\s+(.*)$")


def chain_pairs() -> dict:
    """script -> the chain's subcommands for it (None = no subcommand)."""
    pairs: dict = {}
    for gate in ordered_gates():
        pairs.setdefault(gate["script"], set()).add(gate["subcommand"])
    return pairs


def _flags_of(tail: str) -> set:
    flags = set()
    for token in tail.split():
        token = token.strip("[]")
        if token.startswith("--"):
            flags.add(token)
    return flags


def parse_invocation(text: str):
    """(py3, script, subcommand, flags) for one `python[3] scripts/x.py ...`
    command inside text, or None when text names no such command."""
    m = _INVOCATION_RE.search(text)
    if not m:
        return None
    py3, script, tail = m.group(1) == "3", m.group(2), m.group(3)
    tokens = tail.split()
    sub = tokens[0] if tokens and _SUB_RE.match(tokens[0]) else None
    return py3, script, sub, _flags_of(tail)


def gate_invocation(item: str):
    """The invocation in item when it runs a chain gate, else None."""
    inv = parse_invocation(item)
    if inv is None:
        return None
    _, script, sub, _ = inv
    return inv if sub in chain_pairs().get(script, set()) else None


def allowed_flags() -> dict:
    """(script, subcommand) -> every flag quality-gates.md documents for it:
    the chain's own steps, any invocation anywhere in that doc, and flag
    tokens within two lines of a mention of the script (prose flags such as
    verify_citations' --strict and check_theme's --theme)."""
    allowed: dict = {}
    for gate in ordered_gates():
        allowed.setdefault((gate["script"], gate["subcommand"]),
                           set()).update(gate["flags"])
    doc = read_doc()
    for m in _INVOCATION_RE.finditer(doc):
        tokens = m.group(3).split()
        sub = tokens[0] if tokens and _SUB_RE.match(tokens[0]) else None
        allowed.setdefault((m.group(2), sub), set()).update(
            _flags_of(m.group(3)))
    lines = doc.splitlines()
    for i, line in enumerate(lines):
        window = " ".join(lines[max(0, i - 2):i + 3])
        for script, subs in chain_pairs().items():
            if re.search(rf"\b{re.escape(script)}\b", line):
                for sub in subs:
                    allowed.setdefault((script, sub), set()).update(
                        re.findall(r"--[a-z][a-z0-9-]*", window))
    return allowed


def own_gate_orders(text: str) -> list:
    """Every run order a doc gives on its own: numbered lists with >=2 gate
    items, bullet lists with >=2 command-only gate items, fenced bash blocks
    with >=2 gate command lines, bullet lists that describe >=2 gate
    commands in an order the chain does not run them, and prose lines
    joining >=2 chain scripts with an arrow or an order word ("then",
    "before", "after", ...). Each violation is (kind, [(script, sub), ...]) — the
    sequence as found, duplicates kept."""
    pairs = chain_pairs()
    violations = []

    def gate_of(content):
        inv = gate_invocation(content)
        return (inv[1], inv[2]) if inv else None

    lines = text.splitlines()
    # list groups: items may be separated by blank lines; a different list
    # kind or any other content line ends the group
    groups = {"numbered": [], "bullet": []}
    current = {"numbered": [], "bullet": []}
    fence = False
    fence_block: list = []
    for line in lines:
        if line.lstrip().startswith("```"):
            if fence:
                cmds = [gate_of(l) for l in fence_block]
                cmds = [c for c in cmds if c]
                if len(cmds) >= 2:  # a block that runs >=2 gates in order
                    violations.append(("bash block", cmds))
                fence_block = []
            fence = not fence
            for kind in groups:
                if current[kind]:
                    groups[kind].append(current[kind])
                    current[kind] = []
            continue
        if fence:
            fence_block.append(line)
            continue
        matched = False
        for kind, rx in (("numbered", _NUMBERED_RE), ("bullet", _BULLET_RE)):
            m = rx.match(line)
            if m:
                for other in current:  # a different list kind breaks the group
                    if other != kind:
                        if current[other]:
                            groups[other].append(current[other])
                            current[other] = []
                current[kind].append(m.group(1))
                matched = True
        if matched:
            continue
        if not line.strip():
            continue  # a blank does not end a list
        for kind in current:
            if current[kind]:
                groups[kind].append(current[kind])
                current[kind] = []
        if _ORDER_WORD_RE.search(line):
            scripts = [s for s in pairs
                       if re.search(rf"\b{re.escape(s)}\b", line)]
            if len(scripts) >= 2:
                violations.append(("prose order", scripts))
    for kind in current:
        if current[kind]:
            groups[kind].append(current[kind])

    for items in groups["numbered"]:
        gates = [g for g in (gate_of(i) for i in items) if g]
        if len(gates) >= 2:
            violations.append(("numbered list", gates))
    canonical = [(g["script"], g["subcommand"]) for g in ordered_gates()]
    for items in groups["bullet"]:
        gates, described = [], []
        for item in items:
            stripped = item.strip()
            if _INVOCATION_RE.match(stripped) and gate_of(stripped):
                if not re.sub(r"`?python(3)?\s+scripts/[a-z_0-9]+\.py"
                              r"((?:\s+[^\n`]*)?)`?", "", stripped).strip():
                    gates.append(gate_of(stripped))
                else:
                    described.append(gate_of(stripped))
        if len(gates) >= 2:
            violations.append(("bullet list", gates))
        # A bullet list that describes each command (SKILL.md's Scripts
        # reference) may name several gates, but never in an order the
        # chain does not run them: a reader skimming it must not learn a
        # different order.
        if len(described) >= 2 and not _is_subsequence(described, canonical):
            violations.append(("bullet list out of chain order", described))
    return violations


# Prose that sequences commands: arrows, "then", "before", "after", ...
_ORDER_WORD_RE = re.compile(
    r"→|->|\bthen\b|\bbefore\b|\bafter\b|\bfollowed by\b|\bnext\b", re.I)


def _is_subsequence(seq: list, canonical: list) -> bool:
    it = iter(canonical)
    return all(any(item == c for c in it) for item in seq)


class TestDocDivergence(unittest.TestCase):
    """E3-R2: one chain, linked — never restated. On the docs as they stood
    before entry 3.4 this fails: SKILL.md carried an arrow order (and bare
    `python` gate commands), report-assembly.md a numbered gate list, and
    continuation.md a numbering command list of its own. Gate commands are
    chain-script invocations with a chain subcommand; assembly commands of
    the same scripts (init-run, register-source) are not gate commands and
    stay legal — a subcommand that is neither a chain subcommand nor in the
    script's own --help is a misspelling and fails. Entry 3.8 adds
    html-generation.md (3.7 review: its Steps 1-4 slice was uncovered) and
    the step-order test below."""

    @staticmethod
    def doc_text(name):
        with open(PHASE8_DOCS[name], encoding="utf-8") as f:
            return f.read()

    def test_every_doc_links_the_chain_and_the_anchor_resolves(self):
        canonical = read_doc()
        self.assertIn(CHAIN_HEADING, canonical)  # the anchor target exists
        for name in PHASE8_DOCS:
            with self.subTest(doc=name):
                self.assertIn(CHAIN_ANCHOR, self.doc_text(name),
                              f"{name} does not link the canonical chain")

    def test_no_doc_gives_a_gate_order_of_its_own(self):
        orders = [(name, kind, gates)
                  for name in PHASE8_DOCS
                  for kind, gates in own_gate_orders(self.doc_text(name))]
        if orders:
            listing = "\n".join(f"- {name}: {kind} {gates}"
                                for name, kind, gates in orders)
            self.fail(f"docs restate the chain instead of linking "
                      f"{CHAIN_ANCHOR}:\n{listing}")

    def test_doc_gate_commands_agree_with_quality_gates(self):
        allowed = allowed_flags()
        pairs = chain_pairs()
        for name in PHASE8_DOCS:
            for m in _INVOCATION_RE.finditer(self.doc_text(name)):
                py3, script, tail = m.group(1), m.group(2), m.group(3)
                tokens = tail.split()
                sub = tokens[0] if tokens and _SUB_RE.match(tokens[0]) else None
                with self.subTest(doc=name, command=m.group(0)):
                    self.assertEqual(py3, "3",
                                     "quality-gates.md says python3, "
                                     "not python")
                    if script not in pairs:
                        continue  # not a chain script (decks, engine, ...)
                    if sub in pairs[script]:
                        unexpected = _flags_of(tail) - allowed[(script, sub)]
                        self.assertFalse(
                            unexpected,
                            f"{script} flags {sorted(unexpected)} are not "
                            f"documented in quality-gates.md")
                    elif sub is not None:
                        # the script's own usage brace group lists its
                        # subcommands ({verify,link,report} style)
                        known = re.findall(
                            r"(?<=[{,])[a-z][a-z0-9-]*(?=[,}])",
                            script_help(script, None))
                        self.assertIn(
                            sub, known,
                            f"neither a chain subcommand nor one "
                            f"{script} implements — a misspelling")

    def test_html_generation_steps_follow_chain_order(self):
        """Entry 3.8 (3.7 review note): html-generation.md's Steps 1-4 are
        the chain's readability/render/verify_html/check_theme slice, but
        each step lives under its own heading, so own_gate_orders (lists,
        blocks, single prose lines) cannot see a reorder of the steps.
        Collect the gate invocations of the Generation Steps section in
        document order and require the sequence to be a subsequence of the
        canonical chain. The optional deck/pptx sections sit outside the
        section, so check_theme appears once."""
        text = self.doc_text("reference/html-generation.md")
        in_section = False
        sequence = []
        for line in text.splitlines():
            if line.startswith("## "):
                in_section = line.startswith("## Generation Steps")
                continue
            if not in_section:
                continue
            gate = gate_invocation(line)
            if gate:
                sequence.append((gate[1], gate[2]))
        canonical = [(g["script"], g["subcommand"]) for g in ordered_gates()]
        self.assertTrue(
            sequence,
            "no gate invocations found under ## Generation Steps — the "
            "step-order check must have something to check")
        self.assertTrue(
            _is_subsequence(sequence, canonical),
            f"html-generation.md steps run gates out of chain order: "
            f"{sequence}")

    def test_step_reorder_is_caught(self):
        """Sensitivity probe (3.8): a tree copy whose html-generation.md
        swaps the full Step 3 and Step 4 blocks must fail the step-order
        test above."""
        import tempfile
        text = self.doc_text("reference/html-generation.md")
        start = text.index("### Step 3: Render completeness gate")
        split = text.index("### Step 4: Theme QA gate")
        end = text.index("### Step 5: Open (optional)")
        reordered = (text[:start] + text[split:end] + text[start:split]
                     + text[end:])
        with tempfile.TemporaryDirectory() as tmp:
            swapped = os.path.join(tmp, "html-generation.md")
            with open(swapped, "w", encoding="utf-8") as f:
                f.write(reordered)
            with unittest.mock.patch.dict(
                    PHASE8_DOCS,
                    {"reference/html-generation.md": swapped}):
                with self.assertRaises(AssertionError):
                    self.test_html_generation_steps_follow_chain_order()


if __name__ == "__main__":
    unittest.main()
