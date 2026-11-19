#!/usr/bin/env python3
"""
Source Credibility Evaluator
Assesses source quality, credibility, and potential biases.

CLI
---
Score one source (one JSON score object on stdout, exit 0):

    python3 scripts/source_evaluator.py --url URL [--title TITLE] [--date DATE]

--date takes the source.schema.json published_at form: YYYY, YYYY-MM,
YYYY-MM-DD or YYYY-MM-DDTHH:MM[:SS[.fff]][Z|+HH:MM]. It is parsed at the
earliest instant of its stated precision; a naive timestamp is taken as
UTC. A --date value violating the schema pattern exits 1 with
{"error": ...} on stderr naming the --date flag.

Score every row of a run's sources.jsonl (one JSON object on stdout,
exit 0):

    python3 scripts/source_evaluator.py --dir RUN_DIR

Rows are scored by raw_url, falling back to canonical_locator (doi:
locators resolve through DOI_PUBLISHER_MAP). published_at is used when
present; null falls back to a 4-digit year ("2024" or 2024); otherwise
the date is unknown and recency scores 50.0. registered_at is never used.

Score object shape (--url prints it with source_id null):

    {"source_id", "url", "title", "domain", "overall_score",
     "domain_authority", "recency", "expertise", "bias_score",
     "factors", "recommendation"}

--dir shape:

    {"dir", "count", "average_overall", "sources": [<score objects>],
     "defects": [{"line", "source_id", "field", "error", "action"}]}

count and average_overall cover the scored rows. A row defect never
stops the run: a schema-invalid title, authors or published_at is
treated as absent (action "scored_without_field"; a bad published_at
falls back to year), and a line that is not a JSON object or has no
URL is left out (action "skipped"). Any defect also prints one
{"error": ..., "defects": [...]} object on stderr naming each
source_id or line, and makes the exit code 1.

--title and --date apply only with --url; passing either with --dir is a
usage error (exit 2), including an explicitly passed empty --title ''.

Exit codes: 0 scored, no defects; 1 runtime defect with {"error": ...}
on stderr -- a malformed --date or a missing sources.jsonl (nothing on
stdout), or one or more row defects (stdout still carries every scored
row); 2 usage.

Domain matching uses registrable-domain suffixes everywhere:
domain == known or domain.endswith('.' + known). So nature.com matches
sub.nature.com, but never notnature.com or nature.com.evil.com.
"""

from dataclasses import dataclass
from typing import Dict, Optional
from urllib.parse import urlparse
from datetime import datetime, timedelta, timezone
import argparse
import json
import os
import re
import sys


@dataclass
class CredibilityScore:
    """Represents source credibility assessment"""
    overall_score: float  # 0-100
    domain_authority: float  # 0-100
    recency: float  # 0-100
    expertise: float  # 0-100
    bias_score: float  # 0-100 (higher = more neutral)
    factors: Dict[str, str]
    recommendation: str  # "high_trust", "moderate_trust", "low_trust", "verify"


# source.schema.json published_at pattern: YYYY, YYYY-MM, YYYY-MM-DD, or
# YYYY-MM-DDTHH:MM[:SS[.fff]][Z|+HH:MM]. [0-9] (not \d) keeps it ASCII,
# like the ECMA regex the schema runs.
PUBLISHED_AT_PATTERN = re.compile(
    r'^(?P<year>[0-9]{4})'
    r'(?:-(?P<month>0[1-9]|1[0-2])'
    r'(?:-(?P<day>0[1-9]|[12][0-9]|3[01])'
    r'(?:T(?P<hour>[01][0-9]|2[0-3]):(?P<minute>[0-5][0-9])'
    r'(?::(?P<second>[0-5][0-9])(?:\.(?P<fraction>[0-9]+))?)?'
    r'(?P<offset>Z|[+-][0-9]{2}:[0-9]{2})?)?)?)?$'
)


def parse_published_at(value: str) -> datetime:
    """Parse a published_at string at the earliest instant of its stated
    precision ('2024' -> 2024-01-01T00:00Z, '2024-06' -> June 1st), as an
    aware UTC datetime (naive timestamps are taken as UTC). Raises
    ValueError for values the source.schema.json pattern rejects or that
    are not real calendar dates."""
    if not isinstance(value, str) or not PUBLISHED_AT_PATTERN.fullmatch(value):
        raise ValueError(
            f'malformed published_at {value!r}: must match the '
            'source.schema.json pattern YYYY, YYYY-MM, YYYY-MM-DD or '
            'YYYY-MM-DDTHH:MM[:SS[.fff]][Z|+HH:MM]'
        )
    m = PUBLISHED_AT_PATTERN.fullmatch(value)
    offset = m.group('offset')
    if offset and offset != 'Z':
        offset_hours = int(offset[1:3])
        offset_minutes = int(offset[4:6])
        if offset_hours > 23 or offset_minutes > 59:
            raise ValueError(
                f'malformed published_at {value!r}: invalid UTC offset')
    try:
        if offset == 'Z':
            tz = timezone.utc
        elif offset:
            sign = 1 if offset[0] == '+' else -1
            tz = timezone(sign * timedelta(
                hours=int(offset[1:3]), minutes=int(offset[4:6])))
        else:
            tz = timezone.utc
        micro = int((m.group('fraction') or '0').ljust(6, '0')[:6])
        parsed = datetime(
            int(m.group('year')), int(m.group('month') or 1),
            int(m.group('day') or 1), int(m.group('hour') or 0),
            int(m.group('minute') or 0), int(m.group('second') or 0),
            micro, tzinfo=tz,
        )
    except ValueError:
        raise ValueError(
            f'malformed published_at {value!r}: not a real calendar date'
        ) from None
    return parsed.astimezone(timezone.utc)


class SourceEvaluator:
    """Evaluates source credibility and quality"""

    # Domain reputation tiers
    HIGH_AUTHORITY_DOMAINS = {
        # Academic & Research
        'arxiv.org', 'nature.com', 'science.org', 'cell.com', 'nejm.org',
        'thelancet.com', 'springer.com', 'sciencedirect.com', 'plos.org',
        'ieee.org', 'acm.org', 'pubmed.ncbi.nlm.nih.gov',

        # Government & International Organizations
        'nih.gov', 'cdc.gov', 'who.int', 'fda.gov', 'nasa.gov',
        'gov.uk', 'europa.eu', 'un.org',

        # Established Tech Documentation
        'docs.python.org', 'developer.mozilla.org', 'docs.microsoft.com',
        'cloud.google.com', 'aws.amazon.com', 'kubernetes.io',

        # Reputable News (Fact-check verified)
        'reuters.com', 'apnews.com', 'bbc.com', 'economist.com',
        'scientificamerican.com',

        # Education & Social Science Research
        'eric.ed.gov', 'ed.gov', 'tandfonline.com', 'wiley.com',
        'sagepub.com', 'cambridge.org', 'jstor.org', 'ox.ac.uk',
        'harvard.edu', 'stanford.edu', 'apa.org', 'aera.net',

        # Education Organizations & Policy
        'ascd.org', 'casei.org', 'naeyc.org',
        'learningpolicyinstitute.org', 'oecd.org', 'unesco.org',
        'rand.org',

        # Humanities & Social Science Journals
        'muse.jhu.edu', 'tandf.co.uk', 'link.springer.com',
        'onlinelibrary.wiley.com', 'journals.sagepub.com'
    }

    MODERATE_AUTHORITY_DOMAINS = {
        # Tech News & Analysis
        'techcrunch.com', 'theverge.com', 'arstechnica.com', 'wired.com',
        'zdnet.com', 'cnet.com',

        # Industry Publications
        'forbes.com', 'bloomberg.com', 'wsj.com', 'ft.com',

        # Educational
        'wikipedia.org', 'britannica.com', 'khanacademy.org',

        # Tech Blogs (established)
        'medium.com', 'dev.to', 'stackoverflow.com', 'github.com'
    }

    LOW_AUTHORITY_INDICATORS = [
        'blogspot.com', 'wordpress.com', 'wix.com', 'substack.com'
    ]

    # Registrable domains for the expertise/bias bonuses (suffix matched).
    # sciencedirect.com (Elsevier, the 10.1016 DOI target) and
    # sciencemag.org (Science's former domain) are listed by name: the old
    # 'science' substring rule gave them the bonus, and suffix matching
    # must not take it away from genuine journals.
    ACADEMIC_EXPERTISE_DOMAINS = (
        'arxiv.org', 'nature.com', 'science.org', 'sciencemag.org',
        'sciencedirect.com', 'ieee.org', 'acm.org'
    )
    ACADEMIC_BIAS_DOMAINS = (
        'arxiv.org', 'nature.com', 'science.org', 'sciencemag.org',
        'sciencedirect.com', 'ieee.org'
    )

    # Government suffixes for the expertise bonus (suffix matched): the
    # .gov TLD plus the government-reserved second levels of common
    # country TLDs, which the old '.gov' substring rule also rewarded.
    # gov.evil.com never matches: evil.com is not in this list.
    GOVERNMENT_SUFFIXES = (
        'gov', 'gov.uk', 'gov.au', 'gov.nz', 'gov.in', 'gov.sg',
        'gov.za', 'gov.ie', 'gov.br', 'gov.hk', 'who.int'
    )

    def __init__(self):
        pass

    def evaluate_source(
        self,
        url: str,
        title: str,
        content: Optional[str] = None,
        publication_date: Optional[str] = None,
        author: Optional[str] = None
    ) -> CredibilityScore:
        """Evaluate source credibility. Raises ValueError when
        publication_date violates the source.schema.json pattern."""

        domain = self._extract_domain(url)

        # Calculate component scores
        domain_score = self._evaluate_domain_authority(domain)
        recency_score = self._evaluate_recency(publication_date)
        expertise_score = self._evaluate_expertise(domain, title, author)
        bias_score = self._evaluate_bias(domain, title, content)

        # Calculate overall score (weighted average)
        overall = (
            domain_score * 0.35 +
            recency_score * 0.20 +
            expertise_score * 0.25 +
            bias_score * 0.20
        )

        # Determine factors
        factors = self._identify_factors(
            domain, domain_score, recency_score, expertise_score, bias_score
        )

        # Generate recommendation
        recommendation = self._generate_recommendation(overall)

        return CredibilityScore(
            overall_score=round(overall, 2),
            domain_authority=round(domain_score, 2),
            recency=round(recency_score, 2),
            expertise=round(expertise_score, 2),
            bias_score=round(bias_score, 2),
            factors=factors,
            recommendation=recommendation
        )

    # DOI prefix -> publisher domain mapping (common academic publishers)
    DOI_PUBLISHER_MAP = {
        '10.1037': 'apa.org',        # American Psychological Association
        '10.3102': 'aera.net',       # American Educational Research Association
        '10.1080': 'tandfonline.com',# Taylor & Francis (education, humanities)
        '10.1007': 'springer.com',   # Springer
        '10.1111': 'wiley.com',      # Wiley-Blackwell
        '10.1016': 'sciencedirect.com', # Elsevier
        '10.1177': 'sagepub.com',    # SAGE Publications
        '10.2307': 'jstor.org',      # JSTOR
        '10.1017': 'cambridge.org',  # Cambridge University Press
        '10.1093': 'oxfordacademic.com', # Oxford Academic
    }

    @staticmethod
    def _domain_matches(domain: str, known: str) -> bool:
        """Registrable-domain suffix match: domain is known or a subdomain
        of known. 'nature.com' matches 'sub.nature.com' but never
        'notnature.com' or 'nature.com.evil.com'."""
        return domain == known or domain.endswith('.' + known)

    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL. Strips only a leading 'www.' and uses
        the hostname (no :port). Resolves doi: locators and doi.org URLs
        to the publisher's domain via DOI_PUBLISHER_MAP."""
        parsed = urlparse(url or '')

        # DOI locator: doi:10.1037/... -> publisher domain
        if parsed.scheme.lower() == 'doi':
            path = (parsed.path or '').strip('/')
            for prefix, pub_domain in self.DOI_PUBLISHER_MAP.items():
                if path.startswith(prefix):
                    return pub_domain
            # Unknown DOI prefix: still a registered academic publisher
            return 'unknown-publisher.academic'

        domain = parsed.hostname or ''
        domain = domain.removeprefix('www.')

        # DOI URL: https://doi.org/<prefix>/... -> publisher domain
        if domain == 'doi.org':
            path = parsed.path.strip('/')
            for prefix, pub_domain in self.DOI_PUBLISHER_MAP.items():
                if path.startswith(prefix):
                    return pub_domain
            # Unknown DOI prefix: still a registered academic publisher
            return 'unknown-publisher.academic'

        return domain

    def _evaluate_domain_authority(self, domain: str) -> float:
        """Evaluate domain authority (0-100)"""
        if any(self._domain_matches(domain, d) for d in self.HIGH_AUTHORITY_DOMAINS):
            return 90.0
        elif any(self._domain_matches(domain, d) for d in self.MODERATE_AUTHORITY_DOMAINS):
            return 70.0
        elif any(self._domain_matches(domain, ind) for ind in self.LOW_AUTHORITY_INDICATORS):
            return 40.0
        else:
            # Unknown domain - moderate skepticism
            return 55.0

    def _evaluate_recency(self, publication_date: Optional[str]) -> float:
        """Evaluate information recency (0-100). Unknown dates score 50.0;
        malformed dates raise ValueError instead of being swallowed."""
        if publication_date is None:
            return 50.0  # Unknown date

        pub_date = parse_published_at(publication_date)
        age = datetime.now(timezone.utc) - pub_date

        # Recency scoring
        if age < timedelta(days=90):  # < 3 months
            return 100.0
        elif age < timedelta(days=365):  # < 1 year
            return 85.0
        elif age < timedelta(days=730):  # < 2 years
            return 70.0
        elif age < timedelta(days=1825):  # < 5 years
            return 50.0
        else:
            return 30.0

    def _evaluate_expertise(
        self,
        domain: str,
        title: str,
        author: Optional[str]
    ) -> float:
        """Evaluate source expertise (0-100)"""
        score = 50.0

        # Academic/research domains get high expertise
        if any(self._domain_matches(domain, d)
               for d in self.ACADEMIC_EXPERTISE_DOMAINS):
            score += 30

        # Government/official sources
        if any(self._domain_matches(domain, d)
               for d in self.GOVERNMENT_SUFFIXES):
            score += 25

        # Technical documentation
        if 'docs.' in domain or 'documentation' in title.lower():
            score += 20

        # Author credentials (if available)
        if author:
            if any(credential in author.lower()
                   for credential in ['dr.', 'phd', 'professor']):
                score += 15

        return min(score, 100.0)

    def _evaluate_bias(
        self,
        domain: str,
        title: str,
        content: Optional[str]
    ) -> float:
        """Evaluate potential bias (0-100, higher = more neutral)"""
        score = 70.0  # Start neutral

        # Check for sensationalism in title
        sensational_indicators = [
            '!', 'shocking', 'unbelievable', 'you won\'t believe',
            'secret', 'they don\'t want you to know'
        ]
        title_lower = title.lower()
        if any(indicator in title_lower for indicator in sensational_indicators):
            score -= 20

        # Academic sources are typically less biased
        if any(self._domain_matches(domain, d)
               for d in self.ACADEMIC_BIAS_DOMAINS):
            score += 20

        # Check for balance in content (if available)
        if content:
            # Look for balanced language
            balanced_indicators = ['however', 'although', 'on the other hand', 'critics argue']
            if any(indicator in content.lower() for indicator in balanced_indicators):
                score += 10

        return min(max(score, 0), 100.0)

    def _identify_factors(
        self,
        domain: str,
        domain_score: float,
        recency_score: float,
        expertise_score: float,
        bias_score: float
    ) -> Dict[str, str]:
        """Identify key credibility factors"""
        factors = {}

        if domain_score >= 85:
            factors['domain'] = "High authority domain"
        elif domain_score <= 45:
            factors['domain'] = "Low authority domain - verify claims"

        if recency_score >= 85:
            factors['recency'] = "Recent information"
        elif recency_score <= 40:
            factors['recency'] = "Outdated information - verify currency"

        if expertise_score >= 80:
            factors['expertise'] = "Expert source"
        elif expertise_score <= 45:
            factors['expertise'] = "Limited expertise indicators"

        if bias_score >= 80:
            factors['bias'] = "Balanced perspective"
        elif bias_score <= 50:
            factors['bias'] = "Potential bias detected"

        return factors

    def _generate_recommendation(self, overall_score: float) -> str:
        """Generate trust recommendation"""
        if overall_score >= 80:
            return "high_trust"
        elif overall_score >= 60:
            return "moderate_trust"
        elif overall_score >= 40:
            return "low_trust"
        else:
            return "verify"


def _score_to_dict(
    score: CredibilityScore,
    url: str,
    title: str,
    domain: str,
    source_id: Optional[str] = None
) -> Dict[str, object]:
    """Render a CredibilityScore as the CLI's JSON score object."""
    return {
        'source_id': source_id,
        'url': url,
        'title': title,
        'domain': domain,
        'overall_score': score.overall_score,
        'domain_authority': score.domain_authority,
        'recency': score.recency,
        'expertise': score.expertise,
        'bias_score': score.bias_score,
        'factors': score.factors,
        'recommendation': score.recommendation,
    }


def _row_year(row: dict) -> Optional[str]:
    """The row's year as a 4-digit string, or None. year is free-form in
    the schema; citation_manager writes whatever the agent passed, so an
    integer 2024 is read the same as "2024". Anything else is unknown."""
    year = row.get('year')
    if isinstance(year, int) and not isinstance(year, bool):
        year = str(year)
    if isinstance(year, str) and re.fullmatch(r'[0-9]{4}', year):
        return year
    return None


def _score_row(evaluator: SourceEvaluator, row: dict, defects: list,
               lineno: int) -> Optional[Dict[str, object]]:
    """Score one sources.jsonl row. A defective field is recorded in
    defects and treated as absent, so the row still scores; only a row
    with nothing to score (no URL) is skipped and returns None."""
    source_id = row.get('source_id', 'unknown')

    def defect(field, message, action='scored_without_field'):
        defects.append({'line': lineno, 'source_id': source_id,
                        'field': field, 'error': message, 'action': action})

    url = row.get('raw_url') or row.get('canonical_locator')
    if not isinstance(url, str) or not url:
        defect('raw_url', 'no raw_url or canonical_locator to score',
               action='skipped')
        return None

    title = row.get('title')
    if title is None:
        title = ''
    elif not isinstance(title, str):
        defect('title', f'title must be a string, got {title!r}')
        title = ''

    authors = row.get('authors')
    author = None
    if isinstance(authors, list) and all(isinstance(a, str) for a in authors):
        author = ', '.join(authors)
    elif authors is not None:
        defect('authors', f'authors must be null or a list of strings, '
                          f'got {authors!r}')

    # Date: published_at, else a 4-digit year, else unknown (recency 50.0).
    # registered_at is never used. A malformed published_at is a defect
    # and is treated as null, so the year fallback still applies.
    publication_date = row.get('published_at')
    if publication_date is not None:
        try:
            parse_published_at(publication_date)
        except ValueError as exc:
            defect('published_at', str(exc))
            publication_date = None
    if publication_date is None:
        publication_date = _row_year(row)

    score = evaluator.evaluate_source(
        url, title, publication_date=publication_date, author=author)
    return _score_to_dict(score, url, title, evaluator._extract_domain(url),
                          source_id=source_id)


def _score_dir(evaluator: SourceEvaluator, run_dir: str) -> int:
    """Score every row of run_dir/sources.jsonl. Prints the run summary to
    stdout and returns the exit code.

    One odd row never hides the rest of the run: every scorable row is
    scored and printed. Each row defect (bad JSON line, non-object row,
    no URL, or a schema-invalid title/authors/published_at) is listed in
    the summary's "defects" and in one {"error": ...} object on stderr
    naming the source_id or line, and the exit code is 1 so a caller
    cannot mistake a defective run for a clean one."""
    sources_path = os.path.join(run_dir, 'sources.jsonl')
    if not os.path.isfile(sources_path):
        print(json.dumps(
            {'error': f'{sources_path}: sources.jsonl not found'}),
            file=sys.stderr)
        return 1

    scores = []
    defects = []
    with open(sources_path, encoding='utf-8') as f:
        for lineno, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                defects.append({'line': lineno, 'source_id': None,
                                'field': None,
                                'error': f'not valid JSON: {exc}',
                                'action': 'skipped'})
                continue
            if not isinstance(row, dict):
                defects.append({'line': lineno, 'source_id': None,
                                'field': None,
                                'error': 'row is not a JSON object',
                                'action': 'skipped'})
                continue
            scored = _score_row(evaluator, row, defects, lineno)
            if scored is not None:
                scores.append(scored)

    average = (round(sum(s['overall_score'] for s in scores) / len(scores), 2)
               if scores else None)
    print(json.dumps({
        'dir': run_dir,
        'count': len(scores),
        'average_overall': average,
        'sources': scores,
        'defects': defects,
    }))
    if defects:
        described = '; '.join(
            (f'source {d["source_id"]}' if d['source_id'] is not None
             else 'row') + f' (line {d["line"]}): {d["error"]} [{d["action"]}]'
            for d in defects)
        print(json.dumps({
            'error': f'{sources_path}: {len(defects)} row defect(s): '
                     f'{described}',
            'defects': defects,
        }), file=sys.stderr)
        return 1
    return 0


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog='source_evaluator.py',
        description='Score source credibility (0-100) for one URL or every '
                    'row of a run\'s sources.jsonl.')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--url', help='score this single source')
    group.add_argument('--dir', dest='dir',
                       help='score every row of RUN_DIR/sources.jsonl')
    parser.add_argument('--title', default=None,
                        help='title of the --url source (optional)')
    parser.add_argument('--date', default=None,
                        help='published_at of the --url source, in '
                             'source.schema.json form (optional)')
    args = parser.parse_args(argv)

    if args.dir is not None and (args.title is not None or args.date is not None):
        parser.error('--title and --date apply only to --url')

    evaluator = SourceEvaluator()

    if args.url is not None:
        title = args.title or ''
        try:
            score = evaluator.evaluate_source(
                args.url, title, publication_date=args.date)
        except ValueError as exc:
            print(json.dumps({'error': f'--date: {exc}'}), file=sys.stderr)
            return 1
        print(json.dumps(_score_to_dict(
            score, args.url, title,
            evaluator._extract_domain(args.url))))
        return 0

    return _score_dir(evaluator, args.dir)


if __name__ == '__main__':
    sys.exit(main())
