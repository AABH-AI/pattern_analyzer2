# Prompt — generate the RCA Console architecture

Copy everything below the line into your diagramming or writing tool. It is self-contained: every fact
is stated, so nothing has to be inferred or invented.

Facts verified against branch `test3` at commit `773c943` on 2026-08-24, by reading the live database
and the running source. If you regenerate this prompt later, re-read them — a stale fact sheet is worse
than none, because it looks authoritative.

---

## TASK

Produce an architecture description of the **RCA Console** — one application, as it exists on git branch
`test3` at commit `773c943`. Cover it end to end: the browser, the API, the analysis engine, the data
source, the language-model calls, and the guardrails.

## HARD CONSTRAINTS

1. **Use only the facts in the FACT SHEET below.** Do not add components, services, queues, caches,
   containers, message brokers or cloud services that are not listed. This system is smaller than a
   typical enterprise architecture and the accuracy matters more than the impressiveness.
2. **Describe only the RCA Console.** Ignore any other tool, branch or historical version.
3. **Do not invent numbers.** Every figure you need is below. If a figure you want is not below, say
   "not measured" rather than estimating.
4. **Do not describe the two other engines** (`mode=legacy`, `mode=wfm`) beyond noting they exist behind
   the same endpoint. The Decision Card comes from `mode=spec` only.
5. Flag anything below that looks internally inconsistent instead of silently smoothing it over.

## WHAT TO PRODUCE

1. **A layered diagram** — browser → API → engine → data, with the three language-model calls shown as
   side calls that the main path does not depend on. Mermaid or equivalent.
2. **A request walkthrough** — one numbered sequence from the user's click to the rendered card, naming
   the actual function and module at each hop.
3. **A data-flow section** — which SQL query feeds which analysis, and which card section each analysis
   ends up in.
4. **A component table** — every module named below, its responsibility, and what it depends on.
5. **A guardrails section** — the mechanisms that stop the system asserting more than the data supports.
   Treat this as a first-class part of the architecture, not a footnote; it is the part that determines
   whether the output can be trusted.
6. **A limits section** — what the architecture cannot do, and why.

Write for a technically literate reader who has not seen the code. Prefer plain sentences over
bullet fragments. Do not pad.

---

# FACT SHEET

## Identity

| | |
|---|---|
| Application | RCA Console — root-cause analysis for contact-centre forecast misses |
| Branch | `test3` |
| Commit | `773c943` |
| Purpose | Given one queue and one fiscal week that missed its forecast, determine why, state how confident that conclusion is, and state what could not be determined |

## Layer 1 — the browser

| | |
|---|---|
| File | `rca_console.html` — **one self-contained file**, 3,775 lines, 284 KB |
| External dependencies | **zero** — verified: no `src="http`, no `href="http`, no CDN reference anywhere in the file |
| Libraries | none. No framework, no build step, no bundler, no npm install |
| Rendering | plain DOM string assembly in vanilla JavaScript |
| Offline mode | the file opens directly from disk and accepts a weekly upload, with no backend at all |

Front-end responsibilities: load the dataset once, compute the flag list client-side (every queue-week
whose absolute adherence exceeds the band), let a user pick one, POST it for investigation, and render
the returned card.

The card is rendered into **six tabs**, in this order: `Decision`, `Calendar`,
`Confidence & Recommendation`, `Statistics`, `Challenge`, `Reference`. An accordion layout is available
behind a toggle and the choice is remembered per browser. The tab layout is a post-process over the
assembled card: it splits on panel boundaries and buckets each panel by its own title.

Three post-processing passes run over the assembled card before it is shown: repeated whole sentences
collapse to "(as above)"; a list row that would consist only of that marker is dropped and counted; and
holiday names are never rewritten — a name must read exactly as the calendar says it.

## Layer 2 — the API

| | |
|---|---|
| Framework | FastAPI |
| Database driver | pyODBC, ODBC Driver 17/18 |
| Entry point | `backend/sql_backend.py` |
| Launcher | `run.py` / `run.bat` / `run.sh`, or Docker |
| Port on this branch | **9000** |

Seven endpoints:

| Method | Path | Role |
|---|---|---|
| GET | `/api/health` | is the backend up, is SQL configured, which table |
| GET | `/api/data` | the dataset the browser loads once |
| GET | `/api/queue-context` | scope context for one queue |
| GET | `/api/models` | which language models are available to pick |
| GET | `/api/cqn-mapping` | Combined Queue Name mapping |
| POST | `/api/rca-investigate` | **the main call.** `?mode=spec\|wfm\|legacy`, `&grain=weekly\|monthly\|quarterly`, `&interrogate=0\|1` |
| POST | `/api/rca-summarise` | the optional third model call; cached per queue + week + prompt version |

## Layer 3 — the analysis engine

`backend/wfm/` — **33 Python modules, 14,511 lines**. All arithmetic happens here. No figure on the card
is produced by a language model.

The modules that carry the architecture, largest first:

| Module | Lines | Responsibility |
|---|---|---|
| `spec_engine.py` | 1,809 | orchestrates the 15-step investigation; the only entry point for `mode=spec` |
| `fc_evidence.py` | 1,695 | forecast-response, holiday, weekend, ASU and criticality evidence blocks |
| `decision_card.py` | 1,290 | assembles the 19 numbered card sections from the finished analysis |
| `holiday_response.py` | 981 | calendar phases, phase effects, forecast capture, standing bias |
| `forecast_response.py` | 812 | was a signal available before the week, and did the plan react |
| `statistical_evidence.py` | 685 | the 13 statistical measures of the queue on its own history |
| `why_prompt.py` | 634 | the interrogation prompt |
| `business_report_generator.py` | 571 | narrative assembly for the WFM engine |
| `lag_analysis.py` | 544 | lagged driver relationships, stability across a split history |
| `cross_examination.py` | 536 | challenges the conclusion before confidence is scored |
| `recursive_why.py` | 527 | the why-chain, up to 6 levels deep |
| `narrative_prompt.py` | 396 | the narrative prompt **and the numeric grounding guard** |
| `confidence.py` | 377 | the 8 weighted confidence dimensions and the level caps |
| `holiday_events.py` | 354 | holiday identity, semantic families, weekday structure |
| `hypothesis_catalogue.py` | 332 | the 23 candidate explanations |
| `driver_gate.py` | 328 | whether a candidate driver is relevant at all |
| `prompts.py` | 307 | WFM engine prompts |
| `investigation_engine.py` | 266 | the WFM engine orchestrator |
| `why_rephrase.py` | 203 | plain-language rewriting of why-chain steps |
| `correlation_engine.py` | 201 | Spearman rank correlation |
| `fiscal_calendar.py` | 200 | fiscal week arithmetic |
| `data_granularity.py` | 199 | what the source can and cannot support |
| `skeptic.py` | 191 | rejects causes the evidence does not carry |
| `data_access.py` | 182 | **every SQL query lives here** |
| `channel_migration_detector.py` | 178 | week-over-week movement between channels |
| `hypothesis_generator.py` | 144 | selects which catalogue entries to test |
| `summary_prompt.py` | 139 | the third call's prompt and its grounding check |
| `common.py` | 124 | the adherence formula, shared constants |
| `llm_client.py` | 99 | provider calls, timeout, temperature, seed |
| `data_quality.py` | 75 | extreme-value and integrity checks |
| `temporal_reasoner.py` | 56 | time-order reasoning helpers |
| `hierarchy_analyzer.py` | 37 | scope-level helpers |

Engine characteristics:

- **15 canonical steps**, run in a fixed order. Two orderings are structural: hypotheses are formed
  before statistics are computed, and cross-examination runs before confidence is scored so its result
  can feed in.
- **23 hypotheses** across 6 categories — Business 5, Calendar 4, Demand 4, Statistical 4, Data
  Quality 4, Forecast 2. Every one is reported with a state and a reason, including the rejected ones.
- **8 confidence dimensions**, weighted: ContradictoryEvidence 0.20, EvidenceStrength 0.18,
  BusinessRuleValidation 0.15, StatisticalAgreement 0.14, DataSufficiency 0.12, ContextCompleteness
  0.10, HistoricalConsistency 0.06, ModelAgreement 0.05.
- **86 named numeric constants** across the modules. Every threshold is a named constant with a comment
  at its definition; none is an unexplained literal inside a condition.
- Output: a response object with **42 top-level keys**, containing a Decision Card at version **2.1.0**
  with **19 numbered sections** (`1_executive_summary` … `19_statistical_profile`).

## Layer 4 — the data source

| | |
|---|---|
| Server | `10.10.9.75` |
| Database | `Playground` |
| Table | `dbo.Input_To_ML_Full_138_Trimmed` |
| Size | **114,436 rows · 32 columns** |
| Coverage | **427 queues**, **49 countries**, **3 regions**, **5 channels**, **4 offerings** |
| Fiscal weeks | **202401 – 202908**, 268 distinct weeks |
| Access | read-only. The application has no `INSERT`, `UPDATE` or `DELETE` against this table |

Scale of the problem:

| | |
|---|---|
| Queue-weeks with a scoreable forecast | **71,780** — about **403 a week** |
| Missing by more than the 10% band | **44,883**, which is **63%** |
| …and large enough in absolute terms to act on | **21,788** |
| Suppressed by the 50-contact materiality floor | **23,095** |
| Contacts handled across the file | **60,310,135** |
| Contacts planned across the file | **78,567,681** |

The four measures everything derives from: `Actual_Offered` (contacts that arrived), `fcst_offered`
(the plan), `Planned_ASU` / `Actual_ASU` (installed base), `Final_Units` (shipments, a candidate leading
signal).

**A structural limit that must appear in the architecture.** The table has seven columns named `Monday`
through `Sunday`. They are **holiday flags, not daily volumes** — every value is 0 or 1, and on
non-holiday high-volume weeks every one is 0 even though those weeks took contacts daily. All four
volume columns are weekly. There is therefore **no daily demand figure anywhere in the source**, and the
system reports that weekend effect cannot be isolated from a fiscal-week total rather than estimating
it. Any architecture that implies daily analysis is wrong.

Supporting tables:

| Table | Role |
|---|---|
| `dbo.Holiday_Master` | holiday dates by country and fiscal week; 36 distinct `holiday_type` values |
| `dbo.Holiday_Semantic_Group` | 23 event families, so one holiday spelled several ways counts once |
| `dbo.Holiday_Name_Alias` | raw name → family, scoped by country |
| `dbo.Holiday_Name_Pair_Review` | merge decisions taken, plus **185 pairs still awaiting a business answer** |
| `dbo.CQN_Mapping` | authoritative Combined Queue names |

### The queries, all in `data_access.py::fetch_wfm_context`

**Six query shapes, up to eleven statements per investigation** — one of them runs once per scope level.
Every query is parameterised, so a queue name cannot alter the SQL.

| # | Fetches | Window and why | Feeds |
|---|---|---|---|
| 1 | this queue's own history | up to **157 weeks** — two years plus, so the same week last year exists | statistical profile, phase effects, drift, volatility, outlier test |
| 2 | the **4 weeks after** the target | so a rebound is measurable | post-holiday rebound, repeatability |
| 3 | the same week at **6 scope levels** — Business Org → Region → SubRegion → Country → Offering → Channel | answers "this queue, or the whole region?" **This is the one that runs six times** | the scope ladder under Root Cause |
| 4 | the other channels in the same scope | did demand change channel rather than disappear | week-over-week channel migration |
| 5 | the queue's Combined Queue name | group related queues the way the business groups them | channel sibling grouping |
| 6 | the holiday calendar for that country and week | was there a published reason | calendar context, phases, semantic families |

## The two metrics, and nothing else

```
adherence_pct = (1 − actual / forecast) × 100        signed; negative = demand above plan
accuracy      = 100 − MAPE                          MAPE = mean|actual−forecast| / mean(actual) × 100
```

The sign conventions are deliberately opposite and both are shown, so no reader has to infer a
direction. Adherence is never scored when the forecast is zero or missing — the result is null, not
zero. The investigation band defaults to 10%; the generation threshold is fixed at 5% and is a worklist
control only.

## The language-model calls — three, all optional to the result

| # | When | Fed | Guard |
|---|---|---|---|
| 1 | step 14, every investigation | the finished figures | numeric grounding: a number in the prose that is not in the inputs **discards the entire narrative** |
| 2 | `interrogate=1` | the evidence file | answers must come from the evidence, never the model's own knowledge |
| 3 | on click only, `/api/rca-summarise` | **deterministic figures only** — never the prose from calls 1 or 2 | same grounding; cached per queue + week + prompt version |

Call 3 is deliberately not fed the earlier prose: summarising a summary would let a first-call error
return as established fact in the paragraph most likely to be forwarded onward.

Determinism: `TEMPERATURE 0.0`, `TOP_P 1.0`, `SEED 20260730`, timeout 150s. Same input, same words.

**If every model call fails, the investigation still completes.** Status reads `Incomplete`; every
figure, cause, confidence score and recommendation is present. Only the prose is missing. This is the
single most important property of the architecture and should be drawn as such.

## Guardrails — treat as first-class

| Guard | Rule |
|---|---|
| Numeric grounding | a figure in model prose absent from the inputs discards the prose. A genuine rounding is accepted within a 5% drift cap; an invented number is not |
| Materiality floor | 50 contacts. A 90% miss on 20 contacts is arithmetic, not a finding |
| Not measurable ≠ no effect | every failed gate reports why and how much data it would need |
| Absence of evidence ≠ evidence of absence | a weak correlation reads "not confirmed", never "not a driver" |
| Direction never discarded | −0.22 and +0.22 mean opposite things operationally |
| Identities must reconcile | the ASU split and the miss decomposition publish whether the parts sum to the whole |
| Robust statistics | median and MAD for outliers, so a single spike cannot inflate the threshold that would have caught it |
| Confidence caps are visible | a cap rides beside the score, never hidden behind a click |
| Missing dimension floors at 0.20 | absence of a measurement is not evidence against a finding |

## Test surface

| Suite | Result |
|---|---|
| module smoke | 12 / 12 |
| FC spec semantics | 190 / 190 |
| WFM diagnostics | 148 / 148 |
| narrative grounding | 21 / 21 |
| summary grounding | 14 / 14 |
| UI render, incl. repetition caps, tab attribution, table-squeeze | 20 Decision Cards |
| prompt2 conformance | 16 / 16 |
| new_prompt conformance | 34 / 34 |

Three permanent regression cases live in `results/` — a three-holiday card, a single-holiday card, and
an executive worked example. Each failed when first added, which is why they are there.

## Documentation already written — do not duplicate, reference

| File | Contains |
|---|---|
| `mathematics.md` | every formula, all 86 constants with rationale, the full data lineage |
| `EXECUTIVE_WALKTHROUGH.md` | the management-facing script: the scale, the data source, the SQL in plain English, every parameter on every tab with what to say about it, a worked example, the guardrails, and what is still open |
| `IMP_DOCS/holiday-semantic-groups.md` | the calendar work and every defect found and fixed |
| `AGENTS.md` | the runbook |

### What `EXECUTIVE_WALKTHROUGH.md` established, which the architecture should stay consistent with

- The scale figures above, all verified against the live database.
- Six query shapes, up to eleven statements, six ladder levels.
- The day-column limitation, volunteered rather than buried.
- A worked example: `Social Media English Basic` FW202422 — plan 18,932 against actual 25,697, a
  **6,765-contact under-forecast**, criticality **Critical**, root cause **Drift**, confidence 67.5%, 23
  hypotheses tested. The engine's own strongest line: the evidence implied moving the plan by **1,241**
  contacts and it moved **77**.
- Open items: 185 unresolved holiday pairs, no daily granularity from this source, Business Event
  Repository not deployed, and no independent review of the analytical logic.

## Known-open, and must not be presented as solved

1. **185 holiday name pairs** unresolved — needs a business decision, not code.
2. **No daily granularity** — the day columns are flags. Would require a new feed.
3. **Business Event Repository not deployed** — promotions and campaigns cannot be tested as causes; it
   is correctly reported as not-applicable rather than counted against confidence.
4. **Indonesia's Ascension is double-dated** in the holiday master — an upstream data issue, flagged
   rather than patched.
5. **No independent review** of the analytical logic. The suites pass; a second engineer has not
   reviewed the reasoning.
6. `fc_evidence.py` at 1,695 lines does too much and wants splitting.
7. The suites verify that the machinery ran and is self-consistent. They do **not** assert that a
   conclusion is correct — that would need labelled ground truth, which does not exist.
