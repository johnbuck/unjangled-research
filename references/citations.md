# Citation Guide

## Basic Source Citation

Always cite sources you have registered in `sources.jsonl` using numbered citations. The number refers to the source's entry in the report's bibliography:

```markdown
The Q4 revenue increased by 23% quarter-over-quarter [4].
```

The number's bibliography entry carries the source's registered title and `raw_url`. Never paste raw URLs into prose.

## Evidence Backing

Every load-bearing statement — numbers, quotes, contested claims, anything a reader might challenge — must have a backing row in this run's `evidence.jsonl`. The row holds the exact quote and its locator. The report prose shows only the `[N]` citation; evidence IDs never appear in reader-facing text:

```markdown
The Q4 revenue increased by 23% quarter-over-quarter [4].
```

An evidence row must exist for the quoted figure; `verify_citations_v2.py` re-fetches the source and matches the quote against the visible page text (tags stripped, entities decoded, whitespace and quote characters normalised).

`evidence_store.py add` requires an `evidence_type` — one of `direct_quote`, `paraphrase`, `data_point`, `figure_reference`, `methodology` — and rejects the row (exit 1, JSON error on stderr) on a missing or unknown value, or on a `source_id` that is not registered in the run's `sources.jsonl`. Only `direct_quote` rows are quote-matched against the page, so label paraphrases as `paraphrase`.

## Inline Citations

Cite immediately after referenced information:

```markdown
The Q4 revenue increased by 23% quarter-over-quarter [4].
```

## Multiple Sources

When information comes from multiple sources, keep it to 1-2 per sentence and batch the rest at paragraph level:

```markdown
Customer satisfaction has improved across all metrics [2], with support workloads flat over the same period [5].
```

## Grouping

Group citations where adjacent claims share a source. **Over-citing** (every sentence, chains of 3+) and **under-citing** (no attribution) are both failures; the right balance is one or two citations per supported statement:

```markdown
The revenue increased, costs decreased, and margin improved [4].
```

The readability gate fails reports whose mean citation density exceeds 1.6 refs/sentence — see `reference/quality-gates.md`.

## Section-Level Citations

For longer sections derived from one source:

```markdown
### Engineering Priorities

According to the engineering roadmap [7]:

- Focus on API scalability
- Improve developer experience
- Migrate to microservices architecture
```

## Bibliography Section

Every report ends with a `## Bibliography` section listing every registered source the report actually cites. Use numbered entries — one per line, in first-citation order:

```markdown
## Bibliography
[1] Author/Org (2025). "Strategic Plan". https://example.com/strategic-plan
[2] Market Analysis Team (2024). "Market Analysis Report". https://example.com/market-analysis
[3] Competitor Research Group (2025). "Q3 Competitive Review". https://example.com/competitor-q3
```

Entry rules:

- An entry line starts with `[N]`, `- [N]` or `* [N]` (bare `[N]` lines preferred); one entry per line
- Numbering runs 1..N with no gaps; `validate_report.py` fails a bibliography with a gap
- Every entry is cited in the body: `validate_report.py` fails a report whose bibliography holds an entry nothing cites
- Entries are in first-citation order. The gates do not check the order; the numbering commands produce it. After `extract_claims.py extract` and `verify_claim_support.py link` have run on the current report, `python3 scripts/citation_manager.py renumber-report --dir [folder]` rewrites the report's `[N]` markers and regenerates its bibliography in first-citation order in one step. It reads `[folder]/report.md`; pass `--report [path]` for another file. The full sequence is in the gate chain linked below
- `python3 scripts/citation_manager.py export-bibliography --dir [folder] --style markdown` prints the same entries to stdout in the export format `[N] Author (Year). "Title". URL`. The author segment is omitted when the source row has no `authors`. The year is the source row's `year` field, `(n.d.)` when it is empty; `published_at` does not feed it, so pass `year` to `register-source` as well. A trailing period is stripped from the title, and the URL is bare
- The numbering state is the run's `display_numbers.json`, a flat `{source_id: display_number}` map. `assign-display-numbers` saves it in registration order (provisional), or in first-citation order with `--cited-order`; `renumber-report` saves the final cited-order map. `verify_claim_support.py link` resolves each `[N]` through it

**Gate wiring:** `python3 scripts/validate_report.py --report [path] --format [format] --manifest [run_dir]/run_manifest.json` fails the report (exit 1) when an inline `[N]` has no bibliography entry, a bibliography entry is cited nowhere in the body, or bibliography numbering has gaps; word targets and source floors are warnings that still pass. Always pass `--manifest`: without it the contested-facets gate is skipped.

**Never put evidence-row IDs (`[E:...]`) in report prose.** Evidence IDs live only in `evidence.jsonl` and the run manifest — the readability gate flags long hex tokens in reader-facing text as pipeline-internals leakage.

## Quoting Content

When quoting directly from a source, cite by number in the sentence:

```markdown
The product team noted: "We need to prioritize mobile experience improvements" [3].
```

For block quotes:

```markdown
> We need to prioritize mobile experience improvements to meet our Q4 goals. This includes performance optimization and UI refresh.
>
> — Product Meeting Notes, Oct 2025 [3]
```

Direct quotes must exist as evidence rows: the quote in the report matches the `quote` field of a row in `evidence.jsonl` (re-fetched and matched against the visible page text by `verify_citations_v2.py`); the row holds the evidence ID, not the prose.

## Data Citations

When presenting data, cite the source by number on a "Source:" line:

```markdown
| Metric | Q3 | Q4 | Change |
|--------|----|----|--------|
| Revenue | $2.3M | $2.8M | +21.7% |
| Users | 12.4K | 15.1K | +21.8% |

Source: Financial Dashboard [6]
```

## Freshness Dating

Publication date is part of the truth. The source row's `published_at` carries it — ISO 8601 extended form at whatever precision the source page gives: `YYYY`, `YYYY-MM`, `YYYY-MM-DD`, or a full date-time (`YYYY-MM-DDTHH:MM[:SS[.fff]][Z|+HH:MM]`). Never pad an unknown month, day or time — the source schema accepts only these forms, `register-source` stores the value verbatim, and `source_evaluator.py --dir` records a `published_at` outside them as a row defect (exit 1). Stale numbers carry their publication date in the report:

```markdown
The original API design, published January 2024 [8], has been superseded by the new architecture [9].
```

Never guess a date from memory — take it from the source page or leave `published_at` null and say the date is unknown.

## Cross-References

Link to related prior runs by their report path when the current findings build on them:

```markdown
## Related Research

This research builds on previous findings:
- [Market Analysis - Q2 2025](../market-analysis-q2-20250601/market-analysis-q2.md)

For implementation details, see:
- [Technical Implementation Guide](../technical-implementation-20251012/technical-implementation.md)
```

Evidence from a prior run is never cited directly: re-register the source and re-capture the quote into the current run's stores first (consult freely, re-capture to cite).

## Citation Validation (final pass, local and structural)

Before the report counts as done, check — locally, against run-folder files only, no network:

- Every key claim has a numbered citation
- Every `[N]` resolves to a bibliography entry backed by a registered source in `sources.jsonl`
- Every load-bearing claim has a row in `evidence.jsonl`
- Bibliography includes all cited sources and nothing uncited
- Outdated sources are noted as such (freshness dating)
- Direct quotes are clearly marked and match their evidence rows
- Data sources are attributed

The gates that enforce these rules run in the order given in `reference/quality-gates.md#phase-8-gate-chain`.

## Citation Style

The style is fixed, not a per-run choice: numbered `[N]` citations after the supported statement, evidence rows (not inline IDs) carrying the proof, grouped citations at 1-2 per sentence, and a trailing numbered Bibliography section. Every citation a reader follows must land on a run-folder artifact using only run-folder files.

## Registry Citations (discovery reports)

Discovery-catalog reports cite registries and curated lists as sources. Rules:

- Every popularity number in prose or matrix carries `value (source, as-of date)` — e.g. `340 stars (GitHub, 2026-10-06)`, `12k downloads/30d (Hugging Face, 2026-10-06)`
- A number with no source and date is "unverified" and the candidate caps at Watch
- Registry pages and curated-list sections get numbered bibliography entries in the same export form as any other source, with the retrieval date in the title: `[7] GitHub (2026). "pgbouncer repository metrics, retrieved 2026-10-06". https://github.com/pgbouncer/pgbouncer`
- Excluded evidence classes (G2, AlternativeTo, affiliate listicles, AI-generated comparison sites) never appear in the bibliography — name them under Sources Consulted as rejected
- The same numbers land in `projects.jsonl`; the matrix renders from it (see schemas/discovery_project.schema.json)
