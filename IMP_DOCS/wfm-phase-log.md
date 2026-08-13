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

## 2026-08-14 — Phase 2 step 2: the offline rig, and the deterministic decision layer

### Offline rig — the real SQL path, without the VPN

`results/offline_source.py` mirrors the source spreadsheet into SQLite and hands the engine a
cursor that speaks enough T-SQL (`SELECT TOP n` → `LIMIT n`) for `data_access.fetch_wfm_context` to
run **its own queries unchanged**. Faking the context would have left the SQL layer untested
exactly where a widened `_HISTORY_COLS` can break it.
`results/run_offline_investigation.py` drives a full investigation from it, with `--llm` optional
(the model APIs are public internet; only SQL needs the VPN).

Which local file matters, measured rather than assumed:

| File | Rows | Queues | Verdict |
|---|---:|---:|---|
| `Input_To_ML_20260706110242.csv.xlsx` | 7,350 | 42 | **contains no Indonesia at all** — cannot run the regression case; Voice-only |
| `SA_INDONESIA_CLIENT.xlsx` | 138,529 | 427 | the extract behind `Input_To_ML_Full`; 5 channels, 4 offerings, includes the regression queue |

The larger file is the default. Its header row is only partly labelled, so its columns are mapped
by **position** against the known schema (it is the `Input_To_ML` schema minus `Priority`), and the
loader refuses rather than guesses if the column count ever stops matching.

Two honest limits of the rig: `dbo.CQN_Mapping` does not exist locally, so channel grouping falls
back to the locality proxy; and in this extract the regression queue is the one of 427 whose scope
columns are blank, so its ladder stops at Country. **Live SQL validation is still required.**

### `wfm/rca_decision.py` — what may be claimed

Runs on the Phase 1 evidence and **before** the model, and is re-imposed on the response afterwards
by `business_report_generator.apply_decision`.

- **`miss_category`** — `FORECAST_BASELINE_FAILURE`, `FORECAST_RESPONSE_FAILURE`,
  `CALENDAR_RESPONSE_FAILURE`, `DRIVER_RESPONSE_FAILURE`, `DEMAND_EVENT`, `COMPOUND_MISS`,
  `DATA_LIMITATION`. Decided from the evidence, never by the model.
- **`evidence_class`** — `PRIMARY_DRIVER` / `SECONDARY_CONTRIBUTOR` / `CONTEXTUAL_FACTOR` /
  `UNCONFIRMED_SIGNAL` / `REJECTED`, ranked on total evidence rather than on the model's order or a
  raw coefficient.
- **Direction coherence** — a mechanism that pushes demand the wrong way for this miss is rejected
  outright, whatever else supports it. This is the automated form of the check an earlier engine
  failed when it blamed a demand-suppressing holiday for a busier week.
- **Contradiction resolution** — `supported` / `mixed` / `rejected`, with the contradicting
  evidence named. Two explanations can no longer ship as "Verified" while disagreeing.
- **Confidence** — evidence strength over six weighted dimensions (mechanism strength, history
  depth, absence of contradiction, forecastability, driver coverage, presence of the evidence the
  explanation depends on). A tiny sample cannot raise it.
- **Criticality** — severity, deliberately independent: the absolute contact gap sets the band and
  a large relative gap can lift it one step, so a small queue with a huge percentage cannot
  outrank a large queue with a real staffing hole.
- **Evidence index E1–E17** — every claim traces to a metric, a window and an availability
  statement.

The governing rule is enforced in code: a mechanism is only a response failure where a signal
existed **before** the week **and** has behaved repeatably for that queue.

### Prompt, API and UI

- `prompts.py` gains a section stating the decision is already made: the model may not change
  `miss_category`, re-rank mechanisms, promote a rejected one, or compute any number. It also
  carries the exact wording to use for `absent` / `sparse` / weak / lagged drivers, the calendar
  rules, the weekend rule, and a ban on unsupported service-level claims.
- The response gains `miss_category`, `forecastability`, `root_cause_sentence`,
  `why_this_happened`, `criticality`, `confidence_detail`, `evidence_index`,
  `forecast_response_diagnostic`, `driver_diagnostics`, `weekend_diagnostic`,
  `unconfirmed_signals`, `wfm_action` — all **additive**. `cause_type` and `status` keep their
  meanings; `evidence_class` is attached alongside them. All 12 legacy keys verified present.
- `rca_console.html` gains WFM-only panels in the section 26 order (Root Cause, Confidence &
  Criticality, Why This Happened, Statistical Evidence, Forecast Response, Driver Evidence, then
  history/rejected/missing and WFM Action). `renderDecisionCard()` — `?mode=spec` — is untouched,
  and the panels degrade to the legacy layout against an older backend.

### Three defects the semantic tests caught

1. **`adequate` for a plan that moved away from the expected level.** When the implied change was
   ~0, any forecast movement was called adequate. A plan that drifts a long way from the expected
   level when nothing asked it to has still failed; now classified `wrong_direction`.
2. **A blank `Country` reported "no holiday".** Unresolvable countries now return
   `available: false` with a reason — "holiday effects were NOT checked" is not the same claim as
   "no holiday applies", and this is a live path (one queue of 427).
3. **A fixed COMPOUND_MISS sentence asserted a response failure** even when the second mechanism
   was an unforeseeable demand event. The sentence is now composed from the mechanisms present.

Two further "failures" were fixture bugs where the engine was right and the test was wrong: a
momentum fixture that reset every cycle (so momentum genuinely had never followed through) and a
staircase whose tail sat mid-plateau. Both are documented in the test file so the next reader does
not "fix" the engine to match a bad fixture.

**Validation:** deterministic 148/148, semantic 51/51, smoke 11 passed / 0 failed / 1 skipped,
`compileall` clean, payload and response both serialise with SQL unreachable, `?mode=spec`
untouched (`spec_engine` does not reference the decision layer).

---

## Open items

| Item | Where | Status |
|---|---|---|
| `miss_category` / `evidence_class` additive taxonomy | Phase 2 §5–§7 | **done** |
| Deterministic contradiction resolution + direction coherence | Phase 2 §8–§9 | **done** |
| Confidence integration, deterministic criticality (miss size × queue volume) | Phase 2 §17–§18 | **done** |
| Evidence-class ranking and evidence IDs (E1–E17) | Phase 2 §19, §23 | **done** |
| Prompt update — model narrates, never overrides | Phase 2 §24 | **done** |
| Response serialisation, additive, `back_compat` intact | Phase 2 §25 | **done** |
| WFM UI panel restructure (spec renderer untouched) | Phase 2 §26 | **done** |
| 12 semantic regression cases + Indonesia regression | Phase 2 §27–§28 | **done** (51 checks) |
| Waisak/Vesak transliteration variants | Phase 2 §4 | open — needs a mapping the source does not provide |
| CQN mapping absent offline (locality proxy used) | offline rig | open — resolves with live SQL |
| Confidence ordering breaking check L3 | baseline finding | open |
| Drift total span convention (`slope × n`) | baseline finding | open |
| `seasonality` baseline includes the target week | baseline finding | open |
| **Live SQL + live LLM validation** | Phase 2 §29 | **blocked — no VPN** |
