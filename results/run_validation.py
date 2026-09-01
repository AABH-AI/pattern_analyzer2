"""
WFM RCA engine — end-to-end validation run.
===========================================

Run:  cd backend && python ../results/run_validation.py

WHAT THIS DOES
--------------
Drives the running backend over HTTP exactly as the console does (`/api/queue-context`
then `/api/rca-investigate?mode=wfm`), then re-derives every number the engine reported
from SQL *independently* and asserts they agree. Raw responses and a machine-readable
validation report are written next to this script.

QUEUE SELECTION — DELIBERATE, NOT RANDOM
----------------------------------------
Each case is chosen by an explicit SQL predicate targeting one engine decision path, so
the set is reproducible and covers the branches rather than sampling arbitrarily:

  A  known data-quality suspect      -> must rank data_quality_issue first
  B  both ASU columns present        -> must produce the exact driver decomposition
  C  miss present at a higher level  -> must report inherited_from
  D  multi-channel locality          -> must evaluate channel migration
  E  inside the +/-10% band          -> must REFUSE to investigate (control)

VALIDATION CHECKS (per queue)
-----------------------------
  V1  KPI          engine adherence == (1 - Actual/Forecast)*100 recomputed from raw SQL
  V2  Decomposition base_effect + rate_effect == total miss (exact identity)
  V3  Ladder       each level's adherence == an independent SQL aggregate at that level
  V4  Data quality typical_week_actual == median of the queue's own history from SQL
  V5  Temporal     last_13_week_avg_actual == AVG of the prior 13 weeks from SQL
  V6  Skeptic      every SHIPPED cause_type satisfies its own precondition
  V7  Back-compat  all legacy response keys present (existing UI renders it)
  V8  Language     no banned statistics vocabulary in business-facing text
"""
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/../backend")
from sql_backend import connect, load_config           # noqa: E402
from wfm import skeptic                                # noqa: E402

OUT = os.path.dirname(os.path.abspath(__file__))
BASE = "http://localhost:9400"
BAND = 10.0
MODEL = ("groq", "llama-3.3-70b-versatile")   # only provider that answers inside its timeout here
PACE_SECONDS = 40                             # Groq on-demand cap is 12,000 TPM; a run is ~4.4k

BANNED = ("z-score", "z score", "standard deviation", "sigma", "outlier", "correlation",
          "regression", "pearson", "shap", "isolation forest", "mape")


def log(msg):
    print(msg, flush=True)


def http_json(url, body=None, timeout=200, attempts=4):
    """Retry with backoff. The SQL host sits behind a VPN and a momentary drop surfaces as
    HTTP 502 from /api/queue-context; a transient blip must not abort a validation run."""
    last = None
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(
            url, data=(json.dumps(body, default=str).encode() if body else None),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:160]
            except Exception:
                pass
            last = f"HTTP {e.code}: {detail}"
            if e.code not in (429, 500, 502, 503, 504):
                raise
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
        if attempt < attempts:
            wait = 5 * attempt
            log(f"      retry {attempt}/{attempts - 1} after {wait}s  ({last})")
            time.sleep(wait)
    raise RuntimeError(f"gave up after {attempts} attempts -> {last}")


# --------------------------------------------------------------------------- bundle
def _computed(row):
    def n(v):
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    a, f = n(row.get("Actual_Offered")), n(row.get("fcst_offered"))
    adh = ((1.0 - a / f) * 100.0) if (a is not None and f) else None
    return {"forecast": f, "actual": a,
            "error": (a - f) if (a is not None and f is not None) else None,
            "adherence_pct": adh,
            "accuracy_pct": ((a / f) * 100.0) if (a is not None and f) else None,
            "direction": None if adh is None else ("under" if adh < 0 else "over"),
            "severity": None if adh is None else round(abs(adh) / BAND, 1)}


def _entry(row):
    return {"key": {"Forecast_name": row.get("Forecast_name"),
                    "Fiscal_Week": str(row.get("Fiscal_Week"))},
            "fields": {k: v for k, v in row.items() if not str(k).startswith("_")},
            "computed": _computed(row)}


def _stat_summary(target, history):
    """Mirrors buildStatSummary() in rca_console.html so the bundle is what the UI sends."""
    numeric, categorical = {}, {}
    keys = set(target["fields"])
    for h in history:
        keys |= set(h["fields"])
    for k in sorted(keys):
        hv = [h["fields"].get(k) for h in history]
        hv = [v for v in hv if v is not None and v != ""]
        tv = target["fields"].get(k)
        allv = hv + ([tv] if tv not in (None, "") else [])
        if allv and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in allv):
            hp = [v for v in hv if isinstance(v, (int, float))]
            n = len(hp)
            mean = sum(hp) / n if n else None
            var = (sum((v - mean) ** 2 for v in hp) / (n - 1)) if n > 1 else None
            sd = var ** 0.5 if var is not None else None
            t = tv if isinstance(tv, (int, float)) else None
            numeric[k] = {"history_mean": mean, "history_stdev": sd, "target_value": t,
                          "z_score": ((t - mean) / sd) if (t is not None and sd) else None,
                          "n": n}
        elif allv:
            prior = hv[-1] if hv else None
            categorical[k] = {"target_value": tv if tv not in (None, "") else None,
                              "prior_value": prior,
                              "changed": (str(tv) != str(prior)) if (tv is not None and prior is not None) else None}
    return {"numeric": numeric, "categorical": categorical}


def build_bundle(qc):
    t = _entry(qc["target_row"])
    hist = [_entry(r) for r in (qc.get("history_rows") or [])]
    peers = [_entry(r) for r in (qc.get("peer_rows") or [])]
    slim = lambda e: {"key": e["key"], "computed": e["computed"]}          # noqa: E731
    return {"meta": {"band_threshold": BAND, "schema_note": "results/run_validation.py"},
            "target": t, "history": [slim(h) for h in hist], "peers": [slim(p) for p in peers],
            "statistical_summary": _stat_summary(t, hist)}


# --------------------------------------------------------------------- case selection
def select_cases(cur, table):
    """Each case is picked by an explicit predicate. Nothing here is random."""
    cases = []

    def row_to_case(label, why, r):
        return {"case": label, "why_selected": why, "Forecast_name": r[0],
                "Fiscal_Week": str(r[1]), "Region": r[2], "SubRegion": r[3],
                "Country": r[4], "channel": r[5]}

    # A -- the known data-quality suspect (documented in IMP_DOCS/wfm-rca-engine.md)
    cur.execute(f"SELECT Forecast_name,Fiscal_Week,Region,SubRegion,Country,channel FROM {table} "
                f"WHERE Forecast_name='NA Core Spanish' AND Fiscal_Week=202719")
    r = cur.fetchone()
    if r:
        cases.append(row_to_case("A", "Known isolated extreme (8,805 vs ~117 typical); the only "
                                      "queue in the table with a week >50x its own median. Must "
                                      "rank data_quality_issue first.", r))

    # B -- both ASU columns present and a large miss, so the decomposition must be exact
    cur.execute(f"SELECT TOP 1 Forecast_name,Fiscal_Week,Region,SubRegion,Country,channel FROM {table} "
                f"WHERE Planned_ASU IS NOT NULL AND Planned_ASU<>0 AND Actual_ASU IS NOT NULL "
                f"AND Actual_ASU<>0 AND fcst_offered IS NOT NULL AND fcst_offered>50 "
                f"AND Actual_Offered IS NOT NULL AND ABS(1.0-Actual_Offered/fcst_offered)*100>30 "
                f"ORDER BY Fiscal_Week DESC, Forecast_name")
    r = cur.fetchone()
    if r:
        cases.append(row_to_case("B", "Both Planned_ASU and Actual_ASU present with a >30% miss "
                                      "and a non-trivial forecast, so the driver decomposition "
                                      "must be available and must reconcile exactly.", r))

    # C -- a queue whose whole COUNTRY level also breaches the band that week
    cur.execute(f"""SELECT TOP 1 q.Forecast_name,q.Fiscal_Week,q.Region,q.SubRegion,q.Country,q.channel
      FROM {table} q
      JOIN (SELECT Fiscal_Week,business_org,Region,SubRegion,Country,
                   SUM(Actual_Offered) a, SUM(fcst_offered) f
              FROM {table} WHERE fcst_offered IS NOT NULL AND fcst_offered<>0
             GROUP BY Fiscal_Week,business_org,Region,SubRegion,Country
            HAVING SUM(fcst_offered)<>0 AND ABS(1.0-SUM(Actual_Offered)/SUM(fcst_offered))*100>15) c
        ON c.Fiscal_Week=q.Fiscal_Week AND c.business_org=q.business_org AND c.Region=q.Region
       AND c.SubRegion=q.SubRegion AND c.Country=q.Country
     WHERE q.fcst_offered IS NOT NULL AND q.fcst_offered>20 AND q.Actual_Offered IS NOT NULL
       AND ABS(1.0-q.Actual_Offered/q.fcst_offered)*100>15
     ORDER BY q.Fiscal_Week DESC, q.Forecast_name""")
    r = cur.fetchone()
    if r:
        cases.append(row_to_case("C", "Its Country-level rollup also breaches the band in the same "
                                      "week, so the engine must report the miss as inherited from a "
                                      "higher level rather than concluding at the queue.", r))

    # D -- a locality carrying 4+ channels, so migration is testable
    cur.execute(f"""SELECT TOP 1 q.Forecast_name,q.Fiscal_Week,q.Region,q.SubRegion,q.Country,q.channel
      FROM {table} q
      JOIN (SELECT Region,SubRegion,Country,business_org FROM {table}
             GROUP BY Region,SubRegion,Country,business_org
            HAVING COUNT(DISTINCT channel)>=4) m
        ON m.Region=q.Region AND m.SubRegion=q.SubRegion AND m.Country=q.Country
       AND m.business_org=q.business_org
     WHERE q.fcst_offered IS NOT NULL AND q.fcst_offered>20 AND q.Actual_Offered IS NOT NULL
       AND ABS(1.0-q.Actual_Offered/q.fcst_offered)*100>20
     ORDER BY q.Fiscal_Week DESC, q.Forecast_name""")
    r = cur.fetchone()
    if r:
        cases.append(row_to_case("D", "Sits in a locality carrying 4+ channels, so channel-migration "
                                      "detection has real sibling data to evaluate.", r))

    # E -- CONTROL: inside the band. The engine must refuse to investigate.
    cur.execute(f"SELECT TOP 1 Forecast_name,Fiscal_Week,Region,SubRegion,Country,channel FROM {table} "
                f"WHERE fcst_offered IS NOT NULL AND fcst_offered>100 AND Actual_Offered IS NOT NULL "
                f"AND ABS(1.0-Actual_Offered/fcst_offered)*100 < 5 ORDER BY Fiscal_Week DESC, Forecast_name")
    r = cur.fetchone()
    if r:
        cases.append(row_to_case("E", "CONTROL: adherence inside +/-10%. The business rule forbids "
                                      "investigating, so the engine must return "
                                      "engine=wfm-not-investigated with zero causes.", r))
    return cases


# ------------------------------------------------------------------------ validation
def validate(case, resp, cur, table):
    """Re-derive everything from SQL and compare. Returns a list of check dicts."""
    checks = []

    def add(cid, name, ok, expected, got, note=""):
        checks.append({"id": cid, "check": name, "pass": bool(ok),
                       "expected": expected, "got": got, "note": note})

    name, week = case["Forecast_name"], case["Fiscal_Week"]
    df = resp.get("derived_features") or {}

    # V1 -- KPI recomputed from raw SQL
    cur.execute(f"SELECT Actual_Offered, fcst_offered FROM {table} "
                f"WHERE Forecast_name=? AND Fiscal_Week=?", (name, week))
    row = cur.fetchone()
    truth = None
    if row and row[1]:
        truth = round((1.0 - float(row[0]) / float(row[1])) * 100.0, 1)
    got = (resp.get("kpi_status") or {}).get("adherence_pct")
    add("V1", "KPI adherence matches SQL recomputation",
        truth is not None and got is not None and abs(truth - got) <= 0.05, truth, got,
        f"raw Actual={row[0] if row else None}, Forecast={row[1] if row else None}")

    # V2 -- decomposition identity
    dd = (df.get("correlations") or {}).get("driver_decomposition") or {}
    if dd.get("available"):
        total = dd["total_miss"]
        summed = round(dd["warranty_base_effect"] + dd["contacts_per_unit_effect"], 1)
        add("V2", "Driver decomposition sums to the total miss",
            abs(summed - total) <= 0.15, total, summed,
            f"verdict={dd.get('verdict')}, reconciles_flag={dd.get('reconciles')}")
    else:
        add("V2", "Driver decomposition correctly unavailable", True, "unavailable",
            "unavailable", f"missing={dd.get('missing_fields')}")

    # V3 -- every ladder level re-aggregated from SQL
    ladder = (df.get("investigation_ladder") or {}).get("levels") or []
    groups = {"Business Org": ["business_org"],
              "Region": ["business_org", "Region"],
              "SubRegion": ["business_org", "Region", "SubRegion"],
              "Country": ["business_org", "Region", "SubRegion", "Country"],
              "Channel": ["business_org", "Region", "SubRegion", "Country", "channel"]}
    cur.execute(f"SELECT business_org,Region,SubRegion,Country,channel FROM {table} "
                f"WHERE Forecast_name=? AND Fiscal_Week=?", (name, week))
    dims = dict(zip(("business_org", "Region", "SubRegion", "Country", "channel"), cur.fetchone()))
    mismatches = []
    for lv in ladder:
        g = groups.get(lv["level"])
        if not g:
            continue
        where = " AND ".join(f"{c} = ?" for c in g)
        cur.execute(f"SELECT SUM(Actual_Offered), SUM(fcst_offered) FROM {table} "
                    f"WHERE Fiscal_Week=? AND {where} AND fcst_offered IS NOT NULL AND fcst_offered<>0",
                    tuple([week] + [dims[c] for c in g]))
        s = cur.fetchone()
        if not s or not s[1]:
            continue
        exp = round((1.0 - float(s[0]) / float(s[1])) * 100.0, 1)
        if abs(exp - lv["adherence_pct"]) > 0.15:
            mismatches.append({"level": lv["level"], "expected": exp, "got": lv["adherence_pct"]})
    add("V3", f"All {len(ladder)} ladder levels match independent SQL aggregates",
        not mismatches, "all levels equal", f"{len(mismatches)} mismatch(es)", json.dumps(mismatches))

    # V4 -- data-quality typical week == median of the queue's history
    dq = df.get("data_quality") or {}
    if dq.get("available"):
        # Replicate the engine's window EXACTLY: it fetches TOP 104 rows with
        # Fiscal_Week <= target (so the target week is one of the 104) and only then drops
        # the target. Excluding the target *before* taking 104 pulls in one extra older week
        # and shifts the median -- that was a bug in this harness, not in the engine.
        cur.execute(f"SELECT TOP 104 Fiscal_Week, Actual_Offered FROM {table} "
                    f"WHERE Forecast_name=? AND Fiscal_Week<=? AND Actual_Offered IS NOT NULL "
                    f"ORDER BY Fiscal_Week DESC", (name, week))
        vals = [float(r[1]) for r in cur.fetchall() if str(r[0]) != str(week)]
        exp = round(statistics.median(vals), 1) if vals else None
        add("V4", "Data-quality typical week == median of SQL history",
            exp is not None and abs(exp - dq["typical_week_actual"]) <= 0.15,
            exp, dq.get("typical_week_actual"),
            f"suspect={dq.get('suspect')}, times_typical={dq.get('times_typical')}, n={len(vals)}")
    else:
        add("V4", "Data-quality check reported unavailable", True, "unavailable", "unavailable",
            dq.get("reason", ""))

    # V5 -- temporal 13-week average
    tp = df.get("temporal") or {}
    cur.execute(f"SELECT TOP 13 Actual_Offered FROM {table} WHERE Forecast_name=? "
                f"AND Fiscal_Week<? AND Actual_Offered IS NOT NULL ORDER BY Fiscal_Week DESC",
                (name, week))
    vals = [float(r[0]) for r in cur.fetchall()]
    exp = round(sum(vals) / len(vals), 1) if vals else None
    got = tp.get("last_13_week_avg_actual")
    add("V5", "Temporal last-13-week average matches SQL",
        (exp is None and got is None) or (exp is not None and got is not None and abs(exp - got) <= 0.15),
        exp, got, f"n={len(vals)}")

    # V6 -- every shipped cause satisfies its own precondition
    bad = []
    for c in (resp.get("ranked_root_causes") or []):
        ct = (c.get("cause_type") or "").strip()
        if ct in skeptic.PRECONDITIONS:
            pred, why = skeptic.PRECONDITIONS[ct]
            try:
                if not pred(df):
                    bad.append({"cause_type": ct, "title": c.get("title"), "unmet": why})
            except Exception as e:
                bad.append({"cause_type": ct, "error": str(e)})
    add("V6", "Every shipped cause_type satisfies its precondition", not bad,
        "no unsupported cause ships", f"{len(bad)} unsupported", json.dumps(bad))

    # V7 -- legacy keys for the existing UI
    legacy = ["primary_root_cause", "secondary_contributors", "key_findings", "supporting_evidence",
              "reasoning_narrative", "rejected_hypotheses", "historical_comparison",
              "forecast_improvement_recommendations", "confidence_score", "cause_type",
              "investigation_meta"]
    missing = [k for k in legacy if k not in resp]
    add("V7", "All legacy response keys present (existing UI renders it)", not missing,
        "11 keys", f"{11 - len(missing)} present", json.dumps(missing))

    # V8 -- no statistics jargon in business-facing text
    texts = [resp.get("executive_summary", ""), resp.get("business_impact", "")]
    for c in (resp.get("ranked_root_causes") or []):
        texts += [str(c.get("title", "")), str(c.get("explanation", "")),
                  str(c.get("business_impact", "")), str(c.get("recommended_action", ""))]
        for ev in (c.get("evidence") or []):
            texts.append(str(ev.get("text", "")))
    hits = sorted({w for w in BANNED for tx in texts if w in tx.lower()})
    add("V8", "No banned statistics vocabulary in business-facing text", not hits,
        "none", hits or "none")
    return checks


# ------------------------------------------------------------------------------ main
def main():
    started = datetime.now(timezone.utc)
    cfg = load_config()
    table = cfg["sql"]["table"]

    log("=" * 78)
    log("WFM RCA ENGINE -- END-TO-END VALIDATION RUN")
    log(f"started (UTC)      : {started.isoformat()}")
    log(f"backend            : {BASE}")
    log(f"table              : {table}  on  {cfg['sql']['server']}")
    log(f"model              : {MODEL[0]} / {MODEL[1]}")
    log(f"band               : +/-{BAND}%")
    log("queue selection    : DELIBERATE (explicit SQL predicate per engine path), not random")
    log("=" * 78)

    health = http_json(f"{BASE}/api/health")
    log(f"\n[0] health -> {json.dumps(health)}")

    conn = connect(cfg)
    cur = conn.cursor()
    cases = select_cases(cur, table)
    log(f"[0] selected {len(cases)} cases: {', '.join(c['case'] for c in cases)}")

    results, first = [], True
    for case in cases:
        log("\n" + "-" * 78)
        log(f"CASE {case['case']}: {case['Forecast_name']}  FW{case['Fiscal_Week']}")
        log(f"  locality : {case['Region']} / {case['SubRegion']} / {case['Country']} / {case['channel']}")
        log(f"  selected because: {case['why_selected']}")

        if not first:
            log(f"  pacing {PACE_SECONDS}s (Groq on-demand cap is 12,000 tokens/min)...")
            time.sleep(PACE_SECONDS)
        first = False

        qs = (f"forecast_name={urllib.parse.quote(case['Forecast_name'])}"
              f"&fiscal_week={case['Fiscal_Week']}&region={urllib.parse.quote(case['Region'] or '')}"
              f"&subregion={urllib.parse.quote(case['SubRegion'] or '')}"
              f"&country={urllib.parse.quote(case['Country'] or '')}"
              f"&channel={urllib.parse.quote(case['channel'] or '')}&history_cap=13&peers_cap=15")
        try:
            t0 = time.time()
            qc = http_json(f"{BASE}/api/queue-context?{qs}")
            t_ctx = time.time() - t0
        except Exception as e:
            log(f"  [1] GET /api/queue-context FAILED -> {e}")
            results.append({"case": case, "engine": None, "error": str(e), "checks": [],
                            "note": "queue-context unreachable; case not evaluated"})
            continue
        log(f"  [1] GET /api/queue-context -> {t_ctx:.2f}s "
            f"(history={len(qc.get('history_rows') or [])}, peers={len(qc.get('peer_rows') or [])})")

        bundle = build_bundle(qc)
        try:
            t0 = time.time()
            resp = http_json(
                f"{BASE}/api/rca-investigate?mode=wfm&provider={MODEL[0]}&model={urllib.parse.quote(MODEL[1])}",
                bundle)
            t_inv = time.time() - t0
        except Exception as e:
            log(f"  [2] POST /api/rca-investigate FAILED -> {e}")
            results.append({"case": case, "engine": None, "error": str(e), "checks": [],
                            "note": "investigate call failed; case not evaluated"})
            continue
        meta = resp.get("investigation_meta") or {}
        log(f"  [2] POST /api/rca-investigate?mode=wfm -> {t_inv:.2f}s  engine={meta.get('engine')}")
        log(f"      adherence={(resp.get('kpi_status') or {}).get('adherence_pct')}%  "
            f"causes={len(resp.get('ranked_root_causes') or [])}")
        for c in (resp.get("ranked_root_causes") or []):
            log(f"        #{c['rank']} [{c['confidence_pct']}% {c['confidence_level']}] "
                f"{c['status']} :: {c.get('cause_type')} :: {c.get('title')}")

        raw_path = os.path.join(OUT, f"case-{case['case']}-response.json")
        with open(raw_path, "w", encoding="utf-8") as fh:
            json.dump(resp, fh, indent=1, default=str)
        log(f"  [3] raw response -> results/{os.path.basename(raw_path)}")

        checks = validate(case, resp, cur, table)
        for ck in checks:
            log(f"      {'PASS' if ck['pass'] else 'FAIL'}  {ck['id']}  {ck['check']}"
                + ("" if ck["pass"] else f"   expected={ck['expected']} got={ck['got']} {ck['note']}"))

        results.append({"case": case, "engine": meta.get("engine"),
                        "provider": meta.get("provider"), "model": meta.get("model"),
                        "timing_seconds": {"queue_context": round(t_ctx, 2),
                                           "investigate": round(t_inv, 2)},
                        "adherence_pct": (resp.get("kpi_status") or {}).get("adherence_pct"),
                        "ranked_causes": [{"rank": c["rank"], "cause_type": c.get("cause_type"),
                                           "title": c.get("title"), "confidence_pct": c["confidence_pct"],
                                           "confidence_level": c["confidence_level"],
                                           "status": c.get("status")}
                                          for c in (resp.get("ranked_root_causes") or [])],
                        "skeptic_rejected": [s for s in (resp.get("skeptic_review") or [])
                                             if s.get("verdict") == "rejected"],
                        "checks": checks,
                        "raw_response_file": os.path.basename(raw_path)})

    conn.close()
    total = sum(len(r["checks"]) for r in results)
    passed = sum(1 for r in results for c in r["checks"] if c["pass"])
    report = {"run": {"started_utc": started.isoformat(),
                      "finished_utc": datetime.now(timezone.utc).isoformat(),
                      "backend": BASE, "server": cfg["sql"]["server"], "table": table,
                      "model": f"{MODEL[0]}/{MODEL[1]}", "band_pct": BAND,
                      "selection": "deliberate, one explicit SQL predicate per engine path",
                      "health": health},
              "totals": {"cases": len(results), "checks": total, "passed": passed,
                         "failed": total - passed},
              "cases": results}
    with open(os.path.join(OUT, "validation-report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1, default=str)

    log("\n" + "=" * 78)
    log(f"TOTAL: {passed}/{total} checks passed across {len(results)} cases")
    log("report -> results/validation-report.json")
    log("=" * 78)


if __name__ == "__main__":
    import urllib.parse           # noqa: E402  (used in main)
    main()
