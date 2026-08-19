# WFM RCA Engine (`?mode=wfm`) — the business-authored investigation prompt

Branch: `wfm-rca` (off `shivam-updates`). Added 2026-07-28.
Code: the `backend/wfm/` package + a ~40-line opt-in branch in `backend/sql_backend.py`.
`backend/rca_wfm.py` is now a compatibility shim re-exporting the package.

## Module map

| Module | Responsibility |
|---|---|
| `wfm/investigation_engine.py` | orchestrates the workflow |
| `wfm/spec_engine.py` | **FC_RCA v2.0.0** — the 15-step canonical sequence (`?mode=spec`) |
| `wfm/hypothesis_catalogue.py` | the fixed catalogue of 23 candidate hypotheses |
| `wfm/cross_examination.py` | 18 challenge questions that try to disprove each hypothesis |
| `wfm/confidence.py` | confidence calculated from 8 weighted dimensions, never assigned |
| `wfm/driver_gate.py` | a driver is only a cause where \|r\| >= 0.30 for that queue |
| `wfm/statistical_evidence.py` | 15 metrics over 13/52/104-week windows, stdlib only |
| `wfm/recursive_why.py` · `why_rephrase.py` | the why-chain, and its rewrite into business wording |
| `wfm/decision_card.py` | the 10-section Executive Decision Card |
| `wfm/fiscal_calendar.py` | 4-4-5 fiscal periods, 53-week years as 4-5-5 |
| `wfm/context_repository/` | the Holiday Calendar (Phase 1 of the Context Repository) |
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

Run order, mirroring the prompt's own rules:

```
derive features (all deterministic)
  -> threshold gate            never investigate inside the band
  -> ONE model call            rank + explain + challenge, in business language
  -> skeptic.review            reject causes the features cannot support
  -> hypothesis_generator.mark downgrade over-confident statuses
  -> business_report_generator recompute the KPI, build the report, back-fill legacy keys
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
| M2 every data row is behind a mapped name | **66,612/66,612** *(as verified on `dbo.Input_To_ML`; the live table is now `dbo.Input_To_ML_Full_138_Trimmed` at 114,436 rows -- re-run `results/cqn_mapping_integrity.py` to re-verify)* |
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

## Field terminology — planned units (shipment), NOT the installed base

Settled 2026-07-30 from the business definitions. `Final_Units` is the **number of planned units
for delivery / production**, also called **Shipment**, and one of the major demand drivers.
`Final_Y1..Final_Y5` are those same planned units split by the warranty year they fall under.

Two rules matter for the engine:

1. **They are not the installed base.** The installed base is units already in the field — a
   different quantity. Calling planned units "installed base" sends a forecaster to the wrong lever
   (review the install base, rather than review the shipment plan).
2. **Y1..Y5 are NESTED, not additive.** Y5 ⊆ Y4 ⊆ Y3 ⊆ Y2 ⊆ Y1, so
   `Final_Y1 + ... + Final_Y5 ≠ Final_Units`. They must never be summed. This is also why
   `INSTALLED_BASE_FIELDS` collapses all seven columns into ONE signal (max |z|) — otherwise a
   single real movement is counted seven times and manufactures a dominant fake z-score.

### Where the definition lives (four places, kept in sync deliberately)

| Site | Read by |
|---|---|
| `rca_console.html` → Definitions & Formulas table | the user |
| `rca_console.html` → "Domain knowledge" card | the user |
| `rca_investigate.py` → `FIELD_DEFINITIONS` | **the LLM** (injected as `field_glossary`) |
| `wfm/prompts.py` → `TERMINOLOGY:` rule | **the LLM** |

### The terminology guard — why a prompt rule was not enough

A live WFM run **still produced "installed base" seven times** after every hardcoded string was
corrected: in `executive_summary`, `skeptic_review[].cause/.challenge`,
`investigation_trail.narrative` and `rejected_hypotheses[].hypothesis`. None of it came from our
code — the model writes the phrase unprompted, because that is the term it has learned for
warranty-unit fields.

So the term is rewritten **deterministically on the way out**, the same principle already applied
to the KPI, the migration verdict and the confidence bands: compute it in Python, then overwrite
whatever the model said. `_fix_terminology()` in `wfm/business_report_generator.py` walks the
response **recursively** and is wired into the tail of `apply_language_guard()`.

Recursion is the point: the pre-existing guard visited a fixed list of keys, which is exactly why
those four blocks slipped through. A newly added response key cannot silently reintroduce the term.

Internal identifiers are protected — every pattern requires a literal space, and bare snake_case
tokens are skipped, so the `installed_base_change` cause type (matched by the skeptic's
`PRECONDITIONS` and by the spec suite) and the `base_features.installed_base` key are untouched.
The cause-type key was deliberately **not** renamed: it is never displayed, and renaming it would
break the skeptic lookup and the compliance tests for no reader-visible gain.

The legacy engine gets the same pass via `_fix_terminology_legacy()` in `rca_investigate.py`
(lazy import — `wfm` imports `derive_features` from that module, so a top-level import would be
circular; wrapped in try/except so a cosmetic pass can never fail an investigation).

Verified live on both engines: **0 occurrences** of the old term in either response.

---

## FC_RCA v2.0.0 — the spec engine on this branch (`?mode=spec`)

Added on `spec-v2-refactor`, alongside the WFM engine rather than replacing it: the same queue can be
investigated both ways and compared, and rollback is a query parameter rather than a revert. The
**Engine** dropdown beside *Investigate Root Cause* selects it; it defaults to `WFM (current)`, so a
fresh page load shows the older engine.

### What is different in kind

The LLM is **demoted from investigator to writer**. Every figure, hypothesis, confidence score and
gate decision is computed in Python; the model only phrases what has already been decided, and every
number it writes is reconciled against the finding it came from.

| Module | Owns |
|---|---|
| `spec_engine.py` | the 15-step canonical sequence, the gates, response assembly |
| `hypothesis_catalogue.py` | a **fixed catalogue of 23** hypotheses, conditions evaluated in Python |
| `confidence.py` | confidence **calculated** from 8 weighted dimensions — never assigned by the model |
| `cross_examination.py` | 18 challenge questions that try to **disprove** each hypothesis |
| `driver_gate.py` | a driver may only be a cause where `\|r\| >= 0.30` **for that queue** |
| `recursive_why.py` | asks WHY to a bounded depth over the findings actually made |
| `statistical_evidence.py` | 15 metrics over 13/52/104-week windows, standard library only |
| `fiscal_calendar.py` | real 4-4-5, 53-week years absorbed into Q4 as 4-5-5 |
| `context_repository/holiday_calendar.py` | holiday lookup with an impact window into adjacent weeks |
| `decision_card.py` | the 10-section Executive Decision Card |
| `why_rephrase.py` · `narrative_prompt.py` · `why_prompt.py` | the three places an LLM is invoked |

### Three LLM calls, not one

`narrative_prompt.py` describes itself as "the ONLY place an LLM is invoked". It is not — a spec run
makes **three** calls: `why_rephrase.apply` (step 10b, rewrites the deterministic why-chain),
`_narrate` (step 14, the executive summary) and `_interrogate` (step 14b, optional, and it runs
*after* the RCA is fixed so it cannot influence a conclusion). The principle holds — none of them
decides anything — but the docstring understates the surface area.

### Key thresholds

| | |
|---|---|
| Generation threshold | **±5%** (the WFM engine uses ±10%) |
| Materiality floor | 50 contacts |
| Major deviation | 75% |
| Driver relevance | `\|r\| >= 0.30` over n >= 30 |
| History fetched | 157 weeks (`WFM_HISTORY_WEEKS`) |
| Trend fit floor | r² >= 0.30 |
| Plan vs seasonal norm | 25% |
| LLM | temperature 0.0, top_p 1.0, seed 20260730, timeout 150s |

Confidence weights (v2.0.0): ContradictoryEvidence 0.20 · EvidenceStrength 0.18 ·
BusinessRuleValidation 0.15 · StatisticalAgreement 0.14 · DataSufficiency 0.12 ·
ContextCompleteness 0.10 · HistoricalConsistency 0.06 · ModelAgreement 0.05.

---

## RCA type priority (business decision, 2026-08-13)

The order in which the RCA types are to be built out. Recorded because work has already been done
out of order and one line of it was rejected on review.

**1 — Channel mix (highest).** Volume shifting between channels: Voice→Chat, Chat→Email, Email→Case
and every other combination. The engine must quantify how much moved out of which channel and into
which, inside the drill-down group.

*State:* built and then **parked, not merged**, on branch `wip/rca-drilldown` (commit `f9601ff`).
The analysis was correct — verified on `Americas / NA / United States / Basic` FW202304, where the
group total moved only +1.5% while 4,133 contacts moved out of Voice, Chat and Email into Social
Media. The **presentation** was rejected, not the logic. Measured while building it: grouping the
mix by the mapped Combined Queue fires on only **10%** of groups (1.15 channels on average), while
grouping by `Region → SubRegion → Country → Offering` fires on **79%** (2.53 channels) — so the
drill-down path, not the CQN, has to be the grouping. Recoverable with
`git switch wip/rca-drilldown`; the useful parts can be cherry-picked without the rejected panel.

**2 — Holiday.** A major factor in explaining a high or low contact rate. Already substantially
built: `FC_RCA_Holiday_Master_Production.xlsx` → `holiday_master.json` (12,197 rows read, 9,757 kept
after de-duplicating repeated names within a country-week; 6,698 country-weeks; 79 country keys),
published to SQL as `dbo.Holiday_Master` and three companion tables, with `CAL-01 Holiday` generated
from the calendar's **impact window** — so it fires even when the source row's own `Holiday_Count`
is 0 because a holiday in an adjacent week reaches in.

**3 — Plan vs seasonal norm (base case).** Was the plan set away from the level this week of the
year reliably brings. Implemented as a metric and a ranked finding, but see the open spec gap below:
it has no hypothesis of its own, so it cannot yet become the reported cause.

---

## OPEN SPEC GAP — the plan-level cause has no hypothesis

`FC_RCA_RCA_Methodology.md` (on branch `MD`) defines the Candidate Hypothesis Catalogue, and its
**Forecast** category contains exactly two entries:

| Hypothesis | Generated when |
|---|---|
| Forecast Bias | consistent one-sided deviation across recent periods |
| Trend Misidentification | trend direction in actuals differs from forecast |

Neither covers *"the plan was set away from what this week of the year reliably brings"*. On
`SA Indonesia Client Basic` FW202716 that is the actual cause — plan 63.79 against a 3-year week-16
average of 122.33, **48% below**, with demand of 152 entirely normal for the week — and the queue has
no one-sided bias (+1.8 contacts over 52 weeks) and no trend mismatch, so **no Forecast hypothesis
can fire**. The finding is computed and ranked at 82% but cannot become the headline.

The methodology document makes this binding: *"Every hypothesis originates from the catalogue"* is an
acceptance criterion, and §6 *"prevails"* over other documents. So this needs a **24th catalogue
entry** — a specification amendment, not a code patch. That document's Approver is still "Pending".

---

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
