# -*- coding: utf-8 -*-
"""Publish the holiday calendar to SQL so it can be joined and queried like any other table.

    python load_holiday_to_sql.py            load / reload
    python load_holiday_to_sql.py --check    row counts and a sample join, no writes
    python load_holiday_to_sql.py --dry-run  print what would be written

WHY SQL AS WELL AS THE JSON, NOT INSTEAD OF IT
----------------------------------------------
The engine keeps reading `wfm/context_repository/holiday_master.json` at runtime. That is
deliberate and is NOT changed here:
  * the file-upload path works with no SQL at all, and holiday reasoning must not silently
    disappear when someone runs the console without a database;
  * an in-process dict lookup costs nothing, while a per-request round trip to 10.10.9.75
    would add latency to every investigation for no analytical gain.
What SQL buys is everything the JSON cannot do: joining holidays to Input_To_ML in a query,
letting reporting tools reach them, and making the calendar checkable with SQL rather than by
reading a 1.4 MB JSON file. Same pattern as dbo.CQN_Mapping.

THE JSON IS THE SOURCE, NOT THE XLSX
------------------------------------
Loading from the JSON the engine actually reads means SQL and the engine agree BY CONSTRUCTION.
Re-parsing FC_RCA_Holiday_Master_Production.xlsx here would create a second interpretation of the
same spreadsheet that could drift from the first, and `.gitignore` excludes *.xlsx so the file is
often absent anyway.

FOUR TABLES
    dbo.Holiday_Master          one row per (country, fiscal week, holiday)
    dbo.Holiday_Aggregate_Group aggregate group -> member country, from sheet 07
    dbo.Fiscal_Calendar_Week    fiscal week -> start, end, quarter, month (4-4-5)
    dbo.Holiday_Country_Alias   Country values in the data -> the key the master uses

That last table is the one that makes a join actually work. 45 of the 49 Country values in
dbo.Input_To_ML_Full match a holiday key directly; four do not -- "north america",
"multiple amer countries", "multiple emea countries" and "korea" -- because they are aggregates or
aliases. `holiday_calendar._resolve_country` handles them in Python; without an equivalent in SQL,
a join would silently return no holidays for those queues, which reads as "no holiday" rather than
"not joined". The alias rows are generated from that same resolution logic, so the two cannot
disagree.
"""
import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

from sql_backend import load_config, connect                      # noqa: E402

JSON_PATH = HERE / "wfm" / "context_repository" / "holiday_master.json"

T_MASTER = "dbo.Holiday_Master"
T_GROUP = "dbo.Holiday_Aggregate_Group"
T_FISCAL = "dbo.Fiscal_Calendar_Week"
T_ALIAS = "dbo.Holiday_Country_Alias"

DDL = {
    T_MASTER: f"""CREATE TABLE {T_MASTER} (
        country_key         NVARCHAR(120) NOT NULL,
        fiscal_week         INT           NOT NULL,
        holiday_name        NVARCHAR(200) NOT NULL,
        holiday_type        NVARCHAR(120) NULL,
        holiday_date        DATE          NULL,
        impact_before_days  INT           NULL,
        impact_after_days   INT           NULL,
        aggregate_group     NVARCHAR(120) NULL,
        needs_review        BIT           NULL
    )""",
    T_GROUP: f"""CREATE TABLE {T_GROUP} (
        aggregate_group     NVARCHAR(120) NOT NULL,
        member_country_key  NVARCHAR(120) NOT NULL
    )""",
    T_FISCAL: f"""CREATE TABLE {T_FISCAL} (
        fiscal_week   INT  NOT NULL,
        week_start    DATE NULL,
        week_end      DATE NULL,
        quarter       INT  NULL,
        fiscal_month  INT  NULL
    )""",
    T_ALIAS: f"""CREATE TABLE {T_ALIAS} (
        data_country      NVARCHAR(120) NOT NULL,
        holiday_country_key NVARCHAR(120) NOT NULL,
        resolution        NVARCHAR(40)  NOT NULL
    )""",
}
INDEXES = [
    f"CREATE INDEX IX_Holiday_Master_country_week ON {T_MASTER} (country_key, fiscal_week)",
    f"CREATE INDEX IX_Holiday_Master_week ON {T_MASTER} (fiscal_week)",
    f"CREATE INDEX IX_Fiscal_Calendar_Week_week ON {T_FISCAL} (fiscal_week)",
    f"CREATE INDEX IX_Holiday_Country_Alias_country ON {T_ALIAS} (data_country)",
]


def _date_or_none(text):
    """The master writes ISO dates, but blanks and junk both appear. A bad date must not abort a
    12,000-row load -- it becomes NULL and the row still carries its name, week and impact days."""
    t = (text or "").strip()[:10]
    if len(t) != 10:
        return None
    try:
        y, m, d = (int(x) for x in t.split("-"))
        import datetime
        return datetime.date(y, m, d)
    except (ValueError, TypeError):
        return None


def read_json():
    if not JSON_PATH.exists():
        raise SystemExit(f"{JSON_PATH} is missing. Build it first:\n"
                         f'  python load_holiday_master.py "<path>/FC_RCA_Holiday_Master_Production.xlsx"')
    return json.loads(JSON_PATH.read_text(encoding="utf-8"))


def build_rows(data):
    master = []
    for key, entries in (data.get("holidays") or {}).items():
        country, _, fw = key.partition("|")
        try:
            fw_i = int(fw)
        except (TypeError, ValueError):
            continue
        for e in entries:
            master.append((country, fw_i, str(e.get("name") or "")[:200],
                           str(e.get("type") or "")[:120] or None,
                           _date_or_none(e.get("date")),
                           int(e.get("before") or 0), int(e.get("after") or 0),
                           str(e.get("group") or "")[:120] or None,
                           1 if e.get("needs_review") else 0))

    groups = [(g, m) for g, members in (data.get("aggregate_groups") or {}).items() for m in members]

    fiscal = []
    for fw, v in (data.get("fiscal_calendar") or {}).items():
        try:
            fw_i = int(fw)
        except (TypeError, ValueError):
            continue
        q = v.get("quarter")
        mth = v.get("month")
        fiscal.append((fw_i, _date_or_none(v.get("start")), _date_or_none(v.get("end")),
                       int(q) if isinstance(q, (int, float)) else None,
                       int(mth) if isinstance(mth, (int, float)) else None))
    return master, groups, fiscal


def build_aliases(cfg, data, cur):
    """One row per (Country value in the data -> holiday key), using the ENGINE's resolver.

    Generated by calling holiday_calendar._resolve_country rather than reimplementing it, so the
    SQL join and the Python lookup cannot drift apart.
    """
    from wfm.context_repository.holiday_calendar import _resolve_country
    cur.execute(f"SELECT DISTINCT Country FROM {cfg['sql']['table']} WHERE Country IS NOT NULL")
    out, keys = [], {k.split("|")[0] for k in (data.get("holidays") or {})}
    for (raw,) in cur.fetchall():
        c = (raw or "").strip()
        if not c:
            continue
        for target in _resolve_country(data, c):
            how = ("direct" if c.lower() == target
                   else "aggregate/alias" if target in keys
                   else "unresolved")
            out.append((c[:120], target[:120], how))
    return out


def load(conn, table, ddl, rows, cols):
    cur = conn.cursor()
    cur.execute(f"IF OBJECT_ID('{table}','U') IS NOT NULL DROP TABLE {table}")
    cur.execute(ddl)
    if rows:
        marks = ", ".join("?" for _ in range(cols))
        cur.fast_executemany = True
        cur.executemany(f"INSERT INTO {table} VALUES ({marks})", rows)
    conn.commit()
    print(f"  {table:<32} {len(rows):>7,} rows")


def report(conn, cfg):
    cur = conn.cursor()
    print("\n=== row counts ===")
    for t in (T_MASTER, T_GROUP, T_FISCAL, T_ALIAS):
        try:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            print(f"  {t:<32} {cur.fetchone()[0]:>7,}")
        except Exception as e:                                     # noqa: BLE001
            print(f"  {t:<32} missing ({str(e)[:60]})")

    print("\n=== the join this enables: holidays on a real queue-week ===")
    tbl = cfg["sql"]["table"]
    cur.execute(f"""
        SELECT TOP 8 d.Forecast_name, d.Fiscal_Week, d.Country, h.holiday_name, h.holiday_type
        FROM {tbl} d
        JOIN {T_ALIAS} a  ON a.data_country = d.Country
        JOIN {T_MASTER} h ON h.country_key = a.holiday_country_key
                         AND h.fiscal_week = d.Fiscal_Week
        WHERE d.Actual_Offered IS NOT NULL AND d.fcst_offered > 0
          AND ABS(1 - d.Actual_Offered / d.fcst_offered) * 100 > 15
        ORDER BY d.Fiscal_Week DESC""")
    rows = cur.fetchall()
    if not rows:
        print("  (no flagged queue-week coincided with a holiday in this dataset)")
    for r in rows:
        print(f"  {r[0][:34]:<34} FW{r[1]}  {r[2][:16]:<16} {r[3]}  [{r[4]}]")

    cur.execute(f"""SELECT COUNT(DISTINCT d.Forecast_name) FROM {tbl} d
        JOIN {T_ALIAS} a ON a.data_country = d.Country
        JOIN {T_MASTER} h ON h.country_key = a.holiday_country_key AND h.fiscal_week = d.Fiscal_Week""")
    print(f"\n  queues with at least one holiday week: {cur.fetchone()[0]}")
    cur.execute(f"""SELECT COUNT(*) FROM (SELECT DISTINCT Country FROM {tbl}) c
        WHERE NOT EXISTS (SELECT 1 FROM {T_ALIAS} a WHERE a.data_country = c.Country)""")
    print(f"  Country values with NO holiday alias: {cur.fetchone()[0]}  (these would join to nothing)")


def main():
    ap = argparse.ArgumentParser(description="Publish the holiday calendar to SQL.")
    ap.add_argument("--check", action="store_true", help="counts and a sample join only; no writes")
    ap.add_argument("--dry-run", action="store_true", help="print what would be written; no writes")
    args = ap.parse_args()

    data = read_json()
    master, groups, fiscal = build_rows(data)
    print(f"source: {data.get('source')}")
    print(f"  holiday occurrences in JSON : {len(master):,}")
    print(f"  loader's active_rows counter : {data.get('active_rows'):,}  "
          f"(counts rows READ from the xlsx; {data.get('active_rows', 0) - len(master):,} were "
          f"duplicate names collapsed within a country-week)")
    print(f"  aggregate group memberships : {len(groups):,}")
    print(f"  fiscal calendar weeks       : {len(fiscal):,}")

    cfg = load_config()
    conn = connect(cfg)
    try:
        cur = conn.cursor()
        aliases = build_aliases(cfg, data, cur)
        print(f"  country aliases             : {len(aliases):,}")

        if args.dry_run:
            print("\n--dry-run: nothing written.")
            for t, ddl in DDL.items():
                print(f"\n{ddl}")
            return 0
        if args.check:
            report(conn, cfg)
            return 0

        print("\nloading:")
        load(conn, T_MASTER, DDL[T_MASTER], master, 9)
        load(conn, T_GROUP, DDL[T_GROUP], groups, 2)
        load(conn, T_FISCAL, DDL[T_FISCAL], fiscal, 5)
        load(conn, T_ALIAS, DDL[T_ALIAS], aliases, 3)
        for stmt in INDEXES:
            try:
                cur.execute(stmt)
            except Exception as e:                                 # noqa: BLE001
                print(f"  index skipped: {str(e)[:70]}")
        conn.commit()
        report(conn, cfg)
        print("\nThe engine still reads the JSON at runtime -- nothing about the RCA path changed.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
