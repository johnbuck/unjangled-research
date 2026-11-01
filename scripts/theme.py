"""Theme contract: load and validate a theme folder, emit the renderer's
:root token block, and expose the theme's font CSS, logo, footer label
template, and motif settings.

A theme is a folder holding theme.json plus optional assets: embedded
@font-face rules (fonts.css), and a logo (an SVG or PNG in the folder,
embedded as a data URI). Every required key is validated with an error
that names the bad key path, e.g. "colors.accent_tints: expected 4 hex
colors". Optional keys (fonts.css, logo, brand_name) may be absent.

Usage:
    from theme import load_theme, css_vars, font_css, logo_data_uri, footer_label, motif_settings
    t = load_theme("neutral")           # bare name resolves under themes/
    t = load_theme("path/to/folder")    # or any theme folder path
    head_css = css_vars(t) + font_css(t)

CLI self-test:  python3 theme.py
"""
import base64
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
THEMES_DIR = os.path.join(HERE, "..", "themes")

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_LOGO_MIME = {".svg": "image/svg+xml", ".png": "image/png"}

_COLOR_KEYS = ("surface", "ink", "body", "muted", "line", "line_strong", "fill",
               "accent", "accent_ink", "secondary", "secondary_ink")
_TINT_KEYS = ("accent_tints", "secondary_tints")


def _fail(path, message):
    raise ValueError(f"{path}: {message}")


def _need(obj, key, parent):
    if key not in obj:
        _fail(f"{parent}.{key}" if parent else key, "missing key")
    return obj[key]


def _section(data, key):
    value = _need(data, key, "")
    if not isinstance(value, dict):
        _fail(key, "expected an object")
    return value


def _check_str(value, path):
    if not isinstance(value, str) or not value.strip():
        _fail(path, f"expected a non-empty string, got {value!r}")
    return value


def _check_bool(value, path):
    if not isinstance(value, bool):
        _fail(path, f"expected true or false, got {value!r}")
    return value


def _check_hex(value, path):
    if not isinstance(value, str) or not _HEX.match(value):
        _fail(path, f"expected a 6-digit hex color like #4F46E5, got {value!r}")
    return value


def _check_hex_list(value, path, length=None, allow_empty=False):
    if not isinstance(value, list) or (not value and not allow_empty):
        _fail(path, "expected a list of hex colors")
    for i, item in enumerate(value):
        _check_hex(item, f"{path}[{i}]")
    if length is not None and len(value) != length:
        _fail(path, f"expected {length} hex colors, got {len(value)}")
    return value


def load_theme(name_or_path):
    """Load and validate a theme. A bare name resolves to themes/<name>/;
    any argument containing a path separator is treated as a folder path."""
    if os.path.isabs(name_or_path) or os.sep in name_or_path or (os.altsep and os.altsep in name_or_path):
        folder = name_or_path
    else:
        folder = os.path.join(THEMES_DIR, name_or_path)
    folder = os.path.normpath(folder)
    theme_json = os.path.join(folder, "theme.json")
    if not os.path.isfile(theme_json):
        _fail(name_or_path, f"no theme.json under {folder}")
    try:
        with open(theme_json, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        _fail(name_or_path, f"theme.json is not valid JSON ({exc})")
    if not isinstance(data, dict):
        _fail(name_or_path, "theme.json must hold a JSON object")

    _check_str(_need(data, "name", ""), "name")

    colors = _section(data, "colors")
    for key in _COLOR_KEYS:
        _check_hex(_need(colors, key, "colors"), f"colors.{key}")
    for key in _TINT_KEYS:
        _check_hex_list(_need(colors, key, "colors"), f"colors.{key}", length=4)

    fonts = _section(data, "fonts")
    _check_str(_need(fonts, "family", "fonts"), "fonts.family")
    _check_str(_need(fonts, "fallback", "fonts"), "fonts.fallback")
    css_file = fonts.get("css")
    if css_file is not None:
        _check_str(css_file, "fonts.css")
        if not os.path.isfile(os.path.join(folder, css_file)):
            _fail("fonts.css", f"file {css_file!r} not found in the theme folder")

    logo = data.get("logo")
    if logo is not None:
        _check_str(logo, "logo")
        if os.path.splitext(logo)[1].lower() not in _LOGO_MIME:
            _fail("logo", "expected an .svg or .png file in the theme folder")
        if not os.path.isfile(os.path.join(folder, logo)):
            _fail("logo", f"file {logo!r} not found in the theme folder")
    if data.get("brand_name") is not None:
        _check_str(data["brand_name"], "brand_name")

    footer = _section(data, "footer")
    _check_str(_need(footer, "label", "footer"), "footer.label")

    motif = _section(data, "motif")
    _check_bool(_need(motif, "enabled", "motif"), "motif.enabled")
    _check_hex_list(_need(motif, "tints_a", "motif"), "motif.tints_a")
    _check_hex_list(_need(motif, "tints_b", "motif"), "motif.tints_b")
    ratio = _need(motif, "ratio", "motif")
    if isinstance(ratio, bool) or not isinstance(ratio, (int, float)) or not 0 < ratio < 1:
        _fail("motif.ratio", f"expected a share between 0 and 1, got {ratio!r}")
    _check_hex(_need(motif, "line", "motif"), "motif.line")

    qa = _section(data, "qa")
    _check_hex_list(_need(qa, "allowed_colors", "qa"), "qa.allowed_colors", allow_empty=True)
    forbidden = _need(qa, "forbidden_colors", "qa")
    if not isinstance(forbidden, dict):
        _fail("qa.forbidden_colors", "expected an object mapping hex colors to reasons")
    for hex_key, reason in forbidden.items():
        _check_hex(hex_key, f"qa.forbidden_colors[{hex_key}]")
        if not isinstance(reason, str) or not reason.strip():
            _fail(f"qa.forbidden_colors[{hex_key}]", "expected a reason string")
    _check_bool(_need(qa, "forbid_dark_surfaces", "qa"), "qa.forbid_dark_surfaces")

    data["_dir"] = folder
    return data


def css_vars(theme):
    """The :root{--rf-*} token block every renderer document is fed from."""
    c = theme["colors"]
    parts = [
        f"--rf-surface:{c['surface']}",
        f"--rf-ink:{c['ink']}",
        f"--rf-body:{c['body']}",
        f"--rf-muted:{c['muted']}",
        f"--rf-line:{c['line']}",
        f"--rf-line-strong:{c['line_strong']}",
        f"--rf-fill:{c['fill']}",
        f"--rf-accent:{c['accent']}",
        f"--rf-accent-ink:{c['accent_ink']}",
    ]
    parts += [f"--rf-accent-t{i + 1}:{h}" for i, h in enumerate(c["accent_tints"])]
    parts += [
        f"--rf-secondary:{c['secondary']}",
        f"--rf-secondary-ink:{c['secondary_ink']}",
    ]
    parts += [f"--rf-secondary-t{i + 1}:{h}" for i, h in enumerate(c["secondary_tints"])]
    parts += [
        "--rf-on-accent:var(--rf-surface)",
        "--rf-stage-bg:var(--rf-fill)",
        "--rf-stage-bg-full:var(--rf-ink)",
        "--rf-chrome-bg:var(--rf-surface)",
        "--rf-chrome-ink:var(--rf-ink)",
        "--rf-chrome-line:var(--rf-line)",
        f"--rf-motif-line:{theme['motif']['line']}",
        f"--rf-type:\"{theme['fonts']['family']}\",{theme['fonts']['fallback']}",
    ]
    return ":root{" + ";".join(parts) + "}"


def font_css(theme):
    """The theme's embedded @font-face rules, or "" when the theme has none."""
    css_file = theme["fonts"].get("css")
    if not css_file:
        return ""
    with open(os.path.join(theme["_dir"], css_file), encoding="utf-8") as f:
        return f.read()


def logo_data_uri(theme):
    """The theme's logo as a data URI, or None when the theme has no logo."""
    logo = theme.get("logo")
    if not logo:
        return None
    mime = _LOGO_MIME[os.path.splitext(logo)[1].lower()]
    with open(os.path.join(theme["_dir"], logo), "rb") as f:
        return f"data:{mime};base64," + base64.b64encode(f.read()).decode("ascii")


def footer_label(theme, title="", section=""):
    """Format the theme's footer label template ({title} / {section})."""
    return (theme["footer"]["label"]
            .replace("{title}", str(title))
            .replace("{section}", str(section)))


def motif_settings(theme):
    """The theme's motif block as a plain settings dict."""
    m = theme["motif"]
    return {"enabled": bool(m["enabled"]), "tints_a": list(m["tints_a"]),
            "tints_b": list(m["tints_b"]), "ratio": m["ratio"], "line": m["line"]}


if __name__ == "__main__":
    t = load_theme("neutral")
    block = css_vars(t)
    assert block.startswith(":root{--rf-") and '"Lato"' in block
    assert "Lato Brand" not in font_css(t) and font_css(t).lstrip().startswith("@font-face")
    assert logo_data_uri(t) is None
    assert footer_label(t, "Report", "Q4") == "Report — Q4"
    m = motif_settings(t)
    assert m["enabled"] and len(m["tints_a"]) == 8 and m["line"] == "#E0E0E0"
    print("theme self-test ok:", len(block), "chars of css vars,", len(font_css(t)), "chars of font css")
