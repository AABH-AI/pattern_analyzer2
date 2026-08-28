# ChatGPT prompt — full technical architecture of the Demand Pattern RCA system

Ask for **four** diagrams, not one. Every figure, ID, column name and SQL statement below was
read out of this repository.

- **Panel A** — master end-to-end flow (the one for the slide)
- **Panel B** — the 15 canonical steps, zoomed
- **Panel C** — the 23-hypothesis catalogue
- **Panel D** — the data & JSON contract (SQL, ContextBundle, response)

Ask for Mermaid first in each case, then the image. Mermaid is text, so a wrong label takes
seconds to fix; an image has to be regenerated and usually gets the small labels wrong again.

---

```
You are a principal systems architect. Produce a technical architecture diagram set for a
production forecasting root-cause-analysis system. This is engineering documentation, not
marketing: precision matters more than beauty.

DELIVERABLE — FOUR SEPARATE DIAGRAMS
Do not try to fit all of this into one frame. Produce:
  PANEL A  Master end-to-end runtime flow      (16:9, wide, ~12 x 5.5 in)
  PANEL B  The 15 canonical steps, zoomed      (16:9)
  PANEL C  The 23-hypothesis catalogue         (portrait or 4:3, table/tree style)
  PANEL D  Data & JSON contract                (16:9)

For each panel give me a Mermaid diagram in its own code block FIRST (so I can edit labels),
then render it as an image. Keep node labels short; put technical detail on edges, in
<br/><small> sub-lines, or in a side note box.

HARD RULE: use ONLY the components, function names, column names, SQL, numbers and IDs given
below. Invent nothing. If something seems missing, list it at the end under
"NOT ADDED — please confirm". Do not fill the gap yourself.

################################################################
PANEL A — MASTER END-TO-END FLOW
################################################################
Seven swimlanes as subgraphs, left to right:

LANE 1 · STARTUP & CONNECTION
  run.py  ->  uvicorn  ->  FastAPI app `backend/sql_backend.py` on port 8000
  -> pyODBC + "ODBC Driver 17 for SQL Server"
  -> SQL Server 10.10.9.75 · database `Playground` · table `dbo.Input_To_ML_Full_138_Trimmed`
  Credentials: backend/config.json (gitignored).  Readiness probe: GET /api/health
  Table: 114,436 rows · 427 queues · 32 columns · fiscal weeks 202401-202908
         (actuals to FW202722). A complete grid - every queue has a row for every week.
  ALTERNATE INPUT: if SQL is unreachable the browser can load a weekly file by upload.
                   Draw this as a second entry arrow into Lane 2.

LANE 2 · INPUT LAYER - `rca_console.html` (ONE static file · no libraries · no build step)
  Endpoints it calls: GET /api/data · GET /api/models · GET /api/cqn-mapping ·
                      GET /api/queue-context
  The client computes only TWO metrics per row:
      Forecast Accuracy  = Actual_Offered / fcst_offered * 100
      Forecast Adherence = (1 - Actual_Offered / fcst_offered) * 100   [SIGNED]
        negative = actual ABOVE plan (under-forecast)
        positive = actual BELOW plan (over-forecast)
  A row is FLAGGED when |Adherence| > band (UI default 10%). Flagged rows = the worklist.
  The analyst clicks ONE flagged queue-week -> this is the trigger for everything downstream.
  ENGINE SELECTOR (a dropdown, `window.RCA_ENGINE`, default 'wfm'):
      'wfm'  -> WFM engine      · 'spec' -> FC_RCA v2 Decision Card engine
  Show as a decision diamond. This diagram then follows ?mode=spec.
  Request:  POST /api/rca-investigate?mode=spec&grain=weekly&interrogate=1
  Function chain in the browser:
      triggerRCA()  ->  buildContext()  ->  aggregateData()  ->  buildStatSummary()
                    ->  slimEntry()     ->  callInvestigationEngine()

LANE 3 · SERVER-SIDE DATA FETCH
  `backend/wfm/data_access.py :: fetch_wfm_context(cur, table, key)`
  The browser sends the target row's IDENTITY; the server fetches the DEPTH. Four queries
  (exact SQL in Panel D). Total read about 183 rows = 0.2% of the table, ~0.3s.
  Design rule to annotate: no index exists on these columns, so reads are scoped and capped
  deliberately, and cross-queue work is AGGREGATED (SUM), never pulled as rows.
  DEGRADATION (dashed amber): on failure `wfm_context = {"fetch_error": ...}` and the engine
  continues on the posted bundle alone, stating what is missing.

LANE 4 · BUSINESS CONTEXT for the selected queue
  `backend/wfm/context_repository/holiday_master.json`
      built from FC_RCA_Holiday_Master_Production.xlsx
      12,197 active rows · 6,698 country-weeks · 6 aggregate groups
      per holiday: name, country, date, before/after impact-window days
  Fiscal calendar: 521 weeks -> start/end date, quarter, month (`fiscal_calendar.py`)
  Functions: holiday_context()  -> the holidays in THIS week
             holiday_span()     -> the H-2 ... H+2 window
  Queue dimensions resolved: business_org / Region / SubRegion / Country / Offering /
             channel / Volume_Category
  Each context element is tagged Available · NotApplicable · Missing
  KEY POINT to annotate: a week whose own Holiday_Count = 0 can still be pre- or
  post-holiday, because an adjacent holiday's impact window reaches into it.

LANE 5 · DETERMINISTIC ENGINE - `backend/wfm/spec_engine.py :: investigate()`
  15 canonical steps. In Panel A show them COLLAPSED into 5 blocks:
      Steps 1-4 Intake & threshold | Step 5 Context | Steps 6-9 Hypotheses & evidence |
      Steps 10-13 Cause, challenge, confidence | Steps 14-15 Narrative & audit
  Panel B expands them.

LANE 6 · LLM LAYER - TWO models, BOTH hosted on NVIDIA, called with the SAME API key
  Endpoint: https://integrate.api.nvidia.com/v1/chat/completions
  MODEL 1 (primary)      `nvidia/nemotron-3-super-120b-a12b`   measured 22-29s
  MODEL 2 (interrogator) `openai/gpt-oss-20b`                  measured 25-67s
      ("openai/" is only the model's origin - NVIDIA serves it, on the same key.)
  FOUR prompt call types - give each a hexagon labelled MODEL 1 or MODEL 2:
   1. Step 10 root-cause wording   `why_rephrase.build_messages()`        MODEL 1
   2. Step 14 executive narrative  `narrative_prompt.build_messages()`    MODEL 1
   3. Interrogation ASK (prompt 2) `why_prompt.SYSTEM` via
                                   `why_prompt.build_messages()`          MODEL 2
   4. Interrogation ANSWER (pr. 1) `why_prompt.ANSWER_SYSTEM` via
                                   `why_prompt.build_answer_messages()`   MODEL 1
  Show the interrogation as a two-stage loop:
      MODEL 2 asks -> 3-5 questions, each carrying an `arises_from` field
        -> optional ONE schema-repair retry to the SAME model if a field is missing
        -> MODEL 1 answers EACH question in a SEPARATE call
           (one call per question deliberately: batched, the model collapsed onto whichever
            finding was most striking and returned the same answer twice)
  TOTAL 6-8 LLM calls per investigation. Read timeout 150s.
  WHY THE SPLIT - annotate it: one model both asking and answering shares its own blind
  spots; it is least likely to ask about the thing it did not think to look at, and then it
  judges whether the data can answer.
  FALLBACK (dashed amber): MODEL 2 down -> the interrogator slot is PREPENDED to the chain so
  MODEL 1 asks instead; the section degrades rather than disappearing, and the terminal
  prints `[FC-RCA] FELL BACK` so a silent fallback cannot hide.
  FALLBACK (dashed amber): ANY LLM failure -> the RCA still returns COMPLETE, marked
  "Incomplete", meaning only the PROSE is missing. Every figure, cause, confidence score and
  recommendation is already computed.
  HARD CONSTRAINT to annotate on the lane: the LLM never computes, ranks, scores or selects.
  Its output is schema-validated and every number it writes must trace to the inputs -
  `narrative_prompt.validate()`, `why_prompt.validate()`, `why_prompt.validate_answers()`,
  `why_rephrase._grounded()`.

LANE 7 · OUTPUT & RENDER
  Response: a `decision_card` JSON object of 20 numbered sections (Panel D lists them).
  Browser: renderDecisionCard()  ->  layoutCardSections()  ->  SIX tabs:
      Decision · Calendar · Confidence & Recommendation · Statistics · Challenge · Reference
  Separate small path: POST /api/rca-summarise -> `summary_prompt.build_summary_messages()`
      (an on-demand summary regeneration button, NOT part of the investigate flow)

################################################################
PANEL B - THE 15 CANONICAL STEPS, ZOOMED
################################################################
A vertical or serpentine flow, one box per step: number, name, what it does, and the module.
Use the EXACT step names below - they are the engine's own `_step()` labels.

 1  Receive Forecast Data          intake of the posted ContextBundle + wfm_context
 2  Validate Data Quality          `data_quality.py` - blanks, duplicates at grain, mapping
 3  Calculate Forecast Adherence   `common.adherence_pct()` - signed
 4  Detect Significant Deviation   the +/-5% GENERATION THRESHOLD (fixed, not configurable)
                                   DIAMOND: inside +/-5% -> STOP, return "no RCA generated"
                                     WITH the reason. Also: a 50-contact materiality floor
                                     (a worklist control only, it never suppresses the
                                     analysis) and a 75% major-deviation marker for human
                                     check.
 5  Build Business Context         `context_repository.holiday_context()`, `fiscal_calendar`
 6  Generate Candidate Hypotheses  `hypothesis_catalogue.generate(features)` over a FIXED
                                   catalogue of 23 entries (Panel C).
                                   FOUR states, never conflated:
                                   Generated · NotApplicable · Suppressed · Rejected
 -- BETWEEN 6 AND 7 - DETERMINISTIC EVIDENCE LAYER (draw as its own block; the position is
    FORCED, not stylistic: it needs the generated hypothesis IDs from step 6, and steps 7-8
    need its results) --
      `lag_analysis.py`      Spearman at lags 0/1/2/4/8, level AND change, half-history
                             stability, coverage classes populated / sparse / absent
      `forecast_response.py` expected demand (median), exact miss decomposition
                             (forecast-side + demand-side == actual - forecast), response
                             adequacy, and the 4-CONDITION FORECASTABILITY GATE
      `holiday_response.py`  phases H-2...H+2 measured against the queue's OWN non-holiday
                             baseline, consistency rate, whether the plan historically
                             allowed for it, plan_bias_by_phase
      `data_granularity.py`  what the data grain can and cannot support
      `fc_evidence.py`       ASU decomposition (population vs contact-rate effect),
                             criticality (5 bands), the 7 miss mechanisms, miss_streak,
                             and the DIRECTION-COHERENCE GATE
 7  Collect Supporting Evidence      `statistical_evidence.py`
 8  Collect Contradictory Evidence   actively SOUGHT, not incidental - a separate step
 9  Evaluate Statistical Evidence    `correlation_engine.py` - evaluates ONLY the statistics
                                     the hypotheses asked for (`metrics_for(generated)`).
                                     NO N x M correlation sweep. Annotate: brute force
                                     removed.
10  Recursive Root Cause Reasoning   `recursive_why.py` - WHY until the data stops answering
10  Root Cause Wording               -> LLM call 1 (MODEL 1). Failure keeps the deterministic
                                     wording and records a note.
11  Execute Cross-Examination        `cross_examination.py` - 23 FIXED challenge questions
                                     designed to DISPROVE, answered from features.
                                     FULLY DETERMINISTIC - NO LLM.
12  Assign Confidence                `confidence.py` - 8 weighted dimensions + 8 caps
                                     (detail below). Calculated, never chosen by a model.
13  Generate RCA                     select root cause + miss mechanism + criticality +
                                     recommendations
14  Generate Executive Summary       -> LLM call 2 (MODEL 1) - the ONLY generative step
14  Interrogate Findings             -> LLM calls 3..N (MODEL 2 asks, MODEL 1 answers)
15  Persist Audit Trail              audit record + SHA-256 input fingerprint

TWO ORDERING CONSTRAINTS - draw as annotated constraint arrows; they are structural:
  • Step 6 BEFORE step 9 - hypotheses SELECT the statistics; the reverse is fishing.
  • Step 11 BEFORE step 12 - challenge before confidence; cap gate 7 depends on the outcome.

CONFIDENCE DETAIL for step 12 - put this in a side box:
  8 weighted dimensions (weights sum to 1.00):
    ContradictoryEvidence 0.20 · EvidenceStrength 0.18 · BusinessRuleValidation 0.15 ·
    StatisticalAgreement 0.14 · DataSufficiency 0.12 · ContextCompleteness 0.10 ·
    HistoricalConsistency 0.06 · ModelAgreement 0.05
  Availability per dimension: Available · NotApplicable (excluded, weights renormalised) ·
    Missing (floored at 0.20)
  Levels: Very High >=0.85 · High >=0.70 · Medium >=0.50 · Low >=0.30 · Very Low below
  8 CAP GATES (9 rows - gate 3 splits into 3a/3b). Caps are CEILINGS ON THE LEVEL, not
  subtractions from the score; they never raise confidence; where several bind the LOWEST
  wins:
    1  fewer than 50% of applicable dimensions are Available
    2  a business rule contradicts the conclusion
    3a period coverage below 50%  -> cap Medium
    3b period coverage below 25%  -> cap Low
    4  the expected primary driver is Missing -> cap Medium
    5  ContradictoryEvidence score below 0.40 -> cap Low
    6  all evidence comes from a single source family -> cap Low
    7  the conclusion did not survive cross-examination -> cap Low
    8  queue Volume Band is Emerging -> cap Medium
  Whenever a cap binds, the gate, the threshold and the measured figure are ALL recorded -
  "a bare capped number is not compliant".

THE SEVEN MISS MECHANISMS - a second side box. This answers "why did the forecast miss",
which a hypothesis ID alone does not:
  FORECAST_BASELINE_FAILURE        forecast entered the period at the wrong level
  FORECAST_RESPONSE_FAILURE        forecast did not respond to a knowable signal
  CALENDAR_RESPONSE_FAILURE        the calendar effect was knowable and not allowed for
  DRIVER_RESPONSE_FAILURE          a driver moved and the plan did not follow
  DEMAND_EVENT_LOW_PREDICTABILITY  genuinely not forecastable from the available data
  COMPOUND_MISS                    more than one supported mechanism contributed materially
  DATA_LIMITATION                  critical evidence missing, no defensible mechanism
  The DIRECTION-COHERENCE GATE runs over ALL seven BEFORE confidence: does the mechanism push
  demand the way the miss actually went? An incoherent mechanism cannot reach the card.

################################################################
PANEL C - THE 23-HYPOTHESIS CATALOGUE
################################################################
A grouped table or tree, 6 categories. Show ID · name · the condition that generates it.
Header note: a FIXED catalogue in `hypothesis_catalogue.py`, CATALOGUE_VERSION 2.0.0. The LLM
cannot invent an entry. Anything the evidence shows but no entry covers becomes an
UNEXPLAINED_OBSERVATION rather than being forced into the nearest hypothesis.

CALENDAR (4)
  CAL-01 Holiday                     Holiday_Count > 0 in the period or its impact window
  CAL-02 Fiscal Month Transition     the period spans a fiscal month boundary
  CAL-03 Quarter Transition          the period spans a fiscal quarter boundary
  CAL-04 Seasonality                 >=104 weeks of history and the period is complete
DEMAND (4)
  DEM-01 Demand Spike                actual exceeds forecast beyond the volatility band
  DEM-02 Demand Drop                 actual falls below forecast beyond the volatility band
  DEM-03 Demand Shift                adjacent periods show offsetting deviations
  DEM-04 Volume Redistribution       related queues show inverse deviations, same period
FORECAST (2)
  FC-01  Forecast Bias               consistent one-sided deviation across recent periods
  FC-02  Trend Misidentification     trend direction in actuals differs from the forecast
BUSINESS (5)
  BUS-01 Warranty Mix Shift          warranty Tier A/B, shipment exposure, driver passes gate
  BUS-02 Installed Base Change       ASU exposure, passes the gate, a baseline is available
  BUS-03 ASU Plan Variance           both Planned_ASU and Actual_ASU present, gate passes
  BUS-04 Shipment Volume Change      shipment exposure, driver passes the relevance gate
  BUS-05 Queue Migration             a lineage event exists, or a related queue is inverse
STATISTICAL (4)
  STA-01 Outlier                     the period value exceeds the outlier bounds
  STA-02 Drift                       structural change detected in the series
  STA-03 Momentum Shift              rate of change altered materially
  STA-04 Variance Expansion          volatility increased beyond the historical band
DATA QUALITY (4)
  DQ-01  Missing Data                a mandatory field is blank in the period
  DQ-02  Incorrect Mapping           a dimension value is unmapped or newly appeared
  DQ-03  Duplicate Records           a duplicate detected at the expected grain
  DQ-04  Insufficient History        fewer than 104 weeks of actuals for this queue

Also show the FOUR STATES as a small state diagram, and note that `driver_gate.py` is the
relevance gate the BUS-* conditions refer to.

################################################################
PANEL D - DATA & JSON CONTRACT
################################################################
Three columns: (1) SQL IN · (2) ContextBundle · (3) decision_card OUT.

(1) THE FOUR SQL QUERIES - `data_access.py`. Show them as literal SQL boxes:

  Q1 · this queue's history (157 weeks, 16 columns)
      SELECT TOP 157 Fiscal_Week, Actual_Offered, fcst_offered, Holiday_Count,
             Planned_ASU, Actual_ASU, Final_Units, Final_upp_units, Week_Ending,
             Monday, Tuesday, Wednesday, Thursday, Friday, Saturday, Sunday
      FROM <table> WHERE Forecast_name = ? AND Fiscal_Week <= ?
      ORDER BY Fiscal_Week DESC
      NOTE on the box: Monday...Sunday are per-day HOLIDAY FLAGS, not daily volumes.
      NOTE: `Projection_plan_name` is deliberately absent from this SELECT.

  Q2 · the forward window - did the extreme value revert?
      SELECT TOP 4 Fiscal_Week, Actual_Offered
      FROM <table> WHERE Forecast_name = ? AND Fiscal_Week > ? ORDER BY Fiscal_Week ASC

  Q3 · channel siblings via `dbo.CQN_Mapping` (this week + the prior week)
      SELECT DISTINCT Combined_Queue_Name FROM dbo.CQN_Mapping
      WHERE Forecast_Name = ? AND Combined_Queue_Name IS NOT NULL
      then
      SELECT d.Fiscal_Week, d.channel, d.Forecast_name, d.Actual_Offered, d.fcst_offered
      FROM <table> d WHERE d.Fiscal_Week IN (...) AND EXISTS (
        SELECT 1 FROM dbo.CQN_Mapping m WHERE m.Forecast_Name = d.Forecast_name ...)

  Q4 · the INVESTIGATION LADDER - 6 SUM aggregates, one per level, same week
      SELECT SUM(Actual_Offered), SUM(fcst_offered), COUNT(*)
      FROM <table> WHERE Fiscal_Week = ? AND <level dims> = ?
        AND fcst_offered IS NOT NULL AND fcst_offered <> 0
      Levels, highest first (a level is SKIPPED if any of its dimensions is missing):
        Business Org -> Region -> SubRegion -> Country -> Offering -> Channel
      Purpose to annotate: is this miss the queue's own, or inherited from above?

(2) THE CONTEXTBUNDLE - the JSON the browser POSTs. Show the literal shape:
      {
        "meta":   { "band_threshold": 10, "generated_at": "<ISO>", "schema_note": "..." },
        "target": { "key": {Forecast_name, Fiscal_Week},
                    "fields":   <ALL raw columns for this row>,
                    "computed": {accuracy, adherence, ...} },
        "history": [ {key, computed, channel} x up to 13 ],   // RCA_HISTORY_CAP = 13
        "peers":   [ {key, computed, channel} x up to 15 ],   // RCA_PEERS_CAP   = 15
        "statistical_summary": <mean / stdev / z / trend / changed, for EVERY field
                                discovered across target UNION history>
      }
    ANNOTATE the asymmetry, it is deliberate: the TARGET row keeps its FULL raw fields - it is
    the one row being explained - while history and peers are SLIMMED by `slimEntry()` to
    {key, computed, channel}. Sending full raw fields for all 28 rows repeated the same data
    up to 28 times and blew past provider token limits (Groq returned HTTP 413, "tokens per
    minute limit exceeded") on real data. Nothing generic is lost: statistical_summary still
    covers every field, not a curated subset.
    Also annotate: the caps 13 and 15 are TECHNICAL payload limits, not a judgement about
    which weeks or which peers matter.

(3) THE RESPONSE - `decision_card`, 20 numbered sections. Map each to its UI tab:
      1_executive_summary            2_root_cause              3_confidence
      4_business_impact              5_evidence                6_hypothesis_comparison
      7_recommendations              8_limitations             9_data_availability
      10_audit_reference             11_criticality            12_why_this_happened
      13_forecast_response           14_calendar_context       15_driver_evidence
      16_evidence_index (E1-E14)     17_contradiction_resolution
      18_catalogue_gaps              19_statistical_profile    20_channel_mix
    Plus the additive top-level keys: miss_mechanism · criticality ·
      forecast_response_diagnostic · lagged_driver_evidence · holiday_response ·
      weekend_diagnostic · asu_decomposition · evidence_resolution · fc_evidence_index ·
      unexplained_observations · miss_streak
    card_version 2.1.0

################################################################
STYLE - ALL PANELS
################################################################
- Number the stages so a presenter can talk through them in order.
- Colour by kind: deterministic = navy/blue · LLM = green · data store = grey ·
  gate/decision = amber diamond · fallback = amber DASHED · hard failure = red.
- A distinct shape (hexagon) for every LLM call, labelled MODEL 1 or MODEL 2.
- Make the FIVE gates unmistakable: the +/-5% threshold · forecastability (4 conditions) ·
  direction coherence · driver relevance · the 8 confidence caps.
- Monospace font for SQL, JSON and function names. Sans-serif for prose.
- Every fallback edge labelled with its TRIGGER.
- A compact legend on each panel.
- No gradients, no clip-art, no drop shadows. It must stay legible in greyscale print.
- Where a design decision has a stated reason above, keep that reason as a small italic
  annotation. Those reasons are the point of the document.
```

---

## Follow-ups worth sending after the first reply

- *"Panel A is still too dense — collapse Lane 5 to 3 boxes and move the rest into Panel B."*
- *"Add a Panel E: the three failure/degradation paths only, as one decision tree."*
- *"Give me Panel A again as a one-line-per-lane version for a 30-second verbal walkthrough."*
- *"Now mark on Panel A every node that contributes text to the final card"* — this is the one
  that feeds the one-page redesign: it shows which of the 20 sections are load-bearing and
  which are there because the engine can produce them.
