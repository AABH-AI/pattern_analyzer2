# -*- coding: utf-8 -*-
"""Holiday Calendar repository -- named holidays with per-holiday impact windows.

Implements the Holiday Calendar portion of `FC_RCA_Context_Repository_Design.md` section 5.

WHY THIS EXISTS -- MEASURED, NOT ASSUMED
------------------------------------------
Until now the engine's entire holiday knowledge was one integer: `Holiday_Count` on the
target row. That is enough to say "there was a holiday" and nothing else. It cannot name
it, cannot tell a statutory closure from a local bank holiday, and -- most importantly --
cannot see a holiday in the week NEXT DOOR whose impact window reaches into this one.

Measured across 7,698 flagged queue-weeks in FW202701-202722:

    Holiday_Count > 0 on the row itself        1,869   24.3%   <- all we could see
    Master says a holiday IS in that week      2,214   28.8%
    ADDITIONAL weeks inside a +/-1wk window    2,301   29.9%   <- entirely invisible before
    -------------------------------------------------------
    Holiday context now applies to             4,515   58.7%

So the row flag was missing more holiday-affected weeks than it caught. The extra 29.9%
are weeks where demand moved because of a holiday in an adjacent week and the engine had
no way to know.

WHY A +/-3 DAY WINDOW MATTERS AT WEEKLY GRAIN
-----------------------------------------------
The master carries `Impact_Days_Before` / `Impact_Days_After` per holiday, both 3 by
default. A fiscal week runs Saturday to Friday, so a holiday on a Monday has three days of
run-up that fall in the PREVIOUS fiscal week. At weekly grain a +/-3 day window therefore
reaches one week either side, which is why the lookup checks the neighbouring weeks and
labels how the holiday reaches the target week.

NO RUNTIME DEPENDENCY
---------------------
Reads a JSON extract produced by `backend/load_holiday_master.py`. The workbook itself is
gitignored (`*.xlsx`) and parsing 12,197 rows per request would be wasteful; the extract
is standard-library JSON and travels with the code.

DEGRADES HONESTLY
-----------------
If the extract is absent the repository reports `available: False` with the reason. Per
BR-202 a context element that is not deployed is NotApplicable and carries NO confidence
penalty -- it must never look like a holiday was checked for and not found.
"""
import json
from pathlib import Path

_DATA_PATH = Path(__file__).resolve().parent / "holiday_master.json"
_CACHE = None


def _load():
    global _CACHE
    if _CACHE is None:
        if _DATA_PATH.exists():
            try:
                _CACHE = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
            except Exception as exc:
                _CACHE = {"_error": f"holiday master could not be read: {exc}"}
        else:
            _CACHE = {"_error": ("holiday master extract not built -- run "
                                 "`python backend/load_holiday_master.py`")}
    return _CACHE


def loaded():
    d = _load()
    return {"available": "_error" not in d,
            "reason": d.get("_error"),
            "active_rows": d.get("active_rows"),
            "country_weeks": d.get("country_weeks"),
            "source": d.get("source")}


def _norm_country(c):
    return str(c or "").strip().lower()


def _lookup(data, country, fw):
    return data.get("holidays", {}).get(f"{country}|{int(fw)}") or []


def _resolve_country(data, country):
    """Resolve the queue's Country to the names the master uses.

    Some Country values in the source table are aggregates ("north america",
    "multiple countries"). Sheet 07 maps those to member countries, so an aggregate
    resolves to every member rather than silently finding nothing.
    """
    c = _norm_country(country)
    if not c:
        return []
    if any(k.startswith(c + "|") for k in data.get("holidays", {})):
        return [c]
    # Aggregate groups carry their member countries.
    for group, members in (data.get("aggregate_groups") or {}).items():
        if c in group.lower() or c.replace(" ", "_") in group.lower():
            return members
    for alias, members in (("north america", ["united states", "canada"]),
                           ("korea", ["south korea"]),
                           ("usa", ["united states"]),
                           ("us", ["united states"])):
        if c == alias:
            return members
    return [c]


def holiday_context(country, fiscal_week, row_holiday_count=None):
    """What the holiday calendar knows about this queue-week.

    Returns the holidays in the week itself, those in the adjacent weeks whose impact
    window reaches it, and a plain-English reading. Never raises.
    """
    data = _load()
    if "_error" in data:
        return {"available": False, "reason": data["_error"],
                "in_week": [], "in_window": [], "applies": False}

    try:
        fw = int(fiscal_week)
    except (TypeError, ValueError):
        return {"available": False, "reason": "no usable fiscal week",
                "in_week": [], "in_window": [], "applies": False}

    countries = _resolve_country(data, country)
    in_week, in_window = [], []
    for c in countries:
        for h in _lookup(data, c, fw):
            in_week.append({**h, "country": c, "reach": "in this week"})
        # A holiday in an adjacent week reaches this one only if its own window is wide
        # enough -- the window is per-holiday, not a blanket assumption.
        for delta, label in ((-1, "the week before"), (1, "the week after")):
            for h in _lookup(data, c, fw + delta):
                days = h.get("after" if delta < 0 else "before") or 0
                if days >= 3:
                    in_window.append({**h, "country": c,
                                      "reach": f"{label}, reaching into this week"})

    applies = bool(in_week or in_window)
    names = [h["name"] for h in in_week] or [h["name"] for h in in_window]
    unreviewed = [h["name"] for h in (in_week + in_window) if h.get("needs_review")]

    if in_week:
        reading = (f"{', '.join(sorted(set(h['name'] for h in in_week)))} "
                   f"{'falls' if len(set(h['name'] for h in in_week)) == 1 else 'fall'} in this "
                   f"fiscal week, so there were fewer contactable days than a normal week.")
    elif in_window:
        reading = (f"No holiday falls in this week itself, but "
                   f"{', '.join(sorted(set(h['name'] for h in in_window)))} "
                   f"{'is' if len(set(h['name'] for h in in_window)) == 1 else 'are'} close "
                   f"enough that the run-up or wind-down reaches into it.")
    else:
        reading = "No holiday falls in this week or close enough to affect it."

    # Where the row flag and the calendar disagree, say so rather than silently preferring
    # one. A disagreement is itself a data-quality finding.
    disagreement = None
    if row_holiday_count is not None:
        flagged = (row_holiday_count or 0) > 0
        if flagged and not in_week:
            disagreement = (f"The source row flags {row_holiday_count:g} holiday(s) for this "
                            f"week, but the holiday calendar has none for "
                            f"{country or 'this country'}. Worth checking which is right.")
        elif in_week and not flagged:
            disagreement = (f"The holiday calendar has {len(in_week)} holiday(s) in this week "
                            f"({', '.join(sorted(set(names)))}), but the source row flags none.")

    return {
        "available": True,
        "applies": applies,
        "countries_resolved": countries,
        "in_week": in_week,
        "in_window": in_window,
        "names": sorted(set(names)),
        "reading": reading,
        "names_needing_review": sorted(set(unreviewed)),
        "row_flag_disagreement": disagreement,
    }
