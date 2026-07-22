# Design Choices — Demand Pattern RCA Console

Why the tool is built the way it is. Read this before changing metrics, charts, or the parser.

## Guiding constraints (from the client scope)
- **Single self-contained HTML file. No external libraries, no CDN, no build step.** The XLSX reader, CSV/TSV parser, filters, metrics and charts are all hand-rolled so the file runs from `file://` or behind Kong with zero dependencies. Keep it that way — do not add a framework.
- **The engine never invents numbers.** Only two metrics are computed, both rule-based. Every figure shown has an ⓘ that reveals the exact formula and inputs. Any narration/LLM layer (on-prem LLaMA) is a *later* phase and must not compute.

## The two metrics (do not add more without sign-off)
| Metric | Formula | Notes |
|---|---|---|
| **Forecast Accuracy** | `Actual_Offered ÷ fcst_offered × 100` | Forecast = `fcst_offered` (ML). |
| **Plan Adherence (ML/Manual)** | `ABS(1 − Actual_Offered ÷ fcst_offered) × 100` | Blank if no actual; the current Excel-system formula. |
- Flag rule: Plan-Adherence deviation **> band %** (default ±10). Equivalent to accuracy outside ±band.
- Rows with **no/zero forecast** are data gaps — never scored, never shown as results, counted separately.

## "Avg Accuracy" — the important fix
The old tile averaged `Actual÷Fcst` across rows. Because over- and under-forecasts scatter around 100% and **cancel**, it read ~99% even on genuinely poor data — misleading.
**New definition:** `Avg accuracy = 100 − MAPE`, where MAPE = mean of the per-row absolute % error, which is **exactly the Plan-Adherence deviation** already computed. Clamped at ≥ 0.
- Ties directly to a metric the business already trusts.
- On the full 138,775-row file this is **77.1%** (vs the bogus ~99%).
- Same logic drives the Dashboard's weekly-accuracy line: `100 − mean(deviation)` per fiscal week.

## Display rules
- `fcst_offered` is surfaced to users as **"forecast offered (Simple)"** and formatted to **2 decimals** everywhere it is shown (report input row, evidence trail, math modal). The **calculation still uses full precision** — only the display is rounded, so formulas never break.
- `Actual_Offered` stays integer; accuracy/adherence stay at 1 dp.

## Filters
10 business dimensions, in this fixed order: Fiscal_Week, Region, SubRegion, Country, Forecast_name, Forecaster, Offering, Projection_plan_name, channel, business_org. Excel-style multi-select with search; "(All)" = no constraint. The same set drives the volumetrics/dashboard (`VOL_DIMS = FILTER_FIELDS`).

## Dashboard & charts — applied the `dataviz` method
- **Form first, colour last.** Trends → area+line; magnitude comparisons → ranked horizontal bars; distribution → labelled status bars.
- **No dual-axis.** Volume and accuracy are two *separate* single-series charts, never two y-scales on one plot.
- **No cycled categorical hues.** Bars use a single sequential **blue** (`--accent`); the deviation spread uses the reserved **status palette** (good/warning/serious/critical) and every band carries a **text label**, so meaning is never colour-alone.
- **Colour matches the app** (`--accent #2d6cdf`, `--accent-2 #12986f`, `--warn`, `--danger`) which sits on the validated blue + status ramps; surfaces are the console's light panels.
- Charts are **inline SVG (trends) / HTML bars** — consistent with the no-library rule. Trends ship a JS **crosshair + tooltip**; bars use native hover titles + direct value labels.
- Everything is **reactive to the active filters** — the dashboard re-renders on every `applyAndScan()`.

### Volumetrics "EPIC" panel — visibility rules
- Dimension cards show **row counts** for the top members, **not % of total** — a share was meaningless for high-cardinality dimensions (325 fiscal weeks ⇒ every value rounded to "0%"). The card's headline is the **distinct-value count** (shown large); bars are scaled relative to the top member within that dimension.
- **Fiscal_Week is excluded** from the dimension grid — it's a time axis already summarised by the KPI hero (span + count) and the two week-trend charts, so a card listing 3 arbitrary weeks was redundant clutter.
- Layout is deliberately roomy: top-3 members per card, larger figures, header dividers, hover lift — tuned for legibility over density.

### Known trade-offs / future polish
- Trend charts plot every fiscal week present (up to 325 points); fine as a dense sparkline. A brush/zoom is a future nice-to-have.
- Full crosshair is on the two trend charts only; bars rely on native tooltips. A shared hover legend is a later enhancement.

## Timeline / Gantt
The build Gantt lives both **in the app** (Timeline tab, scoped under `#tab-timeline`) and as a **standalone** `rca_timeline.html` (theme-aware light/dark). Keep the two in sync when phase status changes. Today marker and KPIs are currently hard-set to **22 Jul** — update them as the project moves.
