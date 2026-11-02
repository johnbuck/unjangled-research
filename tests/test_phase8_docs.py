"""Phase 8 docs wiring (story 2.3 + story 3.2 + story 4.5): SKILL.md and
reference/*.md carry no mention of the retired upstream HTML template (named
below only as a concatenation so the repo-wide grep stays clean); SKILL.md
lists render_report.py, render_deck.py, render_pptx.py, and check_theme.py,
and still names the PDF output; every scripts/*.py path named in SKILL.md,
the reference docs, and README.md exists on disk."""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
SKILL = os.path.join(ROOT, "SKILL.md")
REFERENCE = os.path.join(ROOT, "reference")
README = os.path.join(ROOT, "README.md")
SCRIPTS = os.path.join(ROOT, "scripts")
RETIRED_TEMPLATE = "mck" + "insey"


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def reference_docs():
    return [SKILL, README] + sorted(
        os.path.join(REFERENCE, n)
        for n in os.listdir(REFERENCE)
        if n.endswith(".md")
    )


def test_no_retired_template_mentions():
    for doc in reference_docs():
        assert RETIRED_TEMPLATE not in read(doc).lower(), doc


def test_skill_lists_phase8_scripts():
    s = read(SKILL)
    assert "render_report.py" in s
    assert "render_deck.py" in s
    assert "render_pptx.py" in s
    assert "check_theme.py" in s


def test_skill_still_offers_pdf_output():
    s = read(SKILL)
    assert "PDF (professional print, auto-opened)" in s


def test_script_paths_exist():
    for doc in reference_docs():
        text = read(doc)
        for name in set(re.findall(r"scripts/([A-Za-z0-9_]+\.py)", text)):
            assert os.path.isfile(os.path.join(SCRIPTS, name)), (doc, name)


if __name__ == "__main__":
    test_no_retired_template_mentions()
    test_skill_lists_phase8_scripts()
    test_skill_still_offers_pdf_output()
    test_script_paths_exist()
    print("all 4 phase8-docs tests ran and passed")
