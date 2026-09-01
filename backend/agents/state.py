# -*- coding: utf-8 -*-
"""The shared state the agents read and write. The blackboard.

WHY A DECLARED STATE OBJECT RATHER THAN PASSING DICTS AROUND
------------------------------------------------------------
Two reasons, both learned from the existing engine.

First, an agent must not see another agent's prose. When the narrative call was handed the whole
finding object -- 292,308 characters -- it had 86,424 tokens to scan and produced text that
contradicted itself across sections. Declaring what each role may read makes that impossible by
construction rather than by discipline.

Second, this is the shape LangGraph wants if we ever move to it: one typed state, nodes that
take it and return a partial update. Building it this way now means that move is mechanical.

WHAT IS AND IS NOT IN HERE
--------------------------
`evidence` is a SLICE of the deterministic finding, never the whole thing. `figures` is the set
of numbers any agent is allowed to use -- the grounding guard checks written prose against it.
Nothing in this state is computed by a model.
"""


class AgentState(object):
    """One investigation's worth of shared state.

    Deliberately a plain object with named attributes rather than a free dict: a typo in a dict
    key fails silently at 3am, an attribute typo fails immediately.
    """

    __slots__ = (
        # --- inputs, all deterministic --------------------------------------------------------
        "queue", "fiscal_week", "evidence", "figures", "headline",
        # --- agent outputs --------------------------------------------------------------------
        "analyst", "challenger", "report", "verdict",
        # --- bookkeeping ----------------------------------------------------------------------
        "calls", "gate_failures", "revision_count", "errors", "timings",
    )

    def __init__(self, queue, fiscal_week, evidence, figures, headline):
        self.queue = queue
        self.fiscal_week = fiscal_week
        self.evidence = evidence            # scoped dict -- NOT the whole finding
        self.figures = figures              # {str} of permitted numbers, as written
        self.headline = headline            # the deterministic one-liner, never model-written

        self.analyst = None                 # {"claim","mechanism","figures_used","confidence"}
        self.challenger = None              # {"dissents","objection","weakest_link","figures_used"}
        self.report = None                  # {"what_happened","why","how_sure","do_this","not_assessed"}
        self.verdict = None                 # [{"factor","verdict","evidence","severity"}]

        self.calls = []                     # one record per model call, for cost and audit
        self.gate_failures = []             # deterministic checks that failed
        self.revision_count = 0
        self.errors = []
        self.timings = {}

    # -- what each role is allowed to see ------------------------------------------------------
    def for_analyst(self):
        """The Analyst sees the evidence slice and nothing else. No other agent's output."""
        return {"queue": self.queue, "fiscal_week": self.fiscal_week,
                "headline": self.headline, "evidence": self.evidence}

    def for_challenger(self):
        """The Challenger sees the SAME evidence plus the Analyst's claim.

        The same evidence is the point. A challenger given different evidence produces
        disagreements that are artefacts of context rather than of reasoning, which is worse
        than no challenger because the disagreement looks meaningful.
        """
        a = self.analyst or {}
        return {"queue": self.queue, "fiscal_week": self.fiscal_week,
                "headline": self.headline, "evidence": self.evidence,
                "analyst_mechanism": a.get("mechanism"),
                "analyst_claim": a.get("claim"),
                "analyst_says_it_accounts_for": a.get("accounts_for"),
                "analyst_says_that_is_enough": a.get("is_it_enough"),
                "analyst_detail": a.get("mechanism_detail"),
                "analyst_confidence": a.get("confidence")}

    def for_editor(self):
        """The Editor sees both findings and NOT the raw evidence.

        Withholding the evidence is deliberate: the Editor's job is ordering and compression, and
        an editor with access to the evidence starts doing analysis of its own, which is how a
        report ends up asserting something neither the Analyst nor the Challenger said.
        """
        return {"queue": self.queue, "fiscal_week": self.fiscal_week,
                "headline": self.headline,
                "analyst": self.analyst, "challenger": self.challenger}

    def for_judge(self):
        """The Judge sees the report and the findings it came from, to check faithfulness."""
        return {"headline": self.headline, "report": self.report,
                "analyst": self.analyst, "challenger": self.challenger}

    # -- bookkeeping ---------------------------------------------------------------------------
    def record_call(self, role, model, ok, seconds, usage=None, error=None):
        self.calls.append({"role": role, "model": model, "ok": ok,
                           "seconds": round(seconds, 2),
                           "prompt_tokens": (usage or {}).get("prompt_tokens"),
                           "completion_tokens": (usage or {}).get("completion_tokens"),
                           "total_tokens": (usage or {}).get("total_tokens"),
                           "error": error})

    def total_tokens(self):
        return sum(c.get("total_tokens") or 0 for c in self.calls)

    def summary(self):
        return {
            "queue": self.queue, "fiscal_week": self.fiscal_week,
            "calls": len(self.calls),
            "failed_calls": len([c for c in self.calls if not c["ok"]]),
            "total_tokens": self.total_tokens(),
            "seconds": round(sum(c["seconds"] for c in self.calls), 2),
            "challenger_dissented": bool((self.challenger or {}).get("dissents")),
            "gate_failures": self.gate_failures,
            "revisions": self.revision_count,
            "errors": self.errors,
        }
