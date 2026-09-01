# Multi-Agent RCA — Architecture Baseline

**Branch:** `test3_langraph` (port 9400) · **Status:** scaffold. No agent has been run.
**Base:** `test3` @ `3ae7ab6`, unmodified. `test3`, `test3_spec`, `test3_sql`, `test3_azure` untouched.

---

## 1. Definition

Three language-model agents in fixed roles, over one shared state, with a **judge** that scores
the result against a named rubric and may demand exactly one revision.

```
Analyst      states the mechanism the evidence supports
Challenger   tries to falsify it, from the SAME evidence
Editor       reconciles both into one report, inside a word budget
Judge        scores against a rubric; one revision, then publish
```

**What it is not:** agents that converse freely until they agree. That is unreproducible,
unbounded in cost, and would rebuild the 86,424-token context this design exists to remove.

---

## 2. The boundary that makes this safe

Every figure on the card is computed by deterministic Python **before any model is called** —
`spec_engine.py:902-1369`, first model call at `:1373`. Adherence, accuracy, criticality band,
holiday phases, driver gates, 23 hypotheses, 8 confidence dimensions: all of it.

| Agents may affect | Agents may never affect |
|---|---|
| wording, ordering, selection, length | the value of any figure |
| whether a claim is *stated* | whether a figure is *correct* |

So the worst a bad agent can do is write a bad sentence. It cannot produce a wrong number.
This is the property that makes multi-agent acceptable here at all, and it is why the judge's
rubric deliberately does **not** include "is this accurate" — that is settled upstream, in code.

---

## 3. Why not a framework

LangGraph earns its keep on branching, cycles, checkpointing and human-in-the-loop interrupts.
This is a fixed sequence with one bounded revision. A LangGraph spike on an earlier branch
produced the same shape of result; the graph was not the variable.

Against that, the engine's four dependencies — fastapi, uvicorn, pyodbc, openpyxl — are a
deliberate asset, and LangGraph pulls in twenty-odd transitive packages.

**Decision: plain Python, LangGraph-shaped.** Typed state, node functions, explicit edges. If a
later pillar genuinely needs cycles or checkpointing, lifting these nodes into LangGraph is
mechanical rather than a redesign. Three more RCA pillars are planned — scheduling, real-time
adherence, capacity planning — and they are *more of the same shape*, not more complex graphs.

---

## 4. Workflow

```
      SQL ──> 33 deterministic evidence modules      (unchanged)
                            │
                     scope extractor                 declared fields only
                            │
                            ▼
                         ANALYST                       <2,000 tokens
                   names ONE mechanism                 sees: evidence slice only
                            │
                            ▼
                       CHALLENGER                      <2,500 tokens
                  tries to falsify it                  sees: the SAME evidence
                            │                                 PLUS the Analyst's claim
                            ▼
                    SHARED STATE  (the blackboard)
                            │
                      DETERMINISTIC GATES             cost nothing, run first
                            │
                            ▼
                         EDITOR                        <2,000 tokens
                            │
                      DETERMINISTIC GATES              again, on the output
                            │
                            ▼
                          JUDGE                        <3,000 tokens
                            │
                 ┌──────────┴──────────┐
                 ▼                     ▼
           pass: publish       fail: ONE revision, then publish
                                      with the judge's note attached
```

**Analyst and Challenger see the same evidence.** A challenger given *different* evidence
produces disagreements that are artefacts of context, not of reasoning — which is worse than no
challenger, because the disagreement looks meaningful.

**They do not run concurrently.** An earlier draft of this diagram said they did. They cannot:
the Challenger is handed the Analyst's mechanism and magnitude claim so it has something specific
to falsify, which makes the order a hard dependency. Every stage is sequential. See `WORKFLOW.md`
for the full trace and for what "agent to agent" does and does not mean here.

---

## 5. Cost, against what runs today

Measured on `mode=spec`, `Social Media English Basic` FW202637:

| Today | Tokens |
|---|---|
| Narrative | 86,424 |
| Interrogation ask | 87,275 |
| Answers ×3 | 5,316 |
| Summary | 1,345 |
| **Total per investigation** | **180,360** |

| Proposed | Tokens |
|---|---|
| Analyst | <2,000 |
| Challenger | <2,500 |
| Editor | <2,000 |
| Judge | <3,000 |
| One revision, worst case | <2,000 |
| **Total** | **<11,500** |

**~94% less, with twice the agents.** The cost was never the agent count — it was handing each
call the whole 292,308-character finding object. These are declared ceilings, not measurements;
nothing has been run yet.

---

## 6. The judge rubric

Most of what a judge would check is better done in code, where it cannot be lenient. The
deterministic gates run **first**, so the judge is only ever asked about a report that already
passes them.

| Factor | Deterministic | Judge |
|---|---|---|
| Every number appears in the evidence | ✅ reuse `narrative_prompt._matches_supplied` | |
| Length within budget | ✅ | |
| No causal verbs — "caused", "drove", "led to" | ✅ existing check | |
| No statistical jargon | ✅ reuse `_jargon_in` | |
| No fact printed twice | ✅ say-once registry | |
| Every SUPPORTED finding is addressed | ✅ set comparison | |
| The NOT-ASSESSED count is accurate | ✅ from the trigger evaluator | |
| **Two sections contradict each other** | | ✅ |
| **Hedging matches the confidence score** | | ✅ |
| **The recommendation follows from the cause** | | ✅ |
| **Readable by a lead in thirty seconds** | | ✅ |

Only four factors genuinely need a model.

The contradiction factor is not hypothetical: a live card was found asserting and denying the
same mechanism in bullets 4 and 8, because each described a different gate with nothing
reconciling them. Code cannot catch that; a judge can.

**Judge output is structured, never a score.** `{factor, verdict, evidence, severity}` per
factor. A bare 1-10 is unauditable, and LLM judges drift high. **A verdict citing no evidence is
void** — treated as "not assessed", not as a pass.

---

## 7. Reproducibility

The current engine is measurably not reproducible: the same queue-week produced 26,114 words on
one run and 24,986 on the next, 4 questions then 3, 180.0s then 311.2s. Adding agents makes that
worse unless the orchestration is deterministic.

Rules, all enforced in code:

1. **No model decides which agents run.** Roles and order are fixed.
2. **Bounded loops.** Exactly one revision. Never "until the judge is satisfied".
3. **Temperature 0** for Analyst, Editor and Judge. The Challenger runs at 0.3 — it is the one
   role where a little variance is the point.
4. **Declared reads.** An agent sees another's *conclusion*, never its prose.
5. **Budgets in code, not prompts.** Over budget: retry once, then fall back to the headline.

---

## 8. Models

Assigned by **role**, not by name — see `backend/agents/models.py`.

| Role | Model | Tier |
|---|---|---|
| Analyst | `openai/gpt-oss-120b` | production |
| Challenger | `openai/gpt-oss-120b` | production |
| Editor | `openai/gpt-oss-20b` | production |
| Judge | `openai/gpt-oss-120b` | production |

### The reason this file exists

On 2026-09-02 the project's configured Groq model was `llama-3.3-70b-versatile`, **shutdown
2026-08-16 — seventeen days earlier.** Groq's own models page still listed it as production. No
code noticed, and none could have: it was a string in `config.json` that nothing checked.

Groq's deprecation table lists 36 retired models. So the registry declares models by role,
records every retirement with its date and replacement so nobody re-adds one from memory, and
`verify_live()` asks the provider what actually exists. Run it at startup and on deploy.

**A known weakness, stated rather than hidden.** Analyst and Challenger share the gpt-oss
family, because Groq retired every Llama chat model and the only cross-family option — Qwen — is
marked preview, evaluation-only. Two instances of one model over identical evidence agree more
than two families would. **The Challenger's dissent rate must be measured, not assumed.** If it
rarely dissents, the fix is a different family — `qwen/qwen3.6-27b`, or the client-side Llama 3
70B endpoint — not a stronger prompt.

`groq/compound` and `compound-mini` offer provider-side tool use. Deliberately unused: they make
a call's behaviour depend on tools we do not control, which is the opposite of what this design
is buying.

---

## 9. Prerequisites — in this order

Adding agents on top of these would bury the signal.

| # | Prerequisite | Why | Status |
|---|---|---|---|
| 1 | **Fix the provider chain** | `_FAST_FIRST = ("groq","nvidia")` routes every interrogation call to a 403-blocked provider first, then to a reasoning model that leaks its thinking into `content` and timed out, losing a question. Multi-agent multiplies this. | not started |
| 2 | **Replace the dead Groq model** | `llama-3.3-70b-versatile` shut down 2026-08-16 | detected by `audit_config()` |
| 3 | **Say-once registry** | 18,451 words — 69.5% of the current output — is reprinted deterministic strings | designed on `test3_spec` |
| 4 | **Scope extractor** | what makes 11,500 tokens possible instead of 180,360 | designed on `test3_spec` |
| 5 | The agents | | this branch |

---

## 10. Reused, not rebuilt

The engine is already ~40% of a multi-agent system; the roles exist but are unnamed.

| Existing | Becomes |
|---|---|
| `why_prompt` ask → answer with a gate | two agents with a validation handoff |
| the repair call at `spec_engine.py:1625` | the revision loop |
| `validate_answers()` | a judge with veto power |
| `skeptic.py` | part of the Challenger's deterministic backing |
| cross-call dedup | the "two agents collapsed onto one answer" check |
| `_relevant_blocks()` at `why_prompt.py:464` | the scope extractor — **measured: narrows 4-5 of 11 blocks** |
| the grounding guard | gate 1, unchanged and shared |

---

## 11. Failure modes

| Risk | Evidence it is real | Mitigation |
|---|---|---|
| Reproducibility worsens | already broken — see §7 | deterministic orchestration, bounded loops, temp 0 |
| Latency | already 311.2s | Analyst ∥ Challenger; judge only after gates pass |
| Provider capacity | Groq 403 from AA network; a daily token cap | at ~11,500 tokens per investigation, budget the cap before rollout |
| Judge rubber-stamps | LLM judges drift lenient | gates first; every verdict must cite evidence or it is void |
| Infinite critique | — | exactly one revision, then publish with the note |
| Manufactured disagreement | same-family caveat, §8 | measure dissent rate; a challenger that always dissents is as useless as one that never does |

---

## 12. What exists on this branch right now

```
backend/agents/
  models.py          the registry, role assignment, audit_config(), verify_live()
  prompts/           (empty — awaiting approval of this baseline)
ARCHITECTURE_BASELINE.md   this file
IMP_DOCS/multi-agent-architecture.md   the IMP_DOCS entry
```

Nothing is wired into the engine. `POST /api/rca-investigate` behaves exactly as on `test3`.
Nothing is committed.

## 13. Next, once this baseline is approved

1. `state.py` — the typed shared state and its contract
2. `nodes.py` — the four roles as node functions over that state
3. `graph.py` — fixed-order orchestration, concurrency for Analyst ∥ Challenger
4. `rubric.py` — deterministic gates, then the four judge factors
5. `prompts/*.md` — one per role, each told explicitly what it cannot see
6. A fifth mode, `?mode=agents`, so `spec`, `wfm` and `legacy` keep working untouched
7. Tests: dissent rate, judge citation compliance, budget enforcement, reproducibility across
   two identical runs
