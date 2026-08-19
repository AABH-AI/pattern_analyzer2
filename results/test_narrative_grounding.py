# -*- coding: utf-8 -*-
"""Test the grounding tolerance: real roundings must pass, inventions must still fail.

The second half matters more than the first. Loosening a guard is only safe if the thing it guards
against still fails, so the invention cases are the real test.
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = r"D:\OneDrive - Aligned Automation Services Private Limited\Documents\rca patternz\test3"
sys.path.insert(0, os.path.join(ROOT, "backend"))

from wfm import narrative_prompt as np

SUPPLIED = {3929.0, 14847.77, 10919.0, 26.5, 33790.0, 0.0018}

CASES = [
    # (written, expect_pass, note)
    (3929.0,   True,  "exact"),
    (3900.0,   True,  "3,929 -> nearest hundred   <-- the case that broke the card"),
    (4000.0,   True,  "3,929 -> nearest thousand, 'about 4,000'"),
    (3930.0,   True,  "3,929 -> nearest ten"),
    (14847.77, True,  "exact decimal"),
    (14848.0,  True,  "14,847.77 -> nearest whole"),
    (14800.0,  True,  "14,847.77 -> nearest hundred"),
    (15000.0,  True,  "14,847.77 -> nearest thousand"),
    (10919.0,  True,  "exact"),
    (10900.0,  True,  "10,919 -> nearest hundred"),
    (11000.0,  True,  "10,919 -> nearest thousand"),
    (26.5,     True,  "exact percentage"),
    (27.0,     True,  "26.5 -> nearest whole"),
    # ---- inventions: every one of these MUST still fail --------------------------------------
    (9999.0,   False, "INVENTION - unrelated to anything supplied"),
    (3500.0,   False, "INVENTION - not a rounding of 3,929"),
    (12500.0,  False, "INVENTION - between two supplied values, is neither"),
    (2000.0,   False, "INVENTION - a round number, but not a rounding of anything here"),
    (0.0,      False, "INVENTION - zero is not a less precise 3,929"),
    (5000.0,   False, "INVENTION - round, unrelated"),
    (13000.0,  False, "INVENTION - 14,847.77 does not round to 13,000"),
    (30000.0,  False, "INVENTION - 33,790 rounds to 34,000, not 30,000"),
]

print("=" * 96)
print("GROUNDING TOLERANCE   supplied = %s" % sorted(SUPPLIED))
print("=" * 96)
ok = bad = 0
for written, expect, note in CASES:
    got = np._matches_supplied(written, SUPPLIED)
    good = (got == expect)
    ok, bad = ok + good, bad + (not good)
    print("  %s %-11s expect %-6s got %-6s %s" % (
        "OK " if good else "BAD", written, "PASS" if expect else "FAIL",
        "PASS" if got else "FAIL", note))

print("\n  %d correct, %d wrong" % (ok, bad))
print("\n  40,000 rounds from 33,790? %s   (should be False -- 33,790 -> 34,000, not 40,000)"
      % np._matches_supplied(40000.0, {33790.0}))
print("  34,000 rounds from 33,790? %s   (should be True)"
      % np._matches_supplied(34000.0, {33790.0}))
sys.exit(1 if bad else 0)
