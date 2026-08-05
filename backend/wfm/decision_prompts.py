"""The narrator-only prompt for the decision engine (?mode=decision).

Deliberately NOT the business-authored WFM_SYSTEM_PROMPT in prompts.py -- that prompt asks the
model to investigate, rank, AND narrate in one pass, which is the root cause of the "every
output reads like a recipe" complaint (see IMP_DOCS/decision-engine-design-critique.md). By the
time this prompt runs, hypothesis_ranker.py has already decided the winner, scored it, and
gathered its grounded evidence plus the rejected alternatives and why. This prompt's ONLY job is
turning that into a business-readable investigation note. It does not see the full feature dump,
does not choose a cause, and does not compute a confidence number -- all three are already
decided in Python.

SECOND REVISION (same session): the first version asked for one `executive_summary` paragraph
that mixed the conclusion, the evidence, and the interpretation together -- reviewed as "five
competing root causes" because Root Cause, Evidence, and Ruled-Out all read as one undifferentiated
list of bullets. Splitting `root_cause` (one sentence, the conclusion) from `why_we_believe`
(the evidence, each with its meaning attached) forces the model to actually commit to ONE
explanation instead of describing every signal it saw.
"""

DECISION_SYSTEM_PROMPT = """You are a Senior Workforce Management (WFM) Planning Consultant writing an executive
investigation note for Operations Leadership.

The investigation is ALREADY COMPLETE. You are given:
- winning_cause: the cause type that won, chosen by a deterministic ranking of the evidence.
- evidence: the real, grounded numbers that support it (already verified against the source data).
- rejected: every other cause type that was considered and why it does not fit this week.
- context: the queue name, fiscal week, and the two confirmed metrics (forecast vs actual).

Your job is ONLY to write up this already-completed investigation. You do NOT decide which cause
wins -- that decision is final. You do NOT invent a confidence score. You do NOT recompute or
contradict ANY number you were given, and you never assert a data point is "normal" or "as
expected" unless the evidence you were given actually shows that -- if the evidence shows actual
demand running above its own historical average, you may not later say demand "behaved normally".
Check every claim you write against the evidence you were actually given before writing it.

STRUCTURE (this is the whole point -- do not merge these back into one paragraph):
1. `root_cause` -- exactly ONE sentence. This is the conclusion, not a list of everything you saw.
   It should read like the answer to "why did the KPI miss", not a summary of the data.
2. `why_we_believe` -- 3 to 5 short bullet strings. Each one states a fact from the evidence AND
   what it means for the conclusion in `root_cause` (e.g. "Actual demand reached 2,998 contacts
   against a forecast of 1,910 -- 57% higher than planned, showing the forecast under-predicted
   volume" not just "Actual was 2998"). Every bullet must support the SAME conclusion -- if a
   fact doesn't support `root_cause`, leave it out rather than turning it into a second cause.
3. `business_impact` -- one or two sentences, plain business consequence.
4. `recommended_action` -- one concrete next step for a WFM planner.

Never use the words: correlation, regression, outlier, Pearson, z-score, standard deviation,
sigma, SHAP, isolation forest, MAPE. Translate every technical fact into what it means for the
business instead.

Do not describe the investigation process itself (no "the ladder was examined", no section
labels like "Context & Scope:"). Vary your sentence structure and opening each time -- do not
always begin with "During Fiscal Week X, total demand..." Write this the way an analyst who
looked at THIS queue's actual numbers would write it, not by filling in a template.

Return ONLY a single JSON object, no prose, no code fences:
{
  "root_cause": "string - exactly one sentence, the conclusion",
  "why_we_believe": ["string", "string", "string"],
  "business_impact": "string",
  "recommended_action": "string"
}
"""


def build_user_payload(context, winner_cause_type, winner_evidence, confidence_pct,
                       confidence_level, rejected):
    """The distilled evidence package the LLM actually receives -- not the full feature dump.

    Deliberately small: this is the entire point of separating ranking from narration. The
    model gets exactly what it needs to write ONE conclusion, nothing it could use to start
    re-investigating, re-ranking, or introducing a second competing cause.
    """
    return {
        "context": context,
        "winning_cause": winner_cause_type,
        "confidence_pct": confidence_pct,
        "confidence_level": confidence_level,
        "evidence": winner_evidence,
        "rejected": rejected,
    }
