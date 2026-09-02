# -*- coding: utf-8 -*-
"""Copy the tables this app reads from the internal SQL Server to an Azure SQL Database.

    cd backend
    python migrate_to_azure_sql.py --check      # what would be copied, no writes
    python migrate_to_azure_sql.py --apply      # create schema + copy every row
    python migrate_to_azure_sql.py --apply --only Input_To_ML_Full_138_Trimmed
    python migrate_to_azure_sql.py --apply --refresh   # data only, keep the schema

WHY THIS EXISTS
---------------
`10.10.9.75` is RFC1918 private space, so an Azure-hosted container cannot route to it --
that is addressing, not configuration, and no app setting fixes it. To serve the console on a
public Azure link the data has to live somewhere Azure can reach. This copies it.

MUST RUN FROM A MACHINE THAT CAN SEE BOTH
-----------------------------------------
Source is on the AA network, target is on the internet, so this runs from a laptop on the VPN
with internet access. It never runs in the pipeline: the build agent cannot see the source.

TARGET CREDENTIALS COME FROM THE ENVIRONMENT, NEVER A FILE
----------------------------------------------------------
    AZURE_SQL_SERVER      yourserver.database.windows.net
    AZURE_SQL_DATABASE    rca
    AZURE_SQL_USERNAME    the admin login
    AZURE_SQL_PASSWORD    its password

Source connection comes from backend/config.json as usual.

AZURE SQL IS NOT THE SAME AS THE INTERNAL SERVER
------------------------------------------------
Two differences that will otherwise bite:
  * Encryption is MANDATORY. `Encrypt=yes` here; the internal server runs with `Encrypt=no`.
  * The certificate is real, so `TrustServerCertificate` must be **no**. Leaving it on works
    but silently disables the check you are paying for.
Remember to set SQL_ENCRYPT=true and SQL_TRUST_CERT=false on the Web App -- the values in
docker-compose.yml are correct for the internal server and WRONG for Azure SQL.

WHAT IT COPIES
--------------
Only the tables the engine actually reads. `Input_To_ML_Full` and `Input_To_ML` are older
copies and are deliberately left behind.
"""
import argparse
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Order matters only for readability; there are no foreign keys.
TABLES = [
    "Input_To_ML_Full_138_Trimmed",   # the fact table -- everything else is small
    "CQN_Mapping",
    "CQN_Forecast_Pair",
    "Holiday_Master",
    "Holiday_Aggregate_Group",
    "Fiscal_Calendar_Week",
    "Holiday_Country_Alias",
    "Holiday_Semantic_Group",
    "Holiday_Name_Alias",
    "Holiday_Name_Pair_Review",
]

BATCH = 2000
MAX_LEN_TYPES = {"varchar", "nvarchar", "char", "nchar", "varbinary", "binary"}
PRECISION_TYPES = {"decimal", "numeric"}


def rule(c="="):
    print(c * 86)


def azure_conn_str():
    missing = [v for v in ("AZURE_SQL_SERVER", "AZURE_SQL_DATABASE",
                           "AZURE_SQL_USERNAME", "AZURE_SQL_PASSWORD")
               if not os.environ.get(v)]
    if missing:
        print("  target not configured -- these environment variables are unset:")
        for m in missing:
            print("      %s" % m)
        print()
        print("  PowerShell:")
        print('      $env:AZURE_SQL_SERVER   = "yourserver.database.windows.net"')
        print('      $env:AZURE_SQL_DATABASE = "rca"')
        print('      $env:AZURE_SQL_USERNAME = "rcaadmin"')
        print('      $env:AZURE_SQL_PASSWORD = "..."')
        return None
    driver = os.environ.get("AZURE_SQL_DRIVER", "ODBC Driver 18 for SQL Server")
    return ("DRIVER={%s};SERVER=tcp:%s,1433;DATABASE=%s;UID=%s;PWD=%s;"
            "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=60;"
            % (driver, os.environ["AZURE_SQL_SERVER"], os.environ["AZURE_SQL_DATABASE"],
               os.environ["AZURE_SQL_USERNAME"], os.environ["AZURE_SQL_PASSWORD"]))


def column_ddl(col):
    """One column definition, reproducing the source type faithfully."""
    name, dtype, char_len, prec, scale, nullable = col
    t = dtype.lower()
    if t in MAX_LEN_TYPES:
        length = "MAX" if char_len in (-1, None) else str(char_len)
        spec = "%s(%s)" % (dtype.upper(), length)
    elif t in PRECISION_TYPES:
        spec = "%s(%s,%s)" % (dtype.upper(), prec if prec is not None else 18,
                              scale if scale is not None else 0)
    elif t == "datetime2":
        spec = "DATETIME2(%s)" % (scale if scale is not None else 7)
    else:
        spec = dtype.upper()
    return "[%s] %s %s" % (name, spec, "NULL" if nullable == "YES" else "NOT NULL")


def source_columns(cur, table):
    cur.execute(
        "SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, "
        "       NUMERIC_SCALE, IS_NULLABLE "
        "  FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = ? "
        " ORDER BY ORDINAL_POSITION", table)
    return cur.fetchall()


def source_indexes(cur, table):
    """Non-clustered, non-unique indexes worth reproducing -- the joins rely on them."""
    cur.execute("""
        SELECT i.name, STRING_AGG(QUOTENAME(c.name), ',')
                       WITHIN GROUP (ORDER BY ic.key_ordinal)
          FROM sys.indexes i
          JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
          JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
         WHERE i.object_id = OBJECT_ID(?) AND i.type_desc = 'NONCLUSTERED'
               AND i.is_primary_key = 0 AND ic.is_included_column = 0
         GROUP BY i.name""", "dbo." + table)
    return cur.fetchall()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually write to Azure SQL")
    ap.add_argument("--check", action="store_true", help="report only (the default)")
    ap.add_argument("--refresh", action="store_true",
                    help="keep the schema, replace the data (the weekly path)")
    ap.add_argument("--only", action="append", default=None,
                    help="limit to one table; repeatable")
    args = ap.parse_args()
    writing = args.apply and not args.check
    tables = args.only or TABLES

    import pyodbc
    from sql_backend import connect, load_config

    cfg = load_config()
    src_db = (cfg.get("sql") or {}).get("database")
    rule()
    print("MIGRATE TO AZURE SQL   mode=%s" % ("APPLY (writes)" if writing else "CHECK (no writes)"))
    rule()
    print("  source : %s / %s" % ((cfg.get("sql") or {}).get("server"), src_db))
    print("  target : %s / %s" % (os.environ.get("AZURE_SQL_SERVER") or "(unset)",
                                  os.environ.get("AZURE_SQL_DATABASE") or "(unset)"))
    print("  tables : %d" % len(tables))
    print()

    try:
        src = connect(cfg)
        scur = src.cursor()
    except Exception as exc:
        print("  SOURCE UNREACHABLE: %s" % str(exc)[:200])
        print("  Are you on the VPN? 10.10.9.75 is on the internal network.")
        return 2

    cs = azure_conn_str()
    tgt = tcur = None
    if cs:
        try:
            tgt = pyodbc.connect(cs)
            tcur = tgt.cursor()
            tcur.execute("SELECT @@VERSION")
            print("  target reachable: %s" % tcur.fetchone()[0].splitlines()[0][:70])
            print()
        except Exception as exc:
            print("  TARGET UNREACHABLE: %s" % str(exc)[:200])
            print("  Check the Azure SQL firewall allows this machine's public IP.")
            if writing:
                return 2
            tgt = tcur = None
    elif writing:
        return 2

    rule("-")
    print("  %-32s %10s  %s" % ("table", "src rows", "target"))
    rule("-")
    plan = []
    for t in tables:
        try:
            scur.execute("SELECT COUNT(*) FROM dbo.[%s]" % t)
            n = scur.fetchone()[0]
        except Exception as exc:
            print("  %-32s %10s  source error: %s" % (t, "-", str(exc)[:40]))
            continue
        tgt_n = "-"
        if tcur:
            try:
                tcur.execute("SELECT COUNT(*) FROM dbo.[%s]" % t)
                tgt_n = format(tcur.fetchone()[0], ",")
            except Exception:
                tgt_n = "absent"
        print("  %-32s %10s  %s" % (t, format(n, ","), tgt_n))
        plan.append((t, n))
    total = sum(n for _, n in plan)
    rule("-")
    print("  %-32s %10s rows to copy" % ("", format(total, ",")))
    print()

    if not writing:
        print("  CHECK ONLY -- nothing written. Re-run with --apply to copy.")
        rule()
        return 0

    # ---- copy ------------------------------------------------------------------------------
    grand_t0 = time.time()
    for t, n in plan:
        print("  %s" % t)
        cols = source_columns(scur, t)
        names = ["[%s]" % c[0] for c in cols]

        if args.refresh:
            try:
                tcur.execute("TRUNCATE TABLE dbo.[%s]" % t)
                print("     truncated (schema kept)")
            except Exception as exc:
                print("     TRUNCATE failed, falling back to DELETE: %s" % str(exc)[:60])
                tcur.execute("DELETE FROM dbo.[%s]" % t)
        else:
            tcur.execute("IF OBJECT_ID('dbo.[%s]','U') IS NOT NULL DROP TABLE dbo.[%s]" % (t, t))
            ddl = "CREATE TABLE dbo.[%s] (\n  %s\n)" % (
                t, ",\n  ".join(column_ddl(c) for c in cols))
            tcur.execute(ddl)
            print("     created, %d columns" % len(cols))
        tgt.commit()

        scur.execute("SELECT %s FROM dbo.[%s]" % (", ".join(names), t))
        marks = ",".join("?" for _ in names)
        insert = "INSERT INTO dbo.[%s] (%s) VALUES (%s)" % (t, ", ".join(names), marks)
        tcur.fast_executemany = True
        copied, t0 = 0, time.time()
        while True:
            rows = scur.fetchmany(BATCH)
            if not rows:
                break
            tcur.executemany(insert, [tuple(r) for r in rows])
            copied += len(rows)
            tgt.commit()
            if n and copied % (BATCH * 10) == 0:
                print("     %s / %s rows" % (format(copied, ","), format(n, ",")))
        el = time.time() - t0

        tcur.execute("SELECT COUNT(*) FROM dbo.[%s]" % t)
        got = tcur.fetchone()[0]
        ok = got == n
        print("     copied %s rows in %.1fs -- target now %s  %s"
              % (format(copied, ","), el, format(got, ","),
                 "OK" if ok else "MISMATCH, expected %s" % format(n, ",")))
        if not ok:
            print("     ##  row counts differ. Stopping so nothing else is trusted.")
            return 1

        if not args.refresh:
            for idx_name, cols_csv in source_indexes(scur, t):
                if not cols_csv:
                    continue
                try:
                    tcur.execute("CREATE INDEX [%s] ON dbo.[%s] (%s)" % (idx_name, t, cols_csv))
                    print("     index %s (%s)" % (idx_name, cols_csv))
                except Exception as exc:
                    print("     index %s skipped: %s" % (idx_name, str(exc)[:60]))
            tgt.commit()
        print()

    rule()
    print("  DONE in %.1fs. %s rows across %d table(s)."
          % (time.time() - grand_t0, format(total, ","), len(plan)))
    print()
    print("  Now point the app at it -- Web App -> Configuration -> Application settings:")
    print("      SQL_SERVER     %s" % os.environ["AZURE_SQL_SERVER"])
    print("      SQL_DATABASE   %s" % os.environ["AZURE_SQL_DATABASE"])
    print("      SQL_TABLE      dbo.Input_To_ML_Full_138_Trimmed")
    print("      SQL_USERNAME   <the login>            (mark as a secret)")
    print("      SQL_PASSWORD   <the password>         (mark as a secret)")
    print("      SQL_DRIVER     ODBC Driver 18 for SQL Server")
    print("      SQL_ENCRYPT    true      <-- MUST be true for Azure SQL")
    print("      SQL_TRUST_CERT false     <-- MUST be false; the certificate is real")
    print()
    print("  Then check:  curl https://<app>.azurewebsites.net/api/health")
    rule()
    return 0


if __name__ == "__main__":
    sys.exit(main())
