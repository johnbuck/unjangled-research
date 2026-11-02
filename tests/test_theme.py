"""Theme contract checks: the demo rendered under neutral and under a second
theme folder differs in the :root block, font family, footer label, logo
presence, and motif presence with no code change; a malformed theme.json
raises a ValueError naming the bad key; the shipped CSS carries no hex
literal; generated output stays free of external references; the neutral
theme's embedded fonts percent-decode and base64-decode to valid WOFF."""
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
SCRIPTS = os.path.join(ROOT, "scripts")
RENDER_CSS = os.path.join(ROOT, "assets", "render")
FONTS_CSS = os.path.join(ROOT, "themes", "neutral", "fonts.css")
ALT = os.path.join(HERE, "fixtures", "themes", "alt")

HEX_IN_CSS = re.compile(r"#[0-9a-fA-F]{3,8}\b")
FONT_DATA_URI = re.compile(r"url\(data:font/woff;base64,([A-Za-z0-9+/=%]+)\)")


def run_demo(d, theme=None):
    cmd = [sys.executable, os.path.join(SCRIPTS, "render_lib.py"), "--demo", d]
    if theme:
        cmd += ["--theme", theme]
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    with open(os.path.join(d, "demo-page.html"), encoding="utf-8") as f:
        page_html = f.read()
    with open(os.path.join(d, "demo-deck.html"), encoding="utf-8") as f:
        deck_html = f.read()
    return page_html, deck_html


def _root_block(text):
    i = text.index(":root{")
    return text[i:text.index("}", i)]


def test_neutral_theme_helpers():
    sys.path.insert(0, SCRIPTS)
    from theme import load_theme, css_vars, font_css, logo_data_uri, footer_label
    t = load_theme("neutral")
    block = css_vars(t)
    assert block.startswith(":root{--rf-surface:#FFFFFF")
    assert "--rf-accent:#4F46E5" in block and '"Lato"' in block
    fonts = font_css(t)
    assert fonts.lstrip().startswith("@font-face") and "Lato Brand" not in fonts
    assert logo_data_uri(t) is None
    assert footer_label(t, "Report", "Q4") == "Report — Q4"


def test_alt_theme_changes_rendered_output():
    with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
        n_page, n_deck = run_demo(d1)
        a_page, a_deck = run_demo(d2, ALT)
        for neutral, alt in ((n_page, a_page), (n_deck, a_deck)):
            n_root, a_root = _root_block(neutral), _root_block(alt)
            assert n_root != a_root, ":root block did not follow the theme"
            assert "--rf-accent:#4F46E5" in n_root
            assert "--rf-accent:#1E6B3A" in a_root
            assert '"Lato"' in n_root and '"Iowan Old Style"' in a_root
        assert "@font-face" in n_page and "@font-face" not in a_page
        assert "Sample Research Dashboard — Sample data" in n_page
        assert "Sample data · Sample Research Dashboard" in a_page
        assert 'src="data:image/svg+xml;base64,' in a_page and 'class="rf-logo"' in a_page
        assert 'data:image' not in n_page
        assert 'data:image/svg+xml;base64,' in a_deck
        for neutral in (n_page, n_deck):
            assert 'class="motif"' in neutral, "neutral must render the motif grid"
        for alt in (a_page, a_deck):
            assert 'class="motif"' not in alt, "alt disables the motif"


def test_malformed_theme_names_bad_key():
    sys.path.insert(0, SCRIPTS)
    from theme import load_theme
    breakages = [
        ("colors.accent_tints", lambda t: t["colors"].__setitem__("accent_tints", ["#EEEEEE"])),
        ("colors.accent", lambda t: t["colors"].__setitem__("accent", "blue")),
        ("colors.secondary_tints", lambda t: t["colors"].__setitem__("secondary_tints", ["#111111", "#222222", "#333333", "#444444", "x"])),
        ("footer", lambda t: t.pop("footer")),
        ("motif.line", lambda t: t["motif"].__setitem__("line", "#XYZXYZ")),
        ("motif.ratio", lambda t: t["motif"].__setitem__("ratio", 2)),
        ("fonts.family", lambda t: t["fonts"].__setitem__("family", "")),
    ]
    for key_path, break_it in breakages:
        with tempfile.TemporaryDirectory() as d:
            for fn in os.listdir(ALT):
                shutil.copyfile(os.path.join(ALT, fn), os.path.join(d, fn))
            path = os.path.join(d, "theme.json")
            with open(path, encoding="utf-8") as f:
                t = json.load(f)
            break_it(t)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(t, f)
            raised = ""
            try:
                load_theme(d)
            except ValueError as e:
                raised = str(e)
            assert key_path in raised, f"{key_path} not named in error: {raised!r}"


def test_no_hex_literal_in_render_css():
    for fn in sorted(os.listdir(RENDER_CSS)):
        with open(os.path.join(RENDER_CSS, fn), encoding="utf-8") as f:
            text = f.read()
        assert not HEX_IN_CSS.search(text), f"hex literal survived in {fn}"


def test_output_has_no_external_references():
    with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
        for page, deck in (run_demo(d1), run_demo(d2, ALT)):
            for i, text in enumerate((page, deck)):
                assert "http://" not in text, f"http reference in output #{i}"
                assert "https://" not in text, f"https reference in output #{i}"
                assert "@import" not in text, f"@import in output #{i}"


def test_embedded_fonts_decode_to_woff():
    # fonts.css may percent-encode base64 characters (a byte-preserving
    # escape); every data URI must still percent-decode + base64-decode to a
    # WOFF payload, so the escape can never silently corrupt the font.
    with open(FONTS_CSS, encoding="utf-8") as f:
        text = f.read()
    payloads = FONT_DATA_URI.findall(text)
    assert payloads, "no embedded font data URIs found in fonts.css"
    for p in payloads:
        raw = base64.b64decode(urllib.parse.unquote(p, errors="strict"))
        assert raw[:4] == b"wOFF", "embedded font did not decode to WOFF magic"


if __name__ == "__main__":
    test_neutral_theme_helpers()
    test_alt_theme_changes_rendered_output()
    test_malformed_theme_names_bad_key()
    test_no_hex_literal_in_render_css()
    test_output_has_no_external_references()
    test_embedded_fonts_decode_to_woff()
    print("all 6 theme tests ran and passed")
