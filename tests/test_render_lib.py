"""Engine adoption checks: the demo renders both files offline-complete
(no external src/href/@import/url references), esc() escapes HTML, the motif
SVG carries no text elements, the rendered classes are fully renamed, and no
file under skills/unjangled-research carries a trace of the engine's origin.
Origin and leak terms are read at runtime from the private, gitignored
.leak-denylist — the repo root's, or the main checkout's root when this runs
from a worktree — and both checks skip when that file is absent, so this
public file carries no private names (vendor/ dictionaries are skipped —
pre-existing corpus data)."""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
SCRIPTS = os.path.join(ROOT, "scripts")
ASSETS = os.path.join(ROOT, "assets", "render")


def leak_denylist_path():
    """The private .leak-denylist (gitignored): this checkout's root, or
    the main checkout's root when this is a git worktree. None if absent."""
    candidates = [os.path.join(ROOT, '.leak-denylist')]
    try:
        common = subprocess.run(
            ['git', '-C', ROOT, 'rev-parse', '--path-format=absolute',
             '--git-common-dir'], capture_output=True, text=True,
            timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        common = ''
    if common:
        candidates.append(os.path.join(os.path.dirname(common),
                                       '.leak-denylist'))
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def leak_hit_lines(text, denylist_path):
    """Denylist lines whose term matches text, using the leak hook's format:
    plain lines are case-insensitive fixed strings, 're:' lines are
    case-insensitive regexes, '#' lines and blank lines are ignored. Returns
    line numbers only, so a failure never prints a private term."""
    hits = []
    low = text.lower()
    with open(denylist_path, encoding="utf-8") as fh:
        for number, raw in enumerate(fh, 1):
            entry = raw.strip()
            if not entry or entry.startswith('#'):
                continue
            if entry.startswith('re:'):
                if re.search(entry[3:], text, re.IGNORECASE):
                    hits.append(number)
            elif entry.lower() in low:
                hits.append(number)
    return hits


def run_demo(d):
    r = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, "render_lib.py"), "--demo", d],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


def demo_texts():
    """Render the demo into a throwaway dir; return (page_html, deck_html)."""
    with tempfile.TemporaryDirectory() as d:
        run_demo(d)
        page_html = open(os.path.join(d, "demo-page.html"), encoding="utf-8").read()
        deck_html = open(os.path.join(d, "demo-deck.html"), encoding="utf-8").read()
        return page_html, deck_html


def test_demo_writes_both_files():
    with tempfile.TemporaryDirectory() as d:
        run_demo(d)
        for name in ("demo-page.html", "demo-deck.html"):
            path = os.path.join(d, name)
            assert os.path.isfile(path) and os.path.getsize(path) > 100, name
            assert "Sample data" in open(path, encoding="utf-8").read(), name


def test_no_http_references():
    """Self-contained output: no http:// or https:// in any src, href, @import,
    or url() of the generated files or the shipped CSS (checked as plain
    substrings, which is strictly stronger)."""
    texts = list(demo_texts())
    for fn in sorted(os.listdir(ASSETS)):
        with open(os.path.join(ASSETS, fn), encoding="utf-8") as f:
            texts.append(f.read())
    for i, text in enumerate(texts):
        assert "http://" not in text, f"http reference in output #{i}"
        assert "https://" not in text, f"https reference in output #{i}"
        assert "@import" not in text, f"@import in output #{i}"


def test_esc_escapes_html():
    sys.path.insert(0, SCRIPTS)
    from render_lib import esc
    raw = '<script>"a" & \'b\'</script>'
    out = esc(raw)
    assert "<" not in out and ">" not in out, out
    assert "&lt;script&gt;" in out and "&quot;a&quot;" in out, out
    assert "&amp;" in out and "&#x27;b&#x27;" in out, out


def test_motif_has_no_text_elements():
    sys.path.insert(0, SCRIPTS)
    from motif import motif
    svg = motif(seed=3)
    assert svg.startswith('<svg class="motif"'), svg[:40]
    assert 'aria-hidden="true"' in svg
    for tag in ("<text", "<tspan", "<title", "<desc", "<label"):
        assert tag not in svg.lower(), tag
    assert "<polygon" not in svg, "hexagon cells must not return"
    assert '<circle class="hx hx-o"' in svg and '<circle class="hx hx-fill"' in svg


def test_output_classes_renamed():
    page_html, deck_html = demo_texts()
    for text in (page_html, deck_html):
        assert "bh-" not in text, "old bh- class or token survived"
        assert "data-asset" not in text, "host-frame attribute survived"
        assert "Bridge" not in text, "host bridge code survived"
    path = leak_denylist_path()
    if path is None:
        return  # denylist absent: the literal checks above still ran
    for name, text in (("page", page_html), ("deck", deck_html)):
        hits = leak_hit_lines(text, path)
        assert not hits, f"origin traces in demo {name}: denylist lines {hits}"


def test_no_origin_traces():
    """The skill is the repo root; process material around it (archived review
    copies, benchmarks, planning docs, private research output, vendored libs)
    is out of scope for debranding. Skipped when the denylist is absent."""
    path = leak_denylist_path()
    if path is None:
        return
    skip = {"vendor", "__pycache__", "archive", "benchmarks",
            "_bmad-output", "_bmad", "bmad", "research"}
    # scripts/source_evaluator.py's credibility domain list and DOI resolver
    # map hold public publisher domains, some of which share a word with a
    # private denylist entry. Lines there that carry a quoted domain literal
    # are dropped before matching; the rest of that file and every other file
    # are scanned in full. No term is named here.
    domain_literal = re.compile(r"""['"][a-z0-9.-]+\.(?:com|org|net|edu|gov)['"]""")
    hits = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [x for x in dirnames if x not in skip and not x.startswith(".")]
        for fn in filenames:
            if fn.startswith("."):
                continue  # dot-files: the worktree .git pointer, the denylist itself
            file_path = os.path.join(dirpath, fn)
            try:
                with open(file_path, encoding="utf-8") as f:
                    text = f.read()
            except (UnicodeDecodeError, IsADirectoryError):
                continue
            rel = os.path.relpath(file_path, ROOT)
            if rel == os.path.join("scripts", "source_evaluator.py"):
                text = "\n".join(ln for ln in text.splitlines()
                                  if not domain_literal.search(ln))
            for line in leak_hit_lines(text, path):
                hits.append((rel, line))
    assert not hits, f"origin traces found (file, denylist line): {hits}"


if __name__ == "__main__":
    test_demo_writes_both_files()
    test_no_http_references()
    test_esc_escapes_html()
    test_motif_has_no_text_elements()
    test_output_classes_renamed()
    test_no_origin_traces()
    print("all 6 render_lib tests ran and passed")
