# -*- coding: utf-8 -*-
"""Server-side filtering and refresh detection -- offline, no SQL, no model.

Covers backend/wfm/row_query.py and backend/wfm/data_freshness.py.

WHY A FAKE CURSOR RATHER THAN A LIVE CONNECTION
-----------------------------------------------
These checks are about the SQL we BUILD and the decisions we make from what comes back, not
about the server. A fake cursor makes the checks run with the VPN down, run in CI, and -- most
usefully -- lets a result be forced (a NULL checksum, a raising column) that a live server will
not produce on demand.

The live behaviour was measured separately and the figures are recorded in the modules'
docstrings; this suite is what stops those behaviours regressing.

    python results/test_data_ingestion.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

from wfm import data_freshness as df           # noqa: E402
from wfm import row_query as rq                # noqa: E402

PASS = FAIL = 0
WIDTH = 94


def check(cid, ok, label, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  PASS  {cid} {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {cid} {label}" + (f"\n          {detail}" if detail else ""))


def section(title):
    print("\n" + "-" * WIDTH + f"\n{title}\n" + "-" * WIDTH)


class FakeCursor:
    """Returns queued results in order; records the SQL it was given."""

    def __init__(self, results, raise_on=None):
        self.results, self.sql, self.params = list(results), [], []
        self.raise_on = raise_on or ()
        self._row = None

    def execute(self, sql, params=None):
        self.sql.append(" ".join(sql.split()))
        self.params.append(params)
        for frag in self.raise_on:
            if frag.lower() in sql.lower():
                raise RuntimeError(f"simulated failure on {frag}")
        self._row = self.results.pop(0) if self.results else None
        return self

    def fetchone(self):
        return self._row


# ============================================================ FILTER SAFETY
section("FILTER SAFETY -- a filter name is never trusted, a filter value is never interpolated")

for bad in ("Region; DROP TABLE x", "Actual_Offered", "1=1", "", "forecast_name"):
    try:
        rq.build_where({bad: "x"})
        ok = bad in ("",)              # empty name with a value is still a rejection
        check("SAFE-1", False, f"non-whitelisted column {bad!r} was ACCEPTED")
    except rq.FilterError:
        check("SAFE-1", True, f"rejects non-whitelisted column {bad!r}")

where, params = rq.build_where({"Forecast_name": "x' OR '1'='1"})
check("SAFE-2", "OR '1'='1" not in where and params == ["x' OR '1'='1"],
      "a quote-bearing value is parameterised, never placed in the SQL text",
      f"where={where!r} params={params!r}")

where, params = rq.build_where({"Region": ["EMEA", "APJ", "Americas"]})
check("SAFE-3", where.count("?") == 3 and params == ["EMEA", "APJ", "Americas"],
      "a multi-value filter emits one placeholder per value", where)

where, params = rq.build_where({"Region": "", "Country": None, "channel": []})
check("SAFE-4", "?" not in where and params == [],
      "empty filter values are dropped, not turned into IN ('')", where)

for name in rq.FILTERABLE:
    w, p = rq.build_where({name: "v"})
    if f"[{name}] IN (?)" not in w:
        check("SAFE-5", False, f"whitelisted column {name} did not build a clause", w)
        break
else:
    check("SAFE-5", True, f"all {len(rq.FILTERABLE)} whitelisted columns build a clause")

try:
    rq.facets_sql("t", "Actual_Offered; DROP TABLE x", "1=1")
    check("SAFE-6", False, "facets_sql accepted a non-whitelisted column")
except rq.FilterError:
    check("SAFE-6", True, "facets_sql applies the same whitelist as build_where")

# ============================================================ BOUNDS
section("BOUNDS -- a caller cannot ask for the whole table by accident")

for limit, why in ((0, "zero"), (-1, "negative"), (rq.MAX_LIMIT + 1, "above the cap")):
    try:
        rq.rows_sql("t", "1=1", limit=limit)
        check("BND-1", False, f"{why} limit was accepted")
    except rq.FilterError:
        check("BND-1", True, f"rejects a {why} limit")

try:
    rq.rows_sql("t", "1=1", limit=10, offset=-5)
    check("BND-2", False, "negative offset was accepted")
except rq.FilterError:
    check("BND-2", True, "rejects a negative offset")

check("BND-3", "FETCH NEXT 10 ROWS ONLY" in rq.rows_sql("t", "1=1", limit=10, offset=20)
      and "OFFSET 20 ROWS" in rq.rows_sql("t", "1=1", limit=10, offset=20),
      "paging uses OFFSET/FETCH with the requested values")

check("BND-4", "ORDER BY Fiscal_Week" in rq.rows_sql("t", "1=1"),
      "ordering is fixed, so OFFSET/FETCH is deterministic and there is no second injection point")

for bad in ("notanumber", "20a1"):
    try:
        rq.build_where(week_from=bad)
        check("BND-5", False, f"non-numeric week {bad!r} accepted")
    except rq.FilterError:
        check("BND-5", True, f"rejects a non-numeric fiscal week {bad!r}")

try:
    rq.build_where(flagged_only=True, band="wide")
    check("BND-6", False, "non-numeric band accepted")
except rq.FilterError:
    check("BND-6", True, "rejects a non-numeric band")

# ============================================================ SEMANTICS
section("SEMANTICS -- the SQL must mean what the client-side metric means")

check("SEM-1", "NULLIF(fcst_offered, 0)" in rq.ADHERENCE,
      "adherence guards division by zero with NULLIF, so a zero forecast yields NULL not 0")

check("SEM-2", "Actual_Offered IS NOT NULL" in rq.USABLE
      and "fcst_offered IS NOT NULL" in rq.USABLE and "fcst_offered <> 0" in rq.USABLE,
      "a row is only judgeable when both measures exist and the forecast is non-zero")

w, _ = rq.build_where(flagged_only=True, band=10)
check("SEM-3", rq.USABLE in w and "ABS(" in w,
      "flagged_only implies usable-only -- an unjudgeable row can never enter a worklist")

w, p = rq.build_where(flagged_only=True, band=-10)
check("SEM-4", p[-1] == 10.0,
      "the band is applied as a magnitude, so a negative band is not a filter that matches nothing")

w, p = rq.build_where(week_from=202701, week_to=202722)
check("SEM-5", w.count("Fiscal_Week") == 2 and p == [202701, 202722],
      "both week bounds are applied, inclusive", f"{w} {p}")

w, _ = rq.build_where(usable_only=False)
check("SEM-6", w == "1=1",
      "with no filters and usable_only off, the WHERE is a no-op rather than malformed", w)

# ============================================================ FRESHNESS
section("FRESHNESS -- the token moves when the data moves, and never otherwise")

base = [(114436, 72972, 202722, 202908), (1836072, 236981137)]
p1 = df.probe(FakeCursor(list(base)), "t")
p2 = df.probe(FakeCursor(list(base)), "t")
check("FRESH-1", p1["available"] and p1["token"] == p2["token"],
      "identical data produces an identical token -- no false 'refreshed' warnings")

moved = [(114436, 73399, 202723, 202908), (1836072, 236981137)]
check("FRESH-2", df.probe(FakeCursor(moved), "t")["token"] != p1["token"],
      "the frontier advancing moves the token")

restated = [(114436, 72972, 202722, 202908), (1836072, 999999999)]
check("FRESH-3", df.probe(FakeCursor(restated), "t")["token"] != p1["token"],
      "a RESTATEMENT of an existing week moves the token even though every count is unchanged")

check("FRESH-4", df.probe(FakeCursor(list(base)), "t")["source"] == "derived",
      "with no load column configured, the source is reported as derived")

with_col = [(114436, 72972, 202722, 202908), ("2026-08-24 03:00:00",)]
pc = df.probe(FakeCursor(with_col), "t", load_column="LoadedAt")
check("FRESH-5", pc["source"] == "load_column" and pc.get("loaded_at"),
      "a configured load column is preferred and reported", str(pc.get("source")))

degraded = df.probe(FakeCursor([(114436, 72972, 202722, 202908), (1836072, 236981137)],
                               raise_on=("MAX([LoadedAt])",)), "t", load_column="LoadedAt")
check("FRESH-6", degraded["available"] and degraded["source"] == "derived"
      and "load_column_error" in degraded,
      "a configured-but-absent load column degrades to derived AND reports why",
      str(degraded))

broken = df.probe(FakeCursor([], raise_on=("COUNT(*)",)), "t")
check("FRESH-7", broken["available"] is False and broken["error"] and broken["token"] is None,
      "a failing probe reports unavailable rather than raising into the caller", str(broken))

check("FRESH-8", df.probe(FakeCursor([(0, 0, None, None), (None, None)]), "t")["available"],
      "an empty table is a valid answer, not an error")

# ============================================================ COMPARE
section("COMPARE -- warn only when we KNOW, because a false warning teaches people to ignore it")

check("CMP-1", df.compare(p1["token"], p1)["stale"] is False,
      "a client on the current token is not stale")
check("CMP-2", df.compare("0000000000000000", p1)["stale"] is True,
      "a client on an older token is stale")

r = df.compare("anything", {"available": False, "error": "no connection"})
check("CMP-3", r["stale"] is False and r["known"] is False,
      "an unavailable probe reports UNKNOWN, never stale", str(r))

r = df.compare(None, p1)
check("CMP-4", r["stale"] is False and r["known"] is True,
      "a client with no token yet is not stale -- it has nothing to be stale against")

r = df.compare("0000000000000000", p1)
check("CMP-5", r.get("client_token") and r.get("current_token"),
      "a stale verdict names both tokens, so the report is checkable rather than asserted")

# ============================================================ DESCRIBE
section("DESCRIBE -- the sentence a human reads must not overclaim")

d = df.describe(p1, cadence="weekly")
check("DESC-1", "114,436" in d and "202722" in d, "states the row count and the frontier", d)
check("DESC-2", "weekly" in d, "mentions the configured cadence as context")
check("DESC-3", "checksum" in d.lower(),
      "says the signal is derived when there is no load column, rather than implying a load time")
check("DESC-4", "loaded" in df.describe(pc, cadence="weekly").lower(),
      "reports the real load time when one is available")
check("DESC-5", df.describe({"available": False, "error": "boom"}) == "boom",
      "an unavailable probe describes the failure, not a fabricated summary")

# a cadence must never become evidence
check("DESC-6", "monday" not in df.describe(p1, cadence="weekly").lower(),
      "no day of the week is asserted -- staleness is decided by the token, never by the clock")

print("\n" + "=" * WIDTH)
print(f"  {PASS}/{PASS + FAIL} checks passed" + (f"   ({FAIL} FAILED)" if FAIL else ""))
print("=" * WIDTH)
sys.exit(1 if FAIL else 0)
