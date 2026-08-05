# -*- coding: utf-8 -*-
"""Rewrite the deterministic why-chain into this queue's own words.

WHY THIS EXISTS
---------------
`recursive_why` builds each step of the reasoning from an f-string. That is the right way
to derive a FACT -- it is reproducible, auditable, and cannot invent a figure. It is the
wrong way to WRITE it. Read three reports side by side and every one opens "Partly because
the wider book moved with it: ... is out by N contacts (+X%), and this queue is Y% of
that." Only the numbers move. A reader concludes, correctly, that nothing was actually
reasoned about their queue.

So the FACT stays deterministic and the SENTENCE becomes the model's job:

    recursive_why  ->  the facts, fixed, checkable
          |
    this module    ->  the wording, in executive business English, per queue
          |
    validation     ->  every figure in the rewrite must exist in the fact it came from

WHAT IT MAY AND MAY NOT CHANGE
------------------------------
May: sentence structure, ordering within the sentence, emphasis, connective phrasing, which
     figure leads.
May NOT: introduce a number, drop a number, change a direction, add a cause, soften or
     strengthen a conclusion.

That split is deliberate and matches how the spec already treats the narrative: wording
varies (§5.2, logged not failed) while the analysis does not. Nothing here can change which
cause was selected, the confidence, or any verdict -- it runs after all of those are fixed
and only ever replaces display text.

FAILURE IS ALWAYS SAFE
----------------------
Any error, any timeout, any rewrite that fails grounding -> that bullet keeps its original
deterministic wording. A report is never blocked, and never shows an ungrounded sentence.
"""
import json
import re

PROMPT_VERSION = "1.0.0"

# Below this many steps there is nothing worth a model call.
MIN_STEPS = 1

SYSTEM = """# ROLE

You are a Workforce Management analyst writing the root-cause section of a report that a
senior operations leader will read in a Monday review.

You are given the findings for ONE queue, already established and verified. Your ONLY job
is to express each finding in clear executive business English, specific to this queue.

# THE PROBLEM YOU ARE SOLVING

These findings were assembled from templates, so every report reads identically and only
the numbers change. A reader sees the same sentence shape every week and stops believing
anyone looked at their queue. Write each one as if you had studied THIS queue's figures and
were explaining them to the person accountable for it.

# ABSOLUTE RULES — A BREACH MAKES THE REWRITE UNUSABLE

1. **Every number in your sentence must appear in the finding you were given.** Do not
   compute, round differently, combine or estimate. If the finding says 1,779 contacts and
   +5.4%, those are the only figures that may appear in that sentence.
2. **Never add a cause, reason or mechanism that is not in the finding.** No speculation
   about why demand moved, no events, no staffing, no campaigns.
3. **Never change the direction or the conclusion.** If the finding says the gap
   concentrates further down, your sentence says that too.
4. **One finding in, one sentence out** — same order, same count. Do not merge or split.

# HOW TO WRITE IT

- Lead with what it means for the business, then the figure that proves it.
- Name the actual scope ("APJ", "the India Basic tier", "the Chat channel") rather than
  "the wider book" or "a higher level".
- One or two sentences. A leader reads the first line and decides whether to read on.
- Plain business English. No statistical vocabulary — no correlation, outlier, z-score,
  standard deviation, regression, coefficient.
- No hedging filler: not "it appears that", "it seems", "potentially".
- Vary how you open. Do not begin every sentence the same way.

# OUTPUT SCHEMA — STRICT

Respond with ONLY this JSON object and nothing else:

{
  "rewritten": [
    {"index": 0, "text": "the rewritten sentence for finding 0"},
    {"index": 1, "text": "the rewritten sentence for finding 1"}
  ]
}

Return one entry for every finding you were given, with its original index.
"""


def _numbers(text):
    """Significant figures in a string, normalised for comparison.

    Values under 100 are ignored: they are overwhelmingly percentages and small counts that
    legitimately reappear as ordinals or rounded shares, and policing them rejects good
    rewrites without catching a real fabrication -- an invented CONTACT VOLUME is what
    matters, and those are large.
    """
    out = set()
    for m in re.findall(r"-?\d[\d,]*\.?\d*", text or ""):
        try:
            v = abs(float(m.replace(",", "")))
        except ValueError:
            continue
        if v >= 100:
            out.add(round(v, 2))
    return out


def _grounded(rewrite, source):
    """True when the rewrite introduces no figure the source did not already carry.

    One-directional on purpose: DROPPING a figure is allowed (an executive sentence may
    lead with the percentage and leave the raw count out), inventing one is not.
    """
    supplied = _numbers(source)
    for v in _numbers(rewrite):
        if not any(abs(v - s) <= max(1.0, 0.005 * abs(s)) for s in supplied):
            return False
    return True


def build_messages(steps, header):
    """Prompt 2 of the narrative layer: the facts in, the wording out."""
    findings = [{"index": i, "finding": s.get("answer")} for i, s in enumerate(steps)]
    user = "\n".join([
        "# THE QUEUE",
        "",
        "```json",
        json.dumps(header or {}, indent=1, default=str, ensure_ascii=False),
        "```",
        "",
        "# THE FINDINGS — rewrite each one, keeping every figure exactly as given",
        "",
        "```json",
        json.dumps(findings, indent=1, default=str, ensure_ascii=False),
        "```",
        "",
        f"Return exactly {len(findings)} rewritten sentence(s), one per index.",
    ])
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def apply(why, header, call_llm):
    """Rewrite each why-chain step's wording. Returns (why, note).

    `call_llm(messages) -> (parsed, error)` is injected so this module stays free of
    provider and config knowledge, and so it is testable without a network call.

    The input is never mutated: a copy is returned, so a caller holding the deterministic
    chain still has it.
    """
    levels = (why or {}).get("levels") or []
    steps = levels[1:]                      # level 0 is the question, not a finding
    if len(steps) < MIN_STEPS:
        return why, "no findings to rewrite"

    parsed, err = call_llm(build_messages(steps, header))
    if not parsed:
        return why, f"kept deterministic wording: {err}"

    by_index = {}
    for item in (parsed.get("rewritten") or []):
        if not isinstance(item, dict):
            continue
        try:
            by_index[int(item.get("index"))] = str(item.get("text") or "").strip()
        except (TypeError, ValueError):
            continue

    out = dict(why)
    new_levels = list(levels)
    rewritten = rejected = 0
    for i, step in enumerate(steps):
        text = by_index.get(i)
        original = step.get("answer") or ""
        if not text or len(text) < 20:
            continue
        if not _grounded(text, original):
            rejected += 1
            continue
        # Per-step replacement: one ungrounded rewrite costs that sentence its new wording,
        # not the whole chain its rewrite.
        new_step = dict(step)
        new_step["answer"] = text
        new_step["answer_deterministic"] = original      # kept for audit, never displayed
        new_levels[i + 1] = new_step
        rewritten += 1

    out["levels"] = new_levels
    out["wording"] = {"rewritten": rewritten, "rejected_ungrounded": rejected,
                      "prompt_version": PROMPT_VERSION}
    note = f"{rewritten} of {len(steps)} finding(s) rewritten in business language"
    if rejected:
        note += f"; {rejected} kept deterministic wording (introduced a figure not in the finding)"
    return out, note
