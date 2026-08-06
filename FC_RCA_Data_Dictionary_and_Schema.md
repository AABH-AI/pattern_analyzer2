# FC_RCA_Data_Dictionary_and_Schema

**Project:** Forecast RCA Studio (FC_RCA)
**Document Type:** Data Dictionary & Logical Schema
**Version:** 2.1.0
**Supersedes:** Version 2.0.0
**Status:** Approved for Development
**Last Updated:** 30 July 2026

---

## Document Control

| Item | Detail |
|---|---|
| **Purpose** | Define every logical entity, attribute and relationship used by Forecast RCA Studio. |
| **Scope** | Master data, forecast and actual domains, business context, statistical repository, ML explainability, investigation, audit and configuration. |
| **Version basis** | Incorporates P1–P11. Grain and key decisions validated against production-representative data. |
| **Assumptions** | Fact grain is one row per `Forecast_name` × `Fiscal_Week` — verified unique across 138,775 rows. No product identifier exists in source data. |
| **Dependencies** | `FC_RCA_Definitions_and_Formulas.md` v2.0 governs field semantics. `FC_RCA_Business_Rules.md` v2.0 governs validation. |
| **Acceptance Criteria** | (1) Every entity is populatable from source data or explicitly marked derived. (2) No foreign key references a dimension absent from source. (3) Stock and flow measures are distinguished with their aggregation rule stated. |
| **Owner** | Product Owner, FC_RCA |
| **Approver** | Pending |

---

# 1. Purpose

This document defines the logical data model underpinning Forecast RCA Studio.

It establishes:

- Every entity and its grain
- Every attribute and its meaning
- Relationships between entities
- Which entities are stored and which are derived
- Aggregation rules by measure type

The model is **logical**, not physical. It prescribes no database technology.

---

# 2. Design Principles

| # | Principle |
|---|---|
| 1 | **Single source of truth.** No value is stored in two places |
| 2 | **Derived over stored.** Where a value can be computed reliably, it is derived, not persisted |
| 3 | **Grain discipline.** Every entity states its grain explicitly |
| 4 | **Stock and flow separated.** Aggregation rule stated per measure |
| 5 | **No phantom keys.** No foreign key references a dimension absent from source data |
| 6 | **Effective dating** where a classification changes over time |
| 7 | **Immutability** of completed investigations and published calendars |
| 8 | **Auditability.** Every investigation reproducible from its audit record |

## Principle 5 — consequence

Version 1.0.0 keyed several entities on `Product_ID` and `Geography_ID`. **Neither exists in source data.** All fact data arrives at queue × fiscal week grain. Those keys are removed throughout, and product-level attribution is declared unavailable rather than approximated.

---

# 3. High-Level Data Architecture

```
                    MASTER DATA
    Geography · Queue · Offering · Fiscal Calendar
                         |
        +----------------+----------------+
        |                                 |
   FORECAST DOMAIN                  ACTUAL DOMAIN
   fcst_offered                     Actual_Offered
   fcst_handled                     Actual_Handled
        |                                 |
        +----------------+----------------+
                         |
              FORECAST ADHERENCE (derived)
                         |
        +----------------+----------------+
        |                |               |
  BUSINESS CONTEXT   STATISTICAL      ML EXPLAINABILITY
  Holiday · Event    Analysis         SHAP · Importance
  Shipment · ASU     Metrics
  Volume Band
        |                |               |
        +----------------+----------------+
                         |
                 INVESTIGATION DOMAIN
        RCA Case · Hypothesis · Evidence
        Root Cause · Cross-Examination
        Confidence · Decision Card
                         |
                  AUDIT REPOSITORY
```

---

# 4. Logical Entity List

## Master Data

| # | Entity | Grain |
|---|---|---|
| 7 | Geography Master | Region · SubRegion · Country |
| 8 | Region Master | Region |
| 9 | Country Master | Country |
| 10 | Business Unit Master | business_org |
| 11 | Queue Master | Forecast_name |
| 11A | **Queue Volume Band** | Queue × Effective Quarter |
| 11B | **Queue Lineage** | Lineage relationship |
| 12 | Offering Master | Offering |
| 14 | Fiscal Calendar | Fiscal Week |

## Forecast and Actual

| # | Entity | Grain |
|---|---|---|
| 16 | Forecast Entity | Queue × Fiscal Week |
| 20 | Actual Contacts Entity | Queue × Fiscal Week |
| 22 | **Active Serviceable Units (ASU)** | Queue × Fiscal Week |
| 23 | Forecast Adherence Entity | Queue × Fiscal Week × Grain |

## Business Context

| # | Entity | Grain |
|---|---|---|
| 25 | Holiday Calendar Entity | Date × Country |
| 25A | **Holiday Name Synonym** | Canonical × Variant |
| 26 | Business Event Repository | Event |
| 26A | **Shipment Plan Entity** | Queue × Fiscal Week |
| 28 | **Warranty Mix** | Derived view |
| 33A | **Business Observation Repository** | Observation |

## Statistical and ML

| # | Entity |
|---|---|
| 31 | Statistical Analysis Entity |
| 32 | Statistical Metric Result Entity |
| 33–38 | Trend · Seasonality · Drift · Momentum · Correlation · Outlier |
| 40–41 | SHAP · Feature Importance |

## Investigation

| # | Entity |
|---|---|
| 43 | RCA Case Entity |
| 43A | **Period Coverage Entity** |
| 43B | **RCA Rerun Request** |
| 44 | Hypothesis Entity |
| 45 | Evidence Entity |
| 46 | Root Cause Entity |
| 47 | Cross-Examination Entity |
| 47A | **Cross-Examination Iteration** |
| 47B | **Cross-Examination Result** |
| 48 | Confidence Entity |
| 48A | **Confidence Dimension** |
| 48B | **Confidence Cap** |
| 49 | Executive Decision Card Entity |
| 50 | Recommendation Entity |
| 60 | **LLM Invocation Entity** |

## Audit and Configuration

| # | Entity |
|---|---|
| 52 | Audit Log Entity |
| 54 | Business Rules Entity |
| 55 | Statistical Configuration Entity |
| 56 | Explainability Configuration Entity |
| 57 | User Entity |

## Retired Entities

| Entity | Reason |
|---|---|
| **13 Product Master** | No product identifier exists in source data |
| **17 Forecast Version** | No version dimension in source. One row per queue-week, verified |
| **18 Forecast Snapshot** | Same |
| **21 Actual Units** | Superseded by Shipment Plan Entity (26A) |
| **27 Installed Base** | Duplicated Entity 22. Installed base *is* ASU |
| **29 Product Age** | No product identifier or age attribute in source |

---

# 5. Master Data Entities

# 7. Geography Master

**Purpose** — Three-level geography hierarchy.

**Grain** — Region · SubRegion · Country

**Attributes**

- `Region` — three values: APJ, EMEA, Americas
- `SubRegion` — sixteen values
- `Country` — forty-nine values
- `Region_Alias` — accepted input aliases
- `SubRegion_Alias`

**Hierarchy — verified clean**

No SubRegion maps to more than one Region. No Country maps to more than one SubRegion or Region.

| Region | SubRegions |
|---|---|
| **Americas** | **NA** *(NorthAm)* · Brazil · LATAM · Multiple AMER SubRegions |
| **APJ** | ANZ · CCC · IN · JPN · KR · SA |
| **EMEA** | CER · EC · Multiple EMEA SubRegions · NER · SER · UKI |

**Reserved literal — `NA`**

`NA` means North America. **It is a valid value, not a null.** Canonical stored form is `NorthAm`. Governed by BR-111. Affects 16,250 rows (11.7%) if mishandled.

**Aliases**

| Canonical | Accepted |
|---|---|
| `Americas` | `AMER` |
| `NA` → `NorthAm` | `NA` · `NorthAm` · `North America` · `North Americas` |

**Aggregate values**

Deliberate multi-entity groupings, valid and analysed, but unresolvable against the country-level holiday master:

- SubRegion — `Multiple AMER SubRegions` · `Multiple EMEA SubRegions`
- Country — `North America` · `ROLA` · `Multiple AMER Countries` · `Multiple EMEA Countries`

For these, holiday context is **NotApplicable**. ~4.2% of rows.

**Removed** — `Geography_ID` surrogate key. Natural values are used throughout.

---

# 8. Region Master

**Grain** — Region. Three rows: APJ, EMEA, Americas.

**Attributes** — `Region` · `Region_Alias` · `Active_Flag`

---

# 9. Country Master

**Grain** — Country.

**Attributes** — `Country` · `SubRegion` (FK) · `Is_Aggregate` (boolean) · `Holiday_Resolvable` (boolean) · `Active_Flag`

`Is_Aggregate` marks the four multi-country values. `Holiday_Resolvable = false` for those, driving the NotApplicable treatment in BR-111.

---

# 10. Business Unit Master

**Grain** — business_org.

**Attributes** — `business_org` · `Active_Flag`

**Note** — one value (`CSG`) in reference data. Additional values (e.g. `ISG`) expected. Populated dynamically; the dimension is not hidden.

---

# 11. Queue Master

**Purpose** — Defines every forecastable queue.

**Grain / Primary Key** — `Forecast_name`

`Forecast_name` is the queue identifier as supplied by source. **Verified unique in combination with `Fiscal_Week`** across 138,775 rows. No surrogate key is introduced.

**Attributes**

- `Forecast_name`
- `Offering`
- `Region` · `SubRegion` · `Country`
- `business_org`
- `channel` — **stable per queue**; 0 of 427 queues change channel
- `Forecaster` — named individual, **access-restricted**
- `Queue_Status` · `Active_Flag`
- `First_Observed_Fiscal_Week` · `Last_Observed_Fiscal_Week`
- `Has_Lineage` (boolean)
- `Lineage_Origin_Forecast_Name` (nullable)

**Removed**

| Attribute | Reason |
|---|---|
| `Queue_ID` | Superseded by `Forecast_name` as natural key |
| `Queue_Type` | No source |
| `Geography_ID` · `Business_Unit_ID` · `Offering_ID` | Replaced by natural values |
| `Queue_Category` | **Moved to Entity 11A** as an effective-dated dimension. Not a static attribute |

**Population**

**Derived** from the source dataset, not maintained manually. Queues registered on first appearance. Never deleted, only marked inactive.

**Note on BR-103** — because Queue Master is derived from the same feed, the registration rule is satisfied automatically. It remains a guard against orphaned references.

---

# 11A. Queue Volume Band Entity

**Purpose** — Effective-dated volume classification. Drives the Materiality Floor and segmentation.

**Grain** — Queue × Effective Fiscal Quarter

**Primary Key** — `Volume_Band_ID`

**Attributes**

- `Volume_Band_ID`
- `Forecast_Name` (FK)
- `Effective_Fiscal_Year` · `Effective_Fiscal_Quarter`
- `Volume_Band`
- `Avg_Weekly_Volume`
- `Basis_Fiscal_Year` · `Basis_Fiscal_Quarter`
- `Basis_Weeks_Expected` — 13, or 14 for Q4 of a 53-week year
- `Basis_Weeks_Used` — weeks where `Actual_Offered` was not blank
- `Calculated_On_Fiscal_Week` — FW01, FW14, FW27 or FW40
- `Is_Emerging` (boolean)
- `Superseded_By_Volume_Band_ID` (nullable)
- `Supersede_Reason` (nullable)

**Permitted values**

| Volume_Band | Range | Materiality Floor |
|---|---|---|
| `<=100` | 0 – 100 | 10 contacts |
| `101-250` | >100 – 250 | 25 |
| `251-500` | >250 – 500 | 50 |
| `501-1000` | >500 – 1,000 | 100 |
| `1001-5000` | >1,000 – 5,000 | 200 |
| `>5000` | >5,000 | 500 |
| `Emerging` | No prior-quarter actuals | 10 |

Boundaries mutually exclusive and gap-free.

**Immutability**

Once written for a quarter, a row is **immutable**. Never recalculated mid-quarter, never retrospectively amended.

A **quarterly change** produces a new row — both rows correct for their own period. A **wrong calculation** produces a new row with `Superseded_By_Volume_Band_ID` and `Supersede_Reason` set on the prior row. These are different situations and are distinguished in the data.

**Historical RCA binding**

Every RCA records the `Volume_Band_ID` in force at generation. Re-opening a historical RCA resolves the band through that identifier, **not** the queue's current band.

**Note** — source `Volume_Category` is **not used**. Boundaries overlap at 250, leave a gap between 100 and 101, and 16.6% of rows are blank.

---

# 11B. Queue Lineage Entity

**Purpose** — Preserve analytical history across queue renames, merges and splits.

**Problem addressed** — when a `Forecast_name` changes, the engine sees a new queue and loses all history: Volume Band becomes Emerging, `HistoricalConsistency` becomes NotApplicable, year-over-year comparison is unavailable, and the 104-week sufficiency baseline resets.

**Grain** — One row per lineage relationship.

**Attributes**

- `Lineage_ID`
- `Predecessor_Forecast_Name`
- `Successor_Forecast_Name`
- `Effective_Fiscal_Week`
- `Relationship_Type` — Rename · Merge · Split
- `Volume_Allocation_Pct` — for Split, nullable
- `Notes` · `Created_By` · `Created_At`

**Relationship types**

| Type | Predecessors | Successors | History resolution |
|---|---|---|---|
| Rename | 1 | 1 | Full history inherited |
| Merge | N | 1 | Histories combined; **combination disclosed** |
| Split | 1 | N | History inherited by each; shared origin disclosed |

**Resolution**

Where lineage exists, these resolve through the chain: Volume Band basis · Data Sufficiency history depth · `HistoricalConsistency` precedent search · year-over-year and holiday-anchored comparison · Driver Relevance Gate correlation window.

**Disclosure — mandatory**

> *"History for this queue includes 187 weeks recorded under the previous name 'India Comm Client Voice' up to FY27 FW13."*

Inherited history is never presented as native. A merge combines two demand populations and a reader must be able to see that.

**Population** — manually maintained. Queue changes are business events, not data events.

**Constraint** — no cycles. Chains deeper than 3 links require review.

---

# 12. Offering Master

**Grain** — Offering.

**Attributes** — `Offering` · `Is_Out_Of_Warranty` (boolean) · `Active_Flag`

**Observed values** — `Basic` · `Pro` · `OOP` · `Premium`

**Out-of-warranty reference list** — `PON` · `OOP` · `OOW` · `Out-of-Warranty`. A reference list, **extensible, not a hard validation rule**. Drives BR-119 applicability.

**Note** — `Offering` is a **support tier**, not a product. `Basic`, `Pro`, `Premium` are perpetual service levels. They have no lifecycle and shall **never** be used as a product or lifecycle proxy.

---

# 14. Fiscal Calendar Entity

**Purpose** — The canonical time dimension. Every time-based calculation resolves through it.

**Grain** — One row per fiscal week.

**Primary Key** — `Fiscal_Week`, integer, format `YYYYWW` where `YYYY` is the **fiscal** year.

```
Example: 202718 = FW18 of FY27
```

This replaces `Fiscal_Date_Key`, which had no defined format.

**Attributes**

- `Fiscal_Week` (PK)
- `Fiscal_Year` — `FLOOR(Fiscal_Week / 100)`
- `Fiscal_Week_Number` — `MOD(Fiscal_Week, 100)`
- `Fiscal_Quarter` — 1–4, derived
- `Fiscal_Month` — 1–12, derived
- `Fiscal_Month_Label` — e.g. `M05`
- `Calendar_Month_Equivalent` — e.g. June
- `Week_Start_Date` — Saturday
- `Week_End_Date` — Friday
- `Weeks_In_Fiscal_Year` — 52 or 53 (BR-114)
- `Is_53_Week_Year` (boolean)
- `Week_Position_In_Month` — 1–5
- `Weeks_In_Month` — 4 or 5
- `Weeks_In_Quarter` — 13 or 14

**Quarter derivation**

| Fiscal_Week_Number | Quarter |
|---|---|
| 01–13 | Q1 |
| 14–26 | Q2 |
| 27–39 | Q3 |
| 40–52, or 40–53 | Q4 |

**Fiscal Month — 52-week year (4-4-5)**

| Q | Month | Weeks | Range | Calendar |
|---|---|---|---|---|
| Q1 | M01 | 4 | 01–04 | February |
| Q1 | M02 | 4 | 05–08 | March |
| Q1 | M03 | 5 | 09–13 | April |
| Q2 | M04 | 4 | 14–17 | May |
| Q2 | M05 | 4 | 18–21 | June |
| Q2 | M06 | 5 | 22–26 | July |
| Q3 | M07 | 4 | 27–30 | August |
| Q3 | M08 | 4 | 31–34 | September |
| Q3 | M09 | 5 | 35–39 | October |
| Q4 | M10 | 4 | 40–43 | November |
| Q4 | **M11** | 4 | 44–47 | **December** |
| Q4 | **M12** | 5 | 48–52 | **January** |

**Fiscal Month — 53-week year (Q4 becomes 4-5-5)**

Q1, Q2 and Q3 unchanged. Only Q4 differs.

| Q | Month | Weeks | Range | Calendar |
|---|---|---|---|---|
| Q4 | M10 | 4 | 40–43 | November |
| Q4 | **M11** | **5** | **44–48** | **December** |
| Q4 | **M12** | **5** | **49–53** | **January** |

Q4 total = 14 weeks. Fiscal year total = 53.

**Year type determination** — per BR-114: `Weeks_In_Fiscal_Year = MAX(Fiscal_Week_Number)` for that year. Classified only once ≥ 52.

**Governance**

- **Derived** from source, not authored manually
- A year's rows are **provisional** until `Weeks_In_Fiscal_Year ≥ 52`, then **final and immutable**
- The provisional-to-final transition is recorded in the Audit Trail
- A finalised year is never amended; corrections create a new calendar version

**Verified reference**

| FY | Weeks | Type | Q4 pattern |
|---|---|---|---|
| **2023** | **53** | 53-week | **4-5-5** |
| 2024–2028 | 52 | 52-week | 4-4-5 |

FY2023 M11 spans FW44–48 (02 Dec – 30 Dec), holding all five December Fridays.

---

# 15. Forecast Data Domain

# 16. Forecast Entity

**Grain** — Queue × Fiscal Week

**Primary Key** — `Forecast_ID`

**Attributes**

- `Forecast_ID`
- `Forecast_Name` (FK) · `Fiscal_Week` (FK)
- `fcst_offered` — **the sole forecast input to all adherence calculations.** May be fractional
- `fcst_handled` — explanatory variable only
- `Projection_plan_name` — plan-period label
- `Forecaster`

**Aggregation** — **FLOW.** Summed across periods.

**Removed**

| Attribute | Reason |
|---|---|
| `Forecast_Version` | No version dimension in source |
| Version mandatory constraint | Unsatisfiable |

**Known limitation — forecast versioning**

Source holds exactly one row per (`Forecast_name`, `Fiscal_Week`). There is **no forecast version dimension**. `Projection_plan_name` is a plan-period label, not a version of a given week's forecast.

Consequence: forecast-versus-forecast comparison is unavailable. Hypotheses depending on forecast lineage — manual override, version drift, trend misidentification — shall be **declared unavailable** rather than approximated.

---

# 19. Actual Data Domain

# 20. Actual Contacts Entity

**Grain** — Queue × Fiscal Week

**Primary Key** — `Actual_ID`

**Attributes**

- `Actual_ID`
- `Forecast_Name` (FK) · `Fiscal_Week` (FK)
- `Actual_Offered` — **the sole actual input to all adherence calculations**
- `Actual_Handled` — explanatory variable only
- `Holiday_Count` — derived; see below
- `Monday` … `Sunday` — binary holiday-day indicators
- `Is_Zero_Filled` (boolean) — set by BR-122
- `Is_Queue_Inactive` (boolean) — set by BR-122

**Aggregation** — **FLOW.** Summed.

**Zero versus blank**

| Value | Treatment |
|---|---|
| `0` | **Real observation.** Included in all calculations, counts and averages |
| Blank | Missing. Excluded and flagged, unless zero-filled under BR-122 |

**`Holiday_Count`** — fully derivable from the seven day indicators. **Verified identical in 100% of 138,775 rows.** Retained for convenience; **the day indicators are authoritative.**

---

# 22. Active Serviceable Units (ASU) Entity

**Purpose** — The installed base of units in market and covered under warranty. A **STOCK** measure and a primary demand driver.

> **ASU is NOT "Average Selling Units".** Version 1.0.0 carried that definition, describing a sales-velocity metric that does not exist in source data.

**Grain** — Queue × Fiscal Week. Values are **weekly averages**.

**Primary Key** — `ASU_ID`

**Attributes**

- `ASU_ID`
- `Forecast_Name` (FK) · `Fiscal_Week` (FK)
- `Planned_ASU` — base assumed when the forecast was built
- `Actual_ASU` — base that materialised
- `ASU_Adherence` — derived: `(1 − Actual_ASU / Planned_ASU) × 100`
- `Actual_ASU_Growth_Pct_YoY` — derived
- `Actual_ASU_Growth_Pct_MoM` — derived
- `Planned_ASU_Available` · `Actual_ASU_Available` (boolean)
- `ASU_Applicable` (boolean) — false for out-of-warranty offerings (BR-119)
- `ASU_Driver_Relevant` (boolean) — BR-121 gate outcome, effective-dated

**AGGREGATION CONSTRAINT — mandatory**

ASU is a **STOCK** measured as a weekly average. It shall **never** be summed.

```
Monthly ASU   = MEAN(weekly ASU over weeks with values)
Quarterly ASU = MEAN(weekly ASU over weeks with values)
```

Summing produces a meaningless figure — it counts the same physical units once per week they remained under warranty. A queue with 100,000 units under warranty for 13 weeks has an installed base of **100,000, not 1,300,000**.

This differs from `Actual_Offered` and `fcst_offered`, which are **FLOWS** and are summed. The two must never be aggregated by the same routine.

**Availability**

`Actual_ASU` blank in ~44% of rows, `Planned_ASU` in ~34%, owing to data lag. **Expected, not a defect.** Handled as **Missing** — flagged, excluded, RCA continues with reduced confidence.

**Plan versus Actual pairing**

| Pairs with | Field |
|---|---|
| `fcst_offered` (forecast) | `Planned_ASU` |
| `Actual_Offered` (actuals) | `Actual_ASU` |

Divergence between them is a **first-class hypothesis** (BR-208), not merely two features.

**Relationship to shipments**

ASU (stock) and `Final_Units` (flow) are distinct stages of one funnel and do not double-count:

```
Final_upp_units  (production plan, flow)
        ↓
Final_Units      (shipment plan, flow)
        ↓
ASU              (installed base under warranty, stock)
```

**Source** — independent feed. Not derived from shipments. Counts as an **independent evidence source** for `EvidenceStrength`.

**Measured driver relevance** — 236 of 427 queues (55%) show `|r| ≥ 0.3` against demand. The strongest driver in the dataset.

---

# 23. Forecast Adherence Entity

**Purpose** — Stores calculated adherence at each grain.

**Grain** — Queue × Period × RCA Grain

**Primary Key** — `Adherence_ID`

**Attributes**

- `Adherence_ID`
- `Forecast_Name` (FK)
- `RCA_Grain` — Weekly · Monthly · Quarterly
- `Period_Key`
- `Adherence_Value` — **signed**
- `Direction` — Under-forecast · Over-forecast · Perfect
- `Absolute_Variance` — `ABS(Actual_Offered − fcst_offered)`
- `Sum_Actual_Offered` · `Sum_Fcst_Offered`
- `Aggregation_Method` — Direct (Weekly) · Pooled (Monthly/Quarterly)
- `Is_Computable` (boolean) — false where `fcst_offered = 0` (BR-110)
- `Non_Computable_Reason`

**Formula**

```
Adherence_Value = (1 − (Actual_Offered / fcst_offered)) × 100
```

**Signed.** 0% = perfect. Negative = actual above forecast (under-forecast). Positive = actual below forecast (over-forecast).

**The signed value is stored and displayed.** `ABS()` is used only for threshold comparison, never for storage.

**Aggregation** — **RATIO.** Never averaged. Monthly and quarterly are **recomputed** from summed volumes (Pooled method).

---

# 24. Business Context Domain

# 25. Holiday Calendar Entity

**Grain** — Date × Country

**Attributes**

- `Holiday_ID`
- `Date` · `Day_Of_Week`
- `Holiday_Name_Canonical` — resolved through the synonym set
- `Holiday_Name_Source` — as supplied
- `Holiday_Type`
- `Country` (FK)
- `Fiscal_Week` · `Fiscal_Year`
- `Impact_Days_Before` — default 3, **per-holiday override**
- `Impact_Days_After` — default 3, **per-holiday override**
- `Is_Substitute_Holiday` (boolean)
- `Active_Flag`

**Impact window**

A holiday's influence extends beyond its date. Diwali may influence demand for several days either side; a bank holiday may not. **Per-holiday configuration is required.**

**VALIDATION RULE — mandatory at load**

**Reject any row where the weekday derived from `Date` does not match the `Day` column.**

Measured on CY2022+ data: 180 of 10,341 rows fail. **161 are explained by day and month being transposed** — for example a row dated `2022-01-05` with `Day = "Sunday"`, where `2022-05-01` was a Sunday and is Labour Day. The remaining 19 are substitute-holiday observances, accommodated by `Is_Substitute_Holiday`.

4,823 rows (46.6%) have day-of-month ≤ 12, where a transposition would produce a valid date and be **undetectable**. 4,655 of those agree with the `Day` column. The 8 affected countries indicate a specific source path; the feed should be verified.

> **STATUS:** the corrected Holiday master has been supplied and validated. All 161 transposed rows are corrected. A further 29 same-weekday transpositions were found and corrected — see `BR-126`.

**Date representation — mandatory**

| Attribute | Format | Example | Purpose |
|---|---|---|---|
| `Date` | **`DD-MMM-YYYY`** | `06-MAR-2025` | Human-readable, unambiguous |
| `Date_ISO` | `YYYY-MM-DD` | `2025-03-06` | Machine-readable |

`DD-MMM-YYYY` is **mandatory for holiday data** because a three-letter month cannot be confused with a day. Day/month transposition — which corrupted 29 rows in the reference master and 161 in an earlier revision — becomes structurally impossible to introduce or misread.

**SCOPE:** this format applies to **holiday data only**. `INPUT_TO_ML` and all other source feeds retain their existing formats and are **not modified**.

**New attribute — `Calendar_Basis`**

Permitted values:

- `Gregorian — fixed or rule-based`
- `Gregorian — Easter-derived`
- `Islamic`
- `Lunar / Traditional`
- `Hebrew`
- `Election-dependent`

Determines whether `BR-126` drift detection applies. Derived from the canonical holiday name at load, and overridable per holiday.

Measured distribution on the reference master of 12,197 rows:

| `Calendar_Basis` | Rows |
|---|---|
| Gregorian — fixed or rule-based | 6,628 |
| Islamic | 2,449 |
| Lunar / Traditional | 1,579 |
| Gregorian — Easter-derived | 1,464 |
| Hebrew | 54 |
| Election-dependent | 23 |

**Validation at load — BOTH required**

| Layer | Check | Catches |
|---|---|---|
| **1** | Weekday derived from `Date` matches the `Day` column | Most date corruption |
| **2** | Cross-year drift, Gregorian basis only (`BR-126`) | **Same-weekday transpositions** |

**Layer 1 alone is insufficient.** It passes on a transposition where both readings share a weekday, which was true of **all 29** transpositions found in the reference master. `01-NOV-2021` and `11-JAN-2021` are both Mondays.

**Deduplication** — `SELECT DISTINCT` on the **entire row**, not `(Date, Country, Name)`. Measured: 1,935 duplicate rows across 621 groups. Does not corrupt `Holiday_Count`, which derives from day indicators.

---

# 25A. Holiday Name Synonym Entity

**Purpose** — Resolve holiday name variants to a canonical name, enabling holiday-anchored comparison (BR-209).

**Attributes** — `Synonym_ID` · `Canonical_Name` · `Variant_Name` · `Country` (nullable — null means all countries)

**Rationale** — 657 distinct holiday names across 79 countries in CY2022+ data. Variants include "Diwali", "Deepavali", "Diwali/Deepavali".

---

# 26. Business Event Repository

**Grain** — Event

**Attributes**

- `Event_ID`
- `Event_Name` · `Event_Type` · `Event_Description`
- `Forecast_Name` (nullable — null means all queues in scope)
- `Region` · `SubRegion` · `Country` · `Offering` (nullable scoping)
- `Event_Fiscal_Week`
- `Impact_Weeks_Before` — default 2, **per-event override**
- `Impact_Weeks_After` — default 2, **per-event override**
- `Impact_Window_Rationale`
- `Created_By` · `Created_At` · `Active_Flag`

**Window**

```
Event_Fiscal_Week − Impact_Weeks_Before
    <= week <=
Event_Fiscal_Week + Impact_Weeks_After
```

Per-event configuration required because duration varies — a product launch may influence demand for five weeks, an outage for one.

**Availability — the repository is OPTIONAL** (BR-202)

| State | Treatment | Confidence |
|---|---|---|
| Not deployed or empty | **NotApplicable** | No penalty |
| Populated, no event matches | **Available** — "no event found" | No penalty |
| Populated, retrieval failed | **Missing** | Penalty |

*"No event found"* is a **result**, not a gap.

**Population** — manual via Administration Portal in Phase 1. Automated ingestion is Phase 2.

---

# 26A. Shipment Plan Entity

**Purpose** — Planned shipment/delivery volumes and their warranty coverage tiers. Shipments are a **FLOW** measure and one of the primary demand drivers.

**Grain** — Queue × Fiscal Week

**Primary Key** — `Shipment_Plan_ID`

**Attributes**

- `Shipment_Plan_ID`
- `Forecast_Name` (FK) · `Fiscal_Week` (FK)
- `Final_Units` — planned shipments; also termed Shipment
- `Final_Y1` — subset carrying Year 1 warranty
- `Final_Y2` — subset of Y1
- `Final_Y3` — subset of Y2
- `Final_Y4` — subset of Y3
- `Final_Y5` — subset of Y4
- `Final_upp_units` — Unit Production Plan, factory schedule
- `Warranty_Validation_Tier` — A · B · C (BR-112)
- `Warranty_Validation_Reason`
- `Shipment_Applicable` (boolean) — false for out-of-warranty offerings (BR-119)
- `Shipment_Driver_Relevant` (boolean) — BR-121 gate outcome, effective-dated
- `Selected_Lag_Weeks` (nullable) — empirically determined per BR-404

**Structural constraints**

```
Final_Y5 <= Final_Y4 <= Final_Y3 <= Final_Y2 <= Final_Y1 <= Final_Units
```

**MANDATORY: `Final_Y1` through `Final_Y5` are NESTED CUMULATIVE SUBSETS, not mutually exclusive categories.**

```
Final_Units != SUM(Final_Y1 .. Final_Y5)
```

Summing the Y-fields **double-counts** units and is always incorrect. Any implementation, query, report or model that sums them is defective.

Measured: `Final_Units = SUM(Y1..Y5)` in only **1%** of rows. `SUM(Y1..Y5)` averages **2.6× actual shipments**.

In the normal case `Final_Y1 = Final_Units`, because every shipped unit carries at least one year of warranty. Where `Final_Units > Final_Y1`, the difference represents units shipped **with no warranty**.

**Aggregation** — **FLOW.** Summed.

**`Final_upp_units`** — blank in **83.3%** of reference data. Handled as Missing: flagged, excluded, RCA continues. Not relied upon as a primary driver.

**Note — product dimension**

**No product identifier exists in source data.** This entity is keyed on `Forecast_Name` and `Fiscal_Week`. Product-level attribution is **not available** in this release and shall not be claimed. Any hypothesis requiring product-level granularity must be declared unavailable rather than approximated at queue level.

**Measured driver relevance** — 76 of 427 queues (18%) show `|r| ≥ 0.3` against demand. Gated by BR-121.

---

# 28. Warranty Mix (Derived View)

**Purpose** — Mutually exclusive warranty coverage bands derived from the nested values in Entity 26A.

**Nature** — **DERIVED. Not a stored entity.** Computed on demand from Shipment Plan. Holds no independent source data and shall **never** be populated directly.

**Grain** — Queue × Fiscal Week

**Derivation — by DIFFERENCING the nested values**

| Band | Derivation | Meaning |
|---|---|---|
| `No_Warranty` | `Final_Units − Final_Y1` | Shipped without warranty |
| `Warranty_1Y` | `Final_Y1 − Final_Y2` | Exactly 1 year |
| `Warranty_2Y` | `Final_Y2 − Final_Y3` | Exactly 2 years |
| `Warranty_3Y` | `Final_Y3 − Final_Y4` | Exactly 3 years |
| `Warranty_4Y` | `Final_Y4 − Final_Y5` | Exactly 4 years |
| `Warranty_5Y` | `Final_Y5` | 5 years |

**Reconciliation — mandatory**

```
No_Warranty + Warranty_1Y + Warranty_2Y + Warranty_3Y
            + Warranty_4Y + Warranty_5Y  =  Final_Units
```

**Asserted on every calculation.** Failure indicates a Tier C row or a derivation defect. **Verified: holds in 100.0% of Tier A rows.**

**Percentage representation**

```
Warranty Mix % (band n) = exclusive_band_n / Final_Units × 100
```

**DENOMINATOR IS `Final_Units`.** Never `SUM(Y1..Y5)`. Never `Final_Y1`.

Percentages are valid **only** on exclusive bands. Computing a percentage from raw `Final_Y1`–`Y5` is a defect.

**Worked example**

| Field | Value |
|---|---|
| `Final_Units` | 4,220 |
| `Final_Y1` | 4,220 |
| `Final_Y2` | 2,623 |
| `Final_Y3` | 2,562 |
| `Final_Y4` | 1,348 |
| `Final_Y5` | 143 |

| Exclusive band | Calculation | Units | Mix % |
|---|---|---|---|
| No warranty | 4,220 − 4,220 | 0 | 0.0% |
| 1-year only | 4,220 − 2,623 | 1,597 | 37.8% |
| 2-year only | 2,623 − 2,562 | 61 | 1.4% |
| 3-year only | 2,562 − 1,348 | 1,214 | 28.8% |
| 4-year only | 1,348 − 143 | 1,205 | 28.6% |
| 5-year | — | 143 | 3.4% |
| **Total** | | **4,220** ✓ | **100.0%** |

`SUM(Y1..Y5)` = 10,896 — meaningless, and 2.6× actual shipment volume.

**Availability** — returned only where `Warranty_Validation_Tier` is A or B. Tier C returns **unavailable** with a stated reason, never an empty object.

**Removed attributes**

| Attribute | Reason |
|---|---|
| `Out_of_Warranty` | **No source.** Conflated two concepts: (a) units shipped without warranty — now the derived `No_Warranty` band; (b) out-of-warranty support demand — an **Offering** attribute (`PON`/`OOP`/`OOW`) |
| `Product_ID` · `Geography_ID` | No source exists |

---

# 33A. Business Observation Repository

**Purpose** — Analyst knowledge that cannot be derived from data.

**Grain** — Observation

**Attributes**

- `Observation_ID`
- `Source_Type` — AnalystAnnotation · ManualEntry
- `RCA_Case_ID` (nullable)
- `Forecast_Name` · `Fiscal_Week`
- `Annotation_Type` — Agree · Disagree · AdditionalContext
- `Observation_Text`
- `Author` · `Created_At`
- `Provenance_Weight` — 1.00

**Retrieval**

Retrieved where the observation references the same `Forecast_Name`, or the same `SubRegion` and `Offering`, and a related root cause category.

**Exempt from the BR-203 confidence eligibility gate.** That gate governs machine-generated conclusions, whose confidence is self-assessed. A human annotation carries external verification and is eligible regardless of the confidence of the RCA it was recorded against.

**Display** — presented as normal narrative content with a provenance control revealing source, author, why retrieved and impact. Never as a raw system citation.

---

# 30. Statistical Repository Domain

# 31. Statistical Analysis Entity

**Grain** — One row per statistical analysis within an investigation.

**Attributes**

- `Statistical_Analysis_ID`
- `RCA_Case_ID` (FK) — **mandatory**
- `Hypothesis_ID` (FK)
- `Metric_Selected` · `Selection_Reason`
- `Executed_At` · `Execution_Status`
- `Suppression_Reason` (nullable)

**Constraint** — every statistical result links to an investigation. **No statistical calculation may exist outside one** (BR-402, and enforced in the API by a mandatory `investigationId`).

**Suppression** — where a selected metric cannot execute (insufficient coverage, Tier C warranty, Emerging queue), it is recorded as **suppressed** with a reason, never silently omitted. A suppressed metric is distinguishable from one that ran and found nothing.

---

# 32. Statistical Metric Result Entity

**Attributes** — `Metric_Result_ID` · `Statistical_Analysis_ID` (FK) · `Metric_Name` · `Metric_Value` · `Interpretation` · `Evidence_Strength` · `Lag_Applied` (nullable) · `Baseline_Used`

**`Baseline_Used`** — mandatory where a comparison was made. States whether calendar-anchored or holiday-anchored (BR-209), and which period.

---

# 33–38. Trend · Seasonality · Drift · Momentum · Correlation · Outlier Entities

Structure unchanged from Version 1.0.0. Each carries `Statistical_Analysis_ID` (FK), its computed values, interpretation and evidence strength.

**Additions to all six**

- `Lag_Applied` (nullable) — where a flow driver was lagged, the empirically selected lag
- `Driver_Relevance_Correlation` (nullable) — the BR-121 gate value for the driver tested

---

# 39. Machine Learning Explainability Domain

# 40. SHAP Entity

**Attributes** — `SHAP_ID` · `Statistical_Analysis_ID` (FK) · `Feature_Name` · `SHAP_Value` · `Business_Translation` · `Feature_Availability`

**Feature construction constraints**

1. Warranty features shall be **exclusive bands**. Entering nested `Final_Y1`–`Y5` values as separate features produces uninterpretable attribution, because the features are subsets of one another.
2. Features failing the BR-121 relevance gate are **excluded** as NotApplicable.
3. Where BR-112 Tier is C, warranty and shipment features are marked **unavailable** for that observation and shall not be imputed.

`Feature_Availability` — Available · Missing · NotApplicable. Any attribution output states which features were unavailable and for how many periods.

# 41. Feature Importance Entity

Structure unchanged. Same three constraints apply.

---

# 42. Investigation Domain

# 43. RCA Case Entity

**Purpose** — One RCA investigation at one grain for one queue and one fiscal period.

**Grain** — Queue × Fiscal Period × RCA Grain

A queue may hold up to three concurrent RCAs for overlapping time: one Weekly, one Monthly, one Quarterly. These are **independent investigations** and shall never be merged.

**Primary Key** — `RCA_Case_ID`

**Natural Key** — (`Forecast_Name`, `RCA_Grain`, `Period_Key`)

**Foreign Keys** — `Forecast_Name` → Queue Master · `Period_Key` → Fiscal Calendar · `Volume_Band_ID` → Queue Volume Band

**Attributes**

- `RCA_Case_ID`
- `Forecast_Name` · `RCA_Grain` · `Period_Key`
- `Fiscal_Year` · `Fiscal_Quarter` · `Fiscal_Month` · `Fiscal_Week`
- `Forecast_Adherence` — signed
- `Absolute_Variance`
- `Aggregation_Method` — Direct · Pooled
- `Volume_Band_ID`
- `Generation_Mode` — Batch · OnDemand · Manual
- `Generation_Threshold_Met` (boolean)
- `Within_Generation_Window` (boolean, evaluated at query time)
- `Case_Status`
- `Period_Coverage_ID` (FK)
- `Investigation_Start` · `Investigation_End`
- `Final_Confidence` · `Final_Root_Cause`
- `Incomplete_Stages` (list, nullable)
- `Termination_Reason` — Timeout · LLMFailure · ResourceLimit · Error (nullable)
- `Superseded_By_Case_ID` (nullable)
- `Input_Fingerprint` · `Input_Row_Count` · `Input_Fingerprint_Computed_At`

**`Period_Key` resolution**

| RCA_Grain | Format | Example |
|---|---|---|
| Weekly | `YYYYWW` | 202718 |
| Monthly | `YYYYMM` (fiscal) | 202705 |
| Quarterly | `YYYYQ` | 20272 |

**`Case_Status` — consolidated**

Version 1.0.0 carried both `Investigation_Status` and `RCA_Status` with no stated difference. **Merged into one.**

| Value | Meaning | Published |
|---|---|---|
| `Queued` | Enqueued, not started | No |
| `Running` | In progress | No |
| `Completed` | Concluded with a root cause | Yes |
| `Inconclusive` | Concluded without a defensible root cause | Yes |
| **`Incomplete`** | Timed out or narrative failed mid-investigation | **Yes** — banner, stages listed, confidence capped Low (Gate 7), summary states "provisional" |
| `Escalated` | Requires human review | Yes |
| `Superseded` | Recomputed with additional weeks | No |
| **`Failed`** | Unrecoverable error | **No** — reason in audit only |

**Removed values** — `Awaiting Data` (no RCA exists without actuals, so nothing awaits) and `Archived` (retention, not investigation state).

**Recomputation and supersession**

Monthly and Quarterly RCAs are recomputed as additional weeks of actuals arrive (BR-116). A recomputation:

- creates a **new** RCA Case row
- sets `Superseded_By_Case_ID` on the prior row and its status to `Superseded`
- **never** overwrites the prior row

This preserves the full sequence of conclusions as a period filled in, which is itself auditable evidence.

---

# 43A. Period Coverage Entity

**Purpose** — Records which fiscal weeks contributed actuals to an aggregated RCA. Drives the Timeline callout and coverage caps.

**Grain** — One row per RCA Case at Monthly or Quarterly grain.

**Attributes**

- `Period_Coverage_ID`
- `RCA_Case_ID` (FK)
- `Weeks_In_Period` — 4, 5, 13 or 14
- `Weeks_With_Actuals`
- `First_Week_With_Actuals` · `Last_Week_With_Actuals`
- `Missing_Weeks` (list)
- `Non_Computable_Weeks` (list) — excluded under BR-110
- `Zero_Filled_Weeks` (list) — set under BR-122
- `Inactive_Weeks` (list) — set under BR-122
- `Coverage_Ratio`
- `Is_Complete` (boolean)
- `Timeline_Label` — e.g. `Timeline: FW18`

**Rules**

1. Weeks with blank `Actual_Offered` beyond the zero-fill limit are excluded and listed in `Missing_Weeks`.
2. Weeks excluded under BR-110 are listed **separately** in `Non_Computable_Weeks`. A data defect, not an availability gap, and reported distinctly.
3. `Coverage_Ratio` drives Gates 3a and 3b.
4. `Timeline_Label` is **mandatory** on every partial-period output.

---

# 43B. RCA Rerun Request Entity

**Purpose** — Govern re-runs so repeated regeneration cannot be used to obtain a preferred conclusion (BR-124).

**Attributes**

- `Rerun_Request_ID`
- `Original_RCA_Case_ID` · `New_RCA_Case_ID` (nullable)
- `Requested_By` · `Requested_At`
- `Data_Changed` (boolean)
- `Fingerprint_Before` · `Fingerprint_After`
- `Reason` — **mandatory where `Data_Changed = false`**
- `Is_Governance_Exception` (boolean)
- `Administrator_Reviewed` (boolean) · `Administrator_Notes`

---

# 44. Hypothesis Entity

**Attributes**

- `Hypothesis_ID`
- `RCA_Case_ID` (FK)
- `Hypothesis_Catalogue_ID` (FK) — the catalogue entry generated from
- `Hypothesis_Category`
- `Hypothesis_Name`
- `Hypothesis_State`
- `State_Reason` — **mandatory** for Rejected, Suppressed and NotApplicable
- `Evidence_Strength`
- `Hypothesis_Confidence`

**`Hypothesis_State` — four distinct values**

| State | Meaning | Confidence effect |
|---|---|---|
| `Accepted` | Tested, supported, selected | — |
| `Rejected` | Tested, evidence did not support it | None |
| **`Suppressed`** | **Could not be tested** — data invalid or unavailable | Penalty applies |
| **`NotApplicable`** | Never relevant to this queue | **No penalty** |

**These four must never share a presentation.** If Suppressed and Rejected look identical, a reader concludes *"warranty was ruled out"* when the truth is *"warranty could not be checked"* — opposite actions.

Measured relevance: 32% of Basic-offering queue-weeks are Tier C, and warranty tracks demand in only 18% of queues. Both Suppressed and NotApplicable are **common states**, not edge cases.

**Removed** — `Secondary Driver` as a state value. Secondary driver is an orthogonal concept recorded on the Root Cause entity.

---

# 45. Evidence Entity

**Attributes**

- `Evidence_ID`
- `RCA_Case_ID` · `Hypothesis_ID` (FK)
- `Evidence_Type` — Business · Statistical · Historical · ML · **Annotation**
- `Evidence_Source_Family` — drives independence weighting
- `Supporting_Flag` (boolean) — false indicates contradictory evidence
- `Evidence_Strength` — five-level scale
- `Independence_Weight`
- `Evidence_Description`
- `Provenance_Weight` — 1.00 for annotations and business rules

**Note** — `Contradictory` is **not** an evidence *type*. It is the `Supporting_Flag` dimension. Version 1.0.0 of the System Architecture conflated the two.

**Evidence strength scale** — Very Strong 1.0 · Strong 0.8 · Moderate 0.6 · Weak 0.4 · Very Weak 0.2. **Five levels, canonical.**

---

# 46. Root Cause Entity

**Attributes**

- `Root_Cause_ID`
- `RCA_Case_ID` (FK)
- `Hypothesis_ID` (FK)
- `Root_Cause_Category` · `Root_Cause_Statement`
- `Decision_Status` — Accepted · AcceptedWithCaveats · Inconclusive · Escalated
- `Is_Secondary_Driver` (boolean)
- `Reasoning_Depth_Reached`
- `Recursive_Termination_Reason`

---

# 47. Cross-Examination Entity

**Attributes**

- `Cross_Examination_ID`
- `RCA_Case_ID` · `Hypothesis_ID` (FK)
- `Iteration_Number` — 1 to configured maximum (BR-117)
- `Question_Number` — within the iteration
- `Question` · `Question_Semantic_Key`
- `AI_Response`
- `Supporting_Evidence` · `Contradictory_Evidence`
- `Evidence_Was_New` (boolean) — drives BR-117 condition 3
- `Weakness_Detected` (boolean)
- `Validation_Result` · `Confidence_Impact`

**`Question_Semantic_Key`** — drawn from the fixed Challenge Question Catalogue. Because keys are finite and predetermined, deduplication is **exact** — no paraphrase risk.

---

# 47A. Cross-Examination Iteration Entity

**Attributes** — `Iteration_ID` · `RCA_Case_ID` · `Iteration_Number` · `Questions_Asked` · `Evidence_Items_Retrieved` · `Evidence_Items_New` · `Weakness_Detected` · `Iteration_Outcome` (Continue · Terminate)

---

# 47B. Cross-Examination Result Entity

**Attributes** — `RCA_Case_ID` · `Total_Iterations` · `Terminating_Condition` (1–5, BR-117) · `Final_Outcome` (Accepted · AcceptedWithCaveats · Inconclusive · Reject) · `Gate_7_Applies` (true where condition ∈ {2, 3, 5})

**Termination is BOUNDED.** Version 1.0.0 specified two subjective conditions — *"no further meaningful questions remain"* and *"sufficiently validated"* — which were neither mechanically testable nor recorded.

---

# 48. Confidence Entity

**Purpose** — Stores the confidence calculation, decomposed to dimension level so any score can be explained and reproduced.

**Primary Key** — `Confidence_ID`

**Header attributes**

- `Confidence_ID` · `RCA_Case_ID` (FK)
- `Raw_Score` — aggregated, before caps
- `Capped_Score` — after caps
- `Confidence_Level` — Very High · High · Medium · Low · Very Low
- `Binding_Cap` (nullable)
- `Applicable_Weight_Total`
- `Dimensions_Applicable` · `Dimensions_Available` · `Dimensions_Missing` · `Dimensions_Not_Applicable`
- `Weights_Version` (FK)
- `Calculated_At`

**Five levels, canonical.** PRD Version 1.0 specified three and is corrected.

**Removed attributes**

| Attribute | Reason |
|---|---|
| `Statistical_Confidence` · `Business_Confidence` · `Data_Quality_Confidence` · `Explainability_Confidence` | These four did not correspond to the eight dimensions the engine computes. `Explainability_Confidence` appeared in no other document. `HistoricalConsistency`, `ContextCompleteness`, `ContradictoryEvidence` and `ModelAgreement` had nowhere to be persisted |
| `Confidence_Score` · `Overall_Confidence` | Replaced by `Raw_Score` and `Capped_Score`, distinguishing the aggregate from the capped result |
| `Confidence_Category` | Renamed `Confidence_Level` |

**Reproducibility requirement**

`Weights_Version` is **mandatory**. Confidence weights are configurable; without the version in force at calculation time, a historical score cannot be reproduced.

---

# 48A. Confidence Dimension Entity

One row per dimension per calculation. **Always eight rows.**

**Attributes** — `Confidence_Dimension_ID` · `Confidence_ID` (FK) · `Dimension_Name` · `Availability` (Available · Missing · NotApplicable) · `Score` (null where NotApplicable) · `Weight` · `Weighted_Contribution` · `Reason` (mandatory where not Available) · `Component_Detail` (JSON)

**Permitted `Dimension_Name` values**

`DataSufficiency` · `StatisticalAgreement` · `HistoricalConsistency` · `ContextCompleteness` · `EvidenceStrength` · `ContradictoryEvidence` · `ModelAgreement` · `BusinessRuleValidation`

---

# 48B. Confidence Cap Entity

One row per cap evaluated. **All eight gates recorded, met or not.**

**Attributes** — `Confidence_Cap_ID` · `Confidence_ID` (FK) · `Gate_Number` (1–8) · `Gate_Name` · `Condition_Met` (boolean) · `Cap_Level` · `Is_Binding` (true for the single lowest cap met)

---

# 49. Executive Decision Card Entity

**Attributes**

- `Decision_Card_ID` · `RCA_Case_ID` (FK)
- `Card_Version` — increments on recomputation
- `Executive_Summary` · `Root_Cause_Statement`
- `Forecast_Adherence` — signed · `Direction` · `Absolute_Variance`
- `Confidence_Level` · `Binding_Cap`
- `RCA_Grain` · `Period` · `Volume_Band`
- `Timeline_Label` (nullable)
- `Markers` — Major Deviation · Repeated Miss · Manually Requested · Superseded · Incomplete · Governance Exception
- `Published_At`

**Version history** — cards are versioned, never overwritten. Prior versions retained.

---

# 50. Recommendation Entity

**Attributes**

- `Recommendation_ID` · `RCA_Case_ID` · `Root_Cause_ID` (FK)
- `Recommendation_Text`
- `Priority` — Critical · High · Medium · Low, **derived** per BR-702
- `Expected_Impact_Qualitative`
- `Evidence_Reference`

**Maximum 3 per RCA.**

**Removed** — `Suggested_Owner`. All recommendations route to the Demand / Forecast Team, stated once at document level. A field with one possible value carries no information.

**Prohibition** — no quantified benefit. Impact is qualitative only.

---

# 60. LLM Invocation Entity

**Purpose** — Records every LLM invocation for audit and reproducibility.

**Grain** — One row per invocation. Normally one per RCA, two where a retry occurred.

**Attributes**

- `LLM_Invocation_ID` · `RCA_Case_ID` (FK)
- `Invocation_Sequence` — 1 = initial, 2 = retry
- `Model_Identifier` · `Model_Version` — exact pinned version
- `Prompt_Version` — semantic version
- `Temperature` · `Top_P` · `Seed` · `Max_Output_Tokens`
- `Prompt_Full` — complete prompt as sent
- `Response_Full` — complete response as received
- `Validation_Outcome` — Passed · RejectedSchema · RejectedContent · Timeout · Error
- `Validation_Failure_Detail`
- `Input_Tokens` · `Output_Tokens` · `Latency_Ms`
- `Invoked_At`

**Retention** — prompt and response stored **in full**. A truncated record cannot reproduce the narrative.

**Constraint** — an RCA marked `Completed` shall have at least one invocation with `Validation_Outcome = Passed`, **or** be marked `Incomplete` with the failure recorded. There is no third state.

**Note** — there is exactly **one** LLM invocation point in the architecture: the Executive Narrative Engine. Hypotheses and cross-examination questions come from deterministic catalogues.

---

# 51. Audit Repository

# 52. Audit Log Entity

**Attributes** — `Audit_ID` · `RCA_Case_ID` · `Event_Type` · `Rule_ID` · `Rule_Version` · `Inputs_Evaluated` · `Outcome` · `Configuration_Version` · `Timestamp` · `User_ID`

**Constraint** — audit information shall **never** be deleted.

**Reproducibility set** — every RCA shall be reproducible from its audit record alone, including: `Input_Fingerprint` · `Weights_Version` · `Hypothesis_Catalogue_Version` · `Question_Catalogue_Version` · `Prompt_Version` · `Model_Version` · `Seed` · `Business_Rules_Version`.

---

# 53. Configuration Domain

# 54. Business Rules Entity

**Attributes** — `Rule_ID` · `Rule_Name` · `Rule_Category` · `Condition` · `Threshold_Value` · `Default_Value` · `Is_Configurable` (boolean) · `Priority` · `Version` · `Effective_From` · `Approved_By` · `Approved_At` · `Active_Flag`

**`Is_Configurable = false`** for the RCA Generation Threshold (±5%) and LLM temperature (0). These shall not be exposed for configuration.

**Segregation of duties** — rule authoring and rule approval shall be separate roles.

# 55. Statistical Configuration Entity

**Attributes** — `Config_ID` · `Metric_Name` · `Enabled_Flag` · `Parameter_Set` · `Applicable_Hypothesis_Categories` · `Version`

# 56. Explainability Configuration Entity

**Attributes** — `Config_ID` · `Persona` · `Visible_Components` · `Technical_View_Enabled` · `Version`

**Constraint** — the Confidence Panel is visible to **every** persona and cannot be disabled or collapsed.

# 57. User Entity

**Attributes** — `User_ID` · `User_Name` · `Persona` · `Role` · `Forecaster_Filter_Granted` (boolean) · `Active_Flag`

**Deactivation, not deletion.** `DELETE` on a user is a deactivation.

---

# 58. Logical Relationship Summary

```
Queue Master ──1:N── Queue Volume Band (effective-dated)
Queue Master ──1:N── Queue Lineage
Queue Master ──1:N── Forecast Entity
Queue Master ──1:N── Actual Contacts Entity
Queue Master ──1:N── ASU Entity
Queue Master ──1:N── Shipment Plan Entity
Fiscal Calendar ──1:N── all fact entities

Forecast + Actual ──> Forecast Adherence (derived)
Shipment Plan ──> Warranty Mix (derived view)

Forecast Adherence ──1:N── RCA Case (one per grain)
RCA Case ──1:1── Period Coverage
RCA Case ──1:N── Hypothesis
Hypothesis ──1:N── Evidence
Hypothesis ──1:N── Statistical Analysis
Statistical Analysis ──1:N── Metric Result
RCA Case ──1:N── Cross-Examination ──> Iteration ──> Result
RCA Case ──1:1── Confidence ──1:8── Confidence Dimension
Confidence ──1:8── Confidence Cap
RCA Case ──1:1── Root Cause
RCA Case ──1:N── Recommendation (max 3)
RCA Case ──1:N── Decision Card (versioned)
RCA Case ──1:N── LLM Invocation
RCA Case ──1:N── Rerun Request
RCA Case ──1:N── Audit Log
```

**No entity exists for aggregate Levels 1 and 2.** They are computed views over child RCAs and stored volumes (BR-125). Persisting them would create a second source of truth for figures derivable from queue-level data.

---

# 59. Aggregation Rules by Measure Type

| Measure type | Fields | Monthly / Quarterly |
|---|---|---|
| **FLOW** | `Actual_Offered` · `fcst_offered` · `Actual_Handled` · `fcst_handled` · `Final_Units` · `Final_Y1`–`Y5` · `Final_upp_units` · `Holiday_Count` | **SUM** |
| **STOCK** | `Planned_ASU` · `Actual_ASU` | **MEAN** |
| **RATIO** | Forecast Adherence · ASU Adherence · warranty mix % | **RECOMPUTE** from aggregated inputs |

Ratio measures shall **never** be averaged. Summing a stock **double-counts**.

---

# 60A. Future Schema Extensions

FUTURE SCOPE. Not implemented in Phase 1.

- Product Master, Product Age, Installed Base by product — require a product identifier absent from source
- Forecast Version and Forecast Snapshot — require a version dimension absent from source
- Analyst Feedback learning store — annotations are captured (33A) but not consumed autonomously
- Vector embedding store for semantic similarity
- Operational metadata — AHT, ASA, occupancy, shrinkage, staffing. Capacity and RTA constructs, out of Phase 1 scope, no source data
- Marketing activity repository

---

# 61. Guiding Principles

- Every entity states its grain.
- No foreign key references a dimension absent from source data.
- Derived values are derived, not stored twice.
- Stock and flow are never aggregated by the same routine.
- Classifications that change over time are effective-dated.
- Completed investigations are immutable; corrections supersede.
- Every investigation is reproducible from its audit record.
- Missing, NotApplicable and zero are three different states and are never conflated.

---

# End of Document
