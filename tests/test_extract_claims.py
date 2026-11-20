#!/usr/bin/env python3
"""Tests for extract_claims.py CLI."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT = os.path.join(os.path.dirname(__file__), '..', 'scripts', 'extract_claims.py')
FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')


def run_ec(*args: str) -> dict | list:
    """Run extract_claims.py with args."""
    result = subprocess.run(
        [sys.executable, SCRIPT, *args],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f'Exit {result.returncode}: {result.stderr}')
    return json.loads(result.stdout)


SAMPLE_REPORT = """\
---
title: Test Research Report
---

## Executive Summary

This report examines the impact of quantum computing on cryptography [1, 2]. The field has advanced significantly since 2020, with major breakthroughs in error correction.

## Introduction

Quantum computing represents a paradigm shift in computational capability. Researchers at Google demonstrated quantum supremacy in 2019 using a 53-qubit processor [3]. This milestone confirmed theoretical predictions made decades earlier.

## Finding 1

The Shor algorithm can factor large numbers exponentially faster than classical methods [4]. Current RSA-2048 encryption could be broken by a sufficiently large quantum computer. However, such machines are estimated to require millions of physical qubits [5, 6].

## Finding 2

Post-quantum cryptography standards should be adopted within the next 5 years. Organizations should consider hybrid classical-quantum approaches during the transition period. NIST has already standardized several lattice-based algorithms [7].

## Synthesis

Taken together, the evidence suggests that quantum computing poses a real but manageable threat to current cryptographic systems. The timeline for practical quantum attacks remains uncertain, but proactive migration reduces risk substantially.

## Recommendations

Organizations should begin evaluating post-quantum cryptography solutions immediately. Security teams should conduct a cryptographic inventory to identify vulnerable systems. Companies should consider implementing crypto-agility frameworks to enable rapid algorithm switching.

## Bibliography

[1] Smith et al. (2023). Quantum Computing Advances.
[2] Johnson (2024). Cryptographic Implications.
"""


class TestExtract(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # Create empty claims.jsonl
        open(os.path.join(self.tmpdir, 'claims.jsonl'), 'w').close()
        # Write sample report
        self.report_path = os.path.join(self.tmpdir, 'report.md')
        with open(self.report_path, 'w') as f:
            f.write(SAMPLE_REPORT)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_extract_finds_claims(self):
        out = run_ec('extract', '--report', self.report_path, '--dir', self.tmpdir)
        self.assertEqual(out['status'], 'ok')
        self.assertGreater(out['claims_added'], 5)

    def test_extract_idempotent(self):
        out1 = run_ec('extract', '--report', self.report_path, '--dir', self.tmpdir)
        out2 = run_ec('extract', '--report', self.report_path, '--dir', self.tmpdir)
        self.assertEqual(out2['claims_added'], 0)
        self.assertEqual(out2['claims_skipped'], out1['claims_added'])

    def test_claim_types_assigned(self):
        run_ec('extract', '--report', self.report_path, '--dir', self.tmpdir)
        out = run_ec('stats', '--dir', self.tmpdir)
        # Should have at least factual and recommendation types
        self.assertIn('factual', out['by_type'])
        self.assertIn('recommendation', out['by_type'])

    def test_sections_detected(self):
        run_ec('extract', '--report', self.report_path, '--dir', self.tmpdir)
        out = run_ec('stats', '--dir', self.tmpdir)
        self.assertIn('finding_1', out['by_section'])
        self.assertIn('finding_2', out['by_section'])
        self.assertIn('recommendations', out['by_section'])


class TestAdd(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        open(os.path.join(self.tmpdir, 'claims.jsonl'), 'w').close()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_add_and_dedup(self):
        claim = json.dumps({
            'section_id': 'finding_1',
            'text': 'Quantum computers can break RSA encryption.',
            'claim_type': 'factual',
        })
        out1 = run_ec('add', '--json', claim, '--dir', self.tmpdir)
        self.assertEqual(out1['status'], 'added')
        self.assertEqual(len(out1['claim_id']), 16)

        out2 = run_ec('add', '--json', claim, '--dir', self.tmpdir)
        self.assertEqual(out2['status'], 'duplicate')

    def test_add_with_sources(self):
        claim = json.dumps({
            'section_id': 'finding_1',
            'text': 'NIST standardized CRYSTALS-Kyber in 2024.',
            'claim_type': 'factual',
            'cited_source_ids': ['abcdef0123456789'],
            'evidence_ids': ['1234567890abcdef'],
        })
        out = run_ec('add', '--json', claim, '--dir', self.tmpdir)
        self.assertEqual(out['status'], 'added')


class TestListAndStats(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        open(os.path.join(self.tmpdir, 'claims.jsonl'), 'w').close()
        # Add mixed claims
        for sec, text, ctype in [
            ('finding_1', 'The sky appears blue due to Rayleigh scattering.', 'factual'),
            ('finding_1', 'Light wavelengths scatter differently in the atmosphere.', 'factual'),
            ('synthesis', 'Overall, atmospheric optics explains most visual phenomena.', 'synthesis'),
            ('recommendations', 'Researchers should investigate polarization effects further.', 'recommendation'),
        ]:
            run_ec('add', '--json', json.dumps({
                'section_id': sec, 'text': text, 'claim_type': ctype,
            }), '--dir', self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_list_all(self):
        out = run_ec('list', '--dir', self.tmpdir)
        self.assertEqual(out['count'], 4)

    def test_list_by_section(self):
        out = run_ec('list', '--dir', self.tmpdir, '--section', 'finding_1')
        self.assertEqual(out['count'], 2)

    def test_list_by_type(self):
        out = run_ec('list', '--dir', self.tmpdir, '--type', 'recommendation')
        self.assertEqual(out['count'], 1)

    def test_stats(self):
        out = run_ec('stats', '--dir', self.tmpdir)
        self.assertEqual(out['total'], 4)
        self.assertEqual(out['by_type']['factual'], 2)
        self.assertEqual(out['by_type']['synthesis'], 1)
        self.assertEqual(out['by_type']['recommendation'], 1)


class TestListStatsLatestExtraction(unittest.TestCase):
    """list and stats count only the latest extraction (ticket 3.8): the
    same selection verify scores and cited_order_ids numbers — rows of the
    max extraction_id in doc_position order; unstamped (manual add) rows
    never contribute when stamped rows exist; a file with no stamped rows
    at all is one extraction, keep-last per claim_id."""

    E1 = '2026-01-01T00:00:00+00:00'
    E2 = '2026-01-02T00:00:00+00:00'

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

    def write(self, rows):
        with open(os.path.join(self.tmpdir, 'claims.jsonl'), 'w') as f:
            for row in rows:
                f.write(json.dumps(row) + '\n')

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # E1 held a claim whose sentence the report no longer contains
        # (clm_deleted) and an earlier row of clm_kept; E2 is the latest
        # extraction: clm_new (pos 1) and the superseding clm_kept (pos 2).
        # clm_manual is a manual `add` row (no extraction_id).
        self.write([
            self.row('clm_deleted',
                     'The population of Mars is 500 million as of 2025.',
                     status='unsupported', extraction_id=self.E1,
                     doc_position=1),
            self.row('clm_kept', 'Quantum computers can break RSA encryption.',
                     extraction_id=self.E1, doc_position=2),
            self.row('clm_new',
                     'Researchers should investigate lattice schemes.',
                     ctype='recommendation', extraction_id=self.E2,
                     doc_position=1),
            self.row('clm_kept', 'Quantum computers can break RSA encryption.',
                     extraction_id=self.E2, doc_position=2),
            self.row('clm_manual',
                     'The population of Venus is 700 million as of 2025.'),
        ])

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_list_only_latest_extraction_in_doc_order(self):
        out = run_ec('list', '--dir', self.tmpdir)
        self.assertEqual(out['count'], 2)
        self.assertEqual([c['claim_id'] for c in out['claims']],
                         ['clm_new', 'clm_kept'])

    def test_deleted_and_manual_rows_absent(self):
        out = run_ec('list', '--dir', self.tmpdir)
        ids = [c['claim_id'] for c in out['claims']]
        self.assertNotIn('clm_deleted', ids)
        self.assertNotIn('clm_manual', ids)

    def test_stats_only_latest_extraction(self):
        out = run_ec('stats', '--dir', self.tmpdir)
        self.assertEqual(out['total'], 2)
        self.assertEqual(out['by_type'].get('factual'), 1)
        self.assertEqual(out['by_type'].get('recommendation'), 1)
        self.assertEqual(out['by_status'].get('unverified'), 2)

    def test_status_filter_never_resurrects_older_extraction(self):
        # Only E1 carries an unsupported row; filtering first would make E1
        # the "latest" over the filtered set and list clm_deleted.
        out = run_ec('list', '--dir', self.tmpdir, '--status', 'unsupported')
        self.assertEqual(out['count'], 0)

    def test_legacy_file_lists_whole_file_keep_last(self):
        self.write([
            self.row('clm_a', 'The population of Mars is 500 million as of 2025.'),
            self.row('clm_a', 'The population of Mars is 900 million as of 2025.'),
            self.row('clm_b', 'The population of Venus is 700 million as of 2025.'),
        ])
        out = run_ec('list', '--dir', self.tmpdir)
        self.assertEqual(out['count'], 2)
        texts = [c['text'] for c in out['claims']]
        self.assertIn('The population of Mars is 900 million as of 2025.', texts)
        self.assertNotIn('The population of Mars is 500 million as of 2025.', texts)


class TestClaimID(unittest.TestCase):
    """Unit tests for compute_claim_id."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
        from extract_claims import compute_claim_id, classify_claim
        cls.compute_id = staticmethod(compute_claim_id)
        cls.classify = staticmethod(classify_claim)

    def test_deterministic(self):
        id1 = self.compute_id('finding_1', 'Test claim.')
        id2 = self.compute_id('finding_1', 'Test claim.')
        self.assertEqual(id1, id2)

    def test_section_matters(self):
        id1 = self.compute_id('finding_1', 'Same text.')
        id2 = self.compute_id('finding_2', 'Same text.')
        self.assertNotEqual(id1, id2)

    def test_classify_recommendation(self):
        self.assertEqual(
            self.classify('Organizations should adopt PQC immediately.', 'recommendations'),
            'recommendation',
        )

    def test_classify_factual(self):
        self.assertEqual(
            self.classify('RSA-2048 uses 2048-bit keys.', 'finding_1'),
            'factual',
        )

    def test_classify_synthesis(self):
        self.assertEqual(
            self.classify('Taken together, the results indicate a clear trend.', 'synthesis'),
            'synthesis',
        )


class TestBibliographyRule(unittest.TestCase):
    """F2 regression (E1-R1/E1-R12): a '### Sources of funding' subsection
    is body, not a bibliography. On 35d132d everything from it on was
    dropped (only 6 junk claims); all 25 body claims must be extracted,
    and bibliography entries must never become claims."""

    FUNDING_FIXTURE = os.path.join(FIXTURES, 'bibliography', 'funding_subsection_report.md')
    ENTRY_FORMS_FIXTURE = os.path.join(FIXTURES, 'bibliography', 'entry_forms_report.md')

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        open(os.path.join(self.tmpdir, 'claims.jsonl'), 'w').close()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_claims_after_funding_subsection_extracted(self):
        out = run_ec('extract', '--report', self.FUNDING_FIXTURE, '--dir', self.tmpdir)
        self.assertEqual(out['status'], 'ok')
        self.assertEqual(out['claims_added'], 25)
        rows = run_ec('list', '--dir', self.tmpdir)['claims']
        self.assertTrue(
            any('foundation partnered with three universities' in r['text'] for r in rows),
            'first funding sentence must survive as a claim',
        )
        self.assertTrue(
            any('Matching gift programs' in r['text'] for r in rows),
            'last funding sentence must survive as a claim',
        )

    def test_bibliography_entries_are_not_claims(self):
        run_ec('extract', '--report', self.FUNDING_FIXTURE, '--dir', self.tmpdir)
        rows = run_ec('list', '--dir', self.tmpdir)['claims']
        self.assertFalse(
            any(r['section_id'] in ('bibliography', 'sources') for r in rows),
            'bibliography entries are citations, not claims',
        )
        self.assertFalse(any('Alpha Institute' in r['text'] for r in rows))

    def test_postbib_appendix_claims_kept(self):
        run_ec('extract', '--report', self.ENTRY_FORMS_FIXTURE, '--dir', self.tmpdir)
        rows = run_ec('list', '--dir', self.tmpdir)['claims']
        self.assertTrue(
            any('appendix material' in r['text'].lower() for r in rows),
            'post-bibliography appendix stays in claim scope',
        )

    def test_sources_named_body_sections_and_fenced_heading_kept(self):
        """Review fix: only the real bibliography is dropped. '## Data
        sources', '### Sources of funding' and '## Sources of funding' are
        body; a fenced '## Bibliography' example is not a section heading,
        so the prose after the fence stays a claim (the builder's
        section-id skip dropped it)."""
        fixture = os.path.join(FIXTURES, 'bibliography', 'sources_named_sections_report.md')
        run_ec('extract', '--report', fixture, '--dir', self.tmpdir)
        rows = run_ec('list', '--dir', self.tmpdir)['claims']
        texts = ' '.join(r['text'] for r in rows)
        for phrase in ('national registries', 'national foundation paid',
                       'Corporate sponsors', 'Body prose continues',
                       'appendix material'):
            self.assertIn(phrase, texts)
        for entry in ('Alpha Institute', 'Beta Trust', 'Gamma Corp'):
            self.assertNotIn(entry, texts, 'bibliography entries are not claims')
        self.assertNotIn('bibliography', {r['section_id'] for r in rows})

    def test_citation_numbers_exclude_years_and_code(self):
        report = os.path.join(self.tmpdir, 'report.md')
        with open(report, 'w') as f:
            f.write(
                '## Finding\n\n'
                'The Q4 revenue increased by 23 percent [4, 5] while the design from [2024] '
                'and the snippet `config[9]` stay out of the citation numbers.\n'
            )
        run_ec('extract', '--report', report, '--dir', self.tmpdir)
        rows = run_ec('list', '--dir', self.tmpdir)['claims']
        self.assertEqual(rows[0]['_citation_numbers'], [4, 5])


class TestActionSectionClassification(unittest.TestCase):
    """Bug 11: a sentence under a heading that names an action or
    recommendation section (Action Items, Recommendations, Recommendation,
    Next Steps) is a recommendation whatever its wording; only a sentence
    carrying both a citation marker and a number stays factual. On
    bc009a4 every row below but the two pins classified the template's
    uncited action items as factual, and verify --strict failed the
    documented chain at step 8."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
        from extract_claims import classify_claim
        cls.classify = staticmethod(classify_claim)

    def test_template_action_item_is_recommendation(self):
        self.assertEqual(
            self.classify('Adopt daily exit tickets with a cap of two questions.', 'action_items'),
            'recommendation',
        )

    def test_all_four_action_section_ids(self):
        for section_id in ('action_items', 'recommendations', 'recommendation', 'next_steps'):
            self.assertEqual(
                self.classify('Complete the migration within 30 days.', section_id),
                'recommendation',
                section_id,
            )

    def test_cited_sentence_with_number_stays_factual(self):
        self.assertEqual(
            self.classify('Adopt the cadence that lifted retention by 12 points [2].', 'next_steps'),
            'factual',
        )

    def test_cited_sentence_without_number_is_recommendation(self):
        self.assertEqual(
            self.classify('Prefer the weekly cadence for stable classes [3].', 'action_items'),
            'recommendation',
        )

    def test_uncited_sentence_with_number_is_recommendation(self):
        self.assertEqual(
            self.classify('Complete the migration within 30 days.', 'next_steps'),
            'recommendation',
        )

    def test_speculation_wording_in_action_section_is_recommendation(self):
        self.assertEqual(
            self.classify('Pilot deployments might reveal further constraints.', 'action_items'),
            'recommendation',
        )

    def test_bracketed_year_is_not_a_citation_marker(self):
        self.assertEqual(
            self.classify('Review the plan drafted in [2024] again this term.', 'next_steps'),
            'recommendation',
        )

    def test_near_name_heading_keeps_today_classification(self):
        self.assertEqual(
            self.classify('Complete the migration within 30 days.', 'recommended_tools'),
            'factual',
        )

    def test_longer_action_headings_are_action_sections(self):
        # validate_report's required-section gate accepts any '##' heading
        # containing the name, so these headings pass structure; their
        # slug forms must classify like the bare ids.
        for section_id in ('action_items_this_term_', 'next_steps_for_teachers',
                           'recommendation_option_a', 'recommendations_for_districts'):
            self.assertEqual(
                self.classify('Adopt daily exit tickets with a cap of two questions.', section_id),
                'recommendation',
                section_id,
            )

    def test_prefix_match_is_on_whole_slug_words(self):
        for section_id in ('action_plan', 'recommended_actions', 'next_stepsx',
                           'our_recommendation', 'key_findings_and_recommendations'):
            self.assertEqual(
                self.classify('The district runs twelve schools.', section_id),
                'factual',
                section_id,
            )

    def test_non_action_sections_stay_factual(self):
        for section_id in ('summary', 'key_points', 'executive_summary'):
            self.assertEqual(
                self.classify('The district runs twelve schools.', section_id),
                'factual',
                section_id,
            )

    def test_should_rule_still_first(self):
        self.assertEqual(
            self.classify('Teams should adopt the daily cadence.', 'key_points'),
            'recommendation',
        )


class TestTemplateFixtureExtraction(unittest.TestCase):
    """The bug-11 fixture: the quick-brief template filled exactly as
    written. Action Items extract as recommendations (uncited, directive
    wording); Summary and Key Points stay factual."""

    FIXTURE = os.path.join(FIXTURES, 'claims', 'quick_brief_template.md')

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        open(os.path.join(self.tmpdir, 'claims.jsonl'), 'w').close()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_action_items_recommendation_summary_factual(self):
        run_ec('extract', '--report', self.FIXTURE, '--dir', self.tmpdir)
        rows = run_ec('list', '--dir', self.tmpdir)['claims']
        by_section = {}
        for r in rows:
            by_section.setdefault(r['section_id'], set()).add(r['claim_type'])
        self.assertEqual(by_section.get('action_items'), {'recommendation'})
        for section_id in ('summary', 'key_points'):
            self.assertEqual(by_section.get(section_id), {'factual'}, section_id)


class TestExtractionStamping(unittest.TestCase):
    """E1-R8/F13: rows carry extraction_id + doc_position; re-extract
    supersedes, so the latest extraction is exactly the current report
    in document order and never mixes rows from older extractions."""

    REPORT_V1 = (
        '# Stamped Report\n\n'
        '## Finding 1\n\n'
        'First sentence cites the earliest registered source [1].\n'
        'Second sentence cites a later registered source [2].\n'
        'Third sentence exists only in the first version of the report.\n\n'
        '## Bibliography\n\n[1] A. [2] B.\n'
    )
    REPORT_V2 = (
        '# Stamped Report\n\n'
        '## Finding 1\n\n'
        'Second sentence cites a later registered source [2].\n'
        'First sentence cites the earliest registered source [1].\n'
        'A rewritten third sentence replaced the original one entirely.\n\n'
        '## Bibliography\n\n[1] A. [2] B.\n'
    )

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        open(os.path.join(self.tmpdir, 'claims.jsonl'), 'w').close()
        self.report_path = os.path.join(self.tmpdir, 'report.md')
        with open(self.report_path, 'w') as f:
            f.write(self.REPORT_V1)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @staticmethod
    def _latest(claims_path):
        rows = [json.loads(l) for l in open(claims_path) if l.strip()]
        stamped = [r for r in rows if r.get('extraction_id')]
        latest = max(r['extraction_id'] for r in stamped)
        latest_rows = [r for r in stamped if r['extraction_id'] == latest]
        latest_rows.sort(key=lambda r: r['doc_position'])
        return rows, latest_rows

    def test_rows_stamped_in_document_order(self):
        out = run_ec('extract', '--report', self.report_path, '--dir', self.tmpdir)
        rows = run_ec('list', '--dir', self.tmpdir)['claims']
        self.assertEqual(len(rows), 3)
        ids = {r['extraction_id'] for r in rows}
        self.assertEqual(ids, {out['extraction_id']})
        positions = [r['doc_position'] for r in rows]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual([r['text'][:5] for r in rows], ['First', 'Secon', 'Third'])
        self.assertEqual(rows[0]['doc_position'], 1)

    def test_reextract_supersedes_and_latest_extraction_is_current_report(self):
        run_ec('extract', '--report', self.report_path, '--dir', self.tmpdir)
        # The edit swaps the first two sentences and rewrites the third.
        with open(self.report_path, 'w') as f:
            f.write(self.REPORT_V2)
        out2 = run_ec('extract', '--report', self.report_path, '--dir', self.tmpdir)
        self.assertGreater(out2['claims_added'], 0)   # the rewritten sentence
        self.assertGreater(out2['claims_skipped'], 0)  # the two kept sentences

        claims_path = os.path.join(self.tmpdir, 'claims.jsonl')
        all_rows, latest = self._latest(claims_path)
        # Superseded rows stay in the append-only file.
        self.assertGreater(len(all_rows), len(latest))
        self.assertTrue(any('exists only in the first version' in r['text'] for r in all_rows))
        # The latest extraction is exactly the current report, in the
        # current document order — the old third sentence is gone and
        # the swapped order is reflected.
        self.assertEqual([r['text'][:5] for r in latest], ['Secon', 'First', 'A rew'])

    def test_list_shows_only_the_latest_extraction(self):
        """Ticket 3.8: list selects the latest extraction (was: keep-last
        over every claim_id ever extracted, which kept listing a sentence
        the report no longer contains)."""
        run_ec('extract', '--report', self.report_path, '--dir', self.tmpdir)
        with open(self.report_path, 'w') as f:
            f.write(self.REPORT_V2)
        second = run_ec('extract', '--report', self.report_path, '--dir', self.tmpdir)
        out = run_ec('list', '--dir', self.tmpdir)
        # Exactly the current report's sentences; the deleted third
        # sentence's stale claim_id is gone.
        self.assertEqual(out['count'], 3)
        ids = [r['claim_id'] for r in out['claims']]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertFalse(any('exists only in the first version' in r['text']
                             for r in out['claims']))
        # Every listed row comes from the second extraction.
        current = [r for r in out['claims']
                   if r.get('extraction_id') == second['extraction_id']]
        self.assertEqual(len(current), 3)


if __name__ == '__main__':
    unittest.main()
