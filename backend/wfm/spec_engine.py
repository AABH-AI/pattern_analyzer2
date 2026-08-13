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

    # Was the plan reissued during that run, and did it move? This is the answerable form
    # of "why was the plan not adjusted", which cannot be answered as asked.
    tl = _plan_vintage_timeline(history)
    during = [t for t in tl if first_of_streak and t.get("changed_at_week")
              and int(t["changed_at_week"]) >= int(first_of_streak)]
    if during:
        moves = ", ".join(f"{t['changed_at_week']} (set to {t['forecast_set_to']:,.0f})"
                          for t in during if t.get("forecast_set_to") is not None)
        facts.append(
            f"The plan WAS reissued {len(during)} time(s) during that run -- at {moves} -- "
            f"and the queue kept missing the same way afterwards. So this is not a plan "
            f"nobody revisited; it is a plan that was revisited and stayed wrong.")
    elif tl:
        facts.append(
            f"The plan was NOT reissued at any point during that run. The last change was "
            f"at fiscal week {tl[-1].get('changed_at_week')}, before the run began.")

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


def _plan_vintage_timeline(history):
    """Where Projection_plan_name changes, with the miss either side of the change.

    A plan reissued after a bad week looks different from one left in place, and that
    distinction is the difference between "the process worked and was wrong" and "nobody
    looked". Neither was answerable before.
    """
    rows = [h for h in (history or []) if h.get("Projection_plan_name")]
    out, prev = [], None
    for h in rows:
        name = h.get("Projection_plan_name")
        if name != prev:
            a, f = num(h.get("Actual_Offered")), num(h.get("fcst_offered"))
            out.append({
                "changed_at_week": h.get("Fiscal_Week"),
                "new_plan": name,
                "previous_plan": prev,
                "forecast_set_to": rnd(f),
                "actual_that_week": rnd(a),
                "adherence_that_week": (rnd(adherence_pct(a, f)) if a is not None and f else None),
            })
            prev = name
    return out[-8:]


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
def _recommendations(root_cause, features, deviation):
    """BR-701/702/704. Rule-derived, never model-generated. Maximum three, and fewer
    where fewer are warranted -- padding a list to a target is noise, not advice."""
    recs = []
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

    # --- Steps 7-8 -------------------------------------------------------------
    supporting, contradictory = _evidence(feat, stats, gates, ladder)
    _step(7, "Collect Supporting Evidence", f"{len(supporting)} item(s)")
    _step(8, "Collect Contradictory Evidence",
          f"{len(contradictory)} item(s) -- actively sought, not incidental")

    # --- Step 9 ----------------------------------------------------------------
    selected_metrics = cat.metrics_for(generated)
    _step(9, "Evaluate Statistical Evidence",
          f"{len(selected_metrics)} metric(s) selected BY hypothesis: "
          f"{', '.join(sorted(selected_metrics)) or 'none'}")

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

    dims = [
        conf.data_sufficiency(weeks_of_actuals, ctx["weeks_with_actuals"],
                              ctx["weeks_in_period"], dq["mandatory_blank_count"], 4),
        conf.statistical_agreement(feat["statistics"]["supporting"], feat["statistics"]["executed"]),
        conf.model_agreement(1, 1),
        conf.context_completeness(ctx["elements"]["available"], ctx["elements"]["applicable"]),
        conf.evidence_strength(supporting),
        conf.contradictory_evidence(_weigh(supporting), _weigh(contradictory),
                                    search_performed=True),
        conf.business_rule_validation("neutral" if dq["clean"] else "not_evaluable"),
        conf.historical_consistency(None, 0),
    ]
    confidence = conf.calculate(dims, {
        "coverage_ratio": ctx["coverage_ratio"],
        "business_rule_state": "neutral" if dq["clean"] else "not_evaluable",
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
    recs = _recommendations(root_cause, feat, feat["deviation"])
    _step(13, "Generate RCA",
          f"root cause: {root_cause.get('hypothesis') or root_cause.get('cause_type')}; "
          f"{len(recs)} recommendation(s)")

    limitations = _limitations(ctx, gates, weeks_of_actuals, confidence, root_cause)

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
    }

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
                 "plan_vintage": h.get("Projection_plan_name"),
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
            # When the plan vintage CHANGED, and what it was set to at each change. This is
            # what answers "was the plan reissued after it started missing?" -- a question
            # the engine could raise but not settle.
            "plan_vintage_changes": _plan_vintage_timeline(history),
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
        return None, "no LLM provider configured", None
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
        return None, "no LLM provider configured"

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
