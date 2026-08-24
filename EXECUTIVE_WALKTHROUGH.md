# RCA Agent — walkthrough script for management

**Print this and present from it.** Every figure below was read from the live database and the running
code on 2026-08-24 — none of it is from memory. Where something is not yet solved, it says so; that is
deliberate, because the fastest way to lose a technical audience is a claim they can break in one
question.

Reference screen: the console capture of 2026-08-24, `Social Media Italian Upsell`.

---

## 1. The one-minute version

> **Say this:**
>
> "Every week, about four hundred queues get a forecast that can be scored. Roughly two-thirds of them
> miss by more than ten percent. Today, working out *why* any single one missed is a manual job — an
> analyst pulls history, checks the calendar, looks at shipments, forms a view. It takes hours, and two
> analysts will reach different answers.
>
> This tool does that reasoning in about a minute, the same way every time. It doesn't just say *what*
> missed — it says *why*, it says how sure it is, and critically, it tells you what it could **not**
> determine. It's built so that it cannot bluff."

**The three claims to make, and nothing more:**

| Claim | Why it holds |
|---|---|
| Consistent | Every number is computed in code, not judged. Same input, same answer. |
| Honest | It reports what it cannot measure instead of filling the gap. |
| Auditable | Every figure traces to a named source column and a named formula. |

---

## 2. The problem, in this company's own numbers

> **Say this:** "Here's the scale we're dealing with."

| | |
|---|---|
| Queue-weeks with a scoreable forecast | **71,780** across 268 fiscal weeks — about **403 a week** |
| Missing by more than 10% | **44,883** — that's **63%** |
| …and large enough in absolute terms to matter | **21,788** |
| Contacts actually handled, across the file | **60.3 million** |
| Contacts planned | **78.6 million** |

> **The point to land:** "Sixty-three percent of forecasts miss the band. Nobody can investigate
> forty-four thousand of anything. So the first thing the tool does is *not* investigate — it puts
> **23,095** of those aside because the miss, while large as a percentage, is a handful of contacts.
> A ninety-percent miss on twenty contacts is arithmetic, not a problem. That leaves about
> twenty-two thousand that are genuinely worth someone's time."

**If asked "so it filters?" —** it does more than filter: it ranks what survives by how much the miss
actually matters, using absolute size, the size relative to that queue's own normal week, and whether
the queue has been missing in the same direction for several weeks running.

---

## 3. Where the data comes from

> **Say this:** "One source. No spreadsheets, no copies, no manual steps."

| | |
|---|---|
| Server | `10.10.9.75` |
| Database | `Playground` |
| Table | `dbo.Input_To_ML_Full_138_Trimmed` |
| Size | **114,436 rows · 32 columns** |
| Coverage | **427 queues**, **49 countries**, **3 regions**, **5 channels**, fiscal weeks **202401–202908** |

**The four measures everything else is derived from:**

| Column | What it is |
|---|---|
| `Actual_Offered` | contacts that actually arrived — the measured truth |
| `fcst_offered` | the plan for that week |
| `Planned_ASU` / `Actual_ASU` | installed base — the population that generates contacts |
| `Final_Units` | shipments, a candidate early-warning signal |

### The one honest caveat to volunteer

> **Say this, before anyone asks:** "There's one thing this data cannot do, and I want to be the one
> who tells you. There are seven columns named Monday through Sunday. They look like daily volumes.
> They are not — they only mark *whether a holiday fell on that day*. Every value is a nought or a one.
> So the tool cannot tell you what happened on a Saturday, and rather than guess, it says on screen
> that weekend effect cannot be separated from a weekly total. That sentence appears on every single
> output, and it is the truth."

Volunteering this is worth more than hiding it. It is also the answer to "can we get daily
granularity?" — **not from this source; it would need a new feed.**

### Supporting tables

| Table | Role |
|---|---|
| `dbo.Holiday_Master` | holiday dates by country and fiscal week |
| `dbo.Holiday_Semantic_Group` | 23 event families, so one holiday spelled several ways is counted once |
| `dbo.Holiday_Name_Alias` | raw name → family, scoped by country |
| `dbo.Holiday_Name_Pair_Review` | merge decisions taken, and **185 pairs still awaiting a business answer** |
| `dbo.CQN_Mapping` | authoritative Combined Queue names |

---

## 4. What SQL actually runs

> **Say this:** "Six kinds of read-only query per investigation — up to eleven statements, because one of them runs once per scope level. Nothing is written back. Ever."

| # | What it fetches | Why that window |
|---|---|---|
| 1 | Up to **157 weeks** of this queue's own history | Two years plus, so the same week last year exists to compare against |
| 2 | The **four weeks after** the target week | So a rebound can be measured — did the demand come back? |
| 3 | The same week **aggregated at six levels** — Business Org → Region → SubRegion → Country → Offering → Channel | Answers "is this queue's problem, or the whole region's?" This is the one that runs six times, once per level. |
| 4 | The **other channels** in the same scope | Did the demand move to another channel rather than disappear? |
| 5 | The queue's **Combined Queue name** | So related queues are grouped the way the business groups them |
| 6 | The **holiday calendar** for that country and week | Was there a known, published reason? |

**If a DBA asks for the exact count:** five statements plus one per scope level that exists for that
queue, so eleven at most. A level is skipped when the queue has no value for it.

**Two things to say about how they're written:**

- Every query is **parameterised** — values are passed separately from the SQL text, so a queue name
  cannot alter the query. That is the standard defence against injection.
- Every query is a **`SELECT`**. The application has no `INSERT`, `UPDATE` or `DELETE` against the
  source table. If someone asks whether this can corrupt the data: it structurally cannot.

---

## 5. Walking the screen — every parameter, in order

Present the panels in the order the tabs run. **Six tabs:** Decision · Calendar · Confidence &
Recommendation · Statistics · Challenge · Reference.

### Tab 1 — Decision

| On screen | What to say it means |
|---|---|
| **Forecast Adherence** | "How far off the plan was, as a percentage. **Negative means demand came in above plan** — we under-forecast. Positive means we planned too high." |
| **Direction** | Under-forecast or over-forecast, in words, so nobody has to remember the sign convention. |
| **Absolute Variance** | The gap in contacts. "This is the number that decides whether it matters. A percentage on a small queue is noise." |
| **Forecast / Actual** | The two raw figures, so the percentage can be checked in your head. |
| **Criticality** | Low / Moderate / High / Critical. Driven by absolute size, size relative to this queue's normal week, and whether it's been missing the same way several weeks running. |
| **Why Forecast missed** | The *mechanism* — the family of explanation. Compound miss, forecast-response failure, demand event, and so on. |
| **Executive Summary** | Three or four sentences. Written by a language model, but **every number in it is checked against the engine's own figures first** — see §7. |
| **Why This Happened** | The ranked reasons. "Ranked by the evidence itself: does the explanation match the direction of the miss, could the plan have reacted, does this queue's own history support it, how strong is the measurement, was there enough data, and what argues against it." |
| **Root Cause** | The single promoted cause, with the scope table underneath showing at which level the miss is visible. |

### Tab 2 — Calendar

| On screen | What to say it means |
|---|---|
| **Phase for this week** | Pre-holiday, holiday, or post-holiday. "A week with no holiday in it can still be a holiday week — the effect reaches in from next door, and the tool says so explicitly." |
| **Holidays on this row** | What the source data claims. |
| **Window checked** | ±2 weeks. |
| **The phase table** | Six columns: Phase, Weeks, Demand vs non-holiday, Consistency, Plan moved, Reflected in plan? |
| ↳ *Consistency* | "How often the effect went the same way. Under 60% means the pattern is real but not dependable — and the tool will say that rather than pretend." |
| ↳ *Reflected in plan?* | **The money column.** "Did the plan move the way this queue's own history says it should have? A 'no' here is a correctable miss." |
| **Bias table** | Whether the holiday adjustment is *systematically* wrong across years, which is a different question from whether it was wrong this week. Both are reported because they can disagree. |
| **Weekend question** | Three rows, each with a state and a reason. The first will say NOT TESTABLE — see the caveat in §3. |

### Tab 3 — Confidence & Recommendation

| On screen | What to say it means |
|---|---|
| **Confidence bar and %** | How much the tool trusts its own conclusion. |
| **Cap badge**, when present | "Sometimes the arithmetic gives a high score but a rule caps the level lower. The cap is shown **next to the number, never hidden behind a click** — a confident-looking figure must not be able to disagree with a hidden caveat." |
| **The eight-row table** | *What was scored · Score · Effect · Weight*. Eight dimensions, weighted, combined. |
| ↳ *Weight* | How much that dimension counts. Contradictory evidence is weighted highest at 0.20 — "what argues against the finding matters more than what argues for it." |
| ↳ *Effect* | Holding it up / neutral / dragging it down. |
| ↳ **"Not relevant to this queue"** | "This is the part I'd highlight. When a dimension doesn't apply, it is **left out entirely, not scored zero**. Scoring it zero would punish a queue for a test that was never meaningful." |
| **Criticality panel** | The business-impact reasoning, with the gap against a typical week. |
| **Business Context Used** | Which context elements were present: fiscal calendar, holiday calendar, warranty coverage, volume band, queue metadata — and which were not applicable. |
| **Recommendations** | What to do next. |

### Tab 4 — Statistics

| On screen | What to say it means |
|---|---|
| **Statistical Profile** | Thirteen measures of this queue on its own history — accuracy over three windows, volatility, trend, drift, momentum, seasonality, plan against the seasonal norm, outlier detection. |
| ↳ *"FED THE CONCLUSION" marker* | "Which of these actually drove the answer. The rest are context. That distinction is the difference between a dashboard and an argument." |
| ↳ *Volatility* | "The most useful number here. A queue whose own demand swings forty percent week to week **cannot** be forecast to ten percent, and blaming the forecaster there is wrong." |
| ↳ *Drift* | "Is the *error* moving, as distinct from demand moving? Drift is the one that says this will keep getting worse until the baseline is rebuilt." |
| **Evidence** | Supporting and contradictory items, side by side, deliberately. |
| **Driver Evidence** | Whether shipments, installed base and similar leading indicators actually track this queue's demand, at which lag. |

### Tab 5 — Challenge

| On screen | What to say it means |
|---|---|
| **Interrogation** | "A reviewer's questions, asked *of the findings*. Every answer comes from the evidence file — the model is not allowed to answer from its own knowledge." |
| **Hypotheses Considered** | **All 23**, each with a state and a reason. "This is the part I'd point at if anyone doubts the rigour: it shows you the twenty-two explanations it *rejected*, and why." |

### Tab 6 — Reference

| On screen | What to say it means |
|---|---|
| **Evidence Index** | Every finding, with the field it came from, so any number can be traced. |
| **Limitations** | What could not be assessed. "Reading this section first is a reasonable way to judge whether to trust the rest." |

---

## 6. The worked example — run this live if you can

**`Social Media English Basic`, fiscal week 202422, United States.**

| | |
|---|---|
| Plan | **18,932** contacts |
| Actual | **25,697** contacts |
| Adherence | **−35.7%** — under-forecast |
| Gap | **6,765** contacts |
| Criticality | **Critical** |
| Root cause | **Drift** |
| Confidence | **67.5%** |
| Hypotheses tested | **23** |

> **Say this — this is the moment that sells it:**
>
> "The tool's first ranked reason is this: *the plan did not react at all.* The evidence available
> before that week implied the forecast should have moved by **1,241 contacts**. It moved by
> **77**.
>
> That is not a forecasting error in the usual sense. The signal was there, and the plan ignored it.
> And the tool goes further — it says **83% of the gap sits on the demand side**, so this is not a
> plan that was set at the wrong level; it is a plan that failed to respond to something visible.
>
> No analyst produced that sentence. And it took under a minute."

---

## 7. Why it cannot bluff — the part worth dwelling on

> **Say this:** "The thing I'd want you to take away is not the speed. It's the guardrails."

**Every number is computed in code. The language model writes only prose.** It is called once, at the
end, over figures that are already final.

**A number in that prose which is not in the inputs discards the entire summary.** Not a warning — the
whole narrative is thrown away, the card reports *Investigation Incomplete*, and every figure remains.

> "That has actually fired. The model wrote 'approximately 3,900 contacts' when the real figure was
> 3,929. It rounded — which is normal business writing — and the guard rejected the whole paragraph.
> We then had to decide whether rounding is lying. We decided it isn't, and we widened the rule to
> accept a genuine rounding while still catching an invented number. There are twenty-one test cases
> holding that line, and the ones that *must fail* are the important half."

**Not measurable is never reported as no effect.** If a pattern has three historical instances and the
threshold is four, it says so and names the shortfall.

**Absence of evidence is never evidence of absence.** A weak correlation means *not confirmed* — never
*not a driver*.

**The model is fixed:** temperature 0, fixed seed. Same input, same words.

---

## 8. What's open — say this before you're asked

| Item | Status |
|---|---|
| **185 holiday name pairs** unresolved | Needs a business decision, not code: are two holidays sharing a date one event or two? Recorded, not guessed. |
| **Daily granularity** | Not possible from this source. Would need a new feed. |
| **Business Event Repository** | Not deployed, so promotions and campaigns cannot be tested as causes. Correctly reported as not-applicable rather than counted against the score. |
| **Holiday calendar dating** | Indonesia's Ascension appears on two dates in the master. An upstream data issue, flagged not patched. |
| **Independent review** | The engine's own test suites pass — 190, 148, 21, 14 checks and 20 rendered cards — but no second engineer has reviewed the analytical logic. |

> **Say this:** "I'd rather you heard the open items from me than found them yourself. None of them
> stop the tool being useful today; all of them are written down."

---

## 9. Questions you will be asked

**"Can it be wrong?"**
Yes, and it tells you when it might be. Confidence is a number on the screen, the cap is visible, and
the Limitations section lists what it could not assess. What it will not do is produce a figure it
cannot source.

**"Why should I trust an AI with this?"**
You aren't. The analysis is arithmetic in code. The AI writes the paragraph, over numbers that are
already final, and if it invents a figure the paragraph is destroyed.

**"What happens if the AI is down?"**
The investigation completes. Status reads *Incomplete*, and every figure, cause, confidence score and
recommendation is present. Only the prose is missing.

**"How fast?"**
Under a minute per investigation, most of it the model call. The arithmetic is a fraction of a second.

**"Can it corrupt the data?"**
No. Six read-only `SELECT` queries, all parameterised. No write path to the source table exists.

**"How do we know the maths is right?"**
`mathematics.md` documents every formula and all 86 thresholds, with the reasoning for each, generated
from the source rather than written by hand. Every threshold is a named constant with a comment — not
one is an unexplained number buried in a condition.

**"What does it cost to run?"**
One model call per investigation, two more if the interrogation and summary are used. The summary is
on-demand and cached, precisely because most investigations are never summarised.

---

## Closing line

> "This does not replace an analyst. It does the first two hours of an analyst's work in a minute, the
> same way every time, and it is explicit about the limits of what the data can support. The judgement
> stays with the person; what changes is that they start from evidence instead of from a blank page."
