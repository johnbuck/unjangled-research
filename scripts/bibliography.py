#!/usr/bin/env python3
"""Shared bibliography rule for every script that splits or parses a report.

One module decides where the bibliography starts and ends, which entry
forms are valid, and how inline citations are extracted (initiative H4,
epic-gate-integrity E1-R1). Adopted by readability_check.py and
extract_claims.py; validate_report.py, verify_citations.py (entries 3 and
4) and md_to_html.py / build_render_model.py (epic render-fidelity)
import this module instead of keeping their own regex.

Rule:
  - The bibliography starts at a line that is exactly ``## Bibliography``
    or ``## Sources`` (space or tab after the hashes, optional trailing
    spaces). A ``### Sources of funding`` subsection or a
    ``## Sources of funding`` heading is NOT a bibliography start — the
    heading must be exact.
  - It ends at the next ``## `` heading or the end of the file.
  - An entry is a line starting ``[N]``, ``- [N]`` or ``* [N]``.
  - Fenced code blocks are not content: a ``## Bibliography`` or ``## ``
    line inside a fence never starts or ends the section.

Two views:
  - ``body_before_bibliography(text)`` — the citation-density window:
    everything before the bibliography heading. The readability gates'
    density thresholds are calibrated on this window.
  - ``reader_facing_text(text)`` — the whole document minus the
    bibliography section, so post-bibliography appendices stay in scope
    for the internals gate and claim extraction.

Inline citations: ``[N]``, ``[N, M]`` and ``[N,M]`` forms, N limited to
1-3 digits (so bracketed years such as ``[2024]`` do not count), with
code spans and fenced code blocks excluded.

Code exclusion comes in two forms: ``strip_code(text)`` removes code
(for counting), ``mask_code(text)`` blanks it in place so offsets stay
valid (for rewriting markers in the original text).
"""

import re

# A line that is exactly '## Bibliography' or '## Sources' (space or tab
# after the hashes, trailing spaces allowed; optional \r so CRLF files
# still match). Anchored: '### Sources of funding' and
# '## Sources of funding' must not match.
BIB_HEADING_RE = re.compile(r"(?m)^##[ \t](?:Bibliography|Sources)[ \t]*\r?$")

# A '## ' heading ends the bibliography section.
NEXT_SECTION_RE = re.compile(r"(?m)^##[ \t]")

# Entry forms: '[N] ...', '- [N] ...', '* [N] ...'.
ENTRY_RE = re.compile(r"^(?:[-*][ \t]+)?\[(\d{1,3})\][ \t]*(.*)$")

# Inline citations, both '[1]' and '[1, 2]'; N is 1-3 digits.
CITATION_RE = re.compile(r"\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]")

# Fenced code blocks: ``` or ~~~ to the matching fence, or to EOF when
# the fence is never closed. The closing fence allows a trailing \r so a
# CRLF file's fences close (otherwise the mask runs to EOF and hides the
# bibliography heading).
_FENCE_RE = re.compile(r"(?ms)^(?:```|~~~).*?(?:^(?:```|~~~)[ \t]*\r?$|\Z)")

# Inline code spans: one or more backticks to the next backtick run of
# the same length, never crossing a line break.
_SPAN_RE = re.compile(r"(`+)[^`\n]*?\1")


def strip_code(text: str) -> str:
    """Remove fenced code blocks, then inline code spans."""
    text = _FENCE_RE.sub(" ", text)
    return _SPAN_RE.sub(" ", text)


def _mask_code(text: str) -> str:
    """Blank out fenced-code content, preserving length and newlines.

    Heading scans run on the masked text so a '## ' or '## Bibliography'
    line inside a fenced example never starts or ends the bibliography;
    match offsets stay valid for slicing the original text.
    """
    chars = list(text)
    for m in _FENCE_RE.finditer(text):
        for i in range(m.start(), m.end()):
            if chars[i] != "\n":
                chars[i] = " "
    return "".join(chars)


def mask_code(text: str) -> str:
    """Blank out fenced code blocks and inline code spans, preserving
    length and newlines.

    The offset-preserving counterpart of ``strip_code``: the same code is
    excluded (fences first, then spans, so a backtick inside a fence never
    pairs with one outside it), but every masked character becomes a
    space instead of being removed. Match offsets found on the masked
    text are therefore valid for slicing or rewriting the original text —
    use it to find citation markers to rewrite while leaving markers in
    code untouched. Newlines are kept, so line numbers stay valid too.
    """
    fence_masked = _mask_code(text)
    chars = list(fence_masked)
    for m in _SPAN_RE.finditer(fence_masked):
        for i in range(m.start(), m.end()):
            if chars[i] != "\n":
                chars[i] = " "
    return "".join(chars)


def split_bibliography(text: str) -> tuple[str, "str | None"]:
    """Split ``text`` at the bibliography heading.

    Returns ``(before, section)`` where ``before`` is everything before
    the heading and ``section`` runs from just after the heading to the
    next ``## `` heading or the end of the file. Returns ``(text, None)``
    when the document has no bibliography. Fenced code blocks are not
    content: headings inside them do not split.
    """
    masked = _mask_code(text)
    m = BIB_HEADING_RE.search(masked)
    if m is None:
        return text, None
    before = text[: m.start()]
    rest_at = m.end()
    nxt = NEXT_SECTION_RE.search(masked, rest_at)
    if nxt is None:
        return before, text[rest_at:]
    return before, text[rest_at : nxt.start()]


def body_before_bibliography(text: str) -> str:
    """The citation-density window: everything before the bibliography."""
    before, _rest = split_bibliography(text)
    return before


def reader_facing_text(text: str) -> str:
    """The whole document minus the bibliography section.

    Post-bibliography appendices are reader-facing and stay in scope —
    moving narration past the bibliography heading must not evade the
    internals gate or lose claims.
    """
    masked = _mask_code(text)
    m = BIB_HEADING_RE.search(masked)
    if m is None:
        return text
    before = text[: m.start()]
    rest_at = m.end()
    nxt = NEXT_SECTION_RE.search(masked, rest_at)
    if nxt is None:
        return before
    return before + text[nxt.start():]


def parse_entries(section_text: str) -> "list[tuple[int, str]]":
    """Parse bibliography entry lines from a bibliography section.

    An entry is a line starting ``[N]``, ``- [N]`` or ``* [N]``. Returns
    ``(number, rest_of_line)`` pairs in document order; the rest keeps
    the entry text after the ``[N]`` marker with surrounding space
    stripped. Non-entry lines (blank lines, ``###`` subsection notes) are
    skipped.
    """
    entries = []
    for line in section_text.splitlines():
        m = ENTRY_RE.match(line.strip())
        if m:
            entries.append((int(m.group(1)), m.group(2).strip()))
    return entries


def extract_citations(text: str) -> "list[int]":
    """Every cited number in document order, code excluded.

    Handles ``[1]``, ``[1, 2]`` and ``[1,2]``; numbers are capped at
    1-3 digits so bracketed years (``[2024]``) are not citations. Code
    spans and fenced code blocks are excluded first.
    """
    text = strip_code(text)
    numbers = []
    for group in CITATION_RE.findall(text):
        for n in group.split(","):
            numbers.append(int(n.strip()))
    return numbers


def count_refs(text: str) -> int:
    """Count refs in a sentence or window, both ``[1] [2]`` and ``[1, 2]``
    styles, with code excluded and the 1-3 digit cap applied."""
    return len(extract_citations(text))
