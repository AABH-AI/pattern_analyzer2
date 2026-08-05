/* ============================================================================
   WHAT THIS SCRIPT DOES
   ============================================================================
   Reproduces the "Scope — Where the Miss is Visible" drill-down table shown in
   the RCA Console for one queue/week, straight from SQL, level by level:

       Business Org -> Region -> SubRegion -> Country -> Offering -> Channel

   Each level asks the same question: "at this level of the org, was the
   forecast off for this week, and by how much?" Every level below it is a
   NARROWER slice of the one above (Channel is inside Offering, which is
   inside Country, and so on) -- so as you scroll down the results you are
   watching the SAME miss get progressively zoomed in on, until you reach the
   exact queue.

   This is a byte-for-byte match of the production code's own logic
   (backend/wfm/data_access.py, function fetch_wfm_context, _LADDER_LEVELS) --
   same table, same filters, same math. If a number here doesn't match the UI,
   that's a real bug; if it matches, the drill-down is proven correct straight
   from the database, with no LLM or app code in between.
   ============================================================================ */

/* ----------------------------------------------------------------------
   STEP 0 — pick the queue/week to verify.
   Change these 8 values to whichever row you clicked "Investigate" on in
   the console. These are the same dimensions the console's queue key uses.
   ---------------------------------------------------------------------- */
DECLARE @Table       sysname     = N'dbo.Input_To_ML_Full';  -- the live table the app reads from
DECLARE @Week        varchar(10) = '202701';                 -- SA Comm Client Philippines Standard, FW202701
DECLARE @BusinessOrg varchar(50) = 'CSG';                     -- constant across the whole file today
DECLARE @Region      varchar(50) = 'APJ';
DECLARE @SubRegion   varchar(50) = 'SA';
DECLARE @Country     varchar(50) = 'Philippines';
DECLARE @Offering    varchar(50) = 'Basic';
DECLARE @Channel     varchar(50) = 'Voice';
DECLARE @Band        float       = 10.0;   -- the adherence band (%): the console flags anything
                                            -- outside +/-10% as a miss worth investigating

/* ----------------------------------------------------------------------
   STEP 1 — one block per ladder level.
   Every block does the exact same three things, just at a wider or
   narrower scope:
     (a) SUM(Actual_Offered)  -> how much volume actually came in
     (b) SUM(fcst_offered)    -> how much volume the plan expected
     (c) the guard "fcst_offered IS NOT NULL AND fcst_offered <> 0"
         -> a row with no usable forecast can't be scored, so it's excluded
            from both sums (this matches the app exactly -- it never
            silently treats a missing forecast as a zero)
   The blocks are stacked with UNION ALL and stitched together with
   plain-English breadcrumbs so the audience can see exactly which slice
   of the org each row represents.
   ---------------------------------------------------------------------- */
;WITH levels AS (

    -- LEVEL 1: BUSINESS ORG — the whole book of business for this org unit.
    -- This is the widest possible view: every region, every country, every
    -- channel, all rolled into one number for the week.
    SELECT 'Business Org' AS Level, 1 ASj SortOrder,
           CAST(@BusinessOrg AS varchar(50)) AS Scope,
           SUM(Actual_Offered) AS Actual, SUM(fcst_offered) AS Plan_, COUNT(*) AS QueueWeeks
    FROM dbo.Input_To_ML_Full
    WHERE Fiscal_Week = @Week AND business_org = @BusinessOrg
      AND fcst_offered IS NOT NULL AND fcst_offered <> 0

    UNION ALL
    -- LEVEL 2: REGION — same idea, now narrowed to one geographic region
    -- (e.g. Americas). If the miss is already visible here at nearly the
    -- same size as Business Org, the region is where the pattern starts.
    SELECT 'Region', 2, @BusinessOrg + ' / ' + @Region,
           SUM(Actual_Offered), SUM(fcst_offered), COUNT(*)
    FROM dbo.Input_To_ML_Full
    WHERE Fiscal_Week = @Week AND business_org = @BusinessOrg AND Region = @Region
      AND fcst_offered IS NOT NULL AND fcst_offered <> 0

    UNION ALL
    -- LEVEL 3: SUBREGION — one notch inside Region (e.g. Americas -> NA).
    SELECT 'SubRegion', 3, @BusinessOrg + ' / ' + @Region + ' / ' + @SubRegion,
           SUM(Actual_Offered), SUM(fcst_offered), COUNT(*)
    FROM dbo.Input_To_ML_Full
    WHERE Fiscal_Week = @Week AND business_org = @BusinessOrg AND Region = @Region
      AND SubRegion = @SubRegion
      AND fcst_offered IS NOT NULL AND fcst_offered <> 0

    UNION ALL
    -- LEVEL 4: COUNTRY — one notch inside SubRegion (e.g. NA -> United States).
    SELECT 'Country', 4, @BusinessOrg + ' / ' + @Region + ' / ' + @SubRegion + ' / ' + @Country,
           SUM(Actual_Offered), SUM(fcst_offered), COUNT(*)
    FROM dbo.Input_To_ML_Full
    WHERE Fiscal_Week = @Week AND business_org = @BusinessOrg AND Region = @Region
      AND SubRegion = @SubRegion AND Country = @Country
      AND fcst_offered IS NOT NULL AND fcst_offered <> 0

    UNION ALL
    -- LEVEL 5: OFFERING — this is the NEW rung this session added. It splits
    -- the country's volume by support tier/offering (e.g. Basic vs Pro vs
    -- ProSupport). This is what lets us see "is the miss spread evenly
    -- across every offering, or concentrated in just one" -- e.g. a Demand
    -- Switch between offerings, not a real change in total demand.
    SELECT 'Offering', 5, @BusinessOrg + ' / ' + @Region + ' / ' + @SubRegion + ' / ' + @Country + ' / ' + @Offering,
           SUM(Actual_Offered), SUM(fcst_offered), COUNT(*)
    FROM dbo.Input_To_ML_Full
    WHERE Fiscal_Week = @Week AND business_org = @BusinessOrg AND Region = @Region
      AND SubRegion = @SubRegion AND Country = @Country AND Offering = @Offering
      AND fcst_offered IS NOT NULL AND fcst_offered <> 0

    UNION ALL
    -- LEVEL 6: CHANNEL — the narrowest slice: one specific channel (Voice,
    -- Chat, Email, Case, Social Media) inside that Offering. This is the
    -- exact queue the analyst originally clicked "Investigate" on.
    SELECT 'Channel', 6, @BusinessOrg + ' / ' + @Region + ' / ' + @SubRegion + ' / ' + @Country + ' / ' + @Offering + ' / ' + @Channel,
           SUM(Actual_Offered), SUM(fcst_offered), COUNT(*)
    FROM dbo.Input_To_ML_Full
    WHERE Fiscal_Week = @Week AND business_org = @BusinessOrg AND Region = @Region
      AND SubRegion = @SubRegion AND Country = @Country AND Offering = @Offering AND channel = @Channel
      AND fcst_offered IS NOT NULL AND fcst_offered <> 0
)

/* ----------------------------------------------------------------------
   STEP 2 — turn the raw sums into the same figures the console shows:
   Gap (how far off, in contacts) and Adherence % (how far off, as a
   percentage of plan). The formula is the ONE adherence formula used
   everywhere in this app (common.py: adherence_pct) --
       Adherence % = (1 - Actual / Plan) * 100
   IMPORTANT SIGN CONVENTION for the audience: a NEGATIVE number means
   actual volume came in ABOVE the plan (under-forecast); a POSITIVE
   number means actual came in BELOW the plan (over-forecast).
   "Status" flags any level whose |Adherence %| breaches the +/-10% band,
   exactly like the console's own flagging rule.
   ---------------------------------------------------------------------- */
SELECT
    Level,
    Scope,
    ROUND(Actual, 1)                          AS Actual,
    ROUND(Plan_, 1)                           AS Forecast,
    ROUND(Actual - Plan_, 1)                  AS Gap,
    ROUND((1.0 - (Actual / Plan_)) * 100.0, 1) AS Adherence_Pct,
    CASE WHEN ABS((1.0 - (Actual / Plan_)) * 100.0) > @Band
         THEN 'exceeds threshold' ELSE 'within threshold' END AS Status,
    QueueWeeks
FROM levels
ORDER BY SortOrder;

/* ----------------------------------------------------------------------
   HOW TO READ THE RESULT LIVE, TOP TO BOTTOM:
   - If Adherence % barely changes from one row to the next, the miss is
     "inherited" from that wider level -- it isn't specific to the queue,
     it's a pattern across the whole slice above it.
   - The row where Adherence % suddenly jumps in magnitude is exactly where
     the investigation should focus -- that's the level the problem is
     actually concentrated at.
   - Comparing Offering and Channel side by side is what answers the
     "Demand Switch" question: did total volume genuinely change, or did it
     just move from one Offering/Channel to another within the same
     locality (in which case the Country-level total looks fine even
     though individual channels look broken)?
   ---------------------------------------------------------------------- */
