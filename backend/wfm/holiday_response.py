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

from . import holiday_events
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

# Section 10 repeatability bands.
#
# The middle bar is deliberately CONSISTENT_SHARE (0.70) -- the bar this module already uses to
# call a phase effect "consistent". Introducing a second, disagreeing figure for the same idea is
# the mistake the criticality work avoided by reusing the 50-contact materiality floor.
HIGHLY_REPEATABLE_SHARE = 0.85      # clearly above the existing "consistent" bar
LEANS_SHARE = 0.50                  # at or below this the direction is no better than a coin flip
# A rebound is "large" at twice the materiality share. Derived from MATERIAL_SHARE so there is one
# scale in this module, not two.
LARGE_CHANGE_SHARE = MATERIAL_SHARE * 2
# How dispersed the magnitudes may be before quoting a single uplift figure misleads: the range may
# be at most twice the typical size. VERSIONED CONFIGURATION -- a judgement, not a measurement, and
# it would benefit from client confirmation the way CAPTURE_TOLERANCE would.
MAGNITUDE_SPREAD_LIMIT = 2.0
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
            "baseline_weeks": len(base_actuals), "phases": phases,
            # FIX 3: the counterpart label to spec_engine._holiday_effect_for. Two holiday effects
            # on one card with different values is only confusing while neither says what it counted.
            "basis": "weeks the CALENDAR marks as each phase, against this queue's non-holiday weeks",
            "measure": "median",
            "differs_from": ("spec_engine._holiday_effect_for, which uses the MEAN over every week "
                             "with Holiday_Count > 0 -- a wider set, so its percentage is expected "
                             "to differ from this one")}


def _phase_name(country, week, cache):
    """Just the phase. `_phase_of` returns (phase, span_dict); comparing that tuple to a phase
    constant is silently always False, which is how the first version of phase_transitions found
    zero transitions on a queue that plainly has one."""
    got = _phase_of(country, week, cache)
    return got[0] if isinstance(got, tuple) else got


def phase_transitions(rows, country, cache, target_week=None, target_actual=None):
    """Section 9 measurement A: the WEEK-ON-WEEK change across a holiday boundary.

    This is a DIFFERENT QUANTITY from `phase_effect`, and the spec is emphatic about not conflating
    them:

        A  holiday week -> post-holiday week change      FW15 96 -> FW16 152  = +58.3%
        B  post-holiday level vs the non-holiday baseline  (what `phase_effect` measures)

    A is a transition between two specific weeks. B is a standing level. The banned sentence is
    "+58.3% holiday effect", because a holiday that SUPPRESSES demand can still be followed by a
    week that jumps 58% -- the jump is the recovery from the trough, not the holiday's effect. The
    required phrasing is "58.3% post-holiday rebound from FW15 to FW16", so the wording is built
    here rather than left to a caller.

    Returns the target week's transition (when it has one) and every comparable transition in
    history, which is what makes a rebound judgeable as repeatable or not.
    """
    by_week = {int(w): (f, a) for w, f, a in rows if a is not None}
    weeks = sorted(by_week)
    if len(weeks) < 2:
        return {"available": False, "reason": "fewer than two scoreable weeks in history"}

    ordered = {w: i for i, w in enumerate(weeks)}
    hist = []
    for w in weeks:
        i = ordered[w]
        if i == 0:
            continue
        prev = weeks[i - 1]
        # Only a HOLIDAY week followed by a POST-HOLIDAY week is a rebound transition. Any other
        # pair is an ordinary week-on-week change and must not be labelled a rebound.
        if _phase_name(country, prev, cache) != _cal.PHASE_HOLIDAY:
            continue
        if _phase_name(country, w, cache) != _cal.PHASE_POST:
            continue
        a_prev, a_now = by_week[prev][1], by_week[w][1]
        if not a_prev:
            continue
        hist.append({"from_week": prev, "to_week": w,
                     "from_actual": _rnd(a_prev), "to_actual": _rnd(a_now),
                     "change_pct": _rnd((a_now / a_prev - 1.0) * 100.0)})

    target = None
    if target_week is not None and target_actual is not None:
        tw = int(target_week)
        # `rows` stop BEFORE the target week (that is what _rows does, so history can never leak
        # the answer), so the preceding week is simply the last row -- and the target's own actual
        # has to be supplied rather than looked up.
        prior = [w for w in weeks if w < tw]
        if prior:
            prev = prior[-1]
            if (_phase_name(country, prev, cache) == _cal.PHASE_HOLIDAY
                    and _phase_name(country, tw, cache) == _cal.PHASE_POST):
                a_prev, a_now = by_week[prev][1], _num(target_actual)
                if a_prev and a_now is not None:
                    pct = (a_now / a_prev - 1.0) * 100.0
                    target = {
                        "from_week": prev, "to_week": tw,
                        "from_actual": _rnd(a_prev), "to_actual": _rnd(a_now),
                        "change_pct": _rnd(pct),
                        "direction": "rebound" if pct > 0 else ("further_decline" if pct < 0 else "flat"),
                        # The one sentence the spec dictates the shape of.
                        "reading": (f"{_rnd(abs(pct))}% post-holiday "
                                    f"{'rebound' if pct > 0 else 'further decline'} from FW{prev} "
                                    f"({_rnd(a_prev)} contacts) to FW{tw} ({_rnd(a_now)})."),
                    }

    changes = [h["change_pct"] for h in hist if h.get("change_pct") is not None]
    summary = {}
    if changes:
        ups = sum(1 for c in changes if c > 0)
        summary = {
            "instances": len(changes),
            "median_change_pct": _rnd(_st.median(changes)),
            "mean_change_pct": _rnd(sum(changes) / len(changes)),
            "min_change_pct": _rnd(min(changes)), "max_change_pct": _rnd(max(changes)),
            "positive_share": _rnd(ups / len(changes), 3),
            "spread_pct": _rnd(max(changes) - min(changes)),
        }
    return {
        "available": True,
        "target_transition": target,
        "history": hist,
        "summary": summary,
        # Section 10. Classified from the transitions this function has just collected, so the band
        # and the figures behind it can never disagree.
        "repeatability": repeatability(changes, "post-holiday rebound"),
        "measures": ("week-on-week change across a holiday boundary (section 9 measurement A). "
                     "NOT the same quantity as phase_effect, which is the standing level against "
                     "this queue's non-holiday baseline (measurement B)."),
        "wording_rule": ("Describe this as a post-holiday rebound between two named weeks. It must "
                         "never be called a 'holiday effect': a holiday that suppresses demand is "
                         "routinely followed by a large positive change, and that change is the "
                         "recovery, not the holiday's effect."),
    }


def repeatability(changes, label="post-holiday rebound"):
    """Section 10. Classify a set of historical responses into the five named bands.

    `changes` is a list of percentage changes -- the spec's own example is [+29, -47, +89, +58].

    TWO PROPERTIES, NOT ONE. Section 10 lists variability alongside consistency, and they answer
    different questions:

        direction consistency  does it reliably move the SAME WAY?
        magnitude spread       is the SIZE predictable enough to quote a figure?

    A set can be reliable in direction and useless in magnitude, which is exactly the spec's
    example: 3 of 4 positive, but ranging -47% to +89%. The required reading there is "a directional
    forecasting signal, not a deterministic fixed uplift" -- so the band is decided by direction and
    the magnitude verdict rides beside it, rather than being averaged into a single score that hides
    which of the two failed.

    Returns the band, every figure section 10 asks for, and a reading that never says a holiday
    "causes" anything.
    """
    vals = [c for c in (changes or []) if isinstance(c, (int, float))]
    n = len(vals)
    if n < MIN_PHASE_INSTANCES:
        return {"band": "NOT ENOUGH DATA", "instances": n,
                "reason": (f"only {n} comparable instance(s) in this queue's history; "
                           f"{MIN_PHASE_INSTANCES} are needed before a pattern can be called "
                           f"repeatable or not"),
                "reading": (f"There are too few past instances to say whether this queue's "
                            f"{label} repeats. That is a limit of the history, not evidence "
                            f"that no pattern exists.")}

    med = _st.median(vals)
    mean = sum(vals) / n
    lo, hi = min(vals), max(vals)
    spread = hi - lo
    ups = sum(1 for v in vals if v > 0)
    positive_share = ups / n
    # Consistency is measured against the MEDIAN's direction, not against zero, so a queue whose
    # rebounds are reliably negative scores as consistent rather than as inconsistent.
    same_way = sum(1 for v in vals if (v > 0) == (med > 0)) if med != 0 else 0
    consistency = same_way / n
    large = sum(1 for v in vals if abs(v) >= LARGE_CHANGE_SHARE * 100.0) / n
    spread_ratio = (spread / abs(med)) if med else None
    magnitude_predictable = bool(spread_ratio is not None
                                 and spread_ratio <= MAGNITUDE_SPREAD_LIMIT)

    if consistency >= HIGHLY_REPEATABLE_SHARE and magnitude_predictable:
        band = "HIGHLY REPEATABLE"
    elif consistency >= CONSISTENT_SHARE:
        band = "MODERATELY REPEATABLE"
    elif consistency > LEANS_SHARE:
        band = "EMERGING / INCONSISTENT"
    else:
        band = "NOT SUPPORTED"

    # A median of exactly zero is a different finding from an unreliable direction, and the
    # consistency count is 0 there by construction -- nothing moves "the same way as" no movement.
    # Narrating that as a coin flip is a contradiction: flat is not undecided.
    if med == 0:
        if spread == 0:
            reading = (f"Across {n} past instances this queue's {label} has not moved at all "
                       f"(every instance 0%). There is no rebound pattern to plan against -- a flat "
                       f"history, not an unreliable one.")
        else:
            reading = (f"Across {n} past instances this queue's {label} has moved substantially in "
                       f"both directions ({_rnd(lo)}% to {_rnd(hi)}%) and the moves cancel, leaving "
                       f"a median of zero. Large but directionless, so no direction can be relied "
                       f"on.")
        return {
            "band": "NOT SUPPORTED",
            "instances": n,
            "median_change_pct": _rnd(med), "mean_change_pct": _rnd(mean),
            "min_change_pct": _rnd(lo), "max_change_pct": _rnd(hi),
            "spread_pct": _rnd(spread), "spread_ratio": None,
            "positive_share": _rnd(positive_share, 3),
            "direction_consistency": _rnd(consistency, 3),
            "large_change_share": _rnd(large, 3),
            "large_change_threshold_pct": _rnd(LARGE_CHANGE_SHARE * 100.0),
            "magnitude_predictable": False,
            "flat_history": bool(spread == 0),
            "reading": reading,
            "bands": ["HIGHLY REPEATABLE", "MODERATELY REPEATABLE", "EMERGING / INCONSISTENT",
                      "NOT SUPPORTED", "NOT ENOUGH DATA"],
        }

    direction = "upward" if med > 0 else "downward"
    head = (f"Across {n} past instances this queue's {label} has run {direction} "
            f"{_rnd(abs(med))}% at the median ({_rnd(lo)}% to {_rnd(hi)}%), "
            f"moving the same way {_rnd(consistency * 100)}% of the time")
    if band == "HIGHLY REPEATABLE":
        tail = (". Both the direction and the size are consistent enough to plan against.")
    elif band == "MODERATELY REPEATABLE":
        tail = ((". The direction is a usable forecasting signal; the size is not -- the range is "
                 f"{_rnd(spread)} points wide, so this should be treated as a directional signal "
                 f"rather than a fixed uplift.") if not magnitude_predictable else
                ". The direction is a usable forecasting signal.")
    elif band == "EMERGING / INCONSISTENT":
        tail = (". The pattern recurs but is not reliable: it should inform a forecaster's judgement "
                "and should not be applied as a fixed adjustment.")
    else:
        tail = (". The direction is close to a coin flip on this queue's own history, so there is no "
                "dependable pattern to plan against.")
    return {
        "band": band,
        "instances": n,
        "median_change_pct": _rnd(med), "mean_change_pct": _rnd(mean),
        "min_change_pct": _rnd(lo), "max_change_pct": _rnd(hi),
        "spread_pct": _rnd(spread),
        "spread_ratio": _rnd(spread_ratio, 2) if spread_ratio is not None else None,
        "positive_share": _rnd(positive_share, 3),
        "direction_consistency": _rnd(consistency, 3),
        "large_change_share": _rnd(large, 3),
        "large_change_threshold_pct": _rnd(LARGE_CHANGE_SHARE * 100.0),
        "magnitude_predictable": magnitude_predictable,
        "reading": head + tail,
        "bands": ["HIGHLY REPEATABLE", "MODERATELY REPEATABLE", "EMERGING / INCONSISTENT",
                  "NOT SUPPORTED", "NOT ENOUGH DATA"],
    }


def _canonical_display(events):
    """prompt2.md clause E: the executive list uses CANONICAL SEMANTIC names, raws kept for audit.

    Grouped by `semantic_group_id`, NOT by canonical_name. De-duplicating on the name still printed
    both "Ascension of Jesus Christ" and "Ascension Day of Jesus Christ" -- two spellings of one
    family, which is the repetition clause E exists to remove.

    Two dated occurrences of one family therefore collapse to one line naming the family. What this
    must never do is merge DIFFERENT holidays that share a date: grouping is by semantic group, so
    clause E's Christmas / Quaid-e-Azam prohibition holds by construction -- those have different
    groups and stay apart.
    """
    order, by_group = [], {}
    for e in events or []:
        gid = e.get("event_key") or e.get("canonical_name")
        nm = e.get("canonical_name") or (e.get("raw_names") or [None])[0]
        if not nm:
            continue
        if gid not in by_group:
            by_group[gid] = nm
            order.append(gid)
    return [by_group[g] for g in order]


def _canonical_detail(events):
    """The same grouping, with the evidence a reader needs to check it: every raw spelling and every
    date that sits under the family name shown above."""
    out, by_group = [], {}
    for e in events or []:
        gid = e.get("event_key") or e.get("canonical_name")
        if not gid:
            continue
        row = by_group.get(gid)
        if row is None:
            row = {"semantic_group_id": gid,
                   "display_name": e.get("canonical_name") or (e.get("raw_names") or [None])[0],
                   "occurrences": 0, "dates": [], "weekdays": [], "raw_names": [],
                   "fiscal_weeks": [], "needs_review": False}
            by_group[gid] = row
            out.append(row)
        row["occurrences"] += 1
        for k_src, k_dst in (("dates", "dates"), ("weekdays", "weekdays"),
                             ("raw_names", "raw_names"), ("fiscal_weeks", "fiscal_weeks")):
            for v in (e.get(k_src) or []):
                if v not in row[k_dst]:
                    row[k_dst].append(v)
        row["needs_review"] = row["needs_review"] or bool(e.get("needs_review"))
    return out


def _event_view(e):
    """One holiday event, shaped for a reader. Clause D's required fields, weekday included."""
    return {
        "canonical_name": e.get("canonical_name"),
        "raw_names": e.get("raw_names") or [],
        "semantic_group_id": e.get("event_key"),
        "dates": e.get("dates") or [],
        "weekdays": e.get("weekdays") or [],
        "fiscal_weeks": e.get("fiscal_weeks") or [],
        "offset_weeks": e.get("offset_weeks") or [],
        "types": e.get("types") or [],
        "modifier": e.get("modifier"),
        "needs_review": bool(e.get("needs_review")),
    }


def _in_week_view(events):
    """Clause F: holidays whose DATE falls inside the target fiscal week. Offset 0, nothing else."""
    inside = [e for e in (events or []) if 0 in (e.get("offset_weeks") or [])]
    return {
        "count": len(inside),
        "canonical_names": _canonical_display(inside),
        "events": [_event_view(e) for e in inside],
        "by_semantic_group": _canonical_detail(inside),
        # Clause N's required wording, built here so a renderer cannot get it wrong.
        "statement": ("Holidays in this week: None."
                      if not inside else
                      "Holidays in this week: " + ", ".join(_canonical_display(inside)) + "."),
    }


def _adjacent_view(events):
    """Clause F: holidays OUTSIDE the target week whose impact window still reaches it.

    Kept strictly apart from the in-week list. These may inform a pre- or post-holiday reading; they
    are never holidays "in" this week.
    """
    near = [e for e in (events or [])
            if e.get("reaches_target_week") and 0 not in (e.get("offset_weeks") or [])]
    names = _canonical_display(near)
    if not near:
        statement = "Recent holidays potentially affecting this week: none."
    else:
        statement = ("Recent holidays potentially affecting this week: " + ", ".join(names) + ". "
                     "No holiday occurs directly in this fiscal week; the analysis therefore "
                     "evaluates whether this week resembles a historical post-holiday or "
                     "pre-holiday pattern.")
    return {
        "count": len(near),
        "canonical_names": names,
        "events": [_event_view(e) for e in near],
        "by_semantic_group": _canonical_detail(near),
        "statement": statement,
        "note": ("Clause F: these are NOT holidays in the target week. Their dates fall outside it "
                 "and only their impact window reaches it."),
    }


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


# --- Systematic plan bias on holiday weeks -------------------------------------------------------
# A share this high of holiday weeks missing the SAME way is a standing bias in the adjustment, not
# a run of bad luck. Same figure as CONSISTENT_SHARE and for the same reason: below it, the pattern
# is not repeatable enough to hold the process to.
BIAS_SHARE = 0.70
# Median absolute adherence must exceed this for the bias to be worth reporting -- a systematic but
# tiny bias is arithmetically real and operationally irrelevant.
BIAS_MATERIAL_PCT = 10.0
# The later half's median miss must exceed the earlier half's by this much to call it widening.
BIAS_WIDENING_PCT = 5.0


def _adherence(actual, forecast):
    """Signed adherence. Negative means actual came in ABOVE plan."""
    if actual is None or not forecast:
        return None
    return (1.0 - actual / forecast) * 100.0


def plan_bias_by_phase(rows, country, cache):
    """Across this queue's HISTORY, does the plan miss the same way on holiday-phase weeks?

    WHY THIS IS A SEPARATE FINDING FROM `_capture`
    ----------------------------------------------
    `_capture` asks whether the plan applied the phase pattern to THIS week. It can answer
    "captured" -- correctly -- while the adjustment has been systematically too deep for years,
    because "captured" spans 0.5x to 1.75x the historical effect and every week can sit inside that
    band on the same side of it.

    On UKI Comm Client DSP Standard the plan came in BELOW actual on 12 of 20 holiday weeks and the
    recent misses were widening (-28.9%, -37.4%, -69.9%). Each week individually looked captured or
    close to it. The recurring defect is only visible across weeks, so it has to be measured across
    weeks.

    That distinction matters for the action: `_capture` failing points at THIS week's plan, whereas a
    standing bias points at the holiday adjustment RULE. Only the second one is worth changing a
    process for.

    Returns a per-phase block plus a `systematic` summary naming the worst offender.
    """
    buckets = {_cal.PHASE_HOLIDAY: [], _cal.PHASE_PRE: [], _cal.PHASE_POST: []}
    # `_phase_of` returns a (phase, span) TUPLE, not a label -- unpack it the same way
    # `_historical_phase_effect` does. `rows` are (week, forecast, actual), forecast FIRST.
    for week, forecast, actual in rows:
        phase, _span = _phase_of(country, week, cache)
        if phase in buckets:
            adh = _adherence(actual, forecast)
            if adh is not None:
                buckets[phase].append((week, adh))

    phases, worst = {}, None
    for phase, series in buckets.items():
        if len(series) < MIN_PHASE_INSTANCES:
            phases[phase] = {
                "testable": False, "instances": len(series),
                "reason": (f"only {len(series)} {phase.replace('_', ' ')} week(s) with both figures; "
                           f"{MIN_PHASE_INSTANCES} are required to judge a standing bias.")}
            continue

        adhs = [a for _, a in series]
        # adherence < 0 means actual ABOVE plan, i.e. the plan was too LOW for that week.
        too_low = [a for a in adhs if a < 0]
        too_high = [a for a in adhs if a > 0]
        n = len(adhs)
        share_low, share_high = len(too_low) / n, len(too_high) / n
        median_adh = _st.median(adhs)

        direction = None
        share = 0.0
        if share_low >= BIAS_SHARE:
            direction, share = "plan_too_low", share_low
        elif share_high >= BIAS_SHARE:
            direction, share = "plan_too_high", share_high

        # Widening? Compare the median absolute miss of the earlier half against the later half.
        half = n // 2
        earlier = [abs(a) for _, a in series[:half]]
        later = [abs(a) for _, a in series[half:]]
        widening, earlier_med, later_med = None, None, None
        if half >= 2:
            earlier_med, later_med = _st.median(earlier), _st.median(later)
            widening = (later_med - earlier_med) >= BIAS_WIDENING_PCT

        material = abs(median_adh) >= BIAS_MATERIAL_PCT
        systematic = bool(direction and material)

        blk = {
            "testable": True,
            "instances": n,
            "weeks_plan_too_low": len(too_low),
            "weeks_plan_too_high": len(too_high),
            "share_same_way": _rnd(share, 3) if direction else None,
            "median_adherence_pct": _rnd(median_adh),
            "worst_adherence_pct": _rnd(min(adhs, key=lambda a: a) if median_adh < 0
                                        else max(adhs, key=lambda a: a)),
            "recent_weeks": [{"fiscal_week": w, "adherence_pct": _rnd(a)} for w, a in series[-4:]],
            "earlier_half_median_abs": _rnd(earlier_med) if earlier_med is not None else None,
            "later_half_median_abs": _rnd(later_med) if later_med is not None else None,
            "widening": widening,
            "material": material,
            "systematic": systematic,
            "bias_direction": direction,
        }
        if systematic:
            side = ("BELOW actual -- the adjustment is consistently too deep"
                    if direction == "plan_too_low" else
                    "ABOVE actual -- the adjustment is consistently too shallow")
            blk["reading"] = (
                f"Across {n} {phase.replace('_', ' ')} week(s) in this queue's history the plan came "
                f"in {side}: {len(too_low) if direction == 'plan_too_low' else len(too_high)} of {n} "
                f"({share:.0%}), with a median miss of {median_adh:+.1f}%."
                + (f" The misses are WIDENING -- the later half medians "
                   f"{later_med:.1f}% against {earlier_med:.1f}% earlier."
                   if widening else ""))
            if worst is None or abs(median_adh) > abs(worst[1]):
                worst = (phase, median_adh, blk)
        else:
            blk["reading"] = (
                f"No standing bias: across {n} {phase.replace('_', ' ')} week(s) the plan missed "
                f"both ways ({len(too_low)} too low, {len(too_high)} too high), median "
                f"{median_adh:+.1f}%.")
        phases[phase] = blk

    # WIDENING IS REPORTED INDEPENDENTLY OF DIRECTION, and that was not the first design.
    #
    # The first version only surfaced a bias when it was one-SIDED at >= 70%. Run against UKI Comm
    # Client DSP Standard it correctly found none -- 10 of 17 holiday weeks too low is 59%, barely
    # better than a coin flip -- which disproved the "systematically too deep" reading of the raw
    # counts. Good: the gate did its job and refused a finding the data does not support.
    #
    # But the same queue shows the misses GETTING BIGGER on every phase (holiday 16.9% -> 22.6%,
    # pre 11.4% -> 20.9%, post 10.7% -> 29.9% median absolute). A widening miss with no consistent
    # direction is still a deteriorating adjustment and still worth acting on -- it is just a
    # different finding from a standing bias, and it wants different wording. Requiring a direction
    # before reporting it would have hidden it.
    deteriorating = [p for p, b in phases.items() if b.get("testable") and b.get("widening")]

    summary = {"available": True, "phases": phases, "systematic": bool(worst),
               "deteriorating_phases": deteriorating,
               "deteriorating": bool(deteriorating)}
    if worst:
        phase, median_adh, blk = worst
        summary.update({
            "worst_phase": phase,
            "bias_direction": blk["bias_direction"],
            "median_adherence_pct": blk["median_adherence_pct"],
            "widening": blk["widening"],
            "reading": blk["reading"],
            "action": (
                "Review the holiday adjustment RULE for this queue, not just this week's plan: the "
                "same error repeats across holiday weeks."
                if blk["bias_direction"] == "plan_too_low" else
                "Review the holiday adjustment RULE for this queue -- it consistently removes too "
                "little volume."),
        })
    else:
        summary["reading"] = ("No holiday phase shows a standing one-sided plan bias for this "
                              "queue -- the misses go both ways.")

    # Appended rather than replacing, so a queue can be BOTH biased and deteriorating and have both
    # stated. Where there is no bias this is the only finding, and it should not be silent.
    if deteriorating:
        detail = "; ".join(
            f"{p.replace('_', ' ')} {phases[p]['earlier_half_median_abs']:.1f}% -> "
            f"{phases[p]['later_half_median_abs']:.1f}%"
            for p in deteriorating)
        summary["deteriorating_reading"] = (
            f"The size of the miss on holiday-phase weeks is GROWING for this queue, comparing the "
            f"median absolute miss of the earlier half of each phase's history against the later "
            f"half: {detail}. The misses are not consistently one-sided, so this is a widening "
            f"adjustment rather than a standing bias.")
        summary["deteriorating_action"] = (
            "Revisit how the holiday adjustment is sized for this queue. It is not consistently too "
            "deep or too shallow, so the direction is not the problem -- the magnitude is drifting "
            "further from what the weeks actually deliver.")
        summary["reading"] = summary["reading"] + " " + summary["deteriorating_reading"]

    summary["note"] = ("Measured across the queue's whole history, which is the only place a "
                       "recurring adjustment error is visible. A single week can sit inside the "
                       "'captured' tolerance every time and still be biased or deteriorating. "
                       "A one-sided bias and a widening miss are DIFFERENT findings and are "
                       "reported separately.")
    return summary


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
        # "captured" spans a wide band -- anything from half the historical effect to 1.75x it. A
        # bare "captured" hid a 51% overshoot on UKI Comm Client DSP Standard FW202717, where the
        # plan cut -40.04% against the -26.54% history implies. The THRESHOLD is deliberately left
        # at 1.75 (it is versioned configuration no client has confirmed), but the size of the
        # over- or under-shoot inside the band is now stated rather than left for the reader to
        # divide two percentages in their head.
        overshoot = (ratio - 1.0) * 100.0
        if abs(overshoot) >= 15.0:
            tail = (f" That is {_rnd(abs(overshoot))}% "
                    f"{'more' if overshoot > 0 else 'less'} adjustment than the pattern calls for "
                    f"-- inside the tolerance for 'captured', but worth noting.")
        else:
            tail = ""
        out.update({"classification": "captured",
                    "overshoot_pct": _rnd(overshoot),
                    "within_tolerance": True,
                    "tolerance_band": f"{CAPTURE_TOLERANCE}x to {OVER_CAPTURE}x the phase effect",
                    "reason": (f"The plan moved {_rnd(forecast_share * 100)}% against the "
                               f"{_rnd(expected_share * 100)}% the phase historically implies "
                               f"({_rnd(ratio)}x).{tail}")})
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

    # A queue whose Country is blank, or whose Country the master does not know, cannot be checked
    # against a calendar. Reporting phase "none" there would state that no holiday applies, which
    # is a claim the data does not support -- the honest answer is that the check could not run.
    # (Some extracts genuinely carry blank scope columns for a queue, so this is a live path.)
    if not str(country or "").strip() or not span.get("countries_resolved"):
        return {"available": False, "phase": _cal.PHASE_NONE, "applies": False,
                "country_resolved": span.get("countries_resolved") or [],
                "reason": (f"the queue's Country is "
                           f"{'blank' if not str(country or '').strip() else repr(country)}, so it "
                           f"cannot be matched to the holiday calendar"),
                "note": ("Holiday effects were NOT checked for this queue. This is not the same as "
                         "finding no holiday.")}

    rows = _rows(history, target_week)
    cache = {}
    historical = _historical_phase_effect(rows, country, cache)
    # Standing bias across ALL holiday-phase weeks in history. Shares the phase cache, so it costs a
    # pass over rows already in memory rather than another calendar lookup per week.
    plan_bias = plan_bias_by_phase(rows, country, cache)
    # Shares the same phase cache, so this is a pass over rows already in memory.
    transitions = phase_transitions(rows, country, cache, target_week, target_actual)
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

    # Collapse spellings and multi-day rows into EVENTS before anything counts them, so holiday
    # pressure is never overstated by the master's naming (see holiday_events for the measured
    # scale of the problem). Raw names are retained inside each instance for traceability.
    all_rows = [h for group in (span.get("offsets") or {}).values() for h in group]
    events = holiday_events.normalise(all_rows)
    reaching_events = [e for e in events if e.get("reaches_target_week")]
    event_summary = holiday_events.summarise(events, reaching_only=True)

    reading = _reading(phase, span, phase_block, capture, row_holiday_count, event_summary)
    return {
        "available": True,
        "country_resolved": span.get("countries_resolved"),
        "phase": phase,
        "applies": span.get("applies"),
        "span_weeks": SPAN_WEEKS,
        # prompt2.md clause F -- MANDATORY separation. `names` is retained unchanged so nothing
        # that already reads it breaks, but it must never again be rendered as "holidays in this
        # week": on this queue it holds four holidays while row_holiday_count is 0 and not one of
        # them falls inside the target week.
        "names": span.get("names"),
        "holidays_in_target_week": _in_week_view(events),
        "recent_holidays_affecting_target_week": _adjacent_view(events),
        "families": span.get("families"),
        # Event-normalised view. `event_count` is the number a narrative should quote;
        # `raw_name_count` sits beside it so the collapsed inflation stays auditable.
        "events": events,
        "events_reaching_target_week": reaching_events,
        "event_summary": event_summary,
        "holidays_by_offset": span.get("offsets"),
        "holidays_reaching_target_week": span.get("reaching"),
        "row_holiday_count": row_holiday_count,
        "row_flag_disagreement": context.get("row_flag_disagreement"),
        "names_needing_review": context.get("names_needing_review"),
        "historical_response": historical,
        # ADDITIVE. Answers a different question from forecast_capture: not "did the plan apply the
        # pattern to THIS week" but "has the plan been missing the same way on these weeks for
        # years". Only the second one justifies changing the adjustment rule.
        "plan_bias": plan_bias,
        "phase_effect": phase_block,
        # Section 9 measurement A, deliberately adjacent to measurement B above so the two are
        # read together and the difference between them is visible on the card.
        "phase_transition": transitions,
        # Section 10's band, surfaced at the top level so a renderer does not have to reach two
        # levels down for the headline classification. Same object, not a second calculation.
        "rebound_repeatability": (transitions or {}).get("repeatability"),
        "expected_direction": expected_direction,
        "historical_consistency": consistency,
        "forecast_capture": capture,
        "reading": reading,
        "note": ("Holiday direction is measured from this queue's own history, never assumed. A "
                 "target week with Holiday_Count = 0 is still analysed when an adjacent holiday's "
                 "impact window reaches it."),
    }


def _reading(phase, span, phase_block, capture, row_holiday_count, event_summary=None):
    """One plain-English paragraph, safe to put in front of an executive."""
    if phase == _cal.PHASE_NONE:
        return ("No holiday falls in this week, and none in the surrounding weeks has an impact "
                "window wide enough to reach it.")
    # Quote EVENTS, not raw name spellings: the same holiday under two spellings, or a four-day
    # holiday listed once per day, would otherwise read as several separate holidays crowding the
    # week and make the calendar explanation look stronger than the calendar warrants.
    canonical = (event_summary or {}).get("canonical_names") or []
    names = ", ".join(canonical or span.get("names") or []) or "a holiday"
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
