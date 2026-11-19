"""Known-answer tests for readability_check.py."""
import os
import subprocess
import sys
sys.path.insert(0, "scripts")
import readability_check
from readability_check import (
    measure,
    evaluate,
    terminated_body,
    SENTLEN_WARN,
    FK_WARN,
)

GATE = os.path.join("scripts", "readability_check.py")


def run_gate(path):
    """Run the CLI on a fixture; a traceback is always a failure."""
    r = subprocess.run([sys.executable, GATE, path], capture_output=True, text=True)
    out = r.stdout + r.stderr
    assert "Traceback" not in out, f"traceback in gate output:\n{out}"
    return r.returncode, out

def test_dense_fixture_fails():
    m = measure(open("tests/fixtures/dense_internals_report.md").read())
    fails, warns, adv = evaluate(m)
    assert fails, "positive control must fail"
    assert m["internals_hits"] > 0
    assert m["mean_refs"] > 1.6

def test_clean_fixture_passes():
    m = measure(open("tests/fixtures/clean_report.md").read())
    fails, warns, adv = evaluate(m)
    assert not fails and not warns, "negative control must pass clean"

def test_bibliography_excluded():
    text = "Body sentence with one ref [1] and more than thirty characters.\n\n## Bibliography\n[1] Author. (2024). The pipeline of something. Journal.\n"
    m = measure(text)
    assert m["sentences"] == 1, "bibliography entries must not count as sentences"
    assert m["internals_hits"] == 0, "bibliography must not trip internals gate"

def test_comma_style_chains_counted():
    text = "A claim supported by many works in one comma chain [1, 2, 3, 4] here. Another ordinary sentence with exactly one reference attached [5]. One more sentence with no references at all and enough length to count."
    m = measure(text)
    assert m["refs"] == 5, f"expected 5 refs, got {m['refs']}"

def test_postbib_internals_fail():
    """Narration moved past the bibliography must still trip the gate."""
    m = measure(open("tests/fixtures/postbib_internals_report.md").read())
    fails, warns, adv = evaluate(m)
    assert fails and any("internals" in f for f in fails)
    # citation metrics unchanged by the leak
    assert m["mean_refs"] <= 1.6

def test_longwinded_fixture_fails():
    """Long tangled sentences trip the textstat gates even with clean
    citations and zero internals — what the citation and internals gates alone missed."""
    m = measure(open("tests/fixtures/longwinded_report.md").read())
    fails, warns, adv = evaluate(m)
    assert m["mean_sent_len"] > SENTLEN_WARN or m["fk_grade"] > FK_WARN
    assert any("sentence length" in f or "reading grade" in f for f in fails + warns)
    assert m["internals_hits"] == 0 and m["mean_refs"] <= 1.6

def test_funding_subsection_is_measured_and_fails():
    """F2 regression: '### Sources of funding' is not a bibliography start.

    On 35d132d the unanchored split dropped everything from that subsection
    on, so this report passed with mean 0.0. The shared rule keeps it in the
    density window: 26 sentences, 125 refs, mean 4.81.
    """
    m = measure(open("tests/fixtures/bibliography/funding_subsection_report.md").read())
    fails, warns, adv = evaluate(m)
    assert m["sentences"] == 26, "the funding subsection must stay in the window"
    assert m["refs"] == 125
    assert m["mean_refs"] == 4.81
    assert m["mean_refs"] > 1.6
    assert any("citation density" in f for f in fails), "density gate must fail"
    assert m["internals_hits"] == 0, "fixture must not trip unrelated gates"

def test_postbib_and_subsection_split_independent():
    """A '### Sources...' subsection and a later real '## Bibliography'
    coexist: density window stops at the bibliography, not the subsection."""
    text = (
        "# T\n\n## Body\n\nSubsection prose with heavy citing [1, 2, 3, 4, 5].\n\n"
        "### Sources of funding\n\nMore subsection prose citing heavily [1, 2, 3, 4, 5].\n\n"
        "## Bibliography\n\n[1] A (2024). One.\n[2] A (2024). Two.\n"
        "[3] A (2024). Three.\n[4] A (2024). Four.\n[5] A (2024). Five.\n"
    )
    m = measure(text)
    assert m["sentences"] == 2, "both subsection sentences measured, entries not"
    assert m["refs"] == 10 and m["mean_refs"] == 5.0
    assert m["internals_hits"] == 0

def test_code_spans_do_not_count_refs():
    """Citations inside code spans and bracketed years are not refs (E1-R1)."""
    text = (
        "This body sentence cites one real source [1] and hides others.\n"
        "Another sentence shows `cited code [7]` and the year [2024] plainly.\n"
    )
    m = measure(text)
    assert m["refs"] == 1, "code-span [7] and year [2024] must not count"


def test_short_body_exits_1_no_measurable_prose():
    """F10 regression: '# T\n\nOk [1].' crashed with KeyError 'mean_sent_len'.

    On 35d132d the run died in a traceback; it must exit 1 with a clean
    "no measurable prose" failure.
    """
    rc, out = run_gate("tests/fixtures/readability/short_body.md")
    assert rc == 1
    assert "no measurable prose" in out
    assert "KeyError" not in out


def test_short_body_with_internals_names_both():
    """A report with nothing measurable cannot evade the internals gate:
    the no-prose fail and the leak fail are both named (7 hits > 6)."""
    text = (
        "# T\n\nOk [1]. A pipeline ran. A harness ran. A pipeline ran. "
        "A harness ran. A pipeline ran. A harness ran. A pipeline ran."
    )
    m = measure(text)
    fails, warns, adv = evaluate(m)
    assert m["sentences"] == 0, "every segment is under 30 characters"
    assert m["internals_hits"] == 7, "internals stay measured on the zeroed path"
    assert any("no measurable prose" in f for f in fails)
    assert any("leakage" in f for f in fails)


def test_bullet_only_body_segments_per_bullet():
    """F10 regression: bullets without end punctuation merged into one
    giant 'sentence' (sentences=1, mean 4.0, pct3 100%). Each >30-char
    bullet is now its own segment: 2 sentences, per-bullet metrics."""
    m = measure(open("tests/fixtures/readability/bullet_only.md").read())
    fails, warns, adv = evaluate(m)
    assert m["sentences"] == 2, "each >30-char bullet is its own segment"
    assert m["refs"] == 3 and m["mean_refs"] == 1.5
    assert m["pct_3plus"] == 0.0 and m["max_chain"] == 2
    assert not any("citation density" in f for f in fails)


def test_bullet_only_body_metrics_pass():
    """Entry 1.13: with each unpunctuated bullet terminated before
    textstat, the readable bullet-only body passes every gate."""
    m = measure(open("tests/fixtures/readability/bullet_only.md").read())
    fails, warns, adv = evaluate(m)
    assert m["mean_sent_len"] == 11.7, f"per-bullet mean, got {m['mean_sent_len']}"
    assert m["fk_grade"] == 5.8
    assert not fails and not warns, f"bullet-only body must pass: {fails} {warns}"


def test_bullet_only_cli_runs_clean():
    """Entry 1.13: bullet_only.md now passes the CLI (exit 0). On 1.2 it
    exited 1 with a false 35-word merged 'sentence' — that merged
    sentence was the defect this ticket exists to fix."""
    rc, out = run_gate("tests/fixtures/readability/bullet_only.md")
    assert rc == 0, out
    assert "FAIL" not in out and "WARN" not in out


def test_bullet_key_points_fixture_passes():
    """A realistic bullet-only quick-brief Key Points body (six
    unpunctuated, cited, normal-length bullets) passes end to end."""
    rc, out = run_gate("tests/fixtures/readability/bullet_key_points.md")
    assert rc == 0, out
    assert "FAIL" not in out and "WARN" not in out


def test_unpunctuated_bullets_own_textstat_sentences():
    """Entry 1.13: three 12-word unpunctuated bullets are three textstat
    sentences (mean 12.0), not one merged 36-word sentence."""
    bullets = (
        "- First bullet claims a finding from the trial and stays clearly readable\n"
        "- Second bullet records another finding with plain words and no citation here\n"
        "- Third bullet closes the list of measured items with a final claim\n"
    )
    bib = "\n## Bibliography\n\n[1] A (2024). One.\n"
    m = measure(bullets + bib)
    assert m["sentences"] == 3
    assert m["mean_sent_len"] == 12.0, (
        f"each bullet must be its own textstat sentence, got {m['mean_sent_len']}"
    )
    # Numbered items too ('1)' and '1.' delimiters); the marker token
    # counts as a word, so the mean is 13 = (3 x 12 + 3 markers) / 3.
    for delim in (")", "."):
        numbered = (
            bullets.replace("- First", f"1{delim} First")
                   .replace("- Second", f"2{delim} Second")
                   .replace("- Third", f"3{delim} Third")
        ) + bib
        m = measure(numbered)
        assert m["sentences"] == 3
        assert m["mean_sent_len"] == 13.0, (
            f"'1{delim}' items must each be their own textstat sentence, "
            f"got {m['mean_sent_len']}"
        )


def test_terminated_body_leaves_punctuated_text_unchanged():
    """A segment already ending in terminal punctuation is unchanged:
    prose bodies and punctuated bullets round-trip byte-identically."""
    prose = "# Heading\n\nA wrapped sentence that continues\non the next line [1].\n"
    punctuated = (
        "# Key Points\n\n"
        "- Daily two-question exit tickets improve retention [1].\n"
        "- Weekly checks suit stable content [3].   \n"
        "Plain paragraph after the bullets.\n"
    )
    assert terminated_body(prose) == prose
    assert terminated_body(punctuated) == punctuated


def test_long_single_bullet_fails_sentence_length():
    """A genuinely long-winded bullet (35+ words, one item) still fails
    the sentence-length gate: termination splits items, it never
    shortens one."""
    import tempfile
    bullet = "- " + " ".join(f"claim{i}" for i in range(1, 37)) + " [1]\n"
    text = "# T\n\n" + bullet + "\n## Bibliography\n\n[1] A (2024). One.\n"
    m = measure(text)
    fails, warns, adv = evaluate(m)
    assert m["sentences"] == 1 and m["mean_sent_len"] >= 35
    assert any("sentence length" in f for f in fails)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "long_bullet.md")
        with open(path, "w") as f:
            f.write(text)
        rc, out = run_gate(path)
        assert rc == 1
        assert "sentence length" in out


def test_wrapped_long_bullet_stays_one_sentence():
    """Entry 1.13 review: a 35-word bullet hard-wrapped across three
    source lines is ONE list item. Termination and segmentation apply
    to the whole item (marker line plus continuation lines, indented or
    lazy), so wrapping never splits it into short pseudo-sentences that
    pass the sentence-length gate; it fails exactly as unwrapped."""
    import tempfile
    words = (
        "The district trial that ran across six schools for two full terms "
        "found that short practice sets of ten minutes consistently "
        "outperformed hour-long homework on every measured outcome "
        "including retention and completion rates"
    ).split()
    bib = "\n## Bibliography\n\n[1] A (2024). One.\n"
    one_line = "- " + " ".join(words) + " [1]\n"
    lines = [words[:13], words[13:24], words[24:]]
    indented = "- " + "\n  ".join(" ".join(w) for w in lines) + " [1]\n"
    lazy = "- " + "\n".join(" ".join(w) for w in lines) + " [1]\n"
    want = measure("# T\n\n" + one_line + bib)
    assert want["sentences"] == 1 and want["mean_sent_len"] >= 35
    for wrapped in (indented, lazy):
        text = "# T\n\n" + wrapped + bib
        body = text.split("## Bibliography")[0]
        assert readability_check.measured_segments(body) == [wrapped.rstrip("\n")]
        # one period, at the end of the item's last line
        assert terminated_body(body).count(".") == 1
        assert terminated_body(body).endswith("[1].\n\n")
        m = measure(text)
        assert m["sentences"] == 1
        assert m["mean_sent_len"] == want["mean_sent_len"], (
            f"wrapped bullet must measure as unwrapped, got {m['mean_sent_len']}"
        )
        fails, _, _ = evaluate(m)
        assert any("sentence length" in f for f in fails)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "wrapped_bullet.md")
            with open(path, "w") as f:
                f.write(text)
            rc, out = run_gate(path)
            assert rc == 1 and "sentence length" in out, out


def test_wrapped_bullet_citations_count_once():
    """A wrapped item with three citations is one segment carrying all
    three refs, so wrapping cannot halve its citation density."""
    item = (
        "- Short practice sets outperformed long homework in the trial\n"
        "  across six schools and two terms [1][2][3]\n"
    )
    m = measure("# T\n\n" + item + "\n## Bibliography\n\n[1] A (2024). One.\n")
    assert m["sentences"] == 1 and m["refs"] == 3 and m["max_chain"] == 3


def test_bullet_with_two_sentences_splits_inside():
    text = "- First claim inside the bullet ends with a period. Second claim in the same bullet [2].\n"
    m = measure(text)
    assert m["sentences"] == 2, "SENT_SPLIT_RE still applies inside a bullet"
    assert m["refs"] == 1


def test_prose_wrap_still_merges():
    """Non-bullet runs keep the classic behaviour: prose wrapping across a
    line break with no sentence ender stays one segment."""
    text = (
        "This sentence deliberately wraps across two lines with no\n"
        "end punctuation before the break and cites [1] once.\n\n"
        "## Bibliography\n\n[1] A (2024). One.\n"
    )
    m = measure(text)
    assert m["sentences"] == 1 and m["refs"] == 1


def test_thematic_break_does_not_split_prose():
    """Review pass 1: a spaced thematic break ('- - -') is not a bullet;
    the prose run around it keeps the classic merge behaviour."""
    text = (
        "A heading line with no end punctuation continues here\n- - -\n"
        "and trailing prose after the break continues without a period either today"
    )
    m = measure(text)
    assert m["sentences"] == 1, "a thematic break must not split a prose run"


def test_tab_indented_marker_stays_prose():
    """Review pass 1: '\\t- x' is indented code in CommonMark, not a list
    item; it keeps the classic run behaviour."""
    text = (
        "A line of prose without end punctuation keeps going here\n"
        "\t- tab indented marker line continues as prose"
    )
    m = measure(text)
    assert m["sentences"] == 1


def test_numbered_items_segment_per_item():
    """Review: '1)' numbered items have no '.' for SENT_SPLIT_RE, so on
    the pre-fix code three unpunctuated items merged into one segment
    (sentences=1, mean 4.0, pct3 100%). Each item is now its own segment,
    for both the '1)' and '1.' delimiters."""
    items = (
        "First numbered item states a claim with one citation [1] and keeps going",
        "Second numbered item states another claim with two citations [2, 3] and runs on",
        "Third numbered item makes a third distinct claim with one more cite [4]",
    )
    bib = "\n\n## Bibliography\n\n[1] A (2024). One.\n"
    for delim in (")", "."):
        text = "# Key Points\n\n" + "\n".join(
            f"{i}{delim} {item}" for i, item in enumerate(items, 1)
        ) + bib
        m = measure(text)
        assert m["sentences"] == 3, f"'{delim}' items must not merge"
        assert m["refs"] == 4 and m["max_chain"] == 2 and m["pct_3plus"] == 0.0


def test_bibliography_only_file_clean_fail():
    """A file with no body at all fails cleanly, never a traceback."""
    m = measure("## Bibliography\n\n[1] A (2024). One.\n")
    fails, warns, adv = evaluate(m)
    assert m["sentences"] == 0 and m["internals_hits"] == 0
    assert any("no measurable prose" in f for f in fails) and len(fails) == 1


def test_clean_fixture_exits_0():
    rc, out = run_gate("tests/fixtures/clean_report.md")
    assert rc == 0, out


def test_dense_fixture_exits_1():
    rc, out = run_gate("tests/fixtures/dense_internals_report.md")
    assert rc == 1, out


def test_warn_only_fixture_exits_2():
    """F11 exit contract: warnings only exits 2, not 0 and not 1."""
    rc, out = run_gate("tests/fixtures/readability/warn_only.md")
    assert rc == 2
    assert "WARN" in out and "FAIL" not in out


def test_docstring_states_real_thresholds():
    """F10: the docstring must state the thresholds the code enforces."""
    doc = readability_check.__doc__
    for needle in (
        "warn > 2", "fail > 6",          # internals
        "fail > 1.6",                    # citation density
        "warn > 20%", "fail > 25%",      # pct 3+
        "warn > 22", "fail > 27",        # sentence length
        "warn > 16.5", "fail > 18.0",    # Flesch-Kincaid
        "no measurable prose",           # empty-window gate
        "0 pass", "2 warnings only", "1 fail",  # exit codes
    ):
        assert needle in doc, f"docstring missing real threshold: {needle}"

if __name__ == "__main__":
    test_dense_fixture_fails()
    test_clean_fixture_passes()
    test_bibliography_excluded()
    test_comma_style_chains_counted()
    test_postbib_internals_fail()
    test_longwinded_fixture_fails()
    test_funding_subsection_is_measured_and_fails()
    test_postbib_and_subsection_split_independent()
    test_code_spans_do_not_count_refs()
    test_short_body_exits_1_no_measurable_prose()
    test_short_body_with_internals_names_both()
    test_bullet_only_body_segments_per_bullet()
    test_bullet_only_body_metrics_pass()
    test_bullet_only_cli_runs_clean()
    test_bullet_key_points_fixture_passes()
    test_unpunctuated_bullets_own_textstat_sentences()
    test_terminated_body_leaves_punctuated_text_unchanged()
    test_long_single_bullet_fails_sentence_length()
    test_wrapped_long_bullet_stays_one_sentence()
    test_wrapped_bullet_citations_count_once()
    test_bullet_with_two_sentences_splits_inside()
    test_prose_wrap_still_merges()
    test_thematic_break_does_not_split_prose()
    test_tab_indented_marker_stays_prose()
    test_numbered_items_segment_per_item()
    test_bibliography_only_file_clean_fail()
    test_clean_fixture_exits_0()
    test_dense_fixture_exits_1()
    test_warn_only_fixture_exits_2()
    test_docstring_states_real_thresholds()
    print("all 30 known-answer tests ran and passed")
