#!/usr/bin/env python3
"""
Claim-Support Verification — checks whether evidence supports claims.

CLI subcommands:
  verify       Check the latest extraction's claims against evidence,
               update support_status
  link         Resolve citation numbers to sources through the run's
               display-number map (display_numbers.json, written by
               citation_manager.py assign-display-numbers), then link
               claims to evidence rows
  report       Generate a support verification summary over the latest
               extraction (the same rows verify scores)

Version 1 is deterministic and cheap: entity, number, date, and
lexical-overlap checks over stored evidence. No LLM calls.

Only factual claims hard-fail on unsupported status.
Synthesis/recommendation need traceability but softer thresholds.
"""

import argparse
import json
import os
import re
import sys
from collections import Counter


# ---------------------------------------------------------------------------
# JSONL helpers
# ---------------------------------------------------------------------------

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


def write_jsonl(path: str, rows: list[dict]) -> None:
    with open(path, 'w') as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')


def load_display_map(run_dir: str) -> "dict[int, str] | None":
    """Read the run's display-number map -> {display_number: source_id}.

    The map is display_numbers.json in the run dir, written by
    citation_manager.py assign-display-numbers (provisional
    registration-order map or cited-order map) and renumber-report.
    Returns None when no map has been saved.
    """
    path = os.path.join(run_dir, 'display_numbers.json')
    if not os.path.exists(path):
        return None
    with open(path) as f:
        sid_to_num = json.load(f)
    num_to_sid = {}
    for sid, num in sid_to_num.items():
        try:
            num_to_sid[int(num)] = sid
        except (TypeError, ValueError):
            continue
    return num_to_sid


# ---------------------------------------------------------------------------
# Support verification logic
# ---------------------------------------------------------------------------

# Extract numbers (integers and decimals)
NUMBER_RE = re.compile(r'\b\d+(?:\.\d+)?(?:%|x|X)?\b')

# Extract year-like numbers
YEAR_RE = re.compile(r'\b(19|20)\d{2}\b')

# Extract capitalized entities (naive NER)
ENTITY_RE = re.compile(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b')

# Common stop entities to ignore
STOP_ENTITIES = frozenset([
    'The', 'This', 'That', 'These', 'However', 'Furthermore',
    'Moreover', 'Additionally', 'Therefore', 'Nevertheless',
])


def extract_tokens(text: str) -> set[str]:
    """Extract significant lowercase tokens (>3 chars)."""
    words = re.findall(r'\b[a-z]{4,}\b', text.lower())
    return set(words)


def extract_numbers(text: str) -> set[str]:
    """Extract numeric values."""
    return set(NUMBER_RE.findall(text))


def extract_years(text: str) -> set[str]:
    """Extract year mentions."""
    return set(YEAR_RE.findall(text))


def extract_entities(text: str) -> set[str]:
    """Extract capitalized entity mentions."""
    ents = set(ENTITY_RE.findall(text))
    return ents - STOP_ENTITIES


def compute_support_score(claim_text: str, evidence_quotes: list[str]) -> tuple[str, float, str]:
    """
    Compute support status for a claim given its linked evidence quotes.

    Returns (status, score, notes).
    Score range: 0.0 (no overlap) to 1.0 (strong support).
    """
    if not evidence_quotes:
        return ('unsupported', 0.0, 'no evidence linked')

    claim_tokens = extract_tokens(claim_text)
    claim_numbers = extract_numbers(claim_text)
    claim_years = extract_years(claim_text)
    claim_entities = extract_entities(claim_text)

    best_score = 0.0
    best_notes = []

    for quote in evidence_quotes:
        ev_tokens = extract_tokens(quote)
        ev_numbers = extract_numbers(quote)
        ev_years = extract_years(quote)
        ev_entities = extract_entities(quote)

        # Token overlap (Jaccard-like)
        if claim_tokens:
            token_overlap = len(claim_tokens & ev_tokens) / len(claim_tokens)
        else:
            token_overlap = 0.0

        # Number match
        if claim_numbers:
            number_match = len(claim_numbers & ev_numbers) / len(claim_numbers)
        else:
            number_match = 1.0  # No numbers to check

        # Year match
        if claim_years:
            year_match = len(claim_years & ev_years) / len(claim_years)
        else:
            year_match = 1.0

        # Entity match
        if claim_entities:
            entity_match = len(claim_entities & ev_entities) / len(claim_entities)
        else:
            entity_match = 1.0

        # Weighted composite
        score = (
            0.4 * token_overlap +
            0.25 * number_match +
            0.15 * year_match +
            0.2 * entity_match
        )

        if score > best_score:
            best_score = score
            best_notes = []
            if token_overlap < 0.3:
                best_notes.append('low lexical overlap')
            if claim_numbers and number_match < 0.5:
                best_notes.append('number mismatch')
            if claim_years and year_match < 1.0:
                best_notes.append('year mismatch')
            if claim_entities and entity_match < 0.3:
                best_notes.append('entity mismatch')

    # Threshold decision
    if best_score >= 0.6:
        status = 'supported'
    elif best_score >= 0.35:
        status = 'partial'
    else:
        status = 'needs_review'

    notes = '; '.join(best_notes) if best_notes else 'adequate overlap'
    return (status, round(best_score, 3), notes)


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------



def cmd_link(args: argparse.Namespace) -> None:
    """Link claims to their evidence: resolve citation numbers to source IDs
    through the run's display-number map, then find best-matching evidence
    rows by token overlap."""
    claims_path = os.path.join(args.dir, 'claims.jsonl')
    sources_path = os.path.join(args.dir, 'sources.jsonl')
    evidence_path = os.path.join(args.dir, 'evidence.jsonl')

    claims = read_jsonl(claims_path)
    sources = read_jsonl(sources_path)
    evidence = read_jsonl(evidence_path)

    # Resolve [N] through the run's actual display-number map, not
    # registration order (E1-R8/F13). Fall back to registration order —
    # the documented provisional numbering — only when no map was saved,
    # and say so on stderr.
    num_to_sid = load_display_map(args.dir)
    map_source = 'display_numbers.json'
    if num_to_sid is None:
        num_to_sid = {}
        for src in sources:
            sid = src.get('source_id')
            if sid and sid not in num_to_sid.values():
                num_to_sid[len(num_to_sid) + 1] = sid
        map_source = 'registration order'
        print(
            'warning: display_numbers.json not found; resolving citation '
            'numbers by registration order — run '
            '"citation_manager.py assign-display-numbers --dir <run>" to '
            'save the run map',
            file=sys.stderr,
        )

    # Index evidence by source_id
    ev_by_source = {}
    for ev in evidence:
        sid = ev.get('source_id')
        if sid:
            ev_by_source.setdefault(sid, []).append(ev)

    linked = 0
    unresolved = []
    updated = []
    for claim in claims:
        cite_nums = claim.get('_citation_numbers', [])

        # Step 1: resolve citation numbers to source IDs
        if cite_nums and not claim.get('cited_source_ids'):
            sids = []
            for n in cite_nums:
                if n in num_to_sid:
                    sids.append(num_to_sid[n])
                else:
                    unresolved.append(n)
            claim['cited_source_ids'] = sids

        # Step 2: find best-matching evidence rows
        if claim.get('cited_source_ids') and not claim.get('evidence_ids'):
            claim_tokens = extract_tokens(claim.get('text', ''))
            best_eids = []
            for sid in claim['cited_source_ids']:
                candidates = ev_by_source.get(sid, [])
                best_score = 0
                best_eid = None
                for ev in candidates:
                    ev_tokens = extract_tokens(ev.get('quote', ''))
                    if not ev_tokens:
                        continue
                    overlap = len(claim_tokens & ev_tokens)
                    score = overlap / max(len(claim_tokens), 1)
                    if score > best_score:
                        best_score = score
                        best_eid = ev.get('evidence_id')
                if best_eid and best_score >= 0.05:  # minimum 5% token overlap
                    best_eids.append(best_eid)
            claim['evidence_ids'] = best_eids

        if claim.get('evidence_ids'):
            linked += 1
        updated.append(claim)

    write_jsonl(claims_path, updated)
    print(json.dumps({
        'status': 'ok',
        'total_claims': len(updated),
        'linked': linked,
        'unlinked': len(updated) - linked,
        'display_map': map_source,
        'unresolved_citation_numbers': sorted(set(unresolved)),
    }))

def latest_extraction_rows(claims: list[dict]) -> list[dict]:
    """Rows of the latest extraction only, keep-last per claim_id.

    The same selection cited_order_ids makes (citation_manager.py): rows
    of the max extraction_id, in doc_position order. extract re-stamps
    the current report on every run, so those rows are exactly the
    current report; claim_ids whose sentences were deleted are never
    superseded and must not be scored. Rows without an extraction_id
    never contribute when stamped rows exist (manual `add`); a
    claims.jsonl with no stamped rows at all (from before extraction
    stamping) is treated as one extraction in file order.
    """
    stamped = [c for c in claims if c.get('extraction_id')]
    if stamped:
        latest = max(c['extraction_id'] for c in stamped)
        rows = sorted(
            (c for c in stamped if c['extraction_id'] == latest),
            key=lambda c: c.get('doc_position', float('inf')),
        )
    else:
        rows = list(claims)
    by_id: dict = {}
    for c in rows:
        by_id[c.get('claim_id')] = c
    return list(by_id.values())


def cmd_verify(args: argparse.Namespace) -> None:
    """Verify the latest extraction's claims against evidence, update claims.jsonl."""
    claims_path = os.path.join(args.dir, 'claims.jsonl')
    evidence_path = os.path.join(args.dir, 'evidence.jsonl')
    sources_path = os.path.join(args.dir, 'sources.jsonl')

    claims = read_jsonl(claims_path)
    evidence = read_jsonl(evidence_path)
    sources = read_jsonl(sources_path)

    # Build evidence index by source_id
    ev_by_source: dict[str, list[str]] = {}
    ev_by_id: dict[str, dict] = {}
    for ev in evidence:
        sid = ev.get('source_id', '')
        eid = ev.get('evidence_id', '')
        ev_by_source.setdefault(sid, []).append(ev.get('quote', ''))
        ev_by_id[eid] = ev

    # Score only the latest extraction's rows (latest_extraction_rows,
    # above): claims from earlier extractions whose sentences the report
    # no longer contains are never superseded, so scoring them would
    # fail --strict on every retry after a deletion.
    unique_claims = latest_extraction_rows(claims)

    verified = 0
    updated_claims = []

    for claim in unique_claims:
        claim_type = claim.get('claim_type', 'factual')

        # Gather evidence for this claim
        cited_ids = claim.get('cited_source_ids', [])
        evidence_ids = claim.get('evidence_ids', [])

        # Collect evidence quotes from linked evidence_ids
        quotes = []
        for eid in evidence_ids:
            if eid in ev_by_id:
                quotes.append(ev_by_id[eid].get('quote', ''))

        # Also gather from cited sources
        for sid in cited_ids:
            if sid in ev_by_source:
                quotes.extend(ev_by_source[sid])

        if not quotes and not cited_ids and not evidence_ids:
            # No links at all
            if claim_type == 'speculation':
                claim['support_status'] = 'supported'  # Speculation doesn't need evidence
            else:
                claim['support_status'] = 'unsupported'
        elif not quotes:
            # Has cited sources but no evidence captured yet
            claim['support_status'] = 'needs_review'
        else:
            status, score, notes = compute_support_score(claim['text'], quotes)
            claim['support_status'] = status
            claim['_support_score'] = score
            claim['_support_notes'] = notes

        verified += 1
        updated_claims.append(claim)

    # Rewrite claims.jsonl preserving every row (the file is append-only;
    # older extractions' rows keep their historical statuses, unscored).
    # The selected rows are the same dict objects, so their updated
    # support_status lands in the written file.
    write_jsonl(claims_path, claims)

    # Compute summary over the scored rows only (the latest extraction)
    status_counts = Counter(c.get('support_status') for c in updated_claims)
    factual_unsupported = sum(
        1 for c in updated_claims
        if c.get('claim_type') == 'factual' and c.get('support_status') == 'unsupported'
    )
    total_factual = sum(1 for c in updated_claims if c.get('claim_type') == 'factual')

    # Strict mode: fail if any factual claim is unsupported
    passed = True
    if args.strict and factual_unsupported > 0:
        passed = False

    print(json.dumps({
        'status': 'pass' if passed else 'fail',
        'verified': verified,
        'support_status_counts': dict(status_counts),
        'factual_unsupported': factual_unsupported,
        'total_factual': total_factual,
        'unsupported_rate': round(factual_unsupported / max(total_factual, 1), 3),
    }, indent=2))

    if not passed:
        sys.exit(1)


def cmd_report(args: argparse.Namespace) -> None:
    """Generate a human-readable report over the latest extraction."""
    claims_path = os.path.join(args.dir, 'claims.jsonl')
    claims = read_jsonl(claims_path)

    # The same rows verify scores (latest_extraction_rows): claims from
    # earlier extractions whose sentences the report no longer contains
    # are never superseded and must not be listed.
    unique = latest_extraction_rows(claims)

    lines = ['# Claim Support Verification Report', '']

    # Summary
    status_counts = Counter(c.get('support_status') for c in unique)
    type_counts = Counter(c.get('claim_type') for c in unique)
    lines.append(f'**Total claims:** {len(unique)}')
    lines.append(f'**By type:** {dict(type_counts)}')
    lines.append(f'**By status:** {dict(status_counts)}')
    lines.append('')

    # Unsupported factual claims (the failures)
    unsupported_factual = [
        c for c in unique
        if c.get('claim_type') == 'factual' and c.get('support_status') in ('unsupported', 'needs_review')
    ]
    if unsupported_factual:
        lines.append('## Unsupported/Review-needed Factual Claims')
        lines.append('')
        for c in unsupported_factual:
            lines.append(f'- [{c["support_status"]}] `{c["section_id"]}`: {c["text"][:100]}...')
            if c.get('_support_notes'):
                lines.append(f'  Notes: {c["_support_notes"]}')
        lines.append('')

    # All clear
    if not unsupported_factual:
        lines.append('## All factual claims have adequate support.')
        lines.append('')

    print('\n'.join(lines))


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog='verify_claim_support',
        description='Claim-support verification for deep-research v3.0',
    )
    sub = parser.add_subparsers(dest='command', required=True)

    # verify
    p_ver = sub.add_parser('verify', help='Verify claims against evidence')
    p_ver.add_argument('--dir', required=True, help='Run directory')
    p_ver.add_argument('--strict', action='store_true', help='Exit 1 if any factual claim unsupported')

    # link
    p_link = sub.add_parser('link', help='Resolve citation numbers and link claims to evidence')
    p_link.add_argument('--dir', required=True, help='Run directory')

    # report
    p_rep = sub.add_parser('report', help='Generate verification report')
    p_rep.add_argument('--dir', required=True, help='Run directory')

    args = parser.parse_args()
    dispatch = {
        'verify': cmd_verify,
        'link': cmd_link,
        'report': cmd_report,
    }
    dispatch[args.command](args)


if __name__ == '__main__':
    main()
