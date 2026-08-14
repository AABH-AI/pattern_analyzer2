# -*- coding: utf-8 -*-
"""FC-native deterministic evidence: the new analytical capability, in FC vocabulary.

Implements sections 13-25, 30-32 and 43 of the FC Decision Card upgrade brief.

WHY THIS MODULE EXISTS RATHER THAN A SECOND DECISION LAYER
-----------------------------------------------------------
The measurement modules (`lag_analysis`, `forecast_response`, `holiday_response`,
`data_granularity`) are pure arithmetic over history rows and know nothing about either engine.
What they return is shaped for whoever asks. The FC engine cannot consume that shape directly,
because FC has its own settled vocabulary and the brief is explicit that it must survive:

    catalogue hypothesis IDs      CAL-01 .. DQ-04, never a free-text cause
    three availability states     Available / Missing / NotApplicable, never conflated
    four catalogue states         Generated / NotApplicable / Suppressed / Rejected
    the 15-step sequence          evidence is collected at steps 7-9, not at the end

So this module is an ADAPTER plus the genuinely new deterministic tests. It answers each
question in FC terms and says WHICH CATALOGUE HYPOTHESES the answer bears on, so the existing
`_select_root_cause`, `cross_examination` and `confidence` machinery can use it without being
replaced. Nothing here selects a root cause; that remains step 13's job.

WHAT IS NEW HERE, NOT PORTED FROM ANYWHERE
-------------------------------------------
    asu_decomposition        the exact volume/rate identity of section 19
    plan_revision            the three plan-vintage states of section 8
    criticality              section 30 -- FC has no criticality mechanism at all
    miss_mechanism           the seven mechanisms of section 5 (A-G)
    direction_coherence      section 32, as a deterministic gate over ALL mechanisms
    evidence_resolution      section 31 -- supported / mixed / rejected, with a governing reason
    unexplained_observations section 9 -- a catalogue gap is recorded, never made into a cause
    evidence_index           section 43 -- E1..E15 in the brief's OWN numbering

WHY THE EVIDENCE IDS ARE FC's OWN NUMBERING
--------------------------------------------
The brief numbers E9/E10/E11 as pre-holiday / holiday / post-holiday. The WFM engine's index
numbers E9/E10 as holiday phase / forecast capture. Same labels, different meanings. Section 46
keeps the engines independent, so these are published as `fc_evidence_index` and are never
compared to WFM's by ID. Comparing conclusions is meaningful; comparing field numbers is not.

PERFORMANCE (section 48)
------------------------
`lagged_driver_evidence` takes the set of drivers the GENERATED hypotheses actually require and
tests only those. It never sweeps every column against every lag -- that is the N x M explosion
the brief forbids, and it finds something every time.
"""
from . import data_granularity
from . import forecast_response as fr
from . import holiday_events
from . import holiday_response as hr
from . import lag_analysis
from .common import adherence_pct, num, rnd

# The deviation size at or below which a week is NOT a miss. Deliberately the same figure as
# spec_engine.GENERATION_THRESHOLD_PCT: if a week would not have triggered an RCA, it cannot be
# counted as part of a miss run. Declared here rather than imported to avoid a circular import, and
# asserted equal to the engine's value by results/test_fc_spec_semantics.py so the two cannot drift.
MISS_THRESHOLD_PCT = 5.0

# --- FC availability vocabulary (mirrors confidence.py exactly) -----------------
AVAILABLE = "Available"
MISSING = "Missing"
NOT_APPLICABLE = "NotApplicable"

EVIDENCE_VERSION = "1.0.0"

# ==============================================================================
# Section 5 -- the seven miss mechanisms
# ==============================================================================
# ADDITIVE. `root_cause.cause_type` remains the catalogue hypothesis ID; this says which KIND of
# failure the evidence describes, which is the question "why did Forecast miss?" that a
# hypothesis ID alone does not answer. CAL-01 Holiday can be a calendar response failure or a
# genuinely unforeseeable event, and those want opposite actions.
FORECAST_BASELINE_FAILURE = "FORECAST_BASELINE_FAILURE"
FORECAST_RESPONSE_FAILURE = "FORECAST_RESPONSE_FAILURE"
CALENDAR_RESPONSE_FAILURE = "CALENDAR_RESPONSE_FAILURE"
DRIVER_RESPONSE_FAILURE = "DRIVER_RESPONSE_FAILURE"
DEMAND_EVENT_LOW_PREDICTABILITY = "DEMAND_EVENT_LOW_PREDICTABILITY"
COMPOUND_MISS = "COMPOUND_MISS"
DATA_LIMITATION = "DATA_LIMITATION"

MISS_MECHANISMS = (FORECAST_BASELINE_FAILURE, FORECAST_RESPONSE_FAILURE,
                   CALENDAR_RESPONSE_FAILURE, DRIVER_RESPONSE_FAILURE,
                   DEMAND_EVENT_LOW_PREDICTABILITY, COMPOUND_MISS, DATA_LIMITATION)

MECHANISM_MEANING = {
    FORECAST_BASELINE_FAILURE: "Forecast entered the period at the wrong level.",
    FORECAST_RESPONSE_FAILURE: ("A repeatable leading signal existed before the week and the "
                                "plan did not respond adequately to it."),
    CALENDAR_RESPONSE_FAILURE: ("A repeatable calendar effect existed and the plan did not "
                                "capture it."),
    DRIVER_RESPONSE_FAILURE: ("A business driver gave a repeatable leading signal and the plan "
                              "did not incorporate it."),
    DEMAND_EVENT_LOW_PREDICTABILITY: ("Demand moved materially, but no sufficiently repeatable "
                                      "leading signal existed beforehand."),
    COMPOUND_MISS: "More than one supported mechanism contributed materially.",
    DATA_LIMITATION: "Critical evidence is missing, so no defensible mechanism can be stated.",
}

# The catalogue hypotheses each mechanism bears on. Used to attach evidence, never to invent a
# hypothesis: if a mechanism has no catalogue entry it becomes an UNEXPLAINED_OBSERVATION.
MECHANISM_HYPOTHESES = {
    FORECAST_BASELINE_FAILURE: ("FC-01", "FC-02"),
    FORECAST_RESPONSE_FAILURE: ("FC-01", "FC-02", "STA-03"),
    CALENDAR_RESPONSE_FAILURE: ("CAL-01", "CAL-02", "CAL-03", "CAL-04"),
    DRIVER_RESPONSE_FAILURE: ("BUS-01", "BUS-02", "BUS-03", "BUS-04"),
    DEMAND_EVENT_LOW_PREDICTABILITY: ("DEM-01", "DEM-02", "STA-01", "STA-04"),
    DATA_LIMITATION: ("DQ-01", "DQ-02", "DQ-03", "DQ-04"),
}

# Which drivers each BUSINESS hypothesis needs tested. Section 48: the hypothesis selects the
# evidence, the engine does not test everything and then hunt for a story.
HYPOTHESIS_DRIVERS = {
    "BUS-01": ("Final_Units",),                    # warranty mix rides on shipment exposure
    "BUS-02": ("Actual_ASU", "Final_upp_units"),   # installed base, and the upgrade/EPP base
    "BUS-03": ("Actual_ASU", "Planned_ASU"),
    "BUS-04": ("Final_Units",),
}

# ==============================================================================
# Section 30 -- criticality. FC-native.
# ==============================================================================
# CONFIRMED ABSENT before it was written: no criticality, criticality band or severity model
# exists anywhere in the FC engine. The console's `severity` is a band multiple on the worklist
# and is not this.
#
# Criticality is NOT confidence and is never derived from it. Confidence asks how strong the
# evidence is; criticality asks how much the miss matters operationally. A perfectly evidenced
# 30-contact miss is Negligible; a barely evidenced 9,000-contact miss is Critical.
#
# THE ABSOLUTE GAP SETS THE BAND. That is deliberate and it is the whole point: a percentage on
# a tiny queue is arithmetically large and operationally irrelevant, which is exactly why FC
# already has a 50-contact materiality floor. The floor is reused here as the bottom edge rather
# than inventing a second, disagreeing threshold.
CRITICALITY_BANDS = ("Negligible", "Low", "Moderate", "High", "Critical")

# Contacts. Anchored on the existing 50-contact floor and then an order of magnitude per step,
# which is the only defensible spacing without a client-confirmed table -- and it is recorded
# here as versioned configuration so a change is visible in the audit trail.
CRITICALITY_ABS_THRESHOLDS = ((5000, "Critical"), (1000, "High"), (200, "Moderate"), (50, "Low"))
MATERIALITY_FLOOR_CONTACTS = 50

# A large gap RELATIVE TO THIS QUEUE's own normal week can lift the band one step -- 400 contacts
# is routine on a queue that runs 20,000 and is an emergency on one that runs 500. It lifts by at
# most one step and can never lower, so the absolute gap stays the primary control.
CRITICALITY_RELATIVE_LIFT = 0.50        # gap >= 50% of a typical week
CRITICALITY_PERSISTENCE_WEEKS = 4       # a same-direction run this long also lifts one step


def _band_index(band):
    return CRITICALITY_BANDS.index(band)


def criticality(abs_variance, adherence_pct, typical_week_actual, streak_weeks=None,
                volume_band=None):
    """Section 30. Deterministic, decomposed, and independent of confidence.

    `typical_week_actual` should be the queue's own recent median actual -- a median, because a
    mean over a series containing the outlier week being investigated is dragged by it.
    """
    gap = abs(num(abs_variance) or 0.0)
    if gap < MATERIALITY_FLOOR_CONTACTS:
        return {
            "band": "Negligible",
            "band_before_lifts": "Negligible",
            "absolute_gap_contacts": rnd(gap),
            "relative_gap": None,
            "lifts_applied": [],
            "basis": (f"{gap:,.0f} contacts is below the {MATERIALITY_FLOOR_CONTACTS}-contact "
                      f"materiality floor, so the percentage overstates the business "
                      f"significance."),
            "independent_of_confidence": True,
            "reading": (f"Operationally negligible: {gap:,.0f} contacts. The RCA is still "
                        f"generated and still valid -- the floor is a worklist control, not a "
                        f"suppression of the analysis."),
        }

    base = "Low"
    for threshold, band in CRITICALITY_ABS_THRESHOLDS:
        if gap >= threshold:
            base = band
            break

    lifts = []
    typical = num(typical_week_actual)
    relative = (gap / typical) if typical else None
    if relative is not None and relative >= CRITICALITY_RELATIVE_LIFT:
        lifts.append(f"the gap is {relative:.0%} of a typical week for this queue "
                     f"({typical:,.0f} contacts), at or above the "
                     f"{CRITICALITY_RELATIVE_LIFT:.0%} lift threshold")
    if (streak_weeks or 0) >= CRITICALITY_PERSISTENCE_WEEKS:
        lifts.append(f"the miss has run in the same direction for {streak_weeks} consecutive "
                     f"weeks, so the gap is standing rather than isolated")

    final = CRITICALITY_BANDS[min(_band_index(base) + (1 if lifts else 0),
                                  len(CRITICALITY_BANDS) - 1)]

    reading = f"{final}: {gap:,.0f} contacts against plan"
    if relative is not None:
        reading += f", about {relative:.0%} of a typical week for this queue"
    reading += "."
    # Only claim a lift when the band ACTUALLY MOVED. At the top band the lift saturates, and the
    # sentence "Lifted one step from Critical" -- read on a real report -- is simply wrong.
    if lifts and final != base:
        reading += f" Lifted one step from {base} because {lifts[0]}."
    elif lifts:
        reading += (f" Already at the highest band, so the lift did not change it, but note that "
                    f"{lifts[0]}.")
    return {
        "band": final,
        "band_before_lifts": base,
        "absolute_gap_contacts": rnd(gap),
        "relative_gap": (round(relative, 4) if relative is not None else None),
        "typical_week_actual": rnd(typical),
        "adherence_pct": rnd(adherence_pct),
        "streak_weeks": streak_weeks,
        "volume_band": volume_band,
        "lifts_applied": lifts,
        "basis": (f"The absolute gap of {gap:,.0f} contacts sets the band; the relative gap and "
                  f"persistence may lift it by at most one step and can never lower it."),
        "independent_of_confidence": True,
        "reading": reading,
        "thresholds": {"absolute_contacts": dict((str(t), b)
                                                 for t, b in CRITICALITY_ABS_THRESHOLDS),
                       "relative_lift": CRITICALITY_RELATIVE_LIFT,
                       "persistence_weeks": CRITICALITY_PERSISTENCE_WEEKS,
                       "materiality_floor": MATERIALITY_FLOOR_CONTACTS},
    }


# ==============================================================================
# Section 19 -- ASU decomposition, exact
# ==============================================================================
def asu_decomposition(planned_asu, actual_asu, forecast, actual):
    """The exact identity from section 19. volume_effect + rate_effect == actual - forecast.

        planned_rate  = forecast / Planned_ASU
        actual_rate   = actual   / Actual_ASU
        volume_effect = (Actual_ASU - Planned_ASU) * planned_rate
        rate_effect   = Actual_ASU * (actual_rate - planned_rate)

    Algebraically the two effects sum to `actual - forecast` exactly, so `reconciles` is a real
    check on the inputs rather than a decorative one -- if it ever reports False the figures
    themselves disagree and the decomposition must not be published.

    If Actual_ASU is missing the decomposition is NOT fabricated. It reports that it could not be
    performed and the investigation continues with the other hypotheses (section 19, explicit).
    """
    p, a = num(planned_asu), num(actual_asu)
    f, act = num(forecast), num(actual)

    if f is None or act is None:
        return {"available": False, "availability": MISSING,
                "reason": "the week's forecast or actual is not available, so the decomposition "
                          "cannot be performed."}
    if p is None and a is None:
        return {"available": False, "availability": NOT_APPLICABLE,
                "reason": "this queue carries no ASU (units under warranty) exposure, so the "
                          "population/contact-rate split does not apply to it."}
    if p is None or a is None:
        absent = "Actual_ASU" if a is None else "Planned_ASU"
        return {"available": False, "availability": MISSING,
                "reason": (f"{absent} is not populated for this week, so the population and "
                           f"contact-rate effects cannot be separated. No substitute figure was "
                           f"used.")}
    if not p or not a:
        return {"available": False, "availability": MISSING,
                "reason": ("an ASU figure is zero, so a contact rate per unit is undefined for "
                           "this week.")}

    planned_rate = f / p
    actual_rate = act / a
    volume_effect = (a - p) * planned_rate
    rate_effect = a * (actual_rate - planned_rate)
    total = act - f
    reconciles = abs((volume_effect + rate_effect) - total) <= max(0.01, abs(total) * 1e-6)

    vshare = abs(volume_effect) / (abs(volume_effect) + abs(rate_effect)) \
        if (abs(volume_effect) + abs(rate_effect)) else None
    if vshare is None:
        interpretation, leading = "neither effect is measurable", None
    elif vshare >= 0.70:
        interpretation, leading = "population/base effect", "volume"
    elif vshare <= 0.30:
        interpretation, leading = "contact-rate effect", "rate"
    else:
        interpretation, leading = "mixed", "mixed"

    detail = {
        "volume": ("The supported population differed from plan: "
                   f"{a:,.0f} units against a planned {p:,.0f}."),
        "rate": ("The population was close to plan, but contacts per unit differed: "
                 f"{actual_rate:.4f} actual against {planned_rate:.4f} planned."),
        "mixed": ("Both mattered: the population differed from plan AND contacts per unit "
                  "differed."),
    }.get(leading, "Neither effect could be sized.")

    return {
        "available": True,
        "availability": AVAILABLE,
        "planned_asu": rnd(p), "actual_asu": rnd(a),
        "planned_rate": round(planned_rate, 6), "actual_rate": round(actual_rate, 6),
        "volume_effect": rnd(volume_effect), "rate_effect": rnd(rate_effect),
        "total_miss": rnd(total),
        "reconciles": reconciles,
        "volume_share": (round(vshare, 4) if vshare is not None else None),
        "interpretation": interpretation,
        "leading_effect": leading,
        "reading": (f"{detail} The two effects sum to the whole {total:+,.0f}-contact gap "
                    f"({volume_effect:+,.0f} from population, {rate_effect:+,.0f} from contact "
                    f"rate), so nothing is left unexplained by the split."),
        "attaches_to": ["BUS-02", "BUS-03"],
        "identity": "volume_effect + rate_effect = Actual - Forecast",
    }


# ==============================================================================
# Section 8 -- did WFM revisit the plan, and did the revision work?
# ==============================================================================
PLAN_NOT_REVISITED = "plan_not_revisited"
PLAN_REVISED_STILL_WRONG = "plan_revised_but_remained_wrong"
PLAN_REVISED_APPROPRIATELY = "plan_revised_appropriately"
PLAN_NOT_TESTABLE = "not_testable"


def plan_revision(history, plan_timeline, target_week):
    """Section 8. Which of the three plan states the vintage evidence actually supports.

    The brief is explicit that these states must NOT be inferred without plan-vintage evidence,
    so every path here is either grounded in a recorded vintage change or returns
    `not_testable`. "The plan was never revisited" and "we cannot tell whether it was revisited"
    are different findings and only one of them is an accusation.
    """
    rows = [(h.get("Fiscal_Week"), num(h.get("Actual_Offered")), num(h.get("fcst_offered")))
            for h in (history or [])]
    rows = [(w, a, f) for w, a, f in rows if a is not None and f is not None]
    if not rows:
        return {"available": False, "state": PLAN_NOT_TESTABLE, "availability": MISSING,
                "reason": "no paired actual/forecast history is available for this queue."}
    if not plan_timeline:
        return {"available": False, "state": PLAN_NOT_TESTABLE, "availability": MISSING,
                "reason": ("no plan vintage (Projection_plan_name) is recorded in this queue's "
                           "history, so whether the plan was reissued cannot be established.")}

    # The run of same-direction MISSES ending at the target week.
    #
    # A week is only part of the run if it actually missed. `a > f else "over"` classifies a week
    # where actual EQUALS forecast as an over-forecast, so a perfectly forecast queue reported a
    # 120-week over-forecast streak -- and on that basis the engine said the plan was reissued
    # during a miss run that never happened. A week inside the +/-5% generation threshold is by the
    # engine's own definition not a miss, so it ENDS the run rather than extending it.
    direction, streak, first_week = None, 0, None
    for w, a, f in reversed(rows):
        adh = adherence_pct(a, f)
        if adh is None or abs(adh) <= MISS_THRESHOLD_PCT:
            break                       # not a miss -- the run stops here
        d = "under" if a > f else "over"
        if direction is None:
            direction = d
        if d != direction:
            break
        streak += 1
        first_week = w

    # The FIRST vintage record is the initial plan, not a revision -- `_plan_vintage_timeline`
    # emits it with `previous_plan: None` because there is nothing before it. Counting it as a
    # reissue meant every queue looked as though its plan had been revisited.
    changes_during = [t for t in plan_timeline
                      if t.get("changed_at_week") and first_week
                      and t.get("previous_plan") is not None
                      and int(t["changed_at_week"]) >= int(first_week)]

    if streak < 2:
        return {"available": True, "state": PLAN_NOT_TESTABLE, "availability": NOT_APPLICABLE,
                "streak_weeks": streak, "streak_direction": direction,
                "reason": ("this week's miss does not continue a run, so there is no miss streak "
                           "against which to judge whether the plan was revisited."),
                "reading": (f"This {direction}-forecast does not continue a run -- the previous "
                            f"week missed the other way -- so the plan-revision question does "
                            f"not arise for this week.")}

    if not changes_during:
        last = plan_timeline[-1].get("changed_at_week")
        return {
            "available": True, "state": PLAN_NOT_REVISITED, "availability": AVAILABLE,
            "streak_weeks": streak, "streak_direction": direction,
            "streak_began_at_week": first_week,
            "revisions_during_streak": 0,
            "last_revision_week": last,
            "reading": (f"The plan was NOT reissued at any point during the {streak}-week "
                        f"{direction}-forecast run that began at fiscal week {first_week}. The "
                        f"last vintage change was at fiscal week {last}, before the run started. "
                        f"So the plan stood unchanged while the miss continued."),
            "attaches_to": ["FC-01"],
        }

    # It WAS reissued. Did the misses stop? Judged on the weeks AFTER the last revision inside
    # the run -- including the target week, which is the week under investigation.
    last_change = max(int(t["changed_at_week"]) for t in changes_during)
    after = [(w, a, f) for w, a, f in rows if int(w) >= last_change]
    # Same tie problem as the streak: a week that came in ON plan is a SUCCESS of the revision, not
    # a continuing miss. Only weeks that actually breach the threshold in the original direction
    # count as "still missing the same way".
    same_direction_after = [
        (w, a, f) for w, a, f in after
        if (adherence_pct(a, f) is not None
            and abs(adherence_pct(a, f)) > MISS_THRESHOLD_PCT
            and ("under" if a > f else "over") == direction)]
    corrected = len(same_direction_after) < len(after)

    moves = ", ".join(f"FW{t['changed_at_week']} (plan set to "
                      f"{t['forecast_set_to']:,.0f})" if t.get("forecast_set_to") is not None
                      else f"FW{t['changed_at_week']}"
                      for t in changes_during)

    if same_direction_after and len(same_direction_after) == len(after):
        return {
            "available": True, "state": PLAN_REVISED_STILL_WRONG, "availability": AVAILABLE,
            "streak_weeks": streak, "streak_direction": direction,
            "streak_began_at_week": first_week,
            "revisions_during_streak": len(changes_during),
            "last_revision_week": last_change,
            "weeks_after_last_revision": len(after),
            "weeks_still_missing_same_way": len(same_direction_after),
            "reading": (f"The plan WAS reissued {len(changes_during)} time(s) during the "
                        f"{streak}-week {direction}-forecast run -- at {moves} -- and every one "
                        f"of the {len(after)} week(s) since the last reissue has still missed in "
                        f"the same direction. This is not a plan nobody revisited; it is a plan "
                        f"that was revisited and stayed wrong."),
            "attaches_to": ["FC-01", "FC-02"],
        }

    return {
        "available": True,
        "state": PLAN_REVISED_APPROPRIATELY if corrected else PLAN_NOT_TESTABLE,
        "availability": AVAILABLE,
        "streak_weeks": streak, "streak_direction": direction,
        "streak_began_at_week": first_week,
        "revisions_during_streak": len(changes_during),
        "last_revision_week": last_change,
        "weeks_after_last_revision": len(after),
        "weeks_still_missing_same_way": len(same_direction_after),
        "reading": (f"The plan was reissued at {moves}, and {len(after) - len(same_direction_after)} "
                    f"of the {len(after)} week(s) since have come back inside the same direction "
                    f"-- so the revision did move the plan towards demand."),
        "attaches_to": ["FC-01"],
    }


# ==============================================================================
# Section 16-18 -- lagged driver evidence, hypothesis-selected
# ==============================================================================
def lagged_driver_evidence(history, target_week, generated_ids):
    """Sections 16-18. Lags only for drivers the GENERATED hypotheses actually require.

    Section 48 forbids testing every column at every lag. `generated_ids` is the set of catalogue
    IDs that fired, and `HYPOTHESIS_DRIVERS` maps each to the drivers it rests on -- so a queue
    whose business hypotheses did not fire runs no driver lags at all, and the response says so
    rather than shipping a table nothing asked for.

    Coverage states (section 18) are NOT collapsed:
        populated  enough valid paired history -> a coefficient is reported
        sparse     some history, too little to be reliable -> reported AS sparse, never as proof
        absent     no usable data -> NotApplicable, no penalty

    Section 17 wording is enforced here: a weak coefficient is never rendered as "this driver has
    no effect" unless coverage was adequate enough for that to be a real finding.
    """
    wanted, requested_by = [], {}
    for hid in sorted(set(generated_ids or ())):
        for d in HYPOTHESIS_DRIVERS.get(hid, ()):
            if d not in wanted:
                wanted.append(d)
            requested_by.setdefault(d, []).append(hid)

    if not wanted:
        return {"available": False, "availability": NOT_APPLICABLE,
                "requested_drivers": [],
                "reason": ("no business hypothesis was generated for this queue, so no driver "
                           "relationship was requested. Nothing was tested and nothing is "
                           "claimed either way."),
                "note": ("Driver statistics are selected BY hypothesis (section 48). An untested "
                         "driver is not a driver that was ruled out.")}

    full = lag_analysis.analyse(history, target_week)
    if not full.get("available"):
        return {"available": False, "availability": MISSING,
                "requested_drivers": wanted,
                "reason": full.get("reason") or "the lag analysis could not run on this history.",
                "note": full.get("note")}

    by_name = {d.get("driver"): d for d in (full.get("drivers") or [])}
    rows, usable, leading = [], [], []
    for name in wanted:
        d = by_name.get(name)
        if not d:
            rows.append({
                "driver": name, "coverage": "absent", "availability": NOT_APPLICABLE,
                "requested_by": requested_by[name], "tested": False,
                "usable_as_evidence": False,
                "interpretation": (f"{name} does not appear in this queue's history at all, so no "
                                   f"relationship could be tested. This is an absence of data, "
                                   f"not a finding that the driver is irrelevant."),
                # The reading is set on EVERY row, including this early path. It was missing here
                # once, and the card rendered a bare "None" under the driver's name -- which reads
                # as a measured null rather than as "we have no data".
                "reading": (f"{name} has no usable history for this queue, so no relationship "
                            f"could be established either way."),
            })
            continue

        coverage = d.get("coverage")
        best = d.get("best") or {}
        avail = {"populated": AVAILABLE, "sparse": MISSING}.get(coverage, NOT_APPLICABLE)
        row = {
            "driver": name,
            "subject": d.get("subject"),
            "coverage": coverage,
            "availability": avail,
            "requested_by": requested_by[name],
            "tested": bool(d.get("tested")),
            "weeks_with_a_value": d.get("weeks_with_a_value"),
            "weeks_in_window": d.get("weeks_in_window"),
            "best_lag_weeks": d.get("best_lag_weeks"),
            "relationship_type": d.get("relationship_type"),
            "relationship_strength": d.get("relationship_strength"),
            "direction": d.get("direction"),
            "stability": d.get("stability"),
            "paired_weeks": d.get("weeks"),
            "first_half_strength": best.get("first_half_strength"),
            "second_half_strength": best.get("second_half_strength"),
            "usable_as_evidence": bool(d.get("usable_as_evidence")),
            "interpretation": d.get("interpretation"),
            "candidates": d.get("candidates"),
        }
        # Section 17: only ONE of these three readings is ever true, and they lead to different
        # actions -- get the data, distrust the number, or use it.
        if coverage == "absent":
            row["reading"] = (f"{d.get('subject') or name} has no usable history for this queue, "
                              f"so no relationship could be established either way.")
        elif coverage == "sparse":
            row["reading"] = (f"{d.get('subject') or name} is present, but available historical "
                              f"observations are insufficient to establish a reliable "
                              f"relationship.")
        elif d.get("stability") in ("unstable", "moderate") and not d.get("usable_as_evidence"):
            row["reading"] = (f"The relationship between {d.get('subject') or name} and demand is "
                              f"inconsistent across this queue's history, so it is not strong "
                              f"enough to explain the current miss.")
        elif d.get("usable_as_evidence") and (d.get("best_lag_weeks") or 0) > 0:
            row["reading"] = (f"{(d.get('subject') or name).capitalize()} "
                              f"{d.get('best_lag_weeks')} week(s) earlier has a stronger and more "
                              f"stable historical relationship with demand than the same-week "
                              f"comparison.")
        elif d.get("usable_as_evidence"):
            row["reading"] = (f"{(d.get('subject') or name).capitalize()} moves with demand in the "
                              f"same week, with enough history behind it to use.")
        else:
            row["reading"] = row["interpretation"]

        rows.append(row)
        if row["usable_as_evidence"]:
            usable.append(name)
            if (row.get("best_lag_weeks") or 0) > 0:
                leading.append(name)

    return {
        "available": True,
        "availability": AVAILABLE if usable else MISSING,
        "requested_drivers": wanted,
        "lags_tested": full.get("lags_tested"),
        "min_paired_observations": full.get("min_paired_observations"),
        "min_strength": full.get("min_strength"),
        "drivers": rows,
        "usable_drivers": usable,
        "leading_drivers": leading,
        "coverage_summary": {c: len([r for r in rows if r.get("coverage") == c])
                             for c in ("populated", "sparse", "absent")},
        "note": ("Drivers were selected by the generated hypotheses, not swept exhaustively. "
                 "Relationships are measured on this queue's own history with the week under "
                 "investigation excluded."),
    }


# ==============================================================================
# Sections 22-24 -- holiday, in FC terms
# ==============================================================================
def holiday_evidence(history, target_week, target_fields, holiday_context_block):
    """Sections 22-24, wrapped for FC.

    Two things the FC engine could not previously say, both required by section 22:

      * a week with Holiday_Count = 0 can still be pre- or post-holiday. `_holiday_effect_for`
        in spec_engine splits history on Holiday_Count alone, so an adjacent-week effect was
        invisible to it and the report could only say "no holiday impact".
      * an observed holiday effect is not automatically a forecast failure (section 24). Where
        the queue's own history is inconsistent the finding is explicitly that no reliable
        forecastable signal exists -- not that the plan should have caught it.

    `holiday_context_block` is the EXISTING `holiday_context()` output already on `ctx`. It is
    passed in rather than recomputed so the card cannot disagree with itself, and the named
    holidays it resolves stay traceable to the source rows (section 23).
    """
    country = (target_fields or {}).get("Country")
    target = next((h for h in reversed(history or [])
                   if str(h.get("Fiscal_Week")) == str(target_week)), {})
    actual = num(target.get("Actual_Offered"))
    forecast = num(target.get("fcst_offered"))
    row_count = num(target.get("Holiday_Count"))

    block = hr.analyse(history, target_week, country, actual, forecast, row_count)

    # `holiday_response` already normalises events across its own +/-2 week span, which is a
    # strictly wider reach than `holiday_context`'s +/-1. So its event summary is authoritative
    # and is NOT recomputed here. The context block is used only for traceability: the names the
    # spec engine already resolved and put on the card must still match, and section 23 requires
    # the raw source names to stay traceable.
    ctx_rows = list((holiday_context_block or {}).get("in_week") or []) \
        + list((holiday_context_block or {}).get("in_window") or [])
    if ctx_rows and not (block.get("event_summary") or {}).get("event_count"):
        instances = holiday_events.normalise(ctx_rows)
        block["event_summary"] = holiday_events.summarise(instances)
        block["event_instances"] = instances
        block["event_summary_source"] = "holiday_context (+/-1 week)"
    elif block.get("event_summary"):
        block["event_summary_source"] = f"holiday_span (+/-{hr.SPAN_WEEKS} weeks)"

    avail = AVAILABLE if block.get("available") else (
        NOT_APPLICABLE if "Country" in str(block.get("reason") or "") else MISSING)
    block["availability"] = avail
    block["calendar_names"] = (holiday_context_block or {}).get("names") or []
    block["calendar_raw_names"] = sorted({h.get("name") for h in ctx_rows if h.get("name")})
    block["row_flag_disagreement"] = (block.get("row_flag_disagreement")
                                      or (holiday_context_block or {}).get("row_flag_disagreement"))
    block["row_holiday_count"] = row_count
    # The distinction section 22 insists on, stated as data rather than left to the reader.
    block["zero_count_but_adjacent"] = bool((row_count or 0) == 0 and block.get("applies"))
    block["attaches_to"] = ["CAL-01"]
    return block


# ==============================================================================
# Section 25 -- weekend, grain-aware
# ==============================================================================
def weekend_evidence(history, target_fields):
    """Section 25. Determine the grain FIRST, then say only what the grain supports.

    On this source the answer is settled and will stay settled until a daily feed exists: the
    Monday..Sunday columns are per-day HOLIDAY FLAGS, not daily volumes, so a weekend volume
    effect cannot be isolated from fiscal-week totals. That is reported as a limitation with its
    reason, never as "no weekend effect" -- which would be a claim the data cannot support in
    either direction.
    """
    gran = data_granularity.analyse(history, (target_fields or {}))
    day_structure = data_granularity.holiday_day_structure(target_fields or {}, gran)
    supported = bool(gran.get("weekend_analysis_supported"))
    return {
        "available": True,
        "availability": AVAILABLE if supported else NOT_APPLICABLE,
        "grain": gran.get("grain"),
        "weekend_analysis_supported": supported,
        "statement": gran.get("weekend_statement"),
        "capabilities": gran.get("capabilities"),
        "limitations": gran.get("limitations"),
        "holiday_day_structure": day_structure,
        "attaches_to": ["CAL-01"],
        "note": ("Grain is re-checked against the actual rows on every run, so this flips by "
                 "itself if a day-level source is added. Nothing about the weekend is asserted "
                 "from weekly totals."),
    }


# ==============================================================================
# Sections 13-15 -- demand vs forecast, response, forecastability
# ==============================================================================
def response_evidence(history, target_week, actual, forecast, lag_block, holiday_block):
    """Sections 13, 14 and 15 in one deterministic pass, shaped for FC.

    The three things section 13 insists must not be collapsed into "Demand Spike":

        forecast-side level error   the plan was away from expected demand BEFORE the week
        demand-side movement        demand then moved away from expected
        forecast-response error     a signal existed and the plan did not react to it

    The decomposition is exact: forecast_side + demand_side == actual - forecast, so the two
    shares are arithmetic rather than an apportionment judgement.
    """
    block = fr.analyse(history, target_week, actual, forecast, lag_block, holiday_block)
    if not block.get("available"):
        block["availability"] = MISSING
        return block

    block["availability"] = AVAILABLE
    resp = block.get("response") or {}
    fcb = block.get("forecastability") or {}
    dec = block.get("miss_decomposition") or {}

    # Section 15's four conditions, stated individually so a reader can see WHICH one failed.
    # This is the gate that stops "Actual > Forecast" from becoming a forecast failure.
    signals = [s for s in (block.get("signals") or []) if s.get("detected")]
    repeatable = fcb.get("classification") in ("PREDICTABLE", "PARTIALLY_PREDICTABLE")
    # `over_response` counts as inadequate. Over-reacting IS a response failure -- a plan cut
    # further than the evidence justified is a defect, not diligence. It is included here rather
    # than excluded because the DIRECTION-COHERENCE gate is the right place to decide whether the
    # over-reaction is what produced this particular miss: an over-cut that still left the plan
    # above demand cannot explain an over-forecast, and coherence rejects it on that basis. Judging
    # it here instead would bury the decision in a boolean.
    inadequate = resp.get("classification") in ("under_response", "over_response", "no_response",
                                                "wrong_direction", "delayed_response")
    conditions = [
        {"condition": "a leading signal existed before the target week",
         "met": bool(signals),
         "measured": (", ".join(s.get("signal") for s in signals) if signals
                      else "no signal was detected before the week")},
        {"condition": "the signal has repeatable historical support for this queue",
         "met": bool(repeatable),
         "measured": f"{fcb.get('classification')} -- {fcb.get('reason')}"},
        {"condition": "the signal was actually present in the current period",
         "met": bool(signals),
         "measured": (", ".join(f"{s.get('signal')} ({s.get('direction')})" for s in signals)
                      if signals else "none present")},
        {"condition": "the forecast response was inadequate",
         "met": bool(inadequate),
         "measured": f"{resp.get('classification')} -- {resp.get('reason')}"},
    ]
    all_met = all(c["met"] for c in conditions)
    failed = [c["condition"] for c in conditions if not c["met"]]

    block["forecastability_gate"] = {
        "supports_forecast_response_failure": all_met,
        "conditions": conditions,
        "conditions_met": len([c for c in conditions if c["met"]]),
        "conditions_failed": failed,
        "verdict": (
            "A forecast-response failure IS supported: a repeatable signal was available before "
            "the week and the plan did not respond adequately to it."
            if all_met else
            "A forecast-response failure is NOT supported here, because " + failed[0] + " does "
            "not hold. The movement is therefore treated as a demand event, a contextual "
            "factor, or unconfirmed -- not as a forecast failure."),
        "rule": ("Actual above or below forecast is never on its own a forecast failure "
                 "(section 15). All four conditions must hold."),
    }
    block["baseline_error"] = {
        "material": bool((dec.get("forecast_side_share") or 0) >= 0.40
                         and dec.get("available")),
        "forecast_side_contribution": dec.get("forecast_side_contribution"),
        "forecast_side_share": dec.get("forecast_side_share"),
        "expected_demand": dec.get("expected_demand"),
        "expected_basis": dec.get("expected_basis"),
        "reading": dec.get("reading"),
        "attaches_to": ["FC-01"],
    }
    block["attaches_to"] = ["FC-01", "FC-02", "DEM-01", "DEM-02", "STA-03"]
    return block


# ==============================================================================
# Section 5 + 32 -- mechanism selection and the direction-coherence gate
# ==============================================================================
def _direction_of_miss(adherence):
    """adherence > 0 => actual BELOW plan (over-forecast). < 0 => actual ABOVE plan."""
    if adherence is None:
        return None
    return "down" if adherence > 0 else "up"


def direction_coherence(mechanism, adherence, response_block, holiday_block, lag_block):
    """Section 32. Does the mechanism push demand the way the miss actually went?

    Deterministic and applied BEFORE final confidence, so an incoherent mechanism cannot arrive
    at the card wearing a confidence score. A demand-suppressing effect cannot be promoted as the
    cause of a demand increase unless a MEASURED rebound explains the direction -- which is
    exactly what `holiday_response` measures per phase, so "post-holiday recovery" is admissible
    where the phase effect for THIS queue is positive, and is not admissible as a bare assertion.
    """
    miss = _direction_of_miss(adherence)
    if miss is None:
        return {"tested": False, "coherent": None,
                "reason": "the week's adherence could not be calculated, so direction cannot be "
                          "compared."}

    implied, basis = None, None
    if mechanism in (CALENDAR_RESPONSE_FAILURE,):
        implied = (holiday_block or {}).get("expected_direction")
        eff = ((holiday_block or {}).get("forecast_capture") or {}).get("expected_effect_pct")
        basis = (f"the measured effect of the {(holiday_block or {}).get('phase')} phase on this "
                 f"queue ({eff:+.2f}%)" if isinstance(eff, (int, float))
                 else "the measured phase effect for this queue")
    elif mechanism in (FORECAST_BASELINE_FAILURE, FORECAST_RESPONSE_FAILURE):
        # A plan set BELOW expected demand can only explain actual coming in ABOVE plan.
        side = ((response_block or {}).get("forecast_side") or {}).get("vs_expected") or {}
        d = side.get("direction")
        implied = {"below": "up", "above": "down"}.get(d)
        basis = (f"the plan sat {d} the expected level for this week "
                 f"({side.get('difference_pct'):+.1f}%)"
                 if isinstance(side.get("difference_pct"), (int, float))
                 else "the plan's position against the expected level")
    elif mechanism == DRIVER_RESPONSE_FAILURE:
        usable = (lag_block or {}).get("drivers") or []
        top = next((d for d in usable if d.get("usable_as_evidence")), None)
        if top:
            implied = "up" if top.get("direction") == "positive" else "down"
            basis = (f"{top.get('subject') or top.get('driver')} has a "
                     f"{top.get('direction')} relationship with demand at lag "
                     f"{top.get('best_lag_weeks')}")
    elif mechanism == DEMAND_EVENT_LOW_PREDICTABILITY:
        side = ((response_block or {}).get("demand_side") or {}).get("vs_expected") or {}
        implied = {"above": "up", "below": "down"}.get(side.get("direction"))
        basis = (f"demand came in {side.get('direction')} the expected level "
                 f"({side.get('difference_pct'):+.1f}%)"
                 if isinstance(side.get("difference_pct"), (int, float))
                 else "demand's position against the expected level")

    if implied is None:
        return {"tested": False, "coherent": None, "miss_direction": miss,
                "mechanism": mechanism,
                "reason": ("the direction this mechanism implies has not been measured for this "
                           "queue, so coherence cannot be established. It is NOT assumed to be "
                           "coherent.")}

    coherent = (implied == miss)
    return {
        "tested": True,
        "coherent": coherent,
        "mechanism": mechanism,
        "miss_direction": miss,
        "implied_direction": implied,
        "basis": basis,
        "reason": (f"The miss pushed demand {miss} and this mechanism implies {implied}, from "
                   f"{basis} -- the directions "
                   f"{'agree' if coherent else 'DISAGREE, so the mechanism cannot be the cause'}."),
    }


def miss_mechanism(adherence, response_block, holiday_block, lag_block, asu_block, dq_clean):
    """Sections 5 and 15: which mechanism(s) the evidence actually supports.

    Order matters and is not arbitrary. Data limitation is tested first because an
    unestablishable answer must not be dressed up as one. Then the mechanisms that require a
    REPEATABLE signal, because those are the only ones that can fairly be called a forecast
    failure. A demand event is what remains when no repeatable signal existed -- it is a genuine
    finding, not a fallback for "we could not tell".

    Every candidate then passes the direction-coherence gate (section 32) BEFORE it can be
    reported, so nothing incoherent reaches confidence.
    """
    resp = (response_block or {}).get("response") or {}
    gate = (response_block or {}).get("forecastability_gate") or {}
    base = (response_block or {}).get("baseline_error") or {}
    dec = (response_block or {}).get("miss_decomposition") or {}

    if not (response_block or {}).get("available"):
        return {"mechanisms": [DATA_LIMITATION], "primary": DATA_LIMITATION,
                "candidates": [], "rejected_for_direction": [],
                "reason": ((response_block or {}).get("reason")
                           or "the forecast-response diagnostic could not run on this history.")}

    candidates = []

    if base.get("material"):
        candidates.append({
            "mechanism": FORECAST_BASELINE_FAILURE,
            "evidence": base.get("reading"),
            "share_of_miss": dec.get("forecast_side_share"),
        })

    if gate.get("supports_forecast_response_failure"):
        candidates.append({
            "mechanism": FORECAST_RESPONSE_FAILURE,
            # The class name is an internal token. `over_response` reached executive prose verbatim
            # on a real card; section 40 wants the business story readable, and an underscore in a
            # sentence is a leaked identifier.
            "evidence": (f"The plan's reaction was judged "
                         f"{str(resp.get('classification') or '').replace('_', ' ')}. "
                         f"{resp.get('reason')}"),
            "share_of_miss": None,
        })

    cap = (holiday_block or {}).get("forecast_capture") or {}
    if ((holiday_block or {}).get("applies")
            and cap.get("classification") in ("under_reacted", "over_reacted", "wrong_direction",
                                              "delayed")):
        candidates.append({
            "mechanism": CALENDAR_RESPONSE_FAILURE,
            "evidence": cap.get("reason") or (holiday_block or {}).get("reading"),
            "share_of_miss": None,
        })

    if (lag_block or {}).get("leading_drivers"):
        candidates.append({
            "mechanism": DRIVER_RESPONSE_FAILURE,
            "evidence": ("; ".join(d.get("reading") for d in (lag_block.get("drivers") or [])
                                   if d.get("usable_as_evidence") and d.get("reading"))),
            "share_of_miss": None,
        })

    demand_unusual = ((((response_block or {}).get("demand_side") or {})
                       .get("vs_expected") or {}).get("unusual"))
    if demand_unusual and not gate.get("supports_forecast_response_failure"):
        candidates.append({
            "mechanism": DEMAND_EVENT_LOW_PREDICTABILITY,
            "evidence": ((response_block or {}).get("forecastability") or {}).get("reason"),
            "share_of_miss": dec.get("demand_side_share"),
        })

    if not dq_clean:
        candidates.append({
            "mechanism": DATA_LIMITATION,
            "evidence": "a mandatory field is blank for this period.",
            "share_of_miss": None,
        })

    # --- Section 32: the coherence gate, before anything is promoted -----------
    kept, rejected = [], []
    for c in candidates:
        coh = direction_coherence(c["mechanism"], adherence, response_block, holiday_block,
                                  lag_block)
        c["direction_coherence"] = coh
        # An UNTESTED direction is not a failure -- some mechanisms (data limitation) have no
        # direction to test. Only an explicit False rejects.
        if coh.get("coherent") is False:
            rejected.append(c)
        else:
            kept.append(c)

    if not kept:
        return {
            "mechanisms": [DATA_LIMITATION], "primary": DATA_LIMITATION,
            "candidates": candidates, "rejected_for_direction": rejected,
            "reason": ("every mechanism the evidence raised points the opposite way to the miss, "
                       "so none of them can be the cause. No defensible mechanism remains."),
        }

    # Order of preference among what survived. A mechanism that names a repeatable failure is
    # more actionable than one that says the movement was unpredictable, so it leads -- but only
    # because it SURVIVED the gate, never because it is preferred a priori.
    preference = [FORECAST_RESPONSE_FAILURE, CALENDAR_RESPONSE_FAILURE, DRIVER_RESPONSE_FAILURE,
                  FORECAST_BASELINE_FAILURE, DEMAND_EVENT_LOW_PREDICTABILITY, DATA_LIMITATION]
    kept.sort(key=lambda c: preference.index(c["mechanism"])
              if c["mechanism"] in preference else 99)

    material = [c for c in kept if c["mechanism"] != DATA_LIMITATION]
    compound = len(material) > 1
    primary = COMPOUND_MISS if compound else kept[0]["mechanism"]

    return {
        "mechanisms": [c["mechanism"] for c in kept],
        "primary": primary,
        "compound": compound,
        "compound_of": [c["mechanism"] for c in material] if compound else [],
        "candidates": kept,
        "rejected_for_direction": rejected,
        "meaning": MECHANISM_MEANING.get(primary),
        "attaches_to": sorted({h for c in kept
                               for h in MECHANISM_HYPOTHESES.get(c["mechanism"], ())}),
        "reason": ("More than one mechanism survived the direction gate and each contributed "
                   "materially." if compound else kept[0].get("evidence")),
    }


# ==============================================================================
# Section 31 -- contradiction resolution
# ==============================================================================
def evidence_resolution(supporting, contradictory, cross_exam_report, mechanism_block):
    """Section 31. supported / mixed / rejected, with the reason ONE side governs.

    The failure this prevents is two contradictory explanations both arriving verified. Where
    supporting and contradictory evidence disagree the card must show the conflict and say which
    evidence governs -- so the resolution is recorded as a decision with a stated basis, not left
    as two lists a reader has to reconcile.
    """
    rep = cross_exam_report or {}
    refutes = rep.get("refutes") or 0
    weakens = rep.get("weakens") or 0
    supports = rep.get("supports") or 0
    rejected_dir = (mechanism_block or {}).get("rejected_for_direction") or []

    conflicts = []
    for c in rejected_dir:
        conflicts.append({
            "conflict": (f"{c['mechanism']} was raised by the evidence but points the opposite "
                         f"way to the miss."),
            "governed_by": "the direction-coherence gate (section 32)",
            "resolution": c.get("direction_coherence", {}).get("reason"),
        })

    # A baseline finding and a recent-level finding can genuinely disagree; that is the example
    # the brief gives. Surface it rather than letting whichever ran last win silently.
    if supporting and contradictory:
        conflicts.append({
            "conflict": (f"{len(supporting)} item(s) support the conclusion and "
                         f"{len(contradictory)} argue against it."),
            "governed_by": ("cross-examination, which ran before confidence precisely so its "
                            "result could feed in"),
            "resolution": (f"{supports} challenge(s) found nothing wrong, {weakens} raised a "
                           f"doubt and {refutes} contradicted it outright."),
        })

    if refutes:
        state, basis = "rejected", ("a challenge question contradicted the conclusion outright, "
                                    "which is decisive regardless of how much supports it.")
    elif weakens and supports <= weakens:
        state, basis = "mixed", ("the doubts raised at cross-examination are at least as numerous "
                                 "as the answers that found nothing wrong.")
    elif weakens:
        state, basis = "mixed", (f"{supports} challenge(s) found nothing wrong against {weakens} "
                                 f"that raised a doubt, so the conclusion stands with caveats.")
    elif rejected_dir:
        state, basis = "mixed", ("the conclusion stands, but at least one mechanism the evidence "
                                 "raised had to be rejected on direction.")
    else:
        state, basis = "supported", ("no challenge question raised a doubt and no mechanism was "
                                      "rejected on direction.")

    return {
        "state": state,
        "basis": basis,
        "supporting_count": len(supporting or []),
        "contradictory_count": len(contradictory or []),
        "challenge_supports": supports, "challenge_weakens": weakens,
        "challenge_refutes": refutes,
        "conflicts": conflicts,
        "note": ("Two contradictory explanations are never both verified. Where they disagree, "
                 "the governing evidence is named."),
    }


# ==============================================================================
# Section 9 -- catalogue gaps
# ==============================================================================
def unexplained_observations(mechanism_block, generated_ids):
    """Section 9. A material mechanism with no catalogue entry that fired is RECORDED, never
    converted into an ad-hoc cause.

    This is the honest form of a catalogue gap: the engine observed something, has no sanctioned
    hypothesis to carry it, and says so for catalogue extension. The alternative -- letting the
    observation become a free-text cause -- is exactly what made the pre-catalogue engine
    irreproducible.
    """
    out = []
    fired = set(generated_ids or ())
    for c in (mechanism_block or {}).get("candidates") or []:
        mech = c.get("mechanism")
        wanted = set(MECHANISM_HYPOTHESES.get(mech, ()))
        if wanted and not (wanted & fired):
            out.append({
                "type": "UNEXPLAINED_OBSERVATION",
                "observation": mech,
                "meaning": MECHANISM_MEANING.get(mech),
                "evidence": c.get("evidence"),
                "catalogue_entries_that_would_carry_it": sorted(wanted),
                "why_recorded": ("the evidence supports this mechanism, but no catalogue "
                                 "hypothesis that could represent it was generated for this "
                                 "queue. Recorded as a catalogue gap rather than made into an "
                                 "ad-hoc cause."),
            })
    return out


# ==============================================================================
# Section 43 -- evidence IDs
# ==============================================================================
# The brief's OWN numbering. Deliberately not WFM's -- see the module docstring.
FC_EVIDENCE_LABELS = {
    "E1": "Target miss",
    "E2": "Seasonal norm / expected level",
    "E3": "Recent demand movement",
    "E4": "Forecast movement",
    "E5": "Forecast-response test",
    "E6": "ASU decomposition",
    "E7": "Shipment lag relationship",
    "E8": "UPP (upgrade base) evidence",
    "E9": "Pre-holiday effect",
    "E10": "Holiday-week effect",
    "E11": "Post-holiday effect",
    "E12": "Weekend effect",
    "E13": "Hierarchy / scope",
    "E14": "Contradiction",
    "E15": "Plan-vintage evidence",
}


def _ev(available, value, note=None):
    return {"available": bool(available), "value": value, "note": note}


def evidence_index(forecast_summary, response_block, lag_block, holiday_block, weekend_block,
                   asu_block, plan_block, scope_block, resolution_block):
    """Section 43. Every executive finding traceable to a numbered evidence item.

    An entry is `available: False` WITH A REASON rather than omitted. A missing row that simply
    is not rendered tells a reader nothing about whether it was checked.
    """
    dec = (response_block or {}).get("miss_decomposition") or {}
    dside = ((response_block or {}).get("demand_side") or {})
    fside = ((response_block or {}).get("forecast_side") or {})
    resp = (response_block or {}).get("response") or {}
    phases = (holiday_block or {}).get("historical_response") or {}

    def driver(name):
        for d in (lag_block or {}).get("drivers") or []:
            if d.get("driver") == name:
                return d
        return None

    ship, upp = driver("Final_Units"), driver("Final_upp_units")

    def phase_effect(label):
        """One phase row. An unavailable row carries the REAL reason, not a generic absence.

        "No measured post-holiday effect" and "this queue has only 3 comparable non-holiday weeks,
        and 4 are required" lead to different actions -- the second one is answerable by getting
        more history. The first reads as a finding when it is a data gap.
        """
        if not isinstance(phases, dict):
            return _ev(False, None, "the holiday phase analysis did not run for this queue.")
        if not phases.get("available"):
            return _ev(False, None,
                       (phases.get("reason")
                        or (holiday_block or {}).get("reason")
                        or "the holiday phase analysis could not be performed for this queue."))
        blk = (phases.get("phases") or {}).get(label)
        if not blk:
            return _ev(False, None,
                       f"the {label.replace('_', ' ')} phase was not measurable for this queue.")
        if not blk.get("available", True):
            return _ev(False, blk, blk.get("reason") or blk.get("note"))
        return _ev(True, blk, blk.get("reading"))

    idx = {
        "E1": _ev(forecast_summary.get("adherence_pct") is not None, forecast_summary,
                  "The week's actual, plan, signed adherence and contact gap."),
        "E2": _ev(dec.get("expected_demand") is not None,
                  {"expected_demand": dec.get("expected_demand"),
                   "basis": dec.get("expected_basis")},
                  dec.get("expected_basis")),
        "E3": _ev(bool(dside.get("vs_expected", {}).get("testable")),
                  dside.get("vs_expected"),
                  "Where demand sat against the expected level for this week of the year."),
        "E4": _ev(bool(fside.get("vs_expected", {}).get("testable")),
                  fside.get("vs_expected"),
                  "Where the plan sat against that same expected level."),
        "E5": _ev(bool(resp.get("classification")),
                  {"classification": resp.get("classification"), "reason": resp.get("reason"),
                   "gate": (response_block or {}).get("forecastability_gate")},
                  resp.get("reason")),
        "E6": _ev(bool((asu_block or {}).get("available")), asu_block,
                  (asu_block or {}).get("reading") or (asu_block or {}).get("reason")),
        "E7": _ev(bool(ship and ship.get("coverage") != "absent"), ship,
                  (ship or {}).get("reading")
                  or "shipment (planned units for delivery) was not requested or not present."),
        "E8": _ev(bool(upp and upp.get("coverage") != "absent"), upp,
                  (upp or {}).get("reading")
                  or "the upgrade/extended-protection base was not requested or not present."),
        "E9": phase_effect("pre_holiday"),
        "E10": phase_effect("holiday"),
        "E11": phase_effect("post_holiday"),
        "E12": _ev(bool((weekend_block or {}).get("weekend_analysis_supported")), weekend_block,
                   (weekend_block or {}).get("statement")),
        "E13": _ev(bool((scope_block or {}).get("available")), scope_block,
                   (scope_block or {}).get("narrative")),
        "E14": _ev(bool((resolution_block or {}).get("conflicts")), resolution_block,
                   (resolution_block or {}).get("basis")),
        "E15": _ev(bool((plan_block or {}).get("available")), plan_block,
                   (plan_block or {}).get("reading") or (plan_block or {}).get("reason")),
    }
    for eid, entry in idx.items():
        entry["id"] = eid
        entry["label"] = FC_EVIDENCE_LABELS[eid]
    return {"version": EVIDENCE_VERSION, "items": idx,
            "available_count": len([e for e in idx.values() if e["available"]]),
            "total": len(idx),
            "note": ("An item that could not be established is present and marked unavailable "
                     "with its reason, never omitted.")}
