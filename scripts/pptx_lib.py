"""PresentationML writer: a standard-library-only builder for native,
editable .pptx packages.

A Presentation is created from a theme loaded with theme.load_theme,
slides are added with add_slide(notes=...) and drawn with the Slide
methods (text_box, rect, ellipse, line, picture_png) using the HTML
deck's 1280x720 pixel grid through emu_px(), and save(path) writes a
byte-deterministic 16:9 package (12192000 x 6858000 EMU). The package
carries one slide master, a blank slide layout, a theme part mapped from
theme.json (dk1=ink, lt1=surface, dk2=body, lt2=fill, accent1=accent,
accent2=secondary, accent3..6 from the darker accent/secondary tints,
hlink=accent_ink, folHlink=secondary_ink, major/minor latin =
fonts.family), a notes master with its own theme part, and one notes
slide per slide. Colors are always written as srgbClr resolved from the
theme; logo_payload() maps a theme logo to a PNG payload, the
brand_name text, or nothing.

CLI demo deck writer:  python3 pptx_lib.py --demo <dir>
"""
import os
import re
import struct
import sys
import zipfile
import zlib
from hashlib import sha1
from xml.sax.saxutils import escape

NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG_RELS = "http://schemas.openxmlformats.org/package/2006/relationships"

RT = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL_SLIDE = RT + "/slide"
REL_SLIDE_MASTER = RT + "/slideMaster"
REL_SLIDE_LAYOUT = RT + "/slideLayout"
REL_NOTES_MASTER = RT + "/notesMaster"
REL_NOTES_SLIDE = RT + "/notesSlide"
REL_THEME = RT + "/theme"
REL_PRES_PROPS = RT + "/presProps"
REL_VIEW_PROPS = RT + "/viewProps"
REL_TABLE_STYLES = RT + "/tableStyles"
REL_IMAGE = RT + "/image"
REL_HLINK = RT + "/hyperlink"
REL_OFFICE_DOCUMENT = RT + "/officeDocument"
REL_CORE_PROPS = "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties"
REL_EXT_PROPS = RT + "/extended-properties"

CT_PRESENTATION = "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"
CT_SLIDE = "application/vnd.openxmlformats-officedocument.presentationml.slide+xml"
CT_SLIDE_MASTER = "application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"
CT_SLIDE_LAYOUT = "application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"
CT_NOTES_MASTER = "application/vnd.openxmlformats-officedocument.presentationml.notesMaster+xml"
CT_NOTES_SLIDE = "application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml"
CT_THEME = "application/vnd.openxmlformats-officedocument.theme+xml"
CT_PRES_PROPS = "application/vnd.openxmlformats-officedocument.presentationml.presProps+xml"
CT_VIEW_PROPS = "application/vnd.openxmlformats-officedocument.presentationml.viewProps+xml"
CT_TABLE_STYLES = "application/vnd.openxmlformats-officedocument.presentationml.tableStyles+xml"
CT_CORE = "application/vnd.openxmlformats-package.core-properties+xml"
CT_APP = "application/vnd.openxmlformats-officedocument.extended-properties+xml"
CT_RELS = "application/vnd.openxmlformats-package.relationships+xml"
CT_XML = "application/xml"
CT_PNG = "image/png"

EMU_PER_PX = 9525
SLIDE_W_EMU = 12192000
SLIDE_H_EMU = 6858000
NOTES_W_EMU = 6858000
NOTES_H_EMU = 9144000
ZIP_DATE = (1980, 1, 1, 0, 0, 0)
DEFAULT_CREATED = "2026-01-01T00:00:00Z"
XMLDECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'

_ILL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")
_HEX6 = re.compile(r"^[0-9a-fA-F]{6}$")
_ALIGN = {"left": "l", "l": "l", "center": "ctr", "centre": "ctr", "ctr": "ctr",
          "middle": "ctr", "right": "r", "r": "r", "justify": "just", "just": "just"}
_ANCHOR = {"t": "t", "top": "t", "ctr": "ctr", "center": "ctr", "centre": "ctr",
           "middle": "ctr", "b": "b", "bottom": "b"}

_RUN_KEYS = ("text", "size", "bold", "italic", "underline", "color", "font", "url")
_PARA_KEYS = ("align", "bullet", "line_spacing", "space_before", "space_after")


def _clean(text):
    """Strip characters XML 1.0 forbids."""
    return _ILL.sub("", str(text))


def _esc(text):
    return escape(_clean(text))


def _att(text):
    return escape(_clean(text), {'"': "&quot;"})


def emu_px(px):
    """Convert a 1280x720 pixel-grid coordinate to EMU (9525 EMU per px)."""
    return int(round(px * EMU_PER_PX))


def emu_pt(pt):
    """Convert points to EMU (12700 EMU per pt)."""
    return int(round(pt * 12700))


def color_hex(theme, color):
    """Resolve a color to six uppercase hex digits: a theme key name
    ("ink", "accent", "accent_tint2", "secondary_ink", ...), "#RRGGBB",
    or "RRGGBB"."""
    c = theme["colors"]
    text = str(color).strip()
    if text.startswith("#"):
        value = text[1:]
        if _HEX6.match(value):
            return value.upper()
        raise ValueError(f"bad color {color!r}: expected #RRGGBB or a theme key")
    palette = {k: v for k, v in c.items() if k not in ("accent_tints", "secondary_tints")}
    for group, prefix in (("accent_tints", "accent"), ("secondary_tints", "secondary")):
        for i, value in enumerate(c[group], 1):
            palette[f"{prefix}_tint{i}"] = value
    if text in palette:
        return palette[text].lstrip("#").upper()
    raise ValueError(f"unknown color {color!r}: expected a theme key or #RRGGBB")


def _srgb(theme, color):
    return f'<a:srgbClr val="{color_hex(theme, color)}"/>'


def _solid_fill(theme, color):
    return f"<a:solidFill>{_srgb(theme, color)}</a:solidFill>"


def logo_payload(theme):
    """The theme logo in a PowerPoint-usable form: ("png", bytes) when the
    logo is a PNG, ("text", brand_name) when it is an SVG and the theme
    names a brand, else None."""
    logo = theme.get("logo")
    if not logo:
        return None
    if os.path.splitext(logo)[1].lower() == ".png":
        with open(os.path.join(theme["_dir"], logo), "rb") as f:
            return "png", f.read()
    brand = theme.get("brand_name")
    return ("text", brand) if brand else None


def png_bytes(width, height, rgb):
    """A minimal solid-color PNG (stdlib zlib + struct)."""
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _xfrm(x, y, w, h, flip_h=False, flip_v=False):
    flips = (' flipH="1"' if flip_h else "") + (' flipV="1"' if flip_v else "")
    return (f'<a:xfrm{flips}><a:off x="{emu_px(x)}" y="{emu_px(y)}"/>'
            f'<a:ext cx="{emu_px(w)}" cy="{emu_px(h)}"/></a:xfrm>')


def _shape_fill(theme, fill):
    if fill is None:
        return "<a:noFill/>"
    return _solid_fill(theme, fill)


def _shape_line(theme, line):
    if line is None:
        return "<a:ln><a:noFill/></a:ln>"
    if isinstance(line, dict):
        color = line.get("color")
        width = line.get("width_pt", 1.0)
    else:
        color, width = line, 1.0
    return (f'<a:ln w="{emu_pt(width)}">'
            f"{'<a:noFill/>' if color is None else _solid_fill(theme, color)}</a:ln>")


class Slide:
    """One 1280x720-grid slide accumulating shapes, relationships, and
    speaker notes."""

    def __init__(self, presentation, notes=""):
        self._pres = presentation
        self.notes = notes
        self._shapes = []
        self._rels = [{"id": "rId1", "type": REL_SLIDE_LAYOUT,
                       "target": "../slideLayouts/slideLayout1.xml"}]
        self._next_id = 2
        self._urls = {}

    def _id(self):
        i = self._next_id
        self._next_id += 1
        return i

    def _rel(self, rtype, target, external=False):
        rel = {"id": f"rId{len(self._rels) + 1}", "type": rtype, "target": target}
        if external:
            rel["mode"] = "External"
        self._rels.append(rel)
        return rel["id"]

    def _hyperlink_rid(self, url):
        if url not in self._urls:
            self._urls[url] = self._rel(REL_HLINK, _clean(url), external=True)
        return self._urls[url]

    def text_box(self, x, y, w, h, paragraphs, *, size=18, color="body", bold=None,
                 italic=None, underline=None, font=None, align=None, bullet=None,
                 line_spacing=None, space_before=None, space_after=None,
                 autofit=False, word_wrap=True, anchor="t", margin=0, name=None):
        """Add a text box. paragraphs is a list of run dicts (single run)
        or paragraph dicts holding a "runs" list; every dict accepts the
        run keys (text, size in pt, bold, italic, underline, color, font,
        url) and paragraph keys (align, bullet, line_spacing,
        space_before, space_after). Box kwargs act as defaults."""
        defaults = {"size": size, "color": color, "bold": bold, "italic": italic,
                    "underline": underline, "font": font, "align": align,
                    "bullet": bullet, "line_spacing": line_spacing,
                    "space_before": space_before, "space_after": space_after}
        body = "".join(self._paragraph_xml(p, defaults) for p in paragraphs) or "<a:p/>"
        body_pr = self._body_pr(autofit, word_wrap, anchor, margin)
        i = self._id()
        self._shapes.append(
            f'<p:sp><p:nvSpPr><p:cNvPr id="{i}" name="{_att(name or f"TextBox {i - 1}")}"/>'
            '<p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
            f"<p:spPr>{_xfrm(x, y, w, h)}"
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr>'
            f"<p:txBody>{body_pr}<a:lstStyle/>{body}</p:txBody></p:sp>")

    def _body_pr(self, autofit, word_wrap, anchor, margin):
        if isinstance(margin, (tuple, list)):
            m_x, m_y = margin[0], margin[1]
        else:
            m_x = m_y = margin
        attrs = [f'wrap="{"square" if word_wrap else "none"}"',
                 f'lIns="{emu_px(m_x)}"', f'tIns="{emu_px(m_y)}"',
                 f'rIns="{emu_px(m_x)}"', f'bIns="{emu_px(m_y)}"', 'rtlCol="0"']
        key = _ANCHOR.get(str(anchor))
        if key:
            attrs.append(f'anchor="{key}"')
        fit = ""
        if autofit:
            if isinstance(autofit, dict):
                scale = int(round(autofit.get("font_scale", 100) * 1000))
                reduce_ = int(round(autofit.get("ln_spc_reduction", 0) * 1000))
                fit = f'<a:normAutofit fontScale="{min(max(scale, 1000), 100000)}" lnSpcReduction="{min(max(reduce_, 0), 100000)}"/>'
            else:
                fit = "<a:normAutofit/>"
        return f'<a:bodyPr {" ".join(attrs)}>{fit}</a:bodyPr>'

    def _paragraph_xml(self, spec, defaults):
        if "runs" in spec:
            runs = spec["runs"]
            para = spec
        else:
            runs = [spec]
            para = {k: spec[k] for k in _RUN_KEYS if k in spec and k != "text"}
        effective = dict(defaults)
        effective.update({k: para[k] for k in _PARA_KEYS + _RUN_KEYS if k in para})
        attrs, kids = [], []
        align = effective.get("align")
        if align:
            key = _ALIGN.get(str(align))
            if not key:
                raise ValueError(f"unknown align {align!r}")
            attrs.append(f'algn="{key}"')
        bullet = effective.get("bullet")
        if bullet is True or isinstance(bullet, dict):
            bd = bullet if isinstance(bullet, dict) else {}
            indent = emu_px(bd.get("indent_px", 24))
            attrs += [f'marL="{indent}"', f'indent="{-indent}"']
            if bd.get("color"):
                kids.append(f'<a:buClr>{_srgb(self._pres.theme, bd["color"])}</a:buClr>')
            family = self._pres.theme["fonts"]["family"]
            kids.append(f'<a:buFont typeface="{_att(bd.get("font") or family)}"/>')
            kids.append(f'<a:buChar char="{_att(bd.get("char", "•"))}"/>')
        elif bullet is False:
            kids.append("<a:buNone/>")
        if effective.get("line_spacing"):
            kids.insert(0, '<a:lnSpc><a:spcPct val="%d"/></a:lnSpc>'
                        % min(max(int(round(effective["line_spacing"] * 100000)), 0), 300000))
        for key, tag in (("space_before", "spcBef"), ("space_after", "spcAft")):
            if effective.get(key) is not None:
                kids.insert(0, f'<a:{tag}><a:spcPts val="{min(max(int(round(effective[key] * 100)), 0), 1584000)}"/></a:{tag}>')
        ppr = ""
        if attrs or kids:
            ppr = f'<a:pPr {" ".join(attrs)}>{"".join(kids)}</a:pPr>'
        runs_xml = "".join(self._run_xml(r, effective) for r in runs)
        if not runs_xml:
            runs_xml = '<a:endParaRPr lang="en-US" dirty="0"/>'
        return f"<a:p>{ppr}{runs_xml}</a:p>"

    def _run_xml(self, run, effective):
        text = _clean(run.get("text", ""))
        if not text:
            return ""
        attrs = ['lang="en-US"', 'dirty="0"']
        size = run.get("size", effective.get("size"))
        if size is not None:
            attrs.append('sz="%d"' % min(max(int(round(size * 100)), 100), 400000))
        for key, attr, on, off in (("bold", "b", "1", "0"), ("italic", "i", "1", "0"),
                                   ("underline", "u", "sng", "none")):
            value = run.get(key, effective.get(key))
            if value is not None:
                attrs.append(f'{attr}="{on if value else off}"')
        kids = []
        color = run.get("color", effective.get("color"))
        if color is not None:
            kids.append(_solid_fill(self._pres.theme, color))
        family = run.get("font", effective.get("font")) or self._pres.theme["fonts"]["family"]
        kids.append(f'<a:latin typeface="{_att(family)}"/>')
        url = run.get("url")
        if url:
            kids.append(f'<a:hlinkClick r:id="{self._hyperlink_rid(url)}"/>')
        space = ' xml:space="preserve"' if text != text.strip() else ""
        return (f'<a:r><a:rPr {" ".join(attrs)}>{"".join(kids)}</a:rPr>'
                f"<a:t{space}>{_esc(text)}</a:t></a:r>")

    def rect(self, x, y, w, h, fill=None, line=None, radius=None, name=None):
        """Add a rectangle (roundRect when radius in px is given)."""
        if radius:
            shorter = max(min(emu_px(w), emu_px(h)), 1)
            adj = min(max(int(round(emu_px(radius) / shorter * 100000)), 0), 50000)
            geom = (f'<a:prstGeom prst="roundRect"><a:avLst>'
                    f'<a:gd name="adj" fmla="val {adj}"/></a:avLst></a:prstGeom>')
        else:
            geom = '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        i = self._id()
        self._shapes.append(
            f'<p:sp><p:nvSpPr><p:cNvPr id="{i}" name="{_att(name or f"Rectangle {i - 1}")}"/>'
            "<p:cNvSpPr/><p:nvPr/></p:nvSpPr>"
            f"<p:spPr>{_xfrm(x, y, w, h)}{geom}"
            f"{_shape_fill(self._pres.theme, fill)}{_shape_line(self._pres.theme, line)}</p:spPr></p:sp>")

    def ellipse(self, x, y, w, h, fill=None, line=None, name=None):
        """Add an ellipse."""
        i = self._id()
        self._shapes.append(
            f'<p:sp><p:nvSpPr><p:cNvPr id="{i}" name="{_att(name or f"Ellipse {i - 1}")}"/>'
            "<p:cNvSpPr/><p:nvPr/></p:nvSpPr>"
            f"<p:spPr>{_xfrm(x, y, w, h)}"
            '<a:prstGeom prst="ellipse"><a:avLst/></a:prstGeom>'
            f"{_shape_fill(self._pres.theme, fill)}{_shape_line(self._pres.theme, line)}</p:spPr></p:sp>")

    def line(self, x1, y1, x2, y2, color, width_pt=1.0, name=None):
        """Add a straight connector from (x1, y1) to (x2, y2)."""
        x, y = min(x1, x2), min(y1, y2)
        w, h = abs(x2 - x1), abs(y2 - y1)
        i = self._id()
        self._shapes.append(
            f'<p:cxnSp><p:nvCxnSpPr><p:cNvPr id="{i}" name="{_att(name or f"Line {i - 1}")}"/>'
            "<p:cNvCxnSpPr/><p:nvPr/></p:nvCxnSpPr>"
            f"<p:spPr>{_xfrm(x, y, w, h, flip_h=x2 < x1, flip_v=y2 < y1)}"
            '<a:prstGeom prst="line"><a:avLst/></a:prstGeom>'
            f'<a:ln w="{emu_pt(width_pt)}">{_solid_fill(self._pres.theme, color)}</a:ln></p:spPr></p:cxnSp>')

    def picture_png(self, x, y, w, h, png, name=None):
        """Embed PNG bytes as a picture at the given box."""
        media = self._pres._media_name(png)
        rid = self._rel(REL_IMAGE, f"../media/{media}")
        i = self._id()
        self._shapes.append(
            f'<p:pic><p:nvPicPr><p:cNvPr id="{i}" name="{_att(name or f"Picture {i - 1}")}"/>'
            '<p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr>'
            f'<p:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>'
            f"<p:spPr>{_xfrm(x, y, w, h)}"
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>')

    def _slide_xml(self):
        shapes = "".join(self._shapes)
        return (XMLDECL
                + f'<p:sld xmlns:a="{NS_A}" xmlns:r="{NS_R}" xmlns:p="{NS_P}">'
                "<p:cSld><p:spTree>"
                '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
                '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
                '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
                f"{shapes}</p:spTree></p:cSld>"
                "<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>")

    def _notes_slide_xml(self):
        family = _att(self._pres.theme["fonts"]["family"])
        paras = []
        for text in _clean(self.notes).split("\n"):
            if text:
                paras.append(f'<a:p><a:r><a:rPr lang="en-US" sz="1200" dirty="0">'
                             f'<a:latin typeface="{family}"/></a:rPr>'
                             f"<a:t>{_esc(text)}</a:t></a:r></a:p>")
        body = "".join(paras) or '<a:p><a:endParaRPr lang="en-US" sz="1200" dirty="0"/></a:p>'
        return (XMLDECL
                + f'<p:notes xmlns:a="{NS_A}" xmlns:r="{NS_R}" xmlns:p="{NS_P}">'
                "<p:cSld><p:spTree>"
                '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
                '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
                '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
                '<p:sp><p:nvSpPr><p:cNvPr id="2" name="Slide Image Placeholder 1"/>'
                '<p:cNvSpPr><a:spLocks noGrp="1" noRot="1" noChangeAspect="1"/></p:cNvSpPr>'
                '<p:nvPr><p:ph type="sldImg"/></p:nvPr></p:nvSpPr><p:spPr/></p:sp>'
                '<p:sp><p:nvSpPr><p:cNvPr id="3" name="Notes Placeholder 2"/>'
                '<p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>'
                '<p:nvPr><p:ph type="body" idx="1"/></p:nvPr></p:nvSpPr>'
                f'<p:spPr/><p:txBody><a:bodyPr rtlCol="0"/><a:lstStyle/>{body}</p:txBody></p:sp>'
                "</p:spTree></p:cSld>"
                "<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:notes>")


_FMT_SCHEME = (
    '<a:fmtScheme name="Office">'
    '<a:fillStyleLst>'
    '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
    '<a:gradFill rotWithShape="1"><a:gsLst>'
    '<a:gs pos="0"><a:schemeClr val="phClr"><a:tint val="95000"/><a:satMod val="105000"/></a:schemeClr></a:gs>'
    '<a:gs pos="100000"><a:schemeClr val="phClr"><a:shade val="94000"/><a:satMod val="105000"/></a:schemeClr></a:gs>'
    '</a:gsLst><a:lin ang="16200000" scaled="1"/></a:gradFill>'
    '<a:gradFill rotWithShape="1"><a:gsLst>'
    '<a:gs pos="0"><a:schemeClr val="phClr"><a:shade val="93000"/><a:satMod val="105000"/></a:schemeClr></a:gs>'
    '<a:gs pos="100000"><a:schemeClr val="phClr"><a:shade val="94000"/><a:satMod val="105000"/></a:schemeClr></a:gs>'
    '</a:gsLst><a:lin ang="16200000" scaled="0"/></a:gradFill>'
    '</a:fillStyleLst>'
    '<a:lnStyleLst>'
    '<a:ln w="9525" cap="flat" cmpd="sng" algn="ctr"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:prstDash val="solid"/></a:ln>'
    '<a:ln w="25400" cap="flat" cmpd="sng" algn="ctr"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:prstDash val="solid"/></a:ln>'
    '<a:ln w="38100" cap="flat" cmpd="sng" algn="ctr"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:prstDash val="solid"/></a:ln>'
    '</a:lnStyleLst>'
    '<a:effectStyleLst>'
    '<a:effectStyle><a:effectLst/></a:effectStyle>'
    '<a:effectStyle><a:effectLst/></a:effectStyle>'
    '<a:effectStyle><a:effectLst/></a:effectStyle>'
    '</a:effectStyleLst>'
    '<a:bgFillStyleLst>'
    '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
    '<a:solidFill><a:schemeClr val="phClr"><a:tint val="95000"/><a:satMod val="105000"/></a:schemeClr></a:solidFill>'
    '<a:gradFill rotWithShape="1"><a:gsLst>'
    '<a:gs pos="0"><a:schemeClr val="phClr"><a:tint val="25000"/><a:satMod val="105000"/></a:schemeClr></a:gs>'
    '<a:gs pos="100000"><a:schemeClr val="phClr"><a:shade val="94000"/><a:satMod val="105000"/></a:schemeClr></a:gs>'
    '</a:gsLst><a:lin ang="16200000" scaled="0"/></a:gradFill>'
    '</a:bgFillStyleLst>'
    '</a:fmtScheme>')


class Presentation:
    """A .pptx package accumulating slides from one theme."""

    def __init__(self, theme, created=None, title="", creator=""):
        self.theme = theme
        self.created = created or DEFAULT_CREATED
        self.title = title
        self.creator = creator
        self.slides = []
        self._media = {}

    def add_slide(self, notes=""):
        """Add a slide with speaker notes; returns the Slide."""
        slide = Slide(self, notes)
        self.slides.append(slide)
        return slide

    def _media_name(self, png):
        key = sha1(png).digest()
        if key not in self._media:
            self._media[key] = (f"image{len(self._media) + 1}.png", png)
        return self._media[key][0]

    def _theme_xml(self):
        c = self.theme["colors"]
        name = _att(self.theme.get("name", "Theme"))
        family = _att(self.theme["fonts"]["family"])
        slots = (("dk1", c["ink"]), ("lt1", c["surface"]), ("dk2", c["body"]),
                 ("lt2", c["fill"]), ("accent1", c["accent"]),
                 ("accent2", c["secondary"]), ("accent3", c["accent_tints"][2]),
                 ("accent4", c["accent_tints"][3]),
                 ("accent5", c["secondary_tints"][2]),
                 ("accent6", c["secondary_tints"][3]),
                 ("hlink", c["accent_ink"]), ("folHlink", c["secondary_ink"]))
        scheme = "".join(f'<a:{slot}><a:srgbClr val="{hex_.lstrip("#").upper()}"/></a:{slot}>'
                         for slot, hex_ in slots)
        fonts = (f'<a:latin typeface="{family}"/><a:ea typeface=""/><a:cs typeface=""/>')
        return (XMLDECL
                + f'<a:theme xmlns:a="{NS_A}" name="{name}">'
                "<a:themeElements>"
                f'<a:clrScheme name="{name}">{scheme}</a:clrScheme>'
                f'<a:fontScheme name="{name}"><a:majorFont>{fonts}</a:majorFont>'
                f"<a:minorFont>{fonts}</a:minorFont></a:fontScheme>"
                f"{_FMT_SCHEME}</a:themeElements>"
                "<a:objectDefaults/><a:extraClrSchemeLst/></a:theme>")

    def _slide_master_xml(self):
        def placeholder(i, name, ph_type, idx, x, y, w, h):
            ph = f'<p:ph type="{ph_type}"' + (f' idx="{idx}"/>' if idx else "/>")
            return (f'<p:sp><p:nvSpPr><p:cNvPr id="{i}" name="{_att(name)}"/>'
                    '<p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>'
                    f"<p:nvPr>{ph}</p:nvPr></p:nvSpPr>"
                    f"<p:spPr>{_xfrm(x, y, w, h)}"
                    '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>'
                    "<p:txBody><a:bodyPr/><a:lstStyle/><a:p>"
                    '<a:endParaRPr lang="en-US"/></a:p></p:txBody></p:sp>')
        title = placeholder(2, "Title Placeholder 1", "title", None, 64, 60, 1152, 100)
        body = placeholder(3, "Text Placeholder 2", "body", 1, 64, 180, 1152, 480)
        return (XMLDECL
                + f'<p:sldMaster xmlns:a="{NS_A}" xmlns:r="{NS_R}" xmlns:p="{NS_P}">'
                "<p:cSld>"
                '<p:bg><p:bgRef idx="1001"><a:schemeClr val="bg1"/></p:bgRef></p:bg>'
                "<p:spTree>"
                '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
                '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
                '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
                f"{title}{body}</p:spTree></p:cSld>"
                '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1"'
                ' accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5"'
                ' accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
                '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>'
                "<p:txStyles>"
                '<p:titleStyle><a:lvl1pPr algn="l"><a:defRPr sz="3600">'
                '<a:solidFill><a:schemeClr val="tx1"/></a:solidFill>'
                '<a:latin typeface="+mj-lt"/></a:defRPr></a:lvl1pPr></p:titleStyle>'
                '<p:bodyStyle><a:lvl1pPr marL="0" indent="0"><a:buNone/>'
                '<a:defRPr sz="1800"><a:latin typeface="+mn-lt"/></a:defRPr>'
                "</a:lvl1pPr></p:bodyStyle>"
                '<p:otherStyle><a:lvl1pPr marL="0" indent="0"><a:buNone/>'
                '<a:defRPr sz="1800"/></a:lvl1pPr></p:otherStyle>'
                "</p:txStyles></p:sldMaster>")

    def _slide_layout_xml(self):
        return (XMLDECL
                + f'<p:sldLayout xmlns:a="{NS_A}" xmlns:r="{NS_R}" xmlns:p="{NS_P}"'
                ' type="blank" preserve="1">'
                '<p:cSld name="Blank"><p:spTree>'
                '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
                '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
                '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
                "</p:spTree></p:cSld>"
                "<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>")

    def _notes_master_xml(self):
        def placeholder(i, name, ph, x, y, w, h, body=True):
            shape = (f'<p:sp><p:nvSpPr><p:cNvPr id="{i}" name="{_att(name)}"/>'
                     '<p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>'
                     f"<p:nvPr>{ph}</p:nvPr></p:nvSpPr>"
                     f"<p:spPr>{_xfrm(x, y, w, h)}"
                     '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>')
            if body:
                shape += ("<p:txBody><a:bodyPr/><a:lstStyle/><a:p>"
                          '<a:endParaRPr lang="en-US"/></a:p></p:txBody>')
            return shape + "</p:sp>"
        sld_img = placeholder(2, "Slide Image Placeholder 1", '<p:ph type="sldImg"/>',
                              72, 72, 576, 324, body=False)
        body = placeholder(3, "Notes Placeholder 2", '<p:ph type="body" idx="1"/>',
                           72, 432, 576, 456)
        sld_num = placeholder(4, "Slide Number Placeholder 3", '<p:ph type="sldNum" idx="10"/>',
                              576, 936, 72, 36)
        return (XMLDECL
                + f'<p:notesMaster xmlns:a="{NS_A}" xmlns:r="{NS_R}" xmlns:p="{NS_P}">'
                "<p:cSld>"
                '<p:bg><p:bgRef idx="1001"><a:schemeClr val="bg1"/></p:bgRef></p:bg>'
                "<p:spTree>"
                '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
                '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
                '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
                f"{sld_img}{body}{sld_num}</p:spTree></p:cSld>"
                '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1"'
                ' accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5"'
                ' accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
                '<p:notesStyle><a:lvl1pPr marL="0" indent="0"><a:buNone/>'
                '<a:defRPr sz="1200"/></a:lvl1pPr></p:notesStyle></p:notesMaster>')

    def _presentation_xml(self):
        slides = "".join(f'<p:sldId id="{256 + i}" r:id="rId{3 + i}"/>'
                         for i in range(len(self.slides)))
        return (XMLDECL
                + f'<p:presentation xmlns:a="{NS_A}" xmlns:r="{NS_R}" xmlns:p="{NS_P}">'
                '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
                '<p:notesMasterIdLst><p:notesMasterId r:id="rId2"/></p:notesMasterIdLst>'
                f"<p:sldIdLst>{slides}</p:sldIdLst>"
                f'<p:sldSz cx="{SLIDE_W_EMU}" cy="{SLIDE_H_EMU}"/>'
                f'<p:notesSz cx="{NOTES_W_EMU}" cy="{NOTES_H_EMU}"/></p:presentation>')

    def _core_xml(self):
        return (XMLDECL
                + '<cp:coreProperties'
                ' xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"'
                ' xmlns:dc="http://purl.org/dc/elements/1.1/"'
                ' xmlns:dcterms="http://purl.org/dc/terms/"'
                ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
                f"<dc:title>{_esc(self.title)}</dc:title>"
                f"<dc:creator>{_esc(self.creator)}</dc:creator>"
                f"<cp:lastModifiedBy>{_esc(self.creator)}</cp:lastModifiedBy>"
                f'<dcterms:created xsi:type="dcterms:W3CDTF">{_esc(self.created)}</dcterms:created>'
                f'<dcterms:modified xsi:type="dcterms:W3CDTF">{_esc(self.created)}</dcterms:modified>'
                "</cp:coreProperties>")

    def _app_xml(self):
        n = len(self.slides)
        return (XMLDECL
                + '<Properties'
                ' xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"'
                ' xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
                "<PresentationFormat>Widescreen</PresentationFormat>"
                f"<Slides>{n}</Slides><Notes>{n}</Notes>"
                "<Application>pptx_lib</Application><AppVersion>1.0</AppVersion>"
                "</Properties>")

    def _package_parts(self):
        theme = self._theme_xml()
        parts = {
            "docProps/core.xml": self._core_xml().encode("utf-8"),
            "docProps/app.xml": self._app_xml().encode("utf-8"),
            "ppt/presentation.xml": self._presentation_xml().encode("utf-8"),
            "ppt/presProps.xml": (XMLDECL
                                  + f'<p:presentationPr xmlns:p="{NS_P}"/>').encode("utf-8"),
            "ppt/viewProps.xml": (XMLDECL
                                  + f'<p:viewPr xmlns:p="{NS_P}"/>').encode("utf-8"),
            "ppt/tableStyles.xml": (XMLDECL
                                    + '<a:tblStyleLst xmlns:a="' + NS_A + '"'
                                    ' def="{5940675A-B579-460E-94D1-54222C63F5DA}"/>').encode("utf-8"),
            "ppt/theme/theme1.xml": theme.encode("utf-8"),
            "ppt/theme/theme2.xml": theme.encode("utf-8"),
            "ppt/slideMasters/slideMaster1.xml": self._slide_master_xml().encode("utf-8"),
            "ppt/slideLayouts/slideLayout1.xml": self._slide_layout_xml().encode("utf-8"),
            "ppt/notesMasters/notesMaster1.xml": self._notes_master_xml().encode("utf-8"),
        }
        pres_rels = [
            {"id": "rId1", "type": REL_SLIDE_MASTER, "target": "slideMasters/slideMaster1.xml"},
            {"id": "rId2", "type": REL_NOTES_MASTER, "target": "notesMasters/notesMaster1.xml"},
        ]
        pres_rels += [{"id": f"rId{3 + i}", "type": REL_SLIDE, "target": f"slides/slide{i + 1}.xml"}
                      for i in range(len(self.slides))]
        n = len(self.slides)
        pres_rels += [
            {"id": f"rId{n + 3}", "type": REL_PRES_PROPS, "target": "presProps.xml"},
            {"id": f"rId{n + 4}", "type": REL_VIEW_PROPS, "target": "viewProps.xml"},
            {"id": f"rId{n + 5}", "type": REL_THEME, "target": "theme/theme1.xml"},
            {"id": f"rId{n + 6}", "type": REL_TABLE_STYLES, "target": "tableStyles.xml"},
        ]
        parts["_rels/.rels"] = _rels_xml([
            {"id": "rId1", "type": REL_OFFICE_DOCUMENT, "target": "ppt/presentation.xml"},
            {"id": "rId2", "type": REL_CORE_PROPS, "target": "docProps/core.xml"},
            {"id": "rId3", "type": REL_EXT_PROPS, "target": "docProps/app.xml"},
        ]).encode("utf-8")
        parts["ppt/_rels/presentation.xml.rels"] = _rels_xml(pres_rels).encode("utf-8")
        parts["ppt/slideMasters/_rels/slideMaster1.xml.rels"] = _rels_xml([
            {"id": "rId1", "type": REL_SLIDE_LAYOUT, "target": "../slideLayouts/slideLayout1.xml"},
            {"id": "rId2", "type": REL_THEME, "target": "../theme/theme1.xml"},
        ]).encode("utf-8")
        parts["ppt/slideLayouts/_rels/slideLayout1.xml.rels"] = _rels_xml([
            {"id": "rId1", "type": REL_SLIDE_MASTER, "target": "../slideMasters/slideMaster1.xml"},
        ]).encode("utf-8")
        parts["ppt/notesMasters/_rels/notesMaster1.xml.rels"] = _rels_xml([
            {"id": "rId1", "type": REL_THEME, "target": "../theme/theme2.xml"},
        ]).encode("utf-8")
        for i, slide in enumerate(self.slides, 1):
            if not any(r["type"] == REL_NOTES_SLIDE for r in slide._rels):
                slide._rel(REL_NOTES_SLIDE, f"../notesSlides/notesSlide{i}.xml")
            parts[f"ppt/slides/slide{i}.xml"] = slide._slide_xml().encode("utf-8")
            parts[f"ppt/slides/_rels/slide{i}.xml.rels"] = _rels_xml(slide._rels).encode("utf-8")
            parts[f"ppt/notesSlides/notesSlide{i}.xml"] = slide._notes_slide_xml().encode("utf-8")
            parts[f"ppt/notesSlides/_rels/notesSlide{i}.xml.rels"] = _rels_xml([
                {"id": "rId1", "type": REL_NOTES_MASTER, "target": "../notesMasters/notesMaster1.xml"},
            ]).encode("utf-8")
        for name, png in self._media.values():
            parts[f"ppt/media/{name}"] = png
        overrides = [
            ("/ppt/presentation.xml", CT_PRESENTATION),
            ("/ppt/slideMasters/slideMaster1.xml", CT_SLIDE_MASTER),
            ("/ppt/slideLayouts/slideLayout1.xml", CT_SLIDE_LAYOUT),
            ("/ppt/notesMasters/notesMaster1.xml", CT_NOTES_MASTER),
            ("/ppt/theme/theme1.xml", CT_THEME),
            ("/ppt/theme/theme2.xml", CT_THEME),
            ("/ppt/presProps.xml", CT_PRES_PROPS),
            ("/ppt/viewProps.xml", CT_VIEW_PROPS),
            ("/ppt/tableStyles.xml", CT_TABLE_STYLES),
            ("/docProps/core.xml", CT_CORE),
            ("/docProps/app.xml", CT_APP),
        ]
        for i in range(1, len(self.slides) + 1):
            overrides.append((f"/ppt/slides/slide{i}.xml", CT_SLIDE))
            overrides.append((f"/ppt/notesSlides/notesSlide{i}.xml", CT_NOTES_SLIDE))
        parts["[Content_Types].xml"] = _content_types_xml(overrides, png=bool(self._media)).encode("utf-8")
        return parts

    def save(self, path):
        """Write the package. Same input always produces identical bytes."""
        parts = self._package_parts()
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            for name in sorted(parts):
                info = zipfile.ZipInfo(filename=name, date_time=ZIP_DATE)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                zf.writestr(info, parts[name])


def _rels_xml(rels):
    body = "".join(
        '<Relationship Id="%s" Type="%s" Target="%s"%s/>'
        % (_att(r["id"]), _att(r["type"]), _att(r["target"]),
           ' TargetMode="External"' if r.get("mode") else "")
        for r in rels)
    return XMLDECL + f'<Relationships xmlns="{NS_PKG_RELS}">{body}</Relationships>'


def _content_types_xml(overrides, png=False):
    defaults = [f'<Default Extension="rels" ContentType="{CT_RELS}"/>',
                f'<Default Extension="xml" ContentType="{CT_XML}"/>']
    if png:
        defaults.append(f'<Default Extension="png" ContentType="{CT_PNG}"/>')
    body = "".join(defaults)
    body += "".join(f'<Override PartName="{_att(part)}" ContentType="{ctype}"/>'
                    for part, ctype in overrides)
    return (XMLDECL
            + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            + body + "</Types>")


def build_demo_deck(theme, path):
    """Write a three-slide demo deck exercising the whole shape API."""
    pres = Presentation(theme, created="2026-11-01T12:00:00Z",
                        title="Writer demo", creator="pptx_lib")
    s1 = pres.add_slide(notes="Cover notes for the demo deck.")
    s1.text_box(64, 90, 900, 150, [
        {"text": "Writer demo deck", "size": 34, "bold": True, "color": "ink"},
        {"text": "Native editable shapes from one theme", "size": 16, "color": "muted"},
    ], line_spacing=1.15)
    s1.ellipse(64, 260, 24, 24, fill="accent")
    s1.picture_png(984, 90, 232, 155, png_bytes(60, 40, (79, 70, 229)))
    s2 = pres.add_slide(notes="Bullet slide notes.")
    s2.text_box(64, 80, 1152, 500, [
        {"text": "What the writer provides", "size": 24, "bold": True, "color": "ink",
         "bullet": False, "space_after": 8},
        {"text": "Text boxes with real runs", "size": 16, "bullet": True, "line_spacing": 1.3},
        {"text": "Shapes, lines, and PNG pictures", "size": 16, "bullet": True},
        {"runs": [{"text": "Hyperlinks: ", "size": 16},
                  {"text": "open the demo", "size": 16, "color": "accent",
                   "url": "https://example.com/report?a=1&b=2"}]},
    ], autofit=True, anchor="t")
    s3 = pres.add_slide(notes="Shape slide notes.")
    s3.rect(64, 80, 400, 260, fill="accent_tint1", radius=18)
    s3.rect(500, 80, 400, 260, fill=None, line={"color": "line_strong", "width_pt": 1.5})
    s3.ellipse(64, 380, 120, 120, fill="secondary")
    s3.line(64, 552, 1216, 552, color="line_strong", width_pt=2.0)
    s3.text_box(500, 380, 716, 160, [
        {"text": "Q4 2026", "size": 28, "color": "secondary_ink", "align": "center"}],
        anchor="ctr")
    pres.save(path)


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(
        description="Write demo .pptx decks with the PresentationML writer")
    parser.add_argument("--demo", metavar="DIR",
                        help="write test-neutral.pptx and test-alt.pptx into DIR")
    args = parser.parse_args(argv)
    if not args.demo:
        parser.error("--demo is required")
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    from theme import load_theme
    alt = os.path.normpath(os.path.join(here, "..", "tests", "fixtures", "themes", "alt"))
    os.makedirs(args.demo, exist_ok=True)
    paths = [os.path.join(args.demo, "test-neutral.pptx"),
             os.path.join(args.demo, "test-alt.pptx")]
    for theme, path in zip((load_theme("neutral"), load_theme(alt)), paths):
        build_demo_deck(theme, path)
        print("wrote", path)


if __name__ == "__main__":
    main()
