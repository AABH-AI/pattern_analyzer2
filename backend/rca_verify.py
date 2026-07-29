"""
Claim verifier — re-derive an RCA's numbers from SQL and show the query that did it.
==================================================================================

The problem this solves: a reader is handed "Actual demand this week was 6, whereas the queue's
usual actual is around 8.8" and has no way to check it without writing SQL themselves. Confidence
in an RCA is not a percentage the model asserts — it is whether the numbers survive being looked up.

So for each claim, this builds the EXACT SQL that produces the cited number, runs it, and compares.
Every check returns the SQL it ran, so the reader can paste it into their own client and get the
same answer. Nothing here calls an LLM: the verifier must be independent of the thing it verifies,
or it proves nothing.

    POST /api/verify-finding
      body: {"queue": {...}, "claims": [{"source_field": "...", "value": 6, "text": "..."}]}
      ->    {"verified": n, "failed": n, "checks": [{sql, expected, actual, verdict, ...}]}

Verdicts:
  verified     the number reproduces from SQL within tolerance
  mismatch     SQL returns a different number  -- the claim is wrong
  unsupported  no rule exists to re-derive this field yet (NOT a pass; say so)
  no_data      the query ran but returned nothing to compare
"""
from decimal import Decimal

# How close a cited number has to be. Reports round for display, so exact equality is too strict.
TOLERANCE = 0.02          # 2% relative
ABSOLUTE_FLOOR = 0.05     # ...or this, for values near zero


def _num(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _close(a, b):
    a, b = _num(a), _num(b)
    if a is None or b is None:
        return False
    if a == b:
        return True
    return abs(a - b) <= max(ABSOLUTE_FLOOR, TOLERANCE * max(abs(a), abs(b)))


# ---------------------------------------------------------------------------
# One rule per verifiable claim. Each returns (label, sql, params, extractor).
# `history_cap` matches what the engine used, so "usual" means the same thing here.
# ---------------------------------------------------------------------------
def _this_week(table, col, key):
    return (f"this week's {col}",
            f"SELECT {col} FROM {table} WHERE Forecast_name = ? AND Fiscal_Week = ?",
            (key["Forecast_name"], key["Fiscal_Week"]))


def _usual(table, col, key, weeks):
    return (f"average {col} over the {weeks} weeks before this one",
            f"SELECT AVG(CAST(x.{col} AS FLOAT)) FROM (SELECT TOP {int(weeks)} {col} FROM {table} "
            f"WHERE Forecast_name = ? AND Fiscal_Week < ? AND {col} IS NOT NULL "
            f"ORDER BY Fiscal_Week DESC) x",
            (key["Forecast_name"], key["Fiscal_Week"]))


# Fields a claim can cite, and how to reproduce them.
_DIRECT_COLUMNS = ("Actual_Offered", "fcst_offered", "Planned_ASU", "Actual_ASU",
                   "Final_Units", "Final_upp_units", "Holiday_Count", "Actual_Handled",
                   "fcst_handled")


def _build_checks(table, key, claim, history_cap):
    """Return a list of (label, sql, params, kind) candidates for one claim. A cited value may be
    either this week's figure or the historical average, so both are tried and whichever matches
    is reported -- that is not cheating, it is resolving which number the sentence meant."""
    field = str(claim.get("source_field") or "").strip()
    out = []
    if field in _DIRECT_COLUMNS:
        out.append(_this_week(table, field, key) + ("this_week",))
        out.append(_usual(table, field, key, history_cap) + ("usual",))
    elif field in ("adherence_pct", "accuracy_pct", "error"):
        expr = {"adherence_pct": "(1 - (CAST(Actual_Offered AS FLOAT) / fcst_offered)) * 100",
                "accuracy_pct": "(CAST(Actual_Offered AS FLOAT) / fcst_offered) * 100",
                "error": "CAST(Actual_Offered AS FLOAT) - fcst_offered"}[field]
        out.append((f"this week's {field}",
                    f"SELECT {expr} FROM {table} WHERE Forecast_name = ? AND Fiscal_Week = ? "
                    f"AND fcst_offered IS NOT NULL AND fcst_offered <> 0",
                    (key["Forecast_name"], key["Fiscal_Week"]), "this_week"))
        out.append((f"average {field} over the {history_cap} weeks before this one",
                    f"SELECT AVG(x.v) FROM (SELECT TOP {int(history_cap)} {expr} AS v FROM {table} "
                    f"WHERE Forecast_name = ? AND Fiscal_Week < ? AND fcst_offered IS NOT NULL "
                    f"AND fcst_offered <> 0 ORDER BY Fiscal_Week DESC) x",
                    (key["Forecast_name"], key["Fiscal_Week"]), "usual"))
    return out


def verify(cur, table, key, claims, history_cap=13):
    """Re-derive every claim. Returns the report; never raises on a single bad claim."""
    checks = []
    for i, claim in enumerate(claims or []):
        if not isinstance(claim, dict):
            continue
        cited = _num(claim.get("value"))
        field = str(claim.get("source_field") or "").strip()
        base = {"claim_index": i, "text": claim.get("text"), "source_field": field or None,
                "cited_value": claim.get("value")}

        if cited is None:
            checks.append(dict(base, verdict="unsupported", sql=None,
                               note="The claim quotes no number, so there is nothing to re-derive."))
            continue
        candidates = _build_checks(table, key, claim, history_cap)
        if not candidates:
            checks.append(dict(base, verdict="unsupported", sql=None,
                               note=f"No verification rule for field {field!r} yet. "
                                    f"Verifiable fields: {', '.join(_DIRECT_COLUMNS)}, "
                                    f"adherence_pct, accuracy_pct, error."))
            continue

        attempts, matched = [], None
        for label, sql, params, kind in candidates:
            try:
                cur.execute(sql, params)
                row = cur.fetchone()
                got = _num(row[0]) if row else None
            except Exception as e:
                attempts.append({"interpretation": label, "sql": sql, "error": str(e)[:200]})
                continue
            attempts.append({"interpretation": label, "sql": sql,
                             "sql_returned": round(got, 4) if got is not None else None,
                             "matches": _close(cited, got)})
            if got is not None and _close(cited, got):
                matched = {"interpretation": label, "sql": sql, "sql_returned": round(got, 4),
                           "kind": kind}
                break

        if matched:
            checks.append(dict(base, verdict="verified", sql=matched["sql"],
                               sql_returned=matched["sql_returned"],
                               interpretation=matched["interpretation"],
                               note="Reproduces from SQL."))
        elif all(a.get("sql_returned") is None and "error" not in a for a in attempts):
            checks.append(dict(base, verdict="no_data", sql=attempts[0]["sql"] if attempts else None,
                               attempts=attempts,
                               note="The query ran but returned no value to compare."))
        else:
            checks.append(dict(base, verdict="mismatch",
                               sql=attempts[0]["sql"] if attempts else None, attempts=attempts,
                               note="SQL does not reproduce this number under any interpretation "
                                    "tried. Treat the claim as unverified."))

    counts = {}
    for c in checks:
        counts[c["verdict"]] = counts.get(c["verdict"], 0) + 1
    total = len(checks)
    verified = counts.get("verified", 0)
    return {
        "queue": key,
        "history_cap": history_cap,
        "totals": {"claims": total, "verified": verified,
                   "mismatch": counts.get("mismatch", 0),
                   "unsupported": counts.get("unsupported", 0),
                   "no_data": counts.get("no_data", 0)},
        # Deliberately NOT called "confidence": it is the share of quoted numbers that reproduce,
        # which is a fact, unlike the model's self-reported confidence.
        "reproducible_share": round(verified / total, 2) if total else None,
        "verdict": ("all_verified" if total and verified == total
                    else "some_unverified" if total else "nothing_to_verify"),
        "checks": checks,
    }


def claims_from_response(resp):
    """Pull every quoted number out of an RCA response, wherever the model put it."""
    claims = []
    seen = set()

    def add(ev, where):
        if not isinstance(ev, dict):
            return
        keyed = (str(ev.get("source_field")), str(ev.get("value")), str(ev.get("text"))[:60])
        if keyed in seen:
            return
        seen.add(keyed)
        claims.append({"source_field": ev.get("source_field"), "value": ev.get("value"),
                       "text": ev.get("text"), "found_in": where})

    for ev in (resp.get("supporting_evidence") or []):
        add(ev, "supporting_evidence")
    primary = resp.get("primary_root_cause") or {}
    for ev in (primary.get("supporting_evidence") or []):
        add(ev, "primary_root_cause")
    for i, sec in enumerate(resp.get("secondary_contributors") or [], start=1):
        for ev in ((sec or {}).get("supporting_evidence") or []):
            add(ev, f"secondary_contributor_{i}")
    for i, c in enumerate(resp.get("ranked_root_causes") or [], start=1):
        for ev in ((c or {}).get("evidence") or []):
            add(ev, f"ranked_cause_{i}")
    for s in ((resp.get("derived_features") or {}).get("investigation_loop") or {}).get("steps") or []:
        for ev in (s.get("evidence") or []):
            add(ev, f"investigation_loop_step_{s.get('step')}")
    return claims
