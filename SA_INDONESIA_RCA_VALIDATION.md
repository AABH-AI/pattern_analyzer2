# RCA validation — SA Indonesia Client Basic, FY27 FW16

Independent check of the generated RCA against `SA_INDONESIA_CLIENT.xlsx` (174 weeks for this
queue, FW202401–202718) and `SA_INDONASIA HOLIDAY.xlsx` (12 Indonesia holiday rows). Every figure
below was recomputed from those two files; nothing was taken from the RCA output. Cross-checked
against `dbo.Input_To_ML_Full`, which agrees exactly (63.7922 / 152.0 / Holiday_Count 0).

**Verdict: the arithmetic is right, the diagnosis is wrong.** Four of the RCA's figures reproduce
exactly. The causal story it builds on them does not survive the data.

---

## 1. The target week

```
FW202716    forecast   63.79
            actual    152
            variance  +88.2 contacts
            adherence -138.27%          under-forecast
            Holiday_Count = 0
            scope APJ / SA / Indonesia / Basic / Voice · plan FY27 Jun Projection · Brian Tan
```

## 2. What the RCA got right

| Claim | Recomputed | Verdict |
|---|---|---|
| under-forecast by 88.2, actual 152 vs 63.8 | +88.2, 152 vs 63.79 | **exact** |
| drift −9.84 points/week over 13 weeks (≈ −128 total) | slope **−9.84**, total **−128** | **exact** |
| holiday weeks run ~21% below normal | **−20.0%** (96.6 vs 120.8, n=58/114) | **confirmed** |
| Offering out by 88 contacts, this queue is 100% of it | group gap +88.2, queue = 100% | **arithmetically true** (see 3.5) |

The engine is measuring correctly. The failure is in what it concludes.

---

## 3. What the RCA got wrong

### 3.1 The holiday explanation predicts the opposite sign — this is the central error

The RCA says holidays reach into FW202716 and *"holiday weeks run 21% below normal for this queue
(92 contacts against 117). The plan did not carry that adjustment."*

Follow that through. If holidays **reduce** demand and the plan **failed to reduce**, the plan would
be too **high** → an **over**-forecast. The actual miss is a **−138% under-forecast**: demand came in
at **2.4× the plan**.

**The holiday argument, if true, would make the miss go the other way.** It cannot be the cause.

Confirmed three ways:

- `Holiday_Count = 0` for FW202716 in both the file and SQL.
- No holiday row lands on FW202716. The supplied file places holidays on
  `202114, 202117, 202217, 202617, 202715, 202717, 202814, 202818` — FW202716 is absent.
- Holiday weeks for this queue average **96.6** contacts against **120.8** for non-holiday weeks.
  FW202716 came in at **152** — the highest of the surrounding nine weeks, and *above* the
  non-holiday mean.

### 3.2 One holiday named does not exist in the supplied data

The RCA lists four: *"Ascension Day of Jesus Christ, Ascension of Jesus Christ, Idul Fitri Holiday,
Joint Holiday for Waisak Day"*.

**"Joint Holiday for Waisak Day" is not in the holiday file at all.** The file's only Waisak entries
are `Waisak Day (Buddha's Anniversary)` at FW202114 and FW202217 — five and six years from the
target. That name came from another source and this file does not corroborate it.

### 3.3 Two of the four names are the same holiday, counted twice

| Row | Fiscal week | Name | Type |
|---|---|---|---|
| H11333 | 202715 | Ascension **of** Jesus Christ | Public Holiday |
| H12013 | 202717 | Ascension **Day of** Jesus Christ | Derived from INPUT_TO_ML |
| — | 202717 | Ascension **Day of** Jesus Christ | Derived from INPUT_TO_ML |
| — | 202717 | Ascension **Day of** Jesus Christ | Public Holiday |

The same event appears under two canonical names, and FW202717 carries **three** rows for it.
De-duplication is on exact name, so the variants survive. Listing all four makes one holiday in an
adjacent week read as a four-holiday cluster.

### 3.4 "Drift" fails its own fit test as soon as the window widens

| Window | Slope (adherence pts/week) | Total | r² |
|---|---|---|---|
| last 13 weeks | **−9.84** | −128 | **0.29** |
| last 26 weeks | −2.03 | −53 | 0.09 |
| last 52 weeks | −0.61 | −32 | 0.06 |

The 13-week slope is the RCA's **primary supporting evidence**, and its own fit is 0.29 — below the
0.30 floor the engine uses elsewhere to call a trend meaningful. Widen the window and the slope
collapses by a factor of sixteen.

This queue has a **CoV of 31%** over 13 weeks. On a series that volatile, a 13-week regression will
produce a slope in some direction most of the time. **This is a window artefact, not a decaying
baseline.** Error metrics agree there is no standing lean: 52-week bias **+1.8** contacts.

### 3.5 The scope finding is true by construction, not a finding

*"Offering (CSG / APJ / SA / Indonesia / Basic) is out by 88 contacts, but this single queue is 100%
of that."*

The Offering group at FW202716 contains **exactly one queue** — this one. A single-member group is
always 100% of its own gap. Reported as *"Not because the wider book moved"*, it reads as evidence
that the miss is queue-specific, when in fact **no comparison was possible**.

---

## 4. What actually happened

### 4.1 Week 16 is this queue's strongest week of the year, and the plan was cut going into it

| Fiscal week 16 | Actual |
|---|---|
| 202416 | 195 |
| 202516 | 66 |
| 202616 | 106 |
| **202716** | **152** |
| mean of prior years | **129.8** |

Overall mean across 174 weeks: **112.7**. So week 16 carries a **seasonal index of 1.086** — about
**9% above normal**, and the highest of weeks 13–18:

```
wk 13  112.2      wk 16  129.8   <-- target, strongest
wk 14  107.0      wk 17   87.5
wk 15  106.8      wk 18  116.5
```

The plan was set at **63.79** — **51% below** the week-16 historical mean and **33% below** the
queue's own 52-week average forecast of 95.3.

### 4.2 Demand was already rising, and the plan moved down anyway

```
week        forecast   actual     adh%   hol
FW202712      114.9      131    -14.0%    0
FW202713       89.7       93     -3.7%    1
FW202714       35.9      103   -186.9%    0
FW202715       98.5       96     +2.5%    2
FW202716       63.79     152   -138.3%    0   <-- target
```

**Momentum going in: +21.6%** — the last 4 weeks averaged 105.8 against 87.0 for the prior 8. The
plan went **down** from 98.5 to 63.79 into a rising, seasonally strong week.

Both sides moved, but not equally: actual **z = +2.17**, forecast **z = −1.80** against their own
52-week distributions. The plan is nearly as anomalous as the demand — and the plan is the side
under our control.

### 4.3 The plan tracks a driver that does not drive demand

| Driver | r vs **actual** (levels) | r vs **actual** (week-to-week) | r vs **forecast** (levels) |
|---|---|---|---|
| Actual_ASU | +0.559 | **−0.186** | **+0.805** |
| Planned_ASU | +0.472 | **−0.106** | +0.657 |
| Final_Units | −0.093 | +0.039 | — |
| Final_upp_units (shipments) | only **5** usable rows | — | — |
| Holiday_Count | −0.303 | **−0.433** | — |

Two things stand out.

**The forecast is more tightly coupled to ASU (r = +0.805) than actual demand is (+0.559)** — and at
the week-to-week level ASU and demand move *slightly opposite* (−0.186). The plan is being driven by
a series that shares a multi-year trend with demand but does not move with it in any given week.
That is a structural source of recurring error, and it is the most actionable finding here.

**Holiday_Count is the only driver that genuinely moves with demand week to week** (−0.433) — so
holidays *do* matter for this queue, in the direction of *reducing* demand. FW202716 had none.

**Shipments cannot be assessed**: `Final_upp_units` has 5 usable rows out of 174.

### 4.4 Accuracy has roughly doubled in error recently

| Window | MAE | WAPE | Bias |
|---|---|---|---|
| last 13 weeks | 36.6 | **40.6%** | −4.2 |
| last 52 weeks | 20.2 | 20.8% | +1.8 |

Recent error is twice the annual level, and the bias is near zero in both — the misses swing both
ways. That is the signature of an **unstable plan**, not a biased one.

---

## 5. The corrected RCA

> **Primary cause — forecast baseline error, seasonal omission.**
> The plan for FW202716 was set at 63.8 contacts against a week that historically runs 129.8 — this
> queue's strongest week of the year (seasonal index 1.086). Demand momentum was already +21.6%
> going in, and the plan was still cut from 98.5 to 63.8. Actual demand of 152 is within one
> standard deviation of the week-16 historical mean; **the plan is the outlier, not the demand.**
>
> **Contributing cause — the plan follows a non-causal driver.**
> The forecast correlates with ASU at r = +0.805 while actual demand correlates at +0.559, and at
> the week-to-week level demand and ASU move slightly *opposite* (−0.186). A plan anchored to a
> series that only shares a long-run trend with demand will keep missing in both directions —
> consistent with 40.6% WAPE and near-zero bias over 13 weeks.
>
> **Rejected — holiday effect.** `Holiday_Count = 0`; no holiday lands on FW202716; and holidays
> *reduce* this queue's demand by 20%, which would produce an over-forecast, not the observed
> −138% under-forecast.
>
> **Rejected — baseline drift.** The −9.84 pts/week slope has r² = 0.29 and collapses to −0.61
> (r² = 0.06) over 52 weeks. A window artefact on a series with 31% CoV.
>
> **Not assessable — shipments.** `Final_upp_units` carries 5 usable rows of 174.
>
> **Confidence: Medium.** The seasonal and momentum evidence is independent and consistent. It is
> held below High by genuine volatility (CoV 31%) and by only four observations of week 16.

---

## 6. How to integrate this — seven changes

Each is a gate or check that would have prevented one of the errors above.

1. **Direction-coherence gate (highest value).** A cause may only be accepted if the sign of its
   predicted effect matches the sign of the miss. A holiday that *reduces* demand cannot explain an
   *under*-forecast. This single rule kills 3.1 — and it also kills the Good Friday case already
   recorded in `walkthrough.md`. **One rule, two classes of wrong conclusion removed.**

2. **Holiday-in-week requirement.** Report `in_week` and `in_window` separately in the narrative,
   and never name a window holiday without saying it is in an adjacent week. Require
   `Holiday_Count > 0` **or** a measured deficit in the target week before a calendar cause is
   accepted.

3. **Window-stability test on any slope.** Compute drift at 13, 26 and 52 weeks and require the
   sign to hold and r² ≥ 0.30 at the longest window that has data. Report the disagreement when it
   does not: *"the 13-week slope is −9.84 but −0.61 over 52 weeks, so this is short-window noise."*

4. **Seasonal-index vs plan check — this is the missing hypothesis.** For every investigation,
   compare the plan against the week-of-year index. Flag `plan set N% below the seasonal norm`. This
   is what actually explains FW202716 and no current hypothesis tests for it.

5. **Driver-coupling check.** Compare `r(forecast, driver)` with `r(actual, driver)`. Where the plan
   tracks a driver more tightly than demand does, raise it as a forecasting defect. This is a new
   and genuinely diagnostic signal — it explains recurring error rather than one week.

6. **Single-member group guard.** When a scope level has one member, say
   *"this queue is the only member of its Offering group, so the comparison cannot discriminate"* —
   never *"this queue is 100% of the difference"*.

7. **Semantic-family de-duplication for holidays.** De-duplicate on `Semantic_Family` (a column the
   supplied holiday file already carries) rather than exact name, so *Ascension of Jesus Christ* and
   *Ascension Day of Jesus Christ* collapse to one event.

### Data issues worth fixing at source

- **`SA Indonesia Client Basic` is the only queue of 427 whose extract has blank scope columns** —
  all 174 rows lack Region, SubRegion, Country, Offering, channel, Forecaster and plan name. SQL has
  them, so the export is at fault, not the engine.
- **12% of rows across the file have no `Projection_plan_name`** (16,598 of 138,529), which is what
  makes plan-vintage questions unanswerable.
- The holiday file mixes `Public Holiday` rows with rows typed `Derived from INPUT_TO_ML`, and the
  derived ones duplicate the public ones. Provenance should decide precedence.
