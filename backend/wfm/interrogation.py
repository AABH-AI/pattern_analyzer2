# -*- coding: utf-8 -*-
"""Interrogation -- Prompt 2 asks WHY of the generated bullets, Prompt 1 answers from evidence.

Kept in its own module rather than inside `investigation_engine.py` for one reason: it must
be possible to delete this file and have the engine behave exactly as it did before. It is
an addition to the report, never a participant in producing it.

WHERE IT SITS
-------------
    engine produces the report   ranked causes, confidence, skeptic verdicts -- all FIXED
              |
    interrogation runs           reads those bullets, asks what they leave unexplained
              |
    answers come from evidence   never from the model's memory of what it just wrote

Because it runs AFTER the report is complete, it cannot change a conclusion. That ordering
is the whole basis for adding it without altering the engine's output.

THE TWO SEPARATIONS THAT MAKE IT WORK
--------------------------------------
1. The QUESTIONER and the ANSWERER are different calls. Asking a model "why did you say
   that?" gets an answer from recall, and it will always produce something fluent rather
   than admit it cannot support the claim. The answerer here never sees the questioner's
   reasoning -- only the question and the evidence.

2. ONE CALL PER QUESTION. Batched, the model switches between unrelated retrieval tasks
   inside a single generation and collapses onto whichever finding is most striking. That
   is how two different questions came back with the same answer on the previous branch.

Every failure path leaves the report untouched. An LLM failure never blocks an RCA.
"""
import json

from .llm_client import chat_json, timeout_from_config
from . import why_prompt

# Fastest first. Measured on this deployment: the same interrogation took ~3s on Groq and
# 220s+ on the NVIDIA reasoning models. This is comprehension work, not the hardest
# reasoning in the run, so latency matters more than depth.
_FAST_FIRST = ("groq", "nvidia")

MIN_WEEKS_TO_INTERROGATE = 4


def _call(messages, llm_cfg, model_choice, endpoints, defaults, slot_for_choice):
    """One provider call -> (parsed, error). Never raises."""
    slots = []
    if model_choice and model_choice.get("model"):
        picked = slot_for_choice(model_choice, llm_cfg)
        if picked:
            # An explicit choice is honoured exactly -- never silently answered by a
            # different model, or comparing models means nothing.
            slots = [picked]
    if not slots:
        slots = [(llm_cfg or {}).get("primary") or {}, (llm_cfg or {}).get("secondary") or {}]
        slots = [s for s in slots if s.get("provider") and s.get("api_key")]
        slots.sort(key=lambda sl: _FAST_FIRST.index(sl.get("provider"))
                   if sl.get("provider") in _FAST_FIRST else len(_FAST_FIRST))
    if not slots:
        return None, "no LLM provider configured"

    last = "unknown"
    timeout = timeout_from_config(llm_cfg)
    for slot in slots:
        endpoint = slot.get("endpoint") or endpoints.get(slot.get("provider"))
        model = slot.get("model") or defaults.get(slot.get("provider"))
        if not endpoint:
            continue
        try:
            return chat_json(endpoint, slot["api_key"], model, messages, timeout=timeout), None
        except Exception as exc:
            last = f"{slot.get('provider')}/{model}: {exc}"
    return None, last


def _bullets_from(result):
    """The bullets the report ACTUALLY produced -- what gets interrogated.

    Prompt 2 questions these, not an idealised summary. If the engine did not say it, it
    does not get asked about.
    """
    causes = [c for c in (result.get("ranked_root_causes") or []) if isinstance(c, dict)]
    top = causes[0] if causes else None
    return {
        "root_cause": ({"statement": top.get("explanation") or top.get("title"),
                        "hypothesis": top.get("title"),
                        "cause_type": top.get("cause_type"),
                        "confidence_pct": top.get("confidence_pct")} if top else None),
        "other_causes": [{"title": c.get("title"), "explanation": c.get("explanation")}
                         for c in causes[1:4]],
        "executive_summary": result.get("executive_summary"),
        "key_findings": [e.get("text") for e in (result.get("supporting_evidence") or [])
                         if isinstance(e, dict) and e.get("text")][:6],
        "recommendations": result.get("forecast_improvement_recommendations"),
    }


def _evidence_bundle(result, features):
    """Everything the answerer may use. Nothing else reaches it.

    THIS MUST MIRROR `_payload()`. Every block the QUESTIONER can see has to be visible to
    the ANSWERER, or the narrative makes claims that cannot then be checked against
    anything. `channel_siblings` was the case that proved it: the payload carried it, so
    the bullets cited Combined-Queue and per-channel figures, and the bundle omitted it --
    so every question about those figures came back "cannot be answered from the available
    data". The data was there the whole time; it simply was not handed over.

    Before adding a block to `_payload`, add it here too.
    """
    pack = (features or {}).get("evidence_pack") or {}
    sib = (features or {}).get("channel_siblings") or {}
    return {
        "forecast_summary": result.get("forecast_summary"),
        # Combined Queue and per-channel actuals/forecasts for this week and the prior one.
        # The bullets are built from this, so questions about it are answerable.
        "channel_and_combined_queue": {k: sib.get(k) for k in (
            "available", "grouped_by", "combined_queue_names", "is_cqn_proxy",
            "prior_week", "this_week", "per_channel",
            # The Combined-Queue totals and the percentage change the bullets quote.
            "group_total_prior_week", "group_total_this_week", "group_total_change",
            "cqn_total_change_pct", "gross_channel_movement", "offset_share",
            "migration_detected", "gaining_channels", "losing_channels", "reason",
        )} if sib else None,
        "period": {"holiday_count": ((features.get("base_features") or {})
                                     .get("holiday") or {}).get("count")},
        "key_facts": pack.get("key_facts"),
        "weekly_series": pack.get("weekly_series"),
        "period_aggregates": pack.get("period_aggregates"),
        "plan_vintage_changes": pack.get("plan_vintage_changes"),
        "investigation_ladder": (features.get("investigation_ladder") or {}).get("levels"),
        "statistics": features.get("temporal"),
        "drivers": features.get("correlations"),
        "data_quality": features.get("data_quality"),
        "confidence": {"level": result.get("confidence_level"),
                       "pct": result.get("confidence_pct")},
    }


def run(result, features, llm_cfg, model_choice, endpoints, defaults, slot_for_choice):
    """Ask and answer. Returns a block for the report; never raises, never mutates input."""
    out = {"available": False, "questions": [], "answers": [], "not_asked": [],
           "rejected_questions": [], "problems": []}

    pack = (features or {}).get("evidence_pack") or {}
    weeks = pack.get("weeks_of_history") or 0
    # A queue with no history has nothing to interrogate. Running anyway produces sharp
    # questions whose only possible answer is "cannot be determined", which reads as the
    # engine failing when the truth is simply that the queue is new.
    if weeks < MIN_WEEKS_TO_INTERROGATE:
        out["reason"] = (f"only {weeks} week(s) of history for this queue, so there is no "
                         f"pattern to interrogate.")
        return out

    findings = _bullets_from(result)
    if not findings.get("root_cause"):
        out["reason"] = "no root cause was produced, so there is nothing to question."
        return out

    # --- Prompt 2: ask -------------------------------------------------------
    parsed, err = _call(why_prompt.build_messages(findings), llm_cfg, model_choice,
                        endpoints, defaults, slot_for_choice)
    if not parsed:
        out["reason"] = f"question generation unavailable: {err}"
        return out
    questions, rejected = why_prompt.validate(parsed)

    # Weaker models return usable questions while omitting a required field, and the
    # validator then drops the lot -- which made this look like a one-model feature.
    # Measured: nemotron-3-ultra-550b scored zero questions, then four after one repair.
    if not questions and (parsed.get("questions") or []):
        repair = why_prompt.build_messages(findings) + [
            {"role": "assistant", "content": json.dumps(parsed, default=str)},
            {"role": "user", "content":
                "Your reply omitted the required `arises_from` field. Return the SAME "
                "questions, unchanged in wording, with `arises_from` set on each to the "
                "exact statement in the findings that prompted it. Same JSON schema."}]
        reparsed, _ = _call(repair, llm_cfg, model_choice, endpoints, defaults, slot_for_choice)
        if reparsed:
            requestions, rerejected = why_prompt.validate(reparsed)
            if requestions:
                questions, rejected, parsed = requestions, rerejected, reparsed
                out["schema_repaired"] = True

    out["rejected_questions"] = rejected
    out["not_asked"] = [n for n in (parsed.get("not_asked") or []) if isinstance(n, dict)]
    if not questions:
        out["reason"] = ("no question survived the absent-data and traceability checks"
                         + (f" ({'; '.join(r['reason'] for r in rejected[:2])})"
                            if rejected else ""))
        return out

    # --- Prompt 1: answer, one call per question -----------------------------
    bundle = _evidence_bundle(result, features)
    answers, problems = [], []
    for q in questions:
        parsed2, err2 = _call(why_prompt.build_answer_messages(q, bundle), llm_cfg,
                              model_choice, endpoints, defaults, slot_for_choice)
        if not parsed2:
            problems.append(f"no answer for '{str(q.get('question'))[:40]}...': {err2}")
            continue
        got, probs = why_prompt.validate_answers(parsed2, bundle)
        problems.extend(probs)
        if got:
            # Pin the question we asked; the model may echo it back reworded and the UI
            # pairs question to answer by exact text.
            answers.append({**got[0], "question": q.get("question")})

    # A duplicate across separate calls still means one question went unanswered.
    seen, deduped = {}, []
    for a in answers:
        if not a.get("answerable"):
            deduped.append(a)
            continue
        k = why_prompt._dedup_key(str(a.get("answer") or ""))
        if k and k in seen:
            problems.append(f"'{str(a.get('question'))[:35]}...' repeated an earlier answer")
            deduped.append({**a, "answerable": False, "answer": "", "evidence_used": [],
                            "what_would_be_needed": ("This question was not answered on its "
                                                     "own terms — the reply repeated "
                                                     "another answer.")})
            continue
        seen[k] = str(a.get("question") or "")
        deduped.append(a)

    out.update({"available": True, "questions": questions, "answers": deduped,
                "problems": problems,
                "answered": len([a for a in deduped if a.get("answerable")]),
                "unanswerable": len([a for a in deduped if not a.get("answerable")])})
    return out
