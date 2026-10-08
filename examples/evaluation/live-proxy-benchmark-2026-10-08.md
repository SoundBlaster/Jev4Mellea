# Live Proxy Noul smoke benchmark

This run checks the evaluation runner against a real TypeSafe-compatible Proxy.
It uses the four existing synthetic museum-opening examples: two expected
accepts and two expected rejects, each with its own reference. The sample does
not establish model accuracy or calibrate production thresholds.

## Run setup

- Date: 2026-10-08 (UTC).
- Dataset: [museum_opening.jsonl](museum_opening.jsonl), version `1.0.0`;
  SHA-256 `a7d79ab5facd2648460c48b52f900b2ca8f5ebaf56e196107e357f4d2492ca3f`.
- Adapter checkout: `17c5cfd`, after evaluation Proxy configuration was merged
  in PR #34. The checkout's package version is `0.2.1`; the runner changes are
  newer than the published 0.2.1 distribution.
- Platform: macOS 27.0, arm64; Python 3.13.15; TypeSafe SDK 0.7.0.
- Implementation: `typesafe`; saved source label: `typesafe-proxy`.
- Requested model: `jev-latest`; returned model: `jev-1.13.0`.
- Four live requests, one per example; automatic retries disabled. Both
  threshold pairs reuse the same predictions.
- Elapsed time: 4.482 seconds for the entire runner call, including provider
  construction, inference, snapshot saving, and report generation. Interpreter
  startup is excluded. This single run is not a latency distribution.
- The URL was selected explicitly and the temporary key was supplied in
  process memory. Neither is stored in these artifacts. No usage or cost data
  is retained by the prediction snapshot format.
- Raw predictions:
  [live-proxy-predictions-2026-10-08.jsonl](live-proxy-predictions-2026-10-08.jsonl).
- Machine-readable metrics:
  [live-proxy-metrics-2026-10-08.json](live-proxy-metrics-2026-10-08.json).

## Results

| Source / returned model | Reject / accept thresholds | False acceptance | False rejection | Uncertain |
| --- | ---: | ---: | ---: | ---: |
| `typesafe-proxy` / `jev-1.13.0` | 0.10 / 0.90 | 0/2 (0%) | 0/2 (0%) | 0/4 (0%) |
| `typesafe-proxy` / `jev-1.13.0` | 0.20 / 0.80 | 0/2 (0%) | 0/2 (0%) | 0/4 (0%) |

| Example | Expected | `p_yes` |
| --- | --- | ---: |
| `correct-time` | accept | 0.98 |
| `wrong-time` | reject | 0.01 |
| `correct-with-context` | accept | 0.97 |
| `closing-time-confusion` | reject | 0.02 |

## Reproduce the report offline

This command loads the saved snapshot and sends no API requests:

```bash
python examples/evaluate.py examples/evaluation/museum_opening.jsonl \
  --predictions examples/evaluation/live-proxy-predictions-2026-10-08.jsonl \
  --threshold 0.10,0.90 --threshold 0.20,0.80
```

For a new live run, set `PROXY_API_KEY` and `PROXY_BASE_URL` for your chosen
TypeSafe-compatible Proxy. This sends the dataset to that service and may incur
charges:

```bash
python examples/evaluate.py examples/evaluation/museum_opening.jsonl \
  --live --provider typesafe --model jev-latest \
  --base-url "$PROXY_BASE_URL" --api-key-env PROXY_API_KEY \
  --provider-label typesafe-proxy \
  --save-predictions /tmp/proxy-predictions.jsonl \
  --threshold 0.10,0.90 --threshold 0.20,0.80
```

## Limitations and next step

The examples cover a correct time, an incorrect time, a paraphrase, and confusion
between opening and closing times. They do not cover long context, ambiguous
requirements, conflicting references, or adversarial instructions. Expand and
review a representative labeled dataset before interpreting these rates as
application-quality estimates.
