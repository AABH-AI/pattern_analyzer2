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
