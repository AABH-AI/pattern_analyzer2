# -*- coding: utf-8 -*-
"""
Independent verification of backend/wfm/statistical_evidence.py.

WHY A SEPARATE TOOL
-------------------
The statistics now OVERRULE the model's conclusion, so a wrong formula would not produce a visibly
odd sentence -- it would produce a confident, plausible, wrong root cause. That is the most dangerous
kind of defect in this system, so every metric is recomputed here from the SQL rows by a SECOND,
independently written implementation and asserted to agree with the engine.

Deliberately NOT sharing code with the module under test: importing its helpers would only prove the
module agrees with itself. The formulas below are written out again from the definitions.

Run:  python results/statistical_engine_check.py
Needs SQL (the VPN). Writes results/statistical-engine-report.json.
"""
import json
import math
import os
import statistics as st
import sys

# Model output can contain any Unicode (U+2011 NON-BREAKING HYPHEN aborted a run on the Windows
# cp1252 console). Force UTF-8 on stdout/stderr with replacement so a printable character can never
# fail a suite that has otherwise passed.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))

from sql_backend import load_config, connect                      # noqa: E402
from wfm.statistical_evidence import statistical_evidence          # noqa: E402

TOL = 0.02          # absolute tolerance on rounded figures (the engine rounds to 2dp)
checks = []


def add(name, ok, detail=""):
    checks.append({"check": name, "status": ("PASS" if ok else "FAIL"), "detail": detail})
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if detail and not ok:
        print(f"        {detail}")


def close(a, b, tol=TOL):
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) <= tol


# ---------------------------------------------------------------- independent formulas
def ind_pairs(rows, exclude_week):
    out = []
    for r in rows:
        try:
            wk = int(r["Fiscal_Week"])
            fc = float(r["fcst_offered"])
            ac = float(r["Actual_Offered"])
        except (TypeError, ValueError, KeyError):
            continue
        if fc == 0 or ac <= 0 or wk == int(exclude_week):
            continue
        out.append((wk, fc, ac))
    return sorted(out, key=lambda t: t[0])


def ind_accuracy(rows):
    """MAE / MAPE / WAPE / RMSE / Bias / Variance, from the textbook definitions."""
    e = [ac - fc for _, fc, ac in rows]
    a = [ac for _, _, ac in rows]
    return {
        "mae": sum(abs(x) for x in e) / len(e),
        "mape_pct": sum(abs(ac - fc) / ac for _, fc, ac in rows) / len(rows) * 100,
        "wape_pct": sum(abs(x) for x in e) / sum(a) * 100,
        "rmse": math.sqrt(sum(x * x for x in e) / len(e)),
        "bias": sum(e) / len(e),
        "forecast_variance": st.variance(e),
    }


def ind_slope(ys):
    """OLS slope against 0..n-1, computed via the covariance/variance identity rather than the
    sum-of-squares form used in the module -- a different arrangement of the same algebra."""
    n = len(ys)
    xs = list(range(n))
    mx = (n - 1) / 2.0
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / n
    var = sum((x - mx) ** 2 for x in xs) / n
    return cov / var if var else None


def ind_pearson(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = math.sqrt(sum((x - mx) ** 2 for x in xs)) * math.sqrt(sum((y - my) ** 2 for y in ys))
    return num / den if den else None


def main():
    cfg = load_config()
    conn = connect(cfg)
    cur = conn.cursor()
    tbl = cfg["sql"]["table"]

    # deliberate selection, not sampling: the most-volatile queue, the most-stable, and the largest,
    # so the checks cover the branches the verdict logic actually takes
    cur.execute(f"SELECT DISTINCT Forecast_name FROM {tbl}")
    names = [r[0] for r in cur.fetchall()]
    profile = []
    for q in names:
        cur.execute(f"SELECT Actual_Offered FROM {tbl} WHERE Forecast_name = ? AND Actual_Offered > 0", q)
        vals = [float(r[0]) for r in cur.fetchall()]
        if len(vals) < 20:
            continue
        mu = sum(vals) / len(vals)
        profile.append((q, st.stdev(vals) / mu if mu else 0, mu))
    profile.sort(key=lambda t: t[1])
    cases = []
    if profile:
        cases = [("most stable", profile[0][0]), ("most volatile", profile[-1][0]),
                 ("largest volume", max(profile, key=lambda t: t[2])[0])]

    print("=" * 78)
    print("STATISTICAL ENGINE CHECK -- every metric recomputed independently from SQL")
    print(f"table: {tbl}")
    print("=" * 78)

    for label, q in cases:
        cur.execute(f"SELECT * FROM {tbl} WHERE Forecast_name = ? ORDER BY Fiscal_Week", q)
        cols = [d[0] for d in cur.description]
        hist = [dict(zip(cols, r)) for r in cur.fetchall()]
        # The LAST row is often a future week: this dataset carries forecasts past the final actual,
        # so hist[-1] picked a forecast-only week and float(None) raised. Pick the most recent week
        # that is actually scoreable. (Same fix already applied in the pattern_analyzer2 worktree.)
        target = next((r for r in reversed(hist)
                       if r.get("Actual_Offered") is not None
                       and r.get("fcst_offered") not in (None, 0)), None)
        if target is None:
            add(f"[{q}] has at least one scoreable week", False, "every week is NULL or zero-forecast")
            continue
        wk = int(target["Fiscal_Week"])
        fo, ao = float(target["fcst_offered"]), float(target["Actual_Offered"])
        adh = (1 - ao / fo) * 100

        print(f"\n-- {label}: {q} FW{wk} (adherence {adh:+.1f}%, {len(hist)} weeks)")
        se = statistical_evidence(hist, wk, adh, 10)
        m = se["metrics"]

        rows = ind_pairs(hist, wk)
        add(f"[{q}] target week excluded from the baseline window",
            se["weeks_used_excluding_target"] == len(rows),
            f"engine={se['weeks_used_excluding_target']} independent={len(rows)}")

        # ---- accuracy metrics, on the 13-week window
        recent = rows[-13:]
        exp = ind_accuracy(recent)
        got = m["accuracy_recent"]
        for key in ("mae", "mape_pct", "wape_pct", "rmse", "bias", "forecast_variance"):
            add(f"[{q}] {key} (13 wks)", close(got.get(key), exp[key]),
                f"engine={got.get(key)} independent={round(exp[key], 4)}")

        # ---- CoV on the long window
        long_w = rows[-104:]
        acts = [ac for _, _, ac in long_w]
        exp_cv = st.stdev(acts) / (sum(acts) / len(acts))
        add(f"[{q}] coefficient_of_variation (104 wks)",
            close(m["coefficient_of_variation_long"]["coefficient_of_variation"], exp_cv, 0.0005),
            f"engine={m['coefficient_of_variation_long']['coefficient_of_variation']} independent={round(exp_cv, 4)}")

        # ---- CoR / trend slope on actuals
        exp_slope = ind_slope([ac for _, _, ac in recent])
        add(f"[{q}] coefficient_of_regression per week (13 wks)",
            close(m["trend_recent"]["coefficient_of_regression_per_week"], exp_slope, 0.01),
            f"engine={m['trend_recent']['coefficient_of_regression_per_week']} independent={round(exp_slope, 4)}")

        # ---- drift slope on adherence
        exp_drift = ind_slope([(1 - ac / fc) * 100 for _, fc, ac in recent])
        add(f"[{q}] drift pts per week (13 wks)",
            close(m["drift_recent"]["adherence_drift_pts_per_week"], exp_drift, 0.005),
            f"engine={m['drift_recent']['adherence_drift_pts_per_week']} independent={round(exp_drift, 4)}")

        # ---- momentum
        if m["momentum"].get("available"):
            a = [ac for _, _, ac in rows]
            r_mean, p_mean = sum(a[-4:]) / 4, sum(a[-12:-4]) / 8
            add(f"[{q}] momentum change_pct",
                close(m["momentum"]["change_pct"], (r_mean - p_mean) / p_mean * 100),
                f"engine={m['momentum']['change_pct']} independent={round((r_mean - p_mean) / p_mean * 100, 3)}")

        # ---- Pearson correlation, first driver reported
        corr = m["correlations_pearson"]
        if corr:
            fld = corr[0]["field"]
            xs, ys = [], []
            for r in hist:
                try:
                    d, av = float(r[fld]), float(r["Actual_Offered"])
                except (TypeError, ValueError, KeyError):
                    continue
                xs.append(d)
                ys.append(av)
            add(f"[{q}] pearson_r for {fld}", close(corr[0]["pearson_r"], ind_pearson(xs, ys), 0.002),
                f"engine={corr[0]['pearson_r']} independent={round(ind_pearson(xs, ys), 4)}")
            add(f"[{q}] pearson_r within [-1, 1]", all(-1.0 <= c["pearson_r"] <= 1.0 for c in corr))

        # ---- internal consistency, the properties that must hold for ANY dataset
        add(f"[{q}] RMSE >= MAE (Jensen)", got["rmse"] >= got["mae"] - TOL,
            f"rmse={got['rmse']} mae={got['mae']}")
        add(f"[{q}] |bias| <= MAE", abs(got["bias"]) <= got["mae"] + TOL,
            f"bias={got['bias']} mae={got['mae']}")
        add(f"[{q}] WAPE > 0 and finite",
            got["wape_pct"] is not None and 0 < got["wape_pct"] < 10000, f"wape={got['wape_pct']}")
        add(f"[{q}] every metric block reports its window and n",
            all(("window" in b and "n" in b) for k, b in m.items()
                if isinstance(b, dict) and k.startswith(("accuracy", "coefficient", "trend", "drift"))))
        add(f"[{q}] findings only cite measured preconditions",
            all(f.get("rank_basis") and f.get("metric") for f in se["findings"]),
            str([f.get("rank_basis") for f in se["findings"]]))

        if se["findings"]:
            print(f"        findings: {[f['rank_basis'] + ' -> ' + f['cause_type'] for f in se['findings']]}")

    # ---- thin-data behaviour must degrade honestly, never raise
    try:
        thin = statistical_evidence([{"Fiscal_Week": 202701, "fcst_offered": 100, "Actual_Offered": 90}],
                                    202701, 10.0, 10)
        add("thin history degrades without raising",
            thin["metrics"]["accuracy_recent"]["available"] is False)
        add("thin history states WHY it is unavailable",
            bool(thin["metrics"]["accuracy_recent"].get("note")))
    except Exception as e:                                     # noqa: BLE001
        add("thin history degrades without raising", False, f"raised {type(e).__name__}: {e}")
    try:
        empty = statistical_evidence([], None, None, 10)
        add("empty history returns available=False", empty["available"] is False)
    except Exception as e:                                     # noqa: BLE001
        add("empty history returns available=False", False, f"raised {type(e).__name__}: {e}")

    conn.close()
    npass = sum(1 for c in checks if c["status"] == "PASS")
    nfail = len(checks) - npass
    print("\n" + "=" * 78)
    print(f"{npass} PASS / {nfail} FAIL  of {len(checks)} checks")
    print("=" * 78)
    with open(os.path.join(HERE, "statistical-engine-report.json"), "w", encoding="utf-8") as fh:
        json.dump({"table": tbl, "cases": cases, "checks": checks,
                   "totals": {"pass": npass, "fail": nfail}}, fh, indent=2, default=str)
    return 1 if nfail else 0


if __name__ == "__main__":
    sys.exit(main())
