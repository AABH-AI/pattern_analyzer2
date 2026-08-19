/* ============================================================================================
   FIND AND VERIFY MULTI-HOLIDAY / LONG-WEEKEND TEST WEEKS      -- READ ONLY, safe in SSMS
   Server 10.10.9.75 · database Playground · table dbo.Input_To_ML_Full_138_Trimmed

   Written because every earlier test used a week with adherence measured on ~150 contacts and
   Holiday_Count = 0, which exercises none of the calendar work. These queries find weeks that do:
   more than two holidays, a long-weekend day flag, and BOTH measures in the hundreds or better.

   Run the whole file (F5) and read the six grids in order. Nothing writes.
   ============================================================================================ */

USE Playground;
GO

DECLARE @MinVolume    float = 200;   -- BOTH actual and forecast must clear this, not just one
DECLARE @MinHolidays  int   = 3;     -- "more than 2 holidays"
DECLARE @MinMissPct   float = 15;    -- material enough to be worth investigating
GO

/* --- 1. Is the pool big enough to choose from? --------------------------------------------- */
SELECT
    COUNT(*)                                                              AS rows_total,
    SUM(CASE WHEN Holiday_Count >= 3 THEN 1 ELSE 0 END)                   AS holidays_3plus,
    SUM(CASE WHEN Holiday_Count >= 3
              AND Actual_Offered >= 200 AND fcst_offered >= 200
             THEN 1 ELSE 0 END)                                           AS plus_volume_200,
    SUM(CASE WHEN Holiday_Count >= 3
              AND Actual_Offered >= 200 AND fcst_offered >= 200
              AND (Friday > 0 OR Monday > 0 OR Saturday > 0 OR Sunday > 0)
             THEN 1 ELSE 0 END)                                           AS plus_long_weekend
FROM dbo.Input_To_ML_Full_138_Trimmed;
GO

/* --- 2. THE CANDIDATES.  All four conditions at once, richest first. -----------------------
   `day_flags` shows which weekdays a holiday touched. Those columns are per-day HOLIDAY FLAGS,
   never daily volumes -- there is no daily Actual_Offered in this source, so no per-day demand
   figure can be derived from them.                                                            */
SELECT TOP 30
       Forecast_name, Fiscal_Week, Country, Offering, channel,
       Holiday_Count,
       CONCAT_WS(',',
           CASE WHEN Monday    > 0 THEN 'Mon' END, CASE WHEN Tuesday  > 0 THEN 'Tue' END,
           CASE WHEN Wednesday > 0 THEN 'Wed' END, CASE WHEN Thursday > 0 THEN 'Thu' END,
           CASE WHEN Friday    > 0 THEN 'Fri' END, CASE WHEN Saturday > 0 THEN 'Sat' END,
           CASE WHEN Sunday    > 0 THEN 'Sun' END)                        AS day_flags,
       CAST(Actual_Offered AS int)                                        AS actual_offered,
       CAST(ROUND(fcst_offered, 1) AS decimal(12,1))                      AS forecast_offered,
       CAST(ROUND((1 - Actual_Offered / fcst_offered) * 100, 1) AS decimal(6,1)) AS adherence_pct,
       CASE WHEN Actual_Offered > fcst_offered THEN 'under-forecast'
            ELSE 'over-forecast' END                                      AS direction,
       CAST(Planned_ASU AS bigint) AS planned_asu, CAST(Actual_ASU AS bigint) AS actual_asu,
       CAST(Final_Units AS int)    AS final_units
FROM   dbo.Input_To_ML_Full_138_Trimmed
WHERE  Holiday_Count >= 3
  AND  Actual_Offered  >= 200
  AND  fcst_offered    >= 200
  AND  (Friday > 0 OR Monday > 0 OR Saturday > 0 OR Sunday > 0)
  AND  ABS(1 - Actual_Offered / fcst_offered) * 100 > 15
ORDER BY Holiday_Count DESC, Actual_Offered DESC;
GO

/* --- 3. A GENUINE long weekend, as against a full shutdown --------------------------------
   China FW202435 has all seven days flagged, which is Golden Week -- it tests the multi-holiday
   path but there is no midweek group left to contrast against. For the long-weekend comparison
   the holiday must sit on Fri/Sat/Sun/Mon with the midweek days clear.                        */
SELECT TOP 20
       Forecast_name, Fiscal_Week, Country, Holiday_Count,
       CONCAT_WS(',',
           CASE WHEN Monday   > 0 THEN 'Mon' END, CASE WHEN Friday   > 0 THEN 'Fri' END,
           CASE WHEN Saturday > 0 THEN 'Sat' END, CASE WHEN Sunday    > 0 THEN 'Sun' END)
                                                                          AS long_weekend_days,
       CAST(Actual_Offered AS int)                                        AS actual_offered,
       CAST(ROUND(fcst_offered, 1) AS decimal(12,1))                      AS forecast_offered,
       CAST(ROUND((1 - Actual_Offered / fcst_offered) * 100, 1) AS decimal(6,1)) AS adherence_pct
FROM   dbo.Input_To_ML_Full_138_Trimmed
WHERE  Holiday_Count BETWEEN 2 AND 4
  AND  Actual_Offered >= 200 AND fcst_offered >= 200
  AND  (Friday > 0 OR Monday > 0)
  AND  Tuesday = 0 AND Wednesday = 0            -- midweek clear, so a contrast group exists
  AND  ABS(1 - Actual_Offered / fcst_offered) * 100 > 15
ORDER BY Actual_Offered DESC;
GO

/* --- 4. HISTORY DEPTH for a candidate queue ------------------------------------------------
   The calendar tests compare a week against comparable weeks, and each weekday group needs 4+
   instances before it is measurable. A queue with 34 weeks of history will report most weekdays
   as not measurable -- correctly, but it makes for a thin test. Edit the name to check yours.  */
DECLARE @Queue nvarchar(200) = N'Social Media China Basic';

SELECT @Queue                                                             AS queue,
       COUNT(*)                                                           AS weeks_total,
       SUM(CASE WHEN Holiday_Count > 0  THEN 1 ELSE 0 END)                AS holiday_weeks,
       SUM(CASE WHEN Holiday_Count >= 3 THEN 1 ELSE 0 END)                AS weeks_3plus_holidays,
       SUM(CASE WHEN Holiday_Count = 0  THEN 1 ELSE 0 END)                AS clean_reference_weeks,
       CAST(AVG(CAST(Actual_Offered AS float)) AS int)                    AS avg_actual,
       CAST(AVG(CAST(fcst_offered   AS float)) AS int)                    AS avg_forecast,
       MIN(Fiscal_Week) AS first_week, MAX(Fiscal_Week) AS last_week
FROM   dbo.Input_To_ML_Full_138_Trimmed
WHERE  Forecast_name = @Queue AND Actual_Offered IS NOT NULL;
GO

/* --- 5. WHICH HOLIDAYS, AND HOW THEY GROUP ------------------------------------------------
   Joins the master to the new semantic-group tables. Two names in one group are ONE event family
   shown once on the card; two names in different groups stay separate even when they share a date.
   The clearest example is china 2023-10-01, where Mid-Autumn Festival and National Day coincide
   and are NOT the same holiday.                                                                */
SELECT h.country_key, h.fiscal_week, h.holiday_name,
       CONVERT(date, h.holiday_date)      AS holiday_date,
       DATENAME(weekday, h.holiday_date)  AS weekday,
       h.holiday_type,
       ISNULL(a.group_id, '(derived key)') AS semantic_group,
       g.display_name                      AS displays_as,
       CASE WHEN h.needs_review = 1 THEN 'REVIEW' ELSE '' END AS flag
FROM        dbo.Holiday_Master        h
LEFT JOIN   dbo.Holiday_Name_Alias    a ON LOWER(a.raw_name) = LOWER(h.holiday_name)
                                       AND (a.country_scope IS NULL
                                            OR a.country_scope = h.country_key)
LEFT JOIN   dbo.Holiday_Semantic_Group g ON g.group_id = a.group_id
WHERE  (h.country_key = 'china' AND h.fiscal_week IN (202435, 202536))
   OR  (h.country_key = 'japan' AND h.fiscal_week = 202548)
ORDER BY h.country_key, h.fiscal_week, h.holiday_date, h.holiday_name;
GO

/* --- 6. DOES THE GROUPING ACTUALLY REDUCE ANYTHING? ---------------------------------------
   raw_names > display_names is the merge doing work. Equal means every name in that week is
   already its own event, which is the correct answer for most weeks.                          */
SELECT h.country_key, h.fiscal_week,
       COUNT(DISTINCT h.holiday_name)                                     AS raw_names,
       COUNT(DISTINCT ISNULL(g.display_name, h.holiday_name))             AS display_names,
       COUNT(DISTINCT h.holiday_name)
         - COUNT(DISTINCT ISNULL(g.display_name, h.holiday_name))         AS names_collapsed,
       STRING_AGG(CAST(h.holiday_name AS nvarchar(max)), ' | ')           AS raw_list
FROM        dbo.Holiday_Master         h
LEFT JOIN   dbo.Holiday_Name_Alias     a ON LOWER(a.raw_name) = LOWER(h.holiday_name)
                                        AND (a.country_scope IS NULL
                                             OR a.country_scope = h.country_key)
LEFT JOIN   dbo.Holiday_Semantic_Group g ON g.group_id = a.group_id
GROUP BY h.country_key, h.fiscal_week
HAVING   COUNT(DISTINCT h.holiday_name) > 1
ORDER BY names_collapsed DESC, raw_names DESC;
GO

/* --- 7. WHAT IS STILL UNDECIDED ------------------------------------------------------------
   Pairs that co-occur on the same country and date where neither a rule nor the alias table
   settles whether they are one event or two. These need a business answer; nothing in the string
   can supply it. DO_NOT_MERGE rows are decisions already taken, with the reason.               */
SELECT verdict, name_a, name_b, country_scope, slots, rationale
FROM   dbo.Holiday_Name_Pair_Review
ORDER BY CASE verdict WHEN 'UNRESOLVED' THEN 0 ELSE 1 END, ISNULL(slots, 0) DESC;
GO
