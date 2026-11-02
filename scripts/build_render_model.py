#!/usr/bin/env python3
"""
Render model builder: turns a finished report (markdown) plus its optional
run manifest into the single JSON document the report renderer (epic 2) and
deck renderer (epic 3) consume. Section HTML comes from md_to_html's
converter; format inference and per-format structure come from
validate_report's FORMATS table.
"""
import argparse
import json
import re
import sys
from pathlib import Path

from md_to_html import convert_markdown_to_html, _convert_content_section
from validate_report import FORMATS, DEFAULT_FORMAT

BIBLIOGRAPHY_HEADINGS = {"bibliography", "sources"}
SUMMARY_FALLBACKS = ("Summary", "Executive Summary", "Overview")
FINDINGS_SECTIONS = {
    "comprehensive-report": ("Key Findings", "Findings", "Main Analysis"),
    "research-summary": ("Key Findings", "Findings"),
    "comparison": ("Key Findings", "Findings", "Detailed Analysis"),
    "quick-brief": ("Key Findings", "Findings", "Key Points"),
    "discovery-catalog": ("Key Findings", "Findings", "Project Dossiers"),
}
BULLET_FINDINGS_HEADINGS = {"key points", "key findings", "findings"}
PERSPECTIVES_RE = re.compile(
    r"(perspectiv|debate|contested|all[- ]sides|steelman)", re.IGNORECASE
)
FINDING_PREFIX_RE = re.compile(r"^finding\s+\d+\s*[:.\-–—]\s*", re.IGNORECASE)
CITATION_RE = re.compile(r"\[(\d+)\]")
STAT_PATTERNS = [
    re.compile(r"\b(?:19|20)\d{2}\s*[–—-]\s*(?:(?:19|20)\d{2}|present)\b"),
    re.compile(r"\b\d[\d,]*(?:\.\d+)?\s?(?:%|percent\b)"),
    re.compile(
        r"[$€£¥]\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:k|bn|m|million|billion|trillion))?\b"
    ),
    re.compile(r"\b\d[\d,]*(?:\.\d+)?\s+(?:[a-z][a-z\-]*[a-rt-z]\s+)?[a-z][a-z\-]*(?:ies|es|s)\b"),
]
COUNT_UNIT_RE = STAT_PATTERNS[3]
STOP_UNITS = {
    "as", "is", "was", "has", "its", "us", "vs", "this", "thus", "less",
    "versus", "does", "gets", "across",
}
STAT_EXCLUDED_HEADINGS_RE = re.compile(
    r"\b(methodolog|method|criteri|limitation|scope|approach)", re.IGNORECASE
)


def _valid_stat(match):
    if match.re is not COUNT_UNIT_RE:
        return True
    num, _, unit = match.group(0).strip().partition(" ")
    if re.fullmatch(r"(?:18|19|20)\d{2}", num):
        return False
    return unit not in STOP_UNITS


CAMP_PATTERNS = [
    re.compile(
        r"case (?:for|against)\s+(.{2,60}?)"
        r"(?=\s+(?:assembles|argues|rests|cites|builds|draws|contends|holds|points)|[,.]|$)"
    ),
    re.compile(
        r"(?:proponents|advocates|supporters|defenders)\s+of\s+(.{2,60}?)"
        r"(?=\s+(?:defend|argue|hold|maintain|cite|contend|report)|[,.]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:^|\.\s+)(critics|opponents|skeptics|proponents|advocates|supporters)\b",
        re.IGNORECASE,
    ),
]


def strip_md(s):
    s = re.sub(r"\[([^\]]+)\]\((?:[^)]+)\)", r"\1", s)
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"\*(.+?)\*", r"\1", s)
    s = re.sub(r"`([^`]+)`", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


def sentences(text):
    return [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def short(s, n=300):
    s = s.strip()
    if len(s) <= n:
        return s
    return s[:n].rsplit(" ", 1)[0].rstrip(" ,;:")


def norm_heading(h):
    return re.sub(r"\s+", " ", re.sub(r"[*`]", "", h)).strip().lower()


def parse_report(text):
    sections = []
    bib_lines = []
    preamble = []
    current = None
    in_bib = False
    in_fence = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
        m = None if in_fence else re.match(r"^(#{2,3})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            heading = m.group(2).strip()
            if level == 2 and heading.lower() in BIBLIOGRAPHY_HEADINGS:
                in_bib = True
                current = None
                continue
            in_bib = False
            current = {"heading": heading, "level": level, "lines": []}
            sections.append(current)
            continue
        if in_bib:
            bib_lines.append(line)
        elif current is not None:
            current["lines"].append(line)
        else:
            preamble.append(line)
    return {
        "preamble": preamble,
        "sections": sections,
        "bib_body": "\n".join(bib_lines),
    }


def parse_preamble(preamble_lines):
    title = None
    subtitle = None
    date = None
    seen_title = False
    for line in preamble_lines:
        stripped = line.strip()
        if not stripped:
            continue
        if not seen_title and stripped.startswith("# ") and not stripped.startswith("## "):
            title = stripped[2:].strip()
            seen_title = True
            continue
        if seen_title and subtitle is None:
            m = re.match(r"^\*(.+)\*$", stripped)
            if m:
                subtitle = m.group(1).strip()
                continue
        m = re.match(r"^\*{0,2}Date\*{0,2}\s*:\s*(.+)$", stripped, re.IGNORECASE)
        if m:
            date = re.sub(r"\*", "", m.group(1)).strip()
    return title or "", subtitle, date


def infer_format(parsed):
    h2 = [s["heading"] for s in parsed["sections"] if s["level"] == 2]
    has_bib_section = bool(parsed["bib_body"].strip())

    def heading_has(token):
        return any(re.search(token, h, re.IGNORECASE) for h in h2)

    for fmt in ("quick-brief", "comparison", "research-summary", "discovery-catalog"):
        required = FORMATS[fmt]["required"]
        if all(
            any(heading_has(alt) for alt in req.split("|"))
            or (req == "Bibliography" and has_bib_section)
            for req in required
        ):
            return fmt
    return DEFAULT_FORMAT


def build_sections(text, parsed):
    content_html, _ = convert_markdown_to_html(text)
    lines = content_html.split("\n")
    markers = []
    for i, line in enumerate(lines):
        m = re.search(r'<h2 class="section-title">(.*?)</h2>', line)
        if '<h2 class="section-title">' in line and m:
            markers.append((2, norm_heading(re.sub(r"<[^>]+>", "", m.group(1))), i))
            continue
        m = re.search(r'<h3 class="subsection-title">(.*?)</h3>', line)
        if '<h3 class="subsection-title">' in line and m:
            markers.append((3, norm_heading(re.sub(r"<[^>]+>", "", m.group(1))), i))
    fragments = {}
    for idx, (level, heading, start) in enumerate(markers):
        end = markers[idx + 1][2] if idx + 1 < len(markers) else len(lines)
        fragments.setdefault((level, heading), []).append(
            "\n".join(lines[start:end]).strip()
        )
    used = {}
    out = []
    for sec in parsed["sections"]:
        key = (sec["level"], norm_heading(sec["heading"]))
        idx = used.get(key, 0)
        bucket = fragments.get(key, [])
        if idx < len(bucket):
            html = bucket[idx]
        elif sec["level"] == 2:
            html = _convert_content_section(
                f"## {sec['heading']}\n\n" + "\n".join(sec["lines"]).strip()
            ).strip()
        else:
            html = ""
        used[key] = idx + 1
        out.append({"heading": sec["heading"], "level": sec["level"], "html": html})
    return out


def _summary_candidates(fmt):
    candidates = []
    spec_summary = FORMATS.get(fmt, {}).get("summary_section")
    if spec_summary:
        candidates.append(spec_summary)
    candidates += [c for c in SUMMARY_FALLBACKS if c not in candidates]
    return candidates


def _summary_section_index(parsed, fmt):
    for name in _summary_candidates(fmt):
        for i, sec in enumerate(parsed["sections"]):
            if sec["level"] == 2 and sec["heading"].lower() == name.lower():
                return i
    return None


def _findings_section_indexes(parsed, fmt):
    names = {norm_heading(n) for n in FINDINGS_SECTIONS.get(
        fmt, FINDINGS_SECTIONS[DEFAULT_FORMAT])}
    return [
        i for i, sec in enumerate(parsed["sections"])
        if sec["level"] == 2 and norm_heading(sec["heading"]) in names
    ]


def _section_group(parsed, idx):
    sections = parsed["sections"]
    group = [sections[idx]]
    j = idx + 1
    while j < len(sections) and sections[j]["level"] == 3:
        group.append(sections[j])
        j += 1
    return group


def build_executive_summary(parsed, fmt):
    idx = _summary_section_index(parsed, fmt)
    if idx is None:
        return []
    body = "\n".join(parsed["sections"][idx]["lines"]).strip()
    paras = [strip_md(p) for p in re.split(r"\n\s*\n", body)]
    return [p for p in paras if p and not re.fullmatch(r"[-*=_|]+", p.strip())]


def _clean_headline(h):
    h = strip_md(h)
    h = FINDING_PREFIX_RE.sub("", h)
    return h.rstrip(" .:;").strip()


def _finding(headline, raw_text):
    refs = []
    for m in CITATION_RE.finditer(raw_text):
        n = int(m.group(1))
        if n not in refs:
            refs.append(n)
    body = short(" ".join(sentences(strip_md(raw_text))[:2]))
    return {"headline": headline, "body": body, "refs": refs}


def _findings_from_body(heading, body):
    found = []
    paras = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    for para in paras:
        m = re.match(r"^\*\*(.+?)\*\*(.*)", para, re.DOTALL)
        if m:
            found.append(_finding(_clean_headline(m.group(1)), para))
    if found:
        return found
    if norm_heading(heading) in BULLET_FINDINGS_HEADINGS:
        for line in body.splitlines():
            m = re.match(r"^[-*]\s+(.*)$", line.strip())
            if not m:
                continue
            item = m.group(1)
            bm = re.match(r"^\*\*(.+?)\*\*\s*(.*)$", item)
            if bm:
                headline = _clean_headline(bm.group(1))
                raw = bm.group(2) or item
            else:
                plain = strip_md(item)
                headline = short(sentences(plain)[0], 90).rstrip(" .") if plain else ""
                raw = item
            if headline:
                found.append(_finding(headline, raw))
    return found


def build_findings(parsed, fmt):
    out = []
    for idx in _findings_section_indexes(parsed, fmt):
        sec = parsed["sections"][idx]
        children = _section_group(parsed, idx)[1:]
        if children:
            for child in children:
                raw = re.sub(
                    r"(?m)^\s*\**\s*Sources\s*\**:.*$", "", "\n".join(child["lines"])
                ).strip()
                out.append(_finding(_clean_headline(child["heading"]), raw))
        else:
            body = "\n".join(sec["lines"]).strip()
            out.extend(_findings_from_body(sec["heading"], body))
    return out


def _first_stat(sent):
    candidates = []
    for pat in STAT_PATTERNS:
        for m in pat.finditer(sent):
            if _valid_stat(m):
                candidates.append(m)
                break
    if not candidates:
        return None
    return min(candidates, key=lambda m: m.start()).group(0).strip()


# Words a caption never starts or ends on: prepositions, conjunctions,
# articles, pronouns, copulas, and quantity modifiers.
CONNECTOR_WORDS = {
    "a", "an", "the", "and", "or", "but", "nor", "yet", "so", "of", "to",
    "with", "from", "in", "for", "by", "at", "on", "as", "than", "versus",
    "vs", "v", "into", "onto", "upon", "about", "over", "under",
    "between", "among", "across", "through", "during", "within",
    "without", "per", "via", "including", "called", "is", "are", "was",
    "were", "be", "been", "being", "am", "has", "have", "had", "do",
    "does", "did", "will", "would", "can", "could", "should", "may",
    "might", "must", "its", "their", "his", "her", "our", "your", "my",
    "this", "that", "these", "those", "which", "who", "whom", "whose",
    "what", "it", "they", "he", "she", "we", "you", "i", "more", "most",
    "less", "least", "fewer", "some", "such", "both", "either",
    "neither", "each", "all", "any", "no", "not", "if", "then",
    "because", "since", "although", "though", "however", "thus",
    "therefore", "when", "while", "where", "after", "before",
}
# Linking verbs a caption also never starts or ends on: "A third cohort
# tracked 1,323 ..." must not caption as "third cohort tracked".
VERB_EDGE_WORDS = {
    "tracked", "pooled", "carries", "carried", "clears", "totaled",
    "totalled", "totaling", "totalling", "reached", "found", "showed",
    "reported", "explained", "ran", "analyzed", "analysed", "surveyed",
    "enrolled", "examined", "included", "spanning", "covering",
    "comprising", "averaging", "involving", "affecting", "tracking",
    "rose", "fell", "increased", "decreased", "dropped", "climbed",
}
# Value units that measure rather than count: the counted noun is not in
# the value, so the caption prefers the words before the value.
MEASURE_UNITS = {
    "percent", "percentage", "times", "thousand", "million", "billion",
    "trillion",
}
CAPTION_MIN_WORDS = 3
CAPTION_MAX_WORDS = 8
_EDGE_STOP_SET = CONNECTOR_WORDS | VERB_EDGE_WORDS
_EDGE_STRIP_RE = re.compile(r"[,;:.!?…—–\"']")
_CLAUSE_CLOSE_RE = re.compile(r"[,;:.!?…—–]$")
_COORD_CONJ = ("and", "but", "nor")


def _edge_word(tok):
    return _EDGE_STRIP_RE.sub("", tok).lower()


def _has_alnum(tok):
    return any(ch.isalnum() for ch in tok)


def _numish(tok):
    """A token that IS a number ("81,234", "2022,", "$4") rather than an
    identifier that merely contains one ("A2A", "Agent2Agent")."""
    return bool(re.match(r"^[$€£¥]?\d", tok))


def _balanced(s):
    return (s.count('"') % 2 == 0 and s.count("(") == s.count(")")
            and s.count("[") == s.count("]"))


def _clean_sentence(sent):
    text = re.sub(r"\s*\[E:[^\]]*\]", "", strip_md(sent))
    return re.sub(r"\s*\[\d+\]", "", text).strip()


def _after_span(words, cap):
    """Contiguous words after the value: stops before a stand-alone
    punctuation token, a digit-bearing token (another value), or a
    coordinating conjunction, and after a token that closes a clause."""
    span = []
    for tok in words:
        if not _has_alnum(tok) or _numish(tok):
            break
        if _edge_word(tok) in _COORD_CONJ:
            break
        span.append(tok)
        if _CLAUSE_CLOSE_RE.search(tok) or len(span) >= cap:
            break
    return span


def _before_span(words, cap):
    """Contiguous words before the value, walking right to left: stops
    before a stand-alone punctuation token or a digit-bearing token.
    Clause punctuation may be crossed — the subject of the number often
    sits in the clause before it ("Joplin leads on every signal:
    48,000 stars")."""
    span = []
    for tok in reversed(words):
        if not _has_alnum(tok) or _numish(tok):
            break
        span.append(tok)
        if len(span) >= cap:
            break
    span.reverse()
    return span


def _edge_junk(tok):
    """Punctuation alone, a bracketed/parenthetical fragment, or a
    dangling close bracket: never fit at a caption edge."""
    if not _has_alnum(tok):
        return True
    if tok[0] in "([":
        return True
    return tok[-1] in ")]"


def _trim_edges(span):
    span = list(span)
    while True:
        changed = False
        while span and _edge_word(span[-1]) in _EDGE_STOP_SET:
            span.pop()
            changed = True
        while span and _edge_word(span[0]) in _EDGE_STOP_SET:
            span.pop(0)
            changed = True
        while span and _edge_junk(span[-1]):
            span.pop()
            changed = True
        while span and _edge_junk(span[0]):
            span.pop(0)
            changed = True
        if not changed:
            break
    # "<subject> <linking verb> <rest>" is a clause, not a caption: drop
    # the subject-verb head ("children reported odds" -> "odds").
    if len(span) >= 2 and _edge_word(span[1]) in VERB_EDGE_WORDS:
        span = span[2:]
        while span and _edge_word(span[0]) in _EDGE_STOP_SET:
            span.pop(0)
    return span


def _unit_words(value):
    """The value's count noun when it has one: "2,587 tenth-graders" ->
    ["tenth-graders"]; measure words ("4.6 percent") count for nothing."""
    toks = value.split()
    i = 0
    while i < len(toks) and _numish(toks[i]):
        i += 1
    unit = toks[i:]
    if not unit or _edge_word(unit[0]) in MEASURE_UNITS:
        return []
    return unit


def _stat_label(sent, value):
    """A caption for a key stat: one contiguous run of 3-8 words from
    the source sentence, never spliced across the value. Prefer the
    words after the value — led by the value's own count noun when it
    has one — else the words before it; a caption never starts or ends
    on a connector or linking verb. When no run qualifies, return None:
    the caller drops the stat rather than show a fragment."""
    text = _clean_sentence(sent)
    idx = text.find(value)
    if idx < 0:
        return None
    before = text[:idx].split()
    after = text[idx + len(value):].split()
    unit = _unit_words(value)
    candidates = []
    if unit:
        window = _after_span(after, CAPTION_MAX_WORDS - len(unit))
        if sum(1 for w in window if _has_alnum(w)) >= CAPTION_MIN_WORDS:
            candidates.append(unit + window)
        candidates.append(_after_span(after, CAPTION_MAX_WORDS))
        candidates.append(_before_span(before, CAPTION_MAX_WORDS))
    else:
        candidates.append(_before_span(before, CAPTION_MAX_WORDS))
        candidates.append(_after_span(after, CAPTION_MAX_WORDS))
    for cand in candidates:
        span = _trim_edges(cand)
        if not CAPTION_MIN_WORDS <= len(span) <= CAPTION_MAX_WORDS:
            continue
        label = " ".join(span).strip(" \t,;:.!?…—–\"'")
        words = label.split()
        if not CAPTION_MIN_WORDS <= len(words) <= CAPTION_MAX_WORDS:
            continue
        if value in label or label not in text or not _balanced(label):
            continue
        if _edge_junk(words[0]) or _edge_junk(words[-1]):
            continue
        if _edge_word(words[0]) in _EDGE_STOP_SET:
            continue
        if _edge_word(words[-1]) in _EDGE_STOP_SET:
            continue
        return label
    return None


def build_key_stats(parsed, fmt, limit=6):
    order = []
    summary_idx = _summary_section_index(parsed, fmt)
    if summary_idx is not None:
        order.extend(_section_group(parsed, summary_idx))
    for idx in _findings_section_indexes(parsed, fmt):
        order.extend(_section_group(parsed, idx))
    stats = []
    seen = set()
    for sec in order:
        if STAT_EXCLUDED_HEADINGS_RE.search(sec["heading"]):
            continue
        for line in sec["lines"]:
            s = line.strip()
            if not s or s.startswith("|") or s.startswith("#"):
                continue
            s = re.sub(r"^\s*[-*]\s+", "", s)
            for sent in sentences(s):
                value = _first_stat(sent)
                if not value or value in seen:
                    continue
                label = _stat_label(sent, value)
                if not label:
                    continue
                seen.add(value)
                ref_m = CITATION_RE.search(sent)
                stats.append({
                    "value": value,
                    "label": label,
                    "ref": int(ref_m.group(1)) if ref_m else None,
                })
                if len(stats) == limit:
                    return stats
    return stats


def _camp_label(sent):
    for pat in CAMP_PATTERNS:
        m = pat.search(sent)
        if m:
            label = m.group(1).strip(" ,;:.\"'")
            label = re.sub(r"^the\s+", "", label, flags=re.IGNORECASE).strip()
            return short(label, 60) or None
    return None


CASE_OPEN_RE = re.compile(
    r"^\s*the\s+(.{2,60}?)\s+case\b(?!\s+(?:for|of|against|that)\b)", re.IGNORECASE
)
LIST_OR_TABLE_RE = re.compile(r"^\s*(?:[-*+]\s+\S|>\s*\|?\s*-|\|)")


def _content_paragraphs(body):
    """Blank-line-separated blocks of the subsection body with list items,
    table rows, and blank lines dropped."""
    paras = []
    for block in re.split(r"\n\s*\n", body or ""):
        lines = [line.strip() for line in block.splitlines()
                 if line.strip() and not LIST_OR_TABLE_RE.match(line)]
        text = " ".join(lines).strip()
        if text:
            paras.append(text)
    return paras


def _side_label(paragraph, index):
    """'<Words> case' when the paragraph opens 'The <words> case'; else the
    first sentence's camp marker; else 'Position N'."""
    m = CASE_OPEN_RE.match(paragraph)
    if m:
        words = m.group(1).strip()
        return words[0].upper() + words[1:] + " case"
    first = sentences(paragraph)[:1]
    camp = _camp_label(first[0]) if first else None
    if camp:
        return camp
    return f"Position {index + 1}"


def _side_summary(paragraph, limit=300):
    """The paragraph's first two sentences (citations kept), trimmed at a
    sentence boundary when one fits and otherwise at a word boundary."""
    text = ""
    for sent in sentences(paragraph)[:2]:
        if text and len(text) + 1 + len(sent) > limit:
            break
        text = f"{text} {sent}".strip()
    return text if len(text) <= limit else short(text, limit)


def _sides_from_sentences(text):
    """Single-paragraph fallback: camp markers pick their own sentences, and
    without any, cited sentences stand in. Sides are labelled Position N,
    and the cited-sentence filler never runs once a camp marker was found —
    no two sides from one sentence run."""
    sents = sentences(strip_md(text))
    picks = [s for s in sents if _camp_label(s)]
    if not picks:
        picks = [s for s in sents if CITATION_RE.search(s)][:2]
    return [{"label": f"Position {i + 1}", "summary": short(s, 300)}
            for i, s in enumerate(picks[:4])]


def _sides(body):
    """One side per paragraph — the contested-topics house style steelsmans
    each side in its own paragraph — labelled 'X case' / camp marker /
    'Position N', max four, in paragraph order. A single-paragraph
    subsection falls back to sentence-level extraction."""
    paras = [strip_md(p) for p in _content_paragraphs(body)]
    if len(paras) <= 1:
        return _sides_from_sentences(paras[0] if paras else "")
    sides = []
    labels = set()
    for i, para in enumerate(paras[:4]):
        label = _side_label(para, i)
        if label.casefold() in labels:
            label = f"Position {i + 1}"
        labels.add(label.casefold())
        sides.append({"label": label, "summary": _side_summary(para)})
    return sides


FACET_VS_RE = re.compile(r"\b(?:vs\.?|v\.)", re.IGNORECASE)
FACET_PUNCT_RE = re.compile(r"[^\w\s]")


def _facet_tokens(text):
    """Normalization for facet/heading comparison: casefold, vs./vs/v. to
    'versus', punctuation stripped, then tokenized."""
    text = FACET_VS_RE.sub(" versus ", text.casefold())
    return FACET_PUNCT_RE.sub(" ", text).split()


def _facet_short_name(facet):
    """The facet's name before its first colon or question mark, when
    present — 'Alpha vs. beta: does...' compares as 'Alpha versus beta'."""
    head = re.split(r"[:?]", facet, maxsplit=1)[0].strip()
    return head or facet


def _facet_heading_overlap(facet, heading):
    """Token overlap of the facet's short name against a subsection heading:
    matched content tokens over the shorter side's tokens."""
    f_tokens = set(_facet_tokens(_facet_short_name(facet)))
    h_tokens = set(_facet_tokens(heading))
    if not f_tokens or not h_tokens:
        return 0.0
    return len(f_tokens & h_tokens) / min(len(f_tokens), len(h_tokens))


def _match_facets_to_children(facets, children):
    """Pair manifest facets with Perspectives subsections: token overlap
    first (>= 0.6), then a positional fallback when facet and subsection
    counts agree but some facets stayed unmatched. One child index (or
    None) per facet."""
    assigned = [None] * len(facets)
    taken = set()
    for fi, facet in enumerate(facets):
        for ci, child in enumerate(children):
            if ci in taken:
                continue
            if _facet_heading_overlap(facet, child["heading"]) >= 0.6:
                assigned[fi] = ci
                taken.add(ci)
                break
    if len(facets) == len(children):
        unmatched = [fi for fi, ci in enumerate(assigned) if ci is None]
        free = [ci for ci in range(len(children)) if ci not in taken]
        for fi, ci in zip(unmatched, free):
            assigned[fi] = ci
    return assigned


def build_contested_facets(manifest, parsed, built_sections):
    if not manifest:
        return []
    facets = manifest.get("contested_facets") or []
    if not facets:
        return []
    sections = parsed["sections"]
    persp_idx = None
    for i, sec in enumerate(sections):
        if sec["level"] == 2 and PERSPECTIVES_RE.search(sec["heading"]):
            persp_idx = i
            break
    child_indexes = []
    if persp_idx is not None:
        j = persp_idx + 1
        while j < len(sections) and sections[j]["level"] == 3:
            child_indexes.append(j)
            j += 1
    children = [sections[k] for k in child_indexes]
    assigned = _match_facets_to_children(facets, children)
    out = []
    for facet, ci in zip(facets, assigned):
        body, html = "", ""
        if ci is not None:
            child = children[ci]
            body = "\n".join(child["lines"]).strip()
            html = (built_sections[child_indexes[ci]].get("html") or "").strip()
            if not html and body:
                html = _convert_content_section(
                    f"### {child['heading']}\n\n{body}"
                ).strip()
        out.append({"facet": facet, "sides": _sides(body), "html": html})
    return out


def _author_like(seg):
    if re.search(r"\((?:18|19|20)\d{2}\)", seg):
        return True
    return bool(re.match(r"^[A-Z][\w'’\-]+,\s*[A-Z]\.?$", seg))


def _parse_bib_numbered(text):
    url_m = re.search(r"(https?://\S+)", text)
    url = url_m.group(1).rstrip(".,);") if url_m else None
    text2 = text.replace(url_m.group(1), " ", 1) if url_m else text
    segs = [
        s.strip()
        for s in re.split(r"\.\s+", text2.strip().rstrip("."))
        if s.strip() and not re.fullmatch(r"\((?:18|19|20)\d{2}\)", s.strip())
    ]
    quoted = next((s for s in segs if re.fullmatch(r'"(.+)"', s)), None)
    if quoted:
        title = quoted[1:-1]
        rest = [s for s in segs if s != quoted and not _author_like(s)]
        publisher = rest[-1] if rest else None
    elif len(segs) >= 2 and _author_like(segs[0]):
        title = segs[1]
        rest = segs[2:]
        publisher = rest[-1] if rest else None
    elif len(segs) >= 2 and len(segs[0].split()) <= 2:
        title = segs[1]
        rest = segs[2:]
        publisher = rest[-1] if rest else segs[0]
    else:
        title = strip_md(segs[0]) if segs else strip_md(text2)
        publisher = None
    return {"title": title, "url": url, "publisher": publisher}


def build_sources(bib_body):
    sources = []
    auto_n = 0
    for line in bib_body.splitlines():
        s = line.strip()
        if not s or s == "---":
            continue
        m = re.match(r"^[-*]?\s*\[(\d+)\]\s*(.+)$", s)
        if m:
            n = int(m.group(1))
            entry = _parse_bib_numbered(m.group(2))
        else:
            lm = re.match(r"^[-*]?\s*\[([^\]]+)\]\((https?://[^)]+)\)\s*$", s)
            if not lm:
                continue
            auto_n += 1
            n = auto_n
            entry = {"title": strip_md(lm.group(1)), "url": lm.group(2), "publisher": None}
        sources.append({"n": n, **entry})
    return sources


def build_model(report_text, manifest=None, fmt=None):
    parsed = parse_report(report_text)
    title, subtitle, date = parse_preamble(parsed["preamble"])
    if fmt is None and isinstance(manifest, dict):
        for key in ("format", "report_format"):
            value = manifest.get(key)
            if value in FORMATS:
                fmt = value
                break
    if fmt is None:
        fmt = infer_format(parsed)
    if date is None and isinstance(manifest, dict):
        started = manifest.get("started_at")
        if isinstance(started, str) and started[:4].isdigit():
            date = started[:10]
    sections = build_sections(report_text, parsed)
    return {
        "title": title,
        "subtitle": subtitle,
        "date": date,
        "format": fmt,
        "executive_summary": build_executive_summary(parsed, fmt),
        "key_stats": build_key_stats(parsed, fmt),
        "sections": sections,
        "findings": build_findings(parsed, fmt),
        "contested_facets": build_contested_facets(manifest, parsed, sections),
        "sources": build_sources(parsed["bib_body"]),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Build the render model JSON from a finished report",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python build_render_model.py --report report.md
  python build_render_model.py --report report.md --manifest run_manifest.json --out render_model.json
        """,
    )
    parser.add_argument("--report", "-r", required=True, help="Path to report markdown")
    parser.add_argument("--manifest", "-m", default=None, help="Path to run_manifest.json")
    parser.add_argument(
        "--format", "-f", default=None, choices=sorted(FORMATS.keys()),
        help="Report format; default: manifest value, else inferred from headings, else comprehensive-report",
    )
    parser.add_argument("--out", "-o", default=None, help="Write JSON here (stdout when omitted)")
    args = parser.parse_args()

    report_path = Path(args.report)
    if not report_path.exists():
        print(f"ERROR: report not found: {report_path}", file=sys.stderr)
        sys.exit(1)
    manifest = None
    if args.manifest:
        manifest_path = Path(args.manifest)
        if not manifest_path.exists():
            print(f"ERROR: manifest not found: {manifest_path}", file=sys.stderr)
            sys.exit(1)
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)

    model = build_model(report_path.read_text(encoding="utf-8"), manifest, args.format)
    payload = json.dumps(model, indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)


if __name__ == "__main__":
    main()
