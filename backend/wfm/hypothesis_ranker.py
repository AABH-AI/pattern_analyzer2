"""The Evidence Aggregator / Hypothesis Ranker.

Root cause of the "recipe" complaint (see IMP_DOCS / yes.md): the LLM was asked to
simultaneously investigate, rank hypotheses, score confidence, AND write the narrative in one
pass. Under that load it falls back to copying its own best-scoring example verbatim, sentence
by sentence, only swapping the numbers -- which is exactly what got reported as "every output
reads the same".

This module does the investigating, ranking, and scoring in Python -- deterministically, from
data already computed by the other wfm/ modules (skeptic.PRECONDITIONS, forecast_sanity,
chronic_bias, peer_divergence, installed_base, holiday, investigation_ladder, channel_siblings,
correlations, data_quality, statistical_evidence). The LLM's only remaining job (see
decision_engine.py) is to narrate the winner in business language -- it never decides which
cause wins.

Every score is a plain float in [0, 1], built from a magnitude already present in `features` --
never a new statistic invented here. Preconditions and their "why not" text are reused from
skeptic.py rather than duplicated, so both engines agree on what is even possible.
"""
from .common import CAUSE_TYPES
from .skeptic import PRECONDITIONS

# Two cause types the business has flagged as ALWAYS taking priority when their precondition
# holds, regardless of magnitude -- both are existing prompt rules turned into fixed scores
# rather than something for an LLM to weigh against competing evidence:
#   - data_quality_issue: "rank data_quality_issue FIRST" when DATA_QUALITY.suspect is true.
#   - inherited_from_higher_level: "a queue-level cause cannot explain a miss the whole region
#     shares" -- the investigation ladder already proved this arithmetically.
_FIXED_PRIORITY_SCORE = {
    "data_quality_issue": 0.97,
    "inherited_from_higher_level": 0.93,
}

# plan_restatement is real and its precondition can hold, but the business rule (see
# prompts.py "NO ROUTINE PROJECTION PLAN CITATIONS") is that a routine monthly plan update is
# NOT evidence of a cause on its own -- there is no materiality signal computed for it anywhere
# in this codebase, only a boolean "changed". Keep it eligible (so the model sees it was
# considered) but never let it win by default magnitude alone.
_DAMPENED_SCORE_CAP = {"plan_restatement": 0.45}


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def _z_to_score(z, saturate_at=4.0, floor=0.35):
    """Turn a z-score-like magnitude into a confidence in [floor, 1.0]. Saturates so an
    already-extreme value doesn't need to be infinitely more extreme to read as 'certain'."""
    if z is None:
        return floor
    return _clamp(floor + (1.0 - floor) * (abs(z) / saturate_at))


def _score_forecast_baseline_error(features):
    fs = (features.get("base_features") or {}).get("forecast_sanity") or {}
    return _z_to_score(fs.get("forecast_z_vs_own_history"))


def _score_genuine_demand_event(features):
    fs = (features.get("base_features") or {}).get("forecast_sanity") or {}
    return _z_to_score(fs.get("actual_z_vs_own_history"))


def _score_systematic_forecast_bias(features):
    ch = (features.get("base_features") or {}).get("chronic_bias") or {}
    share = ch.get("share_same_direction")
    base = _clamp(0.35 + 0.55 * (share if isinstance(share, (int, float)) else 0.5))
    # Statistical evidence (13-week bias) reinforces or tempers it when available.
    se = ((features.get("statistical_evidence") or {}).get("metrics") or {}).get("accuracy_recent") or {}
    if se.get("bias_material"):
        base = _clamp(base + 0.1)
    return base


def _score_volume_routing_shift(features):
    pd = (features.get("base_features") or {}).get("peer_divergence") or {}
    total, opp = pd.get("peers_total") or 0, pd.get("peers_opposite_direction") or 0
    ratio = (opp / total) if total else 0.0
    return _clamp(0.35 + 0.6 * ratio)


def _score_installed_base_change(features):
    ib = (features.get("base_features") or {}).get("installed_base") or {}
    score = _z_to_score(ib.get("z_score"))
    corr = (features.get("correlations") or {}).get("driver_decomposition") or {}
    if corr.get("available") and (corr.get("warranty_base_share") or 0) >= 0.5:
        score = _clamp(score + 0.1)
    return score


def _score_calendar_holiday_effect(features):
    hol = (features.get("base_features") or {}).get("holiday") or {}
    return _z_to_score(hol.get("z_score"))


def _score_channel_migration(features):
    cs = features.get("channel_siblings") or {}
    offset = cs.get("offset_share")
    if not isinstance(offset, (int, float)):
        return 0.5
    return _clamp(0.4 + 0.6 * offset)


def _score_plan_restatement(features):
    return _DAMPENED_SCORE_CAP["plan_restatement"]


_SCORERS = {
    "forecast_baseline_error": _score_forecast_baseline_error,
    "genuine_demand_event": _score_genuine_demand_event,
    "systematic_forecast_bias": _score_systematic_forecast_bias,
    "volume_routing_shift": _score_volume_routing_shift,
    "installed_base_change": _score_installed_base_change,
    "calendar_holiday_effect": _score_calendar_holiday_effect,
    "channel_migration": _score_channel_migration,
    "plan_restatement": _score_plan_restatement,
}


# Grounded, real-number evidence per cause type. Every value here is read straight out of
# `features` -- nothing computed fresh, nothing invented. This is what the LLM receives instead
# of the full DERIVED_FEATURES/TEMPORAL/etc. dump: a short, pre-digested evidence list for
# exactly the hypothesis it needs to explain.
def _evidence_for(ctype, features):
    bf = features.get("base_features") or {}
    ev = []
    if ctype == "forecast_baseline_error":
        fs = bf.get("forecast_sanity") or {}
        # source_field keys here MUST match what decision_engine._fallback_sentence() looks up
        # for this cause type -- kept as plain readable names, not raw column names, since
        # they double as both the evidence-chip label key and the fallback-template key.
        ev = [{"text": "forecast this week vs its own usual level", "source_field": "forecast",
               "value": fs.get("forecast")},
              {"text": "usual forecast level (13-week)", "source_field": "forecast_usual_level",
               "value": fs.get("forecast_usual_level")}]
    elif ctype == "genuine_demand_event":
        fs = bf.get("forecast_sanity") or {}
        ev = [{"text": "actual demand this week vs its own usual level", "source_field": "actual",
               "value": fs.get("actual")},
              {"text": "usual actual level (13-week)", "source_field": "actual_usual_level",
               "value": fs.get("actual_usual_level")}]
    elif ctype == "systematic_forecast_bias":
        ch = bf.get("chronic_bias") or {}
        ev = [{"text": "usual actual level recently", "source_field": "usual_actual", "value": ch.get("usual_actual")},
              {"text": "usual forecast level recently", "source_field": "usual_forecast", "value": ch.get("usual_forecast")},
              {"text": "share of recent weeks missing the same direction", "source_field": "share_same_direction",
               "value": ch.get("share_same_direction")}]
    elif ctype == "volume_routing_shift":
        pd = bf.get("peer_divergence") or {}
        ev = [{"text": "similar queues moving the opposite direction this week", "source_field": "peers_opposite_direction",
               "value": pd.get("peers_opposite_direction")},
              {"text": "similar queues compared", "source_field": "peers_total", "value": pd.get("peers_total")}]
    elif ctype == "installed_base_change":
        ib = bf.get("installed_base") or {}
        ev = [{"text": f"{ib.get('field')} this week", "source_field": "target_value", "value": ib.get("target_value")},
              {"text": f"{ib.get('field')} usual level", "source_field": "history_mean", "value": ib.get("history_mean")}]
        corr = (features.get("correlations") or {}).get("driver_decomposition") or {}
        if corr.get("available"):
            ev.append({"text": "share of the miss attributed to the warranty base",
                       "source_field": "warranty_base_share", "value": corr.get("warranty_base_share")})
    elif ctype == "calendar_holiday_effect":
        hol = bf.get("holiday") or {}
        ev = [{"text": "holidays this week", "source_field": "holiday_count", "value": hol.get("holiday_count")}]
    elif ctype == "channel_migration":
        cs = features.get("channel_siblings") or {}
        ev = [{"text": d.get("channel_label") or d.get("channel"), "source_field": "channel_delta",
               "value": d.get("change")} for d in (cs.get("per_channel") or [])[:5]]
    elif ctype == "plan_restatement":
        ev = [{"text": "forecast plan changed this week", "source_field": "plan_restatement.changed", "value": True}]
    elif ctype == "data_quality_issue":
        dq = features.get("data_quality") or {}
        ev = [{"text": "actual demand this week", "source_field": "this_week_actual", "value": dq.get("this_week_actual")},
              {"text": "typical week (median)", "source_field": "typical_week_actual", "value": dq.get("typical_week_actual")},
              {"text": "times the typical week", "source_field": "times_typical", "value": dq.get("times_typical")}]
    elif ctype == "inherited_from_higher_level":
        ladder = features.get("investigation_ladder") or {}
        levels = ladder.get("levels") or []
        inherited_level = next((lv for lv in levels if lv.get("level") == ladder.get("inherited_from")), None)
        if inherited_level:
            ev = [{"text": f"{inherited_level.get('level')} adherence this week", "source_field": "adherence_pct",
                   "value": inherited_level.get("adherence_pct")},
                  {"text": f"{inherited_level.get('level')} actual offered", "source_field": "actual_offered",
                   "value": inherited_level.get("actual_offered")},
                  {"text": f"{inherited_level.get('level')} forecast offered", "source_field": "fcst_offered",
                   "value": inherited_level.get("fcst_offered")}]
    return [e for e in ev if e.get("value") is not None]


def rank(features):
    """The public entry point. Returns every eligible cause type, scored and sorted, with the
    winner first and every rejection reason for the ones that aren't eligible at all.

    Shape:
      {
        "winner": "genuine_demand_event",
        "hypothesis_scores": {"genuine_demand_event": 0.91, ...},   # eligible only
        "ranked": [{"cause_type", "score", "evidence": [...]}, ...],  # eligible, sorted desc
        "rejected": [{"cause_type", "reason"}, ...],                  # precondition failed
      }
    """
    ranked, rejected = [], []
    for ctype in CAUSE_TYPES:
        predicate, why_not = PRECONDITIONS[ctype]
        try:
            eligible = bool(predicate(features))
        except Exception:
            eligible = False
        if not eligible:
            rejected.append({"cause_type": ctype, "reason": why_not})
            continue
        if ctype in _FIXED_PRIORITY_SCORE:
            score = _FIXED_PRIORITY_SCORE[ctype]
        else:
            scorer = _SCORERS.get(ctype)
            score = scorer(features) if scorer else 0.5
        ranked.append({
            "cause_type": ctype,
            "score": round(score, 3),
            "evidence": _evidence_for(ctype, features),
        })

    ranked.sort(key=lambda r: r["score"], reverse=True)
    winner = ranked[0]["cause_type"] if ranked else None
    return {
        "winner": winner,
        "hypothesis_scores": {r["cause_type"]: r["score"] for r in ranked},
        "ranked": ranked,
        "rejected": rejected,
    }
