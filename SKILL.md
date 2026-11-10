---
name: unjangled-research
description: Use when the user needs multi-source research with citation tracking, evidence persistence, and structured report generation. Triggers on "deep research", "comprehensive analysis", "research report", "compare X vs Y", "analyze trends", or "state of the art". Not for simple lookups, debugging, or questions answerable with 1-2 searches. The skill also composes slide decks — a self-contained animated HTML deck and an editable PowerPoint (.pptx) from the same slide list — from finished research, from an existing report, or from the user's own notes or outline; triggers on "slide deck", "slides", "presentation", "PowerPoint", ".pptx", "make a deck", or "turn this into slides". Also renders a themed HTML report and a PDF.
---

# Unjangled Research

## Core Purpose

Deliver citation-tracked research reports through a structured pipeline with evidence persistence, source identity management, claim-level verification, and progressive context management.

**Autonomy Principle:** Operate independently. Infer assumptions from context. Only stop for critical errors or incomprehensible queries. Surface high-materiality assumptions explicitly in the Introduction and Methodology rather than silently defaulting.

---

## Outputs

This skill produces four deliverables: a themed HTML report, an HTML slide deck, an editable PowerPoint (.pptx) file, and a PDF. The report is the research output; decks are authored as a JSON slide list and rendered from it — from finished research, from an existing report, or from the user's own notes or outline, all covered in [slide-decks.md](./reference/slide-decks.md). The agent runs every command from the skill directory (the folder containing `scripts/` and `themes/`).

| Output | When | Command |
|---|---|---|
| HTML report | Every research run | `python3 scripts/render_report.py --report [report.md] --manifest [run_dir]/run_manifest.json --format [format] --out [report.html]` |
| HTML slide deck | When the user wants a deck, slides, or a presentation | `python3 scripts/render_deck.py --slides [deck.json] --out [deck.html]` — or `--report [report.md]` straight from a finished report |
| PowerPoint (.pptx) | When the user wants PowerPoint, a .pptx, or editable slides | `python3 scripts/render_pptx.py --slides [deck.json] --out [deck.pptx]` — or `--report [report.md]` straight from a finished report |
| PDF | When the user wants a PDF and WeasyPrint is installed | `weasyprint [report.html] [report.pdf]` — rendered from the gated HTML report |

Theme QA gate on every rendered output (report, deck, .pptx): `python3 scripts/check_theme.py [report.html|deck.html|deck.pptx] [--theme <name|path>]` — must report 0 errors before that output is delivered. On a research run the deck and the .pptx are additional outputs, never a replacement for the HTML report; a deck requested on its own needs no research run at all.

---

## Slide decks

When the user wants a deck, slides, a presentation, or a PowerPoint, follow [slide-decks.md](./reference/slide-decks.md) — the authoring guide. Three entry paths:

- **Path A — a topic:** run the research pipeline first (Phases 1–8), deliver the report, then make the deck from the finished research.
- **Path B — an existing report from this skill:** export its slide plan (`python3 scripts/deck_spec.py --report [report.md] --out [deck.json]`), edit the JSON (reorder, retitle, cut, add slides in any layout), render.
- **Path C — the user's own notes, document, or outline:** write the slide list directly from their material — no research run; never add claims or numbers that are not in it.

Every path ends the same way: render both outputs (`render_deck.py --slides`, `render_pptx.py --slides`), gate each with `check_theme.py` at 0 errors, look at the deck, fix the slide list (never the generated files), deliver.

---

## Decision Tree

```
Request Analysis
+-- Simple lookup? --> STOP: Use WebSearch
+-- Debugging? --> STOP: Use standard tools
+-- Deck / slides / PowerPoint request? --> slide-decks.md (reference/slide-decks.md)
|   +-- Topic to research? --> Path A: research run first, then the deck
|   +-- A report from this skill? --> Path B: export its plan, edit, render
|   +-- The user's own notes/outline? --> Path C: write the slide list directly
+-- Complex analysis needed? --> CONTINUE

Mode Selection
+-- Initial exploration --> quick (3 phases, 2-5 min)
+-- Standard research --> standard (6 phases, 5-10 min) [DEFAULT]
+-- Critical decision --> deep (8 phases, 10-20 min)
+-- Comprehensive review --> ultradeep (8+ phases, 20-45 min)
```

**Default assumptions:** Technical query = technical audience. Comparison = balanced perspective. Trend = recent 1-2 years.

---

## Workflow Overview

| Phase | Name | Quick | Std | Deep | Ultra |
|-------|------|-------|-----|------|-------|
| 1 | SCOPE | Y | Y | Y | Y |
| 2 | PLAN | - | Y | Y | Y |
| 3 | RETRIEVE | Y | Y | Y | Y |
| 4 | TRIANGULATE | - | Y | Y | Y |
| 4.5 | OUTLINE REFINEMENT | - | Y | Y | Y |
| 5 | SYNTHESIZE | - | Y | Y | Y |
| 6 | CRITIQUE | - | - | Y | Y |
| 7 | REFINE | - | - | Y | Y |
| 8 | PACKAGE | Y | Y | Y | Y |

**Note:** Phases 3-5 operate as an evidence loop per section (retrieve → evidence store → refine outline → draft → verify claims → delta-retrieve if needed), not as strict sequential gates.

---

## Execution

**On invocation, load relevant reference files:**

1. **Phase 1-7:** Load [methodology.md](./reference/methodology.md) for detailed phase instructions
2. **Phase 8 (Report):** Load [report-assembly.md](./reference/report-assembly.md) for progressive generation
3. **HTML/PDF output:** Load [html-generation.md](./reference/html-generation.md)
4. **Slide deck / PowerPoint output:** Load [slide-decks.md](./reference/slide-decks.md)
5. **Quality checks:** Load [quality-gates.md](./reference/quality-gates.md)
6. **Long reports (>18K words):** Load [continuation.md](./reference/continuation.md)

**Templates:**
- Report structure: [report_template.md](./templates/report_template.md) (default fallback)
- HTML styling: themed renderer (`scripts/render_report.py`) with [themes/neutral/theme.json](./themes/neutral/theme.json) as the default theme — see [html-generation.md](./reference/html-generation.md)
- **Format selection:** Before assembling the report, consult [format-selection.md](./references/format-selection.md) to choose the appropriate template from [references/report-templates/](./references/report-templates/) based on the question type. Use the default template only when no format-specific template matches.
- **Citation density:** Cite the 1–2 most authoritative sources inline per sentence. Batch additional supporting sources at the paragraph or finding level, not per sentence. A sentence carrying 3+ bracketed references is unreadable to a human reader.

**Scripts:**
- `python scripts/validate_report.py --report [path] --format [format] --manifest [run_dir]/run_manifest.json` — the manifest enables the contested-facets gate: if `contested_facets` is non-empty, the report must contain a Perspectives/Debate section covering every listed facet — pass the format chosen in Phase 8 via format-selection.md (`quick-brief` / `comparison` / `research-summary` / `comprehensive-report` / `discovery-catalog`); each format has its own required sections, word targets, and source floors. Omitting `--format` assumes comprehensive-report.
- `python scripts/verify_citations.py --report [path]`
- `python scripts/verify_citations_v2.py --dir [run_dir]` (independent second network citation check)
- `python scripts/readability_check.py [report_path]` (**MANDATORY — run on EVERY report, every time, before HTML/PDF generation; never skip, no exceptions.** Uses the vendored `textstat` in `vendor/`; no install needed. Must exit 0; failures tell you exactly what to fix: pipeline-internals leakage → move narration to run manifest; citation density → 1-2 refs/sentence, batch the rest at paragraph level; sentence length / reading grade → split compound sentences, unchain appositive lists, prefer plain words)
- `scripts/md_to_html.py` — markdown converter used internally by the render model; not a delivery step
- `python scripts/render_report.py --report [path] --manifest [run_dir]/run_manifest.json --format [format] --out [report.html]` — themed renderer; builds the render model in-process and writes a self-contained HTML report (`--theme <name|path>` overrides the default `neutral` theme)
- `python scripts/render_deck.py --slides [deck.json] --out [deck.html]` — themed HTML slide deck from an authored slide list; `--report [path] --manifest ... --format ...` renders straight from a finished report (`--theme <name|path>` as above); see [slide-decks.md](./reference/slide-decks.md) for authoring
- `python scripts/render_pptx.py --slides [deck.json] --out [deck.pptx]` — native editable PowerPoint deck from the same slide list or report (`--theme <name|path>` as above); an additional output, never a replacement for the HTML report
- `python scripts/check_theme.py [report.html] [--theme <name|path>]` — theme QA gate on the rendered HTML and on `.pptx` decks; 0 errors required before delivery (exit 1 on any ERROR)

**Phase 8 order (explicit):** `validate_report.py` → `readability_check.py` → `render_report.py` → `check_theme.py` — render only after the first two pass, deliver only at 0 QA errors. When the run also includes a deck, follow [slide-decks.md](./reference/slide-decks.md) after the report passes its gate: author or export the slide list, render `render_deck.py` and (when wanted) `render_pptx.py`, and gate each at 0 errors. A deck with no research run (paths B and C) skips Phases 1-8 entirely and goes straight to the guide. Full loop with the citation verifiers: [quality-gates.md](./reference/quality-gates.md).

---

## Scope Contract (Phase 1, comprehensive runs)

Every comprehensive run answers at planning: "which facets of this topic are actively disputed?" The answer lands in `run_manifest.json` → `contested_facets` ([] = no live disagreement found — an auditable position, not a skipped question). Non-empty → follow `references/contested-topics.md`: steelman every facet, describe-only unless the request asks for a choice.

## Output Contract

**Required sections:** depend on the chosen format — see [format-selection.md](./references/format-selection.md) and the per-format table in [quality-gates.md](./reference/quality-gates.md). The default (comprehensive-report) requires:
- Executive Summary (within format bounds)
- Introduction (scope, methodology, assumptions)
- Main Analysis (4-8 findings, 600-2,000 words each, cited)
- Synthesis & Insights (patterns, implications)
- Limitations & Caveats
- Recommendations
- Bibliography (COMPLETE - every citation, no placeholders)
- Methodology Appendix (epistemics only — never pipeline mechanics)

**Output files (all to `~/Documents/[Topic]_Research_[YYYYMMDD]/`):**
- Markdown (primary source of truth)
- `sources.jsonl` — stable source registry with canonical IDs
- `evidence.jsonl` — append-only evidence store with quotes and locators
- `claims.jsonl` — atomic claim ledger with support status
- `run_manifest.json` — query, mode, assumptions, provider config
- `projects.jsonl` — discovery runs only: one row per candidate per `schemas/discovery_project.schema.json` (name, registry, tier, metrics with asOf dates); the report's comparison matrix renders FROM this file — never the reverse
- HTML report (themed, self-contained)
- Slide deck (optional, themed, self-contained — when the user asked for one; author from research, a report, or the user's own notes per [slide-decks.md](./reference/slide-decks.md))
- PowerPoint deck (optional, editable .pptx, themed)
- PDF (professional print, auto-opened)

**Quality standards:**
- Sources at or above the chosen format's floor (3 quick-brief / 5 research-summary / 6 comparison / 10 comprehensive), 3+ per major claim
- All factual claims cited immediately [N] with evidence backing in `evidence.jsonl`
- Claim-support verification mandatory: no unsupported factual claims pass delivery
- No placeholders, no fabricated citations
- Prose-first (>=80%), bullets sparingly

---

## When to Use / NOT Use

**Search tool fallback:** if the primary search tool is unavailable on your harness, use this chain: (1) the harness's `web_extract` or `web_search` tool, (2) `curl -sL -A "Mozilla/5.0"` for direct URL fetches, (3) Playwright browser navigation as last resort. Document which route was used in the manifest.

**Use:** Comprehensive analysis, technology comparisons, state-of-the-art reviews, multi-perspective investigation, market analysis.

**Do NOT use:** Simple lookups, debugging, 1-2 search answers, quick time-sensitive queries.
