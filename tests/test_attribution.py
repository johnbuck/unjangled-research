#!/usr/bin/env python3
"""Attribution regression tests (ticket 3.5, E3-R7/F23): ATTRIBUTION.md
claims only what the code does. Every scripts/*.py is named; every file
the doc calls "verbatim" or "unchanged" is byte-identical to its upstream
copy under archive/07-199bio-deep-research; the "bibliography aliases"
claim appears only if validate_report.py implements aliases; the Lato
credit names the SIL OFL and the license file exists; and no term from
the local, gitignored .leak-denylist appears in the public doc (skipped
when that file is absent, so this file carries no private names)."""

import os
import re
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOC = os.path.join(ROOT, 'ATTRIBUTION.md')
SCRIPTS_DIR = os.path.join(ROOT, 'scripts')
ARCHIVE_DIR = os.path.join(ROOT, 'archive', '07-199bio-deep-research', 'scripts')
VALIDATE_REPORT = os.path.join(ROOT, 'scripts', 'validate_report.py')
OFL = os.path.join(ROOT, 'themes', 'neutral', 'LICENSE-OFL.txt')

# Inherited scripts still allowed to be called verbatim/unchanged. None
# remain: entry 3.7 re-worded verify_html.py's line after epic-render-fidelity
# rewrote it, so every changed file is described as modified/adapted.
UNCHANGED = set()

def read(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


def leak_denylist_path():
    """The private .leak-denylist (gitignored): in this checkout's root, or
    in the main checkout's root when this is a git worktree. None if absent."""
    candidates = [os.path.join(ROOT, '.leak-denylist')]
    try:
        common = subprocess.run(
            ['git', '-C', ROOT, 'rev-parse', '--path-format=absolute',
             '--git-common-dir'], capture_output=True, text=True,
            timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        common = ''
    if common:
        candidates.append(os.path.join(os.path.dirname(common),
                                       '.leak-denylist'))
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def leak_hits(text, denylist_path):
    """Denylist lines that match text, using the pre-commit hook's format:
    plain lines are case-insensitive fixed strings, 're:' lines are
    case-insensitive regexes, '#' lines and blank lines are ignored. Returns
    line numbers only, so a failure never prints a private term."""
    hits = []
    low = text.lower()
    with open(denylist_path, encoding='utf-8') as fh:
        for number, raw in enumerate(fh, 1):
            entry = raw.strip()
            if not entry or entry.startswith('#'):
                continue
            if entry.startswith('re:'):
                if re.search(entry[3:], text, re.IGNORECASE):
                    hits.append(number)
            elif entry.lower() in low:
                hits.append(number)
    return hits


def bullets(text):
    """Yield each markdown bullet: a '- ' line plus its indented wrap."""
    current = []
    for line in text.splitlines():
        if line.startswith('- '):
            if current:
                yield '\n'.join(current)
            current = [line]
        elif current and (line.startswith('  ') or not line.strip()):
            if line.strip():
                current.append(line)
            else:
                yield '\n'.join(current)
                current = []
        elif current:
            yield '\n'.join(current)
            current = []
    if current:
        yield '\n'.join(current)


def verbatim_named_scripts(text):
    """scripts/*.py files named in bullets that say verbatim/unchanged."""
    named = set()
    for bullet in bullets(text):
        low = bullet.lower()
        if 'verbatim' in low or 'unchanged' in low:
            named.update(re.findall(r'scripts/([A-Za-z0-9_]+\.py)', bullet))
    return named


class AttributionTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.doc = read(DOC)

    def test_every_script_is_attributed(self):
        shipped = sorted(os.path.basename(p) for p in
                         os.listdir(SCRIPTS_DIR) if p.endswith('.py'))
        # Match the full scripts/<name> path: a bare basename check would
        # let theme.py hide behind check_theme.py.
        missing = [name for name in shipped
                   if 'scripts/' + name not in self.doc]
        self.assertEqual([], missing,
                         'scripts missing from ATTRIBUTION.md: %s' % missing)

    def test_verbatim_claims_match_archive_byte_for_byte(self):
        named = verbatim_named_scripts(self.doc)
        self.assertEqual(
            UNCHANGED, named,
            'files called verbatim/unchanged (%s) must be exactly %s; '
            'update the doc or UNCHANGED together' % (
                sorted(named), sorted(UNCHANGED)))
        for name in sorted(named):
            ours = os.path.join(SCRIPTS_DIR, name)
            theirs = os.path.join(ARCHIVE_DIR, name)
            self.assertTrue(os.path.isfile(theirs),
                            'no archive copy to compare for %s' % name)
            with open(ours, 'rb') as fh:
                ours_bytes = fh.read()
            with open(theirs, 'rb') as fh:
                theirs_bytes = fh.read()
            self.assertEqual(
                theirs_bytes, ours_bytes,
                '%s is called verbatim but differs from its archive copy'
                % name)

    def test_bibliography_aliases_claim_only_if_implemented(self):
        if 'bibliography aliases' in self.doc.lower():
            source = read(VALIDATE_REPORT)
            self.assertIn(
                'alias', source,
                'ATTRIBUTION.md claims bibliography aliases but '
                'validate_report.py implements none')

    def test_lato_ofl_credit(self):
        self.assertIn('Lato', self.doc)
        self.assertIn('SIL Open Font License', self.doc)
        self.assertIn('themes/neutral/LICENSE-OFL.txt', self.doc)
        self.assertTrue(os.path.isfile(OFL),
                        'themes/neutral/LICENSE-OFL.txt does not exist')
        self.assertIn('Lato', read(OFL))

    def test_no_private_names(self):
        path = leak_denylist_path()
        if path is None:
            self.skipTest('.leak-denylist absent (private, gitignored)')
        hits = leak_hits(self.doc, path)
        self.assertEqual(
            [], hits, 'ATTRIBUTION.md matches .leak-denylist lines %s'
            % hits)

if __name__ == '__main__':
    unittest.main()
