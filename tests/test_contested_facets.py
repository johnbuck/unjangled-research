"""CAP-9 known-answer tests: contested facets must be covered."""
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

def test_facets_without_section_fails():
    assert not run("report_no_perspectives.md", "manifest_with_facets.json"), \
        "listed facets + no Perspectives section must FAIL"

def test_facets_with_section_passes():
    assert run("report_with_perspectives.md", "manifest_with_facets.json"), \
        "listed facets + Perspectives section must PASS"

def test_empty_facets_pass_without_section():
    assert run("report_no_perspectives.md", "manifest_empty.json"), \
        "empty facet list must not require the section"

def test_no_manifest_skips_gate():
    assert run("report_no_perspectives.md"), \
        "without --manifest the contested gate is out of scope"

if __name__ == "__main__":
    test_facets_without_section_fails()
    test_facets_with_section_passes()
    test_empty_facets_pass_without_section()
    test_no_manifest_skips_gate()
    print("all 4 contested-facet tests ran and passed")
