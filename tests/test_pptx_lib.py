"""PresentationML writer checks: a three-slide deck built under the
neutral theme and under the SVG-logo alt theme is a valid package —
every content-type override exists, every relationship target resolves,
every XML part parses, text and notes land in <a:t> runs, the theme
part carries the theme's accent color and font family, output is
byte-deterministic, and the only external relationships are
hyperlinks."""
import json
import os
import posixpath
import shutil
import struct
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
SCRIPTS = os.path.join(ROOT, "scripts")
ALT = os.path.join(HERE, "fixtures", "themes", "alt")

NS_CT = "{http://schemas.openxmlformats.org/package/2006/content-types}"
NS_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
NS_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
NS_P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
NS_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

HLINK_URL = "https://example.com/report?a=1&b=2"

sys.path.insert(0, SCRIPTS)
from pptx_lib import Presentation, color_hex, emu_px, logo_payload, png_bytes  # noqa: E402
from theme import load_theme  # noqa: E402


def make_png(width, height, rgb):
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def build_deck(theme, path):
    pres = Presentation(theme, created="2026-11-01T12:00:00Z",
                        title="Writer & <checks>", creator="pptx_lib tests")
    s1 = pres.add_slide(notes="COVER-NOTES with & <chars> and \x00\x0b stripped")
    s1.text_box(64, 90, 900, 150, [
        {"text": "TITLE-RUN one", "size": 34, "bold": True, "color": "ink"},
        {"text": "SUBTITLE-RUN two", "size": 16, "color": "muted"},
    ], line_spacing=1.1)
    s1.ellipse(64, 260, 24, 24, fill="accent")
    s1.picture_png(984, 90, 232, 155, make_png(60, 40, (79, 70, 229)))
    s2 = pres.add_slide(notes="BULLETS-NOTES")
    s2.text_box(64, 80, 1152, 500, [
        {"text": "FINDINGS-HEAD", "size": 24, "bold": True, "color": "ink",
         "bullet": False, "space_after": 8},
        {"text": "BULLET-ONE", "size": 16, "bullet": True, "line_spacing": 1.3},
        {"text": "BULLET-TWO", "size": 16, "bullet": True},
        {"runs": [{"text": "LINK-LEAD ", "size": 16},
                  {"text": "LINK-RUN", "size": 16, "color": "accent", "url": HLINK_URL}]},
    ], autofit=True)
    s3 = pres.add_slide(notes="SHAPES-NOTES\nsecond notes line")
    s3.rect(64, 80, 400, 260, fill="accent_tint1", radius=18)
    s3.rect(500, 80, 400, 260, fill=None, line={"color": "line_strong", "width_pt": 1.5})
    s3.ellipse(64, 380, 120, 120, fill="secondary")
    s3.line(64, 552, 1216, 552, color="line_strong", width_pt=2.0)
    s3.text_box(500, 380, 716, 160, [
        {"text": "SHAPE-LABEL", "size": 28, "color": "secondary_ink", "align": "center"}],
        anchor="ctr")
    pres.save(path)


def read_parts(path):
    with zipfile.ZipFile(path) as zf:
        return {name: zf.read(name) for name in zf.namelist()}


def deck_paths(label):
    themes = {"neutral": load_theme("neutral"), "alt": load_theme(ALT)}
    out = {}
    for name, theme in themes.items():
        d = tempfile.mkdtemp(prefix=f"pptx-lib-{label}-{name}-")
        out[name] = os.path.join(d, "deck.pptx")
        build_deck(theme, out[name])
    try:
        yield out["neutral"], out["alt"]
    finally:
        for path in out.values():
            shutil.rmtree(os.path.dirname(path), ignore_errors=True)


def each_deck():
    for path_pair in deck_paths("deck"):
        yield path_pair


def test_helpers():
    assert emu_px(1280) == 12192000 and emu_px(720) == 6858000 and emu_px(0) == 0
    t = load_theme("neutral")
    assert color_hex(t, "accent") == "4F46E5"
    assert color_hex(t, "accent_tint2") == "E0E7FF"
    assert color_hex(t, "#aBc123") == "ABC123"
    for bad in ("nope", "#12345", "#GGGGGG"):
        try:
            color_hex(t, bad)
            raise AssertionError(f"color_hex accepted {bad!r}")
        except ValueError:
            pass
    assert png_bytes(2, 2, (1, 2, 3))[:8] == b"\x89PNG\r\n\x1a\n"


def test_package_structure():
    for neutral, alt in each_deck():
        for path, accent, family in ((neutral, "4F46E5", "Lato"),
                                     (alt, "1E6B3A", "Iowan Old Style")):
            assert zipfile.is_zipfile(path), f"{path} is not a zip"
            parts = read_parts(path)
            assert set(parts["[Content_Types].xml"].split())  # non-empty
            overrides = ET.fromstring(parts["[Content_Types].xml"]).findall(f"{NS_CT}Override")
            assert overrides, "no content type overrides"
            for ov in overrides:
                part = ov.get("PartName").lstrip("/")
                assert part in parts, f"override {part} has no part"
            defaults = ET.fromstring(parts["[Content_Types].xml"]).findall(f"{NS_CT}Default")
            exts = {d.get("Extension") for d in defaults}
            assert {"rels", "xml", "png"} <= exts, f"missing defaults: {exts}"
            for name, data in parts.items():
                if name.endswith(".xml") or name.endswith(".rels"):
                    ET.fromstring(data)
            pres = ET.fromstring(parts["ppt/presentation.xml"])
            sld_sz = pres.find(f"{NS_P}sldSz")
            notes_sz = pres.find(f"{NS_P}notesSz")
            assert sld_sz.get("cx") == "12192000" and sld_sz.get("cy") == "6858000"
            assert notes_sz.get("cx") == "6858000" and notes_sz.get("cy") == "9144000"
            slides = pres.findall(f"{NS_P}sldIdLst/{NS_P}sldId")
            assert len(slides) == 3
            slide_parts = [n for n in parts if n.startswith("ppt/slides/slide")]
            assert len(slide_parts) == 3
            theme = parts["ppt/theme/theme1.xml"].decode("utf-8")
            assert accent in theme, f"accent {accent} missing from theme1.xml"
            assert f'typeface="{family}"' in theme
            media = read_parts(path).get("ppt/media/image1.png")
            assert media == make_png(60, 40, (79, 70, 229)), "png part not byte-identical"
            assert not any("svg" in n for n in parts), "alt SVG logo must not be embedded"


def test_relationships_resolve():
    for neutral, alt in each_deck():
        for path in (neutral, alt):
            parts = read_parts(path)
            names = set(parts)
            for name in sorted(n for n in names if n.endswith(".rels")):
                source = "" if name == "_rels/.rels" else name.replace("/_rels/", "/")[:-5]
                for rel in ET.fromstring(parts[name]).findall(f"{NS_REL}Relationship"):
                    target, rtype = rel.get("Target"), rel.get("Type")
                    if rel.get("TargetMode") == "External":
                        assert rtype.endswith("/hyperlink"), f"external rel {rtype} in {name}"
                        assert target.startswith("https://"), f"odd external target {target}"
                        continue
                    base = posixpath.dirname(source)
                    resolved = posixpath.normpath(posixpath.join(base, target))
                    assert resolved in names, f"{name} -> {target} unresolved ({resolved})"
            slide1_rels = parts["ppt/slides/_rels/slide1.xml.rels"].decode("utf-8")
            assert "notesSlide" in slide1_rels, "slide must reference its notes slide"
            hlink = [rel for rel in ET.fromstring(parts["ppt/slides/_rels/slide2.xml.rels"])
                     if rel.get("TargetMode") == "External"]
            assert len(hlink) == 1 and hlink[0].get("Target") == HLINK_URL
            slide2 = parts["ppt/slides/slide2.xml"].decode("utf-8")
            rid = hlink[0].get("Id")
            assert f'<a:hlinkClick r:id="{rid}"' in slide2


def test_text_and_notes():
    expected = {1: ["TITLE-RUN one", "SUBTITLE-RUN two"],
                2: ["FINDINGS-HEAD", "BULLET-ONE", "BULLET-TWO", "LINK-RUN"],
                3: ["SHAPE-LABEL"]}
    notes = {1: "COVER-NOTES", 2: "BULLETS-NOTES", 3: "SHAPES-NOTES"}
    for neutral, alt in each_deck():
        for path in (neutral, alt):
            parts = read_parts(path)
            for i in (1, 2, 3):
                slide = ET.fromstring(parts[f"ppt/slides/slide{i}.xml"])
                texts = [t.text or "" for t in slide.iter(f"{NS_A}t")]
                for marker in expected[i]:
                    assert marker in texts, f"slide{i} missing {marker!r}: {texts}"
                note = ET.fromstring(parts[f"ppt/notesSlides/notesSlide{i}.xml"])
                note_texts = " ".join(t.text or "" for t in note.iter(f"{NS_A}t"))
                assert notes[i] in note_texts, f"notesSlide{i} missing {notes[i]!r}"
            all_xml = b"".join(parts[n] for n in parts if n.endswith(".xml"))
            assert b"\x00" not in all_xml and b"\x0b" not in all_xml
            assert "COVER-NOTES with & <chars>".replace("&", "&amp;") \
                not in parts["ppt/notesSlides/notesSlide1.xml"].decode("utf-8")
            assert "&amp;" in parts["ppt/notesSlides/notesSlide1.xml"].decode("utf-8")


def test_shape_ids_unique():
    for neutral, alt in each_deck():
        for path in (neutral, alt):
            parts = read_parts(path)
            for name in sorted(n for n in parts if n.startswith("ppt/slides/slide")):
                ids = [sp.get("id") for sp in ET.fromstring(parts[name]).iter(f"{NS_P}cNvPr")]
                assert len(ids) == len(set(ids)), f"duplicate shape ids in {name}"


def test_deterministic():
    theme = load_theme("neutral")
    with tempfile.TemporaryDirectory() as d:
        p1, p2 = os.path.join(d, "a.pptx"), os.path.join(d, "b.pptx")
        build_deck(theme, p1)
        build_deck(theme, p2)
        with open(p1, "rb") as f1, open(p2, "rb") as f2:
            assert f1.read() == f2.read(), "two builds of the same deck differ"
        with zipfile.ZipFile(p1) as z1, zipfile.ZipFile(p2) as z2:
            assert z1.namelist() == z2.namelist()
            assert z1.namelist() == sorted(z1.namelist())
            assert all(info.date_time == (1980, 1, 1, 0, 0, 0)
                       for info in z1.infolist())


def test_logo_payload():
    assert logo_payload(load_theme("neutral")) is None
    alt = load_theme(ALT)
    assert logo_payload(alt) is None, "SVG logo without brand_name must fall back to nothing"
    with_brand = dict(alt, brand_name="Example Co")
    assert logo_payload(with_brand) == ("text", "Example Co")
    png = make_png(8, 8, (0, 0, 0))
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(ALT, "theme.json"), encoding="utf-8") as f:
            spec = json.load(f)
        spec["logo"] = "logo.png"
        with open(os.path.join(d, "theme.json"), "w", encoding="utf-8") as f:
            json.dump(spec, f)
        with open(os.path.join(d, "logo.png"), "wb") as f:
            f.write(png)
        theme = load_theme(d)
        assert logo_payload(theme) == ("png", png)


def test_empty_paragraph_list_is_valid():
    """A text box with no paragraphs (or only empty runs) still gets at
    least one <a:p>, because PowerPoint rejects a childless txBody."""
    theme = load_theme("neutral")
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "empty.pptx")
        pres = Presentation(theme, created="2026-11-01T12:00:00Z")
        s = pres.add_slide(notes="")
        s.text_box(10, 10, 500, 100, [])
        s.text_box(10, 200, 500, 100, [{"text": ""}])
        s.text_box(10, 400, 500, 100, [{"runs": []}])
        pres.save(path)
        slide = ET.fromstring(read_parts(path)["ppt/slides/slide1.xml"])
        bodies = slide.iter(f"{NS_P}txBody")
        assert bodies, "no txBody found"
        for body in bodies:
            assert body.find(f"{NS_A}p") is not None, "txBody without a paragraph"


def test_saving_twice_is_stable():
    theme = load_theme("neutral")
    with tempfile.TemporaryDirectory() as d:
        p1, p2 = os.path.join(d, "once.pptx"), os.path.join(d, "twice.pptx")
        pres = Presentation(theme, created="2026-11-01T12:00:00Z")
        s = pres.add_slide(notes="notes")
        s.text_box(10, 10, 400, 100, [{"text": "hello", "size": 20}])
        s.rect(10, 120, 100, 40, fill="fill", radius=6)
        pres.save(p1)
        pres.save(p2)
        with open(p1, "rb") as f1, open(p2, "rb") as f2:
            assert f1.read() == f2.read()


if __name__ == "__main__":
    test_helpers()
    test_package_structure()
    test_relationships_resolve()
    test_text_and_notes()
    test_shape_ids_unique()
    test_deterministic()
    test_logo_payload()
    test_empty_paragraph_list_is_valid()
    test_saving_twice_is_stable()
    print("all 9 pptx_lib tests ran and passed")
