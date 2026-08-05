# -*- coding: utf-8 -*-
"""Driver Relevance Gate and empirical lag selection.

Implements `FC_RCA_Statistical_Framework.md` sections 12, 13 and 14, and `BR-121`.

WHY THIS MODULE EXISTS
----------------------
A driver applies to a queue only where it has demonstrated a relationship with THAT
queue's demand. Previously drivers were quoted as evidence for every queue regardless,
which is how a business lead ended up being told that units under warranty drive a queue
where they demonstrably do not.

    RELEVANT  when  |correlation(driver, Actual_Offered)| >= 0.30  over n >= 30

Spec-measured pass rates across the 427-queue reference set:

    Actual_ASU        236 of 427   55%
    Final_Units        76 of 427   18%
    Warranty band      78 of 427   18%
    ALL THREE FAIL    139 of 427   33%

A third of queues have no usable driver at all. That is a finding, not a failure -- those
queues route to calendar, volume and data-quality hypotheses instead.

STOCK VERSUS FLOW -- DIFFERENT LAG TREATMENT
---------------------------------------------
    STOCK  (ASU / installed base)  tested CONTEMPORANEOUSLY, never lagged, and correlated
                                   on the weekly average LEVEL, never a sum
    FLOW   (shipments, warranty bands)  MAY lag -- determined empirically per queue

Version 1.0.0 REQUIRED a lag for flow measures. Measured against reference data, fixed
lags REDUCE correlation:

    Final_Units vs Actual_Offered, queues with |r| >= 0.3
        Lag 0   19%      <- best
        Lag 4   16%
        Lag 8   17%
        Lag 13  15%

No fixed lag improves on contemporaneous. A queue-specific lag may exist; a universal one
does not. So the lag is scanned 0..13 per queue and the winner recorded -- and the spec
requires the selected lag to appear in the evidence and in the narrative.

WHY THE GATE TESTS AGAINST DEMAND, NOT ADHERENCE
--------------------------------------------------
Adherence is a property of the forecast, not of the business. A driver that tracks
adherence is telling you about the planner's habits; a driver that tracks demand is
telling you about the world.

TWO MANDATORY EXCLUSIONS
-------------------------
1. Raw `Final_Y1`..`Final_Y5` shall NEVER enter a correlation. They are NESTED -- Y2 sits
   inside Y1 -- so correlating both produces spurious multicollinearity and attribution
   that cannot be interpreted. Only EXCLUSIVE bands, derived by differencing, are valid.
2. Rows failing BR-112 (warranty Tier C) are EXCLUDED from any warranty or shipment
   correlation -- not imputed, not zero-filled. Broken data is removed, not invented.

A NOTE ON WHAT THIS GATE DOES NOT DO
--------------------------------------
The gate as specified correlates raw LEVELS. Measured on this dataset, level correlations
between two multi-year declining series are dominated by shared time trend: of 310
relationships retained on levels at |r| >= 0.5, 282 (91%) fall to near zero once
week-over-week changes are used instead. Significance testing does not catch it -- at
n > 100 those are all highly significant.

`co_movement_r` is therefore reported ALONGSIDE the gate result on every driver, so the
difference is visible rather than hidden. The gate verdict itself follows the spec
exactly; the extra figure is advisory and flagged when the two disagree.
"""
from .common import num

MIN_ABS_R = 0.30
MIN_N = 30
MAX_LAG = 13

STOCK = "stock"
FLOW = "flow"

# Business wording for each driver. Every figure this module emits is labelled with BOTH
# the business term and the column name -- a bare "r=+0.57" in a report tells the reader
# nothing about WHICH driver it belongs to, and three of them in a row are indistinguishable.
#
# Final_Units is "planned units for delivery (shipment)", NOT "installed base". Installed
# base IS ASU (Active Serviceable Units); calling shipments the installed base points the
# reader at the wrong lever entirely.
DRIVER_LABEL = {
    "Actual_ASU": "actual units under warranty",
    "Planned_ASU": "planned units under warranty",
    "Final_Units": "planned units for delivery (shipment)",
    "warranty_band_exclusive": "warranty band mix",
}


def label_for(field):
    """'actual units under warranty (Actual_ASU)' -- business term plus the column."""
    name = DRIVER_LABEL.get(field)
    return f"{name} ({field})" if name else field

# Nature per the Statistical Framework correlation-variables table.
DRIVER_NATURE = {
    "Actual_ASU": STOCK,
    "Planned_ASU": STOCK,
    "Final_Units": FLOW,          # shipments
    "warranty_band_exclusive": FLOW,
}

# NEVER correlate these directly -- nested tiers, see module docstring.
FORBIDDEN_RAW = ("Final_Y1", "Final_Y2", "Final_Y3", "Final_Y4", "Final_Y5")


def _pearson(xs, ys):
    """Pearson r over paired values, or None when undefined."""
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    n = len(pairs)
    if n < 3:
        return None, n
    mx = sum(p[0] for p in pairs) / n
    my = sum(p[1] for p in pairs) / n
    cov = sum((a - mx) * (b - my) for a, b in pairs)
    vx = sum((a - mx) ** 2 for a, _ in pairs)
    vy = sum((b - my) ** 2 for _, b in pairs)
    if vx <= 0 or vy <= 0:
        return None, n
    return cov / ((vx * vy) ** 0.5), n


def _deltas(xs, ys):
    """Week-over-week changes, for the advisory co-movement figure."""
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    dx = [pairs[i][0] - pairs[i - 1][0] for i in range(1, len(pairs))]
    dy = [pairs[i][1] - pairs[i - 1][1] for i in range(1, len(pairs))]
    return dx, dy


def exclusive_bands(row):
    """Derive EXCLUSIVE warranty bands by differencing the nested tiers.

    Final_Y1 contains Y2 contains Y3... so the exclusive population in band k is
    Yk - Y(k+1). Only these may enter a correlation.
    """
    y = [num(row.get(f"Final_Y{i}")) for i in range(1, 6)]
    out = {}
    for i in range(5):
        if y[i] is None:
            continue
        nxt = y[i + 1] if i + 1 < 5 else 0
        nxt = nxt if nxt is not None else 0
        out[f"band_Y{i + 1}_exclusive"] = y[i] - nxt
    return out


def evaluate(history, driver_field, tier_c_weeks=None):
    """Run the gate for one driver against one queue's history.

    `history`  rows carrying Fiscal_Week, Actual_Offered and the driver field.
    `tier_c_weeks` weeks failing BR-112, excluded for warranty/shipment drivers.

    Returns the verdict plus everything needed to state it in evidence: the correlation,
    the n, the selected lag, and the advisory co-movement figure.
    """
    if driver_field in FORBIDDEN_RAW:
        return {"driver": driver_field, "relevant": False, "verdict": "forbidden",
                "reason": (f"{driver_field} is a NESTED warranty tier and shall never enter a "
                           f"correlation directly. Use exclusive bands derived by differencing.")}

    nature = DRIVER_NATURE.get(driver_field, FLOW)
    excluded = set(tier_c_weeks or ())
    rows = [r for r in (history or [])
            if r.get("Fiscal_Week") not in excluded]

    demand = [num(r.get("Actual_Offered")) for r in rows]
    series = [num(r.get(driver_field)) for r in rows]

    # Stock is contemporaneous by definition. Flow gets an empirical scan.
    if nature == STOCK:
        r, n = _pearson(series, demand)
        lag, scanned = 0, [0]
    else:
        best = (0, None, 0)
        scanned = []
        for k in range(0, MAX_LAG + 1):
            s, d = (series[:-k], demand[k:]) if k else (series, demand)
            rk, nk = _pearson(s, d)
            if rk is None:
                continue
            scanned.append(k)
            if best[1] is None or abs(rk) > abs(best[1]):
                best = (k, rk, nk)
        lag, r, n = best

    if r is None or n < MIN_N:
        return {"driver": driver_field, "nature": nature, "relevant": False,
                "verdict": "insufficient_data", "correlation": r, "n": n,
                "lag_weeks": lag, "threshold_r": MIN_ABS_R, "threshold_n": MIN_N,
                "reason": (f"Only {n} comparable week(s) for {driver_field}; the gate needs "
                           f"at least {MIN_N}.")}

    relevant = abs(r) >= MIN_ABS_R

    # Advisory: the same relationship on week-over-week movement.
    s, d = (series[:-lag], demand[lag:]) if lag else (series, demand)
    dx, dy = _deltas(s, d)
    co_r, co_n = _pearson(dx, dy)

    # Advisory flag: the driver clears the gate on LEVELS but would FAIL the very same
    # gate on week-to-week MOVEMENT. Same threshold, different quantity -- so this is not
    # a second invented cutoff. It is the signature of shared time trend.
    trend_warning = None
    if relevant and co_r is not None and abs(co_r) < MIN_ABS_R:
        trend_warning = (
            # NEVER say "on levels" here. The same card reports the investigation ladder --
            # Business Org, Region, Country -- and calls those LEVELS. A reader meeting
            # "passed on levels" in an evidence bullet reasonably assumes it means one of
            # those, and asks which. It means the opposite kind of thing entirely: the raw
            # totals, as against their week-to-week changes. The wording avoids the word.
            f"{label_for(driver_field)} rises and falls with demand when you compare the two "
            f"totals across the whole period (r={r:+.2f}), but their week-to-week movements "
            f"barely match (r={co_r:+.2f}, and {MIN_ABS_R} is the minimum to count). Two "
            f"figures that both drift the same way over years without moving together in any "
            f"given week are following a shared trend, not driving each other. Treat as weak "
            f"supporting evidence and do not make it a primary cause.")

    return {
        "driver": driver_field,
        "nature": nature,
        "relevant": relevant,
        "verdict": "relevant" if relevant else "not_applicable",
        "correlation": round(r, 3),
        "co_movement_r": (round(co_r, 3) if co_r is not None else None),
        "co_movement_n": co_n,
        "n": n,
        "lag_weeks": lag,
        "lags_scanned": (f"0-{max(scanned)}" if len(scanned) > 1 else "0 (stock, contemporaneous)"),
        "threshold_r": MIN_ABS_R,
        "threshold_n": MIN_N,
        "trend_warning": trend_warning,
        "label": label_for(driver_field),
        "reason": (
            f"{label_for(driver_field)} tracks this queue's demand (r={r:+.2f} over {n} weeks"
            + (f", at a {lag}-week lag" if lag else "") + ")."
            if relevant else
            f"{label_for(driver_field)} does not track this queue's demand (r={r:+.2f} over "
            f"{n} weeks, below the {MIN_ABS_R} threshold), so it is Not Applicable for this "
            f"queue and carries no confidence penalty."),
    }


def evaluate_all(history, offering=None, tier_c_weeks=None):
    """Run the gate for every candidate driver, in the offering's cascade order.

    The cascade is business causality; the gate is usability. A driver that fails the gate
    is skipped and the next is tried -- the ORDER never changes to chase a better number.
    """
    from .hypothesis_catalogue import cascade_for

    field_for = {"asu": "Actual_ASU", "shipments": "Final_Units"}
    cascade = cascade_for(offering)
    order = [field_for[d] for d in cascade if d in field_for]
    # Planned_ASU supports the ASU Plan Variance hypothesis, so it is evaluated after the
    # cascade -- but ONLY where the queue has ASU exposure at all. For out-of-warranty
    # offerings the spec is explicit that NEITHER driver applies, and evaluating a
    # warranty driver on a queue with no warranty would manufacture a relationship the
    # business does not have.
    if "asu" in cascade and "Planned_ASU" not in order:
        order.append("Planned_ASU")

    results = [evaluate(history, f, tier_c_weeks) for f in order]
    relevant = [r for r in results if r.get("relevant")]
    return {
        "offering": offering,
        "cascade": order,
        "results": results,
        "primary_driver": (relevant[0]["driver"] if relevant else None),
        "any_driver_relevant": bool(relevant),
        "note": ("No driver passes the relevance gate for this queue, so driver attribution is "
                 "Not Applicable here and the investigation routes to calendar, volume and "
                 "data-quality hypotheses instead."
                 if not relevant else
                 f"{len(relevant)} driver(s) passed the gate; "
                 f"{relevant[0]['driver']} is primary by the {offering or 'default'} cascade."),
    }
