"""Shared primitives for the WFM engine. No business logic lives here."""

# Dimensions that define a channel-sibling group. This is NOT the CQN --
# see IMP_DOCS/wfm-rca-engine.md for why the two must stay distinct.
CHANNEL_SIBLING_DIMS = ("Region", "SubRegion", "Country", "business_org")

# The business rule: only investigate outside this band.
DEFAULT_BAND_PCT = 10.0

# How far back the WFM engine looks. The prompt asks for ~104 weeks.
WFM_HISTORY_WEEKS = 104

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


def std_dev(xs):
    """Standard deviation of numeric array."""
    cleaned = [x for x in (xs or []) if isinstance(x, (int, float))]
    if len(cleaned) < 2:
        return 0.0
    m = mean(cleaned)
    variance = sum((x - m) ** 2 for x in cleaned) / (len(cleaned) - 1)
    return variance ** 0.5


def coefficient_of_variation(xs):
    """Coefficient of Variation (CV = StdDev / Mean). Measures volatility."""
    cleaned = [x for x in (xs or []) if isinstance(x, (int, float))]
    m = mean(cleaned)
    if not m:
        return 0.0
    sd = std_dev(cleaned)
    return rnd(sd / m, 3)


def mae(actuals, forecasts):
    """Mean Absolute Error (raw contact volume gap)."""
    pairs = [(a, f) for a, f in zip(actuals or [], forecasts or []) if isinstance(a, (int, float)) and isinstance(f, (int, float))]
    if not pairs:
        return None
    return rnd(sum(abs(a - f) for a, f in pairs) / len(pairs), 1)


def mape(actuals, forecasts):
    """Mean Absolute Percentage Error."""
    pairs = [(a, f) for a, f in zip(actuals or [], forecasts or []) if isinstance(a, (int, float)) and isinstance(f, (int, float)) and a > 0]
    if not pairs:
        return None
    return rnd((sum(abs(a - f) / a for a, f in pairs) / len(pairs)) * 100.0, 1)


def wape(actuals, forecasts):
    """Weighted Absolute Percentage Error (WFM gold standard)."""
    pairs = [(a, f) for a, f in zip(actuals or [], forecasts or []) if isinstance(a, (int, float)) and isinstance(f, (int, float))]
    if not pairs:
        return None
    sum_abs_err = sum(abs(a - f) for a, f in pairs)
    sum_actuals = sum(a for a, f in pairs)
    if not sum_actuals:
        return None
    return rnd((sum_abs_err / sum_actuals) * 100.0, 1)


def rmse(actuals, forecasts):
    """Root Mean Square Error (penalizes extreme single-week spikes)."""
    pairs = [(a, f) for a, f in zip(actuals or [], forecasts or []) if isinstance(a, (int, float)) and isinstance(f, (int, float))]
    if not pairs:
        return None
    mse = sum((a - f) ** 2 for a, f in pairs) / len(pairs)
    return rnd(mse ** 0.5, 1)


def bias(actuals, forecasts):
    """Signed directional forecast bias (negative = under-forecast / actual > fcst)."""
    pairs = [(a, f) for a, f in zip(actuals or [], forecasts or []) if isinstance(a, (int, float)) and isinstance(f, (int, float))]
    if not pairs:
        return None
    sum_err = sum(f - a for a, f in pairs)
    sum_actuals = sum(a for a, f in pairs)
    if not sum_actuals:
        return None
    return rnd((sum_err / sum_actuals) * 100.0, 1)


def drift(actuals, forecasts):
    """Multi-week baseline drift slope over recent 8-13 weeks."""
    pairs = [(a, f) for a, f in zip(actuals or [], forecasts or []) if isinstance(a, (int, float)) and isinstance(f, (int, float))]
    if len(pairs) < 4:
        return 0.0
    recent = pairs[-8:]
    first_half = recent[:len(recent)//2]
    second_half = recent[len(recent)//2:]
    wape_first = wape([p[0] for p in first_half], [p[1] for p in first_half]) or 0.0
    wape_second = wape([p[0] for p in second_half], [p[1] for p in second_half]) or 0.0
    return rnd(wape_second - wape_first, 1)


def momentum(actuals):
    """Week-over-week demand velocity acceleration (delta_t - delta_t-1)."""
    cleaned = [x for x in (actuals or []) if isinstance(x, (int, float))]
    if len(cleaned) < 3:
        return 0.0
    delta_t = cleaned[-1] - cleaned[-2]
    delta_prev = cleaned[-2] - cleaned[-3]
    return rnd(delta_t - delta_prev, 1)


def rnd(v, places=1):
    return round(v, places) if isinstance(v, (int, float)) else v
