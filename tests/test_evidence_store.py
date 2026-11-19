#!/usr/bin/env python3
"""Tests for evidence_store.py CLI, including F17 input validation."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT = os.path.join(os.path.dirname(__file__), '..', 'scripts', 'evidence_store.py')

VALID_TYPES = ('direct_quote', 'paraphrase', 'data_point', 'figure_reference', 'methodology')


def run_es_raw(*args: str) -> subprocess.CompletedProcess:
    """Run evidence_store.py with args, return the raw completed process."""
    return subprocess.run(
        [sys.executable, SCRIPT, *args],
        capture_output=True, text=True,
    )


def run_es(*args: str) -> dict | list:
    """Run evidence_store.py with args, return parsed JSON from stdout."""
    result = run_es_raw(*args)
    if result.returncode != 0:
        raise RuntimeError(f'Exit {result.returncode}: {result.stderr}')
    return json.loads(result.stdout)


def register_source(run_dir: str, source_id: str) -> None:
    """Append a source row (source.schema.json shape) to run_dir/sources.jsonl."""
    row = {
        'source_id': source_id,
        'canonical_locator': f'test://{source_id}',
        'raw_url': f'https://example.com/{source_id}',
        'title': f'Test source {source_id}',
        'source_type': 'web',
        'metadata_status': 'unverified',
        'registered_at': '2026-11-18T00:00:00+00:00',
    }
    with open(os.path.join(run_dir, 'sources.jsonl'), 'a') as f:
        f.write(json.dumps(row) + '\n')


class TestInit(unittest.TestCase):
    def test_creates_empty_file(self):
        with tempfile.TemporaryDirectory() as d:
            out = run_es('init', '--dir', d)
            self.assertEqual(out['status'], 'ok')
            path = os.path.join(d, 'evidence.jsonl')
            self.assertTrue(os.path.exists(path))
            self.assertEqual(os.path.getsize(path), 0)


class TestAddEvidence(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        run_es('init', '--dir', self.tmpdir)
        register_source(self.tmpdir, 'abcdef0123456789')
        register_source(self.tmpdir, 'aaaaaaaaaaaaaaaa')
        register_source(self.tmpdir, 'bbbbbbbbbbbbbbbb')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_add_and_dedup(self):
        ev = json.dumps({
            'source_id': 'abcdef0123456789',
            'quote': 'FActScore decomposes generation into atomic facts.',
            'evidence_type': 'direct_quote',
            'locator': 'page 3',
            'retrieval_query': 'factuality evaluation methods',
        })
        out1 = run_es('add', '--json', ev, '--dir', self.tmpdir)
        self.assertEqual(out1['status'], 'added')
        self.assertEqual(len(out1['evidence_id']), 16)

        # Same quote -> duplicate
        out2 = run_es('add', '--json', ev, '--dir', self.tmpdir)
        self.assertEqual(out2['status'], 'duplicate')
        self.assertEqual(out2['evidence_id'], out1['evidence_id'])

    def test_whitespace_normalization(self):
        ev1 = json.dumps({
            'source_id': 'abcdef0123456789',
            'quote': '  FActScore   decomposes   generation  into atomic facts.  ',
            'evidence_type': 'direct_quote',
        })
        ev2 = json.dumps({
            'source_id': 'abcdef0123456789',
            'quote': 'FActScore decomposes generation into atomic facts.',
            'evidence_type': 'direct_quote',
        })
        out1 = run_es('add', '--json', ev1, '--dir', self.tmpdir)
        out2 = run_es('add', '--json', ev2, '--dir', self.tmpdir)
        # Should be same ID due to normalization
        self.assertEqual(out1['evidence_id'], out2['evidence_id'])
        self.assertEqual(out2['status'], 'duplicate')

    def test_different_sources_different_ids(self):
        ev1 = json.dumps({
            'source_id': 'aaaaaaaaaaaaaaaa',
            'quote': 'Same quote text.',
            'evidence_type': 'paraphrase',
        })
        ev2 = json.dumps({
            'source_id': 'bbbbbbbbbbbbbbbb',
            'quote': 'Same quote text.',
            'evidence_type': 'paraphrase',
        })
        out1 = run_es('add', '--json', ev1, '--dir', self.tmpdir)
        out2 = run_es('add', '--json', ev2, '--dir', self.tmpdir)
        self.assertNotEqual(out1['evidence_id'], out2['evidence_id'])
        self.assertEqual(out2['status'], 'added')


class TestAddValidation(unittest.TestCase):
    """F17: unknown evidence_type and unregistered source_id are rejected."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        run_es('init', '--dir', self.tmpdir)
        register_source(self.tmpdir, 'abcdef0123456789')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def read_rows(self) -> list[dict]:
        with open(os.path.join(self.tmpdir, 'evidence.jsonl')) as f:
            return [json.loads(line) for line in f if line.strip()]

    def test_unknown_evidence_type_rejected(self):
        ev = json.dumps({
            'source_id': 'abcdef0123456789',
            'quote': 'Some quote.',
            'evidence_type': 'paraphrse',
        })
        result = run_es_raw('add', '--json', ev, '--dir', self.tmpdir)
        self.assertEqual(result.returncode, 1)
        self.assertIn('paraphrse', result.stderr)
        for valid in VALID_TYPES:
            self.assertIn(valid, result.stderr)
        self.assertEqual(self.read_rows(), [])

    def test_unregistered_source_rejected(self):
        ev = json.dumps({
            'source_id': 'cccccccccccccccc',
            'quote': 'Some quote.',
            'evidence_type': 'direct_quote',
        })
        result = run_es_raw('add', '--json', ev, '--dir', self.tmpdir)
        self.assertEqual(result.returncode, 1)
        self.assertIn('cccccccccccccccc', result.stderr)
        self.assertIn('sources.jsonl', result.stderr)
        self.assertEqual(self.read_rows(), [])

    def test_missing_sources_file_rejects(self):
        with tempfile.TemporaryDirectory() as d:
            run_es('init', '--dir', d)
            ev = json.dumps({
                'source_id': 'abcdef0123456789',
                'quote': 'Some quote.',
                'evidence_type': 'direct_quote',
            })
            result = run_es_raw('add', '--json', ev, '--dir', d)
            self.assertEqual(result.returncode, 1)
            self.assertIn('sources.jsonl', result.stderr)
            with open(os.path.join(d, 'evidence.jsonl')) as f:
                self.assertEqual(f.read(), '')

    def test_valid_add_still_appends(self):
        ev = json.dumps({
            'source_id': 'abcdef0123456789',
            'quote': 'A valid captured paraphrase.',
            'evidence_type': 'paraphrase',
        })
        out = run_es('add', '--json', ev, '--dir', self.tmpdir)
        self.assertEqual(out['status'], 'added')
        rows = self.read_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['evidence_type'], 'paraphrase')

    def test_missing_evidence_type_rejected(self):
        # A missing type must not default to direct_quote: verify_citations_v2
        # checks direct_quote rows verbatim against the page (F17).
        ev = json.dumps({
            'source_id': 'abcdef0123456789',
            'quote': 'An untyped capture.',
        })
        result = run_es_raw('add', '--json', ev, '--dir', self.tmpdir)
        self.assertEqual(result.returncode, 1)
        self.assertIn('evidence_type is required', result.stderr)
        for valid in VALID_TYPES:
            self.assertIn(valid, result.stderr)
        self.assertEqual(self.read_rows(), [])

    def test_malformed_sources_file_rejects_cleanly(self):
        with open(os.path.join(self.tmpdir, 'sources.jsonl'), 'a') as f:
            f.write('\n   \n{"source_id": "abc')  # blank lines, then a torn row
        ev = json.dumps({
            'source_id': 'abcdef0123456789',
            'quote': 'Some quote.',
            'evidence_type': 'direct_quote',
        })
        result = run_es_raw('add', '--json', ev, '--dir', self.tmpdir)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, '')
        err = json.loads(result.stderr)
        self.assertIn('sources.jsonl is malformed', err['error'])
        self.assertEqual(self.read_rows(), [])

    def test_blank_lines_in_sources_file_are_ignored(self):
        with open(os.path.join(self.tmpdir, 'sources.jsonl'), 'a') as f:
            f.write('\n   \n')
        ev = json.dumps({
            'source_id': 'abcdef0123456789',
            'quote': 'Some quote.',
            'evidence_type': 'direct_quote',
        })
        out = run_es('add', '--json', ev, '--dir', self.tmpdir)
        self.assertEqual(out['status'], 'added')
        self.assertEqual(len(self.read_rows()), 1)


class TestListAndExport(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        run_es('init', '--dir', self.tmpdir)
        register_source(self.tmpdir, 'src_aaa')
        register_source(self.tmpdir, 'src_bbb')
        # Add 3 evidence items from 2 sources
        for src, quote in [
            ('src_aaa', 'First quote from source A.'),
            ('src_aaa', 'Second quote from source A.'),
            ('src_bbb', 'Quote from source B.'),
        ]:
            run_es('add', '--json', json.dumps({
                'source_id': src,
                'quote': quote,
                'evidence_type': 'direct_quote',
            }), '--dir', self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_list_all(self):
        out = run_es('list', '--dir', self.tmpdir)
        self.assertEqual(out['count'], 3)

    def test_list_filtered(self):
        out = run_es('list', '--dir', self.tmpdir, '--source-id', 'src_aaa')
        self.assertEqual(out['count'], 2)

        out = run_es('list', '--dir', self.tmpdir, '--source-id', 'src_bbb')
        self.assertEqual(out['count'], 1)

    def test_export(self):
        out = run_es('export', '--dir', self.tmpdir)
        self.assertIsInstance(out, list)
        self.assertEqual(len(out), 3)
        # Each has required fields
        for row in out:
            self.assertIn('evidence_id', row)
            self.assertIn('source_id', row)
            self.assertIn('quote', row)
            self.assertIn('evidence_type', row)
            self.assertIn('captured_at', row)


class TestEvidenceID(unittest.TestCase):
    """Unit tests for compute_evidence_id."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
        from evidence_store import compute_evidence_id, normalize_quote
        cls.compute_id = staticmethod(compute_evidence_id)
        cls.normalize = staticmethod(normalize_quote)

    def test_deterministic(self):
        id1 = self.compute_id('src_a', 'test quote', 'page 1')
        id2 = self.compute_id('src_a', 'test quote', 'page 1')
        self.assertEqual(id1, id2)

    def test_locator_matters(self):
        id1 = self.compute_id('src_a', 'test quote', 'page 1')
        id2 = self.compute_id('src_a', 'test quote', 'page 2')
        self.assertNotEqual(id1, id2)

    def test_normalize_whitespace(self):
        self.assertEqual(
            self.normalize('  hello   world  '),
            'hello world',
        )


if __name__ == '__main__':
    unittest.main()
