# FC_RCA_Explainability_Framework

**Project:** Forecast RCA Studio (FC_RCA)
**Document Type:** Explainability Framework
**Version:** 2.0.0
**Supersedes:** Version 1.0.0
**Status:** Approved for Development
**Last Updated:** 30 July 2026

---

## Document Control

| Item | Detail |
|---|---|
| **Purpose** | Define how every conclusion, statistic and confidence score is explained, and to whom. |
| **Scope** | Explainability for Phase 1. |
| **Version basis** | Incorporates P1–P10. Confidence disclosure exempted from progressive disclosure. Four hypothesis states made visually distinct. Trigger narrative corrected. |
| **Dependencies** | `FC_RCA_Business_Rules.md` v2.0 · `FC_RCA_Output_and_Decision_Cards.md` v2.0 |
| **Acceptance Criteria** | (1) No confidence figure appears without its basis. (2) Not Applicable and unavailable read differently. (3) Suppressed and rejected are visually distinct. |
| **Owner** | Product Owner, FC_RCA |
| **Approver** | Pending |

---

# 1. Purpose

An unexplained conclusion is not usable, however correct it is.

This document defines what must be explained, to whom, in what language, and what may never be hidden.

---

# 2. Principles

| # | Principle |
|---|---|
| 1 | Every statistic, recommendation, confidence score and root cause is explainable |
| 2 | Business language by default; technical detail on demand |
| 3 | **Confidence and its basis are never hidden** |
| 4 | Contradictory evidence is always displayed |
| 5 | A suppressed analysis is not an analysis that found nothing |
| 6 | **Not applicable** and **unavailable** mean opposite things and must read differently |
| 7 | The explanation never influences the investigation |

---

# 3. What Must Be Explainable

For any element the user asks about, the system shall provide:

| Item |
|---|
| Definition |
| Formula |
| Why it was selected |
| Inputs used |
| Calculation |
| Interpretation |
| Business impact |
| Contribution to the RCA |
| Assumptions |
| Limitations |

**Never present unexplained statistical output.**

---

# 4. Three Information Layers

| Layer | Audience | Content |
|---|---|---|
| **Executive View** | Executive, Ops Manager | Summary · root cause · confidence with decomposition · recommendations · business impact · callouts |
| **Analyst View** | Forecast Analyst | Full investigation · evidence · hypothesis comparison · root cause tree · evidence timeline · cross-grain view · annotations |
| **Technical View** | Data Scientist | Statistical detail · SHAP · feature attribution · residuals · method parameters |

---

# 5. Progressive Disclosure

**Simple by default. Detailed on demand.**

Technical metrics — SHAP, WAPE, MAPE, RMSE, CoV, Correlation, Drift, Momentum, Feature Importance — appear only when the user expands Technical View (`BR-405`).

## THE EXCEPTION — mandatory

> **The Confidence level, its dimension decomposition and any binding cap are NOT technical detail and shall ALWAYS be visible.**
>
> **Progressive disclosure does not apply to them.**

### Why this is a correctness requirement

Where a prominent number and a hidden caveat disagree, **readers act on the number.**

A confidence level displayed in large type at the top of a Decision Card, with *"3 of 8 dimensions unavailable"* behind an expander, is **misleading by construction**. The caveat exists precisely because the number alone is insufficient.

This is stated as an explicit exception inside `BR-405` so the two rules cannot drift apart.

---

# 6. Explanation Structure

Every explanation follows the same shape:

```
1  What happened
2  What the deviation was — signed, with direction and magnitude in contacts
3  What was considered
4  What the evidence showed
5  What contradicted it
6  What could not be assessed, and whether that matters
7  What was concluded
8  How confident, and why
9  What would change the assessment
```

Step 6 is frequently the most useful and is the one most often omitted in conventional analysis.

---

# 7. Explaining the Deviation

## What must be stated

| Item | Example |
|---|---|
| Adherence | −18.4% |
| **Direction in business language** | **"Under-forecast"** — never "negative adherence" |
| Absolute magnitude | 184 contacts |
| Forecast and actual | 1,000 → 1,184 |
| Grain and period | Weekly, FY27 FW18 |
| Volume band context | 501–1000, so 184 contacts is material |

## Example

> *"Forecast Adherence for FY27 FW18 was −18.4%. Actual offered volume of 1,184 exceeded the forecast of 1,000 by 184 contacts — an under-forecast. This deviation exceeds the ±5% RCA Generation Threshold, so an RCA was produced."*

## Correction from Version 1.0.0

Version 1.0.0 required every RCA to explain: *"Why did the RCA trigger? — The observed forecast variance exceeded the configured investigation threshold."*

**Under the ratified model that narrative is factually wrong.** There is no "configured investigation threshold" — generation is fixed at ±5%, and the configurable threshold is a **display filter** that plays no part in the investigation.

Leaving it in place would have the engine tell every user that a presentation control caused the analysis.

**The explanation shall state the deviation, its direction and its absolute magnitude. It shall not reference the user's display filter selection.**

---

# 8. Explaining Business Rules

Where a business rule influenced the investigation, it shall be named with its effect.

## Examples

> *"Forecast Adherence of −18.4% exceeded the ±5% RCA Generation Threshold (BR-001), so this investigation was produced."*

> *"Warranty data for this period failed structural validation (BR-112 Tier C): Final_Y3 exceeds Final_Y2, which is not possible. The Warranty Mix hypothesis was suppressed."*

> *"Shipment volume was not evaluated for this queue: its correlation with demand is 0.08 over 235 weeks, below the 0.3 relevance threshold (BR-121). This is not a data gap — the driver does not track demand for this queue."*

The third example illustrates the wording distinction in §11.

---

# 9. Explaining Statistical Output

## Requirement

Every statistical result is translated into business language. The raw value remains available in Technical View.

## SHAP translation

Instead of displaying:

```
Feature:  Warranty_1Y_share (exclusive band)
SHAP   =  +0.84
```

Display:

> *"The share of shipments covered by 1-year warranty only rose from 31% to 38% of total shipments. Shorter coverage brings customers into contact sooner after purchase, and this was the largest single contributor to the increase in contact demand during the investigation period."*

## Requirements for warranty explanations

| # | Requirement |
|---|---|
| 1 | Name the **specific exclusive band**, not "Warranty Mix" generically |
| 2 | State the direction and magnitude of the shift in percentage points |
| 3 | State the denominator — share of `Final_Units` (total shipments) |
| 4 | Explain the causal mechanism in business terms |
| 5 | Where `BR-112` Tier is **B**, state that totals were reconciled |
| 6 | Where Tier is **C**, produce **no** warranty explanation. Display: *"Warranty data unavailable for this period — source structure invalid"* |

## Lag disclosure

Where a flow driver was lagged, the **empirically selected lag** shall be stated:

> *"Shipment volume was tested with a 6-week lag, selected as the strongest correlation for this queue (r = 0.41 over 235 weeks)."*

A lag applied without disclosure is not explainable.

---

# 10. Driver Ranking

## Requirements

| # | Requirement |
|---|---|
| 1 | Each driver states whether it is a **stock** or a **flow** measure |
| 2 | Flow drivers state the lag applied |
| 3 | Warranty drivers name the **specific exclusive band** |
| 4 | Drivers unavailable due to Tier C are listed as **"Not evaluated — data unavailable"**, never silently omitted |
| 5 | Drivers excluded by relevance are listed as **"Not evaluated — driver not relevant to this queue"** with the measured correlation |

## Example

```
MOST INFLUENTIAL DRIVERS

1.  Active Serviceable Units — installed base growth
    Stock measure, same period, r = 0.44

2.  1-year-only warranty share — shipment coverage mix
    Flow measure, 6-week lag, r = 0.41

NOT EVALUATED

    Shipment volume       Not relevant to this queue — correlation 0.08
                          over 235 weeks, below the 0.3 threshold
```

Omitting an unevaluated driver would imply it was tested and found uninfluential. **That is a different statement.**

---

# 11. Explaining Availability — the critical distinction

Three states, and two of them read similarly while meaning opposite things.

| State | Wording | Confidence effect |
|---|---|---|
| **Available** | Score shown | Scored |
| **Missing** | *"Unavailable — [reason]"* | **Penalty** |
| **Not Applicable** | *"Not relevant to this queue — [reason]"* | **No penalty** |

## Required wording

**Not Applicable**

> *"This queue carries no warranty exposure, so warranty data is not relevant to it. Confidence is unaffected."*

**Missing**

> *"Warranty data is unavailable and IS relevant to this queue. Confidence is reduced."*

**These read similarly and mean opposite things. The distinction shall never be left to inference.**

---

# 12. Explaining Confidence

## Required structure

| # | Element |
|---|---|
| 1 | The level |
| 2 | What supports it |
| 3 | What limits it |
| 4 | What was not assessable, and whether that matters |
| 5 | What would change it |

## Example

> **Confidence: Medium**
>
> *This conclusion is well supported by the available evidence. Four of five statistical measures point to the same driver, and the finding is consistent with a similar period last year.*
>
> *Confidence is limited to Medium because warranty coverage data for this period is structurally invalid, and warranty mix is normally the primary demand driver for Basic-offering queues. The analysis therefore rests on installed base and calendar effects alone.*
>
> *Confidence would rise to High if warranty data for FY27 FW18 were corrected at source.*

## Requirements

| # | Requirement |
|---|---|
| 1 | Explain the **cap**, not only the score. *"Capped at Medium because X"* is more informative than *"Medium"* |
| 2 | State the **gate**, the **threshold crossed** and the **actual figure** |
| 3 | **State what would change the assessment.** A confidence figure with no path to improvement is not actionable |
| 4 | Distinguish Not Applicable from Missing explicitly, per §11 |
| 5 | Never present confidence as a bare number or level. It is a claim about evidence and shall be explained as one |

## Confidence dimensions — eight

| Dimension | Weight |
|---|---|
| Contradictory Evidence | 0.20 |
| Evidence Strength | 0.18 |
| Business Rule Validation | 0.15 |
| Statistical Agreement | 0.14 |
| Data Sufficiency | 0.12 |
| Context Completeness | 0.10 |
| Historical Consistency | 0.06 |
| Model Agreement | 0.05 |

## Confidence levels — five

**Very High · High · Medium · Low · Very Low**

Version 1.0.0 of the PRD specified three; five is canonical.

---

# 13. Explaining Hypotheses — four distinct states

| State | Meaning | Confidence effect |
|---|---|---|
| **ACCEPTED** | Tested, supported, selected | — |
| **REJECTED** | Tested, evidence did not support it | None |
| **SUPPRESSED** | **Could not be tested** — data invalid or unavailable | **Penalty applies** |
| **NOT APPLICABLE** | Never relevant to this queue | **No penalty** |

## Why this is a correctness requirement, not a preference

If **Suppressed** and **Rejected** look the same, a reader concludes *"warranty was ruled out"* when the truth is *"warranty could not be checked."*

**Those support opposite actions** — one closes the question, the other escalates a data problem.

## Measured relevance

| Measure | Value |
|---|---|
| Basic-offering queue-weeks at Tier C | **32%** |
| Queues where warranty tracks demand | **18%** |

**Both Suppressed and Not Applicable are common states, not edge cases.**

## Display requirements

| # | Requirement |
|---|---|
| 1 | The four states shall be **visually distinct** and shall not share a presentation |
| 2 | A **reason is mandatory** for Rejected, Suppressed and Not Applicable |
| 3 | Ordering — Accepted, then Rejected by evidence strength, then Suppressed, then Not Applicable collapsed with a count |
| 4 | Not Applicable is collapsed but **never omitted.** Omitting it would imply the hypothesis was tested |
| 5 | Every hypothesis considered appears in the report. **No investigated hypothesis shall disappear** |

## Removed

`Secondary Driver` as a hypothesis state. Secondary driver is an orthogonal concept recorded on the Root Cause entity — a hypothesis can be Accepted *and* a secondary driver.

---

# 14. Explaining Suppressed Analysis

Where analysis was suppressed for insufficient data, say so explicitly:

> *"Within-period trend analysis was not performed — it requires at least three weeks of actuals and one is available."*

**A suppressed analysis shall never be silently omitted.** Omission implies the analysis ran and found nothing, which is a materially different statement.

---

# 15. Partial-Period Disclosure

Where an RCA is produced from an incomplete fiscal period, the limitation shall be disclosed in the **Executive Summary itself**, not only in technical detail.

## Required statement

Example — Monthly, 1 of 4 weeks:

> *"This analysis covers FW18 only — the first of four fiscal weeks in FY27 M05. Actuals for FW19 to FW21 are not yet available. The conclusion reflects one week of demand and may change materially as the month completes. Confidence has been capped at Low because coverage is below 25%."*

## Requirements

| # | Requirement |
|---|---|
| 1 | State which weeks **are** covered, not only that the period is partial |
| 2 | State which weeks are missing |
| 3 | State that the conclusion **may change** |
| 4 | State that confidence was capped, and by which gate |
| 5 | Use business language. *"Coverage ratio 0.25"* is not a disclosure |

## Prohibition

A partial-period RCA shall **not**:

- be described as a conclusion about the full period
- present a projected or extrapolated full-period figure
- **be compared against a COMPLETE prior period without stating the asymmetry**

The third is the most common error. Comparing a 1-of-4-week month against last year's complete month is not a comparison; it is a category error.

---

# 16. Explaining Holiday-Anchored Comparison

Where a moving holiday is present, the comparison basis shall be stated.

## Example

> *"This period contains Diwali, which fell on Sunday 8 November 2026 — FY27 FW41. In FY26 Diwali fell on Monday 20 October 2025 — FW38, three fiscal weeks earlier. The comparison is therefore anchored on the holiday rather than the fiscal week. FY26 FW41 contained no holiday and would not have been a valid comparison."*

## Requirements

| # | Requirement |
|---|---|
| 1 | Name the holiday and its date in both periods |
| 2 | State the fiscal week in both periods |
| 3 | State the day of week in both, where they differ |
| 4 | State which anchoring mode was used and why |
| 5 | Where both modes disagree, **report both** — the difference is itself the finding |

---

# 17. Explaining Precedent

Where a historical precedent contributed, it shall be identified with its own confidence.

> *"A similar deviation occurred in FY26 FW18 on this queue, concluding the same root cause at High confidence. That precedent contributed to Historical Consistency at a weight of 0.80, reflecting its own confidence level."*

**Requirement** — the precedent's own confidence shall be stated. A reader must be able to see that a conclusion rests partly on an earlier conclusion, and how strong that earlier one was.

Ineligible precedents, where surfaced to an analyst, are **clearly marked non-evidential**.

---

# 18. Explaining Annotations

A retrieved analyst annotation appears as **normal narrative content** — not as a system citation, not in a separate evidence box.

Adjacent to it, a **provenance control** reveals:

| Field | Content |
|---|---|
| Source | RCA and period it was recorded against |
| Author | Name and date recorded |
| **Why** | Reason it was retrieved for this investigation |
| **Impact** | Which hypothesis it supports, which confidence dimension it contributed to |

All four are required. **"Why" and "Impact" are the reason the control exists** — a reader must be able to see why a human observation was considered relevant and what it changed.

---

# 19. Root Cause Tree

## Purpose

Show the recursive reasoning chain from deviation to root cause, so a reader can follow each *why* and see the evidence at every level.

## Structure

```
Level 0   The deviation
            "Adherence −18.4%, 184 contacts under-forecast"
   │
Level 1   Accepted hypothesis
            "Warranty coverage mix shifted"
   │
Level 2   Why
            "1-year-only share rose 31% → 38% of shipments"
   │
Level 3   Why
            "A 12,000-unit shipment cohort carried reduced coverage"
   │
ROOT      Terminating cause
```

## Node content

| Field | Required |
|---|---|
| Statement — business language, no metric names | Yes |
| Evidence count, with expandable detail | Yes |
| Confidence at that reasoning level | Yes |
| Validation status — Validated / Partial / Unvalidated | Yes |
| Termination reason | Final node only |

## Sibling branches

**Rejected and suppressed hypotheses appear as sibling branches at Level 1**, visually distinct and collapsed by default. A reader must be able to see what else was considered.

## Depth

All recursive levels shown. Levels beyond 3 collapsed by default with a count — *"2 further levels"*. Depth cap per `MBS §13`.

## Constraint

The tree **renders** the stored reasoning chain. It performs no calculation and never re-derives a node.

---

# 20. Evidence Timeline

## Purpose

Place evidence in time so a reader can see what preceded the deviation and in what order.

## Tracks

| Track | Content |
|---|---|
| Adherence | Signed value per week across the window |
| Drivers | One lane per relevant driver, **with the lag applied** |
| Events | Business events within their impact windows |
| Holidays | Holidays within their impact windows |
| Data quality | Weeks flagged, zero-filled, non-computable or inactive |
| Baseline | The comparison period used, marked distinctly |

## Marker requirements

| Marker | Must show |
|---|---|
| Driver observation | Value, and lag applied if non-zero |
| Event | Name, and impact window extent |
| Holiday | Name, day of week, impact window |
| Data flag | Reason — blank, zero-filled, Tier C, inactive |
| Baseline | Which mode — calendar-anchored or holiday-anchored |

Where holiday-anchored comparison applies, the timeline shows **both** the same-fiscal-week period and the holiday-matched period, so the reader can see why they differ.

## Constraint

Renders stored evidence only. No calculation.

---

# 21. Cross-Grain Explanation

Where a queue holds investigations at more than one grain for overlapping time, they are presented side by side **as context, not reconciliation**.

```
Nordic Client DSP
Weekly    FW18  −18.4%  Under-forecast  184 contacts  High
Monthly   M05    −4.2%  Under-forecast   62 contacts  Medium  Timeline: FW18
Quarterly Q2     −2.1%  Under-forecast   95 contacts  Medium  Timeline: FW18
```

## Constraint — mandatory

Grains are **independent investigations**. Divergence is expected and diagnostically meaningful — offsetting weekly errors produce a materially smaller monthly deviation, which is itself a finding.

The explanation shall **not**:

- reconcile the figures
- present one grain's root cause as another's
- imply that disagreement is an error

Where grains reach different root causes, both are shown with a note that they rest on **different evidence over different periods**.

---

# 22. Aggregate View Explanation

Where an aggregate figure is presented, the offset ratio shall be explained.

## Example — high offset

> *"Pooled adherence for this group is +0.3%, which appears close to perfect. However, its ten child queues produced 6,528 contacts of forecast error in total — seven over-forecasting and three under-forecasting, almost exactly cancelling. The pooled figure is not a meaningful measure of forecast quality for this group. Investigate the child queues individually."*

## Example — low offset

> *"Pooled adherence for this group is +36.4%, and only 1.0% of the gross error cancels — all five child queues over-forecast in the same direction. This pattern indicates a systemic cause affecting the whole group rather than five unrelated queue-level issues."*

**The offset ratio distinguishes a systemic problem from a portfolio of unrelated errors, and that distinction shall be stated in words, not left to a number.**

---

# 23. Business Language Requirements

| Prohibited | Required instead |
|---|---|
| "negative adherence" | "under-forecast" |
| "positive adherence" | "over-forecast" |
| "coefficient of variation 0.42" | "demand for this queue is highly variable" |
| "SHAP +0.84" | "the largest single contributor" |
| "p < 0.05" | "statistically significant" |
| "Tier C" *(alone)* | "warranty data is structurally invalid for this period" |
| "coverage ratio 0.25" | "1 of 4 fiscal weeks has actuals" |
| "Gate 3b applied" *(alone)* | "confidence capped at Low because coverage is below 25%" |

Rule identifiers may accompany a plain-language statement, never replace one.

---

# 24. Explainability and the Investigation

**The explanation shall never influence the investigation itself.**

Explanation is produced from a completed investigation. It cannot alter a root cause, confidence level, evidence set or recommendation.

Under the ratified LLM boundary this is guaranteed structurally: the narrative engine is invoked after all findings are fixed, and any output introducing a fact absent from its inputs is rejected.

---

# 25. Quality Gates

An explanation shall not be published unless:

| # | Gate |
|---|---|
| 1 | Every claim traces to a recorded evidence item |
| 2 | Confidence is stated with its full decomposition |
| 3 | Any binding cap is stated with gate, threshold and actual figure |
| 4 | All four hypothesis states are present with reasons |
| 5 | Not Applicable and unavailable are worded distinctly |
| 6 | Suppressed analyses are named with reasons |
| 7 | Partial periods carry the Timeline callout and the disclosure statement |
| 8 | Contradictory evidence is displayed |
| 9 | No statistical value appears without an interpretation |

---

# 26. Future Explainability Enhancements

FUTURE SCOPE:

- Semantic similarity explanation for retrieved precedents
- Quantified weekday / weekend impact attribution
- Interactive what-if exploration
- Natural language question answering over an investigation
- Automated event correlation narrative

---

# 27. Guiding Principles

- An unexplained conclusion is not usable
- Confidence and its basis are never hidden
- Not applicable and unavailable mean opposite things
- A suppressed analysis is not an analysis that found nothing
- Omitting an unevaluated driver implies it was evaluated
- Every explanation says what would change the assessment
- The explanation never influences the investigation

---

# End of Document
