"""
Is there any correlation between the data points?
=================================================

Run:  cd backend && python ../results/driver_correlation_survey.py

The question behind the question: **does this dataset contain drivers that actually track demand?**
If nothing correlates, no RCA engine can attribute a miss to anything -- it can only describe the
miss in different words, which is exactly the criticism the business made. So this measures it
rather than assuming either way.

Method
------
Rank (Spearman) correlation, per queue, over that queue's own weekly history, then aggregated
across queues. Per queue and not pooled, on purpose: pooling every queue together would mostly
measure "big queues have big numbers" (a size effect), not "this driver moves with demand".
Rank-based rather than Pearson so one extreme week cannot manufacture a relationship.

A queue is only counted when it has >= MIN_WEEKS usable pairs. "Strong" is |rho| >= 0.5.

Reported per driver:
  queues tested / share strong / median rho / how the sign splits
And separately: does fcst_offered track Actual_Offered at all? If the forecast does not correlate
with demand, that is the finding -- it would mean the plan carries little information about the
thing it is forecasting.
"""
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE + "/../backend")

from sql_backend import connect, load_config          # noqa: E402
from wfm.correlation_engine import _spearman          # noqa: E402

MIN_WEEKS = 12
STRONG = 0.5

DRIVERS = [
    ("fcst_offered", "the forecast itself"),
    ("Planned_ASU", "planned units under warranty"),
    ("Actual_ASU", "actual units under warranty"),
    ("Final_Units", "installed base"),
    ("Final_upp_units", "extended-protection units"),
    ("Holiday_Count", "holidays in the week"),
    ("Actual_Handled", "contacts handled"),
]


def median(xs):
    xs = sorted(xs)
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2.0


def main():
    cfg = load_config()
    table = cfg["sql"]["table"]
    conn = connect(cfg)
    cur = conn.cursor()

    cols = ["Forecast_name", "Fiscal_Week", "Actual_Offered"] + [d for d, _ in DRIVERS]
    cur.execute(f"SELECT {', '.join(cols)} FROM {table} ORDER BY Forecast_name, Fiscal_Week")
    rows = cur.fetchall()
    conn.close()

    by_queue = defaultdict(list)
    for r in rows:
        rec = dict(zip(cols, r))
        by_queue[rec["Forecast_name"]].append(rec)

    print("=" * 78)
    print("DRIVER CORRELATION SURVEY")
    print(f"  {len(rows):,} rows across {len(by_queue)} queues")
    print(f"  per-queue rank correlation vs Actual_Offered; >= {MIN_WEEKS} weeks; strong = |rho| >= {STRONG}")
    print("=" * 78)
    print()
    print(f"  {'driver':22s} {'tested':>7} {'strong':>8} {'share':>7} {'median rho':>11}  sign split")
    print("  " + "-" * 74)

    summary = {}
    for field, label in DRIVERS:
        rhos = []
        for qname, recs in by_queue.items():
            demand = [x["Actual_Offered"] for x in recs]
            drv = [x[field] for x in recs]
            pairs = [(a, b) for a, b in zip(drv, demand)
                     if a is not None and b is not None]
            if len(pairs) < MIN_WEEKS:
                continue
            rho, n = _spearman([p[0] for p in pairs], [p[1] for p in pairs])
            if rho is not None:
                rhos.append(rho)
        if not rhos:
            print(f"  {field:22s} {0:>7} {'-':>8} {'-':>7} {'-':>11}  (no queue had enough data)")
            summary[field] = None
            continue
        strong = [r for r in rhos if abs(r) >= STRONG]
        pos = sum(1 for r in strong if r > 0)
        neg = len(strong) - pos
        share = len(strong) / len(rhos)
        print(f"  {field:22s} {len(rhos):>7} {len(strong):>8} {share:>6.0%} {median(rhos):>11.2f}"
              f"  +{pos} / -{neg}")
        summary[field] = {"tested": len(rhos), "strong": len(strong), "share": round(share, 3),
                          "median_rho": round(median(rhos), 3), "positive": pos, "negative": neg}

    print()
    print("  WHAT THIS MEANS")
    fc = summary.get("fcst_offered")
    if fc:
        print(f"  * The forecast tracks demand on {fc['share']:.0%} of queues (median rho "
              f"{fc['median_rho']:.2f}). This is the sanity check: a forecast that did not correlate "
              f"with its own actuals would carry almost no information.")
    asu = summary.get("Actual_ASU") or summary.get("Planned_ASU")
    if asu:
        print(f"  * The warranty base (ASU) tracks demand on {asu['share']:.0%} of queues that have "
              f"it (median rho {asu['median_rho']:.2f}).")
    hol = summary.get("Holiday_Count")
    if hol:
        print(f"  * Holidays reach the strong threshold on {hol['share']:.0%} of queues "
              f"(median rho {hol['median_rho']:.2f}) -- so treating holidays as a general "
              f"explanation is usually not supported; it has to be shown per queue.")
    print()
    print("  Caveat worth stating: a correlation over a queue's own history says a driver MOVES WITH")
    print("  demand, not that it CAUSED a particular week's miss. The engine uses these only to")
    print("  decide which drivers are worth citing for a given queue -- it retains a relationship")
    print("  per queue and rejects the rest, rather than assuming any driver applies everywhere.")
    print("=" * 78)

    import json
    with open(os.path.join(HERE, "driver-correlation-survey.json"), "w", encoding="utf-8") as fh:
        json.dump({"rows": len(rows), "queues": len(by_queue), "min_weeks": MIN_WEEKS,
                   "strong_threshold": STRONG, "drivers": summary}, fh, indent=1)
    print("report -> results/driver-correlation-survey.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
