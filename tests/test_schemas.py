#!/usr/bin/env python3
"""Generated artifacts must validate against schemas/: an init-run
manifest, register-source rows with and without published_at, and a
manifest carrying format/qa_notes — and wrong-typed values must fail,
proving the validator is real."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'scripts'))

from schema_validator import load_schema, schema_errors  # noqa: E402

SCRIPT = os.path.join(HERE, '..', 'scripts', 'citation_manager.py')
MANIFEST_SCHEMA = load_schema(os.path.join(HERE, '..', 'schemas', 'run_manifest.schema.json'))
SOURCE_SCHEMA = load_schema(os.path.join(HERE, '..', 'schemas', 'source.schema.json'))
CLAIM_SCHEMA = load_schema(os.path.join(HERE, '..', 'schemas', 'claim.schema.json'))
SCRIPTS = os.path.join(HERE, '..', 'scripts')


def run_cm(*args):
    result = subprocess.run(
        [sys.executable, SCRIPT, *args],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f'Exit {result.returncode}: {result.stderr}')
    return json.loads(result.stdout) if result.stdout.strip().startswith(('{', '[')) else result.stdout


def read_jsonl(path):
    with open(path, encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]


class TestGeneratedManifest(unittest.TestCase):
    def test_init_run_manifest_validates(self):
        with tempfile.TemporaryDirectory() as d:
            run_cm('init-run', '--out-dir', d, '--query', 'schema test', '--mode', 'deep')
            with open(os.path.join(d, 'run_manifest.json'), encoding='utf-8') as f:
                manifest = json.load(f)
            self.assertEqual(schema_errors(MANIFEST_SCHEMA, manifest), [])

    def test_manifest_with_format_and_qa_notes_validates(self):
        with tempfile.TemporaryDirectory() as d:
            run_cm('init-run', '--out-dir', d, '--query', 'schema test')
            path = os.path.join(d, 'run_manifest.json')
            with open(path, encoding='utf-8') as f:
                manifest = json.load(f)
            manifest['format'] = 'research-summary'
            manifest['qa_notes'] = 'check_theme WARN justified: short format by design'
            self.assertEqual(schema_errors(MANIFEST_SCHEMA, manifest), [])

    def test_bogus_format_fails(self):
        with tempfile.TemporaryDirectory() as d:
            run_cm('init-run', '--out-dir', d, '--query', 'schema test')
            path = os.path.join(d, 'run_manifest.json')
            with open(path, encoding='utf-8') as f:
                manifest = json.load(f)
            manifest['format'] = 'bogus'
            self.assertTrue(schema_errors(MANIFEST_SCHEMA, manifest))

    def test_non_string_qa_notes_fails(self):
        with tempfile.TemporaryDirectory() as d:
            run_cm('init-run', '--out-dir', d, '--query', 'schema test')
            path = os.path.join(d, 'run_manifest.json')
            with open(path, encoding='utf-8') as f:
                manifest = json.load(f)
            manifest['qa_notes'] = ['not', 'a', 'string']
            self.assertTrue(schema_errors(MANIFEST_SCHEMA, manifest))


class TestGeneratedSources(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        run_cm('init-run', '--out-dir', self.tmpdir, '--query', 'schema test')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def register(self, payload):
        return run_cm('register-source', '--json', json.dumps(payload), '--dir', self.tmpdir)

    def test_source_with_published_at_validates_and_keeps_it(self):
        self.register({
            'raw_url': 'https://example.com/post',
            'title': 'Post',
            'published_at': '2024-01-15T00:00:00Z',
        })
        rows = read_jsonl(os.path.join(self.tmpdir, 'sources.jsonl'))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['published_at'], '2024-01-15T00:00:00Z')
        self.assertEqual(schema_errors(SOURCE_SCHEMA, rows[0]), [])

    def test_source_without_published_at_stores_null_and_validates(self):
        self.register({'raw_url': 'https://example.com/undated', 'title': 'Undated'})
        rows = read_jsonl(os.path.join(self.tmpdir, 'sources.jsonl'))
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]['published_at'])
        self.assertEqual(schema_errors(SOURCE_SCHEMA, rows[0]), [])

    def test_wrong_typed_published_at_fails(self):
        self.register({
            'raw_url': 'https://example.com/bad-type',
            'title': 'Bad type',
            'published_at': 123,
        })
        rows = read_jsonl(os.path.join(self.tmpdir, 'sources.jsonl'))
        self.assertEqual(rows[0]['published_at'], 123)
        self.assertTrue(schema_errors(SOURCE_SCHEMA, rows[0]))

    def test_non_datetime_published_at_string_fails(self):
        self.register({
            'raw_url': 'https://example.com/bad-date',
            'title': 'Bad date',
            'published_at': 'not a date',
        })
        rows = read_jsonl(os.path.join(self.tmpdir, 'sources.jsonl'))
        self.assertTrue(schema_errors(SOURCE_SCHEMA, rows[0]))

    def test_partial_dates_round_trip_and_validate(self):
        # The docs record the date "as the source page gives it" and forbid
        # guessing (references/citations.md), so a year, a month or a day
        # must validate without padding a fake day or time.
        dates = ['2024', '2024-01', '2024-01-15', '2024-01-15T09:30:00+02:00']
        for i, value in enumerate(dates):
            self.register({
                'raw_url': f'https://example.com/dated-{i}',
                'title': f'Dated {i}',
                'published_at': value,
            })
        rows = read_jsonl(os.path.join(self.tmpdir, 'sources.jsonl'))
        self.assertEqual([r['published_at'] for r in rows], dates)
        for row in rows:
            self.assertEqual(schema_errors(SOURCE_SCHEMA, row), [], row['published_at'])


class TestGeneratedClaims(unittest.TestCase):
    """claims.jsonl rows as the pipeline writes them — after
    extract_claims.py extract, verify_claim_support.py link and verify —
    validate against claim.schema.json (additionalProperties: false), so
    every field a writer adds is declared there."""

    REPORT = (
        "# Brief\n\n## Summary\n\n"
        "Daily two-question exit tickets improve retention of covered material [1]. "
        "Weekly checks suit content that changes little between lessons [2].\n\n"
        "## Bibliography\n\n"
        '[1] Alpha (2024). "Retention". https://example.com/alpha\n'
        '[2] Beta (2023). "Weekly checks". https://example.com/beta\n'
    )

    def run_script(self, name, *args):
        result = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, name), *args],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def claim_rows(self, d):
        return read_jsonl(os.path.join(d, 'claims.jsonl'))

    def assert_rows_valid(self, rows, stage):
        self.assertTrue(rows, f'{stage}: no claim rows written')
        for row in rows:
            self.assertEqual(schema_errors(CLAIM_SCHEMA, row), [], f'{stage}: {row}')

    def test_extract_link_verify_rows_validate(self):
        with tempfile.TemporaryDirectory() as d:
            run_cm('init-run', '--out-dir', d, '--query', 'schema test')
            self.run_script('evidence_store.py', 'init', '--dir', d)
            sids = []
            for key in ('alpha', 'beta'):
                out = run_cm('register-source', '--dir', d, '--json', json.dumps({
                    'raw_url': f'https://example.com/{key}', 'title': key,
                }))
                sids.append(out['source_id'])
            self.run_script('evidence_store.py', 'add', '--dir', d, '--json', json.dumps({
                'source_id': sids[0], 'evidence_type': 'direct_quote',
                'quote': 'Daily two-question exit tickets improve retention of covered material.',
            }))
            run_cm('assign-display-numbers', '--dir', d)
            report = os.path.join(d, 'report.md')
            with open(report, 'w', encoding='utf-8') as f:
                f.write(self.REPORT)

            self.run_script('extract_claims.py', 'extract', '--report', report, '--dir', d)
            rows = self.claim_rows(d)
            self.assert_rows_valid(rows, 'extract')
            for row in rows:
                for key in ('extraction_id', 'doc_position', '_citation_numbers'):
                    self.assertIn(key, row)

            self.run_script('verify_claim_support.py', 'link', '--dir', d)
            rows = self.claim_rows(d)
            self.assert_rows_valid(rows, 'link')
            self.assertTrue(any(r.get('cited_source_ids') for r in rows))
            self.assertTrue(any(r.get('evidence_ids') for r in rows))

            self.run_script('verify_claim_support.py', 'verify', '--dir', d)
            rows = self.claim_rows(d)
            self.assert_rows_valid(rows, 'verify')
            self.assertTrue(any('_support_score' in r for r in rows))

    def test_wrong_typed_stamp_fails(self):
        row = {
            'claim_id': '0123456789abcdef', 'section_id': 'summary',
            'text': 'x', 'claim_type': 'factual', 'support_status': 'unverified',
        }
        self.assertEqual(schema_errors(CLAIM_SCHEMA, row), [])
        for key, bad in (('doc_position', '3'), ('doc_position', 0),
                         ('extraction_id', 'yesterday'),
                         ('_citation_numbers', ['1']), ('undeclared', 1)):
            self.assertTrue(schema_errors(CLAIM_SCHEMA, {**row, key: bad}), key)


class TestPublishedAtForm(unittest.TestCase):
    """published_at takes ISO 8601 extended form at year, month, day or
    date-time precision, and nothing else."""

    def setUp(self):
        self.assertIn('published_at', SOURCE_SCHEMA['properties'])
        self.PROP = SOURCE_SCHEMA['properties']['published_at']

    def test_accepted_forms(self):
        for ok in (None, '2024', '2024-01', '2024-01-15', '2024-01-15T00:00Z',
                   '2024-01-15T00:00:00Z', '2024-01-15T00:00:00',
                   '2024-01-15T00:00:00.123+05:30'):
            self.assertEqual(schema_errors(self.PROP, ok), [], ok)

    def test_rejected_forms(self):
        for bad in ('January 2024', '15/01/2024', '2024-1-5', '2024-13',
                    '2024-01-32', '20240115', '24', '2024-01-15 00:00:00',
                    '2024-01-15T25:00:00Z', 'unknown', ''):
            self.assertTrue(schema_errors(self.PROP, bad), bad)


class TestValidatorKeywords(unittest.TestCase):
    """The pattern and format: date-time extensions reject, not just accept."""

    def test_pattern_uses_search_with_schema_supplied_anchors(self):
        schema = {'type': 'string', 'pattern': '^[0-9a-f]{16}$'}
        self.assertEqual(schema_errors(schema, '0123456789abcdef'), [])
        self.assertTrue(schema_errors(schema, 'not-hex'))
        self.assertTrue(schema_errors(schema, 'x0123456789abcde'))

    def test_datetime_format_accepts_z_offset_and_offsetless(self):
        schema = {'type': ['string', 'null'], 'format': 'date-time'}
        for ok in ('2024-01-15T00:00:00Z', '2024-01-15T00:00:00',
                   '2024-01-15T00:00:00+02:00', None):
            self.assertEqual(schema_errors(schema, ok), [], ok)
        for bad in ('2024-01-15', '20240115T000000', 'yesterday'):
            self.assertTrue(schema_errors(schema, bad), bad)


if __name__ == '__main__':
    unittest.main()
