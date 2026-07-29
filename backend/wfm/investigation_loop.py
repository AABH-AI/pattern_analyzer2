"""
The investigation loop — keep asking WHY until it stops being answerable.
========================================================================

WHY THIS EXISTS
---------------
The engine used to stop one level too early. It would report

    "3 of 5 similar queues moved the opposite way this week."

and call that a routing shift. A WFM lead reads that and asks "so what?", then "which
queues?", then "did total demand actually change?" — and the engine had nothing further to
say, even though it had already computed the answers.

Two separate faults, and only one of them was a data problem:

1. **It never walked the chain.** Which channel gained, which lost, whether the Combined
   Queue's total held flat — all of that was already in `channel_siblings`. Nothing chained
   it into "demand did not increase, it moved".
2. **It had no precedent.** "Has this happened before in this Combined Queue?" was
   unanswerable, so a one-week redistribution and a standing pattern looked identical.
   `data_access` now pulls 26 weeks of whole-CQN, per-channel history to close that.

WHAT THIS MODULE DOES
---------------------
Walks a fixed sequence of investigator questions, each one deterministic, each one recording
the evidence that answered it, and each one deciding whether the chain can go deeper:

    Q1  What changed this week?
    Q2  Is the change local to this queue, or system-wide?
    Q3  If local: did total Combined-Queue demand change, or only its distribution?
    Q4  If distribution: which channels gained and which lost?
    Q5  Has this happened before in this Combined Queue?
    Q6  What else could explain it — and what does the data eliminate?
    Q7  Can a WFM lead act on this tomorrow?

The chain terminates one of two ways, and says which:

  * `operational_cause`  — it reached something a WFM lead can act on.
  * `data_exhausted`     — it cannot go deeper, and it states **what data would be needed**
                           to continue. That is the honest end of an investigation, not a
                           failure to be papered over with a plausible guess.

LANGUAGE
--------
Every `answer` is written in operational terms, because that is what the business reads.
"3 of 5 similar queues moved the opposite way" becomes "three related queues handled fewer
contacts this week while this queue handled more, and total demand across the Combined Queue
barely moved — the work was redistributed rather than newly created." The raw counts stay in
`evidence`, where they belong.
"""
from .common import mean, median, num, rnd

# A Combined Queue's total is "flat" if it moved less than this share of its prior level.
_FLAT_TOTAL_SHARE = 0.10
# Channel movements "cancel out" when at least this share of gross movement is offsetting.
_OFFSET_SHARE = 0.60


def _pct(a, b):
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)) or not b:
        return None
    return (a / b - 1.0) * 100.0


def _step(n, question, answer, evidence, deeper, note=""):
    return {"step": n, "question": question, "answer": answer,
            "evidence": [e for e in evidence if e], "can_go_deeper": deeper, "note": note}


def _q1_what_changed(features, adherence):
    fs = (features.get("base_features") or {}).get("forecast_sanity") or {}
    tp = features.get("temporal") or {}
    forecast, actual = fs.get("forecast"), fs.get("actual")
    usual = tp.get("last_13_week_avg_actual") or fs.get("actual_usual_level")
    vs_usual = _pct(actual, usual)
    direction = "more" if (isinstance(adherence, (int, float)) and adherence < 0) else "fewer"
    answer = (f"This queue handled {direction} contacts than the plan expected: "
              f"{rnd(actual)} against a forecast of {rnd(forecast)}")
    if vs_usual is not None:
        answer += f", which is about {abs(round(vs_usual))}% {'above' if vs_usual > 0 else 'below'} its normal weekly level"
    answer += "."
    return _step(1, "What changed this week?", answer,
                 [{"text": f"Forecast {rnd(forecast)} vs actual {rnd(actual)}.",
                   "source_field": "fcst_offered", "value": forecast},
                  {"text": f"Normal weekly level is about {rnd(usual)}.",
                   "source_field": "Actual_Offered", "value": usual}],
                 deeper=True)


def _q2_local_or_systemic(features):
    ladder = features.get("investigation_ladder") or {}
    inherited = ladder.get("inherited_from")
    levels = ladder.get("levels") or []
    if not ladder.get("available"):
        return _step(2, "Is this change local to this queue, or system-wide?",
                     "Cannot tell — no higher-level rollup was available for this queue.",
                     [], deeper=True,
                     note="Higher-level comparison unavailable.")
    if inherited:
        match = next((x for x in levels if x.get("level") == inherited), {})
        return _step(2, "Is this change local to this queue, or system-wide?",
                     f"System-wide. The same miss is already visible at {inherited} level "
                     f"({match.get('scope')}), so this queue did not cause it and correcting this "
                     f"queue alone would not fix it.",
                     [{"text": f"At {inherited} level the whole scope was off by "
                               f"{match.get('adherence_pct')}% in the same direction this week.",
                       "source_field": "Actual_Offered", "value": match.get("actual_offered")}],
                     deeper=True,
                     note="Inherited from a higher level -- but keep going: how the work moved is "
                          "more actionable than which level it shows up at.")
    return _step(2, "Is this change local to this queue, or system-wide?",
                 "Local. No higher level of the business missed in the same direction this week, "
                 "so whatever happened is specific to this queue or its Combined Queue.",
                 [{"text": f"Levels checked and none breached in the same direction: "
                           f"{', '.join(x.get('level') for x in levels)}.",
                   "source_field": "Fiscal_Week", "value": len(levels)}],
                 deeper=True)


def _q3_total_or_distribution(features):
    cs = features.get("channel_siblings") or {}
    if not cs.get("available"):
        return _step(3, "Did total Combined-Queue demand change, or only its distribution?",
                     "Cannot tell — no sibling data for this Combined Queue this week.",
                     [], deeper=False,
                     note=cs.get("reason") or "No Combined-Queue siblings available.")
    before, now = cs.get("group_total_prior_week"), cs.get("group_total_this_week")
    net, gross = cs.get("group_total_change"), cs.get("gross_channel_movement")
    offset = cs.get("offset_share") or 0.0
    flat = bool(isinstance(net, (int, float)) and isinstance(before, (int, float)) and before
                and abs(net) <= _FLAT_TOTAL_SHARE * abs(before))
    redistributed = bool(flat and offset >= _OFFSET_SHARE and gross)
    ev = [{"text": f"Across the whole Combined Queue, contacts went from {before} to {now} "
                   f"(a change of {net}), while the individual channels moved {gross} in total.",
           "source_field": "Actual_Offered", "value": now}]
    if redistributed:
        return _step(3, "Did total Combined-Queue demand change, or only its distribution?",
                     "Only the distribution. Total demand across the Combined Queue barely moved, "
                     "but the split between its channels did — so this was work moving, not new "
                     "customer demand arriving.",
                     ev, deeper=True)
    if flat:
        return _step(3, "Did total Combined-Queue demand change, or only its distribution?",
                     "Total demand across the Combined Queue held roughly flat, but the channel "
                     "movements do not cancel out cleanly, so a straight swap between channels is "
                     "not established.",
                     ev, deeper=True)
    grew = isinstance(net, (int, float)) and net > 0
    return _step(3, "Did total Combined-Queue demand change, or only its distribution?",
                 f"Total demand genuinely {'rose' if grew else 'fell'} across the whole Combined "
                 f"Queue, not just this channel — so this is a real change in customer demand "
                 f"rather than work moving between channels.",
                 ev, deeper=True)


def _q4_who_gained_lost(features):
    cs = features.get("channel_siblings") or {}
    per = cs.get("per_channel") or []
    if not per:
        return _step(4, "Which channels gained and which lost?",
                     "Cannot tell — no per-channel breakdown available.", [], deeper=False,
                     note="No per-channel data.")
    gain = [d for d in per if (d.get("change") or 0) > 0]
    lose = [d for d in per if (d.get("change") or 0) < 0]
    target = next((d for d in per if d.get("is_target_channel")), None)
    say = lambda ds: ", ".join(f"{d['channel']} ({'+' if d['change'] > 0 else ''}{d['change']})"
                               for d in sorted(ds, key=lambda x: -abs(x["change"])))
    parts = []
    if gain:
        parts.append(f"handled more: {say(gain)}")
    if lose:
        parts.append(f"handled fewer: {say(lose)}")
    answer = ("Within the Combined Queue, " + "; ".join(parts) + ".") if parts else \
             "No channel moved materially."
    if target:
        answer += (f" This queue's own channel ({target['channel']}) went from "
                   f"{target['prior_week_actual']} to {target['this_week_actual']}.")
    return _step(4, "Which channels gained and which lost?", answer,
                 [{"text": f"{d['channel']}: {d['prior_week_actual']} -> {d['this_week_actual']}.",
                   "source_field": "Actual_Offered", "value": d["this_week_actual"]} for d in per],
                 deeper=True)


def _q5_precedent(features, cqn_history, target_week):
    """Has this Combined Queue redistributed like this before? This is the step that separates a
    one-off from a standing pattern, and it is the reason cqn_history is fetched."""
    if not cqn_history:
        return _step(5, "Has this happened before in this Combined Queue?",
                     "Cannot tell — no Combined-Queue history was available.", [], deeper=False,
                     note="Needs whole-Combined-Queue history; none returned.")
    by_week = {}
    for r in cqn_history:
        wk = str(r.get("Fiscal_Week"))
        by_week.setdefault(wk, {})[r.get("channel")] = num(r.get("actual")) or 0.0
    weeks = sorted(by_week)
    if len(weeks) < 4:
        return _step(5, "Has this happened before in this Combined Queue?",
                     f"Only {len(weeks)} week(s) of Combined-Queue history available — too few to "
                     f"say whether this is unusual.", [], deeper=False,
                     note="Needs more weeks of Combined-Queue history.")
    totals = [sum(by_week[w].values()) for w in weeks]
    # week-over-week: how often did the CQN total stay flat while channels moved?
    swaps = 0
    comparable = 0
    for i in range(1, len(weeks)):
        prev, cur_ = by_week[weeks[i - 1]], by_week[weeks[i]]
        chans = set(prev) | set(cur_)
        gross = sum(abs(cur_.get(c, 0.0) - prev.get(c, 0.0)) for c in chans)
        net = sum(cur_.values()) - sum(prev.values())
        base = sum(prev.values())
        if not gross or not base:
            continue
        comparable += 1
        if abs(net) <= _FLAT_TOTAL_SHARE * abs(base) and (1 - abs(net) / gross) >= _OFFSET_SHARE:
            swaps += 1
    share = (swaps / comparable) if comparable else None
    this_total = sum(by_week.get(str(target_week), {}).values()) or None
    typical = median(totals)
    ev = [{"text": f"{len(weeks)} weeks of Combined-Queue history reviewed; the total is typically "
                   f"about {rnd(typical)} contacts a week.",
           "source_field": "Actual_Offered", "value": typical}]
    if share is None:
        answer = "Could not compare weeks."
        deeper = False
    elif swaps == 0:
        answer = (f"No. Across {comparable} comparable weeks, the Combined Queue has never before "
                  f"held its total flat while the split between channels moved this much. This "
                  f"week is the first.")
        deeper = True
    elif share >= 0.30:
        answer = (f"Yes, routinely. The split between channels shifts like this in {swaps} of "
                  f"{comparable} weeks ({round(100*share)}%), so this is normal behaviour for this "
                  f"Combined Queue rather than a one-off event — which points at the forecast not "
                  f"modelling the channel mix, rather than at an operational incident.")
        deeper = True
    else:
        answer = (f"Occasionally — {swaps} of {comparable} weeks ({round(100*share)}%). Not routine, "
                  f"but this queue has done it before.")
        deeper = True
    if this_total and typical:
        ev.append({"text": f"This week the Combined Queue total was {rnd(this_total)}.",
                   "source_field": "Actual_Offered", "value": this_total})
    return _step(5, "Has this happened before in this Combined Queue?", answer, ev, deeper=deeper)


def _q6_eliminated(features):
    """What the data rules OUT. A business lead trusts a finding more when it is told what was
    checked and dismissed."""
    base = features.get("base_features") or {}
    eliminated, remaining = [], []
    hol = base.get("holiday") or {}
    if hol and not hol.get("unusual"):
        eliminated.append({"candidate": "Holiday or short week",
                           "why_not": f"the week had a normal number of holidays "
                                      f"({hol.get('holiday_count')})"})
    elif hol.get("unusual"):
        remaining.append("an unusual number of holidays in the week")
    plan = base.get("plan_restatement") or {}
    if plan and plan.get("changed") is False:
        eliminated.append({"candidate": "Forecast plan change",
                           "why_not": "the forecast plan did not change this week"})
    elif plan.get("changed"):
        remaining.append(f"the forecast plan changed ({plan.get('prior')} -> {plan.get('current')})")
    ib = base.get("installed_base") or {}
    if ib and not ib.get("material"):
        eliminated.append({"candidate": "Installed base / units under warranty",
                           "why_not": "the installed base did not move materially"})
    elif ib.get("material"):
        remaining.append(f"the installed base moved ({ib.get('field')} "
                         f"{ib.get('target_value')} vs usual {ib.get('history_mean')})")
    ch = base.get("chronic_bias") or {}
    if str(ch.get("verdict", "")).startswith("chronic"):
        remaining.append(f"a standing {ch.get('consistent_direction')}-forecast bias on this queue")
    elif ch.get("verdict") == "mixed":
        eliminated.append({"candidate": "Standing forecast bias",
                           "why_not": "this queue's misses have no consistent direction"})
    dq = features.get("data_quality") or {}
    if dq.get("suspect"):
        remaining.append("the recorded figure itself may not be credible and needs validating at source")

    answer = ""
    if eliminated:
        answer += "Ruled out: " + "; ".join(f"{e['candidate']} — {e['why_not']}" for e in eliminated) + ". "
    if remaining:
        answer += "Still in play: " + "; ".join(remaining) + "."
    if not answer:
        answer = "Nothing else could be checked from the available fields."
    return _step(6, "What else could explain this, and what does the data eliminate?", answer,
                 [{"text": f"{e['candidate']} ruled out because {e['why_not']}.",
                   "source_field": "Fiscal_Week", "value": 0} for e in eliminated],
                 deeper=bool(remaining), note=f"{len(eliminated)} ruled out, {len(remaining)} open")


def _q7_actionable(features, chain):
    """Can a WFM lead act on this tomorrow? If not, say what data would be needed."""
    cs = features.get("channel_siblings") or {}
    ladder = features.get("investigation_ladder") or {}
    base = features.get("base_features") or {}
    dq = features.get("data_quality") or {}

    if dq.get("suspect"):
        return _step(7, "Can a WFM lead act on this tomorrow?",
                     "Not yet — the recorded figure has to be validated at source first. Acting on "
                     "it would mean adjusting a plan to match a number that may not be real.",
                     [], deeper=False, note="Validate the figure at source.")
    if cs.get("migration_detected"):
        gaining = ", ".join(cs.get("gaining_channels") or []) or "the gaining channel(s)"
        losing = ", ".join(cs.get("losing_channels") or []) or "the losing channel(s)"
        return _step(7, "Can a WFM lead act on this tomorrow?",
                     f"Yes. Forecast the Combined Queue as a whole first and allocate the channel "
                     f"split afterwards, and check the routing rules that moved work from {losing} "
                     f"to {gaining}. The queue-level forecast was not wrong about total demand — it "
                     f"was wrong about which channel would handle it.",
                     [], deeper=False, note="Forecast at Combined-Queue level; review routing.")
    if ladder.get("inherited_from"):
        return _step(7, "Can a WFM lead act on this tomorrow?",
                     f"Yes — but not on this queue alone. The same miss runs across "
                     f"{ladder['inherited_from']} level, so take it there; nothing in this queue's "
                     f"own data explains it.",
                     [], deeper=False, note="Act at the higher level.")
    ch = base.get("chronic_bias") or {}
    if str(ch.get("verdict", "")).startswith("chronic"):
        d = ch.get("consistent_direction")
        return _step(7, "Can a WFM lead act on this tomorrow?",
                     f"Yes. This queue is {d}-forecast week after week "
                     f"(typically {ch.get('usual_actual')} actual against "
                     f"{ch.get('usual_forecast')} forecast), so re-baseline it rather than treating "
                     f"this week as an event.",
                     [], deeper=False, note="Re-baseline the queue.")
    plan = base.get("plan_restatement") or {}
    if plan.get("changed"):
        return _step(7, "Can a WFM lead act on this tomorrow?",
                     f"Partly. The forecast plan changed this week "
                     f"({plan.get('prior')} -> {plan.get('current')}), so confirm whether the new "
                     f"plan carries the current demand assumptions before adjusting anything else.",
                     [], deeper=False, note="Confirm the new plan's assumptions.")
    return _step(7, "Can a WFM lead act on this tomorrow?",
                 "Not from this data alone. Everything measurable has been checked and nothing "
                 "operational explains the gap, so the next step is evidence this system does not "
                 "hold.",
                 [], deeper=False, note="Data exhausted.")


# What we would need to go deeper, by what the chain ran out of.
_DATA_WANTED = {
    "no_operational_cause": [
        "Incident / outage records for the week, to test whether a service event drove contacts",
        "Marketing or campaign calendar, to test whether an outbound activity drove contacts",
        "Product release or recall dates for the affected offering",
        "Routing-rule change history for the Combined Queue, with effective dates",
        "Intraday or daily arrival patterns, to show whether the change was one day or the whole week",
    ],
    "no_cqn_context": [
        "The Combined Queue mapping for this queue, so its sibling channels can be compared",
        "More weeks of Combined-Queue history, to establish whether the pattern is normal",
    ],
    "suspect_value": [
        "The source extract for this week, to confirm the recorded volume is real before acting",
    ],
}


def run(features, wfm_context, adherence):
    """Walk the chain. Returns the case file."""
    target_week = ((wfm_context or {}).get("prior_week") and None)  # placeholder, set below
    tw = (features.get("temporal") or {}).get("this_week") or {}
    target_week = tw.get("fiscal_week")

    chain = [_q1_what_changed(features, adherence)]
    chain.append(_q2_local_or_systemic(features))

    # Q3-Q5 run whenever there is Combined-Queue data to run them on. They deliberately do NOT
    # depend on Q2's verdict: an inherited miss still needs explaining, and "the work moved between
    # channels" is very often WHY the level above moved. Gating these behind "local only" was the
    # original bug -- the chain stopped at the first plausible explanation and never reported a
    # redistribution it had already detected.
    if (features.get("channel_siblings") or {}).get("available"):
        s3 = _q3_total_or_distribution(features)
        chain.append(s3)
        if s3["can_go_deeper"]:
            chain.append(_q4_who_gained_lost(features))
            chain.append(_q5_precedent(features, (wfm_context or {}).get("cqn_history") or [],
                                       target_week))
    else:
        chain.append(_q3_total_or_distribution(features))
    chain.append(_q6_eliminated(features))
    last = _q7_actionable(features, chain)
    chain.append(last)

    # Why did the chain stop?
    note = (last.get("note") or "").lower()
    if "data exhausted" in note:
        outcome, wanted = "data_exhausted", _DATA_WANTED["no_operational_cause"]
    elif "validate the figure" in note:
        outcome, wanted = "data_exhausted", _DATA_WANTED["suspect_value"]
    else:
        outcome, wanted = "operational_cause", []
    if not ((features.get("channel_siblings") or {}).get("available")):
        wanted = wanted + _DATA_WANTED["no_cqn_context"]

    return {
        "steps": chain,
        "steps_taken": len(chain),
        "outcome": outcome,
        "stopped_because": (last.get("note") or ""),
        "operational_action": (last.get("answer") if outcome == "operational_cause" else None),
        "data_required_to_go_deeper": wanted,
        "narrative": " ".join(s["answer"] for s in chain if s.get("answer")),
    }
