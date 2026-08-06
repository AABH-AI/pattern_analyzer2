# FC_RCA_System_Architecture

**Project:** Forecast RCA Studio (FC_RCA)
**Document Type:** System Architecture Specification
**Version:** 2.0.0
**Supersedes:** Version 1.0.0
**Status:** Approved for Development
**Last Updated:** 30 July 2026

---

## Document Control

| Item | Detail |
|---|---|
| **Purpose** | Define system layers, modules, components, workflow, non-functional requirements and deployment posture. |
| **Scope** | Phase 1 architecture. |
| **Version basis** | Incorporates P1–P10. Workflow corrected to the canonical sequence. UI components specified. Asynchronous execution made mandatory. |
| **Dependencies** | `FC_RCA_RCA_Methodology.md` v2.0 owns the canonical sequence. `FC_RCA_Business_Rules.md` v2.0 owns all thresholds. |
| **Acceptance Criteria** | (1) Workflow matches the canonical sequence. (2) Every named component has a data contract. (3) No component performs calculation outside its layer. |
| **Owner** | Product Owner, FC_RCA |
| **Approver** | Pending |

---

# 1. Purpose

This document defines the system's structure: what exists, what each part does, and what it must not do.

---

# 2. Architectural Principles

| # | Principle |
|---|---|
| 1 | API-first |
| 2 | Modular — single responsibility per module |
| 3 | Business logic separated from infrastructure |
| 4 | Configuration over hardcoding |
| 5 | Infrastructure agnostic — no cloud provider or vendor assumed |
| 6 | Deterministic — identical inputs produce identical structured output |
| 7 | Auditable — every investigation reproducible from its record |
| 8 | Presentation contains no business logic |

---

# 3. Technology Stack

| Layer | Technology |
|---|---|
| Backend | **Python** |
| Frontend | **React** |
| LLM | Narrative generation only — pinned model, temperature 0 |
| Transport | REST, JSON |

---

# 4. Layered Architecture

```
┌─────────────────────────────────────────────────────┐
│  PRESENTATION LAYER                                  │
│  Worklist · Decision Card · Confidence Panel ·        │
│  Root Cause Tree · Evidence Timeline · Filter Bar     │
├─────────────────────────────────────────────────────┤
│  APPLICATION SERVICES LAYER                          │
│  RCA Controller · Job Queue · Export · Notification   │
├─────────────────────────────────────────────────────┤
│  AI REASONING LAYER                                  │
│  Workflow · Hypothesis · Evidence · Recursive         │
│  Reasoning · Cross-Examination · Root Cause ·          │
│  Confidence · Recommendation · Narrative (LLM)         │
├─────────────────────────────────────────────────────┤
│  STATISTICAL ANALYTICS LAYER            (a service)   │
│  Error Metrics · Trend · Seasonality · Variability ·   │
│  Correlation · Drift · Momentum · Outlier · ML         │
├─────────────────────────────────────────────────────┤
│  BUSINESS CONTEXT LAYER                              │
│  Fiscal Calendar · Holiday · Queue · Lineage ·         │
│  Shipment/Warranty · Installed Base · Events ·         │
│  Observations · Historical RCA · Business Rules         │
├─────────────────────────────────────────────────────┤
│  DATA ACCESS LAYER                                   │
├─────────────────────────────────────────────────────┤
│  REPOSITORY LAYER                                    │
├─────────────────────────────────────────────────────┤
│  AUDIT & GOVERNANCE LAYER      (spans all layers)     │
└─────────────────────────────────────────────────────┘
```

The **Statistical Analytics Layer is a service** invoked by the Evidence Engine. It does not execute before reasoning begins.

---

# 5. Ingestion Layer

**Purpose** — load forecast and actual data from the source system at queue × fiscal week grain.

## Responsibilities

| Responsibility |
|---|
| Retrieve source rows |
| **Disable automatic NA-string interpretation** (`BR-111`) |
| Normalise dimension aliases before unmapped-value detection |
| Apply validation rules `BR-101` to `BR-122` |
| Compute and store `Warranty_Validation_Tier` per row (`BR-112`) |
| Apply interior blank week treatment (`BR-122`) |
| Compute `Input_Fingerprint` for change detection |
| Record load audit — row counts, reconciliation, failures |

## Mandatory constraint

**`NA` is a valid business value meaning North America.** Read with default settings it becomes blank, affecting 16,250 rows (11.7%) of reference data with no error raised.

Post-load assertion: `COUNT(SubRegion IS NULL)` must equal **zero**.

---

# 6. Presentation Layer

## Purpose

User interface for different business personas. **Contains no business logic.**

## Interfaces

| Interface | Section |
|---|---|
| **RCA Worklist** | §6A |
| **Filter Bar** | §6B |
| Executive Dashboard | — |
| Forecast Analyst Workspace | §8 |
| Technical Diagnostics | — |
| Administration Portal | — |

---

# 6A. RCA Worklist

The application entry point. A hierarchical drill-down over the RCA generation window.

## Level Navigation

```
Level 1 — Region + SubRegion + Country + Offering     (113 groups)
    ↓ drill
Level 2 — + Channel                                   (286 groups)
    ↓ drill
Level 3 — + Forecast_name, weekly                     (427 queues, RCA here)
```

Filter state carries through every drill step.

## Dynamic collapse

Where the next level produces exactly one child group it is **skipped**, and navigation continues to the next level that subdivides (`BR-125`).

Measured on reference data: applies to **71% of Level 2 groups** and 21% of Level 1 groups. The collapsed level **still appears in the breadcrumb**.

```
Americas · NA · United States · Basic  >  Voice  >  Nordic Client DSP
                                         ↑ in the path even when skipped
```

## Grain Tabs

Three tabs at every level: **Weekly · Monthly · Quarterly**.

At Levels 1 and 2 tabs change the aggregation period. At Level 3 they select which RCA grain is listed.

## Level 1 and 2 — aggregate rows

| Field | Notes |
|---|---|
| Group | Region · SubRegion · Country · Offering [· Channel] |
| Pooled adherence | Signed |
| Direction | Under-forecast / Over-forecast / **Offsetting** |
| Net variance | Contacts |
| **GROSS VARIANCE** | Contacts — **the default sort** |
| **Offset ratio** | With SYSTEMIC / MIXED / IDIOSYNCRATIC label |
| Child queues | Count, and how many have an RCA in window |
| Root cause mix | Top 3 by variance contribution |
| Confidence mix | Distribution across children |

**Default sort: gross variance, descending.**

Where the offset ratio exceeds 70%, Direction displays **"Offsetting"** and the pooled adherence figure is de-emphasised — it is not meaningful for that group.

Single-queue groups display no offset label and are marked as such.

## Level 3 — queue rows

| Field | Notes |
|---|---|
| `Forecast_name` | |
| Period | Per grain |
| Adherence | Signed |
| Direction | Under-forecast / Over-forecast |
| **Absolute variance** | Contacts — **default sort** |
| Volume Band | Basis window on hover |
| Confidence | Level, with binding cap if any |
| Root cause | One line |
| Markers | Major Deviation · Manual · Superseded · Incomplete · Timeline |

## Display Rules — Level 3

A row appears where **both** hold:

1. `ABS(adherence) >` selected Adherence Display Filter
2. `ABS(Actual_Offered − fcst_offered) >=` Materiality Floor for the queue's Volume Band, **unless** the "Include immaterial breaches" toggle is on

Major Deviation rows bypass condition 1, **never condition 2**.

Superseded rows hidden by default, reachable via case history. Incomplete rows shown with a marker.

## Constraint

Filtering, sorting, drill-down and level collapse are **presentation only**.

---

# 6B. Filter Bar

A single unified filter bar serves all levels and all grain tabs.

## Filters

| Filter | Type | Source |
|---|---|---|
| Region | Multi-select + search | DISTINCT, dynamic |
| SubRegion | Multi-select + search | DISTINCT, dynamic, **cascaded** |
| Country | Multi-select + search | DISTINCT, dynamic, **cascaded** |
| Offering | Multi-select + search | DISTINCT, dynamic |
| Channel | Multi-select + search | DISTINCT, dynamic |
| Business | Multi-select + search | DISTINCT, dynamic |
| Forecast_name | Multi-select + search | DISTINCT, dynamic |
| **Forecaster** | Multi-select + search | DISTINCT, **ROLE-RESTRICTED** |
| Volume Band | Multi-select + search | Derived (`BR-113`) |
| Fiscal Year | Multi-select + search | Derived |
| Fiscal Month | Multi-select + search | Derived (4-4-5) |
| Fiscal Week | Multi-select + search | DISTINCT, dynamic |
| **Adherence Threshold** | **SINGLE-SELECT** | Fixed list |
| Include immaterial breaches | Toggle | Default **OFF** |

## Dynamic population — mandatory

Every value list is populated by `SELECT DISTINCT` at query time. **No list is hardcoded.** A new Region, Country, Offering, Channel or `business_org` appears automatically.

`business_org` holds one value (`CSG`) in reference data. Additional values (e.g. `ISG`) will appear without code change. **The filter is not hidden.**

## Cascading

```
Region → SubRegion → Country
```

Necessary at 3 Regions, 16 SubRegions and 49 Country values. Offering, Channel, Business, Volume Band and Forecaster do **not** cascade — they are independent dimensions.

## Threshold — single-select

A symmetric band cannot hold two values; ±20% is a subset of ±10%. Options ±5 / 10 / 15 / 20 / 25 / 30%. Default ±10%.

## Role restriction

`Forecaster` identifies named individuals. Available only to roles explicitly granted it. For all other roles **the filter is not rendered**.

## Persistence

Filter state persists **per user across sessions**, with a "Reset filters" control. Grain tab switching preserves state for filters applicable to both grains.

## Constraint

**Presentation only.** No filter creates, triggers, regenerates or alters an RCA (`BR-005`).

---

# 6C. Component Inventory and Persona Access

## Components

| # | Component | Level |
|---|---|---|
| 1 | Filter Bar | All |
| 2 | Worklist — L1 aggregate | 1 |
| 3 | Worklist — L2 aggregate | 2 |
| 4 | Worklist — L3 queue | 3 |
| 5 | Decision Card | 3 |
| 6 | Confidence Panel | 3 |
| 7 | Root Cause Tree | 3 |
| 8 | Evidence Timeline | 3 |
| 9 | Hypothesis Comparison | 3 |
| 10 | Cross-Grain View | 3 |
| 11 | Annotation Provenance Control | 3 |
| 12 | Annotation Entry | 3 |
| 13 | Callouts (6 types) | All |
| 14 | Case History | 3 |
| 15 | Technical View | 3 |
| 16 | Administration Portal | Admin |
| 17 | Governance Exception Review | Admin |

## Persona Access

| Component | Executive | Analyst | Data Scientist | Admin |
|---|---|---|---|---|
| L1 / L2 aggregate | Yes | Yes | Yes | Yes |
| L3 queue worklist | Yes | Yes | Yes | Yes |
| Decision Card | Yes | Yes | Yes | Yes |
| **Confidence Panel** | **Yes** | **Yes** | **Yes** | **Yes** |
| Root Cause Tree | No | Yes | Yes | Yes |
| Evidence Timeline | No | Yes | Yes | Yes |
| Hypothesis Comparison | No | Yes | Yes | Yes |
| Cross-Grain View | No | Yes | Yes | Yes |
| Annotation entry | No | Yes | Yes | Yes |
| Technical View | No | Yes | Yes | Yes |
| Forecaster filter | No | ROLE | No | Yes |
| Re-run request | No | Yes | No | Yes |
| Governance Exception Review | No | No | No | Yes |
| Administration Portal | No | No | No | Yes |

**The Confidence Panel is available to every persona. It is never collapsed and never restricted.**

---

# 7. Application Services Layer

| Service | Responsibility |
|---|---|
| RCA Controller | Orchestrates an investigation |
| Job Queue | Asynchronous execution with priority |
| Export Service | PDF · Word · Markdown · JSON · CSV |
| Notification Service | In-application notifications |
| Configuration Service | Versioned configuration retrieval |

**Contains no reasoning logic.**

---

# 8. Forecast Analyst Workspace

## Provides

- Investigation Details, including grain and period coverage
- Root Cause Analysis
- Evidence Summary
- **Hypothesis Evaluation** — including Suppressed and Not Applicable, with reasons
- Business Context
- Recommendations
- **Cross-Grain View**
- Case History — superseded recomputations
- Annotation entry and provenance controls

Analysts may expand Technical View.

## Cross-Grain View

Where a queue holds investigations at more than one grain for overlapping time:

```
Queue: Nordic Client DSP
Weekly    FW18  −18.4%  Under-forecast  184 contacts  High
Monthly   M05    −4.2%  Under-forecast   62 contacts  Medium  Timeline: FW18
Quarterly Q2     −2.1%  Under-forecast   95 contacts  Medium  Timeline: FW18
```

**Context, not reconciliation.** Divergence between grains is expected and diagnostically meaningful — offsetting weekly errors produce a materially smaller monthly deviation, which is itself a finding.

The component shall **not** reconcile the figures, present one grain's conclusion as another's, or imply that disagreement is an error.

---

# 9. AI Reasoning Layer

| # | Engine | LLM |
|---|---|---|
| 1 | Workflow Engine | No |
| 2 | Hypothesis Engine — deterministic catalogue | **No** |
| 3 | Evidence Engine | No |
| 4 | Recursive Reasoning Engine | No |
| 5 | Cross-Examination Engine — deterministic catalogue | **No** |
| 6 | Root Cause Engine | No |
| 7 | Confidence Engine | **No** |
| 8 | Recommendation Engine | No |
| 9 | **Executive Narrative Engine** | **Yes — the only invocation point** |

---

# 10. Workflow Engine

Executes the canonical sequence defined in `FC_RCA_RCA_Methodology.md §6`.

```
Validate Data
      ↓
Calculate Adherence
      ↓
Detect Deviation
      ↓
Load Context
      ↓
Generate Hypotheses
      ↓
Collect Supporting Evidence
      ↓
Collect Contradictory Evidence
      ↓
Execute Statistics
      ↓
Recursive Root Cause Reasoning
      ↓
Cross-Examination                (bounded loop — BR-117)
      ↓
Confidence Assessment
      ↓
Root Cause Decision
      ↓
Generate Recommendations
      ↓
Generate Decision Card
      ↓
Generate Executive Summary
      ↓
Audit
```

## Configurability

**Step content is configurable** — which metrics run, which hypotheses are generated, thresholds, depth limits.

**Step order is NOT configurable.** In particular:

- Hypotheses shall not be generated after statistics execute
- Confidence shall not be assigned before cross-examination completes

> Version 1.0.0 of this section omitted Recursive Root Cause Reasoning and both Evidence Collection steps, and stated *"The workflow remains configurable"* — which contradicted the invariants.

---

# 11. Hypothesis Engine

Generates candidate hypotheses **deterministically** from the versioned Candidate Hypothesis Catalogue. No LLM.

Records every catalogue entry **not** generated with its failing condition, distinguishing never-applicable from tested-and-rejected from suppressed.

Applies the driver cascade — business order preserved, relevance gate deciding usability.

**Shall not generate a hypothesis outside the catalogue.** Unmatched patterns are recorded as UNEXPLAINED OBSERVATIONS.

---

# 12. Evidence Engine

## Evidence categories

| Category |
|---|
| Business |
| Statistical |
| Historical |
| ML |
| Annotation |

**`Contradictory` is not a category.** It is the `Supporting_Flag` dimension. Version 1.0.0 listed six categories including "Contradictory" and "Operational", conflating a dimension with a category and including a construct with no source.

## Responsibilities

- Collect supporting evidence
- **Collect contradictory evidence as a separate mandatory step**
- Invoke the Statistical Analytics Layer as a service
- Weight by source independence, not volume
- Record strength on the five-level scale

---

# 13. Statistical Analytics Layer

A **service** invoked by the Evidence Engine. Modules: Error Metrics · Trend · Seasonality · Variability · Relationship · Drift · Momentum · Outlier · ML Explainability.

## Correlation variables

| Variable | Nature | Lag | Applicability |
|---|---|---|---|
| Active Serviceable Units — Planned and Actual | **STOCK** | Contemporaneous | Not for out-of-warranty; relevance-gated |
| ASU variance / ASU Adherence | STOCK | Contemporaneous | Same |
| ASU growth rate | Derived | Contemporaneous | Same |
| Shipments / `Final_Units` | Flow | **Empirical** | Not for out-of-warranty; relevance-gated |
| Warranty **exclusive bands** | Flow | **Empirical** | Tier A/B; relevance-gated |
| `Holiday_Count` and day-of-week | — | Contemporaneous | Not for aggregate countries |
| Business Events | — | Impact window | Optional |

**Removed** — "Average Selling Units" (an incorrect definition of ASU) and "Product Age" (no source).

## Constraints

- Lag treatment by measure type; flow lag determined empirically
- Applicability flags respected — Not Applicable excluded without penalty, Missing excluded with penalty
- Every calculation linked to an `investigationId`

---

# 14. Recursive Reasoning Engine

Moves from correlation to mechanism. Depth-bounded. Records question, answer, evidence, confidence, decision and termination reason per level.

Circular reasoning prevented by semantic-key comparison.

---

# 15. Cross-Examination Engine

Draws questions from the versioned Challenge Question Catalogue. No LLM.

Loop bounded per `BR-117` — maximum 3 iterations, early exit on no new evidence, forced outcome on exhaustion. Because catalogue keys are fixed and finite, deduplication is **exact**.

---

# 16. Confidence Engine

## Purpose

Calculate confidence deterministically from eight weighted dimensions, and record the full decomposition.

## Inputs

| Dimension | Source |
|---|---|
| `DataSufficiency` | Queue history depth, period coverage, field completeness |
| `StatisticalAgreement` | Statistical Analytics Layer — metric concurrence |
| `HistoricalConsistency` | Historical RCA Repository — provenance-weighted |
| `ContextCompleteness` | Business Context Layer — element availability |
| `EvidenceStrength` | Evidence Engine — strength and source independence |
| `ContradictoryEvidence` | Evidence Engine — contradictory weight |
| `ModelAgreement` | ML Explainability — method concurrence |
| `BusinessRuleValidation` | Business Rules Engine — rule outcomes |

> Version 1.0.0 listed six, naming two of them "Data Quality" and "Historical Similarity", and omitted `ModelAgreement` and `BusinessRuleValidation` — both of which `MBS §15` required.

## Processing

1. Resolve availability per dimension
2. Score Available dimensions; apply the Missing floor
3. Renormalise weights across applicable dimensions
4. Aggregate
5. Evaluate all eight caps; apply the lowest binding
6. Map to level
7. Persist decomposition

## Outputs

`Raw_Score` · `Capped_Score` · `Confidence_Level` · `Binding_Cap` · per-dimension availability, score, weight and contribution · cap evaluation record · `Weights_Version`

## Constraints

- **Deterministic.** Identical inputs produce identical output
- **Contains no LLM call.** Confidence is computed, never narrated into existence. The LLM may explain a score; it shall never produce one
- A score that cannot be decomposed **shall not be published**
- **Shall never raise confidence in response to unavailable data.** This invariant is asserted in test

---

# 17. Root Cause Engine

Selects the surviving hypothesis with strongest evidence and highest confidence, subject to cross-examination outcome, business rule consistency and contradictory evidence weight.

Records secondary drivers on the Root Cause entity. Where no hypothesis achieves defensible support, sets `Inconclusive` and assigns **no root cause**.

---

# 18. Recommendation Engine

Generates a maximum of **three** recommendations, each traceable to the root cause and its evidence.

Priority **derived** per `BR-702`. Impact **qualitative** per `BR-704`. All route to the Demand / Forecast Team.

**Scope** — investigative and business actions only. Never forecast values. Never executed automatically.

---

# 19. Executive Narrative Engine

**The only component in the architecture that invokes an LLM.**

## Position

Invoked after confidence assignment and root cause selection. **All inputs are fixed before invocation.**

## Constraints

- Governed by the Prompt Contract (`AI_Agent_Architecture §15A`)
- Model and prompt version **pinned**. Temperature **0**
- Strict output schema, validated before use
- Failure marks the RCA `Incomplete`; structured output remains available
- **Contains no calculation capability**
- Cannot alter any input

## What this component does NOT do

Version 1.0.0 implied broader AI involvement. It does **not**:

- generate hypotheses — deterministic catalogue (§11)
- generate cross-examination questions — deterministic catalogue (§15)
- calculate confidence — Confidence Engine (§16)
- select a root cause — Root Cause Engine (§17)
- generate recommendations — Recommendation Engine (§18)

---

# 20. Business Context Layer

Repositories: Fiscal Calendar · Holiday Calendar · Holiday Name Synonym · Queue · Queue Lineage · Shipment and Warranty · Installed Base · Business Event *(optional)* · Business Observation · Historical RCA · Business Rules.

**Removed from Phase 1** — Operational Metadata (AHT, ASA, occupancy, shrinkage, staffing: Capacity constructs with no source data) and Product Repository (no product identifier).

Every element resolves to **Available**, **Missing** or **Not Applicable**.

---

# 21. Data Access and Repository Layers

Data Access provides retrieval with no business logic. Repository Layer persists entities per the Data Dictionary.

---

# 22. Audit and Governance Layer

Spans all layers. Records every rule execution, statistical calculation, reasoning step, cross-examination iteration, confidence calculation and LLM invocation.

**Audit information shall never be deleted.**

Every RCA reproducible from its audit record alone, using: `Input_Fingerprint` · `Business_Rules_Version` · `Weights_Version` · `Hypothesis_Catalogue_Version` · `Question_Catalogue_Version` · `Prompt_Version` · `Model_Version` · `Seed`.

---

# 23. Event-Driven Architecture

The application shall support event-driven, asynchronous processing.

## 23.1 Batch Generation Flow

Applies where `ABS(adherence) > 10%`.

```
Actuals Loaded for Fiscal Week
      ↓
Adherence Calculated (Weekly, Monthly, Quarterly)
      ↓
Generation Threshold Evaluated       (ABS(adherence) > 5%)
      ↓
Generation Window Checked            (trailing 13 weeks)
      ↓
RCA Job Enqueued
      ↓
Workflow Started
      ↓
Context Retrieved
      ↓
Hypotheses Generated
      ↓
Evidence Collected
      ↓
Statistics Executed
      ↓
Recursive Root Cause Reasoning
      ↓
Cross-Examination
      ↓
Confidence Assessment
      ↓
Root Cause Selected
      ↓
Recommendations Generated
      ↓
Decision Card Generated
      ↓
Audit Updated
      ↓
Notification Sent
```

## 23.2 On-Demand Generation Flow

Applies where `5% < ABS(adherence) ≤ 10%`, and to manual requests under `BR-002`.

```
User Opens Period
      ↓
Cache Checked
      ↓
  ── Cache Hit ──> Decision Card Served
      ↓
  ── Cache Miss ──> RCA Job Enqueued (High Priority)
      ↓
Same workflow as 23.1
      ↓
Decision Card Cached and Served
```

## 23.3 Asynchronous Requirements — mandatory, not optional

| # | Requirement |
|---|---|
| 1 | RCA generation shall execute asynchronously. Job submission returns **HTTP 202 Accepted** with a job identifier |
| 2 | Clients shall poll job status or receive a callback. **RCA generation shall never block an HTTP request for its full duration** |
| 3 | Jobs shall be queued with priority. On-demand generation outranks batch |
| 4 | Generated RCAs are **immutable and cached**. Reopening never regenerates |
| 5 | Failed jobs retried with backoff and, on final failure, recorded in the Audit Trail with a stated reason rather than silently dropped |

> Version 1.0.0 stated *"should support asynchronous processing where appropriate"*, listed HTTP 202 among status codes but used it on no endpoint, and returned a synchronous status from `/rca/start`.

## 23.4 Excluded from the Flow

The **Adherence Display Filter** and the **Materiality Floor** are presentation controls. They do not appear in this flow and shall never emit an event that generates, regenerates or invalidates an RCA.

---

# 24. End-to-End Processing Flow

```
Actuals Loaded
      ↓
Validate Data
      ↓
Calculate Adherence
      ↓
Detect Deviation             (ABS(adherence) > 5% — BR-001)
      ↓
Retrieve Business Context
      ↓
Generate Candidate Hypotheses
      ↓
Collect Supporting Evidence
      ↓
Collect Contradictory Evidence
      ↓
Execute Statistical Analysis
      ↓
Recursive Root Cause Reasoning
      ↓
Cross-Examine Hypotheses     (bounded loop)
      ↓
Calculate Confidence
      ↓
Select Root Cause
      ↓
Generate Recommendations
      ↓
Generate Executive Decision Card
      ↓
Generate Technical Report
      ↓
Store Audit
      ↓
Close Investigation
```

## Changes from Version 1.0.0

| Change |
|---|
| *"Forecast Miss → RCA Trigger"* replaced by explicit calculation and detection steps. The threshold does not create an investigation |
| **Recursive Root Cause Reasoning inserted** — previously absent |
| Evidence collection split into supporting and contradictory |
| Generation window check added |

---

# 25. Non-Functional Requirements

| Requirement | Target |
|---|---|
| Complete RCA | Under 60 seconds |
| Asynchronous execution | **Mandatory** |
| Adherence calculation | Under 2 seconds |
| Context retrieval | Under 5 seconds |
| Statistical analysis | Under 20 seconds |
| Narrative generation | Under 30 seconds, 1 retry |
| Generated RCA | Immutable, cached |

## Timeout behaviour — a correctness requirement

| Status | Cause | Published |
|---|---|---|
| **`Incomplete`** | Time budget exhausted, or narrative failed. Some stages ran | **Yes** — banner listing incomplete stages, **confidence capped at Low** (Gate 7), Executive Summary states *"provisional — investigation incomplete"* |
| **`Failed`** | Unrecoverable error | **No** — reason recorded in audit |

**A partial RCA may be published. It must never be mistakable for a complete one.**

**Performance shall never be optimised at the cost of explainability.**

## Volumetrics

| Measure | Value |
|---|---|
| Queues | ~427 |
| Generation window | Trailing 13 fiscal weeks |
| Evaluable queue-weeks in window | ~5,434 |
| RCA scope at ±5% | ~83% of evaluable |
| Weekly narrative calls | ~1,000 across three grains |
| Analysis levels | 113 / 286 / 427 |

Monthly and quarterly RCAs recomputed weekly as actuals arrive.

## Deferred

Availability target · RPO · RTO · capacity model · cost envelope · data retention policy. None blocks RCA generation.

---

# 26. Security Posture — Phase 1

| Item | Phase 1 position |
|---|---|
| Access model | RBAC by persona |
| **`Forecaster` dimension** | **Role-restricted** — identifies named individuals |
| Business rule changes | Segregation of duties: authoring and approval are separate roles |
| Audit | Never deleted |
| Data classification and PII framework | **Deferred.** Internal tool in Phase 1 |

The `Forecaster` restriction is applied as a precaution rather than as part of a full PII framework, which is deferred.

---

# 27. Deployment Posture

| Requirement |
|---|
| Infrastructure agnostic — no cloud provider assumed |
| Containerisable |
| Configuration externalised and versioned |
| Backend Python, frontend React |
| LLM accessed via configurable endpoint with pinned model version |

Environment design, promotion path and secrets management are **deferred** and set at deployment.

---

# 28. Architectural Design Principles

- Layers have single responsibilities
- Presentation contains no business logic
- The Statistical Layer is a service, not a stage
- Module layering is not execution order
- Step order is structural; step content is configurable
- Asynchronous execution is mandatory, not optional
- The LLM has exactly one invocation point
- Confidence is computed, never narrated
- Audit spans everything and is never deleted

---

# End of Document
