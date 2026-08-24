# -*- coding: utf-8 -*-
"""Re-check every factual claim in ARCHITECTURE_PROMPT.md against the running system.

WHY THIS EXISTS
---------------
An earlier version of that prompt described the model calls without NAMING them, and the diagram tool
filled the gap with three capabilities that do not exist in this system -- "Web Search", "Spec Lookup"
and "Forecaster Intent". A prompt that carries facts is only as good as the facts still being true, and
a stale fact sheet is worse than none because it reads as authoritative.

Run this before regenerating the diagram. Image generations are not free.

    python results/verify_architecture_prompt.py
"""
from __future__ import annotations

import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "backend"))

_ok = _bad = 0


def chk(claim, actual, expect):
    global _ok, _bad
    good = str(actual) == str(expect)
    _ok, _bad = _ok + good, _bad + (not good)
    print("  %s %-48s prompt %-16s actual %s"
          % ("OK " if good else "BAD", claim[:48], expect, actual))


def rd(rel):
    return io.open(os.path.join(ROOT, rel), encoding="utf-8").read()


print("=" * 104)
print("VERIFYING ARCHITECTURE_PROMPT.md AGAINST THE RUNNING SYSTEM")
print("=" * 104)

# ---------------------------------------------------------------- engine shape
from wfm import confidence as cf                                                # noqa: E402
from wfm import hypothesis_catalogue as hc                                       # noqa: E402

weights = [v for v in vars(cf).values() if isinstance(v, dict) and "ContradictoryEvidence" in v][0]
chk("8 weighted confidence factors", len(weights), 8)
chk("heaviest factor is contradictory evidence", max(weights, key=weights.get),
    "ContradictoryEvidence")
chk("...weighted 20%", "%.0f%%" % (weights["ContradictoryEvidence"] * 100), "20%")
chk("weights sum to 1.00", "%.2f" % sum(weights.values()), "1.00")

cat = [v for v in vars(hc).values() if isinstance(v, (list, tuple)) and len(v) > 15][0]
chk("23 candidate explanations", len(cat), 23)
_catof = lambda e: (e.get("category") if isinstance(e, dict) else getattr(e, "category", "?"))
chk("across 6 families", len({_catof(e) for e in cat}), 6)

# ---------------------------------------------------------------- the AI calls
se = rd("backend/wfm/spec_engine.py")
sb = rd("backend/sql_backend.py")
# call SITES, excluding the definition itself
sites = [m for m in re.finditer(r"_call_llm\(", se)]
defs = [m for m in re.finditer(r"def _call_llm\(", se)]
spec_calls = len(sites) - len(defs)
summary_calls = len([m for m in re.finditer(r"_call_llm\(", sb)])
chk("4 model calls on a normal run", spec_calls, 4)
chk("+1 summary call, separate file", summary_calls, 1)
chk("narrative retries once", bool(re.search(r"for attempt in \(1, 2\)", se)), "True")
chk("interrogation has a repair attempt", bool(re.search(r"repair\s*=", se)), "True")
chk("why-chain rewrite is non-fatal",
    bool(re.search(r"kept deterministic wording", se)), "True")

llmc = rd("backend/wfm/llm_client.py")
chk("temperature 0", re.search(r"TEMPERATURE\s*=\s*([\d.]+)", llmc).group(1), "0.0")
chk("top_p 1", re.search(r"TOP_P\s*=\s*([\d.]+)", llmc).group(1), "1.0")
chk("calls go out over urllib, no SDK", bool(re.search(r"urllib\.request", llmc)), "True")

cfgp = os.path.join(ROOT, "backend", "config.json")
if os.path.exists(cfgp):
    llm = (json.load(io.open(cfgp, encoding="utf-8")).get("llm") or {})
    chk("primary provider nvidia", (llm.get("primary") or {}).get("provider"), "nvidia")
    chk("secondary provider groq", (llm.get("secondary") or {}).get("provider"), "groq")
    chk("tertiary provider gemini", (llm.get("tertiary") or {}).get("provider"), "gemini")
    chk("9 user-selectable models", len(llm.get("selectable_models") or []), 9)
else:
    print("  --  config.json absent; provider chain not checked")

# ---------------------------------------------------------------- invented things must stay absent
print("")
print("  the three capabilities the earlier diagram invented -- all must be ZERO:")
for token in ("web_search", "forecaster_intent", "spec_lookup", "vector", "embedding"):
    hits = 0
    for root, _, files in os.walk(os.path.join(ROOT, "backend")):
        if "__pycache__" in root:
            continue
        for f in files:
            if f.endswith(".py") and token in io.open(os.path.join(root, f),
                                                      encoding="utf-8", errors="replace").read():
                hits += 1
    chk("no %s anywhere" % token, hits, 0)

# ---------------------------------------------------------------- the lean stack claim
print("")
for lib in ("pandas", "numpy", "scipy", "sklearn", "statsmodels", "requests",
            "openai", "anthropic", "groq"):
    hits = 0
    for root, _, files in os.walk(os.path.join(ROOT, "backend")):
        if "__pycache__" in root:
            continue
        for f in files:
            if not f.endswith(".py"):
                continue
            src = io.open(os.path.join(root, f), encoding="utf-8", errors="replace").read()
            if re.search(r"^\s*(import %s|from %s)" % (lib, lib), src, re.M):
                hits += 1
    chk("no %s dependency" % lib, hits, 0)

req = rd("backend/requirements.txt")
deps = [l.split(">")[0].split("[")[0].strip() for l in req.split("\n")
        if l.strip() and not l.strip().startswith("#")]
chk("4 dependencies in total", len(deps), 4)
print("       -> %s" % ", ".join(deps))

# ---------------------------------------------------------------- data access shape
da = rd("backend/wfm/data_access.py")
body = da[da.index("def fetch_wfm_context"):]
chk("6 database question shapes", len(re.findall(r"cur\.execute\(", body)), 6)
lad = re.search(r"_LADDER_LEVELS\s*=\s*\(([\s\S]{0,800}?)\)\s*\n\n", da)
chk("6 scope levels", len(re.findall(r'\("([^"]+)"', lad.group(1))), 6)

# ---------------------------------------------------------------- the browser claim
html = rd("rca_console.html")
chk("6 UI tabs", len(re.findall(r"\{ id: '", html)), 6)
chk("zero external references", len(re.findall(r'src="http|href="http|cdn\.', html)), 0)

# ---------------------------------------------------------------- the worked example
ex = os.path.join(HERE, "live-spec-exec-example.json")
if os.path.exists(ex):
    d = json.load(io.open(ex, encoding="utf-8"))
    fs = d.get("forecast_summary") or {}
    chk("example planned 18,932", round(fs.get("forecast") or 0), 18932)
    chk("example arrived 25,697", round(fs.get("actual") or 0), 25697)
    chk("example short by 6,765", round(fs.get("absolute_variance_contacts") or 0), 6765)
    chk("example -35.7%", fs.get("adherence_pct"), -35.7)
    chk("example Critical", (d.get("criticality") or {}).get("band"), "Critical")
    chk("example confidence 67.5%", (d.get("confidence") or {}).get("score_pct"), 67.5)
else:
    print("  --  worked example capture absent; not checked")

# ---------------------------------------------------------------- live scale figures
try:
    from sql_backend import connect, load_config
    cfg = load_config()
    t = cfg["sql"]["table"]
    cn = connect(cfg)
    cu = cn.cursor()

    def q1(sql):
        cu.execute(sql)
        return cu.fetchone()[0]

    print("")
    chk("427 queues", q1("SELECT COUNT(DISTINCT Forecast_name) FROM " + t), 427)
    chk("49 countries", q1("SELECT COUNT(DISTINCT Country) FROM " + t), 49)
    chk("3 regions", q1("SELECT COUNT(DISTINCT Region) FROM " + t), 3)
    chk("5 channels", q1("SELECT COUNT(DISTINCT channel) FROM " + t), 5)
    sc = q1("SELECT COUNT(*) FROM %s WHERE fcst_offered>0 AND Actual_Offered IS NOT NULL" % t)
    chk("71,780 scoreable queue-weeks", format(sc, ","), "71,780")
    by = q1("SELECT COUNT(*) FROM %s WHERE fcst_offered>0 AND Actual_Offered IS NOT NULL "
            "AND ABS(1-Actual_Offered/fcst_offered)*100>10" % t)
    chk("44,883 beyond tolerance", format(by, ","), "44,883")
    chk("...which is 63%", "%.0f%%" % (by * 100.0 / sc), "63%")
    mt = q1("SELECT COUNT(*) FROM %s WHERE fcst_offered>0 AND Actual_Offered IS NOT NULL "
            "AND ABS(1-Actual_Offered/fcst_offered)*100>10 "
            "AND ABS(fcst_offered-Actual_Offered)>=50" % t)
    chk("21,788 worth acting on", format(mt, ","), "21,788")
    chk("23,095 set aside", format(by - mt, ","), "23,095")
    chk("60.3M contacts handled",
        "%.1fM" % (q1("SELECT SUM(CAST(Actual_Offered AS bigint)) FROM " + t) / 1e6), "60.3M")
    chk("78.6M contacts planned",
        "%.1fM" % (q1("SELECT SUM(CAST(fcst_offered AS bigint)) FROM " + t) / 1e6), "78.6M")
    cn.close()
except Exception as e:
    print("  --  database not reachable (%s); scale figures not checked" % str(e)[:60])

print("")
print("=" * 104)
print("  %d verified, %d WRONG" % (_ok, _bad))
if _bad:
    print("  Do NOT regenerate the diagram until the prompt is corrected.")
print("=" * 104)
sys.exit(1 if _bad else 0)
