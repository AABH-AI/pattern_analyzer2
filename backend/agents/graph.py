# -*- coding: utf-8 -*-
"""Orchestration: strictly sequential, one bounded revision.

Analyst -> Challenger -> Editor -> Judge, and on a blocking verdict Editor -> Judge once
more. Nothing runs in parallel: the `concurrent_pair` switch submits the Challenger to a
ThreadPoolExecutor with max_workers=1 and immediately blocks on the result, so both
branches behave identically. The switch is kept for a future variant in which the
Challenger is given only the evidence -- then, and only then, the pair could run at the
same time. Today the Challenger reads the Analyst's claim, so it cannot.

WHY THE ORDER IS IN CODE AND NOT DECIDED BY A MODEL
---------------------------------------------------
The existing engine is measurably not reproducible: the same queue-week produced 26,114 words on
one run and 24,986 on the next, 4 interrogation questions then 3, 180.0s then 311.2s. Letting a
model decide which agents run, or how many times, would make that worse. So:

  * roles and order are fixed here
  * exactly ONE revision, never "until the judge is satisfied"
  * temperature 0 everywhere except the Challenger, the one role where variance is the point
  * deterministic gates run BEFORE the judge, so the judge is only ever asked about a report
    that already passes the mechanical checks and cannot be lenient about them

This is written as nodes over a shared state precisely so it can be lifted into LangGraph later
without redesign, if a further RCA pillar needs cycles or checkpointing. It does not need them.
"""
import concurrent.futures
import time

from . import models as M
from . import nodes
from .state import AgentState


def run(queue, fiscal_week, evidence, figures, headline, api_key,
        concurrent_pair=True, allow_revision=True, overrides=None):
    """Run the four roles over one investigation. Returns the AgentState.

    `overrides` maps a role name to a partial config, so a caller can try a different model for
    one role without touching the registry -- which is how the Challenger's dissent rate gets
    measured across model families.
    """
    overrides = overrides or {}

    def spec(role_name):
        s = M.role(role_name)
        s.update(overrides.get(role_name) or {})
        return s

    state = AgentState(queue, fiscal_week, evidence, figures, headline)
    t0 = time.time()

    # --- 1. Analyst. The Challenger needs its claim, so this one is not optional. -------------
    nodes.analyst(state, api_key, spec("analyst"))
    if state.analyst is None:
        state.errors.append("analyst produced nothing -- stopping, there is nothing to challenge "
                            "or edit")
        state.timings["total"] = round(time.time() - t0, 2)
        return state

    # --- 2. Challenger ------------------------------------------------------------------------
    # NOTE: this branch is NOT parallel, despite the flag's name and its True default. The pool
    # has one worker and .result() is awaited immediately, so the Challenger still runs after the
    # Analyst has finished -- which is required, because it reads the Analyst's claim. The switch
    # is kept for a future variant that gives the Challenger only the evidence; that variant could
    # genuinely run the pair at once and save a round trip. Measured cost of the thread hop: nil.
    if concurrent_pair:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(nodes.challenger, state, api_key, spec("challenger"))
            fut.result()
    else:
        nodes.challenger(state, api_key, spec("challenger"))

    # --- 3. Editor ----------------------------------------------------------------------------
    nodes.editor(state, api_key, spec("editor"))
    if state.report is None:
        state.errors.append("editor produced nothing -- no report to judge")
        state.timings["total"] = round(time.time() - t0, 2)
        return state

    # --- 4. Judge -----------------------------------------------------------------------------
    nodes.judge(state, api_key, spec("judge"))

    # --- 5. One revision, if the judge raised something BLOCKING ------------------------------
    # Driven by a blocking factor, not by the judge's own "overall" verdict. A judge that flags a
    # contradiction and then says "publish" cannot wave it through.
    if allow_revision and state.verdict:
        blocking = state.verdict.get("_blocking") or []
        if blocking:
            instruction = (state.verdict.get("revision_instruction") or "").strip()
            if not instruction:
                instruction = "; ".join(
                    "%s: %s" % (b.get("factor"), b.get("note") or "fix this")
                    for b in blocking)
            state.revision_count = 1
            before = state.report
            nodes.editor(state, api_key, spec("editor"),
                         extra_instruction=("A reviewer found a blocking problem with your "
                                            "previous version. Fix exactly this and change "
                                            "nothing else:\n" + instruction))
            if state.report is None:            # the revision failed; keep what we had
                state.report = before
                state.errors.append("revision failed -- keeping the pre-revision report")
            else:
                # Re-judge once so the published report carries an accurate verdict, rather than
                # the verdict of a version nobody will read.
                nodes.judge(state, api_key, spec("judge"))

    state.timings["total"] = round(time.time() - t0, 2)
    return state


def publishable(state):
    """Should this be shown to a lead, and with what caveat?

    Never "no". A lead who clicked Investigate gets something -- withholding the report leaves
    them with nothing, which is worse than a report carrying a visible note.
    """
    if state.report is None:
        return False, "no report was produced"
    blocking = ((state.verdict or {}).get("_blocking") or [])
    if blocking and state.revision_count:
        return True, ("published with an unresolved reviewer note: %s"
                      % "; ".join(b.get("factor") for b in blocking))
    if blocking:
        return True, "published with a reviewer note"
    if state.gate_failures:
        return True, "published; %d automated check(s) flagged" % len(state.gate_failures)
    return True, "clean"
