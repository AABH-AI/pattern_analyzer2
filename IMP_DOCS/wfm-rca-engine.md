# WFM RCA Engine (`?mode=wfm`) — the business-authored investigation prompt

Branch: `wfm-rca` (off `shivam-updates`). Added 2026-07-28.
Code: the `backend/wfm/` package + a ~40-line opt-in branch in `backend/sql_backend.py`.
`backend/rca_wfm.py` is now a compatibility shim re-exporting the package.

## Module map

| Module | Responsibility |
|---|---|
| `wfm/investigation_engine.py` | orchestrates the workflow |
| `wfm/hierarchy_analyzer.py` | Business Org → Region → SubRegion → Country → Channel drill-down |
| `wfm/channel_migration_detector.py` | Voice ↔ Chat ↔ Email shifts within one locality |
| `wfm/temporal_reasoner.py` | 104 weeks, prior week / 4 / 13, same week last year |
| `wfm/correlation_engine.py` | driver relationships + the exact ASU decomposition |
| `wfm/hypothesis_generator.py` | "Hypothesis – To be Validated" marking; the deterministic list |
| `wfm/skeptic.py` | **rejects causes the features cannot support** |
| `wfm/business_report_generator.py` | executive report + legacy-key back-compatibility |
| `wfm/data_quality.py` | is the number itself credible? |
| `wfm/data_access.py` | the SQL fetches |
| `wfm/prompts.py` | the business-authored prompt |
| `wfm/llm_client.py` | LLM transport with a **configurable** timeout (`llm.timeout_seconds`) |
| `wfm/common.py` | shared primitives |
| `wfm/evidence_pack.py` | **(approved-test)** arithmetic over history: miss streak, plan reissues, same-week-last-year, holiday effect |
| `wfm/interrogation.py` | **(approved-test)** Prompt 2 asks WHY of the produced bullets; Prompt 1 answers from evidence |
| `wfm/why_prompt.py` | **(approved-test)** both prompts, plus the absent-data and traceability validators |

Run order, mirroring the prompt's own rules:

```
derive features (all deterministic)
  -> threshold gate            never investigate inside the band
  -> ONE model call            rank + explain + challenge, in business language
  -> skeptic.review            reject causes the features cannot support
  -> hypothesis_generator.mark downgrade over-confident statuses
  -> business_report_generator recompute the KPI, build the report, back-fill legacy keys
  -> interrogation             (approved-test) question the finished report -- EXPLANATORY ONLY
```

## The two modules that close real gaps

### `skeptic.py` — rejection in code

Previously SKEPTIC MODE was entirely prompt-side: the model was asked to argue against
itself. Nothing could reject anything, so a cause the data does not support still shipped.

**Ground 1 — feature precondition (hard reject).** Every cause type names a mechanism, and
every mechanism leaves a trace in the features. No trace ⇒ the cause is *impossible*, not
merely weak. All ten cause types have an explicit precondition in `PRECONDITIONS`.
Unit-verified: a `plan_restatement` claim on a week where `plan_restatement.changed` is
`False` is rejected with *"the forecast plan did not change this week, so this cause is not
possible for this week"*. This was the highest-value defect identified in the earlier
read-through — the old engine would publish that verdict unchallenged.

**Ground 2 — numeric grounding (prunes evidence, does not reject).** Both prompts demand
every value be "a REAL NUMBER from the payload"; nothing verified it. Each cited figure is
now reconciled against the real numbers in the features (2% tolerance for display rounding)
and unreconciled ones are dropped with a note. Deliberately *not* a rejection ground on its
own: a model may legitimately cite a correctly-derived figure (a gap, a difference) that is
not literally in the payload, and killing a sound cause over that would be worse than the
disease.

`eligible_cause_types()` is also fed to the prompt, so the model does not spend one of its
five slots on a type that will be rejected.

### `correlation_engine.py` — relationships and exact attribution

**Relationship strength.** Spearman rank correlation between each candidate driver
(`Actual_ASU`, `Planned_ASU`, `Final_Units`, `Holiday_Count`) and `Actual_Offered` over the
queue's own history. Rank-based on purpose: unaffected by the single extreme week that
usually triggered the investigation, where Pearson would be dragged around by it.
Relationships are RETAINED or REJECTED in code against explicit thresholds (≥12 weeks,
|strength| ≥ 0.5), so "ignore weak correlations" is enforced rather than requested. Each
retained entry carries a jargon-free `plain_language` string for the report, with the
coefficient confined to `technical_strength` for the collapsed section.

**Driver decomposition — the strongest attribution in this dataset, and exact.**

```
planned_rate  = fcst_offered   / Planned_ASU
actual_rate   = Actual_Offered / Actual_ASU
volume_effect = (Actual_ASU - Planned_ASU) * planned_rate
rate_effect   = Actual_ASU * (actual_rate - planned_rate)
volume_effect + rate_effect == Actual_Offered - fcst_offered      (identically)
```

It answers a genuinely causal question — did we miss because the warranty base was not what
we planned, or because contacts per unit moved? — instead of choosing a label. Verified
exact on all **22,003** flagged misses in this table carrying both columns: **60.7%
rate-driven, 9.8% base-driven, 29.6% mixed**. Unit-verified on a synthetic row
(miss 300 = base 100 + rate 200, `reconciles: true`), and the missing-column path returns
`available: false` with the named fields — about 45% of scoreable rows lack `Actual_ASU`.

## What this is

The business supplied a full RCA specification — a cross-functional-team role, a fixed
investigation order, temporal rules, channel-migration rules, skeptic mode, top-5 ranked
causes, hypothesis marking, confidence levels and an executive report format. This engine
implements it.

It is a **second engine, not a replacement**. `POST /api/rca-investigate` with no `mode`
parameter behaves exactly as it always did — same code path, same prompt, same response
keys. Only `?mode=wfm` selects the new engine.

**Nothing in `rca_console.html` changed. `backend/rca_investigate.py` changed by zero
lines.** Verified with `git diff --stat shivam-updates -- backend/rca_investigate.py
rca_console.html` returning empty.

## Why it needed more than a prompt

The spec asks for things the old context bundle could not answer, no matter how the prompt
was worded:

| The spec asks for | The old bundle had | What was added |
|---|---|---|
| ~104 weeks of history, same week last year | 13 weeks | `history_104` + `prior_year_week` SQL fetch |
| "never conclude below a level before checking it isn't inherited" | nothing above the queue | `INVESTIGATION_LADDER` — adherence recomputed at org / region / subregion / country / channel for the same week |
| channel migration Voice ↔ Chat ↔ Email | peers were filtered to the **same** channel | `CHANNEL_SIBLINGS` — the locality across **all** channels, week over week |
| "only investigate outside ±10%" | every row was investigated | threshold gate returning `engine: wfm-not-investigated` |

All of it is fetched **server-side** from the target row's own identifiers, which is why the
console needs no change.

## Request

```
POST /api/rca-investigate?mode=wfm[&provider=&model=]
body: the same ContextBundle the console already builds
```

`provider` / `model` behave as before: a picked model runs alone and never silently falls
back to a different model.

## Response

Every original `InvestigationResponse` key is still present and populated, so the current UI
renders a WFM report without modification:

- rank 1 → `primary_root_cause`, `confidence_score`, `cause_type`
- ranks 2–5 → `secondary_contributors`
- rejected skeptic challenges → `rejected_hypotheses`
- each cause's `recommended_action` → `forecast_improvement_recommendations`

New keys on top (a future UI can render these directly):

| Key | Meaning |
|---|---|
| `executive_summary` | what happened, why, how certain, what next |
| `kpi_status` | `{metric, adherence_pct, threshold_pct, breached, direction}` — **always recomputed in Python, never taken from the model** |
| `business_impact` | operational consequence in plain terms |
| `ranked_root_causes[]` | up to 5: `rank, cause_type, title, explanation, evidence[], confidence_pct, confidence_level, business_impact, recommended_action, status` — `cause_type` was added so `skeptic.py` can gate the claim against the features |
| `skeptic_review[]` | `{cause, challenge, verdict, reason}` |
| `investigation_trail` | `{levels_checked[], inherited_from, narrative}` |
| `channel_migration` | `{detected, gaining_channels[], losing_channels[], detail}` — `detected` is **computed**, the model only narrates |
| `technical_metrics[]` | the collapsed-by-default technical section |
| `missing_information[]` | what could not be verified |

`status` is `"Verified"` or `"Hypothesis - To be Validated"`.

## `investigation_meta.engine` values

| Value | Meaning |
|---|---|
| `wfm-llm` | full investigation ran |
| `wfm-not-investigated` | inside ±band, so per the business rule nothing was investigated |
| `wfm-deterministic-fallback` | the model was unreachable; the report is the deterministic checks only, and says so in `missing_information` |

## What is deterministic vs what the model does

Arithmetic is never delegated to the model. Computed in Python, then handed over as evidence:

- `kpi_status` (the adherence formula, unchanged)
- the investigation ladder and the `inherited_from` verdict
- temporal comparisons (previous week, last 4, last 13, full history, same week last year)
- channel-migration detection (per-channel week-over-week deltas, group total, offset share)
- the data-quality check
- the existing `derive_features()` output, reused not reimplemented

The model's job is to rank, explain in business language, challenge, and write the report.
It cannot change the KPI or the migration verdict — `_coerce_wfm` overwrites both.

## Data-quality gate (an addition to the supplied spec)

The spec forbids fabricating business events. Taken seriously, that implies a step it did not
name: **checking whether the number is real before explaining it.**

`_data_quality` flags a week as `suspect` when the actual is ≥10× or ≤0.1× the queue's typical
week, is the only week anywhere near that level, and the following weeks return to normal. It
is ranked as a *hypothesis to validate at source*, never asserted as the cause.

This changes a conclusion recorded earlier in `prompt-trail.md`. Session 15 reclassified
`NA Core Spanish` week 202719 (actual 8,805 vs usual ~62, forecast ~91) from
`forecast_baseline_error` to `genuine_demand_event`. Evidence found on 2026-07-28 says it is
probably neither:

- across 126 weeks that queue ranges 31–8,805 and **exactly one week exceeds 1,000**
- the following weeks are 87, 54, 39 — straight back to baseline
- of 427 queues with ≥8 weeks, it is the **only** one with a single week >50× its own median
- the warranty base (14.2M planned ASU) barely moves that week
- `8805 / 100 = 88.05` against that week's forecast of `90.78` — a decimal shift would make
  the week almost perfectly forecast. Tested and rejected the alternative that a cumulative
  total was loaded into one week (52 weeks sum to 4,752; 104 weeks to 11,697 — neither matches).

Live check: the WFM engine now ranks **"Suspected data quality issue" #1 at 90% (High)** for
this case, with possible channel migration as a #2 hypothesis at 30% (Low). The original
engine ranked it `systematic_forecast_bias`. **The figure should be validated at source
before any forecasting action is taken.**

## RESOLVED (2026-07-29) — the CQN definition, settled by the mapping file

The client supplied `CQN and FC mapping.xlsx`, now loaded into SQL by
`backend/upload_cqn_mapping.py`:

| Table | Rows | Source |
|---|---|---|
| `dbo.CQN_Mapping` | 532 | Sheet1 — flat: Region, SubRegion, Channel, Offering, Forecast_Name, Combined_Queue_Name, DB_OSP |
| `dbo.CQN_Forecast_Pair` | 522 | Sheet3 — the Data Pair list (pivot; 191 blank CQN cells forward-filled) |

**The spec was right and the console's definition is a different concept.** Of 331 Combined
Queues, **35 span more than one channel** — `EMEA English ProSupp Client (Multi-Site)` covers
Case + Chat + Email + Voice across 9 forecast names. So channel is **not** part of the CQN key,
migration *within* a CQN is real, and `rca_console.html:1653`'s `cqnDimsKey` is a **locality key**,
not the Combined Queue.

**Coverage: 100% — and verified three ways, not one.** `results/cqn_mapping_integrity.py`
(6 PASS / 0 FAIL / 4 INFO):

| Check | Result |
|---|---|
| M1 every queue name resolves | **427/427** |
| M2 every data row is behind a mapped name | **66,612/66,612** |
| M3 every unit of demand is behind a mapped name | **38,923,978/38,923,978** |
| M4 mapping dimensions agree with the data | **all 4 agree on every name** (Region, SubRegion, Channel, Offering) |
| M9 engine resolves the authoritative CQN | `is_cqn_proxy=False`, `cqn_source=mapping` |
| M10 the two mapping tables agree | 0 one-sided differences |

M4 is the one that matters beyond coverage: a mapping can be 100% "covered" and still contradict
the rows it maps. It does not — 427/427 names agree on all four dimensions.

**But it is NOT 1:1, and that is the honest caveat:**

| | |
|---|---|
| names with exactly one Combined Queue | 373 |
| names with MORE THAN ONE | **69** |
| data behind the ambiguous names | 10,452 rows (15.7%) but **16.2M volume — 41.7% of all demand** |
| of those 69: differ only by vendor/site suffix | 23 → resolvable by a naming rule |
| of those 69: genuinely different queues | **46 → needs a business decision** |

So "100% mapped" is true for coverage and integrity, but ~42% of demand sits behind names whose
Combined Queue is ambiguous. Current behaviour is the **union** of a name's queues. `DB_OSP` does
not disambiguate (it differs on only 39 of the 69). Tracked in `TODO.md` P1e.

Re-check any time: `python upload_cqn_mapping.py --coverage` or the integrity suite above.

The engine now groups channel siblings by the authoritative CQN and reports
`is_cqn_proxy: false` plus `combined_queue_names`. The locality proxy remains only as the
fallback for when `dbo.CQN_Mapping` is absent.

**Sheet1 vs Sheet3 — measured, not assumed.** Sheet3 is the same mapping in pivot form with 191
of 523 CQN cells blank. Forward-fill them and the sheets agree on **442/442 names, 0
disagreements** (`--verify-sheets` proves it). Read naively, Sheet3 maps 167 names to blank, which
is why Sheet1 is loaded as authoritative.

**Still open:** 69 of 442 Forecast_Names map to MORE THAN ONE Combined Queue — vendor-site splits
(Concentrix vs CGS, Bangalore vs Pune, SITEL, BW, Sykes). No column disambiguates them; `DB_OSP`
separates in-house from outsourced but not vendor. **Current behaviour: the union of every CQN the
forecast belongs to is used for sibling grouping.** Needs a business answer (`TODO.md` P1e).

## Superseded — the original CQN conflict note (kept for history)

`rca_console.html:1648-1653` records the client's **confirmed** CQN definition as
`Forecast_name + Region + SubRegion + Country + Channel` — **channel is part of the CQN key.**
The WFM spec asks for migration "between Forecast Names or Channels within the same CQN",
which is only possible if channel is **not** in the key. The two definitions are mutually
exclusive.

This engine does **not** redefine CQN. The signed-off definition is untouched and still drives
peer grouping in the default engine. For migration detection only, a separately named grouping
is used:

```
CHANNEL SIBLING GROUP = Region + SubRegion + Country + business_org   (all channels)
```

It is called `channel_siblings` everywhere, never `CQN`, and the output carries
`is_cqn_proxy: true` plus a note saying so. Verified against the data: 43 such groups carry
more than one channel (up to 5 — Case, Chat, Email, Social Media, Voice), so migration is
detectable.

**Open question for the business:** does the true Combined Queue span channels? If yes, the
console's CQN definition needs revisiting (it is used elsewhere). If no, channel migration as
specified cannot occur within a CQN and the check should be renamed. Until answered, the
proxy is labelled as a proxy rather than presented as the CQN.

The console also accepts an uploaded CQN mapping file for the authoritative Combined Queue
Name. When a mapping is loaded, the grouping above remains a proxy — wiring the mapping into
this engine is not done yet.

## Cost / limits

Measured on a real investigation: system prompt ~2,300 tokens, payload ~2,100 tokens, so
**~4,400 tokens per call** (one call, not two). That fits Groq's on-demand 12,000 TPM, but
only a couple of investigations per minute — a burst of testing will return HTTP 429, which
surfaces honestly in `missing_information` rather than as a crash.

**The LLM timeout is now configurable** — `llm.timeout_seconds` in `config.json` (set to 300),
read by `wfm/llm_client.py`. This is a SEPARATE transport from
`rca_investigate._call_openai_compatible` on purpose: that file is kept byte-identical to
`shivam-updates` so the original engine cannot regress, and it keeps its own 100s.

Measured provider behaviour for a full WFM investigation:

| Provider | Time | Notes |
|---|---|---|
| Groq `llama-3.3-70b-versatile` | 2.4–5.7s | fastest, but a **100,000 token/day** cap — a day of development exhausts it, after which every call 429s and the engine degrades honestly |
| NVIDIA `nemotron-3-super-120b-a12b` | **53–68s** | needs the raised timeout; **3/3 queues answered, 27/27 ranking checks passed** (`results/llm-ranking-report.json`) |

Both caps surface in `missing_information` rather than as a crash.

## Verification performed (refactor, 2026-07-28)

- AST parse of all 13 `wfm/*.py` modules plus `sql_backend.py`, `rca_wfm.py`, `rca_investigate.py`
- `wfm` package import, `rca_wfm` shim import (`rca_wfm.investigate_wfm is wfm.investigate_wfm` → True), `sql_backend` import
- `git diff --stat shivam-updates -- backend/rca_investigate.py rca_console.html` → **empty**
- **default mode** (no `mode=`) → `engine: llm`, all legacy keys, **no WFM keys leaked**
- **in-band gate** → `engine: wfm-not-investigated`, 0 causes
- **full WFM path via Groq** → `engine: wfm-llm` in **3.12s**; #1 `data_quality_issue` 90% High
  (auto-downgraded to *Hypothesis – To be Validated*), #2 `genuine_demand_event` 60% Medium;
  both the model's own challenges and the code-side skeptic entries recorded; all legacy keys present
- **`correlation_engine` unit checks** — identity exact (miss 300 = base 100 + rate 200,
  `reconciles: true`); missing-column path returns `available: false`; rank correlation retains
  `Actual_ASU` at 1.00 with a jargon-free sentence and rejects the rest with stated reasons
- **`skeptic` unit checks** — `plan_restatement` rejected when the plan did not change;
  `genuine_demand_event` retained when `forecast_sanity.verdict == actual_anomalous`;
  `eligible_cause_types()` returns only the supported type
- On live data, `correlations.driver_decomposition.available` is correctly `false` for
  `NA Core Spanish` — that queue has no `Actual_ASU` values

### SQL-backed path re-verified after the refactor (VPN restored, same day)

`?mode=wfm` end to end against live SQL, **3.63s**, `engine: wfm-llm`, with the deep context
confirmed present:

- 103 history weeks; last-4 avg 60.2, last-13 avg 61.8
- **same week last year found**: FW `202619`, actual 144.0, forecast 128.17
- all 5 ladder levels returned; `inherited_from: Region`
- channel siblings with real per-channel deltas (Voice +9,971, Chat +1,301, Email −1,114,
  Social Media −3,037); `migration_detected: false` — correct, they do not cancel out
- `data_quality.suspect: true`, 75.3× the typical week
- **relationships retained on live data**: `Planned_ASU` 0.60, `Actual_ASU` 0.53
- in-band gate back to **0.47s** (it was 42s only because the dead SQL host burned the ODBC
  login timeout)

Then three unrelated real queues, each with both ASU columns present:

| Queue / week | Adherence | Decomposition | Ladder | Top cause |
|---|---|---|---|---|
| ROLA Client Core Email FW202652 | 32.4% | miss −193.0 = base −109.8 + rate −83.2, reconciles | inherited from Channel | `inherited_from_higher_level` 80% High |
| ROLA Client Opti-Lat-Prn FW202652 | 29.8% | miss −118.5 = base −73.3 + rate −45.2, reconciles | inherited from Channel | `inherited_from_higher_level` 65% Medium |
| ROLA Comm Client DSP FW202652 | −31.9% | miss 30.0 = base −17.3 + rate 47.3, reconciles → contact-rate driven | not inherited | `volume_routing_shift` 45% Medium |

**The decomposition identity held exactly on every live case.** The skeptic rejected a real
proposed cause on two of the three — `forecast_baseline_error` with *"the forecast was not
unusual against its own history, so this cause is not possible for this week"* — which is
precisely the class of unsupported verdict the old engine published unchallenged.

Two of the three landed on `wfm-deterministic-fallback` because three investigations in quick
succession exceed Groq's 12,000 TPM. They still produced a full ranked report from the
deterministic signals, correctly labelled — the intended degradation.

### Two output fixes made during this verification

1. **Confidence label now derived, not trusted.** The model returned `"Medium"` for 80%, which
   contradicts its own stated bands. `normalise_causes` now always derives
   High/Medium/Low from `confidence_pct`.
2. **`technical_metrics` merged rather than replaced.** A short list from the model was
   suppressing the computed metrics entirely (2 rows instead of 13–15). Computed metrics now
   lead, with any extra model rows appended.

## Verification performed

- AST parse of `rca_wfm.py`, `sql_backend.py`, `rca_investigate.py`
- `git diff --stat shivam-updates -- backend/rca_investigate.py rca_console.html` → empty
- default mode (no `mode=`) → `engine: llm`, all legacy keys, **no** WFM keys leaked
- `?mode=wfm` → `engine: wfm-llm`, 2 ranked causes, skeptic review populated, ladder
  correctly reporting the miss as inherited from **Region** level
- threshold gate on a −3.0% bundle → `engine: wfm-not-investigated`, 0 ranked causes
- all 11 legacy keys present on a WFM response, so the current UI renders it
- SQL fetch on a live queue: 104 history rows, 4 forward rows, 92 channel-sibling rows,
  5 ladder levels

## Not done / next

1. **No evaluation set.** Correctness of the ranking is still unmeasured — the checks above
   prove the engine runs and that the deterministic gates fire, not that verdict #1 is right.
   A labelled set of past misses scored on top-1 accuracy is the prerequisite for tuning
   this prompt further.
2. **`correlation_engine` is not implemented.** The prompt asks for ASU↔demand,
   installed-base↔demand and holiday↔demand relationships "consistently supported by
   history". Nothing computes them yet, so the model is asked for correlations it has no
   numbers for. This is the largest remaining gap in the spec.
3. **ASU driver decomposition is not wired in.** `Planned_ASU` and `Actual_ASU` allow an exact
   split of the miss into a warranty-base effect and a contacts-per-unit effect:
   `volume = (Actual_ASU − Planned_ASU) × planned_rate`, `rate = Actual_ASU × (actual_rate −
   planned_rate)`, which sum identically to the total error — verified exact on all 22,003
   flagged misses that carry both columns (60.7% rate-driven, 9.8% base-driven, 29.6% mixed).
   This is real attribution and should become a first-class signal.
4. **`derive_features` looks for a column named `ASU`** when building the proof panel, but the
   table has only `Planned_ASU` and `Actual_ASU` — that proof row silently never populates.
5. Uploaded CQN mapping is not consumed by this engine (see above).

---

## Branch `approved-test` — the two added cards (2026-08-05)

Additive to the `approved` branch. Both cards render nothing extra when their data is
absent, so an existing report is unchanged.

### Scope card — `investigation_ladder`

The ladder was computed on every run and **never returned**. `_assemble()` emits only the
keys in `RESPONSE_DEFAULTS`, so the figures were built, used internally, then discarded —
the console could say "inherited from Country level" while holding nothing a reader could
check that against. Now emitted by both `_assemble()` and `_fallback()`.

Also added: the **Offering** rung. `data_access.py` had Country → Channel with nothing in
between, and `sql_backend.py` did not carry `Offering` in the context key, so that level
was skipped. Six rungs now: Business Org · Region · SubRegion · Country · Offering · Channel.

### Interrogation card — Prompt 2 over Prompt 1

    engine produces the report      ranked causes, confidence, skeptic verdicts -- FIXED
        |
    Prompt 2 asks WHY               of the bullets the engine actually produced
        |
    Prompt 1 answers                from the evidence bundle, one call per question

Runs **after** the report is complete, so it cannot change a conclusion. Two separations
carry the design:

1. **Questioner and answerer are different calls.** Asking one model "why did you say
   that?" gets recall, and it will always produce something fluent rather than admit it
   cannot support the claim. The answerer never sees the questioner's reasoning.
2. **One call per question.** Batched, the model collapses onto whichever finding is most
   striking — that is how two questions came back with the same answer on the prior branch.

`why_prompt` enforces two rules that were learned from failures, not designed up front:
RULE 1 (a question must trace to a supplied bullet) and RULE 1B (**record, not intent** —
"why didn't anyone adjust the plan" is unanswerable from any dataset; "was the plan
reissued during the run" is answerable). `_BANNED_TERMS` blocks questions about data this
deployment does not hold: marketing, product versions, AHT, events, reason codes, routing,
deflection.

Weaker models return usable questions while omitting `arises_from`, and the validator then
drops all of them — which made this look like a one-model feature. A schema-repair retry
took `nemotron-3-ultra-550b` from 0 questions to 4.

### `evidence_pack.py` — computed once, used twice

Into the **model payload** so the bullets cite facts instead of asserting a bias in the
abstract, and into the **interrogation** so those same facts are answerable. Computing it
once for both keeps them consistent; a narrative quoting one figure while the interrogation
quotes another is worse than either alone.

`key_facts` are finished English sentences, not nested structure — deliberately. Measured
on the prior branch: asked when under-forecasting started, the model answered "not
available" while holding a 26-row series with a signed gap on every row. The figure was
present; the nested lookup was the failure.

Every block is individually guarded, and `_safe_evidence_pack()` guards the call site. The
pack is additive and must never be able to fail an investigation.

### Three defects fixed while wiring this

| Defect | Effect | Fix |
|---|---|---|
| `interrogation` never imported in `investigation_engine.py` | `NameError` on **every** run, swallowed by a broad `except` into a report with no card | added to the `from . import` block |
| interrogation attached only to the model-success path | on any queue where no cause survived the skeptic — exactly when questioning matters most — it silently never ran | `_with_interrogation()`, used by **both** exit paths |
| `back_compat`: `.get("this_week_vs_usual", {}).get(...)` | **pre-existing on `approved`.** The default applies only when the key is ABSENT; `derive_features` emits it set to `None`. `AttributeError` → `_assemble` is outside the retry `try` → **HTTP 500 for the whole investigation** | `or {}` instead of a `{}` default |

`renderInterrogationCard` previously returned `''` for most failure modes. A card that
vanishes leaves the reader unable to tell whether the feature is off, loading, or broken —
the exact question it could not answer for itself, and the reason the import bug went
unnoticed. It now always renders, stating its reason.

### Verified live (2026-08-05)

`CSG / Americas / NA / United States / Pro / Email`, FW202719, adherence −18.8%,
`nemotron-3-super-120b`, 104 weeks fetched, 143s:

- Scope card: 6/6 rungs with figures.
- Interrogation: 3 questions, 2 answered from evidence, 1 correctly refused
  (channel-level splits are not in the bundle) with `what_would_be_needed` stated.
- One answer **contradicted the narrative**: the root cause claimed +17.5%, and the
  answerer checked both baselines (FW202718 = 289, FW202619 = 311 against 360) and
  reported neither yields that figure. This is the interrogation working as intended.

`results/smoke_test_modules.py` — 12/12 pass.

### Interrogation quality pass (2026-08-05)

Reported from the UI: every question came back "Cannot be answered from the available
data", and the questions were lookups ("what were the actual contacts…") rather than WHY.
Both were our defects, not data limits.

**1. The answerer was starved of blocks the questioner could see.** `_payload()` carried
`CHANNEL_SIBLINGS`, so the bullets cited Combined-Queue and per-channel figures.
`_evidence_bundle()` omitted it — so every question about those figures was unanswerable
while `group_total_this_week`, `group_total_prior_week` and `cqn_total_change_pct` (the
very +360.7% being asked about) sat one key away. **The bundle must mirror the payload.**

Same failure a second time in `_relevant_blocks`: questions arrive saying "region-level
forecast", never "ladder", so `investigation_ladder` was filtered out of the evidence for
exactly the questions it answers. Level names are now routable.

**2. `AVAILABLE_DATA` promised blocks that do not exist here** — `hypotheses_generated`,
`why_chain` are spec-v2 only. The questioner was told they were answerable and asked about
them. The table now matches the real bundle.

**3. RULE 1B over-corrected into lookups.** Its "ask instead" column was entirely
retrieval-shaped, so the model produced retrieval. Added **RULE 1A**: every question must
open with *Why* / *What explains* / *What accounts for*, enforced in code by
`_is_why_form()` — checking the OPENER, since "What were the contacts, and why does that
matter?" is a lookup wearing a why as a suffix. RULE 1B now has three columns: intent
(never), lookup (rejected by 1A), and **WHY answerable by comparison** — the target.

**4. The answerer read "Why" as demanding a motive** and refused, correctly noting no
reason is recorded. But no reason is EVER recorded — that refusal invalidates every
question forever. Added a section defining what a WHY answer is here: **attribution** —
localise the movement, quantify the share, contrast it with what did not move. "No reason
or driver is recorded" is now explicitly not a valid refusal.

**5. Numeric validator false positive.** "Voice accounts for 100% of the rise" was dropped
as a fabricated figure. Percentage-suffixed values ≤ 100 are shares — arithmetic over two
supplied figures — and are now exempt. Unsuffixed numbers (contact volumes) and growth
claims above 100% are still checked, which is what the guard is for.

**UI:** unanswered questions are no longer rendered. A question shown above "cannot be
answered" reads as the tool failing, and in every case investigated it WAS the tool
failing. They remain in the response for diagnosis and are counted when none survives, so
a systematic failure is still visible rather than hidden.

#### Verified — `NA Federal Standard`, FW202719

Before: 3 questions, 0 answered, all lookups. After: WHY-form throughout, and the exact
question that previously failed now answers in full —

> **Why did total demand across the Combined Queue increase by 360.7%?**
> The entire increase came from Voice. FW202718 Voice actual was 331; FW202719 it jumped to
> 1,525, a rise of 1,194. No other channel changed, so the Combined Queue rose 331 → 1,525.
> The plan for Voice that week was 364 — the channel driving all the growth was also the
> one forecast lowest. *(channel_and_combined_queue)*

#### OPEN — a narrative fabrication the interrogation exposed

Two questions still refuse, both asking about **Chat**. They are right to. Queried
directly: this locality has **only Voice rows** in FW202718 and FW202719 — no Chat exists.
Yet the root cause states "Voice became over-forecast while Chat became under-forecast".
**That claim is fabricated**, and the skeptic did not catch it because its numeric
grounding checks figures, not the existence of a named channel. Needs a separate fix in
`skeptic.py`: a cause naming a channel must verify that channel is present in
`channel_siblings`.
