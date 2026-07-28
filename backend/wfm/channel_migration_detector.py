"""Channel migration: did demand move BETWEEN channels rather than total demand changing?

READ THIS BEFORE CHANGING THE GROUPING
--------------------------------------
rca_console.html:1648-1653 records the client's CONFIRMED CQN definition as
Forecast_name + Region + SubRegion + Country + Channel -- channel IS part of the CQN key.
The WFM spec asks for migration "between Forecast Names or Channels within the same CQN",
which is only possible if channel is NOT in the key. The two are mutually exclusive.

This module does not redefine CQN. It uses a separately named grouping,
CHANNEL_SIBLING_DIMS = Region + SubRegion + Country + business_org, and every output is
labelled `is_cqn_proxy: true` so the two concepts can never be confused. Verified against
the data: 43 such groups carry more than one channel (up to 5 -- Case, Chat, Email,
Social Media, Voice), so migration is detectable.

Open question for the business is tracked in IMP_DOCS/TODO.md (P1b).
"""
from .common import CHANNEL_SIBLING_DIMS, num, rnd

# A migration looks like: channels moved a lot individually, group total barely moved.
_MIN_OFFSET_SHARE = 0.6      # >=60% of gross channel movement cancels out
_MAX_NET_SHARE = 0.25        # net group change stays under 25% of the prior total

_CQN_NOTE = ("Grouped by locality + business org across all channels. The console's "
             "signed-off CQN definition includes channel, so this grouping is a PROXY "
             "for the Combined Queue, not the authoritative mapped CQN.")


def analyse(rows, target_week, target_channel):
    if not rows:
        return {"available": False,
                "reason": "No channel-sibling rows returned for this locality."}

    weeks = sorted({str(r.get("Fiscal_Week")) for r in rows})
    if len(weeks) < 2:
        return {"available": False,
                "reason": "Only one week of channel-sibling data available; week-over-week "
                          "migration cannot be tested."}
    prev_wk, this_wk = weeks[0], weeks[-1]

    def by_channel(wk):
        agg = {}
        for r in rows:
            if str(r.get("Fiscal_Week")) != wk:
                continue
            ch = r.get("channel") or "(unknown)"
            agg[ch] = agg.get(ch, 0.0) + (num(r.get("Actual_Offered")) or 0.0)
        return agg

    now, before = by_channel(this_wk), by_channel(prev_wk)
    channels = sorted(set(now) | set(before))
    deltas = [{"channel": ch,
               "prior_week_actual": rnd(before.get(ch, 0.0)),
               "this_week_actual": rnd(now.get(ch, 0.0)),
               "change": rnd(now.get(ch, 0.0) - before.get(ch, 0.0)),
               "is_target_channel": ch == target_channel}
              for ch in channels]

    total_now, total_before = sum(now.values()), sum(before.values())
    net = total_now - total_before
    gross = sum(abs(d["change"]) for d in deltas)
    offset_share = (1.0 - abs(net) / gross) if gross else 0.0
    detected = bool(len(channels) > 1 and gross > 0
                    and offset_share >= _MIN_OFFSET_SHARE
                    and abs(net) < max(1.0, _MAX_NET_SHARE * abs(total_before or 1)))

    return {
        "available": True,
        "grouped_by": " + ".join(CHANNEL_SIBLING_DIMS),
        "is_cqn_proxy": True,
        "cqn_note": _CQN_NOTE,
        "prior_week": prev_wk,
        "this_week": this_wk,
        "per_channel": deltas,
        "group_total_prior_week": rnd(total_before),
        "group_total_this_week": rnd(total_now),
        "group_total_change": rnd(net),
        "gross_channel_movement": rnd(gross),
        "offset_share": round(offset_share, 2),
        "migration_detected": detected,
        "gaining_channels": [d["channel"] for d in deltas if d["change"] > 0],
        "losing_channels": [d["channel"] for d in deltas if d["change"] < 0],
        "note": ("Channels moved in opposite directions while the group total stayed close "
                 "to flat, which points to demand moving between channels rather than "
                 "total demand changing."
                 if detected else
                 "Channel movements do not cancel out, so this is not a like-for-like "
                 "shift between channels."),
    }
