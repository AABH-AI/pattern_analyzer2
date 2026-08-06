# Forecast RCA Studio

**Project:** Forecast RCA Studio (FC_RCA)
**Document Type:** Project Overview
**Version:** 2.0.0
**Supersedes:** Version 1.0.0
**Status:** Approved for Development
**Last Updated:** 30 July 2026

---

# 1. Project Overview

Forecast RCA Studio is an enterprise AI platform that explains **why** Forecast Adherence deviations occur.

It is not a chatbot, not a dashboard, not a report generator, not a forecasting engine. It answers one question, defensibly:

> *Why did Forecast Adherence miss?*

Every answer carries its evidence, its confidence, its limitations and a complete audit trail.

---

# 2. Vision

An engine that reasons like a disciplined analyst rather than pattern-matching like a model.

| Principle | Meaning |
|---|---|
| Evidence before conclusion | No root cause without traceable evidence |
| Contradiction actively sought | The engine tries to disprove its own findings |
| Confidence calculated, never assigned | An eight-dimension weighted model |
| **Unknown preferred over wrong** | Inconclusive is a valid, correct outcome |
| Deterministic | Identical inputs produce identical output |

---

# 3. Project Scope

## Included — Phase 1

- Forecast Adherence analysis at Weekly, Monthly and Quarterly grain
- Root Cause Analysis with recursive reasoning and cross-examination
- Driver attribution, gated on demonstrated per-queue relevance
- Confidence scoring across eight weighted dimensions
- Executive summaries and Decision Cards
- Technical analysis and statistical explainability
- Business context: fiscal calendar, holidays, shipments, warranty coverage, installed base, volume banding
- Recommendations — **investigative and business actions**, maximum three per RCA
- Analyst annotations captured as retrievable evidence
- Three-level analysis hierarchy: Region · SubRegion · Country · Offering → Channel → Queue
- Complete audit trail with full reproducibility

## Explicitly Excluded — Phase 1

| Excluded | Note |
|---|---|
| Capacity Planning, Scheduling, Real-Time Adherence | Different pillars |
| Forecast generation and ML forecasting | This engine explains forecasts; it does not produce them |
| **Forecast value recommendations** | Recommending *what the forecast should be* |
| **Automated action execution and tracking** | The engine suggests; humans act |
| **Automated business event ingestion and correlation** | The Event Repository itself **is** available in Phase 1 with manual population |
| Closed-loop learning | Annotations are captured but never autonomously consumed |
| Product-level attribution | No product identifier exists in source data |
| Forecast version comparison | No version dimension exists in source data |

---

# 4. Business Objective

Reduce the time and judgement required to explain a forecast miss, and raise the defensibility of the explanation.

| Outcome | Mechanism |
|---|---|
| Faster diagnosis | RCA generated automatically within a rolling 13-week window |
| Consistent reasoning | Deterministic rules and a fixed hypothesis catalogue |
| Defensible conclusions | Evidence hierarchy, cross-examination, calculated confidence |
| Prioritised attention | Materiality floors and gross-variance ranking |
| Institutional memory | Historical RCAs and analyst annotations retained as evidence |

---

# 5. Forecast Adherence

The primary KPI analysed by this solution is Forecast Adherence.

```
Forecast Adherence % = (1 − (Actual_Offered / fcst_offered)) × 100
```

**Signed metric.** 0% = perfect. Negative = **under-forecast** (actual above forecast). Positive = **over-forecast** (actual below forecast).

The sign is diagnostically essential and is never discarded. `ABS()` is used only for threshold comparison.

RCA is generated for every queue and fiscal period where `ABS(Forecast Adherence) > 5%`, at all three grains, within the generation window.

| Reference | Document |
|---|---|
| Formula, field and calendar definitions | `FC_RCA_Definitions_and_Formulas.md` |
| Trigger, threshold and validation rules | `FC_RCA_Business_Rules.md` |
| Statistical treatment | `FC_RCA_Statistical_Framework.md` |

---

# 6. Guiding Principles

- Business Rules take precedence over statistical inference
- Deterministic logic precedes AI reasoning
- Every conclusion is explainable, auditable and reproducible
- Confidence shall never increase because evidence was lost
- No threshold shall be set from reasoning alone — every value is validated against real data
- Prefer **Unknown** over **wrong with high confidence**

---

# 7. Core Design Philosophy

## Evidence Hierarchy

When evidence conflicts, precedence runs:

1. Verified business data
2. Business Rules
3. Deterministic statistical analysis
4. Historical patterns
5. Time-series analysis
6. ML attribution
7. LLM narrative

The LLM sits at the bottom, and this is enforced **structurally** — it cannot generate hypotheses, questions, evidence or confidence. It writes prose from findings already fixed.

## Reasoning Before Calculation

Hypotheses select which statistics run. Statistics never run first looking for patterns.

## Progressive Disclosure

Simple by default, detailed on demand — **with one exception.** The Confidence level and its full decomposition are **always visible**, never collapsed. A prominent confidence figure with hidden limitations is misleading by construction.

---

# 8. Confidence Philosophy

Confidence is **calculated** from eight weighted dimensions, never assigned.

| Dimension | Weight |
|---|---|
| Contradictory Evidence | **0.20** |
| Evidence Strength | 0.18 |
| Business Rule Validation | 0.15 |
| Statistical Agreement | 0.14 |
| Data Sufficiency | 0.12 |
| Context Completeness | 0.10 |
| Historical Consistency | 0.06 |
| Model Agreement | 0.05 |

Contradictory Evidence carries the highest weight deliberately. The engine's first duty is to avoid being confidently wrong.

**Five levels:** Very High · High · Medium · Low · Very Low.

**Eight caps** limit confidence where specific weaknesses exist — insufficient dimension coverage, business rule contradiction, low period coverage, primary driver unavailable, contradiction outweighing support, single-source evidence, failed cross-examination, Emerging queue. Caps never raise confidence; the lowest binds.

**Three availability states, never conflated:**

| State | Meaning | Effect |
|---|---|---|
| Available | Data present | Scored |
| **Missing** | Relevant but absent | Retained at a floor. **Penalty** |
| **Not Applicable** | Irrelevant to this queue | Excluded. **No penalty** |

---

# 9. Explainability Philosophy

Every statistic, recommendation, confidence score and root cause is explainable in business language.

Four states are always visually distinct: **Accepted · Rejected · Suppressed · Not Applicable.** A hypothesis that *could not be tested* must never look like one that was *tested and ruled out* — those support opposite actions.

Suppressed analyses are recorded with reasons, never silently omitted.

---

# 10. Statistical Philosophy

- Metrics are selected by hypothesis, never executed exhaustively
- Every metric records why it was selected
- Stock and flow measures are aggregated differently and never by the same routine
- Lag is determined **empirically per queue**, not prescribed
- Drivers apply only where they show demonstrated correlation with that queue's demand

Measured driver relevance: installed base 55% of queues · shipments 18% · warranty coverage 18%. A driver that does not track demand for a queue is marked Not Applicable for that queue, without penalty.

---

# 11. Context Repository

Phase 1 business context:

- Fiscal Calendar — 4-4-5, with 53-week years absorbed into Q4 as 4-5-5
- Holiday Calendar — with per-holiday impact windows and holiday-anchored historical comparison
- Shipment Plan and Warranty Coverage — nested tiers, exclusive bands derived by differencing
- Active Serviceable Units — installed base, a stock measure
- Queue metadata, Volume Band and Queue Lineage
- Business Event Repository — **optional**, manual population, no confidence penalty when empty
- Business Observations — analyst annotations
- Historical RCA — gated on confidence and provenance-weighted

Future releases may extend the repository with promotions, product launches, marketing campaigns, automated event correlation and semantic similarity retrieval.

---

# 12. Internal Reasoning Model

```
Validate → Calculate Adherence → Detect Deviation → Build Context
    → Generate Hypotheses (fixed catalogue)
    → Collect Supporting Evidence → Collect Contradictory Evidence
    → Execute Statistics → Recursive Root Cause Reasoning
    → Cross-Examine (bounded loop, max 3 iterations)
    → Assign Confidence → Select Root Cause
    → Recommend → Narrate → Audit
```

Two orderings are structural and not configurable: hypotheses precede statistics, and cross-examination precedes confidence.

---

# 13. Target Users

| Persona | Primary use |
|---|---|
| **Executive / Ops Manager** | Aggregate views, Decision Card, Confidence Panel |
| **Forecast Analyst** | Full investigation, evidence, Root Cause Tree, annotations |
| **Data Scientist** | Statistical diagnostics, SHAP, feature attribution |
| **Administrator** | Configuration, business rules, audit, governance exceptions |

The Confidence Panel is available to **every** persona and is never collapsed.

---

# 14. Technology Stack

| Layer | Technology |
|---|---|
| Backend | **Python** |
| Frontend | **React** |
| Architecture | API-first, modular, infrastructure agnostic |
| LLM | Narrative generation only — pinned model, pinned prompt, temperature 0 |

No cloud provider or vendor is assumed.

---

# 15. Documentation Structure

| Document | Purpose |
|---|---|
| `README.md` | This overview |
| `FC_RCA_Definitions_and_Formulas.md` | **Authoritative** definitions, formulas, field semantics, calendar |
| `FC_RCA_Product_Requirements_Document__PRD_.md` | Functional requirements |
| `FC_RCA_Master_Build_Specification__MBS_.md` | Build specification and precedence authority |
| `FC_RCA_Business_Rules.md` | All deterministic rules and ratified thresholds |
| `FC_RCA_Data_Dictionary_and_Schema.md` | Logical data model |
| `FC_RCA_RCA_Methodology.md` | **Canonical investigation sequence**, hypothesis catalogue |
| `FC_RCA_Statistical_Framework.md` | Metrics, selection, aggregation, governance |
| `FC_RCA_Explainability_Framework.md` | Layers, personas, business translation |
| `FC_RCA_AI_Agent_Architecture.md` | AI pipeline, prompt contract, guardrails |
| `FC_RCA_Context_Repository_Design.md` | Business knowledge layer |
| `FC_RCA_System_Architecture.md` | Layers, modules, components, NFRs |
| `FC_RCA_API_Specification.md` | REST contract |
| `FC_RCA_Output_and_Decision_Cards.md` | Output specification |
| `FC_RCA_Testing_and_Validation_Strategy.md` | Test strategy and quality gates |
| `FC_RCA_Project_Roadmap.md` | Phasing and scope control |

**Sixteen documents.** Content for KPI definitions, data model, vector strategy, prompt specification, prompt versioning and AI safety is folded into the documents above rather than held separately. Deployment architecture is deferred.

---

# 16. Success Criteria

| # | Criterion |
|---|---|
| 1 | Every RCA traceable to evidence |
| 2 | Every confidence score decomposable to dimension level |
| 3 | Identical inputs produce identical structured output |
| 4 | Every investigation reproducible from its audit record |
| 5 | No conclusion published that the evidence does not support |
| 6 | Analysts reach a defensible explanation faster than by manual analysis |

Criterion 5 includes producing **Inconclusive** where warranted. A meaningful share of investigations will correctly reach no defensible root cause, and that is the system working as designed.

---

# 17. Future Roadmap

- Automated business event ingestion and correlation
- Semantic similarity retrieval via embeddings
- Closed-loop learning from analyst feedback
- Forecast value recommendations
- Multi-agent architecture
- Predictive risk detection
- Product-level attribution, once a product dimension exists

Future scope never influences Phase 1 implementation.

---

# End of Document
