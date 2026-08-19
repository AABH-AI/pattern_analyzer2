# Holiday semantic grouping, and the multi-holiday / long-weekend tests

Built **2026-08-19** on branch `test3`. Two things: a curated semantic-group mapping in SQL so one
holiday written several ways is displayed once, and three real test cases that actually exercise the
calendar work.

---

## Why a curated table and not a similarity score

`Ascension Day of Jesus Christ` and `Ascension of Jesus Christ` share tokens, so the derived key
already merged those. What no string rule reaches is `Qing Ming Festival` / `Qing Ming Jie`,
`Showa Day` / `Shōwa Day`, or `Diwali` / `Deepavali`.

Measured over this master: after a same-country same-date pre-filter, **276 name pairs** remain and a
rule decides **23%**. The other 77% need knowledge that is not in the characters.

**But roughly half of those are the inverse problem** — different holidays that merely share a date:

| | | |
|---|---|---|
| `Mid-Autumn Festival` | `National Day` | china, 2023-10-01 |
| `Christmas Day` | `Quaid-e-Azam Day` | pakistan, 12-25 |
| `Annunciation of the Virgin Mary` | `Greek Independence Day` | greece, 03-25 |
| `Qing Ming Festival` | `childrens day` | taiwan, 04-04 |

and one pair of near-identical **names** that are different holidays:

| | |
|---|---|
| `new year's day` | Gregorian, 01-01 |
| `New Year` | **lunar** — late Jan / Feb in china |

A similarity threshold merges every row in both tables above. That is why this is a curated mapping
with a rationale per row, and why the bias is stated once and applied throughout:
**when unsure, do not merge.** Failing to merge inflates an event count; wrongly merging invents a
finding, silently.

---

## The tables

`backend/build_holiday_semantic_groups.py` creates three tables in **Playground**:

| Table | Holds |
|---|---|
| `dbo.Holiday_Semantic_Group` | one row per event family — `group_id`, `display_name`, `rationale` |
| `dbo.Holiday_Name_Alias` | raw name → group, with `country_scope` and how many master rows it matches |
| `dbo.Holiday_Name_Pair_Review` | `DO_NOT_MERGE` decisions with reasons, plus everything still `UNRESOLVED` |

**23 groups covering 3,142 master rows.** `semantic_family` in the runtime JSON went from **99 rows**
(two values: `Diwali`, `Lunar New Year`) to **2,464 rows** across 23 groups. Those two pre-existing
values are absorbed rather than left alongside the new ids — the engine groups on that string, so
leaving both would have split one family into two.

```
python backend/build_holiday_semantic_groups.py            # tables + report
python backend/build_holiday_semantic_groups.py --stamp    # also stamp holiday_master.json
```

The engine needed **no logic change** for the merge itself: `event_key()` already preferred
`semantic_family` over its derived key. Only the display name had to be carried through (below).

### `country_scope` is load-bearing

`Labour Day` appears in **five different months** across countries. Bare `Labor Day` is therefore
deliberately *not* globally mapped — in canada and the USA it is September. Scoped rows resolve the
local cases without touching the others:

```
Labor Day / Labour Day   china             -> CN_LABOR              (1 May + Golden Week extension)
Labor Day / Labour Day   nordics, ecis     -> CAL_LABOURDAY_MAY     (1 May)
Labor Day                canada, USA       -> unmapped, keeps its own identity (September)
```

---

## Three defects found while building this — two of them mine

**1. A wrong merge I made, of exactly the kind this table exists to prevent.** `Prophet's Ascension`
was put in `CAL_ASCENSION`, the *Christian* Ascension of Jesus Christ. It is not that event — it is
Isra and Mi'raj, the Islamic night journey, which falls in Rajab. Both names contain "Ascension",
which is precisely why a similarity score would have made the same mistake. Moved to `CAL_ISRA`.
Found by reading the review table rather than trusting the mapping.

**2. Country-scoped mappings silently missed.** The runtime JSON keys holidays as
`"country|fiscal_week"`, and the stamper was passing that whole composite string to the
country-scoped lookup. Every `CN_`/`JP_`/`IN_` mapping missed and only the cross-country families
applied — 12 groups instead of 23. Caught by counting the distinct groups afterwards instead of
assuming.

**3. A family displayed as one of its member days.** `canonical_name` was `names[0]`, the
alphabetically first raw spelling. Right for a family of spelling variants; wrong for one whose
members are different words — Japan's year-end closure came out labelled **"December 31 Bank
Holiday"** for a span running 2024-12-29 to 2025-01-03. Group display names now travel from
`dbo.Holiday_Semantic_Group` into the JSON as `semantic_groups`, and `canonical_name` prefers them.

That last fix needed a second attempt: `event_key()` normalises the family into `family:jp yearend`
— prefix, lower case, underscores as spaces — so a raw comparison against `JP_YEAREND` never matched
and the first version changed nothing at all. Both sides are now normalised.

---

## The three test cases

Selected by SQL against four conditions at once, because every earlier test used a queue with
`Holiday_Count = 0` and adherence measured on ~150 contacts, which exercises none of this:

- more than 2 holidays in the week
- a long-weekend day flag
- **both** `Actual_Offered` and `fcst_offered` at least 200 — not just one
- a material miss, `|adherence| > 15%`

**529 rows in the table meet all four.** Reports in `results/holiday-weekend-tests/`, regenerate with
`python results/run_holiday_weekend_tests.py` (no model tokens).

| # | Queue | Week | Actual / Forecast | Adherence | Holidays | Tests |
|---|---|---|---|---|---|---|
| 1 | Social Media China Basic | FW202435 | **10,919 / 14,847.8** | +26.5% | 7, all days | the **do-not-merge** case |
| 2 | Social Media Japan Basic | FW202548 | 1,068 / 419.7 | −154.5% | 6, Sun + Fri | a family that **should** merge, across a year boundary |
| 3 | Social Media China Basic | FW202536 | **14,802 / 18,924.9** | +21.8% | 3, Mon + Sat + Sun | a **genuine long weekend** |

### Test 1 — the case where merging would do damage

```
Mid-Autumn Festival holiday        2023-10-01  Sunday   CN_MIDAUTUMN
National Day                       2023-10-01  Sunday   CN_NATIONALDAY
National Day Golden Week holiday   2023-10-02  Monday   CN_NATIONALDAY
```

Same date, **different groups**. Each merged with its own extension day instead:

> Holidays in this week: **Mid-Autumn Festival, National Day (China).**

Four raw names reaching the week → **2** displayed. A date-based merge would have produced one.

### Test 2 — the family that should merge

Five raw names → **2** displayed. `Year-End Holiday` + `December 31` + `January 2` + `January 3 Bank
Holiday` all group to `JP_YEAREND`, while `new year's day` correctly stays separate as
`CAL_NEWYEAR_GREGORIAN`:

> Holidays in this week: **New Year's Day, Year-End / New Year bank holidays (Japan).**

The dated occurrences stay distinct inside the group, so a five-day closure is still five days.

### Test 3 — the long weekend, and the number that matters

Pattern `holiday_adjoining_weekend`, flagged as a long weekend. On this queue's own history:

| Holiday day pattern | Weeks | Median actual | vs no-holiday week |
|---|---|---|---|
| adjoining the weekend | 12 | 18,047 | **−40.6%** |
| on the weekend | 4 | 22,874 | **−24.8%** |
| midweek | 1 | — | not measurable, 4 needed |

**A holiday adjoining the weekend costs this queue nearly 16 points more than one falling on it** —
which is the point of the distinction. A weekend holiday lands on days already non-working.

### An honest limitation in test 1

Test 1 reports **0 of 7 weekdays measurable**. FW202435 is early in the series, so only 34 weeks of
history precede it and each weekday group has 3 instances against a floor of 4. The engine says so
per weekday rather than reporting a figure it cannot support. Tests 2 and 3 have 6 and 7 weekdays
measurable, so the suite covers it between them — but it is worth knowing that an early-2024 target
week cannot exercise the weekday analysis.

---

## The SQL to verify it yourself

`results/find_holiday_weekend_test_weeks.sql` — **read-only**, nine batches, all verified against the
live server. Paste into SSMS and run.

1. Is the candidate pool big enough — 114,436 rows → 1,905 with 3+ holidays → 544 also at volume →
   **529** also with a long-weekend flag
2. The candidates, all four conditions, richest first
3. Genuine long weekends only — Fri/Mon flagged with **midweek clear**, so a contrast group exists
4. History depth for a queue, since each weekday group needs 4+ instances
5. The master joined to the group tables, showing which names collapse and which stay apart
6. Where the grouping actually reduces anything — **2,041 country-weeks** have multiple names, and
   the top cases collapse 3
7. What is still undecided

---

## Still open

**185 pairs remain `UNRESOLVED`** — down from 191 after the scoped Labour Day rows. These need a
business answer, not more code:

| | | | |
|---|---|---|---|
| `Restoration of the Czech Independence Day` | `new year's day` | czech republic | 14 slots |
| `Armed Forces Day` | `October Liberation Day` | ecis | 12 |
| `Arafat Day` | `Eid al-Adha Eve` | ecis | 10 |
| `Father's Day` | `Second Day of Christmas` | bulgaria | 6 |
| `International Women's Day` | `Revolution Day` | ecis_1 | 6 |

Each is the same question: **one event or two?** Some are plainly two (Father's Day is not Christmas).
Others are genuinely arguable — `Arafat Day` and `Eid al-Adha Eve` coincide, and whether a vigil day
and a festival eve are one event is a judgement, which is why it is recorded rather than assumed.

Also unresolved: the master **double-dates Ascension for indonesia** (05-14 and 05-27, both
`needs_review`). Grouping names the family; it does not fix the dating. That belongs upstream in
`Holiday_Master`.

---

## The `Root-Cause Investigation` caption

Asked whether it was necessary. It was not, and it has been trimmed to one sentence with the original
preserved verbatim in an HTML comment beside it.

Three reasons: it never changed, so a reader learned nothing about the queue in front of them; it sits
**above** `#investigationPanel`, which is where results render, so it did not go away once the
investigation completed and generic method prose permanently occupied the space above the actual
findings; and every specific claim it made now appears in the card **with figures** — "competing
hypotheses are weighed, those the data does not support are rejected and recorded with the reason" is
section 6, listing all 23 hypotheses with their states and reasons, and each panel carries its own
`how_to_read`.

One line is kept, because the run takes 30–60 seconds and the reader should know something is about
to happen.

---

## Verification

| | |
|---|---|
| Module smoke | 12 / 12 |
| FC spec semantics | 189 / 189 |
| WFM diagnostics | 148 / 148 |
| UI render, Decision Cards | 18 |
| prompt2 render guard | 28 / 28 |
| `new_prompt` conformance | 34 / 34 PRESENT |
| `prompt2` conformance | 16 / 16 OK |
| `find_holiday_weekend_test_weeks.sql` | 9 / 9 batches, 0 failures |

All exit 0. Running on **http://localhost:9000/rca_console.html**.

---

# Four defects the FW202435 card exposed, and their fixes

The test cases above were built to exercise the calendar work. Reading the card they produced found
four problems that no suite had caught — and the reason is worth stating: all 189 FC checks pass on a
card that contradicts itself, because they check that the machinery ran, not that the conclusion holds
together.

Verified against SQL first, independently of the engine. `results/verify` figures quoted below come
from recomputing them from `dbo.Input_To_ML_Full_138_Trimmed`, not from the report.

## What was already right

| Claim | Independent check |
|---|---|
| Adherence +26.5%, variance 3,929 | +26.46%, 3,929 ✓ |
| ASU split +1,366 / −5,294 | sums to −3,929, **reconciles exactly** ✓ |
| Outlier verdict | modified z = **−5.88**, far beyond the 3.5 bar ✓ |
| Holiday merge, 4 raw → 2 displayed | ✓ |
| The three "typical" levels | each correct for its own window: 33,790 (13wk), 33,330 (35wk), 33,666 (no-holiday) |

---

## FIX 1 — the card asserted and denied the same mechanism

`backend/wfm/decision_card.py`

Bullet 4 said *"A forecast-response failure **IS** supported… all four conditions hold."* Bullet 8 said
*"FORECAST_RESPONSE_FAILURE… **cannot be the cause**."* Four bullets apart, on one card.

Both were true of **different gates** — forecastability asks whether the plan *could* have reacted,
direction-coherence asks whether the mechanism pushes demand the way the miss went. Neither gate was
wrong; the card just never said they had disagreed, so it read as self-contradiction and a reviewer is
right to distrust it.

The forecastability bullet now carries the override and the precedence in the same sentence:

> "All four conditions for calling this a forecast-response failure hold — the plan COULD have
> reacted. It is still not the cause here: the direction-coherence gate, which runs afterwards,
> rejected it because the mechanism implies demand moving the opposite way to this miss. **Being able
> to react and being the explanation are two different tests**, and this evidence passes the first and
> fails the second."

`overridden_by_direction_gate` is published on the bullet so a consumer can detect it without parsing
prose. Neither gate was weakened.

## FIX 2 — "the plan did not carry that adjustment" was false

`backend/wfm/recursive_why.py`, `backend/wfm/spec_engine.py`

The why-chain asserted the plan had not adjusted for the holiday. SQL says the plan was cut from
**27,454.82 to 14,847.77 — 45.9% week on week**. The same card also said it *"over reacted"*. The
over-reaction was right; "did not carry that adjustment" is the opposite of the truth, and it is the
more damaging sentence, because it points a reader at *add a holiday adjustment* when the finding is
that an existing one was too deep.

`_ex_holiday` never looked at the plan — and could not have, because `_holiday_effect_for` measured
**actuals only**. It now measures the plan on the same weeks (`forecast_difference_pct`), and the
explainer states which of four things happened: adjustment absent, roughly right, overdone, or not
measurable. Only the first keeps the original wording, and each leads to a different terminal.

On FW202435 the chain now ends:

> L3 "…holiday weeks run 29% below normal for this queue (24,091 against 34,113). **The plan carried a
> broadly matching adjustment (−30% against the −29% implied), so the calendar was not overlooked.**"
>
> L4 "Because the plan already reflects [the holidays] at roughly the right size, **the calendar is not
> what went wrong this week and the explanation lies elsewhere.**"

That is a materially better answer: it sends the reader on instead of blaming the calendar.

## FIX 3 — two holiday effects, neither labelled

`backend/wfm/spec_engine.py`, `backend/wfm/holiday_response.py`

The card printed **11.93%** in one place and **29%** in another for "the holiday effect". Both are
real, over different populations with different statistics:

| Source | Population | Statistic | FW202435 |
|---|---|---|---|
| `_holiday_effect_for` | every week with `Holiday_Count > 0` | **mean** | −19.7% / −29% |
| `holiday_response.phase_effect` | weeks the **calendar** marks as the holiday phase | **median** | −11.93% |

Reproduced both from SQL. Each block now publishes `basis`, `measure` and `differs_from`, so a reader
can see *why* they differ rather than concluding the engine cannot count. Neither figure changed —
only the labelling.

This also explains a second apparent contradiction that is really two findings: on **all** holiday
weeks the plan's adjustment is well sized (−30% vs −29%), while **this** week it cut far deeper than
the phase norm (−59.79% vs −11.93% implied). Both useful, and now distinguishable.

## FIX 4 — a rounding killed the whole narrative

`backend/wfm/narrative_prompt.py`

This is why the card said **Investigation Incomplete**. Not a provider failure:

> *"the language model call did not succeed: contains number(s) absent from the inputs: **3900.0**"*

The variance is 3,929 and the model wrote 3,900 — rounded to the nearest hundred. The validator's
docstring is explicit that this is a hard failure *"because it is the one error that would make the
report lie"*, which is the right instinct. But rounding a figure for a report is not inventing one, and
the cost was the entire summary discarded and a card announcing failure when the analysis was complete.

A tolerance already existed — 0.5% with a floor of 1 — and was **too tight**: 3,929 → 3,900 is 0.74%.
The docstring claimed it accepted "rounding to the nearest hundred", which is untrue at this magnitude.

The flaw is expressing "rounded to a round number" as a **percentage**, because the error from
rounding to the nearest hundred is a different fraction at every magnitude — 1.3% at 3,929, 5% near
1,000, 0.5% near 10,000. No single percentage covers it without becoming wide enough to admit
inventions.

`_rounds_to()` asks the question directly: *does the supplied figure round to the written one at some
sensible precision?* Two further conditions keep it honest, both added because the test found them:

- **a 5% drift cap** (`ROUNDING_MAX_DRIFT`). `round(33790, -4)` is 30,000 — arithmetically a rounding
  and 11% wrong. Nobody writing a report means 33,790 when they say 30,000.
- **no floor of 1 below 1.** The pre-existing floor meant any supplied value under 1 accepted anything
  within 1.0 of it — a contact rate of 0.0018 was letting the model write "0".

`results/test_narrative_grounding.py`, **21/21**: every legitimate rounding accepted (3,929 → 3,900,
3,930, 4,000; 14,847.77 → 14,848, 14,800, 15,000; 26.5 → 27) and every invention still refused (9,999,
3,500, 12,500, 2,000, 5,000, 13,000, 30,000, 0). **The invention half is the real test** — loosening a
guard is only safe if what it guards against still fails.

End to end with a live model, all three cases now report **`status=Complete`** with a narrative, and
test 1's opening line is the sentence that used to fail:

> "The forecast over-estimated demand by about 26.5% (**roughly 3,900 contacts**) for Social Media
> China Basic in FW35."

---

## Verification after the four fixes

| | |
|---|---|
| Module smoke | 12 / 12 |
| FC spec semantics | 189 / 189 |
| WFM diagnostics | 148 / 148 |
| **Narrative grounding** (new) | **21 / 21** |
| UI render, Decision Cards | 18 |
| Three test cases with `--narrate` | 3 / 3 `status=Complete` |

## Still open from this review

Two cosmetic items were left, deliberately, as they change no conclusion:

1. **Unformatted floats reach executive prose** — `33790.0`, `18942.23`, `0.0012 against 0.0018`.
   Section 40 bans jargon, not raw formatting, so the jargon check passes them.
2. **The header says "Why Forecast missed: Compound miss" while Root Cause says "Outlier"** — two
   answers to one question. Both are correct in their own terms (the mechanism is compound, the
   promoted catalogue hypothesis is Outlier), but a reader has to work that out unaided.

---

# FIX 5 — the weekend table looked empty, and one row was lying

`backend/wfm/fc_evidence.py`

Reported from the UI: the clause-C weekend table showed one row with text and the rest blank.
Reproduced on all four test queues, so not a one-off. Two separate bugs, both mine.

## Bug 1 — the Why column was blank for anything that WORKED

`reason` was only ever populated on **failure**. A row that succeeded had nothing to say, so the only
row carrying text was the one that could not be measured:

```
Daily weekend demand effect     NOT TESTABLE   Weekend impact cannot be isolated from ...
Weekly calendar structure       AVAILABLE      (blank)
Holiday x weekend interaction   AVAILABLE      (blank)
```

That is the exact impression clause C exists to remove — *"do not stop the calendar investigation
with 'weekend impact cannot be isolated'"*. Adding the two extra states and then leaving them blank
reproduced the original failure in a new shape: the reader still learns only what the engine cannot do.

Every row now states what was **found**:

> Weekly calendar structure · `AVAILABLE` · "7 of 7 weekdays have enough history to compare, and
> weekly outcomes differ by 46.8 points between the strongest and weakest of them."
>
> Holiday × weekend interaction · `AVAILABLE` · "4 day-pattern group(s) measurable; adjoining-weekend
> −15.3 versus midweek −24.8, a 9.5-point difference, which is not material against the 10-point bar."

## Bug 2 — AVAILABLE was claimed with nothing measurable

On China FW202435, `weekly_calendar_structure` reported **`AVAILABLE`** while **0 of 7** weekdays
cleared the 4-instance floor. `p2_state` was taken straight from `testable`, which says only that the
*attempt* was possible — not that anything survived it.

This is the same class of error as the driver gate asserting absence from a weak coefficient, and it is
worse than a blank cell: a blank cell tells you nothing, a false `AVAILABLE` tells you something
untrue. The state is now derived from what actually cleared:

| Measurable weekdays | State |
|---|---|
| 0 | `NOT_TESTABLE` |
| 1–4 | `PARTIALLY_AVAILABLE` |
| 5–7 | `AVAILABLE` |

The interaction row is graded the same way — `AVAILABLE` only when the long-weekend contrast is
actually computable, `PARTIALLY_AVAILABLE` when the day patterns exist but the two groups cannot yet
be compared.

## The states now discriminate, which is the point

| Queue | Weekly calendar structure | Holiday × weekend |
|---|---|---|
| SA Indonesia FW202716 | `AVAILABLE` — 7/7, 46.8 pts | `AVAILABLE` — 4 groups, 9.5 pts, not material |
| China Basic FW202435 | **`NOT_TESTABLE`** — was falsely AVAILABLE | `PARTIALLY_AVAILABLE` — 1 group only |
| China Basic FW202536 | `AVAILABLE` — 7/7, 7.0 pts | `PARTIALLY_AVAILABLE` — 2 groups |
| Canada Core French FW202722 | `PARTIALLY_AVAILABLE` — 3/7, 35.6 pts | `AVAILABLE` — 2 groups, contrast computed |

Four queues, four different combinations. Before this, three of the four reported `AVAILABLE /
AVAILABLE` with two blank cells regardless of what the data supported.

Verified through the renderer, not just the response — the same mistake as the earlier round would
otherwise repeat. Suites after the fix: smoke 12/12, FC semantics 189/189, WFM diagnostics 148/148,
narrative grounding 21/21, UI render 18 Decision Cards, prompt2 render 28/28, prompt2 conformance
16/16.
