#!/usr/bin/env python3
"""Deterministic threshold-transfer validation via exhaustive windowed
resampling of judge-labelled artifacts.

Question: the readability gates were calibrated on ~180-320-sentence
comprehensive reports. Do they still separate bad from good at the
sentence counts of the short formats (quick-brief ~11, comparison ~26,
research-summary ~27)?

Method: slide exhaustive windows of length L across each labelled body,
compute the gate metrics per window, and measure flag rates under the
CURRENT thresholds. No RNG, no judges — pass a bad-labelled and a
good-labelled report (--bad, --good); the original calibration pair was
fork v1.1 (blind-judged avg 72) vs v1.2 (avg 84.5), and the same tool
accepts any later pair measured the same way.

Gates tracked (warn-or-worse, matching readability_check.evaluate):
citation density (fail > 1.6), pct-3+ sentences (warn > 20%), mean
sentence length (warn > 22 words), Flesch-Kincaid grade (warn > 16.5),
pipeline-internals hits (warn > 2 per window). Bodies are segmented with
readability_check's own measured_segments (bullets and numbered items are
each their own segment), and each window segment is terminated through
readability_check's terminate_segment before textstat sees the joined
window, so the audit replicates what the gate measures.

Decision rule (fixed before running): a gate "carries" at length L if
bad-label flag-rate >= 0.80 AND good-label flag-rate <= 0.20. Marginal if
either side is 0.5-0.8 / 0.2-0.5. Collapsed otherwise -> reformulate that
gate as absolute counts at that length. A length where either body has
fewer segments than the window is "unmeasured" (the no-measurable-prose
path: nothing to validate, not a verdict).

Usage:
  readability_window_check.py --bad BAD.md --good GOOD.md [--json]
  (--json prints the report object on stdout, verdict summary on stderr)

Exit codes: 0 all gates carry or marginal at every length; 1 some gate
collapsed; 2 some length unmeasured (body shorter than the window) with
none collapsed; 3 a report file could not be read.
"""

import argparse
import json
import os
import sys

# Shared-rules import needs the scripts dir on sys.path (it is sys.path[0]
# when run as a script; tests insert it) — the same guard every script
# importing a sibling module uses.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from readability_check import (  # noqa: E402  (also installs vendor/ on sys.path)
    INTERNALS_RE,
    INTERNALS_WARN,
    FK_WARN,
    MEAN_REFS_MAX,
    PCT3_WARN,
    SENTLEN_WARN,
    body_before_bibliography,
    count_refs,
    measured_segments,
    terminate_segment,
)
import textstat  # noqa: E402  # hard dependency; vendored copy on sys.path

# Judge-labelled calibration pair this tool was built around: two
# blind-judged reports on the same question (v1.1 avg 72 = bad label,
# v1.2 avg 84.5 = good label). Paths come from the command line because
# the artifacts are run outputs, not repo fixtures (the originals are
# gone; see EVALUATION-TOOLING.md "Calibration anchors").
LABELS = ("bad-72", "good-84.5")

# Window lengths = sentence counts of the three verified format runs
LENGTHS = {"quick-brief": 11, "comparison": 26, "research-summary": 27}

GATE_NAMES = ["citation_density", "pct3plus", "sent_len", "fk_grade", "internals"]


def sentences_of(path: str) -> list[str]:
    """Measured segments of a report: the same segmentation the gate uses
    (bullet-aware, segments over 30 characters, bibliography excluded)."""
    with open(path, encoding="utf-8") as f:
        body = body_before_bibliography(f.read())
    return measured_segments(body)


def window_metrics(window: list[str]) -> dict:
    # Segments are terminated before joining, exactly as the gate does
    # for the whole body: textstat splits on punctuation, so an
    # unpunctuated bullet in the window would otherwise merge with its
    # neighbours into one giant sentence.
    text = " ".join(terminate_segment(s) for s in window)
    m = {
        "mean_refs": round(sum(count_refs(s) for s in window) / len(window), 2),
        "n3": sum(1 for s in window if count_refs(s) >= 3),
        "mean_sent_len": round(
            textstat.lexicon_count(text) / max(1, textstat.sentence_count(text)), 1
        ),
        "fk_grade": round(textstat.flesch_kincaid_grade(text), 1),
        "internals_hits": len(INTERNALS_RE.findall(text)),
    }
    m["pct_3plus"] = round(100.0 * m["n3"] / len(window), 1)
    return m


def gate_flags(m: dict) -> dict:
    """Replicate readability_check.evaluate's fail/warn logic per gate.
    Graded gates flag warn-or-worse; citation density has no warn tier, so
    it flags at its fail threshold."""
    return {
        "citation_density": m["mean_refs"] > MEAN_REFS_MAX,
        "pct3plus": m["pct_3plus"] > PCT3_WARN,
        "sent_len": m["mean_sent_len"] > SENTLEN_WARN,
        "fk_grade": m["fk_grade"] > FK_WARN,
        "internals": m["internals_hits"] > INTERNALS_WARN,
    }


def read_sentences(path: str, label: str) -> "list[str] | None":
    try:
        return sentences_of(path)
    except (OSError, UnicodeDecodeError) as e:
        # OSError: missing, unreadable, or a directory. UnicodeDecodeError
        # (a ValueError, so not an OSError): not valid UTF-8 markdown.
        sys.stderr.write(f"cannot read {label} report {path!r}: {e}\n")
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bad", required=True, metavar="REPORT_MD",
                    help="report labelled bad by blind judges (avg 72)")
    ap.add_argument("--good", required=True, metavar="REPORT_MD",
                    help="report labelled good by blind judges (avg 84.5)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    labelled = dict(zip(LABELS, (args.bad, args.good)))
    sents = {}
    for label, path in labelled.items():
        ss = read_sentences(path, label)
        if ss is None:
            return 3
        sents[label] = ss

    report = {}
    for fmt, L in LENGTHS.items():
        report[fmt] = {"window_len": L, "gates": {}}
        for label, ss in sents.items():
            n_windows = max(0, len(ss) - L + 1)
            flag_counts = {g: 0 for g in GATE_NAMES}
            if n_windows == 0:
                # No measurable prose at this length: too few segments to
                # form one window. Not a verdict — the length simply
                # cannot be validated (the gate's own no-measurable-prose
                # fail is the document-level form of the same state).
                report[fmt][label] = {"windows": 0, "segments": len(ss)}
                continue
            for i in range(n_windows):
                flags = gate_flags(window_metrics(ss[i : i + L]))
                for g, f in flags.items():
                    flag_counts[g] += int(f)
            report[fmt][label] = {
                "windows": n_windows,
                "flag_rate": {g: round(flag_counts[g] / n_windows, 3)
                              for g in GATE_NAMES},
            }
        if any(report[fmt][label].get("windows", 0) == 0 for label in LABELS):
            report[fmt]["gates"] = {g: "unmeasured" for g in GATE_NAMES}
            continue
        bad = report[fmt][LABELS[0]]["flag_rate"]
        good = report[fmt][LABELS[1]]["flag_rate"]
        verdicts = {}
        for g in GATE_NAMES:
            if bad[g] >= 0.80 and good[g] <= 0.20:
                v = "carries"
            elif bad[g] >= 0.50 and good[g] <= 0.50:
                v = "marginal"
            else:
                v = "collapsed"
            verdicts[g] = v
        report[fmt]["gates"] = verdicts

    if args.json:
        print(json.dumps(report, indent=2))  # stdout stays pure JSON
        summary = sys.stderr
    else:
        summary = sys.stdout
        for fmt, r in report.items():
            print(f"\n=== {fmt} (window={r['window_len']} sentences) ===")
            for label in LABELS:
                fr = r[label].get("flag_rate", {})
                rates = " ".join(f"{g}={fr.get(g, 'n/a')}" for g in GATE_NAMES)
                print(f"  {label:10} n={r[label]['windows']:4}  {rates}")
            for g, v in r["gates"].items():
                print(f"  {g:18} {v}")

    collapsed = [f"{fmt}:{g}" for fmt, r in report.items()
                 for g, v in r["gates"].items() if v == "collapsed"]
    unmeasured = [fmt for fmt, r in report.items()
                  if any(v == "unmeasured" for v in r["gates"].values())]
    if collapsed:
        print(f"\nREFORMULATE NEEDED: {', '.join(collapsed)}", file=summary)
        return 1
    if unmeasured:
        print(f"\nUNMEASURED (body shorter than window): {', '.join(unmeasured)}",
              file=summary)
        return 2
    print("\nAll gates carry (or marginal) at every format length.", file=summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
