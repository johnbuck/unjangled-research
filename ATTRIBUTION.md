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
- `scripts/research_engine.py`, `scripts/evidence_store.py`,
  `scripts/citation_manager.py`: verbatim.
- `scripts/extract_claims.py`: bibliography entries are no longer parsed as
  claims.
- `scripts/verify_claim_support.py`: `link` subcommand added (upstream
  passed with 0% claim linkage).
- `scripts/source_evaluator.py`: education, humanities and social-science
  domains added, plus DOI-to-publisher resolution.
- `scripts/md_to_html.py`: content after the bibliography is preserved
  (upstream truncated it).
- `scripts/validate_report.py`: format-aware section checks, per-format
  source floors, bibliography aliases, and the `--manifest` facet-coverage
  gate added.
- `scripts/verify_citations.py`, `scripts/verify_html.py`: verbatim.
- `tests/test_citation_manager.py`, `tests/test_evidence_store.py`,
  `tests/test_extract_claims.py`, `tests/test_verify_claim_support.py` and
  their fixtures, `requirements.txt`, `.gitignore`: from upstream;
  `requirements.txt` and `.gitignore` edited for this fork.
- `schemas/` (except `discovery_project.schema.json`), `templates/`,
  `reference/`: from upstream. `run_manifest.schema.json`,
  `templates/report_template.md` and the `reference/` docs were updated for
  the readability gate, format selection, numbered citations and the
  renamed skill.

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

## Original work

- `scripts/verify_citations_v2.py`: second network citation checker that
  re-fetches sources and byte-verifies direct quotes.
- `scripts/readability_check.py`, `scripts/readability_window_check.py`:
  readability gate and its threshold-transfer check.
- `references/report-templates/discovery-catalog.md`,
  `references/discovery-criteria.md`, `schemas/discovery_project.schema.json`.
- `references/contested-topics.md`, `references/source-access.md`,
  `references/search-techniques.md`: method written for this skill, partly
  re-authored from an internal web-research skill by the same author.
- `tests/test_contested_facets.py`, `tests/test_formats.py`,
  `tests/test_readability_check.py` and their fixtures.

## Vendored libraries

textstat (MIT), Pyphen (GPL-2.0+ / LGPL-2.1+ / MPL-1.1) and the CMU
Pronouncing Dictionary (BSD-style). Versions, license files and local
changes are listed in [vendor/README.md](vendor/README.md).

## License

Original additions are MIT, see [LICENSE](LICENSE). Inherited and adapted
material stays under its upstream terms above.
