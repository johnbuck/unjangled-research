# Unjangled Research

A research skill for Claude Code and other agent harnesses that read
`SKILL.md` skills. It produces citation-backed reports in a format matched to
the question, with an evidence store on disk, two independent citation
verifiers, and a readability gate every report must pass.

**This is a fork.** It started as a hard fork of
[199-biotechnologies/claude-deep-research-skill](https://github.com/199-biotechnologies/claude-deep-research-skill)
at commit `f2f2c0f`. The pipeline, most scripts and the HTML/PDF output come
from upstream. The format templates and citation guide are adapted from
OpenAI's Notion research-documentation skill (MIT, Notion Labs). See
[ATTRIBUTION.md](ATTRIBUTION.md) for exactly what came from where and what
changed.

## What the fork adds

- **Format selection.** A decision tree picks one of five report shapes
  (quick brief, research summary, comparison, comprehensive report, discovery
  catalog) and the matching template in `references/report-templates/`.
  `scripts/validate_report.py` checks the mandatory sections for each format.
- **Second citation verifier.** `scripts/verify_citations_v2.py` re-fetches
  every cited source and byte-checks direct quotes, independent of the
  upstream verifier.
- **Claim linkage that fails when it should.** `verify_claim_support.py link`
  ties extracted claims to evidence; the upstream version exited 0 with no
  claims linked.
- **Readability gate.** `scripts/readability_check.py` fails reports with
  dense citation chains, long sentences, a high reading grade, or pipeline
  internals leaking into the text. Thresholds were calibrated against
  blind-judged reports.
- **Contested topics.** `references/contested-topics.md` requires every facet
  of a contested question to be listed and steelmanned, and a verdict only when
  the user asks for one. `validate_report.py --manifest` enforces facet
  coverage.
- **Source access and search craft.** `references/source-access.md` and
  `references/search-techniques.md` cover blocked sources, query iteration,
  and terminology sweeps.

## Install

```bash
git clone https://github.com/johnbuck/unjangled-research.git ~/.claude/skills/unjangled-research
```

For other harnesses, clone into whatever directory they load skills from.

Python 3.10+ standard library is all the core scripts need. The readability
gate's dependencies (textstat, pyphen, CMU Pronouncing Dictionary) are
vendored in `vendor/`. Optional extras are listed in `requirements.txt`.

## Use

Ask for research in plain language; the skill triggers on phrases like
"deep research", "research report", "compare X vs Y" or "state of the art".

```
research the evidence on four-day work weeks and productivity
compare PostgreSQL vs Supabase for a small team, comparison format
```

Reports are written to `~/Documents/[Topic]_Research_[Date]/` as Markdown,
HTML and (with WeasyPrint) PDF.

## Tests

Run from this directory:

```bash
for t in tests/test_*.py; do python3 "$t" || echo "FAILED: $t"; done
```

No network access or API keys are needed.

## How it was evaluated

The evaluation is small and should be read that way: **one DeepResearch
Bench task (task 73), one agent run per variant, two LLM judges** (Claude
Opus and Claude Sonnet) scoring blind, anonymized A/B pairs on the RACE
rubric. The same task was used to calibrate the readability thresholds and
to validate them, so the readability result is not an independent test.

| Comparison (two-judge average) | Fork | Upstream |
|---|---|---|
| Round 1: comprehensiveness | 86.5 | 75.0 |
| Round 1: readability | 72.0 | 83.0 |
| Round 2 (after readability gate): comprehensiveness | 86.0 | 79.0 |
| Round 2: readability | 84.5 | 76.0 |
| Round 2: overall | 83.5 | 79.5 |

The judges' scale for the same upstream report drifted by 6-8 points
between rounds, so cross-round numbers are less reliable than within-round
gaps. Treat these results as a promising signal, not a benchmark claim.

## Background

Before building this, we read the ten most-installed public research skills
end to end. [docs/survey.md](docs/survey.md) has the ranking and what we
took from each.

## License

MIT, see [LICENSE](LICENSE). Upstream and third-party licenses are listed in
[ATTRIBUTION.md](ATTRIBUTION.md) and [vendor/README.md](vendor/README.md).
