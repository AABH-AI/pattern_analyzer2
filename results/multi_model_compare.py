"""
Multi-model comparison — do different models agree on the root cause?
=====================================================================

Run:  cd backend && python ../results/multi_model_compare.py

Runs the SAME queue through several models and diffs their rankings. This answers a question
none of the other suites do: is the verdict a property of the *evidence*, or of the *model*?

Agreement on the top cause_type is the useful signal. It is NOT proof of correctness — all the
models see the same deterministic feature block, so they can agree and still be wrong together.
But disagreement is a red flag worth reading.

Every model is also re-checked against the deterministic evidence, so a model that "agrees"
while citing an unsupported cause is caught rather than counted.
"""
import json
import os
import sys
import time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE + "/../backend")
sys.path.insert(0, HERE)

from sql_backend import connect, load_config                 # noqa: E402
from wfm import fetch_wfm_context, investigate_wfm           # noqa: E402
from wfm import skeptic                                      # noqa: E402
from run_validation import build_bundle                      # noqa: E402

BAND = 10.0
MODELS = [
    ("nvidia", "nvidia/nemotron-3-super-120b-a12b"),
    ("groq", "llama-3.3-70b-versatile"),
    ("nvidia", "nvidia/llama-3.3-nemotron-super-49b-v1.5"),
]
PACE = 6


def pick_queue(cur, table):
    """A queue whose CQN spans channels AND that breaches the band, so every feature block has
    something to say."""
    cur.execute(f"""SELECT TOP 1 d.Forecast_name, d.Fiscal_Week, d.Region, d.SubRegion, d.Country,
                           d.channel, d.business_org
        FROM {table} d
        JOIN dbo.CQN_Mapping x ON x.Forecast_Name = d.Forecast_name
        JOIN (SELECT Combined_Queue_Name FROM dbo.CQN_Mapping
               GROUP BY Combined_Queue_Name HAVING COUNT(DISTINCT Channel) > 1) mc
          ON mc.Combined_Queue_Name = x.Combined_Queue_Name
       WHERE d.fcst_offered > 50 AND d.Actual_Offered IS NOT NULL
         AND ABS(1.0 - d.Actual_Offered/d.fcst_offered)*100 > 20
       ORDER BY d.Fiscal_Week DESC, d.Forecast_name""")
    return cur.fetchone()


def main():
    cfg = load_config()
    table = cfg["sql"]["table"]
    conn = connect(cfg)
    cur = conn.cursor()

    row = pick_queue(cur, table)
    if not row:
        print("no suitable queue found")
        return 2
    name, week, region, sub, country, chan, org = row
    key = {"Forecast_name": name, "Fiscal_Week": str(week), "Region": region, "SubRegion": sub,
           "Country": country, "channel": chan, "business_org": org}

    print("=" * 78)
    print("MULTI-MODEL COMPARISON — same queue, same evidence, different models")
    print(f"  queue : {name}  FW{week}")
    print(f"  scope : {region} / {sub} / {country} / {chan} / {org}")
    print("=" * 78)

    wc = fetch_wfm_context(cur, table, key)
    cur.execute(f"SELECT * FROM {table} WHERE Forecast_name=? AND Fiscal_Week=?", (name, week))
    cols = [d[0] for d in cur.description]
    target = dict(zip(cols, cur.fetchone()))
    cur.execute(f"SELECT TOP 13 * FROM {table} WHERE Forecast_name=? AND Fiscal_Week<? "
                f"ORDER BY Fiscal_Week DESC", (name, week))
    hist = [dict(zip(cols, r)) for r in cur.fetchall()][::-1]
    cur.execute(f"SELECT TOP 15 * FROM {table} WHERE Fiscal_Week=? AND Region=? AND SubRegion=? "
                f"AND Country=? AND channel=? AND Forecast_name<>?",
                (week, region, sub, country, chan, name))
    peers = [dict(zip(cols, r)) for r in cur.fetchall()]
    bundle = build_bundle({"target_row": target, "history_rows": hist, "peer_rows": peers})

    print(f"\n  CQN(s) resolved : {wc.get('cqn_names')}  (source={wc.get('cqn_source')})")
    print(f"  adherence       : {bundle['target']['computed']['adherence_pct']:.1f}%")

    runs, first = [], True
    for provider, model in MODELS:
        if not first:
            time.sleep(PACE)
        first = False
        print("\n" + "-" * 78)
        print(f"{provider} / {model}")
        t0 = time.time()
        resp = investigate_wfm(bundle, cfg.get("llm", {}), wc,
                               model_choice={"provider": provider, "model": model}, band=BAND)
        el = time.time() - t0
        meta = resp.get("investigation_meta") or {}
        causes = resp.get("ranked_root_causes") or []
        engine = meta.get("engine")
        print(f"  engine={engine}  {el:.1f}s  causes={len(causes)}")
        if engine != "wfm-llm":
            print(f"  !! {(resp.get('missing_information') or ['?'])[0][:170]}")
        for c in causes:
            print(f"    #{c['rank']} [{c['confidence_pct']}% {c['confidence_level']}] "
                  f"{c['status']} :: {c.get('cause_type')}")
            print(f"        {c.get('title')}")
        # every shipped cause must still satisfy its precondition
        df = resp.get("derived_features") or {}
        unsupported = []
        for c in causes:
            ct = (c.get("cause_type") or "").strip()
            if ct in skeptic.PRECONDITIONS:
                pred, why = skeptic.PRECONDITIONS[ct]
                try:
                    if not pred(df):
                        unsupported.append(ct)
                except Exception:
                    pass
        print(f"    evidence-supported: {'YES' if not unsupported else 'NO -> ' + str(unsupported)}")
        print(f"    exec: {(resp.get('executive_summary') or '')[:150]}")
        runs.append({"provider": provider, "model": model, "engine": engine,
                     "seconds": round(el, 1),
                     "top_cause_type": (causes[0].get("cause_type") if causes else None),
                     "top_confidence": (causes[0].get("confidence_pct") if causes else None),
                     "all_cause_types": [c.get("cause_type") for c in causes],
                     "unsupported": unsupported,
                     "executive_summary": resp.get("executive_summary")})

    conn.close()

    llm_runs = [r for r in runs if r["engine"] == "wfm-llm"]
    tops = [r["top_cause_type"] for r in llm_runs if r["top_cause_type"]]
    counts = Counter(tops)
    print("\n" + "=" * 78)
    print("AGREEMENT")
    print(f"  models that answered on the LLM : {len(llm_runs)}/{len(runs)}")
    for ct, n in counts.most_common():
        print(f"    top cause '{ct}': {n} of {len(tops)} model(s)")
    consensus = bool(counts) and counts.most_common(1)[0][1] == len(tops) and len(tops) > 1
    print(f"  unanimous on the top cause      : {consensus}")
    bad = [r["model"] for r in runs if r["unsupported"]]
    print(f"  models shipping an unsupported cause: {bad or 'none'}")
    print("=" * 78)

    with open(os.path.join(HERE, "multi-model-report.json"), "w", encoding="utf-8") as fh:
        json.dump({"queue": {"Forecast_name": name, "Fiscal_Week": str(week),
                             "cqn_names": wc.get("cqn_names"), "cqn_source": wc.get("cqn_source")},
                   "agreement": {"llm_answered": len(llm_runs), "top_cause_counts": dict(counts),
                                 "unanimous": consensus},
                   "runs": runs}, fh, indent=1, default=str)
    print("report -> results/multi-model-report.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
