# SQL ingestion, server-side filtering, and refresh detection

How the console gets its data, how it knows when that data has been reloaded, and what happens
when the database cannot be reached. Every figure here was measured against the live server.

Applies to the whole console. Not engine-specific — both `?mode=wfm` and `?mode=spec` sit behind it.

---

## 1. The three problems this addresses

**The browser held the whole table.** `GET /api/data` is `SELECT * FROM <table>` with no `WHERE`:
114,436 rows, 7.3 s, ~82.6 MB on every page load, filtered afterwards in JavaScript. 11,752 of
those rows are pre-allocated future weeks with no actual and no forecast — shipped, parsed, and
discarded.

**Nothing could tell whether the data had moved.** The source table is reloaded on a fixed cadence.
There is no timestamp, version or batch column in any of its 32 columns, so a console left open
across a reload showed the previous load with nothing saying so.

**A dropped VPN produced a confident-looking RCA.** `connect()` failure and `fetch()` failure were
caught by the same `except`, so an unreachable server fell through to "degrade to the posted
bundle" and returned a card built on 13 posted rows instead of 157 weeks plus the ladder.

---

## 2. Server-side filtering

### `GET /api/rows`

A filtered, paged slice with adherence computed in SQL, so the band applies before rows travel.

| Parameter | Meaning |
|---|---|
| `last_weeks` | Window of the last N weeks **that hold data**. Ignored when `week_from` is given. |
| `week_from`, `week_to` | Explicit fiscal-week bounds, inclusive. |
| `flagged_only`, `band` | Only rows whose `|adherence|` exceeds the band. |
| `region`, `subregion`, `country`, `offering`, `channel`, `business_org`, `forecast_name`, `forecaster`, `volume_category` | Comma-separated for multi-value: `region=EMEA,APJ`. |
| `limit`, `offset`, `include_total` | Paging. `limit` is capped at 20,000. |

Measured:

| Window | Rows | Payload |
|---|---|---|
| Last 13 weeks | 5,434 | 3.6 MB |
| **Last 26 weeks (console default)** | **10,946** | **7.3 MB** |
| Last 52 weeks | 21,939 | 14.9 MB |
| Last 104 weeks | 43,219 | 29.4 MB |
| Everything (`/api/data`) | 114,436 | 82.6 MB |

Flagged + current fiscal year: **6,264 rows, 55 ms, 3.9 MB** — 27× faster and 21× smaller than the
bulk load.

### Why the console fetches a WINDOW, not `flagged_only`

The band slider filters `ROWS` client-side. Fetching only rows already flagged at the current band
would make *lowering* the band show nothing new. Within the window every usable row is present and
the slider behaves exactly as before.

`flagged_only` is still offered on the API, and is the right choice for a caller that is not going
to re-filter. On its own it is a weak filter: 44,883 rows, 39% of the table. **The week window does
the work.**

### RCA context is unaffected

Investigation context comes from `/api/queue-context` and the server-side `fetch_wfm_context()`,
not from `ROWS`. Narrowing the console window does not narrow what an investigation sees.

### `GET /api/facets`

Distinct values and counts for one filter column, honouring the other filters. Lets the console
build dropdowns without downloading the table. Measured 47–88 ms.

### Safety

Every filter **value** is parameterised. Every filter **column** is checked against
`row_query.FILTERABLE` and a non-whitelisted name is rejected with 400 rather than ignored —
silently dropping an unknown filter would return more rows than the caller asked for. `ORDER BY`
is fixed, both because `OFFSET`/`FETCH` needs a deterministic order and so there is no second
place to defend against injection.

### `last_weeks` is resolved, not calculated

Fiscal weeks are `YYYYWW`, so `202701 − 5` is not a week, and a fiscal year is 52 or 53 weeks.
`resolve_last_weeks()` asks the table which weeks actually hold data and takes the Nth. Subtracting
would silently produce a window of the wrong length at every year boundary.

---

## 3. Refresh detection

### `GET /api/data-freshness?token=<held>`

Returns a probe and a comparison. ~100 ms, aggregates only, never returns rows.

Two signals, and the response says which was used:

1. **`load_column`** (preferred) — a `LoadedAt`/batch column written by the ingestion job. Exact,
   and it distinguishes "reloaded with identical values" from "not reloaded".
2. **derived** (fallback) — row count, rows with actuals, frontier week, and `CHECKSUM_AGG` over
   `Actual_Offered` and `fcst_offered`.

The fallback exists because the column does not exist in every environment yet. Verified against
live data that the derived token moves when **one cell changes anywhere** in 114,436 rows, and does
not move when nothing changes.

> **Implementation note.** The two `CHECKSUM_AGG` values are combined in Python, not summed in SQL.
> Each returns an `int` and adding two overflows: SQL Server raises `22003` rather than wrapping.
> Found by the sensitivity test.

### No day of the week is hard-coded

A configured cadence only **words** the message. Staleness is decided by the token moving, never by
the clock. An environment that reloads twice a week, late, or not at all is handled by the same
code — an assumed schedule would report refreshes that never happened.

### Warn only when known

`compare()` reports `stale: true` only when the token is **known** to have changed. An unavailable
probe reports `known: false`, never stale. A banner that fires when nothing happened is one people
learn to dismiss, which costs more than never showing it.

### The token is part of the summary cache key

`_SUMMARY_CACHE` was keyed on `Forecast_name | Fiscal_Week | prompt_version`. A queue-week whose
actuals are later restated keeps the same name and week, so the cache served a summary written from
figures that no longer exist. The key now includes the data token. **This was a correctness bug, not
an optimisation.**

Every `/api/rows` slice and every investigation response carries `data_freshness`, so a card can
later be shown to predate a reload instead of quietly disagreeing with the table.

---

## 4. Unreachable database

Connect failure and fetch failure are now different outcomes:

| Situation | Behaviour |
|---|---|
| Cannot **connect** | **503 `sql_unreachable`** — "Connect to the VPN and try again", naming server, database and driver. **No card is returned.** |
| Connected, **fetch** failed | Still degrades to the posted bundle and states what is missing. |

The split is the point. An unreachable server is something the reader fixes in ten seconds; a failed
query after a successful connect is a schema or permission problem they cannot fix from the console.

503 rather than 500: the service is up and the *dependency* is not. That is what lets the console
choose between "retry" and "report a bug".

### Login timeout

Telling someone to reconnect took **30.3 s**, because `pyodbc.connect(timeout=)` is the *login*
timeout and was being handed the 30 s *query* timeout. Split into `sql.login_timeout` (default 5)
and `sql.timeout` (query, set on the connection afterwards). Measured **30.3 s → 5.2 s**, healthy
path unaffected.

### In the console

A **blocking panel**, not an `alert()`. An alert is dismissed and the console then sits there
looking merely empty; a panel that stays put is the difference between someone reconnecting and
someone concluding the tool is broken. It carries a Retry button and the connection details.

---

## 5. Configuration

```jsonc
"sql": {
  "server": "...", "database": "...", "table": "dbo.Input_To_ML",
  "login_timeout": 5,        // bounds the LOGIN attempt; short on purpose
  "timeout": 30,             // per-statement timeout on an established connection
  "refresh": {
    "cadence": "weekly",     // wording only — never used to decide staleness
    "load_column": null,     // e.g. "LoadedAt" once the migration is applied
    "batch_column": null
  }
}
```

Console-side: `window.RCA_WEEK_WINDOW` (default 26) and the **Weeks to pull** selector.

---

## 6. The migration

`backend/migrations/001_load_tracking.sql` — idempotent, safe to re-run.

| Object | Why |
|---|---|
| `LoadedAt datetime2(0) NULL` | Exact freshness instead of an inferred checksum. **Nullable on purpose** — existing rows predate the column and their true load time is unknown; backfilling would make them all look freshly loaded. |
| `LoadBatchId uniqueidentifier NULL` | Groups the rows one run touched, so "what did this load change?" is one query. |
| `IX_Demand_Queue_Week` | The engine runs four scoped queries per investigation; the two heaviest filter on `(Forecast_name, Fiscal_Week)`. |
| `IX_Demand_Week` | The console's window filter, which is what cuts 114,436 rows to ~6,264. |
| `dbo.RCA_Load_Audit` | One row per ingestion run; survives a truncate-and-reload. |

**Applying it is optional.** The application detects whether `LoadedAt` exists and falls back to the
checksum, so an environment that has not run it still works — more slowly, with a slightly weaker
signal, and saying so.

**Not applied to Playground.** That is a shared instance and the DDL is the data owner's call. The
demand table there is currently a **HEAP** — no primary key and no index of any kind.

---

## 7. What is still true

`GET /api/data` is unchanged and still available. Removing it in the same change that added the
replacement would have made a regression impossible to bisect.

The file-upload path is unchanged. It is no longer the answer to "SQL is down" — that now says
*connect to the VPN* — but the reader is still there.

---

## 8. Tests

```
python results/test_data_ingestion.py     # 44 checks, offline, no SQL and no model
```

A fake cursor rather than a live connection: these checks are about the SQL we *build* and the
decisions we make from what comes back. It also lets a result be forced — a NULL checksum, a raising
column — that a live server will not produce on demand.

Live behaviour was measured separately; the figures are recorded in the module docstrings and above.

Groups: `SAFE-*` filter safety · `BND-*` bounds · `SEM-*` metric semantics · `FRESH-*` the probe ·
`CMP-*` the stale verdict · `DESC-*` the sentence a human reads.
