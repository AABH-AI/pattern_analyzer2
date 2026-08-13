# WFM engine — Python call chain and mathematics evidence

**Case:** `SA Indonesia Client Basic`, Fiscal Week **202716** (FY27 FW16)
**Engine:** `POST /api/rca-investigate?mode=wfm` — the WFM cross-functional engine (`backend/wfm/`)
**Model:** `gemini-3.5-flash` (`provider=gemini`), 1 call, 65.8 s, `investigation_meta.engine = "wfm-llm"`
**Data:** live `Playground.dbo.Input_To_ML_Full` on `10.10.9.75`, read at 2026-08-13T10:17:50Z
**Branch:** `spec-v2-refactor` @ `74f46c5`

Every figure in this document was **recomputed from SQL with formulas written from scratch**, importing
nothing from `backend/wfm/`. Where the engine and the independent recomputation disagree, the
disagreement is stated rather than smoothed over. The companion document
[WFM_GEMINI_UI_OUTPUT.md](WFM_GEMINI_UI_OUTPUT.md) covers what the model wrote on top of these numbers.

---

## 1. What is Python and what is the model

The engine makes **exactly one** LLM call. Everything numeric happens in Python before that call, and
the model never computes — it ranks and writes prose over a fixed feature payload.

```
POST /api/rca-investigate?mode=wfm&provider=gemini&model=gemini-3.5-flash
  │
  ├─ sql_backend.rca_investigate()            backend/sql_backend.py:307
  │    └─ fetch_wfm_context(cursor, table, key)      wfm/data_access.py
  │         ├─ SELECT TOP 157 … WHERE Forecast_name=? AND Fiscal_Week<=?   ← history_104
  │         ├─ SELECT TOP 4  … WHERE Fiscal_Week>?                        ← reversion test
  │         ├─ channel siblings (this week + prior week, via dbo.CQN_Mapping)
  │         └─ ladder rollups (Business Org → Region → SubRegion → Country → Offering → Channel)
  │
  ├─ derive_features(context_bundle)           wfm/investigation_engine.py:62  → base_features
  ├─ statistical_evidence.build(...)           14 metrics, stdlib math/statistics only
  ├─ correlation_engine                        Spearman ρ + ASU decomposition
  ├─ hierarchy_analyzer                        investigation ladder → inherited_from
  ├─ channel_migration_detector                offset_share → migration_detected
  ├─ data_quality                              is the 152 itself credible?
  │
  ├─ ═══ ONE model call (gemini-3.5-flash) ═══  rank + explain, business language only
  │
  ├─ skeptic.review()                          hard-reject causes whose precondition is unmet
  ├─ hypothesis_generator.mark()                downgrade over-confident statuses
  └─ business_report_generator.back_compat()    recompute the KPI, back-fill legacy keys
```

`statistical_evidence.py` declares its dependency rule in its own docstring — **stdlib only, no numpy,
no scipy, no sklearn**, "every formula written out so it can be checked by hand". This document is that
check, carried out.

### SQL actually issued for this case

| Purpose | Query shape | Rows |
|---|---|---|
| Queue history | `SELECT TOP 157 … WHERE Forecast_name=? AND Fiscal_Week<=202716 ORDER BY Fiscal_Week DESC` | 157 |
| Forward reversion window | `SELECT TOP 4 Fiscal_Week, Actual_Offered … WHERE Fiscal_Week>202716` | 3 |
| Channel siblings | this week + prior week within the Combined Queue | 1 channel |
| Ladder rollups | `SUM(Actual_Offered)`, `SUM(fcst_offered)` at 6 scope levels for FW202716 | 6 |

`WFM_HISTORY_WEEKS = 157` ([wfm/common.py:26](backend/wfm/common.py#L26)) is a hard cap. The queue
holds **208** weeks in total and **171** at or before the target week, so the engine deliberately works
on the most recent 157. Of those, **155** carry a usable `(fcst_offered, Actual_Offered)` pair and
**154** remain once the target week is excluded — matching `weeks_available: 155` and
`weeks_used_excluding_target: 154` exactly. Rows missing either side are dropped, never zero-filled
(a zero forecast would invent a 100 % error; a zero actual would make MAPE infinite).

---

## 2. The target week and the one KPI

```
adherence_pct = (1 − Actual_Offered / fcst_offered) × 100        wfm/common.py:64
```

| | Value |
|---|---|
| `fcst_offered` | 63.7921553653377 |
| `Actual_Offered` | 152.0 |
| adherence | (1 − 152 / 63.7921553653377) × 100 = **−138.27381 %** → reported **−138.3 %** |
| band | 10.0 % → `breached: true`, `direction: under_forecast` |
| error | 152 − 63.79 = **+88.21** contacts |

Negative means actual ran **above** forecast. `Holiday_Count` for this week is **0.0**.

---

## 3. Reconciliation — engine vs independent recomputation

Both columns are computed inside the engine's own 157-week window. **Exact** means identical to the
last reported decimal place.

### 3.1 Forecast accuracy — three windows

`error = actual − forecast` (so negative bias = over-forecast, the opposite sign to adherence).

| Metric | Formula | 13 wk | 52 wk | 104 wk | Verdict |
|---|---|---|---|---|---|
| MAE | `Σ|eᵢ| / n` | 36.64 | 20.15 | 17.77 | **exact** |
| MAPE % | `Σ(|eᵢ|/aᵢ) / n × 100` | 52.20 | 24.72 | 20.64 | **exact** |
| WAPE % | `Σ|eᵢ| / Σaᵢ × 100` | 40.57 | 20.76 | 17.77 | **exact** |
| RMSE | `√(Σeᵢ² / n)` | 45.31 | 28.01 | 24.19 | **exact** |
| Bias | `Σeᵢ / n` | −4.22 | +1.77 | −1.22 | **exact** |
| Bias % | `bias / mean_actual × 100` | −4.67 | +1.82 | −1.22 | **exact** |
| Error std dev | sample stdev of `eᵢ` | 46.95 | 28.22 | 24.27 | **exact** |
| Forecast variance | sample variance of `eᵢ` | 2204.69 | 796.50 | 589.14 | **exact** |
| Mean actual | `Σaᵢ / n` | 90.31 | 97.06 | 99.99 | **exact** |

No window shows a material standing lean — every `bias_pct` is inside the ±5 % `BIAS_MATERIAL_PCT`
threshold. **This queue is not chronically biased; this week is not "more of the same".**

### 3.2 Volatility, trend, drift, momentum

| Metric | Formula | Engine | Independent | Verdict |
|---|---|---|---|---|
| CV 13 wk | `σ / μ` of actuals | 0.3096 | 0.3096 (sample σ) | **exact** — see §4.1 |
| CV 104 wk | `σ / μ` | 0.2415 | 0.2415 (sample σ) | **exact** |
| Trend 13 wk | OLS slope of actual vs week index | +2.92 /wk, r² 0.165 | +2.9176, r² 0.165 | **exact** |
| Trend 52 wk | OLS slope | +0.10 /wk, r² 0.003 | +0.0989, r² 0.003 | **exact** |
| Drift 13 wk | OLS slope of **adherence** | −9.842 pts/wk, r² 0.289 | −9.8423, r² 0.289 | **exact** |
| Drift 52 wk | OLS slope of adherence | −0.609 pts/wk, r² 0.056 | −0.6090, r² 0.056 | **exact** |
| Drift total 13 wk | slope × span | −127.95 | −127.95 (×13) / −118.11 (×12) | **span convention — see §4.2** |
| Momentum | last 4 wk mean vs prior 8 wk | 105.75 vs 87.00 = +21.55 % | identical | **exact** |

OLS is written out by hand in [wfm/statistical_evidence.py:98](backend/wfm/statistical_evidence.py#L98)
as `slope = Σ(x−x̄)(y−ȳ) / Σ(x−x̄)²`, `r² = sxy² / (sxx·syy)` — reproduced exactly.

Both trends have r² far below the `TREND_R2_MEANINGFUL = 0.30` cutoff, so the engine correctly reports
`trend_meaningful: false` and calls recent movement noise. Drift at r² 0.289 also sits below 0.30, yet
`drift_material: true` — because materiality for drift is judged on the **slope** against
`DRIFT_MATERIAL_PCT = 0.25` pts/wk, not on fit. −9.84 clears that by ~39×.

### 3.3 Seasonality and the plan gap — the winning cause

Week-of-fiscal-year = `202716 % 100 = 16`. Prior years found in-window:

| Fiscal week | Actual |
|---|---|
| 202416 | 195.0 |
| 202516 | 66.0 |
| 202616 | 106.0 |
| **mean** | **122.33** |

| Metric | Engine | Independent | Verdict |
|---|---|---|---|
| same-week mean | 122.33 | 122.33 | **exact** |
| plan vs seasonal norm | 63.79 / 122.33 − 1 = **−47.85 %** | −47.85 % | **exact** |
| plan vs overall mean | 63.79 / 109.16 − 1 = **−41.56 %** | −41.56 % | **exact** |
| seasonal index | 1.118 | 1.121 | **denominator differs — see §4.3** |
| `direction_coherent` | true | plan is low, actual came in high → coherent | **correct** |
| `plan_gap_material` | true | 0.4785 > `PLAN_VS_NORM_MATERIAL` 0.25 | **correct** |

`direction_coherence` is the gate added on this branch, and it earns its place here: a cause is only
allowed to stand if it predicts the **same direction** as the miss. A plan set 48 % low predicts an
under-forecast, and the week under-forecast — coherent. This is precisely the test that
[SA_INDONESIA_RCA_VALIDATION.md](SA_INDONESIA_RCA_VALIDATION.md) found the *older* engine failing when
it blamed a holiday (which predicts a *quieter* week) for a week that ran busier.

### 3.4 Investigation ladder

`adherence_pct` recomputed on `SUM(Actual_Offered)` / `SUM(fcst_offered)` per scope, FW202716 only:

| Level | Scope | Actual | Forecast | Adherence | Verdict |
|---|---|---|---|---|---|
| Business Org | CSG | 254,839 | 245,299.5 | −3.9 % | **exact** (see §4.4) |
| Region | CSG / APJ | 103,574 | 101,894.8 | −1.6 % | **exact** |
| SubRegion | CSG / APJ / SA | 11,118 | 11,256.7 | +1.2 % | **exact** |
| Country | … / Indonesia | 575 | 579.7 | +0.8 % | **exact** |
| **Offering** | … / Basic | 152 | 63.8 | **−138.3 %** | **exact** |
| Channel | … / Voice | 152 | 63.8 | −138.3 % | **exact** |

Only Offering and Channel breach the 10 % band, and they are numerically identical because this
Offering contains exactly one queue-week. `inherited_from: "Offering"` is therefore correct — and the
attribution is real but **degenerate**: the parent equals the child, so "inherited from Offering" adds
no new information about *where* to act. Country, one rung up, is fine at +0.8 %.

### 3.5 Data quality — is 152 credible?

| Check | Engine | Independent | Verdict |
|---|---|---|---|
| typical (median) week | 107.0 | 107.0 | **exact** |
| times typical | 1.4× | 152 / 107 = 1.42 | **exact** (1 dp) |
| following 3 weeks | 73, 70, 85 | 73, 70, 85 | **exact** |
| `suspect` | false | 1.4× median is unremarkable | **correct** |

The value survives scrutiny: 152 is 1.4× a typical week, not 50×, so `data_quality_issue` was never a
candidate. Demand then falls back to 73/70/85, which is consistent with a one-week event rather than a
level shift.

### 3.6 Driver relationships (Spearman ρ) and the ASU decomposition

Retention rule: **≥ 12 weeks and |ρ| ≥ 0.5**. Rank-based on purpose — one extreme week cannot drag it
the way Pearson would.

| Driver | Engine ρ (weeks) | Independent, same window | Independent, full history | Outcome |
|---|---|---|---|---|
| `Actual_ASU` | 0.47 (139) | **0.47 exact** | 0.50 (154) | **rejected** — straddles the 0.5 cutoff (§4.5) |
| `Planned_ASU` | 0.40 (155) | **0.40 exact** | 0.40 (176) | rejected |
| `Final_Units` | −0.01 (155) | **−0.01 exact** | +0.01 (176) | rejected |
| `Holiday_Count` | −0.37 (155) | **−0.37 exact** | −0.34 (176) | rejected |

Inside the engine's own 157-week window all four coefficients reproduce exactly, so the rank-correlation
implementation is confirmed correct; the full-history column differs only because the window differs.

**All four relationships were rejected**, so no driver was available as evidence. That is the honest
outcome and the engine reported it as such.

The exact decomposition could not run at all:

```
volume_effect = (Actual_ASU − Planned_ASU) × planned_rate
rate_effect   = Actual_ASU × (actual_rate − planned_rate)
volume_effect + rate_effect ≡ Actual_Offered − fcst_offered
```

`Actual_ASU` is **NULL** for FW202716, so `driver_decomposition` correctly returns
`available: false, missing_fields: ["Actual_ASU"]` and names the missing field instead of guessing.
The strongest attribution tool in the system was unavailable for this case — and the response says so
in `missing_information`, which the UI renders.

### 3.7 Z-scores (`(target − history_mean) / sample_stdev`, 13 posted weeks)

| Field | Target | Mean | Sample σ | z | Verdict |
|---|---|---|---|---|---|
| `Actual_Offered` | 152.0 | 90.31 | 27.9565 | **+2.21** | **exact** |
| `fcst_offered` | 63.79 | 94.53 | 29.4679 | **−1.04** | **exact** |
| `Holiday_Count` | 0.0 | 0.8462 | 1.3445 | **−0.63** | **exact** |
| `Final_upp_units` | 109.0 | 76.00 | **1.4142** | **+23.33** | **arithmetically exact, statistically void — §4.6** |
| `Planned_ASU` (usual) | 30,050 | 26,672.77 | — | — | **exact** |

`forecast_sanity` concludes `actual_anomalous` (actual z +2.21 vs forecast z −1.04, ratio 0.42) — the
forecast is within normal range for this queue while the actual is not. Note this sits in mild tension
with the winning cause, which says the *plan* is the outlier; §4.7.

---

## 4. Where the numbers need caveats

Everything below reproduced exactly, so none of it is an arithmetic error. These are **definitional
choices and coverage limits** that change how a number should be read.

### 4.1 The "volatile" label rests on a sample-vs-population choice
`CV_VOLATILE = 0.30`. Sample σ gives CV **0.3096** → `volatility_class: "volatile"`. Population σ
gives **0.2974** → would be `"moderate"`. The engine uses sample σ consistently, which is defensible,
but the verdict flips on the third decimal place. The narrative built on it — *"a queue this variable
cannot be held to a tight forecast band, so part of any miss is inherent"* — is a materially different
claim from "moderately variable", and it is one convention away from not applying.

### 4.2 Drift total is `slope × n`, not `slope × (n − 1)`
Reported: **−127.95** pts over 13 weeks (= −9.8423 × 13). Thirteen weekly observations span **12**
intervals, so the change implied across the window is −9.8423 × 12 = **−118.11**. The reported total
overstates the span by one step, **≈ 8.3 %**. The slope itself — the number that carries the meaning —
is exact.

### 4.3 Two metrics in the same module use different denominators
`plan_vs_seasonal_norm.overall_mean_actual = 109.16` (154 weeks, target excluded).
`seasonality.overall_mean_actual = 109.44` (155 weeks, target **included**):
`(109.16 × 154 + 152) / 155 = 109.44` — confirmed exactly. Hence `seasonal_index` 1.118 vs 1.121
independently. Immaterial here (both are far below the 1.15 materiality cutoff, so `seasonal_material`
is `false` either way), but the target week should not be inside a baseline it is being compared
against.

### 4.4 Ladder row inclusion differs by two rows at Business Org
Engine: `fcst_offered` 245,299.5 across 425 queue-weeks. Independent, requiring **both** figures
non-NULL: 245,221.0 across 423. A 78.5 difference from 2 extra rows where one side is NULL. Adherence
rounds to −3.9 % either way, so no verdict changes — but a `SUM` that tolerates a NULL on one side is
comparing slightly different populations in numerator and denominator.

### 4.5 `Actual_ASU` sits on the retention boundary
Engine ρ = 0.47 over 139 weeks (inside the 157 cap) → **rejected** at the |ρ| ≥ 0.5 threshold. Over the
queue's full 208-week history it is ρ = 0.50 over 154 weeks → would be **retained**. The single most
plausible physical driver of contact volume is admitted or dismissed depending on the history cap.
Worth a deliberate decision rather than an artefact of `WFM_HISTORY_WEEKS`.

### 4.6 `Final_upp_units` z = 23.33 is computed from two data points
This is the most consequential finding in this document. Across all **157** fetched weeks,
`Final_upp_units` is non-NULL in only **3**:

| Fiscal week | Final_upp_units |
|---|---|
| 202714 | 77.0 |
| 202715 | 75.0 |
| **202716 (target)** | **109.0** |

The history is therefore `[77, 75]` → mean 76.0, sample σ **1.4142**, giving
`z = (109 − 76) / 1.4142 = 23.33`. The arithmetic is right; the statistic is meaningless. A σ from two
adjacent near-identical readings is not a measure of normal variation, and **any** value would look
extreme against it. The honest reading of the same data is the one Gemini actually used in its prose:
**+43 %** vs a two-week average.

This matters because it is load-bearing, not cosmetic:

- `installed_base.material = true` is set from this z, and
  [wfm/skeptic.py:40](backend/wfm/skeptic.py#L40) uses exactly that flag as the **precondition** for
  the `installed_base_change` cause type. The n=2 z is what made that cause *eligible*.
- The cause shipped at **rank 3, 85 % confidence, status Verified**.
- The skeptic then *retained* it, reasoning: *"the extreme surge in Final_upp_units (z-score of 23.33)
  directly coincides with the anomalous actual demand spike"* — the guard cites the void statistic as
  grounds for keeping the cause.
- `technical_metrics` publishes **"Final_upp_units Z-Score: 23.33"** straight to the UI panel.

A minimum-n guard on the z inputs (the module already has `MIN_N = 6` for its own metrics, but
`_stat_summary` z-scores are computed in the bundle builder without one) would close this. Note also
that `Final_upp_units` has no measured relationship to demand for this queue — it is not among the
four correlation drivers, and the three retained correlation candidates were all rejected.

### 4.7 Two shipped causes disagree about which side is anomalous
`forecast_sanity.verdict = "actual_anomalous"` (the forecast looks normal, the actual does not), and
rank 4 `genuine_demand_event` says exactly that. Rank 1 `forecast_baseline_error` says the opposite —
*"the plan is the unusual value, not the demand"*. Both are defensible from different baselines: the
plan is normal against the **last 13 weeks** (z −1.04) but 48 % low against **this week in prior
years** (122.33). They are nonetheless contradictory explanations shipped as ranks 1 and 4 without the
tension being named. The 13-week baseline is itself depressed — mean forecast 94.53 against a 122.33
seasonal norm — which is why the seasonal comparison is the more informative of the two.

---

## 5. What the deterministic layer decided before the model spoke

| Gate | Result | Consequence |
|---|---|---|
| Threshold gate | \|−138.3\| > 10 | investigate |
| Data quality | not suspect | `data_quality_issue` unavailable |
| Channel migration | `offset_share 0.0` → not detected | `channel_migration` **hard-rejected** |
| Plan restatement | `changed: false` | `plan_restatement` unavailable |
| Forecaster change | `changed: false` | unavailable |
| Holiday | count 0, z −0.63, not unusual | `calendar_holiday_effect` unavailable |
| Peer divergence | 1 similar queue, same direction | `volume_routing_shift` unavailable |
| Chronic bias | verdict `mixed` | `systematic_forecast_bias` weakened |
| Installed base | `material: true` (from the n=2 z) | `installed_base_change` **made eligible** |
| Ladder | `inherited_from: Offering` | `inherited_from_higher_level` eligible |
| Statistical evidence | `plan_vs_seasonal_norm`, 82 % | **overrides the model's rank 1** |

The model was handed a pre-narrowed field. Of ten cause types, the deterministic layer eliminated five
outright, and the one it made eligible on the weakest evidence in the payload (§4.6) is the one that
shipped at rank 3.

**The statistical override is the single most important mechanism here.** Gemini ranked
`inherited_from_higher_level` first at 95 %. `statistical_evidence` computed
`forecast_baseline_error` at 82 % from the plan-vs-seasonal-norm gap and **displaced it to rank 2**:

> *"Statistical evidence (Plan vs seasonal norm (same week, prior years)) overrides the model's
> ranking: forecast_baseline_error is measured directly from this queue's own history."*

This is why confidence runs **82 → 95 → 85 → 80** down the ranks instead of descending. It is a
structural consequence of the override, not a model error — but it does break the invariant that
[results/run_llm_ranking.py](results/run_llm_ranking.py) asserts as check **L3** ("confidence descends
with rank"), so that check would report FAIL on this response. Either L3 needs to exempt an overridden
rank 1, or the override needs to carry the displaced confidence. Flagging it as a genuine
contract inconsistency on this branch, not a defect in this run.

---

## 6. Verdict

`results/verify_indonesia_math.py` asserts each figure against the engine's own reported value and
exits non-zero on any mismatch. Current result: **72 / 72 asserted checks pass**, exit 0, with 5 further
observations recorded for information.

| | |
|---|---|
| Asserted checks | **72** |
| Reproduced exactly | **72** |
| Definitional differences (recorded, not asserted) | **3** (drift span §4.2, seasonality denominator §4.3, ladder NULL handling §4.4) |
| Arithmetic errors found | **0** |
| Statistically unsound inputs found | **1** (`Final_upp_units` z from n=2, §4.6) |
| Contract inconsistencies found | **1** (confidence ordering under override, §5) |

**The arithmetic is sound.** Every accuracy, volatility, trend, drift, momentum, seasonality, plan-gap,
ladder and data-quality figure reproduces to the reported decimal from raw SQL using formulas written
from scratch. The three differences are conventions, not mistakes, and each is small enough not to
change a verdict — though §4.1 shows one verdict *label* sitting on a knife edge.

The weakness is not in the calculator, it is in **coverage discipline**: one field with two usable
history points produced a z-score of 23.33, that z set a `material` flag, the flag opened a
precondition gate, the gate admitted a cause, and the cause shipped at 85 % confidence with the void z
printed on screen as evidence. Everything downstream behaved correctly given the input. The input
should not have been allowed to count.

---

## 7. Reproducing this

```bash
# 1. backend (needs VPN to 10.10.9.75 and backend/config.json)
cd backend && python -m uvicorn sql_backend:app --host 127.0.0.1 --port 8000

# 2. the investigation, exactly as the UI issues it
curl -X POST "http://127.0.0.1:8000/api/rca-investigate?mode=wfm&provider=gemini&model=gemini-3.5-flash" \
     -H "Content-Type: application/json" -d @results/indonesia-wfm-gemini-bundle.json

# 3. the independent recomputation in this document
cd backend && python ../results/verify_indonesia_math.py
```

Captured artefacts: [results/indonesia-wfm-gemini.json](results/indonesia-wfm-gemini.json) (full
response), [results/indonesia-wfm-gemini-bundle.json](results/indonesia-wfm-gemini-bundle.json)
(the posted context bundle), [results/verify_indonesia_math.py](results/verify_indonesia_math.py)
(this document's arithmetic, importing nothing from `wfm/`), and
[results/indonesia-math-verification.json](results/indonesia-math-verification.json) (its
check-by-check output).

The LLM call is **not** deterministic — rankings, wording and confidence percentages will vary between
runs. Everything in §2–§3 is deterministic and will reproduce byte-for-byte while the table is
unchanged.
