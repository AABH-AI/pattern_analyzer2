# Canary UI test log

Browser-driven QA sessions recorded with the Canary plugin (real Chromium, Playwright trace +
video + HAR + console capture per step, then a self-contained `report.html`).

Versioning: **V0.1**, **V0.2**, … one entry per recorded walkthrough. Newest last.

---

## Canary Version V0.1 — 2026-07-28 · first full walkthrough (branch `wfm-rca`)

**Verdict: core flow PASSES end to end.** Page load → SQL connect → fetch + pipeline →
flagged-queue scan → RCA investigation via Groq → all 8 tabs. **6 defects found, all
pre-existing in the UI** — `rca_console.html` was not modified by the WFM work
(`git diff --stat shivam-updates -- rca_console.html` is empty), so none of these were
introduced by it.

- Report: `C:\Users\arnav.bhargava\.canary\sessions\demand-pattern-rca-console---full-qa-walkthrough-ms4r0giq-6b2389\report.html`
- Target: `http://localhost:8000/rca_console.html`, live SQL `Playground.dbo.Input_To_ML`
- Backend: restarted immediately before the run, including the 614× SQL fix (below)

### What the UI reported

Pipeline strip: Ingest `66,612 rows` → Compute `51,905 scored` → Flag `33,003 flagged`.
All 6 pipeline stages reached `done`. Header tiles: `427 Forecast names`, `66,612 Rows`,
`33003 Flagged (±band)`, `75.8% Avg accuracy (100−MAPE)`.

Flagged list is a card list (not a table), **250 cards rendered** against a 33,003 count —
i.e. the list is capped for rendering. First entry:
`NA Core Spanish (unmapped) · Americas · United States · Voice · FW 202719 · acc 9700% · −9600% dev`.

### Every UI number cross-checked against SQL

| UI showed | SQL query result | Verdict |
|---|---|---|
| `66,612 rows` | 66,612 | exact |
| `51,905 scored` | 51,905 (`fcst_offered` usable AND `Actual_Offered` not null) | exact |
| `427 Forecast names` | 427 distinct `Forecast_name` | exact |
| `33,003 flagged` (RCA Console tile) | **33,099** | **tile is WRONG (−96)** |
| `33,099 wks flagged` (Dashboard) | 33,099 | correct |
| RCA case adherence `−5792.2%` | `(1 − 20.0/0.339433394892406)×100 = −5792.2%` | exact |
| RCA case accuracy `5892%` | `20.0/0.339433394892406×100 = 5892.2%` | exact |
| Proof `fcst_offered = 0.34` | 0.339433394892406 | exact (rounded for display) |
| Proof `Actual_Offered = 20` | 20.0 | exact |

The two metrics and the proof panel reconcile to the source data to the decimal. The only
numeric defect found is the flagged tile.

### RCA output verified rendering correctly

Queue `EC Comm Client Israel EUC Chat`, FW `202715`, engine `llm · llama-3.3-70b-versatile`:

- Forecast `0.34`, Actual `20`, adherence `−5792.2%`, miss type Under-Forecast
- **Proof panel rendered with real values** (`fcst_offered` 0.34 vs usual 1.4; `Actual_Offered`
  20 vs usual 5.6)
- Key findings, root cause (`forecast_baseline_error`, 80% High), a 60% secondary, rejected
  hypotheses, historical comparison, reasoning narrative, recommendations, missing information
  — **all populated, no blank panel**
- Note for future testers: `SUPPORTING EVIDENCE` / `REJECTED HYPOTHESES` /
  `HISTORICAL COMPARISON` are `<details>` collapsed by default, so they look empty in
  `innerText`. They are not blank — 512 / 455 / 244 chars of content confirmed inside.

### Network

Every API call returned 200: `/api/health`, `/api/data`, `/api/models`, `/api/queue-context`,
`/api/rca-investigate?provider=groq&model=llama-3.3-70b-versatile`. Zero request failures.
Only non-200 in the whole session: `GET /favicon.ico` → 404 (browser default; no `<link
rel="icon">` and the backend serves no favicon — benign).

### Defects found — all pre-existing, none from the WFM work

1. **Uncaught `TypeError` on EVERY page load** — `rca_console.html:2094` in `renderProbe()`:
   `document.getElementById('kbCount').textContent = KB.length+' entries'`. `#kbCount` /
   `#kbList` were removed when the Probing layer was hidden (commit `e432543`), but
   `renderProbe()` is still called unconditionally at line 2120.
   **Real impact:** the throw aborts the rest of that inline script block, so line 2121
   `renderPipe()` never runs and the initial "all stages pending" pipeline strip is never
   painted on load. Highest-priority fix — one guard clause.
2. **Flagged-week count disagrees between views — RESOLVED against SQL: the Dashboard is
   right, the RCA Console tile is wrong.** Tile says `33,003`, Dashboard says `33,099`.
   Direct query:
   `WHERE fcst_offered IS NOT NULL AND fcst_offered<>0 AND Actual_Offered IS NOT NULL AND
   ABS(1.0-Actual_Offered/fcst_offered)*100 > 10` → **33,099**. The RCA Console tile
   under-counts by 96 weeks. Excluding `Actual_Offered = 0` gives 33,055, so that is not the
   explanation — the tile's scan is dropping 96 rows for another reason. Fix the tile.
3. **Dashboard "Forecast names by adherence band" conveys nothing** — 5 of 6 bands read
   `0 names · 0%` while showing non-zero week counts (`≤±5% → 0 names · 9,815 wks` …
   `>±25% → 427 names · 100% · 15,265 wks`). Arithmetically consistent with bucketing each
   name by its *worst* week (all 427 names have at least one >±25% week), but it reads as
   broken. Should bucket by median/typical week, or be relabelled.
4. **Timeline tab date contradiction** — header "Today is Tue 28 Jul 2026 · 2 DAYS UNTIL THE
   DEMO" while the legend hardcodes `▏ = today (Wed 22 Jul)`.
5. **Model picker races the first RCA** — `rcaModelPickerHtml()` returns "AI model picker loads
   when the backend is running." while `RCA_MODELS` is empty, so the **first** Investigate
   click runs on the NVIDIA default, which times out on this network, and no picker is offered.
   It appears only after `loadRcaModels()` has run once. Fix: await `/api/models` before
   enabling the button, or default to the Groq entry.
6. **Unbounded percentages read as garbage** — flagged cards show `acc 9700% / −9600% dev` and
   `acc 5892% / −5792% dev`. Correct per the documented formula with tiny denominators
   (`fcst_offered = 0.34`), but needs display capping or a "forecast near zero" treatment.

### Backend fix made during this session (in `rca_wfm.py`)

The channel-sibling query resolved the prior week with a correlated subquery
(`... OR Fiscal_Week = (SELECT MAX(Fiscal_Week) ... < ?)`). On this un-indexed table that
measured **101.5s**, while every other query in the module runs in 0.02–0.05s — a WFM
investigation appeared to hang. The prior week is already known from the 104-week history, so
it is now passed as a literal and the query is a two-value equality lookup.

`fetch_wfm_context`: **98.19s → 0.16s (614×)**, identical results (92 sibling rows, same
verdicts). Measured before and after.

### WFM engine states confirmed live after the fix

| Call | Result | Time |
|---|---|---|
| `?mode=wfm` on an in-band bundle (−3.0%) | `engine: wfm-not-investigated`, 0 causes | 0.60s |
| `?mode=wfm&provider=groq` on a breached bundle | `engine: wfm-llm`, #1 "Suspected data quality issue" 80% High, #2 "Inherited miss from higher level" 60% Medium | 3.65s |
| no `mode` (default engine) | `engine: llm`, legacy keys present, **no WFM keys leaked** | ~4s |

### Not covered by V0.1 — do these in V0.2

- The `?mode=wfm` engine was exercised via `curl`, **not through the UI** — the console has no
  WFM toggle yet, so the browser session tested the default engine only.
- File-upload mode (`Upload weekly file`) untested.
- CQN mapping file upload untested.
- Digest / multi-queue export (P4) untested — not built yet.
- No assertion on numeric correctness of dashboard tiles beyond the row count.

---

## Canary Version V0.2 — 2026-07-28 · end-to-end session with video (branch `wfm-rca`)

**Verdict: core flow PASSES end to end. 3 NEW bugs found**, including one that may block a real
user from clicking a queue card. 25 recorded steps, video + trace + HAR + console captured.

- Session dir: `C:\Users\arnav.bhargava\.canary\sessions\wfm-e2e-v02-ms4wyda1-f2f37b`
- **Recording copied into the repo: `results/canary-v0.2/`** (25 MB — video 17.7 MB WebM,
  `report.html` 3.7 MB, 25 step screenshots, `network.har`, `console.log`)
- `trace.zip` (7.1 MB) left in the session dir — view with `npx playwright show-trace`
- Video note: Canary records **one WebM per browser page for the whole session**, not one clip
  per step. Per-step evidence is the 25 screenshots, each bound to its step in the report.
- **Format is WebM (VP8), not MP4** — plays natively in Chrome/Edge/VLC. Playwright's bundled
  ffmpeg cannot transcode it (PNG + VP8 encoders only, no MP4/MOV muxer); a full ffmpeg install
  is required for MP4. Command in `results/README.md`.

### Verified again

- Row count `66,612` — matches SQL exactly. `GET /api/data` took 12,676 ms (HAR).
- 250 flagged cards rendered (list is capped; 33,099 flagged weeks total).
- Model picker offers all 5 models and correctly routes:
  `?provider=groq&model=llama-3.3-70b-versatile` confirmed in the request URL.
- **Two full RCA reports rendered completely**, including the Proof panel with real numbers, and
  every collapsed `<details>` confirmed non-empty (165–703 chars each):
  - `NA Core Spanish` FW202719 — genuine demand event, 60% Medium; forecast 90.78 vs actual 8,805
  - `Social Media Turkish` FW202526 — systematic forecast bias, 35% Low; forecast 3.04 vs actual 76
- Both showed `Engine: deterministic-fallback`, correctly, with the reason visible in MISSING
  INFORMATION: `groq HTTP 429 … tokens per day (TPD): Limit 100000, Used 98586`. Honest
  degradation, not a failure. (LLM coverage was obtained separately — see
  `results/llm-ranking-report.json`, 3/3 on NVIDIA.)
- All 8 tabs render. Zero failed network requests; all 11 `/api/*` calls returned 200.

### New bugs (V0.2)

1. **Flagged-queue cards are not reliably clickable by a real pointer.** A native Playwright
   click on `#q0` was blocked for 30 s — `<input class="fsearch">` from `#filters` and
   `<a data-tab="timeline">` from `.nav` intercept pointer events over the queue list. The test
   only proceeded via `element.click()`. **A real user at that viewport may be unable to click a
   card.** Highest-severity new finding.
2. **Changing the AI model re-runs the PREVIOUS queue and overwrites the current panel.**
   `onRcaModelChange()` calls `triggerRCA(window._rcaCurrent)`, but `_rcaCurrent` is stale after
   `selectFlag()`. Observed live: the report header read `EC Comm Client Israel EUC Chat` while
   the panel rendered `NA Core Spanish · FW 202719` — a real server call for the wrong queue.
   Fix: set `_rcaCurrent` in `selectFlag()`, or do not auto-rerun before an investigation exists.
3. **The model picker only appears after a flagged card is selected** — it lives inside
   `#investigationPanel`, which `selectFlag()` builds. This is the mechanism behind the V0.1
   "picker races the first RCA" finding.

### Still open from V0.1 (re-confirmed, NOT fixed)

- **`renderProbe` TypeError still fires on every page load** — `rca_console.html:2094`,
  `#kbCount` is `null`. Directly probed and reproduced.
- **"Forecast names by adherence band" still shows `0 names · 0%` in 5 of 6 bands.** Root cause
  confirmed as the bucketing rule: names are bucketed by their **worst** week, so all 427 names
  land in `>±25%`. A design defect, not a data problem.
- `favicon.ico` 404 on every load.

### Tester errors (not app defects, recorded for honesty)

- A step clicked `data-tab="architecture"`; the real value is `arch`. Its "PASS" line was bogus
  and was re-run correctly as `verify-tab-architecture-retry`.
- A poll step waited on `#fileInfo`, which does not exist, burning its 123 s budget. This is why
  no trustworthy "UI fully painted" figure exists for this run — use the 12.7 s fetch time.

---

## Canary Version V0.3 — 2026-07-28 · PROVES the RCA actually uses the LLM (branch `wfm-rca`)

**Why this run exists:** V0.2's two investigations both showed `Engine: deterministic-fallback`,
because it selected Groq and Groq's **daily** quota was exhausted. That recording therefore did
NOT demonstrate LLM usage. Selecting Groq was the tester instruction's fault, not the app's.

**Verdict: the RCA demonstrably uses the LLM.** 2 of 3 investigations returned a real LLM engine
line. Recording copied to **`results/canary-v0.3-llm/`** (17.8 MB — video 14.3 MB WebM,
`report.html` 2.0 MB, 18 step screenshots, HAR, console).

### The verbatim Engine footer lines

Investigation 1 — `EC Comm Client Israel EUC Chat` FW202715:
```
Engine: llm · nvidia/nemotron-3-super-120b-a12b · generated 7/28/2026, 11:50:17 PM
```
`forecast_baseline_error`, 78% High. Proof: `fcst_offered` 0.34 vs usual 1.4; `Actual_Offered`
20 vs usual 5.6.

Investigation 2 (retry) — `Social Media Dutch` FW202714:
```
Engine: llm · nvidia/nemotron-3-super-120b-a12b · generated 7/28/2026, 11:56:23 PM
```
`genuine_demand_event`, 85% High primary / 78% overall. Proof: forecast 16.32 vs usual 39.9;
actual 429 vs usual 98.1; Planned ASU 352,523 vs 357,333.
**Money-shot screenshot:** `results/canary-v0.3-llm/screenshots/retry-second-investigation-social-media-dutch-5wenm6.png`
(1920px, Engine line legible).

Investigation 2 attempt A — `Social Media Turkish` FW202525 — **FAILED the objective:**
```
Engine: deterministic-fallback
```
> Selected model 'nvidia/nemotron-3-super-120b-a12b' (nvidia) could not be reached:
> nvidia error: The read operation timed out.

HTTP 200 in **100.1s** — i.e. it died exactly on the old hard-coded 100s ceiling, server-side.
Not a Groq 429, not a UI fault.

### Network evidence

All three calls used the intended URL
`POST /api/rca-investigate?provider=nvidia&model=nvidia%2Fnemotron-3-super-120b-a12b`:

| # | Status | Duration | Engine |
|---|---|---|---|
| 1 | 200 | 44,957 ms | `llm` |
| 2 | 200 | **100,121 ms** | `deterministic-fallback` (timed out) |
| 3 | 200 | 90,238 ms | `llm` |

Zero non-2xx and zero failed requests. `GET /api/data` 14,595 ms; three `/api/queue-context`
842–902 ms; `/api/models` 25 ms. Row count **66,612**, 51,905 scored, 33,003 flagged.

### The fix this run forced, and the honest result

The 100s ceiling lived in `rca_investigate._call_openai_compatible` — the **default** engine,
which is what the UI calls. It now reads `llm.timeout_seconds` from `config.json` (falling back
to 100 when absent), so both engines honour one setting. **This means `rca_investigate.py` is no
longer byte-identical to `shivam-updates`** — a deliberate trade, made because the UI's LLM path
was failing roughly one time in three.

Raising it to 300s was then measured over 3 runs of the default engine + NVIDIA:

| Run | Time | Engine |
|---|---|---|
| 1 | 52.5s | `llm` |
| 2 | **300.7s** | `deterministic-fallback` (hung the whole ceiling) |
| 3 | 43.9s | `llm` |

**300s made things worse, not better** — the success rate stayed 2/3 and the failure simply took
five minutes. NVIDIA occasionally hangs rather than being merely slow, so a bigger ceiling buys
nothing. Settled on **`timeout_seconds: 150`**: it covers the measured 43–100s real completions
with headroom while a hung call fails in 2.5 minutes.

**Still open:** ~1 in 3 NVIDIA calls hangs. A bigger timeout cannot fix that; the real remedy is
a retry, or falling back to a second model when the picked one hangs — but the current design
deliberately refuses to answer a picked model with a different one, to keep per-queue model
comparison honest. That tension needs a product decision.

### Also observed

- **Click interception is intermittent, not unconditional.** Native clicks on `.qitem` and the
  Investigate button were blocked in steps 11/12/14 (fallback to `element.click()`), but in
  step 17 both worked natively. Likely scroll-position / overlay dependent.
- The model dropdown defaults to `Nemotron 3 Super 120B` (NVIDIA) — so the default path is NVIDIA,
  and V0.2's Groq selection was an override.
- `renderProbe` TypeError **still** fires on every page load. Unfixed.
- `favicon.ico` 404 on every load.
- Viewport note: at ~930px the report column sits off-screen right, so investigation 1's
  screenshot shows the filter column rather than the report. The retry step used 1920px and is
  the usable evidence image.
