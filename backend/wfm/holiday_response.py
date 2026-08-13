# -*- coding: utf-8 -*-
"""
Holiday phase analysis -- and whether the FORECAST captured the holiday, not just whether one fell.

WHY THIS MODULE EXISTS
----------------------
Two separate failures in the engine's holiday reasoning motivated this module.

1. `Holiday_Count = 0` was treated as "no holiday effect". The holiday calendar already knew
   better -- it can see a holiday in the neighbouring week whose run-up or wind-down reaches into
   this one -- but that knowledge was only wired into the spec engine, and only at +/-1 week. A
   target week can sit in a post-holiday rebound with a row flag of zero, and the WFM engine had
   no way to say so (spec section 17).

2. Holiday direction was asserted rather than measured. A holiday makes SOME queues quieter
   (fewer contactable days) and others busier (a rebound, or a pre-holiday rush). Assuming the
   first is how an earlier engine came to blame a holiday for a week that ran BUSIER -- an
   explanation pointing the opposite way to the miss. Nothing here assumes a direction: every
   phase's effect is measured from the queue's own history, and if the history is inconsistent the
   module says so instead of picking a side.

WHAT IT ANSWERS
---------------
    Which phase is the target week in?              pre_holiday / holiday / post_holiday / none
    What does that phase historically DO here?      measured ratio vs the queue's non-holiday level
    Is that historical response consistent?         share of instances that moved the same way
    Did DEMAND behave that way this time?
    Did the FORECAST anticipate it?                 captured / under_reacted / over_reacted /
                                                    wrong_direction / delayed / inconsistent_history
                                                    / not_testable

The last line is the point. A holiday that a queue reliably reacts to, on a date known years in
advance, is the most forecastable event there is -- so a forecast that misses it is a genuine
response failure. A holiday whose historical response is all over the place is not something the
forecast can be blamed for.

DEPENDENCIES: standard library, plus the existing holiday calendar repository.
"""
import statistics as _st

from .context_repository import holiday_calendar as _cal

# --- how far either side of the target week to look for holidays (spec section 16: H-2..H+2). ---
SPAN_WEEKS = 2

# --- a phase needs this many historical instances before its effect is called measured. Three is
#     too few to distinguish an effect from two coincidences; four is the practical floor on a
#     queue with only two or three years of history. ---
MIN_PHASE_INSTANCES = 4

# --- how far a phase's median demand must sit from the non-holiday level to count as an effect. ---
MATERIAL_SHARE = 0.10

# --- share of historical instances that must move the same way for the response to be dependable.
#     Below this the history is reported as inconsistent and no forecast blame is attached. ---
CONSISTENT_SHARE = 0.70

# --- forecast capture tolerance, as a share of the effect the history implied. ---
CAPTURE_TOLERANCE = 0.50    # captured at least half of the historical effect == captured
OVER_CAPTURE = 1.75         # more than this much of it == over-reacted

CAPTURE_CLASSES = ("captured", "under_reacted", "over_reacted", "wrong_direction", "delayed",
                   "inconsistent_history", "not_testable")


def _num(v):
    if v is None or v is True or v is False:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _rnd(v, nd=2):
    return round(v, nd) if isinstance(v, (int, float)) and not isinstance(v, bool) else v


def _rows(history, target_week):
    """Chronological (week, forecast, actual) strictly before the target week."""
    out = []
    for row in history or []:
        wk = _num((row or {}).get("Fiscal_Week"))
        if wk is None or (target_week is not None and int(wk) >= int(target_week)):
            continue
        f, a = _num(row.get("fcst_offered")), _num(row.get("Actual_Offered"))
        if a is None or a <= 0:
            continue
        out.append((int(wk), f, a))
    out.sort(key=lambda t: t[0])
    return out


def _phase_of(country, week, cache):
    """Phase label for one historical week, memoised -- 150+ weeks x a dict lookup each."""
    if week not in cache:
        span = _cal.holiday_span(country, week, span=SPAN_WEEKS)
        cache[week] = span if span.get("available") else None
    span = cache[week]
    if not span:
        return None, None
    return span.get("phase"), span


def _historical_phase_effect(rows, country, cache):
    """Measure what each phase historically does to demand AND to the forecast for this queue.

    Baseline is the median of weeks in no phase at all. Median throughout: a single freak week
    inside a phase would otherwise define that phase's "normal".
    """
    buckets = {_cal.PHASE_HOLIDAY: [], _cal.PHASE_PRE: [], _cal.PHASE_POST: [],
               _cal.PHASE_NONE: []}
    for wk, f, a in rows:
        phase, _ = _phase_of(country, wk, cache)
        if phase is None:
            continue
        buckets.setdefault(phase, []).append((wk, f, a))

    base_rows = buckets.get(_cal.PHASE_NONE) or []
    base_actuals = [a for _, _, a in base_rows]
    base_forecasts = [f for _, f, _ in base_rows if f is not None]
    if len(base_actuals) < MIN_PHASE_INSTANCES:
        return {"available": False,
                "reason": (f"only {len(base_actuals)} weeks with no holiday phase, so there is no "
                           f"non-holiday baseline to measure holiday effects against"),
                "phases": {}}
    base_actual = _st.median(base_actuals)
    base_forecast = _st.median(base_forecasts) if base_forecasts else None

    phases = {}
    for phase in (_cal.PHASE_HOLIDAY, _cal.PHASE_PRE, _cal.PHASE_POST):
        entries = buckets.get(phase) or []
        actuals = [a for _, _, a in entries]
        forecasts = [f for _, f, _ in entries if f is not None]
        if len(actuals) < MIN_PHASE_INSTANCES:
            phases[phase] = {
                "testable": False, "instances": len(actuals),
                "reason": (f"only {len(actuals)} historical week(s) in this phase "
                           f"({MIN_PHASE_INSTANCES} required to measure a response)"),
            }
            continue
        median_actual = _st.median(actuals)
        actual_share = median_actual / base_actual - 1.0 if base_actual else None
        # consistency: how many instances moved the same way as the phase median
        if actual_share is None or actual_share == 0:
            consistency = None
        elif actual_share > 0:
            consistency = sum(1 for a in actuals if a > base_actual) / len(actuals)
        else:
            consistency = sum(1 for a in actuals if a < base_actual) / len(actuals)
        median_forecast = _st.median(forecasts) if forecasts else None
        forecast_share = (median_forecast / base_forecast - 1.0
                          if median_forecast is not None and base_forecast else None)
        phases[phase] = {
            "testable": True,
            "instances": len(actuals),
            "median_actual": _rnd(median_actual),
            "baseline_actual": _rnd(base_actual),
            "actual_effect_pct": _rnd((actual_share or 0) * 100.0),
            "direction": ("up" if (actual_share or 0) > 0 else
                          ("down" if (actual_share or 0) < 0 else "flat")),
            "material": abs(actual_share or 0) >= MATERIAL_SHARE,
            "consistency": _rnd(consistency, 3) if consistency is not None else None,
            "consistent": bool(consistency is not None and consistency >= CONSISTENT_SHARE),
            "median_forecast": _rnd(median_forecast),
            "baseline_forecast": _rnd(base_forecast),
            "forecast_effect_pct": _rnd((forecast_share or 0) * 100.0)
            if forecast_share is not None else None,
            "historically_planned_for": bool(
                forecast_share is not None and actual_share is not None
                and (forecast_share > 0) == (actual_share > 0)
                and abs(forecast_share) >= abs(actual_share) * CAPTURE_TOLERANCE),
        }
        phases[phase]["reading"] = _phase_reading(phase, phases[phase])
    return {"available": True, "baseline_actual": _rnd(base_actual),
            "baseline_forecast": _rnd(base_forecast),
            "baseline_weeks": len(base_actuals), "phases": phases}


def _phase_reading(phase, block):
    label = {_cal.PHASE_HOLIDAY: "Weeks containing a holiday",
             _cal.PHASE_PRE: "Weeks running up to a holiday",
             _cal.PHASE_POST: "Weeks following a holiday"}.get(phase, phase)
    if not block.get("testable"):
        return f"{label}: {block.get('reason')}"
    effect = block.get("actual_effect_pct")
    direction = "above" if (effect or 0) > 0 else "below"
    text = (f"{label} have historically run {_rnd(abs(effect or 0))}% {direction} this queue's "
            f"non-holiday level, across {block.get('instances')} week(s)")
    if block.get("consistency") is not None:
        text += f", moving that way in {_rnd((block['consistency']) * 100)}% of them"
    if not block.get("consistent"):
        text += " -- not consistent enough to rely on"
    text += "."
    if block.get("forecast_effect_pct") is not None:
        text += (f" The plan for those weeks moved {_rnd(block['forecast_effect_pct'])}%, so the "
                 f"pattern was "
                 f"{'reflected' if block.get('historically_planned_for') else 'not reflected'} "
                 f"in the forecast historically.")
    return text


def _capture(target_phase, phase_block, target_actual, target_forecast, base_actual, base_forecast,
             neighbour_forecast_shares):
    """Did THIS week's forecast anticipate the phase effect the history establishes?

    Judged against the historical effect, not against the actual outcome: the question is whether
    a knowable, repeated pattern was planned for.
    """
    if target_phase == _cal.PHASE_NONE:
        return {"classification": "not_testable",
                "reason": "the target week is not in any holiday phase, so there is nothing to "
                          "capture."}
    if not phase_block or not phase_block.get("testable"):
        return {"classification": "not_testable",
                "reason": (phase_block or {}).get("reason")
                          or "this phase has no measurable history for this queue."}
    if not phase_block.get("consistent"):
        return {"classification": "inconsistent_history",
                "reason": (f"This queue's response to {target_phase.replace('_', ' ')} weeks has "
                           f"not been consistent "
                           f"({_rnd((phase_block.get('consistency') or 0) * 100)}% moved the same "
                           f"way), so the forecast cannot be held to it."),
                "expected_effect_pct": phase_block.get("actual_effect_pct"),
                "consistency": phase_block.get("consistency")}
    if target_forecast is None or not base_forecast:
        return {"classification": "not_testable",
                "reason": "the target forecast or the non-holiday forecast baseline is unavailable."}

    expected_share = (phase_block.get("actual_effect_pct") or 0) / 100.0
    forecast_share = target_forecast / base_forecast - 1.0
    actual_share = (target_actual / base_actual - 1.0
                    if target_actual is not None and base_actual else None)
    out = {"expected_effect_pct": _rnd(expected_share * 100.0),
           "forecast_deviation_pct": _rnd(forecast_share * 100.0),
           "actual_deviation_pct": _rnd(actual_share * 100.0) if actual_share is not None else None,
           "consistency": phase_block.get("consistency")}

    if expected_share == 0:
        out.update({"classification": "not_testable",
                    "reason": "the phase has no measurable effect to capture."})
        return out
    ratio = forecast_share / expected_share
    out["capture_ratio"] = _rnd(ratio)
    if ratio < 0:
        # The forecast moved the opposite way to the established pattern. Before calling that
        # wrong_direction, check whether the plan applied the pattern to a NEIGHBOURING week
        # instead -- that is a timing failure, not a direction failure.
        if any(s is not None and s / expected_share >= CAPTURE_TOLERANCE
               for s in neighbour_forecast_shares):
            out.update({"classification": "delayed",
                        "reason": ("The plan applied this holiday pattern to an adjacent week "
                                   "rather than to this one.")})
        else:
            out.update({"classification": "wrong_direction",
                        "reason": (f"The phase historically moves demand "
                                   f"{_rnd(expected_share * 100)}%, but the plan moved "
                                   f"{_rnd(forecast_share * 100)}% -- the opposite way.")})
    elif ratio < CAPTURE_TOLERANCE:
        out.update({"classification": "under_reacted",
                    "reason": (f"The phase historically moves demand "
                               f"{_rnd(expected_share * 100)}%; the plan moved only "
                               f"{_rnd(forecast_share * 100)}%.")})
    elif ratio <= OVER_CAPTURE:
        out.update({"classification": "captured",
                    "reason": (f"The plan moved {_rnd(forecast_share * 100)}% against the "
                               f"{_rnd(expected_share * 100)}% the phase historically implies.")})
    else:
        out.update({"classification": "over_reacted",
                    "reason": (f"The plan moved {_rnd(forecast_share * 100)}%, well beyond the "
                               f"{_rnd(expected_share * 100)}% the phase historically implies.")})
    return out


def analyse(history, target_week, country, target_actual=None, target_forecast=None,
            row_holiday_count=None):
    """Holiday phase + forecast-capture analysis for one breach.

    `history` is the raw SQL history block. `country` comes from the target row. Degrades honestly:
    if the holiday master is not deployed, or the queue's country cannot be resolved, the block
    reports that rather than concluding "no holiday".
    """
    state = _cal.loaded()
    if not state.get("available"):
        return {"available": False, "reason": state.get("reason"),
                "phase": _cal.PHASE_NONE, "applies": False,
                "note": ("The holiday calendar is not deployed, so holiday effects were NOT "
                         "checked. This is not the same as finding no holiday.")}

    span = _cal.holiday_span(country, target_week, span=SPAN_WEEKS)
    if not span.get("available"):
        return {"available": False, "reason": span.get("reason"),
                "phase": _cal.PHASE_NONE, "applies": False}

    rows = _rows(history, target_week)
    cache = {}
    historical = _historical_phase_effect(rows, country, cache)
    phase = span.get("phase")
    phase_block = ((historical.get("phases") or {}).get(phase)
                   if historical.get("available") else None)

    # forecast deviation in the weeks either side, used only to tell "delayed" from
    # "wrong_direction" in _capture.
    base_forecast = historical.get("baseline_forecast") if historical.get("available") else None
    by_week = {wk: f for wk, f, _ in rows}
    neighbour_shares = []
    if base_forecast and target_week is not None:
        for delta in (-1, 1):
            f = by_week.get(int(target_week) + delta)
            neighbour_shares.append((f / base_forecast - 1.0) if f is not None else None)

    capture = _capture(phase, phase_block, target_actual, target_forecast,
                       historical.get("baseline_actual") if historical.get("available") else None,
                       base_forecast, neighbour_shares)

    # The row flag disagreeing with the calendar is itself a finding -- reuse the existing check.
    context = _cal.holiday_context(country, target_week, row_holiday_count)

    expected_direction = (phase_block or {}).get("direction")
    consistency = (phase_block or {}).get("consistency")

    reading = _reading(phase, span, phase_block, capture, row_holiday_count)
    return {
        "available": True,
        "country_resolved": span.get("countries_resolved"),
        "phase": phase,
        "applies": span.get("applies"),
        "span_weeks": SPAN_WEEKS,
        "names": span.get("names"),
        "families": span.get("families"),
        "holidays_by_offset": span.get("offsets"),
        "holidays_reaching_target_week": span.get("reaching"),
        "row_holiday_count": row_holiday_count,
        "row_flag_disagreement": context.get("row_flag_disagreement"),
        "names_needing_review": context.get("names_needing_review"),
        "historical_response": historical,
        "phase_effect": phase_block,
        "expected_direction": expected_direction,
        "historical_consistency": consistency,
        "forecast_capture": capture,
        "reading": reading,
        "note": ("Holiday direction is measured from this queue's own history, never assumed. A "
                 "target week with Holiday_Count = 0 is still analysed when an adjacent holiday's "
                 "impact window reaches it."),
    }


def _reading(phase, span, phase_block, capture, row_holiday_count):
    """One plain-English paragraph, safe to put in front of an executive."""
    if phase == _cal.PHASE_NONE:
        return ("No holiday falls in this week, and none in the surrounding weeks has an impact "
                "window wide enough to reach it.")
    names = ", ".join(span.get("names") or []) or "a holiday"
    where = {_cal.PHASE_HOLIDAY: "falls in this week",
             _cal.PHASE_PRE: "falls shortly after this week, so this week is the run-up",
             _cal.PHASE_POST: "fell shortly before this week, so this week is the wind-down"}.get(
                 phase, "is nearby")
    text = f"{names} {where}."
    if (row_holiday_count or 0) == 0 and phase != _cal.PHASE_HOLIDAY:
        text += (" The source row flags no holiday for this week, which is correct -- the effect "
                 "reaches in from an adjacent week.")
    if phase_block and phase_block.get("testable"):
        text += " " + phase_block.get("reading", "")
    elif phase_block:
        text += f" {phase_block.get('reason')}"
    cls = (capture or {}).get("classification")
    if cls and cls != "not_testable":
        text += f" Forecast capture: {cls.replace('_', ' ')} -- {capture.get('reason')}"
    return text
