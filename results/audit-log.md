# Audit log — WFM RCA engine validation run

**Run date:** 2026-07-28 · **16:57:06 → 17:00:18 UTC** (3 min 11 s)
**Branch:** `wfm-rca` · **Result: 40 / 40 checks passed across 5 cases**

Everything in this folder was produced by one command:

```bash
cd backend && python ../results/run_validation.py
```

The script is `results/run_validation.py` — committed alongside the output so the run is
reproducible rather than described. Console transcript: `results/audit-console-output.txt`.
Machine-readable results: `results/validation-report.json`.

---

## 1. Environment as it stood at run time

| Item | Value |
|---|---|
| Backend | `http://localhost:8000`, uvicorn, restarted immediately before the run (PID 36404) |
| `/api/health` | `{"status":"ok","configured":true,"table":"dbo.Input_To_ML"}` |
| SQL Server | `10.10.9.75` → `Playground.dbo.Input_To_ML` (66,612 rows × 33 columns) |
| VPN | connected; `10.10.9.75:1433` TCP open, confirmed before starting |
| Engine | `POST /api/rca-investigate?mode=wfm` → `backend/wfm/` package |
| Model | `groq / llama-3.3-70b-versatile` |
| Band | ±10 % |
| Code state | `rca_investigate.py` and `rca_console.html` unmodified (empty diffstat vs `shivam-updates`) |

## 2. How queues were chosen — deliberately, not randomly

Random sampling was explicitly ruled out. Each case targets **one engine decision path** and
is selected by an explicit SQL predicate, so the set is reproducible and covers the branches
instead of sampling arbitrarily. The predicates are in `select_cases()` in the script.

| Case | Selection predicate | What it must prove |
|---|---|---|
| **A** | `Forecast_name='NA Core Spanish' AND Fiscal_Week=202719` — the known isolated extreme (8,805 vs ~117 typical; the only queue in the table with a week >50× its own median) | must rank `data_quality_issue` first instead of inventing a business cause |
| **B** | both `Planned_ASU` and `Actual_ASU` non-null/non-zero, `fcst_offered>50`, miss >30 % | the exact ASU driver decomposition must be available **and reconcile** |
| **C** | joined against a Country-level rollup that also breaches ±15 % that week | must report the miss as **inherited from a higher level**, not conclude at the queue |
| **D** | locality carrying **≥4 distinct channels**, miss >20 % | channel-migration detection must have real sibling data to evaluate |
| **E** | `fcst_offered>100` and miss **<5 %** — inside the band | **CONTROL:** the engine must *refuse* to investigate |

## 3. Exact steps performed per case

1. `GET /api/queue-context?forecast_name=…&fiscal_week=…&region=…&subregion=…&country=…&channel=…&history_cap=13&peers_cap=15`
   — the same endpoint the console calls.
2. Build the context bundle **exactly as `rca_console.html` does** — `rcaEntry` /
   `rcaComputedBlock` / `buildStatSummary` are mirrored in the script (`build_bundle`), so the
   payload is what the UI would send, not a hand-made shortcut.
3. `POST /api/rca-investigate?mode=wfm&provider=groq&model=llama-3.3-70b-versatile`.
4. Save the untouched response to `results/case-<X>-response.json`.
5. Run checks V1–V8, **re-deriving every number from SQL with fresh independent queries** —
   never by re-reading the engine's own output.
6. 40 s pacing between cases (Groq per-minute cap).

## 4. The eight checks

| ID | Check | Method |
|---|---|---|
| **V1** | KPI correctness | recompute `(1 − Actual_Offered / fcst_offered) × 100` from the raw row; require agreement within 0.05 |
| **V2** | Decomposition identity | `warranty_base_effect + contacts_per_unit_effect == total_miss` |
| **V3** | Ladder correctness | re-aggregate `SUM(Actual)/SUM(Forecast)` at **all 5 levels** with independent `GROUP BY` queries |
| **V4** | Data-quality baseline | `typical_week_actual` must equal the median of the queue's own history from SQL |
| **V5** | Temporal correctness | `last_13_week_avg_actual` must equal `AVG` of the prior 13 weeks from SQL |
| **V6** | Skeptic soundness | every **shipped** `cause_type` must satisfy its own precondition in `skeptic.PRECONDITIONS` |
| **V7** | Back-compatibility | all 11 legacy response keys present, so the existing UI renders it |
| **V8** | Language rule | no banned statistics vocabulary (z-score, correlation, outlier, MAPE, …) in business-facing text |

## 5. Results

| Case | Queue / week | Adherence | Engine | Ranked causes | Checks |
|---|---|---|---|---|---|
| A | NA Core Spanish FW202719 | −9599.7 % | `wfm-deterministic-fallback` | `data_quality_issue` 60 % **(first)**, `inherited_from_higher_level` 65 %, `genuine_demand_event` 60 % | 8/8 |
| B | ANZ Comm Client DSP Upsell FW202652 | 38.5 % | `wfm-deterministic-fallback` | `inherited_from_higher_level` 65 %, `systematic_forecast_bias` 50 % | 8/8 |
| C | ANZ Client Core FW202722 | 66.1 % | `wfm-deterministic-fallback` | `inherited_from_higher_level` 65 %, `genuine_demand_event` 60 % | 8/8 |
| D | Brazil Client Core FW202722 | 75.3 % | **`wfm-llm`** | `inherited_from_higher_level` 90 %, `systematic_forecast_bias` 70 % | 8/8 |
| E | ANZ Comm Client ProSupport Chat FW202722 | −0.0 % | **`wfm-not-investigated`** | none — correct | 8/8 |

Timing: `/api/queue-context` 2.19–2.34 s; investigation 2.35–2.62 s deterministic, **5.69 s**
for the full LLM path. Total wall clock 3 min 11 s including pacing.

### Each case proved what it was selected to prove

- **A** — ranked `data_quality_issue` **first** on the 8,805 outlier, as a *Hypothesis – To be
  Validated*, rather than explaining a probably-corrupt number as a business event. This is the
  case the original engine got wrong (it published `systematic_forecast_bias`).
- **B** — decomposition available and **reconciled exactly** (V2 pass).
- **C** — reported the miss as inherited from **Business Org** level. Selected on a *Country*-level
  breach, and the engine attributed it even higher, which is the correct behaviour: the ladder
  returns the **highest** level breaching in the same direction.
- **D** — full LLM path, and the only case where the model itself ran. It independently reached
  the same top cause as the deterministic path (`inherited_from_higher_level`) at higher
  confidence (90 % vs 65 %).
- **E** — control held: `wfm-not-investigated`, zero causes, at −0.0 % adherence.

**Skeptic rejected a proposed cause in Case B** — recorded in `skeptic_review` with the reason.

## 6. Two defects found and fixed during this run

The first pass scored **36/40**. Both failure classes were diagnosed to root cause rather than
re-run until green.

### 6a. Real engine bug — `secondary_contributors` missing (check V7, Case E)

`back_compat()` only set `secondary_contributors` inside `if ranked:`. The within-band response
has **no** ranked causes, so the key was absent entirely and the existing UI would read
`undefined`.

Fixed in `wfm/business_report_generator.py` — the key is now defaulted outside that guard:

```python
# Must be set even when there are NO ranked causes (the within-band response), otherwise
# the existing UI reads an undefined key. Caught by results/run_validation.py check V7.
result.setdefault("secondary_contributors", [])
```

**A real bug the validation caught, in a path only the control case exercises.**

### 6b. Harness bug — median window off by one week (check V4, Cases C/D/E)

V4 failed by 0.5–1.0 (expected 351.5 got 351.0; 234.0 vs 233.0; 446.5 vs 446.0). The engine
fetches `TOP 104` rows with `Fiscal_Week <= target` (the target is one of the 104) and *then*
drops the target, leaving 103. My check excluded the target **before** taking 104, pulling in
one extra older week and shifting the median.

**The engine was right; the test was wrong.** Fixed in the script, with the reasoning recorded
in a comment so it is not silently reintroduced. Worth stating plainly: three of the four
initial failures were my harness, and only investigating each one told me which was which.

## 7. Honest limitations of this run

- **4 of 5 cases ran on `wfm-deterministic-fallback`, not the LLM path.** The recorded reason is
  in each response's `missing_information`:

  > `groq/llama-3.3-70b-versatile HTTP 429: Rate limit reached … on tokens per day (TPD): Limit 100000, Used 94709`

  This is Groq's **daily** quota, exhausted by the day's development and testing — **not** the
  per-minute cap, so the 40 s pacing could not help. Only Case D had headroom.
  **Consequence:** the *deterministic* path is thoroughly validated (it produced correct,
  fully-reconciled, correctly-ranked reports in 4 cases); the *LLM* path is validated on one
  case here plus earlier runs. Re-run after the daily quota resets, or on a paid tier, for full
  LLM coverage.
- **The LLM path was not exercised through the browser.** The console has no WFM toggle yet, so
  the UI still calls the default engine. Browser coverage of the default engine is
  `IMP_DOCS/canary-test-log.md` (Canary V0.1).
- **V6 proves internal consistency, not truth.** It confirms no cause ships whose precondition
  is unmet — it does not prove the top-ranked cause is the true business cause. That needs a
  labelled set, still open in `IMP_DOCS/TODO.md` (P1b).
- **Channel migration was evaluated but not observed.** Case D had 4+ channel siblings and
  `migration_detected: false`, correctly, because the movements did not cancel out. No case in
  this run contained a genuine migration, so that branch's *positive* path is unproven here.
- A transient `HTTP 502` on the first attempt (VPN still settling) aborted an earlier run. The
  script now retries with backoff and continues past a failed case instead of crashing.

## 8. Files in this folder

| File | Contents |
|---|---|
| `run_validation.py` | the entire run — selection, bundle construction, calls, all 8 checks |
| `audit-console-output.txt` | full console transcript of the passing run |
| `validation-report.json` | machine-readable: per-case results, timings, every check |
| `case-A..E-response.json` | untouched engine responses, including `derived_features` |
| `_server_stdout.log` / `_server_stderr.log` | backend request log for the run |

## 9. Reproducing

```bash
# 1. VPN connected (10.10.9.75:1433 must be reachable)
# 2. start the backend
cd backend && python -m uvicorn sql_backend:app --host 0.0.0.0 --port 8000
# 3. in another shell
cd backend && python ../results/run_validation.py
```

Case selection is predicate-driven, so the same queues are chosen on every run against the same
data. Expect `wfm-llm` on all five once Groq's daily quota has reset.

---

# Addendum — 2026-07-28 · LLM ranking verification + Canary V0.2

Two follow-up runs after the §1–9 validation above.

## 10. LLM ranking verification — "it should use the LLM"

The §1–9 run proved the *arithmetic*, but 4 of its 5 cases fell back to the deterministic path
because Groq's daily quota was spent. This run proves the **model** ran and inspects what it
ranked.

**Command:** `cd backend && python ../results/run_llm_ranking.py`
**Result: LLM answered on 3/3 queues · 27/27 ranking checks passed.**

### What had to change first

`rca_investigate._call_openai_compatible` hard-codes `timeout=100`. Rather than edit that file —
it is deliberately kept byte-identical to `shivam-updates` so the original engine cannot regress
— the WFM engine got its own transport, `backend/wfm/llm_client.py`, with the timeout read from
config:

```json
"llm": { "timeout_seconds": 300, ... }
```

It preserves both hard-won behaviours of the original transport: the browser-like User-Agent
(Groq's Cloudflare 403s the default urllib UA with `error code: 1010`) and the retry without
`response_format` (some NVIDIA models 400/503 on it).

### Provider reality

| Provider | Time per investigation | Constraint |
|---|---|---|
| Groq `llama-3.3-70b-versatile` | 2.4–5.7 s | **100,000 tokens/DAY** — exhausted by the day's testing (`Used 98586`). Per-minute pacing cannot help. |
| NVIDIA `nemotron-3-super-120b-a12b` | **53–68 s** | the working option once Groq is spent |

### Checks (L1–L9)

`engine == wfm-llm` (**a deterministic fallback FAILS this run**, it is not quietly accepted) ·
ranks sequential · confidence descends with rank · `confidence_level` matches its band · every
shipped `cause_type` satisfies its precondition · when the ladder reports `inherited_from`, the
model actually ranked `inherited_from_higher_level` · when `data_quality.suspect`, the model
ranked `data_quality_issue` **first** · no banned statistics vocabulary · every cause carries an
action and a status.

### Results

| Queue / week | Adherence | Time | Causes | Rank 1 |
|---|---|---|---|---|
| NA Core Spanish FW202719 | −9599.7 % | 59.2 s | **5** | `data_quality_issue` 92 % High |
| ANZ Comm Client DSP Upsell FW202652 | 38.5 % | 53.4 s | 1 | `inherited_from_higher_level` 90 % High |
| ANZ Client Core Email FW202722 | 16.3 % | 67.9 s | 3 | `inherited_from_higher_level` 90 % High |

**The most telling result:** on `NA Core Spanish` FW202719 the model produced five ranked causes,
put `data_quality_issue` first at 92 %, and ranked `genuine_demand_event` **last, at 12 %**,
titled *"Unlikely genuine demand surge"*. That is the exact cause the ORIGINAL engine concluded
for this queue (recorded in `prompt-trail.md` Session 15). The engine now actively deprioritises
it and tells the reader to validate the figure at source instead.

### A diagnostic bug found and fixed mid-run

Two queues first came back as `wfm-deterministic-fallback` with an opaque reason: *"produced no
cause the data supports"*. Replaying the same queue directly showed the skeptic **retaining**
both proposals — so this was not over-rejection but model run-to-run variance in which cause
types it chose. The message now records what was proposed, each rejection reason, and which cause
types the data actually supports. Re-running then gave 3/3.

**Honest note on causality:** NVIDIA completed these runs in 53–68 s, which is *inside* the old
100 s ceiling — so the raised timeout is **not** what unblocked them. What varied was the model's
choice of cause types. The raised timeout remains correct insurance (an earlier NVIDIA call on the
default engine did exceed 100 s), but it should not be credited with this result.

## 11. Canary V0.2 — end-to-end browser recording

25 recorded steps with video, trace, HAR and console. Recording copied to
`results/canary-v0.2/` (~25 MB, almost all video). Full write-up in
`IMP_DOCS/canary-test-log.md`.

Core flow passed: load → SQL connect → fetch → 250 flagged cards → model picker (5 options,
Groq routed correctly) → **two complete RCA reports** with Proof panels of real numbers and every
collapsed `<details>` verified non-empty → all 8 tabs. Row count `66,612`, matching SQL exactly.
Zero failed network requests; all 11 `/api/*` calls returned 200.

Both browser RCAs showed `Engine: deterministic-fallback` — correct, with the Groq daily-quota
429 visible in MISSING INFORMATION. LLM coverage came from §10 instead.

**3 new bugs**, worst first:

1. **Flagged-queue cards may not be clickable by a real pointer.** A native click on `#q0` was
   blocked for 30 s — the `#filters` search input and a `.nav` anchor intercept pointer events
   over the queue list. The test only proceeded via `element.click()`.
2. **Changing the AI model re-runs the PREVIOUS queue and overwrites the panel** — stale
   `window._rcaCurrent` after `selectFlag()`. Observed live: header showed one queue while the
   panel rendered another, from a real server call for the wrong queue.
3. **The model picker only exists after a card is selected** (it lives inside
   `#investigationPanel`) — the mechanism behind the V0.1 picker-race finding.

Re-confirmed **still unfixed** from V0.1: the `renderProbe` TypeError on every page load
(`rca_console.html:2094`), and the adherence-band chart reading `0 names · 0 %` in 5 of 6 bands.

## 12. Overall status after the addendum

| Run | Result |
|---|---|
| SQL cross-checks (5 queues, 8 checks each) | **40/40** |
| LLM ranking (3 queues, 9 checks each) | **27/27**, LLM answered 3/3 |
| Canary V0.2 browser session | core flow PASS; 3 new UI bugs, 3 re-confirmed |
| `rca_investigate.py` / `rca_console.html` | untouched (empty diffstat vs `shivam-updates`) |

Still unproven, unchanged: **ranking correctness**. The checks confirm no cause ships whose
supporting feature is absent and that the ranking is internally consistent with the evidence —
not that rank 1 is the true business cause. That needs a labelled set (`IMP_DOCS/TODO.md`, P1b).
