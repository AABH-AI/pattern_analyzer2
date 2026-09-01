# Multi-Agent RCA — IMP_DOCS entry

**Branch:** `test3_langraph` · **Port:** 9400 · **Status:** scaffold, nothing wired, nothing run
**Full baseline:** `ARCHITECTURE_BASELINE.md` in the repo root — read that first

---

## What this branch is for

A fresh approach to the RCA narrative: three language-model agents in fixed roles plus a judge,
replacing the single 86,424-token narrative call.

```
Analyst      states the mechanism the evidence supports
Challenger   tries to falsify it, from the SAME evidence
Editor       reconciles both into one report, inside a budget
Judge        scores against a rubric; one revision, then publish
```

It does **not** replace the deterministic engine. All 33 modules still compute every figure
before any agent runs. Agents affect wording, ordering, selection and length — never a number.

---

## Where the Groq API key goes

**File:** `backend/config.json` — gitignored, never committed, never in a container image.

The Groq slot already exists. Two things to change:

```json
"llm": {
  "primary": {
    "provider": "groq",
    "api_key":  "<PASTE YOUR GROQ KEY HERE>",
    "model":    "openai/gpt-oss-120b"
  },
  "secondary": {
    "provider": "groq",
    "api_key":  "<the same key>",
    "model":    "openai/gpt-oss-20b"
  }
}
```

**The model must change.** The file currently says `llama-3.3-70b-versatile`, which Groq **shut
down on 2026-08-16**. It is dead. `backend/agents/models.py` detects this:

```
PROBLEM: secondary slot uses RETIRED model 'llama-3.3-70b-versatile'
         (shutdown 2026-08-16) -- replace with 'openai/gpt-oss-120b'
```

Alternatively, set it by environment variable and leave the file alone:

```powershell
$env:GROQ_API_KEY = "gsk_..."
$env:GROQ_MODEL   = "openai/gpt-oss-120b"
```

`load_config()` prefers environment variables over the file, and matches them to whichever slot
names that provider — so re-ordering the slots does not silently undo the override.

### Check it worked

```powershell
cd backend
python -c "import sys; sys.path.insert(0,'.'); import json,io; from agents import models as M; print(M.audit_config(json.load(io.open('config.json',encoding='utf-8'))) or 'config OK')"
```

And, from a network where Groq is reachable — **not the AA network, which returns HTTP 403**:

```powershell
python -c "import sys; sys.path.insert(0,'.'); import json,io; from agents import models as M; cfg=json.load(io.open('config.json',encoding='utf-8')); print(M.verify_live(cfg['llm']['primary']['api_key'])[1])"
```

---

## Models — and why they are in code, not just config

| Role | Model | Tier |
|---|---|---|
| Analyst | `openai/gpt-oss-120b` | production |
| Challenger | `openai/gpt-oss-120b` | production |
| Editor | `openai/gpt-oss-20b` | production |
| Judge | `openai/gpt-oss-120b` | production |

Read from https://console.groq.com/docs/models and cross-checked against
https://console.groq.com/docs/deprecations on **2026-09-02**. Where the two disagreed, the
deprecation table won — it is dated. The models page listed both Llama chat models as
"production" while the deprecation table gave them a shutdown date already in the past.

**No live Llama chat model remains on Groq.** The only Llama left is
`meta-llama/llama-prompt-guard-2-22m`, an injection-detection guard, not a chat model. The
client-side Llama 3 70B endpoint is declared in `FUTURE_PROVIDERS` for when it exists.

**Retired, recorded so nobody re-adds them from memory:**

| Model | Shutdown | Replacement |
|---|---|---|
| `llama-3.3-70b-versatile` | 2026-08-16 | `openai/gpt-oss-120b` |
| `llama-3.1-8b-instant` | 2026-08-16 | `openai/gpt-oss-20b` |
| `qwen/qwen3-32b` | 2026-07-17 | `openai/gpt-oss-120b` |
| `moonshotai/kimi-k2-instruct-0905` | 2026-04-15 | `openai/gpt-oss-120b` |
| `meta-llama/llama-guard-4-12b` | 2026-03-05 | `openai/gpt-oss-safeguard-20b` |

**Do not add a model here from memory. Read the docs and record the date you read them.**

### Known weakness, stated not hidden

Analyst and Challenger share the gpt-oss family. Two instances of one model over identical
evidence agree more than two families would, so **the Challenger's dissent rate must be
measured, not assumed**. If it rarely dissents the fix is a different family —
`qwen/qwen3.6-27b`, or the client-side Llama endpoint — not a stronger prompt.

---

## Files on this branch

| Path | What |
|---|---|
| `ARCHITECTURE_BASELINE.md` | definition, workflow, judge rubric, cost, failure modes |
| `backend/agents/models.py` | registry, role assignment, `audit_config()`, `verify_live()` |
| `backend/agents/prompts/` | empty — awaiting approval of the baseline |
| `IMP_DOCS/multi-agent-architecture.md` | this file |

Nothing is wired into the engine. `POST /api/rca-investigate` behaves exactly as on `test3`.

---

## Prerequisites before the agents are worth building

| # | Prerequisite | Why |
|---|---|---|
| 1 | Fix the provider chain | `_FAST_FIRST` routes every interrogation call to a 403-blocked provider first, then to a reasoning model that timed out and lost a question |
| 2 | Replace the dead Groq model | detected by `audit_config()` |
| 3 | Say-once registry | 18,451 words — 69.5% of current output — is reprinted deterministic strings |
| 4 | Scope extractor | what makes ~11,500 tokens possible instead of the measured 180,360 |

---

## Related branches

| Branch | Port | For |
|---|---|---|
| `test3` | 9000 | the approved build — untouched |
| `test3_spec` | 9200 | spec-driven skills proposal; the scope extractor and say-once design live here |
| `test3_sql` | 9300 | all-SQL data path, holiday calendar from SQL |
| `test3_azure` | — | container deployment, Azure SQL migration |
| `test3_langraph` | 9400 | this — multi-agent + judge |
