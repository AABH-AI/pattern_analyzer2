# The mathematics of the RCA engine

Every formula, threshold and data path this system uses. Extracted from the code with
`results/extract_maths.py`, not written from memory — an earlier audit in this project reported
thirteen things missing because it trusted documentation over the payload, and this document exists to
be the thing that is checked rather than the thing that is trusted.

Written **2026-08-21** against branch `test3`. **90 numeric constants** live in `backend/wfm/`; every
one is named, commented at its definition, and listed here.

---

## Part 1 — Where the data comes from

### The single source

| | |
|---|---|
| Server | `10.10.9.75` |
| Database | `Playground` |
| Table | `dbo.Input_To_ML_Full_138_Trimmed` |
| Size | **114,436 rows · 32 columns** |
| Span | FW202401 – FW202908 (178 fiscal weeks) |
| Queues | 427 distinct `Forecast_name` |
| Access | FastAPI + pyODBC (`backend/sql_backend.py`), ODBC Driver 17/18 |

Two earlier loads still exist and are **not** what the engine reads — `dbo.Input_To_ML` (66,612 rows)
and `dbo.Input_To_ML_Full` (88,816). The live table is whatever `backend/config.json` names; check
there rather than trusting any figure quoted in a document.

Supporting tables:

| Table | Role |
|---|---|
| `dbo.Holiday_Master` | holiday dates by country and fiscal week, 36 distinct `holiday_type` values |
| `dbo.Holiday_Semantic_Group` | 23 event families, so one holiday spelled several ways is counted once |
| `dbo.Holiday_Name_Alias` | raw name → group, with `country_scope` |
| `dbo.Holiday_Name_Pair_Review` | 8 recorded DO-NOT-MERGE decisions, 185 pairs still open |
| `dbo.CQN_Mapping` | authoritative Combined Queue names, when loaded |

### The four numbers everything else is built on

| Column | Meaning |
|---|---|
| `Actual_Offered` | contacts that actually arrived — the measured truth |
| `fcst_offered` | the plan for that week |
| `Planned_ASU` / `Actual_ASU` | installed base, the population that generates contacts |
| `Final_Units` | shipments, a candidate leading driver |

**A caution the code enforces:** `Monday`…`Sunday` are **holiday flags**, not daily volumes. There is
no daily `Actual_Offered` anywhere in this source, so no per-day demand figure can be derived. This is
why the weekend question reports "cannot be isolated from fiscal-week totals" rather than guessing.

### What is fetched per investigation

`backend/wfm/data_access.py::fetch_wfm_context` issues these, all parameterised:

| Key | Query | Why that window |
|---|---|---|
| `history_104` | up to 104 prior weeks for the queue | two years, so a same-week-last-year comparison exists |
| `history_forward` | weeks after the target | lets a rebound be measured |
| `channel_sibling_rows` | target + prior week, all channels in scope | week-over-week channel shift |
| `channel_mix_rows` | **all** weeks, all channels in scope | long-run rotation; a 15-point drift over 3 years is invisible in two weeks |
| `ladder` | same week aggregated at 5 scope levels | where the miss is visible |
| `cqn_names` | Combined Queue names for the queue | authoritative grouping when available |

---

## Part 2 — The two metrics, and nothing else

Everything in this system reduces to these. **The math is never changed.**

### Forecast Adherence (signed)

```
adherence_pct = (1 − actual / forecast) × 100
```
`backend/wfm/common.py::adherence_pct`

**Negative means actual ran ABOVE forecast** (under-forecast). Positive means the plan was too high.
Never scored when `forecast` is zero or missing — the result is `None`, not a zero.

A week is investigated when `|adherence| > band`, default **10.0%** (`DEFAULT_BAND_PCT`).

### Forecast Accuracy

```
MAPE      = mean(|actual − forecast|)  /  mean(actual) × 100
accuracy  = 100 − MAPE
bias      = mean(actual − forecast)
```
`backend/wfm/statistical_evidence.py::_accuracy_block`

**The sign convention is deliberately opposite to adherence and the two are reported side by side.**
Error is `actual − forecast`, so a *negative bias* means the forecast ran *high*. Both are shown so
nobody has to infer a direction.

Why 100−MAPE and not a naive average: an earlier version averaged signed accuracy and reported ~99%
on a file whose over- and under-forecasts cancelled out. The real figure was 77.1%.

Windows: **13** weeks (`RECENT_WEEKS`), **52** (`YEAR_WEEKS`), **104** (`LONG_WEEKS`). Minimum **6**
points (`MIN_N`) or the block reports "insufficient history" instead of a number.

---

## Part 3 — The statistical measures

All in `backend/wfm/statistical_evidence.py`. Each is reported with a plain-English reading, and each
states when it cannot be computed rather than returning a silent zero.

### Coefficient of Variation

```
CV = σ / μ        on ACTUAL demand
```

The single most useful number for deciding whether a miss is the forecaster's fault. A queue whose own
demand swings 40% week to week **cannot** be forecast to ±10%, and blaming the plan there is wrong.

| Band | Constant | Meaning |
|---|---|---|
| CV > 0.30 | `CV_VOLATILE` | genuinely hard to forecast |
| CV < 0.15 | `CV_STABLE` | stable demand, so a miss is the plan's fault |

### Trend — is demand moving?

Ordinary least squares slope of demand against week index, with the coefficient of determination:

```
slope = Σ((xᵢ − x̄)(yᵢ − ȳ)) / Σ((xᵢ − x̄)²)
R²    = 1 − SS_residual / SS_total
```

`TREND_R2_MEANINGFUL = 0.30` — below this a slope is noise, and the engine says so rather than
reporting a direction.

### Drift — is the ERROR moving?

The same OLS slope, but of **adherence** over time rather than demand.

Distinct from Trend, and the distinction matters: a queue can have flat demand and drifting adherence
(the plan is decaying), or rising demand with zero drift (the plan is keeping up). Drift is the one
that says *this will keep getting worse until the baseline is rebuilt*.

`DRIFT_MATERIAL_PCT = 0.25` adherence points per week — over 13 weeks that is more than 3 points.

### Momentum

```
momentum = (mean of last 4 weeks / mean of prior 9) − 1
```
Material at **10%** (`MOMENTUM_MATERIAL_PCT`). Answers "was demand already moving before this week",
which decides whether the plan *could* have reacted.

### Seasonality

```
seasonal_index = mean(actual for this fiscal week across prior years) / mean(all weeks)
```
Material at ±**0.15** (`SEASONAL_INDEX_MATERIAL`). Needs at least 2 prior years
(`MIN_PRIOR_YEARS`), otherwise it reports how many it had.

### Plan vs seasonal norm

The plan for this week against what this week of the year normally brings. Material at **0.25**
(`PLAN_VS_NORM_MATERIAL`). This is frequently the strongest single item on a card, because it separates
*the demand was odd* from **the plan was odd**:

> "The plan was set at 64 contacts for a week that has averaged 122 across 3 earlier years. Demand of
> 152 is in line with the week's own history, so **the plan is the outlier, not the demand**."

### Outlier detection — median and MAD, not mean and σ

```
MAD          = median(|xᵢ − median(x)|)
modified z   = 0.6745 × (x − median) / MAD
outlier when |modified z| > 3.5
```

`OUTLIER_MOD_Z = 3.5`. The `0.6745` rescales MAD to a standard-deviation equivalent.

**Why not mean and σ:** with a mean/σ rule a single huge spike inflates σ enough to hide itself. The
median/MAD pair is robust to exactly the point it is looking for. When `MAD = 0` the test is abandoned
rather than dividing by zero.

### Correlation — both measures, deliberately

```
Pearson  r   = cov(x,y) / (σx·σy)                    linear
Spearman ρ   = Pearson r computed on RANKS           monotonic
```

| | |
|---|---|
| Pearson | `statistical_evidence.py::_pearson`, `driver_gate.py`, `lag_analysis.py` |
| Spearman | `correlation_engine.py::_spearman`, `lag_analysis.py` |

Both are reported because they disagree informatively: Spearman survives a non-linear but consistent
relationship that Pearson misses, and a large gap between them is itself a finding.
`RANK_LINEAR_TOLERANCE = 0.25` — a gap wider than this is called out.

Gates: `MIN_ABS_R = 0.30`, `MIN_N = 30` (`driver_gate.py`); `MIN_PAIRS = 12`, `MIN_STRENGTH = 0.5`
(`lag_analysis.py`).

**What a coefficient is never allowed to say:** a sub-threshold r does **not** mean "this is not a
driver". It means *not confirmed*. Direction and strength are reported separately, and a rejection at
the gate no longer terminates the analysis.

### Lag scanning

Lags **0, 1, 2, 4, 8** for hypothesis-selected drivers; the gate scans **0–13** (`MAX_LAG = 13`) for
flow measures. Stability is tested by splitting the history in half and comparing:
`STABILITY_MIN_PAIRS = 8` per half, `STABILITY_TOLERANCE = 0.25`.

ASU is a **stock** measure and is tested contemporaneously on purpose — lagging an installed-base
figure asks a question that does not mean anything.

---

## Part 4 — Decomposition: making the gap add up

### Miss decomposition

```
expected              = median demand for this week (same week, prior years, or last 13)
plan_gap              = forecast − expected
demand_gap            = actual − expected
demand_share_of_gap   = |demand_gap| / (|plan_gap| + |demand_gap|)
```

Published with `reconciles: true/false`. **This is an identity, not an apportionment** — if the parts
do not sum to the whole, the engine says so rather than presenting a tidy split that hides a residual.

### ASU decomposition — population versus rate

```
planned_rate   = forecast / Planned_ASU
actual_rate    = actual   / Actual_ASU

population effect = (Actual_ASU − Planned_ASU) × planned_rate
rate effect       = Actual_ASU × (actual_rate − planned_rate)
```

The two sum **exactly** to `actual − forecast`. Verified on a live card: `+1,366` and `−5,294` summing
to `−3,929`, the whole variance, with nothing unexplained. It answers whether more machines arrived, or
the same machines called more often — a different remedy in each case.

---

## Part 5 — The calendar

`backend/wfm/holiday_response.py`, `holiday_events.py`

### Phases

A window of ±**2** weeks (`SPAN_WEEKS`) around a holiday, resolved to `pre_holiday`, `holiday` or
`post_holiday`. A week with `Holiday_Count = 0` can still be a phase week — the effect reaches in from
an adjacent week, and `zero_count_but_adjacent` records that.

```
phase_effect = (median actual in phase weeks / median actual in non-holiday weeks − 1) × 100
consistency  = share of phase instances that moved the same way
```

| Constant | Value | Gate |
|---|---|---|
| `MIN_PHASE_INSTANCES` | **4** | fewer and the phase is "not measurable", not "no effect" |
| `MATERIAL_SHARE` | 0.10 | effect must be ≥10% off the non-holiday level |
| `CONSISTENT_SHARE` | 0.70 | ≥70% moving the same way to be called consistent |
| `HIGHLY_REPEATABLE_SHARE` | 0.85 | |
| `LEANS_SHARE` | 0.50 | at or below this, direction is no better than a coin flip |

### Did the plan capture it?

```
capture_ratio = plan movement for those weeks / historical demand effect
```

| Ratio | Reading |
|---|---|
| ≥ 0.50 (`CAPTURE_TOLERANCE`) | captured |
| > 1.75 (`OVER_CAPTURE`) | over-reacted |
| below tolerance | not captured |

### Standing bias, which is a different question

`BIAS_SHARE = 0.70`, `BIAS_MATERIAL_PCT = 10.0`, `BIAS_WIDENING_PCT = 5.0`.

A week can sit inside the "captured" tolerance every single time while the adjustment rule drifts
year over year. Capture judges *this* week; bias judges the *rule*. They can disagree, and both are
reported.

### Weekday and weekend structure

Because only holiday **flags** exist per day, the weekend question is answered by comparing whole
weeks grouped by *which weekday the holiday fell on* — not by daily volume, which does not exist.

Measured on a live queue, and the reason the distinction is kept:

| Holiday pattern | Weeks | vs no-holiday week |
|---|---|---|
| **adjoining** the weekend (Fri/Mon) | 12 | **−40.6%** |
| **on** the weekend (Sat/Sun) | 4 | **−24.8%** |

A holiday adjoining the weekend costs nearly 16 points more than one falling on it, because a weekend
holiday lands on days already non-working.

### Two holiday effects, and why they differ

| Source | Population | Statistic |
|---|---|---|
| `spec_engine::_holiday_effect_for` | every week with `Holiday_Count > 0` | **mean** |
| `holiday_response::phase_effect` | weeks the **calendar** marks as that phase | **median** |

Both are real and they legitimately differ — on one card, 29% against 11.93%. Each now publishes
`basis`, `measure` and `differs_from` so a reader can see why rather than concluding the engine cannot
count.

### Semantic grouping

23 curated event families over **3,142** master rows. Curated and not scored, because after a
same-country same-date pre-filter **276** name pairs remain and a string rule decides only **23%** —
and roughly half the rest are the *inverse* problem: different holidays sharing a date.

| | | |
|---|---|---|
| `Mid-Autumn Festival` | `National Day` | china, both 2023-10-01 |
| `Christmas Day` | `Quaid-e-Azam Day` | pakistan, both 12-25 |
| `new year's day` (Gregorian) | `New Year` (**lunar**) | near-identical names, different holidays |

A similarity threshold merges every one of those. The standing rule is therefore **when unsure, do not
merge**: failing to merge inflates an event count, wrongly merging invents a finding silently.

Adjacency: `ADJACENCY_DAYS = 1`, `SAME_OCCURRENCE_DAYS = 7`.

---

## Part 6 — Channel mix

`backend/wfm/channel_mix_rotation.py` (long-run) and `channel_migration_detector.py` (week-over-week)

Two modules answering two questions. The week-over-week detector asks *did volume shift between
channels this week*; it cannot see a structural drift, because 15 points spread over three years moves
almost nothing between adjacent weeks.

```
share(channel, window) = Σ actual for that channel / Σ actual for all channels × 100
change_pts             = share(last 13 weeks) − share(first 13 weeks)
offset_ratio           = min(|fall|, rise) / max(|fall|, rise)
```

| Constant | Value | Gate |
|---|---|---|
| `MIN_SHARE_MOVE_PTS` | **5.0** | smaller moves sit inside ordinary wobble |
| `MIN_OFFSET_RATIO` | **0.5** | the rise and fall must account for each other |
| `WINDOW_WEEKS` | 13 | |
| `MIN_WEEKS_PER_WINDOW` | 8 | two independent windows or no comparison |

Each channel's own weekly share standard deviation is computed so a genuine drift is separable from
wobble (`exceeds_own_noise`).

Measured on live data — **Voice is losing share to digital channels across regions**:

| Scope | Rotation | Points | Offset |
|---|---|---|---|
| APJ / CCC / China / Basic | Social Media → **Email** | 14.5 | 95% |
| Americas / United States / Basic | Voice → **Social Media** | 12.2 | 65% |
| APJ / IN / India / Pro | Voice → **Email** | 12.3 | 85% |
| NA Core scope | Voice → **Email** | 12.4 | 66% |

**What is claimed and what is not.** Share moving from one channel to another is **co-movement**, not
proof a contact was diverted — both could be driven by something else. The wording is always "share
moved from X to Y", never "X was diverted to Y", and the offset ratio is published so the reader can
judge how completely the two account for each other.

Grouped by `Region + SubRegion + Country + business_org`, **not** the CQN key: the signed-off CQN
definition includes channel, so grouping by CQN would put every channel in its own group and guarantee
nothing was ever found. Every result is labelled `is_cqn_proxy: true`.

---

## Part 7 — Confidence and criticality

### Confidence

Eight weighted dimensions, each gated (`backend/wfm/confidence.py`). `MISSING_FLOOR = 0.20` — a missing
dimension scores 0.20, not zero, because absence of a measurement is not evidence against a finding.
`REPEAT_FAMILY_INDEPENDENCE = 0.3` discounts corroboration from the same evidence family, so five
readings of one measurement do not compound into false certainty.

Cross-examination runs **before** confidence (`MAX_ITERATIONS = 3`), specifically so its result can feed
in. `_TOLERANCE = 0.02` in the skeptic absorbs display rounding in a cited figure.

### Criticality

`backend/wfm/fc_evidence.py::criticality`

| Constant | Value | Meaning |
|---|---|---|
| `MATERIALITY_FLOOR_CONTACTS` | **50** | below this, a percentage is arithmetic not a problem |
| `CRITICALITY_RELATIVE_LIFT` | 0.50 | gap ≥ half a typical week lifts a band |
| `CRITICALITY_PERSISTENCE_WEEKS` | 4 | a same-direction run this long also lifts one step |
| `MAJOR_DEVIATION_PCT` | 75.0 | |

A 300% miss on 12 contacts and a 12% miss on 40,000 are not the same event, and the materiality floor
is what stops the first outranking the second.

### The generation threshold

`GENERATION_THRESHOLD_PCT = 5.0` — **fixed, not configurable.** It is a worklist control only: a 40%
miss on 8 contacts still fails the materiality floor and is not promoted.

---

## Part 8 — Determinism

**Every number is computed in Python. The model writes prose only.**

| Parameter | Value | Why |
|---|---|---|
| `TEMPERATURE` | 0.0 | same input, same words |
| `TOP_P` | 1.0 | no nucleus truncation |
| `SEED` | 20260730 | fixed and recorded where the provider honours it |
| `DEFAULT_TIMEOUT_SECONDS` | 100 | `llm.timeout_seconds` overrides; 150 in config now |

Three model calls, all optional to the result:

1. **Narrative** — step 14, prose over finished figures
2. **Interrogation** — the WHY questions asked of the findings
3. **Summary** — on demand, cached per queue+week

If every call fails the investigation still completes: `status: "Incomplete"`, every figure, cause,
confidence score and recommendation present, only prose missing.

### Numeric grounding

`backend/wfm/narrative_prompt.py`. A number in model prose that is not in the inputs is a **hard
failure** — the whole narrative is discarded.

```
accept if  |written − supplied| ≤ max(1.0, 0.005 × |supplied|)      (|supplied| ≥ 1)
        or  written IS supplied rounded to some sensible precision
            AND |written − supplied| ≤ 0.05 × |supplied|
```

`ROUNDING_MAX_DRIFT = 0.05`, `_GROUNDING_MIN = 100`.

Two details, both added because a test found them:

- **The 5% drift cap.** `round(33790, −4)` is 30,000 — arithmetically a rounding, and 11% wrong. Being
  a rounding is necessary but not sufficient.
- **No floor of 1 below 1.** The floor exists so `26.5 → 27` passes, where 0.5% is only 0.13. Applied
  to a contact rate of 0.0018 it was accepting a written "0".

Expressing "rounded to a round number" as a *percentage* is the underlying error: that error is 1.3% at
3,929, 5% near 1,000 and 0.5% near 10,000, so no single percentage covers it without becoming wide
enough to admit inventions. `results/test_narrative_grounding.py` — **21/21**, and the invented-number
half is the real test.

---

## Part 9 — Every constant, by module

90 total. Full list with inline rationale at each definition site.

| Module | Constants |
|---|---|
| `channel_migration_detector` | `_MIN_OFFSET_SHARE` 0.6 · `_MAX_NET_SHARE` 0.25 |
| `channel_mix_rotation` | `MIN_SHARE_MOVE_PTS` 5.0 · `MIN_OFFSET_RATIO` 0.5 · `MIN_WEEKS_PER_WINDOW` 8 · `WINDOW_WEEKS` 13 |
| `common` | `DEFAULT_BAND_PCT` 10.0 · `WFM_HISTORY_WEEKS` 157 |
| `confidence` | `MISSING_FLOOR` 0.20 · `REPEAT_FAMILY_INDEPENDENCE` 0.3 |
| `correlation_engine` | `_MIN_WEEKS` 12 · `_MIN_STRENGTH` 0.5 |
| `cross_examination` | `MAX_ITERATIONS` 3 |
| `data_quality` | `_EXTREME_HIGH` 10.0 · `_EXTREME_LOW` 0.1 · `_MIN_WEEKS` 8 |
| `driver_gate` | `MIN_ABS_R` 0.30 · `MIN_N` 30 · `MAX_LAG` 13 |
| `fc_evidence` | `MISS_THRESHOLD_PCT` 5.0 · `MATERIALITY_FLOOR_CONTACTS` 50 · `CRITICALITY_RELATIVE_LIFT` 0.50 · `CRITICALITY_PERSISTENCE_WEEKS` 4 |
| `forecast_response` | `SHORT_WINDOW` 4 · `MID_WINDOW` 8 · `RECENT_WINDOW` 13 · `MIN_PRIOR_YEARS` 2 · `MIN_BASELINE_WEEKS` 6 · `UNUSUAL_SHARE` 0.20 · `NO_RESPONSE_RATIO` 0.10 · `UNDER_RESPONSE_RATIO` 0.50 · `OVER_RESPONSE_RATIO` 1.50 · `MOMENTUM_MATERIAL_PCT` 10.0 · `PREDICTABLE_CONSISTENCY` 0.70 · `PARTIAL_CONSISTENCY` 0.40 · `MIN_PRECEDENTS` 4 |
| `holiday_events` | `ADJACENCY_DAYS` 1 · `SAME_OCCURRENCE_DAYS` 7 |
| `holiday_response` | `SPAN_WEEKS` 2 · `MIN_PHASE_INSTANCES` 4 · `MATERIAL_SHARE` 0.10 · `CONSISTENT_SHARE` 0.70 · `CAPTURE_TOLERANCE` 0.50 · `HIGHLY_REPEATABLE_SHARE` 0.85 · `LEANS_SHARE` 0.50 · `MAGNITUDE_SPREAD_LIMIT` 2.0 · `OVER_CAPTURE` 1.75 · `BIAS_SHARE` 0.70 · `BIAS_MATERIAL_PCT` 10.0 · `BIAS_WIDENING_PCT` 5.0 |
| `lag_analysis` | `MIN_PAIRS` 12 · `MIN_STRENGTH` 0.5 · `RANK_LINEAR_TOLERANCE` 0.25 · `MISS_THRESHOLD_PCT` 5.0 · `MIN_MISS_PAIRS` 8 · `STABILITY_MIN_PAIRS` 8 · `STABILITY_TOLERANCE` 0.25 |
| `llm_client` | `DEFAULT_TIMEOUT_SECONDS` 100 · `TEMPERATURE` 0.0 · `TOP_P` 1.0 · `SEED` 20260730 |
| `narrative_prompt` | `_GROUNDING_MIN` 100 · `ROUNDING_MAX_DRIFT` 0.05 |
| `recursive_why` | `MAX_DEPTH` 6 · `MIN_EVIDENCE_STRENGTH` 0.4 |
| `skeptic` | `_TOLERANCE` 0.02 |
| `spec_engine` | `GENERATION_THRESHOLD_PCT` 5.0 · `MATERIALITY_FLOOR_CONTACTS` 50 · `MAJOR_DEVIATION_PCT` 75.0 |
| `statistical_evidence` | `RECENT_WEEKS` 13 · `YEAR_WEEKS` 52 · `LONG_WEEKS` 104 · `CV_VOLATILE` 0.30 · `CV_STABLE` 0.15 · `BIAS_MATERIAL_PCT` 5.0 · `DRIFT_MATERIAL_PCT` 0.25 · `MOMENTUM_MATERIAL_PCT` 10.0 · `TREND_R2_MEANINGFUL` 0.30 · `SEASONAL_INDEX_MATERIAL` 0.15 · `PLAN_VS_NORM_MATERIAL` 0.25 · `OUTLIER_MOD_Z` 3.5 · `MIN_N` 6 |

---

## Part 10 — The principles the numbers serve

**A threshold is a judgement, so it is named and commented.** Not one is a bare literal in a condition.

**Not measurable is not the same as no effect.** Every gate that fails reports *why* and how much data
it would need. A phase with 3 instances against a floor of 4 says so; it does not report zero.

**Absence of evidence is never evidence of absence.** A sub-threshold correlation means *not
confirmed*. A missing confidence dimension floors at 0.20, not zero.

**Direction is never discarded.** −0.22 and +0.22 mean opposite things operationally.

**An identity must reconcile or say it does not.** The ASU split and the miss decomposition both
publish whether the parts sum to the whole.

**Robust statistics where a single point could hide itself.** Median and MAD for outliers, medians for
phase effects, because the mean is contaminated by exactly what is being looked for.

**Every number in Python; the model writes prose only.** And a number in that prose which is not in the
inputs kills the prose, not the investigation.

---

## Reproducing this document

```
python results/extract_maths.py                    # constants, formulas, data lineage
python results/test_narrative_grounding.py         # 21/21, grounding tolerance
python results/test_summary_grounding.py           # summary grounding
python results/test_fc_spec_semantics.py           # 190/190, semantics
python results/test_wfm_diagnostics.py             # 148/148
node   results/check_ui_render.js                  # 21 cards, repetition caps
```

`results/find_holiday_weekend_test_weeks.sql` is read-only and verifies the calendar figures directly
in SSMS.
