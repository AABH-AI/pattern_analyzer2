# FC_RCA_Context_Repository_Design

**Project:** Forecast RCA Studio (FC_RCA)
**Document Type:** Context Repository Design
**Version:** 2.1.0
**Supersedes:** Version 2.0.0
**Status:** Approved for Development
**Last Updated:** 30 July 2026

---

## Document Control

| Item | Detail |
|---|---|
| **Purpose** | Define the business knowledge layer: what context exists, how it is retrieved, and how availability is resolved. |
| **Scope** | Business context repositories for Phase 1. |
| **Version basis** | Incorporates P1–P11. Operational Metadata removed from Phase 1. Availability model introduced. Historical learning gated. |
| **Dependencies** | `FC_RCA_Business_Rules.md` v2.0 · `FC_RCA_Data_Dictionary_and_Schema.md` v2.0 |
| **Acceptance Criteria** | (1) Every element resolves to Available, Missing or Not Applicable. (2) No repository depends on data absent from source. (3) Historical learning cannot inflate confidence. |
| **Owner** | Product Owner, FC_RCA |
| **Approver** | Pending |

---

# 1. Purpose

The Context Repository is what allows the engine to reason about a business rather than about a number.

Without it, a −18% deviation is arithmetic. With it, that deviation sits in a fiscal week containing Diwali, on a Basic-offering queue whose warranty coverage mix shifted seven points, in a quarter where the installed base grew 22% against plan.

---

# 2. Design Principles

| # | Principle |
|---|---|
| 1 | Context is retrieved **before** hypotheses are generated |
| 2 | Every element resolves to **Available**, **Missing** or **Not Applicable** — and these three are never conflated |
| 3 | No repository depends on data absent from source |
| 4 | An optional repository carries **no penalty** when unpopulated |
| 5 | Retrieval is scoped to the fiscal period in question, with effective-dated classifications resolved to that period |
| 6 | Learning is gated — a weak conclusion cannot become strong evidence |

## Principle 2 — why it is load-bearing

| State | Meaning | Confidence effect |
|---|---|---|
| **Available** | Data present and usable | Scored |
| **Missing** | Element is relevant, possibly primary, but data absent or invalid | **Penalty** |
| **Not Applicable** | Element is irrelevant to this queue | **No penalty** |

An out-of-warranty queue has no warranty exposure. Penalising it would make that queue structurally incapable of High confidence regardless of analytical quality. A Basic-offering queue with invalid warranty data is the opposite case — the element is not merely relevant, it is the expected primary driver.

Same absence. Opposite meaning.

---

# 3. Repository Inventory — Phase 1

| # | Repository | Populated from |
|---|---|---|
| 4 | Fiscal Calendar | Derived from source |
| 5 | Holiday Calendar | Global holiday master |
| 6 | Holiday Name Synonym | Maintained manually |
| 7 | Queue Repository | Derived from source |
| 8 | Queue Lineage | Maintained manually |
| 9 | Shipment and Warranty Repository | Source |
| 10 | Installed Base Repository (ASU) | Source |
| 11 | Business Event Repository | **Manual, optional** |
| 12 | Business Observation Repository | Analyst annotations |
| 13 | Historical RCA Repository | Completed investigations |
| 14 | Business Rules Repository | Configuration |

## Removed from Phase 1

| Repository | Reason |
|---|---|
| **Operational Metadata** | Specified Queue Capacity, Staffing Model, Service Level Target, AHT, ASA, Occupancy, Shrinkage. **All are Capacity Planning, Scheduling or Real-Time Adherence constructs**, explicitly excluded from Phase 1, and **none has any source in the input data** |
| **Product Repository** | No product identifier exists in source data |
| **Forecast Knowledge Repository** | Superseded by the Queue Repository and Historical RCA Repository |

Operational Metadata is **not** a Context Completeness element in Phase 1. It is excluded from the denominator entirely and carries no penalty. Retaining it as Missing would depress confidence on every investigation for a capability not being built.

---

# 4. Fiscal Calendar Repository

**Purpose** — the canonical time dimension. Every time-based calculation resolves through it.

**Grain** — one row per fiscal week.

**Key** — `Fiscal_Week`, format `YYYYWW` where `YYYY` is the **fiscal** year.

## Derivations

| Item | Rule |
|---|---|
| Fiscal year | `FLOOR(Fiscal_Week / 100)` |
| Week number | `MOD(Fiscal_Week, 100)` |
| Quarter | 01–13 Q1 · 14–26 Q2 · 27–39 Q3 · 40–52/53 Q4 |
| Month | **4-4-5** per quarter |
| 53-week year | Q4 becomes **4-5-5** — M11 five weeks, M12 five weeks |
| Week count | `MAX(Fiscal_Week_Number)` per fiscal year (`BR-114`) |

Fiscal year begins the first week of February. Week begins Saturday, ends Friday. Verified: `Week_Ending` is a Friday in 100% of reference rows.

## Governance

Derived from source, not authored. Provisional until `weeks_in_FY ≥ 52`, then final and immutable. The transition is recorded in the Audit Trail.

**Availability** — always Available.

---

# 5. Holiday Calendar Repository

**Purpose** — calendar context, and the basis for holiday-anchored historical comparison.

**Grain** — Date × Country

## Attributes

`Holiday_ID` · `Date` · `Day_Of_Week` · `Holiday_Name_Canonical` · `Holiday_Name_Source` · `Holiday_Type` · `Country` · `Fiscal_Week` · `Impact_Days_Before` · `Impact_Days_After` · `Is_Substitute_Holiday` · `Active_Flag`

## Impact window

| Attribute | Default | Configurable |
|---|---|---|
| `Impact_Days_Before` | 3 | **Per holiday** |
| `Impact_Days_After` | 3 | **Per holiday** |

A holiday's influence extends beyond its date. Diwali may influence demand for several days either side; a bank holiday may not. **Per-holiday configuration is required.**

## Holiday-anchored comparison

Where a moving holiday is present, historical comparison anchors on the **holiday**, not the fiscal week (`BR-209`).

Measured drift on reference data:

| Holiday | Country | Fiscal week by year |
|---|---|---|
| **Diwali** | India | FY23 FW39 · FY24 FW41 · FY25 FW39 · FY26 FW38 · FY27 FW41 · FY28 FW39 |
| **Eid al-Fitr** | UAE | FY23 FW14 · FY24 FW11 · FY25 FW10 · FY26 FW09 · FY27 FW07 · FY28 FW06 |

Diwali drifts up to **3 fiscal weeks**. Eid drifts **8 weeks over six years**.

Day of week also moves — Diwali falls Monday, Sunday, Thursday, Monday, Sunday, Friday across those years. Recorded and **flagged, not quantified**.

## Validation at load

**Reject any row where the weekday derived from `Date` does not match the `Day` column.**

Measured on CY2022+ data: 180 of 10,341 rows fail. **161 are explained by day and month being transposed.** The remaining 19 are substitute-holiday observances.

4,823 rows (46.6%) have day-of-month ≤ 12, where a transposition would produce a valid date and be **undetectable**. The 8 affected countries indicate a specific source path requiring verification.

> **STATUS:** the corrected Holiday master has been supplied and validated. All 161 transposed rows are corrected, plus 29 further same-weekday transpositions found by `BR-126`.

## Date Representation

`Date` in **`DD-MMM-YYYY`**. `Date_ISO` in `YYYY-MM-DD`. **Holiday data only** — source feeds are unmodified.

## Calendar Basis

Every holiday carries a `Calendar_Basis` attribute determining whether cross-year drift detection applies. See `BR-126`.

## Two-Layer Load Validation

| Layer | Check | Catches |
|---|---|---|
| **1** | Weekday matches the date | Most date corruption |
| **2** | Cross-year drift, Gregorian basis only (`BR-126`) | **Same-weekday transpositions** |

Layer 1 alone is insufficient. All 29 transpositions found in the reference master **passed Layer 1** because both readings fell on the same weekday.

## Anchor Date

Holiday-anchored comparison uses the **ACTUAL** date. `Observed_Date` is supplementary context and does not drive comparison (`BR-209`).

Measured: actual dates agree with the `INPUT_TO_ML` day flags at **71.3%**, observed at 66.3%.

## Deduplication

`SELECT DISTINCT` on the **entire row**. Measured: 1,935 duplicate rows across 621 groups. Does not corrupt `Holiday_Count`, which derives from day indicators.

## Availability

| Condition | State |
|---|---|
| Country resolvable, calendar loaded | Available |
| **Country is an aggregate value** | **Not Applicable** — no penalty |
| Country resolvable, calendar not loaded or stale | Missing — penalty |

Aggregate values: `North America` · `ROLA` · `Multiple AMER Countries` · `Multiple EMEA Countries`. ~4.2% of reference data.

---

# 6. Holiday Name Synonym Repository

**Purpose** — resolve name variants to a canonical name, enabling holiday-anchored comparison across years.

**Attributes** — `Synonym_ID` · `Canonical_Name` · `Variant_Name` · `Country` (nullable — null means all countries)

**Rationale** — 657 distinct holiday names across 79 countries in CY2022+ data. Variants include "Diwali", "Deepavali", "Diwali/Deepavali".

**Population** — maintained manually. New variants are flagged to the Administrator rather than silently unmatched.

---

# 7. Queue Repository

**Purpose** — queue metadata and effective-dated classifications.

## Static attributes

`Forecast_Name` · `Offering` · `Region` · `SubRegion` · `Country` · `business_org` · `channel` · `Forecaster` *(access-restricted)* · `Active_Flag` · `First_Observed_Fiscal_Week` · `Last_Observed_Fiscal_Week`

`channel` is a **stable queue attribute** — 0 of 427 queues change channel across full history.

## Effective-dated classifications

Recalculated **FW01, FW14, FW27, FW40**. Each carries its effective quarter and the basis window it was derived from.

- `Volume_Band` — size, per `BR-113`
- `Avg_Weekly_Volume`
- `Basis_Quarter` · `Basis_Weeks_Used` · `Basis_Weeks_Expected`
- `ASU_Driver_Relevant` · `Shipment_Driver_Relevant` · `Warranty_Driver_Relevant` — per `BR-121`
- `Selected_Lag_Weeks` per flow driver — per `BR-404`

## Retrieval contract — mandatory

A request for queue classification **must specify the fiscal period of interest**. The repository returns the classification **in force for that period**, never the current one.

```
getQueueContext(forecastName, fiscalWeek)
    → classification effective for that week's quarter
```

Resolving a historical RCA against a current classification would silently alter its evidence base and break reproducibility.

**There is deliberately no "current classification" endpoint.**

## Removed

| Attribute | Reason |
|---|---|
| Queue Type | No source |
| Queue Category | Superseded by the two effective-dated classifications |
| Business Unit, Geography as opaque identifiers | Replaced by natural values |

## Population

Derived from the source dataset. Queues registered on first appearance, never deleted, only marked inactive.

**Availability** — always Available.

---

# 8. Queue Lineage Repository

**Purpose** — preserve analytical history across queue renames, merges and splits.

**Problem addressed** — when a `Forecast_name` changes, the engine sees a new queue and loses Volume Band history, precedents, year-over-year comparison and the 104-week sufficiency baseline.

**Attributes** — `Lineage_ID` · `Predecessor_Forecast_Name` · `Successor_Forecast_Name` · `Effective_Fiscal_Week` · `Relationship_Type` (Rename / Merge / Split) · `Volume_Allocation_Pct` · `Notes` · `Created_By` · `Created_At`

## Resolution

Where lineage exists, these resolve through the chain:

- Volume Band basis
- Data Sufficiency history depth
- `HistoricalConsistency` precedent search
- Year-over-year and holiday-anchored comparison
- Driver Relevance Gate correlation window

## Disclosure — mandatory

> *"History for this queue includes 187 weeks recorded under the previous name 'India Comm Client Voice' up to FY27 FW13."*

**Inherited history is never presented as native.** A merge combines two demand populations and a reader must be able to see that.

## Constraints

Manually maintained — queue changes are business events, not data events. No cycles. Chains deeper than 3 links require review.

---

# 9. Shipment and Warranty Repository

**Purpose** — planned shipment volumes and their nested warranty coverage tiers. Provides derived exclusive-band history for RCA.

**Grain** — Queue × Fiscal Week

## Attributes

`Forecast_Name` · `Fiscal_Week` · `Final_Units` · `Final_Y1` to `Final_Y5` · `Final_upp_units` · `Warranty_Validation_Tier` · `Warranty_Validation_Reason` · `Shipment_Applicable` · `Shipment_Driver_Relevant`

## Structural rule

```
Final_Y5 <= Final_Y4 <= Final_Y3 <= Final_Y2 <= Final_Y1 <= Final_Units
Final_Units != SUM(Final_Y1 .. Final_Y5)
```

`Final_Y1` through `Final_Y5` are **nested cumulative subsets**. Summing them **double-counts**. Measured: `SUM(Y1..Y5)` averages **2.6×** actual shipments.

## Derived

- Exclusive warranty bands — `No_Warranty`, `1Y`, `2Y`, `3Y`, `4Y`, `5Y` — obtained by **differencing**
- Band shares as a percentage of `Final_Units`
- Period-over-period band shift
- Trend across the retained history window

**Reconciliation asserted on every calculation.** Verified: exclusive bands reconcile to `Final_Units` in 100.0% of Tier A rows.

**The repository shall never expose raw nested values as independent variables to statistical analysis.**

## Availability

| Condition | State |
|---|---|
| Tier A or B, applicable, driver relevant | Available |
| **Out-of-warranty offering** | **Not Applicable** — no penalty |
| **Driver fails relevance gate** | **Not Applicable** — no penalty |
| Tier C — nesting inverted or totals impossible | **Missing** — penalty, hypothesis suppressed |
| Fields blank | Missing — penalty |

Measured: Tier C affects 15.9% of rows overall, and **32.0% of Basic-offering rows** — the offering for which shipments are the stated primary driver.

Driver relevance: 76 of 427 queues (18%) pass the gate.

## Lag

Shipments are a **flow**. Lag is determined **empirically per queue** (`BR-404`), not prescribed. Measured: no fixed lag improves on contemporaneous.

## Removed

| Attribute | Reason |
|---|---|
| Product, Geography | No source. Grain is Queue × Fiscal Week |
| Warranty Type | Superseded by the exclusive band structure |
| `Out_of_Warranty` | No source. Conflated the derived `No_Warranty` band with an Offering attribute |

---

# 10. Installed Base Repository

**Purpose** — Active Serviceable Units: the installed base of units in market and covered under warranty. A **STOCK** measure and a primary demand driver.

> **ASU is not "Average Selling Units."** Version 1.0.0 carried that definition, describing a sales metric that does not exist in source data.

**Grain** — Queue × Fiscal Week. Values are **weekly averages**.

## Attributes

`Forecast_Name` · `Fiscal_Week` · `Planned_ASU` · `Actual_ASU` · `ASU_Applicable` · `ASU_Driver_Relevant`

## Derived

- `ASU_Adherence` — `(1 − Actual_ASU / Planned_ASU) × 100`, same convention as Forecast Adherence
- Year-over-year growth at the RCA grain
- Month-over-month growth
- Trend across the retained window

## Aggregation rule

**ASU is averaged across periods, never summed.** Summing counts the same physical units once per week they remained under warranty.

## Availability

| Condition | State |
|---|---|
| Values present, applicable, relevant | Available |
| **Out-of-warranty offering** | **Not Applicable** — no penalty |
| **Driver fails relevance gate** | **Not Applicable** — no penalty |
| Values blank | **Missing** — penalty |

Measured: `Actual_ASU` blank in ~44% of rows, `Planned_ASU` in ~34%, owing to data lag. **Expected, not a defect.**

Driver relevance: **236 of 427 queues (55%) pass the gate** — the strongest driver in the dataset.

## Plan versus Actual

| Pairs with | Field |
|---|---|
| `fcst_offered` | `Planned_ASU` |
| `Actual_Offered` | `Actual_ASU` |

Divergence is a **first-class hypothesis** (`BR-208`), not merely two features.

## Relationship to shipments

Distinct stages of one funnel; they do not double-count:

```
Production plan  →  Shipments  →  Installed base under warranty
   (flow)            (flow)            (stock)
```

Installed base supports **contemporaneous** correlation. Shipments support **empirically-lagged** correlation.

## Removed

Product, Geography — no source. "Average Selling Units" — an incorrect definition.

---

# 11. Business Event Repository

**Purpose** — identify business events that may explain a deviation.

**Grain** — Event

## Attributes

`Event_ID` · `Event_Name` · `Event_Type` · `Event_Description` · `Forecast_Name` (nullable) · `Region` / `SubRegion` / `Country` / `Offering` (nullable scoping) · `Event_Fiscal_Week` · `Impact_Weeks_Before` · `Impact_Weeks_After` · `Impact_Window_Rationale` · `Created_By` · `Created_At` · `Active_Flag`

## Matching window

| Attribute | Default | Configurable |
|---|---|---|
| `Impact_Weeks_Before` | 2 | **Per event** |
| `Impact_Weeks_After` | 2 | **Per event** |

Per-event configuration is required because impact duration varies — a product launch may influence demand for five weeks, an outage for one.

## THE REPOSITORY IS OPTIONAL

| State | Treatment | Confidence |
|---|---|---|
| **Not deployed, or empty** | **Not Applicable** | **No penalty** |
| **Populated, no event matches the period** | **Available** — the result is *"no event found"* | **No penalty** |
| Populated, retrieval failed or data stale | **Missing** | Penalty |

**The middle row is the important distinction.** *"No event found"* is a **result**, not a gap. The Event hypothesis was tested and rejected. **Confidence shall not fall for successfully ruling something out.**

This means the repository may remain unpopulated indefinitely without depressing confidence on every investigation, and begins contributing the moment an event is entered.

## Population

**Manual entry via the Administration Portal in Phase 1.** Automated ingestion, event correlation, impact scoring and similarity detection are Phase 2.

---

# 12. Business Observation Repository

**Purpose** — analyst knowledge that cannot be derived from data.

**Grain** — Observation

## Attributes

`Observation_ID` · `Source_Type` · `RCA_Case_ID` (nullable) · `Forecast_Name` · `Fiscal_Week` · `Annotation_Type` (Agree / Disagree / AdditionalContext) · `Observation_Text` · `Author` · `Created_At` · `Provenance_Weight`

## Sources and weighting

| Source | Provenance weight |
|---|---|
| Analyst annotation | **1.00** |
| Manual entry | 1.00 |

**1.00 is the highest weight available** — human-verified evidence.

## Retrieval

Retrieved where the observation references the same `Forecast_Name`, or the same `SubRegion` and `Offering`, and a related root cause category.

## Exemption from the eligibility gate

Annotations are **not** subject to the `BR-203` confidence eligibility gate.

That gate governs **machine-generated conclusions**, whose confidence is self-assessed. A human annotation carries **external verification** and is eligible regardless of the confidence of the RCA it was recorded against.

## Display

Presented as **normal narrative content** with a **provenance control** revealing:

| Field | Content |
|---|---|
| Source | RCA and period it was recorded against |
| Author | Name and date |
| Why | Reason for retrieval |
| Impact | Which hypothesis it supports, which dimension it contributed to |

All four are required. Never presented as a raw system citation.

## No autonomous learning

Annotations do **not** adjust the model, prompts, hypothesis weights or thresholds. They become **retrievable evidence — nothing more**.

The engine produces better RCAs over time because it has access to more evidence, not because it changed itself.

---

# 13. Historical RCA Repository

**Purpose** — store every completed investigation, and provide eligible precedents to future investigations.

## Storage — everything is stored

Every completed RCA contributes: root cause · evidence · recommendations · business observations · cross-examination record · confidence decomposition.

**Learning shall never overwrite historical investigations.**

## Eligibility attributes — mandatory

`Case_Status` · `Confidence_Level` · `Confidence_Score` · `Generation_Threshold_Met` · `Superseded_By_Case_ID` · `Evidence_Eligible` (derived) · `Analyst_Validated` (reserved)

## Retrieval — GATED

**Storage and retrieval-as-evidence are distinct.** An entry may be stored and visible to an analyst while being ineligible to influence a later investigation.

| Entry condition | Retrievable as evidence |
|---|---|
| `Completed` **and** confidence ≥ Medium | **Yes** |
| Confidence Low or Very Low | **No** — reference only |
| `Inconclusive` | **No** — reference only |
| `Superseded` | **No** — never |
| `Failed` | **No** — never |
| `Generation_Threshold_Met = false` | **No** — reference only |

**"Reference only"** means visible to an analyst on request, clearly marked non-evidential, and excluded from `HistoricalConsistency` scoring and hypothesis prioritisation.

## Provenance weighting

A retrieved precedent contributes in proportion to **its own** confidence (`BR-118`):

| Precedent confidence | Provenance weight |
|---|---|
| Very High | 1.00 |
| High | 0.80 |
| Medium | 0.60 |
| Low / Very Low | Not eligible |

## THE CEILING — mandatory

```
HistoricalConsistency <= precedent_confidence_score
```

**This makes confidence laundering structurally impossible.** A Medium precedent can never produce a `HistoricalConsistency` above its own score, so citation cannot amplify.

## Why the gate exists

Without it, a Low-confidence conclusion entering the repository would score 1.00 on a later investigation, raising that investigation above the precedent it rests on. Three iterations convert a guess into a High-confidence finding with nothing verified — the Confirmation Bias and Availability Bias that `RCA Methodology §27` and `BR-303` exist to prevent.

## Compounding risk specific to this dataset

**32% of Basic-offering queue-weeks have unusable warranty data.** Those investigations conclude on alternative hypotheses at reduced confidence. Without the gate, those alternatives would enter the repository, be retrieved by future Basic investigations and weighted up — systematically under-weighting the warranty hypothesis **even in periods where the data is sound**.

The engine would learn to explain Basic queues without warranty, because that is what it was forced to do when the data was broken.

## Similarity matching — Phase 1

**Structural**, on attributes the data already carries:

| Match level | Criteria | Strength |
|---|---|---|
| Exact | Same `Forecast_name`, same fiscal period prior year | Strongest |
| Strong | Same `Forecast_name`, any prior period, same direction | Strong |
| Moderate | Same `SubRegion` + `Offering` + `channel`, similar magnitude | Moderate |
| Weak | Same `Offering` only | Weak |

Deterministic, explainable, and an analyst can verify **why** two periods were matched.

Semantic matching via embeddings is **Phase 2** — it requires an embedding model, a vector store, a similarity threshold and a re-embedding strategy, and it weakens explainability. *"These are 0.87 similar"* is not an explanation an analyst can check.

## Analyst validation — reserved

`Analyst_Validated` is **reserved and not populated in this release**. Analyst annotations are captured (§12), but no validation workflow exists. The eligibility gate therefore relies on **calculated confidence** rather than human validation.

Where a validation workflow is implemented, `Analyst_Validated` should be added to the gate as a stronger condition.

## Retrieval contract

The repository exposes eligible and ineligible entries through **separate paths**. A caller requesting evidence receives only eligible entries. A caller requesting analyst reference may receive all, **with eligibility marked**.

An ineligible entry shall never be returned through the evidence path, and never returned unmarked.

---

# 14. Business Rules Repository

Stores every rule with its threshold, default, configurability, priority, version, effective date and approver.

`Is_Configurable = false` for the RCA Generation Threshold (±5%) and LLM temperature (0).

Rule authoring and rule approval are **separate roles**.

---

# 15. Context Retrieval Engine

## Retrieval sequence

Context is retrieved at **Step 5** of the canonical sequence — after deviation detection, before hypothesis generation.

```
Deviation detected
      ↓
Resolve queue classification for the period      (effective-dated)
      ↓
Resolve calendar and holiday context             (holiday-anchored where applicable)
      ↓
Resolve shipment, warranty and installed base    (applicability + relevance gates)
      ↓
Resolve business events                          (optional)
      ↓
Retrieve eligible historical precedents          (gated, provenance-weighted)
      ↓
Retrieve business observations                   (ungated)
      ↓
Record availability state per element
```

## Availability resolution

Every element resolves to one of three states **before** hypothesis generation, because applicability determines which hypotheses are generated at all.

## Context Completeness

```
ContextCompleteness = elements_available / elements_applicable
```

**Not Applicable elements are excluded from the denominator.** Unavailable elements count as 0 in the numerator.

---

# 16. Context Prioritisation

Where context conflicts, precedence follows the Evidence Hierarchy:

1. Verified business data
2. Business Rules
3. Deterministic statistics
4. Historical patterns
5. Time-series
6. ML attribution
7. LLM narrative

---

# 17. Repository Health

The Administration Portal shall surface, per repository:

| Metric |
|---|
| Row count and coverage |
| Last refresh timestamp |
| Availability rate — Available / Missing / Not Applicable |
| Validation failure count and reasons |
| Unmapped dimension values pending review |
| Effective-dated classification currency |

## Known health issues in reference data

| Repository | Issue |
|---|---|
| Holiday Calendar | 161 rows with day/month transposed; 1,935 duplicate rows; coverage ends 2027-12-31 against data to 2028-03-24 |
| Shipment and Warranty | 15.9% Tier C overall, **32.0% for Basic offering**; conformance degrading — 74.4% in FY23 to 58.8% in FY27 |
| Installed Base | `Actual_ASU` 44% blank, `Planned_ASU` 34% blank |
| Business Event | Unpopulated |

The warranty conformance trend is worth raising with the data owner independently: remediating the source feed would recover roughly 30% of Basic analytical coverage.

---

# 18. Unmapped Value Alert

Dimension members are populated **dynamically** from the current dataset. New values are never blocked, but must never appear silently.

| # | Rule |
|---|---|
| 1 | A new value is **accepted and immediately usable** |
| 2 | It is **flagged** in the Data Availability Callout and surfaced to the Administrator |
| 3 | The Region → SubRegion mapping **updates automatically** |
| 4 | **A SubRegion can never exist without a Region.** An orphan is rejected |
| 5 | **Alias normalisation runs first**, so `AMER` never registers as a new Region |

Without rule 5, a single alias variant would silently split a region into two dimension members.

---

# 19. Historical Learning

The repository improves continuously, subject to the quality gate in §13.

Every completed RCA contributes to **storage**. Only eligible entries contribute to **evidence**.

## Governing constraint

**Confidence shall never increase because a weaker conclusion was cited.**

`HistoricalConsistency` shall never exceed the confidence score of the precedent it cites. The ceiling **propagates**, which makes confidence inflation through repeated citation arithmetically impossible rather than merely discouraged.

---

# 20. Repository APIs

| Capability | Endpoint |
|---|---|
| Fiscal Calendar | `GET /api/v1/context/fiscal-calendar` |
| Holiday Calendar | `GET /api/v1/context/holidays` |
| Queue classification | `GET /api/v1/context/queue-classification` — **`fiscalWeek` mandatory** |
| Queue lineage | `GET /api/v1/context/queue-lineage` |
| Shipment and warranty | `GET /api/v1/context/warranty` |
| Installed base | `GET /api/v1/context/installed-base` |
| Business events | `GET /api/v1/context/events` |
| Business observations | `GET /api/v1/context/observations` |
| Historical RCA search | `GET /api/v1/context/historical-rca` |
| Repository health | `GET /api/v1/system/repositories` |

Full contracts in `FC_RCA_API_Specification.md`.

---

# 21. Future Repository Extensions

FUTURE SCOPE:

- Automated business event ingestion, correlation, impact scoring and similarity detection
- Vector embedding store for semantic similarity retrieval
- Analyst validation workflow feeding the eligibility gate
- Marketing activity repository
- Product repository, contingent on a product dimension existing in source data
- Operational metadata, alongside the Capacity pillar

---

# 22. Guiding Principles

- Context is retrieved before hypotheses are generated
- Not Applicable, Missing and zero are three different states
- An optional repository carries no penalty when unpopulated
- *"No event found"* is a result, not a gap
- Effective-dated classifications resolve to the period under investigation, never to today
- A weak conclusion cannot become strong evidence
- Human knowledge enters as evidence, never as autonomous adjustment

---

# End of Document
