"""WFM RCA Investigation Engine — the business-authored investigation, as modules.

Opt-in via `POST /api/rca-investigate?mode=wfm`. Without that parameter the endpoint runs the
original engine in `rca_investigate.py`, which this package does not modify.

Module map (mirrors the responsibilities the business asked for):

    investigation_engine.py         orchestrates the workflow
    hierarchy_analyzer.py           Business Org -> Region -> ... -> Forecast Name drill-down
    channel_migration_detector.py   Voice <-> Chat <-> Email shifts in one locality
    temporal_reasoner.py            104 weeks, prior week / 4 / 13, same week last year
    correlation_engine.py           driver relationships + the exact ASU decomposition
    hypothesis_generator.py         "Hypothesis - To be Validated" marking, deterministic list
    skeptic.py                      rejects causes the features cannot support
    business_report_generator.py    executive report + legacy-key back-compatibility
    data_quality.py                 is the number itself credible?
    data_access.py                  the SQL fetches
    prompts.py                      the business-authored prompt
    common.py                       shared primitives

Opt-in via `?mode=decision` (see IMP_DOCS / yes.md): Python ranks and scores every hypothesis
deterministically (hypothesis_ranker.py) and the LLM's only job is narrating the pre-decided
winner (decision_engine.py, decision_prompts.py) -- it never investigates, ranks, or scores.

Full contract, verification and known gaps: IMP_DOCS/wfm-rca-engine.md
"""
from .common import CAUSE_TYPES, CHANNEL_SIBLING_DIMS, DEFAULT_BAND_PCT, adherence_pct
from .data_access import fetch_wfm_context
from .decision_engine import investigate_decision
from .investigation_engine import derive_wfm_features, investigate_wfm
from .prompts import WFM_SYSTEM_PROMPT

__all__ = [
    "fetch_wfm_context",
    "investigate_wfm",
    "investigate_decision",
    "derive_wfm_features",
    "WFM_SYSTEM_PROMPT",
    "CAUSE_TYPES",
    "CHANNEL_SIBLING_DIMS",
    "DEFAULT_BAND_PCT",
    "adherence_pct",
]
