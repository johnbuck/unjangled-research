#!/usr/bin/env python3
"""
PowerPoint renderer (E4-R3): turns a render model (build_render_model.py
JSON) into a native, editable .pptx through pptx_lib — and, per E5-R3,
any authored slide list (schemas/deck_spec.schema.json) as well.

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

Slide-list decks (E5-R1, deck_spec.py) render through the same shared
builders for the five layouts the research plan emits, plus one builder
per authored layout, each mirroring its HTML rules (render_deck.py +
deck.css/research.css/deck_layouts.css):

    section   — divider: large section name, sub line, accent bar
    agenda    — numbered rows (01..N) between hairline rules
    two_column — two titled panels, the right one tinted
    three_values — three numbered columns over hairline rules, note
    compare   — two cards (problem vs. solution) with x/check rows,
                kicker lines, and an arrow between them
    bars      — ranked horizontal bars as rectangles scaled to the max
                value (label above, display value right), note
    quote     — large quotation with attribution
    closing   — headline plus numbered next steps

Every non-cover slide carries the theme's footer label (footer.label
formatted with the deck title and the slide's section) at bottom-left, a
slide number at bottom-right, and a thin rule above the footer. Speaker
notes from each spec's notes go on its notes page. Text boxes use word
wrap and normAutofit; sizes are chosen for the clipped lengths in
slide_plan at 1280x720.

    python3 render_pptx.py --model render_model.json [--theme neutral] --out deck.pptx
    python3 render_pptx.py --report report.md [--manifest run_manifest.json] \
        [--format comprehensive-report] [--theme neutral] --out deck.pptx
    python3 render_pptx.py --slides deck.json [--theme neutral] --out deck.pptx
"""
import argparse
import json
import re
import sys
from pathlib import Path

from build_render_model import build_model
from deck_spec import DeckError, load_deck, validate_deck
from motif import motif
from pptx_lib import Presentation, logo_payload
from slide_plan import FORMAT_DISPLAY, plan_slides, stat_parts
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


# ---------- slide-list decks (E5-R3) ----------
# Grid numbers mirror the HTML rules in deck.css, research.css, and
# deck_layouts.css (1cqw = 12.8px; sizes scaled like the research slides).
AGENDA_TOP, AGENDA_BOTTOM = 210, 648      # agenda rows region
PANEL_TOP, PANEL_BOTTOM = 206, 650        # two-column panels
COMPARE_TOP, COMPARE_BOTTOM = 200, 650    # compare cards
COMPARE_GAP, COMPARE_ARROW_W = 33, 56     # 2.6cqw gap, 4.4cqw arrow circle
BARS_TOP, BARS_BOTTOM = 206, 630          # bars region (note rides with it)


def _section_of(slide, deck, layout):
    return (slide.get("section") or deck.get("footer_section")
            or layout.replace("_", " ").title())


def _spec_of(slide, deck, n):
    """The shared spec shape (eyebrow/title/section/number/notes) the
    research builders and the footer read; statement overrides title."""
    section = _section_of(slide, deck, slide["layout"])
    return {"eyebrow": slide.get("eyebrow") or section, "title": slide.get("title") or "",
            "section": section, "number": n, "notes": slide.get("notes") or ""}


def _eyebrow_head(slide, eyebrow):
    """Header carrying only the eyebrow (statement-style), mirroring
    render_deck's _eyebrow_head."""
    slide.text_box(MARGIN_X, BODY_TOP, CONTENT_W, 22,
                   [{"text": (eyebrow or "").upper(), "size": 10,
                     "bold": True, "color": "accent"}],
                   name="Eyebrow")


def _est_lines(text, width_px, size_px, bold=False):
    """Estimated wrapped-line count for plain text at a deck-px size in a
    box of width_px (HTML text cannot be measured here; ~0.5em per glyph
    is conservative for the themes' sans faces)."""
    if not text:
        return 0
    per_char = size_px * (0.54 if bold else 0.5)
    return max(1, -(-len(text) * per_char // width_px))


def _deck_cover_slide(pres, slide, deck, deck_title, theme, n):
    sub = slide["subtitle"] if slide.get("subtitle") is not None \
        else (deck.get("subtitle") or "")
    date = slide["date"] if slide.get("date") is not None \
        else (deck.get("date") or "")
    spec = {"eyebrow": slide.get("eyebrow") or deck.get("eyebrow") or "",
            "title": slide["title"], "subtitle": sub, "date": date,
            "notes": slide.get("notes") or ""}
    _cover_slide(pres, spec, deck_title, theme)


def _deck_statement_slide(pres, slide, deck, deck_title, theme, n):
    spec = _spec_of(slide, deck, n)
    spec["title"] = slide["headline"]
    spec["stats"] = [{"value": s["value"], "label": s["label"], "ref": s.get("ref"),
                      "parts": list(stat_parts(s["value"]))}
                     for s in slide.get("stats") or []]
    _statement_slide(pres, spec, deck_title, theme)


def _deck_bullets_slide(pres, slide, deck, deck_title, theme, n):
    spec = _spec_of(slide, deck, n)
    if slide.get("bullets"):
        spec["bullets"] = slide["bullets"]
        _bulleted_slide(pres, spec, deck_title, theme)
        return
    slide_obj = _new_slide(pres, spec)
    _header(slide_obj, spec)
    refs = slide.get("refs") or []
    if refs:
        slide_obj.text_box(MARGIN_X, 300, CONTENT_W, 60,
                           [{"text": "Evidence: " + " ".join(f"[{r}]" for r in refs),
                             "size": 9.5, "color": "muted"}],
                           name="Evidence")
    else:
        slide_obj.text_box(MARGIN_X, 300, CONTENT_W, 60,
                           [{"text": "Detailed in the full report.", "size": 12,
                             "color": "muted"}],
                           name="Fallback note")
    _footer(slide_obj, spec, deck_title, theme)


def _deck_facet_slide(pres, slide, deck, deck_title, theme, n):
    spec = _spec_of(slide, deck, n)
    spec["sides"] = slide.get("sides") or []
    spec["bullets"] = slide.get("bullets") or []
    _facet_slide(pres, spec, deck_title, theme)


def _deck_sources_slide(pres, slide, deck, deck_title, theme, n):
    spec = _spec_of(slide, deck, n)
    spec["sources"] = slide["sources"]
    spec["more_sources"] = slide.get("more_sources") or 0
    _sources_slide(pres, spec, deck_title, theme)


def _section_pptx_slide(pres, slide, deck, deck_title, theme, n):
    """Section divider: eyebrow, centered large title + sub, accent bar
    directly below them, all one centered group (mirrors .layout-divider /
    .divider-title / .kbar)."""
    spec = _spec_of(slide, deck, n)
    slide_obj = _new_slide(pres, spec)
    _eyebrow_head(slide_obj, spec["eyebrow"])
    paras = [{"text": slide["title"], "size": 34, "bold": True, "color": "ink",
              "line_spacing": 1.08}]
    if slide.get("sub"):
        paras.append({"text": slide["sub"], "size": 12.5, "color": "body",
                      "line_spacing": 1.4, "space_before": 16})
    slide_obj.text_box(MARGIN_X, 120, 640, 440, paras,
                       anchor="ctr", autofit=True, name="Divider title")
    est = (_est_lines(slide["title"], 640, 34, bold=True) * 34 * 1.08
           + (_est_lines(slide["sub"], 640, 12.5) * (16 + 12.5 * 1.4)
              if slide.get("sub") else 0))
    bar_y = min(120 + 440 / 2 + est / 2 + 12, 600)
    slide_obj.rect(MARGIN_X, bar_y, 44, 4, fill="secondary", radius=2, name="Divider bar")
    _footer(slide_obj, spec, deck_title, theme)


def _agenda_pptx_slide(pres, slide, deck, deck_title, theme, n):
    """Numbered agenda rows between hairline rules (mirrors .agenda-list;
    the last row's number and title are muted)."""
    spec = _spec_of(slide, deck, n)
    slide_obj = _new_slide(pres, spec)
    _header(slide_obj, spec)
    items = slide["items"]
    count = len(items)
    row_h = (AGENDA_BOTTOM - AGENDA_TOP) / count
    for j in range(count + 1):
        y = AGENDA_TOP + j * row_h
        slide_obj.line(MARGIN_X, y, SLIDE_W - MARGIN_X, y,
                       color="line", width_pt=1.0, name=f"Agenda rule {j + 1}")
    for j, item in enumerate(items):
        y, last = AGENDA_TOP + j * row_h, j == count - 1
        slide_obj.text_box(MARGIN_X, y, 96, row_h,
                           [{"text": f"{j + 1:02d}", "size": 24,
                             "color": "muted" if last else "accent"}],
                           anchor="ctr", name=f"Agenda number {j + 1}")
        slide_obj.text_box(MARGIN_X + 110, y, 272, row_h,
                           [{"text": item["title"], "size": 18, "bold": True,
                             "color": "muted" if last else "ink", "line_spacing": 1.15}],
                           anchor="ctr", autofit=True, name=f"Agenda item {j + 1}")
        if item.get("desc"):
            slide_obj.text_box(MARGIN_X + 400, y, CONTENT_W - 400, row_h,
                               [{"text": item["desc"], "size": 12.5, "color": "body",
                                 "line_spacing": 1.3}],
                               anchor="ctr", autofit=True, name=f"Agenda desc {j + 1}")
    _footer(slide_obj, spec, deck_title, theme)


def _two_column_pptx_slide(pres, slide, deck, deck_title, theme, n):
    """Two titled panels side by side at content height, centered in the
    body region as one row (the HTML grid row is as tall as the taller
    panel), the right one tinted (mirrors .two-col-panels / .col-panel)."""
    spec = _spec_of(slide, deck, n)
    slide_obj = _new_slide(pres, spec)
    _header(slide_obj, spec)
    gap = 33                     # 2.6cqw panel gap
    panel_w = (CONTENT_W - gap) / 2

    def content_h(panel):
        w = panel_w - 56
        if panel.get("body") is not None:
            return _est_lines(panel["body"], w, 11.5) * 11.5 * 1.5
        return sum(_est_lines(b["text"], w, 11) * 11 * 1.35 + 8
                   for b in panel.get("bullets") or [])

    ests = [26 + _est_lines(slide[k]["title"], panel_w - 56, 16, bold=True)
            * 16 * 1.25 + 14 + content_h(slide[k]) + 26
            for k in ("left", "right")]
    region_h = PANEL_BOTTOM - PANEL_TOP
    panel_h = min(max(max(ests), 120), region_h)
    y = PANEL_TOP + (region_h - panel_h) / 2
    for j, key in enumerate(("left", "right")):
        panel = slide[key]
        x = MARGIN_X + j * (panel_w + gap)
        if key == "right":
            slide_obj.rect(x, y, panel_w, panel_h, fill="accent_tint1",
                           radius=18, name="Column panel right")
        else:
            slide_obj.rect(x, y, panel_w, panel_h, fill=None,
                           line={"color": "line", "width_pt": 1.0},
                           radius=18, name="Column panel left")
        title_h = max(_est_lines(panel["title"], panel_w - 56, 16, bold=True)
                      * 16 * 1.25, 22)
        slide_obj.text_box(x + 28, y + 26, panel_w - 56, title_h,
                           [{"text": panel["title"], "size": 16, "bold": True,
                             "color": "ink", "line_spacing": 1.25}],
                           autofit=True, name=f"Column title {j + 1}")
        body_top = y + 26 + title_h + 14
        body_h = max(y + panel_h - 26 - body_top, 20)
        if panel.get("body") is not None:
            slide_obj.text_box(x + 28, body_top, panel_w - 56, body_h,
                               [{"text": panel["body"], "size": 11.5, "color": "body",
                                 "line_spacing": 1.5}],
                               autofit=True, name=f"Column body {j + 1}")
        else:
            paras = [{"text": b["text"], "size": 11, "color": "body",
                      "bullet": {"color": "secondary", "indent_px": 18},
                      "line_spacing": 1.35, "space_after": 8}
                     for b in panel.get("bullets") or []]
            slide_obj.text_box(x + 28, body_top, panel_w - 56, body_h,
                               paras, autofit=True, name=f"Column bullets {j + 1}")
    _footer(slide_obj, spec, deck_title, theme)


def _three_values_pptx_slide(pres, slide, deck, deck_title, theme, n):
    """Three numbered columns over hairline rules plus note (mirrors
    .value-grid / .value-line / .value-num)."""
    spec = _spec_of(slide, deck, n)
    slide_obj = _new_slide(pres, spec)
    _header(slide_obj, spec)
    gap = 51                     # 4cqw column gap
    col_w = (CONTENT_W - 2 * gap) / 3
    for j, value in enumerate(slide["values"]):
        x = MARGIN_X + j * (col_w + gap)
        slide_obj.line(x, 214, x + col_w, 214, color="line", width_pt=2.0,
                       name=f"Value rule {j + 1}")
        slide_obj.text_box(x, 226, col_w, 70,
                           [{"text": f"{j + 1:02d}", "size": 40, "color": "accent"}],
                           name=f"Value number {j + 1}")
        slide_obj.text_box(x, 302, col_w, 44,
                           [{"text": value["title"], "size": 15, "bold": True,
                             "color": "ink", "line_spacing": 1.2}],
                           autofit=True, name=f"Value title {j + 1}")
        slide_obj.text_box(x, 350, col_w, 240,
                           [{"text": value["body"], "size": 11.5, "color": "body",
                             "line_spacing": 1.5}],
                           autofit=True, name=f"Value body {j + 1}")
    if slide.get("note"):
        grid_bottom = 350 + max(_est_lines(v["body"], col_w, 11.5)
                                for v in slide["values"]) * 11.5 * 1.5
        note_y = min(grid_bottom + 14, 600)
        slide_obj.text_box(MARGIN_X, note_y, CONTENT_W, 24,
                           [{"text": slide["note"], "size": 9.5, "color": "muted"}],
                           name="Values note")
    _footer(slide_obj, spec, deck_title, theme)


def _compare_pptx_slide(pres, slide, deck, deck_title, theme, n):
    """Two cards (problem vs. solution) with marked rows and kickers, an
    arrow circle between them (mirrors .compare-card / .marks /
    .compare-arrow)."""
    spec = _spec_of(slide, deck, n)
    slide_obj = _new_slide(pres, spec)
    _header(slide_obj, spec)
    card_w = (CONTENT_W - COMPARE_ARROW_W - 2 * COMPARE_GAP) / 2
    card_h = COMPARE_BOTTOM - COMPARE_TOP
    default_tags = ("Option A", "Option B")
    for j, (option, kind) in enumerate(zip(slide["options"], ("problem", "solution"))):
        x = MARGIN_X + j * (card_w + COMPARE_GAP + COMPARE_ARROW_W + COMPARE_GAP)
        if kind == "problem":
            slide_obj.rect(x, COMPARE_TOP, card_w, card_h, fill=None,
                           line={"color": "line", "width_pt": 1.0},
                           radius=18, name=f"Compare card {j + 1}")
        else:
            slide_obj.rect(x, COMPARE_TOP, card_w, card_h, fill="accent_tint1",
                           radius=18, name=f"Compare card {j + 1}")
        tone = "muted" if kind == "problem" else "accent"
        slide_obj.text_box(x + 38, COMPARE_TOP + 34, card_w - 76, 20,
                           [{"text": (option.get("tag") or default_tags[j]).upper(),
                             "size": 9, "bold": True, "color": tone}],
                           name=f"Compare tag {j + 1}")
        slide_obj.text_box(x + 38, COMPARE_TOP + 58, card_w - 76, 48,
                           [{"text": option["name"], "size": 15, "bold": True,
                             "color": "ink", "line_spacing": 1.25}],
                           autofit=True, name=f"Compare name {j + 1}")
        kicker_y = COMPARE_TOP + card_h - 38 - 44 if option.get("kicker") else None
        rows_top = COMPARE_TOP + 118
        rows_bottom = (kicker_y - 10) if kicker_y is not None else (COMPARE_BOTTOM - 38)
        rows = option["rows"]
        row_h = (rows_bottom - rows_top) / len(rows)
        mark, mark_fill = (("\u00d7", "fill") if kind == "problem"
                           else ("\u2713", "surface"))
        for i, row in enumerate(rows):
            y = rows_top + i * row_h
            slide_obj.ellipse(x + 38, y + 2, 19, 19, fill=mark_fill,
                              name=f"Compare mark {j + 1}.{i + 1}")
            slide_obj.text_box(x + 38, y + 2, 19, 19,
                               [{"text": mark, "size": 8, "bold": True,
                                 "color": tone}],
                               align="center",
                               anchor="ctr", name=f"Compare mark glyph {j + 1}.{i + 1}")
            slide_obj.text_box(x + 65, y, card_w - 103, row_h - 4,
                               [{"text": row, "size": 11, "color": "body",
                                 "line_spacing": 1.35}],
                               autofit=True, name=f"Compare row {j + 1}.{i + 1}")
        if kicker_y is not None:
            slide_obj.text_box(x + 38, kicker_y, card_w - 76, 44,
                               [{"text": option["kicker"], "size": 11, "bold": True,
                                 "color": tone, "line_spacing": 1.3}],
                               autofit=True, name=f"Compare kicker {j + 1}")
    arrow_x = MARGIN_X + card_w + COMPARE_GAP
    arrow_y = (COMPARE_TOP + COMPARE_BOTTOM) / 2 - COMPARE_ARROW_W / 2
    slide_obj.ellipse(arrow_x, arrow_y, COMPARE_ARROW_W, COMPARE_ARROW_W,
                      fill="secondary_tint2", name="Compare arrow")
    slide_obj.text_box(arrow_x, arrow_y, COMPARE_ARROW_W, COMPARE_ARROW_W,
                       [{"text": "\u2192", "size": 16, "bold": True,
                         "color": "secondary_ink"}],
                       align="center",
                       anchor="ctr", name="Compare arrow glyph")
    _footer(slide_obj, spec, deck_title, theme)


def _bars_pptx_slide(pres, slide, deck, deck_title, theme, n):
    """Ranked horizontal bars scaled to the max value: label above, thin
    track, one fill rectangle per bar, display value right, note directly
    below the last row; the whole block is one centered group and shrinks
    uniformly when the schema-max bar count exceeds the region (mirrors
    .barriers / .btrack / .bfill / .chart-note)."""
    spec = _spec_of(slide, deck, n)
    slide_obj = _new_slide(pres, spec)
    _header(slide_obj, spec)
    bars = slide["bars"]
    note = slide.get("note") or ""
    note_h = 5 + 18 if note else 0
    label_h, track_h, inner_gap, group_gap = 20, 13, 6, 10
    group_h = label_h + inner_gap + track_h
    total = len(bars) * group_h + (len(bars) - 1) * group_gap
    avail = BARS_BOTTOM - BARS_TOP - note_h
    scale = min(1.0, avail / total) if total else 1.0
    label_h, track_h = label_h * scale, track_h * scale
    inner_gap, group_gap = inner_gap * scale, group_gap * scale
    group_h = label_h + inner_gap + track_h
    total = len(bars) * group_h + (len(bars) - 1) * group_gap
    y = BARS_TOP + (BARS_BOTTOM - BARS_TOP - note_h - total) / 2
    val_w = 56                   # 4.4cqw value column
    track_w = CONTENT_W - val_w - 13
    top_value = max((b["value"] for b in bars), default=0)
    for j, bar in enumerate(bars):
        first, last = j == 0, j == len(bars) - 1
        if first and not last:      # .brow.top: bold label, accent fill
            fill, label_color, label_bold = "accent", "ink", True
        elif last and not first:    # .brow.last: secondary-tint fill
            fill, label_color, label_bold = "secondary_tint4", "body", False
        else:
            fill, label_color, label_bold = "accent_tint3", "body", False
        slide_obj.text_box(MARGIN_X, y, CONTENT_W, label_h,
                           [{"text": bar["label"], "size": 10, "bold": label_bold,
                             "color": label_color}],
                           autofit=True, name=f"Bar label {j + 1}")
        slide_obj.line(MARGIN_X, y + label_h + inner_gap + track_h / 2,
                       MARGIN_X + track_w, y + label_h + inner_gap + track_h / 2,
                       color="fill", width_pt=max(track_h * 0.75, 0.75),
                       name=f"Bar track {j + 1}")
        width = track_w * bar["value"] / top_value if top_value > 0 else 0.0
        slide_obj.rect(MARGIN_X, y + label_h + inner_gap, max(width, 1.0), track_h,
                       fill=fill, radius=3, name=f"Bar {j + 1} fill")
        slide_obj.text_box(MARGIN_X + track_w + 13, y + label_h + inner_gap - 4,
                           val_w, 20,
                           [{"text": bar["display"], "size": 10.5, "bold": True,
                             "color": "ink"}],
                           align="right", name=f"Bar value {j + 1}")
        y += group_h + group_gap
    if note:
        slide_obj.text_box(MARGIN_X, y + 5, CONTENT_W, 18,
                           [{"text": note, "size": 9.5, "color": "muted"}],
                           name="Bars note")
    _footer(slide_obj, spec, deck_title, theme)


def _quote_pptx_slide(pres, slide, deck, deck_title, theme, n):
    """Large quotation with attribution (mirrors .quote-text with its
    accent quotation marks and .quote-attr)."""
    spec = _spec_of(slide, deck, n)
    slide_obj = _new_slide(pres, spec)
    if slide.get("title"):
        _header(slide_obj, spec)
    else:
        _eyebrow_head(slide_obj, spec["eyebrow"])
    runs = [{"text": "\u201c", "size": 17, "bold": True, "color": "accent"},
            {"text": slide["quote"], "size": 17, "color": "ink"},
            {"text": "\u201d", "size": 17, "bold": True, "color": "accent"}]
    paras = [{"runs": runs, "line_spacing": 1.4}]
    if slide.get("attribution"):
        paras.append({"text": slide["attribution"].upper(), "size": 9.5,
                      "bold": True, "color": "muted", "space_before": 18})
    slide_obj.text_box(MARGIN_X, 150, CONTENT_W, 460, paras,
                       anchor="ctr", autofit=True, name="Quote")
    _footer(slide_obj, spec, deck_title, theme)


def _closing_pptx_slide(pres, slide, deck, deck_title, theme, n):
    """Headline plus numbered next steps, each step over a hairline rule,
    the whole block one centered group (mirrors .layout-closing / .steps /
    .step / .step-n)."""
    spec = _spec_of(slide, deck, n)
    slide_obj = _new_slide(pres, spec)
    _eyebrow_head(slide_obj, spec["eyebrow"])
    steps = slide["steps"]
    text_w = CONTENT_W - 46
    head_h = max(_est_lines(slide["headline"], CONTENT_W, 26, bold=True)
                 * 26 * 1.12, 30)
    step_hs = [8 + max(_est_lines(step, text_w, 12) * 12 * 1.45, 17) + 8
               for step in steps]
    total = head_h + 20 + sum(step_hs)
    top = max(140, 140 + (480 - total) / 2)
    slide_obj.text_box(MARGIN_X, top, CONTENT_W, head_h,
                       [{"text": slide["headline"], "size": 26, "bold": True,
                         "color": "ink", "line_spacing": 1.12}],
                       autofit=True, name="Closing headline")
    sy = top + head_h + 20
    for j, (step, step_h) in enumerate(zip(steps, step_hs)):
        slide_obj.line(MARGIN_X, sy, SLIDE_W - MARGIN_X, sy,
                       color="line", width_pt=1.0, name=f"Closing step rule {j + 1}")
        slide_obj.text_box(MARGIN_X, sy + 8, 36, 17,
                           [{"text": f"{j + 1:02d}", "size": 10, "bold": True,
                             "color": "accent"}],
                           name=f"Closing step number {j + 1}")
        slide_obj.text_box(MARGIN_X + 46, sy + 7, text_w, step_h - 14,
                           [{"text": step, "size": 12, "color": "body",
                             "line_spacing": 1.45}],
                           autofit=True, name=f"Closing step {j + 1}")
        sy += step_h
    _footer(slide_obj, spec, deck_title, theme)


_SLIDE_LIST_RENDERERS = {
    "cover": _deck_cover_slide,
    "section": _section_pptx_slide,
    "agenda": _agenda_pptx_slide,
    "statement": _deck_statement_slide,
    "bullets": _deck_bullets_slide,
    "two_column": _two_column_pptx_slide,
    "three_values": _three_values_pptx_slide,
    "compare": _compare_pptx_slide,
    "bars": _bars_pptx_slide,
    "facet": _deck_facet_slide,
    "quote": _quote_pptx_slide,
    "sources": _deck_sources_slide,
    "closing": _closing_pptx_slide,
}


def build_presentation_from_deck(deck, theme="neutral"):
    """Compose the .pptx from a validated slide-list deck dict (one slide
    per authored slide, in list order; the cover is slide 1)."""
    theme_obj = theme if isinstance(theme, dict) else load_theme(theme)
    deck_title = deck["title"]
    pres = Presentation(theme_obj, title=deck_title, creator="render_pptx")
    for n, slide in enumerate(deck["slides"], start=1):
        _SLIDE_LIST_RENDERERS[slide["layout"]](pres, slide, deck, deck_title, theme_obj, n)
    return pres


def render_pptx_slides(deck, out_path, theme="neutral"):
    """Validate a slide-list deck dict, render it, and write the .pptx."""
    validate_deck(deck)
    pres = build_presentation_from_deck(deck, theme)
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
        description="Render a native editable PowerPoint deck from a render model (E4-R3) "
                    "or an authored slide list (E5-R3)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 render_pptx.py --model render_model.json --out deck.pptx
  python3 render_pptx.py --report report.md --manifest run_manifest.json --out deck.pptx
  python3 render_pptx.py --report report.md --theme tests/fixtures/themes/alt --out deck.pptx
  python3 render_pptx.py --slides deck.json --out deck.pptx
        """,
    )
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--model", help="render model JSON (from build_render_model.py)")
    src.add_argument("--report", "-r", help="report markdown; the model is built in-process")
    src.add_argument("--slides", help="deck slide-list JSON (schemas/deck_spec.schema.json)")
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
    elif args.slides:
        if args.manifest or args.format:
            ap.error("--manifest/--format apply to --report, not --slides")
        try:
            deck = load_deck(args.slides)
        except DeckError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)
        out = render_pptx_slides(deck, args.out, theme=args.theme)
        print(f"wrote {out}")
        return
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
