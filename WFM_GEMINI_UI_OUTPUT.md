# WFM engine — the Gemini output as it runs on the UI

**Case:** `SA Indonesia Client Basic`, Fiscal Week **202716** (FY27 FW16)
**Engine selected in the console:** **WFM (current)** → `POST /api/rca-investigate?mode=wfm`
**Model:** `gemini-3.5-flash`, provider `gemini` — **1** call, **65.8 s**
**Run:** 2026-08-13T10:17:50Z, live `dbo.Input_To_ML_Full`, branch `spec-v2-refactor` @ `74f46c5`
**Result:** `investigation_meta.engine = "wfm-llm"` — the model genuinely answered; this is **not** a
deterministic fallback.

This document is the model-facing half. The arithmetic underneath it is verified line by line in
[WFM_MATH_AND_TOOL_EVIDENCE.md](WFM_MATH_AND_TOOL_EVIDENCE.md).

---

## 1. What the user sees

In [rca_console.html](rca_console.html) the engine picker offers **WFM (current)** and
**FC_RCA v2.0.0 — Decision Card**. This run used WFM, which renders through the standard investigation
panels. Response keys map to panels as follows:

| UI panel | Source key | State in this run |
|---|---|---|
| **Root Cause** (+ confidence meter) | `ranked_root_causes[0].title`, `confidence_score` | "Plan set 48% below what this week normally brings", **0.82** |
| **Proof — values from the data** | `proof[]` | 4 rows |
| **Key Findings** | `key_findings[]` | 5 bullets |
| **Supporting Evidence** | `supporting_evidence[]` | 1 item |
| **Rejected Hypotheses** | `rejected_hypotheses[]` | 1 (`channel_migration`) |
| **Statistical Evidence — queue level** | `statistical_evidence` | 14 metrics, 2 findings |
| **Historical Comparison** | `historical_comparison` | narrative + 5 data points |
| **Forecast Improvement Recommendations** | per-cause `recommended_action` | 4 actions |
| **Missing Information** | `missing_information[]` | 1 (`Actual_ASU`) |

`back_compat()` also fills the legacy keys (`primary_root_cause`, `secondary_contributors`,
`cause_type`, `technical_metrics`), which is why the existing console renders this engine with no
front-end change.

---

## 2. Executive summary — verbatim

> During Fiscal Week 202716, the SA Indonesia Client Basic queue experienced a significant
> under-forecast with a Forecast Adherence of -138.3%, as actual offered volume reached 152 contacts
> against a forecast of 63.8 contacts. Voice (SA Indonesia Client Basic) demand increased by 56
> contacts compared to the prior week, with no offsetting channel migration detected within the SA
> Indonesia Core Concentrix Combined Queue. This under-forecast was driven by a genuine surge in
> customer contacts, which coincided with a material 43% increase in upgrade and extended-protection
> plan units (Final_upp_units) to 109.0 units compared to the historical average of 76.0. The forecast
> plan failed to anticipate this volume because the baseline forecast was mis-scaled downward to 63.8
> contacts (33% lower than the queue's historical average of 94.5 contacts), and the under-forecast was
> inherited from the broader Offering level rather than being isolated to this specific channel.

Every figure in that paragraph is real and traceable: −138.3 %, 152, 63.8, +56 vs prior week, 43 %,
109.0, 76.0, 33 %, 94.5. **No fabricated numbers.** Note the model chose the honest **43 %** framing of
the `Final_upp_units` move rather than the z-score of 23.33 it was also given — the better of the two
available readings (see §6.2).

---

## 3. The four ranked causes

| # | Cause type | Confidence | Status | Title |
|---|---|---|---|---|
| 1 | `forecast_baseline_error` | **82 %** High | Verified | Plan set 48% below what this week normally brings |
| 2 | `inherited_from_higher_level` | **95 %** High | Verified | Forecast miss inherited from the Offering level |
| 3 | `installed_base_change` | **85 %** High | Verified | Surge in upgrade and extended-protection plan units |
| 4 | `genuine_demand_event` | **80 %** High | Verified | Unanticipated genuine demand surge |

### Rank 1 — statistically imposed, not model-chosen

Rank 1 did **not** come from Gemini. `statistical_evidence` computed it deterministically and displaced
the model's own first choice:

> `statistical_override_applied`: *"Statistical evidence (Plan vs seasonal norm (same week, prior
> years)) overrides the model's ranking: forecast_baseline_error is measured directly from this queue's
> own history. The model's causes are retained below as contributing factors."*

> **Explanation (rank 1):** The plan was set at 64 contacts for a week that has averaged 122 across 3
> earlier years (FW202416 195, FW202516 66, FW202616 106) — 48% below what this week of the year
> normally brings, and 42% below the queue's usual 109. Demand of 152 is in line with the week's own
> history, so the plan is the unusual value, not the demand.

> **Action:** Re-baseline this queue's forecast using the measured figures above.
> **Evidence grade:** `statistical (deterministic)`

This is the strongest claim in the response and it is the one the model did not write. Its confidence,
82 %, is also lower than ranks 2 and 3 — which is why the list is not in descending confidence order.

### Rank 2 — Gemini's own first choice, demoted

> **Explanation:** The under-forecast was driven by a systemic planning gap at the broader Offering
> level (CSG / APJ / SA / Indonesia / Basic) rather than an issue isolated to the Voice channel. Because
> the forecast model under-allocated volume across the entire Basic support tier in Indonesia, both the
> Offering and Channel levels experienced the exact same adherence miss.

> **Evidence:** Offering level adherence was −138.3 % with 152 actual against 63.8 forecast · Country
> level adherence was stable at 0.8 %, indicating the miss was highly concentrated within the Basic
> offering
> **Action:** Review and adjust the forecasting parameters at the Offering level for Indonesia Basic
> support to ensure volume is not systematically under-allocated.

Both figures are exact. The reasoning is sound but the conclusion is **degenerate**: this Offering
contains exactly one queue-week, so Offering and Channel are the same row. "Inherited from Offering" is
arithmetically true and operationally empty — there is no broader population to re-plan. The model's
own phrase *"rather than an issue isolated to the Voice channel"* is the part that does not hold: it
**is** isolated to this queue. Country, one rung up, is healthy at +0.8 %.

### Rank 3 — built on the weakest input in the payload

> **Explanation:** The under-forecast was driven by a material increase in the active supported
> customer population, because the number of upgrade and extended-protection plan units
> (Final_upp_units) rose to 109.0 units (a 43% increase over the historical average of 76.0 units).
> This expanded install base generated a higher volume of customer contacts that the forecast did not
> account for.

> **Action:** Review and update the demand planning assumptions to dynamically link the forecast
> baseline to changes in the upgrade and extended-protection plan unit volumes.

109.0 and 76.0 are exact, and 43 % is exact. **But the "historical average of 76.0" is the mean of two
weeks** — `Final_upp_units` is non-NULL in only 3 of 157 fetched weeks (FW202714 = 77, FW202715 = 75,
target = 109). The causal claim also has no measured support: `Final_upp_units` is not one of the four
correlation drivers, and all four of those were rejected for this queue. The recommended action —
re-link the baseline to this field — would wire the forecast to a field with 2 % coverage.

### Rank 4 — contradicts rank 1

> **Explanation:** The under-forecast resulted from a genuine spike in customer contacts to 152.0,
> which is 68% higher than the historical average of 90.3 contacts. Because the forecast baseline was
> set at 63.8 contacts (33% lower than the historical average of 94.5), the model was unprepared for
> any upward demand movement, creating a severe gap when actual volume rose.

Rank 1 says demand was normal and the plan was the outlier. Rank 4 says demand spiked. Both cite
correct numbers against different baselines (prior-year same-week 122.33 vs trailing-13-week 90.31),
and `forecast_sanity.verdict = "actual_anomalous"` supports rank 4 while the override supports rank 1.
Shipped side by side without the tension being named.

---

## 4. The guards that fired

### Skeptic — one hard rejection

| Cause challenged | Verdict | Reason |
|---|---|---|
| `channel_migration` | **rejected** | Migration not detected; total Combined Queue demand genuinely rose 58.3 % |
| `installed_base_change` | retained | *"…the extreme surge in Final_upp_units (z-score of 23.33) directly coincides with the anomalous actual demand spike this week, making it the most plausible physical driver."* |
| ranks 2, 3, 4 | retained | *"The feature this cause depends on is present in the data and its quoted figures reconcile."* |

The rejection is correct and code-enforced: `offset_share = 0.0`, so channel movements do not cancel
and this cannot be customers switching channels. The `installed_base_change` retention is the weak
link — the guard cites the n=2 z-score of 23.33 as grounds for keeping the cause, so the statistic that
should have disqualified the input is the one used to defend it.

### Language and terminology guards — 6 rewrites

| Original | Rewritten to |
|---|---|
| `outlier` (×2, in rank 1 explanation and evidence) | `unusual value` |
| `INVESTIGATION_LADDER.levels` (×4) | `higher-level check - levels` |

Working as designed: no statistics jargon and no internal payload key names reach the screen. Note the
rank-1 text in `primary_root_cause` still reads *"the plan is the outlier"* while
`ranked_root_causes[0]` reads *"the plan is the unusual value"* — the guard rewrote one copy of the
same sentence and not the other.

### Missing information — declared, not hidden

> Actual_ASU was missing for this week, which prevented a full driver decomposition analysis to isolate
> the exact contact-rate effect.

Correct and important: `Actual_ASU` is NULL for FW202716, so the exact volume-vs-rate decomposition —
the strongest attribution the system has — could not run. The engine says so on screen instead of
substituting a weaker cause silently.

---

## 5. Panels as rendered

**Proof — values from the data**

| Label | This week | Usual | Change |
|---|---|---|---|
| Forecast Offered | 63.79 | 94.53 | about 33% lower than usual |
| Actual_Offered | 152.0 | 90.31 | about 68% higher than usual |
| Planned ASU | 30,050 | 26,672.77 | about the same as usual |
| Planned units / shipment (Final_upp_units) | 109.0 | 76.0 | about 43% higher than usual |

**Key Findings**
- The forecast this week was 63.79, and actual demand was 152.0.
- Actual demand (152.0) was far from this queue's usual level of about 90.31, while the forecast (63.79) was about normal.
- This queue's misses have no consistent direction over recent weeks.
- The one similar queue moved the same way this week.
- Planned units for delivery (Final_upp_units) were 109.0 this week vs a usual ~76.0.

**Historical Comparison**
> Over the last 13 weeks, actual demand for this queue averaged ~90.3 contacts per week. The queue
> historically trends above forecast with an average adherence of -13.3%. Typical weekly error magnitude
> is about ~48.7%. This week's miss magnitude is 2.8x its typical historical variation. In the same
> fiscal week last year (FW 202616), actual demand was 106.0 contacts.

**Investigation trail** (`reasoning_narrative`, verbatim)
> The investigation began at the Business Org level (CSG, -3.9% adherence) and drilled down through
> Region (APJ, -1.6%), SubRegion (SA, 1.2%), and Country (Indonesia, 0.8%), all of which were within
> acceptable thresholds. However, at the Offering level (Basic, -138.3%), a severe under-forecast
> emerged, which was then directly inherited by the Voice channel (-138.3%). This indicates the
> forecasting error is systemic to the Basic offering in Indonesia.

Every percentage matches the ladder exactly. The final inference — "systemic to the Basic offering" —
overreaches: the Basic offering here is one queue-week.

**Business impact**
> The severe under-forecast of 138.3% (88 additional unplanned contacts) likely caused significant
> service level degradation, increased customer wait times, and put operational strain on the Voice
> support team in Indonesia due to under-staffing.

88 unplanned contacts is exact (152 − 63.79 = 88.21). The service-level consequences are unevidenced
inference — plausible, but no SLA, wait-time or staffing data is in the payload. Flagged because it
reads as measured on screen.

**Channel migration** — `detected: false`, grouped by the **authoritative** `dbo.CQN_Mapping`
(`is_cqn_proxy: false`), Combined Queue `SA Indonesia Core Concentrix`. Group total moved 96 → 152
(+58.3 %), `offset_share 0.0`, gaining `Voice`, losing none.

---

## 6. Assessment of the model's contribution

### 6.1 What Gemini did well
- **No fabricated numbers.** Every figure in every explanation traces to the payload.
- **Business language throughout** — no statistics vocabulary reached the user text; the guards found
  only one instance ("outlier") to rewrite.
- **Chose the defensible framing** of `Final_upp_units`: 43 % vs a two-week average, not the z-score of
  23.33 it was handed.
- **Correctly read the ladder**, quoting all six levels accurately and identifying where the breach
  starts.
- **Named its own blind spot** — the missing `Actual_ASU` is reported, not papered over.
- **Every cause carries an action and a status**, and the actions are specific rather than generic.

### 6.2 Where it went wrong
1. **Ranks 1 and 4 contradict each other** (plan-was-wrong vs demand-spiked) and both ship as Verified.
2. **Rank 3 is causally unsupported.** `Final_upp_units` has 3 non-NULL weeks in 157 and no measured
   relationship to demand for this queue, yet it ships at 85 % with an action that would bind the
   baseline to it.
3. **"Not isolated to the Voice channel" is wrong** — Offering and Channel are the same single row.
4. **Business impact asserts service-level damage** from no service-level data.
5. **All four causes are "High" confidence** (80–95 %) on a case where the strongest attribution tool
   was unavailable and every driver correlation was rejected. The confidence band does not reflect that
   evidence gap.

### 6.3 Where the harness, not the model, is at fault
- **Confidence does not descend with rank** (82 → 95 → 85 → 80) because the statistical override
  inserts its own 82 % at rank 1. This breaks check **L3** in
  [results/run_llm_ranking.py](results/run_llm_ranking.py), which asserts descending confidence — that
  check would FAIL on this response. The override needs to either carry the displaced confidence or be
  exempted from L3.
- **The n=2 z-score gated a cause.** `installed_base.material` is set from it and
  [wfm/skeptic.py:40](backend/wfm/skeptic.py#L40) uses that flag as the precondition for
  `installed_base_change`. A minimum-n guard on the bundle's z-scores would have made rank 3 ineligible
  before the model ever saw it.
- **`Final_upp_units` is mislabelled on screen** as *"Planned units / shipment"* in `proof` and
  *"Planned units for delivery"* in `key_findings`. The field glossary in
  [backend/rca_investigate.py:109](backend/rca_investigate.py#L109) defines it as *"Additional
  installed units under an upgrade / extended-protection plan"* — a different quantity from
  `Final_units` (shipment). Gemini described it correctly; the deterministic labels do not.
- **The void z-score is published** as `technical_metrics` → "Final_upp_units Z-Score: 23.33".

### 6.4 Verdict on `gemini-3.5-flash` for this UI
Usable. One call, 65.8 s (inside the 150 s `llm.timeout_seconds`), valid schema, no retry, no
fallback, correct business register, and no invented figures. Its errors are errors of **over-claiming
confidence and over-reaching inference**, not of arithmetic or fabrication — and the two most serious
(rank 3's eligibility, the confidence ordering) originate in the deterministic layer, not the model.

The comparison against `SA_INDONESIA_RCA_VALIDATION.md` is the encouraging part: the earlier engine
blamed a **holiday** for a week that ran *busier*, an explanation pointing the opposite way to the miss
and citing a holiday that did not exist. This run makes no such error — the direction-coherence gate
and the plan-vs-seasonal-norm metric on this branch put the correct cause at rank 1 and rejected
channel migration in code.

---

## 7. Reproducing this

```bash
cd backend && python -m uvicorn sql_backend:app --host 127.0.0.1 --port 8000
# then in the browser: http://localhost:8000/rca_console.html
#   -> select the queue / FW202716, Engine = "WFM (current)", model = Gemini 3.5 Flash
```

Or headless, exactly as the UI posts it:

```bash
curl -X POST "http://127.0.0.1:8000/api/rca-investigate?mode=wfm&provider=gemini&model=gemini-3.5-flash" \
     -H "Content-Type: application/json" -d @results/indonesia-wfm-gemini-bundle.json
```

Full captured response: [results/indonesia-wfm-gemini.json](results/indonesia-wfm-gemini.json).

**The LLM half is not reproducible byte-for-byte** — ranking, wording and confidence percentages vary
between runs, and `gemini-3.5-flash` was chosen over `gemini-flash-latest` precisely because it is the
more stable id. The deterministic half (§5's proof values, the ladder, the statistical evidence) will
reproduce exactly while the source table is unchanged.
