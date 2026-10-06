#!/usr/bin/env python3
"""
Report Validation Script
Ensures research reports meet quality standards before delivery
"""

import argparse
import re
import sys
from pathlib import Path
from typing import List, Tuple, Dict

# Per-format structure (mirrors references/report-templates/ and
# references/format-selection.md). Word ranges and source floors are
# guidance (warnings), section lists are gates.
FORMATS: Dict[str, dict] = {
    "comprehensive-report": {
        "required": [
            "Executive Summary", "Introduction", "Main Analysis",
            "Synthesis", "Limitations", "Recommendations",
            "Bibliography", "Methodology",
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
}
DEFAULT_FORMAT = "comprehensive-report"


class ReportValidator:
    """Validates research report quality"""

    def __init__(self, report_path: Path, fmt: str = DEFAULT_FORMAT):
        if fmt not in FORMATS:
            raise ValueError(
                f"Unknown format '{fmt}'. Choose from: {', '.join(FORMATS)}"
            )
        self.fmt = fmt
        self.spec = FORMATS[fmt]
        self.report_path = report_path
        self.content = self._read_report()
        self.errors: List[str] = []
        self.warnings: List[str] = []

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
            if not re.search(rf'##.*{section}', self.content, re.IGNORECASE):
                missing.append(section)

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
        """Check citation format and presence"""
        # Find all citation references [1], [2], etc.
        citations = re.findall(r'\[(\d+)\]', self.content)

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
        citation_nums = sorted([int(c) for c in unique_citations])
        if citation_nums:
            max_citation = max(citation_nums)
            expected = set(range(1, max_citation + 1))
            missing = expected - set(citation_nums)

            if missing:
                self.warnings.append(f"Non-consecutive citation numbers, missing: {sorted(missing)}")

        return True

    def _check_bibliography(self) -> bool:
        """Check bibliography exists, matches citations, and has no truncation placeholders"""
        pattern = r'## Bibliography(.*?)(?=##|\Z)'
        match = re.search(pattern, self.content, re.DOTALL | re.IGNORECASE)

        if not match:
            self.errors.append("Missing 'Bibliography' section")
            return False

        bib_section = match.group(1)

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
            if re.search(pattern_re, bib_section, re.IGNORECASE):
                self.errors.append(f"⚠️ CRITICAL: Bibliography contains truncation placeholder: {description}")
                self.errors.append(f"   This makes the report UNUSABLE - complete bibliography required")
                return False

        # Count bibliography entries [1], [2], etc. (list-marker form accepted)
        bib_entries = re.findall(r'^\s*[-*]?\s*\[(\d+)\]', bib_section, re.MULTILINE)

        if not bib_entries:
            self.errors.append("Bibliography has no entries")
            return False

        # Check citation number continuity (no gaps)
        bib_nums = sorted([int(n) for n in bib_entries])
        if bib_nums:
            expected = list(range(1, bib_nums[-1] + 1))
            actual = bib_nums
            missing = [n for n in expected if n not in actual]
            if missing:
                self.errors.append(f"Bibliography has gaps in numbering: missing {missing}")
                return False

        # Find citations in text
        text_citations = set(re.findall(r'\[(\d+)\]', self.content))
        bib_citations = set(bib_entries)

        # Check all citations have bibliography entries
        missing_in_bib = text_citations - bib_citations
        if missing_in_bib:
            self.errors.append(f"Citations missing from bibliography: {sorted(missing_in_bib)}")
            return False

        # Check for unused bibliography entries
        unused = bib_citations - text_citations
        if unused:
            self.warnings.append(f"Unused bibliography entries: {sorted(unused)}")

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
        pattern = r'## Bibliography(.*?)(?=##|\Z)'
        match = re.search(pattern, self.content, re.DOTALL | re.IGNORECASE)

        if not match:
            return True  # Already caught in bibliography check

        bib_section = match.group(1)
        bib_entries = re.findall(r'^\s*[-*]?\s*\[(\d+)\]', bib_section, re.MULTILINE)

        source_count = len(set(bib_entries))
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
  python validate_report.py --report report.md
  python validate_report.py -r ~/.claude/research_output/research_report_20251104_153045.md
        """
    )

    parser.add_argument(
        '--report', '-r',
        type=str,
        required=True,
        help='Path to research report markdown file'
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

    validator = ReportValidator(report_path, fmt=args.format)
    passed = validator.validate()

    sys.exit(0 if passed else 1)


if __name__ == '__main__':
    main()
