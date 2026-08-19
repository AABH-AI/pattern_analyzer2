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
    criticality              section 30 -- FC has no criticality mechanism at all
    miss_mechanism           the seven mechanisms of section 5 (A-G)
    direction_coherence      section 32, as a deterministic gate over ALL mechanisms
    evidence_resolution      section 31 -- supported / mixed / rejected, with a governing reason
    unexplained_observations section 9 -- a catalogue gap is recorded, never made into a cause
    evidence_index           section 43 -- E1..E14 in the brief's OWN numbering.
                             E15 (plan vintage) is DELETED: this engine treats
                             `Projection_plan_name` as non-existent.

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
import statistics as _st

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

# ==============================================================================
# Section 15 -- the spec's failure-type vocabulary, and the three distinctions it draws that
# these seven mechanisms did not.
# ==============================================================================
# Published so a reader of either vocabulary can line them up. FORECAST_RESPONSE_FAILURE has no
# single counterpart: in the spec it is the GENERIC form of the INSUFFICIENT_* family, narrowed by
# which signal was missed. DATA_LIMITATION has no counterpart at all and is retained, because
# "no defensible mechanism can be stated" is a real outcome the spec's list has no room for.
SPEC_TAXONOMY_MAP = {
    FORECAST_BASELINE_FAILURE: "FORECAST_BASELINE_UNDER_LEVELING",
    CALENDAR_RESPONSE_FAILURE: "INSUFFICIENT_CALENDAR_ADJUSTMENT",
    DRIVER_RESPONSE_FAILURE: "INSUFFICIENT_DRIVER_RESPONSE",
    DEMAND_EVENT_LOW_PREDICTABILITY: "LOW-PREDICTABILITY_DEMAND_EVENT",
    COMPOUND_MISS: "COMPOUND_FORECAST_MISS",
    FORECAST_RESPONSE_FAILURE: None,
    DATA_LIMITATION: None,
}

# The three the spec distinguishes and this engine did not. They are REFINEMENTS of an existing
# mechanism, never replacements for it -- see this module's patch note.
REFINE_RESPONSE_LAG = "FORECAST_RESPONSE_LAG"
REFINE_SEASONALITY_MIS_SPEC = "SEASONALITY_MIS_SPECIFICATION"
REFINE_DRIVER_SIGNAL_ABSENT = "DRIVER_SIGNAL_NOT_AVAILABLE"

REFINEMENT_MEANING = {
    REFINE_RESPONSE_LAG: ("The plan did react, but late. Distinct from reacting too little: the "
                          "remedy is when the plan is refreshed, not the size of the adjustment."),
    REFINE_SEASONALITY_MIS_SPEC: ("The plan did not represent the level this week of the year "
                                  "reliably reaches, so the miss starts in the seasonal profile "
                                  "rather than in a within-week reaction."),
    REFINE_DRIVER_SIGNAL_ABSENT: ("No usable driver history existed to react to. Distinct from a "
                                  "driver response failure, where the signal was there and was "
                                  "not used -- one is a data gap, the other is a process gap."),
}

# How far the plan may sit from the same-week historical level before the seasonal profile is the
# story. Reuses hr.MATERIAL_SHARE so the holiday work and this share one scale.
SEASONAL_MIS_SPEC_SHARE = hr.MATERIAL_SHARE


def refine_mechanisms(candidates, response_block, lag_block):
    """Section 15's three extra distinctions, as refinements of the mechanisms already found.

    Returns a list of {refines, refinement, meaning, evidence}. It CANNOT add a mechanism, change
    the primary, or touch confidence -- see this module's patch note for why that matters.
    """
    resp = (response_block or {}).get("response") or {}
    baselines = (response_block or {}).get("baselines") or {}
    found = {c.get("mechanism") for c in (candidates or [])}
    out = []

    # 1. Reacted LATE, as against reacted too little. forecast_response already separates these;
    #    the mechanism layer collapsed both into FORECAST_RESPONSE_FAILURE.
    if resp.get("classification") == "delayed_response" and FORECAST_RESPONSE_FAILURE in found:
        out.append({
            "refines": FORECAST_RESPONSE_FAILURE,
            "refinement": REFINE_RESPONSE_LAG,
            "meaning": REFINEMENT_MEANING[REFINE_RESPONSE_LAG],
            "evidence": resp.get("reason"),
        })

    # 2. Was the plan away from the level THIS WEEK OF THE YEAR reliably reaches?
    #
    #    Reuses `baseline_error`, which the response block already computes and reconciles exactly,
    #    rather than recomputing the same gap from a plan figure the block does not carry. Fires
    #    ONLY when the expectation came from the same week in prior years: a material baseline error
    #    measured against a RECENT window is a level error, not a seasonal mis-specification, and
    #    calling it seasonal would be a claim the basis does not support.
    base_err = (response_block or {}).get("baseline_error") or {}
    expected = base_err.get("expected_demand")
    gap_contacts = base_err.get("forecast_side_contribution")
    if (base_err.get("material")
            and baselines.get("expected_basis_key") == "same_week_median"
            and expected and gap_contacts is not None
            and FORECAST_BASELINE_FAILURE in found):
        gap_share = abs(gap_contacts) / expected
        if gap_share >= SEASONAL_MIS_SPEC_SHARE:
            out.append({
                "refines": FORECAST_BASELINE_FAILURE,
                "refinement": REFINE_SEASONALITY_MIS_SPEC,
                "meaning": REFINEMENT_MEANING[REFINE_SEASONALITY_MIS_SPEC],
                "evidence": ("The plan sat %s contacts from the %s expected for this week of the "
                             "year (%s) -- %s%% of that level. The miss starts in the seasonal "
                             "profile the plan was built on, not in a within-week reaction."
                             % (rnd(abs(gap_contacts)), rnd(expected),
                                base_err.get("expected_basis"), rnd(gap_share * 100.0))),
                "gap_vs_same_week_median_pct": rnd(gap_share * 100.0),
                "expected_basis": base_err.get("expected_basis"),
            })

    # 3. No driver history to react to, as against a driver ignored. One is a data gap, the other
    #    a process gap, and they have different owners.
    if lag_block is not None:
        rows = (lag_block or {}).get("drivers") or []
        absent = [r.get("driver") for r in rows if r.get("coverage") in ("absent", "sparse")]
        if absent and DRIVER_RESPONSE_FAILURE not in found:
            out.append({
                "refines": None,
                "refinement": REFINE_DRIVER_SIGNAL_ABSENT,
                "meaning": REFINEMENT_MEANING[REFINE_DRIVER_SIGNAL_ABSENT],
                "evidence": ("No usable driver history for %s, so there was no driver signal "
                             "available to react to. This is insufficient evidence, not a driver "
                             "that was ruled out." % ", ".join(sorted(absent))),
                "drivers": sorted(absent),
            })
    return out


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

# Section 40: the response class is an internal token, and executive prose needs a sentence. These
# lead the bullet, so they name what the plan DID rather than what the field is called.
RESPONSE_PROSE = {
    "over_response": "The plan over-reacted.",
    "under_response": "The plan under-reacted.",
    "no_response": "The plan did not react at all.",
    "wrong_direction": "The plan moved the wrong way.",
    "delayed_response": "The plan reacted, but too late.",
    "adequate": "The plan reacted proportionately.",
    "not_testable": "The plan's reaction could not be judged.",
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
# Miss streak -- WITHOUT the plan-vintage column
# ==============================================================================
# WHAT WAS HERE, AND WHY IT IS GONE
# ---------------------------------
# `plan_revision()` implemented section 8 of the upgrade brief: whether the plan was reissued during
# a miss run, and whether the reissue worked (plan_not_revisited / plan_revised_but_remained_wrong /
# plan_revised_appropriately). It rested entirely on `Projection_plan_name`.
#
# The column is now treated by this engine AS IF IT DOES NOT EXIST, at the user's instruction, and the
# section 8 finding is deleted with it -- keys and all. That is a deliberate departure from the brief,
# recorded here rather than left for someone to discover from an absence.
#
# It is also a defensible one on the data: the column holds MONTHLY projection vintages ("FY27 May
# Projection"), which change on a calendar cycle rather than in response to a miss. `prompts.py`
# already forbids the WFM model from citing those updates as a cause for a WEEKLY miss, and
# `lag_analysis.NOT_DRIVERS` already excludes the column from driver testing. So a reissue mid-run is
# usually the monthly cycle arriving, not somebody reacting -- which is precisely what made
# "the plan was revisited and stayed wrong" read as an accusation on every queue.
#
# WHAT SURVIVES: the MISS STREAK. Criticality lifts a band when a miss is standing rather than
# isolated, and that lift is worth keeping. The streak was computed inside `plan_revision` only
# because that is where it was first needed -- it is derived from adherence alone and never touched
# the plan name, so it moves here intact rather than being lost along with the finding.


def miss_streak(history, threshold_pct=None):
    """How many consecutive weeks, ending at the target, missed in the SAME direction.

    Derived from adherence only. No plan-vintage column is read, and none is needed.

    A week inside the generation threshold is not a miss and ENDS the run -- see MISS_THRESHOLD_PCT.
    Without that, a queue whose actual exactly equals its forecast reported a run stretching back to
    the start of its history.
    """
    limit = MISS_THRESHOLD_PCT if threshold_pct is None else threshold_pct
    rows = [(h.get("Fiscal_Week"), num(h.get("Actual_Offered")), num(h.get("fcst_offered")))
            for h in (history or [])]
    rows = [(w, a, f) for w, a, f in rows if a is not None and f is not None]
    if not rows:
        return {"available": False, "weeks": 0, "direction": None, "began_at_week": None,
                "reason": "no paired actual/forecast history is available for this queue."}

    direction, streak, first_week = None, 0, None
    for w, a, f in reversed(rows):
        adh = adherence_pct(a, f)
        if adh is None or abs(adh) <= limit:
            break
        d = "under" if a > f else "over"
        if direction is None:
            direction = d
        if d != direction:
            break
        streak += 1
        first_week = w

    return {
        "available": True,
        "weeks": streak,
        "direction": direction,
        "began_at_week": first_week,
        "standing": streak >= 2,
        "reading": (f"This queue has missed in the same direction ({direction}-forecast) for "
                    f"{streak} consecutive week(s), beginning at fiscal week {first_week}."
                    if streak >= 2 else
                    "This week's miss does not continue a run -- the previous week was either "
                    "within threshold or missed the other way."),
        "note": ("Counted from adherence only. A week inside the generation threshold is not a miss "
                 "and ends the run."),
    }


# ==============================================================================
# Section 16-18 -- lagged driver evidence, hypothesis-selected
# ==============================================================================
# Bands the gate calls sub-threshold but non-trivial. "negligible" (|r| < 0.10) is left out on
# purpose: re-examining a coefficient that small invites reading noise as a signal, which is the
# opposite failure from the one section 17 is guarding against.
_ENRICHABLE_BANDS = ("very weak", "weak", "moderate", "strong", "very strong")


def _strongest_candidate(lag_row):
    """The strongest TESTABLE lag/change candidate, whether or not it clears MIN_STRENGTH.

    `lag_analysis` only sets `best` when a candidate reaches MIN_STRENGTH (0.5). For exactly the
    drivers this enrichment exists for -- the weak ones -- that means `best` is always None, so
    reading `best` alone would make this block a restatement of the gate. Section 16 asks what the
    relationship looks like at lags 0/1/2/4/8 on level AND change; that answer exists in
    `candidates` either way, and reporting it sub-threshold is the point.
    """
    cands = [c for c in (lag_row.get("candidates") or [])
             if c.get("testable") and isinstance(c.get("relationship_strength"), (int, float))]
    if not cands:
        return None, len(lag_row.get("candidates") or [])
    return max(cands, key=lambda c: abs(c["relationship_strength"])), len(cands)


def _rejected_driver_enrichment(history, target_week, gate_results):
    """Run the lag analysis for drivers the RELEVANCE GATE rejected on a measurable coefficient.

    Strictly enrichment. Published under its own key, it never sets `available`, and it is never
    read by confidence or by hypothesis generation -- so a driver cannot re-enter as evidence
    through this path. Its only job is to stop "not confirmed at the gate" being the last word,
    which is what section 17 asks for in as many words.
    """
    rejected = [g for g in (gate_results or [])
                if not g.get("relevant")
                and g.get("relationship_state") == "not_confirmed"
                and g.get("strength_band") in _ENRICHABLE_BANDS]
    if not rejected:
        return {"available": False,
                "reason": ("no driver was rejected on a measurable-but-sub-threshold "
                           "coefficient, so there is nothing for a lag test to revisit.")}

    full = lag_analysis.analyse(history, target_week)
    if not full.get("available"):
        return {"available": False,
                "reason": full.get("reason") or "the lag analysis could not run on this history."}

    by_name = {d.get("driver"): d for d in (full.get("drivers") or [])}
    rows = []
    for g in rejected:
        name = g.get("driver")
        d = by_name.get(name) or {}
        top, n_tested = _strongest_candidate(d)
        rows.append({
            "driver": name,
            "label": g.get("label") or name,
            "gate_verdict": "not_confirmed",
            "gate_r": g.get("correlation"),
            "gate_direction": g.get("direction"),
            "gate_strength": g.get("strength_band"),
            "gate_lags_scanned": g.get("lags_scanned"),
            "coverage": d.get("coverage"),
            "candidates_tested": n_tested,
            "strongest_lag_weeks": (top or {}).get("lag_weeks"),
            "strongest_relationship": (top or {}).get("relationship_type"),
            "strongest_strength": (top or {}).get("relationship_strength"),
            "strongest_direction": (top or {}).get("direction"),
            "stability": (top or {}).get("stability"),
            "clears_evidence_threshold": bool((top or {}).get("strong_enough")),
            "interpretation": d.get("interpretation"),
            # Deliberately never "usable_as_evidence". This block cannot promote a driver.
            "changes_the_gate_verdict": False,
            "reading": _enrichment_reading(g, d, top),
        })
    return {"available": True, "drivers": rows,
            "lags_tested": list(lag_analysis.LAGS),
            "families_tested": ["level", "change"],
            "note": ("Sections 16-17. These drivers did NOT pass the relevance gate and are not "
                     "used as evidence, in any hypothesis, or in confidence. They are re-examined "
                     "at lags 0/1/2/4/8 on both levels and week-to-week change so that a "
                     "sub-threshold same-period coefficient is not the last word on them."),
            "feeds_confidence": False, "feeds_hypotheses": False}


def _enrichment_reading(gate, lag_row, top):
    """One sentence in section 17's required shape: strength, direction, timing, sample, limits."""
    label = gate.get("label") or gate.get("driver")
    r = gate.get("correlation")
    head = (f"{label} showed a {gate.get('strength_band')} {gate.get('direction')} relationship at "
            f"the gate (r={r:+.2f})" if isinstance(r, (int, float))
            else f"{label} was not measurable at the gate")

    cov = lag_row.get("coverage")
    if cov in ("absent", None):
        return (head + ", and this queue's history has no usable paired observations for it, so no "
                       "lag or change relationship could be established. Insufficient evidence -- "
                       "not a finding that the driver has no influence.")
    if not top:
        return (head + f", and none of the {len(lag_row.get('candidates') or [])} lag/change "
                       f"combinations tested was measurable (too few paired weeks, or the driver "
                       f"does not vary). Insufficient evidence rather than absence.")

    rho = top.get("relationship_strength")
    kind = str(top.get("relationship_type") or "").replace("_", " ")
    tail = (f". Re-tested at lags {min(lag_analysis.LAGS)}-{max(lag_analysis.LAGS)} on both levels "
            f"and week-to-week change, the strongest is {kind} at a {top.get('lag_weeks')}-week "
            f"lag (rho={rho:+.2f}, {top.get('stability') or 'stability not assessed'})")

    if top.get("strong_enough"):
        return (head + tail + " -- which DOES reach the strength this engine treats as evidence, "
                              "so this driver is worth a second look before it is dismissed. It "
                              "still does not change the gate verdict on its own.")
    if cov == "sparse":
        return (head + tail + ", but coverage is sparse, so it is reported as sparse rather than "
                              "treated as established.")
    return (head + tail + ", still short of the strength needed to call it evidence. This is why "
                          "the driver should be described as not confirmed rather than absent.")


def lagged_driver_evidence(history, target_week, generated_ids, gate_results=None):
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
                         "driver is not a driver that was ruled out."),
                # Sections 16-17 of new_prompt.md: "A lagged relationship should be evaluated
                # BEFORE shipment influence is rejected." Without this the lag analysis was
                # unreachable in practice -- the gate rejects a driver on its coefficient, no
                # business hypothesis fires, nothing requests the lag test, and the richer
                # analysis never ran on ANY queue measured. Audited on three: SA Indonesia
                # FW202716, UKI FW202717 and Brazil CEM ProSupport FW202722 (Pro offering with
                # Planned_ASU 2,307,202) -- all three reported "nothing was tested".
                "enrichment": _rejected_driver_enrichment(history, target_week, gate_results)}

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
# Section 12. Day patterns that place a holiday against the weekend, so the closure runs across
# consecutive days rather than interrupting a single midweek day.
LONG_WEEKEND_PATTERNS = ("holiday_adjoining_weekend", "holiday_on_weekend")


# ==============================================================================
# prompt2.md clause M -- the five data-availability states.
# Published ALONGSIDE the engine's Available / Missing / NotApplicable, never instead of them: those
# three feed confidence dimensions and moving them would breach new_prompt.md sections 1 and 25.
# ==============================================================================
P2_AVAILABLE = "AVAILABLE"
P2_PARTIAL = "PARTIALLY_AVAILABLE"
P2_NOT_AVAILABLE = "NOT_AVAILABLE"
P2_NOT_TESTABLE = "NOT_TESTABLE"
P2_INCONCLUSIVE = "INCONCLUSIVE"

# Engine vocabulary -> prompt2 vocabulary. "Missing" maps to PARTIALLY_AVAILABLE rather than
# NOT_AVAILABLE because in this engine Missing means "relevant and present but too thin to rely on",
# which is a different finding from absent -- the distinction section 17 of new_prompt.md turns on.
P2_STATE_MAP = {
    AVAILABLE: P2_AVAILABLE,
    MISSING: P2_PARTIAL,
    NOT_APPLICABLE: P2_NOT_AVAILABLE,
}

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def p2_state(engine_availability, testable=None):
    """Map an engine availability onto prompt2's five states.

    `testable=False` overrides to NOT_TESTABLE: the data may exist while the QUESTION cannot be
    answered from it, which is the whole point of clause C's first state.
    """
    if testable is False:
        return P2_NOT_TESTABLE
    return P2_STATE_MAP.get(engine_availability, P2_INCONCLUSIVE)


def weekday_outcomes(history, granularity=None, target_fields=None):
    """prompt2.md clause K: historical weekly outcomes grouped by the WEEKDAY a holiday fell on.

    Grouping comes from the row's Monday..Sunday flags. That is legitimate for this question -- the
    flags say which weekday a holiday touched, which is precisely what clause K asks -- while clause
    A's prohibition is on reading them as daily VOLUME. Every figure below is therefore a weekly
    total for weeks of that shape, and the wording says so.

    Reference group is weeks with no holiday day flagged at all.
    """
    gran = granularity or data_granularity.analyse(history, (target_fields or {}))
    if not (gran.get("capabilities") or {}).get("holiday_day_of_week"):
        return {"testable": False, "p2_state": P2_NOT_TESTABLE,
                "reason": "the per-day holiday flags are unavailable or not confirmed as flags"}

    ref, by_day = [], {d: [] for d in WEEKDAYS}
    for row in (history or []):
        actual = num(row.get("Actual_Offered"))
        if actual is None:
            continue
        flagged = [d for d in WEEKDAYS if (num(row.get(d)) or 0) > 0]
        if not flagged:
            ref.append(actual)
            continue
        # A week with two holiday days counts toward BOTH weekdays. It is one week of evidence for
        # each shape, not half a week of each, and pretending otherwise would understate both.
        for d in flagged:
            by_day[d].append(actual)

    if len(ref) < hr.MIN_PHASE_INSTANCES:
        return {"testable": False, "p2_state": P2_NOT_TESTABLE,
                "reason": ("only %d week(s) have no holiday day flagged, so there is no reference "
                           "level to compare weekday shapes against" % len(ref))}
    ref_median = _st.median(ref)

    days = {}
    for d in WEEKDAYS:
        vals = by_day[d]
        if len(vals) < hr.MIN_PHASE_INSTANCES:
            days[d] = {"measurable": False, "weeks": len(vals),
                       "p2_state": P2_PARTIAL if vals else P2_NOT_AVAILABLE,
                       "reason": ("only %d week(s) with a holiday on %s; %d needed"
                                  % (len(vals), d, hr.MIN_PHASE_INSTANCES))}
            continue
        med = _st.median(vals)
        eff = ((med / ref_median - 1.0) * 100.0) if ref_median else None
        days[d] = {"measurable": True, "weeks": len(vals), "p2_state": P2_AVAILABLE,
                   "median_actual": rnd(med),
                   "effect_vs_no_holiday_week_pct": rnd(eff) if eff is not None else None,
                   "reading": ("Weeks with a holiday on %s have historically run %s%% against this "
                               "queue's no-holiday level, across %d week(s). This is a WEEKLY "
                               "outcome for weeks of that shape -- it is not a %s volume effect."
                               % (d, rnd(eff) if eff is not None else "n/a", len(vals), d))}
    measurable = {d: v for d, v in days.items() if v.get("measurable")}
    spread = None
    if len(measurable) > 1:
        effs = [v["effect_vs_no_holiday_week_pct"] for v in measurable.values()
                if v.get("effect_vs_no_holiday_week_pct") is not None]
        if effs:
            spread = rnd(max(effs) - min(effs))
    return {
        "testable": True, "p2_state": P2_AVAILABLE,
        "reference": {"weeks_with_no_holiday_day": len(ref), "median_actual": rnd(ref_median)},
        "weekdays": days,
        "measurable_weekdays": sorted(measurable),
        "spread_across_weekdays_pts": spread,
        "measures": ("weekly totals for weeks in which a holiday fell on each weekday. Clause K: "
                     "the correct reading is 'historical weekly outcomes differ when the holiday "
                     "falls on X', never 'X caused a volume reduction'."),
    }


def holiday_weekend_interaction(history, target_fields, granularity=None):
    """Section 12: does a holiday that ADJOINS the weekend behave differently from a midweek one?

    WHAT THIS CAN AND CANNOT SAY. Weekly totals cannot isolate a weekend volume effect -- section 11
    and `weekend_evidence` both say so, and that does not change here. What the per-day holiday flags
    DO permit is grouping this queue's own holiday weeks by where the holiday fell and comparing the
    WEEK-LEVEL total between those groups. A long weekend removes more consecutive contactable days
    than a midweek holiday, so if that matters for this queue it shows up as a difference between the
    groups. That is a real answer to section 12's question and it is NOT the claim that the weekend
    moved volume.

    Thresholds are reused rather than invented: `hr.MIN_PHASE_INSTANCES` (4) for a group to be
    measurable, and `hr.MATERIAL_SHARE` (10 percentage points here) for a difference between two
    groups to count. One scale across the holiday work, not three.
    """
    gran = granularity or data_granularity.analyse(history, (target_fields or {}))
    if not (gran.get("capabilities") or {}).get("holiday_day_of_week"):
        return {"testable": False,
                "reason": ("the per-day holiday flags are unavailable or not confirmed as flags, so "
                           "the day a holiday fell on cannot be established"),
                "note": ("A limit of the source, not a finding that long weekends do not matter "
                         "for this queue.")}

    buckets = {}
    for row in (history or []):
        actual = num(row.get("Actual_Offered"))
        if actual is None:
            continue
        st = data_granularity.holiday_day_structure(row, gran)
        if not st.get("testable"):
            continue
        buckets.setdefault(st.get("pattern") or "none", []).append(actual)

    # Reference = weeks with NO holiday day flagged. Named precisely, because it is NOT the same
    # construct as holiday_response's non-holiday baseline, which also excludes pre- and
    # post-holiday phase weeks. Two similar baselines under one name is exactly how section 9's
    # measurement A and measurement B came to be conflated.
    ref = buckets.get("none") or []
    if len(ref) < hr.MIN_PHASE_INSTANCES:
        return {"testable": False,
                "reason": ("only %d week(s) in this queue's history have no holiday day flagged, "
                           "so there is no reference level to compare against" % len(ref))}
    ref_median = _st.median(ref)

    groups = {}
    for pattern, vals in sorted(buckets.items()):
        if pattern in ("none", None):
            continue
        if len(vals) < hr.MIN_PHASE_INSTANCES:
            groups[pattern] = {"measurable": False, "instances": len(vals),
                               "reason": ("only %d week(s) of this pattern; %d are needed"
                                          % (len(vals), hr.MIN_PHASE_INSTANCES))}
            continue
        med = _st.median(vals)
        effect = ((med / ref_median - 1.0) * 100.0) if ref_median else None
        groups[pattern] = {
            "measurable": True, "instances": len(vals),
            "median_actual": rnd(med),
            "effect_vs_no_holiday_week_pct": rnd(effect) if effect is not None else None,
            "direction": (None if effect is None else
                          ("up" if effect > 0 else ("down" if effect < 0 else "flat"))),
        }

    # THE section 12 question, asked directly rather than inferred from a holiday count.
    material_pts = hr.MATERIAL_SHARE * 100.0
    adjoining = groups.get("holiday_adjoining_weekend") or {}
    midweek = groups.get("midweek_holiday") or {}
    contrast = {"testable": False,
                "reason": ("both an adjoining-weekend group and a midweek group need %d or more "
                           "weeks before the two can be compared" % hr.MIN_PHASE_INSTANCES)}
    if adjoining.get("measurable") and midweek.get("measurable"):
        a = adjoining.get("effect_vs_no_holiday_week_pct")
        m = midweek.get("effect_vs_no_holiday_week_pct")
        if a is not None and m is not None:
            diff = a - m
            is_material = bool(abs(diff) >= material_pts)
            reading = ("Holiday weeks that adjoin the weekend run %s%% against this queue's "
                       "no-holiday level, versus %s%% for a midweek holiday -- a difference of "
                       "%s points. On this queue's own history the long-weekend structure %s make "
                       "a material difference to the week's total."
                       % (rnd(a), rnd(m), rnd(abs(diff)),
                          "does" if is_material else "does not"))
            if not is_material:
                reading += (" The two behave closely enough that the day a holiday falls on is not "
                            "worth a separate plan adjustment for this queue.")
            contrast = {
                "testable": True,
                "adjoining_effect_pct": rnd(a), "midweek_effect_pct": rnd(m),
                "difference_pts": rnd(diff),
                "material": is_material,
                "material_threshold_pts": rnd(material_pts),
                "adjoining_is_deeper": bool(abs(a) > abs(m)),
                "reading": reading,
            }

    target_st = data_granularity.holiday_day_structure(target_fields or {}, gran)
    target_pattern = target_st.get("pattern") if target_st.get("testable") else None
    return {
        "testable": True,
        "reference": {"weeks_with_no_holiday_day": len(ref), "median_actual": rnd(ref_median)},
        "patterns": groups,
        "long_weekend_contrast": contrast,
        "target_pattern": target_pattern,
        "long_weekend_flag": bool(target_pattern in LONG_WEEKEND_PATTERNS),
        "interaction_material": (contrast.get("material") if contrast.get("testable") else None),
        "measures": ("week-level totals grouped by the day a holiday fell on. NOT an isolated "
                     "weekend volume effect -- weekly grain cannot provide one, and none is "
                     "claimed."),
    }


def _weekend_three_states(history, target_fields, gran, supported):
    """prompt2.md clause C. Three questions, answered separately.

    Collapsing them is what produced a card that said "weekend impact cannot be isolated" and left
    the reader with nothing -- when two of the three ARE answerable from weekly data.
    """
    inter = holiday_weekend_interaction(history, target_fields, gran)
    wd = weekday_outcomes(history, gran, target_fields)
    meas = wd.get("measurable_weekdays") or []
    ct = inter.get("long_weekend_contrast") or {}
    pats = {k: v for k, v in (inter.get("patterns") or {}).items() if v.get("measurable")}

    # BUG 2. `testable` says only that the ATTEMPT was possible. On China FW202435 it was True while
    # 0 of 7 weekdays cleared the instance floor, and the row still claimed AVAILABLE -- the same
    # class of error as asserting a driver is absent from a weak coefficient.
    if not wd.get("testable") or not meas:
        struct_state = P2_NOT_TESTABLE
    elif len(meas) >= 5:
        struct_state = P2_AVAILABLE
    else:
        struct_state = P2_PARTIAL

    # BUG 1. Say what was FOUND, not only what could not be. A blank cell against "AVAILABLE" told
    # the reader nothing and made the table look broken.
    if struct_state == P2_NOT_TESTABLE:
        struct_why = (wd.get("reason")
                      or ("the weekday groups each hold fewer than the %d weeks needed, so no "
                          "weekday can be compared" % hr.MIN_PHASE_INSTANCES))
    else:
        struct_why = ("%d of 7 weekdays have enough history to compare" % len(meas))
        if wd.get("spread_across_weekdays_pts") is not None:
            struct_why += (", and weekly outcomes differ by %s points between the strongest and "
                           "weakest of them" % wd.get("spread_across_weekdays_pts"))
        if len(meas) < 7:
            struct_why += (" (%s not measurable)"
                           % ", ".join(d for d in WEEKDAYS if d not in meas))
        struct_why += "."

    if not inter.get("testable"):
        inter_why = inter.get("reason") or "the holiday day pattern could not be established"
    elif ct.get("testable"):
        inter_why = ("%d day-pattern group(s) measurable; adjoining-weekend %s versus midweek %s, a "
                     "%s-point difference, which %s material against the %s-point bar."
                     % (len(pats), ct.get("adjoining_effect_pct"), ct.get("midweek_effect_pct"),
                        ct.get("difference_pts"), "IS" if ct.get("material") else "is not",
                        ct.get("material_threshold_pts")))
    else:
        inter_why = ("%d day-pattern group(s) measurable, but %s"
                     % (len(pats), (ct.get("reason") or "the two groups cannot yet be compared")))

    return {
        "daily_weekend_demand_effect": {
            "state": P2_NOT_TESTABLE if not supported else P2_AVAILABLE,
            "reason": (gran.get("weekend_statement") if not supported else
                       "day-level actual and forecast measures are present in this source"),
            "note": ("Clause A: the Monday..Sunday columns are holiday FLAGS, not daily volumes, so "
                     "no Saturday or Sunday demand figure exists to test."),
        },
        "weekly_calendar_structure": {
            "state": struct_state,
            "measurable_weekdays": meas,
            "spread_across_weekdays_pts": wd.get("spread_across_weekdays_pts"),
            "reason": struct_why,
        },
        "holiday_weekend_interaction": {
            "state": (P2_AVAILABLE if (inter.get("testable") and ct.get("testable"))
                      else (P2_PARTIAL if inter.get("testable") else P2_NOT_TESTABLE)),
            "material": ct.get("material"),
            "reason": inter_why,
        },
        "note": ("Clause C: the weekend is not one question. A daily demand effect is not testable "
                 "on this source; weekly calendar structure and the holiday-weekend interaction "
                 "are. Reporting only the first would understate what the data supports."),
    }


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
        # Section 12, additive. A different question from the statement above: not "can a
        # weekend effect be isolated" (it cannot) but "does this queue behave differently
        # when a holiday adjoins the weekend", which weekly totals CAN answer.
        "holiday_weekend_interaction": holiday_weekend_interaction(history, target_fields, gran),
        # prompt2.md clause C -- the weekend is THREE questions with three different answers, and
        # the document names stopping at "weekend impact cannot be isolated" as the error. The
        # limitation above is still true and still stated; these say what IS answerable.
        "clause_c_states": _weekend_three_states(history, target_fields, gran, supported),
        # Clause K: per-weekday historical outcomes, a weekly reading and never a daily one.
        "weekday_outcomes": weekday_outcomes(history, gran, target_fields),
        # Clause M, mapped rather than replacing the engine's own availability.
        "p2_state": p2_state(AVAILABLE if supported else NOT_APPLICABLE, testable=supported),
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
                "refinements": [], "spec_taxonomy": {DATA_LIMITATION: None},
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
            # sentence is a leaked identifier. Stripping the underscore was not enough -- "judged
            # over response" is still not English. Each class gets a phrase written for a reader.
            "evidence": (f"{RESPONSE_PROSE.get(resp.get('classification'), 'The plan reacted.')} "
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
        # DATA_LIMITATION is the right BAND -- no defensible mechanism can be stated -- but its stock
        # meaning ("critical evidence is missing") would mislead here, and did on a live case with 156
        # weeks of history where every candidate was rejected on DIRECTION. Nothing was missing; every
        # explanation the evidence raised pointed the wrong way. Those are different findings and want
        # different follow-up, so this path carries its own meaning.
        return {
            "mechanisms": [DATA_LIMITATION], "primary": DATA_LIMITATION,
            "candidates": candidates, "rejected_for_direction": rejected,
            "refinements": [], "spec_taxonomy": {DATA_LIMITATION: None},
            "all_candidates_rejected_on_direction": True,
            "meaning": ("Every explanation the evidence raised would push demand the OPPOSITE way "
                        "to the miss, so none of them can be the cause. This is not missing data -- "
                        "it is data that rules out each candidate."),
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
        # Section 15. REFINEMENTS of the mechanisms above, never additions to them: `mechanisms`,
        # `primary`, `candidates` and `attaches_to` are untouched, so rejected_ids, ModelAgreement
        # and confidence cannot move. That is section 24's instruction -- enrich, do not replace.
        "refinements": refine_mechanisms(kept, response_block, lag_block),
        "spec_taxonomy": {c["mechanism"]: SPEC_TAXONOMY_MAP.get(c["mechanism"]) for c in kept},
        "spec_taxonomy_note": ("The spec names eight failure types, this engine seven. The mapping "
                               "is published rather than the names changed, because renaming would "
                               "alter published response values and the hypothesis attachments. "
                               "FORECAST_RESPONSE_FAILURE is the generic form of the spec's "
                               "INSUFFICIENT_* family; DATA_LIMITATION has no counterpart in the "
                               "spec's list and is retained."),
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
}


def _ev(available, value, note=None):
    return {"available": bool(available), "value": value, "note": note}


def evidence_index(forecast_summary, response_block, lag_block, holiday_block, weekend_block,
                   asu_block, scope_block, resolution_block):
    """Section 43. Every executive finding traceable to a numbered evidence item.

    An entry is `available: False` WITH A REASON rather than omitted. A missing row that simply
    is not rendered tells a reader nothing about whether it was checked.

    FOURTEEN items, not fifteen. The brief's E15 was plan-vintage evidence, and this engine treats
    `Projection_plan_name` as non-existent -- so E15 is DELETED rather than shipped permanently
    unavailable. A row that can never be established is not information; it is a promise the engine
    cannot keep. The remaining IDs keep their original numbers so nothing that already cites E1..E14
    has to be re-read.
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
    }
    for eid, entry in idx.items():
        entry["id"] = eid
        entry["label"] = FC_EVIDENCE_LABELS[eid]
    return {"version": EVIDENCE_VERSION, "items": idx,
            "available_count": len([e for e in idx.values() if e["available"]]),
            "total": len(idx),
            "note": ("An item that could not be established is present and marked unavailable "
                     "with its reason, never omitted.")}
