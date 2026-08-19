# -*- coding: utf-8 -*-
"""Run the multi-holiday / long-weekend test cases and write one markdown report per case.

WHY THESE THREE CASES. Every earlier test used SA Indonesia FW202716, which has adjacent holidays
only, `Holiday_Count = 0`, and volumes near 150. None of that exercises what was built. These three
were selected by SQL against four conditions at once -- 3+ holidays, a long-weekend day flag, BOTH
measures at least 200, and a material miss -- and between them they cover the cases that can go wrong:

  1  China FW202435    7 holidays, all seven days flagged. Mid-Autumn Festival and National Day fall
                       on the SAME DATE and are DIFFERENT holidays -- the case where merging would
                       corrupt the result. Volumes 10,919 / 14,848.
  2  Japan FW202548    5 holidays spanning a fiscal-YEAR boundary (2024-12-29 .. 2025-01-03), all one
                       bank-holiday family that SHOULD group. Sunday and Friday both flagged.
  3  China FW202536    3 holidays on Mon + Sat + Sun -- a genuine long weekend rather than a full
                       shutdown, which is what the weekend contrast needs. Volumes 14,802 / 18,925.

    python results/run_holiday_weekend_tests.py            # deterministic only, no model tokens
    python results/run_holiday_weekend_tests.py --narrate  # also call the model for the prose
"""
from __future__ import annotations

import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "backend"))

from sql_backend import connect, load_config                                   # noqa: E402
from wfm.data_access import fetch_wfm_context                                  # noqa: E402
from wfm import spec_engine                                                    # noqa: E402

NARRATE = "--narrate" in sys.argv
OUT_DIR = os.path.join(HERE, "holiday-weekend-tests")

CASES = [
    ("Social Media China Basic", 202435,
     "Seven holidays, every weekday flagged. Mid-Autumn Festival and National Day share "
     "2023-10-01 and are different holidays -- the case where a naive merge would do damage."),
    ("Social Media Japan Basic", 202548,
     "Five holidays spanning the 2024/2025 boundary, all one bank-holiday family. Sunday and "
     "Friday flagged, so the closure runs off both ends of the week."),
    ("Social Media China Basic", 202536,
     "Three holidays on Monday, Saturday and Sunday -- a genuine long weekend rather than a full "
     "shutdown, which is what the long-weekend contrast is for."),
]


def slug(s):
    return re.sub(r"_+", "_", re.sub(r"[^A-Za-z0-9]+", "_", str(s))).strip("_")


def pct(v, nd=1):
    return "n/a" if not isinstance(v, (int, float)) else ("%+.*f%%" % (nd, v))


def num(v, nd=0):
    return "n/a" if not isinstance(v, (int, float)) else ("{:,.{}f}".format(v, nd))


def run_case(cu, tbl, queue, week, llm_cfg):
    cu.execute("SELECT * FROM " + tbl + " WHERE Forecast_name = ? ORDER BY Fiscal_Week", queue)
    cols = [d[0] for d in cu.description]
    recs = [dict(zip(cols, [str(v) if hasattr(v, "isoformat") else v for v in r]))
            for r in cu.fetchall()]
    target = next((r for r in recs if int(r["Fiscal_Week"]) == week), None)
    if target is None:
        return None, None

    def entry(rec):
        fo, ao = rec.get("fcst_offered"), rec.get("Actual_Offered")
        adh = ((1 - ao / fo) * 100) if (fo and ao is not None) else None
        return {"key": {"Forecast_name": queue, "Fiscal_Week": int(rec["Fiscal_Week"])},
                "fields": rec,
                "computed": {"forecast": fo, "actual": ao,
                             "adherence_pct": round(adh, 2) if adh is not None else None,
                             "direction": None if adh is None else ("under" if adh < 0 else "over")}}

    bundle = {"target": entry(target),
              "history": [entry(r) for r in recs if int(r["Fiscal_Week"]) < week][-13:],
              "rows": [entry(r) for r in recs], "peers": []}
    key = {"Forecast_name": queue, "Fiscal_Week": week,
           "Region": target.get("Region"), "SubRegion": target.get("SubRegion"),
           "Country": target.get("Country"), "channel": target.get("channel"),
           "business_org": target.get("business_org"), "Offering": target.get("Offering")}
    ctx = fetch_wfm_context(cu, tbl, key)
    res = spec_engine.investigate(bundle, llm_cfg, ctx, grain="weekly", interrogate=False)
    return res, target


def holiday_rows(cu, country, week):
    cu.execute("""
        SELECT holiday_name, holiday_date, DATENAME(weekday, holiday_date), holiday_type,
               needs_review
        FROM   dbo.Holiday_Master
        WHERE  country_key = ? AND fiscal_week = ?
        ORDER BY holiday_date, holiday_name
    """, str(country or "").lower(), week)
    return cu.fetchall()


def group_of(cu, name):
    cu.execute("SELECT TOP 1 group_id FROM dbo.Holiday_Name_Alias WHERE LOWER(raw_name) = ?",
               str(name).strip().lower())
    r = cu.fetchone()
    return r[0] if r else None


def report(cu, queue, week, why, res, target):
    fs = res.get("forecast_summary") or {}
    hol = res.get("holiday_response") or {}
    wk = res.get("weekend_diagnostic") or {}
    hw = wk.get("holiday_weekend_interaction") or {}
    wd = wk.get("weekday_outcomes") or {}
    c3 = wk.get("clause_c_states") or {}
    conf = res.get("confidence") or {}
    crit = res.get("criticality") or {}
    mech = res.get("miss_mechanism") or {}
    rc = res.get("root_cause") or {}
    card = res.get("decision_card") or {}
    sec = card.get("sections") or {}
    iw = hol.get("holidays_in_target_week") or {}
    ad = hol.get("recent_holidays_affecting_target_week") or {}

    L = []
    a = L.append
    a("# %s — FW%s — %s" % (queue, week, target.get("channel")))
    a("")
    a("*%s*" % why)
    a("")
    a("| | |")
    a("|---|---|")
    a("| Scope | %s / %s / %s · %s · %s |" % (target.get("Region"), target.get("SubRegion"),
                                              target.get("Country"), target.get("Offering"),
                                              target.get("channel")))
    a("| Actual offered | **%s** |" % num(fs.get("actual")))
    a("| Forecast offered | **%s** |" % num(fs.get("forecast"), 1))
    a("| Forecast adherence | **%s** (%s) |" % (pct(fs.get("adherence_pct")), fs.get("direction")))
    a("| Absolute variance | %s contacts |" % num(fs.get("absolute_variance_contacts")))
    a("| `Holiday_Count` on the row | %s |" % target.get("Holiday_Count"))
    a("| History available | %s weeks |" % (res.get("weeks_available")
                                           or (res.get("forecast_response_diagnostic")
                                               or {}).get("weeks_available")))
    a("| Confidence · Criticality | %s %s%% · %s |" % (conf.get("level"), conf.get("score_pct"),
                                                       crit.get("band")))
    a("| Mechanism | %s |" % mech.get("primary"))
    a("| Engine status | %s |" % res.get("status"))
    a("")

    # ---- what the master holds, and what the group table did to it -----------------------------
    a("## 1. The holidays, raw and grouped")
    a("")
    rows = holiday_rows(cu, target.get("Country"), week)
    if rows:
        a("`Holiday_Master` rows for %s FW%s — **%d raw name(s)**:" % (
            target.get("Country"), week, len(rows)))
        a("")
        a("| Raw name | Date | Weekday | Type | Semantic group | Review |")
        a("|---|---|---|---|---|---|")
        for r in rows:
            a("| %s | %s | %s | %s | `%s` | %s |" % (
                r[0], str(r[1])[:10], r[2], r[3], group_of(cu, r[0]) or "(derived)",
                "**YES**" if r[4] else ""))
        a("")
    a("**What the card displays** (prompt2 clauses E and F):")
    a("")
    a("> %s" % (iw.get("statement") or "(no in-week statement)"))
    a(">")
    a("> %s" % (ad.get("statement") or "(no adjacent statement)"))
    a("")
    a("| | Raw names reaching the week | Canonical names displayed |")
    a("|---|---|---|")
    a("| Count | %d | %d |" % (len(hol.get("names") or []),
                               len(iw.get("canonical_names") or []) +
                               len(ad.get("canonical_names") or [])))
    a("| Names | %s | %s |" % (", ".join(hol.get("names") or []) or "—",
                               ", ".join((iw.get("canonical_names") or []) +
                                         (ad.get("canonical_names") or [])) or "—"))
    a("")
    for label, blk in (("In this fiscal week", iw), ("Outside it, window reaches it", ad)):
        grps = blk.get("by_semantic_group") or []
        if grps:
            a("**%s** — %d group(s):" % (label, len(grps)))
            a("")
            a("| Display name | Occurrences | Dates | Weekdays | Raw spellings |")
            a("|---|---|---|---|---|")
            for g in grps:
                a("| %s | %s | %s | %s | %s |" % (
                    g.get("display_name"), g.get("occurrences"),
                    ", ".join(g.get("dates") or []), ", ".join(g.get("weekdays") or []),
                    " / ".join(g.get("raw_names") or [])))
            a("")

    # ---- weekend / weekday --------------------------------------------------------------------
    a("## 2. Weekend and weekday structure")
    a("")
    a("Clause C — three separate questions, not one refusal:")
    a("")
    a("| Question | State | Why |")
    a("|---|---|---|")
    for k, lab in (("daily_weekend_demand_effect", "Daily weekend demand effect"),
                   ("weekly_calendar_structure", "Weekly calendar structure"),
                   ("holiday_weekend_interaction", "Holiday × weekend interaction")):
        b = c3.get(k) or {}
        a("| %s | `%s` | %s |" % (lab, b.get("state"), (b.get("reason") or "")[:130]))
    a("")
    if wd.get("testable"):
        ref = wd.get("reference") or {}
        a("Clause K — weekly outcome by the weekday a holiday fell on. Reference: **%s** weeks with "
          "no holiday day flagged, median **%s** contacts." % (
              ref.get("weeks_with_no_holiday_day"), num(ref.get("median_actual"))))
        a("")
        a("| Holiday fell on | Weeks | Median actual | vs no-holiday week |")
        a("|---|---|---|---|")
        for d, v in (wd.get("weekdays") or {}).items():
            if v.get("measurable"):
                a("| %s | %s | %s | **%s** |" % (d, v.get("weeks"), num(v.get("median_actual")),
                                                 pct(v.get("effect_vs_no_holiday_week_pct"))))
            else:
                a("| %s | %s | — | not measurable — %s |" % (d, v.get("weeks"),
                                                             (v.get("reason") or "")[:60]))
        a("")
        a("Spread across weekdays: **%s points**." % wd.get("spread_across_weekdays_pts"))
        a("")
    if hw.get("testable"):
        a("Long-weekend grouping — this week's pattern is **%s**%s:" % (
            hw.get("target_pattern"),
            " (long weekend)" if hw.get("long_weekend_flag") else ""))
        a("")
        a("| Holiday day pattern | Weeks | Median actual | vs no-holiday week |")
        a("|---|---|---|---|")
        for p, g in sorted((hw.get("patterns") or {}).items()):
            if g.get("measurable"):
                a("| %s | %s | %s | **%s** |" % (p.replace("_", " "), g.get("instances"),
                                                 num(g.get("median_actual")),
                                                 pct(g.get("effect_vs_no_holiday_week_pct"))))
            else:
                a("| %s | %s | — | %s |" % (p.replace("_", " "), g.get("instances"),
                                            (g.get("reason") or "")[:60]))
        a("")
        ct = hw.get("long_weekend_contrast") or {}
        if ct.get("reading"):
            a("> %s" % ct.get("reading"))
            a("")

    # ---- phase, rebound, repeatability ---------------------------------------------------------
    a("## 3. Calendar phase and rebound")
    a("")
    a("| | |")
    a("|---|---|")
    a("| Resolved phase | `%s` |" % hol.get("phase"))
    a("| Window checked | ±%s weeks |" % hol.get("span_weeks"))
    a("| Zero-count but adjacent | %s |" % hol.get("zero_count_but_adjacent"))
    pe = hol.get("phase_effect") or {}
    if pe.get("testable"):
        a("| Phase effect vs own baseline | %s across %s instances |" % (
            pct(pe.get("actual_effect_pct")), pe.get("instances")))
    tr = (hol.get("phase_transition") or {}).get("target_transition") or {}
    if tr.get("reading"):
        a("| Week-on-week transition | %s |" % tr.get("reading"))
    rp = hol.get("rebound_repeatability") or {}
    if rp.get("band"):
        a("| Rebound repeatability | **%s** (%s instances) |" % (rp.get("band"), rp.get("instances")))
    a("")
    if rp.get("reading"):
        a("> %s" % rp.get("reading"))
        a("")

    # ---- conclusion ----------------------------------------------------------------------------
    a("## 4. What the engine concluded")
    a("")
    a("**Root cause:** %s" % (rc.get("hypothesis") or "—"))
    a("")
    a("%s" % (rc.get("statement") or "—"))
    a("")
    why_b = sec.get("12_why_this_happened") or {}
    if why_b.get("bullets"):
        a("Ranked reasons:")
        a("")
        for b in why_b["bullets"]:
            a("%d. %s" % (b.get("rank"), b.get("text")))
        a("")
        a("Jargon found: `%s` · causal verbs found: `%s`" % (
            why_b.get("jargon_found"), why_b.get("causal_verbs_found")))
        a("")
    recs_ = res.get("recommendations") or []
    if recs_:
        a("Recommendations:")
        a("")
        for r_ in recs_:
            a("- %s" % (r_.get("action") if isinstance(r_, dict) else r_))
        a("")
    a("---")
    a("")
    a("*Generated by `results/run_holiday_weekend_tests.py` on branch `test3`. "
      "Semantic groups from `dbo.Holiday_Name_Alias`. "
      "%s*" % ("Narrative written by a model." if NARRATE else
               "Deterministic evidence only — no model was called."))
    return "\n".join(L)


def main():
    cfg = load_config()
    tbl = cfg["sql"]["table"]
    llm_cfg = cfg.get("llm", {}) if NARRATE else {}
    if not os.path.isdir(OUT_DIR):
        os.makedirs(OUT_DIR)
    cn = connect(cfg)
    cu = cn.cursor()

    print("=" * 100)
    print("MULTI-HOLIDAY / LONG-WEEKEND TESTS   (%s)" % (
        "with narrative" if NARRATE else "deterministic, 0 model tokens"))
    print("=" * 100)

    written = []
    for i, (queue, week, why) in enumerate(CASES, start=1):
        res, target = run_case(cu, tbl, queue, week, llm_cfg)
        if res is None:
            print("\n  %d. %s FW%s -- NOT FOUND, skipped" % (i, queue, week))
            continue
        md = report(cu, queue, week, why, res, target)
        name = "%d_%s_%s_%s.md" % (i, week, slug(queue), slug(target.get("channel")))
        path = os.path.join(OUT_DIR, name)
        io.open(path, "w", encoding="utf-8").write(md)
        written.append(name)

        fs = res.get("forecast_summary") or {}
        hol = res.get("holiday_response") or {}
        wk = res.get("weekend_diagnostic") or {}
        wd = wk.get("weekday_outcomes") or {}
        iw = hol.get("holidays_in_target_week") or {}
        ad = hol.get("recent_holidays_affecting_target_week") or {}
        print("\n  %d. %s FW%s (%s)" % (i, queue, week, target.get("channel")))
        print("       actual %s / forecast %s  adherence %s  hol_count=%s" % (
            num(fs.get("actual")), num(fs.get("forecast"), 1), pct(fs.get("adherence_pct")),
            target.get("Holiday_Count")))
        print("       raw names reaching week: %d -> displayed canonical: %d" % (
            len(hol.get("names") or []),
            len(iw.get("canonical_names") or []) + len(ad.get("canonical_names") or [])))
        print("       in-week=%s  adjacent=%s  phase=%s" % (
            iw.get("count"), ad.get("count"), hol.get("phase")))
        print("       weekdays measurable=%s  spread=%s pts" % (
            len(wd.get("measurable_weekdays") or []), wd.get("spread_across_weekdays_pts")))
        print("       confidence=%s %s%%  criticality=%s  mechanism=%s" % (
            (res.get("confidence") or {}).get("level"),
            (res.get("confidence") or {}).get("score_pct"),
            (res.get("criticality") or {}).get("band"),
            (res.get("miss_mechanism") or {}).get("primary")))
        print("       -> %s" % name)
        io.open(os.path.join(OUT_DIR, name.replace(".md", ".json")), "w",
                encoding="utf-8").write(json.dumps(res, indent=1, default=str))

    cn.close()
    print("\n  %d report(s) in results/holiday-weekend-tests/" % len(written))


if __name__ == "__main__":
    main()
