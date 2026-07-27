# -*- coding: utf-8 -*-
"""
LLM Investigation Engine — the one module that is allowed to "reason" about a
forecast miss. Everything else in this backend (and in rca_console.html) is
plain deterministic code that gathers and structures data.

Two deterministic passes bracket the model so its answer can't be generic or
circular:

  1. derive_features() — BEFORE the model runs. It cleans the raw statistical
     summary (drops noise columns that are outliers for meaningless reasons —
     Fiscal_Week, Week_Ending, the Monday..Sunday day flags — and collapses the
     correlated installed-base columns into one signal) and computes genuinely
     discriminating, per-queue causal features: chronic forecast bias/level,
     whether THIS week is worse than the queue's usual miss, a forecast-sanity
     check (is the forecast itself the anomaly?), plan restatement, installed-base
     change, holiday effect, and peer divergence. This is what makes the output
     differ per queue instead of always restating "the actual is an outlier".

  2. _verify_and_fix() — AFTER the model runs. Rejects a primary root cause whose
     ONLY evidence restates the miss (the offered/handled/adherence fields that are
     outliers for every flagged queue by definition) or cites a dropped noise field;
     promotes a clean secondary if one exists, else synthesises an honest,
     fully-cited finding from the strongest derived feature. The engine therefore
     never returns "not enough data" and never invents a cause — the weakest case
     still gets the best *data-backed* finding, phrased with an honest confidence.

Providers: NVIDIA and Groq (both OpenAI-compatible chat APIs), chosen per call.
A specific model can be requested per queue (model picker in the UI) via
`model_choice`; otherwise the configured primary->secondary chain is used. If no
provider is reachable, investigate() returns an honest placeholder.

forecast_summary figures are ALWAYS taken from our own deterministic
context_bundle.target.computed — never from what the model echoes back.
"""
import json
import re
import urllib.request
import urllib.error
from datetime import datetime, timezone

PROVIDER_ENDPOINTS = {
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "nvidia": "https://integrate.api.nvidia.com/v1/chat/completions",
}
DEFAULT_MODELS = {
    "groq": "llama-3.3-70b-versatile",
    "nvidia": "nvidia/nemotron-3-super-120b-a12b",
}

# Columns whose "outlier" / "changed" flags are meaningless and were driving generic
# root causes: Fiscal_Week is monotonic (always ~z 1.9), Week_Ending changes every
# single week (always a "categorical change"), and the day-of-week flags are 0/1 that
# spike to z>3 on any holiday week. Excluded from the stats sent to the model.
NOISE_FIELDS = {"Fiscal_Week", "Week_Ending", "Monday", "Tuesday", "Wednesday",
                "Thursday", "Friday", "Saturday", "Sunday"}
# Near-identical installed-base columns — one real signal counted many times (a fake
# z that dominated). Collapsed to a single "installed_base" signal (max |z|).
INSTALLED_BASE_FIELDS = ["Final_Units", "Final_Y1", "Final_Y2", "Final_Y3",
                         "Final_Y4", "Final_Y5", "Final_upp_units"]
# Fields that are outliers for EVERY flagged queue by definition — citing them as the
# primary cause just restates that a miss happened. Used by the verifier.
DEFINITIONAL_FIELDS = {"Actual_Offered", "Actual_Handled", "fcst_offered", "fcst_handled",
                       "adherence_pct", "accuracy_pct", "error", "forecast", "actual", "severity"}

SYSTEM_PROMPT = """You are an investigative root-cause analyst for a demand-forecasting system.

You are given a JSON "context bundle" for ONE forecast miss (target week's raw data,
its recent history and same-week peer queues, an auto-computed statistical_summary), plus
a DERIVED_FEATURES block we computed for you — chronic bias/level, whether this week is
worse than the queue's usual miss, a forecast-sanity check, plan restatement, installed-base
change, holiday effect, peer divergence, and CLEANED_SIGNALS (the real per-field outliers
with meaningless columns already removed). Reason primarily from DERIVED_FEATURES and
CLEANED_SIGNALS — they are the discriminating evidence.

AUDIENCE & LANGUAGE (very important):
The reader is a BUSINESS LEAD, not a data scientist. Write EVERY human-facing sentence —
key_findings[], primary_root_cause.statement, secondary_contributors[].statement,
supporting_evidence[].text, rejected_hypotheses[].hypothesis, rejected_hypotheses[].reason_rejected,
historical_comparison.narrative, reasoning_narrative[], forecast_improvement_recommendations,
missing_information — in plain, everyday business English that a manager can read once and act on.
Do NOT use statistics jargon in these sentences: never write "z-score", "standard deviation",
"outlier", "sigma", "trend slope", "MAPE", "adherence deviation", "chronic bias". Translate them
into ordinary language, for example:
  - "Actual_Offered z-score 4.5 / is an outlier"  ->  "demand came in far higher than this queue normally runs"
  - "fcst_offered z of -2.3"                       ->  "the forecast was set well below this queue's usual level"
  - "positive trend slope"                          ->  "demand has been climbing for several weeks"
  - "chronic under-forecast bias"                   ->  "this queue is under-forecast almost every week"
Keep the CAUSE itself specific, genuine and correct — do NOT water down or generalise the conclusion,
only simplify the wording. You MAY keep exact field names and numbers in supporting_evidence[].source_field
and supporting_evidence[].value (those render as small technical detail chips for analysts); just make the
.text a plain explanation. reasoning_narrative should read like a short, jargon-free paragraph.

Classify the miss into ONE primary cause_type from this taxonomy, then explain it:
- "forecast_baseline_error"      : the forecast itself is anomalous vs the queue's own history
                                    (see forecast_sanity) — a broken/placeholder baseline, not a demand change.
- "systematic_forecast_bias"     : the queue is chronically off in the same direction (see chronic_bias) —
                                    a calibration problem, this week is just another instance of it.
- "genuine_demand_event"         : a real one-week demand move (this week is materially worse than the
                                    queue's usual miss AND the forecast looks normal).
- "volume_routing_shift"         : a sibling/peer queue moved the opposite way the same week
                                    (see peer_divergence) — volume shifted between queues, not total demand.
- "plan_restatement"             : Projection_plan_name changed this week (see plan_restatement).
- "installed_base_change"        : installed base (Final_* / units) shifted materially and plausibly drives demand.
- "calendar_holiday_effect"      : a holiday/short week plausibly explains the magnitude (see holiday).

How to reason:
1. The miss magnitude/direction are already in context.target.computed — never recompute or contradict them.
2. Prefer the cause_type whose DERIVED_FEATURES evidence is strongest and most SPECIFIC to this queue.
3. Generate multiple hypotheses from DIFFERENT features; for each, weigh supporting vs contradicting evidence;
   reject the weak ones in rejected_hypotheses with the reason.
4. Rank survivors: the strongest becomes primary_root_cause, the rest secondary_contributors.

These three sections are DIFFERENT and must NOT repeat the same sentence:
- key_findings: 3-6 OBJECTIVE OBSERVATIONS discovered in the data — plain facts, NOT the cause. Each states
  something notable that is true of this queue this week (e.g. "The forecast was set about 3x this queue's
  usual level.", "This week's gap is roughly 9x the queue's typical weekly gap.", "3 of 11 similar queues
  moved the opposite way.", "The forecast plan did not change this week."). Do NOT say "the cause is ..." here.
- primary_root_cause.statement: the single MOST LIKELY EXPLANATION for WHY the forecast missed (the conclusion
  drawn FROM the findings). This is a different sentence from any single key finding.
- reasoning_narrative: 2-4 short bullet-style sentences that tell the STORY connecting the findings to the
  cause — what you saw, what you ruled out, and why the primary cause is the best explanation. Return it as an
  ARRAY of short strings (one point each), NOT one long paragraph.

Hard rules:
- NEVER make "Actual_Offered / Actual_Handled / fcst_* is an outlier vs its own history" your PRIMARY
  cause — that is true of every flagged queue by definition and explains nothing. It may appear only as
  background context, never as the primary supporting_evidence.
- Every supporting_evidence item MUST cite a specific source_field from DERIVED_FEATURES/CLEANED_SIGNALS and
  the value you observed. Never invent a cause not traceable to the supplied data.
- ALWAYS produce a primary_root_cause. If no single signal is strong, choose the cause_type best supported by
  DERIVED_FEATURES (usually forecast_baseline_error or systematic_forecast_bias), give it a HONEST LOWER
  confidence, and phrase it as "the data is most consistent with ...". NEVER say "not enough data" and NEVER
  return a null primary — state the best data-backed finding and put what would raise confidence in
  missing_information.
- forecast_improvement_recommendations: ONLY forecasting model/process suggestions (re-baselining, adding a
  variable, revisiting seasonality) — NEVER workforce/staffing/operational advice.
- Respond with ONLY a single JSON object, no prose outside it, matching EXACTLY this shape (use null/[] only
  where truly empty; never omit a key):

{
  "cause_type": "string (one of the taxonomy keys above)",
  "key_findings": ["string (objective observation from the data, NOT the cause)"],
  "primary_root_cause": {"statement": "string", "confidence": 0.0, "supporting_evidence": [{"text": "string", "source_field": "string", "value": "any"}]},
  "supporting_evidence": [{"text": "string", "source_field": "string", "value": "any"}],
  "secondary_contributors": [{"statement": "string", "confidence": 0.0, "supporting_evidence": [{"text": "string", "source_field": "string", "value": "any"}]}],
  "rejected_hypotheses": [{"hypothesis": "string", "reason_rejected": "string"}],
  "historical_comparison": {"narrative": "string", "data_points": [{"label": "string", "value": "any"}]},
  "reasoning_narrative": ["string (one short point per item — the story, NOT one long paragraph)"],
  "forecast_improvement_recommendations": ["string"],
  "confidence_score": 0.0,
  "missing_information": ["string"]
}
"""

_RESPONSE_DEFAULTS = {
    "cause_type": None,
    "key_findings": [],
    "primary_root_cause": None,
    "supporting_evidence": [],
    "secondary_contributors": [],
    "rejected_hypotheses": [],
    "historical_comparison": {"narrative": "", "data_points": []},
    "reasoning_narrative": "",
    "forecast_improvement_recommendations": [],
    "confidence_score": None,
    "missing_information": [],
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _mean(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return sum(xs) / len(xs) if xs else None


# ---------------------------------------------------------------------------
# PASS 1 — deterministic feature engineering (runs BEFORE the model)
# ---------------------------------------------------------------------------
def derive_features(context_bundle):
    """Compute discriminating, per-queue causal features + a cleaned signal list
    from the bundle the console already sends. Pure data, cites field names."""
    b = context_bundle or {}
    target = b.get("target") or {}
    computed = target.get("computed") or {}
    stat = b.get("statistical_summary") or {}
    numeric = dict(stat.get("numeric") or {})
    categorical = dict(stat.get("categorical") or {})
    history = b.get("history") or []
    peers = b.get("peers") or []
    band = ((b.get("meta") or {}).get("band_threshold")) or 10

    hcomp = [h.get("computed") or {} for h in history]
    hist_adh = [c.get("adherence_pct") for c in hcomp if isinstance(c.get("adherence_pct"), (int, float))]
    t_adh = computed.get("adherence_pct")
    t_actual = computed.get("actual")
    t_forecast = computed.get("forecast")

    feats = {}

    # -- chronic bias / level: is this queue ALWAYS off, same direction? --
    mean_adh = _mean(hist_adh)
    typical_abs = _mean([abs(a) for a in hist_adh])
    chronic = None
    if mean_adh is not None and typical_abs is not None:
        # sign convention (frontend): negative adherence = under-forecast (actual ran hot)
        direction = "under" if mean_adh < 0 else "over"
        share_same = (sum(1 for a in hist_adh if (a < 0) == (mean_adh < 0)) / len(hist_adh)) if hist_adh else 0
        chronic = {
            "history_mean_adherence_pct": round(mean_adh, 1),
            "typical_abs_deviation_pct": round(typical_abs, 1),
            "history_weeks": len(hist_adh),
            "consistent_direction": direction if share_same >= 0.7 and typical_abs > band else None,
            "share_same_direction": round(share_same, 2),
            "verdict": ("chronic_" + direction) if (share_same >= 0.7 and typical_abs > band) else "mixed",
        }
    feats["chronic_bias"] = chronic

    # -- this week vs the queue's usual miss --
    if isinstance(t_adh, (int, float)) and typical_abs:
        times = abs(t_adh) / typical_abs if typical_abs else None
        feats["this_week_vs_usual"] = {
            "target_adherence_pct": round(t_adh, 1),
            "typical_abs_deviation_pct": round(typical_abs, 1),
            "times_usual": round(times, 1) if times is not None else None,
            "worse_than_usual": bool(times and times >= 1.5),
        }
    else:
        feats["this_week_vs_usual"] = None

    # -- forecast sanity: is the FORECAST itself the anomaly? --
    fo_stat = numeric.get("fcst_offered") or {}
    fo_z = fo_stat.get("z_score")
    ratio = None
    if isinstance(t_forecast, (int, float)) and isinstance(t_actual, (int, float)) and t_actual not in (0, None):
        ratio = t_forecast / t_actual if t_actual else None
    verdict = "normal"
    if isinstance(fo_z, (int, float)) and abs(fo_z) > 2:
        verdict = "forecast_anomalously_low" if fo_z < 0 else "forecast_anomalously_high"
    elif ratio is not None and (ratio < 0.34 or ratio > 3):
        verdict = "forecast_scale_mismatch"  # forecast an order of magnitude off the actual
    feats["forecast_sanity"] = {
        "forecast": round(t_forecast, 2) if isinstance(t_forecast, (int, float)) else t_forecast,
        "forecast_z_vs_own_history": round(fo_z, 2) if isinstance(fo_z, (int, float)) else None,
        "forecast_over_actual_ratio": round(ratio, 3) if ratio is not None else None,
        "verdict": verdict,
    }

    # -- installed base (collapse correlated Final_* columns to one signal) --
    ib = None
    best = None
    for f in INSTALLED_BASE_FIELDS:
        s = numeric.get(f)
        if s and isinstance(s.get("z_score"), (int, float)):
            if best is None or abs(s["z_score"]) > abs(best[1]):
                best = (f, s["z_score"], s.get("target_value"), s.get("history_mean"))
    if best:
        ib = {"field": best[0], "z_score": round(best[1], 2), "target_value": best[2],
              "history_mean": round(best[3], 2) if isinstance(best[3], (int, float)) else best[3],
              "material": abs(best[1]) > 2}
    feats["installed_base"] = ib

    # -- holiday / calendar (Holiday_Count is meaningful; day flags are not) --
    hc = numeric.get("Holiday_Count") or {}
    feats["holiday"] = {
        "holiday_count": hc.get("target_value"),
        "z_score": round(hc["z_score"], 2) if isinstance(hc.get("z_score"), (int, float)) else None,
        "unusual": bool(isinstance(hc.get("z_score"), (int, float)) and abs(hc["z_score"]) > 2),
    } if hc else None

    # -- plan restatement + other categorical changes (Week_Ending excluded) --
    def _cat_change(field):
        c = categorical.get(field)
        if c and c.get("changed"):
            return {"changed": True, "prior": c.get("prior_value"), "current": c.get("target_value")}
        return {"changed": False} if c else None
    feats["plan_restatement"] = _cat_change("Projection_plan_name")
    feats["forecaster_change"] = _cat_change("Forecaster")
    feats["offering_change"] = _cat_change("Offering")

    # -- peer divergence: did sibling queues move the opposite way this week? --
    t_dir = computed.get("direction")
    opp = []
    same = 0
    for p in peers:
        pc = p.get("computed") or {}
        pd = pc.get("direction")
        if pd is None:
            continue
        if t_dir is not None and pd != t_dir:
            opp.append({"forecast_name": (p.get("key") or {}).get("Forecast_name"),
                        "adherence_pct": round(pc["adherence_pct"], 1) if isinstance(pc.get("adherence_pct"), (int, float)) else None})
        elif pd == t_dir:
            same += 1
    feats["peer_divergence"] = {
        "peers_total": len(peers),
        "peers_opposite_direction": len(opp),
        "peers_same_direction": same,
        "examples_opposite": opp[:5],
        "signal": bool(opp),
    }

    # -- population context (if the console supplied it) --
    feats["population_context"] = (b.get("meta") or {}).get("population")

    # -- cleaned signals: real outliers, noise removed, installed-base collapsed --
    cleaned = []
    for f, s in numeric.items():
        if f in NOISE_FIELDS or f in INSTALLED_BASE_FIELDS or f in DEFINITIONAL_FIELDS:
            continue
        z = s.get("z_score")
        if isinstance(z, (int, float)) and abs(z) > 2:
            cleaned.append({"field": f, "z_score": round(z, 2), "target_value": s.get("target_value"),
                            "history_mean": round(s["history_mean"], 2) if isinstance(s.get("history_mean"), (int, float)) else s.get("history_mean")})
    if ib and ib["material"]:
        cleaned.append({"field": "installed_base(" + ib["field"] + ")", "z_score": ib["z_score"],
                        "target_value": ib["target_value"], "history_mean": ib["history_mean"]})
    cleaned.sort(key=lambda d: abs(d["z_score"]), reverse=True)
    feats["cleaned_signals"] = cleaned

    return feats


def _bundle_for_model(context_bundle, features):
    """A copy of the bundle with derived_features attached and the noise columns
    stripped from statistical_summary, so the model literally cannot cite them."""
    b = dict(context_bundle or {})
    stat = dict(b.get("statistical_summary") or {})
    stat["numeric"] = {k: v for k, v in (stat.get("numeric") or {}).items() if k not in NOISE_FIELDS}
    stat["categorical"] = {k: v for k, v in (stat.get("categorical") or {}).items()
                           if k not in NOISE_FIELDS and k != "Week_Ending"}
    b["statistical_summary"] = stat
    b["derived_features"] = features
    return b


# ---------------------------------------------------------------------------
# PASS 2 — deterministic verifier (runs AFTER the model)
# ---------------------------------------------------------------------------
def _evidence_fields(item):
    ev = (item or {}).get("supporting_evidence") or []
    return [str((e or {}).get("source_field") or "") for e in ev]


def _is_circular(item):
    """True if the finding's ONLY evidence restates the miss (definitional fields)
    or cites a dropped noise column — i.e. it explains nothing specific."""
    flds = [f for f in _evidence_fields(item) if f]
    if not flds:
        return True
    return all((f in DEFINITIONAL_FIELDS) or (f in NOISE_FIELDS) for f in flds)


def _finding_from_features(features):
    """Build an honest, fully-cited primary finding from the strongest derived
    feature — the fallback that guarantees we never say 'not enough data'."""
    fs = features.get("forecast_sanity") or {}
    chronic = features.get("chronic_bias") or {}
    peer = features.get("peer_divergence") or {}
    ev = []
    if fs.get("verdict", "normal") != "normal":
        stmt = ("The forecast for this week was set well away from what this queue normally sees, so the miss is most "
                "likely a problem with the forecast itself rather than a real change in demand.")
        ctype = "forecast_baseline_error"
        conf = 0.55
        ev.append({"text": "the forecast was set far from this queue's usual level", "source_field": "forecast_sanity",
                   "value": fs.get("forecast_z_vs_own_history") or fs.get("forecast_over_actual_ratio")})
    elif chronic.get("verdict", "mixed").startswith("chronic"):
        dirn = "under" if chronic.get("consistent_direction") == "under" else "over"
        plan = "too low" if dirn == "under" else "too high"
        stmt = (f"This queue is {dirn}-forecast almost every week, so this week's miss looks like an ongoing forecasting "
                f"pattern — the plan is consistently set {plan} — rather than a one-off event.")
        ctype = "systematic_forecast_bias"
        conf = 0.5
        ev.append({"text": f"this queue has been {dirn}-forecast for most of the recent weeks",
                   "source_field": "chronic_bias", "value": chronic.get("history_mean_adherence_pct")})
    elif peer.get("signal"):
        ex = (peer.get("examples_opposite") or [{}])[0]
        stmt = ("At least one similar queue moved the opposite way the same week, so the work most likely shifted "
                "between queues rather than total demand going up or down.")
        ctype = "volume_routing_shift"
        conf = 0.45
        ev.append({"text": f"a similar queue ({ex.get('forecast_name')}) moved the opposite way the same week",
                   "source_field": "peer_divergence", "value": peer.get("peers_opposite_direction")})
    else:
        stmt = ("The numbers point to a forecasting-accuracy issue for this queue; nothing else in the available data "
                "stands out strongly enough to be the single cause on its own.")
        ctype = "systematic_forecast_bias"
        conf = 0.35
        ev.append({"text": "no other single factor in the available data stands out", "source_field": "cleaned_signals",
                   "value": len(features.get("cleaned_signals") or [])})
    return ctype, {"statement": stmt, "confidence": conf, "supporting_evidence": ev}


def _observations_from_features(features):
    """Plain-language OBJECTIVE observations from the data — the Key Findings section
    (facts, not the cause). Used to fill key_findings when the model omits them and for
    the deterministic path, so Key Findings never just echoes the root cause."""
    f = features or {}
    obs = []
    fs = f.get("forecast_sanity") or {}
    v = fs.get("verdict", "normal")
    if v == "forecast_anomalously_low":
        obs.append("The forecast this week was set well below this queue's usual level.")
    elif v == "forecast_anomalously_high":
        obs.append("The forecast this week was set well above this queue's usual level.")
    elif v == "forecast_scale_mismatch":
        obs.append("The forecast was far out of line with the actual volume this week.")
    tw = f.get("this_week_vs_usual") or {}
    if tw.get("times_usual"):
        obs.append(f"This week's gap is about {tw['times_usual']}x the size of this queue's typical weekly gap.")
    ch = f.get("chronic_bias") or {}
    if str(ch.get("verdict", "")).startswith("chronic"):
        obs.append(f"This queue is {ch.get('consistent_direction')}-forecast in most of its recent weeks.")
    elif ch.get("verdict") == "mixed":
        obs.append("This queue's misses have no consistent direction over recent weeks.")
    pd = f.get("peer_divergence") or {}
    if pd.get("signal"):
        obs.append(f"{pd.get('peers_opposite_direction')} of {pd.get('peers_total')} similar queues moved the opposite way this week.")
    elif pd.get("peers_total"):
        obs.append(f"The {pd.get('peers_total')} similar queues mostly moved the same way this week.")
    pr = f.get("plan_restatement") or {}
    if pr.get("changed"):
        obs.append(f"The forecast plan changed this week (from {pr.get('prior')} to {pr.get('current')}).")
    else:
        obs.append("The forecast plan did not change this week.")
    ib = f.get("installed_base")
    if ib and ib.get("material"):
        obs.append("The installed base (units under warranty) for this queue shifted noticeably this week.")
    hol = f.get("holiday")
    if hol and hol.get("unusual"):
        obs.append("An unusual number of holidays fell in this week.")
    return obs[:6]


def _verify_and_fix(result, context_bundle, features):
    """Reject circular primaries; promote a clean secondary or synthesise a
    feature-based finding. Guarantees a non-circular, data-backed primary."""
    computed = ((context_bundle or {}).get("target") or {}).get("computed") or {}
    note = None
    primary = result.get("primary_root_cause")
    if not primary or _is_circular(primary):
        # try a clean secondary
        promoted = None
        for sec in (result.get("secondary_contributors") or []):
            if not _is_circular(sec):
                promoted = sec
                break
        if promoted:
            result["secondary_contributors"] = [s for s in result["secondary_contributors"] if s is not promoted]
            if primary:
                result["secondary_contributors"].append(primary)
            result["primary_root_cause"] = promoted
            note = ("Adjusted automatically: the first explanation simply restated that a miss happened, so the "
                    "clearest specific finding in the data was used as the main cause instead.")
        else:
            ctype, synth = _finding_from_features(features)
            if primary:
                result.setdefault("secondary_contributors", []).append(primary)
            result["primary_root_cause"] = synth
            result["cause_type"] = ctype
            result["reasoning_narrative"] = synth["statement"]   # keep the narrative coherent and jargon-free
            if result.get("confidence_score") is None:
                result["confidence_score"] = synth["confidence"]
            note = ("Built automatically from the data: the model did not give a specific cause, so the clearest "
                    "data-backed finding was used.")
    # verifier_note is internal QA context — kept off the business-facing reasoning_narrative on purpose.
    if note:
        result["verifier_note"] = note
    # confidence from primary if the model left it blank
    if result.get("confidence_score") is None and result.get("primary_root_cause"):
        c = result["primary_root_cause"].get("confidence")
        if isinstance(c, (int, float)):
            result["confidence_score"] = c
    return result


def _placeholder_response(context_bundle, features, extra_missing=None):
    """No live provider — still return the best DATA-BACKED finding from our own
    derived features (never a blank 'not enough data'), just flagged as offline."""
    computed = ((context_bundle or {}).get("target") or {}).get("computed") or {}
    fields_seen = sorted(set(((context_bundle or {}).get("target") or {}).get("fields", {}).keys()))
    ctype, synth = _finding_from_features(features)
    missing = list(extra_missing or []) + [
        "Live LLM connection is not configured/available — this finding is the deterministic best-supported "
        "cause from the derived features; connect a provider (config.json llm.* or GROQ/NVIDIA_API_KEY) for the "
        "full multi-hypothesis investigation.",
    ]
    return {
        "cause_type": ctype,
        "key_findings": _observations_from_features(features),
        "primary_root_cause": synth,
        "supporting_evidence": synth["supporting_evidence"],
        "secondary_contributors": [],
        "rejected_hypotheses": [],
        "historical_comparison": {"narrative": "", "data_points": []},
        "reasoning_narrative": synth["statement"],
        "forecast_improvement_recommendations": [],
        "confidence_score": synth["confidence"],
        "missing_information": missing,
        "forecast_summary": _forecast_summary(computed),
        "derived_features": features,
        "investigation_meta": {"engine": "deterministic-fallback", "provider": None, "model": None,
                               "generated_at": _now(), "based_on_fields": fields_seen},
    }


def _forecast_summary(computed):
    return {
        "forecast": computed.get("forecast"),
        "actual": computed.get("actual"),
        "error": computed.get("error"),
        "adherence_pct": computed.get("adherence_pct"),
        "miss_type": computed.get("direction"),
    }


def _extract_json(text):
    """Models occasionally wrap JSON in prose/fences (reasoning models especially) —
    try a direct parse, then the outermost {...} span."""
    text = (text or "").strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError("model response did not contain a JSON object")
    return json.loads(m.group(0))


def _call_openai_compatible(endpoint, api_key, model, messages, timeout=100, use_response_format=True):
    payload = {"model": model, "messages": messages, "temperature": 0.35}
    # Some NVIDIA models (e.g. nemotron-3-ultra) reject response_format with a 400/503;
    # _chat_json retries without it, and _extract_json handles loose/fenced JSON.
    if use_response_format:
        payload["response_format"] = {"type": "json_object"}
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(endpoint, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        # A normal-looking UA gets past Cloudflare bot-management (Groq returns 403/error 1010
        # to the default "Python-urllib/3.x" UA before the request reaches the API).
        "User-Agent": "Mozilla/5.0 (compatible; rca-investigation-engine/1.0)",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return payload["choices"][0]["message"]["content"]


def _chat_json(endpoint, api_key, model, messages):
    """Call the model and parse JSON. Retries once without response_format for
    models that reject it (some NVIDIA models 400/503 on response_format)."""
    try:
        raw = _call_openai_compatible(endpoint, api_key, model, messages, use_response_format=True)
    except urllib.error.HTTPError as e:
        if e.code in (400, 415, 422, 500, 503):
            raw = _call_openai_compatible(endpoint, api_key, model, messages, use_response_format=False)
        else:
            raise
    return _extract_json(raw)


def _coerce_response(parsed, context_bundle, features):
    if not isinstance(parsed, dict):
        parsed = {}
    out = dict(_RESPONSE_DEFAULTS)
    out.update({k: v for k, v in parsed.items() if k in _RESPONSE_DEFAULTS})
    computed = ((context_bundle or {}).get("target") or {}).get("computed") or {}
    out["forecast_summary"] = _forecast_summary(computed)
    out["derived_features"] = features
    # Key Findings must be objective observations, distinct from the root cause — fill from the
    # derived features if the model omitted them (or echoed the cause back), so the section never repeats.
    if not out.get("key_findings"):
        out["key_findings"] = _observations_from_features(features)
    return out


def _call_provider(slot_cfg, context_bundle, features, model_bundle):
    slot_cfg = slot_cfg or {}
    provider = slot_cfg.get("provider")
    api_key = slot_cfg.get("api_key")
    if not provider or not api_key:
        return None, "not configured"
    endpoint = slot_cfg.get("endpoint") or PROVIDER_ENDPOINTS.get(provider)
    if not endpoint:
        return None, f"unknown provider '{provider}' and no endpoint override given"
    model = slot_cfg.get("model") or DEFAULT_MODELS.get(provider)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(model_bundle, default=str)},
    ]
    try:
        parsed = _chat_json(endpoint, api_key, model, messages)
    except urllib.error.HTTPError as e:
        if e.code == 413 and (context_bundle.get("history") or context_bundle.get("peers")):
            trimmed = dict(model_bundle)
            trimmed["history"] = (model_bundle.get("history") or [])[-3:]
            trimmed["peers"] = []
            try:
                retry = [messages[0], {"role": "user", "content": json.dumps(trimmed, default=str)}]
                parsed = _chat_json(endpoint, api_key, model, retry)
            except Exception as e2:
                return None, f"{provider} error (413, trimmed retry failed): {e2}"
        else:
            detail = e.read().decode("utf-8", "replace")[:300]
            return None, f"{provider} HTTP {e.code}: {detail}"
    except Exception as e:
        return None, f"{provider} error: {e}"
    result = _coerce_response(parsed, context_bundle, features)
    result = _verify_and_fix(result, context_bundle, features)
    result["investigation_meta"] = {
        "engine": "llm", "provider": provider, "model": model, "generated_at": _now(),
        "based_on_fields": sorted(set(((context_bundle or {}).get("target") or {}).get("fields", {}).keys())),
    }
    return result, None


def _slot_for_choice(model_choice, llm_cfg):
    """Build a provider slot for a UI-selected model. api_key comes from whichever
    configured slot already holds that provider (so keys stay in config, not the UI)."""
    provider = (model_choice or {}).get("provider")
    model = (model_choice or {}).get("model")
    if not model:
        return None
    if not provider:  # infer from the model id
        provider = "groq" if model.startswith("llama-") and "/" not in model else "nvidia"
    api_key = None
    for slot in (llm_cfg or {}).values():
        if isinstance(slot, dict) and slot.get("provider") == provider and slot.get("api_key"):
            api_key = slot["api_key"]
            break
    if not api_key:
        return None
    return {"provider": provider, "api_key": api_key, "model": model,
            "endpoint": PROVIDER_ENDPOINTS.get(provider)}


def investigate(context_bundle, llm_cfg, model_choice=None):
    """Derive features, then:
      - if a specific model is chosen in the UI, run ONLY that model (no silent
        fallback to a different model — that would make the per-queue model
        comparison dishonest); on failure return the deterministic feature-based
        finding, clearly flagged with the failed model + reason.
      - otherwise run the configured primary -> secondary chain.
    Always returns a non-circular, data-backed result."""
    llm_cfg = llm_cfg or {}
    features = derive_features(context_bundle)
    model_bundle = _bundle_for_model(context_bundle, features)

    if model_choice and model_choice.get("model"):
        chosen = _slot_for_choice(model_choice, llm_cfg)
        if not chosen:
            return _placeholder_response(context_bundle, features,
                [f"Selected model '{model_choice.get('model')}' has no API key configured for its provider — "
                 "add one in backend/config.json (llm.*) or the matching *_API_KEY env var."])
        result, err = _call_provider(chosen, context_bundle, features, model_bundle)
        if result is not None:
            return result
        return _placeholder_response(context_bundle, features,
            [f"Selected model '{chosen['model']}' ({chosen['provider']}) could not be reached: {err}. "
             "Pick a different model, or this is the deterministic best-supported finding."])

    failures = []
    for name in ("primary", "secondary"):
        slot = llm_cfg.get(name) or {}
        if slot.get("provider") and slot.get("api_key"):
            result, err = _call_provider(slot, context_bundle, features, model_bundle)
            if result is not None:
                return result
            failures.append(f"{slot.get('provider')}/{slot.get('model') or DEFAULT_MODELS.get(slot.get('provider'))}: {err}")

    return _placeholder_response(context_bundle, features, [f"{f}." for f in failures] if failures else None)
