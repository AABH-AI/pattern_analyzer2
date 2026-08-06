# FC_RCA_Testing_and_Validation_Strategy

**Project:** Forecast RCA Studio (FC_RCA)
**Document Type:** Testing & Validation Strategy
**Version:** 2.1.0
**Supersedes:** Version 2.0.0
**Status:** Approved for Development
**Last Updated:** 30 July 2026

---

## Document Control

| Item | Detail |
|---|---|
| **Purpose** | Define how the system is validated, with reference test cases carrying measured expected values. |
| **Scope** | Phase 1 testing. |
| **Version basis** | Incorporates P1–P11. Determinism requirement made satisfiable. Reference cases added with values measured against production-representative data. |
| **Dependencies** | All specification documents at v2.0. |
| **Acceptance Criteria** | Every reference case is executable and its expected value is stated numerically. |
| **Owner** | Product Owner, FC_RCA |
| **Approver** | Pending |

---

# 1. Purpose

This document defines what must be proven before the system is trusted.

Every reference case below carries a **measured expected value**, not an illustrative one.

---

# 2. Testing Principles

| # | Principle |
|---|---|
| 1 | Every formula has reference cases with stated expected values |
| 2 | Every threshold has its measured effect asserted |
| 3 | Structured output is tested for **exact** determinism |
| 4 | Narrative output is tested for **fact**, with wording as tolerance |
| 5 | A test that cannot fail is not a test |
| 6 | **Invariants are asserted, not assumed** |

---

# 3. Test Levels

| Level | Coverage target |
|---|---|
| Unit | 90% minimum on calculation and rule modules |
| Integration | Every layer boundary |
| Contract | Every API endpoint |
| End-to-end | Full canonical sequence with order assertion |
| Regression | Reference set on every prompt or weight change |
| UAT | Scenario-based, business-validated |

---

# 4. Components Under Test

| Component |
|---|
| Ingestion and validation |
| Adherence calculation |
| Fiscal calendar derivation |
| Volume band derivation |
| Warranty structure validation and band derivation |
| ASU handling and aggregation |
| Driver relevance gate |
| Hypothesis generation |
| Evidence collection |
| Statistical analytics |
| Recursive reasoning |
| Cross-examination loop |
| Confidence engine |
| Root cause and recommendation engines |
| Narrative engine and prompt contract |
| Analysis hierarchy and aggregate views |
| Re-run governance |
| Audit and reproducibility |

Version 1.0.0 named an "Audit Engine" that does not exist in the architecture. The Audit & Governance **Layer** spans all components.

---

# 5. Determinism and Reproducibility

## 5.1 Structured output — strict determinism

Identical inputs shall produce **identical** structured output:

| Item |
|---|
| Candidate hypothesis set, and the not-generated list with reasons |
| Evidence set |
| Statistical results |
| Cross-examination questions, iterations and terminating condition |
| Confidence score, level, dimension decomposition and binding cap |
| Selected root cause |
| Recommendations |

**Any variation is a defect and shall fail the build.**

This is achievable because hypotheses and questions come from deterministic catalogues rather than an LLM.

> Version 1.0.0 required *"AI reasoning shall be deterministic when identical inputs are supplied"* while assigning hypothesis generation to an LLM — an unachievable combination.

## 5.2 Narrative output — reproducibility with tolerance

Produced by an LLM at temperature 0 with a pinned model and pinned prompt version.

| Assertion | Type |
|---|---|
| Conforms to output schema | **Strict** |
| Contains no numeric value absent from inputs | **Strict** |
| States the same root cause as structured output | **Strict** |
| States the same confidence level | **Strict** |
| Contains every supplied contradictory evidence item | **Strict** |
| Contains every supplied data availability callout | **Strict** |
| Identical wording across runs | **Tolerance — logged, not failed** |

**Wording variation is acceptable. A difference in fact is not.**

---

# 6. Forecast Adherence — Reference Cases

| # | `fcst_offered` | `Actual_Offered` | Expected adherence | Expected direction |
|---|---|---|---|---|
| 1 | 1,000 | 1,000 | **0.0%** | Perfect |
| 2 | 1,000 | 1,120 | **−12.0%** | Under-forecast |
| 3 | 1,000 | 880 | **+12.0%** | Over-forecast |
| 4 | 1,000 | 2,000 | **−100.0%** | Under-forecast |
| 5 | 1,000 | 0 | **+100.0%** | Over-forecast |
| 6 | 0 | 500 | Non-computable | Flagged (`BR-110`) |
| 7 | blank | 500 | Blank | Flagged |
| 8 | 1,000 | blank | Blank | No RCA |

**Sign inversion is a critical defect.** Case 2 returning +12.0% shall fail the build.

## Pooled aggregation

| FW | Forecast | Actual |
|---|---|---|
| 18 | 1,000 | 1,100 |
| 19 | 1,200 | 1,150 |
| 20 | 900 | 1,080 |
| 21 | 1,100 | 1,000 |
| **Total** | **4,200** | **4,330** |

Expected: **−3.1%**. Simple average of weekly values (−4.2%) shall **fail**.

## Pooled with partial coverage

FY27 M05 (FW18–21). Actuals for FW18 and FW19 only.

| Field | Expected |
|---|---|
| Weeks in period | 4 |
| Weeks with actuals | 2 |
| `SUM(fcst_offered)` | **2,200** — FW18+19 only |
| `SUM(Actual_Offered)` | 2,250 |
| Adherence | **−2.3%** |
| Coverage ratio | 0.50 |
| Timeline label | `Timeline: FW19` |
| Confidence cap | Gate 3a → Medium |

Failing results: forecast summed as 4,200 · adherence −7.1% · missing Timeline callout · coverage cap not applied.

---

# 7. Fiscal Calendar — Reference Cases

## 52-week year (FY2027)

| `Fiscal_Week` | Quarter | Month | Calendar |
|---|---|---|---|
| 202701 | Q1 | M01 | Feb |
| 202704 | Q1 | M01 | Feb |
| 202705 | Q1 | M02 | Mar |
| 202709 | Q1 | M03 | Apr |
| 202713 | Q1 | M03 | Apr |
| 202714 | Q2 | M04 | May |
| 202718 | Q2 | M05 | Jun |
| 202726 | Q2 | M06 | Jul |
| 202744 | Q4 | M11 | Dec |
| 202752 | Q4 | M12 | Jan |

## 53-week year (FY2023) — Q4 only

| `Fiscal_Week` | Month | Weeks in month | Calendar |
|---|---|---|---|
| 202340 | M10 | 4 | Nov |
| 202344 | **M11** | **5** | Dec |
| 202348 | **M11** | **5** | Dec |
| 202349 | M12 | 5 | Jan |
| 202353 | M12 | 5 | Feb |

Failing results: 202348 mapped to M12 · 202353 rejected as invalid · 4-4-5 applied to FY2023 Q4 · 4-5-5 applied to a 52-week year.

## Week count derivation

| FY | Weeks present in data | Expected `weeks_in_FY` | Classification |
|---|---|---|---|
| 2022 | FW49–52 only (4) | **52** | 52-week year |
| 2023 | FW01–53 (53) | **53** | 53-week year |
| 2027 | FW01–52 (52) | 52 | 52-week year |
| 2029 | FW01–08 (8) | 8 | In progress |

**FY2022 returning 4 shall fail the build** — `MAX`, not `COUNT(DISTINCT)`.

---

# 8. Volume Band — Reference Cases

Basis FY27 Q1 (FW01–13), metric `Actual_Offered`.

| # | Weekly values | Weeks used | Mean | Expected band |
|---|---|---|---|---|
| 1 | 13 weeks, all = 100 | 13 | 100.0 | `<=100` |
| 2 | 13 weeks, all = 101 | 13 | 101.0 | `101-250` |
| 3 | 13 weeks, all = 250 | 13 | 250.0 | `101-250` |
| 4 | 13 weeks, all = 251 | 13 | 251.0 | `251-500` |
| 5 | 10 weeks = 500, 3 blank | **10** | 500.0 | `251-500` |
| 6 | 10 weeks = 500, 3 weeks = 0 | **13** | **384.6** | `251-500` |
| 7 | All 13 weeks blank | 0 | null | **`Emerging`** |
| 8 | 14 weeks (prior Q4 of 53-week year) | 14 | — | per mean |

Failing results:

- Case 6 computed as 500.0 — **zeros must be included in the denominator**
- Case 5 computed as 384.6 — **blanks must be excluded from the denominator**
- Case 3 assigned `251-500` — boundary 250 belongs to `101-250`
- Case 7 assigned `<=100` — **absence of data is not zero volume**
- Case 8 using 13 weeks where the prior Q4 held 14
- Any recalculation outside FW01/14/27/40
- Any band changing mid-quarter

---

# 9. Warranty Structure — Reference Cases

| # | `Final_Units` | Y1 | Y2 | Y3 | Y4 | Y5 | Expected Tier | Reason |
|---|---|---|---|---|---|---|---|---|
| 1 | 4220 | 4220 | 2623 | 2562 | 1348 | 143 | **A** | Clean |
| 2 | 1454 | 1403 | 915 | 356 | 851 | 938 | **C** | Y3 < Y4 < Y5 inverted |
| 3 | 2689 | 2690 | 1912 | 1832 | 554 | 51 | **B** | Y1 over by 1 (≤ 2 units) |
| 4 | 2500 | 2500 | 1861 | 2708 | 225 | 27 | **C** | Y3 > Y2 inverted |
| 5 | 10000 | 9000 | 5000 | 2000 | 500 | 100 | **A** | 1,000 no-warranty units |
| 6 | 1000 | 1200 | 800 | 400 | 200 | 50 | **C** | Y1 exceeds by 20% |
| 7 | 1000 | 1000 | 1000 | 1000 | 1000 | 1000 | **A** | All units full 5Y |
| 8 | 0 | 0 | 0 | 0 | 0 | 0 | **A** | Zero shipments, valid |

## Exclusive band derivation — case 1

| Band | Expected units | Expected share |
|---|---|---|
| No warranty | 0 | 0.0% |
| 1-year only | 1,597 | 37.8% |
| 2-year only | 61 | 1.4% |
| 3-year only | 1,214 | 28.8% |
| 4-year only | 1,205 | 28.6% |
| 5-year | 143 | 3.4% |
| **Total** | **4,220** | **100.0%** |

Failing results:

- Band sum ≠ `Final_Units`
- Any share computed with `SUM(Y1..Y5)` as denominator — would give **10,896**
- Any share computed with `Final_Y1` as denominator where `Final_Units ≠ Final_Y1`
- Correlation or SHAP executed on raw nested Y-values
- Any warranty output produced for a Tier C row
- Tier C returning an empty object rather than `null`

---

# 10. ASU — Reference Cases

## Aggregation

13 weekly values, all 100,000:

| Aggregation | Expected | Failing result |
|---|---|---|
| Weekly | 100,000 | — |
| Monthly (4 wk) | **100,000** | 400,000 (summed) |
| Quarterly (13 wk) | **100,000** | 1,300,000 (summed) |

Mixed 90,000 / 100,000 / 110,000 / blank across a 4-week month:

| Field | Expected |
|---|---|
| Weeks with values | 3 |
| Monthly ASU | **100,000** — mean of 3 |
| Failing result | 75,000 — blank counted as 0 |
| Failing result | 300,000 — summed |

## Plan variance

| # | `Planned_ASU` | `Actual_ASU` | ASU Adherence | Contact adherence | Expected outcome |
|---|---|---|---|---|---|
| 1 | 100,000 | 120,000 | **−20.0%** | −18% | Generated, direction **coherent** |
| 2 | 100,000 | 80,000 | **+20.0%** | +15% | Generated, direction **coherent** |
| 3 | 100,000 | 120,000 | −20.0% | +15% | Generated, **contradictory evidence recorded** |
| 4 | 100,000 | 105,000 | −5.0% | −18% | Below threshold — no hypothesis |
| 5 | 100,000 | blank | null | −18% | **Suppressed**, reason recorded |
| 6 | blank | 120,000 | null | −18% | **Suppressed**, reason recorded |

## Applicability

| # | Offering | Expected |
|---|---|---|
| 1 | Basic | ASU applicable, warranty applicable |
| 2 | **OOP** | **Both Not Applicable, no confidence penalty** |
| 3 | OOP | Decision Card says *"not applicable"*, **not** *"unavailable"* |
| 4 | Premium | ASU applicable; blank `Actual_ASU` → **Missing**, penalty applies |

Failing results: ASU summed across any period · blank ASU treated as zero in a mean · OOP queue penalised · OOP card describing drivers as "unavailable" · any document referring to ASU as "Average Selling Units".

---

# 11. Driver Relevance Gate — Reference Cases

Measured pass rates on reference data:

| Driver | Queues passing | Share |
|---|---|---|
| `Actual_ASU` | 236 of 427 | **55%** |
| `Final_Units` | 76 of 427 | 18% |
| Warranty band share | 78 of 427 | 18% |
| All three fail | 139 of 427 | **33%** |

| # | Scenario | Expected |
|---|---|---|
| 1 | Driver correlation 0.44, 235 obs | **Relevant** — hypothesis generated |
| 2 | Driver correlation 0.08, 235 obs | **Not Applicable** — no penalty, correlation stated |
| 3 | Driver correlation 0.44, 12 obs | **Not Applicable** — below minimum observations |
| 4 | **Basic offering, shipments pass** | **Shipments used first** — cascade order preserved |
| 5 | **Basic offering, shipments fail, ASU passes** | **Falls through to ASU** — order not reordered |
| 6 | Basic offering, all fail | Falls through to calendar, volume, data quality |

**Case 4 and 5 assert that the gate decides usability, never order.** A build that ranks drivers by average correlation and demotes shipments for Basic queues has failed.

## Lag selection

| # | Scenario | Expected |
|---|---|---|
| 1 | Best correlation at lag 0 | Lag 0 selected and stated |
| 2 | Best correlation at lag 6 | Lag 6 selected and **stated in evidence and narrative** |
| 3 | No lag clears the gate | Driver **Not Applicable** |
| 4 | Any lag applied without disclosure | **FAIL** |

---

# 12. Interior Blank Weeks — Reference Cases

| # | Pattern | Expected |
|---|---|---|
| 1 | Blank before first actual | Pre-launch — excluded |
| 2 | Blank after last actual | Future — excluded |
| 3 | 2 blank weeks between actuals | **Zero-filled**, flagged, adherence +100% |
| 4 | 3 blank weeks between actuals | **Zero-filled**, flagged |
| 5 | **4 blank weeks between actuals** | **Queue inactive** for that span — excluded |
| 6 | 78 blank weeks between actuals | Queue inactive — excluded |

Measured: 550 interior blank weeks across 55 of 427 queues. Median run 3 weeks; maximum 78.

---

# 13. Reserved Literal — Reference Cases

| # | Scenario | Expected |
|---|---|---|
| 1 | SubRegion `NA` read with default settings | **FAIL** — 16,250 rows lose their SubRegion |
| 2 | SubRegion `NA` read with NA-parsing disabled | 16 distinct SubRegions, **zero nulls** |
| 3 | Post-load assertion | `COUNT(SubRegion IS NULL)` = **0** |
| 4 | Input `AMER` | Normalised to `Americas`, **not** a new Region |
| 5 | Input `NorthAm` | Normalised to canonical, same member as `NA` |
| 6 | Genuinely new SubRegion value | Accepted, usable, **flagged** to Administrator |
| 7 | SubRegion with no Region | **Rejected** — orphan |

---

# 13A. Holiday Validation — Reference Cases

## Anchor date basis (`BR-209`)

| # | Scenario | Expected |
|---|---|---|
| 1 | Holiday on Sun `25-DEC-2022`, UK, observed `27-DEC` | **Anchor uses 25-DEC.** Observed date recorded, not used for comparison |
| 2 | Diwali FY27 FW41 vs FY26 | Anchors on the named holiday — **FY26 FW38**, not FW41 |
| 3 | Both modes disagree | **Both reported** |

## Korean alias (`BR-111`)

| # | Scenario | Expected |
|---|---|---|
| 1 | `INPUT_TO_ML` value `korea` | Resolves to holiday master `south korea` |
| 2 | Any variant of Korea | Resolves to `south korea` |
| 3 | **`north-korea`** | **Does NOT resolve. Out of scope** |
| 4 | Korean day-pattern agreement | **>= 95%** |

## Cross-year drift (`BR-126`)

| # | Holiday | Country | Basis | Expected |
|---|---|---|---|---|
| 1 | All Saints' Day `11-JAN` vs `01-NOV` | poland | Gregorian | **FLAGGED** — 10-month drift |
| 2 | Commerce Day `08-FEB` vs `02-AUG` | iceland | Gregorian | **FLAGGED** — 6-month drift |
| 3 | Epiphany `01-JUN` vs `06-JAN` | slovakia | Gregorian | **FLAGGED** — 5-month drift |
| 4 | Diwali, Oct–Nov across years | india | Lunar | **NOT flagged** — exempt |
| 5 | Eid al-Fitr, ~11 days/year drift | uae | Islamic | **NOT flagged** — exempt |
| 6 | Republic Day, 26 Jan every year | india | Gregorian | NOT flagged — no drift |
| 7 | Parliamentary Elections | kuwait | Election-dependent | **NOT flagged** — exempt |
| 8 | Easter Sunday, Mar–Apr across years | germany | Gregorian Easter | NOT flagged — within one month |

## Assertions that shall FAIL the build

- A **same-weekday transposition** passing validation
- A **country blocklist** used for exemption instead of `Calendar_Basis`
- A lunar or Islamic holiday flagged for legitimate drift
- A flagged row **silently deleted** rather than quarantined
- Holiday anchoring using `Observed_Date`
- `korea` failing to resolve
- **`north-korea` resolving to any queue**
- Holiday `Date` stored in any format other than `DD-MMM-YYYY`
- **`INPUT_TO_ML` modified by any process**

## UAT additions

- Sunday holiday with weekend substitution — verify comparison anchors on the **actual** date and the observed date is shown as context
- Korean queue — verify holidays resolve and appear in the RCA
- All Saints Day transposition — verify **FLAGGED**, not silently accepted
- Diwali across three years — verify **NOT flagged** despite month drift
- Eid across six years — verify **NOT flagged** despite 8-week drift
- Flagged drift row — verify **quarantined and surfaced, not deleted**
- Holiday date display — verify `DD-MMM-YYYY` throughout

---

# 14. Confidence Model — Reference Cases

Weights: Contradictory 0.20 · Evidence 0.18 · BusinessRule 0.15 · Statistical 0.14 · DataSufficiency 0.12 · Context 0.10 · Historical 0.06 · ModelAgreement 0.05

## Case A — clean investigation

Scores: 0.90 · 0.85 · 1.00 · 0.80 · 1.00 · 1.00 · 1.00 · 0.75

| Expected | Value |
|---|---|
| Raw score | **0.913** |
| Level | **Very High** |
| Binding cap | null |

## Case B — primary driver Missing

Scores: 0.90 · 0.55 · 1.00 · 0.80 · 1.00 · 0.83 · 0.50 · 0.50

| Expected | Value |
|---|---|
| Raw score | **0.799** — calculated level High |
| Binding cap | **Gate 4** |
| Final level | **Medium** |

## Case C — Not Applicable dimension, renormalised

Warranty element Not Applicable within ContextCompleteness. All other scores as Case A.

| Expected | Value |
|---|---|
| Level | **Very High** |
| Penalty for the Not Applicable element | **None** |

## Case D — Emerging queue, 3 of 13 weeks

HistoricalConsistency and ModelAgreement both Not Applicable. Applicable weight total **0.89**.

Scores: 0.80 · 0.50 · 1.00 · 0.67 · 0.44 · 0.83

| Expected | Value |
|---|---|
| Raw score | **0.708** — 0.630 ÷ 0.89 |
| Caps met | Gate 3b (Low) · Gate 8 (Medium) |
| Binding cap | **Gate 3b — the lowest binds** |
| Final level | **Low** |

## THE INVARIANT TEST — mandatory

For every reference case, compute confidence twice:

```
(i)   with dimension D marked Missing
(ii)  with dimension D excluded and weights renormalised

ASSERT: score(i) <= score(ii)   for every dimension D and every case
```

**A build in which marking a dimension Missing yields HIGHER confidence than excluding it has inverted the availability model and shall FAIL.**

## Failing results

- Any capped score exceeding its raw score
- Missing treated as Not Applicable, or vice versa
- Not Applicable dimension scored 0 rather than excluded
- Case B returning High — cap not applied
- Case D returning Medium — highest rather than lowest cap bound
- Confidence published without full dimension decomposition
- Any confidence value produced by an LLM call
- Identical inputs producing different scores across runs
- Missing `weightsVersion` on a persisted score
- A capped level displayed without gate, threshold and actual figure

---

# 15. Precedent Provenance — Reference Cases

| # | Precedent confidence | Match | Expected `HistoricalConsistency` |
|---|---|---|---|
| 1 | Very High (0.91) | Same cause | **0.91** — 1.00 × 1.00, ceiling 0.91 |
| 2 | High (0.78) | Same cause | **0.78** — 1.00 × 0.80, ceiling 0.78 |
| 3 | Medium (0.62) | Same cause | **0.60** — 1.00 × 0.60 |
| 4 | Medium (0.62) | Related | **0.42** — 0.70 × 0.60 |
| 5 | Low (0.41) | Same cause | **Not eligible** — excluded |
| 6 | Inconclusive | Same cause | **Not eligible** |
| 7 | Superseded | Same cause | **Not eligible** |
| 8 | None found | — | **0.50** — neutral |
| 9 | Emerging queue | — | **Not Applicable** |

## THE LAUNDERING TEST — mandatory

Simulate a three-generation citation chain:

```
Gen 1:  RCA concluding X at Low confidence
Gen 2:  RCA retrieving Gen 1, concluding X
Gen 3:  RCA retrieving Gen 1 and Gen 2, concluding X

ASSERT: Gen 2 does not retrieve Gen 1 (ineligible, Low confidence)
ASSERT: Gen 3 confidence is not higher than with no precedent
ASSERT: for any chain, HistoricalConsistency <= max(precedent confidence scores)
```

**A build in which repeated citation of the same conclusion raises confidence across generations has failed and shall not pass.**

---

# 16. Challenge Loop — Reference Cases

| # | Scenario | Iterations | Terminating condition | Permitted outcome | Gate 7 |
|---|---|---|---|---|---|
| 1 | No weakness on first challenge | 1 | 1 | Accepted | No |
| 2 | Weakness resolved by new evidence, then clean | 2 | 1 | Accepted | No |
| 3 | **Weakness every round, budget exhausted** | **3** | **2** | **AcceptedWithCaveats / Inconclusive** | **YES** |
| 4 | **Iteration retrieves no new evidence** | 2 | **3** | **AcceptedWithCaveats / Inconclusive** | **YES** |
| 5 | Question pool exhausted before cap | 2 | 4 | Accepted / AcceptedWithCaveats | No |
| 6 | Conclusion rejected | 1 | 5 | Reject | YES |

Failing results:

- More than 3 iterations executed
- **Case 3 returning a clean "Accepted"**
- A question with a semantic key already used being re-asked
- Loop continuing after an iteration retrieved no new evidence
- Any iteration absent from the audit record
- The loop not replayable from the audit record

---

# 17. Hypothesis Catalogue — Reference Cases

| # | Scenario | Expected |
|---|---|---|
| 1 | Same investigation run twice | **Identical candidate set, identical order** |
| 2 | `Holiday_Count = 0` | Holiday hypothesis **not generated**, reason recorded |
| 3 | Queue with 39 weeks of history | Seasonality **not generated** · Insufficient History **generated** |
| 4 | `BR-112` Tier C | Warranty Mix Shift **not generated**, reason recorded |
| 5 | Offering = OOP | Four Business hypotheses **not generated** · Queue Migration generated |
| 6 | Pattern with no catalogue match | Recorded as **UNEXPLAINED OBSERVATION**, no ad-hoc hypothesis |
| 7 | Any investigation | `Product Lifecycle` and `Manual Override` **absent from the catalogue** — documented as Known Gaps |

---

# 18. Prompt Contract — Reference Cases

| # | Scenario | Expected |
|---|---|---|
| 1 | Malformed JSON returned | Retry once, then `Incomplete` |
| 2 | **Narrative contains a figure absent from inputs** | **REJECTED**, RCA `Incomplete` |
| 3 | Narrative states a different root cause | **REJECTED** |
| 4 | Narrative states "High" where confidence is Medium | **REJECTED** |
| 5 | Supplied contradictory evidence omitted | **REJECTED** |
| 6 | Timeline callout omitted | **REJECTED** |
| 7 | LLM times out | RCA `Incomplete`, structured output intact |
| 8 | **Analyst annotation contains instruction-like text** | **Treated as data; behaviour unchanged** |
| 9 | Any successful invocation | Prompt version, model version, seed, full prompt and response persisted |

Failing results:

- Any hypothesis generated outside the catalogue
- Any cross-examination question outside the catalogue
- Two runs producing different candidate sets
- An LLM response accepted without validation
- An LLM response **partially** accepted
- A narrative published with an unpinned model version
- An LLM failure **blocking** an RCA rather than marking it `Incomplete`
- **Any LLM invocation outside the Executive Narrative Engine**

---

# 19. Generation Window — Reference Cases

| # | Scenario | Expected |
|---|---|---|
| 1 | Week inside window, breaching | RCA generated |
| 2 | Week outside window, breaching | **No RCA generated** |
| 3 | New actuals week lands | Window advances; new week generated; existing 12 untouched |
| 4 | Week falls out of window | RCA **retained**, not deleted |
| 5 | **Year-over-year baseline outside window** | **Baseline still retrieved** — evidence unbounded |
| 6 | Driver relevance correlation over 235 weeks | **Full history used** |

---

# 20. Analysis Hierarchy — Reference Cases

Measured cardinality: L1 = **113** · L2 = **286** · L3 = **427**. Evaluable in window: 113 / 285 / 424.

| # | Scenario | Expected |
|---|---|---|
| 1 | L1 grouping | Region + SubRegion + **Country** + Offering |
| 2 | L1 breach count at ±10% | **48 of 113** |
| 3 | L2 breach count at ±10% | 162 of 285 |
| 4 | L3 breach count at ±10% | 245 of 424 |
| 5 | Queue channel over time | **Stable** — 0 of 427 queues vary |

## Dynamic collapse

| # | Scenario | Expected |
|---|---|---|
| 1 | L1 group with 1 channel (24 of 113) | **L2 skipped**, navigate to L3 |
| 2 | L2 group with 1 queue (202 of 286) | L3 reached directly |
| 3 | L1 group with 1 queue (19 of 113) | **Both L2 and L3 collapsed** to the queue RCA |
| 4 | L1 group with 24 queues, multiple channels | **No collapse** |
| 5 | Any collapsed level | **Still appears in the breadcrumb** |
| 6 | Collapse decision | Evaluated at **query time from data**, never hardcoded |

## Aggregate views

| # | Group | Expected |
|---|---|---|
| 1 | Americas · NA · United States · Basic | pooled **−7.1%**, net 28,975, gross **72,186**, offset 59.9%, label MIXED. **Ranks first** by default sort despite not breaching ±10% |
| 2 | APJ · CCC · China · Pro | pooled **+36.4%**, gross 28,452, offset **1.0%**, label **SYSTEMIC** |
| 3 | APJ · CCC · China · Premium | pooled −26.1%, gross 58,941, offset 57.5%, MIXED |
| 4 | Any single-queue group | `offsetLabel` **null**; marked single-queue |
| 5 | Any group | Response **without** `grossVariance` → **invalid** |
| 6 | Any group | **No confidence score** at group level |

Failing results:

- `pooledAdherence` returned without `grossVariance` or `offsetRatio`
- Aggregate view sorted by adherence percentage by default
- **Americas · NA · United States · Basic absent from the ranked L1 view**
- A confidence score computed at Level 1 or Level 2
- An RCA generated at Level 1 or Level 2
- A redundant level displayed rather than collapsed
- A collapsed level absent from the breadcrumb

---

# 21. Re-run Governance — Reference Cases

| # | Scenario | Expected |
|---|---|---|
| 1 | Out-of-window request, historical exists | **Historical served, not regenerated** |
| 2 | Out-of-window request, none exists | Generated, `Generation_Mode = Manual` |
| 3 | Re-run, fingerprint changed | Proceeds, prior `Superseded`, change stated |
| 4 | Re-run, fingerprint unchanged, **no reason** | **REJECTED** — 400, reason mandatory |
| 5 | Re-run, fingerprint unchanged, reason given | Proceeds, **Governance Exception logged**, Administrator flagged, banner shown |
| 6 | Re-run on unchanged data | **Result identical to original** — determinism |

---

# 22. Component Tests

| # | Scenario | Expected |
|---|---|---|
| 1 | Confidence Panel | **Never collapsible**, all 8 dimensions, all reasons |
| 2 | **Suppressed hypothesis** | **Visually distinct from Rejected** |
| 3 | Not Applicable hypothesis | Collapsed but present; wording *"not relevant"*, never *"unavailable"* |
| 4 | Complete period | **No Timeline callout** |
| 5 | Filter cascade | Region narrows SubRegion and Country |
| 6 | Threshold filter | **Single-select only** |
| 7 | New `business_org` value in source | Appears in filter **without code change** |
| 8 | Executive persona | Root Cause Tree not rendered; **Confidence Panel rendered** |
| 9 | Root Cause Tree | Rejected and suppressed siblings present, collapsed |
| 10 | Evidence Timeline, holiday-anchored | **Both** baseline periods shown |

---

# 23. End-to-End Validation

## Workflow — must match the canonical sequence

```
Actuals Loaded
      ↓
Data Validation
      ↓
Adherence Calculation
      ↓
Deviation Detection
      ↓
Business Context Retrieval
      ↓
Business Rules Execution
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
Cross-Examination (bounded loop)
      ↓
Confidence Assignment
      ↓
Root Cause Selection
      ↓
Recommendation Generation
      ↓
Decision Card Generation
      ↓
Audit Persistence
```

> Version 1.0.0 omitted Recursive Root Cause Reasoning, Deviation Detection and the separation of supporting from contradictory evidence.

## Sequence assertion

The E2E test shall assert the **order** of stages, not merely their occurrence.

Failing results:

- **Statistics executing before hypothesis generation**
- **Confidence assigned before cross-examination completes**
- Recursive Root Cause Reasoning absent from the trace
- Context built before deviation detection
- Any stage absent from the audit trail

---

# 24. Performance Tests

| Target | Value |
|---|---|
| Complete RCA | Under 60 seconds |
| Adherence calculation | Under 2 seconds |
| Context retrieval | Under 5 seconds |
| Statistical analysis | Under 20 seconds |
| Narrative generation | Under 30 seconds |

## Volumetrics under test

| Measure | Value |
|---|---|
| Queues | 427 |
| Evaluable queue-weeks in window | ~5,434 |
| RCA scope at ±5% | ~83% |
| Weekly narrative calls | ~1,000 across three grains |

Monthly and quarterly recomputed weekly.

## Timeout behaviour

| # | Scenario | Expected |
|---|---|---|
| 1 | Time budget exhausted mid-investigation | **`Incomplete`** — published, banner, stages listed, **confidence capped Low**, provisional wording |
| 2 | Unrecoverable error | **`Failed`** — **not published**, reason in audit |
| 3 | Incomplete RCA | **Must not be mistakable for complete** |

---

# 25. Regression Testing

## Reference set

A fixed set of completed RCAs spanning: high and low confidence · each capped state · Not Applicable dimensions · Missing dimensions · partial periods · all three grains · each hypothesis category · each warranty tier.

## Triggers

| Change | Regression required |
|---|---|
| Prompt version | Yes — full reference set |
| Confidence weights | Yes |
| Any threshold | Yes |
| Hypothesis catalogue | Yes |
| Question catalogue | Yes |
| Model version | Yes |

Old and new output compared side by side. Differences reviewed before release.

---

# 26. UAT Scenarios

## Adherence and triggering

- Under-forecast breach (negative adherence)
- Over-forecast breach (positive adherence)
- Display filter changed — **verify RCA content unchanged**
- Display filter tightened and loosened — **verify no regeneration**
- Materiality floor suppression — verify RCA still exists and is reachable via toggle
- Lazy generation — first open of a ±5–10% period
- Repeat open — verify cache hit, no regeneration
- Major deviation — verify escalation and **display filter** bypass, **not** materiality bypass
- Manual RCA request below threshold
- Non-computable adherence (`fcst_offered = 0`)

## Grains and periods

- Weekly, Monthly and Quarterly for the same queue — verify three independent investigations
- Queue breaching weekly but not monthly — verify offsetting-errors narrative
- Queue breaching monthly but not weekly — verify accumulating-bias narrative
- Partial month, 1 of 4 weeks — verify Timeline, coverage, cap, and prohibition on full-period language
- Partial quarter, 5 of 13 weeks — same
- New actuals week lands — verify recomputation, prior `Superseded` and **not** overwritten
- Recomputed period no longer breaches — verify prior retained, not presented as active
- **Complete period — verify no Timeline callout**
- 53-week year Q4 quarterly RCA — verify 14-week period

## Warranty and drivers

- Tier A — verify specific band named, direction and magnitude stated
- Tier B — verify clamp, flag, small penalty, analysis proceeds
- **Tier C — verify hypothesis SUPPRESSED not rejected**, reason stated, RCA completes at reduced confidence
- Tier C on a Basic queue — verify card states the expected primary driver could not be evaluated
- Shipments with no-warranty units — verify `No_Warranty` band populated, reconciliation holds
- **Basic queue where shipments pass the gate — verify shipments used first**
- Basic queue where shipments fail — verify fall-through to ASU, **not** reordering
- ASU above plan with under-forecast — verify coherent direction
- ASU above plan with over-forecast — verify contradictory evidence recorded
- Installed base **decline** beyond threshold — verify hypothesis generated
- OOP queue — verify Not Applicable, **no penalty**, wording *"not applicable"*

## Holidays

- Diwali period — verify holiday-anchored comparison against FY26 FW38, not FW41
- Eid period — verify anchoring despite 8-week drift
- Multi-day holiday straddling two weeks — verify first-day anchor, straddle recorded
- Day-of-week difference — verify flagged, not quantified
- Aggregate country — verify holiday context Not Applicable, no penalty

## Confidence

- Clean investigation — Very High, no cap
- Basic queue, Tier C — **capped Medium**, reason prominent, **not behind an expander**
- OOP queue — Not Applicable, no penalty, correct wording
- Emerging queue, partial quarter — **lowest cap binds**
- Business rule contradicting the conclusion — **capped Low despite strong statistics**
- Contradiction search not performed — **Missing, not neutral**
- Single-source evidence — Gate 6 caps at Low
- Failed cross-examination — Gate 7 caps at Low
- Confidence explanation — verify it states **what would change** the assessment
- Weights changed — verify historical scores reproduce using stored `weightsVersion`

## Precedent and annotations

- Low-confidence precedent — verify **not returned as evidence**, visible marked non-evidential
- Superseded precedent — verify **never returned**
- Medium precedent, same cause — verify **capped at the precedent's own score**
- Basic queue, repeated Tier C — verify warranty hypothesis **not progressively de-prioritised**
- Annotation retrieved — verify normal comment presentation with provenance control
- Provenance control — verify all four fields present
- Annotation containing instruction-like text — verify **treated as data**

## Hierarchy and aggregates

- L1 group with high offset — verify **"Offsetting"**, pooled figure de-emphasised
- L1 group with low offset — verify **SYSTEMIC** label
- Americas · NA · United States · Basic — verify **ranks first** despite −7.1%
- Single-queue L1 group — verify collapse to queue RCA, breadcrumb intact
- Drill-down — verify filter state carries

## Governance

- Out-of-window request — verify historical served
- Re-run with data change — verify supersession and change statement
- Re-run without data change, no reason — verify rejection
- Re-run without data change, reason given — verify Governance Exception and banner
- LLM unavailable — verify RCA completes `Incomplete`, structured output readable
- Identical investigation run twice — **verify identical structured output**
- Historical RCA re-opened — verify **original** band and materiality floor applied

---

# 27. Quality Gates for Release

| # | Gate |
|---|---|
| 1 | All reference cases pass with stated expected values |
| 2 | Unit coverage ≥ 90% on calculation and rule modules |
| 3 | **The confidence invariant test passes** |
| 4 | **The laundering test passes** |
| 5 | E2E sequence assertion passes |
| 6 | Determinism test passes on structured output |
| 7 | No LLM invocation outside the Narrative Engine |
| 8 | Every API endpoint contract-tested |
| 9 | Regression reference set clean |
| 10 | UAT scenarios business-validated |

---

# 28. Known Data Conditions Under Test

Tests shall exercise these measured conditions rather than assume clean data:

| Condition | Measured |
|---|---|
| Warranty Tier C | 15.9% overall, **32.0% for Basic** |
| Warranty conformance trend | Degrading — 74.4% FY23 to 58.8% FY27 |
| `Actual_ASU` blank | 44% |
| `Planned_ASU` blank | 34% |
| `Final_upp_units` blank | 83.3% |
| Interior blank weeks | 550 across 55 queues, max run 78 |
| `fcst_offered = 0` | 50 rows |
| Queues below 104 weeks history | 18 of 427 |
| Aggregate country values | ~4.2% of rows |
| Holiday rows failing weekday check | 180 of 10,341, of which 161 transposed |
| Actuals lag | ~4 fiscal weeks |

---

# 29. Guiding Principles

- A test that cannot fail is not a test
- Expected values are measured, not illustrated
- Invariants are asserted, not assumed
- Structured output is exact; narrative wording is tolerance
- The build fails on a wrong sign, a summed stock, or a laundered confidence score
- Tests exercise the data as it is, not as it should be

---

# End of Document
