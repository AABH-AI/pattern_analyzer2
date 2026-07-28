"""The investigation ladder: Business Org -> Region -> SubRegion -> Country -> Channel.

The prompt forbids concluding at a lower level before confirming the issue is not
inherited from a higher one. This turns that rule into a computed verdict instead of an
instruction the model may or may not follow.
"""


def analyse(ladder, target_adherence, band):
    """ladder = the per-level rollups from data_access (already adherence-scored)."""
    if not ladder:
        return {"available": False, "levels": [], "levels_breaching_band": [],
                "inherited_from": None,
                "note": "No higher-level rollup was available for this queue."}

    breached = [lv for lv in ladder if abs(lv["adherence_pct"]) > band]
    inherited = None
    if breached and isinstance(target_adherence, (int, float)):
        # The HIGHEST level that missed in the SAME direction as this queue. Ladder is
        # ordered highest-first, so the first match is the highest.
        same_dir = [lv for lv in breached
                    if (lv["adherence_pct"] < 0) == (target_adherence < 0)]
        if same_dir:
            inherited = same_dir[0]["level"]

    return {
        "available": True,
        "band_pct": band,
        "levels": ladder,
        "levels_breaching_band": [lv["level"] for lv in breached],
        "inherited_from": inherited,
        "note": (f"The same miss is already visible at {inherited} level, so it is not "
                 f"specific to this queue and should be attributed there."
                 if inherited else
                 "No higher level breaches the band in the same direction; the miss "
                 "looks specific to this queue."),
    }
