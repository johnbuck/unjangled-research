"""Engine adoption checks: the demo renders both files offline-complete
(no external src/href/@import/url references), esc() escapes HTML, the motif
SVG carries no text elements, the rendered classes are fully renamed, and no
file under skills/unjangled-research carries a trace of the engine's origin
(forbidden names are built by concatenation so this file cannot match its
own pattern; vendor/ dictionaries are skipped — pre-existing corpus data)."""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
SCRIPTS = os.path.join(ROOT, "scripts")
ASSETS = os.path.join(ROOT, "assets", "render")

BAD_WORDS = ["bu" + "zz", "gle" + "an", "hon" + "ey", "rx" + "compare"]
GLN = "data-gle" + "an"  # attribute name from the dropped host integration, built so this file cannot match itself


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
        assert GLN not in text and "data-asset" not in text, "host-frame attribute survived"
        assert "Bridge" not in text, "host bridge code survived"


def test_no_origin_traces():
    """The skill is the repo root; process material around it (archived review
    copies, benchmarks, planning docs, private research output, vendored libs)
    is out of scope for debranding."""
    skip = {"vendor", "__pycache__", "archive", "benchmarks",
            "_bmad-output", "_bmad", "bmad", "research"}
    hits = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [x for x in dirnames if x not in skip and not x.startswith(".")]
        for fn in filenames:
            path = os.path.join(dirpath, fn)
            try:
                with open(path, encoding="utf-8") as f:
                    text = f.read().lower()
            except (UnicodeDecodeError, IsADirectoryError):
                continue
            for w in BAD_WORDS:
                if w in text:
                    hits.append((os.path.relpath(path, ROOT), w))
    assert not hits, f"origin traces found: {hits}"


if __name__ == "__main__":
    test_demo_writes_both_files()
    test_no_http_references()
    test_esc_escapes_html()
    test_motif_has_no_text_elements()
    test_output_classes_renamed()
    test_no_origin_traces()
    print("all 6 render_lib tests ran and passed")
