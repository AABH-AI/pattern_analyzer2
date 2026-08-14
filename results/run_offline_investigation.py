"""
Run the REAL WFM engine against the offline mirror -- no VPN, no fabrication.
=============================================================================

    cd backend && python ../results/run_offline_investigation.py --queue "SA Indonesia Client Basic" --week 202716
    cd backend && python ../results/run_offline_investigation.py --worst 5      # biggest breaches
    cd backend && python ../results/run_offline_investigation.py --llm          # also call the model

Everything except the SQL host is the production path: `data_access.fetch_wfm_context` runs its own
queries through the T-SQL shim in offline_source.py, `derive_wfm_features` builds every block, and
`rca_decision.decide` makes the call. With `--llm` the configured provider is used too, because the
model APIs are on the public internet and do not need the VPN -- only SQL does.

What this canNOT do: prove production behaviour. The mirror is a local spreadsheet extract and
`dbo.CQN_Mapping` does not exist locally, so channel grouping falls back to the locality proxy.
Live SQL validation is still required and is reported as blocked until it runs.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, HERE)

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

import offline_source                                              # noqa: E402
from wfm.data_access import fetch_wfm_context                      # noqa: E402
from wfm.investigation_engine import derive_wfm_features, investigate_wfm   # noqa: E402

BAND = 10.0
FIELDS = ("Fiscal_Week", "Week_Ending", "Region", "SubRegion", "Country", "Forecast_name",
          "Forecaster", "Offering", "Projection_plan_name", "channel", "business_org",
          "Actual_Offered", "Actual_Handled", "fcst_offered", "fcst_handled", "Planned_ASU",
          "Actual_ASU", "Final_Units", "Final_Y5", "Final_Y4", "Final_Y3", "Final_Y2", "Final_Y1",
          "Final_upp_units", "Holiday_Count", "Monday", "Tuesday", "Wednesday", "Thursday",
          "Friday", "Saturday", "Sunday", "Volume_Category")


def row_to_dict(cur, row):
    return {d[0]: v for d, v in zip(cur.description, row)}


def adherence(actual, forecast):
    if actual is None or not forecast:
        return None
    return (1.0 - actual / forecast) * 100.0


def build_bundle(cur, table, name, week, history_cap=13, peers_cap=15):
    """The context bundle the console builds client-side, rebuilt from the mirror."""
    cols = ", ".join(f'"{c}"' for c in FIELDS)
    cur.execute(f'SELECT {cols} FROM "{table}" WHERE Forecast_name=? AND Fiscal_Week=?',
                (name, week))
    row = cur.fetchone()
    if row is None:
        raise SystemExit(f"no row for {name!r} at FW{week} in the offline mirror")
    target = row_to_dict(cur, row)

    cur.execute(f'SELECT {cols} FROM "{table}" WHERE Forecast_name=? AND Fiscal_Week<? '
                f'ORDER BY Fiscal_Week DESC LIMIT {int(history_cap)}', (name, week))
    hist = [row_to_dict(cur, r) for r in cur.fetchall()][::-1]

    cur.execute(f'SELECT {cols} FROM "{table}" WHERE Fiscal_Week=? AND Forecast_name<>? '
                f'AND IFNULL(Region,\'\')=IFNULL(?,\'\') AND IFNULL(Country,\'\')=IFNULL(?,\'\') '
                f'AND IFNULL(channel,\'\')=IFNULL(?,\'\') LIMIT {int(peers_cap)}',
                (week, name, target.get("Region"), target.get("Country"), target.get("channel")))
    peers = [row_to_dict(cur, r) for r in cur.fetchall()]

    def entry(r):
        a, f = r.get("Actual_Offered"), r.get("fcst_offered")
        adh = adherence(a, f)
        return {"key": {"Forecast_name": r.get("Forecast_name"),
                        "Fiscal_Week": str(r.get("Fiscal_Week"))},
                "fields": r,
                "computed": {"forecast": f, "actual": a,
                             "error": (a - f) if (a is not None and f is not None) else None,
                             "adherence_pct": adh,
                             "direction": None if adh is None else ("under" if adh < 0 else "over"),
                             "severity": None if adh is None else abs(adh) / BAND}}

    def stat_summary(t, rows):
        numeric = {}
        keys = set(t["fields"])
        for h in rows:
            keys |= set(h["fields"])
        for k in sorted(keys):
            hv = [h["fields"].get(k) for h in rows]
            hv = [v for v in hv if isinstance(v, (int, float)) and not isinstance(v, bool)]
            tv = t["fields"].get(k)
            if not hv or not isinstance(tv, (int, float)) or isinstance(tv, bool):
                continue
            n = len(hv)
            mean = sum(hv) / n
            var = sum((v - mean) ** 2 for v in hv) / (n - 1) if n > 1 else None
            sd = var ** 0.5 if var else None
            numeric[k] = {"history_mean": mean, "history_stdev": sd, "target_value": tv,
                          "z_score": ((tv - mean) / sd) if sd else None, "n": n}
        return {"numeric": numeric, "categorical": {}}

    t = entry(target)
    h = [entry(r) for r in hist]
    slim = [{"key": e["key"], "computed": e["computed"]} for e in h]
    return {"meta": {"band_threshold": BAND, "schema_note": "results/run_offline_investigation.py"},
            "target": t, "history": slim,
            "peers": [{"key": e["key"], "computed": e["computed"]} for e in map(entry, peers)],
            "statistical_summary": stat_summary(t, h)}


def worst_breaches(cur, table, limit):
    cur.execute(
        f'SELECT Forecast_name, Fiscal_Week, Actual_Offered, fcst_offered '
        f'FROM "{table}" WHERE Actual_Offered IS NOT NULL AND fcst_offered IS NOT NULL '
        f'AND fcst_offered > 0 AND ABS(1.0 - Actual_Offered/fcst_offered)*100 > ? '
        f'ORDER BY ABS(Actual_Offered - fcst_offered) DESC LIMIT {int(limit)}', (BAND,))
    return cur.fetchall()


def summarise(name, week, decision, resp=None):
    print("=" * 100)
    print(f"{name}   FW{week}")
    print("=" * 100)
    print(f"  miss_category   : {decision.get('miss_category')}")
    print(f"                    {decision.get('miss_category_reason')}")
    print(f"  forecastability : {decision.get('forecastability')}")
    conf, crit = decision.get("confidence") or {}, decision.get("criticality") or {}
    print(f"  confidence      : {conf.get('level')} ({conf.get('score_pct')}%)   "
          f"criticality: {crit.get('level')}  [{crit.get('contacts_gap')} contacts, "
          f"{crit.get('gap_as_share_of_typical_week')} of a typical week]")
    print(f"\n  ROOT CAUSE: {decision.get('root_cause_sentence')}")
    print("\n  WHY THIS HAPPENED")
    for b in decision.get("why_bullets") or []:
        print(f"    {b['rank']}. [{b['evidence_class']}] {b['headline']}")
        print(f"       what   : {b.get('what_happened')}")
        print(f"       matters: {b.get('why_it_mattered')}")
        print(f"       mech   : {b.get('forecast_mechanism')}")
        print(f"       evidence: {', '.join(b.get('evidence_ids') or [])}  "
              f"resolution={b.get('resolution')}")
        for c in b.get("contradictions") or []:
            print(f"       CONTRA : {c}")
    if decision.get("rejected"):
        print("\n  REJECTED")
        for r in decision["rejected"]:
            print(f"    - {r['headline']}: {r['reason']}")
    if decision.get("limitations"):
        print("\n  LIMITATIONS")
        for lim in decision["limitations"]:
            print(f"    - {lim}")
    if resp is not None:
        meta = resp.get("investigation_meta") or {}
        print(f"\n  engine={meta.get('engine')} provider={meta.get('provider')} "
              f"model={meta.get('model')}")
        print(f"  executive_summary: {str(resp.get('executive_summary'))[:400]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", default="SA Indonesia Client Basic")
    ap.add_argument("--week", type=int, default=202716)
    ap.add_argument("--worst", type=int, default=0, help="instead, run the N biggest breaches")
    ap.add_argument("--llm", action="store_true", help="also call the configured model")
    ap.add_argument("--json", default="", help="write the full response to this path")
    args = ap.parse_args()

    conn = offline_source.connect()
    cur = conn.cursor()
    table = offline_source.TABLE

    cases = [(args.queue, args.week)]
    if args.worst:
        cases = [(r[0], int(r[1])) for r in worst_breaches(cur, table, args.worst)]

    llm_cfg = {}
    if args.llm:
        from sql_backend import load_config
        llm_cfg = (load_config() or {}).get("llm", {})

    for name, week in cases:
        bundle = build_bundle(cur, table, name, week)
        fields = bundle["target"]["fields"]
        key = {"Forecast_name": name, "Fiscal_Week": week, "Region": fields.get("Region"),
               "SubRegion": fields.get("SubRegion"), "Country": fields.get("Country"),
               "channel": fields.get("channel"), "business_org": fields.get("business_org"),
               "Offering": fields.get("Offering")}
        ctx = fetch_wfm_context(cur, table, key)

        if args.llm:
            resp = investigate_wfm(bundle, llm_cfg, ctx, band=BAND)
            decision = (resp.get("derived_features") or {}).get("decision") or {}
            summarise(name, week, decision, resp)
            if args.json:
                with open(args.json, "w", encoding="utf-8") as fh:
                    json.dump(resp, fh, indent=1, default=str)
                print(f"\n  written -> {args.json}")
        else:
            features, adh = derive_wfm_features(bundle, ctx, BAND)
            summarise(name, week, features.get("decision") or {})
            if args.json:
                with open(args.json, "w", encoding="utf-8") as fh:
                    json.dump(features.get("decision"), fh, indent=1, default=str)
                print(f"\n  written -> {args.json}")
        print()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
