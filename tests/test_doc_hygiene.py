#!/usr/bin/env python3
"""Doc hygiene tests (epic-truthful-docs entry 3.6, E3-R4/E3-R6, findings
F16, F19; regression rule E3-R9).

Rules enforced over SKILL.md, README.md, every *.md under reference/,
references/ and templates/, and every scripts/*.py docstring and usage
text (every string constant — docstrings, epilogs, usage and help
lines — plus the real argparse --help output at top level and per
subcommand):

  1. no bare `python ` command — every runnable command says python3;
  2. no harness-specific home path (`~/.claude`) outside the README
     install line, which the epic Assumption exempts by name;
  3. no "auto-opened" claim about the PDF;
  4. every `scripts/X.py` a doc names exists on disk;
  5. every flag a doc command uses appears in that script's
     (subcommand-aware) --help output.

Named exemptions: only the README install line (epic Assumption — it says
where one harness installs the skill, not a path the skill writes to).
The former md_to_html.py / build_render_model.py bare-`python` exemptions
were removed by entry 3.7 after epic-render-fidelity's sweep (2.7) fixed
both scripts' usage text.

Read-only: reads docs, parses docstrings with ast, runs --help
subprocesses; writes nothing. Reuses script_help()/parse_gate() from
entry 1's tests/test_gate_chain_docs.py without editing it.
"""

import ast
import functools
import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_gate_chain_docs as gate_docs  # noqa: E402

parse_gate = gate_docs.parse_gate
script_help = gate_docs.script_help

ROOT = os.path.abspath(os.path.join(HERE, ".."))
SCRIPTS = os.path.join(ROOT, "scripts")

# The README install line exempt by name (epic Assumption): cloning into
# ~/.claude/skills/ says where one harness installs the skill; the rule
# targets paths the skill writes to or tells an agent to write to.
README_INSTALL_LINE = re.compile(r"^git clone \S+ ~/.claude/skills/\S+ ?$")

# A bare `python` *command*: the word followed by what only a command
# line puts there — a flag (-m, -c), a quoted/bracketed/variable
# argument ("$t", [script], <file>), a path start (./, ~/, /), or a
# *.py path (scripts/x.py, x.py). Prose ("written in python for",
# "Python stdlib", "python 3.10") is not a command and does not match;
# python3 never matches (the word must end at the whitespace).
BARE_PYTHON_RE = re.compile(
    r"(?<![A-Za-z0-9_-])python\s+"
    r"(?:-[A-Za-z]|[\"'$\[<{(./~]|[^\s`'\"]*\.py\b)")
DOC_SCRIPT_REF_RE = re.compile(r"scripts/([A-Za-z0-9_]+\.py)")
# A doc command: interpreter + scripts/X.py + tail, where the tail stops
# at the end of the line or the closing backtick of an inline code span.
DOC_COMMAND_RE = re.compile(
    r"(python3|python)(\s+)(scripts/[A-Za-z0-9_]+\.py)([^\n`]*)")
# Candidate subcommands: lowercase tokens inside {a,b,c} brace groups in
# a script's top-level --help (argparse usage); kept only when
# `<script> <token> --help` exits 0, so --format choice lists like
# {quick-brief,research-summary,...} are not mistaken for subcommands.
_BRACE_TOKEN_RE = re.compile(r"(?<=[{,])[a-z][a-z0-9-]*(?=[,}])")
_SUB_RE = re.compile(r"^[a-z][a-z0-9-]*$")


def doc_paths():
    """Every markdown doc in the hygiene scan set, deterministically."""
    paths = []
    for name in ("SKILL.md", "README.md"):
        path = os.path.join(ROOT, name)
        if os.path.exists(path):
            paths.append(path)
    for base in ("reference", "references", "templates"):
        base_path = os.path.join(ROOT, base)
        for dirpath, dirnames, filenames in os.walk(base_path):
            dirnames.sort()
            for filename in sorted(filenames):
                if filename.endswith(".md"):
                    paths.append(os.path.join(dirpath, filename))
    return paths


def doc_physical_lines(path):
    """(lineno, line) of the raw doc; the README install line (exempt by
    name) is filtered out. Line numbers are the physical file's."""
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    out = []
    for lineno, line in enumerate(lines, 1):
        if (os.path.basename(path) == "README.md"
                and README_INSTALL_LINE.match(line)):
            continue
        out.append((lineno, line))
    return out


def doc_logical_lines(path):
    """(first_lineno, text) with backslash-newline continuations joined,
    so one command split across physical lines is one logical line
    reported at the line it starts on (methodology.md's register-source
    example)."""
    logical = []
    start, text = None, ""
    for lineno, line in doc_physical_lines(path):
        if start is None:
            start = lineno
        if line.endswith("\\"):
            text += line[:-1] + " "
        else:
            text += line
            logical.append((start, text))
            start, text = None, ""
    if start is not None:  # file ends mid-continuation
        logical.append((start, text))
    return logical


def _try_help(script, token):
    argv = [sys.executable, os.path.join(SCRIPTS, script), token, "--help"]
    result = subprocess.run(argv, capture_output=True, text=True)
    return result if result.returncode == 0 else None


@functools.lru_cache(maxsize=None)
def script_usage_surface(script):
    """The user-visible text of one scripts/*.py: every string constant
    (module docstring, epilogs, usage and help strings — md_to_html.py
    has no argparse, its usage line is a print literal) plus the real
    argparse --help output at top level and per subcommand when the
    script supports --help."""
    path = os.path.join(SCRIPTS, script)
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    parts = [node.value for node in ast.walk(tree)
             if isinstance(node, ast.Constant) and isinstance(node.value, str)]
    argv = [sys.executable, path, "--help"]
    result = subprocess.run(argv, capture_output=True, text=True)
    if result.returncode == 0:
        parts.append(result.stdout)
        seen = set()
        for token in _BRACE_TOKEN_RE.findall(result.stdout):
            if token in seen:
                continue
            seen.add(token)
            sub_help = _try_help(script, token)
            # A --format choice token on a script without subcommands
            # re-prints the top-level help (argparse services --help
            # before rejecting the positional); only genuinely different
            # subcommand help joins the surface.
            if sub_help is not None and sub_help.stdout != result.stdout:
                parts.append(sub_help.stdout)
    return "\n".join(parts)


def script_names():
    return sorted(
        name for name in os.listdir(SCRIPTS)
        if name.endswith(".py") and os.path.isfile(os.path.join(SCRIPTS, name))
    )


def doc_commands(path):
    """[(lineno, interp, script_path, tail)] for every doc command, at
    the logical line each command starts on. The tail stops at the end of
    the line or the closing backtick of an inline code span, and at a
    shell separator (&&, ||, |, ;) so a second chained command's flags
    are not mis-attributed to the first script — the separator-cut tail
    still leaves the chained command's own `python3 scripts/…` match to
    be found and checked separately."""
    commands = []
    for lineno, text in doc_logical_lines(path):
        for m in DOC_COMMAND_RE.finditer(text):
            tail = re.split(r"\s&&|\s\|\||\s\|\s|;", m.group(4), maxsplit=1)[0]
            commands.append((lineno, m.group(1), m.group(3), tail))
    return commands


def flag_tokens(tail):
    """Flags of a command tail: tokens starting with '-' (short flags,
    long flags, =-joined values), tolerating optional notation
    '[--theme <name|path>]' — parse_gate's own extraction skips a
    bracketed token, so this widens it for doc prose."""
    flags = []
    for token in tail.split():
        token = token.lstrip("[").split("=", 1)[0]
        if token.startswith("-") and len(token) > 1:
            flags.append(token)
    return flags


def flag_in_help(flag, help_text):
    return re.search(re.escape(flag) + r"(?![\w-])", help_text) is not None


class TestDocsSayPython3(unittest.TestCase):
    """E3-R4/F19: no bare `python ` command in any scanned doc."""

    def test_no_bare_python_in_docs(self):
        failures = []
        for path in doc_paths():
            rel = os.path.relpath(path, ROOT)
            for lineno, line in doc_physical_lines(path):
                if BARE_PYTHON_RE.search(line):
                    failures.append(f"{rel}:{lineno}: {line.strip()[:90]}")
        self.assertFalse(
            failures,
            "bare `python` commands (say python3):\n  " + "\n  ".join(failures))


class TestScriptUsageText(unittest.TestCase):
    """E3-R4/F19: every script's docstring and usage text says python3."""

    def test_no_bare_python_in_script_usage_text(self):
        failures = []
        for script in script_names():
            if BARE_PYTHON_RE.search(script_usage_surface(script)):
                failures.append(script)
        self.assertFalse(
            failures,
            "usage text says bare `python` (python3 only):\n  "
            + "\n  ".join(failures))


class TestNoHarnessHomePaths(unittest.TestCase):
    """E3-R6/F16: nothing scanned writes to or names `~/.claude`, outside
    the README install line the epic Assumption exempts by name."""

    def test_no_claude_home_path_anywhere_scanned(self):
        failures = []
        for path in doc_paths():
            rel = os.path.relpath(path, ROOT)
            for lineno, line in doc_physical_lines(path):
                if "~/.claude" in line:
                    failures.append(f"{rel}:{lineno}: {line.strip()[:90]}")
        for script in script_names():
            for lineno, line in enumerate(
                    script_usage_surface(script).splitlines(), 1):
                if "~/.claude" in line:
                    failures.append(f"scripts/{script} (usage text): "
                                    f"{line.strip()[:90]}")
        self.assertFalse(
            failures,
            "harness-specific home path (rule exempts only the README "
            "install line):\n  " + "\n  ".join(failures))


class TestNoAutoOpened(unittest.TestCase):
    """E3-R4/F19: no doc or usage text says the PDF is auto-opened."""

    def test_no_auto_opened_claim(self):
        failures = []
        for path in doc_paths():
            rel = os.path.relpath(path, ROOT)
            for lineno, line in doc_physical_lines(path):
                if "auto-opened" in line:
                    failures.append(f"{rel}:{lineno}: {line.strip()[:90]}")
        for script in script_names():
            if "auto-opened" in script_usage_surface(script):
                failures.append(f"scripts/{script} (usage text)")
        self.assertFalse(
            failures,
            '"auto-opened" claims (the agent opens the PDF, no script '
            'does):\n  ' + "\n  ".join(failures))


class TestDocScriptReferences(unittest.TestCase):
    """A doc that names scripts/X.py must name a script that exists."""

    def test_every_doc_script_reference_exists(self):
        failures = []
        for path in doc_paths():
            rel = os.path.relpath(path, ROOT)
            for lineno, text in doc_logical_lines(path):
                for script in DOC_SCRIPT_REF_RE.findall(text):
                    if not os.path.isfile(os.path.join(SCRIPTS, script)):
                        failures.append(f"{rel}:{lineno}: scripts/{script}")
        self.assertFalse(
            failures,
            "docs reference scripts that do not exist:\n  "
            + "\n  ".join(failures))


class TestDocCommandFlagsResolve(unittest.TestCase):
    """Every flag a doc command uses appears in that script's real
    (subcommand-aware) --help output."""

    def test_every_doc_command_flag_exists_in_help(self):
        failures = []
        for path in doc_paths():
            rel = os.path.relpath(path, ROOT)
            for lineno, interp, script_path, tail in doc_commands(path):
                command = f"{interp} {script_path}{tail}".strip()
                if interp != "python3":
                    failures.append(f"{rel}:{lineno}: not python3: "
                                    f"{command[:90]}")
                    continue
                gate = parse_gate(command)  # script + subcommand, as parsed
                script, sub = gate["script"], gate["subcommand"]
                if not os.path.isfile(os.path.join(SCRIPTS, script)):
                    continue  # TestDocScriptReferences reports it
                help_text = script_help(script, sub)
                for flag in flag_tokens(tail):
                    if not flag_in_help(flag, help_text):
                        failures.append(
                            f"{rel}:{lineno}: {flag} missing from {script} "
                            f"{'%s --help' % sub if sub else '--help'} "
                            f"(command: {command[:70]})")
        self.assertFalse(
            failures,
            "doc commands use flags the script does not have:\n  "
            + "\n  ".join(failures))


class TestNamedExemptions(unittest.TestCase):
    """The one remaining exemption exists because of a real, named state.
    When that state changes, the exemption must go with it."""

    def test_readme_install_line_exists_exactly_once(self):
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as f:
            lines = [line for line in f.read().splitlines()
                     if README_INSTALL_LINE.match(line)]
        self.assertEqual(
            len(lines), 1,
            "the README install line exempt by name must be exactly one "
            f"git clone into ~/.claude/skills/; found {len(lines)} — "
            "update the exemption with the line")


if __name__ == "__main__":
    unittest.main()
