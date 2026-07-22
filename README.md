# pattern_analyzer2

**Demand Pattern RCA Agent — Console.** A single-file, dependency-free web app that ingests the weekly demand file (`.xlsx`/`.csv`) in the browser and produces rule-based Root-Cause Analysis on two metrics — **Forecast Accuracy** and **Plan Adherence** — keyed on `Forecast_name × Fiscal_Week`.

## Contents
| File | Purpose |
|---|---|
| `rca_console.html` | The app. Tabs: **RCA Console**, **Dashboard** (volumetrics + graphs), **Timeline** (deadline Gantt), Architecture, Tech Stack, AI Models, Data & Files, Definitions. |
| `rca_timeline.html` | Standalone build Gantt to 30 Jul (theme-aware). |
| `index.html` | GitHub Pages entry — redirects to the console. |
| `IMP_DOCS/` | Prompt trail, design choices, handoff, and TODO. |

## Live site
GitHub Pages: **https://aabh-ai.github.io/pattern_analyzer2/**

## Run locally
Open `rca_console.html` in any modern browser → *Upload weekly file* → filter / inspect flagged queues. No build step, no libraries, no data egress.

## Key notes
- Only two metrics are computed; every number has an ⓘ showing the exact formula and inputs.
- **Avg accuracy = 100 − MAPE** (a plain mean of Actual÷Fcst cancels over/under-forecasts and overstates accuracy).
- Display of `forecast offered (Simple)` is rounded to 2 dp — the calculation uses full precision.

See `IMP_DOCS/handoff.md` to continue development.
