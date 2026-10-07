# Discovery Catalog Template

## Format guidance

**Use for:** "which tool/model/library should I use for X", "find the most
popular projects for Y", tool/model discovery questions of any kind.

**Not for:** research questions about a topic (use research-summary or
comprehensive-report), or head-to-head evaluation of two already-chosen
options (use comparison).

**Sizing:** 800-1,500 words. Source floor: 8 (registries and curated lists
count as sources).

**Non-negotiable:** every tier decision follows the criteria table
mechanically. Every number carries value + source + as-of date. If a number
cannot be sourced, the candidate caps at Watch. Relics and wrong-category
candidates are named and rejected in one line each — never silently omitted.

## Skeleton

```markdown
# [Question restated as a catalog title]

## Summary

[The tiered shortlist. Adopt candidates with one-line verdicts; Evaluate
with the missing signal named; Watch with the reason; Ruled Out in one
shared line each. 3-6 sentences prose, no bullets.]

## Selection Criteria

[VERBATIM FREEZE: open references/../discovery-criteria.md in the spec
companion — the maintainer's copy at
_bmad-output/spec-research-skill-fork/discovery-criteria.md is canonical;
the shipped template mirror is references/discovery-criteria.md — and copy
the maintenance table, registry floors table, tier rule, and any model
addenda INTO THIS SECTION unchanged. This is the per-run freeze: audits
recompute tiers against THIS table. Record any override below it with a
reason.]

## Comparison Matrix

| Candidate | Registry | Popularity (source, date) | Last activity | License | Status | Tier |
|---|---|---|---|---|---|---|
[One row per candidate. Popularity cell: "340 stars (GitHub, 2026-10-06)".
Blank cells are forbidden — unknown = "unverified" and caps at Watch.]

## Model Addenda

[ONLY when the question concerns models: task-relevant benchmark table
(position, leaderboard, date), VRAM requirement vs target host as numbers,
quant availability, license class. Omit this section entirely for software
questions.]

## Project Dossiers

### [Candidate name]

[2-4 sentences: what it is, popularity evidence with numbers, maintenance
status, and the honest downside. Adopt candidates must cite two independent
registries.]

## Sources Consulted

[Which curated lists were enumerated first (tool-catalog categories,
awesome-list sections), which registries were checked, and what was
rejected as evidence (listicles, affiliate sites). This is the audit trail
proving curated-list-first ran.]

## Bibliography
[1] ... numbered entries per references/citations.md
```

## Rendering notes

- Freshness banner directly under the title: "Metrics current as of
  [date]; discovery results rot."
- The comparison matrix is the load-bearing section: every cell sourced or
  marked unverified.
- projects.jsonl carries the same numbers as the matrix — render the matrix
  from it, never the reverse.
