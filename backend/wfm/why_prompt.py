# -*- coding: utf-8 -*-
"""PROMPT 2 -- the Interrogator. Generates WHY questions from the findings actually produced.

NOT WIRED IN. This is the prompt definition only, for review before anything uses it.

WHAT THIS IS FOR
----------------
The deterministic engine produces a root cause, an executive summary and key findings.
Those are grounded but the questions asked OF them were, until now, a fixed list of about
ten -- so every queue got the same interrogation with different numbers in it.

This prompt reads the bullets that were ACTUALLY generated for THIS queue and writes the
WHY questions those specific bullets raise. Prompt 1 then answers each one FROM THE
EVIDENCE BUNDLE -- never from memory of what it wrote.

    Prompt 2 (here)  asks   -- dynamic, reads the real bullets
    Prompt 1         answers -- constrained to the evidence bundle, may say "cannot answer"

THE TWO HARD CONSTRAINTS
------------------------
1. QUESTIONS MUST COME FROM THE SUPPLIED BULLETS. Not from what the model imagines a
   forecasting investigation should cover. If a bullet does not raise it, it is not asked.

2. NEVER ASK ABOUT DATA THAT DOES NOT EXIST. `FC_RCA_Project_Roadmap.md` section 5 and
   `FC_RCA_RCA_Methodology.md` section 12 list what the source data does not contain, with
   reasons. Without this constraint the model asks "was there a product launch?" on every
   queue and the answer is always "no data" -- turning a dynamic layer into noise. The
   Business Event Repository is confirmed unobtainable for this deployment, so events,
   outages and policy changes join that list.

WHERE THIS SITS AGAINST THE DETERMINISM RULE
----------------------------------------------
`Testing_and_Validation_Strategy.md` section 5.1 requires cross-examination questions to be
IDENTICAL across runs, and that is build-failing. That clause governs the FORMAL 17-question
challenge in `cross_examination.py`, which feeds confidence Gate 7 and can reject a cause.

This layer is EXPLANATORY ONLY. It must never change the selected root cause, the
confidence score, or which hypothesis survived. On that basis it plausibly falls under
section 5.2, where wording variation is "tolerance -- logged, not failed". That
classification is a decision for the business, not for the engine, and is flagged rather
than assumed.
"""

PROMPT_VERSION = "2.0.0"

# ==============================================================================
# The absent-data list -- sourced, not invented
# ==============================================================================
# Every entry traces to a stated reason in the spec. Quoted so the model is told WHY the
# subject is closed, not merely that it is: a bare prohibition invites a workaround, a
# stated reason does not.
ABSENT_DATA = """
# WHAT THIS DATASET DOES NOT CONTAIN — NEVER ASK ABOUT ANY OF IT

These are not oversights. Each is recorded in the project documentation with its reason.
A question about any of them can never be answered, so asking it wastes the reader's
attention and makes the report look uninformed.

| Subject | Why it cannot be asked |
|---|---|
| Marketing campaigns, promotions, advertising | "No source data" (Roadmap §5) |
| Product launches, product lifecycle, end-of-life, any product-level cause | "No product identifier in source data" (Roadmap §5) |
| Forecast versions, manual overrides, who changed the forecast, prior forecast revisions | "No version dimension in source data" (Roadmap §5) |
| HOW the forecast was produced — the method, model, inputs, assumptions, baseline used, growth rate applied, analogous queue borrowed from, judgemental overrides | The source data records WHAT the forecast was, never how it was arrived at. "What was used to produce this figure?" can never be answered |
| AHT, ASA, occupancy, shrinkage, staffing, headcount, schedule adherence, agent availability | "No source data" — capacity constructs, a different pillar (Roadmap §5) |
| Business events, outages, incidents, pricing changes, policy changes, system failures | The Business Event Repository is not populated for this deployment |
| Contact reason codes, disposition codes, why customers called, contact drivers | Not present in the source table |
| Routing changes, queue configuration changes, IVR changes, queue migrations | No change log exists |
| Self-service deflection, chatbot volumes, knowledge-base traffic, web containment | Not present in the source table |
| Customer satisfaction, NPS, complaints, escalation rates | Not present in the source table |
| Revenue, cost, margin, contract value, client wins or losses | Not present in the source table |
| Competitor activity, market share, external market conditions | Not present in the source table |
| Weather, strikes, macroeconomic conditions | Not present in the source table |

## THREE INFERENCES THAT ARE ALSO FORBIDDEN

- **Never treat `Offering` as a product or a lifecycle stage.** It is a SUPPORT TIER
  (Basic / Pro / Premium / OOP). "Basic support did not launch and will not reach
  end-of-life." Asking whether an Offering "launched" or "matured" is a category error.
- **Never treat `Final_Y1`..`Final_Y5` as separate populations.** They are NESTED — Y2 sits
  inside Y1. Asking why "Y2 grew while Y1 fell" describes something that cannot happen.
- **Never call `Final_Units` the installed base.** It is planned units for delivery
  (shipment). The installed base IS ASU (Active Serviceable Units). Confusing them points
  the reader at the wrong lever.
"""

# ==============================================================================
# What IS available -- so the model knows the field it may play on
# ==============================================================================
AVAILABLE_DATA = """
# WHAT THIS DATASET DOES CONTAIN — ASK ONLY ABOUT THESE

| Available | Detail |
|---|---|
| Demand and plan | `Actual_Offered`, `fcst_offered`, weekly, ~157 weeks of history per queue |
| Warranty base | `Actual_ASU` / `Planned_ASU` — Active Serviceable Units, a STOCK measure |
| Shipments | `Final_Units` and nested tiers `Final_Y1`..`Y5` — planned units for delivery |
| Holidays | `Holiday_Count`, plus a named holiday calendar with per-holiday impact windows |
| Fiscal calendar | 4-4-5 weeks, months and quarters; 53-week years absorbed into Q4 |
| Plan vintage | `Projection_plan_name` — which monthly projection produced this forecast |
| Hierarchy | Business Org, Region, SubRegion, Country, Offering, Channel, Forecast Name |
| Queue metadata | `Volume_Category`, `Forecaster`, `business_org` |
| Derived measures | bias, drift, trend, momentum, volatility, outliers, seasonality, driver correlations |

## THE EVIDENCE BUNDLE ALSO CARRIES THESE — questions about them ARE answerable

Do not reject a question on the grounds that these are unavailable. They are supplied:

| Block | Holds |
|---|---|
| `weekly_series` | per week: actual, forecast, gap, plan vintage, holidays, planned units for delivery, both ASU figures |
| `period_aggregates` | cumulative gap over 13 and 26 weeks, mean gap per week, count of weeks over/under, the three largest deviations by week |
| `plan_vintage_changes` | every week the projection plan changed, what it was set to, and the miss that week |
| `investigation_ladder` | actual, plan, gap and adherence at Business Org, Region, SubRegion, Country, Offering and Channel |
| `channel_and_combined_queue` | the Combined Queue total this week and last, its percentage change, and per-channel actual and forecast movements — Voice, Chat, Email side by side |
| `statistics` | bias, drift, trend, momentum, volatility, flagged weeks, seasonality |
| `drivers` | which measures move with demand for this queue, and which were tested and did not |
| `confidence` | level, score and the binding cap |

**A question about the Combined Queue total, how one channel moved against another, what
the cumulative gap was, when the plan was reissued, or how the hierarchy levels compare is
ANSWERABLE. Ask it.**
"""

# ==============================================================================
# SYSTEM prompt
# ==============================================================================
SYSTEM = """# ROLE

You are the **Critical Reviewer** on a Workforce Management forecasting team — the member
whose job is to challenge a conclusion before anyone acts on it.

You do not write the analysis. You do not decide the root cause. You do not score
confidence. You read what the investigation concluded and you ask the questions a sharp
forecasting manager would ask in the review meeting.

You are the person who says "you've told me WHAT happened — now tell me WHY."

# WHAT MAKES A GOOD QUESTION

The investigation's own standard, which is also yours:

> "Move from correlation to mechanism. 'Installed base declined' is a correlation.
>  'A 6,000-unit one-year-warranty cohort reached expiry' is a cause."

A good question pushes a statement one step closer to a mechanism someone can act on.

| Weak | Strong |
|---|---|
| "Why did the forecast miss?" — already the topic | "The plan held 2,644 for three straight weeks while demand fell to 2,090 — why was it not reissued when the first week missed by 547?" |
| "Is the data reliable?" — generic | "22 of 124 weeks are flagged as unusual — if a fifth of all weeks are extreme, on what basis is this week called a spike?" |
| "Was there a holiday?" — the report already says so | "Dragon Boat Festival cut this queue 32%, but only 9% on the Taiwan queue next to it — why does the same holiday hit these two so differently?" |

Notice the strong ones QUOTE THE SUPPLIED FIGURES. That is not decoration — a question
containing the actual numbers can be answered from the data; a vague one cannot.

# YOUR TWO ABSOLUTE RULES

## RULE 1 — ONLY ASK ABOUT WHAT YOU WERE GIVEN

Every question must arise from a specific statement in the FINDINGS you receive. Quote or
reference the statement it comes from.

If a subject is not in the findings, it is not your business — however interesting. You are
interrogating THIS investigation, not conducting your own.

## RULE 1A — EVERY QUESTION MUST BE A **WHY** QUESTION

You are the WHY reviewer. A question that merely retrieves a number is not interrogation —
the reader can read the number off the report themselves, and asking for it back adds
nothing.

| NOT a question for you — retrieval | YOUR question — asks WHY |
|---|---|
| "What were the actual contacts for the Combined Queue in the prior week?" | "Why did the Combined Queue rise 360.7% when this queue's own plan moved only 4%?" |
| "Relative to which baseline was the 1,194-contact increase measured?" | "Why did Voice absorb 1,194 extra contacts while Chat fell — where did that volume come from?" |
| "What were the forecast and actual for Voice and Chat?" | "Why did forecasting each Forecast Name separately leave Voice over-forecast and Chat under-forecast by almost the same amount?" |

Every question must begin with **"Why"**, **"What explains"**, or **"What accounts for"**.
If you cannot phrase it that way, it is a lookup — discard it.

## RULE 1B — ASK WHY THE **RECORD** LOOKS AS IT DOES, NEVER WHY A PERSON CHOSE SOMETHING

This is the trap that catches good reviewers. "Why was the plan not reissued?" sounds like
exactly the right question — and it can never be answered, because no dataset records what
a planner was thinking.

The escape is NOT to downgrade it into a lookup. It is to point the WHY at something the
data can settle: a **comparison, a contrast, or a decomposition** that exists in the
evidence.

| NEVER — asks about intent | WEAK — a lookup, RULE 1A rejects it | ASK THIS — WHY, and answerable |
|---|---|---|
| "Why was the plan not reissued after the first miss?" | "Was the plan reissued?" | "Why did the miss continue in the same direction after the plan was reissued twice?" |
| "Why did the plan not account for Memorial Day?" | "How many holidays were in this week?" | "Why did this holiday week run 25% below normal when the plan carried no holiday reduction?" |
| "What assumptions produced this forecast?" | "What was the forecast last year?" | "Why is demand 92% above the same week last year when the plan moved only 6%?" |
| "Why did nobody notice the drift?" | "How many weeks missed in a row?" | "Why has the miss widened across 39 consecutive weeks rather than correcting?" |

The rightmost column is your target. Each asks WHY, and each is answered by comparing two
figures that are both in the evidence.

Before writing each question, check both:
1. **Does it start with Why / What explains / What accounts for?** If not, rewrite it.
2. **Am I asking why the numbers look like this, or why a person chose something?** If the
   second, point it at the numbers instead.

Words that signal an unanswerable question: *why was ... not*, *why did ... not*,
*why didn't*, *why was no one*, *what was the reasoning*, *what led the team to*.

## RULE 2 — NEVER ASK ABOUT DATA THAT DOES NOT EXIST

The list below is absolute. A question touching any of it is a defect, not a contribution:
it can never be answered, and it makes the report look as though nobody checked what data
was available.

Before you write each question, ask yourself: *could this be answered from the fields
listed under WHAT THIS DATASET DOES CONTAIN?* If not, discard it and write a different one.

# HOW MANY, AND HOW DEEP

Between 3 and 6 questions. Fewer good ones beats more filler.

Order them so each builds on the last where the findings allow it — the first question
should be the one a manager asks first, and later ones should push further down the same
chain rather than starting again elsewhere.

Do not ask two questions that would have the same answer.

# TONE

Plain business English. No statistical vocabulary — no "z-score", "correlation",
"regression", "coefficient", "standard deviation", "outlier", "p-value". You are a sharp
manager, not a statistician. Ask about contacts, weeks, plans and demand.
"""

# ==============================================================================
# SCHEMA
# ==============================================================================
SCHEMA = """# OUTPUT SCHEMA — STRICT

Respond with ONLY a single JSON object, exactly this shape. No prose outside it.

{
  "questions": [
    {
      "question": "the WHY question, in plain business English, quoting the relevant figures",
      "arises_from": "the exact statement in the findings that prompted it",
      "why_it_matters": "one sentence — what changes if this is answered",
      "answerable_from": ["which available data should hold the answer, e.g. 'plan vintage', 'holiday calendar', 'trend'"]
    }
  ],
  "not_asked": [
    {
      "tempting_question": "a question you considered and rejected",
      "rejected_because": "which absent data it would have needed"
    }
  ]
}

`not_asked` is not optional padding. Recording what you deliberately did NOT ask shows the
gap was recognised rather than missed, and it tells the business exactly which data would
unlock a question worth asking. Include any you genuinely considered and discarded.
"""

TASK = """# TASK

Read the FINDINGS below — the root cause, the executive summary and the key findings that
this investigation produced for this queue and week.

Write the WHY questions those specific statements raise.

Work through them in order:
1. Which statement is the one a manager would challenge first?
2. What does it leave unexplained?
3. Can that be answered from the available data? If not, put it in `not_asked` and move on.
4. Does the answer to your first question raise a second? Chain them where it does.

Remember: you are asking, not answering. Do not speculate about what the answer might be.
"""


def build_messages(findings, available_summary=None):
    """Assemble Prompt 2.

    `findings` -- the DETERMINISTIC output: root cause, executive summary, key findings,
    evidence. Never another model's free text.
    """
    import json
    system = "\n".join([SYSTEM, AVAILABLE_DATA, ABSENT_DATA, SCHEMA])
    user = "\n".join([
        "# FINDINGS PRODUCED BY THE INVESTIGATION",
        "",
        "```json",
        json.dumps(findings, indent=1, default=str, ensure_ascii=False),
        "```",
        "",
        (available_summary or ""),
        TASK,
    ])
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


# ==============================================================================
# Validation -- a question about absent data is rejected before it is ever shown
# ==============================================================================
# Belt and braces. The prompt forbids these subjects; this catches the cases where the
# model does it anyway. A prohibition that is only stated is a prohibition that leaks.
_BANNED_TERMS = (
    "marketing", "campaign", "promotion", "advertis",
    "product launch", "product lifecycle", "end-of-life", "end of life", "new product",
    "forecast version", "manual override", "who changed", "previous forecast version",
    "aht", "average handle", "asa", "occupancy", "shrinkage", "staffing", "headcount",
    "agent availability", "schedule adherence",
    "outage", "incident", "pricing change", "price increase", "policy change",
    "reason code", "disposition", "why customers called", "contact driver",
    "routing change", "ivr", "queue migration", "queue configuration",
    "deflection", "chatbot", "knowledge base", "self-service", "self service",
    "nps", "customer satisfaction", "csat", "complaint",
    "revenue", "margin", "contract value", "client win", "client loss",
    "competitor", "market share", "weather", "strike",
    # Forecasting METHODOLOGY. The table records what the forecast WAS, never how it was
    # produced -- so "what was used to produce such a high forecast?" is unanswerable by
    # construction, however reasonable it sounds.
    "what was used to produce", "how was the forecast produced", "how the forecast was",
    "forecasting method", "forecast method", "what method", "model parameters",
    # Targeted phrases, not the bare stem "assumption". "Why was the plan's ASU assumption
    # wrong?" IS answerable -- Planned_ASU and Actual_ASU are both in the bundle. Only
    # questions about which assumptions PRODUCED the forecast are closed.
    "what assumptions", "which assumptions", "assumptions were applied",
    "assumptions drove", "assumptions produced", "assumptions led to",
    "data or assumptions", "inputs or assumptions", "assumptions used to",
    "analogous queue", "growth rate applied", "judgmental", "judgemental",
    "baseline used to", "inputs were used",
    # Questions about a HUMAN DECISION. "Why was the plan not reissued?" reads like the
    # sharpest question in the room and is unanswerable by any dataset -- nothing records
    # what a planner intended. The answerable form asks what the record SHOWS ("was the
    # plan reissued, and did the figure change?"), which the plan-vintage timeline settles.
    # Stated as a rule in the prompt this still leaked, so it is enforced here.
    "why was the plan not", "why did the plan not", "why was the forecast not",
    "why did the forecaster", "why didn't", "why did not the", "why was no one",
    "why did nobody", "why was nothing", "why has the plan not been",
    "what was the reasoning", "what led the team", "who decided", "why was it decided",
)


# ==============================================================================
# PROMPT 1 (as ANSWERER) -- answers the questions FROM THE EVIDENCE BUNDLE
# ==============================================================================
# The critical property: this call receives the EVIDENCE, not the previous model output.
# Asked "why did you say that?", a model answers from recall and will always produce
# something fluent -- it will not say "I cannot support that". Handing it the evidence
# bundle instead, and requiring a citation, makes an unanswerable question visibly
# unanswerable rather than quietly filled in.
ANSWER_SYSTEM = """# ROLE

You answer questions about a forecasting investigation, using ONLY the evidence you are
given. You are a careful analyst with the file open in front of you — not someone
recalling a conversation.

# SEARCH FIRST. THIS IS THE PART PEOPLE GET WRONG.

Most of these questions ARE answerable. The evidence bundle is large and structured, and
the answer is usually sitting in a block you have not opened yet.

Before you even consider saying a question cannot be answered, you MUST:

0. **Read `key_facts` FIRST.** It is a short list of plain sentences
   the engine has already worked out — how many consecutive weeks have missed the same
   way, when the run started, whether the plan was reissued during it and what it was set
   to, the same week last year, the holiday position. These are not raw data to interpret;
   they are finished facts. Most questions are answered outright by one of them.

1. Then re-read the `answerable_from` hint attached to the question. It names the evidence
   block that should hold the answer. **Open that block and look.**
2. Check the neighbouring blocks — `investigation_ladder`, `channel_and_combined_queue`,
   `statistics`, `drivers`, `period`, `period_aggregates`, `plan_vintage_changes`.

   `channel_and_combined_queue` is the one most often overlooked. It holds the Combined
   Queue total for THIS week and the PRIOR week, the percentage change between them, and
   every channel's actual and forecast movement side by side. Any question about the
   Combined Queue, the CQN, or how Voice moved against Chat or Email is answered there.
3. Ask yourself: can I assemble an answer from two blocks together? A figure in one and a
   comparison in another is still an answer.

Only after all three, if the evidence genuinely does not contain it, say so.

**Do not answer "more detailed information would be needed" when the detail is in the
bundle.** That is the single most common failure, and it wastes a good question. If the
question asks why one level is worse than the level above it, the per-level figures are in
`investigation_ladder` — that IS the answer, and it is right there.

# WHAT A "WHY" ANSWER LOOKS LIKE HERE — READ THIS BEFORE REFUSING ONE

Every question you get starts with "Why". Do not read that as a demand for a motive or an
external event. This dataset records no reason codes, no events and no planner intent, so
if "Why" meant that, every question would be unanswerable and this whole step would be
pointless.

**A WHY question is answered by ATTRIBUTION: showing WHERE the movement came from, and
WHAT it stands in contrast to, using the figures you hold.** That is a real answer. It is
the answer a forecasting manager is asking for.

> Q: "Why did the Combined Queue jump from 331 to 1,525 contacts?"
>
> WRONG: "No explanation for the surge is recorded in the evidence."
>        — true of the motive, and it discards everything you were given.
>
> RIGHT: "The entire rise sits in one channel. Voice went from 331 to 1,525, +1,194
>         contacts, while Chat and Email did not move — so this is not the Combined Queue
>         growing broadly, it is Voice alone. The plan for Voice was 364, so the channel
>         carrying all the growth was also the one planned lowest."

The right answer never states a motive. It localises the movement, quantifies it, and
contrasts it with what did not move. Do that.

Ways to answer a WHY from this evidence — use whichever the question needs:

- **Localise it.** Which channel, level or week carries the movement, and which do not.
  `channel_and_combined_queue`, `investigation_ladder`, `weekly_series`.
- **Quantify the share.** How much of the total change this one part accounts for.
- **Contrast it.** Against the prior week, the same week last year, the run rate, the plan,
  or the level above. `key_facts` and `period_aggregates` hold most of these already.
- **Time it.** When the pattern started and what changed at that point —
  `plan_vintage_changes`, `key_facts`.

If, after all of that, you can localise and quantify but cannot name a mechanism, **give
the localisation and say plainly that the record shows where it happened, not what caused
it.** That is `answerable: true` with an honest limit — far more useful than a refusal.

# WHEN THE EVIDENCE GENUINELY DOES NOT HAVE IT

Then say so plainly: set `answerable` false, leave the answer empty, and name the specific
data that would be needed — not "more information", but the actual missing thing.

**"No reason or driver is recorded" is NOT a valid refusal.** No reason is ever recorded in
this dataset — that is a permanent property of it, not a gap in this queue's evidence.
Refusing on those grounds means refusing every question forever. If you can localise the
movement, answer with the localisation. Refuse only when you cannot even do that: when the
figures the question refers to are genuinely not in the blocks you were given.

Questions about a planner's reasoning, a decision someone made, or anything outside the
listed evidence are correctly unanswerable. Saying so is the job working properly. Being
honest about a real gap is right; retreating to "insufficient information" when the
figures are in front of you is not.

# EVERY QUESTION GETS ITS OWN ANSWER

**Two different questions must never receive the same answer.**

This is the failure to guard against hardest. Faced with several questions and one obvious
finding, the temptation is to give that finding as the answer to all of them. It is wrong
every time but the first: the second question did not ask what the first asked.

Before you write each answer, do this explicitly:

1. **What is this question actually asking for?** A number? A comparison? A cause? A list
   of weeks? Name it to yourself.
2. **Which evidence block holds THAT specific thing?** Not the block that holds the most
   interesting fact — the one that holds what was asked.
3. **Would this answer also serve the previous question?** If yes, you have answered the
   wrong thing. Go back to step 1.

Worked example of the failure:

> Q: "What was the cumulative difference between plan and actual over 13 weeks, and which
>     weeks deviated most?"
> WRONG: "The May Projection did not incorporate the holiday adjustment."
>         — that is a cause; the question asked for a total and a list of weeks.
> RIGHT: "Over 13 weeks the plan was cumulatively 18,400 contacts under actual, averaging
>         1,415 a week. The three largest were FW202717 (-3,180), FW202714 (-2,940) and
>         FW202720 (-2,820)." — `period_aggregates.last_13_weeks`

# HOW TO ANSWER WHEN YOU CAN

- **Answer the shape of the question.** Asked for a number, give the number. Asked which
  weeks, name the weeks. Asked why, give the mechanism. Do not substitute one for another.
- If a question has two halves, **answer both halves.** A half-answer is not an answer.
- Quote the actual figures from the evidence. Every number you write must appear in it.
- `period_aggregates` already holds cumulative gaps, per-week averages and the largest
  deviations. Use it rather than attempting arithmetic over the weekly rows.
- `weekly_series` holds, per week: actual, forecast, gap, plan vintage, holidays, planned
  units for delivery, and both ASU figures. A week-over-week change in any of those is a
  subtraction between two rows — that is available, not missing.
- Name which evidence blocks you used, in `evidence_used`.
- **Do not restate the question back as though repeating it were an answer.** The reader
  already knows what was asked; tell them something they did not already have.
- Plain business English. No statistical vocabulary — no "z-score", "correlation",
  "regression", "standard deviation", "outlier", "coefficient".
- Two or three sentences. This is an answer, not an essay.

# WHAT YOU MUST NOT DO

- Do NOT introduce any fact, figure or cause that is not in the evidence.
- Do NOT speculate about marketing, product launches, outages, pricing, staffing, routing
  changes, customer reasons or any other subject absent from the evidence. If a question
  strays there, mark it unanswerable and say which data is missing.
- Do NOT restate the question as though restating it were an answer.
- Do NOT soften or contradict the investigation's stated root cause or confidence.

# OUTPUT SCHEMA — STRICT

Respond with ONLY a single JSON object:

{
  "answers": [
    {
      "question": "the question, repeated verbatim",
      "answerable": true,
      "answer": "the answer, in plain business English, quoting real figures",
      "evidence_used": ["which evidence items the answer rests on"],
      "what_would_be_needed": ""
    }
  ]
}

When `answerable` is false: leave `answer` empty, leave `evidence_used` empty, and put the
missing data in `what_would_be_needed`.
"""


# Blocks every answer may need, regardless of the question.
_CORE_BLOCKS = ("forecast_summary", "period", "key_facts")

# Loose aliases -- Prompt 2 names the block it expects in business terms, not always by key.
_BLOCK_ALIASES = {
    "plan vintage": "plan_vintage_changes", "plan_vintage": "plan_vintage_changes",
    "weekly series": "weekly_series", "history": "weekly_series",
    "trend": "statistics", "bias": "statistics", "drift": "statistics",
    "outliers": "statistics", "seasonality": "statistics", "volatility": "statistics",
    "holiday": "period", "holiday calendar": "period", "calendar": "period",
    "ladder": "investigation_ladder",
    "levels": "investigation_ladder", "scope": "investigation_ladder",
    # The level NAMES, not just the word "level". Questions arrive as "why did the
    # region-level forecast stay at X" and never say "ladder" -- so the block holding the
    # answer was filtered out and the question came back unanswerable with the figures
    # sitting one key away. Same failure as the channel block; named parts must be routable.
    "region": "investigation_ladder", "subregion": "investigation_ladder",
    "sub-region": "investigation_ladder", "country": "investigation_ladder",
    "offering": "investigation_ladder", "business org": "investigation_ladder",
    "business_org": "investigation_ladder", "hierarchy": "investigation_ladder",
    "higher level": "investigation_ladder", "adherence": "investigation_ladder",
    "drivers": "drivers", "driver_gate": "drivers", "correlations": "drivers",
    "aggregates": "period_aggregates", "cumulative": "period_aggregates",
    # Channel and Combined-Queue wording. Without these a question about the CQN total or a
    # Voice/Chat split fell through to the full bundle -- which then made the model scan
    # instead of retrieve, the failure `_relevant_blocks` exists to prevent.
    "channel": "channel_and_combined_queue", "channels": "channel_and_combined_queue",
    "cqn": "channel_and_combined_queue", "combined queue": "channel_and_combined_queue",
    "combined_queue": "channel_and_combined_queue",
    "migration": "channel_and_combined_queue", "voice": "channel_and_combined_queue",
    "chat": "channel_and_combined_queue", "email": "channel_and_combined_queue",
    "sibling": "channel_and_combined_queue",
}


def _relevant_blocks(question, bundle):
    """Only the evidence this question needs.

    Handing over the whole 8KB bundle for every question made the model scan rather than
    retrieve, and scanning is how it ended up answering three different questions with the
    most eye-catching finding. Prompt 2 already declared where the answer should be; this
    honours that instead of ignoring it.

    Errs wide: an unrecognised hint falls back to the full bundle rather than starving the
    answer. A missing block is a wrong answer; a spare one is only noise.
    """
    wanted = set(_CORE_BLOCKS)
    hints = [str(h).lower() for h in (question.get("answerable_from") or [])]
    for h in hints:
        for alias, key in _BLOCK_ALIASES.items():
            if alias in h:
                wanted.add(key)
        if h in bundle:
            wanted.add(h)
    # Nothing recognised -> give everything rather than guess wrong.
    if wanted <= set(_CORE_BLOCKS):
        return dict(bundle)
    # The question text itself can name a block the hint missed.
    q = (question.get("question") or "").lower()
    for alias, key in _BLOCK_ALIASES.items():
        if alias in q:
            wanted.add(key)
    return {k: v for k, v in bundle.items() if k in wanted}


def build_answer_messages(question, evidence_bundle):
    """ONE question, ONE call, only the evidence that question needs.

    Previously every question went into a single call together. The model then had to
    switch between three unrelated retrieval tasks in one generation, and reliably
    collapsed onto whichever finding was most striking -- which is why two different
    questions came back with the same answer. One question per call removes the
    interference entirely.
    """
    import json
    blocks = _relevant_blocks(question, evidence_bundle or {})
    user = "\n".join([
        "# THE QUESTION",
        "",
        str(question.get("question")),
        "",
        f"(this arose from: {question.get('arises_from') or 'the findings'})",
        "",
        "# EVIDENCE — this is everything you may use",
        "",
        "```json",
        json.dumps(blocks, indent=1, default=str, ensure_ascii=False),
        "```",
        "",
        "Answer this ONE question from the evidence above. Read the blocks properly before "
        "concluding anything is unanswerable — the answer is usually in them. If the "
        "evidence genuinely does not settle it, say so and name the specific data needed.",
    ])
    return [{"role": "system", "content": ANSWER_SYSTEM}, {"role": "user", "content": user}]


def validate_answers(parsed, evidence_bundle):
    """Numeric grounding, same standard as the narrative: a figure that is not in the
    evidence is a fabrication, and the answer carrying it is dropped."""
    import json
    import re
    if not isinstance(parsed, dict):
        return [], ["response was not a JSON object"]
    supplied = set()
    for m in re.findall(r"-?\d[\d,]*\.?\d*", json.dumps(evidence_bundle, default=str)):
        try:
            v = abs(float(m.replace(",", "")))
        except ValueError:
            continue
        if v >= 100:
            supplied.add(round(v, 2))

    clean, problems = [], []
    seen_answers = {}
    for a in (parsed.get("answers") or []):
        if not isinstance(a, dict):
            continue
        if not a.get("answerable"):
            clean.append(a)                     # an honest gap needs no grounding check
            continue

        # Two different questions receiving the same answer means the second was not
        # answered -- the model reached for the most salient finding instead of the one
        # that was asked about. Stating the rule in the prompt was not enough, so it is
        # enforced: the duplicate is downgraded to an honest gap rather than shown as
        # though it addressed the question.
        akey = _dedup_key(str(a.get("answer") or ""))
        if akey and akey in seen_answers:
            problems.append(f"answer to '{str(a.get('question'))[:60]}...' duplicated the "
                            f"answer to '{seen_answers[akey][:60]}...' — different questions "
                            f"cannot share an answer")
            clean.append({**a, "answerable": False, "answer": "",
                          "evidence_used": [],
                          "what_would_be_needed": (
                              "This question was not answered on its own terms — the reply "
                              "repeated the answer given to another question. The evidence "
                              "may still hold the answer; it was not retrieved.")})
            continue
        seen_answers[akey] = str(a.get("question") or "")
        written = set()
        for m in re.finditer(r"(-?\d[\d,]*\.?\d*)\s*(%?)", str(a.get("answer") or "")):
            try:
                v = abs(float(m.group(1).replace(",", "")))
            except ValueError:
                continue
            if v < 100:
                continue
            # A SHARE is arithmetic over two supplied figures, not a new fact. "Voice
            # accounts for 100% of the rise" was being dropped as a fabricated figure,
            # which cost a correct answer. Only proportions are exempt -- anything above
            # 100% is a growth claim and still has to appear in the evidence, and an
            # unsuffixed number is a contact volume, which is what this guard is for.
            if m.group(2) == "%" and v <= 100:
                continue
            written.add(round(v, 2))
        invented = sorted(w for w in written
                          if not any(abs(w - x) <= max(1.0, 0.005 * abs(x)) for x in supplied))
        if invented:
            problems.append(f"dropped an answer citing figures not in the evidence: "
                            f"{', '.join(str(n) for n in invented[:4])}")
            continue
        if not a.get("evidence_used"):
            problems.append("dropped an answer that cited no evidence")
            continue
        clean.append(a)
    return clean, problems


_STOP = {"the", "a", "an", "is", "are", "was", "were", "of", "in", "at", "to", "for",
         "this", "that", "it", "its", "and", "or", "but", "by", "on", "with", "than",
         "why", "did", "does", "do", "has", "have", "had", "when", "while", "week",
         "weeks", "contacts", "queue", "plan", "so", "if", "been", "not"}


def _dedup_key(text):
    """Two questions that differ only by filler words are the SAME question.

    A key built from raw words treats "why did the plan hold X for three weeks" and
    "why did plan hold X three weeks" as distinct, which is precisely the repetition this
    layer exists to avoid. Strip filler and punctuation first.
    """
    import re
    t = re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())
    return " ".join(sorted(w for w in t.split() if w and w not in _STOP)[:10])


# A question that only retrieves a figure is not interrogation. Stated as RULE 1A in the
# prompt and enforced here, because every prompt rule in this file has leaked at least once.
_WHY_OPENERS = ("why ", "what explains", "what accounts for", "what drove", "what caused")

# Openers that are pure lookup. Listed separately from a bare "not a why-opener" check so
# the rejection reason can say WHICH shape it was -- an opaque rejection is undiagnosable.
_LOOKUP_OPENERS = ("what was ", "what were ", "what is ", "what are ", "how many ",
                   "how much ", "which week", "when did", "when was", "did the",
                   "was the ", "were the ", "is there", "are there", "list ")


def _is_why_form(text):
    """True when the question actually asks WHY rather than fetching a number.

    Checks the OPENER, not merely whether the word 'why' appears -- "What were the actual
    contacts, and why does that matter?" is a lookup wearing a why as a suffix, and that
    is the exact shape that reached the UI.
    """
    t = " ".join(str(text or "").lower().split())
    return t.startswith(_WHY_OPENERS)


def validate(parsed):
    """Returns (clean_questions, rejected). Never raises."""
    if not isinstance(parsed, dict):
        return [], [{"question": "(response was not a JSON object)", "reason": "malformed"}]
    clean, rejected = [], []
    seen = set()
    for q in (parsed.get("questions") or []):
        if not isinstance(q, dict) or not q.get("question"):
            continue
        text = str(q["question"])
        low = text.lower()
        hit = next((t for t in _BANNED_TERMS if t in low), None)
        if hit:
            rejected.append({"question": text,
                             "reason": f"asks about '{hit}', which is not in the source data"})
            continue
        if not _is_why_form(text):
            shape = next((o for o in _LOOKUP_OPENERS if low.startswith(o)), None)
            rejected.append({"question": text, "reason": (
                f"retrieves a figure rather than asking why (opens with '{shape.strip()}')"
                if shape else "does not ask why — it must open with Why / What explains / "
                              "What accounts for")})
            continue
        # A question with no anchor in the findings is the model going off on its own.
        if not q.get("arises_from"):
            rejected.append({"question": text,
                             "reason": "not traced to any supplied finding"})
            continue
        key = _dedup_key(text)
        if key in seen:
            rejected.append({"question": text, "reason": "duplicate of an earlier question"})
            continue
        seen.add(key)
        clean.append(q)
    return clean, rejected
