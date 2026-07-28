"""Hypothesis generation and status marking.

Two jobs:

1. `mark` -- enforce the prompt's hypothesis rule in code. A cause whose evidence is thin,
   or which rests on a proxy rather than an authoritative grouping, is downgraded to
   "Hypothesis - To be Validated" even if the model called it Verified. The prompt asks the
   model to be honest about this; this makes it structural.

2. `deterministic` -- build the ranked list from the features alone, with no model. Used by
   the fallback path so an unreachable provider still produces an honest report instead of
   nothing. Every entry here is derived from a computed feature, never invented.
"""
from .common import confidence_level

HYPOTHESIS = "Hypothesis - To be Validated"
VERIFIED = "Verified"

# Cause types that can only ever be a hypothesis from this dataset alone.
_ALWAYS_HYPOTHESIS = {
    # A suspect value needs validating at source; we cannot prove it is bad from here.
    "data_quality_issue",
    # Migration is computed on a PROXY grouping, not the authoritative mapped CQN.
    "channel_migration",
}


def mark(causes, features):
    """Downgrade over-confident statuses. Never upgrades."""
    for c in (causes or []):
        if not isinstance(c, dict):
            continue
        ctype = (c.get("cause_type") or "").strip()
        reasons = []

        if ctype in _ALWAYS_HYPOTHESIS:
            if ctype == "data_quality_issue":
                reasons.append("the figure has to be validated at source before it can be confirmed")
            else:
                reasons.append("channel grouping is a proxy for the Combined Queue, not the mapped CQN")

        if not (c.get("evidence") or []):
            reasons.append("no supporting figure survived reconciliation against the source data")

        if reasons:
            c["status"] = HYPOTHESIS
            c["hypothesis_reason"] = "; ".join(reasons)
        elif c.get("status") not in (VERIFIED, HYPOTHESIS):
            c["status"] = VERIFIED
    return causes


def _entry(rank, ctype, title, explanation, evidence, pct, impact, action, status):
    return {"rank": rank, "cause_type": ctype, "title": title, "explanation": explanation,
            "evidence": evidence, "confidence_pct": pct,
            "confidence_level": confidence_level(pct), "business_impact": impact,
            "recommended_action": action, "status": status}


def deterministic(features, fallback_finding, fallback_ctype):
    """The no-model ranked list. Ordered by how conclusive the computed signal is."""
    dq = features.get("data_quality") or {}
    ladder = features.get("investigation_ladder") or {}
    siblings = features.get("channel_siblings") or {}
    corr = (features.get("correlations") or {}).get("driver_decomposition") or {}

    out = []

    if dq.get("suspect"):
        out.append(_entry(
            len(out) + 1, "data_quality_issue",
            "Suspected data quality issue in this week's actual",
            dq.get("note"),
            [{"text": f"This week recorded {dq.get('this_week_actual')} against a typical week "
                      f"of about {dq.get('typical_week_actual')}.",
              "source_field": "Actual_Offered", "value": dq.get("this_week_actual")}],
            60,
            "Any forecasting action taken on this figure would rest on a number that may not be real.",
            "Validate this week's offered volume at source before acting on it.",
            HYPOTHESIS))

    if ladder.get("inherited_from"):
        lvl = ladder["inherited_from"]
        match = next((x for x in (ladder.get("levels") or []) if x.get("level") == lvl), {})
        out.append(_entry(
            len(out) + 1, "inherited_from_higher_level",
            f"The miss is inherited from {lvl} level",
            f"The same miss is already visible at {lvl} level, so it is not specific to this "
            f"queue and a queue-level cause cannot explain it.",
            [{"text": f"At {lvl} level ({match.get('scope')}) adherence was "
                      f"{match.get('adherence_pct')}% for the same week.",
              "source_field": "Actual_Offered", "value": match.get("actual_offered")}],
            65,
            "Correcting this queue alone would not fix a miss the whole level shares.",
            f"Investigate at {lvl} level before adjusting this queue's plan.",
            VERIFIED))

    if siblings.get("migration_detected"):
        out.append(_entry(
            len(out) + 1, "channel_migration",
            "Customer demand shifted between channels within the same Combined Queue",
            siblings.get("note"),
            [{"text": f"The group total moved from {siblings.get('group_total_prior_week')} to "
                      f"{siblings.get('group_total_this_week')} while individual channels moved "
                      f"{siblings.get('gross_channel_movement')} in total.",
              "source_field": "Actual_Offered", "value": siblings.get("group_total_this_week")}],
            55,
            "Treating this as a forecasting miss would push the wrong correction into the plan.",
            "Review routing and channel-mix assumptions for this locality.",
            HYPOTHESIS))

    if corr.get("available"):
        ctype = ("installed_base_change" if corr.get("verdict") == "warranty_base_driven"
                 else "forecast_baseline_error")
        out.append(_entry(
            len(out) + 1, ctype,
            ("Warranty base differed from plan" if corr.get("verdict") == "warranty_base_driven"
             else "Contacts per unit differed from plan" if corr.get("verdict") == "contact_rate_driven"
             else "Both warranty base and contacts per unit differed from plan"),
            corr.get("plain_language"),
            [{"text": f"Of a total miss of {corr.get('total_miss')}, "
                      f"{corr.get('warranty_base_effect')} came from the warranty base and "
                      f"{corr.get('contacts_per_unit_effect')} from contacts per unit.",
              "source_field": "Actual_ASU", "value": corr.get("actual_units_under_warranty")}],
            70,
            "Points at which assumption to correct: the unit plan or the contact-rate assumption.",
            ("Review the installed-base / ASU assumptions for this queue."
             if corr.get("verdict") == "warranty_base_driven"
             else "Review the contacts-per-unit assumption in the forecast plan."),
            VERIFIED))

    # Always close with the best-supported feature-based finding so the list is never empty.
    out.append(_entry(
        len(out) + 1, fallback_ctype,
        (str(fallback_ctype).replace("_", " ").capitalize() if fallback_ctype
         else "Best-supported finding from the available data"),
        (fallback_finding or {}).get("statement"),
        (fallback_finding or {}).get("supporting_evidence") or [],
        int(round(((fallback_finding or {}).get("confidence") or 0.35) * 100)),
        "See the forecast adherence gap for this queue.",
        "Review this queue's forecast inputs and recent accuracy with the planning team.",
        VERIFIED))

    return out[:5]
