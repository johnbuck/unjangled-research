"""Slide plan (E4-R1): the shared content decisions for every deck renderer.

plan_slides(model) turns a render model (build_render_model.py JSON) into a
list of plain JSON-serialisable slide specs — the single place a deck's
content decisions live. The HTML deck renderer (render_deck.py) and the
PowerPoint renderer (render_pptx.py) both lay out this plan; neither
selects or condenses content itself.

Slide sequence: cover (title, subtitle or the summary's first sentence,
date, the format's display name as eyebrow); a statement slide with the
summary's first sentence as the headline and up to three stat tiles; one
slide per finding (falling back to one slide per top-level section when the
model has no findings); one slide per contested facet with one column per
side; a sources slide. Content slides (statement + findings/sections +
facets) are capped at 12 — when the cap bites, the last kept slide's notes
say how many were omitted. Every spec carries speaker notes with the fuller
text it condenses. Nothing is invented: every number and claim comes from
the model.

Every spec carries kind, title, notes, and number; each kind adds only the
keys it needs:
    cover     — eyebrow (format display name), subtitle, date
    statement — eyebrow, section, stats: [{value, label, ref, parts}]
    finding   — eyebrow, section, bullets: [{text, refs}]
    section   — eyebrow, section, bullets: [{text, refs}]
    facet     — eyebrow, section, sides: [{label, summary}]; bullets only
                in the no-sides fallback that condenses the subsection
    sources   — eyebrow, section, sources: [{n, title, publisher, url}],
                more_sources

A finding's bullets each carry the finding's evidence refs (the same list
on every point). A stat's parts are [num, unit] and num + ' ' + unit always
rebuilds the model's verbatim value.
"""
import re
from html import unescape

from build_render_model import sentences

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


def _summary_paragraphs(model):
    return [_WS_RE.sub(" ", str(p)).strip()
            for p in (model.get("executive_summary") or []) if str(p).strip()]


def _cover_spec(model, title, display):
    paragraphs = _summary_paragraphs(model)
    date = model.get("date")
    return {
        "kind": "cover",
        "title": title,
        "eyebrow": display,
        "subtitle": clip(model.get("subtitle") or first_sentence(paragraphs),
                         COVER_SUB_MAX),
        "date": date,
        "notes": _notes_join(title, f"{display} deck", date,
                             clip(paragraphs[0], NOTE_MAX) if paragraphs else ""),
    }


def _statement_spec(model, title):
    """Headline sentence plus up to three stat tiles; None when there is
    neither an executive summary nor key stats."""
    paragraphs = _summary_paragraphs(model)
    stats = [s for s in (model.get("key_stats") or []) if s][:STAT_TILE_MAX]
    if not paragraphs and not stats:
        return None
    return {
        "kind": "statement",
        "title": clip_words(first_sentence(paragraphs), STATEMENT_WORDS)
                 or clip(title, TITLE_MAX),
        "eyebrow": "Statement",
        "section": "Statement",
        "stats": [{
            "value": s.get("value"),
            "label": clip(s.get("label") or "", 90),
            "ref": int(s["ref"]) if s.get("ref") is not None else None,
            "parts": list(stat_parts(s.get("value"))),
        } for s in stats],
        "notes": _notes_join(*(clip(p, NOTE_MAX) for p in paragraphs))
                 or clip(title, NOTE_MAX),
    }


def _finding_spec(idx, finding):
    headline = clip(finding.get("headline") or "", TITLE_MAX) or f"Finding {idx:02d}"
    body_text = _WS_RE.sub(" ", str(finding.get("body") or "")).strip()
    refs = [int(r) for r in (finding.get("refs") or []) if r is not None]
    points = [clip(s, BULLET_MAX) for s in sentences(body_text)][:3]
    return {
        "kind": "finding",
        "title": headline,
        "eyebrow": f"Finding {idx:02d}",
        "section": "Findings",
        "bullets": [{"text": p, "refs": refs} for p in points],
        "notes": _notes_join(headline, clip(body_text, NOTE_MAX),
                             ("Refs: " + " ".join(f"[{r}]" for r in refs))
                             if refs else ""),
    }


def _section_spec(idx, section):
    """Top-level-section fallback slide: its first three sentences as bullets."""
    heading = clip(section.get("heading") or "", TITLE_MAX) or f"Section {idx:02d}"
    text = html_text(section.get("html") or "")
    points = [clip(s, BULLET_MAX) for s in sentences(text)][:3]
    return {
        "kind": "section",
        "title": heading,
        "eyebrow": f"Section {idx:02d}",
        "section": "Sections",
        "bullets": [{"text": p, "refs": []} for p in points],
        "notes": clip(text, NOTE_MAX) or heading,
    }


def _facet_spec(idx, facet):
    facet_title = clip(facet.get("facet") or "", TITLE_MAX) or f"Contested facet {idx:02d}"
    sides = [s for s in (facet.get("sides") or []) if s]
    sub_text = html_text(facet.get("html") or "")
    spec = {
        "kind": "facet",
        "title": facet_title,
        "eyebrow": "Contested facet",
        "section": "Perspectives",
        "sides": [
            {"label": clip(s.get("label") or f"Side {j + 1}", 40),
             "summary": clip(s.get("summary") or "", 200)}
            for j, s in enumerate(sides)
        ],
        # notes carry the full subsection text the slide condenses
        "notes": _notes_join(facet_title, *(
            f"{clip(side.get('label') or '', 40)}: "
            f"{clip(side.get('summary') or '', NOTE_MAX)}"
            for side in sides), clip(sub_text, NOTE_MAX)),
    }
    if not sides:
        # no extracted sides: condense the matched subsection's text, the
        # same trim the section fallback uses
        points = [clip(s, BULLET_MAX) for s in sentences(sub_text)][:3]
        spec["bullets"] = [{"text": p, "refs": []} for p in points]
    return spec


def _sources_spec(model):
    sources = [s for s in (model.get("sources") or []) if s]
    shown = sources[:SOURCE_SLIDE_MAX]
    more = len(sources) - len(shown)
    entries = []
    for i, src in enumerate(shown):
        n = int(src.get("n") or (i + 1))
        entries.append({
            "n": n,
            "title": clip(src.get("title") or src.get("url") or f"Source {n}", 70),
            "publisher": clip(src.get("publisher"), 60) if src.get("publisher") else None,
            "url": src.get("url"),
        })
    return {
        "kind": "sources",
        "title": f"{len(sources)} sources",
        "eyebrow": "Sources",
        "section": "Sources",
        "sources": entries,
        "more_sources": more,
        "notes": f"{len(sources)} sources in the full report"
                 + (f"; {more} beyond the {SOURCE_SLIDE_MAX} shown" if more > 0 else ""),
    }


def plan_slides(model):
    """The deck's slide specs for a render model: cover, statement (when
    there is one), findings or top-level sections, contested facets, then
    sources — content slides capped, every slide numbered from 1."""
    deck_title = clip(model.get("title") or "Untitled report", COVER_TITLE_MAX)
    fmt = model.get("format") or "comprehensive-report"
    display = FORMAT_DISPLAY.get(fmt, str(fmt).replace("-", " ").title())

    specs = [_cover_spec(model, deck_title, display)]
    content = []
    statement = _statement_spec(model, deck_title)
    if statement is not None:
        content.append(statement)
    findings = [f for f in (model.get("findings") or []) if f]
    if findings:
        content.extend(_finding_spec(i, f) for i, f in enumerate(findings, 1))
    else:
        top_level = [s for s in (model.get("sections") or []) if s.get("level") == 2]
        content.extend(_section_spec(i, s) for i, s in enumerate(top_level, 1))
    facets = [f for f in (model.get("contested_facets") or []) if f]
    content.extend(_facet_spec(i, f) for i, f in enumerate(facets, 1))

    omitted = len(content) - CONTENT_SLIDE_CAP
    if omitted > 0:
        content = content[:CONTENT_SLIDE_CAP]
        content[-1]["notes"] += (f"|Deck capped at {CONTENT_SLIDE_CAP} content slides; "
                                 f"{omitted} later content slide(s) omitted.")

    specs.extend(content)
    specs.append(_sources_spec(model))
    for number, spec in enumerate(specs, start=1):  # the cover is slide 1
        spec["number"] = number
    return specs
