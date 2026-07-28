# pattern_analyzer2

**Demand Pattern RCA Agent — Console.** A single-file, dependency-free web app that ingests the weekly demand file (`.xlsx`/`.csv`) in the browser and produces rule-based Root-Cause Analysis on two metrics — **Forecast Accuracy** and **Forecast Adherence** — keyed on `Forecast_name × Fiscal_Week`.

## Contents
| File | Purpose |
|---|---|
| `rca_console.html` | The app. Tabs: **RCA Console**, **Dashboard** (volumetrics + graphs), **Timeline** (deadline Gantt), Architecture, Tech Stack, AI Models, Data & Files, Definitions. |
| `rca_timeline.html` | Standalone build Gantt to 30 Jul (theme-aware). |
| `index.html` | GitHub Pages entry — redirects to the console. |
| `backend/` | FastAPI + pyODBC connector for live SQL, plus the two RCA engines (`rca_investigate.py` and the `wfm/` package). |
| `run.bat` | **Windows one-shot runner** — deps, config, VPN, SQL check, backend, optional test suites, browser. |
| `run.ps1` / `run.sh` | Same idea for PowerShell / POSIX. |
| `results/` | Validation evidence: audit log, re-runnable test scripts, raw engine responses, Canary browser sessions. |
| `IMP_DOCS/` | Prompt trail, design choices, handoff, TODO, WFM engine contract, Canary test log. |

## Live site
GitHub Pages: **https://aabh-ai.github.io/pattern_analyzer2/**

## Run locally

**No install, no SQL** — open `rca_console.html` in any modern browser → *Upload weekly file* →
filter / inspect flagged queues. No build step, no libraries, no data egress.

**With live SQL** (needs the VPN, the ODBC Driver 17/18 and `backend/config.json`):

```bat
run.bat                 :: setup + VPN + backend + open the console
run.bat --all           :: ...and run all three test suites
run.bat --smoke         :: per-module smoke test only (12 modules, no SQL needed)
```

PowerShell / POSIX equivalents: `run.ps1`, `run.sh`. Docker: see `DEPLOY.md`.

## Root-cause engines

Two engines sit behind `POST /api/rca-investigate`:

- **default** (no parameter) — the original single-call investigation.
- **`?mode=wfm`** — the WFM cross-functional engine: top-5 ranked causes, skeptic review that
  *rejects* causes the data cannot support, hypothesis marking, an investigation ladder
  (Business Org → Region → … so a queue-level cause is never reported before checking whether
  the miss is inherited), 104-week temporal context, channel-migration detection, and the
  ±10% "don't investigate in-band" rule. It backfills the legacy response keys, so the current
  UI renders it unchanged. Contract: `IMP_DOCS/wfm-rca-engine.md`.

## Key notes
- Only two metrics are computed; every number has an ⓘ showing the exact formula and inputs.
- **Avg accuracy = 100 − MAPE** (a plain mean of Actual÷Fcst cancels over/under-forecasts and overstates accuracy).
- Display of `forecast offered (Simple)` is rounded to 2 dp — the calculation uses full precision.

## Evidence

`results/` holds the audit trail — start with `results/audit-log.md`. Latest run: 40/40 SQL
cross-checks over 5 deliberately-selected queues, 3/3 queues answered by the LLM with 27/27
ranking checks, and 12/12 per-module smoke tests. Every number the engine reports was
re-derived from SQL independently.

See `IMP_DOCS/handoff.md` to continue development, and `IMP_DOCS/TODO.md` for what is still open
— most importantly that ranking **correctness** is still unmeasured (it needs a labelled set).
