"""Theme QA gate checks (scripts/check_theme.py): the neutral and alt-theme
demos pass with 0 errors; fixtures with a forbidden theme color, an external
stylesheet link, an external @import, a protocol-relative src, an off-theme
font family, and text inside the motif keep-out each exit 1 with the expected
message; a plain <a href="https://..."> bibliography link and warn-only files
(off-palette color, dark surface) exit 0.

Injected-markup rules (E2-R5): a fixture holding onclick=/ONERROR=/javascript:
hrefs, a javascript: iframe src and an unquoted external src= exits 1 with
each named ERROR, while a fixture holding only escaped markup text
(&lt;img onerror=x&gt;) exits 0. Report, deck and pptx renders of the hostile
fidelity fixture and the format fixtures pass with 0 errors; the same
fidelity report rendered with md_to_html's escaping patched out fails with
the injected script and event handler ERRORs. javascript: URLs in action=,
formaction=, data=, xlink:href= and a meta refresh, a raw leading control
character, an iframe srcdoc=, data: document URLs, and a src= on the
renderer's own deck.js script each fail too.

PowerPoint packages (built at runtime from pptx_lib in a system temp
dir): a clean deck and real render_pptx outputs for
every format fixture exit 0 under neutral and alt (an external hyperlink
relationship included); decks with a forbidden theme color, an external
image relationship, an off-theme typeface, an empty slide, a non-zip
file, a package part that cannot be read (corrupt member), and a package
missing ppt/presentation.xml each exit 1 with the expected message; an
off-palette srgbClr warns only. A pptx_lib deck with a file:// hyperlink
run, a render_pptx.py --model render of a hand-edited model whose sources
carry javascript:, file:// and UNC urls, a hyperlink target with a control
character, and an uppercase HTTPS:// target (allowed, scheme is
case-insensitive) round out the hyperlink rules (E2-R6)."""
import json
import os
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
SCRIPTS = os.path.join(ROOT, "scripts")
CHECK = os.path.join(SCRIPTS, "check_theme.py")
QA = os.path.join(HERE, "fixtures", "qa")
ALT = os.path.join(HERE, "fixtures", "themes", "alt")
FORBIDDEN_THEME = os.path.join(QA, "qa-forbidden")
FORMATS_DIR = os.path.join(HERE, "fixtures", "formats")
FORMAT_PATHS = sorted(
    os.path.join(FORMATS_DIR, f) for f in os.listdir(FORMATS_DIR) if f.endswith(".md")
) + [os.path.join(HERE, "fixtures", "valid_report.md")]
FIDELITY_MD = os.path.join(HERE, "fixtures", "render", "fidelity_report.md")

sys.path.insert(0, SCRIPTS)
import md_to_html  # noqa: E402
from build_render_model import build_model  # noqa: E402
from pptx_lib import Presentation  # noqa: E402
from render_deck import render_deck  # noqa: E402
from render_pptx import render_pptx  # noqa: E402
from render_report import render_report  # noqa: E402
from theme import load_theme  # noqa: E402


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


def test_injected_markup_fixture_fails():
    r = check([os.path.join(QA, "injected-markup.html")])
    assert r.returncode == 1, r.stdout
    needles = (
        "event handler attribute onclick= in <button>",
        "event handler attribute onerror= in <img>",
        "javascript: URL in <a> href=",
        "javascript: URL in <iframe> src=",
        "external resource in src= (//cdn.example.com/pixel.png)",
    )
    for needle in needles:
        assert "ERROR" in r.stdout and needle in r.stdout, (needle, r.stdout)
    # the commented-out script and the quoted attribute value are inert
    assert "injected script element" not in r.stdout, r.stdout
    assert "onerror= in <p>" not in r.stdout, r.stdout


def test_escaped_markup_not_flagged():
    r = check([os.path.join(QA, "escaped-markup.html")])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ERROR" not in r.stdout, r.stdout


def test_fidelity_renders_pass():
    for path in [FIDELITY_MD] + FORMAT_PATHS:
        with open(path, encoding="utf-8") as f:
            model = build_model(f.read())
        with tempfile.TemporaryDirectory(prefix="rf-qa-render-") as d:
            outputs = []
            report = os.path.join(d, "report.html")
            with open(report, "w", encoding="utf-8") as f:
                f.write(render_report(model, theme="neutral"))
            outputs.append(report)
            deck = os.path.join(d, "deck.html")
            with open(deck, "w", encoding="utf-8") as f:
                f.write(render_deck(model, theme="neutral"))
            outputs.append(deck)
            pptx = os.path.join(d, "deck.pptx")
            render_pptx(model, pptx, theme="neutral")
            outputs.append(pptx)
            for out in outputs:
                r = check([out])
                assert r.returncode == 0, (path, out, r.stdout + r.stderr)
                assert "ERROR" not in r.stdout, (path, out, r.stdout)


def test_fidelity_render_without_escaping_fails():
    with open(FIDELITY_MD, encoding="utf-8") as f:
        md = f.read()
    real_escape = md_to_html.escape
    md_to_html.escape = lambda s, quote=True: s
    try:
        html = render_report(build_model(md), theme="neutral")
    finally:
        md_to_html.escape = real_escape
    with tempfile.TemporaryDirectory(prefix="rf-qa-hostile-") as d:
        out = os.path.join(d, "unescaped.html")
        with open(out, "w", encoding="utf-8") as f:
            f.write(html)
        r = check([out])
        assert r.returncode == 1, r.stdout
        assert "injected script element" in r.stdout, r.stdout
        assert "event handler attribute onerror= in <img>" in r.stdout, r.stdout


def test_deck_js_unreadable_fails_strict():
    """When assets/render/deck.js cannot be read, no script is recognised:
    a clean deck render's own script is then reported (strict-by-default)."""
    with open(FIDELITY_MD, encoding="utf-8") as f:
        model = build_model(f.read())
    import check_theme as gate
    real_path = gate.DECK_JS_PATH
    gate.DECK_JS_PATH = os.path.join(real_path + ".missing")
    try:
        with tempfile.TemporaryDirectory(prefix="rf-qa-nojs-") as d:
            out = os.path.join(d, "deck.html")
            with open(out, "w", encoding="utf-8") as f:
                f.write(render_deck(model, theme="neutral"))
            errs, warns = gate.check_file(out, load_theme("neutral"))
    finally:
        gate.DECK_JS_PATH = real_path
    assert not warns, warns
    assert any(e.startswith("injected script element") for e in errs), errs


def pptx_workspace():
    return tempfile.TemporaryDirectory(prefix="rf-qa-pptx-")


def build_clean_deck(theme, path, extra_run=None):
    """A two-slide deck with palette colors, theme fonts, one source
    hyperlink, and optionally one extra run (a bad color or font)."""
    pres = Presentation(theme, created="2026-11-01T12:00:00Z",
                        title="QA clean deck", creator="check_theme tests")
    s1 = pres.add_slide(notes="Cover notes.")
    s1.text_box(64, 90, 900, 150, [
        {"text": "Clean deck", "size": 30, "bold": True, "color": "ink"},
        {"text": "A subtitle in the body color", "size": 14, "color": "body"},
    ])
    s2 = pres.add_slide(notes="Bullets and a source link.")
    paras = [
        {"text": "What is checked", "size": 18, "bold": True, "color": "ink",
         "bullet": False},
        {"text": "Palette colors and the theme font", "size": 14,
         "color": "body", "bullet": True},
        {"text": "Linked source", "size": 14, "color": "accent_ink",
         "bullet": True, "url": "https://example.com/source"},
    ]
    if extra_run:
        paras.append(extra_run)
    s2.text_box(64, 90, 1152, 300, paras)
    pres.save(path)
    return path


def build_empty_slide_deck(theme, path):
    """Slide 2 carries only a shape, so it has no <a:t> text."""
    pres = Presentation(theme, created="2026-11-01T12:00:00Z", title="QA empty slide")
    s1 = pres.add_slide(notes="Cover notes.")
    s1.text_box(64, 90, 900, 100, [{"text": "Title only", "size": 30, "color": "ink"}])
    s2 = pres.add_slide(notes="No text on this slide.")
    s2.rect(64, 90, 400, 200, fill="accent_tint1")
    pres.save(path)
    return path


def rebuild_zip(src, dst, drop=(), replace=None):
    """Copy the package, dropping named parts and rewriting one part
    through replace(bytes) -> bytes."""
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            if info.filename in drop:
                continue
            data = zin.read(info.filename)
            if replace and info.filename == replace[0]:
                data = replace[1](data)
            zout.writestr(info, data)


EXTERNAL_IMAGE_REL = (
    b'<Relationship Id="rIdExternal" '
    b'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
    b'Target="https://images.example.com/pic.png" TargetMode="External"/>')


def test_unclosed_script_fails():
    """A <script> with no close tag runs to EOF in a browser; the gate
    reports it instead of waiting for a closing tag that never comes."""
    with tempfile.TemporaryDirectory(prefix="rf-qa-unclosed-") as d:
        out = os.path.join(d, "unclosed.html")
        with open(out, "w", encoding="utf-8") as f:
            f.write('<!DOCTYPE html><html><body><p>hi</p>'
                    '<script>alert(1)\n<p>trailing text</p></body></html>')
        r = check([out])
        assert r.returncode == 1, r.stdout
        assert "injected script element (unclosed <script> tag)" in r.stdout, r.stdout


def test_deck_js_open_tag_handler_fails():
    """The recognised deck.js body does not whitewash its own open tag: an
    onload= on the renderer's script still runs and still errors."""
    with open(FIDELITY_MD, encoding="utf-8") as f:
        model = build_model(f.read())
    html = render_deck(model, theme="neutral").replace("<script>", '<script onload=alert(1)>', 1)
    with tempfile.TemporaryDirectory(prefix="rf-qa-jsopen-") as d:
        out = os.path.join(d, "deck.html")
        with open(out, "w", encoding="utf-8") as f:
            f.write(html)
        r = check([out])
        assert r.returncode == 1, r.stdout
        assert "event handler attribute onload= in <script>" in r.stdout, r.stdout
        assert "not the renderer's deck.js" not in r.stdout, r.stdout


LIVE_URL_CASES = (
    ('<form action="javascript:alert(1)"><button>go</button></form>',
     "javascript: URL in <form> action="),
    ('<form><button formaction=JavaScript:alert(1)>go</button></form>',
     "javascript: URL in <button> formaction="),
    ('<object data="javascript:alert(1)"></object>',
     "javascript: URL in <object> data="),
    ('<meta http-equiv=refresh content="0;url=javascript:alert(1)">',
     "javascript: URL in <meta> content="),
    ('<svg><a xlink:href="javascript:alert(1)"><text>x</text></a></svg>',
     "javascript: URL in <a> xlink:href="),
    ('<a href="\x01javascript:alert(1)">x</a>',
     "javascript: URL in <a> href="),
    ('<iframe srcdoc="&lt;script&gt;alert(1)&lt;/script&gt;"></iframe>',
     "inline document attribute srcdoc= in <iframe>"),
    ('<iframe src="data:text/html,&lt;script&gt;alert(1)&lt;/script&gt;"></iframe>',
     "data: document URL in <iframe> src="),
    ('<object data="data:image/svg+xml,&lt;svg onload=alert(1)&gt;"></object>',
     "data: document URL in <object> data="),
    ('<a href="data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==">x</a>',
     "data: document URL in <a> href="),
)


def test_live_url_attributes_fail():
    """Review bypasses (2026-11-19): javascript: in action/formaction/data/
    xlink:href/meta refresh, a raw leading C0 control, an iframe srcdoc, and
    data: URLs that carry a document each exit 1 with a named ERROR."""
    with tempfile.TemporaryDirectory(prefix="rf-qa-liveurl-") as d:
        for i, (markup, needle) in enumerate(LIVE_URL_CASES):
            out = os.path.join(d, f"case{i}.html")
            with open(out, "w", encoding="utf-8") as f:
                f.write('<!DOCTYPE html><html><body><main><p>x</p>'
                        f'{markup}</main></body></html>')
            r = check([out])
            assert r.returncode == 1, (markup, r.stdout)
            assert "ERROR" in r.stdout and needle in r.stdout, (markup, needle, r.stdout)


def test_deck_js_with_src_fails():
    """A src= on the renderer's own script replaces its body with other
    code, so the byte-identical deck.js body no longer vouches for it."""
    with open(FIDELITY_MD, encoding="utf-8") as f:
        model = build_model(f.read())
    html = render_deck(model, theme="neutral").replace(
        "<script>", '<script src="payload.js">', 1)
    with tempfile.TemporaryDirectory(prefix="rf-qa-jssrc-") as d:
        out = os.path.join(d, "deck.html")
        with open(out, "w", encoding="utf-8") as f:
            f.write(html)
        r = check([out])
        assert r.returncode == 1, r.stdout
        assert "src= on the renderer's deck.js script" in r.stdout, r.stdout


def test_pptx_clean_deck_passes():
    with pptx_workspace() as d:
        p = build_clean_deck(load_theme("neutral"), os.path.join(d, "clean.pptx"))
        r = check([p])
        assert r.returncode == 0, r.stdout + r.stderr
        assert "ERROR" not in r.stdout, r.stdout


def test_pptx_hyperlink_relationship_allowed():
    with pptx_workspace() as d:
        p = build_clean_deck(load_theme("neutral"), os.path.join(d, "link.pptx"))
        with zipfile.ZipFile(p) as zf:
            rels = zf.read("ppt/slides/_rels/slide2.xml.rels").decode("utf-8")
        assert 'TargetMode="External"' in rels and "/hyperlink" in rels, rels
        r = check([p])
        assert r.returncode == 0, r.stdout + r.stderr
        assert "ERROR" not in r.stdout, r.stdout


def test_pptx_uppercase_https_hyperlink_allowed():
    with pptx_workspace() as d:
        clean = build_clean_deck(load_theme("neutral"), os.path.join(d, "clean.pptx"))
        upper = os.path.join(d, "upper.pptx")
        rebuild_zip(clean, upper, replace=("ppt/slides/_rels/slide2.xml.rels",
                                           lambda data: data.replace(
                                               b"https://example.com/source",
                                               b"HTTPS://example.com/source")))
        r = check([upper])
        assert r.returncode == 0, r.stdout + r.stderr
        assert "ERROR" not in r.stdout, r.stdout


def test_pptx_non_http_hyperlink_fails():
    with pptx_workspace() as d:
        pres = Presentation(load_theme("neutral"), created="2026-11-01T12:00:00Z",
                            title="QA bad hyperlink")
        s = pres.add_slide(notes="A local link.")
        s.text_box(64, 90, 1152, 100, [
            {"text": "Local file link", "size": 14, "color": "accent_ink",
             "url": "file:///etc/passwd"}])
        p = os.path.join(d, "filelink.pptx")
        pres.save(p)
        r = check([p])
        assert r.returncode == 1, r.stdout
        assert "hyperlink target is not http(s)" in r.stdout, r.stdout
        assert "file:///etc/passwd" in r.stdout, r.stdout
        assert "ppt/slides/_rels/slide1.xml.rels" in r.stdout, r.stdout


def test_pptx_hyperlink_control_character_fails():
    with pptx_workspace() as d:
        clean = build_clean_deck(load_theme("neutral"), os.path.join(d, "clean.pptx"))
        bad = os.path.join(d, "tabbed.pptx")
        # a literal tab in an XML attribute is normalized to a space; a
        # character reference smuggles a real tab through the parser, and
        # browsers strip it before reading the scheme
        rebuild_zip(clean, bad, replace=("ppt/slides/_rels/slide2.xml.rels",
                                         lambda data: data.replace(
                                             b"https://example.com/source",
                                             b"http://example.com/so&#x9;urce")))
        r = check([bad])
        assert r.returncode == 1, r.stdout
        assert "hyperlink target contains a control character" in r.stdout, r.stdout


def test_pptx_model_non_http_sources_fail():
    """The 2.5 review repro: render_pptx.py --model writes a hand-edited
    model's javascript:, file:// and UNC source urls into external hyperlink
    relationships, and check_pptx must name all three."""
    with open(FORMAT_PATHS[0], encoding="utf-8") as f:
        model = build_model(f.read())
    model["sources"] = [
        {"n": 1, "title": "Scripted source", "url": "javascript:alert(1)",
         "publisher": None},
        {"n": 2, "title": "Local file source", "url": "file:///etc/passwd",
         "publisher": None},
        {"n": 3, "title": "SMB share source", "url": "\\\\host\\share\\x",
         "publisher": None},
    ]
    with pptx_workspace() as d:
        model_json = os.path.join(d, "model.json")
        with open(model_json, "w", encoding="utf-8") as f:
            json.dump(model, f)
        out = os.path.join(d, "model.pptx")
        r = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "render_pptx.py"),
             "--model", model_json, "--out", out],
            capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        r = check([out])
        assert r.returncode == 1, r.stdout
        assert "hyperlink target is not http(s)" in r.stdout, r.stdout
        for target in ("javascript:alert(1)", "file:///etc/passwd"):
            assert target in r.stdout, (target, r.stdout)
        assert repr("\\\\host\\share\\x") in r.stdout, r.stdout


def test_pptx_renderer_outputs_pass():
    for path in FORMAT_PATHS:
        with open(path, encoding="utf-8") as f:
            model = build_model(f.read())
        with pptx_workspace() as d:
            neutral = os.path.join(d, "neutral.pptx")
            alt = os.path.join(d, "alt.pptx")
            render_pptx(model, neutral, theme="neutral")
            render_pptx(model, alt, theme=ALT)
            for out, theme_arg in ((neutral, None), (alt, ALT)):
                r = check([out], theme=theme_arg)
                assert r.returncode == 0, (path, r.stdout + r.stderr)
                assert "ERROR" not in r.stdout, (path, r.stdout)


def test_pptx_forbidden_color_fails():
    with pptx_workspace() as d:
        p = build_clean_deck(load_theme(FORBIDDEN_THEME), os.path.join(d, "forbidden.pptx"),
                             extra_run={"text": "Off-color run", "size": 14,
                                        "color": "#FF00FF", "bullet": True})
        r = check([p], theme=FORBIDDEN_THEME)
        assert r.returncode == 1, r.stdout
        assert "#FF00FF" in r.stdout and "retired prototype magenta" in r.stdout, r.stdout
        assert "ppt/slides/slide2.xml" in r.stdout, r.stdout


def test_pptx_external_image_relationship_fails():
    with pptx_workspace() as d:
        clean = build_clean_deck(load_theme("neutral"), os.path.join(d, "clean.pptx"))
        bad = os.path.join(d, "external-image.pptx")
        rebuild_zip(clean, bad, replace=("ppt/slides/_rels/slide1.xml.rels",
                                         lambda data: data.replace(
                                             b"</Relationships>",
                                             EXTERNAL_IMAGE_REL + b"</Relationships>")))
        r = check([bad])
        assert r.returncode == 1, r.stdout
        assert "ERROR" in r.stdout and "external relationship" in r.stdout, r.stdout
        assert "images.example.com" in r.stdout, r.stdout


def test_pptx_off_theme_font_fails():
    with pptx_workspace() as d:
        clean = build_clean_deck(load_theme("neutral"), os.path.join(d, "clean.pptx"))
        bad = os.path.join(d, "bad-font.pptx")
        rebuild_zip(clean, bad, replace=("ppt/slides/slide1.xml",
                                         lambda data: data.replace(
                                             b'<a:latin typeface="Lato"/>',
                                             b'<a:latin typeface="Comic Sans MS"/>', 1)))
        r = check([bad])
        assert r.returncode == 1, r.stdout
        assert "typeface 'Comic Sans MS'" in r.stdout, r.stdout
        assert "not declared in theme" in r.stdout, r.stdout


def test_pptx_empty_slide_fails():
    with pptx_workspace() as d:
        p = build_empty_slide_deck(load_theme("neutral"), os.path.join(d, "empty.pptx"))
        r = check([p])
        assert r.returncode == 1, r.stdout
        assert "ERROR" in r.stdout and "has no text" in r.stdout, r.stdout
        assert "ppt/slides/slide2.xml" in r.stdout, r.stdout


def test_pptx_broken_package_fails():
    with pptx_workspace() as d:
        plain = os.path.join(d, "plain.pptx")
        with open(plain, "wb") as f:
            f.write(b"clearly not a zip archive")
        r = check([plain])
        assert r.returncode == 1, r.stdout
        assert "not a valid zip" in r.stdout, r.stdout
        clean = build_clean_deck(load_theme("neutral"), os.path.join(d, "clean.pptx"))
        gutted = os.path.join(d, "gutted.pptx")
        rebuild_zip(clean, gutted, drop=("ppt/presentation.xml",))
        r = check([gutted])
        assert r.returncode == 1, r.stdout
        assert "missing ppt/presentation.xml" in r.stdout, r.stdout


def corrupt_member(src, dst, victim):
    """Re-emit the package STORED and flip one byte of victim's stored
    data, so the zip opens but reading victim fails its CRC check."""
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_STORED) as zout:
        for info in zin.infolist():
            zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            zi.external_attr = info.external_attr
            zout.writestr(zi, zin.read(info.filename))
    with open(dst, "r+b") as f:
        blob = f.read()
        hdr = blob.find(b"PK\x03\x04")
        while hdr != -1:
            name_len = int.from_bytes(blob[hdr + 26:hdr + 28], "little")
            extra_len = int.from_bytes(blob[hdr + 28:hdr + 30], "little")
            name = blob[hdr + 30:hdr + 30 + name_len]
            if name == victim.encode():
                off = hdr + 30 + name_len + extra_len + 4
                blob = blob[:off] + bytes([blob[off] ^ 0xFF]) + blob[off + 1:]
                f.seek(0)
                f.write(blob)
                return
            hdr = blob.find(b"PK\x03\x04", hdr + 1)
    raise AssertionError(f"{victim} not found in {src}")


def test_pptx_corrupt_member_fails():
    with pptx_workspace() as d:
        clean = build_clean_deck(load_theme("neutral"), os.path.join(d, "clean.pptx"))
        for victim in ("_rels/.rels", "ppt/slides/slide1.xml"):
            bad = os.path.join(d, "corrupt_" + victim.replace("/", "_").replace(".", "_") + ".pptx")
            corrupt_member(clean, bad, victim)
            r = check([bad])
            assert r.returncode == 1, (victim, r.stdout + r.stderr)
            assert "Traceback" not in r.stdout + r.stderr, (victim, r.stderr)
            assert "cannot be read" in r.stdout, (victim, r.stdout)


def test_pptx_offpalette_color_warns_only():
    with pptx_workspace() as d:
        p = build_clean_deck(load_theme("neutral"), os.path.join(d, "offpalette.pptx"),
                             extra_run={"text": "Off-palette run", "size": 14,
                                        "color": "#8B5CF3", "bullet": True})
        r = check([p])
        assert r.returncode == 0, r.stdout + r.stderr
        assert "ERROR" not in r.stdout, r.stdout
        assert "not in the theme palette" in r.stdout, r.stdout


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
    test_injected_markup_fixture_fails()
    test_escaped_markup_not_flagged()
    test_unclosed_script_fails()
    test_deck_js_open_tag_handler_fails()
    test_live_url_attributes_fail()
    test_deck_js_with_src_fails()
    test_fidelity_renders_pass()
    test_fidelity_render_without_escaping_fails()
    test_deck_js_unreadable_fails_strict()
    test_pptx_clean_deck_passes()
    test_pptx_hyperlink_relationship_allowed()
    test_pptx_uppercase_https_hyperlink_allowed()
    test_pptx_non_http_hyperlink_fails()
    test_pptx_hyperlink_control_character_fails()
    test_pptx_model_non_http_sources_fail()
    test_pptx_renderer_outputs_pass()
    test_pptx_forbidden_color_fails()
    test_pptx_external_image_relationship_fails()
    test_pptx_off_theme_font_fails()
    test_pptx_empty_slide_fails()
    test_pptx_broken_package_fails()
    test_pptx_corrupt_member_fails()
    test_pptx_offpalette_color_warns_only()
    print("all 32 check_theme tests ran and passed")
