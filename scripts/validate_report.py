#!/usr/bin/env python3
"""
Report Validation Script
Ensures research reports meet quality standards before delivery

The bibliography rule (E1-R1) lives in scripts/bibliography.py: the split,
the entry forms and inline citation extraction are that shared rule, so a
'## Sources' section is a bibliography here too, and code spans, fenced
blocks and bracketed years ('[2024]') are never citations. Citations are
counted in the body only — reader_facing_text, so a citation in a
post-bibliography appendix still counts — and every bibliography entry
must be cited somewhere in the body (E1-R3). With --manifest, every
listed contested facet must be covered by the Perspectives/Debate
section's subsection headings or body text (E1-R2).

Exit codes: 0 pass (warnings allowed), 1 fail.
"""

import argparse
import os
import re
import sys
from pathlib import Path
from typing import List, Tuple, Dict

# Shared bibliography rule (E1-R1): this script must not keep its own
# split or citation regex. Imported after the scripts dir is guaranteed
# on sys.path (it is sys.path[0] when run as a script; tests insert it).
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from bibliography import (  # noqa: E402
    extract_citations,
    parse_entries,
    reader_facing_text,
    split_bibliography,
)

# A Perspectives/Debate section heading (level 2) contains one of these.
PERSPECTIVES_HEADING_RE = re.compile(
    r'(perspectiv|debate|contested|all[- ]sides|steelman)',
    re.IGNORECASE,
)

# Facet/heading normalization for the coverage check (own matcher; the
# renderer's _match_facets_to_children is epic 2's and its positional
# fallback would let any N subsections "cover" N facets).
_FACET_VS_RE = re.compile(r"\b(?:vs\.?|v\.)", re.IGNORECASE)
_FACET_PUNCT_RE = re.compile(r"[^\w\s]")


def _facet_tokens(text: str) -> List[str]:
    """Casefold, vs./vs/v. to 'versus', strip punctuation, tokenize."""
    text = _FACET_VS_RE.sub(" versus ", text.casefold())
    return _FACET_PUNCT_RE.sub(" ", text).split()


_FACET_GLOSS_RE = re.compile(r"\([^()]*\)")

# An explicit ordinal label: '### Facet 2: ...' covers the second listed
# facet. An author's stated claim, not a positional guess — unlabelled
# subsections never cover a facet by their order.
_FACET_LABEL_RE = re.compile(r"^\s*facet\s*#?\s*(\d+)\b", re.IGNORECASE)


def _facet_short_name(facet: str) -> str:
    """The facet's name: parenthetical glosses dropped (they frame the
    sides, '(issue-volume vs criterion-coverage framings)'), then the text
    before its first colon or question mark, when present — 'Alpha vs.
    beta: does...' compares as 'Alpha versus beta'."""
    text = _FACET_GLOSS_RE.sub(" ", facet)
    head = re.split(r"[:?]", text, maxsplit=1)[0].strip()
    return head or text.strip() or facet

# Per-format structure (mirrors references/report-templates/ and
# references/format-selection.md). Word ranges and source floors are
# guidance (warnings), section lists are gates. A required entry may list
# alternatives separated by "|"; comprehensive-report accepts the headings
# of both templates/report_template.md and
# references/report-templates/comprehensive-report.md.
FORMATS: Dict[str, dict] = {
    "comprehensive-report": {
        "required": [
            "Executive Summary", "Introduction|Background",
            "Main Analysis|Key Findings", "Synthesis|Implications",
            "Limitations", "Recommendations", "Bibliography", "Methodology",
        ],
        "recommended": ["Counterevidence Register", "Claims-Evidence Table"],
        "summary_section": "Executive Summary",
        "summary_bounds": (50, 400),
        "word_range": (1500, None),
        "min_sources": 10,
    },
    "research-summary": {
        "required": [
            "Executive Summary", "Key Findings", "Detailed Analysis",
            "Conclusions", "Next Steps", "Bibliography",
        ],
        "recommended": [],
        "summary_section": "Executive Summary",
        "summary_bounds": (50, 400),
        "word_range": (500, 1000),
        "min_sources": 5,
    },
    "comparison": {
        "required": [
            "Overview", "Comparison Matrix", "Detailed Analysis",
            "Recommendation", "Bibliography",
        ],
        "recommended": [],
        "summary_section": "Overview",
        "summary_bounds": (30, 300),
        "word_range": (800, 1200),
        "min_sources": 6,
    },
    "quick-brief": {
        "required": ["Summary", "Key Points", "Action Items", "Bibliography"],
        "recommended": [],
        "summary_section": None,  # the Summary IS the report
        "summary_bounds": None,
        "word_range": (200, 400),
        "min_sources": 3,
    },
    "discovery-catalog": {
        "required": [
            "Summary", "Selection Criteria", "Comparison Matrix",
            "Project Dossiers", "Sources Consulted", "Bibliography",
        ],
        # Model Addenda is models-only and Freshness is a banner line, not a
        # section — both conditional per the template, so neither is warned.
        "recommended": [],
        "summary_section": "Summary",
        "summary_bounds": (30, 300),
        "word_range": (800, 1500),
        "min_sources": 8,
    },
}
DEFAULT_FORMAT = "comprehensive-report"


class ReportValidator:
    """Validates research report quality"""

    def __init__(self, report_path: Path, fmt: str = DEFAULT_FORMAT,
                 manifest_path: Path = None):
        if fmt not in FORMATS:
            raise ValueError(
                f"Unknown format '{fmt}'. Choose from: {', '.join(FORMATS)}"
            )
        self.fmt = fmt
        self.spec = FORMATS[fmt]
        self.report_path = report_path
        self.content = self._read_report()
        self.manifest_path = manifest_path
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def _perspectives_section(self) -> Tuple["str | None", List[str]]:
        """(section_text, subsection_headings) of the first Perspectives/
        Debate section, or (None, []) when the report has none.

        The section runs from its '## ' heading to the next '## ' heading.
        Subsection ('### ') headings inside it are the facet candidates.
        A heading inside a fenced code block is not a heading.
        """
        lines = self.content.splitlines()
        headings = []  # (level, text, line index)
        in_fence = False
        for idx, line in enumerate(lines):
            stripped = line.lstrip()
            if stripped.startswith("```") or stripped.startswith("~~~"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            m = re.match(r"^(#{1,6})[ \t]+(.*)$", line.rstrip())
            if m:
                headings.append((len(m.group(1)), m.group(2).strip(), idx))
        for level, text, idx in headings:
            if level != 2 or not PERSPECTIVES_HEADING_RE.search(text):
                continue
            end = len(lines)
            for lvl2, _t, i2 in headings:
                if i2 > idx and lvl2 <= 2:
                    end = i2
                    break
            subs = [t for lvl, t, i in headings if idx < i < end and lvl == 3]
            return "\n".join(lines[idx + 1:end]), subs
        return None, []

    @staticmethod
    def _uncovered_facets(facets: List[str], section_text: str,
                          subsection_headings: List[str]) -> List[str]:
        """The listed facets the Perspectives section does not cover.

        A facet is covered by a '###' subsection heading that either
        carries the explicit label 'Facet N' (N = the facet's 1-based
        position in the manifest list) or shares >= 0.6 of the facet's
        short-name tokens. Each heading covers at most one facet (docs:
        one subsection per listed facet), matched best score first, so
        one 'impact on consumers' heading cannot also cover 'impact on
        workers'. A facet with no heading is still covered when its
        normalized short name appears as a contiguous run of whole tokens
        in the section text. No positional fallback: N unlabelled,
        unrelated subsections never 'cover' N facets (E1-R2)."""
        covered = set()
        taken = set()
        for hi, heading in enumerate(subsection_headings):
            m = _FACET_LABEL_RE.match(heading)
            if m and 1 <= int(m.group(1)) <= len(facets):
                fi = int(m.group(1)) - 1
                if fi not in covered:
                    covered.add(fi)
                    taken.add(hi)
        f_tokens = [_facet_tokens(_facet_short_name(f)) for f in facets]
        pairs = []
        for fi, ft in enumerate(f_tokens):
            if fi in covered or not ft:
                continue
            for hi, heading in enumerate(subsection_headings):
                if hi in taken:
                    continue
                h_tokens = set(_facet_tokens(heading))
                score = len(set(ft) & h_tokens) / len(set(ft))
                if score >= 0.6:
                    pairs.append((-score, fi, hi))
        for _neg, fi, hi in sorted(pairs):
            if fi not in covered and hi not in taken:
                covered.add(fi)
                taken.add(hi)
        # Contiguous run of whole tokens, never a character substring
        # ("screen timeout" does not cover the facet "screen time").
        tokens = _facet_tokens(section_text)
        uncovered = []
        for fi, ft in enumerate(f_tokens):
            if fi in covered:
                continue
            n = len(ft)
            if not (ft and any(tokens[i:i + n] == ft
                               for i in range(len(tokens) - n + 1))):
                uncovered.append(facets[fi])
        return uncovered

    def _check_contested_facets(self) -> bool:
        """Listed contested facets must be covered by a
        Perspectives/Debate section (validator half of the gate)."""
        if not self.manifest_path:
            return True  # no manifest supplied -> gate not in scope
        import json as _json
        try:
            manifest = _json.load(open(self.manifest_path))
        except Exception as e:
            self.errors.append(f"Cannot read manifest: {e}")
            return False
        facets = manifest.get("contested_facets") or []
        if not facets:
            return True
        section_text, subs = self._perspectives_section()
        if section_text is None:
            self.errors.append(
                f"Manifest lists contested_facets ({len(facets)}) but the "
                f"report has no Perspectives/Debate section covering them"
                f": {facets}"
            )
            return False
        uncovered = self._uncovered_facets(facets, section_text, subs)
        if uncovered:
            self.errors.append(
                "Perspectives section does not cover listed contested "
                "facets: " + "; ".join(uncovered)
            )
            self.errors.append(
                "   Give each facet its own '### ' subsection named after "
                "it, or labelled '### Facet N: ...' in manifest order"
            )
            return False
        return True

    def _read_report(self) -> str:
        """Read report file"""
        try:
            with open(self.report_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            print(f"❌ ERROR: Cannot read report: {e}")
            sys.exit(1)

    def validate(self) -> bool:
        """Run all validation checks"""
        print(f"\n{'='*60}")
        print(f"VALIDATING REPORT: {self.report_path.name}")
        print(f"{'='*60}\n")

        checks = [
            ("Executive Summary", self._check_executive_summary),
            ("Required Sections", self._check_required_sections),
            ("Citations", self._check_citations),
            ("Bibliography", self._check_bibliography),
            ("Placeholder Text", self._check_placeholders),
            ("Content Truncation", self._check_content_truncation),
            ("Word Count", self._check_word_count),
            ("Source Count", self._check_source_count),
            ("Broken Links", self._check_broken_references),
            ("Contested Facets", self._check_contested_facets),
        ]

        for check_name, check_func in checks:
            print(f"⏳ Checking: {check_name}...", end=" ")
            passed = check_func()
            if passed:
                print("✅ PASS")
            else:
                print("❌ FAIL")

        self._print_summary()

        return len(self.errors) == 0

    def _check_executive_summary(self) -> bool:
        """Check the format's summary section exists and is within bounds"""
        section = self.spec["summary_section"]
        if section is None:
            return True  # quick-brief: no separate summary section
        pattern = rf'## {section}(.*?)(?=##|\Z)'
        match = re.search(pattern, self.content, re.DOTALL | re.IGNORECASE)

        if not match:
            self.errors.append(f"Missing '{section}' section")
            return False

        summary = match.group(1).strip()
        word_count = len(summary.split())
        lo, hi = self.spec["summary_bounds"]

        if hi and word_count > hi:
            self.warnings.append(f"{section} too long: {word_count} words (should be ≤{hi})")

        if word_count < lo:
            self.warnings.append(f"{section} too short: {word_count} words (should be ≥{lo})")

        return True

    def _check_required_sections(self) -> bool:
        """Check all format-required sections are present"""
        required = self.spec["required"]
        recommended = self.spec["recommended"]

        missing = []
        for section in required:
            if not re.search(rf'##.*(?:{section})', self.content, re.IGNORECASE):
                missing.append(section.replace("|", " or "))

        if missing:
            self.errors.append(f"Missing sections: {', '.join(missing)}")
            return False

        # Check recommended sections (warnings only)
        missing_recommended = []
        for section in recommended:
            if not re.search(rf'##.*{section}', self.content, re.IGNORECASE):
                missing_recommended.append(section)

        if missing_recommended:
            self.warnings.append(f"Missing recommended sections (for academic rigor): {', '.join(missing_recommended)}")

        return True

    def _check_citations(self) -> bool:
        """Check citation format and presence.

        Citations come from the body only (reader_facing_text: the
        bibliography section is out, post-bibliography appendices stay
        in), via the shared rule — code excluded, '[2024]' is not a
        citation."""
        citations = extract_citations(reader_facing_text(self.content))

        if not citations:
            self.errors.append("No citations found in report")
            return False

        unique_citations = set(citations)

        if len(unique_citations) < self.spec["min_sources"]:
            self.warnings.append(
                f"Only {len(unique_citations)} unique sources cited for "
                f"{self.fmt} (recommended: ≥{self.spec['min_sources']})"
            )

        # Check for consecutive citation numbers
        citation_nums = sorted(unique_citations)
        if citation_nums:
            max_citation = max(citation_nums)
            expected = set(range(1, max_citation + 1))
            missing = expected - set(citation_nums)

            if missing:
                self.warnings.append(f"Non-consecutive citation numbers, missing: {sorted(missing)}")

        return True

    def _check_bibliography(self) -> bool:
        """Check bibliography exists, matches citations, and has no truncation placeholders.

        Split, entries and citations follow the shared rule (E1-R1):
        '## Bibliography' or '## Sources' starts the section, only a '## '
        heading ends it, and entries are '[N]', '- [N]' or '* [N]' lines.
        Every entry must be cited in the body (E1-R3)."""
        _before, section = split_bibliography(self.content)

        if section is None:
            self.errors.append("Missing 'Bibliography' section")
            return False

        # CRITICAL: Check for truncation placeholders (2025 CiteGuard enhancement)
        truncation_patterns = [
            (r'\[\d+-\d+\]', 'Citation range (e.g., [8-75])'),
            (r'Additional.*citations', 'Phrase "Additional citations"'),
            (r'would be included', 'Phrase "would be included"'),
            (r'\[\.\.\.continue', 'Pattern "[...continue"'),
            (r'\[Continue with', 'Pattern "[Continue with"'),
            (r'etc\.(?!\w)', 'Standalone "etc."'),
            (r'and so on', 'Phrase "and so on"'),
        ]

        for pattern_re, description in truncation_patterns:
            if re.search(pattern_re, section, re.IGNORECASE):
                self.errors.append(f"⚠️ CRITICAL: Bibliography contains truncation placeholder: {description}")
                self.errors.append(f"   This makes the report UNUSABLE - complete bibliography required")
                return False

        entries = parse_entries(section)

        if not entries:
            self.errors.append("Bibliography has no entries")
            return False

        # Check citation number continuity (no gaps)
        bib_nums = sorted(n for n, _rest in entries)
        if bib_nums:
            expected = list(range(1, bib_nums[-1] + 1))
            actual = bib_nums
            missing = [n for n in expected if n not in actual]
            if missing:
                self.errors.append(f"Bibliography has gaps in numbering: missing {missing}")
                return False

        # Find citations in the body (reader-facing text, appendices kept)
        body_citations = set(extract_citations(reader_facing_text(self.content)))
        bib_citations = set(bib_nums)

        # Check all citations have bibliography entries
        missing_in_bib = body_citations - bib_citations
        if missing_in_bib:
            self.errors.append(f"Citations missing from bibliography: {sorted(missing_in_bib)}")
            return False

        # Every bibliography entry must be cited in the body (E1-R3)
        uncited = bib_citations - body_citations
        if uncited:
            self.errors.append(
                "Uncited bibliography entries (never cited in the body): "
                + ", ".join(f"[{n}]" for n in sorted(uncited))
            )
            return False

        return True

    def _check_placeholders(self) -> bool:
        """Check for placeholder text that shouldn't be in final report"""
        placeholders = [
            'TBD', 'TODO', 'FIXME', 'XXX',
            '[citation needed]', '[needs citation]',
            '[placeholder]', '[TODO]', '[TBD]'
        ]

        found_placeholders = []
        for placeholder in placeholders:
            if placeholder in self.content:
                found_placeholders.append(placeholder)

        if found_placeholders:
            self.errors.append(f"Found placeholder text: {', '.join(found_placeholders)}")
            return False

        return True

    def _check_content_truncation(self) -> bool:
        """Check for content truncation patterns (2025 Progressive Assembly enhancement)"""
        truncation_patterns = [
            (r'Content continues', 'Phrase "Content continues"'),
            (r'Due to length', 'Phrase "Due to length"'),
            (r'would continue', 'Phrase "would continue"'),
            (r'\[Sections \d+-\d+', 'Pattern "[Sections X-Y"'),
            (r'Additional sections', 'Phrase "Additional sections"'),
            (r'comprehensive.*word document that continues', 'Pattern "comprehensive...document that continues"'),
        ]

        for pattern_re, description in truncation_patterns:
            if re.search(pattern_re, self.content, re.IGNORECASE):
                self.errors.append(f"⚠️ CRITICAL: Content truncation detected: {description}")
                self.errors.append(f"   Report is INCOMPLETE and UNUSABLE - regenerate with progressive assembly")
                return False

        return True

    def _check_word_count(self) -> bool:
        """Check overall report length against the format's target range"""
        word_count = len(self.content.split())
        lo, hi = self.spec["word_range"]

        if word_count < lo * 0.6:
            self.warnings.append(
                f"Report is very short for {self.fmt}: {word_count} words "
                f"(target ≥{lo})"
            )
        if hi and word_count > hi * 2.0:
            self.warnings.append(
                f"Report is very long for {self.fmt}: {word_count} words "
                f"(target ≤{hi})"
            )

        return True

    def _check_source_count(self) -> bool:
        """Check minimum source count"""
        _before, section = split_bibliography(self.content)

        if section is None:
            return True  # Already caught in bibliography check

        source_count = len({n for n, _rest in parse_entries(section)})
        floor = self.spec["min_sources"]

        if source_count < floor:
            self.warnings.append(
                f"Only {source_count} sources for {self.fmt} "
                f"(recommended: ≥{floor})"
            )

        return True

    def _check_broken_references(self) -> bool:
        """Check for broken internal references"""
        # Find all markdown links [text](./path)
        internal_links = re.findall(r'\[.*?\]\((\.\/.*?)\)', self.content)

        broken = []
        for link in internal_links:
            # Remove anchor if present
            link_path = link.split('#')[0]
            full_path = self.report_path.parent / link_path

            if not full_path.exists():
                broken.append(link)

        if broken:
            self.errors.append(f"Broken internal links: {', '.join(broken)}")
            return False

        return True

    def _print_summary(self):
        """Print validation summary"""
        print(f"\n{'='*60}")
        print(f"VALIDATION SUMMARY")
        print(f"{'='*60}\n")

        if self.errors:
            print(f"❌ ERRORS ({len(self.errors)}):")
            for error in self.errors:
                print(f"   • {error}")
            print()

        if self.warnings:
            print(f"⚠️  WARNINGS ({len(self.warnings)}):")
            for warning in self.warnings:
                print(f"   • {warning}")
            print()

        if not self.errors and not self.warnings:
            print("✅ ALL CHECKS PASSED - Report meets quality standards!\n")
        elif not self.errors:
            print("✅ VALIDATION PASSED (with warnings)\n")
        else:
            print("❌ VALIDATION FAILED - Please fix errors before delivery\n")


def main():
    parser = argparse.ArgumentParser(
        description="Validate research report quality",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 validate_report.py --report <run_dir>/report.md --format quick-brief
  python3 validate_report.py --report <run_dir>/report.md --manifest <run_dir>/run_manifest.json
        """
    )

    parser.add_argument(
        '--report', '-r',
        type=str,
        required=True,
        help='Path to research report markdown file'
    )

    parser.add_argument(
        '--manifest', '-m',
        type=str,
        default=None,
        help='Path to run_manifest.json — enables the contested-facets gate'
    )

    parser.add_argument(
        '--format', '-f',
        type=str,
        default=DEFAULT_FORMAT,
        choices=sorted(FORMATS.keys()),
        help=(
            'Report format the writer used (from format-selection.md). '
            'Each format has its own required sections, word targets, and '
            f'source floors. Default: {DEFAULT_FORMAT}.'
        )
    )

    args = parser.parse_args()

    report_path = Path(args.report)

    if not report_path.exists():
        print(f"❌ ERROR: Report file not found: {report_path}")
        sys.exit(1)

    manifest_path = Path(args.manifest) if args.manifest else None
    if manifest_path is not None and not manifest_path.exists():
        print(f"❌ ERROR: Manifest file not found: {manifest_path}")
        sys.exit(1)
    validator = ReportValidator(report_path, fmt=args.format, manifest_path=manifest_path)
    passed = validator.validate()

    sys.exit(0 if passed else 1)


if __name__ == '__main__':
    main()
