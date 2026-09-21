# Initial live Noul benchmark

This is a reproducible smoke benchmark of the evaluation runner, not an
accuracy claim. It uses four short, synthetic museum-opening examples (two
expected accepts and two expected rejects), with one inference per example and
provider. The sample is too small to estimate production quality or calibrate
thresholds.

## Run setup

- Run date: 2026-09-21 (UTC).
- Dataset: [`museum_opening.jsonl`](museum_opening.jsonl), version `1.0.0`,
  SHA-256 `a7d79ab5facd2648460c48b52f900b2ca8f5ebaf56e196107e357f4d2492ca3f`.
- Platform: macOS 27.0, arm64; Python 3.13.15.
- TypeSafe: `typesafe-sdk` 0.7.0; requested `jev-latest`, returned `jev-1.13.0`.
- Laya: `laya-mlx` 0.1.0 and MLX 0.32.2; checkpoint `aac6fef/laya-mlx`,
  returned model `laya-rl-agent`.
- Wall time for all four cases: Jev 1.91 s; Laya 1.81 s. These are single-run
  process times, not a latency distribution; the Laya time includes model
  loading and local inference.
- Raw predictions: [`live-predictions-2026-09-21.jsonl`](live-predictions-2026-09-21.jsonl).

## Results

False-acceptance rate is false accepts / expected rejects; false-rejection rate
is false rejects / expected accepts; uncertain rate is uncertain predictions /
all examples. Counts are shown with their denominators.

| Provider / model | Reject / accept thresholds | False acceptance | False rejection | Uncertain |
| --- | ---: | ---: | ---: | ---: |
| TypeSafe / `jev-1.13.0` | 0.10 / 0.90 | 0/2 (0%) | 0/2 (0%) | 4/4 (100%) |
| TypeSafe / `jev-1.13.0` | 0.35 / 0.55 | 1/2 (50%) | 0/2 (0%) | 1/4 (25%) |
| Laya / `laya-rl-agent` | 0.10 / 0.90 | 0/2 (0%) | 0/2 (0%) | 4/4 (100%) |
| Laya / `laya-rl-agent` | 0.35 / 0.55 | 0/2 (0%) | 0/2 (0%) | 3/4 (75%) |

At the default wide threshold pair both providers abstain on all cases. The
narrower pair reduces abstentions, while Jev accepts one labeled negative. This
tradeoff on four examples only demonstrates how the runner reports outcomes;
it does not justify using either threshold pair in an application.

## Per-example probabilities

| Example | Expected outcome | Jev `p_yes` | Laya `p_yes` |
| --- | --- | ---: | ---: |
| `correct-time` | accept | 0.6000 | 0.5639 |
| `wrong-time` | reject | 0.5600 | 0.5052 |
| `correct-with-context` | accept | 0.5900 | 0.5484 |
| `closing-time-confusion` | reject | 0.4300 | 0.3553 |

Recalculate both threshold pairs without additional provider calls:

```bash
python examples/evaluate.py examples/evaluation/museum_opening.jsonl \
  --predictions examples/evaluation/live-predictions-2026-09-21.jsonl \
  --threshold 0.10,0.90 --threshold 0.35,0.55
```
