# WFM RCA upgrade — running phase log

Branch: `test` (off `spec-v2-refactor` @ `74f46c5`). Dated log of each step of the
"why did the forecast miss" programme, so the sequence of decisions is recoverable without
reading `git log`. The engine's current shape lives in
[wfm-rca-engine.md](wfm-rca-engine.md); this file records how it got there and what is still open.

Governing rule throughout: **Python determines what the data proves, the decision layer determines
what may be claimed, the LLM determines how to explain it.**

---

## 2026-08-13 — Baseline measurement (before any change)

Ran the WFM engine on `SA Indonesia Client Basic` / FW202716 with `gemini-3.5-flash` against live
SQL and independently recomputed every figure it produced.

- [WFM_MATH_AND_TOOL_EVIDENCE.md](../WFM_MATH_AND_TOOL_EVIDENCE.md) — call chain, formulas, and a
  72-assertion independent check (`results/verify_indonesia_math.py`, 72/72 pass).
- [WFM_GEMINI_UI_OUTPUT.md](../WFM_GEMINI_UI_OUTPUT.md) — the model output as the console renders it.

**Findings that set the Phase 1 agenda:**

| Finding | Consequence |
|---|---|
| Arithmetic reproduces exactly across all 72 checks | the calculator was never the problem |
| `Final_upp_units` z-score of **23.33 computed from n=2** (3 non-NULL weeks in 157) armed the `installed_base_change` precondition in `skeptic.py`, shipping a cause at 85 % confidence | needed a coverage discipline, not a formula fix |
| Confidence did not descend with rank (82 → 95 → 85 → 80) because the statistical override inserts its own rank 1 | breaks check L3 in `results/run_llm_ranking.py`; still open |
| Drift total uses `slope × n` where the window spans `n − 1` intervals (−127.95 vs −118.11) | definitional, ~8 % overstatement; still open |
| `seasonality` includes the target week in the baseline the target is compared against | definitional; still open |

---

## 2026-08-13 — Phase 1: the deterministic "why" layer

Four new modules, wired into `derive_wfm_features` in dependency order. No taxonomy, prompt or UI
change, so nothing the existing UI renders could move.

- **`lag_analysis.py`** — Spearman at lags 0/1/2/4/8 in two families (LEVEL `driver(t−k)` vs
  `Actual(t)`, CHANGE `Δdriver(t−k)` vs `ΔActual(t)`). Same thresholds as `correlation_engine`
  (≥12 pairs, |ρ| ≥ 0.5) so two modules cannot disagree about one driver. Every candidate
  re-estimated on each half of its own history; a sign flip between halves blocks promotion to
  evidence. Coverage classes `populated / sparse / absent` replace the single "driver rejected",
  so *"we could not test this"* stops being reported as *"this driver does not affect demand"*.
  The target week is excluded from every estimate — `correlation_engine` does not exclude it.
- **`forecast_response.py`** — demand-side and forecast-side evidence separated; the miss split
  against a robust expected level so that
  `forecast_side + demand_side = actual − forecast` exactly; the movement test
  (`Actual(t−k)→Actual(t)` against `Forecast(t−k)→Forecast(t)`) flagging opposed directions;
  response adequacy judged against **what the expected level implied the plan needed to do**,
  never against the outcome; and the forecastability gate
  `PREDICTABLE / PARTIALLY_PREDICTABLE / LOW_PREDICTABILITY`, where a signal only counts as
  predictable if it has behaved repeatably **for that queue**. This is what stops "actual exceeded
  forecast" reading as a forecasting failure every time.
- **`holiday_response.py`** — pre / holiday / post phases across H−2…H+2, every phase effect
  measured from the queue's own non-holiday level. Direction is never assumed, which is how an
  earlier engine blamed a holiday for a week that ran *busier*. Forecast capture:
  `captured / under_reacted / over_reacted / wrong_direction / delayed / inconsistent_history /
  not_testable`, and an inconsistent history blocks blame instead of picking a side.
- **`data_granularity.py`** — inspects the rows rather than assuming. Confirms this source is
  weekly: one row per fiscal week, no daily actual or forecast, and `Monday`…`Sunday` are 0/1
  **holiday flags**, not daily volumes. Weekend volume effects therefore cannot be isolated and the
  module says so verbatim. The testable half of the weekend question is kept: the flags reveal
  which *day* a holiday fell on, so holiday-on-weekend and holiday-adjoining-weekend are reported
  as calendar structure only.

**Supporting changes**

- `common.week_ordinals()` — `Fiscal_Week` is YYYYWW, so the week before `202701` is `202652`, not
  `202700`. Plain subtraction silently dropped a pair at every fiscal-year boundary (~3 per lag
  over 157 weeks). Year length is taken from the data, so a 53-week year needs no special case.
- `holiday_calendar.holiday_span()` — additive; `holiday_context()` untouched because `spec_engine`
  depends on it.
- `data_access._HISTORY_COLS` widened additively: `Final_upp_units` (so its real coverage is
  measurable), `Monday`…`Sunday`, `Week_Ending`.
- `investigation_engine._payload` — **fixed a live bug.** `prompts.py` has carried a
  "STATISTICAL EVIDENCE" section telling the model to reason from `STATISTICAL_EVIDENCE.findings`
  since that section was written, but the payload never included the block. The model was being
  instructed to use data it could not see.

**Validation:** `results/test_wfm_diagnostics.py` 121/121; existing `smoke_test_modules.py`
unchanged at 11 passed / 0 failed / 1 skipped; `compileall` clean; payload still serialises with
SQL unreachable, every new block degrading to `available: false` with a stated reason.

**Verified on the real case:** FW202716 carries `Holiday_Count = 0` and now resolves to
`post_holiday` from the two holidays in FW202715 — an effect the WFM engine was previously blind to.

---

## 2026-08-14 — Phase 2 step 1: holiday event normalisation

`wfm/holiday_events.py`. Counting raw holiday NAMES overstated how much calendar pressure a week
was under, which made a holiday explanation look stronger than the calendar justified.

### The brief's premise was wrong, and the data says so

Phase 2 §4 asks for events to be grouped by the master's `Aggregate_Group`. Measured on
`FC_RCA_Holiday_Master_Production.xlsx` (12,197 active rows), **`Aggregate_Group` groups COUNTRIES,
not holidays**:

| Group | Distinct holiday names | Countries |
|---|---:|---:|
| `eCIS` | 162 | 2 |
| `AMER_GROUP` | 64 | 2 |
| `ROLA` | 37 | 1 |

Grouping events by it would merge **Columbus Day with Thanksgiving Day**, and Boxing Day with
Bakrid. It is left doing its real job — resolving an aggregate `Country` value to member countries
in `holiday_calendar._resolve_country`. A regression test now guards against reintroducing it as an
event family.

`Semantic_Family` **is** an event-family field but is populated on only **99 of 12,197** rows
(Lunar New Year, Diwali). It is used where present and cannot be relied on otherwise.

### The duplication that actually exists

| Pattern | Count | Handling |
|---|---:|---|
| Exact duplicate rows (country+week+name+date) | 1,495 | collapsed by the extract loader |
| One name spanning several dates in one week (Bahrain Eid al-Adha × 4 days) | 511 buckets | **one multi-day event**, day count retained |
| Same country + name + year at different dates | 620 | kept distinct and **flagged for review**, never merged |

### How event identity is decided

`Semantic_Family` when present; otherwise a key of **modifier + significant core tokens**. Filler
words (`day`, `holiday`, `of`, `the`, `public`, `national`…) are dropped so
`Ascension of Jesus Christ` and `Ascension Day of Jesus Christ` reduce to the same key — but a
MODIFIER prefix (`after`, `joint`, `eve`, `second`, `observed`…) is kept, so a bridge day is never
folded into the holiday it adjoins. Instances are then grouped by **date adjacency**: consecutive
dates form one occurrence with a day count, and two occurrences of one event more than a week apart
stay separate and carry `possible_misdating` for review.

Verified on real data:

- Bahrain FW202619: **4 rows → 1 event, 4 days.**
- Indonesia: `Ascension of Jesus Christ` (2026-05-14, source) and
  `Ascension Day of Jesus Christ` (2026-05-27…29, `Type = Derived from INPUT_TO_ML`,
  `Requires_Review = YES`) share an event key but stay **two occurrences 13 days apart**, both
  flagged `possible_misdating`. The later set is also collapsed from 3 rows to **1 event of 3 days**.
- Bridge days remain distinct: `joint:waisak`, `joint_after:ascension`, `after:ascension`.

`load_holiday_master.py` now dedupes on **name AND date** rather than name alone — deduping on name
discarded the extra days, so a four-day Eid looked identical to a one-day holiday. It also carries
`Semantic_Family` through. The extract was rebuilt from the production workbook (12,197 rows,
6,698 country-weeks).

`holiday_response` now reports `events`, `events_reaching_target_week` and `event_summary`, and its
narrative quotes canonical event names rather than raw spellings. `event_count` sits beside
`raw_name_count` so the removed inflation stays auditable.

**Validation:** `results/test_wfm_diagnostics.py` 148/148 (27 new event checks); existing smoke
suite unchanged.

### Known limitation

Spelling variants of the same festival that share no tokens are not merged — `Waisak Day` and
`Vesak Day` remain separate events. Merging them would need a transliteration map, and inventing
one is exactly the guesswork §4 forbids. They surface in `needs_review` when the master flags them.

---

## Open items

| Item | Where | Status |
|---|---|---|
| `miss_category` / `evidence_class` additive taxonomy | Phase 2 §5–§7 | not started |
| Deterministic contradiction resolution + direction coherence | Phase 2 §8–§9 | not started |
| Confidence integration, deterministic criticality (miss size × queue volume) | Phase 2 §17–§18 | not started |
| Evidence-class ranking and evidence IDs | Phase 2 §19, §23 | not started |
| Prompt update — model narrates, never overrides | Phase 2 §24 | not started |
| Response / Decision Card serialisation | Phase 2 §25 | not started |
| WFM UI panel restructure (spec renderer untouched) | Phase 2 §26 | not started |
| 12 semantic regression cases | Phase 2 §27 | not started |
| Confidence ordering breaking check L3 | baseline finding | open |
| Drift total span convention (`slope × n`) | baseline finding | open |
| `seasonality` baseline includes the target week | baseline finding | open |
| **Live SQL + live LLM validation** | Phase 2 §29 | **blocked — no VPN** |
