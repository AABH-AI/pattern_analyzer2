"""
LLM ranking verification — the WFM engine must actually USE THE LLM.
====================================================================

Run:  cd backend && python ../results/run_llm_ranking.py

Purpose: `run_validation.py` proved the arithmetic. This proves the *model* ran and inspects
what it ranked. Every case here MUST return `investigation_meta.engine == "wfm-llm"`; a
deterministic fallback is recorded as a FAILURE of this run, not quietly accepted.

Provider: NVIDIA. Groq's daily quota (100,000 tokens) was exhausted by the day's testing, and
NVIDIA reasoning models need more than the original hard-coded 100s — hence the configurable
`llm.timeout_seconds` now read by `wfm/llm_client.py`.

For each queue it records what the model ranked, then checks the ranking against the
deterministic evidence the model was given:

  L1  engine == wfm-llm                    (the model genuinely answered)
  L2  ranked causes >= 1, ordered by rank
  L3  confidence_pct descending             (rank 1 is the most confident)
  L4  confidence_level matches its band     (High >=70, Medium >=40, Low <40)
  L5  every shipped cause_type satisfies its precondition
  L6  when the ladder says inherited_from, the model ranked inherited_from_higher_level
  L7  when data_quality.suspect, the model ranked data_quality_issue FIRST
  L8  no banned statistics vocabulary in business-facing text
  L9  every cause carries an action and a status
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE + "/../backend")
sys.path.insert(0, HERE)
from run_validation import BANNED, build_bundle, http_json, log   # noqa: E402
from sql_backend import connect, load_config                      # noqa: E402
from wfm import skeptic                                           # noqa: E402
from wfm.common import confidence_level                           # noqa: E402

BASE = "http://localhost:9000"
BAND = 10.0
PROVIDER = "nvidia"
MODEL = "nvidia/nemotron-3-super-120b-a12b"
PACE = 10


def pick_queues(cur, table):
    """Three deliberately different situations, so the ranking has something to distinguish."""
    out = []

    # 1. the known data-quality outlier -> data_quality_issue must come FIRST
    cur.execute(f"SELECT Forecast_name,Fiscal_Week,Region,SubRegion,Country,channel FROM {table} "
                f"WHERE Forecast_name='NA Core Spanish' AND Fiscal_Week=202719")
    r = cur.fetchone()
    if r:
        out.append(("data-quality outlier", r))

    # 2. both ASU columns + big miss -> the decomposition is available to reason from
    cur.execute(f"SELECT TOP 1 Forecast_name,Fiscal_Week,Region,SubRegion,Country,channel FROM {table} "
                f"WHERE Planned_ASU IS NOT NULL AND Planned_ASU<>0 AND Actual_ASU IS NOT NULL "
                f"AND Actual_ASU<>0 AND fcst_offered>50 AND Actual_Offered IS NOT NULL "
                f"AND ABS(1.0-Actual_Offered/fcst_offered)*100>30 ORDER BY Fiscal_Week DESC, Forecast_name")
    r = cur.fetchone()
    if r:
        out.append(("ASU decomposition available", r))

    # 3. chronic bias, modest miss -> a different cause family entirely
    cur.execute(f"SELECT TOP 1 Forecast_name,Fiscal_Week,Region,SubRegion,Country,channel FROM {table} "
                f"WHERE fcst_offered>200 AND Actual_Offered IS NOT NULL "
                f"AND ABS(1.0-Actual_Offered/fcst_offered)*100 BETWEEN 12 AND 25 "
                f"ORDER BY Fiscal_Week DESC, Forecast_name")
    r = cur.fetchone()
    if r:
        out.append(("moderate miss, high volume", r))
    return out


def check_ranking(resp):
    checks = []

    def add(cid, name, ok, detail=""):
        checks.append({"id": cid, "check": name, "pass": bool(ok), "detail": detail})

    meta = resp.get("investigation_meta") or {}
    df = resp.get("derived_features") or {}
    causes = resp.get("ranked_root_causes") or []

    engine = meta.get("engine")
    add("L1", "engine == wfm-llm (the model actually answered)", engine == "wfm-llm",
        f"engine={engine} provider={meta.get('provider')} model={meta.get('model')}")

    add("L2", "at least one ranked cause, ranks sequential",
        bool(causes) and [c["rank"] for c in causes] == list(range(1, len(causes) + 1)),
        f"{len(causes)} causes, ranks={[c.get('rank') for c in causes]}")

    pcts = [c.get("confidence_pct") or 0 for c in causes]
    add("L3", "confidence descends with rank", pcts == sorted(pcts, reverse=True),
        f"confidences={pcts}")

    bad_level = [(c.get("confidence_pct"), c.get("confidence_level")) for c in causes
                 if c.get("confidence_level") != confidence_level(c.get("confidence_pct") or 0)]
    add("L4", "confidence_level matches its band", not bad_level, f"mismatched={bad_level}")

    unsupported = []
    for c in causes:
        ct = (c.get("cause_type") or "").strip()
        if ct in skeptic.PRECONDITIONS:
            pred, why = skeptic.PRECONDITIONS[ct]
            try:
                if not pred(df):
                    unsupported.append({"cause_type": ct, "unmet": why})
            except Exception as e:
                unsupported.append({"cause_type": ct, "error": str(e)})
    add("L5", "every shipped cause_type satisfies its precondition", not unsupported,
        json.dumps(unsupported))

    inherited = (df.get("investigation_ladder") or {}).get("inherited_from")
    types = [(c.get("cause_type") or "") for c in causes]
    if inherited:
        add("L6", f"ladder says inherited from {inherited} -> model ranked it",
            "inherited_from_higher_level" in types, f"types={types}")
    else:
        add("L6", "ladder reports no inheritance (nothing to rank)", True, "not applicable")

    if (df.get("data_quality") or {}).get("suspect"):
        add("L7", "data_quality.suspect -> data_quality_issue ranked FIRST",
            bool(types) and types[0] == "data_quality_issue", f"first={types[0] if types else None}")
    else:
        add("L7", "value not suspect (nothing to rank first)", True, "not applicable")

    texts = [resp.get("executive_summary", ""), resp.get("business_impact", "")]
    for c in causes:
        texts += [str(c.get("title", "")), str(c.get("explanation", "")),
                  str(c.get("business_impact", "")), str(c.get("recommended_action", ""))]
    hits = sorted({w for w in BANNED for t in texts if w in t.lower()})
    add("L8", "no banned statistics vocabulary", not hits, f"hits={hits}")

    incomplete = [c.get("cause_type") for c in causes
                  if not (c.get("recommended_action") or "").strip() or not (c.get("status") or "").strip()]
    add("L9", "every cause carries an action and a status", not incomplete,
        f"incomplete={incomplete}")
    return checks


def main():
    started = datetime.now(timezone.utc)
    cfg = load_config()
    table = cfg["sql"]["table"]
    log("=" * 78)
    log("LLM RANKING VERIFICATION -- the engine MUST use the LLM")
    log(f"started (UTC) : {started.isoformat()}")
    log(f"provider/model: {PROVIDER} / {MODEL}")
    log(f"llm timeout   : {cfg.get('llm', {}).get('timeout_seconds')}s (configurable; was hard-coded 100)")
    log("=" * 78)
    log(f"\n[0] health -> {json.dumps(http_json(f'{BASE}/api/health'))}")

    conn = connect(cfg)
    cur = conn.cursor()
    queues = pick_queues(cur, table)
    log(f"[0] {len(queues)} queues selected\n")

    out, first = [], True
    for why, r in queues:
        name, week, region, subregion, country, channel = r
        log("-" * 78)
        log(f"{name}  FW{week}   [{why}]")
        if not first:
            time.sleep(PACE)
        first = False
        qs = urllib.parse.urlencode({"forecast_name": name, "fiscal_week": week, "region": region or "",
                                     "subregion": subregion or "", "country": country or "",
                                     "channel": channel or "", "history_cap": 13, "peers_cap": 15})
        qc = http_json(f"{BASE}/api/queue-context?{qs}")
        bundle = build_bundle(qc)
        t0 = time.time()
        try:
            resp = http_json(f"{BASE}/api/rca-investigate?mode=wfm&provider={PROVIDER}"
                             f"&model={urllib.parse.quote(MODEL)}", bundle, timeout=320, attempts=2)
        except Exception as e:
            log(f"  investigate FAILED -> {e}")
            out.append({"queue": name, "fiscal_week": str(week), "error": str(e), "checks": []})
            continue
        elapsed = time.time() - t0
        meta = resp.get("investigation_meta") or {}
        log(f"  engine={meta.get('engine')}  model={meta.get('model')}  {elapsed:.1f}s")
        log(f"  adherence={(resp.get('kpi_status') or {}).get('adherence_pct')}%")
        log(f"  EXEC: {(resp.get('executive_summary') or '')[:200]}")
        for c in (resp.get("ranked_root_causes") or []):
            log(f"    #{c['rank']} [{c['confidence_pct']}% {c['confidence_level']}] {c['status']}")
            log(f"        {c.get('cause_type')} :: {c.get('title')}")
            log(f"        action: {str(c.get('recommended_action'))[:110]}")
        rej = [s for s in (resp.get("skeptic_review") or []) if s.get("verdict") == "rejected"]
        log(f"    skeptic: {len(resp.get('skeptic_review') or [])} entries, {len(rej)} rejected")

        fn = f"llm-{name.replace(' ', '_').replace('/', '-')}-FW{week}.json"
        with open(os.path.join(HERE, fn), "w", encoding="utf-8") as fh:
            json.dump(resp, fh, indent=1, default=str)

        checks = check_ranking(resp)
        for ck in checks:
            log(f"      {'PASS' if ck['pass'] else 'FAIL'}  {ck['id']}  {ck['check']}"
                + ("" if ck["pass"] else f"   [{ck['detail']}]"))
        out.append({"queue": name, "fiscal_week": str(week), "selected_because": why,
                    "engine": meta.get("engine"), "provider": meta.get("provider"),
                    "model": meta.get("model"), "seconds": round(elapsed, 1),
                    "adherence_pct": (resp.get("kpi_status") or {}).get("adherence_pct"),
                    "executive_summary": resp.get("executive_summary"),
                    "ranked_causes": resp.get("ranked_root_causes"),
                    "skeptic_review": resp.get("skeptic_review"),
                    "checks": checks, "raw_file": fn})
        log("")
    conn.close()

    total = sum(len(c["checks"]) for c in out)
    passed = sum(1 for c in out for k in c["checks"] if k["pass"])
    llm_runs = sum(1 for c in out if c.get("engine") == "wfm-llm")
    report = {"run": {"started_utc": started.isoformat(),
                      "finished_utc": datetime.now(timezone.utc).isoformat(),
                      "provider": PROVIDER, "model": MODEL,
                      "llm_timeout_seconds": cfg.get("llm", {}).get("timeout_seconds"),
                      "purpose": "verify the engine uses the LLM and that its ranking is sound"},
              "totals": {"queues": len(out), "llm_answered": llm_runs,
                         "checks": total, "passed": passed, "failed": total - passed},
              "queues": out}
    with open(os.path.join(HERE, "llm-ranking-report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1, default=str)
    log("=" * 78)
    log(f"LLM answered on {llm_runs}/{len(out)} queues;  {passed}/{total} ranking checks passed")
    log("report -> results/llm-ranking-report.json")
    log("=" * 78)


if __name__ == "__main__":
    main()
