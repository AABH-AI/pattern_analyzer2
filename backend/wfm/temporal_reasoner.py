"""Temporal reasoning: compare this week against the queue's own history.

The prompt requires previous week / last 4 / last 13 / same fiscal week last year and
forbids concluding from a single week. All of it is arithmetic on real values -- the
model is never asked to compute an average.
"""
from .common import (
    adherence_pct,
    bias,
    coefficient_of_variation,
    drift,
    mae,
    mape,
    mean,
    momentum,
    num,
    rmse,
    rnd,
    wape,
)


def analyse(history_104, target_week, target_actual, target_forecast, prior_year_wk):
    hist = [h for h in (history_104 or []) if str(h.get("Fiscal_Week")) != str(target_week)]

    # Level statistics (averages, volatility) want every week that HAS an actual.
    acts = [a for a in (num(h.get("Actual_Offered")) for h in hist) if a is not None]

    # Error statistics need the actual and the forecast FROM THE SAME WEEK. Filtering the
    # two columns independently desynchronises them: one week missing a forecast shifts
    # every later actual onto the wrong week's forecast, which manufactures error out of a
    # perfect forecast (a 5-week perfect series with one missing forecast scored 30% WAPE).
    # Pair inside the row first, then split -- so only weeks with BOTH values are scored.
    scored = [(num(h.get("Actual_Offered")), num(h.get("fcst_offered"))) for h in hist]
    scored = [(a, f) for a, f in scored if a is not None and f is not None]
    err_acts = [a for a, _ in scored]
    err_fcsts = [f for _, f in scored]

    def avg(n):
        window = acts[-n:] if n else acts
        return rnd(mean(window))

    last_year = next((h for h in (history_104 or [])
                      if str(h.get("Fiscal_Week")) == str(prior_year_wk)), None)
    t_adh = adherence_pct(target_actual, target_forecast)

    # Plan changes anywhere in the window -- the prompt asks about forecast plan changes.
    plans = [h.get("Projection_plan_name") for h in (history_104 or [])
             if h.get("Projection_plan_name") not in (None, "")]
    distinct_plans = list(dict.fromkeys(str(p) for p in plans))

    # Statistical Evidence calculations across recent history.
    # Error metrics use the same-week pairs; level metrics use the actual series.
    stat_wape = wape(err_acts, err_fcsts)
    stat_mape = mape(err_acts, err_fcsts)
    stat_mae = mae(err_acts, err_fcsts)
    stat_rmse = rmse(err_acts, err_fcsts)
    stat_bias = bias(err_acts, err_fcsts)
    stat_cv = coefficient_of_variation(acts)
    stat_drift = drift(err_acts, err_fcsts)
    stat_momentum = momentum(acts + ([target_actual] if target_actual is not None else []))

    return {
        "this_week": {"fiscal_week": target_week, "actual": target_actual,
                      "forecast": target_forecast, "adherence_pct": rnd(t_adh)},
        "previous_week": ({"fiscal_week": hist[-1].get("Fiscal_Week"),
                           "actual": num(hist[-1].get("Actual_Offered"))} if hist else None),
        "last_4_week_avg_actual": avg(4),
        "last_13_week_avg_actual": avg(13),
        "full_history_avg_actual": avg(0),
        "history_weeks_available": len(acts),
        "history_weeks_scored_for_error": len(scored),
        "same_week_last_year": ({"fiscal_week": last_year.get("Fiscal_Week"),
                                 "actual": num(last_year.get("Actual_Offered")),
                                 "forecast": num(last_year.get("fcst_offered"))}
                                if last_year else None),
        "same_week_last_year_note": (None if last_year else
                                     f"No row found for fiscal week {prior_year_wk}."),
        "distinct_forecast_plans_in_window": distinct_plans,
        "forecast_plan_changed_within_window": len(distinct_plans) > 1,
        "STATISTICAL_EVIDENCE": {
            "wape_pct": stat_wape,
            "mape_pct": stat_mape,
            "mae_contacts": stat_mae,
            "rmse_contacts": stat_rmse,
            "bias_pct": stat_bias,
            "coefficient_of_variation": stat_cv,
            "baseline_drift_pct": stat_drift,
            "demand_momentum_acceleration": stat_momentum,
        },
    }
