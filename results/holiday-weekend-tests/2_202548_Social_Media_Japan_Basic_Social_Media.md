# Social Media Japan Basic — FW202548 — Social Media

*Five holidays spanning the 2024/2025 boundary, all one bank-holiday family. Sunday and Friday flagged, so the closure runs off both ends of the week.*

| | |
|---|---|
| Scope | APJ / JPN / Japan · Basic · Social Media |
| Actual offered | **1,068** |
| Forecast offered | **419.7** |
| Forecast adherence | **-154.5%** (Under-forecast) |
| Absolute variance | 648 contacts |
| `Holiday_Count` on the row | 6 |
| History available | 99 weeks |
| Confidence · Criticality | Medium 65.4% · High |
| Mechanism | COMPOUND_MISS |
| Engine status | Incomplete |

## 1. The holidays, raw and grouped

`Holiday_Master` rows for Japan FW202548 — **5 raw name(s)**:

| Raw name | Date | Weekday | Type | Semantic group | Review |
|---|---|---|---|---|---|
| Year-End Holiday | 2024-12-29 | Sunday | Public Holiday | `JP_YEAREND` |  |
| December 31 Bank Holiday | 2024-12-31 | Tuesday | Public Holiday | `JP_YEAREND` |  |
| new year's day | 2025-01-01 | Wednesday | Public Holiday | `CAL_NEWYEAR_GREGORIAN` |  |
| January 2 Bank Holiday | 2025-01-02 | Thursday | Public Holiday | `JP_YEAREND` |  |
| January 3 Bank Holiday | 2025-01-03 | Friday | Public Holiday | `JP_YEAREND` |  |

**What the card displays** (prompt2 clauses E and F):

> Holidays in this week: New Year's Day, Year-End / New Year bank holidays (Japan).
>
> Recent holidays potentially affecting this week: none.

| | Raw names reaching the week | Canonical names displayed |
|---|---|---|
| Count | 5 | 2 |
| Names | December 31 Bank Holiday, January 2 Bank Holiday, January 3 Bank Holiday, Year-End Holiday, new year's day | New Year's Day, Year-End / New Year bank holidays (Japan) |

**In this fiscal week** — 2 group(s):

| Display name | Occurrences | Dates | Weekdays | Raw spellings |
|---|---|---|---|---|
| New Year's Day | 1 | 2025-01-01 | Wednesday | new year's day |
| Year-End / New Year bank holidays (Japan) | 2 | 2024-12-29, 2024-12-30, 2024-12-31, 2025-01-02, 2025-01-03 | Sunday, Monday, Tuesday, Thursday, Friday | December 31 Bank Holiday / Year-End Holiday / January 2 Bank Holiday / January 3 Bank Holiday |

## 2. Weekend and weekday structure

Clause C — three separate questions, not one refusal:

| Question | State | Why |
|---|---|---|
| Daily weekend demand effect | `NOT_TESTABLE` | Weekend impact cannot be isolated from fiscal-week totals because day-level actual and forecast data is unavailable in the source. |
| Weekly calendar structure | `AVAILABLE` | 6 of 7 weekdays have enough history to compare, and weekly outcomes differ by 24.1 points between the strongest and weakest of the |
| Holiday × weekend interaction | `AVAILABLE` | 3 day-pattern group(s) measurable; adjoining-weekend -18.8 versus midweek 3.7, a -22.5-point difference, which IS material against |

Clause K — weekly outcome by the weekday a holiday fell on. Reference: **73** weeks with no holiday day flagged, median **1,316** contacts.

| Holiday fell on | Weeks | Median actual | vs no-holiday week |
|---|---|---|---|
| Monday | 10 | 1,066 | **-19.0%** |
| Tuesday | 3 | — | not measurable — only 3 week(s) with a holiday on Tuesday; 4 needed |
| Wednesday | 4 | 902 | **-31.5%** |
| Thursday | 4 | 1,219 | **-7.4%** |
| Friday | 7 | 1,068 | **-18.8%** |
| Saturday | 6 | 1,164 | **-11.6%** |
| Sunday | 7 | 947 | **-28.0%** |

Spread across weekdays: **24.1 points**.

Long-weekend grouping — this week's pattern is **holiday_adjoining_weekend** (long weekend):

| Holiday day pattern | Weeks | Median actual | vs no-holiday week |
|---|---|---|---|
| holiday adjoining weekend | 15 | 1,068 | **-18.8%** |
| holiday on weekend | 8 | 1,108 | **-15.8%** |
| midweek holiday | 4 | 1,365 | **+3.7%** |

> Holiday weeks that adjoin the weekend run -18.8% against this queue's no-holiday level, versus 3.7% for a midweek holiday -- a difference of 22.5 points. On this queue's own history the long-weekend structure does make a material difference to the week's total.

## 3. Calendar phase and rebound

| | |
|---|---|
| Resolved phase | `holiday` |
| Window checked | ±2 weeks |
| Zero-count but adjacent | False |
| Phase effect vs own baseline | -11.8% across 26 instances |
| Rebound repeatability | **EMERGING / INCONSISTENT** (19 instances) |

> Across 19 past instances this queue's post-holiday rebound has run upward 5.74% at the median (-25.15% to 61.24%), moving the same way 63.16% of the time. The pattern recurs but is not reliable: it should inform a forecaster's judgement and should not be applied as a fixed adjustment.

## 4. What the engine concluded

**Root cause:** Drift

The forecast error is drifting, not just noisy: adherence has moved about -4.40 points per week, roughly -57 points across 13 weeks, steadily further into under-forecast. The baseline is decaying and will keep missing in this direction until it is rebuilt.

Ranked reasons:

1. The plan moved the wrong way. The expected level implied moving the forecast 163.98 contacts, but it moved -779.36 -- the opposite way. This is one of the mechanisms the evidence supports: More than one supported mechanism contributed materially. Direction checks out: the miss pushed demand up and this mechanism implies up.
2. Against an expected 1363.0 contacts (median demand over the last 13 weeks (fewer than 2 prior years available for fiscal week 48)), the plan sat 943.34 contacts below expectation and demand landed 295.0 contacts below it. This is one of the mechanisms the evidence supports: More than one supported mechanism contributed materially. Direction checks out: the miss pushed demand up and this mechanism implies up.
3. A forecast-response failure IS supported: a repeatable signal was available before the week and the plan did not respond adequately to it. All four conditions for calling this a forecast-response failure hold.
4. New Year's Day, Year-End / New Year bank holidays (Japan) falls in this week. Weeks containing a holiday have historically run 11.85% below this queue's non-holiday level, across 26 week(s), moving that way in 57.7% of them -- not consistent enough to rely on. The plan for those weeks moved -11.88%, so the pattern was reflected in the forecast historically. Forecast capture: inconsistent history -- This queue's response to holiday weeks has not been consistent (57.7% moved the same way), so the forecast cannot be held to it. The week sits in the holiday phase. This queue's response to holiday weeks has not been consistent (57.7% moved the same way), so the forecast cannot be held to it.
5. The population was close to plan, but contacts per unit differed: 0.0012 actual against 0.0006 planned. The two effects sum to the whole +648-contact gap (+87 from population, +561 from contact rate), so nothing is left unexplained by the split. The gap is driven by contacts per unit differing from plan, not by the population.
6. 5 item(s) support the conclusion and 7 argue against it. Governed by cross-examination, which ran before confidence precisely so its result could feed in. 12 challenge(s) found nothing wrong, 5 raised a doubt and 0 contradicted it outright.

Jargon found: `[]` · causal verbs found: `[]`

Recommendations:

- None
- None
- None

---

*Generated by `results/run_holiday_weekend_tests.py` on branch `test3`. Semantic groups from `dbo.Holiday_Name_Alias`. Deterministic evidence only — no model was called.*