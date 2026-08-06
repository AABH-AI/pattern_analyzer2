# FC_RCA_Definitions_and_Formulas

**Project:** Forecast RCA Studio (FC_RCA)
**Document Type:** Definitions & Formulas — Master Reference
**Version:** 2.0
**Supersedes:** Version 1.0
**Status:** Approved — Authoritative
**Last Updated:** 30 July 2026

---

## Document Control

| Item | Detail |
|---|---|
| **Purpose** | Single authoritative source for all business definitions, field semantics, formulas, calendar rules and data-handling rules used by Forecast RCA Studio. |
| **Scope** | Forecast Adherence metrics; fiscal calendar; RCA trigger and display model; volume banding; geography hierarchy; demand-driver model; warranty structure and validation; field definitions; data-handling rules. |
| **Out of Scope** | System architecture, API contracts, prompt specifications, statistical method selection, UI layout. These are governed by their own documents. |
| **Authority** | Where any other project document conflicts with this one on a definition, formula, calendar rule or field meaning, **this document prevails**. All conflicts must be raised and the other document corrected. |
| **Assumptions** | (1) `INPUT_TO_ML.xlsx` is representative of production input grain and quality. (2) Grain is one row per `Forecast_name` × `Fiscal_Week` — verified: zero duplicates across 138,775 rows. (3) `Forecast_name` is the unique queue identifier. |
| **Dependencies** | Source dataset (`INPUT_TO_ML.xlsx` equivalent feed); global holiday master; ingestion layer implementing the rules in Section 9. |
| **Acceptance Criteria** | (1) Every formula reproduces the stated worked examples exactly. (2) Fiscal calendar derivation reproduces the reference tables in Section 3.6. (3) Warranty exclusive bands reconcile to `Final_Units` on all Tier A rows. (4) No downstream document contains a conflicting definition. |
| **Related Documents** | `FC_RCA_Business_Rules.md` · `FC_RCA_Data_Dictionary_and_Schema.md` · `FC_RCA_Statistical_Framework.md` · `FC_RCA_RCA_Methodology.md` · `FC_RCA_Output_and_Decision_Cards.md` · `FC_RCA_Explainability_Framework.md` · `FC_RCA_Product_Requirements_Document__PRD_.md` · `FC_RCA_System_Architecture.md` · `FC_RCA_Master_Build_Specification__MBS_.md` |

---

# 1. Scope of Measurement

| Item | Definition |
|---|---|
| **Grain** | One row per **Queue × Fiscal Week** |
| **Queue identifier** | `Forecast_name` |
| **Actual volume** | `Actual_Offered` — used for **all** actual-volume calculations without exception |
| **Forecast volume** | `fcst_offered` — used for **all** forecast-volume calculations without exception |
| **All other fields** | Explanatory variables used during Root Cause Analysis. They never enter the adherence calculation. |

`Actual_Handled` and `fcst_handled` are **not** used in adherence or accuracy. They are explanatory variables only.

---

# 2. Forecast Calculations

## 2.1 Forecast Adherence — Primary KPI

### Definition

Forecast Adherence is the **signed percentage deviation** of actual offered volume from forecast offered volume.

### Formula

```
Forecast Adherence % = (1 − (Actual_Offered / fcst_offered)) × 100
```

**Excel**
```excel
=IF(Actual_Offered="","",(1-(Actual_Offered/fcst_offered))*100)
```

**Python**
```python
"" if actual_offered == "" else (1 - (actual_offered / fcst_offered)) * 100
```

### Interpretation

| Value | Meaning | Business reading |
|---|---|---|
| **0%** | Actual equals forecast | Perfect adherence |
| **Negative** | Actual **above** forecast | **Under-forecast** — demand exceeded plan |
| **Positive** | Actual **below** forecast | **Over-forecast** — demand fell short of plan |

The sign is diagnostically essential and must never be discarded. Under-forecast and over-forecast have entirely different root causes and different business consequences. **Absolute value is used only for threshold comparison, never for storage or display.**

### Worked examples

| Forecast | Actual | Calculation | Adherence | Reading |
|---|---|---|---|---|
| 1,000 | 1,000 | (1 − 1.000) × 100 | **0.0%** | Perfect |
| 1,000 | 1,120 | (1 − 1.120) × 100 | **−12.0%** | Under-forecast by 12% |
| 1,000 | 880 | (1 − 0.880) × 100 | **+12.0%** | Over-forecast by 12% |
| 1,000 | 2,000 | (1 − 2.000) × 100 | **−100.0%** | Actual double forecast |
| 1,000 | 0 | (1 − 0.000) × 100 | **+100.0%** | No actual volume |

### Edge cases

| Condition | Behaviour |
|---|---|
| `Actual_Offered` is blank | Adherence is **blank**. No RCA. Row excluded from all aggregates. |
| `Actual_Offered` = 0 | **Valid observation.** Adherence = +100%. Included. |
| `fcst_offered` = 0 | Adherence is **undefined** (division by zero). Row **excluded** from calculation and aggregates, **flagged** in the Data Availability Callout. See §9.3. |
| `fcst_offered` is blank | Adherence is **blank**. Row excluded and flagged. |
| Either value negative | **Rejected** at validation. Negative volumes are invalid. |

> **Note — applied by extension.** The `fcst_offered = 0` treatment applies the approved missing-data principle (§9.1: *flag, highlight, exclude, continue*) to a non-computable denominator. 50 such rows exist in the reference dataset. Flagged for confirmation.

## 2.2 Forecast Accuracy — Reference Metric

### Definition

The traditional accuracy ratio, retained for reference and comparison only. **It is not used to trigger RCA.**

### Formula

```
Forecast Accuracy % = (Actual_Offered / fcst_offered) × 100
```

**Excel**
```excel
=(Actual_Offered / fcst_offered) * 100
```

**Python**
```python
(actual_offered / fcst_offered) * 100
```

### Interpretation

100% = perfect. Above 100% = actual exceeded forecast. Below 100% = actual fell short.

### Relationship to Adherence

```
Forecast Adherence % = 100 − Forecast Accuracy %
```

## 2.3 Aggregation — Monthly and Quarterly

Monthly and quarterly adherence use the **Pooled** method. Weekly adherence values are **never averaged**.

### Formula

```
Aggregated Adherence % = (1 − (SUM(Actual_Offered) / SUM(fcst_offered))) × 100
```

Summed across all fiscal weeks in the period **that have actuals available** (§4.5).

### Why Pooled

| | Pooled | Average of weekly |
|---|---|---|
| Weighting | Volume-weighted — high-volume weeks carry proportionate influence | Every week weighted equally regardless of size |
| Stability | Stable | A single low-volume, high-percentage week can dominate |
| Business reconciliation | Matches how the business totals a period | Does not reconcile to period totals |

Measured on the reference dataset, the two methods diverge by up to **53 percentage points** at the 99th percentile, and disagree on breach status for **15 queues** in a single quarter. Pooled is canonical.

### Worked example

FY27 M05 (FW18–21), one queue:

| FW | Forecast | Actual | Weekly adherence |
|---|---|---|---|
| 18 | 1,000 | 1,100 | −10.0% |
| 19 | 1,200 | 1,150 | +4.2% |
| 20 | 900 | 1,080 | −20.0% |
| 21 | 1,100 | 1,000 | +9.1% |
| **Total** | **4,200** | **4,330** | |

**Pooled:** `(1 − 4,330 / 4,200) × 100 = −3.1%`
Average of weekly: `−4.2%` ← **not used**

---

# 3. Fiscal Calendar

## 3.1 Format

| Item | Rule |
|---|---|
| **Field** | `Fiscal_Week` |
| **Format** | `YYYYWW` — integer |
| **`YYYY`** | **Fiscal** year (not calendar year) |
| **`WW`** | Fiscal week number, 01–52 or 01–53 |
| **Example** | `202718` = **FW18 of FY27** |
| **Fiscal year start** | First week of **February** |
| **Week boundaries** | Week begins **Saturday**; **Friday** is the final working day |
| **`Week_Ending`** | Calendar date of that Friday |

**Derivations**
```
Fiscal_Year = FLOOR(Fiscal_Week / 100)
Fiscal_Week_Number = MOD(Fiscal_Week, 100)
```

Verified: `Week_Ending` falls on a Friday in 100% of the reference dataset (138,775 rows).

## 3.2 Quarters

| Quarter | Weeks (52-week year) | Weeks (53-week year) |
|---|---|---|
| Q1 | FW01–13 | FW01–13 |
| Q2 | FW14–26 | FW14–26 |
| Q3 | FW27–39 | FW27–39 |
| **Q4** | **FW40–52** (13 weeks) | **FW40–53** (14 weeks) |

## 3.3 Fiscal Months — 4-4-5 Pattern

Each quarter divides into three months on a **4-4-5** pattern.

| Quarter | Month | Weeks | FW range | Calendar month |
|---|---|---|---|---|
| Q1 | M01 | 4 | FW01–04 | February |
| Q1 | M02 | 4 | FW05–08 | March |
| Q1 | M03 | 5 | FW09–13 | April |
| Q2 | M04 | 4 | FW14–17 | May |
| Q2 | M05 | 4 | FW18–21 | June |
| Q2 | M06 | 5 | FW22–26 | July |
| Q3 | M07 | 4 | FW27–30 | August |
| Q3 | M08 | 4 | FW31–34 | September |
| Q3 | M09 | 5 | FW35–39 | October |
| Q4 | M10 | 4 | FW40–43 | November |
| Q4 | **M11** | 4 | FW44–47 | **December** |
| Q4 | **M12** | 5 | FW48–52 | **January** |

## 3.4 53-Week Fiscal Years — Q4 Becomes 4-5-5

In a 53-week fiscal year, the additional week is absorbed into **Q4**, which becomes **4-5-5**. Q1, Q2 and Q3 are unchanged.

| Quarter | Month | Weeks | FW range | Calendar month |
|---|---|---|---|---|
| Q4 | M10 | 4 | FW40–43 | November |
| Q4 | **M11** | **5** | **FW44–48** | **December** |
| Q4 | **M12** | **5** | **FW49–53** | **January** |

Q4 total = **14 weeks**. Fiscal year total = **53 weeks**.

## 3.5 53-Week Year Detection

The calendar is **derived from the data**, not computed from an anchor date.

```
weeks_in_FY = MAX(Fiscal_Week_Number) observed for that Fiscal_Year
```

| Condition | Classification |
|---|---|
| `weeks_in_FY = 53` | **53-week year** — Q4 uses 4-5-5 |
| `weeks_in_FY = 52` | **52-week year** — all quarters use 4-4-5 |
| `weeks_in_FY < 52` | **In progress** — not yet classified. Month mapping applied only to weeks present |

`MAX()` is used rather than `COUNT(DISTINCT)` because a fiscal year may be partially represented in the dataset. In the reference data FY2022 contains only FW49–52, so `COUNT(DISTINCT)` would return 4 and misclassify it, while `MAX()` correctly returns 52.

## 3.6 Verified Reference — FY2023 (53 weeks)

FY2023 is the only 53-week year in the reference dataset. Applying §3.4:

| Month | Weeks | FW range | Week_Ending dates |
|---|---|---|---|
| M10 | 4 | FW40–43 | 04 Nov → 25 Nov |
| **M11** | **5** | **FW44–48** | **02 Dec → 30 Dec** — all five December Fridays |
| **M12** | **5** | **FW49–53** | 06 Jan → 03 Feb |

Reference week counts by fiscal year:

| FY | Weeks | Pattern |
|---|---|---|
| 2022 | 52 | 4-4-5 (partial data — FW49–52 only) |
| **2023** | **53** | **Q4 = 4-5-5** |
| 2024 | 52 | 4-4-5 |
| 2025 | 52 | 4-4-5 |
| 2026 | 52 | 4-4-5 |
| 2027 | 52 | 4-4-5 |
| 2028 | 52 | 4-4-5 |
| 2029 | In progress | — |

---

# 4. RCA Trigger and Display Model

Three independent controls. **They must never be conflated.**

| Control | Value | Governs | User-changeable |
|---|---|---|---|
| **RCA Generation Threshold** | **±5%** — fixed | Whether an RCA exists | **No** |
| **Adherence Display Filter** | Default ±10% | What appears in the worklist | Yes |
| **Materiality Floor** | Volume-band scaled | What appears in the worklist | Toggle only |

## 4.1 RCA Generation Threshold — ±5%, Fixed

```
Generate RCA WHERE ABS(Forecast Adherence) > 5
```

Fixed at the system level. Not configurable, not exposed in the interface, never affected by any filter.

## 4.2 Generation Strategy

| Adherence | Strategy |
|---|---|
| `ABS(adherence) > 10%` | **Pre-generated** in batch — the default view |
| `5% < ABS(adherence) ≤ 10%` | **Generated on first open**, then cached |
| `ABS(adherence) ≤ 5%` | **No RCA** |

Lazy generation for the ±5–10% band reduces up-front compute by approximately **18%** of RCA scope with no change to the analyst experience, since those cases are only reachable by lowering the display filter.

Once generated, an RCA is **immutable and cached**. Reopening never regenerates.

## 4.3 Adherence Display Filter

| Item | Rule |
|---|---|
| Options | **±5% · ±10% · ±15% · ±20% · ±25% · ±30%** |
| Default | **±10%** |
| Selection | **Single-select** — a symmetric band cannot be multi-selected |
| Test | `ABS(Forecast Adherence) > selected threshold` |
| Effect on RCA | **None.** Display only |

The filter minimum (±5%) equals the generation threshold, so every row reachable by the filter always has an RCA available.

**The filter never triggers, regenerates, alters or invalidates an RCA.** Changing it changes only which rows are listed.

## 4.4 Materiality Floor

A percentage breach on a low-volume queue can represent a negligible number of contacts. The floor adds a second, absolute test.

### Floor by volume band

| Volume Band | Floor (contacts) |
|---|---|
| ≤100 | **10** |
| 101–250 | **25** |
| 251–500 | **50** |
| 501–1000 | **100** |
| 1001–5000 | **200** |
| >5000 | **500** |
| Emerging | Floor of the band matching available volume; **10** if indeterminate |

### Display test

```
Show in worklist WHERE
      ABS(Forecast Adherence) > selected threshold
  AND ABS(Actual_Offered − fcst_offered) >= materiality floor for the queue's band
```

### Override

| Control | Behaviour |
|---|---|
| **"Include immaterial breaches"** toggle in the filter bar | **Off by default.** When on, the floor is bypassed and all breaching rows appear |

### Scope

Display only. The floor **never** prevents RCA generation, alters RCA content, or removes data. Every suppressed row remains fully accessible via the toggle.

### Rationale

Measured on FY27 Q2, the floor suppresses **28.7%** of ±10% breaches — reducing the worklist from 285 to 203 rows per week — while retaining representation in **every** volume band. It correctly suppresses cases such as a queue forecasting 1.9 contacts and receiving 1 (a 48.1% breach, 0.9 contacts) while correctly retaining a low-volume queue that forecast 91 and received 8,805.

## 4.5 RCA Horizon and Timeline Callout

| Rule | Detail |
|---|---|
| **Horizon** | RCA is produced **only** for fiscal weeks where `Actual_Offered` is available |
| **Future data** | **Discarded.** Forecast-only weeks are never analysed |
| **Monthly / Quarterly** | Computed on available weeks only, using the Pooled method (§2.3) |
| **Callout** | Every partial period displays **`Timeline: FWxx`**, where `xx` is the last fiscal week with actuals in that period |
| **Confidence** | Scaled by `weeks_available ÷ weeks_in_period`, stated explicitly |

### Example

FY27 M05 spans FW18–21. If actuals are available only to FW18:

```
Timeline: FW18
Basis: 1 of 4 fiscal weeks — confidence reduced accordingly
```

### RCA grain

RCA is produced independently at three grains for every queue, presented in three separate tabs:

| Tab | Grain | Aggregation |
|---|---|---|
| **Weekly** | Queue × Fiscal Week | Direct |
| **Monthly** | Queue × Fiscal Month | Pooled over available weeks |
| **Quarterly** | Queue × Fiscal Quarter | Pooled over available weeks |

The ±5% generation threshold applies **independently at each grain**.

---

# 5. Volume Band

## 5.1 Definition

The volume band classifies each queue by its **mean weekly actual offered volume in the previous fiscal quarter**. It is derived by the system. The `Volume_Category` field in the source dataset is **not used** (§8, note 3).

## 5.2 Derivation

```
weeks_in_quarter = 14   IF previous quarter = Q4 AND weeks_in_FY of that year = 53
                 = 13   otherwise

basis_weeks      = weeks_in_quarter WHERE Actual_Offered IS NOT BLANK

avg_weekly_volume = SUM(Actual_Offered over basis_weeks) / COUNT(basis_weeks)
```

| Rule | Detail |
|---|---|
| Quarter length | **13 weeks**; **14** only where the previous quarter is Q4 of a 53-week year |
| Blank weeks | **Excluded** from both numerator and denominator |
| Zero values | `Actual_Offered = 0` is a **real observation** and is **included** |
| Metric | `Actual_Offered` only |

## 5.3 Bands

| Band | Range (mean weekly actual offered) |
|---|---|
| ≤100 | 0 – 100 |
| 101–250 | >100 – 250 |
| 251–500 | >250 – 500 |
| 501–1000 | >500 – 1,000 |
| 1001–5000 | >1,000 – 5,000 |
| >5000 | >5,000 |

Boundaries are mutually exclusive and gap-free.

## 5.4 Recalculation Schedule

| Item | Rule |
|---|---|
| Recalculated in | **FW01, FW14, FW27, FW40** — the first week of each fiscal quarter |
| Basis | The **immediately preceding** fiscal quarter |
| Effective period | The whole quarter in which it was calculated |
| Effective dating | Each band is stored with its effective quarter. Historical RCAs always retain the band **in force at the time** |
| Mid-quarter changes | **None.** A band is fixed for its quarter |

## 5.5 Basis Transparency

Because actuals lag the current week, the previous quarter may be incomplete at recalculation time. The band therefore always displays its basis window:

```
Volume Band: 501–1000
Basis: FY27 Q1, FW01–FW10 (10 of 13 weeks)
```

## 5.6 Emerging Queues

| Condition | Treatment |
|---|---|
| No prior-quarter actuals | Band = **`Emerging`** |
| RCA | **Produced** using whatever data is available |
| Confidence | Rated according to data sufficiency and stated explicitly |
| Reclassification | At the next quarterly recalculation, once prior-quarter actuals exist |

Emerging queues are never excluded from analysis.

---

# 6. Geography Hierarchy

Three levels: **Region → SubRegion → Country.** Verified clean in the reference dataset — no SubRegion maps to more than one Region, and no Country maps to more than one SubRegion or Region.

## 6.1 Region → SubRegion Mapping

| Region | SubRegions |
|---|---|
| **Americas** | **NA** *(NorthAm)* · Brazil · LATAM · Multiple AMER SubRegions |
| **APJ** | ANZ · CCC · IN · JPN · KR · SA |
| **EMEA** | CER · EC · Multiple EMEA SubRegions · NER · SER · UKI |

Three Regions, sixteen SubRegions.

## 6.2 Accepted Aliases

Alias forms must be normalised to the canonical value on ingestion. They must **never** create new dimension members.

| Canonical | Accepted aliases |
|---|---|
| Region `Americas` | `AMER` |
| SubRegion `NA` → stored as **`NorthAm`** | `NA` · `NorthAm` · `North America` · `North Americas` |

## 6.3 `NA` — Reserved Literal Value (BR-110)

**`NA` is a valid business value meaning North America. It is not a null, and must never be discarded.**

`NA` is a default null-marker string in Python, Excel, Power BI and most ETL tooling. Read with default settings, all North America rows silently lose their SubRegion — **16,250 rows (11.7%) of the reference dataset**, with no error raised.

### Mandatory ingestion rules

| # | Rule |
|---|---|
| 1 | **Disable automatic NA-string interpretation** on all text columns during read |
| 2 | **Normalise `NA` → `NorthAm`** as the canonical stored value. `NorthAm` is not a null-marker in any common tool, so the collision cannot recur |
| 3 | Apply rule 1 at **every** hop — ingestion, export, refresh, round-trip |
| 4 | **Validate** post-load: `COUNT(SubRegion IS NULL)` must be **zero** |

Verified: with NA-parsing disabled the reference dataset contains **16 distinct SubRegions with zero nulls**, exactly matching §6.1. The reference dataset contains no other affected column.

## 6.4 Aggregate Values

Certain dimension values represent deliberate multi-entity groupings, not data defects.

| Level | Aggregate values |
|---|---|
| SubRegion | `Multiple AMER SubRegions` · `Multiple EMEA SubRegions` |
| Country | `North America` · `ROLA` *(Rest of Latin America)* · `Multiple AMER Countries` · `Multiple EMEA Countries` |

These are valid and fully analysed. **One restriction:** they cannot be resolved against the country-level holiday master. See §9.4.

## 6.5 Unmapped Value Alert

Filter values and dimension members are populated **dynamically** from the current dataset. New values are never blocked, but must never appear silently.

| # | Rule |
|---|---|
| 1 | A new dimension value is **accepted and immediately usable** |
| 2 | It is **flagged** in the Data Availability Callout and surfaced to the Administrator: *"New SubRegion 'XYZ' detected — not in reference mapping"* |
| 3 | The **Region → SubRegion mapping updates automatically** to include it |
| 4 | **A SubRegion can never exist without a Region.** An orphan SubRegion is a validation failure and is **rejected** |
| 5 | Alias normalisation (§6.2) is applied **before** the unmapped check, so `AMER` never registers as a new Region |

Without rule 5, a single alias variant would silently split a region into two dimension members.

---

# 7. Demand Driver Model

## 7.1 Stock versus Flow

Three distinct measures forming a produce → ship → field funnel. They are **not** duplicates and modelling them together does **not** double-count.

| Measure | Field(s) | Nature | Meaning |
|---|---|---|---|
| **Production Plan** | `Final_upp_units` | **Flow** | UPP — quantity of finished goods the factory is scheduled to produce |
| **Shipments** | `Final_Units` | **Flow** | Units planned for delivery/production in that week. Also referred to as Shipment |
| **Installed Base** | `Planned_ASU`, `Actual_ASU` | **Stock** | Active Serviceable Units in the market and covered under warranty at that point in time |

### Analytical consequence

Stock and flow drive contact demand with **different lag structures**:

| Measure | Expected relationship to contact volume |
|---|---|
| Shipments (flow) | **Lagged** — new units generate setup and onboarding contacts within weeks; failure-driven contacts considerably later |
| Installed Base (stock) | **Contemporaneous** — a larger serviceable base generates proportionally more support demand in the same period |

Correlation and feature-attribution analysis must respect this distinction. Testing shipments contemporaneously, or installed base with a long lag, will produce plausible-looking but incorrect drivers.

## 7.2 Warranty Structure — Nested, Not a Partition

`Final_Y1` through `Final_Y5` are **nested cumulative subsets**, not mutually exclusive buckets.

```
Final_Y5 ⊆ Final_Y4 ⊆ Final_Y3 ⊆ Final_Y2 ⊆ Final_Y1 ⊆ Final_Units
```

| Field | Meaning |
|---|---|
| `Final_Y1` | Units that will carry Year 1 warranty |
| `Final_Y2` | Subset of Y1 that will **also** carry Year 2 warranty |
| `Final_Y3` | Subset of Y2 that will also carry Year 3 |
| `Final_Y4` | Subset of Y3 that will also carry Year 4 |
| `Final_Y5` | Subset of Y4 that will also carry Year 5 |

### Critical consequences

| # | Rule |
|---|---|
| 1 | **`Final_Units ≠ SUM(Y1..Y5)`.** Summing the Y-fields double-counts units and is always wrong |
| 2 | Every shipped unit carries at least one year of warranty, therefore **`Final_Y1 = Final_Units`** in the normal case |
| 3 | **`Final_Units − Final_Y1` = shipments carrying no warranty** (spare parts, out-of-warranty). A legitimate positive value |
| 4 | **`Final_Y1 > Final_Units` is structurally impossible** — warranty units cannot exceed shipped units |
| 5 | A **warranty mix percentage** must be computed from **exclusive bands** (§7.3), never from raw Y-field ratios |

## 7.3 Exclusive Warranty Bands

Exclusive bands are derived by **differencing** the nested values.

| Band | Derivation | Meaning |
|---|---|---|
| No warranty | `Final_Units − Final_Y1` | Shipped with no warranty |
| 1-year only | `Final_Y1 − Final_Y2` | Exactly 1 year |
| 2-year only | `Final_Y2 − Final_Y3` | Exactly 2 years |
| 3-year only | `Final_Y3 − Final_Y4` | Exactly 3 years |
| 4-year only | `Final_Y4 − Final_Y5` | Exactly 4 years |
| 5-year | `Final_Y5` | 5 years |
| **Total** | **= `Final_Units`** | |

**Mix percentage denominator = `Final_Units`.**

```
Warranty Mix % (band n) = exclusive_band_n / Final_Units × 100
```

Verified: the exclusive bands reconcile to `Final_Units` in **100.0%** of Tier A rows.

### Worked example

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

`SUM(Y1..Y5)` = 10,896 — meaningless, and 2.6× the actual shipment volume.

## 7.4 Warranty Validation — Three Tiers

Every row is classified before warranty data may be used. This prevents structurally broken input producing a confident but incorrect Warranty Mix conclusion.

### Tier A — PASS

**Conditions — all must hold**
- `Final_Y1 ≤ Final_Units`
- `Final_Y1 ≥ Final_Y2 ≥ Final_Y3 ≥ Final_Y4 ≥ Final_Y5`
- No negative values

**Action** — full use. Warranty Mix hypothesis available. No confidence penalty. `Final_Units − Final_Y1` treated as no-warranty shipments.

### Tier B — WARN

**Condition** — `Final_Y1` exceeds `Final_Units` by no more than `MAX(2 units, 0.5% of Final_Units)`. Nesting intact, no negatives.

**Action**
- **Clamp** `Final_Y1` to `Final_Units`
- Proceed with warranty analysis
- **Flag** in the Data Availability Callout
- Apply a **small** confidence penalty

**Rationale** — a reconciliation artefact between source feeds. Median discrepancy in this tier is a handful of units against shipment volumes in the thousands.

### Tier C — FAIL

**Conditions — any one**
- `Final_Y1 > Final_Units` beyond the Tier B tolerance
- **Nesting inverted** anywhere — e.g. `Final_Y3 > Final_Y2`, structurally impossible
- Any negative value

**Action**
- **Suppress the Warranty Mix hypothesis entirely** for that row
- **Exclude** `Final_Units` and `Final_Y1`–`Final_Y5` from correlation and feature attribution for that row
- **Flag prominently** with the specific failure reason
- **Reduce confidence** with an explicitly stated cause
- **RCA continues normally on all other hypotheses**

**No repair. No substitution. No interpolation.** The engine states that warranty data is unusable for that period rather than producing a figure it cannot defend.

### Reference distribution

| Tier | Rows | Share |
|---|---|---|
| A — PASS | 74,621 | **79.8%** |
| B — WARN | 4,059 | **4.3%** |
| C — FAIL | 14,850 | **15.9%** |
| **Usable (A + B)** | **78,680** | **84.1%** |

---

# 8. Field Definitions

| Field | Type | Definition |
|---|---|---|
| `Fiscal_Week` | Integer | Fiscal week in `YYYYWW` format where `YYYY` is the **fiscal** year (e.g. `202718` = FW18 of FY27). Primary time key. Week begins Saturday; Friday is the final working day. Fiscal year begins with the first week of February. See §3 |
| `Week_Ending` | Date | Calendar date on which the fiscal week ends. Always a Friday |
| `Region` | Text | Top-level geography. Three values: **APJ**, **EMEA**, **Americas**. Alias: `AMER` → `Americas`. See §6.1 |
| `SubRegion` | Text | Geographic subdivision within Region. Sixteen values. **`NA` is a literal value meaning North America, stored canonically as `NorthAm` — never a null.** See §6.1, §6.3 |
| `Country` | Text | Country of the queue. May be a deliberate multi-country aggregate. See §6.4 |
| `Forecast_name` | Text | **Queue identifier.** Name of the forecasting queue supporting a particular business. Unique in combination with `Fiscal_Week` |
| `Forecaster` | Text | Person or team owning the forecast for the queue. **Named individual — access-restricted.** See §9.6 |
| `Offering` | Text | Product or service offering. Observed values: **Basic · Pro · OOP · Premium**. Values indicating out-of-warranty support: `PON`, `OOP`, `OOW`, `Out-of-Warranty` — a **reference list**, extensible, not a validation rule |
| `Projection_plan_name` | Text | Forecast plan under evaluation for the period (weekly or monthly). **Not a forecast version** — see §9.5 |
| `channel` | Text | Customer interaction channel. Observed: Voice · Chat · Email · Case · Social Media |
| `business_org` | Text | Business organisation owning the queue. Observed: **CSG**. Additional values expected (e.g. ISG). Dynamically populated |
| `Actual_Offered` | Numeric | **Actual offered contact volume. The sole actual-volume input to all calculations** |
| `Actual_Handled` | Numeric | Actual handled contact volume. Explanatory variable only |
| `fcst_offered` | Numeric | **Forecast offered contact volume. The sole forecast input to all calculations.** May be fractional |
| `fcst_handled` | Numeric | Forecast handled contact volume. Explanatory variable only |
| `Planned_ASU` | Numeric | Planned Active Serviceable Units per the ASU plan. **Stock measure** — installed base under warranty. See §7.1 |
| `Actual_ASU` | Numeric | Actual Active Serviceable Units. **Stock measure** |
| `Final_Units` | Numeric | Number of planned units for delivery/production. Also referred to as **Shipment**. **Flow measure.** A major demand driver. `Final_Y1`–`Final_Y5` overlap, therefore `Final_Units ≠ SUM(Final_Y1..Final_Y5)`. See §7.2 |
| `Final_Y1` | Numeric | Planned units for delivery/production that will fall under **Year 1** warranty. Normally equals `Final_Units` |
| `Final_Y2` | Numeric | Subset of `Final_Y1` that will also fall under **Year 2** warranty |
| `Final_Y3` | Numeric | Subset of `Final_Y2` that will also fall under **Year 3** warranty |
| `Final_Y4` | Numeric | Subset of `Final_Y3` that will also fall under **Year 4** warranty |
| `Final_Y5` | Numeric | Subset of `Final_Y4` that will also fall under **Year 5** warranty |
| `Final_upp_units` | Numeric | **UPP — Unit Production Plan.** Final actionable quantity of finished goods a factory is scheduled to produce. **Flow measure**, upstream of shipments. Sparsely populated — see note 2 |
| `Holiday_Count` | Integer | Number of holidays in the fiscal week. Equals the sum of the seven day indicators — see note 4 |
| `Monday` … `Sunday` | Binary | Day-level holiday indicator for each day of the fiscal week. `1` = holiday, `0` = not |
| `Volume_Category` | Text | Source-supplied volume band. **Not used by the system** — see note 3 |

### Notes

1. **ASU** is a measure represented by two fields, `Planned_ASU` and `Actual_ASU`. There is no standalone `ASU` column in the dataset.
2. **`Final_upp_units`** is blank in approximately 83% of the reference dataset. Handled per §9.1 — flagged, excluded, RCA continues. Not relied upon as a primary driver.
3. **`Volume_Category`** is superseded by the system-derived Volume Band (§5). The source field is retained for reference and reconciliation but is **never used** in analysis, filtering or banding. Source boundaries also overlap at 250 and leave a gap between 100 and 101.
4. **`Holiday_Count`** is fully derivable from the seven day indicators — verified identical in 100% of the reference dataset. Retained for convenience; the day indicators are authoritative.

---

# 9. Data Handling Rules

## 9.1 Missing and Blank Data

| # | Rule |
|---|---|
| 1 | **Flag** the missing field explicitly |
| 2 | **Highlight** it in the Data Availability Callout |
| 3 | **Exclude** it from calculation — never impute, interpolate or substitute |
| 4 | **Continue** the RCA normally on available data |
| 5 | **Reduce confidence** and state the reason |

A missing driver never halts an investigation. It narrows what the investigation can conclude, and that narrowing is disclosed.

## 9.2 Zero versus Blank

| Value | Treatment |
|---|---|
| **`0`** | A **real observation**. Included in all calculations, counts and averages |
| **Blank** | Missing data. Excluded, flagged per §9.1 |

This distinction applies throughout, including the volume band basis calculation (§5.2).

## 9.3 Non-Computable Adherence

Where `fcst_offered = 0` or is blank, adherence is not computable. The row is excluded from calculation and aggregates and flagged per §9.1. It never appears as a breach and never generates an RCA.

## 9.4 Holiday Resolution

| Country value | Holiday context |
|---|---|
| A single, resolvable country | Resolved from the holiday master |
| **Aggregate values** — `North America` · `ROLA` · `Multiple AMER Countries` · `Multiple EMEA Countries` | **Skipped and flagged** per §9.1. The Holiday hypothesis is suppressed for these queues |

Approximately 4.2% of the reference dataset is affected. A union of holidays across an entire multi-country grouping would produce a meaningless `Holiday_Count`; stating that holiday context is unavailable is the defensible treatment.

Where the holiday master and the dataset differ only in spelling (e.g. `korea` / `south korea`), values are **normalised**, not skipped.

## 9.5 Forecast Versioning — Known Limitation

The dataset holds exactly one row per `Forecast_name` × `Fiscal_Week`. There is **no forecast version dimension**. `Projection_plan_name` is a plan-period label, not a version of a given week's forecast.

**Consequence:** forecast-versus-forecast comparison is not possible. Hypotheses depending on forecast lineage — manual override, trend misidentification, version drift — cannot be evaluated in this release and must be declared unavailable rather than approximated.

## 9.6 Access Restriction

`Forecaster` identifies named individuals. Filtering or grouping by `Forecaster` produces an implicit individual-performance view of forecast misses. This dimension is **role-restricted** and not available to all personas.

---

# 10. Business Notes

- **Forecast Adherence** is the primary KPI for Forecast RCA. **Forecast Accuracy** is a reference metric only.
- Adherence is **signed**: negative = under-forecast, positive = over-forecast. The sign carries diagnostic meaning and is never discarded.
- Adherence calculations use **`Actual_Offered`** and **`fcst_offered`** exclusively. All other fields are explanatory variables.
- For the **Basic** offering, `Final_Units` and `Final_Y1`–`Final_Y5` are comparatively more important demand drivers than ASU, subject to demonstrated correlation. This is a hypothesis-prioritisation input, not a conclusion.
- **`Final_Units` is a flow, ASU is a stock.** They are complementary, not interchangeable, and carry different lag structures (§7.1).
- Holiday fields provide calendar context for RCA.
- Queue metadata — Region, SubRegion, Country, Offering, Channel, Business Organisation, Forecaster, Volume Band — provides segmentation for analysis and hypothesis generation.
- All dimension filters are **dynamically populated** from the current dataset. New values are accepted, flagged and mapped automatically (§6.5).

---

# 11. Observed Data Quality — Reference Only

Observations from the reference dataset. **These are not rules.** They are recorded to inform confidence assessment and to support data-owner escalation.

## 11.1 Warranty Data Conformance by Offering

| Offering | Rows | Tier A | Tier B | **Tier C (unusable)** |
|---|---|---|---|---|
| Premium | 9,635 | 100.0% | 0.0% | **0.0%** |
| Pro | 32,681 | 99.0% | 0.0% | **0.9%** |
| OOP | 11,937 | 78.9% | 4.6% | **16.5%** |
| **Basic** | **39,277** | 59.1% | 8.9% | **32.0%** |

**Note:** Basic is the offering for which `Final_Units` / `Final_Y1`–`Y5` is the stated primary driver, and it has the weakest warranty data. For approximately one third of Basic queue-weeks the expected primary driver is unavailable and the engine will fall back to alternative hypotheses at reduced confidence.

## 11.2 Warranty Conformance by Region

| Region | Tier A | Tier B | Tier C |
|---|---|---|---|
| EMEA | 87.8% | 1.3% | 10.9% |
| APJ | 76.8% | 3.1% | 20.0% |
| Americas | 68.9% | 12.8% | 18.3% |

## 11.3 Warranty Conformance Trend

| FY | 2023 | 2024 | 2025 | 2026 | 2027 |
|---|---|---|---|---|---|
| Fully conforming | 74.4% | 67.7% | 66.1% | 62.1% | **58.8%** |

A 16-point degradation since FY2023. Worth raising with the data owner independently of this project — remediating the source feed would recover roughly 30% of Basic analytical coverage.

## 11.4 Field Completeness

| Field | Blank |
|---|---|
| `Final_upp_units` | 83.3% |
| `Actual_ASU` | 44.3% |
| `Planned_ASU` | 33.7% |
| `Actual_Offered` | 32.2% *(predominantly future periods — excluded by §4.5)* |
| `Final_Units`, `Final_Y1`–`Y5` | 32.6% |
| `fcst_offered` | 11.9% |
| `SubRegion` | **0%** *(after applying §6.3; 11.7% if NA-parsing is left enabled)* |

## 11.5 Data Sufficiency

| Measure | Value |
|---|---|
| Queues | 427 |
| Median weeks of actuals per queue | 235 |
| Queues with fewer than 104 weeks | 18 (4.2%) |
| Actuals lag behind current week | approximately 4 fiscal weeks |

---

# 12. Change Log

## Version 2.0 — 30 July 2026

### Corrections

| # | Change |
|---|---|
| 1 | **Forecast Adherence formula corrected.** v1.0 rendered it as `(1-((Actual_Offered/fcst_offered)*100))` — the `×100` inside the bracket, with unbalanced parentheses. This returned −111 for a 12% under-forecast instead of −12%, and produced negative values for both over- and under-forecast, contradicting the stated sign convention. Corrected to `(1-(Actual_Offered/fcst_offered))*100` |
| 2 | **Region definition corrected.** v1.0 conflated Region and SubRegion, describing LATAM as a Region. Region has three values (APJ, EMEA, Americas); LATAM is a SubRegion of Americas |
| 3 | **Offering values corrected** to Basic / Pro / OOP / Premium, with the out-of-warranty reference list added |
| 4 | **`Volume_Category` superseded** by the system-derived Volume Band |
| 5 | **Fixed ±10% flag replaced** by the three-control trigger and display model |
| 6 | **"No additional calculations are performed"** removed — a statement of the prior rule-based implementation, not of this system |
| 7 | **`Final_Units` redefined** as planned shipments (flow), replacing the earlier installed-base characterisation |
| 8 | **ASU** confirmed as Active Serviceable Units — installed base under warranty (stock) |

### Additions

| # | Addition |
|---|---|
| 9 | Document Control block per project Documentation Standards |
| 10 | Scope of Measurement — grain, queue identity, field conventions (§1) |
| 11 | Adherence edge cases and worked examples (§2.1) |
| 12 | Pooled aggregation for monthly and quarterly (§2.3) |
| 13 | Complete fiscal calendar — 4-4-5, 53-week 4-5-5, detection rule, verified reference tables (§3) |
| 14 | RCA trigger and display model — generation threshold, lazy generation, display filter, materiality floor, horizon and Timeline callout, three RCA grains (§4) |
| 15 | Volume Band — derivation, bands, recalculation schedule, effective dating, Emerging, basis transparency (§5) |
| 16 | Geography hierarchy — mapping, aliases, `NA` reserved literal rule (BR-110), aggregates, Unmapped Value Alert (§6) |
| 17 | Demand driver model — stock vs flow, warranty nesting, exclusive bands, three-tier validation (§7) |
| 18 | Data handling rules — missing data, zero vs blank, non-computable adherence, holiday resolution, forecast versioning limitation, access restriction (§9) |
| 19 | Observed data quality reference (§11) |
| 20 | This change log (§12) |

### Open Item

| # | Item |
|---|---|
| 1 | **`fcst_offered = 0`** treatment (§2.1, §9.3) applies the approved missing-data principle to a non-computable denominator by extension. 50 rows affected in the reference dataset. Awaiting explicit confirmation |

---

# End of Document
