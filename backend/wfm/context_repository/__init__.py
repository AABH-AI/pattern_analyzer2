# -*- coding: utf-8 -*-
"""Business context the source table does not carry.

`FC_RCA_Context_Repository_Design.md`. Phase 1 holds the Holiday Calendar; the Business
Event, Observation and Lineage repositories are not built yet and report themselves as
NotApplicable rather than pretending to be empty-but-present.
"""
from .holiday_calendar import holiday_context, holiday_span, loaded

__all__ = ["holiday_context", "holiday_span", "loaded"]
