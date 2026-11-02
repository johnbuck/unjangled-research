"""Render model builder: every fixture yields a schema-valid model whose
key_stats are verbatim report numbers, the bibliography stays out of
sections, and a contested manifest yields facets with two sides each."""
import json
import os
import re
import string
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

from build_render_model import (  # noqa: E402
    CONNECTOR_WORDS,
    _stat_label,
    build_model,
    sentences,
    strip_md,
)

FORMATS_DIR = os.path.join(HERE, "fixtures", "formats")
CONTESTED_DIR = os.path.join(HERE, "fixtures", "contested")
RENDER_DIR = os.path.join(HERE, "fixtures", "render")
SCHEMA_PATH = os.path.join(HERE, "..", "schemas", "render_model.schema.json")

CASES = [
    (os.path.join(FORMATS_DIR, "quick_brief.md"), "quick-brief"),
    (os.path.join(FORMATS_DIR, "comparison.md"), "comparison"),
    (os.path.join(FORMATS_DIR, "research_summary.md"), "research-summary"),
    (os.path.join(FORMATS_DIR, "discovery_catalog.md"), "discovery-catalog"),
    (os.path.join(HERE, "fixtures", "valid_report.md"), "comprehensive-report"),
]

MODEL_KEYS = [
    "title", "subtitle", "date", "format", "executive_summary", "key_stats",
    "sections", "findings", "contested_facets", "sources",
]


def _is_type(value, name):
    if name == "string":
        return isinstance(value, str)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "array":
        return isinstance(value, list)
    if name == "object":
        return isinstance(value, dict)
    if name == "null":
        return value is None
    return False


def schema_errors(schema, value, path="$"):
    """Small stdlib validator: required keys and types by hand (no
    jsonschema package). Supports the keywords render_model.schema.json
    uses: type, enum, required, properties, additionalProperties, items,
    minItems/maxItems, minLength, minimum."""
    errors = []
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: const mismatch")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in enum {schema['enum']}")
    t = schema.get("type")
    if t is not None:
        names = t if isinstance(t, list) else [t]
        if not any(_is_type(value, n) for n in names):
            errors.append(f"{path}: expected type {names}, got {type(value).__name__}")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required '{key}'")
        props = schema.get("properties", {})
        for key, sub in props.items():
            if key in value:
                errors += schema_errors(sub, value[key], f"{path}.{key}")
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in props:
                    errors.append(f"{path}: unexpected '{key}'")
    if isinstance(value, list):
        if "items" in schema:
            for i, item in enumerate(value):
                errors += schema_errors(schema["items"], item, f"{path}[{i}]")
        lo, hi = schema.get("minItems"), schema.get("maxItems")
        if lo is not None and len(value) < lo:
            errors.append(f"{path}: fewer than {lo} items")
        if hi is not None and len(value) > hi:
            errors.append(f"{path}: more than {hi} items")
    if isinstance(value, str) and "minLength" in schema and len(value) < schema["minLength"]:
        errors.append(f"{path}: shorter than {schema['minLength']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        lo, hi = schema.get("minimum"), schema.get("maximum")
        if lo is not None and value < lo:
            errors.append(f"{path}: below minimum {lo}")
        if hi is not None and value > hi:
            errors.append(f"{path}: above maximum {hi}")
    return errors


def validate_model(model):
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        schema = json.load(f)
    return schema_errors(schema, model)


def build(path, manifest=None, fmt=None):
    with open(path, encoding="utf-8") as f:
        return build_model(f.read(), manifest, fmt)


def test_model_builds_for_every_fixture():
    for path, fmt in CASES:
        model = build(path)
        assert sorted(model.keys()) == sorted(MODEL_KEYS), path
        assert model["title"], path
        assert model["format"] == fmt, (path, model["format"], fmt)
        assert model["sources"], path


def test_format_precedence():
    path = os.path.join(FORMATS_DIR, "research_summary.md")
    with open(os.path.join(RENDER_DIR, "manifest_format.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    assert build(path)["format"] == "research-summary"
    assert build(path, manifest)["format"] == "research-summary"
    assert build(path, manifest, fmt="quick-brief")["format"] == "quick-brief"
    assert build(path, fmt="comparison")["format"] == "comparison"


def test_date_from_manifest():
    path = os.path.join(FORMATS_DIR, "research_summary.md")
    with open(os.path.join(RENDER_DIR, "manifest_format.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    assert build(path)["date"] is None
    assert build(path, manifest)["date"] == "2026-10-02"


def test_each_model_passes_schema():
    for path, fmt in CASES:
        model = build(path)
        errors = validate_model(model)
        assert not errors, (path, errors)


def test_key_stats_verbatim_and_bounded():
    for path, fmt in CASES:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        model = build(path)
        assert len(model["key_stats"]) <= 6, path
        for stat in model["key_stats"]:
            assert stat["value"] in text, (path, stat)
            assert stat["label"], (path, stat)
            assert len(stat["label"].split()) >= 3, (path, stat)
            assert stat["ref"] is None or (
                f"[{stat['ref']}]" in text), (path, stat)


def test_stat_label_handles_quote_opened_before_value():
    sent = (
        'Google\'s launch post announced "a new, open protocol called '
        'Agent2Agent (A2A), with support and contributions from more than '
        '50 technology partners" in April 2025'
    )
    label = _stat_label(sent, "50 technology partners")
    assert label, "a2a-shaped sentence must yield a label"
    words = label.split()
    assert len(words) >= 3, label
    assert label.count('"') % 2 == 0, f"unbalanced quotes: {label!r}"
    assert label.count("(") == label.count(")"), label
    assert words[-1].lower() not in CONNECTOR_WORDS, label
    assert words[0].lower() not in CONNECTOR_WORDS, label
    assert "support" in words or "contributions" in words, label


def _edge_word(word):
    return word.strip(string.punctuation).lower()


def _normalize_sentence(sent):
    text = re.sub(r"\s*\[E:[^\]]*\]", "", strip_md(sent))
    return re.sub(r"\s*\[\d+\]", "", text)


def test_stat_captions_are_contiguous_source_phrases():
    """Every caption is one contiguous 3-8-word run of its source
    sentence (markdown and citation markers removed) — never words
    joined across the removed value — and never opens or closes on a
    connector."""
    for path, fmt in CASES:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
        model = build(path)
        for stat in model["key_stats"]:
            caption = re.sub(r"\s+", " ", stat["label"]).strip()
            words = caption.split()
            assert 3 <= len(words) <= 8, (path, stat, caption)
            assert _edge_word(words[0]) not in CONNECTOR_WORDS, (path, stat, caption)
            assert _edge_word(words[-1]) not in CONNECTOR_WORDS, (path, stat, caption)
            assert stat["value"] not in caption, (path, stat, caption)
            sources = []
            for line in lines:
                s = re.sub(r"^\s*[-*]\s+", "", line.strip())
                for sent in sentences(s):
                    norm = re.sub(r"\s+", " ", _normalize_sentence(sent))
                    if stat["value"] in norm:
                        sources.append(norm)
            assert sources, (path, stat, caption)
            assert any(caption in norm for norm in sources), \
                (path, stat, caption, sources)


def test_stat_label_not_spliced_across_value():
    """A value in the middle of its clause must not yield a caption
    spliced from the words on either side of it: the screen-time shape
    ('Among free of baseline symptoms') and the discovery shape
    ('GitHub mirror carries and a release')."""
    screen_time = (
        "Among 2,587 tenth-graders free of baseline symptoms, each "
        "additional high-frequency digital media activity raised the "
        "odds of later ADHD symptoms, OR 1.11, or 1.10 after covariate "
        "adjustment [5]."
    )
    label = _stat_label(screen_time, "2,587 tenth-graders")
    assert label == "tenth-graders free of baseline symptoms", label

    discovery = "The GitHub mirror carries 9,200 stars and a release this month [2]."
    label = _stat_label(discovery, "9,200 stars")
    assert label is None, label


def test_stat_label_strips_edge_punctuation_and_parenthetical():
    """The a2a shape: the span beside the value opens on a parenthetical
    fragment followed by a comma. The fragment and the dangling comma are
    stripped at the edge, the stopword trim and the 3-8-word rule are
    re-applied, and what survives must not start or end on punctuation,
    a bracket fragment, or a connector."""
    sent = (
        'Google\'s launch post announced "a new, open protocol called '
        'Agent2Agent (A2A), with support and contributions from more than '
        '50 technology partners" in April 2025'
    )
    label = _stat_label(sent, "50 technology partners")
    assert label == "support and contributions", label
    words = label.split()
    assert label[0] not in "([,;:.!?\"'", label
    assert label[-1] not in "([,;:.!?\"'", label
    assert _edge_word(words[0]) not in CONNECTOR_WORDS, label
    assert _edge_word(words[-1]) not in CONNECTOR_WORDS, label


def test_stat_dropped_when_no_clean_caption():
    """A sentence with no contiguous 3-8-word span beside the value
    yields no caption, and the stat is left out of the model rather
    than shown with a fragment."""
    sent = ("The largest meta-analysis, in JAMA Psychiatry in 2022, "
            "pooled 87 studies and 159,425 children [14].")
    assert _stat_label(sent, "87 studies") is None
    report = (
        "# Title\n\n"
        "## Summary\n\n" + sent + "\n\n"
        "## Key Findings\n\nSomething qualitative happened.\n\n"
        "## Bibliography\n\n[1] A (2024). Some publisher. J.\n"
    )
    model = build_model(report)
    values = [s["value"] for s in model["key_stats"]]
    assert "87 studies" not in values, values


def test_key_stats_skip_methodology_and_criteria():
    for path in (os.path.join(HERE, "fixtures", "valid_report.md"),
                 os.path.join(FORMATS_DIR, "discovery_catalog.md")):
        model = build(path)
        values = [s["value"] for s in model["key_stats"]]
        for banned in ("10 peer-reviewed sources", "3 independent sources", "300 stars"):
            assert banned not in values, (path, banned, values)


def test_bibliography_excluded_from_sections():
    for path, fmt in CASES:
        model = build(path)
        headings = {s["heading"].strip().lower() for s in model["sections"]}
        assert "bibliography" not in headings, path
        assert "sources" not in headings, path
        for section in model["sections"]:
            assert "bib-entry" not in section["html"], path
            assert "bibliography-content" not in section["html"], path
        ns = [s["n"] for s in model["sources"]]
        assert ns, path
        assert sorted(ns) == list(range(1, len(ns) + 1)), (path, ns)


def test_findings_extracted():
    rs = build(os.path.join(FORMATS_DIR, "research_summary.md"))
    assert len(rs["findings"]) >= 4, rs["findings"]
    assert rs["findings"][0]["refs"] == [1], rs["findings"][0]
    for f in rs["findings"]:
        assert f["headline"] and f["body"], f
        assert not re.match(r"(?i)^finding\s+\d+", f["headline"]), f["headline"]

    vr = build(os.path.join(HERE, "fixtures", "valid_report.md"))
    assert len(vr["findings"]) == 3, vr["findings"]
    assert vr["findings"][0]["refs"] == [1, 2, 3], vr["findings"][0]

    dc = build(os.path.join(FORMATS_DIR, "discovery_catalog.md"))
    assert len(dc["findings"]) >= 3, dc["findings"]


def test_contested_facets_from_manifest():
    with open(os.path.join(CONTESTED_DIR, "manifest_with_facets.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    model = build(os.path.join(CONTESTED_DIR, "report_with_perspectives.md"), manifest)
    assert len(model["contested_facets"]) == 2, model["contested_facets"]
    for facet in model["contested_facets"]:
        assert facet["facet"], facet
        assert len(facet["sides"]) >= 2, facet
        for side in facet["sides"]:
            assert side["label"], facet
            assert side["summary"], facet
    no_manifest = build(os.path.join(CONTESTED_DIR, "report_with_perspectives.md"))
    assert no_manifest["contested_facets"] == []


def test_facet_matching_survives_heading_rewording():
    """A manifest facet worded 'Alpha vs. beta: ...' must pair with a
    subsection headed 'Alpha versus beta' (vs-forms normalized, token
    overlap), carry the subsection's converted html, and extract one side
    per house-style paragraph — the substring match dropped this content
    and the sentence scan put both sides in one paragraph."""
    with open(os.path.join(RENDER_DIR, "facet_match_manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    model = build(os.path.join(RENDER_DIR, "facet_match_report.md"), manifest)
    assert not validate_model(model)
    assert len(model["contested_facets"]) == 1, model["contested_facets"]
    facet = model["contested_facets"][0]
    assert facet["html"], facet
    for needle in ("heavier alpha exposure tracks more beta problems",
                   "vanishes under controls for household factors"):
        assert needle in facet["html"], (needle, facet["html"])
    # one side per paragraph, 'X case' labels, each summary from its own paragraph
    sides = facet["sides"]
    assert len(sides) == 2, sides
    assert [s["label"] for s in sides] == ["Alpha-causation case", "Confounded-record case"], sides
    para1_only = "consistent direction across instruments"
    para2_only = "household factors and reverse causation"
    assert para1_only in sides[0]["summary"] and para2_only not in sides[0]["summary"], sides
    assert para2_only in sides[1]["summary"] and para1_only not in sides[1]["summary"], sides
    for side in sides:
        assert side["summary"], side


def test_facet_positional_fallback_when_counts_agree():
    """No token overlap, but facet count equals subsection count: the facet
    still matches positionally and carries the subsection's html."""
    report = (
        "# T\n\n"
        "## Perspectives\n\n"
        "### One completely different label\n\n"
        "The strongest case for x harm assembles the cohorts [1]. "
        "The strongest case for y null assembles the reanalyses [2].\n\n"
        "## Bibliography\n\n[1] A (2024). S1. J.\n[2] B (2023). S2. J.\n"
    )
    model = build_model(report, {"contested_facets": ["Speed of light: is it constant?"]})
    facet = model["contested_facets"][0]
    assert facet["html"], facet
    assert len(facet["sides"]) >= 2, facet


def test_sections_html_converted():
    for path, fmt in CASES:
        model = build(path)
        assert model["sections"], path
        for section in model["sections"]:
            assert section["level"] in (2, 3), (path, section)
            assert "<" in section["html"], (path, section["heading"])


if __name__ == "__main__":
    test_model_builds_for_every_fixture()
    test_format_precedence()
    test_date_from_manifest()
    test_each_model_passes_schema()
    test_key_stats_verbatim_and_bounded()
    test_stat_label_handles_quote_opened_before_value()
    test_stat_captions_are_contiguous_source_phrases()
    test_stat_label_not_spliced_across_value()
    test_stat_label_strips_edge_punctuation_and_parenthetical()
    test_stat_dropped_when_no_clean_caption()
    test_key_stats_skip_methodology_and_criteria()
    test_bibliography_excluded_from_sections()
    test_findings_extracted()
    test_contested_facets_from_manifest()
    test_facet_matching_survives_heading_rewording()
    test_facet_positional_fallback_when_counts_agree()
    test_sections_html_converted()
    print("all 17 render-model tests ran and passed")
