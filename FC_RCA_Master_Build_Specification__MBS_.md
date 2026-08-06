# FC_RCA_Master_Build_Specification (MBS)

**Project:** Forecast RCA Studio (FC_RCA)
**Document Type:** Master Build Specification
**Version:** 2.0.0
**Supersedes:** Version 1.0.0
**Status:** Approved for Development
**Last Updated:** 30 July 2026

---

## Document Control

| Item | Detail |
|---|---|
| **Purpose** | Define how Forecast RCA Studio is built: module layering, workflow, precedence, AI governance and build standards. |
| **Scope** | Phase 1 build specification. |
| **Authority** | This document is the **precedence authority** for build decisions. On **execution order**, `FC_RCA_RCA_Methodology.md §6` prevails and §10 of this document expresses the same sequence at coarser granularity. |
| **Version basis** | Incorporates P1–P10. |
| **Acceptance Criteria** | (1) No workflow step skipped. (2) Module layering does not imply execution order. (3) Every AI principle has a stated enforcement mechanism. |
| **Owner** | Product Owner, FC_RCA |
| **Approver** | Pending |

---

# 1. Purpose

This document specifies how the system is built. It is the precedence authority for build decisions.

Where it previously conflicted with itself on execution order — §6 versus §10 — that conflict is resolved in §6 below.

---

# 2. What This System Is

An engine that explains **why** Forecast Adherence deviated.

## What it is not

- Not a chatbot
- Not a dashboard
- Not a report generator
- Not a forecasting engine
- Not a recommendation engine for forecast values

---

# 3. Non-Negotiable Requirements

| # | Requirement |
|---|---|
| 1 | Every conclusion traceable to recorded evidence |
| 2 | Confidence calculated, never assigned |
| 3 | Identical inputs produce identical structured output |
| 4 | Every investigation reproducible from its audit record alone |
| 5 | Contradictory evidence actively sought and always displayed |
| 6 | **Unknown** preferred over **wrong with high confidence** |
| 7 | No threshold set from reasoning alone |

---

# 4. Architecture Baseline

The specification set is the approved baseline. Architecture shall not be redesigned unless an inconsistency, scalability, maintainability, security or explainability issue exists, or the business explicitly requests it.

Every architectural change identifies: the issue, why the change is needed, business impact, technical impact, every affected document — and requires approval before the baseline is modified.

---

# 5. Product Scope

## Included in Phase 1

Forecast Adherence analysis · Root Cause Analysis · driver attribution with relevance gating · confidence scoring · executive summaries · Decision Cards · audit trail · Context Repository · three analysis grains · three-level analysis hierarchy · recommendations for investigative and business actions · analyst annotations as evidence.

## Shall NOT be implemented in Phase 1

| Excluded | Note |
|---|---|
| Capacity Planning, Scheduling, Real-Time Adherence | Different pillars |
| Forecast generation, ML forecasting | This engine explains; it does not forecast |
| **Forecast value recommendations** | Recommending what the forecast should be |
| **Automatic forecast corrections** | — |
| **Automated action execution and tracking** | The engine suggests; humans act |
| **Automated business event ingestion and correlation** | The Event Repository **is** in Phase 1, with manual population |
| Closed-loop learning | Annotations captured, never autonomously consumed |
| Product-level attribution | No product identifier in source data |
| Forecast version comparison | No version dimension in source data |
| Operational metadata — AHT, ASA, occupancy, shrinkage, staffing | Capacity constructs, no source data |

> **Clarification.** Recommending investigative or business **actions** in response to an identified root cause **is** in Phase 1 scope. Recommending forecast **values**, and executing or tracking actions, are not.

---

# 6. Development Architecture Principles

Every module shall have a single responsibility.

## Module Layering

> The diagram below describes **module layering and dependency. It is NOT an execution sequence.** The canonical execution sequence is defined in §10 and, in full detail, in `FC_RCA_RCA_Methodology.md §6`.

```
Layer 1 — Foundation
    Data Layer
    Validation Layer
    Context Repository
    Audit Trail                (spans all layers)

Layer 2 — Analytical Services
    Statistical Engine         (invoked BY the Evidence Engine)
    ML Explainability Module   (invoked BY the Evidence Engine)

Layer 3 — Reasoning
    Hypothesis Engine
    Evidence Engine            (consumes Layer 2 services)
    Recursive Reasoning Engine
    Cross-Examination Engine
    Root Cause Engine
    Confidence Engine
    Recommendation Engine

Layer 4 — Presentation
    Executive Narrative Engine (the only LLM invocation point)
    Decision Card Generator
    Output Layer
```

No module shall perform responsibilities belonging to another module.

## Note on a Prior Reading

Version 1.0.0 presented the module list as a vertical arrow chain, which read as an execution order. It was not one, and two readings conflicted with §10 of this document:

- **The Statistical Engine appears in Layer 2 because it is a SERVICE** consumed by the Evidence Engine. It does not execute before hypothesis generation. Hypotheses select which metrics run (`BR-401`). Executing statistics first would be correlation fishing.
- **The Confidence Engine appears alongside the Cross-Examination Engine** because both sit in the Reasoning layer. Confidence is assigned **after** cross-examination, per §10 step 9, because cross-examination may return Reinvestigate or Reject and change the conclusion.

Where any document conflicts with §10 on execution order, §10 prevails.

---

# 7. Modular Design Requirements

| Requirement |
|---|
| Business logic separated from infrastructure |
| Configuration over hardcoding |
| Reusable components |
| Every module independently testable |
| No module depends on a future-phase module |

---

# 8. Infrastructure Neutrality

No cloud provider, database technology or vendor is assumed. Backend Python, frontend React.

---

# 9. Evidence Hierarchy

When evidence conflicts, precedence runs:

1. **Verified business data**
2. **Business Rules**
3. Deterministic statistical analysis
4. Historical patterns
5. Time-series analysis
6. ML attribution
7. **LLM narrative**

The LLM sits at the bottom and this is enforced structurally: it cannot generate hypotheses, questions, evidence or confidence.

Where a business rule contradicts the conclusion, confidence is capped at Low regardless of statistical support (`BR-505`, Gate 2). **This is the operative meaning of precedence.**

---

# 10. RCA Workflow — CANONICAL

> This is the canonical execution sequence at coarse granularity. The full 15-step sequence, which decomposes several of these steps, is defined in `FC_RCA_RCA_Methodology.md §6`. The two are consistent; where any other document conflicts, RCA Methodology §6 prevails.
>
> **§6 of this document describes module layering, not execution order.**

```
Step  1   Validate data
Step  2   Calculate Forecast Adherence
Step  3   Identify deviations
Step  4   Build business context
Step  5   Generate hypotheses
Step  6   Evaluate evidence
Step  7   Perform recursive root cause reasoning
Step  8   Cross-examine the selected conclusion     ← bounded loop
Step  9   Assign confidence
Step 10   Generate Decision Card
Step 11   Generate Executive Summary
Step 12   Persist audit trail
```

## Invariants

Two orderings are structural and shall not be varied by configuration:

1. **Hypothesis generation (Step 5) precedes statistical evaluation (Step 6).** Hypotheses determine which metrics execute.
2. **Cross-examination (Step 8) precedes confidence assignment (Step 9).** Cross-examination may change or discard the conclusion, and confidence caps depend on its outcome.

**No workflow step may be skipped.**

---

# 11. Context Repository

Before any statistical analysis begins, the engine shall build contextual understanding using available metadata.

Phase 1 context: fiscal calendar · holiday calendar with impact windows · shipment plan and warranty coverage · installed base (ASU) · business events (optional) · volume band · queue metadata and lineage · business observations · historical RCA.

Each element resolves to **Available**, **Missing** or **Not Applicable**. The three are never conflated.

---

# 12. Statistical Discipline

- Metrics selected by hypothesis, never executed exhaustively
- Every metric records why it was selected
- Stock and flow aggregated differently, never by the same routine
- Lag determined empirically per queue, not prescribed
- Drivers applied only where they show demonstrated correlation with that queue's demand
- No unexplained statistical output appears in the application

---

# 13. Recursive Reasoning

## Two bounded loops

| Loop | Bound |
|---|---|
| **Recursive root cause depth** — the "why → why" chain | Configurable maximum reasoning depth |
| **Challenge loop** — cross-examination returning work | **Maximum 3 iterations** (`BR-117`), early exit on no new evidence |

Both terminate deterministically. Both record their terminating condition.

## Recursive root cause depth

Each level records question, answer, supporting evidence, confidence, decision and — on the final level — termination reason.

Depth terminates where: maximum depth reached · no evidence item at the next level meets minimum strength · the claim would re-derive one already asserted at a shallower depth.

---

# 14. Cross-Examination Requirement

Every accepted conclusion shall be challenged before publication.

Questions are drawn from a **fixed catalogue** with semantic keys, making deduplication exact. The loop is bounded. Where it terminates by iteration cap or no-new-evidence, the outcome shall **not** be a clean "Accepted" — the conclusion was interrupted, not validated — and confidence is capped at Low.

---

# 15. Confidence Model

Confidence is calculated from **eight** weighted dimensions:

| Dimension | Weight |
|---|---|
| ContradictoryEvidence | 0.20 |
| EvidenceStrength | 0.18 |
| BusinessRuleValidation | 0.15 |
| StatisticalAgreement | 0.14 |
| DataSufficiency | 0.12 |
| ContextCompleteness | 0.10 |
| HistoricalConsistency | 0.06 |
| ModelAgreement | 0.05 |

Full specification in `FC_RCA_Business_Rules.md §5B`.

Three availability states — Available, Missing, Not Applicable. **Confidence shall never increase because evidence was lost.**

Eight caps limit confidence where specific weaknesses exist. The lowest binds. Whenever a cap binds, the gate, threshold and actual figure are all stated.

---

# 16. Progressive Disclosure

Simple by default. Detailed on demand.

## The exception

**The Confidence level, its dimension decomposition and any binding cap are always visible** and shall never be collapsed. Progressive disclosure does not apply to them.

A prominent confidence figure with hidden limitations is misleading by construction.

---

# 17. Output Requirements

Default output: Executive Summary · Root Cause · Confidence with decomposition · Recommendations · Business Impact.

Every output shall distinguish four hypothesis states: **Accepted · Rejected · Suppressed · Not Applicable.** These support different actions and shall never share a presentation.

Partial periods carry a **Timeline callout**. Complete periods carry none — its absence signifies completeness.

---

# 18. Development Standards

| Standard |
|---|
| Configuration over hardcoding |
| Reusable components |
| Business rules separated from implementation |
| Modular architecture |
| Major design decisions versioned |
| Assumptions documented |
| Designed for enterprise deployment |

## Code requirements

Modular · readable · testable · observable · explainable · extensible · secure · configuration-driven · version controlled. With error handling, logging, validation and useful comments. Unnecessary dependencies avoided.

---

# 19. Review Standards

Before recommending implementation, review: completeness · correctness · consistency · simplicity · scalability · maintainability · security · explainability · governance · testability.

**Identify weaknesses before proceeding.**

---

# 20. Decision Framework

Every recommendation considers business value · user experience · technical feasibility · operational complexity · enterprise compatibility · long-term maintainability.

**Prefer the simplest solution that satisfies the business objective.**

---

# 21. Auditability

Every RCA shall be reproducible from its audit record alone. The reproducibility set:

| Item |
|---|
| `Input_Fingerprint` |
| `Business_Rules_Version` |
| `Weights_Version` |
| `Hypothesis_Catalogue_Version` |
| `Question_Catalogue_Version` |
| `Prompt_Version` |
| `Model_Version` and `Seed` |
| Full prompt and full response |

Audit information shall never be deleted.

---

# 22. Executive Summary Standards

- Executive-ready
- Plain, simple, concise language
- Presented as bullet points
- No statistical notation, no metric names, no technical terms
- Every claim traceable to evidence

**No word or sentence limit applies.** No configuration key is required.

---

# 23. Performance

| Target | Value |
|---|---|
| Complete RCA | Under 60 seconds |
| Asynchronous execution | **Mandatory** — job submission returns HTTP 202 with a job identifier |
| Generated RCAs | Immutable and cached. Reopening never regenerates |

## Timeout behaviour — a correctness requirement

Where an RCA exceeds its time budget mid-investigation, it is marked **`Incomplete`** and published with:

- A banner listing stages not executed
- **Confidence capped at Low** (Gate 7)
- An Executive Summary stating *"provisional — investigation incomplete"* rather than a settled root cause

Where an unrecoverable error occurs, it is marked **`Failed`** and **not published**. The reason is recorded in the audit trail.

**A partial RCA may be published. It must never be mistakable for a complete one.**

Performance shall never be optimised at the cost of explainability.

---

# 24. Volumetrics

| Measure | Value |
|---|---|
| Queues | ~427 |
| Generation window | Trailing 13 fiscal weeks |
| Evaluable queue-weeks in window | ~5,434 |
| RCA scope at ±5% | ~83% of evaluable |
| Weekly narrative calls | ~1,000 across three grains |
| Analysis levels | 113 / 286 / 427 |

Monthly and quarterly RCAs are recomputed weekly as actuals arrive.

---

# 25. AI Governing Principles

| # | Principle |
|---|---|
| 1 | The LLM shall never create evidence |
| 2 | Prefer **Unknown** over **wrong with high confidence** |
| 3 | Every conclusion is explainable |
| 4 | The AI is subordinate to deterministic evidence |
| 5 | No autonomous action |
| 6 | Every AI invocation is reproducible |

---

# 25A. AI Safety and Responsible Use

§25 states the principles. This section states how they are **enforced**.

## Principle 1 — The AI shall never create evidence

**Enforcement:** the LLM is invoked only after all evidence is collected and the root cause selected. Any numeric value in its output absent from its inputs causes **rejection** (`AI_Agent_Architecture §15A`).

## Principle 2 — Prefer "Unknown" over "wrong with high confidence"

**Enforcement:**

| Mechanism | Effect |
|---|---|
| Confidence caps (`§5B`) | Ceilings for specific weaknesses |
| `BR-306` | No root cause assigned where none is defensible |
| `BR-112` Tier C | Warranty hypothesis suppressed on invalid data |
| `BR-117` | A conclusion that exhausted its challenge budget cannot be "Accepted" |
| `BR-118` | Confidence cannot be inflated by citing weaker precedent |
| `BR-121` | A driver that does not track demand is not used |

## Principle 3 — Every conclusion is explainable

**Enforcement:** an RCA that cannot be decomposed to dimension level is **not published**. Confidence decomposition is exempt from progressive disclosure and always visible.

## Principle 4 — The AI is subordinate to deterministic evidence

**Enforcement:** structural. The LLM cannot generate hypotheses, questions, evidence or confidence. It writes prose from findings already fixed.

## Principle 5 — No autonomous action

**Enforcement:** the engine produces analysis and recommendations. It executes nothing. No forecast is altered, no action taken, no system updated.

## Principle 6 — Reproducibility

**Enforcement:** model version, prompt version, temperature, seed, full prompt and full response persisted with every RCA. Weights, catalogue and rule versions likewise.

## Failure Modes and Mitigations

| Failure mode | Mitigation |
|---|---|
| Model produces plausible but fabricated detail | Numeric validation against inputs; rejection |
| Model omits an inconvenient finding | Contradictory evidence and callout presence checks |
| Model output drifts after a provider update | Version pinning; regression reference set |
| Instruction embedded in an analyst annotation alters behaviour | **Context isolation** — data never treated as instruction |
| Cost escalates unnoticed | Token ceilings; daily budget |
| Narrative implies more certainty than evidence supports | Confidence level and cap reason mandatory in narrative; validated |
| Weak conclusion recycled as strong evidence | `BR-203` eligibility gate; `BR-118` provenance ceiling |

## Out of Scope for Phase 1

- Autonomous learning or model fine-tuning
- Prompt A/B testing in production
- LLM-generated hypotheses or questions
- Any LLM involvement in numeric calculation

---

# 26. Documentation Standards

Every document shall include: Purpose · Scope · Version · Assumptions · Dependencies · Acceptance Criteria · Related Documents · Owner · Approver.

When any approved design changes, every affected document is identified and updated. **Documentation inconsistency is not permitted.**

---

# 27. Governance

| Requirement | Detail |
|---|---|
| Business ownership | Rules and thresholds owned by the business |
| Approval | Rule, threshold, catalogue and prompt changes require approval |
| Versioning | Every artifact versioned |
| Segregation | Authoring and approval are separate roles |
| Evidence | Threshold changes validated against real data before release |
| Decision record | Change packages serve as the decision register |

---

# 28. Critical Failure Definition

**Publishing a conclusion that the evidence does not support, with confidence that the evidence does not justify, is a critical failure.**

It arises when multiple methods agree because they share a corrupted input. Every validation gate, relevance gate, cap and ceiling in this specification exists to prevent it.

---

# 29. Guiding Principles

- Business correctness before everything
- Deterministic logic before AI reasoning
- Evidence before conclusion
- Explainability before convenience
- Simplicity before sophistication
- **Unknown before wrong**

---

# End of Document
