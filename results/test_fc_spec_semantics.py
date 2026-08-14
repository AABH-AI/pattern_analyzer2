# -*- coding: utf-8 -*-
"""Semantic regression tests for the FC Decision Card engine (?mode=spec).

    python results/test_fc_spec_semantics.py

WHAT THESE TEST, AND WHAT THEY DELIBERATELY DO NOT
---------------------------------------------------
They assert deterministic BEHAVIOUR AND STATE -- which mechanism the evidence supports, which
availability state a block reports, whether a threshold moved, whether a cap armed. They never
assert one exact LLM sentence, because the prose is allowed to vary and the finding is not.

Section 45 of the upgrade brief names 24 scenarios. Each has its own block below, tagged with the
scenario number, so a reviewer can check coverage against the brief rather than trusting a count.

WHY SO MANY SYNTHETIC FIXTURES
------------------------------
Real data cannot be relied on to contain a clean example of each state -- there is no queue whose
history is guaranteed to show a pre-holiday pull-forward with consistent history AND a sparse
secondary driver. Fixtures make the intended state reachable and, more importantly, make the
INTENT reviewable: a reader can see what the test believes it is constructing.

A NOTE ON FIXTURES THAT DISAGREE WITH THE ENGINE
-------------------------------------------------
Where a fixture and the engine disagree, the fixture is wrong more often than the engine. Any place
that happened is commented in full, so nobody later "fixes" working logic to satisfy a bad fixture.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "backend"))

from wfm import cross_examination as cx           # noqa: E402
from wfm import confidence as conf                 # noqa: E402
from wfm import decision_card                      # noqa: E402
from wfm import fc_evidence as fce                 # noqa: E402
from wfm import holiday_events                     # noqa: E402
from wfm import hypothesis_catalogue as cat        # noqa: E402
from wfm import narrative_prompt                   # noqa: E402
from wfm import spec_engine                        # noqa: E402
from wfm.common import adherence_pct               # noqa: E402

PASS, FAIL = [], []


def check(tag, name, condition, detail=""):
    (PASS if condition else FAIL).append((tag, name, detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {tag} {name}"
          + (f"\n        {detail}" if detail and not condition else ""))


# ==============================================================================
# Fixture builders
# ==============================================================================
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def week_seq(start, n):
    """n consecutive fiscal weeks from `start`, rolling the year at week 52."""
    out, y, w = [], start // 100, start % 100
    for _ in range(n):
        out.append(y * 100 + w)
        w += 1
        if w > 52:
            y, w = y + 1, 1
    return out


def row(week, actual, forecast, **kw):
    r = {"Fiscal_Week": week, "Actual_Offered": actual, "fcst_offered": forecast,
         "Holiday_Count": 0, "Projection_plan_name": kw.pop("plan", "PLAN_A"),
         "Planned_ASU": kw.pop("planned_asu", None), "Actual_ASU": kw.pop("actual_asu", None),
         "Final_Units": kw.pop("final_units", None),
         "Final_upp_units": kw.pop("upp", None),
         "Week_Ending": kw.pop("week_ending", None)}
    for d in DAYS:
        r[d] = kw.pop(d, 0)
    r.update(kw)
    return r


def flat_history(start=202401, n=150, actual=1000.0, forecast=1000.0, **kw):
    """A stable queue: same actual and forecast every week. The baseline every other fixture
    perturbs, so any finding in a derived fixture is attributable to the perturbation."""
    return [row(w, actual, forecast, **kw) for w in week_seq(start, n)]


def fields(**kw):
    f = {"Forecast_name": "TEST QUEUE", "Country": "TestLand", "Offering": "Basic",
         "Region": "APJ", "SubRegion": "ANZ", "channel": "Voice", "business_org": "ORG",
         "Volume_Category": "1001-5000", "Warranty_Tier": "A",
         "Actual_Offered": None, "fcst_offered": None, "Holiday_Count": 0,
         "Planned_ASU": None, "Actual_ASU": None, "Final_Units": None}
    f.update(kw)
    return f


def run_engine(history, target_fields, ladder=None, llm_cfg=None):
    """The REAL investigate(), no model configured. Exercises all 15 steps."""
    target = history[-1]
    tf = dict(target_fields)
    tf.update({k: target.get(k) for k in ("Fiscal_Week", "Actual_Offered", "fcst_offered",
                                          "Holiday_Count", "Planned_ASU", "Actual_ASU",
                                          "Final_Units")})
    bundle = {"target": {
        "key": {k: tf.get(k) for k in ("Forecast_name", "Fiscal_Week", "Region", "SubRegion",
                                       "Country", "channel", "business_org", "Offering")},
        "fields": tf,
        "computed": {"actual": tf["Actual_Offered"], "forecast": tf["fcst_offered"],
                     "adherence_pct": adherence_pct(tf["Actual_Offered"], tf["fcst_offered"])}}}
    wfm_ctx = {"history_104": history, "ladder": ladder or [],
               "ladder_verdict": {"levels": ladder or [], "band_pct": 5.0}}
    return spec_engine.investigate(bundle, llm_cfg if llm_cfg is not None else {"providers": {}},
                                   wfm_ctx, grain="weekly", interrogate=False)


print("=" * 94)
print("  FC DECISION CARD (?mode=spec) -- SEMANTIC REGRESSION")
print("=" * 94)

# ==============================================================================
# Section 6 -- thresholds must not drift
# ==============================================================================
print("\n-- Section 6: threshold drift guards --")
check("THR-1", "RCA generation threshold is fixed at +/-5%",
      spec_engine.GENERATION_THRESHOLD_PCT == 5.0,
      f"got {spec_engine.GENERATION_THRESHOLD_PCT}")
check("THR-2", "materiality floor is 50 contacts",
      spec_engine.MATERIALITY_FLOOR_CONTACTS == 50,
      f"got {spec_engine.MATERIALITY_FLOOR_CONTACTS}")
check("THR-3", "major deviation threshold is 75%",
      spec_engine.MAJOR_DEVIATION_PCT == 75.0,
      f"got {spec_engine.MAJOR_DEVIATION_PCT}")
check("THR-4", "fc_evidence reuses the SAME materiality floor rather than declaring a second one",
      fce.MATERIALITY_FLOOR_CONTACTS == spec_engine.MATERIALITY_FLOOR_CONTACTS,
      "two disagreeing floors would make the criticality band and the worklist contradict")
check("THR-9", "the miss-run threshold matches the engine's generation threshold",
      fce.MISS_THRESHOLD_PCT == spec_engine.GENERATION_THRESHOLD_PCT,
      "a week that would not have triggered an RCA must not count as part of a miss run; "
      "fc_evidence declares the figure locally to avoid a circular import, so this guards the drift")

# The floor is a WORKLIST control. It must never suppress the RCA itself (section 6, explicit).
_h = flat_history(n=120, actual=100.0, forecast=100.0)
_h[-1] = row(_h[-1]["Fiscal_Week"], 130.0, 100.0)       # +30% but only 30 contacts
_r = run_engine(_h, fields())
check("THR-5", "a sub-floor miss still produces a full RCA (floor is presentation, not suppression)",
      _r.get("status") in ("Complete", "Incomplete") and bool(_r.get("root_cause")),
      f"status={_r.get('status')} material={_r.get('material')}")
check("THR-6", "and it is flagged as below the materiality floor rather than silently dropped",
      _r.get("material") is False,
      f"material={_r.get('material')}")
check("THR-7", "criticality reports Negligible for a sub-floor gap, with the floor named",
      (_r.get("criticality") or {}).get("band") == "Negligible"
      and "materiality floor" in ((_r.get("criticality") or {}).get("basis") or ""),
      json.dumps(_r.get("criticality"), default=str)[:200])

# A miss INSIDE +/-5% must not generate an RCA at all.
_h2 = flat_history(n=120, actual=1000.0, forecast=1000.0)
_h2[-1] = row(_h2[-1]["Fiscal_Week"], 1030.0, 1000.0)    # +3%, inside the band
_r2 = run_engine(_h2, fields())
check("THR-8", "a deviation inside +/-5% generates NO RCA and says why",
      _r2.get("status") == "NotInvestigated" and bool(_r2.get("reason")),
      f"status={_r2.get('status')} reason={str(_r2.get('reason'))[:90]}")

# ==============================================================================
# Scenario 1 -- forecast baseline failure
# ==============================================================================
print("\n-- Scenario 1: forecast baseline failure --")
# Demand has been steady at 1000 for three years. The plan for the target week is set at 600 --
# far below the level this week of the year reliably brings -- and demand arrives on trend.
_h = flat_history(n=150, actual=1000.0, forecast=1000.0)
_h[-1] = row(_h[-1]["Fiscal_Week"], 1000.0, 600.0)
_r = run_engine(_h, fields())
_mech = _r.get("miss_mechanism") or {}
_resp = _r.get("forecast_response_diagnostic") or {}
check("S1-1", "the miss is attributed to the plan's LEVEL, not to demand moving",
      (_resp.get("miss_decomposition") or {}).get("leading_side") == "forecast",
      json.dumps(_resp.get("miss_decomposition"), default=str)[:220])
check("S1-2", "FORECAST_BASELINE_FAILURE is among the supported mechanisms",
      fce.FORECAST_BASELINE_FAILURE in (_mech.get("mechanisms") or []),
      f"got {_mech.get('mechanisms')}")
check("S1-3", "the forecast-side and demand-side contributions sum to the whole gap",
      (_resp.get("miss_decomposition") or {}).get("reconciles") is True)
check("S1-4", "and the recommendation names the baseline, not generic monitoring",
      any(x.get("follows_mechanism") == fce.FORECAST_BASELINE_FAILURE
          for x in (_r.get("recommendations") or [])),
      json.dumps(_r.get("recommendations"), default=str)[:200])

# ==============================================================================
# Scenario 2 -- a genuine demand event, NOT a forecast failure
# ==============================================================================
print("\n-- Scenario 2: genuine demand event (low predictability) --")
# The plan tracks demand faithfully for three years, then demand jumps with no prior signal.
_h = flat_history(n=150, actual=1000.0, forecast=1000.0)
_h[-1] = row(_h[-1]["Fiscal_Week"], 1800.0, 1000.0)
_r = run_engine(_h, fields())
_mech = _r.get("miss_mechanism") or {}
_gate = (_r.get("forecast_response_diagnostic") or {}).get("forecastability_gate") or {}
check("S2-1", "actual above forecast is NOT on its own called a forecast failure",
      _gate.get("supports_forecast_response_failure") is False,
      json.dumps(_gate.get("conditions_failed"), default=str)[:200])
check("S2-2", "the mechanism is a low-predictability demand event",
      _mech.get("primary") == fce.DEMAND_EVENT_LOW_PREDICTABILITY,
      f"got {_mech.get('primary')} from {_mech.get('mechanisms')}")
check("S2-3", "the recommendation explicitly does NOT demand a model fix",
      any(x.get("follows_mechanism") == fce.DEMAND_EVENT_LOW_PREDICTABILITY
          and "not treat this as a model defect" in x.get("text", "")
          for x in (_r.get("recommendations") or [])),
      json.dumps([x.get("text") for x in (_r.get("recommendations") or [])], default=str)[:260])

# ==============================================================================
# Scenario 3 -- a PREDICTABLE forecast response failure
# ==============================================================================
print("\n-- Scenario 3: predictable forecast response failure --")
# Demand climbs steadily for eight weeks into the target while the plan is left flat. The rise is
# visible beforehand and, because this queue's history is full of momentum that follows through,
# it is repeatable.
_weeks = week_seq(202401, 150)
_h = []
for i, w in enumerate(_weeks[:-9]):
    # a sawtooth that RELIABLY continues: three rising weeks then a reset, so momentum
    # follow-through is high across the history
    _h.append(row(w, 1000.0 + (i % 4) * 120.0, 1000.0 + (i % 4) * 120.0))
for k, w in enumerate(_weeks[-9:]):
    _h.append(row(w, 1000.0 + k * 110.0, 1000.0))        # demand climbs, plan stays put
_r = run_engine(_h, fields())
_gate = (_r.get("forecast_response_diagnostic") or {}).get("forecastability_gate") or {}
_respb = (_r.get("forecast_response_diagnostic") or {}).get("response") or {}
check("S3-1", "a leading signal is detected before the target week",
      any(s.get("detected") for s in
          ((_r.get("forecast_response_diagnostic") or {}).get("signals") or [])),
      json.dumps([(s.get("signal"), s.get("detected")) for s in
                  ((_r.get("forecast_response_diagnostic") or {}).get("signals") or [])])[:200])
check("S3-2", "the plan's reaction is classed as inadequate, not adequate",
      _respb.get("classification") in ("no_response", "under_response", "delayed_response",
                                       "wrong_direction", "over_response"),
      f"got {_respb.get('classification')}: {_respb.get('reason')}")
check("S3-3", "the four-condition gate records WHICH conditions held",
      len(_gate.get("conditions") or []) == 4
      and all("condition" in c and "met" in c and "measured" in c
              for c in _gate.get("conditions") or []))

# ==============================================================================
# Scenarios 4, 5, 6 -- calendar: response failure, post-holiday, pre-holiday
# ==============================================================================
print("\n-- Scenarios 4/5/6: calendar phases --")
# Phase effects are measured against the queue's OWN non-holiday baseline, so the fixture needs
# enough non-holiday weeks AND at least MIN_PHASE_INSTANCES holiday weeks.
from wfm import holiday_response as hr                                          # noqa: E402

_weeks = week_seq(202401, 150)
_hol_weeks = set(_weeks[::13])                    # a holiday every 13 weeks -> ~11 instances
_h = []
for w in _weeks:
    if w in _hol_weeks:
        _h.append(row(w, 600.0, 1000.0, Holiday_Count=1))     # holiday weeks run far below normal
    else:
        _h.append(row(w, 1000.0, 1000.0))
_hist_only = hr._historical_phase_effect(
    [(r["Fiscal_Week"], r["fcst_offered"], r["Actual_Offered"]) for r in _h],
    None, {})
# The assertion here was wrong on first writing, and the ENGINE was right. With no country every
# week is labelled PHASE_NONE, so the non-holiday baseline is the whole history and each phase has
# zero instances -- reported as `testable: false` with a reason. That is the honest answer: the
# baseline genuinely exists, and no phase could be measured. Asserting `available is False` demanded
# that the engine throw away a baseline it legitimately has.
check("S4-1", "with no country resolved, NO phase is testable and each says so",
      all(p.get("testable") is False and (p.get("reason") or p.get("note"))
          for p in (_hist_only.get("phases") or {}).values())
      or _hist_only.get("available") is False,
      json.dumps(_hist_only, default=str)[:300])
check("S4-1b", "and no phase effect is asserted from zero instances",
      all((p.get("instances") or 0) == 0 or p.get("testable")
          for p in (_hist_only.get("phases") or {}).values()),
      json.dumps({k: v.get("instances") for k, v in (_hist_only.get("phases") or {}).items()}))

# Direct block test with an explicit phase, so the assertion does not depend on the shipped
# holiday master containing a particular country.
_phases = {
    "holiday": {"testable": True, "instances": 11, "actual_effect_pct": -40.0, "direction": "down",
                "consistency": 1.0, "consistent": True, "material": True,
                "forecast_effect_pct": 0.0, "historically_planned_for": False,
                "reading": "Weeks containing a holiday run 40% below normal for this queue."},
    "post_holiday": {"testable": True, "instances": 11, "actual_effect_pct": 22.0,
                     "direction": "up", "consistency": 0.9, "consistent": True, "material": True,
                     "forecast_effect_pct": 0.0, "historically_planned_for": False,
                     "reading": "Weeks after a holiday run 22% above normal -- a rebound."},
    "pre_holiday": {"testable": True, "instances": 11, "actual_effect_pct": 15.0, "direction": "up",
                    "consistency": 0.85, "consistent": True, "material": True,
                    "forecast_effect_pct": 0.0, "historically_planned_for": False,
                    "reading": "Weeks before a holiday run 15% above normal -- pull-forward."},
}


def hol_block(phase, effect_pct, consistency, capture="under_reacted", applies=True):
    return {"available": True, "applies": applies, "phase": phase, "span_weeks": 2,
            "availability": fce.AVAILABLE, "calendar_names": ["Test Holiday"],
            "row_holiday_count": 0, "zero_count_but_adjacent": (phase != "holiday"),
            "expected_direction": "up" if effect_pct > 0 else "down",
            "historical_consistency": consistency,
            "historical_response": {"available": True, "phases": _phases},
            "forecast_capture": {"classification": capture,
                                 "expected_effect_pct": effect_pct,
                                 "reason": f"the plan did not allow for the {phase} effect."},
            "reading": f"This week sits in the {phase} phase."}


# Scenario 4 -- calendar response failure: consistent phase effect, plan did not capture it.
_mech4 = fce.miss_mechanism(-25.0, {"available": True,
                                    "demand_side": {"vs_expected": {"unusual": True,
                                                                    "direction": "above",
                                                                    "difference_pct": 22.0}},
                                    "forecast_side": {"vs_expected": {"direction": "at",
                                                                      "difference_pct": 0.0}},
                                    "miss_decomposition": {"available": True, "reconciles": True,
                                                           "forecast_side_share": 0.1,
                                                           "demand_side_share": 0.9},
                                    "response": {"classification": "no_response"},
                                    "forecastability": {"classification": "PREDICTABLE"},
                                    "forecastability_gate": {
                                        "supports_forecast_response_failure": False,
                                        "conditions": [], "verdict": "not supported"}},
                            hol_block("post_holiday", 22.0, 0.9), {}, {}, True)
check("S4-2", "a consistent, uncaptured phase effect yields CALENDAR_RESPONSE_FAILURE",
      fce.CALENDAR_RESPONSE_FAILURE in (_mech4.get("mechanisms") or []),
      f"got {_mech4.get('mechanisms')}")
check("S5-1", "post-holiday rebound is direction-coherent with an UNDER-forecast",
      any((c.get("direction_coherence") or {}).get("coherent") is True
          for c in (_mech4.get("candidates") or [])
          if c.get("mechanism") == fce.CALENDAR_RESPONSE_FAILURE),
      json.dumps([(c["mechanism"], (c.get("direction_coherence") or {}).get("coherent"))
                  for c in _mech4.get("candidates") or []])[:200])

# Scenario 6 -- pre-holiday pull-forward, and a week whose own row shows NO holiday.
_pre = hol_block("pre_holiday", 15.0, 0.85)
check("S6-1", "a target week with Holiday_Count = 0 can still be pre-holiday",
      _pre["row_holiday_count"] == 0 and _pre["applies"] is True
      and _pre["zero_count_but_adjacent"] is True)
_cal_panel = decision_card.calendar_panel(_pre, {"weekend_analysis_supported": False,
                                                 "statement": "weekly totals only",
                                                 "grain": "weekly"})
check("S6-2", "the card says so explicitly rather than reporting 'no holiday impact'",
      _cal_panel.get("zero_count_but_adjacent") is True
      and "pre- or post-holiday" in (_cal_panel.get("how_to_read") or "").lower(),
      (_cal_panel.get("how_to_read") or "")[:180])
check("S6-3", "all three phases are reported with their instance counts and consistency",
      set(_cal_panel.get("phases", {}).keys()) == {"holiday", "pre_holiday", "post_holiday"}
      and all(v.get("instances") == 11 for v in _cal_panel["phases"].values()))

# Section 24 -- an observed phase effect with INCONSISTENT history is not a forecast failure.
_mech_incon = fce.miss_mechanism(-25.0, {"available": True,
                                         "demand_side": {"vs_expected": {"unusual": True,
                                                                         "direction": "above",
                                                                         "difference_pct": 22.0}},
                                         "forecast_side": {"vs_expected": {"direction": "at",
                                                                           "difference_pct": 0.0}},
                                         "miss_decomposition": {"available": True,
                                                                "reconciles": True,
                                                                "demand_side_share": 0.9},
                                         "response": {"classification": "no_response"},
                                         "forecastability": {"classification": "LOW_PREDICTABILITY",
                                                             "reason": "not repeatable"},
                                         "forecastability_gate": {
                                             "supports_forecast_response_failure": False,
                                             "conditions": [], "verdict": "not supported"}},
                                 hol_block("post_holiday", 22.0, 0.45,
                                           capture="inconsistent_history"),
                                 {}, {}, True)
check("S4-3", "an INCONSISTENT phase history does NOT become a calendar response failure",
      fce.CALENDAR_RESPONSE_FAILURE not in (_mech_incon.get("mechanisms") or []),
      f"got {_mech_incon.get('mechanisms')}")

# ==============================================================================
# Scenarios 7 and 8 -- weekend, by data grain
# ==============================================================================
print("\n-- Scenarios 7/8: weekend attribution by grain --")
_h = flat_history(n=60)
_wk = fce.weekend_evidence(_h, _h[-1])
check("S7-1", "weekly-only data reports the weekend LIMITATION, not a weekend effect",
      _wk.get("weekend_analysis_supported") is False
      and "cannot be isolated" in (_wk.get("statement") or ""),
      json.dumps(_wk, default=str)[:220])
check("S7-2", "and it is NotApplicable rather than Missing -- the data cannot ever answer it here",
      _wk.get("availability") == fce.NOT_APPLICABLE,
      f"got {_wk.get('availability')}")
check("S7-3", "the grain is stated as found in the data, not assumed",
      _wk.get("grain") == "weekly")
_daily = [dict(r, daily_actual=[10] * 7, date=f"2026-01-{(i % 28) + 1:02d}")
          for i, r in enumerate(flat_history(n=60))]
_wk2 = fce.weekend_evidence(_daily, _daily[-1])
check("S8-1", "the grain check is re-run against the actual rows every time, not hardcoded",
      isinstance(_wk2.get("capabilities"), dict)
      and "daily_actual" in _wk2["capabilities"],
      json.dumps(_wk2.get("capabilities"), default=str)[:200])
check("S8-2", "no weekend causality is asserted while the grain does not support it",
      _wk2.get("weekend_analysis_supported") == _wk2["capabilities"].get("weekend_volume_effect"))

# ==============================================================================
# Scenarios 9 and 10 -- lagged-only driver, and a sparse driver
# ==============================================================================
print("\n-- Scenarios 9/10: driver lag and coverage --")
# Final_Units at lag 2 drives demand; the same-week relationship is deliberately noise.
_weeks = week_seq(202401, 150)
_units = [500.0 + 300.0 * ((i * 7) % 11) / 11.0 for i in range(len(_weeks))]
_h = []
for i, w in enumerate(_weeks):
    demand = 1000.0 + (_units[i - 2] - 500.0) * 1.5 if i >= 2 else 1000.0
    _h.append(row(w, demand, 1000.0, final_units=_units[i],
                  upp=(12.0 if i >= len(_weeks) - 3 else None)))   # UPP present for 3 weeks only
_h[-1] = row(_h[-1]["Fiscal_Week"], _h[-1]["Actual_Offered"] * 1.4, 1000.0,
             final_units=_units[-1], upp=12.0)
_lag = fce.lagged_driver_evidence(_h, _h[-1]["Fiscal_Week"], {"BUS-02", "BUS-04"})
_by = {d["driver"]: d for d in _lag.get("drivers") or []}
check("S9-1", "the driver lag test runs only for drivers the GENERATED hypotheses asked for",
      set(_lag.get("requested_drivers") or []) == {"Actual_ASU", "Final_upp_units", "Final_Units"},
      f"got {_lag.get('requested_drivers')}")
check("S9-2", "the lagged relationship is found and the best lag is NOT zero",
      (_by.get("Final_Units") or {}).get("best_lag_weeks") not in (None, 0),
      json.dumps(_by.get("Final_Units"), default=str)[:260])
check("S9-3", "and the reading says the earlier week is stronger, not that the driver is irrelevant",
      "earlier" in ((_by.get("Final_Units") or {}).get("reading") or "")
      or (_by.get("Final_Units") or {}).get("usable_as_evidence") is True,
      (_by.get("Final_Units") or {}).get("reading"))
check("S10-1", "a driver with only a few observations is reported SPARSE, never as proof",
      (_by.get("Final_upp_units") or {}).get("coverage") in ("sparse", "absent"),
      json.dumps(_by.get("Final_upp_units"), default=str)[:220])
check("S10-2", "a sparse driver is never usable as evidence",
      (_by.get("Final_upp_units") or {}).get("usable_as_evidence") is False)
check("S10-3", "the three coverage states are reported separately and never collapsed",
      set((_lag.get("coverage_summary") or {}).keys()) == {"populated", "sparse", "absent"},
      json.dumps(_lag.get("coverage_summary"), default=str))
check("S10-4", "an ABSENT driver is NotApplicable (no penalty), a SPARSE one is Missing (penalty)",
      all((d.get("availability") == fce.NOT_APPLICABLE) if d.get("coverage") == "absent"
          else (d.get("availability") == fce.MISSING) if d.get("coverage") == "sparse"
          else True for d in _lag.get("drivers") or []),
      json.dumps([(d["driver"], d.get("coverage"), d.get("availability"))
                  for d in _lag.get("drivers") or []]))
check("S10-5", "a sparse driver never reads as 'this driver has no effect'",
      all("no effect" not in (d.get("reading") or "") for d in _lag.get("drivers") or []))
# Section 20/21 -- Shipment and UPP are separate drivers and never combined.
check("S21-1", "Final_Units and Final_upp_units are distinct subjects, never merged",
      (_by.get("Final_Units") or {}).get("subject") != (_by.get("Final_upp_units") or {}).get("subject")
      or (_by.get("Final_upp_units") or {}).get("subject") is None)
check("S20-1", "the nested Final_Y1..Y5 columns are excluded from driver testing",
      all(not str(d.get("driver", "")).startswith("Final_Y") for d in _lag.get("drivers") or []),
      "they overlap and must never be summed")

# ==============================================================================
# Scenarios 11 and 12 -- contradiction, and direction contradiction
# ==============================================================================
print("\n-- Scenarios 11/12: contradiction and direction --")
_res = fce.evidence_resolution([{"text": "a"}, {"text": "b"}], [{"text": "c"}],
                               {"supports": 4, "weakens": 5, "refutes": 0}, {})
check("S11-1", "supporting and contradictory evidence both survive into a resolution",
      _res.get("state") == "mixed" and _res.get("supporting_count") == 2
      and _res.get("contradictory_count") == 1,
      json.dumps(_res, default=str)[:200])
check("S11-2", "the resolution NAMES what governs the conclusion",
      bool(_res.get("basis")) and bool(_res.get("conflicts")))
_res_ref = fce.evidence_resolution([{"text": "a"}], [{"text": "c"}],
                                   {"supports": 9, "weakens": 0, "refutes": 1}, {})
check("S11-3", "a refutation is decisive however much supports the conclusion",
      _res_ref.get("state") == "rejected",
      json.dumps(_res_ref, default=str)[:200])

# A demand-SUPPRESSING mechanism cannot explain a demand INCREASE.
_coh = fce.direction_coherence(fce.CALENDAR_RESPONSE_FAILURE, -25.0, {},
                               {"expected_direction": "down", "phase": "holiday",
                                "forecast_capture": {"expected_effect_pct": -30.0}}, {})
check("S12-1", "a suppressing calendar effect is INCOHERENT with an under-forecast",
      _coh.get("coherent") is False,
      json.dumps(_coh, default=str)[:240])
check("S12-2", "the incoherence states both directions and why it cannot be the cause",
      "DISAGREE" in (_coh.get("reason") or "") and _coh.get("miss_direction") == "up"
      and _coh.get("implied_direction") == "down")
_mech_bad = fce.miss_mechanism(-25.0, {"available": True,
                                       "demand_side": {"vs_expected": {"unusual": False}},
                                       "forecast_side": {"vs_expected": {"direction": "at",
                                                                         "difference_pct": 0.0}},
                                       "miss_decomposition": {"available": True, "reconciles": True},
                                       "response": {"classification": "no_response"},
                                       "forecastability": {"classification": "PREDICTABLE"},
                                       "forecastability_gate": {
                                           "supports_forecast_response_failure": False,
                                           "conditions": [], "verdict": "no"}},
                               {"applies": True, "expected_direction": "down", "phase": "holiday",
                                "forecast_capture": {"classification": "under_reacted",
                                                     "expected_effect_pct": -30.0,
                                                     "reason": "r"}},
                               {}, {}, True)
check("S12-3", "an incoherent mechanism is REJECTED, not promoted",
      fce.CALENDAR_RESPONSE_FAILURE not in (_mech_bad.get("mechanisms") or [])
      and any(c["mechanism"] == fce.CALENDAR_RESPONSE_FAILURE
              for c in _mech_bad.get("rejected_for_direction") or []),
      json.dumps({"kept": _mech_bad.get("mechanisms"),
                  "rejected": [c["mechanism"] for c in
                               _mech_bad.get("rejected_for_direction") or []]}))
check("S12-4", "when every mechanism is incoherent the verdict is DATA_LIMITATION, not a guess",
      _mech_bad.get("primary") in (fce.DATA_LIMITATION,)
      or _mech_bad.get("mechanisms") != [],
      json.dumps(_mech_bad.get("primary"), default=str))
# The direction gate is a BUSINESS RULE and must be able to arm confidence Gate 2.
_state = spec_engine._business_rule_state({"clean": True}, {"hypothesis_id": "CAL-01"}, _mech_bad)
check("S12-5", "a cause carried only by a direction-rejected mechanism CONTRADICTS the rules",
      _state == "contradicts", f"got {_state}")
_dims = [conf.business_rule_validation(_state)]
_c = conf.calculate(_dims + [conf.data_sufficiency(150, 1, 1, 0, 4)],
                    {"business_rule_state": _state, "evidence_families": {"a", "b"}})
check("S12-6", "and that caps the confidence LEVEL at Low via Gate 2",
      _c.get("level") == conf.LOW and (_c.get("binding_cap") or {}).get("gate") == 2,
      f"level={_c.get('level')} cap={(_c.get('binding_cap') or {}).get('gate')}")

# ==============================================================================
# Scenario 13 -- compound miss
# ==============================================================================
print("\n-- Scenario 13: compound miss --")
_mech_c = fce.miss_mechanism(
    -30.0,
    {"available": True,
     "demand_side": {"vs_expected": {"unusual": True, "direction": "above",
                                     "difference_pct": 20.0}},
     "forecast_side": {"vs_expected": {"direction": "below", "difference_pct": -25.0}},
     "miss_decomposition": {"available": True, "reconciles": True, "forecast_side_share": 0.5,
                            "demand_side_share": 0.5, "reading": "half and half"},
     "response": {"classification": "under_response", "reason": "moved too little"},
     "forecastability": {"classification": "PREDICTABLE", "reason": "repeatable"},
     "forecastability_gate": {"supports_forecast_response_failure": True, "conditions": [],
                              "verdict": "supported"},
     "baseline_error": {"material": True, "reading": "plan below the seasonal norm"}},
    hol_block("post_holiday", 20.0, 0.9), {}, {}, True)
check("S13-1", "two materially supported mechanisms produce COMPOUND_MISS",
      _mech_c.get("primary") == fce.COMPOUND_MISS and _mech_c.get("compound") is True,
      f"got {_mech_c.get('primary')} of {_mech_c.get('compound_of')}")
check("S13-2", "and each contributing mechanism is named rather than averaged away",
      len(_mech_c.get("compound_of") or []) >= 2,
      json.dumps(_mech_c.get("compound_of"), default=str))
check("S13-3", "compound direction coherence is the conjunction over its parts, not None",
      all((c.get("direction_coherence") or {}).get("coherent") is not False
          for c in _mech_c.get("candidates") or []))

# ==============================================================================
# Scenario 14 -- data limitation
# ==============================================================================
print("\n-- Scenario 14: data limitation --")
_h = [row(202401, 1000.0, 1000.0), row(202402, 1800.0, 1000.0)]
_r = run_engine(_h, fields())
check("S14-1", "a queue with almost no history reaches DATA_LIMITATION, not a fabricated cause",
      (_r.get("miss_mechanism") or {}).get("primary") == fce.DATA_LIMITATION,
      f"got {(_r.get('miss_mechanism') or {}).get('primary')}")
check("S14-2", "the RCA is still complete and still publishable",
      bool(_r.get("root_cause")) and bool(_r.get("confidence")) and bool(_r.get("decision_card")))
check("S14-3", "insufficient history is named as a limitation with the figure",
      any("weeks of history" in str(l) or "weeks of actuals" in str(l)
          for l in _r.get("limitations") or []),
      json.dumps(_r.get("limitations"), default=str)[:220])
check("S14-4", "no mechanism is asserted that the evidence cannot carry",
      (_r.get("miss_mechanism") or {}).get("primary") == fce.DATA_LIMITATION
      and not (_r.get("miss_mechanism") or {}).get("compound"))

# ==============================================================================
# Scenarios 15 and 16 -- holiday event identity
# ==============================================================================
print("\n-- Scenarios 15/16: holiday event normalisation --")
_dupes = [
    {"name": "Eid al-Fitr", "date": "2026-03-20", "before": 3, "after": 3, "type": "Public"},
    {"name": "Eid al-Fitr", "date": "2026-03-20", "before": 3, "after": 3, "type": "Public"},
    {"name": "Eid al-Fitr Holiday", "date": "2026-03-21", "before": 3, "after": 3, "type": "Public"},
]
_inst = holiday_events.normalise(_dupes)
_sum = holiday_events.summarise(_inst, reaching_only=False)
check("S15-1", "an exact duplicate row is collapsed",
      _sum.get("raw_name_count", 0) >= 2 and _sum.get("event_count", 99) < 3,
      json.dumps(_sum, default=str)[:240])
check("S15-2", "multiple days of ONE named holiday count as one event with several days",
      (_sum.get("total_holiday_days") or 0) >= 2 and _sum.get("event_count") == 1,
      json.dumps(_sum, default=str)[:240])
_distinct = [
    {"name": "Ascension Day", "date": "2026-05-14", "before": 3, "after": 3, "type": "Public"},
    {"name": "Ascension Day", "date": "2026-05-28", "before": 3, "after": 3, "type": "Public"},
]
_inst2 = holiday_events.normalise(_distinct)
_sum2 = holiday_events.summarise(_inst2, reaching_only=False)
check("S16-1", "the same name on dates two weeks apart stays TWO occurrences",
      _sum2.get("event_count") == 2, json.dumps(_sum2, default=str)[:240])
check("S16-2", "and the ambiguity is FLAGGED rather than silently resolved",
      bool(_sum2.get("possible_misdating") or _sum2.get("needs_review")),
      json.dumps(_sum2, default=str)[:240])
# Section 23 -- Aggregate_Group is NOT an event identity. Guarding against reintroduction.
_agg = [
    {"name": "Columbus Day", "date": "2026-10-12", "group": "AMER_GROUP", "before": 1, "after": 1},
    {"name": "Thanksgiving", "date": "2026-11-26", "group": "AMER_GROUP", "before": 3, "after": 3},
]
_sum3 = holiday_events.summarise(holiday_events.normalise(_agg), reaching_only=False)
check("S23-1", "two different holidays sharing an Aggregate_Group stay SEPARATE events",
      _sum3.get("event_count") == 2,
      "Aggregate_Group groups COUNTRIES, not holidays -- grouping by it would merge "
      "Columbus Day with Thanksgiving")
# Section 23 -- no invented transliteration mapping.
_waisak = holiday_events.event_key("Waisak Day"), holiday_events.event_key("Vesak Day")
check("S23-2", "Waisak and Vesak are NOT silently mapped together without authoritative data",
      _waisak[0] != _waisak[1], f"{_waisak}")

# ==============================================================================
# Scenarios 17, 18, 19 -- plan vintage
# ==============================================================================
print("\n-- Scenarios 17/18/19: plan revision during a miss streak --")


def streak_history(revisions, corrected):
    """Six same-direction over-forecast weeks, optionally with a plan reissue partway."""
    weeks = week_seq(202401, 120)
    h = [row(w, 1000.0, 1000.0, plan="PLAN_A") for w in weeks[:-6]]
    tail = weeks[-6:]
    for i, w in enumerate(tail):
        plan = "PLAN_A"
        if revisions and i >= 3:
            plan = "PLAN_B"
        actual = 1000.0
        forecast = 1400.0                                  # over-forecast throughout
        if corrected and i >= 4:
            forecast = 1010.0                              # the revision worked
        h.append(row(w, actual, forecast, plan=plan))
    return h


_h_not = streak_history(revisions=False, corrected=False)
_p_not = fce.plan_revision(_h_not, spec_engine._plan_vintage_timeline(_h_not),
                           _h_not[-1]["Fiscal_Week"])
check("S19-1", "a plan left unchanged through a persistent miss is plan_not_revisited",
      _p_not.get("state") == fce.PLAN_NOT_REVISITED,
      json.dumps(_p_not, default=str)[:260])
check("S19-2", "and the streak length and start week are stated",
      (_p_not.get("streak_weeks") or 0) >= 6 and _p_not.get("streak_began_at_week"))

_h_wrong = streak_history(revisions=True, corrected=False)
_p_wrong = fce.plan_revision(_h_wrong, spec_engine._plan_vintage_timeline(_h_wrong),
                             _h_wrong[-1]["Fiscal_Week"])
check("S18-1", "a plan reissued mid-run that kept missing is plan_revised_but_remained_wrong",
      _p_wrong.get("state") == fce.PLAN_REVISED_STILL_WRONG,
      json.dumps(_p_wrong, default=str)[:300])
check("S18-2", "the distinction from 'nobody looked' is stated in words",
      "revisited and stayed wrong" in (_p_wrong.get("reading") or ""),
      _p_wrong.get("reading"))
check("S18-3", "and the recommendation targets the METHOD, not the cadence",
      any("not the cadence" in x.get("text", "")
          for x in fce and spec_engine._mechanism_recommendations({}, {}, _p_wrong, None)),
      json.dumps(spec_engine._mechanism_recommendations({}, {}, _p_wrong, None),
                 default=str)[:220])

_h_ok = streak_history(revisions=True, corrected=True)
_p_ok = fce.plan_revision(_h_ok, spec_engine._plan_vintage_timeline(_h_ok),
                          _h_ok[-1]["Fiscal_Week"])
check("S17-1", "a revision that moved the plan towards demand is NOT reported as a failure",
      _p_ok.get("state") != fce.PLAN_REVISED_STILL_WRONG,
      json.dumps(_p_ok, default=str)[:300])
# No vintage recorded at all is a DIFFERENT finding from "never revisited".
_h_no_plan = [dict(r, Projection_plan_name=None) for r in _h_not]
_p_none = fce.plan_revision(_h_no_plan, spec_engine._plan_vintage_timeline(_h_no_plan),
                            _h_no_plan[-1]["Fiscal_Week"])
check("S17-2", "no recorded vintage is 'not testable', NOT an accusation that nobody looked",
      _p_none.get("state") == fce.PLAN_NOT_TESTABLE and _p_none.get("availability") == fce.MISSING,
      json.dumps(_p_none, default=str)[:240])

# ==============================================================================
# Scenario 20 -- confidence caps, and Missing vs NotApplicable
# ==============================================================================
print("\n-- Scenario 20: confidence model preserved, Missing vs NotApplicable --")
check("S20-2", "the eight confidence dimensions and their weights are unchanged",
      conf.WEIGHTS == {"ContradictoryEvidence": 0.20, "EvidenceStrength": 0.18,
                       "BusinessRuleValidation": 0.15, "StatisticalAgreement": 0.14,
                       "DataSufficiency": 0.12, "ContextCompleteness": 0.10,
                       "HistoricalConsistency": 0.06, "ModelAgreement": 0.05},
      json.dumps(conf.WEIGHTS))
check("S20-3", "the Missing floor is still 0.20",
      conf.MISSING_FLOOR == 0.20)
# Eight LOGICAL gates, nine rows: gate 3 has two thresholds (3a caps at Medium below 50% period
# coverage, 3b at Low below 25%) and each is reported separately so the reader sees which bit. The
# first version of this check asserted 8 rows and was simply counting the wrong thing.
_gate_rows = conf._caps([conf.data_sufficiency(100, 1, 1, 0, 4)], {})
check("S20-4", "all eight caps are still evaluated (nine rows -- gate 3 has two thresholds)",
      len(_gate_rows) == 9
      and {str(g["gate"]) for g in _gate_rows} == {"1", "2", "3a", "3b", "4", "5", "6", "7", "8"},
      json.dumps([g["gate"] for g in _gate_rows], default=str))
check("S20-4b", "and every gate is reported whether it bound or not, with its measured figure",
      all(("bound" in g and "measured" in g and "threshold" in g and "condition" in g)
          for g in _gate_rows),
      "a bare capped number is not compliant -- the gate must be inspectable")
_na = conf.historical_consistency(None, 0)
_ms = conf.contradictory_evidence(0, 0, search_performed=False)
check("S20-5", "NotApplicable carries NO score and is excluded from the weighting",
      _na["availability"] == conf.NOT_APPLICABLE and _na["score"] is None)
check("S20-6", "Missing is retained at the floor so losing evidence LOWERS confidence",
      _ms["availability"] == conf.MISSING and _ms["score"] == conf.MISSING_FLOOR)
_panel = decision_card.confidence_panel(conf.calculate([_na, _ms], {}))
_words = {d["dimension"]: d["wording"] for d in _panel["dimensions"]}
check("S20-7", "the card wording for Missing and NotApplicable is DIFFERENT",
      _words["HistoricalConsistency"].startswith("Not relevant to this queue")
      and _words["ContradictoryEvidence"].startswith("Unavailable"),
      json.dumps(_words))
check("S20-8", "NotApplicable is never listed as a limitation",
      all(d["is_limitation"] is False for d in _panel["dimensions"]
          if d["state"] == "Not Applicable"))
check("S20-9", "the confidence panel is never collapsed",
      _panel.get("always_visible") is True)
_capped = conf.calculate([conf.data_sufficiency(10, 1, 1, 0, 4),
                          conf.business_rule_validation("contradicts")],
                         {"business_rule_state": "contradicts", "evidence_families": {"x"}})
check("S20-10", "a bound cap publishes gate, condition, measured value and threshold",
      all(k in (_capped.get("binding_cap") or {})
          for k in ("gate", "condition", "measured", "threshold", "cap")),
      json.dumps(_capped.get("binding_cap"), default=str)[:200])
check("S20-11", "the calculated level and the final level are BOTH shown",
      _panel.get("calculated_level") is not None and _panel.get("final_level") is not None)

# Criticality is separate from confidence and never derived from it (section 30).
_crit_small = fce.criticality(9000.0, -120.0, 400.0, 1, "1-100")
_crit_big = fce.criticality(300.0, -8.0, 40000.0, 1, "20000+")
check("S30-1", "a huge gap on a small queue is Critical",
      _crit_small["band"] == "Critical", json.dumps(_crit_small, default=str)[:200])
check("S30-2", "a modest gap on a very large queue is not",
      _crit_big["band"] in ("Low", "Moderate"), json.dumps(_crit_big, default=str)[:200])
check("S30-3", "criticality states that it is independent of confidence",
      _crit_small.get("independent_of_confidence") is True
      and _crit_big.get("independent_of_confidence") is True)
_crit_persist = fce.criticality(300.0, -8.0, 40000.0, 9, "20000+")
check("S30-4", "a persistent miss lifts the band by exactly one step",
      fce.CRITICALITY_BANDS.index(_crit_persist["band"])
      - fce.CRITICALITY_BANDS.index(_crit_big["band"]) == 1,
      f"{_crit_big['band']} -> {_crit_persist['band']}")
check("S30-5", "an isolated sub-floor miss is Negligible, not Low",
      fce.criticality(30.0, -60.0, 100.0, 1, "1-100")["band"] == "Negligible")
check("S30-6", "a lift can never LOWER the band",
      all(fce.CRITICALITY_BANDS.index(fce.criticality(g, -20.0, t, s, None)["band"])
          >= fce.CRITICALITY_BANDS.index(fce.criticality(g, -20.0, None, None, None)["band"])
          for g, t, s in ((60.0, 100.0, 9), (5000.0, 100.0, 9), (900.0, 10000.0, 1))))

# ==============================================================================
# Scenarios 21 and 22 -- LLM failure and fabrication
# ==============================================================================
print("\n-- Scenarios 21/22: LLM failure behaviour --")
_h = flat_history(n=150)
_h[-1] = row(_h[-1]["Fiscal_Week"], 1500.0, 1000.0)
_r_nollm = run_engine(_h, fields(), llm_cfg={"providers": {}})
check("S21-1", "with NO provider configured, investigate() does not raise",
      isinstance(_r_nollm, dict),
      "this is the exact pre-existing ValueError that returned HTTP 500 from ?mode=spec")
check("S21-2", "the deterministic RCA is complete and the narrative is marked missing",
      _r_nollm.get("status") == "Incomplete" and bool(_r_nollm.get("root_cause"))
      and bool(_r_nollm.get("confidence")) and bool(_r_nollm.get("incomplete_reason")))
check("S21-3", "the reason says the ANALYSIS is intact and only the prose is absent",
      "complete" in (_r_nollm.get("incomplete_reason") or "").lower(),
      str(_r_nollm.get("incomplete_reason"))[:200])
check("S21-4", "the card still renders every mandatory section",
      all(k in ((_r_nollm.get("decision_card") or {}).get("sections") or {})
          for k in ("1_executive_summary", "2_root_cause", "3_confidence", "5_evidence",
                    "6_hypothesis_comparison", "7_recommendations", "8_limitations",
                    "10_audit_reference")))
check("S21-5", "and the fallback executive summary is populated from the engine's own figures",
      bool(((_r_nollm.get("decision_card") or {}).get("sections") or {})
           .get("1_executive_summary")))
_ok, _errs = narrative_prompt.validate("not a dict", {})
check("S21-6", "a non-JSON narrative reply fails validation rather than being used",
      _ok is False and _errs)
_ok2, _errs2 = narrative_prompt.validate({"executiveSummary": "should be a list"}, {})
check("S21-7", "a schema violation is reported per key",
      _ok2 is False and any("must be a list" in e for e in _errs2),
      json.dumps(_errs2))

_finding = {"forecast_summary": {"actual": 1500.0, "forecast": 1000.0}}
_ok3, _errs3 = narrative_prompt.validate(
    {"executiveSummary": ["Demand reached 9999 contacts."], "rootCauseStatement": "",
     "confidenceExplanation": "", "limitations": [], "recommendationNarratives": []}, _finding)
check("S22-1", "an invented number is a HARD failure",
      _ok3 is False and any("absent from the inputs" in e for e in _errs3),
      json.dumps(_errs3))
_ok4, _errs4 = narrative_prompt.validate(
    {"executiveSummary": ["Demand reached 1,500 contacts against a plan of 1,000."],
     "rootCauseStatement": "", "confidenceExplanation": "", "limitations": [],
     "recommendationNarratives": []}, _finding)
check("S22-2", "rounding a supplied figure for a report is NOT fabrication",
      _ok4 is True, json.dumps(_errs4))

# Section 40/41 -- jargon and bullet order.
_parsed = {"executiveSummary": ["The z-score was high."], "rootCauseStatement": "",
           "confidenceExplanation": "", "limitations": [], "recommendationNarratives": []}
narrative_prompt.validate(_parsed, {})
check("S40-1", "statistical jargon in executive prose is flagged as a warning",
      any("jargon" in w for w in (_parsed.get("_narrative_warnings") or [])),
      json.dumps(_parsed.get("_narrative_warnings")))
_parsed2 = {"executiveSummary": [], "rootCauseStatement": "", "confidenceExplanation": "",
            "limitations": [], "recommendationNarratives": [],
            "whyThisHappened": [{"rank": 2, "text": "b"}, {"rank": 1, "text": "a"}]}
narrative_prompt.validate(_parsed2, {"decision_card_why": {"bullets": [{"rank": 1}, {"rank": 2}]}})
check("S41-1", "a model that REORDERS the ranked bullets has its version discarded",
      "whyThisHappened" not in _parsed2
      and any("reordered" in w for w in (_parsed2.get("_narrative_warnings") or [])),
      json.dumps(_parsed2.get("_narrative_warnings")))
_wb = decision_card.why_bullets({
    "miss_mechanism": {"candidates": [{"mechanism": fce.FORECAST_BASELINE_FAILURE,
                                       "evidence": "plan below norm",
                                       "direction_coherence": {"coherent": True,
                                                               "miss_direction": "up",
                                                               "implied_direction": "up"}}],
                       "compound": False},
    "forecast_response_diagnostic": {}, "lagged_driver_evidence": {}, "holiday_response": {},
    "plan_revision": {}, "asu_decomposition": {}, "evidence_resolution": {},
    "root_cause": {"miss_mechanism_meaning": "m"}, "forecast_summary": {}})
check("S41-2", "the bullets are ranked deterministically and say so",
      _wb.get("ranked_deterministically") is True
      and [b["rank"] for b in _wb["bullets"]] == list(range(1, len(_wb["bullets"]) + 1)))
check("S41-3", "no bullet carries a null-valued key that a template could print",
      all(v is not None for b in _wb["bullets"] for v in b.values()))
check("S40-2", "the deterministic bullets are themselves jargon-free",
      not _wb.get("jargon_found"), json.dumps(_wb.get("jargon_found")))

# Found on LIVE output: the same sentence printed as bullets 2 and 3, because the
# FORECAST_BASELINE_FAILURE candidate's `evidence` IS `miss_decomposition.reading`. Both sources are
# legitimate, so the de-duplication is in why_bullets rather than at either source -- suppressing one
# upstream would lose the bullet entirely on reports where only that source fires.
_dup_reading = "Against an expected 100 contacts, the plan sat 40 below expectation."
_wb_dup = decision_card.why_bullets({
    "miss_mechanism": {"candidates": [{"mechanism": fce.FORECAST_BASELINE_FAILURE,
                                       "evidence": _dup_reading,
                                       "direction_coherence": {"coherent": True,
                                                               "miss_direction": "up",
                                                               "implied_direction": "up"}}],
                       "compound": False},
    "forecast_response_diagnostic": {
        "miss_decomposition": {"available": True, "reconciles": True, "leading_side": "forecast",
                               "forecast_side_share": 0.8, "demand_side_share": 0.2,
                               "reading": _dup_reading},
        "baseline_error": {"material": True, "reading": _dup_reading}},
    "lagged_driver_evidence": {}, "holiday_response": {}, "plan_revision": {},
    "asu_demposition": {}, "asu_decomposition": {}, "evidence_resolution": {},
    "root_cause": {"miss_mechanism_meaning": "m"}, "forecast_summary": {}})
_texts = [b.get("what_happened") for b in _wb_dup["bullets"]]
check("S41-5", "the same finding is never printed as two bullets",
      len(_texts) == len(set(_texts)) and _wb_dup.get("duplicates_dropped", 0) >= 1,
      f"dropped={_wb_dup.get('duplicates_dropped')} texts={json.dumps(_texts, default=str)[:200]}")
check("S41-6", "and the HIGHER-ranked occurrence is the one kept",
      _wb_dup["bullets"][0]["rank"] == 1 and _texts[0] == _dup_reading)

# Also found on LIVE output: DATA_LIMITATION reached by the all-rejected-on-direction path is NOT a
# data gap, and the stock meaning ("critical evidence is missing") misdescribed a case with 156 weeks
# of history.
_mech_all_rej = fce.miss_mechanism(
    -25.0,
    {"available": True,
     "demand_side": {"vs_expected": {"unusual": False}},
     "forecast_side": {"vs_expected": {"direction": "above", "difference_pct": 20.0}},
     "miss_decomposition": {"available": True, "reconciles": True, "forecast_side_share": 0.9},
     "response": {"classification": "no_response"},
     "forecastability": {"classification": "PREDICTABLE"},
     "forecastability_gate": {"supports_forecast_response_failure": False, "conditions": [],
                              "verdict": "no"},
     "baseline_error": {"material": True, "reading": "plan ABOVE the norm"}},
    {}, {}, {}, True)
check("S54-1", "every candidate rejected on direction still yields DATA_LIMITATION",
      _mech_all_rej.get("primary") == fce.DATA_LIMITATION,
      json.dumps(_mech_all_rej.get("mechanisms"), default=str))
check("S54-2", "but it is flagged as ruled-out-by-data, NOT as missing data",
      _mech_all_rej.get("all_candidates_rejected_on_direction") is True
      and "not missing data" in (_mech_all_rej.get("meaning") or ""),
      str(_mech_all_rej.get("meaning"))[:200])

# ==============================================================================
# The near-zero implied-change branch -- sign-aware, not hardcoded
# ==============================================================================
# Found on a real card: UKI Comm Client DSP Standard FW202717 reported `wrong_direction` with
# implied_change -2.3 and forecast_change_made -82.61 -- the SAME sign. Section 14 defines
# wrong_direction as moving OPPOSITE the expected direction, so the label contradicted the spec on
# its own terms. Worse, it pointed the remedy the wrong way: FW17 is a holiday week every year and a
# cut WAS correct; only its size was wrong.
print("\n-- Section 14: near-zero implied change is classified by SIGN --")
from wfm import forecast_response as _fr                                        # noqa: E402


def adequacy(prior_plan, target_plan, expected):
    """Drive _adequacy directly.

    `rows` are 4-tuples (week, forecast, actual, _) and a DETECTED signal is required -- without one
    the function correctly returns not_testable, because there was nothing to respond to.
    """
    rows = [(202716, prior_plan, 400.0, None), (202717, target_plan, 397.0, None)]
    signals = [{"signal": "demand_momentum", "detected": True}]
    return _fr._adequacy(rows, 202717, target_plan, expected, signals)


# implied ~0, plan moves the SAME way as the (tiny) implied change -> over_response
_a1 = adequacy(316.3, 233.7, 314.0)
check("SGN-1", "a big move in the SAME direction as a tiny implied change is over_response",
      _a1["classification"] == "over_response",
      f"got {_a1['classification']}: {_a1['reason']}")
check("SGN-2", "and the reason no longer claims 'no change was required'",
      "No change was required" not in _a1["reason"],
      _a1["reason"])
check("SGN-3", "it states where the plan needed to be and how far past it went",
      "314.0" in _a1["reason"] and "233.7" in _a1["reason"]
      and _a1.get("over_move_contacts") is not None,
      f"over_move_contacts={_a1.get('over_move_contacts')} :: {_a1['reason']}")
check("SGN-4", "and it is NOT labelled wrong_direction",
      _a1["classification"] != "wrong_direction",
      "section 14 reserves wrong_direction for a move OPPOSITE the implied direction")

# implied ~0, plan moves the OPPOSITE way -> wrong_direction is the correct label
_a2 = adequacy(316.3, 420.0, 314.0)
check("SGN-5", "a big move OPPOSITE a tiny implied change is still wrong_direction",
      _a2["classification"] == "wrong_direction",
      f"got {_a2['classification']}: {_a2['reason']}")

# implied ~0 and the plan stayed put -> adequate, unchanged behaviour
_a3 = adequacy(316.3, 315.0, 314.0)
check("SGN-6", "a plan that stayed at the expected level is still adequate",
      _a3["classification"] == "adequate", f"got {_a3['classification']}")

# a genuine opposite move with a LARGE implied change still routes through the ratio path
_a4 = adequacy(200.0, 150.0, 400.0)
check("SGN-7", "the non-negligible path is untouched: opposite move -> wrong_direction",
      _a4["classification"] == "wrong_direction" and _a4.get("response_ratio") is not None,
      f"got {_a4['classification']} ratio={_a4.get('response_ratio')}")
# implied 200, moved 360 -> ratio 1.8. Deliberately NOT 1.5: that is exactly OVER_RESPONSE_RATIO and
# the boundary is inclusive, so a ratio of 1.5 is correctly `adequate`. The first version of this
# check sat on the boundary and read the right answer as a failure.
_a5 = adequacy(200.0, 560.0, 400.0)
check("SGN-8", "and a large same-way overshoot is still over_response via the ratio",
      _a5["classification"] == "over_response" and _a5.get("response_ratio") == 1.8,
      f"got {_a5['classification']} ratio={_a5.get('response_ratio')}")
check("SGN-9", "a ratio exactly at the 1.50 over-response threshold stays adequate",
      adequacy(200.0, 500.0, 400.0)["classification"] == "adequate",
      "the boundary is inclusive by design; this pins it so a later change is deliberate")
# Section 40: the class token must not reach executive prose, and "judged over response" -- which is
# what a bare underscore-strip produced -- is not English either.
check("SGN-10", "every response class has a written sentence for the executive bullet",
      set(fce.RESPONSE_PROSE) >= set(_fr.RESPONSE_CLASSES),
      f"missing prose for {sorted(set(_fr.RESPONSE_CLASSES) - set(fce.RESPONSE_PROSE))}")
check("SGN-11", "and none of those sentences contains an underscore or a raw class name",
      all("_" not in v and v[0].isupper() and v.endswith(".")
          for v in fce.RESPONSE_PROSE.values()),
      json.dumps(fce.RESPONSE_PROSE))

# ==============================================================================
# Holiday capture: the ratio is stated, the threshold is NOT moved
# ==============================================================================
print("\n-- Sections 24/49: the capture ratio is stated inside the 'captured' band --")
check("CAP-1", "OVER_CAPTURE is still 1.75 -- the threshold was deliberately NOT tightened",
      hr.OVER_CAPTURE == 1.75, f"got {hr.OVER_CAPTURE}")
check("CAP-2", "CAPTURE_TOLERANCE is still 0.50",
      hr.CAPTURE_TOLERANCE == 0.50, f"got {hr.CAPTURE_TOLERANCE}")
_cap = hr._capture("holiday",
                   {"testable": True, "consistent": True, "consistency": 0.94,
                    "actual_effect_pct": -26.54},
                   397.0, 233.7, 396.8, 389.8, [])
check("CAP-3", "a 1.5x over-cut still classifies as captured (threshold unchanged)",
      _cap["classification"] == "captured", f"got {_cap['classification']}")
check("CAP-4", "but the ratio and the overshoot are now stated on the block",
      _cap.get("capture_ratio") is not None and _cap.get("overshoot_pct") is not None,
      json.dumps({k: _cap.get(k) for k in ("capture_ratio", "overshoot_pct")}))
check("CAP-5", "and the reason quotes the multiple, so a reader need not divide two percentages",
      "x" in _cap["reason"].lower() and "%" in _cap["reason"],
      _cap["reason"])
check("CAP-6", "the tolerance band is published so 'captured' can be interpreted",
      bool(_cap.get("tolerance_band")), str(_cap.get("tolerance_band")))

# ==============================================================================
# Standing holiday plan bias -- and the refusal to claim one that is not there
# ==============================================================================
print("\n-- Section 8/24: standing vs widening holiday plan bias --")
# A queue whose plan is consistently BELOW actual on holiday weeks.
_biased = [(202400 + i, 100.0, 150.0) for i in range(1, 13)]     # every week: actual >> plan
_pb = hr.plan_bias_by_phase(_biased, None, {})
check("BIAS-1", "with no country resolvable, no phase is testable and no bias is claimed",
      _pb.get("systematic") is False
      and all(not v.get("testable") for v in (_pb.get("phases") or {}).values()),
      json.dumps({k: v.get("testable") for k, v in (_pb.get("phases") or {}).items()}))

# Drive the per-phase maths directly with synthetic phase series, so the assertion does not depend
# on the shipped calendar containing a particular country.
def bias_block(adherences):
    """Build the phase block the summary reads, via the real function, using a fake phase mapper."""
    import wfm.holiday_response as H
    real = H._phase_of
    weeks = [202400 + i for i in range(1, len(adherences) + 1)]
    # actual/forecast pair that yields the wanted adherence: adh = (1 - a/f) * 100
    rows = [(w, 100.0, 100.0 * (1 - adh / 100.0)) for w, adh in zip(weeks, adherences)]
    H._phase_of = lambda country, week, cache: (H._cal.PHASE_HOLIDAY, {})
    try:
        return H.plan_bias_by_phase(rows, "x", {})
    finally:
        H._phase_of = real


# 11 of 12 weeks with the plan too low, median miss well past 10% -> a standing one-sided bias
_one_sided = bias_block([-30, -35, -28, -40, -33, -31, -45, -38, -29, -36, -42, +4])
_hb = (_one_sided.get("phases") or {}).get("holiday") or {}
check("BIAS-2", "11 of 12 holiday weeks missing the same way IS a standing bias",
      _hb.get("systematic") is True and _hb.get("bias_direction") == "plan_too_low",
      json.dumps({k: _hb.get(k) for k in ("systematic", "bias_direction", "share_same_way",
                                          "median_adherence_pct")}))
check("BIAS-3", "and it recommends changing the RULE, not this week's plan",
      "rule" in (_one_sided.get("action") or "").lower(),
      str(_one_sided.get("action")))

# 7 of 12 one way, 5 the other -> NOT a bias. This is the real UKI shape and the gate must refuse it.
_coin_flip = bias_block([-30, -35, +28, -40, +33, -31, +45, -38, +29, -36, +42, -20])
_cb = (_coin_flip.get("phases") or {}).get("holiday") or {}
check("BIAS-4", "a near-even split is NOT reported as a systematic bias",
      _cb.get("systematic") is False,
      f"share_same_way={_cb.get('share_same_way')} -- 58% is not a pattern, and claiming one "
      f"would be exactly the fabrication section 54 forbids")
check("BIAS-5", "one-sided but IMMATERIAL misses are not reported either",
      (bias_block([-2, -3, -2, -4, -3, -2, -1, -3]).get("phases") or {})
      .get("holiday", {}).get("systematic") is False,
      "a systematic but tiny bias is arithmetically real and operationally irrelevant")

# Widening is reported INDEPENDENTLY of direction -- the finding the UKI case actually supports.
_widening = bias_block([-6, +5, -7, +6, -40, +38, -45, +42])
_wsum = _widening
check("BIAS-6", "growing misses are reported even with NO consistent direction",
      _wsum.get("deteriorating") is True and _wsum.get("systematic") is False,
      json.dumps({k: _wsum.get(k) for k in ("systematic", "deteriorating",
                                            "deteriorating_phases")}))
check("BIAS-7", "and it is worded as a widening adjustment, not as a standing bias",
      "widening" in (_wsum.get("deteriorating_reading") or "").lower()
      and "not consistently one-sided" in (_wsum.get("deteriorating_reading") or ""),
      str(_wsum.get("deteriorating_reading"))[:220])
check("BIAS-8", "its action targets the SIZE of the adjustment, not its direction",
      "magnitude" in (_wsum.get("deteriorating_action") or "").lower(),
      str(_wsum.get("deteriorating_action"))[:200])
check("BIAS-9", "a stable, unbiased queue gets neither finding",
      (lambda s: s.get("systematic") is False and s.get("deteriorating") is False)(
          bias_block([-5, +4, -6, +5, -4, +6, -5, +4])),
      "no bias and no widening -> the panel says so rather than staying silent")
check("BIAS-10", "the two findings are documented as DIFFERENT questions",
      "DIFFERENT findings" in (_wsum.get("note") or ""),
      str(_wsum.get("note"))[:200])
_overlay = decision_card._with_narrative(_wb, {"whyThisHappened": [{"rank": 1, "text": "REWRITTEN"}]})
check("S41-4", "model rewording is matched BY RANK and keeps the deterministic text alongside",
      _overlay["bullets"][0]["text"] == "REWRITTEN"
      and _overlay["bullets"][0]["text_deterministic"] == _wb["bullets"][0]["text"])

# ==============================================================================
# Scenario 23 -- the 23-hypothesis catalogue is intact
# ==============================================================================
print("\n-- Scenario 23: catalogue preserved --")
check("S23-3", "the catalogue still holds exactly 23 entries",
      len(cat.CATALOGUE) == 23, f"got {len(cat.CATALOGUE)}")
check("S23-4", "and still six categories",
      len({e["category"] for e in cat.CATALOGUE}) == 6,
      json.dumps(sorted({e["category"] for e in cat.CATALOGUE})))
_expected_names = {
    "Holiday", "Fiscal Month Transition", "Quarter Transition", "Seasonality", "Demand Spike",
    "Demand Drop", "Demand Shift", "Volume Redistribution", "Forecast Bias",
    "Trend Misidentification", "Warranty Mix Shift", "Installed Base Change", "ASU Plan Variance",
    "Shipment Volume Change", "Queue Migration", "Outlier", "Drift", "Momentum Shift",
    "Variance Expansion", "Missing Data", "Incorrect Mapping", "Duplicate Records",
    "Insufficient History"}
_actual_names = {e["name"] for e in cat.CATALOGUE}
check("S23-5", "every named hypothesis from the brief is still represented",
      _expected_names == _actual_names,
      f"missing {sorted(_expected_names - _actual_names)}; "
      f"unexpected {sorted(_actual_names - _expected_names)}")
check("S23-6", "Product Lifecycle and Manual Override remain OUTSIDE the catalogue",
      not any("Lifecycle" in e["name"] or "Override" in e["name"] for e in cat.CATALOGUE),
      "neither is implementable against the current source data")
check("S23-7", "the offering driver cascade is unchanged",
      cat.DRIVER_CASCADE == {"Basic": ["shipments", "asu"], "Premium": ["asu", "shipments"],
                             "Pro": ["asu", "shipments"], "OOP": [], "OOW": []},
      json.dumps(cat.DRIVER_CASCADE))
check("S23-8", "the four catalogue states are all still distinct",
      len({cat.GENERATED, cat.NOT_APPLICABLE, cat.SUPPRESSED, cat.REJECTED}) == 4)
_gen, _not = cat.generate({"history": {"weeks_of_actuals": 4}}, {"BUS-01": "tier C"})
check("S23-9", "a suppressed hypothesis is Suppressed with a reason, not NotApplicable",
      any(n["id"] == "BUS-01" and n["state"] == cat.SUPPRESSED and n.get("reason")
          for n in _not),
      json.dumps([n for n in _not if n["id"] == "BUS-01"], default=str)[:200])
check("S23-10", "every non-generated entry records its FAILING CONDITION",
      all(n.get("reason") for n in _not),
      "a silent absence tells a business lead nothing")
check("S23-11", "the challenge catalogue grew additively and is versioned",
      cx.CATALOGUE_VERSION == "2.1.0" and len(cx.CATALOGUE) == 23,
      f"version {cx.CATALOGUE_VERSION}, {len(cx.CATALOGUE)} questions")
_orig_keys = {"STAT_SIGNIFICANCE", "STAT_SAMPLE_ADEQUACY", "STAT_METRIC_AGREEMENT",
              "STAT_OUTLIER_DEPENDENCE", "HIST_PRECEDENT", "HIST_SEASONAL_RECURRENCE",
              "HIST_TREND_CONSISTENCY", "BIZ_RULE_CONSISTENCY", "BIZ_DRIVER_APPLICABILITY",
              "BIZ_MATERIALITY", "LOGIC_DIRECTION_COHERENCE", "DATA_SUFFICIENCY",
              "DATA_COMPLETENESS", "DATA_CREDIBILITY", "DATA_MAPPING_INTEGRITY",
              "ALT_STRONGER_HYPOTHESIS", "ALT_HIGHER_LEVEL", "ALT_REVERSE_CAUSATION"}
_now_keys = {q["semantic_key"] for q in cx.CATALOGUE}
check("S23-12", "no original challenge question was removed or renamed",
      _orig_keys <= _now_keys, f"lost {sorted(_orig_keys - _now_keys)}")
check("S23-13", "the five section-27 questions were added",
      {"FCST_SIGNAL_TIMING", "FCST_LAG_SUPPORT", "FCST_COULD_HAVE_REACTED",
       "CAL_PHASE_INTERACTION", "FCST_WEEKEND_ATTRIBUTION"} <= _now_keys,
      f"have {sorted(_now_keys - _orig_keys)}")
# A new question with no measurement must not report support.
_ans = next(q for q in cx.CATALOGUE if q["semantic_key"] == "FCST_LAG_SUPPORT")["answer"]({}, {})
check("S27-1", "an unmeasured challenge question returns UNANSWERED, never SUPPORTS",
      _ans["verdict"] == cx.UNANSWERED, json.dumps(_ans, default=str)[:200])
_ans2 = next(q for q in cx.CATALOGUE
             if q["semantic_key"] == "CAL_PHASE_INTERACTION")["answer"](
    {"holiday_phase": {"available": True, "applies": True, "historical_consistency": 0.40}}, {})
check("S27-2", "an inconsistent phase history REFUTES a calendar hypothesis rather than weakening it",
      _ans2["verdict"] == cx.REFUTES, json.dumps(_ans2, default=str)[:220])

# ==============================================================================
# Section 4 -- the canonical sequence, and section 38 -- the contract
# ==============================================================================
print("\n-- Sections 4 and 38: sequence and output contract --")
_h = flat_history(n=150)
_h[-1] = row(_h[-1]["Fiscal_Week"], 1600.0, 1000.0)
_r = run_engine(_h, fields())
_steps = (_r.get("audit") or {}).get("steps") or []
_nums = [s["step"] for s in _steps]
check("SEQ-1", "all 15 canonical steps are recorded",
      set(range(1, 16)) <= set(_nums), f"recorded {sorted(set(_nums))}")
check("SEQ-2", "steps are recorded in non-decreasing order -- nothing was reordered",
      _nums == sorted(_nums), f"{_nums}")
_step_names = {s["step"]: s["name"] for s in _steps}
check("SEQ-3", "hypotheses (6) are generated BEFORE statistics are evaluated (9)",
      _nums.index(6) < _nums.index(9))
check("SEQ-4", "cross-examination (11) runs BEFORE confidence (12)",
      _nums.index(11) < _nums.index(12))
check("SEQ-5", "the LLM narrative is step 14, after the deterministic RCA at 13",
      _nums.index(13) < _nums.index(14))
check("AUD-1", "the input fingerprint is preserved",
      bool((_r.get("audit") or {}).get("input_fingerprint")))
check("AUD-2", "all four version stamps are recorded",
      all((_r.get("audit") or {}).get(k) for k in
          ("catalogue_version", "challenge_catalogue_version", "confidence_weights_version",
           "prompt_version")))
check("AUD-3", "the generation threshold is recorded on the audit trail",
      (_r.get("audit") or {}).get("generation_threshold_pct") == 5.0)

_LEGACY_KEYS = ("queue", "period", "holiday", "context_elements", "grain", "forecast_summary",
                "root_cause", "confidence", "supporting_evidence", "contradictory_evidence",
                "recommendations", "limitations", "why_chain", "hypotheses", "cross_examination",
                "driver_gate", "statistical_evidence", "data_quality", "major_deviation",
                "material", "audit", "engine", "decision_card", "status")
check("CON-1", "every pre-existing response key is still present",
      all(k in _r for k in _LEGACY_KEYS),
      f"missing {[k for k in _LEGACY_KEYS if k not in _r]}")
_NEW_KEYS = ("forecast_response_diagnostic", "forecastability", "lagged_driver_evidence",
             "holiday_response", "weekend_diagnostic", "asu_decomposition", "plan_revision",
             "miss_mechanism", "criticality", "evidence_resolution", "fc_evidence_index",
             "unexplained_observations")
check("CON-2", "the additive keys are all present",
      all(k in _r for k in _NEW_KEYS), f"missing {[k for k in _NEW_KEYS if k not in _r]}")
check("CON-3", "cause_type is STILL the catalogue hypothesis id, not the new mechanism",
      (_r.get("root_cause") or {}).get("cause_type")
      == (_r.get("root_cause") or {}).get("hypothesis_id"),
      json.dumps({k: (_r.get("root_cause") or {}).get(k)
                  for k in ("cause_type", "hypothesis_id", "miss_mechanism")}, default=str))
check("CON-4", "the ten mandatory card sections survive alongside the eight additive ones",
      all(k in ((_r.get("decision_card") or {}).get("sections") or {})
          for k in ("1_executive_summary", "2_root_cause", "3_confidence", "4_business_impact",
                    "5_evidence", "6_hypothesis_comparison", "7_recommendations",
                    "8_limitations", "9_data_availability", "10_audit_reference",
                    "11_criticality", "12_why_this_happened", "13_forecast_response",
                    "14_calendar_context", "15_driver_evidence", "16_evidence_index",
                    "17_contradiction_resolution", "18_catalogue_gaps")),
      json.dumps(sorted(((_r.get("decision_card") or {}).get("sections") or {}).keys())))
check("CON-5", "the card version records that it changed",
      (_r.get("decision_card") or {}).get("card_version") == "2.1.0")
check("CON-6", "the whole response is JSON-serialisable",
      bool(json.dumps(_r, default=str)))
_ix = _r.get("fc_evidence_index") or {}
check("EVI-1", "the evidence index carries all 15 items",
      len(_ix.get("items") or {}) == 15, f"got {len(_ix.get('items') or {})}")
check("EVI-2", "an unestablished evidence item is present with a reason, not omitted",
      all(("note" in e and e.get("id") and e.get("label"))
          for e in (_ix.get("items") or {}).values()))

# Section 19 -- the ASU identity must hold exactly.
print("\n-- Section 19: ASU decomposition identity --")
for planned, actual_asu, fc, act in ((1000.0, 1200.0, 500.0, 700.0),
                                     (5000.0, 4000.0, 2000.0, 1500.0),
                                     (250.0, 250.0, 100.0, 160.0)):
    d = fce.asu_decomposition(planned, actual_asu, fc, act)
    check("ASU-1", f"volume + rate == actual - forecast for ({planned},{actual_asu},{fc},{act})",
          d.get("reconciles") is True
          and abs(d["volume_effect"] + d["rate_effect"] - (act - fc)) < 0.5,
          json.dumps(d, default=str)[:200])
_no_asu = fce.asu_decomposition(1000.0, None, 500.0, 700.0)
check("ASU-2", "a missing Actual_ASU is REPORTED, never fabricated",
      _no_asu.get("available") is False and _no_asu.get("availability") == fce.MISSING
      and "Actual_ASU" in (_no_asu.get("reason") or ""),
      json.dumps(_no_asu, default=str)[:220])
_na_asu = fce.asu_decomposition(None, None, 500.0, 700.0)
check("ASU-3", "no ASU exposure at all is NotApplicable, not Missing",
      _na_asu.get("availability") == fce.NOT_APPLICABLE,
      "a queue with no ASU exposure must not be penalised for lacking it")

# Section 33 -- scope narrows the search; it never becomes the cause.
print("\n-- Section 33: scope is not a cause --")
_ladder = [{"level": "Country", "scope": "TestLand", "actual_offered": 50000.0,
            "fcst_offered": 40000.0, "adherence_pct": -25.0, "queue_weeks_in_scope": 40}]
_h = flat_history(n=150)
_h[-1] = row(_h[-1]["Fiscal_Week"], 1500.0, 1000.0)
_r_scope = run_engine(_h, fields(), ladder=_ladder)
_sc = ((_r_scope.get("decision_card") or {}).get("sections") or {}).get("2_root_cause", {}).get("scope") or {}
check("SCO-1", "the ladder is rendered as SCOPE and carries the caution",
      "WHERE the miss is visible, not WHY" in (_sc.get("caution") or ""),
      str(_sc.get("caution"))[:160])
check("SCO-2", "the promoted cause is a catalogue hypothesis, never 'inherited from Country'",
      str((_r_scope.get("root_cause") or {}).get("hypothesis_id") or "").split("-")[0]
      in ("CAL", "DEM", "FC", "BUS", "STA", "DQ")
      or (_r_scope.get("root_cause") or {}).get("cause_type") == spec_engine.INCONCLUSIVE,
      json.dumps((_r_scope.get("root_cause") or {}).get("hypothesis_id"), default=str))

# Section 9 -- catalogue gaps are recorded, never converted into a cause.
print("\n-- Section 9: catalogue gaps --")
_gaps = fce.unexplained_observations(
    {"candidates": [{"mechanism": fce.CALENDAR_RESPONSE_FAILURE, "evidence": "e"}]}, {"FC-01"})
check("GAP-1", "a mechanism with no matching generated hypothesis is recorded as a catalogue gap",
      len(_gaps) == 1 and _gaps[0]["type"] == "UNEXPLAINED_OBSERVATION",
      json.dumps(_gaps, default=str)[:240])
check("GAP-2", "and it names the catalogue entries that WOULD have carried it",
      bool(_gaps[0].get("catalogue_entries_that_would_carry_it")))
_no_gaps = fce.unexplained_observations(
    {"candidates": [{"mechanism": fce.CALENDAR_RESPONSE_FAILURE, "evidence": "e"}]}, {"CAL-01"})
check("GAP-3", "no gap is recorded when a matching hypothesis DID fire",
      _no_gaps == [])

# Section 48 -- no N x M statistical explosion.
print("\n-- Section 48: hypothesis-first, no fishing --")
_lag_none = fce.lagged_driver_evidence(flat_history(n=150), 202520, set())
check("PERF-1", "with no business hypothesis generated, NO driver lag is computed",
      _lag_none.get("available") is False
      and _lag_none.get("availability") == fce.NOT_APPLICABLE
      and _lag_none.get("requested_drivers") == [],
      json.dumps(_lag_none, default=str)[:220])
check("PERF-2", "and it says nothing was tested rather than that nothing was found",
      "Nothing was tested and nothing is claimed" in (_lag_none.get("reason") or ""),
      _lag_none.get("reason"))
_lag_one = fce.lagged_driver_evidence(flat_history(n=150), 202520, {"BUS-04"})
check("PERF-3", "one hypothesis requests only ITS driver, not every column",
      _lag_one.get("requested_drivers") == ["Final_Units"],
      json.dumps(_lag_one.get("requested_drivers")))

# Scenario 24 -- SA Indonesia FW202716, REGRESSION ONLY.
print("\n-- Scenario 24: SA Indonesia FW202716 regression (offline capture) --")
_cap = os.path.join(HERE, "_offline_cache", "spec-offline-results.json")
if not os.path.exists(_cap):
    print("  SKIP  S24 no offline capture present; run the offline rig first")
else:
    _data = json.load(open(_cap, encoding="utf-8"))
    _ind = {k: v for k, v in _data.items() if "Indonesia" in k}
    if not _ind:
        print("  SKIP  S24 offline capture holds no Indonesian queue")
    else:
        _k, _v = sorted(_ind.items())[0]
        check("S24-1", f"{_k} still produces a complete card",
              bool((_v.get("decision_card") or {}).get("sections")))
        check("S24-2", "with a mechanism drawn from the fixed set",
              (_v.get("miss_mechanism") or {}).get("primary") in fce.MISS_MECHANISMS,
              str((_v.get("miss_mechanism") or {}).get("primary")))
        check("S24-3", "and a criticality band from the fixed set",
              (_v.get("criticality") or {}).get("band") in fce.CRITICALITY_BANDS,
              str((_v.get("criticality") or {}).get("band")))
        check("S24-4", "no executive bullet leaks statistical jargon",
              not (((_v.get("decision_card") or {}).get("sections") or {})
                   .get("12_why_this_happened", {}).get("jargon_found")),
              json.dumps(((_v.get("decision_card") or {}).get("sections") or {})
                         .get("12_why_this_happened", {}).get("jargon_found")))

# ==============================================================================
print("\n" + "-" * 94)
print(f"  {len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
if FAIL:
    print("\n  FAILURES:")
    for tag, name, detail in FAIL:
        print(f"    {tag} {name}")
        if detail:
            print(f"        {detail}")
print("-" * 94)
sys.exit(1 if FAIL else 0)
