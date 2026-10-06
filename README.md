# unjangled-research

A research skill for deep-research agents: an 8-phase pipeline with evidence persistence, dual citation verifiers, and format-selection report templates.

**Validated at comprehensiveness 86.5 (blind RACE scoring)** — 48 sources on a single-task benchmark, beating its upstream baseline (75.0) by 11.5 points with the same model on the same harness.

## What it is

A [SKILL.md](SKILL.md)-format skill that teaches an agent to research a question against primary sources and produce a citation-tracked report. The agent runs eight phases — SCOPE, PLAN, RETRIEVE, TRIANGULATE, SYNTHESIZE, CRITIQUE, REFINE, PACKAGE — persisting every quote to an append-only evidence store before writing the sentence it supports.

## Key features

- **8-phase pipeline** (inherited from [199-biotechnologies/claude-deep-research-skill](https://github.com/199-biotechnologies/claude-deep-research-skill) at `f2f2c0f`, MIT license)
- **Evidence store**: append-only JSONL with sha256 content-hash IDs; every quote persisted before the sentence it supports
- **Claim-evidence linkage**: `verify_claim_support.py link` resolves citation numbers to source IDs and matches claims to evidence rows by token overlap
- **Dual citation verifiers**: 07's own `verify_citations.py` (report-level) + `verify_citations_v2.py` (independent second network check, re-fetches sources and byte-verifies quotes)
- **Source evaluator** covering academic, government, education, humanities, and social-science domains; resolves DOIs to publisher domains for scoring
- **Format-selection templates**: decision tree (`references/format-selection.md`) picks the right report template (comparison, comprehensive, quick-brief, research-summary) based on the question type
- **Raw document archiving**: every fetched page/PDF archived to `raw/` for reproducibility
- **Machine-ingestible artifacts**: structured JSONL stores with stable schemas — designed for future knowledge-graph integration

## Installation

Copy this directory into your agent's skills folder. No pip dependencies beyond stdlib Python 3.10+. For HTML/PDF output, `uv run --with weasyprint` works.

```
cp -r unjangled-research/ <your-agent>/skills/unjangled-research/
```

## Scripts

| Script | Purpose |
|--------|---------|
| `research_engine.py` | Phase-prompt engine for deep-mode |
| `evidence_store.py` | Append-only JSONL store for quotes |
| `citation_manager.py` | Source registration, display numbers, bibliography export |
| `extract_claims.py` | Extract claims from report text |
| `verify_claim_support.py` | Link claims to evidence (`link`) and verify support (`verify`) |
| `validate_report.py` | 9-check report validation |
| `verify_citations.py` | Network citation verification (upstream) |
| `verify_citations_v2.py` | Independent second network citation checker |
| `source_evaluator.py` | Credibility scoring with domain awareness |
| `md_to_html.py` | Markdown to styled HTML |
| `verify_html.py` | HTML output verification |

## Validation results

Blind RACE scoring on DeepResearch Bench task 73 (holistic elementary English education), run on a Hermes/GLM-5.3 agent:

| Dimension | This skill | Upstream 07 |
|-----------|-----------|-------------|
| Comprehensiveness | **86.5** | 75.0 |
| Instruction following | **79.5** | 80.5 |
| Depth | 78.5 | 82.0 |
| Readability | 72.0 | 83.0 |
| **Overall** | **79.0** | 78.5 |

Judged by two independent cross-model agents (claude-opus, claude-sonnet), blind to which report was which.

## Provenance

Hard fork of [199-biotechnologies/claude-deep-research-skill](https://github.com/199-biotechnologies/claude-deep-research-skill) at commit `f2f2c0f` (MIT license). Bug fixes, template overlay, verifier sidecar, and domain-extended source evaluator are original work from the unjangled-research effort.

See [ATTRIBUTION.md](ATTRIBUTION.md) for detailed provenance.

## License

MIT (inherited from upstream).
