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
# Imported rather than restated: two copies of the 50-contact floor would drift, and the header
# marker would then quote a different number from the one criticality actually applies.
from .fc_evidence import MATERIALITY_FLOOR_CONTACTS

INCONCLUSIVE = "Inconclusive"

# ==============================================================================
# Section 40 -- executive language
# ==============================================================================
# Terms banned from EXECUTIVE prose. Not from the statistical section, which is where a analyst
# should be able to see the coefficient -- the rule is that the business story is readable without
# them, not that they are hidden.
#
# This exists as a checkable list rather than a style note because a style note cannot be tested.
# `jargon_found` is published on the card so the test suite can assert the executive fields are
# clean, and so a reviewer can see the check ran rather than trusting that it did.
EXEC_JARGON = ("z-score", "z score", "zscore", "p-value", "p value", "r-squared", "r squared",
               "r²", "spearman", "pearson", "coefficient of variation", "standard deviation",
               "std dev", "stdev", "regression", "sigma", "wape", "mape", "rho", "correlation "
               "coefficient", "quartile", "kurtosis", "heteroscedastic")


def jargon_in(text):
    """Which banned terms appear in a piece of executive prose. Empty list is the pass condition."""
    low = str(text or "").lower()
    return sorted({t for t in EXEC_JARGON if t in low})


# Section 27 of new_prompt.md, and a DIFFERENT list on purpose. EXEC_JARGON is unconditional --
# "Spearman rho" never belongs in executive prose. A causal verb is conditional: the spec bans it
# "unless causal evidence is sufficiently strong". Folding these into EXEC_JARGON would assert the
# unconditional rule and would also retroactively fail prose that is legitimately causal, so they
# are tracked separately and reported beside it.
CAUSAL_VERBS = ("caused", "causing", "drove", "driving", "generated", "generating",
                "resulted in", "resulting in", "led to", "produced", "triggered")

# What the spec asks for instead. Published so a writer -- human or model -- is given the
# replacement rather than only the prohibition.
HEDGED_ALTERNATIVES = ("supported", "consistent with", "contributed", "may have influenced",
                       "not confirmed", "could not be isolated")


def causal_verbs_in(text):
    """Unsupported causal verbs in a piece of executive prose (section 27).

    Whole-word matched by PADDING rather than a regex word boundary: the phrases are multi-word
    ("resulted in", "led to"), and a plain substring test produced false hits -- "produced" fired
    inside "reproduced" and "led to" fired inside "controlled to". Normalising every non-alphanumeric
    run to a single space and then looking for " verb " handles both, with nothing to escape.
    """
    import re as _re
    low = " " + _re.sub("[^a-z0-9]+", " ", str(text or "").lower()) + " "
    return sorted({v for v in CAUSAL_VERBS if (" " + v + " ") in low})


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

    # Business Org is dropped from this card. It is the entire book -- every queue in the
    # deployment rolls into the one row, so it is the same figure on every report and it
    # breaches on almost every one. A level that is always present and almost always red
    # carries no information about THIS queue, and it was crowding out the levels that do.
    #
    # Filtered here rather than in `data_access` so the rung stays available to the skeptic,
    # the prompts and the driver gate, which legitimately compare against the book total.
    # `first_breach` is computed from the rows BELOW, so removing the row also moves the
    # card's "the pattern starts at ..." sentence to the highest level still shown -- the
    # narrative and the table cannot disagree.
    levels = [lv for lv in levels if str(lv.get("level", "")).strip().lower() != "business org"]

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
            # A share under half a percent formatted as "about 0% of it", which reads as
            # "none of it" when the queue does contribute. Say it is small instead of
            # rounding it away.
            share_txt = "under 1%" if share < 0.005 else f"about {share:.0%}"
            narrative += (f" {queue_name} accounts for {_fmt(abs(target_variance))} of that gap, "
                          f"{share_txt} of it.")
        # Only claim the levels above are clean when there ARE levels above it on this card.
        # Business Org is filtered out here, so the top row has nothing shown above it --
        # and asserting "every level above is within threshold" would be a statement about
        # a level the reader cannot see, and in practice a false one, since the book total
        # breaches on most reports.
        if rows and rows[0] is not first_breach:
            narrative += (" Every level above this one is within threshold, so this is where "
                          "the wider pattern begins.")
        else:
            narrative += (" This is the highest level shown, so the pattern may extend wider "
                          "than this card displays.")
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
# Section 30 -- Criticality, shown SEPARATELY from confidence
# ==============================================================================
def criticality_panel(criticality):
    """Section 30. Visible in its own right, never folded into the confidence number.

    The two answer different questions and a reader who conflates them acts wrongly in both
    directions: they ignore a large miss that happens to be thinly evidenced, and they escalate a
    trivial one that happens to be well evidenced. The panel therefore states the independence
    explicitly rather than relying on the reader to infer it from the layout.
    """
    c = criticality or {}
    if not c:
        return {"available": False,
                "reason": "criticality could not be computed for this period."}
    return {
        "available": True,
        "band": c.get("band"),
        "band_before_lifts": c.get("band_before_lifts"),
        "lifted": c.get("band") != c.get("band_before_lifts"),
        "lifts_applied": c.get("lifts_applied") or [],
        "absolute_gap_contacts": c.get("absolute_gap_contacts"),
        "relative_gap": c.get("relative_gap"),
        "typical_week_actual": c.get("typical_week_actual"),
        "streak_weeks": c.get("streak_weeks"),
        "statement": c.get("reading"),
        "basis": c.get("basis"),
        "how_to_read": ("Criticality is how much this miss MATTERS operationally. It is calculated "
                        "from the size of the gap in contacts, that gap against a typical week for "
                        "this queue, and whether the miss is standing or isolated. It is NOT "
                        "derived from confidence, and a high confidence score can sit beside a low "
                        "criticality band without contradiction."),
        "not_confidence": ("Confidence says how strong the evidence is. Criticality says how much "
                           "the miss matters. They are independent by design."),
        "thresholds": c.get("thresholds"),
    }


# ==============================================================================
# Sections 39 + 41 -- Why This Happened, as DETERMINISTICALLY RANKED bullets
# ==============================================================================
# Rank order is the section 41 list, applied as a sort key. The first bullet is therefore the
# strongest explanation as the EVIDENCE measures it -- never as the model prefers it, and never
# simply the order the blocks happened to be computed in.
_RANK_CAUSAL_COHERENCE = 0     # does the mechanism explain the direction of the miss at all
_RANK_FORECASTABILITY = 1      # could the plan have reacted
_RANK_HISTORICAL = 2           # does this queue's own history support it
_RANK_STATISTICAL = 3          # how strong is the measurement
_RANK_SUFFICIENCY = 4          # was there enough data
_RANK_CONTRADICTION = 5        # what argues against


def why_bullets(result):
    """Section 39 and 41. Each bullet says WHAT happened, WHY it mattered, and the forecast
    mechanism -- the three parts the brief asks for -- and carries its evidence ID.

    Built from the deterministic blocks only. The narrative model may later REWORD these, but the
    set of bullets, their order and their figures are settled here.
    """
    mech = result.get("miss_mechanism") or {}
    resp = result.get("forecast_response_diagnostic") or {}
    lag = result.get("lagged_driver_evidence") or {}
    hol = result.get("holiday_response") or {}
    asu = result.get("asu_decomposition") or {}
    res = result.get("evidence_resolution") or {}
    fs = result.get("forecast_summary") or {}

    out = []

    def bullet(rank, what, why_it_mattered, mechanism, evidence_id=None, strength=None):
        """One bullet. Keys whose value is absent are OMITTED rather than set to null.

        A renderer that prints every key it finds will print the string "None" for a null, and that
        is exactly how the WFM report once shipped a literal "undefined" to a user. Leaving the key
        out means a naive template renders nothing, which is the correct thing to render.
        """
        if not what:
            return
        b = {"rank_basis": rank, "what_happened": what,
             "text": " ".join(p for p in (what, why_it_mattered, mechanism) if p)}
        for k, v in (("why_it_mattered", why_it_mattered), ("forecast_mechanism", mechanism),
                     ("evidence_id", evidence_id), ("strength", strength)):
            if v:
                b[k] = v
        out.append(b)

    # 1. The mechanism itself -- the direct answer to "why did Forecast miss?"
    for c in (mech.get("candidates") or []):
        m = c.get("mechanism")
        coh = (c.get("direction_coherence") or {})
        bullet(_RANK_CAUSAL_COHERENCE,
               c.get("evidence"),
               (f"This is {'the' if not mech.get('compound') else 'one of the'} mechanism"
                f"{'s' if mech.get('compound') else ''} the evidence supports: "
                f"{(result.get('root_cause') or {}).get('miss_mechanism_meaning') or ''}").strip(),
               (f"Direction checks out: the miss pushed demand {coh.get('miss_direction')} and this "
                f"mechanism implies {coh.get('implied_direction')}." if coh.get("coherent")
                else "Direction was not testable for this mechanism."),
               evidence_id="E5", strength="Strong")

    # 2. Which SIDE of the gap was already there before the week began (section 13).
    dec = resp.get("miss_decomposition") or {}
    if dec.get("available") and dec.get("reconciles"):
        lead = dec.get("leading_side")
        bullet(_RANK_CAUSAL_COHERENCE, dec.get("reading"),
               (f"Most of the gap -- {abs((dec.get(lead + '_side_share') or 0)) * 100:.0f}% of it -- "
                f"sits on the {lead} side." if lead else None),
               ("The plan was already away from the expected level before the week started."
                if lead == "forecast" else
                "Demand moved away from what the available signals pointed to."),
               evidence_id="E2", strength="Strong")

    # 3. Could the plan have reacted (section 15)?
    #
    # The forecastability gate and the direction-coherence gate answer DIFFERENT questions, and they
    # can disagree: the plan may well have been able to react (all four conditions met) while the
    # mechanism still pushes demand the opposite way to the miss, in which case the direction gate --
    # which runs later -- rejects it. Stating only the first produced a card that asserted
    # "a forecast-response failure IS supported" four bullets above "FORECAST_RESPONSE_FAILURE cannot
    # be the cause". Both were true; together they read as self-contradiction. The override is now
    # named in the same sentence rather than left for the reader to reconcile.
    gate = resp.get("forecastability_gate") or {}
    if gate.get("conditions"):
        _rejected_mechs = {c.get("mechanism") for c in (mech.get("rejected_for_direction") or [])}
        _fr_overridden = (gate.get("supports_forecast_response_failure")
                          and "FORECAST_RESPONSE_FAILURE" in _rejected_mechs)
        if _fr_overridden:
            _why = ("All four conditions for calling this a forecast-response failure hold -- the "
                    "plan COULD have reacted. It is still not the cause here: the direction-"
                    "coherence gate, which runs afterwards, rejected it because the mechanism "
                    "implies demand moving the opposite way to this miss. Being able to react and "
                    "being the explanation are two different tests, and this evidence passes the "
                    "first and fails the second.")
        elif gate.get("supports_forecast_response_failure"):
            _why = "All four conditions for calling this a forecast-response failure hold."
        else:
            _why = (f"{gate.get('conditions_met')} of 4 conditions hold, so it is not classed as a "
                    f"forecast failure.")
        bullet(_RANK_FORECASTABILITY, gate.get("verdict"), None, _why,
               evidence_id="E5", strength="Strong")
        if _fr_overridden:
            # Published so a consumer can see the two gates disagreed without parsing prose.
            out[-1]["overridden_by_direction_gate"] = True

    # 4. Calendar (sections 22-24).
    cap = hol.get("forecast_capture") or {}
    if hol.get("applies"):
        bullet(_RANK_HISTORICAL,
               hol.get("reading"),
               (f"The week sits in the {str(hol.get('phase') or '').replace('_', '-')} phase"
                + (f", and a holiday falls close enough to reach it even though the source row "
                   f"records none." if hol.get("zero_count_but_adjacent") else ".")),
               cap.get("reason"),
               evidence_id="E10", strength="Moderate")

    # 5. Drivers (sections 16-18, 20-21).
    for d in (lag.get("drivers") or []):
        if d.get("usable_as_evidence"):
            bullet(_RANK_STATISTICAL, d.get("reading"),
                   (f"It is usable prospectively: the value is known "
                    f"{d.get('best_lag_weeks')} week(s) before the demand it precedes."
                    if (d.get("best_lag_weeks") or 0) > 0 else
                    "It moves with demand in the same week."),
                   None, evidence_id="E7", strength="Moderate")
        elif d.get("coverage") == "sparse":
            bullet(_RANK_SUFFICIENCY, d.get("reading"),
                   "So it was not used to support any conclusion.", None,
                   evidence_id="E8", strength="Weak")

    # 6. ASU split (section 19).
    if asu.get("available"):
        # "The gap is a mixed." -- the article does not survive every interpretation value, and
        # three of the four are not noun phrases. Worded per value instead.
        _asu_says = {"population/base effect": ("The gap is driven by the supported population "
                                                "differing from plan."),
                     "contact-rate effect": ("The gap is driven by contacts per unit differing "
                                             "from plan, not by the population."),
                     "mixed": "Both the population and the contact rate contributed.",
                     }.get(asu.get("interpretation"),
                           "Neither the population nor the contact rate could be sized.")
        bullet(_RANK_STATISTICAL, asu.get("reading"), None, _asu_says,
               evidence_id="E6", strength="Strong")

    # 7. The plan-vintage bullet is DELETED. It read `Projection_plan_name`, which this engine
    #    treats as non-existent. Nothing is substituted for it -- there is no evidence left about
    #    whether the plan was revisited, so no bullet should imply there is.

    # 8. What argues against (section 31).
    for conflict in (res.get("conflicts") or []):
        bullet(_RANK_CONTRADICTION, conflict.get("conflict"),
               f"Governed by {conflict.get('governed_by')}.",
               conflict.get("resolution"), evidence_id="E14", strength="Moderate")

    out.sort(key=lambda b: b["rank_basis"])

    # De-duplicate on what_happened, keeping the HIGHER-ranked occurrence.
    #
    # Live output printed the same sentence as bullets 2 and 3: the FORECAST_BASELINE_FAILURE
    # candidate's `evidence` IS `miss_decomposition.reading`, and the decomposition bullet uses the
    # same string. Both are legitimately derived, so the fix is here rather than at either source --
    # suppressing one of them upstream would lose the bullet entirely on reports where only that
    # source fires. A reader seeing one finding printed twice reads it as two findings.
    seen, unique = set(), []
    for b in out:
        keyed = (b.get("what_happened") or "").strip()
        if keyed and keyed in seen:
            continue
        seen.add(keyed)
        unique.append(b)
    dropped = len(out) - len(unique)
    out = unique

    for i, b in enumerate(out, start=1):
        b["rank"] = i
        b["jargon_found"] = jargon_in(b["text"])
        # Section 27. Reported, not stripped: a bullet whose evidence genuinely supports causation
        # is allowed to say so, and the reviewer needs to see WHICH verb was used to judge that.
        b["causal_verbs_found"] = causal_verbs_in(b["text"])
    return {
        "bullets": out,
        "count": len(out),
        "duplicates_dropped": dropped,
        "ranking_basis": ["causal coherence", "forecastability", "historical consistency",
                          "statistical strength", "data sufficiency", "contradiction resolution"],
        "ranked_deterministically": True,
        "note": ("Order is set by the evidence, not by the narrative model. The model may reword a "
                 "bullet; it cannot reorder, add or remove one."),
        "jargon_found": sorted({j for b in out for j in b["jargon_found"]}),
        "causal_verbs_found": sorted({v for b in out for v in b["causal_verbs_found"]}),
        "preferred_phrasing": list(HEDGED_ALTERNATIVES),
    }


def _with_narrative(why, narrative):
    """Overlay the model's rewording onto the deterministic bullets, matched BY RANK.

    Matched by rank rather than by position, so a model that returns the entries in a different
    order cannot silently reassign one bullet's prose to another bullet's evidence. `narrative_prompt`
    already discards a reordered list outright; this is the second line of defence, and it is here
    because the failure mode -- correct-looking prose attached to the wrong evidence ID -- is
    invisible on the rendered card.

    `text` keeps the deterministic wording when there is no rewrite, so the card is never blank and
    never depends on the model having succeeded.
    """
    w = dict(why or {})
    bullets = [dict(b) for b in (w.get("bullets") or [])]
    reworded = {b.get("rank"): b.get("text") for b in ((narrative or {}).get("whyThisHappened") or [])
                if isinstance(b, dict) and b.get("text")}
    used = 0
    for b in bullets:
        alt = reworded.get(b.get("rank"))
        b["text_deterministic"] = b.get("text")
        if alt:
            b["text"] = alt
            b["reworded_by_model"] = True
            used += 1
    w["bullets"] = bullets
    w["reworded_count"] = used
    w["wording_source"] = ("model rewording over deterministic bullets" if used
                           else "deterministic wording only")
    return w


# ==============================================================================
# Sections 14-15 -- Forecast Response panel
# ==============================================================================
def forecast_response_panel(resp):
    """What signal existed, and whether the plan captured it (section 39's Forecast Response)."""
    r = resp or {}
    if not r.get("available"):
        return {"available": False, "reason": r.get("reason")
                or "the forecast-response diagnostic could not run on this queue's history."}
    response = r.get("response") or {}
    gate = r.get("forecastability_gate") or {}
    fcb = r.get("forecastability") or {}
    dec = r.get("miss_decomposition") or {}
    return {
        "available": True,
        "expected_demand": dec.get("expected_demand"),
        "expected_basis": dec.get("expected_basis"),
        "forecast_side_contribution": dec.get("forecast_side_contribution"),
        "demand_side_contribution": dec.get("demand_side_contribution"),
        "forecast_side_share": dec.get("forecast_side_share"),
        "demand_side_share": dec.get("demand_side_share"),
        "decomposition_reconciles": dec.get("reconciles"),
        "decomposition_reading": dec.get("reading"),
        "signals": [{"signal": s.get("signal"), "detected": s.get("detected"),
                     "direction": s.get("direction"),
                     "visible_from_fiscal_week": s.get("visible_from_fiscal_week"),
                     "reading": s.get("reading")}
                    for s in (r.get("signals") or [])],
        "response_classification": response.get("classification"),
        "response_reason": response.get("reason"),
        "implied_change": response.get("implied_change"),
        "forecast_change_made": response.get("forecast_change_made"),
        "timing_note": response.get("timing_note"),
        "forecastability": fcb.get("classification"),
        "forecastability_reason": fcb.get("reason"),
        "gate_conditions": gate.get("conditions"),
        "gate_verdict": gate.get("verdict"),
        "supports_forecast_failure": gate.get("supports_forecast_response_failure"),
        "how_to_read": ("The plan is judged against what the expected demand level implied it "
                        "needed to do, never against the outcome. Judging it against the outcome "
                        "would make every miss a forecast failure by definition."),
    }


# ==============================================================================
# Sections 22-25 -- Calendar and weekend context
# ==============================================================================
# The 14 metrics the engine computes, in reading order: accuracy, then spread, then shape over time,
# then the calendar, then the plan against the calendar, then outliers. Labels are the reader's
# vocabulary, not the payload key. Ordered deliberately -- a reader who stops a third of the way down
# should still have the three things that matter most.
STAT_PROFILE_ORDER = [
    ("accuracy_recent", "Forecast accuracy - recent"),
    ("accuracy_year", "Forecast accuracy - 52 weeks"),
    ("accuracy_long", "Forecast accuracy - full history"),
    ("coefficient_of_variation_recent", "Volatility - recent"),
    ("coefficient_of_variation_long", "Volatility - full history"),
    ("trend_recent", "Trend - recent"),
    ("trend_year", "Trend - 52 weeks"),
    ("drift_recent", "Baseline drift - recent"),
    ("drift_year", "Baseline drift - 52 weeks"),
    ("momentum", "Momentum"),
    ("seasonality", "Seasonality for this fiscal week"),
    ("plan_vs_seasonal_norm", "Plan against the seasonal norm"),
    ("outliers", "Outlier detection"),
]


def statistical_profile(result):
    """A standing statistical profile of this queue, whether or not it supports the conclusion.

    Deliberately NOT filtered by what the conclusion needs. A metric that argues against the finding,
    or simply says nothing, is information -- and a panel that only ever shows corroborating numbers
    teaches a reader to distrust it. Metrics that could not be computed are RETURNED with their note
    rather than dropped, for the same reason section 17 separates "not tested" from "not present".
    """
    se = result.get("statistical_evidence") or {}
    if not se.get("available"):
        return {"available": False,
                "reason": se.get("reason") or "not enough history for statistical measures",
                "how_to_read": ("Deterministic arithmetic on this queue's own history. No model is "
                                "involved and nothing here is model-written.")}

    metrics = se.get("metrics") or {}
    # Which metrics actually fed the ranked conclusion, so context can be told from cause.
    used = {str(f.get("rank_basis") or "") for f in (se.get("findings") or [])}
    used |= {str((result.get("root_cause") or {}).get("rank_basis") or "")}

    rows = []
    for key, label in STAT_PROFILE_ORDER:
        blk = metrics.get(key)
        if not blk:
            continue
        ok = blk.get("available") is not False
        rows.append({
            "metric": key, "label": label, "available": ok,
            "reading": (blk.get("reading") if ok else None),
            "note": (None if ok else (blk.get("note") or "not available for this queue")),
            # A prefix match, since rank_basis is the family ("drift") and the metric key is the
            # window ("drift_recent"). An exact match would report every window as unused.
            "fed_the_conclusion": any(u and (key == u or key.startswith(u) or u.startswith(key))
                                      for u in used if u),
        })

    return {
        "available": True,
        "weeks_available": se.get("weeks_available"),
        "metrics_shown": len(rows),
        "metrics_unavailable": sum(1 for r in rows if not r["available"]),
        "rows": rows,
        "findings": [{"title": f.get("title"), "cause_type": f.get("cause_type"),
                      "confidence_pct": f.get("confidence_pct"),
                      "rank_basis": f.get("rank_basis")}
                     for f in (se.get("findings") or [])],
        "correlations": [{"subject": c.get("subject"), "field": c.get("field"),
                          "pearson_r": c.get("pearson_r"), "n": c.get("n"),
                          "strength": c.get("strength"), "direction": c.get("direction"),
                          "reading": c.get("reading")}
                         for c in (metrics.get("correlations_pearson") or [])],
        "how_to_read": ("Deterministic arithmetic on this queue's own %s weeks of history - no model "
                        "involved, and it runs whether or not the miss also appears at a higher "
                        "level. Shown whatever it says: a measure that argues against the conclusion, "
                        "or says nothing, is reported the same as one that supports it. Anything that "
                        "could not be computed says so instead of being dropped."
                        % (se.get("weeks_available") or 0)),
    }


def calendar_panel(holiday, weekend):
    """Pre / holiday / post, plus what the data grain will and will not support."""
    h, w = holiday or {}, weekend or {}
    phases = (h.get("historical_response") or {}).get("phases") or {}
    return {
        "available": bool(h.get("available")),
        "availability": h.get("availability"),
        "reason": h.get("reason"),
        "phase": h.get("phase"),
        "applies": h.get("applies"),
        "span_weeks": h.get("span_weeks"),
        "zero_count_but_adjacent": h.get("zero_count_but_adjacent"),
        "row_holiday_count": h.get("row_holiday_count"),
        "calendar_names": h.get("calendar_names") or [],
        # prompt2.md clause F -- MANDATORY. These two must never be shown as one list: on a queue
        # with Holiday_Count = 0 the old single list read as four holidays "in this week" when none
        # of them fell inside it.
        "holidays_in_target_week": h.get("holidays_in_target_week"),
        "recent_holidays_affecting_target_week": h.get("recent_holidays_affecting_target_week"),
        "raw_source_names": h.get("calendar_raw_names") or [],
        "event_summary": h.get("event_summary"),
        "event_summary_source": h.get("event_summary_source"),
        "names_needing_review": h.get("names_needing_review") or [],
        "row_flag_disagreement": h.get("row_flag_disagreement"),
        "phases": {k: {"instances": v.get("instances"),
                       "actual_effect_pct": v.get("actual_effect_pct"),
                       # The plan's own movement for these weeks. Present on the phase block all
                       # along and simply not projected, which forced the renderer to read it out of
                       # the prose -- so every row repeated the whole sentence to carry one number.
                       "forecast_effect_pct": v.get("forecast_effect_pct"),
                       "historically_planned_for": v.get("historically_planned_for"),
                       "direction": v.get("direction"),
                       "consistency": v.get("consistency"),
                       "consistent": v.get("consistent"),
                       "material": v.get("material"),
                       "historically_planned_for": v.get("historically_planned_for"),
                       "testable": v.get("testable"),
                       "reading": v.get("reading") or v.get("reason")}
                   for k, v in phases.items()},
        "forecast_capture": h.get("forecast_capture"),
        # A DIFFERENT question from forecast_capture, and both are shown: capture asks whether the
        # plan applied the pattern to THIS week; plan_bias asks whether the plan has been missing the
        # same way, or by a growing amount, on these weeks for years. Only the second justifies
        # changing the adjustment rule rather than this week's number.
        "plan_bias": h.get("plan_bias"),
        "historical_consistency": h.get("historical_consistency"),
        "expected_direction": h.get("expected_direction"),
        "statement": h.get("reading"),
        # Section 9 measurement A, beside measurement B (`phases`) so a reader sees both and the
        # difference between them. Without this the card could only show the standing level.
        "phase_transition": h.get("phase_transition"),
        # Section 10's band over that rebound's history.
        "rebound_repeatability": h.get("rebound_repeatability"),
        "weekend": {
            "supported": w.get("weekend_analysis_supported"),
            "grain": w.get("grain"),
            "statement": w.get("statement"),
            "holiday_day_structure": w.get("holiday_day_structure"),
            # Section 12. The weekend VOLUME effect is still not isolable and the statement above
            # still says so -- but whether a holiday adjoining the weekend behaves differently IS
            # measurable from weekly totals, and the card was showing only the limitation.
            "holiday_weekend_interaction": w.get("holiday_weekend_interaction"),
            # Clause C: three states, not one refusal. Clause K: per-weekday weekly outcomes.
            "clause_c_states": w.get("clause_c_states"),
            "weekday_outcomes": w.get("weekday_outcomes"),
            "p2_state": w.get("p2_state"),
        },
        "how_to_read": ("A week with no holiday recorded on its own row can still be pre- or "
                        "post-holiday. An observed phase effect is only held against the plan "
                        "where this queue's own history responds to that phase consistently."),
    }


# ==============================================================================
# Sections 16-21 -- Driver evidence
# ==============================================================================
def driver_panel(lag, asu):
    """ASU, Shipment, UPP and any other applicable driver, with coverage never collapsed."""
    l, a = lag or {}, asu or {}
    return {
        "available": bool(l.get("available")),
        "availability": l.get("availability"),
        "reason": l.get("reason"),
        "requested_drivers": l.get("requested_drivers") or [],
        "lags_tested": l.get("lags_tested"),
        "coverage_summary": l.get("coverage_summary"),
        "usable_drivers": l.get("usable_drivers") or [],
        "leading_drivers": l.get("leading_drivers") or [],
        "drivers": [{"driver": d.get("driver"), "subject": d.get("subject"),
                     "coverage": d.get("coverage"), "availability": d.get("availability"),
                     "requested_by": d.get("requested_by"),
                     "best_lag_weeks": d.get("best_lag_weeks"),
                     "relationship_type": d.get("relationship_type"),
                     "relationship_strength": d.get("relationship_strength"),
                     "direction": d.get("direction"), "stability": d.get("stability"),
                     "paired_weeks": d.get("paired_weeks"),
                     "usable_as_evidence": d.get("usable_as_evidence"),
                     # Section 16 item 10: the relationship in the weeks that actually MISSED, which
                     # are the only weeks an RCA is about. A driver can track ordinary weeks and say
                     # nothing about the misses.
                     "during_miss_weeks": d.get("during_miss_weeks"),
                     "reading": d.get("reading")}
                    for d in (l.get("drivers") or [])],
        # Sections 16-17. Present when the relevance gate rejected a driver on a measurable but
        # sub-threshold coefficient: it is re-examined at other lags and on week-to-week change so
        # "not confirmed at the gate" is not the last word. It never promotes a driver to evidence.
        "enrichment": l.get("enrichment"),
        "asu_decomposition": a,
        "how_to_read": ("Drivers were selected by the hypotheses that fired, not swept. "
                        "'Populated', 'sparse' and 'absent' are three different findings: only the "
                        "first can support a conclusion, and 'absent' is a data gap rather than "
                        "evidence that the driver does not matter."),
        "shipment_vs_upp": ("Shipment (Final_Units) is planned units for delivery. UPP "
                            "(Final_upp_units) is additional installed units under an upgrade or "
                            "extended-protection plan. They are separate drivers and are never "
                            "combined."),
    }


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
    #
    # Every marker used to render in the same red alarm styling, so a neutral fact sat beside genuine
    # warnings and read as one. `markers` stays a list of plain strings for anything already consuming
    # it; `marker_detail` carries the tone so the UI can tell a warning from a note.
    markers = []
    detail = []

    def mark(text, tone):
        markers.append(text)
        detail.append({"text": text, "tone": tone})

    if result.get("major_deviation"):
        mark("Major Deviation", "warn")
    if not result.get("material", True):
        # Was: "Below materiality floor -- worklist suppressed, RCA still generated". Every word of
        # that is engine vocabulary, and it fires on the MAJORITY of investigable weeks -- 23,095 of
        # the 44,883 rows beyond the band sit under the 50-contact floor. A note that common, painted
        # red and written in internal language, trains the reader to ignore the marker row.
        #
        # What a reader needs is the number and its consequence: the gap is small, so the percentage
        # is the misleading part, and nothing about the analysis below is affected.
        v = variance
        if isinstance(v, (int, float)):
            # rnd(), the same formatter the rest of the card uses. round() applies banker's
            # rounding, so a 22.5-contact gap printed as "22" -- a small thing, and exactly the kind
            # of quiet disagreement between two figures on one card that costs a reader trust.
            mark(f"Small miss: {rnd(abs(v))} contacts, under the {MATERIALITY_FLOOR_CONTACTS}-"
                 f"contact floor for ranking. The percentage overstates it; the analysis below is "
                 f"unaffected.", "info")
        else:
            mark(f"Small miss: under the {MATERIALITY_FLOOR_CONTACTS}-contact floor for ranking, so "
                 f"the percentage overstates it. The analysis below is unaffected.", "info")
    if not period.get("complete", True):
        mark(f"Timeline: {period.get('label')}", "info")
    if result.get("status") == "Incomplete":
        mark("Investigation Incomplete", "warn")

    narrative = result.get("narrative") or {}
    inconclusive = rc.get("cause_type") == INCONCLUSIVE
    crit = result.get("criticality") or {}
    if crit.get("band") and crit["band"] in ("Critical", "High"):
        mark(f"Criticality: {crit['band']}", "warn")

    return {
        # --- 3.1 mandatory header ---
        "header": {
            "marker_detail": detail,   # same markers, each with a tone: "warn" or "info"
            "forecast_adherence_pct": adh,               # SIGNED, never absolute
            "direction": fs.get("direction"),            # business language
            "absolute_variance_contacts": variance,
            "forecast": fs.get("forecast"), "actual": fs.get("actual"),
            "grain": result.get("grain"),
            "period": period.get("label"),
            "queue": key.get("Forecast_name"),
            "volume_band": (result.get("volume_band") or None),
            "confidence_level": conf.get("level"),
            # ADDITIVE. Criticality sits beside confidence in the header and never replaces it --
            # a reader needs both numbers to triage, and only one of them says how much the miss
            # matters.
            "criticality_band": crit.get("band"),
            "miss_mechanism": rc.get("miss_mechanism"),
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
            # --- ADDITIVE sections (section 39). The ten above are byte-identical in structure ---
            # and every existing consumer keeps working. These are numbered from 11 so the original
            # ordering is preserved and a renderer that does not know them simply ignores them.
            "11_criticality": criticality_panel(crit),
            # Reuse the bullets the engine already built and handed to the model, so the prose and
            # the card cannot disagree about what the points are or what order they come in.
            # Recomputing here would let them drift apart silently.
            "12_why_this_happened": _with_narrative(result.get("decision_card_why")
                                                    or why_bullets(result), narrative),
            "13_forecast_response": forecast_response_panel(
                result.get("forecast_response_diagnostic")),
            "14_calendar_context": calendar_panel(result.get("holiday_response"),
                                                  result.get("weekend_diagnostic")),
            "15_driver_evidence": driver_panel(result.get("lagged_driver_evidence"),
                                               result.get("asu_decomposition")),
            "16_evidence_index": result.get("fc_evidence_index"),
            "17_contradiction_resolution": result.get("evidence_resolution"),
            # 19 rather than slotted in mid-list: the existing 18 keep their keys and order, which is
            # the non-breaking guarantee. Everything here was already computed and discarded.
            "19_statistical_profile": statistical_profile(result),
            "18_catalogue_gaps": {
                # Section 9: an observation the catalogue cannot carry is shown as a GAP, so a
                # reader can see the engine noticed something it had no sanctioned hypothesis for.
                # Silence here would be indistinguishable from having nothing to report.
                "items": result.get("unexplained_observations") or [],
                "count": len(result.get("unexplained_observations") or []),
                "note": ("Observations the evidence supports but the fixed catalogue has no entry "
                         "for. Recorded for catalogue extension, never converted into a cause."),
            },
        },
        "status": result.get("status"),
        "incomplete_reason": result.get("incomplete_reason"),
        "engine": result.get("engine"),
        # Section 28's A-F reading order, published BESIDE the eighteen sections rather than
        # replacing them. See a_to_f_view's docstring for why section 1 wins the conflict.
        "view_a_to_f": a_to_f_view(result),
        # 2.1.0: eight additive sections, a criticality band and the miss mechanism on the header.
        # Nothing removed or restructured -- see the section list above.
        "card_version": "2.1.0",
    }


def a_to_f_view(result):
    """Section 28's A-F reading order, assembled from what the eighteen sections already hold.

    A VIEW, not a calculation. Nothing here computes a number; every value is drawn from a block the
    engine already produced, and every entry names its source in `from` so this can never drift into
    being a second source of truth.
    """
    rc = result.get("root_cause") or {}
    conf = result.get("confidence") or {}
    crit = result.get("criticality") or {}
    mech = result.get("miss_mechanism") or {}
    resp = result.get("forecast_response_diagnostic") or {}
    hol = result.get("holiday_response") or {}
    wk = result.get("weekend_diagnostic") or {}
    lag = result.get("lagged_driver_evidence") or {}
    asu = result.get("asu_decomposition") or {}
    stats = result.get("statistical_evidence") or {}
    narrative = result.get("narrative") or {}
    # The header is assembled inline in build(); reading forecast_summary directly keeps this view
    # independent of build()'s locals and draws on exactly the same source the header uses.
    fs = result.get("forecast_summary") or {}

    def phase(name):
        block = ((hol.get("historical_response") or {}).get("phases") or {}).get(name) or {}
        if not hol.get("available"):
            return {"state": "NOT_AVAILABLE", "detail": hol.get("reason") or hol.get("note")}
        if not block:
            return {"state": "NOT_AVAILABLE",
                    "detail": "no measured history for this phase on this queue"}
        if not block.get("testable"):
            return {"state": "INCONCLUSIVE", "detail": block.get("reason")}
        return {"state": "MEASURED", "effect_pct": block.get("actual_effect_pct"),
                "instances": block.get("instances"), "detail": block.get("reading")}

    def driver(name):
        for row in (lag.get("drivers") or []):
            if row.get("driver") == name:
                return {"state": ("AVAILABLE" if row.get("usable_as_evidence") else "NOT_CONFIRMED"),
                        "coverage": row.get("coverage"),
                        "best_lag_weeks": row.get("best_lag_weeks"),
                        "during_miss_weeks": row.get("during_miss_weeks"),
                        "detail": row.get("reading") or row.get("interpretation")}
        # Not requested is a different finding from not related -- section 17.
        enr = (lag.get("enrichment") or {})
        for row in (enr.get("drivers") or []):
            if row.get("driver") == name:
                return {"state": "NOT_CONFIRMED", "coverage": row.get("coverage"),
                        "best_lag_weeks": row.get("strongest_lag_weeks"),
                        "detail": row.get("reading")}
        return {"state": "NOT_TESTED",
                "detail": (lag.get("reason")
                           or "no hypothesis required this driver, so it was not tested. An "
                              "untested driver is not a driver that was ruled out.")}

    not_confirmed = []
    for item in (result.get("limitations") or []):
        not_confirmed.append({"item": item, "from": "8_limitations"})
    for g in ((result.get("driver_gate") or {}).get("results") or []):
        if g.get("relationship_state") == "not_confirmed":
            not_confirmed.append({"item": g.get("reason"), "from": "driver_gate"})
    if not wk.get("weekend_analysis_supported"):
        not_confirmed.append({"item": wk.get("statement"), "from": "14_calendar_context"})
    res_block = result.get("evidence_resolution") or {}
    if res_block.get("state") in ("mixed", "rejected"):
        not_confirmed.append({"item": res_block.get("reason") or res_block.get("reading"),
                              "from": "17_contradiction_resolution"})

    return {
        "A_executive_rca": {
            "from": ["1_executive_summary", "2_root_cause", "3_confidence", "11_criticality"],
            "primary_rca": rc.get("hypothesis"),
            "confidence": {"level": conf.get("level"), "score_pct": conf.get("score_pct"),
                           "capped": conf.get("capped")},
            "criticality": crit.get("band"),
            "actual": fs.get("actual"), "forecast": fs.get("forecast"),
            "miss_contacts": fs.get("absolute_variance_contacts"),
            "adherence_pct": fs.get("adherence_pct"),
            "direction": fs.get("direction"),
            "executive_narrative": narrative.get("executiveSummary"),
        },
        "B_why_did_forecast_miss": {
            "from": ["12_why_this_happened", "13_forecast_response"],
            "demand_movement": (resp.get("miss_decomposition") or {}).get("reading"),
            "forecast_response": (resp.get("response") or {}).get("classification"),
            "forecast_response_detail": (resp.get("response") or {}).get("reason"),
            "forecast_failure_mechanism": mech.get("primary"),
            "mechanism_meaning": mech.get("meaning"),
            # Section 15's finer vocabulary, where the evidence supported it.
            "refinements": mech.get("refinements") or [],
            "spec_taxonomy": mech.get("spec_taxonomy") or {},
        },
        "C_calendar_impact": {
            "from": ["14_calendar_context"],
            "pre_holiday": phase("pre_holiday"),
            "holiday": phase("holiday"),
            "post_holiday": phase("post_holiday"),
            "weekend": {"state": ("MEASURED" if wk.get("weekend_analysis_supported")
                                  else "NOT_AVAILABLE"),
                        "detail": wk.get("statement")},
            "long_weekend": (wk.get("holiday_weekend_interaction") or {}).get(
                "long_weekend_contrast"),
            "post_holiday_rebound": hol.get("phase_transition"),
            "historical_consistency": hol.get("rebound_repeatability"),
            "forecast_captured_the_calendar_change": (hol.get("forecast_capture") or {}).get(
                "classification"),
        },
        "D_demand_drivers": {
            "from": ["15_driver_evidence", "statistical_evidence"],
            "asu": driver("Actual_ASU"),
            "asu_decomposition": {"state": ("MEASURED" if asu.get("available") else "NOT_AVAILABLE"),
                                  "detail": asu.get("reading") or asu.get("reason")},
            "shipment_final_units": driver("Final_Units"),
            "final_upp_units": driver("Final_upp_units"),
            "seasonality": (stats.get("metrics") or {}).get("seasonality"),
            "momentum_shift": (stats.get("metrics") or {}).get("momentum"),
        },
        "E_what_is_not_confirmed": {
            "from": ["8_limitations", "9_data_availability", "17_contradiction_resolution",
                     "18_catalogue_gaps", "driver_gate"],
            "items": [x for x in not_confirmed if x.get("item")],
            "catalogue_gaps": result.get("unexplained_observations") or [],
        },
        "F_wfm_action": {
            "from": ["7_recommendations"],
            "recommendations": result.get("recommendations") or [],
            "note": ("Only actions the evidence already supports. An empty list means the evidence "
                     "did not support a recommendation, not that none was sought."),
        },
        "note": ("Section 28's reading order, as a VIEW over the eighteen numbered sections -- "
                 "which are unchanged. Section 28 asks for A-F and section 1 forbids reordering "
                 "existing output, so both are honoured: nothing moved, and A-F points at the same "
                 "data. Every entry names its source section in `from`."),
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
