# gta6-twitch-ccu-forecast-01

Forecast, from the first hour of Grand Theft Auto VI's release day on Twitch, how many people watch the
category live in each of the other 23 hours (2026-11-19 UTC), as five quantiles an hour, for the lowest
mean pinball loss on the log scale.

Run: `python3 main.py` (Python 3.13, standard library only, deterministic, offline). It reads every
`*.in` in `$MAKEFUN_INPUT_DIR` (default `/input`) and writes `<id>.out` to `$MAKEFUN_OUTPUT_DIR`
(default `/output`), one file per case, 23 rows of five quantiles each, at most 65,536 bytes.

## How it forecasts

The 38-42 comparable launches in each case are decomposed on the log scale into a quiet level, a
UTC-hour-of-day multiplier and a release-day surplus that lives on **hours since unlock**, then pooled
by phase and corrected for two launch-specific covariates — the size of hour 1 and how elevated hour 1
already is above its own quiet level — plus a console-only platform offset. Quantiles are weighted
empirical quantiles of the pool's standardised residuals (skewed, longer right tail), widened by the
hour's conditional scale and the fit's own uncertainty at the case's covariates, and blended toward the
persistence baseline when the weighted evidence is thin or the first hour is an outlier.

`MODEL.md` has the equations, the constants, and the calibration diagnostics.

## Practice results

Mean pinball loss over hours 2..24 and the five levels; lower is better.

| case | launch | house baseline | this entry | gain |
|------|--------|---------------:|-----------:|-----:|
| p00 | Marvel's Wolverine | 0.7436 | 0.2150 | 3.46x |
| p01 | Red Dead Redemption 2 | 0.2868 | 0.1643 | 1.75x |
| p02 | God of War Ragnarök | 0.2146 | 0.1340 | 1.60x |
| p03 | Marvel's Spider-Man 2 | 0.3033 | 0.1863 | 1.63x |
| mean | | 0.387077 | 0.174906 | 2.21x |

90% coverage 0.946 (baseline 0.783), typical miss 29.5% (baseline 82.7%). The kit ships no local grader,
so `tools/grade_local.py` implements the arithmetic of RULES.txt "Scoring" and is validated against the
RULES worked example (0.112545) and against the published baseline (0.387077 / 82.7% / 0.783).

## Layout

    main.py                     the entry: reads a case, writes the forecast
    MODEL.md                    model structure, constants, diagnostics, limits
    tools/grade_local.py        the documented pinball loss, coverage and typical miss
    tools/validate.py           strict format guard for an output file
    tools/diagnose.py           practice scores, determinism, runtime, leave-one-comparable-out
    tools/practice_answers.json hours 1..24 of the four practice launches (SullyGnome averages)

    python3 tools/diagnose.py --kit <unpacked kit>       full report
    python3 tools/validate.py out/*.out                  format guard

## Attribution

The comparable and practice curves are SullyGnome.com's hourly Twitch category averages, read as
`input/NOTICE.txt` describes; the contest's own counting is make.fun's. Nothing here bulk-downloads the
site: the practice answers are the four release days the kit's practice cases are built from.

MIT licensed.
