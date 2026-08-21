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

---

# FIX 6 - the card said the same thing over and over

Reported from the UI: the holiday name and its sentence appearing "10-12 times... infuriating". A
captured page (`Downloads/1.html`) put real numbers on it, and they were worse than any synthetic
render had shown: **39 name printings** on one card - 14x `Idul Fitri Holiday`, 13x `Ascension of
Jesus Christ`, 12x `Joint Holiday for Waisak Day` - with one sentence printed **7 times**.

None of the 189 FC checks or 18 render checks caught it, and the reason matters: **every panel was
individually correct.** One measured fact is stored in **26 payload locations** and four to six card
sections each legitimately report it, because each is the section that fact belongs to. No per-panel
assertion can see a problem that only exists in the total.

## Two data bugs the capture exposed that a synthetic render never did

```
"Holiday calendar: Ascension of Jesus Christ, Ascension of Jesus Christ, Idul Fitri Holiday, ..."
"...but Ascension Day of Jesus Christ, Ascension of Jesus Christ, Idul Fitri Holiday, ..."
```

**The same name twice in one list.** `calendar_names` carries one entry per dated *occurrence*, so an
event spanning two days appears twice, and joining it raw printed the name twice inside one sentence.
Fixed with `_uniq_names()` - the dated occurrences stay distinct in the data, because a five-day
closure is five days; only the name list used for prose collapses.

**A raw spelling printed beside its own canonical form.** `_holNames` read `h.name`, the raw source
string, so both spellings of one event were listed as two holidays - in the panel whose entire purpose
this week is to show they are the same event. `canonical_name` was already on those rows. The semantic
grouping was being bypassed at the last step, which makes this the more embarrassing of the two.

## Why site-by-site patching failed, and what worked

I patched render sites one at a time first. It moved the worst repeat from 13 printings to 9 and left
**fifteen of eighteen cards still failing**. That approach cannot converge: the fact is stored in 26
places, and any new panel reading the same field reintroduces it.

Two central passes over the assembled card replaced it, both renderer-side only so the response keeps
every field self-contained for anything reading one section over the API:

**`dedupeNameLists`** - the list of names is established once, then referred to. "Holiday calendar: A,
B, C", "Recent holidays potentially affecting this week: A, B, C" and "A, B, C fell shortly before this
week" are three *different* sentences carrying the same list, so sentence-level dedup never touched
them. Later occurrences become "the 3 holidays named above". Only runs of two or more comma-joined
names collapse, which deliberately leaves the holiday reference table alone - its rows carry one name
each and that table is where a reader looks them up.

**`dedupeRenderedProse`** - the first occurrence of a sentence survives in full; later ones become
"(as above)". Only text *between* tags is touched, so attributes and handlers are untouched, and
sentences under 55 characters are always kept because a short label repeating is not the problem and
dropping one can strand a table row.

One bug worth recording in the name pass: `present` was ordered by name **length**, so runs starting
mid-list never matched and `Joint Holiday for Waisak Day` - last in every list - stayed at 10
printings while the other two dropped. Ordering by position in the text fixed it.

## Result on the reported card

| | Captured page | After |
|---|---|---|
| Name printings | **39** (14 / 13 / 12) | **14** (6 / 4 / 4) |
| Worst repeated sentence | **7x** | **1x** |
| Sentences appearing >3x | 14 distinct | **0** |

## The guard that would have caught it

`results/check_ui_render.js` now asserts on the **whole rendered card**, which is the only level the
fault exists at: no holiday name more than 6 times, no sentence over 55 characters more than 3 times,
and never the same name twice consecutively in one list. `RENDER_REPEAT_REPORT=1` prints the actual
counts for a before/after.

The reported queue is committed as `results/live-spec-holiday-repetition-case.json` so this exact case
is re-checked on every run. When first added it **failed**, which is the point of adding it.

---

# The phase table, and a new statistical section

## The phase table already had columns - and the prose as well

Three rows, each repeating one template: *"Weeks [X] have historically run Y% below this queue's
non-holiday level, across N week(s), moving that way in Z% of them. The plan for those weeks moved W%,
so the pattern was [not] reflected in the forecast historically."* Every figure in that sentence was
**already a column**, except the plan's movement - which existed on the phase block as
`forecast_effect_pct` and was simply not projected into the card panel, the same filtering bug that
once shipped a driver block the page never displayed.

So the sixth "Reading" column became a `Plan moved` column, and the shared wording moved to a single
caption under the table, which is the job a table header does.

| Phase | Weeks | Demand vs non-holiday | Consistency | Plan moved | Reflected in plan? |
|---|---|---|---|---|---|
| holiday | 52 | -13.0% | 75% | -13.88% | yes |
| pre-holiday | 17 | +0.45% | 53% | +4.56% | yes |
| post-holiday | 27 | -2.24% | 52% | +4.35% | **no** |

## Section 19 - statistical profile

Asked for the WFM "Statistical Evidence - queue level" quality on the Decision Card. The finding on
opening it up: **the engine already computed all of it and the card threw it away** - 14 metrics,
ranked findings and 4 Pearson correlations over **155 weeks** on the reported queue, against 18 card
sections none of which was statistical. Some readings did reach `5_evidence.supporting`, but only the
ones that *support* the conclusion: cherry-picked, unlabelled and mixed with non-statistical items.

`19_statistical_profile` carries all **14** metrics - the WFM panel's 8 plus `accuracy_long`,
`coefficient_of_variation_recent`, `trend_year`, `drift_year` and `plan_vs_seasonal_norm`, the last of
which is the strongest single item on the reported queue:

> *"The plan was set at 64 contacts for a week that has averaged 122 across 3 earlier years... Demand
> of 152 is in line with the week's own history, so **the plan is the outlier, not the demand**."*

Carried over from WFM: a fixed labelled metric list in a stable order, one plain-English reading each,
explicit not-available handling (stated, not dropped), the ranked findings block, the correlations
sub-list, and a caption saying it is arithmetic with no model.

Added beyond it: a **FED THE CONCLUSION** marker on the metrics that actually fed the ranked result.
WFM has no ranked why-chain to tie back to; the card does, and "this number is context" against "this
number is why" is the difference between a dashboard and an argument. Three of thirteen are marked on
the reported queue.

Deliberately **not** filtered by what the conclusion needs - a measure that argues against the finding,
or says nothing, is shown the same as one that supports it. A profile that only ever corroborates
teaches a reader to distrust it.

`test_fc_spec_semantics` asserted the card carries *exactly* 18 sections, which was the wrong
assertion for its own stated intent ("nothing was lost") since it also forbade adding one. It now
checks all 18 original keys **by name** - strictly stronger, since a rename or a drop still fails -
plus a new check that section 19 is present. **190/190.**

## Verification

| | |
|---|---|
| Module smoke | 12 / 12 |
| FC spec semantics | **190 / 190** |
| WFM diagnostics | 148 / 148 |
| Narrative grounding | 21 / 21 |
| UI render + repetition caps | **19 Decision Cards**, including the reported case |
| prompt2 conformance | 16 / 16 |
| `new_prompt` conformance | 34 / 34 |

---

# FIX 7 - the cure became the symptom, and the card got a shape

## The reported problem

```
Limitations - what could not be assessed
Business Event Repository is not deployed, so this is NotApplicable ... (BR-202).
(as above)
(as above)
(as above)
(as above)
(as above)
```

Five rows saying nothing. The dedup shipped in FIX 6 replaced repeated sentences with a marker, which
is right inside a sentence or a table cell that must stay populated, and wrong as an entire list item.
Measured on the captured page: **21 "(as above)" and 36 "Same as stated above"** markers, five of them
whole bullets. The cure had become the symptom.

`dropMarkerOnlyItems` now removes any list item whose entire content is a marker and replaces the run
with one honest line: *"5 further items repeated points already made above, and are not restated
here."* A guard assertion was added so it cannot come back.

## Two more repetition gaps, both mine

**Single-holiday cards got no dedup at all.** `dedupeNameLists` opened with
`if (known.length < 2) return html` because it was written to collapse comma-joined *runs*. One holiday
has no run, so the function returned immediately -- which is why `Shavuot` still printed **12 times** on
the latest output while the earlier three-holiday card was fixed.

**And I reintroduced it while fixing it.** I replaced the single-name special case with a general
per-name cap, then left the `< 2` early return in place, so `Columbus Day` reached **9 printings** on a
new case. The cap is the part that always applies; run-collapsing is the part that needs two names. The
early return now calls the cap before returning.

| Case | Before | After |
|---|---|---|
| Three-holiday card | 39 printings | **9** |
| `Passover (Day 7)` | 10x | **4x** |
| `Columbus Day` | 9x | **4x** |
| Worst repeated sentence | 7x | **1x** |

## The card now has a shape

Measured on the captured output: **~32,000 characters of visible text, about 11 A4 pages**, top four
sections 56% of it, and the whole page carried **one** `<details>` element, closed. Leads said the
output was too long to act on.

**Tabs, with an accordion behind a live toggle.** Six groups, ordered as asked:

| Tab | Holds |
|---|---|
| Decision | summary, headline, ranked reasons, the cause |
| Calendar | holidays, phases, the weekend question |
| Confidence & Recommendation | how sure, how much it matters, what to do |
| Statistics | standing profile, channel mix, evidence |
| Challenge | interrogation, the 23 hypotheses |
| Reference | index, context, limitations, audit |

Implemented as a post-process over the assembled card, the same shape as the dedup passes: split on the
`inv-card` boundary, bucket by title, emit a strip plus panels. Nothing inside a panel changes, so every
existing render assertion still sees the markup it asserted on. An unmatched section falls through to
Reference rather than vanishing, and a guard asserts the count in equals the count out - silently losing
a panel would be far worse than showing it one tab away from ideal.

The layout choice is the viewer's, remembered per browser, so switching between tabs and accordion is a
click rather than a redeploy.

## The Summary button - a third model call

`POST /api/rca-summarise`, `backend/wfm/summary_prompt.py`.

**Fed deterministic figures only** - headline numbers, the ranked why-bullets as the engine wrote them,
root cause, confidence, criticality, and the statistical measures that actually fed the conclusion.
**Not** the narrative from call 1 or the interrogation prose from call 2. Summarising another model's
prose lets a first-call error return as established fact in the paragraph a lead is most likely to
forward on, with rounded figures rounded again. `results/test_summary_grounding.py` asserts that no
earlier prose reaches the prompt, rather than trusting that it does not.

**On click, cached per queue + week + prompt version.** Groq's cap is 100k tokens per *day* and most
cards are never summarised, so spending a third call on every run would be paid for by the runs that
fail later in the day. Measured: **0.02s** cached against **21s** live.

Same numeric grounding as the narrative, reusing `narrative_prompt._numbers_in` and `_matches_supplied`
directly rather than reimplementing - two grounding rules would drift, and the looser one would ship.
A rejected summary is discarded and reported, never shown with a warning.

Verified end to end against a live model. The output states what is unsettled, unprompted:

> "These patterns were consistent with a forecast-response failure and a demand spike, **though the
> measures did not agree and no single statistical story was settled.**"

## A scoping bug in the summary button

First attempt failed with `API_BASE is not defined`. It is a **function-local** `const` redeclared in
four separate functions, so a fifth calling `fetch()` cannot see it. Fixed with one shared
`rcaApiBase()`; the existing four keep their local copies, because rewriting working call sites to fix a
bug they do not have is risk without benefit.

The summary also now **only invokes when a model is selected**. The investigation endpoint falls back to
a default chain when nothing is picked, which is right for the main run - an investigation must produce
something. A summary is optional, so silently spending a call on a model nobody chose is the wrong
default.

## Section 20 - channel mix rotation

Asked whether channel rotation could be detected for same-name queues across channels. It can, and
`channel_migration_detector` already existed - wired into the WFM engine, not the card, and answering a
**different question**: it compares the target week with the prior week. A drift of fifteen points
spread over three years moves almost nothing between adjacent weeks, so that test cannot see it.

`backend/wfm/channel_mix_rotation.py` is the long-run complement. It needed a second fetch:
`channel_sibling_rows` is filtered to two weeks because that is all the week-over-week detector needs,
so widening it would change what that detector sees. `channel_mix_rows` is a separate key for the same
reason - neither test can quietly start reading the other's rows.

Measured on live data. **Voice is losing share to digital channels across regions:**

| Scope | Rotation | Points | Offset |
|---|---|---|---|
| APJ / CCC / China / Basic | Social Media -> **Email** | 14.5 | 95% |
| Americas / United States / Basic | Voice -> **Social Media** | 12.2 | 65% |
| APJ / IN / India / Pro | Voice -> **Email** | 12.3 | 85% |
| NA Core scope | Voice -> **Email** | 12.4 | 66% |

And it discriminates: China Basic under the `business_org` grouping reports **stable**, largest move 4.9
points, under the 5-point bar. A mix that never changes is not a migration and reporting one would be
noise.

**Co-movement is reported; diversion is not claimed.** A falling channel and a rising channel can both
be driven by something else, so the wording is always "share moved from X to Y" and the offset ratio is
published so a reader can judge how completely the two account for each other. Each channel's own weekly
share deviation is computed so a genuine drift is separable from wobble.

Grouped by `Region + SubRegion + Country + business_org`, reusing the existing convention rather than
inventing a second one, and **not** the CQN key: the signed-off CQN definition includes channel, so
grouping by CQN would put every channel in its own group and guarantee nothing was ever found. Every
result carries `is_cqn_proxy: true`.

## mathematics.md

`mathematics.md` at the repo root: every formula, all **90** numeric constants with their module and
rationale, the full data lineage, and the principles the numbers serve. Generated from
`results/extract_maths.py` rather than written from memory, because an earlier audit in this project
reported thirteen things missing by trusting documentation over the payload.

## Verification

| | |
|---|---|
| Module smoke | 12 / 12 |
| FC spec semantics | 190 / 190 |
| WFM diagnostics | 148 / 148 |
| Narrative grounding | 21 / 21 |
| **Summary grounding** (new) | **14 / 14** |
| UI render, repetition caps, tab integrity | **21 Decision Cards** |
| prompt2 conformance | 16 / 16 |
| `new_prompt` conformance | 34 / 34 |

Three permanent regression cases now live in `results/`: the reported three-holiday card, a
single-holiday card, and a channel-mix card. Each **failed when first added**, which is the point of
adding them.
