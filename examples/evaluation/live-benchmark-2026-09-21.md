# Initial live Noul benchmark

This is a reproducible smoke benchmark of the evaluation runner, not an
accuracy claim. It uses four short, synthetic museum-opening examples (two
expected accepts and two expected rejects), with one inference per example and
provider. The sample is too small to estimate production quality or calibrate
thresholds.

**Correction (2026-09-21):** review found that the first recorded run omitted
each example's reference from provider state. Those results were invalid and
have been replaced below with a rerun after fixing reference forwarding.

## Run setup

- Run date: 2026-09-21 (UTC).
- Dataset: [`museum_opening.jsonl`](museum_opening.jsonl), version `1.0.0`,
  SHA-256 `a7d79ab5facd2648460c48b52f900b2ca8f5ebaf56e196107e357f4d2492ca3f`.
- Platform: macOS 27.0, arm64; Python 3.13.15.
- TypeSafe: `typesafe-sdk` 0.7.0; requested `jev-latest`, returned `jev-1.13.0`.
- Laya: `laya-mlx` 0.1.0 and MLX 0.32.2; checkpoint `aac6fef/laya-mlx`,
  returned model `laya-rl-agent`.
- Wall time for all four cases: Jev 1.97 s; Laya 1.08 s. These are single-run
  process times, not a latency distribution; the Laya time includes model
  loading and local inference.
- Raw predictions: [`live-predictions-2026-09-21.jsonl`](live-predictions-2026-09-21.jsonl).

## Results

False-acceptance rate is false accepts / expected rejects; false-rejection rate
is false rejects / expected accepts; uncertain rate is uncertain predictions /
all examples. Counts are shown with their denominators.

| Provider / model | Reject / accept thresholds | False acceptance | False rejection | Uncertain |
| --- | ---: | ---: | ---: | ---: |
| TypeSafe / `jev-1.13.0` | 0.10 / 0.90 | 0/2 (0%) | 0/2 (0%) | 0/4 (0%) |
| TypeSafe / `jev-1.13.0` | 0.35 / 0.55 | 0/2 (0%) | 0/2 (0%) | 0/4 (0%) |
| Laya / `laya-rl-agent` | 0.10 / 0.90 | 0/2 (0%) | 0/2 (0%) | 2/4 (50%) |
| Laya / `laya-rl-agent` | 0.35 / 0.55 | 0/2 (0%) | 0/2 (0%) | 1/4 (25%) |

At both threshold pairs, Jev separates all four cases. Laya abstains on two
examples at the wide pair and one at the narrower pair. This result on four
examples only demonstrates how the runner reports outcomes; it does not
establish comparative accuracy or justify either threshold pair in an
application.

## Per-example probabilities

| Example | Expected outcome | Jev `p_yes` | Laya `p_yes` |
| --- | --- | ---: | ---: |
| `correct-time` | accept | 0.9800 | 0.4031 |
| `wrong-time` | reject | 0.0100 | 0.0408 |
| `correct-with-context` | accept | 0.9700 | 0.6954 |
| `closing-time-confusion` | reject | 0.0200 | 0.0790 |

Recalculate both threshold pairs without additional provider calls:

```bash
python examples/evaluate.py examples/evaluation/museum_opening.jsonl \
  --predictions examples/evaluation/live-predictions-2026-09-21.jsonl \
  --threshold 0.10,0.90 --threshold 0.35,0.55
```
