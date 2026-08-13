# -*- coding: utf-8 -*-
"""The fixed hypothesis catalogue -- what the engine is allowed to consider.

Implements `FC_RCA_RCA_Methodology.md` section 12.

WHY THIS MODULE EXISTS
----------------------
The engine had no catalogue. The LLM was handed the payload and asked what might have
caused the miss, which means the set of things considered changed between runs of the
same investigation -- a paraphrase produces a different hypothesis, and two runs test
different things. That is why the output was never reproducible.

Here the candidate set is DETERMINISTIC: 23 entries in 6 categories, each with an
applicability condition evaluated against the features. The model is never asked what to
consider. Per the spec:

    The engine shall NOT generate a hypothesis outside the catalogue. Any observed
    pattern with no matching entry is recorded as an UNEXPLAINED OBSERVATION and
    surfaced for catalogue extension -- never converted into an ad-hoc hypothesis.

FOUR STATES, NEVER CONFLATED
-----------------------------
Version 1.0.0 collapsed these together. They support opposite actions, so the
Explainability Framework requires them to remain visually distinct:

    GENERATED       applicable to this queue -- goes forward for testing
    NOT_APPLICABLE  never relevant to this queue (no ASU exposure, aggregate country...)
    SUPPRESSED      blocked by a data-quality gate -- COULD have been tested, was not
    REJECTED        tested against evidence and ruled out

"Could not be tested" and "tested and ruled out" must never look the same. The first says
go and get the data; the second says stop looking here.

WHY NOT-GENERATED ENTRIES ARE RECORDED
---------------------------------------
Every catalogue entry that does not fire is recorded WITH ITS FAILING CONDITION. A silent
absence tells a business lead nothing; "Installed Base Change was not considered because
this queue has no ASU exposure" tells them the engine looked and why it stopped.

KNOWN GAPS -- deliberately absent from the catalogue
-----------------------------------------------------
Product Lifecycle (needs a product identifier, launch date and lifecycle stage) and
Manual Override (needs a forecast version dimension) are NOT catalogue entries. Neither
is implementable against the current source data, and holding them as permanently
inapplicable entries would put two dead rows on every Decision Card forever.

Note on `Offering`: it is a SUPPORT TIER (Basic / Pro / Premium / OOP), not a product.
Basic support did not launch and will not reach end-of-life. It shall never be used as a
product or lifecycle proxy.
"""

# --- States -------------------------------------------------------------------
GENERATED = "Generated"
NOT_APPLICABLE = "NotApplicable"
SUPPRESSED = "Suppressed"
REJECTED = "Rejected"

CATALOGUE_VERSION = "2.0.0"

# --- Categories ---------------------------------------------------------------
CALENDAR = "Calendar"
DEMAND = "Demand"
FORECAST = "Forecast"
BUSINESS = "Business"
STATISTICAL = "Statistical"
DATA_QUALITY = "Data Quality"


def _h(hid, category, name, condition_text, predicate, metrics, evidence_types):
    """One catalogue entry.

    `metrics` is what gets EXECUTED if this hypothesis is generated -- the spec forbids
    running statistics exhaustively (Statistical Framework principle 4), so the hypothesis
    selects its own tests rather than the engine computing everything and hunting.
    """
    return {"id": hid, "category": category, "name": name,
            "condition": condition_text, "predicate": predicate,
            "metrics": metrics, "evidence_types": evidence_types}


def _g(f, *path, default=None):
    """Safe nested get across the feature dict."""
    cur = f
    for p in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(p)
    return cur if cur is not None else default


# ==============================================================================
# THE CATALOGUE -- 23 entries, 6 categories
# ==============================================================================
CATALOGUE = [
    # ---- Calendar ----
    _h("CAL-01", CALENDAR, "Holiday",
       "Holiday_Count > 0 in the period or its impact window",
       lambda f: (_g(f, "period", "holiday_count", default=0) or 0) > 0
                 or bool(_g(f, "period", "holiday_in_impact_window")),
       ["holiday_anchored_comparison", "seasonality"],
       ["deterministic_statistic", "business_rule"]),

    _h("CAL-02", CALENDAR, "Fiscal Month Transition",
       "period spans a fiscal month boundary",
       lambda f: bool(_g(f, "period", "spans_month_boundary")),
       ["period_comparison"], ["business_rule"]),

    _h("CAL-03", CALENDAR, "Quarter Transition",
       "period spans a fiscal quarter boundary",
       lambda f: bool(_g(f, "period", "spans_quarter_boundary")),
       ["period_comparison"], ["business_rule"]),

    _h("CAL-04", CALENDAR, "Seasonality",
       ">= 104 weeks of history and the period is complete",
       lambda f: (_g(f, "history", "weeks_of_actuals", default=0) or 0) >= 104
                 and bool(_g(f, "period", "complete", default=True)),
       ["seasonality", "trend"], ["deterministic_statistic"]),

    # ---- Demand ----
    _h("DEM-01", DEMAND, "Demand Spike",
       "actual exceeds forecast beyond the volatility band",
       lambda f: (_g(f, "deviation", "adherence_pct") is not None
                  and _g(f, "deviation", "adherence_pct") < 0
                  and bool(_g(f, "deviation", "beyond_volatility_band"))),
       ["outlier_detection", "variability"], ["deterministic_statistic"]),

    _h("DEM-02", DEMAND, "Demand Drop",
       "actual falls below forecast beyond the volatility band",
       lambda f: (_g(f, "deviation", "adherence_pct") is not None
                  and _g(f, "deviation", "adherence_pct") > 0
                  and bool(_g(f, "deviation", "beyond_volatility_band"))),
       ["outlier_detection", "variability"], ["deterministic_statistic"]),

    _h("DEM-03", DEMAND, "Demand Shift",
       "adjacent periods show offsetting deviations",
       lambda f: bool(_g(f, "deviation", "adjacent_offsetting")),
       ["period_comparison", "momentum"], ["deterministic_statistic"]),

    _h("DEM-04", DEMAND, "Volume Redistribution",
       "related queues show inverse deviations in the same period",
       lambda f: bool(_g(f, "related_queues", "inverse_deviation")),
       ["cross_queue_comparison"], ["deterministic_statistic"]),

    # ---- Forecast ----
    _h("FC-01", FORECAST, "Forecast Bias",
       "consistent one-sided deviation across recent periods",
       lambda f: bool(_g(f, "forecast", "one_sided_bias")),
       # plan_vs_seasonal_norm belongs here: "the plan was set away from the level this week of the
       # year reliably brings" is a forecast defect. Without it the plan-level finding had no
       # hypothesis to attach to and could never become the reported cause.
       ["bias", "error_metrics", "plan_vs_seasonal_norm"], ["deterministic_statistic"]),

    _h("FC-02", FORECAST, "Trend Misidentification",
       "trend direction in actuals differs from the forecast",
       lambda f: bool(_g(f, "forecast", "trend_direction_mismatch")),
       ["trend", "momentum"], ["deterministic_statistic"]),

    # ---- Business ----
    _h("BUS-01", BUSINESS, "Warranty Mix Shift",
       "warranty Tier A or B, shipment exposure, and the driver passes the relevance gate",
       lambda f: (_g(f, "warranty", "tier") in ("A", "B")
                  and bool(_g(f, "warranty", "shipment_applicable"))
                  and bool(_g(f, "warranty", "passes_relevance_gate"))),
       ["correlation", "warranty_band_comparison"],
       ["deterministic_statistic", "business_rule"]),

    _h("BUS-02", BUSINESS, "Installed Base Change",
       "ASU exposure, passes the relevance gate, and a baseline is available",
       lambda f: (bool(_g(f, "asu", "applicable"))
                  and bool(_g(f, "asu", "passes_relevance_gate"))
                  and bool(_g(f, "asu", "baseline_available"))),
       ["correlation", "asu_level_comparison"],
       ["deterministic_statistic", "business_rule"]),

    _h("BUS-03", BUSINESS, "ASU Plan Variance",
       "both Planned_ASU and Actual_ASU present and the gate passes",
       lambda f: (_g(f, "asu", "planned") is not None
                  and _g(f, "asu", "actual") is not None
                  and bool(_g(f, "asu", "passes_plan_variance_gate"))),
       ["driver_decomposition"], ["deterministic_statistic"]),

    _h("BUS-04", BUSINESS, "Shipment Volume Change",
       "shipment exposure and the driver passes the relevance gate",
       lambda f: (bool(_g(f, "shipments", "applicable"))
                  and bool(_g(f, "shipments", "passes_relevance_gate"))),
       ["correlation", "empirical_lag"], ["deterministic_statistic"]),

    _h("BUS-05", BUSINESS, "Queue Migration",
       "a lineage event exists, or a related queue shows an inverse deviation",
       lambda f: (bool(_g(f, "lineage", "event_in_period"))
                  or bool(_g(f, "related_queues", "inverse_deviation"))),
       ["cross_queue_comparison"], ["business_rule", "deterministic_statistic"]),

    # ---- Statistical ----
    _h("STA-01", STATISTICAL, "Outlier",
       "period value exceeds the outlier bounds",
       lambda f: bool(_g(f, "statistics", "target_is_outlier")),
       ["outlier_detection"], ["deterministic_statistic"]),

    _h("STA-02", STATISTICAL, "Drift",
       "structural change detected in the series",
       lambda f: bool(_g(f, "statistics", "drift_material")),
       ["drift"], ["deterministic_statistic"]),

    _h("STA-03", STATISTICAL, "Momentum Shift",
       "rate of change altered materially",
       lambda f: bool(_g(f, "statistics", "momentum_material")),
       ["momentum"], ["deterministic_statistic"]),

    _h("STA-04", STATISTICAL, "Variance Expansion",
       "volatility increased beyond the historical band",
       lambda f: bool(_g(f, "statistics", "variance_expanded")),
       ["variability"], ["deterministic_statistic"]),

    # ---- Data Quality ----
    _h("DQ-01", DATA_QUALITY, "Missing Data",
       "a mandatory field is blank in the period",
       lambda f: (_g(f, "data_quality", "mandatory_blank_count", default=0) or 0) > 0,
       ["completeness"], ["business_rule"]),

    _h("DQ-02", DATA_QUALITY, "Incorrect Mapping",
       "a dimension value is unmapped or newly appeared",
       lambda f: bool(_g(f, "data_quality", "unmapped_dimension")),
       ["mapping_check"], ["business_rule"]),

    _h("DQ-03", DATA_QUALITY, "Duplicate Records",
       "a duplicate was detected at the expected grain",
       lambda f: bool(_g(f, "data_quality", "duplicates_detected")),
       ["duplicate_check"], ["business_rule"]),

    _h("DQ-04", DATA_QUALITY, "Insufficient History",
       "fewer than 104 weeks of actuals for this queue",
       lambda f: (_g(f, "history", "weeks_of_actuals", default=0) or 0) < 104,
       ["completeness"], ["business_rule"]),
]


# ==============================================================================
# Driver cascade -- business causality decides ORDER, the gate decides USABILITY
# ==============================================================================
# The relevance gate says whether a driver CAN be used. Which driver is tried FIRST is a
# business question, not a statistical one. A low average pass rate must never demote a
# business-correct driver for the queues where it does work -- so the cascade never
# reorders; where a driver fails the gate it is skipped and the next is tried.
DRIVER_CASCADE = {
    "Basic":   ["shipments", "asu"],
    "Premium": ["asu", "shipments"],
    "Pro":     ["asu", "shipments"],
    "OOP":     [],   # out-of-warranty: neither driver applies -> calendar, volume, data quality
    "OOW":     [],
}


def cascade_for(offering):
    """Driver order for an offering. Unknown offerings get the Premium order."""
    return DRIVER_CASCADE.get((offering or "").strip(), ["asu", "shipments"])


# ==============================================================================
# Generation
# ==============================================================================
def generate(features, suppressions=None):
    """Evaluate every catalogue entry against the features.

    Returns (generated, not_generated). `not_generated` carries the failing condition for
    EVERY entry that did not fire, so the Decision Card can show what was considered and
    why it stopped -- rather than silently omitting it.

    `suppressions`: {hypothesis_id: reason} for entries blocked by a data-quality gate.
    Suppressed is distinct from NotApplicable: the hypothesis was relevant and testable,
    and a gate stopped it.
    """
    supp = suppressions or {}
    generated, not_generated = [], []

    for entry in CATALOGUE:
        hid = entry["id"]
        record = {"id": hid, "category": entry["category"], "name": entry["name"],
                  "condition": entry["condition"]}

        if hid in supp:
            record.update({"state": SUPPRESSED, "reason": supp[hid]})
            not_generated.append(record)
            continue

        try:
            fired = bool(entry["predicate"](features or {}))
        except Exception as exc:                     # a broken check must not kill the run
            record.update({"state": SUPPRESSED,
                           "reason": f"applicability check could not be evaluated ({exc})"})
            not_generated.append(record)
            continue

        if fired:
            record.update({"state": GENERATED, "metrics": entry["metrics"],
                           "evidence_types": entry["evidence_types"]})
            generated.append(record)
        else:
            record.update({"state": NOT_APPLICABLE,
                           "reason": f"not generated because {entry['condition']} was not met"})
            not_generated.append(record)

    return generated, not_generated


def metrics_for(generated):
    """Union of the metrics the generated hypotheses require.

    This is the whole point of hypotheses preceding statistics: the engine computes what
    was asked for, and records why each metric ran.
    """
    out = {}
    for h in generated or []:
        for m in h.get("metrics") or []:
            out.setdefault(m, []).append(h["id"])
    return out


def summarise(generated, not_generated):
    """Counts plus the minimum-three check from the spec."""
    shortfall = None
    if len(generated) < 3:
        shortfall = (f"Only {len(generated)} applicable hypothesis(es); the catalogue "
                     f"yielded fewer than the minimum of three for this queue and period.")
    return {
        "catalogue_version": CATALOGUE_VERSION,
        "catalogue_size": len(CATALOGUE),
        "generated": len(generated),
        "not_applicable": len([n for n in not_generated if n["state"] == NOT_APPLICABLE]),
        "suppressed": len([n for n in not_generated if n["state"] == SUPPRESSED]),
        "shortfall": shortfall,
    }
