"""Temporal reasoning: compare this week against the queue's own history.

The prompt requires previous week / last 4 / last 13 / same fiscal week last year and
forbids concluding from a single week. All of it is arithmetic on real values -- the
model is never asked to compute an average.
"""
from .common import adherence_pct, mean, num, rnd


def analyse(history_104, target_week, target_actual, target_forecast, prior_year_wk):
    hist = [h for h in (history_104 or []) if str(h.get("Fiscal_Week")) != str(target_week)]
    acts = [num(h.get("Actual_Offered")) for h in hist]
    acts = [a for a in acts if a is not None]

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

    return {
        "this_week": {"fiscal_week": target_week, "actual": target_actual,
                      "forecast": target_forecast, "adherence_pct": rnd(t_adh)},
        "previous_week": ({"fiscal_week": hist[-1].get("Fiscal_Week"),
                           "actual": num(hist[-1].get("Actual_Offered"))} if hist else None),
        "last_4_week_avg_actual": avg(4),
        "last_13_week_avg_actual": avg(13),
        "full_history_avg_actual": avg(0),
        "history_weeks_available": len(acts),
        "same_week_last_year": ({"fiscal_week": last_year.get("Fiscal_Week"),
                                 "actual": num(last_year.get("Actual_Offered")),
                                 "forecast": num(last_year.get("fcst_offered"))}
                                if last_year else None),
        "same_week_last_year_note": (None if last_year else
                                     f"No row found for fiscal week {prior_year_wk}."),
        "distinct_forecast_plans_in_window": distinct_plans,
        "forecast_plan_changed_within_window": len(distinct_plans) > 1,
    }
