#!/usr/bin/env python3
"""Post-render completeness gate for the themed HTML report.

The 199-bio pipeline ran this as Step 6, after its markdown report became
HTML: pass meant the HTML still held the report the author wrote, so the
pipeline could proceed; fail meant content was lost and the errors named
it. This is the same job against the themed renderer (render_report.py):
every section heading and body line, every citation marker, every
bibliography entry and note, and every link with its URL must survive
the render (compared after HTML-unescaping, so escaped text still
matches). No unfilled template tokens and no emojis. The markdown side
is read through the shared bibliography helper (bibliography.py) and
links are compared in the converter's anchor form.

    python3 verify_html.py --html report.html --md report.md

Exit codes: 0 all checks passed; 1 verification errors (named on
stdout), including unreadable or undecodable files.
"""

import argparse
import re
import sys
from html import unescape
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from bibliography import (
    extract_citations,
    mask_code,
    parse_entries,
    reader_facing_text,
    split_bibliography,
)

# Same shape as md_to_html's link rule: no whitespace or pipe inside a
# target, at most one level of balanced parentheses.
_LINK_RE = re.compile(r"\[([^\]|]+)\]\(((?:[^()\s|<]|\([^()\s|<]*\))+)\)")
_HEADING_RE = re.compile(r"^(#{2,4})[ \t]+(.*)$")
_LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+")
_RULE_RE = re.compile(r"(?:-{3,}|\*{3,}|_{3,})")
_DATE_LINE_RE = re.compile(r"^\*{0,2}Date\*{0,2}\s*:", re.I)
# A whole-line markdown link entry inside the bibliography section.
_BIB_LINK_RE = re.compile(r"^[-*]?\s*\[([^\]]+)\]\((https?://[^)]+)\)\s*$")
# The quoted title of the export entry form 'Author (Year). "Title".
# Publisher.' — mirrors the model builder's rule so author material
# before the quotes is never required as rendered text.
_QUOTED_TITLE_RE = re.compile(r'(?:^|\.\s+)"(.+)"(?=\.?\s*$|\.\s)')
_TR_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.S)
_ANCHOR_RE = re.compile(r'<a\b[^>]*?href="([^"]*)"[^>]*>(.*?)</a>', re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_STYLE_SCRIPT_RE = re.compile(r"<(style|script)\b.*?</\1>", re.S)
_HEADING_ELS_RE = re.compile(
    r"<h[2-4][^>]*>(.*?)</h[2-4]>|"
    r'<p class="rf-eyebrow">(.*?)</p>', re.S)
_CITE_HTML_RE = re.compile(r"\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]")
_PLACEHOLDER_RE = re.compile(r"\{\{[A-Z][A-Z_]*\}\}")
_EMOJI_RE = re.compile(
    "[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF\U00002702-\U000027B0\U000024C2-\U0001F251]+"
)
_SEP_CELL_RE = re.compile(r":?-+:?")


def _plain(html):
    """Text of the HTML: style/script blocks dropped, tags removed,
    entities unescaped, whitespace collapsed.

    Tags are dropped without inserting a space (the renderer emits
    newlines between block elements, and inline tags sit mid-text), and
    unescaping runs after tag removal — the renderer escapes authored
    text, so escaped markup must survive as text, never as a tag."""
    html = _STYLE_SCRIPT_RE.sub(" ", html)
    return re.sub(r"\s+", " ", unescape(_TAG_RE.sub("", html))).strip()


def _strip_inline(text):
    """Remove markdown inline markers: bold, italic, code-span backticks."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"(`+)([^`]+)\1", r"\2", text)
    return re.sub(r"\s+", " ", text).strip()


def _short(text, limit=70):
    text = text.strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _anchors(html):
    """[(unescaped href, plain text)] for every anchor in the HTML."""
    return [(unescape(m.group(1)), _plain(m.group(2)))
            for m in _ANCHOR_RE.finditer(html)]


def _region(html, marker):
    """(raw, plain) for the section that opens with marker, or ('','')."""
    i = html.find(marker)
    if i < 0:
        return "", ""
    j = html.find("</section>", i)
    raw = html[i:j if j >= 0 else len(html)]
    return raw, _plain(raw)


def _md_link(raw_line, masked_match):
    """(text, target) for a link match, sliced from the raw markdown line.

    mask_code keeps character offsets, so the masked match's group spans
    address the raw line; a link inside a code span is blanked in the
    masked line and therefore never reaches here."""
    m = _LINK_RE.match(raw_line, masked_match.start(), masked_match.end())
    return m.group(1), m.group(2)


def _line_needles(text_line, masked_line, require_word=True):
    """What a markdown line must leave in the HTML: text fragments with
    links reduced to their text, and the links themselves.

    Returns (fragments, links): fragments are normalized strings that
    must appear as text; links are (text, target) pairs checked by
    _check_link. Code spans stay inside their fragment (their content is
    literal text, links included). Wordless fragments (an all-dash table
    cell) are kept for table cells via require_word=False."""
    fragments = []
    links = []
    pos = 0
    for m in _LINK_RE.finditer(masked_line):
        fragments.append(text_line[pos:m.start()])
        text, target = _md_link(text_line, m)
        links.append((_strip_inline(text), target))
        pos = m.end()
    fragments.append(text_line[pos:])
    keep = (lambda f: f and re.search(r"\w", f)) if require_word else bool
    worded = [f for f in (_strip_inline(x) for x in fragments) if keep(f)]
    return worded, links


def _md_tables(masked_lines, raw_lines):
    """Consecutive pipe-row groups: [(header_cells, [data_row_cells])].

    Row structure is detected on the masked lines (a fence never holds a
    table) and cells are sliced from the raw lines, so code-span cell
    text is still checked. Only the row directly after the header can be
    the separator — the converter's own rule — so a later all-dash row
    stays a data row."""
    tables = []
    rows = []
    for mi, line in enumerate(list(masked_lines) + [""]):
        if line.strip().startswith("|"):
            raw = raw_lines[mi] if mi < len(raw_lines) else line
            cells = [c.strip() for c in raw.strip().strip("|").split("|")]
            if cells and any(c for c in cells):
                rows.append(cells)
            continue
        if rows:
            header = rows[0]
            data = []
            for pos, cells in enumerate(rows[1:]):
                is_sep = (pos == 0 and len(cells) == len(header) and cells
                          and all(_SEP_CELL_RE.fullmatch(c) for c in cells))
                if not is_sep:
                    data.append(cells)
            tables.append((header, data))
            rows = []
    return tables


def _check_link(text, target, scope_plain, scope_anchors, errors):
    """A markdown link survives as the converter's anchor form or as the
    literal 'text (target)' text (non-https targets, code spans, and
    every link on the plain-text summary path since 2.8's strip_md).
    Link text alone is a lost URL, on every path."""
    literal = f"{text} ({target})"
    if any(href == target and text in atext for href, atext in scope_anchors):
        return
    if literal in scope_plain:
        return
    errors.append(f"lost link: '{_short(text, 40)}' ({target})")


def _author_like(segment):
    """Author/year material the renderer legitimately drops: a year in
    parentheses or a 'Surname, I.' name fragment (the model builder's
    own distinction)."""
    if re.search(r"\((?:18|19|20)\d{2}\)", segment):
        return True
    return bool(re.match(r"^[A-Z][\w'’\-]+,\s*[A-Z]\.?$", segment))


def _bib_text_pool(rest):
    """Segments of a bibliography entry that must survive as rendered
    text: the quoted title (plus any publisher after it) when the entry
    has one, else the longer non-author segments after the first."""
    no_url = re.sub(r"https?://\S+", " ", rest)
    stripped = no_url.strip()
    qm = _QUOTED_TITLE_RE.search(stripped)
    if qm:
        pool = [qm.group(1)]
        for seg in re.split(r"\.\s+", stripped[qm.end():]):
            seg = seg.strip().rstrip(".").strip()
            if seg and not _author_like(seg):
                pool.append(seg)
        return pool
    segs = [x.strip() for x in re.split(r"\.\s+", stripped)
            if x.strip() and not re.fullmatch(r"\((?:18|19|20)\d{2}\)", x.strip())]
    tail = [x.rstrip(".").strip() for x in segs[1:]]
    tail = [x for x in tail if x and not _author_like(x)]
    big = [x for x in tail if len(x.split()) >= 3]
    return big or [x for x in tail if re.search(r"\w", x)] or segs[:1]


def verify(html_path, md_path):
    """Run every completeness check. Returns (errors, warnings)."""
    errors = []
    warnings = []
    try:
        html = Path(html_path).read_text(encoding="utf-8")
        md = Path(md_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"failed to read files: {exc}"], []

    body_md = reader_facing_text(md)
    _, bib_md = split_bibliography(md)
    masked = mask_code(body_md)
    masked_lines = masked.splitlines()
    raw_lines = body_md.splitlines()

    full_plain = _plain(html)
    summary_raw, summary_plain = _region(html, '<section class="rf-summary"')
    # the report body proper: sections render inside rf-doc, before the
    # bibliography. Body lines that did not render through the summary
    # are checked here, not against the whole page — a copy of the same
    # text in the summary, a KPI card or the footer must not hide a loss
    # from the body.
    d0 = html.find('<div class="rf-doc"')
    d1 = html.find('<section class="rf-bib"', d0 if d0 >= 0 else 0)
    doc_raw = html[d0:d1 if d1 >= 0 else len(html)] if d0 >= 0 else ""
    doc_plain = _plain(doc_raw)
    doc_anchors = _anchors(doc_raw)
    h1_plain = " | ".join(_plain(m) for m in re.findall(r"<h1\b[^>]*>(.*?)</h1>", html, re.S))
    bib_raw, bib_plain = _region(html, '<section class="rf-bib"')
    summary_anchors = _anchors(summary_raw)
    bib_anchors = _anchors(bib_raw)
    bib_hrefs = {href for href, _ in bib_anchors}

    # -- structure ------------------------------------------------------
    for needle, name in (("<html", "html tag"), ("<head", "head tag"),
                         ("<body", "body tag"), ("<title>", "title tag"),
                         ('class="rf-page"', "page container")):
        if needle not in html:
            errors.append(f"missing {name} in HTML")
    open_divs, close_divs = html.count("<div"), html.count("</div>")
    if abs(open_divs - close_divs) > 2:
        warnings.append(
            f"possible unclosed divs: {open_divs} opening, {close_divs} closing")

    # -- placeholders and emojis (kept from the original job) -----------
    found = _PLACEHOLDER_RE.findall(html)
    if found:
        errors.append(f"unreplaced template placeholders: {', '.join(found)}")
    emojis = sorted(set(_EMOJI_RE.findall(full_plain)))
    if emojis:
        errors.append(f"emojis in HTML (should be none): {emojis}")

    # -- headings ---------------------------------------------------------
    corpus = " | ".join(
        _plain(next(g for g in m.groups() if g is not None))
        for m in _HEADING_ELS_RE.finditer(html))
    for i, mline in enumerate(masked_lines):
        hm = _HEADING_RE.match(mline)
        if not hm:
            continue
        # group offsets address the masked line; mask_code keeps offsets,
        # so they slice the raw line's authored heading text
        heading = _strip_inline(raw_lines[i][hm.start(2):hm.end(2)])
        if heading and heading not in corpus:
            errors.append(f"missing heading in HTML: {_short(heading)}")

    # -- preamble: title, subtitle, and the lines to skip -----------------
    skip = set()
    title = None
    subtitle = None
    for i, mline in enumerate(masked_lines):
        s = mline.strip()
        if not s:
            continue
        hm = _HEADING_RE.match(mline)
        if hm:
            break
        if title is None and s.startswith("# ") and not s.startswith("## "):
            title = raw_lines[i].strip()[2:].strip()
            skip.add(i)
            continue
        if title is not None and subtitle is None and re.fullmatch(r"\*.+\*", s):
            subtitle = raw_lines[i].strip().strip("*")
            skip.add(i)
            continue
        if _DATE_LINE_RE.match(s):
            skip.add(i)
    if title and _strip_inline(title) not in h1_plain:
        errors.append(f"report title missing from HTML: {_short(title)}")
    if subtitle and _strip_inline(subtitle) not in full_plain:
        errors.append(f"report subtitle missing from HTML: {_short(subtitle)}")

    # -- body text and links ------------------------------------------------
    for i, (raw, mline) in enumerate(zip(raw_lines, masked_lines)):
        s = mline.strip()
        if i in skip or not s or _HEADING_RE.match(mline) or s.startswith("|"):
            continue
        if _RULE_RE.fullmatch(s):
            continue
        # strip the indent and list marker from both lines at the same
        # offset: mask_code keeps offsets, and _line_needles slices the
        # raw line with the masked line's match spans, so the two must
        # stay aligned (a marker stripped from one side only shifts every
        # link span and crashes or mis-slices list items holding links)
        lm = _LIST_RE.match(mline)
        cut = lm.end() if lm else len(mline) - len(mline.lstrip())
        worded, links = _line_needles(raw[cut:], mline[cut:])
        # a line renders through the summary block when everything it
        # authored landed there — its fragments, or, for a link-only
        # line, its link texts
        if worded:
            line_in_summary = all(f in summary_plain for f in worded)
        else:
            line_in_summary = all(t in summary_plain for t, _ in links if t)
        if line_in_summary:
            scope_plain, scope_anchors = summary_plain, summary_anchors
        else:
            scope_plain, scope_anchors = doc_plain, doc_anchors
        for frag in worded:
            if frag not in scope_plain:
                errors.append(f"lost body text: {_short(frag)}")
        for text, target in links:
            _check_link(text, target, scope_plain, scope_anchors, errors)

    # -- tables -------------------------------------------------------------
    tr_rows = [(_plain(m.group(1)), _anchors(m.group(1)))
               for m in _TR_RE.finditer(html)]
    for header, data in _md_tables(masked_lines, raw_lines):
        for cells in [header] + data:
            text_needles = []
            link_needs = []
            for cell in cells:
                cell_worded, cell_links = _line_needles(
                    cell, mask_code(cell), require_word=False)
                text_needles.extend(cell_worded)
                link_needs.extend((text, target, f"{text} ({target})")
                                  for text, target in cell_links)
            for row_plain, row_anchors in tr_rows:
                if not all(c in row_plain for c in text_needles):
                    continue
                if all(
                        any(href == target and text in atext
                            for href, atext in row_anchors)
                        or literal in row_plain
                        for text, target, literal in link_needs):
                    break
            else:
                errors.append(
                    "lost table row: | " + " | ".join(cells) + " |")

    # -- citations ------------------------------------------------------------
    body_html = html.split('<section class="rf-bib"', 1)[0]
    html_cites = set()
    for group in _CITE_HTML_RE.findall(_plain(body_html)):
        html_cites.update(int(n) for n in group.split(","))
    for n in sorted(set(extract_citations(body_md)) - html_cites):
        errors.append(f"citation [{n}] missing from the rendered body")

    # -- bibliography ---------------------------------------------------------
    if bib_md:
        for n, rest in parse_entries(bib_md):
            if f'id="ref-{n}"' not in html:
                errors.append(f"bibliography entry [{n}] missing its row")
                continue
            for url in (u.rstrip(".,);") for u in re.findall(r"https?://\S+", rest)):
                if url not in bib_hrefs:
                    errors.append(
                        f"bibliography entry [{n}] lost its URL: {url}")
            no_url = re.sub(r"https?://\S+", " ", rest)
            needles = [_strip_inline(x).strip('"')
                       for x in _bib_text_pool(rest)]
            if any(n not in bib_plain for n in needles if n):
                pool = _bib_text_pool(rest)
                named = (pool[0] if pool else no_url.strip()) or rest
                errors.append(
                    f"bibliography entry [{n}] lost its text: {_short(named)}")
        for line in bib_md.splitlines():
            s = line.strip()
            if not s or _RULE_RE.fullmatch(s) or parse_entries(s):
                continue
            lm = _BIB_LINK_RE.match(s)
            if lm:
                if lm.group(2) not in bib_hrefs:
                    errors.append(
                        f"bibliography link entry lost its URL: {lm.group(2)}")
                elif _strip_inline(lm.group(1)).strip('"') not in bib_plain:
                    errors.append(
                        f"bibliography link entry lost its text: {_short(lm.group(1))}")
                continue
            note = re.sub(r"^#{1,6}\s+", "", s)
            if note not in bib_plain:
                errors.append(f"bibliography note lost: {_short(note)}")

    return errors, warnings


def main():
    parser = argparse.ArgumentParser(
        description="Verify a rendered HTML report still holds the "
                    "authored markdown report (completeness gate)")
    parser.add_argument("--html", type=Path, required=True,
                        help="path to the rendered HTML report")
    parser.add_argument("--md", type=Path, required=True,
                        help="path to the markdown report it was rendered from")
    args = parser.parse_args()

    for path, label in ((args.html, "HTML"), (args.md, "markdown")):
        if not path.exists():
            print(f"ERROR: {label} file not found: {path}")
            return 1

    errors, warnings = verify(args.html, args.md)

    print(f"verify_html: {args.html} against {args.md}")
    for w in warnings:
        print(f"WARNING: {w}")
    for e in errors:
        print(f"ERROR: {e}")
    if errors:
        plural = "s" if len(errors) != 1 else ""
        print(f"verify_html: FAIL ({len(errors)} error{plural})")
        return 1
    print("verify_html: PASS (all authored content present)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
