# FC_RCA_API_Specification

**Project:** Forecast RCA Studio (FC_RCA)
**Document Type:** API Specification
**Version:** 2.0.0
**Supersedes:** Version 1.0.0
**Status:** Approved for Development
**Last Updated:** 30 July 2026

---

## Document Control

| Item | Detail |
|---|---|
| **Purpose** | Define the REST contract for Forecast RCA Studio. |
| **Scope** | Phase 1 API surface. |
| **Version basis** | Incorporates P1–P10. Asynchronous execution made mandatory. `investigationId` made mandatory on statistical endpoints. Aggregate, tree, timeline, hypothesis, confidence and classification endpoints added. |
| **Dependencies** | `FC_RCA_Business_Rules.md` v2.0 · `FC_RCA_Data_Dictionary_and_Schema.md` v2.0 |
| **Acceptance Criteria** | (1) No endpoint returns a pooled figure without its offset ratio. (2) No statistical calculation is reachable outside an investigation. (3) Not Applicable and unavailable are returned distinctly. |
| **Owner** | Product Owner, FC_RCA |
| **Approver** | Pending |

---

# 1. Conventions

| Item | Value |
|---|---|
| Base path | `/api/v1` |
| Format | JSON |
| Authentication | Bearer token |
| Authorisation | Role-based |

## Status codes

| Code | Meaning |
|---|---|
| 200 | Success |
| **202** | **Accepted — job enqueued.** Used by all generation endpoints |
| 204 | No content — valid absence, not an error |
| 400 | Bad request — missing or invalid parameter |
| 401 / 403 | Unauthenticated / unauthorised |
| 404 | Not found |
| 409 | Conflict — request valid but not satisfiable in current state |
| 500 | Server error |

## Null semantics — mandatory

| Situation | Representation |
|---|---|
| Value measured as zero | `0` |
| Value relevant but unavailable | `null` **plus** an availability flag and reason |
| Value **not applicable** to this entity | `null` **plus** `applicable: false` and a reason |

**Zero shall never be returned in place of an absent value.** `0` asserts a measurement; `null` asserts an absence. An empty object shall never be returned where `null` is correct — `{}` coerces to zeros downstream.

---

# 2. Analysis Hierarchy APIs

## 2.1 Level 1 and Level 2 aggregate views

```
GET /api/v1/analysis/level1
GET /api/v1/analysis/level2
```

**Query parameters** — `grain` · all filter dimensions · `threshold` · `includeImmaterial`

**Response**

```json
{
  "level": 1,
  "grain": "quarterly",
  "windowStart": 202710,
  "windowEnd": 202722,
  "groups": [
    {
      "region": "Americas",
      "subRegion": "NorthAm",
      "country": "United States",
      "offering": "Basic",
      "pooledAdherence": -7.1,
      "direction": "Under-forecast",
      "netVariance": 28975,
      "grossVariance": 72186,
      "offsetRatio": 59.9,
      "offsetLabel": "MIXED",
      "childQueues": 24,
      "childQueuesWithRca": 19,
      "nextLevelSubdivides": true,
      "rootCauseMix": [
        { "rootCause": "Warranty coverage shift", "queues": 8, "variancePct": 31.0 }
      ],
      "confidenceMix": {
        "veryHigh": 2, "high": 7, "medium": 6, "low": 4, "veryLow": 0
      }
    }
  ]
}
```

**Contract requirements**

| # | Requirement |
|---|---|
| 1 | `grossVariance` and `offsetRatio` are **mandatory** on every group. A response containing `pooledAdherence` without them is **invalid** |
| 2 | Default sort is `grossVariance` **descending** |
| 3 | `offsetLabel` derives from `offsetRatio` — <20% `SYSTEMIC`, 20–70% `MIXED`, >70% `IDIOSYNCRATIC`. **`null` for single-queue groups** |
| 4 | **No confidence score at group level** — only the child distribution |
| 5 | `nextLevelSubdivides` indicates whether the next level produces more than one child. Where `false`, the client **skips** that level (`BR-125`) while retaining it in the breadcrumb |

## 2.2 Level 3 worklist

```
GET /api/v1/analysis/level3
```

**Query parameters** — `grain` · all filter dimensions · `threshold` · `includeImmaterial`

Returns queue-period rows with adherence, direction, absolute variance, volume band, confidence, root cause and markers. Default sort `absoluteVariance` descending.

---

# 3. RCA APIs

## 3.1 Retrieve RCA

```
GET /api/v1/rca
```

Retrieves an existing RCA, generating on demand where it falls in the lazy band.

| Parameter | Required | Notes |
|---|---|---|
| `forecastName` | Yes | Queue identifier |
| `grain` | Yes | `weekly` \| `monthly` \| `quarterly` |
| `periodKey` | Yes | `YYYYWW` \| `YYYYMM` (fiscal) \| `YYYYQ` |

### 200 — RCA available

```json
{
  "rcaCaseId": "...",
  "forecastName": "Nordic Client DSP",
  "grain": "monthly",
  "periodKey": 202705,
  "caseStatus": "Completed",
  "forecastAdherence": -4.2,
  "direction": "Under-forecast",
  "absoluteVariance": 184,
  "aggregationMethod": "Pooled",
  "volumeBand": "501-1000",
  "generationMode": "Batch",
  "withinGenerationWindow": true,
  "coverage": {
    "weeksInPeriod": 4,
    "weeksWithActuals": 1,
    "coverageRatio": 0.25,
    "isComplete": false,
    "lastWeekWithActuals": 202718,
    "missingWeeks": [202719, 202720, 202721],
    "nonComputableWeeks": [],
    "zeroFilledWeeks": [],
    "inactiveWeeks": [],
    "timelineLabel": "Timeline: FW18"
  },
  "confidence": {
    "level": "Low",
    "rawScore": 0.708,
    "cappedScore": 0.499,
    "calculatedLevel": "High",
    "bindingCap": {
      "gateNumber": "3b",
      "gateName": "LowPeriodCoverage",
      "capLevel": "Low",
      "thresholdCrossed": 0.25,
      "actualValue": 0.25,
      "reason": "Only 1 of 4 fiscal weeks has actuals (25%). Coverage below 25%"
    }
  },
  "markers": ["Timeline"],
  "supersededByCaseId": null
}
```

### 202 — generation in progress

```json
{
  "jobId": "...",
  "status": "Queued",
  "pollUrl": "/api/v1/rca/jobs/{jobId}",
  "estimatedSeconds": 45
}
```

### 204 — no RCA exists and none is warranted

`ABS(adherence) <= 5%` and no manual request. Body empty. **This is not an error.**

### 409 — period has no actuals

```json
{
  "error": "PERIOD_HAS_NO_ACTUALS",
  "message": "No fiscal week in this period has Actual_Offered available.",
  "latestWeekWithActuals": 202722
}
```

### Removed parameters

`forecastVersion` and `actualVersion` — **removed.** No forecast version dimension exists in source data. Source holds exactly one row per (`Forecast_name`, `Fiscal_Week`), verified across 138,775 rows.

Consequence: forecast-versus-forecast comparison is unavailable, and hypotheses depending on forecast lineage are **declared unavailable** rather than approximated.

## 3.2 Request RCA below threshold

```
POST /api/v1/rca/request
```

Manual request under `BR-002`.

```json
{
  "forecastName": "Nordic Client DSP",
  "grain": "weekly",
  "periodKey": 202718,
  "requestReason": "Stakeholder query"
}
```

**202 Accepted** with `jobId`, `pollUrl` and `generationThresholdMet: false`.

## 3.3 Request re-run

```
POST /api/v1/rca/{rcaCaseId}/rerun
```

```json
{
  "reason": "string"
}
```

| Condition | Response |
|---|---|
| Fingerprint changed | **202** — re-run proceeds, prior marked `Superseded` |
| Fingerprint unchanged, reason supplied | **202** — proceeds, `isGovernanceException: true`, Administrator flagged |
| Fingerprint unchanged, **reason absent or empty** | **400** — `REASON_REQUIRED` |

```json
{
  "jobId": "...",
  "dataChanged": false,
  "isGovernanceException": true,
  "administratorNotified": true,
  "message": "Re-run proceeding. No data change detected. Reason recorded for Administrator review."
}
```

## 3.4 Job status

```
GET /api/v1/rca/jobs/{jobId}
```

```json
{
  "jobId": "...",
  "status": "Running",
  "currentStage": "CrossExamination",
  "stagesCompleted": 8,
  "stagesTotal": 15,
  "rcaCaseId": null,
  "elapsedSeconds": 31
}
```

On completion, returns `status: "Completed"`, `rcaCaseId` and `resultUrl`. On failure, `status: "Failed"` with `failureReason` and `auditReference`.

**Note** — this reports **job** status, distinct from `caseStatus` on the RCA. A job may complete successfully while its investigation concludes `Inconclusive`. Version 1.0.0 conflated the two in overlapping status attributes.

## 3.5 Case history

```
GET /api/v1/rca/{rcaCaseId}/history
```

Returns all superseded versions with their supersession reason and the weeks added at each recomputation.

---

# 4. Investigation Detail APIs

## 4.1 Confidence

```
GET /api/v1/rca/{rcaCaseId}/confidence
```

```json
{
  "rcaCaseId": "...",
  "confidenceLevel": "Medium",
  "rawScore": 0.799,
  "cappedScore": 0.699,
  "calculatedLevel": "High",
  "bindingCap": {
    "gateNumber": 4,
    "gateName": "PrimaryDriverUnavailable",
    "capLevel": "Medium",
    "reason": "Warranty data invalid (BR-112 Tier C); warranty is the expected primary driver for Basic offering"
  },
  "applicableWeightTotal": 1.00,
  "weightsVersion": "v1.0",
  "dimensionCounts": {
    "applicable": 8, "available": 8, "missing": 0, "notApplicable": 0
  },
  "dimensions": [
    {
      "name": "ContradictoryEvidence",
      "availability": "Available",
      "score": 0.90,
      "weight": 0.20,
      "weightedContribution": 0.180,
      "reason": null
    }
  ],
  "capsEvaluated": [
    { "gateNumber": 1, "conditionMet": false, "capLevel": "Medium", "isBinding": false },
    { "gateNumber": 4, "conditionMet": true, "capLevel": "Medium", "isBinding": true }
  ]
}
```

**Contract requirements**

| # | Requirement |
|---|---|
| 1 | `dimensions` contains **all eight** entries always, including Not Applicable ones (`score: null`, `reason` populated) |
| 2 | `capsEvaluated` lists **all eight gates** with their outcome, not only those met |
| 3 | Where Not Applicable, `score` is **`null`** — never `0` |
| 4 | `rawScore` and `cappedScore` both returned. Where they differ, `bindingCap` is non-null and `reason` mandatory |
| 5 | `weightsVersion` mandatory for reproducibility |

## 4.2 Hypotheses

```
GET /api/v1/rca/{rcaCaseId}/hypotheses
```

```json
{
  "hypotheses": [
    {
      "hypothesisId": "...",
      "name": "Warranty coverage mix shift",
      "category": "Business",
      "state": "suppressed",
      "reason": "Warranty data structurally invalid — Final_Y3 exceeds Final_Y2 (BR-112 Tier C)",
      "supportingEvidenceCount": 0,
      "contradictoryEvidenceCount": 0,
      "evidenceStrength": null,
      "confidence": null
    },
    {
      "hypothesisId": "...",
      "name": "Shipment volume change",
      "category": "Business",
      "state": "notApplicable",
      "reason": "Shipment volume correlation with demand is 0.08 over 235 weeks, below the 0.3 relevance threshold (BR-121)",
      "supportingEvidenceCount": 0,
      "evidenceStrength": null,
      "confidence": null
    }
  ],
  "counts": {
    "accepted": 1, "rejected": 5, "suppressed": 2, "notApplicable": 6
  },
  "notGenerated": [
    { "name": "Seasonality", "reason": "Requires 104 weeks of history; queue has 39" }
  ]
}
```

**`state` values** — `accepted` · `rejected` · `suppressed` · `notApplicable`. **Four distinct states.** `reason` mandatory for the latter three.

## 4.3 Evidence

```
GET /api/v1/rca/{rcaCaseId}/evidence
```

Returns evidence items with type, source family, supporting flag, strength, independence weight and provenance weight. Contradictory items are always included.

## 4.4 Root Cause Tree

```
GET /api/v1/rca/{rcaCaseId}/root-cause-tree
```

```json
{
  "rcaCaseId": "...",
  "nodes": [
    {
      "nodeId": "...",
      "parentNodeId": null,
      "level": 0,
      "statement": "Adherence −18.4%, 184 contacts under-forecast",
      "evidenceCount": 0,
      "confidence": null,
      "validationStatus": null,
      "nodeType": "deviation"
    },
    {
      "nodeId": "...",
      "parentNodeId": "...",
      "level": 1,
      "statement": "Warranty coverage mix shifted",
      "evidenceCount": 4,
      "confidence": "High",
      "validationStatus": "Validated",
      "nodeType": "accepted",
      "isTerminal": false
    }
  ],
  "maxDepthReached": false,
  "terminationReason": "No further evidence available at depth 4"
}
```

**`nodeType`** — `deviation` · `accepted` · `rejected` · `suppressed` · `notApplicable`

## 4.5 Evidence Timeline

```
GET /api/v1/rca/{rcaCaseId}/evidence-timeline
```

```json
{
  "rcaCaseId": "...",
  "axisStart": 202704,
  "axisEnd": 202722,
  "analysedPeriod": { "start": 202718, "end": 202718 },
  "tracks": [
    {
      "trackType": "adherence",
      "points": [ { "fiscalWeek": 202718, "value": -18.4 } ]
    },
    {
      "trackType": "driver",
      "label": "1-year-only warranty share",
      "lagWeeks": 6,
      "relevanceCorrelation": 0.41,
      "points": [ { "fiscalWeek": 202712, "value": 38.0 } ]
    },
    {
      "trackType": "holiday",
      "label": "Diwali",
      "dayOfWeek": "Sunday",
      "windowStart": 202717,
      "windowEnd": 202719
    },
    {
      "trackType": "dataFlag",
      "fiscalWeek": 202715,
      "flag": "zeroFilled",
      "reason": "Interior blank week, 2-week run (BR-122)"
    },
    {
      "trackType": "baseline",
      "mode": "holidayAnchored",
      "fiscalWeek": 202638,
      "label": "Diwali FY26 FW38"
    }
  ]
}
```

Where holiday-anchored comparison applies, **both** the same-fiscal-week and holiday-matched periods are returned so the reader can see why they differ.

## 4.6 Cross-examination

```
GET /api/v1/rca/{rcaCaseId}/cross-examination
```

Returns iterations with questions, semantic keys, evidence retrieved, whether it was new, weaknesses detected, the terminating condition and whether Gate 7 applies.

## 4.7 Annotations

```
GET  /api/v1/rca/{rcaCaseId}/annotations
POST /api/v1/rca/{rcaCaseId}/annotations
```

```json
{
  "annotations": [
    {
      "annotationId": "...",
      "text": "Queue was re-routed to absorb overflow from the Israel chat queue during the outage.",
      "author": "...",
      "recordedAt": "2026-06-12",
      "sourceRcaCaseId": "...",
      "sourceForecastName": "Nordic Client DSP",
      "sourceFiscalWeek": 202718,
      "retrievalReason": "Same queue, related root cause category",
      "impactStatement": "Supports the Queue Migration hypothesis",
      "contributedToDimension": "EvidenceStrength",
      "provenanceWeight": 1.00
    }
  ]
}
```

`POST` accepts `annotationType` (`Agree` / `Disagree` / `AdditionalContext`) and `text`. **There is no endpoint to modify an RCA.**

## 4.8 Cross-grain view

```
GET /api/v1/rca/cross-grain
```

Parameters `forecastName` and `fiscalWeek`. Returns the Weekly, Monthly and Quarterly investigations covering that week, as **context**. Returns no reconciliation.

---

# 5. Statistical APIs

```
GET /api/v1/statistics/error-metrics
GET /api/v1/statistics/trend
GET /api/v1/statistics/seasonality
GET /api/v1/statistics/variability
GET /api/v1/statistics/correlation
GET /api/v1/statistics/drift
GET /api/v1/statistics/momentum
GET /api/v1/statistics/outliers
GET /api/v1/statistics/shap
GET /api/v1/statistics/feature-importance
```

## Mandatory parameter

| Parameter | Required | Notes |
|---|---|---|
| **`investigationId`** | **YES** | The RCA this calculation belongs to |

**`investigationId` is required on all statistical endpoints.** A statistical calculation cannot be requested outside an investigation.

Every result links to `Statistical_Analysis_ID` and is recorded in the audit trail. This enforces `Statistical Framework §24`: **no unexplained statistical output shall appear in the application.**

Requests without `investigationId` return **400 Bad Request**.

## Response requirements

Every response carries the metric value **and** its interpretation in business language, the selection reason, evidence strength, and where applicable `lagApplied` and `driverRelevanceCorrelation`.

Suppressed metrics return with `executionStatus: "Suppressed"` and a reason — never omitted.

---

# 6. Context APIs

## 6.1 Fiscal Calendar

```
GET /api/v1/context/fiscal-calendar
```

Returns fiscal week, year, quarter, month, month label, calendar equivalent, week start and end dates, weeks in year, `is53WeekYear`, weeks in month and weeks in quarter.

## 6.2 Holidays

```
GET /api/v1/context/holidays
```

Returns holidays with canonical name, source name, day of week, impact window, substitute flag and fiscal week. Deduplicated on the entire row.

Where `country` is an aggregate value, returns `applicable: false` with a reason.

## 6.3 Queue classification

```
GET /api/v1/context/queue-classification
```

| Parameter | Required | Notes |
|---|---|---|
| `forecastName` | Yes | |
| **`fiscalWeek`** | **Yes** | Classification returned is the one **in force** for that week's quarter |

```json
{
  "forecastName": "Nordic Client DSP",
  "fiscalWeek": 202718,
  "effective": { "fiscalYear": 2027, "fiscalQuarter": 2 },
  "volumeBand": {
    "band": "501-1000",
    "avgWeeklyVolume": 743.2,
    "materialityFloor": 100,
    "isEmerging": false,
    "basis": {
      "fiscalYear": 2027,
      "fiscalQuarter": 1,
      "weeksExpected": 13,
      "weeksUsed": 10,
      "calculatedOnFiscalWeek": 202714,
      "label": "FY27 Q1, FW01–FW10 (10 of 13 weeks)"
    }
  },
  "driverRelevance": {
    "asu": { "relevant": true, "correlation": 0.44, "observations": 235 },
    "shipments": { "relevant": false, "correlation": 0.08, "observations": 235 },
    "warranty": { "relevant": false, "correlation": 0.06, "observations": 231 }
  }
}
```

### Emerging queue response

```json
{
  "volumeBand": {
    "band": "Emerging",
    "avgWeeklyVolume": null,
    "materialityFloor": 10,
    "isEmerging": true,
    "basis": {
      "weeksExpected": 13,
      "weeksUsed": 0,
      "label": "No prior-quarter actuals available"
    }
  }
}
```

**Contract requirements**

| # | Requirement |
|---|---|
| 1 | `fiscalWeek` is **mandatory**. There is deliberately **no "current classification" endpoint** |
| 2 | `materialityFloor` is returned by the **server**, not computed by the client. Floor and band are defined together and must not drift apart |
| 3 | `avgWeeklyVolume` is **`null`** for Emerging queues, never `0` |

## 6.4 Queue lineage

```
GET /api/v1/context/queue-lineage
```

Returns the lineage chain with predecessor, successor, effective week, relationship type and, where history is inherited, a disclosure statement.

## 6.5 Warranty and shipments

```
GET /api/v1/context/warranty
```

```json
{
  "forecastName": "Nordic Client DSP",
  "fiscalWeek": 202718,
  "validationTier": "A",
  "validationReason": null,
  "applicable": true,
  "driverRelevant": true,
  "shipments": {
    "finalUnits": 4220,
    "nested": { "y1": 4220, "y2": 2623, "y3": 2562, "y4": 1348, "y5": 143 },
    "unitProductionPlan": null,
    "unitProductionPlanAvailable": false
  },
  "exclusiveBands": {
    "noWarranty":  { "units": 0,    "sharePct": 0.0  },
    "warranty1Y":  { "units": 1597, "sharePct": 37.8 },
    "warranty2Y":  { "units": 61,   "sharePct": 1.4  },
    "warranty3Y":  { "units": 1214, "sharePct": 28.8 },
    "warranty4Y":  { "units": 1205, "sharePct": 28.6 },
    "warranty5Y":  { "units": 143,  "sharePct": 3.4  }
  },
  "reconciliation": {
    "bandSum": 4220, "finalUnits": 4220, "reconciled": true
  },
  "denominator": "finalUnits"
}
```

### Tier C response

```json
{
  "validationTier": "C",
  "validationReason": "Nesting inverted: Final_Y3 (2708) > Final_Y2 (1861)",
  "exclusiveBands": null,
  "warrantyHypothesisAvailable": false
}
```

**Contract requirements**

| # | Requirement |
|---|---|
| 1 | `exclusiveBands` is the **only** structure permitted for analysis. `nested` is returned for transparency and audit and shall **not** be consumed as independent variables |
| 2 | `reconciliation` asserted on every response. Where `reconciled` is false the response is invalid and treated as Tier C |
| 3 | Where `validationTier` is `C`, `exclusiveBands` is **`null`** — **an empty object shall NOT be returned.** Consumers must be unable to mistake unavailable data for zero values |
| 4 | Absent fields are `null` with an explicit availability flag, never `0` |

**Removed** — `productId`, `geographyId` (no source), `outOfWarranty` (no source; conflated two concepts), and `warrantyMix` as an untyped empty array.

## 6.6 Installed base

```
GET /api/v1/context/installed-base
```

```json
{
  "forecastName": "Nordic Client DSP",
  "fiscalWeek": 202718,
  "applicable": true,
  "driverRelevant": true,
  "measureType": "stock",
  "aggregationMethod": "mean",
  "plannedAsu": 100000,
  "actualAsu": 120000,
  "plannedAsuAvailable": true,
  "actualAsuAvailable": true,
  "asuAdherence": -20.0,
  "actualAsuGrowthPctYoY": 22.4,
  "actualAsuGrowthPctMoM": 3.1,
  "baseline": {
    "type": "priorYearSamePeriod",
    "fiscalWeek": 202618,
    "actualAsu": 98000
  }
}
```

### Out-of-warranty queue

```json
{
  "applicable": false,
  "applicabilityReason": "Offering 'OOP' indicates out-of-warranty support; installed base is not applicable to this queue",
  "plannedAsu": null,
  "actualAsu": null
}
```

### Applicable but unavailable

```json
{
  "applicable": true,
  "actualAsu": null,
  "actualAsuAvailable": false,
  "unavailableReason": "Actual_ASU not yet loaded for this period (data lag)"
}
```

**Contract requirements**

| # | Requirement |
|---|---|
| 1 | `measureType` always `"stock"`, `aggregationMethod` always `"mean"`. Monthly and quarterly requests return the **MEAN** of weekly values, never a sum |
| 2 | `applicable: false` and `available: false` are **different states** and returned distinctly. The first carries no confidence penalty; the second does |
| 3 | Absent values are `null` with an availability flag, never `0` |
| 4 | `asuAdherence` is `null` where either input is unavailable — never computed from a partial pair |

## 6.7 Business events

```
GET  /api/v1/context/events
POST /api/v1/context/events        (Administrator)
PUT  /api/v1/context/events/{id}   (Administrator)
```

Returns events with impact window. Where the repository is empty or not deployed:

```json
{
  "applicable": false,
  "applicabilityReason": "Event Repository not populated. Not applicable — no confidence penalty",
  "events": []
}
```

Where populated but no event matches:

```json
{
  "applicable": true,
  "events": [],
  "result": "No event found for this period. Event hypothesis tested and rejected."
}
```

**These two responses are materially different and shall not be conflated.**

## 6.8 Business observations

```
GET /api/v1/context/observations
```

Returns annotations and manual observations with provenance weight and retrieval reason. **Not subject to the `BR-203` confidence eligibility gate.**

## 6.9 Historical RCA search

```
GET /api/v1/context/historical-rca
```

```json
{
  "eligiblePrecedents": [
    {
      "rcaCaseId": "...",
      "forecastName": "Nordic Client DSP",
      "periodKey": 202618,
      "matchLevel": "exact",
      "matchReason": "Same queue, same fiscal period prior year",
      "rootCause": "Warranty coverage mix shift",
      "confidenceLevel": "High",
      "confidenceScore": 0.78,
      "provenanceWeight": 0.80,
      "resultingHistoricalConsistency": 0.78
    }
  ],
  "ineligiblePrecedents": [
    {
      "rcaCaseId": "...",
      "periodKey": 202612,
      "ineligibilityReason": "Confidence Low — below Medium eligibility threshold (BR-203)",
      "evidential": false
    }
  ]
}
```

**Contract requirements**

| # | Requirement |
|---|---|
| 1 | Eligible and ineligible precedents returned through **separate paths** |
| 2 | An ineligible entry shall **never** be returned through the evidence path, and never unmarked |
| 3 | `resultingHistoricalConsistency` shall **never exceed** `confidenceScore` — the `BR-118` ceiling |
| 4 | Similarity is **structural** in Phase 1. `matchLevel` is one of `exact` · `strong` · `moderate` · `weak`, with `matchReason` stated. Not a vector distance |

---

# 7. Export APIs

```
POST /api/v1/export/pdf
POST /api/v1/export/word
POST /api/v1/export/markdown
POST /api/v1/export/json
POST /api/v1/export/csv
```

**202 Accepted** with a `jobId` and download URL on completion.

Exports include the confidence decomposition and all callouts. **An export shall not omit content that the Decision Card is required to display.**

PowerPoint export is **FUTURE SCOPE**.

---

# 8. Configuration APIs

```
GET /api/v1/configuration
PUT /api/v1/configuration                    (Administrator)
GET /api/v1/configuration/business-rules
PUT /api/v1/configuration/business-rules/{id} (Administrator)
GET /api/v1/configuration/statistical
GET /api/v1/configuration/explainability
```

## LLM configuration

```
GET /api/v1/configuration/llm
PUT /api/v1/configuration/llm                (Administrator)
```

```json
{
  "modelIdentifier": "string",
  "modelVersion": "string",
  "temperature": 0,
  "topP": 1.0,
  "seed": 42,
  "maxOutputTokens": 2000,
  "timeoutSeconds": 30,
  "maxRetriesPerRca": 1,
  "dailyTokenBudget": 2000000,
  "activePromptVersion": "1.0.0"
}
```

**Constraints**

| # | Constraint |
|---|---|
| 1 | `temperature` is **fixed at 0** and shall not be configurable above it |
| 2 | `modelVersion` shall not be null or a floating alias such as `"latest"` |
| 3 | Changing `activePromptVersion` requires a completed reference-set regression |
| 4 | Only **one** prompt version may be active. A/B testing is FUTURE SCOPE |

## Prompt version registry

```
GET /api/v1/configuration/prompts
GET /api/v1/configuration/prompts/{version}
```

Returns full prompt text, release date, approver and regression result. Prior versions retained indefinitely and **immutable**.

## Non-configurable parameters

The RCA Generation Threshold (±5%) and LLM temperature (0) are **not exposed** for configuration. Attempts to modify them return **403**.

---

# 9. Administration APIs

```
GET    /api/v1/admin/users
POST   /api/v1/admin/users
PUT    /api/v1/admin/users/{id}
DELETE /api/v1/admin/users/{id}
```

`DELETE` is a **deactivation**, not a physical delete.

## Governance exception review

```
GET /api/v1/admin/governance-exceptions
PUT /api/v1/admin/governance-exceptions/{id}
```

Returns re-run requests where no data change was detected, with the supplied reason, requester, both RCA versions and review status.

## Unmapped values

```
GET /api/v1/admin/unmapped-values
```

Returns dimension values not present in the reference mapping, with first-seen date and affected row count.

---

# 10. System APIs

```
GET /api/v1/system/health
GET /api/v1/system/repositories
GET /api/v1/system/audit/{rcaCaseId}
```

`repositories` returns per-repository row count, last refresh, availability rate, validation failure count and unmapped values pending review.

`audit` returns the complete reproducibility set: input fingerprint, business rules version, weights version, hypothesis catalogue version, question catalogue version, prompt version, model version and seed.

---

# 11. Notification APIs

```
GET  /api/v1/system/notifications
POST /api/v1/system/notifications
```

In-application notifications. **Email distribution is deferred to Phase 2.**

---

# 12. Corrections from Version 1.0.0

| # | Correction |
|---|---|
| 1 | Three malformed paths with a leading space — `/ api/v1/admin/users` — corrected |
| 2 | `investigationId` made **mandatory** on all statistical endpoints. Previously they were investigation-agnostic GETs with no required parameters, permitting un-audited statistical output |
| 3 | `forecastVersion` and `actualVersion` **removed** from RCA generation — no source exists |
| 4 | **HTTP 202** now used by all generation endpoints. Previously listed but used nowhere |
| 5 | `grain` parameter added throughout — previously no way to request monthly or quarterly |
| 6 | Aggregate, root cause tree, evidence timeline, hypothesis, confidence, queue classification, lineage, observation and cross-grain endpoints **added** — previously specified in other documents with no endpoint |
| 7 | Null semantics made explicit. Tier C returns `null`, not `{}` |
| 8 | `applicable: false` and `available: false` distinguished throughout |

---

# 13. Guiding Principles

- Zero is a measurement; `null` is an absence. They are never interchanged
- Not Applicable and unavailable are different states with different consequences
- No statistical calculation is reachable outside an investigation
- No pooled figure is returned without its offset ratio
- Generation is asynchronous; nothing blocks an HTTP request for 60 seconds
- Every response that omits data says why

---

# End of Document
