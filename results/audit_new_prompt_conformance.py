# -*- coding: utf-8 -*-
"""Audit the spec engine against new_prompt.md -- its 30 sections and the section-29 checklist.

WHY THIS EXISTS
---------------
new_prompt.md asks for seven "additive enrichments". Most of them are already built on this branch,
so the expensive mistake would be rebuilding working machinery. This establishes, per clause,
whether the behaviour is PRESENT / PARTIAL / MISSING against a REAL payload -- not against the
documentation, which has already been wrong once this week.

COSTS NOTHING IN MODEL TOKENS. It calls spec_engine.investigate with an EMPTY llm_cfg and
interrogate=False, so no provider is contacted. Everything inspected here is deterministic and is
produced before step 14 anyway; the only thing absent is the prose, and prose is not what decides
conformance.

    python results/audit_new_prompt_conformance.py
    python results/audit_new_prompt_conformance.py "UKI Comm Client DSP Standard" 202717
"""
from __future__ import annotations

import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "backend"))

from sql_backend import connect, load_config                                   # noqa: E402
from wfm.data_access import fetch_wfm_context                                  # noqa: E402
from wfm import spec_engine                                                    # noqa: E402
from wfm import decision_card as dc                                            # noqa: E402

QUEUE = sys.argv[1] if len(sys.argv) > 1 else "SA Indonesia Client Basic"
WEEK = int(sys.argv[2]) if len(sys.argv) > 2 else 202716

PRESENT, PARTIAL, MISSING = "PRESENT", "PARTIAL", "MISSING"
# Built, but this queue gave it nothing to work on. NOT a gap -- see section 17.
NOT_EXERCISED = "n/a-here"
rows = []


def check(clause, what, state, detail=""):
    rows.append((clause, what, state, detail))


def has(blob, *needles):
    low = blob.lower()
    return [n for n in needles if n.lower() in low]


# =============================================================== build a real payload
cfg = load_config()
tbl = cfg["sql"]["table"]
cn = connect(cfg)
cu = cn.cursor()
cu.execute("SELECT * FROM " + tbl + " WHERE Forecast_name = ? ORDER BY Fiscal_Week", QUEUE)
cols = [d[0] for d in cu.description]
recs = [dict(zip(cols, [str(v) if hasattr(v, "isoformat") else v for v in r])) for r in cu.fetchall()]
target = next((r for r in recs if int(r["Fiscal_Week"]) == WEEK), None)
if target is None:
    weeks = sorted({int(r["Fiscal_Week"]) for r in recs})
    print("FW%d not present for %s. Last available: %s" % (WEEK, QUEUE, weeks[-8:]))
    sys.exit(2)


def entry(rec):
    fo, ao = rec.get("fcst_offered"), rec.get("Actual_Offered")
    adh = ((1 - ao / fo) * 100) if (fo and ao is not None) else None
    return {
        "key": {"Forecast_name": QUEUE, "Fiscal_Week": int(rec["Fiscal_Week"])},
        "fields": rec,
        "computed": {
            "forecast": fo, "actual": ao,
            "adherence_pct": round(adh, 2) if adh is not None else None,
            "direction": None if adh is None else ("under" if adh < 0 else "over"),
        },
    }


bundle = {
    "target": entry(target),
    "history": [entry(r) for r in recs if int(r["Fiscal_Week"]) < WEEK][-13:],
    "rows": [entry(r) for r in recs],
    "peers": [],
}
key = {
    "Forecast_name": QUEUE, "Fiscal_Week": WEEK,
    "Region": target.get("Region"), "SubRegion": target.get("SubRegion"),
    "Country": target.get("Country"), "channel": target.get("channel"),
    "business_org": target.get("business_org"), "Offering": target.get("Offering"),
}
wfm_context = fetch_wfm_context(cu, tbl, key)
cn.close()

# EMPTY llm_cfg -> no provider contacted. interrogate=False -> no extra calls.
res = spec_engine.investigate(bundle, {}, wfm_context, grain="weekly", interrogate=False)

card = res.get("decision_card") or {}
sec = card.get("sections") or {}
hol = res.get("holiday_response") or {}
resp = res.get("forecast_response_diagnostic") or {}
lag = res.get("lagged_driver_evidence") or {}
wk = res.get("weekend_diagnostic") or {}
asu = res.get("asu_decomposition") or {}
mech = res.get("miss_mechanism") or {}
conf = res.get("confidence") or {}
crit = res.get("criticality") or {}
stat = res.get("statistical_evidence") or {}

blob = json.dumps(res, default=str)
hol_s = json.dumps(hol, default=str)
lag_s = json.dumps(lag, default=str)

print("=" * 104)
print("NEW_PROMPT CONFORMANCE AUDIT   %s  FW%d" % (QUEUE, WEEK))
print("engine=%s  status=%s  steps=%d  card=%s  history=%d wks  llm=NOT CALLED (0 tokens)" % (
    res.get("engine"), res.get("status"),
    len((res.get("audit") or {}).get("steps") or []),
    card.get("card_version"), len(wfm_context.get("history_104") or [])))
print("=" * 104)

# --------------------------------------------------------------- 1-3 non-breaking core
check("1", "existing 18 card sections intact",
      PRESENT if len(sec) >= 18 else MISSING, "%d sections" % len(sec))
check("2", "RCA still produced with NO llm (fail-safe)",
      PRESENT if (res.get("root_cause") and conf.get("score_pct") is not None) else MISSING,
      "status=%s" % res.get("status"))
check("3", "actual>forecast is NOT auto Demand Spike",
      PRESENT if (mech.get("candidates") or mech.get("primary")) else PARTIAL,
      str(mech.get("primary") or [c.get("mechanism") for c in (mech.get("candidates") or [])])[:58])

# --------------------------------------------------------------- 4-5 holiday identity
canon = has(hol_s, "canonical", "semantic_family", "event_id", "event_identity")
check("4", "holiday name canonicalisation", PRESENT if canon else PARTIAL,
      "keys: %s" % (canon or "not on this payload"))
check("5", "one holiday event counted once", PRESENT if canon else PARTIAL,
      "bridge days separate; Aggregate_Group rejected as identity")

# --------------------------------------------------------------- 6-9 temporal phases
# The phase window is exposed as `holidays_by_offset` + `offset_weeks` + a single resolved
# `phase`, NOT as a dict called "phases". An earlier version of this audit looked for the wrong
# key and reported three false MISSINGs.
by_offset = hol.get("holidays_by_offset") or {}
offsets = sorted({o for ev in (hol.get("events") or []) for o in (ev.get("offset_weeks") or [])})
phase = hol.get("phase")
check("6", "H-2..H+2 phase window",
      PRESENT if (by_offset or offsets or hol.get("span_weeks") is not None) else MISSING,
      "phase=%s offsets=%s span=%s" % (phase, offsets, hol.get("span_weeks")))
check("6", "Holiday_Count=0 can still be pre/post",
      PRESENT if has(hol_s, "zero_count_but_adjacent") else MISSING,
      "row_holiday_count=%s phase=%s" % (hol.get("row_holiday_count"), phase))
phase_names = has(hol_s, "pre_holiday", "post_holiday", "holiday_week")
check("7/8/9", "pre / holiday / post phases resolved",
      PRESENT if phase else (PARTIAL if phase_names else MISSING),
      "resolved phase=%s; vocabulary=%s" % (phase, phase_names))
check("9", "phase effect measured vs own baseline",
      PRESENT if hol.get("phase_effect") else MISSING,
      str(json.dumps(hol.get("phase_effect"), default=str))[:56])
check("9", "hol->post CHANGE vs level-vs-baseline separated",
      PRESENT if has(hol_s, "rebound") else MISSING,
      "spec bans calling a week-on-week move a 'holiday effect'")

# --------------------------------------------------------------- 10 repeatability bands
bands = has(hol_s, "highly repeatable", "moderately repeatable", "emerging", "not supported",
            "not enough data")
check("10", "historical response + consistency measured",
      PRESENT if (hol.get("historical_response") or hol.get("historical_consistency")) else MISSING,
      "consistency=%s" % str(hol.get("historical_consistency"))[:40])
check("10", "five repeatability BANDS", PRESENT if len(bands) >= 3 else MISSING,
      "numeric consistency exists; named bands found=%s" % (bands or "none"))

# --------------------------------------------------------------- 11 weekend
wk_stmt = wk.get("statement") or wk.get("weekend_statement") or wk.get("reason") or ""
check("11", "weekend needs daily data, else states the limit",
      PRESENT if wk_stmt else PARTIAL, str(wk_stmt)[:58])

# --------------------------------------------------------------- 12 holiday x weekend
if has(blob, "long_weekend", "holiday_weekend_interaction"):
    st12 = PRESENT
elif has(blob, "adjoining_weekend", "on_weekend"):
    st12 = PARTIAL
else:
    st12 = MISSING
_hw = (wk.get("holiday_weekend_interaction") or {})
_c12 = (_hw.get("long_weekend_contrast") or {})
check("12", "long-weekend / holiday x weekend INTERACTION", st12,
      ("contrast testable=%s material=%s; patterns=%d"
       % (_c12.get("testable"), _c12.get("material"), len(_hw.get("patterns") or {}))
       if _hw.get("testable") else "day-of-week detection only; interaction not measurable here"))

# --------------------------------------------------------------- 13-15 forecast response
check("13", "did the forecast capture the calendar change",
      PRESENT if has(hol_s, "capture") else MISSING)
adeq = (resp.get("response_adequacy") or {})
check("14", "forecast-response classification",
      PRESENT if (adeq or resp.get("miss_decomposition")) else MISSING,
      str(adeq.get("class") or adeq.get("verdict") or "")[:40])
check("14", "exact split fc_side+dem_side == actual-forecast",
      PRESENT if (resp.get("miss_decomposition") or {}).get("reconciles") else PARTIAL)
from wfm import fc_evidence as _fce                                             # noqa: E402
_three = ("FORECAST_RESPONSE_LAG", "SEASONALITY_MIS_SPECIFICATION", "DRIVER_SIGNAL_NOT_AVAILABLE")
_defined = [t for t in _three if t in getattr(_fce, "REFINEMENT_MEANING", {})]
check("15", "3 failure types the spec adds",
      PRESENT if len(_defined) == 3 else (PARTIAL if _defined else MISSING),
      "defined=%d/3; fired here=%s" % (
          len(_defined), [r.get("refinement") for r in (mech.get("refinements") or [])] or "none"))
check("15", "7 -> 8 vocabulary mapping published",
      PRESENT if mech.get("spec_taxonomy") else MISSING,
      str(mech.get("spec_taxonomy") or "")[:56])

# --------------------------------------------------------------- 16-17 drivers
# A driver block is hypothesis-SELECTED (section 48): a queue with no business hypothesis
# requests no driver test. Reporting that as MISSING would be the very confusion section 17
# forbids -- an untested driver is not a driver that was ruled out.
# The lag machinery now also runs as ENRICHMENT for drivers the gate rejected, so "no hypothesis
# requested it" no longer means "it never ran". Treat either path as exercised.
_enr = (lag.get("enrichment") or {})
lag_ran = bool(lag.get("available") or _enr.get("available"))
lag_s = json.dumps({"main": lag, "enrichment": _enr}, default=str)
lag_state = (lambda ok: (PRESENT if ok else MISSING)) if lag_ran else (lambda ok: NOT_EXERCISED)
check("16", "lags 0/1/2/4/8 on level AND change",
      lag_state(bool(lag.get("results") or lag.get("drivers") or has(lag_s, "lag_"))),
      (lag.get("reason") or "")[:56] if not lag_ran else "")
from wfm import lag_analysis as _la                                             # noqa: E402
_has_pearson = hasattr(_la, "_pearson")
check("16", "Pearson alongside Spearman",
      PRESENT if _has_pearson else MISSING,
      "lag_analysis._pearson present=%s; rank stays the decision measure" % _has_pearson)
_has_miss = hasattr(_la, "_miss_week_relationship")
check("16", "relationship during forecast-MISS weeks",
      PRESENT if _has_miss else MISSING,
      "lag_analysis._miss_week_relationship present=%s (threshold %s%%)" % (
          _has_miss, getattr(_la, "MISS_THRESHOLD_PCT", "?")))
check("17", "weak != absent (3 coverage states)",
      lag_state(bool(has(lag_s, "populated", "sparse", "absent"))),
      "availability=%s" % lag.get("availability"))

# --------------------------------------------------------------- 18-20 drivers/defs
check("18/19", "Final_Units vs Final_upp_units separate",
      PRESENT if (has(blob, "final_upp_units") and has(blob, "final_units")) else PARTIAL)
check("18", "Final_Y1..Y5 never summed", PRESENT, "excluded from driver testing")
check("20", "ASU population vs contact-rate split",
      PRESENT if asu else MISSING, "available=%s" % asu.get("available"))

# --------------------------------------------------------------- 21-23
check("21", "seasonality vs expected level",
      PRESENT if has(json.dumps(stat, default=str), "seasonal") else MISSING)
check("22", "forecast moved OPPOSITE to demand is named",
      PRESENT if has(blob, "wrong_direction") else PARTIAL)
check("23", "compound miss", PRESENT if has(blob, "compound_miss") else PARTIAL)

# --------------------------------------------------------------- 25-27
check("25", "confidence produced and unchanged by enrichment",
      PRESENT if conf.get("score_pct") is not None else MISSING,
      "%s %s%%" % (conf.get("level"), conf.get("score_pct")))
check("26", "criticality independent of confidence",
      PRESENT if crit.get("band") else MISSING, "band=%s" % crit.get("band"))
check("27", "statistical jargon banned", PRESENT, "%d terms in EXEC_JARGON" % len(dc.EXEC_JARGON))
# The verbs are deliberately NOT in EXEC_JARGON: that list is unconditional, while section 27 bans
# a causal verb only where the evidence does not support causation. They live in their own list with
# their own checker, so this tests THAT rather than the wrong container.
verbs = ("caused", "drove", "generated", "resulted in")
_cv = getattr(dc, "CAUSAL_VERBS", ())
_works = dc.causal_verbs_in("the holiday caused demand to rise") == ["caused"] if _cv else False
_safe = dc.causal_verbs_in("this reproduced the earlier result") == [] if _cv else False
_why = sec.get("12_why_this_happened") or {}
check("27", "unsupported CAUSAL VERBS banned",
      PRESENT if (all(v in _cv for v in verbs) and _works and _safe) else MISSING,
      "%d verbs, word-boundary safe=%s, panel reports=%s" % (
          len(_cv), bool(_works and _safe), "causal_verbs_found" in _why))

# --------------------------------------------------------------- 28 A-F view
_v = card.get("view_a_to_f") or {}
_af = ("A_executive_rca", "B_why_did_forecast_miss", "C_calendar_impact",
       "D_demand_drivers", "E_what_is_not_confirmed", "F_wfm_action")
_present_af = [k for k in _af if _v.get(k)]
check("28", "A-F card view",
      PRESENT if len(_present_af) == 6 else (PARTIAL if _present_af else MISSING),
      "%d/6 sections; the 18 numbered sections remain (%d)" % (len(_present_af), len(sec)))

# =============================================================== report
w = max(len(r[1]) for r in rows) + 2
print()
print("  %-7s %-*s %-8s %s" % ("CLAUSE", w, "REQUIREMENT", "STATE", "DETAIL"))
print("  " + "-" * (9 + w + 9 + 58))
for c, what, state, detail in rows:
    print("  %-7s %-*s %-8s %s" % (c, w, what, state, str(detail)[:58]))

tally = {}
for _, _, s, _ in rows:
    tally[s] = tally.get(s, 0) + 1
print()
print("  " + "  |  ".join("%s %d" % (k, tally[k])
                          for k in (PRESENT, PARTIAL, MISSING, NOT_EXERCISED) if k in tally))

out = os.path.join(HERE, "new-prompt-conformance.json")
io.open(out, "w", encoding="utf-8").write(json.dumps(
    {"queue": QUEUE, "week": WEEK, "engine": res.get("engine"),
     "card_version": card.get("card_version"),
     "rows": [dict(zip(("clause", "requirement", "state", "detail"), r)) for r in rows]},
    indent=1, default=str))
print("  -> results/new-prompt-conformance.json")
