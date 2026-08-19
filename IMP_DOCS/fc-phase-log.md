# FC Decision Card upgrade — phase log (branch `test2`)

> **As of 2026-08-14. This document is a log, not a current-state reference.**
> A PHASE LOG of the FC upgrade, written as each phase completed. Historical by design; the card was version 2.0.0 during the phases it describes and is 2.1.0 now.
>
> For what is true NOW: the live table and port are in `backend/config.json` and `IMP_DOCS/installation-and-connection.md`; current engine behaviour is in `IMP_DOCS/new-prompt-conformance.md`, `prompt2-conformance.md` and `holiday-semantic-groups.md`.

Base: `74f46c5` (an exact copy of `spec-v2-refactor`). **`main`, `spec-v2-refactor` and `test` are
untouched.** `test2` deliberately carries **no** WFM engine changes — those live on `test`.

Scope: `POST /api/rca-investigate?mode=spec` only.

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
