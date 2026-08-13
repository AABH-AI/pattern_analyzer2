# -*- coding: utf-8 -*-
"""
Data-granularity gate -- what the source data can and cannot support, checked rather than assumed.

WHY THIS MODULE EXISTS
----------------------
Spec sections 18, 19 and 31 ask for weekend and day-of-week diagnostics, and then immediately
forbid inventing them: "Do not manufacture weekend evidence." The two instructions are only
compatible if something INSPECTS the data first and reports what is possible. That is this module.
It is the gate that makes the honest answer available to the report, so weekend causality can
never be inferred from weekly totals.

WHAT THIS TABLE ACTUALLY PROVIDES (verified, not assumed)
---------------------------------------------------------
The check runs against the real rows every time, so it stays correct if the schema changes. On
`dbo.Input_To_ML_Full` as it stands today it finds:

    Actual_Offered / fcst_offered      one value per FISCAL WEEK        -> weekly grain
    Week_Ending                        the date the fiscal week ends    -> one date per week
    Monday .. Sunday                   0/1 HOLIDAY FLAGS, per day       -> NOT daily volumes
    rows per fiscal week               exactly one                      -> no intra-week detail

So there is no daily actual, no daily forecast, and no day-of-week volume profile. Weekend softness
CANNOT be isolated from a weekly total: a week containing a quiet Saturday and a week containing a
busy one are the same single number. Any statement that "the weekend caused the miss" would be
fabricated, and this module makes that explicit.

THE PART THAT *IS* POSSIBLE
---------------------------
The Monday..Sunday holiday flags are day-level information even though volumes are not. They reveal
WHICH DAY a holiday fell on, which supports the genuinely testable half of spec section 19:

    a holiday on a Saturday or Sunday   -> lands on days that may already be non-working
    a holiday on a Friday or a Monday   -> adjoins the weekend, extending a closure
    a holiday mid-week                  -> an isolated interruption

That distinction changes the expected size of a holiday effect and is reported for use by the
holiday analysis. It is described as calendar STRUCTURE, never as a measured weekend volume effect.

DEPENDENCIES: standard library only.
"""

DAY_COLUMNS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
WEEKEND_DAYS = ("Saturday", "Sunday")

# Column names that would indicate a genuine daily grain if the source ever provided one. Checked
# by name AND by shape (more than one row per fiscal week), so a rename does not defeat the check.
DAILY_ACTUAL_HINTS = ("daily_actual", "actual_daily", "actual_offered_daily", "date", "Date",
                      "activity_date", "contact_date")
DAILY_FORECAST_HINTS = ("daily_forecast", "forecast_daily", "fcst_offered_daily")

WEEKEND_LIMITATION = ("Weekend impact cannot be isolated from fiscal-week totals because "
                      "day-level actual and forecast data is unavailable in the source.")


def _num(v):
    if v is None or v is True or v is False:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _looks_like_flags(values):
    """True when every value is 0 or 1 -- the signature of a flag column, not a volume column.

    This is what separates "Monday is a holiday flag" from "Monday is Monday's contact volume".
    A volume column on a queue handling ~90 contacts a week would not be all zeros and ones.
    """
    seen = [v for v in values if v is not None]
    if not seen:
        return None
    return all(v in (0.0, 1.0) for v in seen)


def analyse(history, target_fields=None):
    """Inspect the available data and report which analyses it can and cannot support.

    `history` is the raw SQL history block; `target_fields` is the target row's fields. Both are
    inspected because the history block carries a narrower column set than the posted row.
    """
    rows = [r for r in (history or []) if r]
    fields = dict(target_fields or {})
    columns = set(fields.keys())
    for r in rows:
        columns |= set(r.keys())

    # --- rows per fiscal week: the shape test for daily data ---
    per_week = {}
    for r in rows:
        wk = _num(r.get("Fiscal_Week"))
        if wk is not None:
            per_week[int(wk)] = per_week.get(int(wk), 0) + 1
    max_rows_per_week = max(per_week.values()) if per_week else 0

    # --- are the day columns flags or volumes? ---
    day_columns_present = [c for c in DAY_COLUMNS if c in columns]
    day_values = []
    for c in day_columns_present:
        day_values += [_num(fields.get(c))] if c in fields else []
        day_values += [_num(r.get(c)) for r in rows if c in r]
    flags = _looks_like_flags(day_values)

    daily_actual = any(h in columns for h in DAILY_ACTUAL_HINTS if h not in ("date", "Date")) \
        or max_rows_per_week > 1
    daily_forecast = any(h in columns for h in DAILY_FORECAST_HINTS) or max_rows_per_week > 1

    grain = "daily" if max_rows_per_week > 1 else "weekly"

    capabilities = {
        "weekly_totals": bool({"Actual_Offered", "fcst_offered"} & columns),
        "week_end_date": "Week_Ending" in columns,
        "daily_actual": bool(daily_actual),
        "daily_forecast": bool(daily_forecast),
        "day_of_week_volume_profile": bool(daily_actual),
        "weekend_volume_effect": bool(daily_actual),
        "holiday_day_of_week": bool(day_columns_present) and flags is True,
    }

    limitations = []
    if not capabilities["daily_actual"]:
        limitations.append(WEEKEND_LIMITATION)
    if day_columns_present and flags is True:
        limitations.append(
            f"The columns {', '.join(day_columns_present)} are holiday flags, not daily volumes, "
            f"so they identify WHICH DAY a holiday fell on but carry no demand information.")
    elif day_columns_present and flags is False:
        limitations.append(
            f"The columns {', '.join(day_columns_present)} contain values other than 0/1, so their "
            f"meaning could not be confirmed as holiday flags; they were not used.")

    return {
        "available": True,
        "grain": grain,
        "rows_per_fiscal_week_max": max_rows_per_week,
        "weeks_inspected": len(per_week),
        "columns_seen": sorted(columns),
        "day_columns_present": day_columns_present,
        "day_columns_are_flags": flags,
        "capabilities": capabilities,
        "limitations": limitations,
        "weekend_analysis_supported": capabilities["weekend_volume_effect"],
        "weekend_statement": (None if capabilities["weekend_volume_effect"]
                              else WEEKEND_LIMITATION),
        "note": ("Checked against the actual rows on every run. If a daily source is added, "
                 "`capabilities.daily_actual` flips to true and the weekend limitation "
                 "disappears without a code change."),
    }


def holiday_day_structure(target_fields, granularity=None):
    """Which day(s) a holiday fell on, and how that relates to the weekend (spec section 19).

    Calendar STRUCTURE only -- it says a holiday adjoined the weekend, never that the weekend moved
    volume. Returns `testable: False` when the flags are unavailable or not confirmed as flags.
    """
    fields = dict(target_fields or {})
    if granularity is not None and not (granularity.get("capabilities") or {}).get(
            "holiday_day_of_week"):
        return {"testable": False,
                "reason": "the per-day holiday flags are unavailable or not confirmed as flags"}
    present = [c for c in DAY_COLUMNS if c in fields]
    if not present:
        return {"testable": False, "reason": "no per-day holiday flag columns on the target row"}

    flagged = [c for c in present if (_num(fields.get(c)) or 0) > 0]
    if not flagged:
        return {"testable": True, "holiday_days": [], "count": 0,
                "pattern": "none",
                "reading": "No holiday day is flagged within this fiscal week."}

    on_weekend = [d for d in flagged if d in WEEKEND_DAYS]
    adjoining = [d for d in flagged if d in ("Friday", "Monday")]
    if on_weekend and len(on_weekend) == len(flagged):
        pattern = "holiday_on_weekend"
        reading = (f"The holiday day(s) fall on {', '.join(on_weekend)}, which may already be "
                   f"non-working for this queue, so the effect on contactable days can be smaller "
                   f"than the holiday count suggests.")
    elif adjoining:
        pattern = "holiday_adjoining_weekend"
        reading = (f"The holiday falls on {', '.join(adjoining)}, adjoining the weekend and "
                   f"extending the closure across consecutive days.")
    elif len(flagged) > 1:
        pattern = "multiple_holiday_days"
        reading = (f"{len(flagged)} holiday days fall in this week ({', '.join(flagged)}), "
                   f"reducing contactable days more than a single holiday would.")
    else:
        pattern = "midweek_holiday"
        reading = (f"The holiday falls on {flagged[0]}, an isolated mid-week interruption.")

    return {"testable": True, "holiday_days": flagged, "count": len(flagged),
            "on_weekend": on_weekend, "adjoining_weekend": adjoining,
            "pattern": pattern, "reading": reading,
            "note": ("Derived from the per-day holiday flags. This describes the calendar only -- "
                     "no weekend demand effect is claimed, and none can be measured at weekly "
                     "grain.")}
