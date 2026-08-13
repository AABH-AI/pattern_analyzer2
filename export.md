# Export / handoff — Forecast RCA Studio, as of 2026-08-13

Written so a new session (or a new person) can pick this up with nothing lost. Every figure here was
verified against SQL or the code, not recalled.

---

## 1. Where everything is

### Branches — and which one to use

| Branch | Head | What it is |
|---|---|---|
| **`spec-v2-refactor`** | `74f46c5` + local | **Current work.** FC_RCA v2.0.0 engine. All session work is pushed here. |
| `main` | `1d6d170` | The management-approved WFM engine. Do not disturb without asking. |
| `MD` | `e1e75cc` | **The 17 FC_RCA specification documents.** Contains no code. |
| `wip/rca-drilldown` | `f9601ff` | Channel-mix drill-down — built, verified, **presentation rejected**. Recoverable. |
| `UI` | `1591422` | 8 ahead of main, 3 behind. Source of `run.py`. |
| `approved-test` | `c38ff3f` | Sibling of spec-v2 (diverged 5 commits each way) + `knowlegebase.md`. |

**The code and its specification are on different branches.** spec-v2's modules say they implement
`FC_RCA_RCA_Methodology.md`, `FC_RCA_Business_Rules.md`, `FC_RCA_Statistical_Framework.md` and four
more — all seven live on `MD`, none on `spec-v2-refactor`, and `MD` has none of the code. **Neither
branch is reviewable alone.**

### Worktrees on this machine

```
...\rca patternz\pattern_analyzer2      -> approved-test (the original clone)
...\rca patternz\spec-v2-refactor       -> spec-v2-refactor (current work)
```

`backend/config.json` and `backend/.env` are **gitignored** — they were copied by hand into the
spec-v2 worktree. A fresh worktree needs them or SQL features silently vanish.

### SQL — `10.10.9.75`, table in force is `dbo.Input_To_ML_Full`

| Table | Rows | Note |
|---|---|---|
| `dbo.Input_To_ML_Full` | **88,816** | 427 queues, FW202401–202752, all 5 channels |
| `dbo.Holiday_Master` | 9,757 | from `FC_RCA_Holiday_Master_Production.xlsx` |
| `dbo.Holiday_Country_Alias` | 50 | **without this, 4 of 49 countries join to nothing** |
| `dbo.Fiscal_Calendar_Week` | 521 | |
| `dbo.Holiday_Aggregate_Group` | 8 | |
| `dbo.CQN_Mapping` | 532 | 100% coverage of the 427 queues |
| `dbo.CQN_Forecast_Pair` | 522 | |
| `dbo.Input_To_ML` | 66,612 | original, untouched |
| `dbo.Input_To_ML_P1` | 7,350 | the `file1.csv` extract — **Voice only** |

**Known mismatch:** `config.json` week filter says `202500..202699` while the table holds
`202401..202752`. A reload would truncate differently.

### How to run

```
cd <spec-v2-refactor worktree>
python run.py                # deps, checks, backend, browser  (port 8000)
python run.py --check        # pre-flight only
python run.py --test         # gate the launch on the 12-module smoke test
```

Then set the **⚙️ Engine** dropdown beside *Investigate Root Cause* to
**FC_RCA v2.0.0 — Decision Card**. It defaults to `WFM (current)`, so a fresh page load shows the
older engine — this has caused confusion more than once.

---

## 2. The business decisions on record

**RCA type priority (2026-08-13)**

1. **Channel mix** — Voice→Chat, Chat→Email, Email→Case, all combinations
2. **Holiday** — a major factor in explaining a high or low contact rate
3. **Plan vs seasonal norm** — the base case

**Earlier decisions**

- Statistical evidence is the **strongest** evidence available; it overrules the model where they
  conflict, and always runs — including when the miss is inherited from a higher level.
- No SHAP. Deterministic driver attribution only; no new dependencies.
- `Final_Units` / `Final_Y1..Y5` are **planned units for delivery (Shipment)**, not the installed
  base. `Y5 ⊆ Y4 ⊆ Y3 ⊆ Y2 ⊆ Y1` — never sum them.
- Drill-down path: `Region → SubRegion → Country → Offering → Channel`. Business Org dropped (one
  value in the data).
- Channel movement is measured **week-over-week** within the group.

---

## 3. What this session changed

All pushed to `spec-v2-refactor` in `74f46c5`, except the last item.

**Wrong conclusions the engine was reaching**

- **A cause could explain a miss it would push the other way.** Two reports blamed a holiday for a
  week that came in far *above* plan, while their own evidence said holidays make that queue
  *quieter*. Cross-examination asked 16 and 13 questions and passed it both times.
  → `LOGIC_DIRECTION_COHERENCE` added. Survivors went from **6-of-6 to 3-of-5**.
- **No report on any queue had ever used a measured statement.** `_select_root_cause` compared
  `top["cause_type"]` against `best["cause_type"]`, and catalogue entries have **no `cause_type`
  key** — always `None != <string>`, so every headline fell through to the catalogue's *condition*
  text ("Demand Spike — actual exceeds forecast beyond the volatility band"). Dead code path.
- **Causes weren't ordered by confidence** — a live run returned `[70, 90, 60, 40]` unsorted.

**Content computed then discarded** — the deepest recurring pattern, six instances:
`ranked_root_causes[].title`, holiday names, the `driver_gate` note, `data_quality`, plan vintage,
and the measured statement. Five now render; `executive_summary` and `investigation_trail` still
have **0 UI references**.

**Gemini never worked at all** — three faults chained: no `gemini` in `PROVIDER_ENDPOINTS`;
`_narrate` returning its placeholder `"unknown"`; Google rejecting `seed` with
`HTTP 400 Unknown name "seed"`. Fixed; `seed` omitted for Gemini only.

**Holiday calendar published to SQL** — validated **40 of 40** sampled country-weeks identical
between SQL and the engine's own lookup.

**Uncommitted (this last exchange):** `_call_llm` retryable fallback — an explicit model choice had
**no fallback**, so a 429 killed the interrogation entirely
(*"question generation unavailable: gemini/gemini-3.6-flash: HTTP Error 429"*). It now appends the
configured chain and falls back only on retryable failures (429/5xx/timeout), never on 400/401 which
would fail identically everywhere. Also fixed a **latent `ValueError`**: one return path gave a
3-tuple while every caller unpacks 2.

---

## 4. The single most important open finding

**Confidence is capped to Low on essentially every report, and the cause is mechanical.**

Before the direction gate, two unrelated queues — different countries, channels, volumes — both had
**6 of 6** hypotheses survive with `ContradictoryEvidence = 0.3774`, *identical to four decimal
places*. The chain: cross-examination eliminates nothing → every hypothesis survives → *"N others
explain the same movement"* → ContradictoryEvidence (weight **0.20**, the heaviest of eight) lands
just under the 0.40 cap → **gate 5 fires on every report**.

A confidence score that is almost always "Low" carries no information, and it is the first thing a
reviewer notices. The direction gate improved one queue to 3-of-5; the mechanism is still there.

---

## 5. The blocked item — a spec gap, not a code gap

`FC_RCA_RCA_Methodology.md` gives the **Forecast** category exactly two hypotheses:

| Hypothesis | Generated when |
|---|---|
| Forecast Bias | consistent one-sided deviation across recent periods |
| Trend Misidentification | trend direction in actuals differs from forecast |

Neither covers *"the plan was set away from what this week of the year reliably brings."* On
`SA Indonesia Client Basic` FW202716 that **is** the cause — plan 63.79 against a 3-year week-16
average of 122.33 (**48% below**), demand of 152 entirely normal for the week — and the queue has no
one-sided bias (+1.8 contacts over 52 weeks) and no trend mismatch, so **no Forecast hypothesis can
fire**. The finding is computed and ranked at 82% but cannot become the headline.

*"Every hypothesis originates from the catalogue"* is an acceptance criterion and §6 *"prevails"*, so
this needs a **24th catalogue entry — a specification amendment**. That document's Approver is
**"Pending"**.

---

## 6. Suggestions, in the order I would do them

**1. Recover the channel-mix work rather than rebuild it.** It is priority 1 and it already exists on
`wip/rca-drilldown`. The analysis was verified — `Americas / NA / United States / Basic` FW202304,
group total moved **+1.5%** while **4,133 contacts** moved out of Voice, Chat and Email into Social
Media. Only the *presentation* was rejected. Cherry-pick the engine changes, leave the panel, and
design the display fresh. Rebuilding from scratch would repeat a week of measurement work.

**2. Fix the confidence cap before adding features.** It undermines every report regardless of how
good the analysis is. Two candidate approaches: make cross-examination genuinely discriminate (the
direction gate showed this is possible), or reconsider whether "N alternatives survived" should
depress ContradictoryEvidence at all — on a queue with real ambiguity, surviving alternatives are an
honest finding, not evidence against the leader.

**3. Get the 24th hypothesis approved, or decide it isn't wanted.** Until then, plan-level causes —
which in my sampling are the *most common real cause* — cannot be reported. This is a decision, not
work.

**4. Merge `MD` and `spec-v2-refactor`, or cross-reference them.** Nobody can review either alone.
The code cites seven specification documents that are not in the same tree.

**5. Add a regression test for the class of bug that keeps recurring.** Three separate times, good
content was computed and never rendered; twice, a comparison could never evaluate true. A test that
asserts *"every response key the engine populates is either rendered or explicitly marked internal"*
would have caught all five. The existing suites pass while these bugs ship — they check contracts,
not whether the reader sees anything.

**6. Do not trust "the suites are green" as evidence the output is good.** All four pass — 12/12,
42/42, 57/57, 6/6 — and none of them asks whether a conclusion agrees with the direction of the miss,
or whether the headline is a sentence rather than a definition. That gap is exactly what let the Good
Friday and Indonesia conclusions through.

**7. Two data problems worth fixing at source**, because they silently limit what any RCA can say:
`SA Indonesia Client Basic` is the **only queue of 427** whose export has blank Region / SubRegion /
Country / Offering / channel / Forecaster / plan name (SQL has them, so the export is at fault); and
**12% of rows file-wide (16,598 of 138,529) carry no `Projection_plan_name`**, which is why
plan-vintage questions come back unanswerable.

---

## 7. Reference — files and thresholds

**Documents in this worktree**

| File | Contents |
|---|---|
| `walkthrough.md` | project inventory + a full 2027 run + four-tier TODO |
| `SA_INDONESIA_RCA_VALIDATION.md` | the FW202716 validation with statistical evidence |
| `SA_INDONESIA_RCA_SIMPLE.md` | the same in plain English, no statistics background needed |
| `export.md` | this file |
| `IMP_DOCS/wfm-rca-engine.md` | the spec-v2 engine, the RCA priority, the open spec gap |
| `IMP_DOCS/TODO.md` | P0–P3 findings from three reviewed reports |

**Verification tools** (`results/`): `smoke_test_modules.py` 12/12 · `spec_compliance_check.py`
42/42 (2 providers) · `statistical_engine_check.py` 57/57 · `cqn_mapping_integrity.py` 6/6.
`statistical_engine_check.py` recomputes every metric with a **second independent implementation** —
it deliberately shares no code with the module under test.

**Loaders** (`backend/`): `upload_excel_to_sql.py` · `upload_cqn_mapping.py` ·
`load_holiday_master.py` (xlsx→JSON) · `load_holiday_to_sql.py` (JSON→4 SQL tables).

**Thresholds** — generation ±5% · materiality 50 contacts · major deviation 75% · driver relevance
|r| ≥ 0.30 over n ≥ 30 · history 157 weeks · trend fit r² ≥ 0.30 · plan-vs-norm 25% · CoV volatile
≥ 0.30 / stable ≤ 0.15 · outlier modified-z 3.5 · min n 6.

**LLM** — temperature 0.0, top_p 1.0, seed 20260730 (omitted for Gemini), timeout 150s.
Chain: `nvidia/nemotron-3-super-120b-a12b` → `groq/llama-3.3-70b-versatile` →
`gemini/gemini-3.6-flash`. Gemini rate-limits under repeated use; `gemini-flash-lite-latest` has
succeeded where `gemini-3.6-flash` returned 429.

**Confidence weights** (v2.0.0, sum 1.0) — ContradictoryEvidence 0.20 · EvidenceStrength 0.18 ·
BusinessRuleValidation 0.15 · StatisticalAgreement 0.14 · DataSufficiency 0.12 ·
ContextCompleteness 0.10 · HistoricalConsistency 0.06 · ModelAgreement 0.05.

**Three LLM calls, not one.** `narrative_prompt.py` claims to be "the ONLY place an LLM is invoked".
A spec run makes three: `why_rephrase.apply` (step 10b), `_narrate` (step 14), `_interrogate`
(step 14b, after the RCA is fixed so it cannot influence a conclusion).
