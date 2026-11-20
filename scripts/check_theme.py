"""Theme QA gate for rendered HTML and PowerPoint output (every rule
reads from the theme).

Checks one or more self-contained themed HTML files, or PowerPoint
packages (.pptx), against the theme that produced them, generalizing
the adopted engine's brand checker: palette, fonts, external
references, motif text safety, and dark-surface rules all come from the
theme contract (scripts/theme.py), so the same gate serves every theme.

Usage:
    python3 check_theme.py report.html deck.pptx [more ...] [--theme neutral|path/to/theme]

Exit 1 on any ERROR, 0 with warnings only, 2 when the theme cannot load.

ERROR (HTML):
  * a color from the theme's qa.forbidden_colors appears (reason included)
  * an external resource reference: http(s):// or protocol-relative // in
    src=, href= of any non-<a> element (plain <a href="https://..."> hyperlinks
    are allowed - bibliography links), @import, or url(); src= and href=
    values are read quoted or unquoted
  * an injected <script> element: the only script allowed is the renderer's
    own, recognised by a body byte-identical to assets/render/deck.js and an
    open tag without src= (a src= replaces the body with other code)
  * an event handler attribute (onerror=, onclick=, any on*=) inside a real
    tag, any letter case, quoted or unquoted value; escaped text such as
    &lt;img onerror=x&gt; is not a tag and is never flagged
  * a javascript: URL in any tag's URL attribute (href=, src=, action=,
    formaction=, data=, poster=, xlink:href= and the like) or in a <meta>
    refresh content= url, case-insensitive, with leading whitespace/control
    characters and entity tricks (jav&#x61;script:) decoded first
  * a data: URL that carries a document rather than an image (data:text/html
    and any other non-image/* type, or image/svg+xml loaded into a frame,
    object or embed) in the same attributes
  * an iframe srcdoc= attribute (an inline document; its escaped markup runs)
  * a font-family that is not the theme's fonts.family, one of its
    fonts.fallback families, or a generic family
  * text in the motif keep-out: an outer-cell motif polygon intersecting the
    cover text keep-out rectangles (COVER_KEEPOUTS from scripts/motif.py),
    or a <text>/<foreignObject> element inside a motif svg

WARN (HTML):
  * a hex color outside the theme palette (colors + tints + motif tints/line
    + qa.allowed_colors + #FFFFFF/#000000; 3-digit forms normalized, hex
    inside base64 font/image data ignored)
  * a dark body/slide/section background (relative luminance < 0.2) when
    qa.forbid_dark_surfaces is true

ERROR (.pptx; slides, masters, layouts, theme parts, and every .rels are
inspected):
  * a color from the theme's qa.forbidden_colors appears as an srgbClr
    val, case-insensitive (part and reason included)
  * a Relationship with TargetMode="External" whose Type is not the
    hyperlink type
  * an external hyperlink relationship whose target does not start with
    http:// or https:// (scheme compared case-insensitively; file://,
    javascript:, UNC paths and empty targets fail), or whose target
    carries a control character
  * a latin/ea/cs typeface (a:latin, a:ea, a:cs, including the theme
    fontScheme) that is not the theme's fonts.family, one of its
    fonts.fallback families, a generic family, or a theme placeholder
    like "+mj-lt"/"+mn-lt" (empty typeface="" is fine)
  * a slide with no non-whitespace <a:t> text
  * a package that is not a valid zip, a part that cannot be read
    (corrupt member), or lacks [Content_Types].xml or ppt/presentation.xml

WARN (.pptx):
  * an srgbClr outside the theme palette (colors + tints + motif tints/line
    + qa.allowed_colors + FFFFFF/000000)
"""
import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
import zlib
from html import unescape

from motif import COVER_KEEPOUTS
from theme import load_theme

GENERIC_FAMILIES = {
    "serif", "sans-serif", "system-ui", "monospace", "cursive", "fantasy",
    "math", "emoji", "fangsong", "ui-serif", "ui-sans-serif", "ui-monospace",
    "ui-rounded", "inherit", "initial", "unset", "revert", "revert-layer",
}
SURFACE_WORDS = {"body", "slide", "section", "cover"}
DATA_URI = re.compile(r"data:[^)\"'\s]*")
HEX6 = re.compile(r"#[0-9A-Fa-f]{6}\b")
HEX3 = re.compile(r"#[0-9A-Fa-f]{3}\b(?![0-9A-Fa-f])")
HEXVAL6 = re.compile(r"^[0-9A-Fa-f]{6}$")
HYPERLINK_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
INLINE_TAGS = ("body", "section", "div", "main", "article", "aside", "header", "footer")

# The renderer's own deck script: render_lib.deck() embeds this file's text
# verbatim inside <script>...</script>. A script body byte-identical to it is
# the only live script a themed render may carry.
DECK_JS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "assets", "render", "deck.js")
SCRIPT_OPEN_RE = re.compile(r"<script\b[^>]*>", re.I)
SCRIPT_CLOSE_RE = re.compile(r"</script\s*>", re.I)
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
TAG_RE = re.compile(r"<([a-zA-Z][\w-]*)((?:[^<>\"']|\"[^\"]*\"|'[^']*')*)>")
QUOTED_RE = re.compile(r"\"[^\"]*\"|'[^']*'")
ATTR_VALUE_RE = re.compile(r"=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]*)")
HANDLER_RE = re.compile(r"(?<![\w-])(on[a-zA-Z]+)\s*=", re.I)
URL_ATTR_RE = re.compile(r"(?<![\w-])(href|src)\s*=\s*"
                         r"(?:\"([^\"]*)\"|'([^']*)'|([^\s>]*))", re.I)
URL_STRIP_RE = re.compile(r"[\t\n\r\f\v]")
# Leading/trailing characters a URL parser trims: C0 controls and space.
URL_TRIM = "".join(chr(c) for c in range(0x21))
# Attributes whose value a browser loads, submits to or navigates to as a URL.
LIVE_URL_ATTRS = frozenset((
    "href", "src", "action", "formaction", "data", "poster", "background",
    "cite", "codebase", "longdesc", "lowsrc", "dynsrc", "manifest", "icon",
    "ping", "archive", "classid", "srcset"))
ANY_ATTR_RE = re.compile(r"(?<![\w-])([a-zA-Z_:][\w:.-]*)\s*=\s*"
                         r"(?:\"([^\"]*)\"|'([^']*)'|([^\s>]*))")
META_URL_RE = re.compile(r"url\s*=\s*(.*)$", re.I | re.S)
SRC_ATTR_RE = re.compile(r"(?<![\w-])src\s*=", re.I)
FRAME_TAGS = frozenset(("iframe", "frame", "object", "embed"))
PPTX_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def _deck_js_text():
    """The renderer's deck.js text, or None when it cannot be read (then no
    script is recognised and every <script> is reported)."""
    try:
        with open(DECK_JS_PATH, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def _norm_hex(h):
    h = h.upper()
    if len(h) == 4:
        h = "#" + "".join(c * 2 for c in h[1:])
    return h


def _hexes_in(text):
    found = {m.group(0) for m in HEX6.finditer(text)}
    found |= {m.group(0) for m in HEX3.finditer(text)}
    return {_norm_hex(h) for h in found}


def _uniq(items):
    return list(dict.fromkeys(items))


def theme_palette(theme):
    """Every hex the theme sanctions: colors, tints, motif tints/line, qa extras, black/white."""
    c = theme["colors"]
    allowed = {_norm_hex(c[k]) for k in
               ("surface", "ink", "body", "muted", "line", "line_strong", "fill",
                "accent", "accent_ink", "secondary", "secondary_ink")}
    for key in ("accent_tints", "secondary_tints"):
        allowed |= {_norm_hex(h) for h in c[key]}
    m = theme["motif"]
    allowed |= {_norm_hex(h) for h in m["tints_a"]}
    allowed |= {_norm_hex(h) for h in m["tints_b"]}
    allowed.add(_norm_hex(m["line"]))
    allowed |= {_norm_hex(h) for h in theme["qa"]["allowed_colors"]}
    allowed |= {"#FFFFFF", "#000000"}
    return allowed


def theme_families(theme):
    """The theme's font family plus every family named in its fallback list."""
    families = {theme["fonts"]["family"].strip().lower()}
    for name in theme["fonts"]["fallback"].split(","):
        name = name.strip().strip("\"'").lower()
        if name:
            families.add(name)
    return families


def _luminance(hex6):
    def lin(byte):
        c = int(byte, 16) / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(hex6[1:3]) + 0.7152 * lin(hex6[3:5]) + 0.0722 * lin(hex6[5:7])


def _is_external(url):
    url = url.strip()
    if url.startswith("data:"):
        return False
    return url.startswith("//") or "http://" in url or "https://" in url


def _is_javascript_url(url):
    """True when the attribute value is a javascript: URL the way a browser
    reads it: entities decode once, tab/newline/CR vanish anywhere, leading
    and trailing whitespace is trimmed, and the scheme is case-insensitive."""
    return _norm_url(url).startswith("javascript:")


def _norm_url(url):
    """The attribute value the way a URL parser reads its scheme: entities
    decoded once, tab/newline/CR removed anywhere, leading and trailing C0
    controls and whitespace trimmed, lowercased."""
    v = URL_STRIP_RE.sub("", unescape(url))
    return v.strip(URL_TRIM).strip().strip(URL_TRIM).lower()


def _is_data_document(url, tag):
    """True when the value is a data: URL whose payload a browser renders
    as a document that can run script: any non-image/* media type, or
    image/svg+xml loaded into a frame, object or embed. Image data: URLs
    (the theme logo) are inert."""
    v = _norm_url(url)
    if not v.startswith("data:"):
        return False
    mediatype = v[5:].split(",", 1)[0].split(";", 1)[0].strip()
    if not mediatype.startswith("image/"):
        return True
    return mediatype == "image/svg+xml" and tag in FRAME_TAGS


def _attr_value(m):
    return m.group(2) if m.group(2) is not None else (
        m.group(3) if m.group(3) is not None else (m.group(4) or ""))


def _check_live_url(tag, attr, value, errs):
    if _is_javascript_url(value):
        errs.append(f"javascript: URL in <{tag}> {attr}= ({value})")
    elif _is_data_document(value, tag):
        errs.append(f"data: document URL in <{tag}> {attr}= ({value})")


def _iter_open_tags(src):
    """(tag, attrs) for every real opening tag in src. HTML comments are
    stripped first (comment content is inert), so escaped text such as
    &lt;img onerror=x&gt; never yields a tag."""
    for m in TAG_RE.finditer(src):
        yield m.group(1).lower(), m.group(2)


def _check_injected_markup(src, errs):
    """Script/handler/javascript: rules (E2-R5): every <script> must pair
    with a close tag and its body must be byte-identical to the renderer's
    deck.js and its open tag carries no src=; no on*= attribute may sit in a
    real tag; no URL attribute or meta refresh may carry a javascript: or
    data: document URL; no srcdoc= may appear. Recognised deck.js bodies are masked out of the tag
    scan but their open tags stay scannable (an onload= there still runs);
    hostile script bodies stay scannable. Returns the comment-stripped,
    deck.js-masked source for further tag checks."""
    nocmt = COMMENT_RE.sub(" ", src)
    # Markup inside a quoted attribute value (title="<script>…") is inert:
    # blank the value contents of real tags before pairing script tags, the
    # way the HTML tokenizer consumes them.
    masked = nocmt
    for m in TAG_RE.finditer(nocmt):
        for q in QUOTED_RE.finditer(m.group(2)):
            start = m.start(2) + q.start()
            inner = q.group(0)[1:-1]
            masked = (masked[:start + 1] + " " * len(inner)
                      + masked[start + 1 + len(inner):])
    opens = sorted((m.start(), m.end()) for m in SCRIPT_OPEN_RE.finditer(masked))
    closes = sorted((m.start(), m.end()) for m in SCRIPT_CLOSE_RE.finditer(masked))
    deck_js = _deck_js_text()
    scan = nocmt
    for o_start, o_end in opens:
        close = next((c for c in closes if c[0] > o_end), None)
        if close is None:
            errs.append("injected script element (unclosed <script> tag)")
            continue
        closes.remove(close)
        body = masked[o_end:close[0]]
        has_src = SRC_ATTR_RE.search(ATTR_VALUE_RE.sub("=", masked[o_start:o_end]))
        if deck_js is not None and body == deck_js and has_src:
            errs.append("injected script element (src= on the renderer's deck.js "
                        "script loads other code)")
            continue
        if deck_js is not None and body == deck_js:
            blank = " " * (close[1] - o_end)
            scan = scan[:o_end] + blank + scan[close[1]:]
            continue
        snippet = " ".join((body.strip() or masked[o_start:o_end]).split())[:40]
        errs.append(f"injected script element (not the renderer's deck.js: {snippet})")
    for tag, attrs in _iter_open_tags(scan):
        bare = ATTR_VALUE_RE.sub("=", attrs)
        for h in HANDLER_RE.finditer(bare):
            errs.append(f"event handler attribute {h.group(1).lower()}= in <{tag}>")
        for a in ANY_ATTR_RE.finditer(attrs):
            attr = a.group(1).lower()
            local = attr.rsplit(":", 1)[-1]
            value = _attr_value(a)
            if local in LIVE_URL_ATTRS:
                _check_live_url(tag, attr, value, errs)
            elif local == "srcdoc":
                errs.append(f"inline document attribute srcdoc= in <{tag}>")
            elif tag == "meta" and local == "content":
                u = META_URL_RE.search(unescape(value))
                if u:
                    _check_live_url(tag, attr, u.group(1).strip().strip("\"'"), errs)
    return scan


def _var_tokens(text):
    tokens = {}
    for block in re.findall(r":root\{([^}]*)\}", text):
        for decl in block.split(";"):
            name, sep, value = decl.partition(":")
            if sep and name.strip().startswith("--"):
                tokens[name.strip()] = value.strip()
    return tokens


def _resolve(value, tokens):
    for _ in range(6):
        m = re.search(r"var\((--[\w-]+)\)", value)
        if not m or m.group(1) not in tokens:
            break
        value = value[:m.start()] + tokens[m.group(1)] + value[m.end():]
    return value


def _words(text):
    return {w for w in re.split(r"[^a-z0-9]+", text.lower()) if w}


def _font_declarations(src, stripped):
    """font-family declaration values from <style> blocks and inline style attributes."""
    decls = []
    css_text = "\n".join(re.findall(r"<style\b[^>]*>(.*?)</style>", stripped, re.S))
    decls += [m.group(1) for m in re.finditer(r"font-family\s*:\s*([^;}]+)", css_text)]
    for m in re.finditer(r"\bstyle\s*=\s*(?:\"([^\"]*)\"|'([^']*)')", src):
        for part in (m.group(1) or m.group(2) or "").split(";"):
            head, sep, value = part.partition(":")
            if sep and head.strip().lower() == "font-family":
                decls.append(value)
    return decls


def _local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _pptx_scan_parts(names):
    """The XML parts to inspect: slides, masters, layouts, and theme parts."""
    wanted = []
    for folder in ("slides", "slideMasters", "slideLayouts", "theme"):
        prefix = f"ppt/{folder}/"
        wanted += [n for n in names if n.startswith(prefix) and n.endswith(".xml")
                   and "/" not in n[len(prefix):]]
    return sorted(set(wanted))


def check_pptx(path, theme):
    """(errors, warnings) for one PowerPoint package; messages carry no
    file prefix."""
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        return ["not a PowerPoint package (not a valid zip archive)"], []
    except OSError as exc:
        return [f"cannot read file ({exc})"], []
    errs, warns = [], []
    with zf:
        names = zf.namelist()
        for required in ("[Content_Types].xml", "ppt/presentation.xml"):
            if required not in names:
                errs.append(f"package is missing {required}")
        trees = {}
        for name in _pptx_scan_parts(names):
            try:
                trees[name] = ET.fromstring(zf.read(name).decode("utf-8"))
            except (zipfile.BadZipFile, zlib.error) as exc:
                errs.append(f"{name} cannot be read ({exc})")
            except (ET.ParseError, UnicodeDecodeError) as exc:
                errs.append(f"{name} is not valid XML ({exc})")
        forbidden = {_norm_hex(h): reason for h, reason in theme["qa"]["forbidden_colors"].items()}
        allowed = theme_palette(theme)
        families = theme_families(theme)
        for name, root in sorted(trees.items()):
            has_text = False
            for el in root.iter():
                tag = _local(el.tag)
                if tag == "srgbClr":
                    val = (el.get("val") or "").strip()
                    if not HEXVAL6.match(val):
                        continue
                    h = "#" + val.upper()
                    if h in forbidden:
                        errs.append(f"forbidden color {h} in {name} ({forbidden[h]})")
                    elif h not in allowed:
                        warns.append(f"color {h} in {name} is not in the theme palette")
                elif tag in ("latin", "ea", "cs"):
                    face = el.get("typeface")
                    if face is None:
                        continue
                    face = face.strip()
                    bare = face.strip("\"'").lower()
                    if (not face or face.startswith("+")
                            or bare in families or bare in GENERIC_FAMILIES):
                        continue
                    errs.append(f"typeface '{face}' in {name} "
                                f"is not declared in theme '{theme['name']}'")
                elif tag == "t" and (el.text or "").strip():
                    has_text = True
            if name.startswith("ppt/slides/") and not has_text:
                errs.append(f"slide {name} has no text")
        for name in sorted(n for n in names if n.endswith(".rels")):
            try:
                root = ET.fromstring(zf.read(name).decode("utf-8"))
            except (zipfile.BadZipFile, zlib.error) as exc:
                errs.append(f"{name} cannot be read ({exc})")
                continue
            except (ET.ParseError, UnicodeDecodeError) as exc:
                errs.append(f"{name} is not valid XML ({exc})")
                continue
            for rel in root.iter():
                if _local(rel.tag) != "Relationship" or rel.get("TargetMode") != "External":
                    continue
                rtype = rel.get("Type") or ""
                raw = rel.get("Target") or ""
                target = raw.strip()
                if rtype != HYPERLINK_REL:
                    errs.append(f"external relationship of type {rtype} in {name} "
                                f"({raw})")
                elif PPTX_CONTROL_RE.search(raw):
                    errs.append(f"hyperlink target contains a control character "
                                f"in {name} ({raw!r})")
                elif not target[:8].lower().startswith(("http://", "https://")):
                    errs.append(f"hyperlink target is not http(s) in {name} ({target!r})")
    return _uniq(errs), _uniq(warns)


def check_file(path, theme):
    """(errors, warnings) for one rendered HTML file or .pptx package;
    messages carry no file prefix."""
    if path.lower().endswith(".pptx"):
        return check_pptx(path, theme)
    try:
        with open(path, encoding="utf-8") as f:
            src = f.read()
    except OSError as exc:
        return [f"cannot read file ({exc})"], []
    stripped = DATA_URI.sub("data:", src)
    errs, warns = [], []

    forbidden = {_norm_hex(h): reason for h, reason in theme["qa"]["forbidden_colors"].items()}
    allowed = theme_palette(theme)
    for h in sorted(_hexes_in(stripped)):
        if h in forbidden:
            errs.append(f"forbidden color {h} ({forbidden[h]})")
        elif h not in allowed:
            warns.append(f"color {h} is not in the theme palette")

    families = theme_families(theme)
    for decl in _font_declarations(src, stripped):
        for name in decl.split(","):
            name = name.split("!")[0].strip().strip("\"'").lower()
            if not name or name.startswith("var("):
                continue
            if name not in families and name not in GENERIC_FAMILIES:
                errs.append(f"font-family '{name}' is not declared in theme '{theme['name']}'")

    scan = _check_injected_markup(src, errs)
    for tag, attrs in _iter_open_tags(scan):
        for a in URL_ATTR_RE.finditer(attrs):
            attr = a.group(1).lower()
            url = a.group(2) if a.group(2) is not None else (
                a.group(3) if a.group(3) is not None else (a.group(4) or ""))
            if attr == "src":
                if _is_external(url):
                    errs.append(f"external resource in src= ({url})")
            elif tag != "a" and _is_external(url):
                errs.append(f"external resource in <{tag}> href= ({url})")
    for m in re.finditer(r"@import\s+(?:\"([^\"]+)\"|'([^']+)')", stripped):
        url = m.group(1) or m.group(2)
        if _is_external(url):
            errs.append(f"@import loads an external resource ({url})")
    for m in re.finditer(r"url\(\s*(?:\"([^\"]*)\"|'([^']*)'|([^)\"']*))\s*\)", stripped):
        url = m.group(1) or m.group(2) or m.group(3) or ""
        if _is_external(url):
            errs.append(f"external resource in url() ({url})")

    for m in re.finditer(r"<svg\b[^>]*>.*?</svg>", src, re.S):
        svg = m.group(0)
        open_tag = svg[:svg.index(">") + 1]
        cls = re.search(r"class\s*=\s*\"([^\"]*)\"", open_tag)
        if not cls or "motif" not in cls.group(1).split():
            continue
        if re.search(r"<text\b|<foreignObject\b", svg, re.I):
            errs.append("text element inside motif svg")
        rects = COVER_KEEPOUTS if 'viewBox="0 0 1280 720"' in svg else []
        overlaps = []
        for pm in re.finditer(r"<polygon\b([^>]*)>", svg):
            attrs = pm.group(1)
            classes = re.search(r"class\s*=\s*\"([^\"]*)\"", attrs)
            if not classes or "hx-o" not in classes.group(1).split():
                continue
            points = re.search(r"points\s*=\s*\"([^\"]*)\"", attrs)
            if not points:
                continue
            xs, ys = [], []
            for pair in points.group(1).split():
                x, _, y = pair.partition(",")
                try:
                    xs.append(float(x))
                    ys.append(float(y))
                except ValueError:
                    pass
            if not xs:
                continue
            for a, b, c, d in rects:
                if max(xs) > a and min(xs) < c and max(ys) > b and min(ys) < d:
                    overlaps.append(
                        f"motif cell ({min(xs):.0f},{min(ys):.0f})-({max(xs):.0f},{max(ys):.0f})"
                        " overlaps the cover text keep-out")
                    break
        if overlaps:
            errs.append(overlaps[0] + (f" (+{len(overlaps) - 1} more)" if len(overlaps) > 1 else ""))

    if theme["qa"]["forbid_dark_surfaces"]:
        tokens = _var_tokens(stripped)

        def dark_check(value, where):
            resolved = _resolve(value, tokens)
            for h in sorted(_hexes_in(resolved)):
                lum = _luminance(h)
                if lum < 0.2:
                    warns.append(f"dark surface {h} on '{where}' (relative luminance {lum:.2f})")

        for block in re.findall(r"<style\b[^>]*>(.*?)</style>", stripped, re.S):
            for rm in re.finditer(r"([^{}]+)\{([^{}]*)\}", block):
                sel = " ".join(rm.group(1).split())
                if not (_words(sel) & SURFACE_WORDS):
                    continue
                for bm in re.finditer(r"background(?:-color)?\s*:\s*([^;}]+)", rm.group(2)):
                    dark_check(bm.group(1), sel)
        for tm in re.finditer(r"<(%s)\b([^>]*)>" % "|".join(INLINE_TAGS), src):
            attrs = tm.group(2)
            cm = re.search(r"class\s*=\s*\"([^\"]*)\"", attrs)
            if not (_words(tm.group(1) + " " + (cm.group(1) if cm else "")) & SURFACE_WORDS):
                continue
            sm = re.search(r"\bstyle\s*=\s*\"([^\"]*)\"", attrs)
            if not sm:
                continue
            for bm in re.finditer(r"background(?:-color)?\s*:\s*([^;\"]+)", sm.group(1)):
                dark_check(bm.group(1), f"<{tm.group(1)}> inline style")

    return _uniq(errs), _uniq(warns)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Theme QA gate for rendered HTML and PowerPoint output.")
    ap.add_argument("files", nargs="+", metavar="FILE",
                    help="rendered HTML file(s) and/or .pptx package(s) to check")
    ap.add_argument("--theme", default="neutral", metavar="NAME_OR_PATH",
                    help="theme name under themes/ or a theme folder path (default: neutral)")
    args = ap.parse_args(argv)
    try:
        theme = load_theme(args.theme)
    except ValueError as exc:
        print(f"cannot load theme {args.theme!r}: {exc}", file=sys.stderr)
        return 2
    files = list(dict.fromkeys(args.files))
    total_errors = total_warnings = 0
    for path in files:
        errs, warns = check_file(path, theme)
        for message in errs:
            print(f"ERROR: {path}: {message}")
        for message in warns:
            print(f"WARN: {path}: {message}")
        print(f"checked {path}: {len(errs)} error(s), {len(warns)} warning(s)")
        total_errors += len(errs)
        total_warnings += len(warns)
    print(f"theme qa [{theme['name']}]: {len(files)} file(s), "
          f"{total_errors} error(s), {total_warnings} warning(s)")
    return 1 if total_errors else 0


if __name__ == "__main__":
    sys.exit(main())
