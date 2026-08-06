# FC_RCA_Project_Roadmap

**Project:** Forecast RCA Studio (FC_RCA)
**Document Type:** Product Roadmap
**Version:** 2.0.0
**Supersedes:** Version 1.0.0
**Status:** Approved for Development
**Last Updated:** 30 July 2026

---

## Document Control

| Item | Detail |
|---|---|
| **Purpose** | Define phasing, deliverables and scope boundaries for Forecast RCA Studio. |
| **Scope** | Phases 1 to 4. Phase 1 is authoritative; later phases are directional. |
| **Version basis** | Incorporates P1–P10. Phase boundaries for the Event Repository, recommendations and analyst feedback are clarified where Version 1.0.0 was ambiguous. |
| **Dependencies** | `FC_RCA_Business_Rules.md` v2.0 · `FC_RCA_Definitions_and_Formulas.md` v2.0 |
| **Acceptance Criteria** | Every Phase 1 deliverable traces to a ratified specification. No Phase 1 capability depends on a future-phase capability. |
| **Owner** | Product Owner, FC_RCA |
| **Approver** | Pending |

---

# 1. Purpose

This document defines what is built when, and — equally important — what is deliberately not built yet.

Future scope shall never influence Phase 1 implementation.

---

# 2. Product Vision

An engine that explains forecast misses defensibly, at scale, without human interpretation of raw data.

Long term, an intelligence layer over the Demand pillar. Near term, one question answered well.

---

# 3. Roadmap Principles

| # | Principle |
|---|---|
| 1 | **Specification before implementation.** No module is built before its specification is ratified |
| 2 | **Evidence before commitment.** Every threshold validated against real data before release |
| 3 | **No forward dependencies.** A Phase 1 capability never requires a Phase 2 capability to function |
| 4 | **Explicit deferral.** Deferred features are named, with the reason |
| 5 | **Scope integrity.** Additions require approval and a phase assignment |

## Principle 3 — how it is honoured

Where a Phase 1 capability would otherwise depend on something deferred, the dependency is made **optional with no penalty** rather than left dangling. The Event Repository is the worked example: available in Phase 1 with manual population, and where empty it is treated as **Not Applicable** — carrying no confidence penalty — rather than as missing data.

---

# 4. Phase Overview

| Phase | Focus | Status |
|---|---|---|
| **1** | Forecast RCA Engine | **Current** |
| 2 | RCA Intelligence Expansion | Planned |
| 3 | AI Forecast Intelligence Platform | Directional |
| 4 | Enterprise AI Ecosystem | Directional |

---

# Phase 1 — Forecast RCA Engine (Current)

## Objective

Produce defensible root cause analysis for Forecast Adherence deviations, at three grains, with calculated confidence and complete auditability.

## Deliverables

### Metrics and Calendar

- Forecast Adherence — signed, `(1 − Actual_Offered / fcst_offered) × 100`
- Forecast Accuracy — reference metric
- Pooled aggregation for monthly and quarterly
- Fiscal Calendar — 4-4-5, 53-week years as Q4 4-5-5, data-derived week count

### Trigger and Scope

- RCA generation at **±5%**, fixed
- Rolling **13-week generation window** ending at the latest week with actuals
- Pre-generation above ±10%, lazy generation for the ±5–10% band
- Three independent grains: Weekly · Monthly · Quarterly
- Monthly and quarterly recomputed as actuals arrive, prior versions superseded not overwritten

### Data Model

- Queue Master, derived from source, keyed on `Forecast_name`
- Queue Volume Band — effective-dated, recalculated FW01/14/27/40
- Queue Lineage — rename, merge, split
- Shipment Plan with nested warranty tiers
- Warranty Mix as a derived view with exclusive bands
- Active Serviceable Units — installed base, stock measure
- Period Coverage, RCA Rerun Request, LLM Invocation

### Validation

- Three-tier warranty structure validation
- Reserved literal preservation (`NA` = North America)
- Interior blank week treatment — zero-fill to 3 weeks, inactive beyond
- Non-computable adherence handling
- Fiscal year week count derivation

### Reasoning

- Fixed **hypothesis catalogue** — six categories, deterministic generation
- Fixed **challenge question catalogue** — five categories, semantic-key deduplication
- Recursive root cause reasoning, depth-bounded
- Cross-examination with **bounded loop** — maximum 3 iterations, forced outcome on exhaustion
- Driver Relevance Gate — per-queue correlation, business cascade order preserved
- Empirical lag determination per queue

### Confidence

- Eight weighted dimensions
- Three availability states — Available, Missing, Not Applicable
- Eight caps, lowest binding
- Full decomposition persisted and always visible

### Business Context

- Holiday Calendar with per-holiday impact windows
- **Holiday-anchored comparison** for moving holidays
- Business Event Repository — **manual population, optional, no penalty when empty**
- Business Observations — analyst annotations as retrievable evidence
- Historical RCA retrieval, gated on confidence and provenance-weighted

### Output

- Executive Decision Card, versioned
- Confidence Panel — always visible, never collapsed
- Root Cause Tree · Evidence Timeline · Hypothesis Comparison · Cross-Grain View
- Six callout types
- Recommendations — investigative and business actions, maximum 3, qualitative impact

### Interface

- Three-level analysis hierarchy with **dynamic level collapse**
- Unified filter bar — 13 filters, multi-select with search, dynamically populated, cascading geography
- Adherence Display Filter — single-select, display only
- Materiality floors by volume band, with an override toggle

### AI

- LLM confined to **narrative generation only**
- Pinned model, pinned prompt version, temperature 0, strict output schema
- Full prompt and response persisted per invocation
- Guardrails enforced by architecture, not instruction

### Governance

- Complete audit trail, never deleted
- Re-run governance with input fingerprinting and governance exceptions
- Full reproducibility from the audit record

## Success Criteria

| # | Criterion |
|---|---|
| 1 | Identical inputs produce identical structured output |
| 2 | Every confidence score decomposable to eight dimensions |
| 3 | Every RCA reproducible from its audit record alone |
| 4 | No conclusion published beyond what evidence supports |
| 5 | Every threshold carries a measured effect in the specification |

---

# Phase 2 — RCA Intelligence Expansion

## Objective

Reduce manual effort in populating context, and broaden how the engine finds precedent.

## Planned Enhancements

### Business Event Repository — automation

The repository itself is **Phase 1**. Phase 2 adds:

- Automated ingestion from source systems — product launches, promotions, marketing campaigns, outages
- Event correlation with demand deviation
- Event impact scoring
- Event similarity detection

### Semantic Similarity Retrieval

- Embedding model and vector store
- Semantic matching of historical RCAs, beyond the Phase 1 structural match
- Similarity threshold and re-embedding strategy

Phase 1 matches structurally on queue, sub-region, offering and event. That is deterministic and explainable. Semantic matching catches cases structural matching misses, at the cost of explainability, and therefore needs its own governance.

### Closed-Loop Learning

- Analyst annotations, captured in Phase 1, become inputs to model and prompt improvement
- Requires an approved AI governance process before any autonomous adjustment

### Queue Behaviour Classification

Deferred from Phase 1 as redundant — metric selection is hypothesis-driven, which does the same job with one mechanism instead of two. Revisit only if hypothesis-driven selection proves insufficient in practice.

### Weekly Email Summary

- Scheduler, subscription model, template, recipient permissions

### Extended Context

- Marketing activity
- Predictive risk detection

## Success Criteria

Context population requires materially less manual effort. Precedent retrieval finds relevant cases that structural matching misses.

---

# Phase 3 — AI Forecast Intelligence Platform

## Objective

Move from explaining misses to informing the forecast itself.

## Planned Capabilities

- **Forecast value recommendations** — recommending what the forecast should be. Explicitly excluded from Phase 1
- Forecast DNA — characterising each queue's forecastability
- Multi-agent architecture
- Automated action tracking — following a recommendation through to outcome
- Capacity and scheduling context, alongside the Capacity pillar
- Product-level attribution, contingent on a product dimension being added to source data

## Dependency Note

Product-level attribution, forecast version comparison and operational metadata all require **data that does not currently exist**. They are not deferred by choice but by data availability. Each is documented as a Known Gap with the specific fields required.

## Success Criteria

The platform influences forecast production, not only its explanation.

---

# Phase 4 — Enterprise AI Ecosystem

## Objective

Extend the reasoning pattern beyond the Demand pillar.

## Potential Enhancements

- Cross-pillar RCA — Capacity, Scheduling, Real-Time Adherence
- Enterprise knowledge graph
- Autonomous monitoring and alerting
- Conversational analysis interface

Directional only. No commitment.

---

# 5. Features Explicitly Deferred

| Feature | Phase | Reason |
|---|---|---|
| Automated business event ingestion | 2 | Repository available Phase 1 with manual population |
| Event correlation, impact scoring, similarity | 2 | Requires automated ingestion first |
| Semantic similarity retrieval | 2 | Requires embedding strategy and governance |
| Closed-loop learning | 2 | Requires AI governance approval |
| Queue Behaviour Classification | 2 | Redundant — hypothesis-driven metric selection covers it |
| Weekly Email Summary | 2 | Distribution feature, not an RCA capability |
| Marketing activity context | 2 | No source data |
| **Forecast value recommendations** | 3 | Out of Phase 1 scope by design |
| **Automated action execution and tracking** | 3 | The engine suggests; humans act |
| Forecast DNA | 3 | — |
| Multi-agent architecture | 3 | — |
| Capacity, Scheduling, RTA context | 3 | Different pillars |
| **Product-level attribution** | 3+ | **No product identifier in source data** |
| **Forecast version comparison** | 3+ | **No version dimension in source data** |
| **Operational metadata** — AHT, ASA, occupancy, shrinkage, staffing | 3+ | Capacity constructs, no source data |
| Cross-pillar RCA | 4 | — |
| Prompt A/B testing in production | 4 | Two active prompt versions break reproducibility |

## Deferred Non-Functional Work

| Item | Note |
|---|---|
| NFR targets — availability, RPO, RTO, capacity model, cost envelope | One exception is **in** Phase 1: RCA timeout behaviour, because a partial RCA that looks complete is a correctness risk |
| Security and PII framework | Internal tool in Phase 1. `Forecaster` filter is role-restricted as a precaution |
| Governance instruments — ADR register, RACI, change control | The P1–P10 change packages serve as the decision record in the interim |
| Deployment architecture | Set at deployment |
| LLM daily token budget | Set at deployment. Estimated ~550,000 tokens/day at Phase 1 volumes |

None of these blocks RCA generation.

---

# 6. Roadmap Governance

| Requirement | Detail |
|---|---|
| Phase assignment | Every new capability receives an explicit phase |
| Scope additions | Require approval and a documented rationale |
| Deferral | Requires a stated reason and, where applicable, the data dependency |
| Review | Phase boundaries reviewed at each phase close |
| Evidence | Capability decisions supported by measurement where data permits |

---

# 7. Scope Management

## What triggers a scope review

- A requirement that cannot be satisfied with available data
- A capability that would create a forward dependency
- A threshold that measurement shows to be unworkable
- A rule that measurement shows cannot discriminate

## Precedent

Three Phase 1 rules were **withdrawn on measurement** during specification:

| Withdrawn | Measurement |
|---|---|
| `BR-003` Repeated Forecast Miss | 100% of queues reach three consecutive breaching weeks |
| Week-over-week installed base comparison | ±10% fires on 0.3% of weeks |
| Fixed lag requirement for flow measures | No fixed lag improves on contemporaneous |

Withdrawing a rule on evidence is scope management working correctly, not scope loss.

---

# 8. Long-Term Vision

A reasoning layer that any Workforce Management pillar can adopt: hypothesis-driven, evidence-bounded, confidence-calculated, fully auditable — and honest enough to say *Unknown* when the evidence does not support a conclusion.

---

# End of Document
