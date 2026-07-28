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


def rnd(v, places=1):
    return round(v, places) if isinstance(v, (int, float)) else v
