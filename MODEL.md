# Model notes

Everything here is measured, not asserted: the numbers come from `tools/diagnose.py`, which scores the
entry with `tools/grade_local.py` (the arithmetic of RULES.txt, "Scoring") against the practice
answers the historical source publishes (`tools/practice_answers.json`).

## Shape of the model

For a comparable launch `c` and an hour offset `o` (0 = the release day's first hour, so hour `h` of the
contest is `o = h - 1`), on the log scale:

    ln v_c(o) = a_c + D(o mod 24) + S_c(o - u_c) + noise

* `a_c` — the category's quiet level: the mean of `ln v - D` over the hours 120 to 30 hours before its
  release day, with at least 12 usable points (`v >= 2`). A category with too few quiet hours is flagged
  and down-weighted to 0.2 in the pool; it still contributes its shape, never its level.
* `D` — the UTC-hour-of-day multiplier, estimated only from hours that are neither the release day nor
  the two days after it (`o <= -14` or `o >= 40`), so no launch shape leaks into the diurnal. It is
  centred; the practice pool's profile runs from -0.48 at 09:00Z to +0.72 at 19:00Z.
* `S` — the launch surplus above that quiet level. It is pooled **by phase** `k = o - u_c`, where `u_c`
  is the comparable's unlock hour: an explicit `HH:MM Z|UTC` in its note when the note names the wave,
  else the console convention (US Eastern midnight, 04:00Z in the pool's cases). Aligning by phase is
  what lets a launch that unlocked at 14:00Z lend its ramp to a forecast whose hour 1 sits at 00:00Z.

Two facts make the pool usable:

1. `L_c(o) = S_c(o) - S_c(0)` exactly, so the ramp can be pooled on level-free curves (each comparable
   centred on its own mean surplus). Pooling raw surplus instead lets one 875k-viewer launch dominate
   the average, and the median then swings by a factor of two between implementations.
2. Growth from hour 1 is strongly conditioned on the launch's size and on how elevated hour 1 already
   is: across the 37 pooled launches, `corr(ln v1, ln(v_peak / v1)) = -0.94`. Both covariates are fitted
   per offset by weighted least squares over the pool, smoothed across neighbouring hours, and capped at
   ±0.5 log per unit covariate so a single launch cannot set the slope:

       x1 = ln v1                         (a bigger first hour leaves less room to grow)
       x2 = S1 = ln v1 - a_c - D(0)       (how far above its own quiet level hour 1 already is)

A third, purely structural term handles platform class: console-only launches (no PC SKU) sit above
PC-inclusive ones in the same hours, an offset estimated per hour, shrunk by its own effective sample
size (`ess / (ess + 6)`) and capped at ±0.4 log. GTA VI is console-only (PS5, Xbox Series X|S).

The forecast anchors on the case's hour-1 print and adds, per contest hour `h` (`o = h - 1`):

    ln q_h = ln p1 + [D(o) - D(0)] + [R(o - u_case) - R(-u_case)]
             + B1(o)(x1_case - mean x1) + B2(o)(x2_case - mean x2) + G(o) * console_only + residual

with `u_case` read from the case's own `notes` by the same parser, `x1_case` and `x2_case` clipped into
the range the pool actually spans (no extrapolating a 4x-bigger launch past the biggest comparable).

## Quantiles

No normal assumption, and no shared shape across hours. Each comparable's residual around the formula
above is turned into an out-of-sample residual before anything is read off it: a comparable that was in
the fit is one the fit leaned on, and the weighted-least-squares hat diagonal

    h_i = w_i * (1 / sum(w) + z_i' (Z'WZ)^-1 z_i),      z = (x1, x2) centred

is the exact leave-one-out inflation for the weighted mean plus the regression's own leverage, so
`r_i / (1 - h_i)` estimates the error the same formula would make on a launch it never saw. Each hour's
five levels are then the weighted empirical quantiles of those residuals, standardised by the hour's
robust scale (weighted MAD, capped by the weighted sd) and pooled over a three-hour window, so a thin
pool cannot make jagged tails; the window's quantiles are put back on the hour's own scale. Pooling one
sample per window keeps the five levels ordered, and the 0.5 level is a real per-hour bias correction,
not zero by construction: it is what pulled the median reliability from 0.34 to 0.45 (target 0.50).

Three widenings remain: the case's own distance from the pool (`sqrt(1/ess + leverage)` from the same
2x2 covariance, which is what keeps a case sitting at the pool's edge honest), a width multiplier, and
`lambda = ess / (ess + 14)` divided by `1 + outlier` blending toward the persistence baseline's normal
spread `0.15 * sqrt(h - 1)` when the weighted evidence is thin or hour 1 is an outlier.

Comparable weights (multiplicative, on top of a tier weight from the note: 1.0 comparable, 0.8
unverified, 0.5 weak, 0.25 early-access-contaminated):

    exp(-0.5 ((ln v1 - ln p1)/2.2)^2)          size similarity
    exp(-0.5 ((u_c - u_case)/8)^2)             unlock proximity (soft: the phase term does the work)
    platform overlap, PC mismatch x0.6          same audience
    weekday mismatch x0.9                       release day's position in the week

## What the late-hour residuals answer to

The 17 pooled launches' late residuals (mean of `ln y - ln median` over hours 15-19 and 20-24) against
every covariate available at forecast time:

| covariate | corr with 15-19 | corr with 20-24 |
|-----------|----------------:|----------------:|
| console-only (no PC SKU) | −0.11 | −0.18 |
| number of platforms | +0.35 | +0.16 |
| weekday index | +0.36 | −0.39 |
| unlock hour | −0.11 | −0.17 |
| ln(hour-1 viewers) | +0.01 | −0.37 |
| hour-1 elevation S1 | −0.04 | −0.46 |
| observed evening peak hour | −0.19 | −0.04 |
| ln(viewers per channel), release day | −0.36 | −0.26 |
| *observed* fall from hour 1 to hours 2-6 | +0.38 | +0.75 |

Nothing available at forecast time clears |0.5|, and the two that do (the observed early fall and the
early-band residual) are outcomes, not inputs: the case carries only hour 1. So the late loss is mostly
cross-launch dispersion of the evening amplitude, which is what the conformal width has to carry. The one
*structural* error that is measurable is the peak's timing, not its size, and that is the shift above.

## Two proxies, one decision

A change has to earn its place on both harnesses: leave-one-out over the 17 launch-grade pooled
comparables, and the mean over the four practice cases. (LOO alone once accepted a global phase shift
that cost the practice cases 0.8%, so both columns are now printed for every candidate; the live entry,
audited through this session's tools, is LOO 0.2443 / practice 0.164962, coverage 0.908 / 0.946.)

| candidate | LOO | vs live | practice | vs live | coverage LOO / practice | verdict |
|-----------|----:|--------:|---------:|--------:|------------------------|---------|
| phase shift 0.75 h alone (previously accepted on LOO) | 0.2415 | −1.15% | 0.166328 | +0.83% | 0.910 / 0.946 | rejected: practice worse |
| local conformal, size kernel 1.4 for the quantile read only | 0.2474 | +1.3% | 0.163183 | −1.08% | 0.847 / 0.946 | rejected: LOO worse, LOO coverage out |
| same at kernel 1.8 | 0.2452 | +0.4% | 0.163297 | −1.01% | 0.847 / 0.935 | rejected: LOO worse, coverage out |
| width 0.50 alone | 0.2442 | −0.04% | 0.162923 | −1.24% | 0.890 / 0.935 | rejected: LOO gain under 0.5% |
| phase shift 0.40 h + width 0.50 | 0.2416 | −1.10% | 0.162231 | −1.66% | 0.880 / 0.935 | passed both, but band coverage was lopsided (hours 2-4 at 0.76, hours 20-24 at 0.96 on LOO) |
| **that + band widths 0.85 (hours 15-24) and 1.20 (hours 2-8)** | **0.2401** | **−1.72%** | **0.159744** | **−3.16%** | 0.890 / 0.946 | **accepted** |

The band widths are a calibration, not a fit: per-band coverage showed both harnesses over-covering the
evening (LOO 0.91 and 0.96, practice 1.00 and 1.00 for 15-19 and 20-24) and under-covering the morning
(LOO 0.76 and 0.85, practice 0.75 and 0.88 for 2-4 and 9-14). Narrowing hours 15-24 and widening 2-8
moves both harnesses toward 0.9 at once, and the losses fall in the bands that carry them:

| band | LOO loss, live | LOO loss, accepted |
|------|---------------:|-------------------:|
| 2-4 | 0.1586 | 0.1576 |
| 5-8 | 0.2331 | 0.2325 |
| 9-14 | 0.2688 | 0.2695 |
| 15-19 | 0.2813 | 0.2729 |
| 20-24 | 0.2359 | 0.2276 |

Rejected without a gain: dropping comparables whose hour-1 size is a platform-class outlier (LOO
0.2401 → 0.2404 at 2.5 sd, 0.2408 at 2.0 sd; the size kernel already softens them and trimming removes
the biggest launches that bracket a case like GTA VI), and a tier weight on the quantile read (no effect:
the tier is already inside the weight).

Practice coverage stays at 0.946 against the 0.88-0.92 window: the same width policy cannot satisfy both
harnesses, because leave-one-out needs the wider late band that practice does not. The change moves LOO
from 0.908 into the window and practice from 0.946 to 0.946 while cutting its loss 3.2%; narrowing
further to force practice's 0.92 takes LOO to 0.867, outside the window on the other side. Reported
rather than papered over.

## Per hour, and what was tried on the worst of them

Per-hour loss (mean over the five levels) and 90% coverage on both harnesses at the chosen configuration:

| hour | LOO loss | LOO cov | practice loss | practice cov |
|-----:|---------:|--------:|--------------:|-------------:|
| 12 | 0.2613 | 0.88 | 0.2399 | 0.75 |
| 13 | 0.2853 | 0.82 | 0.1644 | 1.00 |
| 7 | 0.2869 | 0.88 | 0.1587 | 1.00 |
| 17 | 0.2875 | 0.88 | 0.1547 | 1.00 |
| 5 | 0.1305 | 1.00 | 0.2392 | 0.50 |
| 2 | 0.1270 | 0.76 | 0.0595 | 1.00 |

The four worst by combined loss are hours 12, 13, 7 and 17; hour 5 is the practice cases' unlock wave
(their 04:00Z console midnight) and the one hour where the two harnesses disagree hardest (LOO covers
1.00, practice covers 0.50). Nothing below was accepted: each candidate was measured on both, and
`MODEL.md` keeps the numbers so the trade-off is visible rather than remembered.

| candidate | LOO | vs HEAD | practice | vs HEAD | coverage | verdict |
|-----------|----:|--------:|---------:|--------:|----------|---------|
| warp each comparable onto the case's expected evening peak (fade in from hour 8) | 0.2408 | +0.29% | 0.164426 | +2.9% | 0.903 / 0.946 | rejected: worse on both |
| same warp, no global phase shift | 0.2429 | +1.2% | 0.163216 | +2.2% | 0.895 / 0.946 | rejected |
| 0.05/0.95 levels at 0.9x width | 0.2402 | +0.04% | 0.157827 | −1.20% | 0.870 / 0.935 | rejected: LOO worse and its coverage under 0.88 |
| 0.05/0.95 levels at 0.8x width | 0.2419 | +0.75% | 0.156098 | −2.28% | 0.798 / 0.924 | rejected: LOO worse, coverage far out |
| 0.05/0.95 levels at 1.15x width | 0.2413 | +0.50% | 0.162649 | +1.8% | 0.928 / 0.946 | rejected: worse on both |
| band widths 0.80 late / 1.35 early / width 0.48 | 0.2397 | −0.17% | 0.158174 | −0.98% | 0.887 / 0.946 | rejected: LOO gain under the 0.5% bar |
| extra width in the two hours around each case's own unlock | 0.2401 | 0.00% | 0.159624 | −0.08% | 0.890 / 0.946 | rejected: no gain, it only re-spent the early-band width |

The pattern is consistent: every lever that narrows the evening helps the practice cases (which are
over-covered at 0.946) and either leaves leave-one-out flat or breaks its coverage floor, and every lever
that widens the morning does the reverse. With one width policy, the two harnesses cannot be moved
together any further than commit 217a460 already moves them.

## Results

Practice, mean pinball loss over 23 hours x 5 levels (lower is better):

| case | launch | baseline | this entry | gain | 90% coverage | typical miss |
|------|--------|---------:|-----------:|-----:|-------------:|-------------:|
| p00 | Marvel's Wolverine | 0.7436 | 0.2229 | 3.34x | 0.96 | 42% |
| p01 | Red Dead Redemption 2 | 0.2868 | 0.1285 | 2.23x | 1.00 | 18% |
| p02 | God of War Ragnarök | 0.2146 | 0.1205 | 1.78x | 1.00 | 16% |
| p03 | Marvel's Spider-Man 2 | 0.3033 | 0.1879 | 1.61x | 0.83 | 31% |
| **mean** | | **0.387077** | **0.164962** | **2.35x** | 0.946 | 26.1% |

Leave-one-comparable-out is the metric every change below is judged on: each of the 17 pooled launches
with `v1 >= 15000` and a comparable-or-better note is scored with its own curve removed from its own
pool. `tools/loo.py` reports it by hour band and by level, so a change has to move the hours that cost.

| change | LOO loss | vs before | bands 2-4 / 5-8 / 9-14 / 15-19 / 20-24 |
|--------|---------:|----------:|------------------------------------------|
| before this session (shape x scale quantiles) | 0.2636 | — | 0.1560 / 0.2336 / 0.2961 / 0.3066 / 0.2702 |
| conformal per-hour, per-level quantiles | 0.2586 | −1.90% | 0.1519 / 0.2311 / 0.2933 / 0.3021 / 0.2594 |
| + covariate slope cap 0.5 -> 0.3 | 0.2525 | −2.36% | 0.1526 / 0.2304 / 0.2829 / 0.2959 / 0.2502 |
| + size-kernel width 1.5 -> 2.2 | 0.2495 | −1.19% | 0.1550 / 0.2319 / 0.2729 / 0.2886 / 0.2529 |
| + width 0.8 -> 0.55, ESS_K 14 | 0.2443 | −2.08% | 0.1586 / 0.2331 / 0.2710 / 0.2813 / 0.2359 |
| + evening phase shift 0.75 h (diurnal and surplus, tapered in from hour 10) | 0.2415 | −1.15% | 0.1586 / 0.2331 / 0.2688 / 0.2745 / 0.2323 |

The phase shift is not a tuned knob: scoring each pooled launch's evening peak (its maximum over hours
15..24) against the model's shows the model peaks +0.82 h early on average (median +1.0 h), and a shift
of 0.75 h removes most of it. It touches nothing before hour 8 by construction (the taper), so the two
settled early bands do not move at all.

Rejected, both measured (per the rule: revert anything that does not improve LOO by 1%):

| change | LOO loss | verdict |
|--------|---------:|---------|
| separate ramp for unlocks within 2 h of the day start, shrunk by weight | 0.2559 (primary) / 0.3357 (wider set incl. sub-15k launches) | reverted: +1.0% on the primary set but −2.9% on the wider one (Cyberpunk 0.289 -> 0.244, Black Myth 1.52 -> 1.77); one or two near-start comparables is not a regime |
| pre-day elevation (mean of the 36 h before release above the quiet level) as a partial third covariate | 0.2501 at cap 0.10, 0.2522 at cap 0.25 | reverted: +1.8-2.3% worse than 0.2456 at every cap; its raw signal (corr −0.21 with the median residual) is already carried by the hour-1 covariates |
| `categories_hourly` rescaling | not run | not validatable: the field is null in every practice case, so no LOO fold can measure it |
| hour-1 viewers per live channel as a late-hour covariate (one pooled evening slope, capped 0.15-0.5) | 0.2452-0.2505 | reverted: worse at every cap and window. The apparent −0.70 correlation with the hours 20-24 residual came from reading the channel count of the window's *first* day (14 days before release); against the release day's own channels it is −0.26, and dropping Halo Infinite leaves +0.03 |
| rank-based size similarity instead of log-distance | 0.2701 at its best width | reverted: worse at every kernel width tried (2-8 rank positions); rank throws away the absolute level, which the covariates need |
| shift the diurnal only (not the surplus) | 0.2422-0.2423 | superseded: −0.86%, below the 1% bar; shifting both reaches −1.15% |

Per level at the chosen configuration: 0.05 → 0.0190, 0.25 → 0.0583, 0.50 → 0.0765, 0.75 → 0.0671,
0.95 → 0.0234; coverage 0.908. The 9-14, 15-19 and 20-24 bands carry 69% of the loss before the changes and
67% after (0.8729 of 1.2625 → 0.7882 of 1.1799 per band-sum), and they took all of the gain: -8.5%,
-8.3% and -12.7% respectively, while 2-4 got 1.7% worse and 5-8 stayed flat.

Reliability (share of hours with `y <= q_tau`; an honest forecast sits at tau):

| tau | 0.05 | 0.25 | 0.50 | 0.75 | 0.95 |
|-----|-----:|-----:|-----:|-----:|-----:|
| this entry, practice | 0.03 | 0.12 | 0.45 | 0.78 | 0.98 |
| baseline, practice | 0.08 | 0.23 | 0.29 | 0.50 | 0.86 |
| this entry, leave-one-out | 0.02 | 0.19 | 0.46 | 0.71 | 0.92 |

## What it cannot do

* The scale is extrapolated up to the biggest comparable and no further; a launch four times bigger than
  anything in the pool is treated as if it were the biggest. That is a choice: the alternative
  (extrapolating a -0.5 slope) claims knowledge the data does not have.
* A launch whose PC build unlocks hours after the console one (Resident Evil Requiem, Monster Hunter
  Wilds in the leave-one-out set) keeps growing when the pool says decline; those are the entries' worst
  cases and the reason a handful of them lose to the baseline.
* The phase convention is a single number per launch. GTA VI unlocks in waves (NZ, then central Europe,
  the UK, the US east and west coasts); the parser takes the first wave in 00..08Z, which for the final
  case is 00:00Z, the UK/European midnight that dominates its first hour.
