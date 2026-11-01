"""Theme QA gate checks (scripts/check_theme.py): the neutral and alt-theme
demos pass with 0 errors; fixtures with a forbidden theme color, an external
stylesheet link, an external @import, a protocol-relative src, an off-theme
font family, and text inside the motif keep-out each exit 1 with the expected
message; a plain <a href="https://..."> bibliography link and warn-only files
(off-palette color, dark surface) exit 0."""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
SCRIPTS = os.path.join(ROOT, "scripts")
CHECK = os.path.join(SCRIPTS, "check_theme.py")
QA = os.path.join(HERE, "fixtures", "qa")
ALT = os.path.join(HERE, "fixtures", "themes", "alt")
FORBIDDEN_THEME = os.path.join(QA, "qa-forbidden")


def render_demo(d, theme=None):
    cmd = [sys.executable, os.path.join(SCRIPTS, "render_lib.py"), "--demo", d]
    if theme:
        cmd += ["--theme", theme]
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def check(paths, theme=None):
    cmd = [sys.executable, CHECK] + list(paths)
    if theme:
        cmd += ["--theme", theme]
    return subprocess.run(cmd, capture_output=True, text=True)


def demo_files(d):
    return [os.path.join(d, n) for n in ("demo-page.html", "demo-deck.html")]


def test_neutral_demo_passes():
    with tempfile.TemporaryDirectory() as d:
        render_demo(d)
        r = check(demo_files(d))
        assert r.returncode == 0, r.stdout + r.stderr
        assert "ERROR" not in r.stdout, r.stdout
        assert "2 file(s), 0 error(s)" in r.stdout, r.stdout


def test_alt_demo_passes():
    with tempfile.TemporaryDirectory() as d:
        render_demo(d, ALT)
        r = check(demo_files(d), theme=ALT)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "ERROR" not in r.stdout, r.stdout


def test_forbidden_color_fails():
    r = check([os.path.join(QA, "forbidden-color.html")], theme=FORBIDDEN_THEME)
    assert r.returncode == 1, r.stdout
    assert "ERROR" in r.stdout and "#FF00FF" in r.stdout, r.stdout
    assert "retired prototype magenta" in r.stdout, r.stdout


def test_external_references_fail():
    cases = (
        ("external-link.html", "fonts.example.com"),
        ("external-import.html", "fonts.example.com"),
        ("external-proto.html", "cdn.example.com"),
    )
    for name, needle in cases:
        r = check([os.path.join(QA, name)])
        assert r.returncode == 1, (name, r.stdout)
        assert "ERROR" in r.stdout and needle in r.stdout, (name, r.stdout)


def test_font_family_not_in_theme_fails():
    r = check([os.path.join(QA, "bad-font.html")])
    assert r.returncode == 1, r.stdout
    assert "font-family" in r.stdout and "comic sans ms" in r.stdout, r.stdout


def test_text_inside_motif_fails():
    r = check([os.path.join(QA, "motif-text.html")])
    assert r.returncode == 1, r.stdout
    assert "ERROR" in r.stdout and "inside motif" in r.stdout, r.stdout


def test_motif_keepout_overlap_fails():
    r = check([os.path.join(QA, "motif-keepout.html")])
    assert r.returncode == 1, r.stdout
    assert "ERROR" in r.stdout and "keep-out" in r.stdout, r.stdout


def test_plain_hyperlink_allowed():
    r = check([os.path.join(QA, "plain-link.html")])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ERROR" not in r.stdout, r.stdout


def test_offpalette_and_dark_surface_warn_only():
    r = check([os.path.join(QA, "warn-misc.html")])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ERROR" not in r.stdout, r.stdout
    assert "not in the theme palette" in r.stdout, r.stdout
    assert "dark surface" in r.stdout, r.stdout


if __name__ == "__main__":
    test_neutral_demo_passes()
    test_alt_demo_passes()
    test_forbidden_color_fails()
    test_external_references_fail()
    test_font_family_not_in_theme_fails()
    test_text_inside_motif_fails()
    test_motif_keepout_overlap_fails()
    test_plain_hyperlink_allowed()
    test_offpalette_and_dark_surface_warn_only()
    print("all 9 check_theme tests ran and passed")
