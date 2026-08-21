# -*- coding: utf-8 -*-
"""Pull every numeric constant, threshold and formula out of the code, so mathematics.md is a record
of what the engine ACTUALLY does rather than what I remember it doing.

Writing that document from memory would be the same mistake as the first conformance audit, which
reported thirteen things missing because it trusted the documentation over the payload.
"""
import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = r"D:\OneDrive - Aligned Automation Services Private Limited\Documents\rca patternz\test3"
BE = os.path.join(ROOT, "backend", "wfm")

print("=" * 100)
print("1. MODULE-LEVEL NUMERIC CONSTANTS  (the thresholds every finding is gated on)")
print("=" * 100)
pat = re.compile(r"^(_?[A-Z][A-Z0-9_]{2,})\s*=\s*(-?\d+(?:\.\d+)?)\s*(?:#\s*(.*))?$", re.M)
total = 0
for fn in sorted(os.listdir(BE)):
    if not fn.endswith(".py"):
        continue
    src = io.open(os.path.join(BE, fn), encoding="utf-8", errors="replace").read()
    hits = pat.findall(src)
    if not hits:
        continue
    print("\n  %s" % fn)
    for name, val, note in hits:
        total += 1
        print("     %-34s %-10s %s" % (name, val, (note or "")[:56]))
print("\n  %d constant(s) total" % total)

print("\n" + "=" * 100)
print("2. THE FORMULAS  (lines that compute a metric, not a threshold)")
print("=" * 100)
FORMULA_HINTS = [
    (r"adherence", "adherence"),
    (r"1\s*-\s*\w*actual\w*\s*/\s*\w*fc?s?t?\w*", "adherence core"),
    (r"MAPE|mape", "accuracy / MAPE"),
    (r"pstdev|stdev|\*\*\s*0\.5", "standard deviation"),
    (r"0\.6745", "modified z-score"),
    (r"median", "median"),
    (r"spearman|_rank", "Spearman"),
    (r"pearson", "Pearson"),
]
seen = set()
for fn in sorted(os.listdir(BE)):
    if not fn.endswith(".py"):
        continue
    src = io.open(os.path.join(BE, fn), encoding="utf-8", errors="replace").read()
    for i, line in enumerate(src.split("\n"), 1):
        t = line.strip()
        if not t or t.startswith("#") or len(t) > 130:
            continue
        for rx, label in FORMULA_HINTS:
            if re.search(rx, t, re.I) and ("=" in t or "return" in t):
                k = (label, t[:70])
                if k in seen:
                    continue
                seen.add(k)
                print("  [%-18s] %s:%d" % (label, fn, i))
                print("      %s" % t[:118])
                break

print("\n" + "=" * 100)
print("3. DATA LINEAGE  (where every number originates)")
print("=" * 100)
da = io.open(os.path.join(BE, "data_access.py"), encoding="utf-8", errors="replace").read()
for m in re.finditer(r'f?"(SELECT[^"]{0,150})', da):
    print("   %s..." % " ".join(m.group(1).split())[:112])
print("\n   tables referenced across the backend:")
tabs = set()
for fn in os.listdir(os.path.join(ROOT, "backend")) + ["wfm/" + x for x in os.listdir(BE)]:
    p = os.path.join(ROOT, "backend", fn)
    if not p.endswith(".py") or not os.path.isfile(p):
        continue
    src = io.open(p, encoding="utf-8", errors="replace").read()
    tabs |= set(re.findall(r"dbo\.[A-Za-z_0-9]+", src))
for t in sorted(tabs):
    print("     %s" % t)
