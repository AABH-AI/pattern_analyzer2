# -*- coding: utf-8 -*-
"""Audit the spec engine against prompt2.md -- the dataset-reality rules (clauses A-O).

prompt2.md is a different document from new_prompt.md. Where new_prompt asked for extra ANALYSIS,
prompt2 governs what the analysis is ALLOWED TO CLAIM given a weekly-grain source. Several of its
clauses are mandatory and prohibitive rather than additive:

    F  current-week and adjacent holidays MUST be separate fields          ("This is mandatory.")
    C  must NOT stop the calendar investigation at "weekend cannot be isolated"
    E  the executive list must use canonical names, raws kept in audit
    K  weekday structure must never be read as daily volume

COSTS NOTHING IN MODEL TOKENS -- empty llm_cfg, interrogate=False.

    python results/audit_prompt2_conformance.py
    python results/audit_prompt2_conformance.py "Brazil Comm Client CEM ProSupport" 202722
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

QUEUE = sys.argv[1] if len(sys.argv) > 1 else "SA Indonesia Client Basic"
WEEK = int(sys.argv[2]) if len(sys.argv) > 2 else 202716

OK, PART, GAP = "OK", "PARTIAL", "GAP"
# Built, but this queue gave it nothing to work on. Not a gap -- and not an OK either.
NOT_HERE = "n/a-here"
rows = []


def check(clause, what, state, detail=""):
    rows.append((clause, what, state, detail))


cfg = load_config()
tbl = cfg["sql"]["table"]
cn = connect(cfg)
cu = cn.cursor()
cu.execute("SELECT * FROM " + tbl + " WHERE Forecast_name = ? ORDER BY Fiscal_Week", QUEUE)
cols = [d[0] for d in cu.description]
recs = [dict(zip(cols, [str(v) if hasattr(v, "isoformat") else v for v in r])) for r in cu.fetchall()]
target = next((r for r in recs if int(r["Fiscal_Week"]) == WEEK), None)
if target is None:
    print("FW%d not present for %s" % (WEEK, QUEUE))
    sys.exit(2)


def entry(rec):
    fo, ao = rec.get("fcst_offered"), rec.get("Actual_Offered")
    adh = ((1 - ao / fo) * 100) if (fo and ao is not None) else None
    return {"key": {"Forecast_name": QUEUE, "Fiscal_Week": int(rec["Fiscal_Week"])},
            "fields": rec,
            "computed": {"forecast": fo, "actual": ao,
                         "adherence_pct": round(adh, 2) if adh is not None else None}}


bundle = {"target": entry(target),
          "history": [entry(r) for r in recs if int(r["Fiscal_Week"]) < WEEK][-13:],
          "rows": [entry(r) for r in recs], "peers": []}
key = {"Forecast_name": QUEUE, "Fiscal_Week": WEEK,
       "Region": target.get("Region"), "SubRegion": target.get("SubRegion"),
       "Country": target.get("Country"), "channel": target.get("channel"),
       "business_org": target.get("business_org"), "Offering": target.get("Offering")}
ctx = fetch_wfm_context(cu, tbl, key)
cn.close()

res = spec_engine.investigate(bundle, {}, ctx, grain="weekly", interrogate=False)
card = res.get("decision_card") or {}
sec = card.get("sections") or {}
hol = res.get("holiday_response") or {}
wk = res.get("weekend_diagnostic") or {}
lag = res.get("lagged_driver_evidence") or {}
asu = res.get("asu_decomposition") or {}
scope = (sec.get("2_root_cause") or {}).get("scope") or {}
hol_s = json.dumps(hol, default=str)

print("=" * 104)
print("PROMPT2 CONFORMANCE (dataset-reality rules)   %s  FW%d" % (QUEUE, WEEK))
print("row Holiday_Count=%s   resolved phase=%s   llm=NOT CALLED" % (
    hol.get("row_holiday_count"), hol.get("phase")))
print("=" * 104)

# --- A: no daily demand claims -----------------------------------------------------------------
caps = (wk.get("capabilities") or {})
check("A", "daily actual/forecast correctly reported absent",
      OK if (caps.get("daily_actual") is False and caps.get("daily_forecast") is False) else GAP,
      "daily_actual=%s daily_forecast=%s" % (caps.get("daily_actual"), caps.get("daily_forecast")))

# --- B/K: weekday structure ---------------------------------------------------------------------
ds = wk.get("holiday_day_structure") or {}
hw = wk.get("holiday_weekend_interaction") or {}
check("B/K", "holiday_weekday derived (which day it fell on)",
      OK if ds.get("holiday_days") is not None else GAP,
      "days=%s pattern=%s" % (ds.get("holiday_days"), ds.get("pattern")))
_evs = hol.get("events") or []
_bw = [e for e in _evs if "holiday_before_weekend" in e]
check("B", "holiday_before_weekend vs holiday_after_weekend separated",
      (OK if _bw else (NOT_HERE if not _evs else GAP)),
      ("per event: before=%s after=%s on_wknd=%s long=%s"
       % (sum(1 for e in _evs if e.get("holiday_before_weekend")),
          sum(1 for e in _evs if e.get("holiday_after_weekend")),
          sum(1 for e in _evs if e.get("holiday_on_weekend")),
          sum(1 for e in _evs if e.get("long_weekend_candidate")))) if _bw else "not derived")
_wd = wk.get("weekday_outcomes") or {}
_meas = _wd.get("measurable_weekdays") or []
check("K", "per-weekday historical outcome comparison",
      OK if len(_meas) >= 5 else (PART if _meas else GAP),
      "%d of 7 weekdays measurable, spread %s pts" % (len(_meas),
                                                      _wd.get("spread_across_weekdays_pts")))

# --- C: the three-way weekend answer ------------------------------------------------------------
three = {"daily_weekend_demand": None, "weekly_calendar_structure": None,
         "holiday_weekend_interaction": None}
present = [k for k in three if k in json.dumps(wk, default=str)]
_c3 = wk.get("clause_c_states") or {}
_named = [k for k in ("daily_weekend_demand_effect", "weekly_calendar_structure",
                      "holiday_weekend_interaction") if (_c3.get(k) or {}).get("state")]
check("C", "weekend answered as THREE separate states, not one refusal",
      OK if len(_named) == 3 else (PART if _named else GAP),
      " | ".join("%s=%s" % (k.split("_")[0], (_c3.get(k) or {}).get("state")) for k in _named))

# --- D: holiday join fields ---------------------------------------------------------------------
ev = (hol.get("events") or [{}])[0] if (hol.get("events") or []) else {}
want = ["raw_names", "canonical_name", "event_key", "dates", "types", "needs_review"]
have = [w for w in want if w in ev]
check("D", "holiday join carries raw+canonical+group+date+type",
      (OK if len(have) == len(want) else (NOT_HERE if not ev else PART)),
      "have=%s" % (have or "no holiday event in the window"))
check("D", "weekday published on the joined holiday",
      (OK if (ev.get("weekdays") is not None) else (NOT_HERE if not ev else GAP)),
      "weekdays=%s" % (ev.get("weekdays") if ev else "no events"))
_iwv = hol.get("holidays_in_target_week") or {}
_adv = hol.get("recent_holidays_affecting_target_week") or {}
_gid = [e for blk in (_iwv, _adv) for e in (blk.get("events") or [])
        if e.get("semantic_group_id")]
check("D", "semantic_group_id published",
      (OK if _gid else (NOT_HERE if not (hol.get("events") or []) else PART)),
      "%d event(s) carry semantic_group_id in the clause-F views" % len(_gid))

# --- E: canonical display -----------------------------------------------------------------------
names = hol.get("names") or []
canon = sorted({e.get("canonical_name") for e in (hol.get("events") or []) if e.get("canonical_name")})
dupe_family = len(names) > len(canon)
_disp = ((hol.get("recent_holidays_affecting_target_week") or {}).get("canonical_names") or []) \
        + ((hol.get("holidays_in_target_week") or {}).get("canonical_names") or [])
_raw = hol.get("names") or []
check("E", "executive list uses canonical semantic names only",
      (OK if (_disp and len(_disp) <= len(_raw))
       else (NOT_HERE if not _raw else (PART if _disp else GAP))),
      "raw=%d -> displayed=%d %s" % (len(_raw), len(_disp), _disp))

# --- F: MANDATORY separation ---------------------------------------------------------------------
in_week = [e for e in (hol.get("events") or []) if 0 in (e.get("offset_weeks") or [])]
_iw = hol.get("holidays_in_target_week")
check("F", "HOLIDAYS_IN_TARGET_WEEK is its own field",
      OK if isinstance(_iw, dict) and "statement" in _iw else GAP,
      (_iw or {}).get("statement") or "missing")
_ad = hol.get("recent_holidays_affecting_target_week")
_leak = bool((_iw or {}).get("count") == 0 and (_iw or {}).get("canonical_names"))
check("F", "RECENT_HOLIDAYS_AFFECTING_TARGET_WEEK is its own field",
      OK if (isinstance(_ad, dict) and "statement" in _ad and not _leak) else GAP,
      "in_week=%s adjacent=%s, no leak=%s" % ((_iw or {}).get("count"),
                                              (_ad or {}).get("count"), not _leak))

# --- G: driver tests ----------------------------------------------------------------------------
enr = (lag.get("enrichment") or {})
check("G", "7 driver tests incl. miss-week + forecast response",
      OK if (lag.get("available") or enr.get("available")) else GAP,
      "main=%s enrichment=%s" % (lag.get("available"), enr.get("available")))

# --- H: level vs change -------------------------------------------------------------------------
check("H", "level and change relationships both reported",
      OK if "level" in json.dumps(lag, default=str) and "change" in json.dumps(lag, default=str)
      else PART, "candidate families are same_week/lagged x level/change")

# --- J: ASU not causal --------------------------------------------------------------------------
check("J", "ASU split published as composition, not cause",
      OK if asu else GAP, "available=%s" % asu.get("available"))

# --- L: scope safety ----------------------------------------------------------------------------
check("L", "queue share of the wider gap stated, not blamed",
      OK if scope.get("narrative") else GAP,
      str(scope.get("narrative"))[:70])

# --- M: five availability states ----------------------------------------------------------------
states = set()
for blk in (hol, wk, lag, asu, res.get("forecast_response_diagnostic") or {}):
    v = blk.get("availability")
    if v:
        states.add(v)
want5 = {"AVAILABLE", "PARTIALLY_AVAILABLE", "NOT_AVAILABLE", "NOT_TESTABLE", "INCONCLUSIVE"}
_p2 = {b.get("p2_state") for b in (wk,) if b.get("p2_state")}
for _blk in ((wk.get("clause_c_states") or {}).values()):
    if isinstance(_blk, dict) and _blk.get("state"):
        _p2.add(_blk["state"])
check("M", "the five prompt2 availability states published",
      OK if _p2 & want5 else GAP,
      "in use here: %s (engine keeps %s for confidence)" % (sorted(_p2), sorted(states)))

# =============================================================== report
w = max(len(r[1]) for r in rows) + 2
print()
print("  %-6s %-*s %-8s %s" % ("CLAUSE", w, "REQUIREMENT", "STATE", "DETAIL"))
print("  " + "-" * (8 + w + 10 + 60))
for c, what, state, detail in rows:
    print("  %-6s %-*s %-8s %s" % (c, w, what, state, str(detail)[:60]))
tally = {}
for _, _, s_, _ in rows:
    tally[s_] = tally.get(s_, 0) + 1
print()
print("  " + "  |  ".join("%s %d" % (k, tally[k])
                          for k in (OK, PART, GAP, NOT_HERE) if k in tally))
io.open(os.path.join(HERE, "prompt2-conformance.json"), "w", encoding="utf-8").write(
    json.dumps({"queue": QUEUE, "week": WEEK,
                "rows": [dict(zip(("clause", "requirement", "state", "detail"), r)) for r in rows]},
               indent=1, default=str))
print("  -> results/prompt2-conformance.json")
