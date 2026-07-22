# TODO — Demand Pattern RCA Console

Deploy **30 Jul 2026** · last dev day **29 Jul**. Ordered by priority.

## P0 — critical path to the mockup
- [ ] **P4 · Phase-1 digest** — one-click export of *all* flagged queues (multi-queue scan → top-N → printable/report page). Main remaining build.
- [ ] **P6 · Validation with Prashant / SME** on the full real dataset — must land by **28 Jul** to keep a buffer day.
- [ ] **Confirm the adherence band** — ±10% vs ±15%, and whether it tiers by `Volume_Category`. Blocks P6 tuning.
- [ ] **P7 · Demo packaging + dry run** (28–29 Jul) — walkthrough script, rehearsal, digest export sanity check.

## P1 — correctness / data questions to close (probing layer)
- [ ] Source of truth for adherence — **Offered vs Handled**?
- [ ] On **Projection_plan restatement** mid-cycle, is the miss forgiven? (auto-probe already flags restated queues)
- [ ] Exact meaning of **ASU** (Planned/Actual).
- [ ] Treatment of **holiday weeks** (`Holiday_Count > 0`).
- [ ] Per-**Offering** / per-**Channel** acceptable bands, if any.

## P2 — dashboard / UX polish (post-deadline OK)
- [x] High-cardinality dimension cards showed 0% shares — now show row counts; Fiscal_Week dropped from the grid; panel made bolder/cleaner. (2026-07-22)
- [ ] Trend charts: optional brush/zoom for the 325-week span; shared hover legend across the two trend charts.
- [ ] Export the Dashboard as a PNG/PDF for the digest.
- [ ] Consider a light/dark toggle for the console itself (timeline already themes; console is light-only).

## P3 — architecture phase (out of 30 Jul scope)
- [ ] On-prem **LLaMA narration** layer (explains drivers; never computes).
- [ ] Wire the two metrics as **MCP tools** + SQL metric views.
- [ ] RAG over the probing KB to auto-surface known causes on matching queues.
- [ ] Let confirmed KB rules feed back into flag suppression / re-flagging.

## Done ✓ (2026-07-22)
- [x] 10-dimension filters
- [x] `fcst_offered` → "forecast offered (Simple)", 2-dp display (calc intact)
- [x] Stray `''` after Fiscal Week removed
- [x] Avg Accuracy → 100 − MAPE (77.1% full file)
- [x] EPIC volumetrics + **Dashboard** tab with graphs
- [x] Data-driven probing auto-probes + category + captured context
- [x] Deadline **Gantt** embedded (Timeline tab) + standalone `rca_timeline.html` refreshed
- [x] Project folder + IMP_DOCS
