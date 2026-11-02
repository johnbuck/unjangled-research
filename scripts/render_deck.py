#!/usr/bin/env python3
"""
Deck renderer: turns a render model (build_render_model.py JSON) into a
self-contained themed motion deck per E3-R1.

The content plan — slide selection and order, condensing, the 12-content-
slide cap, speaker notes — comes from slide_plan.plan_slides (E4-R1); this
module lays each planned spec out as themed HTML through render_lib. The
sequence and note rules are documented in slide_plan.py.

    python3 render_deck.py --model render_model.json [--theme neutral] --out deck.html
    python3 render_deck.py --report report.md [--manifest run_manifest.json] \
        [--format comprehensive-report] [--theme neutral] --out deck.html
"""
import argparse
import json
import sys
from pathlib import Path

from build_render_model import build_model
from render_lib import deck, cover_slide, slide_head, slide_foot, esc
from slide_plan import CONTENT_SLIDE_CAP, FORMAT_DISPLAY, plan_slides

EMPTY_MAIN_FALLBACK = '<p class="fine">Detailed in the full report.</p>'


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
        description="Render a themed HTML slide deck from a render model (E3-R1)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 render_deck.py --model render_model.json --out deck.html
  python3 render_deck.py --report report.md --manifest run_manifest.json --out deck.html
  python3 render_deck.py --report report.md --theme tests/fixtures/themes/alt --out deck.html
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
