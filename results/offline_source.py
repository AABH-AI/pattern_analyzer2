"""
Offline source rig -- run the REAL WFM data_access path against the local spreadsheet, no VPN.
==============================================================================================

Build once, then use:

    python ../results/offline_source.py --build          # mirror the xlsx into SQLite
    python ../results/offline_source.py --info           # what the mirror contains

WHY THIS EXISTS
---------------
`wfm/data_access.fetch_wfm_context` is the only way the engine gets its 157-week history, its
channel siblings and its investigation ladder. Bypassing it in an offline harness would mean the
SQL layer is never exercised until someone is back on the VPN, and it is exactly the layer where a
widened `_HISTORY_COLS` or a new column can break.

So instead of faking the context, this mirrors the real source spreadsheet into SQLite and hands the
engine a cursor that speaks enough T-SQL to run `data_access`'s own queries unchanged. What the
engine computes offline is therefore computed by the same code path that runs in production, from
the same numbers.

NOT FAKED, AND NOT A SUBSTITUTE
-------------------------------
Every value comes from the spreadsheet. Nothing is generated. But the local extract is the 7,350-row
`Input_To_ML_20260706110242` (42 queues, FW202401-202719), not the 88,816-row
`dbo.Input_To_ML_Full` the production config points at, and `dbo.CQN_Mapping` does not exist
locally -- so channel grouping falls back to the locality proxy, which is a real code path but not
the production one. Live SQL validation stays required; this rig makes everything up to it testable.

T-SQL DIFFERENCES HANDLED
-------------------------
`SELECT TOP n ...` -> `SELECT ... LIMIT n`. That is the only dialect feature `data_access` uses.
Anything else it might grow will raise loudly here rather than silently return the wrong rows.
"""
import argparse
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "backend"))

# The local sources available while the VPN is unavailable.
#
# TWO files are needed, and it matters which:
#
#   Input_To_ML_20260706110242.csv.xlsx   7,350 rows, 42 queues, 15 countries, Voice only.
#                                         Has a full header row. Does NOT contain Indonesia, so
#                                         the SA Indonesia FW202716 regression cannot run on it.
#   SA_INDONESIA_CLIENT.xlsx              138,623 rows, many queues INCLUDING the regression
#                                         queue. Same column ORDER minus `Priority`, but its
#                                         header row is only partly labelled, so its columns are
#                                         mapped by POSITION against the known schema below.
#
# The larger file is the default because it is the only local source that can exercise both the
# generic multi-queue requirement and the regression case.
XLSX_SMALL = r"C:\Users\shivam.saraf\Downloads\Input_To_ML_20260706110242.csv.xlsx"
SHEET_SMALL = "Input_To_ML_20260706110242"
XLSX = r"C:\Users\shivam.saraf\Downloads\SA_INDONESIA_CLIENT.xlsx"
SHEET = "Sheet1"
DB = os.path.join(HERE, "_offline_cache", "input_to_ml.sqlite")
TABLE = "Input_To_ML_Full"

# Positional schema for SA_INDONESIA_CLIENT.xlsx. Verified against its first data row:
# 202249 | 2022-01-07 | APJ | ANZ | Australia | ANZ Client Core | Brian Tan | Basic | ...
# It is the Input_To_ML schema with `Priority` absent, which shifts everything after
# Forecast_name left by one.
POSITIONAL_SCHEMA = [
    "Fiscal_Week", "Week_Ending", "Region", "SubRegion", "Country", "Forecast_name",
    "Forecaster", "Offering", "Projection_plan_name", "channel", "business_org",
    "Actual_Offered", "Actual_Handled", "fcst_offered", "fcst_handled",
    "Planned_ASU", "Actual_ASU", "Final_Units", "Final_Y5", "Final_Y4", "Final_Y3", "Final_Y2",
    "Final_Y1", "Final_upp_units", "Holiday_Count",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "Volume_Category",
]

# Mirrors backend/upload_excel_to_sql.py so a column is typed here exactly as it is in SQL Server.
NUMERIC = {"Actual_Offered", "Actual_Handled", "fcst_offered", "fcst_handled", "Planned_ASU",
           "Actual_ASU", "Final_Units", "Final_Y5", "Final_Y4", "Final_Y3", "Final_Y2", "Final_Y1",
           "Final_upp_units", "Holiday_Count", "Monday", "Tuesday", "Wednesday", "Thursday",
           "Friday", "Saturday", "Sunday"}
INT_COLS = {"Fiscal_Week"}

_TOP = re.compile(r"^\s*SELECT\s+TOP\s+(\d+)\s+", re.IGNORECASE)


def translate(sql):
    """T-SQL -> SQLite. Only `SELECT TOP n` is needed; anything else passes through untouched."""
    m = _TOP.match(sql)
    if not m:
        return sql
    n = m.group(1)
    body = sql[m.end():]
    return f"SELECT {body} LIMIT {n}"


class OfflineCursor:
    """Quacks like a pyODBC cursor for the calls `data_access` makes: execute, fetchall,
    fetchone, description."""

    def __init__(self, cur):
        self._cur = cur

    def execute(self, sql, params=None):
        translated = translate(sql)
        if params is None:
            self._cur.execute(translated)
        elif isinstance(params, (list, tuple)):
            self._cur.execute(translated, params)
        else:
            self._cur.execute(translated, (params,))
        return self

    def fetchall(self):
        return self._cur.fetchall()

    def fetchone(self):
        return self._cur.fetchone()

    @property
    def description(self):
        return self._cur.description


class OfflineConnection:
    def __init__(self, db_path=DB):
        if not os.path.exists(db_path):
            raise RuntimeError(
                f"offline mirror not built: {db_path}\n"
                f"run:  cd backend && python ../results/offline_source.py --build")
        self._conn = sqlite3.connect(db_path)

    def cursor(self):
        return OfflineCursor(self._conn.cursor())

    def close(self):
        self._conn.close()


def config(table=TABLE):
    """A config dict shaped like backend/config.json, pointing at the mirror."""
    return {"sql": {"table": table, "server": "offline-sqlite", "database": "local"}}


def connect(db_path=DB):
    return OfflineConnection(db_path)


def build(xlsx=XLSX, sheet=SHEET, db_path=DB, table=TABLE, positional=None):
    """Mirror the spreadsheet into SQLite. Values are copied, never derived.

    `positional` forces the POSITIONAL_SCHEMA rather than trusting the header row, which is what
    SA_INDONESIA_CLIENT.xlsx needs -- most of its header cells are blank. Auto-detected when not
    given: a header row with more than a couple of unnamed columns cannot be trusted.
    """
    import openpyxl

    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    if os.path.exists(db_path):
        os.remove(db_path)

    wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    ws = wb[sheet]
    it = ws.iter_rows(values_only=True)
    raw_header = next(it)
    unnamed = sum(1 for h in raw_header if h is None or str(h).strip() in ("", "None"))
    if positional is None:
        positional = unnamed > 2
    if positional:
        if len(raw_header) != len(POSITIONAL_SCHEMA):
            raise RuntimeError(
                f"{os.path.basename(xlsx)} has {len(raw_header)} columns but the positional "
                f"schema describes {len(POSITIONAL_SCHEMA)}. Refusing to guess -- inspect the "
                f"sheet and update POSITIONAL_SCHEMA.")
        header = list(POSITIONAL_SCHEMA)
        print(f"  header row has {unnamed} unnamed columns -> using the positional schema")
    else:
        header = [str(h).strip() for h in raw_header]

    def sql_type(col):
        if col in INT_COLS:
            return "INTEGER"
        if col in NUMERIC:
            return "REAL"
        return "TEXT"

    cols_ddl = ", ".join(f'"{c}" {sql_type(c)}' for c in header)
    conn = sqlite3.connect(db_path)
    conn.execute(f'CREATE TABLE "{table}" ({cols_ddl})')
    placeholders = ", ".join("?" for _ in header)

    def coerce(col, value):
        if value is None or value == "":
            return None
        if col in INT_COLS:
            try:
                return int(float(str(value)))
            except (TypeError, ValueError):
                return None
        if col in NUMERIC:
            # The extract stores some numerics as strings ('1890.170028748534').
            try:
                return float(str(value).replace(",", "").strip())
            except (TypeError, ValueError):
                return None
        if hasattr(value, "isoformat"):
            return value.isoformat()[:10]
        return str(value)

    rows = 0
    batch = []
    for raw in it:
        if raw is None or all(v is None for v in raw):
            continue
        batch.append([coerce(c, v) for c, v in zip(header, raw)])
        rows += 1
        if len(batch) >= 2000:
            conn.executemany(f'INSERT INTO "{table}" VALUES ({placeholders})', batch)
            batch = []
    if batch:
        conn.executemany(f'INSERT INTO "{table}" VALUES ({placeholders})', batch)

    # The indexes data_access's access pattern actually needs.
    conn.execute(f'CREATE INDEX ix_queue_week ON "{table}" ("Forecast_name", "Fiscal_Week")')
    conn.execute(f'CREATE INDEX ix_week ON "{table}" ("Fiscal_Week")')
    conn.commit()
    conn.close()
    wb.close()
    print(f"  mirrored {rows:,} rows, {len(header)} columns -> {db_path}")
    return rows


def info(db_path=DB, table=TABLE):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(f'SELECT COUNT(*), MIN(Fiscal_Week), MAX(Fiscal_Week), '
                f'COUNT(DISTINCT Forecast_name) FROM "{table}"')
    n, lo, hi, queues = cur.fetchone()
    print(f"  rows={n:,}  weeks {lo}-{hi}  queues={queues}")
    for col in ("channel", "Offering", "Country", "Region"):
        cur.execute(f'SELECT "{col}", COUNT(*) FROM "{table}" GROUP BY "{col}" '
                    f'ORDER BY COUNT(*) DESC LIMIT 8')
        vals = ", ".join(f"{v}({c})" for v, c in cur.fetchall())
        print(f"  {col:10s}: {vals}")
    cur.execute(f'SELECT COUNT(*) FROM "{table}" WHERE Actual_ASU IS NOT NULL')
    print(f"  rows with Actual_ASU: {cur.fetchone()[0]:,}")
    cur.execute(f'SELECT COUNT(*) FROM "{table}" WHERE Final_upp_units IS NOT NULL')
    print(f"  rows with Final_upp_units: {cur.fetchone()[0]:,}")
    conn.close()


def main():
    ap = argparse.ArgumentParser(description="Offline SQLite mirror of the RCA source spreadsheet.")
    ap.add_argument("--build", action="store_true", help="rebuild the mirror from the xlsx")
    ap.add_argument("--info", action="store_true", help="describe the mirror")
    ap.add_argument("--xlsx", default=XLSX)
    ap.add_argument("--sheet", default=SHEET)
    args = ap.parse_args()
    if args.build:
        build(args.xlsx, args.sheet)
    if args.info or not args.build:
        info()
    return 0


if __name__ == "__main__":
    sys.exit(main())
