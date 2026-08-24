# FC RCA Decision Card engine — `?mode=spec`

The canonical FC RCA methodology and the Executive Decision Card. **This is not the WFM engine.**

| | |
|---|---|
| `?mode=spec` | **canonical FC RCA methodology + Executive Decision Card** — this document |
| `?mode=wfm` | WFM-specific forecast diagnostic engine — see `wfm-rca-engine.md` |
| `?mode=legacy` | the original engine, unchanged |

The two engines are **independent** and stay that way. They may be compared on the same input, and
where they disagree the reason is different methodology, a different hypothesis universe, different
evidence and different scope — not a bug. Neither is made to match the other for consistency's sake.

---

## What did not change

Everything in this list was verified by `results/test_fc_spec_semantics.py`, which fails if any of it
drifts.

- The **canonical 15-step sequence**. No step is skipped, collapsed or reordered. Hypotheses (6)
  still precede statistics (9); cross-examination (11) still precedes confidence (12); the LLM is
  still step 14, after the deterministic RCA at 13.
- The **±5% RCA generation threshold**, fixed and not configurable.
- The **50-contact materiality floor** — a worklist control. It never suppresses the RCA.
- The **75% major-deviation threshold**.
- The **23-hypothesis catalogue**, six categories, all four states
  (`Generated` / `NotApplicable` / `Suppressed` / `Rejected`), every non-generated entry recorded
  with its failing condition.
- The **offering driver cascade** — Basic: shipment→ASU; Premium and Pro: ASU→shipment; OOP and OOW:
  neither.
- **Product Lifecycle and Manual Override remain outside the catalogue.** Neither is implementable
  against the current source. `Offering` is a support tier and is never a lifecycle proxy.
- The **eight-dimension confidence model**, its exact weights, the 0.20 Missing floor, the
  renormalisation rule and all eight caps (nine rows — gate 3 has two thresholds).
- **Missing vs NotApplicable** wording, which carries opposite meanings and opposite actions.
- The **input fingerprint** and the full audit trail with four version stamps.
- **13/26-week aggregates**. The plan-vintage timeline is REMOVED — see the exclusion note below.
- The **LLM as narrator only**: four-part prompt, context fencing, numeric grounding, and an RCA that
  survives any model failure.
- Every **pre-existing response key**, and the **ten mandatory card sections**.

`root_cause.cause_type` is still the catalogue hypothesis ID. Everything new sits beside it.

---

## What the upgrade added

### Forecast-response diagnosis — `forecast_response_diagnostic`

Separates three things that "Demand Spike" used to blur together:

| | question |
|---|---|
| **forecast-side level error** | was the plan away from expected demand *before* the week? |
| **demand-side movement** | did demand then move away from expected? |
| **forecast-response error** | did a signal exist that the plan failed to react to? |

The split is **exact**: `forecast_side + demand_side == actual − forecast`, so the two shares are
arithmetic rather than an apportionment judgement. `reconciles` is a real check on the inputs.

Expected demand is a **median**, preferring the same week in prior years — a mean over a window
containing the outlier being investigated is dragged by it.

Response adequacy is judged against **what the expected level implied the plan needed to do**, never
against the outcome. Judging against the outcome would make every miss a forecast failure by
definition. Classes: `adequate`, `under_response`, `over_response`, `wrong_direction`,
`delayed_response`, `no_response`, `not_testable`.

**When little movement was implied, the class is decided by SIGN, not assumed.** If the prior plan
already sat near the expected level, any material move is judged on whether it went the *same* way as
the (small) implied change — `over_response` — or the *opposite* way — `wrong_direction`. With the
implied change at exactly zero there is no direction to be wrong about, so it is `over_response`.

This mattered on a real card: UKI Comm Client DSP Standard FW202717 had implied `−2.3` and a move of
`−82.61` — the **same** sign — and was reported as `wrong_direction`. That contradicts §14's own
definition ("moves *opposite* the expected direction") and pointed the remedy the wrong way: fiscal
week 17 is a holiday week every year, so a cut *was* correct and only its size was wrong.

### Forecastability gate — `forecastability_gate`

**`Actual > Forecast` is never on its own a forecast failure.** All four conditions must hold:

1. a leading signal existed before the target week,
2. that signal has repeatable historical support **for this queue**,
3. the signal was actually present in the current period,
4. the forecast response was inadequate.

Each condition is published with its measured value, so a reader sees *which* one failed. When the
gate does not pass, the movement is classified as a demand event, a contextual factor, unconfirmed,
or a data limitation — not as a forecast failure.

### The seven mechanisms — `miss_mechanism`

Additive to `cause_type`. A hypothesis ID says *what* was considered; the mechanism says **why the
forecast missed**.

| mechanism | meaning |
|---|---|
| `FORECAST_BASELINE_FAILURE` | the plan entered the period at the wrong level |
| `FORECAST_RESPONSE_FAILURE` | a repeatable signal existed and the plan did not react adequately |
| `CALENDAR_RESPONSE_FAILURE` | a repeatable calendar effect existed and the plan did not capture it |
| `DRIVER_RESPONSE_FAILURE` | a driver gave a repeatable early signal and the plan did not use it |
| `DEMAND_EVENT_LOW_PREDICTABILITY` | demand moved and nothing available beforehand could reliably have predicted it — **not a forecasting failure** |
| `COMPOUND_MISS` | more than one mechanism contributed materially; each is named |
| `DATA_LIMITATION` | the evidence cannot support a defensible mechanism |

Not every miss is forced into a forecast failure. That is the point.

### Direction-coherence gate — before confidence

For an under-forecast, a promoted cause must explain **higher** actual demand; for an over-forecast,
**lower**. A demand-suppressing mechanism cannot be promoted as the cause of a demand increase unless
a *measured* rebound explains the direction — which `holiday_response` measures per phase, so
"post-holiday recovery" is admissible where that phase effect is genuinely positive for this queue,
and inadmissible as a bare assertion.

This runs **before final confidence**, and it is a **business rule**: when the promoted cause rests
only on a mechanism the gate rejected, `BusinessRuleValidation` scores 0.00 and confidence Gate 2
caps the level at Low. Arithmetic cannot outvote a rule saying the conclusion points the wrong way.

### Lag-aware driver evidence — `lagged_driver_evidence`

Lags 0/1/2/4/8 on both **level** and **change** relationships, measured with Spearman on the queue's
own history with the target week excluded, plus a half-history stability test.

**Hypothesis-selected, never swept.** Only drivers the *generated* hypotheses require are tested, so
a queue with no business hypothesis runs no driver lags at all and says so. There is no N×M
correlation explosion.

Three coverage states, never collapsed:

| state | meaning | availability |
|---|---|---|
| `populated` | enough valid paired history | `Available` |
| `sparse` | some history, too little to be reliable | `Missing` (penalised) |
| `absent` | no usable data | `NotApplicable` (no penalty) |

A weak coefficient is **never** rendered as "this driver has no effect". The three legitimate
readings are: the earlier week is stronger; coverage is too thin to establish a relationship; the
relationship is inconsistent by period.

`Final_Units` (planned units for delivery, i.e. **Shipment**) and `Final_upp_units` (additional
installed units under an upgrade / extended-protection plan, i.e. **UPP**) are separate drivers and
are never combined. `Final_Y1..Y5` nest and overlap, and are excluded from driver testing entirely —
they must never be summed.

### ASU decomposition — `asu_decomposition`

```
planned_rate  = forecast / Planned_ASU
actual_rate   = actual   / Actual_ASU
volume_effect = (Actual_ASU - Planned_ASU) * planned_rate
rate_effect   = Actual_ASU * (actual_rate - planned_rate)

volume_effect + rate_effect == Actual - Forecast     (exactly)
```

Read as a **population/base effect**, a **contact-rate effect**, or **mixed**. If `Actual_ASU` is
missing the decomposition is *not* fabricated — it reports that it could not be performed and the
investigation continues. No ASU exposure at all is `NotApplicable`, not `Missing`.

### Calendar: pre / holiday / post — `holiday_response`

Phases **H−2 … H+2**, each measured against the queue's **own non-holiday baseline**, with instance
count, effect size, consistency rate, and whether the plan *historically* allowed for it.

**A target week with `Holiday_Count = 0` can still be pre-holiday, post-holiday or
adjacent-affected.** The engine never says "no holiday impact" merely because the target row records
none; `zero_count_but_adjacent` marks exactly that case and the card states it in words.

**An observed phase effect is not automatically a forecast failure.** Where the queue's own history
is inconsistent, the finding is that no reliable forecastable signal exists — not that the plan
should have caught it. Capture classes: `captured`, `under_reacted`, `over_reacted`,
`wrong_direction`, `delayed`, `inconsistent_history`, `not_testable`.

`captured` spans a wide band — 0.5× to 1.75× the historical effect — so the **`capture_ratio` and
`overshoot_pct` are published** and the sentence quotes the multiple. A bare "captured" hid a 51%
over-cut (−40.04% applied against −26.54% implied, 1.51×). The threshold itself is deliberately
**unchanged**: it is versioned configuration no client has confirmed, and moving it would flip
existing verdicts across every queue.

### Is the holiday adjustment itself right? — `holiday_response.plan_bias`

A different question from `forecast_capture`, and both are reported. Capture asks whether the plan
applied the pattern to **this** week. `plan_bias` asks whether the plan has been missing the same way,
or by a **growing** amount, on these weeks for years. Only the second justifies changing the
adjustment *rule* rather than this week's number — and a week can sit inside the `captured` tolerance
every single time while the rule drifts.

Two findings, reported **separately** because they want different actions:

| finding | test | action |
|---|---|---|
| **standing one-sided bias** | ≥70% of that phase's weeks miss the same way **and** median \|adherence\| ≥ 10% | review the adjustment rule — it is consistently too deep or too shallow |
| **widening miss** | the later half's median absolute miss exceeds the earlier half's by ≥5 points | review how the adjustment is *sized* — direction is not the problem, magnitude is drifting |

**Widening is reported independently of direction.** The first version required a consistent direction
first, and on UKI Comm Client DSP Standard that correctly found *no* bias — 10 of 17 holiday weeks too
low is 59%, barely better than a coin flip — which disproved a "systematically too deep" reading of
the raw counts. But the same queue's misses are clearly growing on every phase (holiday 16.9%→22.6%,
pre 11.4%→20.9%, post 10.7%→29.9% median absolute). Requiring a direction would have hidden a real,
actionable finding.

Event identity is `Semantic_Family` where present, else a modifier + core-token key, so bridge days
stay separate from their anchor and spelling variants merge. **`Aggregate_Group` is not an event
identity** — it groups *countries*, so using it would merge Columbus Day with Thanksgiving. Raw
source names stay traceable, review flags are surfaced, and no transliteration mapping
(Waisak/Vesak) is invented.

### Weekend — `weekend_diagnostic`

**Grain is determined first.** On this source the `Monday`…`Sunday` columns are per-day *holiday
flags*, not daily volumes, so a weekend volume effect **cannot be isolated from fiscal-week totals**.
That is reported as a limitation with its reason, never as "no weekend effect" — which the data
cannot support in either direction. The check re-runs against the actual rows every time, so it
flips by itself if a daily source is ever added.

### Criticality — `criticality`

**New: the FC engine had no criticality mechanism at all.**

Confidence asks how strong the evidence is. Criticality asks how much the miss **matters
operationally**. They are independent, and never blended or traded off.

- The **absolute contact gap** sets the band. That is deliberate: a percentage on a tiny queue is
  arithmetically large and operationally irrelevant, which is why the 50-contact materiality floor
  already exists — and it is reused as the bottom edge rather than inventing a second threshold.
- The **relative gap** (gap vs a typical week for this queue, using a *median*) can lift the band by
  at most one step.
- **Persistence** (a same-direction run of 4+ weeks) can also lift it one step.
- A lift can never lower the band, and never saturates into a false claim.

Bands: `Negligible` / `Low` / `Moderate` / `High` / `Critical`.

### `Projection_plan_name` is treated as non-existent

**The column is excluded from this engine entirely.** Not hidden, not left blank — the engine reads
as though the field does not exist.

That deletes the brief's **§8** plan-revision finding (*plan not revisited / revised but still wrong /
revised appropriately*), because it rested wholly on that column. A deliberate departure from the
brief, recorded here rather than left to be discovered from an absence.

It is also defensible on the data. The column holds **monthly projection vintages**
("FY27 May Projection") which change on a calendar cycle, not in response to a miss —
40 distinct names over 208 weeks for one queue, roughly one every five. So a reissue mid-run is
usually the monthly cycle arriving rather than somebody reacting, which is exactly what made
*"the plan was revisited and stayed wrong"* read as an accusation on every queue. Two existing
decisions already pointed the same way: [prompts.py](../backend/wfm/prompts.py) forbids the WFM model
from citing routine plan updates as a cause, and `lag_analysis.NOT_DRIVERS` excludes the column from
driver testing.

Removed with it: `plan_revision`, `plan_vintage_timeline`, evidence item **E15**, recommendations
**M6/M7**, the plan bullet in *Why This Happened*, the plan-vintage row in the interrogation prompt,
`plan_vintage` in the LLM weekly series, `plan_vintage_changes` in the evidence bundle, and the
*"Plan measured against"* block on the card. The evidence index is now **14 items (E1–E14)**; the
remaining IDs keep their numbers so existing citations stay valid.

**What survived:** the **miss streak** — `miss_streak` — which criticality uses for its persistence
lift. It was only ever computed inside `plan_revision` because that is where it was first needed; it
derives from adherence alone and never touched the plan name. The card's *Forecast owner* block also
survives, since `Forecaster` is a different column answering a different question.

Enforced, not merely intended: `results/test_fc_spec_semantics.py` runs the engine over a fixture
whose rows **do** carry a plan vintage and asserts neither the column name nor the value
(`FY.. ... Projection`) appears anywhere in the response, and `results/check_ui_render.js` feeds a
plan vintage into the renderer and asserts it never reaches the markup.

### Contradiction resolution — `evidence_resolution`

`supported` / `mixed` / `rejected`, with the reason **one side governs** stated. Two contradictory
explanations are never both verified. Conflicts are shown with what resolved them — the
direction-coherence gate, or cross-examination.

### Evidence IDs — `fc_evidence_index`

E1–E14, in the FC brief's own numbering (E9 pre-holiday, E10 holiday, E11 post-holiday, E15
plan-vintage). Published as `fc_evidence_index` and **never compared to the WFM engine's index by
ID** — the same labels mean different things there. An item that could not be established is present
and marked unavailable **with its reason**, never omitted.

### Cross-examination — catalogue 2.1.0

Five questions added; nothing removed, reworded or reclassified. The loop, the bound of 3, and the
before-confidence ordering are untouched.

`FCST_SIGNAL_TIMING`, `FCST_LAG_SUPPORT`, `FCST_COULD_HAVE_REACTED`, `CAL_PHASE_INTERACTION`,
`FCST_WEEKEND_ATTRIBUTION`.

Each returns `UNANSWERED` — never `SUPPORTS` — when the measurement is absent, so a queue with less
data cannot look better challenged than one with more. `CAL_PHASE_INTERACTION` **refutes** rather
than weakens a Calendar hypothesis, because an inconsistent phase response leaves a calendar
explanation with no forecastable signal to rest on.

### Confidence inputs — enhanced, model untouched

Three dimensions that could never be scored now can be:

| dimension | was | now |
|---|---|---|
| `HistoricalConsistency` | hardcoded `(None, 0)` — permanently NotApplicable | holiday phase instances for the target week's phase + momentum precedents, as an instance-weighted mean |
| `ModelAgreement` | hardcoded `(1, 1)` — permanently NotApplicable | two genuinely independent paths: catalogue+cross-examination, and mechanism evidence+direction gate |
| `BusinessRuleValidation` | data quality only | the direction-coherence gate, which can now score 0.00 and arm Gate 2 |

**Confidence numbers move on some queues as a result.** That is documented and intended: the score
moves because evidence was **found**, never because evidence was lost — the invariant the model
exists to protect.

---

## The Executive Decision Card

`card_version` **2.1.0**. Ten mandatory sections unchanged; eight added, numbered from 11 so a
renderer that does not know them shows the original card.

```
 1 executive summary        11 criticality
 2 root cause (+ scope)     12 why this happened      <- ranked bullets
 3 confidence               13 forecast response
 4 business impact          14 calendar context
 5 evidence                 15 driver evidence
 6 hypothesis comparison    16 evidence index
 7 recommendations          17 contradiction resolution
 8 limitations              18 catalogue gaps
 9 data availability
10 audit reference
```

**Ranked bullets (§41).** Order is set by the evidence — causal coherence, forecastability,
historical consistency, statistical strength, data sufficiency, contradiction resolution — and is
**not** the model's preference. The model may reword a bullet; it cannot reorder, merge, drop or add
one. A reply that reorders them is discarded and the deterministic order kept. Rewording is matched
**by rank**, not by position, so a reordered reply cannot attach one bullet's prose to another
bullet's evidence ID.

**Executive language (§40)** is *checkable*, not merely instructed. `decision_card.EXEC_JARGON` is the
banned-term list; every bullet carries its own `jargon_found` and the panel carries the union, so the
test suite asserts the prose is clean and a reviewer can see the check ran.

**Scope is not a cause.** The ladder narrows the search; it never becomes the explanation. "Inherited
from Country" is never a root cause.

---

## The interrogation uses TWO models, not one

The interrogation stage runs two prompts:

| prompt | job | model |
|---|---|---|
| **2 — ask** | read the findings, ask what they leave unexplained | **`llm.interrogator`** |
| **1 — answer** | answer each question strictly from the evidence bundle | `llm.primary` |

Until now both went to the same model, which meant the questioner and the answerer shared the same
blind spots — a model is least likely to ask about the thing it does not think to look at, and then it
is the one deciding whether the data can answer. Splitting the questioner off gives the challenge some
independence.

**The answerer deliberately stays on the primary.** It is the half whose output is quoted as fact on
the card, so it must remain grounded in the evidence bundle and its behaviour should not change.

```jsonc
"llm": {
  "primary":      { "provider": "nvidia", "model": "nvidia/nemotron-3-super-120b-a12b", "api_key": "..." },
  "interrogator": { "model": "openai/gpt-oss-120b" }
}
```

Only `model` is needed — provider, `api_key` and endpoint are inherited from `primary`, because this
is the same account and the same key. **Omit the key and nothing changes**: the questioner stays on
the primary exactly as before.

**Two rules that differ from every other call.**

- **The console's per-queue model picker does NOT override the interrogator.** Everywhere else an
  explicit pick wins so a model-comparison run is uniform; here it does not, because the questioner is
  part of the method rather than a subject of the comparison — the questions stay comparable across runs.
- **A dead questioner falls back to the primary rather than deleting the section**, and the response
  says so: `interrogation.questions_asked_by`,
  `questions_asked_by_configured_model` and `interrogator_fell_back`. A silent fallback would look
  identical to the split working.

**Verify a candidate on the REAL prompt, and verify RELIABILITY not just capability.** The question
prompt is ~40,000 characters, and repeated runs matter more than one good run. Measured 2026-08-21 on
this account:

| model | success | median | max | valid questions |
|---|---|---|---|---|
| **`openai/gpt-oss-20b`** ← configured | **5/5** | **38.1s** | 67.0s | 3–5 every run |
| `openai/gpt-oss-120b` | **2/4** | 135.7s | **150.1s timeout** | 5/5 when it answered |
| `nvidia/nemotron-3-super-120b-a12b` *(primary)* | 4/4 | 25.0s | 28.7s | 3 |
| `nvidia/nemotron-3.5-lightning-30b-a3b` | 0 | — | **timeout** | — |
| `minimaxai/minimax-m3` | 0 | — | **timeout** | — |

Two traps this table records, both of which caught me:

- **A single good run is not reliability.** `gpt-oss-120b` was chosen on one 56.8s sample and is
  genuinely the strongest questioner — 5/5 valid every time it answered — but it times out on roughly
  half of attempts, with a median of 135.7s against the 150s timeout. Half of all investigations were
  falling back silently. `gpt-oss-20b` is slightly weaker per run and dramatically more useful.
- **A trivial prompt proves nothing.** `nemotron-3.5-lightning` and `minimax-m3` both answered a
  toy prompt in under 11s and then timed out on the real one.

Retired ids: `deepseek-ai/deepseek-v4-flash` is **HTTP 410 Gone**, the dated `-0731` variant timed out,
and `nvidia/llama-3.3-nemotron-super-49b-v1.5` is deprecated by NVIDIA on **2026-08-25**. All three
were removed from `selectable_models` — a picker offering a model that cannot answer is worse than one
that omits it.

### Seeing it work — terminal log

Every LLM call prints one line, because the fallback is otherwise invisible: the card reads identically
whichever model asked.

```
[FC-RCA] narrate(step14)  nvidia/nemotron-3-super-120b-a12b   64.3s  OK
[FC-RCA] ask(prompt2)     openai/gpt-oss-20b                  30.2s  OK   5 question(s) kept, 0 rejected
[FC-RCA] answer(prompt1)  nvidia/nemotron-3-super-120b-a12b   54.9s  OK   5 call(s), 2 answered from evidence
```

A failed questioner adds a `FELL BACK` line naming both models and suggesting the model may be
deprecated or withdrawn. `print` rather than `logging` because uvicorn owns the logging configuration
and a custom logger needs its handlers wired up to appear at all.

---

## Running it

```bash
# offline, no SQL, no model — exercises all 15 steps
cd backend && python ../results/run_offline_investigation.py

# the semantic suite — 149 checks, all 24 brief scenarios
python results/test_fc_spec_semantics.py

# the renderer, against real captured responses
node results/check_ui_render.js

# live SQL + live model, ten scenarios selected from real data
cd backend && python ../results/run_live_spec_validation.py
```

`run_live_spec_validation.py` starts its **own** server on port **8011**, not 8000, and refuses to
run if anything is already listening there. A stale server on the same port silently answered part of
the first live run with pre-upgrade code, producing a plausible mixed result with no error; a build
guard now aborts the run if a completed response arrives without `criticality`.

---

## Module map

| file | role |
|---|---|
| `wfm/spec_engine.py` | the 15-step workflow. The new evidence is computed between steps 6 and 7 |
| `wfm/fc_evidence.py` | **new** — FC-native adapter + criticality, ASU split, plan revision, mechanisms, direction gate, resolution, catalogue gaps, evidence index |
| `wfm/decision_card.py` | the card, + the eight new panels and the jargon list |
| `wfm/cross_examination.py` | 23 questions, catalogue 2.1.0 |
| `wfm/confidence.py` | **unchanged** — only its inputs improved |
| `wfm/hypothesis_catalogue.py` | **unchanged** — 23 entries |
| `wfm/narrative_prompt.py` | prompt 2.1.0, narration only |
| `wfm/lag_analysis.py` | lags, coverage classes, stability *(shared, engine-agnostic)* |
| `wfm/forecast_response.py` | baselines, decomposition, response adequacy *(shared)* |
| `wfm/holiday_response.py` | phases H−2…H+2, forecast capture *(shared)* |
| `wfm/holiday_events.py` | event identity and de-duplication *(shared)* |
| `wfm/data_granularity.py` | what the data grain supports *(shared)* |
| `wfm/data_access.py` | `_HISTORY_COLS` widened additively — read by **both** engines |
| `wfm/common.py` | `week_ordinals()` for fiscal-year rollover |

---

## Known limitations

- **Weekend attribution is impossible on this source** and will stay so until a day-level feed
  exists. The `Monday`…`Sunday` columns are holiday flags.
- **Business Event Repository is not deployed**, so that context element is `NotApplicable` and
  carries no confidence penalty (BR-202).
- **`Final_upp_units` is sparse on most queues.** That is reported as sparse coverage rather than used
  as evidence — judging it from a short window is what produced a z-score of 23.33 from two points.
- Two holiday-master entries for Ascension are flagged `possible_misdating` (05-14 source vs 05-27
  derived, `Requires_Review=YES`). Surfaced, not silently resolved.
- The **criticality band thresholds** (5000 / 1000 / 200 / 50 contacts) are anchored on the existing
  materiality floor and then an order of magnitude per step. They are versioned configuration and
  would benefit from a client-confirmed table.
