# Walkthrough — what exists, what a result contains, and what is left to do

Branch `spec-v2-refactor`. Written 2026-08-11 from a live run against
`dbo.Input_To_ML_Full` on `10.10.9.75`. Every figure below was verified against SQL, not read
off the screen.

---

## 1. What has actually been built

### The engine

Two RCA engines live side by side behind `POST /api/rca-investigate`, selected by `mode`:

| `mode` | Engine | Returns |
|---|---|---|
| `wfm` (default) | the WFM cross-functional engine | the original response shape |
| `spec` | **FC_RCA v2.0.0** — the canonical 15-step workflow | an Executive Decision Card |
| `legacy` | the original single-pass engine | the original shape |

`spec` is the new work. It is a **separate engine, not a rewrite** — the same queue can be
investigated both ways and compared, and rollback is a query parameter rather than a revert.

**26 modules** in `backend/wfm/`. The spec-v2 core:

| Module | Lines | What it owns |
|---|---|---|
| `spec_engine.py` | 1,150 | the 15-step sequence, gates, response assembly |
| `statistical_evidence.py` | 595 | 14 metrics over 13/52/104-week windows, standard library only |
| `decision_card.py` | 523 | the 10-section Executive Decision Card |
| `confidence.py` | 377 | confidence **calculated** from 8 weighted dimensions, never assigned |
| `cross_examination.py` | — | challenge questions that try to **disprove** each hypothesis |
| `hypothesis_catalogue.py` | — | a **fixed catalogue of 23** hypotheses with Python-evaluated conditions |
| `driver_gate.py` | — | a driver may only be a cause where `Pearson r ≥ 0.3` **for that queue** |
| `recursive_why.py` | — | asks WHY to a bounded depth over findings actually made |
| `fiscal_calendar.py` | — | real 4-4-5, with 53-week years absorbed into Q4 as 4-5-5 |
| `context_repository/holiday_calendar.py` | — | holiday lookup with an impact window into adjacent weeks |
| `why_rephrase.py` / `narrative_prompt.py` / `why_prompt.py` | — | the three places an LLM is allowed to write |

### Data loaded into SQL

| Table | Rows | Notes |
|---|---|---|
| `dbo.Input_To_ML_Full` | **88,816** | 427 queues, FW202401–202752, all 5 channels (Voice 36,816 · Email 26,416 · Chat 15,184 · Social Media 9,568 · Case 832) |
| `dbo.Holiday_Master` | **9,757** | from `FC_RCA_Holiday_Master_Production.xlsx`, 79 country keys |
| `dbo.Fiscal_Calendar_Week` | 521 | week → start, end, quarter, month |
| `dbo.Holiday_Country_Alias` | 50 | maps `Country` in the data to the holiday key — without it 4 of 49 countries join to nothing |
| `dbo.Holiday_Aggregate_Group` | 8 | AMER_GROUP, BENELUX, EMEA_GROUP, NORDICS, ROLA, eCIS |
| `dbo.CQN_Mapping` | 532 | 100% coverage of the 427 queues |
| `dbo.CQN_Forecast_Pair` | 522 | Sheet 3 data pairs |
| `dbo.Input_To_ML` | 66,612 | the original table, untouched |
| `dbo.Input_To_ML_P1` | 7,350 | the `file1.csv` extract — **Voice only** |

### Tools

**Loaders** (`backend/`): `upload_excel_to_sql.py`, `upload_cqn_mapping.py`,
`load_holiday_master.py` (xlsx → JSON), `load_holiday_to_sql.py` (JSON → 4 SQL tables).

**Verification** (`results/`): `smoke_test_modules.py` (12 modules), `spec_compliance_check.py`
(42 clause checks × 2 providers), `statistical_engine_check.py` (57 checks, recomputes every
metric with a second independent implementation), `cqn_mapping_integrity.py`,
`run_validation.py`, `run_llm_ranking.py`, `multi_model_compare.py`.

**Launcher**: `run.py` — port check, config check, holiday-master pre-flight, optional
`--test` gate, health wait, browser. `--check`, `--port`, `--no-browser`.

### Models

`nvidia` (4 models), `groq` (1), `gemini` (4 flash). Gemini needed three fixes before it worked
at all — see the TODO.

---

## 2. A real 2027 result, end to end

**Case chosen deliberately, not sampled**: real volume, variance far above the 50-contact
materiality floor, a clear but not absurd miss, and enough history that seasonal and trend
findings are dependable.

```
CHK Cons eBiz Basic    FW202722
APJ / CCC / China / Basic / Email
plan FY27 Jun Projection · forecaster Brian Tan · 178 weeks of actuals

forecast   2,565.81
actual     3,498
variance     +932 contacts
adherence   -36.33%   (under-forecast — actual ran above plan)
```

Run with `?mode=spec&interrogate=1`, Gemini `gemini-flash-lite-latest`.
**Wall 15.3 s**, of which the narrative took **1.86 s**. Status **Complete**.

### What came back

**Root cause** — `DEM-01 Demand Spike`, cross-examination *Accepted with Caveats*.

**Why-chain, level 0** (the best sentence in the whole report):

> Under-forecast of −36.3% — 932 contacts against plan, and this is not a one-off: the plan
> has been out in the same direction repeatedly, averaging 600 contacts a week.

**Hypotheses** — 6 generated from the catalogue of 23; 17 recorded Not Applicable with reasons
and no confidence penalty:

```
CAL-04 Seasonality          DEM-01 Demand Spike
FC-01  Forecast Bias        FC-02  Trend Misidentification
STA-02 Drift                STA-03 Momentum Shift
```

**Cross-examination** — 13 to 16 challenge questions each. **All six survived.**

**Confidence** — `Low 68.7%`, calculated Medium then **capped**: ContradictoryEvidence scored
0.3774 against a 0.40 threshold. Two dimensions excluded as not relevant, without penalty
(ModelAgreement, HistoricalConsistency).

**Business context** — 5 of 5 applicable elements available. Holiday calendar consulted:
`applies: false`, no holiday in the week or its window. Drivers: 3 passed the gate,
`Actual_ASU` primary.

**Statistics (13-week window)** — MAE 599.92 · WAPE 22.19% · bias +553.43 · n=13 ·
CoV over 104 weeks 0.2211. Strongest finding: *"Forecast baseline is drifting, not just missing."*

**Interrogation** — 4 questions asked, 3 answered from evidence, 1 reported unanswerable.

**Audit** — fingerprint, catalogue/challenge/confidence-weights/prompt versions all `2.0.0`,
17 step entries, `narrative_model: gemini/gemini-flash-lite-latest`, `narrative_seconds: 1.86`.

### Reading it honestly

The finding is defensible: a queue under-forecast by 932 contacts, on a plan that has been out
in the same direction for weeks, with drift confirmed statistically over 13 weeks. The
recommendation follows — re-baseline.

But **`recommendations` came back empty**, and the root-cause *statement* is the catalogue's
condition text (*"actual exceeds forecast beyond the volatility band"*) rather than a
diagnosis. The good sentence is in the why-chain, not where the reader looks first.

---

## 3. TODO

### P0 — the engine reaches conclusions the evidence does not support

- [ ] **Cross-examination eliminates nothing, and that pins every report to Low confidence.**
      Two unrelated queues, measured:

      | Queue | Survived | ContradictoryEvidence | Confidence |
      |---|---|---|---|
      | CHK Cons eBiz Basic FW202722 | **6 of 6** | **0.3774** | Low 68.7% |
      | India Cons IW FW202632 | **6 of 6** | **0.3774** | Low 67.4% |

      Identical to four decimal places on different queues, different countries, different
      channels. The chain is mechanical: nothing is eliminated → every hypothesis survives →
      *"N other hypotheses survived and explain the same movement"* → ContradictoryEvidence
      pins just under the 0.40 gate → **every RCA is capped to Low**. A confidence score that
      is always Low carries no information. Fix the elimination, and the score starts moving.

- [ ] **A holiday cause is accepted without testing whether the holiday week was actually
      lower.** `Czech Republic Comm Client ProSupport Chat` FW202709 was diagnosed as
      *"Good Friday reduced the number of contactable days and the plan failed to reflect that
      drop"* — while actual (39) was **7.7× the plan** (5.05). Good Friday is genuinely in that
      week, but the holiday week's actual sits only **−4.9%** below the surrounding 8-week mean
      (41.0) — about **two contacts**, against a 34-contact gap. Sixteen challenge questions
      passed it as *Accepted with Caveats*. **Add the one challenge that matters:** a calendar
      cause must show the holiday week materially below adjacent non-holiday weeks.

- [ ] **No hypothesis can catch a plan-value collapse inside an unchanged plan vintage** — and
      that was the real cause of the case above:

      ```
      FW202707   plan 16.5   actual 38   FY27 Mar Projection
      FW202708   plan  5.0   actual 39   FY27 Mar Projection   <- plan collapses
      FW202709   plan  5.0   actual 39   FY27 Mar Projection   <- week investigated
      FW202710   plan  9.5   actual 31   FY27 Apr Projection   <- plan recovers
      ```

      Demand never moved; the plan broke for two weeks. Statistically the plan is the anomaly
      (z = **−1.39**) and the actual is not (z = **+0.89**). `plan_restatement` cannot fire
      because it tests whether the plan **name** changed — the name did not.

- [ ] **The scope narrative states something false.** It prints *"Every level above this one is
      within threshold, so this is where the wider pattern begins"* while the table beside it
      shows Region **+6.4%**, SubRegion **+10.7%** and Country **+25.7%** all exceeding. Only
      Offering (+2.6%) is within. Also unreported: every level above is *positive* while the
      channel is *negative* — the queue moves opposite to its parents, which is diagnostic.

- [ ] **The interrogation rationalises instead of refusing.** It correctly caught a 16-vs-39
      contradiction, then explained it away — *"16 describes the expected level on Good Friday
      alone"* — with nothing behind it. A fabricated reconciliation is worse than
      "cannot be answered". Neither 16 nor the claimed "normal level of 22" exists in the data
      (the 11 prior weeks average 42.9); 16 matches the *previous plan* value of 16.5.

### P1 — the report is missing content it already has

- [ ] **`recommendations` is empty on a Complete report.** Measured on the walkthrough case.
- [ ] **`root_cause.statement` shows the catalogue condition, not a diagnosis.** The usable
      sentence is in `why_chain.levels[0].answer` and never surfaces first.
- [ ] **Confidence dimensions carry `state: None`**, so the dimension table's
      Available / Missing colouring cannot work.
- [ ] **Holiday-occurrence history is absent from the interrogation bundle.** The interrogator
      said it could not list prior Good Fridays with their gaps — **SQL answers that in one
      join**, proven on `UKI Alienware Email`: Good Friday over-forecast every year
      (+17.6%, +26.4%, +22.2%, +22.2%) with the plan revised between years and the miss
      persisting. Same class of gap as the plan-vintage series that was already fixed.
- [ ] **The interrogation refuses questions its own evidence answers.** It asked for the plan
      value for FW202709; it is 5.05, in `forecast_summary`, cited by its own third answer.
- [ ] **ASU is reported as primary driver while being NULL for the target week.** Business
      Context says *"Installed base (ASU): Not applicable"*; Demand Drivers says
      *"Actual_ASU is primary"*.
- [ ] **A full RCA is generated on sub-materiality misses.** 34 contacts against a 50-contact
      floor still produced a confident holiday narrative. The marker fires and the contradictory
      evidence says the percentage overstates significance — but the diagnosis is issued anyway.

### P2 — correctness and hygiene

- [ ] **`narrative_prompt.py` documents itself as "the ONLY place an LLM is invoked".** There
      are **three**: `why_rephrase.apply`, `_narrate`, `_interrogate`.
- [ ] **`renderProbe` throws on every page load** — `document.getElementById('kbCount')` with no
      null guard (`rca_console.html`). Logged in every Canary run since V0.1 and still open. It
      makes real console errors easy to miss.
- [ ] **Gemini needs a fallback chain.** Three faults were fixed to make it work at all: no
      `gemini` entry in `PROVIDER_ENDPOINTS`; `_narrate` returning its placeholder `"unknown"`
      when no endpoint resolved; and Google rejecting `seed` with
      `HTTP 400 Unknown name "seed"`. It still hits free-tier **429** under repeated use —
      `gemini-3.6-flash` failed where `gemini-flash-lite-latest` succeeded, so try the siblings
      before giving up.
- [ ] **The config week filter disagrees with the loaded data.** `config.json` says
      `202500..202699`; the table holds `202401..202752`. A reload would silently truncate.
- [ ] **`active_rows` is misleading in `holiday_master.json`** — it counts rows *read* (12,197),
      not rows *kept* (9,757 after name de-duplication within a country-week).
- [ ] **No holiday validation tool.** Partly covered: SQL and the engine's own lookup agree on
      40 of 40 sampled country-weeks, totals match 9,757 both sides. A permanent
      `results/holiday_master_check.py` would close it.
- [ ] **Casing is inconsistent in the holiday source** — `Christmas Day` vs `new year's day`.

### P3 — deferred by decision

- [ ] Outage records, campaign calendar, product releases — the Business Event Repository is
      not deployed, so it reports NotApplicable rather than pretending to be empty (BR-202).
- [ ] The channel-mix drill-down (Region → SubRegion → Country → Offering → Channel) is parked
      on `wip/rca-drilldown`, rejected on review. The analysis was correct; the presentation was
      not.

---

## 4. How to run it

```
python run.py                  # deps, checks, backend, browser
python run.py --check          # pre-flight only
python run.py --test           # gate the launch on the 12-module smoke test
```

Then pick a flagged queue and set the **⚙️ Engine** dropdown to
**FC_RCA v2.0.0 — Decision Card**. It defaults to `WFM (current)`, so a fresh page load shows
the older engine's output.

### Suite status

| Suite | Result |
|---|---|
| `smoke_test_modules.py` | 12 / 12 |
| `spec_compliance_check.py` | 42 PASS / 0 FAIL / 0 SKIP (2 providers) |
| `statistical_engine_check.py` | 57 PASS / 0 FAIL |
| `cqn_mapping_integrity.py` | 6 PASS / 0 FAIL / 4 INFO |

The suites pass. **They do not cover the P0 findings** — no check asks whether
cross-examination actually eliminates anything, or whether an accepted cause agrees with the
direction of the miss. That is the gap that let the Good Friday conclusion through.
