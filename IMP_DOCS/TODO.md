# TODO — Demand Pattern RCA Console

Deploy **30 Jul 2026** · last dev day **29 Jul**. Ordered by priority.

## P0 — critical path to the mockup
- [x] **P6 · Connect to SQL Server (AA)** — **DONE.** Live ingestion via FastAPI + pyODBC backend (`GET /api/data`); 138,775 rows loaded into `Playground.dbo.Input_To_ML`; console button wired; hosting packaged (Docker/Windows-service/systemd). See `IMP_DOCS/installation-and-connection.md`.
- [ ] **P4 · Phase-1 digest** — one-click export of *all* flagged queues (multi-queue scan → top-N → printable/report page). Main remaining build.
- [ ] **P7 · Validation with Prashant / SME** on the full real dataset — must land by **28 Jul** to keep a buffer day.
- [ ] **Confirm the adherence band** — ±10% vs ±15%, and whether it tiers by `Volume_Category`. Blocks tuning.
- [ ] **P8 · Demo packaging + dry run** (28–29 Jul) — walkthrough script, rehearsal, digest export sanity check.

## P1 — correctness / data questions to close (probing layer)
- [ ] Source of truth for adherence — **Offered vs Handled**?
- [ ] On **Projection_plan restatement** mid-cycle, is the miss forgiven? (auto-probe already flags restated queues)
- [ ] Exact meaning of **ASU** (Planned/Actual).
- [ ] Treatment of **holiday weeks** (`Holiday_Count > 0`).
- [ ] Per-**Offering** / per-**Channel** acceptable bands, if any.

## P2 — dashboard / UX polish (post-deadline OK)
- [x] High-cardinality dimension cards showed 0% shares — now show row counts; Fiscal_Week dropped from the grid; panel made bolder/cleaner. (2026-07-22)
- [ ] Trend charts: optional brush/zoom for the 325-week span; shared hover legend across the two trend charts.
- [ ] Export the Dashboard as a PNG/PDF for the digest.
- [ ] Consider a light/dark toggle for the console itself (timeline already themes; console is light-only).

## P3 — architecture phase (out of 30 Jul scope)
- [x] ~~Paste real Groq/NVIDIA API keys~~ — **done and live-verified.** One fix was needed: Groq sits behind Cloudflare bot-management, which blocked `urllib`'s default `Python-urllib/3.x` User-Agent with an HTTP 403 ("error code: 1010"). Fixed by sending a normal `User-Agent` header in `_call_openai_compatible` (`rca_investigate.py`) — not spoofing a browser session, just not announcing "bare script." Confirmed live: Groq now returns a real root cause with cited evidence, a rejected hypothesis with a valid reason, and forecasting-only recommendations.
- [x] **Security:** real API keys were briefly pasted into `backend/config.example.json` (the committed template) instead of only `config.json`. Caught before it was staged/committed or pushed — confirmed absent from git index and history, template restored to empty placeholders. No rotation needed, but worth a reminder to only ever paste secrets into `config.json`/`.env`, never the `.example` files.
- [x] **Fixed a real payload-size bug**, found from an actual production row: Groq rejected the request with `413 tokens per minute limit exceeded` (real bundle ≈13,916 tokens vs. Groq's 12,000 TPM cap); NVIDIA timed out on the same oversized payload. Root cause: `history`/`peer` entries were sending the full 33-column raw record per row (up to 12 history + N peers), duplicating what `statistical_summary` already distills generically. Fixed by slimming history/peer entries to `{key, computed}` only in the bundle actually sent to the model (the TARGET row keeps its full raw fields — it's the one row being explained — and `statistical_summary` is still computed from the full, untrimmed data first, so no generic signal is lost). Added `RCA_PEERS_CAP=15` (sorted by \|error\| so the most-diverged peers survive the cap) alongside the existing `RCA_HISTORY_CAP=12`. Also added a server-side safety net: on an HTTP 413 specifically, retry once with history cut to the last 3 weeks and peers dropped, before falling through to the next provider. Stress-tested with a deliberately worst-case bundle (33 target fields + full history/peer caps + 33 statistical_summary fields) against the real Groq API: ~3,200 tokens, comfortably under the limit; confirmed via mocked test that the 413-retry path itself works correctly.
- [ ] Wire the two metrics as **MCP tools** + SQL metric views.
- [ ] RAG over the probing KB to auto-surface known causes on matching queues.
- [ ] Let confirmed KB rules feed back into flag suppression / re-flagging.
- [ ] Longer-term: swap Groq/NVIDIA for the client's actual on-prem LLaMA endpoint once reachable (same `call_model()`/provider-slot pattern, just a new entry in `PROVIDER_ENDPOINTS`).

## Done ✓ (2026-07-24, session 5 — browse any queue without code changes)
- [x] The "Test specific Forecast_name(s)" box now has a native `<datalist>` autocomplete populated with every distinct `Forecast_name` in the loaded data (refreshed in `buildFilters()`) — type a few letters to browse, no need to know or spell the exact name.
- [x] Added a **🎲 Random queue** button (`pickRandomQueue()`) — one click jumps to an arbitrary Forecast_name from the loaded data and focuses it, so any queue (flagged or not) is reachable with zero typing and zero code changes, ever.
- [x] `triggerRCA` no longer dead-ends on a manually-picked queue/week that isn't an automatic miss — it now shows **"🔎 Investigate anyway"**, which re-invokes with `force=true` to bypass the auto-trigger gate for that one deliberate, human-initiated click. The automatic path (a row reaching `FLAGS` at all) is unchanged — still gated on a real miss beyond band, per spec step 1.
- [x] Verified: datalist contains a queue that never flags; random-pick can reach it; browsing to it and clicking Investigate without `force` shows the override button (not a dead end); clicking through with `force=true` actually proceeds through the full pipeline.

## Done ✓ (2026-07-24, session 4 — live evidence check + priority swap)
- [x] **Proved the pipeline against the real database, not synthetic data** — connected directly to the real SQL Server (`10.10.9.75`/`Playground`) and ran two real flagged queues end-to-end through the actual LLM: "Portugal Client Core"/202722 (real 12-week declining history, zero real peers → model correctly concluded "unusual **decrease**") and "ROLA COMM Client ProSupport Upsell"/202722 (real 3-sibling CQN group → model cited the actual peer names and actual error values in its evidence). Confirmed the "generic copy-paste" impression was about the model's reasoning tendency, not the data pipeline — the data plumbing is genuinely per-queue.
- [x] Found a real wording imprecision from that live test: when peers move the SAME direction as the target (shared decline), the model described it as a "shift... between sibling queues" — language that only fits OPPOSITE-direction peers. Not yet fixed — flagged for a follow-up prompt tweak to distinguish "shared regional/channel decline" from "routing shift between siblings."
- [x] Diagnosed a second stale-server 404 (`GET /api/queue-context` → 404) as the same class of bug as the earlier 405 — the new route didn't exist in the already-running process. Confirmed fixed by restart (verified the exact failing request succeeds in a fresh process).
- [x] Swapped LLM priority to **NVIDIA primary, Groq secondary** in `config.json`/`config.example.json`/`.env.example`/`docker-compose.yml`, per request. While doing this, found and fixed a real latent bug: the env-var override logic in `load_config()` matched `GROQ_API_KEY`→primary-slot and `NVIDIA_API_KEY`→secondary-slot by **fixed position**, which would have silently undone this exact swap the moment either env var was set (e.g. via Docker). Now matches env vars to whichever slot names that provider, regardless of position. Verified live: `investigation_meta.provider` now correctly reports `nvidia` as the one actually used.
- [x] Recreated `backend/.env.example` (found deleted from the working tree, not by this session) since it's referenced by `docker-compose.yml` and contains no secrets.

## Done ✓ (2026-07-24, session 3 — SQL-scoped querying for RCA)
- [x] Added `GET /api/queue-context` to `sql_backend.py` — queries SQL Server directly for just the selected queue's own row + prior-week history + same-week CQN peers, via parameterized queries (no injection risk), instead of the console filtering the whole already-loaded table client-side.
- [x] `aggregateData(r)` (client-side) now calls this endpoint when the console's data source is SQL (`window.SRC==='sql'`); file-upload mode keeps the existing in-browser filtering (no SQL connection to query), and the SQL path falls back to in-browser filtering too if the scoped query fails for any reason — investigation never breaks outright over this.
- [x] Fixed two real bugs surfaced while wiring this in: a stray unused `aggregateData(r)` call in `triggerRCA` that would have fired a wasted duplicate SQL request every time, and a missing `await` on `buildContext(r)` that would have sent a Promise object instead of the actual context bundle once it became `async`.
- [x] Verified: query construction (parameterization, `TOP N` caps, chronological history ordering) with a mocked SQL connection; the full client-side branch logic (file-upload mode never calls fetch, SQL mode calls the right endpoint with the right params and correctly hydrates raw SQL rows into the same shape as in-browser rows, SQL-failure fallback, and a full `triggerRCA` run through both endpoints) — all via stubbed `fetch`, no real SQL Server access needed to verify the logic.
- [x] Clarified for the user: the LLM payload was already scoped to just one queue's data before this change (target + its own history + CQN peers, capped) — the earlier rate-limit bug was from duplicated raw fields per row, not from sending unrelated queues' data. This change makes that scoping happen via a real SQL query instead of filtering an already-fully-loaded in-browser array, which matters once the table is large enough that preloading all of it becomes the bottleneck.

## Done ✓ (2026-07-24, session 2 — live LLM wiring)
- [x] **Groq (primary) + NVIDIA (secondary fallback)** wired into `backend/rca_investigate.py::call_model()` — both OpenAI-compatible chat APIs behind one shared HTTP helper, automatic fallback chain (Groq → NVIDIA → honest placeholder), robust JSON extraction from prose/fence-wrapped model output, and response coercion so a malformed model reply can't crash the renderer.
- [x] `forecast_summary` in every response (real or placeholder) is always sourced from our own deterministic computation, never the model's echo — the one part of the output that's pure fact can't drift even slightly.
- [x] Config shape updated to named `primary`/`secondary` slots in `config.json`/`.env.example`/`docker-compose.yml`; `config.json` already has empty key placeholders ready to fill in.
- [x] Verified with 7 backend tests (mocked HTTP calls — no real key needed to test the logic): no-config placeholder, successful primary call, primary-fails-secondary-succeeds fallback, both-fail honest placeholder citing both failures, fenced/prose JSON extraction, and malformed/non-dict model response handling.
- [x] Fixed the sign/terminology in the Forecast Adherence findings text per user correction (kept the mathematically-verified sign pairing, added the requested over/under-forecast synonyms).

## Done ✓ (2026-07-24 — Root-Cause Investigation rebuild)
- [x] **Removed** the earlier rule-based/"agentic exploration" RCA panel (trend/sibling/discovery-lift/memory, all deterministic) per client instruction — replaced with a genuine LLM-investigation architecture; the old approach risked presenting scripted JS as if it were free-form model reasoning.
- [x] Signed **Plan Adherence** (ABS removed from the formula and every place it's displayed); flagging/severity/sort/MAPE all updated to compare on magnitude while the displayed number stays signed.
- [x] Modular architecture per the client's exact spec: RCA Trigger, Data Aggregator, Context Builder, LLM Investigation Engine, RCA Formatter, UI Renderer.
- [x] Data Aggregator + Context Builder are **fully generic** — no hardcoded field list; verified in testing that an untouched column (`Final_upp_units`) was auto-discovered and included.
- [x] Real backend proxy (`POST /api/rca-investigate` in `sql_backend.py` + new `backend/rca_investigate.py`) — keeps any future provider key server-side, since the repo/site is public.
- [x] Honest placeholder investigation response (empty root-cause/hypotheses + explicit `missing_information`, never a fabricated conclusion) until a provider is wired.
- [x] Investigation-report UI: Forecast Summary, Investigation Timeline (reuses the existing pipeline-strip visual language), Key Findings, Root Causes (confidence bar + evidence chips), Supporting Evidence, Rejected Hypotheses, Historical Comparison, Reasoning Narrative, Forecast Improvement Recommendations, Confidence, Missing Information — all collapsible via native `<details>`.
- [x] Verified end-to-end with a DOM-stub harness + stubbed `fetch` (no live backend needed) — aggregator/context-builder correctness, placeholder + mock-LLM render paths, and the backend-unreachable error path all pass.
- [x] **Adversarial spec-compliance review** (4 independent reviewers + adjudication) against the client's exact written spec, then fixed every confirmed finding:
  - **Fixed a pre-existing CRITICAL security hole**, found in passing: `sql_backend.py`'s static mount served the entire repo root, so `GET /backend/config.json` returned the **real, live SQL Server credentials** in plain text (confirmed exploitable before the fix). Added middleware blocking `/backend/*` and dotfiles before the static handler. **This predates the RCA feature and was already exploitable in production — worth telling Prashant/whoever manages the AA-network deployment, and rotating the SQL credentials as a precaution** since there's no way to confirm nobody hit that path already.
  - Replaced a hardcoded, unconfirmed "25% = critical" severity cutoff with a pure ratio of the two already-confirmed numbers (`|deviation| ÷ band`, e.g. `2.2× band`) — no new invented threshold.
  - Fixed the engine badge to fail closed toward "uncertain" (requires explicit `engine==='llm'`) rather than failing open toward "real AI" on any non-`'placeholder'` value.
  - Documented (not code-changed, to avoid inventing a new rule): peer-matching ties to the client-CONFIRMED CQN key (not invented, but a fixed column-name assumption worth flagging for reuse); recommendations guardrail belongs in the model's system prompt, not a hardcoded keyword filter; "pattern deviations" is intentionally left for the LLM to derive from `is_outlier`/`trend_slope`/`changed` rather than a hand-picked score.

## Done ✓ (2026-07-24, sessions 7–11 — dashboard filters, popup, run tooling, data scope)
- [x] Dashboard **dropdown filters** (Region…Projection plan) driving the scan engine → affected/flagged queues per selection
- [x] **Fiscal Week — typeable (Excel-style)** (exact / partial / comma / range) with datalist type-ahead
- [x] **Affected-queues popup** on Fiscal Week select — real flagged names (name·week·signed adherence·band·direction), no fabrication; **ⓘ** hint button
- [x] **"Forecast names by adherence band"** chart (≤±5 / ±5–10 / ±10–15 / ±15–20 / ±20–25 / >±25); renamed the all-weeks spread
- [x] **Data-ingestion loading screen** (6-step overlay, file + SQL paths)
- [x] **run.ps1 / run.sh** one-command runner; **AGENTS.md / CLAUDE.md** AI runbook
- [x] **Truncated data to FY2025–2027** (138,775 → 66,612 rows) + loader Fiscal_Week filter so reloads stay truncated

## Done ✓ (2026-07-24, session 6 — merge Shivam's dashboard + timeline polish)
- [x] Merged `origin/shivam-updates` into main (clean, merge `babf5a1`) — both feature sets intact; his branch left untouched (0 ahead of main)
- [x] **"Plan Adherence" → "Forecast Adherence"**, now **signed** (− = actual above forecast, + = below); flag on **|Forecast Adherence| > band**
- [x] Dashboard: deviation colour-bands, flagged-% KPI, right-side **Insights drawer**, signed adherence, **agentic deep-dive / exploration-trace** UI (Shivam)
- [x] Timeline: added **"RCA output — report per queue"** (now 10 steps); **auto-date from the PC clock**; plain-English step names; light-only
- [ ] Cosmetic: clean up the last 2 legacy "Plan Adherence" strings in the UI (notes card + code comment)

## Done ✓ (2026-07-23, session 5 — SQL Server (AA) live)
- [x] FastAPI + pyODBC backend (`backend/sql_backend.py`): `/api/health`, `/api/data` (`SELECT * FROM <table>`), also serves the UI
- [x] Excel→SQL loader (`upload_excel_to_sql.py`, `--dry-run` / `--schema-only`) — loaded **138,775 rows** into `Playground.dbo.Input_To_ML`
- [x] Console "Connect to SQL Server (AA)" wired to `/api/data` (was a file-picker mock); modal shows real server/db/table
- [x] Deployment package: `Dockerfile` (bundles msodbcsql18) + `docker-compose.yml` + env-var secrets + `DEPLOY.md`
- [x] Timeline renames: P2 → "Accuracy & Error Computation (100-MAPE)", P5 → "Data Volumetrics"; P6 marked Done
- [x] `IMP_DOCS/installation-and-connection.md` added

## Done ✓ (2026-07-22, session 4 — RCA analytics bundle)
- [x] Actual-vs-Forecast weekly overlay (two-series, one y-scale)
- [x] Signed forecast bias (diverging) by Region + top over/under-forecast queues
- [x] Rule-based auto-insight callouts (scope-aware) + KPI delta vs baseline on drill

## Done ✓ (2026-07-22, session 3)
- [x] Volumetrics **drill-down** — click any dimension value to re-scope the whole panel card-by-card; breadcrumb + clear; expandable member lists; row counts (not 0% shares)
- [x] Pushed project to GitHub `AABH-AI/pattern_analyzer2` (public) + `index.html` Pages entry

## Done ✓ (2026-07-22)
- [x] 10-dimension filters
- [x] `fcst_offered` → "forecast offered (Simple)", 2-dp display (calc intact)
- [x] Stray `''` after Fiscal Week removed
- [x] Avg Accuracy → 100 − MAPE (77.1% full file)
- [x] EPIC volumetrics + **Dashboard** tab with graphs
- [x] Data-driven probing auto-probes + category + captured context
- [x] Deadline **Gantt** embedded (Timeline tab) + standalone `rca_timeline.html` refreshed
- [x] Project folder + IMP_DOCS
