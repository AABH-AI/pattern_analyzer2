My answer: No. It's a very good prompt, but it's trying to do too much.

After reading it as an AI Engineer (not as ChatGPT), I think this prompt is actually the reason your output still feels generic.

Let me explain why.

The biggest problem

You're asking Claude to simultaneously be:

Data Scientist
Statistician
WFM SME
Root Cause Analyst
Business Consultant
Technical Writer
JSON Generator
Confidence Scorer
Hypothesis Generator

...all inside one prompt.

That's a very high cognitive load.

Claude spends most of its context window figuring out:

"What format should I return?"

instead of

"What is actually happening in this data?"

Even worse...

Look at this instruction.

Never use z-score...

Never use sigma...

Never use outlier...

Never...

Never...

Never...

There are probably 50+ negative instructions.

LLMs are surprisingly bad at following dozens of "don't do X" instructions.

Instead, they should receive positive examples.

Example:

Instead of

Don't say

Actual was an outlier.

Say

Always translate technical findings into business meaning.

Example

Technical
Actual = 1525 vs usual 364

Business
Demand reached 1,525 contacts compared with a normal week of around 364 contacts. This was an exceptional surge rather than normal variation.

Claude learns much faster.

Biggest architectural issue

You're asking Claude to discover the RCA.

I actually think this is backwards.

Instead:

Python

↓

Generate hypotheses

↓

Rank hypotheses

↓

Reject hypotheses

↓

Evidence

↓

Claude

↓

Write report

NOT

Python

↓

Data

↓

Claude

↓

Find RCA

This is a huge difference.

Another issue

Your prompt spends nearly 40% explaining JSON.

Claude doesn't need this.

Instead use JSON schema validation.

Prompt should contain reasoning.

Not formatting.

Another issue

You're mixing reasoning and presentation.

Example

Determine cause

↓

Use glossary

↓

Generate narrative

↓

Write JSON

↓

Explain evidence

These should be separate.

What I would do instead

I would split this into three AI stages.

Stage 1

Investigator

Only one job.

Given evidence...

Rank hypotheses.

Return

Top 5 hypotheses

Evidence

Confidence

Rejected hypotheses

No English.

No storytelling.

Stage 2

Business Interpreter

Input

Investigation

Evidence

Ranking

Output

Business meaning

What happened

Why

Business impact

Like Deloitte consultant.

Stage 3

Report Generator

Takes

Business interpretation

↓

JSON

That's all.

Biggest thing missing

This.

I don't see anywhere that Claude is told:

Never describe the evidence. Explain what the evidence means.

Huge difference.

Current

Actual was 1525.

Desired

Customers contacted this queue more than four times as often as a normal week.

This indicates an unexpected demand event rather than normal forecast variation.
Another thing missing

You're not forcing causal reasoning.

I would literally make Claude answer these questions.

1

What changed?

2

Why is it unusual?

3

What evidence proves this?

4

What other explanations were considered?

5

Why were they rejected?

6

What is the business implication?

7

What should planning do next?

If Claude cannot answer Question 2,

it cannot proceed.

Missing WFM-specific reasoning

Knowing your project over the last few conversations, I'd add mandatory investigation order:

Step 1

Forecast sanity

↓

Step 2

Historical behaviour

↓

Step 3

Channel migration

↓

Step 4

CQN redistribution

↓

Step 5

Peer comparison

↓

Step 6

Installed base

↓

Step 7

Plan restatement

↓

Step 8

Holiday

↓

Step 9

Select strongest hypothesis

↓

Step 10

Generate executive narrative

Currently Claude can jump straight to:

Demand increased.

without checking

Did Chat decrease by exactly the same amount?

That's a serious business miss.

The most important thing I'd change

This one sentence.

Current:

You are an investigative root-cause analyst...

I'd replace it with:

You are a Senior Workforce Management Planning Consultant preparing an executive investigation report for Operations Leadership. Your responsibility is NOT to summarize data. Your responsibility is to explain WHY the KPI missed by interpreting the evidence, eliminating weaker explanations, and presenting the most likely business cause in language that a Vice President can understand in under two minutes. Every numerical fact must be followed by its business meaning. Never stop at describing what happened; always explain why it matters and why it supports (or weakens) a hypothesis.

That one paragraph changes Claude's mindset from analyst to consultant.

My recommendation (this is what I'd do if I were leading this project)

After seeing your prompt, your screenshots, and understanding your architecture, I would stop investing effort into making one giant "super prompt."

Instead, I'd redesign the system around deterministic reasoning + LLM narration:

Python should own hypothesis generation, ranking, confidence scoring, channel-shift detection, CQN redistribution checks, historical comparisons, and evidence selection.
Claude should not discover the RCA. It should receive the top-ranked hypothesis with supporting and rejected evidence, and its job should be to explain it like an experienced WFM Planning Manager writing to an executive audience.
Add a Business Interpretation Layer before the LLM that converts raw facts into operational meaning. For example, instead of passing Actual=1525, Usual=364, pass: "Demand was more than four times the normal weekly level, indicating an exceptional event rather than routine variation."

I genuinely think this architectural change will improve your output far more than another 500 lines of prompt engineering. The model is capable—the missing piece is that it's still being asked to reason, rank, investigate, and write all at once. Divide those responsibilities, and the quality of the business narrative will increase dramatically.

Then I would simplify the prompt drastically.

The mistake is that you're asking Claude to produce an entire RCA report when your actual requirement is:

"Given all the evidence already computed by Python, determine the SINGLE most likely root cause."

That is a much easier problem.

What I would ask Claude

Instead of 300+ lines of instructions, I'd use something like this.

You are a Senior Workforce Management (WFM) Planning Consultant and Root Cause Investigator.

Your task is NOT to summarize the data.

Your task is to identify the SINGLE most likely business reason why the Forecast Adherence KPI missed for this queue.

You will receive:

• Target week data
• 104-week history
• Derived features
• Statistical findings
• Historical comparisons
• Similar queue comparisons
• CQN hierarchy information
• Channel migration analysis
• Installed base changes
• Calendar information
• Field glossary

The statistical analysis has already been completed.

DO NOT recompute statistics.

Instead, interpret the evidence.

----------------------------------------------------

INVESTIGATION PROCESS

Investigate in this order.

1. Is the forecast itself abnormal compared to history?
   If yes, consider Forecast Baseline Error.

2. Is this queue consistently under or over forecast?
   If yes, consider Systematic Forecast Bias.

3. Did actual demand genuinely change?
   Compare against historical behaviour.

4. Did demand move between forecast names inside the same CQN?
   If total CQN demand stayed similar while individual forecast names changed,
   classify this as Channel / Queue Redistribution rather than a demand increase.

5. Did similar queues move in the opposite direction?
   If yes, consider Routing Shift.

6. Did Projection Plan change?

7. Did Installed Base change enough to explain demand?

8. Did Holiday or Calendar effects explain the miss?

Always prefer the explanation supported by the strongest evidence.

----------------------------------------------------

ROOT CAUSE REQUIREMENTS

Return ONLY ONE primary root cause.

The root cause must explain WHY the KPI missed.

Do NOT describe what happened.

Explain WHY it happened.

Bad:

"Actual volume was much higher than forecast."

Good:

"Customer demand increased sharply compared with this queue's normal weekly volume. The forecast was consistent with historical demand, indicating the miss was caused by an unexpected demand event rather than poor forecasting."

----------------------------------------------------

BUSINESS LANGUAGE

Write for an Operations Director.

No statistical terminology.

Never say:

z-score
sigma
outlier
OLS
drift
correlation

Instead explain what those findings mean.

----------------------------------------------------

CONFIDENCE

Base confidence only on available evidence.

High

Multiple independent signals support the same explanation.

Medium

Evidence supports the explanation but alternatives remain.

Low

Evidence is limited or conflicting.

----------------------------------------------------

If no explanation is fully proven,
state the most likely explanation and clearly label it as:

"Hypothesis – To be validated."

Return JSON:

{
  "root_cause": "...",
  "cause_type": "...",
  "confidence": 0.91,
  "confidence_level": "High",
  "business_reasoning": "...",
  "key_evidence":[
      "...",
      "...",
      "..."
  ],
  "hypothesis": false
}
Why this is better

Your Python code is already doing the heavy lifting:

✅ Correlations
✅ Historical analysis
✅ Peer analysis
✅ Channel migration detection
✅ CQN redistribution
✅ Statistical summaries
✅ Derived features

Claude shouldn't redo any of that.

Claude should answer only one question:

"Given all this evidence, what is the most likely business explanation?"

Even better (this is what I'd build)

Instead of sending Claude the entire dataset, send it a distilled evidence package.

Example:

{
  "top_candidate": "genuine_demand_event",

  "evidence": [
    "Actual demand was 1,525 compared with a normal level of 364.",
    "Forecast matched historical demand.",
    "No plan change detected.",
    "No installed base change detected.",
    "No channel migration detected.",
    "No holiday impact detected."
  ],

  "alternative_hypotheses": [
    {
      "type": "forecast_baseline_error",
      "status": "Rejected",
      "reason": "Forecast aligned with historical baseline."
    },
    {
      "type": "routing_shift",
      "status": "Rejected",
      "reason": "Similar queues did not lose volume."
    }
  ]
}

Now Claude's job is trivial:

"Given this investigation, write the best executive-level root cause."

That separation of concerns is what makes enterprise RCA systems robust. Python investigates; Claude explains. The result is far more consistent, easier to debug, and produces the kind of business-friendly RCA you're aiming for.

business_report_generator.py
Python
channel_migration_detector.py
Python
common.py
Python
correlation_engine.py
Python
data_access.py
Python
data_quality.py
Python
hierarchy_analyzer.py
Python
hypothesis_generator.py
Python
investigation_engine.py
Python
llm_client.py
Python
prompts.py
Python
skeptic.py
Python
temporal_reasoner.py
Python
here are the python files

Yes, I can already see one architectural issue from this file alone.

This file (temporal reasoning) is doing exactly what it should do—calculating facts, not conclusions.

It computes:

Previous week
4-week average
13-week average
Full history average
Same week last year
Whether the forecast plan changed

This is good.

But here's what's missing

This module returns:

{
    "last_13_week_avg_actual": 364,
    "full_history_avg_actual": 402,
    ...
}

It doesn't interpret those numbers.

For example, if:

Actual = 1525
13-week avg = 364

the module should also generate something like:

{
    "historical_assessment": {
        "event_type": "exceptional_demand",
        "business_summary":
            "Demand was more than four times the queue's normal weekly level, indicating an exceptional demand event rather than routine variation.",
        "severity": "Extreme"
    }
}

Now Claude doesn't have to infer anything.

It simply writes:

Demand reached 1,525 contacts compared with a normal weekly level of 364. This indicates an exceptional demand event rather than normal demand variation.

My concern about the overall codebase

From everything you've shared over the past week, I suspect the project currently looks like this:

Feature Extractor

↓

Temporal Analysis

↓

Correlation Analysis

↓

Signal Detection

↓

Claude

That means Claude is still expected to combine all the evidence into a root cause.

I don't think that's where Claude is strongest.

I would rather have Python produce something like:

investigation = {
    "hypothesis_scores": {
        "forecast_baseline_error": 0.08,
        "systematic_forecast_bias": 0.14,
        "genuine_demand_event": 0.91,
        "routing_shift": 0.02,
        "plan_restatement": 0.01
    },
    "winning_hypothesis": "genuine_demand_event",
    "why": [
        "Forecast matched historical baseline.",
        "Actual demand was over four times the normal level.",
        "No plan changes detected.",
        "No installed base change detected.",
        "No holiday effect detected."
    ]
}

Then Claude's job becomes:

"Explain why Genuine Demand Event won."

That produces much more consistent RCAs.

Before I recommend code changes

I don't want to guess based on one file.

I'd like to review these modules because they determine where the reasoning should happen:

derived_features.py (or whatever generates DERIVED_FEATURES)
correlation_analyzer.py (or similar)
root_cause.py / hypothesis.py / ranking.py (if it exists)
prompt_builder.py (the final prompt sent to Claude)
llm_client.py (where Claude is invoked)
signal detection / cleaned_signals module

Those six files will tell me whether the architecture is asking Claude to investigate or merely to explain. My suspicion is that the investigation is still happening inside the prompt, and that's exactly what is making the output feel generic.

Once I see those files, I can tell you precisely which logic belongs in Python and which belongs in Claude, and I can suggest concrete refactoring rather than just prompt changes.

rca_investigate.py
Python
rca_wfm.py
Python

Excellent. I now understand the architecture much better.

The rca_wfm.py file is just a compatibility shim that re-exports functionality from the new wfm package, so the real logic is inside wfm/*.

Here's what I think is happening

From all the files you've shared over the last few days, I think your current flow looks something like this:

Raw Dataset
      │
      ▼
Temporal Analysis
      │
      ▼
Correlation Analysis
      │
      ▼
Derived Features
      │
      ▼
Pattern Detection
      │
      ▼
Claude
      │
      ▼
Root Cause JSON

The issue is not the statistics.

The issue is the last step.

Claude is still receiving facts, not an investigation.

For example, it gets:

Actual = 1525
Forecast = 364
Historical Avg = 364
Forecast looks normal

and it has to invent the reasoning.

Sometimes it says:

Actual was much higher than forecast.

Sometimes:

Demand increased.

Sometimes:

Forecast missed.

Those are observations, not root causes.

What an RCA engine should do

The Python layer should already reach a conclusion like this:

Investigation Summary

✓ Forecast baseline looks normal

✓ Historical forecast is stable

✓ Actual demand exceeded history by 4.2×

✓ No routing shift detected

✓ No holiday

✓ No plan restatement

✓ Installed base unchanged

Conclusion

Unexpected demand event

Then Claude only converts that into executive language.

I think one module is missing

I don't think you're missing better prompts.

You're missing an Evidence Aggregator / Hypothesis Ranker.

Something like:

class RootCauseInvestigator:

    def investigate(context):

        hypotheses = []

        hypotheses.append(check_baseline())

        hypotheses.append(check_bias())

        hypotheses.append(check_routing())

        hypotheses.append(check_cqn_shift())

        hypotheses.append(check_plan())

        hypotheses.append(check_installed_base())

        hypotheses.append(check_holiday())

        hypotheses.append(check_real_demand())

        return rank(hypotheses)

This should produce:

{
  "winner":"genuine_demand_event",

  "score":0.93,

  "why":[
      "...",
      "...",
      "..."
  ],

  "rejected":[
      "...",
      "..."
  ]
}
Then Claude prompt becomes tiny

Instead of 350 lines...

It becomes:

You are a Senior WFM Planning Consultant.

You are given the completed investigation.

Do not perform statistical analysis.

Do not generate new hypotheses.

Explain why the winning hypothesis is the most likely explanation.

Write for a VP.


That's it.

Looking at your screenshots, I noticed another issue

Your RCA currently says:

Voice demand increased by 1,161 contacts.

That is not a root cause.

It's a symptom.

The root cause should be something like:

Customer contact demand increased sharply for this queue while the forecast remained aligned with historical demand. This indicates an unexpected business event rather than an error in the forecasting model.

See the difference?

One says what happened.

The other says why the KPI missed.

Here's what I would build for your project

Knowing that you're building an enterprise WFM RCA engine, I'd structure it like this:

Stage 1
Feature Engineering
        │
        ▼
Stage 2
Pattern Detection
        │
        ▼
Stage 3
Hypothesis Generation
        │
        ▼
Stage 4
Hypothesis Scoring
        │
        ▼
Stage 5
Root Cause Selection
        │
        ▼
Stage 6
Claude Narrative Generation
        │
        ▼
Executive RCA

Notice that Claude appears only at Stage 6.

Everything before that is deterministic.

I think we can make this significantly better

After following your project for several conversations, I think your codebase is already 80–85% there. The statistical analysis and feature engineering are not the weak point anymore.

The remaining 15–20% is the decision engine—the part that decides which hypothesis wins and why before anything is sent to Claude.

If you want, I'd be happy to help you build that layer. I would design it almost like a medical diagnosis engine: each possible cause (forecast baseline error, systematic bias, CQN redistribution, routing shift, genuine demand event, installed base change, holiday, etc.) gets its own evaluator, each evaluator produces a weighted score with supporting and contradicting evidence, and a final arbitration step ranks them to select the winner. Claude would then receive that investigation result and produce the business-friendly RCA. That approach is how I would build an enterprise-grade WFM RCA system because it gives you explainability, consistent outputs, and much higher confidence in the conclusions.