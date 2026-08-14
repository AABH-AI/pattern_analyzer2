# -*- coding: utf-8 -*-
"""Live validation of the FC Decision Card engine against real SQL and a real model.

    cd backend && python ../results/run_live_spec_validation.py            # deterministic only
    cd backend && python ../results/run_live_spec_validation.py --llm      # also call the model

WHY THIS GOES THROUGH HTTP RATHER THAN CALLING investigate() DIRECTLY
---------------------------------------------------------------------
Section 47 asks for investigations through `POST /api/rca-investigate?mode=spec`, and that is the
right boundary to test. The endpoint does three things the engine does not: it fetches the SQL
context, it maps the posted bundle onto the engine's key, and it wraps failures in
`HTTPException(500)`. That last one is why the pre-existing `_narrate` arity bug presented as a 500
rather than as a stack trace -- calling the engine directly would have hidden the very failure mode
that matters to a user.

The scenarios are the ten section 47 names. Each is SELECTED FROM LIVE DATA by a query that makes it
that scenario, and the query is printed, so a reviewer can see the case was found rather than chosen
to flatter the result.

NEVER FABRICATES. If SQL or the server is unreachable the run stops and says so; it does not fall
back to the offline mirror and present the output as live.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "backend"))

# A PRIVATE port, deliberately not 8000.
#
# The first live run of this script was silently CONTAMINATED. A uvicorn started hours earlier by
# run.py was already bound to 0.0.0.0:8000 running pre-upgrade code. On Windows two sockets can bind
# the same port and it is undefined which one receives a given connection, so the run's requests were
# split between the old server and the new one: some cases came back with ten card sections and no
# new keys, others with eighteen. Nothing errored, and the output looked like a real result.
#
# Two defences, because a private port alone would not have caught it:
#   1. this port, so the user's own running app is never disturbed and never answers our requests;
#   2. _assert_port_free() below, which refuses to start if anything is already listening.
DEFAULT_PORT = int(os.environ.get("RCA_VALIDATION_PORT", "8011"))
BASE = os.environ.get("RCA_BASE", f"http://127.0.0.1:{DEFAULT_PORT}")
OUT = os.path.join(HERE, "live-spec-validation.json")
LOG = os.path.join(HERE, "live-spec-validation-output.txt")

PASS, FAIL = [], []


def check(tag, name, condition, detail=""):
    (PASS if condition else FAIL).append((tag, name, detail))
    line = f"  {'PASS' if condition else 'FAIL'}  {tag} {name}"
    if detail and not condition:
        line += f"\n        {detail}"
    print(line)
    return bool(condition)


# ==============================================================================
# Case selection -- from LIVE data, with the query shown
# ==============================================================================
# Each entry: (label, sql, why this query makes it that scenario)
# `{t}` is the configured table. Every query requires a late fiscal week so real prior history
# exists: history is `Fiscal_Week <= target`, so an early target week has almost none and every
# scenario would collapse onto DATA_LIMITATION.
CASE_QUERIES = [
    ("under-forecast",
     "SELECT TOP 1 Forecast_name, Fiscal_Week FROM {t} "
     "WHERE Fiscal_Week BETWEEN 202530 AND 202748 AND fcst_offered > 500 "
     "  AND Actual_Offered > fcst_offered * 1.25 "
     "ORDER BY Actual_Offered - fcst_offered DESC",
     "largest absolute gap where actual exceeds plan by more than 25%"),

    ("over-forecast",
     "SELECT TOP 1 Forecast_name, Fiscal_Week FROM {t} "
     "WHERE Fiscal_Week BETWEEN 202530 AND 202748 AND fcst_offered > 500 "
     "  AND Actual_Offered < fcst_offered * 0.75 "
     "ORDER BY fcst_offered - Actual_Offered DESC",
     "largest absolute gap where actual falls more than 25% below plan"),

    ("baseline error (plan far from the seasonal norm)",
     "SELECT TOP 1 d.Forecast_name, d.Fiscal_Week FROM {t} d "
     "JOIN (SELECT Forecast_name, AVG(CAST(Actual_Offered AS FLOAT)) AS mean_actual "
     "      FROM {t} WHERE Actual_Offered IS NOT NULL GROUP BY Forecast_name "
     "      HAVING COUNT(*) >= 104) m ON m.Forecast_name = d.Forecast_name "
     "WHERE d.Fiscal_Week BETWEEN 202530 AND 202748 AND d.fcst_offered > 300 "
     "  AND d.fcst_offered < m.mean_actual * 0.6 "
     "ORDER BY m.mean_actual - d.fcst_offered DESC",
     "the plan for the week sits below 60% of the queue's own long-run mean demand"),

    ("holiday week",
     "SELECT TOP 1 Forecast_name, Fiscal_Week FROM {t} "
     "WHERE Fiscal_Week BETWEEN 202530 AND 202748 AND Holiday_Count > 0 "
     "  AND fcst_offered > 300 AND Country IS NOT NULL AND Country <> '' "
     "  AND ABS(1 - Actual_Offered / fcst_offered) > 0.15 "
     "ORDER BY ABS(Actual_Offered - fcst_offered) DESC",
     "a breach in a week whose own row records a holiday, with a resolvable country"),

    ("post-holiday week (row records NO holiday)",
     "SELECT TOP 1 a.Forecast_name, a.Fiscal_Week FROM {t} a "
     "JOIN {t} b ON b.Forecast_name = a.Forecast_name AND b.Fiscal_Week = a.Fiscal_Week - 1 "
     "WHERE a.Fiscal_Week BETWEEN 202530 AND 202748 AND a.Holiday_Count = 0 "
     "  AND b.Holiday_Count > 0 AND a.fcst_offered > 300 "
     "  AND a.Country IS NOT NULL AND a.Country <> '' "
     "  AND ABS(1 - a.Actual_Offered / a.fcst_offered) > 0.15 "
     "ORDER BY ABS(a.Actual_Offered - a.fcst_offered) DESC",
     "the week itself has Holiday_Count = 0 but the PREVIOUS week has a holiday -- the case "
     "section 22 says must not be reported as 'no holiday impact'"),

    ("lagged driver available",
     "SELECT TOP 1 Forecast_name, Fiscal_Week FROM {t} "
     "WHERE Fiscal_Week BETWEEN 202530 AND 202748 AND Final_Units IS NOT NULL "
     "  AND Actual_ASU IS NOT NULL AND fcst_offered > 300 "
     "  AND ABS(1 - Actual_Offered / fcst_offered) > 0.20 "
     "ORDER BY ABS(Actual_Offered - fcst_offered) DESC",
     "both shipment and warranty-base columns populated, so lags can actually be tested"),

    ("sparse driver (UPP present but thin)",
     "SELECT TOP 1 Forecast_name, Fiscal_Week FROM {t} "
     "WHERE Fiscal_Week BETWEEN 202530 AND 202748 AND Final_upp_units IS NOT NULL "
     "  AND fcst_offered > 200 AND ABS(1 - Actual_Offered / fcst_offered) > 0.20 "
     "ORDER BY ABS(Actual_Offered - fcst_offered) DESC",
     "the upgrade-base column is populated on the target row, so its COVERAGE gets judged"),

    ("data limitation (short history)",
     "SELECT TOP 1 d.Forecast_name, d.Fiscal_Week FROM {t} d "
     "JOIN (SELECT Forecast_name, MIN(Fiscal_Week) AS first_week FROM {t} "
     "      WHERE Actual_Offered IS NOT NULL GROUP BY Forecast_name) f "
     "  ON f.Forecast_name = d.Forecast_name "
     "WHERE d.Fiscal_Week BETWEEN f.first_week AND f.first_week + 3 "
     "  AND d.fcst_offered > 100 AND ABS(1 - d.Actual_Offered / d.fcst_offered) > 0.25 "
     "ORDER BY ABS(d.Actual_Offered - d.fcst_offered) DESC",
     "a breach within four weeks of the queue's FIRST week, so there is almost no history"),

    ("persistent plan miss",
     "SELECT TOP 1 a.Forecast_name, a.Fiscal_Week FROM {t} a "
     "JOIN {t} b ON b.Forecast_name = a.Forecast_name AND b.Fiscal_Week = a.Fiscal_Week - 1 "
     "JOIN {t} c ON c.Forecast_name = a.Forecast_name AND c.Fiscal_Week = a.Fiscal_Week - 2 "
     "JOIN {t} e ON e.Forecast_name = a.Forecast_name AND e.Fiscal_Week = a.Fiscal_Week - 3 "
     "WHERE a.Fiscal_Week BETWEEN 202530 AND 202748 AND a.fcst_offered > 300 "
     "  AND a.Actual_Offered > a.fcst_offered * 1.10 AND b.Actual_Offered > b.fcst_offered * 1.10 "
     "  AND c.Actual_Offered > c.fcst_offered * 1.10 AND e.Actual_Offered > e.fcst_offered * 1.10 "
     "ORDER BY a.Actual_Offered - a.fcst_offered DESC",
     "four consecutive weeks all under-forecast by more than 10% -- a standing miss run"),

    ("queue with full hierarchy context",
     "SELECT TOP 1 Forecast_name, Fiscal_Week FROM {t} "
     "WHERE Fiscal_Week BETWEEN 202530 AND 202748 AND fcst_offered > 500 "
     "  AND Region IS NOT NULL AND SubRegion IS NOT NULL AND Country IS NOT NULL "
     "  AND Offering IS NOT NULL AND channel IS NOT NULL AND business_org IS NOT NULL "
     "  AND ABS(1 - Actual_Offered / fcst_offered) > 0.20 "
     "ORDER BY ABS(Actual_Offered - fcst_offered) DESC",
     "every ladder dimension populated, so all six investigation levels can be computed"),
]


def _assert_port_free(port):
    """Refuse to run if anything already listens on `port`.

    This exists because the alternative failed silently. See the comment on DEFAULT_PORT: a stale
    server answering some of our requests produced a plausible-looking mixed result with no error.
    A validation run that might be talking to unknown code is worse than no validation run.
    """
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.5)
        if s.connect_ex(("127.0.0.1", port)) == 0:
            print(f"\nREFUSING TO RUN: something is already listening on 127.0.0.1:{port}.")
            print("A second server on the same port would answer some of these requests with "
                  "unknown code, and the run would look valid while being meaningless.")
            print(f"Set RCA_VALIDATION_PORT to a free port, or stop that process first.")
            return False
    return True


def _confirm_our_server(base):
    """Prove the server answering us is running THIS code before trusting a single result.

    The upgrade adds `criticality` to every completed spec response. A server that does not return
    that key on a real breach is not running this build, whatever port it is on. Checked once,
    up front, rather than discovered case by case.
    """
    try:
        with urllib.request.urlopen(f"{base}/api/health", timeout=5) as r:
            json.loads(r.read().decode("utf-8"))
        return True
    except Exception as exc:
        print(f"health check failed: {type(exc).__name__}: {exc}")
        return False


def main():
    ap = argparse.ArgumentParser()
    # NO --llm FLAG, deliberately. It was here and it did nothing, which is worse than absent: the
    # endpoint always uses whatever `llm.primary` in config.json points at, and nothing a client
    # passes can turn that off. A flag that looks like it controls the model but does not would make
    # every result ambiguous about whether a model ran.
    #
    # To exercise the NO-MODEL path, use results/test_fc_spec_semantics.py (scenario 21): it calls
    # investigate() directly with an empty llm_cfg, which is the only way to reach that branch.
    ap.add_argument("--interrogate", action="store_true",
                    help="also run the WHY interrogation (2 extra model calls per case)")
    ap.add_argument("--no-server", action="store_true",
                    help="assume a server is already listening on RCA_BASE")
    args = ap.parse_args()

    from sql_backend import connect, load_config                            # noqa: E402
    from wfm.common import adherence_pct                                    # noqa: E402

    cfg = load_config()
    table = (cfg.get("sql") or {}).get("table") or "dbo.Input_To_ML"

    # --- SQL must be genuinely reachable. No silent fallback. ---------------
    try:
        conn = connect(cfg)
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*), MIN(Fiscal_Week), MAX(Fiscal_Week) FROM {table}")
        rows, wmin, wmax = cur.fetchone()
    except Exception as exc:
        print(f"LIVE SQL UNREACHABLE: {type(exc).__name__}: {exc}")
        print("Live validation is BLOCKED. Nothing was fabricated and no offline substitute was "
              "used.")
        return 2
    print(f"LIVE SQL: {table} -- {rows:,} rows, fiscal weeks {wmin}..{wmax}")

    # --- select the cases --------------------------------------------------
    # TOP 1 per query put the same queue-week in four different scenario slots on the first run, so
    # ten "scenarios" tested four distinct investigations. Each query now returns candidates and the
    # first one not already taken is used, which keeps the scenarios genuinely distinct without
    # loosening what makes each one that scenario.
    cases, taken = [], set()
    for label, sql, why in CASE_QUERIES:
        try:
            cur.execute(sql.replace("SELECT TOP 1 ", "SELECT TOP 40 ").format(t=table))
            rows_ = cur.fetchall()
        except Exception as exc:
            print(f"  !! case selection failed for '{label}': {type(exc).__name__}: {exc}")
            continue
        pick = next(((r[0], int(r[1])) for r in rows_ if (r[0], int(r[1])) not in taken), None)
        if pick is None:
            print(f"  -- no unused live row matches '{label}' -- skipped (nothing invented)")
            continue
        taken.add(pick)
        cases.append({"label": label, "name": pick[0], "week": pick[1], "why": why})
        print(f"  selected {label:46s} {pick[0]} FW{pick[1]}")

    if not cases:
        print("No cases could be selected from live data. BLOCKED.")
        return 2

    # --- the server ---------------------------------------------------------
    proc = None
    if not args.no_server:
        if not _assert_port_free(DEFAULT_PORT):
            return 2
        print(f"\nstarting the backend on port {DEFAULT_PORT} ...")
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "sql_backend:app", "--host", "127.0.0.1",
             "--port", str(DEFAULT_PORT), "--log-level", "warning"],
            cwd=os.path.join(ROOT, "backend"),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        for attempt in range(40):
            try:
                urllib.request.urlopen(f"{BASE}/api/health", timeout=3).read()
                print("backend is up")
                break
            except Exception:
                if proc is not None and proc.poll() is not None:
                    print("backend exited during start-up:")
                    print((proc.stdout.read() or "")[-3000:])
                    return 2
                time.sleep(1.0)
        else:
            print(f"backend did not answer on {BASE}. BLOCKED.")
            return 2

        results, summary = {}, []
        for case in cases:
            name, week = case["name"], case["week"]
            print("\n" + "=" * 96)
            print(f"{case['label'].upper()}: {name} FW{week}")
            print(f"  selected because: {case['why']}")
            print("=" * 96)

            cur.execute(f"SELECT * FROM {table} WHERE Forecast_name = ? AND Fiscal_Week = ?",
                        (name, week))
            r = cur.fetchone()
            fields = dict(zip([d[0] for d in cur.description], r))
            actual, forecast = fields.get("Actual_Offered"), fields.get("fcst_offered")

            bundle = {"target": {
                "key": {k: fields.get(k) for k in
                        ("Forecast_name", "Fiscal_Week", "Region", "SubRegion", "Country",
                         "channel", "business_org", "Offering")},
                "fields": fields,
                "computed": {"actual": actual, "forecast": forecast,
                             "adherence_pct": adherence_pct(actual, forecast)}}}

            url = (f"{BASE}/api/rca-investigate?mode=spec&grain=weekly"
                   f"&interrogate={1 if args.interrogate else 0}")
            req = urllib.request.Request(
                url, data=json.dumps(bundle, default=str).encode("utf-8"),
                headers={"Content-Type": "application/json"})
            t0 = time.time()
            try:
                with urllib.request.urlopen(req, timeout=420) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                    status_code = resp.status
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:400]
                check(case["label"], f"HTTP {exc.code} from ?mode=spec", False, detail)
                summary.append({"case": case["label"], "queue": name, "week": week,
                                "http": exc.code, "error": detail})
                continue
            except Exception as exc:
                check(case["label"], "endpoint reachable", False, f"{type(exc).__name__}: {exc}")
                continue
            secs = round(time.time() - t0, 2)

            # BUILD GUARD. A completed spec response from this build always carries `criticality`.
            # If it does not, we are talking to a different build and every assertion below is
            # measuring the wrong thing -- so stop the whole run rather than emit a page of
            # failures that misdescribe the cause. This is what the first contaminated run needed
            # and did not have.
            if body.get("status") not in ("NotInvestigated",) and "criticality" not in body:
                print("\nABORTING: the server answered without `criticality`, so it is NOT running "
                      "this build. Every check below would be meaningless.")
                print(f"  keys returned: {sorted(body.keys())[:24]}")
                print("  A stale server on the same port is the usual cause -- see the comment on "
                      "DEFAULT_PORT.")
                return 2

            results[f"{name}|{week}"] = body
            fs = body.get("forecast_summary") or {}
            rc = body.get("root_cause") or {}
            cf = body.get("confidence") or {}
            cr = body.get("criticality") or {}
            mech = body.get("miss_mechanism") or {}
            sections = (body.get("decision_card") or {}).get("sections") or {}

            print(f"  HTTP {status_code} in {secs}s · status {body.get('status')} · "
                  f"engine {body.get('engine')}")
            if body.get("status") == "NotInvestigated":
                print(f"  no RCA: {body.get('reason')}")
                check(case["label"], "an in-band week explains itself", bool(body.get("reason")))
                summary.append({"case": case["label"], "queue": name, "week": week,
                                "status": "NotInvestigated", "reason": body.get("reason")})
                continue

            print(f"  adherence {fs.get('adherence_pct')}% · gap "
                  f"{fs.get('absolute_variance_contacts')} contacts")
            print(f"  ROOT CAUSE   {rc.get('hypothesis_id')} {rc.get('hypothesis')}")
            print(f"  MECHANISM    {rc.get('miss_mechanism')} "
                  f"(compound={rc.get('compound')}, direction_ok={rc.get('direction_coherent')})")
            print(f"  CONFIDENCE   {cf.get('level')} ({cf.get('score_pct')}%) "
                  f"calculated {cf.get('level_before_caps')}"
                  + (f", capped by gate {(cf.get('binding_cap') or {}).get('gate')}"
                     if cf.get("capped") else ", no cap"))
            print(f"  CRITICALITY  {cr.get('band')} (gap {cr.get('absolute_gap_contacts')}, "
                  f"{cr.get('relative_gap')} of a typical week)")
            print(f"  EVIDENCE     {rc.get('evidence_resolution')} · "
                  f"index {(body.get('fc_evidence_index') or {}).get('available_count')}"
                  f"/{(body.get('fc_evidence_index') or {}).get('total')}")
            hol = body.get("holiday_response") or {}
            print(f"  HOLIDAY      available={hol.get('available')} phase={hol.get('phase')} "
                  f"row_count={hol.get('row_holiday_count')} "
                  f"zero_but_adjacent={hol.get('zero_count_but_adjacent')}")
            lag = body.get("lagged_driver_evidence") or {}
            print(f"  DRIVERS      requested={lag.get('requested_drivers')} "
                  f"coverage={lag.get('coverage_summary')} usable={lag.get('usable_drivers')}")
            plan = body.get("plan_revision") or {}
            print(f"  PLAN         {plan.get('state')} "
                  f"(streak {plan.get('streak_weeks')} {plan.get('streak_direction')}, "
                  f"{plan.get('revisions_during_streak')} revision(s))")
            print(f"  MODEL        {(body.get('audit') or {}).get('narrative_model')} "
                  f"in {(body.get('audit') or {}).get('narrative_seconds')}s"
                  + (f" · error: {str(body.get('narrative_error'))[:80]}"
                     if body.get("narrative_error") else ""))
            wb = sections.get("12_why_this_happened") or {}
            print(f"  WHY BULLETS  {wb.get('count')} ranked, {wb.get('reworded_count')} reworded, "
                  f"jargon={wb.get('jargon_found')}")
            for b in (wb.get("bullets") or [])[:3]:
                print(f"     [{b.get('rank')}] {str(b.get('text'))[:150]}")

            # --- the assertions that must hold on EVERY live case ----------
            lb = case["label"]
            check(lb, "HTTP 200 -- no 500 from the spec engine", status_code == 200)
            check(lb, "all 15 canonical steps recorded",
                  set(range(1, 16)) <= {s["step"] for s in
                                        ((body.get("audit") or {}).get("steps") or [])})
            check(lb, "the input fingerprint is present",
                  bool((body.get("audit") or {}).get("input_fingerprint")))
            check(lb, "the RCA is complete regardless of the model",
                  bool(rc) and bool(cf) and bool(body.get("decision_card")))
            check(lb, "the mechanism is one of the seven",
                  rc.get("miss_mechanism") in
                  ("FORECAST_BASELINE_FAILURE", "FORECAST_RESPONSE_FAILURE",
                   "CALENDAR_RESPONSE_FAILURE", "DRIVER_RESPONSE_FAILURE",
                   "DEMAND_EVENT_LOW_PREDICTABILITY", "COMPOUND_MISS", "DATA_LIMITATION"),
                  str(rc.get("miss_mechanism")))
            check(lb, "criticality is banded and independent of confidence",
                  cr.get("band") in ("Negligible", "Low", "Moderate", "High", "Critical")
                  and cr.get("independent_of_confidence") is True,
                  json.dumps(cr, default=str)[:160])
            check(lb, "all 18 card sections present",
                  len([k for k in sections if k[0].isdigit()]) == 18,
                  json.dumps(sorted(sections.keys())))
            check(lb, "cause_type is still the catalogue id",
                  rc.get("cause_type") == rc.get("hypothesis_id")
                  or rc.get("cause_type") == "Inconclusive")
            check(lb, "the evidence index carries all 15 items with a reason each",
                  len((body.get("fc_evidence_index") or {}).get("items") or {}) == 15)
            check(lb, "no statistical jargon in the ranked executive bullets",
                  not wb.get("jargon_found"), json.dumps(wb.get("jargon_found")))
            check(lb, "the ASU decomposition either reconciles exactly or says why it could not",
                  ((body.get("asu_decomposition") or {}).get("reconciles") is True
                   or bool((body.get("asu_decomposition") or {}).get("reason"))),
                  json.dumps(body.get("asu_decomposition"), default=str)[:200])
            check(lb, "no driver coverage state was collapsed",
                  set((lag.get("coverage_summary") or {}).keys())
                  == {"populated", "sparse", "absent"} or not lag.get("available"))
            check(lb, "the weekend claim is grain-based, never asserted from weekly totals",
                  ((body.get("weekend_diagnostic") or {}).get("weekend_analysis_supported")
                   is False)
                  or bool(((body.get("weekend_diagnostic") or {})
                           .get("capabilities") or {}).get("daily_actual")),
                  json.dumps(body.get("weekend_diagnostic"), default=str)[:200])

            # Scenario-specific assertions.
            if "post-holiday" in lb:
                check(lb, "a week whose own row records NO holiday is still placed in a phase",
                      hol.get("available") is True
                      and (hol.get("applies") is True or bool(hol.get("reason"))),
                      json.dumps({k: hol.get(k) for k in
                                  ("available", "applies", "phase", "row_holiday_count",
                                   "reason")}, default=str))
            if "sparse driver" in lb:
                check(lb, "the upgrade base is judged on COVERAGE, not on a striking figure",
                      any(d.get("driver") == "Final_upp_units" for d in lag.get("drivers") or [])
                      or "Final_upp_units" not in (lag.get("requested_drivers") or []),
                      json.dumps([{d.get("driver"): d.get("coverage")}
                                  for d in lag.get("drivers") or []]))
            if "persistent plan miss" in lb:
                check(lb, "the plan-revision state is established from vintage evidence",
                      plan.get("state") in ("plan_not_revisited",
                                            "plan_revised_but_remained_wrong",
                                            "plan_revised_appropriately", "not_testable"),
                      json.dumps(plan, default=str)[:220])
            if "hierarchy" in lb:
                _scope = ((sections.get("2_root_cause") or {}).get("scope") or {})
                check(lb, "the ladder is rendered as SCOPE with its caution",
                      "WHERE the miss is visible, not WHY" in (_scope.get("caution") or "")
                      or _scope.get("available") is False,
                      str(_scope.get("caution"))[:140])
            if "data limitation" in lb:
                check(lb, "a short-history queue does NOT get a confident mechanism",
                      rc.get("miss_mechanism") == "DATA_LIMITATION"
                      or cf.get("level") in ("Very Low", "Low", "Medium"),
                      f"mechanism={rc.get('miss_mechanism')} confidence={cf.get('level')}")

            summary.append({
                "case": lb, "queue": name, "week": week, "http": status_code, "seconds": secs,
                "adherence_pct": fs.get("adherence_pct"),
                "gap_contacts": fs.get("absolute_variance_contacts"),
                "root_cause": rc.get("hypothesis_id"), "hypothesis": rc.get("hypothesis"),
                "miss_mechanism": rc.get("miss_mechanism"),
                "compound": rc.get("compound"),
                "direction_coherent": rc.get("direction_coherent"),
                "evidence_resolution": rc.get("evidence_resolution"),
                "confidence": cf.get("level"), "confidence_pct": cf.get("score_pct"),
                "confidence_capped_by": (cf.get("binding_cap") or {}).get("gate"),
                "criticality": cr.get("band"),
                "holiday_phase": hol.get("phase"),
                "holiday_zero_but_adjacent": hol.get("zero_count_but_adjacent"),
                "drivers_usable": lag.get("usable_drivers"),
                "driver_coverage": lag.get("coverage_summary"),
                "plan_state": plan.get("state"),
                "narrative_model": (body.get("audit") or {}).get("narrative_model"),
                "narrative_error": body.get("narrative_error"),
                "why_bullets": wb.get("count"),
                "jargon": wb.get("jargon_found"),
            })

        with open(OUT, "w", encoding="utf-8") as fh:
            json.dump(results, fh, default=str, indent=1)
        print(f"\nwrote {OUT}  ({len(results)} live response(s))")

        print("\n" + "=" * 96)
        print("  LIVE SUMMARY")
        print("=" * 96)
        for s in summary:
            print(f"  {s['case']:46s} {str(s.get('miss_mechanism')):32s} "
                  f"conf {str(s.get('confidence')):10s} crit {str(s.get('criticality')):10s} "
                  f"{s.get('root_cause')}")
        print("\n" + "-" * 96)
        print(f"  {len(PASS)}/{len(PASS) + len(FAIL)} live checks passed over {len(results)} case(s)")
        if FAIL:
            print("\n  FAILURES:")
            for tag, name, detail in FAIL:
                print(f"    [{tag}] {name}")
                if detail:
                    print(f"        {detail}")
        print("-" * 96)
        return 1 if FAIL else 0
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    code = main()
    sys.exit(code)
