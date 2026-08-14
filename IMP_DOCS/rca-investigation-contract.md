# RCA Investigation Contract

The exact JSON shapes shared between the six Root-Cause Investigation modules
(`rca_console.html` client-side; `backend/rca_investigate.py` server-side).
Read this before touching the Data Aggregator, Context Builder, LLM
Investigation Engine, RCA Formatter, or UI Renderer — they all depend on this
shape staying stable. The shape itself is generic (no field is named as
required beyond `target`/`history`/`peers`/`statistical_summary`/`meta`) — the
*contents* of `fields`/`numeric`/`categorical` are whatever the source file
happens to have, discovered automatically.

## ContextBundle (client → `POST /api/rca-investigate`)

```jsonc
{
  "meta": {
    "band_threshold": 10,
    "generated_at": "2026-07-24T12:00:00.000Z",
    "schema_note": "Generic bundle — every column present in the source file is included automatically; nothing is hand-picked."
  },
  "target": {
    "key": { "Forecast_name": "NA Chat Premium", "Fiscal_Week": "202510" },
    "fields": { /* every raw column on this row, whatever they are */ },
    "computed": {
      "forecast": 1000, "actual": 1220, "error": 220,
      "adherence_pct": -22.0, "accuracy_pct": 122.0,
      "direction": "under",   // negative adherence_pct = actual ran ABOVE forecast
      "severity": 2.2         // |adherence_pct| ÷ band_threshold — a ratio of the two CONFIRMED numbers,
                               // deliberately not a second invented cutoff (e.g. a hand-picked "25% = critical")
    }
  },
  "history": [ /* { key, computed } only — NO fields — prior weeks for the same Forecast_name, chronological, capped at RCA_HISTORY_CAP (13) */ ],
  "peers":   [ /* { key, computed } only — NO fields — same Fiscal_Week, same Region/SubRegion/Country/channel, different Forecast_name, capped at RCA_PEERS_CAP (15), sorted by |error| so the most-diverged peers survive the cap */ ],
  // history/peers deliberately drop the raw `fields` object that `target` carries: sending
  // it per-row (up to 12+15 times) duplicated exactly what statistical_summary already
  // distills generically, and blew past provider token limits on real data (Groq: 413,
  // "tokens per minute limit exceeded", ~13,916 tokens vs. its 12,000 TPM cap). Both caps
  // and this slimming are token-budget engineering, not business rules about what evidence
  // counts — statistical_summary is still computed from the FULL, untrimmed history first,
  // so no generic signal is lost, only the duplicated raw rows.
  "statistical_summary": {
    "numeric":     { "<fieldName>": { "history_mean":, "history_stdev":, "target_value":, "z_score":, "is_outlier": /* |z|>2 */, "trend_slope":, "n": } },
    "categorical": { "<fieldName>": { "target_value":, "prior_value":, "changed":, "distinct_recent_values": [] } }
  }
}
```

`numeric` vs `categorical` is decided per field, automatically: a field is
numeric only if every observed value (history + target) parses as a number.
Every field key discovered in `target.fields ∪ history[].fields` gets an
entry in one or the other — nothing is pre-selected by name.

## InvestigationResponse (`POST /api/rca-investigate` response)

```jsonc
{
  "forecast_summary": { "forecast":, "actual":, "error":, "adherence_pct":, "miss_type": "over"|"under", "severity": },
  "primary_root_cause": { "statement":, "confidence": 0.0-1.0, "supporting_evidence": [{"text":,"source_field":,"value":}] } | null,
  "supporting_evidence": [ { "text":, "source_field":, "value": } ],
  "secondary_contributors": [ { "statement":, "confidence":, "supporting_evidence": [] } ],
  "rejected_hypotheses": [ { "hypothesis":, "reason_rejected": } ],
  "historical_comparison": { "narrative":, "data_points": [ {"label":,"value":} ] },
  "reasoning_narrative": "",
  "forecast_improvement_recommendations": [ "" ],   // forecasting improvements ONLY — never workforce/operational
  "confidence_score": 0.0-1.0 | null,
  "missing_information": [ "" ],
  "investigation_meta": { "engine": "placeholder"|"llm", "provider": null|"groq"|"nvidia", "model": null|"...", "generated_at":, "based_on_fields": [] }
}
```

**`null`/empty means "not determined," never "determined to be nothing."**
`primary_root_cause: null` + a `missing_information` entry explaining why is
the honest placeholder response — never a fabricated conclusion. The UI
Renderer shows an explicit empty-state for every section rather than hiding
it, so the gap is visible, not silently absent.

## WFM mode (`?mode=wfm`) — additive

`POST /api/rca-investigate?mode=wfm` selects the WFM business-prompt engine
(`backend/rca_wfm.py`). **Without the `mode` parameter this endpoint is unchanged**, so the
contract above still holds exactly for every existing caller.

The WFM engine accepts the **same ContextBundle** — it fetches the extra context it needs
(104-week history, channel siblings across all channels, higher-level rollups) server-side from
the target row's identifiers, so the console sends nothing new.

It returns **every key in the InvestigationResponse above**, populated by mapping its ranked
list: rank 1 → `primary_root_cause` / `cause_type` / `confidence_score`, ranks 2-5 →
`secondary_contributors`, rejected skeptic challenges → `rejected_hypotheses`, each cause's
action → `forecast_improvement_recommendations`. Plus these additional keys:

`executive_summary`, `kpi_status`, `business_impact`, `ranked_root_causes[]`,
`skeptic_review[]`, `investigation_trail`, `channel_migration`, `technical_metrics[]`.

`kpi_status` and `channel_migration.detected` are computed in Python and overwrite whatever the
model returned. `investigation_meta.engine` is one of `wfm-llm`,
`wfm-not-investigated` (inside ±band — the business rule forbids investigating), or
`wfm-deterministic-fallback`.

Full detail, including the CQN definition conflict and known gaps: `IMP_DOCS/wfm-rca-engine.md`.

## FC Decision Card mode (`?mode=spec`) — additive

`POST /api/rca-investigate?mode=spec` selects the canonical FC RCA methodology and the Executive
Decision Card (`backend/wfm/spec_engine.py`). Same ContextBundle; extra query parameters
`grain` (`weekly` | `monthly` | `quarterly`) and `interrogate` (`1` | `0`).

It returns its own response shape rather than the InvestigationResponse above — the console detects
it by the presence of `decision_card` and routes to `renderDecisionCard`, or to `renderSpecStatus`
when there is no card (which is a legitimate outcome: inside the ±5% generation threshold, or the
investigation stopped early with a reason).

**Every key below was present before the Decision Card upgrade and is unchanged:**

`queue`, `period`, `holiday`, `context_elements`, `grain`, `forecast_summary`, `root_cause`,
`confidence`, `supporting_evidence`, `contradictory_evidence`, `recommendations`, `limitations`,
`why_chain`, `hypotheses`, `cross_examination`, `driver_gate`, `statistical_evidence`,
`data_quality`, `major_deviation`, `material`, `audit`, `engine`, `decision_card`, `status`,
`narrative`, `narrative_error`, `incomplete_reason`, `interrogation`.

**Added by the upgrade, all additive:**

`forecast_response_diagnostic`, `forecastability`, `forecastability_gate`,
`lagged_driver_evidence`, `holiday_response`, `weekend_diagnostic`, `asu_decomposition`,
`plan_revision`, `plan_vintage_timeline`, `miss_mechanism`, `criticality`, `evidence_resolution`,
`unexplained_observations`, `fc_evidence_index`, `decision_card_why`.

On `root_cause`, alongside the existing `cause_type` / `hypothesis_id` / `hypothesis` / `category` /
`statement` / `cross_examination` / `caveats` / `selected_because`:
`miss_mechanism`, `miss_mechanism_meaning`, `miss_mechanisms_supported`, `compound`,
`evidence_resolution`, `evidence_ids`, `direction_coherent`.

**`root_cause.cause_type` is still the catalogue hypothesis ID.** The mechanism answers a different
question — *why did the forecast miss* — and never replaces it.

`decision_card.card_version` is `2.1.0`: the ten mandatory sections are unchanged and eight are
added, numbered `11_`…`18_` so a renderer that does not know them shows the original card.

Full detail, including what was deliberately preserved and the known limitations:
`IMP_DOCS/fc-decision-card-engine.md`.

> `?mode=spec` = canonical FC RCA methodology + Executive Decision Card
> `?mode=wfm` = WFM-specific forecast diagnostic engine
>
> The two are independent. They may be compared; neither is made to match the other.

## Where each piece lives

| Module | File | Function |
|---|---|---|
| RCA Trigger | `rca_console.html` | `triggerRCA(i)` |
| Data Aggregator | `rca_console.html` (calls out to `backend/sql_backend.py`) | `aggregateData(r)` — SQL mode (`window.SRC==='sql'`) calls `GET /api/queue-context` for a real scoped SQL query (just this queue's own row + history + CQN peers); file-upload mode (or if the query fails) falls back to filtering the in-browser rows |
| Context Builder | `rca_console.html` | `buildStatSummary`, `buildContext(r)` (now `async` — awaits the Data Aggregator) |
| LLM Investigation Engine (caller) | `rca_console.html` | `callInvestigationEngine(ctx)` — POSTs to the backend |
| LLM Investigation Engine (actual reasoning) | `backend/rca_investigate.py` | `investigate()` → `_call_provider()` → **Groq (primary), NVIDIA (secondary fallback)** |
| RCA Formatter | `rca_console.html` | `formatInvestigation(resp, ctx)` |
| UI Renderer | `rca_console.html` | `renderInvestigationReport(f, ctx)` |

**Live and wired** to Groq (primary) + NVIDIA (secondary), both OpenAI-compatible
chat APIs behind one shared HTTP helper (`_call_openai_compatible`). To go live,
set `llm.primary.api_key` / `llm.secondary.api_key` in `backend/config.json`
(or `GROQ_API_KEY`/`NVIDIA_API_KEY` env vars) — with both blank you get the
honest placeholder; if a live call fails, it falls back primary→secondary→
placeholder rather than fabricating anything. `model` is optional on both slots.
To swap in a different provider later (e.g. the client's actual on-prem LLaMA
endpoint), add it to `PROVIDER_ENDPOINTS`/`DEFAULT_MODELS` in
`rca_investigate.py` — the calling code doesn't change.
