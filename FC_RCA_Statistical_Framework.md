# FC_RCA_Statistical_Framework

**Project:** Forecast RCA Studio (FC_RCA)
**Document Type:** Statistical Framework Specification
**Version:** 2.0.0
**Supersedes:** Version 1.0.0
**Status:** Approved for Development
**Last Updated:** 30 July 2026

---

## Document Control

| Item | Detail |
|---|---|
| **Purpose** | Define the statistical capability set, metric selection, aggregation, lag treatment, driver relevance and statistical governance. |
| **Scope** | Statistical analysis for Phase 1. |
| **Version basis** | Incorporates P1–P10. The adherence formula, aggregation rules, lag treatment and driver relevance gate are all corrected against measured data. |
| **Dependencies** | `FC_RCA_Definitions_and_Formulas.md` v2.0 · `FC_RCA_Business_Rules.md` v2.0 · `FC_RCA_RCA_Methodology.md` v2.0 |
| **Acceptance Criteria** | (1) No metric executes without a hypothesis requiring it. (2) Stock and flow never share an aggregation routine. (3) No unexplained statistical output appears in the application. |
| **Owner** | Product Owner, FC_RCA |
| **Approver** | Pending |

---

# 1. Purpose

This document defines what the engine measures, when, and how each result is interpreted.

---

# 2. Principles

| # | Principle |
|---|---|
| 1 | **Statistics support reasoning. They do not replace it** |
| 2 | Every metric is selected by a hypothesis |
| 3 | **Metrics shall not be executed unnecessarily** |
| 4 | Every result carries an interpretation in business language |
| 5 | All calculations are deterministic and reproducible |
| 6 | **No unexplained statistical output appears in the application** |
| 7 | A metric that cannot execute is recorded as suppressed, never silently omitted |
| 8 | No threshold is set from reasoning alone |

---

# 3. Position in the Canonical Sequence

The Statistical Analytics Layer is invoked at **Step 9** of the canonical sequence (`FC_RCA_RCA_Methodology.md §6`) — **after** hypothesis generation and evidence collection.

It is a **service**, not a stage that precedes reasoning.

```
Hypotheses (Step 6) → Evidence (Steps 7-8) → STATISTICS (Step 9)
```

Executing statistics before hypotheses would be correlation fishing.

---

# 4. Forecast Adherence

The primary business KPI.

```
Forecast Adherence % = (1 − (Actual_Offered / fcst_offered)) × 100
```

Canonical definition: `FC_RCA_Definitions_and_Formulas.md §2.1`.

## Properties

| Property | Value |
|---|---|
| Signed | Yes. 0% = perfect adherence |
| Negative | Actual above forecast = **under-forecast** |
| Positive | Actual below forecast = **over-forecast** |
| Storage | Signed value stored and displayed |
| `ABS()` | Used **only** for threshold comparison |

**The sign is diagnostically essential and shall never be discarded.** Over-forecast and under-forecast have opposite causes and opposite remedies.

## Correction from Version 1.0.0

Version 1.0.0 specified `1 − ABS((Actual / Forecast) − 1)`.

| | Version 1.0.0 | Version 2.0.0 |
|---|---|---|
| Perfect score | 1.00 | **0%** |
| Sign preserved | **No** | **Yes** |
| Measured minimum on reference data | **−9,499.7%** | — |

The unsigned form reached −9,499.7% on 1.5% of rows and destroyed direction — the single most diagnostic property of the metric. The trailing hedge *"or the business-approved equivalent formula defined in the Business Rules document"* pointed at a document that contained no formula, and is removed.

## Aggregation

Monthly and quarterly use the **Pooled** method:

```
(1 − (SUM(Actual_Offered) / SUM(fcst_offered))) × 100
```

**Weekly adherence values shall never be averaged.** Pooled is volume-weighted and reconciles to period totals; the simple average diverges by up to **53 percentage points** at the 99th percentile on reference data, and disagrees on breach status for 15 queues in a single quarter.

## Direction as evidence

A persistent one-sided pattern indicates **systematic forecast bias**. Alternating signs indicate **volatility**. Hypothesis generation shall use the sign.

## Purpose and limits

Forecast Adherence is the **generation metric**. It is **not** the Root Cause.

---

# 5. Forecast Accuracy — reference metric

```
Forecast Accuracy % = (Actual_Offered / fcst_offered) × 100
```

100% = perfect. Retained for reference and comparison only. **Not used to trigger RCA.**

```
Forecast Adherence % = 100 − Forecast Accuracy %
```

---

# 6. Aggregation by Measure Type

Different measures aggregate differently. Applying the wrong routine produces **silently incorrect** figures.

| Measure type | Fields | Monthly / Quarterly |
|---|---|---|
| **FLOW** | `Actual_Offered` · `fcst_offered` · `Actual_Handled` · `fcst_handled` · `Final_Units` · `Final_Y1`–`Y5` · `Final_upp_units` · `Holiday_Count` | **SUM** |
| **STOCK** | `Planned_ASU` · `Actual_ASU` | **MEAN** |
| **RATIO** | Forecast Adherence · ASU Adherence · warranty mix % | **RECOMPUTE** from aggregated inputs |

**Ratio measures shall never be averaged.**

**Summing a stock double-counts.** A queue with 100,000 units under warranty for 13 consecutive weeks has an installed base of **100,000 — not 1,300,000**.

---

# 7. Statistical Capability Set

> This section describes the **capability set** available to the Evidence Engine. It is **not an execution sequence**, and not every stage runs on every RCA.
>
> Version 1.0.0 presented a linear chain of fourteen analytical stages prefixed *"Every RCA shall follow the same analytical sequence"* — which, read literally, mandated running every metric on every investigation, contradicting Principle 3 and `BR-401`.

## Always Executed

| Stage | Purpose |
|---|---|
| Data Validation | Gate — `BR-101` to `BR-122` |
| Data Profiling | Establishes what analysis is possible |
| Descriptive Statistics | Baseline characterisation |
| Error Metrics | Quantifies the deviation |

## Selected by Hypothesis

| Stage | Selected when |
|---|---|
| Trend Analysis | Trend or growth hypothesis |
| Seasonality Analysis | Seasonal hypothesis; requires complete periods |
| Variability Analysis | Volatility hypothesis |
| Relationship Analysis | Driver hypothesis (correlation) |
| Drift Detection | Structural change hypothesis |
| Momentum Analysis | Acceleration hypothesis |
| Outlier Detection | Anomaly or data quality hypothesis |
| ML Explainability | Multi-driver attribution required |

## Always Executed on Completion

| Stage | Purpose |
|---|---|
| Evidence Generation | Converts statistical output into evidence |
| Confidence Contribution | Feeds `StatisticalAgreement` and `ModelAgreement` |

## Suppression

Where a selected stage cannot execute — insufficient coverage, Tier C warranty data, Emerging queue, driver failing the relevance gate — it is recorded as **SUPPRESSED with a stated reason**, never silently omitted.

**A suppressed stage is distinguishable from one that ran and found nothing.**

---

# 8. Error Metrics

| Metric | Purpose |
|---|---|
| MAE | Mean absolute error, in contacts |
| WAPE | Weighted absolute percentage error |
| RMSE | Penalises large deviations |
| Bias | Signed mean error — direction of systematic miss |

**MAPE is available but de-emphasised.** With 261 rows holding `Actual_Offered = 0` and 50 holding `fcst_offered = 0` in reference data, MAPE is unstable at low volumes. WAPE is preferred.

---

# 9. Trend Analysis

Detects sustained directional movement. Reports slope, direction, significance and the window analysed.

**Requires** ≥ 3 periods with actuals. Below that, suppressed.

---

# 10. Seasonality Analysis

Detects recurring patterns.

**Requires** ≥ 104 weeks of history **and** a complete period. On partial periods, suppressed — a seasonal comparison against an incomplete period is not a comparison.

## Holiday-anchored seasonality

Where a moving holiday is present, seasonal comparison uses **holiday-anchored** matching (`BR-209`) rather than same-fiscal-week matching.

Measured drift: **Diwali** moves up to 3 fiscal weeks across years. **Eid al-Fitr** moves 8 weeks over six years. Same-fiscal-week comparison for affected queues is systematically wrong.

Where both anchoring modes are available and disagree, **both are reported**.

---

# 11. Variability Analysis

Coefficient of Variation, standard deviation, range. Establishes the volatility band against which a deviation is judged.

---

# 12. Relationship Analysis — Correlation

## Correlation variables

| Variable | Nature | Lag treatment | Applicability |
|---|---|---|---|
| `fcst_offered` | Flow | Contemporaneous | Always |
| `Actual_Offered` | Flow | Contemporaneous | Always |
| **`Actual_ASU`** | **STOCK** | **Contemporaneous** | Not for out-of-warranty; relevance-gated |
| `Planned_ASU` | STOCK | Contemporaneous | Same |
| ASU variance / ASU Adherence | STOCK | Contemporaneous | Same |
| ASU growth rate | Derived | Contemporaneous | Same |
| **Shipments** (`Final_Units`) | Flow | **Empirical lag** | Not for out-of-warranty; relevance-gated |
| **Warranty exclusive bands** | Flow | **Empirical lag** | Tier A/B; relevance-gated |
| `Holiday_Count` and day indicators | — | Contemporaneous | Not for aggregate countries |
| Unit Production Plan | Flow | Empirical lag | 83% sparse — flagged |
| Business Events | — | Within impact window | Optional |
| Marketing Activity | — | — | FUTURE SCOPE |

## Removed from Version 1.0.0

| Removed | Reason |
|---|---|
| **"Average Selling Units"** | **An incorrect definition of ASU.** ASU is Active Serviceable Units — the installed base under warranty, a stock measure |
| "Product Age" | No source in input data |
| "Installed Base" as a separate variable | Installed base **is** ASU |

## Mandatory constraints

1. **Warranty variables shall be EXCLUSIVE BANDS only.** Raw `Final_Y1`–`Final_Y5` values shall never enter correlation. They are nested — `Y2` is contained within `Y1` — so correlating both produces spurious multicollinearity and uninterpretable attribution.
2. **Stock and flow require different lag treatment.** See §13.
3. Rows failing `BR-112` (Tier C) shall be **excluded** from any correlation involving warranty or shipment variables — not imputed, not zero-filled.
4. Drivers failing the relevance gate (`BR-121`) shall be excluded as **Not Applicable** — no confidence penalty.
5. **ASU is a stock.** Correlation uses the weekly average level, never a sum.

---

# 13. Lag Treatment — Empirical, Not Prescribed

Stock measures are tested **contemporaneously**.

Flow measures **may** exhibit lag. The lag, where one exists, is determined **empirically per queue**:

```
FOR lag IN 0..13 weeks:
    compute correlation(driver shifted by lag, Actual_Offered)
SELECT the lag with the highest absolute correlation
IF that correlation clears the BR-121 relevance gate:
    use that lag
ELSE:
    the driver is NOT RELEVANT for this queue
```

## Measured basis

Version 1.0.0 **required** lag treatment for flow measures. Fixed lags were tested against reference data and **reduce** correlation:

| `Final_Units` vs `Actual_Offered` | Queues with \|r\| ≥ 0.3 |
|---|---|
| **Lag 0** | **19%** |
| Lag 4 | 16% |
| Lag 8 | 17% |
| Lag 13 | 15% |

**No fixed lag improves on contemporaneous.** A queue-specific lag may exist; a universal one does not. The prescriptive requirement is withdrawn.

The selected lag shall be **recorded in the evidence and stated in the narrative**.

---

# 14. Driver Relevance Gate

A driver applies to a queue only where it has demonstrated a relationship with that queue's demand.

```
Driver is RELEVANT where:
    ABS( correlation(driver, Actual_Offered) ) >= 0.3
    over at least 30 observations
```

## Measured pass rates

| Driver | Queues passing | Share |
|---|---|---|
| **`Actual_ASU`** | 236 of 427 | **55%** |
| `Final_Units` | 76 of 427 | 18% |
| Warranty band share | 78 of 427 | 18% |
| **All three fail** | 139 of 427 | **33%** |

## Why the gate tests against demand, not adherence

Correlation with **adherence** — the miss itself — is far weaker across all drivers: ASU 19%, warranty 5%, shipments 2%.

This is expected: where a forecaster already accounts for a driver, that driver will not explain the residual error. **The error lives in what was unexpected, not in the driver level.**

Gating on adherence correlation would disable nearly every driver. The gate therefore tests whether a driver **tracks demand at all** for that queue.

## Driver cascade — business order preserved

The gate determines **usability**, never **order**. Business causality sets the order.

| Offering | Cascade |
|---|---|
| **Basic** | **Shipments** → ASU → next metric |
| Premium, Pro | ASU → Shipments → next metric |
| Out-of-warranty | Neither applies |

A low average pass rate does not demote a business-correct driver for the queues where it works.

## Evaluation and effect

Recalculated FW01, FW14, FW27, FW40, effective-dated. Where a driver fails, the associated hypothesis is **not generated** and the driver is excluded as **Not Applicable** — no penalty.

The measured correlation is stated on the Decision Card:

> *"Warranty coverage was not evaluated for this queue: correlation with demand is 0.08 over 235 weeks, below the 0.3 relevance threshold."*

---

# 15. ASU Plan Variance

`Planned_ASU` is a forecast and is treated as one:

```
ASU Adherence % = (1 − (Actual_ASU / Planned_ASU)) × 100
```

Same formula and sign convention as Forecast Adherence.

## Measured

| Measure | Value |
|---|---|
| Rows with both values | 73,439 (52.9%) |
| Median ASU Adherence | **+1.3%** — typically accurate |
| p05 / p95 | −56.8% / +98.3% |
| Fires at ±20% | 34.8% before gating |

## Separate relevance gate

```
ABS( correlation(ASU adherence, contact adherence) ) >= 0.3
over at least 30 observations
```

Measured pass rate: **16% of queues** (53 of 341). Where the gate fails, the hypothesis is **Not Applicable**.

This gate is distinct from `BR-121`: it asks whether a **plan miss** explains a **forecast miss**, not whether a driver level tracks demand.

## Directional coherence

| ASU variance | Expected adherence |
|---|---|
| Positive | Negative — under-forecast |
| Negative | Positive — over-forecast |

Where coherent, strong supporting evidence. Where opposite, **contradictory evidence** is recorded and the hypothesis shall not be accepted without an explanation of the divergence. **Flagged, not capped** — a genuine explanation may exist.

---

# 16. Drift Detection

Detects structural change in the series. Reports change point, magnitude and direction.

**Requires** sufficient history either side of the candidate change point. On partial periods, suppressed.

---

# 17. Momentum Analysis

Detects change in rate of change. Reports acceleration or deceleration.

---

# 18. Outlier Detection

Identifies periods outside expected bounds. Reports method, bound and magnitude of exceedance.

**Note** — an outlier is not a root cause. It is a signal requiring explanation.

---

# 19. ML Explainability

## SHAP and Feature Importance

Attributes a deviation across multiple drivers.

## Explanatory variables

- Active Serviceable Units — installed base, stock, contemporaneous
- Shipments / `Final_Units` — flow, empirical lag
- Warranty **exclusive bands** — flow, empirical lag, Tier A/B only
- `Holiday_Count` and day-of-week indicators
- Historical demand
- Unit Production Plan — sparse, flagged where absent

## Excluded in this release

| Excluded | Reason |
|---|---|
| Product Age | No source |
| Marketing Activity, Business Events as features | Future scope |

## Feature construction constraints

1. **Warranty features shall be exclusive bands.** Entering nested `Final_Y1`–`Y5` values as separate features produces attribution that cannot be interpreted, because the features are subsets of one another.
2. Attribution shall respect the lag structure in §13.
3. Where `BR-112` Tier is C, warranty and shipment features are marked **unavailable** for that observation and **shall not be imputed**. Attribution output states which features were unavailable and for how many periods.
4. Features failing the relevance gate are excluded as **Not Applicable**.

## Interpretation requirement

Every SHAP output shall be translated into business language naming the **specific** feature, its direction, magnitude and denominator. *"Warranty Mix was the largest contributor"* is insufficient — the specific exclusive band must be named.

---

# 20. Metric Selection

## Scenario-driven selection

| Scenario | Primary metrics | Secondary |
|---|---|---|
| Warranty Mix Shift | Correlation, SHAP | Regression |
| Installed Base Change | Regression, Feature Importance | Drift |
| Shipment Volume Change | Lagged Correlation | Regression |
| ASU Plan Variance | Variance comparison, Correlation | Regression |
| Holiday Impact | Historical Comparison, Seasonality | Trend |
| Demand Spike / Drop | Outlier, Variability | Momentum |
| Forecast Bias | Bias, Trend | Historical Comparison |
| Trend Misidentification | Trend, Drift | Momentum |
| Volatility | CoV, RMSE | Drift |
| Data Quality Issue | Validation Metrics | Residual Analysis |

## Constraints

1. Where history is insufficient, metrics requiring historical baselines — Seasonality, year-over-year comparison, Drift — shall **not** execute. Recorded as **SUPPRESSED** with a stated reason.
2. Where Volume Band is **Emerging**, the same constraint applies.
3. Warranty Mix Shift metrics require `BR-112` Tier A or B. Tier C suppresses the scenario entirely.
4. Shipment and warranty scenarios use **empirical lag**. Installed base uses **contemporaneous**.
5. Drivers failing `BR-121` suppress their scenario as Not Applicable.

Metric selection shall remain configurable.

## Queue Behaviour Classification — withdrawn from Phase 1

Version 1.0.0 defined a six-way behavioural classification (Stable / Seasonal / Trending / Event Driven / Highly Volatile / Emerging) with no derivation rule, used for metric selection.

**Withdrawn.** Metric selection is hypothesis-driven, which does the same job with one mechanism instead of two. The classification also reused the word *Emerging*, colliding with the Volume Band value of that name.

Revisit only if hypothesis-driven selection proves insufficient in practice. Deferred to Phase 2.

---

# 21. Evidence Strength Scale

**Five levels, canonical**, matching the Data Dictionary and Explainability Framework:

| Level | Weight |
|---|---|
| Very Strong | 1.0 |
| Strong | 0.8 |
| Moderate | 0.6 |
| Weak | 0.4 |
| Very Weak | 0.2 |

Version 1.0.0 used a three-level scale here (Strong / Moderate / Weak) while other documents used five. **Five is canonical.**

---

# 22. Statistical Contribution to Confidence

Statistical output feeds two confidence dimensions:

| Dimension | Derivation | Weight |
|---|---|---|
| `StatisticalAgreement` | `metrics_supporting_conclusion / metrics_executed`. Fewer than 2 executed → Not Applicable | 0.14 |
| `ModelAgreement` | `methods_concurring / methods_executed`. Fewer than 2 applicable → Not Applicable | 0.05 |

Suppressed metrics reduce the denominator and are recorded, not counted as disagreement.

---

# 23. Evidence Hierarchy

Statistics sit **third** in the evidence hierarchy:

1. Verified business data
2. Business Rules
3. **Deterministic statistical analysis**
4. Historical patterns
5. Time-series analysis
6. ML attribution
7. LLM narrative

Where a business rule contradicts a statistical finding, the business rule prevails and confidence is capped at Low (`BR-505`, Gate 2).

---

# 24. Statistical Governance

| Requirement | Detail |
|---|---|
| **Investigation scoping** | Every statistical calculation links to an `investigationId`. **No calculation may exist outside an investigation** |
| Selection recording | Every metric records why it was selected |
| Interpretation | Every result carries a business-language interpretation |
| Audit | Every result recorded with its `Statistical_Analysis_ID` |
| Determinism | Identical inputs produce identical results |
| Configuration | Metric enablement and parameters are versioned configuration |
| Threshold validation | Every threshold validated against real data before release |

## No unexplained output

**No unexplained statistical output shall appear in the application.** A metric value without an interpretation is not publishable.

This is enforced in the API: statistical endpoints require `investigationId`, and requests without it return HTTP 400.

---

# 25. Reference Test Cases

## Forecast Adherence

| # | `fcst_offered` | `Actual_Offered` | Expected | Direction |
|---|---|---|---|---|
| 1 | 1,000 | 1,000 | **0.0%** | Perfect |
| 2 | 1,000 | 1,120 | **−12.0%** | Under-forecast |
| 3 | 1,000 | 880 | **+12.0%** | Over-forecast |
| 4 | 1,000 | 2,000 | −100.0% | Under-forecast |
| 5 | 1,000 | 0 | +100.0% | Over-forecast |
| 6 | 0 | 500 | Non-computable | Flagged (`BR-110`) |
| 7 | blank | 500 | Blank | Flagged |
| 8 | 1,000 | blank | Blank | No RCA |

**Sign inversion is a critical defect.** Case 2 returning +12.0% shall fail the build.

## Pooled aggregation

| FW | Forecast | Actual |
|---|---|---|
| 18 | 1,000 | 1,100 |
| 19 | 1,200 | 1,150 |
| 20 | 900 | 1,080 |
| 21 | 1,100 | 1,000 |
| **Total** | **4,200** | **4,330** |

Expected Pooled: **−3.1%**. Simple average of weekly values (−4.2%) shall **fail**.

## ASU aggregation

13 weekly values, all 100,000:

| Aggregation | Expected | Failing result |
|---|---|---|
| Weekly | 100,000 | — |
| Monthly (4 wk) | **100,000** | 400,000 (summed) |
| Quarterly (13 wk) | **100,000** | 1,300,000 (summed) |

Mixed 90,000 / 100,000 / 110,000 / blank across a 4-week month:

| Field | Expected |
|---|---|
| Weeks with values | 3 |
| Monthly ASU | **100,000** — mean of 3, blank excluded |
| Failing result | 75,000 — blank counted as 0 |
| Failing result | 300,000 — summed |

## Warranty exclusive bands

Input: `Final_Units` 4,220 · `Y1` 4,220 · `Y2` 2,623 · `Y3` 2,562 · `Y4` 1,348 · `Y5` 143

| Band | Expected units | Expected share |
|---|---|---|
| No warranty | 0 | 0.0% |
| 1-year only | 1,597 | 37.8% |
| 2-year only | 61 | 1.4% |
| 3-year only | 1,214 | 28.8% |
| 4-year only | 1,205 | 28.6% |
| 5-year | 143 | 3.4% |
| **Total** | **4,220** | **100.0%** |

Assertions that shall **fail** the build:

- Band sum ≠ `Final_Units`
- Any share computed with `SUM(Y1..Y5)` as denominator — would give 10,896
- Correlation or SHAP executed on raw nested Y-values
- Any warranty output produced for a Tier C row

---

# 26. Future Statistical Extensions

FUTURE SCOPE:

- MASE
- Bayesian confidence intervals
- Causal inference methods
- Queue Behaviour Classification
- Semantic similarity scoring
- Quantified weekday / weekend impact coefficients per queue

---

# 27. Guiding Principles

- Statistics support reasoning; they do not replace it
- A metric that does not test a hypothesis does not run
- Stock and flow never share an aggregation routine
- Lag is measured, not assumed
- A driver that does not track demand is not used
- A suppressed metric is not a metric that found nothing
- Every number in the application has an explanation attached

---

# End of Document
