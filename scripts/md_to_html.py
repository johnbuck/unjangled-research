#!/usr/bin/env python3
"""
Markdown to HTML converter for research reports: converts markdown
sections to HTML while preserving structure and formatting. Report text
is html-escaped before any markdown rule runs, so the only live markup
in the output is the tags this converter generates (E2-R1); the
bibliography boundary and entries come from the shared helper
(bibliography.py), and a prose link renders as an https anchor or as
'text (URL)' plain text (E2-R3).

    python3 md_to_html.py <markdown_file>    # demo: prints a truncated conversion
"""

import re
import sys
from html import escape
from typing import Tuple
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from bibliography import parse_entries, reader_facing_text, split_bibliography


def convert_markdown_to_html(markdown_text: str) -> Tuple[str, str]:
    """
    Convert markdown to HTML in two parts: content and bibliography

    Args:
        markdown_text: Full markdown report text

    Returns:
        Tuple of (content_html, bibliography_html)
    """
    _, bib_section = split_bibliography(markdown_text)
    content_md = reader_facing_text(markdown_text)
    bibliography_md = bib_section or ""

    # Convert content (everything except bibliography)
    content_html = _convert_content_section(content_md)

    # Convert bibliography separately
    bibliography_html = _convert_bibliography_section(bibliography_md)

    return content_html, bibliography_html


def _convert_content_section(markdown: str) -> str:
    """Convert main content sections to HTML.

    Report text is html-escaped before any markdown rule runs, so the
    only live markup in the output is the tags this converter generates.
    """
    html = escape(markdown)

    # Remove title and front matter (first ## heading is handled separately)
    lines = html.split('\n')
    processed_lines = []
    skip_until_first_section = True

    for line in lines:
        # Skip everything until we hit "## Executive Summary" or first major section
        if skip_until_first_section:
            if line.startswith('## ') and not line.startswith('### '):
                skip_until_first_section = False
                processed_lines.append(line)
            continue
        processed_lines.append(line)

    html = '\n'.join(processed_lines)

    # Convert headers
    # ## Section Title → <div class="section"><h2 class="section-title">Section Title</h2></div>
    html = re.sub(
        r'^## (.+)$',
        r'<div class="section"><h2 class="section-title">\1</h2>',
        html,
        flags=re.MULTILINE
    )

    # ### Subsection → <h3 class="subsection-title">Subsection</h3>
    html = re.sub(
        r'^### (.+)$',
        r'<h3 class="subsection-title">\1</h3>',
        html,
        flags=re.MULTILINE
    )

    # #### Subsubsection → <h4 class="subsubsection-title">Title</h4>
    html = re.sub(
        r'^#### (.+)$',
        r'<h4 class="subsubsection-title">\1</h4>',
        html,
        flags=re.MULTILINE
    )

    # Inline rules: `code` spans, prose links, **bold**, *italic*.
    # Code spans and link targets are held out of the later rules, so a
    # link inside a code span stays literal and a `*` in a URL is kept
    # (E2-R3).
    html = _convert_inline(html)

    # Convert unordered lists
    html = _convert_lists(html)

    # Convert tables
    html = _convert_tables(html)

    # Convert paragraphs (wrap non-HTML lines in <p> tags)
    html = _convert_paragraphs(html)

    # Close all open sections
    html = _close_sections(html)

    # Wrap executive summary if present
    html = html.replace(
        '<h2 class="section-title">Executive Summary</h2>',
        '<div class="executive-summary"><h2 class="section-title">Executive Summary</h2>'
    )
    if '<div class="executive-summary">' in html:
        # Close executive summary at the next section
        html = html.replace(
            '</h2>\n<div class="section">',
            '</h2></div>\n<div class="section">',
            1
        )

    return html


def _convert_bibliography_section(markdown: str) -> str:
    """Convert bibliography section to HTML.

    Entries are found through the shared bibliography helper and their
    text escaped; the old `Title - URL` anchor shape is kept. Any other
    authored line in the section (a note, a `### Primary sources` label,
    a `- [Title](url)` link entry) is kept as an escaped paragraph, so no
    authored word is dropped; only blank lines and thematic rules are.
    """
    if not markdown.strip():
        return ""

    entries = []
    for line in markdown.splitlines():
        parsed = parse_entries(line)
        if not parsed:
            stripped = line.strip()
            if stripped and not re.fullmatch(r"(?:-{3,}|\*{3,}|_{3,})", stripped):
                entries.append(f'<p class="bib-note">{escape(stripped)}</p>')
            continue
        n, rest = parsed[0]
        text = escape(rest)
        m = re.match(r"(.+?)\s*-\s*(https?://[^\s\)]+)$", text)
        if m:
            entries.append(
                f'<div class="bib-entry"><span class="bib-number">[{n}]</span> '
                f'<a href="{m.group(2)}" target="_blank">{m.group(1)}</a></div>'
            )
        else:
            entries.append(
                f'<div class="bib-entry"><span class="bib-number">[{n}]</span> {text}</div>'
            )

    html = "\n".join(entries)
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
    return f'<div class="bibliography-content">{html}</div>'


_CODE_SPAN_RE = re.compile(r'`(.+?)`')
# Link target: no whitespace or pipe, with at most one level of balanced
# parentheses (`…/Foo_(bar)`); no held placeholder, so a code span inside
# a target leaves the link literal.
_LINK_RE = re.compile(
    r"\[([^\]|]+)\]\(((?:[^()\s|<]|\([^()\s|<]*\))+)\)"
)
# Placeholder for a held fragment. '<' never survives the escape pass as
# authored text, so only this converter can produce one.
_HOLD_RE = re.compile(r"<\x00(\d+)>")


def _convert_inline(html: str) -> str:
    """Inline rules on already-escaped text: code spans, then prose
    links, then bold and italic.

    A code span is held whole, so its text (a link, `*`) stays literal.
    Only an https:// target becomes an anchor (scheme case-insensitive,
    href keeps the escaped form it arrived in, so it is never escaped
    twice and no quote can break out of the attribute). Every other
    target — http:, javascript:, file:, data:, relative — renders as
    plain text with the URL in round brackets after it: no anchor, no raw
    markdown (E2-R3). Targets are held, so bold and italic never rewrite
    a URL. Text and URL never contain a pipe, so a link can never
    straddle the cell boundary of a pipe-delimited table row.
    """
    held = []

    def hold(fragment):
        held.append(fragment)
        return f"<\x00{len(held) - 1}>"

    html = _CODE_SPAN_RE.sub(lambda m: hold(f"<code>{m.group(1)}</code>"), html)

    def link(m):
        text, target = m.group(1), m.group(2)
        if target.lower().startswith("https://"):
            return f'<a href="{hold(target)}">{text}</a>'
        return f"{text} ({hold(target)})"

    html = _LINK_RE.sub(link, html)
    html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
    html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
    return _HOLD_RE.sub(lambda m: held[int(m.group(1))], html)


def _convert_lists(html: str) -> str:
    """Convert markdown lists to HTML lists"""
    lines = html.split('\n')
    result = []
    in_list = False
    list_level = 0

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Check for unordered list item
        if stripped.startswith('- ') or stripped.startswith('* '):
            if not in_list:
                result.append('<ul>')
                in_list = True
                list_level = len(line) - len(line.lstrip())

            # Get the content after the marker
            content = stripped[2:]
            result.append(f'<li>{content}</li>')

        # Check for ordered list item
        elif re.match(r'^\d+\.\s', stripped):
            if not in_list:
                result.append('<ol>')
                in_list = True
                list_level = len(line) - len(line.lstrip())

            # Get the content after the number and period
            content = re.sub(r'^\d+\.\s', '', stripped)
            result.append(f'<li>{content}</li>')

        else:
            # Not a list item
            if in_list:
                # Check if we're still in the list (indented continuation)
                current_level = len(line) - len(line.lstrip())
                if current_level > list_level and stripped:
                    # Continuation of previous list item
                    if result[-1].endswith('</li>'):
                        result[-1] = result[-1][:-5] + ' ' + stripped + '</li>'
                    continue
                else:
                    # End of list
                    result.append('</ul>' if '<ul>' in '\n'.join(result[-10:]) else '</ol>')
                    in_list = False
                    list_level = 0

            result.append(line)

    # Close any remaining open list
    if in_list:
        result.append('</ul>' if '<ul>' in '\n'.join(result[-10:]) else '</ol>')

    return '\n'.join(result)


_SEPARATOR_CELL_RE = re.compile(r":?-+:?")


def _is_separator_row(cells, header_cell_count):
    """True when the row is exactly the header's width and every cell is
    a strict separator cell: dashes with optional leading/trailing
    colons (`---`, `:--`, `--:`, `:--:`). A dash row of any other width
    is a data row (GFM delimiter rows match the header cell count)."""
    return (bool(cells) and len(cells) == header_cell_count
            and all(_SEPARATOR_CELL_RE.fullmatch(c) for c in cells))


def _convert_tables(html: str) -> str:
    """Convert markdown tables to HTML tables.

    Only the row directly after the header can be the separator, and
    only when it matches the strict separator pattern at the header's
    width. Data rows that contain `---` are kept as data rows (E2-R3).
    A row's trailing pipe is optional: the empty part it would leave is
    dropped only when the row ends with `|`, so `| a | b` keeps its last
    cell — and a separator written without its trailing pipe still has
    the header's width and separates."""
    lines = html.split('\n')
    result = []
    in_table = False
    next_row_is_separator = False
    header_cell_count = 0

    for i, line in enumerate(lines):
        stripped_row = line.strip()
        if '|' in stripped_row and stripped_row.startswith('|'):
            parts = line.split('|')[1:]
            if stripped_row.endswith('|'):
                parts = parts[:-1]
            cells = [cell.strip() for cell in parts]
            if not in_table:
                result.append('<table>')
                in_table = True
                # This is the header row
                result.append('<thead><tr>')
                for cell in cells:
                    result.append(f'<th>{cell}</th>')
                result.append('</tr></thead>')
                result.append('<tbody>')
                header_cell_count = len(cells)
                next_row_is_separator = True
            elif next_row_is_separator and _is_separator_row(cells, header_cell_count):
                # Drop the one real separator row
                next_row_is_separator = False
            else:
                next_row_is_separator = False
                # Data row
                result.append('<tr>')
                for cell in cells:
                    result.append(f'<td>{cell}</td>')
                result.append('</tr>')
        else:
            if in_table:
                result.append('</tbody></table>')
                in_table = False
            result.append(line)

    if in_table:
        result.append('</tbody></table>')

    return '\n'.join(result)


def _convert_paragraphs(html: str) -> str:
    """Wrap non-HTML lines in paragraph tags"""
    lines = html.split('\n')
    result = []
    in_paragraph = False

    for line in lines:
        stripped = line.strip()

        # Skip empty lines
        if not stripped:
            if in_paragraph:
                result.append('</p>')
                in_paragraph = False
            result.append(line)
            continue

        # Skip lines that are already HTML tags
        if (stripped.startswith('<') and stripped.endswith('>')) or \
           stripped.startswith('</') or \
           '<h' in stripped or '<div' in stripped or '<ul' in stripped or \
           '<ol' in stripped or '<li' in stripped or '<table' in stripped or \
           '</div>' in stripped or '</ul>' in stripped or '</ol>' in stripped:
            if in_paragraph:
                result.append('</p>')
                in_paragraph = False
            result.append(line)
            continue

        # Regular text line - wrap in paragraph
        if not in_paragraph:
            result.append('<p>' + line)
            in_paragraph = True
        else:
            result.append(line)

    if in_paragraph:
        result.append('</p>')

    return '\n'.join(result)


def _close_sections(html: str) -> str:
    """Close all open section divs"""
    # Count open and closed divs
    open_divs = html.count('<div class="section">')
    closed_divs = html.count('</div>')

    # Add closing divs for sections
    # Each section should be closed before the next section starts
    lines = html.split('\n')
    result = []
    section_open = False

    for i, line in enumerate(lines):
        if '<div class="section">' in line:
            if section_open:
                result.append('</div>')  # Close previous section
            section_open = True
        result.append(line)

    # Close final section if still open
    if section_open:
        result.append('</div>')

    return '\n'.join(result)


def main():
    """Demo the converter with a sample markdown file."""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python3 md_to_html.py <markdown_file>")
        sys.exit(1)

    md_file = Path(sys.argv[1])
    if not md_file.exists():
        print(f"Error: File {md_file} not found")
        sys.exit(1)

    markdown_text = md_file.read_text()
    content_html, bib_html = convert_markdown_to_html(markdown_text)

    print("=== CONTENT HTML ===")
    print(content_html[:1000])
    print("\n=== BIBLIOGRAPHY HTML ===")
    print(bib_html[:500])


if __name__ == "__main__":
    main()
