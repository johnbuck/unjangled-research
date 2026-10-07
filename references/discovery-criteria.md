# Discovery criteria (CAP-8)

Deterministic criteria for the discovery-catalog format. Every rule is a
number or a checkable fact; "actively maintained" and "popular" are not
criteria. Thresholds are stated defaults: frozen per-run into the report's
Selection Criteria section, and any override is recorded with a reason.

## Universal maintenance gates (all platforms, evaluated first)

Derived from awesome-selfhosted-data's upstream convention (archived flag +
latest release + rolling 12-month commit history):

| Status | Definition (days since last commit or release) | Consequence |
|---|---|---|
| ACTIVE | ≤ 180 | eligible for any tier |
| FADING | 181–365 | eligible, flagged |
| DORMANT | 366–730 | cannot tier above Watch |
| ARCHIVED/DEAD | repo archived, or > 730 | Ruled Out, named in one line |

Hard disqualifiers: no license or license incompatible with the stated use;
registry-deprecated/yanked packages; ARCHIVED status. Unverifiable metrics
(no version, no date, unknown fields) cap the candidate at Watch.

## Registry floors (every value cited as `number (registry, date)`)

| Registry | Primary metric | Adopt floor | Corroboration |
|---|---|---|---|
| GitHub | stars | ≥ 300 (calibrated: p10–p25 band of curated catalog; junk line ~145) — 1,000+ earns a high-visibility flag, not a gate | contributors ≥ 5; forks |
| Hugging Face | downloads/30d | ≥ 1,000, OR task-benchmark top-quartile (benchmark counts as a popularity signal for models) | likes ≥ 500; model card complete |
| PyPI/npm/crates | downloads/month | ≥ 25,000 (weakest floor — no distribution data yet; recalibrate after first e2e) | dependents; last release ≤ 180d |
| Docker Hub | pulls | ≥ 1,000,000 (CI re-pulls inflate; excludes almost nothing) | verified publisher; last push ≤ 180d |
| Ollama | pulls | ≥ 100,000 | GGUF/quant variants |
| Repology | distros packaging | ≥ 2 distros | corroboration only |

Percentile rule: candidate set < 8 → absolute floors alone decide;
set ≥ 8 → a candidate qualifies at ≥ 70th percentile of the enumerated set
on its primary metric. The percentile is an ALTERNATIVE path, never an
additional requirement: a candidate above the floor is never demoted for
being below the percentile. Registry floors apply to the registries the
question's candidates actually live on (a floor for a registry nothing in
the question uses is dormant). Two-signal rule: Adopt requires
floor-or-percentile PLUS one corroborating signal from a different
registry.

## Tier decision rule (ordered)

1. **Ruled Out** — fails any hard gate, or fails both floor and percentile
2. **Watch** — passes maintenance + popularity but: single popularity
   source, or bus factor (contributors < 5, no org), or < 180 days since
   first stable release, or partially unverifiable metrics
3. **Evaluate** — passes all but one soft flag: issue-ratio > 0.5
   (open/(open+closed), GitHub), telemetry on by default without opt-out,
   resource footprint unknown
4. **Adopt** — ACTIVE + floor-or-percentile + two independent sources +
   bus factor clear + license clean + zero soft flags

Precedence (binding): where conditions from multiple tiers fire, the most
restrictive matching tier wins — with one model-specific exception:
**the 180-day age cap is waived to Adopt for models holding a
task-relevant benchmark top-quartile position AND two independent
signals** (anti-hype intent is preserved for unproven models; benchmark
evidence is the maturity signal). VRAM flags are fit-annotations, not soft
flags, when the model demonstrably fits the stated target at a standard
quantization — cite the GB numbers.

## Model-specific addenda (target = models)

- Benchmark gate: Adopt requires a position on ≥ 1 task-relevant leaderboard
  (LMArena Elo, MTEB, SWE-bench, Open LLM Leaderboard) within the top
  quartile of enumerated candidates, or a cited paper eval. General
  impressions of quality are prohibited as evidence.
- Runnability (homelab runs): VRAM requirement stated as a number against
  the target host; GGUF/ONNX availability is a flag, not a gate.
- Model license class (permissive / community-terms / research-only) is a
  hard filter when commercial use is in scope.

## Source universe

- Tier A registries (evidence base): GitHub, Hugging Face, PyPI (pepy),
  npm, crates.io, Docker Hub, Ollama library, Repology
- Tier B curated lists (discovery layer, anti-SEO): cognee tool-catalog
  dataset (weekly refresh), awesome-selfhosted-data structured YAML,
  awesome-sysadmin, topic awesome-lists, Papers With Code, OpenModelDB
- Tier C benchmarks (models only, task-gated): LMArena, MTEB, Open LLM
  Leaderboard, SWE-bench
- Tier D community corroboration (last, qualitative): HN (Algolia),
  r/selfhosted, r/LocalLLaMA — failure stories and sentiment, never
  popularity
- Excluded as evidence: G2, AlternativeTo, affiliate comparison sites,
  AI-generated listicles

Method binding: curated-list-first (enumerate before any web search); open
web verifies extracted names only; relics and wrong-category candidates
named-and-rejected in one line each, never silently omitted.

## Reporting discipline

- Every number: `value (source, as-of date)`, mirrored in projects.jsonl
- Criteria table frozen into Selection Criteria at run start; overrides
  recorded with reasons, in the run
- Freshness banner: discovery results rot; every number dated
