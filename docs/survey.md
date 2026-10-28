# Survey: ten public research skills

Before building Unjangled Research, we read the ten most-installed general
research skills on the skills.sh registry end to end. This page records the
ranking and what each one is good for. The skills themselves are not copied
here; follow the links.

Install and star counts are a snapshot from 2026-09-23 and have moved since.
Stars are for the whole source repository, not the individual skill.

| # | Skill | Installs | Stars | One-liner |
|---|-------|----------|-------|-----------|
| 01 | [mattpocock research](https://github.com/mattpocock/skills) | 548.0K | 267,952 | Minimalist: background agent, primary sources only, cited markdown out |
| 02 | [RigorPilot ai-research-explore / -reproduction](https://github.com/lllllllama/RigorPilot-Skills) | 311.3K | 495 | Deep-learning research rigor and reproducibility |
| 03 | [firecrawl-deep-research](https://github.com/firecrawl/firecrawl-workflows) | 34.6K | 167 | Firecrawl API crawl plus synthesis (vendor pipeline) |
| 04 | [tavily-research](https://github.com/tavily-ai/skills) | 19.4K | 486 | tvly CLI deep research with cited reports (vendor pipeline, best-written) |
| 05 | [warp research](https://github.com/warpdotdev/common-skills) | 19.2K | 585 | Subagent delegation to keep reading noise out of your context |
| 06 | [parallel-deep-research](https://github.com/parallel-web/parallel-agent-skills) | 14.7K | 76 | parallel-cli tiered research, async polling, context chaining |
| 07 | [199-bio deep-research](https://github.com/199-biotechnologies/claude-deep-research-skill) | 9.9K | 1,116 | 8-phase pipeline, persistent evidence store, JSON schemas |
| 08 | [anthropic research-synthesis](https://github.com/anthropics/knowledge-work-plugins) | 3.7K | — | User-research synthesis (interviews and surveys to themes) |
| 09 | [openai notion-research-documentation](https://github.com/openai/skills) | 3.1K | 27,557 | Research to structured docs; four output templates plus a citation guide |
| 10 | [lingzhi227 deep-research suite](https://github.com/lingzhi227/agent-research-skills) | 1.7K | 355 | Six-phase academic literature review with phase gates |

## Notes

- **Security audits:** on 2026-09-23, the Snyk audit shown on skills.sh
  flagged WARN for 7 of the 10 skills listed here, and the Socket audit
  flagged WARN for both RigorPilot skills. We did not assess these warnings
  independently. Review any skill's scripts before installing it.
- **10 lingzhi227:** the repository has no license file, so its contents are
  all rights reserved by default.

## What we took forward

- **07** is the base of Unjangled Research: its pipeline, evidence store and
  verification scripts. In a blind two-judge comparison on one benchmark
  task, it beat our first, from-scratch skill by a wide margin on
  comprehensiveness and depth.
- **09**'s format-selection guide and report templates became the format
  layer, adapted to plain Markdown.

See [ATTRIBUTION.md](../ATTRIBUTION.md) for the exact lineage.
