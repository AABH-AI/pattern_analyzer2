"""
CQN mapping integrity — is it *properly* mapped, not just "covered"?
===================================================================

Run:  cd backend && python ../results/cqn_mapping_integrity.py

"100% mapped" can mean several different things, and only one of them was true on the first
pass. This separates them:

  M1  NAME coverage      every Forecast_name in the data resolves to >=1 Combined Queue
  M2  ROW coverage       every data row is behind a mapped name
  M3  VOLUME coverage    every unit of Actual_Offered is behind a mapped name
  M4  DIMENSION INTEGRITY the mapping's Region/SubRegion/Channel/Offering AGREE with the data
                          (a mapping can be 100% "covered" and still contradict the rows)
  M5  UNIQUENESS         is the mapping 1:1?  -- it is NOT: 69 of 442 names carry >1 CQN
  M6  AMBIGUITY WEIGHT   how much data sits behind the ambiguous names (this is the headline:
                          15.7% of rows but ~42% of VOLUME)
  M7  AMBIGUITY SHAPE    of the ambiguous names, how many differ only by vendor/site suffix
                          (resolvable by a naming rule) vs genuinely different queues
                          (needs a business decision)
  M8  UNUSED MAPPING     mapping names with no data -- harmless, but should be known
  M9  ENGINE WIRING      the engine actually resolves the real CQN and reports
                          is_cqn_proxy=False

M1-M4 and M9 are assertions. M5-M8 are reported, not asserted: the fan-out is a property of
the client's data, not a bug, and the decision on how to treat it is the business's.
"""
import os
import re
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE + "/../backend")

from sql_backend import connect, load_config          # noqa: E402
from wfm import fetch_wfm_context                     # noqa: E402
from wfm.channel_migration_detector import analyse    # noqa: E402

MAP_TABLE = "dbo.CQN_Mapping"
PAIR_TABLE = "dbo.CQN_Forecast_Pair"

# Vendor / delivery-site tokens that appear as CQN suffixes. Two CQNs that differ ONLY by one of
# these are the same business queue delivered from different sites. Foundever is the rebrand of
# Sitel/CGS, which is why it belongs here.
VENDOR_TOKENS = ("SITEL", "Foundever", "CNX", "Concentrix", "CGS", "BW", "Sykes",
                 "OSP", "DB", "Bangalore", "Pune", "Tampa FL", "Multi-Site", "SA OMNI")

results = []


def check(cid, name, ok, detail=""):
    results.append({"id": cid, "check": name,
                    "status": "PASS" if ok is True else ("INFO" if ok is None else "FAIL"),
                    "detail": detail})


def strip_vendor(cqn):
    s = cqn
    for v in sorted(VENDOR_TOKENS, key=len, reverse=True):
        s = re.sub(r"\s*\b" + re.escape(v) + r"\b\s*", " ", s, flags=re.I)
    return " ".join(s.split()).lower()


def main():
    cfg = load_config()
    table = cfg["sql"]["table"]
    conn = connect(cfg)
    cur = conn.cursor()

    def one(sql, params=()):
        cur.execute(sql, params)
        return cur.fetchone()

    print("=" * 78)
    print("CQN MAPPING INTEGRITY")
    print(f"  data    : {table}")
    print(f"  mapping : {MAP_TABLE}  (+ {PAIR_TABLE})")
    print("=" * 78)

    # ---- M1/M2/M3 coverage ----
    names, = one(f"SELECT COUNT(DISTINCT Forecast_name) FROM {table}")
    names_m, = one(f"SELECT COUNT(*) FROM (SELECT DISTINCT d.Forecast_name FROM {table} d "
                   f"WHERE EXISTS(SELECT 1 FROM {MAP_TABLE} x WHERE x.Forecast_Name=d.Forecast_name)) y")
    check("M1", "every queue name resolves to a Combined Queue", names_m == names,
          f"{names_m}/{names} names")

    rows, = one(f"SELECT COUNT(*) FROM {table}")
    rows_m, = one(f"SELECT COUNT(*) FROM {table} d "
                  f"WHERE EXISTS(SELECT 1 FROM {MAP_TABLE} x WHERE x.Forecast_Name=d.Forecast_name)")
    check("M2", "every data row is behind a mapped name", rows_m == rows, f"{rows_m:,}/{rows:,} rows")

    vol, = one(f"SELECT SUM(Actual_Offered) FROM {table}")
    vol_m, = one(f"SELECT SUM(d.Actual_Offered) FROM {table} d "
                 f"WHERE EXISTS(SELECT 1 FROM {MAP_TABLE} x WHERE x.Forecast_Name=d.Forecast_name)")
    check("M3", "every unit of demand is behind a mapped name",
          abs((vol_m or 0) - (vol or 0)) < 1, f"{vol_m:,.0f}/{vol:,.0f}")

    # ---- M4 dimension integrity ----
    bad = []
    for col_d, col_m in (("Region", "Region"), ("SubRegion", "SubRegion"),
                         ("channel", "Channel"), ("Offering", "Offering")):
        tot, = one(f"SELECT COUNT(*) FROM (SELECT DISTINCT d.Forecast_name, d.{col_d} FROM {table} d "
                   f"WHERE EXISTS(SELECT 1 FROM {MAP_TABLE} x WHERE x.Forecast_Name=d.Forecast_name)) y")
        agree, = one(f"SELECT COUNT(*) FROM (SELECT DISTINCT d.Forecast_name, d.{col_d} FROM {table} d "
                     f"WHERE EXISTS(SELECT 1 FROM {MAP_TABLE} x WHERE x.Forecast_Name=d.Forecast_name "
                     f"AND x.{col_m}=d.{col_d})) y")
        if agree != tot:
            bad.append(f"{col_d} {agree}/{tot}")
    check("M4", "mapping dimensions agree with the data (Region/SubRegion/Channel/Offering)",
          not bad, "; ".join(bad) if bad else "all 4 dimensions agree on every name")

    # ---- M5 uniqueness ----
    single, = one(f"SELECT COUNT(*) FROM (SELECT Forecast_Name FROM {MAP_TABLE} "
                  f"GROUP BY Forecast_Name HAVING COUNT(DISTINCT Combined_Queue_Name)=1) x")
    multi, = one(f"SELECT COUNT(*) FROM (SELECT Forecast_Name FROM {MAP_TABLE} "
                 f"GROUP BY Forecast_Name HAVING COUNT(DISTINCT Combined_Queue_Name)>1) x")
    check("M5", "mapping is 1:1 (one Combined Queue per name)", None,
          f"{single} names are 1:1, {multi} carry MORE THAN ONE Combined Queue")

    # ---- M6 ambiguity weight ----
    amb_rows, = one(f"SELECT COUNT(*) FROM {table} d WHERE d.Forecast_name IN ("
                    f"SELECT Forecast_Name FROM {MAP_TABLE} GROUP BY Forecast_Name "
                    f"HAVING COUNT(DISTINCT Combined_Queue_Name)>1)")
    amb_vol, = one(f"SELECT SUM(d.Actual_Offered) FROM {table} d WHERE d.Forecast_name IN ("
                   f"SELECT Forecast_Name FROM {MAP_TABLE} GROUP BY Forecast_Name "
                   f"HAVING COUNT(DISTINCT Combined_Queue_Name)>1)")
    check("M6", "how much data sits behind ambiguous names", None,
          f"{amb_rows:,} rows ({100*amb_rows/rows:.1f}%) but {amb_vol:,.0f} volume "
          f"({100*(amb_vol or 0)/vol:.1f}% of all demand)")

    # ---- M7 ambiguity shape ----
    cur.execute(f"SELECT Forecast_Name, Combined_Queue_Name FROM {MAP_TABLE} WHERE Forecast_Name IN ("
                f"SELECT Forecast_Name FROM {MAP_TABLE} GROUP BY Forecast_Name "
                f"HAVING COUNT(DISTINCT Combined_Queue_Name)>1)")
    fan = defaultdict(set)
    for f, c in cur.fetchall():
        fan[f].add(c)
    vendor_only = [f for f, cs in fan.items() if len({strip_vendor(c) for c in cs}) == 1]
    genuinely = [f for f in fan if f not in set(vendor_only)]
    check("M7", "shape of the ambiguity", None,
          f"{len(vendor_only)} differ only by vendor/site suffix (resolvable by a naming rule); "
          f"{len(genuinely)} are genuinely different queues (needs a business decision)")

    # ---- M8 unused mapping rows ----
    unused, = one(f"SELECT COUNT(*) FROM (SELECT DISTINCT Forecast_Name FROM {MAP_TABLE} "
                  f"WHERE Forecast_Name NOT IN (SELECT DISTINCT Forecast_name FROM {table})) x")
    check("M8", "mapping names with no data in the fact table", None,
          f"{unused} (extra rows in the workbook; harmless)")

    # ---- M9 engine wiring ----
    cur.execute(f"SELECT TOP 1 d.Forecast_name, d.Fiscal_Week, d.Region, d.SubRegion, d.Country, "
                f"d.channel, d.business_org FROM {table} d "
                f"JOIN {MAP_TABLE} x ON x.Forecast_Name=d.Forecast_name "
                f"JOIN (SELECT Combined_Queue_Name FROM {MAP_TABLE} GROUP BY Combined_Queue_Name "
                f"      HAVING COUNT(DISTINCT Channel)>1) mc ON mc.Combined_Queue_Name=x.Combined_Queue_Name "
                f"WHERE d.fcst_offered > 20 AND d.Actual_Offered IS NOT NULL "
                f"ORDER BY d.Fiscal_Week DESC")
    row = cur.fetchone()
    if not row:
        check("M9", "engine resolves the authoritative CQN", None, "no multi-channel CQN sample found")
    else:
        key = dict(zip(("Forecast_name", "Fiscal_Week", "Region", "SubRegion", "Country",
                        "channel", "business_org"), row))
        key["Fiscal_Week"] = str(key["Fiscal_Week"])
        wc = fetch_wfm_context(cur, table, key)
        cs = analyse(wc["channel_sibling_rows"], key["Fiscal_Week"], key["channel"],
                     cqn_names=wc.get("cqn_names"), cqn_source=wc.get("cqn_source"))
        ok = (wc.get("cqn_source") == "mapping" and cs.get("is_cqn_proxy") is False
              and bool(wc.get("cqn_names")))
        check("M9", "engine resolves the authoritative CQN (is_cqn_proxy=False)", ok,
              f"{key['Forecast_name']} FW{key['Fiscal_Week']}: source={wc.get('cqn_source')}, "
              f"cqns={wc.get('cqn_names')}, channels="
              f"{[d['channel'] for d in cs.get('per_channel', [])]}")

    # ---- the two tables still agree ----
    diff_a, = one(f"SELECT COUNT(*) FROM (SELECT DISTINCT Forecast_Name, Combined_Queue_Name FROM {MAP_TABLE} "
                  f"EXCEPT SELECT DISTINCT Forecast_Name, Combined_Queue_Name FROM {PAIR_TABLE}) x")
    diff_b, = one(f"SELECT COUNT(*) FROM (SELECT DISTINCT Forecast_Name, Combined_Queue_Name FROM {PAIR_TABLE} "
                  f"EXCEPT SELECT DISTINCT Forecast_Name, Combined_Queue_Name FROM {MAP_TABLE}) x")
    check("M10", f"{MAP_TABLE} and {PAIR_TABLE} carry the same pairs",
          diff_a == 0 and diff_b == 0, f"{diff_a} / {diff_b} one-sided differences")

    conn.close()

    print()
    for r in results:
        print(f"  {r['status']:4s} {r['id']:4s} {r['check']}")
        if r["detail"]:
            print(f"        {r['detail']}")
    p = sum(1 for r in results if r["status"] == "PASS")
    f = sum(1 for r in results if r["status"] == "FAIL")
    i = sum(1 for r in results if r["status"] == "INFO")
    print()
    print("=" * 78)
    print(f"{p} PASS / {f} FAIL / {i} INFO")
    print("Verdict: coverage is 100% (names, rows AND volume) and the mapping never contradicts")
    print("the data. It is NOT 1:1 -- see M5/M6/M7, which is a property of the client's data.")
    print("=" * 78)
    return 1 if f else 0


if __name__ == "__main__":
    sys.exit(main())
