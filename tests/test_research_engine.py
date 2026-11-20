#!/usr/bin/env python3
"""CLI tests for scripts/research_engine.py (epic 3 entry 2, E3-R6/E3-R4).

The engine is the run's state scaffold: it displays phase instructions
for the selected mode's phase sequence and persists one resumable
research_state.json in the run folder. These tests drive the CLI by
subprocess in temp dirs (HOME redirected, so nothing touches the real
home or the skill directory) and check the state it writes and resumes,
per the ticket's verify criteria."""

import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')
SCRIPTS = os.path.join(ROOT, 'scripts')
ENGINE = os.path.join(SCRIPTS, 'research_engine.py')
CONTINUATION_MD = os.path.join(ROOT, 'reference', 'continuation.md')
STATE_NAME = 'research_state.json'

SKILL_PHASES = [
    'scope', 'plan', 'retrieve', 'triangulate', 'outline_refinement',
    'synthesize', 'critique', 'refine', 'package',
]
MODE_PHASE_SETS = {
    'quick': ['scope', 'retrieve', 'package'],
    'standard': ['scope', 'plan', 'retrieve', 'triangulate',
                 'outline_refinement', 'synthesize', 'package'],
    'deep': SKILL_PHASES,
    'ultradeep': SKILL_PHASES,
}


def run_cli(*args, home):
    env = dict(os.environ)
    env['HOME'] = home
    return subprocess.run(
        [sys.executable, ENGINE, *args],
        capture_output=True, text=True, env=env,
    )


def read_state(run_dir):
    with open(os.path.join(run_dir, STATE_NAME)) as f:
        return json.load(f)


class EngineCLITests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home_dir = os.path.join(self._tmp.name, 'home')
        self.work = os.path.join(self._tmp.name, 'work')
        os.makedirs(self.home_dir)
        os.makedirs(self.work)

    def tearDown(self):
        self._tmp.cleanup()

    def run_dir(self, name='run'):
        path = os.path.join(self.work, name)
        os.makedirs(path, exist_ok=True)
        return path

    # -- init ---------------------------------------------------------------

    def test_init_writes_state_and_displays_first_phase(self):
        run = self.run_dir()
        result = run_cli('--query', 'quantum computing state', '--mode', 'quick',
                         '--dir', run, home=self.home_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        state = read_state(run)
        self.assertEqual(state['query'], 'quantum computing state')
        self.assertEqual(state['mode'], 'quick')
        self.assertEqual(state['phase'], 'scope')
        self.assertEqual([p['phase'] for p in state['phases']],
                         MODE_PHASE_SETS['quick'])
        self.assertEqual(state['phases'][0]['status'], 'displayed')
        self.assertIsNotNone(state['phases'][0]['displayed_at'])
        self.assertEqual(state['phases'][1]['status'], 'pending')
        self.assertEqual(state['run_dir'], run)
        self.assertIn('PHASE 1/3: SCOPE', result.stdout)
        self.assertIn('methodology.md', result.stdout)

    def test_mode_phase_sets_match_skill_docs(self):
        for mode, expected in MODE_PHASE_SETS.items():
            with self.subTest(mode=mode):
                run = self.run_dir(f'run-{mode}')
                result = run_cli('--query', 'q', '--mode', mode,
                                 '--dir', run, '--all', home=self.home_dir)
                self.assertEqual(result.returncode, 0, result.stderr)
                state = read_state(run)
                self.assertEqual([p['phase'] for p in state['phases']], expected)
                self.assertTrue(all(p['status'] == 'displayed'
                                    for p in state['phases']))

    def test_state_file_permissions_match_other_run_files(self):
        """Ticket 3.8: the state file was created 0600 by mkstemp; the
        run's other files come from plain open(), so the modes must agree
        (0o666 & ~umask) whatever the umask is."""
        run = self.run_dir()
        result = run_cli('--query', 'permissions', '--mode', 'quick',
                         '--dir', run, home=self.home_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        sibling = os.path.join(run, 'sibling.jsonl')
        with open(sibling, 'w') as f:
            f.write('{}\n')
        state_mode = stat.S_IMODE(os.stat(os.path.join(run, STATE_NAME)).st_mode)
        self.assertEqual(state_mode, stat.S_IMODE(os.stat(sibling).st_mode))

    def test_default_dir_is_documents_under_home(self):
        result = run_cli('--query', 'PostgreSQL vs Supabase comparison',
                         home=self.home_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        docs = os.path.join(self.home_dir, 'Documents')
        entries = [d for d in os.listdir(docs)
                   if re.fullmatch(r'Postgresql_vs_supabase_comparison_Research_\d{8}', d)]
        self.assertEqual(len(entries), 1, os.listdir(docs))
        state = read_state(os.path.join(docs, entries[0]))
        self.assertEqual(state['mode'], 'standard')

    # -- resume --------------------------------------------------------------

    def test_resume_advances_cursor_in_same_file(self):
        run = self.run_dir()
        state_file = os.path.join(run, STATE_NAME)
        run_cli('--query', 'topic', '--mode', 'standard', '--dir', run,
                home=self.home_dir)
        for i, phase in enumerate(MODE_PHASE_SETS['standard'][1:], start=2):
            result = run_cli('--resume', state_file, '--mode', 'quick',
                             home=self.home_dir)
            self.assertEqual(result.returncode, 0, result.stderr)
            state = read_state(run)
            self.assertEqual(state['phase'], phase)
            self.assertEqual(state['mode'], 'standard',
                             'resumed run must keep its own mode')
            self.assertEqual(state['query'], 'topic')
            self.assertIn(f'PHASE {i}/7', result.stdout)
        with open(state_file) as f:
            finished = f.read()
        result = run_cli('--resume', state_file, home=self.home_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('already displayed', result.stdout)
        with open(state_file) as f:
            self.assertEqual(f.read(), finished,
                             'completed run must not be rewritten')

    def test_init_over_existing_state_resumes_it(self):
        run = self.run_dir()
        run_cli('--query', 'first question', '--mode', 'deep',
                '--dir', run, home=self.home_dir)
        result = run_cli('--query', 'different question', '--mode', 'quick',
                         '--dir', run, home=self.home_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        state = read_state(run)
        self.assertEqual(state['query'], 'first question')
        self.assertEqual(state['mode'], 'deep')
        self.assertEqual([p['phase'] for p in state['phases']], SKILL_PHASES)

    def test_all_displays_every_phase_in_order(self):
        run = self.run_dir()
        result = run_cli('--query', 'q', '--mode', 'deep', '--dir', run,
                         '--all', home=self.home_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        for i, phase in enumerate(SKILL_PHASES, start=1):
            self.assertIn(f'PHASE {i}/9: {phase.upper()}', result.stdout)
        state = read_state(run)
        self.assertEqual(state['phase'], 'package')

    # -- errors ----------------------------------------------------------------

    def test_missing_query_without_resume_is_a_usage_error(self):
        result = run_cli(home=self.home_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--query', result.stderr)

    def test_resume_missing_file_exits_1(self):
        result = run_cli('--resume', os.path.join(self.work, 'nope.json'),
                         home=self.home_dir)
        self.assertEqual(result.returncode, 1)
        self.assertIn('state file not found', result.stderr)

    def test_resume_invalid_json_exits_1(self):
        bad = os.path.join(self.run_dir(), STATE_NAME)
        with open(bad, 'w') as f:
            f.write('{not json')
        result = run_cli('--resume', bad, home=self.home_dir)
        self.assertEqual(result.returncode, 1)
        self.assertIn('Invalid state file', result.stderr)

    def test_resume_tampered_phase_name_exits_1(self):
        bad = os.path.join(self.run_dir(), STATE_NAME)
        run = os.path.dirname(bad)
        run_cli('--query', 'q', '--mode', 'quick', '--dir', run, home=self.home_dir)
        state = read_state(run)
        state['phases'][0]['phase'] = 'mind_probe'
        with open(bad, 'w') as f:
            json.dump(state, f)
        result = run_cli('--resume', bad, home=self.home_dir)
        self.assertEqual(result.returncode, 1)
        self.assertIn('invalid state file', result.stderr)

    # -- no home writes ---------------------------------------------------------

    def test_nothing_written_under_home_or_claude(self):
        run = self.run_dir()
        result = run_cli('--query', 'q', '--mode', 'standard', '--dir', run,
                         '--all', home=self.home_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(os.listdir(self.home_dir), [],
                         'script with --dir must not touch HOME')
        result = run_cli('--resume', os.path.join(run, STATE_NAME), home=self.home_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(os.listdir(self.home_dir), [])

    # -- doc agreement ------------------------------------------------------

    def test_script_and_continuation_name_same_state_location(self):
        with open(ENGINE) as f:
            engine_src = f.read()
        with open(CONTINUATION_MD) as f:
            doc = f.read()
        location = '~/Documents/[Topic]_Research_[YYYYMMDD]/'
        self.assertIn(location, engine_src)
        self.assertIn(location, doc)
        for text, name in ((engine_src, 'research_engine.py'),
                           (doc, 'continuation.md')):
            self.assertNotIn('.claude', text,
                             f'{name} must not name a harness-specific home path')

    def test_continuation_commands_parse_against_scripts(self):
        with open(CONTINUATION_MD) as f:
            doc = f.read()
        # Entry 3.4 replaced continuation.md's numbering command list with a
        # link to the one Phase 8 gate chain; the numbering contract is the
        # link. Any python3 command the doc still names must keep parsing.
        self.assertIn('quality-gates.md#phase-8-gate-chain', doc,
                      'continuation.md must link the canonical gate chain '
                      'for citation numbering')
        commands = re.findall(
            r'python3 (scripts/[a-z_0-9]+\.py)((?: [^`\n]+)?)', doc)
        for script, rest in commands:
            tokens = rest.split()
            sub = None
            if tokens and not tokens[0].startswith('-'):
                sub, tokens = tokens[0], tokens[1:]
            with self.subTest(script=script, sub=sub):
                path = os.path.join(ROOT, script)
                cmd = [sys.executable, path] + ([sub, '--help'] if sub
                                                else ['--help'])
                help_run = subprocess.run(cmd, capture_output=True, text=True)
                self.assertEqual(help_run.returncode, 0,
                                 f'{" ".join(cmd)} failed: {help_run.stderr}')
                for flag in re.findall(r'(--[a-z-]+)', ' '.join(tokens)):
                    self.assertIn(flag, help_run.stdout + help_run.stderr,
                                  f'{script} {sub or ""} does not document {flag}')


if __name__ == '__main__':
    unittest.main()
