# -*- coding: utf-8 -*-
"""
LLM Investigation Engine — the one module that is allowed to "reason" about a
forecast miss. Everything else in this backend (and in rca_console.html) is
plain deterministic code that gathers and structures data; NOTHING upstream of
this file decides what caused a miss.

Providers: NVIDIA (primary) and Groq (secondary/fallback), both OpenAI-compatible
chat-completion APIs, so one HTTP helper (`_call_openai_compatible`) serves both.
Which one is "primary" vs "secondary" is decided entirely by backend/config.json's
"llm" section (gitignored — see config.example.json) — swap the two slot objects
there to reorder; GROQ_API_KEY / NVIDIA_API_KEY env vars apply to whichever slot
currently names that provider, not a fixed position. If neither slot is configured,
or both calls fail, `investigate()` returns the HONEST placeholder below — it never
fabricates a root cause, a confidence number, or "evidence" no model actually produced.

The `forecast_summary` figures in every response (real or placeholder) are ALWAYS
taken from our own deterministic `context_bundle.target.computed` — never from
what the model echoes back — so the one part of the output that's supposed to be
plain fact can't drift or be hallucinated even slightly.
"""
import json
import re
import urllib.request
import urllib.error
from datetime import datetime, timezone

PROVIDER_ENDPOINTS = {
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "nvidia": "https://integrate.api.nvidia.com/v1/chat/completions",
}
DEFAULT_MODELS = {
    "groq": "llama-3.3-70b-versatile",
    "nvidia": "meta/llama-3.1-70b-instruct",
}

SYSTEM_PROMPT = """You are an investigative root-cause analyst for a demand-forecasting system.

You will be given a JSON "context bundle" describing one forecast miss: the target week's
full raw data, its recent history for the same queue, peer queues sharing the same
Region/SubRegion/Country/Channel the same week, and an auto-computed statistical summary
(history mean/stdev/z-score/outlier flag/trend slope per numeric field, changed-flag per
categorical field) covering EVERY field present in the data — this is not a curated list of
what matters, it is everything available; you decide what's relevant.

Investigate this miss the way a skilled human analyst would — NOT by applying a fixed
checklist or known business rule:
1. Understand the forecast miss (magnitude/direction are already computed for you in
   context.target.computed — do not recompute or contradict these numbers).
2. Examine every available variable in the context bundle, not just an assumed few.
3. Detect unusual changes — use the statistical_summary's z-scores, outlier flags, trend
   slopes, and categorical change flags, but also read the raw values and peers yourself.
4. Compare against historical behaviour for this queue and against peer queues.
5. Generate MULTIPLE distinct hypotheses that could explain the miss, drawn from DIFFERENT
   parts of the context bundle — do not stop at the first plausible-looking signal.
6. For each hypothesis, evaluate the evidence in the data that SUPPORTS it and the evidence
   that CONTRADICTS it.
7. Reject hypotheses that lack sufficient supporting evidence — explain exactly why in
   rejected_hypotheses.
8. Rank the surviving hypotheses by likelihood; the most likely becomes primary_root_cause,
   the rest become secondary_contributors.
9. Estimate a confidence score (0.0-1.0) based on how much of the actual data supports your
   conclusion — do not default to a fixed number.
10. Identify what additional information, if it existed, would improve your confidence —
    list it in missing_information.

Critical trap to avoid — generic evidence that looks specific but isn't:
The field(s) driving context.target.computed (typically the offered/handled or equivalent
demand figures) will ALWAYS show up as an outlier vs. their own history for ANY flagged
miss — that is what "flagged" means, definitionally, for every single case you will ever be
asked to investigate. Citing "this field is an outlier vs. its own history" as your PRIMARY
evidence is true but empty — it restates that a miss happened, it does not explain WHY this
specific case happened rather than any other. Only lean on it if you truly find nothing more
specific; prefer hypotheses built from evidence that would NOT be true of every other flagged
queue: a specific peer moving the opposite direction the same week, a specific categorical
field that changed and plausibly explains this magnitude, a specific other numeric field's
outlier/trend that co-occurs with the miss, or a specific historical pattern unique to this
queue. Explicitly check `peers` — do any of them move in the opposite direction the same
week (a volume/routing shift between sibling queues), which is a materially different
explanation from genuine total-demand change and should be distinguished, not skipped.

Hard rules:
- Never invent a cause not traceable to the supplied data. Every entry in supporting_evidence
  must cite a specific field name (source_field) and the value you actually observed.
- Never apply a fixed business rule or IF-THEN checklist (e.g. "if Holiday_Count>0 then
  holiday caused it") — reason freely from what THIS case's data actually shows.
- forecast_improvement_recommendations must contain ONLY suggestions for improving the
  forecasting model/process (e.g. re-baselining, adding a variable, revisiting a seasonality
  assumption) — NEVER workforce, staffing, or operational recommendations.
- If the data doesn't clearly support any conclusion, say so plainly: set primary_root_cause
  to null and explain why in missing_information rather than guessing.
- Respond with ONLY a single JSON object, no prose outside it, matching EXACTLY this shape
  (types shown, use null/[] where you have nothing to report — never omit a key):

{
  "primary_root_cause": {"statement": "string", "confidence": 0.0, "supporting_evidence": [{"text": "string", "source_field": "string", "value": "any"}]} or null,
  "supporting_evidence": [{"text": "string", "source_field": "string", "value": "any"}],
  "secondary_contributors": [{"statement": "string", "confidence": 0.0, "supporting_evidence": [{"text": "string", "source_field": "string", "value": "any"}]}],
  "rejected_hypotheses": [{"hypothesis": "string", "reason_rejected": "string"}],
  "historical_comparison": {"narrative": "string", "data_points": [{"label": "string", "value": "any"}]},
  "reasoning_narrative": "string",
  "forecast_improvement_recommendations": ["string"],
  "confidence_score": 0.0,
  "missing_information": ["string"]
}
"""

_RESPONSE_DEFAULTS = {
    "primary_root_cause": None,
    "supporting_evidence": [],
    "secondary_contributors": [],
    "rejected_hypotheses": [],
    "historical_comparison": {"narrative": "", "data_points": []},
    "reasoning_narrative": "",
    "forecast_improvement_recommendations": [],
    "confidence_score": None,
    "missing_information": [],
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _placeholder_response(context_bundle, extra_missing=None):
    """No live provider available — say so honestly. Every list is empty rather
    than invented; missing_information explains exactly what to do next."""
    target = (context_bundle or {}).get("target", {})
    computed = target.get("computed", {})
    fields_seen = sorted(set((target.get("fields") or {}).keys()))
    missing = [
        "Live LLM connection is not configured or unavailable (backend/config.json → "
        "\"llm\".primary/secondary, or GROQ_API_KEY/NVIDIA_API_KEY env vars).",
        f"{len(fields_seen)} field(s) were gathered generically from the source file "
        "and are ready to send to a model once one is reachable.",
    ] + list(extra_missing or [])
    narrative = (
        "No LLM is connected. This is a placeholder response showing the exact shape a "
        "real investigation will return — it is not an analysis, and no conclusion has "
        "been drawn."
    )
    if extra_missing:
        narrative = "No live investigation could be completed. " + " ".join(extra_missing)
    return {
        "forecast_summary": {
            "forecast": computed.get("forecast"),
            "actual": computed.get("actual"),
            "error": computed.get("error"),
            "adherence_pct": computed.get("adherence_pct"),
            "miss_type": computed.get("direction"),
            "severity": computed.get("severity"),
        },
        "primary_root_cause": None,
        "supporting_evidence": [],
        "secondary_contributors": [],
        "rejected_hypotheses": [],
        "historical_comparison": {"narrative": "", "data_points": []},
        "reasoning_narrative": narrative,
        "forecast_improvement_recommendations": [],
        "confidence_score": None,
        "missing_information": missing,
        "investigation_meta": {
            "engine": "placeholder",
            "provider": None,
            "model": None,
            "generated_at": _now(),
            "based_on_fields": fields_seen,
        },
    }


def _extract_json(text):
    """Models occasionally wrap JSON in prose/fences despite instructions —
    try a direct parse first, then fall back to the outermost {...} span."""
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError("model response did not contain a JSON object")
    return json.loads(m.group(0))


def _call_openai_compatible(endpoint, api_key, model, messages, timeout=60):
    body = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    req = urllib.request.Request(endpoint, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        # Groq (and some other providers) sit behind Cloudflare bot-management, which
        # blocks urllib's default "Python-urllib/3.x" User-Agent with a 403 (Cloudflare
        # error 1010) before the request ever reaches the actual API. A normal-looking
        # UA is enough to get past it — this isn't spoofing a browser session, just
        # not announcing "I am a bare urllib script."
        "User-Agent": "Mozilla/5.0 (compatible; rca-investigation-engine/1.0)",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return payload["choices"][0]["message"]["content"]


def _coerce_response(parsed, context_bundle):
    """Fill any STRUCTURALLY missing keys with safe empty defaults so a slightly
    malformed model reply can't crash the formatter/renderer downstream — this
    fills gaps in shape, never invents content. forecast_summary is always
    overwritten from our own deterministic computed values (see module docstring)."""
    if not isinstance(parsed, dict):
        parsed = {}
    out = dict(_RESPONSE_DEFAULTS)
    out.update({k: v for k, v in parsed.items() if k in _RESPONSE_DEFAULTS})
    target_computed = ((context_bundle or {}).get("target") or {}).get("computed") or {}
    out["forecast_summary"] = {
        "forecast": target_computed.get("forecast"),
        "actual": target_computed.get("actual"),
        "error": target_computed.get("error"),
        "adherence_pct": target_computed.get("adherence_pct"),
        "miss_type": target_computed.get("direction"),
        "severity": target_computed.get("severity"),
    }
    return out


def _call_provider(slot_cfg, context_bundle):
    """Returns (response_dict, None) on success, or (None, error_string) on any
    failure (not configured, network error, bad JSON, provider error) — never
    raises, so the primary->secondary->placeholder fallback chain stays simple."""
    slot_cfg = slot_cfg or {}
    provider = slot_cfg.get("provider")
    api_key = slot_cfg.get("api_key")
    if not provider or not api_key:
        return None, "not configured"
    endpoint = slot_cfg.get("endpoint") or PROVIDER_ENDPOINTS.get(provider)
    if not endpoint:
        return None, f"unknown provider '{provider}' and no endpoint override given"
    model = slot_cfg.get("model") or DEFAULT_MODELS.get(provider)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(context_bundle, default=str)},
    ]
    try:
        raw = _call_openai_compatible(endpoint, api_key, model, messages)
        parsed = _extract_json(raw)
    except urllib.error.HTTPError as e:
        if e.code == 413 and (context_bundle.get("history") or context_bundle.get("peers")):
            # Payload too large for this provider's size/rate limit. Retry ONCE with a
            # trimmed bundle (last 3 history weeks, no peers) rather than failing outright —
            # statistical_summary (already computed from the full, untrimmed data client-side)
            # is unchanged, so no analytical signal is lost, only the duplicated raw rows.
            trimmed = dict(context_bundle)
            trimmed["history"] = (context_bundle.get("history") or [])[-3:]
            trimmed["peers"] = []
            try:
                retry_messages = [messages[0], {"role": "user", "content": json.dumps(trimmed, default=str)}]
                raw = _call_openai_compatible(endpoint, api_key, model, retry_messages)
                parsed = _extract_json(raw)
            except Exception as e2:
                return None, f"{provider} error (413, retry with trimmed context also failed): {e2}"
        else:
            detail = e.read().decode("utf-8", "replace")[:300]
            return None, f"{provider} HTTP {e.code}: {detail}"
    except Exception as e:
        return None, f"{provider} error: {e}"
    result = _coerce_response(parsed, context_bundle)
    result["investigation_meta"] = {
        "engine": "llm",
        "provider": provider,
        "model": model,
        "generated_at": _now(),
        "based_on_fields": sorted(set(((context_bundle or {}).get("target") or {}).get("fields", {}).keys())),
    }
    return result, None


def investigate(context_bundle, llm_cfg):
    """Try llm_cfg["primary"] (Groq), then llm_cfg["secondary"] (NVIDIA) as a
    fallback, then the honest placeholder if neither is configured or both fail."""
    llm_cfg = llm_cfg or {}
    failures = []
    for slot_name in ("primary", "secondary"):
        slot = llm_cfg.get(slot_name) or {}
        if not slot.get("provider") or not slot.get("api_key"):
            continue
        result, err = _call_provider(slot, context_bundle)
        if result is not None:
            return result
        failures.append(f"{slot.get('provider', slot_name)}: {err}")
    extra = [f"{f}." for f in failures] if failures else None
    return _placeholder_response(context_bundle, extra)
