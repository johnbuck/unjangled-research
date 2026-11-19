#!/usr/bin/env python3
"""
Citation Manager — stable source identity and run manifest management.

CLI subcommands:
  init-run             Create run_manifest.json + empty artifact JSONL files
  register-source      Append a source to sources.jsonl, return source_id
  assign-display-numbers  Generate stable_id -> display_number mapping
  export-bibliography   Render bibliography from sources.jsonl
  renumber-report       Renumber the report's citations in cited order

Source identity:
  source_id = sha256(canonical_locator)[:16]
  canonical_locator = doi:..., arxiv:..., or normalized URL

Display numbers:
  assign-display-numbers saves the run's map to display_numbers.json
  (registration order by default; --cited-order numbers only the sources
  the report cites, in first-citation order taken from cited_source_ids
  in claims.jsonl, latest extraction, document order). verify_claim_
  support.py link resolves [N] through that file; export-bibliography
  numbers entries by it.

Full numbering flow (epic 3 documents this sequence):
  init-run -> register-source (each) -> assign-display-numbers
  -> write report draft with those numbers -> extract_claims.py extract
  -> verify_claim_support.py link -> renumber-report (rebuilds the map
  in cited order and rewrites the report in one step)
  -> export-bibliography
  After any later report edit: re-run extract, link, renumber-report.
  Re-running any step is safe:
  - renumber-report is idempotent, and it exits 1 without writing when
    claims.jsonl does not match the report (re-run extract and link);
  - assign-display-numbers keeps every saved number and only appends
    newly registered sources, so a source added after renumbering gets
    the next free number to cite it with;
  - assign-display-numbers --cited-order is the standalone cited-order
    mode (saves the map without touching a report). It exits 1 instead
    of changing a number the current map (or registration order, when
    none is saved) gives a source, because renumber-report and link read
    the report's markers through that map. --force overrides.

All state is append-only JSONL. No mutable citation numbers in state files.
"""

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse

# Shared bibliography rule (E1-R1) for splitting the report and matching
# citation markers. CITATION_RE finds the [N] / [N, M] groups; mask_code
# is the helper's offset-preserving code mask (fences and inline spans),
# used so markers inside code are never renumbered.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from bibliography import (  # noqa: E402
    CITATION_RE,
    mask_code,
    reader_facing_text,
    split_bibliography,
)

DISPLAY_MAP_FILENAME = 'display_numbers.json'


# ---------------------------------------------------------------------------
# Canonical locator normalization
# ---------------------------------------------------------------------------

DOI_RE = re.compile(r'(?:https?://(?:dx\.)?doi\.org/|doi:)(10\.\d{4,}/\S+)', re.IGNORECASE)
ARXIV_RE = re.compile(r'(?:https?://arxiv\.org/abs/|arxiv:)(\d{4}\.\d{4,}(?:v\d+)?)', re.IGNORECASE)

# URL query params that are tracking noise, not content identifiers
TRACKING_PARAMS = frozenset([
    'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
    'ref', 'source', 'fbclid', 'gclid', 'mc_cid', 'mc_eid',
])


def canonicalize_locator(raw_url: str) -> str:
    """Derive a canonical locator from a raw URL or identifier string.

    Priority: DOI > arXiv > normalized URL.
    """
    # DOI
    m = DOI_RE.search(raw_url)
    if m:
        return f'doi:{m.group(1).rstrip(".")}'

    # arXiv
    m = ARXIV_RE.search(raw_url)
    if m:
        return f'arxiv:{m.group(1)}'

    # Normalized URL: lowercase scheme+host, strip fragment and tracking params
    parsed = urlparse(raw_url)
    scheme = (parsed.scheme or 'https').lower()
    host = (parsed.hostname or '').lower()
    path = parsed.path.rstrip('/')
    # Filter query params
    if parsed.query:
        pairs = []
        for part in parsed.query.split('&'):
            kv = part.split('=', 1)
            if kv[0].lower() not in TRACKING_PARAMS:
                pairs.append(part)
        query = '&'.join(sorted(pairs))
    else:
        query = ''
    return urlunparse((scheme, host, path, '', query, ''))


def compute_source_id(canonical_locator: str) -> str:
    """sha256(canonical_locator)[:16] hex."""
    return hashlib.sha256(canonical_locator.encode('utf-8')).hexdigest()[:16]


# ---------------------------------------------------------------------------
# JSONL helpers
# ---------------------------------------------------------------------------

def append_jsonl(path: str, obj: dict) -> None:
    with open(path, 'a') as f:
        f.write(json.dumps(obj, ensure_ascii=False) + '\n')


def read_jsonl(path: str) -> list[dict]:
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


# ---------------------------------------------------------------------------
# Display-number map and citation order
# ---------------------------------------------------------------------------

def display_map_path(run_dir: str) -> str:
    return os.path.join(run_dir, DISPLAY_MAP_FILENAME)


def load_display_map(run_dir: str) -> "dict[str, int] | None":
    """Read display_numbers.json -> {source_id: display_number}, or None."""
    path = display_map_path(run_dir)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def save_display_map(run_dir: str, mapping: dict[str, int]) -> str:
    path = display_map_path(run_dir)
    with open(path, 'w') as f:
        json.dump(mapping, f, indent=2)
        f.write('\n')
    return path


def registration_order_map(sources: list[dict]) -> dict[str, int]:
    """Registration-order numbering over unique source_ids (gapless)."""
    mapping: dict[str, int] = {}
    for src in sources:
        sid = src.get('source_id')
        if sid and sid not in mapping:
            mapping[sid] = len(mapping) + 1
    return mapping


def cited_order_ids(claims_rows: list[dict]) -> "list[str] | None":
    """Source ids in first-citation order, latest extraction only.

    Rows of the latest extraction_id (the max in claims.jsonl) are sorted
    by doc_position — document order — and their cited_source_ids are
    collected in row order, deduplicated keeping first occurrence. Rows
    without an extraction_id (manual `add`) never contribute. Returns
    None when claims.jsonl holds no stamped rows.
    """
    stamped = [r for r in claims_rows if r.get('extraction_id')]
    if not stamped:
        return None
    latest = max(r['extraction_id'] for r in stamped)
    rows = [r for r in stamped if r.get('extraction_id') == latest]
    rows.sort(key=lambda r: r.get('doc_position', float('inf')))
    ids: list[str] = []
    seen = set()
    for row in rows:
        for sid in row.get('cited_source_ids', []):
            if sid not in seen:
                seen.add(sid)
                ids.append(sid)
    return ids


def cited_order_map(run_dir: str) -> dict[str, int]:
    """Cited-only, first-citation-order numbering from claims.jsonl.

    Fails loudly (exit 1) when claims.jsonl holds no extraction rows or
    cites ids that are not registered in sources.jsonl.
    """
    claims_path = os.path.join(run_dir, 'claims.jsonl')
    sources_path = os.path.join(run_dir, 'sources.jsonl')
    claims = read_jsonl(claims_path)
    sources = read_jsonl(sources_path)

    ids = cited_order_ids(claims)
    if ids is None:
        print(json.dumps({
            'error': f'no extraction rows in {claims_path} — run '
                     '"extract_claims.py extract" before cited-order numbering',
        }), file=sys.stderr)
        sys.exit(1)

    known = {s.get('source_id') for s in sources}
    unknown = [sid for sid in ids if sid not in known]
    if unknown:
        print(json.dumps({
            'error': 'cited source_ids not registered in sources.jsonl',
            'source_ids': unknown,
        }), file=sys.stderr)
        sys.exit(1)

    return {sid: i for i, sid in enumerate(ids, 1)}


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_init_run(args: argparse.Namespace) -> None:
    """Create run_manifest.json and empty JSONL artifact files."""
    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)

    artifact_paths = {
        'sources': 'sources.jsonl',
        'evidence': 'evidence.jsonl',
        'claims': 'claims.jsonl',
        'report': 'report.md',
    }

    manifest = {
        'version': '3.0.0',
        'query': args.query or '',
        'mode': args.mode,
        'started_at': datetime.now(timezone.utc).isoformat(),
        'finished_at': None,
        'assumptions': [],
        'provider_config': {
            'primary': 'search-cli',
            'scholarly': None,
        },
        'report_dir': out_dir,
        'artifact_paths': artifact_paths,
        'continuation': None,
    }

    manifest_path = os.path.join(out_dir, 'run_manifest.json')
    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write('\n')

    # Create empty artifact files
    for name in ('sources', 'evidence', 'claims'):
        p = os.path.join(out_dir, artifact_paths[name])
        if not os.path.exists(p):
            open(p, 'w').close()

    print(json.dumps({'status': 'ok', 'manifest': manifest_path, 'dir': out_dir}))


def cmd_register_source(args: argparse.Namespace) -> None:
    """Register a source, append to sources.jsonl, print source_id."""
    data = json.loads(args.json)
    raw_url = data.get('raw_url', data.get('url', ''))
    if not raw_url:
        print(json.dumps({'error': 'raw_url is required'}), file=sys.stderr)
        sys.exit(1)

    canonical = data.get('canonical_locator') or canonicalize_locator(raw_url)
    source_id = compute_source_id(canonical)

    sources_path = os.path.join(args.dir, 'sources.jsonl')

    # Check for duplicate
    existing = read_jsonl(sources_path)
    for row in existing:
        if row.get('source_id') == source_id:
            print(json.dumps({
                'status': 'duplicate',
                'source_id': source_id,
                'canonical_locator': canonical,
            }))
            return

    source = {
        'source_id': source_id,
        'canonical_locator': canonical,
        'raw_url': raw_url,
        'title': data.get('title', ''),
        'authors': data.get('authors'),
        'year': data.get('year'),
        'published_at': data.get('published_at'),
        'source_type': data.get('source_type', 'web'),
        'metadata_status': data.get('metadata_status', 'unverified'),
        'registered_at': datetime.now(timezone.utc).isoformat(),
    }
    append_jsonl(sources_path, source)
    print(json.dumps({
        'status': 'registered',
        'source_id': source_id,
        'canonical_locator': canonical,
    }))


def extend_display_map(saved: dict[str, int], sources: list[dict]) -> dict[str, int]:
    """Keep every saved number; give each registered source that has no
    number yet the next free one, in registration order."""
    mapping = dict(saved)
    nxt = max(mapping.values(), default=0) + 1
    for sid in registration_order_map(sources):
        if sid not in mapping:
            mapping[sid] = nxt
            nxt += 1
    return mapping


def map_conflicts(current: dict[str, int], new: dict[str, int]) -> list[str]:
    """Ways ``new`` would change what an existing [N] means: a source
    whose number changes, or a number that would point at a different
    source. Dropping entries is not a conflict (a marker for a dropped
    number fails loudly in renumber-report)."""
    current_by_num = {n: sid for sid, n in current.items()}
    out = []
    for sid, n in new.items():
        if sid in current and current[sid] != n:
            out.append(f'{sid}: [{current[sid]}] would become [{n}]')
        elif sid not in current and n in current_by_num:
            out.append(f'[{n}] would move from {current_by_num[n]} to {sid}')
    return out


def cmd_assign_display_numbers(args: argparse.Namespace) -> None:
    """Map stable source IDs to display numbers and save them to the run.

    Default: registration order over every registered source — the
    provisional numbering the draft is written with. When the run
    already has a saved map, its numbers are kept and only newly
    registered sources are appended, so re-running it never changes
    what a written [N] means.

    --cited-order: only the sources the report cites, in first-citation
    order read from cited_source_ids in claims.jsonl (latest extraction,
    document order). It refuses (exit 1) to replace a current numbering
    it would change — the saved map, or registration order when none is
    saved, which is what link resolved the report's markers through —
    because link and renumber-report would then read the report's
    markers through the wrong map. renumber-report is the step that
    renumbers a report; --force overrides when no report uses the
    current numbering.

    Both modes write display_numbers.json, which link,
    export-bibliography and renumber-report read.
    """
    sources_path = os.path.join(args.dir, 'sources.jsonl')
    sources = read_jsonl(sources_path)
    saved = load_display_map(args.dir)

    if args.cited_order:
        mapping = cited_order_map(args.dir)
        current = saved if saved is not None else registration_order_map(sources)
        conflicts = map_conflicts(current, mapping)
        if conflicts and not args.force:
            where = (display_map_path(args.dir) if saved is not None
                     else 'registration order (no display_numbers.json saved; '
                          'link falls back to it)')
            print(json.dumps({
                'error': 'cited-order numbering would change what existing [N] '
                         f'markers mean under the current numbering, {where}. '
                         'A report written with the current numbers would then '
                         'be read through the wrong map by link and '
                         'renumber-report. Run "renumber-report --dir <run>" to '
                         'renumber the report and save the cited-order map '
                         'together, or pass --force if no report uses the '
                         'current numbering',
                'conflicts': conflicts,
            }), file=sys.stderr)
            sys.exit(1)
    else:
        mapping = extend_display_map(saved or {}, sources)

    save_display_map(args.dir, mapping)
    print(json.dumps(mapping, indent=2))


def _format_bib_entry(number: int, src: dict) -> str:
    """One bibliography entry: [N] Author (Year). "Title". URL

    No markdown link (the renderer must read the title from the quoted
    segment), and no double period: the author segment keeps its own
    punctuation, the title drops a trailing period, and the URL is bare.
    """
    authors = src.get('authors')
    author_str = ''
    if authors:
        names = [str(a).strip() for a in authors if str(a).strip()]
        if len(names) == 1:
            author_str = names[0]
        elif len(names) == 2:
            author_str = f'{names[0]} & {names[1]}'
        elif names:
            author_str = f'{names[0]} et al.'
    year = src.get('year')
    year_str = f'({year})' if year else '(n.d.)'
    title = (src.get('title') or 'Untitled').strip().rstrip('.')
    url = (src.get('raw_url') or '').strip()
    head = f'[{number}] '
    if author_str:
        head += f'{author_str} '
    line = f'{head}{year_str}. "{title}". {url}'
    return line.rstrip()


def cmd_export_bibliography(args: argparse.Namespace) -> None:
    """Generate bibliography from sources.jsonl, numbered by the run's
    display-number map when one has been saved (registration order
    otherwise). A cited-order map exports exactly the cited sources."""
    sources_path = os.path.join(args.dir, 'sources.jsonl')
    sources = read_jsonl(sources_path)

    # Deduplicate by source_id, preserve order
    seen = set()
    unique = []
    for src in sources:
        if src['source_id'] not in seen:
            seen.add(src['source_id'])
            unique.append(src)

    saved_map = load_display_map(args.dir)
    if saved_map is not None:
        unique = [s for s in unique if s.get('source_id') in saved_map]
        unique.sort(key=lambda s: saved_map[s['source_id']])
        numbering = {s['source_id']: saved_map[s['source_id']] for s in unique}
    else:
        numbering = registration_order_map(sources)

    style = args.style

    if style == 'markdown':
        lines = ['## Bibliography', '']
        for src in unique:
            lines.append(_format_bib_entry(numbering[src['source_id']], src))
        print('\n'.join(lines))

    elif style == 'json':
        out = []
        for src in unique:
            out.append({
                'display_number': numbering[src['source_id']],
                'source_id': src['source_id'],
                'canonical_locator': src['canonical_locator'],
                'title': src.get('title', ''),
                'authors': src.get('authors'),
                'year': src.get('year'),
                'raw_url': src.get('raw_url', ''),
            })
        print(json.dumps(out, indent=2, ensure_ascii=False))

    else:
        print(f'Unknown style: {style}', file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# renumber-report
# ---------------------------------------------------------------------------

def _rewrite_markers(text: str, old_num_to_sid: dict, new_map: dict) -> tuple[str, list[int], int, set]:
    """Rewrite every citation marker in ``text`` through the old map to the
    new numbers. Markers inside fenced code or code spans are left alone.
    Returns (new_text, stale_numbers, rewritten_count, source_ids_cited)."""
    masked = mask_code(text)
    out = []
    last = 0
    stale: list[int] = []
    cited: set = set()
    count = 0
    for m in CITATION_RE.finditer(masked):
        nums = [int(x.strip()) for x in m.group(1).split(',')]
        new_nums = []
        ok = True
        for n in nums:
            sid = old_num_to_sid.get(n)
            if sid is not None:
                cited.add(sid)
            if sid is None or sid not in new_map:
                ok = False
                stale.append(n)
                break
            new_nums.append(new_map[sid])
        if not ok:
            continue
        out.append(text[last:m.start()])
        out.append('[' + ', '.join(str(n) for n in new_nums) + ']')
        last = m.end()
        count += 1
    out.append(text[last:])
    return ''.join(out), stale, count, cited


def cmd_renumber_report(args: argparse.Namespace) -> None:
    """Renumber the report's citations in cited order.

    Builds the cited-only, first-citation-order map from claims.jsonl
    (latest extraction), saves it as the run's display_numbers.json, and
    rewrites the report: every body [N] marker goes through
    old-number -> source_id -> new-number, and the bibliography section
    is regenerated from the new map. A bibliography that does not match
    the body's markers is a defect, so both are rewritten together.
    """
    run_dir = args.dir
    report_path = args.report or os.path.join(run_dir, 'report.md')
    if not os.path.exists(report_path):
        print(json.dumps({'error': f'Report not found: {report_path}'}), file=sys.stderr)
        sys.exit(1)

    # The OLD map is the one the report's current markers were written
    # with. Without it the old numbers are unknowable.
    old_map = load_display_map(run_dir)
    if old_map is None:
        print(json.dumps({
            'error': f'{display_map_path(run_dir)} not found — the report\'s '
                     'current numbers cannot be mapped back to sources. Run '
                     '"assign-display-numbers --dir <run>" first',
        }), file=sys.stderr)
        sys.exit(1)
    old_num_to_sid = {int(num): sid for sid, num in old_map.items()}

    new_map = cited_order_map(run_dir)  # exits 1 on bad claims data

    sources_path = os.path.join(run_dir, 'sources.jsonl')
    by_sid = {}
    for src in read_jsonl(sources_path):
        by_sid.setdefault(src.get('source_id'), src)

    with open(report_path) as f:
        text = f.read()

    before, section = split_bibliography(text)
    if section is None:
        # No bibliography yet: everything is body; one is appended below.
        heading_line = '## Bibliography'
        body = text
        tail = ''
    else:
        heading_start = len(before)
        heading_line_end = text.find('\n', heading_start)
        if heading_line_end == -1:
            heading_line_end = len(text)
        heading_line = text[heading_start:heading_line_end].rstrip('\r')
        after = reader_facing_text(text)
        tail = after[len(before):]
        body = text[:heading_start]

    body_new, stale_body, n_body, cited_body = _rewrite_markers(body, old_num_to_sid, new_map)
    tail_new, stale_tail, n_tail, cited_tail = _rewrite_markers(tail, old_num_to_sid, new_map)
    stale = sorted(set(stale_body + stale_tail))
    if stale:
        print(json.dumps({
            'error': 'report cites number(s) with no source in the current '
                     'display map and cited set — re-run extract_claims.py '
                     'extract and verify_claim_support.py link, then renumber. '
                     'If they are current, the marker sits where extract does '
                     'not read claims (text before the first ## heading): '
                     'move the citation into a section',
            'stale_markers': [f'[{n}]' for n in stale],
        }), file=sys.stderr)
        sys.exit(1)
    # Every source the claims cite must be cited by the report's markers
    # read through the saved map. If not, claims.jsonl is stale (the
    # report changed after the last extract/link) or link resolved the
    # markers through a different map than the one saved now — either
    # way the new numbering would be built from the wrong citations.
    not_in_report = [sid for sid in new_map if sid not in (cited_body | cited_tail)]
    if not_in_report:
        print(json.dumps({
            'error': 'claims.jsonl cites source(s) that the report\'s markers '
                     'do not cite through the saved display map — the report '
                     'changed after the last extract/link, or the map changed '
                     'after link. Re-run extract_claims.py extract and '
                     'verify_claim_support.py link, then renumber',
            'source_ids': not_in_report,
        }), file=sys.stderr)
        sys.exit(1)

    entries = [_format_bib_entry(new_map[sid], by_sid[sid]) for sid in new_map]
    if section is None:
        new_text = body_new.rstrip('\n') + '\n\n' + heading_line + '\n\n' + '\n'.join(entries) + '\n'
    else:
        new_text = body_new + heading_line + '\n\n' + '\n'.join(entries) + '\n'
        if tail_new:
            if not tail_new.startswith('\n'):
                new_text += '\n'
            new_text += tail_new
        if not new_text.endswith('\n'):
            new_text += '\n'

    with open(report_path, 'w') as f:
        f.write(new_text)

    save_display_map(run_dir, new_map)
    print(json.dumps({
        'status': 'ok',
        'report': os.path.abspath(report_path),
        'cited_sources': len(new_map),
        'markers_rewritten': n_body + n_tail,
        'display_numbers': new_map,
    }, indent=2))


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog='citation_manager',
        description='Stable source identity and run manifest management for deep-research v3.0',
    )
    sub = parser.add_subparsers(dest='command', required=True)

    # init-run
    p_init = sub.add_parser('init-run', help='Create run manifest and empty artifact files')
    p_init.add_argument('--out-dir', required=True, help='Output directory for the research run')
    p_init.add_argument('--query', default='', help='Original research question')
    p_init.add_argument('--mode', default='standard', choices=['quick', 'standard', 'deep', 'ultradeep'])

    # register-source
    p_reg = sub.add_parser('register-source', help='Register a source and return its stable ID')
    p_reg.add_argument('--json', required=True, help='JSON object with at least raw_url and title')
    p_reg.add_argument('--dir', required=True, help='Run directory containing sources.jsonl')

    # assign-display-numbers
    p_num = sub.add_parser('assign-display-numbers', help='Map stable source IDs to display numbers')
    p_num.add_argument('--dir', required=True, help='Run directory containing sources.jsonl')
    p_num.add_argument('--cited-order', action='store_true',
                       help='Number only the cited sources, in first-citation order '
                            'read from cited_source_ids in claims.jsonl (latest '
                            'extraction, document order). Refuses to change '
                            'the numbers an existing report uses; '
                            'renumber-report does that')
    p_num.add_argument('--force', action='store_true',
                       help='With --cited-order: replace the current numbering '
                            'even though it changes existing numbers (only '
                            'when no report uses them)')

    # export-bibliography
    p_bib = sub.add_parser('export-bibliography', help='Generate bibliography from sources')
    p_bib.add_argument('--dir', required=True, help='Run directory containing sources.jsonl')
    p_bib.add_argument('--style', default='markdown', choices=['markdown', 'json'])

    # renumber-report
    p_ren = sub.add_parser('renumber-report',
                           help='Renumber the report\'s citations in cited order '
                                '(rewrites [N] markers and the bibliography)')
    p_ren.add_argument('--dir', required=True, help='Run directory (map and stores)')
    p_ren.add_argument('--report', default=None,
                       help='Path to the report (default: <dir>/report.md)')

    args = parser.parse_args()

    dispatch = {
        'init-run': cmd_init_run,
        'register-source': cmd_register_source,
        'assign-display-numbers': cmd_assign_display_numbers,
        'export-bibliography': cmd_export_bibliography,
        'renumber-report': cmd_renumber_report,
    }
    dispatch[args.command](args)


if __name__ == '__main__':
    main()
