#!/usr/bin/env python3
"""Offline tests for verify_citations_v2.py (E1-R5, F8).

No network: urllib.request.urlopen is replaced with canned responses.
Run directories live in temp dirs; nothing writes inside the repo.
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
import urllib.error
import urllib.request

SCRIPT = os.path.join(os.path.dirname(__file__), '..', 'scripts', 'verify_citations_v2.py')
FIXTURE = os.path.join(os.path.dirname(__file__), 'fixtures', 'verify_citations_v2', 'example_page.html')

URL = 'https://example.com/results'

with open(FIXTURE, encoding='utf-8') as _f:
    PAGE_HTML = _f.read()

GENUINE_QUOTE = 'Revenue & profit rose sharply in Q4, beating every forecast on Wall Street.'
CURLY_QUOTE = 'The board called the result "unprecedented" in its statement to investors.'
FABRICATED_QUOTE = 'This sentence appears nowhere in the fetched page at all.'


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


class FakeUlopen:
    """url -> (status, body); status >= 400 raises HTTPError."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls = []

    def __call__(self, req, timeout=30):
        url = req.full_url
        self.calls.append(url)
        status, body = self.routes.get(url, (404, ''))
        if status >= 400:
            raise urllib.error.HTTPError(url, status, 'canned error', None, None)
        return FakeResponse(body.encode('utf-8'), status)


def write_jsonl(path: str, rows: list):
    with open(path, 'w') as f:
        for row in rows:
            f.write(json.dumps(row) + '\n')


def quote_row(eid: str, quote: str, source_id: str = 'src_ex_001', **extra) -> dict:
    row = {
        'evidence_id': eid,
        'source_id': source_id,
        'quote': quote,
        'evidence_type': 'direct_quote',
    }
    row.update(extra)
    return row


def source_row(source_id: str = 'src_ex_001', url: str = URL) -> dict:
    return {'source_id': source_id, 'title': 'Example Results', 'raw_url': url}


class MainHarness(unittest.TestCase):
    """Runs verify_citations_v2.main() in-process against a mocked urlopen."""

    def run_main(self, routes: dict, tmpdir: str, extra_args: list | None = None) -> tuple[int, dict]:
        """Return (exit_code, parsed_json_or_stdout)."""
        fake = FakeUlopen(routes)
        out, err = io.StringIO(), io.StringIO()
        if extra_args is None:
            extra_args = ['--json']
        argv = ['verify_citations_v2', '--dir', tmpdir, *extra_args]
        old_argv, sys.argv = sys.argv, argv
        try:
            with unittest.mock.patch('urllib.request.urlopen', fake), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    sys.modules['verify_citations_v2'].main()
                    code = 0
                except SystemExit as e:
                    code = e.code
        finally:
            sys.argv = old_argv
        stdout = out.getvalue()
        if stdout.strip().startswith('{'):
            return code, json.loads(stdout)
        return code, {'stdout': stdout, 'stderr': err.getvalue()}

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
        import verify_citations_v2
        sys.modules.setdefault('verify_citations_v2', verify_citations_v2)

    def make_run(self, sources: list, evidence: list) -> str:
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)
        write_jsonl(os.path.join(tmpdir, 'sources.jsonl'), sources)
        write_jsonl(os.path.join(tmpdir, 'evidence.jsonl'), evidence)
        return tmpdir


class TestPageTextMatching(MainHarness):
    """Quotes match on page text, not raw HTML."""

    def test_genuine_quote_with_entities_and_tags_matches(self):
        d = self.make_run([source_row()], [quote_row('ev_ok_001', GENUINE_QUOTE)])
        code, rep = self.run_main({URL: (200, PAGE_HTML)}, d)
        self.assertEqual(code, 0)
        self.assertEqual(rep['fidelity_misses'], 0)
        self.assertEqual(rep['detail'][0]['status'], 'verified')

    def test_curly_quotes_normalise(self):
        d = self.make_run([source_row()], [quote_row('ev_q_001', CURLY_QUOTE)])
        code, rep = self.run_main({URL: (200, PAGE_HTML)}, d)
        self.assertEqual(code, 0)
        self.assertEqual(rep['detail'][0]['status'], 'verified')

    def test_fabricated_quote_is_miss_and_exits_1(self):
        d = self.make_run([source_row()], [quote_row('ev_bad_001', FABRICATED_QUOTE)])
        code, rep = self.run_main({URL: (200, PAGE_HTML)}, d)
        self.assertEqual(code, 1)
        self.assertEqual(rep['fidelity_misses'], 1)
        self.assertEqual(rep['miss_ids'], ['ev_bad_001'])
        self.assertEqual(rep['detail'][0]['status'], 'MISS')


class TestReachableStatus(MainHarness):
    """Any 2xx counts as reachable; 4xx is unreachable."""

    def test_203_is_reachable(self):
        d = self.make_run([source_row()], [quote_row('ev_203_001', GENUINE_QUOTE)])
        code, rep = self.run_main({URL: (203, PAGE_HTML)}, d)
        self.assertEqual(code, 0)
        self.assertEqual(rep['unreachable'], 0)
        self.assertEqual(rep['reachable'], 1)
        self.assertEqual(rep['detail'][0]['status'], 'verified')

    def test_all_unreachable_exits_2(self):
        d = self.make_run([source_row()], [quote_row('ev_x_001', GENUINE_QUOTE)])
        code, rep = self.run_main({URL: (403, '')}, d)
        self.assertEqual(code, 2)
        self.assertEqual(rep['unreachable'], 1)
        self.assertEqual(rep['fidelity_misses'], 0)
        self.assertIn('unreachable', rep['detail'][0]['status'])


class TestZeroSources(MainHarness):
    """An empty sources.jsonl means nothing was checked: exit 1."""

    def test_empty_sources_exits_1(self):
        d = self.make_run([], [quote_row('ev_lonely', GENUINE_QUOTE)])
        code, rep = self.run_main({}, d)
        self.assertEqual(code, 1)
        self.assertEqual(rep['sources_checked'], 0)
        self.assertEqual(rep['fidelity_misses'], 0)


class TestSkippedShortQuotes(MainHarness):
    """Short quotes are reported, not silently dropped."""

    def test_short_quote_counted_in_output(self):
        rows = [quote_row('ev_short_01', 'Too short.'), quote_row('ev_ok_002', GENUINE_QUOTE)]
        d = self.make_run([source_row()], rows)
        code, rep = self.run_main({URL: (200, PAGE_HTML)}, d)
        self.assertEqual(code, 0)
        self.assertEqual(rep['skipped_short_quotes'], 1)
        statuses = {r['evidence_id']: r['status'] for r in rep['detail']}
        self.assertIn('skipped (short quote', statuses['ev_short_01'])
        self.assertEqual(statuses['ev_ok_002'], 'verified')

    def test_text_output_reports_skip_count(self):
        rows = [quote_row('ev_short_02', 'Tiny.'), quote_row('ev_ok_003', GENUINE_QUOTE)]
        d = self.make_run([source_row()], rows)
        code, rep = self.run_main({URL: (200, PAGE_HTML)}, d, extra_args=[])
        self.assertEqual(code, 0)
        self.assertIn('1 skipped', rep['stdout'])


class TestSupersedesFilterRemoved(MainHarness):
    """No writer for `supersedes` exists, so every evidence row is checked."""

    def test_superseded_row_is_still_checked(self):
        rows = [
            quote_row('ev_new_001', GENUINE_QUOTE, supersedes='ev_old_001'),
            quote_row('ev_old_001', CURLY_QUOTE),
        ]
        d = self.make_run([source_row()], rows)
        code, rep = self.run_main({URL: (200, PAGE_HTML)}, d)
        self.assertEqual(code, 0)
        statuses = {r['evidence_id']: r['status'] for r in rep['detail']}
        self.assertEqual(statuses['ev_new_001'], 'verified')
        self.assertEqual(statuses['ev_old_001'], 'verified')
        self.assertEqual(len(rep['detail']), 2)


class TestNoFalseMatches(MainHarness):
    """Normalisation must not let a quote match text a reader never sees,
    or match part of a word; it must not lose visible text either."""

    PAGE = (
        '<html><head>'
        '<style>p::after { content: "A stylesheet string posing as a quote"; }</style>'
        '<script>var s = "A sentence that lives only in the page JavaScript";</script>'
        '</head><body>'
        '<!-- A comment line the reader never sees on the page -->'
        '<p>Nonprofit income rose sharply in the fourth quarter.</p>'
        '<p>If a &lt; b and c &gt; d then the ordering holds for every input.</p>'
        '<p><span class="dropcap">T</span>he committee met <a href="/x" title="a > b">on Friday</a> to vote.</p>'
        '<p>First paragraph ends here.</p><p>Second paragraph starts here.</p>'
        '</body></html>'
    )

    def check(self, quote: str) -> str:
        d = self.make_run([source_row()], [quote_row('ev_t_001', quote)])
        _, rep = self.run_main({URL: (200, self.PAGE)}, d)
        return rep['detail'][0]['status']

    def test_script_text_does_not_match(self):
        self.assertEqual(self.check('A sentence that lives only in the page JavaScript'), 'MISS')

    def test_style_text_does_not_match(self):
        self.assertEqual(self.check('A stylesheet string posing as a quote'), 'MISS')

    def test_comment_text_does_not_match(self):
        self.assertEqual(self.check('A comment line the reader never sees'), 'MISS')

    def test_partial_word_does_not_match(self):
        self.assertEqual(self.check('profit income rose sharply in the fourth quarter.'), 'MISS')
        self.assertEqual(self.check('Nonprofit income rose sharply in the fourth'), 'verified')

    def test_encoded_angle_brackets_stay_text(self):
        self.assertEqual(self.check('If a < b and c > d then the ordering holds'), 'verified')

    def test_inline_tag_inside_word_does_not_split_it(self):
        self.assertEqual(self.check('The committee met on Friday to vote.'), 'verified')

    def test_block_tags_do_not_join_words(self):
        self.assertEqual(self.check('ends here. Second paragraph starts'), 'verified')
        self.assertEqual(self.check('ends here.Second paragraph starts'), 'MISS')


class TestProgramName(unittest.TestCase):
    """--help must show the real program name."""

    def test_usage_shows_verify_citations_v2(self):
        result = subprocess.run(
            [sys.executable, SCRIPT, '--help'],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('usage: verify_citations_v2', result.stdout)
        self.assertNotIn('usage: verify_citations ', result.stdout)


if __name__ == '__main__':
    unittest.main()
