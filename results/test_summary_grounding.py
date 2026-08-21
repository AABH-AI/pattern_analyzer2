# -*- coding: utf-8 -*-
"""The summary is the shortest, most-forwarded paragraph on the card, so it is the worst place for an
ungrounded number or a causal claim. These are the cases that must FAIL.

The failing half is the real test. This guard is deliberately looser than exact matching so legitimate
rounding survives, which means the invented-number cases are what prove it still bites.

Also asserts the design decision behind the third call: earlier model prose must NOT reach the prompt.
Summarising a summary lets a first-call error return as established fact in the part a lead is most
likely to quote onward.

Costs no model tokens -- `validate_summary` is pure, so model output is supplied directly.

    python results/test_summary_grounding.py
"""
from __future__ import annotations

import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "backend"))

from wfm import summary_prompt                                                  # noqa: E402

CASE = os.path.join(HERE, "live-spec-holiday-repetition-case.json")
if not os.path.exists(CASE):
    print("SKIP  %s not present" % os.path.basename(CASE))
    sys.exit(0)

result = json.load(io.open(CASE, encoding="utf-8"))
fs = result.get("forecast_summary") or {}
actual = fs.get("actual")
forecast = fs.get("forecast")

CASES = [
    ("supplied figures used as given", True, {
        "summary": "The plan was set at %s and demand reached %s. The evidence supports a calendar "
                   "effect the plan did not size correctly. The measures do not all agree."
                   % (forecast, actual),
        "headline": "Demand of %s against a plan of %s." % (actual, forecast),
        "watch_next": "Check whether the same phase repeats next cycle."}),
    ("a ROUNDED supplied figure is allowed", True, {
        "summary": "The plan was about %d contacts and demand landed near %d contacts. The evidence "
                   "supports a calendar effect."
                   % (round(float(forecast), -1), round(float(actual), -1)),
        "headline": "Under-forecast on a holiday week.",
        "watch_next": "nothing specific"}),
    ("AN INVENTED NUMBER must fail", False, {
        "summary": "The plan was 41234 contacts and demand reached 99999 contacts.",
        "headline": "A large miss.", "watch_next": "nothing specific"}),
    ("A CAUSAL VERB must fail", False, {
        "summary": "The holiday caused the miss and drove demand upward.",
        "headline": "The holiday caused the miss.", "watch_next": "nothing specific"}),
    ("an empty summary must fail", False, {
        "summary": "", "headline": "Something happened.", "watch_next": "nothing specific"}),
    ("a missing headline must fail", False, {
        "summary": "The plan was below demand and the evidence supports a calendar effect.",
        "watch_next": "nothing specific"}),
    ("an over-long headline must fail", False, {
        "summary": "The plan was below demand.",
        "headline": "x" * 200, "watch_next": "nothing specific"}),
    ("a non-dict response must fail", False, ["not", "a", "dict"]),
]

print("=" * 98)
print("SUMMARY GROUNDING   (no model tokens spent)")
print("=" * 98)
ok = bad = 0
for label, expect_pass, payload in CASES:
    got, errors = summary_prompt.validate_summary(payload, result)
    good = (got == expect_pass)
    ok, bad = ok + good, bad + (not good)
    print("  %s %-40s expect %-4s got %-4s %s" % (
        "OK " if good else "BAD", label, "PASS" if expect_pass else "FAIL",
        "PASS" if got else "FAIL", "" if good else ("errors=%s" % errors[:2])))

# ---- what the prompt is actually fed ---------------------------------------------------------
msgs = summary_prompt.build_summary_messages(result)
user = msgs[1]["content"]
print("")
print("  prompt input: %s chars, %d line(s)" % (format(len(user), ","), user.count("\n") + 1))
for must in ("HEADLINE FIGURES", "ROOT CAUSE", "CONFIDENCE", "RANKED REASONS"):
    hit = must in user
    ok, bad = ok + hit, bad + (not hit)
    print("  %s input contains %s" % ("OK " if hit else "BAD", must))

# ---- the design decision, asserted, not assumed ----------------------------------------------
narr = result.get("narrative") or {}
pieces = []
for v in (narr.values() if isinstance(narr, dict) else []):
    if isinstance(v, str):
        pieces.append(v)
    elif isinstance(v, list):
        pieces += [x for x in v if isinstance(x, str)]
leaked = [p[:70] for p in pieces if len(p) > 45 and p in user]
ok, bad = ok + (not leaked), bad + bool(leaked)
print("  %s no call-1 narrative prose reached the summary prompt%s"
      % ("OK " if not leaked else "BAD", "" if not leaked else "  -- found: %s" % leaked[:2]))

inter = json.dumps(result.get("interrogation") or result.get("cross_examination") or [], default=str)
inter_leak = False
for chunk in [c.strip() for c in inter.split('"') if len(c.strip()) > 60][:12]:
    if chunk in user:
        inter_leak = True
        break
ok, bad = ok + (not inter_leak), bad + inter_leak
print("  %s no call-2 interrogation prose reached the summary prompt"
      % ("OK " if not inter_leak else "BAD"))

print("")
print("  %d correct, %d wrong" % (ok, bad))
sys.exit(1 if bad else 0)
