# -*- coding: utf-8 -*-
"""
Queue-level statistical evidence -- the deterministic drill-down.

WHY THIS MODULE EXISTS
----------------------
`hierarchy_analyzer` finds the HIGHEST level that missed in the same direction and reports
`inherited_from`. Once that fires, the investigation concludes "the miss came from SubRegion" and the
queue's own behaviour is never characterised. That is early stopping: it says WHERE the miss was
visible, not WHY this queue behaves the way it does.

This module answers the queue-level question with arithmetic only -- no model, no LLM. Per the
business decision (2026-07-30) statistical evidence is the STRONGEST evidence available, so these
figures overrule the model where they conflict, exactly as the KPI, the channel-migration verdict and
the confidence bands already do. It ALWAYS runs, including when the miss is inherited, so the report
can say both "inherited from SubRegion" AND "this queue is chronically over-forecast with rising
drift and high volatility".

DEPENDENCIES: standard library only (`math`, `statistics`). The backend is deliberately
dependency-light -- no numpy, no scipy, no sklearn. Every formula here is written out so it can be
checked by hand against the source data.

WINDOWS
-------
Three nested windows, because a metric's meaning depends on how far back it looks:
    RECENT = 13 weeks   -- matches RCA_HISTORY_CAP, the "usual" the rest of the report quotes
    YEAR   = 52 weeks   -- one full seasonal cycle
    LONG   = 104 weeks  -- what data_access already fetches (history_104)
Every metric reports the window and the n it used. All 42 queues in the P1 extract carry 175 weeks,
so all three windows are populated; the code still degrades honestly when they are not.

A NOTE ON MAPE
--------------
MAPE divides by the actual, so it explodes when actuals approach zero. On this dataset the minimum
Actual_Offered is 28 and NO week falls below 10 contacts, so MAPE is safe here -- but it is still
reported alongside WAPE, which is volume-weighted and cannot blow up, and WAPE is the one used for
any verdict.
"""
import math
import statistics as _st

RECENT_WEEKS = 13
YEAR_WEEKS = 52
LONG_WEEKS = 104

# --- thresholds. Each one is a judgement call and is named so it can be challenged, not buried. ---
CV_VOLATILE = 0.30          # sigma/mu above this => the queue is genuinely hard to forecast
CV_STABLE = 0.15            # below this => stable demand, so a miss is the forecast's fault
BIAS_MATERIAL_PCT = 5.0     # mean signed error worth calling a bias, as % of mean actual
DRIFT_MATERIAL_PCT = 0.25   # adherence points per week; over ~13 weeks that is >3 points of drift
MOMENTUM_MATERIAL_PCT = 10.0
TREND_R2_MEANINGFUL = 0.30  # below this a slope is noise, not a trend
SEASONAL_INDEX_MATERIAL = 0.15   # +/-15% off the annual mean for this week-of-year
OUTLIER_MOD_Z = 3.5         # modified z-score (median/MAD based), the standard robust cutoff
MIN_N = 6                   # fewer points than this and we report "insufficient history", not a number


def _num(v):
    """Coerce to float, or None. Strings arrive from CSV/pyODBC alike."""
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


def _pairs(history):
    """(fiscal_week, forecast, actual) for rows where BOTH figures are usable, chronological.

    Rows missing either side are dropped rather than zero-filled: a zero forecast would invent a
    100% error, and a zero actual would make MAPE infinite.
    """
    out = []
    for row in history or []:
        wk = _num((row or {}).get("Fiscal_Week"))
        fc = _num((row or {}).get("fcst_offered"))
        ac = _num((row or {}).get("Actual_Offered"))
        if wk is None or fc is None or ac is None:
            continue
        if fc == 0 or ac <= 0:
            continue
        out.append((int(wk), fc, ac))
    out.sort(key=lambda t: t[0])
    return out


def _slope_intercept_r2(xs, ys):
    """Ordinary least squares by hand. Returns (slope, intercept, r_squared) or (None, None, None).

    Written out rather than pulled from a library so the numbers can be reproduced in a spreadsheet
    if a forecaster challenges them.
    """
    n = len(xs)
    if n < 2:
        return None, None, None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None, None, None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx
    intercept = my - slope * mx
    syy = sum((y - my) ** 2 for y in ys)
    r2 = (sxy ** 2) / (sxx * syy) if syy > 0 else None
    return slope, intercept, r2


def _pearson(xs, ys):
    """Pearson linear r. Spearman (rank) already exists in correlation_engine; this is the linear
    counterpart, reported next to it so a non-linear relationship is visible as a gap between them."""
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return sxy / math.sqrt(sxx * syy)


def _week_of_year(fiscal_week):
    """202719 -> 19. The fiscal year starts at week 1 of February (see FIELD_DEFINITIONS), so the
    trailing two digits ARE the week-of-fiscal-year and are directly comparable across years."""
    return int(fiscal_week) % 100


# ---------------------------------------------------------------------------
# the metrics
# ---------------------------------------------------------------------------
def _accuracy_block(rows, label):
    """Forecast Variance, MAE, MAPE, WAPE, RMSE and Bias over one window.

    Sign convention matches the rest of the system: error = actual - forecast, so a NEGATIVE bias
    means the forecast ran HIGH (over-forecast). This is the opposite sign to `adherence_pct`
    (which is (1 - actual/forecast) * 100), and the two are deliberately reported side by side so
    nobody has to infer the direction.
    """
    if len(rows) < MIN_N:
        return {"window": label, "n": len(rows), "available": False,
                "note": f"needs at least {MIN_N} comparable weeks; only {len(rows)} available"}
    errs = [ac - fc for _, fc, ac in rows]
    abs_errs = [abs(e) for e in errs]
    acts = [ac for _, _, ac in rows]
    sum_act = sum(acts)
    mean_act = sum_act / len(acts)

    mae = sum(abs_errs) / len(abs_errs)
    mape = sum(abs(e) / ac for e, (_, _, ac) in zip(errs, rows)) / len(errs) * 100.0
    wape = (sum(abs_errs) / sum_act * 100.0) if sum_act else None
    rmse = math.sqrt(sum(e * e for e in errs) / len(errs))
    bias = sum(errs) / len(errs)
    bias_pct = (bias / mean_act * 100.0) if mean_act else None
    variance = _st.variance(errs) if len(errs) > 1 else 0.0

    direction = "over-forecast" if bias < 0 else ("under-forecast" if bias > 0 else "balanced")
    material = bool(bias_pct is not None and abs(bias_pct) >= BIAS_MATERIAL_PCT)
    return {
        "window": label, "n": len(rows), "available": True,
        "forecast_variance": _rnd(variance),
        "forecast_error_std_dev": _rnd(math.sqrt(variance)),
        "mae": _rnd(mae),
        "mape_pct": _rnd(mape),
        "wape_pct": _rnd(wape),
        "rmse": _rnd(rmse),
        "bias": _rnd(bias),
        "bias_pct": _rnd(bias_pct),
        "bias_direction": direction,
        "bias_material": material,
        "mean_actual": _rnd(mean_act),
        "reading": (
            f"Over the last {len(rows)} weeks this queue's forecast was off by an average of "
            f"{mae:,.0f} contacts ({wape:.1f}% of the volume it handled). "
            + (f"It leans {direction}: on average {abs(bias):,.0f} contacts "
               f"({abs(bias_pct):.1f}% of typical volume) {'above' if bias > 0 else 'below'} plan."
               if material else
               f"There is no material standing lean either way (average {bias:+,.0f} contacts).")
        ),
    }


def _coefficient_of_variation(rows, label):
    """CoV = sigma / mu on ACTUAL demand. This is the single most useful number for deciding whether
    a miss is the forecaster's fault: a queue whose own demand swings 40% week to week cannot be
    forecast to +/-10%, and blaming the forecast there is wrong."""
    if len(rows) < MIN_N:
        return {"window": label, "n": len(rows), "available": False,
                "note": f"needs at least {MIN_N} weeks"}
    acts = [ac for _, _, ac in rows]
    mu = sum(acts) / len(acts)
    sd = _st.stdev(acts) if len(acts) > 1 else 0.0
    cv = (sd / mu) if mu else None
    if cv is None:
        cls, reading = "unknown", "Demand average is zero, so volatility cannot be scored."
    elif cv >= CV_VOLATILE:
        cls = "volatile"
        reading = (f"This queue's own demand is volatile: week-to-week swings average "
                   f"{cv * 100:.0f}% of its mean ({mu:,.0f} contacts). A queue this variable cannot "
                   f"be held to a tight forecast band, so part of any miss is inherent.")
    elif cv <= CV_STABLE:
        cls = "stable"
        reading = (f"This queue's demand is stable (variation {cv * 100:.0f}% of a "
                   f"{mu:,.0f}-contact mean). Because the demand itself is predictable, a large miss "
                   f"points at the forecast rather than at the customers.")
    else:
        cls = "moderate"
        reading = (f"This queue's demand varies moderately ({cv * 100:.0f}% of a {mu:,.0f}-contact "
                   f"mean).")
    return {"window": label, "n": len(rows), "available": True,
            "coefficient_of_variation": _rnd(cv, 4),
            "coefficient_of_variation_pct": _rnd(cv * 100 if cv is not None else None),
            "mean_actual": _rnd(mu), "std_dev_actual": _rnd(sd),
            "volatility_class": cls, "reading": reading}


def _trend_and_cor(rows, label):
    """Trend Analysis + Coefficient of Regression (CoR).

    CoR is the OLS slope: contacts gained or lost per week. Reported with r-squared, because a slope
    without a fit statistic is how a random walk gets reported as a trend.
    """
    if len(rows) < MIN_N:
        return {"window": label, "n": len(rows), "available": False,
                "note": f"needs at least {MIN_N} weeks"}
    xs = list(range(len(rows)))
    acts = [ac for _, _, ac in rows]
    slope, intercept, r2 = _slope_intercept_r2(xs, acts)
    mu = sum(acts) / len(acts)
    per_week_pct = (slope / mu * 100.0) if (slope is not None and mu) else None
    meaningful = bool(r2 is not None and r2 >= TREND_R2_MEANINGFUL)
    if slope is None:
        direction, reading = "flat", "Not enough spread in the weeks to fit a trend."
    else:
        direction = "rising" if slope > 0 else ("falling" if slope < 0 else "flat")
        if meaningful:
            reading = (f"Demand has been {direction} steadily over the last {len(rows)} weeks, by "
                       f"about {abs(slope):,.0f} contacts per week "
                       f"({abs(per_week_pct):.1f}% of the mean). Over {len(rows)} weeks that is a "
                       f"shift of roughly {abs(slope) * len(rows):,.0f} contacts, so a forecast "
                       f"built on the older level would now be systematically wrong.")
        else:
            reading = (f"No dependable trend: the week-to-week movement does not line up "
                       f"(fit {0 if r2 is None else r2:.2f}), so recent moves are noise rather than "
                       f"direction.")
    return {"window": label, "n": len(rows), "available": True,
            "coefficient_of_regression_per_week": _rnd(slope),
            "coefficient_of_regression_pct_per_week": _rnd(per_week_pct),
            "r_squared": _rnd(r2, 3), "direction": direction,
            "trend_meaningful": meaningful, "reading": reading}


def _drift(rows, label):
    """Drift = is the forecast ERROR itself moving? OLS slope of adherence over time.

    Distinct from Trend, which is the slope of demand. A queue can have flat demand and drifting
    adherence (the plan is decaying), or rising demand with zero drift (the plan is keeping up).
    Drift is the one that says "this will keep getting worse unless the baseline is rebuilt".
    """
    if len(rows) < MIN_N:
        return {"window": label, "n": len(rows), "available": False,
                "note": f"needs at least {MIN_N} weeks"}
    xs = list(range(len(rows)))
    adh = [(1.0 - ac / fc) * 100.0 for _, fc, ac in rows]
    slope, _, r2 = _slope_intercept_r2(xs, adh)
    material = bool(slope is not None and abs(slope) >= DRIFT_MATERIAL_PCT)
    if slope is None:
        direction, reading = "none", "Adherence drift cannot be fitted."
    else:
        direction = "worsening_over" if slope > 0 else ("worsening_under" if slope < 0 else "none")
        total = slope * len(rows)
        if material:
            side = "over-forecast" if slope > 0 else "under-forecast"
            reading = (f"The forecast error is drifting, not just noisy: adherence has moved about "
                       f"{slope:+.2f} points per week, roughly {total:+.0f} points across "
                       f"{len(rows)} weeks, steadily further into {side}. The baseline is decaying "
                       f"and will keep missing in this direction until it is rebuilt.")
        else:
            reading = (f"No material drift: adherence moves {slope:+.2f} points per week, so the "
                       f"error is not systematically growing in either direction.")
    return {"window": label, "n": len(rows), "available": True,
            "adherence_drift_pts_per_week": _rnd(slope, 3),
            "adherence_drift_total_pts": _rnd(slope * len(rows) if slope is not None else None),
            "r_squared": _rnd(r2, 3), "direction": direction,
            "drift_material": material, "reading": reading}


def _momentum(rows, recent=4, prior=8):
    """Momentum = short-run persistence. Mean of the last `recent` weeks vs the `prior` weeks before.

    Answers "was the queue already moving before the week we are explaining?". A miss on a queue that
    had been climbing for a month is a forecast that failed to follow a visible move -- a different
    finding from a miss that arrived out of nowhere.
    """
    need = recent + prior
    if len(rows) < need:
        return {"available": False, "n": len(rows),
                "note": f"needs {need} weeks ({recent} recent + {prior} prior); have {len(rows)}"}
    acts = [ac for _, _, ac in rows]
    r_mean = sum(acts[-recent:]) / recent
    p_mean = sum(acts[-need:-recent]) / prior
    change_pct = ((r_mean - p_mean) / p_mean * 100.0) if p_mean else None
    material = bool(change_pct is not None and abs(change_pct) >= MOMENTUM_MATERIAL_PCT)
    direction = ("accelerating" if (change_pct or 0) > 0 else
                 "decelerating" if (change_pct or 0) < 0 else "flat")
    reading = (
        f"Demand was already {direction} before this week: the last {recent} weeks averaged "
        f"{r_mean:,.0f} contacts against {p_mean:,.0f} in the {prior} weeks before "
        f"({change_pct:+.1f}%). A forecast still set to the older level was going to miss."
        if material else
        f"No build-up going in: the last {recent} weeks ({r_mean:,.0f}) sit close to the previous "
        f"{prior} ({p_mean:,.0f}, {0 if change_pct is None else change_pct:+.1f}%)."
    )
    return {"available": True, "recent_weeks": recent, "prior_weeks": prior,
            "recent_mean_actual": _rnd(r_mean), "prior_mean_actual": _rnd(p_mean),
            "change_pct": _rnd(change_pct), "direction": direction,
            "momentum_material": material, "reading": reading}


def _seasonality(rows, target_week):
    """Seasonality index for the target week-of-fiscal-year.

    index = mean actual for THIS week-of-year (other years) / mean actual across all weeks.
    Requires the same week-of-year to appear in at least 2 other years, otherwise it is one
    observation and not a seasonal pattern.
    """
    if not rows or target_week is None:
        return {"available": False, "note": "no history or no target week"}
    wk = _week_of_year(target_week)
    acts = [ac for _, _, ac in rows]
    overall = sum(acts) / len(acts)
    same = [ac for w, _, ac in rows if _week_of_year(w) == wk and int(w) != int(target_week)]
    if len(same) < 2 or not overall:
        return {"available": False, "week_of_fiscal_year": wk, "prior_years_found": len(same),
                "note": (f"week {wk} appears in only {len(same)} earlier year(s); a seasonal index "
                         f"needs at least 2 for the pattern to be real")}
    idx = (sum(same) / len(same)) / overall
    material = abs(idx - 1.0) >= SEASONAL_INDEX_MATERIAL
    if material:
        hi = idx > 1.0
        reading = (f"Fiscal week {wk} is normally a {'busy' if hi else 'quiet'} week for this queue: "
                   f"across {len(same)} earlier years it averaged {sum(same) / len(same):,.0f} "
                   f"contacts against a typical {overall:,.0f} -- about "
                   f"{abs(idx - 1) * 100:.0f}% {'above' if hi else 'below'} normal. A forecast that "
                   f"ignores this recurring pattern will miss this week every year.")
    else:
        reading = (f"Fiscal week {wk} carries no special seasonal pattern for this queue "
                   f"(index {idx:.2f} across {len(same)} earlier years).")
    return {"available": True, "week_of_fiscal_year": wk, "prior_years_found": len(same),
            "seasonal_index": _rnd(idx, 3), "seasonal_material": material,
            "same_week_mean_actual": _rnd(sum(same) / len(same)),
            "overall_mean_actual": _rnd(overall), "reading": reading}


def _outliers(rows, target_week):
    """Robust outlier detection over the long window, on ACTUAL demand.

    Median + MAD rather than mean + standard deviation: with a mean/sd rule a single huge spike
    inflates the sd and then hides itself. Cutoff is the conventional modified-z of 3.5.
    """
    if len(rows) < MIN_N:
        return {"available": False, "n": len(rows), "note": f"needs at least {MIN_N} weeks"}
    acts = [ac for _, _, ac in rows]
    med = _st.median(acts)
    mad = _st.median([abs(a - med) for a in acts])
    if mad == 0:
        return {"available": False, "n": len(rows),
                "note": "demand is essentially constant, so no outlier scale exists"}
    scored = []
    for w, _, ac in rows:
        mz = 0.6745 * (ac - med) / mad          # 0.6745 rescales MAD to a sd-equivalent
        if abs(mz) >= OUTLIER_MOD_Z:
            scored.append({"fiscal_week": w, "actual": _rnd(ac), "modified_z": _rnd(mz, 2),
                           "direction": "spike" if mz > 0 else "dip"})
    tgt = next((s for s in scored if target_week is not None and int(s["fiscal_week"]) == int(target_week)), None)
    reading = (
        (f"This week is itself a statistical outlier for this queue: {tgt['actual']:,.0f} contacts "
         f"against a typical {med:,.0f} -- a genuine {tgt['direction']}, not a rounding issue."
         if tgt else
         f"This week is not an outlier for this queue (typical level {med:,.0f} contacts).")
        + (f" {len(scored)} of {len(rows)} weeks in the window are outliers."
           if scored else f" No outlier weeks in the last {len(rows)}.")
    )
    return {"available": True, "n": len(rows), "median_actual": _rnd(med), "mad": _rnd(mad),
            "outlier_weeks": scored[-8:], "outlier_count": len(scored),
            "target_week_is_outlier": bool(tgt), "target_week_detail": tgt, "reading": reading}


def _correlations(history, target_week):
    """Pearson r between demand and each candidate driver, over the long window.

    correlation_engine already computes SPEARMAN (rank). Pearson is added here because the pair is
    diagnostic: a strong Spearman with a weak Pearson means the relationship is real but not linear,
    which is exactly the case a linear forecast model handles badly.
    """
    drivers = (("Actual_ASU", "actual units under warranty"),
               ("Planned_ASU", "planned units under warranty"),
               ("Final_Units", "planned units for delivery (shipment)"),
               ("Holiday_Count", "holidays in the week"))
    out = []
    for field, label in drivers:
        xs, ys = [], []
        for row in history or []:
            d = _num((row or {}).get(field))
            a = _num((row or {}).get("Actual_Offered"))
            if d is None or a is None:
                continue
            xs.append(d)
            ys.append(a)
        if len(xs) < MIN_N:
            continue
        r = _pearson(xs, ys)
        if r is None:
            continue
        strength = ("strong" if abs(r) >= 0.6 else "moderate" if abs(r) >= 0.3 else "weak")
        out.append({"field": field, "subject": label, "pearson_r": _rnd(r, 3), "n": len(xs),
                    "strength": strength,
                    "direction": "moves together" if r > 0 else "moves opposite",
                    "reading": (f"Demand and {label} show a {strength} "
                                f"{'positive' if r > 0 else 'negative'} relationship "
                                f"(r={r:+.2f} over {len(xs)} weeks).")})
    out.sort(key=lambda d: abs(d["pearson_r"]), reverse=True)
    return out


# ---------------------------------------------------------------------------
# the verdict -- what overrules the model
# ---------------------------------------------------------------------------
def _verdict(blocks, target_adherence, band):
    """Pick the strongest statistical finding and express it as a cause.

    Ordered deliberately, strongest explanation first. Each branch requires a measured precondition,
    so this can only fire when the arithmetic supports it -- it never guesses.
    """
    cv = blocks.get("coefficient_of_variation_long") or {}
    drift = blocks.get("drift_recent") or {}
    acc_recent = blocks.get("accuracy_recent") or {}
    trend = blocks.get("trend_recent") or {}
    mom = blocks.get("momentum") or {}
    seas = blocks.get("seasonality") or {}
    out_b = blocks.get("outliers") or {}

    findings = []

    if out_b.get("target_week_is_outlier"):
        findings.append({
            "cause_type": "genuine_demand_event", "rank_basis": "outlier_detection",
            "confidence_pct": 80,
            "title": "Genuine demand outlier in this week",
            "statement": out_b.get("reading"),
            "metric": "Outlier Detection (modified z on 104 weeks)"})

    if seas.get("seasonal_material"):
        findings.append({
            "cause_type": "calendar_seasonality", "rank_basis": "seasonality",
            "confidence_pct": 75,
            "title": f"Recurring seasonal pattern in fiscal week {seas.get('week_of_fiscal_year')}",
            "statement": seas.get("reading"),
            "metric": "Seasonality index (week-of-fiscal-year)"})

    if drift.get("drift_material"):
        findings.append({
            "cause_type": "systematic_forecast_bias", "rank_basis": "drift",
            "confidence_pct": 78,
            "title": "Forecast baseline is drifting, not just missing",
            "statement": drift.get("reading"),
            "metric": "Drift (OLS slope of adherence)"})

    if trend.get("trend_meaningful") and mom.get("momentum_material"):
        findings.append({
            "cause_type": "forecast_baseline_error", "rank_basis": "trend+momentum",
            "confidence_pct": 72,
            "title": "Demand was already moving and the plan did not follow",
            "statement": (trend.get("reading") or "") + " " + (mom.get("reading") or ""),
            "metric": "Trend Analysis + Momentum"})

    if acc_recent.get("bias_material"):
        findings.append({
            "cause_type": "systematic_forecast_bias", "rank_basis": "bias",
            "confidence_pct": 70,
            "title": f"Standing {acc_recent.get('bias_direction')} bias on this queue",
            "statement": acc_recent.get("reading"),
            "metric": "Bias / MAE / WAPE"})

    if cv.get("volatility_class") == "volatile":
        findings.append({
            "cause_type": "inherent_demand_volatility", "rank_basis": "coefficient_of_variation",
            "confidence_pct": 65,
            "title": "Queue demand is inherently volatile",
            "statement": cv.get("reading"),
            "metric": "Coefficient of Variation"})
    elif cv.get("volatility_class") == "stable" and isinstance(target_adherence, (int, float)) \
            and abs(target_adherence) > (band or 10):
        findings.append({
            "cause_type": "forecast_baseline_error", "rank_basis": "coefficient_of_variation",
            "confidence_pct": 68,
            "title": "Stable demand, so the miss sits with the forecast",
            "statement": cv.get("reading"),
            "metric": "Coefficient of Variation"})

    findings.sort(key=lambda f: f["confidence_pct"], reverse=True)
    return findings


def statistical_evidence(history_104, target_week, target_adherence=None, band=10):
    """The public entry point. `history_104` is the raw row list from data_access.fetch_wfm_context.

    Returns every metric, each with the window and n it used, plus a ranked list of statistical
    findings. Never raises on thin data -- individual blocks report available: False with the reason,
    so the report can say what it could not compute instead of quietly showing nothing.
    """
    every = _pairs(history_104)

    # NO LOOK-AHEAD. Every window is taken from weeks at or before the target, never after.
    # This matters because the windows are "the last N rows" of whatever history is passed in: via
    # the API, fetch_wfm_context supplies 104 weeks ENDING at the target week, but a caller holding a
    # queue's full series (the loaders and the check tools do) would otherwise hand over weeks AFTER
    # the one being explained, and "the last 13 weeks" would silently become 13 future weeks.
    # Measured: the same queue-week scored drift +1.85 pts/week from a full series against +0.47 from
    # the correct window -- a different verdict, from future data leaking into the baseline.
    rows_all = ([r for r in every if int(r[0]) <= int(target_week)]
                if target_week is not None else every)

    # The target week itself is excluded from the BASELINE windows: including the week being explained
    # lets a big miss pull its own "usual" toward itself and understate the anomaly. Seasonality and
    # outlier detection use rows_all instead, because both need the target week present to score it.
    rows = [r for r in rows_all if target_week is None or int(r[0]) != int(target_week)]

    recent = rows[-RECENT_WEEKS:]
    year = rows[-YEAR_WEEKS:]
    long_w = rows[-LONG_WEEKS:]

    blocks = {
        "accuracy_recent": _accuracy_block(recent, f"last {RECENT_WEEKS} weeks"),
        "accuracy_year": _accuracy_block(year, f"last {YEAR_WEEKS} weeks"),
        "accuracy_long": _accuracy_block(long_w, f"last {LONG_WEEKS} weeks"),
        "coefficient_of_variation_recent": _coefficient_of_variation(recent, f"last {RECENT_WEEKS} weeks"),
        "coefficient_of_variation_long": _coefficient_of_variation(long_w, f"last {LONG_WEEKS} weeks"),
        "trend_recent": _trend_and_cor(recent, f"last {RECENT_WEEKS} weeks"),
        "trend_year": _trend_and_cor(year, f"last {YEAR_WEEKS} weeks"),
        "drift_recent": _drift(recent, f"last {RECENT_WEEKS} weeks"),
        "drift_year": _drift(year, f"last {YEAR_WEEKS} weeks"),
        "momentum": _momentum(rows),
        "seasonality": _seasonality(rows_all, target_week),
        "outliers": _outliers(rows_all, target_week),
        "correlations_pearson": _correlations(history_104, target_week),
    }
    findings = _verdict(blocks, target_adherence, band)
    return {
        "available": bool(rows),
        "weeks_available": len(rows_all),
        "weeks_supplied": len(every),
        "weeks_after_target_ignored": len(every) - len(rows_all),
        "weeks_used_excluding_target": len(rows),
        "windows": {"recent": RECENT_WEEKS, "year": YEAR_WEEKS, "long": LONG_WEEKS},
        "metrics": blocks,
        "findings": findings,
        "strongest_finding": findings[0] if findings else None,
        "note": ("Deterministic arithmetic on this queue's own history -- no model involved. "
                 "Runs regardless of whether the miss is also visible at a higher level, so the "
                 "queue is always characterised rather than the investigation stopping upstream."),
    }
