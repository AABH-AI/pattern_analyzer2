# results/

Validation evidence for the WFM RCA engine (`POST /api/rca-investigate?mode=wfm`).

**Latest: 2026-07-28**
- **40/40** SQL cross-checks across 5 deliberately-selected queues (`validation-report.json`)
- **3/3 queues answered by the LLM**, **27/27** ranking checks (`llm-ranking-report.json`)
- **Canary V0.2** end-to-end browser session with video (`canary-v0.2/`)
- **Canary V0.3** — the run that **proves the UI's RCA uses the LLM** (`canary-v0.3-llm/`)

Start with **[`audit-log.md`](audit-log.md)** — the full workflow: environment, how each queue
was chosen and why, the exact steps, all eight checks, results, the two defects found and
fixed mid-run, and the honest limitations.

| File | What it is |
|---|---|
| [`audit-log.md`](audit-log.md) | **read this first** — the complete audit trail |
| `run_validation.py` | the script that produced everything here; re-runnable |
| `audit-console-output.txt` | full console transcript of the passing run |
| `validation-report.json` | machine-readable results, timings, every check |
| `case-A-response.json` | NA Core Spanish FW202719 — the data-quality outlier case |
| `case-B-response.json` | ANZ Comm Client DSP Upsell FW202652 — ASU decomposition case |
| `case-C-response.json` | ANZ Client Core FW202722 — inherited-miss case |
| `case-D-response.json` | Brazil Client Core FW202722 — multi-channel case (full LLM path) |
| `case-E-response.json` | ANZ Comm Client ProSupport Chat FW202722 — in-band control |
| `_server_stdout.log`, `_server_stderr.log` | backend request log for the run |

### LLM ranking verification — the engine must actually use the LLM

| File | What it is |
|---|---|
| `run_llm_ranking.py` | the script; asserts `engine == wfm-llm` (a deterministic fallback FAILS the run) |
| `llm-ranking-report.json` | 3/3 LLM-answered, 27/27 checks, per-queue rankings |
| `llm-ranking-console-output.txt` | console transcript |
| `llm-NA_Core_Spanish-FW202719.json` | raw LLM response — 5 ranked causes |
| `llm-ANZ_Comm_Client_DSP_Upsell-FW202652.json` | raw LLM response |
| `llm-ANZ_Client_Core_Email-FW202722.json` | raw LLM response |

Provider NVIDIA `nemotron-3-super-120b-a12b`, 53–68 s per investigation. Groq was unusable —
its **daily** 100,000-token quota was exhausted by the day's testing, so per-minute pacing could
not help. Checks L1–L9 cover: the model really answered, ranks sequential, confidence descending,
confidence band correct, every shipped `cause_type` satisfies its precondition, the ladder's
`inherited_from` is actually ranked, `data_quality.suspect` forces `data_quality_issue` first, no
banned statistics vocabulary, and every cause carries an action and a status.

Notable: on `NA Core Spanish` FW202719 the model returned 5 ranked causes, put
`data_quality_issue` **first at 92 %**, and ranked `genuine_demand_event` **last at 12 %**
("Unlikely genuine demand surge") — actively deprioritising the very cause the *original* engine
had concluded for that queue.

### Canary V0.2 — browser recording

| Path | What it is |
|---|---|
| `canary-v0.2/report.html` | self-contained session report (3.7 MB) — open in a browser |
| `canary-v0.2/video/*.webm` | **screen recording, 17.7 MB**, one clip for the whole session |
| `canary-v0.2/screenshots/` | 25 PNGs, one per recorded step |
| `canary-v0.2/network.har` | every request/response |
| `canary-v0.2/console.log` | browser console output |

Canary records **one video per browser page for the whole session**, not one clip per step —
per-step evidence is the screenshots, each bound to its step in the report. `trace.zip` (7.1 MB)
was left in the session dir; view with `npx playwright show-trace`.

**Format is WebM (VP8), not MP4.** Play it in Chrome/Edge — both play WebM natively — or in VLC.
There is no MP4 in this folder. Playwright's bundled ffmpeg
(`%LOCALAPPDATA%\ms-playwrightfmpeg-1011fmpeg-win64.exe`) **cannot** convert it: that build
ships only the PNG and VP8 encoders and no MP4/MOV muxer — it exists purely to write Playwright's
WebM capture. To get an MP4, install a full ffmpeg first:

```powershell
winget install --id Gyan.FFmpeg -e
ffmpeg -i results/canary-v0.2/video/*.webm -c:v libx264 -preset fast -crf 26        -pix_fmt yuv420p -movflags +faststart results/canary-v0.2/video/canary-v0.2.mp4
```

**Folder is ~25 MB, almost all video** — worth deciding whether that belongs in git before
committing.

Canary V0.2 found 3 new bugs (worst: flagged-queue cards may not be clickable by a real pointer)
and re-confirmed 3 unfixed from V0.1. Full write-up: `IMP_DOCS/canary-test-log.md`; tracked as
P1c / P1d in `IMP_DOCS/TODO.md`.

**Caveat on V0.2:** both of its investigations show `Engine: deterministic-fallback`, because it
selected Groq and Groq's daily quota was spent. **V0.2 does not demonstrate LLM usage** — see
V0.3 below for that.

### Canary V0.3 — proves the UI's RCA actually uses the LLM

| Path | What it is |
|---|---|
| `canary-v0.3-llm/report.html` | session report (2.0 MB) |
| `canary-v0.3-llm/video/*.webm` | screen recording, **14.3 MB** (WebM, not MP4) |
| `canary-v0.3-llm/screenshots/retry-second-investigation-social-media-dutch-5wenm6.png` | **the money shot** — 1920px, Engine footer legible |
| `canary-v0.3-llm/network.har`, `console.log` | network + console |

Two of three investigations returned, verbatim from the UI footer:

```
Engine: llm · nvidia/nemotron-3-super-120b-a12b
```

`EC Comm Client Israel EUC Chat` FW202715 → `forecast_baseline_error` 78% High (45.0s), and
`Social Media Dutch` FW202714 → `genuine_demand_event` 85% High (90.2s). The third
(`Social Media Turkish`) died at **exactly 100,121 ms** on the old hard-coded 100s ceiling and
fell back — which is what prompted making the timeout configurable in the default engine too.

Use **NVIDIA, not Groq**, for any browser demo: Groq's 100,000-token daily cap is easily spent,
after which every call 429s and the engine (correctly) degrades.

## Run it

```bash
# VPN connected (10.10.9.75:1433 reachable), backend running on :8000
cd backend && python ../results/run_validation.py
```

## What is actually proven

Every number the engine reported was **re-derived from SQL with independent queries** — the KPI,
all five investigation-ladder levels, the data-quality baseline, the 13-week average — and the
ASU driver decomposition was confirmed to reconcile exactly. The in-band control confirmed the
engine refuses to investigate inside ±10%.

## What is not proven

Ranking **correctness**. The checks confirm no cause ships whose supporting feature is absent;
they do not establish that the top-ranked cause is the true business cause. That needs a
labelled set of past misses — still open in `IMP_DOCS/TODO.md` (P1b).

Also: 4 of the 5 cases fell back to the deterministic path because Groq's **daily** token quota
was exhausted by the day's testing. The deterministic path is therefore well covered; the LLM
path is covered by one case here plus earlier runs. See §7 of the audit log.

## Related

- `IMP_DOCS/wfm-rca-engine.md` — engine contract, module map, known gaps
- `IMP_DOCS/canary-test-log.md` — browser QA sessions (Canary V0.1)
- `IMP_DOCS/TODO.md` — P1b (WFM follow-ups), P1c (UI defects found by Canary)
