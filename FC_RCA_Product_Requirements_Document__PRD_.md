# FC_RCA_Product_Requirements_Document (PRD)

**Project:** Forecast RCA Studio (FC_RCA)
**Document Type:** Product Requirements Document
**Version:** 2.0.0
**Supersedes:** Version 1.0.0
**Status:** Approved for Development
**Last Updated:** 30 July 2026

---

## Document Control

| Item | Detail |
|---|---|
| **Purpose** | Define what Forecast RCA Studio must do. |
| **Scope** | Functional and non-functional requirements for Phase 1. |
| **Version basis** | Incorporates P1–P10. Confidence levels corrected from three to five. Requirement set expanded to cover generation window, analysis hierarchy, materiality and re-run governance. |
| **Assumptions** | Grain is queue × fiscal week. `Forecast_name` is the queue identifier. |
| **Dependencies** | `FC_RCA_Definitions_and_Formulas.md` v2.0 · `FC_RCA_Business_Rules.md` v2.0 |
| **Acceptance Criteria** | Every functional requirement traces to a ratified rule or specification. |
| **Owner** | Product Owner, FC_RCA |
| **Approver** | Pending |

---

# 1. Purpose

This document defines the product requirements for Forecast RCA Studio.

---

# 2. Problem Statement

Explaining a forecast miss currently requires manual analysis across multiple data sources, and the explanation depends on the analyst's judgement, availability and recall. Explanations are inconsistent, slow to produce and difficult to defend.

---

# 3. Product Goal

Produce defensible root cause analysis for Forecast Adherence deviations, automatically, consistently and with stated confidence.

---

# 4. Target Users

| Persona | Need |
|---|---|
| Executive / Ops Manager | What happened, why, how confident, what to do |
| Forecast Analyst | Full investigation with evidence and the ability to annotate |
| Data Scientist | Statistical diagnostics and feature attribution |
| Administrator | Configuration, rules, audit and governance |

---

# 5. Product Scope

## Included in Phase 1

Forecast Adherence analysis · Root Cause Analysis · driver attribution · confidence scoring · executive summaries · technical analysis · Decision Cards · audit trail · Context Repository · three analysis grains · three-level analysis hierarchy · recommendations for investigative and business actions · analyst annotations.

## Shall NOT be developed in Phase 1

| Excluded | Note |
|---|---|
| Capacity Planning, Scheduling, Real-Time Adherence | Different pillars |
| Forecast generation, ML forecasting | — |
| **Forecast value recommendations** | Recommending what the forecast should be |
| **Automated action execution and tracking** | — |
| **Automated business event ingestion** | The Event Repository **is** in Phase 1, manually populated |
| Closed-loop learning | Annotations captured, not consumed |
| Product-level attribution | No product identifier in source data |
| Forecast version comparison | No version dimension in source data |
| Operational metadata | Capacity constructs, no source data |
| Weekly email summary | Deferred to Phase 2 |

> Recommending investigative or business **actions** in response to a root cause **is** in scope.

---

# 6. Functional Requirements

## FR-001 — Data Ingestion

The system shall ingest forecast and actual data at queue × fiscal week grain from the source system.

Ingestion shall implement the validation rules `BR-101` to `BR-122`, including reserved literal preservation (`BR-111`) and interior blank week treatment (`BR-122`).

## FR-002 — Data Validation

The system shall validate every ingested row before analysis. Failures shall flag, exclude and continue with reduced confidence, or reject where the rule requires it. No failure shall be silent.

## FR-003 — Adherence Calculation

The system shall automatically calculate Forecast Adherence using the canonical formula:

```
Forecast Adherence % = (1 − (Actual_Offered / fcst_offered)) × 100
```

Adherence shall be calculated at **Weekly, Monthly and Quarterly** grain per queue. Monthly and quarterly values use the **Pooled** aggregation method over fiscal weeks with actuals available.

Adherence shall be calculated only for fiscal periods where `Actual_Offered` is available. Future periods are excluded.

The **signed** value shall be stored and displayed. The absolute value shall be used only for threshold comparison.

## FR-004 — RCA Generation

The system shall generate an RCA for every queue and fiscal period where `ABS(Forecast Adherence) > 5%`.

The ±5% RCA Generation Threshold is **fixed at system level**. It is not configurable and not exposed in the user interface.

## FR-004a — Adherence Display Filter

The system shall provide an Adherence Display Filter controlling which breaching periods appear in the worklist.

| Item | Value |
|---|---|
| Options | ±5% · ±10% · ±15% · ±20% · ±25% · ±30% |
| Default | ±10% |
| Selection | **Single-select** |

The Display Filter shall **never** create, trigger, regenerate or alter an RCA.

## FR-004b — Materiality Floor

The system shall apply a Materiality Floor to worklist display, suppressing breaches whose absolute contact variance falls below the floor for that queue's Volume Band.

| Volume Band | Floor |
|---|---|
| ≤100 | 10 contacts |
| 101–250 | 25 |
| 251–500 | 50 |
| 501–1000 | 100 |
| 1001–5000 | 200 |
| >5000 | 500 |

An **"Include immaterial breaches"** toggle shall bypass the floor. Default off.

The Materiality Floor shall never prevent RCA generation or alter RCA content.

## FR-004c — RCA Worklist

The system shall provide a prioritised RCA worklist presenting all periods satisfying FR-004a and FR-004b, allowing a user to select an investigation.

## FR-004d — Volume Band

The system shall derive a Volume Band for every queue, recalculated in the first fiscal week of each fiscal quarter (**FW01, FW14, FW27, FW40**) from the mean weekly `Actual_Offered` of the preceding fiscal quarter.

The band shall be **effective-dated**. Historical RCAs shall retain the band in force at the time of generation.

Queues without prior-quarter actuals shall be classified **Emerging**. RCA shall still be produced, with confidence reduced and history-dependent hypotheses suppressed.

The source `Volume_Category` field shall not be used.

## FR-004e — RCA Grain

The system shall produce RCA independently at three grains for every queue: Weekly, Monthly and Quarterly.

Each grain shall be presented in a **separate tab** and is an independent investigation with its own hypotheses, evidence, confidence and root cause.

The ±5% generation threshold shall be evaluated **independently at each grain**.

## FR-004f — Period Horizon and Timeline

The system shall restrict RCA to fiscal periods containing at least one fiscal week with `Actual_Offered` available. Future periods shall be excluded entirely.

Every partial period shall display a Timeline callout:

```
Timeline: FW18
```

Confidence for partial periods shall be capped by coverage, with the gate, threshold and actual figure stated.

Monthly and Quarterly RCAs shall be recomputed as additional weeks of actuals become available. Prior conclusions shall be retained as **superseded**, never overwritten.

## FR-004g — Generation Window

The system shall generate RCA only for fiscal periods within the **trailing 13 fiscal weeks ending at the latest fiscal week with actuals**.

This bounds **generation**, not evidence. Evidence retrieval — year-over-year comparison, holiday-anchored comparison, driver relevance correlation, historical precedent — reaches across full retained history.

RCAs falling outside the window shall be **retained** as historical records.

## FR-004h — Analysis Hierarchy

The system shall provide a three-level analysis hierarchy:

| Level | Grouping |
|---|---|
| 1 | Region + SubRegion + Country + Offering |
| 2 | + Channel |
| 3 | + Forecast_name, at week level — **RCA generated here** |

Levels 1 and 2 are **aggregation views**. They shall not generate independent RCAs.

Aggregate views shall display **net variance, gross variance and offset ratio** together. A pooled adherence figure shall never be displayed without its offset ratio.

Aggregate views shall rank by **gross variance**, not adherence percentage.

Where a level produces exactly one child group it shall be **skipped**, with the level retained in the breadcrumb.

## FR-005 — Business Context Retrieval

The system shall retrieve applicable business context before analysis. Each element shall resolve to **Available**, **Missing** or **Not Applicable**, and these three states shall never be conflated.

## FR-006 — Hypothesis Generation

The system shall generate candidate hypotheses **deterministically** from a versioned Candidate Hypothesis Catalogue. The system shall not generate a hypothesis outside the catalogue.

Every catalogue entry not generated shall be recorded with its failing condition.

## FR-007 — Recursive Root Cause Reasoning

The system shall perform recursive root cause reasoning, moving from correlation to mechanism, bounded by a configurable maximum depth, recording every level.

## FR-008 — Cross-Examination

The system shall cross-examine every accepted conclusion using questions drawn from a versioned Challenge Question Catalogue.

The loop shall be **bounded** — maximum 3 iterations, early exit where an iteration retrieves no new evidence.

Where the loop terminates by iteration cap or no-new-evidence, the outcome shall **not** be a clean "Accepted", and confidence shall be capped.

## FR-009 — Confidence Assessment

The system shall calculate confidence from **eight** weighted dimensions. Confidence shall never be manually assigned.

Every confidence score shall be **decomposable to dimension level** and shall state which dimensions were Missing or Not Applicable, and why.

Confidence shall never increase as a result of unavailable data.

## FR-010 — Decision Card

The system shall produce an Executive Decision Card containing:

- Executive Summary
- Root Cause
- **Confidence with full decomposition and any binding cap**
- Adherence, signed, with direction and absolute variance
- Recommendations, maximum three
- Business Impact
- Limitations and data availability callouts
- Timeline callout where the period is partial
- Audit reference

Decision Cards shall be **versioned**, never overwritten.

## FR-011 — Hypothesis Transparency

The system shall record and display every hypothesis considered in one of four **visually distinct** states:

| State | Meaning |
|---|---|
| Accepted | Tested, supported, selected |
| Rejected | Tested, evidence did not support it |
| **Suppressed** | **Could not be tested** |
| **Not Applicable** | Never relevant to this queue |

A reason is mandatory for the latter three. No hypothesis considered shall disappear from the output.

## FR-012 — Output Formats

The system shall deliver output through:

- Web portal
- Aggregate and queue-level worklists
- API response
- Export — PDF, Word, Markdown, JSON, CSV

Weekly email summary is **deferred to Phase 2**.

## FR-013 — Recommendations

The system shall generate recommendations proposing **investigative or business actions** in response to the identified root cause.

| Requirement | Value |
|---|---|
| Maximum per RCA | **3** |
| Priority | Critical / High / Medium / Low, **derived** |
| Impact statement | **Qualitative only** |
| Routing | Demand / Forecast Team |

Recommendations shall not propose forecast values, shall not state a quantified benefit, and shall not be executed automatically.

## FR-014 — Analyst Annotation

The system shall allow analysts to record an annotation against any RCA — agreement, disagreement or additional context.

Analysts shall **not** be able to modify an RCA.

Annotations shall be retained, retrievable by future investigations as evidence, and displayed as normal narrative content with a **provenance control** revealing source, author, reason for retrieval and impact.

## FR-015 — Re-run Governance

The system shall serve the existing historical RCA for any out-of-window request where one exists.

A re-run shall require explicit request. Where no data change is detected, the requester shall supply a **mandatory reason**, the re-run shall be recorded as a **Governance Exception**, flagged to the Administrator, and marked on the Decision Card.

## FR-016 — Audit Trail

The system shall record every rule execution, statistical calculation, reasoning step, cross-examination iteration and LLM invocation.

Every RCA shall be reproducible from its audit record alone. Audit information shall never be deleted.

## FR-017 — Filter Bar

The system shall provide a unified filter bar with **dynamically populated, multi-select, searchable** filters:

Region · SubRegion · Country · Offering · Channel · Business · Forecast_name · Forecaster · Volume Band · Fiscal Year · Fiscal Month · Fiscal Week

Geography shall **cascade** — Region narrows SubRegion narrows Country.

The Adherence Threshold shall be **single-select**.

`Forecaster` identifies named individuals and shall be **role-restricted**.

New dimension values shall appear automatically and be flagged to the Administrator.

## FR-018 — Determinism

Identical inputs shall produce identical **structured** output — hypothesis set, evidence, statistics, confidence, root cause and recommendations.

Narrative wording may vary within provider tolerance; a difference in fact shall not.

---

# 7. Non-Functional Requirements

| Requirement | Target |
|---|---|
| Complete RCA | Under 60 seconds |
| Asynchronous execution | Mandatory. Job submission returns HTTP 202 |
| **RCA timeout behaviour** | **`Incomplete` — published with banner, confidence capped, provisional wording. Never mistakable for complete** |
| **Unrecoverable error** | **`Failed` — not published. Reason in audit** |
| Reproducibility | Every RCA reproducible from audit record |
| Modularity | Business logic separated from infrastructure |
| Portability | No cloud provider or vendor assumed |
| Backend | Python |
| Frontend | React |

## Deferred

Availability target · RPO · RTO · capacity model · cost envelope · data retention policy · security and PII framework. None blocks RCA generation.

---

# 8. Forecast Adherence

The primary KPI:

```
Forecast Adherence % = (1 − (Actual_Offered / fcst_offered)) × 100
```

Signed. 0% = perfect. Negative = under-forecast. Positive = over-forecast.

Governed by `FC_RCA_Definitions_and_Formulas.md`. Thresholds and validation by `FC_RCA_Business_Rules.md`.

---

# 9. Fiscal Calendar

| Item | Rule |
|---|---|
| Format | `YYYYWW`, where `YYYY` is the **fiscal** year |
| Fiscal year start | First week of February |
| Week boundaries | Begins Saturday, ends Friday |
| Month pattern | **4-4-5** |
| 53-week year | Q4 becomes **4-5-5** |
| Week count derivation | `MAX(Fiscal_Week_Number)` per fiscal year |

---

# 10. Confidence Requirements

Every RCA shall include one of the following confidence levels:

- **Very High**
- **High**
- **Medium**
- **Low**
- **Very Low**

Confidence shall be **CALCULATED** — never assigned, estimated or inferred — from eight weighted dimensions:

Contradictory Evidence · Evidence Strength · Business Rule Validation · Statistical Agreement · Data Sufficiency · Context Completeness · Historical Consistency · Model Agreement

Each dimension resolves to **Available**, **Not Applicable** or **Missing**. Not Applicable dimensions are excluded and remaining weights renormalised. Missing dimensions are retained at a floor and count against confidence.

**Confidence shall never increase as a result of unavailable data.**

Confidence shall be capped where defined conditions are met, including insufficient dimension coverage, business rule contradiction, low period coverage, unavailability of the expected primary driver, and failed cross-examination.

Every confidence score shall be decomposable to dimension level and shall display which dimensions were excluded or missing, and why.

Full model in `FC_RCA_Business_Rules.md §5B`.

---

# 11. User Experience Requirements

Three information layers:

| Layer | Content |
|---|---|
| **Executive View** | Business-friendly summary, Decision Card, Confidence Panel |
| **Analyst View** | Full investigation, evidence, Root Cause Tree, Evidence Timeline, Hypothesis Comparison, annotation |
| **Technical View** | Statistical detail, SHAP, feature attribution |

Progressive disclosure applies — **except** to the Confidence Panel, which is always visible to every persona and never collapsed.

---

# 12. Context Repository Requirements

Phase 1 shall support contextual enrichment using available metadata including:

- Fiscal Calendar, including fiscal month and quarter derivation
- Holiday Calendar, with per-holiday impact windows and holiday-anchored comparison
- Shipment Plan and Warranty Coverage — Tier A/B, relevance-gated
- Installed Base — Active Serviceable Units, relevance-gated
- Business Events — **optional**, manual population, no penalty when absent
- Queue Metadata, Volume Band and Queue Lineage
- Business Observations — analyst annotations
- Geography — Region, SubRegion, Country
- Business Rules
- Historical RCA — eligibility-gated, provenance-weighted

---

# 13. Assumptions

| # | Assumption |
|---|---|
| 1 | `Forecast_name` is the unique queue identifier |
| 2 | Source grain is one row per queue per fiscal week |
| 3 | `Actual_Offered` and `fcst_offered` are the sole adherence inputs |
| 4 | Actuals lag the current week by approximately four weeks |
| 5 | No product identifier exists in source data |
| 6 | No forecast version dimension exists in source data |
| 7 | `channel` is a stable queue attribute |

---

# 14. Dependencies

- Source system providing forecast and actual data at the stated grain
- Global holiday master, corrected for the day/month transposition identified in 161 rows
- Queue Lineage maintained manually when queue names change
- LLM provider supporting pinned model version, temperature 0 and seed

---

# 15. Acceptance Criteria

| # | Criterion |
|---|---|
| 1 | Adherence reproduces the reference test cases exactly, including sign |
| 2 | Pooled aggregation reproduces its reference case |
| 3 | Fiscal month mapping reproduces both 52-week and 53-week reference tables |
| 4 | Warranty exclusive bands reconcile to `Final_Units` on all Tier A rows |
| 5 | Confidence is decomposable to eight dimensions on every RCA |
| 6 | Identical inputs produce identical structured output |
| 7 | Every RCA is reproducible from its audit record |
| 8 | Suppressed, Rejected and Not Applicable hypotheses are visually distinct |
| 9 | No RCA is generated outside the generation window |
| 10 | No aggregate figure is displayed without its offset ratio |

---

# 16. Out of Scope

See §5. Future capability is defined in `FC_RCA_Project_Roadmap.md`.

Future scope shall never influence Phase 1 implementation.

---

# End of Document
