# Prompt — RCA Console architecture, for a business audience

Copy everything below the line. Facts verified against the running system on 2026-08-24.

**This replaces an earlier version of this prompt.** That one produced a diagram with six invented API
endpoints, an invented table name, an invented engine pipeline, and three invented AI capabilities
called "Web Search", "Spec Lookup" and "Forecaster Intent" — none of which exist anywhere in this
system. The cause was in the prompt, not the tool: it described components without **naming** them, so
the gaps got filled with whatever a typical AI application usually contains. Everything below is now
named explicitly, and there is a closed list of permitted boxes.

---

## AUDIENCE — read this first, it governs everything else

This diagram will be reviewed by a **business and executive team**. They are deciding whether to trust
and fund this system. They are not reviewing the code.

**Therefore, the following must NOT appear anywhere in the output:**

- line counts, file sizes, byte counts
- git branch names or commit hashes
- port numbers, driver versions, framework version numbers
- HTTP methods (GET/POST) or URL paths
- file names, function names, module names, class names
- phrases like "vanilla JS", "DOM string assembly", "grain normalization", "pyODBC", "JSON schema"
- anything of the form `No src="http"`

Those details belong in an engineering document. On an executive diagram they read as noise, and worse,
they invite exactly the question you do not want: *"why are you showing me this?"*

**What must appear instead:** what the system does, what it is built on in one line, where the data comes
from, how the answer is produced, why the answer can be trusted, and what it cannot do.

## HARD RULES

1. **Use only the components in the COMPONENT LIST below.** It is a closed list. If your diagram needs a
   box that is not on it — a queue, a cache, a broker, a search tool, a vector store, an agent — you
   have made an error. Stop and re-read the list.
2. **Invent nothing.** No capability, tool, table, model or step that is not named below. This is the
   failure the previous attempt made, and it is the one that destroys credibility in the room.
3. **Every number you use must come from the FIGURES section.** If you want a figure that is not there,
   write "not measured".
4. If anything below appears contradictory, **say so in a note** rather than resolving it silently.

## WHAT TO PRODUCE

1. **One diagram**, four bands top to bottom: *What the user does* → *What the system does* →
   *Where the data comes from* → *What guarantees the answer*. Label the bands in those words, not as
   "Layer 1/2/3/4" — a layer number tells a business reader nothing.
2. **A short narrative**, six to ten sentences, that a manager could read aloud.
3. **A "why you can trust this" panel** — the guardrails. Give this real space; it is the reason the
   system is defensible, and it is what an executive actually wants to know.
4. **A "what it cannot do" panel** — stated plainly, not hedged.
5. **A one-line value statement** at the top.

Keep it to one page. Prefer fewer, larger boxes over many small ones.

---

# COMPONENT LIST — the only boxes permitted

## Band 1 — what the user does

| Component | Say this about it |
|---|---|
| **The console** | A single web page. No installation, no plug-ins. It can also run entirely offline from a file, with no server, if someone just wants to check a week. |
| **The weekly list** | Every queue and week whose forecast missed by more than the agreed tolerance, ranked by how much the miss actually matters. |
| **Investigate** | The user picks one and asks why. One click. |
| **The result** | A structured card, organised into six tabs: **Decision · Calendar · Confidence & Recommendation · Statistics · Challenge · Reference**. |

## Band 2 — what the system does

| Component | Say this about it |
|---|---|
| **The analysis engine** | Reads the queue's own history, computes every figure, tests candidate explanations, rejects the ones the evidence does not support, and scores how confident it is. **All arithmetic happens here, in code — never by an AI.** |
| **Candidate explanations** | **23** of them, across six families: business change, calendar, demand behaviour, statistical artefact, data quality, and forecasting process. Every one is reported with its verdict and the reason — including the rejected ones. |
| **The challenge step** | Before confidence is scored, the conclusion is argued against. This deliberately runs first, so the challenge can lower the confidence rather than being an afterthought. |
| **Confidence scoring** | **Eight** weighted factors. The heaviest is *evidence that contradicts the conclusion*, at 20% — what argues against a finding counts for more than what argues for it. |
| **The written summary** | The only place AI is used. See the AI section below. |

## Band 3 — where the data comes from

| Component | Say this about it |
|---|---|
| **One SQL Server database** | A single source. No spreadsheets, no copies, no manual steps in between. **Read-only** — the system has no ability to change it. |
| **The forecast and actuals table** | Weekly figures per queue: what was planned, what actually arrived, the installed base, and shipments. |
| **The holiday calendar** | Public holidays by country and week, plus a curated mapping so one holiday spelled several ways is counted once rather than three times. |
| **The queue mapping** | So related queues are grouped the way the business groups them. |

For the diagram, the six kinds of question the system asks the database — describe them as questions,
not as queries:

1. *What has this queue done for the last three years?*
2. *What happened in the weeks straight after?* (so a recovery can be seen)
3. *Is this one queue's problem, or the whole region's?* (checked at six levels, from business
   organisation down to individual channel)
4. *Did the demand move to a different channel rather than disappear?*
5. *Which other queues belong with this one?*
6. *Was there a public holiday nobody accounted for?*

## Band 4 — what guarantees the answer

| Guarantee | Say this about it |
|---|---|
| **Every figure is computed, not judged** | Same input, same answer, every time. Two analysts can disagree; this cannot disagree with itself. |
| **The AI cannot introduce a number** | Any figure in the written summary that does not exist in the underlying analysis causes the **entire summary to be discarded**. Not flagged — discarded. |
| **The analysis does not depend on the AI** | If every AI call fails, the investigation still completes. Every figure, cause, confidence score and recommendation is present; only the prose is missing. |
| **It reports what it could not measure** | Where there is not enough history, it says so and says how much more it would need — it does not report a small number as "no effect". |
| **Small misses are set aside deliberately** | A 90% miss on twenty contacts is arithmetic, not a problem. Misses below a materiality floor are not put on the worklist, though they can still be investigated on request. |
| **Every figure is traceable** | Each finding names the field it came from. |

---

# THE AI SECTION — read carefully, this is what the previous attempt got wrong

**AI is used for wording only. It never produces a number, and it never decides a cause.**

There is **no web search. No browsing. No document lookup. No intent detection. No agent, and no
tools.** If any of those appear in your output, it is an invention — the previous attempt at this
diagram invented exactly those three and they do not exist.

### The models actually used

A **three-provider fallback chain**, in this order. If the first is unavailable the second is tried,
then the third:

| Order | Provider | Model |
|---|---|---|
| 1 | NVIDIA | Nemotron 3 Super 120B |
| 2 | Groq | Llama 3.3 70B Versatile |
| 3 | Google | Gemini 3.6 Flash |

A user can also pick from **nine** models directly, to compare how different models word the same
finding. The analysis underneath is identical whichever is chosen — only the prose changes.

### The calls, and there are up to five — not three

This is the part to draw carefully, and the previous attempt showed it wrongly as "three calls in
parallel". They are **sequential**, and most are optional.

| # | Call | When | Purpose |
|---|---|---|---|
| 1 | **Narrative** | every investigation | writes the executive summary over figures that are already final |
| 2 | **Interrogation — questions** | when the interrogation is enabled | generates the sceptical questions a reviewer would ask of the findings |
| 3 | **Interrogation — repair** | only if call 2 returns something malformed | one retry |
| 4 | **Interrogation — answers** | when the interrogation is enabled | answers those questions **from the evidence file only**, never from the model's own knowledge |
| 5 | **Summary** | only when a user clicks *Summarise* | a short paragraph for someone who will not read the full card. Cached, so a second reader pays nothing |

So the interrogation is a **two-stage exchange** — ask, then answer — with a repair attempt in between
if needed. Show it that way; a single "interrogation" box loses the point, which is that the questions
and the answers are produced separately and the answers are constrained to the evidence.

Call 5 is deliberately **not** given the output of calls 1–4. Summarising a summary would let a mistake
made in the first paragraph return as established fact in the one most likely to be forwarded onward.

### Settings

Temperature zero, fixed seed. Asked twice, the same investigation produces the same words.

---

# FIGURES — the only numbers you may use

## Scale of the problem

| | |
|---|---|
| Queues covered | **427**, across **49 countries**, **3 regions**, **5 channels** |
| History | just over **five years** of weekly data |
| Queue-weeks with a scoreable forecast | **71,780** — about **400 every week** |
| Missing by more than the tolerance band | **44,883**, which is **63%** |
| Large enough in absolute terms to act on | **21,788** |
| Set aside as immaterial | **23,095** |
| Contacts handled, across the whole file | **60.3 million** |
| Contacts planned | **78.6 million** |

The single most useful framing: *sixty-three percent of forecasts miss the band, and nobody can
investigate forty-four thousand of anything. The system's first act is to decide which twenty-two
thousand are worth a person's time.*

## A real worked example — use this, do not invent one

A United States social-media queue, one week in 2024:

| | |
|---|---|
| Planned | **18,932** contacts |
| Actually arrived | **25,697** contacts |
| Shortfall | **6,765** contacts, **35.7%** under-forecast |
| Business impact | **Critical** |
| Cause identified | a drifting forecast baseline |
| Confidence | **67.5%** |
| Explanations tested | **23** |

The finding worth quoting: *the evidence available before that week implied the plan should have moved
by 1,241 contacts. It moved by 77.* The signal existed and the plan did not respond to it.

## What it cannot do — state these plainly

1. **No daily detail.** The source records whole weeks. It also has seven columns named after the days
   of the week, but those only mark *whether a holiday fell on that day* — they are not daily volumes.
   The system therefore says weekend effects cannot be separated from a weekly total, rather than
   estimating them. Getting daily analysis would require a new data feed.
2. **Promotions and campaigns cannot be tested as causes.** The business event repository is not
   deployed, so that explanation is correctly reported as not-applicable rather than counted against
   the confidence score.
3. **185 holiday naming questions are unresolved.** Where two holidays fall on the same date, deciding
   whether they are one event or two is a business judgement. They are recorded and awaiting an answer,
   not guessed at.
4. **It does not prove causation.** It reports what the evidence supports and how strongly. The wording
   throughout is deliberately "the evidence supports", never "this caused".
5. **The judgement stays with the analyst.** This produces the evidence; a person still decides.

---

# CLOSING GUIDANCE

The strongest thing about this system is not that it is fast. It is that **it is built so that it cannot
bluff** — the arithmetic is in code, the AI cannot introduce a figure, and the system states its own
limits on screen. Build the diagram so that a sceptical executive reaches that conclusion without being
told it.

If you find yourself with empty space, add nothing. A sparse accurate diagram beats a full one with an
invented box in it.
