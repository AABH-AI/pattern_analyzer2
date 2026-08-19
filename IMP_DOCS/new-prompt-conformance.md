# `new_prompt.md` conformance — audit, build log and plan

Audited **2026-08-18** against branch `test3` (`5b1cdf7`), engine `?mode=spec`, card `2.1.0`.

Re-run it yourself:

```
python results/audit_new_prompt_conformance.py
python results/audit_new_prompt_conformance.py "Brazil Comm Client CEM ProSupport" 202722
```

**No model tokens are spent.** The audit calls `spec_engine.investigate` with an empty `llm_cfg`
and `interrogate=False`, so no provider is contacted. Everything it inspects is deterministic and is
produced before step 14; the only thing absent is the prose, and prose is not what decides
conformance.

Queues used: `SA Indonesia Client Basic` FW202716 (holiday case), `UKI Comm Client DSP Standard`
FW202717 (calendar case), `Brazil Comm Client CEM ProSupport` FW202722 (driver case — Pro offering,
`Planned_ASU` 2,307,202 and `Final_Units` 12,088, so drivers are genuinely exposed).

---

## Headline: 23 of 33 checks already pass

The spec asks for seven enrichments. Five are substantially built. Rebuilding them would have been
the expensive mistake, which is why this audit ran first.

Confirmed working, on live data:

| Clause | Evidence from the run |
|---|---|
| §4–5 holiday identity | `event_key: ascension+christ+jesus`, `canonical_name`, `name_variants`, `needs_review` — bridge days separate, `Aggregate_Group` rejected as an identity |
| §6 phase window | `phase=post_holiday`, `offset_weeks=[-1,1,2]`, `span_weeks=2` |
| §6 the key one | `row_holiday_count=0` **and** `phase=post_holiday` — a zero-holiday week correctly read as post-holiday |
| §9 phase effect | `testable: true`, **27 instances**, measured against the queue's own non-holiday baseline |
| §10 historical response | consistency measured — `0.519` on SA Indonesia |
| §11 weekend | returns the spec's required sentence verbatim: *"Weekend impact cannot be isolated from fiscal-week totals because day-level actual and forecast data is unavailable in the source."* |
| §14 forecast response | `miss_decomposition.reconciles = true` — the split is an exact identity, not an apportionment |
| §20 ASU | population vs contact-rate split present, and honest when `Actual_ASU` is absent |
| §22 | `wrong_direction` already named |
| §23 | `COMPOUND_MISS` already the resolved mechanism on SA Indonesia |
| §25–26 | confidence `Medium 60.5%` and criticality `Moderate` produced independently |
| §2 fail-safe | full RCA produced with **no LLM at all** — status `Incomplete`, everything else complete |

### A correction to my own first pass

My first audit reported **13 MISSING**. Three were false negatives: it looked for a `phases` dict
that does not exist (the real keys are `phase`, `holidays_by_offset`, `offset_weeks`,
`phase_effect`), and it marked the driver clauses MISSING when the driver block had simply never
been *requested*.

That second error is the exact confusion §17 forbids — treating *not tested* as *not present*. The
audit now carries a fourth state, `n/a-here`, for a block that is built but had nothing to work on.

---

## FINDING 1 — the most important one: §17 is violated verbatim

On `Brazil Comm Client CEM ProSupport` FW202722, the driver gate publishes this:

> "planned units for delivery (shipment) (`Final_Units`) **does not track this queue's demand**
> (r=−0.22 over 155 weeks, below the 0.3 threshold), so it is **Not Applicable** for this queue and
> carries no confidence penalty."

§17 says, in as many words:

> Never say "ASU is not a driver" simply because correlation is below threshold.
> For shipment: *"Same-week shipment activity does not explain the miss. A lagged relationship
> should be evaluated before shipment influence is rejected."*

Three separate problems in that one sentence:

1. **It asserts absence from a sub-threshold coefficient.** r = −0.22 over 155 weeks is a weak
   *inverse* relationship, not an absent one. The spec's required reading is "not confirmed".
2. **It is labelled `NotApplicable`**, which in this engine's own vocabulary means *"never relevant
   to this queue — no action, no penalty"*. The honest label for measured-but-weak is different, and
   the distinction is load-bearing elsewhere in the same codebase.
3. **The direction is discarded.** −0.22 and +0.22 mean opposite things operationally; the sentence
   treats both as "does not track".

### And it has a structural consequence

All five Business hypotheses (BUS-01…BUS-05) are `NotApplicable` *because* the gate rejected every
driver first. `lagged_driver_evidence` is hypothesis-selected, so it is never requested:

> "no business hypothesis was generated for this queue, so no driver relationship was requested.
> Nothing was tested and nothing is claimed either way."

So the richer analysis the spec asks for in §16 — level **and** change relationships, lags
0/1/2/4/8, half-history stability, three coverage states — **never runs on any of the three queues
tested**. The machinery is well built and effectively unreachable.

In fairness to the existing design: the gate *does* scan lags 0–13 for flow measures, and treats ASU
as a stock measure tested contemporaneously on purpose. So the rejection is not naive. The defect is
that a rejection at the gate is **terminal** — nothing downstream can revisit it, and §16/§17 exist
precisely to say it should not be.

---

## FINDING 2 — six genuine gaps

| Clause | Gap | Note |
|---|---|---|
| §9 | holiday→post **change** not separated from post-level **vs baseline** | spec's explicit ban on calling a +58.3% week-on-week move a "holiday effect" |
| §10 | five repeatability **bands** absent | numeric consistency exists (`0.519`); the named bands HIGHLY / MODERATELY REPEATABLE / EMERGING / NOT SUPPORTED / NOT ENOUGH DATA do not |
| §12 | holiday × weekend **interaction** not measured | detection already exists (`holiday_day_structure` → `on_weekend`, `adjoining_weekend`, `pattern`); nothing compares effect size by pattern. Measurable from weekly totals |
| §15 | 3 failure types absent | `FORECAST_RESPONSE_LAG`, `SEASONALITY_MIS_SPECIFICATION`, `DRIVER_SIGNAL_NOT_AVAILABLE` — agreed to add beside the existing 7, with a published mapping |
| §16 | Pearson alongside Spearman | `lag_analysis` uses Spearman only; the gate uses Pearson. Two different measures on the same question, never reported together |
| §16 | relationship during forecast-**miss** weeks | not built |
| §27 | causal verbs not banned | `EXEC_JARGON` holds 23 statistical terms; `caused` / `drove` / `generated` / `resulted in` are not among them |
| §28 | A–F card view | agreed: add over the existing 18 sections, non-breaking |

---

## Decisions taken (recorded so they are not re-litigated)

1. **`?mode=spec` only.** Every mechanism the spec describes lives there; `?mode=wfm` is a separate
   engine with its own hypothesis universe and no Decision Card.
2. **A–F is a VIEW over the existing 18 sections**, not a restructure. §28 and §1 conflict — §1 says
   do not reorder existing UI fields — and §1 wins because it is the non-breaking guarantee.
3. **Keep the 7 mechanisms, add the 3 new distinctions, publish a mapping.** Renaming would change
   published response values, `MECHANISM_HYPOTHESES` keys and the FC semantics suite.
4. **Audit before building.** This document is that audit.

---

## Build order

Ranked by how much a reader's conclusion changes, not by effort.

1. **§17 narration + the terminal-rejection problem.** Stop asserting "does not track", report
   strength / direction / sample / lag scanned / coverage, and re-label measured-but-weak as
   not-confirmed rather than Not Applicable. Then let the lag evidence run for drivers the gate
   rejected on a weak-but-present coefficient, so §16's analysis is reachable. **This is the one
   that changes what people conclude from a card.**
2. **§27 causal-verb ban** — cheap, checkable, and it protects every sentence on the card.
3. **§9 rebound vs baseline separation** — a wording-level correctness fix with a worked example
   already in the spec.
4. **§10 five bands** over the consistency rate that is already computed.
5. **§12 holiday × weekend interaction**, grouping historical instances by the `pattern` that
   `holiday_day_structure` already returns.
6. **§15 three new failure types** + mapping table.
7. **§16 Pearson beside Spearman, and behaviour during miss weeks.**
8. **§28 A–F view.**

Every item above is additive. None changes an existing calculation, threshold, confidence or
criticality value — which is §1, and §1 is the constraint the whole document rests on.

---

## BUILD LOG

Updated after each edit. Every item is additive: no existing calculation, threshold, confidence or
criticality value changed, which is §1. Suites re-run after each one —
**smoke 12/12 · FC semantics 189/189 · WFM diagnostics 148/148 · UI render 18 cards**, all exit 0.

### DONE — #1 §17 narration, and the lag analysis made reachable

`backend/wfm/driver_gate.py`, `backend/wfm/fc_evidence.py`, `backend/wfm/spec_engine.py`

**The sentence.** The gate published *"planned units for delivery (shipment) does not track this
queue's demand (r=−0.22)"*. It now reads:

> "…shows a **weak inverse** relationship with this queue's demand (r=−0.22 over 155 weeks; 0.3 is
> the minimum this gate counts as tracking), **best of lags 0–13 was 2 week(s)**. On this evidence
> the relationship is **NOT CONFIRMED, which is a weaker claim than absent** — a coefficient below
> the threshold is not proof the driver has no influence."

New fields: `relationship_state`, `direction`, `strength_band` (negligible → very strong).
`evaluate_all`'s aggregate note carries the same correction.

**The gate DECISION is unchanged on purpose.** `relevant` and `verdict` feed a confidence dimension,
and §1/§25 forbid moving confidence. Confidence on SA Indonesia FW202716 is still `Medium 60.5%`.

**The structural half.** §16's lag analysis was *unreachable in practice*: the gate rejects the
drivers → no Business hypothesis fires → nothing requests the lag test. All three audited queues
reported "nothing was tested". Gate results now travel into `lagged_driver_evidence`, so a driver
rejected on a measurable-but-weak coefficient is re-examined at lags 0/1/2/4/8 on **both** levels
and week-to-week change, published under `enrichment` with `feeds_confidence: False`,
`feeds_hypotheses: False`, `changes_the_gate_verdict: False`. It cannot promote a driver.

```
Actual_ASU    10 candidates  strongest = lagged_level  lag 8  rho +0.24  clears=False
Final_Units   10 candidates  strongest = lagged_level  lag 2  rho -0.21  clears=False
```

It also surfaces a sign disagreement that was previously invisible: on SA Indonesia the gate reads
**inverse** (r=−0.20) while the strongest change-relationship is **positive** (+0.14) — the
shared-trend signature.

*Bug found while building:* the first version read `best`, which `lag_analysis` only sets when a
candidate clears **MIN_STRENGTH = 0.5**. For exactly the weak drivers this exists for, `best` is
always `None`, so the block merely restated the gate. It now reports the strongest *candidate*
regardless, via `_strongest_candidate()`.

### DONE — #2 §27 causal verbs

`backend/wfm/decision_card.py`

A **separate list** from `EXEC_JARGON`, deliberately. "Spearman rho" is banned unconditionally; a
causal verb is banned *"unless causal evidence is sufficiently strong"*. Folding them together would
assert the wrong rule and retroactively fail legitimately causal prose.

`CAUSAL_VERBS` (11 terms) + `causal_verbs_in()` + `HEDGED_ALTERNATIVES` (published so a writer gets
the replacement, not just the prohibition). Reported per bullet as `causal_verbs_found` and
panel-wide, never stripped — a bullet whose evidence supports causation may say so, and a reviewer
needs to see which verb was used.

Whole-word matched by **padding, not a regex boundary**: `` written through two layers of quoting
became a literal backspace character in the file. Padding has nothing to escape. 8/8 cases,
including the traps — `reproduced` does not fire "produced", `controlled to` does not fire "led to".

Honest note: the deterministic bullets are already clean (`causal_verbs_found: []` on both queues).
The value is as a guard on the **narrative model's rewording** at step 14, which is where a causal
verb would actually appear.

### DONE — #3 §9 rebound separated from level-vs-baseline

`backend/wfm/holiday_response.py` — new `phase_transitions()`, exposed as `phase_transition`.

The two quantities §9 forbids conflating are now both published, side by side:

| | SA Indonesia FW202716 |
|---|---|
| **A** week-on-week transition (`phase_transition`) | **+58.33%**, FW202715 (96) → FW202716 (152) |
| **B** level vs non-holiday baseline (`phase_effect`) | **−2.24%** across 27 instances |

The required sentence is built in the module rather than left to a caller:

> "58.33% post-holiday rebound from FW202715 (96.0 contacts) to FW202716 (152.0)."

This is the spec's own worked example, reproduced from live data — and it shows why the ban matters:
the holiday phase runs 2% **below** baseline while the move into the target week is **+58% up**. The
rebound is recovery from a trough, not the holiday's effect.

Historical distribution now available (and it feeds #4 directly): **26 instances, median +11.04%,
mean +28.27%, range −34.41% to +216.07%, positive share 0.65, spread 250 points** — "recurring but
inconsistent", exactly §10's required reading.

*Two bugs found while building, both mine:* `_phase_of` returns a **tuple** `(phase, span)`, so
comparing it to a phase constant was silently always false and the first version found zero
transitions on a queue that plainly has one — hence `_phase_name()`. And `_rows()` deliberately
**excludes the target week** so history cannot leak the answer, so the target's own actual has to be
passed in rather than looked up.

### DONE — #4 §10 the five repeatability bands

`backend/wfm/holiday_response.py` — new pure `repeatability()`, exposed as
`phase_transition.repeatability` and mirrored at the top level as `rebound_repeatability`.

**Thresholds are derived, not invented.** The middle bar IS `CONSISTENT_SHARE` (0.70), the bar this
module already used to call a phase effect "consistent" — a second, disagreeing figure for the same
idea is the mistake the criticality work avoided by reusing the 50-contact floor. `LARGE_CHANGE_SHARE`
is `MATERIAL_SHARE × 2`, so there is one scale in the module, not two. Only
`MAGNITUDE_SPREAD_LIMIT = 2.0` is a fresh judgement, and it is flagged in the code as versioned
configuration wanting client confirmation, the way `CAPTURE_TOLERANCE` is.

| Band | Condition |
|---|---|
| NOT ENOUGH DATA | fewer than `MIN_PHASE_INSTANCES` (4) instances |
| HIGHLY REPEATABLE | direction consistency ≥ 0.85 **and** magnitude predictable |
| MODERATELY REPEATABLE | consistency ≥ `CONSISTENT_SHARE` (0.70) |
| EMERGING / INCONSISTENT | consistency > 0.50 |
| NOT SUPPORTED | consistency ≤ 0.50 |

**Two properties, not one score.** §10 lists variability beside consistency and they answer different
questions: does it move the same way, and is the size worth quoting. A set can be reliable in
direction and useless in magnitude — which is precisely the spec's example. So the band is decided by
direction and the magnitude verdict rides beside it, rather than being averaged into one number that
hides which half failed.

Consistency is measured against the **median's** direction, not against zero, so a queue whose
rebounds are reliably *negative* scores as consistent rather than inconsistent.

**Unit-tested in isolation before being wired into the engine.** The spec's own example
`[+29, −47, +89, +58]` returns MODERATELY REPEATABLE with:

> "Across 4 past instances this queue's post-holiday rebound has run upward 43.5% at the median
> (−47% to 89%), moving the same way 75.0% of the time. The direction is a usable forecasting signal;
> the size is not — the range is 136 points wide, so this should be treated as a **directional signal
> rather than a fixed uplift**."

which is §10's required interpretation almost verbatim, and never says a holiday "causes" anything —
confirmed by running `causal_verbs_in()` over every generated reading.

All five bands confirmed reachable; every boundary case checked (0.500 → NOT SUPPORTED, 0.667 →
EMERGING, 0.714 → MODERATELY, 0.857 + tight → HIGHLY).

*One test-expectation error, mine not the code's:* I labelled `[20, 15, −12, 18, −22, −9]` as
"leans but unreliable" and expected EMERGING. Its median is 3.0 with three up and three down —
consistency exactly 0.500, which is a coin flip, so NOT SUPPORTED was correct. A genuinely leaning
set needs 4 of 6.

On live data the bands discriminate:

| Queue | Instances | Consistency | Band |
|---|---|---|---|
| SA Indonesia FW202716 | 26 | 65.4% | EMERGING / INCONSISTENT |
| Brazil CEM ProSupport FW202722 | 25 | 80.0% | MODERATELY REPEATABLE |

That matters for the case this project has argued about all week: Indonesia's post-holiday rebound
now carries "recurs but is not reliable — should inform a forecaster's judgement and should not be
applied as a fixed adjustment", which is the engine stating its own uncertainty on exactly the
conclusion the validation disproved.

**Audit movement:** PRESENT 23 → **25**, MISSING 6 → **4**.

### DONE — #5 §12 holiday × weekend / long weekend

`backend/wfm/fc_evidence.py` — new `holiday_weekend_interaction()`, attached to `weekend_evidence`
as `holiday_weekend_interaction`. Placed in `fc_evidence` because it already imports both
`data_granularity` and `holiday_response`; putting it in the shared `holiday_response` would have
added a new cross-import to an engine-agnostic module.

**What it can and cannot say.** Weekly totals still cannot isolate a weekend volume effect — §11 and
`weekend_evidence` both say so and that has not changed. What the per-day holiday flags DO permit is
grouping this queue's own holiday weeks by *where the holiday fell* and comparing the **week-level**
total between those groups. A long weekend removes more consecutive contactable days than a midweek
holiday, so if that matters for a queue it shows up as a difference between groups. That is a real
answer to §12 and is **not** the claim that the weekend moved volume — stated in the block's own
`measures` field.

**Data checked before any code was written.** Both audited queues have 157 history rows with
`holiday_day_of_week` capability and four distinct non-none patterns, each clearing
`MIN_PHASE_INSTANCES`. Had every holiday week shared one pattern, the honest move would have been to
report it unmeasurable rather than ship a check that always says "not testable".

**Thresholds reused, not invented:** `hr.MIN_PHASE_INSTANCES` (4) for a group to be measurable,
`hr.MATERIAL_SHARE` (10 percentage points here) for a difference between groups to count.

The reference group is named precisely — *weeks with no holiday day flagged* — because it is **not**
the same construct as `holiday_response`'s non-holiday baseline, which also excludes pre- and
post-holiday phase weeks. Two similar baselines under one name is exactly how §9's measurement A and
B came to be conflated.

Live results:

| Pattern | SA Indonesia (ref 111.0, n=107) | Brazil CEM ProSupport (ref 217.5, n=120) |
|---|---|---|
| holiday adjoining weekend | −15.3% (n=24) | −31.0% (n=13) |
| **holiday on weekend** | **−0.9%** (n=7) | **+2.1%** (n=7) |
| midweek holiday | −24.8% (n=12) | −30.6% (n=12) |
| multiple holiday days | +9.0% (n=5) | −59.1% (n=5) |
| long-weekend contrast | 9.5 pts — **not material** | 0.4 pts — **not material** |

**Two independent sanity checks that the measurement is real, not noise:**

1. `holiday_on_weekend` lands at ≈0% on **both** queues (−0.9%, +2.1%) — exactly what you would
   predict, because a Saturday or Sunday holiday falls on days already non-working, so the week's
   total is barely touched. Nobody told the code that; it fell out of the data.
2. Brazil's `multiple_holiday_days` is the deepest group at −59.1% — more holiday days, fewer
   contactable days.

Point 1 is the practically useful finding: **holiday COUNT alone overstates impact when the holiday
falls at the weekend.** `holiday_day_structure` already warned of this in prose; it is now quantified.

On both queues the long-weekend structure does **not** make a material difference, and the block says
so with the figures. §12 says "only report this when the data supports it", so a measured
"no material difference" is the correct output, not a silence.

Also fixed: the audit's own §12 detail line still read "effect-by-pattern not measured" while
reporting PRESENT — a self-contradiction of the same kind flagged in `fc-decision-card-engine.md`.
It now prints the real contrast.

**Audit movement:** PRESENT 25 → **26**, MISSING 4 → **3**.

### DONE — #6 §15 three failure types + the 7→8 vocabulary mapping

`backend/wfm/fc_evidence.py` — `SPEC_TAXONOMY_MAP`, `refine_mechanisms()`, `REFINEMENT_MEANING`;
`miss_mechanism()` now also returns `refinements` and `spec_taxonomy`.

**Why refinements and not three new mechanisms.** `miss_mechanism`'s candidate list feeds
`MECHANISM_HYPOTHESES` → `rejected_ids` in `spec_engine`, and the `ModelAgreement` confidence
dimension reads mechanism evidence. Appending candidates could therefore have **moved confidence**,
which §1 and §25 forbid. So `mechanisms`, `primary`, `compound`, `candidates` and `attaches_to` are
untouched and the refinement rides beside them — §24's own instruction: *do not replace, enrich*.

| Existing mechanism | Spec name |
|---|---|
| FORECAST_BASELINE_FAILURE | FORECAST_BASELINE_UNDER_LEVELING |
| CALENDAR_RESPONSE_FAILURE | INSUFFICIENT_CALENDAR_ADJUSTMENT |
| DRIVER_RESPONSE_FAILURE | INSUFFICIENT_DRIVER_RESPONSE |
| DEMAND_EVENT_LOW_PREDICTABILITY | LOW-PREDICTABILITY_DEMAND_EVENT |
| COMPOUND_MISS | COMPOUND_FORECAST_MISS |
| FORECAST_RESPONSE_FAILURE | *(generic form of the INSUFFICIENT_* family — no single counterpart)* |
| DATA_LIMITATION | *(no counterpart; retained, because "no defensible mechanism" is a real outcome)* |

The three genuinely new distinctions:

- **FORECAST_RESPONSE_LAG** — the plan reacted, but *late*. `forecast_response` already separated
  `delayed_response`; the mechanism layer collapsed it into FORECAST_RESPONSE_FAILURE, so "reacted
  too little" and "reacted too late" were indistinguishable. Different remedies: the size of the
  adjustment versus when the plan is refreshed.
- **SEASONALITY_MIS_SPECIFICATION** — the plan did not represent the level this week of the year
  reliably reaches. Derived from `baseline_error`, which the engine already reconciles exactly, and
  fires **only** when `expected_basis_key == "same_week_median"`: a material baseline error measured
  against a *recent window* is a level error, not a seasonal one, and calling it seasonal would be a
  claim the basis does not support.
- **DRIVER_SIGNAL_NOT_AVAILABLE** — no usable driver history existed to react to. A data gap, as
  against DRIVER_RESPONSE_FAILURE's process gap. Different owners.

Fires on SA Indonesia FW202716:

> "The plan sat 42.2 contacts from the 106.0 expected for this week of the year (median demand in
> fiscal week 16 across 3 prior years) — 39.8% of that level. The miss starts in the seasonal profile
> the plan was built on, not in a within-week reaction."

**This partially unblocks the catalogue gap recorded in FINDING 1 of this document.** The plan-level
cause could not be *reported* because the Forecast category has only two entries and a 24th entry
needs an approver. A refinement is not a catalogue hypothesis, so the cause can now be named without
the spec amendment. The amendment is still the right long-term fix.

*One error caught before it shipped:* the first version read `baselines["target_forecast"]`, which
does not exist — the response block carries no target forecast at all. Verified against a live
payload rather than assumed, and rewritten onto `baseline_error`.

**§1 proof:** SA Indonesia confidence `Medium 60.5%` and criticality `Moderate`, identical before and
after.

### DONE — #7 §16 Pearson beside Spearman, and the relationship during miss weeks

`backend/wfm/lag_analysis.py` — `_pearson()`, `_miss_week_relationship()`, new constants
`RANK_LINEAR_TOLERANCE` / `MISS_THRESHOLD_PCT` / `MIN_MISS_PAIRS`.

**Both additions are informational.** `relationship_strength` stays **Spearman**, so `strong_enough`,
`_best` and `usable_as_evidence` are untouched. Spearman remains the decision measure because it is
rank-based and so is not dragged by a single extreme week, which weekly contact volumes produce
routinely. Pearson is published because §16 asks for both — and because the **gap** between them is
itself a reading: ranks agreeing where the linear fit does not means the relationship is real but not
proportional.

On live data the two agree closely everywhere (gaps 0.01–0.08, all `proportional=True`), so no
relationship on these queues is outlier-driven.

**The miss-week relationship is the more valuable half.** A driver can track demand across ordinary
weeks and say nothing about the weeks the forecast got wrong — and those are the only weeks an RCA is
about. Measured at the same lag and family as the strongest all-weeks candidate, so the figures are
comparable:

| Queue · driver | all weeks | during miss weeks | verdict |
|---|---|---|---|
| Brazil · `Holiday_Count` | −0.64 | **−0.66** (108 miss weeks, 73 paired) | holds, and strong |
| Brazil · `Final_Units` | −0.21 | −0.08 | collapses |
| SA Indonesia · `Actual_ASU` | 0.50 | 0.42 | weakens |

Brazil's `Holiday_Count` is the only driver that holds where it matters. `Final_Units` explains
ordinary weeks and not misses — invisible before this.

**A finding that challenges an existing rule, recorded rather than acted on.** SA Indonesia's
`Actual_ASU` reaches rank **0.50 at a 2-week lag** — exactly `MIN_STRENGTH`, the engine's own evidence
bar. The gate rejected that same driver at **r=+0.18**, because ASU is classed as a *stock* measure
and therefore tested contemporaneously only. On this queue the never-lag-a-stock-measure rule is what
discarded a usable signal. That rule was set from measured evidence across many queues and one
counter-example does not overturn it, so this is **flagged for whoever owns the rule, not changed.**

`MISS_THRESHOLD_PCT = 5.0` matches the engine's fixed ±5% generation threshold and is held as a
module constant with a comment saying so, because `lag_analysis` is engine-agnostic by design and
must not import `spec_engine`. If that threshold changes, this must change with it.

### DONE — #8 §28 the A–F view

`backend/wfm/decision_card.py` — `a_to_f_view()`, attached as `view_a_to_f`.

§28 prescribes sections A–F; §1 forbids reordering existing output. **§1 wins**, because it is the
non-breaking guarantee the whole document rests on. So all eighteen numbered sections stay exactly as
they are and A–F is published beside them, pointing at the same data. A renderer can present either.

Every field carries a **`from`** naming the section it was drawn from, so the view cannot quietly
become a second source of truth — if a figure looks wrong, the reader is told where it came from.
Nothing in it computes a number.

Verified on SA Indonesia FW202716: all 6/6 sections populate, the 18 numbered sections remain, and
`section D` correctly distinguishes `NOT_TESTED` (no hypothesis asked) from `NOT_CONFIRMED` (measured,
sub-threshold) from `AVAILABLE` — the §17 distinction, now visible on the card rather than buried.

*One error caught before it shipped:* the first version took a `header` argument and was attached as
`a_to_f_view(result, hdr)`. `build()` has no `hdr` local — the header is assembled inline in the
return — so that would have been a runtime `NameError` on every card. The view now reads
`forecast_summary` directly, the same source the header itself uses, and is independent of `build()`'s
locals.

---

## FINAL STATE

**Conformance audit: 34 / 34 PRESENT. Zero missing, zero unexercised.**

Six of the audit's own checks were stale after the build and were corrected — they had been testing a
hardcoded verdict, or the wrong container (§27's verbs are deliberately in `CAUSAL_VERBS`, not
`EXEC_JARGON`), or a payload key rather than the module that owns the behaviour. An audit that
under-reports is as damaging as one that over-reports; this is the same defect flagged earlier in
`fc-decision-card-engine.md`.

| Suite | Result |
|---|---|
| Module smoke | 12 / 12 |
| FC spec semantics | 189 / 189 |
| WFM diagnostics | 148 / 148 |
| UI render | 18 Decision Cards |

Every suite re-run after every one of the eight items, all exit 0.

**The §1 invariant held throughout:** SA Indonesia FW202716 reports confidence `Medium 60.5%` and
criticality `Moderate` — identical before item #1 and after item #8. Not one of the eight items
required new mathematics; every one was a reporting, routing or classification fix over figures the
engine already computed.

### Still open, and deliberately not done

1. **`fc_evidence.py` is overloaded** — FC adapter, criticality, ASU split, mechanisms, direction
   gate, resolution, evidence index, and now three more concerns. It wants splitting. Not done here
   because restructuring it mid-task is exactly the breakage risk the instruction was to avoid.
2. **Two lag vocabularies coexist** — `lag_analysis.LAGS = (0,1,2,4,8)` and the gate's `0..13` scan.
   Pearson was added to the first only.
3. **The ASU stock-lag rule** — see #7. A decision for the rule's owner.
4. **The suites never ask whether a conclusion is RIGHT.** All 189 FC checks passed through every
   defect found this week, including the holiday conclusion that pointed the wrong way. A test that
   asserts a conclusion agrees with the direction of the miss would be worth more than any remaining
   item on the spec's list.
5. **The 24th catalogue entry** is still the right long-term fix for the plan-level cause; #6 only
   routes around it.
