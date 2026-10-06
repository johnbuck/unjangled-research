# Attribution

## Upstream

This skill is a hard fork of [199-biotechnologies/claude-deep-research-skill](https://github.com/199-biotechnologies/claude-deep-research-skill) at commit `f2f2c0f`, MIT license.

Inherited components (vendored, with modifications noted):
- `SKILL.md` — 8-phase pipeline structure (name changed from "deep-research" to "research-fork"; search fallback section added)
- `scripts/research_engine.py`, `scripts/evidence_store.py`, `scripts/citation_manager.py`, `scripts/extract_claims.py` — vendored verbatim
- `scripts/verify_claim_support.py` — vendored with `link` subcommand added (original had phantom linking step: 246 claims at 0% linkage passing exit 0)
- `scripts/source_evaluator.py` — vendored with education/humanities/social-science domains added and DOI-to-publisher resolution (original was STEM/gov only)
- `scripts/md_to_html.py` — vendored with post-bibliography preservation fix (original truncated after bibliography)
- `scripts/validate_report.py`, `scripts/verify_citations.py`, `scripts/verify_html.py` — vendored verbatim
- `schemas/` — vendored verbatim
- `templates/`, `reference/`, `tests/` — vendored verbatim

## Original work (from the unjangled-research effort)

- `scripts/verify_citations_v2.py` — independent second network citation checker (re-fetches sources, byte-verifies direct quotes)
- `references/format-selection.md` — decision tree for report template selection
- `references/report-templates/` — four report templates (comparison, comprehensive-report, quick-brief, research-summary)
- `references/citations.md`, `references/search-techniques.md`, `references/source-access.md`, `references/contested-topics.md` — supporting reference documents

## License

MIT (inherited from upstream; original additions also MIT).
