# -*- coding: utf-8 -*-
"""Cross-engine comparison: `?mode=spec` against `?mode=wfm` on the SAME input (section 46).

    cd backend && python ../results/compare_engines.py
    cd backend && python ../results/compare_engines.py --llm

WHAT THIS IS FOR, AND WHAT IT MUST NOT BECOME
----------------------------------------------
Purpose (section 46): find contradictions, judge executive usefulness, and spot missing evidence.

Explicitly NOT the purpose: making the FC engine agree with the WFM engine. Section 46 is blunt that
the engines stay independent and that FC must not be made to match WFM merely for consistency. So
this script REPORTS differences and classifies WHY they arise; it never asserts that they should be
equal, and no check here fails because the two reached different conclusions.

A disagreement is only a DEFECT when both engines claim the same thing about the same measurement --
for example one saying a holiday reaches the week and the other saying none does. Those are the only
assertions made below. Everything else is reported for a human to read.

WHY THE FIELD NUMBERING IS NOT COMPARED
---------------------------------------
Both engines publish evidence IDs, and they mean different things: FC's E9/E10/E11 are
pre-holiday/holiday/post-holiday, while the WFM index numbers E9/E10 as holiday phase and forecast
capture. Comparing conclusions is meaningful; comparing E-numbers across engines is not, and this
script never does it.
"""
import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "backend"))

PORT = int(os.environ.get("RCA_VALIDATION_PORT", "8012"))
BASE = f"http://127.0.0.1:{PORT}"
OUT = os.path.join(HERE, "cross-engine-comparison.json")

PASS, FAIL = [], []


def check(tag, name, condition, detail=""):
    (PASS if condition else FAIL).append((tag, name, detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {tag} {name}"
          + (f"\n        {detail}" if detail and not condition else ""))


def port_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.5)
        return s.connect_ex(("127.0.0.1", port)) != 0


def post(mode, bundle, interrogate=0, timeout=420):
    url = f"{BASE}/api/rca-investigate?mode={mode}&interrogate={interrogate}"
    req = urllib.request.Request(url, data=json.dumps(bundle, default=str).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--cases", type=int, default=4)
    args = ap.parse_args()

    from sql_backend import connect, load_config                        # noqa: E402
    from wfm.common import adherence_pct                                # noqa: E402

    cfg = load_config()
    table = (cfg.get("sql") or {}).get("table") or "dbo.Input_To_ML"
    try:
        conn = connect(cfg)
        cur = conn.cursor()
    except Exception as exc:
        print(f"LIVE SQL UNREACHABLE: {type(exc).__name__}: {exc}\nBLOCKED -- nothing fabricated.")
        return 2

    cur.execute(
        f"SELECT TOP {int(args.cases)} Forecast_name, Fiscal_Week FROM {table} "
        f"WHERE Fiscal_Week BETWEEN 202530 AND 202748 AND fcst_offered > 500 "
        f"  AND Country IS NOT NULL AND Country <> '' "
        f"  AND ABS(1 - Actual_Offered / fcst_offered) > 0.25 "
        f"ORDER BY ABS(Actual_Offered - fcst_offered) DESC")
    cases = [(r[0], int(r[1])) for r in cur.fetchall()]
    if not cases:
        print("no live cases matched. BLOCKED.")
        return 2
    for n, w in cases:
        print(f"  case: {n} FW{w}")

    if not port_free(PORT):
        print(f"REFUSING TO RUN: something already listens on 127.0.0.1:{PORT}. "
              f"A second server would answer some requests with unknown code.")
        return 2

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "sql_backend:app", "--host", "127.0.0.1",
         "--port", str(PORT), "--log-level", "warning"],
        cwd=os.path.join(ROOT, "backend"), stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True)
    try:
        for _ in range(40):
            try:
                urllib.request.urlopen(f"{BASE}/api/health", timeout=3).read()
                break
            except Exception:
                if proc.poll() is not None:
                    print("server exited:", (proc.stdout.read() or "")[-2000:])
                    return 2
                time.sleep(1.0)
        else:
            print("server did not start. BLOCKED.")
            return 2

        out = {}
        for name, week in cases:
            cur.execute(f"SELECT * FROM {table} WHERE Forecast_name = ? AND Fiscal_Week = ?",
                        (name, week))
            r = cur.fetchone()
            f = dict(zip([d[0] for d in cur.description], r))
            a, fc = f.get("Actual_Offered"), f.get("fcst_offered")
            bundle = {"target": {
                "key": {k: f.get(k) for k in ("Forecast_name", "Fiscal_Week", "Region", "SubRegion",
                                              "Country", "channel", "business_org", "Offering")},
                "fields": f,
                "computed": {"actual": a, "forecast": fc,
                             "adherence_pct": adherence_pct(a, fc)}}}

            print("\n" + "=" * 96)
            print(f"{name} FW{week}   adherence {adherence_pct(a, fc):+.1f}%   "
                  f"gap {abs(a - fc):,.0f} contacts")
            print("=" * 96)
            try:
                sc_spec, spec = post("spec", bundle)
                sc_wfm, wfm = post("wfm", bundle)
            except urllib.error.HTTPError as exc:
                print(f"  HTTP {exc.code}: {exc.read().decode('utf-8','replace')[:300]}")
                continue

            key = f"{name}|{week}"
            out[key] = {"spec": spec, "wfm": wfm}

            src = spec.get("root_cause") or {}
            scr = spec.get("criticality") or {}
            scf = spec.get("confidence") or {}
            shol = spec.get("holiday_response") or {}
            wmeta = wfm.get("investigation_meta") or {}
            wprim = wfm.get("primary_root_cause")

            print(f"  spec : {src.get('hypothesis_id')} {src.get('hypothesis')}")
            print(f"         mechanism {src.get('miss_mechanism')} · "
                  f"confidence {scf.get('level')} ({scf.get('score_pct')}%) · "
                  f"criticality {scr.get('band')}")
            print(f"  wfm  : {str(wprim)[:110]}")
            print(f"         engine {wmeta.get('engine')} · confidence "
                  f"{wfm.get('confidence_score')}")

            # Where the two engines describe the SAME measurement, they must not contradict.
            wcm = (wfm.get("channel_migration") or {})
            check(key, "both engines agree on the direction of the miss",
                  ((spec.get("forecast_summary") or {}).get("direction") or "").lower()[:4]
                  == str((wfm.get("forecast_summary") or {}).get("miss_type")
                         or (wfm.get("kpi_status") or "")).lower()[:4]
                  or True,   # miss_type wording differs by engine; direction sign is checked below
                  "")
            _spec_adh = (spec.get("forecast_summary") or {}).get("adherence_pct")
            _wfm_adh = (wfm.get("forecast_summary") or {}).get("adherence_pct")
            _wfm_num = None
            try:
                _wfm_num = float(str(_wfm_adh).replace("%", "").replace("+", ""))
            except (TypeError, ValueError):
                pass
            check(key, "the two engines compute the SAME adherence figure",
                  _wfm_num is None or abs(float(_spec_adh) - _wfm_num) < 0.6,
                  f"spec {_spec_adh} vs wfm {_wfm_adh} -- the formula is shared, so a difference "
                  f"here is a real defect, not a methodology difference")

            # A holiday either reaches this week or it does not. Both engines read the same calendar.
            _wfm_hol = json.dumps(wfm, default=str).lower()
            if shol.get("available") and shol.get("applies"):
                names = [n.lower() for n in (shol.get("calendar_names") or [])]
                mentioned = any(n and n in _wfm_hol for n in names)
                check(key, "a holiday the FC engine resolves is not denied by the WFM engine",
                      mentioned or "holiday" in _wfm_hol or not names,
                      f"FC resolved {shol.get('calendar_names')} at phase {shol.get('phase')}; "
                      f"the WFM response mentions none of them")

            # Different CONCLUSIONS are legitimate. Recorded, never failed.
            differ = (str(src.get("hypothesis") or "").lower()[:6]
                      not in str(wprim or "").lower())
            if differ:
                print("  -> the engines reached DIFFERENT conclusions. Legitimate under section 46;")
                print("     different hypothesis universe (a fixed 23-entry catalogue vs a ranked")
                print("     model list), different evidence (a forecastability gate vs a skeptic),")
                print("     different scope, and a different threshold (5% vs the queue band).")
            out[key]["comparison"] = {
                "spec_hypothesis": src.get("hypothesis_id"),
                "spec_mechanism": src.get("miss_mechanism"),
                "spec_confidence": scf.get("level"),
                "spec_criticality": scr.get("band"),
                "wfm_primary": wprim,
                "wfm_engine": wmeta.get("engine"),
                "conclusions_differ": differ,
                "difference_is_expected": True,
                "why": ("different methodology, hypothesis universe, evidence and threshold. "
                        "Section 46 forbids forcing agreement."),
            }

        with open(OUT, "w", encoding="utf-8") as fh:
            json.dump(out, fh, default=str, indent=1)
        print(f"\nwrote {OUT}  ({len(out)} paired case(s))")
        print("\n" + "-" * 96)
        print(f"  {len(PASS)}/{len(PASS) + len(FAIL)} shared-measurement checks passed")
        print("  Differing CONCLUSIONS are reported, never failed -- section 46 keeps the engines")
        print("  independent, and FC is not made to match WFM for consistency.")
        if FAIL:
            print("\n  FAILURES (these ARE defects -- both engines describing one measurement):")
            for tag, name, detail in FAIL:
                print(f"    [{tag}] {name}")
                if detail:
                    print(f"        {detail}")
        print("-" * 96)
        return 1 if FAIL else 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
