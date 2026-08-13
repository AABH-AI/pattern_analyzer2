"""LLM transport for the WFM engine, with a CONFIGURABLE timeout.

Why this exists
---------------
`rca_investigate._call_openai_compatible` hard-codes `timeout=100`. NVIDIA reasoning models
routinely need longer than that on this network for a full WFM payload, so every NVIDIA
investigation landed in the deterministic fallback — and when Groq's daily quota is spent there
is no working provider left at all.

Rather than edit `rca_investigate.py` (which is deliberately kept byte-identical to
`shivam-updates` so the original engine cannot regress), the WFM engine gets its own transport
with the timeout read from config:

    "llm": { "timeout_seconds": 300, ... }

Defaults to 100 so behaviour is unchanged when the key is absent.

Everything else mirrors the original transport exactly, including the two behaviours that were
learned the hard way and must not be lost:
  * a browser-like User-Agent -- Groq's Cloudflare returns 403 "error code: 1010" to the
    default Python-urllib UA before the request reaches the API;
  * a retry without `response_format` -- some NVIDIA models reject it with 400/503.
"""
import json
import urllib.error
import urllib.request

from rca_investigate import _extract_json      # loose/fenced JSON parsing, reused as-is

DEFAULT_TIMEOUT_SECONDS = 100

# --- Invocation parameters -- FC_RCA_AI_Agent_Architecture.md 15A, all mandatory ---
#
# TEMPERATURE 0, not 0.35. The Testing strategy requires "AI reasoning shall be
# deterministic when identical inputs are supplied". At 0.35 the same queue re-run
# produced a different narrative every time, which makes an RCA impossible to review and
# impossible to reproduce from its audit record. Sampling randomness bought nothing here:
# the model is writing prose from findings that are already fixed, not exploring ideas.
TEMPERATURE = 0.0
TOP_P = 1.0               # no nucleus truncation
SEED = 20260730           # fixed and recorded, for reproducibility where the provider honours it

_UA = "Mozilla/5.0 (compatible; rca-investigation-engine/1.0)"


def timeout_from_config(llm_cfg):
    """Read llm.timeout_seconds, falling back to the original 100s."""
    try:
        value = float((llm_cfg or {}).get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)
        return value if value > 0 else DEFAULT_TIMEOUT_SECONDS
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SECONDS


# Endpoints whose OpenAI-compatibility layer rejects `seed` outright. Google's answers
#   HTTP 400  Invalid JSON payload received. Unknown name "seed": Cannot find field.
# and it is a hard reject, not a warning -- so every Gemini call failed, and because
# spec_engine's `_narrate` only records a reason when it reaches the request, the report
# surfaced "the language model call did not succeed: unknown" with nothing to act on.
# `seed` is omitted for these providers rather than dropped globally: NVIDIA and Groq honour
# it, and it is what makes an identical re-run reproducible. Determinism for Gemini therefore
# rests on temperature 0 alone, which the audit record should be read as meaning.
_NO_SEED_HOSTS = ("generativelanguage.googleapis.com",)


def _supports_seed(endpoint):
    return not any(h in (endpoint or "") for h in _NO_SEED_HOSTS)


def _post(endpoint, api_key, model, messages, timeout, use_response_format):
    payload = {"model": model, "messages": messages,
               "temperature": TEMPERATURE, "top_p": TOP_P}
    if _supports_seed(endpoint):
        payload["seed"] = SEED
    if use_response_format:
        payload["response_format"] = {"type": "json_object"}
    req = urllib.request.Request(
        endpoint, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {api_key}",
                 "Accept": "application/json",
                 "User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return body["choices"][0]["message"]["content"]


def chat_json(endpoint, api_key, model, messages, timeout=None):
    """Call the model and parse JSON. Retries once without response_format for models
    that reject it."""
    timeout = timeout or DEFAULT_TIMEOUT_SECONDS
    try:
        raw = _post(endpoint, api_key, model, messages, timeout, True)
    except urllib.error.HTTPError as e:
        if e.code in (400, 415, 422, 500, 503):
            raw = _post(endpoint, api_key, model, messages, timeout, False)
        else:
            raise
    return _extract_json(raw)
