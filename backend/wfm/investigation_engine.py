"""Orchestrates the WFM investigation.

Order matters and mirrors the prompt's own rules:

    derive features (all deterministic)
      -> threshold gate            (never investigate inside the band)
      -> ONE model call            (rank + explain + challenge, in business language)
      -> skeptic.review            (reject causes the features cannot support)
      -> hypothesis_generator.mark (downgrade over-confident statuses)
      -> business_report_generator (recompute the KPI, build the report, back-fill legacy keys)

Arithmetic is never delegated to the model. If the provider is unreachable, the same report
is built from the deterministic features alone and labelled as such -- it never fabricates.
"""
import json
import urllib.error

from rca_investigate import (
    DEFAULT_MODELS,
    FIELD_DEFINITIONS,
    PROVIDER_ENDPOINTS,
    _finding_from_features,
    _forecast_summary,
    _now,
    _slot_for_choice,
    derive_features,
)

from .llm_client import chat_json, timeout_from_config

from . import (
    business_report_generator as report,
    channel_migration_detector,
    correlation_engine,
    data_quality,
    hierarchy_analyzer,
    hypothesis_generator,
    skeptic,
    statistical_evidence as stats_engine,
    temporal_reasoner,
)
from .common import DEFAULT_BAND_PCT, adherence_pct
from .prompts import WFM_SYSTEM_PROMPT


def derive_wfm_features(context_bundle, wfm_context, band):
    """Every deterministic signal, in one block. Reuses the default engine's
    derive_features() rather than reimplementing it."""
    target = (context_bundle or {}).get("target") or {}
    computed = target.get("computed") or {}
    fields = target.get("fields") or {}

    actual = computed.get("actual", fields.get("Actual_Offered"))
    forecast = computed.get("forecast", fields.get("fcst_offered"))
    week = (target.get("key") or {}).get("Fiscal_Week", fields.get("Fiscal_Week"))
    adherence = computed.get("adherence_pct")
    if adherence is None:
        adherence = adherence_pct(actual, forecast)

    history = wfm_context.get("history_104") or []
    features = {
        "base_features": derive_features(context_bundle),
        "temporal": temporal_reasoner.analyse(history, week, actual, forecast,
                                              wfm_context.get("prior_year_week")),
        "channel_siblings": channel_migration_detector.analyse(
            wfm_context.get("channel_sibling_rows") or [], week, fields.get("channel"),
            cqn_names=wfm_context.get("cqn_names"),
            cqn_source=wfm_context.get("cqn_source", "proxy")),
        "investigation_ladder": hierarchy_analyzer.analyse(
            wfm_context.get("ladder") or [], adherence, band),
        "data_quality": data_quality.analyse(history, wfm_context.get("history_forward") or [],
                                             week, actual),
        "correlations": correlation_engine.analyse(history, fields),
        # Queue-level deterministic statistics. ALWAYS computed -- deliberately NOT gated on whether
        # a higher level also missed, because that gate is exactly what made the investigation stop
        # at "inherited from SubRegion" without ever characterising the queue itself.
        "statistical_evidence": stats_engine.statistical_evidence(history, week, adherence, band),
    }
    return features, adherence


def _payload(context_bundle, features, adherence, band):
    target = (context_bundle or {}).get("target") or {}
    return {
        "kpi": {"name": "Forecast Adherence",
                "formula": "(1 - (Actual_Offered / fcst_offered)) * 100",
                "value_pct": round(adherence, 1) if isinstance(adherence, (int, float)) else None,
                "threshold_pct": band},
        "queue": target.get("key"),
        "target_row_fields": target.get("fields"),
        "forecast_summary": _forecast_summary(target.get("computed") or {}),
        "DERIVED_FEATURES": features.get("base_features"),
        "TEMPORAL": features.get("temporal"),
        "CHANNEL_SIBLINGS": features.get("channel_siblings"),
        "INVESTIGATION_LADDER": features.get("investigation_ladder"),
        "DATA_QUALITY": features.get("data_quality"),
        "CORRELATIONS": features.get("correlations"),
        "ELIGIBLE_CAUSE_TYPES": skeptic.eligible_cause_types(features),
        "FIELD_GLOSSARY": FIELD_DEFINITIONS,
    }


def _assemble(parsed, features, adherence, band, provider, model):
    """Model reply -> reviewed, marked, back-compatible report."""
    parsed = parsed if isinstance(parsed, dict) else {}
    out = {}
    for key, default in report.RESPONSE_DEFAULTS.items():
        value = parsed.get(key, default)
        out[key] = default if value is None else value

    causes = report.normalise_causes(out.get("ranked_root_causes"))
    causes, challenges = skeptic.review(causes, features)
    causes = hypothesis_generator.mark(causes, features)
    out["ranked_root_causes"] = report.normalise_causes(causes)

    # Keep the model's own challenges, then append what the skeptic decided in code.
    model_challenges = [c for c in (out.get("skeptic_review") or []) if isinstance(c, dict)]
    out["skeptic_review"] = model_challenges + challenges

    # Arithmetic wins over narration.
    out["kpi_status"] = report.kpi_status(adherence, band)
    siblings = features.get("channel_siblings") or {}
    out["channel_migration"] = {
        "detected": bool(siblings.get("migration_detected")),
        "narrative": (out.get("channel_migration") or {}).get("narrative") or siblings.get("note", ""),
        "gaining_channels": siblings.get("gaining_channels") or [],
        "losing_channels": siblings.get("losing_channels") or [],
        "grouped_by": siblings.get("grouped_by"),
        "is_cqn_proxy": siblings.get("is_cqn_proxy"),
        "combined_queue_names": siblings.get("combined_queue_names") or [],
        "cqn_note": siblings.get("cqn_note"),
        "detail": siblings,
    }
    # Merge, don't replace: the computed metrics are the trustworthy ones, and a short list
    # from the model must not suppress them.
    model_metrics = [m for m in (out.get("technical_metrics") or []) if isinstance(m, dict)]
    computed_metrics = report.technical_metrics(features)
    seen = {str(m.get("label")) for m in computed_metrics}
    out["technical_metrics"] = computed_metrics + [m for m in model_metrics
                                                  if str(m.get("label")) not in seen]

    out["derived_features"] = features
    out["investigation_meta"] = {"engine": "wfm-llm", "provider": provider, "model": model,
                                "calls": 1, "generated_at": _now()}
    # Statistical evidence is the strongest evidence available, so it is applied BEFORE back_compat
    # -- back_compat derives primary_root_cause/confidence from ranked_root_causes[0], and the
    # override is what decides who holds rank 1.
    out = report.apply_statistical_override(out, features)
    out = report.back_compat(out, features.get("base_features") or {})
    # The prompt's BUSINESS LANGUAGE rule, enforced rather than requested.
    return report.apply_language_guard(out)


def _fallback(features, adherence, band, reason):
    """No model: build the same report from the deterministic signals only, and say so."""
    base = features.get("base_features") or {}
    ctype, finding = _finding_from_features(base)
    causes = report.normalise_causes(hypothesis_generator.deterministic(features, finding, ctype))
    causes, challenges = skeptic.review(causes, features)
    causes = hypothesis_generator.mark(causes, features)
    causes = report.normalise_causes(causes)

    ladder = features.get("investigation_ladder") or {}
    siblings = features.get("channel_siblings") or {}
    top = causes[0] if causes else {}

    out = {
        "executive_summary": top.get("explanation") or (finding or {}).get("statement") or "",
        "kpi_status": report.kpi_status(adherence, band),
        "business_impact": top.get("business_impact") or "",
        "ranked_root_causes": causes,
        "skeptic_review": challenges,
        "investigation_trail": {"levels_checked": [lv.get("level") for lv in (ladder.get("levels") or [])],
                               "inherited_from": ladder.get("inherited_from") or "",
                               "narrative": ladder.get("note") or ""},
        "channel_migration": {"detected": bool(siblings.get("migration_detected")),
                              "narrative": siblings.get("note") or "",
                              "gaining_channels": siblings.get("gaining_channels") or [],
                              "losing_channels": siblings.get("losing_channels") or [],
                              "grouped_by": siblings.get("grouped_by"),
                              "is_cqn_proxy": siblings.get("is_cqn_proxy"),
                              "combined_queue_names": siblings.get("combined_queue_names") or [],
                              "cqn_note": siblings.get("cqn_note"),
                              "detail": siblings},
        "technical_metrics": report.technical_metrics(features),
        "missing_information": [
            f"{reason} This report was built from the deterministic data checks only - it is "
            f"not the full multi-hypothesis WFM investigation."],
        "derived_features": features,
        "cause_type": ctype,
        "investigation_meta": {"engine": "wfm-deterministic-fallback", "generated_at": _now()},
    }
    out = report.apply_statistical_override(out, features)
    return report.apply_language_guard(report.back_compat(out, base))


def investigate_wfm(context_bundle, llm_cfg, wfm_context, model_choice=None, band=None):
    llm_cfg = llm_cfg or {}
    if band is None:
        band = ((context_bundle or {}).get("meta") or {}).get("band_threshold") or DEFAULT_BAND_PCT
    band = float(band)

    features, adherence = derive_wfm_features(context_bundle, wfm_context or {}, band)

    # The business rule: never investigate inside the acceptable threshold.
    if isinstance(adherence, (int, float)) and abs(adherence) <= band:
        return report.not_investigated(adherence, band, features)

    if model_choice and model_choice.get("model"):
        slot = _slot_for_choice(model_choice, llm_cfg)
        if not slot:
            return _fallback(features, adherence, band,
                             f"Selected model '{model_choice.get('model')}' has no API key "
                             f"configured for its provider.")
        slots = [slot]
    else:
        slots = [llm_cfg.get(n) or {} for n in ("primary", "secondary")]
        slots = [s for s in slots if s.get("provider") and s.get("api_key")]
        if not slots:
            return _fallback(features, adherence, band, "No LLM provider is configured.")

    payload = _payload(context_bundle, features, adherence, band)
    timeout = timeout_from_config(llm_cfg)
    failures = []
    for slot in slots:
        endpoint = slot.get("endpoint") or PROVIDER_ENDPOINTS.get(slot.get("provider"))
        model = slot.get("model") or DEFAULT_MODELS.get(slot.get("provider"))
        if not endpoint:
            failures.append(f"unknown provider '{slot.get('provider')}'")
            continue
        messages = [{"role": "system", "content": WFM_SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(payload, default=str)}]
        try:
            parsed = chat_json(endpoint, slot["api_key"], model, messages, timeout=timeout)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:200]
            except Exception:
                pass
            failures.append(f"{slot.get('provider')}/{model} HTTP {e.code}: {detail}")
            continue
        except Exception as e:
            failures.append(f"{slot.get('provider')}/{model} error: {e}")
            continue

        result = _assemble(parsed, features, adherence, band, slot.get("provider"), model)
        if not result.get("ranked_root_causes"):
            # Every proposed cause was rejected, or none was offered. Falling back beats
            # shipping a report with no cause in it -- but record WHAT was rejected and why,
            # otherwise this is an opaque "the LLM didn't work" with no way to diagnose it.
            proposed = [(c.get("cause_type") or "?") for c in (parsed.get("ranked_root_causes") or [])
                        if isinstance(c, dict)]
            rejected = [f"{r.get('cause')}: {r.get('reason')}"
                        for r in (result.get("skeptic_review") or [])
                        if r.get("verdict") == "rejected"]
            detail = f"proposed {proposed or 'nothing'}"
            if rejected:
                detail += f"; all rejected -> {' | '.join(rejected)[:400]}"
            detail += (f"; the data only supports {skeptic.eligible_cause_types(features)}")
            failures.append(f"{slot.get('provider')}/{model} produced no cause the data "
                            f"supports ({detail})")
            continue
        return result

    return _fallback(features, adherence, band, " ".join(f"{f}." for f in failures))
