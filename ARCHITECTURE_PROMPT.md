# Prompt — RCA Console architecture (one page, business audience)

Copy everything below the line. Every fact verified against the running system on 2026-08-24 —
**54 claims checked, all correct** (see `results/verify_architecture_prompt.py`).

---

# TASK

Draw **one page**: the architecture of the **RCA Console**, a tool that explains why a contact-centre
forecast missed.

# AUDIENCE

A **business and executive team** deciding whether to trust this system. They are not reviewing code.

**Never show:** line counts · file sizes · git branches or commits · port numbers · version numbers ·
URL paths · HTTP methods · file, function or module names · `pyODBC` · `vanilla JS` · `JSON schema` ·
`grain normalization` · anything shaped like `No src="http"`.

Those read as noise to this audience and invite the one question you don't want: *"why are you showing
me this?"*

# THE ONE-PAGE DISCIPLINE — this is the hard part

The previous attempt at this diagram failed by being **cluttered**: forty-plus boxes, an endpoint table,
and icon rows nobody reads. Treat these as limits, not suggestions:

- **Four bands. Maximum five boxes per band. Twenty boxes total, absolute ceiling.**
- **No tables inside the diagram.** Tables are for documents, not one-pagers.
- **No icon rows.** One icon per band at most, or none.
- **Three colours plus grey.** Nothing else.
- **If a box needs more than twelve words, cut the box or cut the words.**
- **Leave white space.** If you have room left over, add nothing. A sparse accurate page beats a full
  one with an invented box in it.

Label the bands in these words — not "Layer 1/2/3/4", which tells a business reader nothing:

> **What the user does** → **How the answer is produced** → **Where the data comes from** →
> **Why the answer can be trusted**

# HARD RULES

1. **Closed component list.** Use only what is named below. If your diagram needs a box that is not
   there — a queue, a cache, a broker, a search tool, a vector database, an agent — **you have made an
   error.** Re-read the list.
2. **Invent nothing.** The previous attempt invented six API endpoints, a table name, an engine
   pipeline, and three AI capabilities called "Web Search", "Spec Lookup" and "Forecaster Intent". None
   of those exist. Verified: they appear in **zero files**.
3. **Every number must come from the FIGURES section.** No estimates.

---

# BAND 1 — What the user does

- **One web page.** No installation. Opens in a browser, and can also run entirely offline from a file
  with no server at all.
- **A ranked weekly list** of every queue whose forecast missed beyond tolerance, ordered by how much
  the miss actually matters — not by percentage.
- **One click to investigate.**
- **The answer**, as a card in six tabs: Decision · Calendar · Confidence & Recommendation ·
  Statistics · Challenge · Reference.

# BAND 2 — How the answer is produced

- **The analysis engine.** Computes every figure in code. **No AI is involved in any number or any
  cause.**
- **23 candidate explanations** across six families — business change, calendar, demand behaviour,
  statistical artefact, data quality, forecasting process. Each is reported with its verdict and reason,
  **including the ones rejected.**
- **A challenge step that runs before confidence is scored**, so arguing against the conclusion can
  actually lower the score rather than being an afterthought.
- **Confidence from eight weighted factors.** The heaviest, at **20%**, is *evidence that contradicts
  the conclusion* — what argues against a finding counts for more than what argues for it.
- **AI writes the wording only** (see the AI band).

# BAND 3 — Where the data comes from

- **One SQL Server database, read-only.** A single source; no spreadsheets, no copies, no manual steps.
  The system cannot change it.
- **Weekly forecast and actuals per queue**, plus installed base and shipments.
- **A public-holiday calendar**, with a curated mapping so one holiday spelled several ways counts once
  rather than three times.

Show the database access as the **six questions** the system asks — as questions, not queries:

1. What has this queue done for the last three years?
2. What happened in the weeks straight after? *(so a recovery is visible)*
3. Is this one queue's problem, or the whole region's? *(checked at six levels, business organisation
   down to channel)*
4. Did demand move to a different channel rather than disappear?
5. Which other queues belong with this one?
6. Was there a public holiday nobody accounted for?

# BAND 4 — Why the answer can be trusted

Give this band real weight. It is the reason the system is defensible.

- **Every figure is computed, not judged.** Same input, same answer, every time.
- **The AI cannot introduce a number.** Any figure in the written summary that isn't in the underlying
  analysis causes the **entire summary to be discarded** — not flagged, discarded.
- **The analysis never depends on the AI.** If every AI call fails, the investigation still completes:
  every figure, cause, confidence score and recommendation present, only the prose missing.
- **It states what it could not measure**, and how much more data it would need — rather than reporting
  a thin result as "no effect".
- **Small misses are set aside on purpose.** A 90% miss on twenty contacts is arithmetic, not a problem.
- **Every finding names the field it came from.**

---

# THE AI — the part the last attempt got wrong

**AI is used for wording only. It never produces a number and never decides a cause.**

There is **no web search, no browsing, no document lookup, no intent detection, no agent and no tools.**
If any of those appear, it is invented.

**Models — a three-provider fallback chain.** If the first is unavailable the next is tried:

> NVIDIA Nemotron 3 Super 120B → Groq Llama 3.3 70B → Google Gemini 3.6 Flash

A user can also pick from **nine** models to compare wording. The analysis underneath is identical
whichever is chosen.

**The calls are sequential and every one is optional.** Do not draw them as parallel — the last attempt
did, and it is wrong. On a normal run there are **four**:

| Order | Call | If it fails |
|---|---|---|
| 1 | **Plain-language rewrite** of the reasoning chain | the plainer wording is skipped; the original stands |
| 2 | **Narrative** — the executive summary, over figures already final | status reads *Incomplete*; every figure remains |
| 3 | **Interrogation, part one** — generates the sceptical questions a reviewer would ask | the interrogation is omitted |
| 4 | **Interrogation, part two** — answers them **from the evidence file only**, never from the model's own knowledge | as above |

Plus, when they occur:

- **a retry** — the narrative retries once if it comes back malformed, and the interrogation has one
  repair attempt
- **a summary** — only when a user clicks *Summarise*. Cached, so a second reader pays nothing. It is
  deliberately **not** given the output of calls 1–4: summarising a summary would let a mistake in the
  first paragraph return as established fact in the one most likely to be forwarded on.

**The interrogation is a two-stage exchange — ask, then answer.** Draw it as two, not one. That the
questions and the answers are produced separately, and the answers are constrained to the evidence, is
the whole point of it.

**Settings:** temperature zero, fixed seed. Asked twice, the same investigation yields the same words.

---

# WHAT IT IS BUILT ON — one line in the diagram, no more

Python service (FastAPI) reading SQL Server directly, and a single self-contained web page.

Worth one short sentence somewhere on the page, because it is unusually defensible:

> **Four dependencies in total.** No data-science stack — no pandas, no NumPy, no SciPy, no machine
> learning framework. Every statistic is written out in plain code on Python's own standard library, so
> any figure can be read and checked. The AI providers are called over standard web requests with **no
> vendor SDK**, so no provider is locked in.

Do not list the four by name on the diagram. It is the *absence* of a heavy stack that matters, not the
inventory.

---

# FIGURES — the only numbers permitted

**Scale**

- **427 queues** · **49 countries** · **3 regions** · **5 channels**
- Just over **five years** of weekly history
- **71,780** queue-weeks with a scoreable forecast — about **400 a week**
- **44,883** missed beyond tolerance — **63%**
- **21,788** large enough to act on · **23,095** set aside as immaterial
- **60.3 million** contacts handled against **78.6 million** planned

The framing that lands: *sixty-three percent of forecasts miss the band, and nobody can investigate
forty-four thousand of anything. The system's first job is deciding which twenty-two thousand are worth
a person's time.*

**One real worked example — use this, do not invent one**

A United States social-media queue, one week in 2024:

- Planned **18,932** · arrived **25,697** · short by **6,765** contacts — **35.7%** under-forecast
- Business impact **Critical** · cause: a drifting forecast baseline · confidence **67.5%** ·
  **23** explanations tested

The line worth quoting on the page:

> *The evidence available before that week implied the plan should have moved by 1,241 contacts.
> It moved by 77.*

**What it cannot do — state plainly, do not hedge**

1. **No daily detail.** The source records whole weeks. Daily analysis would need a new data feed.
2. **Promotions and campaigns cannot be tested as causes** — that data source is not deployed, and the
   system reports it as not-applicable rather than counting it against confidence.
3. **185 holiday naming questions are unresolved** — where two holidays share a date, whether they are
   one event or two is a business judgement. Recorded, not guessed.
4. **It does not prove causation.** The wording throughout is "the evidence supports", never "this
   caused".
5. **The judgement stays with the analyst.** This produces the evidence; a person still decides.

---

# CLOSING

The strongest thing about this system is not that it is fast. It is that **it is built so that it cannot
bluff** — the arithmetic is in code, the AI cannot introduce a figure, and the system states its own
limits on screen. Build the page so a sceptical executive reaches that conclusion without being told
it.
