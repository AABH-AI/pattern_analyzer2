# FC_RCA_Business_Rules

**Project:** Forecast RCA Studio (FC_RCA)
**Document Type:** Business Rules Specification
**Version:** 2.1.0
**Supersedes:** Version 2.0.0
**Status:** Approved for Development
**Last Updated:** 30 July 2026

---

## Document Control

| Item | Detail |
|---|---|
| **Purpose** | Define all deterministic business rules governing Forecast RCA Studio. |
| **Scope** | Trigger, validation, business context, investigation, statistical selection, confidence, explainability and recommendation rules for Phase 1. |
| **Version basis** | Version 2.1.0 incorporates change packages P1 to P11. Every threshold was measured against production-representative data before ratification. |
| **Assumptions** | Grain is one row per `Forecast_name` × `Fiscal_Week`. `Forecast_name` is the queue identifier. |
| **Dependencies** | `FC_RCA_Definitions_and_Formulas.md` v2.0 governs all definitions and formulas referenced here. |
| **Acceptance Criteria** | (1) No rule contains an unspecified threshold. (2) Every percentage-based rule has an absolute floor where applicable. (3) Every rule states its priority and its measured effect where one was determined. |
| **Related Documents** | `FC_RCA_Definitions_and_Formulas.md` · `FC_RCA_Data_Dictionary_and_Schema.md` · `FC_RCA_Statistical_Framework.md` · `FC_RCA_RCA_Methodology.md` · `FC_RCA_Master_Build_Specification__MBS_.md` |
| **Owner** | Product Owner, FC_RCA |
| **Approver** | Pending |

---

# 1. Purpose

This document defines all business rules governing the Forecast RCA Studio.

Business Rules provide deterministic decision logic that guides the AI before any statistical or machine learning analysis is performed.

Business Rules ensure:

- Standardization
- Consistency
- Repeatability
- Explainability
- Auditability
- Business Governance

Business Rules always take precedence over statistical inference whenever applicable. This precedence is enforced mechanically by BR-505.

---

# 2. Objectives

The Business Rules Framework shall:

- Define when an RCA is generated.
- Define mandatory validation rules.
- Define investigation prerequisites.
- Define confidence calculation and thresholds.
- Define business constraints.
- Standardize decision making.
- Minimize subjective interpretation.
- Support explainable AI reasoning.

---

# 3. Guiding Principles

## Rule 1 — Business Owned

Business Rules are owned by the business, not developers.

## Rule 2 — Configurable

Rules shall be configurable without changing application code.

## Rule 3 — Version Controlled

Every rule shall maintain version history.

## Rule 4 — Explainable

The AI shall explain whenever a Business Rule influences an RCA.

## Rule 5 — Auditable

Every executed rule shall be recorded in the Audit Trail.

## Rule 6 — Evidence Based

Every threshold shall be validated against real data before ratification. No threshold shall be set from reasoning alone.

---

# 4. Rule Categories

1. RCA Trigger and Scope Rules
2. Data Validation Rules
3. Business Context Rules
4. Investigation Rules
5. Statistical Rules
6. Confidence Rules
7. Explainability Rules
8. Recommendation Rules
9. Audit Rules
10. Future Rules

---

# 4A. Rule Index

Rule identifiers are stable across change packages and are therefore not contiguous within each category.

| Category | Rules |
|---|---|
| **Trigger and Scope** | BR-001 · BR-002 · BR-004 · BR-005 · BR-115 · BR-116 · BR-123 · BR-124 · BR-125 |
| **Data Validation** | BR-101 to BR-109 · BR-110 · BR-111 · BR-112 · BR-113 · BR-114 · BR-119 · BR-121 · BR-122 · **BR-126** |
| **Business Context** | BR-201 to BR-209 · BR-120 |
| **Investigation** | BR-301 to BR-306 · BR-117 |
| **Statistical** | BR-401 to BR-405 |
| **Confidence** | BR-501 to BR-507 · BR-118 |
| **Explainability** | BR-601 · BR-602 · BR-603 · BR-605 |
| **Recommendation** | BR-701 · BR-702 · BR-704 |

## Retired Rules

| Rule | Reason |
|---|---|
| **BR-003** Repeated Forecast Miss | Measured: 100% of queues reach three or more consecutive breaching weeks at ±5%, and 100% at eight weeks. The rule cannot discriminate. Retired |
| **BR-604** Technical Detail Visibility | Duplicated BR-405 — same name, same metrics, same requirement. Merged into BR-405 |
| **BR-703** Action Ownership | All recommendations route to the Demand / Forecast Team. A field with one possible value carries no information. Routing is stated once in BR-701 |

---

# 5. Rule Execution Order

Business Rules execute in the canonical investigation sequence defined in `FC_RCA_RCA_Methodology.md` §6.

```
Data Validation
      ↓
Adherence Calculation
      ↓
Deviation Detection
      ↓
Business Context
      ↓
Hypothesis Generation
      ↓
Supporting Evidence Collection
      ↓
Contradictory Evidence Collection
      ↓
Statistical Analysis
      ↓
Recursive Root Cause Reasoning
      ↓
Cross-Examination                (bounded loop — BR-117)
      ↓
Confidence Assessment
      ↓
Root Cause Selection
      ↓
Recommendations
      ↓
Executive Summary
      ↓
Audit
```

Rules executed earlier have higher priority.

## Structural Invariants

Two orderings are structural and shall not be varied by configuration:

1. **Hypothesis generation precedes statistical analysis.** Hypotheses determine which metrics execute. Statistics-first execution is correlation fishing and violates Statistical Framework Principle 4.
2. **Cross-examination precedes confidence assignment.** Cross-examination may return Reinvestigate or Reject, changing or discarding the conclusion, and confidence caps depend on its outcome.

---

# 5A. Canonical Metric Definition

## Forecast Adherence

All rules referencing Forecast Adherence use the following canonical definition, governed by `FC_RCA_Definitions_and_Formulas.md`.

```
Forecast Adherence % = (1 − (Actual_Offered / fcst_offered)) × 100
```

| Value | Meaning | Business reading |
|---|---|---|
| 0% | Actual equals forecast | Perfect adherence |
| Negative | Actual above forecast | **Under-forecast** — demand exceeded plan |
| Positive | Actual below forecast | **Over-forecast** — demand fell short |

Because perfect adherence is 0% and misses occur in both directions, every threshold in this document is a **two-sided band** evaluated as `ABS(Forecast Adherence)`. No rule may be expressed as "falls below" a threshold.

## Ratified Threshold Values

Every value below was measured against reference data before ratification. Measured effects are stated.

| Parameter | Value | Configurable | Measured effect |
|---|---|---|---|
| RCA Generation Threshold | **±5%** | No — fixed | 83.6% of queue-weeks |
| Display Filter default | ±10% | Yes | 68.6% |
| Display Filter options | ±5 / 10 / 15 / 20 / 25 / 30% | Yes | 83.6% down to 32.8% |
| Major Deviation | **±75% AND materiality floor** | Yes | ~35 cases per week |
| Warranty Mix Shift | **10 percentage points** | Yes | 16.0% of comparisons |
| Installed Base Change | **±20% year-over-year at RCA grain** | Yes | 27.3% |
| Installed Base Change, secondary | ±5% month-over-month | Yes | 8.8% |
| ASU Plan Variance | **±20% ASU adherence** | Yes | 34.8%, gated to 16% of queues |
| Driver Relevance Gate | **\|r\| ≥ 0.3, n ≥ 30** | Yes | ASU 55% · shipments 18% · warranty 18% |
| BR-208 relevance gate | \|r\| ≥ 0.3 adherence-to-adherence | Yes | 16% of queues |
| Minimum historical weeks | 104 | Yes | 18 of 427 queues fail |
| Warranty Tier B tolerance | MAX(2 units, 0.5%) | Yes | 4.3% of rows |
| Interior blank zero-fill limit | **3 consecutive weeks** | Yes | 550 weeks, 55 queues |
| Event impact window | ±2 weeks, per-event override | Yes | — |
| Holiday impact window | ±3 days, per-holiday override | Yes | — |
| Confidence Missing floor | 0.20 | Yes | — |
| Coverage cap, Medium | < 50% of weeks | Yes | — |
| Coverage cap, Low | < 25% of weeks | Yes | — |
| Challenge loop max iterations | 3 | Yes | — |
| RCA Generation Window | **Trailing 13 fiscal weeks** | Yes | 5,434 evaluable queue-weeks |

## Separation of Concerns

| Control | Governs | Affects RCA content |
|---|---|---|
| RCA Generation Threshold | Whether an RCA exists | Yes |
| RCA Generation Window | Which periods receive an RCA | Yes |
| Display Filter | What appears in the worklist | **No** |
| Materiality Floor | What appears in the worklist | **No** |

The Display Filter and Materiality Floor are presentation controls. They shall never create, trigger, regenerate, alter or invalidate an RCA.

---

# 5B. Confidence Model

Confidence is **CALCULATED**. It is never assigned, estimated or inferred.

## Availability Model

Every dimension resolves to one of three states before scoring:

| State | Meaning | Treatment |
|---|---|---|
| **Available** | Data present and usable | Score 0.0 to 1.0 |
| **NotApplicable** | Dimension irrelevant to this queue | Exclude, renormalise weights |
| **Missing** | Dimension relevant but data absent or invalid | Retain at Missing floor 0.20 |

### Governing Constraint

**Confidence shall never increase because evidence was lost.** A dimension may be excluded only where it is genuinely irrelevant to the queue, never where it is relevant but unavailable.

## Dimensions and Weights

| Dimension | Weight | Configurable |
|---|---|---|
| ContradictoryEvidence | **0.20** | Yes |
| EvidenceStrength | 0.18 | Yes |
| BusinessRuleValidation | 0.15 | Yes |
| StatisticalAgreement | 0.14 | Yes |
| DataSufficiency | 0.12 | Yes |
| ContextCompleteness | 0.10 | Yes |
| HistoricalConsistency | 0.06 | Yes |
| ModelAgreement | 0.05 | Yes |
| **Total** | **1.00** | |

Weights derive from the Evidence Hierarchy (MBS §9). ContradictoryEvidence carries the highest weight as the deliberate expression of *prefer Unknown over wrong with high confidence*.

## Dimension Scoring

### DataSufficiency

```
history_score  = MIN(1.0, weeks_of_actuals_for_queue / 104)
coverage_score = Weeks_With_Actuals / Weeks_In_Period    (Weekly grain = 1.0)
field_score    = 1 − (mandatory_fields_blank / mandatory_fields_expected)

DataSufficiency = (0.40 × history_score)
                + (0.40 × coverage_score)
                + (0.20 × field_score)
```

Period coverage enters the model here and only here.

### StatisticalAgreement

```
StatisticalAgreement = metrics_supporting_conclusion / metrics_executed
```

Fewer than 2 metrics executed → **NotApplicable**.

### HistoricalConsistency

Governed by BR-118 (precedent provenance weighting).

### ContextCompleteness

```
ContextCompleteness = elements_available / elements_applicable
```

| Element | NotApplicable when |
|---|---|
| Fiscal calendar | Never |
| Holiday calendar | Country is an aggregate value (BR-111) |
| Warranty coverage | Queue has no shipment exposure (BR-119) or driver fails BR-121 |
| Installed base | Queue has no ASU exposure (BR-119) or driver fails BR-121 |
| Business events | Repository not deployed or empty (BR-202) |
| Volume band | Never |
| Queue metadata | Never |

Warranty at BR-112 **Tier C** counts as **unavailable**, not NotApplicable — shipments exist and the data is broken.

### EvidenceStrength

```
EvidenceStrength = Σ(strength_i × independence_i) / Σ(independence_i)
```

Strength per five-level scale: Very Strong 1.0 · Strong 0.8 · Moderate 0.6 · Weak 0.4 · Very Weak 0.2

| Evidence source family | Independence weight |
|---|---|
| Business rule | 1.0 |
| Deterministic statistic | 1.0 |
| Analyst annotation | 1.0 |
| Historical precedent | 0.8 |
| ML attribution | 0.6 |
| Second item from a family already counted | 0.3 |

Zero evidence items → **0.0**, not Missing. An investigation with no evidence has a finding, not a gap.

### ContradictoryEvidence — inverted scale

```
ContradictoryEvidence = 1 − ( contradictory_weight
                            / (supporting_weight + contradictory_weight) )
```

Contradiction search not performed → **Missing**.

### ModelAgreement

```
ModelAgreement = methods_concurring / methods_executed
```

Fewer than 2 applicable → **NotApplicable**.

### BusinessRuleValidation

| Condition | Score |
|---|---|
| All applicable rules satisfied and supportive | 1.00 |
| All satisfied, neutral to the conclusion | 0.60 |
| A rule was not evaluable | 0.40 |
| **A business rule contradicts the conclusion** | **0.00 + Gate 2** |

## Aggregation

```
applicable = dimensions where Availability ≠ NotApplicable

Raw_Score = Σ(weight_d × score_d for d in applicable)
            ─────────────────────────────────────────
            Σ(weight_d for d in applicable)
```

## Levels

| Score | Level |
|---|---|
| ≥ 0.85 | Very High |
| 0.70 – 0.849 | High |
| 0.50 – 0.699 | Medium |
| 0.30 – 0.499 | Low |
| < 0.30 | Very Low |

## Caps

Applied after aggregation. Caps never raise confidence. Where several apply, **the lowest binds**.

| Gate | Condition | Cap |
|---|---|---|
| 1 | < 50% of applicable dimensions Available | Medium |
| 2 | A business rule contradicts the conclusion | Low |
| 3a | Coverage_Ratio < 0.50 | Medium |
| 3b | Coverage_Ratio < 0.25 | Low |
| 4 | Expected primary driver Missing | Medium |
| 5 | ContradictoryEvidence score < 0.40 | Low |
| 6 | Evidence from a single source family only | Low |
| 7 | Conclusion did not survive cross-examination (BR-117 conditions 2, 3 or 5) | Low |
| 8 | Volume Band = Emerging | Medium |

**Whenever a cap binds, the gate, the threshold crossed and the actual measured figure shall all be stated.** A bare capped number is not compliant.

## Mandatory Recording

Every calculation shall persist: each dimension's availability, score, weight and contribution; every cap evaluated and which bound; and the weights version in force. A confidence score that cannot be decomposed shall not be published.

---

# 6. RCA Trigger and Scope Rules

These rules determine whether an RCA is generated, for which periods, and how it is presented.

---

# 7. Rule BR-001

**Rule Name**

RCA Generation Threshold

**Purpose**

Determine whether a Forecast Adherence deviation warrants an RCA.

**Condition**

```
ABS(Forecast Adherence) > 5
```

**Value**

±5% — fixed at system level. Not configurable. Not exposed in the user interface.

**Action**

Generate an RCA for that queue and fiscal period.

Generation strategy:

| Adherence | Strategy |
|---|---|
| `ABS(adherence) > 10%` | **Pre-generated** in batch |
| `5% < ABS(adherence) ≤ 10%` | **Generated on first open**, then cached |
| `ABS(adherence) ≤ 5%` | No RCA |

Lazy generation for the ±5–10% band reduces up-front compute by approximately 18% of RCA scope with no change to the analyst experience.

Once generated, an RCA is immutable and cached. Reopening never regenerates.

**Constraints**

- Applies only to fiscal periods where `Actual_Offered` is available.
- Applies only within the RCA Generation Window (BR-123).
- Applies independently at Weekly, Monthly and Quarterly grain (BR-115).

**Priority**

Critical

**Note**

This rule governs RCA existence only. The user-selectable Adherence Display Filter (BR-005) governs presentation and never affects this rule.

---

# 8. Rule BR-002

**Rule Name**

Manual RCA Request

**Purpose**

Allow authorised users to initiate an RCA for a period that did not meet the RCA Generation Threshold.

**Condition**

User explicitly requests investigation for a queue and fiscal period where `ABS(Forecast Adherence) ≤ 5%`.

**Action**

Generate RCA on demand. Flag the Decision Card as "Manually Requested — below generation threshold". Set `Generation_Threshold_Met = false`.

**Constraint**

`Actual_Offered` must be available for the requested period. Manual request cannot override the actuals-availability rule.

**Priority**

High

---

# 9. Rule BR-004

**Rule Name**

Major Forecast Deviation

**Purpose**

Escalate unusually large deviations that carry real business impact.

**Condition — BOTH required**

```
ABS(Forecast Adherence) > 75
AND
ABS(Actual_Offered − fcst_offered) >= Materiality Floor for the queue's Volume Band
```

**Default**

75 percent. Configurable.

**Action**

Escalate the existing RCA to High Priority. Mark the Decision Card "Major Deviation". Bypass the **Adherence Display Filter** so the case appears regardless of the user's threshold selection.

**MATERIALITY FLOOR IS NOT BYPASSED**

Measured against reference data, bypassing the floor would badge `fcst 2 → actual 4` (adherence −75.4%, miss 2 contacts) as a Major Deviation alongside `fcst 16,675 → actual 25,168` (miss 8,493 contacts). A percentage alone cannot distinguish them. Both conditions are required.

**Measured effect**

At ±75% before the floor: approximately 35 cases per week. Distribution of `|adherence|`: p50 = 14%, p95 = 64%, p99 = 129%.

**Priority**

Critical

---

# 10. Rule BR-005

**Rule Name**

Adherence Display Filter

**Purpose**

Allow users to control which breaching periods appear in the worklist.

**Condition**

Row is displayed where `ABS(Forecast Adherence) > selected threshold`.

**Options**

±5% · ±10% · ±15% · ±20% · ±25% · ±30%

**Default**

±10%

**Selection**

**Single-select.** A symmetric band cannot be multi-selected — ±20% is a subset of ±10%.

**Constraint — mandatory**

This rule is a presentation control only. It shall never:

- create, trigger, regenerate, alter or invalidate an RCA
- change any Root Cause, Evidence, Confidence or Recommendation
- appear in RCA reasoning or narrative
- be cited as the reason an investigation exists

Because the filter minimum (±5%) equals the RCA Generation Threshold, every row reachable by the filter always has an RCA available.

**Audit**

The filter value in force when a user opened an investigation shall be recorded as investigation metadata, and shall not form part of the RCA input set.

**Priority**

Medium

---

# 11. Rule BR-115

**Rule Name**

RCA Grain

**Purpose**

Define the periods at which RCA is produced.

**Rule**

RCA shall be produced independently at three grains for every queue:

| Grain | Period | Aggregation |
|---|---|---|
| Weekly | Fiscal Week | Direct calculation |
| Monthly | Fiscal Month | Pooled over weeks with actuals |
| Quarterly | Fiscal Quarter | Pooled over weeks with actuals |

Each grain is an **independent investigation** with its own hypotheses, evidence, statistics, confidence and root cause.

**Threshold application**

The ±5% RCA Generation Threshold is evaluated independently at each grain against that grain's aggregated adherence.

A queue may breach at one grain and not another. This is expected and diagnostically meaningful:

| Pattern | Interpretation |
|---|---|
| Weekly breaches, monthly does not | Offsetting weekly errors; timing issue |
| Monthly breaches, weekly rarely does | Small consistent bias accumulating |
| All grains breach in the same direction | Systematic forecast error |

**Constraints**

1. Grains shall never be merged, averaged or reconciled against one another.
2. A monthly RCA shall not be inferred from its constituent weekly RCAs. It is computed from pooled volumes.
3. Cross-grain patterns may be cited as evidence within a grain's investigation, but a grain's conclusion shall not be substituted from another grain.

**Priority**

Critical

---

# 12. Rule BR-116

**Rule Name**

Period Horizon and Recomputation

**Purpose**

Restrict RCA to periods with actuals and govern recomputation as periods fill in.

**Horizon rule**

RCA shall be produced only for fiscal periods containing at least one fiscal week where `Actual_Offered` is available.

Future periods are **discarded entirely**. No RCA is generated, no placeholder is created, no status assigned.

Reference: actuals lag the current fiscal week by approximately four weeks.

**Aggregation scope**

Monthly and Quarterly adherence is computed using only weeks with actuals. Weeks without actuals are excluded from both numerator and denominator, and recorded in the Period Coverage Entity.

**Recomputation trigger**

When a new week of actuals lands, every Monthly and Quarterly RCA whose period contains that week shall be **recomputed**.

Recomputation creates a new RCA Case row and marks the prior row `Superseded`. Prior rows are never overwritten.

Recomputation applies the generation threshold afresh. Where a recomputed period no longer breaches, the new case is recorded with `Generation_Threshold_Met = false` and `Case_Status = Superseded`, preserving history without presenting a non-breaching period as an active investigation.

**Minimum coverage**

RCA is generated from the **first available week**. There is no minimum week count. Withholding a monthly RCA until the month completes would delay every insight by up to five weeks against an actuals lag that already costs four. Partial periods are analysed and their partiality disclosed (BR-507).

**Priority**

Critical

---

# 13. Rule BR-123

**Rule Name**

RCA Generation Window

**Purpose**

Bound RCA generation to a rolling recent window.

**Rule**

RCA shall be generated only for fiscal periods falling within the **trailing 13 fiscal weeks ending at the latest fiscal week with actuals**.

```
window_end   = MAX(Fiscal_Week WHERE Actual_Offered IS NOT NULL)
window_start = the 13th fiscal week counting back from window_end inclusive
```

Measured on reference data: window_end = 202722, window_start = 202710, containing 5,434 evaluable queue-weeks across 424 queues.

**GENERATION ONLY — evidence is unbounded**

This rule bounds which periods **receive** an RCA. It does not bound the data an RCA may reference.

| Mechanism | Reaches back |
|---|---|
| Year-over-year comparison | Prior fiscal years |
| Holiday-anchored comparison (BR-209) | Multiple prior years |
| Data Sufficiency scoring | Up to 104 weeks |
| Driver Relevance Gate (BR-121) | Full history, minimum 30 observations |
| HistoricalConsistency precedents | Full RCA history |
| Volume Band basis | Prior fiscal quarter |

**Window movement**

| Event | Effect |
|---|---|
| New week enters the window | RCA generated for that week at all three grains |
| Week already in the window | Existing RCA retained — immutable, never regenerated |
| Monthly / Quarterly period still open | Recomputed per BR-116, prior marked Superseded |
| Week falls out of the window | RCA **retained** as a historical record. Not deleted |

**Grain interaction**

| Grain | Generated where |
|---|---|
| Weekly | The fiscal week is within the window |
| Monthly | The fiscal month contains at least one week within the window |
| Quarterly | The fiscal quarter contains at least one week within the window |

A 13-week window spans one full quarter, so exactly one quarterly RCA is open at any time, and two or three monthly RCAs.

**Priority**

Critical

---

# 14. Rule BR-124

**Rule Name**

Historical RCA Retention and Re-run Governance

**Purpose**

Retain completed RCAs indefinitely, serve them on request, and govern re-runs so that repeated regeneration cannot be used to obtain a preferred conclusion.

**Retention**

A completed RCA is retained indefinitely as a historical record. Falling outside the generation window does not delete it.

**Out-of-window request**

| Condition | Response |
|---|---|
| A historical RCA exists | **Serve the historical RCA.** Do not regenerate |
| No historical RCA exists | Generate on demand, mark `Generation_Mode = Manual` |

The default is always to serve what exists. An RCA is a record of an investigation at a point in time, not a live query.

**Input Fingerprint**

Every RCA stores a fingerprint of the input data used at generation:

- `Input_Fingerprint` — hash of the contributing source rows
- `Input_Row_Count`
- `Input_Fingerprint_Computed_At`

The fingerprint covers `Actual_Offered`, `fcst_offered`, and every driver field for the period and its comparison baselines.

**Re-run request**

A re-run is permitted only on explicit request. On request the system recomputes the fingerprint and compares.

**Case A — data has changed**

Re-run proceeds. Previous RCA marked `Superseded`, retained. Decision Card states what changed:

> *"Re-run on 30 Jul 2026. Source data revised — 4 of 13 weeks restated."*

**Case B — no data change detected**

Re-run is **not refused**, but is **governed**:

1. The requester **must** supply a reason. Free text, mandatory, non-empty.
2. The re-run proceeds and is recorded as a **Governance Exception**.
3. The exception is **flagged** to the Administrator and the queue owner.
4. The reason, requester, timestamp and both RCA versions are stored for Administrator review.
5. The Decision Card carries a visible marker: *"Re-run requested without data change. Reason on record."*

**Rationale**

The engine is deterministic — temperature 0, pinned model, pinned prompt, rule-driven reasoning. A re-run on unchanged data produces the same result. A request to re-run unchanged data therefore indicates either a misunderstanding of the system or dissatisfaction with the conclusion. Both warrant a record.

This prevents repeated regeneration being used to obtain a different answer, and creates an audit trail of why a different answer was wanted.

**Priority**

High

---

# 15. Rule BR-125

**Rule Name**

Aggregate Analysis Views

**Purpose**

Provide hierarchical entry points above queue level without generating independent investigations.

**Nature — mandatory**

Levels 1 and 2 are **aggregation views**. They do not generate RCA. They pool volumes and summarise the root causes found in their child queue RCAs.

No hypotheses, evidence, statistics, cross-examination or confidence are computed at Levels 1 or 2. An aggregate view has no root cause of its own.

**Levels**

| Level | Grouping | Measured groups |
|---|---|---|
| 1 | Region + SubRegion + Country + Offering | 113 |
| 2 | + Channel | 286 |
| 3 | + Forecast_name, weekly — **RCA generated** | 427 |

**Adherence at aggregate levels**

Pooled:

```
Aggregate Adherence % = (1 − SUM(Actual_Offered) / SUM(fcst_offered)) × 100
```

**MANDATORY DISCLOSURE — net, gross and offset**

| Measure | Definition |
|---|---|
| Net variance | `ABS( SUM(Actual) − SUM(Forecast) )` |
| Gross variance | `SUM( ABS(Actual − Forecast) )` per child queue |
| Offset ratio | `(1 − Net / Gross) × 100` |

**A pooled adherence figure shall never be displayed without its offset ratio.**

Measured: 75 of 113 Level 1 groups contain queues erring in both directions. Median cancellation among multi-queue groups is 36.4%. Fifteen groups cancel more than 70%. One group shows +0.3% pooled adherence while its children produced 6,528 contacts of error.

**Systemic indicator**

| Offset ratio | Label | Interpretation |
|---|---|---|
| < 20% | **SYSTEMIC** | Children err in the same direction. Common cause likely |
| 20% – 70% | **MIXED** | Both patterns present |
| > 70% | **IDIOSYNCRATIC** | Pooled figure not meaningful. Investigate children |

Single-queue groups display no offset label.

**Ranking — mandatory**

Aggregate views shall rank by **gross variance**, not adherence percentage.

Measured: `Americas · NA · United States · Basic` carries the largest absolute error in the business — 72,186 contacts gross, 28,975 net — at −7.1% adherence, and would not appear under a ±10% percentage filter.

**Dynamic level collapse — mandatory**

```
When drilling from level N:
    IF level N+1 produces exactly ONE child group
        SKIP level N+1 and continue to the next level that subdivides
    ELSE
        display level N+1
```

Evaluated at query time against actual data. No level is collapsed by configuration.

Measured: 202 of 286 Level 2 groups (71%) contain exactly one queue. 24 of 113 Level 1 groups (21%) contain exactly one channel. 19 of 113 (17%) contain exactly one queue.

These proportions are properties of the current dataset and will change with full data. The rule is deliberately data-driven so it remains correct under any distribution.

**Breadcrumb requirement**

A collapsed level shall still appear in the navigation path:

```
Americas · NA · United States · Basic  >  Voice  >  Nordic Client DSP
```

**Root cause summarisation**

An aggregate view reports the distribution of root causes among its child RCAs, weighted by each child's contribution to gross variance. Weighting by variance rather than count prevents many small queues outvoting a few large ones.

**Confidence at aggregate level**

An aggregate view carries **no confidence score**. It reports the confidence distribution of its children.

**Materiality at aggregate level**

The Volume Band materiality floor is per-queue and does not apply. Aggregate views apply no floor — they rank by gross variance, so immaterial groups sort to the bottom naturally.

**Priority**

High

---

# 16. Data Validation Rules

These rules govern whether data is fit for investigation.

---

# 17. Rule BR-101

**Rule Name**

Mandatory Data Availability

**Condition**

Forecast and Actual data must be available for the requested period.

**Failure**

Stop investigation. Record reason.

**Priority**

Critical

---

# 18. Rule BR-102

**Rule Name**

Actuals Availability

**Condition**

`Actual_Offered` must be available for the fiscal period.

**Failure**

Stop investigation. No RCA is generated for periods without actuals (BR-116).

**Priority**

Critical

---

# 19. Rule BR-103

**Rule Name**

Queue Registration

**Condition**

The queue must exist in Queue Master.

**Note**

Queue Master is **derived** from the source dataset, so this rule is satisfied automatically for any queue present in the data. It remains as a guard against orphaned references.

Where the queue has lineage (rename, merge or split), history resolves through the Queue Lineage entity.

**Priority**

High

---

# 20. Rule BR-104

**Rule Name**

Fiscal Calendar Validity

**Condition**

The fiscal period must exist in the Fiscal Calendar and the fiscal year must be classified (BR-114).

**Failure**

Stop investigation.

**Priority**

Critical

---

# 21. Rule BR-105

**Rule Name**

Historical Data Sufficiency

**Condition**

Sufficient historical data must exist for statistical analysis.

**Recommended minimum**

104 fiscal weeks. Configurable.

**Failure**

Reduce confidence via the `DataSufficiency` dimension and state the reason. For Emerging queues the outcome is governed by BR-207: **reduce confidence, never stop investigation**.

**Measured**

18 of 427 queues (4.2%) hold fewer than 104 weeks of actuals. Minimum observed is 39 weeks.

**Priority**

High

---

# 22. Rule BR-106

**Rule Name**

Data Consistency

**Condition**

Forecast and Actual values must be numerically consistent and free of type errors.

**Failure**

Flag and exclude the affected field. Continue with reduced confidence.

**Priority**

High

---

# 23. Rule BR-107

**Rule Name**

Negative Value Validation

**Condition**

Forecast or Actual values are negative.

**Action**

Reject investigation.

**Measured**

Zero negative values in reference data across 138,775 rows.

**Priority**

Critical

---

# 24. Rule BR-108

**Rule Name**

Missing Mandatory Fields

**Mandatory fields**

- Queue (`Forecast_name`)
- Fiscal Week
- Forecast (`fcst_offered`)
- Actual (`Actual_Offered`)

**Failure**

Stop investigation.

**Priority**

Critical

---

# 25. Rule BR-109

**Rule Name**

Data Freshness

**Condition**

Latest actuals available.

**Failure**

Warn user. Reduce confidence.

**Note**

Actuals lag the current fiscal week by approximately four weeks in reference data. This is expected and is disclosed via the Timeline callout rather than treated as a failure.

**Priority**

Medium

---

# 26. Rule BR-110

**Rule Name**

Non-Computable Adherence

**Condition**

`fcst_offered = 0` or `fcst_offered` is blank.

**Result**

Forecast Adherence is undefined. Division by zero.

**Action**

Exclude the row from adherence calculation and from all monthly and quarterly aggregates. Flag in the Data Availability Callout. Do not generate an RCA for that period.

**Constraint**

No substitution, imputation or default value. The period is reported as non-computable.

**Measured**

50 rows in reference data.

**Priority**

Critical

---

# 27. Rule BR-111

**Rule Name**

Reserved Literal Preservation

**Purpose**

Prevent valid business values being destroyed by automatic null interpretation.

**Background**

SubRegion `NA` means North America. It is a valid business value, not a null. `NA` is a default null-marker in Python, Excel, Power BI and most ETL tooling. Read with default settings it silently becomes blank — affecting **16,250 rows (11.7%)** of reference data, with no error raised.

**Action**

1. Disable automatic NA-string interpretation on all text columns at read.
2. Normalise `NA` to the canonical stored value **`NorthAm`**. `NorthAm` is not a null-marker in any common tool, so the collision cannot recur.
3. Apply rule 1 at every hop — ingestion, export, refresh, round-trip.
4. Assert post-load: `COUNT(SubRegion IS NULL)` must equal zero.

**Accepted aliases**

| Canonical | Accepted input forms |
|---|---|
| `NA` → `NorthAm` | `NA` · `NorthAm` · `North America` · `North Americas` |
| `Americas` | `AMER` |
| **`south korea`** | **`korea`** · `Korea` · `KOREA` · `South Korea` · `Republic of Korea` |

**Note on Korea**

`INPUT_TO_ML` uses `korea`; the holiday master uses `south korea`. Without this alias the join fails **silently** and every Korean holiday week reports as unexplained.

Measured effect: day-pattern agreement for Korea rose from **0% to 95.4%** across 65 country-weeks on adding this single alias.

**North Korea is OUT OF SCOPE.** The holiday master value `north-korea` shall not be aliased to `south korea` and shall not resolve to any queue.

Alias normalisation executes **before** unmapped-value detection, so an alias never registers as a new dimension member.

**Aggregate values**

The following are deliberate multi-entity groupings, valid and fully analysed, but cannot be resolved against the country-level holiday master:

- SubRegion: `Multiple AMER SubRegions` · `Multiple EMEA SubRegions`
- Country: `North America` · `ROLA` · `Multiple AMER Countries` · `Multiple EMEA Countries`

For these, holiday context is **NotApplicable** — no confidence penalty. Approximately 4.2% of reference data.

**Measured confirmation**

Tested against `INPUT_TO_ML` using the member composition confirmed by the Product Owner:

| Aggregate value | Country-weeks | Weeks with `Holiday_Count` > 0 |
|---|---|---|
| `north america` | 93 | **0** |
| `multiple amer countries` | 230 | **0** |
| `multiple emea countries` | 148 | **0** |

**Zero in all 471 weeks.** The individual member countries validate normally — United States 94.3%, Canada 95.2% — so the underlying holiday data is sound.

The source system does not populate holiday context for these aggregate queue groups. NotApplicable with no penalty is therefore the correct treatment, and is now evidence-based rather than inferred.

**Unmapped Value Alert**

A new dimension value is accepted and immediately usable, flagged in the Data Availability Callout, and surfaced to the Administrator. The Region → SubRegion mapping updates automatically. **A SubRegion can never exist without a Region** — an orphan SubRegion is a validation failure and is rejected.

**Failure**

Reject the load. Do not proceed with silent data loss.

**Priority**

Critical

---

# 28. Rule BR-112

**Rule Name**

Warranty Structure Validation

**Purpose**

Prevent structurally invalid warranty data producing a confident but incorrect Warranty Mix conclusion.

**Scope**

Evaluated per row at ingestion. Result stored on the Shipment Plan Entity as `Warranty_Validation_Tier`.

## Tier A — PASS

**Conditions, all required**

- `Final_Y1 ≤ Final_Units`
- `Final_Y1 ≥ Final_Y2 ≥ Final_Y3 ≥ Final_Y4 ≥ Final_Y5`
- No negative values

**Action** — warranty data fully usable. Warranty Mix hypothesis available. No confidence penalty. `Final_Units − Final_Y1` treated as no-warranty shipments.

## Tier B — WARN

**Condition** — `Final_Y1` exceeds `Final_Units` by no more than `MAX(2 units, 0.5% of Final_Units)`. Nesting intact, no negatives.

**Action**

- **Clamp** `Final_Y1` to `Final_Units`
- Proceed with warranty analysis
- **Flag** in the Data Availability Callout
- Apply a **small** confidence penalty via `ContextCompleteness`
- Record reason: *"Warranty totals reconciled — minor source discrepancy"*

## Tier C — FAIL

**Conditions, any one**

- `Final_Y1 > Final_Units` beyond the Tier B tolerance
- **Nesting inverted** anywhere — e.g. `Final_Y3 > Final_Y2`, structurally impossible
- Any negative value

**Action**

- **Suppress the Warranty Mix hypothesis entirely** for that row
- **Exclude** `Final_Units` and `Final_Y1`–`Final_Y5` from correlation and feature attribution
- **Flag prominently** with the specific failure reason
- **Reduce confidence** with an explicitly stated cause
- **Continue** the RCA on all other hypotheses

**MANDATORY CONSTRAINT**

No repair. No substitution. No interpolation. No default values.

Where warranty was the expected primary driver, the Decision Card shall state explicitly:

> *"Warranty data unavailable for this period (source structure invalid). The expected primary driver could not be evaluated. Analysis proceeded on alternative hypotheses at reduced confidence."*

**Measured distribution**

| Tier | Rows | Share |
|---|---|---|
| A — PASS | 74,621 | 79.8% |
| B — WARN | 4,059 | 4.3% |
| C — FAIL | 14,850 | 15.9% |
| **Usable (A + B)** | **78,680** | **84.1%** |

By offering: Premium 0.0% Tier C · Pro 0.9% · OOP 16.5% · **Basic 32.0%**. Basic is the offering for which shipments are the stated primary driver and has the weakest warranty data.

**Priority**

Critical

---

# 29. Rule BR-113

**Rule Name**

Volume Band Derivation

**Purpose**

Classify each queue by demand size to support materiality assessment and segmentation.

**Execution schedule**

Executed in **FW01, FW14, FW27 and FW40** only — the first fiscal week of each fiscal quarter.

**Basis**

```
weeks_in_quarter = 14  IF previous quarter = Q4 AND weeks_in_FY = 53
                 = 13  otherwise

basis_weeks = weeks_in_quarter WHERE Actual_Offered IS NOT BLANK

avg_weekly_volume = SUM(Actual_Offered over basis_weeks) / COUNT(basis_weeks)
```

**Rules**

1. Metric is `Actual_Offered` only. Never `fcst_offered`, never `Actual_Handled`.
2. Blank weeks are excluded from **both** numerator and denominator.
3. `Actual_Offered = 0` is a **real observation** and is included in both.
4. `weeks_in_FY` is determined per BR-114.

**Band assignment**

| avg_weekly_volume | Volume_Band | Materiality Floor |
|---|---|---|
| 0 – 100 | `<=100` | 10 contacts |
| >100 – 250 | `101-250` | 25 |
| >250 – 500 | `251-500` | 50 |
| >500 – 1,000 | `501-1000` | 100 |
| >1,000 – 5,000 | `1001-5000` | 200 |
| >5,000 | `>5000` | 500 |
| No basis weeks | `Emerging` | 10 (or band matching observed volume) |

**Effective period**

The band applies for the **entire quarter** in which it was calculated. Never recalculated mid-quarter.

**Correction mechanism**

A band calculated wrongly is corrected by writing a **new superseding row**, never by overwriting. This distinguishes:

- **Volume shifted** — normal quarterly change. Both rows correct for their own period
- **Calculated wrongly** — a defect. The prior row is marked superseded with a reason, and RCAs that used it can be identified and re-run

**Transparency**

The basis window shall be displayed wherever the band appears:

```
Volume Band: 501-1000
Basis: FY27 Q1, FW01–FW10 (10 of 13 weeks)
```

Because actuals lag by approximately four weeks, the previous quarter is typically 70–80% complete at recalculation time. This is expected and disclosed rather than corrected.

**Note**

The source dataset contains a `Volume_Category` field. It is **not used** — source boundaries overlap at 250, leave a gap between 100 and 101, and 16.6% of rows are blank.

**Priority**

High

---

# 30. Rule BR-114

**Rule Name**

Fiscal Year Week Count

**Purpose**

Determine the number of fiscal weeks in a fiscal year, governing the Q4 month pattern and quarter length.

**Derivation**

```
weeks_in_FY = MAX(Fiscal_Week_Number) observed for that Fiscal_Year
```

`MAX` is used rather than `COUNT(DISTINCT)` because a fiscal year may be only partially represented. In reference data FY2022 contains only FW49–52; `COUNT(DISTINCT)` returns 4 and misclassifies it, `MAX` correctly returns 52.

**Classification**

| weeks_in_FY | Classification | Q4 month pattern | Q4 length |
|---|---|---|---|
| 53 | 53-week year | **4-5-5** | 14 weeks |
| 52 | 52-week year | 4-4-5 | 13 weeks |
| < 52 | In progress | Not yet classified | n/a |

**Constraint**

A fiscal year is classified only once `weeks_in_FY ≥ 52`. Below that it is in progress, and month mapping applies only to weeks present.

**Reference**

FY2023 is the only 53-week year in reference data. Its Q4 spans FW40–FW53, with M11 (December) holding five weeks (FW44–48) and M12 (January) holding five (FW49–53).

**Priority**

Critical

---

# 31. Rule BR-119

**Rule Name**

ASU and Shipment Applicability

**Purpose**

Exclude installed-base and shipment dimensions where they do not apply to the queue, without penalising the investigation.

**Condition**

Offering indicates out-of-warranty support:

```
Offering IN (PON, OOP, OOW, Out-of-Warranty)
```

A reference list, extensible, not a hard validation rule.

**Action**

Set `ASU_Applicable = false` and `Shipment_Applicable = false`.

The following are **NotApplicable**, not missing:

- `Planned_ASU`, `Actual_ASU`
- `Final_Units`, `Final_Y1` to `Final_Y5`
- Warranty exclusive bands
- BR-204 Installed Base Change hypothesis
- BR-205 Warranty Mix Shift hypothesis
- BR-208 ASU Plan Variance hypothesis

**Confidence treatment**

NotApplicable dimensions are excluded from `ContextCompleteness` and the remaining weights renormalised. **No confidence penalty applies.**

**Disclosure**

The Decision Card shall state that these drivers are **not applicable**, and shall not describe them as unavailable or missing. Those words imply a limitation where none exists.

**Consequence**

Out-of-warranty queues have no product-side demand driver. Their RCA draws on calendar effects, holiday effects, volume patterns and data quality only. Root causes will be structurally narrower than for warranty-bearing offerings. A known limitation of current data, to be revisited in a later phase.

**Scope**

11,937 rows in reference data (8.6%).

**Priority**

High

---

# 32. Rule BR-121

**Rule Name**

Driver Relevance Gate

**Purpose**

Apply a demand driver to a queue only where that driver has demonstrated a relationship with that queue's demand.

**Rationale**

Driver relevance varies materially by queue. Measured on reference data, only 18% of queues show meaningful correlation between shipment volume and demand, and 18% for warranty coverage share, against 55% for installed base. Applying a driver universally means building hypotheses on a variable that does not move with demand in four cases out of five.

This implements the principle already stated in the Definitions document: drivers apply *"provided it has a good correlation"*.

**Gate**

```
Driver is RELEVANT for a queue where:

    ABS( correlation(driver, Actual_Offered) ) >= 0.3
    over at least 30 observations within the retained history window
```

Default threshold 0.3, minimum observations 30. Both configurable.

**Driver cascade — business order preserved**

The gate determines whether a driver is **usable**, never the order drivers are tried in. Business causality sets the order.

| Offering | Cascade |
|---|---|
| **Basic** | **Shipments** → ASU → next metric |
| Premium, Pro | ASU → Shipments → next metric |
| OOP / out-of-warranty | Neither applies (BR-119) → calendar, volume, data quality |

Where a driver fails the gate, the cascade moves to the next driver. It never reorders. A low average pass rate does not demote a business-correct driver for the queues where it works.

**Effect where a driver fails**

The associated hypothesis is **not generated**. The driver is excluded from correlation and feature attribution for that queue. This is a **NotApplicable** state — no confidence penalty.

**Evaluation**

Recalculated on the same schedule as the Volume Band — FW01, FW14, FW27, FW40 — and stored with effective dating, so a historical RCA resolves the relevance state in force at its time of generation.

**Measured pass rates**

| Driver | Queues passing |
|---|---|
| `Actual_ASU` | 236 of 427 — **55%** |
| `Final_Units` | 76 of 427 — 18% |
| Warranty band share | 78 of 427 — 18% |
| **All three fail** | **139 of 427 — 33%** |

**Disclosure**

The Decision Card shall state which drivers were excluded by relevance and the measured correlation:

> *"Warranty coverage was not evaluated for this queue: correlation with demand is 0.08 over 235 weeks, below the 0.3 relevance threshold."*

**Relationship to BR-208**

BR-208 uses a **separate** gate — correlation between ASU adherence and contact adherence, threshold 0.3, measured pass rate 16%. That rule concerns whether a *plan miss* explains a *forecast miss*. BR-121 concerns whether a driver *level* tracks demand.

**Priority**

High

---

# 33. Rule BR-122

**Rule Name**

Interior Blank Week Treatment

**Purpose**

Distinguish a reporting gap from a genuinely inactive queue.

**Definitions**

| Position | Treatment |
|---|---|
| Blank **before** the queue's first actual | Pre-launch — excluded |
| Blank **after** the queue's last actual | Future — excluded |
| Blank **between** actuals, run ≤ **3 weeks** | **Treated as zero** |
| Blank **between** actuals, run > **3 weeks** | **Queue inactive** — excluded |

**Interior blanks, ≤ 3 consecutive weeks**

`Actual_Offered` is set to 0. The week becomes a real observation:

- Adherence computes as +100% (full over-forecast)
- The week counts in the Volume Band denominator
- The week counts toward period coverage
- The zero-fill is **flagged** in the Data Availability Callout

**Interior blanks, > 3 consecutive weeks**

The queue is marked **inactive** for that span — excluded from adherence, Volume Band, coverage and history depth. No RCA generated. The inactive span is recorded and disclosed.

**Measured**

550 interior blank weeks across 55 of 427 queues. Median run length 3 weeks; maximum 78 weeks.

Zero-filling 3 weeks asserts a plausible reporting gap or a genuinely quiet period. Zero-filling 78 weeks would assert that a queue received no contacts for 18 months, which then propagates into Volume Band, adherence and history depth.

**Priority**

High

---

# 33A. Rule BR-126

**Rule Name**

Cross-Year Holiday Drift Detection

**Purpose**

Detect corrupted holiday dates that the weekday check cannot identify, specifically day/month transpositions where both readings fall on the same weekday.

**Why this rule is needed**

`BR-201` and the Holiday Calendar entity validate that the stated weekday matches the date. **That check cannot detect a transposition where both readings share a weekday.**

All 29 transpositions found in the reference holiday master were of this kind:

| Stored | True date | Both weekdays |
|---|---|---|
| `11-JAN-2021` | `01-NOV-2021` | Monday |
| `08-FEB-2021` | `02-AUG-2021` | Monday |
| `01-JUN-2024` | `06-JAN-2024` | Saturday |

The `Day` column agrees with either reading, so it cannot discriminate. Only a cross-year pattern check finds them.

**Rule**

A named holiday shall not move more than **one calendar month** between fiscal years for the same country.

```
FOR each (Country, Canonical_Name) with >= 2 observations:
    month_spread = circular distance between earliest and latest month
    IF month_spread > 1 AND Calendar_Basis is Gregorian:
        FLAG the outlier rows
```

**Exemption — by CALENDAR BASIS, not by country**

| `Calendar_Basis` | Subject to rule | Reason |
|---|---|---|
| Gregorian — fixed or rule-based | **YES** | Should not move months |
| Gregorian — Easter-derived | **YES** | Computable; bounded drift |
| Islamic | No | Hijri calendar; ~11 days/year earlier |
| Lunar / Traditional | No | Chinese, Hindu, Buddhist, Thai calendars |
| Hebrew | No | Hebrew calendar |
| Election-dependent | No | Set by decree |

Exemption is **data-driven, not a country blocklist.** A Gregorian-fixed holiday in India — Republic Day, 26 January — remains subject to the rule, while Diwali in the same country is exempt. A country list would wrongly exempt both.

**Action on violation**

Per the missing-data principle (D3):

1. **FLAG** the row and record the expected month range
2. **EXCLUDE** the row from holiday interpretation until reviewed
3. **SURFACE** to the Administrator with the drift measurement
4. **CONTINUE** the load. The row is **not deleted**

Consistent with the base-file principle: nothing a source system asserts is silently discarded.

**Measured effect**

On the reference holiday master of 12,197 rows:

| Group | Rows | Share |
|---|---|---|
| Subject to the rule | 8,092 | 66.3% |
| Exempt — non-Gregorian basis | 4,105 | 33.7% |

**All 29 known transpositions carry a Gregorian basis**, so the rule would have detected every one. No exempt holiday would have been falsely flagged.

**Priority**

High

---

# 34. Business Context Rules

These rules retrieve and evaluate business context that may explain a deviation.

---

# 35. Rule BR-201

**Rule Name**

Holiday Impact

**Purpose**

Determine whether holidays contributed to the deviation.

**Condition**

`Holiday_Count > 0` for the fiscal period, or the period falls within a holiday's impact window.

**Holiday impact window**

| Attribute | Default | Configurable |
|---|---|---|
| `Impact_Days_Before` | 3 | **Per holiday** |
| `Impact_Days_After` | 3 | **Per holiday** |

Diwali may influence contact demand for several days either side; a bank holiday may not. Per-holiday configuration is required.

**Action**

Generate the Holiday hypothesis. Retrieve the holiday name, day of week and impact window. Apply holiday-anchored comparison per BR-209.

**Constraint**

Where Country is an aggregate value, holiday context is **NotApplicable** (BR-111) — no confidence penalty.

**Priority**

High

---

# 36. Rule BR-202

**Rule Name**

Business Event Detection

**Purpose**

Identify business events that may explain a deviation.

**Availability — the Event Repository is OPTIONAL**

| Repository state | Treatment | Confidence |
|---|---|---|
| Not deployed, or empty | **NotApplicable** | No penalty |
| Populated, no event matches the period | **Available** — result is "no event found" | No penalty |
| Populated, retrieval failed or data stale | **Missing** | Penalty |

The middle row is the important distinction. *"No event found"* is a **result**, not a gap. The Event hypothesis was tested and rejected. Confidence shall not fall for successfully ruling something out.

This means the repository may remain unpopulated indefinitely without depressing confidence, and begins contributing the moment an event is entered.

**Matching Window**

| Attribute | Default | Configurable |
|---|---|---|
| `Impact_Weeks_Before` | 2 | **Per event** |
| `Impact_Weeks_After` | 2 | **Per event** |

Per-event configuration is required because impact duration varies — a product launch may influence demand for five weeks, a system outage for one.

**Population**

Manual entry via the Administration Portal in Phase 1. Automated ingestion, event correlation, impact scoring and similarity detection are Phase 2.

**Priority**

Medium

---

# 37. Rule BR-203

**Rule Name**

Historical RCA Search

**Purpose**

Retrieve similar historical investigations eligible to serve as evidence.

**Condition — structural match**

A prior investigation exists with a matching `Forecast_Name`, or matching `SubRegion` and `Offering`, or a matching business event.

Similarity is **structural** in Phase 1:

| Match level | Criteria | Strength |
|---|---|---|
| Exact | Same `Forecast_name`, same fiscal period prior year | Strongest |
| Strong | Same `Forecast_name`, any prior period, same direction | Strong |
| Moderate | Same `SubRegion` + `Offering` + `channel`, similar magnitude | Moderate |
| Weak | Same `Offering` only | Weak |

Semantic similarity via embeddings is Phase 2.

**Condition — eligibility gate, ALL required**

| # | Requirement |
|---|---|
| 1 | `Case_Status = Completed` |
| 2 | `Confidence_Level ≥ Medium` |
| 3 | Not `Superseded` by a later recomputation |
| 4 | `Generation_Threshold_Met = true` |

**Action**

Retrieve eligible precedents. Each is returned with its own confidence level, which weights its contribution per BR-118.

**Ineligible precedents**

Not retrieved as evidence. May be surfaced to an analyst on request, clearly marked non-evidential, and shall not affect `HistoricalConsistency` scoring or hypothesis prioritisation.

**Exemption**

Analyst annotations (BR-120) are **not** subject to this gate. It governs machine-generated conclusions, whose confidence is self-assessed. A human annotation carries external verification.

**Constraint**

Historical similarity strengthens contextual understanding but shall never replace fresh analysis. A precedent is evidence about the past, not a conclusion about the present.

**Priority**

High

---

# 38. Rule BR-204

**Rule Name**

Installed Base Change Hypothesis

**Purpose**

Generate a hypothesis where the serviceable installed base changed materially.

**Precondition**

`ASU_Applicable = true` (BR-119) **and** ASU passes the Driver Relevance Gate (BR-121). `Actual_ASU` available for the period and the comparison baseline.

**Condition**

```
ABS(Actual_ASU year-over-year change %) > 20
```

Evaluated at the **RCA's own grain** against the same fiscal period in the prior year.

**Growth and decline both qualify.** A shrinking serviceable base reduces support demand exactly as a growing base increases it.

**Secondary condition**

```
ABS(Actual_ASU month-over-month change %) > 5
```

A sharp month-on-month move is notable even where year-over-year is flat.

**Defaults**

20 percent year-over-year, 5 percent month-over-month. Configurable.

**Comparison basis — measured**

| Basis | p50 | p90 | Fires at threshold |
|---|---|---|---|
| Week-over-week | 0.3% | 1.3% | ±10% → **0.3%** |
| Month-over-month | 1.0% | 4.6% | ±5% → 8.8% |
| **Year-over-year** | **10.2%** | **41.2%** | ±20% → **27.3%** |

Week-over-week comparison is **withdrawn**. ASU is a slow-moving stock and does not move week to week.

**Action**

Generate the Installed Base Change hypothesis. State direction: *"serviceable base expanded"* or *"serviceable base contracted"*. Execute contemporaneous correlation and regression.

**Note**

ASU is a **stock**. Growth is computed on the weekly average level, never on a sum.

**Priority**

High

---

# 39. Rule BR-205

**Rule Name**

Warranty Mix Shift Hypothesis

**Purpose**

Generate a Warranty Mix Shift hypothesis where coverage distribution changed materially.

**Precondition — mandatory**

`Warranty_Validation_Tier` is A or B (BR-112) **and** `Shipment_Applicable = true` (BR-119) **and** warranty passes the Driver Relevance Gate (BR-121).

Where Tier is C: record *"Warranty Mix hypothesis suppressed — source structure invalid."*

**Condition**

```
ABS(band_share_current − band_share_baseline) > 10 percentage points
```

Bands are the six exclusive bands. Shares are computed with `Final_Units` as denominator.

**Default**

10 percentage points. Configurable.

**Measured**

| Threshold | Fires on |
|---|---|
| 2pp | 36.8% |
| 5pp | 25.5% |
| **10pp** | **16.0%** |
| 15pp | 10.9% |

Distribution: median 0.5pp, p75 5.2pp, p90 16.4pp — highly skewed.

**Baseline**

Same fiscal period in the prior year where available; otherwise the trailing 13-week mean. **The baseline used shall be stated in the evidence.**

**Action**

Generate the hypothesis. Execute Trend, Correlation and SHAP analysis on **exclusive bands only**.

**CONSTRAINT**

Statistical analysis shall never be executed on raw `Final_Y1`–`Y5` values. Nested values are not independent variables — `Y2` is contained within `Y1`, so correlating both produces spurious multicollinearity and uninterpretable attribution.

**Priority**

High

---

# 40. Rule BR-206

**Rule Name**

Business Context Completeness

**Condition**

All applicable business context elements have been retrieved.

**Action**

Record which elements were available, missing or not applicable. Feed the `ContextCompleteness` dimension.

**Priority**

Medium

---

# 41. Rule BR-207

**Rule Name**

Emerging Queue Handling

**Purpose**

Ensure new queues receive RCA rather than being excluded for lack of history.

**Condition**

`Volume_Band = Emerging` — no prior-quarter actuals available.

**Action**

1. **Produce the RCA** using whatever data is available. Do not skip.
2. State the available history explicitly in the Data Availability Callout.
3. Reduce confidence in proportion to data sufficiency and state the reason.
4. Apply the Emerging materiality floor: the floor of the band matching observed volume to date, defaulting to 10 contacts.
5. **Suppress** hypotheses requiring historical baselines — seasonality, year-over-year comparison, drift, warranty mix shift against a prior-year baseline. Record as **suppressed**, not rejected.

**Reclassification**

At the next quarterly recalculation the queue receives a numeric band. Historical RCAs keep the band in force at their time of generation.

**Interaction with BR-105**

An Emerging queue necessarily fails BR-105. Under this rule the outcome is **reduce confidence**, never stop investigation.

**Priority**

High

---

# 42. Rule BR-208

**Rule Name**

ASU Plan Variance Hypothesis

**Purpose**

Determine whether the forecast was built on an installed-base assumption that did not materialise.

**Rationale**

`Planned_ASU` is the serviceable base assumed when the forecast was produced. `Actual_ASU` is what materialised. Where they diverge materially, the forecast rested on a demand base that proved wrong — a direct and quantifiable explanation rather than a correlation.

**Precondition**

`ASU_Applicable = true` (BR-119). Both `Planned_ASU` and `Actual_ASU` available. **And** the queue passes this rule's own relevance gate:

```
ABS( correlation(ASU adherence, contact adherence) ) >= 0.3
over at least 30 observations
```

Measured pass rate: **16% of queues** (53 of 341 tested). Where the gate fails, the hypothesis is **NotApplicable** — no confidence penalty.

**Condition**

```
ASU Adherence % = (1 − (Actual_ASU / Planned_ASU)) × 100

ABS(ASU Adherence) > 20
```

Same formula and sign convention as Forecast Adherence — `Planned_ASU` is a forecast and is treated as one.

**Default**

20 percent. Configurable.

**Measured**

Median ASU Adherence is **+1.3%** — the ASU forecast is typically accurate. Tails are wide: p05 −56.8%, p95 +98.3%. At ±20%, fires on 34.8% of rows before the relevance gate.

**Directional Coherence Test**

| ASU variance | Expected adherence | Interpretation |
|---|---|---|
| Positive | Negative (under-forecast) | More serviceable units than planned → more demand than forecast |
| Negative | Positive (over-forecast) | Fewer serviceable units than planned → less demand than forecast |

Where directions are coherent, the hypothesis carries strong supporting evidence. Where opposite, the hypothesis is recorded with **contradictory evidence** and shall not be accepted without an explanation of the divergence. Coherence is **flagged**, not capped — a genuine explanation may exist.

**Action**

Generate the hypothesis. State both figures and the variance in business language:

> *"The forecast assumed 100,000 serviceable units under warranty. 120,000 materialised — 20% above plan. Adherence for the period was −18%, consistent in direction with a demand base larger than assumed."*

**Availability**

Where either value is blank (44% and 34% of rows respectively), the hypothesis is **suppressed**, not rejected. Recorded with the reason.

**Priority**

High

---

# 43. Rule BR-209

**Rule Name**

Holiday-Anchored Comparison

**Purpose**

Compare periods against the correct historical equivalent where a moving holiday is present, rather than against the same fiscal week.

**Mechanism**

```
STEP 1  Read Holiday_Count and the seven day indicators for the period.
STEP 2  If Holiday_Count > 0, resolve the holiday NAME and its day of week
        from the Holiday master, keyed on Country + Fiscal Week.
STEP 3  Locate the same holiday name, same country, in prior fiscal years.
        Retrieve its fiscal week and day of week in each.
STEP 4  Anchor the historical comparison on the HOLIDAY, not the fiscal week.
STEP 5  Record any day-of-week difference between the periods.
```

**Comparison Modes**

| Mode | Anchor | Applied when |
|---|---|---|
| Calendar-anchored | Same fiscal week | Default, no holiday present |
| **Holiday-anchored** | Same named holiday | `Holiday_Count > 0` in either period |

Where both are available and **disagree, both shall be reported.** If the calendar-anchored prior period was ordinary and the holiday-anchored prior period contained the holiday, that difference is itself the finding.

**Anchor date basis — mandatory**

Holiday-anchored comparison shall use the **ACTUAL** holiday date.

`Observed_Date` records weekend substitution. It is **supplementary context** for explaining volume shifts and shall **not** drive period comparison.

**Measured basis** — day-pattern agreement between the holiday master and the `INPUT_TO_ML` day flags, across 4,028 country-weeks:

| Anchor basis | Exact day-pattern match |
|---|---|
| **ACTUAL date** | **71.3%** |
| Observed date | 66.3% |

The operational system encodes actual holiday dates. Anchoring on observed dates would introduce a systematic 5-point divergence from the source of truth.

Both dates are retained on every holiday row. Only the actual date anchors comparison.

**Measured drift**

| Holiday | Country | Fiscal week by year |
|---|---|---|
| **Diwali** | India | FY23 FW39 · FY24 FW41 · FY25 FW39 · FY26 FW38 · FY27 FW41 · FY28 FW39 |
| **Eid al-Fitr** | UAE | FY23 FW14 · FY24 FW11 · FY25 FW10 · FY26 FW09 · FY27 FW07 · FY28 FW06 |

Diwali drifts up to **3 fiscal weeks**. Eid drifts **8 weeks over six years**, following the lunar calendar. Comparing FY27 FW41 against FY26 FW41 for an India queue compares Diwali week against an ordinary week.

**Multi-day holidays**

Where a holiday spans multiple days and straddles two fiscal weeks, the anchor is the week containing the **first day**. The straddle is recorded.

**Day-of-week difference**

**Recorded and flagged, not quantified.** Diwali falls Monday, Sunday, Thursday, Monday, Sunday, Friday across the years above. A holiday at a weekend has different contact impact than midweek, but quantifying it requires an empirical coefficient per queue that has not been established.

**Name synonyms**

Holiday names vary — "Diwali", "Deepavali", "Diwali/Deepavali". A maintained synonym set is required. 657 distinct holiday names exist across 79 countries in CY2022+ reference data.

**Unresolvable countries**

Where Country is an aggregate value, holiday context is **NotApplicable** (BR-111).

**Priority**

High

---

# 44. Rule BR-120

**Rule Name**

Analyst Annotation

**Purpose**

Capture analyst knowledge that cannot be derived from data, and make it available to future investigations.

**Scope**

Analysts may record an annotation against any RCA: agreement, disagreement, additional context, or a business explanation the engine could not know.

**Analysts may NOT modify an RCA.** A machine-generated conclusion carrying a machine-calculated confidence score must retain its auditable derivation. An analyst who disagrees records the disagreement and their reasoning; the RCA may then be re-run under BR-124.

**Storage**

Annotations are stored as **Business Observations**.

**Attributes**

`Annotation_ID` · `RCA_Case_ID` · `Forecast_Name` · `Fiscal_Week` · `Annotation_Type` (Agree / Disagree / AdditionalContext) · `Annotation_Text` · `Author` · `Created_At`

**Retrieval as evidence**

Retrievable by future investigations on the same queue. **Provenance weight 1.00** — the highest available, as human-verified evidence. Exempt from the BR-203 confidence eligibility gate.

**Display requirement**

An annotation retrieved into a later RCA is displayed as a **normal comment** in the narrative, not as a system citation.

Alongside it, a clickable provenance control shall reveal:

```
Source     RCA FY27 FW18, Nordic Client DSP
Author     [name], recorded 12 Jun 2026
Why        Retrieved because it references the same queue and a
           related root cause category
Impact     Supports the Queue Migration hypothesis; contributed to
           EvidenceStrength
```

All four fields are required.

**NO AUTONOMOUS LEARNING**

Annotations do not adjust the model, prompts, hypothesis weights or thresholds. They become retrievable evidence — nothing more. The engine produces better RCAs because it has access to more evidence, not because it changed itself.

**Priority**

High

---

# 45. Investigation Rules

---

# 46. Rule BR-301

**Rule Name**

Minimum Hypotheses

**Condition**

At least three candidate hypotheses shall be generated where the catalogue yields three applicable entries.

**Note**

Hypotheses are generated deterministically from the Candidate Hypothesis Catalogue. Where fewer than three entries are applicable, the shortfall and its reasons are recorded.

**Priority**

High

---

# 47. Rule BR-302

**Rule Name**

Evidence Requirement

**Condition**

Every hypothesis shall have supporting or contradictory evidence collected before evaluation.

**Priority**

Critical

---

# 48. Rule BR-303

**Rule Name**

Bias Avoidance

**Condition**

The investigation shall not favour a hypothesis on the basis of familiarity or precedent frequency.

**Enforcement**

BR-118 caps `HistoricalConsistency` at the confidence of the precedent cited, making confidence inflation through repeated citation arithmetically impossible.

**Priority**

High

---

# 49. Rule BR-304

**Rule Name**

Contradictory Evidence Requirement

**Condition**

Contradictory evidence shall be actively sought for every hypothesis, not only supporting evidence.

**Failure**

The `ContradictoryEvidence` dimension is scored **Missing** (0.20). Omitting the search is a weakness, not a neutral outcome.

**Priority**

Critical

---

# 50. Rule BR-305

**Rule Name**

Recursive Reasoning Requirement

**Condition**

Recursive root cause reasoning shall execute before cross-examination.

**Constraint**

Bounded by the configurable maximum reasoning depth. Each level records question, answer, supporting evidence, confidence, decision and termination reason.

**Priority**

Critical

---

# 51. Rule BR-306

**Rule Name**

Inconclusive Permitted

**Condition**

Where no defensible root cause exists, the investigation concludes `Inconclusive`.

**Constraint**

This is a valid outcome, not a failure. Preferring *Unknown* over *wrong with high confidence* is a governing principle.

**Priority**

Critical

---

# 52. Rule BR-117

**Rule Name**

Challenge Loop Termination

**Purpose**

Bound the cross-examination challenge loop so it terminates deterministically and reproducibly.

**Scope**

Applies to the Recursive Challenge Loop, **not** to recursive root cause depth, which is bounded separately.

**Termination conditions — the loop ends when ANY is met**

| # | Condition | Test |
|---|---|---|
| 1 | Conclusion survives a full challenge round | No weakness detected |
| 2 | Maximum iterations reached | `iteration_count ≥ 3` |
| 3 | No new evidence retrieved in an iteration | Mechanical — see below |
| 4 | All challenge questions exhausted | Question pool depleted |
| 5 | Conclusion rejected | Outcome = Reject |

Default maximum iterations: **3**. Configurable.

**Condition 3 — new evidence test**

An iteration retrieves no new evidence where every evidence item returned is already present in the investigation's evidence set, compared by `(source, metric, period, value)`. Mechanical, requires no judgement.

**Question deduplication**

Every challenge question carries a fixed semantic key drawn from the Challenge Question Catalogue. A question whose key matches one already asked shall **not** be re-asked. Because keys are fixed and finite, deduplication is exact — there is no paraphrase risk.

**Forced outcome on iteration cap**

Where the loop terminates by condition 2 or 3, the outcome shall **not** be "Accepted".

| Terminating condition | Permitted outcomes |
|---|---|
| 1 — survives | Accepted, or Accepted with Caveats |
| **2 — iteration cap** | **Accepted with Caveats, or Inconclusive only** |
| **3 — no new evidence** | **Accepted with Caveats, or Inconclusive only** |
| 4 — questions exhausted | Accepted, or Accepted with Caveats |
| 5 — rejected | Reject |

Exhausting the iteration budget is not the same as withstanding challenge. A conclusion that ran out of budget has been **interrupted, not validated**.

**Interaction with Confidence Gate 7**

Gate 7 caps confidence at Low where the terminating condition is **2, 3 or 5**.

**Mandatory recording**

Every iteration shall persist: iteration number, questions asked with semantic keys, evidence retrieved, whether that evidence was new, weaknesses detected, and the outcome. An investigation whose challenge loop cannot be replayed from the audit record is not compliant.

**Priority**

Critical

---

# 53. Statistical Rules

---

# 54. Rule BR-401

**Rule Name**

Hypothesis-Driven Metric Selection

**Condition**

Statistical metrics shall be selected by the hypothesis under test.

**Constraint**

Metrics shall not be executed unnecessarily. Statistics-first execution is prohibited — hypothesis generation precedes statistical analysis in the canonical sequence.

**Priority**

Critical

---

# 55. Rule BR-402

**Rule Name**

Statistical Justification

**Condition**

Every executed metric shall record why it was selected.

**Priority**

High

---

# 56. Rule BR-403

**Rule Name**

Aggregation by Measure Type

**Condition**

Aggregation routine shall match the measure type.

| Measure type | Examples | Monthly / Quarterly |
|---|---|---|
| **Flow** | `Actual_Offered` · `fcst_offered` · `Final_Units` · `Final_Y1`–`Y5` · `Holiday_Count` | **SUM** |
| **Stock** | `Planned_ASU` · `Actual_ASU` | **MEAN** |
| **Ratio** | Forecast Adherence · warranty mix % · ASU variance % | **RECOMPUTE** from aggregated inputs |

Ratio measures shall never be averaged. Summing a stock double-counts — a queue with 100,000 units under warranty for 13 weeks has an installed base of 100,000, not 1,300,000.

**Priority**

Critical

---

# 57. Rule BR-404

**Rule Name**

Lag Treatment

**Condition**

Stock measures are tested contemporaneously. Flow measures **may** exhibit lag, determined **empirically per queue**:

```
FOR lag IN 0..13 weeks:
    compute correlation(driver shifted by lag, Actual_Offered)
SELECT the lag with the highest absolute correlation
IF that correlation clears the BR-121 relevance gate:
    use that lag
ELSE:
    the driver is NOT RELEVANT for this queue
```

**Measured basis**

Fixed lags were tested and **reduce** correlation:

| `Final_Units` vs `Actual_Offered` | Queues with \|r\| ≥ 0.3 |
|---|---|
| Lag 0 | **19%** |
| Lag 4 | 16% |
| Lag 8 | 17% |
| Lag 13 | 15% |

No fixed lag improves on contemporaneous. A queue-specific lag may exist; a universal one does not. Any prescriptive lag requirement is withdrawn.

The selected lag shall be recorded in the evidence and stated in the narrative.

**Priority**

High

---

# 58. Rule BR-405

**Rule Name**

Technical Detail Visibility

**Purpose**

Support progressive disclosure. Hide advanced statistical output by default.

**Technical metrics**

SHAP · WAPE · MAPE · RMSE · CoV · Correlation · Drift · Momentum · **Feature Importance**

These shall appear only when the user explicitly expands the Technical View. The default experience shall remain business-friendly.

**EXCEPTION — mandatory**

The **Confidence level, its dimension decomposition and any binding cap are NOT technical detail** and shall always be visible. Progressive disclosure does not apply to them.

A prominent confidence level with hidden limitations is misleading by construction.

**Note**

Supersedes the retired BR-604, which duplicated this rule.

**Priority**

Medium

---

# 59. Confidence Rules

Confidence shall reflect the strength of evidence supporting the selected Root Cause. Confidence shall never be manually assigned. It shall always be calculated per §5B.

---

# 60. Rule BR-501

**Rule Name**

Confidence Calculation

**Purpose**

Calculate confidence deterministically from eight weighted dimensions.

**Inputs**

The eight dimensions defined in §5B, each resolved to an availability state and scored 0.0 to 1.0.

**Action**

1. Resolve availability for all eight dimensions.
2. Score every Available dimension. Score Missing dimensions at 0.20.
3. Aggregate per §5B over applicable dimensions.
4. Evaluate all eight caps. Apply the lowest that binds.
5. Map the capped score to a level.
6. Persist the full decomposition.

**Constraints**

- Confidence shall never be manually assigned, overridden or adjusted outside this rule.
- Identical inputs shall produce an identical score. The calculation is deterministic.
- A score that cannot be decomposed to dimension level shall not be published.

**Priority**

Critical

---

# 61. Rule BR-502

**Rule Name**

Contradictory Evidence Penalty

**Mechanism**

Scored as the `ContradictoryEvidence` dimension, weight **0.20** — the highest of the eight.

```
ContradictoryEvidence = 1 − ( contradictory_weight
                            / (supporting_weight + contradictory_weight) )
```

**Cap**

Where the score falls below 0.40, **Gate 5** caps confidence at Low regardless of all other dimensions.

**Missing state**

Where no contradiction search was performed, the dimension is **Missing** and scores 0.20.

**Mandatory display**

Contradictory evidence shall always be displayed, whether or not it changed the conclusion.

**Priority**

Critical

---

# 62. Rule BR-503

**Rule Name**

Missing Context Penalty

**Mechanism**

Context enters via the `ContextCompleteness` dimension, weight 0.10:

```
ContextCompleteness = elements_available / elements_applicable
```

**CRITICAL DISTINCTION**

- **NotApplicable** elements are excluded from the denominator. **No penalty.**
- **Unavailable** elements count as 0 in the numerator. **Penalty applies.**

BR-112 Tier C warranty is **unavailable**, not NotApplicable — shipments exist and the data is invalid.

**Cap**

Where the missing element is the expected primary driver for the queue's Offering, **Gate 4** caps confidence at Medium.

**Mandatory explanation**

Every missing element shall be named, with its reason, on the Decision Card — not behind an expander.

**Priority**

High

---

# 63. Rule BR-504

**Rule Name**

Historical Consistency

**Mechanism**

Scored as the `HistoricalConsistency` dimension, weight 0.06. Governed by BR-118.

**Rationale for the neutral score**

Absence of precedent is not evidence against a conclusion. A first occurrence is not less true for being first. Scoring it low would systematically bias the engine toward familiar explanations.

**Note**

This rule is no longer a *bonus*. Under the weighted model there is no additive uplift; there are only dimension scores. Weight 0.06 reflects the Evidence Hierarchy, in which historical precedent supports but never determines.

**Priority**

Medium

---

# 64. Rule BR-505

**Rule Name**

Business Rule Precedence

**Purpose**

Ensure Business Rules override statistical and ML inference.

**Mechanism**

Scored as the `BusinessRuleValidation` dimension, weight 0.15.

| Condition | Score |
|---|---|
| All applicable rules satisfied and supportive | 1.00 |
| All satisfied, neutral to the conclusion | 0.60 |
| A rule was not evaluable | 0.40 |
| **A business rule contradicts the conclusion** | **0.00 + Gate 2** |

**Override mechanism**

Where a business rule contradicts the conclusion, **Gate 2 caps confidence at Low regardless of statistical or ML agreement.**

This is the operative meaning of precedence: no volume of statistical support can raise a conclusion above Low confidence if a deterministic business rule contradicts it.

**Mandatory disclosure**

The contradicting rule shall be named on the Decision Card, with the nature of the contradiction stated.

**Priority**

Critical

---

# 65. Rule BR-506

**Rule Name**

Inconclusive Investigation

**Condition**

No hypothesis achieves defensible support.

**Action**

`Case_Status = Inconclusive`. **No root cause is assigned at all.**

**Note**

This is not a cap. Confidence describes a conclusion; where there is no conclusion, there is nothing to describe.

**Priority**

Critical

---

# 66. Rule BR-507

**Rule Name**

Partial-Period Confidence

**Purpose**

Ensure conclusions from incomplete periods carry proportionate confidence.

**Mechanism — two parts, applied once each**

1. Coverage is an **input** to `DataSufficiency`:

```
coverage_score = Weeks_With_Actuals / Weeks_In_Period
```

contributing 40% of that dimension's score.

2. Coverage imposes a **cap**:

| Coverage_Ratio | Cap | Gate |
|---|---|---|
| < 0.50 | Medium | 3a |
| < 0.25 | Low | 3b |

**Coverage is never applied a third time.** No multiplier is applied to the aggregate score.

**Mandatory disclosure**

```
Timeline: FW18
Coverage: 2 of 5 fiscal weeks (40%)
Confidence capped at Medium — incomplete period (Gate 3a)
```

Whenever a cap binds, the gate, the threshold crossed and the actual figure shall all be stated.

**Suppressed analysis**

| Analysis | Requires |
|---|---|
| Within-period trend | ≥ 3 weeks with actuals |
| Within-period volatility | ≥ 4 weeks with actuals |
| Seasonality | Complete period plus prior-year equivalent |

Suppressed analyses are recorded as **suppressed**, distinguishable from analyses that ran and found nothing.

**Priority**

High

---

# 67. Rule BR-118

**Rule Name**

Precedent Provenance Weighting

**Purpose**

Prevent confidence inflation through repeated citation of weak precedents.

**Scope**

Governs the `HistoricalConsistency` dimension.

**Base score — precedent match**

| Condition | Base score |
|---|---|
| Eligible precedent found, same root cause | 1.00 |
| Eligible precedent found, related cause | 0.70 |
| Eligible precedent found, different cause | 0.40 |
| No eligible precedent found | **0.50 (neutral)** |
| Queue is Emerging | **NotApplicable** |

**Provenance weight — precedent's own confidence**

| Precedent Confidence_Level | Provenance weight |
|---|---|
| Very High | 1.00 |
| High | 0.80 |
| Medium | 0.60 |
| Low / Very Low | **Not eligible** (BR-203) |

**Scoring**

```
HistoricalConsistency = base_score × provenance_weight
```

Where several eligible precedents exist, the **highest** resulting score is used, and all precedents consulted are recorded.

**CEILING — mandatory**

```
HistoricalConsistency <= precedent_confidence_score
```

This ceiling makes confidence laundering **structurally impossible**. A Medium precedent (score 0.50–0.699) can never produce a `HistoricalConsistency` above its own score, so citation cannot amplify.

**Worked example**

| Precedent | Match | Precedent confidence | Base | Weight | Score | Ceiling | Final |
|---|---|---|---|---|---|---|---|
| A | Same cause | Very High (0.91) | 1.00 | 1.00 | 1.00 | 0.91 | **0.91** |
| B | Same cause | Medium (0.62) | 1.00 | 0.60 | 0.60 | 0.62 | **0.60** |
| C | Same cause | Low (0.41) | — | — | — | — | **Not eligible** |

**Mandatory recording**

Every precedent consulted shall be recorded with its identifier, match type, own confidence, provenance weight, resulting score, and whether it was eligible.

**Priority**

High

---

# 68. Explainability Rules

---

# 69. Rule BR-601

**Rule Name**

Business Language

**Condition**

All default outputs shall use business language. No statistical notation, no metric names, no technical terms.

**Priority**

High

---

# 70. Rule BR-602

**Rule Name**

Evidence Traceability

**Condition**

Every claim in an output shall be traceable to a recorded evidence item.

**Priority**

Critical

---

# 71. Rule BR-603

**Rule Name**

Assumption Disclosure

**Condition**

Every assumption made during investigation shall be stated in the output.

**Priority**

High

---

# 72. Rule BR-605

**Rule Name**

Business Language Translation

**Purpose**

Translate technical results into business language.

**Requirements**

1. Name the specific measure, not a generic category.
2. State direction and magnitude.
3. State the denominator where a share is quoted.
4. Explain the causal mechanism in business terms.

**Example**

> *"The share of shipments covered by 1-year warranty only rose from 31% to 38% of total shipments. Shorter coverage brings customers into contact sooner after purchase, and this was the largest single contributor to the increase in contact demand during the investigation period."*

**Priority**

High

---

# 73. Recommendation Rules

---

# 74. Rule BR-701

**Rule Name**

Evidence-Based Recommendations

**Purpose**

Generate actionable recommendations traceable to the identified root cause.

**Scope**

Recommendations propose **investigative or business actions**. They shall never propose a forecast value, and shall never be executed automatically.

**Routing**

All recommendations route to the **Demand / Forecast Team**. No per-recommendation owner is assigned.

**Requirements**

1. Every recommendation shall reference the Root Cause that generated it.
2. Every recommendation shall reference the evidence supporting that root cause.
3. **Maximum 3 recommendations per RCA.**
4. A recommendation with no traceable root cause shall not be generated.

Three is a deliberate ceiling. An RCA producing eight recommendations produces none that will be acted on.

**Priority**

High

---

# 75. Rule BR-702

**Rule Name**

Recommendation Prioritisation

**Purpose**

Rank recommendations so the most consequential is acted on first.

**Priority levels**

| Level | Assigned when |
|---|---|
| **Critical** | Root cause is recurring **AND** deviation exceeds the Major Deviation threshold |
| **High** | Root cause is recurring, **OR** deviation exceeds Major Deviation |
| **Medium** | Single-period deviation with High or Very High confidence |
| **Low** | Single-period deviation with Medium or lower confidence |

**Constraint**

Priority is **derived** from the above conditions, never assigned by the LLM.

**Priority**

Medium

---

# 76. Rule BR-704

**Rule Name**

Expected Business Impact

**Purpose**

State the consequence of acting, without inventing a quantification.

**Requirement**

Every recommendation shall carry a **qualitative** impact statement referencing the observed deviation:

> *"Would reduce recurrence of a −18.4% under-forecast on a queue averaging 743 contacts per week."*

**Prohibition**

Recommendations shall **not** state a quantified benefit — no contacts recovered, no cost avoided, no accuracy improvement percentage.

Quantifying a benefit requires assuming the action works and by how much. No data supports that assumption, and a fabricated figure would breach the prohibition on inventing business rules.

**Priority**

Medium

---

# 77. Audit Rules

Every rule execution shall be recorded in the Audit Trail with:

- Rule identifier and version
- Inputs evaluated
- Outcome
- Timestamp
- Configuration version in force

Audit information shall never be deleted.

Every RCA shall be reproducible from its audit record alone, including: input fingerprint, weights version, catalogue version, prompt version, model version and seed.

---

# 78. Configuration Rules

All configurable parameters shall be:

- Externalised from application code
- Version controlled
- Change-approved by the business
- Recorded on every RCA that used them

Fixed parameters — those marked "No" in the §5A table — shall not be exposed for configuration. The RCA Generation Threshold (±5%) and LLM temperature (0) are fixed.

---

# 79. Future Business Rules

FUTURE SCOPE. Not implemented in Phase 1.

- Automated business event ingestion and correlation
- Semantic similarity retrieval via embeddings
- Closed-loop learning from analyst feedback
- Forecast value recommendations
- Automated action execution and tracking
- Capacity, scheduling and real-time adherence context
- Product-level attribution (requires a product dimension absent from source data)

---

# 80. Business Rule Governance

| Requirement | Detail |
|---|---|
| Ownership | Business owned, not developer owned |
| Approval | Every rule change requires business approval |
| Versioning | Every rule maintains version history |
| Review | Periodic review of thresholds against measured effect |
| Segregation | Rule authoring and rule approval shall be separate roles |
| Evidence | Every threshold change shall be validated against real data before release |

---

# 81. Guiding Principles

- Business Rules take precedence over statistical inference.
- Deterministic logic precedes AI reasoning.
- Every rule is explainable, auditable and configurable.
- Prefer **Unknown** over **wrong with high confidence**.
- Confidence shall never increase because evidence was lost.
- No threshold shall be set from reasoning alone.

---

# End of Document
