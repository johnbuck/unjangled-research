#!/usr/bin/env python3
"""Offline tests for verify_citations.py (E1-R4, F7).

No network: urllib.request.urlopen is replaced with canned routes (DOI
JSON metadata and URL HEAD responses alike) and time.sleep is
neutralised. Reports are read from tests/fixtures/verify_citations/;
nothing writes inside the repo. Run: python3 tests/test_verify_citations.py
"""

import contextlib
import io
import json
import os
import sys
import unittest
import unittest.mock
import urllib.error

SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'scripts'))
FIXDIR = os.path.join(os.path.dirname(__file__), 'fixtures', 'verify_citations')

sys.path.insert(0, SCRIPTS)
import verify_citations  # noqa: E402


def doi_body(title: str, year: int) -> bytes:
    return json.dumps({
        'title': title,
        'issued': {'date-parts': [[year]]},
        'author': [{'family': 'Mesa', 'given': 'Ana'}],
        'container-title': 'Journal of Coastal Dynamics',
    }).encode('utf-8')


ROUTES = {
    'https://doi.org/10.48550/genuine-alpha': (
        200, doi_body('Field Measurements of Coastal Erosion Rates', 2021)),
    'https://doi.org/10.48550/genuine-beta': (
        200, doi_body('Longitudinal Survey of Urban Heat Island Effects', 2019)),
    'https://doi.org/10.48550/genuine-gamma': (
        200, doi_body('Experimental Analysis of Soil Permeability Gradients', 2020)),
    'https://doi.org/10.48550/wrong-paper': (
        200, doi_body('Fiscal Policy Responses in Eastern Europe', 2021)),
    'https://doi.org/10.48550/missing-one': (404, b''),
    'https://doi.org/10.48550/missing-two': (404, b''),
    'https://example.org/web-finding': (200, b''),
}


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200):
        self._body = body
        self.status = status

    def read(self, n: int = -1) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeUrlopen:
    """url -> (status, body); status >= 400 raises HTTPError; unknown url 404."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls = []

    def __call__(self, req, timeout=None):
        url = req.full_url
        self.calls.append(url)
        status, body = self.routes.get(url, (404, b''))
        if status >= 400:
            raise urllib.error.HTTPError(url, status, 'canned error', None, None)
        return FakeResponse(body, status)


class MainHarness(unittest.TestCase):
    """Runs verify_citations.main() in-process against a mocked urlopen."""

    def run_main(self, fixture: str, extra_args=()) -> tuple:
        report = os.path.join(FIXDIR, fixture)
        fake = FakeUrlopen(ROUTES)
        out, err = io.StringIO(), io.StringIO()
        argv = ['verify_citations', '--report', report, *extra_args]
        old_argv, sys.argv = sys.argv, argv
        try:
            with unittest.mock.patch('urllib.request.urlopen', fake), \
                    unittest.mock.patch('time.sleep', lambda s: None), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    verify_citations.main()
                    code = 0
                except SystemExit as e:
                    code = e.code
        finally:
            sys.argv = old_argv
        return code, out.getvalue()


class TestEntryFormsAndSectionEnd(MainHarness):
    """Every E1-R1 entry form parses; only '## ' ends the section."""

    def test_dash_star_and_plain_entries_with_subsection_inside_parse_fully(self):
        code, out = self.run_main('entry_forms_report.md')
        self.assertEqual(code, 0)
        self.assertIn('Found 3 citations', out)
        self.assertIn('DOI Verified: 3/3', out)
        self.assertIn('CITATION VERIFICATION PASSED', out)

    def test_sources_alias_heading_is_a_bibliography(self):
        code, out = self.run_main('sources_heading_report.md')
        self.assertEqual(code, 0)
        self.assertIn('Found 1 citations', out)
        self.assertIn('CITATION VERIFICATION PASSED', out)


class TestDefaultFailsOnBadResults(MainHarness):
    """No flags: suspicious or under-half-verified runs exit non-zero."""

    def test_fabricated_citation_exits_nonzero_with_no_flags(self):
        code, out = self.run_main('fabricated_report.md')
        self.assertEqual(code, 1)
        self.assertIn('Title mismatch', out)
        self.assertIn('FAIL: Suspicious citations detected', out)

    def test_under_half_verified_exits_nonzero(self):
        code, out = self.run_main('under_half_report.md')
        self.assertEqual(code, 1)
        self.assertIn('FAIL: Less than 50% of citations verified (1/3)', out)

    def test_entry_with_no_doi_or_url_is_suspicious(self):
        code, out = self.run_main('no_verification_report.md')
        self.assertEqual(code, 1)
        self.assertIn('No DOI or URL', out)
        self.assertIn('FAIL: Suspicious citations detected', out)


class TestStrict(MainHarness):
    """--strict additionally demands every entry verified by DOI or URL."""

    def test_default_tolerates_unverified_when_half_met(self):
        code, out = self.run_main('strict_unverified_report.md')
        self.assertEqual(code, 0)
        self.assertIn('CITATION VERIFICATION PASSED', out)

    def test_strict_fails_unverified_entry(self):
        code, out = self.run_main('strict_unverified_report.md', ['--strict'])
        self.assertEqual(code, 1)
        self.assertIn('STRICT MODE: Unverified citations found', out)

    def test_strict_passes_when_all_verified_by_doi_or_url(self):
        code, out = self.run_main('url_verified_report.md', ['--strict'])
        self.assertEqual(code, 0)
        self.assertIn('URL Verified: 1/2', out)
        self.assertIn('CITATION VERIFICATION PASSED', out)


class TestNoBibliography(MainHarness):
    """A report without a bibliography fails loudly."""

    def test_body_only_report_exits_nonzero(self):
        code, out = self.run_main('no_bibliography_report.md')
        self.assertEqual(code, 1)
        self.assertIn('No Bibliography section found', out)


if __name__ == '__main__':
    unittest.main()
