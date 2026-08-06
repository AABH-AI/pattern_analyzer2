# FC_RCA_RCA_Methodology

**Project:** Forecast RCA Studio (FC_RCA)
**Document Type:** RCA Methodology Specification
**Version:** 2.0.0
**Supersedes:** Version 1.0.0
**Status:** Approved for Development
**Last Updated:** 30 July 2026

---

## Document Control

| Item | Detail |
|---|---|
| **Purpose** | Define how an investigation is conducted: the canonical sequence, the hypothesis catalogue, evidence handling, recursive reasoning, cross-examination, confidence and output. |
| **Scope** | Investigation methodology for Phase 1. |
| **Authority** | **§6 of this document is the canonical execution sequence.** Where any other document specifies a different order, this section prevails. |
| **Version basis** | Incorporates P1–P10. |
| **Dependencies** | `FC_RCA_Definitions_and_Formulas.md` v2.0 · `FC_RCA_Business_Rules.md` v2.0 |
| **Acceptance Criteria** | (1) No stage may be skipped. (2) Every hypothesis originates from the catalogue. (3) Every loop terminates deterministically. |
| **Owner** | Product Owner, FC_RCA |
| **Approver** | Pending |

---

# 1. Purpose

This document defines how Forecast RCA Studio investigates a deviation.

It answers: what happens, in what order, with what inputs, under what constraints, and how the investigation knows when to stop.

---

# 2. Methodology Principles

| # | Principle |
|---|---|
| 1 | **Never stop at correlation.** Continue until a business root cause is identified or none is defensible |
| 2 | **Multiple competing hypotheses**, generated deterministically |
| 3 | **Contradictory evidence actively sought**, not merely tolerated |
| 4 | **Cross-examine the conclusion** — attempt to disprove it |
| 5 | **Bounded reasoning.** Every recursive path terminates |
| 6 | **Prefer Unknown** over wrong with high confidence |
| 7 | **Every step recorded** and replayable from the audit trail |

---

# 3. What This Methodology Is Not

- Not a search for the strongest correlation
- Not an exhaustive statistical sweep
- Not a narrative generator dressed as analysis
- Not a system that must always produce an answer

`Inconclusive` is a valid, correct outcome.

---

# 4. Scope of Investigation

| Item | Value |
|---|---|
| Metric | Forecast Adherence — `(1 − Actual_Offered / fcst_offered) × 100` |
| Grain | Weekly · Monthly · Quarterly, **independently** |
| Trigger | `ABS(adherence) > 5%`, fixed |
| Window | Trailing 13 fiscal weeks ending at the latest week with actuals |
| Horizon | Only periods with actuals available |

---

# 5. Investigation Inputs

- Forecast and actual volumes for the period
- Business context: calendar, holidays, shipments, warranty, installed base, events, volume band, queue metadata, lineage
- Historical RCAs, eligibility-gated and provenance-weighted
- Business observations and analyst annotations
- Business rules in force, with their versions

---

# 6. End-to-End RCA Lifecycle — CANONICAL

> **THIS SECTION IS THE CANONICAL EXECUTION SEQUENCE.**
>
> Where any other document specifies a different order, this section prevails and that document shall be corrected. `MBS §10` expresses the same sequence at coarser granularity and is consistent with it. `MBS §6` describes module **layering**, not execution order.

```
Step  1   Receive Forecast Data
Step  2   Validate Data Quality
Step  3   Calculate Forecast Adherence
Step  4   Detect Significant Deviation
Step  5   Build Business Context
Step  6   Generate Candidate Hypotheses
Step  7   Collect Supporting Evidence
Step  8   Collect Contradictory Evidence
Step  9   Evaluate Statistical Evidence
Step 10   Perform Recursive Root Cause Reasoning
Step 11   Execute Cross-Examination          ← bounded loop, §29
Step 12   Assign Confidence
Step 13   Generate RCA
Step 14   Generate Executive Summary
Step 15   Persist Audit Trail
```

## Structural Invariants

| Invariant | Rationale |
|---|---|
| Steps 7–8 (evidence) precede Step 9 (statistics) | Evidence collection determines which statistical tests are relevant |
| **Step 6 (hypotheses) precedes Step 9 (statistics)** | Hypotheses select metrics. Statistical Framework Principle 4 forbids unnecessary execution |
| **Step 11 (cross-examination) precedes Step 12 (confidence)** | Cross-examination may return Reinvestigate or Reject; confidence caps depend on its outcome |
| Step 4 (deviation) precedes Step 5 (context) | Context is built for periods requiring investigation |

**No workflow step may be skipped.**

Step 11 contains a bounded loop. See §29.

---

# 7. Step 1 — Receive Forecast Data

Inputs are received at queue × fiscal week grain. The input row set is fingerprinted (`Input_Fingerprint`) so the investigation can later be checked for data change on re-run.

---

# 8. Step 2 — Validate Data Quality

Business Rules `BR-101` to `BR-122` execute. Outcomes:

| Outcome | Effect |
|---|---|
| Pass | Continue |
| Flag | Continue with the field flagged and excluded, confidence reduced |
| Reject | Stop. Reason recorded |

Zero is a real observation. Blank is missing. Interior blanks up to three weeks are zero-filled; longer runs mark the queue inactive.

---

# 9. Step 3 — Calculate Forecast Adherence

```
Forecast Adherence % = (1 − (Actual_Offered / fcst_offered)) × 100
```

Signed. Stored signed. Monthly and quarterly use the **Pooled** method over weeks with actuals.

Where `fcst_offered = 0`, adherence is non-computable. The period is excluded and flagged (`BR-110`).

---

# 10. Step 4 — Detect Significant Deviation

`ABS(adherence) > 5%` → RCA generated, subject to the generation window.

Direction is recorded and is itself evidence: a persistent one-sided pattern indicates systematic bias; alternating signs indicate volatility.

---

# 11. Step 5 — Build Business Context

Context elements retrieved, each resolving to Available, Missing or Not Applicable:

| Element | Not Applicable when |
|---|---|
| Fiscal calendar | Never |
| Holiday calendar | Country is an aggregate value |
| Shipment plan and warranty | Out-of-warranty offering, or driver fails the relevance gate |
| Installed base (ASU) | Out-of-warranty offering, or driver fails the relevance gate |
| Business events | Repository not deployed or empty |
| Volume band | Never |
| Queue metadata and lineage | Never |
| Historical RCA | No eligible precedent |

---

# 12. Step 6 — Generate Candidate Hypotheses

## Deterministic generation

Hypotheses are generated **deterministically from the Candidate Hypothesis Catalogue**. No LLM is involved.

```
FOR each hypothesis H in catalogue:
    IF H.applicability_conditions are satisfied by this investigation:
        generate H as a candidate
    ELSE:
        record H as NOT GENERATED with the failing condition
```

Identical inputs always produce an identical candidate set.

## Candidate Hypothesis Catalogue

Six categories. Each entry carries an identifier, category, name, applicability conditions, required evidence types and the metrics selected when tested.

### Calendar

| Hypothesis | Generated when |
|---|---|
| Holiday | `Holiday_Count > 0` in the period or its impact window |
| Fiscal Month Transition | Period spans a fiscal month boundary |
| Quarter Transition | Period spans a fiscal quarter boundary |
| Seasonality | ≥ 104 weeks of history **and** period is complete |

### Demand

| Hypothesis | Generated when |
|---|---|
| Demand Spike | Actual exceeds forecast beyond the volatility band |
| Demand Drop | Actual falls below forecast beyond the volatility band |
| Demand Shift | Adjacent periods show offsetting deviations |
| Volume Redistribution | Related queues show inverse deviations |

### Forecast

| Hypothesis | Generated when |
|---|---|
| Forecast Bias | Consistent one-sided deviation across recent periods |
| Trend Misidentification | Trend direction in actuals differs from forecast |

### Business

| Hypothesis | Generated when |
|---|---|
| Warranty Mix Shift | Tier A/B **and** `Shipment_Applicable` **and** passes relevance gate |
| Installed Base Change | `ASU_Applicable` **and** passes relevance gate **and** baseline available |
| ASU Plan Variance | Both `Planned_ASU` and `Actual_ASU` available **and** passes its own gate |
| Shipment Volume Change | `Shipment_Applicable` **and** passes relevance gate |
| Queue Migration | Lineage event, or inverse deviation in a related queue |

### Statistical

| Hypothesis | Generated when |
|---|---|
| Outlier | Period value exceeds outlier bounds |
| Drift | Structural change detected in the series |
| Momentum Shift | Rate of change altered materially |
| Variance Expansion | Volatility increased beyond the historical band |

### Data Quality

| Hypothesis | Generated when |
|---|---|
| Missing Data | Mandatory field blank in the period |
| Incorrect Mapping | Dimension value unmapped or newly appeared |
| Duplicate Records | Duplicate detected at the expected grain |
| Insufficient History | < 104 weeks of actuals for the queue |

## Driver Cascade — business order preserved

The relevance gate determines whether a driver is **usable**. Business causality determines the **order** drivers are tried in.

| Offering | Cascade |
|---|---|
| **Basic** | **Shipments** → ASU → next metric |
| Premium, Pro | ASU → Shipments → next metric |
| Out-of-warranty | Neither applies → calendar, volume, data quality |

Where a driver fails the gate, the cascade moves to the next. **It never reorders.** A low average pass rate does not demote a business-correct driver for the queues where it works.

## Not-Generated Recording

Every catalogue entry not generated is recorded with its failing condition. This distinguishes three states that Version 1.0.0 conflated:

- A hypothesis never applicable to this queue
- A hypothesis tested and rejected
- A hypothesis suppressed by a data-quality gate

## Known Gaps — not implementable with current data

| Hypothesis | Would test | Requires |
|---|---|---|
| **Product Lifecycle** | Whether a product entering a new lifecycle stage shifted demand | Product identifier, launch date, lifecycle stage |
| **Manual Override** | Whether a manual forecast adjustment caused the deviation | Forecast version dimension |

> **Note on `Offering`:** `Offering` is a **support tier** (`Basic` / `Pro` / `Premium` / `OOP`), not a product. Basic support did not launch and will not reach end-of-life. `Offering` shall **never** be used as a product or lifecycle proxy.

Both are documented here rather than held in the catalogue as permanently inapplicable entries, so they do not appear on every Decision Card indefinitely.

## Extensibility

The catalogue is **versioned configuration**, not code. New hypotheses are added through the Administration Portal with applicability conditions. The catalogue version is recorded on every RCA.

## Constraint

The engine shall **not** generate a hypothesis outside the catalogue. Any observed pattern with no matching entry is recorded as an **UNEXPLAINED OBSERVATION** and surfaced for catalogue extension — never converted into an ad-hoc hypothesis.

## Minimum

At least three candidate hypotheses where the catalogue yields three applicable entries. Where fewer are applicable, the shortfall and its reasons are recorded.

---

# 13. Steps 7 and 8 — Evidence Collection

Supporting and contradictory evidence are collected as **separate steps**. Contradictory evidence is actively sought, not merely noted if encountered.

## Evidence Types

| Type | Independence weight |
|---|---|
| Business rule | 1.00 |
| Deterministic statistic | 1.00 |
| Analyst annotation | 1.00 |
| Historical precedent | 0.80 |
| ML attribution | 0.60 |
| Second item from a family already counted | 0.30 |

**Independence over volume.** Three correlation metrics from the same family are not three independent confirmations.

## Evidence Strength — five levels, canonical

Very Strong 1.0 · Strong 0.8 · Moderate 0.6 · Weak 0.4 · Very Weak 0.2

## Supporting versus Contradictory

`Contradictory` is a **flag**, not an evidence type. An evidence item has a type and a supporting flag.

## Failure to seek contradiction

Where no contradiction search was performed, the `ContradictoryEvidence` confidence dimension is scored **Missing**. Omitting the search is a weakness, not a neutral outcome.

---

# 14. Step 9 — Evaluate Statistical Evidence

Metrics are selected by hypothesis (`BR-401`), never executed exhaustively.

| Measure type | Aggregation | Lag |
|---|---|---|
| Flow | SUM | Empirical per queue, 0–13 weeks |
| Stock | MEAN | Contemporaneous |
| Ratio | Recompute | n/a |

Where a selected metric cannot execute, it is recorded as **suppressed** with a reason — distinguishable from one that ran and found nothing.

---

# 15. Evidence Hierarchy

When evidence conflicts, precedence runs:

1. Verified business data
2. Business Rules
3. Deterministic statistical analysis
4. Historical patterns
5. Time-series analysis
6. ML attribution
7. LLM narrative

**AI reasoning shall never override verified business evidence.** This is enforced structurally — the LLM cannot generate evidence, hypotheses, questions or confidence.

Where a business rule contradicts the conclusion, confidence is capped at Low regardless of statistical support (`BR-505`, Gate 2).

---

# 16. Evidence Matrix

An internal audit artifact recording, per hypothesis: every evidence item, its type, source family, strength, independence weight and supporting flag. Produced for every investigation and retained.

---

# 17. Step 10 — Recursive Root Cause Reasoning

## Purpose

Move from correlation to mechanism. *"Installed base declined"* is a correlation. *"A 6,000-unit one-year-warranty cohort reached expiry"* is a cause.

## Depth

Each level asks *why* of the level above.

```
Level 0   Adherence −18.4%, 184 contacts under-forecast
Level 1   Warranty coverage mix shifted
Level 2   1-year-only share rose 31% → 38% of shipments
Level 3   A 12,000-unit shipment cohort carried reduced coverage
ROOT      Terminating cause
```

## Recorded per level

- Level number
- Question, with semantic key
- Answer
- Supporting evidence
- Confidence at that level
- Decision
- Termination reason — final level only

## Constraints and their mechanisms

| Requirement | Mechanism |
|---|---|
| Avoid circular reasoning | A node may not re-derive a claim already asserted at a shallower depth. Claims compared by normalised semantic key |
| Avoid repeated questions | Questions recorded with semantic keys. A matching key shall not be re-asked |
| Ignore unsupported assumptions | A step with no supporting evidence does not advance the chain. It is recorded and terminated |
| Stop when evidence becomes insufficient | Depth terminates where the next level yields no evidence item meeting minimum strength |
| Respect maximum depth | `MBS §13` configurable maximum reasoning depth |
| Preserve every step | Persisted per level |

> Version 1.0.0 stated the first four as instructions without mechanisms. *"Avoid repeated questions"* is not enforceable against generated text without semantic-key comparison, since a paraphrase is otherwise a new question.

## Warranty expiry as a reasoning step

Where ASU decline is identified as a driver, the next *why* may be a **warranty expiry wave** — units shipped with one-year-only coverage reaching expiry, derivable from lagged `Final_Y1 − Final_Y2`.

This is a **reasoning step, not a modelled driver.** Measured correlation between the derived expiry wave and ASU change is **−0.171** — directionally correct but too weak for a feature. And warranty begins at customer activation, not planned shipment, so a fixed 52-week lag is a proxy with unknown error. Where cited, the uncertainty is stated.

---

# 18. Step 11 — Cross-Examination

## Purpose

Attempt to **disprove** the accepted conclusion.

## Challenge Question Catalogue

Questions are drawn **deterministically** from a fixed catalogue. No LLM is involved.

Five categories, 17 base questions, each with a fixed semantic key.

| Category | Questions | Example key |
|---|---|---|
| Statistical Validation | 4 | `STAT_SIGNIFICANCE` |
| Historical Validation | 3 | `HIST_PRECEDENT` |
| Business Validation | 3 | `BIZ_RULE_CONSISTENCY` |
| Data Validation | 4 | `DATA_SUFFICIENCY` |
| Alternative Explanation | 3 | `ALT_STRONGER_HYPOTHESIS` |

## Selection

```
applicable_questions = catalogue WHERE
    question.applies_to_categories CONTAINS hypothesis.category
    AND question.semantic_key NOT IN already_asked
```

## Answering

Questions are answered **from evidence**, not by an LLM. Each answer cites the evidence items that produced it. An unanswerable question is recorded as UNANSWERED with the reason, and counts toward termination condition 3.

## Deduplication

Because keys are fixed and finite, deduplication is **exact**. There is no paraphrase risk — a question either has been asked or has not.

---

# 19. Cross-Examination Outcomes

| Outcome | Meaning |
|---|---|
| **Accepted** | Conclusion survived challenge |
| **Accepted with Caveats** | Survived, with stated limitations |
| **Reinvestigate** | Weakness identified requiring further investigation — subject to the iteration bound |
| **Reject** | Conclusion does not hold |

## Reinvestigate constraints

| Constraint | Rule |
|---|---|
| Maximum iterations | 3, configurable |
| Early termination | An iteration retrieving no new evidence ends the loop |
| Question reuse | Prohibited — semantic key deduplication |
| Outcome on cap exhaustion | **Accepted with Caveats, or Inconclusive. Never Accepted** |

Reinvestigate is **not available** where the iteration bound has been reached, the previous iteration retrieved no new evidence, or all applicable questions have been asked.

---

# 20. Recursive Challenge Loop — BOUNDED

```
                Accepted Hypothesis
                        │
    ┌─── iteration = 1 ─┴───────────────────────┐
    │                                            │
    │   Challenge (questions not yet asked)       │
    │            ↓                                │
    │   Weakness Detected?                        │
    │            ↓ YES                            │
    │   Return to Investigation                   │
    │            ↓                                │
    │   Retrieve Additional Evidence              │
    │            ↓                                │
    │   New evidence retrieved?  ── NO ──┐        │
    │            ↓ YES                    │        │
    │   Revalidate                        │        │
    │            ↓                        │        │
    │   iteration < 3?  ── NO ──┐         │        │
    │            ↓ YES           │         │        │
    │   iteration = iteration+1  │         │        │
    └────────────┘               │         │        │
                                 ↓         ↓        ↓
                        TERMINATE: forced outcome
                     (Accepted with Caveats | Inconclusive)

    Weakness NOT detected → TERMINATE: Accepted | Accepted with Caveats
```

## Termination — `BR-117`

| # | Condition | Outcome permitted |
|---|---|---|
| 1 | Conclusion survives a full round | Accepted / Accepted with Caveats |
| 2 | `iteration_count` reaches 3 | **Accepted with Caveats / Inconclusive** |
| 3 | An iteration retrieves no new evidence | **Accepted with Caveats / Inconclusive** |
| 4 | Question pool exhausted | Accepted / Accepted with Caveats |
| 5 | Conclusion rejected | Reject |

## Why conditions 2 and 3 cannot yield a clean Accepted

Running out of iterations, or out of new evidence, is not the same as withstanding challenge. **The conclusion was interrupted, not validated.** Confidence Gate 7 caps such conclusions at Low.

## New evidence test

An iteration retrieves no new evidence where every item returned is already present in the evidence set, compared by `(source, metric, period, value)`. Mechanical, requires no judgement.

## Reproducibility

Every iteration is persisted with its questions, evidence, weaknesses and outcome. The loop shall be replayable from the audit record.

---

# 21. Step 12 — Assign Confidence

Calculated per `FC_RCA_Business_Rules.md §5B`. Eight weighted dimensions, three availability states, eight caps.

## Confidence Dimensions

| # | Dimension | Weight | Meaning |
|---|---|---|---|
| 1 | ContradictoryEvidence | **0.20** | Extent to which evidence opposes the conclusion |
| 2 | EvidenceStrength | 0.18 | Quality and source-independence of support |
| 3 | BusinessRuleValidation | 0.15 | Whether deterministic rules support the conclusion |
| 4 | StatisticalAgreement | 0.14 | Whether multiple metrics concur |
| 5 | DataSufficiency | 0.12 | History depth, period coverage, field completeness |
| 6 | ContextCompleteness | 0.10 | Availability of applicable business context |
| 7 | HistoricalConsistency | 0.06 | Whether history supports the conclusion |
| 8 | ModelAgreement | 0.05 | Whether analytical methods concur |

Version 1.0.0 listed seven and omitted `BusinessRuleValidation`, which `MBS §15` required. All eight are now specified and persistable.

**Contradiction carries the greatest weight** deliberately. The engine's primary obligation is to avoid confident error.

## Confidence Levels — five, canonical

| Score | Level |
|---|---|
| ≥ 0.85 | Very High |
| 0.70 – 0.849 | High |
| 0.50 – 0.699 | Medium |
| 0.30 – 0.499 | Low |
| < 0.30 | Very Low |

PRD Version 1.0 specified three levels and has been corrected.

## Caps

A level may be capped below its calculated value. **A capped score shall always display both the calculated level and the binding cap**, with the threshold crossed and the actual figure, so a reader can distinguish a weak analysis from a strong analysis with a specific limitation.

---

# 22. Step 13 — Generate RCA

## Root Cause Selection

The surviving hypothesis with the strongest evidence and highest confidence, subject to:

- Cross-examination outcome
- Business rule consistency
- Contradictory evidence weight

## Secondary Drivers

Where a second hypothesis retains meaningful support, it is recorded as a **secondary driver** on the Root Cause entity. Secondary driver is **not** a hypothesis state — the four states remain Accepted, Rejected, Suppressed, NotApplicable.

## Inconclusive

Where no hypothesis achieves defensible support, `Case_Status = Inconclusive` and **no root cause is assigned**. This is a correct outcome.

## Recommendations

Maximum three, each referencing its root cause and evidence, prioritised per `BR-702`, with qualitative impact per `BR-704`. All route to the Demand / Forecast Team.

---

# 23. Step 14 — Generate Executive Summary

Produced by the LLM — **the only stage where an LLM is invoked.**

| Requirement | Detail |
|---|---|
| Format | Bullet points |
| Language | Plain, simple, concise, executive-ready |
| Prohibited | Statistical notation, metric names, technical terms |
| Traceability | Every claim traceable to a supplied evidence item |
| Length | **No word or sentence limit.** Quality governed by the above |

The narrative engine writes; it does not analyse, decide, select or infer. It cannot introduce a fact absent from its inputs, alter a conclusion, or omit supplied contradictory evidence or callouts.

Where the LLM fails or times out, the RCA completes **without** a narrative and is marked `Incomplete`. All structured output remains available.

---

# 24. Step 15 — Persist Audit Trail

Every RCA shall be reproducible from its audit record alone, including: input fingerprint, business rules version, weights version, hypothesis catalogue version, question catalogue version, prompt version, model version and seed.

Audit information shall never be deleted.

---

# 25. Decision Card Contents

The Decision Card is specified in `FC_RCA_Output_and_Decision_Cards.md`, which **owns** it. This section is descriptive only.

Header: adherence (signed) · direction · absolute variance · forecast and actual · grain · period · volume band · markers · Timeline where partial.

Body: executive summary · root cause · confidence with full decomposition · evidence summary · hypothesis comparison across four states · recommendations · limitations · audit reference.

---

# 26. Failure Modes

| Failure | Severity | Prevented by |
|---|---|---|
| **Incorrect with high confidence** | **Critical** | Evidence hierarchy · cross-examination · caps · `BR-118` ceiling · three-tier warranty validation |
| Correlation presented as cause | High | Recursive reasoning requirement |
| Confident conclusion on invalid data | High | `BR-112` Tier C suppression |
| Confidence inflated by weak precedent | High | `BR-118` provenance ceiling |
| Suppressed hypothesis read as rejected | High | Four distinct states, visually enforced |
| Partial period read as complete | High | Timeline callout · coverage caps |
| Non-terminating investigation | Medium | `BR-117` bounded loop |
| Inconclusive treated as failure | Medium | `BR-306` |

## The primary failure mode

**Incorrect with high confidence** is the failure this methodology exists to prevent. It arises when multiple methods agree because they share a corrupted input — which is why warranty structure validation, driver relevance gating and the provenance ceiling all exist.

---

# 27. Cognitive Biases Guarded Against

| Bias | Guard |
|---|---|
| **Confirmation bias** | Contradictory evidence collected as a separate mandatory step |
| **Availability bias** | No-precedent scores neutral (0.50), not low. `BR-118` prevents citation amplification |
| **Anchoring** | Hypotheses generated from a fixed catalogue, not from the first plausible explanation |
| **Narrative fallacy** | LLM cannot generate hypotheses or conclusions |
| **Survivorship** | Not-generated and suppressed hypotheses recorded, never omitted |
| **Automation bias** | Confidence decomposition always visible; limitations never collapsed |

---

# 28. Quality Gates

An RCA shall not be published unless:

1. Every claim traces to recorded evidence
2. Confidence is decomposable to eight dimensions
3. Cross-examination has terminated under a recorded condition
4. All four hypothesis states are recorded with reasons
5. Data availability callouts are present where applicable
6. Timeline callout is present where the period is partial
7. The audit record is complete

Failure of any gate results in `Incomplete` or `Failed`, never silent publication.

---

# 29. Guiding Principles

- Never stop at the first plausible explanation
- Statistics support reasoning; they do not replace it
- Contradiction is sought, not tolerated
- Every loop terminates, and its terminating condition is recorded
- Confidence never rises because evidence was lost
- Confidence never rises because a weaker conclusion was cited
- **Unknown** is preferable to **wrong with high confidence**

---

# End of Document
