"""Local re-implementation of the contest's score, exactly as RULES.txt 'Scoring' defines it.

    pinball(tau, y, q) = 2 * max(tau * d, (tau - 1) * d),  d = ln(y) - ln(q),  y floored at 1

The loss of a case is the mean over its printed hours (2..24) and the five levels; the entry's loss is
the mean over every item of every case. `typical_miss` is 100 * (exp(mean |ln y - ln median|) - 1) and
`coverage90` the share of hours with q05 <= y <= q95.

Validation of this file against the kit's own numbers:
  * the worked example in RULES ('A worked example') scores 0.112545 for the two-hour case;
  * the house baseline (starter/main.py) scores about 0.387 on the four practice cases with typical
    miss 82.8% and 90% coverage 0.783, as RULES' 'Baseline and prizes' states.

The kit ships no local grader ("there is no local grade of this competition: the server grades every
entry"), so this file is the documented arithmetic, not the server's binary.
"""

import json
import math
import sys

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]


def pinball(tau, y, q):
    d = math.log(max(y, 1.0)) - math.log(max(q, 1e-9))
    return 2.0 * max(tau * d, (tau - 1.0) * d)


def score_case(rows, answer):
    """rows: {hour: [q05, q25, q50, q75, q95]}, answer: {hour: viewers} for hours 2..24."""
    hours = sorted(h for h in answer if h >= 2)
    total, misses, covered = 0.0, [], 0
    for h in hours:
        q = rows[h]
        y = answer[h]
        for tau, value in zip(LEVELS, q):
            total += pinball(tau, y, value)
        misses.append(abs(math.log(max(y, 1.0)) - math.log(q[2])))
        if q[0] <= y <= q[4]:
            covered += 1
    n = len(hours)
    return {
        "loss": total / (5 * n),
        "typical_miss_pct": 100.0 * (math.exp(sum(misses) / n) - 1.0),
        "coverage90": covered / n,
        "hours": n,
    }


def score_many(rows_by_case, answers_by_case):
    per = {c: score_case(rows_by_case[c], answers_by_case[c]) for c in sorted(rows_by_case)}
    items = sum(v["hours"] for v in per.values())
    if not items:
        return {"loss": float("nan"), "per_case": {}}
    loss = sum(v["loss"] * v["hours"] for v in per.values()) / items
    coverage = sum(v["coverage90"] * v["hours"] for v in per.values()) / items
    logmiss = sum(math.log1p(v["typical_miss_pct"] / 100.0) * v["hours"] for v in per.values()) / items
    return {"loss": loss, "coverage90": coverage,
            "typical_miss_pct": 100.0 * (math.exp(logmiss) - 1.0), "per_case": per}


def baseline_rows(p1):
    """The house baseline: q_tau(h) = p1 * exp(z_tau * 0.15 * sqrt(h - 1))."""
    z = [-1.6448536269514722, -0.6744897501960817, 0.0, 0.6744897501960817, 1.6448536269514722]
    return {h: [p1 * math.exp(zi * 0.15 * math.sqrt(h - 1)) for zi in z] for h in range(2, 25)}


def load_answers(path):
    """practice_answers.json: {case: {day, hourly: [24 viewers]}} -> {case: {hour 1..24}}."""
    raw = json.loads(open(path).read())
    return {case: {h + 1: v for h, v in enumerate(entry["hourly"])} for case, entry in raw.items()}


def worked_example():
    rows = {2: [600000, 800000, 900000, 1100000, 1500000],
            3: [600000, 800000, 900000, 1100000, 1500000]}
    return score_case(rows, {2: 1000000, 3: 700000})


if __name__ == "__main__":
    print("worked example:", worked_example())
