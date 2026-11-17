"""Leave-one-comparable-out harness: the shipped model, scored on every pooled launch with its own
curve removed from its own pool, broken down by hour band and by quantile level.

    python3 tools/loo.py [--kit <unpacked kit>] [--json] [--min-v1 N] [--min-tier T]

The point of the breakdown is aim: a change should lower the band that actually costs, not the average
by accident. Bands are contest hours: 2-4, 5-8, 9-14, 15-19, 20-24.
"""

import argparse
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import grade_local
import main as entry

BANDS = [(2, 4), (5, 8), (9, 14), (15, 19), (20, 24)]


def iso(t0, hours):
    return dt.datetime.fromtimestamp(t0 + hours * 3600, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def folds(case, min_v1, min_tier):
    for comp in case.get("comparables") or ():
        name = comp.get("name") or ""
        if name.startswith("Grand Theft Auto VI category"):
            continue
        series = entry.comparable_series(comp)
        if not all(o in series for o in range(24)):
            continue
        if series[0] < min_v1 or entry.tier_weight(comp.get("unlock")) < min_tier:
            continue
        t0 = entry.parse_ts(comp["day_start"])
        channels = None
        for point in comp.get("hourly") or ():
            if point.get("from") == comp.get("day_start"):
                channels = point.get("channels")
                break
        pseudo = {
            "schema": case["schema"], "id": "loo", "game": case["game"],
            "day_start": comp["day_start"], "checkpoint": case["checkpoint"],
            "levels": case["levels"],
            "known": [{"hour": 1, "viewers": series[0], "channels": channels}],
            "forecast": case["forecast"], "history": [],
            "history_hourly": [{"from": iso(t0, o), "viewers": v} for o, v in sorted(series.items()) if o <= 0],
            "streams": None, "categories_hourly": None,
            "comparables": [c for c in case["comparables"] if c.get("name") != name],
            "notes": comp.get("unlock") or "",
        }
        yield name, pseudo, series


def item_losses(rows, series):
    """{(hour, level index): loss} for hours 2..24 of one fold."""
    out = {}
    for hour in range(2, 25):
        y = series[hour - 1]
        for index, (tau, q) in enumerate(zip(grade_local.LEVELS, rows[hour])):
            out[(hour, index)] = grade_local.pinball(tau, y, q)
    return out


def run(kit, min_v1=15000, min_tier=0.8):
    case = json.loads(open(os.path.join(kit, "input", "p00.in")).read())
    per_case, band_acc, level_acc, n_items = [], {b: 0.0 for b in BANDS}, [0.0] * 5, 0
    band_n = {b: 0 for b in BANDS}
    covered = 0
    hours_total = 0
    for name, pseudo, series in folds(case, min_v1, min_tier):
        rows = entry.forecast_case(pseudo)
        base = entry.baseline_rows(series[0])
        losses = item_losses(rows, series)
        base_losses = item_losses(base, series)
        case_total = sum(losses.values()) / len(losses)
        base_total = sum(base_losses.values()) / len(base_losses)
        for (hour, index), value in losses.items():
            n_items += 1
            level_acc[index] += value
            for band in BANDS:
                if band[0] <= hour <= band[1]:
                    band_acc[band] += value
                    band_n[band] += 1
                    break
        for band in BANDS:
            pass
        for hour in range(2, 25):
            hours_total += 1
            if rows[hour][0] <= series[hour - 1] <= rows[hour][4]:
                covered += 1
        per_case.append({
            "name": name, "loss": case_total, "baseline": base_total,
            "unlock": entry.unlock_hour(
                {"unlock": pseudo["notes"], "platforms": "", "hourly": [], "day_start": "2000-01-01T00:00:00Z"}),
            "pc": entry.parse_platforms(str(series.get("platforms", "")))["pc"],
            "band": {f"{b[0]}-{b[1]}": sum(v for (h, _), v in losses.items() if b[0] <= h <= b[1])
                     / (5 * (b[1] - b[0] + 1)) for b in BANDS},
        })
    return {
        "mean": sum(c["loss"] for c in per_case) / len(per_case),
        "baseline": sum(c["baseline"] for c in per_case) / len(per_case),
        "band": {f"{b[0]}-{b[1]}": band_acc[b] / band_n[b] for b in BANDS},
        "level": {tau: level_acc[i] / n_items for i, tau in enumerate(grade_local.LEVELS)},
        "coverage": covered / hours_total,
        "cases": per_case,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kit", default=os.environ.get(
        "MAKEFUN_KIT", os.path.join(os.path.dirname(ROOT), "makefun", "gta6",
                                    "gta6-twitch-ccu-forecast-01-kit")))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--min-v1", type=int, default=15000)
    parser.add_argument("--min-tier", type=float, default=0.8)
    args = parser.parse_args()
    report = run(args.kit, args.min_v1, args.min_tier)
    if args.json:
        print(json.dumps(report, indent=1))
        return
    print("LOO (%d comparable launches)" % len(report["cases"]))
    print("  mean loss %.4f   baseline %.4f   gain %.2fx   coverage90 %.3f"
          % (report["mean"], report["baseline"], report["baseline"] / report["mean"], report["coverage"]))
    print("  band      " + "  ".join("%-7s" % b for b in report["band"]))
    print("  loss      " + "  ".join("%-7.4f" % v for v in report["band"].values()))
    print("  level     " + "  ".join("%-7s" % t for t in report["level"]))
    print("  loss      " + "  ".join("%-7.4f" % v for v in report["level"].values()))
    print("  per case:")
    for case in sorted(report["cases"], key=lambda c: -c["loss"]):
        print("    %-34s %.3f (base %.3f) u=%2d bands %s"
              % (case["name"][:34], case["loss"], case["baseline"], case["unlock"],
                 " ".join("%.2f" % v for v in case["band"].values())))


if __name__ == "__main__":
    main()
