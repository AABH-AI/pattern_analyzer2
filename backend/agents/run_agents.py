# -*- coding: utf-8 -*-
"""Run the multi-agent RCA on a real queue-week, end to end.

    cd backend
    python -m agents.run_agents                          # picks the largest recent miss
    python -m agents.run_agents --queue "Social Media English Basic" --week 202637
    python -m agents.run_agents --challenger qwen/qwen3.6-27b   # cross-family dissent test

WHAT IT DOES
------------
1. Reads the real row and its history from SQL.
2. Computes the deterministic evidence with the EXISTING engine -- every figure, unchanged.
3. Extracts a SCOPED slice of that evidence, not the whole finding object.
4. Runs Analyst -> Challenger -> Editor -> Judge on Groq.
5. Prints the report, the verdict, and what it cost.

The scoping in step 3 is the whole point. The engine's narrative call was measured at 86,424
tokens because it was handed the entire 292,308-character finding. This hands each agent a few
thousand characters of the fields that matter.
"""
import argparse
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents import graph, models as M          # noqa: E402


def rule(c="="):
    print(c * 92)


def num(v):
    """A figure as a person would write it, for the allowed-numbers set."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return int(round(f)) if abs(f - round(f)) < 0.01 else round(f, 1)


def scope_evidence(finding, cursor=None, fact_table=None, queue=None, fiscal_week=None):
    """The slice the agents may see, and the set of numbers they may write.

    `cursor` is optional. Given one, this adds the same holiday's occurrences in previous years
    and what this queue actually did in those weeks -- the comparison that turns "there is a
    holiday this week" into something a planner can act on.

    Deliberately narrow. Everything here is already computed; nothing is recalculated. The
    ~40 keys of the finding object become the handful that bear on "why did this week miss".
    """
    fs = finding.get("forecast_summary") or {}
    crit = finding.get("criticality") or {}
    hol = finding.get("holiday_response") or {}
    conf = finding.get("confidence") or {}
    rc = finding.get("root_cause") or {}
    dq = finding.get("data_quality") or {}
    stat = finding.get("statistical_evidence") or {}
    mech = finding.get("miss_mechanism") or {}
    streak = finding.get("miss_streak") or {}

    ev = {
        "forecast": num(fs.get("forecast")),
        "actual": num(fs.get("actual")),
        "gap_contacts": num(fs.get("absolute_variance_contacts")),
        "adherence_pct": num(fs.get("adherence_pct")),
        "direction": fs.get("direction"),
        "criticality_band": crit.get("band"),
        "typical_week_actual": num(crit.get("typical_week_actual")),
        "same_direction_weeks": crit.get("streak_weeks") or streak.get("length"),
        "data_quality_clean": dq.get("clean"),
        "data_quality_issues": (dq.get("issues") or [])[:3],
        "holiday_phase": hol.get("phase"),
        "holidays_in_week": ((hol.get("holidays_in_target_week") or {})
                             .get("canonical_names") or [])[:4],
        "holiday_measurable": (hol.get("forecast_capture") or {}).get("classification"),
        "holiday_not_measurable_reason": (hol.get("forecast_capture") or {}).get("reason"),
        "confidence_band": conf.get("band"),
        "confidence_pct": num(conf.get("score_pct")),
        "deterministic_root_cause": rc.get("hypothesis") or rc.get("cause_type"),
        "miss_mechanism": mech.get("primary"),
    }
    # a few statistical facts, if the engine produced them
    for k in ("plan_vs_seasonal_norm", "bias", "volatility", "trend", "momentum",
              "seasonal_index", "outlier"):
        v = stat.get(k)
        if isinstance(v, dict):
            ev["stat_" + k] = {kk: num(vv) if isinstance(vv, (int, float)) else vv
                               for kk, vv in list(v.items())[:4]}

    # --- the rest of what the approved card reasons over -------------------------------------
    # Without these the agents could only ever talk about the size of the miss and the calendar.
    # test3's decision card covers drivers, peers and channel movement, so the agents must see
    # them too or the comparison is not like for like.
    dg = finding.get("driver_gate") or {}
    if dg.get("results"):
        ev["drivers"] = [{
            "driver": d.get("driver"),
            "verdict": d.get("verdict"),
            "relevant": d.get("relevant"),
            "reason": (d.get("reason") or "")[:160],
            "correlation": num(d.get("correlation")),
            "weeks_compared": d.get("n"),
            "lag_weeks": d.get("lag_weeks"),
        } for d in (dg.get("results") or [])[:4]]
        ev["driver_offering"] = dg.get("offering")

    asu = finding.get("asu_decomposition") or {}
    if asu:
        ev["asu_split"] = {k: num(v) if isinstance(v, (int, float)) else v
                           for k, v in list(asu.items())[:6]}

    fg = finding.get("forecastability_gate") or {}
    if fg:
        ev["was_it_knowable_at_plan_time"] = {
            "supports_forecast_response_failure": fg.get("supports_forecast_response_failure"),
            "conditions": [{"condition": c.get("condition"), "met": c.get("met"),
                            "measured": str(c.get("measured"))[:90]}
                           for c in (fg.get("conditions") or [])[:4]],
        }

    cm = finding.get("channel_migration") or {}
    if cm:
        ev["channel_migration"] = {k: num(v) if isinstance(v, (int, float)) else
                                   (str(v)[:120] if isinstance(v, str) else v)
                                   for k, v in list(cm.items())[:6]}

    # CQN peers -- the same-week comparison the card makes. If comparable queues missed the same
    # way, this is not a queue problem, and an agent that cannot see that will say it is.
    ctx = finding.get("wfm_context") or {}
    sib = ctx.get("channel_sibling_rows") or []
    if sib:
        ev["cqn_peers_same_week"] = {"count": len(sib), "cqn_names": ctx.get("cqn_names")}

    # --- the same holiday in previous years -------------------------------------------------
    # "Columbus Day is in this week" is nearly useless alone. The planner's question is: when
    # did it fall last year, and what did demand do? A holiday drifts across fiscal weeks --
    # Columbus Day was week 37 in three years and week 36 in another -- so the naive
    # "same fiscal week last year" comparison silently compares a holiday week to a normal one.
    names = ((hol.get("holidays_in_target_week") or {}).get("canonical_names") or [])
    countries = hol.get("country_resolved") or []
    if cursor is not None and names and countries and fiscal_week:
        try:
            from wfm.context_repository import holiday_sql as hs
            prior = hs.same_holiday_prior_years(cursor, countries, names, fiscal_week,
                                                years=4, fact_table=fact_table)
            if prior:
                weeks = [p["fiscal_week"] for p in prior]
                qh = hs.queue_history_for_weeks(cursor, fact_table, queue, weeks) if queue else {}
                same_holiday = []
                for p in prior[:4]:
                    row = {"years_ago": p["years_ago"],
                           "fiscal_week": p["fiscal_week"],
                           "week_number": p["fiscal_week_number"],
                           "date": p["holiday_date"],
                           "landed_in_the_same_week_number": p["same_fiscal_week_as_now"]}
                    h = qh.get(p["fiscal_week"])
                    if h:
                        row["this_queue_forecast"] = h["forecast"]
                        row["this_queue_actual"] = h["actual"]
                        row["this_queue_adherence_pct"] = h["adherence_pct"]
                    same_holiday.append(row)
                ev["same_holiday_previous_years"] = same_holiday
                past = [r["this_queue_adherence_pct"] for r in same_holiday
                        if r.get("this_queue_adherence_pct") is not None]
                if past:
                    ev["holiday_weeks_typical_adherence_pct"] = round(
                        sum(past) / len(past), 1)
                    ev["holiday_weeks_measured"] = len(past)
                drifted = [r["fiscal_week"] for r in same_holiday
                           if not r["landed_in_the_same_week_number"]]
                if drifted:
                    ev["holiday_drifted_weeks"] = drifted
        except Exception as exc:
            ev["same_holiday_previous_years_error"] = str(exc)[:120]

    ev = {k: v for k, v in ev.items() if v not in (None, "", [], {})}

    figures = set()
    def harvest(o):
        if isinstance(o, (int, float)) and not isinstance(o, bool):
            figures.add(str(num(o)))
        elif isinstance(o, dict):
            for x in o.values():
                harvest(x)
        elif isinstance(o, list):
            for x in o:
                harvest(x)
    harvest(ev)
    return ev, figures


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue")
    ap.add_argument("--week", type=int)
    ap.add_argument("--challenger", help="override the challenger's model")
    ap.add_argument("--analyst", help="override the analyst's model")
    ap.add_argument("--save", default="../results/agents-run.json")
    args = ap.parse_args()

    from sql_backend import connect, load_config
    from wfm import investigate_spec, fetch_wfm_context
    from wfm.common import adherence_pct

    cfg = load_config()
    table = cfg["sql"]["table"]
    llm = cfg.get("llm") or {}
    api_key = next(((llm.get(s) or {}).get("api_key") for s in ("primary", "secondary")
                    if (llm.get(s) or {}).get("provider") == "groq"
                    and (llm.get(s) or {}).get("api_key")), None)
    if not api_key:
        print("No Groq key in config.json. Add one to llm.primary or llm.secondary.")
        return 2

    problems = M.audit_config(cfg)
    if problems:
        print("CONFIG PROBLEMS:")
        for p in problems:
            print("   %s" % p)
        print()

    conn = connect(cfg)
    cur = conn.cursor()

    queue, week = args.queue, args.week
    if not (queue and week):
        cur.execute(
            "SELECT TOP 1 Forecast_name, Fiscal_Week FROM %s "
            " WHERE Fiscal_Week BETWEEN 202530 AND 202748 AND fcst_offered > 3000 "
            "   AND Country IS NOT NULL AND Country <> '' "
            "   AND ABS(1 - Actual_Offered / fcst_offered) > 0.25 "
            " ORDER BY ABS(Actual_Offered - fcst_offered) DESC" % table)
        row = cur.fetchone()
        if not row:
            print("no case found")
            return 2
        queue, week = row[0], int(row[1])

    cur.execute("SELECT * FROM %s WHERE Forecast_name = ? AND Fiscal_Week = ?" % table,
                (queue, week))
    r = cur.fetchone()
    if not r:
        print("not found: %s FW%s" % (queue, week))
        return 2
    f = dict(zip([d[0] for d in cur.description], r))
    a, fc = f.get("Actual_Offered"), f.get("fcst_offered")

    rule()
    print("MULTI-AGENT RCA")
    rule()
    print("  queue   : %s" % queue)
    print("  week    : FW%s   %s / %s" % (week, f.get("Country"), f.get("channel")))
    print("  forecast: %s      actual: %s" % (format(round(fc), ","), format(round(a), ",")))
    print("  gap     : %s contacts   adherence %+.1f%%"
          % (format(round(abs(a - fc)), ","), adherence_pct(a, fc)))
    print()
    for role in ("analyst", "challenger", "editor", "judge"):
        s = M.role(role)
        ov = {"analyst": args.analyst, "challenger": args.challenger}.get(role)
        print("  %-11s %s%s" % (role, ov or s["model"], "  (override)" if ov else ""))
    print()

    # ---- deterministic evidence, from the existing engine ---------------------------------
    print("  computing deterministic evidence (existing engine, no agents involved)...")
    bundle = {"target": {
        "key": {k: f.get(k) for k in ("Forecast_name", "Fiscal_Week", "Region", "SubRegion",
                                      "Country", "channel", "business_org", "Offering")},
        "fields": f,
        "computed": {"actual": a, "forecast": fc, "adherence_pct": adherence_pct(a, fc)}}}
    wfm_ctx = fetch_wfm_context(cur, table, bundle["target"]["key"])
    finding = investigate_spec(bundle, {}, wfm_ctx, grain="weekly", interrogate=False)

    ev, figures = scope_evidence(finding, cursor=cur, fact_table=table,
                                 queue=queue, fiscal_week=week)
    whole = len(json.dumps(finding, default=str))
    scoped = len(json.dumps(ev, default=str))
    print("     whole finding : %s chars  (~%s tokens)"
          % (format(whole, ","), format(whole // 4, ",")))
    print("     scoped slice  : %s chars  (~%s tokens)   %.1f%% of it"
          % (format(scoped, ","), format(scoped // 4, ","), 100.0 * scoped / whole))
    print("     %d fields, %d permitted figures" % (len(ev), len(figures)))
    print()

    headline = ("%s, FW%s: %s contacts %s plan (%s planned, %s handled), adherence %+.1f%%."
                % (queue, week, format(round(abs(a - fc)), ","),
                   "over" if a > fc else "under", format(round(fc), ","),
                   format(round(a), ","), adherence_pct(a, fc)))

    overrides = {}
    if args.analyst:
        overrides["analyst"] = {"model": args.analyst}
    if args.challenger:
        overrides["challenger"] = {"model": args.challenger}

    print("  running agents...")
    state = graph.run(queue, week, ev, figures, headline, api_key, overrides=overrides)

    # ---- output ---------------------------------------------------------------------------
    print()
    rule("-")
    print("  ANALYST")
    rule("-")
    if state.analyst:
        print("    claim      : %s" % state.analyst.get("claim"))
        print("    mechanism  : %s" % state.analyst.get("mechanism"))
        print("    confidence : %s" % state.analyst.get("confidence"))
    else:
        print("    (nothing produced)")

    print()
    rule("-")
    print("  CHALLENGER")
    rule("-")
    if state.challenger:
        d = state.challenger.get("dissents")
        print("    dissents   : %s" % d)
        if d:
            print("    objection  : %s" % state.challenger.get("objection"))
            print("    cited      : %s" % str(state.challenger.get("evidence_cited"))[:150])
            if state.challenger.get("alternative_mechanism"):
                print("    alternative: %s" % state.challenger["alternative_mechanism"])
        print("    weakest    : %s" % state.challenger.get("weakest_link"))
    else:
        print("    (nothing produced)")

    print()
    rule("-")
    print("  THE REPORT")
    rule("-")
    if state.report:
        for k in ("what_happened", "why", "how_sure", "do_this", "not_assessed"):
            print("    %-15s %s" % (k.replace("_", " ").upper(), state.report.get(k)))
        print()
        print("    words: %s / %s" % (state.report.get("_word_count"), 200))
    else:
        print("    (nothing produced)")

    print()
    rule("-")
    print("  JUDGE")
    rule("-")
    if state.verdict:
        for fac in state.verdict.get("factors") or []:
            mark = "PASS" if fac.get("verdict") == "pass" else "FAIL"
            sev = fac.get("severity") or ""
            print("    %-4s %-36s %s" % (mark, fac.get("factor"),
                                          ("[%s]" % sev) if sev not in ("", "none") else ""))
            if fac.get("verdict") == "fail":
                print("         %s" % (fac.get("note") or ""))
        if state.verdict.get("not_assessed"):
            print("    not assessed: %s" % state.verdict["not_assessed"])
        if state.verdict.get("voided_for_no_evidence"):
            print("    voided (no citation): %s" % state.verdict["voided_for_no_evidence"])
        print("    overall: %s" % state.verdict.get("overall"))
    else:
        print("    (nothing produced)")

    ok, why = graph.publishable(state)
    print()
    rule()
    s = state.summary()
    print("  publishable : %s -- %s" % (ok, why))
    print("  calls       : %d  (%d failed)" % (s["calls"], s["failed_calls"]))
    print("  tokens      : %s" % format(s["total_tokens"], ","))
    print("  seconds     : %s" % state.timings.get("total"))
    print("  revisions   : %d" % s["revisions"])
    print("  dissented   : %s" % s["challenger_dissented"])
    if s["gate_failures"]:
        print("  gate failures:")
        for g in s["gate_failures"]:
            print("     %s" % g)
    if s["errors"]:
        print("  errors:")
        for e in s["errors"]:
            print("     %s" % e)
    print()
    print("  per call:")
    for c in state.calls:
        print("     %-11s %-24s %5.2fs  %5s tok  %s"
              % (c["role"], c["model"], c["seconds"], c.get("total_tokens") or "-",
                 "ok" if c["ok"] else ("FAILED: %s" % str(c.get("error"))[:60])))
    rule()

    out = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", args.save))
    payload = {"queue": queue, "fiscal_week": week, "headline": headline,
               "scoped_evidence": ev, "permitted_figures": sorted(figures),
               "analyst": state.analyst, "challenger": state.challenger,
               "report": state.report, "verdict": state.verdict,
               "summary": s, "calls": state.calls,
               "context_comparison": {"whole_finding_chars": whole,
                                      "scoped_chars": scoped,
                                      "scoped_share_pct": round(100.0 * scoped / whole, 2)}}
    try:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        io.open(out, "w", encoding="utf-8").write(
            json.dumps(payload, indent=2, default=str, ensure_ascii=False))
        print("  saved -> %s" % out)
    except Exception as exc:
        print("  could not save: %s" % exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
