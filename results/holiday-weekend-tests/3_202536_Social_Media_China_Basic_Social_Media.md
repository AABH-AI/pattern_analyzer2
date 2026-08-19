# Social Media China Basic — FW202536 — Social Media

*Three holidays on Monday, Saturday and Sunday -- a genuine long weekend rather than a full shutdown, which is what the long-weekend contrast is for.*

| | |
|---|---|
| Scope | APJ / CCC / China · Basic · Social Media |
| Actual offered | **14,802** |
| Forecast offered | **18,924.9** |
| Forecast adherence | **+21.8%** (Over-forecast) |
| Absolute variance | 4,123 contacts |
| `Holiday_Count` on the row | 3 |
| History available | 87 weeks |
| Confidence · Criticality | Medium 62.9% · High |
| Mechanism | DEMAND_EVENT_LOW_PREDICTABILITY |
| Engine status | Complete |

## 1. The holidays, raw and grouped

`Holiday_Master` rows for China FW202536 — **1 raw name(s)**:

| Raw name | Date | Weekday | Type | Semantic group | Review |
|---|---|---|---|---|---|
| National Day Golden Week holiday | 2024-10-05 | Saturday | Public Holiday | `CN_NATIONALDAY` |  |

**What the card displays** (prompt2 clauses E and F):

> Holidays in this week: National Day (China).
>
> Recent holidays potentially affecting this week: none.

| | Raw names reaching the week | Canonical names displayed |
|---|---|---|
| Count | 2 | 1 |
| Names | National Day, National Day Golden Week holiday | National Day (China) |

**In this fiscal week** — 1 group(s):

| Display name | Occurrences | Dates | Weekdays | Raw spellings |
|---|---|---|---|---|
| National Day (China) | 1 | 2024-10-01, 2024-10-02, 2024-10-03, 2024-10-04, 2024-10-05, 2024-10-06, 2024-10-07 | Tuesday, Wednesday, Thursday, Friday, Saturday, Sunday, Monday | National Day / National Day Golden Week holiday |

## 2. Weekend and weekday structure

Clause C — three separate questions, not one refusal:

| Question | State | Why |
|---|---|---|
| Daily weekend demand effect | `NOT_TESTABLE` | Weekend impact cannot be isolated from fiscal-week totals because day-level actual and forecast data is unavailable in the source. |
| Weekly calendar structure | `AVAILABLE` |  |
| Holiday × weekend interaction | `AVAILABLE` | both an adjoining-weekend group and a midweek group need 4 or more weeks before the two can be compared |

Clause K — weekly outcome by the weekday a holiday fell on. Reference: **71** weeks with no holiday day flagged, median **30,404** contacts.

| Holiday fell on | Weeks | Median actual | vs no-holiday week |
|---|---|---|---|
| Monday | 8 | 16,979 | **-44.2%** |
| Tuesday | 6 | 15,316 | **-49.6%** |
| Wednesday | 6 | 15,316 | **-49.6%** |
| Thursday | 6 | 16,384 | **-46.1%** |
| Friday | 6 | 16,384 | **-46.1%** |
| Saturday | 8 | 17,448 | **-42.6%** |
| Sunday | 6 | 15,818 | **-48.0%** |

Spread across weekdays: **7.0 points**.

Long-weekend grouping — this week's pattern is **holiday_adjoining_weekend** (long weekend):

| Holiday day pattern | Weeks | Median actual | vs no-holiday week |
|---|---|---|---|
| holiday adjoining weekend | 12 | 18,047 | **-40.6%** |
| holiday on weekend | 4 | 22,874 | **-24.8%** |
| midweek holiday | 1 | — | only 1 week(s) of this pattern; 4 are needed |

## 3. Calendar phase and rebound

| | |
|---|---|
| Resolved phase | `holiday` |
| Window checked | ±2 weeks |
| Zero-count but adjacent | False |
| Phase effect vs own baseline | -34.9% across 16 instances |
| Rebound repeatability | **MODERATELY REPEATABLE** (10 instances) |

> Across 10 past instances this queue's post-holiday rebound has run upward 14.86% at the median (-0.08% to 87.77%), moving the same way 90.0% of the time. The direction is a usable forecasting signal; the size is not -- the range is 87.85 points wide, so this should be treated as a directional signal rather than a fixed uplift.

## 4. What the engine concluded

**Root cause:** Drift

The forecast error is drifting, not just noisy: adherence has moved about -1.35 points per week, roughly -18 points across 13 weeks, steadily further into under-forecast. The baseline is decaying and will keep missing in this direction until it is rebuilt.

Ranked reasons:

1. A leading signal existed before the week and has behaved repeatably for this queue, making the movement foreseeable. The evidence points to a material demand shift that lacked a reliable predictive signal, and the direction of the miss (down) matches what that mechanism implies.
2. Compared to the expected demand of 21,105 contacts (based on the last 13 weeks), the plan was 2,180 contacts low and actual demand was 6,303 contacts low. About three‑quarters of the total gap came from demand falling short of what the available signals suggested.
3. The conditions for a forecast‑response failure are not met because the forecast’s reaction was adequate. Since only three of the four required conditions hold, the miss is classified as a demand event or contextual factor rather than a forecast failure.
4. The National Day Golden Week holiday occurred this week. Historically, holiday weeks for this queue run about 35% below non‑holiday levels, and the plan reflected that pattern (though with a slightly larger adjustment). The holiday was therefore accounted for in the forecast.
5. The number of units under warranty in the market moves together with demand in the same week, and there is sufficient history to use this relationship.
6. The installed base was near its planned level, but each unit generated fewer contacts than expected. The resulting shortfall in contact rate drove the entire gap, while the population contribution was small and offsetting.
7. Five pieces of evidence support the conclusion while ten challenge it. The cross‑examination process found no fatal flaws in eight of the challenges, with the remaining two only raising doubts.

Jargon found: `[]` · causal verbs found: `[]`

Recommendations:

- None
- None
- None

---

*Generated by `results/run_holiday_weekend_tests.py` on branch `test3`. Semantic groups from `dbo.Holiday_Name_Alias`. Narrative written by a model.*