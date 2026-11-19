"""Offline tests for readability_window_check.py (ticket 1.11, E1-R11/E1-R12).

Runs the calibration-transfer audit on synthetic fixture reports copied
into a temp dir (the original judge-labelled artifacts are gone — see the
Decision line in the epic Notes). Never writes inside the skill dir.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = os.path.join(str(REPO), "scripts", "readability_window_check.py")
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "fixtures", "readability_window")

FORMATS = {"quick-brief": 11, "comparison": 26, "research-summary": 27}
GATES = ["citation_density", "pct3plus", "sent_len", "fk_grade", "internals"]
LABELS = ["bad-72", "good-84.5"]


def run_script(*argv):
    r = subprocess.run([sys.executable, SCRIPT, *argv],
                       capture_output=True, text=True, timeout=120)
    out = r.stdout + r.stderr
    assert "Traceback" not in out, f"traceback in script output:\n{out}"
    return r.returncode, r.stdout, r.stderr


def fixture_pair():
    """Copy the bad/good fixtures into a fresh temp dir; return paths."""
    tmp = tempfile.mkdtemp(prefix="rwc-test-")
    paths = {}
    for name in ("bad_report.md", "good_report.md"):
        dst = os.path.join(tmp, name)
        shutil.copy(os.path.join(FIXTURES, name), dst)
        paths[name.split("_")[0]] = dst
    return tmp, paths


def run_json(bad, good):
    code, out, err = run_script("--bad", bad, "--good", good, "--json")
    return code, json.loads(out), err


def test_separation_worse_flags_more_and_carries():
    tmp, p = fixture_pair()
    try:
        code, out, err = run_script("--bad", p["bad"], "--good", p["good"])
        assert code == 0, f"clean pair should exit 0, got {code}; stderr:\n{err}"
        for fmt in FORMATS:
            assert fmt in out, f"format {fmt} missing from output"
        assert "REFORMULATE" not in out, "no gate should collapse on this pair"
        assert "carries" in out
        assert sorted(os.listdir(tmp)) == ["bad_report.md", "good_report.md"], \
            "script must not write next to its inputs"
    finally:
        shutil.rmtree(tmp)


def test_json_shape_and_bad_flags_more():
    tmp, p = fixture_pair()
    try:
        code, report, _ = run_json(p["bad"], p["good"])
        assert code == 0
        assert set(report) == set(FORMATS), "must cover all three format lengths"
        for fmt, L in FORMATS.items():
            r = report[fmt]
            assert r["window_len"] == L
            for label in LABELS:
                entry = r[label]
                assert entry["windows"] > 0, f"{fmt}/{label} needs windows"
                rates = entry["flag_rate"]
                assert set(rates) == set(GATES), "flag_rate must cover every gate"
                for g in GATES:
                    assert 0.0 <= rates[g] <= 1.0
            assert set(r["gates"]) == set(GATES)
            for g, v in r["gates"].items():
                assert v in ("carries", "marginal"), \
                    f"{fmt}/{g} verdict {v!r} on a cleanly separated pair"
            bad = r["bad-72"]["flag_rate"]
            good = r["good-84.5"]["flag_rate"]
            for g in ("citation_density", "pct3plus", "internals"):
                assert bad[g] > good[g], f"{fmt}/{g}: bad must flag more"
            for g in GATES:
                assert bad[g] >= good[g], f"{fmt}/{g}: bad must not flag less"
    finally:
        shutil.rmtree(tmp)


def expected_verdict(bad, good):
    """The decision rule fixed before running (script docstring)."""
    if bad >= 0.80 and good <= 0.20:
        return "carries"
    if bad >= 0.50 and good <= 0.50:
        return "marginal"
    return "collapsed"


def test_mixed_body_reaches_marginal_and_collapsed_exit_1():
    """A bad label whose body is half bad prose, half good prose: windows
    straddle the seam, so flag rates land between 0 and 1 and the verdicts
    leave 'carries'. The clean pair only ever reaches 1.0 vs 0.0; this
    pins the rest of the decision rule and the collapsed exit code."""
    tmp, p = fixture_pair()
    try:
        bad_text = open(p["bad"]).read()
        good_text = open(p["good"]).read()
        head, bib = bad_text.split("## Bibliography", 1)
        good_body = good_text.split("## Bibliography", 1)[0].split("\n", 1)[1]
        mixed = os.path.join(tmp, "mixed_report.md")
        with open(mixed, "w") as f:
            f.write(head + "\n" + good_body + "\n## Bibliography" + bib)
        code, report, err = run_json(mixed, p["good"])
        assert code == 1, f"a collapsed gate must exit 1, got {code}"
        assert "REFORMULATE NEEDED" in err
        seen = set()
        for fmt in FORMATS:
            bad = report[fmt]["bad-72"]["flag_rate"]
            good = report[fmt]["good-84.5"]["flag_rate"]
            for g in GATES:
                v = report[fmt]["gates"][g]
                assert v == expected_verdict(bad[g], good[g]), \
                    f"{fmt}/{g}: verdict {v!r} breaks the rule for {bad[g]}/{good[g]}"
                seen.add(v)
        assert {"marginal", "collapsed"} <= seen, f"verdicts seen: {seen}"
    finally:
        shutil.rmtree(tmp)


def test_short_body_is_unmeasured_exit_2():
    tmp = tempfile.mkdtemp(prefix="rwc-test-")
    try:
        short = os.path.join(tmp, "short_report.md")
        shutil.copy(os.path.join(FIXTURES, "short_report.md"), short)
        good = os.path.join(tmp, "good_report.md")
        shutil.copy(os.path.join(FIXTURES, "good_report.md"), good)
        code, out, err = run_script("--bad", short, "--good", good, "--json")
        assert code == 2, f"short body must exit 2, got {code}; stderr:\n{err}"
        report = json.loads(out)
        for fmt in FORMATS:
            assert report[fmt]["bad-72"]["windows"] == 0
            assert report[fmt]["bad-72"]["segments"] == 2
            for g in GATES:
                assert report[fmt]["gates"][g] == "unmeasured"
        code, out, _ = run_script("--bad", short, "--good", good)
        assert code == 2
        assert "UNMEASURED" in out
    finally:
        shutil.rmtree(tmp)


def test_no_measurable_prose_is_unmeasured():
    tmp = tempfile.mkdtemp(prefix="rwc-test-")
    try:
        empty = os.path.join(tmp, "empty_report.md")
        with open(empty, "w") as f:
            f.write("# Title\n\n## Bibliography\n\n[1] Source. https://x\n")
        good = os.path.join(tmp, "good_report.md")
        shutil.copy(os.path.join(FIXTURES, "good_report.md"), good)
        code, out, err = run_script("--bad", empty, "--good", good, "--json")
        assert code == 2, f"no-prose body must exit 2, got {code}; stderr:\n{err}"
        report = json.loads(out)
        assert report["quick-brief"]["bad-72"]["segments"] == 0
        assert report["quick-brief"]["gates"]["citation_density"] == "unmeasured"
    finally:
        shutil.rmtree(tmp)


def test_unreadable_input_exits_3():
    tmp, p = fixture_pair()
    try:
        missing = os.path.join(tmp, "nope.md")
        code, out, err = run_script("--bad", missing, "--good", p["good"])
        assert code == 3, f"unreadable input must exit 3, got {code}"
        assert "nope.md" in err, "stderr must name the unreadable path"
        # Non-UTF-8 bytes: undecodable is unreadable (exit 3), never a
        # traceback, and never exit 1 (which means "collapsed").
        binary = os.path.join(tmp, "binary.md")
        with open(binary, "wb") as f:
            f.write(b"\xff\xfe\x00bad")
        code, out, err = run_script("--bad", binary, "--good", p["good"])
        assert code == 3, f"non-UTF-8 input must exit 3, got {code}"
        assert "binary.md" in err
    finally:
        shutil.rmtree(tmp)


def test_segmentation_matches_the_gate():
    """The audit must slide the same segments the gate measures."""
    sys.path.insert(0, os.path.join(str(REPO), "scripts"))
    import readability_window_check as rwc
    from readability_check import body_before_bibliography, measured_segments
    tmp = tempfile.mkdtemp(prefix="rwc-test-")
    try:
        path = os.path.join(tmp, "bullets.md")
        text = ("# B\n\n"
                "- An unpunctuated bullet item that is comfortably over thirty characters [1]\n"
                "- Another long bullet without end punctuation about the pipeline study [2]\n"
                "1. A numbered item long enough to count as its own segment here today\n"
                "\n"  # blank line: without it the prose line lazily continues item 1
                "Prose sentence with one citation attached [3] and enough length to count.\n\n"
                "## Bibliography\n\n[1] A. https://x\n[2] B. https://y\n[3] C. https://z\n")
        with open(path, "w") as f:
            f.write(text)
        got = rwc.sentences_of(path)
        want = measured_segments(body_before_bibliography(text))
        assert got == want, "audit segmentation must equal the gate's"
        assert len(got) == 4, f"bullets must be their own segments, got {len(got)}"
    finally:
        shutil.rmtree(tmp)


def test_window_metrics_terminate_unpunctuated_segments():
    """Entry 1.13: window segments are terminated before textstat sees
    the joined window, exactly as the gate terminates the whole body —
    two unpunctuated 12-word bullets are two sentences (mean 12.0),
    not one merged 24-word sentence."""
    sys.path.insert(0, os.path.join(str(REPO), "scripts"))
    import readability_window_check as rwc
    window = [
        "- First bullet claims a finding from the trial and stays clearly readable",
        "- Second bullet records one more finding here with plain words again today",
    ]
    m = rwc.window_metrics(window)
    assert m["mean_sent_len"] == 12.0, (
        f"each unpunctuated window segment must be its own textstat "
        f"sentence, got {m['mean_sent_len']}"
    )
    # A hard-wrapped item is one segment and is terminated once, at its
    # end, so its continuation lines stay in the same textstat sentence.
    wrapped = ("- First bullet claims a finding from the trial\n"
               "  and stays clearly readable for every reader")
    m = rwc.window_metrics([wrapped, window[1]])
    # (15 + 12) / 2 = 13.5; split per line it would be 27 / 3 = 9.0
    assert m["mean_sent_len"] == 13.5, m


if __name__ == "__main__":
    test_separation_worse_flags_more_and_carries()
    test_json_shape_and_bad_flags_more()
    test_mixed_body_reaches_marginal_and_collapsed_exit_1()
    test_short_body_is_unmeasured_exit_2()
    test_no_measurable_prose_is_unmeasured()
    test_unreadable_input_exits_3()
    test_segmentation_matches_the_gate()
    test_window_metrics_terminate_unpunctuated_segments()
    print("all 8 readability_window_check tests ran and passed")
