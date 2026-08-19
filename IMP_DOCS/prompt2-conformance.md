# `prompt2.md` conformance — dataset-reality rules

Built and audited **2026-08-18** on branch `test3`, engine `?mode=spec`, card `2.1.0`.

Companion to `new-prompt-conformance.md`. The two documents ask for different things and it is worth
being clear about which is which:

| | |
|---|---|
| `new_prompt.md` | additive **analysis** — measure more things |
| `prompt2.md` | **data-reality discipline** — what the analysis is allowed to CLAIM from a weekly-grain source |

`prompt2.md` is mostly prohibitive, and several clauses are corrections rather than features. Clause F
is the only one in either document that calls itself **mandatory**.

Re-run the audit — **no model tokens are spent** (empty `llm_cfg`, `interrogate=False`):

```
python results/audit_prompt2_conformance.py
python results/audit_prompt2_conformance.py "Canada Core French" 202722
python results/audit_prompt2_conformance.py "Brazil Comm Client CEM ProSupport" 202722
node   results/check_prompt2_render.js <live-response.json> [...]
```

---

## Result

| Queue | Shape | Result |
|---|---|---|
| SA Indonesia Client Basic FW202716 | adjacent holidays only, `Holiday_Count=0` | **OK 16** |
| Canada Core French FW202722 | holiday **inside** the week | **OK 15 · PARTIAL 1** |
| Brazil CEM ProSupport FW202722 | no holiday in the ±2 window | **OK 11 · n/a-here 5** |

Opening audit was `OK 7 · PARTIAL 3 · GAP 6`.

Canada's single PARTIAL is honest: only 3 of 7 weekdays clear the 4-week sample floor, because Canada
has fewer holidays than Indonesia. Brazil's five `n/a-here` are the same kind of honesty — that queue
has no holiday event to inspect, so clauses B, D and E have nothing to test. Marking either OK would
over-report.

---

## What was built

### Clause F — the mandatory separation  *(the one that was actually wrong)*

`backend/wfm/holiday_response.py` — `holidays_in_target_week` and
`recent_holidays_affecting_target_week`, each with its own statement, canonical name list and audit
rows.

Before, one `names` list mixed both. On SA Indonesia FW202716 that meant **four holidays presented
together while `Holiday_Count` was 0 and not one of them fell inside the week** — which is exactly how
that card read as "four holidays crowding this week", and is the root of the Ascension / Idul Fitri /
Waisak confusion this project has been arguing about for days.

Now, on the same queue:

> **Holidays in this week: None.**
> Recent holidays potentially affecting this week: Ascension of Jesus Christ, Idul Fitri Holiday,
> Joint Holiday for Waisak Day. No holiday occurs directly in this fiscal week; the analysis
> therefore evaluates whether this week resembles a historical post-holiday or pre-holiday pattern.

That second sentence is clause N's required wording, built in the module rather than left to a
renderer, because the whole point is that it cannot be got wrong.

`names` is retained untouched so nothing reading it breaks — but it must never again be rendered as
"holidays in this week".

### Clause E — canonical semantic names, raws kept for audit

Grouped by **`semantic_group_id`**, not by canonical name. The first attempt de-duplicated on the
name and still printed both "Ascension of Jesus Christ" and "Ascension Day of Jesus Christ" — two
spellings of one family, which is the repetition clause E exists to remove. Result: **raw 4 →
displayed 3**.

What it must never do, and does not: merge two *different* holidays that share a date. That is clause
E's own Christmas / Quaid-e-Azam prohibition, and it holds by construction — grouping is by semantic
group and those have different groups. `by_semantic_group` publishes every raw spelling and date under
the family name so the collapse is auditable.

### Clauses B and D — the weekday, from the DATE

`backend/wfm/holiday_events.py` — `weekday_of()` and `weekday_structure()`, attached to every event.

Derived from the holiday **date**, not from the row's `Monday..Sunday` flags. The flags only say
"some holiday touched Monday", never *which* — the confusion prompt2's own closing note points at.
The date is authoritative and comes from the Holiday Master.

Four independent flags, deliberately not collapsed into one label, because a two-day event can
straddle Friday and Saturday:

| Flag | Meaning |
|---|---|
| `holiday_on_weekend` | every day of the event falls Sat/Sun |
| `holiday_before_weekend` | **Friday** — the closure runs forward into the weekend |
| `holiday_after_weekend` | **Monday** — the closure extends backward out of one |
| `long_weekend_candidate` | any of the above |

Clause B explicitly wants Friday and Monday distinguished; the previous work for `new_prompt` §12
lumped both into "adjoining". Verified against real dates: 2026-05-14 is a Thursday (Ascension),
Idul Fitri lands on a **Friday**, Pancasila Day on a **Monday**, Vesak on the weekend. A malformed
date returns `None` rather than raising.

### Clause C — the weekend is three questions, not one refusal

`backend/wfm/fc_evidence.py` — `_weekend_three_states()`, published as `clause_c_states`.

The document names stopping at *"weekend impact cannot be isolated"* as the error. That sentence is
still shown, because it is still true — what sits beside it now is what **is** answerable:

| Question | Indonesia | Brazil |
|---|---|---|
| daily weekend demand effect | `NOT_TESTABLE` | `NOT_TESTABLE` |
| weekly calendar structure | `AVAILABLE` | `AVAILABLE` |
| holiday × weekend interaction | `AVAILABLE` | `AVAILABLE` |

### Clause K — per-weekday weekly outcomes

`weekday_outcomes()`. Grouped from the row day flags, which is legitimate here: clause K asks which
**weekday** was affected, not which holiday it was, and the flags answer exactly that. Clause A's
prohibition is on reading the result as daily volume, so every sentence is phrased as a weekly
outcome for weeks of that shape.

All seven weekdays measurable on both larger queues, and the pattern replicates independently:

| Holiday fell on | SA Indonesia (ref 111.0, n=107) | Brazil (ref 217.5, n=120) |
|---|---|---|
| Monday | −13.1% (12 wks) | −29.2% (8) |
| Tuesday | −42.3% (8) | −37.9% (7) |
| Wednesday | −25.7% (8) | −41.6% (8) |
| Thursday | −24.8% (20) | −36.8% (10) |
| Friday | −24.8% (12) | −31.5% (5) |
| **Saturday** | **+4.5%** (6) | **−14.0%** (5) |
| **Sunday** | **−8.1%** (9) | **−3.0%** (6) |
| spread | **46.8 pts** | **38.6 pts** |

Weekday holidays cut the week hard; weekend holidays barely move it, because they land on days
already non-working. Nobody told the code that — it fell out of the data, on two unrelated queues in
different regions.

**This supersedes what was built for `new_prompt` §12.** That grouping reported only 9.5 points
between "adjoining" and "midweek" because it averaged Friday (−24.8%) with Monday (−13.1%), and
Tuesday (−42.3%) with Thursday (−24.8%). The per-weekday split reveals structure the grouping hid.
The §12 block is left in place; clause K is the finer instrument.

### Clause M — the five availability states, mapped not replaced

`P2_STATE_MAP` plus `p2_state()`. The engine's own `Available` / `Missing` / `NotApplicable` feed
confidence dimensions and must not move (`new_prompt.md` §1 and §25), so prompt2's vocabulary is
published alongside.

`Missing` maps to **`PARTIALLY_AVAILABLE`**, not `NOT_AVAILABLE`, because in this engine Missing means
"relevant and present but too thin to rely on" — a different finding from absent, and the distinction
§17 turns on. `testable=False` overrides to `NOT_TESTABLE`: the data can exist while the question
cannot be answered from it, which is clause C's first state.

---

## The check that was missing

`results/check_prompt2_render.js` — renders `cardCalendarPanel` from a live response in a VM and
greps the resulting **HTML**.

This exists because of a real failure on the previous round: new evidence was verified in the API
response, the card panels silently filtered it out, and the page never changed. **The user found it,
not a test.** Verifying JSON does not answer "does the reader see it".

Assertions are **conditional on the payload**, because clause F is conditional by design:

| Payload | Required |
|---|---|
| in-week holidays present | an in-week table, and **no** "no holiday occurs directly" sentence |
| in-week holidays absent | "Holidays in this week: None." **and** that sentence |
| adjacent holidays present | an adjacent table |

An unconditional version failed on both test queues for opposite reasons, which is how this shape was
arrived at. **28/28 checks pass** across the two payload shapes.

Both the panel (`decision_card.calendar_panel`) and the renderer were widened in the same pass this
time, rather than declaring the response correct and stopping.

---

## Not done, and why

1. **Clause D asks the Holiday Master to be a first-class joined dataset**, and prompt2's closing note
   is right that this would remove most of the remaining confusion at source. The engine still reads
   the JSON snapshot at runtime. Changing that is a data-pipeline decision, not an engine edit.
2. **Semantic holiday merging across genuinely different names** — Diwali/Deepavali, Waisak/Vesak —
   remains unsolved and cannot be solved deterministically. Measured on the master: after a
   same-country same-date pre-filter there are **276 name pairs** to adjudicate, of which a rule can
   decide **23%**; the other **77%** need knowledge outside the strings. Roughly half of those are the
   *inverse* case — genuinely different holidays sharing a date, where merging would corrupt the
   measurement. `semantic_family` already exists in the runtime JSON, populated on **99 of 10,702**
   rows with exactly two values: `Diwali` and `Lunar New Year`. The mechanism is built and waiting;
   the field needs filling, LLM-proposed and human-approved, never decided at runtime.
3. **Clause O's 13-point checklist** is not yet a test. Several items are asserted by the audit above;
   turning the whole list into one runnable gate is the obvious next step.

---

## Verification

| Suite | Result |
|---|---|
| Module smoke | 12 / 12 |
| FC spec semantics | 189 / 189 |
| WFM diagnostics | 148 / 148 |
| UI render (Decision Cards) | 18 |
| **prompt2 render guard** | **28 / 28 over 2 payload shapes** |

All exit 0. Confidence and criticality unchanged throughout — SA Indonesia FW202716 still reports
`Medium 60.5%` / `Moderate`, as it has since before any of this work began.
