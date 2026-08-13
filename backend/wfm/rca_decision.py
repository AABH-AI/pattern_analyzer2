# -*- coding: utf-8 -*-
"""
The RCA decision layer -- what the evidence PROVES, decided in Python before the model speaks.

    Python determines WHAT the data proves.
    This layer determines WHAT MAY BE CLAIMED.
    The LLM determines HOW to explain it.

WHY THIS MODULE EXISTS
----------------------
Phase 1 produced more evidence, and more evidence means more ways to be confidently wrong. Two
explanations can each look reasonable alone and contradict each other in the same report -- the
baseline was too low AND demand spiked unforeseeably are different diagnoses with different
actions, and shipping both as "Verified" tells a forecaster nothing. Ranking was also left to the
model, which meant the loudest number won rather than the best-supported mechanism.

This module makes every judgement deterministically:

    which mechanisms the evidence actually supports        -> candidates
    whether each one points the same way as the miss       -> direction coherence  (spec 9)
    what argues against each one                           -> contradiction resolution (spec 8)
    how they rank against each other                       -> evidence_class  (spec 19)
    what KIND of forecasting failure this was              -> miss_category   (spec 6)
    how strong the evidence is                             -> confidence      (spec 17)
    how much it matters operationally                      -> criticality     (spec 18)

THE CENTRAL RULE (spec 7)
-------------------------
A large gap between actual and forecast is NOT sufficient to call something a forecast failure.
A mechanism may only be promoted to a forecast-response failure when a signal existed BEFORE the
week AND that signal has behaved repeatably for this queue. Where no such signal existed, the
honest answer is a low-predictability demand event, and the forecaster is not blamed for it.

ADDITIVE ONLY
-------------
`cause_type` and `status` keep their existing values and meanings. `miss_category`,
`evidence_class` and `criticality` are new fields alongside them, so every existing consumer --
the console, `results/*.py`, `back_compat()` -- keeps working unchanged.

DEPENDENCIES: standard library only.
"""

# ---------------------------------------------------------------------------
# the vocabularies -- new, additive, and separate from cause_type/status
# ---------------------------------------------------------------------------
MISS_CATEGORIES = (
    "FORECAST_BASELINE_FAILURE",
    "FORECAST_RESPONSE_FAILURE",
    "CALENDAR_RESPONSE_FAILURE",
    "DRIVER_RESPONSE_FAILURE",
    "DEMAND_EVENT",
    "COMPOUND_MISS",
    "DATA_LIMITATION",
)

EVIDENCE_CLASSES = (
    "PRIMARY_DRIVER",
    "SECONDARY_CONTRIBUTOR",
    "CONTEXTUAL_FACTOR",
    "UNCONFIRMED_SIGNAL",
    "REJECTED",
)

RESOLUTIONS = ("supported", "mixed", "rejected")
CRITICALITIES = ("Critical", "High", "Medium", "Low")

# --- thresholds. Every one is a judgement call, named so it can be argued with. ---
MATERIAL_SHARE = 0.30        # a side of the decomposition worth calling a contributor
DOMINANT_SHARE = 0.65        # one side this dominant makes the other a secondary at most
PRIMARY_MIN_STRENGTH = 0.55  # below this nothing is promoted to PRIMARY_DRIVER
SECONDARY_MIN_STRENGTH = 0.35
CONTEXTUAL_MIN_STRENGTH = 0.15
COMPOUND_MIN_STRENGTH = 0.45  # a second mechanism this strong makes the miss compound

# --- criticality: miss size x queue volume (spec 18). Bands are on the OPERATIONAL gap, so a
#     small queue with a huge percentage cannot outrank a large queue with a real staffing hole. ---
CRITICAL_CONTACTS = 500      # contacts above/below plan that WFM would have to cover
HIGH_CONTACTS = 150
MEDIUM_CONTACTS = 40
CRITICAL_RELATIVE = 1.00     # gap as a multiple of a typical week for this queue
HIGH_RELATIVE = 0.50
MEDIUM_RELATIVE = 0.20


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


def _clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


def _get(d, *path, default=None):
    cur = d
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
    return default if cur is None else cur


# ---------------------------------------------------------------------------
# 1. evidence index -- every claim in the report can be traced to one of these (spec 23)
# ---------------------------------------------------------------------------
def build_evidence_index(features, actual, forecast, adherence):
    """The deterministic facts, each with a stable id, a value and where it came from.

    Nothing here is computed for the first time -- it is a citable index over what the Phase 1
    modules already produced, so a client challenging a sentence lands on a metric, a window and a
    data-availability statement.
    """
    fr = features.get("forecast_response") or {}
    hol = features.get("holiday_response") or {}
    lag = features.get("lag_analysis") or {}
    gran = features.get("data_granularity") or {}
    corr = features.get("correlations") or {}
    ladder = features.get("investigation_ladder") or {}
    dq = features.get("data_quality") or {}
    base = features.get("base_features") or {}

    ev = {}

    def add(eid, label, value, source, window=None, available=True, note=None):
        ev[eid] = {"id": eid, "label": label, "value": value, "source": source,
                   "window": window, "available": bool(available), "note": note}

    gap = (actual - forecast) if (actual is not None and forecast is not None) else None
    add("E1", "Forecast miss", _rnd(gap), "target row: Actual_Offered - fcst_offered",
        window="target week", available=gap is not None)
    add("E1a", "Actual Offered", _rnd(actual), "target row", window="target week",
        available=actual is not None)
    add("E1b", "Forecast Offered", _rnd(forecast), "target row", window="target week",
        available=forecast is not None)
    add("E1c", "Forecast Adherence", _rnd(adherence, 1), "(1 - actual/forecast) x 100",
        window="target week", available=adherence is not None)

    baselines = fr.get("baselines") or {}
    add("E2", "Expected demand level", baselines.get("expected_demand"),
        baselines.get("expected_basis") or "not established",
        window=baselines.get("expected_basis"),
        available=baselines.get("expected_demand") is not None)

    dec = fr.get("miss_decomposition") or {}
    add("E3", "Miss split: forecast side vs demand side",
        {"forecast_side": dec.get("forecast_side_contribution"),
         "demand_side": dec.get("demand_side_contribution"),
         "leading_side": dec.get("leading_side")},
        "forecast_response.miss_decomposition (an identity, not an attribution model)",
        window=baselines.get("expected_basis"), available=bool(dec.get("available")),
        note=dec.get("reason"))

    mom = next((s for s in (fr.get("signals") or []) if s.get("signal") == "demand_momentum"), {})
    add("E4", "Demand momentum before the target week", mom.get("change_pct"),
        "forecast_response: last 4 weeks against the 8 before them",
        window="12 weeks before target", available=bool(mom.get("testable")),
        note=mom.get("reason"))

    add("E5", "Same-week seasonal reference", baselines.get("same_week_median_actual"),
        f"median of the same fiscal week across "
        f"{baselines.get('same_week_years_found') or 0} prior year(s)",
        window="prior years, same week",
        available=baselines.get("same_week_median_actual") is not None)

    moves = [m for m in (fr.get("movement_test") or []) if m.get("testable")]
    add("E6", "Actual movement against forecast movement",
        [{"lookback_weeks": m["lookback_weeks"], "actual": m["actual_direction"],
          "forecast": m["forecast_direction"], "opposed": m["directions_opposed"]}
         for m in moves],
        "forecast_response.movement_test", window="1, 2 and 4 weeks back",
        available=bool(moves))

    resp = fr.get("response") or {}
    add("E7", "Forecast response adequacy", resp.get("classification"),
        "forecast_response.response -- judged against what the expected level implied, "
        "never against the outcome", available=resp.get("classification") != "not_testable",
        note=resp.get("reason"))

    fcast = fr.get("forecastability") or {}
    add("E8", "Forecastability", fcast.get("classification"),
        "forecast_response.forecastability -- a signal counts only if it has behaved "
        "repeatably for this queue", available=bool(fcast.get("classification")),
        note=fcast.get("reason"))

    add("E9", "Holiday phase and its measured effect here",
        {"phase": hol.get("phase"), "events": _get(hol, "event_summary", "event_count"),
         "effect_pct": _get(hol, "phase_effect", "actual_effect_pct"),
         "consistency": hol.get("historical_consistency")},
        "holiday_response -- effect measured from this queue's own history, never assumed",
        window=f"+/-{hol.get('span_weeks')} weeks", available=bool(hol.get("available")),
        note=hol.get("reason"))
    add("E10", "Did the plan capture the holiday pattern",
        _get(hol, "forecast_capture", "classification"),
        "holiday_response.forecast_capture", available=bool(hol.get("available")),
        note=_get(hol, "forecast_capture", "reason"))

    drivers = lag.get("drivers") or []
    add("E11", "Best driver lead relationship",
        [{"driver": d["driver"], "best_lag_weeks": d.get("best_lag_weeks"),
          "strength": d.get("relationship_strength"), "stability": d.get("stability"),
          "type": d.get("relationship_type"), "usable": d.get("usable_as_evidence")}
         for d in drivers if d.get("tested")],
        f"lag_analysis: Spearman at lags {lag.get('lags_tested')}, level and change families",
        window=f"{lag.get('weeks_in_window')} weeks", available=bool(lag.get("available")))
    add("E12", "Driver data coverage",
        [{"driver": d["driver"], "coverage": d.get("coverage"),
          "weeks_with_a_value": d.get("weeks_with_a_value"),
          "weeks_in_window": d.get("weeks_in_window")} for d in drivers],
        "lag_analysis coverage classes: populated / sparse / absent",
        available=bool(lag.get("available")))

    asu = corr.get("driver_decomposition") or {}
    add("E13", "ASU decomposition (population vs contact rate)",
        {"verdict": asu.get("verdict"), "base_effect": asu.get("warranty_base_effect"),
         "rate_effect": asu.get("contacts_per_unit_effect"),
         "reconciles": asu.get("reconciles")},
        "correlation_engine.driver_decomposition -- exact identity when both ASU figures exist",
        available=bool(asu.get("available")), note=asu.get("reason"))

    add("E14", "Where the miss is visible in the hierarchy",
        {"inherited_from": ladder.get("inherited_from"),
         "levels_breaching": ladder.get("levels_breaching_band")},
        "hierarchy_analyzer -- scope, not cause", available=bool(ladder.get("available")))

    add("E15", "Weekend / day-level evidence",
        gran.get("weekend_statement") or "day-level data available",
        "data_granularity -- checked against the actual rows",
        available=bool(_get(gran, "capabilities", "weekend_volume_effect")),
        note=gran.get("weekend_statement"))

    add("E16", "Is the number itself credible",
        {"suspect": dq.get("suspect"), "times_typical": dq.get("times_typical")},
        "data_quality", available=bool(dq.get("available")))

    add("E17", "Similar queues that week",
        {"peers": _get(base, "peer_divergence", "peers_total"),
         "opposite_direction": _get(base, "peer_divergence", "peers_opposite_direction")},
        "peer_divergence", available=_get(base, "peer_divergence") is not None)
    return ev


# ---------------------------------------------------------------------------
# 2. candidate mechanisms, each generated only where its evidence exists
# ---------------------------------------------------------------------------
def _miss_direction(actual, forecast):
    if actual is None or forecast is None:
        return None
    if actual > forecast:
        return "under_forecast"      # demand ran ABOVE plan
    if actual < forecast:
        return "over_forecast"
    return "on_plan"


def _direction_coherent(predicted, miss_direction):
    """Does the mechanism push actual the way the miss actually went? (spec 9)

    `predicted` is what the mechanism does to ACTUAL relative to FORECAST: "higher" or "lower".
    A mechanism that suppresses demand cannot explain a week that ran busier, however strong its
    other evidence -- this is the check that stops a holiday being blamed for a spike.
    """
    if predicted is None or miss_direction is None:
        return None
    if miss_direction == "under_forecast":
        return predicted == "higher"
    if miss_direction == "over_forecast":
        return predicted == "lower"
    return None


def _candidates(features, actual, forecast, miss_direction):
    """Every mechanism the evidence can support, with a deterministic strength in [0, 1].

    A mechanism that has no evidence is not generated at all -- absence here is silence, never a
    weak claim.
    """
    fr = features.get("forecast_response") or {}
    hol = features.get("holiday_response") or {}
    lag = features.get("lag_analysis") or {}
    corr = features.get("correlations") or {}
    base = features.get("base_features") or {}
    dq = features.get("data_quality") or {}

    dec = fr.get("miss_decomposition") or {}
    resp = fr.get("response") or {}
    fcast = (fr.get("forecastability") or {}).get("classification")
    signals = fr.get("signals") or []
    out = []

    # ---- data quality first: if the number itself is not credible nothing else matters ----
    if dq.get("suspect"):
        out.append({
            "key": "data_quality", "cause_type": "data_quality_issue",
            "category_hint": "DATA_LIMITATION",
            "headline": "The reported figure itself does not look credible",
            "what": (f"This week reads {dq.get('times_typical')}x a typical week and "
                     f"{'returns to normal immediately after' if dq.get('returns_to_normal_immediately') else 'does not settle'}."),
            "why_it_mattered": "A value this far from the queue's own history should be confirmed "
                               "before any forecasting conclusion is drawn from it.",
            "mechanism": "Nothing can be attributed to forecasting until the figure is confirmed.",
            "predicted_direction": None, "strength": 0.9,
            "evidence_ids": ["E16", "E1"], "action": "Confirm the reported volume at source before "
                                                     "acting on this week.",
        })

    # ---- forecast baseline: the plan started away from the expected level ----
    fs = _num(dec.get("forecast_side_contribution"))
    fs_share = _num(dec.get("forecast_side_share"))
    if dec.get("available") and fs is not None and fs_share is not None and abs(fs) > 0:
        material = fs_share >= MATERIAL_SHARE
        plan_gap = _get(features, "statistical_evidence", "metrics", "plan_vs_seasonal_norm",
                        default={}) or {}
        seasonal_backed = bool(plan_gap.get("plan_gap_material")) and \
            bool(plan_gap.get("direction_coherent"))
        strength = _clamp(fs_share * (1.15 if seasonal_backed else 0.95))
        if material:
            out.append({
                "key": "baseline", "cause_type": "forecast_baseline_error",
                "category_hint": "FORECAST_BASELINE_FAILURE",
                "headline": "Forecast baseline was "
                            f"{'under' if fs > 0 else 'over'}-sized before the week began",
                "what": (f"The plan entered the week {abs(_rnd(fs))} contacts "
                         f"{'below' if fs > 0 else 'above'} the expected demand level of "
                         f"{dec.get('expected_demand')} ({dec.get('expected_basis')})."),
                "why_it_mattered": ("That gap existed before any demand movement, so part of the "
                                    "miss was already committed when the week started."),
                "mechanism": "The starting baseline did not reflect the expected level for this "
                             "week of the year.",
                "predicted_direction": "higher" if fs > 0 else "lower",
                "strength": strength,
                "evidence_ids": ["E3", "E2", "E5"],
                "action": "Re-baseline this queue against its same-week seasonal level rather "
                          "than its recent trailing average.",
            })

    # ---- demand moved away from the expected level ----
    ds = _num(dec.get("demand_side_contribution"))
    ds_share = _num(dec.get("demand_side_share"))
    if dec.get("available") and ds is not None and ds_share is not None and abs(ds) > 0:
        if ds_share >= MATERIAL_SHARE:
            low_predictability = fcast in ("LOW_PREDICTABILITY", "NOT_TESTABLE", None)
            out.append({
                "key": "demand_event", "cause_type": "genuine_demand_event",
                "category_hint": "DEMAND_EVENT",
                "headline": ("Demand moved beyond what any signal foreshadowed"
                             if low_predictability else
                             "Demand moved away from its expected level"),
                "what": (f"Demand landed {abs(_rnd(ds))} contacts "
                         f"{'above' if ds > 0 else 'below'} the expected level of "
                         f"{dec.get('expected_demand')}."),
                "why_it_mattered": ("No leading signal was available to anticipate this, so it is "
                                    "a demand event rather than a planning failure."
                                    if low_predictability else
                                    "Demand itself, not only the plan, moved this week."),
                "mechanism": ("Low predictability: nothing in this queue's own history "
                              "foreshadowed the move." if low_predictability else
                              "A demand movement the plan did not contain."),
                "predicted_direction": "higher" if ds > 0 else "lower",
                "strength": _clamp(ds_share * (1.0 if low_predictability else 0.85)),
                "evidence_ids": ["E3", "E8", "E4"],
                "action": ("Treat as a demand event: review whether any external signal could be "
                           "brought into the forecast, rather than re-tuning the model."
                           if low_predictability else
                           "Review what moved demand and whether it is repeatable."),
            })

    # ---- forecast response failure: a repeatable signal existed and the plan did not follow ----
    cls = resp.get("classification")
    if cls in ("no_response", "wrong_direction", "under_response", "delayed_response") \
            and fcast in ("PREDICTABLE", "PARTIALLY_PREDICTABLE"):
        severity = {"wrong_direction": 0.95, "no_response": 0.85, "under_response": 0.7,
                    "delayed_response": 0.65}[cls]
        confidence_factor = 1.0 if fcast == "PREDICTABLE" else 0.7
        detected = [s.get("signal") for s in signals if s.get("detected")]
        out.append({
            "key": "response", "cause_type": "systematic_forecast_bias",
            "category_hint": "FORECAST_RESPONSE_FAILURE",
            "headline": {
                "wrong_direction": "The plan moved the opposite way to the signal",
                "no_response": "The plan did not react to a visible signal",
                "under_response": "The plan reacted, but by far too little",
                "delayed_response": "The plan reacted, but too late",
            }[cls],
            "what": resp.get("reason"),
            "why_it_mattered": ("A signal was visible before the week and this queue's history "
                                "shows that signal is worth acting on."),
            "mechanism": "The forecast did not translate an available leading signal into the plan.",
            "predicted_direction": "higher" if (_num(resp.get("implied_change")) or 0) > 0
                                   else "lower",
            "strength": _clamp(severity * confidence_factor),
            "evidence_ids": ["E7", "E8", "E6", "E4"],
            "action": ("Review why the visible movement in "
                       f"{', '.join(detected) or 'the leading indicators'} did not reach the plan "
                       f"for this week."),
        })

    # ---- calendar: a repeatable holiday phase the plan did not capture ----
    phase = hol.get("phase")
    phase_effect = hol.get("phase_effect") or {}
    capture = (hol.get("forecast_capture") or {}).get("classification")
    if hol.get("available") and phase and phase != "none" and phase_effect.get("testable"):
        if phase_effect.get("consistent") and phase_effect.get("material") and \
                capture in ("under_reacted", "wrong_direction", "delayed", "over_reacted"):
            effect = _num(phase_effect.get("actual_effect_pct")) or 0
            names = ", ".join((hol.get("event_summary") or {}).get("canonical_names") or []) \
                or "a holiday"
            out.append({
                "key": "calendar", "cause_type": "calendar_holiday_effect",
                "category_hint": "CALENDAR_RESPONSE_FAILURE",
                "headline": f"A repeating {phase.replace('_', '-')} pattern was not planned for",
                "what": (f"{names} places this week in the {phase.replace('_', ' ')} phase, which "
                         f"historically runs {abs(_rnd(effect))}% "
                         f"{'above' if effect > 0 else 'below'} this queue's normal level "
                         f"across {phase_effect.get('instances')} comparable weeks."),
                "why_it_mattered": ("The date is known years ahead and the queue's response to it "
                                    "has been consistent, so this was foreseeable."),
                "mechanism": f"The plan {capture.replace('_', ' ')} the known calendar pattern.",
                "predicted_direction": "higher" if effect > 0 else "lower",
                "strength": _clamp(0.55 + 0.35 * (_num(phase_effect.get("consistency")) or 0)),
                "evidence_ids": ["E9", "E10"],
                "action": f"Build the measured {phase.replace('_', ' ')} response into the plan "
                          f"for this queue.",
            })
        elif phase_effect.get("material"):
            # present and measured, but not dependable enough to blame the plan for
            out.append({
                "key": "calendar_context", "cause_type": "calendar_holiday_effect",
                "category_hint": None,
                "headline": "A holiday phase applies, but its effect here is not dependable",
                "what": (f"This week sits in the {phase.replace('_', ' ')} phase; across "
                         f"{phase_effect.get('instances')} comparable weeks the response has not "
                         f"been consistent."),
                "why_it_mattered": "Context worth knowing, but not firm enough to attribute the "
                                   "miss to.",
                "mechanism": "Calendar context only.",
                "predicted_direction": None,
                "strength": 0.25, "evidence_ids": ["E9"],
                "action": "Track this queue's holiday response until a dependable pattern emerges.",
                "context_only": True,
            })

    # ---- an operational driver led demand and the plan did not follow it ----
    for sig in signals:
        name = str(sig.get("signal") or "")
        if not name.startswith("driver_movement:") or not sig.get("detected"):
            continue
        driver = sig.get("driver")
        entry = next((d for d in (lag.get("drivers") or []) if d.get("driver") == driver), {})
        if not entry.get("usable_as_evidence"):
            continue
        stable = entry.get("stability") == "stable"
        responded_badly = cls in ("no_response", "wrong_direction", "under_response",
                                  "delayed_response")
        if not responded_badly:
            continue
        out.append({
            "key": f"driver:{driver}", "cause_type": "installed_base_change",
            "category_hint": "DRIVER_RESPONSE_FAILURE",
            "headline": f"A leading operational signal moved and the plan did not follow",
            "what": (f"{entry.get('subject', driver)} moved {sig.get('change_pct')}% "
                     f"{sig.get('lag_weeks')} week(s) before this one, and this queue's history "
                     f"shows a {entry.get('stability')} relationship at that lead."),
            "why_it_mattered": "The movement was visible in time to act on it.",
            "mechanism": "The plan did not reflect a driver that historically leads demand here.",
            "predicted_direction": "higher" if sig.get("implies_demand") == "up" else "lower",
            "strength": _clamp((0.55 if stable else 0.4)
                               + 0.35 * abs(_num(entry.get("relationship_strength")) or 0)),
            "evidence_ids": ["E11", "E12", "E7"],
            "action": f"Link the plan to {entry.get('subject', driver)} at a "
                      f"{sig.get('lag_weeks')}-week lead for this queue.",
        })

    # ---- ASU: an exact decomposition, when it is available ----
    asu = corr.get("driver_decomposition") or {}
    if asu.get("available") and asu.get("verdict"):
        verdict = asu.get("verdict")
        out.append({
            "key": "asu", "cause_type": "installed_base_change",
            "category_hint": "DRIVER_RESPONSE_FAILURE",
            "headline": {"warranty_base_driven": "The supported population differed from plan",
                         "contact_rate_driven": "Contacts per supported unit differed from plan",
                         "mixed": "Both the supported population and the contact rate differed "
                                  "from plan"}.get(verdict, "ASU decomposition"),
            "what": asu.get("plain_language"),
            "why_it_mattered": "This split reconciles exactly to the miss, so it is attribution "
                               "rather than association.",
            "mechanism": "The plan's assumption about the supported base or the contact rate did "
                         "not hold.",
            "predicted_direction": "higher" if (actual or 0) > (forecast or 0) else "lower",
            "strength": 0.75, "evidence_ids": ["E13"],
            "action": "Reconcile the ASU assumptions behind this queue's plan.",
        })

    # ---- inheritance is SCOPE, not cause (spec 22) ----
    ladder = features.get("investigation_ladder") or {}
    inherited = ladder.get("inherited_from")
    if inherited:
        levels = ladder.get("levels") or []
        parent = next((lv for lv in levels if lv.get("level") == inherited), {})
        target_level = levels[-1] if levels else {}
        degenerate = (parent.get("queue_weeks_in_scope") or 0) <= 1 or \
            (parent.get("actual_offered") == target_level.get("actual_offered"))
        out.append({
            "key": "scope", "cause_type": "inherited_from_higher_level",
            "category_hint": None,
            "headline": f"The same miss is visible at {inherited} level",
            "what": (f"{inherited} shows {parent.get('adherence_pct')}% adherence across "
                     f"{parent.get('queue_weeks_in_scope')} queue-week(s)."),
            "why_it_mattered": ("This narrows WHERE the miss sits. It does not explain WHY."
                                + (" Here the parent contains only this queue, so it adds no "
                                   "new information." if degenerate else "")),
            "mechanism": "Scope, not mechanism.",
            "predicted_direction": None, "strength": 0.1 if degenerate else 0.2,
            "evidence_ids": ["E14"], "context_only": True,
            "action": ("Explain this queue on its own evidence; the higher level adds nothing here."
                       if degenerate else
                       f"Check whether the {inherited} plan needs re-basing as a whole."),
        })
    return out


# ---------------------------------------------------------------------------
# 3. contradiction resolution (spec 8) and direction coherence (spec 9)
# ---------------------------------------------------------------------------
def _resolve(cand, features, miss_direction, others):
    """Supported / mixed / rejected, with the contradicting evidence named.

    A mechanism is rejected outright only for a hard reason -- it points the wrong way, or the
    feature it depends on is absent. Everything softer is `mixed`, which keeps the finding visible
    while stopping it being presented as settled.
    """
    contradictions = []
    fr = features.get("forecast_response") or {}
    dec = fr.get("miss_decomposition") or {}

    coherent = _direction_coherent(cand.get("predicted_direction"), miss_direction)
    if coherent is False:
        contradictions.append({
            "evidence": "direction coherence",
            "statement": (f"This mechanism would push demand "
                          f"{cand.get('predicted_direction')} relative to plan, but the week ran "
                          f"{'above' if miss_direction == 'under_forecast' else 'below'} plan. "
                          f"It cannot explain the direction of this miss."),
            "hard": True})

    if cand["key"] == "demand_event":
        # a demand event is contradicted by a repeatable signal having existed
        fcast = (fr.get("forecastability") or {}).get("classification")
        if fcast == "PREDICTABLE":
            contradictions.append({
                "evidence": "E8",
                "statement": ("A leading signal existed before the week and has behaved repeatably "
                              "for this queue, so the movement was foreseeable and this is not "
                              "purely a demand event."),
                "hard": False})
    if cand["key"] == "baseline":
        fs_share = _num(dec.get("forecast_side_share")) or 0
        if fs_share < MATERIAL_SHARE:
            contradictions.append({
                "evidence": "E3",
                "statement": (f"Only {int(fs_share * 100)}% of the miss sits on the forecast side, "
                              f"so the starting plan is not the main explanation."),
                "hard": False})
        sanity = _get(features, "base_features", "forecast_sanity", default={}) or {}
        if sanity.get("verdict") == "actual_anomalous":
            contradictions.append({
                "evidence": "forecast_sanity",
                "statement": ("Against the queue's recent 13 weeks the plan looks normal and the "
                              "ACTUAL looks unusual, which argues the demand moved rather than the "
                              "plan being mis-set. The two baselines disagree because the recent "
                              "weeks are themselves below the seasonal level."),
                "hard": False})
    if cand["key"] == "response":
        if (fr.get("forecastability") or {}).get("classification") == "PARTIALLY_PREDICTABLE":
            contradictions.append({
                "evidence": "E8",
                "statement": ("The signal's historical timing or size has not been consistent, so "
                              "only part of this movement was reasonably foreseeable."),
                "hard": False})
    if cand["key"].startswith("driver:"):
        entry_ids = cand.get("evidence_ids") or []
        if "E13" not in entry_ids and not (features.get("correlations") or {}).get(
                "driver_decomposition", {}).get("available"):
            contradictions.append({
                "evidence": "E13",
                "statement": ("The exact ASU decomposition is unavailable this week, so the driver "
                              "relationship is association rather than exact attribution."),
                "hard": False})

    if any(c["hard"] for c in contradictions):
        resolution = "rejected"
    elif contradictions:
        resolution = "mixed"
    else:
        resolution = "supported"
    return {"resolution": resolution, "direction_coherent": coherent,
            "contradictions": contradictions}


# ---------------------------------------------------------------------------
# 4. evidence class + miss category
# ---------------------------------------------------------------------------
def _classify(cands):
    """Rank deterministically on total evidence, not on the model's order or a raw coefficient."""
    for c in cands:
        if c["resolution"] == "rejected":
            c["evidence_class"] = "REJECTED"
        elif c.get("context_only"):
            c["evidence_class"] = "CONTEXTUAL_FACTOR"
        elif c["strength"] < CONTEXTUAL_MIN_STRENGTH:
            c["evidence_class"] = "UNCONFIRMED_SIGNAL"
        else:
            c["evidence_class"] = None      # decided below, once the field is known

    live = [c for c in cands if c["evidence_class"] is None]
    live.sort(key=lambda c: (-c["strength"], c["key"]))
    for i, c in enumerate(live):
        if i == 0 and c["strength"] >= PRIMARY_MIN_STRENGTH and c["resolution"] == "supported":
            c["evidence_class"] = "PRIMARY_DRIVER"
        elif i == 0 and c["strength"] >= PRIMARY_MIN_STRENGTH:
            # strong but contested -- still leads, and the contest is reported with it
            c["evidence_class"] = "PRIMARY_DRIVER"
        elif c["strength"] >= SECONDARY_MIN_STRENGTH:
            c["evidence_class"] = "SECONDARY_CONTRIBUTOR"
        elif c["strength"] >= CONTEXTUAL_MIN_STRENGTH:
            c["evidence_class"] = "CONTEXTUAL_FACTOR"
        else:
            c["evidence_class"] = "UNCONFIRMED_SIGNAL"
    cands.sort(key=lambda c: (EVIDENCE_CLASSES.index(c["evidence_class"]), -c["strength"]))
    return cands


def _miss_category(cands, features, actual, forecast):
    """What KIND of forecasting problem this was -- decided here, never by the model (spec 6)."""
    fr = features.get("forecast_response") or {}
    reasons = []

    if not fr.get("available"):
        return "DATA_LIMITATION", (fr.get("reason") or
                                   "there is not enough history to diagnose this miss"), []
    primary = next((c for c in cands if c["evidence_class"] == "PRIMARY_DRIVER"), None)
    if primary is None:
        dec = fr.get("miss_decomposition") or {}
        if not dec.get("available"):
            return ("DATA_LIMITATION",
                    "The miss cannot be split into forecast-side and demand-side contributions, "
                    "so no mechanism can be established: " + str(dec.get("reason")), [])
        return ("DATA_LIMITATION",
                "No mechanism reached the evidence threshold, so the cause is not established "
                "on the available data.", [])

    if primary["key"] == "data_quality":
        return ("DATA_LIMITATION",
                "The reported figure is not credible enough to diagnose a forecasting cause.",
                ["E16"])

    contributors = [c for c in cands
                    if c["evidence_class"] in ("PRIMARY_DRIVER", "SECONDARY_CONTRIBUTOR")
                    and not c.get("context_only")
                    and c["strength"] >= COMPOUND_MIN_STRENGTH
                    and c["resolution"] != "rejected"]
    distinct = {c["category_hint"] for c in contributors if c.get("category_hint")}
    for c in contributors:
        reasons.extend(c.get("evidence_ids") or [])

    if len(distinct) > 1:
        return ("COMPOUND_MISS",
                "More than one mechanism contributes materially: "
                + "; ".join(sorted(distinct)) + ".", sorted(set(reasons)))
    return (primary.get("category_hint") or "DEMAND_EVENT",
            primary.get("mechanism") or primary.get("what"),
            sorted(set(primary.get("evidence_ids") or [])))


# ---------------------------------------------------------------------------
# 5. confidence (evidence strength) and criticality (business severity) -- independent
# ---------------------------------------------------------------------------
def _confidence(cands, features, evidence):
    """How strong is the evidence behind the leading explanation? (spec 17)

    Deliberately NOT severity, and deliberately not the model's number. A tiny sample cannot raise
    it; a missing dimension that the chosen explanation does not depend on does not destroy it.
    """
    primary = next((c for c in cands if c["evidence_class"] == "PRIMARY_DRIVER"), None)
    if primary is None:
        return {"score_pct": None, "level": "Low",
                "reason": "no mechanism reached the evidence threshold",
                "dimensions": []}

    fr = features.get("forecast_response") or {}
    lag = features.get("lag_analysis") or {}
    dims = []

    def dim(name, value, weight, note):
        dims.append({"dimension": name, "score": _rnd(value, 3), "weight": weight, "note": note})

    dim("mechanism evidence strength", primary["strength"], 0.30,
        "how directly the evidence supports this mechanism")

    weeks = _num(fr.get("weeks_available")) or 0
    dim("history depth", _clamp(weeks / 104.0), 0.15,
        f"{int(weeks)} usable weeks before the target week")

    contradiction_penalty = 1.0 if primary["resolution"] == "supported" else (
        0.6 if primary["resolution"] == "mixed" else 0.0)
    dim("absence of contradiction", contradiction_penalty, 0.20,
        primary["resolution"])

    fcast = (fr.get("forecastability") or {}).get("classification")
    dim("forecastability established",
        {"PREDICTABLE": 1.0, "PARTIALLY_PREDICTABLE": 0.6,
         "LOW_PREDICTABILITY": 0.5, "NOT_TESTABLE": 0.3}.get(fcast, 0.3), 0.15,
        f"forecastability is {fcast}")

    tested = [d for d in (lag.get("drivers") or []) if d.get("tested")]
    coverage = (sum(1 for d in tested) / len(lag.get("drivers") or [1])) if lag.get("drivers") else 0
    dim("driver data coverage", _clamp(coverage), 0.10,
        f"{len(tested)} of {len(lag.get('drivers') or [])} drivers had enough data to test")

    needed = set(primary.get("evidence_ids") or [])
    have = sum(1 for eid in needed if (evidence.get(eid) or {}).get("available"))
    dim("evidence this explanation depends on is present",
        (have / len(needed)) if needed else 1.0, 0.10,
        f"{have} of {len(needed)} required evidence items available")

    score = sum(d["score"] * d["weight"] for d in dims)
    pct = int(round(_clamp(score) * 100))
    level = "High" if pct >= 70 else ("Medium" if pct >= 40 else "Low")
    return {"score_pct": pct, "level": level, "dimensions": dims,
            "reason": (f"Evidence strength for the leading explanation, weighted across "
                       f"{len(dims)} dimensions. Independent of how severe the miss is."),
            "limitations": [d["note"] for d in dims if d["score"] < 0.5]}


def _criticality(features, actual, forecast):
    """How operationally significant is this miss? (spec 18) -- miss size x queue volume.

    Bands are anchored on the ABSOLUTE contact gap WFM would have to cover, with the relative gap
    only able to lift a band. A 90-contact queue missing by 88 is real but is not the same
    operational problem as a 5,000-contact queue missing by 900, and adherence percentage alone
    would rank them the other way round.
    """
    gap = abs(actual - forecast) if (actual is not None and forecast is not None) else None
    typical = _num(_get(features, "data_quality", "typical_week_actual")) or \
        _num(_get(features, "forecast_response", "baselines", "recent_13_week_median_actual"))
    if gap is None:
        return {"level": None, "reason": "the contact gap cannot be measured"}

    relative = (gap / typical) if typical else None

    def band_from_absolute(g):
        if g >= CRITICAL_CONTACTS:
            return "Critical"
        if g >= HIGH_CONTACTS:
            return "High"
        if g >= MEDIUM_CONTACTS:
            return "Medium"
        return "Low"

    def band_from_relative(r):
        if r is None:
            return "Low"
        if r >= CRITICAL_RELATIVE:
            return "Critical"
        if r >= HIGH_RELATIVE:
            return "High"
        if r >= MEDIUM_RELATIVE:
            return "Medium"
        return "Low"

    absolute_band = band_from_absolute(gap)
    relative_band = band_from_relative(relative)
    # The absolute gap sets the floor; a large relative gap can lift it by one band, never more.
    order = list(reversed(CRITICALITIES))          # Low .. Critical
    lifted = min(order.index(absolute_band) + (1 if order.index(relative_band) >
                                               order.index(absolute_band) else 0),
                 len(order) - 1)
    level = order[lifted]
    return {
        "level": level,
        "contacts_gap": _rnd(gap),
        "typical_week_volume": _rnd(typical),
        "gap_as_share_of_typical_week": _rnd(relative, 3),
        "absolute_band": absolute_band,
        "relative_band": relative_band,
        "reason": (f"{_rnd(gap)} contacts {'above' if (actual or 0) > (forecast or 0) else 'below'} "
                   f"plan that WFM would need to cover"
                   + (f", against a typical week of {_rnd(typical)} "
                      f"({_rnd((relative or 0) * 100, 1)}% of a normal week)." if typical
                      else ".")),
        "note": ("Severity, not evidence strength -- deliberately independent of confidence. "
                 "The absolute gap sets the band; a large relative gap can lift it one step so a "
                 "small queue is not ignored, but cannot outrank a large absolute shortfall."),
    }


# ---------------------------------------------------------------------------
# 6. narration inputs -- the sentence and the ranked bullets the UI renders (spec 20, 21)
# ---------------------------------------------------------------------------
def _root_cause_sentence(cands, miss_category, actual, forecast, features):
    """One business sentence that names the forecasting problem, never a label like 'Demand Spike'."""
    primary = next((c for c in cands if c["evidence_class"] == "PRIMARY_DRIVER"), None)
    if primary is None:
        return ("The available evidence does not establish why the forecast missed for this week.")
    secondary = [c for c in cands if c["evidence_class"] == "SECONDARY_CONTRIBUTOR"
                 and not c.get("context_only")]
    lead = {
        "FORECAST_BASELINE_FAILURE": "Forecast entered the week below the level this week of the "
                                     "year normally brings",
        "FORECAST_RESPONSE_FAILURE": "Forecast did not react to a movement that was visible before "
                                     "the week",
        "CALENDAR_RESPONSE_FAILURE": "Forecast did not capture a calendar pattern this queue "
                                     "repeats every year",
        "DRIVER_RESPONSE_FAILURE": "Forecast did not follow an operational driver that leads "
                                   "demand for this queue",
        "DEMAND_EVENT": "Demand moved beyond anything the available signals foreshadowed",
        # COMPOUND_MISS is composed below from the mechanisms actually present -- a fixed sentence
        # would assert a response failure even when the second mechanism is an unforeseeable
        # demand event, which is a different diagnosis with a different action.
        "COMPOUND_MISS": None,
        "DATA_LIMITATION": "The evidence available is not sufficient to establish why the forecast "
                           "missed",
    }.get(miss_category, primary["headline"])

    # Each mechanism states its own half of a compound sentence, so the sentence can never claim a
    # response failure that the evidence did not find.
    clause = {
        "baseline": ("the forecast entered the week below the level this week of the year "
                     "normally brings"),
        "demand_event": "demand then moved further than any available signal foreshadowed",
        "response": "the plan did not react to a movement that was visible beforehand",
        "calendar": "a calendar pattern this queue repeats every year was not planned for",
        "asu": "the supported-base assumptions behind the plan did not hold",
        "data_quality": "the reported figure itself is not credible",
    }

    def clause_for(cand):
        if cand["key"].startswith("driver:"):
            return "an operational driver that leads demand here was not followed"
        text = clause.get(cand["key"])
        if text:
            return text
        return cand["headline"][0].lower() + cand["headline"][1:]

    if miss_category == "COMPOUND_MISS":
        parts = [clause_for(c) for c in ([primary] + secondary)[:2]]
        sentence = " and ".join(parts)
        return sentence[0].upper() + sentence[1:] + "."

    if miss_category == "FORECAST_BASELINE_FAILURE" and (actual or 0) < (forecast or 0):
        lead = "Forecast entered the week above the level this week of the year normally brings"
    if lead is None:
        lead = primary["headline"]
    if secondary:
        return f"{lead}, and {clause_for(secondary[0])}."
    return lead + "."


def _why_bullets(cands):
    """Ranked highest evidence first, each answering what / why it mattered / how it hit the plan."""
    out = []
    rank = 0
    for c in cands:
        if c["evidence_class"] in ("REJECTED",):
            continue
        rank += 1
        out.append({
            "rank": rank,
            "headline": c["headline"],
            "what_happened": c.get("what"),
            "why_it_mattered": c.get("why_it_mattered"),
            "forecast_mechanism": c.get("mechanism"),
            "evidence_class": c["evidence_class"],
            "evidence_ids": c.get("evidence_ids") or [],
            "cause_type": c.get("cause_type"),
            "resolution": c.get("resolution"),
            "contradictions": [x["statement"] for x in c.get("contradictions") or []],
        })
    return out


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------
def decide(features, actual, forecast, adherence, band=10.0):
    """The whole deterministic decision, ready for the payload and the response.

    Called BEFORE the model, so the model narrates decisions already made. `investigation_engine`
    then re-imposes `miss_category` and `evidence_class` on the assembled response, so a model that
    tries to override them cannot.
    """
    evidence = build_evidence_index(features, actual, forecast, adherence)
    miss_direction = _miss_direction(actual, forecast)
    cands = _candidates(features, actual, forecast, miss_direction)

    for c in cands:
        c.update(_resolve(c, features, miss_direction, cands))
    _classify(cands)

    miss_category, category_reason, category_ids = _miss_category(cands, features, actual, forecast)
    confidence = _confidence(cands, features, evidence)
    criticality = _criticality(features, actual, forecast)

    fr = features.get("forecast_response") or {}
    gran = features.get("data_granularity") or {}
    limitations = []
    if not (fr.get("miss_decomposition") or {}).get("available"):
        limitations.append((fr.get("miss_decomposition") or {}).get("reason"))
    if not (features.get("correlations") or {}).get("driver_decomposition", {}).get("available"):
        limitations.append((features.get("correlations") or {})
                           .get("driver_decomposition", {}).get("reason"))
    if gran.get("weekend_statement"):
        limitations.append(gran.get("weekend_statement"))
    for d in (features.get("lag_analysis") or {}).get("drivers") or []:
        if d.get("coverage") in ("sparse", "absent"):
            limitations.append(d.get("interpretation"))

    return {
        "version": "wfm-decision-1.0.0",
        "miss_direction": miss_direction,
        "miss_category": miss_category,
        "miss_category_reason": category_reason,
        "miss_category_evidence_ids": category_ids,
        "forecastability": (fr.get("forecastability") or {}).get("classification"),
        "forecastability_reason": (fr.get("forecastability") or {}).get("reason"),
        "root_cause_sentence": _root_cause_sentence(cands, miss_category, actual, forecast,
                                                    features),
        "why_bullets": _why_bullets(cands),
        "candidates": cands,
        "rejected": [{"headline": c["headline"], "cause_type": c.get("cause_type"),
                      "reason": "; ".join(x["statement"] for x in c.get("contradictions") or [])}
                     for c in cands if c["evidence_class"] == "REJECTED"],
        "confidence": confidence,
        "criticality": criticality,
        "evidence_index": evidence,
        "limitations": [x for x in limitations if x],
        "rules": {
            "primary_min_strength": PRIMARY_MIN_STRENGTH,
            "material_share": MATERIAL_SHARE,
            "compound_min_strength": COMPOUND_MIN_STRENGTH,
            "note": ("A gap between actual and forecast is never on its own sufficient to call a "
                     "forecast failure: a response mechanism requires a signal that existed before "
                     "the week AND has behaved repeatably for this queue."),
        },
    }
