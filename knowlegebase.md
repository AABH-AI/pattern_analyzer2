# Knowledge Base — Demand Pattern RCA Agent

Everything known about this product, basic to advanced: what it is, how it's built, how the
investigation engine reasons, the data model, the UI, the branch topology, and the engineering
techniques used to build and harden it. Written as a single reference so a new reader (human or
AI) can get oriented from zero and also find the deep internals when they need them.

This file lives at the repo root next to `README.md`. It is a synthesis — the authoritative,
blow-by-blow history of *why* each decision was made lives in `IMP_DOCS/prompt-trail.md`; the
open items live in `IMP_DOCS/TODO.md`. This file is the "what is true right now, and why it works
this way" reference.

---

## 1. What this product is, in one paragraph

**Demand Pattern RCA Agent** ("RCA Console") is a single-page web tool that ingests a weekly
workforce-management demand file (or connects live to SQL Server), computes exactly two metrics —
**Forecast Accuracy** and **Forecast Adherence** — flags any queue/week that missed its plan by
more than a configurable band, and then runs an LLM-backed root-cause investigation on any flagged
queue. The investigation is built so that **all arithmetic is done in Python and the LLM only
narrates** — the model is never allowed to invent a number, only explain one that was already
computed deterministically. The tool is aimed at WFM (workforce management) planners and,
increasingly, at executives who want to see *why* a forecast missed without reading a spreadsheet.

## 2. The business problem

A workforce-management team forecasts contact-center demand (`Actual_Offered` vs `fcst_offered`)
per queue per week. When a forecast misses badly, someone has to explain why — was it a genuine
demand spike, a forecasting error, a holiday effect, or did volume just move to a different
channel/offering without the total actually changing? Answering that by hand means pulling the
queue's history, its siblings, and the wider region/country pattern, then reasoning about which
explanation the evidence actually supports. This tool automates that reasoning while keeping every
number traceable back to the source file.

## 3. The two metrics — the only arithmetic that matters

```
Forecast Accuracy   = (Actual_Offered / fcst_offered) * 100
Forecast Adherence  = (1 - Actual_Offered / fcst_offered) * 100
```

- **Forecast Adherence is signed.** Negative = actual ran **above** forecast (under-forecast).
  Positive = actual ran **below** forecast (over-forecast). This is the one sign convention used
  everywhere in the app — console, WFM engine, SQL verification scripts, all agree.
- **Avg Accuracy is 100 − MAPE** (mean absolute % error), not a plain mean of Actual÷Forecast — a
  plain mean lets over- and under-forecasts cancel out and silently overstates accuracy (this was
  a real bug fixed early in the project's history: it read ~99% when the true figure was ~77%).
- **A row flags** when `|Forecast Adherence| > band%` (default band = **10%**).
- Rows with no/zero `fcst_offered` are skipped entirely — "can't compute," never treated as 0%.

## 4. Data model

- **Grain:** one row per `Forecast_name × Fiscal_Week`.
- **Fiscal_Week** format: `YYYYWW` (e.g. `202719`). Week starts Saturday, Friday is the last
  working day; fiscal year starts the 1st week of February.
- **Key dimensions:** `Region`, `SubRegion`, `Country`, `Forecast_name`, `Forecaster`, `Offering`
  (Basic/Pro/OOP/Premium), `Projection_plan_name`, `channel` (Voice/Chat/Email/Case/Social Media),
  `business_org` — constant (`CSG` only, confirmed against live data) across the entire table, so
  it is never a meaningful drill-down level on its own.
- **Core numeric fields:** `Actual_Offered`, `Actual_Handled`, `fcst_offered`, `fcst_handled`,
  `Planned_ASU`, `Actual_ASU` (ASU = the driver behind contact volume — `contacts = ASU ×
  contacts-per-unit`; exact acronym expansion still unconfirmed, tracked as an open question),
  `Final_Units` / `Final_Y1`–`Final_Y5` (installed units under warranty year 1–5 — a demand
  driver, **not** prior-year actuals), `Holiday_Count`, `Monday`–`Sunday` day flags.
- **Live SQL table:** `dbo.Input_To_ML_Full` on server `10.10.9.75`, database `Playground` —
  88,816 rows, loaded specifically because it has real Channel and Offering diversity (an earlier
  table, `dbo.Input_To_ML_P1`, had only Voice and no variation, which made channel/offering-level
  drill-down untestable). Older tables (`dbo.Input_To_ML`, `dbo.Input_To_ML_P1`) are left in place,
  not deleted, in case the config needs to point back at them.
- **CQN mapping tables:** `dbo.CQN_Mapping` (532 rows) and `dbo.CQN_Forecast_Pair` (522 rows) —
  see §8, the Combined Queue Name.

## 5. Application architecture

- **Frontend:** `rca_console.html` — one self-contained file (HTML+CSS+JS, no build step, no
  external libraries, no CDN dependency). Everything — filters, charts (hand-rolled SVG), the
  investigation report renderer, the design system — lives in this one file.
- **Backend:** FastAPI (`backend/sql_backend.py`), pyODBC to SQL Server. Key endpoints:
  - `GET /api/health` — reports whether SQL is configured and which table is active.
  - `GET /api/data` — `SELECT * FROM <table>`, powers file-free "Connect to SQL Server" ingestion.
  - `GET /api/queue-context` — scoped fetch of one queue's own row + prior-week history + CQN
    peers, so the console never has to pull the whole table to investigate one queue.
  - `GET /api/models` — the LLM provider/model picker catalog.
  - `GET /api/cqn-mapping` — serves the authoritative Combined Queue mapping to the client.
  - `POST /api/rca-investigate[?mode=wfm]` — the investigation endpoint (§6).
- **Config:** `backend/config.json` (gitignored — never committed; `config.example.json` is the
  documented, secret-free template). Holds SQL connection details and the three LLM provider slots
  (`primary`/`secondary`/`tertiary`) plus the `selectable_models` catalog the UI's model picker
  reads from.
- **Loaders:** `backend/upload_excel_to_sql.py` (weekly demand file → SQL, with `--dry-run` and a
  destructive `DROP TABLE IF EXISTS` unless a new `--table` name is given) and
  `backend/upload_cqn_mapping.py` (the CQN workbook → the two mapping tables, plus `--coverage` /
  `--verify-sheets` checks).
- **Runner:** `run.py` at the repo root — one command that frees port 8010, installs deps, waits
  for `/api/health`, and opens the browser.

## 6. Two RCA engines behind one endpoint

`POST /api/rca-investigate` has always supported a `?mode=` switch, and the two modes are fully
independent code paths sharing one response contract:

| Mode | Engine | Prompt style |
|---|---|---|
| *(none)* / `legacy` | `backend/rca_investigate.py` | generic, schema-driven, works on any CSV shape |
| `wfm` | `backend/wfm/` package | a full business-authored investigation specification (see §7) |

Both return the same `InvestigationResponse` shape (see `IMP_DOCS/rca-investigation-contract.md`
for the exact JSON), so the UI renders either without modification. `?mode=wfm` is what the
console actually uses today.

### The generic ContextBundle (both engines consume this)

The frontend builds one shape regardless of source file: `target` (the row being explained, full
raw fields + computed `forecast/actual/error/adherence_pct/direction/severity`), `history` (prior
weeks, **key+computed only, no raw fields** — this was deliberately slimmed after a real Groq `413
tokens-per-minute` failure caused by sending full raw rows 12+15 times), `peers` (same week, same
locality, different `Forecast_name`, same slimming), and `statistical_summary` (per-field mean/
stdev/z-score/outlier/trend for numeric fields, changed/distinct-values for categorical — computed
generically over **whatever columns exist**, nothing hand-picked by name).

`null`/empty in the response means "not determined," never "determined to be nothing" —
`primary_root_cause: null` plus a `missing_information` entry is the honest placeholder, never a
fabricated conclusion.

## 7. The WFM engine, module by module

Package: `backend/wfm/`. Selected via `?mode=wfm`. Pipeline, mirroring the prompt's own rules:

```
derive features (all deterministic)
  -> threshold gate            never investigate inside the ±band
  -> ONE model call            rank + explain + challenge, in business language
  -> skeptic.review            reject causes the features cannot support
  -> hypothesis_generator.mark downgrade over-confident statuses
  -> business_report_generator recompute the KPI, build the report, back-fill legacy keys
  -> interrogation             a second pass that asks WHY of the finished report
```

| Module | Responsibility |
|---|---|
| `investigation_engine.py` | orchestrates the whole workflow |
| `data_access.py` | the SQL fetches — history, channel-sibling rows, the ladder |
| `hierarchy_analyzer.py` | the drill-down ladder computation |
| `channel_migration_detector.py` | Voice↔Chat↔Email (or Offering↔Offering) shifts within one locality — generalized to take any `group_field`, not hardcoded to channel |
| `temporal_reasoner.py` | 104 weeks of history, prior week/4/13, same week last year |
| `correlation_engine.py` | driver relationships (Spearman rank correlation) + the exact ASU decomposition |
| `hypothesis_generator.py` | marks causes "Hypothesis – To be Validated" vs "Verified"; also the fully-deterministic no-model fallback ranked list |
| `skeptic.py` | **rejects** causes the features cannot support — see below |
| `business_report_generator.py` | builds the executive report, back-fills legacy response keys |
| `data_quality.py` | is the number itself credible, before explaining it? |
| `evidence_pack.py` | arithmetic over history the engine could always have done: miss-streak length, whether the plan was reissued mid-streak, same-week-last-year, whether holidays actually move this queue |
| `interrogation.py` / `why_prompt.py` | a second LLM call that asks WHY of the bullets *actually produced*, answered only from the evidence bundle (never from memory) — currently built and returned by the API, but its UI card is commented out pending question-quality work |
| `prompts.py` | the business-authored investigation prompt |
| `llm_client.py` | LLM transport with a configurable timeout (`llm.timeout_seconds`, default 150s) |
| `common.py` | shared primitives: `CAUSE_TYPES`, `adherence_pct`, `confidence_level`, etc. |

### The investigation ladder (drill-down)

`_LADDER_LEVELS` in `data_access.py`:

```
Business Org -> Region -> SubRegion -> Country -> Offering -> Channel
```

Each level recomputes `SUM(Actual_Offered)`/`SUM(fcst_offered)`/adherence for that wider scope, at
the *same week*, so the report can say "the miss is already visible at Country level, so it isn't
specific to this queue" (`inherited_from`) instead of just asserting it. Business Org is still
computed (it's free — narrowing every query below costs nothing) but filtered out of the rendered
Scope card, since it's a constant and would just repeat the whole-book total under a misleading
label. Offering was added between Country and Channel specifically to see a **Demand Switch** —
volume moving between Offerings/Channels within a locality rather than genuinely changing.

### Channel/Offering migration detection

`channel_migration_detector.analyse(rows, target_week, target_value, group_field=...)` — checks
whether the group's *total* stayed roughly flat while individual members moved in opposite
directions (`offset_share >= 0.6` and net change `< 25%` of prior total). If so, `detected: true`
and the narrative describes customers routing differently rather than demand changing. This
computation is **always done in Python**; the model only narrates the verdict, never decides it.

### `skeptic.py` — the rejection layer

Two grounds:

1. **Feature precondition (hard reject).** Every cause type in `CAUSE_TYPES` has an explicit
   boolean predicate in `PRECONDITIONS`. No trace in the features ⇒ the cause is impossible, not
   merely weak, and is rejected with a stated reason (e.g. a `plan_restatement` claim on a week
   where the plan didn't change is rejected: *"the forecast plan did not change this week, so this
   cause is not possible for this week"*). This was identified as the single highest-value
   accuracy defect in the whole engine — without it, an unsupported verdict shipped unchallenged.
2. **Numeric grounding (prunes evidence, does not reject the cause).** Every cited figure is
   reconciled against the real computed numbers (2% tolerance for display rounding); unreconciled
   figures are dropped with a note, but a cause survives if its remaining evidence still supports
   it — a model may legitimately cite a correctly-derived figure (a gap, a difference) that isn't
   literally in the raw payload.

### `correlation_engine.py` — relationships and exact attribution

Spearman rank correlation (not Pearson — deliberately robust to the single extreme week that
usually *triggers* the investigation) between candidate drivers (`Actual_ASU`, `Planned_ASU`,
`Final_Units`, `Holiday_Count`) and `Actual_Offered`. Retained only if `≥12 weeks` of history and
`|strength| ≥ 0.5` — enforced in code, not just requested in the prompt.

The **ASU driver decomposition** is exact, not a heuristic:

```
planned_rate  = fcst_offered   / Planned_ASU
actual_rate   = Actual_Offered / Actual_ASU
volume_effect = (Actual_ASU - Planned_ASU) * planned_rate
rate_effect   = Actual_ASU * (actual_rate - planned_rate)
volume_effect + rate_effect == Actual_Offered - fcst_offered      (identically)
```

This answers a genuinely causal question — did the miss come from the warranty base being
different than planned, or from contacts-per-unit moving? — instead of picking a label. Verified
exact on all 22,003 flagged misses carrying both ASU columns in the real dataset: 60.7%
rate-driven, 9.8% base-driven, 29.6% mixed. About 45% of scoreable rows are missing `Actual_ASU`
and correctly report `available: false` rather than guessing.

### Cause taxonomy (`common.CAUSE_TYPES`)

```
forecast_baseline_error, systematic_forecast_bias, genuine_demand_event,
volume_routing_shift, plan_restatement, installed_base_change,
calendar_holiday_effect, data_quality_issue, inherited_from_higher_level,
channel_migration
```

An `offering_migration` cause type (parallel to `channel_migration`, using the same detector
generalized with `group_field="Offering"`) was built on the `approved` branch's most recent work
alongside the Offering rung of the ladder — **not yet present on `approved-test`/`UI`**, see §10.

### `investigation_meta.engine` values

| Value | Meaning |
|---|---|
| `wfm-llm` | a full investigation ran |
| `wfm-not-investigated` | inside the ±band — per the business rule, nothing is investigated |
| `wfm-deterministic-fallback` | the model was unreachable; the report is deterministic-checks-only and says so in `missing_information` |

### What's deterministic vs what the model does

Never delegated to the model: the KPI/adherence formula, the investigation ladder and its
`inherited_from` verdict, all temporal comparisons, channel/offering-migration detection, the
data-quality check. The model's job is strictly to **rank, explain in business language, and
challenge** — it cannot change the KPI or the migration verdict; the response coercion layer
overwrites both even if the model tries.

## 8. The Combined Queue Name (CQN) — a subtlety worth knowing well

The console's own working key (`cqnDimsKey` in `rca_console.html`) is `Forecast_name + Region +
SubRegion + Country + Channel` — a **locality key**, not the true Combined Queue. The business
supplied an actual CQN mapping workbook (`CQN and FC mapping.xlsx`, loaded via
`upload_cqn_mapping.py` into `dbo.CQN_Mapping`/`dbo.CQN_Forecast_Pair`) that settled a real
definitional conflict: **35 of 331 Combined Queues span more than one channel** (e.g. one CQN
covers Case + Chat + Email + Voice across 9 Forecast_names). So channel is *not* part of the true
CQN key, and "migration between channels within a CQN" is a real, distinct phenomenon from a
locality-level channel split.

Coverage is 100% and verified three independent ways (every queue name resolves, every row and
every unit of demand sits behind a mapped name, and the mapping's own dimensions agree with the
data on all 427 names) — but it is **not 1:1**: 69 of 442 Forecast_names map to *more than one*
Combined Queue (vendor/site splits, e.g. the same vendor rebranded, or genuinely different queues
sharing a name pattern), carrying 41.7% of all demand. Current behavior takes the **union** of a
name's queues; the general "genuinely different queues needing disambiguation" case (46 of the 69)
is an open business decision, not a code defect.

When the mapping table is loaded, `data_access.py` prefers it (`cqn_source: "mapping"`,
`is_cqn_proxy: false`); when absent, the engine falls back to the locality proxy
(`cqn_source: "proxy"`, `is_cqn_proxy: true`) and is honest about the difference in its narrative.

## 9. LLM providers

Three OpenAI-compatible chat-completions providers behind one shared transport
(`llm_client.py`'s `_post`/`chat_json`; zero transport code changes were needed to add each one —
same request/response shape):

| Provider | Default model | Role |
|---|---|---|
| NVIDIA (`build.nvidia.com`) | `nvidia/nemotron-3-super-120b-a12b` | primary |
| Groq | `llama-3.3-70b-versatile` | secondary/fallback, fast baseline |
| Gemini (Google's OpenAI-compat endpoint) | `gemini-3.6-flash` | tertiary — added later; every "flash"-tier model works on the free tier, every "pro"-tier model 429s (needs billing) |

A specific model picked in the UI is **never** silently answered by a different model on failure —
if it fails, the deterministic fallback finding is returned instead, so per-queue model comparison
stays honest. `nvidia/llama-3.3-nemotron-super-49b-v1.5` is the one NVIDIA model that is actually
name-confirmed as a Llama derivative; the others (`nemotron-3-super-120b-a12b`,
`nemotron-3-ultra-550b-a55b`) are NVIDIA's own Nemotron 3 architecture with no confirmed Llama
lineage — worth being precise about this distinction, since asserting an unconfirmed lineage was a
real mistake caught and corrected during this project (see §12).

Embeddings (for RAG over the currently-hidden Probing/knowledge-base layer): `nomic-embed-text`,
"if required" — not confirmed active, just the intended model when that layer is re-enabled.

## 10. The UI — 7 tabs and the design system

Tabs: **RCA Console** (the main working screen), **Dashboard** (volumetrics/charts), plus five
reference tabs — **Architecture**, **Tech Stack**, **AI Models**, **Data & Files**, **Definitions &
Formulas** — that map the app onto the client's approved enterprise Agentic Platform stack
(LangGraph, MCP tools, Kong gateway, Alation catalog, etc.) so nothing looks built outside the
approved architecture. A "Timeline" tab (an internal build-deadline Gantt chart) existed early on
and was removed entirely once its purpose (an internal dev-progress tracker) was served — not to
be confused with the *investigation* pipeline visualizer, which is a different, still-live feature
inside the RCA Console tab itself.

**Design system** (current, on the `UI` branch): a "Corporate SaaS polish" direction — Stripe/
Linear/Notion-inspired. Design tokens: a refined neutral palette (`--bg:#f7f8fb`,
`--panel:#fff`, `--border:#e4e7ec`) plus one strong indigo accent (`--accent:#4f46e5`), a radius
scale (`--r-sm/md/lg/xl`, 8–20px) and a 3-tier shadow scale (`--sh-sm/md/lg`) that give real depth
instead of flat 1px borders everywhere. Every emoji in the app (~35 instances) was replaced with a
small inline-SVG icon set (`ico(name, size)` in `rca_console.html`, ~24 icons) — emoji render
inconsistently across OS/browser and read as unpolished; single-color stroke icons that inherit
`currentColor` don't. The KPI stat row was moved out of a cramped narrow column into a full-width
4-across row with icon badges (the single highest-leverage layout fix); queue-list cards carry a
severity-colored left accent bar; the Root Cause section gives its primary conclusion a visually
distinct "PRIMARY CONCLUSION" card so a reader's eye lands on the answer first, with supporting
points genuinely secondary (smaller, muted) rather than reading as five competing conclusions.

Theme: light-only by deliberate choice (no dark-mode toggle) — chosen to avoid doubling the
design/testing surface for this round.

## 11. Branch topology — which branch is which

This project has accumulated several branches with real, non-overlapping purposes. Knowing which
is which matters before touching any of them:

| Branch | What it is |
|---|---|
| `main` | a separate, further-ahead lineage (full Statistical Evidence engine); not touched in the sessions covered by this document |
| `approved` | the **pinned, business-approved baseline** — a specific commit (`48e9711`) the business signed off on for its Root Cause quality (causal-clause contract + dynamic multi-factor driver attribution). Later sessions added: the Offering/Business-Org drill-down ladder, Gemini as a third provider, and two Root Cause duplication-bug fixes, all on top of that pinned commit |
| `approved-test` | branched from the **same** commit as `approved` (`ad14000`), but received a *different* set of additions (a colleague's Scope Card / Evidence Pack / Interrogation work) instead of `approved`'s later fixes. The two branches are siblings, not one ahead of the other |
| `UI` | branched from `approved-test`'s tip — the premium visual redesign described in §10. Contains everything `approved-test` has, plus the design system and structural overhaul, but **not** the Offering-drill-down/Gemini/duplication-bug work that only exists on `approved` |
| `decision-engine`, `wfm-rca`, `shivam-updates`, `shivam-wfm-rca`, `call2` | earlier experimental/feature branches in the WFM engine's evolution, largely superseded |

**A real, instructive regression came from this exact topology**: `approved-test` (and therefore
`UI`) ran the *original*, more primitive Root Cause bullet-assembly logic for a while — bare
metric-dump bullets, no causal connector requirement — because the fix for that had landed on
`approved` *after* the two branches diverged, and a cherry-pick attempt to bring it over had been
aborted (correctly, to avoid risking the shared branch) and never revisited. The fix was
eventually re-applied by hand-porting the exact diff from `approved`'s fixing commits. **Lesson:**
sibling branches with a shared ancestor can silently drift apart in quality, not just in features —
worth periodically diffing branches that are supposed to represent "the same product, different
presentation" against each other.

**Working-copy convention used throughout:** each branch that needs active work gets its own
sibling folder (`pattern_analyzer2`, `pattern_analyzer2-approved-test`, `pattern_analyzer2-UI`),
cloned fresh rather than switched-into within one working tree, specifically so that work on one
branch can never accidentally bleed into another. `backend/config.json` (gitignored) is copied by
hand into each new clone since it can't come from git.

## 12. Known issues / open questions

- **69 of 442 Forecast_names map to more than one Combined Queue** (§8) — 46 of them are
  genuinely different queues needing a business decision on how to disambiguate, not just a naming
  rule.
- **`Actual_ASU` is missing on ~45% of scoreable rows** — the ASU driver decomposition simply can't
  run on those; correctly reports `available: false` rather than guessing.
- **The exact meaning of `ASU`** (the acronym itself) is still unconfirmed, despite its formula
  being well understood and load-bearing.
- **The Interrogation ("WHY, asked of these findings") UI card is built and returned by the API but
  intentionally not rendered** — commented out pending question-quality work, not a bug.
- **File-upload mode cannot show the Scope/drill-down card** — the ladder needs live SQL aggregate
  queries across the *whole* table; the file-upload path only posts one queue's own rows. This is
  a real, by-design limitation, not a bug — the browser has the full file loaded in memory, so a
  client-side ladder computation is a real, not-yet-built option if this is ever needed offline.
- **A dead SQL host makes a `?mode=wfm` request wait ~42s** before degrading (the fetch is
  deliberately non-fatal, but the ODBC login timeout dominates).
- **No evaluation set exists for ranking correctness** — verification so far proves the engine
  *runs* and the deterministic gates *fire*, not that cause #1 is actually right most of the time.
  A labelled set of ~50-100 past misses is a prerequisite for any further prompt tuning to be
  falsifiable.
- **`Offering`/`Business Org` drill-down and `offering_migration` exist only on `approved`**, not
  yet ported to `approved-test`/`UI` (§11).

## 13. Techniques and methods used building and hardening this product

This section is deliberately about *how the work was done*, not just what exists — the
methodology is as reusable as the code.

### Live-verification discipline over trusting code inspection
Every fix in this project's history was confirmed against a **real running server and real data**
before being called done — never just "the code looks right." This discipline exists *because* of
a real failure earlier in the project: a hand-rolled test script gave a false "still broken" result
because the test script itself had drifted from the real function it was supposed to be checking.
The recovery was to rebuild the test harness to mirror the actual current function byte-for-byte,
then re-test — the standing rule since then is to distrust a test result that contradicts an
otherwise-clearly-correct code change, and check the test itself first.

### Root-cause-first debugging, not symptom patching
Repeated pattern: when something looked broken, the investigation traced to an actual mechanism
before touching code. Examples: a Root Cause quality "regression" turned out to be a sibling
branch that had simply never received an earlier fix (traced via `git log`/`git show`, not
guessed); a drill-down ladder silently stopping at Country was traced to one missing dictionary
key in an endpoint (`sql_backend.py`'s `key` dict lacked `"Offering"`), not a data-availability
limit as first assumed; a hallucinating model copying a prompt's own example text verbatim was
traced to the prompt literally labeling that example "MANDATORY PATTERN."

### Porting fixes exactly via `git show`/`git diff`, not re-deriving them
When the same class of bug existed on a second branch that hadn't received an earlier fix, the
fix was pulled with `git show <commit> -- <file>` and applied as the *exact same diff*, including
its original code comments explaining the WHY — not re-implemented from memory, which risks subtly
different (and unverified) behavior.

### Systemic changes before bespoke ones, for design work
When asked for a full visual overhaul, the highest-leverage first move was rewriting the shared
design tokens and component classes (`.card`, `.tag`, `.chip`, nav, buttons) that every one of the
7 tabs already used — one coordinated change produced consistent impact everywhere, before any
per-screen bespoke polish. When that alone wasn't enough (user feedback: "just a color touch"),
the next escalation was structural — actually moving DOM elements (the KPI row) out of cramped
containers, not just re-coloring what was already there. The distinction mattered and was learned
from direct, blunt user feedback rather than guessed at the outset.

### Distinguishing "not shipped" from "not visible" (browser cache)
Multiple times during heavy UI iteration, the user reported "nothing changed" when the server was
in fact serving the new file correctly. The diagnostic technique: fetch the page with a
cache-busting query parameter (or check response headers) directly from the shell, independent of
any browser, to prove server-side truth before concluding the code was wrong. This dev server
sends no `Cache-Control` header, so a browser can serve a fully cached copy without even
revalidating — worth remembering as a recurring, specific failure mode of this exact setup.

### Verification scripts that mirror production logic exactly, for independent proof
When asked to prove the drill-down ladder was real (not invented by the LLM), a standalone SQL
script was written that reproduces `data_access.py`'s own query logic and `common.adherence_pct`'s
formula byte-for-byte, so a match against the live UI is genuine independent proof and a mismatch
would mean a real bug — not "trust me, the code looks right."

### Branch isolation for risky/exploratory work
Before any structurally risky change (a cherry-pick that might conflict, a full visual overhaul),
the working branch was cloned into its own separate folder rather than switched into within the
existing working tree — so an aborted or messy attempt can never leave the reference branch in a
half-changed state. Confirmed via `git status`/`git log` at each step, not just assumed.

### Testing UI changes with real recorded browser sessions (Canary), not just static analysis
CSS/JS syntax checks (`node --check`, brace-counting) catch *breakage*; they cannot catch "does
this actually look premium." Every visual round in this project was followed by an actual
Playwright-driven recorded session (the `canary` CLI) clicking through the real UI, taking real
screenshots, reviewed visually before reporting anything as done. When a subagent lacked shell
access to drive Canary itself, the same CLI was invoked directly instead of skipping the check.

### Documentation kept current every session, not retrofitted later
`IMP_DOCS/prompt-trail.md` (chronological narrative — what was asked, why, what changed, what was
verified) and `IMP_DOCS/TODO.md` (current punch list) were updated at the end of essentially every
work session, including a dedicated "did I document the WHY, not just the WHAT" pass before
committing — because a future reader (including a future instance of this same assistant) needs
the reasoning, not just the diff.

### Small, reviewable commits with honest messages; secrets never touched
Every commit describes what changed and why in the body, not just a one-line summary. `git status`
was checked before every `git add` to confirm no gitignored secret file (`config.json`) or stray
unrelated change was about to be staged. Commit messages were written to a temp file and applied
with `git commit -F` when they contained characters PowerShell's quoting would otherwise mangle.

### Asking before guessing on subjective/irreversible decisions
Design direction (palette/mood), scope (all 7 tabs vs. just the 2 executives use), and branch
targets for a push were confirmed with the user via explicit questions before large, hard-to-
partially-undo work started — while purely mechanical fixes (a stray hardcoded hex color, a
missing CSS unit) were just fixed directly without asking, since there was only one reasonable
answer.

## 14. Where things live — quick file map

```
rca_console.html                 the entire frontend (one file, no build step)
run.py                           one-command local launcher
README.md                        top-level project readme
knowlegebase.md                  this file
backend/
  sql_backend.py                 FastAPI app, all HTTP endpoints
  rca_investigate.py             the "legacy" generic RCA engine
  rca_wfm.py                     compatibility shim re-exporting backend/wfm/
  upload_excel_to_sql.py         weekly file -> SQL loader
  upload_cqn_mapping.py          CQN workbook -> SQL loader (+ coverage/verify checks)
  config.json                    real secrets (gitignored, never committed)
  config.example.json            documented, secret-free template
  wfm/                           the WFM investigation engine package (see §7 for module map)
IMP_DOCS/
  prompt-trail.md                chronological "what/why" narrative, session by session
  TODO.md                        current punch list, done vs. open
  wfm-rca-engine.md              the WFM engine's own deep-dive reference
  rca-investigation-contract.md  the exact JSON contract between frontend and backend
  installation-and-connection.md setup / SQL connection / troubleshooting
  canary-test-log.md             history of recorded browser-QA findings
  verify_drilldown.sql           (on approved-test/UI) standalone SQL proof of the ladder
results/
  *.py                           validation/smoke-test/spec-compliance scripts
  audit-log.md                   findings log
```

## 15. How to run it locally

1. `cd backend && copy config.example.json config.json`, fill in SQL server details and at least
   one LLM provider's `api_key` (leave both blank to get the honest deterministic-only fallback,
   never a fabricated conclusion).
2. From the repo root: `python run.py` — frees port 8010, installs Python deps, starts the
   FastAPI server, waits for `/api/health`, opens the browser.
3. In the console: either **Connect to SQL Server (AA)** (needs VPN/network access to
   `10.10.9.75`) or **Upload weekly file** with a `.csv`/`.tsv`/`.xlsx` matching the schema in §4.
4. Click any flagged queue in the list, then **Investigate Root Cause** — this calls
   `POST /api/rca-investigate?mode=wfm` and renders the full report once the LLM responds
   (NVIDIA typically 43–100s; a picked model that fails returns the deterministic fallback rather
   than silently switching models).
