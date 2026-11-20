#!/usr/bin/env python3
"""
Citation Verification Script

Catches fabricated citations by checking:
1. DOI resolution (via doi.org)
2. Basic metadata matching (title similarity, year match)
3. URL accessibility verification
4. Hallucination pattern detection (generic titles, suspicious patterns)
5. Flags suspicious entries for manual review

The bibliography is found and parsed with the shared rule in
scripts/bibliography.py (E1-R1): the section starts at an exact
'## Bibliography' or '## Sources' line, ends at the next '## ' heading
only (a '###' subsection inside does not end it), and entries are
'[N]', '- [N]' or '* [N]' lines.

Usage:
    python3 verify_citations.py --report [path]
    python3 verify_citations.py --report [path] --strict

Exit codes:
    0  no suspicious citations and at least half the entries verified
       (with --strict: every entry verified by DOI or URL)
    1  any suspicious citation, fewer than half verified, no bibliography
       section or no parseable entries, unreadable report, or (with
       --strict) any entry that verified by neither DOI nor URL

Does NOT require API keys - uses free DOI resolver and heuristics.
"""

import sys
import argparse
import os
import re
from pathlib import Path
from typing import List, Dict, Tuple
from urllib import request, error
from urllib.parse import quote
import json
import time
from datetime import datetime

# Shared bibliography rule (E1-R1): this script must not keep its own
# split or entry regex. Imported after the scripts dir is guaranteed
# on sys.path (it is sys.path[0] when run as a script; tests insert it).
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from bibliography import parse_entries, split_bibliography

class CitationVerifier:
    """Verify citations in research report"""

    def __init__(self, report_path: Path, strict_mode: bool = False):
        self.report_path = report_path
        self.strict_mode = strict_mode
        self.content = self._read_report()
        self.suspicious = []
        self.verified = []
        self.errors = []

        # Hallucination detection patterns (2025 CiteGuard enhancement)
        self.suspicious_patterns = [
            # Generic academic-sounding but fake patterns
            (r'^(A |An |The )?(Study|Analysis|Review|Survey|Investigation) (of|on|into)',
             "Generic academic title pattern"),
            (r'^(Recent|Current|Modern|Contemporary) (Advances|Developments|Trends) in',
             "Generic 'advances' title pattern"),
            # Too perfect, templated titles
            (r'^[A-Z][a-z]+ [A-Z][a-z]+: A (Comprehensive|Complete|Systematic) (Review|Analysis|Guide)$',
             "Too perfect, templated structure"),
        ]

    def _read_report(self) -> str:
        """Read report file"""
        try:
            with open(self.report_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            print(f"L ERROR: Cannot read report: {e}")
            sys.exit(1)

    def extract_bibliography(self) -> List[Dict]:
        """Extract bibliography entries from the report.

        Boundaries and entry forms come from the shared rule in
        scripts/bibliography.py (E1-R1): the section starts at an exact
        '## Bibliography' or '## Sources' line, ends only at the next
        '## ' heading (a '###' subsection inside does not end it), and
        entries are '[N]', '- [N]' or '* [N]' lines. Non-entry lines in
        the section (blank lines, '###' notes) are skipped.
        """
        before, section = split_bibliography(self.content)

        if section is None:
            self.errors.append("No Bibliography section found")
            return []

        entries = []
        for num, rest in parse_entries(section):
            # Try to parse: Author (Year). "Title". Venue. URL
            year_match = re.search(r'\((\d{4})\)', rest)
            title_match = re.search(r'"([^"]+)"', rest)
            doi_match = re.search(r'doi\.org/(10\.\S+)', rest)
            url_match = re.search(r'https?://[^\s\)]+', rest)

            entries.append({
                'num': num,
                'raw': rest,
                'year': year_match.group(1) if year_match else None,
                'title': title_match.group(1) if title_match else None,
                'doi': doi_match.group(1) if doi_match else None,
                'url': url_match.group(0) if url_match else None
            })

        return entries

    def verify_doi(self, doi: str) -> Tuple[bool, Dict]:
        """
        Verify DOI exists and get metadata.
        Returns (success, metadata_dict)
        """
        if not doi:
            return False, {}

        try:
            # Use content negotiation to get JSON metadata
            url = f"https://doi.org/{quote(doi)}"
            req = request.Request(url)
            req.add_header('Accept', 'application/vnd.citationstyles.csl+json')

            with request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))

                return True, {
                    'title': data.get('title', ''),
                    'year': data.get('issued', {}).get('date-parts', [[None]])[0][0],
                    'authors': [
                        f"{a.get('family', '')} {a.get('given', '')}"
                        for a in data.get('author', [])
                    ],
                    'venue': data.get('container-title', '')
                }
        except error.HTTPError as e:
            if e.code == 404:
                return False, {'error': 'DOI not found (404)'}
            return False, {'error': f'HTTP {e.code}'}
        except Exception as e:
            return False, {'error': str(e)}

    def verify_url(self, url: str) -> Tuple[bool, str]:
        """
        Verify URL is accessible (2025 CiteGuard enhancement).
        Returns (accessible, status_message)
        """
        if not url:
            return False, "No URL"

        try:
            # HEAD request to check accessibility without downloading
            req = request.Request(url, method='HEAD')
            req.add_header('User-Agent', 'Mozilla/5.0 (Research Citation Verifier)')

            with request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    return True, "URL accessible"
                else:
                    return False, f"HTTP {response.status}"
        except error.HTTPError as e:
            return False, f"HTTP {e.code}"
        except error.URLError as e:
            return False, f"URL error: {e.reason}"
        except Exception as e:
            return False, f"Connection error: {str(e)[:50]}"

    def detect_hallucination_patterns(self, entry: Dict) -> List[str]:
        """
        Detect common LLM hallucination patterns in citations (2025 CiteGuard).
        Returns list of detected issues.
        """
        issues = []
        title = entry.get('title', '')

        if not title:
            return issues

        # Check against suspicious patterns
        for pattern, description in self.suspicious_patterns:
            if re.match(pattern, title, re.IGNORECASE):
                issues.append(f"Suspicious title pattern: {description}")

        # Check for overly generic titles
        generic_words = ['overview', 'introduction', 'guide', 'handbook', 'manual']
        if any(word in title.lower() for word in generic_words) and len(title.split()) < 5:
            issues.append("Very generic short title")

        # Check for placeholder-like titles
        if any(x in title.lower() for x in ['tbd', 'todo', 'placeholder', 'example']):
            issues.append("Placeholder text in title")

        # Check for inconsistent metadata
        if entry.get('year'):
            year = int(entry['year'])
            current_year = datetime.now().year
            # Very recent without DOI or URL is suspicious
            if year >= current_year - 1 and not entry.get('doi') and not entry.get('url'):
                issues.append(f"Recent year ({year}) with no verification method")
            # Future year is definitely wrong
            if year > current_year:
                issues.append(f"Future year: {year} (current: {current_year})")
            # Very old with modern phrasing is suspicious
            if year < 2000 and any(word in title.lower() for word in ['ai', 'llm', 'gpt', 'transformer']):
                issues.append(f"Anachronistic: pre-2000 ({year}) citation mentioning modern AI terms")

        return issues

    def check_title_similarity(self, title1: str, title2: str) -> float:
        """
        Simple title similarity check (word overlap).
        Returns score 0.0-1.0
        """
        if not title1 or not title2:
            return 0.0

        # Normalize: lowercase, remove punctuation, split
        def normalize(s):
            s = s.lower()
            s = re.sub(r'[^\w\s]', ' ', s)
            return set(s.split())

        words1 = normalize(title1)
        words2 = normalize(title2)

        if not words1 or not words2:
            return 0.0

        overlap = len(words1 & words2)
        total = len(words1 | words2)

        return overlap / total if total > 0 else 0.0

    def verify_entry(self, entry: Dict) -> Dict:
        """Verify a single bibliography entry (Enhanced 2025 with CiteGuard)"""
        result = {
            'num': entry['num'],
            'status': 'unknown',
            'issues': [],
            'metadata': {},
            'verification_methods': []
        }

        # STEP 1: Run hallucination detection (CiteGuard 2025)
        hallucination_issues = self.detect_hallucination_patterns(entry)
        if hallucination_issues:
            result['issues'].extend(hallucination_issues)
            result['status'] = 'suspicious'

        # STEP 2: Has DOI?
        if entry['doi']:
            print(f"  [{entry['num']}] Checking DOI {entry['doi']}...", end=' ')
            success, metadata = self.verify_doi(entry['doi'])

            if success:
                result['metadata'] = metadata
                result['status'] = 'verified'
                print("")

                # Check title similarity if we have both
                if entry['title'] and metadata.get('title'):
                    similarity = self.check_title_similarity(
                        entry['title'],
                        metadata['title']
                    )

                    if similarity < 0.5:
                        result['issues'].append(
                            f"Title mismatch (similarity: {similarity:.1%})"
                        )
                        result['status'] = 'suspicious'

                # Check year match
                if entry['year'] and metadata.get('year'):
                    if int(entry['year']) != int(metadata['year']):
                        result['issues'].append(
                            f"Year mismatch: report says {entry['year']}, DOI says {metadata['year']}"
                        )
                        result['status'] = 'suspicious'

            else:
                print(f"✗ {metadata.get('error', 'Failed')}")
                result['status'] = 'unverified'
                result['issues'].append(f"DOI resolution failed: {metadata.get('error', 'unknown')}")

        # STEP 3: Check URL accessibility (if no DOI or DOI failed)
        if entry['url'] and result['status'] != 'verified':
            url_ok, url_status = self.verify_url(entry['url'])
            if url_ok:
                result['verification_methods'].append('URL')
                # Upgrade status if URL verifies
                if result['status'] in ['unknown', 'no_doi', 'unverified']:
                    result['status'] = 'url_verified'
                print(f"  [{entry['num']}] URL accessible ✓")
            else:
                result['issues'].append(f"URL check failed: {url_status}")

        # STEP 4: Final fallback - no verification method
        if not entry['doi'] and not entry['url']:
            if 'No DOI provided' not in ' '.join(result['issues']):
                result['issues'].append("No DOI or URL - cannot verify")
            result['status'] = 'suspicious'

        return result

    def verify_all(self):
        """Verify all bibliography entries"""
        print(f"\n{'='*60}")
        print(f"CITATION VERIFICATION: {self.report_path.name}")
        print(f"{'='*60}\n")

        entries = self.extract_bibliography()

        if not entries:
            for e in self.errors or ["No bibliography entries found"]:
                print(f"L {e}")
            print()
            return False

        print(f"Found {len(entries)} citations\n")

        results = []
        for entry in entries:
            result = self.verify_entry(entry)
            results.append(result)

            # Rate limiting
            time.sleep(0.5)

        # Summarize
        print(f"\n{'='*60}")
        print(f"VERIFICATION SUMMARY")
        print(f"{'='*60}\n")

        verified = [r for r in results if r['status'] == 'verified']
        url_verified = [r for r in results if r['status'] == 'url_verified']
        suspicious = [r for r in results if r['status'] == 'suspicious']
        unverified = [r for r in results if r['status'] in ['unverified', 'no_doi', 'unknown']]

        print(f'DOI Verified: {len(verified)}/{len(results)}')
        print(f'URL Verified: {len(url_verified)}/{len(results)}')
        print(f'Suspicious: {len(suspicious)}/{len(results)}')
        print(f'Unverified: {len(unverified)}/{len(results)}')
        print()

        if suspicious:
            print('SUSPICIOUS CITATIONS (Manual Review Needed):')
            for r in suspicious:
                print(f"\n  [{r['num']}]")
                for issue in r['issues']:
                    print(f"    - {issue}")
            print()

        if unverified and len(unverified) > 0:
            print('UNVERIFIED CITATIONS (Could not check):')
            for r in unverified:
                print(f"  [{r['num']}] {r['issues'][0] if r['issues'] else 'Unknown'}")
            print()

        # Decision: the default run fails on any suspicious citation or
        # when fewer than half the entries verified (E1-R4). --strict
        # additionally fails when any entry verified by neither DOI nor
        # URL, i.e. it demands every entry verified.
        total_verified = len(verified) + len(url_verified)
        passed = True

        if suspicious:
            print('FAIL: Suspicious citations detected')
            passed = False

        if total_verified / len(results) < 0.5:
            print(f'FAIL: Less than 50% of citations verified '
                  f'({total_verified}/{len(results)})')
            passed = False

        if self.strict_mode and unverified:
            print('STRICT MODE: Unverified citations found')
            passed = False

        if passed:
            print('CITATION VERIFICATION PASSED')
        return passed


def main():
    parser = argparse.ArgumentParser(
        description="Verify citations in research report",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 verify_citations.py --report report.md

Note: Requires internet connection to check DOIs.
Uses free DOI resolver - no API key needed.
        """
    )

    parser.add_argument(
        '--report', '-r',
        type=str,
        required=True,
        help='Path to research report markdown file'
    )

    parser.add_argument(
        '--strict',
        action='store_true',
        help='Strict mode: additionally fail when any citation verified '
             'by neither DOI nor URL (default already fails on suspicious '
             'citations or fewer than half verified)'
    )

    args = parser.parse_args()
    report_path = Path(args.report)

    if not report_path.exists():
        print(f"ERROR: Report file not found: {report_path}")
        sys.exit(1)

    verifier = CitationVerifier(report_path, strict_mode=args.strict)
    passed = verifier.verify_all()

    sys.exit(0 if passed else 1)


if __name__ == '__main__':
    main()
