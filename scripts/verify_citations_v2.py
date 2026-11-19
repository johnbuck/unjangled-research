#!/usr/bin/env python3
# unjangled-research v3.5: network citation verifier (second checker).
# Locally authored. Stdlib only, Python 3.10+.
"""
verify_citations_v2.py -- re-fetch each registered source and confirm:
  1. the source URL resolves (any 2xx; 4xx/5xx or network error = unreachable, recorded)
  2. each direct_quote row attributed to that source appears in the fetched
     visible page text (script, style, template and comments dropped; tags
     stripped; entities decoded; whitespace and quote characters normalised),
     on word boundaries, case-sensitive

This is the SECOND checker. verify_citations.py checks DOIs and URLs;
this re-fetches each source and checks the quoted text. Disagreements between the two are
findings, not noise. Bot-walls (403) are expected weather: they mean
"unverifiable this pass," not "fabricated."

Exit 0 = all reachable sources verified, zero fidelity misses.
Exit 1 = fidelity misses on reachable sources (quotes not found),
         or no sources to check (empty sources.jsonl).
Exit 2 = all sources unreachable (nothing verifiable — recorded, not failed).
"""

import argparse
import html
import json
import os
import re
import sys
import urllib.request
import urllib.error

UA = 'unjangled-research/3.5 (citation-verifier)'
MIN_QUOTE_LEN = 20

# Content a reader never sees: comments, scripts, styles, templates.
_HIDDEN_RE = re.compile(
    r'<!--.*?-->|<(script|style|template)\b[^>]*>.*?</\1\s*>', re.S | re.I)
# A tag: '<' + letter (or '/', '!', '?'), attributes may quote a '>'.
_TAG_RE = re.compile(
    r'<(/?)([A-Za-z][A-Za-z0-9-]*)(?:"[^"]*"|\'[^\']*\'|[^\'">])*>|<[!?][^>]*>')
# Inline elements render without a break, so removing them must not split a
# word ('<span>T</span>he' reads 'The'). Every other tag becomes a space.
_INLINE_TAGS = frozenset({
    'a', 'abbr', 'b', 'bdi', 'bdo', 'cite', 'code', 'data', 'del', 'dfn', 'em',
    'font', 'i', 'ins', 'kbd', 'mark', 'q', 's', 'samp', 'small', 'span',
    'strike', 'strong', 'sub', 'sup', 'time', 'tt', 'u', 'var', 'wbr',
})
_WS_RE = re.compile(r'\s+')
_QUOTE_TRANS = str.maketrans({
    '\u201c': '"', '\u201d': '"', '\u2033': '"',
    '\u2018': "'", '\u2019': "'", '\u2032': "'",
    # invisible characters that break a match: soft hyphen, zero-width space, BOM
    '\u00ad': None, '\u200b': None, '\ufeff': None,
})


def norm_text(s: str) -> str:
    """Whitespace collapsed, quote characters folded to ASCII."""
    return _WS_RE.sub(' ', s.translate(_QUOTE_TRANS)).strip()


def _tag_sub(m: re.Match) -> str:
    name = (m.group(2) or '').lower()
    return '' if name in _INLINE_TAGS else ' '


def page_text(body: str) -> str:
    """HTML body -> visible page text: hidden blocks dropped, tags stripped,
    then entities decoded (in that order, so an encoded '&lt;' stays text),
    then normalised."""
    text = _HIDDEN_RE.sub(' ', body)
    text = _TAG_RE.sub(_tag_sub, text)
    text = html.unescape(text)
    return norm_text(text)


def quote_in_page(quote: str, page: str) -> bool:
    """True if the normalised quote occurs in the page text on word boundaries,
    so 'profit rose' does not match inside 'nonprofit rose'."""
    pat = re.escape(quote)
    if re.match(r'\w', quote):
        pat = r'(?<!\w)' + pat
    if re.search(r'\w$', quote):
        pat += r'(?!\w)'
    return re.search(pat, page) is not None


def fetch(url: str, timeout: int = 30) -> tuple[str, int]:
    """Return (body, status). Non-fatal on any network error."""
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(2_000_000).decode('utf-8', errors='replace'), r.status
    except urllib.error.HTTPError as e:
        return '', e.code
    except Exception:
        return '', -1


def main() -> None:
    ap = argparse.ArgumentParser(prog='verify_citations_v2')
    ap.add_argument('--dir', required=True, help='Run directory')
    ap.add_argument('--json', action='store_true', help='JSON output')
    args = ap.parse_args()

    sources = [json.loads(l) for l in open(os.path.join(args.dir, 'sources.jsonl')) if l.strip()]
    evidence = [json.loads(l) for l in open(os.path.join(args.dir, 'evidence.jsonl')) if l.strip()]

    results = []
    misses = []
    unreachable = 0
    skipped_short = 0

    for src in sources:
        url = src.get('raw_url') or src.get('canonical_locator', '')
        if not url.startswith('http'):
            results.append({'source_id': src['source_id'], 'url': url, 'status': 'skipped (non-http)'})
            continue
        body, code = fetch(url)
        if 200 <= code < 300 and body:
            page = page_text(body)
            src_quotes = [e for e in evidence
                          if e.get('source_id') == src['source_id'] and e.get('evidence_type') == 'direct_quote']
            for q_row in src_quotes:
                q = norm_text(q_row.get('quote', ''))
                if len(q) < MIN_QUOTE_LEN:
                    skipped_short += 1
                    results.append({'source_id': src['source_id'], 'evidence_id': q_row['evidence_id'],
                                    'status': f'skipped (short quote, <{MIN_QUOTE_LEN} chars)'})
                    continue
                ok = quote_in_page(q, page)
                results.append({'source_id': src['source_id'], 'evidence_id': q_row['evidence_id'],
                                'status': 'verified' if ok else 'MISS'})
                if not ok:
                    misses.append(q_row['evidence_id'])
        else:
            unreachable += 1
            results.append({'source_id': src['source_id'], 'url': url[:80], 'status': f'unreachable ({code})'})

    report = {
        'run_dir': os.path.abspath(args.dir),
        'sources_checked': len(sources),
        'reachable': len(sources) - unreachable,
        'unreachable': unreachable,
        'skipped_short_quotes': skipped_short,
        'fidelity_misses': len(misses),
        'miss_ids': misses,
        'detail': results,
    }

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        for r in results:
            print(f"{r.get('status', '?'):16s} {r.get('source_id', '')} {r.get('evidence_id', '')}")
        print(f"--- {report['reachable']} reachable / {unreachable} unreachable / "
              f"{len(misses)} misses / {skipped_short} skipped (short quotes)")

    if misses:
        sys.exit(1)
    if not sources:
        print('no sources to verify: nothing was checked', file=sys.stderr)
        sys.exit(1)
    if unreachable == len(sources) and sources:
        sys.exit(2)
    sys.exit(0)


if __name__ == '__main__':
    main()
