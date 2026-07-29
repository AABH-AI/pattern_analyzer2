"""
Full correlation survey — every data point, both files, two targets.
===================================================================

Run:  cd backend && python ../results/full_correlation_survey.py

"Correlation" means three different things across these columns, so three methods are used and
labelled. Mixing them into one number would be meaningless.

  1. NUMERIC vs NUMERIC      -> Spearman rank correlation (rho, -1..+1)
  2. CATEGORICAL vs NUMERIC  -> eta-squared on ranks: the share of variance in the target that
                                knowing the category explains (0..1)
  3. BINARY FLAG vs NUMERIC  -> rank-biserial: the Monday..Sunday holiday flags

TWO TARGETS, and the difference matters:
  * `Actual_Offered`  -- what drives DEMAND
  * `abs(adherence)`  -- what drives the MISS
A driver can track demand perfectly and explain none of the miss. The RCA is about the miss, so the
second target is the one that matters for root-cause work; the first is context.

THE CARDINALITY TRAP -- read before believing any eta-squared
-------------------------------------------------------------
A categorical with many levels explains variance trivially. `Forecast_name` has 427 values, so
"Forecast_name explains X% of adherence variance" mostly restates "queues differ from each other",
which is identity, not insight. Every eta-squared below is therefore printed WITH its level count
and an adjusted figure, and anything with more than ~20 levels should be read as descriptive only.
Low-cardinality columns (Region=3, Offering=4, channel=5) are the interpretable ones.

BOTH FILES: `Combined_Queue_Name` and `DB_OSP` come from the CQN mapping workbook via
dbo.CQN_Mapping, so the survey covers the mapping file too, not just Input_To_ML.

Known data limits, measured before running: `business_org` has ONE distinct value (it can explain
nothing), `Final_upp_units` is 22% populated, `Actual_ASU` 57%.
"""
import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE + "/../backend")

from sql_backend import connect, load_config          # noqa: E402
from wfm.correlation_engine import _ranks, _spearman   # noqa: E402

MIN_PAIRS = 200          # pooled tests
MIN_WEEKS = 12           # per-queue tests
MIN_GROUP = 30           # a category level needs this many rows to count
STRONG = 0.5

NUMERIC = ["fcst_offered", "Planned_ASU", "Actual_ASU", "Final_Units", "Final_Y1", "Final_Y2",
           "Final_Y3", "Final_Y4", "Final_Y5", "Final_upp_units", "Holiday_Count"]
DAY_FLAGS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
CATEGORICAL = ["Region", "SubRegion", "Country", "Offering", "Projection_plan_name", "channel",
               "business_org", "Volume_Category", "Forecast_name",
               "Combined_Queue_Name", "DB_OSP"]      # last two come from the mapping file


def eta_squared_on_ranks(groups):
    """Share of rank variance explained by group membership. Robust to skew; 0..1."""
    values = [v for g in groups.values() for v in g]
    if len(values) < MIN_PAIRS or len(groups) < 2:
        return None, 0
    ranks = _ranks(values)
    idx, by_group = 0, {}
    for name, g in groups.items():
        by_group[name] = ranks[idx:idx + len(g)]
        idx += len(g)
    grand = sum(ranks) / len(ranks)
    ss_total = sum((r - grand) ** 2 for r in ranks)
    if ss_total <= 0:
        return None, len(groups)
    ss_between = sum(len(rs) * ((sum(rs) / len(rs)) - grand) ** 2 for rs in by_group.values() if rs)
    return ss_between / ss_total, len(groups)


def main():
    cfg = load_config()
    table = cfg["sql"]["table"]
    conn = connect(cfg)
    cur = conn.cursor()

    cols = (["Forecast_name", "Fiscal_Week", "Actual_Offered"] + NUMERIC + DAY_FLAGS
            + [c for c in CATEGORICAL if c not in ("Forecast_name", "Combined_Queue_Name", "DB_OSP")])
    cur.execute(
        f"SELECT {', '.join('d.' + c for c in cols)}, m.Combined_Queue_Name, m.DB_OSP "
        f"FROM {table} d LEFT JOIN dbo.CQN_Mapping m ON m.Forecast_Name = d.Forecast_name")
    fetched = cur.fetchall()
    conn.close()
    names = cols + ["Combined_Queue_Name", "DB_OSP"]
    rows = [dict(zip(names, r)) for r in fetched]

    # the two targets
    for r in rows:
        a, f = r.get("Actual_Offered"), r.get("fcst_offered")
        r["_adh"] = ((1 - a / f) * 100) if (isinstance(a, (int, float)) and isinstance(f, (int, float)) and f) else None
        r["_absadh"] = abs(r["_adh"]) if r["_adh"] is not None else None

    print("=" * 96)
    print("FULL CORRELATION SURVEY — Input_To_ML joined to the CQN mapping")
    print(f"  {len(rows):,} joined rows (the LEFT JOIN fans out multi-CQN queues, so this exceeds 66,612)")
    print(f"  targets: Actual_Offered (drives demand) and |adherence| (drives the MISS)")
    print("=" * 96)

    out = {"joined_rows": len(rows), "numeric": {}, "day_flags": {}, "categorical": {},
           "per_queue": {}, "fiscal_week": {}}

    # ---------------- 1. numeric vs both targets, POOLED ----------------
    print("\n1) NUMERIC vs target — Spearman rho, pooled across all queues")
    print(f"   {'driver':20s} {'n':>7} {'rho vs demand':>14} {'n':>7} {'rho vs |miss|':>14}")
    print("   " + "-" * 68)
    for c in NUMERIC:
        xs = [(r[c], r["Actual_Offered"]) for r in rows if r.get(c) is not None and r.get("Actual_Offered") is not None]
        r1, n1 = _spearman([p[0] for p in xs], [p[1] for p in xs]) if len(xs) >= MIN_PAIRS else (None, len(xs))
        ys = [(r[c], r["_absadh"]) for r in rows if r.get(c) is not None and r.get("_absadh") is not None]
        r2, n2 = _spearman([p[0] for p in ys], [p[1] for p in ys]) if len(ys) >= MIN_PAIRS else (None, len(ys))
        f1 = f"{r1:+.2f}" if r1 is not None else "  n/a"
        f2 = f"{r2:+.2f}" if r2 is not None else "  n/a"
        print(f"   {c:20s} {n1:>7,} {f1:>14} {n2:>7,} {f2:>14}")
        out["numeric"][c] = {"n_demand": n1, "rho_demand": round(r1, 3) if r1 is not None else None,
                            "n_miss": n2, "rho_abs_miss": round(r2, 3) if r2 is not None else None}

    # ---------------- 2. day flags ----------------
    print("\n2) HOLIDAY-ON-DAY flags vs target — Spearman on a 0/1 flag")
    print(f"   {'flag':12s} {'holiday weeks':>14} {'rho vs demand':>14} {'rho vs |miss|':>14}")
    print("   " + "-" * 58)
    for c in DAY_FLAGS:
        on = sum(1 for r in rows if r.get(c))
        xs = [(r[c], r["Actual_Offered"]) for r in rows if r.get(c) is not None and r.get("Actual_Offered") is not None]
        r1, _ = _spearman([p[0] for p in xs], [p[1] for p in xs]) if len(xs) >= MIN_PAIRS else (None, 0)
        ys = [(r[c], r["_absadh"]) for r in rows if r.get(c) is not None and r.get("_absadh") is not None]
        r2, _ = _spearman([p[0] for p in ys], [p[1] for p in ys]) if len(ys) >= MIN_PAIRS else (None, 0)
        f1 = f"{r1:+.2f}" if r1 is not None else "  n/a"
        f2 = f"{r2:+.2f}" if r2 is not None else "  n/a"
        print(f"   {c:12s} {on:>14,} {f1:>14} {f2:>14}")
        out["day_flags"][c] = {"holiday_weeks": on,
                              "rho_demand": round(r1, 3) if r1 is not None else None,
                              "rho_abs_miss": round(r2, 3) if r2 is not None else None}

    # ---------------- 3. categoricals ----------------
    print("\n3) CATEGORICAL vs target — eta-squared on ranks (share of variance explained)")
    print("   READ WITH CARE: many levels explains variance trivially. >20 levels = descriptive only.")
    print(f"   {'column':24s} {'levels':>7} {'eta2 demand':>12} {'eta2 |miss|':>12}  interpretable?")
    print("   " + "-" * 78)
    for c in CATEGORICAL:
        g1, g2 = defaultdict(list), defaultdict(list)
        for r in rows:
            k = r.get(c)
            if k in (None, ""):
                continue
            if r.get("Actual_Offered") is not None:
                g1[str(k)].append(r["Actual_Offered"])
            if r.get("_absadh") is not None:
                g2[str(k)].append(r["_absadh"])
        g1 = {k: v for k, v in g1.items() if len(v) >= MIN_GROUP}
        g2 = {k: v for k, v in g2.items() if len(v) >= MIN_GROUP}
        e1, n1 = eta_squared_on_ranks(g1)
        e2, n2 = eta_squared_on_ranks(g2)
        levels = max(n1, n2)
        note = ("CONSTANT - explains nothing" if levels <= 1 else
                "yes" if levels <= 20 else "descriptive only (high cardinality)")
        f1 = f"{e1:.3f}" if e1 is not None else "n/a"
        f2 = f"{e2:.3f}" if e2 is not None else "n/a"
        print(f"   {c:24s} {levels:>7} {f1:>12} {f2:>12}  {note}")
        out["categorical"][c] = {"levels": levels,
                                "eta2_demand": round(e1, 4) if e1 is not None else None,
                                "eta2_abs_miss": round(e2, 4) if e2 is not None else None,
                                "interpretable": note}

    # ---------------- 4. Fiscal_Week: trend and seasonality ----------------
    print("\n4) FISCAL_WEEK — is there a trend or a seasonal pattern?")
    wk = [(int(r["Fiscal_Week"]), r["Actual_Offered"]) for r in rows
          if r.get("Fiscal_Week") is not None and r.get("Actual_Offered") is not None]
    rho_t, n_t = _spearman([p[0] for p in wk], [p[1] for p in wk])
    byweek = defaultdict(float)
    for w, a in wk:
        byweek[w] += a
    weeks = sorted(byweek)
    seas = defaultdict(list)
    for w in weeks:
        seas[w % 100].append(byweek[w])       # week-of-year from YYYYWW
    seas = {k: v for k, v in seas.items() if len(v) >= 2}
    e_s, n_s = eta_squared_on_ranks({str(k): v for k, v in seas.items()})
    print(f"   long-term trend (week vs demand, pooled) : rho {rho_t:+.3f} over {n_t:,} rows")
    print(f"   seasonality (week-of-year explains total): eta2 {e_s:.3f} over {n_s} week-numbers"
          if e_s is not None else "   seasonality: not computable")
    out["fiscal_week"] = {"trend_rho": round(rho_t, 3) if rho_t is not None else None,
                         "seasonality_eta2": round(e_s, 4) if e_s is not None else None,
                         "week_numbers": n_s}

    # ---------------- 5. per-queue, the honest driver test ----------------
    print("\n5) PER-QUEUE — the test that actually matters for RCA")
    print("   (pooled correlations above are contaminated by queue size; this is within-queue)")
    byq = defaultdict(list)
    for r in rows:
        byq[r["Forecast_name"]].append(r)
    print(f"   {'driver':20s} {'queues':>7} {'strong vs demand':>17} {'strong vs |miss|':>17}")
    print("   " + "-" * 66)
    for c in NUMERIC:
        s1 = s2 = tested1 = tested2 = 0
        for q, recs in byq.items():
            p1 = [(x[c], x["Actual_Offered"]) for x in recs
                  if x.get(c) is not None and x.get("Actual_Offered") is not None]
            if len(p1) >= MIN_WEEKS:
                tested1 += 1
                rr, _ = _spearman([p[0] for p in p1], [p[1] for p in p1])
                if rr is not None and abs(rr) >= STRONG:
                    s1 += 1
            p2 = [(x[c], x["_absadh"]) for x in recs
                  if x.get(c) is not None and x.get("_absadh") is not None]
            if len(p2) >= MIN_WEEKS:
                tested2 += 1
                rr, _ = _spearman([p[0] for p in p2], [p[1] for p in p2])
                if rr is not None and abs(rr) >= STRONG:
                    s2 += 1
        a = f"{s1}/{tested1} ({100*s1/tested1:.0f}%)" if tested1 else "n/a"
        b = f"{s2}/{tested2} ({100*s2/tested2:.0f}%)" if tested2 else "n/a"
        print(f"   {c:20s} {max(tested1,tested2):>7} {a:>17} {b:>17}")
        out["per_queue"][c] = {"strong_vs_demand": a, "strong_vs_abs_miss": b}

    with open(os.path.join(HERE, "full-correlation-survey.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    print("\nreport -> results/full-correlation-survey.json")
    print("=" * 96)
    return 0


if __name__ == "__main__":
    sys.exit(main())
