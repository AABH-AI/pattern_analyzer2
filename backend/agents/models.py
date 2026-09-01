# -*- coding: utf-8 -*-
"""The model registry: which model each agent role uses, and whether it is still alive.

WHY THIS FILE EXISTS RATHER THAN A MODEL NAME IN A PROMPT FILE
--------------------------------------------------------------
On 2026-09-02 this project's configured Groq model was `llama-3.3-70b-versatile`, whose
shutdown date was 2026-08-16 -- seventeen days earlier. Groq's own models page still listed it
under "production". Nothing in the code noticed, and nothing could have: the model name was a
string in config.json and no code ever checked it against the provider.

Provider catalogues churn. Groq's deprecation table lists 36 retired models. So this registry
does two things a config string cannot:

  1. Declares models by ROLE, not by name, so swapping a model is one line and the agents do
     not care.
  2. `verify_live()` asks the provider what actually exists and reports which configured models
     are missing. Run it at startup and on deploy. A dead model then fails loudly at boot
     instead of silently at 3am.

MODEL FACTS ARE NOT HARDCODED FROM MEMORY
-----------------------------------------
Every ID below was read from https://console.groq.com/docs/models and cross-checked against
https://console.groq.com/docs/deprecations on 2026-09-02. Where the two pages disagreed, the
deprecation table won -- it is dated and specific. The models page listed both Llama chat
models as "production" while the deprecation table gave them a shutdown date that had already
passed.

**Do not add a model here from memory. Read the docs, record the date you read them.**
"""

CATALOGUE_READ_ON = "2026-09-02"
CATALOGUE_SOURCE = ("https://console.groq.com/docs/models + "
                    "https://console.groq.com/docs/deprecations")

# ---------------------------------------------------------------------------------------------
# Groq, as of CATALOGUE_READ_ON. `alive` is our reading of the deprecation table, not a guess.
# ---------------------------------------------------------------------------------------------
GROQ_MODELS = {
    # --- production text ---------------------------------------------------------------------
    "openai/gpt-oss-120b": {
        "alive": True, "tier": "production", "context": 131072,
        "good_at": "advanced reasoning; built-in web search and code execution",
        "notes": "Groq's recommended general/reasoning model. The replacement Groq names for "
                 "both retired Llama chat models.",
    },
    "openai/gpt-oss-20b": {
        "alive": True, "tier": "production", "context": 131072,
        "good_at": "balanced cost and quality",
        "notes": "Cheaper sibling. Suits compression and editing, where the reasoning is light "
                 "and the constraint is length.",
    },
    # --- production agentic systems -----------------------------------------------------------
    "groq/compound": {
        "alive": True, "tier": "production", "context": 131072,
        "good_at": "agentic use with web search and code execution built in",
        "notes": "Provider-side tool use. Deliberately unused for now: it makes a call's "
                 "behaviour depend on tools we do not control, which is the opposite of the "
                 "reproducibility this design is trying to buy.",
    },
    "groq/compound-mini": {
        "alive": True, "tier": "production", "context": 131072,
        "good_at": "lighter agentic tasks", "notes": "As above.",
    },
    # --- preview ------------------------------------------------------------------------------
    "qwen/qwen3.6-27b": {
        "alive": True, "tier": "preview", "context": None,
        "good_at": "multilingual; a different model family from gpt-oss",
        "notes": "Groq names this as an alternative replacement for llama-3.3-70b-versatile. "
                 "A different family is what makes a Challenger genuinely disagree rather than "
                 "echo the Analyst -- but Groq marks preview as evaluation-only.",
    },
    "qwen/qwen3.8-27b": {
        "alive": True, "tier": "preview", "context": None,
        "good_at": "advanced multilingual reasoning", "notes": "As above.",
    },
    "openai/gpt-oss-safeguard-20b": {
        "alive": True, "tier": "preview", "context": None,
        "good_at": "safety and policy classification",
        "notes": "Candidate for a guard pass. Named as the replacement for the retired "
                 "llama-guard-4-12b.",
    },
    "meta-llama/llama-prompt-guard-2-22m": {
        "alive": True, "tier": "preview", "context": None,
        "good_at": "prompt-injection detection",
        "notes": "The only Llama model left on Groq, and it is a guard, NOT a chat model. It "
                 "cannot serve an agent role.",
    },
    # --- audio, listed for completeness; unused by this engine --------------------------------
    "whisper-large-v3": {"alive": True, "tier": "production", "context": None,
                         "good_at": "speech to text", "notes": "unused here"},
    "whisper-large-v3-turbo": {"alive": True, "tier": "production", "context": None,
                               "good_at": "faster speech to text", "notes": "unused here"},
    "canopylabs/orpheus-v1-english": {"alive": True, "tier": "preview", "context": None,
                                      "good_at": "text to speech", "notes": "unused here"},

    # --- RETIRED. Kept deliberately, with dates, so nobody re-adds them from memory. ----------
    "llama-3.3-70b-versatile": {
        "alive": False, "tier": "retired", "shutdown": "2026-08-16",
        "replacement": "openai/gpt-oss-120b",
        "notes": "WAS this project's configured Groq model. Dead before we noticed.",
    },
    "llama-3.1-8b-instant": {
        "alive": False, "tier": "retired", "shutdown": "2026-08-16",
        "replacement": "openai/gpt-oss-20b", "notes": "",
    },
    "qwen/qwen3-32b": {
        "alive": False, "tier": "retired", "shutdown": "2026-07-17",
        "replacement": "openai/gpt-oss-120b", "notes": "",
    },
    "moonshotai/kimi-k2-instruct-0905": {
        "alive": False, "tier": "retired", "shutdown": "2026-04-15",
        "replacement": "openai/gpt-oss-120b", "notes": "",
    },
    "meta-llama/llama-guard-4-12b": {
        "alive": False, "tier": "retired", "shutdown": "2026-03-05",
        "replacement": "openai/gpt-oss-safeguard-20b", "notes": "",
    },
}

GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"

# Groq is behind Cloudflare, which returns 403 "error code: 1010" to the default
# Python-urllib User-Agent BEFORE the request reaches the API. It is not a network block and not
# a bad key. wfm/llm_client.py has carried this workaround since the beginning; verify_live was
# written without it, so it 403'd every time and handed the UI an empty model list.
_UA = "Mozilla/5.0 (compatible; rca-multiagent/1.0)"

# ---------------------------------------------------------------------------------------------
# ROLE ASSIGNMENT
#
# Roles, not model names, are what the rest of the code refers to. Change a model here and the
# agents are unaffected.
#
# On the choice of a single family: there is no live Llama chat model on Groq, so the Analyst
# and Challenger share the gpt-oss family and will agree more often than two families would.
# That is a real weakness of this configuration, not something to paper over -- see
# `SAME_FAMILY_CAVEAT`. `qwen/qwen3.6-27b` is the ready alternative if preview is acceptable,
# and a client-side Llama 3 70B endpoint is the other, once one exists.
# ---------------------------------------------------------------------------------------------
ROLES = {
    "analyst": {
        "model": "openai/gpt-oss-120b",
        "why": "states the mechanism the evidence supports; the hardest reasoning in the chain",
        "max_tokens": 1200, "temperature": 0.0,
    },
    "challenger": {
        "model": "openai/gpt-oss-120b",
        "why": "tries to falsify the Analyst from the SAME evidence. Wants the strongest "
               "available reasoning, because a weak challenger simply agrees.",
        "max_tokens": 2000, "temperature": 0.3,
    },
    "editor": {
        "model": "openai/gpt-oss-20b",
        "why": "reconciles two findings into one report inside a word budget. Ordering and "
               "compression, not analysis -- the cheaper model is the right tool.",
        "max_tokens": 2000, "temperature": 0.0,
    },
    "judge": {
        "model": "openai/gpt-oss-120b",
        "why": "scores the report against a rubric and must cite evidence per factor. Needs "
               "the strongest model: a lenient judge is worse than no judge.",
        # 1200 was not enough: it is a reasoning model, and it returned two of five factors and
        # an empty overall because it ran out of room mid-rubric.
        "max_tokens": 3000, "temperature": 0.0,
    },
}

SAME_FAMILY_CAVEAT = (
    "Analyst and Challenger currently run the same model family (gpt-oss), because Groq retired "
    "every Llama chat model on 2026-08-16 and the only cross-family option, Qwen, is marked "
    "preview. Two instances of one model reasoning over identical evidence agree more than two "
    "families would, so the Challenger's disagreement rate should be MEASURED, not assumed. If "
    "it rarely dissents, the fix is a different family -- either qwen/qwen3.6-27b or a "
    "client-side Llama 3 70B endpoint -- not a stronger prompt."
)

# Future providers. Declared but unused: the client side has Llama 3 70B and Gemini is planned,
# and when either arrives it needs an endpoint here rather than a code change.
FUTURE_PROVIDERS = {
    "client_llama": {
        "endpoint": None,          # e.g. http://<host>:11434/v1/chat/completions for Ollama
        "models": ["llama3:70b"],
        "notes": "Client-side Llama 3 70B. Any OpenAI-compatible /chat/completions endpoint "
                 "works -- every call site resolves slot['endpoint'] before the built-in map. "
                 "This is the preferred fix for the same-family caveat above.",
    },
    "gemini": {
        "endpoint": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "models": [],              # read from Google's docs when needed; do not guess
        "notes": "Planned. Model IDs deliberately empty -- fill them from the live docs, not "
                 "from memory, for the same reason this file exists.",
    },
}


def role(name):
    """The config for one agent role. Raises rather than silently defaulting."""
    if name not in ROLES:
        raise KeyError("unknown agent role %r; known roles: %s"
                       % (name, ", ".join(sorted(ROLES))))
    return dict(ROLES[name])


def alive(model_id):
    """Is this model believed live, per the catalogue reading? Unknown models return None."""
    entry = GROQ_MODELS.get(model_id)
    return None if entry is None else bool(entry.get("alive"))


def retired():
    """{model_id: (shutdown_date, replacement)} for everything we know is gone."""
    return {m: (e.get("shutdown"), e.get("replacement"))
            for m, e in GROQ_MODELS.items() if not e.get("alive")}


def audit_config(cfg):
    """Check the models in config.json against the catalogue. Returns a list of problems.

    This is the check that was missing when llama-3.3-70b-versatile died unnoticed.
    """
    problems = []
    llm = (cfg or {}).get("llm") or {}
    for slot_name in ("primary", "secondary", "tertiary"):
        slot = llm.get(slot_name) or {}
        model, provider = slot.get("model"), slot.get("provider")
        if not model:
            continue
        if provider != "groq":
            continue                       # only Groq's catalogue is recorded here
        state = alive(model)
        if state is False:
            e = GROQ_MODELS[model]
            problems.append(
                "%s slot uses RETIRED model %r (shutdown %s) -- replace with %r"
                % (slot_name, model, e.get("shutdown"), e.get("replacement")))
        elif state is None:
            problems.append(
                "%s slot uses %r, which is not in the catalogue read on %s. Verify it against "
                "%s before relying on it." % (slot_name, model, CATALOGUE_READ_ON, GROQ_MODELS_URL))
    for role_name, spec in ROLES.items():
        if alive(spec["model"]) is not True:
            problems.append("agent role %r is assigned %r, which is not live"
                            % (role_name, spec["model"]))
    return problems


def verify_live(api_key, timeout=20):
    """Ask Groq what models actually exist right now. The authoritative check.

    Returns (available_ids, report). Never raises -- a network failure is reported, because a
    verification step that crashes the app is worse than one that says it could not check.
    """
    import json
    import urllib.error
    import urllib.request
    if not api_key:
        return set(), {"ok": False, "reason": "no api key supplied"}
    req = urllib.request.Request(GROQ_MODELS_URL, headers={
        "Authorization": "Bearer %s" % api_key,
        "Accept": "application/json",
        "User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
        return set(), {"ok": False, "reason": "HTTP %s: %s" % (exc.code, body),
                       "hint": ("403 with 'error code: 1010' is Cloudflare rejecting the "
                                "User-Agent, not a network block and not a bad key. This "
                                "function sends a browser UA, so a 403 here means the key "
                                "itself. 401 means the key is invalid.")}
    except Exception as exc:
        return set(), {"ok": False, "reason": "%s: %s" % (type(exc).__name__, exc)}

    available = {m.get("id") for m in (payload.get("data") or []) if m.get("id")}
    assigned = {spec["model"] for spec in ROLES.values()}
    missing = sorted(assigned - available)
    catalogued_alive = {m for m, e in GROQ_MODELS.items() if e.get("alive")}
    return available, {
        "ok": not missing,
        "provider_reports": len(available),
        "assigned_to_roles": sorted(assigned),
        "assigned_but_absent": missing,
        "catalogue_says_alive_but_absent": sorted(catalogued_alive - available),
        "present_but_not_in_catalogue": sorted(available - set(GROQ_MODELS)),
        "catalogue_read_on": CATALOGUE_READ_ON,
    }
