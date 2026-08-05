# TODO — Demand Pattern RCA Console

Deploy **30 Jul 2026** · last dev day **29 Jul**. Ordered by priority.

## Done ✓ (2026-08-05, session 26 — Gemini added; two more Root Cause duplication bugs closed)
- [x] **Gemini wired in as a third LLM provider** via Google's OpenAI-compatibility endpoint
      (zero changes needed to `llm_client.py`/`_post` — same request/response shape as
      NVIDIA/Groq). Live-verified which models the account's key can actually use: all
      "flash"-tier models work (`gemini-3.6-flash` set as default, per the user's pick), all
      "pro"-tier models return `429 quota=0` on the free tier (needs billing enabled). Key lives
      in `backend/config.json`'s new `tertiary` slot — confirmed gitignored.
- [x] **Every ranked cause (up to 5) was getting the full 4-part narrative**, not just the
      winner — `prompts.py` required it unconditionally for both the prose instruction and the
      JSON schema's `explanation` field. Fixed: only rank 1 gets the full structure now; ranks
      2-5 get one short sentence. Directly caused the "5 full paragraphs = 5 competing root
      causes" pattern flagged in the Session 25 `yes.md` review, reproduced live with Gemini.
- [x] **`reasoning_narrative` still defaulted to `executive_summary`** even when a ranked cause
      existed — two separately-written model fields both describing the same winning cause,
      similar enough to notice as a repeat but different enough in wording that dedup missed it.
      Fixed in `business_report_generator.back_compat`: only falls back to `executive_summary`
      when there's no ranked cause to duplicate against. Live-verified on a real Brazil queue via
      Gemini: **7 Root Cause bullets → 1 clean bullet.**
- Verification note: a hand-rolled test script briefly gave a false "still 7 bullets" read
  because the script itself had drifted from the real `getRootCausePoints()` (it still simulated
  pulling from `key_findings`/`supporting_evidence`/`historical_comparison`, removed from the
  actual function back in Session 25). Rebuilt the test harness to mirror the live function
  exactly before trusting any further result — worth remembering next time a quick test
  contradicts a code-level fix that's otherwise clearly correct.

## Deferred — not urgent, do later
- [ ] **Canary QA pass on the `approved` branch** (pinned to `48e9711`). This branch was pushed as
      the business-approved Root Cause baseline (causal-clause contract + dynamic multi-factor
      driver attribution — see `README.md`'s example screenshot). No Canary session has been
      recorded against it yet; run one to get a real recorded trace/report before treating it as
      the reference build long-term.

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

## P1b — WFM engine follow-ups (branch `wfm-rca`, added 2026-07-28)
Contract + full detail: `IMP_DOCS/wfm-rca-engine.md`. The engine ships and runs; these are the
gaps between it and the business spec.
- [x] **SQL-backed WFM path re-verified after the refactor** (2026-07-28, VPN restored) —
      3.63s end to end, 103 history weeks, same-week-last-year found, all 5 ladder levels,
      real channel-sibling deltas, relationships retained on live data, and the ASU
      decomposition identity exact on 3 further real queues. See `wfm-rca-engine.md`.
- [ ] **A dead SQL host makes a `?mode=wfm` request wait ~42s** before degrading. The fetch is
      deliberately non-fatal (the engine still answers from the posted bundle), but the ODBC
      login timeout dominates. Lower the connect timeout for this path, or probe the host once
      and cache the result for a few seconds.
- [ ] **BLOCKING QUESTION · does the true Combined Queue span channels?** The console's
      signed-off CQN is `Forecast_name + Region + SubRegion + Country + Channel` (channel IS in
      the key, `rca_console.html:1653`), but the WFM spec wants migration *between channels
      within a CQN* — mutually exclusive. Migration detection currently uses a separately named
      proxy (`Region + SubRegion + Country + business_org`, flagged `is_cqn_proxy: true`).
      Answer decides whether the console's CQN definition changes or the check is renamed.
- [ ] **No evaluation set — ranking correctness is unmeasured.** Verification so far proves the
      engine runs and the deterministic gates fire, NOT that cause #1 is right. Need ~50-100
      past misses labelled by the forecasters, scored on top-1 accuracy. Prerequisite for any
      further prompt tuning; without it every prompt change is unfalsifiable.
- [x] **`correlation_engine` implemented** (2026-07-28) — `wfm/correlation_engine.py`. Rank
      correlation per driver with retain/reject thresholds (≥12 weeks, |strength| ≥ 0.5), plus
      the exact ASU driver decomposition. Unit-verified.
- [x] **`skeptic` now rejects in code** (2026-07-28) — `wfm/skeptic.py`. Feature preconditions
      for all 10 cause types (hard reject) + numeric grounding of every cited figure (prunes
      evidence). Verified: a `plan_restatement` claim on a week where the plan did not change is
      rejected. This was the highest-value accuracy defect.
- [x] **Split into reasoning modules** (2026-07-28) — `backend/wfm/` package, 13 modules;
      `backend/rca_wfm.py` kept as a compatibility shim.
- [x] **ASU driver decomposition wired as a first-class signal** (2026-07-28) — in
      `correlation_engine`, fed to the prompt as `CORRELATIONS`, and surfaced in
      `technical_metrics`. Original note kept below for the maths.
- [ ] ~~Wire the exact ASU driver decomposition as a first-class signal.~~
      `volume = (Actual_ASU − Planned_ASU) × planned_rate`, `rate = Actual_ASU × (actual_rate −
      planned_rate)`; these sum identically to the total error — verified exact on all 22,003
      flagged misses carrying both columns (60.7% rate-driven, 9.8% base-driven, 29.6% mixed).
      This is genuine attribution, unlike picking a label.
- [ ] **`derive_features` looks for a column named `ASU`** for the proof panel; the table only
      has `Planned_ASU` / `Actual_ASU`, so that proof row silently never populates.
- [x] **LLM timeout configurable in BOTH engines** (2026-07-28) — `llm.timeout_seconds` in
      `config.json`, set to **150**, honoured by `wfm/llm_client.py` AND
      `rca_investigate._call_openai_compatible` (falls back to the original 100 when the key is
      absent). **Note: this means `rca_investigate.py` is no longer byte-identical to
      `shivam-updates`** — traded deliberately because the UI's LLM path was failing ~1 in 3 on
      the old 100s ceiling (Canary V0.3 measured a call dying at exactly 100,121 ms).
      NVIDIA answers WFM investigations in 53–68s; **3/3 queues, 27/27 ranking checks**
      (`results/llm-ranking-report.json`).
- [ ] **~1 in 3 NVIDIA calls HANGS, and a bigger timeout does not help.** Measured on the default
      engine + NVIDIA: 52.5s `llm` / **300.7s fallback** / 43.9s `llm` at a 300s ceiling — the
      success rate stayed 2/3 and the failure just took 5 minutes, so 300 was reverted to 150.
      Real remedies: retry the same model once, or fall back to a second model on a hang. The
      latter conflicts with the deliberate "never answer a picked model with a different one"
      rule that keeps per-queue model comparison honest. **Needs a product decision.**
- [ ] **Validate `NA Core Spanish` week 202719 (actual 8,805) at source** — almost certainly a
      decimal shift, not demand. See `wfm-rca-engine.md`. This revises Session 15's conclusion.
- [ ] Consume the uploaded **CQN mapping file** in the WFM engine (today the grouping is a proxy).
- [ ] Optional: surface the new WFM keys (`ranked_root_causes`, `skeptic_review`,
      `investigation_trail`, collapsed `technical_metrics`) directly in the UI. Not required —
      the engine backfills the legacy keys so the current UI already renders it.

## P1c — defects found by Canary V0.1 (2026-07-28, all pre-existing in the UI)
Full detail + report path: `IMP_DOCS/canary-test-log.md`. None introduced by the WFM work
(`rca_console.html` unmodified on branch `wfm-rca`).
- [ ] **Uncaught `TypeError` on every page load** — `rca_console.html:2094` `renderProbe()` sets
      `#kbCount`, removed with the Probing layer (`e432543`), but is still called at line 2120.
      The throw aborts the block so line 2121 `renderPipe()` never runs and the initial pipeline
      strip is never painted. One guard clause. **Highest priority — it fires for every user.**
- [ ] **RCA Console flagged tile under-counts by 96** — RESOLVED against SQL: true count is
      **33,099** (the Dashboard figure). The tile shows `33,003`. Not explained by excluding
      `Actual_Offered = 0` (that gives 33,055). Fix the tile's scan, not the Dashboard.
- [ ] **Dashboard "Forecast names by adherence band" reads as broken** — 5 of 6 bands show
      `0 names · 0%` against non-zero week counts, because names are bucketed by their WORST
      week (all 427 have a >±25% week). Bucket by typical week, or relabel.
- [ ] **Model picker races the first RCA** — first Investigate click runs on the NVIDIA default
      (times out here) with no picker shown, because `RCA_MODELS` is still empty. Await
      `/api/models` before enabling, or default to Groq.
- [ ] **Unbounded percentages** — `acc 9700% / −9600% dev` is formula-correct with
      `fcst_offered = 0.34` but reads as garbage. Cap the display or special-case near-zero forecasts.
- [ ] **Timeline legend hardcodes "today (Wed 22 Jul)"** while the header computes 28 Jul.
- [ ] No favicon → a 404 on every load (cosmetic; it is the 404 in the console).
- [ ] **MONITORING TRAP: an LLM outage is invisible at the HTTP status layer.** Canary V0.5 measured
      `POST /api/rca-investigate?provider=groq` returning **HTTP 200 in 0.4s** while the upstream
      Groq call had 429'd — the backend deliberately swallows it and returns a successful
      deterministic payload. Anyone monitoring this endpoint by status code sees 100% success while
      every investigation is silently falling back. The truth is in
      `investigation_meta.engine` / `missing_information`. Consider a health signal or a metric
      that surfaces the fallback rate.
- [ ] **`_rcaCurrent` stores an INDEX, not a queue key** (`rca_console.html:2002`). Canary V0.5 saw
      no drift only because no filter or re-sort ran between model switches; apply a filter after
      an investigation and index 0 points at a different queue, so the next model change
      investigates the wrong one. Store the queue key instead.
- [ ] **`/api/data` ships 44.8 MB to the browser on every SQL connect** and takes ~12s (measured,
      Canary V0.4). It works, but it is the heaviest thing in the app: the whole 66,612-row table
      crosses the wire so the browser can aggregate it. Candidate for server-side aggregation or
      a paged/summary endpoint — the RCA path already queries SQL per queue via
      `/api/queue-context` (0.8-0.9s), so the full dump is only needed for the dashboard.

## P1d — defects found by Canary V0.2 (2026-07-28)
Recording in `results/canary-v0.2/`, full write-up in `IMP_DOCS/canary-test-log.md`.
- [ ] **Flagged-queue cards may not be clickable by a real pointer.** A native click on `#q0` was
      blocked 30s: `<input class="fsearch">` (`#filters`) and `<a data-tab="timeline">` (`.nav`)
      intercept pointer events over the queue list. The test only proceeded via `element.click()`.
      **A real user at that viewport may be unable to open a queue.** Highest severity.
- [ ] **Changing the AI model re-runs the PREVIOUS queue and overwrites the panel.**
      **Located precisely (Canary V0.4):** `onRcaModelChange` at `rca_console.html:1845` calls
      `triggerRCA(window._rcaCurrent)`, but `_rcaCurrent` is set ONLY inside `triggerRCA`
      (`:2002`) and `selectFlag` never clears it. So selecting a different queue and then changing
      the model re-investigates the previous queue while the new one is on screen. Observed live in
      V0.2 (header said `EC Comm Client Israel EUC Chat`, panel rendered `NA Core Spanish`).
      Fix: set/clear `_rcaCurrent` in `selectFlag`, or don't auto-rerun before an investigation exists.
- [ ] **Model picker only exists after a card is selected** (it lives inside `#investigationPanel`,
      built by `selectFlag()`). This is the mechanism behind the V0.1 picker-race finding.

## P1e — CQN mapping (loaded 2026-07-29) and the Data Pair pipeline
Loader: `backend/upload_cqn_mapping.py`. Source: `CQN and FC mapping.xlsx`.
- [x] **CQN mapping loaded into SQL** — `dbo.CQN_Mapping` (532 rows, Sheet1: Region, SubRegion,
      Channel, Offering, Forecast_Name, Combined_Queue_Name, DB_OSP) and
      `dbo.CQN_Forecast_Pair` (522 rows, Sheet3 Data Pair). Both indexed on Forecast_Name and
      Combined_Queue_Name. **Coverage: 427/427 queues mapped — 0 unmapped.**
- [x] **"unmapped" action item CLOSED** — every `Forecast_name` in `Input_To_ML` resolves to at
      least one Combined Queue. Re-check any time with
      `python upload_cqn_mapping.py --coverage`.
- [x] **The CQN definition conflict is RESOLVED — the spec was right.** 35 of 331 Combined Queues
      span more than one channel (e.g. `EMEA English ProSupp Client (Multi-Site)` = Case + Chat +
      Email + Voice over 9 forecast names). So channel IS NOT part of the CQN key, migration
      *within* a CQN is real, and the console's `cqnDimsKey` (`rca_console.html:1653`) is a
      **locality key, not the Combined Queue**. The WFM engine now groups channel siblings by the
      authoritative CQN and reports `is_cqn_proxy: false`.
- [x] **Sheet3 vs Sheet1 settled by measurement.** Sheet3 is the same mapping in PIVOT form with
      191 of 523 CQN cells blank (group labels written once). Forward-fill those and the two
      sheets agree on **442/442 names, 0 disagreements** — verifiable with
      `python upload_cqn_mapping.py --verify-sheets`. Read naively, Sheet3 maps 167 names to blank.
- [ ] **Rename the console's `cqnDimsKey`.** It is not the CQN — it is a locality key. Leaving the
      name as-is guarantees someone re-conflates the two concepts. Cosmetic but load-bearing.
- [ ] **Generalise the Data Pair upload into a reusable pipeline** (requested 2026-07-29). Today
      `upload_cqn_mapping.py` is hardcoded to this workbook's two sheet shapes. Wanted: one
      entry point that takes any "pair"-shaped sheet (two key columns, optional dimensions),
      auto-detects the header row, forward-fills pivot blanks, validates against a target table,
      reports coverage, and loads it — so future mapping files (site, vendor, LOB, skill) can be
      onboarded without new code. Should also accept `.csv`, and expose a `--replace` vs
      `--append` mode instead of always dropping the table.
- [ ] **BUSINESS DECISION NEEDED — 69 names map to MORE THAN ONE Combined Queue, and they carry
      41.7% of all demand.** Measured by `results/cqn_mapping_integrity.py`: 10,452 rows (15.7%)
      but **16.2M of 38.9M volume**. So this is not an edge case.
      Split by shape: **23 differ only by a vendor/site suffix** (ProSupport BRZ Voice vs
      ...SITEL; CHK Cons Tech Core BW vs ...Sykes; CGS vs Foundever, which is the same vendor
      rebranded) — those are resolvable by a naming rule. **46 are genuinely different queues**
      (e.g. `China Client Core Chat` → CCC Client Core Chat BW / CHK Cons Tech Chat Sykes /
      Hong Kong Client Chat Sykes). `DB_OSP` differs on only 39 of the 69, so it cannot
      disambiguate the rest.
      **Current behaviour: the UNION of a name's queues is used for sibling grouping.** The
      alternative is investigating per-CQN and reporting separately. Needs the business to say
      which.
- [ ] **Wire the mapping into the CONSOLE too.** The UI still shows the `unmapped` badge and reads
      an uploaded mapping file client-side; it does not know about `dbo.CQN_Mapping`. An endpoint
      (e.g. `GET /api/cqn-mapping`) would remove the badge and let the dashboard group by real
      Combined Queue.

## P1j — RCA output quality, from Canary V0.6 (file-upload, no SQL) — 2026-07-30
Recording: `results/canary-v0.6-fileupload/canary-v0.6-fileupload.mp4` (4.2 MB) + report/screenshots.
Case: `NA Federal Standard` FW202719, Groq llama-3.3-70b-versatile, `engine: wfm-llm`.
Forecast 364.04, actual 1,525, adherence **-318.9%**, a 1,161-contact miss (materially large, not a
small-denominator artefact).

### CONFIRMED WORKING
- [x] **Negative adherence now shows correctly in the top UI** — header `-318.9%` and the FINDINGS
      line `-318.9%` agree, caption reads "Under-forecast — actual came in above plan". The old
      header/findings disagreement is gone. (Committed: `b919739` + `8308730`.)
- [x] **File-upload path works with no SQL at all** — 7,350 rows, 42 forecast names from
      `file1.csv`; `mapBadge` = "CQN mapped · 443 entries"; **0 of 250 cards unmapped** after the
      mapping upload.

### CORRECTION TO AN EARLIER CLAIM — I was wrong, the business was right
I reported that SUPPORTING EVIDENCE / REJECTED HYPOTHESES / HISTORICAL COMPARISON "render empty
despite the API returning their data". **That is wrong.** Those three are
`<details class="inv-sec">` with **no `open` attribute** — collapsed by design (`rca_console.html`
~2061/2065/2070), while Proof / Key Findings / Narrative / Recommendations / Missing Information all
carry `open`. They contain their data; they simply start closed. The tester read `innerText`, got
only the `<summary>` text, and concluded "empty" — and I repeated it without checking.
**Canary V0.1 already documented this exact trap** ("they look empty in innerText but are not") and
I failed to apply my own earlier finding. The recording never scrolled or expanded below Proof,
which is what surfaced the mistake.
- [ ] **Future browser QA must EXPAND every `<details>` before judging a panel empty.** Add it to
      the session brief as a standing rule.
- [ ] Consider whether Supporting Evidence and Historical Comparison should default to `open`.
      A business reader is unlikely to click three disclosure triangles, so the strongest evidence
      is effectively hidden. Product decision, not a bug.

### REAL DEFECTS — still valid after the correction

- [ ] **THE SERIOUS ONE: the root cause states the chronic direction BACKWARDS.** The headline says
      the queue has *"consistently been under-estimating the demand"*. The data says the opposite,
      verified arithmetically:
        history 364.5 actual vs 414.5 forecast -> adherence **+12.1% = chronically OVER-forecast**
        this week 1,525 actual vs 364.04 forecast -> -318.9% = under-forecast **this week only**
      KEY FINDING 3 correctly says "over-forecast in most recent weeks", and the historical panel
      independently says "trends below forecast, average adherence 12.2%" — matching +12.1%. So two
      parts of the same report contradict the conclusion drawn from them. A forecaster will spot
      this immediately and stop trusting the output.
      **Fix:** `chronic_bias.consistent_direction` is already computed deterministically. The
      narrative must be made to USE it rather than letting the model infer direction from prose.
      Same principle as the KPI and the migration verdict: compute it, then overwrite.
- [ ] **The root cause is one idea repeated seven times.** Bullet 1 is a paragraph; bullets 2-5 are
      that paragraph split into its own sentences; 6-7 restate it again. Almost certainly the
      "guarantee minimum 6 comprehensive bullet points" rule (`79cb90f`) manufacturing volume where
      there is only one idea. One bullet is also circular — *"Because the forecast was generated
      independently for this queue, it became under-forecast"* asserts a mechanism with no evidence.
      **Question for the business:** was the 6-bullet floor a stakeholder ask? If so the fix is not
      removing it but giving the model more genuine content to fill it.
- [ ] **`DERIVED_FEATURES` is printed to the business reader, twice**, inside ROOT CAUSE prose. An
      internal payload block name. Same class of leak as `peers[0].computed.error`. The language
      guard (on `wfm-rca`) should be extended to strip internal block names, not just statistics
      vocabulary.
- [ ] **MISSING INFORMATION shows four bare internal tokens** instead of sentences:
      `Actual_ASU · CHANNEL_SIBLINGS · INVESTIGATION_LADDER · DATA_QUALITY`. These should read as
      plain English ("the channel-sibling comparison was unavailable because ...").
- [ ] **"No recommendations yet" is false.** Every ranked cause carries a `recommended_action`
      (e.g. "Review the forecasting process to identify and address the systematic bias"), but the
      top-level `forecast_improvement_recommendations` was null, and that is what the UI reads.
      Back-fill it from the causes.
- [ ] **Footer says "based on 0 field(s)"** — `fields_used` is null in the WFM response, while the
      default engine populated it. Back-fill it.
- [ ] **`technical_metrics` is never rendered (0 UI refs)** and contains
      **`Forecast Error = 1160.9627879`** — an unrounded float waiting to be displayed. The
      `_round_display` fix is on `wfm-rca`, not this branch.
- [ ] **"3 of 7 similar queues (same region, country and channel)"** still appears — the analyst
      phrasing, and the locality group rather than the Combined Queue. The CQN-naming fix is on
      `wfm-rca` (`b1c0fd6`) and is not on this branch. (It also needs SQL, which this run did not
      have.)
- [ ] **Flagged list caps at 250 with no indication** — 3,091 flagged, 250 rendered, no
      "showing 250 of 3,091" note. A reader cannot tell the list is truncated.

### QA / environment friction worth fixing
- [ ] **The sticky `#filters` panel and `.nav` bar intercept clicks over `#qlist`** at ~929px width;
      a forced click landed on the Timeline nav link and silently switched tabs. Widening to 1680px
      fixed it. Third session in a row hitting this — it is likely affecting real users on smaller
      screens, not just automation.
- [ ] **`renderProbe` TypeError still fires on every page load** (`rca_console.html:2211`, called
      from `:2237`). Unfixed across V0.1, V0.2, V0.3, V0.4, V0.5 and now V0.6.
- [ ] Note for testers: the weekly file input is `id="fileWeekly"` (not `fileInput`), the RCA tab is
      `#tab-console` (not `#tab-rca`), and Canary cannot `setInputFiles` from a real path — the file
      must be base64'd into `~/.canary/tmp` and passed as a buffer.

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
- [ ] **Re-enable the Probing layer (Phase 2).** Hidden from the RCA Console UI on 2026-07-27 (HTML block commented out in `rca_console.html`; `renderContextProbes()` no-ops when its elements are absent). The JS — `renderContextProbes` (data-driven probes: restated plans, top flagged forecaster, unscoreable rows), `PROBES` (static domain questions), `saveKnowledge`/`downloadKB` (Markdown KB, localStorage) — is intact and ready. Bring it back when building the knowledge-base / RAG phase.
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
