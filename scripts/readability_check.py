#!/usr/bin/env python3
"""Readability gate.

Measures citation-chain density and pipeline-internals leakage in a research
report body (bibliography excluded). Thresholds calibrated 2026-10-06 against
two blind-labelled task-73 artifacts (fork judged 72, upstream 07 judged 83).

Windows: citation density is measured on the body before the bibliography;
internals are scanned over the whole document minus the bibliography section
(post-bibliography appendices included). List items (a '-', '*' or
'+' bullet, or a '1.' / '1)' numbered item, with up to three leading
spaces, plus the continuation lines that wrap it) are each their own
segment, so an unpunctuated list item never merges with the next item;
runs of other lines are split on sentence enders as before. The textstat
metrics see the same boundaries: each unpunctuated list item is
terminated with a period at its end before textstat sees it (terminal
punctuation '.', '!' '?' is left untouched), so every list item counts
as its own sentence for sentence length, FK grade and the other
standard formulas. A hard-wrapped item is terminated once, at its last
line, so wrapping a long item never splits it into short sentences.

Gates:
  no sentence over 30 characters      hard fail ("no measurable prose")
  pipeline-internals hits             warn > 2, fail > 6
  mean refs/sentence                  fail > 1.6
  sentences with 3+ refs              warn > 20%, fail > 25%
  mean sentence length (words)        warn > 22, fail > 27
  Flesch-Kincaid grade                warn > 16.5, fail > 18.0
  max citation chain >= 12            advisory only (non-discriminating)

Exit codes: 0 pass, 2 warnings only, 1 fail (3: textstat unavailable).
"""

import argparse
import json
import os
import re
import sys

# textstat is a hard dependency. The skill vendors a copy under
# vendor/ so deployments without pip access still run; a system install
# takes precedence when present.
_VENDOR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vendor")
if os.path.isdir(_VENDOR) and _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)
try:
    import textstat
except ImportError as e:
    sys.stderr.write(
        f"FATAL: textstat is required (pip install textstat, or restore the "
        f"skill's vendor/ directory). {e}\n"
    )
    sys.exit(3)

# Shared bibliography rule (E1-R1): this script must not keep its own
# split or citation regex. Imported after the scripts dir is guaranteed
# on sys.path (it is sys.path[0] when run as a script; tests insert it).
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from bibliography import (  # noqa: E402,F401
    body_before_bibliography,  # re-exported: readability_window_check imports it from here
    count_refs,
    reader_facing_text,
)

__all__ = [
    "body_before_bibliography",
    "count_refs",
    "list_blocks",
    "reader_facing_text",
    "terminate_segment",
    "terminated_body",
]

INTERNALS_RE = re.compile(
    r"append-only|run manifest|evidence rows|cryptographic identit"
    r"|deep mode|fallback chain|evidence store|the run executed"
    r"|retrieval registered|source evaluation scored|pipeline|harness"
    r"|\b[0-9a-f]{12,}\b",
    re.IGNORECASE,
)
SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

# A list-item line (a '-', '*' or '+' bullet, or a CommonMark ordered
# marker of 1-9 digits plus '.' or ')', up to three leading spaces):
# measured as its own segment so unpunctuated list items never merge into
# one giant sentence (F10). Numbered items are included because '1)'
# items have no '.' for SENT_SPLIT_RE to split on, and '1.' items only
# split by accident of the next item's marker. The negative lookahead
# excludes spaced thematic breaks ('- - -', '* * *'): the rest of the line
# is markers and whitespace only, which is a break, not a bullet; spaces
# only before the marker, so a tab-indented line stays prose (CommonMark
# reads it as indented code).
BULLET_LINE_RE = re.compile(r"^ {0,3}(?:[-*+]|\d{1,9}[.)])[ \t]+(?![-*+ \t]*$)")

# Thresholds. Internals recalibrated 2026-10-06 after an instrument-
# window defect was found (post-bibliography appendices were unmeasured;
# corrected to whole-document scan). Re-derived from the same blind-labelled
# pair: fork v1.1 (judged 72) = 20 hits incl. hash-ID table; 07 (judged 83,
# docked lightly for its own appendix chatter) = 6 hits. Judges penalize
# degree, not presence -> warn > 2, fail > 6 (never worse than the 83-scored
# benchmark). Hash-ID pattern added per judge feedback naming the table.
INTERNALS_WARN = 2
INTERNALS_FAIL = 6
MEAN_REFS_MAX = 1.6
PCT3_WARN = 20.0
PCT3_FAIL = 25.0
# Standard-formula gates (calibrated 2026-10-06 on the same blind-
# labelled pair): 07 (judged 83) = 21.6 words/sentence, FK 15.7; fork v1.1
# (judged 72) = 32.2, FK 19.0. Warn at the 83-scored benchmark's level,
# fail midway toward the 72-scored level. Flesch/Fog/SMOG are reported but
# ungated (redundant with FK; compressed dynamic range on academic prose).
SENTLEN_WARN = 22.0
SENTLEN_FAIL = 27.0
FK_WARN = 16.5
FK_FAIL = 18.0

# body_before_bibliography / reader_facing_text / count_refs come from
# scripts/bibliography.py (E1-R1 shared rule) and are re-exported by the
# import at the top of this file; readability_window_check.py imports
# them from here. The density window is the window the thresholds were
# calibrated on (fork 2.06, 07 1.04).


def list_blocks(lines: "list[str]") -> "list[tuple[bool, list[str]]]":
    """Lines grouped into (is_list_item, lines) blocks, in order.

    A list item is a BULLET_LINE_RE line plus every continuation line
    after it: each following non-blank line that is not itself a list
    item, indented or lazy, as CommonMark continues an item's paragraph.
    The item ends at a blank line or the next list item. Every other
    maximal run of lines (blank lines included) is one prose block.
    Concatenating the blocks' lines gives back the input lines exactly.
    """
    blocks: "list[tuple[bool, list[str]]]" = []
    for line in lines:
        if BULLET_LINE_RE.match(line):
            blocks.append((True, [line]))
        elif blocks and blocks[-1][0] and line.strip():
            blocks[-1][1].append(line)  # continuation of the open item
        elif blocks and not blocks[-1][0]:
            blocks[-1][1].append(line)
        else:
            blocks.append((False, [line]))
    return blocks


def measured_segments(body: str) -> "list[str]":
    """Segments over 30 characters in the density window.

    List items (bullets and numbered items, continuation lines included)
    are each their own chunk; runs of other lines keep the classic
    behaviour (SENT_SPLIT_RE over the whole run, so prose wrapping across
    lines still joins into one sentence).
    """
    chunks = ["\n".join(ls) for _, ls in list_blocks(body.splitlines())]
    segments = [s for chunk in chunks for s in SENT_SPLIT_RE.split(chunk)]
    return [s for s in segments if len(s.strip()) > 30]


def terminate_segment(segment: str) -> str:
    """A copy of segment that ends in terminal punctuation.

    Unchanged (whitespace included) when the segment already ends in
    '.', '!' or '?' — the SENT_SPLIT_RE enders; otherwise the trailing
    whitespace is stripped and a period is appended, so textstat —
    which splits sentences on punctuation, not on list markers —
    counts the segment as its own sentence.
    """
    s = segment.rstrip()
    return segment if s[-1:] in ".!?" else s + "."


def terminated_body(body: str) -> str:
    """Body with every unpunctuated list item terminated by a period.

    Only list items (list_blocks) are touched, and each is terminated
    once, at the end of its last continuation line, so a hard-wrapped
    item stays one sentence. A body without unpunctuated list items
    round-trips byte-identically and every item already ending in
    terminal punctuation is unchanged.
    """
    out = []
    for is_item, ls in list_blocks(body.split("\n")):
        out.append(terminate_segment("\n".join(ls)) if is_item else "\n".join(ls))
    return "\n".join(out)


def measure(text: str) -> dict:
    body = body_before_bibliography(text)  # calibrated citation-density window
    reader_facing = reader_facing_text(text)  # whole doc minus bib entries
    internals = INTERNALS_RE.findall(reader_facing)
    sentences = measured_segments(body)
    if not sentences:
        # No measurable prose: the textstat metrics are zeroed (textstat
        # on a few-word body is noise) but the dict stays complete, so
        # evaluate() and the summary line never KeyError; internals stay
        # measured so a short or bullet-only report cannot evade the
        # leak gate by having nothing measurable.
        return {
            "sentences": 0,
            "refs": 0,
            "mean_refs": 0.0,
            "pct_3plus": 0.0,
            "max_chain": 0,
            "internals_hits": len(internals),
            "internals_samples": [s.strip()[:60] for s in internals[:5]],
            "flesch_ease": 0.0,
            "fk_grade": 0.0,
            "gunning_fog": 0.0,
            "smog": 0.0,
            "mean_sent_len": 0.0,
        }
    chain_counts = [count_refs(s) for s in sentences]
    n3 = sum(1 for n in chain_counts if n >= 3)
    total_refs = sum(chain_counts)
    # Textstat reads the terminated body: every measured segment counts
    # as its own sentence (an unpunctuated list item would otherwise
    # merge with the next line into one giant textstat "sentence").
    prose = terminated_body(body)
    return {
        "sentences": len(sentences),
        "refs": total_refs,
        "mean_refs": round(total_refs / len(sentences), 2),
        "pct_3plus": round(100.0 * n3 / len(sentences), 1),
        "max_chain": max(chain_counts),
        "internals_hits": len(internals),
        "internals_samples": [s.strip()[:60] for s in internals[:5]],
        "flesch_ease": round(textstat.flesch_reading_ease(prose), 1),
        "fk_grade": round(textstat.flesch_kincaid_grade(prose), 1),
        "gunning_fog": round(textstat.gunning_fog(prose), 1),
        "smog": round(textstat.smog_index(prose), 1),
        "mean_sent_len": round(
            textstat.lexicon_count(prose) / max(1, textstat.sentence_count(prose)), 1
        ),
    }


def evaluate(m: dict) -> tuple[list, list, list]:
    fails, warns, advisories = [], [], []
    if m["sentences"] == 0:
        fails.append(
            "no measurable prose: the body before the bibliography has no "
            "sentence over 30 characters — the report is too short for the "
            "readability gates to measure"
        )
    if m["internals_hits"] > INTERNALS_FAIL:
        fails.append(
            f"pipeline-internals leakage: {m['internals_hits']} hits "
            f"(fail > {INTERNALS_FAIL}; samples: {m['internals_samples']}) — "
            f"process narration belongs in the run manifest, not the report"
        )
    elif m["internals_hits"] > INTERNALS_WARN:
        warns.append(
            f"pipeline-internals leakage: {m['internals_hits']} hits "
            f"(warn > {INTERNALS_WARN}; samples: {m['internals_samples']})"
        )
    if m["mean_refs"] > MEAN_REFS_MAX:
        fails.append(
            f"citation density: mean {m['mean_refs']} refs/sentence "
            f"(max {MEAN_REFS_MAX}) — cite 1-2 most authoritative per sentence, "
            f"batch the rest at paragraph level"
        )
    if m["mean_sent_len"] > SENTLEN_FAIL:
        fails.append(
            f"sentence length: mean {m['mean_sent_len']} words/sentence "
            f"(fail > {SENTLEN_FAIL}) — split compound sentences; unchain "
            f"comma-linked appositive lists"
        )
    elif m["mean_sent_len"] > SENTLEN_WARN:
        warns.append(
            f"sentence length: mean {m['mean_sent_len']} words/sentence "
            f"(warn > {SENTLEN_WARN})"
        )
    if m["fk_grade"] > FK_FAIL:
        fails.append(
            f"reading grade: Flesch-Kincaid {m['fk_grade']} (fail > {FK_FAIL}) — "
            f"shorten sentences and prefer plain words"
        )
    elif m["fk_grade"] > FK_WARN:
        warns.append(
            f"reading grade: Flesch-Kincaid {m['fk_grade']} (warn > {FK_WARN})"
        )
    if m["pct_3plus"] > PCT3_FAIL:
        fails.append(
            f"{m['pct_3plus']}% of sentences carry 3+ refs (fail > {PCT3_FAIL})"
        )
    elif m["pct_3plus"] > PCT3_WARN:
        warns.append(
            f"{m['pct_3plus']}% of sentences carry 3+ refs (warn > {PCT3_WARN})"
        )
    if m["max_chain"] >= 12:
        advisories.append(
            f"max citation chain {m['max_chain']} — consider splitting across "
            f"sentences (advisory; upstream also scores 83 with a 12-chain)"
        )
    return fails, warns, advisories


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("report", help="Path to report markdown")
    ap.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = ap.parse_args()

    text = open(args.report, encoding="utf-8").read()
    m = measure(text)
    fails, warns, advisories = evaluate(m)

    if args.json:
        print(json.dumps({"metrics": m, "fails": fails, "warns": warns,
                          "advisories": advisories}, indent=2))
    else:
        print(f"readability: {args.report}")
        print(f"  sentences={m['sentences']} refs={m['refs']} "
              f"mean/sent={m['mean_refs']} pct3+={m['pct_3plus']}% "
              f"maxchain={m['max_chain']} internals={m['internals_hits']}")
        print(f"  flesch={m['flesch_ease']} fk={m['fk_grade']} "
              f"fog={m['gunning_fog']} smog={m['smog']} "
              f"sent-len={m['mean_sent_len']}w")
        for f_ in fails:
            print(f"  FAIL: {f_}")
        for w in warns:
            print(f"  WARN: {w}")
        for a in advisories:
            print(f"  advisory: {a}")

    if fails:
        return 1
    if warns:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
