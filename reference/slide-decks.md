# Slide Decks: Authoring Guide

This skill composes slide decks. A deck is authored once as a JSON slide list and rendered to two deliverables: a self-contained animated HTML deck and a native, editable PowerPoint (.pptx) file. This skill does produce slide decks; any note saying otherwise is outdated.

The agent runs every command in this guide from the skill directory (the folder containing `scripts/` and `themes/`); paths below are relative to it.

---

## What you can make

| Deliverable | What it is |
|---|---|
| HTML deck | One self-contained file (CSS, JS, fonts, logo inlined — works offline). Staggered entrance animation, keyboard navigation (←/→ or PageUp/PageDown, Home/End, F fullscreen, R replay), a speaker-notes pane (N or the Notes button), and `prefers-reduced-motion` honored automatically. |
| PowerPoint (.pptx) | The same slide list rendered as native, editable shapes and text on a 1280×720 grid. Opens and edits in PowerPoint, Keynote, Google Slides, and LibreOffice. Each slide's speaker notes sit on its notes page. |

Both come from the same slide-list JSON, so author the content once.

**Which to offer:**

- The user says "deck", "slides", or "presentation" → render **both**.
- The user says "PowerPoint", "editable", "Keynote", or "Google Slides" → the .pptx is the deliverable (rendering both is still fine; the HTML is a quick visual check).
- The user wants something to present from a browser or to share as one file → the HTML deck.

---

## Workflow

1. **Outline the story first.** Know the audience, the one message per slide, and a 6–12 slide arc (cover, optional agenda/section dividers, 4–8 content slides, sources when citing, closing). Do not write JSON before the outline exists.
2. **Write the slide list JSON.** One file per deck: deck-level `title` plus defaults (`subtitle`, `date`, `eyebrow`, `footer_section`) and a `slides` array. Each slide names a `layout` and that layout's fields — see the layout reference below. Format: `schemas/deck_spec.schema.json`.
3. **Validate.** The renderers validate on load, or check without rendering:

   ```bash
   python3 scripts/deck_spec.py --check [deck.json]
   ```

   Prints `valid: N slides` and exits 0, or prints every error naming the slide index and field (exit 1), writing nothing. Fix the JSON, not the error's surface.
4. **Render both:**

   ```bash
   python3 scripts/render_deck.py --slides [deck.json] --out [deck.html]
   python3 scripts/render_pptx.py --slides [deck.json] --out [deck.pptx]
   ```

   `--theme <name|path>` overrides the default `neutral` theme on both.
5. **Theme QA gate — 0 errors required before delivery:**

   ```bash
   python3 scripts/check_theme.py [deck.html] [deck.pptx] [--theme <name|path>]
   ```

6. **Look at it.** Open the HTML deck in a browser and step through every slide (keyboard: ←/→). For the .pptx, render slides to PNG when LibreOffice is available:

   ```bash
   soffice --headless --convert-to pdf --outdir [outdir] [deck.pptx]
   pdftoppm -png -r 60 [outdir]/[deck].pdf [outdir]/slide
   ```

   If neither tool is available, say so and rely on the theme QA gate plus the HTML deck — the .pptx mirrors the HTML layout at 1280×720, so a clean HTML deck is strong evidence.
7. **Fix content, not files.** Overflow, truncation, or crowding means the slide has too much: shorten the text, drop an item, or split the slide — the per-field limits in the layout reference exist to keep content inside 1280×720. Never edit the generated HTML or .pptx; fix the slide list (or the theme) and re-render.
8. **Deliver.** Hand over `[deck].html` and `[deck].pptx`. Tell the user: the HTML deck is one self-contained file (arrow keys to present, N for speaker notes); the .pptx is fully editable (every word is a native text box or shape) with speaker notes on each slide's notes page.

---

## Three entry paths

### Path A — a topic ("make a deck about X")

Run the research pipeline first (Phases 1–8, per [methodology.md](./methodology.md) and [report-assembly.md](./report-assembly.md)) and deliver the report; the deck is composed from that finished research. Then either render the deck straight from the report (no editing), or export the plan and edit it as in path B first:

```bash
python3 scripts/render_deck.py --report [report.md] --manifest [run_dir]/run_manifest.json --format [format] --out [deck.html]
python3 scripts/render_pptx.py --report [report.md] --manifest [run_dir]/run_manifest.json --format [format] --out [deck.pptx]
```

### Path B — an existing report from this skill ("turn this report into slides")

Export the report's slide plan as an editable slide list, edit the JSON, render:

```bash
python3 scripts/deck_spec.py --report [report.md] --manifest [run_dir]/run_manifest.json --format [format] --out [deck.json]
```

Then edit `[deck.json]`: reorder slides, retitle them, cut slides, or add slides using any layout in the reference below (the export only uses cover, statement, bullets, facet, and sources). Re-validate, render, and gate as in the workflow. `--manifest` and `--format` are optional; without them the format is inferred from the report.

### Path C — the user's own material ("make slides from my notes/document/outline")

No research run. Read the material, outline the deck, and write the slide list directly from their content. Every claim and every number comes verbatim from the user's material — do not add claims, numbers, or emphasis that are not in it. If a gap would strengthen the deck, say so in delivery instead of filling it yourself.

---

## Layout reference

Thirteen layouts. Every field's limit below is enforced by `scripts/deck_spec.py` (and mirrored in `schemas/deck_spec.schema.json`); limits are measured so maxed content still fits 1280×720. All slides also take optional `notes` (speaker notes; `|` separates lines) and `section` (≤ 60 chars; this slide's footer section name — defaults to the deck's `footer_section`, else the layout name). JSON examples are single slides — drop them into a deck's `slides` array; numbers shown are sample data.

### Openers

#### `cover`

The deck's title slide. Required first slide. Deck-level `title`, `subtitle`, `date`, `eyebrow` fill any field the cover omits, so the cover alone can suffice.

| Field | Req. | Limit |
|---|---|---|
| `title` | yes | 120 |
| `eyebrow` | no | 120 |
| `subtitle` | no | 160 |
| `date` | no | 80 (null = no date line) |

```json
{
  "layout": "cover",
  "title": "Q3 support review",
  "eyebrow": "Support team · Q3 2026",
  "subtitle": "Results, one open question, and what's next",
  "date": "October 2026 · Sample data",
  "notes": "Cover slide|15-minute standup deck"
}
```

#### `section`

A divider marking a chapter or act break. Use between story movements, not after every slide.

| Field | Req. | Limit |
|---|---|---|
| `title` | yes | 90 (shown large) |
| `eyebrow` | no | 120 |
| `sub` | no | 200 (one line under the name) |

```json
{
  "layout": "section",
  "title": "Where the numbers came from",
  "eyebrow": "Part 02",
  "sub": "The dashboard export and the survey re-run.",
  "notes": "Section divider|Transition to methods"
}
```

#### `agenda`

The table of contents: 2–5 numbered rows. Use when the deck runs longer than ~6 slides or the audience needs the map.

| Field | Req. | Limit |
|---|---|---|
| `title` | yes | 30 |
| `items` | yes | 2–5 entries |
| `items[].title` | yes | 20 |
| `items[].desc` | no | 55 |
| `eyebrow` | no | 120 |

```json
{
  "layout": "agenda",
  "title": "What we'll cover",
  "eyebrow": "Agenda",
  "items": [
    {"title": "Results", "desc": "Volume and response time vs. last quarter"},
    {"title": "What worked", "desc": "Help-center rewrite, triage rota"},
    {"title": "Open question", "desc": "Satisfaction flat at 4.2/5 (sample data)"}
  ],
  "notes": "Three parts, about three minutes each"
}
```

### Message layouts

#### `statement`

One sentence carrying the slide's whole point, with up to three stat tiles beneath. The workhorse for a key finding.

| Field | Req. | Limit |
|---|---|---|
| `headline` | yes | 150 |
| `stats` | no | 0–3 tiles |
| `stats[].value` | yes | 40 — the number verbatim from its source; never computed or invented |
| `stats[].label` | yes | 90 — what the value counts |
| `stats[].ref` | no | [N] citation integer ≥ 1, or null |
| `eyebrow` | no | 120 |

```json
{
  "layout": "statement",
  "eyebrow": "Headline finding",
  "headline": "Median response time fell by a third in one quarter",
  "stats": [
    {"value": "3h40m", "label": "median first response this quarter (sample data)", "ref": 1},
    {"value": "6h", "label": "previous quarter (sample data)", "ref": null},
    {"value": "-39%", "label": "change, quarter over quarter (sample data)", "ref": 1}
  ],
  "notes": "Statement layout|Tile values are sample data"
}
```

#### `bullets`

A short titled list, up to five points. Each bullet carries optional `refs` ([N] citations shown as an evidence line).

| Field | Req. | Limit |
|---|---|---|
| `title` | yes | 90 |
| `bullets` | yes | 0–5 points |
| `bullets[].text` | yes | 200 |
| `bullets[].refs` | no | [N] citation integers |
| `refs` | no | fallback evidence line when no bullets render |
| `eyebrow` | no | 120 |

```json
{
  "layout": "bullets",
  "title": "What changed last quarter",
  "eyebrow": "Actions",
  "bullets": [
    {"text": "Rewrote the ten most-visited help-center articles.", "refs": [1]},
    {"text": "Stood up a triage rota for first responses.", "refs": []},
    {"text": "Retired the legacy ticket form.", "refs": []}
  ],
  "notes": "Bullets layout|Sample content"
}
```

#### `quote`

Someone's words, large. Omit `title` for a full-bleed quote; include it (≤ 35) when the quote needs a caption.

| Field | Req. | Limit |
|---|---|---|
| `quote` | yes | 400 — the words themselves, no quotation marks |
| `attribution` | no | 120 — who said or wrote it, and where |
| `title` | no | 35 |
| `eyebrow` | no | 120 |

```json
{
  "layout": "quote",
  "eyebrow": "From the review",
  "quote": "The rota change did more for response time than any tool we bought.",
  "attribution": "Dana, team lead — quarterly review notes (sample attribution)",
  "notes": "Quote layout|Sample quotation"
}
```

### Structure layouts

#### `two_column`

Two titled panels side by side — two explanations, before/after context, or detail plus summary. Each panel is a paragraph or bullets, never both.

| Field | Req. | Limit |
|---|---|---|
| `title` | yes | 90 |
| `left` / `right` | yes | panel objects |
| panel `title` | yes | 60 |
| panel `body` | one of | 350 — paragraph text |
| panel `bullets` | one of | 1–3 points, each ≤ 120 |
| `eyebrow` | no | 120 |

```json
{
  "layout": "two_column",
  "title": "What worked, what didn't",
  "eyebrow": "Scorecard",
  "left": {
    "title": "Worked",
    "bullets": [
      {"text": "Help-center rewrite cut repeat tickets."},
      {"text": "Triage rota spread first-response load."}
    ]
  },
  "right": {
    "title": "Didn't",
    "body": "The chat-widget rollout slipped to next quarter, so its expected volume shift never landed (sample data)."
  },
  "notes": "Two-column layout|Both columns, no spin"
}
```

#### `three_values`

Three parallel pillars — exactly three, one numbered column each. Use for three benefits, principles, or parts of a framework.

| Field | Req. | Limit |
|---|---|---|
| `title` | yes | 42 |
| `values` | yes | exactly 3 |
| `values[].title` | yes | 45 |
| `values[].body` | yes | 200 |
| `note` | no | 100 — qualifier under the columns |
| `eyebrow` | no | 120 |

```json
{
  "layout": "three_values",
  "title": "Three things to repeat next quarter",
  "eyebrow": "Values",
  "values": [
    {"title": "Write it down", "body": "Every incident got a short public note, which became the rewritten articles."},
    {"title": "Share the load", "body": "The rota made first response everyone's job once a week, not one team's always."},
    {"title": "Measure weekly", "body": "A Monday dashboard look kept small dips from becoming quarter-end surprises."}
  ],
  "note": "Sample data — illustrative values.",
  "notes": "Three-values layout|Sample content"
}
```

#### `compare`

Two cards facing off — problem/solution, before/after, option A/B — with an arrow between. The left card renders ✗ marks, the right ✓ marks.

| Field | Req. | Limit |
|---|---|---|
| `title` | yes | 35 |
| `options` | yes | exactly 2 |
| option `tag` | no | 30 — defaults to "Option A"/"Option B" |
| option `name` | yes | 45 |
| option `rows` | yes | 1–3 lines, each ≤ 60 |
| option `kicker` | no | 80 — takeaway at the card's bottom |
| `eyebrow` | no | 120 |

```json
{
  "layout": "compare",
  "title": "Two ways to answer it",
  "eyebrow": "Compare",
  "options": [
    {
      "tag": "Today",
      "name": "Weekly manual review",
      "rows": ["Findings arrive days late.", "Coverage depends on who's on call."],
      "kicker": "Reactive by default."
    },
    {
      "tag": "Proposed",
      "name": "Monday dashboard look",
      "rows": ["Dips surface the week they happen.", "One owner, fifteen minutes."],
      "kicker": "Small dips stay small."
    }
  ],
  "notes": "Compare layout|Sample contrast, no real measurements"
}
```

### Data layout

#### `bars`

Ranked horizontal bars, 2–6, each with a value at its end. Order the bars yourself, largest first — widths scale to the largest value, and the top row is emphasized. Put the source (or the "Sample data" label) in `note`.

| Field | Req. | Limit |
|---|---|---|
| `title` | yes | 90 |
| `bars` | yes | 2–6 bars |
| `bars[].label` | yes | 60 |
| `bars[].value` | yes | number ≥ 0 — drives the bar's length |
| `bars[].display` | yes | 16 — the text at the bar's end (e.g. "64%") |
| `note` | no | 200 — source or qualifier; label sample data here |
| `eyebrow` | no | 120 |

```json
{
  "layout": "bars",
  "title": "Where first responses came from",
  "eyebrow": "Bars · Sample data",
  "bars": [
    {"label": "Triage rota", "value": 48, "display": "48%"},
    {"label": "Direct queue", "value": 31, "display": "31%"},
    {"label": "Escalations", "value": 14, "display": "14%"},
    {"label": "Other", "value": 7, "display": "7%"}
  ],
  "note": "Sample data — share of a hypothetical 1,050-ticket quarter.",
  "notes": "Bars layout|All values are sample data"
}
```

### Debate layout

#### `facet`

Two to four sides of one contested question, each stating its position. Use for genuine disagreement, not mild nuance. Without `sides`, falls back to ≤ 3 bullets.

| Field | Req. | Limit |
|---|---|---|
| `title` | yes | 90 |
| `sides` | one of | 1–4 sides |
| `sides[].label` | yes | 40 |
| `sides[].summary` | yes | 200 — one or two sentences stating the position |
| `bullets` | one of | 0–3 fallback points (text ≤ 200) |
| `eyebrow` | no | 120 |

```json
{
  "layout": "facet",
  "title": "Why the score stayed flat",
  "eyebrow": "Open question",
  "sides": [
    {"label": "Volume effect", "summary": "Faster answers on simpler tickets can't move a score weighted by the hard ones (sample position)."},
    {"label": "Survey fatigue", "summary": "The same respondents answer quarterly, anchoring on last quarter's number (sample position)."}
  ],
  "notes": "Facet layout|Both sides are sample positions"
}
```

### Closing layouts

#### `sources`

The bibliography slide: numbered entries matching the [N] citations used on earlier slides. Keep to about five entries per slide — more renders densely; use `more_sources` to count the rest.

| Field | Req. | Limit |
|---|---|---|
| `title` | yes | 40 |
| `sources` | yes | 1–12 entries |
| `sources[].n` | yes | integer ≥ 1 (the [N] number) |
| `sources[].title` | yes | 70 |
| `sources[].publisher` | no | 60 |
| `sources[].url` | no | 300 |
| `more_sources` | no | integer ≥ 0 — shown as "+N more in the full report" |
| `eyebrow` | no | 120 |

```json
{
  "layout": "sources",
  "title": "3 sources",
  "eyebrow": "Sources",
  "sources": [
    {"n": 1, "title": "Quarterly support dashboard export", "publisher": "Internal", "url": null},
    {"n": 2, "title": "CSAT survey, week 13 (sample data)", "publisher": "Survey tool", "url": null},
    {"n": 3, "title": "Triage rota notes", "publisher": "Team wiki", "url": null}
  ],
  "more_sources": 1,
  "notes": "Sources layout|All entries are illustrative, sample data"
}
```

#### `closing`

The final slide: one headline plus numbered next steps. End every deck here, not on a sources slide.

| Field | Req. | Limit |
|---|---|---|
| `headline` | yes | 90 |
| `steps` | yes | 1–5 steps, each ≤ 120, in order |
| `eyebrow` | no | 120 |

```json
{
  "layout": "closing",
  "eyebrow": "Next steps",
  "headline": "Ship the widget, then re-measure",
  "steps": [
    "Ship the chat widget in October.",
    "Re-run the CSAT survey in week 1.",
    "Review both at the end of the quarter."
  ],
  "notes": "Closing layout|Owners confirmed in the meeting"
}
```

---

## Writing good slides

- **One idea per slide.** If a slide makes two points, it is two slides.
- **Short headlines.** A title states the point ("Response time fell by a third"), not the topic ("Response time").
- **≤ 3–4 items per row.** The layouts enforce this; don't fight it by cramming each item.
- **Numbers verbatim or labelled.** Take values verbatim from their source. Label illustrative numbers "Sample data" in the label or the `note`. Never invent or compute-then-present numbers.
- **Date ranges on metrics.** A number without a period is a rumor: "1,050 tickets (Q3)" not "1,050 tickets".
- **Sources in the slide.** [N] refs point at the sources slide; chart sources go in the `bars` `note`. When the material is the user's own, no sources slide is needed — say where numbers came from in the notes.
- **Speaker notes carry the detail.** The slide is the headline; the fuller text goes in `notes` (`|` separates lines).
- **Motion is the engine's job.** Staggered reveals ship automatically and honor `prefers-reduced-motion`; do not hand-roll animation.

**Picking a layout:**

| You have… | Use |
|---|---|
| A title page | `cover` |
| A table of contents | `agenda` |
| A chapter break | `section` |
| One point, maybe 2–3 numbers | `statement` |
| A short list of points | `bullets` |
| Two explanations side by side | `two_column` |
| Three parallel pillars | `three_values` |
| A versus B, before/after, problem/solution | `compare` |
| Ranked quantities | `bars` |
| 2–4 sides of a contested question | `facet` |
| Someone's words | `quote` |
| Bibliography | `sources` |
| Next steps / call to action | `closing` |

---

## Themes

- Default theme: `neutral` (`themes/neutral/theme.json`). Override on any render with `--theme <name|path>` — a name under `themes/` or a path to a theme folder; pass the same value to `check_theme.py`.
- Adding a theme: copy `themes/neutral/` to `themes/<name>/` and edit `theme.json` (palette, fonts, footer label, motif) — see the "Adding a theme" section of [html-generation.md](./html-generation.md).
- Never edit CSS. All styling is generated from the theme; a fix belongs in `theme.json` or the slide list, followed by a re-render.

---

## Limits, stated plainly

- **Fixed layouts.** No free-form positioning; a slide is its layout. Content that does not fit does not belong on the slide — shorten or split it.
- **No native PowerPoint charts.** `bars` are shapes with widths, not chart objects; nothing here creates Excel/Sheets charts.
- **Fonts by name.** The .pptx references the theme's font family by name — rendered with that font if installed, else the viewer's default; nothing is embedded (the HTML deck does embed its fonts).
- **No images.** Author content is text and bars only; the only image is the theme's logo, when the theme has one.
- **Per-field limits.** Every field cap in the layout reference above is enforced at validation; they keep maxed content inside 1280×720.
- **Sources slides render densely past ~5 entries** — split or use `more_sources`.

---

## Worked example (path C)

The user's notes, `q3-notes.md`:

```markdown
# Q3 support review — notes

- Audience: support team leads, Thursday standup (15 min)
- Ticket volume: 1,240 in Q2 → 1,050 in Q3, after the new help center shipped
- Median first response: 6h in Q2 → 3h40m in Q3
- CSAT flat at 4.2/5 — the open question for Q4
- Worked: rewrote the top-10 articles; new triage rota
- Didn't: chat widget rollout slipped to Q4
- Dana: "The rota change did more for response time than any tool we bought."
- Next: ship chat widget in October; re-run the CSAT survey in week 1; review
  again end of Q4
```

Outline: cover → agenda → results (statement) → worked/didn't (two_column) → the flat score (bullets) → Dana (quote) → next (closing). Seven slides, one message each, every number from the notes.

The slide list, `q3_review.json`:

```json
{
  "title": "Q3 support review",
  "subtitle": "Results, one open question, and what's next",
  "date": "October 2026",
  "eyebrow": "Support team · Q3 2026",
  "footer_section": "Q3 review",
  "slides": [
    {
      "layout": "cover",
      "title": "Q3 support review",
      "notes": "15-minute standup deck|Numbers from the Q3 dashboard and survey"
    },
    {
      "layout": "agenda",
      "title": "What we'll cover",
      "items": [
        {"title": "Results", "desc": "Volume and response time vs. Q2"},
        {"title": "What worked", "desc": "Help-center rewrite, triage rota"},
        {"title": "Open question", "desc": "CSAT flat at 4.2/5"},
        {"title": "Next steps", "desc": "October and end-of-Q4 actions"}
      ],
      "notes": "Four parts, about three minutes each"
    },
    {
      "layout": "statement",
      "headline": "Volume and response time both improved; CSAT held flat",
      "stats": [
        {"value": "1,050", "label": "tickets in Q3, down from 1,240 in Q2"},
        {"value": "3h40m", "label": "median first response, from 6h in Q2"},
        {"value": "4.2/5", "label": "CSAT, unchanged from Q2"}
      ],
      "notes": "All three numbers from the dashboard export"
    },
    {
      "layout": "two_column",
      "title": "What worked, what didn't",
      "left": {
        "title": "Worked",
        "bullets": [
          {"text": "Rewrote the top-10 help-center articles."},
          {"text": "New triage rota spread first-response load."}
        ]
      },
      "right": {
        "title": "Didn't",
        "bullets": [
          {"text": "Chat-widget rollout slipped to Q4."}
        ]
      },
      "notes": "Both columns, no spin"
    },
    {
      "layout": "bullets",
      "title": "The open question: CSAT",
      "bullets": [
        {"text": "Volume and speed improved; the score didn't move."},
        {"text": "CSAT flat at 4.2/5 — the question to answer in Q4."},
        {"text": "Survey re-runs in week 1 of the chat launch."}
      ],
      "notes": "Name the question; don't bury it"
    },
    {
      "layout": "quote",
      "quote": "The rota change did more for response time than any tool we bought.",
      "attribution": "Dana — Q3 review notes",
      "notes": "Read it as written"
    },
    {
      "layout": "closing",
      "eyebrow": "Next steps",
      "headline": "Ship the widget, then re-measure",
      "steps": [
        "Ship the chat widget in October.",
        "Re-run the CSAT survey in week 1.",
        "Review both at the end of Q4."
      ],
      "notes": "Owners confirmed in the meeting"
    }
  ]
}
```

Validate, render, gate, and look (from the skill directory, deck files in a work folder such as `/tmp/q3-deck`):

```bash
python3 scripts/deck_spec.py --check /tmp/q3-deck/q3_review.json
python3 scripts/render_deck.py --slides /tmp/q3-deck/q3_review.json --out /tmp/q3-deck/q3_review.html
python3 scripts/render_pptx.py --slides /tmp/q3-deck/q3_review.json --out /tmp/q3-deck/q3_review.pptx
python3 scripts/check_theme.py /tmp/q3-deck/q3_review.html /tmp/q3-deck/q3_review.pptx
soffice --headless --convert-to pdf --outdir /tmp/q3-deck /tmp/q3-deck/q3_review.pptx
pdftoppm -png -r 60 /tmp/q3-deck/q3_review.pdf /tmp/q3-deck/slide
```

`check_theme.py` prints its per-file checks and exits 0; the PNGs (`slide-1.png` … `slide-7.png`) show every slide. Deliver `q3_review.html` and `q3_review.pptx`, mention the speaker notes, and say the .pptx is editable.
