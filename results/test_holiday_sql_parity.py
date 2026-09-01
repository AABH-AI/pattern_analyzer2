# -*- coding: utf-8 -*-
"""Does the SQL-built holiday structure match the JSON extract, exactly?

    cd backend && python ../results/test_holiday_sql_parity.py

THE POINT
---------
`holiday_calendar.use_sql(cursor)` swaps the source of holiday knowledge. If the two sources
disagree, holiday reasoning changes silently -- the worst possible failure, because every
figure still looks plausible. This test compares the two structures key by key and field by
field, and it compares the ACTUAL PUBLIC OUTPUT (`holiday_context`) on real queue-weeks, not
just the raw dicts.

It fails loudly on any difference. A difference is not automatically a bug in the SQL path --
it may be a data gap to publish -- but it must never pass unnoticed.

Requires live SQL. Without it the test reports BLOCKED and changes nothing.
"""
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "backend"))

PASS, FAIL, WARN = [], [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("  %-4s %s%s" % ("PASS" if cond else "FAIL", name,
                           ("\n         " + detail) if detail and not cond else ""))


def warn(name, detail=""):
    WARN.append(name)
    print("  WARN %s%s" % (name, ("\n         " + detail) if detail else ""))


def rule(c="="):
    print(c * 94)


def main():
    from sql_backend import connect, load_config
    from wfm.context_repository import holiday_calendar as cal
    from wfm.context_repository import holiday_sql

    cfg = load_config()
    table = (cfg.get("sql") or {}).get("table")
    try:
        conn = connect(cfg)
        cur = conn.cursor()
    except Exception as exc:
        print("LIVE SQL UNREACHABLE: %s: %s" % (type(exc).__name__, exc))
        print("BLOCKED -- nothing asserted, nothing fabricated.")
        return 2

    rule()
    print("HOLIDAY SOURCE PARITY -- SQL vs the JSON extract")
    rule()

    # ---- the JSON side, read directly so the test does not depend on cache state ---------
    jpath = os.path.join(ROOT, "backend", "wfm", "context_repository", "holiday_master.json")
    if not os.path.exists(jpath):
        print("no JSON extract present -- nothing to compare against. BLOCKED.")
        return 2
    js = json.loads(io.open(jpath, encoding="utf-8").read())
    sq = holiday_sql.build(cur)

    print("  JSON : %s country-weeks, %s active rows"
          % (format(js.get("country_weeks") or 0, ","), format(js.get("active_rows") or 0, ",")))
    print("  SQL  : %s country-weeks, %s rows"
          % (format(sq.get("country_weeks") or 0, ","), format(sq.get("active_rows") or 0, ",")))
    print()

    rule("-")
    print("  TOP-LEVEL STRUCTURE")
    rule("-")
    for key in ("holidays", "aggregate_groups", "semantic_groups", "fiscal_calendar"):
        check("both carry '%s'" % key, key in js and key in sq)
    check("same number of country-weeks",
          len(js["holidays"]) == len(sq["holidays"]),
          "json %d vs sql %d" % (len(js["holidays"]), len(sq["holidays"])))
    check("same number of semantic groups",
          len(js["semantic_groups"]) == len(sq["semantic_groups"]),
          "json %d vs sql %d" % (len(js["semantic_groups"]), len(sq["semantic_groups"])))
    check("same number of fiscal-calendar weeks",
          len(js["fiscal_calendar"]) == len(sq["fiscal_calendar"]),
          "json %d vs sql %d" % (len(js["fiscal_calendar"]), len(sq["fiscal_calendar"])))

    rule("-")
    print("  KEY SETS")
    rule("-")
    jk, sk = set(js["holidays"]), set(sq["holidays"])
    only_json, only_sql = sorted(jk - sk), sorted(sk - jk)
    check("no country-week only in JSON", not only_json,
          "%d missing from SQL, e.g. %s" % (len(only_json), only_json[:5]))
    check("no country-week only in SQL", not only_sql,
          "%d extra in SQL, e.g. %s" % (len(only_sql), only_sql[:5]))

    rule("-")
    print("  EVERY HOLIDAY, FIELD BY FIELD")
    rule("-")
    fields = ("name", "type", "date", "before", "after", "group",
              "semantic_family", "needs_review")
    diffs, compared, missing_family = [], 0, []
    for key in sorted(jk & sk):
        a = sorted(js["holidays"][key], key=lambda h: (str(h.get("date")), h.get("name") or ""))
        b = sorted(sq["holidays"][key], key=lambda h: (str(h.get("date")), h.get("name") or ""))
        if len(a) != len(b):
            diffs.append("%s: %d holidays in JSON, %d in SQL" % (key, len(a), len(b)))
            continue
        for ha, hb in zip(a, b):
            compared += 1
            for f in fields:
                va, vb = ha.get(f), hb.get(f)
                if va == vb:
                    continue
                if f == "semantic_family" and va is not None and vb is None:
                    missing_family.append("%s | %s -> %s" % (key, ha.get("name"), va))
                    continue
                diffs.append("%s | %s | %s: json=%r sql=%r"
                             % (key, ha.get("name"), f, va, vb))
    print("  compared %s holiday rows across %s country-weeks"
          % (format(compared, ","), format(len(jk & sk), ",")))
    check("no field differences", not diffs,
          "%d difference(s); first 6:\n         %s"
          % (len(diffs), "\n         ".join(diffs[:6])))

    if missing_family:
        warn("semantic_family absent in SQL for %d holiday row(s)" % len(missing_family),
             "the alias table has no row for these. Publish them to close the gap.\n"
             "         first 5:\n         %s" % "\n         ".join(missing_family[:5]))
    else:
        check("semantic_family reproduced for every holiday", True)

    if sq.get("_parity_gaps"):
        warn("holiday_sql reported its own parity gaps",
             json.dumps(sq["_parity_gaps"]["semantic_family_unresolved"])[:300])

    rule("-")
    print("  AGGREGATE GROUPS AND SEMANTIC GROUP NAMES")
    rule("-")
    check("aggregate_groups identical",
          {k: sorted(v) for k, v in js["aggregate_groups"].items()}
          == {k: sorted(v) for k, v in sq["aggregate_groups"].items()},
          "json=%s\n         sql =%s" % (sorted(js["aggregate_groups"]),
                                         sorted(sq["aggregate_groups"])))
    check("semantic group display names identical",
          js["semantic_groups"] == sq["semantic_groups"],
          "differing ids: %s" % sorted(
              set(js["semantic_groups"].items()) ^ set(sq["semantic_groups"].items()))[:6])
    check("fiscal_calendar identical",
          js["fiscal_calendar"] == sq["fiscal_calendar"],
          "%d weeks differ" % len({k for k in set(js["fiscal_calendar"]) | set(sq["fiscal_calendar"])
                                   if js["fiscal_calendar"].get(k) != sq["fiscal_calendar"].get(k)}))

    # ---- the part that actually matters: identical PUBLIC output on real queue-weeks -----
    rule("-")
    print("  PUBLIC OUTPUT -- holiday_context() on real queue-weeks, both sources")
    rule("-")
    cur.execute("SELECT DISTINCT TOP 40 Country, Fiscal_Week FROM %s "
                " WHERE Country IS NOT NULL AND Country <> '' "
                " ORDER BY Fiscal_Week DESC" % table)
    cases = [(r[0], int(r[1])) for r in cur.fetchall()]

    cal.refresh()
    cal._SQL_CURSOR = None                       # force the JSON path
    json_out = {}
    for country, week in cases:
        json_out[(country, week)] = cal.holiday_context(country, week)
    src_json = cal.configured_source()

    cal.use_sql(cur)                             # force the SQL path
    sql_out = {}
    for country, week in cases:
        sql_out[(country, week)] = cal.holiday_context(country, week)
    src_sql = cal.configured_source()

    check("JSON path reported served_from='json'", src_json == "json", "got %r" % src_json)
    check("SQL path reported served_from='sql'", src_sql == "sql", "got %r" % src_sql)

    mismatched = [k for k in json_out if json_out[k] != sql_out[k]]
    print("  compared holiday_context() on %d real (country, week) pairs" % len(cases))
    check("holiday_context identical from both sources", not mismatched,
          "%d differ, e.g. %s" % (len(mismatched), mismatched[:4]))
    if mismatched:
        k = mismatched[0]
        print("         JSON: %s" % json.dumps(json_out[k], default=str)[:280])
        print("         SQL : %s" % json.dumps(sql_out[k], default=str)[:280])

    with_holiday = [k for k in json_out if (json_out[k] or {}).get("applies")]
    check("the sample actually exercised holidays (%d of %d applied)"
          % (len(with_holiday), len(cases)), len(with_holiday) > 0,
          "no case in the sample had a holiday -- the comparison proved little")

    # ---- the weekly-refresh question ------------------------------------------------------
    rule("-")
    print("  WATERMARK -- nothing needs configuring when a new week lands")
    rule("-")
    wm = holiday_sql.watermark(cur, table)
    for k, v in wm.items():
        print("    %-32s %s" % (k, v))
    check("holiday calendar covers the newest data week",
          bool(wm.get("holiday_calendar_ahead_of_data")),
          "data reaches %s but the calendar stops at %s"
          % (wm.get("max_fiscal_week"), wm.get("holiday_calendar_covers_to")))

    cal.refresh()
    cal._SQL_CURSOR = None                       # leave the module as we found it

    print()
    rule()
    print("  %d passed, %d failed, %d warning(s)" % (len(PASS), len(FAIL), len(WARN)))
    rule()
    if FAIL:
        print("  FAILURES:")
        for f in FAIL:
            print("    - %s" % f)
    if WARN:
        print("  WARNINGS (not failures -- data gaps to publish):")
        for w in WARN:
            print("    - %s" % w)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
