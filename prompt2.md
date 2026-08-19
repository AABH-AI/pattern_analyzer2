# DATASET-SPECIFIC RULES

The source WFM dataset is a WEEKLY dataset.

Primary analytical grain:

Fiscal_Week × Week_Ending × Region × SubRegion × Country
× Forecast_name × Forecaster × Offering
× Projection_plan_name × channel × business_org

The dataset contains weekly Actual and Forecast measures and weekly driver/context
fields.

## AVAILABLE WEEKLY MEASURES

Actual_Offered
Actual_Handled
fcst_offered
fcst_handled
Planned_ASU
Actual_ASU
Final_Units
Final_Y1
Final_Y2
Final_Y3
Final_Y4
Final_Y5
Final_upp_units
Holiday_Count
Monday
Tuesday
Wednesday
Thursday
Friday
Saturday
Sunday
Volume_Category

================================================================
A. DAILY DATA LIMITATION
========================

The source does NOT contain daily Actual_Offered or daily Forecast_Offered.

Therefore the system MUST NOT claim:

* Saturday actual demand
* Sunday actual demand
* Friday forecast miss
* Monday forecast recovery
* day-specific forecast adherence
* day-specific volume contribution

unless a separate daily source is explicitly available.

The weekday columns:

Monday
Tuesday
Wednesday
Thursday
Friday
Saturday
Sunday

must be treated only as WEEKLY DAY-STRUCTURE / DAY-PRESENCE INFORMATION
unless the source schema explicitly defines them otherwise.

Do not interpret these fields as daily actual volume or daily forecast volume.

================================================================
B. WEEKLY CALENDAR EFFECT IS STILL TESTABLE
===========================================

Even without daily demand values, weekly calendar structure can be analyzed.

Where holiday event dates are available, derive:

holiday_weekday
holiday_on_weekend
holiday_adjacent_to_weekend
holiday_before_weekend
holiday_after_weekend
long_weekend_candidate

Then compare weekly outcomes across historical weeks.

Allowed examples:

HOLIDAY ON MONDAY
vs
HOLIDAY ON FRIDAY
vs
MIDWEEK HOLIDAY
vs
NO HOLIDAY

Allowed conclusion:

"Weekly calendar structure is associated with different historical weekly outcomes."

Not allowed:

"Saturday caused the miss."

================================================================
C. WEEKEND EFFECT
=================

Because daily Actual and Forecast measures are unavailable:

DIRECT WEEKEND VOLUME EFFECT:
NOT TESTABLE

However:

WEEKLY CALENDAR / HOLIDAY-WEEKEND STRUCTURE:
MAY BE TESTABLE

Therefore do not stop the calendar investigation with:

"Weekend impact cannot be isolated."

Instead distinguish:

1. Daily weekend demand effect:
   NOT TESTABLE

2. Weekly calendar structure:
   TESTABLE where sufficient history exists

3. Holiday × weekend interaction:
   TESTABLE only through weekly historical pattern if the holiday weekday/date
   is available from the holiday master.

================================================================
D. HOLIDAY JOIN
===============

Holiday information should be joined from the Holiday Master using:

country
+
event date
+
fiscal week

Do not infer the holiday identity solely from Holiday_Count.

Holiday_Count only indicates the weekly count.

The Holiday Master must provide:

raw holiday name
canonical holiday name
semantic_group_id
holiday date
weekday
holiday type
observed/substitute status
joint/bridge status

================================================================
E. HOLIDAY SEMANTIC DEDUPLICATION
=================================

The final executive holiday list must use canonical semantic names.

Example:

RAW:

Ascension Day of Jesus Christ
Ascension of Jesus Christ

If semantic classification confirms SAME_EVENT:

DISPLAY:

Ascension of Jesus Christ

not both names.

Keep original names in audit/supporting evidence.

Do not merge:

Christmas Day
Quaid-e-Azam Day

merely because they share a date.

================================================================
F. CURRENT-WEEK VS ADJACENT HOLIDAY
===================================

The following must be separate fields:

HOLIDAYS_IN_TARGET_WEEK

and

RECENT_HOLIDAYS_AFFECTING_TARGET_WEEK

If the holiday date is outside the target fiscal week:

it MUST NOT appear under:

"Holidays in this week"

It may appear under:

"Recent holidays potentially affecting this week"

This is mandatory.

================================================================
G. WEEKLY DRIVER TESTING
========================

Drivers available in this dataset include:

Actual_ASU
Planned_ASU
Final_Units
Final_upp_units

Final_Y1 through Final_Y5 are nested components and MUST NOT be summed
to recreate Final_Units.

For each applicable driver evaluate:

1. same-week level relationship
2. week-to-week change relationship
3. lagged relationship
4. direction consistency
5. historical stability
6. relationship during miss weeks
7. whether the forecast responded to the signal

================================================================
H. LEVEL VS CHANGE
==================

A relationship in historical levels does not establish a week-to-week driver effect.

Example:

Level correlation = +0.57
Change correlation = -0.25

Executive interpretation:

"ASU tracks demand over the longer historical level, but its week-to-week
movement does not consistently explain the current miss."

Never write:

"ASU drove demand"

from level correlation alone.

================================================================
I. FORECAST RESPONSE
====================

For each usable driver, distinguish:

DRIVER MOVEMENT
from
FORECAST RESPONSE TO DRIVER MOVEMENT

The key question is:

"Did the driver move before the target week, and did the forecast respond
in the appropriate direction and magnitude?"

Example:

Final_Units ↓ 15%
Actual_Offered ↓ 12%
Forecast_Offered ↓ 2%

Possible interpretation:

"Demand fell alongside the shipment signal, but the forecast adjusted only
partially."

Do not automatically call this causal.

================================================================
J. ASU DECOMPOSITION
====================

When Actual_ASU and Planned_ASU are available, decompose the forecast gap into:

POPULATION EFFECT
and
CONTACT-RATE EFFECT

The decomposition explains:

HOW THE FORECAST GAP IS COMPOSED

It does NOT by itself prove:

WHY DEMAND CHANGED.

Example:

Population effect = -3
Contact-rate effect = -20
Total gap = -23

The executive statement may be:

"Most of the forecast gap came from the contact-rate difference rather than
the ASU population difference."

Do not turn this automatically into:

"ASU caused the miss."

================================================================
K. HOLIDAY × WEEKDAY STRUCTURE
==============================

Because the weekly dataset identifies day-of-week structure and the Holiday Master
contains event dates, the system may evaluate:

holiday on Monday
holiday on Tuesday
holiday on Wednesday
holiday on Thursday
holiday on Friday
holiday on Saturday
holiday on Sunday

where sufficient historical sample exists.

However:

Do NOT claim a daily volume effect.

The correct interpretation is:

"Historical weekly outcomes differ when the holiday falls on X."

not:

"Monday caused a 20% volume reduction."

================================================================
L. SCOPE SAFETY
===============

The dataset contains multiple hierarchy levels.

Never mix:

Region
SubRegion
Country
Offering
Channel
Queue

when explaining a target miss.

A Region-level gap can provide CONTEXT.

It must not be presented as the CAUSE of a queue-level miss.

Example:

Region gap = +13,018
Target queue gap = +22

Allowed:

"The queue contributes less than 1% of the region's overall gap."

Not allowed:

"The region caused the queue miss."

================================================================
M. DATA AVAILABILITY STATES
===========================

Every investigation should use one of:

AVAILABLE
PARTIALLY_AVAILABLE
NOT_AVAILABLE
NOT_TESTABLE
INCONCLUSIVE

Specifically:

Daily weekend demand:
NOT_AVAILABLE / NOT_TESTABLE

Weekly holiday structure:
AVAILABLE where Holiday Master + fiscal mapping exists

Historical driver level:
AVAILABLE where populated

Historical driver change:
AVAILABLE where enough consecutive observations exist

Lagged driver:
AVAILABLE only where sufficient history exists

================================================================
N. EXECUTIVE CALENDAR LANGUAGE
==============================

If no holiday falls in the target week:

"Holidays in this week: None."

If prior holidays may influence the week:

"Recent holidays potentially affecting this week: [canonical names]."

Then:

"No holiday occurs directly in this fiscal week; the analysis therefore evaluates
whether this week resembles a historical post-holiday/pre-holiday pattern."

Never write the adjacent holiday list under:

"Holidays in this week."

================================================================
O. FINAL DATA-REALITY CHECK
===========================

Before rendering calendar or driver evidence, verify:

[1] Weekly grain is respected.
[2] No daily demand claims are made.
[3] Holiday identity comes from semantic canonicalization.
[4] Holiday date determines the fiscal-week relationship.
[5] Current-week and adjacent holidays are separated.
[6] Weekday structure is not treated as daily volume.
[7] Level correlation is not treated as week-to-week causality.
[8] Driver movement and forecast response are separated.
[9] ASU decomposition is not treated as causal proof.
[10] Region/context numbers are not mixed with queue-level causes.
[11] Final_Units and Final_upp_units remain separate.
[12] Final_Y1:Y5 are never summed.
[13] Missing daily data is reported as a limitation, not as evidence against
weekend influence.


One final observation from your sample: Holiday_Count plus weekday flags are not enough to identify which holiday occurred on which day. For the calendar work you want, the Holiday Master really should be treated as a first-class joined dataset. That will solve a large part of the current Ascension/Idul Fitri/Waisak confusion before the LLM even sees the RCA evidence.