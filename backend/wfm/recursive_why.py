# -*- coding: utf-8 -*-
"""Recursive root-cause reasoning -- interrogate the findings that were ACTUALLY made.

Implements `FC_RCA_RCA_Methodology.md` section 17 (Step 10) and the depth bound in
`FC_RCA_Master_Build_Specification__MBS_.md` section 13.

WHY THIS WAS REWRITTEN
----------------------
The first version walked a FIXED four-rung ladder: is it wider? why is the wider level
out? why the standing bias? why did the plan not follow? Every queue and every week got
the same four questions with different numbers substituted in. Three different queues
produced three identical-sounding chains -- which is the same "linear, not dynamic"
failure the whole engine was being rebuilt to fix, reproduced one layer up.

The correct shape is the reverse. Let the findings be generated first, then ask WHY of the
findings that actually exist:

    CLAIMS      what was actually observed for THIS queue this week
    EXPLAINERS  each can address a particular KIND of claim, if its evidence is present
    CHAIN       take the live claim, find an explainer that addresses it, its answer
                becomes the next claim, repeat

Two queues with different findings therefore get different questions, different depths and
different terminating causes -- because different explainers fire. Nothing is templated by
position; a rung exists only if something in the data created it.

The questions are still DETERMINISTIC and still not model-generated. They are phrased from
the claim's own content, so a spike asks about a spike and a chronic bias asks about a
chronic bias.

TERMINATION -- unchanged, all four conditions deterministic
------------------------------------------------------------
    1. Maximum depth reached
    2. No explainer can address the live claim from available evidence
    3. The next claim repeats one already asserted higher up (normalised semantic key)
    4. The explainer marks itself terminal -- nothing further can be broken down

Confidence can only fall going down: an inference several steps deep cannot be more
certain than the observation it rests on.
"""
import re

MAX_DEPTH = 6
MIN_EVIDENCE_STRENGTH = 0.4

CONTINUE = "continue"
TERMINATE = "terminate"


def _norm(text):
    """Normalised semantic key -- catches a claim restated in different words."""
    t = re.sub(r"[0-9][0-9,\.]*", "#", (text or "").lower())
    t = re.sub(r"[^a-z# ]+", " ", t)
    stop = {"the", "a", "an", "is", "are", "was", "were", "of", "in", "at", "to", "for",
            "this", "that", "it", "its", "and", "or", "but", "by", "on", "with", "than",
            "queue", "week", "weeks", "contacts", "level", "plan", "because", "so"}
    return " ".join(sorted(w for w in t.split() if w and w not in stop)[:12])


def _fmt(n):
    return f"{n:,.0f}" if isinstance(n, (int, float)) else "n/a"


# ==============================================================================
# CLAIMS -- a claim is a KIND plus the numbers that make it specific
# ==============================================================================
def _claim(kind, text, **data):
    return {"kind": kind, "text": text, "data": data}


def _opening_claim(obs):
    """The chain starts from whatever is most notable about THIS week -- not a fixed line.

    Four different openings depending on what the data actually shows, so the first
    question already differs between queues.
    """
    fs, m = obs["fs"], obs["metrics"]
    out = (m.get("outliers") or {})
    acc = (m.get("accuracy_recent") or {})
    direction = fs.get("direction") or "Miss"
    var = fs.get("absolute_variance_contacts")
    adh = fs.get("adherence_pct")

    if out.get("target_week_is_outlier"):
        det = out.get("target_week_detail") or {}
        return _claim(
            "single_week_extreme",
            f"{direction} of {adh}% — {_fmt(var)} contacts against plan, and this week is a "
            f"genuine {det.get('direction', 'spike')}: {_fmt(det.get('actual'))} contacts "
            f"against a typical {_fmt(out.get('median_actual'))}.",
            actual=det.get("actual"), typical=out.get("median_actual"),
            outlier_share=(out.get("outlier_count") or 0) / max(1, out.get("n") or 1))
    if acc.get("bias_material"):
        return _claim(
            "recurring_miss",
            f"{direction} of {adh}% — {_fmt(var)} contacts against plan, and this is not a "
            f"one-off: the plan has been out in the same direction repeatedly, averaging "
            f"{_fmt(acc.get('mae'))} contacts a week over 13 weeks.",
            per_week=acc.get("mae"), bias_direction=acc.get("bias_direction"))
    return _claim(
        "isolated_miss",
        f"{direction} of {adh}% — {_fmt(var)} contacts against plan, with no standing pattern "
        f"behind it.",
        variance=var)


# ==============================================================================
# QUESTIONS -- phrased from the claim's own content, never from its position
# ==============================================================================
def _question_for(claim):
    k, d = claim["kind"], claim["data"]
    return {
        "single_week_extreme":
            f"Why did demand reach {_fmt(d.get('actual'))} when this queue normally runs "
            f"about {_fmt(d.get('typical'))}?",
        "recurring_miss":
            f"Why has the plan been out by around {_fmt(d.get('per_week'))} contacts a week, "
            f"in the same direction, rather than missing at random?",
        "isolated_miss":
            f"Why was this week out by {_fmt(d.get('variance'))} contacts when nothing in this "
            f"queue's history predicted it?",
        "shared_with_wider_book":
            f"Why is {d.get('level')} out by {_fmt(d.get('gap'))} contacts?",
        "queue_dominates_wider":
            f"What is it about this queue specifically that produces {_fmt(d.get('per_week'))} "
            f"contacts a week of error?",
        "plan_not_tracking_demand":
            f"Why has the plan not moved with demand, which has been {d.get('direction')} by "
            f"about {_fmt(d.get('slope'))} contacts a week?",
        "plan_ignored_known_calendar":
            f"Why did the plan not allow for {d.get('names')}, which is a known date?",
        "plan_level_stale":
            f"Why has the plan's level not been corrected despite missing the same way for "
            f"{d.get('weeks')} weeks?",
        "genuinely_volatile":
            f"If this queue swings this much routinely, is there anything to explain?",
        "concentrated_below":
            f"Why is {d.get('level')} ({d.get('scope')}) worse than the levels above it?",
    }.get(k, f"Why {claim['text'][:60]}?")


# ==============================================================================
# EXPLAINERS -- each addresses particular claim KINDS, if its evidence exists
# ==============================================================================
# The opening claim kinds -- the three ways a week can present itself.
_OPENING_KINDS = ("single_week_extreme", "recurring_miss", "isolated_miss")


def _ex_scope(claim, obs):
    """Is the observation this queue's own, or the book's? Opening claims ONLY.

    The kind guard is load-bearing. Without it this explainer matched every claim, fired
    again on the second round, and its own previous answer tripped the circularity check --
    so every chain terminated at depth 1 reporting "would be circular", which was true but
    only because the same explainer had been asked twice.
    """
    if claim["kind"] not in _OPENING_KINDS:
        return None
    sc = obs["scope"]
    if not sc.get("available"):
        return None
    starts, share = sc.get("starts_at"), sc.get("queue_share_of_gap")
    if not starts:
        return {
            "answer": ("Because it is this queue's own behaviour, not something inherited — no "
                       "wider level missed in the same direction this week."),
            "evidence": ["investigation ladder"], "strength": 0.8, "confidence": 0.80,
            "next": _claim("queue_dominates_wider", "the queue's own behaviour",
                           per_week=(obs["metrics"].get("accuracy_recent") or {}).get("mae")),
        }
    first = next((l for l in sc.get("levels") or [] if l.get("level") == starts), {})
    gap = abs(first.get("gap_contacts") or 0)
    if share is not None and share >= 0.5:
        return {
            "answer": (f"Not because the wider book moved — {starts} ({first.get('scope')}) is out "
                       f"by {_fmt(gap)} contacts, but this single queue is {share:.0%} of that, so "
                       f"the wider figure is mostly this queue showing up in the total."),
            "evidence": ["investigation ladder"], "strength": 0.8, "confidence": 0.80,
            "next": _claim("queue_dominates_wider", "this queue drives the wider gap",
                           per_week=(obs["metrics"].get("accuracy_recent") or {}).get("mae")),
        }
    return {
        "answer": (f"Partly because the wider book moved with it: {starts} "
                   f"({first.get('scope')}) is out by {_fmt(gap)} contacts "
                   f"({first.get('adherence_pct'):+.1f}%), and this queue is "
                   f"{(share or 0):.0%} of that."),
        "evidence": ["investigation ladder"], "strength": 0.8, "confidence": 0.78,
        "next": _claim("shared_with_wider_book", f"{starts} is out by {_fmt(gap)}",
                       level=starts, scope=first.get("scope"), gap=gap),
    }


def _ex_concentration(claim, obs):
    """Addresses 'why is the wider level out' by locating where inside it the gap sits."""
    if claim["kind"] != "shared_with_wider_book":
        return None
    sc, d = obs["scope"], claim["data"]
    levels = sc.get("levels") or []
    # Adherence at the level this claim is about, so "worse than" has something to mean.
    here = next((abs(x.get("adherence_pct") or 0) for x in levels
                 if x.get("level") == d.get("level")), 0.0)
    below = [l for l in levels
             if l.get("breaches_band") and l.get("same_direction")
             and abs(l.get("adherence_pct") or 0) > here]
    worst = max(below, key=lambda l: abs(l.get("adherence_pct") or 0), default=None)
    if worst:
        return {
            "answer": (f"Because the gap concentrates further down: {worst.get('level')} "
                       f"({worst.get('scope')}) is out by {worst.get('adherence_pct'):+.1f}%, "
                       f"worse than {d.get('level')}. The problem sits inside "
                       f"{worst.get('level')}, not across the whole of {d.get('level')}."),
            "evidence": ["investigation ladder"], "strength": 0.7, "confidence": 0.72,
            "next": _claim("concentrated_below", "the gap concentrates lower down",
                           level=worst.get("level"), scope=worst.get("scope")),
        }
    return {
        "answer": (f"Because it is spread across {d.get('level')} rather than concentrated in one "
                   f"place — a book-wide planning pattern rather than a local fault. Fixing this "
                   f"queue alone would not close it."),
        "evidence": ["investigation ladder"], "strength": 0.6, "confidence": 0.62,
        "next": _claim("queue_dominates_wider", "this queue's own share of a book-wide pattern",
                       per_week=(obs["metrics"].get("accuracy_recent") or {}).get("mae")),
    }


def _ex_holiday(claim, obs):
    """A named holiday in or reaching this week is a cause in its own right.

    Placed ahead of the generic mechanism explainer because a short week is a CONCRETE
    reason a plan missed, and one that leads somewhere specific: the plan did not adjust
    for a known calendar event. "The baseline is drifting" is true of the queue in
    general; "Christmas Day fell in this week" is true of THIS week.
    """
    if claim["kind"] not in ("queue_dominates_wider", "concentrated_below", "recurring_miss",
                             "single_week_extreme", "isolated_miss"):
        return None
    hol = (obs.get("period") or {}).get("holiday") or {}
    if not hol.get("applies"):
        return None
    effect = (obs["metrics"].get("holiday_effect") or {})
    # Only offer it where holiday weeks DEMONSTRABLY move this queue. A holiday that has
    # never shifted this queue's volume is a calendar fact, not an explanation.
    if not effect.get("material"):
        return None

    in_week = hol.get("in_week") or []
    where = ("falls in this week" if in_week else
             "falls close enough that its run-up or wind-down reaches this week")
    names = ", ".join(hol.get("names") or ["a holiday"])
    return {
        "answer": (f"Because {names} {where}, and holiday weeks run "
                   f"{abs(effect.get('difference_pct', 0)):.0f}% "
                   f"{'below' if (effect.get('difference_pct') or 0) < 0 else 'above'} normal "
                   f"for this queue ({effect.get('avg_holiday'):,.0f} contacts against "
                   f"{effect.get('avg_normal'):,.0f}). The plan did not carry that adjustment."),
        "evidence": ["holiday calendar", "holiday effect"], "strength": 0.8, "confidence": 0.80,
        "next": _claim("plan_ignored_known_calendar", "the plan did not adjust for a known holiday",
                       names=names),
    }


def _ex_calendar_terminal(claim, obs):
    """Terminal for the holiday branch -- a known, dated, repeating event."""
    if claim["kind"] != "plan_ignored_known_calendar":
        return None
    hol = (obs.get("period") or {}).get("holiday") or {}
    dis = hol.get("row_flag_disagreement")
    answer = (f"Because {claim['data'].get('names')} is a fixed, known date that the plan "
              f"treats as an ordinary week. This is the most correctable kind of miss: the "
              f"calendar is published in advance, so the adjustment can be built into the plan "
              f"rather than explained afterwards.")
    if dis:
        answer += f" Note: {dis}"
    return {"answer": answer, "evidence": ["holiday calendar"], "strength": 0.8,
            "confidence": 0.78, "terminal": True}


def _ex_mechanism(claim, obs):
    """The heart of it: WHICH failure mode produced the queue's own error.

    Four mutually exclusive mechanisms, chosen by measurement -- so different queues get
    genuinely different answers here, not the same sentence with new numbers.
    """
    if claim["kind"] not in ("queue_dominates_wider", "concentrated_below", "recurring_miss",
                             "single_week_extreme", "isolated_miss"):
        return None
    m = obs["metrics"]
    acc, trend = m.get("accuracy_recent") or {}, m.get("trend_recent") or {}
    drift, cv = m.get("drift_recent") or {}, m.get("coefficient_of_variation_long") or {}
    out = m.get("outliers") or {}
    slope = trend.get("coefficient_of_regression_per_week")

    # A queue that is an outlier most weeks is not explained by "this week was unusual".
    share = (out.get("outlier_count") or 0) / max(1, out.get("n") or 1)
    if claim["kind"] == "single_week_extreme" and share >= 0.10:
        return {
            "answer": (f"It is not exceptional for this queue — {out.get('outlier_count')} of "
                       f"{out.get('n')} weeks ({share:.0%}) are just as extreme. A plan built on "
                       f"an average will miss badly here most weeks by construction, because the "
                       f"average describes almost none of them."),
            "evidence": ["outlier detection", "coefficient of variation"],
            "strength": 0.7, "confidence": 0.70,
            "next": _claim("genuinely_volatile", "the queue is inherently volatile"),
        }
    if trend.get("trend_meaningful") and isinstance(slope, (int, float)) and acc.get("bias_material"):
        return {
            "answer": (f"Because demand is moving and the plan is standing still. Demand has been "
                       f"{trend.get('direction')} by about {_fmt(abs(slope))} contacts a week for "
                       f"13 weeks; the plan held near its old level. A static plan against moving "
                       f"demand falls further behind every week, which is why the error is "
                       f"one-directional rather than random."),
            "evidence": ["trend", "bias"], "strength": 0.8, "confidence": 0.78,
            "next": _claim("plan_not_tracking_demand", "the plan is not tracking demand",
                           direction=trend.get("direction"), slope=abs(slope)),
        }
    if drift.get("drift_material"):
        return {
            "answer": (f"Because the error is widening, not steady: adherence has moved "
                       f"{_fmt(abs(drift.get('adherence_drift_total_pts') or 0))} points across 13 "
                       f"weeks in one direction. A baseline decaying like this keeps missing "
                       f"further until it is rebuilt."),
            "evidence": ["drift"], "strength": 0.8, "confidence": 0.75,
            "next": _claim("plan_level_stale", "the baseline is decaying", weeks=13),
        }
    if acc.get("bias_material"):
        return {
            "answer": (f"Because the plan's level is simply set wrong for this queue. Demand has "
                       f"not been trending, yet the plan is out the same way week after week by "
                       f"{_fmt(acc.get('mae'))} contacts — a number chosen too "
                       f"{'low' if acc.get('bias_direction') == 'under-forecast' else 'high'} and "
                       f"left in place."),
            "evidence": ["bias"], "strength": 0.8, "confidence": 0.75,
            "next": _claim("plan_level_stale", "the level was set wrong and left",
                           weeks=acc.get("n") or 13),
        }
    if cv.get("volatility_class") == "volatile":
        return {
            "answer": ("Because this queue's demand swings widely week to week, so a single-week "
                       "miss of this size is within its normal behaviour and does not imply a "
                       "fault in the plan."),
            "evidence": ["coefficient of variation"], "strength": 0.6, "confidence": 0.62,
            "next": _claim("genuinely_volatile", "inherently volatile"),
        }
    return None


def _ex_volatile_terminal(claim, obs):
    if claim["kind"] != "genuinely_volatile":
        return None
    cv = (obs["metrics"].get("coefficient_of_variation_long") or {})
    return {
        "answer": ("Nothing further to explain in the plan. The realistic action is to widen the "
                   "tolerance for this queue or forecast it as a range, because a single number "
                   "cannot describe demand that moves this much"
                   + (f" (it varies by about {cv.get('cv_pct')}% of its own average)."
                      if cv.get("cv_pct") is not None else ".")),
        "evidence": ["coefficient of variation"], "strength": 0.6, "confidence": 0.60,
        "terminal": True,
    }


def _ex_driver(claim, obs):
    """Terminal: can a measurable business driver account for the plan being wrong?"""
    if claim["kind"] not in ("plan_not_tracking_demand", "plan_level_stale"):
        return None
    gates = obs["gates"]
    warn = next((g.get("trend_warning") for g in gates.get("results", []) if g.get("trend_warning")),
                None)
    if gates.get("any_driver_relevant") and not warn:
        prim = gates.get("primary_driver")
        g = next((x for x in gates.get("results", []) if x.get("driver") == prim), {})
        return {
            "answer": (f"Because the plan's assumption about {g.get('label') or prim} is wrong. "
                       f"That driver does track this queue's demand, so the assumption behind it "
                       f"is the specific thing to correct."),
            "evidence": ["driver relevance gate"], "strength": 0.7, "confidence": 0.68,
            "terminal": True,
        }
    if warn:
        return {
            "answer": ("It cannot be traced to a business driver. The drivers that look related "
                       "only track demand across the period as a whole, not week to week, so "
                       "none can account for the plan being wrong in any given week. The cause "
                       "lies in how the plan is SET and how often it is revisited."),
            "evidence": ["driver relevance gate"], "strength": 0.6, "confidence": 0.58,
            "terminal": True,
        }
    return {
        "answer": ("No measurable driver explains it, and no business-event record exists for "
                   "this period. What remains is the planning process itself: the level, and how "
                   "often it is revisited. That is where the fix sits, and it is also the limit "
                   "of what this data can establish."),
        "evidence": ["driver relevance gate", "context repository"], "strength": 0.6,
        "confidence": 0.55, "terminal": True,
    }


EXPLAINERS = (_ex_scope, _ex_concentration, _ex_holiday, _ex_calendar_terminal,
              _ex_mechanism, _ex_volatile_terminal, _ex_driver)


# ==============================================================================
# The chain
# ==============================================================================
def reason(scope, metrics, gates, forecast_summary, period=None, max_depth=MAX_DEPTH):
    obs = {"scope": scope or {}, "metrics": metrics or {}, "gates": gates or {},
           "fs": forecast_summary or {}, "period": period or {}}

    claim = _opening_claim(obs)
    levels = [{"level": 0, "question": None, "semantic_key": _norm(claim["text"]),
               "answer": claim["text"], "evidence": ["forecast summary"],
               "strength": 1.0, "confidence": 1.0, "decision": CONTINUE,
               "claim_kind": claim["kind"]}]
    seen = {levels[0]["semantic_key"]}
    conf_ceiling = 1.0
    termination = None

    for depth in range(1, max_depth + 1):
        question = _question_for(claim)
        step, failures = None, []
        for ex in EXPLAINERS:
            try:
                step = ex(claim, obs)
            except Exception as exc:
                # Swallowing this silently is how a malformed expression in one explainer
                # made every chain look like it had simply run out of evidence. Record it
                # so a broken explainer reports itself instead of masquerading as an
                # honest "nothing more could be established".
                failures.append(f"{ex.__name__}: {type(exc).__name__}: {exc}")
                step = None
            if step:
                break

        if step is None:
            termination = ("no evidence available could answer the next question, so the chain "
                           "stops here rather than guessing")
            if failures:
                termination += (" (note: " + "; ".join(failures) +
                                " — this is a fault in the engine, not an absence of data)")
            break
        if (step.get("strength") or 0) < MIN_EVIDENCE_STRENGTH:
            termination = "the next step had no evidence strong enough to advance the chain"
            break
        key = _norm(step["answer"])
        if key in seen:
            termination = ("the next step would repeat a claim already made higher up, which "
                           "would be circular")
            break

        seen.add(key)
        conf_ceiling = min(conf_ceiling, step.get("confidence", 0.5))
        levels.append({
            "level": depth, "question": question, "semantic_key": key,
            "answer": step["answer"], "evidence": step.get("evidence") or [],
            "strength": step.get("strength"), "confidence": conf_ceiling,
            "decision": TERMINATE if step.get("terminal") else CONTINUE,
            "claim_kind": (step.get("next") or {}).get("kind") if not step.get("terminal") else None,
        })
        if step.get("terminal"):
            termination = "the chain reached a cause that cannot be broken down further"
            break
        claim = step.get("next")
        if not claim:
            termination = "the answer did not raise a further question"
            break
    else:
        termination = f"the maximum reasoning depth of {max_depth} was reached"

    levels[-1]["termination_reason"] = termination
    return {
        "available": len(levels) > 1,
        "levels": levels,
        "depth_reached": len(levels) - 1,
        "max_depth": max_depth,
        "terminating_cause": levels[-1]["answer"],
        "confidence_at_root": levels[-1]["confidence"],
        "termination_reason": termination,
    }
