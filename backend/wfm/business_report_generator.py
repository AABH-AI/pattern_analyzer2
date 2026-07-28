"""Turn findings into the report the console renders.

Also owns BACK-COMPATIBILITY: every key the existing UI reads is populated from the ranked
list, so a WFM report renders in the current console with no frontend change.
  rank 1  -> primary_root_cause / cause_type / confidence_score
  rank 2+ -> secondary_contributors
  rejected skeptic challenges -> rejected_hypotheses
  each cause's action -> forecast_improvement_recommendations
"""
from rca_investigate import _observations_from_features

from .common import confidence_level, rnd

RESPONSE_DEFAULTS = {
    "executive_summary": "",
    "kpi_status": {},
    "business_impact": "",
    "ranked_root_causes": [],
    "skeptic_review": [],
    "investigation_trail": {},
    "channel_migration": {},
    "technical_metrics": [],
    "missing_information": [],
}


def kpi_status(adherence, band):
    """Arithmetic. Always overwrites whatever the model said."""
    ok = isinstance(adherence, (int, float))
    return {
        "metric": "Forecast Adherence",
        "adherence_pct": rnd(adherence),
        "threshold_pct": band,
        "breached": bool(ok and abs(adherence) > band),
        "direction": (None if not ok else ("under_forecast" if adherence < 0 else "over_forecast")),
    }


def normalise_causes(causes):
    """Enforce rank order, cap at 5, repair confidence."""
    out = [c for c in (causes or []) if isinstance(c, dict)][:5]
    for i, c in enumerate(out, start=1):
        c["rank"] = i
        pct = c.get("confidence_pct")
        if isinstance(pct, float) and 0 < pct <= 1:        # model gave 0-1 not 0-100
            pct = round(pct * 100)
        c["confidence_pct"] = pct if isinstance(pct, (int, float)) else 0
        # The High/Medium/Low bands are defined, so derive the label rather than trusting
        # the model's -- it returned "Medium" for 80%, which contradicts its own scale.
        c["confidence_level"] = confidence_level(c["confidence_pct"])
    return out


def technical_metrics(features):
    """The collapsed technical section -- where jargon is allowed to live."""
    rows = []
    for p in ((features.get("base_features") or {}).get("proof") or []):
        rows.append({"label": p.get("label"), "value": p.get("this_week")})
    corr = (features.get("correlations") or {}).get("driver_decomposition") or {}
    if corr.get("available"):
        rows += [
            {"label": "Miss attributed to warranty base", "value": corr.get("warranty_base_effect")},
            {"label": "Miss attributed to contacts per unit", "value": corr.get("contacts_per_unit_effect")},
            {"label": "Warranty-base share of the miss", "value": corr.get("warranty_base_share")},
            {"label": "Decomposition reconciles to total miss", "value": corr.get("reconciles")},
        ]
    for r in ((features.get("correlations") or {}).get("relationships") or {}).get("retained", []):
        rows.append({"label": f"Relationship strength: {r.get('driver')} vs demand",
                     "value": r.get("technical_strength")})
    ladder = features.get("investigation_ladder") or {}
    for lv in (ladder.get("levels") or []):
        rows.append({"label": f"Adherence at {lv.get('level')} level", "value": lv.get("adherence_pct")})
    return rows


def back_compat(result, base_features):
    """Fill the ORIGINAL response keys so the existing console renders this unchanged."""
    ranked = result.get("ranked_root_causes") or []
    if ranked:
        top = ranked[0]
        result.setdefault("primary_root_cause", {
            "statement": top.get("explanation") or top.get("title") or "",
            "confidence": (top.get("confidence_pct") or 0) / 100.0,
            "supporting_evidence": top.get("evidence") or [],
        })
        result.setdefault("secondary_contributors", [{
            "statement": r.get("explanation") or r.get("title") or "",
            "confidence": (r.get("confidence_pct") or 0) / 100.0,
            "supporting_evidence": r.get("evidence") or [],
        } for r in ranked[1:]])
        if result.get("confidence_score") is None:
            result["confidence_score"] = (top.get("confidence_pct") or 0) / 100.0
        if not result.get("cause_type"):
            result["cause_type"] = top.get("cause_type")

    # Must be set even when there are NO ranked causes (the within-band response), otherwise
    # the existing UI reads an undefined key. Caught by results/run_validation.py check V7.
    result.setdefault("secondary_contributors", [])
    result.setdefault("key_findings", _observations_from_features(base_features or {}))
    result.setdefault("supporting_evidence", (ranked[0].get("evidence") if ranked else []) or [])
    result.setdefault("reasoning_narrative", result.get("executive_summary") or "")
    result.setdefault("rejected_hypotheses", [
        {"hypothesis": s.get("cause") or s.get("challenge") or "",
         "reason_rejected": s.get("reason") or ""}
        for s in (result.get("skeptic_review") or []) if s.get("verdict") == "rejected"
    ])
    result.setdefault("historical_comparison", {})
    result.setdefault("forecast_improvement_recommendations",
                      [r.get("recommended_action") for r in ranked if r.get("recommended_action")])
    result.setdefault("forecast_summary", {})
    result.setdefault("cause_type", None)
    result.setdefault("derived_features", {})
    return result


def not_investigated(adherence, band, features):
    """Within the band the business rule forbids investigating."""
    shown = rnd(adherence) if isinstance(adherence, (int, float)) else "not scoreable"
    return back_compat({
        "executive_summary": (f"Forecast Adherence for this queue-week is {shown}%, inside the "
                              f"acceptable +/-{band}% threshold. No investigation was run."),
        "kpi_status": kpi_status(adherence, band),
        "business_impact": "None - the week performed within the accepted tolerance.",
        "ranked_root_causes": [],
        "skeptic_review": [],
        "investigation_trail": {"levels_checked": [], "inherited_from": "",
                               "narrative": "Not investigated: within threshold."},
        "channel_migration": {"detected": False, "narrative": "", "gaining_channels": [],
                              "losing_channels": []},
        "technical_metrics": [],
        "missing_information": [],
        "derived_features": features,
        "confidence_score": 1.0,
        "primary_root_cause": {"statement": "Within threshold - not investigated.",
                               "confidence": 1.0, "supporting_evidence": []},
        "investigation_meta": {"engine": "wfm-not-investigated"},
    }, features.get("base_features") or {})
