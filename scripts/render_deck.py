#!/usr/bin/env python3
"""
Deck renderer: turns a render model (build_render_model.py JSON) into a
self-contained themed motion deck per E3-R1, and any authored slide list
(schemas/deck_spec.schema.json) into the same per E5-R2.

The content plan — slide selection and order, condensing, the 12-content-
slide cap, speaker notes — comes from slide_plan.plan_slides (E4-R1); this
module lays each planned spec out as themed HTML through render_lib. The
sequence and note rules are documented in slide_plan.py. Slide-list decks
(E5-R1) are authored per layout (deck_spec.py validates them); the five
kinds the plan emits reuse the same body builders, so exporting a plan
(deck_spec.py --report) and rendering it reproduces the planned deck
byte for byte.

    python3 render_deck.py --model render_model.json [--theme neutral] --out deck.html
    python3 render_deck.py --report report.md [--manifest run_manifest.json] \
        [--format comprehensive-report] [--theme neutral] --out deck.html
    python3 render_deck.py --slides deck.json [--theme neutral] --out deck.html
"""
import argparse
import json
import os
import sys
from pathlib import Path

from build_render_model import build_model
from deck_spec import DeckError, load_deck
from render_lib import deck, cover_slide, slide_head, slide_foot, esc
from slide_plan import CONTENT_SLIDE_CAP, FORMAT_DISPLAY, plan_slides, stat_parts

EMPTY_MAIN_FALLBACK = '<p class="fine">Detailed in the full report.</p>'

# CSS for the layouts that predate the slide-list format (divider, two titled
# panels, quote, closing); injected only on the --slides path so the
# --report/--model decks keep byte-identical output (E5-R2).
_LAYOUTS_CSS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "..", "assets", "render", "deck_layouts.css")


def _bullets_html(points, start_delay=2):
    items = "".join(
        f'<li data-a style="--d:{j + start_delay}">{esc(p)}</li>'
        for j, p in enumerate(points))
    return f'<ul class="ticks">{items}</ul>' if items else ""


def _evidence_html(refs):
    if not refs:
        return ""
    return ('<p class="fine" data-a style="--d:5">Evidence: '
            + " ".join(f"[{r}]" for r in refs) + "</p>")


def _statement_body(spec, deck_name, theme):
    tiles = []
    for i, stat in enumerate(spec["stats"]):
        num, suffix = stat["parts"]
        small = f"<small>{esc(suffix)}</small>" if suffix else ""
        label = esc(stat["label"])
        if stat.get("ref") is not None:
            label += f" [{stat['ref']}]"
        tiles.append(
            f'<article class="stat-tile" data-a style="--d:{i + 2}">'
            f'<p class="stat-num">{esc(num)}{small}</p>'
            f'<p class="stat-txt">{label}</p></article>')
    tiles_html = f'<div class="stat-tiles">{"".join(tiles)}</div>' if tiles else ""
    return ('<div class="slide-body">'
            '<header class="slide-head"><p class="eyebrow" data-a style="--d:0">'
            + esc(spec["eyebrow"]) + '</p></header>'
            f'<main class="slide-main"><h2 class="statement-title" data-a style="--d:1">{esc(spec["title"])}</h2>'
            f'{tiles_html}</main>'
            + slide_foot(deck_name, spec["section"], spec["number"], theme=theme)
            + '</div>')


def _bulleted_body(spec, deck_name, theme, refs=()):
    """Finding / section / facet-fallback layout: bullet points, then the
    evidence line, then the fallback note."""
    bullets = _bullets_html([b["text"] for b in spec.get("bullets") or []])
    main = bullets or _evidence_html(refs) or EMPTY_MAIN_FALLBACK
    return ('<div class="slide-body">'
            + slide_head(spec["eyebrow"], spec["title"], theme=theme)
            + f'<main class="slide-main">{main}</main>'
            + slide_foot(deck_name, spec["section"], spec["number"], theme=theme)
            + '</div>')


def _facet_body(spec, deck_name, theme):
    sides = spec.get("sides") or []
    if sides:
        cols = min(max(len(sides), 2), 4)
        side_html = "".join(
            f'<article class="facet-side" data-a style="--d:{j + 2}">'
            f'<h3>{esc(side["label"])}</h3>'
            f'<p>{esc(side["summary"])}</p></article>'
            for j, side in enumerate(sides))
        main = f'<div class="facet-grid cols-{cols}">{side_html}</div>'
    else:
        main = (_bullets_html([b["text"] for b in spec.get("bullets") or []])
                or EMPTY_MAIN_FALLBACK)
    return ('<div class="slide-body">'
            + slide_head(spec["eyebrow"], spec["title"], theme=theme)
            + f'<main class="slide-main">{main}</main>'
            + slide_foot(deck_name, spec["section"], spec["number"], theme=theme)
            + '</div>')


def _sources_body(spec, deck_name, theme):
    rows = []
    for i, src in enumerate(spec["sources"]):
        dd = f" — {esc(src['publisher'])}" if src["publisher"] else ""
        rows.append(f'<div class="fact" data-a style="--d:{min(i, 6)}">'
                    f'<dt>[{src["n"]}] {esc(src["title"])}</dt><dd>{dd}</dd></div>')
    more = spec["more_sources"]
    more_html = (f'<p class="fine" data-a style="--d:7">+{more} more in the full report</p>'
                 if more > 0 else "")
    main = (f'<dl class="facts">{"".join(rows)}</dl>{more_html}' if rows
            else '<p class="fine">No sources listed in the render model.</p>')
    return ('<div class="slide-body">'
            + slide_head(spec["eyebrow"], spec["title"], theme=theme)
            + f'<main class="slide-main">{main}</main>'
            + slide_foot(deck_name, spec["section"], spec["number"], theme=theme)
            + '</div>')


def _slide_body(spec, deck_name, theme):
    kind = spec["kind"]
    if kind == "statement":
        return _statement_body(spec, deck_name, theme)
    if kind == "facet":
        return _facet_body(spec, deck_name, theme)
    if kind == "sources":
        return _sources_body(spec, deck_name, theme)
    if kind == "finding":
        bullets = spec.get("bullets") or []
        return _bulleted_body(spec, deck_name, theme,
                              refs=bullets[0]["refs"] if bullets else [])
    return _bulleted_body(spec, deck_name, theme)


def _section_cls(spec):
    if spec["kind"] == "sources":
        return "slide sources" + (" dense" if len(spec["sources"]) > 6 else "")
    return "slide"


def render_deck(model, theme="neutral"):
    """Compose the themed motion deck from a render model's slide plan."""
    specs = plan_slides(model)
    cover = specs[0]
    sections_html = [cover_slide(
        eyebrow=cover["eyebrow"],
        title=cover["title"],
        sub=cover["subtitle"],
        meta=cover["date"] or "",
        foot_note="",
        seed=5,
        notes=cover["notes"],
        theme=theme,
    )]
    for spec in specs[1:]:
        sections_html.append(
            f'<section class="{_section_cls(spec)}" '
            f'data-notes="{esc(spec["notes"])}">'
            + _slide_body(spec, cover["title"], theme) + '</section>')
    return deck(cover["title"], sections_html, theme=theme)


# ---------- slide-list decks (E5-R1/E5-R2) ----------
def _eyebrow_of(slide, section):
    return slide.get("eyebrow") or section


def _section_of(slide, deck, layout):
    return (slide.get("section") or deck.get("footer_section")
            or layout.replace("_", " ").title())


def _eyebrow_head(eyebrow):
    """Header carrying only the eyebrow (statement-style), for quote/closing."""
    return ('<header class="slide-head"><p class="eyebrow" data-a style="--d:0">'
            + esc(eyebrow) + '</p></header>')


def _divider_body(slide, eyebrow, section, deck_name, n, theme):
    sub = (f'<p class="sub" data-a style="--d:2">{esc(slide["sub"])}</p>'
           if slide.get("sub") else "")
    main = (f'<h2 class="divider-title" data-a style="--d:1">{esc(slide["title"])}</h2>{sub}'
            '<span class="kbar" data-a="grow-x" style="--d:3"></span>')
    return ('<div class="slide-body">' + _eyebrow_head(eyebrow)
            + f'<main class="slide-main">{main}</main>'
            + slide_foot(deck_name, section, n, theme=theme) + '</div>')


def _agenda_body(slide, eyebrow, section, deck_name, n, theme):
    rows = "".join(
        f'<li class="agenda-row" data-a style="--d:{j + 2}">'
        f'<span class="agenda-num">{j + 1:02d}</span>'
        f'<span class="agenda-title">{esc(item["title"])}</span>'
        f'<span class="agenda-desc">{esc(item.get("desc") or "")}</span></li>'
        for j, item in enumerate(slide["items"]))
    main = f'<ol class="agenda-list">{rows}</ol>'
    return ('<div class="slide-body">'
            + slide_head(eyebrow, slide["title"], theme=theme)
            + f'<main class="slide-main">{main}</main>'
            + slide_foot(deck_name, section, n, theme=theme) + '</div>')


def _two_column_body(slide, eyebrow, section, deck_name, n, theme):
    def panel(panel_dict, tint, delay):
        if panel_dict.get("body") is not None:
            content = f'<p class="col-body">{esc(panel_dict["body"])}</p>'
        else:
            content = _bullets_html([b["text"] for b in panel_dict.get("bullets") or []],
                                    start_delay=delay + 1)
        return (f'<article class="col-panel{" tint" if tint else ""}" data-a style="--d:{delay}">'
                f'<h3>{esc(panel_dict["title"])}</h3>{content}</article>')

    main = ('<div class="two-col-panels">'
            + panel(slide["left"], False, 2) + panel(slide["right"], True, 3)
            + '</div>')
    return ('<div class="slide-body">'
            + slide_head(eyebrow, slide["title"], theme=theme)
            + f'<main class="slide-main">{main}</main>'
            + slide_foot(deck_name, section, n, theme=theme) + '</div>')


def _three_values_body(slide, eyebrow, section, deck_name, n, theme):
    cols = "".join(
        f'<article class="value-col" data-a style="--d:{j + 2}"><span class="value-line"></span>'
        f'<span class="value-num">{j + 1:02d}</span><h3>{esc(v["title"])}</h3>'
        f'<p>{esc(v["body"])}</p></article>'
        for j, v in enumerate(slide["values"]))
    note = f'<p class="fine">{esc(slide["note"])}</p>' if slide.get("note") else ""
    main = f'<div class="value-grid">{cols}</div>{note}'
    return ('<div class="slide-body">'
            + slide_head(eyebrow, slide["title"], theme=theme)
            + f'<main class="slide-main">{main}</main>'
            + slide_foot(deck_name, section, n, theme=theme) + '</div>')


_COMPARE_ARROW = ('<div class="compare-arrow" data-a="pop" style="--d:4" aria-hidden="true">'
                  '<svg viewBox="0 0 24 24"><path d="M5 12h14M13 6l6 6-6 6" fill="none" '
                  'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg></div>')


def _compare_body(slide, eyebrow, section, deck_name, n, theme):
    default_tags = ("Option A", "Option B")

    def card(option, kind, delay, default_tag):
        rows = "".join(f'<li>{esc(row)}</li>' for row in option["rows"])
        kicker = f'<p class="kicker">{esc(option["kicker"])}</p>' if option.get("kicker") else ""
        marks = "x" if kind == "problem" else "check"
        return (f'<article class="compare-card {kind}" data-a style="--d:{delay}">'
                f'<p class="tag">{esc(option.get("tag") or default_tag)}</p>'
                f'<h3>{esc(option["name"])}</h3>'
                f'<ul class="marks {marks}">{rows}</ul>{kicker}</article>')

    main = (card(slide["options"][0], "problem", 2, default_tags[0]) + _COMPARE_ARROW
            + card(slide["options"][1], "solution", 5, default_tags[1]))
    return ('<div class="slide-body">'
            + slide_head(eyebrow, slide["title"], theme=theme)
            + f'<main class="slide-main">{main}</main>'
            + slide_foot(deck_name, section, n, theme=theme) + '</div>')


def _bars_body(slide, eyebrow, section, deck_name, n, theme):
    bars = slide["bars"]
    top = max((b["value"] for b in bars), default=0)
    rows = []
    for j, bar in enumerate(bars):
        width = bar["value"] / top * 100 if top > 0 else 0.0
        cls = " brow"
        if j == 0 and len(bars) > 1:
            cls = " brow top"
        elif j == len(bars) - 1 and len(bars) > 1:
            cls = " brow last"
        rows.append(f'<div class="{cls.strip()}"><span class="bname">{esc(bar["label"])}</span>'
                    f'<span class="btrack"><span class="bfill" style="--w:{width:.0f}%;--d:{j}">'
                    f'</span></span><span class="bval">{esc(bar["display"])}</span></div>')
    note = f'<p class="chart-note">{esc(slide["note"])}</p>' if slide.get("note") else ""
    main = f'<div class="barriers">{"".join(rows)}{note}</div>'
    return ('<div class="slide-body">'
            + slide_head(eyebrow, slide["title"], theme=theme)
            + f'<main class="slide-main">{main}</main>'
            + slide_foot(deck_name, section, n, theme=theme) + '</div>')


def _quote_body(slide, eyebrow, section, deck_name, n, theme):
    attribution = (f'<p class="quote-attr" data-a style="--d:2">{esc(slide["attribution"])}</p>'
                   if slide.get("attribution") else "")
    main = f'<p class="quote-text" data-a style="--d:1">{esc(slide["quote"])}</p>{attribution}'
    head = (slide_head(eyebrow, slide["title"], theme=theme) if slide.get("title")
            else _eyebrow_head(eyebrow))
    return ('<div class="slide-body">' + head
            + f'<main class="slide-main">{main}</main>'
            + slide_foot(deck_name, section, n, theme=theme) + '</div>')


def _closing_body(slide, eyebrow, section, deck_name, n, theme):
    steps = "".join(
        f'<li class="step" data-a style="--d:{j + 2}"><span class="step-n">{j + 1:02d}</span>'
        f'<span>{esc(step)}</span></li>'
        for j, step in enumerate(slide["steps"]))
    main = (f'<h2 class="closing-title" data-a style="--d:1">{esc(slide["headline"])}</h2>'
            f'<ol class="steps">{steps}</ol>')
    return ('<div class="slide-body">' + _eyebrow_head(eyebrow)
            + f'<main class="slide-main">{main}</main>'
            + slide_foot(deck_name, section, n, theme=theme) + '</div>')


def _slide_list_body(slide, deck, deck_name, n, theme):
    """(section classes, slide-body HTML) for one authored slide, numbered n.

    The five layouts the research plan emits reuse the plan's body builders
    so an exported plan renders exactly like the --report/--model path.
    """
    layout = slide["layout"]
    section = _section_of(slide, deck, layout)
    eyebrow = _eyebrow_of(slide, section)
    if layout == "statement":
        spec = {"eyebrow": eyebrow, "title": slide["headline"], "section": section,
                "number": n,
                "stats": [{"value": s["value"], "label": s["label"],
                           "ref": s.get("ref"), "parts": list(stat_parts(s["value"]))}
                          for s in slide.get("stats") or []]}
        return "slide", _statement_body(spec, deck_name, theme)
    if layout == "bullets":
        bullets = slide.get("bullets") or []
        refs = bullets[0].get("refs") or [] if bullets else (slide.get("refs") or [])
        spec = {"eyebrow": eyebrow, "title": slide["title"], "section": section,
                "number": n, "bullets": bullets}
        return "slide", _bulleted_body(spec, deck_name, theme, refs=refs)
    if layout == "facet":
        spec = {"eyebrow": eyebrow, "title": slide["title"], "section": section,
                "number": n, "sides": slide.get("sides") or [],
                "bullets": slide.get("bullets") or []}
        return "slide", _facet_body(spec, deck_name, theme)
    if layout == "sources":
        sources = [{"n": s["n"], "title": s["title"],
                    "publisher": s.get("publisher") or "", "url": s.get("url")}
                   for s in slide["sources"]]
        spec = {"kind": "sources", "eyebrow": eyebrow, "title": slide["title"],
                "section": section, "number": n, "sources": sources,
                "more_sources": slide.get("more_sources") or 0}
        return _section_cls(spec), _sources_body(spec, deck_name, theme)
    body = {"section": _divider_body, "agenda": _agenda_body,
            "two_column": _two_column_body, "three_values": _three_values_body,
            "compare": _compare_body, "bars": _bars_body,
            "quote": _quote_body, "closing": _closing_body}[layout]
    return f"slide layout-{layout}", body(slide, eyebrow, section, deck_name, n, theme)


# Layouts whose CSS ships in deck_layouts.css instead of deck.css/research.css
NEW_LAYOUTS = ("section", "two_column", "quote", "closing")


def render_slides(deck_spec, theme="neutral"):
    """Compose the themed motion deck from a validated slide-list deck dict."""
    extra_css = ""
    if any(s["layout"] in NEW_LAYOUTS for s in deck_spec["slides"]):
        with open(_LAYOUTS_CSS_PATH, encoding="utf-8") as f:
            extra_css = f.read()
    sections_html = []
    for n, slide in enumerate(deck_spec["slides"], start=1):
        notes = slide.get("notes") or ""
        if slide["layout"] == "cover":
            sub = slide["subtitle"] if slide.get("subtitle") is not None \
                else (deck_spec.get("subtitle") or "")
            meta = slide["date"] if slide.get("date") is not None \
                else (deck_spec.get("date") or "")
            sections_html.append(cover_slide(
                eyebrow=slide.get("eyebrow") or deck_spec.get("eyebrow") or "",
                title=slide["title"],
                sub=sub,
                meta=meta,
                foot_note="",
                seed=5,
                notes=notes,
                theme=theme))
        else:
            cls, body = _slide_list_body(slide, deck_spec, deck_spec["title"], n, theme)
            sections_html.append(
                f'<section class="{cls}" data-notes="{esc(notes)}">{body}</section>')
    return deck(deck_spec["title"], sections_html, extra_css=extra_css, theme=theme)


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
        description="Render a themed HTML slide deck from a render model (E3-R1) "
                    "or an authored slide list (E5-R2)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 render_deck.py --model render_model.json --out deck.html
  python3 render_deck.py --report report.md --manifest run_manifest.json --out deck.html
  python3 render_deck.py --report report.md --theme tests/fixtures/themes/alt --out deck.html
  python3 render_deck.py --slides deck.json --out deck.html
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
    ap.add_argument("--out", "-o", required=True, help="write the HTML deck here")
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
            spec = load_deck(args.slides)
        except DeckError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)
        html = render_slides(spec, theme=args.theme)
        out = Path(args.out)
        if out.parent and not out.parent.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")
        print(f"wrote {out}")
        return
    else:
        report_path = Path(args.report)
        if not report_path.exists():
            print(f"ERROR: report not found: {report_path}", file=sys.stderr)
            sys.exit(1)
        manifest = _load_json(args.manifest) if args.manifest else None
        model = build_model(report_path.read_text(encoding="utf-8"), manifest, args.format)

    html = render_deck(model, theme=args.theme)
    out = Path(args.out)
    if out.parent and not out.parent.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
