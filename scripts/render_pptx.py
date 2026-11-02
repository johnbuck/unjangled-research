#!/usr/bin/env python3
"""
PowerPoint renderer (E4-R3): turns a render model (build_render_model.py
JSON) into a native, editable .pptx through pptx_lib.

The content plan comes from slide_plan.plan_slides (E4-R1); this module
lays each planned spec out on pptx_lib's 1280x720 pixel grid, mirroring
the HTML deck's layout (render_deck.py + deck.css/research.css):

    cover     — eyebrow, title, subtitle, date in the left column (the
                motif's keep-outs keep the right side clear), a native
                ellipse dot motif in the bottom-right corner built from
                motif.py's dot positions and the theme's tints (none when
                the theme disables the motif), and the theme logo as a
                PNG picture, brand-name text, or nothing
    statement — headline sentence plus up to three stat tiles (rounded
                rects with tint fills, value large, label small, [N] ref)
    finding /
    section   — title plus up to three bullets, refs as an Evidence
                [N] line
    facet     — facet title plus one tinted panel per side (2-4 columns)
    sources   — numbered entries, hyperlinked titles, "+N more" note

Every non-cover slide carries the theme's footer label (footer.label
formatted with the deck title and the slide's section) at bottom-left, a
slide number at bottom-right, and a thin rule above the footer. Speaker
notes from each spec's notes go on its notes page. Text boxes use word
wrap and normAutofit; sizes are chosen for the clipped lengths in
slide_plan at 1280x720.

    python3 render_pptx.py --model render_model.json [--theme neutral] --out deck.pptx
    python3 render_pptx.py --report report.md [--manifest run_manifest.json] \
        [--format comprehensive-report] [--theme neutral] --out deck.pptx
"""
import argparse
import json
import re
import sys
from pathlib import Path

from build_render_model import build_model
from motif import motif
from pptx_lib import Presentation, logo_payload
from slide_plan import FORMAT_DISPLAY, plan_slides
from theme import footer_label, load_theme, motif_settings

# 1280x720-grid layout, in deck CSS units (cqw = 1% of 1280 = 12.8px):
# slide-body inset 5.4cqw/6.6cqw/3cqw, cover inset 6.4cqw/8cqw/3.2cqw,
# footer rule at the slide-foot's border-top, cover text column max 46cqw.
SLIDE_W = 1280
SLIDE_H = 720
MARGIN_X = 84            # 6.6cqw side inset
CONTENT_W = SLIDE_W - 2 * MARGIN_X
BODY_TOP = 66            # 5.4cqw top inset
FOOT_RULE_Y = 674        # thin rule above the footer
COVER_X = 102            # 8cqw cover side inset
COVER_TEXT_W = 568       # ~46cqw text column; motif keep-outs start past x=740
COVER_MOTIF_SEED = 5     # the HTML cover's motif seed (render_deck parity)

STAT_FILLS = ("accent_tint1", "secondary_tint1", "accent_tint2")
FACET_FILLS = ("accent_tint1", "secondary_tint1", "accent_tint2", "secondary_tint2")

# motif.py emits <circle class="hx hx-o|hx-fill" style="..." cx cy r/>
_CIRCLE_RE = re.compile(
    r'<circle class="hx (hx-o|hx-fill)" style="([^"]*)" '
    r'cx="(-?[\d.]+)" cy="(-?[\d.]+)" r="([\d.]+)"')
_STYLE_COLOR_RE = re.compile(r"(fill|stroke):([^;]+)")


def _notes(spec):
    """Speaker notes: the spec's | -joined note lines become paragraphs."""
    return (spec.get("notes") or "").replace("|", "\n")


def _new_slide(pres, spec):
    return pres.add_slide(notes=_notes(spec))


def _png_size(data):
    """(width, height) from a PNG's IHDR chunk, or (1, 1) if unreadable."""
    if len(data) > 24 and data[12:16] == b"IHDR":
        return (int.from_bytes(data[16:20], "big"),
                int.from_bytes(data[20:24], "big"))
    return 1, 1


def _draw_motif(slide, theme):
    """Native-shape dot motif: one ellipse per motif.py circle, rings
    first-come (surface fill, motif-line stroke), tint dots on top. The
    motif's cover keep-outs keep every dot clear of the text column."""
    settings = motif_settings(theme)
    if not settings["enabled"]:
        return
    svg = motif(seed=COVER_MOTIF_SEED, line=settings["line"],
                tints_a=settings["tints_a"], tints_b=settings["tints_b"],
                tint_a_share=settings["ratio"])
    for i, (kind, style, cx, cy, r) in enumerate(_CIRCLE_RE.findall(svg)):
        cx, cy, r = float(cx), float(cy), float(r)
        colors = dict(_STYLE_COLOR_RE.findall(style))
        if kind == "hx-o":
            slide.ellipse(cx - r, cy - r, 2 * r, 2 * r, fill="surface",
                          line={"color": colors.get("stroke", settings["line"]),
                                "width_pt": 1.0},
                          name=f"Motif ring {i + 1}")
        else:
            slide.ellipse(cx - r, cy - r, 2 * r, 2 * r,
                          fill=colors.get("fill", "surface"), line=None,
                          name=f"Motif dot {i + 1}")


def _header(slide, spec):
    """Eyebrow + title block shared by every non-cover, non-statement slide."""
    slide.text_box(MARGIN_X, BODY_TOP, CONTENT_W, 22,
                   [{"text": (spec.get("eyebrow") or "").upper(), "size": 10,
                     "bold": True, "color": "accent"}],
                   name="Eyebrow")
    slide.text_box(MARGIN_X, BODY_TOP + 26, CONTENT_W, 92,
                   [{"text": spec["title"], "size": 24, "bold": True,
                     "color": "ink", "line_spacing": 1.08}],
                   autofit=True, name="Slide title")


def _footer(slide, spec, deck_title, theme):
    """Thin rule, theme footer label bottom-left, slide number bottom-right."""
    slide.line(MARGIN_X, FOOT_RULE_Y, SLIDE_W - MARGIN_X, FOOT_RULE_Y,
               color="line", width_pt=1.0, name="Footer rule")
    label = footer_label(theme, deck_title, spec.get("section") or "").upper()
    slide.text_box(MARGIN_X, 682, 940, 24,
                   [{"text": label, "size": 8, "color": "muted"}],
                   name="Footer label")
    slide.text_box(SLIDE_W - MARGIN_X - 120, 682, 120, 24,
                   [{"text": f"{spec['number']:02d}", "size": 8, "bold": True,
                     "color": "muted", "align": "right"}],
                   name="Slide number")


def _cover_slide(pres, spec, deck_title, theme):
    slide = _new_slide(pres, spec)
    _draw_motif(slide, theme)          # behind the text; never overlaps it
    payload = logo_payload(theme)
    if payload:
        kind, data = payload
        if kind == "png":
            w, h = _png_size(data)
            box_h = 42                 # 3.3cqw cover logo height
            box_w = min(300, max(24, round(box_h * w / max(h, 1))))
            slide.picture_png(COVER_X, 82, box_w, box_h, data, name="Cover logo")
        else:
            slide.text_box(COVER_X, 78, 520, 44,
                           [{"text": data, "size": 14, "bold": True, "color": "ink"}],
                           name="Cover brand")
    paras = [{"text": (spec.get("eyebrow") or "").upper(), "size": 10,
              "bold": True, "color": "accent", "space_after": 18}]
    paras.append({"text": spec["title"], "size": 40, "bold": True,
                  "color": "ink", "line_spacing": 1.05, "space_after": 18})
    if spec.get("subtitle"):
        paras.append({"text": spec["subtitle"], "size": 14, "color": "body",
                      "line_spacing": 1.3, "space_after": 22})
    if spec.get("date"):
        paras.append({"text": str(spec["date"]).upper(), "size": 9.5,
                      "bold": True, "color": "muted"})
    slide.text_box(COVER_X, 200, COVER_TEXT_W, 372, paras,
                   anchor="ctr", autofit=True, name="Cover text")


def _statement_slide(pres, spec, deck_title, theme):
    slide = _new_slide(pres, spec)
    slide.text_box(MARGIN_X, BODY_TOP, CONTENT_W, 22,
                   [{"text": (spec.get("eyebrow") or "").upper(), "size": 10,
                     "bold": True, "color": "accent"}],
                   name="Eyebrow")
    stats = [s for s in (spec.get("stats") or []) if s]
    if stats:
        slide.text_box(MARGIN_X, 104, CONTENT_W, 190,
                       [{"text": spec["title"], "size": 28, "bold": True,
                         "color": "ink", "line_spacing": 1.12}],
                       autofit=True, anchor="ctr", name="Statement headline")
        gap = 24
        tile_w = (CONTENT_W - gap * (len(stats) - 1)) / len(stats)
        y, tile_h = 320, 240
        for i, stat in enumerate(stats):
            x = MARGIN_X + i * (tile_w + gap)
            slide.rect(x, y, tile_w, tile_h, fill=STAT_FILLS[i % len(STAT_FILLS)],
                       radius=16, name=f"Stat tile {i + 1}")
            num, unit = stat["parts"]
            value_runs = [{"text": num, "size": 34, "color": "ink"}]
            if unit:
                value_runs.append({"text": " " + unit, "size": 14, "color": "muted"})
            slide.text_box(x + 22, y + 26, tile_w - 44, 66,
                           [{"runs": value_runs, "line_spacing": 1.0}],
                           name=f"Stat value {i + 1}")
            label_runs = [{"text": stat["label"] or "", "size": 11, "color": "body"}]
            if stat.get("ref") is not None:
                label_runs.append({"text": f"  [{stat['ref']}]", "size": 11,
                                   "color": "muted"})
            slide.text_box(x + 22, y + 100, tile_w - 44, 118,
                           [{"runs": label_runs, "line_spacing": 1.25}],
                           autofit=True, name=f"Stat label {i + 1}")
    else:
        slide.text_box(MARGIN_X, 140, CONTENT_W, 400,
                       [{"text": spec["title"], "size": 30, "bold": True,
                         "color": "ink", "line_spacing": 1.12}],
                       autofit=True, anchor="ctr", name="Statement headline")
    _footer(slide, spec, deck_title, theme)


def _bullets_body(slide, spec):
    """Bullet points + evidence line: the finding / section / facet-fallback
    main area (mirrors render_deck's _bulleted_body)."""
    bullets = spec.get("bullets") or []
    paras = [{"text": b["text"], "size": 13, "color": "body",
              "bullet": {"color": "secondary", "indent_px": 22},
              "line_spacing": 1.25, "space_after": 12} for b in bullets]
    if paras:
        slide.text_box(MARGIN_X, 214, CONTENT_W, 330, paras,
                       autofit=True, name="Bullets")
        refs = bullets[0].get("refs") or []
        if refs:
            slide.text_box(MARGIN_X, 566, CONTENT_W, 26,
                           [{"text": "Evidence: " + " ".join(f"[{r}]" for r in refs),
                             "size": 9.5, "color": "muted"}],
                           name="Evidence")
    else:
        slide.text_box(MARGIN_X, 300, CONTENT_W, 60,
                       [{"text": "Detailed in the full report.", "size": 12,
                         "color": "muted"}],
                       name="Fallback note")


def _bulleted_slide(pres, spec, deck_title, theme):
    slide = _new_slide(pres, spec)
    _header(slide, spec)
    _bullets_body(slide, spec)
    _footer(slide, spec, deck_title, theme)


def _facet_slide(pres, spec, deck_title, theme):
    slide = _new_slide(pres, spec)
    _header(slide, spec)
    sides = spec.get("sides") or []
    if sides:
        cols = min(len(sides), 4) if len(sides) > 1 else 1
        rows = -(-len(sides) // cols)
        gap = 20
        top, bottom = 212, 656
        panel_h = (bottom - top - (rows - 1) * gap) / rows
        panel_w = (CONTENT_W - (cols - 1) * gap) / cols
        for j, side in enumerate(sides):
            r, c = divmod(j, cols)
            x = MARGIN_X + c * (panel_w + gap)
            y = top + r * (panel_h + gap)
            slide.rect(x, y, panel_w, panel_h, fill=FACET_FILLS[j % len(FACET_FILLS)],
                       radius=14, name=f"Facet panel {j + 1}")
            slide.text_box(x + 20, y + 16, panel_w - 40, 46,
                           [{"text": side["label"], "size": 13, "bold": True,
                             "color": "ink", "line_spacing": 1.15}],
                           autofit=True, name=f"Facet label {j + 1}")
            slide.text_box(x + 20, y + 68, panel_w - 40, panel_h - 86,
                           [{"text": side["summary"], "size": 11, "color": "body",
                             "line_spacing": 1.3}],
                           autofit=True, name=f"Facet summary {j + 1}")
    else:
        _bullets_body(slide, spec)
    _footer(slide, spec, deck_title, theme)


def _sources_slide(pres, spec, deck_title, theme):
    slide = _new_slide(pres, spec)
    _header(slide, spec)
    paras = []
    for src in spec.get("sources") or []:
        runs = [{"text": f"[{src['n']}]  ", "size": 10, "bold": True, "color": "ink"}]
        title_run = {"text": src["title"], "size": 10, "color": "body"}
        if src.get("url"):
            title_run["url"] = src["url"]
            title_run["color"] = "accent_ink"
        runs.append(title_run)
        if src.get("publisher"):
            runs.append({"text": f" — {src['publisher']}", "size": 10, "color": "muted"})
        paras.append({"runs": runs, "line_spacing": 1.15, "space_after": 8})
    if paras:
        slide.text_box(MARGIN_X, 202, CONTENT_W, 420, paras,
                       autofit=True, name="Sources")
    else:
        slide.text_box(MARGIN_X, 300, CONTENT_W, 60,
                       [{"text": "No sources listed in the render model.", "size": 12,
                         "color": "muted"}],
                       name="No sources note")
    if spec.get("more_sources"):
        slide.text_box(MARGIN_X, 630, CONTENT_W, 24,
                       [{"text": f"+{spec['more_sources']} more in the full report",
                         "size": 9.5, "color": "muted"}],
                       name="More sources")
    _footer(slide, spec, deck_title, theme)


_RENDERERS = {
    "cover": _cover_slide,
    "statement": _statement_slide,
    "finding": _bulleted_slide,
    "section": _bulleted_slide,
    "facet": _facet_slide,
    "sources": _sources_slide,
}


def build_presentation(model, theme="neutral"):
    """Compose the .pptx from a render model's slide plan (one slide per
    planned spec, in plan order)."""
    theme_obj = theme if isinstance(theme, dict) else load_theme(theme)
    specs = plan_slides(model)
    deck_title = specs[0]["title"]
    pres = Presentation(theme_obj, title=deck_title, creator="render_pptx")
    for spec in specs:
        _RENDERERS[spec["kind"]](pres, spec, deck_title, theme_obj)
    return pres


def render_pptx(model, out_path, theme="neutral"):
    """Render the model's slide plan and write the .pptx to out_path."""
    pres = build_presentation(model, theme)
    out = Path(out_path)
    if str(out.parent) and not out.parent.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
    pres.save(str(out))
    return str(out)


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as exc:
        print(f"ERROR: {path} is not valid JSON ({exc})", file=sys.stderr)
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser(
        description="Render a native editable PowerPoint deck from a render model (E4-R3)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 render_pptx.py --model render_model.json --out deck.pptx
  python3 render_pptx.py --report report.md --manifest run_manifest.json --out deck.pptx
  python3 render_pptx.py --report report.md --theme tests/fixtures/themes/alt --out deck.pptx
        """,
    )
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--model", help="render model JSON (from build_render_model.py)")
    src.add_argument("--report", "-r", help="report markdown; the model is built in-process")
    ap.add_argument("--manifest", "-m", default=None, help="run_manifest.json for --report")
    ap.add_argument("--format", "-f", default=None,
                    choices=sorted(FORMAT_DISPLAY.keys()),
                    help="report format; default: manifest value, else inferred")
    ap.add_argument("--theme", default="neutral", metavar="NAME_OR_PATH",
                    help="theme name under themes/ or a theme folder path (default: neutral)")
    ap.add_argument("--out", "-o", required=True, help="write the .pptx deck here")
    args = ap.parse_args()

    if args.model:
        if args.manifest or args.format:
            ap.error("--manifest/--format apply to --report, not --model")
        model = _load_json(args.model)
        missing = [k for k in ("title", "sections", "sources") if k not in model]
        if missing:
            print(f"ERROR: render model is missing {', '.join(missing)}: {args.model}",
                  file=sys.stderr)
            sys.exit(1)
    else:
        report_path = Path(args.report)
        if not report_path.exists():
            print(f"ERROR: report not found: {report_path}", file=sys.stderr)
            sys.exit(1)
        manifest = _load_json(args.manifest) if args.manifest else None
        model = build_model(report_path.read_text(encoding="utf-8"), manifest, args.format)

    out = render_pptx(model, args.out, theme=args.theme)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
