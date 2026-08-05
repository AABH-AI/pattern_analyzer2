# -*- coding: utf-8 -*-
"""Fiscal calendar -- 4-4-5, with 53-week years absorbed into Q4 as 4-5-5.

Implements `FC_RCA_Definitions_and_Formulas.md` section 3.

WHY THIS MODULE EXISTS
----------------------
Nothing in the engine understood fiscal periods. `Fiscal_Week` was treated as an opaque
sortable integer, which is enough for weekly RCA and not enough for anything else:

  * Monthly and quarterly grain cannot exist without a week-to-period mapping.
  * "Period spans a fiscal month boundary" and "spans a quarter boundary" are two entries
    in the hypothesis catalogue that simply cannot be generated without it.
  * Period coverage feeds DataSufficiency in the confidence model, and coverage means
    "weeks with actuals / weeks in period" -- which needs to know how long the period is.

THE CALENDAR IS DERIVED FROM THE DATA, NOT FROM AN ANCHOR DATE
---------------------------------------------------------------
Whether a fiscal year has 52 or 53 weeks is decided by what is actually present:

    weeks_in_FY = MAX(Fiscal_Week_Number) observed for that Fiscal_Year

MAX, deliberately, and not COUNT(DISTINCT). A fiscal year may be only partly represented
in the dataset. The spec's own example: FY2022 contains only FW49-52, so COUNT would
return 4 and misclassify the year, while MAX correctly returns 52.

A year with MAX < 52 is IN PROGRESS -- not a short year. It is left unclassified and the
month mapping is applied only to the weeks that exist, rather than guessing.

53-WEEK YEARS
-------------
The extra week is absorbed into Q4, which becomes 4-5-5. Q1-Q3 never change. In the
reference data FY2023 is the only 53-week year, and its M11 covers FW44-48 -- all five
December Fridays.
"""

# Quarter boundaries. Q4 alone varies with year length.
_QUARTERS_52 = ((1, 1, 13), (2, 14, 26), (3, 27, 39), (4, 40, 52))
_QUARTERS_53 = ((1, 1, 13), (2, 14, 26), (3, 27, 39), (4, 40, 53))

# Fiscal months as (month_number, first_week, last_week, calendar_month_name).
# Q1-Q3 are 4-4-5 in every year.
_MONTHS_COMMON = (
    (1, 1, 4, "February"), (2, 5, 8, "March"), (3, 9, 13, "April"),
    (4, 14, 17, "May"), (5, 18, 21, "June"), (6, 22, 26, "July"),
    (7, 27, 30, "August"), (8, 31, 34, "September"), (9, 35, 39, "October"),
)
# Q4 in a 52-week year: 4-4-5
_MONTHS_Q4_52 = ((10, 40, 43, "November"), (11, 44, 47, "December"), (12, 48, 52, "January"))
# Q4 in a 53-week year: 4-5-5 -- M11 gains the extra week
_MONTHS_Q4_53 = ((10, 40, 43, "November"), (11, 44, 48, "December"), (12, 49, 53, "January"))

IN_PROGRESS = "in_progress"


def fiscal_year(fiscal_week):
    """FLOOR(Fiscal_Week / 100). 202718 -> 2027."""
    v = _int(fiscal_week)
    return (v // 100) if v is not None else None


def week_number(fiscal_week):
    """MOD(Fiscal_Week, 100). 202718 -> 18."""
    v = _int(fiscal_week)
    return (v % 100) if v is not None else None


def _int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def weeks_in_year(all_fiscal_weeks, year):
    """MAX(week number) observed for `year`, or None when the year is absent.

    See the module docstring for why this is MAX and not COUNT(DISTINCT).
    """
    nums = [week_number(w) for w in (all_fiscal_weeks or []) if fiscal_year(w) == year]
    nums = [n for n in nums if n is not None]
    return max(nums) if nums else None


def classify_year(all_fiscal_weeks, year):
    """53 | 52 | IN_PROGRESS -- the length classification for one fiscal year."""
    observed = weeks_in_year(all_fiscal_weeks, year)
    if observed is None:
        return None
    if observed >= 53:
        return 53
    if observed == 52:
        return 52
    return IN_PROGRESS


def quarter(fiscal_week, year_length=52):
    """Fiscal quarter 1-4 for a week."""
    n = week_number(fiscal_week)
    if n is None:
        return None
    table = _QUARTERS_53 if year_length == 53 else _QUARTERS_52
    for q, lo, hi in table:
        if lo <= n <= hi:
            return q
    return None


def fiscal_month(fiscal_week, year_length=52):
    """(month_number, calendar_month_name) for a week, or (None, None).

    `year_length` selects the Q4 shape: 4-4-5 for a 52-week year, 4-5-5 for a 53-week one.
    Passing IN_PROGRESS is treated as 52 -- the weeks that exist still map correctly,
    because only Q4 differs and an in-progress year has not reached it.
    """
    n = week_number(fiscal_week)
    if n is None:
        return None, None
    q4 = _MONTHS_Q4_53 if year_length == 53 else _MONTHS_Q4_52
    for m, lo, hi, name in _MONTHS_COMMON + q4:
        if lo <= n <= hi:
            return m, name
    return None, None


def weeks_of_month(year, month_number, year_length=52):
    """Every Fiscal_Week in one fiscal month, as YYYYWW integers."""
    q4 = _MONTHS_Q4_53 if year_length == 53 else _MONTHS_Q4_52
    for m, lo, hi, _name in _MONTHS_COMMON + q4:
        if m == month_number:
            return [year * 100 + n for n in range(lo, hi + 1)]
    return []


def weeks_of_quarter(year, quarter_number, year_length=52):
    """Every Fiscal_Week in one fiscal quarter, as YYYYWW integers."""
    table = _QUARTERS_53 if year_length == 53 else _QUARTERS_52
    for q, lo, hi in table:
        if q == quarter_number:
            return [year * 100 + n for n in range(lo, hi + 1)]
    return []


def spans_month_boundary(fiscal_weeks, year_length=52):
    """True when a set of weeks crosses a fiscal month boundary.

    Drives the "Fiscal Month Transition" hypothesis.
    """
    months = {fiscal_month(w, year_length)[0] for w in (fiscal_weeks or [])}
    months.discard(None)
    return len(months) > 1


def spans_quarter_boundary(fiscal_weeks, year_length=52):
    """True when a set of weeks crosses a fiscal quarter boundary.

    Drives the "Quarter Transition" hypothesis.
    """
    qs = {quarter(w, year_length) for w in (fiscal_weeks or [])}
    qs.discard(None)
    return len(qs) > 1


def describe(fiscal_week, year_length=52):
    """Everything about one week, for display and for the audit record."""
    y, n = fiscal_year(fiscal_week), week_number(fiscal_week)
    m, cal = fiscal_month(fiscal_week, year_length)
    q = quarter(fiscal_week, year_length)
    return {
        "fiscal_week": _int(fiscal_week),
        "fiscal_year": y,
        "week_number": n,
        "quarter": q,
        "fiscal_month": m,
        "calendar_month": cal,
        "year_length": year_length,
        "label": (f"FY{str(y)[-2:]} FW{n:02d}" if y and n else None),
        "period_label_month": (f"FY{str(y)[-2:]} M{m:02d} ({cal})" if y and m else None),
        "period_label_quarter": (f"FY{str(y)[-2:]} Q{q}" if y and q else None),
    }


def period_weeks(grain, fiscal_week, year_length=52):
    """The full set of weeks in the period containing `fiscal_week`, at the given grain.

    Used by the confidence model: coverage is weeks-with-actuals over weeks-in-period, so
    a monthly RCA raised two weeks into a five-week month is only 40% covered and must be
    capped accordingly (Gate 3a).
    """
    y = fiscal_year(fiscal_week)
    g = (grain or "weekly").lower()
    if g == "weekly":
        return [_int(fiscal_week)]
    if g == "monthly":
        m, _ = fiscal_month(fiscal_week, year_length)
        return weeks_of_month(y, m, year_length) if m else []
    if g == "quarterly":
        q = quarter(fiscal_week, year_length)
        return weeks_of_quarter(y, q, year_length) if q else []
    return [_int(fiscal_week)]
