"""
Spec compliance check — does the engine obey the BUSINESS PROMPT, clause by clause?
==================================================================================

Run:  cd backend && python ../results/spec_compliance_check.py

The other suites answer different questions:
  * smoke_test_modules.py  -> does each module work in isolation?
  * run_validation.py      -> do the numbers reconcile against SQL?
  * run_llm_ranking.py     -> did the LLM actually answer, and is its ranking coherent?

This one asks: **is the output a proper RCA as specified in the business prompt?** Each check
maps to a named clause of that prompt, and each runs against a LIVE LLM investigation.

A clause that cannot be evaluated without the SQL deep context (the investigation ladder and
channel siblings both need cross-queue rollups) is reported SKIP, never PASS.
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE + "/../backend")

from sql_backend import load_config                     # noqa: E402
from wfm import fetch_wfm_context, investigate_wfm      # noqa: E402
from wfm.common import confidence_level                 # noqa: E402

BAND = 10.0

# The prompt's own banned vocabulary, verbatim from "# BUSINESS LANGUAGE".
BANNED = ("correlation", "regression", "outlier", "pearson", "z-score", "z score",
          "shap", "isolation forest", "standard deviation", "sigma", "mape")

# Fabrication tripwires -- the prompt forbids assuming these outright.
FABRICATION = ("marketing campaign", "product launch", "promotion campaign",
               "advertising campaign", "new product release")


def load_bundle(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def context_for(bundle, cfg):
    """Prefer the real SQL deep context. If SQL is unreachable, rebuild what we can from the
    bundle's own history and say so, so SQL-dependent clauses are SKIPPED not faked."""
    target = bundle["target"]
    fields = target.get("fields") or {}
    key = {"Forecast_name": target["key"].get("Forecast_name"),
           "Fiscal_Week": target["key"].get("Fiscal_Week"),
           "Region": fields.get("Region"), "SubRegion": fields.get("SubRegion"),
           "Country": fields.get("Country"), "channel": fields.get("channel"),
           "business_org": fields.get("business_org")}
    try:
        from sql_backend import connect
        conn = connect(cfg)
        try:
            wc = fetch_wfm_context(conn.cursor(), cfg["sql"]["table"], key)
            return wc, True
        finally:
            conn.close()
    except Exception as e:
        print(f"    [SQL unavailable: {type(e).__name__}] rebuilding shallow context from the bundle")
        hist = []
        for h in bundle.get("history") or []:
            c = h.get("computed") or {}
            hist.append({"Fiscal_Week": h["key"]["Fiscal_Week"], "Actual_Offered": c.get("actual"),
                         "fcst_offered": c.get("forecast"), "Holiday_Count": None,
                         "Projection_plan_name": None, "Planned_ASU": None,
                         "Actual_ASU": None, "Final_Units": None})
        hist.append({"Fiscal_Week": target["key"]["Fiscal_Week"],
                     "Actual_Offered": fields.get("Actual_Offered"),
                     "fcst_offered": fields.get("fcst_offered"),
                     "Holiday_Count": fields.get("Holiday_Count"),
                     "Projection_plan_name": fields.get("Projection_plan_name"),
                     "Planned_ASU": fields.get("Planned_ASU"),
                     "Actual_ASU": fields.get("Actual_ASU"),
                     "Final_Units": fields.get("Final_Units")})
        return {"history_104": hist, "history_forward": [], "channel_sibling_rows": [],
                "ladder": [], "prior_week": (hist[-2]["Fiscal_Week"] if len(hist) > 1 else None),
                "prior_year_week": None}, False


def business_text(resp):
    out = [resp.get("executive_summary", ""), resp.get("business_impact", ""),
           str(resp.get("reasoning_narrative", ""))]
    for c in resp.get("ranked_root_causes") or []:
        out += [str(c.get("title", "")), str(c.get("explanation", "")),
                str(c.get("business_impact", "")), str(c.get("recommended_action", ""))]
        for ev in c.get("evidence") or []:
            out.append(str(ev.get("text", "")))
    for k in resp.get("key_findings") or []:
        out.append(str(k))
    return " \n".join(out)


def real_numbers(feats):
    pool = set()

    def walk(n):
        if isinstance(n, dict):
            for v in n.values():
                walk(v)
        elif isinstance(n, (list, tuple)):
            for v in n:
                walk(v)
        elif isinstance(n, (int, float)) and not isinstance(n, bool):
            pool.add(float(n))
    walk(feats)
    return pool


def check_spec(resp, had_sql):
    """Every entry names the clause of the business prompt it enforces."""
    out = []

    def add(cid, clause, ok, detail=""):
        out.append({"id": cid, "clause": clause,
                    "status": ("PASS" if ok is True else "SKIP" if ok is None else "FAIL"),
                    "detail": detail})

    feats = resp.get("derived_features") or {}
    causes = resp.get("ranked_root_causes") or []
    kpi = resp.get("kpi_status") or {}
    text = business_text(resp)
    low = text.lower()

    # --- KPI ---
    add("S1", "KPI: Forecast Adherence formula + threshold recorded",
        kpi.get("metric") == "Forecast Adherence" and kpi.get("threshold_pct") == BAND
        and isinstance(kpi.get("adherence_pct"), (int, float)),
        json.dumps(kpi))
    add("S2", "KPI: breach flag agrees with |adherence| > threshold",
        kpi.get("breached") == (abs(kpi.get("adherence_pct", 0)) > BAND),
        f"adherence={kpi.get('adherence_pct')} breached={kpi.get('breached')}")

    # --- ROOT CAUSE GENERATION ---
    add("S3", "Root causes: multiple explanations, ranked, capped at 5",
        1 <= len(causes) <= 5 and [c.get("rank") for c in causes] == list(range(1, len(causes) + 1)),
        f"{len(causes)} causes, ranks={[c.get('rank') for c in causes]}")
    required = ("title", "explanation", "evidence", "confidence_pct",
                "confidence_level", "business_impact", "recommended_action", "status")
    missing = {k: sum(1 for c in causes if not str(c.get(k, "")).strip() and c.get(k) != 0)
               for k in required}
    add("S4", "Root causes: each carries description, evidence, confidence, impact, action",
        all(v == 0 for v in missing.values()),
        json.dumps({k: v for k, v in missing.items() if v}))
    add("S5", "Root causes: best-supported first (confidence descends)",
        [c.get("confidence_pct") or 0 for c in causes] ==
        sorted([c.get("confidence_pct") or 0 for c in causes], reverse=True),
        str([c.get("confidence_pct") for c in causes]))

    # --- CONFIDENCE SCORING ---
    bad = [(c.get("confidence_pct"), c.get("confidence_level")) for c in causes
           if c.get("confidence_level") != confidence_level(c.get("confidence_pct") or 0)]
    add("S6", "Confidence: percent AND High/Medium/Low, consistent with each other",
        not bad, f"mismatches={bad}")

    # --- HYPOTHESIS ENGINE ---
    statuses = {str(c.get("status", "")) for c in causes}
    add("S7", "Hypothesis engine: status is Verified or 'Hypothesis - To be Validated'",
        statuses and all(s in ("Verified", "Hypothesis - To be Validated") for s in statuses),
        str(sorted(statuses)))

    # --- SKEPTIC MODE ---
    sk = resp.get("skeptic_review") or []
    add("S8", "Skeptic mode: challenges recorded with verdicts",
        bool(sk) and all(("challenge" in e or "reason" in e) and e.get("verdict") in ("retained", "rejected")
                         for e in sk if isinstance(e, dict)),
        f"{len(sk)} entries, {sum(1 for e in sk if e.get('verdict')=='rejected')} rejected")

    # --- BUSINESS LANGUAGE ---
    hits = sorted({w for w in BANNED if w in low})
    add("S9", "Business language: no statistics vocabulary in business-facing text",
        not hits, f"found={hits}")
    tech = resp.get("technical_metrics") or []
    add("S10", "Technical metrics kept in their own (collapsed) section",
        isinstance(tech, list) and len(tech) > 0, f"{len(tech)} rows")

    # --- OUTPUT FORMAT ---
    add("S11", "Output format: executive summary, KPI status, business impact all present",
        bool(str(resp.get("executive_summary", "")).strip()) and bool(kpi)
        and bool(str(resp.get("business_impact", "")).strip()),
        f"summary={len(str(resp.get('executive_summary','')))} chars")

    # --- CORE PRINCIPLE: never jump straight to a cause ---
    add("S12", "Core principle: observations exist separately from the ranked cause",
        bool(resp.get("key_findings")),
        f"{len(resp.get('key_findings') or [])} key findings")

    # --- TEMPORAL REASONING ---
    tp = feats.get("temporal") or {}
    have = [k for k in ("previous_week", "last_4_week_avg_actual", "last_13_week_avg_actual",
                        "same_week_last_year") if tp.get(k) is not None]
    add("S13", "Temporal: prior week / last 4 / last 13 / same week last year computed",
        len(have) >= 3, f"present={have} (of 4); history weeks={tp.get('history_weeks_available')}")

    # --- INVESTIGATION ORDER (needs SQL) ---
    ladder = feats.get("investigation_ladder") or {}
    if not had_sql or not ladder.get("available"):
        add("S14", "Investigation order: higher levels checked before concluding", None,
            "needs the SQL cross-queue rollup")
    else:
        levels = ladder.get("levels") or []
        add("S14", "Investigation order: higher levels checked before concluding",
            len(levels) >= 3 and "inherited_from" in ladder,
            f"levels={[l.get('level') for l in levels]} inherited_from={ladder.get('inherited_from')}")
        if ladder.get("inherited_from"):
            add("S15", "Investigation order: an inherited miss is actually reported as inherited",
                any((c.get("cause_type") == "inherited_from_higher_level") for c in causes),
                f"inherited_from={ladder.get('inherited_from')}, "
                f"types={[c.get('cause_type') for c in causes]}")
        else:
            add("S15", "Investigation order: nothing inherited to report", True, "no higher-level breach")

    # --- CQN / CHANNEL SHIFT (needs SQL) ---
    cs = feats.get("channel_siblings") or {}
    cm = resp.get("channel_migration") or {}
    if not had_sql or not cs.get("available"):
        add("S16", "CQN validation: channel migration evaluated before blaming the forecast", None,
            "needs the SQL channel-sibling rows")
    else:
        add("S16", "CQN validation: channel migration evaluated before blaming the forecast",
            "migration_detected" in cs and "detected" in cm,
            f"detected={cm.get('detected')} channels={len(cs.get('per_channel') or [])} "
            f"is_cqn_proxy={cs.get('is_cqn_proxy')}")

    # --- CORRELATION ANALYSIS ---
    corr = feats.get("correlations") or {}
    rel = corr.get("relationships") or {}
    add("S17", "Correlation analysis: relationships retained/rejected on evidence",
        "retained" in rel and "rejected" in rel,
        f"retained={[r.get('driver') for r in rel.get('retained', [])]}, "
        f"rejected={len(rel.get('rejected', []))}")

    # --- CRITICAL RULES: never fabricate ---
    fab = sorted({w for w in FABRICATION if w in low})
    add("S18", "Critical rules: no invented campaigns / product launches asserted",
        not fab, f"found={fab}")
    pool = real_numbers(feats)

    def reconciles(v):
        try:
            x = float(str(v).replace(",", "").strip())
        except (TypeError, ValueError):
            return None
        return any(r == x or abs(r - x) / max(abs(r), abs(x), 1e-9) <= 0.02 for r in pool)
    checked = unmatched = 0
    for c in causes:
        for ev in c.get("evidence") or []:
            r = reconciles(ev.get("value"))
            if r is None:
                continue
            checked += 1
            if not r:
                unmatched += 1
    add("S19", "Critical rules: every quoted figure traces to the real data",
        unmatched == 0, f"{checked} numeric citations checked, {unmatched} unmatched")

    # --- insufficient evidence must be declared ---
    add("S20", "Critical rules: gaps declared rather than glossed over",
        isinstance(resp.get("missing_information"), list),
        f"{len(resp.get('missing_information') or [])} item(s)")

    # --- ACTION RECOMMENDATIONS ---
    weak = [c.get("cause_type") for c in causes if len(str(c.get("recommended_action", ""))) < 15]
    add("S21", "Action recommendations: every cause carries a practical action",
        not weak, f"too-short={weak}")
    return out


def main():
    cfg = load_config()
    tmp = os.environ.get("CLAUDE_JOB_DIR", "")
    candidates = [os.path.join(tmp, "tmp", "bundle.json"), os.path.join(HERE, "bundle.json")]
    bundle_path = next((p for p in candidates if os.path.exists(p)), None)
    if not bundle_path:
        print("No context bundle available. Run results/run_validation.py first (needs SQL).")
        return 2

    print("=" * 78)
    print("SPEC COMPLIANCE CHECK -- does the engine obey the business prompt?")
    print(f"branch artefacts: wfm/ package      bundle: {os.path.basename(bundle_path)}")
    print("=" * 78)

    bundle = load_bundle(bundle_path)
    wc, had_sql = context_for(bundle, cfg)
    print(f"    SQL deep context: {'YES' if had_sql else 'NO (ladder + channel clauses will SKIP)'}")

    runs = []
    for provider, model in (("nvidia", "nvidia/nemotron-3-super-120b-a12b"),
                            ("groq", "llama-3.3-70b-versatile")):
        print("\n" + "-" * 78)
        print(f"RUN: {provider} / {model}")
        t0 = time.time()
        resp = investigate_wfm(bundle, cfg.get("llm", {}), wc,
                               model_choice={"provider": provider, "model": model}, band=BAND)
        el = time.time() - t0
        engine = (resp.get("investigation_meta") or {}).get("engine")
        print(f"  engine={engine}  {el:.1f}s  causes={len(resp.get('ranked_root_causes') or [])}")
        if engine != "wfm-llm":
            print(f"  !! not an LLM answer -- {(resp.get('missing_information') or ['?'])[0][:150]}")
        for c in resp.get("ranked_root_causes") or []:
            print(f"    #{c['rank']} [{c['confidence_pct']}% {c['confidence_level']}] "
                  f"{c['status']} :: {c.get('cause_type')} :: {c.get('title')}")
        checks = check_spec(resp, had_sql)
        for ck in checks:
            mark = ck["status"]
            print(f"      {mark}  {ck['id']:4s} {ck['clause']}")
            if mark != "PASS" and ck["detail"]:
                print(f"            {ck['detail']}")
        fn = f"spec-{provider}-response.json"
        with open(os.path.join(HERE, fn), "w", encoding="utf-8") as fh:
            json.dump(resp, fh, indent=1, default=str)
        runs.append({"provider": provider, "model": model, "engine": engine,
                     "seconds": round(el, 1), "raw_file": fn,
                     "ranked": [{k: c.get(k) for k in ("rank", "cause_type", "title",
                                                       "confidence_pct", "confidence_level", "status")}
                                for c in resp.get("ranked_root_causes") or []],
                     "checks": checks})

    tot = sum(len(r["checks"]) for r in runs)
    p = sum(1 for r in runs for c in r["checks"] if c["status"] == "PASS")
    f = sum(1 for r in runs for c in r["checks"] if c["status"] == "FAIL")
    s = sum(1 for r in runs for c in r["checks"] if c["status"] == "SKIP")
    with open(os.path.join(HERE, "spec-compliance-report.json"), "w", encoding="utf-8") as fh:
        json.dump({"had_sql_deep_context": had_sql, "bundle": os.path.basename(bundle_path),
                   "totals": {"checks": tot, "pass": p, "fail": f, "skip": s}, "runs": runs},
                  fh, indent=1, default=str)
    print("\n" + "=" * 78)
    print(f"{p} PASS / {f} FAIL / {s} SKIP  of {tot} clause checks across {len(runs)} providers")
    print("report -> results/spec-compliance-report.json")
    print("=" * 78)
    return 1 if f else 0


if __name__ == "__main__":
    sys.exit(main())
