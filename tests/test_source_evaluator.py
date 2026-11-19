#!/usr/bin/env python3
"""Tests for source_evaluator.py: the CLI (--url / --dir) printing JSON
scores, registrable-domain suffix matching (the four suffix traps),
partial-date recency tiers computed against now (no drift), and the error
paths (exit 1 runtime defect, exit 2 usage)."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'scripts'))

from source_evaluator import SourceEvaluator  # noqa: E402

SCRIPT = os.path.join(HERE, '..', 'scripts', 'source_evaluator.py')
FIXTURES = os.path.join(HERE, 'fixtures', 'source_evaluator')

SCORE_KEYS = {
    'source_id', 'url', 'title', 'domain', 'overall_score',
    'domain_authority', 'recency', 'expertise', 'bias_score',
    'factors', 'recommendation',
}


def run_se_raw(*args):
    return subprocess.run(
        [sys.executable, SCRIPT, *args],
        capture_output=True, text=True,
    )


def run_se(*args):
    result = run_se_raw(*args)
    if result.returncode != 0:
        raise RuntimeError(f'Exit {result.returncode}: {result.stderr}')
    return json.loads(result.stdout)


def expected_recency(published):
    """The plan's recency tier table, computed against now (no drift)."""
    age = datetime.now(timezone.utc) - published
    if age < timedelta(days=90):
        return 100.0
    if age < timedelta(days=365):
        return 85.0
    if age < timedelta(days=730):
        return 70.0
    if age < timedelta(days=1825):
        return 50.0
    return 30.0


def utc_iso(moment):
    return moment.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def make_row(source_id, raw_url, **extra):
    row = {
        'source_id': source_id,
        'canonical_locator': extra.pop('canonical_locator', raw_url),
        'raw_url': raw_url,
        'title': extra.pop('title', ''),
        'source_type': 'web',
        'metadata_status': 'unverified',
        'registered_at': '2026-11-18T00:00:00+00:00',
    }
    row.update(extra)
    return row


def write_run(rows):
    """Write rows to a fresh run dir outside the repo; return its path."""
    run_dir = tempfile.mkdtemp()
    with open(os.path.join(run_dir, 'sources.jsonl'), 'w', encoding='utf-8') as f:
        for row in rows:
            f.write(json.dumps(row) + '\n')
    return run_dir


def make_run(testcase, rows):
    """write_run with cleanup registered on the test case."""
    run_dir = write_run(rows)
    testcase.addCleanup(shutil.rmtree, run_dir, ignore_errors=True)
    return run_dir


class TestParsePublishedAt(unittest.TestCase):
    """parse_published_at accepts the four schema precisions at their
    earliest instant and rejects everything the schema pattern rejects."""

    def setUp(self):
        # Imported here (not at module top) so that against 35d132d, where
        # the function does not exist, each test fails on its own instead
        # of the module crashing at import.
        from source_evaluator import parse_published_at
        self.parse_published_at = parse_published_at

    def test_year_month_day_precisions_take_earliest_instant(self):
        self.assertEqual(self.parse_published_at('2024'),
                         datetime(2024, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(self.parse_published_at('2024-06'),
                         datetime(2024, 6, 1, tzinfo=timezone.utc))
        self.assertEqual(self.parse_published_at('2024-06-15'),
                         datetime(2024, 6, 15, tzinfo=timezone.utc))

    def test_time_forms_return_aware_utc(self):
        for value, expected in (
            ('2024-06-15T09:30:00', datetime(2024, 6, 15, 9, 30, tzinfo=timezone.utc)),
            ('2024-06-15T09:30Z', datetime(2024, 6, 15, 9, 30, tzinfo=timezone.utc)),
            ('2024-06-15T09:30:00.123+02:00',
             datetime(2024, 6, 15, 7, 30, 0, 123000, tzinfo=timezone.utc)),
        ):
            parsed = self.parse_published_at(value)
            self.assertEqual(parsed, expected, value)
            self.assertIsNotNone(parsed.tzinfo, value)

    def test_schema_violating_values_raise(self):
        for bad in ('January 2024', '15/01/2024', '2024-1-5', '2024-13',
                    '2024-01-32', '2024-02-31', '20240115', '24',
                    '2024-01-15 09:30:00', '2024-01-15T25:00:00Z',
                    '2024-01-15T09:30:00+99:00', '2024-01-15T09:30:00+00:99',
                    'unknown', '', None, 123):
            with self.assertRaises(ValueError, msg=repr(bad)):
                self.parse_published_at(bad)


class TestSuffixTraps(unittest.TestCase):
    """Domain bonuses match registrable-domain suffixes, never substrings."""

    def setUp(self):
        self.evaluator = SourceEvaluator()

    def score(self, url, title='A title'):
        return self.evaluator.evaluate_source(url, title)

    def test_sciencedaily_gets_no_science_bonus(self):
        score = self.score('https://www.sciencedaily.com/x')
        self.assertEqual(self.evaluator._extract_domain(url='https://www.sciencedaily.com/x'),
                         'sciencedaily.com')
        self.assertEqual(score.expertise, 50.0)
        self.assertEqual(score.domain_authority, 55.0)
        self.assertEqual(score.bias_score, 70.0)

    def test_nested_gov_subdomain_gets_no_gov_bonus(self):
        score = self.score('https://something.gov.evil.com/x')
        self.assertEqual(score.expertise, 50.0)
        self.assertEqual(score.domain_authority, 55.0)

    def test_notnature_gets_no_nature_bonus(self):
        score = self.score('https://notnature.com/article')
        self.assertEqual(score.expertise, 50.0)
        self.assertEqual(score.bias_score, 70.0)

    def test_nature_prefixed_evil_domain_gets_no_nature_bonus(self):
        score = self.score('https://nature.com.evil.com/article')
        self.assertEqual(score.expertise, 50.0)
        self.assertEqual(score.bias_score, 70.0)
        self.assertEqual(score.domain_authority, 55.0)

    def test_real_domains_and_subdomains_do_match(self):
        score = self.score('https://www.nature.com/articles/x')
        self.assertEqual(score.domain_authority, 90.0)
        self.assertEqual(score.expertise, 80.0)  # 50 + 30 academic
        self.assertEqual(score.bias_score, 90.0)  # 70 + 20 academic
        sub = self.score('https://sub.nature.com/articles/x')
        self.assertEqual(sub.expertise, 80.0)
        gov = self.score('https://www.nih.gov/grants')
        self.assertEqual(gov.expertise, 75.0)  # 50 + 25 government

    def test_genuine_bonuses_the_substring_rule_gave_are_kept(self):
        # Elsevier (sciencedirect.com, the 10.1016 DOI target) and Science's
        # former domain kept their academic bonus under the old 'science'
        # substring; suffix matching must not drop it.
        for url in ('https://www.sciencedirect.com/science/article/pii/S1',
                    'https://doi.org/10.1016/j.cell.2020.01.001',
                    'doi:10.1016/j.cell.2020.01.001',
                    'https://www.sciencemag.org/news/x'):
            score = self.score(url)
            self.assertEqual(score.expertise, 80.0, url)
            self.assertEqual(score.bias_score, 90.0, url)
        # Government second levels under country TLDs kept the .gov bonus.
        for url in ('https://www.ons.gov.uk/x', 'https://www.abs.gov.au/x',
                    'https://www.gov.uk/guidance/x'):
            self.assertEqual(self.score(url).expertise, 75.0, url)
        for url in ('https://gov.evil.com/x', 'https://abs.gov.au.evil.com/x',
                    'https://notgov.uk/x'):
            self.assertEqual(self.score(url).expertise, 50.0, url)

    def test_low_authority_indicators_match_by_suffix(self):
        self.assertEqual(
            self.evaluator._evaluate_domain_authority('foo.wordpress.com'), 40.0)
        self.assertEqual(
            self.evaluator._evaluate_domain_authority('notwordpress.com'), 55.0)

    def test_extract_domain_strips_only_leading_www_and_port(self):
        extract = self.evaluator._extract_domain
        self.assertEqual(extract('https://www.example.com:8080/x'), 'example.com')
        self.assertEqual(extract('https://EXAMPLE.com/x'), 'example.com')
        self.assertEqual(extract('https://awww.example.com/x'), 'awww.example.com')

    def test_doi_locators_resolve_through_publisher_map(self):
        extract = self.evaluator._extract_domain
        self.assertEqual(extract('doi:10.1037/0003-066X/123'), 'apa.org')
        self.assertEqual(extract('https://doi.org/10.1037/x'), 'apa.org')
        self.assertEqual(extract('doi:10.9999/unknown'), 'unknown-publisher.academic')


class TestRecencyTiers(unittest.TestCase):
    """Recency tiers for --date values, with expectations computed from
    now so the test never drifts across tier boundaries."""

    def test_tiers_from_computed_ages(self):
        for days in (30, 200, 500, 1000, 3000):
            published = datetime.now(timezone.utc) - timedelta(days=days)
            out = run_se('--url', 'https://example.com/x',
                         '--date', utc_iso(published))
            self.assertEqual(out['recency'], expected_recency(published), days)

    def test_partial_precisions_take_earliest_instant(self):
        for value, instant in (
            ('2024', datetime(2024, 1, 1, tzinfo=timezone.utc)),
            ('2024-06', datetime(2024, 6, 1, tzinfo=timezone.utc)),
            ('2024-06-15', datetime(2024, 6, 15, tzinfo=timezone.utc)),
        ):
            out = run_se('--url', 'https://example.com/x', '--date', value)
            self.assertEqual(out['recency'], expected_recency(instant), value)

    def test_no_date_scores_unknown(self):
        out = run_se('--url', 'https://example.com/x')
        self.assertEqual(out['recency'], 50.0)


class TestSingleSourceCLI(unittest.TestCase):
    def test_score_shape_and_exit_0(self):
        out = run_se('--url', 'https://www.sciencedaily.com/x')
        self.assertEqual(set(out), SCORE_KEYS)
        self.assertIsNone(out['source_id'])
        self.assertEqual(out['domain'], 'sciencedaily.com')
        self.assertEqual(out['expertise'], 50.0)

    def test_title_penalises_sensationalism(self):
        out = run_se('--url', 'https://example.com/x',
                     '--title', 'Shocking discovery!')
        self.assertEqual(out['bias_score'], 50.0)
        self.assertEqual(out['expertise'], 50.0)


class TestDirCLI(unittest.TestCase):
    def test_fixture_run_scores_every_row(self):
        run_dir = os.path.join(FIXTURES, 'run')
        out = run_se('--dir', run_dir)
        self.assertEqual(set(out),
                         {'dir', 'count', 'average_overall', 'sources', 'defects'})
        self.assertEqual(out['defects'], [])
        self.assertEqual(out['dir'], run_dir)
        self.assertEqual(out['count'], 3)
        self.assertEqual(len(out['sources']), 3)
        self.assertEqual([s['source_id'] for s in out['sources']],
                         ['aaaa000000000001', 'aaaa000000000002', 'aaaa000000000003'])
        for source in out['sources']:
            self.assertEqual(set(source), SCORE_KEYS, source['source_id'])
        expected_average = round(
            sum(s['overall_score'] for s in out['sources']) / 3, 2)
        self.assertEqual(out['average_overall'], expected_average)

        full, year_row, undated = out['sources']
        # Row 1: full timestamp row on nature.com with a credentialed author.
        self.assertEqual(full['recency'],
                         expected_recency(datetime(2026, 10, 1, 12, tzinfo=timezone.utc)))
        self.assertEqual(full['domain_authority'], 90.0)
        self.assertEqual(full['expertise'], 95.0)  # 50 + 30 academic + 15 Prof.
        # Row 2: null published_at falls back to the year field.
        self.assertEqual(year_row['recency'],
                         expected_recency(datetime(2025, 1, 1, tzinfo=timezone.utc)))
        # Row 3: all-null dates score unknown.
        self.assertEqual(undated['recency'], 50.0)
        self.assertEqual(undated['domain_authority'], 70.0)  # wikipedia.org

    def test_raw_url_preferred_over_canonical_locator(self):
        run_dir = make_run(self, [make_row(
            'cccc000000000001', 'https://www.wikipedia.org/wiki/X',
            canonical_locator='doi:10.1037/prefer-raw')])
        out = run_se('--dir', run_dir)
        self.assertEqual(out['sources'][0]['domain'], 'wikipedia.org')
        self.assertEqual(out['sources'][0]['domain_authority'], 70.0)

    def test_canonical_locator_fallback_resolves_doi(self):
        run_dir = make_run(self, [make_row(
            'cccc000000000002', '',
            canonical_locator='doi:10.1037/fallback')])
        out = run_se('--dir', run_dir)
        self.assertEqual(out['sources'][0]['domain'], 'apa.org')
        self.assertEqual(out['sources'][0]['domain_authority'], 90.0)

    def test_free_form_year_scores_unknown_without_error(self):
        run_dir = make_run(self, [
            make_row('cccc000000000003', 'https://example.com/a', year='2024ish'),
        ])
        out = run_se('--dir', run_dir)
        self.assertEqual([s['recency'] for s in out['sources']], [50.0])

    def test_integer_year_is_read_like_a_string_year(self):
        # citation_manager passes year through unvalidated, so agents'
        # "year": 2024 lands in sources.jsonl as an integer.
        run_dir = make_run(self, [
            make_row('cccc000000000004', 'https://example.com/b', year=2024),
            make_row('cccc000000000005', 'https://example.com/c', year='2024'),
        ])
        out = run_se('--dir', run_dir)
        jan_2024 = expected_recency(datetime(2024, 1, 1, tzinfo=timezone.utc))
        self.assertEqual([s['recency'] for s in out['sources']],
                         [jan_2024, jan_2024])
        self.assertEqual(out['defects'], [])

    def test_zero_row_file_scores_empty_run(self):
        run_dir = make_run(self, [])
        out = run_se('--dir', run_dir)
        self.assertEqual(out['count'], 0)
        self.assertIsNone(out['average_overall'])
        self.assertEqual(out['sources'], [])


class TestErrorPaths(unittest.TestCase):
    def test_missing_sources_file_exits_1_with_error_json(self):
        result = run_se_raw('--dir', os.path.join(FIXTURES, 'empty'))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, '')
        error = json.loads(result.stderr)
        self.assertIn('sources.jsonl', error['error'])

    def test_bad_date_row_exits_1_naming_source_id(self):
        result = run_se_raw('--dir', os.path.join(FIXTURES, 'bad-date'))
        self.assertEqual(result.returncode, 1)
        error = json.loads(result.stderr)
        self.assertIn('badda7e000000001', error['error'])
        self.assertIn('January 2024', error['error'])
        # The row is still scored, with its date treated as unknown.
        out = json.loads(result.stdout)
        self.assertEqual(out['count'], 1)
        self.assertEqual(out['sources'][0]['source_id'], 'badda7e000000001')
        self.assertEqual(out['sources'][0]['recency'], 50.0)
        self.assertEqual([(d['source_id'], d['field'], d['action'])
                          for d in out['defects']],
                         [('badda7e000000001', 'published_at',
                           'scored_without_field')])

    def test_bad_json_row_exits_1_naming_line_number(self):
        run_dir = make_run(self, [])
        with open(os.path.join(run_dir, 'sources.jsonl'), 'w', encoding='utf-8') as f:
            f.write(json.dumps(make_row('dddd000000000001', 'https://example.com/1')) + '\n')
            f.write('{not valid json\n')
        result = run_se_raw('--dir', run_dir)
        self.assertEqual(result.returncode, 1)
        error = json.loads(result.stderr)
        self.assertIn('line 2', error['error'])
        out = json.loads(result.stdout)
        self.assertEqual([s['source_id'] for s in out['sources']],
                         ['dddd000000000001'])
        self.assertEqual([(d['line'], d['action']) for d in out['defects']],
                         [(2, 'skipped')])

    def test_bad_cli_date_exits_1_naming_flag(self):
        result = run_se_raw('--url', 'https://example.com/x',
                            '--date', 'January 2024')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, '')
        error = json.loads(result.stderr)
        self.assertIn('--date', error['error'])

    def test_non_string_title_row_exits_1_naming_source_id(self):
        run_dir = make_run(self, [
            make_row('eeee000000000001', 'https://example.com/t', title=5)])
        result = run_se_raw('--dir', run_dir)
        self.assertEqual(result.returncode, 1)
        error = json.loads(result.stderr)
        self.assertIn('eeee000000000001', error['error'])
        self.assertIn('title', error['error'])
        out = json.loads(result.stdout)
        self.assertEqual(out['sources'][0]['title'], '')
        self.assertEqual(out['defects'][0]['field'], 'title')

    def test_non_string_authors_row_exits_1_naming_source_id(self):
        run_dir = make_run(self, [
            make_row('eeee000000000002', 'https://example.com/a', authors=[1, 2])])
        result = run_se_raw('--dir', run_dir)
        self.assertEqual(result.returncode, 1)
        error = json.loads(result.stderr)
        self.assertIn('eeee000000000002', error['error'])
        self.assertIn('authors', error['error'])
        out = json.loads(result.stdout)
        self.assertEqual(out['count'], 1)
        self.assertEqual(out['defects'][0]['field'], 'authors')

    def test_one_odd_row_does_not_hide_the_rest_of_the_run(self):
        # Rows older runs wrote (no published_at key at all, integer year)
        # score cleanly; defective rows are scored without the bad field
        # or skipped, every defect is reported, and the exit code is 1.
        legacy = make_row('ffff000000000001', 'https://www.nih.gov/a', year='2024')
        legacy.pop('title')
        run_dir = make_run(self, [
            legacy,
            make_row('ffff000000000002', 'https://example.com/b',
                     published_at='Spring 2023', year='2023'),
            make_row('ffff000000000003', '', canonical_locator=''),
            make_row('ffff000000000004', 'https://example.com/d', year=2022),
        ])
        with open(os.path.join(run_dir, 'sources.jsonl'), 'a', encoding='utf-8') as f:
            f.write('["not", "an", "object"]\n')
        result = run_se_raw('--dir', run_dir)
        self.assertEqual(result.returncode, 1)
        out = json.loads(result.stdout)
        self.assertEqual([s['source_id'] for s in out['sources']],
                         ['ffff000000000001', 'ffff000000000002',
                          'ffff000000000004'])
        self.assertEqual(out['count'], 3)
        self.assertEqual(out['average_overall'], round(
            sum(s['overall_score'] for s in out['sources']) / 3, 2))
        # The bad published_at falls back to the row's year.
        self.assertEqual(out['sources'][1]['recency'],
                         expected_recency(datetime(2023, 1, 1, tzinfo=timezone.utc)))
        self.assertEqual(
            [(d['line'], d['source_id'], d['field'], d['action'])
             for d in out['defects']],
            [(2, 'ffff000000000002', 'published_at', 'scored_without_field'),
             (3, 'ffff000000000003', 'raw_url', 'skipped'),
             (5, None, None, 'skipped')])
        error = json.loads(result.stderr)
        self.assertIn('ffff000000000002', error['error'])
        self.assertIn('ffff000000000003', error['error'])
        self.assertIn('line 5', error['error'])
        self.assertEqual(error['defects'], out['defects'])

    def test_no_mode_exits_2(self):
        self.assertEqual(run_se_raw().returncode, 2)

    def test_url_and_dir_are_mutually_exclusive(self):
        result = run_se_raw('--url', 'https://example.com/x',
                            '--dir', os.path.join(FIXTURES, 'run'))
        self.assertEqual(result.returncode, 2)

    def test_title_and_date_with_dir_exit_2(self):
        run_dir = os.path.join(FIXTURES, 'run')
        for extra in (['--title', ''], ['--title', 'A title'], ['--date', '2024']):
            result = run_se_raw('--dir', run_dir, *extra)
            self.assertEqual(result.returncode, 2, extra)

    def test_title_or_date_with_dir_exits_2(self):
        for extra in (['--title', 'T'], ['--date', '2024']):
            result = run_se_raw('--dir', os.path.join(FIXTURES, 'run'), *extra)
            self.assertEqual(result.returncode, 2, extra)
            self.assertEqual(result.stdout, '', extra)


if __name__ == '__main__':
    unittest.main()
