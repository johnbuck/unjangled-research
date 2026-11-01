#!/usr/bin/env python3
"""
Themed report renderer: turns a render model (build_render_model.py JSON)
into a self-contained themed HTML page per E2-R1 — header with title,
subtitle, date, and the format's display name as the eyebrow; KPI cards
from key_stats; executive summary; sections in model order; a Perspectives
block per contested facet; a numbered bibliography whose id="ref-N" anchors
the in-text [N] citations link to; footer from the theme's label template.

    python3 render_report.py --model render_model.json [--theme neutral] --out report.html
    python3 render_report.py --report report.md [--manifest run_manifest.json] \
        [--format comprehensive-report] [--theme neutral] --out report.html
"""
import argparse
import json
import re
import sys
from html import unescape
from pathlib import Path

from build_render_model import build_model, _summary_candidates, PERSPECTIVES_RE
from render_lib import page, page_header, page_footer, esc

FORMAT_DISPLAY = {
    "comprehensive-report": "Comprehensive Report",
    "research-summary": "Research Summary",
    "comparison": "Comparison",
    "quick-brief": "Quick Brief",
    "discovery-catalog": "Discovery Catalog",
}
FOOTER_SECTION = "Research report"
TOC_MIN_SECTIONS = 5
CITATION_RE = re.compile(r"\[(\d{1,3})\]")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_DIV_RE = re.compile(r"</?div[^>]*>")
_HR_PARA_RE = re.compile(r"<p>\s*(?:-{3,}|\*{3,}|_{3,})\s*</p>")


def _clean_section_html(html):
    """Make an md_to_html fragment renderable inside its own section wrapper:
    drop the wrapper divs (fragment boundaries leave them unbalanced),
    collapse [text](url) markdown links to their text (full URLs live in the
    bibliography), and drop thematic-break paragraphs."""
    html = _DIV_RE.sub("", html)
    html = _MD_LINK_RE.sub(r"\1", html)
    html = _HR_PARA_RE.sub("", html)
    return html.strip()


def _link_citations(text, valid_ns):
    """[N] → <a href="#ref-N" class="rf-cite">[N]</a> for every N that has a
    bibliography anchor; unresolvable markers stay plain text."""
    def repl(m):
        n = int(m.group(1))
        if n in valid_ns:
            return f'<a class="rf-cite" href="#ref-{n}">[{n}]</a>'
        return m.group(0)
    return CITATION_RE.sub(repl, text)


def _summary_index(model, fmt):
    for name in _summary_candidates(fmt):
        for i, sec in enumerate(model["sections"]):
            if sec["level"] == 2 and sec["heading"].strip().lower() == name.lower():
                return i
    return None


def _perspectives_group(model):
    """(index of the Perspectives/Debate h2, its h3 children) or (None, [])."""
    sections = model["sections"]
    for i, sec in enumerate(sections):
        if sec["level"] == 2 and PERSPECTIVES_RE.search(sec["heading"]):
            children = []
            j = i + 1
            while j < len(sections) and sections[j]["level"] == 3:
                children.append(j)
                j += 1
            return i, children
    return None, []


def _rendered_facet_headings(facets):
    """Headings of subsections whose html is carried inside the Perspectives
    block; only those are skipped in the normal section flow."""
    headings = set()
    for facet in facets:
        for m in re.finditer(
            r'<h3 class="subsection-title">(.*?)</h3>', facet.get("html") or "", re.S
        ):
            headings.add(unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip().lower())
    return headings


def _kpi_strip(stats, valid_ns):
    cards = []
    for stat in stats:
        ref = stat.get("ref")
        link = ""
        if ref is not None and ref in valid_ns:
            link = f'<a class="rf-cite" href="#ref-{ref}">[{ref}]</a>'
        cards.append(
            f'<div class="rf-kpi"><span class="rf-kpi-label">{esc(stat.get("label") or "")}</span>'
            f'<span class="rf-kpi-num">{esc(stat.get("value") or "")}</span>'
            f'<span class="rf-kpi-note">{link}</span></div>'
        )
    return f'<section class="rf-kpis" aria-label="Key statistics">{"".join(cards)}</section>'


def _toc(entries):
    items = "".join(
        f'<li><a href="#{anchor}"><span class="rf-toc-num">{n:02d}</span>{esc(label)}</a></li>'
        for n, (label, anchor) in enumerate(entries, 1)
    )
    return ('<nav class="rf-toc" aria-label="Contents">'
            f'<p class="rf-toc-title">Contents</p><ol>{items}</ol></nav>')


def _summary_block(heading, paragraphs, valid_ns):
    ps = "".join(
        f'<p>{_link_citations(esc(p), valid_ns)}</p>' for p in paragraphs
    )
    return (f'<section class="rf-summary" aria-label="Executive summary">'
            f'<p class="rf-eyebrow">{esc(heading)}</p>'
            f'<div class="rf-summary-body">{ps}</div></section>')


def _perspectives_block(heading, facets, anchor, valid_ns):
    facet_html = []
    for facet in facets:
        sides = []
        for j, side in enumerate(facet.get("sides") or []):
            cls = "a" if j % 2 == 0 else "b"
            label = side.get("label") or f"Side {j + 1}"
            summary = side.get("summary") or ""
            sides.append(
                f'<div class="rf-persp-side {cls}"><p class="rf-eyebrow">{esc(label)}</p>'
                f'<p class="rf-persp-text">{_link_citations(esc(summary), valid_ns)}</p></div>'
            )
        sub_html = _link_citations(
            _clean_section_html(facet.get("html") or ""), valid_ns)
        panel = (
            f'<article class="rf-persp-facet">'
            f'<h3 class="rf-persp-facet-title">{esc(facet.get("facet") or "Contested facet")}</h3>'
        )
        if sides:
            panel += f'<div class="rf-persp-sides">{"".join(sides)}</div>'
        if sub_html:
            panel += f'<div class="rf-persp-body">{sub_html}</div>'
        facet_html.append(panel + "</article>")
    return (f'<section class="rf-sec rf-persp" id="{anchor}" aria-label="Perspectives">'
            f'<h2 class="section-title">{esc(heading)}</h2>'
            f'<div class="rf-persp-list">{"".join(facet_html)}</div></section>')


def _bibliography(sources):
    rows = []
    for src in sources:
        n = src["n"]
        title_text = esc(src.get("title") or src.get("url") or f"Source {n}")
        if src.get("url"):
            link = f'<a class="rf-ref-link" href="{esc(src["url"])}">{title_text}</a>'
        else:
            link = f'<span class="rf-ref-title">{title_text}</span>'
        pub = (f' <span class="rf-ref-pub">— {esc(src["publisher"])}</span>'
               if src.get("publisher") else "")
        rows.append(
            f'<div class="rf-ref" id="ref-{n}"><span class="rf-ref-num">[{n}]</span>'
            f'<span class="rf-ref-body">{link}{pub}</span></div>'
        )
    return ('<section class="rf-bib" id="refs" aria-label="Bibliography">'
            '<h2 class="section-title">Bibliography</h2>'
            f'<div class="rf-refs">{"".join(rows)}</div></section>')


def render_report(model, theme="neutral"):
    """Compose the themed report page from a render model dict."""
    sections = model.get("sections") or []
    sources = model.get("sources") or []
    valid_ns = {src["n"] for src in sources}
    fmt = model.get("format") or "comprehensive-report"
    display = FORMAT_DISPLAY.get(fmt, fmt.replace("-", " ").title())
    title = model.get("title") or "Untitled report"
    subtitle = model.get("subtitle")
    date = model.get("date")

    summary_idx = _summary_index(model, fmt)
    summary_paras = [p for p in (model.get("executive_summary") or []) if p.strip()]
    persp_idx, persp_children = _perspectives_group(model)
    facets = model.get("contested_facets") or []
    # the Perspectives block replaces the original section only when at
    # least one facet matched a subsection (sides or html); otherwise the
    # section renders as normal body so no content is dropped
    matched_any = any(f.get("html") or f.get("sides") for f in facets)
    use_persp_block = bool(facets) and persp_idx is not None and matched_any
    skipped = {summary_idx} if (summary_idx is not None and summary_paras) else set()
    if use_persp_block:
        in_block = _rendered_facet_headings(facets)
        for j in persp_children:
            if sections[j]["heading"].strip().lower() in in_block:
                skipped.add(j)

    h2_indexes = [i for i, sec in enumerate(sections) if sec["level"] == 2]

    parts = [page_header(display, title, sub=subtitle, meta=date, theme=theme)]

    if model.get("key_stats"):
        parts.append(_kpi_strip(model["key_stats"], valid_ns))

    toc_entries = [
        (sections[i]["heading"], f"sec-{i}")
        for i in h2_indexes if i not in skipped
    ]
    if sources:
        toc_entries.append(("Bibliography", "refs"))
    if len(h2_indexes) >= TOC_MIN_SECTIONS:
        parts.append(_toc(toc_entries))

    if summary_idx is not None and summary_paras:
        parts.append(_summary_block(sections[summary_idx]["heading"], summary_paras, valid_ns))

    doc = []
    for i, sec in enumerate(sections):
        if use_persp_block and i == persp_idx:
            doc.append(_perspectives_block(
                sections[persp_idx]["heading"], facets, f"sec-{persp_idx}", valid_ns))
            continue
        if i in skipped:
            continue
        html = _clean_section_html(sec.get("html") or "")
        if sec["level"] == 2:
            if html:
                html = html.replace(
                    '<h2 class="section-title">',
                    f'<h2 class="section-title" id="sec-{i}">', 1)
                html = _link_citations(html, valid_ns)
            else:
                html = (f'<h2 class="section-title" id="sec-{i}">{esc(sec["heading"])}</h2>')
        else:
            if not html:
                html = f'<h3 class="subsection-title">{esc(sec["heading"])}</h3>'
            else:
                html = _link_citations(html, valid_ns)
        doc.append(f'<section class="rf-sec rf-l{sec["level"]}">{html}</section>')
    parts.append(f'<div class="rf-doc">{"".join(doc)}</div>')

    if sources:
        parts.append(_bibliography(sources))

    parts.append(page_footer(theme=theme, title=title, section=FOOTER_SECTION,
                             right=date or ""))
    body = f'<div class="rf-report">{"".join(parts)}</div>'
    return page(title, body, theme=theme)


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
        description="Render a themed HTML report from a render model (E2-R1)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 render_report.py --model render_model.json --out report.html
  python3 render_report.py --report report.md --manifest run_manifest.json --out report.html
  python3 render_report.py --report report.md --theme themes/neutral --out report.html
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
    ap.add_argument("--out", "-o", required=True, help="write the HTML report here")
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

    html = render_report(model, theme=args.theme)
    out = Path(args.out)
    if out.parent and not out.parent.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
