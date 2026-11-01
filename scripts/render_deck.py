#!/usr/bin/env python3
"""
Deck renderer: turns a render model (build_render_model.py JSON) into a
self-contained themed motion deck per E3-R1.

Slide sequence: cover (title, subtitle or the summary's first sentence,
date, the format's display name as eyebrow, theme motif); a statement
slide with the summary's first sentence as the headline and up to three
stat tiles; one slide per finding (falling back to one slide per top-level
section when the model has no findings); one slide per contested facet
with one column per side; a sources slide. Content slides (statement +
findings/sections + facets) are capped at 12 — when the cap bites, the
last kept slide's notes say how many were omitted. Every slide carries
data-notes speaker notes with the fuller text it condenses. Nothing is
invented: every number and claim comes from the model.

    python3 render_deck.py --model render_model.json [--theme neutral] --out deck.html
    python3 render_deck.py --report report.md [--manifest run_manifest.json] \
        [--format comprehensive-report] [--theme neutral] --out deck.html
"""
import argparse
import json
import re
import sys
from html import unescape
from pathlib import Path

from build_render_model import build_model, sentences
from render_lib import deck, cover_slide, slide_head, slide_foot, esc

FORMAT_DISPLAY = {
    "comprehensive-report": "Comprehensive Report",
    "research-summary": "Research Summary",
    "comparison": "Comparison",
    "quick-brief": "Quick Brief",
    "discovery-catalog": "Discovery Catalog",
}

TITLE_MAX = 90          # slide titles stay short enough for 1280x720
BULLET_MAX = 160        # so do bullet points
COVER_SUB_MAX = 140
COVER_TITLE_MAX = 120
STATEMENT_WORDS = 20    # statement headline: one trimmed sentence
STAT_TILE_MAX = 3
CONTENT_SLIDE_CAP = 12  # statement + findings/sections + facets
SOURCE_SLIDE_MAX = 12
NOTE_MAX = 600          # speaker notes carry fuller text, clipped hard
EMPTY_MAIN_FALLBACK = '<p class="fine">Detailed in the full report.</p>'

_HEADING_RE = re.compile(r"<h[23]\b[^>]*>.*?</h[23]>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
# a stat value's leading token when the value splits as "<num> <unit>"
_NUM_TOKEN_RE = re.compile(r"^[$€£¥]?\d[\d.,]*(?:[–—-]\d[\d.,]*)?[%×xX]?$")


def clip(text, limit):
    """Trim to limit characters at a word boundary with an ellipsis."""
    text = _WS_RE.sub(" ", str(text or "")).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:.-–—")
    return cut + "…"


def clip_words(text, n):
    """First n words of text — the statement headline trim."""
    return " ".join(_WS_RE.sub(" ", str(text or "")).split()[:n])


def html_text(fragment):
    """Plain text from a section's HTML: drop the h2/h3 headings, then tags."""
    text = _HEADING_RE.sub(" ", fragment or "")
    text = _TAG_RE.sub(" ", text)
    return _WS_RE.sub(" ", unescape(text)).strip()


def stat_parts(value):
    """('48,000', 'stars') for '48,000 stars'; (value, '') when it does not
    split as a numeric head plus unit — num + ' ' + suffix always rebuilds
    the model's verbatim value."""
    value = _WS_RE.sub(" ", str(value or "")).strip()
    head, sep, tail = value.partition(" ")
    if sep and tail and _NUM_TOKEN_RE.match(head):
        return head, tail
    return value, ""


def first_sentence(paragraphs):
    for para in paragraphs or []:
        parts = sentences(str(para))
        if parts:
            return parts[0]
    return ""


def _notes_join(*parts):
    return "|".join(p for p in parts if p)


def _statement_slide(model, title, theme):
    """Headline sentence plus up to three stat tiles; None when there is
    neither an executive summary nor key stats."""
    paragraphs = [_WS_RE.sub(" ", str(p)).strip()
                  for p in (model.get("executive_summary") or []) if str(p).strip()]
    stats = [s for s in (model.get("key_stats") or []) if s][:STAT_TILE_MAX]
    if not paragraphs and not stats:
        return None
    headline = clip_words(first_sentence(paragraphs), STATEMENT_WORDS) or clip(title, TITLE_MAX)
    tiles = []
    for i, stat in enumerate(stats):
        num, suffix = stat_parts(stat.get("value"))
        small = f"<small>{esc(suffix)}</small>" if suffix else ""
        label = esc(clip(stat.get("label") or "", 90))
        if stat.get("ref") is not None:
            label += f" [{int(stat['ref'])}]"
        tiles.append(
            f'<article class="stat-tile" data-a style="--d:{i + 2}">'
            f'<p class="stat-num">{esc(num)}{small}</p>'
            f'<p class="stat-txt">{label}</p></article>')
    tiles_html = f'<div class="stat-tiles">{"".join(tiles)}</div>' if tiles else ""
    notes = _notes_join(*(clip(p, NOTE_MAX) for p in paragraphs)) or clip(title, NOTE_MAX)

    def body(n):
        return ('<div class="slide-body">'
                '<header class="slide-head"><p class="eyebrow" data-a style="--d:0">Statement</p></header>'
                f'<main class="slide-main"><h2 class="statement-title" data-a style="--d:1">{esc(headline)}</h2>'
                f'{tiles_html}</main>'
                + slide_foot(title, "Statement", n, theme=theme) + '</div>')
    return {"cls": "slide", "notes": notes, "body": body}


def _bullets_html(points, start_delay=2):
    items = "".join(
        f'<li data-a style="--d:{j + start_delay}">{esc(p)}</li>'
        for j, p in enumerate(points))
    return f'<ul class="ticks">{items}</ul>' if items else ""


def _finding_slide(idx, finding, title, theme):
    headline = clip(finding.get("headline") or "", TITLE_MAX) or f"Finding {idx:02d}"
    body_text = _WS_RE.sub(" ", str(finding.get("body") or "")).strip()
    points = [clip(s, BULLET_MAX) for s in sentences(body_text)][:3]
    bullets = _bullets_html(points)
    refs = [int(r) for r in (finding.get("refs") or []) if r is not None]
    refs_html = ""
    if refs:
        refs_html = (f'<p class="fine" data-a style="--d:5">Evidence: '
                     + " ".join(f"[{r}]" for r in refs) + "</p>")
    notes = _notes_join(headline, clip(body_text, NOTE_MAX),
                        ("Refs: " + " ".join(f"[{r}]" for r in refs)) if refs else "")

    def body(n):
        return ('<div class="slide-body">'
                + slide_head(f"Finding {idx:02d}", headline, theme=theme)
                + f'<main class="slide-main">{bullets or refs_html or EMPTY_MAIN_FALLBACK}</main>'
                + slide_foot(title, "Findings", n, theme=theme) + '</div>')
    return {"cls": "slide", "notes": notes, "body": body}


def _section_slide(idx, section, title, theme):
    """Top-level-section fallback slide: its first three sentences as bullets."""
    heading = clip(section.get("heading") or "", TITLE_MAX) or f"Section {idx:02d}"
    text = html_text(section.get("html") or "")
    points = [clip(s, BULLET_MAX) for s in sentences(text)][:3]
    bullets = _bullets_html(points)
    notes = clip(text, NOTE_MAX) or heading

    def body(n):
        return ('<div class="slide-body">'
                + slide_head(f"Section {idx:02d}", heading, theme=theme)
                + f'<main class="slide-main">{bullets or EMPTY_MAIN_FALLBACK}</main>'
                + slide_foot(title, "Sections", n, theme=theme) + '</div>')
    return {"cls": "slide", "notes": notes, "body": body}


def _facet_slide(idx, facet, title, theme):
    facet_title = clip(facet.get("facet") or "", TITLE_MAX) or f"Contested facet {idx:02d}"
    sides = [s for s in (facet.get("sides") or []) if s]
    sub_text = html_text(facet.get("html") or "")
    if sides:
        cols = min(max(len(sides), 2), 4)
        side_html = "".join(
            f'<article class="facet-side" data-a style="--d:{j + 2}">'
            f'<h3>{esc(clip(side.get("label") or f"Side {j + 1}", 40))}</h3>'
            f'<p>{esc(clip(side.get("summary") or "", 200))}</p></article>'
            for j, side in enumerate(sides))
        main_html = f'<div class="facet-grid cols-{cols}">{side_html}</div>'
    else:
        # no extracted sides: condense the matched subsection's text, the
        # same trim the section fallback uses
        points = [clip(s, BULLET_MAX) for s in sentences(sub_text)][:3]
        main_html = _bullets_html(points) or EMPTY_MAIN_FALLBACK
    # notes carry the full subsection text the slide condenses
    notes = _notes_join(facet_title, *(
        f"{clip(side.get('label') or '', 40)}: {clip(side.get('summary') or '', NOTE_MAX)}"
        for side in sides), clip(sub_text, NOTE_MAX))

    def body(n):
        return ('<div class="slide-body">'
                + slide_head("Contested facet", facet_title, theme=theme)
                + f'<main class="slide-main">{main_html}</main>'
                + slide_foot(title, "Perspectives", n, theme=theme) + '</div>')
    return {"cls": "slide", "notes": notes, "body": body}


def _sources_slide(model, title, theme):
    sources = [s for s in (model.get("sources") or []) if s]
    shown = sources[:SOURCE_SLIDE_MAX]
    rows = []
    for i, src in enumerate(shown):
        n = int(src.get("n") or (i + 1))
        text = clip(src.get("title") or src.get("url") or f"Source {n}", 70)
        publisher = src.get("publisher")
        dd = f" — {esc(clip(publisher, 60))}" if publisher else ""
        rows.append(f'<div class="fact" data-a style="--d:{min(i, 6)}">'
                    f'<dt>[{n}] {esc(text)}</dt><dd>{dd}</dd></div>')
    more = len(sources) - len(shown)
    more_html = (f'<p class="fine" data-a style="--d:7">+{more} more in the full report</p>'
                 if more > 0 else "")
    main_html = (f'<dl class="facts">{"".join(rows)}</dl>{more_html}' if rows
                 else '<p class="fine">No sources listed in the render model.</p>')
    notes = (f"{len(sources)} sources in the full report"
             + (f"; {more} beyond the {SOURCE_SLIDE_MAX} shown" if more > 0 else ""))

    def body(n):
        return ('<div class="slide-body">'
                + slide_head("Sources", f"{len(sources)} sources", theme=theme)
                + f'<main class="slide-main">{main_html}</main>'
                + slide_foot(title, "Sources", n, theme=theme) + '</div>')
    cls = "slide sources" + (" dense" if len(shown) > 6 else "")
    return {"cls": cls, "notes": notes, "body": body}


def render_deck(model, theme="neutral"):
    """Compose the themed motion deck from a render model dict."""
    title = clip(model.get("title") or "Untitled report", COVER_TITLE_MAX)
    fmt = model.get("format") or "comprehensive-report"
    display = FORMAT_DISPLAY.get(fmt, str(fmt).replace("-", " ").title())
    date = model.get("date")
    paragraphs = [_WS_RE.sub(" ", str(p)).strip()
                  for p in (model.get("executive_summary") or []) if str(p).strip()]

    cover_notes = _notes_join(title, f"{display} deck", date,
                              clip(paragraphs[0], NOTE_MAX) if paragraphs else "")
    cover = cover_slide(
        eyebrow=display,
        title=title,
        sub=clip(model.get("subtitle") or first_sentence(paragraphs), COVER_SUB_MAX),
        meta=date or "",
        foot_note="",
        seed=5,
        notes=cover_notes,
        theme=theme,
    )

    content = []
    statement = _statement_slide(model, title, theme)
    if statement is not None:
        content.append(statement)
    findings = [f for f in (model.get("findings") or []) if f]
    if findings:
        content.extend(_finding_slide(i, f, title, theme)
                       for i, f in enumerate(findings, 1))
    else:
        top_level = [s for s in (model.get("sections") or [])
                     if s.get("level") == 2]
        content.extend(_section_slide(i, s, title, theme)
                       for i, s in enumerate(top_level, 1))
    facets = [f for f in (model.get("contested_facets") or []) if f]
    content.extend(_facet_slide(i, f, title, theme)
                   for i, f in enumerate(facets, 1))

    omitted = len(content) - CONTENT_SLIDE_CAP
    if omitted > 0:
        content = content[:CONTENT_SLIDE_CAP]
        content[-1]["notes"] += (f"|Deck capped at {CONTENT_SLIDE_CAP} content slides; "
                                 f"{omitted} later content slide(s) omitted.")

    content.append(_sources_slide(model, title, theme))

    sections_html = [cover]
    for i, slide in enumerate(content, start=2):  # the cover is slide 1
        sections_html.append(f'<section class="{slide["cls"]}" '
                             f'data-notes="{esc(slide["notes"])}">{slide["body"](i)}</section>')
    return deck(title, sections_html, theme=theme)


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
