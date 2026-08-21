# -*- coding: utf-8 -*-
"""The third LLM call: a short summary of a finished investigation.

WHY IT EXISTS
-------------
Measured on a captured card: about 32,000 characters of visible text, roughly 11 A4 pages, with the
four largest sections making up 56% of it. The feedback from leads was that the output is too long to
act on. Tabs shorten the page; this shortens the *reading*.

WHAT IT IS FED, AND WHAT IT IS NOT
----------------------------------
Deterministic figures only: the headline numbers, the ranked why-bullets as the engine wrote them, the
root cause, confidence, criticality, and the statistical measures that actually fed the conclusion.

It is NOT fed the narrative from call 1 or the interrogation prose from call 2. That is the whole point
of the choice. Summarising another model's prose lets an error from the first call return as an
established fact in the third, with rounded figures rounded again -- and the summary is the part a lead
is most likely to quote onward, so it is the worst place for an inherited mistake.

The same numeric grounding guard as the narrative applies, for the same reason: a figure that is not in
the inputs is the one error that would make the report lie.
"""
from __future__ import annotations

SUMMARY_PROMPT_VERSION = "1.0.0"

_SYSTEM = (
    "You write the one-paragraph summary a workforce-management lead reads before deciding whether "
    "to open the full investigation.\n"
    "\n"
    "RULES, all of them hard:\n"
    "1. Every number you write must appear in the input. Do not compute, combine or re-derive "
    "anything. Rounding a supplied figure is fine; inventing one is not.\n"
    "2. Do not use causal verbs -- caused, drove, generated, resulted in, led to. The evidence "
    "supports a mechanism; it does not prove causation. Write 'is consistent with', 'the evidence "
    "supports', 'coincided with'.\n"
    "3. No statistical jargon. No p-values, coefficients, r-values, z-scores, sigma or 'correlation'. "
    "A lead should not need a statistics course.\n"
    "4. State what is NOT settled if the input says so. A summary that sounds more certain than the "
    "evidence is worse than no summary.\n"
    "5. Plain past tense, active voice, no preamble, no bullet points, no headings.\n"
    "\n"
    "Return ONLY JSON: {\"summary\": \"...\", \"headline\": \"...\", \"watch_next\": \"...\"}\n"
    "  summary   3-5 sentences. What missed, by how much, what the evidence supports, what is unclear.\n"
    "  headline  one sentence under 110 characters, the single thing to know.\n"
    "  watch_next  one sentence: the one thing to check next week. Say 'nothing specific' if the "
    "input does not support naming one."
)


def build_summary_messages(result):
    """Assemble the third call's input from deterministic fields only."""
    fs = result.get("forecast_summary") or {}
    rc = result.get("root_cause") or {}
    conf = result.get("confidence") or {}
    crit = result.get("criticality") or {}
    card = (result.get("decision_card") or {}).get("sections") or {}
    prof = card.get("19_statistical_profile") or {}

    lines = []
    q = result.get("queue") or {}
    lines.append("QUEUE: %s, fiscal week %s" % (q.get("Forecast_name") or "?",
                                                q.get("Fiscal_Week") or "?"))
    lines.append("HEADLINE FIGURES")
    for label, key in (("forecast", "forecast"), ("actual", "actual"),
                       ("adherence_pct", "adherence_pct"), ("variance", "variance"),
                       ("direction", "direction")):
        if fs.get(key) is not None:
            lines.append("  %s: %s" % (label, fs.get(key)))

    lines.append("MECHANISM: %s" % ((result.get("miss_mechanism") or {}).get("primary") or "not resolved"))
    lines.append("ROOT CAUSE: %s" % (rc.get("hypothesis") or rc.get("cause_type") or "not resolved"))
    if rc.get("statement"):
        lines.append("  statement: %s" % rc["statement"])
    lines.append("CONFIDENCE: %s (%s%%)" % (conf.get("band") or "?", conf.get("score_pct")))
    lines.append("CRITICALITY: %s" % (crit.get("band") or "?"))

    bullets = (card.get("12_why_this_happened") or {}).get("bullets") or []
    if bullets:
        lines.append("RANKED REASONS, strongest first, as the engine wrote them:")
        for i, b in enumerate(bullets[:6], 1):
            t = b.get("text_deterministic") or b.get("text") or b.get("what_happened") or ""
            if t:
                lines.append("  %d. %s" % (i, str(t)[:420]))

    used = [r for r in (prof.get("rows") or []) if r.get("fed_the_conclusion") and r.get("reading")]
    if used:
        lines.append("STATISTICAL MEASURES THAT FED THE CONCLUSION:")
        for r in used[:5]:
            lines.append("  %s: %s" % (r.get("label"), str(r.get("reading"))[:300]))

    lims = card.get("8_limitations") or []
    if lims:
        lines.append("WHAT COULD NOT BE ASSESSED:")
        for l in list(lims)[:4]:
            lines.append("  - %s" % str(l)[:220])

    return [{"role": "system", "content": _SYSTEM},
            {"role": "user", "content": "\n".join(lines)}]


def validate_summary(parsed, result):
    """Schema plus the same numeric grounding the narrative uses.

    Reusing `narrative_prompt`'s number extraction and tolerance deliberately: two grounding rules
    that could drift apart would eventually disagree about the same figure on the same card, and the
    looser one would be the one that shipped.
    """
    from . import narrative_prompt as npmod

    errors = []
    if not isinstance(parsed, dict):
        return False, ["response was not a JSON object"]
    for k in ("summary", "headline"):
        if not str(parsed.get(k) or "").strip():
            errors.append("missing or empty '%s'" % k)
    head = str(parsed.get("headline") or "")
    if len(head) > 160:
        errors.append("headline is %d characters, over the 160 limit" % len(head))

    verbs = [v for v in ("caused", "drove", "generated", "resulted in", "led to")
             if (" %s " % v) in (" " + " ".join(str(parsed.get(k) or "") for k in
                                                ("summary", "headline", "watch_next")).lower() + " ")]
    if verbs:
        errors.append("causal verb(s) used, which the evidence does not support: %s" % ", ".join(verbs))

    # Exactly how narrative_prompt.validate does it: every number anywhere in the result object is
    # "supplied". Deliberately the same call rather than a parallel implementation -- two grounding
    # rules would drift, and the looser of the two is the one that would ship.
    import json as _json
    supplied = npmod._numbers_in(_json.dumps(result, default=str))
    written = set()
    for k in ("summary", "headline", "watch_next"):
        written |= npmod._numbers_in(str(parsed.get(k) or ""))
    bad = sorted(w for w in written if not npmod._matches_supplied(w, supplied))
    if bad:
        errors.append("contains number(s) absent from the inputs: %s"
                      % ", ".join(str(b) for b in bad[:6]))
    return (not errors), errors
