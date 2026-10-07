# Discovery Catalog: Self-Hosted Note Taking

*Metrics current as of 2026-10-06; discovery results rot.*

## Summary

Three candidates clear the Adopt bar. Joplin leads on every signal: 48,000 stars on GitHub, packages in four distributions, and a release two weeks old [1] [5]. Obsidian.md is Evaluate rather than Adopt because its sync engine is proprietary and only one registry carries it [2]. Trilium Notes clears the floors but its single-maintainer bus factor caps it at Watch [3]. Two relics were considered and rejected in one line each: Tomboy (archived 2020) and NV.py (no release since 2015).

## Selection Criteria

Frozen from discovery-criteria.md (verbatim, overrides below — none):

| Status | Definition (days since last commit or release) | Consequence |
|---|---|---|
| ACTIVE | ≤ 180 | eligible for any tier |
| FADING | 181–365 | eligible, flagged |
| DORMANT | 366–730 | cannot tier above Watch |
| ARCHIVED/DEAD | repo archived, or > 730 | Ruled Out, named |

Registry floors: GitHub ≥ 300 stars (1,000+ = high-visibility flag);
packaging in ≥ 2 distros corroborates. Percentile rule: candidate set ≥ 8 →
also qualify at ≥ 70th percentile. Two-signal rule: Adopt requires
floor-or-percentile plus one corroborating signal from a different registry.

Tier rule: Ruled Out (hard-gate or floor failure) → Watch (single source,
bus factor, < 180 days stable, or unverified metrics) → Evaluate (one soft
flag) → Adopt (ACTIVE + floor + two sources + bus factor clear + clean
license + zero soft flags).

## Comparison Matrix

| Candidate | Registry | Popularity (source, date) | Last activity | License | Status | Tier |
|---|---|---|---|---|---|---|
| Joplin | GitHub | 48,000 stars (GitHub, 2026-10-06) | release 2026-09-24 (GitHub, 2026-10-06) | MIT | ACTIVE | Adopt |
| Joplin | Repology | 4 distros (Repology, 2026-10-06) | — | — | — | Adopt |
| Obsidian.md | GitHub | 9,200 stars (GitHub, 2026-10-06) | release 2026-10-01 (GitHub, 2026-10-06) | proprietary core | ACTIVE | Evaluate |
| Trilium Notes | GitHub | 28,000 stars (GitHub, 2026-10-06) | commit 2026-09-30 (GitHub, 2026-10-06) | AGPL-3.0 | ACTIVE | Watch |

## Project Dossiers

### Joplin

An open-source markdown note application with end-to-end encryption and self-hosted sync via the Joplin Server. Popularity evidence: 48,000 stars on GitHub and packaging in four distributions [1] [5]. Release cadence is monthly with the latest two weeks old [1]. The honest downside: the mobile clients lag the desktop feature set, and the sync server wants its own database container.

### Obsidian.md

A local-first knowledge base with a plugin ecosystem. The GitHub mirror carries 9,200 stars and a release this month [2]. It sits at Evaluate rather than Adopt because the core is proprietary: only one independent registry carries it, so the two-signal rule is unmet [2]. The downside is lock-in risk if the vendor changes licensing.

### Trilium Notes

A hierarchical note application with strong scripting support. It clears every floor: 28,000 stars, commits this week, AGPL-3.0 [3]. It caps at Watch on bus factor alone — one maintainer, no organization behind it [3]. The downside: single-maintainer projects can go DORMANT without notice.

## Sources Consulted

Enumerated first: the tool-catalog dataset note-taking category and the awesome-selfhosted note-taking section [6] [7]. Verified against GitHub and Repology [1] [5]. Considered and rejected: Tomboy (archived 2020, one line), NV.py (no release since 2015, one line). Excluded as evidence class: G2, AlternativeTo, and affiliate comparison sites, per criteria.

## Bibliography
[1] GitHub. Joplin repo metrics, retrieved 2026-10-06. https://github.com/laurent22/joplin
[2] GitHub. Obsidian.md repo metrics, retrieved 2026-10-06. https://github.com/obsidianmd/obsidian-releases
[3] GitHub. Trilium Notes repo metrics, retrieved 2026-10-06. https://github.com/zadam/trilium
[4] Repology. Joplin packaging, retrieved 2026-10-06. https://repology.org/project/joplin
[5] Repology. Joplin packaging across distributions, retrieved 2026-10-06. https://repology.org/project/joplin/versions
[6] awesome-selfhosted. Note-taking section, retrieved 2026-10-06. https://github.com/awesome-selfhosted/awesome-selfhosted
[7] tool-catalog dataset. Note-taking category, snapshot 2026-10-04. homelab cognee
[8] awesome-selfhosted-data. Joplin YAML entry, snapshot 2026-10-04. https://github.com/awesome-selfhosted/awesome-selfhosted-data
