# -*- coding: utf-8 -*-
"""Confidence is CALCULATED. It is never assigned, estimated or inferred.

Implements `FC_RCA_Business_Rules.md` section 5B in full.

WHY THIS MODULE EXISTS
----------------------
Until now `confidence_pct` was a number the LLM chose. `prompts.py` asked for it in the
reply schema, so the figure that told a business lead how much to trust the answer was
produced by the same component that produced the answer -- and by the one component the
Evidence Hierarchy ranks LAST. A model that is confidently wrong reports high confidence.

Here it is arithmetic over eight weighted dimensions, and every part of it is recorded so
the number can be taken apart. Per the spec: "A confidence score that cannot be decomposed
shall not be published."

THE THREE AVAILABILITY STATES -- NEVER CONFLATED
------------------------------------------------
    Available      data present and usable            -> scored 0.0 to 1.0
    NotApplicable  irrelevant to THIS queue           -> excluded, weights renormalised
    Missing        relevant but absent or invalid     -> retained at the 0.20 floor

The distinction carries the governing constraint of the whole model:

    CONFIDENCE SHALL NEVER INCREASE BECAUSE EVIDENCE WAS LOST.

A dimension may be dropped only when it is genuinely irrelevant to the queue. When it is
relevant but unavailable it stays in the denominator at the floor and drags the score down.
Conflating the two would let a queue with missing data score HIGHER than one with complete
data, which is precisely backwards.

WHY ContradictoryEvidence CARRIES THE HIGHEST WEIGHT
-----------------------------------------------------
0.20, more than EvidenceStrength. It is the deliberate expression of "prefer Unknown over
wrong with high confidence". The engine's first duty is to avoid being confidently wrong,
so the dimension that measures how hard the conclusion was attacked outranks the one that
measures how well it was supported.

CAPS
----
Eight gates, applied AFTER aggregation. Caps are ceilings on the LEVEL, not subtractions
from the score. They never raise confidence, and where several apply the lowest binds.
Whenever a cap binds, the gate, the threshold and the measured figure are all recorded --
the spec is explicit that "a bare capped number is not compliant".
"""

WEIGHTS_VERSION = "2.0.0"

# --- Availability states ------------------------------------------------------
AVAILABLE = "Available"
NOT_APPLICABLE = "NotApplicable"
MISSING = "Missing"

MISSING_FLOOR = 0.20

# --- Dimensions and weights (Business Rules 5B) --------------------------------
WEIGHTS = {
    "ContradictoryEvidence": 0.20,
    "EvidenceStrength": 0.18,
    "BusinessRuleValidation": 0.15,
    "StatisticalAgreement": 0.14,
    "DataSufficiency": 0.12,
    "ContextCompleteness": 0.10,
    "HistoricalConsistency": 0.06,
    "ModelAgreement": 0.05,
}

# --- Levels --------------------------------------------------------------------
VERY_HIGH, HIGH, MEDIUM, LOW, VERY_LOW = "Very High", "High", "Medium", "Low", "Very Low"
_LEVEL_ORDER = [VERY_LOW, LOW, MEDIUM, HIGH, VERY_HIGH]     # ascending


def level_for(score):
    """Score -> level band. Boundaries per the spec table, inclusive at the lower edge."""
    if score >= 0.85:
        return VERY_HIGH
    if score >= 0.70:
        return HIGH
    if score >= 0.50:
        return MEDIUM
    if score >= 0.30:
        return LOW
    return VERY_LOW


def _min_level(a, b):
    """The lower of two levels. Used because caps are ceilings and the lowest binds."""
    return a if _LEVEL_ORDER.index(a) <= _LEVEL_ORDER.index(b) else b


# --- Evidence strength scale (five levels, canonical) ---------------------------
STRENGTH = {"Very Strong": 1.0, "Strong": 0.8, "Moderate": 0.6, "Weak": 0.4, "Very Weak": 0.2}

# Independence weight by evidence source family. A second item from a family already
# counted contributes 0.3 -- two statistics agreeing is weaker corroboration than a
# statistic and an analyst annotation agreeing, because they can fail the same way.
INDEPENDENCE = {
    "business_rule": 1.0,
    "deterministic_statistic": 1.0,
    "analyst_annotation": 1.0,
    "historical_precedent": 0.8,
    "ml_attribution": 0.6,
}
REPEAT_FAMILY_INDEPENDENCE = 0.3


def _dim(name, availability, score, note=None):
    return {"dimension": name, "availability": availability,
            "score": (round(score, 4) if isinstance(score, (int, float)) else None),
            "weight": WEIGHTS[name], "note": note}


# ==============================================================================
# Dimension scoring -- each is a pure function of explicit inputs
# ==============================================================================
def data_sufficiency(weeks_of_actuals, weeks_with_actuals, weeks_in_period,
                     mandatory_fields_blank, mandatory_fields_expected):
    """History depth, period coverage and field completeness.

    Period coverage enters the confidence model HERE AND ONLY HERE (spec 5B). At weekly
    grain coverage is 1.0 by definition; it bites on monthly and quarterly grains that are
    still filling up.
    """
    if weeks_of_actuals is None:
        return _dim("DataSufficiency", MISSING, MISSING_FLOOR,
                    "No history count available for this queue.")
    history_score = min(1.0, (weeks_of_actuals or 0) / 104.0)
    coverage_score = ((weeks_with_actuals / weeks_in_period)
                      if (weeks_in_period or 0) > 0 else 1.0)
    coverage_score = max(0.0, min(1.0, coverage_score))
    field_score = (1.0 - (mandatory_fields_blank / mandatory_fields_expected)
                   if (mandatory_fields_expected or 0) > 0 else 1.0)
    field_score = max(0.0, min(1.0, field_score))
    s = 0.40 * history_score + 0.40 * coverage_score + 0.20 * field_score
    return _dim("DataSufficiency", AVAILABLE, s,
                f"history {history_score:.2f} (of 104 wks), coverage {coverage_score:.2f}, "
                f"fields {field_score:.2f}")


def statistical_agreement(metrics_supporting, metrics_executed):
    """Share of executed metrics that support the conclusion.

    Under two metrics there is nothing to agree ABOUT, so the dimension is NotApplicable
    rather than Missing -- no penalty for a question that could not sensibly be asked.
    """
    if not metrics_executed or metrics_executed < 2:
        return _dim("StatisticalAgreement", NOT_APPLICABLE, None,
                    f"only {metrics_executed or 0} metric(s) executed; fewer than 2 to compare")
    return _dim("StatisticalAgreement", AVAILABLE, metrics_supporting / metrics_executed,
                f"{metrics_supporting} of {metrics_executed} executed metrics support it")


def model_agreement(methods_concurring, methods_executed):
    """Share of independent methods reaching the same conclusion."""
    if not methods_executed or methods_executed < 2:
        return _dim("ModelAgreement", NOT_APPLICABLE, None,
                    f"only {methods_executed or 0} method(s) applicable; nothing to cross-check")
    return _dim("ModelAgreement", AVAILABLE, methods_concurring / methods_executed,
                f"{methods_concurring} of {methods_executed} methods concur")


def context_completeness(elements_available, elements_applicable):
    """How much of the business context that COULD apply to this queue was actually there.

    `elements_applicable` must already exclude elements that are NotApplicable for the
    queue (no shipment exposure, aggregate country, and so on) -- otherwise an irrelevant
    element would be penalised as though it were missing.
    """
    if not elements_applicable:
        return _dim("ContextCompleteness", NOT_APPLICABLE, None,
                    "no context elements apply to this queue")
    return _dim("ContextCompleteness", AVAILABLE, elements_available / elements_applicable,
                f"{elements_available} of {elements_applicable} applicable context elements present")


def evidence_strength(evidence_items):
    """Weighted mean strength, discounting repeated sources within one family.

    `evidence_items`: [{"strength": "Strong", "family": "deterministic_statistic"}, ...]

    Zero evidence scores 0.0, NOT Missing. An investigation that collected no evidence has
    reached a finding about itself -- that is information, not an absence of it.
    """
    items = [e for e in (evidence_items or []) if isinstance(e, dict)]
    if not items:
        return _dim("EvidenceStrength", AVAILABLE, 0.0,
                    "no evidence items collected -- a finding, not a gap")
    seen = set()
    num = den = 0.0
    for e in items:
        fam = (e.get("family") or "deterministic_statistic")
        strength = STRENGTH.get(e.get("strength"), 0.4)
        indep = (REPEAT_FAMILY_INDEPENDENCE if fam in seen
                 else INDEPENDENCE.get(fam, 0.6))
        seen.add(fam)
        num += strength * indep
        den += indep
    return _dim("EvidenceStrength", AVAILABLE, (num / den) if den else 0.0,
                f"{len(items)} item(s) across {len(seen)} source family(ies)")


def contradictory_evidence(supporting_weight, contradictory_weight, search_performed=True):
    """INVERTED scale: 1.0 means nothing contradicts, 0.0 means contradiction dominates.

    If no contradiction search was performed the dimension is MISSING, never 1.0. Not
    having looked is not the same as having looked and found nothing -- scoring it as
    'clean' would reward skipping the search, which is exactly backwards.
    """
    if not search_performed:
        return _dim("ContradictoryEvidence", MISSING, MISSING_FLOOR,
                    "no contradiction search was performed")
    total = (supporting_weight or 0.0) + (contradictory_weight or 0.0)
    if total <= 0:
        return _dim("ContradictoryEvidence", MISSING, MISSING_FLOOR,
                    "contradiction search ran but weighed nothing either way")
    s = 1.0 - ((contradictory_weight or 0.0) / total)
    return _dim("ContradictoryEvidence", AVAILABLE, s,
                f"supporting {supporting_weight:.2f} vs contradictory {contradictory_weight:.2f}")


def business_rule_validation(state):
    """One of: supportive | neutral | not_evaluable | contradicts.

    `contradicts` scores 0.00 AND arms Gate 2, which caps the final level at Low. A
    business rule outranks statistics in the Evidence Hierarchy, so a rule saying the
    conclusion is impossible cannot be outvoted by arithmetic.
    """
    table = {"supportive": (1.00, "all applicable rules satisfied and supportive"),
             "neutral": (0.60, "all applicable rules satisfied, neutral to the conclusion"),
             "not_evaluable": (0.40, "a business rule could not be evaluated"),
             "contradicts": (0.00, "a business rule CONTRADICTS the conclusion")}
    score, note = table.get(state, (0.40, "business rule state unknown; treated as not evaluable"))
    return _dim("BusinessRuleValidation", AVAILABLE, score, note)


def historical_consistency(precedent_score, precedents_found=0):
    """Governed by BR-118 -- precedent provenance weighting.

    No precedent is NotApplicable, not Missing: a queue with no comparable history is not
    concealing evidence, there is genuinely nothing to be consistent with.
    """
    if precedent_score is None or not precedents_found:
        return _dim("HistoricalConsistency", NOT_APPLICABLE, None,
                    "no comparable precedent exists for this queue")
    return _dim("HistoricalConsistency", AVAILABLE, precedent_score,
                f"{precedents_found} precedent(s), provenance-weighted")


# ==============================================================================
# Caps
# ==============================================================================
def _caps(dimensions, ctx):
    """Evaluate all eight gates. Every gate is recorded, bound or not, with its figures."""
    applicable = [d for d in dimensions if d["availability"] != NOT_APPLICABLE]
    available = [d for d in applicable if d["availability"] == AVAILABLE]
    share_available = (len(available) / len(applicable)) if applicable else 0.0
    contra = next((d for d in dimensions if d["dimension"] == "ContradictoryEvidence"), None)
    coverage = ctx.get("coverage_ratio")
    families = ctx.get("evidence_families") or set()

    gates = [
        {"gate": 1, "condition": "fewer than 50% of applicable dimensions are Available",
         "cap": MEDIUM, "measured": f"{share_available:.0%} available "
                                    f"({len(available)} of {len(applicable)})",
         "threshold": "50%", "bound": bool(applicable) and share_available < 0.50},
        {"gate": 2, "condition": "a business rule contradicts the conclusion",
         "cap": LOW, "measured": ctx.get("business_rule_state") or "unknown",
         "threshold": "contradicts", "bound": ctx.get("business_rule_state") == "contradicts"},
        {"gate": "3a", "condition": "period coverage below 50%", "cap": MEDIUM,
         "measured": (f"{coverage:.0%}" if coverage is not None else "not measured"),
         "threshold": "50%", "bound": coverage is not None and coverage < 0.50},
        {"gate": "3b", "condition": "period coverage below 25%", "cap": LOW,
         "measured": (f"{coverage:.0%}" if coverage is not None else "not measured"),
         "threshold": "25%", "bound": coverage is not None and coverage < 0.25},
        {"gate": 4, "condition": "the expected primary driver is Missing", "cap": MEDIUM,
         "measured": ("primary driver missing" if ctx.get("primary_driver_missing")
                      else "primary driver present or not applicable"),
         "threshold": "Missing", "bound": bool(ctx.get("primary_driver_missing"))},
        {"gate": 5, "condition": "ContradictoryEvidence score below 0.40", "cap": LOW,
         "measured": (f"{contra['score']:.2f}" if contra and contra.get("score") is not None
                      else "not scored"),
         "threshold": "0.40",
         "bound": bool(contra and contra.get("score") is not None and contra["score"] < 0.40)},
        {"gate": 6, "condition": "all evidence comes from a single source family", "cap": LOW,
         "measured": f"{len(families)} source family(ies): {', '.join(sorted(families)) or 'none'}",
         "threshold": "more than 1", "bound": len(families) == 1},
        {"gate": 7, "condition": "the conclusion did not survive cross-examination", "cap": LOW,
         "measured": ctx.get("cross_examination_outcome") or "not run",
         "threshold": "survived",
         "bound": ctx.get("cross_examination_outcome") in ("reinvestigate", "rejected", "unresolved")},
        {"gate": 8, "condition": "queue Volume Band is Emerging", "cap": MEDIUM,
         "measured": ctx.get("volume_band") or "unknown",
         "threshold": "not Emerging", "bound": (ctx.get("volume_band") == "Emerging")},
    ]
    return gates


# ==============================================================================
# Public entry point
# ==============================================================================
def calculate(dimensions, context=None):
    """Aggregate scored dimensions into a confidence score, level and full decomposition.

    `dimensions` is the list returned by the scoring functions above.
    `context` supplies what the caps need that the dimensions alone do not carry.

    Returns everything needed to publish AND to defend the number -- per the spec's
    mandatory recording clause, a score that cannot be decomposed shall not be published.
    """
    ctx = context or {}
    dims = [d for d in (dimensions or []) if isinstance(d, dict)]

    applicable = [d for d in dims if d["availability"] != NOT_APPLICABLE]
    weight_sum = sum(d["weight"] for d in applicable)

    for d in dims:
        if d["availability"] == NOT_APPLICABLE:
            d["contribution"] = None
        else:
            # Missing dimensions were already set to the floor by their scorer; they stay in
            # the denominator so that losing evidence lowers the score rather than raising it.
            d["contribution"] = round((d["weight"] * (d["score"] or 0.0)) / weight_sum, 4) \
                if weight_sum else 0.0

    raw = (sum(d["weight"] * (d["score"] or 0.0) for d in applicable) / weight_sum) \
        if weight_sum else 0.0
    raw = max(0.0, min(1.0, raw))

    level_uncapped = level_for(raw)
    gates = _caps(dims, ctx)
    bound = [g for g in gates if g["bound"]]

    final_level = level_uncapped
    for g in bound:
        final_level = _min_level(final_level, g["cap"])

    binding = None
    if bound:
        # The lowest cap binds; report the specific gate that produced it.
        binding = sorted(bound, key=lambda g: _LEVEL_ORDER.index(g["cap"]))[0]

    return {
        "score": round(raw, 4),
        "score_pct": round(raw * 100, 1),
        "level": final_level,
        "level_before_caps": level_uncapped,
        "capped": final_level != level_uncapped,
        "binding_cap": binding,
        "caps_evaluated": gates,
        "dimensions": dims,
        "dimensions_applicable": len(applicable),
        "dimensions_available": len([d for d in applicable if d["availability"] == AVAILABLE]),
        "dimensions_missing": len([d for d in applicable if d["availability"] == MISSING]),
        "dimensions_not_applicable": len(dims) - len(applicable),
        "weights_version": WEIGHTS_VERSION,
        "missing_floor": MISSING_FLOOR,
        "explanation": _explain(raw, level_uncapped, final_level, binding, dims),
    }


def _explain(raw, level_uncapped, final_level, binding, dims):
    """Plain-English decomposition. The Confidence Panel is never collapsed, so this
    string is read by business users, not only by analysts."""
    parts = [f"Confidence is {final_level} ({raw * 100:.0f}%)."]
    if binding:
        parts.append(
            f"It was capped at {binding['cap']} from {level_uncapped} because "
            f"{binding['condition']} (measured: {binding['measured']}, "
            f"threshold: {binding['threshold']}).")
    missing = [d["dimension"] for d in dims if d["availability"] == MISSING]
    if missing:
        parts.append("Held down by missing evidence for: " + ", ".join(missing) + ".")
    na = [d["dimension"] for d in dims if d["availability"] == NOT_APPLICABLE]
    if na:
        parts.append("Not relevant to this queue, so excluded without penalty: "
                     + ", ".join(na) + ".")
    return " ".join(parts)
