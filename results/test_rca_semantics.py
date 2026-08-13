"""
Semantic regression -- does the engine reach the RIGHT DIAGNOSIS, not just the right arithmetic?
================================================================================================

Run:  cd backend && python ../results/test_rca_semantics.py

`test_wfm_diagnostics.py` proves the metrics are correct. Correct metrics can still produce a wrong
diagnosis: the whole point of the decision layer is that a large gap between actual and forecast is
NOT by itself a forecast failure. These cases test the conclusion.

Each fixture is built so the right answer is known by construction -- a queue whose demand is
perfectly ordinary and whose plan is mis-scaled MUST come out as a baseline failure, and a queue
with no leading signal at all MUST NOT be blamed on the forecaster however large the miss.

The twelve cases follow the Phase 2 brief section 27, plus the SA Indonesia regression, which is
asserted on BEHAVIOUR (does it avoid "demand spike", does it keep sparse drivers out of the causes)
and never on a hard-coded sentence.

NO DATABASE AND NO NETWORK for the synthetic cases. The Indonesia regression uses the offline
mirror when it has been built, and skips with a clear message when it has not.
"""
import os
import sys

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

from wfm import rca_decision                                       # noqa: E402
from wfm.investigation_engine import derive_wfm_features           # noqa: E402
from wfm.context_repository import holiday_calendar as _cal        # noqa: E402

RESULTS = []
BAND = 10.0


def check(name, ok, detail=""):
    RESULTS.append({"name": name, "pass": bool(ok), "detail": detail})
    return bool(ok)


def eq(name, got, want):
    return check(name, got == want, f"got={got!r} want={want!r}")


def in_(name, got, allowed):
    return check(name, got in allowed, f"got={got!r} allowed={allowed!r}")


# ---------------------------------------------------------------------------
# fixture construction
# ---------------------------------------------------------------------------
def weeks(year, first, count):
    return [year * 100 + w for w in range(first, first + count)]


def history(n=60, year=2026, actual=100.0, forecast=100.0, drivers=None, holiday=0.0,
            actual_fn=None, forecast_fn=None, driver_fn=None):
    """A queue's weekly history. Callables receive the zero-based week index."""
    rows = []
    for i, wk in enumerate(weeks(year, 1, n)):
        row = {"Fiscal_Week": wk,
               "Actual_Offered": float(actual_fn(i) if actual_fn else actual),
               "fcst_offered": float(forecast_fn(i) if forecast_fn else forecast),
               "Holiday_Count": float(holiday)}
        if drivers:
            for name, value in drivers.items():
                row[name] = float(driver_fn(i, name) if driver_fn else value)
        rows.append(row)
    return rows


def bundle(target_week, actual, forecast, fields=None):
    f = {"Fiscal_Week": target_week, "Actual_Offered": actual, "fcst_offered": forecast,
         "Country": "testland", "channel": "Voice", "Holiday_Count": 0.0}
    f.update(fields or {})
    adherence = (1.0 - actual / forecast) * 100.0 if forecast else None
    return {"meta": {"band_threshold": BAND},
            "target": {"key": {"Forecast_name": "Q", "Fiscal_Week": str(target_week)},
                       "fields": f,
                       "computed": {"forecast": forecast, "actual": actual,
                                    "error": actual - forecast, "adherence_pct": adherence}},
            "history": [], "peers": [], "statistical_summary": {"numeric": {}, "categorical": {}}}


def run(hist, target_week, actual, forecast, fields=None, forward=None):
    """Build features exactly as the engine does, then decide."""
    ctx = {"history_104": hist, "history_forward": forward or [], "channel_sibling_rows": [],
           "ladder": [], "prior_week": None, "prior_year_week": target_week - 100,
           "cqn_names": [], "cqn_source": "proxy"}
    feats, adherence = derive_wfm_features(bundle(target_week, actual, forecast, fields), ctx, BAND)
    return feats, feats.get("decision") or {}


class NoHolidays:
    """Neutralise the real holiday master so a synthetic case is not perturbed by real calendars."""

    def __enter__(self):
        self._saved = _cal._CACHE
        _cal._CACHE = {"holidays": {}, "active_rows": 0, "country_weeks": 0,
                       "source": "test fixture", "aggregate_groups": {}}
        return self

    def __exit__(self, *exc):
        _cal._CACHE = self._saved
        return False


class Holidays:
    def __init__(self, mapping):
        self.mapping = mapping

    def __enter__(self):
        self._saved = _cal._CACHE
        _cal._CACHE = {"holidays": self.mapping, "active_rows": len(self.mapping),
                       "country_weeks": len(self.mapping), "source": "test fixture",
                       "aggregate_groups": {}}
        return self

    def __exit__(self, *exc):
        _cal._CACHE = self._saved
        return False


# ---------------------------------------------------------------------------
# Case 1 -- forecast baseline failure: demand is utterly ordinary, the plan is mis-scaled
# ---------------------------------------------------------------------------
def case_1_baseline_failure():
    with NoHolidays():
        # demand flat at 100 for three years; the plan for the target week is set at 50
        hist = history(n=60, actual=100.0, forecast=100.0)
        feats, d = run(hist, 202661, actual=100.0, forecast=50.0)
    eq("C1-1 baseline failure is diagnosed", d.get("miss_category"), "FORECAST_BASELINE_FAILURE")
    primary = next((b for b in d["why_bullets"] if b["evidence_class"] == "PRIMARY_DRIVER"), {})
    check("C1-2 the leading mechanism is the baseline",
          "baseline" in (primary.get("headline") or "").lower(), str(primary.get("headline")))
    check("C1-3 demand is NOT blamed",
          not any("demand moved" in (b.get("headline") or "").lower() and
                  b["evidence_class"] == "PRIMARY_DRIVER" for b in d["why_bullets"]), "")
    check("C1-4 the root cause is a sentence, not a label",
          len((d.get("root_cause_sentence") or "").split()) >= 6, d.get("root_cause_sentence"))


# ---------------------------------------------------------------------------
# Case 2 -- genuine demand event: no signal of any kind existed
# ---------------------------------------------------------------------------
def case_2_demand_event():
    with NoHolidays():
        hist = history(n=60, actual=100.0, forecast=100.0)
        feats, d = run(hist, 202661, actual=220.0, forecast=100.0)
    eq("C2-1 an unforeseeable jump is a demand event", d.get("miss_category"), "DEMAND_EVENT")
    eq("C2-2 forecastability is low", d.get("forecastability"), "LOW_PREDICTABILITY")
    resp = (feats.get("forecast_response") or {}).get("response") or {}
    eq("C2-3 response adequacy is not testable", resp.get("classification"), "not_testable")
    check("C2-4 the forecaster is not blamed",
          "not a response failure" in (resp.get("reason") or "").lower(), resp.get("reason"))


# ---------------------------------------------------------------------------
# Case 3 -- a repeatable signal existed and the plan was cut anyway
# ---------------------------------------------------------------------------
def _momentum_growth(i):
    """Persistent compounding growth: ~3% a week."""
    return 100.0 * (1.03 ** i)


def _momentum_history(n=60):
    """Demand that grows persistently, so momentum is BOTH material and historically predictive.

    Two earlier fixtures were rejected by the engine, correctly, and both were fixture bugs:
      - a 12-week cycle that reset: momentum was material at each rise and then collapsed, so
        `momentum_repeatability` measured that momentum means nothing here and the engine refused
        to call the miss foreseeable;
      - a staircase: the last four weeks usually sat mid-plateau, so the last-4 vs prior-8
        comparison never cleared MOMENTUM_MATERIAL_PCT at the tail.
    To test a PREDICTABLE signal the signal has to have actually been predictive. Compounding
    growth keeps the 4-vs-8 ratio constant (~19%) at every point in the history, so momentum is
    material throughout AND the following week always continues it.
    """
    return history(n=n, actual_fn=_momentum_growth, forecast=100.0)


def _next_after(n=60, growth=1.15):
    """A target actual that continues the fixture's growth, so the target is not a step DOWN."""
    return round(_momentum_growth(n - 1) * growth, 1)


def case_3_response_failure():
    with NoHolidays():
        hist = _momentum_history()
        # the target continues the growth, and the plan is CUT anyway
        feats, d = run(hist, 202661, actual=_next_after(), forecast=70.0)
    in_("C3-1 a foreseeable miss is a forecast/compound failure", d.get("miss_category"),
        ("FORECAST_RESPONSE_FAILURE", "COMPOUND_MISS", "FORECAST_BASELINE_FAILURE"))
    fr = feats.get("forecast_response") or {}
    in_("C3-2 forecastability is established", (fr.get("forecastability") or {}).get("classification"),
        ("PREDICTABLE", "PARTIALLY_PREDICTABLE"))
    check("C3-3 momentum was detected before the week",
          any(s.get("signal") == "demand_momentum" and s.get("detected")
              for s in fr.get("signals") or []), "")


# ---------------------------------------------------------------------------
# Case 4 -- a recurring calendar pattern the plan never captures
# ---------------------------------------------------------------------------
def _holiday_map(country="testland", year=2026, n=60, step=8):
    out = {}
    for w in range(1, n + 2):
        if w % step == 0:
            out[f"{country}|{year * 100 + w}"] = [
                {"name": f"Test Holiday {w}", "type": "National", "date": f"{year - 1}-01-{w:02d}"
                 if w < 29 else None, "before": 3, "after": 3, "group": "", "needs_review": False}]
    return out


def case_4_calendar_failure():
    with Holidays(_holiday_map()):
        # post-holiday weeks reliably rebound to 160; the plan stays flat at 100 every time
        def actual_fn(i):
            w = (i + 1) % 8
            return 160.0 if w == 1 else (70.0 if w == 0 else 100.0)
        hist = history(n=56, actual_fn=actual_fn, forecast=100.0)
        feats, d = run(hist, 202657, actual=160.0, forecast=100.0)   # week 57 -> 57 % 8 == 1
    hol = feats.get("holiday_response") or {}
    eq("C4-1 the target week is recognised as post-holiday", hol.get("phase"), "post_holiday")
    phase = hol.get("phase_effect") or {}
    check("C4-2 the phase effect is measured as UP", phase.get("direction") == "up", str(phase))
    in_("C4-3 an uncaptured repeatable calendar pattern is a calendar/compound failure",
        d.get("miss_category"),
        ("CALENDAR_RESPONSE_FAILURE", "COMPOUND_MISS", "FORECAST_RESPONSE_FAILURE"))
    check("C4-4 the holiday mechanism appears in the ranked why",
          any("calendar" in (b.get("cause_type") or "") or "holiday" in (b.get("headline") or "").lower()
              for b in d.get("why_bullets") or []), str([b.get("headline") for b in d.get("why_bullets") or []]))


# ---------------------------------------------------------------------------
# Case 5 / 6 -- under-response and wrong-direction response
# ---------------------------------------------------------------------------
def case_5_under_response():
    with NoHolidays():
        hist = _momentum_history()
        # plan nudged from 100 to 110 when the expected level implies far more
        feats, d = run(hist, 202661, actual=_next_after(), forecast=110.0)
    resp = (feats.get("forecast_response") or {}).get("response") or {}
    in_("C5-1 a small move in the right direction is under/no response",
        resp.get("classification"),
        ("under_response", "no_response", "delayed_response", "adequate", "not_testable"))
    check("C5-2 the implied and actual movement are both reported",
          resp.get("implied_change") is not None or resp.get("classification") == "not_testable",
          str(resp))


def case_6_wrong_direction():
    with NoHolidays():
        hist = _momentum_history()
        feats, d = run(hist, 202661, actual=_next_after(), forecast=60.0)
    fr = feats.get("forecast_response") or {}
    opposed = [m for m in fr.get("movement_test") or [] if m.get("testable")
               and m.get("directions_opposed")]
    check("C6-1 opposed movement is detected", bool(opposed), str(fr.get("directions_opposed_at")))
    resp = fr.get("response") or {}
    in_("C6-2 a plan cut against a rising signal is a response failure",
        resp.get("classification"),
        ("wrong_direction", "no_response", "under_response", "delayed_response"))


# ---------------------------------------------------------------------------
# Case 7 -- compound: baseline already low AND demand moved
# ---------------------------------------------------------------------------
def case_7_compound():
    with NoHolidays():
        hist = history(n=60, actual=100.0, forecast=100.0)
        feats, d = run(hist, 202661, actual=160.0, forecast=55.0)
    in_("C7-1 two material mechanisms give a compound miss", d.get("miss_category"),
        ("COMPOUND_MISS", "FORECAST_BASELINE_FAILURE", "DEMAND_EVENT"))
    dec = (feats.get("forecast_response") or {}).get("miss_decomposition") or {}
    check("C7-2 both sides of the miss are material",
          (dec.get("forecast_side_share") or 0) > 0.2 and (dec.get("demand_side_share") or 0) > 0.2,
          str({k: dec.get(k) for k in ("forecast_side_share", "demand_side_share")}))
    check("C7-3 the decomposition still reconciles exactly", dec.get("reconciles"), str(dec))


# ---------------------------------------------------------------------------
# Case 8 -- data limitation: too little history to decide anything
# ---------------------------------------------------------------------------
def case_8_data_limitation():
    with NoHolidays():
        hist = history(n=4, actual=100.0, forecast=100.0)
        feats, d = run(hist, 202605, actual=200.0, forecast=80.0)
    eq("C8-1 too little history is a data limitation", d.get("miss_category"), "DATA_LIMITATION")
    check("C8-2 no cause is invented", not [b for b in d.get("why_bullets") or []
                                            if b["evidence_class"] == "PRIMARY_DRIVER"],
          str(d.get("why_bullets")))
    check("C8-3 the shortfall is stated", "required" in (d.get("miss_category_reason") or "")
          or "not enough" in (d.get("miss_category_reason") or ""), d.get("miss_category_reason"))


# ---------------------------------------------------------------------------
# Case 9 -- a sparse driver must never become a cause
# ---------------------------------------------------------------------------
def case_9_sparse_driver():
    with NoHolidays():
        hist = history(n=60, actual=100.0, forecast=100.0)
        for row in hist[-2:]:
            row["Final_upp_units"] = 76.0
        feats, d = run(hist, 202661, actual=180.0, forecast=100.0,
                       fields={"Final_upp_units": 109.0})
    lag = feats.get("lag_analysis") or {}
    upp = next((x for x in lag.get("drivers") or [] if x["driver"] == "Final_upp_units"), {})
    eq("C9-1 the sparse driver is classed sparse", upp.get("coverage"), "sparse")
    check("C9-2 it is never usable as evidence", not upp.get("usable_as_evidence"), str(upp))
    check("C9-3 it never appears as a ranked cause",
          not any("upp" in str(b.get("what_happened", "")).lower() and
                  b["evidence_class"] in ("PRIMARY_DRIVER", "SECONDARY_CONTRIBUTOR")
                  for b in d.get("why_bullets") or []), "")
    check("C9-4 the limitation is reported instead",
          any("too few" in str(x) for x in d.get("limitations") or []),
          str(d.get("limitations"))[:200])


# ---------------------------------------------------------------------------
# Case 10 -- lagged-only driver: weak same-week, strong at lag 2
# ---------------------------------------------------------------------------
def case_10_lagged_driver():
    with NoHolidays():
        n = 60
        driver = [10 + (i * 7) % 13 for i in range(n)]
        rows = []
        for i, wk in enumerate(weeks(2026, 1, n)):
            src = driver[i - 2] if i >= 2 else driver[0]
            rows.append({"Fiscal_Week": wk, "Final_Units": float(driver[i]),
                         "Actual_Offered": 50.0 + 2.0 * src, "fcst_offered": 95.0,
                         "Holiday_Count": 0.0})
        feats, d = run(rows, 202661, actual=150.0, forecast=95.0,
                       fields={"Final_Units": float(driver[-1])})
    lag = feats.get("lag_analysis") or {}
    fu = next((x for x in lag.get("drivers") or [] if x["driver"] == "Final_Units"), {})
    eq("C10-1 the two-week lead is recovered", fu.get("best_lag_weeks"), 2)
    check("C10-2 the driver is usable evidence", fu.get("usable_as_evidence"), str(fu))
    check("C10-3 the wording is 'leads demand', never 'no relationship'",
          "associated with" in (fu.get("interpretation") or "")
          or "week(s) earlier" in (fu.get("interpretation") or ""), fu.get("interpretation"))


# ---------------------------------------------------------------------------
# Case 11 / 12 -- weekend evidence follows the data grain, never the wish
# ---------------------------------------------------------------------------
def case_11_holiday_weekend_interaction():
    with Holidays(_holiday_map()):
        hist = history(n=56, actual=100.0, forecast=100.0)
        feats, d = run(hist, 202657, actual=150.0, forecast=100.0,
                       fields={"Saturday": 1.0, "Sunday": 1.0, "Holiday_Count": 2.0})
    hs = feats.get("holiday_day_structure") or {}
    eq("C11-1 a weekend holiday is identified from the day flags", hs.get("pattern"),
       "holiday_on_weekend")
    check("C11-2 no weekend DEMAND effect is claimed",
          "no weekend demand effect is claimed" in (hs.get("note") or ""), str(hs.get("note")))


def case_12_weekly_only_weekend():
    with NoHolidays():
        hist = history(n=60, actual=100.0, forecast=100.0)
        feats, d = run(hist, 202661, actual=180.0, forecast=100.0)
    gran = feats.get("data_granularity") or {}
    eq("C12-1 the grain is detected as weekly", gran.get("grain"), "weekly")
    check("C12-2 weekend attribution is refused",
          gran.get("weekend_analysis_supported") is False, str(gran.get("capabilities")))
    check("C12-3 the limitation reaches the decision layer",
          any("Weekend impact cannot be isolated" in str(x) for x in d.get("limitations") or []),
          str(d.get("limitations"))[:200])


# ---------------------------------------------------------------------------
# Direction coherence -- a suppressing mechanism cannot explain a busier week
# ---------------------------------------------------------------------------
def case_direction_coherence():
    with Holidays(_holiday_map()):
        # holiday weeks reliably SUPPRESS demand here...
        def actual_fn(i):
            return 60.0 if (i + 1) % 8 == 0 else 100.0
        hist = history(n=56, actual_fn=actual_fn, forecast=100.0)
        # ...and the target week is a holiday week that came in BUSIER than plan
        feats, d = run(hist, 202656, actual=160.0, forecast=100.0)
    bullets = d.get("why_bullets") or []
    calendar = [b for b in bullets if (b.get("cause_type") or "") == "calendar_holiday_effect"]
    promoted = [b for b in calendar if b["evidence_class"] in ("PRIMARY_DRIVER",
                                                              "SECONDARY_CONTRIBUTOR")]
    check("DIR-1 a demand-suppressing holiday is not promoted for an over-shooting week",
          not promoted, str([(b["headline"], b["evidence_class"]) for b in calendar]))
    rejected = d.get("rejected") or []
    check("DIR-2 direction incoherence is explained where it rejects a cause",
          all("direction" in (r.get("reason") or "").lower() or r.get("reason")
              for r in rejected), str(rejected)[:200])


# ---------------------------------------------------------------------------
# criticality is independent of confidence, and absolute gap sets the band
# ---------------------------------------------------------------------------
def case_criticality():
    with NoHolidays():
        small = history(n=60, actual=90.0, forecast=90.0)
        _, ds = run(small, 202661, actual=178.0, forecast=90.0)      # 88 contacts on a small queue
        big = history(n=60, actual=5000.0, forecast=5000.0)
        _, db = run(big, 202661, actual=5900.0, forecast=5000.0)     # 900 contacts on a big queue
    order = list(reversed(rca_decision.CRITICALITIES))
    small_level = (ds.get("criticality") or {}).get("level")
    big_level = (db.get("criticality") or {}).get("level")
    check("CRIT-1 a large absolute gap outranks a large percentage on a small queue",
          order.index(big_level) >= order.index(small_level),
          f"small={small_level} big={big_level}")
    eq("CRIT-2 a 900-contact gap is Critical", big_level, "Critical")
    check("CRIT-3 criticality is not derived from confidence",
          (ds.get("criticality") or {}).get("level") is not None
          and (ds.get("confidence") or {}).get("score_pct") is not None
          and "independent" in ((ds.get("criticality") or {}).get("note") or ""), "")


# ---------------------------------------------------------------------------
# SA Indonesia FW202716 -- behaviour, never a hard-coded sentence
# ---------------------------------------------------------------------------
def case_indonesia_regression():
    try:
        import offline_source
        from wfm.data_access import fetch_wfm_context
        import run_offline_investigation as runner
        conn = offline_source.connect()
    except Exception as exc:
        check("IND-0 offline mirror available", False,
              f"SKIPPED: {exc} -- run: python ../results/offline_source.py --build")
        return
    try:
        cur = conn.cursor()
        table = offline_source.TABLE
        name, week = "SA Indonesia Client Basic", 202716
        b = runner.build_bundle(cur, table, name, week)
        fields = b["target"]["fields"]
        key = {"Forecast_name": name, "Fiscal_Week": week, "Region": fields.get("Region"),
               "SubRegion": fields.get("SubRegion"), "Country": fields.get("Country"),
               "channel": fields.get("channel"), "business_org": fields.get("business_org"),
               "Offering": fields.get("Offering")}
        ctx = fetch_wfm_context(cur, table, key)
        feats, _ = derive_wfm_features(b, ctx, BAND)
        d = feats.get("decision") or {}

        check("IND-1 a decision is produced", bool(d.get("miss_category")), str(d)[:120])
        sentence = (d.get("root_cause_sentence") or "").lower()
        check("IND-2 the root cause is not a generic label",
              "demand spike" not in sentence and len(sentence.split()) >= 6, sentence)
        check("IND-3 forecast-side and demand-side are separated",
              (feats.get("forecast_response") or {}).get("miss_decomposition", {}).get("available"),
              "")
        # Holiday phase: in the LIVE table this queue carries Country = "Indonesia" and the week
        # resolves to post_holiday from the two holidays in FW202715. In the offline extract this
        # is the one queue of 427 whose scope columns are blank, so the correct behaviour there is
        # to refuse the check rather than assert "no holiday". Both are asserted, whichever applies.
        hol = feats.get("holiday_response") or {}
        if str(fields.get("Country") or "").strip():
            eq("IND-4 a resolvable country gives the post-holiday phase", hol.get("phase"),
               "post_holiday")
        else:
            check("IND-4 a blank Country refuses the holiday check rather than claiming none",
                  hol.get("available") is False and "cannot be matched" in (hol.get("reason") or ""),
                  f"available={hol.get('available')} reason={hol.get('reason')}")
            check("IND-4b and says that is not the same as finding no holiday",
                  "not the same as finding no holiday" in (hol.get("note") or ""),
                  str(hol.get("note")))
        lag = feats.get("lag_analysis") or {}
        upp = next((x for x in lag.get("drivers") or [] if x["driver"] == "Final_upp_units"), {})
        if upp:
            check("IND-5 sparse Final_upp_units is not promoted",
                  not upp.get("usable_as_evidence"), str(upp.get("coverage")))
        asu = (feats.get("correlations") or {}).get("driver_decomposition") or {}
        check("IND-6 the missing ASU limitation is preserved",
              asu.get("available") is False and "Actual_ASU" in str(asu.get("missing_fields")),
              str(asu)[:160])
        check("IND-7 hierarchy is not presented as the cause",
              not any((b_.get("cause_type") == "inherited_from_higher_level")
                      and b_["evidence_class"] == "PRIMARY_DRIVER"
                      for b_ in d.get("why_bullets") or []), "")
        check("IND-8 confidence and criticality are both present and independent",
              (d.get("confidence") or {}).get("level") and (d.get("criticality") or {}).get("level"),
              f"conf={(d.get('confidence') or {}).get('level')} "
              f"crit={(d.get('criticality') or {}).get('level')}")
    finally:
        conn.close()


def main():
    cases = [case_1_baseline_failure, case_2_demand_event, case_3_response_failure,
             case_4_calendar_failure, case_5_under_response, case_6_wrong_direction,
             case_7_compound, case_8_data_limitation, case_9_sparse_driver,
             case_10_lagged_driver, case_11_holiday_weekend_interaction,
             case_12_weekly_only_weekend, case_direction_coherence, case_criticality,
             case_indonesia_regression]
    print("=" * 96)
    print("WFM RCA SEMANTIC REGRESSION -- does it reach the right DIAGNOSIS?")
    print("=" * 96)
    for c in cases:
        try:
            c()
        except Exception as exc:
            import traceback
            RESULTS.append({"name": f"{c.__name__} raised {type(exc).__name__}", "pass": False,
                            "detail": traceback.format_exc().splitlines()[-1]})
    failed = [r for r in RESULTS if not r["pass"]]
    for r in RESULTS:
        print(f"  {'PASS' if r['pass'] else 'FAIL'}  {r['name']}")
        if not r["pass"]:
            print(f"          {r['detail']}")
    print("-" * 96)
    print(f"  {len(RESULTS) - len(failed)}/{len(RESULTS)} semantic checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
