# The whole workflow, end to end

What happens between clicking **Run agents** and reading the answer. Written to be read by
someone who has not seen the code.

The short version: **one Structured Query Language database, thirty-three calculation modules,
then four language-model calls in a fixed order, with automatic checks between them.** Every
number is calculated before any model is called. The models write sentences around numbers they
were handed; they never compute and never query the database.

---

## Is there agent-to-agent communication? No — and that is deliberate

This is the question that gets asked most, so it goes first, and the answer is not the
fashionable one.

**No agent ever sends a message to another agent.** There is no conversation, no negotiation, no
"agents discussing until they converge". No agent can invoke another one. If you search the code
for one role calling another, you will not find it, because the roles do not know each other
exists.

What exists instead is a **blackboard**. A single shared object (`AgentState`, in
`backend/agents/state.py`) holds everything known about the investigation. An orchestrator
(`graph.run`, in `backend/agents/graph.py`) calls each role in turn. Each role reads a
**declared slice** of that shared object — never the whole thing, never another role's private
reasoning — and writes its own result back.

So the flow is not a conversation between peers. It is a production line where each station is
told exactly what it may look at.

### What each role is allowed to see

This is enforced in code by four separate methods, not by asking the model politely.

| Role | Sees | Deliberately does **not** see |
|---|---|---|
| **Analyst** | The evidence slice, the queue, the week, the headline | Anything from any other role — it goes first |
| **Challenger** | The **same** evidence slice, plus the Analyst's mechanism, claim, magnitude and confidence | Nothing extra. Identical evidence is the point |
| **Editor** | The Analyst's finding and the Challenger's finding | **The raw evidence.** Withheld on purpose |
| **Judge** | The written report, and the two findings it came from | The raw evidence |

Two of those restrictions are load-bearing and worth explaining.

**The Challenger gets identical evidence.** A challenger given *different* evidence produces
disagreements that are artefacts of what it happened to be shown, not of reasoning. That is
worse than having no challenger at all, because the disagreement looks meaningful and is not.

**The Editor is denied the evidence.** Its job is ordering and compression, nothing else. An
editor that can see the underlying figures starts doing analysis of its own, and that is exactly
how a report ends up asserting something neither the Analyst nor the Challenger ever said.
Taking the evidence away removes the temptation rather than forbidding it in a prompt.

### Why a blackboard rather than a conversation

Three reasons, in order of how much they matter.

1. **Cost is bounded.** Four calls, each with a declared token ceiling. A conversation that runs
   until agents agree has no ceiling — it costs whatever it costs, and you find out afterwards.
2. **It is reproducible.** Same input, same order, same declared reads. A free-form exchange
   between models is not reproducible, and an explanation of a forecast miss that cannot be
   reproduced is not evidence of anything.
3. **Failures are attributable.** When the output is wrong you can point at one station. In a
   conversation, a bad conclusion is smeared across a dozen turns and nobody can say where it
   entered.

There is exactly **one** feedback edge in the whole system: if the Judge raises a blocking
problem, the Editor rewrites **once**, and the Judge re-checks. Once — never "until the judge is
satisfied". An unbounded quality loop is how a system that costs pennies becomes one that costs
pounds, silently.

---

## The full trace

```
  [1]  Structured Query Language database
       dbo.Input_To_ML_Full_138_Trimmed   forecasts and actuals
       dbo.CQN_Mapping                    which queues are peers
       dbo.Holiday_Master                 which weeks contain a holiday
                    │
                    ▼
  [2]  33 deterministic calculation modules          no model involved
       adherence, accuracy, trend, peer comparison,
       holiday phase, prior-year holiday lookup
                    │
                    │   result: one finding object, ~279,500 characters
                    ▼
  [3]  scope extractor           declared fields only
                    │
                    │   result: ~3,200 characters. About 1.1% of the finding.
                    ▼
  [4]  ANALYST          names ONE mechanism from a closed list of six,
                        and says how much of the gap it accounts for
                    │
                    ▼
       automatic checks     circular claim? ungrounded number? invalid mechanism?
                    │
                    ▼
  [5]  CHALLENGER      same evidence + the Analyst's claim.
                        must raise a typed objection and quote its figure
                    │
                    ▼
       automatic checks     objection typed? figure actually cited?
                    │
                    ▼
  [6]  EDITOR          both findings, no raw evidence.
                        five fields, hard word budget
                    │
                    ▼
       automatic checks     over budget? number not in the permitted set?
                    │
                    ▼
  [7]  JUDGE           scores the report against five factors
                    │
         ┌──────────┴──────────┐
         ▼                     ▼
     nothing blocking     something blocking
       publish            ONE Editor rewrite, Judge re-checks, then publish
                          with the note attached
```

### Step 1 and 2 — the figures

The database is read, and thirty-three modules compute everything: adherence, accuracy, the
trend across up to one hundred and four weeks, how peer queues in the same grouping behaved that
week, whether a holiday falls in the week, and what the same holiday *by name* did in earlier
years. Holidays drift across fiscal weeks, so "the same week last year" is not the same thing as
"the same holiday last year" — the lookup is by name for exactly that reason.

Nothing here involves a language model. On the measured run this took **0.67 seconds**.

### Step 3 — the scope extractor, and why it exists

The finding object is about 279,500 characters. Handing that to a model was the original
mistake: the earlier engine passed the whole object to its narrative call and got back text that
contradicted itself between sections, because 86,000 tokens of context gives a model far too
many ways to be locally plausible and globally wrong.

The extractor pulls roughly twenty named fields, about 3,200 characters — **1.1 percent**. It
also builds the set of figures the models are permitted to write. Any number appearing in the
prose that is not in that set is flagged automatically.

### Steps 4 to 7 — the four roles

**Analyst.** Must choose exactly one mechanism: a holiday or calendar event; a business driver
moving; demand trending while the plan stayed flat; a standing bias in the plan; a possible data
problem; or *the figures do not settle it*. That last option is a respectable answer and the
prompt says so, because a manufactured cause is worse than an honest shrug.

It must also state how much of the gap the mechanism accounts for, and whether that is enough.
This is the part that makes the claim checkable. "The forecast under-predicted demand because of
forecast bias" is circular — an under-forecast *is* a bias — and a Challenger handed a circular
claim has nothing to test. That failure is caught in code, not left to the prompt: a list of
circular phrasings is checked against the claim and flagged.

**Challenger.** Must raise one of four typed objections, and cite the figure it relies on:
too small to explain a gap this size; another explanation fits better; the figures do not show
this; too few weeks to say. Rounding nitpicks are discarded. Given a different model family it
disagrees more readily than it does echoing its own family.

**Editor.** Five fields — what happened, why, how sure, what to do, what was not checked —
inside a hard word budget. On the measured run the output was **66 words**. The comparable
section of the old decision card ran to about 26,000.

**Judge.** Five factors: does the report contradict itself; does the confidence match the
hedging; does the recommendation follow from the cause; is it readable in thirty seconds; is it
faithful to what the two findings actually said. A factor scored without a supporting quote is
discarded rather than trusted.

---

## What it costs

Measured on `Social Media English Basic`, fiscal week 202637 — a forecast of 16,423 against an
actual of 30,444, a gap of 14,021 contacts, adherence −85.4 percent.

| | Old decision card | This |
|---|---|---|
| Words of output | ~26,000 | **66** |
| Tokens consumed | ~180,000 | **9,874** |
| Seconds | ~311 | **8.7** plus 0.67 for the figures |
| Calls to a model | many | 4 |

On that run the Challenger genuinely dissented — objection type *unsupported*, on the grounds
that naming "Forecast Bias" as a root cause carries no quantitative link to the full 14,021
gap — all five Judge factors passed, and the circular-claim check correctly fired against the
Analyst's wording.

---

## Where to look in the code

| File | What it holds |
|---|---|
| `backend/agents/state.py` | The blackboard, and the four declared read scopes |
| `backend/agents/graph.py` | The fixed order and the single bounded revision |
| `backend/agents/nodes.py` | The four prompts, and the automatic checks |
| `backend/agents/models.py` | Which model fills which role, and the retired-model list |
| `backend/agents/run_agents.py` | The scope extractor |
| `backend/agents/server.py` | The web interface, including `/api/sources` |

## One honest note on the name

The branch this grew from was called `test3_langraph`, and **LangGraph is not used**. It was
evaluated and not adopted: the whole orchestration is about eighty lines of ordinary Python, and
a framework would have added a dependency and a layer of indirection without removing any of
those lines. The structure is deliberately the shape LangGraph wants — one typed state object,
stations that take it and return an update — so adopting it later is mechanical rather than a
rewrite. Nothing here is blocked on that decision.
