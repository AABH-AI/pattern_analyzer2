# -*- coding: utf-8 -*-
"""
Forecast-response diagnosis -- did the forecast FAIL TO REACT, or was the week unpredictable?

WHY THIS MODULE EXISTS
----------------------
Every metric the engine had before this module described the SIZE of the miss. None of them
answered the question a WFM forecaster actually asks:

    "Was there something I could have seen coming, and did my forecast react to it?"

Without that, "actual exceeded forecast" reads as a forecasting failure every time, which is both
unfair and useless. Two weeks can produce an identical -138% adherence for opposite reasons:

    demand rose after four weeks of visible upward momentum, and the plan was cut anyway
        -> a forecast RESPONSE failure, and an actionable one
    demand rose with no prior signal of any kind
        -> a low-predictability demand event, and nobody's fault

This module separates those. It is deliberately conservative: it will NOT call a miss a forecast
failure unless it can first demonstrate that a signal existed AND that the signal has historically
been worth reacting to (spec sections 7, 8, 20). "Do not blame the forecasting model merely because
actual > forecast."

THE THREE QUESTIONS, IN ORDER
-----------------------------
1. DEMAND SIDE  -- was actual demand unusual, against its own baselines?
2. FORECAST SIDE -- was the forecast unusual, against those same baselines?
3. RESPONSE      -- a signal existed before the week; did the forecast move with it, and enough?

Question 3 is only asked when question 1 or 2 shows something to react to, and its answer is
`not_testable` whenever the inputs are missing rather than a guess.

THE DECOMPOSITION
-----------------
The miss is split into a forecast-side and a demand-side contribution against a robust EXPECTED
demand level, and the split reconciles exactly:

    forecast_side = expected - forecast          (the plan started below/above what was expected)
    demand_side   = actual   - expected          (demand landed above/below what was expected)
    forecast_side + demand_side = actual - forecast = the whole miss

This is the same idea as the ASU decomposition -- an identity, not an attribution model -- and it
is reported with the language the spec requires: "diagnostic contribution", never "probability" or
"cause". It answers "how much of this miss was already baked in before the week started?"

`expected` is a MEDIAN, not a mean, and prefers the same week of prior fiscal years when enough of
them exist. Median because one freak week in the baseline would otherwise move the very quantity
used to judge freak weeks; same-week-of-year because a queue with any seasonality has a different
normal in week 16 than its trailing average implies.

DEPENDENCIES: standard library only.
"""
import statistics as _st

from .common import week_ordinals

# --- baselines. 4/8/13 weeks per spec section 6; 13 matches RCA_HISTORY_CAP and the "usual" the
#     rest of the report already quotes, so the numbers agree across panels. ---
SHORT_WINDOW = 4
MID_WINDOW = 8
RECENT_WINDOW = 13

MIN_PRIOR_YEARS = 2         # same-week seasonal expectation needs at least this many prior years
MIN_BASELINE_WEEKS = 6      # below this there is no defensible baseline at all

# --- what counts as "unusual" for demand or forecast, as a share of the baseline. 0.20 is one
#     band-width either side of a 10% band's worth of tolerance doubled: big enough that ordinary
#     week-to-week noise on a volatile queue does not trip it. ---
UNUSUAL_SHARE = 0.20

# --- response adequacy bands, as a ratio of the forecast movement actually made to the movement
#     the expected level implied. Named so they can be argued with rather than buried. ---
NO_RESPONSE_RATIO = 0.10    # moved less than a tenth of what was needed == did not react
UNDER_RESPONSE_RATIO = 0.50  # reacted, but less than half way
OVER_RESPONSE_RATIO = 1.50   # over-shot by more than half again

# --- momentum: the signal most often available, and the one most often ignored. ---
MOMENTUM_MATERIAL_PCT = 10.0

# --- how repeatable a signal must have been historically before the forecast can be blamed for
#     not reacting to it (spec section 7D / 20). ---
PREDICTABLE_CONSISTENCY = 0.70
PARTIAL_CONSISTENCY = 0.40
MIN_PRECEDENTS = 4          # fewer historical instances than this and repeatability is untested

RESPONSE_CLASSES = ("adequate", "under_response", "over_response", "wrong_direction",
                    "delayed_response", "no_response", "not_testable")
FORECASTABILITY = ("PREDICTABLE", "PARTIALLY_PREDICTABLE", "LOW_PREDICTABILITY", "NOT_TESTABLE")


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


def _pct(part, whole):
    """Percentage change, or None when the denominator cannot carry one."""
    if part is None or not whole:
        return None
    return (part / whole - 1.0) * 100.0


def _rows_before(history, target_week):
    """Chronological rows strictly before the target week, with both figures usable."""
    out = []
    for row in history or []:
        wk = _num((row or {}).get("Fiscal_Week"))
        if wk is None or (target_week is not None and int(wk) >= int(target_week)):
            continue
        out.append((int(wk), _num(row.get("fcst_offered")), _num(row.get("Actual_Offered")), row))
    out.sort(key=lambda t: t[0])
    return out


def _ordinals(rows, target_week):
    """Continuous week counter covering the history AND the target week.

    Every "k weeks before the target" lookup in this module goes through this, so none of them
    breaks at a fiscal-year boundary (the week before 202701 is 202652, not 202700).
    """
    weeks = [w for w, _, _, _ in rows]
    if target_week is not None:
        weeks.append(int(target_week))
    return week_ordinals(weeks)


def _week_of_year(fiscal_week):
    """YYYYWW -> WW. The fiscal year starts at week 1, so the trailing two digits are directly
    comparable across years (same convention as statistical_evidence and fiscal_calendar)."""
    try:
        return int(fiscal_week) % 100
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# 1. demand-side and forecast-side baselines
# ---------------------------------------------------------------------------
def _baselines(rows, target_week):
    """Every baseline both sides are judged against, plus which one is authoritative.

    `expected_demand` is the single number the decomposition uses. Preference order and the reason
    for it are recorded in `expected_basis` so the choice is auditable rather than implicit.
    """
    actuals = [a for _, _, a in ((w, f, a) for w, f, a, _ in rows) if a is not None]
    forecasts = [f for _, f, _, _ in rows if f is not None]
    out = {
        "weeks_available": len(rows),
        "recent_4_week_mean_actual": _rnd(sum(actuals[-SHORT_WINDOW:]) / len(actuals[-SHORT_WINDOW:]))
        if len(actuals) >= SHORT_WINDOW else None,
        "recent_8_week_mean_actual": _rnd(sum(actuals[-MID_WINDOW:]) / len(actuals[-MID_WINDOW:]))
        if len(actuals) >= MID_WINDOW else None,
        "recent_13_week_mean_actual": _rnd(sum(actuals[-RECENT_WINDOW:]) / len(actuals[-RECENT_WINDOW:]))
        if len(actuals) >= RECENT_WINDOW else None,
        "recent_13_week_median_actual": _rnd(_st.median(actuals[-RECENT_WINDOW:]))
        if len(actuals) >= MIN_BASELINE_WEEKS else None,
        "recent_13_week_mean_forecast": _rnd(sum(forecasts[-RECENT_WINDOW:]) / len(forecasts[-RECENT_WINDOW:]))
        if len(forecasts) >= RECENT_WINDOW else None,
    }

    # same week of the fiscal year, prior years only
    wk = _week_of_year(target_week)
    same_week = [(w, f, a) for w, f, a, _ in rows if _week_of_year(w) == wk]
    out["same_week_prior_years"] = [{"fiscal_week": w, "actual": a, "forecast": _rnd(f)}
                                    for w, f, a in same_week]
    out["same_week_years_found"] = len(same_week)
    if same_week:
        sw_actuals = [a for _, _, a in same_week if a is not None]
        sw_forecasts = [f for _, f, _ in same_week if f is not None]
        out["same_week_median_actual"] = _rnd(_st.median(sw_actuals)) if sw_actuals else None
        out["same_week_mean_actual"] = _rnd(sum(sw_actuals) / len(sw_actuals)) if sw_actuals else None
        # dispersion matters: a same-week history of 195/66/106 is a weak seasonal anchor however
        # convenient its mean is, and the report should be able to say so.
        out["same_week_spread_actual"] = (_rnd(max(sw_actuals) - min(sw_actuals))
                                         if len(sw_actuals) > 1 else None)
        out["same_week_stdev_actual"] = (_rnd(_st.stdev(sw_actuals))
                                         if len(sw_actuals) > 1 else None)
        out["same_week_median_forecast"] = (_rnd(_st.median(sw_forecasts))
                                            if sw_forecasts else None)
    else:
        out.update({"same_week_median_actual": None, "same_week_mean_actual": None,
                    "same_week_spread_actual": None, "same_week_stdev_actual": None,
                    "same_week_median_forecast": None})

    if out["same_week_years_found"] >= MIN_PRIOR_YEARS and out["same_week_median_actual"] is not None:
        out["expected_demand"] = out["same_week_median_actual"]
        out["expected_basis"] = (f"median demand in fiscal week {wk} across "
                                 f"{out['same_week_years_found']} prior year(s)")
        out["expected_basis_key"] = "same_week_median"
    elif out["recent_13_week_median_actual"] is not None:
        out["expected_demand"] = out["recent_13_week_median_actual"]
        out["expected_basis"] = (f"median demand over the last {RECENT_WINDOW} weeks "
                                 f"(fewer than {MIN_PRIOR_YEARS} prior years available for "
                                 f"fiscal week {wk})")
        out["expected_basis_key"] = "recent_median"
    else:
        out["expected_demand"] = None
        out["expected_basis"] = "not enough history to establish an expected demand level"
        out["expected_basis_key"] = None
    return out


def _side_verdict(value, baseline, label):
    """Was one side of the equation unusual against a baseline, and by how much."""
    if value is None or not baseline:
        return {"testable": False, "reason": f"{label} or its baseline is unavailable"}
    share = value / baseline - 1.0
    return {"testable": True, "value": _rnd(value), "baseline": _rnd(baseline),
            "difference": _rnd(value - baseline), "difference_pct": _rnd(share * 100.0),
            "unusual": abs(share) >= UNUSUAL_SHARE,
            "direction": "above" if share > 0 else ("below" if share < 0 else "level")}


# ---------------------------------------------------------------------------
# 2. the movement test -- spec section 8
# ---------------------------------------------------------------------------
def _movement(rows, target_week, target_actual, target_forecast, lookbacks=(1, 2, 4),
              ordinals=None):
    """Actual(t-k) -> Actual(t) against Forecast(t-k) -> Forecast(t).

    The single most diagnostic comparison in the whole module: demand and plan moving in OPPOSITE
    directions is the signature of a forecast that did not react. Reported for several lookbacks
    because a one-week comparison on a volatile queue can be noise.
    """
    ordinals = ordinals or _ordinals(rows, target_week)
    by_ordinal, week_at = {}, {}
    for w, f, a, _ in rows:
        o = ordinals.get(w)
        if o is not None:
            by_ordinal[o] = (f, a)
            week_at[o] = w
    target_ordinal = ordinals.get(int(target_week)) if target_week is not None else None
    out = []
    for k in lookbacks:
        prev = by_ordinal.get(target_ordinal - k) if target_ordinal is not None else None
        source_week = week_at.get(target_ordinal - k) if target_ordinal is not None else None
        if not prev or prev[0] is None or prev[1] is None:
            out.append({"lookback_weeks": k, "testable": False,
                        "reason": f"the week {k} week(s) before the target is not available "
                                  f"with both a forecast and an actual"})
            continue
        pf, pa = prev
        actual_change = (target_actual - pa) if target_actual is not None else None
        forecast_change = (target_forecast - pf) if target_forecast is not None else None
        if actual_change is None or forecast_change is None:
            out.append({"lookback_weeks": k, "testable": False,
                        "reason": "the target week is missing a forecast or an actual"})
            continue
        opposed = (actual_change > 0 > forecast_change) or (actual_change < 0 < forecast_change)
        out.append({
            "lookback_weeks": k, "testable": True,
            "from_fiscal_week": source_week,
            "actual_from": pa, "actual_to": target_actual,
            "actual_change": _rnd(actual_change), "actual_change_pct": _rnd(_pct(target_actual, pa)),
            "forecast_from": _rnd(pf), "forecast_to": _rnd(target_forecast),
            "forecast_change": _rnd(forecast_change),
            "forecast_change_pct": _rnd(_pct(target_forecast, pf)),
            "actual_direction": "up" if actual_change > 0 else ("down" if actual_change < 0 else "flat"),
            "forecast_direction": "up" if forecast_change > 0 else ("down" if forecast_change < 0 else "flat"),
            "directions_opposed": opposed,
        })
    return out


# ---------------------------------------------------------------------------
# 3. signals that existed BEFORE the target week -- spec section 7A
# ---------------------------------------------------------------------------
def _momentum_signal(rows):
    """Was demand already moving before the target week, on its own recent history."""
    actuals = [a for _, _, a, _ in rows if a is not None]
    if len(actuals) < SHORT_WINDOW + MID_WINDOW:
        return {"signal": "demand_momentum", "detected": False, "testable": False,
                "reason": f"needs {SHORT_WINDOW + MID_WINDOW} weeks of actuals, "
                          f"has {len(actuals)}"}
    recent = actuals[-SHORT_WINDOW:]
    prior = actuals[-(SHORT_WINDOW + MID_WINDOW):-SHORT_WINDOW]
    recent_mean = sum(recent) / len(recent)
    prior_mean = sum(prior) / len(prior)
    change_pct = _pct(recent_mean, prior_mean)
    detected = change_pct is not None and abs(change_pct) >= MOMENTUM_MATERIAL_PCT
    return {"signal": "demand_momentum", "detected": bool(detected), "testable": True,
            "recent_weeks": SHORT_WINDOW, "prior_weeks": MID_WINDOW,
            "recent_mean_actual": _rnd(recent_mean), "prior_mean_actual": _rnd(prior_mean),
            "change_pct": _rnd(change_pct),
            "direction": None if change_pct is None else ("up" if change_pct > 0 else "down"),
            "visible_from_fiscal_week": rows[-1][0] if rows else None,
            "reading": (f"Demand in the {SHORT_WINDOW} weeks before the target week averaged "
                        f"{_rnd(recent_mean)} against {_rnd(prior_mean)} in the "
                        f"{MID_WINDOW} weeks before that ({_rnd(change_pct)}%)."
                        if change_pct is not None else "Momentum could not be measured.")}


def _seasonal_signal(baselines, target_week):
    """Does this week of the fiscal year have a different normal from the queue's usual?

    Not "is the target unusual" -- that is the demand-side test. This asks whether a forecaster
    had a SEASONAL reason to plan this week differently, which is knowable in advance.
    """
    wk = _week_of_year(target_week)
    same = baselines.get("same_week_median_actual")
    recent = baselines.get("recent_13_week_median_actual")
    if same is None or not recent:
        return {"signal": "same_week_seasonal_pattern", "detected": False, "testable": False,
                "reason": (f"needs at least {MIN_PRIOR_YEARS} prior years for fiscal week {wk} "
                           f"and a recent baseline")}
    share = same / recent - 1.0
    spread = baselines.get("same_week_spread_actual")
    return {"signal": "same_week_seasonal_pattern", "detected": abs(share) >= UNUSUAL_SHARE,
            "testable": True, "week_of_fiscal_year": wk,
            "same_week_median_actual": same, "recent_median_actual": recent,
            "difference_pct": _rnd(share * 100.0),
            "years_found": baselines.get("same_week_years_found"),
            "spread_across_years": spread,
            "direction": "up" if share > 0 else ("down" if share < 0 else "flat"),
            "reading": (f"Fiscal week {wk} has historically run {_rnd(share * 100.0)}% against this "
                        f"queue's recent median, across {baselines.get('same_week_years_found')} "
                        f"prior year(s)"
                        + (f"; those years span {spread} contacts, so the seasonal anchor is "
                           f"itself wide." if spread else "."))}


def _driver_signals(lag_result, history, target_week):
    """Did any driver with a usable LEADING relationship actually MOVE before the target week?

    A leading relationship is necessary but not sufficient: the driver has to have moved. This is
    the join between lag_analysis (is there a relationship?) and this module (did it fire?).
    """
    out = []
    if not (lag_result or {}).get("available"):
        return out
    by_week = {}
    for row in history or []:
        wk = _num((row or {}).get("Fiscal_Week"))
        if wk is not None:
            by_week[int(wk)] = row
    for entry in lag_result.get("drivers") or []:
        if not entry.get("usable_as_evidence"):
            continue
        lag = entry.get("best_lag_weeks")
        if lag is None or target_week is None:
            continue
        driver = entry["driver"]
        signal_week = int(target_week) - int(lag)
        now_row = by_week.get(signal_week)
        prev_row = by_week.get(signal_week - 1)
        now = _num((now_row or {}).get(driver))
        prev = _num((prev_row or {}).get(driver))
        if now is None or prev is None:
            out.append({"signal": f"driver_movement:{driver}", "detected": False,
                        "testable": False, "driver": driver, "lag_weeks": lag,
                        "reason": (f"{driver} has no usable value at fiscal week {signal_week} "
                                   f"and/or the week before, so its movement cannot be measured")})
            continue
        change_pct = _pct(now, prev)
        moved = change_pct is not None and abs(change_pct) >= UNUSUAL_SHARE * 100.0
        expected_direction = entry.get("direction")
        implies_up = ((change_pct or 0) > 0) == (expected_direction == "positive")
        out.append({
            "signal": f"driver_movement:{driver}", "driver": driver, "lag_weeks": lag,
            "detected": bool(moved), "testable": True,
            "relationship_strength": entry.get("relationship_strength"),
            "relationship_type": entry.get("relationship_type"),
            "stability": entry.get("stability"),
            "signal_week": signal_week, "value_at_signal_week": now, "value_week_before": prev,
            "change_pct": _rnd(change_pct),
            "implies_demand": "up" if implies_up else "down",
            "visible_from_fiscal_week": signal_week,
            "reading": (f"{entry.get('subject', driver)} moved {_rnd(change_pct)}% at fiscal week "
                        f"{signal_week}, {lag} week(s) before the target week, and this queue's "
                        f"history shows a {entry.get('stability')} relationship at that lag."),
        })
    return out


def _holiday_signal(holiday_result):
    """A calendar signal is the most forecastable kind there is -- the date is known years ahead.

    Consumes the holiday_response block rather than recomputing anything, so there is one source
    of truth for the calendar.
    """
    if not (holiday_result or {}).get("available"):
        return {"signal": "holiday_transition", "detected": False, "testable": False,
                "reason": (holiday_result or {}).get("reason")
                          or "holiday context is unavailable"}
    phase = holiday_result.get("phase")
    if not holiday_result.get("applies"):
        return {"signal": "holiday_transition", "detected": False, "testable": True,
                "phase": phase, "reading": "No holiday falls in this week or reaches it from an "
                                           "adjacent week."}
    return {"signal": "holiday_transition", "detected": True, "testable": True,
            "phase": phase, "names": holiday_result.get("names"),
            "expected_direction": holiday_result.get("expected_direction"),
            "historical_consistency": holiday_result.get("historical_consistency"),
            "visible_from_fiscal_week": "known in advance",
            "reading": holiday_result.get("reading")}


# ---------------------------------------------------------------------------
# 4. repeatability -- spec section 7D. Was this signal historically worth reacting to?
# ---------------------------------------------------------------------------
def _momentum_repeatability(rows):
    """When this queue's demand had momentum before, did the next week actually follow it?

    Counts historical instances where momentum was material and checks whether the following week
    moved the same way against the recent mean. This is what makes it legitimate to say "the
    forecast should have reacted": not that momentum existed, but that momentum has historically
    meant something for THIS queue.
    """
    actuals = [(w, a) for w, _, a, _ in rows if a is not None]
    need = SHORT_WINDOW + MID_WINDOW + 1
    if len(actuals) < need + MIN_PRECEDENTS:
        return {"testable": False, "precedents": 0,
                "reason": f"needs {need + MIN_PRECEDENTS} weeks of actuals, has {len(actuals)}"}
    followed = 0
    precedents = 0
    for i in range(SHORT_WINDOW + MID_WINDOW, len(actuals)):
        recent = [a for _, a in actuals[i - SHORT_WINDOW:i]]
        prior = [a for _, a in actuals[i - SHORT_WINDOW - MID_WINDOW:i - SHORT_WINDOW]]
        if not recent or not prior:
            continue
        recent_mean = sum(recent) / len(recent)
        prior_mean = sum(prior) / len(prior)
        change_pct = _pct(recent_mean, prior_mean)
        if change_pct is None or abs(change_pct) < MOMENTUM_MATERIAL_PCT:
            continue
        precedents += 1
        next_actual = actuals[i][1]
        if (change_pct > 0 and next_actual > recent_mean) or \
           (change_pct < 0 and next_actual < recent_mean):
            followed += 1
    if precedents < MIN_PRECEDENTS:
        return {"testable": False, "precedents": precedents,
                "reason": f"only {precedents} historical instances of material momentum "
                          f"({MIN_PRECEDENTS} required to judge repeatability)"}
    consistency = followed / precedents
    return {"testable": True, "precedents": precedents, "followed_through": followed,
            "consistency": _rnd(consistency),
            "reading": (f"In {followed} of {precedents} earlier weeks where this queue had material "
                        f"momentum, the next week continued in the same direction "
                        f"({_rnd(consistency * 100)}%).")}


def _forecastability(signals, momentum_repeat, lag_result):
    """PREDICTABLE / PARTIALLY_PREDICTABLE / LOW_PREDICTABILITY -- spec section 20.

    The gate that stops the engine blaming a forecaster for missing an unforecastable week. A
    signal only counts towards PREDICTABLE if its historical behaviour was repeatable: a calendar
    signal with a consistent historical response, or a driver relationship that survived the
    stability split, or momentum that has historically followed through.
    """
    detected = [s for s in signals if s.get("detected")]
    if not detected:
        untestable = [s for s in signals if not s.get("testable")]
        if len(untestable) == len(signals) and signals:
            return {"classification": "NOT_TESTABLE",
                    "reason": "no signal could be tested with the available data",
                    "signals_detected": [], "basis": []}
        return {"classification": "LOW_PREDICTABILITY",
                "reason": ("No leading signal was present before this week, so the demand movement "
                           "was not foreseeable from this queue's own data."),
                "signals_detected": [], "basis": []}

    basis = []
    strong = False
    partial = False
    for s in detected:
        name = s.get("signal")
        if name == "demand_momentum":
            if momentum_repeat.get("testable"):
                c = momentum_repeat.get("consistency") or 0
                if c >= PREDICTABLE_CONSISTENCY:
                    strong = True
                    basis.append(f"{name}: historically followed through {_rnd(c * 100)}% of the time")
                elif c >= PARTIAL_CONSISTENCY:
                    partial = True
                    basis.append(f"{name}: followed through only {_rnd(c * 100)}% of the time")
                else:
                    basis.append(f"{name}: rarely followed through ({_rnd(c * 100)}%), so it is a "
                                 f"weak basis for expecting this week to move")
            else:
                partial = True
                basis.append(f"{name}: present, but its historical repeatability is untested "
                             f"({momentum_repeat.get('reason')})")
        elif str(name).startswith("driver_movement:"):
            if s.get("stability") == "stable":
                strong = True
                basis.append(f"{name}: stable relationship at a {s.get('lag_weeks')}-week lead")
            else:
                partial = True
                basis.append(f"{name}: relationship is {s.get('stability')} at a "
                             f"{s.get('lag_weeks')}-week lead")
        elif name == "holiday_transition":
            consistency = s.get("historical_consistency")
            if isinstance(consistency, (int, float)) and consistency >= PREDICTABLE_CONSISTENCY:
                strong = True
                basis.append(f"{name}: the calendar date is known in advance and this queue's "
                             f"historical response has been consistent")
            else:
                partial = True
                basis.append(f"{name}: the calendar date is known in advance, but this queue's "
                             f"historical response to it has not been consistent")
        elif name == "same_week_seasonal_pattern":
            spread = s.get("spread_across_years")
            years = s.get("years_found") or 0
            if years >= 3 and not spread:
                strong = True
                basis.append(f"{name}: a repeated seasonal level across {years} years")
            else:
                partial = True
                basis.append(f"{name}: a seasonal level exists across {years} year(s), but the "
                             f"years themselves vary widely, so the level is only indicative")
        else:
            partial = True
            basis.append(f"{name}: detected, repeatability not assessed")

    if strong:
        classification = "PREDICTABLE"
        reason = ("At least one leading signal was present before the week AND has behaved "
                  "repeatably for this queue, so the movement was foreseeable.")
    elif partial:
        classification = "PARTIALLY_PREDICTABLE"
        reason = ("A leading signal was present, but its historical timing or magnitude has not "
                  "been consistent for this queue, so only part of the movement was foreseeable.")
    else:
        classification = "LOW_PREDICTABILITY"
        reason = ("Signals were present but none has behaved repeatably for this queue, so the "
                  "movement was not reliably foreseeable.")
    return {"classification": classification, "reason": reason,
            "signals_detected": [s.get("signal") for s in detected], "basis": basis}


# ---------------------------------------------------------------------------
# 5. response adequacy -- spec section 7B/7C
# ---------------------------------------------------------------------------
def _adequacy(rows, target_week, target_forecast, expected_demand, signals, ordinals=None):
    """Did the forecast move, in the right direction, and by enough?

    Measured against what the EXPECTED level implied the forecast needed to do, not against the
    actual -- judging the plan against an outcome nobody could know is hindsight, not diagnosis.

        implied_change  = expected_demand - forecast(t-1)
        actual_change   = forecast(t)     - forecast(t-1)
        response_ratio  = actual_change / implied_change
    """
    detected = [s for s in signals if s.get("detected")]
    if not detected:
        return {"classification": "not_testable",
                "reason": ("No leading signal was detected before this week, so there was nothing "
                           "for the forecast to respond to. A miss here is not a response "
                           "failure.")}
    ordinals = ordinals or _ordinals(rows, target_week)
    by_ordinal = {ordinals.get(w): (f, a) for w, f, a, _ in rows if ordinals.get(w) is not None}
    target_ordinal = ordinals.get(int(target_week)) if target_week is not None else None
    prev = by_ordinal.get(target_ordinal - 1) if target_ordinal is not None else None
    if not prev or prev[0] is None or target_forecast is None:
        return {"classification": "not_testable",
                "reason": "the prior week's forecast or this week's forecast is unavailable"}
    if expected_demand is None:
        return {"classification": "not_testable",
                "reason": "no expected demand level could be established, so the size of the "
                          "response required cannot be judged"}
    prior_forecast = prev[0]
    implied = expected_demand - prior_forecast
    made = target_forecast - prior_forecast
    out = {"prior_week_forecast": _rnd(prior_forecast), "target_forecast": _rnd(target_forecast),
           "expected_demand": _rnd(expected_demand),
           "implied_change": _rnd(implied), "forecast_change_made": _rnd(made),
           "signals_considered": [s.get("signal") for s in detected]}

    # A negligible implied change means the prior plan was already at the expected level. That is
    # only "adequate" if the plan STAYED there -- a plan that moved a long way away from the
    # expected level when nothing asked it to has still failed, and calling that adequate was a
    # real defect caught by the wrong-direction regression case.
    if abs(implied) < max(1.0, abs(prior_forecast) * NO_RESPONSE_RATIO * 0.1):
        drift_away = target_forecast - expected_demand
        material_drift = abs(drift_away) > max(1.0, abs(expected_demand) * UNUSUAL_SHARE * 0.5)
        if not material_drift:
            out.update({"classification": "adequate", "response_ratio": None,
                        "reason": ("The prior forecast was already at the expected demand level "
                                   "and stayed there, so no material change was required.")})
        else:
            out.update({"classification": "wrong_direction", "response_ratio": None,
                        "reason": (f"No change was required -- the prior plan already sat at the "
                                   f"expected level of {_rnd(expected_demand)} -- but the plan "
                                   f"moved {_rnd(made)} contacts to {_rnd(target_forecast)}, away "
                                   f"from it.")})
        return out
    ratio = made / implied
    out["response_ratio"] = _rnd(ratio)
    if ratio < 0:
        out.update({"classification": "wrong_direction",
                    "reason": (f"The expected level implied moving the forecast "
                               f"{_rnd(implied)} contacts, but it moved {_rnd(made)} -- the "
                               f"opposite way.")})
    elif ratio < NO_RESPONSE_RATIO:
        out.update({"classification": "no_response",
                    "reason": (f"The expected level implied moving the forecast "
                               f"{_rnd(implied)} contacts; it moved {_rnd(made)}, effectively "
                               f"not reacting.")})
    elif ratio < UNDER_RESPONSE_RATIO:
        out.update({"classification": "under_response",
                    "reason": (f"The forecast moved {_rnd(made)} contacts against the "
                               f"{_rnd(implied)} the expected level implied -- it reacted, but "
                               f"by well under half of what was needed.")})
    elif ratio <= OVER_RESPONSE_RATIO:
        out.update({"classification": "adequate",
                    "reason": (f"The forecast moved {_rnd(made)} contacts against the "
                               f"{_rnd(implied)} implied, which is a proportionate reaction.")})
    else:
        out.update({"classification": "over_response",
                    "reason": (f"The forecast moved {_rnd(made)} contacts against the "
                               f"{_rnd(implied)} implied -- it over-reacted.")})

    # Timing: a forecast that moved the right way only in the target week, when the signal had
    # been visible for two or more weeks, reacted late. Reported alongside the magnitude verdict
    # rather than replacing it, so both facts survive.
    timing = _timing(rows, target_week, target_forecast, detected, made, ordinals)
    out.update(timing)
    if timing.get("reacted_late") and out["classification"] in ("adequate", "under_response"):
        out["classification"] = "delayed_response"
        out["reason"] = (out["reason"] + " The signal had already been visible for "
                         f"{timing.get('weeks_signal_visible')} week(s) before the forecast "
                         f"moved, so the reaction was late.")
    return out


def _timing(rows, target_week, target_forecast, detected, made, ordinals=None):
    """How long the earliest detected signal had been visible before the forecast moved."""
    ordinals = ordinals or _ordinals(rows, target_week)
    weeks = []
    for s in detected:
        vis = s.get("visible_from_fiscal_week")
        if isinstance(vis, int) and ordinals.get(vis) is not None:
            weeks.append(ordinals[vis])
    target_ordinal = ordinals.get(int(target_week)) if target_week is not None else None
    if not weeks or target_ordinal is None:
        return {"reacted_late": False, "weeks_signal_visible": None,
                "timing_note": "signal visibility date is not datable, so timing is not judged"}
    earliest = min(weeks)
    visible_for = target_ordinal - earliest
    if visible_for < 2 or made == 0:
        return {"reacted_late": False, "weeks_signal_visible": visible_for,
                "timing_note": "the signal was not visible long enough before the week to call "
                               "the reaction late"}
    # Did the forecast move in the same direction in any week between the signal and the target?
    by_ordinal = {ordinals.get(w): f for w, f, _, _ in rows if ordinals.get(w) is not None}
    moved_earlier = False
    for o in range(earliest + 1, target_ordinal):
        f_now, f_prev = by_ordinal.get(o), by_ordinal.get(o - 1)
        if f_now is None or f_prev is None:
            continue
        step = f_now - f_prev
        if step != 0 and (step > 0) == (made > 0):
            moved_earlier = True
            break
    return {"reacted_late": not moved_earlier, "weeks_signal_visible": visible_for,
            "timing_note": ("the forecast had already begun moving this way before the target week"
                            if moved_earlier else
                            "the forecast did not move this way in any week between the signal "
                            "and the target week")}


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------
def analyse(history, target_week, target_actual, target_forecast,
            lag_result=None, holiday_result=None):
    """The full forecast-response diagnosis for one breach.

    `history` is the raw SQL history block; `lag_result` is `lag_analysis.analyse(...)` and
    `holiday_result` is `holiday_response.analyse(...)`. Both are optional -- the module degrades
    to what it can measure and says which signals it could not test.
    """
    rows = _rows_before(history, target_week)
    if len(rows) < MIN_BASELINE_WEEKS:
        return {"available": False,
                "reason": (f"only {len(rows)} usable history weeks before the target week "
                           f"({MIN_BASELINE_WEEKS} required to establish any baseline)"),
                "weeks_available": len(rows)}

    baselines = _baselines(rows, target_week)
    expected = baselines.get("expected_demand")

    demand_side = {
        "question": "Was actual demand unusual for this queue and this week of the year?",
        "vs_expected": _side_verdict(target_actual, expected, "actual"),
        "vs_recent_13_week_median": _side_verdict(
            target_actual, baselines.get("recent_13_week_median_actual"), "actual"),
        "vs_recent_4_week_mean": _side_verdict(
            target_actual, baselines.get("recent_4_week_mean_actual"), "actual"),
        "vs_same_week_prior_years": _side_verdict(
            target_actual, baselines.get("same_week_median_actual"), "actual"),
    }
    forecast_side = {
        "question": "Was the forecast itself unusual against the same baselines?",
        "vs_expected": _side_verdict(target_forecast, expected, "forecast"),
        "vs_recent_13_week_mean_forecast": _side_verdict(
            target_forecast, baselines.get("recent_13_week_mean_forecast"), "forecast"),
        "vs_same_week_prior_year_forecasts": _side_verdict(
            target_forecast, baselines.get("same_week_median_forecast"), "forecast"),
        "vs_same_week_prior_year_demand": _side_verdict(
            target_forecast, baselines.get("same_week_median_actual"), "forecast"),
    }

    # the exactly-reconciling split
    if expected is None or target_actual is None or target_forecast is None:
        decomposition = {"available": False,
                         "reason": ("the miss cannot be split without an expected demand level "
                                    "and both a forecast and an actual")}
    else:
        forecast_contribution = expected - target_forecast
        demand_contribution = target_actual - expected
        total = target_actual - target_forecast
        gross = abs(forecast_contribution) + abs(demand_contribution)
        decomposition = {
            "available": True,
            "expected_demand": _rnd(expected),
            "expected_basis": baselines.get("expected_basis"),
            "total_miss": _rnd(total),
            "forecast_side_contribution": _rnd(forecast_contribution),
            "demand_side_contribution": _rnd(demand_contribution),
            "forecast_side_share": _rnd(abs(forecast_contribution) / gross, 3) if gross else None,
            "demand_side_share": _rnd(abs(demand_contribution) / gross, 3) if gross else None,
            "reconciles": abs((forecast_contribution + demand_contribution) - total) < 0.01,
            "leading_side": ("forecast" if abs(forecast_contribution) > abs(demand_contribution)
                             else ("demand" if abs(demand_contribution) > abs(forecast_contribution)
                                   else "balanced")),
            "note": ("A diagnostic contribution, not a causal probability: it states how much of "
                     "the miss was already present in the plan before the week began, and how "
                     "much came from demand landing away from its expected level."),
        }
        decomposition["reading"] = (
            f"Against an expected {_rnd(expected)} contacts ({baselines.get('expected_basis')}), "
            f"the plan sat {_rnd(abs(forecast_contribution))} contacts "
            f"{'below' if forecast_contribution > 0 else 'above'} expectation and demand landed "
            f"{_rnd(abs(demand_contribution))} contacts "
            f"{'above' if demand_contribution > 0 else 'below'} it.")

    ordinals = _ordinals(rows, target_week)
    movement = _movement(rows, target_week, target_actual, target_forecast, ordinals=ordinals)
    momentum = _momentum_signal(rows)
    seasonal = _seasonal_signal(baselines, target_week)
    holiday_sig = _holiday_signal(holiday_result)
    signals = [momentum, seasonal, holiday_sig] + _driver_signals(lag_result, history, target_week)

    momentum_repeat = _momentum_repeatability(rows)
    forecastability = _forecastability(signals, momentum_repeat, lag_result)
    adequacy = _adequacy(rows, target_week, target_forecast, expected, signals, ordinals)

    opposed = [m for m in movement if m.get("testable") and m.get("directions_opposed")]

    return {
        "available": True,
        "weeks_available": len(rows),
        "baselines": baselines,
        "demand_side": demand_side,
        "forecast_side": forecast_side,
        "miss_decomposition": decomposition,
        "movement_test": movement,
        "directions_opposed_at": [m["lookback_weeks"] for m in opposed],
        "signals": signals,
        "momentum_repeatability": momentum_repeat,
        "forecastability": forecastability,
        "response": adequacy,
        "note": ("Response adequacy is judged against what the expected demand level implied the "
                 "forecast needed to do, never against the actual outcome. A miss is only a "
                 "response failure where a signal existed AND that signal has behaved repeatably "
                 "for this queue."),
    }
