#!/usr/bin/env python3
"""End-to-end tests for cited-order bibliography numbering (ticket 1.7,
E1-R8/F13): link resolves [N] through the run's display-number map,
extract supersedes rows so the latest extraction is the current report
in document order, renumber-report rewrites markers and bibliography
together, and the result passes validate_report and parses cleanly in
the renderer's build_sources."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, '..', 'scripts')
FIXTURES = os.path.join(HERE, 'fixtures', 'numbering')

CM = os.path.join(SCRIPTS, 'citation_manager.py')
EC = os.path.join(SCRIPTS, 'extract_claims.py')
VCS = os.path.join(SCRIPTS, 'verify_claim_support.py')
VR = os.path.join(SCRIPTS, 'validate_report.py')

sys.path.insert(0, os.path.abspath(SCRIPTS))


def run_script(script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, script, *args],
        capture_output=True, text=True,
    )


def run_json(script: str, *args: str) -> dict:
    result = run_script(script, *args)
    if result.returncode != 0:
        raise RuntimeError(f'Exit {result.returncode}: {result.stderr}\n{result.stdout}')
    return json.loads(result.stdout)


def read_jsonl(path: str) -> list[dict]:
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


SOURCES = [
    ('alpha', 'https://example.com/alpha', 'Alpha Analytics', 'Retention pace in classroom practice', '2024'),
    ('beta', 'https://example.com/beta', 'Beta Education Notes', 'Time cost of formative checks', '2023'),
    ('gamma', 'https://example.com/gamma', 'Gamma Teaching Quarterly', 'Feedback frequency for stable curricula', '2022'),
    # Registered but never cited by the fixtures: renumber must drop it.
    ('delta', 'https://example.com/delta', 'Delta Drafts', 'Never cited by any fixture report', '2021'),
]


def make_run(tmpdir: str) -> dict:
    """init-run + register the three fixture sources in registration
    order alpha, beta, gamma. Returns {key: source_id}."""
    run_json(CM, 'init-run', '--out-dir', tmpdir, '--query', 'exit tickets', '--mode', 'quick')
    ids = {}
    for key, url, org, title, year in SOURCES:
        payload = json.dumps({
            'raw_url': url, 'title': title, 'authors': [org], 'year': year,
        })
        out = run_json(CM, 'register-source', '--json', payload, '--dir', tmpdir)
        assert out['status'] == 'registered'
        ids[key] = out['source_id']
    return ids


def latest_extraction_rows(claims: list[dict]) -> list[dict]:
    stamped = [r for r in claims if r.get('extraction_id')]
    latest = max(r['extraction_id'] for r in stamped)
    rows = [r for r in stamped if r['extraction_id'] == latest]
    rows.sort(key=lambda r: r['doc_position'])
    return rows


class TestNumberingEndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.ids = make_run(self.tmpdir)
        self.report = os.path.join(self.tmpdir, 'report.md')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_full_flow(self):
        ids = self.ids

        # Provisional registration-order map is saved for the draft.
        mapping = run_json(CM, 'assign-display-numbers', '--dir', self.tmpdir)
        self.assertEqual(mapping, {ids['alpha']: 1, ids['beta']: 2, ids['gamma']: 3,
                                   ids['delta']: 4})
        with open(os.path.join(self.tmpdir, 'display_numbers.json')) as f:
            self.assertEqual(json.load(f), mapping)

        # Draft written with the provisional numbers.
        shutil.copy(os.path.join(FIXTURES, 'quick_brief_v1.md'), self.report)
        out = run_json(EC, 'extract', '--report', self.report, '--dir', self.tmpdir)
        self.assertEqual(out['status'], 'ok')
        self.assertGreater(out['claims_added'], 0)

        rows = read_jsonl(os.path.join(self.tmpdir, 'claims.jsonl'))
        for row in rows:
            self.assertIn('extraction_id', row)
            self.assertIn('doc_position', row)

        link = run_json(VCS, 'link', '--dir', self.tmpdir)
        self.assertEqual(link['display_map'], 'display_numbers.json')
        self.assertEqual(link['unresolved_citation_numbers'], [])

        def claim_by_prefix(prefix):
            matches = [r for r in read_jsonl(os.path.join(self.tmpdir, 'claims.jsonl'))
                       if r['text'].startswith(prefix)]
            self.assertTrue(matches, f'no claim starts with {prefix!r}')
            return matches[0]

        # link mapped [N] through the provisional map, in document order.
        self.assertEqual(claim_by_prefix('Daily two-question exit tickets improve')['cited_source_ids'], [ids['beta']])
        self.assertEqual(claim_by_prefix('Completion stays under three minutes')['cited_source_ids'], [ids['gamma']])
        self.assertEqual(claim_by_prefix('Weekly checks suit content')['cited_source_ids'], [ids['alpha']])

        # The edit: citation order changes (alpha now cited first), a
        # sentence is re-cited, one bullet is removed.
        shutil.copy(os.path.join(FIXTURES, 'quick_brief_v2.md'), self.report)
        out2 = run_json(EC, 'extract', '--report', self.report, '--dir', self.tmpdir)
        self.assertGreater(out2['claims_added'], 0)   # new/changed sentences
        self.assertGreater(out2['claims_skipped'], 0)  # superseded unchanged ones
        run_json(VCS, 'link', '--dir', self.tmpdir)

        claims = read_jsonl(os.path.join(self.tmpdir, 'claims.jsonl'))
        latest = latest_extraction_rows(claims)
        texts = ' '.join(r['text'] for r in latest)
        # Latest extraction is exactly the current report.
        self.assertIn("alpha team's classroom trial", texts)
        self.assertNotIn('The team must decide by Friday', texts)  # v1-only sentence
        # v1-only sentences are gone from the latest extraction even
        # though their rows are still in the append-only file.
        self.assertFalse(any(
            r['section_id'] == 'summary' and r['text'].startswith('Daily two-question exit tickets improve')
            for r in latest))
        self.assertFalse(any(
            r['section_id'] == 'key_points' and r['text'].startswith('Weekly checks suit content')
            for r in latest))
        # ...but their superseded rows remain in the file.
        self.assertTrue(any(
            r['section_id'] == 'summary' and r['text'].startswith('Daily two-question exit tickets improve')
            for r in claims if r['extraction_id'] != latest[0]['extraction_id']))

        # First-citation order of the latest extraction: alpha, gamma, beta.
        order = []
        for r in latest:
            for sid in r['cited_source_ids']:
                if sid not in order:
                    order.append(sid)
        self.assertEqual(order, [ids['alpha'], ids['gamma'], ids['beta']])

        # Renumber: map + report rewritten together. Delta, registered but
        # never cited, is dropped from map and bibliography.
        ren = run_json(CM, 'renumber-report', '--dir', self.tmpdir)
        self.assertEqual(ren['status'], 'ok')
        self.assertEqual(ren['cited_sources'], 3)
        self.assertEqual(ren['display_numbers'],
                         {ids['alpha']: 1, ids['gamma']: 2, ids['beta']: 3})
        self.assertNotIn(ids['delta'], ren['display_numbers'])
        with open(os.path.join(self.tmpdir, 'display_numbers.json')) as f:
            self.assertEqual(json.load(f), ren['display_numbers'])

        with open(self.report) as f:
            text = f.read()
        self.assertNotIn('example.com/delta', text)

        # Body markers follow the new numbers.
        from bibliography import extract_citations, reader_facing_text
        cited = extract_citations(reader_facing_text(text))
        self.assertEqual(cited[:3], [1, 2, 1])  # summary: alpha, gamma, alpha
        self.assertEqual(sorted(set(cited)), [1, 2, 3])

        # Bibliography regenerated in cited order, in the export format.
        self.assertIn(
            '[1] Alpha Analytics (2024). "Retention pace in classroom practice". https://example.com/alpha',
            text)
        self.assertIn(
            '[2] Gamma Teaching Quarterly (2022). "Feedback frequency for stable curricula". https://example.com/gamma',
            text)
        self.assertIn(
            '[3] Beta Education Notes (2023). "Time cost of formative checks". https://example.com/beta',
            text)

        # validate_report passes: no gaps, nothing uncited.
        vr = run_script(VR, '--report', self.report, '--format', 'quick-brief')
        self.assertEqual(vr.returncode, 0, f'{vr.stdout}\n{vr.stderr}')

        # build_render_model.build_sources parses clean titles.
        import build_render_model as brm
        parsed = brm.parse_report(text)
        sources = brm.build_sources(parsed['bib_body'])
        self.assertEqual(len(sources), 3)
        titles = [s['title'] for s in sources]
        self.assertEqual(titles, [
            'Retention pace in classroom practice',
            'Feedback frequency for stable curricula',
            'Time cost of formative checks',
        ])
        urls = [s['url'] for s in sources]
        self.assertEqual(urls, [SOURCES[0][1], SOURCES[2][1], SOURCES[1][1]])  # cited order

        # export-bibliography matches the renumbered report.
        exp = run_script(CM, 'export-bibliography', '--dir', self.tmpdir, '--style', 'markdown')
        self.assertEqual(exp.returncode, 0)
        self.assertIn(
            '[2] Gamma Teaching Quarterly (2022). "Feedback frequency for stable curricula". https://example.com/gamma',
            exp.stdout)

    def test_renumber_is_idempotent(self):
        run_json(CM, 'assign-display-numbers', '--dir', self.tmpdir)
        shutil.copy(os.path.join(FIXTURES, 'quick_brief_v1.md'), self.report)
        run_json(EC, 'extract', '--report', self.report, '--dir', self.tmpdir)
        run_json(VCS, 'link', '--dir', self.tmpdir)
        run_json(CM, 'renumber-report', '--dir', self.tmpdir)
        with open(self.report) as f:
            once = f.read()
        run_json(CM, 'renumber-report', '--dir', self.tmpdir)
        with open(self.report) as f:
            twice = f.read()
        self.assertEqual(once, twice)

    def test_renumber_rewrites_appendix_markers(self):
        """Post-bibliography appendices are body: their markers must be
        rewritten too, not just the pre-bibliography body's."""
        run_json(CM, 'assign-display-numbers', '--dir', self.tmpdir)
        ids = self.ids
        with open(self.report, 'w') as f:
            f.write(
                '# Brief\n\n## Summary\n\n'
                'Beta comes first in the citation order of this appendix-checking report [2].\n'
                'Alpha arrives second in the citation order of this appendix-checking report [1].\n\n'
                '## Bibliography\n\n[1] Alpha. [2] Beta.\n\n'
                '## Appendix\n\n'
                'The appendix also leans on the beta findings for its extra commentary [2].\n'
            )
        run_json(EC, 'extract', '--report', self.report, '--dir', self.tmpdir)
        run_json(VCS, 'link', '--dir', self.tmpdir)
        ren = run_json(CM, 'renumber-report', '--dir', self.tmpdir)
        # Cited order: beta first, alpha second.
        self.assertEqual(ren['display_numbers'], {ids['beta']: 1, ids['alpha']: 2})
        with open(self.report) as f:
            text = f.read()
        self.assertIn('## Appendix', text)
        # The appendix marker was rewritten through the map: old [2] (beta)
        # becomes new [1]. The stale marker must be gone.
        self.assertIn('extra commentary [1].', text)
        self.assertNotIn('extra commentary [2]', text)
        # And the pre-bibliography body was rewritten too: old [2] (beta)
        # became [1], old [1] (alpha) became [2].
        self.assertIn('Beta comes first in the citation order of this appendix-checking report [1].', text)
        self.assertNotIn('Beta comes first in the citation order of this appendix-checking report [2]', text)
        self.assertIn('Alpha arrives second in the citation order of this appendix-checking report [2].', text)

    def test_cited_order_assign_standalone(self):
        shutil.copy(os.path.join(FIXTURES, 'quick_brief_v1.md'), self.report)
        run_json(EC, 'extract', '--report', self.report, '--dir', self.tmpdir)
        run_json(VCS, 'link', '--dir', self.tmpdir)
        # No map saved: link resolved through registration order, so the
        # cited-order map would change what the report's [N] mean.
        refused = run_script(CM, 'assign-display-numbers', '--dir', self.tmpdir, '--cited-order')
        self.assertEqual(refused.returncode, 1)
        self.assertIn('registration order', refused.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.tmpdir, 'display_numbers.json')))
        # --force is the explicit standalone override.
        mapping = run_json(CM, 'assign-display-numbers', '--dir', self.tmpdir,
                           '--cited-order', '--force')
        # v1 cites beta first, then gamma, then alpha.
        self.assertEqual(mapping, {
            self.ids['beta']: 1,
            self.ids['gamma']: 2,
            self.ids['alpha']: 3,
        })
        with open(os.path.join(self.tmpdir, 'display_numbers.json')) as f:
            self.assertEqual(json.load(f), mapping)


class TestOutOfOrderSteps(unittest.TestCase):
    """Running a step out of order or twice must either be harmless or
    fail loudly without writing — never silently re-point a [N]."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.ids = make_run(self.tmpdir)
        self.report = os.path.join(self.tmpdir, 'report.md')
        self.map_path = os.path.join(self.tmpdir, 'display_numbers.json')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def draft_extract_link(self, fixture='quick_brief_v1.md'):
        shutil.copy(os.path.join(FIXTURES, fixture), self.report)
        run_json(EC, 'extract', '--report', self.report, '--dir', self.tmpdir)
        run_json(VCS, 'link', '--dir', self.tmpdir)

    def read(self, path):
        with open(path) as f:
            return f.read()

    def test_cited_order_before_renumber_refuses(self):
        """The builder's named footgun: --cited-order between the
        provisional assign and renumber-report used to overwrite the map
        renumber reads as the report's numbering, so renumber left
        markers unchanged under a reordered bibliography."""
        run_json(CM, 'assign-display-numbers', '--dir', self.tmpdir)
        self.draft_extract_link()
        before = self.read(self.map_path)
        result = run_script(CM, 'assign-display-numbers', '--dir', self.tmpdir, '--cited-order')
        self.assertEqual(result.returncode, 1)
        self.assertIn('renumber-report', result.stderr)
        self.assertIn('conflicts', result.stderr)
        self.assertEqual(self.read(self.map_path), before, 'map must not be written')
        # The intended step still works and gives the cited order.
        ren = run_json(CM, 'renumber-report', '--dir', self.tmpdir)
        ids = self.ids
        self.assertEqual(ren['display_numbers'], {ids['beta']: 1, ids['gamma']: 2, ids['alpha']: 3})

    def test_assign_after_renumber_keeps_numbers(self):
        """Re-running the default assign after renumber used to reset the
        map to registration order, so the next link resolved the report's
        cited-order markers to the wrong sources."""
        run_json(CM, 'assign-display-numbers', '--dir', self.tmpdir)
        self.draft_extract_link()
        ren = run_json(CM, 'renumber-report', '--dir', self.tmpdir)
        report_after = self.read(self.report)

        again = run_json(CM, 'assign-display-numbers', '--dir', self.tmpdir)
        for sid, n in ren['display_numbers'].items():
            self.assertEqual(again[sid], n, 'existing numbers are kept')
        self.assertEqual(again[self.ids['delta']], 4, 'uncited source appended')

        run_json(EC, 'extract', '--report', self.report, '--dir', self.tmpdir)
        run_json(VCS, 'link', '--dir', self.tmpdir)
        latest = latest_extraction_rows(read_jsonl(os.path.join(self.tmpdir, 'claims.jsonl')))
        first = next(r for r in latest if r['cited_source_ids'])
        self.assertEqual(first['cited_source_ids'], [self.ids['beta']])
        run_json(CM, 'renumber-report', '--dir', self.tmpdir)
        self.assertEqual(self.read(self.report), report_after)

    def test_source_registered_after_renumber_gets_next_number(self):
        run_json(CM, 'assign-display-numbers', '--dir', self.tmpdir)
        self.draft_extract_link()
        run_json(CM, 'renumber-report', '--dir', self.tmpdir)
        eps = run_json(CM, 'register-source', '--dir', self.tmpdir, '--json', json.dumps({
            'raw_url': 'https://example.com/eps', 'title': 'Epsilon pilot', 'year': '2020',
        }))['source_id']
        mapping = run_json(CM, 'assign-display-numbers', '--dir', self.tmpdir)
        self.assertEqual(mapping[eps], 5)  # after the kept 1-3 and delta's 4
        text = self.read(self.report).replace(
            'weekly this term.', 'weekly this term, per a district pilot of exit tickets [5].', 1)
        with open(self.report, 'w') as f:
            f.write(text)
        run_json(EC, 'extract', '--report', self.report, '--dir', self.tmpdir)
        run_json(VCS, 'link', '--dir', self.tmpdir)
        ren = run_json(CM, 'renumber-report', '--dir', self.tmpdir)
        self.assertEqual(ren['display_numbers'][eps], 1)  # now cited first
        self.assertNotIn(self.ids['delta'], ren['display_numbers'])
        vr = run_script(VR, '--report', self.report, '--format', 'quick-brief')
        self.assertEqual(vr.returncode, 0, vr.stdout)

    def test_renumber_refuses_claims_stale_against_report(self):
        """An edit that drops a source's only citations, renumbered without
        re-extracting, would keep that source in the bibliography."""
        run_json(CM, 'assign-display-numbers', '--dir', self.tmpdir)
        self.draft_extract_link()
        text = self.read(self.report).replace(' [3].', '.')  # drop every gamma marker
        with open(self.report, 'w') as f:
            f.write(text)
        map_before = self.read(self.map_path)
        result = run_script(CM, 'renumber-report', '--dir', self.tmpdir)
        self.assertEqual(result.returncode, 1)
        self.assertIn(self.ids['gamma'], result.stderr)
        self.assertIn('extract', result.stderr)
        self.assertEqual(self.read(self.report), text)
        self.assertEqual(self.read(self.map_path), map_before)

    def test_renumber_after_extract_without_link_refuses(self):
        run_json(CM, 'assign-display-numbers', '--dir', self.tmpdir)
        self.draft_extract_link()
        run_json(EC, 'extract', '--report', self.report, '--dir', self.tmpdir)  # no link
        result = run_script(CM, 'renumber-report', '--dir', self.tmpdir)
        self.assertEqual(result.returncode, 1)
        self.assertIn('link', result.stderr)


class TestRenumberFailures(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.ids = make_run(self.tmpdir)
        self.report = os.path.join(self.tmpdir, 'report.md')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_renumber_without_saved_map_fails(self):
        shutil.copy(os.path.join(FIXTURES, 'quick_brief_v1.md'), self.report)
        run_json(EC, 'extract', '--report', self.report, '--dir', self.tmpdir)
        run_json(VCS, 'link', '--dir', self.tmpdir)
        result = run_script(CM, 'renumber-report', '--dir', self.tmpdir)
        self.assertEqual(result.returncode, 1)
        self.assertIn('display_numbers.json not found', result.stderr)

    def test_renumber_stale_marker_fails(self):
        run_json(CM, 'assign-display-numbers', '--dir', self.tmpdir)
        with open(self.report, 'w') as f:
            f.write(
                '# Brief\n\n## Summary\n\n'
                'Daily two-question exit tickets improve retention of covered material [2].\n'
                'Completion stays under three minutes when the ticket holds two questions [3].\n'
                'Weekly checks suit content that changes little between lessons [1].\n'
                'A rogue marker cites a number no source owns [9].\n\n'
                '## Bibliography\n\n[1] A. [2] B. [3] C.\n'
            )
        run_json(EC, 'extract', '--report', self.report, '--dir', self.tmpdir)
        link = run_json(VCS, 'link', '--dir', self.tmpdir)
        self.assertEqual(link['unresolved_citation_numbers'], [9])
        result = run_script(CM, 'renumber-report', '--dir', self.tmpdir)
        self.assertEqual(result.returncode, 1)
        self.assertIn('[9]', result.stderr)
        # Nothing was written: report and map unchanged.
        with open(self.report) as f:
            self.assertIn('[9]', f.read())
        with open(os.path.join(self.tmpdir, 'display_numbers.json')) as f:
            self.assertEqual(json.load(f),
                             {self.ids['alpha']: 1, self.ids['beta']: 2,
                              self.ids['gamma']: 3, self.ids['delta']: 4})

    def test_cited_order_without_extraction_fails(self):
        run_json(CM, 'assign-display-numbers', '--dir', self.tmpdir)
        result = run_script(CM, 'assign-display-numbers', '--dir', self.tmpdir, '--cited-order')
        self.assertEqual(result.returncode, 1)
        self.assertIn('no extraction rows', result.stderr)

    def test_cited_order_unknown_source_fails(self):
        run_json(CM, 'assign-display-numbers', '--dir', self.tmpdir)
        bogus = '0123456789abcdef'
        with open(os.path.join(self.tmpdir, 'claims.jsonl'), 'w') as f:
            f.write(json.dumps({
                'claim_id': 'a' * 16, 'section_id': 'summary', 'text': 'X ' * 20,
                'claim_type': 'factual', 'cited_source_ids': [bogus],
                'evidence_ids': [], 'support_status': 'unverified',
                'extraction_id': '2026-11-18T00:00:00.000000+00:00', 'doc_position': 1,
            }) + '\n')
        result = run_script(CM, 'assign-display-numbers', '--dir', self.tmpdir, '--cited-order')
        self.assertEqual(result.returncode, 1)
        self.assertIn(bogus, result.stderr)


if __name__ == '__main__':
    unittest.main()
