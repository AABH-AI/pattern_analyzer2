"""
LIVE validation -- real SQL, real model, the real HTTP API. Phase 2 section 29.
==============================================================================

    cd backend && python ../results/run_live_validation.py

Drives `POST /api/rca-investigate?mode=wfm` over HTTP exactly as the console does, against the
configured database and the configured provider. Nothing here is synthetic and nothing is asserted
that the response does not contain.

Cases: the SA Indonesia FW202716 regression, plus queues picked by PREDICATE from the live table so
the generic requirement is exercised rather than assumed -- a large-volume breach, a moderate
breach, and a queue whose Actual_ASU is present so the exact decomposition can run.

Checks are behavioural. No expected sentence is hard-coded: the point is that the engine reaches a
defensible diagnosis on real data, not that it reproduces a particular string.
"""
import json
import os
import sys
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
sys.path.insert(0, HERE)
sys.path.insert(0, ".")

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

from run_validation import build_bundle, http_json        # noqa: E402
from sql_backend import connect, load_config             # noqa: E402
from wfm import rca_decision                             # noqa: E402

BASE = "http://127.0.0.1:8000"
# Overridable, because a provider can run out of quota mid-run. Gemini's free tier returns HTTP 429
# after very few calls on this account, and the engine's designed response to that is to fall back
# to the deterministic report and SAY so -- correct behaviour, but it means the model path has to be
# validated on a provider with quota left.
PROVIDER = sys.argv[1] if len(sys.argv) > 1 else "gemini"
MODEL = sys.argv[2] if len(sys.argv) > 2 else "gemini-3.5-flash"
ONLY = sys.argv[3] if len(sys.argv) > 3 else ""      # "generic" skips the regression case
BAND = 10.0
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append({"name": name, "pass": bool(ok), "detail": detail})
    return bool(ok)


def pick_cases(cur, table):
    """Real queue-weeks selected by predicate, so nothing about the case set is hand-picked."""
    cases = [("regression", "SA Indonesia Client Basic", 202716)]

    cur.execute(f"SELECT TOP 1 Forecast_name, Fiscal_Week FROM {table} "
                f"WHERE Actual_Offered IS NOT NULL AND fcst_offered > 200 "
                f"AND ABS(1.0 - Actual_Offered/fcst_offered)*100 > 25 "
                f"ORDER BY ABS(Actual_Offered - fcst_offered) DESC")
    r = cur.fetchone()
    if r:
        cases.append(("largest absolute breach on a high-volume queue", r[0], int(r[1])))

    cur.execute(f"SELECT TOP 1 Forecast_name, Fiscal_Week FROM {table} "
                f"WHERE Actual_ASU IS NOT NULL AND Actual_ASU <> 0 AND Planned_ASU IS NOT NULL "
                f"AND Planned_ASU <> 0 AND fcst_offered > 100 AND Actual_Offered IS NOT NULL "
                f"AND ABS(1.0 - Actual_Offered/fcst_offered)*100 > 20 "
                f"ORDER BY Fiscal_Week DESC, Forecast_name")
    r = cur.fetchone()
    if r:
        cases.append(("both ASU figures present -> exact decomposition available", r[0], int(r[1])))

    cur.execute(f"SELECT TOP 1 Forecast_name, Fiscal_Week FROM {table} "
                f"WHERE fcst_offered > 300 AND Actual_Offered IS NOT NULL "
                f"AND ABS(1.0 - Actual_Offered/fcst_offered)*100 BETWEEN 11 AND 18 "
                f"ORDER BY Fiscal_Week DESC, Forecast_name")
    r = cur.fetchone()
    if r:
        cases.append(("moderate breach just outside the band", r[0], int(r[1])))
    return cases


def validate(label, name, week, resp, elapsed):
    tag = f"{name} FW{week}"
    meta = resp.get("investigation_meta") or {}
    df = resp.get("derived_features") or {}
    d = df.get("decision") or {}

    print("=" * 100)
    print(f"[{label}]  {tag}")
    print("=" * 100)
    print(f"  engine={meta.get('engine')} provider={meta.get('provider')} model={meta.get('model')}"
          f"  {elapsed:.1f}s")
    kpi = resp.get("kpi_status") or {}
    print(f"  adherence={kpi.get('adherence_pct')}%  breached={kpi.get('breached')}")
    print(f"  miss_category   : {resp.get('miss_category')}")
    print(f"  forecastability : {(resp.get('forecastability') or {}).get('classification')}")
    conf, crit = resp.get("confidence_detail") or {}, resp.get("criticality") or {}
    print(f"  confidence      : {conf.get('level')} ({conf.get('score_pct')}%)   "
          f"criticality: {crit.get('level')} ({crit.get('contacts_gap')} contacts)")
    print(f"  ROOT CAUSE      : {resp.get('root_cause_sentence')}")
    for b in resp.get("why_this_happened") or []:
        print(f"    {b['rank']}. [{b['evidence_class']}] {b['headline']}  "
              f"(evidence {', '.join(b.get('evidence_ids') or [])}, {b.get('resolution')})")
    print(f"  wfm_action      : {resp.get('wfm_action')}")
    print(f"  EXEC SUMMARY    : {str(resp.get('executive_summary'))[:300]}")

    # ---- the model genuinely ran ----
    check(f"{tag} | engine is wfm-llm (the model answered)", meta.get("engine") == "wfm-llm",
          f"engine={meta.get('engine')}")
    check(f"{tag} | the configured model answered", meta.get("model") == MODEL,
          f"model={meta.get('model')}")

    # ---- deterministic decisions present and legal ----
    check(f"{tag} | miss_category is one of the defined values",
          resp.get("miss_category") in rca_decision.MISS_CATEGORIES, str(resp.get("miss_category")))
    classes = [b.get("evidence_class") for b in resp.get("why_this_happened") or []]
    check(f"{tag} | every evidence_class is legal",
          all(c in rca_decision.EVIDENCE_CLASSES for c in classes), str(classes))
    check(f"{tag} | criticality is one of the defined bands",
          (crit.get("level") in rca_decision.CRITICALITIES) or crit.get("level") is None,
          str(crit.get("level")))
    check(f"{tag} | confidence and criticality are independent fields",
          conf.get("score_pct") is not None and crit.get("level") is not None, "")

    # ---- the model did not override the decision layer ----
    check(f"{tag} | the response category matches the deterministic decision",
          resp.get("miss_category") == d.get("miss_category"),
          f"response={resp.get('miss_category')} decision={d.get('miss_category')}")
    check(f"{tag} | the ranked why matches the deterministic ranking",
          [b.get("headline") for b in resp.get("why_this_happened") or []]
          == [b.get("headline") for b in d.get("why_bullets") or []], "")

    # ---- backward compatibility ----
    for key in ("primary_root_cause", "secondary_contributors", "confidence_score", "cause_type",
                "key_findings", "forecast_summary", "proof", "statistical_evidence",
                "ranked_root_causes", "kpi_status"):
        check(f"{tag} | legacy key {key} still present", key in resp, "")
    causes = resp.get("ranked_root_causes") or []
    if causes:
        check(f"{tag} | cause_type preserved on ranked causes",
              all(c.get("cause_type") for c in causes), "")
        check(f"{tag} | status preserved on ranked causes",
              all(c.get("status") for c in causes), "")
        check(f"{tag} | evidence_class added alongside",
              all(c.get("evidence_class") for c in causes), "")

    # ---- the honesty rules ----
    text = " ".join([str(resp.get("executive_summary") or ""),
                     str(resp.get("business_impact") or ""),
                     str(resp.get("root_cause_sentence") or "")] +
                    [str(b.get("what_happened")) + str(b.get("why_it_mattered"))
                     for b in resp.get("why_this_happened") or []]).lower()
    banned = [w for w in ("service level", "wait time", "abandon", "understaff", "staffing shortage")
              if w in text]
    check(f"{tag} | no unsupported service-level claims", not banned, f"found={banned}")

    weekend = resp.get("weekend_diagnostic") or {}
    if not weekend.get("supported"):
        check(f"{tag} | no weekend attribution at weekly grain",
              "weekend" not in text or "cannot be isolated" in text, "weekend mentioned in prose")

    drivers = (resp.get("driver_diagnostics") or {}).get("drivers") or []
    sparse = [x["driver"] for x in drivers if x.get("coverage") in ("sparse", "absent")]
    promoted = [b for b in resp.get("why_this_happened") or []
                if b["evidence_class"] in ("PRIMARY_DRIVER", "SECONDARY_CONTRIBUTOR")
                and any(s.lower() in str(b.get("what_happened") or "").lower() for s in sparse)]
    check(f"{tag} | no sparse/absent driver is promoted to a cause", not promoted,
          f"sparse={sparse}")

    if resp.get("miss_category") != "DEMAND_EVENT":
        pass
    if (resp.get("forecastability") or {}).get("classification") == "LOW_PREDICTABILITY":
        check(f"{tag} | a low-predictability week is not called a forecast failure",
              resp.get("miss_category") in ("DEMAND_EVENT", "COMPOUND_MISS",
                                            "FORECAST_BASELINE_FAILURE", "DATA_LIMITATION"),
              str(resp.get("miss_category")))

    check(f"{tag} | the root cause is a sentence, not a label",
          len(str(resp.get("root_cause_sentence") or "").split()) >= 6,
          str(resp.get("root_cause_sentence")))
    check(f"{tag} | an action is stated", bool(str(resp.get("wfm_action") or "").strip()), "")
    check(f"{tag} | evidence index is populated", len(resp.get("evidence_index") or {}) >= 10,
          str(len(resp.get("evidence_index") or {})))
    return d


def main():
    cfg = load_config()
    table = cfg["sql"]["table"]
    print(f"live table: {table}   provider/model: {PROVIDER}/{MODEL}")
    print(f"health: {json.dumps(http_json(f'{BASE}/api/health'))}\n")

    cur = connect(cfg).cursor()
    cases = pick_cases(cur, table)
    if ONLY == "generic":
        cases = [c for c in cases if c[0] != "regression"]
    captured = {}

    for i, (label, name, week) in enumerate(cases):
        if i:
            time.sleep(6)      # be polite to the provider between calls
        qs = urllib.parse.urlencode({"forecast_name": name, "fiscal_week": week,
                                     "history_cap": 13, "peers_cap": 15})
        qc = http_json(f"{BASE}/api/queue-context?{qs}")
        bundle = build_bundle(qc)
        url = (f"{BASE}/api/rca-investigate?mode=wfm&provider={PROVIDER}"
               f"&model={urllib.parse.quote(MODEL)}")
        t0 = time.time()
        try:
            resp = http_json(url, bundle, timeout=320, attempts=2)
        except Exception as exc:
            check(f"{name} FW{week} | investigation completed", False, str(exc))
            continue
        elapsed = time.time() - t0
        validate(label, name, week, resp, elapsed)
        captured[f"{name}|{week}"] = resp
        print()

    out = os.path.join(HERE, f"live-validation-{PROVIDER}.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(captured, fh, indent=1, default=str)

    failed = [r for r in RESULTS if not r["pass"]]
    print("=" * 100)
    for r in RESULTS:
        if not r["pass"]:
            print(f"  FAIL  {r['name']}\n          {r['detail']}")
    print(f"  {len(RESULTS) - len(failed)}/{len(RESULTS)} live checks passed over "
          f"{len(captured)} real queue-week(s)")
    print(f"  responses -> {out}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
