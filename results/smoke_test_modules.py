"""
Per-module smoke test — proves every WFM module works on its own.
=================================================================

Run:  cd backend && python ../results/smoke_test_modules.py

`run_validation.py` tests the engine end to end; this tests each module in isolation with
hand-built inputs, so a failure points at one file instead of "the engine broke". No SQL and no
LLM required for modules 1-9; the two SQL/LLM-dependent ones are skipped cleanly when offline.
"""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/../backend")

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
results = []


def check(module, what, fn):
    try:
        detail = fn()
        if detail == SKIP:
            results.append((SKIP, module, what, "no SQL/LLM available"))
        else:
            results.append((PASS, module, what, detail or ""))
    except Exception as e:
        results.append((FAIL, module, what, f"{type(e).__name__}: {e}"))
        traceback.print_exc()


# ---------------------------------------------------------------- 1. common
def t_common():
    from wfm.common import adherence_pct, confidence_level, median, prior_year_week
    assert round(adherence_pct(80, 100), 1) == 20.0, "over-forecast sign"
    assert round(adherence_pct(120, 100), 1) == -20.0, "under-forecast sign"
    assert adherence_pct(10, 0) is None and adherence_pct(10, None) is None, "no forecast -> None"
    assert confidence_level(90) == "High" and confidence_level(50) == "Medium" and confidence_level(10) == "Low"
    assert median([1, 2, 3, 4]) == 2.5 and median([]) is None
    assert prior_year_week(202719) == 202619 and prior_year_week("x") is None
    return "KPI sign convention, bands, median, fiscal-week maths"


# ------------------------------------------------------- 2. temporal_reasoner
def t_temporal():
    from wfm import temporal_reasoner
    hist = [{"Fiscal_Week": 202700 + i, "Actual_Offered": float(i * 10),
             "fcst_offered": 100.0, "Projection_plan_name": "P1"} for i in range(1, 15)]
    hist.append({"Fiscal_Week": 202619, "Actual_Offered": 55.0, "fcst_offered": 50.0,
                 "Projection_plan_name": "P0"})
    out = temporal_reasoner.analyse(hist, 202714, 140.0, 100.0, 202619)
    assert out["history_weeks_available"] == 14, out["history_weeks_available"]
    assert out["same_week_last_year"]["actual"] == 55.0, "last-year lookup"
    assert out["forecast_plan_changed_within_window"] is True, "plan change detected"
    assert out["last_4_week_avg_actual"] is not None
    return f"14 wks, last-year found, plan-change flag, 4/13wk averages"


# ----------------------------------------------------- 3. hierarchy_analyzer
def t_hierarchy():
    from wfm import hierarchy_analyzer
    ladder = [{"level": "Business Org", "scope": "CSG", "adherence_pct": -25.0,
               "actual_offered": 1.0, "fcst_offered": 1.0, "queue_weeks_in_scope": 9},
              {"level": "Region", "scope": "APJ", "adherence_pct": 2.0,
               "actual_offered": 1.0, "fcst_offered": 1.0, "queue_weeks_in_scope": 9}]
    out = hierarchy_analyzer.analyse(ladder, -30.0, 10.0)
    assert out["inherited_from"] == "Business Org", out["inherited_from"]
    # opposite direction must NOT be treated as inherited
    out2 = hierarchy_analyzer.analyse(ladder, +30.0, 10.0)
    assert out2["inherited_from"] is None, out2["inherited_from"]
    assert hierarchy_analyzer.analyse([], -30.0, 10.0)["available"] is False
    return "highest same-direction level wins; opposite direction ignored; empty handled"


# ---------------------------------------- 4. channel_migration_detector
def t_migration():
    from wfm import channel_migration_detector as cmd
    # Voice loses 100, Chat gains 100, group total flat -> migration
    rows = [{"Fiscal_Week": 1, "channel": "Voice", "Actual_Offered": 500.0},
            {"Fiscal_Week": 1, "channel": "Chat", "Actual_Offered": 100.0},
            {"Fiscal_Week": 2, "channel": "Voice", "Actual_Offered": 400.0},
            {"Fiscal_Week": 2, "channel": "Chat", "Actual_Offered": 200.0}]
    out = cmd.analyse(rows, 2, "Voice")
    assert out["migration_detected"] is True, out
    assert out["is_cqn_proxy"] is True, "must be labelled a proxy, never 'the CQN'"
    # both channels grow -> NOT migration
    rows2 = [r.copy() for r in rows]
    rows2[2]["Actual_Offered"] = 900.0
    out2 = cmd.analyse(rows2, 2, "Voice")
    assert out2["migration_detected"] is False, out2
    assert cmd.analyse([], 2, "Voice")["available"] is False
    return "offsetting move detected; joint growth rejected; proxy flag present"


# --------------------------------------------------------- 5. data_quality
def t_data_quality():
    from wfm import data_quality
    hist = [{"Fiscal_Week": 100 + i, "Actual_Offered": 50.0} for i in range(12)]
    hist.append({"Fiscal_Week": 112, "Actual_Offered": 8000.0})          # the spike
    fwd = [{"Fiscal_Week": 113, "Actual_Offered": 52.0},
           {"Fiscal_Week": 114, "Actual_Offered": 48.0}]
    out = data_quality.analyse(hist, fwd, 112, 8000.0)
    assert out["suspect"] is True, out
    assert out["returns_to_normal_immediately"] is True
    # a level shift (other weeks near it) must NOT be suspect
    hist2 = hist + [{"Fiscal_Week": 111, "Actual_Offered": 7800.0}]
    assert data_quality.analyse(hist2, fwd, 112, 8000.0)["suspect"] is False
    assert data_quality.analyse(hist[:3], fwd, 112, 8000.0)["available"] is False
    return "isolated reverting spike flagged; level shift not flagged; short history skipped"


# ----------------------------------------------------- 6. correlation_engine
def t_correlation():
    from wfm import correlation_engine as ce
    d = ce.driver_decomposition({"fcst_offered": 1000.0, "Actual_Offered": 1300.0,
                                 "Planned_ASU": 100000.0, "Actual_ASU": 110000.0})
    assert d["available"] and d["reconciles"], d
    assert abs((d["warranty_base_effect"] + d["contacts_per_unit_effect"]) - d["total_miss"]) < 0.15
    assert ce.driver_decomposition({"fcst_offered": 10})["available"] is False
    hist = [{"Actual_Offered": float(i * 10), "Actual_ASU": float(i * 100),
             "Planned_ASU": None, "Final_Units": None, "Holiday_Count": 0} for i in range(1, 16)]
    rel = ce.relationships(hist)
    kept = [r["driver"] for r in rel["retained"]]
    assert "Actual_ASU" in kept, kept
    assert all("plain_language" in r for r in rel["retained"]), "business wording required"
    assert rel["rejected"], "weak drivers must be explicitly rejected"
    return f"identity exact; missing cols handled; retained={kept}"


# ------------------------------------------------------------- 7. skeptic
def t_skeptic():
    from wfm import skeptic
    feats = {"base_features": {"plan_restatement": {"changed": False},
                               "forecast_sanity": {"verdict": "actual_anomalous"}},
             "data_quality": {"suspect": False}, "channel_siblings": {},
             "investigation_ladder": {}, "correlations": {}}
    causes = [{"cause_type": "plan_restatement", "title": "Plan changed", "evidence": []},
              {"cause_type": "genuine_demand_event", "title": "Real spike", "evidence": []}]
    kept, entries = skeptic.review(causes, feats)
    assert [c["title"] for c in kept] == ["Real spike"], kept
    assert any(e["verdict"] == "rejected" for e in entries), "rejection must be recorded"
    assert skeptic.eligible_cause_types(feats) == ["genuine_demand_event"], skeptic.eligible_cause_types(feats)
    # numeric grounding: a fabricated figure is pruned
    feats2 = dict(feats); feats2["base_features"] = dict(feats["base_features"])
    feats2["base_features"]["proof"] = [{"this_week": 4321.0}]
    c = [{"cause_type": "genuine_demand_event", "title": "T",
          "evidence": [{"value": 4321.0}, {"value": 999999.0}]}]
    kept2, _ = skeptic.review(c, feats2)
    assert len(kept2[0]["evidence"]) == 1, kept2[0]["evidence"]
    assert len(skeptic.PRECONDITIONS) == 10, len(skeptic.PRECONDITIONS)
    return "unsupported cause rejected; 10 preconditions; fabricated figure pruned"


# ------------------------------------------------ 8. hypothesis_generator
def t_hypothesis():
    from wfm import hypothesis_generator as hg
    marked = hg.mark([{"cause_type": "data_quality_issue", "status": "Verified",
                       "evidence": [{"value": 1}]}], {})
    assert marked[0]["status"] == hg.HYPOTHESIS, "data quality can never be Verified"
    marked2 = hg.mark([{"cause_type": "genuine_demand_event", "status": "Verified",
                        "evidence": []}], {})
    assert marked2[0]["status"] == hg.HYPOTHESIS, "no evidence -> hypothesis"
    feats = {"base_features": {}, "data_quality": {"suspect": True, "note": "n",
                                                   "this_week_actual": 9, "typical_week_actual": 1},
             "investigation_ladder": {}, "channel_siblings": {}, "correlations": {}}
    lst = hg.deterministic(feats, {"statement": "s", "confidence": 0.4,
                                   "supporting_evidence": []}, "systematic_forecast_bias")
    assert lst and lst[0]["cause_type"] == "data_quality_issue", lst[0]
    assert len(lst) <= 5
    return "over-confidence downgraded; deterministic list leads with data quality"


# ------------------------------------------ 9. business_report_generator
def t_report():
    from wfm import business_report_generator as brg
    k = brg.kpi_status(-25.0, 10.0)
    assert k["breached"] and k["direction"] == "under_forecast", k
    assert brg.kpi_status(5.0, 10.0)["breached"] is False
    causes = brg.normalise_causes([{"confidence_pct": 0.8, "confidence_level": "Medium"},
                                   {"confidence_pct": 30}])
    assert causes[0]["confidence_pct"] == 80, causes[0]
    assert causes[0]["confidence_level"] == "High", "band must be derived, not trusted"
    assert [c["rank"] for c in causes] == [1, 2]
    ni = brg.not_investigated(-3.0, 10.0, {"base_features": {}})
    for key in ("primary_root_cause", "secondary_contributors", "key_findings", "confidence_score"):
        assert key in ni, f"legacy key {key} missing from within-band response"
    return "KPI recomputed; 0-1 confidence rescaled; band derived; legacy keys present"


# ------------------------------------------------------- 10. data_access (SQL)
def t_data_access():
    try:
        from sql_backend import connect, load_config
        from wfm import fetch_wfm_context
        cfg = load_config()
        conn = connect(cfg)
    except Exception:
        return SKIP
    try:
        cur = conn.cursor()
        wc = fetch_wfm_context(cur, cfg["sql"]["table"], {
            "Forecast_name": "NA Core Spanish", "Fiscal_Week": "202719", "Region": "Americas",
            "SubRegion": "NA", "Country": "United States", "channel": "Voice", "business_org": "CSG"})
        assert wc["history_104"], "no history"
        assert wc["ladder"], "no ladder"
        assert wc["prior_week"], "no prior week"
        return (f"{len(wc['history_104'])} history, {len(wc['history_forward'])} forward, "
                f"{len(wc['channel_sibling_rows'])} siblings, {len(wc['ladder'])} ladder levels")
    finally:
        conn.close()


# ------------------------------------------------------ 11. llm_client / prompts
def t_llm_client():
    from wfm.llm_client import DEFAULT_TIMEOUT_SECONDS, timeout_from_config
    from wfm.prompts import WFM_SYSTEM_PROMPT
    assert timeout_from_config({"timeout_seconds": 150}) == 150
    assert timeout_from_config({}) == DEFAULT_TIMEOUT_SECONDS
    assert timeout_from_config({"timeout_seconds": "junk"}) == DEFAULT_TIMEOUT_SECONDS
    for token in ("ranked_root_causes", "cause_type", "skeptic_review",
                  "ELIGIBLE_CAUSE_TYPES", "DATA QUALITY FIRST"):
        assert token in WFM_SYSTEM_PROMPT, f"prompt missing {token}"
    return "timeout config parsed + defaulted; prompt contract intact"


# ------------------------------------------- 12. investigation_engine wiring
def t_engine_wiring():
    from wfm import derive_wfm_features, investigate_wfm
    bundle = {"meta": {"band_threshold": 10.0},
              "target": {"key": {"Forecast_name": "Q", "Fiscal_Week": "202719"},
                         "fields": {"Actual_Offered": 100.0, "fcst_offered": 100.0},
                         "computed": {"actual": 100.0, "forecast": 100.0, "adherence_pct": 0.0}},
              "history": [], "peers": [], "statistical_summary": {"numeric": {}, "categorical": {}}}
    wc = {"history_104": [], "history_forward": [], "channel_sibling_rows": [], "ladder": [],
          "prior_week": None, "prior_year_week": None}
    feats, adh = derive_wfm_features(bundle, wc, 10.0)
    for block in ("base_features", "temporal", "channel_siblings",
                  "investigation_ladder", "data_quality", "correlations"):
        assert block in feats, f"missing feature block {block}"
    # in-band -> must refuse to investigate, with no LLM call at all
    out = investigate_wfm(bundle, {}, wc, band=10.0)
    assert out["investigation_meta"]["engine"] == "wfm-not-investigated", out["investigation_meta"]
    assert out["ranked_root_causes"] == []
    return "all 6 feature blocks built; in-band gate refuses without calling any provider"


CHECKS = [
    ("common.py", "KPI maths & helpers", t_common),
    ("temporal_reasoner.py", "104wk / last-year / plan change", t_temporal),
    ("hierarchy_analyzer.py", "investigation ladder", t_hierarchy),
    ("channel_migration_detector.py", "channel migration", t_migration),
    ("data_quality.py", "credibility of the number", t_data_quality),
    ("correlation_engine.py", "decomposition + relationships", t_correlation),
    ("skeptic.py", "rejection & numeric grounding", t_skeptic),
    ("hypothesis_generator.py", "status marking & fallback list", t_hypothesis),
    ("business_report_generator.py", "report + back-compat", t_report),
    ("data_access.py", "SQL fetches (needs VPN)", t_data_access),
    ("llm_client.py + prompts.py", "timeout config & prompt contract", t_llm_client),
    ("investigation_engine.py", "wiring & threshold gate", t_engine_wiring),
]

if __name__ == "__main__":
    print("=" * 78)
    print("WFM MODULE SMOKE TEST — each module exercised in isolation")
    print("=" * 78)
    for module, what, fn in CHECKS:
        check(module, what, fn)
    print()
    for status, module, what, detail in results:
        print(f"  {status}  {module:34s} {what}")
        if detail:
            print(f"        {detail}")
    n_pass = sum(1 for r in results if r[0] == PASS)
    n_fail = sum(1 for r in results if r[0] == FAIL)
    n_skip = sum(1 for r in results if r[0] == SKIP)
    print()
    print("=" * 78)
    print(f"{n_pass} passed, {n_fail} failed, {n_skip} skipped, of {len(results)} modules")
    print("=" * 78)
    sys.exit(1 if n_fail else 0)
