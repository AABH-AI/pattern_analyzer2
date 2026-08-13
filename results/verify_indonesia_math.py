"""
Independent arithmetic check of the WFM engine — SA Indonesia Client Basic, FW202716.
=====================================================================================

Run:  cd backend && python ../results/verify_indonesia_math.py

Backs every number in ../WFM_MATH_AND_TOOL_EVIDENCE.md. This script deliberately imports
NOTHING from backend/wfm/ — every formula is written out here from scratch and run against
dbo.Input_To_ML_Full directly, so agreement with the engine means two independent
implementations concur, not that one called the other.

It reads SQL and writes one JSON report. It changes nothing.

Sections
  1  target week + the one KPI            adherence = (1 - actual/forecast) * 100
  2  accuracy over 13 / 52 / 104 weeks    MAE, MAPE, WAPE, RMSE, bias, error sd/variance
  3  volatility (CV), trend, drift        OLS slope + r^2, written out by hand
  4  momentum, seasonality, plan gap
  5  z-scores over the 13 posted weeks    including the Final_upp_units coverage problem
  6  Spearman rho for the four drivers
  7  the investigation ladder             6 scope levels, recomputed from SUM()
  8  data quality                         median, times-typical, reversion

The engine's own window is TOP 157 rows <= target (wfm/common.py WFM_HISTORY_WEEKS), so the
checks run inside that window; section 6 additionally reports the full-history value because
the retention threshold is sensitive to it.
"""
import json
import math
import os
import statistics as st
import sys

sys.path.insert(0, ".")
from sql_backend import connect, load_config  # noqa: E402

NAME, TARGET, CAP = "SA Indonesia Client Basic", 202716, 157
HERE = os.path.dirname(os.path.abspath(__file__))

# What the engine reported, transcribed from results/indonesia-wfm-gemini.json, so every
# check below is an explicit comparison rather than a number to eyeball.
ENGINE = {
    "adherence_pct": -138.3,
    "accuracy_recent": {"mae": 36.64, "mape_pct": 52.2, "wape_pct": 40.57, "rmse": 45.31,
                        "bias": -4.22, "bias_pct": -4.67, "forecast_error_std_dev": 46.95,
                        "forecast_variance": 2204.69, "mean_actual": 90.31},
    "accuracy_year": {"mae": 20.15, "mape_pct": 24.72, "wape_pct": 20.76, "rmse": 28.01,
                      "bias": 1.77, "bias_pct": 1.82, "forecast_error_std_dev": 28.22,
                      "forecast_variance": 796.5, "mean_actual": 97.06},
    "accuracy_long": {"mae": 17.77, "mape_pct": 20.64, "wape_pct": 17.77, "rmse": 24.19,
                      "bias": -1.22, "bias_pct": -1.22, "forecast_error_std_dev": 24.27,
                      "forecast_variance": 589.14, "mean_actual": 99.99},
    "cv_recent": 0.3096, "cv_long": 0.2415,
    "trend_recent_slope": 2.92, "trend_recent_r2": 0.165,
    "trend_year_slope": 0.1, "trend_year_r2": 0.003,
    "drift_recent_slope": -9.842, "drift_recent_r2": 0.289, "drift_recent_total": -127.95,
    "drift_year_slope": -0.609, "drift_year_r2": 0.056, "drift_year_total": -31.67,
    "momentum_recent": 105.75, "momentum_prior": 87.0, "momentum_pct": 21.55,
    "same_week_mean": 122.33, "seasonal_index": 1.118,
    "plan_vs_seasonal_norm_pct": -47.85, "plan_vs_overall_pct": -41.56,
    "z_actual": 2.21, "z_forecast": -1.04, "z_holiday": -0.63, "z_upp": 23.33,
    "usual_forecast": 94.53, "usual_actual": 90.31, "usual_planned_asu": 26672.77,
    "spearman": {"Actual_ASU": 0.47, "Planned_ASU": 0.4, "Final_Units": -0.01,
                 "Holiday_Count": -0.37},
    "ladder": {"Business Org": -3.9, "Region": -1.6, "SubRegion": 1.2, "Country": 0.8,
               "Offering": -138.3, "Channel": -138.3},
    "typical_week_actual": 107.0, "next_weeks_actual": [73.0, 70.0, 85.0],
}

checks = []


def add(cid, what, mine, engine, tol=0.005):
    """Record one comparison. Exact means equal to the engine's own reported precision."""
    if isinstance(mine, (int, float)) and isinstance(engine, (int, float)):
        ok = abs(mine - engine) <= tol
    else:
        ok = mine == engine
    checks.append({"id": cid, "check": what, "mine": mine, "engine": engine, "pass": bool(ok)})
    return ok


# --------------------------------------------------------------------------- data
cfg = load_config()
table = cfg["sql"]["table"]
cur = connect(cfg).cursor()
cur.execute(f"SELECT TOP {CAP} Fiscal_Week,fcst_offered,Actual_Offered,Holiday_Count,Planned_ASU,"
            f"Actual_ASU,Final_Units,Final_upp_units FROM {table} "
            f"WHERE Forecast_name=? AND Fiscal_Week<=? ORDER BY Fiscal_Week DESC", (NAME, TARGET))
cols = [d[0] for d in cur.description]
rows = [dict(zip(cols, r)) for r in cur.fetchall()][::-1]          # chronological
F = lambda v: None if v is None else float(v)                      # noqa: E731

pairs = [(int(r["Fiscal_Week"]), F(r["fcst_offered"]), F(r["Actual_Offered"])) for r in rows
         if F(r["fcst_offered"]) not in (None, 0) and (F(r["Actual_Offered"]) or 0) > 0]
hist = [p for p in pairs if p[0] != TARGET]
by_week = {int(r["Fiscal_Week"]): r for r in rows}
_, TF, TA = [p for p in pairs if p[0] == TARGET][0]

add("W1", "rows fetched inside the 157 cap", len(rows), 157)
add("W2", "usable (forecast, actual) pairs", len(pairs), 155)
add("W3", "weeks used excluding the target", len(hist), 154)

# --------------------------------------------------------------- 1. the one KPI
add("K1", "adherence_pct = (1 - actual/forecast) * 100",
    round((1.0 - TA / TF) * 100.0, 1), ENGINE["adherence_pct"])
add("K2", "error = actual - forecast", round(TA - TF, 2), 88.21)

# --------------------------------------------------------------- 2. accuracy blocks
def accuracy(win):
    n = len(win)
    err = [a - f for _, f, a in win]
    acts = [a for _, _, a in win]
    mean_actual = sum(acts) / n
    bias = sum(err) / n
    return {"mae": round(sum(abs(e) for e in err) / n, 2),
            "mape_pct": round(sum(abs(a - f) / a * 100.0 for _, f, a in win) / n, 2),
            "wape_pct": round(sum(abs(e) for e in err) / sum(acts) * 100.0, 2),
            "rmse": round(math.sqrt(sum(e * e for e in err) / n), 2),
            "bias": round(bias, 2), "bias_pct": round(bias / mean_actual * 100.0, 2),
            "forecast_error_std_dev": round(st.stdev(err), 2),
            "forecast_variance": round(st.variance(err), 2),
            "mean_actual": round(mean_actual, 2)}

for label, w in (("recent", 13), ("year", 52), ("long", 104)):
    got = accuracy(hist[-w:])
    for metric, val in got.items():
        add(f"A-{label}-{metric}", f"{metric} over {w} weeks", val,
            ENGINE[f"accuracy_{label}"][metric])

# --------------------------------------------------------------- 3. CV, trend, drift
def ols(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    syy = sum((y - my) ** 2 for y in ys)
    return sxy / sxx, (sxy ** 2 / (sxx * syy) if syy else None)

for label, w in (("recent", 13), ("long", 104)):
    acts = [a for _, _, a in hist[-w:]]
    add(f"CV-{label}", f"CV over {w} weeks (sample sd / mean)",
        round(st.stdev(acts) / (sum(acts) / len(acts)), 4), ENGINE[f"cv_{label}"])

for label, w in (("recent", 13), ("year", 52)):
    win = hist[-w:]
    xs = list(range(len(win)))
    s, r2 = ols(xs, [a for _, _, a in win])
    add(f"T-{label}-slope", f"trend slope of actual, {w} weeks", round(s, 2),
        ENGINE[f"trend_{label}_slope"])
    add(f"T-{label}-r2", f"trend r^2, {w} weeks", round(r2, 3), ENGINE[f"trend_{label}_r2"])
    s2, r22 = ols(xs, [(1.0 - a / f) * 100.0 for _, f, a in win])
    add(f"D-{label}-slope", f"adherence drift slope, {w} weeks", round(s2, 3),
        ENGINE[f"drift_{label}_slope"])
    add(f"D-{label}-r2", f"drift r^2, {w} weeks", round(r22, 3), ENGINE[f"drift_{label}_r2"])
    # The engine's total is slope * n. A window of n observations spans n-1 intervals, so
    # slope * (n-1) is the change actually implied across it. Both are reported.
    add(f"D-{label}-total(x n)", f"drift total as slope x n, {w} weeks", round(s2 * w, 2),
        ENGINE[f"drift_{label}_total"])
    checks.append({"id": f"D-{label}-total(x n-1)",
                   "check": f"drift total as slope x (n-1), {w} weeks — span convention, FYI",
                   "mine": round(s2 * (w - 1), 2), "engine": ENGINE[f"drift_{label}_total"],
                   "pass": None})

# --------------------------------------------------------------- 4. momentum / seasonality
r4 = [a for _, _, a in hist[-4:]]
r8 = [a for _, _, a in hist[-12:-4]]
add("M1", "momentum: last 4 weeks mean", round(sum(r4) / 4, 2), ENGINE["momentum_recent"])
add("M2", "momentum: prior 8 weeks mean", round(sum(r8) / 8, 2), ENGINE["momentum_prior"])
add("M3", "momentum change %", round((sum(r4) / 4 / (sum(r8) / 8) - 1) * 100, 2),
    ENGINE["momentum_pct"])

same = [(w, a) for w, _, a in hist if w % 100 == TARGET % 100]
sm = sum(a for _, a in same) / len(same)
window_mean = sum(a for _, _, a in hist) / len(hist)
add("S1", "prior-year same-week count", len(same), 3)
add("S2", "same-week mean actual", round(sm, 2), ENGINE["same_week_mean"])
add("S3", "plan vs seasonal norm %", round((TF / sm - 1) * 100, 2),
    ENGINE["plan_vs_seasonal_norm_pct"])
add("S4", "plan vs overall mean %", round((TF / window_mean - 1) * 100, 2),
    ENGINE["plan_vs_overall_pct"])
# seasonal_index: the engine divides by a mean that INCLUDES the target week (155 rows),
# while plan_vs_seasonal_norm excludes it (154). Recorded, not asserted.
checks.append({"id": "S5", "check": "seasonal index — denominator excludes target (FYI)",
               "mine": round(sm / window_mean, 3), "engine": ENGINE["seasonal_index"],
               "pass": None})
incl = (window_mean * len(hist) + TA) / (len(hist) + 1)
add("S6", "seasonal index when the target IS included (explains S5)",
    round(sm / incl, 3), ENGINE["seasonal_index"])

# --------------------------------------------------------------- 5. z-scores
h13 = [w for w, _, _ in hist[-13:]]
fc13 = [f for _, f, _ in hist[-13:]]
ac13 = [a for _, _, a in hist[-13:]]
add("Z1", "usual forecast (13-week mean)", round(sum(fc13) / 13, 2), ENGINE["usual_forecast"])
add("Z2", "usual actual (13-week mean)", round(sum(ac13) / 13, 2), ENGINE["usual_actual"])
add("Z3", "z of actual vs own 13-week history",
    round((TA - sum(ac13) / 13) / st.stdev(ac13), 2), ENGINE["z_actual"])
add("Z4", "z of forecast vs own 13-week history",
    round((TF - sum(fc13) / 13) / st.stdev(fc13), 2), ENGINE["z_forecast"])

for field, key in (("Holiday_Count", "z_holiday"), ("Final_upp_units", "z_upp")):
    vals = [F(by_week[w][field]) for w in h13 if F(by_week[w][field]) is not None]
    t = F(by_week[TARGET][field])
    m = sum(vals) / len(vals)
    sd = st.stdev(vals) if len(vals) > 1 else None
    add(f"Z-{field}", f"z of {field} (n={len(vals)} history weeks)",
        (round((t - m) / sd, 2) if sd else None), ENGINE[key])

upp = [(int(r["Fiscal_Week"]), F(r["Final_upp_units"])) for r in rows
       if F(r["Final_upp_units"]) is not None]
checks.append({"id": "Z-COVERAGE",
               "check": "Final_upp_units non-NULL weeks out of 157 — WHY its z is unsound",
               "mine": {"weeks_with_a_value": len(upp), "values": upp},
               "engine": "z 23.33 treated as material", "pass": None})

asu13 = [F(by_week[w]["Planned_ASU"]) for w in h13 if F(by_week[w]["Planned_ASU"]) is not None]
add("Z5", "usual Planned_ASU (13-week mean)", round(sum(asu13) / len(asu13), 2),
    ENGINE["usual_planned_asu"])

# --------------------------------------------------------------- 6. Spearman
def spearman(xs, ys):
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        out = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                out[order[k]] = avg
            i = j + 1
        return out
    rx, ry = rank(xs), rank(ys)
    n = len(rx)
    mx, my = sum(rx) / n, sum(ry) / n
    sxx = sum((x - mx) ** 2 for x in rx)
    syy = sum((y - my) ** 2 for y in ry)
    sxy = sum((x - mx) * (y - my) for x, y in zip(rx, ry))
    return sxy / math.sqrt(sxx * syy) if sxx > 0 and syy > 0 else None

for drv in ("Actual_ASU", "Planned_ASU", "Final_Units", "Holiday_Count"):
    xy = [(F(r[drv]), F(r["Actual_Offered"])) for r in rows
          if F(r[drv]) is not None and F(r["Actual_Offered"]) is not None]
    if len(xy) >= 3:
        add(f"R-{drv}", f"Spearman rho, {drv} vs Actual_Offered ({len(xy)} weeks)",
            round(spearman([a for a, _ in xy], [b for _, b in xy]), 2), ENGINE["spearman"][drv])

cur.execute(f"SELECT Actual_ASU,Actual_Offered FROM {table} WHERE Forecast_name=? "
            f"AND Actual_ASU IS NOT NULL AND Actual_Offered IS NOT NULL", NAME)
full = [(float(a), float(b)) for a, b in cur.fetchall()]
checks.append({"id": "R-BOUNDARY",
               "check": "Actual_ASU rho over the FULL history — straddles the 0.5 retention cutoff",
               "mine": {"weeks": len(full), "rho": round(spearman([a for a, _ in full],
                                                                  [b for _, b in full]), 2)},
               "engine": {"weeks": 139, "rho": 0.47, "outcome": "rejected"}, "pass": None})

# --------------------------------------------------------------- 7. ladder
SCOPES = [
    ("Business Org", "business_org='CSG'"),
    ("Region", "business_org='CSG' AND Region='APJ'"),
    ("SubRegion", "business_org='CSG' AND Region='APJ' AND SubRegion='SA'"),
    ("Country", "business_org='CSG' AND Region='APJ' AND SubRegion='SA' AND Country='Indonesia'"),
    ("Offering", "business_org='CSG' AND Region='APJ' AND SubRegion='SA' AND Country='Indonesia' "
                 "AND Offering='Basic'"),
    ("Channel", "business_org='CSG' AND Region='APJ' AND SubRegion='SA' AND Country='Indonesia' "
                "AND Offering='Basic' AND channel='Voice'"),
]
for level, where in SCOPES:
    cur.execute(f"SELECT SUM(Actual_Offered),SUM(fcst_offered) FROM {table} "
                f"WHERE Fiscal_Week={TARGET} AND {where} AND Actual_Offered IS NOT NULL "
                f"AND fcst_offered IS NOT NULL")
    a, f = cur.fetchone()
    add(f"L-{level}", f"adherence at {level}",
        round((1.0 - float(a) / float(f)) * 100, 1), ENGINE["ladder"][level], tol=0.051)

# --------------------------------------------------------------- 8. data quality
acts_all = [a for _, _, a in hist]
add("Q1", "typical (median) week actual", st.median(acts_all), ENGINE["typical_week_actual"])
add("Q2", "this week as a multiple of typical", round(TA / st.median(acts_all), 2), 1.42)
cur.execute(f"SELECT TOP 3 Actual_Offered FROM {table} WHERE Forecast_name=? AND Fiscal_Week>? "
            f"ORDER BY Fiscal_Week ASC", (NAME, TARGET))
add("Q3", "the 3 following weeks (reversion test)",
    [float(r[0]) for r in cur.fetchall()], ENGINE["next_weeks_actual"])

# --------------------------------------------------------------- report
asserted = [c for c in checks if c["pass"] is not None]
failed = [c for c in asserted if not c["pass"]]
print("=" * 96)
print(f"INDEPENDENT ARITHMETIC CHECK -- {NAME} FW{TARGET}")
print(f"table: {table}    formulas: written from scratch, nothing imported from wfm/")
print("=" * 96)
for c in checks:
    mark = "FYI " if c["pass"] is None else ("PASS" if c["pass"] else "FAIL")
    print(f"  {mark}  {c['id']:22s} {c['check']}")
    if c["pass"] is None or not c["pass"]:
        print(f"            mine={c['mine']}   engine={c['engine']}")
print("-" * 96)
print(f"  {len(asserted) - len(failed)}/{len(asserted)} asserted checks passed, "
      f"{len(checks) - len(asserted)} recorded for information")
if failed:
    print("  FAILED: " + ", ".join(c["id"] for c in failed))

with open(os.path.join(HERE, "indonesia-math-verification.json"), "w", encoding="utf-8") as fh:
    json.dump({"queue": NAME, "fiscal_week": TARGET, "table": table, "checks": checks,
               "asserted": len(asserted), "passed": len(asserted) - len(failed)},
              fh, indent=1, default=str)
sys.exit(1 if failed else 0)
