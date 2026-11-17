"""Strict validator for a forecast file, written against RULES.txt 'Your forecast'.

    {"hours": [{"hour": h, "q": [q05, q25, q50, q75, q95]}, ...]}

23 rows, hours 2..24 exactly once each, only those two keys per row, five finite numbers in
(0, 1e9], non-decreasing, at most 65,536 bytes of UTF-8 JSON, and (for the entry) byte identical
across two runs.
"""

import json
import math
import sys

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
MAX_BYTES = 65536


def check_bytes(payload):
    problems = []
    if len(payload) > MAX_BYTES:
        problems.append("file is %d bytes, over %d" % (len(payload), MAX_BYTES))
    try:
        document = json.loads(payload.decode("utf-8"))
    except Exception as exc:
        return ["not UTF-8 JSON: %s" % exc]
    if not isinstance(document, dict) or list(document.keys()) != ["hours"]:
        problems.append("top level must be one object with exactly the key 'hours'")
        return problems
    rows = document["hours"]
    if not isinstance(rows, list) or len(rows) != 23:
        problems.append("'hours' must be a list of 23 rows")
        return problems
    seen = {}
    for row in rows:
        if not isinstance(row, dict) or sorted(row.keys()) != ["hour", "q"]:
            problems.append("a row must hold exactly 'hour' and 'q': %r" % (row,))
            continue
        hour = row["hour"]
        if not isinstance(hour, int) or not 2 <= hour <= 24:
            problems.append("bad hour %r" % (hour,))
            continue
        seen[hour] = seen.get(hour, 0) + 1
        q = row["q"]
        if not isinstance(q, list) or len(q) != 5:
            problems.append("hour %d must hold five quantiles" % hour)
            continue
        previous = None
        for tau, value in zip(LEVELS, q):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                problems.append("hour %d: quantile %s is not a number" % (hour, tau))
                continue
            if not math.isfinite(value):
                problems.append("hour %d: quantile %s is not finite" % (hour, tau))
            elif not 0 < value <= 1e9:
                problems.append("hour %d: quantile %s is %r, outside (0, 1e9]" % (hour, tau, value))
            if previous is not None and value < previous:
                problems.append("hour %d: quantiles decrease at %s" % (hour, tau))
            previous = value
    for hour in range(2, 25):
        if seen.get(hour, 0) != 1:
            problems.append("hour %d appears %d times" % (hour, seen.get(hour, 0)))
    return problems


if __name__ == "__main__":
    bad = 0
    for path in sys.argv[1:]:
        problems = check_bytes(open(path, "rb").read())
        if problems:
            bad += 1
            print("%s: INVALID" % path)
            for problem in problems:
                print("   -", problem)
        else:
            print("%s: valid" % path)
    sys.exit(1 if bad else 0)
