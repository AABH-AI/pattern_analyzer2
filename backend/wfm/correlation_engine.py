"""Correlation engine -- relationships that are allowed to be used as evidence.

Three independent things live here:

1. RELATIONSHIP STRENGTH (`relationships`)
   Which drivers genuinely track this queue's demand.

2. DRIVER DECOMPOSITION (`driver_decomposition`)
   An exact algebraic split of the miss when both ASU columns are present.

3. THIS-WEEK ATTRIBUTION (`this_week_attribution`)
   Whether any surviving driver actually moved THIS week, in the direction that
   would explain THIS miss.


WHY THIS MODULE WAS REWRITTEN -- CO-DRIFT IS NOT CO-MOVEMENT
------------------------------------------------------------
The first version ranked each driver against demand on RAW LEVELS across ~104
weeks. That measures whether two series drifted the same way over two years, not
whether one moves the other. Almost every queue here is in a multi-year decline,
and the warranty base is declining alongside it, so nearly everything correlated
with nearly everything.

Audited against the live table (427 queues, 310 relationships retained by the old
rule): 282 of them -- 91% -- collapse to essentially zero once the shared time
trend is removed. Worst case, CHK Premium Support: units-under-warranty vs demand
scored +0.94 on levels and +0.03 on week-to-week movement. The engine was telling
business leads "when units under warranty went up, demand almost always went up
too" on the strength of two lines that merely sloped the same way.

Significance testing does NOT catch this. With n>100 those spurious relationships
are all highly significant -- they are real correlations that mean nothing causally.
The fix is to test the right quantity, not to test the same quantity harder.

So a driver now has to clear four gates before it may be cited:

  1. CO-MOVEMENT   Rank correlation on WEEK-OVER-WEEK CHANGES, not levels. This is
                   the gate the old rule was missing and the one that removes shared
                   drift. A relationship that only exists on levels is reported as
                   rejected, with the two numbers side by side so the difference is
                   visible rather than hidden.
  2. SIGNIFICANCE  The co-movement figure must be distinguishable from noise at this
                   queue's own week count.
  3. STABILITY     It must hold with the same sign in BOTH halves of the history. A
                   relationship that appears in one half and not the other is not
                   something to plan against.
  4. AGREEMENT     In the weeks the driver actually moved, demand must have moved the
                   same way clearly more often than a coin toss.

`agreement_pct` is deliberately the headline number in the business text. "They moved
together in 71% of the 84 weeks where the driver moved" is something a lead can check
by hand; a correlation coefficient is not.

Holidays are NOT rank-correlated -- the column is a small-integer count that is 0 most
weeks, so a rank correlation over it is mostly ties and unstable. It gets a direct group
contrast instead: average demand in holiday weeks vs normal weeks, in real contacts.

FINALLY, AND MOST IMPORTANTLY: a relationship that holds across history still does not
explain a specific week. `this_week_attribution` closes that gap -- a driver is only
offered as evidence for THIS miss if it also moved THIS week, by a material amount, in
the direction that would push demand the way the miss went. A driver that sat at its
usual value explains nothing about this week no matter how strong its history is, and is
reported as such so the model cannot reach for it.

NOTE ON LANGUAGE: the prompt forbids "correlation" and friends in business-facing text.
Every entry carries a jargon-free `plain_language` string; coefficients stay under
`co_movement_strength` / `drift_only_strength` for the collapsed technical section.
"""
from .common import mean, median, num, rnd

# --- Gates -------------------------------------------------------------------
_MIN_WEEKS = 12          # too little history to judge anything
_MIN_MOVING_WEEKS = 10   # weeks in which the driver actually moved
_MIN_AGREEMENT = 60.0    # % of moving weeks where demand moved the same way
_MAX_LAG = 6             # weeks a driver may lead demand by

# A driver only counts as "moved this week" past this much of a shift vs its usual.
_MATERIAL_MOVE_PCT = 10.0

# Drivers that can plausibly LEAD demand (a unit shipped generates contacts later),
# so a lag scan is causally sensible. Others are tested contemporaneously only.
_LAGGABLE = ("Actual_ASU", "Planned_ASU", "Final_Units")

_DRIVERS = (
    ("Actual_ASU", "the number of units under warranty"),
    ("Planned_ASU", "the planned number of units under warranty"),
    ("Final_Units", "the installed base"),
)


# --- Statistics --------------------------------------------------------------
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


def _r_critical(n, strict=False):
    """Smallest |r| distinguishable from zero at n observations.

    From the t-approximation t = r*sqrt((n-2)/(1-r^2)), inverted. `strict` uses the
    1% level, applied when a lag was scanned -- searching several lags and keeping the
    best inflates the chance of a fluke, so the survivor must clear a higher bar.
    """
    df = n - 2
    if df < 1:
        return 1.0
    t = (2.576 + 5.0 / df) if strict else (1.96 + 2.4 / df)
    return t / ((df + t * t) ** 0.5)


def _deltas(xs, ys):
    """Week-over-week changes for pairs where both weeks have both values."""
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    dx = [pairs[i][0] - pairs[i - 1][0] for i in range(1, len(pairs))]
    dy = [pairs[i][1] - pairs[i - 1][1] for i in range(1, len(pairs))]
    return dx, dy


def _agreement(dx, dy):
    """Of the weeks the driver moved, how often did demand move the same way?

    The number a business lead can verify by eye, unlike a coefficient.
    """
    moving = [(a, b) for a, b in zip(dx, dy) if a != 0 and b != 0]
    if len(moving) < _MIN_MOVING_WEEKS:
        return None, len(moving)
    same = sum(1 for a, b in moving if (a > 0) == (b > 0))
    return round(same / len(moving) * 100.0, 0), len(moving)


def _stable(dx, dy):
    """Does the relationship hold with the same sign in both halves of the history?"""
    if len(dx) < 2 * _MIN_WEEKS:
        return None
    h = len(dx) // 2
    r1, _ = _spearman(dx[:h], dy[:h])
    r2, _ = _spearman(dx[h:], dy[h:])
    if r1 is None or r2 is None:
        return None
    return (r1 > 0) == (r2 > 0) and abs(r1) > 0.15 and abs(r2) > 0.15


def _best_lag(series, demand, laggable):
    """Best lag (driver leads demand by k weeks) on CHANGES. Returns (lag, r, n)."""
    best = (0, None, 0)
    lags = range(0, _MAX_LAG + 1) if laggable else (0,)
    for k in lags:
        if k:
            s, d = series[:-k], demand[k:]
        else:
            s, d = series, demand
        dx, dy = _deltas(s, d)
        if len(dx) < _MIN_WEEKS:
            continue
        r, n = _spearman(dx, dy)
        if r is None:
            continue
        if best[1] is None or abs(r) > abs(best[1]):
            best = (k, r, n)
    return best


# --- Plain language ----------------------------------------------------------
def _strength_word(agreement_pct):
    """Honest qualifier. 60% agreement beats a coin toss but is not "usually"."""
    if agreement_pct >= 80:
        return "a strong and dependable pattern"
    if agreement_pct >= 70:
        return "a clear pattern"
    if agreement_pct >= 65:
        return "a modest but consistent pattern"
    return "a weak pattern -- better than chance, but only just"


def _describe(subject, agreement_pct, moving_weeks, lag, direction):
    when = "in the same week" if not lag else (
        f"about {lag} week{'s' if lag > 1 else ''} later")
    way = "the same way" if direction == "same" else "the opposite way"
    return (f"In the {moving_weeks} weeks where {subject} moved, this queue's demand moved "
            f"{way} {when} in {agreement_pct:.0f}% of them -- {_strength_word(agreement_pct)}.")


def _reject_drift(subject, weeks, agreement_pct, failed_gate):
    """Say which test the driver failed, not a generic dismissal."""
    if failed_gate == "significance":
        detail = ("week to week their movements are too close to random to tell apart from "
                  "chance")
    elif failed_gate == "agreement":
        detail = (f"week to week they moved the same way only {agreement_pct:.0f}% of the time, "
                  f"barely different from a coin toss")
    else:
        detail = "week to week they do not move together"
    return (f"Across {weeks} weeks {subject} and demand both drifted in the same overall "
            f"direction, but {detail}. That is two figures sloping the same way over a long "
            f"period, not one driving the other, so it is not used as evidence.")


# --- Holidays ----------------------------------------------------------------
def _holiday_effect(history):
    """Group contrast, not a rank correlation -- the column is 0 in most weeks."""
    hol, normal = [], []
    for h in history or []:
        d = num(h.get("Actual_Offered"))
        c = num(h.get("Holiday_Count"))
        if d is None or c is None:
            continue
        (hol if c > 0 else normal).append(d)
    if len(hol) < 3 or len(normal) < 3:
        return {"driver": "Holiday_Count", "subject": "holidays in the week",
                "available": False,
                "reason": (f"Only {len(hol)} holiday weeks and {len(normal)} normal weeks in "
                           f"this queue's history -- too few to measure a holiday effect.")}
    mh, mn = mean(hol), mean(normal)
    if not mn:
        return {"driver": "Holiday_Count", "subject": "holidays in the week",
                "available": False, "reason": "No normal-week demand to compare against."}
    diff_pct = (mh - mn) / mn * 100.0
    material = abs(diff_pct) >= 5.0
    return {
        "driver": "Holiday_Count",
        "subject": "holidays in the week",
        "available": True,
        "material": material,
        "holiday_weeks": len(hol),
        "normal_weeks": len(normal),
        "avg_demand_holiday_weeks": rnd(mh),
        "avg_demand_normal_weeks": rnd(mn),
        "difference_pct": rnd(diff_pct),
        "evidence_weight": ("strong" if abs(diff_pct) >= 15 else
                            "moderate" if abs(diff_pct) >= 8 else "weak"),
        "plain_language": (
            f"Weeks containing a holiday average {rnd(mh)} contacts against {rnd(mn)} in normal "
            f"weeks -- {abs(rnd(diff_pct))}% "
            f"{'lower' if diff_pct < 0 else 'higher'}."
            if material else
            f"Holiday weeks average {rnd(mh)} contacts against {rnd(mn)} in normal weeks, a "
            f"difference of only {abs(rnd(diff_pct))}% -- holidays do not materially move this queue."),
    }


# --- Relationships -----------------------------------------------------------
def relationships(history_104):
    """Which drivers actually move this queue's demand, on its own history."""
    hist = history_104 or []
    demand = [num(h.get("Actual_Offered")) for h in hist]

    retained, rejected = [], []
    for field, subject in _DRIVERS:
        series = [num(h.get(field)) for h in hist]

        levels_r, n_levels = _spearman(series, demand)
        lag, change_r, n_ch = _best_lag(series, demand, field in _LAGGABLE)

        base = {"driver": field, "subject": subject, "weeks": n_levels,
                "drift_only_strength": (round(levels_r, 2) if levels_r is not None else None),
                "co_movement_strength": (round(change_r, 2) if change_r is not None else None),
                "lag_weeks": lag}

        if change_r is None or n_ch < _MIN_WEEKS:
            base["reason"] = ("Not enough usable weeks in this queue's history to judge whether "
                              "this moves demand.")
            rejected.append(base)
            continue

        if lag:
            s, d = series[:-lag], demand[lag:]
        else:
            s, d = series, demand
        dx, dy = _deltas(s, d)
        agreement_pct, moving_weeks = _agreement(dx, dy)
        stable = _stable(dx, dy)

        base["agreement_pct"] = agreement_pct
        base["weeks_driver_moved"] = moving_weeks
        base["stable_across_history"] = stable
        base["direction"] = "same" if change_r > 0 else "opposite"
        # Kept for the collapsed technical section and for backwards compatibility with
        # callers that read `technical_strength` -- now the co-movement figure, which is
        # the one the retain/reject decision is actually made on.
        base["technical_strength"] = round(change_r, 2)

        if abs(change_r) < _r_critical(n_ch, strict=bool(lag)):
            base["reason"] = _reject_drift(subject, n_levels, agreement_pct, "significance")
            rejected.append(base)
            continue
        if agreement_pct is None:
            base["reason"] = (f"{subject.capitalize()} barely moves in this queue's history, so "
                              f"there is nothing to judge a relationship against.")
            rejected.append(base)
            continue
        if agreement_pct < _MIN_AGREEMENT:
            base["reason"] = _reject_drift(subject, n_levels, agreement_pct, "agreement")
            rejected.append(base)
            continue
        if stable is False:
            base["reason"] = (f"The link between {subject} and demand holds in one half of this "
                              f"queue's history but reverses in the other, so it is not "
                              f"dependable enough to plan against.")
            rejected.append(base)
            continue

        base["plain_language"] = _describe(subject, agreement_pct, moving_weeks, lag,
                                           base["direction"])
        base["evidence_weight"] = ("strong" if agreement_pct >= 75 else
                                   "moderate" if agreement_pct >= 65 else "weak")
        retained.append(base)

    retained.sort(key=lambda e: abs(e.get("co_movement_strength") or 0), reverse=True)

    hol = _holiday_effect(hist)
    if hol.get("available") and hol.get("material"):
        retained.append(hol)
    else:
        rejected.append(hol if not hol.get("available") else
                        {**hol, "reason": hol.get("plain_language")})

    return {
        "available": bool(retained or rejected),
        "method": ("Drivers are judged on week-to-week MOVEMENT, not on whether they drifted the "
                   "same way over the whole period. Two figures that both decline for two years "
                   "will track each other closely without one causing the other; that pattern is "
                   "rejected here and listed with both numbers so the difference is visible."),
        "min_weeks_required": _MIN_WEEKS,
        "min_agreement_pct_required": _MIN_AGREEMENT,
        "retained": retained,
        "rejected": rejected,
        "note": ("Only relationships that survive week-to-week testing are retained. Everything in "
                 "`rejected` must NOT be used as evidence, including entries with a high "
                 "`drift_only_strength` -- that figure is precisely the trap."),
    }


# --- This week ---------------------------------------------------------------
def this_week_attribution(history_104, target_fields, retained):
    """Did any surviving driver actually move THIS week, the way the miss went?

    A relationship that holds across history still explains nothing about a specific
    week unless the driver moved in that week. This is the step that separates a
    standing relationship from evidence for this miss.
    """
    fields = target_fields or {}
    actual = num(fields.get("Actual_Offered"))
    fcst = num(fields.get("fcst_offered"))
    if actual is None or fcst is None:
        return {"available": False,
                "reason": "This week's actual or forecast is missing, so nothing can be attributed."}

    # Which way did demand miss? Below forecast = "down".
    miss_dir = "down" if actual < fcst else "up"
    miss_size = abs(actual - fcst)

    explains, does_not = [], []
    for rel in retained or []:
        field = rel.get("driver")
        subject = rel.get("subject")
        if field == "Holiday_Count":
            hc = num(fields.get("Holiday_Count")) or 0
            if hc > 0:
                explains.append({
                    "driver": field, "subject": subject,
                    "this_week_value": hc,
                    "plain_language": (f"This week contained {int(hc)} holiday, and holiday weeks "
                                       f"run {abs(rel.get('difference_pct', 0))}% "
                                       f"{'below' if (rel.get('difference_pct') or 0) < 0 else 'above'} "
                                       f"normal for this queue.")})
            else:
                does_not.append({
                    "driver": field, "subject": subject, "this_week_value": 0,
                    "plain_language": ("There was no holiday this week, so the holiday pattern does "
                                       "not explain this miss.")})
            continue

        this_val = num(fields.get(field))
        hist_vals = [num(h.get(field)) for h in (history_104 or [])]
        hist_vals = [v for v in hist_vals[-13:] if v is not None]
        usual = median(hist_vals) if hist_vals else None
        if this_val is None or not usual:
            does_not.append({"driver": field, "subject": subject,
                             "plain_language": (f"There is no usable {subject} figure for this week, "
                                                f"so it cannot be tested against this miss.")})
            continue

        move_pct = (this_val - usual) / usual * 100.0
        if abs(move_pct) < _MATERIAL_MOVE_PCT:
            does_not.append({
                "driver": field, "subject": subject,
                "this_week_value": rnd(this_val), "usual_value": rnd(usual),
                "move_pct": rnd(move_pct),
                "plain_language": (f"{subject.capitalize()} was {rnd(this_val)} this week against a "
                                   f"usual {rnd(usual)} -- essentially unchanged, so it does not "
                                   f"explain this miss.")})
            continue

        # Which way would this move have pushed demand?
        pushed = "up" if ((move_pct > 0) == (rel.get("direction") == "same")) else "down"
        entry = {"driver": field, "subject": subject,
                 "this_week_value": rnd(this_val), "usual_value": rnd(usual),
                 "move_pct": rnd(move_pct), "would_push_demand": pushed,
                 "matches_miss_direction": pushed == miss_dir}
        if pushed == miss_dir:
            entry["plain_language"] = (
                f"{subject.capitalize()} came in at {rnd(this_val)} against a usual {rnd(usual)} "
                f"({'up' if move_pct > 0 else 'down'} {abs(rnd(move_pct))}%), which for this queue "
                f"pushes demand {pushed} -- the same direction as this week's miss.")
            explains.append(entry)
        else:
            entry["plain_language"] = (
                f"{subject.capitalize()} moved {'up' if move_pct > 0 else 'down'} "
                f"{abs(rnd(move_pct))}% this week, which for this queue pushes demand {pushed} -- "
                f"the OPPOSITE direction to this miss, so it does not explain it and argues "
                f"against it being the cause.")
            does_not.append(entry)

    return {
        "available": True,
        "miss_direction": miss_dir,
        "miss_size_contacts": rnd(miss_size),
        "explains_this_week": explains,
        "does_not_explain_this_week": does_not,
        "no_driver_explains_this_week": not explains,
        "plain_language": (
            "None of the measurable drivers moved this week in a way that would explain the miss, "
            "so the explanation lies in how the forecast itself was set rather than in a change in "
            "the underlying business."
            if not explains else
            "The drivers listed under explains_this_week both hold up historically for this queue "
            "and moved this week in the direction the miss went."),
    }


# --- Exact decomposition (unchanged -- this one is an identity, not an inference) ---
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
    rels = relationships(history_104)
    return {
        "relationships": rels,
        "driver_decomposition": driver_decomposition(target_fields or {}),
        "this_week_attribution": this_week_attribution(
            history_104, target_fields, rels.get("retained")),
    }
