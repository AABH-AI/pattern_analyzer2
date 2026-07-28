"""Compatibility shim.

The WFM engine was split from this single file into the `wfm/` package (one module per
responsibility) on 2026-07-28. This shim keeps `from rca_wfm import ...` working for anything
that still imports the old path.

New code should import from `wfm` directly:

    from wfm import fetch_wfm_context, investigate_wfm

Module map and rationale: `wfm/__init__.py` and `IMP_DOCS/wfm-rca-engine.md`.
"""
from wfm import (  # noqa: F401  (re-exported for backwards compatibility)
    CAUSE_TYPES,
    CHANNEL_SIBLING_DIMS,
    DEFAULT_BAND_PCT,
    WFM_SYSTEM_PROMPT,
    adherence_pct,
    derive_wfm_features,
    fetch_wfm_context,
    investigate_wfm,
)

__all__ = [
    "fetch_wfm_context",
    "investigate_wfm",
    "derive_wfm_features",
    "WFM_SYSTEM_PROMPT",
    "CAUSE_TYPES",
    "CHANNEL_SIBLING_DIMS",
    "DEFAULT_BAND_PCT",
    "adherence_pct",
]
