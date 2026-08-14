# -*- coding: utf-8 -*-
"""Run the REAL spec_engine.investigate() offline against real rows, with NO model.

    python results/run_offline_spec.py

WHY THIS EXISTS ALONGSIDE THE LIVE VALIDATION
---------------------------------------------
It needs no VPN and no API key, so it is the loop you can actually run on every change. And because
`llm_cfg` has no providers, it exercises the section 37 fallback on every case: the narrative must
fail and the RCA must still be complete. That is the path that was returning HTTP 500 on this branch
before the two arity bugs were fixed.

It also PRODUCES the capture that two other checks depend on:
  * results/check_ui_render.js renders these responses through the real renderDecisionCard
  * results/test_fc_spec_semantics.py scenario 24 uses the Indonesian case as a regression

Data comes from results/offline_source.py -- a local SQLite mirror of the source spreadsheet, built
with `python results/offline_source.py --build`. The mirror is gitignored: it is a copy of the client
demand data, which .gitignore already refuses to commit in spreadsheet form.

Cases are SELECTED to span the states worth exercising, and each selection requires a LATE target
week -- history is `Fiscal_Week <= target`, so an early week has almost none and every scenario would
collapse onto DATA_LIMITATION.
"""
import json
import os
import sys

ROOT = (r"d:\OneDrive - Aligned Automation Services Private Limited\Documents\RCAspec"
        r"\pattern_analyzer2")
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, os.path.join(ROOT, "results"))

import offline_source                                        # noqa: E402
from wfm import spec_engine                                  # noqa: E402
from wfm.common import adherence_pct, num                    # noqa: E402
from wfm.data_access import _HISTORY_COLS, _LADDER_LEVELS    # noqa: E402

conn = offline_source.connect()
cur = conn.cursor()
table = offline_source.TABLE

CASES = json.loads(os.environ.get("CASES", "[]")) or None


def pick_cases(limit=8):
    """A deliberate spread. `deep` restricts to queues with real history, because a queue with
    four weeks of actuals cannot exercise precedent, lag or seasonal expectation -- it only ever
    lands on DATA_LIMITATION, which proves the honest path but nothing else."""
    cur.execute(f"SELECT Forecast_name FROM {table} WHERE Actual_Offered IS NOT NULL "
                f"GROUP BY Forecast_name HAVING COUNT(*) >= 104")
    deep = {r[0] for r in cur.fetchall()}
    print(f"queues with >=104 weeks of actuals: {len(deep)}")

    def q(sql, params=(), label="", want=1, require_deep=True):
        cur.execute(sql, params)
        got = []
        for name, week in [(r[0], int(r[1])) for r in cur.fetchall()]:
            if require_deep and name not in deep:
                continue
            got.append((name, week, label))
            if len(got) >= want:
                break
        return got

    out = []
    out += q(f"SELECT Forecast_name, Fiscal_Week FROM {table} WHERE Fiscal_Week >= 202600 AND fcst_offered > 200 "
             f"AND Actual_Offered > fcst_offered * 1.3 ORDER BY Actual_Offered - fcst_offered DESC",
             (), "under-forecast, deep history", 2)
    out += q(f"SELECT Forecast_name, Fiscal_Week FROM {table} WHERE Fiscal_Week >= 202600 AND fcst_offered > 200 "
             f"AND Actual_Offered < fcst_offered * 0.7 ORDER BY fcst_offered - Actual_Offered DESC",
             (), "over-forecast, deep history", 2)
    out += q(f"SELECT Forecast_name, Fiscal_Week FROM {table} WHERE Fiscal_Week >= 202600 AND Holiday_Count > 0 "
             f"AND fcst_offered > 100 AND ABS(1 - Actual_Offered / fcst_offered) > 0.15 "
             f"ORDER BY ABS(Actual_Offered - fcst_offered) DESC",
             (), "holiday week, deep history", 1)
    out += q(f"SELECT Forecast_name, Fiscal_Week FROM {table} WHERE Fiscal_Week >= 202600 AND Actual_ASU IS NOT NULL "
             f"AND Planned_ASU IS NOT NULL AND fcst_offered > 200 "
             f"AND ABS(1 - Actual_Offered / fcst_offered) > 0.20 "
             f"ORDER BY ABS(Actual_Offered - fcst_offered) DESC",
             (), "ASU both present, deep history", 1)
    out += q(f"SELECT Forecast_name, Fiscal_Week FROM {table} WHERE Fiscal_Week >= 202600 AND Country IS NULL "
             f"AND fcst_offered > 50 AND ABS(1 - Actual_Offered / fcst_offered) > 0.30",
             (), "blank country (holiday NotApplicable)", 1, require_deep=False)
    out += q(f"SELECT Forecast_name, Fiscal_Week FROM {table} WHERE Fiscal_Week >= 202600 AND fcst_offered > 50 "
             f"AND ABS(1 - Actual_Offered / fcst_offered) > 0.30",
             (), "sparse history (DATA_LIMITATION path)", 1, require_deep=False)
    # De-duplicate on (name, week) so one queue cannot fill the whole spread.
    seen, uniq = set(), []
    for name, week, label in out:
        if (name, week) in seen:
            continue
        seen.add((name, week))
        uniq.append((name, week, label))
    return uniq[:limit]


def bundle(name, week):
    cur.execute(f"SELECT * FROM {table} WHERE Forecast_name = ? AND Fiscal_Week = ?", (name, week))
    row = cur.fetchone()
    fields = dict(zip([d[0] for d in cur.description], row))

    cur.execute(f"SELECT TOP 157 {', '.join(_HISTORY_COLS)} FROM {table} "
                f"WHERE Forecast_name = ? AND Fiscal_Week <= ? ORDER BY Fiscal_Week DESC",
                (name, week))
    hc = [d[0] for d in cur.description]
    history = [dict(zip(hc, r)) for r in cur.fetchall()][::-1]

    ladder = []
    for label, group in _LADDER_LEVELS:
        if any(fields.get(g) in (None, "") for g in group):
            continue
        where = " AND ".join(f"{g} = ?" for g in group)
        cur.execute(f"SELECT SUM(Actual_Offered), SUM(fcst_offered), COUNT(*) FROM {table} "
                    f"WHERE Fiscal_Week = ? AND {where} AND fcst_offered IS NOT NULL "
                    f"AND fcst_offered <> 0", tuple([week] + [fields[g] for g in group]))
        r = cur.fetchone()
        if not r or r[1] in (None, 0):
            continue
        act, fc, n = float(r[0] or 0), float(r[1]), int(r[2] or 0)
        ladder.append({"level": label, "scope": " / ".join(str(fields[g]) for g in group),
                       "actual_offered": round(act, 1), "fcst_offered": round(fc, 1),
                       "adherence_pct": round(adherence_pct(act, fc), 1),
                       "queue_weeks_in_scope": n})

    actual, forecast = num(fields["Actual_Offered"]), num(fields["fcst_offered"])
    ctx_bundle = {"target": {
        "key": {k: fields.get(k) for k in ("Forecast_name", "Fiscal_Week", "Region", "SubRegion",
                                           "Country", "channel", "business_org", "Offering")},
        "fields": fields,
        "computed": {"actual": actual, "forecast": forecast,
                     "adherence_pct": adherence_pct(actual, forecast)}}}
    wfm_ctx = {"history_104": history, "ladder": ladder,
               "ladder_verdict": {"levels": ladder, "band_pct": 5.0}}
    return ctx_bundle, wfm_ctx


failures = 0
results = {}
for name, week, label in (CASES or pick_cases()):
    print("=" * 100)
    print(f"{label.upper()}: {name} FW{week}")
    print("=" * 100)
    cb, wc = bundle(name, week)
    try:
        res = spec_engine.investigate(cb, {"providers": {}}, wc, grain="weekly",
                                      interrogate=False)
    except Exception as exc:
        failures += 1
        import traceback
        traceback.print_exc()
        continue

    results[f"{name}|{week}"] = res
    fs = res.get("forecast_summary") or {}
    rc = res.get("root_cause") or {}
    conf = res.get("confidence") or {}
    crit = res.get("criticality") or {}
    mech = res.get("miss_mechanism") or {}
    print(f"  status={res.get('status')}  engine={res.get('engine')}")
    print(f"  adherence={fs.get('adherence_pct')}%  gap={fs.get('absolute_variance_contacts')}")
    print(f"  steps recorded: {len((res.get('audit') or {}).get('steps') or [])}")
    print(f"  ROOT CAUSE      {rc.get('hypothesis_id')} {rc.get('hypothesis')}")
    print(f"  MECHANISM       {rc.get('miss_mechanism')} (compound={rc.get('compound')})")
    print(f"                  supported: {rc.get('miss_mechanisms_supported')}")
    print(f"  direction ok    {rc.get('direction_coherent')}")
    print(f"  evidence res.   {rc.get('evidence_resolution')}   ids={rc.get('evidence_ids')}")
    print(f"  CONFIDENCE      {conf.get('level')} ({conf.get('score_pct')}%) "
          f"before caps {conf.get('level_before_caps')} "
          f"capped={conf.get('capped')} gate={(conf.get('binding_cap') or {}).get('gate')}")
    for d in conf.get("dimensions") or []:
        print(f"      {d['dimension']:24s} {d['availability']:14s} {d.get('score')}")
    print(f"  CRITICALITY     {crit.get('band')} (from {crit.get('band_before_lifts')}) "
          f"gap={crit.get('absolute_gap_contacts')} rel={crit.get('relative_gap')}")
    print(f"  x-exam          {len(res.get('cross_examination') or [])} report(s), "
          f"{sum(r['questions_asked'] for r in res.get('cross_examination') or [])} questions, "
          f"catalogue v{(res.get('audit') or {}).get('challenge_catalogue_version')}")
    print(f"  hypotheses      {(res.get('hypotheses') or {}).get('summary')}")
    print(f"  supporting={len(res.get('supporting_evidence') or [])} "
          f"contradictory={len(res.get('contradictory_evidence') or [])}")
    print(f"  recommendations:")
    for r in res.get("recommendations") or []:
        print(f"      [{r['priority']:6s}] {r['id']:12s} {r['text'][:110]}")
    print(f"  limitations ({len(res.get('limitations') or [])}):")
    for l in (res.get("limitations") or [])[:6]:
        print(f"      - {str(l)[:120]}")
    idx = res.get("fc_evidence_index") or {}
    print(f"  evidence index  {idx.get('available_count')}/{idx.get('total')}")
    print(f"  new keys present: "
          f"{[k for k in ('forecast_response_diagnostic','forecastability','lagged_driver_evidence','holiday_response','weekend_diagnostic','asu_decomposition','plan_revision','miss_mechanism','criticality','evidence_resolution','fc_evidence_index') if k in res]}")
    print(f"  decision_card sections: {sorted((res.get('decision_card') or {}).get('sections', {}).keys())}")
    print()

os.makedirs(os.path.join(ROOT, "results", "_offline_cache"), exist_ok=True)
out = os.path.join(ROOT, "results", "_offline_cache", "spec-offline-results.json")
with open(out, "w", encoding="utf-8") as fh:
    json.dump(results, fh, default=str, indent=1)
print(f"wrote {out}  ({len(results)} case(s), {failures} failure(s))")
sys.exit(1 if failures else 0)
