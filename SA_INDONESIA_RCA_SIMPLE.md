# The Indonesia forecast miss — explained in plain English

*A simple version of `SA_INDONESIA_RCA_VALIDATION.md`. No statistics background needed.*

---

## What happened, in one paragraph

One week in Indonesia, our forecast said to expect about **64 customer contacts**. **152** actually
came in — more than double. Our RCA system looked at it and said: *"demand spiked, a holiday made it
worse, and the forecast has been slowly getting worse for 13 weeks."*

We checked that answer against three years of real data for this queue. **The system's numbers were
right, but its explanation was wrong.** The real reason is simpler and more useful: **this is
normally the busiest week of the year for this queue, and the plan was cut just before it.**

---

## First, the good news

The system is doing its sums correctly. We recalculated everything from your two spreadsheets and it
matched:

| What the system said | What we found |
|---|---|
| Missed by 88 contacts (152 actual vs 64 planned) | Correct |
| Forecast slipping about 9.8 points a week | Correct |
| Holiday weeks are about 21% quieter | Correct (we got 20%) |

So this is not a broken calculator. **The problem is the story it built on top of those numbers.**

---

## The main problem: the holiday explanation is backwards

The system said a holiday was partly to blame — that holidays make this queue quieter, and the plan
forgot to allow for it.

Think about what that would actually do.

> **A shop closes for a public holiday.** Fewer customers come in that week.
> If your plan *forgot* about the closure, you would have expected **too many** customers,
> not too few.

That is the opposite of what happened here. We expected **64** and got **152**. We expected far
**too few**, not too many. So a holiday — which makes things *quieter* — cannot explain a week that
came in *much busier*.

**The explanation and the problem point in opposite directions.**

And there is a simpler point on top of that: **there was no holiday that week at all.** The holiday
column reads zero. The nearest holidays are in the week before and the week after.

---

## Four more things that don't hold up

### 1. One holiday it named doesn't exist in your data

The system listed *"Joint Holiday for Waisak Day"*. That name appears nowhere in the holiday
spreadsheet you gave us. The only Waisak entries are from **2020 and 2021** — five years away from
the week we were looking at.

### 2. Two of the holidays it named are the same holiday

It listed *"Ascension of Jesus Christ"* **and** *"Ascension Day of Jesus Christ"*. Those are the same
day, written two different ways in the data. One week has it recorded **three times**.

So what is really *one* holiday, in a *neighbouring* week, was presented as **four holidays**
crowding around this one. That makes the holiday explanation look far stronger than it is.

### 3. The "getting worse for 13 weeks" claim vanishes when you look longer

The system found the forecast slipping 9.8 points a week over 13 weeks. That is real — but look
wider:

| How far back you look | How fast it's "slipping" |
|---|---|
| 3 months | 9.8 points a week |
| 6 months | 2.0 points a week |
| 1 year | **0.6 points a week** |

> It is like judging the climate from two weeks of weather.

This queue is genuinely bumpy — the number of contacts swings about **30%** week to week. When
something bounces around that much, you can almost always find a "trend" if you pick a short enough
window. Over a full year, there is essentially no trend at all.

**This was the system's main piece of supporting evidence, and it doesn't survive a longer look.**

### 4. "This queue is 100% of the problem" sounds meaningful, but isn't

The system said the wider group was off by 88 contacts and this one queue accounted for **all** of
it — implying the problem is specific to this queue.

But **that group contains only one queue: this one.** Of course it is 100% of its own number. It is
like saying you won a race you ran alone. Nothing was actually compared.

---

## So what really happened?

### This is normally the busiest week of the year for this queue

We looked at the same week across four years:

| Same week, different years | Contacts |
|---|---|
| 2024 | 195 |
| 2025 | 66 |
| 2026 | 106 |
| **2027 (the week in question)** | **152** |
| **Typical for this week** | **130** |

The queue's normal level across all weeks is about **113**. So this particular week of the year
usually runs **higher** than normal — it is one of this queue's busier weeks.

**And the plan was set at 64** — less than half what this week normally brings.

### Demand was already climbing, and the plan was cut anyway

Here are the weeks leading up to it:

| Week | Plan | Actual |
|---|---|---|
| four weeks before | 115 | 131 |
| three weeks before | 90 | 93 |
| two weeks before | 36 | 103 |
| one week before | 99 | 96 |
| **the week in question** | **64** | **152** |

Contacts had been running around 100 for a month and rising. The plan went **down** from 99 to 64,
heading into the busiest week of the year.

**The demand was not the surprise. The plan was.**

---

## The bigger discovery — and the most useful one

We found something that explains not just this week, but why this queue keeps getting missed.

The plan appears to be built by following **"units under warranty"** — how many machines are out
there under support cover. That sounds sensible.

But we checked whether contacts actually follow that number week to week. **They don't.**

- The **plan** follows units-under-warranty very closely (0.81 out of 1.0)
- **Actual contacts** follow it much more loosely (0.56)
- And week to week, contacts and units-under-warranty move **slightly in opposite directions**

> It is like steering a boat by watching the tide when you should be watching the waves.
> The tide tells you roughly where the sea is over months. It tells you nothing about the wave
> about to hit you.

The plan is anchored to something that moves with demand over *years* but not over *weeks*. That is
why this queue's forecasts miss in **both directions** — sometimes far too high, sometimes far too
low — rather than being consistently wrong one way.

We can also see the accuracy getting worse recently: over the last year the forecast was typically
off by about **20 contacts**; over the last three months, about **37**.

---

## The corrected answer

> **Main reason:** the plan was set at 64 contacts for a week that normally brings about 130 — this
> queue's busiest time of year — while demand had already been climbing for a month. The plan was
> even *reduced* going into that week. The 152 contacts we received were entirely normal for that
> week of the year. **The plan was the odd one out, not the customers.**
>
> **Underlying reason:** the plan is built around units-under-warranty, which does not track weekly
> contact volumes. Until that changes, this queue will keep missing in both directions.
>
> **Not the reason — holidays.** There was no holiday that week, and holidays make this queue
> *quieter*, which would have made us over-predict, not under-predict.
>
> **Not the reason — a slipping baseline.** That trend only appears if you look at exactly three
> months, and disappears over a year.
>
> **Couldn't check — shipments.** That column is almost entirely empty for this queue: 5 usable
> rows out of 174.

---

## What we've fixed, and what still needs fixing

### Already fixed and tested

**A "does this make sense?" check.** The system now asks one new question of any holiday
explanation: *does this push demand the same way the miss actually went?* If a holiday makes a queue
quieter, it can no longer be blamed for a week that came in busier. We tested it — it correctly
rejects both this Indonesia case and a similar Good Friday case we found earlier in the Czech
Republic. **One rule, two wrong answers prevented.**

**Ranking causes properly.** The system was listing a 70%-confidence cause above a 90% one. Now
sorted correctly.

### Still to do

1. **Check the calendar against the plan.** Nothing currently asks *"is this a week that's normally
   busy, and did the plan allow for that?"* — which is the actual answer here.
2. **Test trends over more than one window.** Report a trend only if it holds up over a longer
   period too, and say so when it doesn't.
3. **Compare what the plan follows against what demand follows.** This is how we found the
   units-under-warranty problem. It would flag this on every queue automatically.
4. **Stop saying "100%" when a group has only one member.** Say the comparison wasn't possible.
5. **Treat the same holiday written two ways as one holiday.**
6. **Only blame a holiday if there was one that week** (or genuinely close enough to matter).

### Two data problems worth fixing at the source

- This queue is the **only one out of 427** whose export is missing its basic details — region,
  country, product, channel, forecaster, plan name. The database has them; the spreadsheet export
  dropped them.
- **12% of all rows** in the file have no plan name recorded, which is why the system can't answer
  questions like *"was the plan revised after the last time this happened?"*

---

## The short version

| | |
|---|---|
| **What the system said** | Demand spiked; a holiday contributed; the forecast has been slipping |
| **Were its numbers right?** | Yes, all of them |
| **Was its reasoning right?** | No — the holiday explanation points the wrong way, and there was no holiday |
| **What really happened** | The plan was cut to 64 for a week that normally brings 130, while demand was rising |
| **The deeper issue** | The plan follows units-under-warranty, which doesn't track weekly demand |
| **Fixed so far** | A logic check that rejects explanations pointing the wrong way; correct cause ordering |
| **Biggest remaining gap** | Nothing checks the plan against what that week of the year normally brings |
