# -*- coding: utf-8 -*-
"""
Lagged driver relationships -- does a driver LEAD demand, and by how many weeks?

WHY THIS MODULE EXISTS
----------------------
`correlation_engine.relationships()` tests one thing: does driver(t) move with Actual_Offered(t)
in the SAME week. That is the wrong question for most operational drivers. Shipment activity
(`Final_Units`) does not generate a support contact the same week the units leave the factory --
the contact arrives when the customer has the product in hand and something goes wrong with it.
A same-week test on a leading driver returns a weak coefficient, the driver is dropped, and the
engine then reports "no driver relationship" when the real answer is "the relationship is at a
two-week lag".

Worse, the current same-week rejection is reported as though the driver were irrelevant. This
module separates three genuinely different findings (spec section 12):

    usable    -- enough paired observations, and a strong stable relationship at some lag
    weak      -- enough data, but no lag produces a strong stable relationship
    sparse    -- the driver exists in the schema but has too few usable observations
    absent    -- the driver is not present in the data at all

"Sparse" is the one the old code could not say, and it is the honest answer for a field like
`Final_upp_units` on a queue where only a handful of weeks carry a value.

WHAT IS TESTED
--------------
Two relationship families, because they answer different questions:

    LEVEL   driver(t-k)  vs Actual(t)        "busy shipment weeks precede busy contact weeks"
    CHANGE  d-driver(t-k) vs d-Actual(t)     "a RISE in shipments precedes a RISE in contacts"

The change family is the one that matters for a forecast miss. A level relationship can be an
artefact of both series drifting together over two years; a change relationship means the driver
actually moves demand week to week, which is what a forecaster could have reacted to.

Lags 0, 1, 2, 4, 8 weeks. Not a continuous sweep: each extra lag tested is another chance to find
a coefficient by luck, and these five cover same-week, short operational delay, monthly and
quarterly effects without turning the search into a fishing expedition.

METHOD
------
Spearman rank correlation, the same method and the same thresholds `correlation_engine` already
uses (spec section 11 -- keep the established statistical method unless it is demonstrably wrong).
Rank-based, so the one extreme week that usually triggered the investigation cannot drag the
coefficient the way Pearson would.

STABILITY
---------
A coefficient computed once over 150 weeks can hide a relationship that held in year 1 and
reversed in year 2. Every candidate is therefore re-estimated on each half of its own paired
history and the two halves compared. A relationship that does not survive being split is reported
as `unstable` and never promoted to `usable`, because a forecaster cannot act on it.

TARGET-WEEK EXCLUSION
---------------------
The target week is excluded from every estimate. It is the week under investigation; including it
lets the anomaly being explained contribute to the evidence used to explain it. (Note that
`correlation_engine.relationships()` does NOT currently exclude it -- see the module report.)

DEPENDENCIES: standard library only, consistent with the rest of `backend/wfm/`.
"""
import math

from .common import week_ordinals, num

# --- lags tested, in weeks. 0 is kept so this module's answer is directly comparable with the
#     existing same-week correlation rather than being a separate universe of numbers. ---
LAGS = (0, 1, 2, 4, 8)

# --- thresholds. Deliberately the same values as correlation_engine so that two modules cannot
#     disagree about whether the same driver is usable. ---
MIN_PAIRS = 12          # fewer paired observations than this and no coefficient is reported
MIN_STRENGTH = 0.5      # |rho| below this is not strong enough to use as evidence
# How far Spearman and Pearson may differ before the relationship is called non-proportional.
# Same value as STABILITY_TOLERANCE below, and for the same reason: it is the gap at which two
# estimates of one relationship stop telling the same story. One tolerance, used twice.
RANK_LINEAR_TOLERANCE = 0.25
# A week is a MISS at the engine's fixed +/-5% RCA generation threshold. Held here as a module
# constant because lag_analysis is engine-agnostic by design and must not import spec_engine; if
# that threshold ever changes, this has to change with it.
MISS_THRESHOLD_PCT = 5.0
MIN_MISS_PAIRS = 8      # below this the miss-week estimate is reported as too thin, never as zero
STABILITY_MIN_PAIRS = 8  # per half; below this the split test is not attempted
STABILITY_SIGN_FLIP = "unstable"      # halves disagree on direction
STABILITY_TOLERANCE = 0.25            # |rho_first - rho_second| above this is only "moderate"

# --- candidate drivers. Discovered from the data (spec section 5 -- queue-agnostic), but the
#     business meaning of each has to be stated somewhere, and stating it wrongly is how
#     Final_upp_units came to be described as "shipment". These strings are the authority for
#     this module and match FIELD_DEFINITIONS in rca_investigate.py. ---
DRIVER_SUBJECTS = {
    "Actual_ASU": "units actually in the market under warranty",
    "Planned_ASU": "units planned to be in the market under warranty",
    "Final_Units": "planned units for delivery / production (shipment)",
    "Final_upp_units": "additional installed units under an upgrade or extended-protection plan",
    "Holiday_Count": "the number of holidays in the week",
}

# Columns that are never drivers: the metric being explained, its forecast, and the identifiers.
# Handled volumes are excluded from the RCA entirely per the client's instruction.
NOT_DRIVERS = {
    "Actual_Offered", "fcst_offered", "Actual_Handled", "fcst_handled",
    "Fiscal_Week", "Week_Ending", "Forecast_name", "Projection_plan_name", "Forecaster",
    "Region", "SubRegion", "Country", "Offering", "channel", "business_org", "Volume_Category",
    # Final_Y1..Y5 are NESTED SUBSETS of Final_Units (never sum them, never treat them as
    # independent drivers) -- Final_Units is the authoritative shipment field.
    "Final_Y1", "Final_Y2", "Final_Y3", "Final_Y4", "Final_Y5",
    # Per-day holiday flags. Holiday_Count already carries the count; the flags are 0/1 and
    # spike on any holiday week, which produces a meaningless coefficient.
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
}

TARGET_COLUMN = "Actual_Offered"


def _num(v):
    """Coerce to float, or None. Booleans are not numbers; strings arrive from pyODBC/CSV alike."""
    if v is None or v is True or v is False:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _rnd(v, nd=2):
    return round(v, nd) if isinstance(v, (int, float)) and not isinstance(v, bool) else v


def _ranks(values):
    """Ranks with ties averaged -- the standard correction, without which tied driver values
    (a Holiday_Count of 0 in most weeks) would bias the coefficient."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        average_rank = (i + j) / 2.0 + 1
        for k in range(i, j + 1):
            out[order[k]] = average_rank
        i = j + 1
    return out


def _pearson(xs, ys):
    """Linear correlation, reported BESIDE Spearman -- never instead of it (section 16).

    Spearman stays the decision measure because it is rank-based and so is not dragged by a single
    extreme week, which weekly contact volumes produce routinely. Pearson is published because
    section 16 asks for both, and because the GAP between them is itself a reading: when the ranks
    agree strongly and the linear fit does not, the relationship is real but not proportional --
    driven by a few large weeks rather than moving smoothly with the driver.
    """
    n = len(xs)
    if n < 2:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    num = sum(a * b for a, b in zip(dx, dy))
    den = (sum(a * a for a in dx) ** 0.5) * (sum(b * b for b in dy) ** 0.5)
    if not den:
        return None
    return num / den


def _spearman(xs, ys):
    """Spearman rho, or None when it cannot be computed (too few pairs, or no variance in one
    series -- a driver that never changes has no relationship to measure, it has no signal)."""
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    rx, ry = _ranks(xs), _ranks(ys)
    n = len(rx)
    mx, my = sum(rx) / n, sum(ry) / n
    sxx = sum((x - mx) ** 2 for x in rx)
    syy = sum((y - my) ** 2 for y in ry)
    if sxx <= 0 or syy <= 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(rx, ry))
    return sxy / math.sqrt(sxx * syy)


def _series(history, target_week):
    """Chronological rows strictly BEFORE the target week, plus the driver columns present.

    Rows at or after the target week are dropped: the target is what we are explaining, and
    anything after it was not knowable when the forecast was made.
    """
    rows = []
    for row in history or []:
        wk = _num((row or {}).get("Fiscal_Week"))
        if wk is None:
            continue
        if target_week is not None and int(wk) >= int(target_week):
            continue
        rows.append((int(wk), row))
    rows.sort(key=lambda t: t[0])
    return rows


def discover_drivers(rows):
    """Which candidate driver columns actually appear in this queue's history.

    Discovered from the data rather than hard-coded, so a table with a new driver column needs no
    code change (spec section 5). A column is a candidate if it is numeric somewhere in the
    history and is not on the NOT_DRIVERS list.
    """
    seen = set()
    for _, row in rows:
        for key, value in (row or {}).items():
            if key in NOT_DRIVERS or key in seen:
                continue
            if _num(value) is not None:
                seen.add(key)
    # Deterministic order: known drivers first in DRIVER_SUBJECTS order, then anything new,
    # so the output does not reshuffle between runs.
    known = [d for d in DRIVER_SUBJECTS if d in seen]
    extra = sorted(seen - set(known))
    return known + extra


def _paired(rows, driver, lag, change, ordinals=None):
    """Paired (driver, demand) observations at one lag, for one relationship family.

    LEVEL  : driver(t-lag)                      vs Actual(t)
    CHANGE : driver(t-lag) - driver(t-lag-1)    vs Actual(t) - Actual(t-1)

    Pairs are keyed on a continuous week ORDINAL (see common.week_ordinals), not on list position
    and not on raw YYYYWW subtraction. Position would silently pair weeks that are not really
    `lag` apart whenever a week is missing; raw subtraction would break at every fiscal-year
    boundary, because the week before 202701 is 202652.
    """
    ordinals = ordinals or week_ordinals([wk for wk, _ in rows])
    by_ordinal = {}
    for wk, row in rows:
        o = ordinals.get(wk)
        if o is not None:
            by_ordinal[o] = row
    xs, ys = [], []
    for wk, row in rows:
        o = ordinals.get(wk)
        if o is None:
            continue
        demand_now = _num(row.get(TARGET_COLUMN))
        if demand_now is None:
            continue
        src = by_ordinal.get(o - lag)
        if src is None:
            continue
        driver_now = _num(src.get(driver))
        if driver_now is None:
            continue
        if not change:
            xs.append(driver_now)
            ys.append(demand_now)
            continue
        prev_demand_row = by_ordinal.get(o - 1)
        prev_driver_row = by_ordinal.get(o - lag - 1)
        if prev_demand_row is None or prev_driver_row is None:
            continue
        demand_prev = _num(prev_demand_row.get(TARGET_COLUMN))
        driver_prev = _num(prev_driver_row.get(driver))
        if demand_prev is None or driver_prev is None:
            continue
        xs.append(driver_now - driver_prev)
        ys.append(demand_now - demand_prev)
    return xs, ys


def _stability(xs, ys):
    """Re-estimate on each half of the paired history and compare.

    Returns (label, first_half_rho, second_half_rho). A relationship that reverses sign between
    halves is `unstable` however strong it looks overall -- that is a coefficient describing two
    different regimes, not a relationship a forecaster can use.
    """
    n = len(xs)
    half = n // 2
    if half < STABILITY_MIN_PAIRS:
        return "not_testable", None, None
    first = _spearman(xs[:half], ys[:half])
    second = _spearman(xs[half:], ys[half:])
    if first is None or second is None:
        return "not_testable", _rnd(first), _rnd(second)
    if (first >= 0) != (second >= 0):
        return STABILITY_SIGN_FLIP, _rnd(first), _rnd(second)
    if abs(first - second) > STABILITY_TOLERANCE:
        return "moderate", _rnd(first), _rnd(second)
    return "stable", _rnd(first), _rnd(second)


def _miss_week_relationship(rows, driver, lag, change, ordinals=None):
    """Section 16 item 10: does the relationship hold in the weeks that ACTUALLY MISSED?

    A driver can track demand across ordinary weeks and say nothing about the weeks the forecast got
    wrong -- and those are the only weeks an RCA is about. Reported separately from the all-weeks
    figure so the two can disagree visibly rather than being averaged into one number.

    Restricted to weeks where |adherence| exceeds the engine's generation threshold. Reported as too
    thin below MIN_MISS_PAIRS rather than as an absence of relationship.
    """
    ordinals = ordinals or week_ordinals([wk for wk, _ in rows])
    missed = []
    for wk, row in rows:
        f = num(row.get("fcst_offered"))
        a = num(row.get("Actual_Offered"))
        if not f or a is None:
            continue
        if abs((1.0 - a / f) * 100.0) > MISS_THRESHOLD_PCT:
            missed.append((wk, row))
    if len(missed) < MIN_MISS_PAIRS:
        return {"testable": False, "miss_weeks": len(missed),
                "reason": ("only %d week(s) in this queue's history missed by more than %.0f%%; "
                           "%d are needed before the relationship can be measured on them alone"
                           % (len(missed), MISS_THRESHOLD_PCT, MIN_MISS_PAIRS))}
    xs, ys = _paired(missed, driver, lag, change, ordinals)
    if len(xs) < MIN_MISS_PAIRS:
        return {"testable": False, "miss_weeks": len(missed), "paired": len(xs),
                "reason": ("only %d paired observation(s) survive inside the miss weeks at this "
                           "lag" % len(xs))}
    rho = _spearman(xs, ys)
    if rho is None:
        return {"testable": False, "miss_weeks": len(missed), "paired": len(xs),
                "reason": "the driver does not vary across the miss weeks"}
    return {"testable": True, "miss_weeks": len(missed), "paired": len(xs),
            "relationship_strength": _rnd(rho),
            "direction": "positive" if rho >= 0 else "negative",
            "strong_enough": abs(rho) >= MIN_STRENGTH,
            "lag_weeks": lag, "relationship_type": _kind(lag, change)}


def _candidate(rows, driver, lag, change, ordinals=None):
    """One (driver, lag, family) estimate, or None when there is not enough paired data."""
    xs, ys = _paired(rows, driver, lag, change, ordinals)
    if len(xs) < MIN_PAIRS:
        return {"lag_weeks": lag, "relationship_type": _kind(lag, change), "weeks": len(xs),
                "relationship_strength": None, "testable": False,
                "reason": f"only {len(xs)} paired observations at this lag "
                          f"({MIN_PAIRS} required)"}
    rho = _spearman(xs, ys)
    if rho is None:
        return {"lag_weeks": lag, "relationship_type": _kind(lag, change), "weeks": len(xs),
                "relationship_strength": None, "testable": False,
                "reason": "the driver does not vary over this window, so no relationship "
                          "can be measured"}
    label, first, second = _stability(xs, ys)
    # Section 16 asks for both measures. `relationship_strength` remains SPEARMAN, so nothing that
    # reads it -- strong_enough, _best, usable_as_evidence -- can move. Pearson rides beside it.
    r_lin = _pearson(xs, ys)
    gap = (abs(rho - r_lin) if r_lin is not None else None)
    return {"lag_weeks": lag, "relationship_type": _kind(lag, change), "weeks": len(xs),
            "relationship_strength": _rnd(rho), "testable": True,
            "direction": "positive" if rho >= 0 else "negative",
            "stability": label, "first_half_strength": first, "second_half_strength": second,
            "strong_enough": abs(rho) >= MIN_STRENGTH,
            "rank_strength": _rnd(rho),
            "linear_strength": _rnd(r_lin) if r_lin is not None else None,
            "rank_vs_linear_gap": _rnd(gap) if gap is not None else None,
            # A large gap means the ranks and the linear fit disagree: the relationship is not
            # proportional, so a coefficient should not be read as "x% more driver, y% more demand".
            "proportional": (None if gap is None else bool(gap <= RANK_LINEAR_TOLERANCE))}


def _kind(lag, change):
    family = "change" if change else "level"
    return f"{'same_week' if lag == 0 else 'lagged'}_{family}"


def _coverage(rows, driver):
    """How much usable history this driver actually has -- the spec section 12 distinction.

    Returns (class, weeks_with_value, weeks_total). `absent` means the column never carries a
    number for this queue; `sparse` means it does but too rarely to measure anything.
    """
    total = len(rows)
    present = sum(1 for _, row in rows if _num(row.get(driver)) is not None)
    if present == 0:
        return "absent", present, total
    if present < MIN_PAIRS:
        return "sparse", present, total
    return "populated", present, total


def _interpret(driver, best, coverage_class, present, total):
    """Plain business English. No coefficients, no jargon -- those live in the technical block.

    Every branch here is a statement the data actually supports. The wording for the negative
    cases is deliberately "not established" rather than "no relationship" (spec section 11): a
    weak measured relationship is not proof of no relationship.
    """
    subject = DRIVER_SUBJECTS.get(driver, driver)
    if coverage_class == "absent":
        return (f"{driver} ({subject}) carries no values for this queue, so its relationship "
                f"with demand cannot be tested.")
    if coverage_class == "sparse":
        return (f"{driver} ({subject}) exists, but only {present} of {total} history weeks carry "
                f"a value -- too few to establish any relationship with demand. Treat it as "
                f"untested, not as unrelated.")
    if best is None:
        return (f"No lag from 0 to {max(LAGS)} weeks had enough paired data to test "
                f"{driver} ({subject}) against demand.")
    if not best.get("strong_enough"):
        return (f"The historical relationship between {subject} and demand was not strong enough "
                f"at any tested lag to use as evidence for this miss (strongest at "
                f"{best['lag_weeks']} week(s)). This does not mean the driver is irrelevant -- "
                f"it means this queue's own history does not establish it.")
    if best.get("stability") == STABILITY_SIGN_FLIP:
        return (f"{subject.capitalize()} appears related to demand at {best['lag_weeks']} week(s), "
                f"but the relationship reverses direction between the earlier and later halves of "
                f"the history, so it is not dependable enough to use as evidence.")
    direction = "higher" if best.get("direction") == "positive" else "lower"
    if best["lag_weeks"] == 0:
        when = "in the same week"
    else:
        when = f"{best['lag_weeks']} week(s) earlier"
    family = ("A RISE in " if "change" in best["relationship_type"] else "A higher level of ")
    return (f"{family}{subject} {when} is associated with {direction} contact demand "
            f"({best['stability']} across the history tested).")


def _best(candidates):
    """The most useful estimate among the tested lags.

    Ordering rules, in priority order:
      1. testable before untestable,
      2. strong-and-not-unstable before anything else,
      3. stronger |rho| first,
      4. shorter lag first -- a shorter lead is easier to act on and less likely to be spurious,
      5. change family before level family at equal strength, because a change relationship is
         the one a forecaster could actually have reacted to.
    """
    testable = [c for c in candidates if c.get("testable")]
    if not testable:
        return None

    def key(c):
        usable = c.get("strong_enough") and c.get("stability") != STABILITY_SIGN_FLIP
        return (0 if usable else 1,
                -abs(c.get("relationship_strength") or 0.0),
                c.get("lag_weeks", 99),
                0 if "change" in c.get("relationship_type", "") else 1)

    return sorted(testable, key=key)[0]


def analyse(history, target_week=None):
    """Lagged relationship analysis for every driver present in this queue's history.

    `history` is the raw SQL history block (wfm_context["history_104"]) -- the same rows
    `correlation_engine` and `statistical_evidence` consume. `target_week` is excluded from all
    estimates.

    Returns a block whose top level answers the only question that matters for an RCA:
    which driver, if any, gives this queue a usable LEADING signal, and at what lag.
    """
    rows = _series(history, target_week)
    if not rows:
        return {"available": False, "reason": "no usable history rows before the target week",
                "lags_tested": list(LAGS), "drivers": []}

    drivers = discover_drivers(rows)
    if not drivers:
        return {"available": False, "reason": "no driver columns present in the history",
                "lags_tested": list(LAGS), "drivers": []}

    ordinals = week_ordinals([wk for wk, _ in rows])
    out = []
    for driver in drivers:
        coverage_class, present, total = _coverage(rows, driver)
        entry = {
            "driver": driver,
            "subject": DRIVER_SUBJECTS.get(driver, driver),
            "coverage": coverage_class,
            "weeks_with_a_value": present,
            "weeks_in_window": total,
        }
        if coverage_class in ("absent", "sparse"):
            # Explicitly NOT tested. The distinction between "we tested and found nothing" and
            # "we could not test" is the whole point of spec section 12.
            entry.update({"tested": False, "best": None, "candidates": [],
                          "usable_as_evidence": False,
                          "interpretation": _interpret(driver, None, coverage_class,
                                                       present, total)})
            out.append(entry)
            continue

        candidates = []
        for lag in LAGS:
            for change in (False, True):
                candidates.append(_candidate(rows, driver, lag, change, ordinals))
        best = _best(candidates)
        # Section 16 item 10, measured at the SAME lag and family as the strongest all-weeks
        # candidate, so the two figures are comparable rather than measuring different things.
        _ref = best or max(
            (c for c in candidates
             if c.get("testable") and isinstance(c.get("relationship_strength"), (int, float))),
            key=lambda c: abs(c["relationship_strength"]), default=None)
        during_miss = (_miss_week_relationship(
            rows, driver, _ref.get("lag_weeks") or 0,
            str(_ref.get("relationship_type") or "").endswith("change"), ordinals)
            if _ref else {"testable": False,
                          "reason": "no measurable all-weeks relationship to compare against"})
        entry.update({
            "tested": True,
            "candidates": candidates,
            "best": best,
            "during_miss_weeks": during_miss,
            "usable_as_evidence": bool(best and best.get("strong_enough")
                                       and best.get("stability") != STABILITY_SIGN_FLIP),
            "interpretation": _interpret(driver, best, coverage_class, present, total),
        })
        if best:
            entry["best_lag_weeks"] = best.get("lag_weeks")
            entry["relationship_strength"] = best.get("relationship_strength")
            entry["relationship_type"] = best.get("relationship_type")
            entry["stability"] = best.get("stability")
            entry["direction"] = best.get("direction")
            entry["weeks"] = best.get("weeks")
        out.append(entry)

    usable = [d for d in out if d.get("usable_as_evidence")]
    usable.sort(key=lambda d: -abs(d.get("relationship_strength") or 0.0))
    return {
        "available": True,
        "lags_tested": list(LAGS),
        "min_paired_observations": MIN_PAIRS,
        "min_strength": MIN_STRENGTH,
        "weeks_in_window": len(rows),
        "target_week_excluded": target_week,
        "drivers": out,
        "leading_drivers": [d["driver"] for d in usable
                            if (d.get("best_lag_weeks") or 0) > 0],
        "usable_drivers": [d["driver"] for d in usable],
        "strongest": (usable[0]["driver"] if usable else None),
        "note": ("Relationships are measured on this queue's own history, excluding the week "
                 "under investigation. A driver that is not retained is reported as untested or "
                 "not established -- never as unrelated to demand."),
    }
