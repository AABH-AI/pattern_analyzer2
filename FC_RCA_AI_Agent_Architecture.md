# FC_RCA_AI_Agent_Architecture

**Project:** Forecast RCA Studio (FC_RCA)
**Document Type:** AI Agent Architecture Specification
**Version:** 2.0.0
**Supersedes:** Version 1.0.0
**Status:** Approved for Development
**Last Updated:** 30 July 2026

---

## Document Control

| Item | Detail |
|---|---|
| **Purpose** | Define the AI reasoning pipeline, the boundary of LLM involvement, the prompt contract, versioning and guardrails. |
| **Scope** | AI reasoning for Phase 1. |
| **Version basis** | Incorporates P1–P10. **Version 2.0.0 confines the LLM to narrative generation only.** |
| **Dependencies** | `FC_RCA_RCA_Methodology.md` v2.0 owns the canonical sequence and both catalogues. |
| **Acceptance Criteria** | (1) Identical inputs produce identical structured output. (2) No hypothesis exists outside the catalogue. (3) Every LLM invocation is version-pinned and reproducible. (4) LLM failure never blocks an RCA. |
| **Owner** | Product Owner, FC_RCA |
| **Approver** | Pending |

---

# 1. Purpose

This document defines how the AI reasons — and, more importantly, where it does not.

---

# 2. The Central Architectural Decision

Version 1.0.0 assigned the LLM three jobs: generating hypotheses, generating cross-examination questions, and writing the narrative.

**Version 2.0.0 confines the LLM to narrative generation.**

```
VERSION 1.0.0                        VERSION 2.0.0
─────────────                        ─────────────
Context ──> LLM ──> hypotheses       Context ──> Catalogue ──> hypotheses
Evidence ─> LLM ──> questions        Evidence ─> Catalogue ──> questions
Findings ─> LLM ──> narrative        Findings ─> LLM ───────> narrative
                                                    ↑
                                          only LLM invocation point
```

## Why

`FC_RCA_Testing_and_Validation_Strategy.md` requires *"AI reasoning shall be deterministic when identical inputs are supplied."* With an LLM generating hypotheses, that is unachievable — a paraphrase produces a different hypothesis set, and two runs of the same investigation could test different things.

## What this protects

The Evidence Hierarchy places LLM reasoning at the bottom, below business rules, statistics and historical evidence. This decision enforces that **structurally** rather than by policy: the LLM is physically unable to introduce a hypothesis that has not been approved, because it is never asked for one.

**An instruction a model might disregard is weaker than a capability it does not have.**

---

# 3. AI Responsibilities

| Responsibility | Mechanism | LLM involved |
|---|---|---|
| Hypothesis generation | Deterministic catalogue | **No** |
| Evidence collection | Rules and retrieval | No |
| Statistical selection | Hypothesis-driven | No |
| Recursive reasoning | Rule-driven, depth-bounded | No |
| Cross-examination | Deterministic question catalogue | **No** |
| Confidence calculation | Weighted formula | **No** |
| Root cause selection | Decision matrix | No |
| Recommendation generation | Rule-derived | No |
| **Narrative generation** | **LLM** | **Yes** |

---

# 4. AI Reasoning Pipeline

```
Forecast Data
      ↓
Data Validation
      ↓
Adherence Calculation
      ↓
Deviation Detection
      ↓
Context Building
      ↓
Hypothesis Generation           (catalogue — §8)
      ↓
Evidence Collection
      ↓
Statistical Validation
      ↓
Recursive Root Cause Reasoning
      ↓
Cross-Examination               (catalogue, bounded loop — §11)
      ↓
Confidence Assignment
      ↓
RCA Generation
      ↓
Decision Card
      ↓
Executive Summary               (LLM — §15)
      ↓
Audit Trail
```

**No stage may be skipped.**

Consistent with the canonical sequence in `FC_RCA_RCA_Methodology.md §6`. Version 1.0.0 placed Context Building **before** Deviation Detection; this is corrected — context is built for periods that require investigation.

---

# 5. AI Reasoning Lifecycle

| Stage | Purpose |
|---|---|
| **Understand** | What deviated, by how much, in which direction |
| **Contextualise** | What business context applies, and what does not |
| **Hypothesise** | Which catalogue entries are applicable |
| **Evidence** | What supports and what contradicts each |
| **Deepen** | Why, recursively, until mechanism or exhaustion |
| **Challenge** | Attempt to disprove the surviving conclusion |

---

# 6. Business Context Consumed

- Fiscal calendar, fiscal month and quarter
- Holiday calendar with impact windows and holiday-anchored comparison
- Shipment plan and warranty coverage — Tier A/B only, relevance-gated
- Installed base (ASU) — relevance-gated
- Business events — optional, no penalty when absent
- Volume band and queue behaviour
- Queue metadata, lineage and forecaster
- Business observations and analyst annotations
- Historical RCA — eligibility-gated, provenance-weighted

---

# 7. Context Elements and Applicability

Each element resolves to Available, Missing or Not Applicable. The distinction is load-bearing:

| State | Confidence effect |
|---|---|
| Available | Scored |
| **Missing** | Retained at a floor. **Penalty** |
| **Not Applicable** | Excluded, weights renormalised. **No penalty** |

---

# 8. Hypothesis Generation

Deterministic, from the Candidate Hypothesis Catalogue in `FC_RCA_RCA_Methodology.md §12`. No LLM.

```
FOR each hypothesis H in catalogue:
    IF H.applicability_conditions satisfied:
        generate H
    ELSE:
        record H as NOT GENERATED with the failing condition
```

## Hypothesis categories

| Category | Entries |
|---|---|
| Calendar | Holiday · Fiscal Month Transition · Quarter Transition · Seasonality |
| Demand | Demand Spike · Demand Drop · Demand Shift · Volume Redistribution |
| Forecast | Forecast Bias · Trend Misidentification |
| Business | Warranty Mix Shift · Installed Base Change · ASU Plan Variance · Shipment Volume Change · Queue Migration |
| Statistical | Outlier · Drift · Momentum Shift · Variance Expansion |
| Data Quality | Missing Data · Incorrect Mapping · Duplicate Records · Insufficient History |

## Driver cascade

Business causality sets the order; the relevance gate decides usability.

| Offering | Cascade |
|---|---|
| **Basic** | **Shipments** → ASU → next |
| Premium, Pro | ASU → Shipments → next |
| Out-of-warranty | Neither applies |

## Constraint

The engine shall **not** generate a hypothesis outside the catalogue. Any pattern with no matching entry is recorded as an **UNEXPLAINED OBSERVATION** and surfaced for catalogue extension.

## Suppression

Where a hypothesis cannot be generated because a data-quality gate failed, it is recorded as **Suppressed**, distinguishable from **Rejected** and from **Not Applicable**. Suppression is recorded and surfaced.

---

# 9. Evidence Collection

Supporting and contradictory evidence collected as separate mandatory steps. Independence weighted over volume. Five-level strength scale.

---

# 10. Recursive Root Cause Reasoning

Depth-bounded per `MBS §13`. Each level records question with semantic key, answer, supporting evidence, confidence, decision and — on the final level — termination reason.

Circular reasoning is prevented by semantic-key comparison: a node may not re-derive a claim already asserted at a shallower depth.

---

# 11. Cross-Examination

Questions drawn deterministically from the Challenge Question Catalogue in `FC_RCA_RCA_Methodology.md §18`. No LLM.

Five categories, 17 base questions, each with a fixed semantic key.

## Selection

```
applicable_questions = catalogue WHERE
    question.applies_to_categories CONTAINS hypothesis.category
    AND question.semantic_key NOT IN already_asked
```

## Deduplication

Because keys are fixed and finite, deduplication is **exact**. There is no paraphrase risk. This is the enforcement mechanism that `RCA Methodology §17` required and could not previously provide against generated text.

## Termination

Bounded per `BR-117` — maximum 3 iterations, early exit on no new evidence, forced outcome on exhaustion. The catalogue is finite, so termination condition 4 (question pool exhausted) is reachable and testable.

## Answering

Answered **from evidence**, not by an LLM. Each answer cites its evidence items.

---

# 12. Confidence Assignment

Calculated per `FC_RCA_Business_Rules.md §5B`. Eight weighted dimensions:

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

Version 1.0.0 listed seven and omitted `BusinessRuleValidation`.

**Confidence shall never be randomly assigned, and shall never be produced by an LLM.** The Confidence Engine contains no LLM call.

---

# 13. Root Cause Selection

Decision matrix over surviving hypotheses, weighing evidence strength, confidence, cross-examination outcome and business rule consistency. Deterministic.

---

# 14. Recommendation Generation

Rule-derived per `BR-701`, `BR-702`, `BR-704`. Maximum three. Priority derived from recurrence and deviation magnitude. Impact qualitative. Routed to the Demand / Forecast Team.

---

# 15. Executive Narrative Engine

**This is the only stage where an LLM is invoked.**

## Purpose

Convert completed findings into executive-ready prose. The engine **writes**; it does not analyse, decide, select or infer.

## Inputs — all produced upstream, all fixed before the call

- Root cause, selected by the Decision Engine
- Supporting and contradictory evidence
- Confidence level, decomposition and any binding cap
- Recommendations, maximum three
- Data availability callouts and Timeline label
- Business context

## Output Requirements

- Executive-ready
- Plain, simple, concise language
- Presented as bullet points
- No statistical notation, no metric names, no technical terms
- Every claim traceable to a supplied evidence item

**No word or sentence limit applies.** Quality is governed by the requirements above, not by length. No configuration key is required.

## Constraints

The narrative engine shall **not**:

- introduce any fact not present in its inputs
- alter a root cause, confidence level or recommendation
- soften, strengthen or reinterpret a confidence assessment
- omit a contradictory evidence item supplied to it
- omit a data availability callout supplied to it
- infer causation beyond what the evidence states

## Failure Handling

Where the LLM call fails, times out or returns invalid output, the RCA is completed **without** a narrative and marked `Incomplete`. All structured output — root cause, evidence, confidence, recommendations — remains fully available.

**An LLM failure shall never block an RCA.** The reasoning is complete before the narrative is written.

---

# 15A. Prompt Contract

Governs every LLM invocation. There is exactly one invocation point: §15.

## Invocation Parameters — mandatory

| Parameter | Value | Rationale |
|---|---|---|
| Model identifier | **Pinned, exact** | An unannounced provider update would silently change output |
| Model version | **Pinned, exact** | Same |
| Temperature | **0** | Deterministic sampling |
| Top-p | 1.0 | No nucleus truncation |
| Seed | Fixed, recorded | Reproducibility where supported |
| Max output tokens | Configured | Cost and latency ceiling |
| Stop sequences | Configured | Prevent runaway generation |

**Model version pinning is mandatory.** An unpinned model makes every historical RCA irreproducible the moment the provider updates.

## Prompt Structure

Every prompt has four fixed parts:

| # | Part | Content |
|---|---|---|
| 1 | **SYSTEM** | Role, constraints, prohibitions. Versioned. Never varies within a prompt version |
| 2 | **SCHEMA** | Required output structure. Strict |
| 3 | **CONTEXT** | Structured findings. **Data only.** No instruction text, no free-form content |
| 4 | **TASK** | The specific narrative requested |

## Context Isolation — mandatory

The CONTEXT block contains **data only**.

Analyst annotations, business observations and any other free-text field retrieved from the repository shall be passed as **clearly delimited data, never as instruction.** Text within a data field shall never be interpreted as a directive.

Rationale: analyst annotations are user-supplied free text stored in the repository and later retrieved into a prompt. Without delimitation, text in an annotation could alter engine behaviour.

## Output Schema — strict

```json
{
  "executiveSummary": ["bullet", "bullet", "bullet"],
  "rootCauseStatement": "string",
  "confidenceExplanation": "string",
  "limitations": ["string"],
  "recommendationNarratives": [
    { "recommendationId": "string", "text": "string" }
  ]
}
```

Free-form text responses are **rejected**. Malformed output is retried once, then treated as failure per §15.

## Validation — every response, before use

| Check | Action on failure |
|---|---|
| Conforms to schema | Retry once, then fail |
| Contains no numeric value absent from inputs | **Reject and fail** |
| Contains no root cause other than the one supplied | **Reject and fail** |
| Confidence level matches the supplied level exactly | **Reject and fail** |
| All supplied contradictory evidence is represented | **Reject and fail** |
| All supplied callouts are represented | **Reject and fail** |

A response failing validation is **discarded entirely**. The RCA is marked `Incomplete` and published without a narrative. **A response is never partially accepted.**

## Cost and Latency Ceilings

| Control | Purpose |
|---|---|
| Max tokens per invocation | Bounds single-call cost |
| Max invocations per RCA | 1 narrative + 1 retry |
| Timeout per invocation | Bounds latency |
| Daily token budget | Bounds aggregate cost |

Estimated Phase 1 volume: approximately 1,000 narrative calls per week, ~3.8 million tokens per week, ~550,000 per day. The daily ceiling is set at deployment.

## Recording — mandatory

Every invocation persists: prompt version, model identifier and version, temperature, seed, full prompt, full response, validation outcome, token counts, latency and retry count.

An RCA whose narrative cannot be reproduced from its audit record is not compliant.

---

# 15B. Prompt Versioning and Change Control

## Versioning

Every prompt carries a semantic version, recorded on every RCA that used it.

| Change | Increment |
|---|---|
| Wording clarification, no behaviour change | Patch — 1.0.1 |
| New output field or constraint | Minor — 1.1.0 |
| Changed role, task or schema | Major — 2.0.0 |

## Immutability

A released prompt version is **immutable**. Changes create a new version. Prior versions are retained indefinitely so any historical RCA can be reproduced with the prompt that actually generated it.

## Change Control

| Requirement | Detail |
|---|---|
| Approval | Same approval as a business rule change |
| Regression | Run against a fixed reference set before release |
| Comparison | Old and new output compared side by side |
| Rollback | Any version may be reinstated |

## Reference Set

A fixed set of completed RCAs spanning: high and low confidence, each capped state, Not Applicable dimensions, Missing dimensions, partial periods, all three grains, and each hypothesis category.

Every prompt change is executed against this set. Differences are reviewed before release.

## Experimentation

**Prompt A/B testing is FUTURE SCOPE and shall not run in production.** Two prompt versions active simultaneously would make output non-reproducible without recording which served each request, and would produce inconsistent narratives for equivalent investigations.

Only **one** prompt version may be active.

## Determinism Statement

| Stage | Mechanism | Deterministic |
|---|---|---|
| Adherence | Formula | Yes |
| Deviation detection | Threshold | Yes |
| **Hypothesis generation** | **Catalogue** | **Yes** |
| Evidence collection | Rules | Yes |
| Statistics | Formulae | Yes |
| Recursive reasoning | Bounded, rule-driven | Yes |
| **Cross-examination** | **Fixed catalogue, bounded** | **Yes** |
| Confidence | Weighted formula | Yes |
| Root cause selection | Decision matrix | Yes |
| Narrative | Pinned model, temp 0, pinned prompt | Yes, subject to provider guarantees |

The single residual dependency is the LLM provider honouring temperature 0 and seed. Where a provider cannot guarantee this, the narrative may vary in **wording** while all structured output remains identical.

Testing asserts strictly on **structured** output and treats narrative wording variation as a **tolerance**, logged rather than failed. A difference in **fact** is never tolerated.

---

# 16. AI Guardrails

## Scope

The LLM is invoked at one point. These guardrails apply to that invocation and are enforced by the validation checks in §15A.

## Prohibitions — enforced, not advisory

| Prohibition | Enforcement |
|---|---|
| Invent evidence | Numeric values absent from inputs → response rejected |
| Generate a root cause | Root cause other than the supplied one → rejected |
| Assign or alter confidence | Level mismatch → rejected |
| Generate a hypothesis | **Never asked** — catalogue (§8) |
| Generate a cross-examination question | **Never asked** — catalogue (§11) |
| Omit contradictory evidence | Supplied item absent → rejected |
| Omit a data availability callout | Supplied callout absent → rejected |
| Execute a statistical calculation | No calculation capability exposed |
| Act on instructions embedded in data | Context isolation (§15A) |

## Structural Guarantees

Three prohibitions are guaranteed by **architecture** rather than instruction — the LLM cannot violate them because it is never asked:

1. It cannot generate a hypothesis outside the approved catalogue.
2. It cannot generate an unbounded cross-examination question set.
3. It cannot produce a confidence score.

## Human Oversight

- Every RCA is reviewable by an analyst
- Analysts may record disagreement as an annotation (`BR-120`), retained and visible
- **No autonomous action follows from an RCA.** Recommendations are suggestions to humans, never executed

---

# 17. Human-in-the-Loop

## Phase 1 — capture without consumption

Analysts may:

| Action | Available |
|---|---|
| **Accept** an RCA | Yes |
| **Reject** an RCA, with reasoning | Yes |
| Record an **annotation** | Yes |
| **Modify** an RCA | **No** |

**Modify is deliberately excluded.** A machine-generated conclusion carrying a machine-calculated confidence score must retain its auditable derivation. An analyst who disagrees records the disagreement; the RCA may then be re-run under `BR-124`.

## Annotations become evidence

Annotations are stored as Business Observations and are **retrievable by future investigations** on the same queue, with provenance weight 1.00 — the highest available, as human-verified evidence.

Displayed as a **normal comment** in the narrative, with a clickable provenance control revealing source, author, why retrieved and impact.

## No autonomous learning

Annotations do **not** adjust the model, prompts, hypothesis weights or thresholds. They become retrievable evidence — nothing more.

The engine produces better RCAs over time because it has access to more evidence, not because it changed itself. This is compatible with the Phase 1 exclusion of closed-loop learning.

---

# 18. AI Safety Position

Enforcement of the AI principles is specified in `FC_RCA_Master_Build_Specification__MBS_.md §25A`. In summary:

| Principle | Enforcement |
|---|---|
| Never create evidence | Numeric validation against inputs |
| Prefer Unknown over wrong | Caps · `BR-306` · `BR-112` Tier C · `BR-117` · `BR-118` |
| Every conclusion explainable | Non-decomposable confidence is not published |
| AI subordinate to deterministic evidence | Structural — no hypothesis, question, evidence or confidence generation |
| No autonomous action | Recommendations are suggestions only |
| Reproducibility | Model, prompt, temperature, seed and full exchange persisted |

---

# 19. Out of Scope for Phase 1

- Autonomous learning or model fine-tuning
- Prompt A/B testing in production
- LLM-generated hypotheses or cross-examination questions
- Any LLM involvement in numeric calculation
- Multi-agent architecture

---

# 20. Guiding Principles

- The LLM explains; it never decides
- A capability the model does not have is stronger than an instruction it might disregard
- Determinism is achieved by removing generation, not by constraining it
- Every invocation is reproducible or the RCA is not compliant
- Human knowledge enters as evidence, never as autonomous adjustment

---

# End of Document
