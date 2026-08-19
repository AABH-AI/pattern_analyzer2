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
| Engine status | Incomplete |

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

1. At least one leading signal was present before the week AND has behaved repeatably for this queue, so the movement was foreseeable. This is the mechanism the evidence supports: Demand moved materially, but no sufficiently repeatable leading signal existed beforehand. Direction checks out: the miss pushed demand down and this mechanism implies down.
2. Against an expected 21105.0 contacts (median demand over the last 13 weeks (fewer than 2 prior years available for fiscal week 36)), the plan sat 2180.06 contacts below expectation and demand landed 6303.0 contacts below it. Most of the gap -- 74% of it -- sits on the demand side. Demand moved away from what the available signals pointed to.
3. A forecast-response failure is NOT supported here, because the forecast response was inadequate does not hold. The movement is therefore treated as a demand event, a contextual factor, or unconfirmed -- not as a forecast failure. 3 of 4 conditions hold, so it is not classed as a forecast failure.
4. National Day (China) falls in this week. Weeks containing a holiday have historically run 34.85% below this queue's non-holiday level, across 16 week(s), moving that way in 93.8% of them. The plan for those weeks moved -25.83%, so the pattern was reflected in the forecast historically. Forecast capture: captured -- The plan moved -40.85% against the -34.85% the phase historically implies (1.17x). That is 17.21% more adjustment than the pattern calls for -- inside the tolerance for 'captured', but worth noting. The week sits in the holiday phase. The plan moved -40.85% against the -34.85% the phase historically implies (1.17x). That is 17.21% more adjustment than the pattern calls for -- inside the tolerance for 'captured', but worth noting.
5. Units actually in the market under warranty moves with demand in the same week, with enough history behind it to use. It moves with demand in the same week.
6. The population was close to plan, but contacts per unit differed: 0.0025 actual against 0.0034 planned. The two effects sum to the whole -4,123-contact gap (+1,768 from population, -5,891 from contact rate), so nothing is left unexplained by the split. The gap is driven by contacts per unit differing from plan, not by the population.
7. 5 item(s) support the conclusion and 10 argue against it. Governed by cross-examination, which ran before confidence precisely so its result could feed in. 10 challenge(s) found nothing wrong, 8 raised a doubt and 0 contradicted it outright.

Jargon found: `[]` · causal verbs found: `[]`

Recommendations:

- None
- None
- None

---

*Generated by `results/run_holiday_weekend_tests.py` on branch `test3`. Semantic groups from `dbo.Holiday_Name_Alias`. Deterministic evidence only — no model was called.*