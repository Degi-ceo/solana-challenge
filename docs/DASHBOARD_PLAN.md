# Dashboard plan (v3)

Goal: Kamil opens one page and knows, without asking, **what the bot is doing, whether anything needs him, what the results are, and what every
rule is**. It must be tidy, transparent, and equally good on a desktop and a phone.

## Critique of v2 (design-critique + dataviz anti-patterns + accessibility checklist)

| Finding | Severity | Fix in v3 |
|---|---|---|
| One endless page with 8 sections and anchor chips; nothing says what matters most | Critical | 4 tabs (Overview, Data, Rules, Log); Overview answers "what now / what's needed / verdict / plan" |
| No "right now", no ETA, no "needs from you", no verdict criteria | Critical | A "Right now" card and a verdict card with the coded go/no-go thresholds |
| Serif + tabular figures on big numbers, 11px chart text, dashed reference lines (all listed anti-patterns) | Major | One sans face, proportional big figures, solid hairlines, 13px minimum captions |
| Six equal-weight tiles, many card styles | Major | Four figures max; one card style; hierarchy by size and position |
| Charts with no table twin, hover-only detail | Major | Every chart has a "Table view"; values printed on the bars |
| Tables and fixed-height SVG not built for 390px wide screens | Critical | HTML bars (fluid), tables become cards on phones, 44px touch targets |
| Built on a framework page I could not render or test | Major | Plain self-contained page; screenshots checked at 1280px and 390px, light and dark |
| Status shown by colour alone in places | Major | Status = icon/dot + word, text stays ink-coloured |

## Information architecture

- **Top bar (always visible):** Paper only · Live trading off · Kill switch · snapshot age (warns when older than 2 h).
- **Overview:** Right now (task, progress, ETA, next step, needs from you) → four figures (paper P&L, paper trades, history coverage, tests) →
  verdict (criteria vs current) → work plan (9 tasks).
- **Data:** coverage meter + ETA → funnel (found → eligible → age window → liquidity floor → history ready) → liquidity bands →
  backtest results (empty state until it runs) → pool explorer (search, filters, sort).
- **Rules:** the six-step pipeline, then every threshold grouped (filters, exits, costs, risk, limits, verdict) with plain-language reasons.
- **Log:** data-source health, then the project journal (newest first) with a link to the full file.

## Visual system (from the dataviz skill)

Surfaces `#fcfcfb` / `#1a1a19`; ink `#0b0b0b` / `#f0efec`; single accent blue `#2a78d6` / `#3987e5`; status green / amber / red only for status,
always with icon + word. Bars ≤ 24px with a 4px rounded data end, hairline solid grid, meters on a lighter tint of the same blue.
Inter with a system fallback; body 15px, captions 13px. Light and dark both designed.

## Mechanics

- `docs/dashboard/template.html` + `bot/build_dashboard.py` embed the exporter's JSON into one self-contained HTML file → published as an Artifact.
- Snapshot, not a stream: the page shows its age, and I republish after each task. A live version needs the VPS (task 8).
- Verified by Playwright screenshots at 1280×900 and 390×844 in both themes before publishing.
