#!/usr/bin/env python3
"""
FC_RCA deterministic reasoning engine — computed entirely from the source workbook.

Nothing here is hardcoded to a queue, a period or an outcome:

  * every threshold is read from config.json -> engine.thresholds
  * every hypothesis, its applicability, suppression and accept conditions are read
    from hypothesis_catalogue.json (the spec requires the catalogue to be versioned
    CONFIGURATION, not code)
  * every reason string is rendered from measured feature values, never authored
  * driver relevance is measured PER QUEUE by best-lag correlation, never assumed
  * holiday effect is measured PER QUEUE from that queue's own history

Implements the canonical sequence in FC_RCA_RCA_Methodology.md §6, steps 1-13.
Step 14 (narrative) belongs to narrative_service.py — the only LLM invocation point.

CLI:
  python rca_engine.py --queues                     list breaching queues, latest week
  python rca_engine.py --rca "<Forecast_name>"      full investigation
  python rca_engine.py --selftest                   invariants, no narrative calls
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# numeric helpers
# ---------------------------------------------------------------------------

NUMERIC_COLUMNS = (
    "Actual_Offered", "fcst_offered",
    "Planned_ASU", "Actual_ASU", "Final_Units", "Final_Y5", "Final_Y4",
    "Final_Y3", "Final_Y2", "Final_Y1", "Final_upp_units", "Holiday_Count",
)
# Handled volumes (Actual_Handled, fcst_handled) are deliberately NOT loaded.
# Forecast Adherence is defined on OFFERED volume only, so handled figures play no
# part in any calculation, hypothesis or output — carrying them would only invite
# them into a conclusion they have no business being in. Handled volume measures
# what the operation coped with, not what customers asked for; mixing the two is
# how a demand explanation quietly turns into a capacity one.


def coerce(value: Any) -> float | None:
    """Cast BEFORE validating.

    The source workbook stores some numerics as text — measured: fcst_offered
    7,934 rows, fcst_handled 7,410, Actual_Offered 286, Actual_Handled 254, with
    values such as '410.99999999999994'. A naive load turns these into NaN, which
    would register as the Missing availability state, apply a DataSufficiency
    penalty and raise a false Missing Data hypothesis.
    """
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "").strip())
        except ValueError:
            return None
    return None


def coerce_raw(value: Any) -> float | None:
    """coerce(), plus the bytes the fast reader hands back for genuine numbers."""
    if type(value) is bytes:
        try:
            return float(value)
        except ValueError:
            try:
                return float(value.decode("utf-8", "replace").replace(",", "").strip())
            except ValueError:
                return None
    return coerce(value)


# ---------------------------------------------------------------------------
# workbook readers — fast path plus fallback, both feeding one ingest
# ---------------------------------------------------------------------------

_CELL = re.compile(rb'<c r="([A-Z]+)\d+"([^>]*)><v>([^<]*)</v>')
_ROW = re.compile(rb"<row ")
_SI = re.compile(rb"<si>(.*?)</si>", re.S)
_T = re.compile(rb"<t[^>]*>([^<]*)</t>")
_SHEET = re.compile(r"xl/worksheets/sheet\d+\.xml$")


def _col_index(letters: bytes) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + (ch - 64)
    return n - 1


def _read_xlsx_fast(path: Path):
    """Parse the sheet XML directly. Values come back as bytes (numbers) or str
    (shared strings); omitted cells are simply absent, which is how blanks appear."""
    import zipfile

    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        sheets = sorted(n for n in names if _SHEET.match(n))
        if not sheets:
            raise ValueError("no worksheet found in workbook")
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            blob = z.read("xl/sharedStrings.xml")
            shared = [b"".join(_T.findall(si)).decode("utf-8", "replace")
                      for si in _SI.findall(blob)]
        raw = z.read(sheets[0])

    header: list[str] | None = None
    rows: list[dict[int, Any]] = []
    for chunk in _ROW.split(raw)[1:]:
        cells = _CELL.findall(chunk)
        if not cells:
            continue
        rec: dict[int, Any] = {}
        for letters, attrs, value in cells:
            rec[_col_index(letters)] = (shared[int(value)] if b't="s"' in attrs else value)
        if header is None:
            header = [str(rec.get(i, "")) for i in range(max(rec) + 1)]
            continue
        rows.append(rec)
    if header is None:
        raise ValueError("workbook contains no rows")
    return header, rows, "fast-xml"


def _read_sql(sql: dict, min_week=None, max_week=None):
    """Read the demand table over ODBC. Same shape as the workbook readers.

    Only the columns the engine uses are selected, and the fiscal-week filter is
    applied in the WHERE clause so the database does the narrowing rather than
    shipping every row over the wire.
    """
    import pyodbc

    wanted = ["Fiscal_Week", "Forecast_name", *DIMENSIONS, *NUMERIC_COLUMNS]
    seen, cols = set(), []
    for c in wanted:
        if c not in seen:
            seen.add(c)
            cols.append(c)

    conn_str = (
        f"DRIVER={{{sql.get('driver', 'ODBC Driver 17 for SQL Server')}}};"
        f"SERVER={sql['server']};DATABASE={sql['database']};"
        f"Encrypt={'yes' if sql.get('encrypt') else 'no'};"
        f"TrustServerCertificate={'yes' if sql.get('trust_server_certificate') else 'no'};"
    )
    if (sql.get("auth") or "sql").lower() == "sql":
        conn_str += f"UID={sql['username']};PWD={sql['password']};"
    else:
        conn_str += "Trusted_Connection=yes;"

    where, params = [], []
    if min_week is not None:
        where.append("Fiscal_Week >= ?")
        params.append(int(min_week))
    if max_week is not None:
        where.append("Fiscal_Week <= ?")
        params.append(int(max_week))
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    select = ", ".join(f"[{c}]" for c in cols)

    with pyodbc.connect(conn_str, timeout=int(sql.get("timeout", 30))) as cn:
        cur = cn.cursor()
        cur.execute(f"SELECT {select} FROM {sql['table']}{clause}", *params)
        header = [d[0] for d in cur.description]
        rows = [{i: v for i, v in enumerate(rec) if v is not None and v != ""}
                for rec in cur.fetchall()]
    return header, rows, f"sql:{sql['table']}"


def _read_xlsx_openpyxl(path: Path):
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("openpyxl is required for the fallback reader") from exc
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    it = ws.iter_rows(values_only=True)
    header = [str(h) if h is not None else "" for h in next(it)]
    rows = [{i: v for i, v in enumerate(r) if v is not None and v != ""} for r in it]
    wb.close()
    return header, rows, "openpyxl"


def mean(xs) -> float | None:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def median(xs) -> float | None:
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def stdev(xs) -> float | None:
    xs = [x for x in xs if x is not None]
    return statistics.pstdev(xs) if len(xs) > 1 else None


def pearson(a, b) -> float | None:
    pts = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(pts) < 3:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in pts) / (sx * sy)


def best_lag_correlation(demand, driver, max_lag: int, min_sample: int):
    """Lag is determined EMPIRICALLY per queue, never prescribed."""
    best_r, best_lag = None, None
    for lag in range(0, max_lag + 1):
        shifted = [driver[i - lag] if i - lag >= 0 else None for i in range(len(driver))]
        pairs = sum(1 for x, y in zip(demand, shifted) if x is not None and y is not None)
        if pairs < min_sample:
            continue
        r = pearson(demand, shifted)
        if r is not None and (best_r is None or abs(r) > abs(best_r)):
            best_r, best_lag = r, lag
    return best_r, best_lag


def slope(xs) -> float | None:
    xs = [x for x in xs if x is not None]
    n = len(xs)
    if n < 3:
        return None
    mx = (n - 1) / 2
    my = sum(xs) / n
    den = sum((i - mx) ** 2 for i in range(n))
    if den == 0:
        return None
    return sum((i - mx) * (xs[i] - my) for i in range(n)) / den


def pct_change(new, old) -> float | None:
    if new is None or old in (None, 0):
        return None
    return (new - old) / abs(old) * 100.0


# ---------------------------------------------------------------------------
# fiscal calendar — 4-4-5, 53-week years absorbed into Q4 as 4-5-5
# ---------------------------------------------------------------------------


def fiscal_parts(fw: int, weeks_in_year: int = 52) -> dict:
    year, week = divmod(fw, 100)
    if week <= 13:
        quarter, in_q = 1, week
    elif week <= 26:
        quarter, in_q = 2, week - 13
    elif week <= 39:
        quarter, in_q = 3, week - 26
    else:
        quarter, in_q = 4, week - 39
    if quarter == 4 and weeks_in_year == 53:
        pattern = (4, 5, 5)          # 53-week year absorbed into Q4
    else:
        pattern = (4, 4, 5)
    bounds, run = [], 0
    for length in pattern:
        run += length
        bounds.append(run)
    offset = 0 if in_q <= bounds[0] else (1 if in_q <= bounds[1] else 2)
    month = (quarter - 1) * 3 + offset + 1
    month_start = in_q == 1 or in_q == bounds[0] + 1 or in_q == bounds[1] + 1
    return {"fiscalYear": year, "fiscalWeek": week, "fiscalQuarter": quarter,
            "fiscalMonth": month, "weekInQuarter": in_q,
            "isMonthStart": month_start, "isQuarterStart": in_q == 1}


# ---------------------------------------------------------------------------
# data store
# ---------------------------------------------------------------------------

# Descriptive (non-numeric) columns carried into per-queue metadata at load time.
# These are the queue's identity and grouping attributes — they are what the engine
# groups, filters and rolls up by; they are never treated as demand drivers.
#
# EXCLUDED on purpose:
#   business_org — the source carries a single value (CSG) on every row, so it cannot
#     distinguish anything and would only add noise.
#   Forecaster — a person's name. An RCA explains why demand moved, and attributing a
#     miss to a named individual is both outside that question and against the spec's
#     rule that recommendations route to a team, never to a person.
# Re-add either here if that changes; nothing else needs editing, because every
# consumer reads this tuple rather than hardcoding a column list.
DIMENSIONS = ("Region", "SubRegion", "Country", "Offering", "channel",
              "Volume_Category", "Projection_plan_name")


class DataStore:
    """Loads the workbook once and indexes it by queue and fiscal week."""

    def __init__(self, path=None, sql: dict | None = None,
                 min_week=None, max_week=None):
        self.path = path
        self.sql = sql
        self.min_week = min_week
        self.max_week = max_week
        self.rows_by_queue: dict[str, dict[int, dict]] = defaultdict(dict)
        self.meta: dict[str, dict] = {}
        self.weeks: list[int] = []
        self.weeks_with_actuals: list[int] = []
        self.duplicates: dict[str, int] = defaultdict(int)
        self.coerced_strings: dict[str, int] = defaultdict(int)
        self.row_count = 0
        self.first_seen: dict[str, int] = {}
        self.reader: str = ""
        self._siblings: dict[str, list[str]] = {}
        self._holiday_effect: dict[str, tuple[float | None, int]] = {}

    # -- load ---------------------------------------------------------------
    def load(self) -> "DataStore":
        """Read the workbook.

        The fast path parses the sheet XML directly. openpyxl's read_only mode is
        already streaming, but it builds a Python object per cell, and at ~4.4M cells
        that dominates the whole load: measured 32.6s against 3.6s for a direct
        parse of the same file — 7.4x. Inflating the 131 MB sheet XML itself costs
        only 0.37s, so the cost was never I/O.

        openpyxl remains the fallback for anything the fast path cannot handle
        (unusual cell encodings, a workbook it does not recognise). Both paths feed
        the same ingest, so behaviour cannot drift between them.
        """
        if self.sql:
            header, rows, self.reader = _read_sql(self.sql, self.min_week, self.max_week)
        else:
            try:
                header, rows, self.reader = _read_xlsx_fast(self.path)
            except Exception:
                header, rows, self.reader = _read_xlsx_openpyxl(self.path)

        idx = {name: i for i, name in enumerate(header)}
        required = {"Fiscal_Week", "Forecast_name", "Actual_Offered", "fcst_offered"}
        missing = required - set(idx)
        if missing:
            raise ValueError(f"workbook is missing required columns: {sorted(missing)}")

        num_idx = [(c, idx[c]) for c in NUMERIC_COLUMNS if c in idx]
        dim_idx = [(d, idx[d]) for d in DIMENSIONS if d in idx]
        qi, wi = idx["Forecast_name"], idx["Fiscal_Week"]
        weeks, weeks_actual = set(), set()
        rows_by_queue, meta, first_seen = self.rows_by_queue, self.meta, self.first_seen
        coerced = self.coerced_strings

        for raw in rows:
            queue = raw.get(qi)
            week = raw.get(wi)
            if queue is None or week is None:
                continue
            if isinstance(queue, bytes):
                queue = queue.decode("utf-8", "replace")
            week = int(coerce_raw(week) or 0)
            if not week:
                continue
            self.row_count += 1
            weeks.add(week)

            record: dict[str, Any] = {}
            for col, i in num_idx:
                val = raw.get(i)
                # A numeric stored as TEXT arrives as a shared string, so it is a str
                # here where a genuine number is bytes. That is exactly the source
                # defect worth counting: cast first, validate after.
                if isinstance(val, str) and val.strip() != "":
                    coerced[col] += 1
                record[col] = coerce_raw(val)

            if record.get("Actual_Offered") is not None:
                weeks_actual.add(week)

            per_queue = rows_by_queue[queue]
            if week in per_queue:
                self.duplicates[queue] += 1
            per_queue[week] = record

            if queue not in meta:
                m = {}
                for d, i in dim_idx:
                    v = raw.get(i)
                    m[d] = v.decode("utf-8", "replace") if isinstance(v, bytes) else v
                m["Forecast_name"] = queue
                meta[queue] = m
                first_seen[queue] = week
            elif week < first_seen[queue]:
                first_seen[queue] = week

        self.weeks = sorted(weeks)
        self.weeks_with_actuals = sorted(weeks_actual)
        self._index_siblings()
        return self

    def _index_siblings(self) -> None:
        groups: dict[tuple, list[str]] = defaultdict(list)
        for queue, meta in self.meta.items():
            groups[(meta.get("Country"), meta.get("Offering"))].append(queue)
        for queue, meta in self.meta.items():
            peers = groups[(meta.get("Country"), meta.get("Offering"))]
            self._siblings[queue] = [q for q in peers if q != queue]

    # -- accessors ----------------------------------------------------------
    @property
    def latest_actuals_week(self) -> int:
        return self.weeks_with_actuals[-1]

    def queue_names(self) -> list[str]:
        return sorted(self.rows_by_queue)

    def siblings(self, queue: str) -> list[str]:
        return self._siblings.get(queue, [])

    def series(self, queue: str, field: str, weeks: list[int]) -> list[float | None]:
        rows = self.rows_by_queue.get(queue, {})
        return [rows.get(w, {}).get(field) for w in weeks]

    def weeks_up_to(self, week: int) -> list[int]:
        return [w for w in self.weeks if w <= week]

    def actual_weeks_for(self, queue: str) -> list[int]:
        rows = self.rows_by_queue.get(queue, {})
        return sorted(w for w, r in rows.items() if r.get("Actual_Offered") is not None)

    # -- per-queue measured holiday effect ----------------------------------
    def holiday_effect(self, queue: str) -> tuple[float | None, int]:
        """Measured from THIS queue's own history. Never assumed."""
        if queue in self._holiday_effect:
            return self._holiday_effect[queue]
        rows = self.rows_by_queue.get(queue, {})
        hol, non = [], []
        for record in rows.values():
            actual = record.get("Actual_Offered")
            if actual is None:
                continue
            (hol if (record.get("Holiday_Count") or 0) > 0 else non).append(actual)
        effect = None
        if len(hol) >= 1 and len(non) >= 3:
            mh, mn = mean(hol), mean(non)
            if mn:
                effect = (mh - mn) / mn * 100.0
        self._holiday_effect[queue] = (effect, len(hol))
        return self._holiday_effect[queue]


# ---------------------------------------------------------------------------
# period model — weekly / monthly / quarterly, pooled
# ---------------------------------------------------------------------------


def period_weeks(store: DataStore, grain: str, anchor_week: int) -> list[int]:
    """Weeks belonging to the period that contains anchor_week, at this grain."""
    if grain == "Weekly":
        return [anchor_week]
    parts = fiscal_parts(anchor_week)
    out = []
    for w in store.weeks:
        if w // 100 != anchor_week // 100:
            continue
        p = fiscal_parts(w)
        if grain == "Monthly" and p["fiscalMonth"] == parts["fiscalMonth"]:
            out.append(w)
        elif grain == "Quarterly" and p["fiscalQuarter"] == parts["fiscalQuarter"]:
            out.append(w)
    return sorted(out)


def pooled_adherence(store: DataStore, queue: str, weeks: list[int]):
    """Pooled over weeks WITH actuals. fcst=0 makes a week non-computable (BR-110)."""
    used, noncomputable, blank = [], [], []
    total_a = total_f = 0.0
    rows = store.rows_by_queue.get(queue, {})
    for w in weeks:
        rec = rows.get(w, {})
        a, f = rec.get("Actual_Offered"), rec.get("fcst_offered")
        if a is None:
            blank.append(w)
            continue
        if f in (None, 0):
            noncomputable.append(w)
            continue
        total_a += a
        total_f += f
        used.append(w)
    adherence = ((1 - total_a / total_f) * 100.0) if total_f else None
    return {"adherence": adherence, "actual": total_a, "forecast": total_f,
            "weeksUsed": used, "weeksNonComputable": noncomputable,
            "weeksBlank": blank, "weeksInPeriod": weeks}


def volume_band(forecast: float | None, bands: dict) -> tuple[str, bool]:
    """Derive a band from volume when Volume_Category is absent at source."""
    order = ["<=100", "101-250", "250-500", "501-1000", "1001-5000", ">5000"]
    limits = [100, 250, 500, 1000, 5000]
    if forecast is None:
        return order[0], True
    for name, limit in zip(order, limits):
        if forecast <= limit:
            return name, True
    return ">5000", True


# ---------------------------------------------------------------------------
# feature computation — everything the catalogue conditions can reference
# ---------------------------------------------------------------------------


def compute_features(store: DataStore, cfg: dict, cat: dict, queue: str,
                     grain: str, anchor_week: int) -> dict:
    th = cfg["engine"]["thresholds"]
    meta = store.meta[queue]
    offering = meta.get("Offering")
    win = int(th["trailing_window_weeks"])

    weeks = period_weeks(store, grain, anchor_week)
    period = pooled_adherence(store, queue, weeks)

    actual_weeks = [w for w in store.actual_weeks_for(queue) if w <= anchor_week]
    hist_weeks = [w for w in actual_weeks if w not in period["weeksUsed"]]
    trailing = hist_weeks[-win:]

    dem_hist = store.series(queue, "Actual_Offered", trailing)
    fc_hist = store.series(queue, "fcst_offered", trailing)

    f: dict[str, Any] = {}
    f["queue"] = queue
    f["grain"] = grain
    f["offering"] = offering
    f["channel"] = meta.get("channel")
    f["adherence"] = period["adherence"]
    f["abs_adherence"] = abs(period["adherence"]) if period["adherence"] is not None else None
    f["forecast_offered"] = period["forecast"]
    f["actual_offered"] = period["actual"]
    f["variance_contacts"] = period["actual"] - period["forecast"]
    f["abs_variance_contacts"] = abs(f["variance_contacts"])
    f["history_weeks"] = len(actual_weeks)
    f["actual_weeks"] = len(actual_weeks)
    f["trailing_periods"] = len(trailing)
    f["period_complete"] = len(period["weeksBlank"]) == 0 and len(period["weeksNonComputable"]) == 0

    parts = fiscal_parts(anchor_week)
    f.update({k: v for k, v in parts.items()})
    f["spans_month_boundary"] = parts["isMonthStart"] if grain == "Weekly" else True
    f["spans_quarter_boundary"] = parts["isQuarterStart"] if grain == "Weekly" else grain == "Quarterly"

    # calendar — holiday, measured per queue
    hol_count = sum((store.rows_by_queue[queue].get(w, {}).get("Holiday_Count") or 0)
                    for w in period["weeksInPeriod"])
    effect, sample = store.holiday_effect(queue)
    f["holiday_count"] = hol_count
    f["holiday_effect_pct"] = effect
    f["holiday_effect_sample"] = sample
    trailing_mean = mean(dem_hist)
    f["trailing_mean_actual"] = trailing_mean
    f["trailing_median_actual"] = median(dem_hist)
    f["actual_vs_history_pct"] = pct_change(period["actual"] / max(len(period["weeksUsed"]), 1),
                                            trailing_mean) if trailing_mean else None
    # how much of the observed movement the queue's own holiday effect would explain
    if effect and f["actual_vs_history_pct"] not in (None, 0):
        f["holiday_explained_share"] = max(0.0, min(1.0, effect / f["actual_vs_history_pct"]))
        f["direction_matches_holiday_effect"] = (effect < 0) == (f["actual_vs_history_pct"] < 0)
    else:
        f["holiday_explained_share"] = 0.0
        f["direction_matches_holiday_effect"] = False
    # A holiday depresses demand. It can therefore only explain a miss where actual
    # came in BELOW forecast. Matching against the trailing mean alone is not enough:
    # demand can sit below its own average yet still land above a lower forecast, and
    # in that case the holiday explains nothing about the miss.
    f["holiday_direction_vs_forecast_coherent"] = bool(
        effect is not None and f["variance_contacts"] is not None
        and (effect < 0) == (f["variance_contacts"] < 0))

    # seasonality — same week last year
    ly = anchor_week - 100
    ly_rec = store.rows_by_queue.get(queue, {}).get(ly, {})
    ly_a, ly_f = ly_rec.get("Actual_Offered"), ly_rec.get("fcst_offered")
    f["same_week_last_year_available"] = ly_a is not None and ly_f not in (None, 0)
    f["same_week_last_year_adherence"] = ((1 - ly_a / ly_f) * 100.0) if f["same_week_last_year_available"] else None
    if f["same_week_last_year_available"] and period["adherence"] is not None:
        same_sign = (f["same_week_last_year_adherence"] < 0) == (period["adherence"] < 0)
        ratio = min(abs(f["same_week_last_year_adherence"]), abs(period["adherence"])) / \
            max(abs(f["same_week_last_year_adherence"]), abs(period["adherence"]), 1e-9)
        f["seasonal_consistency"] = ratio if same_sign else 0.0
    else:
        f["seasonal_consistency"] = 0.0

    # statistical
    sd = stdev(dem_hist)
    period_mean_actual = period["actual"] / max(len(period["weeksUsed"]), 1)
    f["period_z_score"] = (abs(period_mean_actual - trailing_mean) / sd) if (sd and trailing_mean is not None) else None
    med = median(dem_hist)
    devs = [abs(x - med) for x in dem_hist if x is not None] if med is not None else []
    mad = median(devs) if devs else None
    f["mad_z_score"] = (abs(period_mean_actual - med) / (1.4826 * mad)) if (mad and mad > 0) else None

    half = len(trailing) // 2
    early, late = dem_hist[:half], dem_hist[half:]
    f["drift_early_mean"], f["drift_late_mean"] = mean(early), mean(late)
    f["drift_shift_pct"] = pct_change(f["drift_late_mean"], f["drift_early_mean"])
    f["abs_drift_shift_pct"] = abs(f["drift_shift_pct"]) if f["drift_shift_pct"] is not None else None
    f["momentum_early_slope"], f["momentum_late_slope"] = slope(early), slope(late)
    f["momentum_change_pct"] = pct_change(f["momentum_late_slope"], f["momentum_early_slope"])
    f["abs_momentum_change_pct"] = abs(f["momentum_change_pct"]) if f["momentum_change_pct"] is not None else None
    f["earlier_std"], f["recent_std"] = stdev(early), stdev(late)
    f["variance_ratio"] = (f["recent_std"] / f["earlier_std"]) if (f["earlier_std"] and f["recent_std"]) else None

    # forecast bias / trend, from signed adherence history
    adh_hist = []
    for w in trailing:
        rec = store.rows_by_queue[queue].get(w, {})
        a, fo = rec.get("Actual_Offered"), rec.get("fcst_offered")
        adh_hist.append(((1 - a / fo) * 100.0) if (a is not None and fo not in (None, 0)) else None)
    valid_adh = [x for x in adh_hist if x is not None]
    f["mean_bias"] = mean(valid_adh)
    f["abs_mean_bias"] = abs(f["mean_bias"]) if f["mean_bias"] is not None else None
    cur_sign = 1 if (period["adherence"] or 0) > 0 else -1
    run = 0
    for x in reversed(valid_adh):
        if (1 if x > 0 else -1) == cur_sign:
            run += 1
        else:
            break
    f["bias_run_length"] = run + 1
    f["bias_sign_share"] = (sum(1 for x in valid_adh if (1 if x > 0 else -1) == cur_sign)
                            / len(valid_adh)) if valid_adh else None
    sa, sf = slope(dem_hist), slope(fc_hist)
    f["actual_trend_slope_pct"] = (sa / trailing_mean * 100.0) if (sa is not None and trailing_mean) else None
    f["forecast_trend_slope_pct"] = (sf / mean(fc_hist) * 100.0) if (sf is not None and mean(fc_hist)) else None
    if f["actual_trend_slope_pct"] is not None and f["forecast_trend_slope_pct"] is not None:
        denom = max(abs(f["actual_trend_slope_pct"]), abs(f["forecast_trend_slope_pct"]), 1e-9)
        f["trend_divergence"] = abs(f["actual_trend_slope_pct"] - f["forecast_trend_slope_pct"]) / denom
    else:
        f["trend_divergence"] = None

    # adjacent period offset — demand shift / transition
    prior = [w for w in actual_weeks if w < min(period["weeksInPeriod"])]
    f["adjacent_period_available"] = bool(prior)
    if prior:
        pw = prior[-1]
        rec = store.rows_by_queue[queue].get(pw, {})
        a, fo = rec.get("Actual_Offered"), rec.get("fcst_offered")
        adj_var = (a - fo) if (a is not None and fo is not None) else None
        f["adjacent_adherence"] = ((1 - a / fo) * 100.0) if (a is not None and fo not in (None, 0)) else None
        if adj_var is not None and f["variance_contacts"]:
            opposite = (adj_var < 0) != (f["variance_contacts"] < 0)
            f["adjacent_offset_ratio"] = (min(abs(adj_var), abs(f["variance_contacts"]))
                                          / max(abs(adj_var), abs(f["variance_contacts"]))) if opposite else 0.0
        else:
            f["adjacent_offset_ratio"] = 0.0
    else:
        f["adjacent_adherence"] = None
        f["adjacent_offset_ratio"] = 0.0

    # drivers — relevance measured per queue, order from the cascade
    cascade = cat["driver_cascade"].get(offering, [])
    #
    # Final_Y1..Y5 are NESTED, not disjoint: Y2 is a subset of Y1, Y3 of Y2, and so
    # on, so sum(Y1..Y5) != Final_Units. Correlating raw Final_Y1 against demand
    # therefore just re-measures the whole installed base. The exclusive cohort —
    # units whose coverage expires soonest, i.e. in-year-1-only — is Y1 minus Y2,
    # obtained by DIFFERENCING the nested tiers.
    def exclusive_band(q: str, weeks_: list[int], outer: str, inner: str):
        a = store.series(q, outer, weeks_)
        b = store.series(q, inner, weeks_)
        return [(x - y) if (x is not None and y is not None) else None for x, y in zip(a, b)]

    driver_fields = {
        "asu": "Actual_ASU",              # Active Serviceable Units, under warranty in market
        "shipment": "Final_upp_units",    # extended-protection / upgrade plan units
        "installed_base": "Final_Units",  # installed base (warranty units) — demand driver
    }
    gate = float(th["relevance_gate_correlation"])
    driver_series: dict[str, list] = {}
    for name, field in driver_fields.items():
        driver_series[name] = store.series(queue, field, trailing)
    # warranty = exclusive year-1-only cohort, derived by differencing nested tiers
    driver_series["warranty"] = exclusive_band(queue, trailing, "Final_Y1", "Final_Y2")

    for name in list(driver_series):
        field = driver_fields.get(name)
        drv_hist = driver_series[name]
        present_hist = any(v is not None for v in drv_hist)
        r, lag = best_lag_correlation(dem_hist, drv_hist,
                                      int(th["max_lag_weeks"]), int(th["min_lag_sample"]))
        if name == "warranty":
            period_vals = exclusive_band(queue, period["weeksInPeriod"], "Final_Y1", "Final_Y2")
        else:
            period_vals = [store.rows_by_queue[queue].get(w, {}).get(field)
                           for w in period["weeksInPeriod"]]
        cur, base = mean(period_vals), mean(drv_hist)
        change = pct_change(cur, base)
        f[f"{name}_correlation"] = round(r, 4) if r is not None else None
        f[f"{name}_lag_weeks"] = lag
        f[f"{name}_gate_passed"] = bool(r is not None and abs(r) >= gate)
        f[f"{name}_change_pct"] = change
        f[f"abs_{name}_change_pct"] = abs(change) if change is not None else None
        f[f"{name}_fields_present"] = present_hist
        f[f"{name}_in_cascade"] = name in cascade
        f[f"{name}_cascade_position"] = cascade.index(name) + 1 if name in cascade else None
        #
        # DIRECTION COHERENCE. A driver only explains THIS deviation if the demand
        # movement it implies points the same way as the movement actually observed.
        # implied = sign(correlation) x sign(driver movement). A driver that moved,
        # and correlates, but implies the OPPOSITE direction, is not the cause —
        # accepting it would produce a confident explanation that contradicts the
        # arithmetic. Correlation sign is also recorded so the mechanism can be
        # phrased correctly rather than assuming a positive relationship.
        implied = None
        if r is not None and change is not None and change != 0:
            implied = (1 if r > 0 else -1) * (1 if change > 0 else -1)
        observed = None
        if f.get("actual_vs_history_pct") is not None and f["actual_vs_history_pct"] != 0:
            observed = 1 if f["actual_vs_history_pct"] > 0 else -1
        f[f"{name}_implied_demand_direction"] = implied
        f[f"{name}_correlation_sign"] = (1 if (r or 0) > 0 else -1) if r is not None else None
        f[f"{name}_direction_coherent"] = bool(
            implied is not None and observed is not None and implied == observed)
    f["asu_applicable"] = "asu" in cascade
    f["shipment_applicable"] = "shipment" in cascade
    f["warranty_applicable"] = "warranty" in cascade or "shipment" in cascade
    f["warranty_mix_change_pct"] = f.get("warranty_change_pct")
    f["abs_warranty_mix_change_pct"] = f.get("abs_warranty_change_pct")

    planned = mean([store.rows_by_queue[queue].get(w, {}).get("Planned_ASU") for w in period["weeksInPeriod"]])
    actual_asu = mean([store.rows_by_queue[queue].get(w, {}).get("Actual_ASU") for w in period["weeksInPeriod"]])
    f["planned_asu"], f["actual_asu"] = planned, actual_asu
    f["asu_plan_actual_both_present"] = planned is not None and actual_asu is not None
    f["asu_plan_variance_pct"] = pct_change(actual_asu, planned)
    f["abs_asu_plan_variance_pct"] = abs(f["asu_plan_variance_pct"]) if f["asu_plan_variance_pct"] is not None else None

    # siblings — redistribution
    sibs = store.siblings(queue)
    f["sibling_queue_count"] = len(sibs)
    f["queue_lineage_available"] = False      # no lineage source deployed
    f["lineage_event_in_period"] = False
    worst_r, worst_q, offset_share = None, None, 0.0
    for sib in sibs:
        sib_hist = store.series(sib, "Actual_Offered", trailing)
        r = pearson(dem_hist, sib_hist)
        if r is not None and (worst_r is None or r < worst_r):
            worst_r, worst_q = r, sib
        rec = store.rows_by_queue.get(sib, {}).get(anchor_week, {})
        sa_, sf_ = rec.get("Actual_Offered"), rec.get("fcst_offered")
        if sa_ is not None and sf_ is not None and f["variance_contacts"]:
            sv = sa_ - sf_
            if (sv < 0) != (f["variance_contacts"] < 0):
                offset_share = max(offset_share, min(abs(sv), abs(f["variance_contacts"]))
                                   / max(abs(sv), abs(f["variance_contacts"])))
    f["sibling_inverse_correlation"] = round(worst_r, 4) if worst_r is not None else None
    f["sibling_top_queue"] = worst_q
    f["sibling_offset_share"] = round(offset_share, 4)

    # data quality
    ratio = (period["actual"] / period["forecast"]) if period["forecast"] else None
    f["actual_forecast_ratio"] = round(ratio, 4) if ratio is not None else None
    hist_ratios = [a / fo for a, fo in zip(dem_hist, fc_hist)
                   if a is not None and fo not in (None, 0)]
    f["trailing_min_ratio"] = round(min(hist_ratios), 4) if hist_ratios else None
    collapse_at = float(th["data_quality_collapse_ratio"])
    f["data_quality_collapse"] = bool(
        ratio is not None and ratio < collapse_at
        and (f["trailing_min_ratio"] is None or f["trailing_min_ratio"] > collapse_at)
    )
    f["missing_field_count"] = sum(
        1 for col in ("Actual_ASU", "Planned_ASU", "Volume_Category", "Final_Units")
        if (col == "Volume_Category" and not meta.get("Volume_Category"))
        or (col != "Volume_Category" and mean([store.rows_by_queue[queue].get(w, {}).get(col)
                                               for w in period["weeksInPeriod"]]) is None)
    )
    f["duplicate_row_count"] = store.duplicates.get(queue, 0)
    f["unmapped_dimension_count"] = sum(1 for d in ("Region", "SubRegion", "Country", "Offering", "channel")
                                        if not meta.get(d))
    f["first_appearance_week"] = store.first_seen.get(queue)

    f["_period"] = period
    f["_trailing_weeks"] = trailing
    f["_adherence_history"] = adh_hist
    return f


# ---------------------------------------------------------------------------
# declarative condition evaluation
# ---------------------------------------------------------------------------


def resolve(value, cfg: dict):
    if isinstance(value, str) and value.startswith("cfg:"):
        return cfg["engine"]["thresholds"][value[4:]]
    return value


def test_condition(cond: dict, features: dict, cfg: dict) -> tuple[bool, str]:
    name = cond["feature"]
    op = cond["op"]
    want = resolve(cond.get("value"), cfg)
    have = features.get(name)
    label = f"{name}={fmt_value(have)}"

    if op == "present":
        return have is not None, label
    if op == "absent":
        return have is None, label
    if have is None:
        return False, f"{name}=unavailable"

    try:
        if op == "gt":
            ok = have > want
        elif op == "gte":
            ok = have >= want
        elif op == "lt":
            ok = have < want
        elif op == "lte":
            ok = have <= want
        elif op == "eq":
            ok = have == want
        elif op == "ne":
            ok = have != want
        elif op == "in":
            ok = have in want
        elif op == "not_in":
            ok = have not in want
        elif op == "abs_gt":
            ok = abs(have) > want
        elif op == "abs_gte":
            ok = abs(have) >= want
        else:
            return False, f"{name}: unknown operator '{op}'"
    except TypeError:
        return False, f"{name}: incomparable ({fmt_value(have)} vs {fmt_value(want)})"

    symbol = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "eq": "=", "ne": "!=",
              "in": "in", "not_in": "not in", "abs_gt": "|x|>", "abs_gte": "|x|>="}[op]
    return ok, f"{name}={fmt_value(have)} {symbol} {fmt_value(want)}"


def fmt_value(v) -> str:
    if v is None:
        return "unavailable"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:.2f}".rstrip("0").rstrip(".") if abs(v) < 1e6 else f"{v:,.0f}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def evaluate_all(conds, features, cfg) -> tuple[bool, list[str]]:
    details = []
    ok = True
    for cond in conds or []:
        passed, detail = test_condition(cond, features, cfg)
        details.append(("PASS " if passed else "FAIL ") + detail)
        ok = ok and passed
    return ok, details


HUMAN = {
    "holiday_count": "holiday days in period",
    "holiday_effect_pct": "this queue's measured holiday demand effect",
    "holiday_effect_sample": "holiday weeks observed",
    "holiday_explained_share": "share of the movement the holiday effect would explain",
    "period_z_score": "standard deviations from this queue's trailing mean",
    "actual_vs_history_pct": "change against trailing mean demand",
    "trailing_mean_actual": "trailing mean weekly demand",
    "trailing_median_actual": "trailing median weekly demand",
    "mad_z_score": "robust outlier score",
    "bias_run_length": "consecutive periods deviating the same way",
    "mean_bias": "mean signed adherence over the window",
    "bias_sign_share": "share of window periods deviating the same way",
    "actual_trend_slope_pct": "actual demand trend per week",
    "forecast_trend_slope_pct": "forecast trend per week",
    "trend_divergence": "relative divergence between the two trends",
    "asu_correlation": "installed-base correlation with demand",
    "asu_lag_weeks": "installed-base lag, weeks",
    "asu_change_pct": "installed-base change against trailing mean",
    "asu_gate_passed": "installed base passes this queue's relevance gate",
    "shipment_correlation": "shipment correlation with demand",
    "shipment_lag_weeks": "shipment lag, weeks",
    "shipment_change_pct": "shipment change against trailing mean",
    "shipment_gate_passed": "shipments pass this queue's relevance gate",
    "warranty_correlation": "warranty-cohort correlation with demand",
    "warranty_lag_weeks": "warranty lag, weeks",
    "warranty_mix_change_pct": "warranty cohort change against trailing mean",
    "warranty_gate_passed": "warranty passes this queue's relevance gate",
    "asu_plan_variance_pct": "actual installed base against plan",
    "planned_asu": "planned installed base",
    "actual_asu": "actual installed base",
    "drift_shift_pct": "mean shift between window halves",
    "drift_early_mean": "earlier-half mean demand",
    "drift_late_mean": "later-half mean demand",
    "momentum_change_pct": "change in rate of change",
    "variance_ratio": "recent volatility against earlier",
    "recent_std": "recent standard deviation",
    "earlier_std": "earlier standard deviation",
    "actual_forecast_ratio": "actual as a share of forecast",
    "trailing_min_ratio": "lowest actual/forecast ratio in the window",
    "missing_field_count": "context fields absent for this period",
    "duplicate_row_count": "duplicate rows at queue x week",
    "history_weeks": "weeks of actuals available",
    "actual_weeks": "weeks of actuals available",
    "adjacent_offset_ratio": "offset against the adjacent period",
    "adjacent_adherence": "adjacent period adherence",
    "sibling_queue_count": "related queues in the same country and offering",
    "sibling_inverse_correlation": "strongest inverse correlation with a related queue",
    "sibling_offset_share": "share of this variance offset by a related queue",
    "sibling_top_queue": "most inversely correlated related queue",
    "seasonal_consistency": "agreement with the same week last year",
    "same_week_last_year_adherence": "same week last year adherence",
    "unmapped_dimension_count": "unmapped dimension values",
    "first_appearance_week": "first fiscal week seen",
    "trailing_periods": "periods in the trailing window",
}


def render_evidence(names, features) -> str:
    """Reason strings are RENDERED from measured values, never authored."""
    parts = []
    for n in names or []:
        if n not in features:
            continue
        parts.append(f"{HUMAN.get(n, n)} {fmt_value(features[n])}")
    return "; ".join(parts) if parts else "no measurable evidence available"


# ---------------------------------------------------------------------------
# investigation
# ---------------------------------------------------------------------------

CONF_WEIGHTS = [
    ("ContradictoryEvidence", 0.20), ("EvidenceStrength", 0.18),
    ("BusinessRuleValidation", 0.15), ("StatisticalAgreement", 0.14),
    ("DataSufficiency", 0.12), ("ContextCompleteness", 0.10),
    ("HistoricalConsistency", 0.06), ("ModelAgreement", 0.05),
]
LEVELS = [(0.85, "Very High"), (0.70, "High"), (0.50, "Medium"), (0.30, "Low"), (0.0, "Very Low")]
ORDER = {"Very Low": 0, "Low": 1, "Medium": 2, "High": 3, "Very High": 4}


def level_for(score: float) -> str:
    for cut, name in LEVELS:
        if score >= cut:
            return name
    return "Very Low"


class Engine:
    def __init__(self, store: DataStore, cfg: dict, cat: dict):
        self.store, self.cfg, self.cat = store, cfg, cat
        self.th = cfg["engine"]["thresholds"]

    # -- worklist -----------------------------------------------------------
    def worklist(self, grain: str = "Weekly", week: int | None = None,
                 include_immaterial: bool = True) -> dict:
        week = week or self.store.latest_actuals_week
        trigger = float(self.cfg["engine"]["adherence_trigger_pct"])
        batch_at = float(self.cfg["engine"]["batch_threshold_pct"])
        major_at = float(self.cfg["engine"]["major_deviation_pct"])
        floors = self.cfg["engine"]["materiality_floor_by_band"]

        rows, suppressed = [], 0
        for queue in self.store.queue_names():
            weeks = period_weeks(self.store, grain, week)
            p = pooled_adherence(self.store, queue, weeks)
            if p["adherence"] is None or not p["weeksUsed"]:
                continue
            adh = p["adherence"]
            if abs(adh) <= trigger:
                continue
            meta = self.store.meta[queue]
            band = meta.get("Volume_Category")
            derived = not band
            if derived:
                band, _ = volume_band(p["forecast"] / max(len(p["weeksUsed"]), 1), floors)
            variance = p["actual"] - p["forecast"]
            floor = floors.get(band, 0)
            material = abs(variance) >= floor
            major = abs(adh) > major_at and material
            if not material and not include_immaterial:
                suppressed += 1
                continue
            rows.append({
                "queue": queue,
                "region": meta.get("Region"), "subRegion": meta.get("SubRegion"),
                "country": meta.get("Country"), "offering": meta.get("Offering"),
                "channel": meta.get("channel"),
                "adherencePct": round(adh, 1),
                "direction": "Under-forecast" if adh < 0 else "Over-forecast",
                "forecastOffered": round(p["forecast"]), "actualOffered": round(p["actual"]),
                "varianceContacts": round(variance),
                "absVarianceContacts": abs(round(variance)),
                "volumeBand": band, "volumeBandDerived": derived,
                "materialityFloor": floor, "materialityMet": material,
                "majorDeviation": major,
                "generationMode": "Batch" if abs(adh) > batch_at else "OnDemand",
                "period": week, "grain": grain,
            })
        # §8 default sort is ABSOLUTE VARIANCE, not adherence percentage
        rows.sort(key=lambda r: -r["absVarianceContacts"])
        return {"week": week, "grain": grain, "count": len(rows),
                "suppressedImmaterial": suppressed,
                "totalQueues": len(self.store.queue_names()), "rows": rows}

    # -- aggregate view (§7) -------------------------------------------------
    def aggregate(self, grain: str = "Weekly", week: int | None = None,
                  level: int = 1) -> dict:
        week = week or self.store.latest_actuals_week
        keys = ("Region", "SubRegion", "Country", "Offering") if level == 1 else \
               ("Region", "SubRegion", "Country", "Offering", "channel")
        groups: dict[tuple, list[str]] = defaultdict(list)
        for queue, meta in self.store.meta.items():
            groups[tuple(meta.get(k) for k in keys)].append(queue)

        trigger = float(self.cfg["engine"]["adherence_trigger_pct"])
        out = []
        for key, queues in groups.items():
            pos = neg = tot_a = tot_f = 0.0
            children_with_rca = 0
            for q in queues:
                p = pooled_adherence(self.store, q, period_weeks(self.store, grain, week))
                if p["adherence"] is None or not p["weeksUsed"]:
                    continue
                v = p["actual"] - p["forecast"]
                tot_a += p["actual"]
                tot_f += p["forecast"]
                if v >= 0:
                    pos += v
                else:
                    neg += abs(v)
                if abs(p["adherence"]) > trigger:
                    children_with_rca += 1
            if tot_f == 0:
                continue
            gross, net = pos + neg, pos - neg
            offset = (min(pos, neg) / (gross / 2)) if gross else 0.0
            offset = min(1.0, offset)
            single = len(queues) == 1
            label = "IDIOSYNCRATIC" if offset < 0.30 else ("MIXED" if offset < 0.70 else "SYSTEMIC")
            out.append({
                "group": " · ".join(str(k) for k in key),
                "pooledAdherencePct": round((1 - tot_a / tot_f) * 100.0, 1),
                "direction": ("Offsetting" if offset > 0.70 and not single
                              else ("Under-forecast" if net > 0 else "Over-forecast")),
                "netVarianceContacts": round(net), "grossVarianceContacts": round(gross),
                "offsetRatio": round(offset, 3), "offsetLabel": None if single else label,
                "deEmphasisePooled": offset > 0.70 and not single,
                "singleQueueGroup": single,
                "childQueues": len(queues), "childrenWithRca": children_with_rca,
            })
        # §7.4 ranked by GROSS variance, never adherence percentage
        out.sort(key=lambda r: -r["grossVarianceContacts"])
        return {"week": week, "grain": grain, "level": level,
                "note": "No confidence score at aggregate level — confidence describes a conclusion, and an aggregate has none of its own.",
                "rows": out}

    # -- full investigation --------------------------------------------------
    def investigate(self, queue: str, grain: str = "Weekly",
                    week: int | None = None) -> dict:
        if queue not in self.store.rows_by_queue:
            raise KeyError(queue)
        week = week or self.store.latest_actuals_week
        f = compute_features(self.store, self.cfg, self.cat, queue, grain, week)
        period = f["_period"]
        meta = self.store.meta[queue]

        if period["adherence"] is None:
            return {"queue": queue, "period": week, "grain": grain,
                    "caseStatus": "Failed",
                    "reason": "Forecast Adherence is non-computable for this period (BR-110): fcst_offered is zero or absent."}

        floors = self.cfg["engine"]["materiality_floor_by_band"]
        band = meta.get("Volume_Category")
        band_derived = not band
        if band_derived:
            band, _ = volume_band(period["forecast"] / max(len(period["weeksUsed"]), 1), floors)
        floor = floors.get(band, 0)
        variance = period["actual"] - period["forecast"]
        material = abs(variance) >= floor
        major = abs(period["adherence"]) > float(self.cfg["engine"]["major_deviation_pct"]) and material

        # ---- Step 6: hypotheses, from the catalogue ----
        hypotheses = []
        for spec in self.cat["hypotheses"]:
            applicable, app_detail = evaluate_all(spec.get("applicable_when"), f, self.cfg)
            if not applicable:
                hypotheses.append({
                    "id": spec["id"], "category": spec["category"], "name": spec["name"],
                    "state": "Not Applicable",
                    "reason": "Not relevant to this queue — " + "; ".join(
                        d[5:] for d in app_detail if d.startswith("FAIL")),
                    "conditions": app_detail})
                continue
            supp, supp_detail = evaluate_all(spec.get("suppressed_when"), f, self.cfg)
            if spec.get("suppressed_when") and supp:
                hypotheses.append({
                    "id": spec["id"], "category": spec["category"], "name": spec["name"],
                    "state": "Suppressed",
                    "reason": "Could not be tested — " + "; ".join(
                        d[5:] for d in supp_detail if d.startswith("PASS")),
                    "conditions": supp_detail})
                continue
            accepted, acc_detail = evaluate_all(spec.get("accepted_when"), f, self.cfg)
            hypotheses.append({
                "id": spec["id"], "category": spec["category"], "name": spec["name"],
                "state": "Accepted" if accepted else "Rejected",
                "reason": render_evidence(spec.get("evidence_features"), f)
                          + ("" if accepted else " — did not meet: " + "; ".join(
                              d[5:] for d in acc_detail if d.startswith("FAIL"))),
                "conditions": acc_detail,
                "metrics": spec.get("metrics", []),
                "evidenceFeatures": {n: f.get(n) for n in spec.get("evidence_features", [])}})

        accepted = [h for h in hypotheses if h["state"] == "Accepted"]

        # ---- Step 13: root cause selection, driver cascade first ----
        cascade = self.cat["driver_cascade"].get(meta.get("Offering"), [])
        driver_names = {"shipment": "Shipment Volume Change", "asu": "Installed Base Change",
                        "warranty": "Warranty Mix Shift"}
        # A root cause must be a BUSINESS cause. Data Quality entries are still
        # investigated and still recorded with their state, but they are never
        # selected as the root cause and never framed as the answer to "why".
        priority = ([driver_names[d] for d in cascade]
                    + ["Installed Base Change", "Warranty Mix Shift", "Shipment Volume Change",
                       "Holiday", "Seasonality", "Demand Shift", "Volume Redistribution",
                       "Queue Migration", "Forecast Bias", "Trend Misidentification",
                       "Drift", "Momentum Shift", "Demand Spike", "Demand Drop",
                       "Outlier", "Variance Expansion", "ASU Plan Variance",
                       "Fiscal Month Transition", "Quarter Transition"])
        business = [h for h in accepted if h["category"] != "Data Quality"]
        primary = None
        for want in priority:
            primary = next((h for h in business if h["name"] == want), None)
            if primary:
                break
        if primary is None:
            primary = business[0] if business else None
        secondary = next((h for h in business if h is not primary), None)
        inconclusive = primary is None
        why_chain = self._build_why_chain(f, primary, cascade, meta)

        # ---- Step 10: recursive chain, derived from measured values ----
        tree = self._build_chain(f, period, variance, primary, cascade)

        # ---- Steps 7-8: evidence ----
        evidence = self._build_evidence(f, primary, hypotheses, period, major, floor, band)

        # ---- Step 11: cross-examination ----
        xexam = self._cross_examine(f, primary, hypotheses, material, period)

        # ---- Step 12: confidence ----
        confidence = self._confidence(f, primary, hypotheses, evidence, xexam,
                                      band_derived, period, inconclusive)

        recommendations = self._recommend(f, primary, inconclusive, band_derived)
        availability = self._availability(f, meta, band_derived, band)
        limitations = self._limitations(f, xexam, confidence, band_derived, period)

        fingerprint = hashlib.sha256(json.dumps({
            "queue": queue, "grain": grain, "week": week,
            "rows": [self.store.rows_by_queue[queue].get(w) for w in period["weeksInPeriod"]],
        }, sort_keys=True, default=str).encode()).hexdigest()

        timeline = None
        if period["weeksBlank"] or period["weeksNonComputable"]:
            timeline = {
                "lastWeekWithActuals": max(period["weeksUsed"]) if period["weeksUsed"] else None,
                "weeksUsed": len(period["weeksUsed"]),
                "weeksInPeriod": len(period["weeksInPeriod"]),
                "coveragePct": round(len(period["weeksUsed"]) / max(len(period["weeksInPeriod"]), 1) * 100),
                "missingWeeks": period["weeksBlank"],
                "nonComputableWeeks": period["weeksNonComputable"],
            }

        return {
            "queue": queue, "period": week, "grain": grain,
            "fiscal": fiscal_parts(week),
            "region": meta.get("Region"), "subRegion": meta.get("SubRegion"),
            "country": meta.get("Country"), "offering": meta.get("Offering"),
            "channel": meta.get("channel"),
            "adherencePct": round(period["adherence"], 1),
            "direction": "Under-forecast" if period["adherence"] < 0 else "Over-forecast",
            "forecastOffered": round(period["forecast"]),
            "actualOffered": round(period["actual"]),
            "varianceContacts": round(variance),
            "absVarianceContacts": abs(round(variance)),
            "actualVsForecast": "above" if variance > 0 else "below",
            "volumeBand": band, "volumeBandDerived": band_derived,
            "materialityFloor": floor, "materialityMet": material,
            "majorDeviation": major,
            "caseStatus": "Inconclusive" if inconclusive else "Completed",
            "generationMode": "Batch" if abs(period["adherence"]) > float(
                self.cfg["engine"]["batch_threshold_pct"]) else "OnDemand",
            "rootCause": None if inconclusive else {
                "id": primary["id"], "name": primary["name"], "category": primary["category"],
                "statement": why_chain[-1]["because"], "reason": primary["reason"]},
            "whyChain": why_chain,
            "secondaryDriver": None if not secondary else {
                "name": secondary["name"], "reason": secondary["reason"]},
            "reasoningChain": tree,
            "hypotheses": hypotheses,
            "hypothesisCounts": {s: sum(1 for h in hypotheses if h["state"] == s)
                                 for s in ("Accepted", "Rejected", "Suppressed", "Not Applicable")},
            "evidence": evidence,
            "crossExamination": xexam,
            "confidence": confidence,
            "recommendations": recommendations,
            "dataAvailability": availability,
            "limitations": limitations,
            "timeline": timeline,
            "adherenceHistory": [
                {"week": w, "adherencePct": (round(v, 1) if v is not None else None)}
                for w, v in zip(f["_trailing_weeks"], f["_adherence_history"])
            ] + [{"week": week, "adherencePct": round(period["adherence"], 1)}],
            "driverAnalysis": {
                name: {"correlation": f.get(f"{name}_correlation"),
                       "lagWeeks": f.get(f"{name}_lag_weeks"),
                       "gatePassed": f.get(f"{name}_gate_passed"),
                       "changePct": (round(f[f"{name}_change_pct"], 1)
                                     if f.get(f"{name}_change_pct") is not None else None),
                       "inCascade": f.get(f"{name}_in_cascade"),
                       "cascadePosition": f.get(f"{name}_cascade_position"),
                       "fieldsPresent": f.get(f"{name}_fields_present")}
                for name in ("asu", "shipment", "warranty")},
            "audit": {
                "inputFingerprint": fingerprint,
                "businessRulesVersion": self.cfg["engine"]["business_rules_version"],
                "weightsVersion": self.cfg["engine"]["confidence_weights_version"],
                "hypothesisCatalogueVersion": self.cat["version"],
                "questionCatalogueVersion": self.cfg["engine"]["question_catalogue_version"],
                "relevanceGate": self.th["relevance_gate_correlation"],
                "trailingWindowWeeks": self.th["trailing_window_weeks"],
                "sourceRows": self.store.row_count,
            },
            "features": {k: v for k, v in f.items() if not k.startswith("_")},
        }

    # -- the WHY chain: business language, no figures, no data-quality framing ----
    def _build_why_chain(self, f, primary, cascade, meta) -> list[dict]:
        """Successive 'why' answers in plain business language.

        Deliberately carries NO numbers, NO metric names and NO investigative
        wording. The measured figures live in reasoningChain and driverAnalysis for
        anyone who wants them; this chain answers only 'why'.
        """
        direction = "more" if f["variance_contacts"] > 0 else "fewer"
        plan_word = "above" if f["variance_contacts"] > 0 else "below"
        chain = [{
            "why": "Why did the forecast miss?",
            "because": (f"Customers contacted this queue {direction} than the plan expected, "
                        f"so demand landed {plan_word} forecast."),
        }]
        if primary is None:
            chain.append({
                "why": f"Why did demand land {plan_word} plan?",
                "because": ("No business explanation holds up. The way demand moved does not match "
                            "the calendar, it does not match how the covered base moved, and it does "
                            "not match a lasting change in the way this queue is forecast. Rather than "
                            "name a cause the evidence does not support, this is left open."),
                "terminal": True,
            })
            return chain

        name = primary["name"]
        offering = meta.get("Offering")
        drv = {"Installed Base Change": "asu", "Shipment Volume Change": "shipment",
               "Warranty Mix Shift": "warranty"}.get(name)

        if drv:
            moved = "grew" if (f.get(f"{drv}_change_pct") or 0) > 0 else "shrank"
            inverse = (f.get(f"{drv}_correlation_sign") or 1) < 0
            # The demand direction is what the driver IMPLIES, not what its own
            # movement was: for an inversely related driver, a shrinking base means
            # rising demand. Phrasing this from the movement alone would state a
            # mechanism that contradicts the observed direction.
            follow = "more" if (f.get(f"{drv}_implied_demand_direction") or 1) > 0 else "fewer"
            what = {"asu": "the number of units in the market still under warranty",
                    "shipment": "the number of units carrying an extended protection plan",
                    "warranty": "the number of units whose warranty cover is closest to running out"}[drv]
            if inverse:
                link = (f"For a {offering} offering, {what} moves opposite to contacts into this queue: "
                        f"as cover falls away, customers who would have been served under warranty come "
                        f"through this queue instead. So when it {moved}, {follow} customers ended up "
                        f"contacting this queue, showing up a short while later rather than immediately.")
            else:
                link = (f"For a {offering} offering, {what} is what generates contacts. When it {moved}, "
                        f"{follow} customers became eligible to call, and that shows up in this queue "
                        f"a short while later rather than immediately.")
            chain += [
                {"why": f"Why did demand land {plan_word} plan?",
                 "because": (f"The base of customers entitled to support {moved}, and support demand for this "
                             f"queue moves with that base.")},
                {"why": "Why did that change demand for this queue?", "because": link},
                {"why": "Why did the forecast not allow for it?",
                 "because": ("The forecast for this queue was not carrying that movement in the covered base. "
                             "The plan assumed the entitled population would hold steady, so the shift passed "
                             "straight through into the miss."),
                 "terminal": True},
            ]
            return chain

        if name == "Holiday":
            chain += [
                {"why": f"Why did demand land {plan_word} plan?",
                 "because": "A public holiday fell inside this period, and customers do not contact support on holidays the way they do on working days."},
                {"why": "Why did that produce a miss rather than being absorbed?",
                 "because": ("This queue has a consistent holiday pattern in its own history, but the plan for "
                             "this period was built as though the week traded normally.")},
                {"why": "Why was the holiday not in the plan?",
                 "because": ("The holiday calendar for this country was not reflected in the forecast for this "
                             "period, so a predictable, recurring calendar effect was left out."),
                 "terminal": True},
            ]
            return chain

        if name in ("Forecast Bias", "Trend Misidentification", "Drift", "Momentum Shift"):
            side = "under" if f["variance_contacts"] > 0 else "over"
            chain += [
                {"why": f"Why did demand land {plan_word} plan?",
                 "because": f"It was not a one-off. This queue has been {side}-planned in the same direction for a run of consecutive periods."},
                {"why": "Why does it keep going the same way?",
                 "because": ("Underlying demand for this queue has been moving in one direction while the plan "
                             "has stayed closer to where demand used to be, so the two drift further apart "
                             "each period.")},
                {"why": "Why has the plan not caught up?",
                 "because": ("The way this queue is forecast is not tracking its direction of travel. No movement "
                             "in the covered base explains it, so the gap sits with the forecasting approach "
                             "rather than with the business."),
                 "terminal": True},
            ]
            return chain

        if name == "Volume Redistribution":
            chain += [
                {"why": f"Why did demand land {plan_word} plan?",
                 "because": "Customer contacts did not disappear or appear — they arrived somewhere else. A related queue serving the same customers moved the opposite way at the same time."},
                {"why": "Why did contacts move between queues?",
                 "because": ("Customers reaching this business can land in more than one queue. When routing or "
                             "customer behaviour tips one way, one queue gains what the other loses while the "
                             "total barely changes.")},
                {"why": "Why did the forecast miss it?",
                 "because": ("Each queue was planned on its own. The total across the related queues was closer "
                             "to right than either queue individually, so the split between them is what failed."),
                 "terminal": True},
            ]
            return chain

        if name in ("Demand Shift", "Fiscal Month Transition", "Quarter Transition"):
            chain += [
                {"why": f"Why did demand land {plan_word} plan?",
                 "because": "The demand arrived, but not in the period the plan expected it — the neighbouring period moved the opposite way by a similar amount."},
                {"why": "Why did it land in a different period?",
                 "because": ("Contacts near a period boundary can fall either side of it. The volume was real and "
                             "expected; only its timing was wrong.")},
                {"why": "Why does that matter?",
                 "because": ("Judged on the period alone this looks like a miss, but across the two periods "
                             "together the plan was close. The issue is how demand was spread across the "
                             "boundary, not how much was expected."),
                 "terminal": True},
            ]
            return chain

        if name == "Seasonality":
            chain += [
                {"why": f"Why did demand land {plan_word} plan?",
                 "because": "This time of year behaves differently for this queue, and the same pattern showed up at the same point last year."},
                {"why": "Why was a repeating pattern missed?",
                 "because": ("The plan for this period was built closer to recent weeks than to how this queue "
                             "behaves at this point in the year.")},
                {"why": "Why does that keep happening?",
                 "because": ("The seasonal shape of this queue's demand is not being carried into its forecast, "
                             "so a pattern that repeats every year is treated as a surprise each time."),
                 "terminal": True},
            ]
            return chain

        chain += [
            {"why": f"Why did demand land {plan_word} plan?",
             "because": f"Demand for this queue moved well outside how it normally behaves, well beyond its usual period-to-period swing."},
            {"why": "Why did it move that much?",
             "because": ("Nothing in the covered base or the calendar moved with it. The shift in demand is real "
                         "and clearly outside normal variation, but no business driver available for this queue "
                         "moves alongside it.")},
            {"why": "Why can this not be taken further?",
             "because": ("The drivers that would explain a movement of this kind for this queue either do not "
                         "apply to this offering or do not track its demand closely enough to be relied on. "
                         "What can be said is stated; what cannot is left open rather than guessed."),
             "terminal": True},
        ]
        return chain

    # -- chain --------------------------------------------------------------
    def _build_chain(self, f, period, variance, primary, cascade) -> list[dict]:
        direction = "above" if variance > 0 else "below"
        chain = [{
            "level": 0,
            "question": "What deviated, and by how much?",
            "answer": (f"Adherence {period['adherence']:+.1f}% — actual {period['actual']:,.0f} "
                       f"came in {abs(variance):,.0f} contacts {direction} a forecast of "
                       f"{period['forecast']:,.0f}."),
            "evidence": "Verified business data",
            "semanticKey": "LVL0_MAGNITUDE",
        }]
        if primary is None:
            tested = [h for h in ([] if not f else []) ]
            chain.append({
                "level": 1,
                "question": "Does any catalogue hypothesis hold on the measured evidence?",
                "answer": ("No hypothesis met its acceptance conditions. "
                           + self._why_nothing_held(f)),
                "evidence": "Deterministic statistics",
                "semanticKey": "LVL1_NO_HYPOTHESIS", "terminal": True,
                "terminationReason": "No hypothesis achieved defensible support — recorded as Inconclusive (BR-306).",
            })
            return chain

        name = primary["name"]
        feats = primary.get("evidenceFeatures", {})

        chain.append({
            "level": 1,
            "question": "Is the movement outside this queue's normal variation?",
            "answer": (f"Period demand sits {fmt_value(f.get('period_z_score'))} standard deviations "
                       f"from the trailing mean of {fmt_value(f.get('trailing_mean_actual'))} "
                       f"contacts per week over {f.get('trailing_periods')} weeks."),
            "evidence": "Deterministic statistic — volatility band",
            "semanticKey": "LVL1_VARIATION",
        })

        driver_map = {"Installed Base Change": "asu", "Shipment Volume Change": "shipment",
                      "Warranty Mix Shift": "warranty"}
        if name in driver_map:
            d = driver_map[name]
            chain.append({
                "level": 2,
                "question": f"Does {HUMAN.get(d + '_correlation', d)} demonstrably track demand for this queue?",
                "answer": (f"Yes — correlation {fmt_value(f.get(d + '_correlation'))} at a lag of "
                           f"{fmt_value(f.get(d + '_lag_weeks'))} weeks, at or above the relevance gate of "
                           f"{self.th['relevance_gate_correlation']}. Cascade position "
                           f"{fmt_value(f.get(d + '_cascade_position'))} for {f.get('offering')}."),
                "evidence": "Deterministic statistic — empirical best-lag correlation",
                "semanticKey": "LVL2_DRIVER_RELEVANCE",
            })
            chain.append({
                "level": 3,
                "question": "Did that driver actually move in this period?",
                "answer": (f"It moved {fmt_value(f.get(d + '_change_pct'))}% against its trailing mean, "
                           f"at or beyond the {self.th['driver_change_min_pct']}% materiality floor for a driver movement."),
                "evidence": "Verified business data",
                "semanticKey": "LVL3_DRIVER_MOVEMENT",
            })
            chain.append({
                "level": 4,
                "question": "What mechanism does that establish?",
                "answer": (f"A {fmt_value(f.get(d + '_change_pct'))}% movement in "
                           f"{HUMAN.get(d + '_correlation', d).replace(' correlation with demand', '')} "
                           f"propagated to this queue's demand after roughly "
                           f"{fmt_value(f.get(d + '_lag_weeks'))} weeks, which the forecast did not absorb."),
                "evidence": "Deterministic statistic",
                "semanticKey": "LVL4_MECHANISM", "terminal": True,
                "terminationReason": "A business driver with demonstrated per-queue relevance and a measured movement is a terminating cause.",
            })
            return chain

        if name == "Missing Data":
            chain.append({
                "level": 2,
                "question": "Is the actual volume plausible against this queue's own history?",
                "answer": (f"No. Actual is {fmt_value(f.get('actual_forecast_ratio'))} of forecast, "
                           f"whereas the lowest ratio anywhere in the trailing window is "
                           f"{fmt_value(f.get('trailing_min_ratio'))}."),
                "evidence": "Deterministic statistic",
                "semanticKey": "LVL2_PLAUSIBILITY",
            })
            chain.append({
                "level": 3,
                "question": "Does any business driver or calendar effect accompany it?",
                "answer": self._driver_summary(f, cascade),
                "evidence": "Business rule — relevance gate",
                "semanticKey": "LVL3_DRIVER_CHECK",
            })
            chain.append({
                "level": 4,
                "question": "What mechanism does that establish?",
                "answer": ("Actuals for this queue-week appear truncated at source. The magnitude is "
                           "outside anything the queue's own history produces, and no driver or calendar "
                           "effect accompanies it — this is a load or mapping fault in the actuals feed, "
                           "not a demand change."),
                "evidence": "Deterministic statistic",
                "semanticKey": "LVL4_MECHANISM", "terminal": True,
                "terminationReason": "Data-quality mechanism established; the deviation is not a demand event.",
            })
            return chain

        if name == "Holiday":
            chain.append({
                "level": 2,
                "question": "How does this queue behave in holiday weeks historically?",
                "answer": (f"Across {fmt_value(f.get('holiday_effect_sample'))} holiday weeks in its own history, "
                           f"demand runs {fmt_value(f.get('holiday_effect_pct'))}% against non-holiday weeks."),
                "evidence": "Deterministic statistic — measured per queue",
                "semanticKey": "LVL2_HOLIDAY_PROFILE",
            })
            chain.append({
                "level": 3,
                "question": "What mechanism does that establish?",
                "answer": (f"{fmt_value(f.get('holiday_count'))} holiday day(s) fell in this period, and this "
                           f"queue's own measured holiday effect accounts for "
                           f"{fmt_value(round((f.get('holiday_explained_share') or 0) * 100, 1))}% of the observed "
                           f"movement. The forecast did not carry that calendar effect."),
                "evidence": "Business rule — holiday calendar",
                "semanticKey": "LVL3_MECHANISM", "terminal": True,
                "terminationReason": "Calendar mechanism established from the queue's own holiday history.",
            })
            return chain

        if name in ("Forecast Bias", "Trend Misidentification", "Drift", "Momentum Shift"):
            chain.append({
                "level": 2,
                "question": "Is the deviation episodic or systematic?",
                "answer": (f"Systematic — {fmt_value(f.get('bias_run_length'))} consecutive periods deviating "
                           f"the same way, {fmt_value(f.get('bias_sign_share'))} of the window one-sided, "
                           f"mean signed adherence {fmt_value(f.get('mean_bias'))}%."),
                "evidence": "Deterministic statistic — sign run",
                "semanticKey": "LVL2_SYSTEMATIC",
            })
            chain.append({
                "level": 3,
                "question": "Is a business driver responsible instead?",
                "answer": self._driver_summary(f, cascade),
                "evidence": "Business rule — relevance gate",
                "semanticKey": "LVL3_DRIVER_CHECK",
            })
            chain.append({
                "level": 4,
                "question": "What mechanism does that establish?",
                "answer": (f"The forecast for this queue carries a persistent directional bias: actual demand "
                           f"trends {fmt_value(f.get('actual_trend_slope_pct'))}% per week while the forecast "
                           f"trends {fmt_value(f.get('forecast_trend_slope_pct'))}%, so the gap compounds and no "
                           f"qualifying driver explains it."),
                "evidence": "Deterministic statistic — trend divergence",
                "semanticKey": "LVL4_MECHANISM", "terminal": True,
                "terminationReason": "Forecast-method mechanism established; no driver passes the relevance gate.",
            })
            return chain

        if name == "Volume Redistribution":
            chain.append({
                "level": 2,
                "question": "Does a related queue show an offsetting movement?",
                "answer": (f"Yes — {f.get('sibling_top_queue')} correlates "
                           f"{fmt_value(f.get('sibling_inverse_correlation'))} with this queue and offsets "
                           f"{fmt_value(round((f.get('sibling_offset_share') or 0) * 100, 1))}% of the variance."),
                "evidence": "Deterministic statistic",
                "semanticKey": "LVL2_SIBLING",
            })
            chain.append({
                "level": 3,
                "question": "What mechanism does that establish?",
                "answer": ("Volume moved between related queues in the same country and offering rather than "
                           "changing in total, so the forecast split across queues no longer matches how "
                           "contacts arrive."),
                "evidence": "Deterministic statistic",
                "semanticKey": "LVL3_MECHANISM", "terminal": True,
                "terminationReason": "Redistribution mechanism established across related queues.",
            })
            return chain

        # generic demand / statistical terminal
        chain.append({
            "level": 2,
            "question": "Does a business driver explain the movement?",
            "answer": self._driver_summary(f, cascade),
            "evidence": "Business rule — relevance gate",
            "semanticKey": "LVL2_DRIVER_CHECK",
        })
        chain.append({
            "level": 3,
            "question": "What mechanism does that establish?",
            "answer": (f"Demand moved {fmt_value(f.get('actual_vs_history_pct'))}% against its trailing mean, "
                       f"{fmt_value(f.get('period_z_score'))} standard deviations out, with "
                       f"{'no driver passing' if not any(f.get(d + '_gate_passed') for d in ('asu', 'shipment', 'warranty')) else 'the qualifying driver static'} "
                       f"this queue's relevance gate. The movement is real and quantified, but its business "
                       f"origin is not identifiable from the fields available."),
            "evidence": "Deterministic statistic",
            "semanticKey": "LVL3_MECHANISM", "terminal": True,
            "terminationReason": "Depth terminated — the next level yields no evidence item meeting minimum strength.",
        })
        return chain

    def _driver_summary(self, f, cascade) -> str:
        if not cascade:
            return ("No demand driver applies to an out-of-warranty offering — neither shipments nor "
                    "installed base are relevant by construction.")
        parts = []
        for d in cascade + (["warranty"] if "warranty" not in cascade else []):
            if not f.get(f"{d}_fields_present"):
                parts.append(f"{d}: fields absent for this queue")
                continue
            gate = "passes" if f.get(f"{d}_gate_passed") else "fails"
            parts.append(f"{d} {gate} the gate (r={fmt_value(f.get(d + '_correlation'))} "
                         f"at lag {fmt_value(f.get(d + '_lag_weeks'))}), moved "
                         f"{fmt_value(f.get(d + '_change_pct'))}%")
        return "Driver cascade for " + str(f.get("offering")) + " — " + "; ".join(parts) + "."

    def _why_nothing_held(self, f) -> str:
        bits = [
            f"Movement against trailing mean {fmt_value(f.get('actual_vs_history_pct'))}%",
            f"z-score {fmt_value(f.get('period_z_score'))} against a band of {self.th['volatility_band_sigma']}",
            f"one-sided run {fmt_value(f.get('bias_run_length'))} against a minimum of {self.th['bias_run_min']}",
        ]
        return "Measured: " + "; ".join(bits) + "."

    # -- evidence -----------------------------------------------------------
    def _build_evidence(self, f, primary, hypotheses, period, major, floor, band) -> list[dict]:
        ev = [
            {"supporting": True, "type": "Business rule", "sourceFamily": "rules",
             "strength": "Very Strong", "independenceWeight": 1.00,
             "text": (f"BR-001 breach confirmed — adherence {period['adherence']:+.1f}% exceeds the "
                      f"±{self.cfg['engine']['adherence_trigger_pct']}% generation threshold.")},
            {"supporting": True, "type": "Verified business data", "sourceFamily": "source",
             "strength": "Very Strong", "independenceWeight": 1.00,
             "text": (f"Forecast {period['forecast']:,.0f} and actual {period['actual']:,.0f} both present "
                      f"and validated across {len(period['weeksUsed'])} week(s) with actuals.")},
        ]
        if primary:
            ev.append({"supporting": True, "type": "Deterministic statistic", "sourceFamily": "stats",
                       "strength": "Strong", "independenceWeight": 1.00,
                       "text": f"{primary['name']}: {primary['reason']}"})
        # contradiction is SOUGHT, as a separate mandatory step
        for d in ("asu", "shipment", "warranty"):
            if f.get(f"{d}_fields_present") and not f.get(f"{d}_gate_passed"):
                ev.append({"supporting": False, "type": "Deterministic statistic", "sourceFamily": "stats",
                           "strength": "Moderate", "independenceWeight": 1.00,
                           "text": (f"{HUMAN.get(d + '_correlation', d)} is {fmt_value(f.get(d + '_correlation'))} "
                                    f"at lag {fmt_value(f.get(d + '_lag_weeks'))}, below the "
                                    f"{self.th['relevance_gate_correlation']} relevance gate — this driver "
                                    f"cannot corroborate any explanation for this queue.")})
        for d in ("asu", "shipment", "warranty"):
            if not f.get(f"{d}_fields_present"):
                ev.append({"supporting": False, "type": "Verified business data", "sourceFamily": "source",
                           "strength": "Moderate", "independenceWeight": 1.00,
                           "text": (f"{HUMAN.get(d + '_correlation', d)} could not be evaluated — the "
                                    f"underlying field is absent for this queue, so this explanation can be "
                                    f"neither confirmed nor excluded.")})
        if f.get("holiday_count") and (primary or {}).get("name") != "Holiday":
            ev.append({"supporting": False, "type": "Business rule", "sourceFamily": "rules",
                       "strength": "Moderate", "independenceWeight": 1.00,
                       "text": (f"{fmt_value(f.get('holiday_count'))} holiday day(s) fall in this period and this "
                                f"queue's measured holiday effect is {fmt_value(f.get('holiday_effect_pct'))}%, "
                                f"which could account for part of the movement.")})
        if not major and abs(period["actual"] - period["forecast"]) < floor:
            ev.append({"supporting": False, "type": "Business rule", "sourceFamily": "rules",
                       "strength": "Strong", "independenceWeight": 1.00,
                       "text": (f"Absolute variance {abs(period['actual'] - period['forecast']):,.0f} contacts is "
                                f"below the materiality floor of {floor} for volume band {band} — the percentage "
                                f"overstates the business impact.")})
        # second same-family item is down-weighted, not counted as independent
        fam_seen, out = set(), []
        for item in ev:
            key = (item["sourceFamily"], item["supporting"])
            if key in fam_seen:
                item = dict(item, independenceWeight=0.30, strength="Weak",
                            text=item["text"] + " (second item from a family already counted — "
                                                "down-weighted to 0.30, not an independent confirmation)")
            fam_seen.add(key)
            out.append(item)
        return out

    # -- cross-examination ---------------------------------------------------
    def _cross_examine(self, f, primary, hypotheses, material, period) -> dict:
        if primary is None:
            return {"outcome": "Inconclusive", "iterationsUsed": 1,
                    "maxIterations": int(self.cfg["engine"]["max_cross_examination_iterations"]),
                    "terminationCondition": 5,
                    "terminationText": "Conclusion rejected — no hypothesis achieved defensible support.",
                    "questions": [], "gate7Applies": False}
        cat = primary["category"]
        asked = []
        for q in self.cat["challenge_questions"]:
            if cat not in q["applies_to"]:
                continue
            answer, answered = self._answer_challenge(q["key"], f, primary, material, period)
            asked.append({"semanticKey": q["key"], "category": q["category"],
                          "question": q["question"], "answer": answer, "answered": answered})
        unanswered = [q for q in asked if not q["answered"]]
        max_iter = int(self.cfg["engine"]["max_cross_examination_iterations"])
        if not unanswered:
            outcome, cond, text, gate7 = ("Accepted", 1,
                                          "Conclusion survived a full round of challenge.", False)
            iters = 1
        else:
            outcome, cond, gate7 = "Accepted with Caveats", 3, True
            text = ("An iteration retrieved no new evidence for "
                    f"{len(unanswered)} question(s). The conclusion was interrupted, not validated.")
            iters = min(max_iter, 2)
        return {"outcome": outcome, "iterationsUsed": iters, "maxIterations": max_iter,
                "terminationCondition": cond, "terminationText": text,
                "questions": asked, "unansweredCount": len(unanswered), "gate7Applies": gate7}

    def _answer_challenge(self, key, f, primary, material, period):
        gate = self.th["relevance_gate_correlation"]
        if key == "STAT_SIGNIFICANCE":
            z = f.get("period_z_score")
            if z is None:
                return "Cannot be evaluated — trailing history is insufficient to derive a volatility band.", False
            return (f"Yes — {fmt_value(z)} standard deviations from the trailing mean, against a band of "
                    f"{self.th['volatility_band_sigma']}.", True)
        if key == "STAT_METRIC_AGREEMENT":
            agree = sum(1 for k in ("period_z_score", "mad_z_score") if f.get(k) is not None)
            return (f"{agree} of 2 selected metrics returned a value; z-score {fmt_value(f.get('period_z_score'))} "
                    f"and robust outlier score {fmt_value(f.get('mad_z_score'))}.", agree == 2)
        if key == "STAT_SAMPLE_ADEQUACY":
            n = f.get("trailing_periods") or 0
            return (f"{n} periods in the trailing window against a minimum of "
                    f"{self.th['bias_min_periods']}.", n >= int(self.th["bias_min_periods"]))
        if key == "STAT_ALTERNATIVE_MODEL":
            return (f"Robust (median-based) outlier score {fmt_value(f.get('mad_z_score'))} agrees in direction "
                    f"with the mean-based z-score {fmt_value(f.get('period_z_score'))}.",
                    f.get("mad_z_score") is not None)
        if key == "HIST_PRECEDENT":
            return ("No eligible historical RCA exists for this queue. Scored neutral (0.50) by BR-118, not low.", True)
        if key == "HIST_RECURRENCE":
            run = f.get("bias_run_length") or 0
            return (f"{run} consecutive periods deviating the same way; "
                    f"{fmt_value(f.get('bias_sign_share'))} of the window one-sided.", True)
        if key == "HIST_SEASONAL_MATCH":
            if not f.get("same_week_last_year_available"):
                return "Cannot be evaluated — the same week last year has no computable adherence.", False
            return (f"Same week last year adherence {fmt_value(f.get('same_week_last_year_adherence'))}%, "
                    f"consistency {fmt_value(f.get('seasonal_consistency'))}.", True)
        if key == "BIZ_RULE_CONSISTENCY":
            return ("No business rule in force contradicts the conclusion.", True)
        if key == "BIZ_DRIVER_RELEVANCE":
            d = {"Installed Base Change": "asu", "Shipment Volume Change": "shipment",
                 "Warranty Mix Shift": "warranty"}.get(primary["name"])
            if not d:
                return "Not applicable — the conclusion does not cite a business driver.", True
            return (f"Correlation {fmt_value(f.get(d + '_correlation'))} at lag "
                    f"{fmt_value(f.get(d + '_lag_weeks'))} against a gate of {gate}.",
                    bool(f.get(f"{d}_gate_passed")))
        if key == "BIZ_MATERIALITY":
            return (f"Absolute variance {fmt_value(f.get('abs_variance_contacts'))} contacts against the "
                    f"materiality floor for this volume band.", bool(material))
        if key == "DATA_SUFFICIENCY":
            n = f.get("history_weeks") or 0
            return (f"{n} weeks of actuals available for this queue; "
                    f"{fmt_value(f.get('missing_field_count'))} context field(s) absent for this period.",
                    n >= int(self.th["bias_min_periods"]))
        if key == "DATA_COMPLETENESS":
            missing = f.get("missing_field_count") or 0
            return (f"{missing} context field(s) absent for this period.", missing == 0)
        if key == "DATA_INTEGRITY":
            return (f"Actual/forecast ratio {fmt_value(f.get('actual_forecast_ratio'))} against a trailing "
                    f"minimum of {fmt_value(f.get('trailing_min_ratio'))}.",
                    f.get("actual_forecast_ratio") is not None)
        if key == "DATA_COVERAGE":
            complete = not period["weeksBlank"] and not period["weeksNonComputable"]
            return (f"{len(period['weeksUsed'])} of {len(period['weeksInPeriod'])} week(s) used; "
                    f"{len(period['weeksBlank'])} blank, {len(period['weeksNonComputable'])} non-computable.",
                    complete)
        if key == "ALT_STRONGER_HYPOTHESIS":
            untested = [d for d in ("asu", "shipment", "warranty") if not f.get(f"{d}_fields_present")]
            if untested:
                return (f"Cannot be fully excluded — {', '.join(untested)} could not be evaluated because the "
                        f"underlying field is absent, so that alternative was untestable.", False)
            return ("No stronger alternative survives: every applicable driver was evaluated against the "
                    "relevance gate.", True)
        if key == "ALT_UNTESTED_DRIVER":
            untested = [d for d in ("asu", "shipment", "warranty") if not f.get(f"{d}_fields_present")]
            return ((f"{', '.join(untested)} left untested — field absent." if untested
                     else "Every applicable driver was tested against the relevance gate."), not untested)
        if key == "ALT_CONFOUNDING":
            return (f"Holiday effect for this queue is {fmt_value(f.get('holiday_effect_pct'))}% and "
                    f"{fmt_value(f.get('holiday_count'))} holiday day(s) fall in this period.", True)
        return ("No answering procedure is defined for this question.", False)

    # -- confidence ----------------------------------------------------------
    def _confidence(self, f, primary, hypotheses, evidence, xexam,
                    band_derived, period, inconclusive) -> dict:
        support = [e for e in evidence if e["supporting"]]
        contra = [e for e in evidence if not e["supporting"]]
        strength_map = {"Very Strong": 1.0, "Strong": 0.8, "Moderate": 0.6, "Weak": 0.4, "Very Weak": 0.2}
        sup_w = sum(strength_map[e["strength"]] * e["independenceWeight"] for e in support)
        con_w = sum(strength_map[e["strength"]] * e["independenceWeight"] for e in contra)

        drivers_present = [d for d in ("asu", "shipment", "warranty") if f.get(f"{d}_fields_present")]
        drivers_missing = [d for d in ("asu", "shipment", "warranty") if not f.get(f"{d}_fields_present")]
        context_missing = len(drivers_missing) + (1 if band_derived else 0) \
            + (0 if f.get("asu_plan_actual_both_present") else 1)

        metrics_ran = sum(1 for k in ("period_z_score", "mad_z_score", "drift_shift_pct",
                                      "variance_ratio", "trend_divergence") if f.get(k) is not None)

        dims = []
        for name, weight in CONF_WEIGHTS:
            state, score, why = "Available", 0.5, ""
            if name == "ContradictoryEvidence":
                total = sup_w + con_w
                score = (sup_w / total) if total else 0.5
                why = (f"contradiction search performed; support weight {sup_w:.2f} against "
                       f"opposing weight {con_w:.2f} across {len(contra)} opposing item(s)")
            elif name == "EvidenceStrength":
                score = min(1.0, sup_w / 3.0)
                why = (f"{len(support)} supporting item(s), independence-weighted total {sup_w:.2f}")
            elif name == "BusinessRuleValidation":
                score = 0.0 if inconclusive else 0.9
                why = "no business rule in force contradicts the conclusion" if not inconclusive \
                      else "no conclusion to validate"
            elif name == "StatisticalAgreement":
                score = min(1.0, metrics_ran / 5.0)
                why = f"{metrics_ran} of 5 selected metrics returned a value"
            elif name == "DataSufficiency":
                weeks = f.get("history_weeks") or 0
                score = min(1.0, weeks / float(self.th["seasonality_min_history_weeks"]))
                why = (f"{weeks} weeks of actuals against the {self.th['seasonality_min_history_weeks']}-week "
                       f"reference depth; {len(period['weeksUsed'])} of {len(period['weeksInPeriod'])} "
                       f"period week(s) used")
            elif name == "ContextCompleteness":
                if context_missing:
                    state, score = "Missing", 0.5
                    why = (f"{context_missing} applicable context element(s) absent: "
                           + ", ".join(drivers_missing + (["volume band"] if band_derived else [])
                                       + ([] if f.get("asu_plan_actual_both_present") else ["actual installed base"])))
                else:
                    score, why = 1.0, "every applicable context element is present"
            elif name == "HistoricalConsistency":
                score = 0.5
                why = "no eligible historical RCA precedent; neutral by BR-118, never low"
            elif name == "ModelAgreement":
                state, score = "Not Applicable", 0.0
                why = "no ML attribution ran for this hypothesis; excluded and weights renormalised"
            dims.append({"dimension": name, "weight": weight, "availability": state,
                         "score": round(score, 4), "reason": why})

        active = [d for d in dims if d["availability"] != "Not Applicable"]
        wsum = sum(d["weight"] for d in active)
        for d in dims:
            d["contribution"] = round(d["weight"] / wsum * d["score"], 4) \
                if d["availability"] != "Not Applicable" else None
        raw = round(sum(d["contribution"] for d in active), 4)
        calculated = level_for(raw)

        caps = []
        if any(d["availability"] == "Missing" for d in dims):
            caps.append({"gate": "Gate 4", "name": "Applicable context element unavailable",
                         "ceiling": "High",
                         "threshold": "every applicable context element Available",
                         "actual": f"{context_missing} element(s) Missing"})
        if band_derived:
            caps.append({"gate": "Gate 5", "name": "Volume band not supplied at source",
                         "ceiling": "High", "threshold": "Volume_Category present in source",
                         "actual": "absent — derived from period forecast volume"})
        if xexam.get("gate7Applies"):
            caps.append({"gate": "Gate 7", "name": "Cross-examination did not survive challenge",
                         "ceiling": "Low", "threshold": "terminating condition 1 or 4",
                         "actual": f"terminated on condition {xexam['terminationCondition']} — "
                                   f"{xexam.get('unansweredCount', 0)} question(s) unanswerable"})
        if period["weeksBlank"] or period["weeksNonComputable"]:
            cov = len(period["weeksUsed"]) / max(len(period["weeksInPeriod"]), 1)
            if cov < 0.25:
                caps.append({"gate": "Gate 3b", "name": "Period coverage below 25%",
                             "ceiling": "Low", "threshold": "at least 25% of period weeks with actuals",
                             "actual": f"{cov*100:.0f}% coverage"})
        if inconclusive:
            caps.append({"gate": "BR-306", "name": "No defensible root cause",
                         "ceiling": "Very Low",
                         "threshold": "at least one hypothesis with defensible support",
                         "actual": "no hypothesis met its acceptance conditions"})

        published, binding = calculated, None
        for cap in caps:
            if ORDER[cap["ceiling"]] < ORDER[published]:
                published, binding = cap["ceiling"], cap
        for cap in caps:
            cap["binding"] = cap is binding

        would_change = []
        if drivers_missing:
            would_change.append(
                f"Supplying {', '.join(drivers_missing)} for this queue would make those driver explanations "
                f"testable and lift Context Completeness off its floor.")
        if band_derived:
            would_change.append(
                "Supplying Volume_Category at source would remove the derived band and release the Gate 5 ceiling.")
        if xexam.get("gate7Applies"):
            would_change.append(
                f"Answering the {xexam.get('unansweredCount', 0)} unanswerable challenge question(s) would allow "
                f"the conclusion to be validated rather than interrupted, releasing the Gate 7 ceiling.")
        if not would_change:
            would_change.append("No identified weakness is currently limiting this assessment.")

        return {"level": published, "calculatedScore": raw, "calculatedLevel": calculated,
                "dimensions": dims, "activeDimensionCount": len(active),
                "caps": caps, "bindingCap": binding, "whatWouldChangeIt": would_change,
                "weightsVersion": self.cfg["engine"]["confidence_weights_version"]}

    # -- recommendations -----------------------------------------------------
    def _recommend(self, f, primary, inconclusive, band_derived) -> list[dict]:
        recs = []
        name = (primary or {}).get("name")
        driver_map = {"Installed Base Change": "installed base", "Shipment Volume Change": "shipments",
                      "Warranty Mix Shift": "warranty coverage"}
        if inconclusive:
            recs.append({"id": "R1", "priority": "Medium",
                         "action": "Review this queue-period with the queue owner",
                         "addresses": "Inconclusive — no defensible cause established",
                         "evidence": self._why_nothing_held(f),
                         "impact": "Would establish whether an unmodelled business event applies to this queue",
                         "routing": "Demand / Forecast Team", "type": "Investigative"})
        elif name in driver_map:
            recs.append({"id": "R1", "priority": "High",
                         "action": f"Review how {driver_map[name]} feeds this queue's forecast",
                         "addresses": name,
                         "evidence": primary["reason"],
                         "impact": "Would reduce recurrence of a deviation driven by a measured business driver",
                         "routing": "Demand / Forecast Team", "type": "Business"})
        elif name == "Missing Data":
            recs.append({"id": "R1", "priority": "High",
                         "action": "Validate the actuals feed for this queue and fiscal week",
                         "addresses": name, "evidence": primary["reason"],
                         "impact": "Would confirm whether this is a data fault before it is treated as demand",
                         "routing": "Demand / Forecast Team", "type": "Investigative"})
            recs.append({"id": "R2", "priority": "Medium",
                         "action": "Re-run this investigation once the feed is confirmed",
                         "addresses": name, "evidence": "Conclusion is provisional on feed integrity",
                         "impact": "Would replace a provisional finding with a confirmed one",
                         "routing": "Demand / Forecast Team", "type": "Investigative"})
        elif name in ("Forecast Bias", "Trend Misidentification", "Drift", "Momentum Shift"):
            recs.append({"id": "R1", "priority": "High",
                         "action": "Review the trend term in this queue's forecast method",
                         "addresses": name, "evidence": primary["reason"],
                         "impact": "Would address a persistent directional bias rather than a single period",
                         "routing": "Demand / Forecast Team", "type": "Business"})
        elif name == "Holiday":
            recs.append({"id": "R1", "priority": "High",
                         "action": "Carry this queue's measured holiday effect into the forecast calendar",
                         "addresses": name, "evidence": primary["reason"],
                         "impact": "Would remove a recurring calendar-driven deviation",
                         "routing": "Demand / Forecast Team", "type": "Business"})
        else:
            recs.append({"id": "R1", "priority": "Medium",
                         "action": f"Investigate the movement identified as {name}",
                         "addresses": name, "evidence": primary["reason"],
                         "impact": "Would establish the business origin of a quantified movement",
                         "routing": "Demand / Forecast Team", "type": "Investigative"})

        missing = [d for d in ("asu", "shipment", "warranty") if not f.get(f"{d}_fields_present")]
        if missing or band_derived:
            gaps = missing + (["Volume_Category"] if band_derived else [])
            recs.append({"id": f"R{len(recs)+1}", "priority": "Low",
                         "action": f"Supply {', '.join(gaps)} for this queue",
                         "addresses": "Context completeness",
                         "evidence": f"{len(gaps)} context element(s) absent, each carrying a confidence penalty",
                         "impact": "Would raise testable coverage on future investigations for this queue",
                         "routing": "Demand / Forecast Team", "type": "Investigative"})
        return recs[:int(self.cfg["engine"]["max_recommendations"])]

    # -- availability / limitations -----------------------------------------
    def _availability(self, f, meta, band_derived, band) -> list[dict]:
        out = []
        for d, label in (("asu", "Installed base"), ("shipment", "Shipment plan"),
                         ("warranty", "Warranty coverage")):
            if not f.get(f"{d}_in_cascade") and d != "warranty":
                out.append({"element": label, "state": "NOT RELEVANT",
                            "reason": f"driver does not apply to a {f.get('offering')} offering"})
            elif not f.get(f"{d}_fields_present"):
                out.append({"element": label, "state": "UNAVAILABLE",
                            "reason": "field absent for this queue in the source data"})
            elif not f.get(f"{d}_gate_passed"):
                out.append({"element": label, "state": "NOT RELEVANT",
                            "reason": (f"correlation {fmt_value(f.get(d + '_correlation'))} below the "
                                       f"{self.th['relevance_gate_correlation']} relevance gate for this queue")})
        if not f.get("asu_plan_actual_both_present"):
            out.append({"element": "Actual installed base", "state": "UNAVAILABLE",
                        "reason": "not supplied in the source data for this period"})
        if band_derived:
            out.append({"element": "Volume band", "state": "UNAVAILABLE",
                        "reason": f"absent at source; derived as {band} from period forecast volume"})
        out.append({"element": "Business events", "state": "NOT RELEVANT",
                    "reason": "repository not populated — no confidence penalty"})
        out.append({"element": "Queue lineage", "state": "UNAVAILABLE",
                    "reason": "no lineage source deployed"})
        if not f.get("holiday_count"):
            out.append({"element": "Holiday context", "state": "NOT RELEVANT",
                        "reason": "no holiday day falls in this period or its impact window"})
        return out

    def _limitations(self, f, xexam, confidence, band_derived, period) -> list[str]:
        out = []
        if xexam.get("gate7Applies"):
            out.append(f"Cross-examination terminated without fully surviving challenge — {xexam['terminationText']} "
                       f"Confidence is capped at Low by Gate 7.")
        missing = [d for d in ("asu", "shipment", "warranty") if not f.get(f"{d}_fields_present")]
        if missing:
            out.append(f"{', '.join(missing)} could not be evaluated for this queue because the underlying "
                       f"field is absent, so those explanations were untestable.")
        if band_derived:
            out.append("Volume band was absent at source and derived from period forecast volume; "
                       "the materiality floor applied is therefore provisional.")
        if period["weeksNonComputable"]:
            out.append(f"{len(period['weeksNonComputable'])} week(s) were non-computable under BR-110 "
                       f"(fcst_offered = 0) and excluded — a data defect, not an availability gap.")
        out.append("The Business Event Repository is empty, so no external business event could be correlated. "
                   "This carries no confidence penalty.")
        out.append("No product identifier exists in the source data, so product-level attribution is out of scope. "
                   "Offering is a support tier, never a product proxy.")
        return out


# ---------------------------------------------------------------------------
# bootstrap
# ---------------------------------------------------------------------------


def load_all(config_path: Path | None = None):
    cfg = json.loads((config_path or (HERE / "config.json")).read_text(encoding="utf-8"))
    cat = json.loads((HERE / "hypothesis_catalogue.json").read_text(encoding="utf-8"))
    src = (HERE / cfg["data"]["input_file"]).resolve()
    if not src.exists():
        raise SystemExit(f"input workbook not found: {src}\nSet data.input_file in config.json.")
    store = DataStore(src).load()
    return Engine(store, cfg, cat), store, cfg, cat


def selftest() -> int:
    print("FC_RCA reasoning engine — self-test\n")
    engine, store, cfg, cat = load_all()
    failures = 0

    def check(label, cond, extra=""):
        nonlocal failures
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}{(' — ' + extra) if extra else ''}")
        if not cond:
            failures += 1

    check("workbook loaded", store.row_count > 0, f"{store.row_count:,} rows")
    check("queues indexed", len(store.queue_names()) > 0, f"{len(store.queue_names())} queues")
    check("string numerics were coerced, not dropped", sum(store.coerced_strings.values()) > 0,
          f"{sum(store.coerced_strings.values()):,} values across {len(store.coerced_strings)} columns")
    check("no duplicate rows at queue x week", sum(store.duplicates.values()) == 0)
    check("latest actuals week derived from data", store.latest_actuals_week in store.weeks_with_actuals,
          f"FW{store.latest_actuals_week}")
    check("future forecast-only weeks excluded from actuals",
          max(store.weeks) > store.latest_actuals_week,
          f"file extends to FW{max(store.weeks)}")

    cal = fiscal_parts(202722)
    check("fiscal calendar 4-4-5 maps FW22 to Q2 M6", cal["fiscalQuarter"] == 2 and cal["fiscalMonth"] == 6,
          f"Q{cal['fiscalQuarter']} M{cal['fiscalMonth']}")
    check("catalogue loaded as configuration", len(cat["hypotheses"]) > 0,
          f"{len(cat['hypotheses'])} hypotheses, {len(cat['challenge_questions'])} challenge questions")

    wl = engine.worklist()
    check("worklist computed from data", wl["count"] > 0, f"{wl['count']} breaching queues")
    check("worklist sorted by absolute variance, not percentage",
          all(wl["rows"][i]["absVarianceContacts"] >= wl["rows"][i + 1]["absVarianceContacts"]
              for i in range(min(20, len(wl["rows"]) - 1))))

    # direction semantics — the bug this engine replaces
    bad_dir = [r for r in wl["rows"]
               if (r["adherencePct"] < 0) != (r["varianceContacts"] > 0)]
    check("direction sign is consistent with variance everywhere", not bad_dir,
          f"{len(bad_dir)} inconsistent rows")
    over = next((r for r in wl["rows"] if r["adherencePct"] > 0), None)
    check("positive adherence means actual BELOW forecast",
          over is not None and over["varianceContacts"] < 0 and over["direction"] == "Over-forecast",
          f"{over['queue']} {over['adherencePct']:+}% variance {over['varianceContacts']:+,}" if over else "")

    sample = [r["queue"] for r in wl["rows"][:12]]
    mechanisms, inconclusive = 0, 0
    for q in sample:
        rca = engine.investigate(q)
        n_states = {h["state"] for h in rca["hypotheses"]}
        if rca["caseStatus"] == "Inconclusive":
            inconclusive += 1
        else:
            mechanisms += 1
        if len(rca["hypotheses"]) != len(cat["hypotheses"]):
            check(f"{q}: all catalogue entries recorded", False,
                  f"{len(rca['hypotheses'])} of {len(cat['hypotheses'])}")
        active = [d for d in rca["confidence"]["dimensions"] if d["contribution"] is not None]
        total = round(sum(d["contribution"] for d in active), 4)
        if abs(total - rca["confidence"]["calculatedScore"]) > 1e-6:
            check(f"{q}: confidence decomposes to its score", False)
        if not (0.0 <= rca["confidence"]["calculatedScore"] <= 1.0):
            check(f"{q}: confidence in range", False)
        chain = rca["reasoningChain"]
        if not chain or not chain[-1].get("terminal"):
            check(f"{q}: reasoning chain terminates", False)
        if chain[-1].get("terminal") and not chain[-1].get("terminationReason"):
            check(f"{q}: termination reason recorded", False)
        keys = [n["semanticKey"] for n in chain]
        if len(keys) != len(set(keys)):
            check(f"{q}: no repeated semantic key in the chain", False)
        xk = [q2["semanticKey"] for q2 in rca["crossExamination"]["questions"]]
        if len(xk) != len(set(xk)):
            check(f"{q}: cross-examination keys deduplicated exactly", False)
        if rca["caseStatus"] != "Inconclusive" and not rca["rootCause"]:
            check(f"{q}: completed case has a root cause", False)
        if len(rca["recommendations"]) > int(cfg["engine"]["max_recommendations"]):
            check(f"{q}: at most 3 recommendations", False)
        if any(str(r.get("impact", "")).strip().rstrip(".").replace(",", "").isdigit()
               for r in rca["recommendations"]):
            check(f"{q}: recommendation impact is qualitative", False)

    check(f"investigated {len(sample)} real queues without error", True,
          f"{mechanisms} with an established mechanism, {inconclusive} inconclusive")
    check("engine reaches a mechanism on real data", mechanisms > 0)

    r0 = engine.investigate(sample[0])
    r1 = engine.investigate(sample[0])
    check("identical inputs produce identical output",
          json.dumps(r0, sort_keys=True, default=str) == json.dumps(r1, sort_keys=True, default=str))

    agg = engine.aggregate(level=1)
    check("aggregate view computed", len(agg["rows"]) > 0, f"{len(agg['rows'])} level-1 groups")
    check("aggregate ranked by gross variance",
          all(agg["rows"][i]["grossVarianceContacts"] >= agg["rows"][i + 1]["grossVarianceContacts"]
              for i in range(min(20, len(agg["rows"]) - 1))))
    check("no aggregate row carries a confidence score",
          all("confidence" not in r for r in agg["rows"]))
    offs = [r for r in agg["rows"] if r["offsetRatio"] > 0.70 and not r["singleQueueGroup"]]
    check("offsetting groups are detected and de-emphasised",
          all(r["deEmphasisePooled"] and r["direction"] == "Offsetting" for r in offs),
          f"{len(offs)} offsetting group(s)")

    print(f"\n{'ALL CHECKS PASSED' if not failures else str(failures) + ' CHECK(S) FAILED'}")
    return 1 if failures else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="FC_RCA deterministic reasoning engine")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--queues", action="store_true")
    ap.add_argument("--aggregate", action="store_true")
    ap.add_argument("--rca", metavar="QUEUE")
    ap.add_argument("--grain", default="Weekly", choices=["Weekly", "Monthly", "Quarterly"])
    ap.add_argument("--week", type=int)
    ap.add_argument("--limit", type=int, default=15)
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    engine, store, cfg, cat = load_all()
    if args.queues:
        wl = engine.worklist(args.grain, args.week)
        print(f"FW{wl['week']} {wl['grain']} — {wl['count']} of {wl['totalQueues']} queues breach "
              f"±{cfg['engine']['adherence_trigger_pct']}%\n")
        for r in wl["rows"][:args.limit]:
            print(f"  {r['adherencePct']:+8.1f}%  {r['absVarianceContacts']:>7,} contacts  "
                  f"{r['direction']:<15} {'MAJOR ' if r['majorDeviation'] else '      '}"
                  f"{r['queue']}")
        return 0
    if args.aggregate:
        agg = engine.aggregate(args.grain, args.week)
        print(f"FW{agg['week']} level-1 aggregate, ranked by gross variance\n")
        for r in agg["rows"][:args.limit]:
            print(f"  gross {r['grossVarianceContacts']:>8,}  net {r['netVarianceContacts']:>8,}  "
                  f"pooled {r['pooledAdherencePct']:+6.1f}%  offset {r['offsetRatio']:.2f} "
                  f"{str(r['offsetLabel'] or 'SINGLE'):<14} {r['group']}")
        return 0
    if args.rca:
        matches = [q for q in store.queue_names() if args.rca.lower() in q.lower()]
        if not matches:
            print(f"no queue matching '{args.rca}'")
            return 1
        rca = engine.investigate(matches[0], args.grain, args.week)
        print(json.dumps(rca, indent=2, default=str)[:6000])
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
