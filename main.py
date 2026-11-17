"""gta6-twitch-ccu-forecast-01: a pooled launch-curve model for Twitch release-day CCU.

The entry reads one case (`<id>.in`, schema makefun/twitch-ccu-case/v1) per run and writes 23 rows of
five quantiles (0.05, 0.25, 0.5, 0.75, 0.95) for hours 2..24 of the release day (UTC), scored by the
mean pinball loss on ln(viewers).

Model, in one paragraph
-----------------------
Every comparable launch is decomposed on the log scale into a level, a UTC-hour-of-day multiplier and
a release-day surplus that lives on "hours since unlock":

    ln v_c(o) = a_c + D(o mod 24) + S_c(o - u_c) + noise          o = hours after the case's day_start

`a_c` is the category's quiet pre-launch level (median log viewers minus the diurnal, over the quiet
window 5 days to 30 hours before release; a category with too few quiet points is flagged and
down-weighted). `D` is the diurnal multiplier, estimated from comparable hours that are neither the
release day nor the two days after it, so no launch shape leaks into it. `S` is pooled across
comparables as a function of k = hours since that comparable's unlock, so a launch that unlocks at
14:00Z and one that unlocks at 00:00Z contribute their ramps at the same phase.

Two launch-specific covariates correct the pooled shape, both fitted per offset by weighted least
squares over the pool and smoothed over neighbouring hours:

  * ln(v_1)  -- a bigger first hour means most of the audience is already present, so the day grows
    less from there (the 38 comparable launches show this strongly);
  * S_1      -- how elevated hour 1 already is above its own quiet baseline (unlock phase + hype).

The forecast anchors on the case's hour-1 print p1 and adds, per hour o,

    ln q(o) = ln p1 + [D(o) - D(0)] + [R(k_o) - R(k_1)] + B1(o) (ln p1 - mean) + B2(o) (S_1 - mean)

with k_o = o - u_case. Quantiles are not normal and not one shape for the whole day: each comparable's
residual is inflated by its own hat value (the exact leave-one-out factor) to stand for a launch the fit
never saw, and each hour reads its five levels off the weighted empirical quantiles of those
out-of-sample residuals, pooled over a three-hour window so a thin pool cannot make jagged tails.
Intervals widen with the hour's residual scale, the fit's standard error at the case's covariates, and
shrink toward the persistence baseline (0.15 * sqrt(h-1) in log space, normal) when the weighted
evidence is thin or the case's first hour is an outlier against the pool.

Everything is standard library, deterministic and offline; the same input gives byte-identical output.
"""

import json
import math
import os
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
# Normal quantiles, used only for the persistence-baseline fallback and the shrinkage blend.
ZN = [-1.6448536269514722, -0.6744897501960817, 0.0, 0.6744897501960817, 1.6448536269514722]
BASELINE_SIGMA = 0.15

# --- model constants (chosen on the 38-comparable pool, never on the four practice answers) --------
WEIGHT_MODE = "log"    # size similarity: "log" (distance in ln v1) or "rank" (distance in the pool's rank)
SIG_SCALE = 2.2        # kernel width on that similarity (log units, or rank positions)
SIG_UNLOCK = 8.0       # kernel width on |u_c - u_case|, hours (soft: the phase term carries it)
W_PLATFORM_PC_MISMATCH = 0.6   # a PC/console mismatch multiplies the weight
W_WEEKDAY_OTHER = 0.9  # release on another weekday
BETA_CAP = 0.3         # cap on |covariate slope| per offset, log units per unit covariate
GROUP_CAP = 0.4        # cap on the console-only group offset per offset, log units
GROUP_SHRINK = 6.0     # the offset is shrunk by ess / (ess + GROUP_SHRINK)
ESS_K = 14.0           # shrinkage: lambda = ess / (ess + ESS_K)
INFLATE = 0.3          # weight of the fitted-mean standard error in the predictive scale
WIDTH = 0.50           # multiplier on the conformal residual scale
WIDTH_LATE = 0.85      # extra width multiplier for hours 15-24 (both harnesses over-cover there)
WIDTH_EARLY = 1.20     # extra width multiplier for hours 2-8 (both under-cover there)
ROBUST_SCALE = True    # use the weighted MAD instead of the weighted sd for the conditional scale
PEAK_SHIFT = 0.40      # the case's evening peak lands this many hours later than the pool's
PEAK_FROM = 10         # the shift is tapered in from this offset
RAMP_SHIFT = True      # also shift the launch surplus, not only the diurnal
HAT_CAP = 0.8          # cap on the leave-one-out hat value (a weight share that large is degenerate)
PARAM_W = 0.0          # blend weight on the parametric quantile fit (0 = conformal only)
PARAM_ITERS = 10       # IRLS iterations of that fit
BASE_LO, BASE_HI = -120, -30   # quiet pre-launch window (hours from day_start)
MIN_BASE_POINTS = 12

RAMP_STEP = 2          # hours per ramp bin
RAMP_LO, RAMP_HI = -14, 44


# --------------------------------------------------------------------------------------------------
# small numeric helpers


def weighted_mean(values, weights):
    total = sum(weights)
    if total <= 0:
        return 0.0
    return sum(v * w for v, w in zip(values, weights)) / total


def weighted_quantile(pairs, q):
    """Empirical quantile of (value, weight) pairs, with linear interpolation of the weighted CDF."""
    pairs = sorted(pairs)
    total = sum(w for _, w in pairs)
    if total <= 0:
        return 0.0
    target = q * total
    cum = 0.0
    for i, (value, weight) in enumerate(pairs):
        prev, cum = cum, cum + weight
        if cum >= target:
            if weight <= 0 or i + 1 >= len(pairs):
                return value
            frac = (target - prev) / weight
            return value + (pairs[i + 1][0] - value) * (frac - 0.5)
    return pairs[-1][0]


def weighted_ols3(x1, x2, y, w):
    """Weighted least squares y = a + b1 x1 + b2 x2; returns (a, b1, b2, m1, m2)."""
    n = len(y)
    sw = sum(w)
    if n < 4 or sw <= 0:
        return 0.0, 0.0, 0.0, 0.0, 0.0
    m1 = sum(a * wi for a, wi in zip(x1, w)) / sw
    m2 = sum(a * wi for a, wi in zip(x2, w)) / sw
    my = sum(a * wi for a, wi in zip(y, w)) / sw
    s11 = sum(wi * (a - m1) ** 2 for a, wi in zip(x1, w))
    s22 = sum(wi * (a - m2) ** 2 for a, wi in zip(x2, w))
    s12 = sum(wi * (a - m1) * (b - m2) for a, b, wi in zip(x1, x2, w))
    s1y = sum(wi * (a - m1) * (c - my) for a, c, wi in zip(x1, y, w))
    s2y = sum(wi * (a - m2) * (c - my) for a, c, wi in zip(x2, y, w))
    det = s11 * s22 - s12 * s12
    if abs(det) < 1e-9:
        return my, 0.0, 0.0, m1, m2
    b1 = (s1y * s22 - s2y * s12) / det
    b2 = (s2y * s11 - s1y * s12) / det
    return my - b1 * m1 - b2 * m2, b1, b2, m1, m2


def round2(x):
    scaled = x * 100.0
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    return whole / 100.0


# --------------------------------------------------------------------------------------------------
# reading a case


def parse_ts(text):
    """'2026-11-19T00:00:00Z' -> seconds since the epoch (UTC, no timezone database needed)."""
    day, clock = text.rstrip("Z").split("T")
    y, mo, d = (int(p) for p in day.split("-"))
    hh, mm, ss = (int(p) for p in clock.split(":"))
    return (date(y, mo, d).toordinal() - 719163) * 86400 + hh * 3600 + mm * 60 + ss


def comparable_series(comp):
    t0 = parse_ts(comp["day_start"])
    series = {}
    for point in comp.get("hourly") or ():
        viewers = point.get("viewers")
        if not viewers or viewers <= 0:
            continue
        offset = int(round((parse_ts(point["from"]) - t0) / 3600.0))
        series[offset] = viewers
    return series


def parse_platforms(text):
    text = (text or "").lower()
    return {
        "pc": ("pc" in text) or ("steam" in text) or ("windows" in text),
        "ps": "ps" in text,
        "xb": "xbox" in text,
        "sw": "switch" in text,
    }


CLOCK = re.compile(r"(\d{1,2}):(\d{2})\s*(?:Z|UTC)")
DAY_START_PHRASE = ("day_start", "viewers and channels", "sullygnome")


def wave_hours(text):
    """Every explicit 'HH:MM Z|UTC' hour named in the note, ignoring sentences about the data itself."""
    hours = []
    for sentence in re.split(r"[.;]\s", text or ""):
        low = sentence.lower()
        if any(phrase in low for phrase in DAY_START_PHRASE):
            continue
        for match in CLOCK.finditer(sentence):
            hours.append(int(match.group(1)))
    return hours


def pick_wave(hours):
    """The release-day wave: the earliest explicit hour in 00..08Z, else the earliest named."""
    for hh in range(0, 9):
        if hh in hours:
            return hh
    return min(hours) if hours else None


def unlock_hour(comp):
    """The comparable's unlock hour, in UTC hours after its day_start.

    Read from the note when it names one (the kit's notes name the waves for most launches); the
    console convention otherwise, US Eastern midnight, which the pool's winter cases put at 04:00Z.
    The value aligns curves by phase, and a misaligned comparable is damped by its weight.
    """
    picked = pick_wave(wave_hours(comp.get("unlock") or ""))
    return 4 if picked is None else picked


def tier_weight(text):
    text = text or ""
    if "early-access-contaminated" in text:
        return 0.25
    if "Tier: weak" in text:
        return 0.5
    if "unverified" in text:
        return 0.8
    return 1.0


def case_unlock_hour(notes):
    """The case's own unlock hour, on the same convention as the comparables."""
    picked = pick_wave(wave_hours(notes or ""))
    return 4 if picked is None else picked


def weekday_of(case):
    days = parse_ts(case["day_start"]) // 86400
    return (days + 4) % 7  # 1970-01-01 was a Thursday


# --------------------------------------------------------------------------------------------------
# pool preparation


def diurnal(pool):
    """D[24]: UTC-hour-of-day multiplier from clean, non-release days, centred."""
    buckets = [[] for _ in range(24)]
    for comp in pool:
        for offset, viewers in comp["series"].items():
            if offset <= -14 or offset >= 40:
                buckets[offset % 24].append(math.log(viewers))
    raw = [sum(b) / len(b) if b else None for b in buckets]
    known = [v for v in raw if v is not None]
    centre = sum(known) / len(known) if known else 0.0
    return [(v if v is not None else centre) - centre for v in raw]


def quiet_level(comp, diurnal_profile):
    """a_c: the log level of the category on quiet days, diurnal removed."""
    values = [math.log(v) - diurnal_profile[o % 24]
              for o, v in comp["series"].items()
              if BASE_LO <= o <= BASE_HI and v >= 2]
    if len(values) < MIN_BASE_POINTS:
        values = [math.log(v) - diurnal_profile[o % 24]
                  for o, v in comp["series"].items() if o <= -7 and v >= 2]
    if len(values) < MIN_BASE_POINTS:
        return None
    return sum(values) / len(values)


def prepare_pool(case, exclude):
    pool = []
    for comp in case.get("comparables") or ():
        name = comp.get("name") or ""
        if name.startswith("Grand Theft Auto VI category"):
            continue  # the target category before release: no launch day to learn from
        if name in exclude:
            continue
        series = comparable_series(comp)
        if not all(o in series for o in range(24)):
            continue
        pool.append({
            "name": name,
            "series": series,
            "u": unlock_hour(comp),
            "tier": tier_weight(comp.get("unlock")),
            "platforms": parse_platforms(comp.get("platforms")),
            "weekday": weekday_of({"day_start": comp.get("day_start") or case["day_start"]}),
            "v1": series[0],
        })
    profile = diurnal(pool)
    for comp in pool:
        level = quiet_level(comp, profile)
        comp["level"] = level
        if level is None:
            comp["S"] = comp["S1"] = comp["L"] = None
            comp["x1"] = math.log(comp["v1"])
            comp["x2"] = 0.0
        else:
            comp["S"] = {o: math.log(comp["series"][o]) - level - profile[o % 24] for o in range(24)}
            comp["S1"] = comp["S"][0]
            comp["L"] = {o: comp["S"][o] - comp["S1"] for o in range(24)}
            # the ramp is pooled on level-free curves: L_c(o) = Sc(o) - Sc(0) exactly, so centring
            # each comparable on its own mean surplus removes its level without changing the shape
            centre = sum(comp["S"].values()) / 24.0
            comp["Sc"] = {o: comp["S"][o] - centre for o in range(24)}
            comp["x1"] = math.log(comp["v1"])
            comp["x2"] = comp["S1"]

    return pool, profile


def pool_ramp(pool, weights, shifts, means):
    """R(k): covariate-adjusted surplus, pooled by hours since unlock (k = o - u_c)."""
    bins = list(range(RAMP_LO, RAMP_HI, RAMP_STEP))
    acc = {b: 0.0 for b in bins}
    wsum = {b: 0.0 for b in bins}
    for comp, weight in zip(pool, weights):
        if comp["Sc"] is None:
            continue
        for o in range(24):
            k = o - comp["u"]
            b = max(bins[0], min(bins[-1], RAMP_STEP * int(math.floor(k / RAMP_STEP))))
            b1, b2 = shifts.get(o, (0.0, 0.0))
            adjusted = comp["Sc"][o] - b1 * (comp["x1"] - means[0]) - b2 * (comp["x2"] - means[1])
            acc[b] += weight * adjusted
            wsum[b] += weight
    raw = {b: (acc[b] / wsum[b] if wsum[b] > 0 else None) for b in bins}
    known = [(b, raw[b]) for b in bins if raw[b] is not None]
    if not known:
        return {b: 0.0 for b in bins}
    filled = {}
    for b in bins:
        if raw[b] is not None:
            filled[b] = raw[b]
            continue
        below = [x for x in known if x[0] < b]
        above = [x for x in known if x[0] > b]
        if below and above:
            (b0, v0), (b1, v1) = below[-1], above[0]
            filled[b] = v0 + (v1 - v0) * (b - b0) / (b1 - b0)
        elif below:
            filled[b] = below[-1][1]
        else:
            filled[b] = above[0][1]
    smooth = {}
    for i, b in enumerate(bins):
        lo = filled[bins[max(0, i - 1)]]
        hi = filled[bins[min(len(bins) - 1, i + 1)]]
        smooth[b] = 0.25 * lo + 0.5 * filled[b] + 0.25 * hi
    return smooth


def ramp_at(ramp, k):
    bins = sorted(ramp)
    if k <= bins[0]:
        return ramp[bins[0]]
    if k >= bins[-1]:
        return ramp[bins[-1]]
    base = RAMP_STEP * int(math.floor(k / RAMP_STEP))
    frac = (k - base) / RAMP_STEP
    hi = base + RAMP_STEP
    return ramp[base] * (1.0 - frac) + ramp[hi] * frac


# --------------------------------------------------------------------------------------------------
# forecast


def forecast_case(case):
    first = next((row for row in case.get("known") or () if row.get("hour") == 1), None)
    p1 = max(1.0, float(first["viewers"])) if first and first.get("viewers") else 1.0
    notes = case.get("notes") or ""
    u_case = case_unlock_hour(notes)
    weekday = weekday_of(case)
    case_platforms = parse_platforms(notes)

    pool, profile = prepare_pool(case, exclude=())

    # similarity in size: distance in log hour-1 viewers, or distance in rank among the pool
    sizes = sorted(c["x1"] for c in pool)
    rank_of = {c["name"]: float(sum(1 for s in sizes if s < c["x1"])) for c in pool}
    case_rank = float(sum(1 for s in sizes if s < math.log(p1)))
    weights = []
    for comp in pool:
        weight = comp["tier"]
        if comp["S"] is None:
            weight *= 0.2
        if case_platforms["pc"] or case_platforms["ps"] or case_platforms["xb"]:
            same = comp["platforms"]["pc"] == case_platforms["pc"]
            overlap = sum(1 for k in case_platforms if case_platforms[k] and comp["platforms"][k])
            union = sum(1 for k in case_platforms if case_platforms[k] or comp["platforms"][k])
            weight *= (1.0 if same else W_PLATFORM_PC_MISMATCH) * (0.6 + 0.4 * (overlap / union if union else 1.0))
        if comp["weekday"] != weekday:
            weight *= W_WEEKDAY_OTHER
        if WEIGHT_MODE == "rank":
            weight *= math.exp(-0.5 * ((rank_of[comp["name"]] - case_rank) / SIG_SCALE) ** 2)
        else:
            weight *= math.exp(-0.5 * ((comp["x1"] - math.log(p1)) / SIG_SCALE) ** 2)
        weight *= math.exp(-0.5 * ((comp["u"] - u_case) / SIG_UNLOCK) ** 2)
        weights.append(weight)

    scored = [(c, w) for c, w in zip(pool, weights) if c["S"] is not None]
    if not scored:
        return baseline_rows(p1)
    mean_x1 = weighted_mean([c["x1"] for c, _ in scored], [w for _, w in scored])
    mean_x2 = weighted_mean([c["x2"] for c, _ in scored], [w for _, w in scored])

    level_case = case_quiet_level(case, profile)
    s1_case = None if level_case is None else math.log(p1) - level_case - profile[0]


    # case covariates, clipped into the range the pool actually spans
    x1_case = math.log(p1)
    lo1 = min(c["x1"] for c, _ in scored)
    hi1 = max(c["x1"] for c, _ in scored)
    x1_case = max(lo1, min(hi1, x1_case))
    if s1_case is None:
        x2_case = mean_x2
        outlier = 0.0
    else:
        lo2 = min(c["x2"] for c, _ in scored)
        hi2 = max(c["x2"] for c, _ in scored)
        x2_case = max(lo2, min(hi2, s1_case))
        spread = weighted_std([c["x2"] for c, _ in scored], [w for _, w in scored]) or 1.0
        outlier = max(0.0, abs(s1_case - mean_x2) / (2.5 * spread) - 1.0)

    # per-offset covariate slopes, smoothed across neighbouring hours
    raw_b1, raw_b2 = {}, {}
    for o in range(1, 24):
        _, b1, b2, _, _ = weighted_ols3([c["x1"] for c, _ in scored], [c["x2"] for c, _ in scored],
                                        [c["L"][o] for c, _ in scored], [w for _, w in scored])
        raw_b1[o] = max(-BETA_CAP, min(BETA_CAP, b1))
        raw_b2[o] = max(-BETA_CAP, min(BETA_CAP, b2))
    smooth_b1, smooth_b2 = {}, {}
    for o in range(1, 24):
        window = [g for g in (o - 1, o, o + 1) if 1 <= g <= 23]
        smooth_b1[o] = sum(raw_b1[g] for g in window) / len(window)
        smooth_b2[o] = sum(raw_b2[g] for g in window) / len(window)
    shifts = {o: (smooth_b1[o], smooth_b2[o]) for o in range(1, 24)}

    ramp = pool_ramp([c for c, _ in scored], [w for _, w in scored], shifts, (mean_x1, mean_x2))

    # console-only launches (no PC SKU) against the rest: a group offset per hour, capped
    console_only = 0.0 if case_platforms["pc"] else 1.0
    group_delta = {}
    for o in range(1, 24):
        residuals = {0: [], 1: []}
        for comp, weight in zip(pool, weights):
            if comp["S"] is None:
                continue
            phase = ramp_at(ramp, o - comp["u"]) - ramp_at(ramp, -comp["u"])
            trend = smooth_b1[o] * (comp["x1"] - mean_x1) + smooth_b2[o] * (comp["x2"] - mean_x2)
            group = 0 if comp["platforms"]["pc"] else 1
            residuals[group].append((comp["L"][o] - phase - trend, weight))
        if residuals[1] and residuals[0] and sum(w for _, w in residuals[1]) > 1.0 \
                and sum(w for _, w in residuals[0]) > 1.0:
            high = weighted_mean([r for r, _ in residuals[1]], [w for _, w in residuals[1]])
            low = weighted_mean([r for r, _ in residuals[0]], [w for _, w in residuals[0]])
            w1 = sum(w for _, w in residuals[1])
            w0 = sum(w for _, w in residuals[0])
            ess_g = 2.0 * (w1 * w0) / (w1 + w0)
            delta = (high - low) * ess_g / (ess_g + GROUP_SHRINK)
            group_delta[o] = max(-GROUP_CAP, min(GROUP_CAP, delta))
        else:
            group_delta[o] = 0.0
    group_delta = {o: sum(group_delta[g] for g in (o - 1, o, o + 1) if 1 <= g <= 23)
                     / len([g for g in (o - 1, o, o + 1) if 1 <= g <= 23]) for o in range(1, 24)}

    def phase_shifted(o):
        """The ramp increment for the case, with the evening phase shift applied if RAMPSHIFT."""
        if not RAMP_SHIFT or PEAK_SHIFT == 0.0:
            return ramp_at(ramp, o - u_case) - ramp_at(ramp, -u_case)
        taper = 0.0 if o < PEAK_FROM - 2 else min(1.0, (o - (PEAK_FROM - 2)) / 3.0)
        k = o - PEAK_SHIFT * taper
        low = int(math.floor(k))
        frac = k - low
        value = ramp_at(ramp, low - u_case) * (1.0 - frac) + ramp_at(ramp, low + 1 - u_case) * frac
        return value - ramp_at(ramp, -u_case)

    median_shift = {}
    for o in range(1, 24):
        phase = phase_shifted(o)
        trend = smooth_b1[o] * (x1_case - mean_x1) + smooth_b2[o] * (x2_case - mean_x2)
        median_shift[o] = phase + trend + console_only * group_delta[o]

    # --- conformal quantiles -------------------------------------------------------------------
    # A residual from a comparable that was in the fit is optimistic: the fit leans on it. The
    # weighted-least-squares hat diagonal h_i is the exact leave-one-out inflation for the weighted
    # mean and the regression's own leverage, so r / (1 - h_i) estimates the error on a launch the
    # fit never saw. Each hour's five levels are then read as weighted empirical quantiles of those
    # out-of-sample residuals, standardised by the hour's robust scale and pooled over a three-hour
    # window so a thin pool cannot produce jagged tails; the window's quantiles are put back on the
    # hour's own scale. Pooling one sample per window keeps the five levels ordered.
    scored_weights = [w for _, w in scored]
    total_weight = sum(scored_weights)
    ess = (total_weight ** 2) / sum(w * w for w in scored_weights) if total_weight > 0 else 0.0
    s11 = sum(w * (c["x1"] - mean_x1) ** 2 for c, w in scored)
    s22 = sum(w * (c["x2"] - mean_x2) ** 2 for c, w in scored)
    s12 = sum(w * (c["x1"] - mean_x1) * (c["x2"] - mean_x2) for c, w in scored)
    det = s11 * s22 - s12 * s12
    if abs(det) > 1e-12:
        inv = (s22 / det, s12 / det, s11 / det)
    else:
        inv = (0.0, 0.0, 1.0 / max(s22, 1e-9))

    raw = {o: [] for o in range(1, 24)}
    for o in range(1, 24):
        for comp, weight in zip(pool, weights):
            if comp["S"] is None:
                continue
            phase = ramp_at(ramp, o - comp["u"]) - ramp_at(ramp, -comp["u"])
            trend = smooth_b1[o] * (comp["x1"] - mean_x1) + smooth_b2[o] * (comp["x2"] - mean_x2)
            group = 0.0 if comp["platforms"]["pc"] else 1.0
            z1 = comp["x1"] - mean_x1
            z2 = comp["x2"] - mean_x2
            hat = weight * (1.0 / max(total_weight, 1e-9)
                            + inv[0] * z1 * z1 + 2.0 * inv[1] * z1 * z2 + inv[2] * z2 * z2)
            raw[o].append((comp["L"][o] - phase - trend - group * group_delta[o],
                           weight, min(max(hat, 0.0), HAT_CAP)))
    loo_residuals = {o: [] for o in range(1, 24)}
    for o in range(1, 24):
        for value, weight, hat in raw[o]:
            loo_residuals[o].append((value / (1.0 - hat), weight))

    scales = {}
    for o in range(1, 24):
        values = [r for r, _ in loo_residuals[o]]
        ww = [w for _, w in loo_residuals[o]]
        scale = weighted_std(values, ww)
        if ROBUST_SCALE:
            scale = min(scale, 1.4826 * weighted_mad(values, ww))
        scales[o] = max(scale, 1e-6)

    conformal = {}
    for o in range(1, 24):
        window = [g for g in (o - 1, o, o + 1) if 1 <= g <= 23]
        sample = [(r / scales[g], w) for g in window for r, w in loo_residuals[g]]
        quantiles = [weighted_quantile(sample, tau) for tau in LEVELS]
        for i in range(1, 5):
            quantiles[i] = max(quantiles[i], quantiles[i - 1])
        conformal[o] = [q * scales[o] for q in quantiles]

    # the case's own distance from the pool (and thin evidence) widen the band, never the median
    sxx = sum(w * (c["x2"] - mean_x2) ** 2 for c, w in scored)
    dx1 = x1_case - mean_x1
    dx2 = x2_case - mean_x2
    if abs(det) > 1e-12:
        leverage = (inv[2] * dx1 * dx1 - 2.0 * inv[1] * dx1 * dx2 + inv[0] * dx2 * dx2)
    else:
        leverage = dx2 * dx2 / max(sxx, 1e-9)
    leverage = max(0.0, leverage)
    lam = ess / (ess + ESS_K) if ess > 0 else 0.0
    lam /= (1.0 + outlier)

    def profile_at(o):
        """The diurnal term for the case, with the evening phase shift applied (tapered in)."""
        if PEAK_SHIFT == 0.0:
            return profile[o % 24]
        taper = 0.0 if o < PEAK_FROM - 2 else min(1.0, (o - (PEAK_FROM - 2)) / 3.0)
        x = o - PEAK_SHIFT * taper
        low = int(math.floor(x))
        frac = x - low
        return profile[low % 24] * (1.0 - frac) + profile[(low + 1) % 24] * frac

    def band_width(o):
        """Per-band width: the pool's dispersion is wider than a launch-grade case needs late in the
        day (both harnesses over-cover hours 15-24) and too narrow before the evening"""
        if o >= 14:
            return WIDTH_LATE
        if o <= 7:
            return WIDTH_EARLY
        return 1.0

    rows = {}
    for o in range(1, 24):
        scale = scales[o]
        standard_error = scale * math.sqrt(1.0 / max(ess, 1e-6) + leverage)
        widen = math.sqrt(1.0 + (INFLATE * standard_error / scale) ** 2)
        base_shift = median_shift[o]
        spread = [value * WIDTH * band_width(o) * widen for value in conformal[o]]
        quantiles = []
        for i in range(5):
            normal = ZN[i] * BASELINE_SIGMA * math.sqrt(o)  # persistence baseline, o = h - 1
            shift = lam * spread[i] + (1.0 - lam) * normal
            quantiles.append(math.exp(math.log(p1) + (profile_at(o) - profile[0]) + base_shift + shift))
        rows[o + 1] = quantiles
    rows = tidy(rows)
    if PARAM_W > 0.0:
        rows = blend_parametric(rows, scored, pool, weights, ramp, smooth_b1, smooth_b2, group_delta,
                               median_shift, profile, p1, u_case, console_only, x1_case)
    return rows


def blend_parametric(rows, scored, pool, weights, ramp, smooth_b1, smooth_b2, group_delta,
                     median_shift, profile, p1, u_case, console_only, x1_case):
    """Fit log q_tau(o) = a + b*o/24 + c*(o/24)^2 + d*(anchor - log hour1) by pinball loss on the pool's
    own launches, and blend its quantiles with the conformal ones in log space (weight PARAM_W).

    `anchor` is the model's own median log ratio for that launch and hour, so the fit starts from what
    already works and only learns a smooth correction in the hour and in how far the anchor sits below
    hour 1. Fitted by iteratively reweighted least squares: deterministic, fixed iterations, no seed.
    """
    log_p1 = math.log(p1)
    mean_x1 = weighted_mean([c["x1"] for c, _ in scored], [w for _, w in scored])
    features, targets = [], []
    for comp, weight in zip(pool, weights):
        if comp["S"] is None:
            continue
        for o in range(1, 24):
            anchor = (ramp_at(ramp, o - comp["u"]) - ramp_at(ramp, -comp["u"])
                      + smooth_b1[o] * (comp["x1"] - mean_x1)
                      + (0.0 if comp["platforms"]["pc"] else 1.0) * group_delta[o])
            features.append([1.0, o / 24.0, (o / 24.0) ** 2, anchor - comp["x1"]])
            targets.append(comp["L"][o])
    if len(targets) < 40:
        return rows
    betas = [quantile_fit(features, targets, tau, PARAM_ITERS) for tau in LEVELS]
    for o in range(1, 24):
        log_base = log_p1 + (profile[o % 24] - profile[0])
        case_feat = [1.0, o / 24.0, (o / 24.0) ** 2, median_shift[o] - log_p1]
        fitted = [sum(b * f for b, f in zip(betas[i], case_feat)) for i in range(5)]
        values = [math.exp((1.0 - PARAM_W) * math.log(rows[o + 1][i]) + PARAM_W * (log_base + fitted[i]))
                  for i in range(5)]
        for i in range(1, 5):
            values[i] = max(values[i], values[i - 1])
        rows[o + 1] = values
    return tidy(rows)


def case_quiet_level(case, profile):
    """The case's own quiet pre-launch level, from history_hourly, diurnal removed."""
    history = case.get("history_hourly") or ()
    if not history:
        return None
    t0 = parse_ts(case["day_start"])
    values = []
    for point in history:
        viewers = point.get("viewers")
        if not viewers or viewers < 2:
            continue
        offset = int(round((parse_ts(point["from"]) - t0) / 3600.0))
        if BASE_LO <= offset <= BASE_HI:
            values.append(math.log(viewers) - profile[offset % 24])
    if len(values) < MIN_BASE_POINTS:
        values = []
        for point in history:
            viewers = point.get("viewers")
            if not viewers or viewers < 2:
                continue
            offset = int(round((parse_ts(point["from"]) - t0) / 3600.0))
            if offset <= -7:
                values.append(math.log(viewers) - profile[offset % 24])
    if len(values) < MIN_BASE_POINTS:
        return None
    return sum(values) / len(values)


def solve_linear(matrix, rhs):
    """Small dense linear solve with partial pivoting (deterministic)."""
    n = len(rhs)
    rows = [list(matrix[i]) + [rhs[i]] for i in range(n)]
    for i in range(n):
        pivot = max(range(i, n), key=lambda r: abs(rows[r][i]))
        if abs(rows[pivot][i]) < 1e-12:
            continue
        rows[i], rows[pivot] = rows[pivot], rows[i]
        inv = 1.0 / rows[i][i]
        for r in range(i + 1, n):
            factor = rows[r][i] * inv
            if factor:
                for k in range(i, n + 1):
                    rows[r][k] -= factor * rows[i][k]
    out = [0.0] * n
    for i in range(n - 1, -1, -1):
        acc = rows[i][n] - sum(rows[i][k] * out[k] for k in range(i + 1, n))
        out[i] = acc / rows[i][i] if abs(rows[i][i]) > 1e-12 else 0.0
    return out


def quantile_fit(features, targets, tau, iters, ridge=1e-4):
    """Pinball-loss fit of a linear quantile model by iteratively reweighted least squares."""
    k = len(features[0])
    n = len(targets)
    beta = [0.0] * k
    for _ in range(iters):
        ata = [[0.0] * k for _ in range(k)]
        atb = [0.0] * k
        for i in range(n):
            row = features[i]
            r = targets[i] - sum(beta[j] * row[j] for j in range(k))
            w = tau / r if r > 0 else (1.0 - tau) / (-r)
            if w > 1e4:
                w = 1e4
            elif w < 1e-4:
                w = 1e-4
            for a in range(k):
                ra = row[a] * w
                atb[a] += ra * targets[i]
                for b in range(a, k):
                    ata[a][b] += ra * row[b]
        for a in range(k):
            for b in range(a):
                ata[a][b] = ata[b][a]
            ata[a][a] += ridge
        new = solve_linear(ata, atb)
        if max(abs(new[j] - beta[j]) for j in range(k)) < 1e-6:
            beta = new
            break
        beta = new
    return beta


def weighted_mad(values, weights):
    """Weighted median absolute deviation around zero."""
    return weighted_quantile([(abs(v), w) for v, w in zip(values, weights)], 0.5)


def weighted_std(values, weights):
    mean = weighted_mean(values, weights)
    var = weighted_mean([(v - mean) ** 2 for v in values], weights)
    return math.sqrt(max(var, 0.0))


def baseline_rows(p1):
    return {h: [p1 * math.exp(z * BASELINE_SIGMA * math.sqrt(h - 1)) for z in ZN] for h in range(2, 25)}


def tidy(rows):
    out = {}
    for hour in sorted(rows):
        values = []
        for value in rows[hour]:
            value = float(value)
            if not (value == value) or value <= 0:
                value = 1.0
            value = min(value, 1e9)
            value = round2(value)
            value = max(value, 0.01)
            if values and value < values[-1]:
                value = values[-1]
            values.append(value)
        out[hour] = values
    return out


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        try:
            rows = forecast_case(case)
        except Exception:
            # a valid file always beats a crash: fall back to the persistence baseline
            first = next((row for row in case.get("known") or () if row.get("hour") == 1), None)
            p1 = max(1.0, float(first["viewers"])) if first and first.get("viewers") else 1.0
            rows = tidy(baseline_rows(p1))
        document = {"hours": [{"hour": h, "q": rows[h]} for h in sorted(rows)]}
        (OUTPUT_DIR / (path.stem + ".out")).write_text(
            json.dumps(document, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
