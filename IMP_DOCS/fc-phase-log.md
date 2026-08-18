# FC Decision Card upgrade — phase log (branch `test2`)

Base: `74f46c5` (an exact copy of `spec-v2-refactor`). **`main`, `spec-v2-refactor` and `test` are
untouched.** `test2` deliberately carries **no** WFM engine changes — those live on `test`.

Scope: `POST /api/rca-investigate?mode=spec` only — with two deliberate exceptions recorded in
steps 9 and 10 (console-wide UI surfaces, and one WFM file made honest after a column was dropped).

---

## Current state at HEAD — `5b1cdf7`

The steps below are a chronological record and are **not** rewritten as things change. Several
describe work later removed — `plan_revision`, evidence item E15, a 149-check suite — which is correct
for a log but misleading if read as today's facts. Today's facts:

| | |
|---|---|
| Live table | `Playground.dbo.Input_To_ML_Full_138_Trimmed` — 114,436 rows, 427 queues, FW202401–202908, **32 columns** |
| `_HISTORY_COLS` | **16** columns. `Projection_plan_name` removed *before* the column was dropped |
| Card version | **2.1.0** — 10 mandatory + 8 additive sections |
| Rendered order | Executive Summary → **Why This Happened** → Root Cause → … |
| Evidence index | **14 items (E1–E14)**. E15 was plan-vintage and is deleted |
| `Projection_plan_name` | treated as non-existent; dropped from the table; absent from every UI surface |
| §8 plan-revision finding | **deleted** — `miss_streak` survives it and drives criticality's persistence lift |
| FC semantic suite | **189 checks** |
| Module diagnostics | 148 checks |
| UI render guard | 18 Decision Cards + a page-wide reference check |
| Live validation | 135/135 over 10 real investigations, recorded at `e0e248d` — **predates** steps 6–10 |

The live capture in `results/live-spec-validation.json` therefore still holds pre-step-6 verdicts. Any
case whose response landed on the near-zero-implied branch would now read `over_response` rather than
`wrong_direction`, and none would carry `plan_revision`.

---

## Step 0 — the shared, engine-agnostic foundation · `b7a6486`

The brief (§22–23) states that the corrected holiday-event normalisation is "already present in the
repository". **On this branch it was not** — it was authored on `test` for the WFM engine. Rather than
rewrite ~1,800 lines of tested arithmetic in FC vocabulary, the measurement modules came across
verbatim: `lag_analysis`, `forecast_response`, `holiday_response`, `holiday_events`,
`data_granularity`. They are pure functions over history rows and know nothing about either engine.

Shared files touched, additively only:

- `common.py` — `week_ordinals()`. `Fiscal_Week` is YYYYWW, so the week before 202701 is 202652, not
  202700; plain subtraction silently loses a pair at every fiscal-year boundary, about three per lag
  over 157 weeks. Year length is read from the data, so a 53-week year needs no special case.
- `data_access.py` — `_HISTORY_COLS` widened by 9 (`Final_upp_units`, `Week_Ending`,
  `Monday`…`Sunday`). **Read by both engines**, so `?mode=wfm` now runs the wider SELECT. Confirmed
  with the user first. Every consumer reads by key, so the WFM engine is behaviourally identical.
- `load_holiday_master.py` — dedupe on name **and** date (was name alone, which discarded the extra
  days of a multi-day holiday); carries `Semantic_Family`.
- `holiday_calendar.py` — added `holiday_span()`. `holiday_context()` is **deliberately unchanged**
  because `spec_engine` already depends on it.

Not brought across: `rca_decision.py`, `investigation_engine.py`, `business_report_generator.py`,
`prompts.py`, the `rca_console.html` WFM panels.

---

## Step 1 — the deterministic evidence layer · `bf3abfe`

New `backend/wfm/fc_evidence.py`: the FC-native adapter plus the genuinely new tests
(`asu_decomposition`, `plan_revision`, `criticality`, `miss_mechanism`, `direction_coherence`,
`evidence_resolution`, `unexplained_observations`, `evidence_index`).

Runs **between steps 6 and 7**, and that position is forced, not chosen — see
`fc-decision-card-engine.md`.

### Two pre-existing bugs fixed

Both fire **only when no LLM provider is configured**, i.e. exactly the §37 fallback that must work.
Transposed halves of one mistake:

| function | returned | callers expect | symptom |
|---|---|---|---|
| `_call_llm` | 3-tuple | 2 | `ValueError: too many values to unpack (expected 2)` |
| `_narrate` | 2-tuple | 3 | `ValueError: not enough values to unpack (expected 3, got 2)` |

`sql_backend.py` wraps engine failures in `HTTPException(500)`, so `?mode=spec` answered **HTTP 500**
instead of returning the complete deterministic RCA. Present at `74f46c5`, untouched by this work,
found by running the engine offline against an empty `llm_cfg`.

### Three defects of my own, found by running it rather than reading it

- `over_response` was excluded from "inadequate" in the forecastability gate. Over-reacting **is** a
  response failure; whether it caused *this* miss is the direction gate's decision, not a boolean's.
  On a real over-forecast the gate then raised `FORECAST_RESPONSE_FAILURE` and correctly rejected it.
- the absent-driver early path set no `reading`, so the card would have rendered a bare `None` under
  a driver name — which reads as a measured null, not as "no data".
- `COMPOUND_MISS` is not itself a candidate mechanism, so the direction verdict came back `None`
  ("not tested") on reports where every contributing mechanism *had* been tested and passed.

---

## Step 2 — the card, the renderer, the prompt · `b0bb5a8`

`card_version` 2.0.0 → **2.1.0**: eight sections added (`11_`…`18_`), the ten mandatory ones
untouched. Six new renderer panels, all **top-level functions** — a helper declared inside the
renderer and called from a panel outside it is the ReferenceError that once replaced an entire report
with an error card. Prompt 2.0.0 → **2.1.0**: still narration only, plus the rules that the ranked
bullets must not be reordered, that `DEMAND_EVENT_LOW_PREDICTABILITY` is not a forecasting failure,
and that criticality and confidence are never blended.

§40 became **checkable**: `decision_card.EXEC_JARGON` is the list, `jargon_in()` the test, and every
bullet carries its own `jargon_found`.

Three cosmetic-but-real defects fixed by reading the *rendered* output: a saturated criticality lift
claiming "lifted one step from Critical"; "The gap is a mixed."; and `over_response` reaching
executive prose with its underscore intact.

---

## Step 3 — the 24-scenario semantic suite · `bf306ff`

`results/test_fc_spec_semantics.py`, **149 checks**. Every §45 scenario has its own block tagged with
its number, so coverage is checkable rather than claimed.

### Two genuine defects in `plan_revision`, caught by a fixture

A flat fixture (actual **equals** forecast every week) reported a 120-week over-forecast streak and
then claimed the plan had been reissued during it:

1. `"under" if a > f else "over"` classifies a week where actual equals forecast as an
   over-forecast — so a perfectly forecast queue had every week counted into a miss run. A week
   inside ±5% is by the engine's own definition not a miss and now **ends** the run. Same tie bug
   applied to the "still missing the same way" count after a revision, where a week that came in on
   plan is a *success* of the revision.
2. `_plan_vintage_timeline` emits the **initial** plan as its first entry (`previous_plan: None`).
   That was counted as a reissue, so every queue looked as though its plan had been revisited —
   inverting the §8 finding that matters most: "never revisited" became "revisited and stayed wrong".

Both are consequential: §8 calls the three plan states a critical FC business question, and both bugs
pushed the answer towards the accusatory one.

### Three assertion bugs in the test, where the ENGINE was right

Documented in the file so nobody later "fixes" working logic to satisfy a bad fixture:

- `S4-1` demanded `available: False` when no country resolves. The engine correctly reports a
  baseline it genuinely has (the whole history is non-holiday) with every phase `testable: false` and
  a reason. The assertion was asking it to discard real data.
- `S6-2` matched the literal `"pre-holiday"` against wording that reads "pre- **or** post-holiday".
- `S20-4` asserted eight cap rows. There are **nine** — gate 3 has two thresholds (3a caps at Medium
  below 50% period coverage, 3b at Low below 25%), reported separately so the reader sees which bit.
  Eight logical gates, nine rows.

---

## Step 4 — live validation

### The first run was contaminated and was discarded

A uvicorn started hours earlier by `run.py` (PID 15980, 13:19) was bound to `0.0.0.0:8000` running
pre-upgrade code. On Windows two sockets can bind the same port and it is **undefined** which one
receives a given connection, so the run's requests split between the old build and the new one: some
cases returned ten card sections and no new keys, others eighteen. Nothing errored. The output looked
like a real result.

Three defences added, because a private port alone would not have caught it:

1. port **8011**, so the user's own running app is never disturbed and never answers;
2. `_assert_port_free()` — refuses to start if anything is listening;
3. a **build guard** — aborts the whole run if a completed response arrives without `criticality`,
   rather than emitting a page of failures that misdescribe the cause.

Also: `TOP 1` per query had put the same queue-week in four different scenario slots, so ten
"scenarios" tested four distinct investigations. Selection now takes the first candidate not already
used.

### The clean run — 135/135 over 10 real investigations · `e0e248d`

Against `dbo.Input_To_ML_Full` (88,816 rows, FW202401–202752), narrated by
`nvidia/nemotron-3-super-120b-a12b` at 53–81s per case.

| scenario | mechanism | conf | criticality | cause |
|---|---|---|---|---|
| under-forecast | `COMPOUND_MISS` | High | Critical | FC-01 |
| over-forecast | `DEMAND_EVENT_LOW_PREDICTABILITY` | Medium | Critical | STA-02 |
| baseline error | `DATA_LIMITATION` | Low | High | DEM-02 |
| holiday week | `CALENDAR_RESPONSE_FAILURE` | Medium | Critical | STA-02 |
| post-holiday (row has **no** holiday) | `FORECAST_RESPONSE_FAILURE` | High | Critical | STA-02 |
| lagged driver available | `FORECAST_BASELINE_FAILURE` | High | Critical | FC-02 |
| sparse driver | `COMPOUND_MISS` | High | High | FC-01 |
| data limitation (short history) | `DATA_LIMITATION` | Low | Critical | DQ-04 |
| persistent plan miss | `COMPOUND_MISS` | Medium | Critical | STA-02 |
| hierarchy context | `COMPOUND_MISS` | High | Critical | FC-01 |

**Six of the seven mechanisms appeared on real data** — the evidence that the classification
discriminates rather than defaulting. Every case: HTTP 200, 15 steps, 18 card sections, and
`jargon=[]` in the ranked bullets *with a live model rewording every one of them*.

### Two more defects, exposed only by live output

1. **The same sentence printed as two bullets.** The `FORECAST_BASELINE_FAILURE` candidate's
   `evidence` *is* `miss_decomposition.reading`, so one finding appeared twice. De-duplicated in
   `why_bullets` on `what_happened`, keeping the higher-ranked occurrence — fixed there rather than
   at either source, because both derivations are legitimate and suppressing one upstream would lose
   the bullet on reports where only that source fires.
2. **`DATA_LIMITATION` misdescribed a case with 156 weeks of history.** FW202703 reached it because
   *every* candidate was rejected on direction, not because anything was missing. The band is right;
   the stock meaning ("critical evidence is missing") was the opposite of the truth. That path now
   carries its own meaning and an `all_candidates_rejected_on_direction` flag. The underlying
   behaviour was already correct — it is §54 working on live data.

### One finding that looked like a bug and is not

`plan_revised_but_remained_wrong` came back on all ten cases, which is exactly the shape of a
false positive after fixing two bugs in that function. Checked against the live table:
`Projection_plan_name` holds **monthly** projections ("FY27 Jun Projection") — 40 distinct names over
208 rows for one queue, about one change per five weeks. A 19-week miss streak genuinely contains four
reissues. The finding is real, and damning: the plan was reissued on schedule and kept missing the
same way.

---

## Step 5 — SA Indonesia FW202716 before/after · `80adc26`

Both sides run against **live SQL with a live model**; "before" came from a git worktree at `74f46c5`,
so it is the actual old code rather than a reconstruction.
`results/indonesia-fw202716-{before,after}.json`, reproducible via
`results/run_indonesia_before_after.py`.

**Unchanged** — and this matters as much as what moved: adherence −138.3%, gap 88.2 contacts, root
cause `DEM-01 Demand Spike`, `cause_type` `DEM-01`, 157 history rows, status Complete.

**Moved:** mechanism none → `COMPOUND_MISS`; criticality none → Moderate (88 contacts is 92% of a
typical week, lifting one step from Low); holiday phase none → `post_holiday` on a week whose row
records `Holiday_Count = 0`, with capture `inconsistent_history` at 51.9% — so the engine explicitly
does **not** blame the holiday; evidence index none → 11/15; ranked bullets 0 → 6; card 10 → 18
sections; recommendations 1 → 3, replacing a generic "review this period manually" with the seasonal
baseline and the leading signal, each tagged with the mechanism it follows.

**Confidence Low (61.9%) → Medium (60.5%)** — the score fell slightly while the level rose, which
needs explaining rather than glossing:

- `ContradictoryEvidence` 0.3226 → 0.4178. Four supporting items instead of one improves the ratio,
  lifting the dimension **above** the 0.40 Gate 5 threshold — so Gate 5 stops binding and the Medium
  calculated level is no longer capped down to Low.
- `EvidenceStrength` 0.8 → 0.7231. Lower, and correctly so: the new items are honestly graded,
  including Moderate and Weak ones, where the single old item was Strong.
- `ModelAgreement` NotApplicable → 0.5; `HistoricalConsistency` NotApplicable → 0.4029.

The level moved because evidence was **found**, never because it was lost.

---

## Step 6 — three fixes from validating one card against live SQL · `0beee15`

All three surfaced from checking UKI Comm Client DSP Standard FW202717 against the database rather
than from reading code.

1. **`wrong_direction` was a misclassification, not bad wording.** The near-zero-implied branch of
   `_adequacy` returned it unconditionally. On that card the implied change was **−2.3** and the plan
   moved **−82.61** — the *same* sign. §14 defines `wrong_direction` as moving *opposite* the expected
   direction, so the label contradicted the spec on its own terms. Worse, it pointed the remedy the
   wrong way: fiscal week 17 is a holiday week every year, so a cut *was* correct and only its size
   was wrong. Now decided by **sign** — same way → `over_response`, opposite → `wrong_direction`,
   implied exactly zero → `over_response` (no direction to be wrong about).

2. **The capture ratio is stated; the threshold was deliberately not moved.** `captured` spans
   0.5×–1.75×, so a bare "captured" hid a 51% over-cut (−40.04% applied against −26.54% implied,
   1.51×). `capture_ratio`, `overshoot_pct`, `within_tolerance` and `tolerance_band` are now
   published. `OVER_CAPTURE` stays **1.75** — versioned configuration no client has confirmed, and
   tightening it would flip existing verdicts on every queue.

3. **New `holiday_response.plan_bias` — and it refused the finding I expected.** I had claimed the
   holiday cut was "systematically too deep" from raw counts. The measurement disagreed: **10 of 17**
   phase-labelled holiday weeks is 59%, against a 70% threshold — barely better than a coin flip and
   **not** a pattern. The gate did its job and declined a finding the data does not support (§54), and
   my earlier statement was overstated.

   What the data *does* support is that the misses are **widening** on every phase (holiday
   16.9%→22.6%, pre 11.4%→20.9%, post 10.7%→29.9% median absolute). So widening is reported
   **independently of direction** — the first design required a consistent direction first and would
   have hidden this entirely. Two findings, two actions: **M8** (standing one-sided bias → fix the
   rule) and **M9** (widening → fix how it is *sized*).

Also `RESPONSE_PROSE`: stripping the underscore still left "judged over response", which is not
English. Each class now has a written sentence.

Two bugs of mine caught by running it: `_phase_of` returns a `(phase, span)` tuple, not a label; and
`SGN-8` asserted `over_response` at a ratio of exactly 1.50, which is the inclusive boundary — the
right answer was `adequate` and my test was wrong.

---

## Step 7 — Decision Card UI: reading order and chip removal · `d009b63`

**"Why This Happened" moved to immediately after the Executive Summary**, before Root Cause. It had
been *after* Root Cause, which put the two most-read blocks either side of a long panel containing the
scope table. Executive Summary and Root Cause were a single template literal and could not be
separated; they are now `summaryCard` and `rootCauseCard`, with `cause` kept as the two joined so no
other reference had to change.

**The `E5  Strong` chips are no longer rendered on the bullets.** "E5" means nothing without the
Evidence Index open, and a bare strength label invites weighing bullets against each other when the
*order* already does that — the ranking is deterministic evidence. `bullets[].evidence_id` and
`bullets[].strength` remain on the response, and the Evidence Index still lists every item, so
nothing became untraceable.

The render guard now checks **order**, not only presence: Why immediately after Summary, Why before
Root Cause, no chips inside the Why block, and E1 still present in the index. Verified it bites —
reverting the concatenation failed all 6 offline cards with the positions named.

---

## Step 8 — `Projection_plan_name` treated as non-existent · `4a37e1a`

At the user's instruction the engine reads as though the column does not exist. That **deletes the
brief's §8 plan-revision finding**, keys included — a deliberate departure from the brief, recorded
here rather than left to be discovered from an absence.

Defensible on the data: the column holds **monthly** projection vintages that change on a calendar
cycle rather than in response to a miss — 40 distinct names over 208 weeks for one queue, about one
every five. That is why `plan_revised_but_remained_wrong` fired on **all ten** live cases and read as
an accusation on every one. Two existing decisions already pointed the same way: `prompts.py` forbids
the WFM model from citing routine plan updates as a cause, and `lag_analysis.NOT_DRIVERS` already
excluded the column from driver testing.

Removed: `plan_revision`, `plan_vintage_timeline`, evidence item **E15**, recommendations **M6/M7**,
the plan bullet, the plan-vintage prompt row, `plan_vintage` in the LLM series,
`plan_vintage_changes` in the evidence bundle, and the *"Plan measured against"* card block. The
evidence index is now **14 items (E1–E14)**, keeping their original numbers so existing citations stay
valid.

**Survived:** `miss_streak` — the one part of `plan_revision` that never touched the column. It
derives from adherence alone and still drives criticality's persistence lift. Also the card's
*Forecast owner* block, since `Forecaster` is a different column answering a different question.

---

## Step 9 — the rest of the console · `a4dc137`

**A scoping error of mine.** Step 8 made the Decision Card clean and I verified that — but I read "the
output" as the card and left the column on every other surface. A user searching the page for "plan"
found them and reasonably concluded the change had not landed.

Removed: the worklist queue card line, the `CUR_CTX` clipboard string, the left-hand **"Projection
Plan"** filter (whose dropdown listed every plan name), the dashboard filter, the field glossary row,
and two probe questions.

Most of the 87 search hits were never the column: rendering the card and counting visible text gives
46 × the ordinary word "plan" (*"88 contacts against plan"*), **13 × "ex-plan-ation"**, 6 × "Planned
for?" and 1 × `planned_asu`. The rest were the page chrome this commit removed.

**Cross-engine consequence:** the queue card, filters, dashboard and glossary are console-wide, shared
with `?mode=wfm` and `?mode=legacy`, so this removes a filter dimension the console has offered since
the earliest sessions — the filter set drops from 10 dimensions to 9. Wider than the original scope,
done because the instruction was to treat the column as non-existent, and reversible.

New **page-wide** guard in `check_ui_render.js`: the per-card checks could never catch a leak elsewhere
on the page, which is exactly how this got through. Verified it bites.

---

## Step 10 — the column dropped from the source table · `5b1cdf7`

```sql
ALTER TABLE dbo.Input_To_ML_Full_138_Trimmed DROP COLUMN Projection_plan_name
```

33 → **32 columns**, all **114,436 rows intact**, 101,532 non-null values across 40 plan names
removed. No index, default constraint, view or procedure referenced it, so the `ALTER` cascaded into
nothing. **No backup table was created because one already exists:** `dbo.Input_To_ML_Full_138`
(138,775 rows) still carries the column and its data, as do `Input_To_ML_Full` and `Input_To_ML`.
Recovery is an `UPDATE` join from `_138` on `Forecast_name + Fiscal_Week`.

**The code change had to land first, and this is the part worth reading.**
`data_access._HISTORY_COLS` named the column in the history `SELECT`. Dropping the column with that
line in place would **not** have failed loudly: the query raises *"Invalid column name"*,
`sql_backend` catches it into `wfm_context = {"fetch_error": …}`, and **both** engines then run on the
posted bundle alone. Every investigation on every queue would have silently lost its entire 157-week
history and reported insufficient data — while still rendering a confident-looking card. The tuple was
trimmed first (**16 columns**), the drop second. Verified after: `fetch_error` none, **141** history
weeks returned, ladder and siblings intact.

**A false statement prevented in WFM.** `temporal_reasoner` reads the column with `.get()`, so it
could not crash — it would simply have reported `forecast_plan_changed_within_window: False` forever.
*"The plan did not change"* and *"we cannot tell"* are different claims and only the second is true
now, so it returns `None` plus an explicit note. A WFM file, outside the Decision Card scope, changed
because dropping the column made the existing answer false.

Verified end to end on the changed table: `?mode=spec` 16 steps, 18 sections, evidence 11/14, 141
weeks, `miss_streak` 5 under; `?mode=wfm` deterministic fallback, primary cause present, 140 weeks,
`forecast_plan_changed_within_window: None`. Neither response contains the column.

---

## Open items

- **Criticality band thresholds** (5000 / 1000 / 200 / 50 contacts) are anchored on the existing
  materiality floor and then an order of magnitude per step. Versioned configuration; a
  client-confirmed table would be better.
- **`Final_upp_units` is sparse on most queues.** Reported as sparse coverage rather than used —
  correct, but it means §21's UPP evidence is rarely available in practice.
- **Weekend attribution is impossible on this source** and stays so until a day-level feed exists.
  The `Monday`…`Sunday` columns are holiday flags. The capability check re-runs every time, so it
  flips by itself if that changes.
- **Two Ascension entries** in the holiday master are flagged `possible_misdating` (05-14 source vs
  05-27 derived, `Requires_Review=YES`). Surfaced, not resolved — no mapping invented.
- **`Business Event Repository` is not deployed**, so that context element is permanently
  `NotApplicable` (BR-202).
- **Cross-engine comparison (§46)** is available but not automated. The two engines can be run on the
  same input and their conclusions compared; nothing forces them to agree.
- The `holiday_master.json` rebuild changes what `holiday_context()` returns for multi-day holidays,
  which `spec_engine` reads. This is the one intended cross-engine effect and it is the point of §23.
