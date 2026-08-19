# Social Media China Basic — FW202435 — Social Media

*Seven holidays, every weekday flagged. Mid-Autumn Festival and National Day share 2023-10-01 and are different holidays -- the case where a naive merge would do damage.*

| | |
|---|---|
| Scope | APJ / CCC / China · Basic · Social Media |
| Actual offered | **10,919** |
| Forecast offered | **14,847.8** |
| Forecast adherence | **+26.5%** (Over-forecast) |
| Absolute variance | 3,929 contacts |
| `Holiday_Count` on the row | 7 |
| History available | 34 weeks |
| Confidence · Criticality | Medium 65.0% · High |
| Mechanism | COMPOUND_MISS |
| Engine status | Complete |

## 1. The holidays, raw and grouped

`Holiday_Master` rows for China FW202435 — **3 raw name(s)**:

| Raw name | Date | Weekday | Type | Semantic group | Review |
|---|---|---|---|---|---|
| Mid-Autumn Festival holiday | 2023-10-01 | Sunday | Public Holiday | `CN_MIDAUTUMN` |  |
| National Day | 2023-10-01 | Sunday | Public Holiday | `CN_NATIONALDAY` |  |
| National Day Golden Week holiday | 2023-10-02 | Monday | Public Holiday | `CN_NATIONALDAY` |  |

**What the card displays** (prompt2 clauses E and F):

> Holidays in this week: Mid-Autumn Festival, National Day (China).
>
> Recent holidays potentially affecting this week: none.

| | Raw names reaching the week | Canonical names displayed |
|---|---|---|
| Count | 4 | 2 |
| Names | Mid-Autumn Festival, Mid-Autumn Festival holiday, National Day, National Day Golden Week holiday | Mid-Autumn Festival, National Day (China) |

**In this fiscal week** — 2 group(s):

| Display name | Occurrences | Dates | Weekdays | Raw spellings |
|---|---|---|---|---|
| Mid-Autumn Festival | 1 | 2023-09-29, 2023-09-30, 2023-10-01 | Friday, Saturday, Sunday | Mid-Autumn Festival / Mid-Autumn Festival holiday |
| National Day (China) | 1 | 2023-10-01, 2023-10-02, 2023-10-03, 2023-10-04, 2023-10-05, 2023-10-06, 2023-10-07 | Sunday, Monday, Tuesday, Wednesday, Thursday, Friday, Saturday | National Day / National Day Golden Week holiday |

## 2. Weekend and weekday structure

Clause C — three separate questions, not one refusal:

| Question | State | Why |
|---|---|---|
| Daily weekend demand effect | `NOT_TESTABLE` | Weekend impact cannot be isolated from fiscal-week totals because day-level actual and forecast data is unavailable in the source. |
| Weekly calendar structure | `AVAILABLE` |  |
| Holiday × weekend interaction | `AVAILABLE` | both an adjoining-weekend group and a midweek group need 4 or more weeks before the two can be compared |

Clause K — weekly outcome by the weekday a holiday fell on. Reference: **30** weeks with no holiday day flagged, median **33,666** contacts.

| Holiday fell on | Weeks | Median actual | vs no-holiday week |
|---|---|---|---|
| Monday | 3 | — | not measurable — only 3 week(s) with a holiday on Monday; 4 needed |
| Tuesday | 3 | — | not measurable — only 3 week(s) with a holiday on Tuesday; 4 needed |
| Wednesday | 3 | — | not measurable — only 3 week(s) with a holiday on Wednesday; 4 needed |
| Thursday | 2 | — | not measurable — only 2 week(s) with a holiday on Thursday; 4 needed |
| Friday | 2 | — | not measurable — only 2 week(s) with a holiday on Friday; 4 needed |
| Saturday | 2 | — | not measurable — only 2 week(s) with a holiday on Saturday; 4 needed |
| Sunday | 2 | — | not measurable — only 2 week(s) with a holiday on Sunday; 4 needed |

Spread across weekdays: **None points**.

Long-weekend grouping — this week's pattern is **holiday_adjoining_weekend** (long weekend):

| Holiday day pattern | Weeks | Median actual | vs no-holiday week |
|---|---|---|---|
| holiday adjoining weekend | 4 | 22,964 | **-31.8%** |
| midweek holiday | 1 | — | only 1 week(s) of this pattern; 4 are needed |

## 3. Calendar phase and rebound

| | |
|---|---|
| Resolved phase | `holiday` |
| Window checked | ±2 weeks |
| Zero-count but adjacent | False |
| Phase effect vs own baseline | -11.9% across 4 instances |
| Rebound repeatability | **NOT ENOUGH DATA** (3 instances) |

> There are too few past instances to say whether this queue's post-holiday rebound repeats. That is a limit of the history, not evidence that no pattern exists.

## 4. What the engine concluded

**Root cause:** Outlier

This week is itself a statistical outlier for this queue: 10,919 contacts against a typical 33,178 -- a genuine dip, not a rounding issue. 2 of 35 weeks (6%) in the window are outliers -- which means spikes like this are uncommon but not rare for this queue, so treat it as notable rather than exceptional.

Ranked reasons:

1. The plan moved –59.79 %, well beyond the –11.93 % that the holiday phase historically implies. This is one of the mechanisms the evidence supports: more than one supported mechanism contributed materially. Direction checks out: the miss pushed demand down and this mechanism implies down.
2. Planned units for delivery / production (shipment) eight weeks earlier has a stronger and more stable historical relationship with demand than the same‑week comparison. This is one of the mechanisms the evidence supports: more than one supported mechanism contributed materially. Direction checks out: the miss pushed demand down and this mechanism implies down.
3. Against an expected 33,790 contacts (median demand over the last 13 weeks), the plan sat 18,942 contacts below expectation and demand landed 22,871 contacts below it. Most of the gap – about 55 % – sits on the demand side, meaning demand moved away from what the available signals pointed to.
4. A forecast‑response failure is supported: a repeatable signal was available before the week and the plan did not respond adequately to it. All four conditions for calling this a forecast‑response failure hold – the plan could have reacted. However, the direction‑coherence gate rejected it as the cause because the mechanism implies demand moving the opposite way to this miss. Being able to react and being the explanation are two different tests; this evidence passes the first and fails the second.
5. Mid‑Autumn Festival and National Day (China) fall in this week. Weeks containing a holiday have historically run 11.93 % below this queue's non‑holiday level, across four weeks, moving that way in 100 % of them. The plan for those weeks moved –24.88 %, so the pattern was reflected in the forecast historically. Forecast capture: over‑reacted – the plan moved –59.79 %, well beyond the –11.93 % the phase historically implies. The week sits in the holiday phase, and the plan moved –59.79 %, well beyond the –11.93 % the phase historically implies.
6. The population was close to plan, but contacts per unit differed: 0.0012 actual against 0.0018 planned. The two effects sum to the whole –3,929‑contact gap (+1,366 from population, –5,294 from contact rate), so nothing is left unexplained by the split. The gap is driven by contacts per unit differing from plan, not by the population.
7. FORECAST_BASELINE_FAILURE was raised by the evidence but points the opposite way to the miss. Governed by the direction‑coherence gate (section 32). The miss pushed demand down and this mechanism implies up, from the plan sitting below the expected level for this week (–56.1 %) – the directions disagree, so the mechanism cannot be the cause.
8. FORECAST_RESPONSE_FAILURE was raised by the evidence but points the opposite way to the miss. Governed by the direction‑coherence gate (section 32). The miss pushed demand down and this mechanism implies up, from the plan sitting below the expected level for this week (–56.1 %) – the directions disagree, so the mechanism cannot be the cause.
9. Eight items support the conclusion and eight argue against it. Governed by cross‑examination, which ran before confidence precisely so its result could feed in. Thirteen challenge(s) found nothing wrong, five raised a doubt and none contradicted it outright.

Jargon found: `[]` · causal verbs found: `[]`

Recommendations:

- None
- None
- None

---

*Generated by `results/run_holiday_weekend_tests.py` on branch `test3`. Semantic groups from `dbo.Holiday_Name_Alias`. Narrative written by a model.*