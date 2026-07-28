"""Correlation engine -- the module that was missing.

The prompt asks the model to identify "business relationships consistently supported by
historical evidence" (ASU vs demand, installed base vs demand, holidays vs demand) and to
"ignore weak or accidental correlations". Nothing computed them, so the model was being
asked for relationships it had no numbers for -- an invitation to invent one, which the
CRITICAL RULES forbid. This closes that gap.

Two independent things live here:

1. RELATIONSHIP STRENGTH (`relationships`)
   Rank correlation (Spearman) between each candidate driver and Actual_Offered over the
   queue's own history. Rank-based on purpose: it is unaffected by the single extreme week
   that usually triggered the investigation, where a Pearson correlation would be dragged
   around by it. Relationships are RETAINED or REJECTED in code against explicit
   thresholds, so "ignore weak correlations" is enforced rather than requested.

2. DRIVER DECOMPOSITION (`driver_decomposition`) -- the strongest attribution available
   in this dataset, and exact rather than inferred.

   Demand is driven by the warranty base: contacts = ASU x contacts-per-unit. With both
   Planned_ASU and Actual_ASU present, the miss splits exactly:

       planned_rate = fcst_offered  / Planned_ASU
       actual_rate  = Actual_Offered / Actual_ASU
       volume_effect = (Actual_ASU - Planned_ASU) * planned_rate
       rate_effect   = Actual_ASU * (actual_rate - planned_rate)

   and volume_effect + rate_effect == Actual_Offered - fcst_offered identically. Verified
   exact on all 22,003 flagged misses in this table that carry both columns (60.7%
   rate-driven, 9.8% base-driven, 29.6% mixed).

   That answers a genuinely causal question -- did we miss because the installed base was
   not what we planned, or because contacts per unit moved? -- instead of choosing a label.

NOTE ON LANGUAGE: the prompt forbids the word "correlation" and friends in business-facing
text. Every entry therefore carries a jargon-free `plain_language` string for the report,
with the coefficient kept under `technical_strength` for the collapsed technical section.
"""
from .common import num, rnd

# A relationship is only retained on this much evidence.
_MIN_WEEKS = 12
_MIN_STRENGTH = 0.5

# Candidate drivers, with the business words for them. Field -> plain-English subject.
_DRIVERS = (
    ("Actual_ASU", "the number of units under warranty"),
    ("Planned_ASU", "the planned number of units under warranty"),
    ("Final_Units", "the installed base"),
    ("Holiday_Count", "the number of holidays in the week"),
)


def _ranks(values):
    """Ranks with ties averaged."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        shared = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = shared
        i = j + 1
    return ranks


def _spearman(xs, ys):
    """Rank correlation in [-1, 1], or None when it cannot be computed."""
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 3:
        return None, len(pairs)
    rx = _ranks([p[0] for p in pairs])
    ry = _ranks([p[1] for p in pairs])
    n = len(pairs)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    if vx <= 0 or vy <= 0:
        return None, n
    return cov / ((vx * vy) ** 0.5), n


def _describe(subject, strength):
    direction = "higher" if strength > 0 else "lower"
    if abs(strength) >= 0.8:
        firmness = "almost always"
    elif abs(strength) >= 0.65:
        firmness = "usually"
    else:
        firmness = "more often than not"
    return (f"Historically, when {subject} went up, this queue's demand {firmness} went "
            f"{direction} too.")


def relationships(history_104):
    """Which drivers actually track demand for THIS queue, on its own history."""
    hist = history_104 or []
    demand = [num(h.get("Actual_Offered")) for h in hist]

    retained, rejected = [], []
    for field, subject in _DRIVERS:
        series = [num(h.get(field)) for h in hist]
        strength, n = _spearman(series, demand)
        if strength is None:
            rejected.append({"driver": field, "subject": subject, "weeks": n,
                             "reason": "Not enough usable values in this queue's history "
                                       "to judge the relationship."})
            continue
        entry = {"driver": field, "subject": subject, "weeks": n,
                 "technical_strength": round(strength, 2),
                 "direction": "same" if strength > 0 else "opposite"}
        if n >= _MIN_WEEKS and abs(strength) >= _MIN_STRENGTH:
            entry["plain_language"] = _describe(subject, strength)
            retained.append(entry)
        else:
            entry["reason"] = (f"Relationship too weak or too little history to rely on "
                               f"({n} weeks).")
            rejected.append(entry)

    retained.sort(key=lambda e: abs(e["technical_strength"]), reverse=True)
    return {
        "available": bool(retained or rejected),
        "min_weeks_required": _MIN_WEEKS,
        "min_strength_required": _MIN_STRENGTH,
        "retained": retained,
        "rejected": rejected,
        "note": ("Only relationships consistently supported by this queue's own history are "
                 "retained; the rest are listed as rejected so they are not used as evidence."),
    }


def driver_decomposition(fields):
    """Split the miss exactly into a warranty-base effect and a contacts-per-unit effect.

    `fields` is the target row's raw fields. Returns available=False, with the reason, when
    either ASU column is missing -- about 45% of scoreable rows in this table.
    """
    fcst = num(fields.get("fcst_offered"))
    actual = num(fields.get("Actual_Offered"))
    planned_asu = num(fields.get("Planned_ASU"))
    actual_asu = num(fields.get("Actual_ASU"))

    missing = [n for n, v in (("fcst_offered", fcst), ("Actual_Offered", actual),
                              ("Planned_ASU", planned_asu), ("Actual_ASU", actual_asu))
               if not v]
    if missing:
        return {"available": False,
                "missing_fields": missing,
                "reason": ("Cannot split the miss into a warranty-base effect and a "
                           "contacts-per-unit effect because these values are missing or "
                           "zero for this week: " + ", ".join(missing) + ".")}

    planned_rate = fcst / planned_asu
    actual_rate = actual / actual_asu
    total_error = actual - fcst
    volume_effect = (actual_asu - planned_asu) * planned_rate
    rate_effect = actual_asu * (actual_rate - planned_rate)

    denom = abs(volume_effect) + abs(rate_effect)
    volume_share = (abs(volume_effect) / denom) if denom else 0.0
    if volume_share >= 0.65:
        verdict, headline = "warranty_base_driven", (
            "The miss came mainly from the number of units under warranty not being what "
            "the plan assumed, rather than from customer behaviour changing.")
    elif volume_share <= 0.35:
        verdict, headline = "contact_rate_driven", (
            "The units under warranty were close to plan; the miss came mainly from each "
            "unit generating a different number of contacts than the plan assumed.")
    else:
        verdict, headline = "mixed", (
            "The miss came from both the warranty base and the contacts-per-unit "
            "assumption; neither explains it on its own.")

    return {
        "available": True,
        "planned_units_under_warranty": rnd(planned_asu),
        "actual_units_under_warranty": rnd(actual_asu),
        "planned_contacts_per_unit": round(planned_rate, 8),
        "actual_contacts_per_unit": round(actual_rate, 8),
        "total_miss": rnd(total_error),
        "warranty_base_effect": rnd(volume_effect),
        "contacts_per_unit_effect": rnd(rate_effect),
        "warranty_base_share": round(volume_share, 2),
        "verdict": verdict,
        "plain_language": headline,
        # The two effects sum to the total miss by construction; carried so the report can
        # show it reconciles and any drift is visible rather than silent.
        "reconciles": abs((volume_effect + rate_effect) - total_error) < max(1e-6, abs(total_error) * 1e-9),
    }


def analyse(history_104, target_fields):
    return {
        "relationships": relationships(history_104),
        "driver_decomposition": driver_decomposition(target_fields or {}),
    }
