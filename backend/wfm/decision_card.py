# -*- coding: utf-8 -*-
"""The Executive Decision Card -- the primary artifact. Everything else supports it.

Implements `FC_RCA_Output_and_Decision_Cards.md` sections 3, 4 and 5.

WHY THIS MODULE EXISTS
----------------------
Two complaints drove it, and they are the same complaint.

FIRST: the report said "demand genuinely rose" and "the miss is inherited from the
Country level" without ever saying WHERE, HOW MUCH, or WHY THAT MATTERS. The numbers were
sitting in the ladder rows the whole time -- `actual_offered`, `fcst_offered` and a scope
count at every level -- and nothing rendered them. A reader was told a conclusion and
given no way to check it.

    Before:  "Inherited from Country level (-10.2% exceeding threshold)."
    After:   "Country (United States) ran 8,410 contacts ABOVE a plan of 82,400 -- a
              10.2% under-forecast across 46 queues. This queue contributes 1,644 of
              those 8,410, about 20%. The level above it, SubRegion, is within
              threshold at -9.8%, so the pattern starts at Country."

SECOND: "inherited from a higher level" was being used as a conclusion. It is not one.
It says WHERE the miss is visible, never WHY it happened. The card therefore renders the
ladder as SCOPE -- context that narrows the search -- and never as the root cause. The
queue's own behaviour is always reported alongside it.

THE CONFIDENCE PANEL IS NEVER COLLAPSED
----------------------------------------
An explicit exception to progressive disclosure, and the spec says why: where a prominent
number and a hidden caveat disagree, readers act on the number. A confidence level whose
limitations sit behind an expander is misleading by construction.

Three prohibitions enforced here: a capped level is never presented as the calculated
level; a Missing dimension is never omitted; a Not Applicable dimension is never
described as a limitation.

AVAILABILITY WORDING IS LOAD-BEARING
-------------------------------------
    Missing         "Unavailable -- <reason>"              penalty applies
    NotApplicable   "Not relevant to this queue -- <reason>"  no penalty

"Warranty data not relevant to this queue" and "warranty data unavailable" mean opposite
things and lead to opposite actions. A reader must never have to infer which is meant.
"""
from .confidence import AVAILABLE, MISSING, NOT_APPLICABLE
from .common import rnd

INCONCLUSIVE = "Inconclusive"


def _fmt(n, nd=0):
    if not isinstance(n, (int, float)):
        return "n/a"
    return f"{n:,.{nd}f}"


# ==============================================================================
# The part that was missing -- the ladder, with its numbers
# ==============================================================================
def scope_analysis(ladder, target_adherence, target_variance, queue_name):
    """Turn the investigation ladder into something a reader can check.

    Returns the level where the pattern STARTS, each level's real figures, and this
    queue's share of the wider gap. Deliberately labelled `scope`, never `root cause`.
    """
    levels = (ladder or {}).get("levels") or []
    if not levels:
        return {"available": False,
                "reason": "Higher-level figures were not available for this period, so the "
                          "miss could not be placed in a wider context."}

    band = (ladder or {}).get("band_pct") or 10.0
    rows, first_breach = [], None
    for lv in levels:
        act, fc = lv.get("actual_offered"), lv.get("fcst_offered")
        adh = lv.get("adherence_pct")
        gap = (act - fc) if isinstance(act, (int, float)) and isinstance(fc, (int, float)) else None
        breaches = isinstance(adh, (int, float)) and abs(adh) > band
        same_direction = (isinstance(adh, (int, float)) and isinstance(target_adherence, (int, float))
                          and (adh < 0) == (target_adherence < 0))
        row = {
            "level": lv.get("level"), "scope": lv.get("scope"),
            "actual": rnd(act), "forecast": rnd(fc),
            "gap_contacts": rnd(gap),
            "adherence_pct": rnd(adh),
            "queues_in_scope": lv.get("queue_weeks_in_scope"),
            "breaches_band": breaches,
            "same_direction": same_direction,
            "reading": _level_reading(lv, gap, adh, band, breaches, same_direction),
        }
        rows.append(row)
        if breaches and same_direction and first_breach is None:
            first_breach = row

    share = None
    if first_breach and first_breach.get("gap_contacts") and target_variance:
        try:
            share = abs(target_variance) / abs(first_breach["gap_contacts"])
        except ZeroDivisionError:
            share = None

    if first_breach:
        narrative = (
            f"The pattern starts at {first_breach['level']} level ({first_breach['scope']}): "
            f"{_fmt(first_breach['actual'])} contacts against a plan of "
            f"{_fmt(first_breach['forecast'])} -- a gap of "
            f"{_fmt(abs(first_breach['gap_contacts'] or 0))} contacts "
            f"({first_breach['adherence_pct']:+.1f}%) across "
            f"{first_breach['queues_in_scope']} queue-week(s).")
        if share is not None:
            narrative += (f" {queue_name} accounts for {_fmt(abs(target_variance))} of that gap, "
                          f"about {share:.0%} of it.")
        narrative += (" Every level above this one is within threshold, so this is where the "
                      "wider pattern begins.")
    else:
        narrative = ("No higher level missed in the same direction, so this movement is "
                     "specific to this queue rather than part of a wider pattern.")

    return {
        "available": True,
        "starts_at": (first_breach or {}).get("level"),
        "starts_at_scope": (first_breach or {}).get("scope"),
        "queue_share_of_gap": (round(share, 4) if share is not None else None),
        "levels": rows,
        "narrative": narrative,
        "caution": ("This says WHERE the miss is visible, not WHY it happened. A wider pattern "
                    "narrows the search; it does not explain the cause. The queue's own "
                    "behaviour is reported below regardless."),
    }


def _level_reading(lv, gap, adh, band, breaches, same_direction):
    if not isinstance(adh, (int, float)):
        return f"{lv.get('level')}: figures unavailable."
    direction = "below plan" if adh > 0 else "above plan"
    state = ("exceeds the threshold" if breaches else f"within the ±{band:.0f}% threshold")
    txt = (f"{lv.get('level')} ({lv.get('scope')}): {_fmt(lv.get('actual_offered'))} actual "
           f"against {_fmt(lv.get('fcst_offered'))} planned")
    if gap is not None:
        txt += f", {_fmt(abs(gap))} contacts {direction}"
    txt += f" ({adh:+.1f}%, {state})"
    if breaches and not same_direction:
        txt += " -- but in the OPPOSITE direction to this queue, so it cannot be the source"
    return txt + "."


# ==============================================================================
# Confidence Panel
# ==============================================================================
# Plain-English name and meaning for every confidence dimension. The raw names are
# internal vocabulary -- "StatisticalAgreement 0.36" tells a business reader nothing about
# what was measured, whether 0.36 is good, or which direction helps.
#
# ContradictoryEvidence is the one that reliably misleads: it is an INVERTED scale, so a
# HIGH score means nothing argues against the conclusion and a LOW score means plenty
# does. Read the wrong way round it says the exact opposite of the truth, so its meaning
# text says so explicitly.
DIMENSION_MEANING = {
    "ContradictoryEvidence": (
        "Evidence AGAINST this conclusion",
        "Higher is better: 1.00 means nothing argues against it, 0.00 means the evidence "
        "against outweighs the evidence for."),
    "EvidenceStrength": (
        "How strong the supporting evidence is",
        "Weighs each piece of evidence by how reliable its source is, and discounts a "
        "second piece from a source already counted."),
    "BusinessRuleValidation": (
        "Whether the business rules agree",
        "1.00 = every applicable rule supports it; 0.00 = a rule contradicts it outright."),
    "StatisticalAgreement": (
        "Whether the measurements agree with each other",
        "The share of the measures that ran which point the same way. A low score means "
        "the numbers tell different stories."),
    "DataSufficiency": (
        "How much data was available",
        "Combines depth of history, how complete the period is, and whether required "
        "fields were filled in."),
    "ContextCompleteness": (
        "How much business context was available",
        "The share of the context that applies to this queue which was actually present -- "
        "calendar, holidays, warranty, shipments."),
    "HistoricalConsistency": (
        "Whether this matches what happened before",
        "Compares against similar past cases for this queue."),
    "ModelAgreement": (
        "Whether independent methods agree",
        "Needs at least two methods to compare; with one there is nothing to cross-check."),
}


def confidence_panel(confidence):
    """Section 4. Always visible, never collapsed, fully decomposed."""
    c = confidence or {}
    dims = []
    for d in c.get("dimensions") or []:
        av = d.get("availability")
        if av == AVAILABLE:
            wording = f"{d.get('score'):.2f}" if isinstance(d.get("score"), float) else "n/a"
            state = "Available"
        elif av == MISSING:
            # Wording MUST differ from NotApplicable -- opposite meanings, opposite actions.
            wording = f"Unavailable — {d.get('note') or 'relevant but absent'}"
            state = "Missing"
        else:
            wording = f"Not relevant to this queue — {d.get('note') or 'does not apply'}"
            state = "Not Applicable"
        plain, meaning = DIMENSION_MEANING.get(d.get("dimension"), (d.get("dimension"), ""))
        sc = d.get("score")
        # Which way is this pulling? Judged against the score a dimension needs to be
        # carrying its weight rather than dragging -- so the reader can see at a glance
        # what is holding the number down instead of decoding eight decimals.
        if state != "Available" or not isinstance(sc, (int, float)):
            verdict = "—"
        elif sc >= 0.75:
            verdict = "holding it up"
        elif sc >= 0.50:
            verdict = "neutral"
        else:
            verdict = "pulling it down"
        dims.append({"dimension": d.get("dimension"), "plain_name": plain, "meaning": meaning,
                     "state": state, "score": sc, "weight": d.get("weight"),
                     "contribution": d.get("contribution"), "wording": wording,
                     "verdict": verdict,
                     # A Not Applicable dimension is NEVER a limitation -- it is simply
                     # irrelevant, and listing it as a shortcoming would mislead.
                     "is_limitation": state == "Missing"})

    cap = c.get("binding_cap")
    return {
        "final_level": c.get("level"),
        "calculated_level": c.get("level_before_caps"),
        "score_pct": c.get("score_pct"),
        "capped": bool(c.get("capped")),
        "cap": ({"gate": cap.get("gate"), "condition": cap.get("condition"),
                 "measured": cap.get("measured"), "threshold": cap.get("threshold"),
                 "cap_level": cap.get("cap")} if cap else None),
        "cap_statement": (
            f"Calculated {c.get('level_before_caps')} ({c.get('score_pct')}%), capped at "
            f"{cap.get('cap')} — {cap.get('condition')}. Gate {cap.get('gate')}: "
            f"measured {cap.get('measured')} against a threshold of {cap.get('threshold')}."
            if cap else None),
        "dimensions": dims,
        "in_plain_words": _confidence_in_words(c, dims, cap),
        "how_to_read": ("Eight things are scored out of 1.00 and combined by the weights shown. "
                        "Anything not relevant to this queue is left out entirely rather than "
                        "counted as a zero. A cap can then lower the final level, but never "
                        "raise it."),
        "what_would_change_it": _what_would_change(c, dims),
        "always_visible": True,
    }


def _confidence_in_words(c, dims, cap):
    """One paragraph a manager can read instead of decoding the table."""
    drags = [d["plain_name"] for d in dims if d["verdict"] == "pulling it down"]
    holds = [d["plain_name"] for d in dims if d["verdict"] == "holding it up"]
    na = [d["plain_name"] for d in dims if d["state"] == "Not Applicable"]

    parts = []
    if cap:
        parts.append(f"The evidence scored {c.get('score_pct')}%, which on its own would be "
                     f"{c.get('level_before_caps')}. It was then held down to "
                     f"{c.get('level')} because {cap.get('condition')}.")
    else:
        parts.append(f"The evidence scored {c.get('score_pct')}%, giving {c.get('level')} "
                     f"confidence. Nothing capped it.")
    if holds:
        parts.append("Strongest support came from: " + ", ".join(holds[:3]).lower() + ".")
    if drags:
        parts.append("Weakest were: " + ", ".join(drags[:3]).lower() + ".")
    if na:
        parts.append(", ".join(na) + " did not apply to this queue, so "
                     + ("they were" if len(na) > 1 else "it was")
                     + " left out rather than counted against it.")
    return " ".join(parts)


def _what_would_change(confidence, dims):
    """Required by the spec. Concrete, not generic."""
    out = []
    cap = confidence.get("binding_cap") or {}
    gate = cap.get("gate")
    if gate == 6:
        out.append("Would rise if evidence came from more than one source family — a business "
                   "rule, an analyst annotation or a comparable prior case alongside the "
                   "statistics.")
    if gate == 4:
        out.append("Would rise if the expected primary driver for this queue could be evaluated.")
    if gate in ("3a", "3b"):
        out.append("Would rise as the remaining weeks of the period arrive.")
    if gate == 1:
        out.append("Would rise if the dimensions currently unavailable could be scored.")
    if gate == 5:
        out.append("Would rise if the contradictions raised at cross-examination were resolved.")
    if gate == 7:
        out.append("Would rise if the conclusion survived cross-examination without weaknesses.")
    if gate == 8:
        out.append("Would rise once this queue has enough volume history to leave the Emerging band.")
    for d in dims:
        if d["state"] == "Missing":
            out.append(f"Would rise if {d['dimension']} could be measured "
                       f"({d['wording'].replace('Unavailable — ', '')}).")
    if not out:
        out.append("No single cap is holding this back; confidence reflects the evidence as it "
                   "stands.")
    return out


# ==============================================================================
# Hypothesis Comparison -- four visually distinct states
# ==============================================================================
def hypothesis_comparison(hypotheses, cross_examination):
    """Section 5. Accepted / Rejected / Suppressed / Not Applicable.

    A hypothesis that COULD NOT BE TESTED must never look like one TESTED AND RULED OUT.
    The first says go and get the data; the second says stop looking there.
    """
    by_id = {r.get("hypothesis_id"): r for r in (cross_examination or [])}
    rows = []
    for h in (hypotheses or {}).get("generated") or []:
        rep = by_id.get(h["id"]) or {}
        survived = rep.get("survived")
        # The old wording listed three counts that did not add up to the total, because
        # unanswered questions were omitted -- "15 questions: 11 supported, 2 weakened,
        # 0 refuted" leaves two unaccounted for and quietly undermines the whole panel.
        # Every question is now accounted for, and the sentence says what the exercise
        # WAS: an attempt to disprove the conclusion, not to confirm it.
        asked = rep.get("questions_asked", 0)
        sup, weak, ref = rep.get("supports", 0), rep.get("weakens", 0), rep.get("refutes", 0)
        una = rep.get("unanswered", 0)
        bits = [f"{sup} found nothing wrong with it"]
        if weak:
            bits.append(f"{weak} raised a doubt")
        if ref:
            bits.append(f"{ref} contradicted it outright")
        if una:
            bits.append(f"{una} could not be answered from the data")
        rows.append({
            "id": h["id"], "name": h["name"], "category": h["category"],
            "state": "Accepted" if survived else "Rejected",
            "outcome": rep.get("outcome"),
            "detail": (f"We put {asked} standard challenge question(s) to this explanation, each "
                       f"answered from the data and each trying to disprove it — "
                       + "; ".join(bits) + "."),
            "caveats": rep.get("caveats") or [],
            # The questions that actually bit. A count of doubts without the doubts
            # themselves is not something a reader can act on.
            "doubts_raised": [a.get("detail") for r in (rep.get("rounds") or [])
                              for a in (r.get("answers") or [])
                              if a.get("verdict") in ("weakens", "refutes") and a.get("detail")],
            "action_hint": ("Survived every challenge that could be put to it." if survived and not weak
                            else "Survived challenge, but with the doubts listed below." if survived
                            else "Tested against the evidence and ruled out — do not pursue."),
        })
    for n in (hypotheses or {}).get("not_generated") or []:
        suppressed = n.get("state") == "Suppressed"
        rows.append({
            "id": n["id"], "name": n["name"], "category": n["category"],
            "state": "Suppressed" if suppressed else "Not Applicable",
            "outcome": None,
            "detail": n.get("reason"),
            "caveats": [],
            "action_hint": ("COULD NOT BE TESTED — the data needed was blocked or missing. "
                            "Fix the data and this becomes answerable."
                            if suppressed else
                            "Never relevant to this queue — no action, no penalty."),
        })
    order = {"Accepted": 0, "Rejected": 1, "Suppressed": 2, "Not Applicable": 3}
    rows.sort(key=lambda r: (order.get(r["state"], 9), r["id"]))
    return {"states": ["Accepted", "Rejected", "Suppressed", "Not Applicable"],
            "counts": {s: len([r for r in rows if r["state"] == s]) for s in order},
            "rows": rows}


# ==============================================================================
# The card
# ==============================================================================
def build(result, ladder=None):
    """Assemble the Executive Decision Card from a spec-engine result."""
    fs = result.get("forecast_summary") or {}
    rc = result.get("root_cause") or {}
    conf = result.get("confidence") or {}
    key = result.get("queue") or {}
    period = result.get("period") or {}
    adh = fs.get("adherence_pct")
    variance = fs.get("absolute_variance_contacts")

    scope = scope_analysis(ladder, adh, variance, key.get("Forecast_name") or "This queue")

    # --- 3.2 conditional header markers ---
    markers = []
    if result.get("major_deviation"):
        markers.append("Major Deviation")
    if not result.get("material", True):
        markers.append("Below materiality floor — worklist suppressed, RCA still generated")
    if not period.get("complete", True):
        markers.append(f"Timeline: {period.get('label')}")
    if result.get("status") == "Incomplete":
        markers.append("Investigation Incomplete")

    narrative = result.get("narrative") or {}
    inconclusive = rc.get("cause_type") == INCONCLUSIVE

    return {
        # --- 3.1 mandatory header ---
        "header": {
            "forecast_adherence_pct": adh,               # SIGNED, never absolute
            "direction": fs.get("direction"),            # business language
            "absolute_variance_contacts": variance,
            "forecast": fs.get("forecast"), "actual": fs.get("actual"),
            "grain": result.get("grain"),
            "period": period.get("label"),
            "queue": key.get("Forecast_name"),
            "volume_band": (result.get("volume_band") or None),
            "confidence_level": conf.get("level"),
            "markers": markers,
        },
        # --- 3.3 the ten mandatory body sections ---
        "sections": {
            "1_executive_summary": narrative.get("executiveSummary") or _fallback_summary(fs, rc, conf),
            "2_root_cause": {
                "statement": (narrative.get("rootCauseStatement") or rc.get("statement")),
                "hypothesis": rc.get("hypothesis"),
                "category": rc.get("category"),
                "inconclusive": inconclusive,
                "selected_because": rc.get("selected_because"),
                "cross_examination": rc.get("cross_examination"),
                # The ladder is SCOPE. It is attached to the root cause section as context
                # and is explicitly not the cause itself.
                "scope": scope,
                # The why-chain is attached to the root cause because it IS the reasoning
                # behind it: each level asks why of the level above, until the data can no
                # longer answer. Without it the card states a cause and shows no working.
                "why_chain": result.get("why_chain"),
                # Prompt 2 asked these; Prompt 1 answered them from the evidence bundle.
                "interrogation": result.get("interrogation"),
            },
            "3_confidence": confidence_panel(conf),
            "4_business_impact": {
                "contacts": variance,
                "direction": fs.get("direction"),
                "statement": (f"{_fmt(variance)} contacts {'fewer than' if (adh or 0) > 0 else 'more than'} "
                              f"planned in {period.get('label')}."),
            },
            "5_evidence": {
                "supporting": result.get("supporting_evidence") or [],
                "contradictory": result.get("contradictory_evidence") or [],
                "note": "Contradictory evidence is actively sought, not merely noted if encountered.",
            },
            "6_hypothesis_comparison": hypothesis_comparison(result.get("hypotheses"),
                                                             result.get("cross_examination")),
            "7_recommendations": result.get("recommendations") or [],
            "8_limitations": result.get("limitations") or [],
            "9_data_availability": _availability_callout(result),
            "10_audit_reference": {
                "fingerprint": (result.get("audit") or {}).get("input_fingerprint"),
                "completed_at": (result.get("audit") or {}).get("completed_at"),
                "catalogue_version": (result.get("audit") or {}).get("catalogue_version"),
                "confidence_weights_version": (result.get("audit") or {}).get("confidence_weights_version"),
                "prompt_version": (result.get("audit") or {}).get("prompt_version"),
                "steps": (result.get("audit") or {}).get("steps"),
            },
        },
        "status": result.get("status"),
        "incomplete_reason": result.get("incomplete_reason"),
        "engine": result.get("engine"),
        "card_version": "2.0.0",
    }


def _fallback_summary(fs, rc, conf):
    """Used when the narrative call failed. The RCA is still complete and still publishable --
    an LLM failure never blocks an RCA."""
    return [
        f"{fs.get('direction')} of {fs.get('adherence_pct')}% — "
        f"{_fmt(fs.get('absolute_variance_contacts'))} contacts against plan.",
        (rc.get("statement") or "No defensible root cause could be established."),
        f"Confidence: {conf.get('level')} ({conf.get('score_pct')}%).",
        "Narrative generation was unavailable; these figures are the engine's own and are complete.",
    ]


def _availability_callout(result):
    """Section 9. What was and was not available, stated plainly."""
    gates = result.get("driver_gate") or {}
    out = []
    for g in gates.get("results", []):
        out.append({"item": g.get("driver"),
                    "state": "Available" if g.get("relevant") else "Not Applicable",
                    "detail": g.get("reason")})
        if g.get("trend_warning"):
            out.append({"item": f"{g.get('driver')} (caution)", "state": "Available",
                        "detail": g["trend_warning"]})
    if not gates.get("any_driver_relevant"):
        out.append({"item": "Driver attribution", "state": "Not Applicable",
                    "detail": gates.get("note")})
    return out
