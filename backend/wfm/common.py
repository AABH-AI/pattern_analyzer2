"""Shared primitives for the WFM engine. No business logic lives here."""

# Dimensions that define a channel-sibling group. This is NOT the CQN --
# see IMP_DOCS/wfm-rca-engine.md for why the two must stay distinct.
CHANNEL_SIBLING_DIMS = ("Region", "SubRegion", "Country", "business_org")

# The business rule: only investigate outside this band.
DEFAULT_BAND_PCT = 10.0

# How far back the WFM engine looks.
#
# 104 weeks (2 years) is the MINIMUM the spec requires, not a ceiling -- and at exactly 104
# a seasonal index can never be built. Seasonality compares the target week-of-year against
# the SAME week in other years and needs at least two earlier instances to be a pattern
# rather than one observation. A 104-week window ending at the target contains only ONE
# earlier instance of that week, so seasonality reported "unavailable" on every queue,
# including ones with three years of data sitting in the table.
#
# Measured on NA Comm Client ProSupport Email at FW202720: the table holds 126 weeks and
# week 20 exists at 202520, 202620 and 202720 -- but the 104-week cut started at ~202619,
# so 202520 was discarded before the engine saw it and only 1 earlier year survived.
#
# 157 = three fiscal years plus one week, which guarantees two earlier instances of every
# week-of-year. The downstream windows (13 / 52 / 104) slice from the end and are unchanged;
# only seasonality and the outlier baseline see the extra depth.
WFM_HISTORY_WEEKS = 157

# The cause taxonomy the skeptic gates on. Each key must have a precondition in
# skeptic.PRECONDITIONS -- a type with no precondition can never be rejected.
CAUSE_TYPES = (
    "forecast_baseline_error",
    "systematic_forecast_bias",
    "genuine_demand_event",
    "volume_routing_shift",
    "plan_restatement",
    "installed_base_change",
    "calendar_holiday_effect",
    "data_quality_issue",
    "inherited_from_higher_level",
    "channel_migration",
)


def num(v):
    """Numeric or None. Booleans are not numbers here."""
    if isinstance(v, bool):
        return None
    return v if isinstance(v, (int, float)) else None


def mean(xs):
    xs = [x for x in (xs or []) if isinstance(x, (int, float))]
    return (sum(xs) / len(xs)) if xs else None


def median(xs):
    xs = sorted(x for x in (xs or []) if isinstance(x, (int, float)))
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2.0


def adherence_pct(actual, forecast):
    """The one KPI. Same math and sign convention as the console and the default
    engine -- negative means actual ran ABOVE forecast. Never scored without a
    usable forecast."""
    a, f = num(actual), num(forecast)
    if a is None or not f:
        return None
    return (1.0 - (a / f)) * 100.0


def confidence_level(pct):
    if not isinstance(pct, (int, float)):
        return "Low"
    if pct >= 70:
        return "High"
    if pct >= 40:
        return "Medium"
    return "Low"


def prior_year_week(fiscal_week):
    """202719 -> 202619. Fiscal_Week is YYYYWW, so subtract 100."""
    try:
        return int(fiscal_week) - 100
    except (TypeError, ValueError):
        return None


def rnd(v, places=1):
    return round(v, places) if isinstance(v, (int, float)) else v


def week_ordinals(fiscal_weeks):
    """Map YYYYWW values onto a continuous week counter so lag arithmetic survives year rollover.

    `Fiscal_Week` is YYYYWW, so plain subtraction breaks at every fiscal-year boundary: the week
    before 202701 is 202652, not 202700. Any analysis that pairs a week with "the week k weeks
    earlier" therefore loses a pair at each boundary -- roughly three per lag over a 157-week
    window, and silently, which is the worst way to lose data.

    The year length is taken from the DATA (the highest week number observed in that year) rather
    than assumed to be 52, so a 53-week fiscal year is handled without a special case. This is the
    same principle fiscal_calendar states in its own docstring: the calendar is derived from the
    data, not from an anchor date.

    Returns {fiscal_week: ordinal}. Genuine gaps stay gaps -- a missing week leaves a hole in the
    ordinals, so callers pairing on `ordinal - k` still refuse to pair weeks that are not really
    k apart.
    """
    weeks = sorted({int(w) for w in fiscal_weeks if w is not None})
    if not weeks:
        return {}
    length = {}
    for wk in weeks:
        year, week = divmod(wk, 100)
        length[year] = max(length.get(year, 0), week)
    base, running = {}, 0
    for year in sorted(length):
        base[year] = running
        running += length[year]
    return {wk: base[wk // 100] + (wk % 100) for wk in weeks}
