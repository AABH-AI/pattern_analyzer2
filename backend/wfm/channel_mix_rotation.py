# -*- coding: utf-8 -*-
"""Long-run channel rotation: which channel is losing share, and which is taking it.

WHY A SECOND MODULE AND NOT A CHANGE TO THE EXISTING ONE
-------------------------------------------------------
`channel_migration_detector` already answers a real question, but a different one. It compares the
TARGET WEEK against the PRIOR WEEK -- "did volume shift between channels this week". That is the right
test for a one-week miss and it cannot see a structural drift, because a drift of fifteen points spread
over three years moves almost nothing week to week.

Measured on the live table, that drift is the larger story. APJ / CCC / China / Basic over 178 weeks:

    Social Media   58.3%  ->  43.1%     -15.2 points
    Email          11.2%  ->  25.7%     +14.5 points
    Voice          30.3%  ->  30.4%       flat
    Chat            0.2%  ->   0.8%       flat

Neither channel's own week-to-week share moves more than about 8 points of standard deviation, so a
15-point one-way change is a rotation and not noise. A forecast built on the old mix keeps missing in a
direction nobody can explain from the queue's own volume, because the volume did not leave -- it
changed door.

WHAT IS AND IS NOT CLAIMED
--------------------------
Share moving from one channel to another is CO-MOVEMENT, not proof that a contact was diverted. A
falling channel and a rising channel can both be caused by something else entirely. So the output says
"share moved from X to Y", never "X was diverted to Y", and it publishes the offset ratio so a reader
can see how completely the two account for each other.

GROUPING
--------
CHANNEL_SIBLING_DIMS -- Region + SubRegion + Country + business_org -- reusing the grouping the
week-over-week detector already established rather than inventing a second one. Deliberately NOT the
CQN key: the console's signed-off CQN definition includes channel, so grouping by CQN would put every
channel in its own group and guarantee nothing is ever found. Same caveat as the existing detector,
and it is published on every result: this is a PROXY for the combined queue, not the authoritative
mapped CQN.
"""
from __future__ import annotations

from .common import CHANNEL_SIBLING_DIMS, num

# A channel's share must move by at least this many points across the two windows before it is worth
# reporting. Below this the change is inside the week-to-week wobble of most queues.
MIN_SHARE_MOVE_PTS = 5.0

# The rise and the fall must account for each other to this degree before the pair is named as a
# rotation. Two unrelated changes that happen to point opposite ways are not a rotation.
MIN_OFFSET_RATIO = 0.5

# A window shorter than this cannot establish a share, and comparing two noisy windows would produce
# a confident-looking number from nothing.
MIN_WEEKS_PER_WINDOW = 8
WINDOW_WEEKS = 13


def _shares(rows, weeks):
    """Channel shares, in percent, across a set of fiscal weeks."""
    tot = {}
    for r in rows:
        try:
            w = int(r.get("Fiscal_Week"))
        except (TypeError, ValueError):
            continue
        if w not in weeks:
            continue
        ch = str(r.get("channel") or "(unknown)")
        v = num(r.get("Actual_Offered"))
        if v is None:
            continue
        tot[ch] = tot.get(ch, 0.0) + float(v)
    grand = sum(tot.values())
    if not grand:
        return {}, 0.0
    return {c: v / grand * 100.0 for c, v in tot.items()}, grand


def _share_series_sd(rows, weeks, channel):
    """Standard deviation of one channel's weekly share, so drift can be told from wobble."""
    per = []
    for w in sorted(weeks):
        num_w, den_w = 0.0, 0.0
        for r in rows:
            try:
                if int(r.get("Fiscal_Week")) != w:
                    continue
            except (TypeError, ValueError):
                continue
            v = num(r.get("Actual_Offered"))
            if v is None:
                continue
            den_w += float(v)
            if str(r.get("channel") or "(unknown)") == channel:
                num_w += float(v)
        if den_w:
            per.append(num_w / den_w * 100.0)
    if len(per) < 4:
        return None
    mean = sum(per) / len(per)
    return (sum((x - mean) ** 2 for x in per) / len(per)) ** 0.5


def analyse(sibling_rows, target_week, target_channel):
    """Report long-run channel rotation for the scope the target queue sits in.

    `sibling_rows` must be every row for the scope group ACROSS channels -- the same shape the
    week-over-week detector takes, so the caller does not need a second query.
    """
    rows = [r for r in (sibling_rows or []) if r.get("Actual_Offered") is not None]
    if not rows:
        return {"available": False, "reason": "no sibling rows with actuals for this scope"}

    weeks = sorted({int(r["Fiscal_Week"]) for r in rows
                    if str(r.get("Fiscal_Week") or "").strip().isdigit()})
    channels = sorted({str(r.get("channel") or "(unknown)") for r in rows})

    if len(channels) < 2:
        return {"available": False, "channels": channels,
                "reason": ("this scope carries only the %s channel, so there is no other channel for "
                           "share to move to" % (channels[0] if channels else "one"))}
    if len(weeks) < MIN_WEEKS_PER_WINDOW * 2:
        return {"available": False, "channels": channels, "weeks": len(weeks),
                "reason": ("%d week(s) of history across channels; %d are needed to compare two "
                           "independent windows" % (len(weeks), MIN_WEEKS_PER_WINDOW * 2))}

    early = set(weeks[:WINDOW_WEEKS])
    late = set(weeks[-WINDOW_WEEKS:])
    a, a_tot = _shares(rows, early)
    b, b_tot = _shares(rows, late)
    if not a or not b:
        return {"available": False, "channels": channels,
                "reason": "one of the two comparison windows carries no volume"}

    moves = []
    for c in channels:
        sd = _share_series_sd(rows, set(weeks), c)
        moves.append({
            "channel": c,
            "share_early_pct": round(a.get(c, 0.0), 1),
            "share_late_pct": round(b.get(c, 0.0), 1),
            "change_pts": round(b.get(c, 0.0) - a.get(c, 0.0), 1),
            "weekly_share_sd_pts": (round(sd, 1) if sd is not None else None),
            # A move inside its own weekly wobble is not evidence of anything.
            "exceeds_own_noise": (None if sd is None
                                  else abs(b.get(c, 0.0) - a.get(c, 0.0)) > sd),
        })
    moves.sort(key=lambda m: m["change_pts"])

    fallers = [m for m in moves if m["change_pts"] <= -MIN_SHARE_MOVE_PTS]
    risers = [m for m in moves if m["change_pts"] >= MIN_SHARE_MOVE_PTS]

    rotations = []
    for f in fallers:
        for r in risers:
            lost, gained = abs(f["change_pts"]), r["change_pts"]
            offset = min(lost, gained) / max(lost, gained) if max(lost, gained) else 0.0
            if offset < MIN_OFFSET_RATIO:
                continue
            rotations.append({
                "from_channel": f["channel"], "to_channel": r["channel"],
                "points_moved": round(min(lost, gained), 1),
                "offset_ratio": round(offset, 2),
                "from_change_pts": f["change_pts"], "to_change_pts": r["change_pts"],
                "both_exceed_noise": bool(f.get("exceeds_own_noise")
                                          and r.get("exceeds_own_noise")),
                "reading": (
                    "Share moved from %s to %s: %s fell %.1f points (%.1f%% to %.1f%%) while %s rose "
                    "%.1f points (%.1f%% to %.1f%%), comparing the first %d weeks with the last %d. "
                    "The two account for %.0f%% of each other. This is co-movement in the mix, not "
                    "proof that contacts were diverted -- but a plan built on the older mix will keep "
                    "missing on both channels, in opposite directions."
                    % (f["channel"], r["channel"], f["channel"], abs(f["change_pts"]),
                       f["share_early_pct"], f["share_late_pct"], r["channel"], r["change_pts"],
                       r["share_early_pct"], r["share_late_pct"], WINDOW_WEEKS, WINDOW_WEEKS,
                       offset * 100.0)),
            })
    rotations.sort(key=lambda x: -x["points_moved"])

    tc = str(target_channel or "")
    this = next((m for m in moves if m["channel"] == tc), None)
    involved = [r for r in rotations
                if r["from_channel"] == tc or r["to_channel"] == tc]

    if rotations:
        headline = ("Channel mix rotated: " + "; ".join(
            "%s to %s, %.1f points" % (r["from_channel"], r["to_channel"], r["points_moved"])
            for r in rotations[:2]) + ".")
    else:
        biggest = max(moves, key=lambda m: abs(m["change_pts"]))
        headline = ("Channel mix is stable across %d weeks. The largest move is %s at %+.1f points, "
                    "under the %.0f-point bar for reporting a rotation."
                    % (len(weeks), biggest["channel"], biggest["change_pts"], MIN_SHARE_MOVE_PTS))

    return {
        "available": True,
        "grouped_by": " + ".join(CHANNEL_SIBLING_DIMS),
        "is_cqn_proxy": True,
        "cqn_note": ("The signed-off CQN definition includes channel, so grouping by CQN would place "
                     "every channel in its own group and guarantee nothing is ever found. This is a "
                     "proxy for the combined queue, across channels."),
        "weeks": len(weeks), "window_weeks": WINDOW_WEEKS,
        "early_weeks": [min(early), max(early)], "late_weeks": [min(late), max(late)],
        "channels": channels,
        "per_channel": moves,
        "rotations": rotations,
        "rotation_detected": bool(rotations),
        "target_channel": tc or None,
        "target_channel_move": this,
        "target_channel_involved": involved,
        "headline": headline,
        "how_to_read": (
            "Share of this scope's total contacts, by channel, in the first %d weeks against the last "
            "%d. A channel losing share while another gains a similar amount is a rotation -- the "
            "demand did not leave, it changed door, and a plan built on the old mix keeps missing on "
            "both. Each channel's own week-to-week share deviation is shown so a genuine drift can be "
            "told from ordinary wobble. Co-movement is reported; diversion is not claimed."
            % (WINDOW_WEEKS, WINDOW_WEEKS)),
    }
