# `test3` — what was built, 2026-08-18

Everything done on this branch in one session, with the reasoning, the figures, and the mistakes.
Detail per spec lives in `new-prompt-conformance.md` and `prompt2-conformance.md`; this is the record
of the whole thing.

**Nothing is committed.** All of it sits in the `test3` working tree.

| | |
|---|---|
| Branch | `test3`, forked from `test2` at `5b1cdf7` |
| Worktree | `…/rca patternz/test3` — separate folder, so `test2` was never disturbed |
| Port | **9400** (`test2` keeps 8000) |
| Code changed | **1,517 insertions / 115 deletions** across 11 files |
| Suites | 12/12 · 189/189 · 148/148 · 18 cards · 28/28 render — all exit 0 |
| Confidence invariant | SA Indonesia FW202716 `Medium 60.5%` / `Moderate` — **unmoved from first edit to last** |

---

## 1. The branch, and the port

`test3` was created as a **separate git worktree** rather than by switching the existing folder,
because a colleague was committing to `test2` in that directory and a server was live from it.
Switching branches underneath a running process is what caused a day of confusion earlier in the
week — the console HTML was read fresh from disk while the Python engine stayed in memory, so the app
was half-reverted and looked broken.

Five files were deliberately excluded and confirmed **never committed to any branch**, so they cannot
reappear on a merge: `EXECUTIVE_BRIEFING.md`, `PROJECT_DEEP_DIVE.md`, `check_playground_tables.sql`,
`sys22.py`, `where_am_i.sql`. Keeping `sys22.py` out matters — it carries plaintext SQL credentials.

Two gitignored runtime files were copied by hand because git cannot carry them: `backend/config.json`
and `backend/.env`.

**The port moved to 9400** across 16 files — `run.py`, the four launchers, `docker-compose.yml`,
`Dockerfile`, `sql_backend.py`, `rca_console.html` including its four `file://` API fallbacks, two
`results/` scripts, and six instructional docs. All together, because the UI branch changed this port
once before and then needed a follow-up commit to chase the references it had orphaned.

Deliberately left on 8000: recorded canary evidence, `results/audit-log.md`, and the incident notes in
IMP_DOCS. Those describe runs that really happened on 8000 — rewriting them would make the record
false. And `smoke_test_modules.py`'s four `8000`s are **contact volumes, not a port**; a blind
substitution would have corrupted a test fixture.

`run.py`'s banner now reads the live branch from git instead of hardcoding the one it was written on:

```
Demand Pattern RCA Console - test3   (port 9400)
```

**Why the port move was needed at all:** `run.py` frees its port by *killing whatever holds it*. Run
from test3 with the old default, it silently killed the test2 server (PID 7008). Both now coexist.

---

## 2. `new_prompt.md` — eight items

Audited first, which was the right call: **23 of 33 checks already passed.** Five of the seven
"enrichments" the document asked for were already built, and rebuilding them would have been the
expensive mistake.

| # | Clause | What was done |
|---|---|---|
| 1 | §17 | Driver rejection no longer asserts absence; **and the lag analysis was made reachable** |
| 2 | §27 | `CAUSAL_VERBS` + `causal_verbs_in()`, separate from `EXEC_JARGON` |
| 3 | §9 | `phase_transitions()` — the week-on-week rebound, separated from level-vs-baseline |
| 4 | §10 | `repeatability()` — the five named bands |
| 5 | §12 | `holiday_weekend_interaction()` |
| 6 | §15 | Three failure-type refinements + the 7→8 vocabulary mapping |
| 7 | §16 | Pearson beside Spearman; relationship during **miss weeks** |
| 8 | §28 | The A–F view over the intact 18 sections |

### The two that changed what a reader concludes

**§17 was violated word for word.** The gate published *"planned units for delivery does not track
this queue's demand (r=−0.22 over 155 weeks)"* — asserting **absence** from a sub-threshold
coefficient, throwing away the direction, and labelling it `NotApplicable`, which in this engine means
"never relevant". It now reports strength, direction, sample and lags scanned, and lands on **NOT
CONFIRMED — "a weaker claim than absent"**.

**And §16's machinery was unreachable.** The gate rejects the drivers → no Business hypothesis fires →
nothing requests the lag test. All three audited queues reported *"nothing was tested"*. Lags
0/1/2/4/8 on level and change, half-history stability, three coverage states — well built, never run.
Gate results now travel into the lag evidence as enrichment, marked `feeds_confidence: False`,
`feeds_hypotheses: False`, `changes_the_gate_verdict: False`. It cannot promote a driver.

### Findings that fell out of the work

**§9 reproduced the spec's own worked example** from live data: *"58.33% post-holiday rebound from
FW202715 (96.0 contacts) to FW202716 (152.0)."* And it showed why the ban matters — the holiday phase
runs **2.24% below** baseline while the move into the target week is **+58% up**. Calling that a
"holiday effect" inverts the meaning; it is recovery from a trough.

**§10 discriminates.** Indonesia's post-holiday rebound is `EMERGING / INCONSISTENT` (65.4% over 26
instances) and carries *"should not be applied as a fixed adjustment"* — the engine stating its own
uncertainty on the exact conclusion the earlier validation disproved. Brazil lands `MODERATELY
REPEATABLE` at 80%.

**§6's hard case already worked:** `row_holiday_count=0` **and** `phase=post_holiday`, with
`offset_weeks=[-1,1,2]`.

**§16 turned up something that challenges an existing rule.** SA Indonesia's `Actual_ASU` reaches rank
**0.50 at a 2-week lag** — exactly `MIN_STRENGTH`, the engine's own evidence bar — while the gate
rejected it at r=+0.18 because ASU is classed a *stock* measure and tested contemporaneously only.
That rule was set from measured evidence across many queues, so one counter-example does not overturn
it. **Recorded for the rule's owner, not changed.**

**And §16's miss-week test is the more valuable half:** Brazil's `Holiday_Count` holds at **−0.66
across 108 miss weeks**, while `Final_Units` collapses from −0.21 to −0.08. One explains the weeks that
actually missed; the other explains ordinary weeks. Invisible before.

### How §1 was honoured

Every item is additive. The three that could have moved confidence were deliberately routed around it:

- **§15** became *refinements* rather than new mechanism candidates, because candidates feed
  `MECHANISM_HYPOTHESES` → `rejected_ids` → the `ModelAgreement` dimension.
- **§16**'s Pearson is informational; `relationship_strength` stays Spearman, so `strong_enough`,
  `_best` and `usable_as_evidence` are untouched.
- **§17**'s gate *decision* is unchanged — only the sentence and the added fields.

---

## 3. The gap you found

After declaring §1–§8 done, you reported the page still showing *"Weekend impact cannot be
isolated…"* and *"no business hypothesis was generated…"* and nothing else.

**You were right and I had missed two whole layers.** I verified the new evidence reached the API
response and stopped there. It did not reach the screen, for three separate reasons:

1. `calendar_panel()` and `driver_panel()` **explicitly filter** which fields enter card sections 14
   and 15. Neither was widened, so the response carried `phase_transition`,
   `rebound_repeatability`, `holiday_weekend_interaction` and `enrichment` and the card dropped all
   four.
2. `cardDriverPanel()` **early-returns** on `!available` and prints the reason alone — so even once
   the panel carried the enrichment, the renderer bailed before reaching it.
3. Nothing rendered the rebound or the band at all.

This is the **compute-then-discard** pattern this project keeps hitting, one layer further out: the
measurement existed and the panel threw it away. The lesson — *follow the data to the screen* —
changed how the next phase was built and tested.

---

## 4. `prompt2.md` — six clauses

A different document: `new_prompt` asked for more analysis, `prompt2` governs **what the analysis may
claim** from a weekly-grain source. Mostly prohibitive.

Opening audit `OK 7 · PARTIAL 3 · GAP 6` → **`OK 16`** on the holiday queue.

**Clause F is the only clause in either document that calls itself mandatory, and it was the thing
actually wrong.** One `names` list mixed in-week and adjacent holidays, so Indonesia showed four
holidays together while `Holiday_Count` was 0 and none fell inside the week. That is the
Ascension / Idul Fitri / Waisak confusion, at source. Now:

> **Holidays in this week: None.**
> Recent holidays potentially affecting this week: Ascension of Jesus Christ, Idul Fitri Holiday,
> Joint Holiday for Waisak Day. No holiday occurs directly in this fiscal week; the analysis therefore
> evaluates whether this week resembles a historical post-holiday or pre-holiday pattern.

**Clause K supersedes my own §12 work.** Per-weekday, from the holiday **date** rather than the row
flags:

| Holiday fell on | Indonesia | Brazil |
|---|---|---|
| Mon–Fri | −13% to −42% | −29% to −42% |
| **Sat / Sun** | **+4.5% / −8.1%** | **−14.0% / −3.0%** |
| spread | **46.8 pts** | **38.6 pts** |

§12's grouping reported only **9.5 points**, because "adjoining" averaged Friday (−24.8%) with Monday
(−13.1%) and "midweek" averaged Tuesday (−42.3%) with Thursday (−24.8%). Weekend holidays barely move
the week — they land on days already non-working — and that replicated on two unrelated queues in
different regions. Nobody told the code; it fell out of the data.

Also: **E** canonical display grouped by `semantic_group_id` (raw 4 → displayed 3) · **B/D** weekday
from the date, Friday (`before_weekend`) finally distinct from Monday (`after_weekend`) · **C** three
weekend states instead of one refusal, with the limitation sentence kept because it is true ·
**M** prompt2's five states mapped alongside the engine's own, since those feed confidence.

### The check that was missing

`results/check_prompt2_render.js` renders the panel in a VM and greps the **HTML** — because verifying
JSON does not answer "does the reader see it". Assertions are **conditional on the payload**, since
clause F is conditional by design; an unconditional version failed on both test queues for opposite
reasons. **28/28** across two payload shapes. Panel and renderer were widened in the same pass this
time.

Audited across three queue shapes, which is what gives confidence it generalises:

| Queue | Shape | Result |
|---|---|---|
| SA Indonesia FW202716 | adjacent only, `Holiday_Count=0` | **OK 16** |
| Canada Core French FW202722 | holiday **inside** the week | **OK 15 · PARTIAL 1** |
| Brazil CEM FW202722 | no holiday in window | **OK 11 · n/a-here 5** |

Canada's PARTIAL is honest — only 3 of 7 weekdays clear the 4-week sample floor there. Brazil's
`n/a-here` means nothing to test, not a gap.

---

## 5. Analysis that produced findings, not code

### Can holiday names be matched deterministically?

Measured, because you asked whether an LLM is genuinely required. Deterministic pre-filter first —
same country, same date, which is the constraint clause E already imposes:

```
9,104 (country,date) slots  ->  509 with more than one name  ->  276 name pairs to adjudicate
```

Of those 276, a rule decides **23.2%** (shared token, containment, near-identical spelling).
**76.8% need knowledge outside the strings.**

**But the more important finding is that the hard pairs are two different problems.** Same holiday,
different name — `Boxing Day` ↔ `St.Stephen's Day`, `Labor Day` ↔ `May Day`, `Ashoora` ↔ `Ashura`,
`Mouloud` ↔ `Prophet Mohamed's Birthday` — is your Diwali/Deepavali case. But roughly half are
genuinely **different holidays sharing a date**: `Christmas Day` ↔ `Quaid-e-Azam Day` (Pakistan,
Dec 25), `Annunciation of the Virgin Mary` ↔ `Greek Independence Day` (Mar 25), `Qing Ming Festival` ↔
`childrens day` (Taiwan, Apr 4).

So same-country-same-date is **necessary but nowhere near sufficient**, and a rule that merged
co-occurring names would fold Christmas into Quaid-e-Azam Day, halve the holiday count and corrupt
every phase effect downstream. The task is not "merge" — it is "decide: one event or two", and the
answer is frequently two.

The pre-filter does earn its place: `Lab(o)ur Day` spans **five months**, and after filtering only
**3** pairs survive, all on `2022-05-01` in one country. The September-Canada / May-Thailand
cross-contamination is killed deterministically.

**And the field for this already exists.** The runtime JSON carries `semantic_family` on all 10,702
rows, populated on **99** — with exactly two values: **`Diwali`** and **`Lunar New Year`**. Someone
started this work on your example and stopped. The merge key already prefers that field when present,
so nothing new is needed architecturally.

**Recommendation, unbuilt:** LLM *proposes*, human *approves*, engine reads a **frozen** table. Never
a model at runtime — that would put a non-deterministic component in the measurement path. 276 pairs
is a one-time reviewable job. Bias should be explicit: **when unsure, do not merge** — failing to merge
Diwali/Deepavali inflates an event count; wrongly merging Christmas corrupts the measurement, quietly.

### Merging, as it stands

Enabled and working. All three Ascension spellings collapse to `ascension+christ+jesus`; bridge days
(`joint:waisak`) stay separate from their anchor; no Waisak/Vesak transliteration is invented. It
correctly **declined** to merge the two Ascension entries on Indonesia because they fall on different
dates — 2026-05-14 in FW202715 and 2026-05-27/28/29 in FW202717 — which clause E forbids merging. Both
are already flagged `needs_review`.

**A correction to something I told you earlier:** I said those two were "the same day, spelled two
ways". They are not — they are the same holiday **double-dated** in `Holiday_Master`. The fix belongs
at source, not in normalisation, and my earlier framing would have sent you looking in the wrong place.

---

## 6. Mistakes I made, and how they were caught

Recorded because the pattern is informative: every one was caught by testing against live data or by
edge cases, and **not one by the existing suites**.

| Mistake | Caught by |
|---|---|
| First audit reported 13 MISSING — 3 were false, wrong key names (`phases` vs `phase`) | reading the live payload |
| Same audit treated *not tested* as *not present* — the exact confusion §17 forbids | re-reading the spec |
| §17 enrichment read `best`, which is only set above `MIN_STRENGTH` 0.5 — always `None` for the weak drivers it exists for | live output showing empty |
| `\b` written through two layers of quoting became a literal **backspace** in the file | unit test returning `[]` |
| `_phase_of` returns a **tuple**; comparing it to a phase constant is always false → zero transitions found | live output showing 0 on a queue that plainly has one |
| `_rows()` excludes the target week, so the target actual must be passed in | same |
| §15 read `baselines["target_forecast"]`, which does not exist | checking the payload before trusting it |
| A–F view took a `header` arg; `build()` has no such local → runtime `NameError` on every card | reading `build()` before applying |
| `repeatability()` narrated a flat history as *"flat … and close to a coin flip"* | edge-case sweep |
| Six audit checks went stale after the build and under-reported | re-running the audit and disbelieving it |
| **Verified the response and never checked the screen** | **you** |

The last one is the significant one. An independent reviewer was launched to check the eight edits
adversarially and **died on a spend limit before reporting**, so its edge-case plan was run by hand
instead — which found the flat-history defect. The work has not been independently reviewed.

---

## 7. Verification

| | |
|---|---|
| Module smoke | 12 / 12 |
| FC spec semantics | 189 / 189 |
| WFM diagnostics | 148 / 148 |
| UI render, Decision Cards | 18 |
| prompt2 render guard | 28 / 28 over 2 payload shapes |
| `new_prompt` conformance | **34 / 34 PRESENT** |
| `prompt2` conformance | **16 / 16 OK** on the holiday queue |

Re-run, all zero-token (empty `llm_cfg`, `interrogate=False`):

```
python results/audit_new_prompt_conformance.py
python results/audit_prompt2_conformance.py
node   results/check_prompt2_render.js <live-response.json>
```

End-to-end through HTTP on 9400 with a real narrative: `status=Complete`, card 2.1.0, 18 sections,
confidence `Medium 60.5%`, criticality `Moderate`.

---

## 8. Still open

1. **`fc_evidence.py` is overloaded** — FC adapter, criticality, ASU split, mechanisms, direction gate,
   resolution, evidence index, and now six more concerns. It wants splitting. Not done because
   restructuring it mid-task was the breakage risk to avoid.
2. **The suites never ask whether a conclusion is RIGHT.** All 189 FC checks passed through every
   defect found this week, including the holiday conclusion that pointed the wrong way. A test
   asserting that a conclusion agrees with the direction of the miss would be worth more than any
   remaining spec item.
3. **Semantic holiday merging** — §5 above. A decision and a review job, not engineering.
4. **The Holiday Master as a first-class joined dataset** — prompt2's closing note is right that this
   removes most of the remaining confusion at source. A data-pipeline decision.
5. **The ASU stock-lag rule** — §2 above. For the rule's owner.
6. **The 24th catalogue entry** is still the right long-term fix for the plan-level cause; §15's
   refinement only routes around it.
7. **Two lag vocabularies coexist** — `lag_analysis.LAGS = (0,1,2,4,8)` and the gate's `0..13` scan.
8. **Clause O's 13-point checklist** is not yet one runnable gate.
9. **No independent review** — see §6.

---

## 9. File inventory

**Engine (1,517 insertions / 115 deletions):**

| File | + |
|---|---|
| `backend/wfm/fc_evidence.py` | 518 |
| `backend/wfm/holiday_response.py` | 363 |
| `backend/wfm/decision_card.py` | 196 |
| `rca_console.html` | 155 |
| `backend/wfm/lag_analysis.py` | 98 |
| `backend/wfm/driver_gate.py` | 59 |
| `backend/wfm/holiday_events.py` | 46 |
| `backend/wfm/spec_engine.py`, `backend/sql_backend.py` | 8 each |

**New files:** `IMP_DOCS/new-prompt-conformance.md` · `IMP_DOCS/prompt2-conformance.md` ·
`IMP_DOCS/test3-build-record.md` (this) · `results/audit_new_prompt_conformance.py` ·
`results/audit_prompt2_conformance.py` · `results/check_prompt2_render.js` · two conformance JSONs.

**Port move:** `run.py`, `run.bat`, `run.ps1`, `run.sh`, `docker-compose.yml`, `backend/Dockerfile`,
`AGENTS.md`, `CLAUDE.md`, `DEPLOY.md`, `backend/README.md`, `results/README.md`,
`IMP_DOCS/installation-and-connection.md`, `results/run_validation.py`, `results/run_llm_ranking.py`.

**Running now:** http://localhost:9400/rca_console.html — hard-refresh, the HTML is served from disk.
