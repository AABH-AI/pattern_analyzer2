"""The decision engine (?mode=decision): Python investigates and ranks, the LLM only narrates.

Pipeline (mirrors the business's own investigation_engine.py order, but hypothesis selection
moves from the LLM into hypothesis_ranker.py):

    derive_wfm_features (deterministic, reused as-is from investigation_engine.py)
      -> hypothesis_ranker.rank      (scores every eligible cause, picks the winner)
      -> ONE narrator-only model call (writes up the pre-decided winner)
      -> assemble                    (backward-compatible response shape, zero frontend change,
                                       PLUS a new investigation_summary block the console prefers
                                       when present -- see IMP_DOCS/decision-engine-design-critique.md)

SECOND REVISION (same session, live-review feedback): the first version put the winning cause's
full paragraph, the runners-up, AND everything ruled out into one flat "Root Cause" bullet list --
reviewed as "five competing root causes" rather than one investigation with a conclusion. This
version builds a genuinely structured `investigation_summary`: ONE root_cause sentence, a
`why_we_believe` evidence list, `contributing_factors` (ONLY causes materially close to the
winner's score -- not every eligible cause), and `ruled_out` (everything else, one line each).
Also fixes a live-caught contradiction: the forecast_baseline_error fallback previously claimed
actual demand "stayed normal" unconditionally, which was false whenever actual was ALSO elevated.

If no provider is reachable, the narrative is built from the ranker's own grounded evidence
templates -- it never fabricates and never blocks on the model being down, same guarantee the
other two engines already make.
"""
import json

from rca_investigate import (
    DEFAULT_MODELS,
    PROVIDER_ENDPOINTS,
    _forecast_summary,
    _now,
    _observations_from_features,
    _slot_for_choice,
)

from . import business_report_generator as report
from . import hypothesis_ranker
from .common import DEFAULT_BAND_PCT, confidence_level
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

# A cause only becomes a listed "contributing factor" if its score is within this margin of the
# winner's -- otherwise it's just noise that dilutes the ONE conclusion the report is supposed to
# reach. Anything else eligible, and anything ruled out on precondition, goes into `ruled_out`
# as a single terse line instead of a competing paragraph.
_MATERIALITY_MARGIN = 0.15
_MAX_CONTRIBUTING = 2

# Terse "ruled out" phrasing for causes whose PRECONDITION failed (matches the business's own
# skeptic.py reasons, reworded as a one-line dismissal rather than a paragraph).
_RULED_OUT_INELIGIBLE = {
    "plan_restatement": "No projection plan change this week.",
    "calendar_holiday_effect": "No unusual holiday impact this week.",
    "installed_base_change": "No material installed-base change this week.",
    "volume_routing_shift": "No similar queue moved in the opposite direction this week.",
    "systematic_forecast_bias": "This queue's misses have no consistent standing direction.",
    "genuine_demand_event": "Actual demand was not unusual against its own history.",
    "forecast_baseline_error": "The forecast itself was not unusual against its own history.",
    "channel_migration": "No evidence of channel migration within the Combined Queue.",
    "data_quality_issue": "No data-quality concerns with this week's figure.",
    "inherited_from_higher_level": "No higher level shows the same miss in the same direction.",
}


# Deterministic fallback sentence per cause type, used only when no LLM is reachable, AND as the
# basis for the `why_we_believe` bullets (LLM or fallback both draw on the same grounded facts).
# Each states a fact plus its meaning -- never an unconditional claim the evidence might
# contradict (the "actual behaved normally" bug: that claim is now OMITTED rather than asserted,
# since forecast_baseline_error winning does not guarantee actual was normal too).
def _fallback_bullets(ctype, ev):
    if ctype == "genuine_demand_event":
        return [
            f"Actual demand this week ({ev.get('actual')}) was far from this queue's usual "
            f"level (~{ev.get('actual_usual_level')}), while the forecast stayed close to normal.",
            "This points to a real change in customer demand rather than a forecasting error.",
        ]
    if ctype == "forecast_baseline_error":
        return [
            f"The forecast this week ({ev.get('forecast')}) was far from this queue's usual "
            f"level (~{ev.get('forecast_usual_level')}).",
            "This indicates the forecast baseline itself was incorrectly scaled for this week.",
        ]
    if ctype == "systematic_forecast_bias":
        return [
            f"Over recent weeks this queue has typically run {ev.get('usual_actual')} actual "
            f"against {ev.get('usual_forecast')} forecast.",
            f"It has missed in the same direction {round((ev.get('share_same_direction') or 0) * 100)}% "
            f"of the time, indicating a standing bias rather than a one-off.",
        ]
    if ctype == "volume_routing_shift":
        return [
            f"{ev.get('peers_opposite_direction')} of {ev.get('peers_total')} similar queues "
            f"moved in the opposite direction this week.",
            "This is consistent with demand shifting between queues rather than changing overall.",
        ]
    if ctype == "installed_base_change":
        return [
            f"The installed base moved to {ev.get('target_value')} against a usual level of "
            f"~{ev.get('history_mean')}.",
            "This change in the warranty base was not reflected in the forecast.",
        ]
    if ctype == "calendar_holiday_effect":
        return [f"This week carried {ev.get('holiday_count')} holiday(s), more than this queue "
                f"usually sees, which the forecast baseline does not adjust for."]
    if ctype == "channel_migration":
        return ["Demand moved between channels within the same combined queue rather than the "
                "total changing, while forecasts are generated independently per channel."]
    if ctype == "plan_restatement":
        return ["The forecast plan changed this week and was not fully reconciled against "
                "recent actual demand."]
    if ctype == "data_quality_issue":
        return [f"This week's value ({ev.get('this_week_actual')}) is {ev.get('times_typical')}x "
                f"the typical week and does not resemble anything else in this queue's history."]
    if ctype == "inherited_from_higher_level":
        return [f"The same miss is already visible one level up in the reporting hierarchy "
                f"(adherence {ev.get('adherence_pct')}%), so a queue-level cause cannot explain it."]
    return ["The available evidence most consistently points to this cause."]


def _fallback_root_cause(ctype, ev):
    title = _TITLES.get(ctype, ctype)
    bullets = _fallback_bullets(ctype, ev)
    return f"{title}: {bullets[0]}"


def _evidence_map(evidence_list):
    return {e.get("source_field"): e.get("value") for e in (evidence_list or []) if e.get("source_field")}


def _rejected_hypotheses(ranking, contributing_types):
    """Legacy field (kept for other UI paths that still read it) -- everything not the winner
    and not a listed contributing factor."""
    out = [{"hypothesis": _TITLES.get(r["cause_type"], r["cause_type"]), "reason_rejected": r["reason"]}
           for r in ranking["rejected"]]
    for r in ranking["ranked"][1:]:
        if r["cause_type"] in contributing_types:
            continue
        out.append({"hypothesis": _TITLES.get(r["cause_type"], r["cause_type"]),
                    "reason_rejected": f"Eligible but scored {r['score']} vs the winning cause's "
                                       f"{ranking['ranked'][0]['score']} -- weaker evidence."})
    return out


def _ruled_out_lines(ranking, contributing_types, winner_type):
    """The terse 'What we ruled out' list -- one line per cause that is NOT the winner and NOT
    a material contributing factor. Precondition-failures get their skeptic-derived reason;
    eligible-but-weak causes get a one-line 'considered but weaker' note."""
    lines = []
    for r in ranking["rejected"]:
        phrase = _RULED_OUT_INELIGIBLE.get(r["cause_type"])
        if phrase:
            lines.append(phrase)
    for r in ranking["ranked"]:
        if r["cause_type"] == winner_type or r["cause_type"] in contributing_types:
            continue
        lines.append(f"{_TITLES.get(r['cause_type'], r['cause_type'])} was considered but the "
                     f"evidence was materially weaker than the primary cause.")
    return lines


def investigate_decision(context_bundle, llm_cfg, wfm_context, model_choice=None, band=None):
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
        summary = {
            "root_cause": f"No specific driver in the available data explains this week's miss "
                          f"for {context['forecast_name']}.",
            "confidence_pct": 20, "confidence_level": "Low",
            "why_we_believe": [], "contributing_factors": [],
            "ruled_out": [r["reason"] for r in ranking["rejected"]],
            "business_impact": "Undetermined without further data.",
            "recommended_action": "Gather additional context before drawing a conclusion.",
        }
        out = {
            "executive_summary": summary["root_cause"],
            "cause_type": None, "confidence_score": None,
            "primary_root_cause": {"statement": summary["root_cause"], "confidence": 0.2,
                                   "supporting_evidence": []},
            "secondary_contributors": [], "key_findings": _observations_from_features(
                features.get("base_features") or {}),
            "reasoning_narrative": [],
            "rejected_hypotheses": [{"hypothesis": r["cause_type"], "reason_rejected": r["reason"]}
                                    for r in ranking["rejected"]],
            "missing_information": [],
            "investigation_summary": summary,
            "forecast_summary": _forecast_summary(computed),
        }
        return report.back_compat(out, features.get("base_features") or {})

    winner = ranking["ranked"][0]
    winner_ctype = winner["cause_type"]
    confidence_pct = round(winner["score"] * 100)
    conf_level = confidence_level(confidence_pct)

    contributing = [r for r in ranking["ranked"][1:]
                    if r["score"] >= winner["score"] - _MATERIALITY_MARGIN][:_MAX_CONTRIBUTING]
    contributing_types = {r["cause_type"] for r in contributing}

    payload = build_user_payload(
        context, winner_ctype, winner["evidence"], confidence_pct, conf_level,
        [{"cause_type": r["cause_type"], "reason": f"scored {r['score']} vs the winner's {winner['score']}"}
         for r in ranking["ranked"][1:]] + ranking["rejected"])

    narrative = None
    if model_choice and model_choice.get("model"):
        slot = _slot_for_choice(model_choice, llm_cfg)
        slots = [slot] if slot else []
    else:
        slots = [llm_cfg.get(n) or {} for n in ("primary", "secondary")]
        slots = [s for s in slots if s.get("provider") and s.get("api_key")]

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
            if narrative and isinstance(narrative, dict) and narrative.get("root_cause"):
                break
            narrative = None
        except Exception:
            continue

    engine_tag = "wfm-decision-llm"
    ev_map = _evidence_map(winner["evidence"])
    if not narrative:
        narrative = {
            "root_cause": _fallback_root_cause(winner_ctype, ev_map),
            "why_we_believe": _fallback_bullets(winner_ctype, ev_map),
            "business_impact": "Review this queue's forecast inputs with the planning team.",
            "recommended_action": "Recalibrate the forecast for this queue against its recent actual demand.",
        }
        engine_tag = "wfm-decision-deterministic-fallback"

    why_we_believe = narrative.get("why_we_believe") or _fallback_bullets(winner_ctype, ev_map)
    contributing_lines = [
        f"{_TITLES.get(r['cause_type'], r['cause_type'])}: {_fallback_bullets(r['cause_type'], _evidence_map(r['evidence']))[0]}"
        for r in contributing
    ]
    ruled_out = _ruled_out_lines(ranking, contributing_types, winner_ctype)

    summary = {
        "root_cause": narrative.get("root_cause", ""),
        "confidence_pct": confidence_pct, "confidence_level": conf_level,
        "why_we_believe": why_we_believe,
        "contributing_factors": contributing_lines,
        "ruled_out": ruled_out,
        "business_impact": narrative.get("business_impact", ""),
        "recommended_action": narrative.get("recommended_action", ""),
    }

    out = {
        "executive_summary": narrative.get("root_cause", ""),
        "business_impact": narrative.get("business_impact", ""),
        "cause_type": winner_ctype,
        "confidence_score": winner["score"],
        "primary_root_cause": {
            "statement": narrative.get("root_cause", ""),
            "confidence": winner["score"],
            "supporting_evidence": winner["evidence"],
        },
        "secondary_contributors": [
            {"statement": contributing_lines[i] if i < len(contributing_lines) else "",
             "confidence": r["score"], "supporting_evidence": r["evidence"]}
            for i, r in enumerate(contributing)
        ],
        "key_findings": _observations_from_features(features.get("base_features") or {}),
        "reasoning_narrative": [],
        "rejected_hypotheses": _rejected_hypotheses(ranking, contributing_types),
        "forecast_improvement_recommendations": (
            [narrative["recommended_action"]] if narrative.get("recommended_action") else []),
        "investigation_summary": summary,
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
