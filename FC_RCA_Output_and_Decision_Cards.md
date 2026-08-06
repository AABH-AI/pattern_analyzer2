# FC_RCA_Output_and_Decision_Cards

**Project:** Forecast RCA Studio (FC_RCA)
**Document Type:** Output Specification
**Version:** 2.0.0
**Supersedes:** Version 1.0.0
**Status:** Approved for Development
**Last Updated:** 30 July 2026

---

## Document Control

| Item | Detail |
|---|---|
| **Purpose** | Define every output the system produces, its mandatory content, and its publication gates. |
| **Scope** | Phase 1 outputs. |
| **Authority** | **This document owns the Decision Card specification.** All other documents cross-reference it. |
| **Version basis** | Incorporates P1–P10. |
| **Dependencies** | `FC_RCA_Business_Rules.md` v2.0 · `FC_RCA_Explainability_Framework.md` v2.0 |
| **Acceptance Criteria** | (1) No Decision Card published without full confidence decomposition. (2) Four hypothesis states visually distinct. (3) Partial periods always carry the Timeline callout. |
| **Owner** | Product Owner, FC_RCA |
| **Approver** | Pending |

---

# 1. Purpose

This document defines what the system shows, and what it must never hide.

## Ownership

Version 1.0.0 of the baseline specified the Decision Card in **five** documents with five different content lists. **This document is now the single owner.** `PRD`, `RCA_Methodology`, `Explainability_Framework` and `Data_Dictionary` cross-reference it and do not restate it.

---

# 2. Output Inventory

| # | Output | Audience |
|---|---|---|
| 1 | **Executive Decision Card** | All |
| 2 | Confidence Panel | All |
| 3 | Aggregate view rows — Levels 1 and 2 | All |
| 4 | Queue worklist rows — Level 3 | All |
| 5 | Root Cause Report | Analyst |
| 6 | Evidence Summary | Analyst |
| 7 | Hypothesis Comparison | Analyst |
| 8 | Root Cause Tree | Analyst |
| 9 | Evidence Timeline | Analyst |
| 10 | Cross-Examination Report | Analyst |
| 11 | Cross-Grain View | Analyst |
| 12 | Recommendations | All |
| 13 | Statistical Summary | Data Scientist |
| 14 | Technical Diagnostics | Data Scientist |
| 15 | Audit Report | Administrator |
| 16 | Case History | Analyst |

---

# 3. Executive Decision Card

The primary artifact. Everything else supports it.

## 3.1 Mandatory Header

| Field | Example | Notes |
|---|---|---|
| **Forecast Adherence** | **−18.4%** | **Signed. Never absolute** |
| **Direction** | **Under-forecast** | Business language, derived from sign |
| **Absolute Variance** | **184 contacts** | `ABS(Actual_Offered − fcst_offered)` |
| Forecast / Actual | 1,000 / 1,184 | Both values shown |
| Grain | Weekly | Weekly · Monthly · Quarterly |
| Period | FY27 FW18 | |
| Volume Band | 501–1000 | Basis window on hover |
| Confidence | Medium | With decomposition — §4 |

**Direction shall be stated in business language.** *"Under-forecast"* and *"Over-forecast"* are the required terms. *"Negative adherence"* is not.

## 3.2 Conditional Header Markers

| Condition | Marker |
|---|---|
| `ABS(adherence) > 75%` **and** materiality floor met | **"Major Deviation"** |
| Generated below threshold | "Manually Requested — below generation threshold" |
| Partial period | **"Timeline: FWxx"** |
| Recomputed with more weeks | "Superseded" |
| Timed out or narrative failed | **"Investigation Incomplete"** |
| Re-run without data change | **"Governance Exception"** |

## 3.3 Mandatory Body Sections

| # | Section | Content |
|---|---|---|
| 1 | Executive Summary | Bullet points, business language |
| 2 | Root Cause | Statement, or `Inconclusive` with reason |
| 3 | **Confidence** | Level **plus full decomposition** — §4 |
| 4 | Business Impact | Deviation magnitude and direction in contacts |
| 5 | Evidence Summary | Supporting and contradictory |
| 6 | Hypothesis Comparison | **Four distinct states** — §5 |
| 7 | Recommendations | Maximum 3, with priority and qualitative impact |
| 8 | Limitations | What could not be assessed and why |
| 9 | Data Availability Callout | §6 |
| 10 | Audit Reference | Reproducibility identifier |

## 3.4 Versioning

Decision Cards are **versioned, never overwritten**. Where a monthly or quarterly RCA is recomputed as actuals arrive, a new card version is created and the prior version retained.

Case History exposes all versions with the weeks added at each recomputation.

---

# 4. Confidence Panel

## 4.1 Visibility — mandatory

> **ALWAYS VISIBLE. Never collapsed, never behind an expander.**
>
> This is an explicit exception to `BR-405` progressive disclosure, stated in that rule.

### Why

Where a prominent number and a hidden caveat disagree, **readers act on the number.** A confidence level whose limitations are collapsed by default is misleading by construction.

## 4.2 Required Content

| Element | Always shown |
|---|---|
| Final level | Yes |
| Calculated level | Where a cap binds |
| Binding cap, with gate, threshold and actual figure | Where a cap binds |
| **All eight dimensions** | Yes — with availability state and score |
| Reason per dimension | Where Missing or Not Applicable |
| Limitations | Yes |
| What would change it | Yes |

## 4.3 Required Format

```
┌──────────────────────────────────────────────────────────────┐
│  CONFIDENCE: MEDIUM                                          │
│                                                              │
│  Calculated: High (0.80)                                     │
│  Capped at Medium — expected primary driver unavailable       │
│  Gate 4 · warranty is the primary driver for Basic offering    │
│                                                              │
│  Dimension                    Availability      Score        │
│  Contradictory Evidence       Available          0.90        │
│  Evidence Strength            Available          0.55        │
│  Business Rule Validation     Available          1.00        │
│  Statistical Agreement        Available          0.80        │
│  Data Sufficiency             Available          1.00        │
│  Context Completeness         Available          0.83        │
│  Historical Consistency       Available          0.50        │
│  Model Agreement              Available          0.50        │
│                                                              │
│  Limitations                                                 │
│  • Warranty data invalid (BR-112 Tier C) — the expected      │
│    primary driver for Basic offering could not be evaluated   │
│                                                              │
│  Would rise to High if warranty data were corrected at source │
└──────────────────────────────────────────────────────────────┘
```

## 4.4 Availability Wording — mandatory distinction

| State | Wording | Penalty |
|---|---|---|
| Available | Score shown | Scored |
| **Missing** | *"Unavailable — [reason]"* | **Yes** |
| **Not Applicable** | *"Not relevant to this queue — [reason]"* | **No** |

**These must read differently.** *"Warranty data not relevant to this queue"* and *"warranty data unavailable"* mean opposite things. A reader shall never have to infer which applies.

## 4.5 Prohibitions

A Decision Card shall **not**:

- present a capped level as though it were the calculated level
- omit dimensions that were Missing
- describe a Not Applicable dimension as a limitation
- display a confidence level that cannot be decomposed
- display a capped level without the gate, threshold and actual figure

---

# 5. Hypothesis Comparison

## 5.1 Four distinct states — mandatory

| State | Meaning | Confidence effect |
|---|---|---|
| **ACCEPTED** | Tested, supported, selected | — |
| **REJECTED** | Tested, evidence did not support it | None |
| **SUPPRESSED** | **Could not be tested** — data invalid or unavailable | Penalty applies |
| **NOT APPLICABLE** | Never relevant to this queue | No penalty |

**These four must be visually distinct and must not share a presentation.**

## 5.2 Why this is a correctness requirement

If Suppressed and Rejected look the same, a reader concludes *"warranty was ruled out"* when the truth is *"warranty could not be checked."* **Those support opposite actions** — one closes the question, the other escalates a data problem.

Measured: **32% of Basic-offering queue-weeks are Tier C**, and warranty tracks demand in only **18% of queues**. Both states are common, not edge cases.

## 5.3 Required content

| Field | Notes |
|---|---|
| Hypothesis | Name and category |
| State | One of the four |
| **Reason** | **Mandatory** for Rejected, Suppressed and Not Applicable |
| Evidence | Supporting and contradictory counts, expandable |
| Evidence strength | Five-level scale |
| Confidence | At hypothesis level |

## 5.4 Ordering

Accepted first. Then Rejected by evidence strength. Then Suppressed. Then Not Applicable, collapsed by default with a count.

**Not Applicable is collapsed but never omitted.** Omitting it would imply the hypothesis was tested.

## 5.5 Suggested layout

```
HYPOTHESES CONSIDERED — 22 total

  ACCEPTED     1
    Warranty coverage mix shift        Strong      High

  REJECTED     5
    Demand spike                       Moderate    Low
    Holiday impact                     Weak        Very Low
    ...

  SUPPRESSED   2
    Installed base change     ASU unavailable for this period (data lag)
    Seasonality               Requires 104 weeks; queue has 39

  NOT APPLICABLE   6                                    [collapsed]
    Shipment volume change    Correlation 0.08 — below 0.3 threshold
    ...
```

## 5.6 Constraint

**No investigated hypothesis shall disappear from the final report.**

`Secondary Driver` is **not** a state. It is recorded on the Root Cause. A hypothesis can be Accepted *and* a secondary driver.

---

# 6. Callout Components

Six callouts with defined triggers, content and placement.

| Callout | Trigger | Placement |
|---|---|---|
| Timeline | Partial period | Above Executive Summary |
| Data Availability | Any flagged, missing or not-applicable element | Above Executive Summary |
| Major Deviation | `BR-004` conditions met | Header banner |
| Superseded | `Case_Status = Superseded` | Header banner |
| Incomplete | `Case_Status = Incomplete` | Header banner |
| Governance Exception | Re-run without data change | Header banner |

## 6.1 Timeline

```
┌────────────────────────────────────────────────────┐
│  Timeline: FW18                                    │
│  Coverage: 1 of 4 fiscal weeks (25%)               │
│  Missing: FW19, FW20, FW21                         │
│  Confidence capped at Low — coverage below 25%      │
│  (Gate 3b)                                         │
└────────────────────────────────────────────────────┘
```

**Requirements**

| # | Requirement |
|---|---|
| 1 | Timeline shows the **last** fiscal week with actuals |
| 2 | Coverage states weeks used and weeks in period, with percentage |
| 3 | Missing weeks listed explicitly |
| 4 | Weeks excluded under `BR-110` listed **separately** as "Non-computable" — a data defect, not an availability gap |
| 5 | Weeks zero-filled under `BR-122` listed separately |
| 6 | **Complete periods display no Timeline callout.** Its absence signifies completeness and shall not be ambiguous |

## 6.2 Data Availability

Lists each affected element with its reason, distinguishing the three states:

```
Warranty coverage    UNAVAILABLE   Structurally invalid (BR-112 Tier C)
Installed base       NOT RELEVANT  Correlation 0.08, below threshold (BR-121)
Holiday context      NOT RELEVANT  Country is an aggregate value (BR-111)
Business events      NOT RELEVANT  Repository not populated
FW15 actuals         ZERO-FILLED   Interior blank, 2-week run (BR-122)
FW20 actuals         NON-COMPUTABLE  fcst_offered = 0 (BR-110)
```

## 6.3 Incomplete

```
┌────────────────────────────────────────────────────┐
│  INVESTIGATION INCOMPLETE                          │
│  Stages not executed: Cross-Examination, Narrative  │
│  Reason: Time budget exhausted                     │
│  This is a provisional finding.                    │
│  Confidence capped at Low (Gate 7).                │
└────────────────────────────────────────────────────┘
```

**A partial RCA may be published. It must never be mistakable for a complete one.**

## 6.4 Governance Exception

```
┌────────────────────────────────────────────────────┐
│  RE-RUN WITHOUT DATA CHANGE                        │
│  Requested by [name] on 30 Jul 2026                │
│  Reason on record. Flagged for Administrator review.│
└────────────────────────────────────────────────────┘
```

---

# 7. Aggregate View Output — Levels 1 and 2

## 7.1 Mandatory fields

| Field | Notes |
|---|---|
| Group | Region · SubRegion · Country · Offering [· Channel] |
| Pooled adherence | Signed |
| Direction | Under-forecast / Over-forecast / **Offsetting** |
| Net variance | Contacts |
| **Gross variance** | Contacts — **default sort** |
| **Offset ratio** | With SYSTEMIC / MIXED / IDIOSYNCRATIC label |
| Child queues | Count, and how many have an RCA in window |
| Root cause mix | Top 3 by variance contribution |
| Confidence mix | Distribution across children |

## 7.2 Mandatory disclosure

> **A pooled adherence figure shall NEVER be displayed without its offset ratio.**

Measured: **75 of 113 Level 1 groups** contain queues erring in both directions. Median cancellation **36.4%**. Fifteen groups cancel more than 70%. One group shows **+0.3% pooled adherence while its children produced 6,528 contacts of error.**

An aggregate figure without its offset ratio understates real forecast error in the majority of groups.

## 7.3 Offsetting presentation

Where the offset ratio exceeds 70%:

- Direction displays **"Offsetting"** rather than a direction
- The pooled adherence figure is **de-emphasised** — it is not meaningful for that group

Single-queue groups display no offset label and are marked as such.

## 7.4 Ranking

**Ranked by gross variance, not adherence percentage.**

Measured: `Americas · NA · United States · Basic` carries the largest absolute error in the business — **72,186 contacts gross** — at −7.1% adherence, and would not appear under a ±10% percentage filter.

## 7.5 No confidence at aggregate level

An aggregate view carries **no confidence score**. It reports the confidence **distribution** of its children. Confidence describes a conclusion, and an aggregate view has none of its own.

---

# 8. Queue Worklist Output — Level 3

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
| Markers | Per §3.2 |

## Display rules

A row appears where **both** hold:

1. `ABS(adherence) >` selected Adherence Display Filter
2. `ABS(Actual_Offered − fcst_offered) >=` Materiality Floor for the queue's Volume Band, **unless** "Include immaterial breaches" is on

Major Deviation rows bypass condition 1, **never condition 2**.

Superseded rows hidden by default. Incomplete rows shown with a marker.

---

# 9. Root Cause Report

| Section |
|---|
| Root cause statement, or `Inconclusive` with reason |
| Reasoning chain — Root Cause Tree |
| Secondary drivers, where present |
| Supporting evidence with strength and source |
| Contradictory evidence — **always displayed** |
| Cross-examination outcome and terminating condition |
| Confidence with full decomposition |
| Assumptions and limitations |

---

# 10. Evidence Summary

Every evidence item with type, source family, supporting flag, strength, independence weight and provenance weight.

**Contradictory evidence shall always be displayed**, whether or not it changed the conclusion.

Where an annotation contributed, it appears as narrative content with a provenance control.

---

# 11. Cross-Examination Report

| Field |
|---|
| Iterations executed, of the maximum |
| Questions asked per iteration, with semantic keys |
| Evidence retrieved, and whether it was new |
| Weaknesses detected |
| **Terminating condition** — 1 to 5 |
| Final outcome |
| Whether Gate 7 applies |

Where the loop terminated by iteration cap or no-new-evidence, the report shall state that the conclusion was **interrupted, not validated**.

---

# 12. Recommendations

| Requirement | Value |
|---|---|
| Maximum per RCA | **3** |
| Scope | **Investigative and business actions only** |
| Priority | Critical · High · Medium · Low, **derived** |
| Impact | **Qualitative only** |
| Routing | **Demand / Forecast Team** |

## Required content per recommendation

- Action statement
- Root cause it addresses
- Evidence reference
- Priority
- Qualitative impact statement

## Prohibitions

Recommendations shall **not**:

- propose forecast values
- state a quantified benefit — no contacts recovered, no cost avoided, no accuracy percentage
- be executed automatically
- name an individual — routing is to a team

## Example

```
RECOMMENDATIONS (2)

1  HIGH — Review warranty mix assumptions with the product team
   Addresses: Warranty coverage mix shift
   Evidence: 1-year-only share rose 31% → 38% of shipments
   Impact: Would reduce recurrence of a −18.4% under-forecast on a
           queue averaging 743 contacts per week

2  MEDIUM — Escalate warranty data quality for Americas Basic queues
   Addresses: Warranty structural validation failures
   Evidence: 32% of Basic queue-weeks fail BR-112 Tier C
   Impact: Would restore the primary demand driver for this segment
```

---

# 13. Statistical Summary and Technical Diagnostics

Collapsed by default per `BR-405`.

Technical metrics: SHAP · WAPE · MAPE · RMSE · CoV · Correlation · Drift · Momentum · Feature Importance.

**Every value carries its interpretation.** No unexplained statistical output appears in the application.

Suppressed metrics appear with `Suppressed` and a reason — never omitted.

**The Confidence Panel is exempt** and remains visible.

---

# 14. Audit Report

Returns the complete reproducibility set: input fingerprint · business rules version · weights version · hypothesis catalogue version · question catalogue version · prompt version · model version · seed · full prompt and response.

Available to Administrators.

---

# 15. Case History

All versions of an RCA with:

- Version number and generation timestamp
- Weeks of actuals available at that version
- Adherence at that version
- Root cause at that version
- Confidence at that version
- Supersession reason

**This is itself evidence** — the sequence of conclusions as a period filled in shows how the picture changed.

---

# 16. Case Status Presentation

| Status | Published | Presentation |
|---|---|---|
| `Queued` | No | — |
| `Running` | No | Progress indicator |
| `Completed` | Yes | Standard |
| `Inconclusive` | Yes | Root cause section states no defensible cause, with reasons |
| **`Incomplete`** | **Yes** | **Banner, stages listed, confidence capped, provisional wording** |
| `Escalated` | Yes | Escalation reason stated |
| `Superseded` | Hidden by default | Reachable via Case History |
| **`Failed`** | **No** | Reason in audit only |

## Removed from Version 1.0.0

| Status | Reason |
|---|---|
| "Awaiting Data" | No RCA exists without actuals, so nothing is ever awaiting |
| "Archived" | Retention concern, not an investigation state |

---

# 17. Export

| Format | Available |
|---|---|
| PDF | Yes |
| Word | Yes |
| Markdown | Yes |
| JSON | Yes |
| CSV | Yes |
| PowerPoint | FUTURE SCOPE |

**An export shall not omit content the Decision Card is required to display** — including the confidence decomposition and all callouts.

---

# 18. Publication Gates

A Decision Card shall **not** be published unless all of the following pass:

| # | Gate |
|---|---|
| 1 | Every claim traces to a recorded evidence item |
| 2 | **Confidence is decomposable to eight dimensions** |
| 3 | Any binding cap states gate, threshold and actual figure |
| 4 | All four hypothesis states are recorded with reasons |
| 5 | Contradictory evidence is present where it exists |
| 6 | Data availability callout present where applicable |
| 7 | Timeline callout present where the period is partial |
| 8 | Cross-examination has terminated under a recorded condition |
| 9 | Recommendations reference their root cause, or none are produced |
| 10 | Audit reference is complete |

Failure of any gate results in `Incomplete` or `Failed` — **never silent publication.**

## Note on recommendations

Version 1.0.0 made *"Recommendations generated"* a publication gate while four scope documents excluded the Recommendation Engine from Phase 1 — meaning no RCA could be published. That contradiction is resolved: recommendations for **investigative and business actions** are in Phase 1 scope, and gate 9 permits an RCA with no recommendations where none is warranted.

---

# 19. Notification

In-application notifications on RCA completion, Major Deviation and Governance Exception.

**Email distribution is deferred to Phase 2.**

---

# 20. Guiding Principles

- The Decision Card is the product. Everything else supports it
- Confidence and its basis are never hidden
- Suppressed, Rejected and Not Applicable are three different findings
- A pooled figure without its offset ratio is misleading
- A partial RCA may be published; it must never look complete
- The absence of a Timeline callout signifies completeness
- No investigated hypothesis disappears
- Direction is stated in business language, never as a sign

---

# End of Document
