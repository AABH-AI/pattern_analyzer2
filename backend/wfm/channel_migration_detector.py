"""Demand-switch detection: did volume move BETWEEN segments of one dimension rather than
total demand genuinely changing? Originally channel-only ("did customers switch from Voice to
Chat"); generalised 2026-08-05 to any single grouping field so the SAME arithmetic also answers
"did volume move between Offerings" (Region -> SubRegion -> Country -> Offering -> Channel is
the business's own drill-down order -- see IMP_DOCS/wfm-rca-engine.md). One SQL fetch already
carries both `channel` and `Offering` per row (data_access.py), so this is called twice on the
same rows: once grouped by channel (existing behaviour, unchanged for any existing caller that
doesn't pass group_field), once by Offering.

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

# A migration looks like: segments moved a lot individually, group total barely moved.
_MIN_OFFSET_SHARE = 0.6      # >=60% of gross movement cancels out
_MAX_NET_SHARE = 0.25        # net group change stays under 25% of the prior total

_CQN_NOTE = ("Grouped by locality + business org across all channels. The console's "
             "signed-off CQN definition includes channel, so this grouping is a PROXY "
             "for the Combined Queue, not the authoritative mapped CQN.")


def analyse(rows, target_week, target_channel, cqn_names=None, cqn_source="proxy",
            group_field="channel", group_label="Channel"):
    """group_field is the row key to segment by (e.g. "channel" or "Offering"); group_label is
    its business-facing name, used only in narrative text. Defaults preserve exact prior
    behaviour for any caller that doesn't pass these two (channel migration detection)."""
    if not rows:
        return {"available": False,
                "reason": f"No sibling rows returned for this locality to check {group_label} movement."}

    weeks = sorted({str(r.get("Fiscal_Week")) for r in rows})
    if len(weeks) < 2:
        return {"available": False,
                "reason": f"Only one week of data available; week-over-week {group_label} "
                          f"movement cannot be tested."}
    prev_wk, this_wk = weeks[0], weeks[-1]

    def by_segment_details(wk):
        agg = {}
        names_map = {}
        for r in rows:
            if str(r.get("Fiscal_Week")) != str(wk):
                continue
            seg = r.get(group_field) or "(unknown)"
            fn = r.get("Forecast_name")
            agg[seg] = agg.get(seg, 0.0) + (num(r.get("Actual_Offered")) or 0.0)
            if seg not in names_map:
                names_map[seg] = set()
            if fn:
                names_map[seg].add(fn)
        return agg, names_map

    now, names_now = by_segment_details(this_wk)
    before, names_before = by_segment_details(prev_wk)

    segments = sorted(set(now) | set(before))
    deltas = []
    for seg in segments:
        c_now = rnd(now.get(seg, 0.0))
        c_before = rnd(before.get(seg, 0.0))
        seg_change = rnd(c_now - c_before)
        s_names = sorted(names_now.get(seg, set()) | names_before.get(seg, set()))
        s_text = ", ".join(s_names) if s_names else ""
        c_label = f"{seg} ({s_text})" if s_text else f"{seg} {group_label.lower()}"
        deltas.append({
            "channel": seg,                       # key name kept for back-compat with existing
            group_field: seg,                     # readers of channel-mode output; also exposed
            "sibling_queue_names": s_names,        # under the real group_field name for offering
            "sibling_queues_text": s_text,         # mode and any future dimension.
            "channel_label": c_label,
            "prior_week_actual": c_before,
            "this_week_actual": c_now,
            "change": seg_change,
            "abs_change": abs(seg_change),
            "is_target_channel": seg == target_channel
        })

    total_now, total_before = sum(now.values()), sum(before.values())
    net = total_now - total_before
    gross = sum(abs(d["change"]) for d in deltas)
    offset_share = (1.0 - abs(net) / gross) if gross else 0.0
    detected = bool(len(segments) > 1 and gross > 0
                    and offset_share >= _MIN_OFFSET_SHARE
                    and abs(net) < max(1.0, _MAX_NET_SHARE * abs(total_before or 1)))

    cqn_pct = rnd((net / total_before) * 100) if total_before else 0.0
    cqn_pct_str = f"{cqn_pct:+.1f}%" if cqn_pct != 0 else "0.0%"

    delta_phrases = []
    for d in deltas:
        c_label = d["channel_label"]
        c = d["change"]
        val = int(abs(round(c)))
        if c < 0:
            delta_phrases.append(f"{c_label} demand reduced by {val} contacts")
        elif c > 0:
            delta_phrases.append(f"{c_label} demand increased by {val} contacts")

    if len(delta_phrases) == 1:
        deltas_text = delta_phrases[0]
    elif len(delta_phrases) == 2:
        deltas_text = f"{delta_phrases[0]} while {delta_phrases[1]}"
    elif len(delta_phrases) > 2:
        deltas_text = f"{delta_phrases[0]} while " + ", ".join(delta_phrases[1:-1]) + f" and {delta_phrases[-1]}"
    else:
        deltas_text = f"{group_label.lower()} volumes remained unchanged"

    cqn_total_phrase = (
        f"remained almost unchanged ({cqn_pct_str})" if abs(cqn_pct) < 3.0
        else f"changed by {cqn_pct_str}"
    )

    authoritative = (cqn_source == "mapping") and bool(cqn_names)
    cqn_label = (f"the Combined Queue ({cqn_names[0]})" if (authoritative and cqn_names)
                 else "the Combined Queue")

    is_channel_mode = (group_field == "channel")
    formatted_narrative = (
        f"During Fiscal Week {this_wk}, total demand across {cqn_label} {cqn_total_phrase}. "
        f"However, {deltas_text}. "
        + (f"This indicates that customers chose different contact channels rather than demand reducing. "
           f"Because the forecast was generated independently for each Forecast Name instead of the CQN, "
           f"over-forecast and under-forecast errors occurred across individual channels."
           if is_channel_mode else
           f"This indicates that volume shifted between {group_label} segments rather than total "
           f"demand genuinely changing. Because forecasts are generated independently per Forecast "
           f"Name rather than at the {group_label} level, over-forecast and under-forecast errors "
           f"occurred across individual {group_label.lower()}s.")
    )


    return {
        "available": True,
        "group_field": group_field,
        "group_label": group_label,
        "grouped_by": ("Combined_Queue_Name (authoritative mapping)" if authoritative
                       else " + ".join(CHANNEL_SIBLING_DIMS)),
        "combined_queue_names": list(cqn_names or []),
        "is_cqn_proxy": not authoritative,
        "cqn_note": (
            "Grouped by the AUTHORITATIVE Combined Queue from dbo.CQN_Mapping"
            + (f" ({len(cqn_names)} CQNs: {', '.join(cqn_names[:3])}"
               + ("..." if len(cqn_names) > 3 else "") + ")" if cqn_names else "")
            + ". A Forecast_Name can belong to more than one Combined Queue (vendor-site "
              "splits), in which case the union of its queues is used."
            if authoritative else _CQN_NOTE),
        "prior_week": prev_wk,
        "this_week": this_wk,
        "per_channel": deltas,
        "group_total_prior_week": rnd(total_before),
        "group_total_this_week": rnd(total_now),
        "group_total_change": rnd(net),
        "cqn_total_change_pct": cqn_pct,
        "gross_channel_movement": rnd(gross),
        "offset_share": round(offset_share, 2),
        "migration_detected": detected,
        "gaining_channels": [d["channel"] for d in deltas if d["change"] > 0],
        "losing_channels": [d["channel"] for d in deltas if d["change"] < 0],
        "deltas_text": deltas_text,
        "formatted_narrative": formatted_narrative,
        "note": (formatted_narrative if detected else
                 f"{group_label} movements do not cancel out, so this is not a like-for-like "
                 f"shift between {group_label.lower()}s."),
    }

