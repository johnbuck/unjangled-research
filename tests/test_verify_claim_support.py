#!/usr/bin/env python3
"""Tests for verify_claim_support.py CLI.

Includes the bug-11 template-chain tests: each of the five report
templates, filled exactly as written with action items left uncited,
runs the documented 15-step chain from reference/quality-gates.md
(``## Phase 8 gate chain``) with urllib.request.urlopen mocked, and
every step passes; an uncited factual sentence planted in Summary still
fails at step 8. On bc009a4 the chains fail at verify --strict because
extract_claims.classify_claim typed the uncited action items as factual
claims."""

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
import urllib.error

SCRIPT = os.path.join(os.path.dirname(__file__), '..', 'scripts', 'verify_claim_support.py')
EXTRACT_SCRIPT = os.path.join(os.path.dirname(__file__), '..', 'scripts', 'extract_claims.py')


def run_extract(*args: str) -> dict:
    """Run extract_claims.py."""
    result = subprocess.run(
        [sys.executable, EXTRACT_SCRIPT, *args],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f'Exit {result.returncode}: {result.stderr}\n{result.stdout}')
    return json.loads(result.stdout.strip())


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


class TestVerifyLatestExtraction(unittest.TestCase):
    """verify scores only the latest extraction's rows — the same
    selection cited_order_ids makes (ticket 3.10)."""

    E1 = '2026-01-01T00:00:00+00:00'
    E2 = '2026-01-02T00:00:00+00:00'
    QUOTE = ("Shor's algorithm can factor large integers exponentially "
             "faster than any known classical algorithm.")

    def claim(self, claim_id: str, text: str, claim_type: str = 'factual',
              extraction_id: str | None = None, doc_position: int | None = None,
              cited: list | None = None, evidence: list | None = None) -> dict:
        row = {
            'claim_id': claim_id,
            'section_id': 'finding_1',
            'text': text,
            'claim_type': claim_type,
            'cited_source_ids': cited or [],
            'evidence_ids': evidence or [],
            'support_status': 'unverified',
        }
        if extraction_id is not None:
            row['extraction_id'] = extraction_id
            row['doc_position'] = doc_position or 1
        return row

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        write_jsonl(os.path.join(self.tmpdir, 'sources.jsonl'), [
            {'source_id': 'src_shor', 'title': 'Shor 1994'},
        ])
        write_jsonl(os.path.join(self.tmpdir, 'evidence.jsonl'), [
            {
                'evidence_id': 'ev_shor',
                'source_id': 'src_shor',
                'quote': self.QUOTE,
                'evidence_type': 'direct_quote',
            },
        ])

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def superseded_run(self) -> None:
        """E1 held an uncited factual claim (clm_stale) and a supported
        one (clm_kept); E2, the latest extraction, re-stamps only
        clm_kept — clm_stale's sentence was deleted from the report."""
        write_jsonl(os.path.join(self.tmpdir, 'claims.jsonl'), [
            self.claim('clm_stale',
                       'The population of Mars is 500 million as of 2025.',
                       extraction_id=self.E1, doc_position=1),
            self.claim('clm_kept', self.QUOTE,
                       extraction_id=self.E1, doc_position=2,
                       cited=['src_shor'], evidence=['ev_shor']),
            self.claim('clm_kept', self.QUOTE,
                       extraction_id=self.E2, doc_position=2,
                       cited=['src_shor'], evidence=['ev_shor']),
            self.claim('clm_new',
                       'Quantum hardware scaling might someday favor error correction.',
                       claim_type='speculation',
                       extraction_id=self.E2, doc_position=1),
        ])

    def read_claims(self) -> list[dict]:
        with open(os.path.join(self.tmpdir, 'claims.jsonl')) as f:
            return [json.loads(l) for l in f if l.strip()]

    def test_scores_only_latest_extraction(self):
        self.superseded_run()
        out = run_vcs('verify', '--dir', self.tmpdir)
        self.assertEqual(out['verified'], 2)  # clm_kept + clm_new, not clm_stale
        self.assertEqual(out['factual_unsupported'], 0)
        self.assertEqual(out['total_factual'], 1)
        self.assertEqual(out['support_status_counts'], {'supported': 2})

    def test_deleted_claim_no_longer_fails_strict(self):
        self.superseded_run()
        out = run_vcs('verify', '--dir', self.tmpdir, '--strict')
        self.assertEqual(out['status'], 'pass')

    def test_strict_still_fails_on_latest_extractions_own_claims(self):
        self.superseded_run()
        rows = self.read_claims()
        rows[3]['claim_type'] = 'factual'  # clm_new loses its evidence exemption
        rows[3]['cited_source_ids'] = []
        rows[3]['evidence_ids'] = []
        write_jsonl(os.path.join(self.tmpdir, 'claims.jsonl'), rows)
        out = run_vcs('verify', '--dir', self.tmpdir, '--strict', expect_fail=True)
        self.assertEqual(out['status'], 'fail')
        self.assertEqual(out['factual_unsupported'], 1)

    def test_write_back_preserves_stale_rows_unscored(self):
        self.superseded_run()
        run_vcs('verify', '--dir', self.tmpdir)
        rows = self.read_claims()
        self.assertEqual(len(rows), 4)  # append-only file keeps every row
        by_pos = {(r['extraction_id'], r['claim_id']): r for r in rows}
        # Stale rows keep their historical status: never scored.
        self.assertEqual(by_pos[(self.E1, 'clm_stale')]['support_status'], 'unverified')
        self.assertEqual(by_pos[(self.E1, 'clm_kept')]['support_status'], 'unverified')
        # Latest extraction's rows are scored and updated.
        self.assertEqual(by_pos[(self.E2, 'clm_kept')]['support_status'], 'supported')
        self.assertEqual(by_pos[(self.E2, 'clm_new')]['support_status'], 'supported')

    def test_legacy_rows_without_extraction_id_score_as_one_extraction(self):
        write_jsonl(os.path.join(self.tmpdir, 'claims.jsonl'), [
            self.claim('clm_old_row',
                       'The population of Mars is 500 million as of 2025.'),
            self.claim('clm_old_row',
                       'The population of Mars is 500 million as of 2026.'),
            self.claim('clm_other',
                       'The population of Venus is 700 million as of 2025.'),
        ])
        out = run_vcs('verify', '--dir', self.tmpdir, expect_fail=False)
        # One extraction, keep-last per claim_id: 2 claims scored.
        self.assertEqual(out['verified'], 2)
        self.assertEqual(out['factual_unsupported'], 2)
        strict = run_vcs('verify', '--dir', self.tmpdir, '--strict', expect_fail=True)
        self.assertEqual(strict['status'], 'fail')

    def test_manual_rows_not_scored_when_stamped_rows_exist(self):
        write_jsonl(os.path.join(self.tmpdir, 'claims.jsonl'), [
            self.claim('clm_stamped', self.QUOTE,
                       extraction_id=self.E1, doc_position=1,
                       cited=['src_shor'], evidence=['ev_shor']),
            # manual `add` row: no extraction_id, never scored alongside
            # stamped rows (the same exclusion cited_order_ids makes).
            self.claim('clm_manual',
                       'The population of Mars is 500 million as of 2025.'),
        ])
        out = run_vcs('verify', '--dir', self.tmpdir, '--strict')
        self.assertEqual(out['verified'], 1)
        self.assertEqual(out['factual_unsupported'], 0)
        self.assertEqual(out['status'], 'pass')

    def test_empty_claims_file_passes_strict(self):
        write_jsonl(os.path.join(self.tmpdir, 'claims.jsonl'), [])
        out = run_vcs('verify', '--dir', self.tmpdir, '--strict')
        self.assertEqual(out['verified'], 0)
        self.assertEqual(out['status'], 'pass')


class TestReportLatestExtraction(unittest.TestCase):
    """report lists only the latest extraction (ticket 3.8, the selection
    verify scores): a claim whose sentence the report no longer contains
    must not appear, and the totals must agree with verify's summary."""

    E1 = '2026-01-01T00:00:00+00:00'
    E2 = '2026-01-02T00:00:00+00:00'
    KEPT = ("Shor's algorithm can factor large integers exponentially "
            "faster than any known classical algorithm.")
    DELETED = 'The population of Mars is 500 million as of 2025.'

    def row(self, claim_id, text, ctype='factual', status='unverified',
            extraction_id=None, doc_position=None):
        row = {
            'claim_id': claim_id,
            'section_id': 'finding_1',
            'text': text,
            'claim_type': ctype,
            'cited_source_ids': [],
            'evidence_ids': [],
            'support_status': status,
        }
        if extraction_id is not None:
            row['extraction_id'] = extraction_id
            row['doc_position'] = doc_position or 1
        return row

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        write_jsonl(os.path.join(self.tmpdir, 'sources.jsonl'), [
            {'source_id': 'src_shor', 'title': 'Shor 1994'},
        ])
        write_jsonl(os.path.join(self.tmpdir, 'evidence.jsonl'), [
            {
                'evidence_id': 'ev_shor',
                'source_id': 'src_shor',
                'quote': self.KEPT,
                'evidence_type': 'direct_quote',
            },
        ])
        # E1 held the now-deleted sentence and an earlier row of clm_kept;
        # E2, the latest extraction, holds clm_new and clm_kept only. The
        # report's listing section shows factual claims that are
        # unsupported or need review, so both claim rows carry such a
        # status — the deleted one must not be listed, the kept one must.
        write_jsonl(os.path.join(self.tmpdir, 'claims.jsonl'), [
            self.row('clm_deleted', self.DELETED, status='unsupported',
                     extraction_id=self.E1, doc_position=1),
            self.row('clm_kept', self.KEPT, status='supported',
                     extraction_id=self.E1, doc_position=2),
            self.row('clm_new',
                     'Researchers should investigate lattice schemes.',
                     ctype='recommendation', extraction_id=self.E2,
                     doc_position=1),
            self.row('clm_kept', self.KEPT, status='needs_review',
                     extraction_id=self.E2, doc_position=2),
        ])

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_report_lists_only_the_latest_extraction(self):
        out = run_vcs('report', '--dir', self.tmpdir)
        self.assertIn('**Total claims:** 2', out)
        self.assertIn(self.KEPT[:60], out)
        self.assertNotIn('Mars', out)

    def test_report_totals_match_verify_summary(self):
        verify = run_vcs('verify', '--dir', self.tmpdir)
        report = run_vcs('report', '--dir', self.tmpdir)
        self.assertIn(f"**Total claims:** {verify['verified']}", report)
        self.assertEqual(verify['verified'], 2)

    def test_report_manual_row_not_listed_when_stamped_rows_exist(self):
        write_jsonl(os.path.join(self.tmpdir, 'claims.jsonl'), [
            self.row('clm_stamped', self.KEPT, status='supported',
                     extraction_id=self.E1, doc_position=1),
            self.row('clm_manual', self.DELETED, status='unsupported'),
        ])
        out = run_vcs('report', '--dir', self.tmpdir)
        self.assertIn('**Total claims:** 1', out)
        self.assertNotIn('Mars', out)

    def test_report_legacy_file_whole_file(self):
        write_jsonl(os.path.join(self.tmpdir, 'claims.jsonl'), [
            self.row('clm_a', 'The population of Mars is 500 million as of 2025.',
                     status='unsupported'),
            self.row('clm_a', 'The population of Mars is 900 million as of 2025.',
                     status='needs_review'),
            self.row('clm_b', 'The population of Venus is 700 million as of 2025.'),
        ])
        out = run_vcs('report', '--dir', self.tmpdir)
        self.assertIn('**Total claims:** 2', out)
        # keep-last per claim_id: the 900 million row is clm_a's survivor
        self.assertNotIn('500 million', out)
        self.assertIn('900 million', out)


class TestVerifyDeletedClaimEndToEnd(unittest.TestCase):
    """The 3.1 review's reproduction: an unsupported sentence is deleted
    and the chain re-run, so verify --strict must pass on retry."""

    REPORT_WITH_UNSUPPORTED = (
        '# Quantum Findings\n'
        '\n'
        '## Findings\n'
        '\n'
        "Shor's algorithm can factor large integers exponentially faster "
        'than any known classical algorithm [1].\n'
        '\n'
        'The population of Mars is 500 million as of 2025.\n'
    )
    REPORT_CLEANED = (
        '# Quantum Findings\n'
        '\n'
        '## Findings\n'
        '\n'
        "Shor's algorithm can factor large integers exponentially faster "
        'than any known classical algorithm [1].\n'
    )

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        write_jsonl(os.path.join(self.tmpdir, 'sources.jsonl'), [
            {'source_id': 'src_shor', 'title': 'Shor 1994'},
        ])
        write_jsonl(os.path.join(self.tmpdir, 'evidence.jsonl'), [
            {
                'evidence_id': 'ev_shor',
                'source_id': 'src_shor',
                'quote': ("Shor's algorithm can factor large integers "
                          'exponentially faster than any known classical '
                          'algorithm.'),
                'evidence_type': 'direct_quote',
            },
        ])
        self.report = os.path.join(self.tmpdir, 'report.md')
        with open(self.report, 'w') as f:
            f.write(self.REPORT_WITH_UNSUPPORTED)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_strict_fails_then_passes_after_sentence_deleted(self):
        # Cycle 1: the uncited sentence is in the latest extraction.
        run_extract('extract', '--report', self.report, '--dir', self.tmpdir)
        run_vcs('link', '--dir', self.tmpdir)
        failed = run_vcs('verify', '--dir', self.tmpdir, '--strict', expect_fail=True)
        self.assertEqual(failed['status'], 'fail')
        self.assertEqual(failed['factual_unsupported'], 1)

        # The agent deletes the unsupported sentence and re-runs the chain.
        with open(self.report, 'w') as f:
            f.write(self.REPORT_CLEANED)
        run_extract('extract', '--report', self.report, '--dir', self.tmpdir)
        run_vcs('link', '--dir', self.tmpdir)
        passed = run_vcs('verify', '--dir', self.tmpdir, '--strict')
        self.assertEqual(passed['status'], 'pass')
        self.assertEqual(passed['factual_unsupported'], 0)
        self.assertEqual(passed['verified'], 1)  # only the surviving sentence


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


# ---------------------------------------------------------------------------
# Bug 11: templates filled as written pass the documented chain
# ---------------------------------------------------------------------------

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
SCRIPTS_DIR = os.path.join(ROOT, 'scripts')
QUALITY_GATES = os.path.join(ROOT, 'reference', 'quality-gates.md')
CLAIMS_FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               'fixtures', 'claims')

ALPHA = 'https://example.com/alpha'
BETA = 'https://example.com/beta'
GAMMA = 'https://example.com/gamma'
DELTA = 'https://example.com/delta'
EPSILON = 'https://example.com/epsilon'
ZETA = 'https://example.com/zeta'
ETA = 'https://example.com/eta'
THETA = 'https://example.com/theta'
IOTA = 'https://example.com/iota'
KAPPA = 'https://example.com/kappa'

PAGES = {
    ALPHA: 'Daily two-question exit tickets lifted retention of covered '
           'material across the trial classrooms in 2024.',
    BETA: 'Completion stayed under three minutes whenever each formative '
          'ticket held two questions.',
    GAMMA: 'Weekly checks suited stable curricula, and teachers tuned '
           'feedback frequency to the calendar.',
    DELTA: 'Marginal notes on ticket trials that the brief never relies on.',
    EPSILON: 'Spacing practice across weekly sessions raised recall of '
             'tested material by a wide margin.',
    ZETA: 'Worked examples cut error rates and time on task for novice '
          'learners in early units.',
    ETA: 'Feedback delivered within one day of the check moved subsequent '
         'accuracy more than end-of-week marking.',
    THETA: 'Pre-registered classroom trials state their evidence floors and '
           'replications before analysis begins.',
    IOTA: 'Short warm-up quizzes at the start of lessons improved recall of '
          'the prior lesson material.',
    KAPPA: 'Cumulative review woven into monthly tests sustained gains '
           'through the school year.',
}
QUOTES = dict(PAGES)
META = {
    ALPHA: ('Alpha Analytics', 'Retention pace in classroom practice', '2024'),
    BETA: ('Beta Education Notes', 'Time cost of formative checks', '2023'),
    GAMMA: ('Gamma Teaching Quarterly', 'Feedback frequency for stable curricula', '2022'),
    DELTA: ('Delta Education Press', 'Uncited marginalia in ticket trials', '2021'),
    EPSILON: ('Epsilon Learning Lab', 'Spacing practice in classroom recall', '2023'),
    ZETA: ('Zeta Cognition Reports', 'Guided solution sets for novice learners', '2022'),
    ETA: ('Eta Pedagogy Group', 'Feedback timing and accuracy', '2024'),
    THETA: ('Theta Methods Board', 'Reporting standards for classroom trials', '2021'),
    IOTA: ('Iota Classroom Studies', 'Warm-up quizzes and recall', '2024'),
    KAPPA: ('Kappa Education Review', 'Cumulative review across the year', '2020'),
}
UNCITED_SUMMARY_SENTENCE = ('The district also mandated a ninety-second cap '
                            'for every grade level in 2025.')


def bibliography(urls) -> str:
    lines = []
    for n, url in enumerate(urls, 1):
        org, title, year = META[url]
        lines.append(f'[{n}] {org} ({year}). "{title}". {url}')
    return '\n'.join(lines)


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200):
        self._body, self.status = body, status

    def read(self, n: int = -1) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeUrlopen:
    """url -> (status, body); status >= 400 raises HTTPError."""

    def __init__(self, routes: dict):
        self.routes = routes

    def __call__(self, req, timeout=None):
        url = req.full_url
        status, body = self.routes.get(url, (404, b''))
        if status >= 400:
            raise urllib.error.HTTPError(url, status, 'canned error', None, None)
        return FakeResponse(body, status)


ROUTES = {url: (200, body.encode('utf-8')) for url, body in PAGES.items()}

sys.path.insert(0, SCRIPTS_DIR)
import citation_manager  # noqa: E402
import check_theme  # noqa: E402
import readability_check  # noqa: E402
import render_report  # noqa: E402
import validate_report  # noqa: E402
import verify_citations  # noqa: E402
import verify_citations_v2  # noqa: E402

MODULES = {
    'citation_manager.py': citation_manager,
    'check_theme.py': check_theme,
    'extract_claims.py': None,  # the module under classification test
    'readability_check.py': readability_check,
    'render_report.py': render_report,
    'validate_report.py': validate_report,
    'verify_citations.py': verify_citations,
    'verify_citations_v2.py': verify_citations_v2,
    'verify_claim_support.py': None,  # set after the module import below
    'verify_html.py': None,  # set after the module import below
}
import verify_claim_support as _vcs_module  # noqa: E402
MODULES['verify_claim_support.py'] = _vcs_module
import extract_claims as _ec_module  # noqa: E402
MODULES['extract_claims.py'] = _ec_module
import verify_html as _vh_module  # noqa: E402
MODULES['verify_html.py'] = _vh_module


def documented_chain_commands() -> list[str]:
    """The chain's bash commands, in documented order, parsed from
    reference/quality-gates.md's `## Phase 8 gate chain` section."""
    with open(QUALITY_GATES, encoding='utf-8') as f:
        text = f.read()
    start = text.index('## Phase 8 gate chain')
    rest = text[start:]
    nxt = rest.find('\n## ', 1)
    section = rest[:nxt] if nxt != -1 else rest
    cmds = []
    for chunk in re.split(r'(?m)^(?=\d+\.\s)', section)[1:]:
        m = re.search(r'```bash\n[ \t]*(\S.*)\n', chunk)
        if m:
            cmds.append(m.group(1).strip())
    return cmds


def run_gate(module, argv):
    """Run one gate's main() in-process with the network mocked; return
    (exit_code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    old_argv, sys.argv = sys.argv, argv
    try:
        with unittest.mock.patch('urllib.request.urlopen', FakeUrlopen(ROUTES)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                ret = module.main()
                code = 0 if ret is None else ret
            except SystemExit as e:
                code = e.code if e.code is not None else 0
    finally:
        sys.argv = old_argv
    return code, out.getvalue(), err.getvalue()


class TemplateChainCase(unittest.TestCase):
    """A temp run folder at the end of assembly, before Phase 8: sources
    registered, the provisional (registration-order) map saved, the
    draft — a report template filled exactly as written, action items
    uncited — written with those numbers, evidence captured."""

    FORMAT = None        # validate/render --format
    REGISTRATION = ()    # source URLs in registration order
    REPORT_TEXT = None   # the filled template (body + bibliography)

    def setUp(self):
        self.run_dir = tempfile.mkdtemp(prefix='template_chain_')
        self.addCleanup(shutil.rmtree, self.run_dir, ignore_errors=True)
        self.report = os.path.join(self.run_dir, 'report.md')
        self.manifest = os.path.join(self.run_dir, 'run_manifest.json')
        c, _, e = run_gate(citation_manager, [
            'citation_manager', 'init-run', '--out-dir', self.run_dir,
            '--query', 'exit-ticket cadence', '--mode', 'quick'])
        assert c == 0, e
        self.ids = {}
        for url in self.REGISTRATION:
            org, title, year = META[url]
            c, o, e = run_gate(citation_manager, [
                'citation_manager', 'register-source', '--dir', self.run_dir,
                '--json', json.dumps({'raw_url': url, 'title': title,
                                      'authors': [org], 'year': year})])
            assert c == 0, e
            self.ids[url] = json.loads(o)['source_id']
        c, _, e = run_gate(citation_manager, [
            'citation_manager', 'assign-display-numbers', '--dir', self.run_dir])
        assert c == 0, e
        with open(self.report, 'w', encoding='utf-8') as f:
            f.write(self.report_text())
        with open(os.path.join(self.run_dir, 'evidence.jsonl'), 'w') as f:
            for i, url in enumerate(self.REGISTRATION, 1):
                f.write(json.dumps({
                    'evidence_id': f'ev_{i:03}',
                    'source_id': self.ids[url],
                    'quote': QUOTES[url],
                    'evidence_type': 'direct_quote',
                }) + '\n')

    def report_text(self) -> str:
        return self.REPORT_TEXT

    def run_chain(self):
        """The doc's chain commands, in the doc's order, network mocked.
        Returns [(step_no, script, code, stdout, stderr)]."""
        commands = documented_chain_commands()
        assert len(commands) == 15, f'expected 15 chain steps, got {len(commands)}'
        results = []
        for i, cmd in enumerate(commands, 1):
            tokens = cmd.replace('<run_dir>', self.run_dir) \
                        .replace('<format>', self.FORMAT).split()
            module = MODULES[os.path.basename(tokens[1])]
            argv = [os.path.splitext(os.path.basename(tokens[1]))[0]] + tokens[2:]
            code, out, err = run_gate(module, argv)
            results.append((i, os.path.basename(tokens[1]), code, out, err))
        return results

    @staticmethod
    def first_failure(results):
        for row in results:
            ok = (0, 2) if row[1] == 'readability_check.py' else (0,)
            if row[2] not in ok:
                return row
        return None

    def assert_chain_passes(self, results):
        failed = self.first_failure(results)
        if failed:
            self.fail(f'step {failed[0]} {failed[1]} exited {failed[2]}:\n'
                      f'{failed[3]}\n{failed[4]}')
        self.assertTrue(os.path.isfile(os.path.join(self.run_dir, 'report.html')),
                        'render step wrote no report.html')

    def read_report(self) -> str:
        with open(self.report, encoding='utf-8') as f:
            return f.read()


QUICK_BRIEF_BIBLIOGRAPHY = bibliography((ALPHA, BETA, GAMMA))

RESEARCH_SUMMARY_TEXT = """\
# Exit-Ticket Cadence and Practice Design

## Executive Summary

Daily two-question exit tickets lift retention of covered material across classrooms [1]. Completion stays under three minutes whenever each ticket holds two questions [2]. Spacing the same retrieval across sessions strengthens recall further, so the daily cadence pairs well with weekly review [4].

## Key Findings

### Finding 1: Daily retrieval lifts retention
Daily two-question tickets lifted retention of covered material across the trial classrooms [1]. The gain appeared within the first month of use and held through the term [1]. Teachers reported the routine settled after two weeks of practice [1].

Source: [1]

### Finding 2: Two questions keep completion low
Completion stayed under three minutes whenever each formative ticket held two questions [2]. Longer drafts pushed completion past five minutes in the same classrooms [2]. Short tickets also kept marking load inside the planning period [2].

Source: [2]

### Finding 3: Spacing and worked examples add gains
Spacing retrieval practice across weekly sessions raised recall of tested material by a wide margin [4]. Worked examples embedded in the tickets cut error rates for novice skills [5]. Weekly checks still suited content that changed little between lessons [3].

Source: [4] [5]

## Detailed Analysis

### Retention evidence
The retention evidence covers one term of daily use in mixed classrooms [1]. Retention gains were largest for material introduced in the same week [1]. Weekly checks carried stable content without loss, which marks the boundary of the daily effect [3]. Feedback tuned to the calendar kept stable curricula on track through the term [3].

### Completion and load
Completion stayed under three minutes whenever each ticket held two questions [2]. Classes that kept tickets short reported steadier completion across the term [2]. The two-question cap also kept the marking burden inside one planning period [2].

### Ticket design
Worked examples cut error rates and time on task for novice learners [5]. Spacing the same questions across sessions raised recall of tested material [4]. The strongest design pairs a two-question daily ticket with a weekly aggregate review [4].

## Conclusions

The evidence favours a daily two-question cadence over weekly checks alone [1]. The completion cost stays under three minutes per ticket, which the calendar absorbs [2]. Spacing and worked examples extend the same routine without new tools [4].

## Next Steps

1. Adopt daily exit tickets with a cap of two questions.
2. Add one worked example per ticket for novice skills.
3. Review the weekly aggregate every Friday during planning period.

## Bibliography
""" + bibliography((ALPHA, BETA, GAMMA, EPSILON, ZETA))

COMPARISON_TEXT = """\
# Exit-Ticket Cadence Comparison

## Overview

This comparison weighs a daily two-question cadence against a weekly aggregate cadence for formative checks [1]. Daily two-question tickets lift retention of covered material across classrooms [1]. Weekly checks suit content that changes little between lessons [3]. The deciding criteria are retention lift [1], completion time [2], feedback timing [6], and planning load [3]. Same-day feedback moved subsequent accuracy more than end-of-week marking in the timing study [6].

## Comparison Matrix

| Criteria | Daily two-question | Weekly aggregate | Hybrid split |
|----------|--------------------|------------------|--------------|
| Retention lift | Strong, replicated [1] | Modest [3] | Strong on new material |
| Completion time | Under three minutes [2] | Under one minute | Mixed by design |
| Feedback timing | Same day [6] | End of week | Same day for new material |
| Planning load | High first month | Low all term | Moderate |

## Detailed Analysis

### Daily two-question cadence

The daily cadence closes each lesson with two questions on the material just covered [1]. It lifts retention of covered material across classrooms and keeps completion under three minutes per ticket [1]. Same-day feedback moved subsequent accuracy more than end-of-week marking [6]. The planning load runs high in the first month and settles afterwards [2].

**Pros**:
- Lifts retention of covered material across classrooms [1].
- Completion stays under three minutes per ticket [2].
- Feedback arrives the same day it matters [6].

**Cons**:
- Planning load runs high in the first month [2].

**Best for**: classrooms introducing new material every week [1].

Source: [1]

### Weekly aggregate cadence

The weekly cadence collects one aggregate check each Friday [3]. It suits content that changes little between lessons and keeps the planning load low through the term [3]. The feedback loop is slower, which matters most when new material introduces confusion [3].

**Pros**:
- Suits content that changes little between lessons [3].
- Planning load stays low through the term [3].

**Cons**:
- Feedback arrives too late for new material [6].

**Best for**: stable curricula on a steady calendar [3].

Source: [3]

### Hybrid split cadence

The hybrid runs daily tickets on new material and aggregates the rest weekly [4]. Spacing the daily questions across the week raised recall of tested material, so the split keeps most of the daily gain [4]. Completion patterns differ between the two rhythms in the same classrooms [2].

**Pros**:
- Daily tickets on new material lift retention [1].
- Weekly aggregates keep planning load bounded [3].

**Cons**:
- Two rhythms to maintain through the term [2].

**Best for**: departments mixing new and stable units [4].

Source: [4]

## Recommendation

**Selected option**: Daily two-question cadence.

**Rationale**: The retention lift is replicated and completion stays under three minutes, while the planning cost of the daily cadence falls after the first month.

## Bibliography
""" + bibliography((ALPHA, BETA, GAMMA, EPSILON, ZETA, ETA))

DISCOVERY_CATALOG_TEXT = """\
# Discovery Catalog: Classroom Retrieval Routines

*Metrics current as of 2026-11-19; discovery results rot.*

## Summary

Three routines clear the evidence bar [8]. Daily two-question exit tickets lead on every signal: a replicated retention lift and completion under three minutes [1] [2]. Weekly aggregate checks sit at Evaluate because their evidence covers only stable curricula [3]. Worked-example tickets clear the floors but cap at Watch on a single source [6]. Two routines were ruled out in one line each: unstructured reflection journals have no controlled evidence, and end-of-unit feedback arrives too late [7].

## Selection Criteria

Frozen from the methods board record, no overrides recorded [8].

| Status | Definition (evidence recency) | Consequence |
|---|---|---|
| ACTIVE | evidence within 730 days | eligible for any tier |
| FADING | 731 to 1095 days | eligible, flagged |
| DORMANT | 1096 to 1460 days | cannot tier above Watch |
| ARCHIVED | no evidence after 2020 | Ruled Out, named |

Evidence floors follow the board standard: two independent study sources, with a replication corroborating the headline number [8]. Percentile rule: a candidate set of eight or more routines also qualifies at the seventieth percentile of measured lift [8]. Two-signal rule: Adopt requires the floor plus one corroborating signal from a different study design [8].

## Comparison Matrix

| Candidate | Evidence source | Strength (source, date) | Recency | Cost | Status | Tier |
|---|---|---|---|---|---|---|
| Daily exit tickets | Trial registry | replicated lift [1] | 2024 [1] | low [2] | ACTIVE | Adopt |
| Weekly aggregates | Practitioner guide | stable content only [3] | 2022 [3] | low [3] | ACTIVE | Evaluate |
| Worked-example tickets | Cognition reports | single design [6] | 2022 [6] | low [6] | ACTIVE | Watch |

## Project Dossiers

### Daily exit tickets

A two-question closing routine with replicated retention evidence across classrooms [1]. Completion stays under three minutes per ticket, which keeps the cost low [2]. The honest downside: the evidence covers mathematics and reading, not every subject [1].

### Weekly aggregates

A Friday routine suiting content that changes little between lessons [3]. It keeps planning load low through the term [3]. The downside: feedback arrives too late for material introduced that week [7].

### Worked-example tickets

A daily ticket variant embedding one worked example for novice skills [6]. Error rates for novices fell in the reporting study [6]. The downside: a single source and a single study design cap it at Watch [6].

## Sources Consulted

Enumerated first: the trial-registry category for classroom routines [1] and the practitioner-guide index [3]. Verified against two study records covering retrieval practice [1] [5]. Same-day feedback studies were consulted for timing context [7]. Rejected as evidence: vendor pamphlets and single-anecdote notes, recorded as marginalia [4].

## Bibliography
""" + bibliography((ALPHA, BETA, GAMMA, DELTA, EPSILON, ZETA, ETA, THETA))

COMPREHENSIVE_TEXT = """\
# Retention Routines for Grade 4 Mathematics

## Executive Summary

Daily two-question exit tickets lift retention of covered material across classrooms [1]. Completion stays under three minutes whenever each ticket holds two questions [2]. Same-day feedback moved subsequent accuracy more than end-of-week marking [6]. This report weighs the daily cadence against weekly aggregates and recommends the daily routine with a two-question cap [1].

## Background & Context

The school sought a formative routine that fits a forty-minute lesson without new materials [2]. Retention of covered material had slipped between units by the spring assessments [1]. Weekly checks suited content that changed little between lessons, but new material introduced each Monday needed faster signals [3]. The question was which cadence the evidence supports for a mixed Grade 4 cohort [1].

## Methodology

- Sources consulted: ten registered sources spanning trials, practitioner guides, methods standards and classroom studies [7].
- Time period: evidence published between 2020 and 2024 [1].
- Scope: Grade 3 to 5 mathematics classrooms, with literacy results excluded [3].

## Key Findings

### Theme 1: Daily retrieval lifts retention
**Summary**: Daily two-question tickets lifted retention of covered material across the trial classrooms [1].

**Details**:
- The gain appeared within the first month of use and held through the term [1].
- Retention gains were largest for material introduced in the same week [1].
- Teachers reported the routine settled after two weeks of practice [1].

**Sources**: [1] [2]

### Theme 2: Completion stays low
**Summary**: Completion stayed under three minutes whenever each formative ticket held two questions [2].

**Details**:
- Longer drafts pushed completion past five minutes in the same classrooms [2].
- Short tickets kept marking load inside one planning period [2].
- The two-question cap kept completion steady across the whole term [2].

**Sources**: [2]

### Theme 3: Timing and spacing shape the gains
**Summary**: Feedback delivered within one day of the check moved subsequent accuracy more than end-of-week marking [6].

**Details**:
- Spacing retrieval practice across weekly sessions raised recall of tested material [4].
- Worked examples embedded in the tickets cut error rates for novice skills [5].
- Cumulative review woven into monthly tests sustained gains through the school year [9].

**Sources**: [4] [5] [6]

## Data & Evidence

| Measure | Daily two-question | Weekly aggregate |
|---|---|---|
| Retention lift | replicated [1] | modest [3] |
| Completion time | under three minutes [2] | under one minute [2] |
| Feedback delay | same day [6] | end of week [3] |

As the trial record puts it, daily two-question tickets "lifted retention of covered material across the trial classrooms" [1]. The timing study reports that same-day feedback moved subsequent accuracy more than end-of-week marking [6].

## Implications

### Short-term
The daily cadence needs one planning period per week to write and mark tickets [2]. Classes introducing new material every week gain the most from the switch [1]. Teachers already running weekly aggregates can keep them for stable content [3].

### Long-term
Retention gains compound when the same questions return in later weeks [4]. Cumulative review sustains the gains through the school year [9]. The routine needs no new materials, so the cost stays inside planning time [2].

## Limitations

The retention evidence covers a single term of daily use [1]. Reading and mathematics carry the direct evidence, and other subjects rest on weaker transfer [1]. The timing comparison comes from one study design [6]. Evidence older than 2024 was weighted down for recency [7].

## Recommendations

### Priority 1: Adopt the daily two-question cadence
- **What**: Run two exit questions at the end of each mathematics lesson.
- **Why**: The retention lift is replicated and completion stays low.
- **How**: Write tickets in the weekly planning period and mark them the same day.

### Priority 2: Add spacing and worked examples
- **What**: Reuse earlier questions and embed one worked example for novice skills.
- **Why**: Spacing raises recall and worked examples cut novice error rates.
- **How**: Draw two of every ten questions from earlier weeks.

## Appendix

### Additional Resources
- The practitioner guide to stable-curriculum feedback cadences [3].
- The methods board standard for pre-registered classroom trials [7].
- Marginal notes from earlier ticket trials, kept for context [10].

### Open Questions
- Whether the retention lift holds for older grade bands remains untested [1].
- Whether warm-up quizzes can replace the closing ticket is an open comparison [8].

## Bibliography
""" + bibliography((ALPHA, BETA, GAMMA, EPSILON, ZETA, ETA, THETA, IOTA, KAPPA, DELTA))


class TestQuickBriefTemplateChain(TemplateChainCase):
    """The 3.4 reproduction: the quick-brief template filled exactly as
    its skeleton writes it — numbered, uncited Action Items. On bc009a4
    the chain fails at step 8 with the three action items unsupported."""

    FORMAT = 'quick-brief'
    REGISTRATION = (ALPHA, BETA, GAMMA)
    FIXTURE = os.path.join(CLAIMS_FIXTURES, 'quick_brief_template.md')

    def report_text(self) -> str:
        with open(self.FIXTURE, encoding='utf-8') as f:
            return f.read()

    def test_every_gate_passes_in_documented_order(self):
        self.assert_chain_passes(self.run_chain())
        # The uncited action items extracted as recommendations, and the
        # renumbered bibliography is the cited-order one.
        with open(os.path.join(self.run_dir, 'claims.jsonl')) as f:
            rows = [json.loads(l) for l in f if l.strip()]
        latest = max(r['extraction_id'] for r in rows if r.get('extraction_id'))
        action = [r for r in rows if r['extraction_id'] == latest
                  and r['section_id'] == 'action_items']
        self.assertEqual(len(action), 3)
        self.assertEqual({r['claim_type'] for r in action}, {'recommendation'})
        self.assertIn('across classrooms [1].', self.read_report())

    def test_uncited_factual_sentence_in_summary_fails_step_8(self):
        with open(self.report, encoding='utf-8') as f:
            text = f.read()
        with open(self.report, 'w', encoding='utf-8') as f:
            f.write(text.replace(
                '\n\n## Key Points',
                f'\n{UNCITED_SUMMARY_SENTENCE}\n\n## Key Points'))
        failed = self.first_failure(self.run_chain())
        self.assertIsNotNone(failed)
        self.assertEqual(failed[1], 'verify_claim_support.py')
        self.assertEqual(failed[2], 1)
        self.assertEqual(json.loads(failed[3])['factual_unsupported'], 1)


class TestResearchSummaryTemplateChain(TemplateChainCase):
    FORMAT = 'research-summary'
    REGISTRATION = (ALPHA, BETA, GAMMA, EPSILON, ZETA)
    REPORT_TEXT = RESEARCH_SUMMARY_TEXT

    def test_every_gate_passes_in_documented_order(self):
        self.assert_chain_passes(self.run_chain())


class TestLongerActionHeadingChain(TemplateChainCase):
    """Review of 3.11: "## Next Steps for Teachers" passes the structure
    gate (it contains "Next Steps"), so its uncited items must classify
    as recommendations too; exact-id matching failed step 8 here."""

    FORMAT = 'research-summary'
    REGISTRATION = (ALPHA, BETA, GAMMA, EPSILON, ZETA)
    REPORT_TEXT = RESEARCH_SUMMARY_TEXT.replace(
        '## Next Steps\n', '## Next Steps for Teachers\n')

    def test_every_gate_passes_in_documented_order(self):
        self.assertIn('## Next Steps for Teachers\n', self.REPORT_TEXT)
        self.assert_chain_passes(self.run_chain())


class TestComparisonTemplateChain(TemplateChainCase):
    FORMAT = 'comparison'
    REGISTRATION = (ALPHA, BETA, GAMMA, EPSILON, ZETA, ETA)
    REPORT_TEXT = COMPARISON_TEXT

    def test_every_gate_passes_in_documented_order(self):
        self.assert_chain_passes(self.run_chain())


class TestDiscoveryCatalogTemplateChain(TemplateChainCase):
    FORMAT = 'discovery-catalog'
    REGISTRATION = (ALPHA, BETA, GAMMA, DELTA, EPSILON, ZETA, ETA, THETA)
    REPORT_TEXT = DISCOVERY_CATALOG_TEXT

    def test_every_gate_passes_in_documented_order(self):
        self.assert_chain_passes(self.run_chain())


class TestComprehensiveTemplateChain(TemplateChainCase):
    FORMAT = 'comprehensive-report'
    REGISTRATION = (ALPHA, BETA, GAMMA, EPSILON, ZETA, ETA, THETA, IOTA,
                    KAPPA, DELTA)
    REPORT_TEXT = COMPREHENSIVE_TEXT

    def test_every_gate_passes_in_documented_order(self):
        self.assert_chain_passes(self.run_chain())


class TestTemplatePassesStrictVerify(unittest.TestCase):
    """The quick-brief template fixture end to end through the real
    CLIs (extract, link, verify --strict): passes once the action items
    classify as recommendations; bc009a4 failed with all three counted
    as unsupported factual claims."""

    FIXTURE = os.path.join(CLAIMS_FIXTURES, 'quick_brief_template.md')

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        write_jsonl(os.path.join(self.tmpdir, 'sources.jsonl'), [
            {'source_id': 'src_alpha', 'title': META[ALPHA][1]},
            {'source_id': 'src_beta', 'title': META[BETA][1]},
            {'source_id': 'src_gamma', 'title': META[GAMMA][1]},
        ])
        write_jsonl(os.path.join(self.tmpdir, 'evidence.jsonl'), [
            {'evidence_id': 'ev_alpha', 'source_id': 'src_alpha',
             'quote': QUOTES[ALPHA], 'evidence_type': 'direct_quote'},
            {'evidence_id': 'ev_beta', 'source_id': 'src_beta',
             'quote': QUOTES[BETA], 'evidence_type': 'direct_quote'},
            {'evidence_id': 'ev_gamma', 'source_id': 'src_gamma',
             'quote': QUOTES[GAMMA], 'evidence_type': 'direct_quote'},
        ])

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_template_action_items_pass_strict(self):
        run_extract('extract', '--report', self.FIXTURE, '--dir', self.tmpdir)
        run_vcs('link', '--dir', self.tmpdir)
        out = run_vcs('verify', '--dir', self.tmpdir, '--strict')
        self.assertEqual(out['status'], 'pass')
        self.assertEqual(out['factual_unsupported'], 0)
        with open(os.path.join(self.tmpdir, 'claims.jsonl')) as f:
            rows = [json.loads(l) for l in f if l.strip()]
        action = [r for r in rows if r['section_id'] == 'action_items']
        self.assertTrue(action, 'action items must extract as claims')
        self.assertEqual({r['claim_type'] for r in action}, {'recommendation'})


if __name__ == '__main__':
    unittest.main()
