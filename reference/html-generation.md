# HTML Generation: Themed Report

## Design Principles

- Page-style report rendered from the finished markdown by `scripts/render_report.py`
- One self-contained HTML file: fonts and assets embedded, zero external references
- Styling comes from the theme (`themes/<name>/theme.json`) — never edit CSS
- Info-first structure: header, KPI cards, sections in order, linked citations, anchored bibliography
- NO EMOJIS in final HTML

---

## Generation Steps

The agent runs every command from the skill directory (the folder containing
`scripts/` and `themes/`); paths below are relative to it.
Steps 1-4 are the readability, render, render-completeness and theme-QA
gates of the Phase 8 gate chain; the full order, with the gates that run
between them, is in
`reference/quality-gates.md#phase-8-gate-chain`.

### Step 1: Readability gate (unchanged rule)

```bash
python3 scripts/readability_check.py [report_path]
```

Must pass before any HTML is generated — every report, every format, never
skipped: exit 0 is a clean pass, exit 2 is warnings only and still a pass;
exit 1 fails (fix the prose, re-run); exit 3 (textstat unavailable) also
blocks delivery.
On failure the gate output names the repair. Full thresholds:
`reference/quality-gates.md`.

### Step 2: Render the themed report

```bash
python3 scripts/render_report.py --report [report.md] --manifest [run_dir]/run_manifest.json --format [format] --out [report.html]
```

- `--report` takes the finished report markdown; the render model is built
  in-process, so no separate model step is needed.
- `--manifest` points at the run's `run_manifest.json` (optional; supplies
  the date, the format default, and `contested_facets` for the Perspectives
  blocks).
- `--format` is the format chosen in Phase 8 (`quick-brief` / `comparison` /
  `research-summary` / `comprehensive-report` / `discovery-catalog`);
  default: the run manifest's `format` field, else inferred from the report.
- `--theme <name|path>` selects a theme: a name under `themes/` or a path to
  a theme folder. Default: `neutral`.
- `--out` writes a single self-contained HTML file.

The renderer emits the header (title, subtitle, date, format eyebrow, motif),
KPI cards when the report carries key stats, the executive summary, sections
in order, a Perspectives block per contested facet, a numbered bibliography
whose `id="ref-N"` anchors the in-text `[N]` citations link to, and a footer
from the theme's label template.

**What the renderer guarantees (what epic-render-fidelity shipped):**

- All report text is HTML-escaped before the markdown rules run, so the only
  live markup in the report is what the renderer itself generates — a
  `<script>` or `onerror=` copied from a web page renders as visible text.
- Link rule: a `[text](https://…)` link in a report section stays a live
  `<a href>` anchor (the scheme is matched case-insensitively, so `HTTPS://`
  anchors too). Every other target — `http:`, `javascript:`, `file:`,
  `data:`, relative — renders as plain escaped text `text (URL)`. In every
  plain-text path (the executive summary strip, KPI labels, findings, deck
  slides, speaker notes, .pptx text) all links, https included, render as
  `text (URL)`. Authored markdown goes live only as an https section
  anchor; the one other live anchor in the report is the renderer-built
  bibliography row, which anchors whatever http(s) URL its entry carries
  (the theme gate exempts `<a href>` links — they load nothing).
- The bibliography boundary is the shared helper's exact, case-sensitive
  heading rule: `## Bibliography` or `## Sources`, exact case, outside code
  fences. A lower-case `## sources` heading is a body section; a `###`
  subsection (such as `### Sources of funding`) is body text; sections after
  the bibliography stay in the body.
- Authored non-entry lines in the bibliography section (a note, a `###`
  label) are kept and rendered as unnumbered note paragraphs under the
  bibliography; decks list sources only, never notes.
- Table rows survive: only the row directly after the header separates (and
  only at the header's width); data rows containing `---` and rows written
  without a trailing pipe keep every cell.
- A theme whose `fonts.css` or `logo` resolves outside the theme folder
  (`../`, absolute path, symlink) fails to load, and the renderer exits 1
  with one clean `ERROR:` line naming the field before writing any output.

### Step 3: Render completeness gate

```bash
python3 scripts/verify_html.py --html [report.html] --md [report.md]
```

The post-render completeness gate: the delivered HTML must still hold the
report the author wrote — every section heading and body line, every
citation marker, every bibliography entry and note, every link with its URL,
no unfilled template tokens and no emojis. Exit 0 = pass
(`verify_html: PASS`); exit 1 names each loss (`ERROR: …` lines plus
`verify_html: FAIL (N errors)`) — a lost heading or body text, a link that
lost its URL, a dropped table row, a missing citation, a lost bibliography
entry or note. A loss means the renderer dropped authored content: fix the
report or the theme and re-render, never the generated HTML.

### Step 4: Theme QA gate

```bash
python3 scripts/check_theme.py [report.html] [--theme <name|path>]
```

Must report 0 errors before the report is delivered. Fix every ERROR and
re-render; resolve WARNs or record the justification in the run manifest's
`qa_notes` field. Exit 0 = no errors (WARNs allowed); exit 1 = at least
one ERROR; exit 2 = the theme could not be loaded. Pass
`--theme` when Step 2 used a non-default theme.

Besides the standing rules (forbidden colors, external references,
undeclared fonts, text in the motif keep-out — full list in
`reference/quality-gates.md`), the gate fails injected markup and unsafe
links: a `<script>` that is not the renderer's own `deck.js`, any `on…=`
event handler attribute, a `javascript:` or `data:` document URL (entity
tricks and any letter case included), a `srcdoc=` attribute — and, on
`.pptx` packages, an external hyperlink target that is not `http(s)` or
carries a control character.

### Step 5: Open (optional)

Open the HTML for the user when the environment allows it (for example
`open` on macOS, `xdg-open` on Linux).

---

## Optional: slide deck

When the user asks for slides, a presentation, or a deck, the agent renders
one from the same inputs as the report (otherwise the report alone is
delivered). Render it after the report has passed Steps 1-4. This works from
a finished report of an earlier run too: pass its markdown via `--report`
(and that run's manifest via `--manifest` if available) with no new research.

For any other deck request — composing one from notes or an outline, editing
an exported plan, or choosing layouts — the authoring guide is
[slide-decks.md](./slide-decks.md); the command below is path A/B of that
guide, rendered straight from the report.

```bash
python3 scripts/render_deck.py --report [report.md] --manifest [run_dir]/run_manifest.json --format [format] --out [deck.html]
```

`--report`, `--manifest`, `--format`, and `--theme <name|path>` behave exactly
as in Step 2; the render model is built in-process. The deck is one
self-contained HTML file (cover, statement and stat tiles, finding slides,
one slide per contested facet, sources).

Gate the deck the same way:

```bash
python3 scripts/check_theme.py [deck.html] [--theme <name|path>]
```

`check_theme.py` must report 0 errors on the deck too before it is delivered
(same ERROR/WARN rules as Step 4, including the injected-markup and
hyperlink-target rules). Fix problems in the report or the theme
and re-render — never by editing the generated HTML.

---

## Optional: PowerPoint

When the user asks for PowerPoint, a `.pptx`, or editable slides, the agent
also renders a native PowerPoint deck from the same inputs as the report —
an additional output next to the HTML report, never instead of it. Render it
after the report has passed Steps 1-4 (and after the optional HTML deck).
As with the HTML deck, a finished report of an earlier run works too: pass
its markdown via `--report` (and that run's manifest via `--manifest` if
available) with no new research. Authoring or editing the deck itself —
including rendering from a slide list with `--slides [deck.json]` — is
covered in [slide-decks.md](./slide-decks.md):

```bash
python3 scripts/render_pptx.py --report [report.md] --manifest [run_dir]/run_manifest.json --format [format] --out [deck.pptx]
```

`--report`, `--manifest`, `--format`, and `--theme <name|path>` behave exactly
as in Step 2; the render model is built in-process, so no separate model step
is needed.

Gate the `.pptx` the same way:

```bash
python3 scripts/check_theme.py [deck.pptx] [--theme <name|path>]
```

`check_theme.py` must report 0 errors on the `.pptx` too before it is
delivered. It inspects the package's slides, masters, layouts, theme parts,
and relationships: forbidden colors, off-theme fonts, empty slides, and any
external relationship other than a hyperlink are ERRORs; an external
hyperlink whose target is not `http(s)` (any letter case) or carries a
control character is an ERROR too; off-palette colors
WARN. Fix problems in the report or the theme and re-render — never by
patching the generated file.

The file is fully editable: every visible word sits in native text boxes and
shapes (`<a:t>` runs), so it opens and edits in PowerPoint, Keynote, Google
Slides, or LibreOffice. Fonts are referenced by name only (the theme's
family — Lato if the viewer has it installed, otherwise the viewer's default
sans); nothing is embedded and nothing needs to be installed. Each slide
carries its speaker notes on its notes page.

---

## Adding a theme

Copy `themes/neutral/` to `themes/<name>/` and edit `theme.json`. The
renderer generates all CSS from the theme — never edit CSS, and never patch
the generated HTML. `fonts.css` (the `@font-face` rules) ships inside the
theme folder and is embedded at render time; a logo file and its license can
live there too.

| `theme.json` key | Controls |
|---|---|
| `name` | theme identifier used by `--theme` |
| `colors` | palette: `surface`, `ink`, `body`, `muted`, `line`, `line_strong`, `fill`, `accent` (+ `accent_ink`, `accent_tints`), `secondary` (+ `secondary_ink`, `secondary_tints`) |
| `fonts` | `family`, `fallback` stack, `css` (the `@font-face` file to embed) |
| `footer` | footer label template (`{title}`, `{section}`) |
| `motif` | background motif: `enabled`, `tints_a`, `tints_b`, `ratio`, `line` |
| `qa` | gate rules: `allowed_colors`, `forbidden_colors` (hex → reason), `forbid_dark_surfaces` |

A new theme is exercised only through the renderer: re-run Step 2 with
`--theme <name>` and gate the output with Step 4. A theme whose `fonts.css`
or `logo` resolves outside its folder (including through a symlink) fails to
load, and every renderer exits 1 with one clean `ERROR:` line naming the
field.

---

## PDF Generation (optional)

**Option A: WeasyPrint (preferred)**

1. Render and gate the themed report first (Steps 1-4). The HTML is
   self-contained, so WeasyPrint needs no network access.
2. Generate: `weasyprint [report.html] [report.pdf]`
3. Open the PDF.

If pagination is poor, consult
[weasyprint_guidelines.md](./weasyprint_guidelines.md); fix problems in the
theme (`theme.json`) or the report, never by editing the generated HTML.
Requires WeasyPrint (`pip install weasyprint`).

**Option B: another local HTML-to-PDF tool**

Any converter that renders local, self-contained HTML works; the report
pulls nothing from the network.
