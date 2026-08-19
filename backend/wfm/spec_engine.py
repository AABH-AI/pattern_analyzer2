# -*- coding: utf-8 -*-
"""The canonical 15-step RCA workflow.

Implements `FC_RCA_RCA_Methodology.md` section 6 -- the CANONICAL EXECUTION SEQUENCE.

WHY THIS IS A NEW MODULE RATHER THAN A REWRITE OF investigation_engine.py
--------------------------------------------------------------------------
The existing engine is wired to the live endpoint and is what the console renders today.
Replacing it in place would mean the tool is broken for however long the conversion takes,
with no way back and no way to compare. Running the two side by side means:

    * nothing that works today stops working
    * the same queue can be investigated both ways and the outputs put next to each other,
      which is exactly what "show the manager the results" needs
    * rollback is a query parameter, not a revert

Select it with `?mode=spec`. `?mode=wfm` remains the default and is untouched.

THE SEQUENCE -- no step may be skipped
---------------------------------------
     1 Receive Forecast Data          9 Evaluate Statistical Evidence
     2 Validate Data Quality         10 Recursive Root Cause Reasoning
     3 Calculate Forecast Adherence  11 Cross-Examination     <- bounded loop
     4 Detect Significant Deviation  12 Assign Confidence
     5 Build Business Context        13 Generate RCA
     6 Generate Candidate Hypotheses 14 Generate Executive Summary  <- the only LLM call
     7 Collect Supporting Evidence   15 Persist Audit Trail
     8 Collect Contradictory Evidence

TWO ORDERINGS ARE STRUCTURAL AND NOT CONFIGURABLE
---------------------------------------------------
    Step 6 before Step 9   Hypotheses SELECT the metrics. Statistics never run first
                           looking for patterns -- that is fishing, and it finds
                           something every time.
    Step 11 before Step 12 Cross-examination can return Reinvestigate or Reject, and
                           confidence Gate 7 depends on the outcome. Scoring first and
                           challenging afterwards produces a number that cannot be fixed.

WHAT THE LLM DOES HERE
----------------------
Step 14, and nothing else. By the time it is called the cause is selected, the evidence
is collected, the confidence is calculated and the recommendations are derived. It writes
prose. If it fails, the RCA is still complete and is marked Incomplete -- an LLM failure
never blocks an RCA.
"""
import time as _time
from datetime import datetime, timezone
import hashlib
import json

from . import confidence as conf
from . import cross_examination as cx
from . import driver_gate
from . import fc_evidence
from . import fiscal_calendar as fcal
from . import hypothesis_catalogue as cat
from . import decision_card
from . import narrative_prompt
from . import recursive_why
from . import why_rephrase
from . import why_prompt
from .context_repository import holiday_context
from .common import adherence_pct, num, rnd
from .llm_client import chat_json, timeout_from_config

# Spec: RCA Generation Threshold is +/-5% and is NOT configurable (Business Rules 5A).
# The display filter is a separate, configurable presentation control that must never
# create, trigger or invalidate an RCA.
GENERATION_THRESHOLD_PCT = 5.0

# Materiality floor -- a worklist control only. A 40% miss on 12 contacts is arithmetically
# large and operationally irrelevant; the floor keeps it out of the worklist WITHOUT
# suppressing the RCA itself.
MATERIALITY_FLOOR_CONTACTS = 50

MAJOR_DEVIATION_PCT = 75.0

INCONCLUSIVE = "Inconclusive"


# ==============================================================================
# Steps 1-3
# ==============================================================================
def _fingerprint(rows):
    """Input_Fingerprint -- lets a re-run be checked for data change (Methodology 7)."""
    payload = json.dumps(rows, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def _holiday_effect_for(history):
    """Do holiday weeks actually move THIS queue? Group contrast, not a rank correlation --
    Holiday_Count is 0 in most weeks so ranks would be almost all ties."""
    hol = [num(h.get("Actual_Offered")) for h in history or []
           if (num(h.get("Holiday_Count")) or 0) > 0 and h.get("Actual_Offered") is not None]
    nor = [num(h.get("Actual_Offered")) for h in history or []
           if (num(h.get("Holiday_Count")) or 0) == 0 and h.get("Actual_Offered") is not None]
    if len(hol) < 3 or len(nor) < 3:
        return {"material": False, "reason": f"only {len(hol)} holiday week(s) in history"}
    mh, mn = sum(hol) / len(hol), sum(nor) / len(nor)
    if not mn:
        return {"material": False, "reason": "no normal-week baseline"}
    diff = (mh - mn) / mn * 100.0
    return {"material": abs(diff) >= 5.0, "difference_pct": round(diff, 1),
            "avg_holiday": round(mh), "avg_normal": round(mn),
            "holiday_weeks": len(hol), "normal_weeks": len(nor)}





def _derived_facts(history, target_week, ctx, gates, m):
    """Flat, pre-answered statements -- the facts questions keep needing.

    Two separate problems this solves, both observed live.

    FIRST, retrieval from nested JSON is unreliable. Asked "when did under-forecasting
    start?", the model answered "that data is not available" while holding a 26-row series
    with a signed gap on every row and 13 consecutive negative weeks in it. The figure was
    there; reading it out of nested structure was the failure. A flat labelled sentence is
    read correctly where a nested lookup is not.

    SECOND, anything stated here is arithmetic the model no longer performs. The engine is
    deterministic and reproducible; the model is neither. Every fact moved into this block
    is one fewer chance to get a number wrong.
    """
    rows = [(h.get("Fiscal_Week"), num(h.get("Actual_Offered")), num(h.get("fcst_offered")))
            for h in (history or [])]
    rows = [(w, a, f) for w, a, f in rows if a is not None and f is not None]
    facts = []
    if not rows:
        return facts

    # The run of same-direction misses ending at the target -- "how long has this been
    # going wrong?", asked in some form on nearly every queue.
    tgt_dir = None
    streak, first_of_streak = 0, None
    for w, a, f in reversed(rows):
        d = "under" if a > f else "over"
        if tgt_dir is None:
            tgt_dir = d
        if d != tgt_dir:
            break
        streak += 1
        first_of_streak = w
    if streak > 1:
        facts.append(
            f"This queue has now missed in the SAME direction ({tgt_dir}-forecast) for "
            f"{streak} consecutive weeks. The run began at fiscal week {first_of_streak}.")
    else:
        facts.append(f"This week's {tgt_dir}-forecast does not continue a run -- the "
                     f"previous week missed the other way.")

    # The plan-reissue facts that used to sit here are DELETED. They were derived from
    # `Projection_plan_name`, which this engine treats as non-existent -- see the note above
    # `miss_streak` in fc_evidence.py. Nothing replaces them: no substitute for a reissue was
    # invented, and the model is not told the plan was or was not revisited.

    # Same week last year -- the comparison a manager reaches for first.
    ly = next((r for r in rows if target_week and int(r[0]) == int(target_week) - 100), None)
    tgt = next((r for r in rows if target_week and int(r[0]) == int(target_week)), None)
    if ly and tgt and ly[1]:
        chg = (tgt[1] - ly[1]) / ly[1] * 100
        facts.append(
            f"Same week last year (fiscal week {ly[0]}) actual demand was {ly[1]:,.0f} "
            f"contacts against a plan of {ly[2]:,.0f}. This year's actual of {tgt[1]:,.0f} "
            f"is {abs(chg):.0f}% {'higher' if chg > 0 else 'lower'} than that.")

    hol = (ctx or {}).get("holiday") or {}
    if hol.get("applies"):
        facts.append(f"Holiday calendar: {', '.join(hol.get('names') or [])} "
                     f"{hol.get('reading', '')}")

    if not (gates or {}).get("any_driver_relevant"):
        facts.append("No business driver (units under warranty, planned shipments) tracks "
                     "this queue's demand closely enough to be used, so no driver-based "
                     "answer exists for any question about this week.")
    return facts


def _period_aggregates(history):
    """Cumulative gap and worst weeks -- the arithmetic questions keep asking for.

    "What was the cumulative difference over 13 weeks and which weeks contributed most?"
    is a fair question and the answer is a sum, not a judgement. Computing it here means
    the answerer reads a figure instead of attempting mental arithmetic over 26 rows.
    """
    rows = [(h.get("Fiscal_Week"), num(h.get("Actual_Offered")), num(h.get("fcst_offered")))
            for h in (history or [])]
    rows = [(w, a, f) for w, a, f in rows if a is not None and f is not None]
    if not rows:
        return {"available": False}

    def block(n):
        sel = rows[-n:]
        gaps = [(w, a - f) for w, a, f in sel]
        worst = sorted(gaps, key=lambda g: -abs(g[1]))[:3]
        over = len([g for _, g in gaps if g < 0])
        return {"weeks": len(sel),
                "cumulative_gap_contacts": rnd(sum(g for _, g in gaps)),
                "mean_gap_per_week": rnd(sum(g for _, g in gaps) / len(gaps)),
                "weeks_over_forecast": over,
                "weeks_under_forecast": len(gaps) - over,
                "largest_deviations": [{"fiscal_week": w, "gap_contacts": rnd(g)}
                                       for w, g in worst]}

    return {"available": True, "last_13_weeks": block(13), "last_26_weeks": block(26)}




def _validate(target_fields, history):
    """Step 2. Returns (issues, suppressions) -- suppressions block hypotheses later."""
    issues, suppressions = [], {}
    mandatory = ("Actual_Offered", "fcst_offered", "Fiscal_Week", "Forecast_name")
    blanks = [f for f in mandatory if target_fields.get(f) in (None, "")]
    if blanks:
        issues.append(f"mandatory field(s) blank: {', '.join(blanks)}")

    fc = num(target_fields.get("fcst_offered"))
    if fc is not None and fc == 0:
        issues.append("forecast is zero -- adherence is undefined")

    # BR-112: warranty Tier C means the shipment/warranty data is broken, so any hypothesis
    # resting on it is SUPPRESSED (could have been tested, was not) rather than
    # NotApplicable (never relevant). The distinction drives different actions.
    tier = target_fields.get("Warranty_Tier")
    if tier == "C":
        suppressions["BUS-01"] = ("warranty data for this queue fails the Tier C integrity "
                                  "check (BR-112), so warranty mix could not be tested")
    return {"issues": issues, "clean": not issues,
            "mandatory_blank_count": len(blanks)}, suppressions


# ==============================================================================
# Step 5 -- Business Context
# ==============================================================================
def _build_context(target_fields, history, wfm_context, grain, target_week):
    """Step 5. Only built for periods that require investigation (Step 4 precedes it)."""
    all_weeks = [h.get("Fiscal_Week") for h in history]
    year = fcal.fiscal_year(target_week)
    year_len = fcal.classify_year(all_weeks, year)
    year_len = year_len if year_len in (52, 53) else 52

    period = fcal.period_weeks(grain, target_week, year_len)
    with_actuals = [w for w in period
                    if any(str(h.get("Fiscal_Week")) == str(w)
                           and h.get("Actual_Offered") is not None for h in history)]
    # The target week's own actual is present by definition even if history excludes it.
    if target_week in period and target_week not in with_actuals:
        with_actuals.append(target_week)

    coverage = (len(with_actuals) / len(period)) if period else 1.0
    hol = holiday_context(target_fields.get("Country"), target_week,
                          num(target_fields.get("Holiday_Count")))
    elements = _context_elements(target_fields, wfm_context, hol)

    return {
        "grain": grain,
        "calendar": fcal.describe(target_week, year_len),
        "year_length": year_len,
        "period_weeks": period,
        "weeks_with_actuals": len(with_actuals),
        "weeks_in_period": len(period),
        "coverage_ratio": round(coverage, 4),
        "complete": coverage >= 0.999,
        "holiday_count": num(target_fields.get("Holiday_Count")) or 0,
        # No longer hardcoded False. The Holiday Calendar resolves named holidays for this
        # country and week AND those in adjacent weeks whose impact window reaches it --
        # which, measured across FW202701-22, covers 58.7% of flagged queue-weeks against
        # the 24.3% the row flag alone could see.
        "holiday": hol,
        "holiday_in_impact_window": bool(hol.get("applies")),
        "spans_month_boundary": fcal.spans_month_boundary(period, year_len),
        "spans_quarter_boundary": fcal.spans_quarter_boundary(period, year_len),
        "elements": elements,
    }


def _context_elements(target_fields, wfm_context, hol=None):
    """Which context elements APPLY to this queue, and which are actually present.

    The Available / NotApplicable distinction matters: an element that is irrelevant to
    the queue is excluded without penalty, while one that is relevant but absent drags
    ContextCompleteness down. Conflating them would reward missing data.
    """
    country = (target_fields.get("Country") or "").strip()
    aggregate_country = country.lower() in ("", "multiple", "various", "aggregate", "all")
    has_asu = num(target_fields.get("Actual_ASU")) is not None
    has_ship = num(target_fields.get("Final_Units")) is not None

    els = [
        {"element": "Fiscal calendar", "applicable": True, "available": True},
        {"element": "Holiday calendar", "applicable": not aggregate_country,
         "available": bool((hol or {}).get("available"))},
        {"element": "Warranty coverage", "applicable": has_ship, "available": has_ship},
        {"element": "Installed base (ASU)", "applicable": has_asu, "available": has_asu},
        {"element": "Business events", "applicable": False,       # repository not deployed
         "available": False,
         "note": "Business Event Repository is not deployed, so this is NotApplicable and "
                 "carries no confidence penalty (BR-202)."},
        {"element": "Volume band", "applicable": True,
         "available": target_fields.get("Volume_Category") is not None},
        {"element": "Queue metadata", "applicable": True, "available": True},
    ]
    applicable = [e for e in els if e["applicable"]]
    return {"elements": els,
            "applicable": len(applicable),
            "available": len([e for e in applicable if e["available"]])}


# ==============================================================================
# Steps 7-8 -- Evidence
# ==============================================================================
def _evidence(features, stats, gates, ladder):
    """Steps 7 and 8. Supporting and contradictory are collected as SEPARATE steps --
    contradiction is actively sought, not merely noted if it happens to turn up."""
    supporting, contradictory = [], []

    top = (stats or {}).get("strongest_finding") or {}
    if top:
        supporting.append({"text": top.get("statement"), "strength": "Strong",
                           "family": "deterministic_statistic",
                           "source": top.get("metric")})

    # Drivers that only DRIFT with demand are evidence against leaning on them. They are
    # collapsed into ONE line rather than emitted per driver: the warning text is identical
    # apart from the coefficient, so three of them read as three findings when they are one
    # finding about three drivers. Naming the drivers and their figures in a single sentence
    # says strictly more in a quarter of the space.
    drifters, genuine, failed = [], [], []
    for g in (gates or {}).get("results", []):
        if not g.get("relevant"):
            failed.append(g)
        elif g.get("trend_warning"):
            drifters.append(g)
        else:
            genuine.append(g)

    for g in genuine:
        supporting.append({"text": g.get("reason"), "strength": "Moderate",
                           "family": "deterministic_statistic", "source": g.get("driver")})

    if drifters:
        # Each figure carries its own driver name. A list of bare coefficients is unreadable:
        # the reader cannot tell which number belongs to which driver.
        detail = "; ".join(f"{driver_gate.label_for(g['driver'])} scores {g['correlation']:+.2f} "
                           f"across the period but only {g['co_movement_r']:+.2f} week to week"
                           for g in drifters)
        contradictory.append({
            "text": (f"{len(drifters)} driver(s) track demand when you compare totals across the "
                     f"whole period, but not from one week to the next — {detail}. Two figures "
                     f"that both drift the same way over years without moving together in any "
                     f"given week are following a shared trend, not driving each other, so none "
                     f"of them can carry a cause here. (This is about raw totals versus "
                     f"week-to-week change — nothing to do with Region or Country level.)"),
            "strength": "Moderate", "family": "deterministic_statistic",
            "source": ", ".join(g["driver"] for g in drifters)})

    if failed:
        detail = "; ".join(f"{driver_gate.label_for(g['driver'])} "
                           f"{(('r=%+.2f' % g['correlation']) if isinstance(g.get('correlation'), (int, float)) else 'not measurable')}"
                           for g in failed)
        contradictory.append({
            "text": (f"{len(failed)} driver(s) do not track this queue's demand at all — "
                     f"{detail} — so a driver-based explanation is not available for this queue."),
            "strength": "Moderate", "family": "deterministic_statistic",
            "source": ", ".join(g["driver"] for g in failed)})

    if (ladder or {}).get("inherited_from"):
        contradictory.append({
            "text": (f"The same movement is visible at {ladder['inherited_from']} level, so a "
                     f"queue-specific cause does not account for all of it."),
            "strength": "Strong", "family": "deterministic_statistic", "source": "ladder"})

    return supporting, contradictory


def _fc_evidence_items(fc):
    """Turn the new deterministic blocks into FC evidence items (steps 7 and 8).

    THREE RULES, each of which exists because breaking it produced a wrong report.

    STRENGTH FOLLOWS COVERAGE, NOT MAGNITUDE. A sparse driver is never Strong however extreme its
    coefficient. This is the exact failure the upgrade exists to fix: a z-score of 23.33 computed
    from two observations armed a precondition and shipped a cause at 85% confidence. A big number
    from a tiny sample is weak evidence, and the strength label has to say so.

    SOURCE FAMILY IS ASSIGNED HONESTLY. Confidence Gate 6 caps at Low when every item comes from a
    single family, so mislabelling statistics as business rules would defeat a cap that exists to
    catch exactly that. The holiday CALENDAR is a business record; the holiday EFFECT measured from
    this queue's history is a statistic; the plan vintage is a recorded process fact; phase
    instances and momentum precedents are historical precedent. They are tagged as what they are.

    CONTRADICTORY MEANS ARGUES AGAINST, NOT MERELY UNHELPFUL. A mechanism rejected on direction is
    genuine contradictory evidence. An absent driver is a limitation, not a contradiction, and
    filing it as one would inflate the ContradictoryEvidence weight and depress confidence for
    having less data -- which is backwards.
    """
    supporting, contradictory = [], []

    def add(bucket, text, strength, family, source, evidence_id=None):
        if not text:
            return
        item = {"text": text, "strength": strength, "family": family, "source": source}
        if evidence_id:
            item["evidence_id"] = evidence_id
        bucket.append(item)

    resp, lag = fc.get("response") or {}, fc.get("lag") or {}
    hol, asu = fc.get("holiday") or {}, fc.get("asu") or {}
    mech = fc.get("mechanism") or {}

    # --- the miss decomposition: which side of the gap was already there (section 13) ---
    dec = resp.get("miss_decomposition") or {}
    if dec.get("available") and dec.get("reconciles"):
        add(supporting, dec.get("reading"), "Strong", "deterministic_statistic",
            "miss_decomposition", "E2")

    # --- the forecast-response test and its gate (sections 14-15) ---
    r = resp.get("response") or {}
    gate = resp.get("forecastability_gate") or {}
    if r.get("classification") and r.get("classification") != "not_testable":
        supported = gate.get("supports_forecast_response_failure")
        add(supporting if supported else contradictory,
            (f"Forecast response: {r.get('classification').replace('_', ' ')}. "
             f"{r.get('reason')}" if supported else
             f"{gate.get('verdict')} ({r.get('classification').replace('_', ' ')}: "
             f"{r.get('reason')})"),
            "Strong" if supported else "Moderate",
            "deterministic_statistic", "forecast_response", "E5")

    fcb = resp.get("forecastability") or {}
    if fcb.get("classification") in ("LOW_PREDICTABILITY", "NOT_TESTABLE"):
        # Evidence AGAINST calling this a forecast failure. It belongs in the contradictory list
        # because that is precisely what it argues against.
        add(contradictory, fcb.get("reason"), "Strong", "historical_precedent",
            "forecastability", "E5")

    # --- driver lags (sections 16-18) ---
    for d in lag.get("drivers") or []:
        if d.get("usable_as_evidence"):
            # Stability moderates strength: halves that disagree cannot carry a Strong label.
            strength = "Strong" if d.get("stability") == "stable" else "Moderate"
            add(supporting, d.get("reading"), strength, "deterministic_statistic",
                d.get("driver"), "E7" if d.get("driver") == "Final_Units" else None)
        elif d.get("coverage") == "sparse":
            add(contradictory, d.get("reading"), "Weak", "deterministic_statistic",
                d.get("driver"), "E8" if d.get("driver") == "Final_upp_units" else None)
        # `absent` is deliberately NOT filed as contradictory -- see the docstring.

    # --- calendar (sections 22-24) ---
    if hol.get("applies") and hol.get("calendar_names"):
        add(supporting,
            f"Holiday calendar: {', '.join(hol['calendar_names'])}. {hol.get('reading') or ''}"
            .strip(),
            "Moderate", "business_rule", "holiday_calendar", "E10")
    cap = hol.get("forecast_capture") or {}
    if cap.get("classification") in ("under_reacted", "over_reacted", "wrong_direction",
                                     "delayed"):
        add(supporting, cap.get("reason"), "Moderate", "historical_precedent",
            "holiday_forecast_capture", "E11")
    elif cap.get("classification") == "inconsistent_history":
        # Section 24, stated explicitly: a visible pattern that is not consistent enough to be a
        # forecastable signal argues AGAINST holding the plan to it.
        add(contradictory, cap.get("reason"), "Strong", "historical_precedent",
            "holiday_forecast_capture", "E11")

    # --- ASU decomposition (section 19) ---
    if asu.get("available"):
        add(supporting, asu.get("reading"), "Strong", "deterministic_statistic",
            "asu_decomposition", "E6")
    elif asu.get("availability") == MISSING_AVAILABILITY:
        add(contradictory, f"ASU decomposition could not be performed: {asu.get('reason')}",
            "Weak", "deterministic_statistic", "asu_decomposition", "E6")

    # --- mechanisms rejected on direction (section 32) ---
    for c in mech.get("rejected_for_direction") or []:
        add(contradictory, (c.get("direction_coherence") or {}).get("reason"),
            "Strong", "business_rule", "direction_coherence", "E14")

    return supporting, contradictory


# `confidence.MISSING` under a local name -- the availability vocabulary is confidence.py's, and
# importing the constant rather than repeating the string keeps the two from drifting apart.
MISSING_AVAILABILITY = conf.MISSING


# ==============================================================================
# Confidence INPUT builders (section 28 -- inputs enhanced, model untouched)
# ==============================================================================
def _precedent_inputs(fc_holiday, fc_response):
    """(precedents_found, precedent_score) for `conf.historical_consistency`.

    BR-118 asks for provenance-weighted precedent. Two things now measure real precedent for a
    queue, and both carry their own instance count and their own consistency rate, so the combined
    score is an instance-weighted mean rather than an average of averages -- a phase with 30
    instances should not be outvoted by one with 4.

    Returns (0, None) when nothing measured precedent, which lands on NotApplicable exactly as
    before. A queue with no comparable history is not concealing evidence; there is genuinely
    nothing to be consistent with, and it must not be penalised for that.
    """
    parts = []      # (instances, consistency)

    phases = (fc_holiday or {}).get("historical_response") or {}
    if phases.get("available"):
        # The precedent that matters is for the phase the TARGET week is actually in. The other
        # phases are measured, but they are not this week's precedent.
        target_phase = (fc_holiday or {}).get("phase")
        blk = (phases.get("phases") or {}).get(target_phase) or {}
        if blk.get("testable") and blk.get("consistency") is not None:
            parts.append((blk.get("instances") or 0, blk["consistency"]))

    mom = (fc_response or {}).get("momentum_repeatability") or {}
    if mom.get("testable") and mom.get("consistency") is not None:
        parts.append((mom.get("precedents") or 0, mom["consistency"]))

    parts = [(n, c) for n, c in parts if n > 0]
    if not parts:
        return 0, None
    total = sum(n for n, _ in parts)
    score = sum(n * c for n, c in parts) / total
    return total, max(0.0, min(1.0, score))


def _method_agreement_inputs(root_cause, fc_mechanism):
    """(methods_executed, methods_concurring) for `conf.model_agreement`.

    The two methods are genuinely independent and share no code:

        1. catalogue applicability -> cross-examination -> `_select_root_cause`
        2. measured evidence -> mechanism candidates -> direction-coherence gate

    They CONCUR when the surviving mechanism's evidence bears on the very hypothesis that was
    promoted -- that is, the two paths reached compatible explanations. They DISAGREE when the
    mechanism evidence points at a different family of hypotheses entirely, which is real
    information and should cost confidence.

    Returns (1, 1) when the mechanism path could not run, which lands on NotApplicable exactly as
    before -- one method means nothing to cross-check, and that is not a weakness.
    """
    mech = fc_mechanism or {}
    if not mech.get("candidates"):
        return 1, 1
    attaches = set(mech.get("attaches_to") or ())
    if not attaches:
        return 1, 1
    hid = (root_cause or {}).get("hypothesis_id")
    return 2, (2 if hid and hid in attaches else 1)


def _business_rule_state(dq, root_cause, fc_mechanism):
    """One of supportive | neutral | not_evaluable | contradicts, for `conf.business_rule_validation`.

    THE DIRECTION-COHERENCE GATE IS A BUSINESS RULE (section 32), and in the Evidence Hierarchy a
    business rule outranks statistics. So when the promoted cause rests only on mechanisms the gate
    rejected, the rule CONTRADICTS the conclusion: the dimension scores 0.00 and Gate 2 caps the
    final level at Low. Arithmetic must not be able to outvote a rule saying the conclusion points
    the wrong way.

    Data quality still takes precedence -- a blank mandatory field means the rules could not be
    evaluated at all, and that is a different statement from a rule disagreeing.
    """
    if not (dq or {}).get("clean"):
        return "not_evaluable"

    mech = fc_mechanism or {}
    rejected = mech.get("rejected_for_direction") or []
    if not mech.get("candidates") and not rejected:
        return "neutral"

    hid = (root_cause or {}).get("hypothesis_id")
    if not hid:
        return "neutral"

    surviving = set(mech.get("attaches_to") or ())
    rejected_ids = set()
    for c in rejected:
        rejected_ids |= set(fc_evidence.MECHANISM_HYPOTHESES.get(c.get("mechanism"), ()))

    # The promoted hypothesis is carried ONLY by a mechanism that failed the direction gate.
    if hid in rejected_ids and hid not in surviving:
        return "contradicts"
    if hid in surviving:
        # Coherent AND the mechanism evidence bears on it -- the rule actively supports it.
        return "supportive"
    return "neutral"


def _context_counts(ctx, fc_holiday, fc_lag, fc_weekend):
    """(available, applicable) context elements, including what the new evidence establishes.

    `_context_elements` counts the seven original elements. Three more are now genuinely resolved
    or genuinely absent on every run, and a queue where all three were established should not be
    scored as though that context were missing. The Available/NotApplicable distinction is kept:
    an element that does not apply to the queue is EXCLUDED rather than counted as a zero, because
    counting it would penalise a queue for a question that could not sensibly be asked of it.
    """
    els = (ctx or {}).get("elements") or {}
    available = els.get("available") or 0
    applicable = els.get("applicable") or 0

    # Holiday phase: applicable wherever the holiday calendar itself is applicable for the queue.
    hol_applicable = any(e.get("element") == "Holiday calendar" and e.get("applicable")
                         for e in (els.get("elements") or []))
    if hol_applicable:
        applicable += 1
        if (fc_holiday or {}).get("available"):
            available += 1

    # Driver lag: applicable only where a hypothesis actually requested a driver.
    if (fc_lag or {}).get("requested_drivers"):
        applicable += 1
        if (fc_lag or {}).get("availability") == conf.AVAILABLE:
            available += 1

    # Data grain: always applicable and always resolved -- the module reports the grain it found,
    # so this element is Available even when the grain turns out to limit what can be analysed.
    applicable += 1
    if (fc_weekend or {}).get("grain"):
        available += 1

    return available, applicable


def _weigh(items):
    """Total independence-weighted strength, for the ContradictoryEvidence dimension."""
    seen, total = set(), 0.0
    for e in items or []:
        fam = e.get("family") or "deterministic_statistic"
        s = conf.STRENGTH.get(e.get("strength"), 0.4)
        w = conf.REPEAT_FAMILY_INDEPENDENCE if fam in seen else conf.INDEPENDENCE.get(fam, 0.6)
        seen.add(fam)
        total += s * w
    return total


# ==============================================================================
# Step 13 -- Root cause selection (deterministic decision matrix)
# ==============================================================================
# The finding's `rank_basis` and the catalogue's `metrics` name the same things with two small
# spelling differences. Mapping them is what lets a measured statement become the headline.
_RANK_BASIS_TO_METRIC = {
    "coefficient_of_variation": "variability",
    "trend+momentum": "trend",
}


def _select_root_cause(survivors, reports, stats, why=None):
    """Step 13. Deterministic: weigh cross-examination outcome, then statistical support.

    Returns Inconclusive when nothing survives. That is a correct outcome, not a failure --
    "a meaningful share of investigations will correctly reach no defensible root cause".
    """
    if not survivors:
        return {"cause_type": INCONCLUSIVE, "hypothesis_id": None,
                "statement": ("No hypothesis in the catalogue survived challenge for this "
                              "period, so no defensible root cause can be stated."),
                "selected_because": "every generated hypothesis was rejected at cross-examination"}

    by_id = {r["hypothesis_id"]: r for r in reports}
    order = {cx.ACCEPTED: 0, cx.ACCEPTED_WITH_CAVEATS: 1}

    # Which hypothesis does the STRONGEST measured evidence actually point at? Ranking on
    # cross-examination outcome alone let a hypothesis win while the best evidence in the payload
    # belonged to a different one -- on SA Indonesia FW202716 "Demand Spike" won on support counts
    # while the decisive finding (the plan set 48% below the week's own 3-year average) belonged to
    # Forecast Bias, so the report headlined a restatement of the miss instead of its cause.
    # Outcome still dominates: a hypothesis that failed challenge cannot be promoted by evidence.
    _top = (stats or {}).get("strongest_finding") or {}
    _top_basis = _RANK_BASIS_TO_METRIC.get(_top.get("rank_basis"), _top.get("rank_basis"))

    def rank(h):
        r = by_id.get(h["id"]) or {}
        carries_top = bool(_top_basis and _top_basis in (h.get("metrics") or []))
        return (order.get(r.get("outcome"), 9),
                0 if carries_top else 1,          # the strongest evidence breaks the tie
                -(r.get("supports") or 0), r.get("weakens") or 0)

    best = sorted(survivors, key=rank)[0]
    rep = by_id.get(best["id"]) or {}
    top = (stats or {}).get("strongest_finding") or {}
    # Match on what the two vocabularies actually share. The previous guard compared
    # top["cause_type"] against best["cause_type"], and catalogue entries have no cause_type key at
    # all -- so it was always None != a real string, and no report ever used a measured statement.
    _basis = top.get("rank_basis")
    _basis = _RANK_BASIS_TO_METRIC.get(_basis, _basis)
    statement = top.get("statement") if (_basis and _basis in (best.get("metrics") or [])) else None

    # Fall back to the why-chain's opening claim before the catalogue condition. The condition is a
    # test ("actual exceeds forecast beyond the volatility band"), not a finding; the why-chain's
    # first level is written about this queue and this week.
    if not statement:
        for lv in ((why or {}).get("levels") or []):
            claim = (lv.get("answer") or lv.get("claim") or "").strip()
            if claim:
                statement = claim
                break

    return {
        "cause_type": best.get("id"),
        "hypothesis_id": best.get("id"),
        "hypothesis": best.get("name"),
        "category": best.get("category"),
        "statement": statement or f"{best.get('name')} — {best.get('condition')}.",
        "cross_examination": rep.get("outcome"),
        "caveats": rep.get("caveats") or [],
        "selected_because": (f"survived cross-examination as {rep.get('outcome')} with "
                             f"{rep.get('supports')} supporting answer(s)"),
    }


# ==============================================================================
# Step 14 -- Recommendations (rule-derived, max 3)
# ==============================================================================
def _mechanism_recommendations(fc_mechanism, fc_lag, fc_signals=None, fc_holiday=None):
    """Section 44. The action follows the VERIFIED mechanism, not the hypothesis label.

    Section 44 forbids a generic "monitor the situation" where a specific action is supported, and
    it equally forbids the opposite error: telling WFM to fix a model that could not have predicted
    the movement. A low-predictability event gets an honest recommendation that says so, because
    the alternative -- demanding a model change for an unforeseeable event -- is advice that cannot
    be acted on and quietly blames the team for the weather.

    Ordered most-specific first. `_recommendations` puts these ahead of the generic rules and then
    applies the existing three-item cap.
    """
    out = []
    mech = fc_mechanism or {}
    present = set(mech.get("mechanisms") or ())

    if fc_evidence.FORECAST_BASELINE_FAILURE in present:
        out.append({"id": "M1", "priority": "High",
                    "text": ("Review the seasonal baseline and re-levelling logic for this queue: "
                             "the plan entered the period away from the level this week of the "
                             "year reliably brings."),
                    "impact": ("Corrects a standing level error that repeats every week until the "
                               "baseline is reset."),
                    "owner": "Demand / Forecast Team",
                    "follows_mechanism": fc_evidence.FORECAST_BASELINE_FAILURE})

    if fc_evidence.FORECAST_RESPONSE_FAILURE in present:
        signals = ", ".join(s.get("signal", "") for s in (fc_signals or [])
                            if s.get("detected")) or None
        out.append({"id": "M2", "priority": "High",
                    "text": ("Incorporate the identified leading signal and its observed lag into "
                             "the forecast process"
                             + (f" (signal: {signals})" if signals else "")
                             + ": the signal was available before the week and the plan did not "
                               "respond adequately to it."),
                    "impact": ("Turns a signal the process already receives into a plan movement, "
                               "which is where this miss was avoidable."),
                    "owner": "Demand / Forecast Team",
                    "follows_mechanism": fc_evidence.FORECAST_RESPONSE_FAILURE})

    if fc_evidence.CALENDAR_RESPONSE_FAILURE in present:
        out.append({"id": "M3", "priority": "High",
                    "text": ("Revisit the pre-holiday, holiday and post-holiday adjustments for "
                             "this queue: the calendar pattern is established in its own history "
                             "and the plan did not capture it."),
                    "impact": ("Holiday phases recur on a known calendar, so this is a correction "
                               "that pays back every year."),
                    "owner": "Demand / Forecast Team",
                    "follows_mechanism": fc_evidence.CALENDAR_RESPONSE_FAILURE})

    if fc_evidence.DRIVER_RESPONSE_FAILURE in present:
        for d in (fc_lag or {}).get("drivers") or []:
            if d.get("usable_as_evidence") and (d.get("best_lag_weeks") or 0) > 0:
                out.append({
                    "id": f"M4-{d['driver']}", "priority": "Medium",
                    "text": (f"Evaluate {d.get('subject') or d['driver']} as a leading demand "
                             f"input at a {d['best_lag_weeks']}-week lag, which is where its "
                             f"relationship with this queue's demand is strongest and most "
                             f"stable."),
                    "impact": ("A lagged driver is usable prospectively: the value is already "
                               "known weeks before the demand it precedes."),
                    "owner": "Demand / Forecast Team",
                    "follows_mechanism": fc_evidence.DRIVER_RESPONSE_FAILURE})
                break

    if fc_evidence.DEMAND_EVENT_LOW_PREDICTABILITY in present:
        out.append({"id": "M5", "priority": "Medium",
                    "text": ("Do not treat this as a model defect. No sufficiently repeatable "
                             "leading signal existed before the week, so keep monitoring the "
                             "available drivers and revisit adding a predictive feature only if "
                             "the pattern recurs."),
                    "impact": ("Prevents effort being spent re-tuning a model against an event it "
                               "could not have seen, and records the pattern for next time."),
                    "owner": "Demand / Forecast Team",
                    "follows_mechanism": fc_evidence.DEMAND_EVENT_LOW_PREDICTABILITY})

    # The holiday adjustment RULE, not this week's number. Emitted from the standing-bias measurement
    # rather than from the target week's capture verdict, because a week can sit inside the "captured"
    # tolerance every time while the adjustment drifts -- which is exactly what UKI Comm Client DSP
    # Standard does. Both branches are grounded in a measured finding; neither fires on a single week.
    _bias = ((fc_holiday or {}).get("plan_bias") or {})
    if _bias.get("systematic") and _bias.get("action"):
        out.append({"id": "M8", "priority": "High",
                    "text": _bias["action"],
                    "impact": ("Corrects a repeating calendar error rather than one week's plan, so "
                               "it pays back on every future holiday week."),
                    "owner": "Demand / Forecast Team",
                    "follows_mechanism": "holiday_plan_bias"})
    elif _bias.get("deteriorating") and _bias.get("deteriorating_action"):
        out.append({"id": "M9", "priority": "Medium",
                    "text": _bias["deteriorating_action"],
                    "impact": ("The direction of the adjustment is not the problem; its size is "
                               "drifting, and that is measurable and correctable."),
                    "owner": "Demand / Forecast Team",
                    "follows_mechanism": "holiday_plan_bias_widening"})

    # M6 and M7 -- "the plan was reissued and stayed wrong" and "reissue this queue's plan" -- are
    # DELETED along with the plan-vintage finding they rested on. No replacement advice is invented:
    # without the column there is no evidence about whether anybody revisited the plan, and section 44
    # forbids advice the mechanism does not support.

    return out


def _recommendations(root_cause, features, deviation, fc_mechanism=None, fc_lag=None,
                     fc_signals=None, fc_holiday=None):
    """BR-701/702/704. Rule-derived, never model-generated. Maximum three, and fewer
    where fewer are warranted -- padding a list to a target is noise, not advice.

    Mechanism-derived advice leads, because it is the specific action section 44 asks for. The
    original rules follow and still fire; the three-item cap is unchanged.
    """
    recs = list(_mechanism_recommendations(fc_mechanism, fc_lag, fc_signals, fc_holiday))
    cid = (root_cause or {}).get("hypothesis_id") or ""

    if cid.startswith("FC-") or cid.startswith("STA-02"):
        recs.append({"id": "R1", "priority": "High",
                     "text": "Re-base this queue's forward plan to its current run rate.",
                     "impact": "Removes a standing gap that repeats every week until corrected.",
                     "owner": "Demand / Forecast Team"})
    if cid == "DQ-04" or (features.get("history", {}).get("weeks_of_actuals") or 0) < 104:
        recs.append({"id": "R2", "priority": "Medium",
                     "text": "Extend the history held for this queue to at least 104 weeks.",
                     "impact": "Enables seasonal and trend testing that cannot run today.",
                     "owner": "Demand / Forecast Team"})
    if cid.startswith("DQ-") and cid != "DQ-04":
        recs.append({"id": "R3", "priority": "High",
                     "text": "Validate the recorded figure at source before acting on it.",
                     "impact": "Prevents a data fault being actioned as a business change.",
                     "owner": "Demand / Forecast Team"})
    if (deviation or {}).get("major"):
        recs.append({"id": "R4", "priority": "High",
                     "text": "Review this period manually — the deviation exceeds the major threshold.",
                     "impact": "Large deviations warrant a human check before the plan is reissued.",
                     "owner": "Demand / Forecast Team"})
    return recs[:3]


# ==============================================================================
# The workflow
# ==============================================================================
def investigate(context_bundle, llm_cfg, wfm_context, grain="weekly", model_choice=None,
               interrogate=True):
    """Run all 15 steps. No step may be skipped."""
    started = datetime.now(timezone.utc).isoformat()
    steps = []

    def _step(n, name, detail):
        steps.append({"step": n, "name": name, "detail": detail})

    # --- Step 1 ---------------------------------------------------------------
    target = (context_bundle or {}).get("target") or {}
    fields = target.get("fields") or {}
    key = target.get("key") or {}
    history = (wfm_context or {}).get("history_104") or []
    target_week = key.get("Fiscal_Week") or fields.get("Fiscal_Week")
    try:
        target_week = int(target_week)
    except (TypeError, ValueError):
        pass
    fingerprint = _fingerprint(history + [fields])
    _step(1, "Receive Forecast Data",
          f"{len(history)} history rows for {key.get('Forecast_name')} at FW{target_week}")

    # --- Step 2 ---------------------------------------------------------------
    dq, suppressions = _validate(fields, history)
    _step(2, "Validate Data Quality",
          "clean" if dq["clean"] else "; ".join(dq["issues"]))

    # --- Step 3 ---------------------------------------------------------------
    # Prefer the raw columns, but fall back to `computed`. The console always populates
    # `computed` (it is what the worklist badge is drawn from), while `fields` mirrors the
    # SOURCE columns -- and in file-upload mode those can be named differently. Reading
    # only `fields` made adherence None on exactly those queues, which ended the run at
    # step 3 with no card and no explanation.
    computed = target.get("computed") or {}
    actual = num(fields.get("Actual_Offered"))
    if actual is None:
        actual = num(computed.get("actual"))
    forecast = num(fields.get("fcst_offered"))
    if forecast is None:
        forecast = num(computed.get("forecast"))
    adherence = adherence_pct(actual, forecast)
    if adherence is None:
        adherence = num(computed.get("adherence_pct"))
    abs_variance = abs((actual or 0) - (forecast or 0))
    _step(3, "Calculate Forecast Adherence",
          f"{adherence:+.1f}%" if adherence is not None else "undefined")

    # --- Step 4 ---------------------------------------------------------------
    # The threshold is FIXED at +/-5% and is not the display filter.
    if adherence is None:
        return _incomplete(context_bundle, steps, started, fingerprint,
                           "Forecast Adherence could not be calculated for this period.")
    breaches = abs(adherence) > GENERATION_THRESHOLD_PCT
    major = abs(adherence) > MAJOR_DEVIATION_PCT and abs_variance >= MATERIALITY_FLOOR_CONTACTS
    material = abs_variance >= MATERIALITY_FLOOR_CONTACTS
    _step(4, "Detect Significant Deviation",
          f"{'breaches' if breaches else 'within'} the fixed ±{GENERATION_THRESHOLD_PCT}% "
          f"generation threshold")
    if not breaches:
        return _in_band(context_bundle, steps, started, fingerprint, adherence)

    # --- Step 5 ---------------------------------------------------------------
    ctx = _build_context(fields, history, wfm_context, grain, target_week)
    _step(5, "Build Business Context",
          f"{ctx['calendar']['label']}, coverage {ctx['coverage_ratio']:.0%}, "
          f"{ctx['elements']['available']}/{ctx['elements']['applicable']} context elements")

    # --- statistics and gates feed both hypotheses and evidence ----------------
    from . import statistical_evidence as stats_engine
    stats = stats_engine.statistical_evidence(history, target_week, adherence,
                                              GENERATION_THRESHOLD_PCT)
    gates = driver_gate.evaluate_all(history, fields.get("Offering"))
    ladder = (wfm_context or {}).get("ladder_verdict") or {}

    weeks_of_actuals = len([h for h in history if h.get("Actual_Offered") is not None])
    m = (stats or {}).get("metrics") or {}
    feat = {
        "period": ctx,
        "history": {"weeks_of_actuals": weeks_of_actuals, "precedents": 0},
        "deviation": {"adherence_pct": adherence, "abs_variance": abs_variance,
                      "material": material, "major": major,
                      "beyond_volatility_band": abs(adherence) > GENERATION_THRESHOLD_PCT,
                      "times_usual": None, "adjacent_offsetting": False},
        "forecast": {"one_sided_bias": bool((m.get("accuracy_recent") or {}).get("bias_material")),
                     "trend_direction_mismatch": bool((m.get("trend_recent") or {}).get("trend_meaningful"))},
        "statistics": {"target_is_outlier": bool((m.get("outliers") or {}).get("target_week_is_outlier")),
                       "drift_material": bool((m.get("drift_recent") or {}).get("drift_material")),
                       "momentum_material": bool((m.get("momentum") or {}).get("momentum_material")),
                       "variance_expanded": ((m.get("coefficient_of_variation_long") or {}).get("volatility_class") == "volatile"),
                       "seasonal_material": bool((m.get("seasonality") or {}).get("seasonal_material")),
                       "trend_meaningful": bool((m.get("trend_recent") or {}).get("trend_meaningful")),
                       # Agreement is "metrics supporting the conclusion / metrics executed".
                       # Counting every metric BLOCK as executed is wrong -- most of them were
                       # never asked a question. Only blocks that actually computed count, and
                       # only those that produced a material finding count as supporting.
                       "executed": len([b for b in m.values()
                                        if isinstance(b, dict) and b.get("available")]),
                       "supporting": len([b for b in m.values()
                                          if isinstance(b, dict) and b.get("available")
                                          and any(b.get(k) for k in
                                                  ("drift_material", "momentum_material",
                                                   "trend_meaningful", "seasonal_material",
                                                   "bias_material", "target_week_is_outlier"))])},
        "asu": {"applicable": num(fields.get("Actual_ASU")) is not None,
                "planned": num(fields.get("Planned_ASU")), "actual": num(fields.get("Actual_ASU")),
                "passes_relevance_gate": any(g.get("driver") == "Actual_ASU" and g.get("relevant")
                                             for g in gates.get("results", [])),
                "passes_plan_variance_gate": False, "baseline_available": True},
        "shipments": {"applicable": num(fields.get("Final_Units")) is not None,
                      "passes_relevance_gate": any(g.get("driver") == "Final_Units" and g.get("relevant")
                                                   for g in gates.get("results", []))},
        "warranty": {"tier": fields.get("Warranty_Tier"), "shipment_applicable": False,
                     "passes_relevance_gate": False},
        "data_quality": {"mandatory_blank_count": dq["mandatory_blank_count"],
                         "suspect": False, "unmapped_dimension": False,
                         "duplicates_detected": False},
        "related_queues": {"inverse_deviation": False},
        "lineage": {"event_in_period": False},
        "drivers": {"any_relevant": gates.get("any_driver_relevant"),
                    "primary": gates.get("primary_driver"),
                    "trend_warning": next((g.get("trend_warning") for g in gates.get("results", [])
                                           if g.get("trend_warning")), None)},
        "ladder": ladder,
        "business_rules": {},
    }
    tw = (m.get("coefficient_of_variation_long") or {})
    feat["deviation"]["times_usual"] = None

    # A metric block that could not be COMPUTED suppresses the hypothesis that depends on
    # it. The catalogue condition for Seasonality is only "enough history and a complete
    # period" -- it does not know whether a seasonal index could actually be built. Without
    # this the hypothesis is generated, never really tested, and can win selection on the
    # strength of questions that were never able to challenge it.
    for hid, block, label in (("CAL-04", "seasonality", "a seasonal index"),
                              ("STA-01", "outliers", "outlier bounds"),
                              ("STA-02", "drift_recent", "a drift slope"),
                              ("STA-03", "momentum", "a momentum figure")):
        blk = m.get(block) or {}
        if blk.get("available") is False:
            suppressions[hid] = (f"{label} could not be computed for this queue: "
                                 f"{blk.get('note') or 'insufficient comparable history'}")

    # --- Step 6 -- hypotheses BEFORE statistics are interpreted ----------------
    generated, not_generated = cat.generate(feat, suppressions)
    _step(6, "Generate Candidate Hypotheses",
          f"{len(generated)} generated from a catalogue of {len(cat.CATALOGUE)}; "
          f"{len(not_generated)} recorded as not generated")

    # --- The new deterministic evidence ----------------------------------------
    # PLACED HERE DELIBERATELY, between steps 6 and 7. Two constraints decide the position and
    # they point at the same slot:
    #
    #   * `lagged_driver_evidence` takes the GENERATED hypothesis IDs and tests only the drivers
    #     they require, so it cannot run before step 6. That is the hypothesis-first principle
    #     (spec sections 4 and 48) doing real work rather than being asserted.
    #   * steps 7 and 8 COLLECT evidence, so the measurements must exist by then.
    #
    # This mirrors how the engine already treats `stats`: computed above, evaluated and recorded
    # at step 9. Nothing is reordered and no step is skipped -- what each step DOES is unchanged.
    generated_ids = {h["id"] for h in generated}
    # The gate results travel with it so a driver the gate rejected on a measurable-but-weak
    # coefficient can still be re-examined at other lags -- as ENRICHMENT only. Section 17 asks
    # for a lagged relationship to be evaluated before a driver is written off, and before this
    # the lag analysis was unreachable whenever the gate rejected everything, which is the common
    # case: three audited queues all reported "nothing was tested".
    fc_lag = fc_evidence.lagged_driver_evidence(history, target_week, generated_ids,
                                                gate_results=(gates or {}).get("results"))
    fc_holiday = fc_evidence.holiday_evidence(history, target_week, fields, ctx.get("holiday"))
    fc_response = fc_evidence.response_evidence(history, target_week, actual, forecast,
                                                fc_lag, fc_holiday)
    fc_asu = fc_evidence.asu_decomposition(fields.get("Planned_ASU"), fields.get("Actual_ASU"),
                                           forecast, actual)
    # The miss STREAK survives the removal of the plan-vintage finding: criticality lifts a band
    # when a miss is standing rather than isolated, and that is computed from adherence alone.
    fc_streak = fc_evidence.miss_streak(history)
    fc_weekend = fc_evidence.weekend_evidence(history, fields)
    fc_mechanism = fc_evidence.miss_mechanism(adherence, fc_response, fc_holiday, fc_lag,
                                              fc_asu, dq["clean"])
    fc_unexplained = fc_evidence.unexplained_observations(fc_mechanism, generated_ids)

    # Criticality (section 30) -- the queue's own recent MEDIAN actual is the typical week, not a
    # mean: a mean over a window containing the outlier being investigated is dragged by it.
    _typical = ((fc_response.get("baselines") or {}).get("recent_13_week_median_actual")
                if fc_response.get("available") else None)
    fc_criticality = fc_evidence.criticality(abs_variance, adherence, _typical,
                                             fc_streak.get("weeks"),
                                             fields.get("Volume_Category"))

    # Anything the evidence supports but the catalogue could not carry is SUPPRESSED as a
    # catalogue gap, never promoted into an ad-hoc cause (section 9).
    fc_blocks = {"lag": fc_lag, "holiday": fc_holiday, "response": fc_response, "asu": fc_asu,
                 "streak": fc_streak, "weekend": fc_weekend, "mechanism": fc_mechanism,
                 "criticality": fc_criticality, "unexplained": fc_unexplained}

    # --- Steps 7-8 -------------------------------------------------------------
    supporting, contradictory = _evidence(feat, stats, gates, ladder)
    _fc_supporting, _fc_contradictory = _fc_evidence_items(fc_blocks)
    supporting.extend(_fc_supporting)
    contradictory.extend(_fc_contradictory)
    _step(7, "Collect Supporting Evidence",
          f"{len(supporting)} item(s) ({len(_fc_supporting)} from the forecast-response, "
          f"calendar, lag and plan-vintage evidence)")
    _step(8, "Collect Contradictory Evidence",
          f"{len(contradictory)} item(s) -- actively sought, not incidental "
          f"({len(_fc_contradictory)} from the new deterministic tests)")

    # --- Step 9 ----------------------------------------------------------------
    selected_metrics = cat.metrics_for(generated)
    _step(9, "Evaluate Statistical Evidence",
          f"{len(selected_metrics)} metric(s) selected BY hypothesis: "
          f"{', '.join(sorted(selected_metrics)) or 'none'}"
          + (f"; driver lags requested for {', '.join(fc_lag.get('requested_drivers') or [])}"
             if fc_lag.get("requested_drivers") else "; no driver lag was requested")
          + f"; forecast response {(fc_response.get('response') or {}).get('classification')}"
          + f"; mechanism {fc_mechanism.get('primary')}")

    # --- Step 10 -- ask WHY of each answer until it stops being answerable -------
    _scope_for_why = decision_card.scope_analysis(
        (wfm_context or {}).get("ladder_verdict")
        or {"levels": (wfm_context or {}).get("ladder") or [],
            "band_pct": GENERATION_THRESHOLD_PCT},
        adherence, abs_variance, key.get("Forecast_name") or "This queue")
    # The holiday effect measured for THIS queue travels with the metrics so the why-chain
    # can use it; a named holiday alone is a calendar fact, it only becomes a cause when
    # holiday weeks demonstrably move this queue.
    _m_for_why = dict(m)
    _m_for_why["holiday_effect"] = ((gates or {}).get("holiday_effect")
                                    or _holiday_effect_for(history))
    why = recursive_why.reason(_scope_for_why, _m_for_why, gates,
                               {"direction": ("Over-forecast" if adherence > 0 else "Under-forecast"),
                                "adherence_pct": rnd(adherence),
                                "absolute_variance_contacts": rnd(abs_variance)},
                               period=ctx)
    _step(10, "Recursive Root Cause Reasoning",
          f"asked WHY {why['depth_reached']} level(s) deep; stopped because "
          f"{why['termination_reason']}")

    # The FACTS above are deterministic and stay that way. Only their WORDING is handed to
    # the model, because assembling every report from the same f-strings made each one read
    # identically with different numbers -- and a reader who sees the same sentence every
    # week stops believing the queue was looked at. Every figure in a rewrite is checked
    # back against the finding it came from; anything that fails keeps its original wording.
    try:
        why, _wording_note = why_rephrase.apply(
            why,
            {"queue": (fields or {}).get("Forecast_name"),
             "week": target_week,
             "region": (fields or {}).get("Region"),
             "country": (fields or {}).get("Country"),
             "offering": (fields or {}).get("Offering"),
             "channel": (fields or {}).get("channel"),
             "direction": ("Over-forecast" if adherence > 0 else "Under-forecast"),
             "adherence_pct": rnd(adherence)},
            lambda msgs: _call_llm(msgs, llm_cfg, model_choice, prefer_fast=True))
    except Exception as exc:
        _wording_note = f"kept deterministic wording: {type(exc).__name__}: {exc}"
        why = dict(why); why["wording"] = {"error": _wording_note}
    _step(10, "Root Cause Wording", _wording_note)

    # --- Step 11 -- BEFORE confidence ------------------------------------------
    feat["alternatives"] = {"count": max(0, len(generated) - 1)}
    # The measured holiday effect for THIS queue -- holiday weeks vs normal weeks over its own
    # history. Needed by LOGIC_DIRECTION_COHERENCE, which compares the direction a calendar cause
    # implies against the direction the miss actually took.
    feat["holiday_effect"] = _m_for_why.get("holiday_effect")
    # The new deterministic evidence, put where the CHALLENGE can reach it. The extra questions
    # added for section 27 -- timing, lag support, forecastability and calendar interaction -- are
    # answered from these blocks, so they must be on `feat` before examine_all runs. Placed here
    # rather than at construction because `fc_lag` needs the generated hypothesis IDs.
    feat["forecast_response"] = fc_response.get("response") or {}
    feat["forecastability"] = fc_response.get("forecastability") or {}
    feat["forecastability_gate"] = fc_response.get("forecastability_gate") or {}
    feat["signals"] = fc_response.get("signals") or []
    feat["miss_decomposition"] = fc_response.get("miss_decomposition") or {}
    feat["lag"] = fc_lag
    feat["holiday_phase"] = fc_holiday
    feat["mechanism"] = fc_mechanism
    feat["miss_streak"] = fc_streak
    feat["weekend"] = fc_weekend
    feat["asu_decomposition"] = fc_asu
    survivors, reports = cx.examine_all(generated, feat)
    _step(11, "Execute Cross-Examination",
          f"{len(survivors)} of {len(generated)} survived; "
          f"{sum(r['questions_asked'] for r in reports)} question(s) asked")

    # --- Step 12 ---------------------------------------------------------------
    root_cause = _select_root_cause(survivors, reports, stats, why)
    top_report = next((r for r in reports
                       if r["hypothesis_id"] == root_cause.get("hypothesis_id")), {})
    # Cross-examination IS a contradiction search, and it runs before confidence precisely
    # so its result can feed in. Without this the ContradictoryEvidence dimension scores a
    # clean 1.00 ("nothing contradicts") on an investigation whose own challenge raised
    # four weaknesses -- which is exactly the confidently-wrong failure the 0.20 weight on
    # this dimension exists to prevent.
    for c in (top_report.get("caveats") or []):
        contradictory.append({"text": c, "strength": "Moderate",
                              "family": "cross_examination", "source": "challenge"})

    families = {e.get("family") for e in (supporting + contradictory) if e.get("family")}

    # --- Confidence INPUTS are enhanced; the model is not (section 28) -----------
    # The eight dimensions, their weights, the 0.20 Missing floor, the renormalisation rule and
    # all eight caps are untouched. What changes is that three dimensions which previously had
    # nothing to score can now be scored from real measurements. Each is a genuine improvement in
    # the same direction the spec intends -- confidence must never rise because evidence was lost,
    # and here it moves because evidence was FOUND.
    #
    # HistoricalConsistency was hardcoded (None, 0), i.e. permanently NotApplicable. That was
    # honest when nothing measured precedent; it is no longer, because the holiday phase analysis
    # counts comparable prior instances and the momentum test counts prior occurrences with a
    # follow-through rate. A queue with genuine precedent should not be scored as though it had
    # none.
    _precedents, _precedent_score = _precedent_inputs(fc_holiday, fc_response)

    # ModelAgreement was hardcoded (1, 1), i.e. permanently NotApplicable -- one method, nothing
    # to cross-check. There are now genuinely TWO independent deterministic paths to an
    # explanation: the catalogue-plus-cross-examination path that produced `root_cause`, and the
    # mechanism-evidence path that produced `fc_mechanism`. They share no code and can disagree.
    # They CONCUR when the mechanism's evidence bears on the very hypothesis that was promoted.
    _methods, _concurring = _method_agreement_inputs(root_cause, fc_mechanism)

    # BusinessRuleValidation: the direction-coherence gate IS a business rule, and it outranks
    # statistics in the Evidence Hierarchy. When the promoted cause rests on a mechanism the gate
    # rejected, the rule CONTRADICTS the conclusion -- which scores 0.00 and arms Gate 2 to cap the
    # final level at Low. That is the intended behaviour: arithmetic must not outvote a rule saying
    # the conclusion is directionally impossible.
    _rule_state = _business_rule_state(dq, root_cause, fc_mechanism)

    # ContextCompleteness gains the elements the new evidence actually establishes, so a queue
    # where the holiday phase, driver lag coverage and data grain were all resolved is no longer
    # scored as though that context were absent.
    _ctx_available, _ctx_applicable = _context_counts(ctx, fc_holiday, fc_lag, fc_weekend)

    dims = [
        conf.data_sufficiency(weeks_of_actuals, ctx["weeks_with_actuals"],
                              ctx["weeks_in_period"], dq["mandatory_blank_count"], 4),
        conf.statistical_agreement(feat["statistics"]["supporting"], feat["statistics"]["executed"]),
        conf.model_agreement(_concurring, _methods),
        conf.context_completeness(_ctx_available, _ctx_applicable),
        conf.evidence_strength(supporting),
        conf.contradictory_evidence(_weigh(supporting), _weigh(contradictory),
                                    search_performed=True),
        conf.business_rule_validation(_rule_state),
        conf.historical_consistency(_precedent_score, _precedents),
    ]
    confidence = conf.calculate(dims, {
        "coverage_ratio": ctx["coverage_ratio"],
        "business_rule_state": _rule_state,
        "evidence_families": families,
        "primary_driver_missing": not gates.get("any_driver_relevant"),
        "cross_examination_outcome": ("survived" if top_report.get("survived")
                                      else (top_report.get("outcome") or "not run").lower()),
        "volume_band": fields.get("Volume_Category"),
    })
    _step(12, "Assign Confidence",
          f"{confidence['level']} ({confidence['score_pct']}%)"
          + (f", capped by gate {confidence['binding_cap']['gate']}"
             if confidence.get("binding_cap") else ""))

    # --- Step 13 ---------------------------------------------------------------
    recs = _recommendations(root_cause, feat, feat["deviation"], fc_mechanism, fc_lag,
                            fc_response.get("signals"), fc_holiday)

    # The mechanism, the direction verdict and the contradiction resolution are attached to the
    # root cause ALONGSIDE the existing keys -- `cause_type`, `hypothesis_id`, `hypothesis`,
    # `category`, `statement`, `cross_examination`, `caveats` and `selected_because` are all
    # untouched. `cause_type` remains the catalogue ID; the mechanism answers the different
    # question of WHY the forecast missed, which a hypothesis label alone does not.
    fc_resolution = fc_evidence.evidence_resolution(supporting, contradictory, top_report,
                                                    fc_mechanism)
    root_cause["miss_mechanism"] = fc_mechanism.get("primary")
    # Prefer the block's OWN meaning where it set one. The all-rejected-on-direction path lands on
    # DATA_LIMITATION but is not a data gap, and the stock meaning would say it was.
    root_cause["miss_mechanism_meaning"] = (
        fc_mechanism.get("meaning")
        or fc_evidence.MECHANISM_MEANING.get(fc_mechanism.get("primary")))
    root_cause["miss_mechanisms_supported"] = fc_mechanism.get("mechanisms")
    root_cause["compound"] = bool(fc_mechanism.get("compound"))
    root_cause["evidence_resolution"] = fc_resolution.get("state")
    root_cause["evidence_ids"] = sorted({e["evidence_id"] for e in supporting
                                         if e.get("evidence_id")})
    # COMPOUND_MISS is not itself a candidate mechanism -- it is the label for "more than one
    # survived". Looking it up among the candidates found nothing and reported the direction verdict
    # as None, i.e. "not tested", on exactly the reports where every contributing mechanism HAD been
    # tested and had passed. For a compound miss the verdict is the conjunction over its parts.
    _cands = fc_mechanism.get("candidates") or []
    if fc_mechanism.get("compound"):
        _verdicts = [(c.get("direction_coherence") or {}).get("coherent")
                     for c in _cands if c.get("mechanism") in (fc_mechanism.get("compound_of") or [])]
        _tested = [v for v in _verdicts if v is not None]
        root_cause["direction_coherent"] = (all(_tested) if _tested else None)
    else:
        _promoted = next((c for c in _cands
                          if c.get("mechanism") == fc_mechanism.get("primary")), None)
        root_cause["direction_coherent"] = (
            ((_promoted or {}).get("direction_coherence") or {}).get("coherent")
            if _promoted else None)

    _step(13, "Generate RCA",
          f"root cause: {root_cause.get('hypothesis') or root_cause.get('cause_type')}; "
          f"mechanism: {root_cause.get('miss_mechanism')}; "
          f"evidence {fc_resolution.get('state')}; "
          f"criticality {fc_criticality.get('band')}; "
          f"{len(recs)} recommendation(s)")

    # De-duplicated ACROSS both sources, not just within each. The weekend-grain sentence arrived
    # twice on a real report: once from `_fc_limitations` and once as a cross-examination caveat via
    # `root_cause["caveats"]`. The same sentence printed twice reads as two separate limitations.
    limitations = _dedupe(_limitations(ctx, gates, weeks_of_actuals, confidence, root_cause)
                          + _fc_limitations(fc_lag, fc_weekend, fc_holiday, fc_response, fc_asu,
                                            fc_unexplained))

    finding = {
        "queue": key,
        "period": ctx["calendar"],
        # THE HOLIDAY CONTEXT WAS COMPUTED AND THROWN AWAY. `ctx` carries it, and it decides whether
        # CAL-01 Holiday is even generated -- but `finding` took only ctx["calendar"], so the names
        # never reached the response. On India Cons IW FW202632 the engine correctly generated and
        # ACCEPTED CAL-01 because two holidays in FW202631 (Milad un-Nabi/Id-e-Milad, Onam, both with
        # a 3-day window) reach into the week -- while the source row's own Holiday_Count is 0. The
        # report then said "Holiday: Accepted with Caveats" and named no holiday, no date and no
        # reason, which reads as the engine inventing a calendar cause out of nothing.
        "holiday": ctx.get("holiday"),
        "context_elements": ctx.get("elements"),
        "grain": grain,
        "forecast_summary": {"forecast": rnd(forecast), "actual": rnd(actual),
                             "adherence_pct": rnd(adherence),
                             "absolute_variance_contacts": rnd(abs_variance),
                             "direction": ("Over-forecast" if adherence > 0 else "Under-forecast")},
        "root_cause": root_cause,
        "confidence": confidence,
        "supporting_evidence": supporting,
        "contradictory_evidence": contradictory,
        "recommendations": recs,
        "limitations": limitations,
        "why_chain": why,
        # --- ADDITIVE. Section 38: no existing key is removed or repurposed. -------
        "forecast_response_diagnostic": fc_response,
        "forecastability": fc_response.get("forecastability"),
        "forecastability_gate": fc_response.get("forecastability_gate"),
        "lagged_driver_evidence": fc_lag,
        "holiday_response": fc_holiday,
        "weekend_diagnostic": fc_weekend,
        "asu_decomposition": fc_asu,
        # `plan_revision` and `plan_vintage_timeline` are DELETED, not emptied: this engine
        # treats Projection_plan_name as non-existent, and a key that can never carry a value
        # is a promise it cannot keep. `miss_streak` replaces the only part that did not
        # depend on the column.
        "miss_streak": fc_streak,
        "miss_mechanism": fc_mechanism,
        "criticality": fc_criticality,
        "evidence_resolution": fc_resolution,
        "unexplained_observations": fc_unexplained,
        "fc_evidence_index": fc_evidence.evidence_index(
            {"forecast": rnd(forecast), "actual": rnd(actual), "adherence_pct": rnd(adherence),
             "absolute_variance_contacts": rnd(abs_variance),
             "direction": ("Over-forecast" if adherence > 0 else "Under-forecast")},
            fc_response, fc_lag, fc_holiday, fc_weekend, fc_asu, _scope_for_why,
            fc_resolution),
    }

    # The ranked WHY bullets are built HERE, before the model is called, and travel with the
    # finding. Two reasons, and the second is the important one:
    #   * the prompt asks the model to reword them, so it has to see them;
    #   * computing them once means the prose and the card cannot show a different set of bullets in
    #     a different order. Building them twice would make that divergence possible.
    finding["decision_card_why"] = decision_card.why_bullets(finding)

    # --- Step 14 -- the ONLY LLM call ------------------------------------------
    _narr_t0 = _time.time()
    narrative, narrative_error, narrative_model = _narrate(finding, llm_cfg, model_choice)
    _narr_secs = round(_time.time() - _narr_t0, 2)
    _step(14, "Generate Executive Summary",
          "narrative generated" if narrative else f"narrative unavailable: {narrative_error}")

    # --- Interrogation: Prompt 2 asks, Prompt 1 answers from evidence -----------
    # Explanatory only. Runs AFTER the RCA is complete so it cannot influence any
    # conclusion -- the cause, the confidence and the surviving hypothesis are already
    # fixed by the time either call is made.
    interro = {"available": False, "reason": "not requested"}
    if interrogate:
        evidence_bundle = {
            "forecast_summary": finding["forecast_summary"],
            "period": {k: ctx.get(k) for k in ("calendar", "coverage_ratio", "holiday",
                                               "spans_month_boundary", "spans_quarter_boundary")},
            "statistics": {k: v for k, v in (m or {}).items() if isinstance(v, dict)},
            "drivers": gates,
            "scope_by_level": _scope_for_why.get("levels"),
            "why_chain": why.get("levels"),
            "supporting_evidence": supporting,
            "contradictory_evidence": contradictory,
            "hypotheses_generated": [{"id": h["id"], "name": h["name"]} for h in generated],
            "hypotheses_not_generated": [{"id": n["id"], "name": n["name"],
                                          "state": n["state"], "reason": n.get("reason")}
                                         for n in not_generated],
            "confidence": {"level": confidence["level"], "score_pct": confidence["score_pct"],
                           "binding_cap": confidence.get("binding_cap")},
            "history_weeks": weeks_of_actuals,
            # THE WEEK-BY-WEEK SERIES. Its absence was the real reason answers came back
            # "cannot be determined": the interrogator asked why the plan was not reissued
            # after the first miss, and the bundle held no plan-vintage history and no
            # weekly figures to answer with. The model was right to refuse -- the fault was
            # a bundle that could not support the question.
            #
            # Last 26 weeks only. The whole 157 would bloat the prompt, and a question
            # about "why was the plan not adjusted" is answered by recent weeks, not by
            # three years of them.
            "weekly_series": [
                {"fiscal_week": h.get("Fiscal_Week"),
                 "actual": num(h.get("Actual_Offered")),
                 "forecast": rnd(num(h.get("fcst_offered"))),
                 "gap": (rnd(num(h.get("Actual_Offered")) - num(h.get("fcst_offered")))
                         if num(h.get("Actual_Offered")) is not None
                         and num(h.get("fcst_offered")) is not None else None),
                 "holidays": num(h.get("Holiday_Count")),
                 # The driver columns. Omitting them made questions like "what was the
                 # week-over-week change in Final_Units?" unanswerable from a series that
                 # was supposed to be the answer -- the interrogator asked precisely the
                 # right question and the bundle could not support it.
                 "planned_units_shipment": num(h.get("Final_Units")),
                 "actual_asu": num(h.get("Actual_ASU")),
                 "planned_asu": num(h.get("Planned_ASU"))}
                for h in (history or [])[-26:]],
            # Aggregates the questions keep asking for. A model summing 26 rows in its head
            # gets it wrong; precomputing costs nothing and removes the arithmetic from a
            # component that should only be reading.
            "period_aggregates": _period_aggregates(history),
            # Flat pre-answered statements. Read the docstring -- these exist because
            # nested-JSON retrieval demonstrably failed on questions the data could answer.
            "key_facts_already_established": _derived_facts(history, target_week, ctx, gates, m),
            # `plan_vintage_changes` is DELETED. The interrogator can no longer ask whether the
            # plan was reissued, because the engine no longer reads the column that would answer it
            # -- and giving the model the vintage while forbidding the finding would let the plan
            # name reach the prose by the back door. The interrogation answers ARE output.
        }
        interro = _interrogate(finding, evidence_bundle, llm_cfg, model_choice)
        _step(14, "Interrogate Findings",
              (f"{len(interro.get('questions') or [])} question(s) asked, "
               f"{interro.get('answered', 0)} answered from evidence, "
               f"{interro.get('unanswerable', 0)} beyond the data")
              if interro.get("available") else f"skipped: {interro.get('reason')}")

    # --- Step 15 ---------------------------------------------------------------
    audit = {
        "input_fingerprint": fingerprint,
        # WHO wrote the summary and HOW LONG it took. Neither was recorded before, so the footer
        # could only show version numbers that are the same on every report.
        "narrative_model": narrative_model,
        "narrative_seconds": _narr_secs,
        "started_at": started,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "catalogue_version": cat.CATALOGUE_VERSION,
        "challenge_catalogue_version": cx.CATALOGUE_VERSION,
        "confidence_weights_version": conf.WEIGHTS_VERSION,
        "prompt_version": narrative_prompt.PROMPT_VERSION,
        "generation_threshold_pct": GENERATION_THRESHOLD_PCT,
        "steps": steps,
    }
    _step(15, "Persist Audit Trail", f"fingerprint {fingerprint}")

    result = {
        **finding,
        "narrative": narrative,
        "status": "Complete" if narrative else "Incomplete",
        # An RCA marked Incomplete is complete in every respect EXCEPT the prose. Saying so,
        # and saying why, stops the label reading as "the analysis failed" when the analysis
        # is intact and only the wording is missing.
        "narrative_error": narrative_error,
        "incomplete_reason": (None if narrative else
                              f"Every figure, cause, confidence score and recommendation below is "
                              f"complete. Only the written summary is missing, because the language "
                              f"model call did not succeed: {narrative_error}"),
        "hypotheses": {"generated": generated, "not_generated": not_generated,
                       "summary": cat.summarise(generated, not_generated)},
        "cross_examination": reports,
        "driver_gate": gates,
        "statistical_evidence": stats,
        "data_quality": dq,
        "major_deviation": major,
        "material": material,
        "audit": audit,
        "engine": "spec-v2",
        "interrogation": interro,
    }
    # The card is assembled last because it reads the finished result -- including the
    # ladder, which is what answers "where, and how much" rather than just "inherited".
    result["decision_card"] = decision_card.build(result, (wfm_context or {}).get("ladder_verdict")
                                                  or {"levels": (wfm_context or {}).get("ladder") or [],
                                                      "band_pct": GENERATION_THRESHOLD_PCT})
    return result


def _limitations(ctx, gates, weeks, confidence, root_cause):
    """What could not be assessed, and why. A mandatory Decision Card section."""
    out = []
    if weeks < 104:
        out.append(f"Only {weeks} weeks of history are held for this queue; seasonal and "
                   f"long-term trend findings need 104 and are therefore less dependable.")
    if not gates.get("any_driver_relevant"):
        out.append("No business driver (units under warranty, shipments) tracks this queue's "
                   "demand closely enough to be used, so driver attribution was not possible.")
    if ctx["coverage_ratio"] < 0.999:
        out.append(f"The period is {ctx['coverage_ratio']:.0%} complete, so these figures will "
                   f"move as the remaining weeks arrive.")
    for e in ctx["elements"]["elements"]:
        if e.get("note"):
            out.append(e["note"])
    if confidence.get("binding_cap"):
        b = confidence["binding_cap"]
        out.append(f"Confidence was capped at {b['cap']} because {b['condition']} "
                   f"(measured: {b['measured']}).")
    if root_cause.get("caveats"):
        out.extend(root_cause["caveats"])
    return out


def _dedupe(items):
    """Order-preserving de-duplication of the limitation sentences."""
    seen, out = set(), []
    for s in items or []:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _fc_limitations(fc_lag, fc_weekend, fc_holiday, fc_response, fc_asu, fc_unexplained):
    """What the NEW evidence could not establish, and why.

    Section 54: where evidence is insufficient the gap is stated, never filled with a plausible
    business story. Each of these is a sentence a reader can act on -- get the data, or accept that
    the question is unanswerable from this source -- rather than a silence they have to interpret.
    """
    out = []

    if not (fc_weekend or {}).get("weekend_analysis_supported"):
        out.append((fc_weekend or {}).get("statement")
                   or "Weekend impact could not be isolated from fiscal-week totals.")

    for d in (fc_lag or {}).get("drivers") or []:
        if d.get("coverage") == "sparse":
            out.append(f"{d.get('subject') or d.get('driver')} is present for this queue, but "
                       f"available historical observations are insufficient to establish a "
                       f"reliable relationship, so it was not used as evidence.")
        elif d.get("coverage") == "absent" and d.get("requested_by"):
            out.append(f"{d.get('driver')} was required by "
                       f"{', '.join(d['requested_by'])} but has no usable history for this queue, "
                       f"so that relationship could not be tested either way.")

    hol = fc_holiday or {}
    if not hol.get("available") and hol.get("reason"):
        out.append(f"Holiday phase analysis did not run: {hol['reason']}")
    cap = hol.get("forecast_capture") or {}
    if cap.get("classification") == "inconsistent_history":
        out.append(cap.get("reason"))
    if hol.get("row_flag_disagreement"):
        out.append(hol["row_flag_disagreement"])
    for name in (hol.get("names_needing_review") or []):
        out.append(f"The holiday '{name}' is flagged for review in the holiday master, so any "
                   f"calendar finding resting on it carries that caveat. No mapping was invented "
                   f"to resolve it.")

    if (fc_asu or {}).get("availability") == conf.MISSING:
        out.append(f"ASU decomposition: {(fc_asu or {}).get('reason')}")

    fcb = (fc_response or {}).get("forecastability") or {}
    if fcb.get("classification") == "NOT_TESTABLE":
        out.append(f"Forecastability could not be tested: {fcb.get('reason')}")

    for u in (fc_unexplained or []):
        out.append(f"Catalogue gap: the evidence supports {u['observation']} "
                   f"({u.get('meaning')}), but no catalogue hypothesis that could represent it was "
                   f"generated for this queue. Recorded for catalogue extension rather than turned "
                   f"into an ad-hoc cause.")

    return _dedupe(out)



def _interrogate(finding, evidence_bundle, llm_cfg, model_choice):
    """Prompt 2 asks, Prompt 1 answers -- both server-side, both fail-safe.

    EXPLANATORY ONLY. Nothing here may change the root cause, the confidence score or the
    selected hypothesis; it elaborates a conclusion that is already fixed. That is what
    keeps it inside narrative tolerance rather than the build-failing determinism clause
    that governs the formal cross-examination.

    Two extra LLM calls, so it is skipped when `interrogate` is off. If either call fails
    the RCA is unaffected -- same rule as the narrative: an LLM failure never blocks an RCA.
    """
    out = {"available": False, "questions": [], "answers": [], "not_asked": [],
           "rejected_questions": [], "problems": []}

    # A queue with no history has nothing to interrogate. Running the loop anyway produces
    # sharp-sounding questions whose only possible answer is "cannot be determined" --
    # which reads as the engine failing when the truth is simply that this queue is new.
    # Seen live on a file-upload queue at FW202447 with zero prior weeks: two well-formed
    # questions, both unanswerable, and two wasted LLM calls.
    weeks = (evidence_bundle or {}).get("history_weeks") or 0
    series = (evidence_bundle or {}).get("weekly_series") or []
    if weeks < 4 or len(series) < 4:
        out["reason"] = (f"only {weeks} week(s) of history for this queue, so there is no "
                         f"pattern to interrogate. The miss is reported on its own terms "
                         f"rather than questioned against a history that does not exist.")
        return out

    # --- Prompt 2: ask -------------------------------------------------------
    parsed, err = _call_llm(why_prompt.build_messages(finding), llm_cfg, model_choice,
                            prefer_fast=True)
    if not parsed:
        out["reason"] = f"question generation unavailable: {err}"
        return out
    questions, rejected = why_prompt.validate(parsed)

    # Weaker models return good questions while omitting a required field, and the
    # validator then drops everything -- so the whole section vanished on those models and
    # looked like the feature only working on one. Measured across the five selectable
    # models: nemotron-3-ultra-550b produced a usable question with no `arises_from` and
    # scored zero. One repair attempt naming the missing field recovers it; the schema is
    # still enforced, the model just gets told precisely what it left out.
    if not questions and (parsed.get("questions") or []):
        missing = [q for q in parsed["questions"]
                   if isinstance(q, dict) and q.get("question") and not q.get("arises_from")]
        if missing:
            repair = why_prompt.build_messages(finding) + [
                {"role": "assistant", "content": json.dumps(parsed, default=str)},
                {"role": "user", "content":
                    "Your reply omitted the required `arises_from` field on "
                    f"{len(missing)} question(s). Return the SAME questions again, "
                    "unchanged in wording, with `arises_from` set on each to the exact "
                    "statement in the findings that prompted it. Same JSON schema, "
                    "nothing else added."}]
            reparsed, _ = _call_llm(repair, llm_cfg, model_choice, prefer_fast=True)
            if reparsed:
                questions, rejected = why_prompt.validate(reparsed)
                parsed = reparsed if questions else parsed
                out["schema_repaired"] = bool(questions)

    out["rejected_questions"] = rejected
    out["not_asked"] = [n for n in (parsed.get("not_asked") or []) if isinstance(n, dict)]
    if not questions:
        out["reason"] = ("no question survived the absent-data and traceability checks"
                         + (f" ({len(rejected)} rejected: "
                            f"{'; '.join(r['reason'] for r in rejected[:2])})" if rejected else ""))
        return out

    # --- Prompt 1: answer, ONE CALL PER QUESTION, FROM THE EVIDENCE ----------
    # Separate calls, not one call carrying every question. Batched, the model had to
    # switch between unrelated retrieval tasks inside a single generation and collapsed
    # onto whichever finding was most striking -- which is how two different questions came
    # back with the same answer. Each call now sees ONE question and only the evidence
    # blocks that question needs.
    answers, problems = [], []
    for q in questions:
        parsed2, err2 = _call_llm(why_prompt.build_answer_messages(q, evidence_bundle),
                                  llm_cfg, model_choice, prefer_fast=True)
        if not parsed2:
            problems.append(f"no answer returned for '{str(q.get('question'))[:45]}...': {err2}")
            continue
        got, probs = why_prompt.validate_answers(parsed2, evidence_bundle)
        problems.extend(probs)
        if got:
            # Pin the question we asked -- the model may echo it back reworded, and the UI
            # pairs question to answer by exact text.
            answers.append({**got[0], "question": q.get("question")})
        else:
            problems.append(f"answer to '{str(q.get('question'))[:45]}...' failed validation")

    # A duplicate across SEPARATE calls still means one question went unanswered.
    seen, deduped = {}, []
    for a in answers:
        if not a.get("answerable"):
            deduped.append(a)
            continue
        k = why_prompt._dedup_key(str(a.get("answer") or ""))
        if k and k in seen:
            problems.append(f"'{str(a.get('question'))[:40]}...' repeated the answer given to "
                            f"'{seen[k][:40]}...'")
            deduped.append({**a, "answerable": False, "answer": "", "evidence_used": [],
                            "what_would_be_needed": ("This question was not answered on its own "
                                                     "terms — the reply repeated another answer.")})
            continue
        seen[k] = str(a.get("question") or "")
        deduped.append(a)

    out.update({"available": True, "questions": questions, "answers": deduped,
                "problems": problems,
                "answered": len([a for a in deduped if a.get("answerable")]),
                "unanswerable": len([a for a in deduped if not a.get("answerable")])})
    return out


# Providers ordered fastest-first, for calls where latency matters more than depth.
# Measured on this deployment: the same interrogation took ~3s on Groq and ~222s on NVIDIA
# Nemotron. Three sequential calls at NVIDIA speed is four minutes, which is unusable in a
# UI -- and the interrogation is comprehension work, not the hardest reasoning in the run.
_FAST_FIRST = ("groq", "nvidia")


def _call_llm(messages, llm_cfg, model_choice, prefer_fast=False):
    """One provider call returning (parsed, error). Shared by narrative and interrogation.

    `prefer_fast` reorders the fallback chain. An EXPLICIT model choice always wins over it:
    when someone picks a model to compare engines, every call in that run must use it or the
    comparison means nothing.
    """
    from rca_investigate import _slot_for_choice
    from .investigation_engine import DEFAULT_MODELS, PROVIDER_ENDPOINTS
    if model_choice and model_choice.get("model"):
        picked = _slot_for_choice(model_choice, llm_cfg)
        slots = [picked] if picked else []
    else:
        slots = [(llm_cfg or {}).get("primary") or {}, (llm_cfg or {}).get("secondary") or {}]
        slots = [s for s in slots if s.get("provider") and s.get("api_key")]
        if prefer_fast:
            slots.sort(key=lambda sl: _FAST_FIRST.index(sl.get("provider"))
                       if sl.get("provider") in _FAST_FIRST else len(_FAST_FIRST))
    if not slots:
        # TWO values. `_call_llm` returns (parsed, error) and all four call sites unpack two --
        # this path returned three, raising `ValueError: too many values to unpack (expected 2)`.
        # See the matching note in `_narrate`: the two fixes are transposed halves of the same
        # mistake, and both fire only when no provider is configured, which is exactly the
        # section 37 fallback that has to keep working.
        return None, "no LLM provider configured"
    timeout = timeout_from_config(llm_cfg)
    last = "unknown"
    for slot in slots:
        endpoint = slot.get("endpoint") or PROVIDER_ENDPOINTS.get(slot.get("provider"))
        model = slot.get("model") or DEFAULT_MODELS.get(slot.get("provider"))
        if not endpoint:
            # Do not fall through leaving `last` as its initial "unknown" -- that is exactly how a
            # missing gemini endpoint surfaced as "Investigation Incomplete: ... did not succeed:
            # unknown", which says nothing a reader can act on.
            last = (f"provider '{slot.get('provider')}' has no endpoint configured "
                    f"(add it to PROVIDER_ENDPOINTS or set `endpoint` on the slot in config.json)")
            continue
        try:
            return chat_json(endpoint, slot["api_key"], model, messages, timeout=timeout), None
        except Exception as exc:
            last = f"{slot.get('provider')}/{model}: {exc}"
    return None, last


def _narrate(finding, llm_cfg, model_choice):
    """Step 14. Failure here NEVER blocks the RCA -- everything structured is already done."""
    from rca_investigate import _slot_for_choice
    from .investigation_engine import DEFAULT_MODELS, PROVIDER_ENDPOINTS

    # `model_choice` is a DICT ({"provider": ..., "model": ...}) built from the query
    # params, not a model name. Passing it straight through put a dict where the model
    # string belongs, and the provider answered 400 Bad Request -- which surfaced as
    # "Investigation Incomplete" with no obvious cause. Resolve it to a slot the same way
    # the WFM engine does.
    if model_choice and model_choice.get("model"):
        picked = _slot_for_choice(model_choice, llm_cfg)
        if not picked:
            return None, (f"selected model '{model_choice.get('model')}' has no API key "
                          f"configured for provider '{model_choice.get('provider')}'"), None
        # An explicit choice is honoured exactly -- never silently answered by a different
        # model, or the comparison the picker exists for would be meaningless.
        slots = [picked]
    else:
        slots = [(llm_cfg or {}).get("primary") or {}, (llm_cfg or {}).get("secondary") or {}]
        slots = [s for s in slots if s.get("provider") and s.get("api_key")]
    if not slots:
        # THREE values. The caller unpacks (narrative, error, model); this path returned two, so
        # `investigate()` raised
        #     ValueError: not enough values to unpack (expected 3, got 2)
        # on every run with no configured provider -- and the endpoint answered 500 instead of the
        # complete deterministic RCA that section 37 requires. Found by running the engine offline
        # against an empty llm_cfg. Covered by results/test_fc_spec_semantics.py so it cannot
        # regress silently.
        return None, "no LLM provider configured", None

    messages = narrative_prompt.build_messages(finding)
    timeout = timeout_from_config(llm_cfg)
    last = "unknown"
    for slot in slots:
        endpoint = slot.get("endpoint") or PROVIDER_ENDPOINTS.get(slot.get("provider"))
        model = slot.get("model") or DEFAULT_MODELS.get(slot.get("provider"))
        if not endpoint:
            continue
        for attempt in (1, 2):                      # malformed output is retried once
            try:
                parsed = chat_json(endpoint, slot["api_key"], model, messages, timeout=timeout)
                ok, errors = narrative_prompt.validate(parsed, finding)
                if ok:
                    # the model that actually answered, not the one that was asked first
                    return parsed, None, f"{slot.get('provider')}/{model}"
                last = "; ".join(errors)
            except Exception as exc:
                last = f"{slot.get('provider')}/{model}: {exc}"
                break
    return None, last, None


def _in_band(context_bundle, steps, started, fingerprint, adherence):
    return {"engine": "spec-v2", "status": "NotInvestigated",
            "reason": (f"Forecast Adherence is {adherence:+.1f}%, within the fixed "
                       f"±{GENERATION_THRESHOLD_PCT}% generation threshold. No RCA is generated."),
            "forecast_summary": {"adherence_pct": rnd(adherence)},
            "audit": {"input_fingerprint": fingerprint, "started_at": started, "steps": steps}}


def _incomplete(context_bundle, steps, started, fingerprint, reason):
    return {"engine": "spec-v2", "status": "Incomplete", "reason": reason,
            "audit": {"input_fingerprint": fingerprint, "started_at": started, "steps": steps}}
