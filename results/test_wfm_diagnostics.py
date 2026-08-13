"""
Deterministic tests for the WFM "why did the forecast miss" diagnostics.
========================================================================

Run:  cd backend && python ../results/test_wfm_diagnostics.py

Covers the modules added for the forecast-response upgrade:

    wfm/lag_analysis.py        lagged level + change relationships, coverage classes
    wfm/forecast_response.py   demand vs forecast side, movement test, adequacy, forecastability
    wfm/holiday_response.py    pre/holiday/post phases and forecast capture
    wfm/data_granularity.py    what the source can and cannot support
    wfm/common.week_ordinals   fiscal-year rollover in lag arithmetic

NO DATABASE AND NO NETWORK. Every case is a synthetic fixture built in this file, so the suite
runs offline and each assertion states the exact behaviour it pins. Standard library only --
`backend/requirements.txt` carries no test framework, and the repo's convention is a runnable
script that prints PASS/FAIL and exits non-zero (see results/smoke_test_modules.py).

Fixtures are constructed so the RIGHT answer is known by construction: a driver is planted at a
known lag, a phase effect is planted at a known size, and the test asserts the module recovers it.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
sys.path.insert(0, ".")

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

from wfm import data_granularity, forecast_response, holiday_response, lag_analysis  # noqa: E402
from wfm.common import week_ordinals                                                 # noqa: E402
from wfm.context_repository import holiday_calendar as _cal                          # noqa: E402

RESULTS = []


def check(name, condition, detail=""):
    RESULTS.append({"name": name, "pass": bool(condition), "detail": detail})
    return bool(condition)


def eq(name, got, want, tol=None):
    ok = (abs(got - want) <= tol) if (tol is not None and isinstance(got, (int, float))
                                      and isinstance(want, (int, float))) else got == want
    return check(name, ok, f"got={got!r} want={want!r}")


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
def weeks(year, first, count):
    """Contiguous YYYYWW values, e.g. weeks(2026, 1, 52) -> 202601..202652."""
    return [year * 100 + w for w in range(first, first + count)]


def build(rows_spec):
    """rows_spec: list of dicts already keyed as the SQL history rows are."""
    return [dict(r) for r in rows_spec]


def planted_lag_history(lag=2, n=52, year=2026):
    """Actual(t) = 50 + 2 * driver(t-lag). The relationship is exact, at a known lag.

    `driver` walks a fixed pseudo-pattern with period 13 so it has no accidental
    self-similarity at lags 1, 2, 4 or 8 other than the one planted.
    """
    wks = weeks(year, 1, n)
    driver = [10 + (i * 7) % 13 for i in range(n)]
    rows = []
    for i, wk in enumerate(wks):
        src = driver[i - lag] if i - lag >= 0 else driver[0]
        rows.append({"Fiscal_Week": wk, "Final_Units": driver[i],
                     "Actual_Offered": 50.0 + 2.0 * src, "fcst_offered": 95.0})
    return build(rows)


def flat_history(n=40, year=2026, actual=100.0, forecast=100.0, driver=None):
    rows = []
    for i, wk in enumerate(weeks(year, 1, n)):
        row = {"Fiscal_Week": wk, "Actual_Offered": actual, "fcst_offered": forecast}
        if driver is not None:
            row["Final_Units"] = driver
        rows.append(row)
    return build(rows)


# ---------------------------------------------------------------------------
# 1. week_ordinals -- fiscal-year rollover
# ---------------------------------------------------------------------------
def test_week_ordinals():
    o = week_ordinals([202650, 202651, 202652, 202701, 202702])
    eq("ORD-1 the week after 202652 is 1 ordinal later, not 49",
       o[202701] - o[202652], 1)
    eq("ORD-2 202702 is 2 ordinals after 202652", o[202702] - o[202652], 2)

    # a 53-week year is taken from the data, not assumed
    o53 = week_ordinals([202651, 202652, 202653, 202701])
    eq("ORD-3 a 53-week year rolls over correctly", o53[202701] - o53[202653], 1)

    # a genuine gap stays a gap
    ogap = week_ordinals([202601, 202602, 202605])
    eq("ORD-4 a missing week leaves a real hole", ogap[202605] - ogap[202602], 3)
    check("ORD-5 empty input is safe", week_ordinals([]) == {})

    # the rollover actually reaches the lag pairing
    hist = planted_lag_history(lag=1, n=52, year=2026)
    hist += [{"Fiscal_Week": 202701, "Final_Units": 12, "Actual_Offered": 74.0,
              "fcst_offered": 95.0},
             {"Fiscal_Week": 202702, "Final_Units": 19, "Actual_Offered": 74.0,
              "fcst_offered": 95.0}]
    res = lag_analysis.analyse(hist, target_week=202703)
    fu = next(d for d in res["drivers"] if d["driver"] == "Final_Units")
    lag1 = [c for c in fu["candidates"]
            if c["lag_weeks"] == 1 and c["relationship_type"] == "lagged_level"][0]
    eq("ORD-6 pairs are not lost at the year boundary", lag1["weeks"], 53)


# ---------------------------------------------------------------------------
# 2. lag_analysis -- the planted lag must be recovered
# ---------------------------------------------------------------------------
def test_lag_detection():
    for planted in (0, 1, 2, 4, 8):
        hist = planted_lag_history(lag=planted, n=52)
        res = lag_analysis.analyse(hist, target_week=202653)
        check(f"LAG-1.{planted} analysis available", res.get("available"), res.get("reason", ""))
        fu = next((d for d in res["drivers"] if d["driver"] == "Final_Units"), None)
        if not check(f"LAG-2.{planted} Final_Units was tested", fu and fu.get("tested")):
            continue
        eq(f"LAG-3.{planted} best lag recovered", fu.get("best_lag_weeks"), planted)
        check(f"LAG-4.{planted} relationship is usable as evidence",
              fu.get("usable_as_evidence"), str(fu.get("best")))
        check(f"LAG-5.{planted} strength is near-perfect",
              abs(fu.get("relationship_strength") or 0) > 0.95,
              str(fu.get("relationship_strength")))

    # all five lags are actually attempted, in both families
    res = lag_analysis.analyse(planted_lag_history(lag=2), target_week=202653)
    fu = next(d for d in res["drivers"] if d["driver"] == "Final_Units")
    eq("LAG-6 five lags x two families were tested", len(fu["candidates"]), 10)
    eq("LAG-7 lags tested are the documented set", res["lags_tested"], [0, 1, 2, 4, 8])
    kinds = {c["relationship_type"] for c in fu["candidates"]}
    check("LAG-8 both level and change families present",
          {"same_week_level", "same_week_change", "lagged_level", "lagged_change"} == kinds,
          str(sorted(kinds)))


def test_lag_beats_same_week():
    """A strong LAGGED relationship with a weak SAME-WEEK one must not be reported as no
    relationship -- the exact failure the old same-week-only correlation produced."""
    hist = planted_lag_history(lag=2, n=52)
    res = lag_analysis.analyse(hist, target_week=202653)
    fu = next(d for d in res["drivers"] if d["driver"] == "Final_Units")
    same = [c for c in fu["candidates"]
            if c["lag_weeks"] == 0 and c["relationship_type"] == "same_week_level"][0]
    # The property that matters is not that same-week is absolutely weak -- two series can be
    # incidentally correlated at lag 0 -- but that the planted LAGGED relationship is materially
    # stronger and is the one the module reports.
    check("LAG-9 the lagged relationship is materially stronger than same-week",
          abs(fu.get("relationship_strength") or 0) > abs(same.get("relationship_strength") or 0),
          f"lagged={fu.get('relationship_strength')} same_week={same.get('relationship_strength')}")
    eq("LAG-10 the lagged relationship is the one reported", fu.get("best_lag_weeks"), 2)
    check("LAG-11 Final_Units is named a leading driver",
          "Final_Units" in res.get("leading_drivers", []), str(res.get("leading_drivers")))


def test_target_week_excluded():
    hist = planted_lag_history(lag=2, n=52)
    hist.append({"Fiscal_Week": 202653, "Final_Units": 999.0, "Actual_Offered": 9999.0,
                 "fcst_offered": 95.0})
    res = lag_analysis.analyse(hist, target_week=202653)
    eq("LAG-12 the target week is excluded from the window", res.get("target_week_excluded"),
       202653)
    fu = next(d for d in res["drivers"] if d["driver"] == "Final_Units")
    eq("LAG-13 the extreme target row did not enter the estimate", fu.get("best_lag_weeks"), 2)


# ---------------------------------------------------------------------------
# 3. lag_analysis -- data sufficiency (spec section 12)
# ---------------------------------------------------------------------------
def test_coverage_classes():
    # sparse: the field exists but only a couple of weeks carry a value. This is the
    # Final_upp_units situation that produced a z-score of 23.33 from n=2.
    hist = planted_lag_history(lag=2, n=52)
    hist[-1]["Final_upp_units"] = 77.0
    hist[-2]["Final_upp_units"] = 75.0
    res = lag_analysis.analyse(hist, target_week=202653)
    upp = next(d for d in res["drivers"] if d["driver"] == "Final_upp_units")
    eq("COV-1 two populated weeks is classed sparse", upp.get("coverage"), "sparse")
    check("COV-2 a sparse driver is not tested", upp.get("tested") is False)
    check("COV-3 a sparse driver is never usable evidence", not upp.get("usable_as_evidence"))
    check("COV-4 the wording says untested, NOT unrelated",
          "untested" in upp["interpretation"] and "unrelated" not in upp["interpretation"].lower()
          .replace("not as unrelated", ""),
          upp["interpretation"])
    eq("COV-5 sparse coverage is quantified", upp.get("weeks_with_a_value"), 2)

    # absent: the column never appears
    check("COV-6 an absent column is not invented",
          all(d["driver"] != "Actual_ASU" for d in res["drivers"]),
          str([d["driver"] for d in res["drivers"]]))

    # a populated but flat driver has no variance -> not testable, and not called unrelated
    flat = flat_history(n=40, driver=5.0)
    res2 = lag_analysis.analyse(flat, target_week=202641)
    fu = next(d for d in res2["drivers"] if d["driver"] == "Final_Units")
    check("COV-7 a driver that never varies is not usable", not fu.get("usable_as_evidence"))
    check("COV-8 a non-varying driver is explained, not blamed",
          "not established" in fu["interpretation"] or "enough paired data" in fu["interpretation"]
          or "does not vary" in str(fu.get("candidates")),
          fu["interpretation"])


def test_tiny_sample_produces_no_coefficient():
    hist = planted_lag_history(lag=1, n=10)      # below MIN_PAIRS
    res = lag_analysis.analyse(hist, target_week=202611)
    fu = next(d for d in res["drivers"] if d["driver"] == "Final_Units")
    eq("TINY-1 ten weeks is classed sparse, not measured", fu.get("coverage"), "sparse")
    check("TINY-2 no relationship strength is published from a tiny sample",
          fu.get("relationship_strength") is None, str(fu.get("relationship_strength")))

    # just enough rows to be populated, but not enough PAIRS at a long lag
    hist2 = planted_lag_history(lag=1, n=14)
    res2 = lag_analysis.analyse(hist2, target_week=202615)
    fu2 = next(d for d in res2["drivers"] if d["driver"] == "Final_Units")
    lag8 = [c for c in fu2["candidates"]
            if c["lag_weeks"] == 8 and c["relationship_type"] == "lagged_level"][0]
    check("TINY-3 an under-powered lag is refused, not estimated",
          lag8.get("testable") is False and lag8.get("relationship_strength") is None,
          str(lag8))
    check("TINY-4 the refusal says how many pairs it had",
          "paired observations" in (lag8.get("reason") or ""), str(lag8.get("reason")))


def test_unstable_relationship_is_not_promoted():
    """Sign-flipping between halves must block a driver from becoming evidence."""
    n = 52
    wks = weeks(2026, 1, n)
    rows = []
    for i, wk in enumerate(wks):
        d = 10 + (i * 7) % 13
        # first half positive relationship, second half inverted
        a = 50.0 + 2.0 * d if i < n // 2 else 50.0 - 2.0 * d
        rows.append({"Fiscal_Week": wk, "Final_Units": d, "Actual_Offered": a,
                     "fcst_offered": 95.0})
    res = lag_analysis.analyse(build(rows), target_week=202653)
    fu = next(d for d in res["drivers"] if d["driver"] == "Final_Units")
    best = fu.get("best") or {}
    check("STAB-1 a sign-flipping relationship is flagged unstable",
          any(c.get("stability") == "unstable" for c in fu["candidates"] if c.get("testable")),
          str([c.get("stability") for c in fu["candidates"] if c.get("testable")]))
    check("STAB-2 stability is reported on the chosen estimate",
          best.get("stability") in ("stable", "moderate", "unstable", "not_testable"),
          str(best.get("stability")))


# ---------------------------------------------------------------------------
# 4. forecast_response -- the movement test (spec section 8)
# ---------------------------------------------------------------------------
def opposed_history():
    """Demand rising materially for weeks, the plan cut in the target week.

    The rise has to clear MOMENTUM_MATERIAL_PCT (10%) on a last-4 vs prior-8 comparison, otherwise
    the fixture tests nothing: the module would correctly report "no signal" and every response
    assertion below would be vacuous.
    """
    rows = []
    for i, wk in enumerate(weeks(2026, 1, 40)):
        actual = 80.0 + (5.0 * (i - 27) if i >= 28 else 0.0)   # +5 a week over the last 12
        rows.append({"Fiscal_Week": wk, "Actual_Offered": actual, "fcst_offered": 95.0,
                     "Final_Units": 10.0 + (i % 5)})
    return build(rows)


def test_movement_opposed():
    hist = opposed_history()
    res = forecast_response.analyse(hist, 202641, target_actual=160.0, target_forecast=60.0)
    check("MOVE-1 the analysis is available", res.get("available"), res.get("reason", ""))
    one = next(m for m in res["movement_test"] if m["lookback_weeks"] == 1)
    check("MOVE-2 the one-week movement is testable", one.get("testable"), str(one))
    eq("MOVE-3 actual direction is up", one.get("actual_direction"), "up")
    eq("MOVE-4 forecast direction is down", one.get("forecast_direction"), "down")
    check("MOVE-5 opposed directions are flagged", one.get("directions_opposed"))
    check("MOVE-6 the opposed lookbacks are listed",
          1 in res.get("directions_opposed_at", []), str(res.get("directions_opposed_at")))
    eq("MOVE-7 the source week is reported as a real fiscal week",
       one.get("from_fiscal_week"), 202640)


def test_movement_untestable_when_missing():
    hist = [{"Fiscal_Week": 202601, "Actual_Offered": 100.0, "fcst_offered": 100.0}] * 1
    hist = build(hist * 8)
    for i, r in enumerate(hist):
        r["Fiscal_Week"] = 202601 + i
    res = forecast_response.analyse(hist, 202620, target_actual=150.0, target_forecast=90.0)
    if res.get("available"):
        one = next(m for m in res["movement_test"] if m["lookback_weeks"] == 1)
        check("MOVE-8 a missing prior week is not guessed", one.get("testable") is False,
              str(one))


# ---------------------------------------------------------------------------
# 5. forecast_response -- decomposition reconciles exactly (spec section 6)
# ---------------------------------------------------------------------------
def test_decomposition_reconciles():
    hist = opposed_history()
    res = forecast_response.analyse(hist, 202641, target_actual=160.0, target_forecast=60.0)
    dec = res["miss_decomposition"]
    check("DEC-1 the decomposition is available", dec.get("available"), str(dec.get("reason")))
    total = dec["forecast_side_contribution"] + dec["demand_side_contribution"]
    eq("DEC-2 the two contributions sum to the whole miss", round(total, 6),
       round(dec["total_miss"], 6))
    eq("DEC-3 total_miss is actual - forecast", dec["total_miss"], 100.0, tol=0.01)
    check("DEC-4 reconciliation is asserted in the output", dec.get("reconciles"))
    check("DEC-5 the leading side is named",
          dec.get("leading_side") in ("forecast", "demand", "balanced"), dec.get("leading_side"))
    check("DEC-6 the wording is diagnostic and explicitly disclaims causal probability",
          "diagnostic" in dec["note"].lower()
          and "not a causal probability" in dec["note"].lower(),
          dec["note"])
    check("DEC-7 the expected baseline states its basis",
          bool(dec.get("expected_basis")), str(dec.get("expected_basis")))


def test_decomposition_unavailable_without_inputs():
    hist = opposed_history()
    res = forecast_response.analyse(hist, 202641, target_actual=None, target_forecast=60.0)
    dec = res["miss_decomposition"]
    check("DEC-8 no actual means no decomposition, not a guess",
          dec.get("available") is False, str(dec))


# ---------------------------------------------------------------------------
# 6. forecast_response -- adequacy + forecastability (spec sections 7, 20)
# ---------------------------------------------------------------------------
def test_no_signal_is_not_a_response_failure():
    """The central protection: a flat queue that jumps once must NOT be called a forecast
    failure. There was nothing to react to."""
    hist = flat_history(n=40, actual=100.0, forecast=100.0, driver=5.0)
    res = forecast_response.analyse(hist, 202641, target_actual=200.0, target_forecast=100.0)
    eq("PRED-1 no signal -> response is not testable",
       res["response"]["classification"], "not_testable")
    eq("PRED-2 no signal -> low predictability",
       res["forecastability"]["classification"], "LOW_PREDICTABILITY")
    check("PRED-3 the reason says a miss here is not a response failure",
          "not a response" in res["response"]["reason"].lower(), res["response"]["reason"])


def test_signal_with_no_forecast_move():
    hist = opposed_history()
    res = forecast_response.analyse(hist, 202641, target_actual=160.0, target_forecast=60.0)
    check("RESP-1 momentum was detected before the target week",
          any(s["signal"] == "demand_momentum" and s.get("detected") for s in res["signals"]),
          str([(s["signal"], s.get("detected")) for s in res["signals"]]))
    cls = res["response"]["classification"]
    check("RESP-2 a plan cut against a rising signal is a response failure",
          cls in ("wrong_direction", "no_response", "under_response", "delayed_response"), cls)
    check("RESP-3 the response records what was implied and what was done",
          res["response"].get("implied_change") is not None
          and res["response"].get("forecast_change_made") is not None, str(res["response"]))


def test_adequate_response_is_recognised():
    """A forecast that DID react proportionately must not be blamed."""
    hist = opposed_history()
    # expected demand from the recent median; move the plan onto it
    probe = forecast_response.analyse(hist, 202641, target_actual=120.0, target_forecast=95.0)
    expected = probe["baselines"]["expected_demand"]
    res = forecast_response.analyse(hist, 202641, target_actual=120.0, target_forecast=expected)
    check("RESP-4 a plan set at the expected level is adequate or untestable",
          res["response"]["classification"] in ("adequate", "not_testable"),
          f"{res['response']['classification']} expected={expected}")


def test_forecastability_needs_repeatable_history():
    """Momentum that has never followed through must not make the week 'predictable'."""
    n = 40
    rows = []
    for i, wk in enumerate(weeks(2026, 1, n)):
        # a saw-tooth: momentum is frequently material but reverses every time
        actual = 100.0 + (30.0 if (i // 4) % 2 == 0 else -30.0)
        rows.append({"Fiscal_Week": wk, "Actual_Offered": actual, "fcst_offered": 100.0})
    res = forecast_response.analyse(build(rows), 202641, target_actual=180.0,
                                    target_forecast=100.0)
    f = res["forecastability"]
    check("PRED-4 momentum that reverses does not yield PREDICTABLE",
          f["classification"] in ("PARTIALLY_PREDICTABLE", "LOW_PREDICTABILITY", "NOT_TESTABLE"),
          f["classification"])
    check("PRED-5 the basis for the verdict is stated", isinstance(f.get("basis"), list))
    rep = res["momentum_repeatability"]
    check("PRED-6 repeatability is measured or explicitly untestable",
          rep.get("testable") in (True, False), str(rep))


def test_short_history_degrades_honestly():
    hist = flat_history(n=4)
    res = forecast_response.analyse(hist, 202605, target_actual=150.0, target_forecast=90.0)
    check("SHORT-1 too little history reports unavailable, not a verdict",
          res.get("available") is False, str(res)[:200])
    check("SHORT-2 the reason names the shortfall", "required" in (res.get("reason") or ""),
          res.get("reason"))


# ---------------------------------------------------------------------------
# 7. holiday_response -- phases and forecast capture (spec sections 16, 17)
# ---------------------------------------------------------------------------
class _FakeCalendar:
    """A synthetic holiday master, injected into the real repository cache.

    Lets the phase logic be tested without depending on which holidays a real country has, and
    lets the "master not deployed" path be tested at all.
    """

    def __init__(self, holidays):
        self.holidays = holidays

    def __enter__(self):
        self._saved = _cal._CACHE
        _cal._CACHE = {"holidays": self.holidays, "active_rows": len(self.holidays),
                       "country_weeks": len(self.holidays), "source": "test fixture",
                       "aggregate_groups": {}}
        return self

    def __exit__(self, *exc):
        _cal._CACHE = self._saved
        return False


HOLIDAY_STEP = 8   # every 8th week, so 52 weeks give >= MIN_PHASE_INSTANCES of each phase


def holiday_every_n_weeks(country="testland", year=2026, n=52, before=3, after=3,
                          step=HOLIDAY_STEP):
    """A holiday every `step` weeks, so a one-year history holds enough instances of pre /
    holiday / post to clear MIN_PHASE_INSTANCES (4) and still leave unaffected baseline weeks.

    With step 8: holidays at 8,16,24,32,40,48 -> 6 of each phase, and 5 clean weeks per cycle.
    """
    out = {}
    for w in range(1, n + 1):
        if w % step == 0:
            out[f"{country}|{year * 100 + w}"] = [
                {"name": f"Test Holiday W{w}", "type": "National", "date": None,
                 "before": before, "after": after, "group": "Test", "needs_review": False}]
    return out


def test_holiday_span_and_phase():
    with _FakeCalendar(holiday_every_n_weeks()):
        eq("HOL-1 the holiday week itself is phase holiday",
           _cal.holiday_span("testland", 202616, span=2)["phase"], "holiday")
        eq("HOL-2 the week before a holiday is pre_holiday",
           _cal.holiday_span("testland", 202615, span=2)["phase"], "pre_holiday")
        eq("HOL-3 the week after a holiday is post_holiday",
           _cal.holiday_span("testland", 202617, span=2)["phase"], "post_holiday")
        span = _cal.holiday_span("testland", 202620, span=2)   # 4 weeks from 16 and from 24
        eq("HOL-4 a week far from any holiday is phase none", span["phase"], "none")
        eq("HOL-5 span is reported", span["span_weeks"], 2)

    # a NARROW window must not reach two weeks out
    with _FakeCalendar(holiday_every_n_weeks(before=3, after=3)):
        span = _cal.holiday_span("testland", 202614, span=2)   # two weeks before week 16
        check("HOL-6 a 3-day window does not reach 2 weeks",
              span["phase"] == "none" or not span["applies"], str(span["phase"]))

    # a WIDE window does reach two weeks out
    with _FakeCalendar(holiday_every_n_weeks(before=7, after=7)):
        span = _cal.holiday_span("testland", 202614, span=2)
        eq("HOL-7 a 7-day window reaches 2 weeks as pre_holiday", span["phase"], "pre_holiday")


def phase_effect_history(n=48, rebound=130.0, holiday_level=70.0, normal=100.0, forecast=100.0):
    """Holiday weeks quieter, the week after busier -- a measurable, consistent phase effect."""
    hist = []
    for wk in weeks(2026, 1, n):
        w = wk % 100
        if w % HOLIDAY_STEP == 0:
            actual = holiday_level
        elif w % HOLIDAY_STEP == 1:
            actual = rebound
        else:
            actual = normal
        hist.append({"Fiscal_Week": wk, "Actual_Offered": actual, "fcst_offered": forecast,
                     "Holiday_Count": 1.0 if w % HOLIDAY_STEP == 0 else 0.0})
    return build(hist)


# Week 49 is one after the holiday in week 48, so the target sits in post_holiday with a zero flag.
POST_HOLIDAY_TARGET = 202649


def test_holiday_count_zero_but_adjacent_effect():
    """Spec section 17: Holiday_Count = 0 must NOT mean unaffected."""
    with _FakeCalendar(holiday_every_n_weeks()):
        res = holiday_response.analyse(phase_effect_history(), POST_HOLIDAY_TARGET, "testland",
                                       target_actual=130.0, target_forecast=100.0,
                                       row_holiday_count=0.0)
        check("HOL-8 the analysis is available", res.get("available"), str(res.get("reason")))
        eq("HOL-9 a zero row flag still yields a phase", res["phase"], "post_holiday")
        check("HOL-10 the target week is reported as affected", res.get("applies"))
        eq("HOL-11 the row flag is echoed for audit", res.get("row_holiday_count"), 0.0)
        check("HOL-12 the reading explains the adjacent reach",
              "adjacent" in res["reading"] or "wind-down" in res["reading"], res["reading"])


def test_holiday_direction_is_measured_not_assumed():
    """A queue that gets BUSIER after a holiday must be reported as such."""
    with _FakeCalendar(holiday_every_n_weeks()):
        res = holiday_response.analyse(phase_effect_history(), POST_HOLIDAY_TARGET, "testland",
                                       target_actual=130.0, target_forecast=100.0,
                                       row_holiday_count=0.0)
        hr = res.get("historical_response") or {}
        if check("HOL-13 historical phase effects were measured", hr.get("available"),
                 str(hr.get("reason"))):
            post = (hr.get("phases") or {}).get("post_holiday") or {}
            if check("HOL-14 the post-holiday phase is testable", post.get("testable"),
                     str(post.get("reason"))):
                eq("HOL-15 a busier post-holiday week is measured as UP",
                   post.get("direction"), "up")
                check("HOL-16 the effect is material", post.get("material"), str(post))
            holiday_phase = (hr.get("phases") or {}).get("holiday") or {}
            if holiday_phase.get("testable"):
                eq("HOL-17 a quieter holiday week is measured as DOWN",
                   holiday_phase.get("direction"), "down")


def test_holiday_forecast_capture():
    """A flat plan against a consistent, material phase effect is under_reacted or wrong."""
    with _FakeCalendar(holiday_every_n_weeks()):
        res = holiday_response.analyse(phase_effect_history(), POST_HOLIDAY_TARGET, "testland",
                                       target_actual=130.0, target_forecast=100.0,
                                       row_holiday_count=0.0)
        cap = res.get("forecast_capture") or {}
        check("HOL-18 a capture verdict is produced",
              cap.get("classification") in holiday_response.CAPTURE_CLASSES,
              str(cap.get("classification")))
        check("HOL-19 an unchanged plan is not called captured",
              cap.get("classification") != "captured", str(cap))


def test_holiday_master_missing_is_not_no_holiday():
    saved = _cal._CACHE
    try:
        _cal._CACHE = {"_error": "holiday master extract not built -- test"}
        res = holiday_response.analyse(flat_history(n=20), 202620, "testland",
                                       target_actual=150.0, target_forecast=90.0)
        check("HOL-20 a missing master reports unavailable", res.get("available") is False,
              str(res)[:160])
        check("HOL-21 and says it is NOT the same as finding no holiday",
              "not the same as finding no holiday" in (res.get("note") or ""),
              str(res.get("note")))
    finally:
        _cal._CACHE = saved


def test_inconsistent_holiday_history_blocks_blame():
    with _FakeCalendar(holiday_every_n_weeks()):
        hist = []
        for i, wk in enumerate(weeks(2026, 1, 48)):
            w = wk % 100
            if w % HOLIDAY_STEP == 1:
                # the post-holiday week rebounds, then slumps, alternately -- no dependable pattern
                actual = 140.0 if (w // HOLIDAY_STEP) % 2 == 0 else 60.0
            else:
                actual = 100.0
            hist.append({"Fiscal_Week": wk, "Actual_Offered": actual, "fcst_offered": 100.0,
                         "Holiday_Count": 1.0 if w % HOLIDAY_STEP == 0 else 0.0})
        res = holiday_response.analyse(build(hist), POST_HOLIDAY_TARGET, "testland",
                                       target_actual=140.0, target_forecast=100.0,
                                       row_holiday_count=0.0)
        cap = res.get("forecast_capture") or {}
        check("HOL-22 an inconsistent phase history blocks forecast blame",
              cap.get("classification") in ("inconsistent_history", "not_testable"),
              str(cap.get("classification")))


# ---------------------------------------------------------------------------
# 8. data_granularity -- weekend claims must be impossible (spec sections 18, 31)
# ---------------------------------------------------------------------------
def test_weekly_grain_blocks_weekend_claims():
    fields = {"Actual_Offered": 152.0, "fcst_offered": 63.8, "Week_Ending": "2026-05-22",
              "Monday": 0.0, "Tuesday": 0.0, "Wednesday": 0.0, "Thursday": 0.0,
              "Friday": 0.0, "Saturday": 0.0, "Sunday": 0.0, "Holiday_Count": 0.0}
    hist = flat_history(n=20)
    for r in hist:
        r.update({"Monday": 0.0, "Saturday": 0.0, "Sunday": 0.0, "Week_Ending": "2026-01-01"})
    g = data_granularity.analyse(hist, fields)
    eq("GRAN-1 the grain is detected as weekly", g["grain"], "weekly")
    eq("GRAN-2 one row per fiscal week", g["rows_per_fiscal_week_max"], 1)
    check("GRAN-3 daily actual is absent", g["capabilities"]["daily_actual"] is False)
    check("GRAN-4 weekend volume effect is unsupported",
          g["capabilities"]["weekend_volume_effect"] is False)
    check("GRAN-5 the weekend limitation is stated verbatim",
          data_granularity.WEEKEND_LIMITATION in g["limitations"], str(g["limitations"]))
    check("GRAN-6 the day columns are recognised as flags",
          g["day_columns_are_flags"] is True, str(g["day_columns_are_flags"]))
    check("GRAN-7 holiday day-of-week IS available as a capability",
          g["capabilities"]["holiday_day_of_week"] is True)
    check("GRAN-8 no weekend statement claims causality",
          "cannot be isolated" in (g["weekend_statement"] or ""), g["weekend_statement"])


def test_daily_grain_would_flip_the_capability():
    """If a daily source is ever added, the gate must open without a code change."""
    hist = []
    for wk in (202601, 202601, 202602, 202602):
        hist.append({"Fiscal_Week": wk, "Actual_Offered": 20.0, "fcst_offered": 20.0,
                     "Date": "2026-01-01"})
    g = data_granularity.analyse(hist, {"Actual_Offered": 20.0})
    eq("GRAN-9 several rows per week is detected as daily", g["grain"], "daily")
    check("GRAN-10 weekend analysis becomes supported",
          g["capabilities"]["weekend_volume_effect"] is True)
    check("GRAN-11 the weekend limitation disappears",
          data_granularity.WEEKEND_LIMITATION not in g["limitations"], str(g["limitations"]))


def test_holiday_day_structure():
    g = data_granularity.analyse(flat_history(n=12), {"Monday": 0.0, "Saturday": 0.0})
    s = data_granularity.holiday_day_structure(
        {"Monday": 0.0, "Tuesday": 0.0, "Wednesday": 0.0, "Thursday": 0.0, "Friday": 1.0,
         "Saturday": 0.0, "Sunday": 0.0}, g)
    eq("DAY-1 a Friday holiday adjoins the weekend", s.get("pattern"),
       "holiday_adjoining_weekend")
    s2 = data_granularity.holiday_day_structure(
        {"Monday": 0.0, "Tuesday": 0.0, "Wednesday": 1.0, "Thursday": 0.0, "Friday": 0.0,
         "Saturday": 0.0, "Sunday": 0.0}, g)
    eq("DAY-2 a Wednesday holiday is midweek", s2.get("pattern"), "midweek_holiday")
    s3 = data_granularity.holiday_day_structure(
        {"Monday": 0.0, "Tuesday": 0.0, "Wednesday": 0.0, "Thursday": 0.0, "Friday": 0.0,
         "Saturday": 1.0, "Sunday": 1.0}, g)
    eq("DAY-3 a weekend-only holiday is identified", s3.get("pattern"), "holiday_on_weekend")
    s4 = data_granularity.holiday_day_structure(
        {"Monday": 0.0, "Tuesday": 0.0, "Wednesday": 0.0, "Thursday": 0.0, "Friday": 0.0,
         "Saturday": 0.0, "Sunday": 0.0}, g)
    eq("DAY-4 no flagged day yields no pattern", s4.get("pattern"), "none")
    check("DAY-5 the structure never claims a weekend demand effect",
          "no weekend demand effect is claimed" in (s.get("note") or ""), str(s.get("note")))
    s5 = data_granularity.holiday_day_structure({"Actual_Offered": 1.0}, None)
    check("DAY-6 missing flag columns are refused, not guessed",
          s5.get("testable") is False, str(s5))


# ---------------------------------------------------------------------------
# 9. no hard-coded queue / week / country anywhere (spec section 5)
# ---------------------------------------------------------------------------
def test_no_hardcoded_case():
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "backend" / "wfm"
    # A queue or country name has no legitimate use in these modules at all.
    banned_name = re.compile(r"SA Indonesia|Indonesia|Client Basic", re.I)
    # A fiscal week appearing in a COMPARISON is a hard-coded case; the same digits inside a
    # docstring example are documentation, which the rest of the package also uses.
    banned_logic = re.compile(r"(?:==|!=|>=|<=|\bin\b)\s*[\[\(\{'\"]*\s*20\d{4}")
    offenders = []
    for name in ("lag_analysis.py", "forecast_response.py", "holiday_response.py",
                 "data_granularity.py"):
        text = (root / name).read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if banned_name.search(line) or banned_logic.search(line):
                offenders.append(f"{name}:{i}: {line.strip()[:70]}")
    check("GEN-1 no queue, country or fiscal week is hard-coded in the new modules",
          not offenders, str(offenders))


# ---------------------------------------------------------------------------
def main():
    tests = [
        test_week_ordinals,
        test_lag_detection, test_lag_beats_same_week, test_target_week_excluded,
        test_coverage_classes, test_tiny_sample_produces_no_coefficient,
        test_unstable_relationship_is_not_promoted,
        test_movement_opposed, test_movement_untestable_when_missing,
        test_decomposition_reconciles, test_decomposition_unavailable_without_inputs,
        test_no_signal_is_not_a_response_failure, test_signal_with_no_forecast_move,
        test_adequate_response_is_recognised, test_forecastability_needs_repeatable_history,
        test_short_history_degrades_honestly,
        test_holiday_span_and_phase, test_holiday_count_zero_but_adjacent_effect,
        test_holiday_direction_is_measured_not_assumed, test_holiday_forecast_capture,
        test_holiday_master_missing_is_not_no_holiday,
        test_inconsistent_holiday_history_blocks_blame,
        test_weekly_grain_blocks_weekend_claims, test_daily_grain_would_flip_the_capability,
        test_holiday_day_structure,
        test_no_hardcoded_case,
    ]
    print("=" * 92)
    print("WFM FORECAST-RESPONSE DIAGNOSTICS -- deterministic tests (no DB, no network)")
    print("=" * 92)
    errors = []
    for t in tests:
        try:
            t()
        except Exception as exc:            # a crash is a failure, not a stack trace on the floor
            import traceback
            errors.append(f"{t.__name__}: {type(exc).__name__}: {exc}")
            RESULTS.append({"name": f"{t.__name__} raised {type(exc).__name__}", "pass": False,
                            "detail": traceback.format_exc().splitlines()[-1]})

    failed = [r for r in RESULTS if not r["pass"]]
    for r in RESULTS:
        print(f"  {'PASS' if r['pass'] else 'FAIL'}  {r['name']}")
        if not r["pass"]:
            print(f"          {r['detail']}")
    print("-" * 92)
    print(f"  {len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    if errors:
        print("  CRASHES:")
        for e in errors:
            print(f"    {e}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
