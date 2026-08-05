# -*- coding: utf-8 -*-
"""Evidence pack -- the facts behind the finding, computed once and used twice.

WHY THIS MODULE EXISTS
----------------------
The engine could say "the forecast was biased, consistently under-estimating demand" and
stop. True, and unactionable. The facts that make it useful -- how long it has been going
wrong, whether anyone reissued the plan during that run, how this week compares with the
same week last year -- were all derivable from history the engine already fetches, and
none of them were computed.

Everything here is arithmetic over `history_104`. No model, no new query, no new column.

USED TWICE, DELIBERATELY
------------------------
    1. INTO THE MODEL PAYLOAD -> the root-cause bullets cite these facts instead of
       asserting a bias in the abstract.
    2. INTO THE INTERROGATION -> the answers to WHY questions come from here, so a
       question about the length of the run or the plan's reissue history is answerable
       rather than "cannot be determined".

Computing it once for both keeps the two consistent. A narrative that quotes one figure
while the interrogation quotes another is worse than either alone.

WHY FLAT SENTENCES AND NOT JUST NUMBERS
----------------------------------------
`key_facts` are written as finished English, not as a nested structure to interpret.
Measured on the previous branch: asked "when did under-forecasting start?", the model
answered "that data is not available" while holding a 26-row series with a signed gap on
every row. The figure was present; reading it out of nested JSON was the failure. A flat
labelled sentence is read correctly where a nested lookup is not.

Anything stated as a fact here is also arithmetic the model no longer performs -- and the
engine is deterministic where the model is not.
"""
from .common import adherence_pct, num, rnd

RECENT_WEEKS = 26          # what the payload carries; enough to see a plan cycle
AGG_WINDOWS = (13, 26)


def _pairs(history):
    """(week, actual, forecast) for weeks that have both, chronological."""
    out = []
    for h in history or []:
        a, f = num(h.get("Actual_Offered")), num(h.get("fcst_offered"))
        if a is None or f is None:
            continue
        out.append((h.get("Fiscal_Week"), a, f))
    return out


# ==============================================================================
# Blocks
# ==============================================================================
def weekly_series(history, weeks=RECENT_WEEKS):
    """Per week: actual, forecast, signed gap, plan vintage, holidays, drivers.

    The signed `gap` is precomputed rather than left as a subtraction. Two columns the
    reader must subtract is one more step than a model reliably takes.
    """
    return [{
        "fiscal_week": h.get("Fiscal_Week"),
        "actual": num(h.get("Actual_Offered")),
        "forecast": rnd(num(h.get("fcst_offered"))),
        "gap": (rnd(num(h.get("Actual_Offered")) - num(h.get("fcst_offered")))
                if num(h.get("Actual_Offered")) is not None
                and num(h.get("fcst_offered")) is not None else None),
        "plan_vintage": h.get("Projection_plan_name"),
        "holidays": num(h.get("Holiday_Count")),
        "planned_units_shipment": num(h.get("Final_Units")),
        "actual_asu": num(h.get("Actual_ASU")),
        "planned_asu": num(h.get("Planned_ASU")),
    } for h in (history or [])[-weeks:]]


def period_aggregates(history):
    """Cumulative gap, mean, over/under counts and the largest deviations.

    Precomputed because these are exactly the figures questions ask for, and a model
    summing 26 rows in its head gets them wrong. Reading a total is reliable; deriving
    one is not.
    """
    rows = _pairs(history)
    if not rows:
        return {"available": False, "reason": "no comparable weeks"}

    def block(n):
        sel = rows[-n:]
        gaps = [(w, a - f) for w, a, f in sel]
        if not gaps:
            return None
        under = len([g for _, g in gaps if g > 0])      # actual ABOVE plan
        worst = sorted(gaps, key=lambda g: -abs(g[1]))[:3]
        return {
            "weeks": len(sel),
            "cumulative_gap_contacts": rnd(sum(g for _, g in gaps)),
            "mean_gap_per_week": rnd(sum(g for _, g in gaps) / len(gaps)),
            "weeks_actual_above_plan": under,
            "weeks_actual_below_plan": len(gaps) - under,
            "largest_deviations": [{"fiscal_week": w, "gap_contacts": rnd(g)} for w, g in worst],
        }

    out = {"available": True}
    for n in AGG_WINDOWS:
        b = block(n)
        if b:
            out[f"last_{n}_weeks"] = b
    return out


def plan_vintage_timeline(history, limit=8):
    """Every week the projection plan changed, what it was set to, and that week's miss.

    This is what answers "was the plan reissued while it was going wrong?" -- the
    answerable form of "why did nobody adjust it", which no dataset can settle.
    """
    out, prev = [], None
    for h in history or []:
        name = h.get("Projection_plan_name")
        if not name or name == prev:
            prev = name or prev
            continue
        a, f = num(h.get("Actual_Offered")), num(h.get("fcst_offered"))
        out.append({
            "changed_at_week": h.get("Fiscal_Week"),
            "new_plan": name,
            "previous_plan": prev,
            "forecast_set_to": rnd(f),
            "actual_that_week": rnd(a),
            "adherence_that_week": (rnd(adherence_pct(a, f)) if a is not None and f else None),
        })
        prev = name
    return out[-limit:]


def key_facts(history, target_week, holiday_count=None):
    """Finished English sentences -- the facts a reader and a model both need stated.

    Deliberately prose, not structure. See the module docstring: nested lookups failed
    where flat sentences are read correctly.
    """
    rows = _pairs(history)
    facts = []
    if not rows:
        return facts

    # Coerce before formatting. `Holiday_Count` arrives as a STRING in file-upload mode --
    # the browser sends whatever the spreadsheet column held -- and `f"{value:g}"` on a str
    # raises "Unknown format code 'g'", which surfaced as a 500 on the whole investigation.
    # A display helper must never be the thing that kills an RCA, so nothing is formatted
    # here until it is known to be a number.
    holiday_count = num(holiday_count)

    # How long has this been going wrong, and since when? Asked in some form on almost
    # every queue, and previously answerable only by reading 26 rows.
    tgt_dir, streak, first = None, 0, None
    for w, a, f in reversed(rows):
        d = "under-forecast" if a > f else "over-forecast"
        if tgt_dir is None:
            tgt_dir = d
        if d != tgt_dir:
            break
        streak += 1
        first = w
    if streak > 1:
        facts.append(f"This queue has missed in the SAME direction ({tgt_dir}) for {streak} "
                     f"consecutive weeks. The run began at fiscal week {first}.")
    else:
        facts.append(f"This week's {tgt_dir} does not continue a run — the previous week "
                     f"missed the other way.")

    # Was the plan reissued while that run was happening? A plan revisited and still wrong
    # is a different finding from a plan nobody looked at, and they imply different fixes.
    tl = plan_vintage_timeline(history)
    during = [t for t in tl if first and t.get("changed_at_week")
              and str(t["changed_at_week"]) >= str(first)]
    if during:
        moves = ", ".join(f"FW{t['changed_at_week']} (set to {t['forecast_set_to']:,.0f})"
                          for t in during if t.get("forecast_set_to") is not None)
        facts.append(f"The plan WAS reissued {len(during)} time(s) during that run — {moves} — "
                     f"and the queue kept missing the same way afterwards. This is not a plan "
                     f"nobody revisited; it is a plan that was revisited and stayed wrong.")
    elif tl:
        facts.append(f"The plan was NOT reissued during that run. Its last change was at "
                     f"fiscal week {tl[-1].get('changed_at_week')}, before the run began.")

    # Same week last year -- the first comparison a manager reaches for.
    if target_week:
        try:
            ly_wk = int(target_week) - 100
        except (TypeError, ValueError):
            ly_wk = None
        ly = next((r for r in rows if ly_wk and str(r[0]) == str(ly_wk)), None)
        tgt = next((r for r in rows if str(r[0]) == str(target_week)), None)
        if ly and tgt and ly[1]:
            chg = (tgt[1] - ly[1]) / ly[1] * 100
            facts.append(f"Same week last year (FW{ly[0]}) actual demand was {ly[1]:,.0f} "
                         f"against a plan of {ly[2]:,.0f}. This year's {tgt[1]:,.0f} is "
                         f"{abs(chg):.0f}% {'higher' if chg > 0 else 'lower'}.")

    # Do holiday weeks actually move this queue? A holiday is only a cause where it does.
    hol = [a for h, a in ((h, num(h.get("Actual_Offered"))) for h in history or [])
           if (num(h.get("Holiday_Count")) or 0) > 0 and a is not None]
    nor = [a for h, a in ((h, num(h.get("Actual_Offered"))) for h in history or [])
           if (num(h.get("Holiday_Count")) or 0) == 0 and a is not None]
    if len(hol) >= 3 and len(nor) >= 3 and sum(nor):
        mh, mn = sum(hol) / len(hol), sum(nor) / len(nor)
        diff = (mh - mn) / mn * 100
        if abs(diff) >= 5:
            facts.append(f"Holiday weeks run {abs(diff):.0f}% "
                         f"{'below' if diff < 0 else 'above'} normal for this queue "
                         f"({mh:,.0f} contacts against {mn:,.0f})."
                         + (f" This week carries {holiday_count:g} holiday(s)."
                            if holiday_count else " This week carries no holiday."))
        else:
            facts.append(f"Holiday weeks are only {abs(diff):.0f}% different from normal for "
                         f"this queue, so holidays do not materially move it.")
    return facts


def build(history, target_week, holiday_count=None):
    """The whole pack. Safe on empty history -- every block reports its own absence.

    EVERY BLOCK IS INDIVIDUALLY GUARDED. This pack is additive: it enriches a report and is
    never required to produce one, so a fault in it must degrade that one block and nothing
    else.

    Learned the hard way. A single `f"{value:g}"` against a string `Holiday_Count` raised
    inside `key_facts` and returned HTTP 500 for the whole investigation -- a queue that
    could have been explained was not, because one sentence about holidays would not
    format. Blocks now fail alone.
    """
    out, failed = {}, []
    for name, fn, empty in (
            ("key_facts", lambda: key_facts(history, target_week, holiday_count), []),
            ("weekly_series", lambda: weekly_series(history), []),
            ("period_aggregates", lambda: period_aggregates(history), {"available": False}),
            ("plan_vintage_changes", lambda: plan_vintage_timeline(history), []),
            ("weeks_of_history", lambda: len(_pairs(history)), 0)):
        try:
            out[name] = fn()
        except Exception as exc:
            out[name] = empty
            failed.append(f"{name}: {type(exc).__name__}: {exc}")

    out["note"] = ("Arithmetic on this queue's own history. `key_facts` are finished "
                   "statements — quote them directly rather than re-deriving them.")
    if failed:
        # Surfaced, never swallowed: a silently empty block reads as "no history" when the
        # truth is a defect, and those need opposite responses.
        out["blocks_failed"] = failed
    return out
