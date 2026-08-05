# -*- coding: utf-8 -*-
"""Cross-examination -- try to DISPROVE the conclusion before accepting it.

Implements `FC_RCA_AI_Agent_Architecture.md` section 11, `FC_RCA_RCA_Methodology.md`
sections 18-20, and the iteration bound in `BR-117`.

WHY THIS MODULE EXISTS
----------------------
`skeptic.py` performs a single pass: it checks each proposed cause against one feature
precondition and drops the ones that fail. That is a filter, not a challenge. It never
asks whether a DIFFERENT explanation fits the same facts better, whether the history is
deep enough to support the claim, or whether the conclusion has any precedent.

This module runs the challenge as the spec defines it: a fixed catalogue of questions,
answered FROM EVIDENCE, in a bounded loop, before confidence is assigned.

NO LLM IS INVOLVED. Questions come from a catalogue; answers come from the features.

WHY A FIXED CATALOGUE WITH SEMANTIC KEYS
------------------------------------------
Version 1.0.0 had the LLM generate challenge questions, which made deduplication
impossible -- "is the sample big enough?" and "do we have sufficient history?" are the
same question wearing different words, and nothing could tell that they were. With fixed
keys, deduplication is EXACT. A question either has been asked or has not.

That exactness is also what makes termination condition 4 (question pool exhausted)
reachable and testable, rather than theoretical.

ORDERING IS STRUCTURAL
----------------------
Cross-examination runs BEFORE confidence, never after. Confidence caps depend on the
outcome (Gate 7 caps at Low when the conclusion did not survive), so computing confidence
first and challenging afterwards would produce a number that cannot be corrected.

THE ITERATION BOUND
-------------------
Maximum 3 iterations. Reinvestigate is NOT available where the bound is reached, the
previous iteration retrieved no new evidence, or every applicable question has been
asked. On exhaustion the outcome is "Accepted with Caveats" or "Inconclusive" --
NEVER plain "Accepted". A conclusion that ran out of road has not been vindicated.

CATALOGUE AUTHORSHIP NOTE
-------------------------
The spec fixes the five categories and their counts (4 / 3 / 3 / 4 / 3 = 17) and gives
one example key per category. The remaining keys are authored here to those counts and
category meanings. They are versioned configuration -- `CATALOGUE_VERSION` is recorded on
every RCA so a change is visible.
"""
from .common import num

CATALOGUE_VERSION = "2.0.0"
MAX_ITERATIONS = 3

# --- Outcomes -----------------------------------------------------------------
ACCEPTED = "Accepted"
ACCEPTED_WITH_CAVEATS = "Accepted with Caveats"
REINVESTIGATE = "Reinvestigate"
REJECT = "Reject"
INCONCLUSIVE = "Inconclusive"

# --- Answer verdicts ----------------------------------------------------------
SUPPORTS = "supports"
WEAKENS = "weakens"
REFUTES = "refutes"
UNANSWERED = "unanswered"

# --- Categories ---------------------------------------------------------------
STAT, HIST, BIZ, DATA, ALT = ("Statistical Validation", "Historical Validation",
                              "Business Validation", "Data Validation",
                              "Alternative Explanation")

ALL_CATS = ("Calendar", "Demand", "Forecast", "Business", "Statistical", "Data Quality")


def _g(d, *path, default=None):
    cur = d
    for p in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(p)
    return cur if cur is not None else default


def _a(verdict, detail, evidence=None):
    return {"verdict": verdict, "detail": detail, "evidence": evidence or []}


# ==============================================================================
# THE CHALLENGE QUESTION CATALOGUE -- 17 questions, 5 categories, fixed keys
# ==============================================================================
def _q(key, category, text, applies_to, answer_fn):
    return {"semantic_key": key, "category": category, "question": text,
            "applies_to": applies_to, "answer": answer_fn}


CATALOGUE = [
    # ---- Statistical Validation (4) ----
    _q("STAT_SIGNIFICANCE", STAT,
       "Is the deviation large enough to be distinguishable from this queue's normal weekly variation?",
       ALL_CATS,
       lambda f, h: (
           _a(SUPPORTS, f"The miss is {_g(f,'deviation','times_usual'):.1f}x this queue's typical "
                        f"weekly variation.", ["this_week_vs_usual"])
           if isinstance(_g(f, "deviation", "times_usual"), (int, float))
           and _g(f, "deviation", "times_usual") >= 1.5 else
           _a(WEAKENS, "The miss is within the range this queue moves in most weeks, so it may "
                       "be ordinary variation rather than a distinct event.", ["this_week_vs_usual"])
           if isinstance(_g(f, "deviation", "times_usual"), (int, float)) else
           _a(UNANSWERED, "Typical weekly variation could not be computed for this queue."))),

    _q("STAT_SAMPLE_ADEQUACY", STAT,
       "Were enough comparable weeks available for the statistics to mean anything?",
       ALL_CATS,
       lambda f, h: (
           _a(SUPPORTS, f"{_g(f,'history','weeks_of_actuals',default=0)} weeks of actuals is "
                        f"ample for the tests run.", ["history"])
           if (_g(f, "history", "weeks_of_actuals", default=0) or 0) >= 104 else
           _a(WEAKENS, f"Only {_g(f,'history','weeks_of_actuals',default=0)} weeks of actuals; "
                       f"below the 104 the framework expects, so seasonal and trend findings are "
                       f"less dependable.", ["history"]))),

    _q("STAT_METRIC_AGREEMENT", STAT,
       "Do the statistical measures agree with one another, or do they point in different directions?",
       ("Statistical", "Forecast", "Demand"),
       lambda f, h: (
           _a(SUPPORTS, f"{_g(f,'statistics','supporting',default=0)} of "
                        f"{_g(f,'statistics','executed',default=0)} measures point the same way.",
              ["statistics"])
           if (_g(f, "statistics", "executed", default=0) or 0) >= 2
           and (_g(f, "statistics", "supporting", default=0) or 0)
           / max(1, _g(f, "statistics", "executed", default=1)) >= 0.6 else
           _a(WEAKENS, "The measures do not agree, so no single statistical story is settled.",
              ["statistics"])
           if (_g(f, "statistics", "executed", default=0) or 0) >= 2 else
           _a(UNANSWERED, "Fewer than two measures were executed; there is nothing to compare."))),

    _q("STAT_OUTLIER_DEPENDENCE", STAT,
       "Does the conclusion depend on a single unusual week that may itself be wrong?",
       ALL_CATS,
       lambda f, h: (
           _a(WEAKENS, "The recorded value for this week is itself flagged as questionable, so "
                       "any explanation built on it inherits that doubt.", ["data_quality"])
           if _g(f, "data_quality", "suspect") else
           _a(SUPPORTS, "The recorded value is plausible against this queue's history.",
              ["data_quality"]))),

    # ---- Historical Validation (3) ----
    _q("HIST_PRECEDENT", HIST,
       "Has this queue behaved this way before, and did the same explanation hold then?",
       ALL_CATS,
       lambda f, h: (
           _a(SUPPORTS, f"{_g(f,'history','precedents',default=0)} comparable prior case(s) exist "
                        f"for this queue.", ["historical_precedent"])
           if (_g(f, "history", "precedents", default=0) or 0) > 0 else
           _a(UNANSWERED, "No comparable prior case exists for this queue, so precedent can "
                          "neither support nor contradict the conclusion."))),

    # For a Calendar hypothesis this question tests the hypothesis's OWN premise, so a
    # negative answer is fatal rather than merely weakening. For other categories the same
    # fact is only a caveat -- it rules out a seasonal reading without touching the claim.
    _q("HIST_SEASONAL_RECURRENCE", HIST,
       "Does the same period in previous years show the same movement?",
       ("Calendar", "Demand", "Statistical"),
       lambda f, h: (
           _a(SUPPORTS, "The same fiscal period moved the same way in prior years.",
              ["seasonality"])
           if _g(f, "statistics", "seasonal_material") else
           _a(REFUTES, "The same fiscal period in prior years does not show this movement, so a "
                       "seasonal explanation cannot stand.", ["seasonality"])
           if (h.get("category") == "Calendar") else
           _a(WEAKENS, "The same fiscal period in prior years does not show this movement, so a "
                       "seasonal reading is not supported.", ["seasonality"]))),

    _q("HIST_TREND_CONSISTENCY", HIST,
       "Is this consistent with the queue's established direction of travel, or a break from it?",
       ("Forecast", "Demand", "Statistical"),
       lambda f, h: (
           _a(SUPPORTS, "The movement continues the queue's established direction.", ["trend"])
           if _g(f, "statistics", "trend_meaningful") else
           _a(WEAKENS, "No established direction exists for this queue, so the movement cannot be "
                       "attributed to a continuing trend.", ["trend"]))),

    # ---- Business Validation (3) ----
    _q("BIZ_RULE_CONSISTENCY", BIZ,
       "Does any business rule contradict this conclusion?",
       ALL_CATS,
       lambda f, h: (
           _a(REFUTES, f"A business rule contradicts this conclusion: "
                       f"{_g(f,'business_rules','contradiction')}", ["business_rule"])
           if _g(f, "business_rules", "contradiction") else
           _a(SUPPORTS, "No business rule contradicts this conclusion.", ["business_rule"]))),

    _q("BIZ_DRIVER_APPLICABILITY", BIZ,
       "Is the driver being blamed one that actually moves this queue?",
       ("Business",),
       lambda f, h: (
           _a(SUPPORTS, f"{_g(f,'drivers','primary')} passed the relevance gate for this queue.",
              ["driver_gate"])
           if _g(f, "drivers", "any_relevant") else
           _a(REFUTES, "No driver passes the relevance gate for this queue, so a driver-based "
                       "explanation cannot be supported here.", ["driver_gate"]))),

    _q("BIZ_MATERIALITY", BIZ,
       "Is the deviation large enough in absolute contacts to be worth acting on?",
       ALL_CATS,
       lambda f, h: (
           _a(SUPPORTS, f"{abs(_g(f,'deviation','abs_variance',default=0) or 0):,.0f} contacts is "
                        f"above the materiality floor.", ["materiality"])
           if _g(f, "deviation", "material", default=True) else
           _a(WEAKENS, f"Only {abs(_g(f,'deviation','abs_variance',default=0) or 0):,.0f} contacts "
                       f"in absolute terms -- below the materiality floor, so the percentage "
                       f"overstates the business significance.", ["materiality"]))),

    # ---- Data Validation (4) ----
    _q("DATA_SUFFICIENCY", DATA,
       "Is there enough data in this period to draw any conclusion?",
       ALL_CATS,
       lambda f, h: (
           _a(SUPPORTS, "The period is fully covered by actuals.", ["coverage"])
           if (_g(f, "period", "coverage_ratio", default=1.0) or 0) >= 0.99 else
           _a(WEAKENS, f"Only {(_g(f,'period','coverage_ratio',default=0) or 0):.0%} of the period "
                       f"has actuals, so the figure will move as the rest arrives.", ["coverage"]))),

    _q("DATA_COMPLETENESS", DATA,
       "Are any mandatory fields blank for this period?",
       ALL_CATS,
       lambda f, h: (
           _a(WEAKENS, f"{_g(f,'data_quality','mandatory_blank_count',default=0)} mandatory "
                       f"field(s) blank.", ["data_quality"])
           if (_g(f, "data_quality", "mandatory_blank_count", default=0) or 0) > 0 else
           _a(SUPPORTS, "All mandatory fields are present.", ["data_quality"]))),

    _q("DATA_CREDIBILITY", DATA,
       "Could the recorded figure itself be wrong rather than the business having changed?",
       ALL_CATS,
       lambda f, h: (
           _a(REFUTES, "The recorded figure is not credible against this queue's history, so it "
                       "should be validated at source before any business explanation is accepted.",
              ["data_quality"])
           if _g(f, "data_quality", "suspect") and h.get("category") != "Data Quality" else
           _a(SUPPORTS, "The recorded figure is credible.", ["data_quality"]))),

    _q("DATA_MAPPING_INTEGRITY", DATA,
       "Did the queue's mapping or structure change in a way that would move volume artificially?",
       ALL_CATS,
       lambda f, h: (
           _a(WEAKENS, "A lineage or mapping change affects this queue in this period, so part of "
                       "the movement may be structural rather than demand.", ["lineage"])
           if _g(f, "lineage", "event_in_period") or _g(f, "data_quality", "unmapped_dimension")
           else _a(SUPPORTS, "No mapping or lineage change affects this queue in this period.",
                   ["lineage"]))),

    # ---- Alternative Explanation (3) ----
    _q("ALT_STRONGER_HYPOTHESIS", ALT,
       "Does another surviving hypothesis explain the same facts at least as well?",
       ALL_CATS,
       lambda f, h: (
           _a(WEAKENS, f"{_g(f,'alternatives','count',default=0)} other hypothesis(es) survived "
                       f"and explain the same movement, so this one is not uniquely supported.",
              ["hypotheses"])
           if (_g(f, "alternatives", "count", default=0) or 0) > 0 else
           _a(SUPPORTS, "No other surviving hypothesis explains this movement.", ["hypotheses"]))),

    _q("ALT_HIGHER_LEVEL", ALT,
       "Is this movement visible across the wider book, making a queue-level cause insufficient?",
       ALL_CATS,
       lambda f, h: (
           _a(WEAKENS, f"The same movement is visible at {_g(f,'ladder','inherited_from')} level, "
                       f"so a queue-specific cause does not explain all of it.", ["ladder"])
           if _g(f, "ladder", "inherited_from") else
           _a(SUPPORTS, "The wider book did not move the same way, so this is specific to this "
                        "queue.", ["ladder"]))),

    # Deliberately does NOT quote the driver-gate warning verbatim. That text already
    # appears once in the evidence, and repeating it here produced three near-identical
    # paragraphs differing only in a coefficient -- which reads as three separate findings
    # when it is one finding stated three times.
    _q("ALT_REVERSE_CAUSATION", ALT,
       "Could the relationship run the other way, or both follow a third factor?",
       ("Business", "Statistical"),
       lambda f, h: (
           _a(WEAKENS, "The drivers that look related to demand only track it across the period "
                       "as a whole, not week to week, so the direction of cause cannot be "
                       "established from this data.", ["driver_gate"])
           if _g(f, "drivers", "trend_warning") else
           _a(SUPPORTS, "The relationship holds week to week, not merely across the period as a "
                        "whole.", ["driver_gate"]))),
]


def _applicable(hypothesis_category, already_asked):
    """catalogue WHERE applies_to CONTAINS category AND key NOT IN already_asked."""
    return [q for q in CATALOGUE
            if hypothesis_category in q["applies_to"]
            and q["semantic_key"] not in already_asked]


def examine(hypothesis, features, max_iterations=MAX_ITERATIONS):
    """Run the bounded challenge loop against one hypothesis.

    Returns the outcome, every question asked with its answer, and the termination reason.
    Everything is recorded -- the Cross-Examination Report is a named output, so a
    question that was asked and answered weakly must be visible, not quietly dropped.
    """
    category = hypothesis.get("category") or "Statistical"
    asked, rounds = set(), []
    refuted = False
    weakness_count = 0
    termination = None

    for iteration in range(1, (max_iterations or MAX_ITERATIONS) + 1):
        pool = _applicable(category, asked)
        if not pool:
            termination = ("Every applicable question in the catalogue has been asked "
                           "(pool exhausted).")
            break

        answers = []
        for q in pool:
            try:
                ans = q["answer"](features or {}, hypothesis)
            except Exception as exc:
                ans = _a(UNANSWERED, f"could not be evaluated ({exc})")
            asked.add(q["semantic_key"])
            answers.append({"semantic_key": q["semantic_key"], "category": q["category"],
                            "question": q["question"], **ans})

        rounds.append({"iteration": iteration, "questions_asked": len(answers),
                       "answers": answers})

        refuted = refuted or any(a["verdict"] == REFUTES for a in answers)
        weakness_count += sum(1 for a in answers if a["verdict"] == WEAKENS)

        if refuted:
            termination = "A question refuted the conclusion; the loop stopped early."
            break

        # Early termination: an iteration that retrieved no new evidence ends the loop.
        if all(a["verdict"] == UNANSWERED for a in answers):
            termination = "The iteration retrieved no new evidence; the loop ended early."
            break

        # Everything applicable has now been asked, so a further iteration is not available.
        if not _applicable(category, asked):
            termination = "All applicable questions were asked within this iteration."
            break
    else:
        termination = (f"The iteration bound of {max_iterations or MAX_ITERATIONS} was reached "
                       f"without resolution.")

    all_answers = [a for r in rounds for a in r["answers"]]
    supports = sum(1 for a in all_answers if a["verdict"] == SUPPORTS)
    weakens = sum(1 for a in all_answers if a["verdict"] == WEAKENS)
    refutes = sum(1 for a in all_answers if a["verdict"] == REFUTES)
    unanswered = sum(1 for a in all_answers if a["verdict"] == UNANSWERED)

    # --- Outcome ---------------------------------------------------------------
    # A refutation is decisive. Otherwise weaknesses decide between clean acceptance and
    # acceptance with caveats. A conclusion that ran out of iterations is NEVER plain
    # Accepted -- exhaustion is not vindication.
    bound_reached = "iteration bound" in (termination or "")
    if refutes:
        outcome = REJECT
    elif weakens == 0 and unanswered == 0:
        outcome = ACCEPTED
    elif weakens >= 3 or (weakens and bound_reached):
        outcome = ACCEPTED_WITH_CAVEATS if supports > weakens else INCONCLUSIVE
    else:
        outcome = ACCEPTED_WITH_CAVEATS

    caveats = [a["detail"] for a in all_answers if a["verdict"] == WEAKENS and a.get("detail")]

    return {
        "hypothesis": hypothesis.get("name") or hypothesis.get("id"),
        "hypothesis_id": hypothesis.get("id"),
        "outcome": outcome,
        "survived": outcome in (ACCEPTED, ACCEPTED_WITH_CAVEATS),
        "iterations_run": len(rounds),
        "questions_asked": len(all_answers),
        "supports": supports, "weakens": weakens, "refutes": refutes, "unanswered": unanswered,
        "caveats": caveats,
        "rounds": rounds,
        "termination_reason": termination,
        "catalogue_version": CATALOGUE_VERSION,
        "catalogue_size": len(CATALOGUE),
    }


def examine_all(hypotheses, features, max_iterations=MAX_ITERATIONS):
    """Challenge every surviving hypothesis. Returns (survivors, reports)."""
    reports = [examine(h, features, max_iterations) for h in (hypotheses or [])]
    survivors = [h for h, r in zip(hypotheses or [], reports) if r["survived"]]
    return survivors, reports
