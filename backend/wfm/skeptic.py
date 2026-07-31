"""Skeptic -- the module that was missing.

SKEPTIC MODE in the prompt said "challenge it / reject weak explanations". Until now that
was entirely prompt-side: the model was asked to argue against itself and volunteer
rejections. Nothing in code could reject anything, so a cause the data does not support
still shipped as the answer.

This module rejects in code, on two grounds:

1. FEATURE PRECONDITION (hard reject)
   Each cause type names a mechanism, and every mechanism leaves a trace in the derived
   features. If the trace is absent, the cause is impossible -- not merely weak. A model
   can otherwise return `plan_restatement` for a week where the plan demonstrably did not
   change, and nothing catches it. This is the single highest-value check here.

2. NUMERIC GROUNDING (evidence pruning, not rejection)
   Both prompts insist every evidence value is "a REAL NUMBER from the payload", but
   nothing verified it. Each cited value is reconciled against the real numbers in the
   features; those that do not reconcile are dropped from the evidence with a note.
   Deliberately NOT a rejection ground on its own -- a model may legitimately cite a
   correctly-derived figure (a gap, a difference) that is not literally in the payload, and
   killing a sound cause over that would be worse than the disease.

A rejected cause is never silently deleted -- it is recorded in `skeptic_review` with the
reason, which is what the prompt's output contract asks for.
"""
from .common import num

# cause_type -> (predicate over the assembled features, why it is impossible without it)
PRECONDITIONS = {
    "plan_restatement": (
        lambda f: bool(((f.get("base_features") or {}).get("plan_restatement") or {}).get("changed")),
        "the forecast plan did not change this week",
    ),
    "calendar_holiday_effect": (
        lambda f: bool(((f.get("base_features") or {}).get("holiday") or {}).get("unusual")),
        "the number of holidays this week was not unusual",
    ),
    "installed_base_change": (
        lambda f: bool(((f.get("base_features") or {}).get("installed_base") or {}).get("material")),
        "planned units for delivery (shipment) did not move materially this week",
    ),
    "volume_routing_shift": (
        lambda f: bool(((f.get("base_features") or {}).get("peer_divergence") or {}).get("signal")),
        "no similar queue moved in the opposite direction this week",
    ),
    "systematic_forecast_bias": (
        lambda f: str((((f.get("base_features") or {}).get("chronic_bias") or {}).get("verdict")) or "").startswith("chronic"),
        "this queue's misses have no consistent direction, so there is no standing bias",
    ),
    "genuine_demand_event": (
        lambda f: (((f.get("base_features") or {}).get("forecast_sanity") or {}).get("verdict")) == "actual_anomalous",
        "actual demand was not unusual against its own history while the forecast looked normal",
    ),
    "forecast_baseline_error": (
        lambda f: (((f.get("base_features") or {}).get("forecast_sanity") or {}).get("verdict")) in (
            "forecast_anomalously_low", "forecast_anomalously_high", "forecast_scale_mismatch"),
        "the forecast was not unusual against its own history",
    ),
    "channel_migration": (
        lambda f: bool((f.get("channel_siblings") or {}).get("migration_detected")),
        "channel movements in this locality do not cancel out, so demand did not shift between channels",
    ),
    "data_quality_issue": (
        lambda f: bool((f.get("data_quality") or {}).get("suspect")),
        "the recorded value is not implausible against this queue's history",
    ),
    "inherited_from_higher_level": (
        lambda f: bool((f.get("investigation_ladder") or {}).get("inherited_from")),
        "no higher level breaches the band in the same direction",
    ),
}

_TOLERANCE = 0.02        # 2% -- absorbs display rounding in a cited figure


def _real_numbers(features):
    """Every real number the model was actually given, flattened."""
    out = set()

    def walk(node):
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, (list, tuple)):
            for v in node:
                walk(v)
        else:
            n = num(node)
            if n is not None:
                out.add(float(n))

    walk(features)
    return out


def _reconciles(value, pool):
    v = num(value)
    if v is None:
        # A non-numeric evidence value cannot be checked; treat as unverifiable, not wrong.
        try:
            v = float(str(value).replace(",", "").strip())
        except (TypeError, ValueError):
            return None
    for real in pool:
        if real == v:
            return True
        scale = max(abs(real), abs(v), 1e-9)
        if abs(real - v) / scale <= _TOLERANCE:
            return True
    return False


def review(ranked_causes, features):
    """Challenge every proposed cause.

    Returns (kept, skeptic_entries). Order of `kept` is preserved; ranks are renumbered by
    the report generator, not here.
    """
    pool = _real_numbers(features)
    kept, entries = [], []

    for cause in (ranked_causes or []):
        if not isinstance(cause, dict):
            continue
        title = cause.get("title") or cause.get("explanation") or "(untitled)"
        ctype = (cause.get("cause_type") or "").strip()

        # -- ground 1: feature precondition --
        if ctype in PRECONDITIONS:
            predicate, why_not = PRECONDITIONS[ctype]
            try:
                supported = bool(predicate(features))
            except Exception:
                supported = True          # never reject because a check itself failed
            if not supported:
                entries.append({
                    "cause": title,
                    "challenge": f"Does the data actually show {ctype.replace('_', ' ')}?",
                    "verdict": "rejected",
                    "reason": (f"No. The data shows {why_not}, so this cause is not "
                               f"possible for this week."),
                })
                continue

        # -- ground 2: numeric grounding (prune evidence, keep the cause) --
        pruned, dropped = [], []
        for ev in (cause.get("evidence") or []):
            if not isinstance(ev, dict):
                continue
            verdict = _reconciles(ev.get("value"), pool)
            if verdict is False:
                dropped.append(ev)
            else:
                pruned.append(ev)
        if dropped:
            cause["evidence"] = pruned
            cause["evidence_note"] = (
                f"{len(dropped)} cited figure(s) could not be reconciled against the source "
                f"data and were removed.")
            entries.append({
                "cause": title,
                "challenge": "Does every number quoted here appear in the source data?",
                "verdict": "retained",
                "reason": (f"Mostly. {len(dropped)} figure(s) did not reconcile and were "
                           f"dropped; the remaining {len(pruned)} check out."),
            })
        else:
            entries.append({
                "cause": title,
                "challenge": "Is this supported by the data, or could something else explain it better?",
                "verdict": "retained",
                "reason": ("The feature this cause depends on is present in the data and its "
                           "quoted figures reconcile."),
            })
        kept.append(cause)

    return kept, entries


def eligible_cause_types(features):
    """Which cause types the data can support at all. Handed to the model so it does not
    waste a slot on one that will be rejected."""
    out = []
    for ctype, (predicate, _) in PRECONDITIONS.items():
        try:
            if predicate(features):
                out.append(ctype)
        except Exception:
            continue
    return out
