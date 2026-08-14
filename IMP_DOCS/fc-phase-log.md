# FC Decision Card upgrade — phase log (branch `test2`)

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
