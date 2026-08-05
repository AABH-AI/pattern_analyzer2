"""The decision engine (?mode=decision): Python investigates and ranks, the LLM only narrates.

Pipeline (mirrors the business's own investigation_engine.py order, but hypothesis selection
moves from the LLM into hypothesis_ranker.py):

    derive_wfm_features (deterministic, reused as-is from investigation_engine.py)
      -> hypothesis_ranker.rank      (NEW: scores every eligible cause, picks the winner)
      -> ONE narrator-only model call (writes the paragraph for the pre-decided winner)
      -> assemble                    (backward-compatible response shape, zero frontend change)

If no provider is reachable, the narrative is built from the ranker's own grounded evidence
templates -- it never fabricates and never blocks on the model being down, same guarantee the
other two engines already make.
"""
import json
import urllib.error

from rca_investigate import (
    _forecast_summary,
    _now,
    _observations_from_features,
    _slot_for_choice,
)

from . import business_report_generator as report
from . import hypothesis_ranker
from .common import CAUSE_TYPES, confidence_level
from .decision_prompts import DECISION_SYSTEM_PROMPT, build_user_payload
from .investigation_engine import derive_wfm_features
from .llm_client import chat_json, timeout_from_config

_TITLES = {
    "forecast_baseline_error": "Forecast Baseline Error",
    "systematic_forecast_bias": "Systematic Forecast Bias",
    "genuine_demand_event": "Genuine Demand Event",
    "volume_routing_shift": "Volume Routing Shift",
    "plan_restatement": "Forecast Plan Restatement",
    "installed_base_change": "Installed Base Change",
    "calendar_holiday_effect": "Calendar / Holiday Effect",
    "data_quality_issue": "Data Quality Issue",
    "inherited_from_higher_level": "Inherited From a Higher Level",
    "channel_migration": "Channel Migration",
}

# Deterministic fallback sentence per cause type, used only when no LLM is reachable. Each is
# one grounded, causal sentence built from evidence already in hand -- never a bare number dump,
# never a template the LLM would otherwise be asked to fill.
def _fallback_sentence(ctype, evidence_map, context):
    ev = evidence_map
    if ctype == "genuine_demand_event":
        return (f"Actual demand this week ({ev.get('actual')}) was far from this queue's usual "
                f"level (~{ev.get('actual_usual_level')}), while the forecast was about normal. "
                f"Because the forecast tracked the queue's history correctly, the miss is best "
                f"explained by a real change in customer demand rather than a forecasting error.")
    if ctype == "forecast_baseline_error":
        return (f"The forecast this week ({ev.get('forecast')}) was far from this queue's usual "
                f"level (~{ev.get('forecast_usual_level')}), while actual demand stayed normal. "
                f"Because the forecast itself moved and demand did not, the miss is best "
                f"explained by an incorrectly scaled forecast baseline.")
    if ctype == "systematic_forecast_bias":
        return (f"Over recent weeks this queue has typically run {ev.get('usual_actual')} actual "
                f"against {ev.get('usual_forecast')} forecast, missing in the same direction "
                f"{round((ev.get('share_same_direction') or 0) * 100)}% of the time. Because the "
                f"forecast has not been re-baselined to this queue's true running level, the same "
                f"gap recurred this week.")
    if ctype == "volume_routing_shift":
        return (f"{ev.get('peers_opposite_direction')} of {ev.get('peers_total')} similar queues "
                f"moved in the opposite direction this week. Because forecasts are generated "
                f"independently per queue name rather than at the combined-queue level, demand "
                f"shifting between them shows up as a miss on each one individually.")
    if ctype == "installed_base_change":
        return (f"The installed base moved to {ev.get('target_value')} against a usual level of "
                f"~{ev.get('history_mean')}. Because the forecast did not account for this change "
                f"in the warranty base, the resulting shift in expected contacts was not captured.")
    if ctype == "calendar_holiday_effect":
        return (f"This week carried {ev.get('holiday_count')} holiday(s), more than this queue "
                f"usually sees. Because the forecast baseline does not adjust for an unusual "
                f"holiday count, the calendar effect on customer contacts was not captured.")
    if ctype == "channel_migration":
        return ("Demand moved between channels within the same combined queue rather than the "
                "total changing. Because forecasts are generated independently per channel "
                "instead of at the combined-queue level, the shift produced an over-forecast on "
                "one channel and an under-forecast on another.")
    if ctype == "plan_restatement":
        return ("The forecast plan changed this week. Because the revised plan was not fully "
                "reconciled against the queue's recent actual demand, the change contributed to "
                "this week's miss.")
    if ctype == "data_quality_issue":
        return (f"This week's value ({ev.get('this_week_actual')}) is {ev.get('times_typical')}x "
                f"the typical week and does not resemble anything else in this queue's history. "
                f"Because a value this unusual is more likely an ingestion issue than a genuine "
                f"business event, it should be validated at source before being treated as real.")
    if ctype == "inherited_from_higher_level":
        return (f"The same miss is already visible one level up in the reporting hierarchy "
                f"(adherence {ev.get('adherence_pct')}%). Because a queue-level cause cannot "
                f"explain a miss the whole level above it shares, the cause is inherited rather "
                f"than specific to this queue.")
    return "The data most consistent with this week's miss was selected from the available evidence."


def _evidence_map(evidence_list):
    return {e.get("source_field"): e.get("value") for e in (evidence_list or []) if e.get("source_field")}


def _secondary_statement(entry, context):
    ctype = entry["cause_type"]
    ev_map = _evidence_map(entry["evidence"])
    title = _TITLES.get(ctype, ctype)
    sentence = _fallback_sentence(ctype, ev_map, context)
    return f"Also considered: {title.lower()}. {sentence}"


def _rejected_hypotheses(ranking):
    out = [{"hypothesis": _TITLES.get(r["cause_type"], r["cause_type"]), "reason_rejected": r["reason"]}
           for r in ranking["rejected"]]
    # The runners-up that WERE eligible but scored lower than the winner are also worth
    # recording as rejected -- with the actual reason being "weaker evidence", not "impossible".
    for r in ranking["ranked"][1:]:
        out.append({"hypothesis": _TITLES.get(r["cause_type"], r["cause_type"]),
                    "reason_rejected": f"Eligible but scored {r['score']} vs the winning cause's "
                                       f"{ranking['ranked'][0]['score']} -- weaker evidence."})
    return out


def investigate_decision(context_bundle, llm_cfg, wfm_context, model_choice=None, band=None):
    from .common import DEFAULT_BAND_PCT
    llm_cfg = llm_cfg or {}
    if band is None:
        band = ((context_bundle or {}).get("meta") or {}).get("band_threshold") or DEFAULT_BAND_PCT
    band = float(band)

    features, adherence = derive_wfm_features(context_bundle, wfm_context or {}, band)

    if isinstance(adherence, (int, float)) and abs(adherence) <= band:
        return report.not_investigated(adherence, band, features)

    ranking = hypothesis_ranker.rank(features)
    target = (context_bundle or {}).get("target") or {}
    key = target.get("key") or {}
    computed = target.get("computed") or {}
    context = {
        "forecast_name": key.get("Forecast_name"), "fiscal_week": key.get("Fiscal_Week"),
        "forecast": computed.get("forecast"), "actual": computed.get("actual"),
        "adherence_pct": round(adherence, 1) if isinstance(adherence, (int, float)) else None,
    }

    if not ranking["ranked"]:
        # Nothing was eligible at all -- every precondition failed. Still never says "not
        # enough data"; states the plainest fact available and flags it as unresolved.
        out = {
            "executive_summary": (f"No specific driver in the available data explains this "
                                  f"week's miss for {context['forecast_name']}."),
            "business_impact": "Undetermined without further data.",
            "cause_type": None, "confidence_score": None,
            "primary_root_cause": {"statement": "No eligible cause was found in the available "
                                                "evidence for this week.", "confidence": 0.2,
                                   "supporting_evidence": []},
            "secondary_contributors": [], "key_findings": _observations_from_features(
                features.get("base_features") or {}),
            "reasoning_narrative": [],
            "rejected_hypotheses": _rejected_hypotheses(ranking),
            "missing_information": [r["reason"] for r in ranking["rejected"]],
            "forecast_summary": _forecast_summary(computed),
        }
        return report.back_compat(out, features.get("base_features") or {})

    winner = ranking["ranked"][0]
    winner_ctype = winner["cause_type"]
    confidence_pct = round(winner["score"] * 100)
    conf_level = confidence_level(confidence_pct)

    secondary = ranking["ranked"][1:3]
    payload = build_user_payload(
        context, winner_ctype, winner["evidence"], confidence_pct, conf_level,
        [{"cause_type": r["cause_type"], "reason": f"scored {r['score']} vs the winner's {winner['score']}"}
         for r in secondary] + ranking["rejected"][:3])

    narrative = None
    failures = []
    if model_choice and model_choice.get("model"):
        slot = _slot_for_choice(model_choice, llm_cfg)
        slots = [slot] if slot else []
    else:
        slots = [llm_cfg.get(n) or {} for n in ("primary", "secondary")]
        slots = [s for s in slots if s.get("provider") and s.get("api_key")]

    from rca_investigate import PROVIDER_ENDPOINTS, DEFAULT_MODELS
    timeout = timeout_from_config(llm_cfg)
    for slot in slots:
        endpoint = slot.get("endpoint") or PROVIDER_ENDPOINTS.get(slot.get("provider"))
        model = slot.get("model") or DEFAULT_MODELS.get(slot.get("provider"))
        if not endpoint:
            continue
        messages = [{"role": "system", "content": DECISION_SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(payload, default=str)}]
        try:
            narrative = chat_json(endpoint, slot["api_key"], model, messages, timeout=timeout)
            break
        except Exception as e:
            failures.append(f"{slot.get('provider')}/{model}: {e}")
            continue

    engine_tag = "wfm-decision-llm"
    if not narrative or not isinstance(narrative, dict) or not narrative.get("executive_summary"):
        ev_map = _evidence_map(winner["evidence"])
        narrative = {
            "executive_summary": _fallback_sentence(winner_ctype, ev_map, context),
            "business_impact": "Review this queue's forecast inputs with the planning team.",
            "recommended_action": "Recalibrate the forecast for this queue against its recent actual demand.",
        }
        engine_tag = "wfm-decision-deterministic-fallback"

    out = {
        "executive_summary": narrative.get("executive_summary", ""),
        "business_impact": narrative.get("business_impact", ""),
        "cause_type": winner_ctype,
        "confidence_score": winner["score"],
        "primary_root_cause": {
            "statement": narrative.get("executive_summary", ""),
            "confidence": winner["score"],
            "supporting_evidence": winner["evidence"],
        },
        "secondary_contributors": [
            {"statement": _secondary_statement(r, context), "confidence": r["score"],
             "supporting_evidence": r["evidence"]}
            for r in secondary
        ],
        "key_findings": _observations_from_features(features.get("base_features") or {}),
        # Deliberately NOT populated with a "runner-up scored lower" summary here --
        # secondary_contributors already covers the runners-up with full grounded sentences.
        # Populating both was tried and produced exactly the cross-field duplication this
        # session spent itself fixing elsewhere: two bullets describing the same fact in
        # different words. Left empty unless the ladder/channel-migration narrative is
        # genuinely additional content (below), matching the pattern already proven on main.
        "reasoning_narrative": [],
        "rejected_hypotheses": _rejected_hypotheses(ranking),
        "recommended_action": narrative.get("recommended_action", ""),
        "forecast_improvement_recommendations": (
            [narrative["recommended_action"]] if narrative.get("recommended_action") else []),
        "investigation_ladder_available": bool((features.get("investigation_ladder") or {}).get("available")),
        "derived_features": features,
        "investigation_meta": {"engine": engine_tag,
                              "provider": (slots[0].get("provider") if slots else None),
                              "hypothesis_scores": ranking["hypothesis_scores"],
                              "generated_at": _now()},
        "forecast_summary": _forecast_summary(computed),
    }

    ladder = features.get("investigation_ladder") or {}
    out["investigation_trail"] = {
        "levels_checked": [lv.get("level") for lv in (ladder.get("levels") or [])],
        "inherited_from": ladder.get("inherited_from") or "",
        "narrative": (ladder.get("note") if ladder.get("available") else "") or "",
    }
    siblings = features.get("channel_siblings") or {}
    out["channel_migration"] = {
        "detected": bool(siblings.get("migration_detected")),
        "narrative": siblings.get("note") or "",
        "gaining_channels": siblings.get("gaining_channels") or [],
        "losing_channels": siblings.get("losing_channels") or [],
        "grouped_by": siblings.get("grouped_by"),
        "is_cqn_proxy": siblings.get("is_cqn_proxy"),
        "combined_queue_names": siblings.get("combined_queue_names") or [],
        "cqn_note": siblings.get("cqn_note"),
        "detail": siblings,
    }
    out["technical_metrics"] = report.technical_metrics(features)
    missing = []
    corr = (features.get("correlations") or {}).get("driver_decomposition") or {}
    if not corr.get("available"):
        missing.append(corr.get("reason") or "Driver decomposition unavailable for this queue.")
    if not (features.get("channel_siblings") or {}).get("available"):
        missing.append((features.get("channel_siblings") or {}).get("reason")
                       or "Channel-sibling comparison unavailable for this locality.")
    out["missing_information"] = missing

    return report.back_compat(out, features.get("base_features") or {})
