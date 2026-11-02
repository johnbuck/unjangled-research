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
    are allowed - bibliography links), @import, or url()
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
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
import zlib

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
                if rtype != HYPERLINK_REL:
                    errs.append(f"external relationship of type {rtype} in {name} "
                                f"({rel.get('Target')})")
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

    for m in re.finditer(r"\ssrc\s*=\s*(?:\"([^\"]*)\"|'([^']*)')", src):
        url = m.group(1) or m.group(2) or ""
        if _is_external(url):
            errs.append(f"external resource in src= ({url})")
    for m in re.finditer(r"<([a-zA-Z][\w-]*)[^>]*?\shref\s*=\s*(?:\"([^\"]*)\"|'([^']*)')", src):
        tag, url = m.group(1).lower(), (m.group(2) or m.group(3) or "")
        if tag != "a" and _is_external(url):
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
