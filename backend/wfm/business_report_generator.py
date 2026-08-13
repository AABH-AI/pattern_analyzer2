"""Turn findings into the report the console renders.

Also owns BACK-COMPATIBILITY: every key the existing UI reads is populated from the ranked
list, so a WFM report renders in the current console with no frontend change.
  rank 1  -> primary_root_cause / cause_type / confidence_score
  rank 2+ -> secondary_contributors
  rejected skeptic challenges -> rejected_hypotheses
  each cause's action -> forecast_improvement_recommendations

...and the LANGUAGE GUARD. The business prompt forbids statistics vocabulary in business-facing
text ("Avoid phrases like Correlation / Regression / Outlier / Pearson / Z-score / SHAP /
Isolation Forest"). Asking the model is not enough: a live NVIDIA run produced the executive
summary "...the actual figure is an extreme outlier compared to all prior weeks...", which breaks
the rule for a reader who is not supposed to need statistics. The guard rewrites the offending
words deterministically and records every rewrite in `language_guard_applied`, so the edit is
visible rather than silent. Technical vocabulary stays allowed in `technical_metrics`, which the
console renders collapsed -- exactly as the prompt intends.
"""
import re

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

# Keys the decision layer owns outright. Listed so it is obvious what is deterministic and what
# the model may write: everything here is overwritten after the model replies.
DECISION_OWNED_KEYS = (
    "miss_category", "miss_category_reason", "forecastability", "root_cause_sentence",
    "why_this_happened", "criticality", "evidence_index", "evidence_ids",
    "forecast_response_diagnostic", "driver_diagnostics", "weekend_diagnostic",
    "unconfirmed_signals", "wfm_action", "decision_meta",
)


# Longest patterns first, so "extreme outlier" wins over "outlier" and reads as English.
_LANGUAGE_SUBSTITUTIONS = (
    (r"\bextreme outliers?\b", "extreme value"),
    (r"\bstatistical outliers?\b", "unusual value"),
    (r"\boutliers\b", "unusual values"),
    (r"\boutlier\b", "unusual value"),
    (r"\bz[\s\-]?scores?\b", "distance from the usual level"),
    (r"\bstandard deviations?\b", "typical week-to-week variation"),
    (r"\bsigma\b", "typical variation"),
    (r"\bcorrelations?\b", "relationship"),
    (r"\bcorrelated\b", "linked"),
    (r"\bregressions?\b", "trend fitting"),
    (r"\bpearson\b", "relationship"),
    (r"\bmape\b", "average forecast error"),
    (r"\bshap\b", "driver attribution"),
    (r"\bisolation forest\b", "anomaly detection"),
    (r"\btrend slope\b", "direction of travel"),
)

# Business-facing fields. `technical_metrics` is deliberately NOT in this list.
_GUARDED_TOP = ("executive_summary", "business_impact")
_GUARDED_CAUSE = ("title", "explanation", "business_impact", "recommended_action")


def _scrub(text):
    """Rewrite banned vocabulary. Returns (new_text, [what changed])."""
    if not isinstance(text, str) or not text:
        return text, []
    changed, out = [], text
    for pattern, replacement in _LANGUAGE_SUBSTITUTIONS:
        for hit in set(m.group(0) for m in re.finditer(pattern, out, flags=re.IGNORECASE)):
            changed.append(f"{hit} -> {replacement}")
        out = re.sub(pattern, replacement, out, flags=re.IGNORECASE)
    if changed:
        # keep sentence capitalisation if a replacement landed at the very start
        out = out[:1].upper() + out[1:] if out[:1].islower() and text[:1].isupper() else out
    return out, changed


# ---------------------------------------------------------------------------
# TERMINOLOGY: Final_Units and Final_Y1..Y5 are PLANNED UNITS FOR DELIVERY / PRODUCTION
# (the business also calls them "Shipment"). They are NOT the installed base -- that would be
# units already in the field, a different quantity that points a reader at the wrong lever.
# The model reliably writes "installed base" anyway, so the term is rewritten on the way out.
# Longest phrase first: "the installed base" must be consumed before "installed base".
# Every pattern needs a literal space, so `installed_base_change` (a cause_type value) is safe.
# ---------------------------------------------------------------------------
_TERMINOLOGY = (
    (r"\bthe\s+installed\s+base\b", "planned units for delivery (shipment)"),
    (r"\ban\s+installed\s+base\b", "a planned-unit (shipment)"),
    (r"\binstalled\s+base\b", "planned units (shipment)"),
    (r"\binstalled\s+units\s+under\s+warranty\b", "planned units falling under warranty"),
    (r"\binstalled\s+units\b", "planned units"),
)

# Internal payload block names. These are OUR structure, not the business's vocabulary, and they
# reach the reader two ways: inside prose, and as supporting_evidence[].source_field, which the
# console prints as a technical chip. "INVESTIGATION_LADDER.levels[2].adherence_pct" is where the
# word "investigate" appeared on screen next to a finding -- meaningless to a forecaster.
_BLOCK_LABELS = (
    (r"\bINVESTIGATION_LADDER\b", "higher-level check"),
    (r"\bCHANNEL_SIBLINGS\b", "similar queues"),
    (r"\bDERIVED_FEATURES\b", "data analysis"),
    (r"\bCLEANED_SIGNALS\b", "data analysis"),
    (r"\bDATA_QUALITY\b", "data quality check"),
    (r"\bTEMPORAL\b", "history"),
    (r"\bHIERARCHY\b", "reporting hierarchy"),
)

_BLOCK_NAME_MAP = {
    "INVESTIGATION_LADDER": "higher-level check",
    "CHANNEL_SIBLINGS": "similar queues",
    "DERIVED_FEATURES": "data analysis",
    "CLEANED_SIGNALS": "data analysis",
    "DATA_QUALITY": "data quality check",
    "TEMPORAL": "history",
    "HIERARCHY": "reporting hierarchy",
}

_SNAKE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")     # a bare identifier, never prose


def _relabel_block(value):
    """Turn an internal payload reference into a business label, or return None if it is not one.

    Two shapes reach the reader:
      "CHANNEL_SIBLINGS"                             -> "similar queues"
      "INVESTIGATION_LADDER.levels[2].adherence_pct" -> "higher-level check - adherence_pct"
    The second is a supporting_evidence[].source_field, which the console renders as a chip beside
    the finding. The trailing field name is kept because it is the one part an analyst can act on;
    the block name and the array indices are ours, not theirs.
    """
    text = (value or "").strip()
    if not text:
        return None
    head = re.split(r"[.\[]", text, 1)[0]
    label = _BLOCK_NAME_MAP.get(head)
    if label is None:
        return None
    if head == text:
        return label
    leaf = re.split(r"[.\[]", text)
    leaf = [p for p in leaf if p and not p.rstrip("]").isdigit()]
    tail = leaf[-1].rstrip("]") if len(leaf) > 1 else ""
    return f"{label} - {tail}" if tail and tail != head else label


def _fix_terminology(value, path="", log=None):
    """Recursively rewrite the banned term in every string value. Returns the new value."""
    if log is None:
        log = []
    if isinstance(value, dict):
        return {k: _fix_terminology(v, f"{path}.{k}", log) for k, v in value.items()}
    if isinstance(value, list):
        return [_fix_terminology(v, f"{path}[{i}]", log) for i, v in enumerate(value)]
    if not isinstance(value, str) or not value:
        return value
    # Internal block names are handled BEFORE the identifier guard below. A bare "CHANNEL_SIBLINGS"
    # or "DATA_QUALITY" matches _SNAKE, so the guard would otherwise protect exactly the tokens that
    # were being printed at the reader (they appeared verbatim in MISSING INFORMATION). None of the
    # patterns can match a real field name -- they are specific upper-case block names.
    block = _relabel_block(value)
    if block is not None:
        log.append(f"{path.lstrip('.')}: {value} -> {block}")
        return block

    if _SNAKE.match(value):          # identifier such as installed_base_change -- leave alone
        return value
    out = value
    for pattern, replacement in _BLOCK_LABELS:
        if re.search(pattern, out):
            hits = set(m.group(0) for m in re.finditer(pattern, out))
            out = re.sub(pattern, replacement, out)
            for h in hits:
                log.append(f"{path.lstrip('.')}: {h} -> {replacement}")
    for pattern, replacement in _TERMINOLOGY:
        if re.search(pattern, out, flags=re.IGNORECASE):
            hits = set(m.group(0) for m in re.finditer(pattern, out, flags=re.IGNORECASE))
            out = re.sub(pattern, replacement, out, flags=re.IGNORECASE)
            for h in hits:
                log.append(f"{path.lstrip('.')}: {h} -> {replacement}")
    if out != value and value[:1].isupper() and out[:1].islower():
        out = out[:1].upper() + out[1:]              # keep sentence capitalisation
    return out


# A statistical finding outranks the model only at or above this confidence. The verdict's weaker
# branches (inherent volatility at 65, stable-demand at 68) are measurements worth reporting but are
# not better ANSWERS than a strongly evidenced model conclusion.
STAT_LEAD_MIN_CONFIDENCE = 70


def apply_statistical_override(result, features):
    """Insert the strongest DETERMINISTIC statistical finding at rank 1.

    Statistical evidence is the strongest evidence available, so it leads. The model's causes are
    demoted, not discarded: they remain in ranked_root_causes below, and what happened is recorded in
    `statistical_override_applied` so the change is auditable rather than invisible.

    No-ops when the arithmetic produced no finding, which is the common case for a well-behaved queue.
    """
    stats = (features or {}).get("statistical_evidence") or {}
    top = stats.get("strongest_finding")
    if not top:
        return result

    ranked = [c for c in (result.get("ranked_root_causes") or []) if isinstance(c, dict)]

    # Statistical evidence LEADS only when it is decisive. The verdict scores its own findings, and
    # the weak branches score below this line -- "the queue is volatile" (65) is a real measurement
    # but it is not a stronger answer than a well-evidenced 90% model conclusion. Putting a 60%
    # finding at rank 1 above a 90% one also broke the report's own contract that confidence
    # descends (results/spec_compliance_check.py S5), which is a fair complaint, not a test artefact.
    # Below the line the finding is still added -- never hidden -- but it takes its place on merit.
    decisive = (top.get("confidence_pct") or 0) >= STAT_LEAD_MIN_CONFIDENCE

    # Do not duplicate: if the model already reached the same cause_type, keep ITS wording (it has
    # the business context) and merely attach the measured figures as the evidence behind it.
    same = next((c for c in ranked if c.get("cause_type") == top.get("cause_type")), None)

    stat_evidence = [{
        "text": top.get("statement") or "",
        "source_field": top.get("metric") or "statistical evidence",
        "value": top.get("rank_basis"),
    }]

    if same is not None:
        same["evidence"] = list(same.get("evidence") or []) + stat_evidence
        if decisive:
            # Mark it as statistically backed BEFORE promoting. Without this the cause is promoted
            # above a higher-confidence one while still looking like an ordinary model cause, so the
            # ordering appears arbitrary to anything reading the report (spec S5 flagged exactly
            # that: a 45%-confidence cause sitting above a 90% one with no stated reason).
            same["evidence_grade"] = "statistical (deterministic)"
            same["statistically_confirmed_by"] = top.get("metric")
            _rest = sorted((c for c in ranked if c is not same),
                           key=lambda c: (c.get("confidence_pct") or 0), reverse=True)
            ranked = [same] + _rest
        note = (f"Statistical evidence ({top.get('metric')}) confirms the model's "
                f"{top.get('cause_type')} conclusion; the measured figures were attached and the "
                f"cause promoted to rank 1.")
    else:
        entry = {
            "cause_type": top.get("cause_type"),
            "title": top.get("title"),
            "explanation": top.get("statement"),
            "confidence_pct": top.get("confidence_pct"),
            "evidence": stat_evidence,
            # required by the report contract on EVERY cause (spec S4)
            "business_impact": (f"Forecast Adherence for this queue is affected by a measured "
                                f"{top.get('rank_basis')} pattern in its own history."),
            "recommended_action": top.get("recommended_action")
                                  or "Re-baseline this queue's forecast using the measured figures above.",
            "evidence_grade": "statistical (deterministic)",
        }
        if decisive:
            # Sort the model's causes by confidence BEFORE the statistical cause is placed on top.
            # The model returns them in whatever order it wrote them -- a live run came back
            # [70, 90, 60, 40] -- and nothing sorted them, so the report claimed "best-supported
            # first" while ranking a 70% cause above a 90% one (spec check S5). Only the mandated
            # leader is exempt from descending order; everything below it must earn its place.
            ranked.sort(key=lambda c: (c.get("confidence_pct") or 0), reverse=True)
            ranked.insert(0, entry)
            note = (f"Statistical evidence ({top.get('metric')}) overrides the model's ranking: "
                    f"{top.get('cause_type')} is measured directly from this queue's own history. The "
                    f"model's causes are retained below as contributing factors.")
        else:
            # added, then ordered by confidence with everything else -- reported, not promoted
            ranked.append(entry)
            ranked.sort(key=lambda c: (c.get("confidence_pct") or 0), reverse=True)
            note = (f"Statistical evidence ({top.get('metric')}) was added as a contributing cause. "
                    f"It did not lead: at {top.get('confidence_pct')}% it is below the "
                    f"{STAT_LEAD_MIN_CONFIDENCE}% bar for overriding a model conclusion.")

    # Reuse normalise_causes rather than assigning ranks by hand: it also derives confidence_level
    # from confidence_pct, and every consumer (the UI badge, the spec suite) expects that key on
    # every cause. Setting rank alone left the inserted statistical cause without it and crashed
    # results/spec_compliance_check.py.
    result["ranked_root_causes"] = normalise_causes(ranked)
    # Apply the SAME Verified / Hypothesis marking every other cause goes through, rather than
    # stamping a status by hand. hypothesis_generator only imports .common, so there is no cycle.
    # A statistical cause normally lands on "Verified" -- it is arithmetic on the queue's own data
    # and carries its evidence -- but it must earn that from the same rules, not by assertion.
    from .hypothesis_generator import mark as _mark_status
    result["ranked_root_causes"] = _mark_status(result["ranked_root_causes"], features or {})
    ranked = result["ranked_root_causes"]
    result["statistical_override_applied"] = note

    # The panel headline and the primary cause must follow the new rank 1, otherwise the report
    # would show the statistical cause in the list while still headlining the model's.
    lead = ranked[0]
    result["cause_type"] = lead.get("cause_type")
    result["primary_root_cause"] = {
        "statement": lead.get("explanation") or lead.get("title") or "",
        "confidence": (lead.get("confidence_pct") or 0) / 100.0,
        "supporting_evidence": lead.get("evidence") or [],
    }
    result["confidence_score"] = (lead.get("confidence_pct") or 0) / 100.0
    result["statistical_evidence"] = stats          # rendered as its own panel
    return result


def apply_language_guard(result):
    """Enforce the prompt's BUSINESS LANGUAGE rule in code, and log what was rewritten."""
    log = []
    for key in _GUARDED_TOP:
        new, changed = _scrub(result.get(key))
        if changed:
            result[key] = new
            log += [f"{key}: {c}" for c in changed]

    narrative = result.get("reasoning_narrative")
    if isinstance(narrative, str):
        new, changed = _scrub(narrative)
        if changed:
            result["reasoning_narrative"] = new
            log += [f"reasoning_narrative: {c}" for c in changed]
    elif isinstance(narrative, list):
        rebuilt = []
        for item in narrative:
            new, changed = _scrub(item)
            rebuilt.append(new)
            log += [f"reasoning_narrative: {c}" for c in changed]
        result["reasoning_narrative"] = rebuilt

    for i, cause in enumerate(result.get("ranked_root_causes") or [], start=1):
        if not isinstance(cause, dict):
            continue
        for key in _GUARDED_CAUSE:
            new, changed = _scrub(cause.get(key))
            if changed:
                cause[key] = new
                log += [f"cause{i}.{key}: {c}" for c in changed]
        for j, ev in enumerate(cause.get("evidence") or [], start=1):
            if not isinstance(ev, dict):
                continue
            new, changed = _scrub(ev.get("text"))
            if changed:
                ev["text"] = new
                log += [f"cause{i}.evidence{j}: {c}" for c in changed]

    findings = result.get("key_findings")
    if isinstance(findings, list):
        rebuilt = []
        for item in findings:
            new, changed = _scrub(item)
            rebuilt.append(new)
            log += [f"key_findings: {c}" for c in changed]
        result["key_findings"] = rebuilt

    # Recursive terminology pass LAST, so it also covers the blocks the key-by-key guard above
    # never visits -- executive_summary, skeptic_review, investigation_trail, rejected_hypotheses.
    term_log = []
    for key, value in list(result.items()):
        if key in ("derived_features", "language_guard_applied"):
            continue                     # internal payload, not shown as prose
        result[key] = _fix_terminology(value, key, term_log)
    if term_log:
        log += term_log
        result["terminology_guard_applied"] = term_log

    if log:
        result["language_guard_applied"] = log
    return result


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


def _build_historical_comparison(base_features, temporal):
    ch = (base_features or {}).get("chronic_bias") or {}
    tw = (base_features or {}).get("this_week_vs_usual") or {}
    temp = temporal or {}
    weeks = ch.get("history_weeks") or temp.get("history_weeks_available") or 13
    mean_adh = ch.get("history_mean_adherence_pct")
    typ = ch.get("typical_abs_deviation_pct") or tw.get("typical_abs_deviation_pct")
    usual_act = ch.get("usual_actual") or temp.get("last_13_week_avg_actual")
    usual_fc = ch.get("usual_forecast")

    narrative_parts = []
    if weeks:
        if usual_act is not None:
            narrative_parts.append(f"Over the last {weeks} weeks, actual demand for this queue averaged ~{usual_act} contacts per week.")
        if mean_adh is not None:
            dir_str = "above" if mean_adh < 0 else "below"
            narrative_parts.append(f"The queue historically trends {dir_str} forecast with an average adherence of {mean_adh}%.")
        if typ is not None:
            narrative_parts.append(f"Typical weekly error magnitude is about ~{typ}%.")
        if tw.get("times_usual") is not None and tw.get("times_usual") > 1:
            narrative_parts.append(f"This week's miss magnitude is {tw.get('times_usual')}x its typical historical variation.")

    last_year = temp.get("same_week_last_year")
    if last_year and last_year.get("actual") is not None:
        narrative_parts.append(f"In the same fiscal week last year (FW {last_year.get('fiscal_week')}), actual demand was {last_year.get('actual')} contacts.")

    narrative = " ".join(narrative_parts) if narrative_parts else f"Historical baseline evaluated over {weeks} weeks of demand data."

    dp = []
    if weeks:
        dp.append({"label": "Historical weeks evaluated", "value": str(weeks)})
    if usual_act is not None:
        dp.append({"label": "13-Week avg actual demand", "value": f"{usual_act} contacts"})
    if usual_fc is not None:
        dp.append({"label": "13-Week avg forecast", "value": f"{usual_fc} contacts"})
    if temp.get("last_4_week_avg_actual") is not None:
        dp.append({"label": "Recent 4-Week avg actual", "value": f"{temp.get('last_4_week_avg_actual')} contacts"})
    if last_year and last_year.get("actual") is not None:
        dp.append({"label": f"Same week last year (FW {last_year.get('fiscal_week')}) actual", "value": f"{last_year.get('actual')} contacts"})

    return {"narrative": narrative, "data_points": dp}


def apply_decision(result, decision, features=None):
    """Re-impose the deterministic decision on the assembled response.

    Runs AFTER the model and after back_compat, so nothing the model wrote can change what the
    report claims. `cause_type` and `status` are deliberately left alone -- they are the existing
    contract and every current consumer still reads them. `evidence_class` is attached ALONGSIDE
    them so the new ranking is additive.
    """
    if not decision:
        return result

    result["miss_category"] = decision.get("miss_category")
    result["miss_category_reason"] = decision.get("miss_category_reason")
    result["forecastability"] = {
        "classification": decision.get("forecastability"),
        "reason": decision.get("forecastability_reason"),
    }
    result["root_cause_sentence"] = decision.get("root_cause_sentence")
    result["why_this_happened"] = decision.get("why_bullets") or []
    result["criticality"] = decision.get("criticality") or {}
    result["evidence_index"] = decision.get("evidence_index") or {}
    result["decision_meta"] = {
        "version": decision.get("version"),
        "rules": decision.get("rules"),
        "note": ("miss_category and evidence_class are decided in Python from the deterministic "
                 "evidence. The model narrates them and cannot override them."),
    }

    # Confidence: the deterministic score is authoritative, and it is EVIDENCE STRENGTH -- kept
    # separate from criticality, which is severity.
    conf = decision.get("confidence") or {}
    if conf.get("score_pct") is not None:
        result["confidence_score"] = round(conf["score_pct"] / 100.0, 3)
        result["confidence_detail"] = conf

    # evidence_class onto each ranked cause, matched on the mechanism the decision layer used.
    by_cause_type = {}
    for cand in decision.get("candidates") or []:
        by_cause_type.setdefault(cand.get("cause_type"), []).append(cand)
    for cause in result.get("ranked_root_causes") or []:
        pool = by_cause_type.get(cause.get("cause_type")) or []
        match = pool[0] if pool else None
        cause["evidence_class"] = (match or {}).get("evidence_class") or "UNCONFIRMED_SIGNAL"
        cause["evidence_ids"] = (match or {}).get("evidence_ids") or []
        cause["direction_coherent"] = (match or {}).get("direction_coherent")
        cause["evidence_resolution"] = (match or {}).get("resolution")

    # Anything the decision layer rejected is reported as rejected, whatever the model said.
    rejected = decision.get("rejected") or []
    existing = result.get("rejected_hypotheses") or []
    seen = {str(r.get("hypothesis")) for r in existing if isinstance(r, dict)}
    for r in rejected:
        if r.get("headline") not in seen:
            existing.append({"hypothesis": r.get("headline"),
                             "reason_rejected": r.get("reason")})
    result["rejected_hypotheses"] = existing
    result["unconfirmed_signals"] = [
        {"headline": c.get("headline"), "cause_type": c.get("cause_type"),
         "why_unconfirmed": c.get("why_it_mattered"), "evidence_ids": c.get("evidence_ids")}
        for c in (decision.get("candidates") or [])
        if c.get("evidence_class") == "UNCONFIRMED_SIGNAL"]

    # The panels the UI renders straight from deterministic evidence.
    feats = features or (result.get("derived_features") or {})
    fr = feats.get("forecast_response") or {}
    result["forecast_response_diagnostic"] = {
        "available": bool(fr.get("available")),
        "response": fr.get("response"),
        "movement_test": fr.get("movement_test"),
        "signals": fr.get("signals"),
        "miss_decomposition": fr.get("miss_decomposition"),
        "forecastability": fr.get("forecastability"),
        "reason": fr.get("reason"),
    }
    lag = feats.get("lag_analysis") or {}
    result["driver_diagnostics"] = {
        "available": bool(lag.get("available")),
        "lags_tested": lag.get("lags_tested"),
        "drivers": [{"driver": d.get("driver"), "subject": d.get("subject"),
                     "coverage": d.get("coverage"),
                     "weeks_with_a_value": d.get("weeks_with_a_value"),
                     "weeks_in_window": d.get("weeks_in_window"),
                     "best_lag_weeks": d.get("best_lag_weeks"),
                     "relationship_strength": d.get("relationship_strength"),
                     "relationship_type": d.get("relationship_type"),
                     "stability": d.get("stability"),
                     "usable_as_evidence": d.get("usable_as_evidence"),
                     "interpretation": d.get("interpretation")}
                    for d in (lag.get("drivers") or [])],
        "reason": lag.get("reason"),
    }
    gran = feats.get("data_granularity") or {}
    result["weekend_diagnostic"] = {
        "grain": gran.get("grain"),
        "supported": bool((gran.get("capabilities") or {}).get("weekend_volume_effect")),
        "statement": gran.get("weekend_statement"),
        "holiday_day_structure": feats.get("holiday_day_structure"),
    }
    result["holiday_response"] = feats.get("holiday_response") or {}

    # Limitations are additive to whatever the model flagged, deduped.
    missing = list(result.get("missing_information") or [])
    for lim in decision.get("limitations") or []:
        if lim and lim not in missing:
            missing.append(lim)
    result["missing_information"] = missing

    # One concrete action, taken from the leading supported mechanism.
    primary = next((c for c in (decision.get("candidates") or [])
                    if c.get("evidence_class") == "PRIMARY_DRIVER"), None)
    result["wfm_action"] = (primary or {}).get("action") or (
        "Confirm the figures for this week before acting: the evidence does not establish a cause.")
    return result


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
    # Always expose the statistics, whether or not they overrode anything -- the drill-down is the
    # point, so the panel must be populated even for a queue whose numbers are unremarkable.
    if "statistical_evidence" not in result:
        _se = (result.get("derived_features") or {})
        _se = _se.get("statistical_evidence") if isinstance(_se, dict) else None
        if _se:
            result["statistical_evidence"] = _se

    result.setdefault("secondary_contributors", [])
    result.setdefault("key_findings", _observations_from_features(base_features or {}))
    result.setdefault("supporting_evidence", (ranked[0].get("evidence") if ranked else []) or [])
    # The ROOT CAUSE panel renders reasoning_narrative. It must carry the REASONING -- what was
    # checked and why this conclusion -- not the executive summary, whose first half is the fiscal
    # week and the volume deltas. Those numbers are already in KEY FINDINGS and the PROOF table, and
    # putting them here pushed the actual answer to the bottom of the panel.
    # investigation_trail.narrative is the genuine reasoning and has NO other render site in the
    # console (0 references), so it was being computed and discarded.
    _trail = ((result.get("investigation_trail") or {}).get("narrative") or "").strip()
    _why = ((ranked[0].get("explanation") if ranked else "") or "").strip()
    result.setdefault("reasoning_narrative", _trail or _why or result.get("executive_summary") or "")
    result.setdefault("rejected_hypotheses", [
        {"hypothesis": s.get("cause") or s.get("challenge") or "",
         "reason_rejected": s.get("reason") or ""}
        for s in (result.get("skeptic_review") or []) if s.get("verdict") == "rejected"
    ])
    hc = result.get("historical_comparison")
    if not isinstance(hc, dict) or not (hc.get("narrative") or hc.get("data_points")):
        df_all = result.get("derived_features") or {}
        temp = df_all.get("temporal") if isinstance(df_all, dict) else {}
        result["historical_comparison"] = _build_historical_comparison(base_features, temp)
    fs = (base_features or {}).get("forecast_sanity") or {}
    tw = (base_features or {}).get("this_week_vs_usual") or {}
    fc_val = fs.get("forecast") if fs.get("forecast") is not None else tw.get("target_forecast")
    act_val = fs.get("actual") if fs.get("actual") is not None else tw.get("target_actual")
    err_val = (round(act_val - fc_val, 2)
               if isinstance(act_val, (int, float)) and isinstance(fc_val, (int, float))
               else None)

    kpi_st = result.get("kpi_status") or {}
    adh_val = kpi_st.get("adherence_pct")
    miss_dir = kpi_st.get("direction")
    if adh_val is None:
        adh_val = (base_features or {}).get("this_week_vs_usual", {}).get("target_adherence_pct")
    result["forecast_summary"] = {
        "forecast": fc_val,
        "actual": act_val,
        "error": err_val,
        "adherence_pct": adh_val,
        "miss_type": miss_dir,
    }
    result.setdefault("proof", (base_features or {}).get("proof") or [])
    result.setdefault("cause_type", None)
    df = dict(result.get("derived_features") or {})
    if base_features:
        df.update(base_features)
    result["derived_features"] = df
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
                               "narrative": ""},
        # Set explicitly (not left to back_compat's setdefault) so the ROOT CAUSE panel does NOT
        # fall back to executive_summary, whose text is "No investigation was run." -- the word
        # "investigation" has no business appearing inside a ROOT CAUSE panel. The single honest
        # statement above is the whole content for an in-band week.
        "reasoning_narrative": "",
        "channel_migration": {"detected": False, "narrative": "", "gaining_channels": [],
                              "losing_channels": []},
        "technical_metrics": [],
        "missing_information": [],
        "derived_features": features,
        # NOT 1.0. This is a week that was never analysed, and 1.0 rendered as a "90-100% High"
        # confidence ROOT CAUSE card -- a confident-looking cause whose text admits no analysis was
        # done. None makes the console show "Confidence not scored", which is the truth.
        "confidence_score": None,
        "primary_root_cause": {
            "statement": (f"No root cause applies: Forecast Adherence of {shown}% is inside the "
                          f"accepted +/-{band}% tolerance, so this queue-week is not a miss."),
            "confidence": None, "supporting_evidence": []},
        "investigation_meta": {"engine": "wfm-not-investigated"},
    }, features.get("base_features") or {})
