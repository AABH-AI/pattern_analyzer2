#!/usr/bin/env python3
"""
Config adaptation for FC_RCA.

config.json is the user's file and describes THEIR deployment: the SQL source, the
Excel loader path, and the LLM slots with their keys. It deliberately does not carry
the engine's internal thresholds.

This module supplies those defaults and merges the user's config over the top, so
config.json stays small and hand-editable while the engine still gets every value it
needs. A key present in config.json always wins.

Also normalises the LLM block: the user's file lists slots as primary / secondary /
tertiary with inline api_key values, and does not carry provider base URLs. Those are
filled in here. An inline key is used as given; the literal "env" still means read
from .env.
"""

from __future__ import annotations

import copy
from typing import Any

PROVIDER_BASE_URLS = {
    "nvidia": {"base_url": "https://integrate.api.nvidia.com/v1", "api_key_env": "NVIDIA_API_KEY"},
    "groq": {"base_url": "https://api.groq.com/openai/v1", "api_key_env": "GROQ_API_KEY"},
    # Google's OpenAI-compatibility layer — same request shape as the other two.
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
               "api_key_env": "GEMINI_API_KEY"},
}

ENGINE_DEFAULTS: dict[str, Any] = {
    "adherence_trigger_pct": 5.0,
    "batch_threshold_pct": 10.0,
    "major_deviation_pct": 75.0,
    "generation_window_weeks": 13,
    "max_reasoning_depth": 6,
    "max_cross_examination_iterations": 3,
    "max_recommendations": 3,
    "hypothesis_catalogue_version": "2.0.0",
    "question_catalogue_version": "2.0.0",
    "business_rules_version": "2.0.0",
    "confidence_weights_version": "2.0.0",
    "materiality_floor_by_band": {
        "<=100": 10, "101-250": 18, "250-500": 30,
        "501-1000": 55, "1001-5000": 120, ">5000": 300,
    },
    "thresholds": {
        "relevance_gate_correlation": 0.30,
        "max_lag_weeks": 13,
        "min_lag_sample": 12,
        "volatility_band_sigma": 2.0,
        "outlier_mad_multiplier": 3.5,
        "trailing_window_weeks": 13,
        "bias_min_periods": 6,
        "bias_run_min": 5,
        "bias_mean_min_pct": 8.0,
        "drift_min_periods": 8,
        "drift_min_shift_pct": 20.0,
        "momentum_min_change_pct": 50.0,
        "variance_expansion_min_ratio": 1.6,
        "trend_divergence_min": 0.5,
        "driver_change_min_pct": 3.0,
        "asu_plan_variance_min_pct": 20.0,
        "holiday_explained_share_min": 0.35,
        "holiday_min_sample": 5,
        "offset_ratio_min": 0.40,
        "redistribution_corr_max": -0.30,
        "seasonality_min_history_weeks": 104,
        "seasonal_consistency_min": 0.60,
        "data_quality_collapse_ratio": 0.15,
    },
}

INVOCATION_DEFAULTS = {
    "temperature": 0, "top_p": 1, "seed": 20260706,
    "max_output_tokens": 4000, "stop_sequences": [],
    "response_format": "json_object", "system_preamble": "detailed thinking off",
}

RETRY_DEFAULTS = {
    "schema_retries": 1, "transport_retries": 4,
    "transport_backoff_seconds": [1, 2, 4, 8],
    "retry_on_status": [429, 500, 502, 503, 504],
}

VALIDATION_DEFAULTS = {
    "enforce_schema": True, "reject_unknown_numerics": True,
    "reject_foreign_root_cause": True, "require_exact_confidence_level": True,
    "require_all_contradictory_evidence": True, "require_all_callouts": True,
    "numeric_tolerance": 0.05,
}

SERVICE_DEFAULTS = {"host": "127.0.0.1", "port": 8787, "audit_directory": "./audit"}

CACHE_DEFAULTS = {"enabled": True, "directory": "./narrative_cache", "immutable": True}


def _merge(base: dict, over: dict) -> dict:
    """Deep merge; a value present in `over` always wins."""
    out = copy.deepcopy(base)
    for key, val in (over or {}).items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], val)
        else:
            out[key] = val
    return out


def normalise(cfg: dict) -> dict:
    """Return a config the engine and server can rely on, without mutating the input."""
    cfg = copy.deepcopy(cfg or {})

    cfg["engine"] = _merge(ENGINE_DEFAULTS, cfg.get("engine") or {})
    cfg["validation"] = _merge(VALIDATION_DEFAULTS, cfg.get("validation") or {})
    cfg["service"] = _merge(SERVICE_DEFAULTS, cfg.get("service") or {})

    llm = cfg.setdefault("llm", {})
    llm["invocation"] = _merge(INVOCATION_DEFAULTS, llm.get("invocation") or {})
    llm["retry"] = _merge(RETRY_DEFAULTS, llm.get("retry") or {})
    llm["narrative_cache"] = _merge(CACHE_DEFAULTS, llm.get("narrative_cache") or {})
    llm.setdefault("timeout_seconds", 150)
    llm.setdefault("budget", {"max_invocations_per_rca": 2, "daily_token_budget": 550000})

    # provider base URLs, inferred from the slots the user actually configured
    providers = dict(llm.get("providers") or {})
    for slot in ("primary", "secondary", "tertiary"):
        prov = (llm.get(slot) or {}).get("provider")
        if prov and prov not in providers and prov in PROVIDER_BASE_URLS:
            providers[prov] = dict(PROVIDER_BASE_URLS[prov])
    for prov in {m.get("provider") for m in llm.get("selectable_models") or []}:
        if prov and prov not in providers and prov in PROVIDER_BASE_URLS:
            providers[prov] = dict(PROVIDER_BASE_URLS[prov])
    llm["providers"] = providers

    # ordered list of slots that actually exist, so callers stop assuming two
    llm["slot_order"] = [s for s in ("primary", "secondary", "tertiary")
                         if (llm.get(s) or {}).get("provider")]

    data = cfg.setdefault("data", {})
    data.setdefault("coerce_string_numerics", True)
    data.setdefault("queue_identity_column", "Forecast_name")
    if cfg.get("excel_path") and not data.get("input_file"):
        data["input_file"] = cfg["excel_path"]

    return cfg


def source_summary(cfg: dict) -> str:
    sql = cfg.get("sql") or {}
    if sql.get("server"):
        return f"SQL {sql['server']}/{sql.get('database')}.{sql.get('table')}"
    return f"Excel {cfg.get('excel_path') or (cfg.get('data') or {}).get('input_file')}"
