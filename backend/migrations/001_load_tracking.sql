-- =============================================================================
-- 001_load_tracking.sql
-- Make the demand table's refresh detectable, and its scoped reads fast.
--
-- WHY
-- ---
-- The source table is reloaded on a fixed cadence. Two problems today, both measured against
-- a live instance:
--
--   1. NO CHANGE DETECTION. There is no timestamp, version or batch column anywhere in the 32
--      columns, so nothing can tell a console whether the data it is showing is still current.
--      The application falls back to a CHECKSUM_AGG probe (see backend/wfm/data_freshness.py),
--      which works but costs a full scan (~100 ms) and cannot distinguish "reloaded with
--      identical values" from "not reloaded at all".
--
--   2. THE TABLE IS A HEAP. No primary key, no index of any kind. Every scoped read the RCA
--      engine performs -- and it performs four per investigation -- is a full table scan.
--
-- This migration fixes both. It is IDEMPOTENT: safe to run repeatedly, and safe to run against
-- an instance where part of it has already been applied.
--
-- APPLYING IT IS OPTIONAL. The application detects whether LoadedAt exists and uses the
-- checksum fallback when it does not, so an environment that has not run this still works --
-- just more slowly, and with a slightly weaker freshness signal.
--
-- SET THE TABLE NAME ONCE, HERE:
-- =============================================================================
DECLARE @table  sysname = N'dbo.Input_To_ML_Full_138_Trimmed';
DECLARE @object int     = OBJECT_ID(@table);
DECLARE @sql    nvarchar(max);

IF @object IS NULL
BEGIN
    RAISERROR('Table %s does not exist on this server.', 16, 1, @table);
    RETURN;
END

-- -----------------------------------------------------------------------------
-- 1. LoadedAt -- when the ingestion job last wrote this row.
--
-- NULLABLE ON PURPOSE. Existing rows predate the column and their true load time is unknown.
-- Backfilling a made-up value would make every one of them look freshly loaded, so they stay
-- NULL and the freshness probe reads MAX(LoadedAt), which ignores them. The first real load
-- after this migration populates the rows it touches.
-- -----------------------------------------------------------------------------
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = @object AND name = 'LoadedAt')
BEGIN
    SET @sql = N'ALTER TABLE ' + @table + N' ADD LoadedAt datetime2(0) NULL;';
    EXEC sp_executesql @sql;
    PRINT 'ADDED  LoadedAt datetime2(0) NULL';
END
ELSE
    PRINT 'SKIP   LoadedAt already exists';

-- -----------------------------------------------------------------------------
-- 2. LoadBatchId -- which run of the ingestion job wrote this row.
--
-- LoadedAt alone cannot separate two loads in the same second, and cannot group the rows a
-- single run touched. A batch id makes "what did Monday's load actually change?" answerable
-- with one query instead of a diff.
-- -----------------------------------------------------------------------------
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = @object AND name = 'LoadBatchId')
BEGIN
    SET @sql = N'ALTER TABLE ' + @table + N' ADD LoadBatchId uniqueidentifier NULL;';
    EXEC sp_executesql @sql;
    PRINT 'ADDED  LoadBatchId uniqueidentifier NULL';
END
ELSE
    PRINT 'SKIP   LoadBatchId already exists';

-- -----------------------------------------------------------------------------
-- 3. The index the RCA engine's reads actually need.
--
-- Every investigation runs four scoped queries; the two heaviest filter on
-- (Forecast_name, Fiscal_Week). The INCLUDE list carries the columns those queries select, so
-- they are answered from the index without touching the heap.
--
-- NONCLUSTERED, not a clustered PK: the ingestion job's write pattern is unknown to us and
-- imposing a clustered key could change its load performance. A nonclustered index is additive
-- and can be dropped without touching the data.
-- -----------------------------------------------------------------------------
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = @object AND name = 'IX_Demand_Queue_Week')
BEGIN
    SET @sql = N'CREATE NONCLUSTERED INDEX IX_Demand_Queue_Week ON ' + @table + N'
                     (Forecast_name ASC, Fiscal_Week DESC)
                 INCLUDE (Actual_Offered, fcst_offered, Holiday_Count,
                          Planned_ASU, Actual_ASU, Final_Units, Final_upp_units, Week_Ending);';
    EXEC sp_executesql @sql;
    PRINT 'CREATED IX_Demand_Queue_Week';
END
ELSE
    PRINT 'SKIP   IX_Demand_Queue_Week already exists';

-- -----------------------------------------------------------------------------
-- 4. The index the worklist needs.
--
-- The console's default view filters by Fiscal_Week range and then by adherence. Adherence is
-- computed, so it cannot be indexed directly -- but the week range can, and that is the filter
-- that does the work: it cuts 114,436 rows to ~6,264 before the adherence test runs at all.
-- -----------------------------------------------------------------------------
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = @object AND name = 'IX_Demand_Week')
BEGIN
    SET @sql = N'CREATE NONCLUSTERED INDEX IX_Demand_Week ON ' + @table + N'
                     (Fiscal_Week DESC)
                 INCLUDE (Forecast_name, Actual_Offered, fcst_offered,
                          Region, SubRegion, Country, Offering, channel, business_org);';
    EXEC sp_executesql @sql;
    PRINT 'CREATED IX_Demand_Week';
END
ELSE
    PRINT 'SKIP   IX_Demand_Week already exists';

-- -----------------------------------------------------------------------------
-- 5. A load audit trail.
--
-- One row per ingestion run. This is what makes "when did the data last change, and by how
-- much?" answerable without scanning the demand table, and it survives even if the demand
-- table is truncated and reloaded.
-- -----------------------------------------------------------------------------
IF OBJECT_ID('dbo.RCA_Load_Audit') IS NULL
BEGIN
    CREATE TABLE dbo.RCA_Load_Audit (
        LoadBatchId      uniqueidentifier NOT NULL PRIMARY KEY,
        SourceTable      sysname          NOT NULL,
        StartedAt        datetime2(0)     NOT NULL,
        CompletedAt      datetime2(0)     NULL,
        RowsAffected     bigint           NULL,
        FrontierWeek     bigint           NULL,   -- max fiscal week holding actuals after the load
        Notes            nvarchar(400)    NULL
    );
    PRINT 'CREATED dbo.RCA_Load_Audit';
END
ELSE
    PRINT 'SKIP   dbo.RCA_Load_Audit already exists';

PRINT 'Migration 001_load_tracking complete.';
