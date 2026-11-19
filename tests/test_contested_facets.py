"""Known-answer tests: contested facets must be covered."""
import subprocess, sys, os

HERE = os.path.dirname(os.path.abspath(__file__))
V = lambda *p: os.path.join(HERE, "fixtures", "contested", *p)
SCRIPT = os.path.join(HERE, "..", "scripts", "validate_report.py")

def run(report, manifest=None):
    cmd = [sys.executable, SCRIPT, "--report", V(report), "--format", "comprehensive-report"]
    if manifest:
        cmd += ["--manifest", V(manifest)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode == 0

def run_out(report, manifest=None):
    cmd = [sys.executable, SCRIPT, "--report", V(report), "--format", "comprehensive-report"]
    if manifest:
        cmd += ["--manifest", V(manifest)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, r.stdout

def test_facets_without_section_fails():
    assert not run("report_no_perspectives.md", "manifest_with_facets.json"), \
        "listed facets + no Perspectives section must FAIL"

def test_facets_with_section_passes():
    assert run("report_with_perspectives.md", "manifest_with_facets.json"), \
        "listed facets + Perspectives section must PASS"

def test_uncovered_facet_fails_naming_it():
    code, out = run_out("report_with_perspectives.md", "manifest_facet_uncovered.json")
    assert code == 1, out
    assert "does not cover" in out and "replication across cohorts" in out, \
        "the uncovered facet must be named"

def test_body_phrase_covers_facet():
    assert run("report_body_phrase.md", "manifest_with_facets.json"), \
        "a facet named verbatim in the section prose covers the facet"

def test_empty_facets_pass_without_section():
    assert run("report_no_perspectives.md", "manifest_empty.json"), \
        "empty facet list must not require the section"

def test_no_manifest_skips_gate():
    assert run("report_no_perspectives.md"), \
        "without --manifest the contested gate is out of scope"

if __name__ == "__main__":
    test_facets_without_section_fails()
    test_facets_with_section_passes()
    test_uncovered_facet_fails_naming_it()
    test_body_phrase_covers_facet()
    test_empty_facets_pass_without_section()
    test_no_manifest_skips_gate()
    print("all 6 contested-facet tests ran and passed")
