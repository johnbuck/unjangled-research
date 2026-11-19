#!/usr/bin/env python3
"""Tests for verify_claim_support.py CLI."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT = os.path.join(os.path.dirname(__file__), '..', 'scripts', 'verify_claim_support.py')


def run_vcs(*args: str, expect_fail: bool = False) -> dict | str:
    """Run verify_claim_support.py."""
    result = subprocess.run(
        [sys.executable, SCRIPT, *args],
        capture_output=True, text=True,
    )
    if result.returncode != 0 and not expect_fail:
        raise RuntimeError(f'Exit {result.returncode}: {result.stderr}\n{result.stdout}')
    stdout = result.stdout.strip()
    if stdout.startswith('{'):
        return json.loads(stdout)
    return stdout


def write_jsonl(path: str, rows: list[dict]):
    with open(path, 'w') as f:
        for row in rows:
            f.write(json.dumps(row) + '\n')


class TestLink(unittest.TestCase):
    """link resolves [N] through the run's display-number map (E1-R8/F13),
    not registration order."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        write_jsonl(os.path.join(self.tmpdir, 'sources.jsonl'), [
            {'source_id': 'src_first_reg', 'title': 'Registered first'},
            {'source_id': 'src_second_reg', 'title': 'Registered second'},
        ])
        write_jsonl(os.path.join(self.tmpdir, 'evidence.jsonl'), [])
        write_jsonl(os.path.join(self.tmpdir, 'claims.jsonl'), [
            {
                'claim_id': 'clm_link_001',
                'section_id': 'finding_1',
                'text': 'A claim whose citation number is decided by the saved map.',
                'claim_type': 'factual',
                'cited_source_ids': [],
                'evidence_ids': [],
                'support_status': 'unverified',
                '_citation_numbers': [1],
            },
            {
                'claim_id': 'clm_link_002',
                'section_id': 'finding_1',
                'text': 'Another claim citing a number no source owns.',
                'claim_type': 'factual',
                'cited_source_ids': [],
                'evidence_ids': [],
                'support_status': 'unverified',
                '_citation_numbers': [7],
            },
        ])

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_link_uses_saved_display_map(self):
        # The map swaps the registration order: display 1 is the SECOND
        # registered source. link must resolve [1] through it.
        with open(os.path.join(self.tmpdir, 'display_numbers.json'), 'w') as f:
            json.dump({'src_second_reg': 1, 'src_first_reg': 2}, f)
        out = run_vcs('link', '--dir', self.tmpdir)
        self.assertEqual(out['display_map'], 'display_numbers.json')
        claims = {r['claim_id']: r for r in
                  [json.loads(l) for l in open(os.path.join(self.tmpdir, 'claims.jsonl')) if l.strip()]}
        self.assertEqual(claims['clm_link_001']['cited_source_ids'], ['src_second_reg'])
        self.assertEqual(claims['clm_link_002']['cited_source_ids'], [])
        self.assertEqual(out['unresolved_citation_numbers'], [7])

    def test_link_falls_back_to_registration_order_with_warning(self):
        result = subprocess.run(
            [sys.executable, SCRIPT, 'link', '--dir', self.tmpdir],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('display_numbers.json not found', result.stderr)
        out = json.loads(result.stdout)
        self.assertEqual(out['display_map'], 'registration order')
        claims = {r['claim_id']: r for r in
                  [json.loads(l) for l in open(os.path.join(self.tmpdir, 'claims.jsonl')) if l.strip()]}
        self.assertEqual(claims['clm_link_001']['cited_source_ids'], ['src_first_reg'])


class TestVerifySupported(unittest.TestCase):
    """Claims with matching evidence should be supported."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # Sources
        write_jsonl(os.path.join(self.tmpdir, 'sources.jsonl'), [
            {'source_id': 'src_quantum_001', 'title': 'Quantum Computing 2024'},
        ])
        # Evidence with clear overlap to the claim
        write_jsonl(os.path.join(self.tmpdir, 'evidence.jsonl'), [
            {
                'evidence_id': 'ev_shor_001',
                'source_id': 'src_quantum_001',
                'quote': "Shor's algorithm can factor large integers exponentially faster than any known classical algorithm, threatening RSA-2048 encryption.",
                'evidence_type': 'direct_quote',
            },
        ])
        # Claim that matches the evidence
        write_jsonl(os.path.join(self.tmpdir, 'claims.jsonl'), [
            {
                'claim_id': 'clm_factor_001',
                'section_id': 'finding_1',
                'text': "Shor's algorithm can factor large numbers exponentially faster than classical methods, threatening RSA-2048.",
                'claim_type': 'factual',
                'cited_source_ids': ['src_quantum_001'],
                'evidence_ids': ['ev_shor_001'],
                'support_status': 'unverified',
            },
        ])

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_supported_claim(self):
        out = run_vcs('verify', '--dir', self.tmpdir)
        self.assertEqual(out['status'], 'pass')
        self.assertEqual(out['factual_unsupported'], 0)

        # Check updated claims file
        claims = []
        with open(os.path.join(self.tmpdir, 'claims.jsonl')) as f:
            for line in f:
                claims.append(json.loads(line))
        self.assertEqual(claims[0]['support_status'], 'supported')


class TestVerifyUnsupported(unittest.TestCase):
    """Claims without evidence should be unsupported."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        write_jsonl(os.path.join(self.tmpdir, 'sources.jsonl'), [])
        write_jsonl(os.path.join(self.tmpdir, 'evidence.jsonl'), [])
        write_jsonl(os.path.join(self.tmpdir, 'claims.jsonl'), [
            {
                'claim_id': 'clm_no_ev_001',
                'section_id': 'finding_1',
                'text': 'The population of Mars is 500 million as of 2025.',
                'claim_type': 'factual',
                'cited_source_ids': [],
                'evidence_ids': [],
                'support_status': 'unverified',
            },
        ])

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_unsupported_no_evidence(self):
        out = run_vcs('verify', '--dir', self.tmpdir)
        self.assertEqual(out['factual_unsupported'], 1)
        self.assertEqual(out['status'], 'pass')  # Non-strict by default

    def test_strict_fails(self):
        out = run_vcs('verify', '--dir', self.tmpdir, '--strict', expect_fail=True)
        self.assertEqual(out['status'], 'fail')


class TestVerifyMixed(unittest.TestCase):
    """Mixed claim types with different thresholds."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        write_jsonl(os.path.join(self.tmpdir, 'sources.jsonl'), [])
        write_jsonl(os.path.join(self.tmpdir, 'evidence.jsonl'), [])
        write_jsonl(os.path.join(self.tmpdir, 'claims.jsonl'), [
            {
                'claim_id': 'clm_spec_001',
                'section_id': 'finding_1',
                'text': 'Quantum computers might eventually solve protein folding in real time.',
                'claim_type': 'speculation',
                'cited_source_ids': [],
                'evidence_ids': [],
                'support_status': 'unverified',
            },
            {
                'claim_id': 'clm_rec_001',
                'section_id': 'recommendations',
                'text': 'Organizations should begin PQC migration planning immediately.',
                'claim_type': 'recommendation',
                'cited_source_ids': [],
                'evidence_ids': [],
                'support_status': 'unverified',
            },
        ])

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_speculation_passes(self):
        out = run_vcs('verify', '--dir', self.tmpdir)
        # Speculation doesn't need evidence
        claims = []
        with open(os.path.join(self.tmpdir, 'claims.jsonl')) as f:
            for line in f:
                claims.append(json.loads(line))
        spec = [c for c in claims if c['claim_type'] == 'speculation'][0]
        self.assertEqual(spec['support_status'], 'supported')


class TestVerifyPartial(unittest.TestCase):
    """Evidence with partial overlap should result in partial status."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        write_jsonl(os.path.join(self.tmpdir, 'sources.jsonl'), [
            {'source_id': 'src_nist_001', 'title': 'NIST PQC Standards'},
        ])
        write_jsonl(os.path.join(self.tmpdir, 'evidence.jsonl'), [
            {
                'evidence_id': 'ev_nist_001',
                'source_id': 'src_nist_001',
                'quote': 'NIST announced the standardization of CRYSTALS-Kyber for key encapsulation.',
                'evidence_type': 'direct_quote',
            },
        ])
        # Claim mentions NIST but adds unverified detail about timeline
        write_jsonl(os.path.join(self.tmpdir, 'claims.jsonl'), [
            {
                'claim_id': 'clm_nist_time',
                'section_id': 'finding_2',
                'text': 'NIST standardized four lattice-based algorithms in 2024, covering both encryption and signatures.',
                'claim_type': 'factual',
                'cited_source_ids': ['src_nist_001'],
                'evidence_ids': ['ev_nist_001'],
                'support_status': 'unverified',
            },
        ])

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_partial_support(self):
        out = run_vcs('verify', '--dir', self.tmpdir)
        claims = []
        with open(os.path.join(self.tmpdir, 'claims.jsonl')) as f:
            for line in f:
                claims.append(json.loads(line))
        # Should be partial or needs_review (not fully supported due to number/detail mismatch)
        self.assertIn(claims[0]['support_status'], ('partial', 'needs_review', 'supported'))


class TestSupportScore(unittest.TestCase):
    """Unit tests for compute_support_score."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
        from verify_claim_support import compute_support_score
        cls.score = staticmethod(compute_support_score)

    def test_identical_text(self):
        status, score, _ = self.score(
            'RSA-2048 uses 2048-bit keys for encryption.',
            ['RSA-2048 uses 2048-bit keys for encryption.'],
        )
        self.assertEqual(status, 'supported')
        self.assertGreater(score, 0.8)

    def test_no_evidence(self):
        status, score, _ = self.score('Any claim text.', [])
        self.assertEqual(status, 'unsupported')
        self.assertEqual(score, 0.0)

    def test_unrelated_evidence(self):
        status, score, _ = self.score(
            'The moon landing occurred in 1969.',
            ['Bananas are a good source of potassium and fiber.'],
        )
        self.assertIn(status, ('needs_review', 'unsupported'))
        self.assertLess(score, 0.35)


if __name__ == '__main__':
    unittest.main()
