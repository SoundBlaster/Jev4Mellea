# ProxyAPI Luna Noul evaluation — 2026-10-09

## Scope

Four live Noul requests through the temporary `ProxyAPIProvider` and the actual
evaluation runner, using [museum_opening.jsonl](museum_opening.jsonl) unchanged.
Run on 2026-10-08 around 22:38 UTC (2026-10-09 in Europe/Moscow).
The adapter and runner are parked on `proxyapi-adapter`, not merged into `main`.

- Dataset: `museum-opening-time` v1.0.0; 2 expected accepts and 2 expected rejects.
- SHA-256: `a7d79ab5facd2648460c48b52f900b2ca8f5ebaf56e196107e357f4d2492ca3f`.
- Endpoint: `https://api.proxyapi.ru/v1/decisions`.
- Requested model: `openai/gpt-6-luna-decisions`.
- Returned model: `openai/gpt-6-luna-decisions-20261006`.
- Source label: `proxyapi-luna` (separate from native OpenAI and other gateways).
- Each example used its own candidate and reference; no conversation history was shared.
- Automatic retries and redirects disabled; both threshold pairs reuse the same predictions.
- The temporary key was supplied through a non-echoing prompt and not persisted.

## Predictions

| Example | Expected | ProxyAPI Luna P(yes) | Historical Jev P(yes) | Historical Laya P(yes) |
| --- | --- | ---: | ---: | ---: |
| correct-time | accept | 1.0 | 0.98 | 0.4031 |
| wrong-time | reject | 0.0 | 0.01 | 0.0408 |
| correct-with-context | accept | 1.0 | 0.97 | 0.6954 |
| closing-time-confusion | reject | 0.0 | 0.02 | 0.0790 |

Jev/Laya values are saved observations from 2026-09-21, not new calls. The
TypeSafe-compatible Proxy snapshot from 2026-10-08 has the same Jev values.
All snapshots are checked against the same dataset hash before comparison.

## Metrics

Both reject/accept threshold pairs, **0.10/0.90** and **0.20/0.80**, give the
same observed counts:

| Source / model | False acceptance | False rejection | Uncertain |
| --- | --- | --- | --- |
| proxyapi-luna / openai/gpt-6-luna-decisions-20261006 | 0/2 (0%) | 0/2 (0%) | 0/4 (0%) |
| typesafe / jev-1.13.0 (historical) | 0/2 (0%) | 0/2 (0%) | 0/4 (0%) |
| typesafe-proxy / jev-1.13.0 (historical) | 0/2 (0%) | 0/2 (0%) | 0/4 (0%) |
| laya / laya-rl-agent (historical) | 0/2 (0%) | 0/2 (0%) | 2/4 (50%) |

Laya abstained on both expected accepts. Uncertain cases are counted separately
from false rejections, so its zero false-rejection rate does not mean it accepted
those examples. Jev and ProxyAPI Luna accepted both positives and rejected both
negatives on this sample.

## Timing and usage

- Four requests, `input_tokens=879` total, `output_tokens=0` total.
- Runner elapsed time: **1.391 s**, including provider construction, inference,
  snapshot saving, and report generation; excludes interpreter startup.
- Observed per-call elapsed times: **0.535, 0.313, 0.295, 0.207 s**.
- Observed median: **0.304 s**, mean **0.338 s**; only four observations.
- Usage and request IDs are in [the run trace](live-proxyapi-run-2026-10-09.json).
  Actual balance and charged amount were not inspected.

## Reproduce without inference

```bash
python examples/evaluate.py examples/evaluation/museum_opening.jsonl \
  --predictions examples/evaluation/live-proxyapi-predictions-2026-10-09.jsonl \
  --threshold 0.10,0.90 --threshold 0.20,0.80

python examples/evaluate.py examples/evaluation/museum_opening.jsonl \
  --predictions examples/evaluation/comparison-predictions-2026-10-09.jsonl \
  --threshold 0.10,0.90 --threshold 0.20,0.80
```

New live runs require an explicit `--live --provider proxyapi` and a locally
configured `PROXYAPI_API_KEY`; see [branch instructions](../../EXPERIMENTAL_PROXYAPI.md).

## Artifacts and limitations

- [Raw ProxyAPI predictions](live-proxyapi-predictions-2026-10-09.jsonl)
- [ProxyAPI metrics](live-proxyapi-metrics-2026-10-09.json)
- [Combined historical/new predictions](comparison-predictions-2026-10-09.jsonl)
- [Combined metrics](comparison-metrics-2026-10-09.json)

This is a synthetic four-example smoke evaluation, with only two examples in
each expected class. It does not establish production accuracy, calibrated
probabilities, relative provider superiority, or latency percentiles/SLA.
Historical observations were collected on different dates. Choice and Score
were contract-tested in the earlier smoke check, not evaluated on labeled tasks.
Next: build and independently label a representative dataset with ambiguous,
contradictory, adversarial, and longer-context examples before tuning thresholds.
