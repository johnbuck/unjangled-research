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

An evidence row must exist for the quoted figure; `verify_citations_v2.py` byte-verifies it against the fetched source.

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

Every report ends with a `## Bibliography` section listing every registered source the report actually cites. Use numbered entries — one per line, in citation order:

```markdown
## Bibliography
[1] Author/Org (2025). Strategic Plan. https://example.com/strategic-plan
[2] Market Analysis Team (2024). Market Analysis Report. https://example.com/market-analysis
[3] Competitor Research Group (2025). Q3 Competitive Review. https://example.com/competitor-q3
```

A leading list marker (`- [1] ...`) is accepted, but bare `[N]` lines are preferred.

**Gate wiring:** `validate_report.py --format [format]` checks that every inline `[N]` resolves to a bibliography entry, numbering has no gaps, and the entry count clears the format's source floor. Removing the bibliography must leave no orphan inline citation, and vice versa: every inline `[N]` resolves to a registered source, every bibliography entry is cited inline.

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

Direct quotes must exist as evidence rows: the quote in the report matches the `quote` field of a row in `evidence.jsonl` (verified byte-level by `verify_citations_v2.py`); the row holds the evidence ID, not the prose.

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

Publication date is part of the truth. The source row's `published_at` carries it; stale numbers carry their publication date in the report:

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

The full gate chain (validate, readability, verify_citations, verify_citations_v2) is documented in `reference/quality-gates.md`.

## Citation Style

The style is fixed, not a per-run choice: numbered `[N]` citations after the supported statement, evidence rows (not inline IDs) carrying the proof, grouped citations at 1-2 per sentence, and a trailing numbered Bibliography section. Every citation a reader follows must land on a run-folder artifact using only run-folder files.
