# Attribution

## Upstream: 199-biotechnologies/claude-deep-research-skill

This skill is a hard fork of
[199-biotechnologies/claude-deep-research-skill](https://github.com/199-biotechnologies/claude-deep-research-skill)
at commit `f2f2c0f`. Upstream has no LICENSE file or copyright notice; its
[README at that commit](https://github.com/199-biotechnologies/claude-deep-research-skill/blob/f2f2c0f/README.md)
states "MIT - modify as needed for your workflow." This fork relies on that
grant and credits the upstream authors, 199 Biotechnologies.

Inherited components, with modifications noted:

- `SKILL.md`: pipeline structure from upstream. Renamed from `deep-research`
  to `unjangled-research`; search fallback, format selection, readability
  gate, scope contract and contested-topic rules added.
- `scripts/research_engine.py`: modified — rewritten as the run's state
  scaffold for the orchestrating agent: it prints the phase instruction
  templates the skill's docs give the chosen mode and persists one resumable
  `research_state.json` in the run folder (phase cursor including outline
  refinement, working `--resume`); it never searches or writes reports.
- `scripts/evidence_store.py`: modified — `add` rejects unknown evidence
  types and source IDs missing from `sources.jsonl` (JSON error on stderr,
  exit 1, nothing appended).
- `scripts/citation_manager.py`: modified — display numbers are assigned in
  citation order (`assign-display-numbers --cited-order`),
  `renumber-report` rewrites markers and bibliography together, and
  `export-bibliography` writes a markdown bibliography.
- `scripts/extract_claims.py`: bibliography entries are no longer parsed as
  claims; the split now comes from the shared rule in
  `scripts/bibliography.py`.
- `scripts/verify_claim_support.py`: `link` subcommand and `--strict`
  (exit 1 on any unsupported factual claim) added; upstream passed with 0%
  claim linkage.
- `scripts/source_evaluator.py`: education, humanities and social-science
  domains added, plus DOI-to-publisher resolution; it now has a CLI with
  JSON output and matches source domains by suffix.
- `scripts/md_to_html.py`: modified — content after the bibliography is
  preserved (upstream truncated it); all report text is now HTML-escaped
  before the markdown rules run (only converter-generated markup is live),
  the bibliography boundary and entries come from the shared rule in
  `scripts/bibliography.py`, https links render as anchors and every other
  link target as plain `text (URL)`, and table data rows survive (strict
  separator rule, trailing pipe optional).
- `scripts/validate_report.py`: format-aware section checks, per-format
  source floors and the `--manifest` facet-coverage gate added; the
  bibliography is found through the shared rule in `scripts/bibliography.py`
  (heading `## Bibliography` or `## Sources`), and an entry the body never
  cites is an error.
- `scripts/verify_citations.py`: modified — parses the bibliography through
  the shared rule in `scripts/bibliography.py` (every entry form) and fails
  on bad results by default; `--strict` also fails entries verified by
  neither DOI nor URL.
- `scripts/verify_html.py`: modified — still the upstream pipeline's
  post-render completeness gate (the 199-bio pipeline ran it after the HTML
  template fill), rewritten for the themed renderer: the delivered HTML is
  checked against the markdown report through the shared rule in
  `scripts/bibliography.py`, and every lost heading, body line, link URL,
  table row, citation marker and bibliography entry or note is named (exit 0
  pass, exit 1 fail).
- `tests/test_citation_manager.py`, `tests/test_evidence_store.py`,
  `tests/test_extract_claims.py`, `tests/test_verify_claim_support.py` and
  their fixtures, `requirements.txt`, `.gitignore`: from upstream;
  `requirements.txt` and `.gitignore` edited for this fork, and the four
  test files extended for the changes above.
- `schemas/` (except `discovery_project.schema.json`,
  `render_model.schema.json` and `deck_spec.schema.json`), `templates/`,
  `reference/` (except `slide-decks.md`): from upstream. `run_manifest.schema.json` (manifest
  `format` and `qa_notes` fields), `source.schema.json` (`published_at`),
  `templates/report_template.md` and the `reference/` docs were updated for
  the readability gate, format selection, numbered citations and the
  renamed skill.
- `templates/mckinsey_report_template.html`: inherited from upstream and
  used for the HTML output until this fork replaced it with the themed
  renderer (`scripts/render_report.py` driven by `themes/<name>/theme.json`);
  the template file has been removed.

## Adapted: OpenAI Notion research-documentation skill

- **Source:** https://github.com/openai/skills (Notion research
  documentation skill), Copyright 2025 Notion Labs, Inc., MIT-style license
  reproduced below.
- **Adapted files:** `references/format-selection.md` (from
  `reference/format-selection-guide.md`), `references/citations.md` (from
  `reference/citations.md`), and the comparison, comprehensive-report,
  quick-brief and research-summary templates in
  `references/report-templates/` (from the four `*-template.md` files, with
  the matching `*-format.md` guidance merged in at the top).
- **Changes:** Notion page, database and mention syntax replaced by plain
  Markdown links and numbered citations; Notion MCP workflow steps removed;
  a fifth format (discovery catalog) added to the decision tree; mandatory
  sections and word targets added per format.

> Copyright 2025 Notion Labs, Inc.
>
> Permission is hereby granted, free of charge, to any person obtaining a
> copy of this software and associated documentation files (the
> "Software"), to deal in the Software without restriction, including
> without limitation the rights to use, copy, modify, merge, publish,
> distribute, sublicense, and/or sell copies of the Software, and to permit
> persons to whom the Software is furnished to do so, subject to the
> following conditions:
>
> The above copyright notice and this permission notice shall be included
> in all copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
> OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
> MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN
> NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
> DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
> OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE
> USE OR OTHER DEALINGS IN THE SOFTWARE.

## Adopted engine: themed renderer

The renderer stack rests on a page/deck HTML engine adopted from a
debranded internal (non-public) HTML brand-reporting skill by the same
author. The brand name, logo, palette, product-specific layouts and
product-specific code were removed, CSS classes were renamed, and all
colors and fonts now come from theme files (`themes/<name>/theme.json`).
Adopted and reworked from that engine: `scripts/render_lib.py` (page and
deck builders), `scripts/motif.py` (motif generator),
`assets/render/page.css`, `assets/render/deck.css`,
`assets/render/deck.js` and `assets/render/research.css`, and
`scripts/check_theme.py` (descended from the engine's brand-QA check, now a
theme-driven QA gate), and `reference/slide-decks.md` (the deck authoring
guide, a debranded successor to that skill's workflow and generic-layouts
reference). Written for this fork on top of the adopted engine:
`scripts/render_report.py` (themed self-contained HTML report),
`scripts/build_render_model.py` (report/deck render model),
`scripts/render_deck.py` and `scripts/slide_plan.py` (research slide
decks), `scripts/deck_spec.py`, `schemas/deck_spec.schema.json` and
`assets/render/deck_layouts.css` (slide-list deck authoring over the
engine's generic layouts), `schemas/render_model.schema.json`, `scripts/render_pptx.py` and
`scripts/pptx_lib.py` (standard-library PowerPoint writer),
`scripts/theme.py` (theme contract), the themes under `themes/`, and the
renderer tests `tests/test_render_lib.py`, `tests/test_render_report.py`,
`tests/test_render_model.py`, `tests/test_render_deck.py`,
`tests/test_slide_plan.py`, `tests/test_deck_spec.py`,
`tests/test_render_pptx.py`, `tests/test_pptx_lib.py`,
`tests/test_theme.py` and `tests/test_check_theme.py`.

## Fonts

The neutral theme embeds the Lato typeface. Lato is Copyright 2010-2014 by
tyPoland Lukasz Dziedzic (team@latofonts.com) and is licensed under the
SIL Open Font License, Version 1.1. The license is carried alongside the
theme at [themes/neutral/LICENSE-OFL.txt](themes/neutral/LICENSE-OFL.txt),
and the font is embedded as WOFF in `themes/neutral/fonts.css`.

## Original work

- `scripts/verify_citations_v2.py`: second network citation checker that
  re-fetches sources and matches direct quotes on the fetched page's
  visible text (script, style, template and comment code dropped, tags
  stripped, entities decoded, whitespace and quote characters normalised,
  word boundaries, case-sensitive), failing when nothing was checked.
- `scripts/readability_check.py`, `scripts/readability_window_check.py`:
  readability gate (shared bibliography rule; each bullet counts as its
  own sentence) and its threshold-transfer check.
- `scripts/bibliography.py`: the shared bibliography rule used by the gate
  scripts — heading `## Bibliography` or `## Sources`, `[N]`, `- [N]` and
  `* [N]` entries, inline citation extraction with code spans and fenced
  blocks excluded.
- The fork-original renderer files listed under "Adopted engine" above.
- `references/report-templates/discovery-catalog.md`,
  `references/discovery-criteria.md`, `schemas/discovery_project.schema.json`.
- `references/contested-topics.md`, `references/source-access.md`,
  `references/search-techniques.md`: method written for this skill, partly
  re-authored from an internal web-research skill by the same author.
- `tests/test_contested_facets.py`, `tests/test_formats.py`,
  `tests/test_readability_check.py` and their fixtures; the gate tests
  `tests/test_bibliography.py`, `tests/test_numbering.py`,
  `tests/test_readability_window_check.py`, `tests/test_schemas.py`,
  `tests/test_source_evaluator.py`, `tests/test_validate_report.py`,
  `tests/test_verify_citations.py`, `tests/test_verify_citations_v2.py`
  and `tests/schema_validator.py`; `tests/test_research_engine.py` from
  this initiative's research-engine repair; the documentation-contract
  tests `tests/test_*_docs.py` and `tests/test_attribution.py`.

## Vendored libraries

textstat (MIT), Pyphen (GPL-2.0+ / LGPL-2.1+ / MPL-1.1) and the CMU
Pronouncing Dictionary (BSD-style). Versions, license files and local
changes are listed in [vendor/README.md](vendor/README.md).

## License

Original additions are MIT, see [LICENSE](LICENSE). Inherited and adapted
material stays under its upstream terms above.
