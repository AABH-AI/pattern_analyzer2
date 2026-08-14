"""Run SA Indonesia Client Basic FW202716 through spec_engine on WHICHEVER checkout this is.

Run from inside a checkout's backend/ directory. Writes a small JSON summary so the same script can
produce the before and the after and the two can be diffed.

    cd <checkout>/backend && python <this> <label> <outpath>
"""
import json
import os
import sys

LABEL = sys.argv[1] if len(sys.argv) > 1 else "unknown"
OUTPATH = sys.argv[2] if len(sys.argv) > 2 else "indo.json"

sys.path.insert(0, ".")
from sql_backend import connect, load_config                                # noqa: E402
from wfm import spec_engine                                                 # noqa: E402
from wfm.data_access import fetch_wfm_context                               # noqa: E402
from wfm.common import adherence_pct                                        # noqa: E402

NAME, WEEK = "SA Indonesia Client Basic", 202716

cfg = load_config()
table = cfg["sql"]["table"]
conn = connect(cfg)
cur = conn.cursor()

cur.execute(f"SELECT * FROM {table} WHERE Forecast_name = ? AND Fiscal_Week = ?", (NAME, WEEK))
row = cur.fetchone()
fields = dict(zip([d[0] for d in cur.description], row))
actual, forecast = fields["Actual_Offered"], fields["fcst_offered"]

key = {k: fields.get(k) for k in ("Forecast_name", "Fiscal_Week", "Region", "SubRegion", "Country",
                                  "channel", "business_org", "Offering")}
wfm_ctx = fetch_wfm_context(cur, table, key)

bundle = {"target": {"key": key, "fields": fields,
                     "computed": {"actual": actual, "forecast": forecast,
                                  "adherence_pct": adherence_pct(actual, forecast)}}}

err = None
try:
    res = spec_engine.investigate(bundle, cfg.get("llm", {}), wfm_ctx, grain="weekly",
                                  model_choice=None, interrogate=False)
except Exception as exc:
    import traceback
    err = f"{type(exc).__name__}: {exc}"
    traceback.print_exc()
    res = {}

rc = res.get("root_cause") or {}
cf = res.get("confidence") or {}
sections = (res.get("decision_card") or {}).get("sections") or {}
hol = res.get("holiday_response") or res.get("holiday") or {}

summary = {
    "label": LABEL,
    "exception": err,
    "history_weeks_fetched": len(wfm_ctx.get("history_104") or []),
    "history_columns": sorted((wfm_ctx.get("history_104") or [{}])[0].keys()),
    "status": res.get("status"),
    "engine": res.get("engine"),
    "adherence_pct": (res.get("forecast_summary") or {}).get("adherence_pct"),
    "gap_contacts": (res.get("forecast_summary") or {}).get("absolute_variance_contacts"),
    "root_cause_id": rc.get("hypothesis_id"),
    "root_cause_name": rc.get("hypothesis"),
    "root_cause_statement": rc.get("statement"),
    "cause_type": rc.get("cause_type"),
    "miss_mechanism": rc.get("miss_mechanism"),
    "miss_mechanism_meaning": rc.get("miss_mechanism_meaning"),
    "direction_coherent": rc.get("direction_coherent"),
    "evidence_resolution": rc.get("evidence_resolution"),
    "confidence_level": cf.get("level"),
    "confidence_pct": cf.get("score_pct"),
    "confidence_before_caps": cf.get("level_before_caps"),
    "confidence_capped_gate": (cf.get("binding_cap") or {}).get("gate"),
    "confidence_dimensions": {d["dimension"]: {"availability": d["availability"],
                                               "score": d.get("score")}
                              for d in (cf.get("dimensions") or [])},
    "criticality": (res.get("criticality") or {}).get("band"),
    "criticality_reading": (res.get("criticality") or {}).get("reading"),
    "card_version": (res.get("decision_card") or {}).get("card_version"),
    "card_sections": sorted(sections.keys()),
    "supporting_evidence_count": len(res.get("supporting_evidence") or []),
    "contradictory_evidence_count": len(res.get("contradictory_evidence") or []),
    "limitations_count": len(res.get("limitations") or []),
    "recommendations": [{"id": r.get("id"), "text": r.get("text"),
                         "follows_mechanism": r.get("follows_mechanism")}
                        for r in (res.get("recommendations") or [])],
    "cross_exam_questions": sum(r.get("questions_asked", 0)
                                for r in (res.get("cross_examination") or [])),
    "challenge_catalogue_version": (res.get("audit") or {}).get("challenge_catalogue_version"),
    "prompt_version": (res.get("audit") or {}).get("prompt_version"),
    "narrative_model": (res.get("audit") or {}).get("narrative_model"),
    "narrative_error": res.get("narrative_error"),
    # what the upgrade added -- absent on the "before" run
    "has_forecast_response": "forecast_response_diagnostic" in res,
    "has_forecastability_gate": "forecastability_gate" in res,
    "has_lagged_driver": "lagged_driver_evidence" in res,
    "has_holiday_response": "holiday_response" in res,
    "has_weekend": "weekend_diagnostic" in res,
    "has_asu_decomposition": "asu_decomposition" in res,
    "has_plan_revision": "plan_revision" in res,
    "has_criticality": "criticality" in res,
    "has_evidence_index": "fc_evidence_index" in res,
    "holiday_phase": hol.get("phase"),
    "holiday_applies": hol.get("applies"),
    "holiday_names": hol.get("names") or hol.get("calendar_names"),
    "holiday_zero_but_adjacent": hol.get("zero_count_but_adjacent"),
    "holiday_capture": (hol.get("forecast_capture") or {}).get("classification"),
    "holiday_consistency": hol.get("historical_consistency"),
    "why_bullets": [(b.get("rank"), (b.get("what_happened") or "")[:170])
                    for b in ((sections.get("12_why_this_happened") or {}).get("bullets") or [])],
    "why_jargon": (sections.get("12_why_this_happened") or {}).get("jargon_found"),
    "evidence_index_available": (res.get("fc_evidence_index") or {}).get("available_count"),
    "evidence_index_total": (res.get("fc_evidence_index") or {}).get("total"),
}

with open(OUTPATH, "w", encoding="utf-8") as fh:
    json.dump(summary, fh, indent=1, default=str)
print(f"[{LABEL}] wrote {OUTPATH}")
print(f"[{LABEL}] status={summary['status']} cause={summary['root_cause_id']} "
      f"mechanism={summary['miss_mechanism']} conf={summary['confidence_level']} "
      f"crit={summary['criticality']} exception={summary['exception']}")
