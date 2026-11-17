"""Calibration report for the entry: practice scores (baseline vs model), determinism, format, runtime,
and a leave-one-comparable-out check that the quantiles are not tuned on the case they score.

    python3 tools/diagnose.py --kit <unpacked kit>      (default: $MAKEFUN_KIT, else ../kit)

Every number printed here comes from tools/grade_local.py, the documented arithmetic of RULES
'Scoring', and from the practice answers the historical source publishes (tools/practice_answers.json).
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import grade_local
import validate
import main as entry


def run_entry(input_dir, output_dir):
    """Two runs, byte compared; returns (seconds of the slower run, per-case bytes)."""
    timings, payloads = [], []
    for _ in range(2):
        start = time.time()
        env = dict(os.environ, MAKEFUN_INPUT_DIR=input_dir, MAKEFUN_OUTPUT_DIR=output_dir)
        subprocess.run([sys.executable, os.path.join(ROOT, "main.py")], check=True, env=env)
        timings.append(time.time() - start)
        payloads.append({name: open(os.path.join(output_dir, name), "rb").read()
                         for name in sorted(os.listdir(output_dir))})
    identical = payloads[0] == payloads[1]
    return max(timings), payloads[0], identical


def practice_report(kit, answers):
    cases = {}
    for case_id in sorted(answers):
        path = os.path.join(kit, "input", case_id + ".in")
        cases[case_id] = json.loads(open(path).read())
    with tempfile.TemporaryDirectory() as out:
        seconds, payloads, identical = run_entry(os.path.join(kit, "input"), out)
    rows = {}
    problems = []
    for case_id in sorted(answers):
        payload = payloads[case_id + ".out"]
        problems.extend("%s: %s" % (case_id, p) for p in validate.check_bytes(payload))
        document = json.loads(payload.decode("utf-8"))
        rows[case_id] = {row["hour"]: row["q"] for row in document["hours"]}
    truth = {case_id: {h: v for h, v in answers[case_id].items() if h >= 2} for case_id in answers}
    model = grade_local.score_many(rows, truth)
    base_rows = {case_id: grade_local.baseline_rows(answers[case_id][1]) for case_id in answers}
    base = grade_local.score_many(base_rows, truth)
    # the grader runs one case per process: time that, on the case with the most comparables
    per_case = {}
    for case_id in sorted(answers):
        with tempfile.TemporaryDirectory() as single_in, tempfile.TemporaryDirectory() as single_out:
            source = os.path.join(kit, "input", case_id + ".in")
            target = os.path.join(single_in, case_id + ".in")
            with open(source, "rb") as src, open(target, "wb") as dst:
                dst.write(src.read())
            env = dict(os.environ, MAKEFUN_INPUT_DIR=single_in, MAKEFUN_OUTPUT_DIR=single_out)
            start = time.perf_counter()
            subprocess.run([sys.executable, os.path.join(ROOT, "main.py")], check=True, env=env)
            per_case[case_id] = time.perf_counter() - start
    return {
        "seconds": max(per_case.values()), "per_case_seconds": per_case,
        "identical": identical, "problems": problems,
        "model": model, "baseline": base, "rows": rows,
        "sizes": {case_id: len(payloads[case_id + ".out"]) for case_id in answers},
        "cases": cases,
    }


def reliability(rows_by_case, answers_by_case):
    """For each level tau: the share of printed hours with y <= q_tau (an honest forecast: ~tau)."""
    counts = {tau: 0 for tau in grade_local.LEVELS}
    hours = 0
    for case_id, rows in rows_by_case.items():
        for hour, q in rows.items():
            y = answers_by_case[case_id].get(hour)
            if y is None:
                continue
            hours += 1
            for tau, value in zip(grade_local.LEVELS, q):
                if y <= value:
                    counts[tau] += 1
    return {tau: counts[tau] / hours for tau in grade_local.LEVELS} if hours else {}


def loo_report(cases, min_v1=15000, min_tier=0.8):
    """Treat each comparable as if it were the case, drop it from its own pool, score it."""
    import datetime as dt

    def iso(t0, hours):
        return dt.datetime.fromtimestamp(t0 + hours * 3600, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    results = []
    base_case = cases[sorted(cases)[0]]
    for comp in base_case["comparables"]:
        name = comp["name"]
        if name.startswith("Grand Theft Auto VI category"):
            continue
        series = entry.comparable_series(comp)
        if not all(o in series for o in range(24)):
            continue
        if series[0] < min_v1 or entry.tier_weight(comp["unlock"]) < min_tier:
            continue
        t0 = entry.parse_ts(comp["day_start"])
        pseudo = {
            "schema": base_case["schema"], "id": "loo", "game": base_case["game"],
            "day_start": comp["day_start"], "checkpoint": base_case["checkpoint"],
            "levels": base_case["levels"],
            "known": [{"hour": 1, "viewers": series[0]}],
            "forecast": base_case["forecast"], "history": [],
            "history_hourly": [{"from": iso(t0, o), "viewers": v} for o, v in sorted(series.items()) if o <= 0],
            "streams": None, "categories_hourly": None,
            "comparables": [c for c in base_case["comparables"] if c["name"] != name],
            "notes": comp["unlock"],
        }
        rows = entry.forecast_case(pseudo)
        answer = {h: series[h - 1] for h in range(2, 25)}
        model = grade_local.score_case(rows, answer)
        base = grade_local.score_case(entry.baseline_rows(series[0]), answer)
        results.append({"name": name, "loss": model["loss"], "base": base["loss"],
                        "coverage": model["coverage90"], "miss": model["typical_miss_pct"],
                        "rows": rows, "answer": answer})
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kit", default=os.environ.get("MAKEFUN_KIT",
                                                        os.path.join(os.path.dirname(ROOT), "makefun",
                                                                     "gta6",
                                                                     "gta6-twitch-ccu-forecast-01-kit")))
    args = parser.parse_args()
    answers = grade_local.load_answers(os.path.join(HERE, "practice_answers.json"))
    truth = {case_id: {h: v for h, v in answers[case_id].items() if h >= 2} for case_id in answers}
    base_rows = {case_id: grade_local.baseline_rows(answers[case_id][1]) for case_id in answers}
    report = practice_report(args.kit, answers)

    print("worked example (RULES)          loss %.6f  (expected 0.112545)" % grade_local.worked_example()["loss"])
    print("two runs byte identical         %s" % report["identical"])
    print("slowest single-case run         %.2f s  (limit 8 s per case; all four: %s)"
          % (report["seconds"], " ".join("%.2f" % v for v in report["per_case_seconds"].values())))
    print("format problems                 %d" % len(report["problems"]))
    for problem in report["problems"]:
        print("   -", problem)
    print("output sizes                    %s" % report["sizes"])
    print()
    print("case   baseline   model    gain   cover90  miss%   typical")
    print("----   --------   -----    ----   -------  -----   -------")
    for case_id in sorted(report["model"]["per_case"]):
        m = report["model"]["per_case"][case_id]
        b = report["baseline"]["per_case"][case_id]
        print("%s    %8.4f  %7.4f  %5.2fx  %7.2f  %5.0f   %6.1f%%"
              % (case_id, b["loss"], m["loss"], b["loss"] / m["loss"], m["coverage90"],
                 m["typical_miss_pct"], 100 * (m["coverage90"] - 0.9)))
    print()
    print("mean over the four practice cases: baseline %.6f   model %.6f   gain %.2fx"
          % (report["baseline"]["loss"], report["model"]["loss"],
             report["baseline"]["loss"] / report["model"]["loss"]))
    print("model coverage90 %.3f  typical miss %.1f%%   (baseline %.3f / %.1f%%)"
          % (report["model"]["coverage90"], report["model"]["typical_miss_pct"],
             report["baseline"]["coverage90"], report["baseline"]["typical_miss_pct"]))
    print()
    print("reliability (share of hours with y <= q_tau; an honest forecast sits at tau)")
    print("   tau       0.05   0.25   0.50   0.75   0.95")
    print("   model     " + "  ".join("%5.2f" % reliability(report["rows"], truth)[tau]
                                     for tau in grade_local.LEVELS))
    print("   baseline  " + "  ".join("%5.2f" % reliability(base_rows, truth)[tau] for tau in grade_local.LEVELS))
    print()
    loo = loo_report(report["cases"])
    if loo:
        mean_model = sum(r["loss"] for r in loo) / len(loo)
        mean_base = sum(r["base"] for r in loo) / len(loo)
        print("leave-one-comparable-out (%d comparable launches, each scored with its own curve removed"
              " from its pool)" % len(loo))
        print("   mean loss %.4f   baseline %.4f   gain %.2fx   coverage90 %.2f"
              % (mean_model, mean_base, mean_base / mean_model,
                 sum(r["coverage"] for r in loo) / len(loo)))
        lrel = reliability({r["name"]: r["rows"] for r in loo}, {r["name"]: r["answer"] for r in loo})
        print("   reliability" + " " * 7 + "  ".join("%5.2f" % lrel[tau] for tau in grade_local.LEVELS))
        worse = [r for r in loo if r["loss"] > r["base"]]
        print("   cases where the baseline wins: %d of %d %s"
              % (len(worse), len(loo), [r["name"] for r in worse]))
        for r in sorted(loo, key=lambda x: x["loss"], reverse=True)[:5]:
            print("   worst: %-34s %.3f (baseline %.3f, coverage %.2f)"
                  % (r["name"][:34], r["loss"], r["base"], r["coverage"]))


if __name__ == "__main__":
    main()
