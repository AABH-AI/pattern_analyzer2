"""Is the number itself credible?

Not in the supplied spec, but implied by it: "never fabricate business events" only holds
if you first check the value is real. An isolated extreme that reverts immediately, unique
in the queue's whole history, is far more likely an ingestion artefact than a business event.

Always surfaced as a hypothesis to validate at source -- never asserted as the cause.

Real case this was built from: NA Core Spanish week 202719 recorded 8,805 against a typical
week of ~117. Across 126 weeks that queue never otherwise exceeds 1,000; the following weeks
are 87 / 54 / 39; and of 427 queues with >=8 weeks it is the only one with a single week
above 50x its own median. 8805/100 = 88.05 against that week's forecast of 90.78.
"""
from .common import mean, median, num

_EXTREME_HIGH = 10.0     # >=10x the typical week
_EXTREME_LOW = 0.1       # <=1/10th
_MIN_WEEKS = 8


def analyse(history_104, history_forward, target_week, target_actual):
    acts = [(str(h.get("Fiscal_Week")), num(h.get("Actual_Offered")))
            for h in (history_104 or [])]
    acts = [(w, a) for w, a in acts if a is not None]
    others = [a for w, a in acts if w != str(target_week)]

    if target_actual is None or len(others) < _MIN_WEEKS:
        return {"available": False,
                "reason": "Not enough history to judge whether the value is credible."}

    typical = median(others)
    ratio = (target_actual / typical) if typical else None
    extreme = bool(ratio is not None and (ratio >= _EXTREME_HIGH or ratio <= _EXTREME_LOW))

    # Is it a one-off, or a level shift? A level shift has other weeks near it.
    isolated = bool(ratio is not None
                    and not any(a >= 0.5 * target_actual for a in others))

    # Reversion needs weeks AFTER the target -- only available retrospectively.
    after = [num(h.get("Actual_Offered")) for h in (history_forward or [])]
    after = [a for a in after if a is not None][:3]
    after_mean = mean(after)
    reverts = bool(after and typical is not None and after_mean is not None
                   and abs(after_mean - typical) <= max(1.0, 0.5 * typical))

    suspect = bool(extreme and isolated and (reverts or not after))
    if extreme and isolated and reverts:
        note = ("This week's value is far outside everything else this queue has ever "
                "recorded, it is the only week anywhere near that level, and the following "
                "weeks return to the normal level. Validate the figure at source before "
                "treating it as a real demand event.")
    elif extreme and isolated:
        note = ("This week's value is far outside everything else this queue has ever "
                "recorded and is the only week anywhere near that level. No later weeks "
                "are available yet to confirm it reverted. Validate the figure at source "
                "before acting on it.")
    elif extreme:
        note = ("This week's value is far from the typical week, but other weeks sit near "
                "the same level, so it looks like a genuine shift rather than a bad value.")
    else:
        note = "Nothing about the value itself looks implausible."

    return {
        "available": True,
        "this_week_actual": target_actual,
        "typical_week_actual": round(typical, 1) if typical is not None else None,
        "times_typical": round(ratio, 1) if ratio else None,
        "weeks_compared": len(others),
        "is_isolated_one_off": isolated,
        "next_weeks_actual": [round(a, 1) for a in after],
        "returns_to_normal_immediately": reverts,
        "reversion_testable": bool(after),
        "suspect": suspect,
        "note": note,
    }
