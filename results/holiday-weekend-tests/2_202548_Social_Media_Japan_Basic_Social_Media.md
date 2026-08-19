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
| Engine status | Complete |

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
| Weekly calendar structure | `AVAILABLE` |  |
| Holiday × weekend interaction | `AVAILABLE` |  |

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

1. The plan moved in the opposite direction of what was needed: instead of increasing the forecast by about 164 contacts, it cut it by 779 contacts. This contributed to the miss and is one of the mechanisms the evidence supports.
2. Against an expected level of 1,363 contacts, the plan sat 943 contacts low while demand was only 295 low, showing the plan entered the week too far below expectations. This reflects a baseline failure and is one of the mechanisms the evidence supports.
3. A repeatable signal existed before the week but the plan did not respond adequately to it, constituting a forecast‑response failure that the evidence supports.
4. Holidays in the week typically reduce contacts, but the plan's adjustment was based on an inconsistent historical pattern and thus was not reliable. Because the week is a holiday period and the forecast cannot rely on past holiday response, this contributed to the miss.
5. The installed base matched plan, but each unit generated about twice as many contacts as expected, driving the entire miss. This shows the error is in contact rate, not volume, and the plan did not adjust for the higher contact rate.
6. The evidence is mixed, with more challenges supporting the conclusion than raising doubts, which affects confidence in the root cause.

Jargon found: `[]` · causal verbs found: `[]`

Recommendations:

- None
- None
- None

---

*Generated by `results/run_holiday_weekend_tests.py` on branch `test3`. Semantic groups from `dbo.Holiday_Name_Alias`. Narrative written by a model.*