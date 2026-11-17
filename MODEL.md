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

No normal assumption. For every comparable and every hour, the residual around the formula above is
divided by that hour's conditional scale (weighted MAD, capped by the weighted sd, winsorised at ±2), and
the five levels are read as weighted empirical quantiles of the pooled standardised residuals. The
practice pool's shape is roughly (-1.35, -0.55, 0.0, 0.5, 1.8): skewed, with a longer right tail, which
is how launches actually surprise.

Three widenings apply:

* the hour's conditional scale (comparables disagree more at some hours than others);
* the fitted mean's own standard error at the case's covariates, `sqrt(1/ess + leverage)`, leverage being
  the quadratic form of the 2x2 weighted covariance of (x1, x2) — this is what keeps a case sitting at
  the pool's edge honest;
* the weighted evidence `ess = (sum w)^2 / sum w^2`: `lambda = ess / (ess + 8)` blends the empirical
  quantiles with the persistence baseline's normal spread `0.15 * sqrt(h - 1)`, and `lambda` is divided
  by `1 + outlier`, where `outlier` measures how far the case's hour 1 sits from the pool's elevation.

Comparable weights (all multiplicative, on top of a tier weight from the note: 1.0 comparable, 0.8
unverified, 0.5 weak, 0.25 early-access-contaminated):

    exp(-0.5 ((ln v1 - ln p1)/1.5)^2)          size similarity
    exp(-0.5 ((u_c - u_case)/8)^2)             unlock proximity (soft: the phase term does the work)
    platform overlap, PC mismatch x0.6          same audience
    weekday mismatch x0.9                       release day's position in the week

## Results

Practice, mean pinball loss over 23 hours x 5 levels (lower is better):

| case | launch | baseline | this entry | gain | 90% coverage | typical miss |
|------|--------|---------:|-----------:|-----:|-------------:|-------------:|
| p00 | Marvel's Wolverine | 0.7436 | 0.2150 | 3.46x | 0.96 | 41% |
| p01 | Red Dead Redemption 2 | 0.2868 | 0.1643 | 1.75x | 1.00 | 30% |
| p02 | God of War Ragnarök | 0.2146 | 0.1340 | 1.60x | 1.00 | 19% |
| p03 | Marvel's Spider-Man 2 | 0.3033 | 0.1863 | 1.63x | 0.83 | 30% |
| **mean** | | **0.387077** | **0.174906** | **2.21x** | 0.946 | 29.5% |

The baseline's published figures are 0.387, typical miss 82.8%, coverage 0.783; scoring the starter
through `tools/grade_local.py` reproduces them (0.387077 / 82.7% / 0.783), and the RULES worked example
scores 0.112545 as printed.

Leave-one-comparable-out (each of the 17 pooled launches with `v1 >= 15000` and a comparable-or-better
note is treated as the case, with its own curve removed from its pool): mean loss **0.2636** against the
baseline's **0.3472** (1.32x), coverage 0.89, baseline ahead on 3 of 17. That check is the honest one:
the practice cases are scored by a pool that never contained them, and this one also removes each case's
own curve from its neighbours.

Reliability (share of hours with `y <= q_tau`; an honest forecast sits at tau):

| tau | 0.05 | 0.25 | 0.50 | 0.75 | 0.95 |
|-----|-----:|-----:|-----:|-----:|-----:|
| this entry, practice | 0.04 | 0.10 | 0.34 | 0.77 | 0.99 |
| baseline, practice | 0.08 | 0.23 | 0.29 | 0.50 | 0.86 |
| this entry, leave-one-out | 0.04 | 0.22 | 0.48 | 0.72 | 0.92 |

The lower quantiles sit low and the upper ones high: the entry is deliberately wider than the four
practice cases need (they are all covered, and the pooled launches disagree by roughly a factor of two
by mid-afternoon), which is the trade that keeps the leave-one-out coverage at 0.89 instead of 0.6.

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
