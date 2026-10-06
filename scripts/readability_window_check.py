#!/usr/bin/env python3
"""Deterministic threshold-transfer validation via exhaustive windowed
resampling of judge-labelled artifacts (CAP-4c).

Question: the readability gates were calibrated on ~180-320-sentence
comprehensive reports. Do they still separate bad from good at the
sentence counts of the short formats (quick-brief ~11, comparison ~26,
research-summary ~27)?

Method: slide exhaustive windows of length L across each labelled body,
compute the gate metrics per window, and measure flag rates under the
CURRENT thresholds. No RNG, no judges — the labels come from the two
blind-judged artifacts (v1.1 avg 72, v1.2 avg 84.5).

Decision rule (fixed before running): a gate "carries" at length L if
bad-label flag-rate >= 0.80 AND good-label flag-rate <= 0.20. Marginal if
either side is 0.5-0.8 / 0.2-0.5. Collapsed otherwise -> reformulate that
gate as absolute counts at that length.
"""

import argparse
import json
import re
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from readability_check import (  # noqa: E402  (also installs vendor/ on sys.path)
    SENT_SPLIT_RE,
    body_before_bibliography,
    count_refs,
    evaluate,
    measure,
)
import textstat  # noqa: E402  # hard dependency; vendored copy on sys.path

# Judge-labelled calibration artifacts
LABELLED = {
    "bad-72": (
        "/mnt/nfs-share/Bismouth/homelab/pinkleberry/bench/"
        "unjangled-hermes-val/runs-fork-73/Holistic_Empowerment_"
        "Elementary_English_Research_20261005/"
        "research_report_20261005_holistic_empowerment_elementary_english.md"
    ),
    "good-84.5": (
        "/mnt/nfs-share/Bismouth/homelab/pinkleberry/bench/"
        "unjangled-hermes-val/runs-fork-73-v12/Holistic_Empowerment_"
        "Elementary_English_Research_20261006/"
        "research_report_20261006_holistic_empowerment_elementary_english.md"
    ),
}

# Window lengths = sentence counts of the three verified format runs
LENGTHS = {"quick-brief": 11, "comparison": 26, "research-summary": 27}


def sentences_of(path: str) -> list[str]:
    body = body_before_bibliography(open(path).read())
    return [s for s in SENT_SPLIT_RE.split(body) if len(s.strip()) > 30]


def window_metrics(window: list[str]) -> dict:
    text = " ".join(window)
    m = {
        "mean_refs": round(sum(count_refs(s) for s in window) / len(window), 2),
        "n3": sum(1 for s in window if count_refs(s) >= 3),
        "mean_sent_len": round(
            textstat.lexicon_count(text) / max(1, textstat.sentence_count(text)), 1
        ),
        "fk_grade": round(textstat.flesch_kincaid_grade(text), 1),
    }
    m["pct_3plus"] = round(100.0 * m["n3"] / len(window), 1)
    return m


GATE_NAMES = ["citation_density", "pct3plus", "sent_len", "fk_grade"]


def gate_flags(m: dict) -> dict:
    """Replicate readability_check.evaluate's fail/warn logic per gate."""
    from readability_check import (
        MEAN_REFS_MAX, PCT3_WARN, PCT3_FAIL,
        SENTLEN_WARN, SENTLEN_FAIL, FK_WARN, FK_FAIL,
    )
    return {
        "citation_density": m["mean_refs"] > MEAN_REFS_MAX,
        "pct3plus": m["pct_3plus"] > PCT3_WARN,  # warn-or-worse
        "sent_len": m["mean_sent_len"] > SENTLEN_WARN,
        "fk_grade": m["fk_grade"] > FK_WARN,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    sents = {label: sentences_of(p) for label, p in LABELLED.items()}
    report = {}
    for fmt, L in LENGTHS.items():
        report[fmt] = {"window_len": L, "gates": {}}
        for label, ss in sents.items():
            n_windows = max(0, len(ss) - L + 1)
            flag_counts = {g: 0 for g in GATE_NAMES}
            if n_windows == 0:
                report[fmt][label] = {"windows": 0}
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
        bad = report[fmt]["bad-72"]["flag_rate"]
        good = report[fmt]["good-84.5"]["flag_rate"]
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
        print(json.dumps(report, indent=2))
    else:
        for fmt, r in report.items():
            print(f"\n=== {fmt} (window={r['window_len']} sentences) ===")
            for label in ("bad-72", "good-84.5"):
                fr = r[label].get("flag_rate", {})
                rates = " ".join(f"{g}={fr.get(g, 'n/a')}" for g in GATE_NAMES)
                print(f"  {label:10} n={r[label]['windows']:4}  {rates}")
            for g, v in r["gates"].items():
                print(f"  {g:18} {v}")

    collapsed = [f"{fmt}:{g}" for fmt, r in report.items()
                 for g, v in r["gates"].items() if v == "collapsed"]
    if collapsed:
        print(f"\nREFORMULATE NEEDED: {', '.join(collapsed)}")
        return 1
    print("\nAll gates carry (or marginal) at every format length.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
