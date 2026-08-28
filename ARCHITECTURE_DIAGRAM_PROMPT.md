# Prompt for ChatGPT — Demand Pattern RCA system architecture flowchart

Copy everything inside the fence below into ChatGPT. Every name, number and endpoint in it is real,
taken from this repository, so the diagram it produces will match the system rather than a generic
RCA pipeline.

Two practical notes before you paste it:

- **Ask for Mermaid first.** It is text, so you can correct a wrong label yourself in seconds, and it
  renders in draw.io, VS Code, GitHub and Mermaid Live. An image is harder to fix and usually gets the
  small labels wrong.
- **The target is slide 4 of `Demand_Pattern_RCA_Overview.pptx`**, which is a 16:9 landscape area of
  roughly 12 × 5 inches. That is why the prompt asks for a wide left-to-right layout rather than a
  tall one.

---

```
You are a senior systems architect producing a presentation-quality architecture flowchart.

GOAL
Draw the complete end-to-end runtime flow of a production "Demand Pattern Root Cause Analysis"
system, from the moment the server starts to the moment the analyst reads the finished card. This is
for an executive/technical review slide, so it must be readable at a glance and accurate in detail.

OUTPUT FORMAT
1. First give me a single Mermaid `flowchart LR` diagram in one code block, using subgraphs as
   swimlanes. Use short node labels (2-6 words) with the technical detail on the EDGES or in
   <br/><small> sub-lines, so no box becomes a paragraph.
2. Then, below the diagram, give a numbered walkthrough of the flow in one line per step.
3. Do not invent any component, file, endpoint, model or number that I have not given you. If you
   think something is missing, list it separately at the end under "Assumptions I did NOT add".

LAYOUT
- Left to right, wide rather than tall (target 16:9, about 12 x 5 inches).
- Seven swimlanes as subgraphs, in this order:
  L1 Startup & Connection | L2 Input Layer (browser) | L3 Server-side Data Fetch |
  L4 Business Context | L5 Deterministic Engine (15 steps) | L6 LLM Layer | L7 Output & Render
- Use distinct colours per lane. Deterministic components in blue/navy, LLM components in green,
  fallback/degradation paths in amber with DASHED arrows, hard failures in red.
- Mark every LLM call with a distinct shape (e.g. a hexagon) so a reader can instantly count them.

============================================================
THE SYSTEM — use exactly these components and labels
============================================================

L1 · STARTUP & CONNECTION
- `run.py` starts uvicorn, which serves the FastAPI app `backend/sql_backend.py` on port 8000.
- On the first request it connects via pyODBC + "ODBC Driver 17 for SQL Server" to
  SQL Server `10.10.9.75` → database `Playground` → table `dbo.Input_To_ML_Full_138_Trimmed`.
- Credentials come from `backend/config.json` (gitignored). `GET /api/health` is the readiness check.
- The table holds 114,436 rows · 427 queues · 32 columns · fiscal weeks 202401–202908.
  It is a complete grid: every queue has a row for every week. Actuals exist to FW202722.
- IMPORTANT branch: if SQL is unreachable the system still runs — the browser can load a weekly file
  by upload instead. Show this as an alternate input path.

L2 · INPUT LAYER (browser — `rca_console.html`, ONE static file, no libraries, no build step)
- The page calls `GET /api/data` to load the table as JSON (or the user uploads a weekly file).
- It also calls `GET /api/models` (which LLMs are offered) and `GET /api/cqn-mapping`.
- Client-side it computes ONLY TWO metrics per row:
    Forecast Accuracy  = Actual_Offered ÷ fcst_offered × 100
    Forecast Adherence = (1 − Actual_Offered ÷ fcst_offered) × 100   [SIGNED]
      negative = actual ABOVE plan (under-forecast) · positive = actual BELOW plan (over-forecast)
- A row is FLAGGED when |Forecast Adherence| > band (default ±10%). Flagged rows form the worklist.
- The analyst clicks one flagged queue-week. That single click is what starts an investigation.
- The client builds a "ContextBundle": the target row's raw fields + computed metrics,
  the prior 13 weeks (RCA_HISTORY_CAP), up to 15 peer queues (RCA_PEERS_CAP), and an
  auto-discovered statistical summary. The caps exist to bound the payload, not to judge relevance.
- It also calls `GET /api/queue-context` for a properly scoped SQL slice of this queue.
- Then it POSTs to: `POST /api/rca-investigate?mode=spec&grain=weekly&interrogate=1`
- Note there are THREE engines behind that one endpoint — `?mode=legacy`, `?mode=wfm`, and
  `?mode=spec` (the FC Decision Card engine). Show the mode switch as a decision node; this diagram
  then follows `?mode=spec`.

L3 · SERVER-SIDE DATA FETCH — `backend/wfm/data_access.py :: fetch_wfm_context()`
The browser sends only the target row's identity; the server fetches the depth. FOUR queries:
 1. This queue's history: `SELECT TOP 157` — 157 weeks (~3 years), 16 columns
    (Actual_Offered, fcst_offered, Holiday_Count, Week_Ending, Planned_ASU, Actual_ASU,
     Final_Units, Final_upp_units, Monday…Sunday).
    NOTE: Monday…Sunday are per-day HOLIDAY FLAGS, not daily volumes.
 2. A 4-week FORWARD window — used only to test whether an extreme value reverted.
 3. Channel siblings — same Combined Queue (from `dbo.CQN_Mapping`), this week + prior week.
 4. The investigation ladder — six SUM aggregates, one per hierarchy level:
    Business Org → Region → SubRegion → Country → Offering → Channel.
- Total read per investigation: about 183 rows = 0.2% of the table, in ~0.3s.
- Label the design rule on this lane: the table has NO index on these columns, so reads are scoped
  and capped deliberately; cross-queue work is AGGREGATED, never pulled as rows.
- Degradation path: if this fetch fails, the engine continues on the posted bundle alone and says
  what is missing (dashed amber).

L4 · BUSINESS CONTEXT for the selected queue
- `backend/wfm/context_repository/holiday_master.json` — built from
  `FC_RCA_Holiday_Master_Production.xlsx`: 12,197 active rows, 6,698 country-weeks, 6 aggregate
  groups. Per holiday it carries name, country, date, and before/after impact-window days.
- A fiscal calendar of 521 weeks mapped to real start/end dates, quarter and month.
- `holiday_context()` resolves the holidays in THIS week; `holiday_span()` resolves H−2 … H+2.
- Also resolved for the queue: Region / SubRegion / Country / Offering / Channel / Volume_Category,
  and which context elements are Available vs NotApplicable vs Missing.
- KEY POINT to show: a week whose own `Holiday_Count = 0` can still be pre- or post-holiday,
  because an adjacent holiday's impact window reaches into it.

L5 · DETERMINISTIC ENGINE — `backend/wfm/spec_engine.py :: investigate()`, 15 canonical steps
Group them as five blocks and show them strictly in order:
- Steps 1–4  Receive data → Validate quality → Calculate adherence → Detect ±5% breach.
             DECISION NODE: inside ±5% → STOP, return "no RCA generated" WITH the reason.
- Step 5     Build business context (from L4).
- Step 6     Generate candidate hypotheses from a FIXED catalogue of 23 entries in 6 categories.
             Four states, never conflated: Generated / NotApplicable / Suppressed / Rejected.
- BETWEEN 6 AND 7 (show this as its own block — the position is forced, not a preference):
             the deterministic evidence layer runs here because it needs the GENERATED hypothesis
             IDs, and steps 7–8 need its results:
               • `lag_analysis` — Spearman at lags 0/1/2/4/8, level AND change, half-history
                 stability, coverage classes populated / sparse / absent
               • `forecast_response` — expected demand (median), exact miss decomposition
                 (forecast-side + demand-side == actual − forecast), response adequacy,
                 the 4-condition FORECASTABILITY GATE
               • `holiday_response` — phases H−2…H+2 measured against the queue's OWN non-holiday
                 baseline, consistency rate, whether the plan historically allowed for it
               • `data_granularity` — what the data grain can and cannot support
               • `fc_evidence` — exact ASU decomposition (population vs contact-rate effect),
                 criticality (5 bands), the 7 miss mechanisms, and the DIRECTION-COHERENCE GATE
- Steps 7–8  Collect SUPPORTING evidence, then CONTRADICTORY evidence (actively sought, not
             incidental).
- Step 9     Evaluate only the statistics the hypotheses asked for. NO N×M correlation sweep.
- Step 10    Recursive WHY until the data stops answering  → then an LLM call to reword it (see L6).
- Step 11    Cross-examination — 23 fixed challenge questions designed to DISPROVE, answered from
             features, fully deterministic, NO LLM.
- Step 12    Confidence — 8 weighted dimensions, 8 caps. Calculated, never chosen by a model.
- Step 13    Select root cause + miss mechanism + criticality + recommendations.
- Step 14    Executive summary — the ONLY generative step (see L6).
- Step 15    Persist audit trail + SHA-256 input fingerprint.
Show the two ORDERING CONSTRAINTS as annotations, because they are structural:
  • Step 6 BEFORE step 9 — hypotheses select the statistics (otherwise it is fishing).
  • Step 11 BEFORE step 12 — challenge before confidence (a cap depends on the outcome).

L6 · LLM LAYER — TWO models, both hosted on NVIDIA, called with the SAME API key
Endpoint for both: `https://integrate.api.nvidia.com/v1/chat/completions`
- MODEL 1 (primary) `nvidia/nemotron-3-super-120b-a12b` — measured 22–29s. It does THREE jobs:
    (a) rewords the root-cause chain            [step 10]
    (b) writes the executive summary            [step 14]
    (c) ANSWERS each interrogation question, strictly from the evidence bundle   [prompt 1]
- MODEL 2 (interrogator) `openai/gpt-oss-20b` — measured 25–67s. ONE job:
    (d) ASKS the interrogation questions — reads the findings and asks what they leave
        unexplained                                                              [prompt 2]
    "openai/" is only the model's origin; it is SERVED BY NVIDIA on the same key.
- Show the interrogation as a two-stage loop:
    prompt 2 (MODEL 2) produces 3–5 questions, each with an `arises_from` field
      → optional ONE schema-repair retry, to the SAME model, if a required field is missing
      → then prompt 1 (MODEL 1) answers EACH question in its own separate call
        (one call per question on purpose — batched, the model collapsed onto whichever finding was
         most striking and returned the same answer twice)
- TOTAL: typically 6–8 LLM calls per investigation. Read timeout 150s.
- Why the split matters — annotate it: one model doing both asking and answering shares its own
  blind spots; it is least likely to ask about the thing it did not think to look at, and then it
  judges whether the data can answer.
- FALLBACK (dashed amber): if MODEL 2 fails, MODEL 1 asks instead — the section degrades rather
  than disappearing — and the terminal prints a `[FC-RCA] FELL BACK` line so a silent fallback
  cannot hide.
- FALLBACK (dashed amber): if ANY LLM call fails, the RCA is still returned complete and marked
  "Incomplete", meaning only the PROSE is missing. Every figure, cause, confidence score and
  recommendation is already computed.
- HARD CONSTRAINT to annotate on this lane: the LLM never computes, ranks, scores or selects. Its
  output is validated — strict JSON schema, and every number it writes must trace back to the
  inputs (an invented figure is a hard failure).

L7 · OUTPUT & RENDER
- The engine returns a `decision_card` with 18 sections plus additive keys
  (`miss_mechanism`, `criticality`, `forecast_response_diagnostic`, `lagged_driver_evidence`,
   `holiday_response`, `weekend_diagnostic`, `asu_decomposition`, `evidence_resolution`,
   `fc_evidence_index` with items E1–E14, `unexplained_observations`, `miss_streak`).
- The browser calls `renderDecisionCard()` → `layoutCardSections()`, which groups the panels into
  SIX tabs: Decision · Calendar · Confidence & Recommendation · Statistics · Challenge · Reference.
- The analyst reads: Executive Summary → Why This Happened (ranked bullets) → Root Cause →
  Confidence → Criticality → Evidence → Forecast Response → Calendar → Drivers → Evidence Index →
  Recommendations → Limitations.
- Also show a separate small path: `POST /api/rca-summarise` for an on-demand summary regeneration.

============================================================
STYLE REQUIREMENTS
============================================================
- Number the major stages 1…N along the flow so a presenter can talk through it in order.
- Make the THREE decision/gate nodes visually obvious (diamonds):
    the ±5% threshold gate, the forecastability gate, and the direction-coherence gate.
- Make all fallback/degradation edges DASHED and amber, and label each with its trigger.
- Use a hexagon (or another distinct shape) for each of the 4 LLM call types, labelled
  "MODEL 1" or "MODEL 2" so the split is unmistakable.
- Keep every node label short. Put detail on edges or in a small legend box.
- Include a compact legend: deterministic · LLM · gate · fallback · data store.
- No gradients, no clip-art, no drop shadows. It must stay legible in greyscale print.
```

---

## If you want an image instead of Mermaid

Append this to the prompt:

```
Also produce a second version as a single wide PNG-style diagram suitable for a 16:9 slide,
1920x800 or wider. Prioritise legibility of the lane titles and the LLM call boxes over decoration.
```

## Follow-ups worth sending after the first reply

- *"Collapse L5 into 5 blocks — the 15 steps are too dense for the slide."*
- *"Now produce a simplified one-line-per-lane version for a 30-second explanation."*
- *"Add the numbers to each lane: 114,436 rows · 157 weeks · 23 hypotheses · 23 questions ·
  8 confidence dimensions · 6–8 LLM calls."*
