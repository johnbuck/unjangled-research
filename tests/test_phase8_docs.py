"""Phase 8 docs wiring (story 2.3 + story 3.2 + story 4.5 + story 5.4 + bug
2): SKILL.md and reference/*.md carry no mention of the retired upstream HTML
template (named below only as a concatenation so the repo-wide grep stays
clean); SKILL.md lists render_report.py, render_deck.py, render_pptx.py, and
check_theme.py, and still names the PDF output; every scripts/*.py path named
in SKILL.md, the reference docs, and README.md exists on disk. The frontmatter
description advertises every output (report, HTML slide deck, PowerPoint
.pptx, PDF) plus the deck trigger phrases within 1024 characters, keeping the
research triggers and the "not for simple lookups" boundary. SKILL.md carries
an Outputs section and a deck section, links the authoring guide
(reference/slide-decks.md) from both the Outputs section and the Decision
Tree, and nothing in it implies decks come only from a research run. The
guide documents every layout in the deck_spec schema's layout set (derived
from the schema, so a new layout without a guide section fails), and every
JSON example block in the guide parses and validates with deck_spec.py.
Read-only: this test writes nothing."""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
SKILL = os.path.join(ROOT, "SKILL.md")
REFERENCE = os.path.join(ROOT, "reference")
README = os.path.join(ROOT, "README.md")
SCRIPTS = os.path.join(ROOT, "scripts")
SCHEMA = os.path.join(ROOT, "schemas", "deck_spec.schema.json")
GUIDE = os.path.join(REFERENCE, "slide-decks.md")
RETIRED_TEMPLATE = "mck" + "insey"

sys.path.insert(0, SCRIPTS)
from deck_spec import validate_deck  # noqa: E402


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def reference_docs():
    return [SKILL, README] + sorted(
        os.path.join(REFERENCE, n)
        for n in os.listdir(REFERENCE)
        if n.endswith(".md")
    )


def frontmatter_description():
    lines = read(SKILL).splitlines()
    assert lines[0] == "---", "SKILL.md has no frontmatter"
    end = lines.index("---", 1)
    for line in lines[1:end]:
        if line.startswith("description:"):
            return line[len("description:"):].strip()
    raise AssertionError("frontmatter has no description")


def schema_layouts():
    """The layout set from the schema's slide oneOf branches, not a copy."""
    with open(SCHEMA, encoding="utf-8") as f:
        schema = json.load(f)
    layouts = set()
    for branch in schema["$defs"]["slide"]["oneOf"]:
        const = branch["properties"]["layout"].get("const")
        assert const, "schema branch without a layout const"
        layouts.add(const)
    return layouts


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


def test_description_advertises_every_output():
    d = frontmatter_description()
    assert len(d) <= 1024, len(d)
    for phrase in (
        "report",
        "slide deck",
        "slides",
        "presentation",
        "PowerPoint",
        ".pptx",
        "PDF",
        "deep research",
        "comprehensive analysis",
        "research report",
        "compare X vs Y",
        "analyze trends",
        "state of the art",
        "make a deck",
        "turn this into slides",
        "Not for simple lookups",
    ):
        assert phrase in d, phrase


def test_skill_outputs_and_deck_sections():
    s = read(SKILL)
    assert "## Outputs" in s
    assert "## Slide decks" in s
    body = s[s.index("## Outputs"):]
    for needed in (
        "render_report.py",
        "render_deck.py",
        "render_pptx.py",
        "check_theme.py",
        "slide-decks.md",
    ):
        assert needed in body, needed
    for name in set(re.findall(r"scripts/([A-Za-z0-9_]+\.py)", body)):
        assert os.path.isfile(os.path.join(SCRIPTS, name)), name


def test_decision_tree_links_the_guide():
    s = read(SKILL)
    tree = s[s.index("## Decision Tree"):]
    tree = tree[:tree.index("```", tree.index("```") + 3) + 3]
    assert "slide-decks.md" in tree, "Decision Tree does not route decks"
    for path in ("Path A", "Path B", "Path C"):
        assert path in tree, path


def test_guide_documents_every_schema_layout():
    guide = read(GUIDE)
    documented = set(re.findall(r"^#### `([a-z_]+)`", guide, re.M))
    layouts = schema_layouts()
    missing = layouts - documented
    assert not missing, f"layouts without a guide section: {sorted(missing)}"


def test_guide_json_examples_validate():
    guide = read(GUIDE)
    blocks = re.findall(r"```json\n(.*?)```", guide, re.S)
    assert len(blocks) >= len(schema_layouts()), (
        "fewer JSON examples than layouts")
    for i, block in enumerate(blocks):
        obj = json.loads(block)  # every example parses
        if "slides" in obj:      # a whole deck example
            deck = obj
        else:
            assert "layout" in obj, f"example {i} is neither deck nor slide"
            deck = {"title": "Example", "slides": [obj]}
        validate_deck(deck)      # DeckError names the slide and field


if __name__ == "__main__":
    test_no_retired_template_mentions()
    test_skill_lists_phase8_scripts()
    test_skill_still_offers_pdf_output()
    test_script_paths_exist()
    test_description_advertises_every_output()
    test_skill_outputs_and_deck_sections()
    test_decision_tree_links_the_guide()
    test_guide_documents_every_schema_layout()
    test_guide_json_examples_validate()
    print("all 9 phase8-docs tests ran and passed")
