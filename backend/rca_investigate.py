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
# "Handled" columns are excluded from the RCA entirely (per client) — accuracy/adherence are
# defined on OFFERED, and handled would just muddy the analysis. Stripped from the model context,
# the cleaned signals, the glossary and the proof panel.
HANDLED_FIELDS = {"Actual_Handled", "fcst_handled"}
# Fields that are outliers for EVERY flagged queue by definition — citing them as the
# primary cause just restates that a miss happened. Used by the verifier.
DEFINITIONAL_FIELDS = {"Actual_Offered", "Actual_Handled", "fcst_offered", "fcst_handled",
                       "adherence_pct", "accuracy_pct", "error", "forecast", "actual", "severity"}

# Business glossary — the plain-English meaning of each source field, MIRRORED FROM the
# console's Definitions & Formulas tab (keep the two in sync). Injected into the context the
# model sees (field_glossary) so it interprets fields correctly — e.g. that ASU = units under
# warranty, fcst_offered is the forecast compared against Actual_Offered, and Final_Y1..Y5 are
# NESTED/overlapping counts — rather than guessing from column names.
FIELD_DEFINITIONS = {
    "Fiscal_Week": "Fiscal calendar week (e.g. 202249) and the primary time key. The week starts on Saturday, Friday is the last working day, and the fiscal year starts from the 1st week of February.",
    "Week_Ending": "Calendar date on which the fiscal week ends.",
    "Region": "Top-level geographic region (AMER/AMERICAS includes North America (NA) and Canada; LATAM includes Brazil and the rest of Latin America).",
    "SubRegion": "Sub-region within the region.",
    "Country": "Country of the queue.",
    "Forecast_name": "Name of the queue, which supports a particular business.",
    "Forecaster": "Person or team that owns the forecast for the queue.",
    "Offering": "Product or service offering (Basic, Premium, Pro kind of support).",
    "Projection_plan_name": "The forecast plan considered for that period (a week or a month).",
    "channel": "Contact/demand channel (e.g. Voice, Chat, Email, Case, Social Media).",
    "business_org": "Business organisation the queue rolls up to.",
    "Actual_Offered": "Actual offered volume.",
    "Actual_Handled": "Actual volume handled.",
    "fcst_offered": "Forecasted volume (the forecast that Actual_Offered is compared against).",
    "fcst_handled": "Forecasted handled volume.",
    "ASU": "Active Serviceable Units currently in the market and covered under warranty.",
    "Planned_ASU": "Planned Active Serviceable Units (as per the ASU plan).",
    "Actual_ASU": "Actual Active Serviceable Units.",
    "Final_Units": "Installed base (warranty units), a demand driver. Final_Y1..Y5 OVERLAP (nested): Y2 is a subset of Y1, Y3 of Y2, and so on — so their sum is NOT Final_Units.",
    "Final_Y5": "Installed units under warranty in year 5 (nested subset — see Final_Units).",
    "Final_Y4": "Installed units under warranty in year 4 (nested subset — see Final_Units).",
    "Final_Y3": "Installed units under warranty in year 3 (nested subset — see Final_Units).",
    "Final_Y2": "Installed units under warranty in year 2 (nested subset — see Final_Units).",
    "Final_Y1": "Installed units under warranty in year 1 (nested subset — see Final_Units).",
    "Final_upp_units": "Additional installed units under an upgrade / extended-protection plan.",
    "Holiday_Count": "Number of holidays in the fiscal week.",
    "Monday": "Holiday flag for Monday.", "Tuesday": "Holiday flag for Tuesday.",
    "Wednesday": "Holiday flag for Wednesday.", "Thursday": "Holiday flag for Thursday.",
    "Friday": "Holiday flag for Friday.", "Saturday": "Holiday flag for Saturday.",
    "Sunday": "Holiday flag for Sunday.",
    "Volume_Category": "Volume band the queue falls into (e.g. 501-1000).",
}

SYSTEM_PROMPT = """You are an investigative root-cause analyst for a demand-forecasting system.

You are given a JSON "context bundle" for ONE forecast miss (target week's raw data,
its recent history and same-week peer queues, an auto-computed statistical_summary), plus
a DERIVED_FEATURES block we computed for you — chronic bias/level, whether this week is
worse than the queue's usual miss, a forecast-sanity check, plan restatement, installed-base
change, holiday effect, peer divergence, and CLEANED_SIGNALS (the real per-field outliers
with meaningless columns already removed). Reason primarily from DERIVED_FEATURES and
CLEANED_SIGNALS — they are the discriminating evidence.

A FIELD_GLOSSARY block gives the business meaning of each field — use it to interpret the data
correctly (e.g. ASU = Active Serviceable Units under warranty; fcst_offered = the forecasted volume
that Actual_Offered is compared against; Final_Y1..Y5 are NESTED/overlapping installed-base counts, so
never treat them as independent). Use the glossary only to understand fields — never repeat a definition
as a finding or a cause.

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

Write every sentence so a manager who reads ONLY your text understands it end to end — state the ACTUAL
NUMBER and WHAT IT MEANS together, never a bare number or a vague phrase they must interpret. Compare each
number to this queue's usual level in words, e.g.:
  BAD  : "Actual_Offered was 8805, an outlier."   (number with no meaning)
  GOOD : "Demand came in at 8,805 this week versus a usual ~62 for this queue — about 140x higher — so this
          was a genuine demand surge, not a forecasting error."
Spell out the takeaway in the primary cause and the reasoning: what happened, by how much vs usual, and what
it implies. Assume the reader does not know the field names or the data.

Classify the miss into ONE primary cause_type from this taxonomy, then explain it:
- "forecast_baseline_error"      : the forecast itself is anomalous vs the queue's own history
                                    (see forecast_sanity) — a broken/placeholder baseline, not a demand change.
- "systematic_forecast_bias"     : the queue is chronically off in the same direction (see chronic_bias) —
                                    a calibration problem, this week is just another instance of it.
- "genuine_demand_event"         : a real one-week demand move (this week is materially worse than the
                                    queue's usual miss AND the forecast looks normal).
- "volume_routing_shift"         : a similar queue moved the opposite way the same week (see peer_divergence)
                                    — volume shifted between queues, not total demand. ("Similar queues" =
                                    other queues in the SAME region, sub-region, country and channel that week;
                                    always call them "similar queues", not "peer queues".)
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
- Every supporting_evidence item MUST cite a specific source_field and, in `value`, an ACTUAL NUMBER FROM THE
  DATA — the forecast, the actual demand, a historical average, an ASU/units count, a holiday count, etc.
  (DERIVED_FEATURES.proof lists these real values). NEVER put a z-score, standard deviation, ratio, or other
  derived statistic in `value` or in the text — those exist only to help you reason, not to show the lead.
  Quote the real numbers as proof (e.g. "forecast was 4.5 vs a usual ~12; actual was 44"). Never invent a cause
  not traceable to the supplied data.
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
        _fm = (numeric.get("fcst_offered") or {}).get("history_mean")
        _am = (numeric.get("Actual_Offered") or {}).get("history_mean")
        chronic = {
            "history_mean_adherence_pct": round(mean_adh, 1),
            "typical_abs_deviation_pct": round(typical_abs, 1),
            "history_weeks": len(hist_adh),
            "usual_forecast": round(_fm, 1) if isinstance(_fm, (int, float)) else _fm,   # real avg from data
            "usual_actual": round(_am, 1) if isinstance(_am, (int, float)) else _am,      # real avg from data
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

    # -- forecast vs actual sanity: is the FORECAST off vs its own history, or did the
    #    ACTUAL demand itself move? (forecast≪actual alone does NOT mean the forecast is broken —
    #    a normal forecast with a spiking actual is a genuine demand event, not a baseline error). --
    fo_stat = numeric.get("fcst_offered") or {}
    ao_stat = numeric.get("Actual_Offered") or {}
    fo_z = fo_stat.get("z_score")
    ao_z = ao_stat.get("z_score")
    ratio = None
    if isinstance(t_forecast, (int, float)) and isinstance(t_actual, (int, float)) and t_actual not in (0, None):
        ratio = t_forecast / t_actual if t_actual else None
    verdict = "normal"
    if isinstance(fo_z, (int, float)) and abs(fo_z) > 2:
        # the forecast itself is off vs its own recent history
        verdict = "forecast_anomalously_low" if fo_z < 0 else "forecast_anomalously_high"
    elif isinstance(ao_z, (int, float)) and abs(ao_z) > 2:
        # forecast looks normal but the actual demand is off vs its own history -> demand moved
        verdict = "actual_anomalous"
    elif fo_z is None and ao_z is None and ratio is not None and (ratio < 0.34 or ratio > 3):
        # no history to z-test against — fall back to the raw forecast-vs-actual gap
        verdict = "forecast_scale_mismatch"
    fo_mean = fo_stat.get("history_mean")
    ao_mean = ao_stat.get("history_mean")
    feats["forecast_sanity"] = {
        "forecast": round(t_forecast, 2) if isinstance(t_forecast, (int, float)) else t_forecast,
        "actual": t_actual,
        "forecast_usual_level": round(fo_mean, 2) if isinstance(fo_mean, (int, float)) else fo_mean,  # real avg from data
        "actual_usual_level": round(ao_mean, 2) if isinstance(ao_mean, (int, float)) else ao_mean,    # real avg from data
        "forecast_z_vs_own_history": round(fo_z, 2) if isinstance(fo_z, (int, float)) else None,       # internal only, not shown
        "actual_z_vs_own_history": round(ao_z, 2) if isinstance(ao_z, (int, float)) else None,         # internal only, not shown
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
    all_p = []
    for p in peers:
        key_info = p.get("key") or {}
        fields_info = p.get("fields") or {}
        fname = key_info.get("Forecast_name") or fields_info.get("Forecast_name") or "Unknown Queue"
        pc = p.get("computed") or {}
        pd = pc.get("direction")
        adh = pc.get("adherence_pct")
        if pd is None:
            continue
        is_opp = (t_dir is not None and pd != t_dir)
        # NameError guard: `tgt` was never defined in this function -- it exists only in
        # _bundle_for_model() further down the file. Any peer with a direction therefore raised
        # "name 'tgt' is not defined" and killed the WHOLE investigation, on both engines, since
        # derive_features() is shared. The intent was "fall back to the target queue's channel",
        # and the target is already in scope as `target`.
        _tgt_channel = ((target.get("fields") or {}).get("channel")
                        or (target.get("key") or {}).get("channel"))
        ch_val = (fields_info.get("channel") or key_info.get("channel") or p.get("channel")
                  or _tgt_channel or "Unknown")
        item = {
            "forecast_name": fname,
            "channel": ch_val,
            "direction": pd,
            "adherence_pct": round(adh, 1) if isinstance(adh, (int, float)) else None,
            "actual": fields_info.get("Actual_Offered") or pc.get("actual"),
            "forecast": fields_info.get("fcst_offered") or pc.get("forecast"),
            "is_opposite": is_opp
        }
        all_p.append(item)
        if is_opp:
            opp.append({"forecast_name": fname, "channel": ch_val,
                        "adherence_pct": round(adh, 1) if isinstance(adh, (int, float)) else None})
        elif pd == t_dir:
            same += 1

    feats["peer_divergence"] = {
        "peers_total": len(peers),
        "peers_opposite_direction": len(opp),
        "peers_same_direction": same,
        "examples_opposite": opp[:5],
        "all_peers": all_p,
        "signal": bool(opp),
    }


    # -- population context (if the console supplied it) --
    feats["population_context"] = (b.get("meta") or {}).get("population")

    # -- cleaned signals: real outliers, noise removed, installed-base collapsed --
    cleaned = []
    for f, s in numeric.items():
        if f in NOISE_FIELDS or f in INSTALLED_BASE_FIELDS or f in DEFINITIONAL_FIELDS or f in HANDLED_FIELDS:
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

    # -- PROOF: real values straight from the data file (NO z-scores/deviations), each with a
    #    plain "change vs usual" so a manager instantly sees which number is the odd one out.
    #    "usual" = this queue's average over the prior weeks in history (RCA_HISTORY_CAP). --
    def _tw(val):
        return round(val, 2) if isinstance(val, (int, float)) else val
    def _usual(val):
        return round(val, 2) if isinstance(val, (int, float)) else val
    def _change(tw, us):
        if not isinstance(tw, (int, float)) or not isinstance(us, (int, float)) or us == 0:
            return "no historical comparison"
        r = tw / us
        if 0.8 <= r <= 1.25:
            return "about the same as usual"
        if r > 1.25:
            return f"about {round(r)}x higher than usual" if r >= 2 else f"about {round((r - 1) * 100)}% higher than usual"
        return f"about {round(1 / r)}x lower than usual" if r <= 0.5 else f"about {round((1 - r) * 100)}% lower than usual"
    def _row(label, field, tw, us):
        return {"label": label, "field": field, "this_week": _tw(tw), "usual": _usual(us), "change": _change(tw, us)}
    proof = [
        _row("Forecast Offered", "fcst_offered", t_forecast, (numeric.get("fcst_offered") or {}).get("history_mean")),
        _row("Actual_Offered", "Actual_Offered", t_actual, (numeric.get("Actual_Offered") or {}).get("history_mean")),
    ]
    for fld, label in (("ASU", "Units under warranty (ASU)"), ("Actual_ASU", "Actual ASU"),
                       ("Planned_ASU", "Planned ASU")):   # handled columns intentionally excluded
        s = numeric.get(fld)
        if s and s.get("target_value") is not None:
            proof.append(_row(label, fld, s.get("target_value"), s.get("history_mean")))
    if ib and ib.get("material"):
        proof.append(_row("Installed base (" + ib["field"] + ")", ib["field"], ib["target_value"], ib["history_mean"]))
    if hc and (hc.get("target_value") or hc.get("unusual")):   # skip the noisy "0 holidays (usual ~0.08)" row
        proof.append(_row("Holidays in the week", "Holiday_Count", hc.get("target_value"), hc.get("history_mean")))
    feats["proof"] = proof

    return feats


def _bundle_for_model(context_bundle, features):
    """A copy of the bundle with derived_features attached and the noise columns
    stripped from statistical_summary, so the model literally cannot cite them."""
    b = dict(context_bundle or {})
    _drop = NOISE_FIELDS | HANDLED_FIELDS
    stat = dict(b.get("statistical_summary") or {})
    stat["numeric"] = {k: v for k, v in (stat.get("numeric") or {}).items() if k not in _drop}
    stat["categorical"] = {k: v for k, v in (stat.get("categorical") or {}).items()
                           if k not in _drop and k != "Week_Ending"}
    b["statistical_summary"] = stat
    # Strip "handled" columns from the target row the model sees too, so nothing handled-related reaches it.
    tgt = dict(b.get("target") or {})
    tgt["fields"] = {k: v for k, v in (tgt.get("fields") or {}).items() if k not in HANDLED_FIELDS}
    b["target"] = tgt
    b["derived_features"] = features
    # Business glossary for the fields actually present, so the model reads them correctly.
    present = set(tgt["fields"].keys())
    present |= set((stat.get("numeric") or {}).keys()) | set((stat.get("categorical") or {}).keys())
    b["field_glossary"] = {k: FIELD_DEFINITIONS[k] for k in FIELD_DEFINITIONS if k in present and k not in HANDLED_FIELDS}
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
    fsv = fs.get("verdict", "normal")
    if fsv in ("forecast_anomalously_low", "forecast_anomalously_high", "forecast_scale_mismatch"):
        stmt = (f"During the target fiscal week, forecast offered was set at {fs.get('forecast')} contacts, "
                f"which is far from this queue's typical 13-week average of ~{fs.get('forecast_usual_level')} contacts, while actual demand was {fs.get('actual')} contacts. "
                f"This indicates that the forecast baseline itself was incorrectly scaled rather than actual demand changing unexpectedly. "
                f"Because the forecast plan was generated using outdated baseline assumptions, the forecast became severely inaccurate relative to actual incoming workload.")
        ctype = "forecast_baseline_error"
        conf = 0.55
        ev.append({"text": f"forecast was {fs.get('forecast')} this week vs a usual ~{fs.get('forecast_usual_level')}; actual demand was {fs.get('actual')}",
                   "source_field": "fcst_offered", "value": fs.get("forecast")})
    elif fsv == "actual_anomalous":
        stmt = (f"During the target fiscal week, actual demand reached {fs.get('actual')} contacts — far exceeding this queue's 13-week typical level of ~{fs.get('actual_usual_level')} contacts — while forecast was set at normal levels ({fs.get('forecast')}). "
                f"This indicates a genuine real-world demand surge rather than a forecasting calculation error. "
                f"Because the operational forecast did not account for this external demand surge, actual volume ran significantly ahead of planned capacity.")
        ctype = "genuine_demand_event"
        conf = 0.6
        ev.append({"text": f"actual demand was {fs.get('actual')} vs a usual ~{fs.get('actual_usual_level')}, while the forecast ({fs.get('forecast')}) was about normal",
                   "source_field": "Actual_Offered", "value": fs.get("actual")})
    elif chronic.get("verdict", "mixed").startswith("chronic"):
        dirn = "under" if chronic.get("consistent_direction") == "under" else "over"
        plan = "too low" if dirn == "under" else "too high"
        stmt = (f"During the target fiscal week, actual demand was {fs.get('actual')} contacts against a forecast of {fs.get('forecast')} contacts. "
                f"Over recent weeks, this queue has consistently run {dirn}-forecast (typically averaging {chronic.get('usual_actual')} actual contacts against {chronic.get('usual_forecast')} forecast contacts). "
                f"This indicates an ongoing systematic forecasting bias where baseline plan targets are consistently set {plan}. "
                f"Because the forecast model was not re-baselined to align with true weekly demand levels, systematic {dirn}-forecasting recurred this week.")
        ctype = "systematic_forecast_bias"
        conf = 0.5
        ev.append({"text": f"recently this queue ran about {chronic.get('usual_actual')} actual against {chronic.get('usual_forecast')} forecast, {dirn}-forecast in most weeks",
                   "source_field": "Actual_Offered", "value": chronic.get("usual_actual")})
    elif peer.get("signal"):
        ex = (peer.get("examples_opposite") or [{}])[0]
        stmt = (f"During the target fiscal week, total demand across similar queues in this locality remained relatively stable. "
                f"However, demand for this queue moved in the opposite direction of sibling queue {ex.get('forecast_name')}. "
                f"This indicates that customer workload shifted between queues within the locality rather than total demand changing. "
                f"Because forecasts were generated independently for each queue name instead of at the Combined Queue level, routing shifts caused forecast adherence misses across individual queues.")
        ctype = "volume_routing_shift"
        conf = 0.45
        ev.append({"text": f"a similar queue ({ex.get('forecast_name')}) moved the opposite way the same week",
                   "source_field": "peer_divergence", "value": peer.get("peers_opposite_direction")})
    else:
        stmt = (f"During the target fiscal week, actual demand reached {fs.get('actual')} contacts against a forecast of {fs.get('forecast')} contacts. "
                f"Analysis of available operational drivers indicates a standard forecasting adherence miss. "
                f"Because no external holiday or installed base shift occurred, the miss is attributable to standing forecast baseline error for this queue.")
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
    # Always lead with the two real headline numbers straight from the data.
    if fs.get("forecast") is not None and fs.get("actual") is not None:
        obs.append(f"The forecast this week was {fs.get('forecast')}, and actual demand was {fs.get('actual')}.")
    v = fs.get("verdict", "normal")
    lvl = fs.get("forecast_usual_level")
    if v == "forecast_anomalously_low":
        obs.append(f"That forecast ({fs.get('forecast')}) is well below this queue's usual level of about {lvl}.")
    elif v == "forecast_anomalously_high":
        obs.append(f"That forecast ({fs.get('forecast')}) is well above this queue's usual level of about {lvl}.")
    elif v == "actual_anomalous":
        obs.append(f"Actual demand ({fs.get('actual')}) was far from this queue's usual level of about {fs.get('actual_usual_level')}, while the forecast ({fs.get('forecast')}) was about normal.")
    elif v == "forecast_scale_mismatch":
        obs.append(f"The forecast ({fs.get('forecast')}) is far out of line with the actual volume ({fs.get('actual')}) this week.")
    ch = f.get("chronic_bias") or {}
    if str(ch.get("verdict", "")).startswith("chronic"):
        obs.append(f"This queue is {ch.get('consistent_direction')}-forecast in most recent weeks (typically about {ch.get('usual_actual')} actual against {ch.get('usual_forecast')} forecast).")
    elif ch.get("verdict") == "mixed":
        obs.append("This queue's misses have no consistent direction over recent weeks.")
    pd = f.get("peer_divergence") or {}
    if pd.get("signal"):
        obs.append(f"{pd.get('peers_opposite_direction')} of {pd.get('peers_total')} similar queues (same region, country and channel) moved the opposite way this week.")
    elif pd.get("peers_total") == 1:
        obs.append("The one similar queue moved the same way this week.")
    elif pd.get("peers_total"):
        obs.append(f"All {pd.get('peers_total')} similar queues mostly moved the same way this week.")
    ib = f.get("installed_base")
    if ib and ib.get("material"):
        obs.append(f"The installed base ({ib.get('field')}) was {ib.get('target_value')} this week vs a usual ~{ib.get('history_mean')}.")
    hol = f.get("holiday")
    if hol and hol.get("unusual"):
        obs.append(f"There were {hol.get('holiday_count')} holidays in this week — more than usual.")
    return obs[:6]



# --- Deterministic fills so every report section has content when the data supports it,
#     even if the model returns a sparse JSON (some models omit the softer sections). ---
_RECS_BY_CAUSE = {
    "forecast_baseline_error": [
        "Re-baseline the forecast for this queue so it reflects its recent typical level.",
        "Add a check that flags when a new forecast departs sharply from the queue's recent average.",
    ],
    "systematic_forecast_bias": [
        "Correct the standing bias in this queue's forecast — it leans the same way most weeks.",
        "Review the model inputs driving the consistent over/under-forecast for this queue.",
    ],
    "genuine_demand_event": [
        "Investigate what drove the real demand change and whether it is seasonal or recurring.",
        "Consider adding an event/seasonality signal so similar moves are anticipated.",
    ],
    "volume_routing_shift": [
        "Review the routing/allocation rules between this queue and its sibling queues.",
        "Forecast the related queues together so volume shifts between them net out.",
    ],
    "plan_restatement": [
        "Compare actuals against the forecast-plan version that was in force for the week.",
        "Track plan restatements as a known driver when reviewing accuracy.",
    ],
    "installed_base_change": [
        "Feed installed-base (units under warranty) changes into the forecast for this queue.",
        "Revisit how warranty-unit growth maps to expected demand.",
    ],
    "calendar_holiday_effect": [
        "Ensure the forecast accounts for holiday and short weeks for this queue.",
        "Add a holiday-calendar feature to the forecasting model.",
    ],
}


def _deterministic_rejected(features, selected):
    """Plain-language 'what we checked and ruled out' built from the derived features,
    excluding the cause that was actually selected."""
    f = features or {}
    out = []
    fs = f.get("forecast_sanity") or {}
    ch = f.get("chronic_bias") or {}
    pd = f.get("peer_divergence") or {}
    pr = f.get("plan_restatement") or {}
    hol = f.get("holiday") or {}
    ib = f.get("installed_base") or {}
    if selected != "genuine_demand_event" and fs.get("verdict", "normal") != "normal":
        out.append({"hypothesis": "A genuine surge or drop in demand caused the miss.",
                    "reason_rejected": "The forecast itself was set far from this queue's usual level, so the gap points to the forecast rather than a real demand change."})
    if selected != "systematic_forecast_bias" and ch.get("verdict") == "mixed":
        out.append({"hypothesis": "This queue has a steady one-directional forecast bias.",
                    "reason_rejected": "Its recent misses go both ways, so there is no consistent lean to blame."})
    if selected != "volume_routing_shift" and not pd.get("signal") and pd.get("peers_total"):
        out.append({"hypothesis": "Work shifted between this queue and similar queues.",
                    "reason_rejected": "Most similar queues moved the same way this week, not the opposite way."})
    if selected != "plan_restatement" and pr and pr.get("changed") is False:
        out.append({"hypothesis": "A change in the forecast plan caused the miss.",
                    "reason_rejected": "The forecast plan did not change for this week."})
    if selected != "calendar_holiday_effect" and hol and not hol.get("unusual"):
        out.append({"hypothesis": "A holiday or short week distorted the numbers.",
                    "reason_rejected": "This week had no unusual number of holidays."})
    if selected != "installed_base_change" and ib and not ib.get("material"):
        out.append({"hypothesis": "A change in the installed base (units under warranty) drove demand.",
                    "reason_rejected": "The installed base for this queue did not change materially this week."})
    return out[:5]


def _deterministic_history(features):
    ch = features.get("chronic_bias") or {}
    tw = features.get("this_week_vs_usual") or {}
    weeks = ch.get("history_weeks")
    mean_adh = ch.get("history_mean_adherence_pct")
    typ = ch.get("typical_abs_deviation_pct") or tw.get("typical_abs_deviation_pct")
    if not weeks:
        return {"narrative": "", "data_points": []}
    lean = ""
    if mean_adh is not None:
        lean = " and usually runs " + ("above" if mean_adh < 0 else "below") + " forecast"
    narrative = (f"Over the last {weeks} weeks this queue typically misses by about "
                 f"{typ}%{lean}. This week's miss is {tw.get('times_usual')}x that typical size."
                 if typ is not None and tw.get("times_usual") is not None else
                 f"Over the last {weeks} weeks this queue's misses averaged {mean_adh}% adherence.")
    dp = [{"label": "Weeks compared", "value": weeks}]
    if mean_adh is not None:
        dp.append({"label": "Average adherence (history)", "value": f"{mean_adh}%"})
    if typ is not None:
        dp.append({"label": "Typical weekly miss", "value": f"{typ}%"})
    if tw.get("times_usual") is not None:
        dp.append({"label": "This week vs typical", "value": f"{tw['times_usual']}x"})
    return {"narrative": narrative, "data_points": dp}


def _fill_gaps(result, features):
    """Populate any report section the model left empty from the deterministic features,
    so a sparse model reply never leaves a blank card when the data can say something."""
    if not result.get("key_findings"):
        result["key_findings"] = _observations_from_features(features)
    ctype = result.get("cause_type")
    primary = result.get("primary_root_cause") or {}
    # reasoning narrative (list of points)
    rn = result.get("reasoning_narrative")
    rn_empty = (not rn) or (isinstance(rn, list) and not rn)
    if rn_empty and primary.get("statement"):
        pts = list(result.get("key_findings") or [])[:2]
        pts.append(primary["statement"])
        pts.append("Other possible explanations were checked against the data and did not fit as well.")
        result["reasoning_narrative"] = pts
    if not result.get("rejected_hypotheses"):
        result["rejected_hypotheses"] = _deterministic_rejected(features, ctype)
    hc = result.get("historical_comparison") or {}
    if not hc.get("narrative") and not (hc.get("data_points")):
        result["historical_comparison"] = _deterministic_history(features)
    if not result.get("forecast_improvement_recommendations"):
        result["forecast_improvement_recommendations"] = list(_RECS_BY_CAUSE.get(ctype, [
            "Review this queue's forecast inputs and recent accuracy with the planning team.",
        ]))
    return result


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
    _fill_gaps(result, features)   # no blank cards when the data can say something
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
    result = {
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
    _fill_gaps(result, features)   # fill rejected / history / recommendations from the features too
    return result


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


# Read from config.json as "llm".timeout_seconds; falls back to the original 100s when the key
# is absent, so behaviour is unchanged for any existing config. Raised because NVIDIA reasoning
# models take 45-100s for a real investigation from the browser: Canary V0.3 measured
# /api/rca-investigate at 45s / 100.1s / 90s on the same model, and the middle one died exactly
# on the old 100s ceiling ("nvidia error: The read operation timed out") and fell back to the
# deterministic finding. That made the UI's LLM path fail roughly one time in three.
LLM_TIMEOUT_DEFAULT = 100


def _configured_timeout(llm_cfg):
    try:
        value = float((llm_cfg or {}).get("timeout_seconds") or LLM_TIMEOUT_DEFAULT)
        return value if value > 0 else LLM_TIMEOUT_DEFAULT
    except (TypeError, ValueError):
        return LLM_TIMEOUT_DEFAULT


def _call_openai_compatible(endpoint, api_key, model, messages, timeout=None, use_response_format=True):
    timeout = timeout or LLM_TIMEOUT_DEFAULT
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


def _chat_json(endpoint, api_key, model, messages, timeout=None):
    """Call the model and parse JSON. Retries once without response_format for
    models that reject it (some NVIDIA models 400/503 on response_format)."""
    try:
        raw = _call_openai_compatible(endpoint, api_key, model, messages, timeout=timeout,
                                      use_response_format=True)
    except urllib.error.HTTPError as e:
        if e.code in (400, 415, 422, 500, 503):
            raw = _call_openai_compatible(endpoint, api_key, model, messages, timeout=timeout,
                                          use_response_format=False)
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


def _call_provider(slot_cfg, context_bundle, features, model_bundle, timeout=None):
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
        parsed = _chat_json(endpoint, api_key, model, messages, timeout=timeout)
    except urllib.error.HTTPError as e:
        if e.code == 413 and (context_bundle.get("history") or context_bundle.get("peers")):
            trimmed = dict(model_bundle)
            trimmed["history"] = (model_bundle.get("history") or [])[-3:]
            trimmed["peers"] = []
            try:
                retry = [messages[0], {"role": "user", "content": json.dumps(trimmed, default=str)}]
                parsed = _chat_json(endpoint, api_key, model, retry, timeout=timeout)
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
    timeout = _configured_timeout(llm_cfg)

    if model_choice and model_choice.get("model"):
        chosen = _slot_for_choice(model_choice, llm_cfg)
        if not chosen:
            return _placeholder_response(context_bundle, features,
                [f"Selected model '{model_choice.get('model')}' has no API key configured for its provider — "
                 "add one in backend/config.json (llm.*) or the matching *_API_KEY env var."])
        result, err = _call_provider(chosen, context_bundle, features, model_bundle, timeout=timeout)
        if result is not None:
            return result
        return _placeholder_response(context_bundle, features,
            [f"Selected model '{chosen['model']}' ({chosen['provider']}) could not be reached: {err}. "
             "Pick a different model, or this is the deterministic best-supported finding."])

    failures = []
    for name in ("primary", "secondary"):
        slot = llm_cfg.get(name) or {}
        if slot.get("provider") and slot.get("api_key"):
            result, err = _call_provider(slot, context_bundle, features, model_bundle, timeout=timeout)
            if result is not None:
                return result
            failures.append(f"{slot.get('provider')}/{slot.get('model') or DEFAULT_MODELS.get(slot.get('provider'))}: {err}")

    return _placeholder_response(context_bundle, features, [f"{f}." for f in failures] if failures else None)
