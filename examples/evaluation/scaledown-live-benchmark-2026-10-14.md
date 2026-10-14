# ScaleDown Decisions live smoke run — 2026-10-14

This run verifies the adapter against the live ScaleDown Decisions endpoint. It
is a four-example smoke run, not a quality benchmark for production decisions.

## Configuration

- Dataset: `museum-opening-time` version `1.0.0`, 4 examples
- Dataset SHA-256: `a7d79ab5facd2648460c48b52f900b2ca8f5ebaf56e196107e357f4d2492ca3f`
- Provider/model: `scaledown` / `classify-1`
- Endpoint: `https://api.scaledown.xyz/v1/scaledown`
- Live requests: 4, one per example
- Prediction source: [saved predictions](scaledown-live-predictions-2026-10-14.jsonl)
- Reproducible offline report: [metrics JSON](scaledown-live-metrics-2026-10-14.json)

## Results

| Reject / accept thresholds | False acceptance | False rejection | Uncertain |
| --- | ---: | ---: | ---: |
| 0.10 / 0.90 | 0/2 (0%) | 0/2 (0%) | 3/4 (75%) |
| 0.20 / 0.80 | 0/2 (0%) | 0/2 (0%) | 2/4 (50%) |

The output probabilities were `0.9206`, `0.1234`, `0.7909`, and `0.2395` in
dataset order. The stricter thresholds leave three examples for review; the
second pair classifies two additional examples while leaving two uncertain.

## Limits

The dataset is a tiny format demonstration, so these rates do not establish
ScaleDown's accuracy, calibration, or suitability for a real application. The
run confirms that authentication, the endpoint contract, response validation,
and snapshot evaluation work end to end. Latency and per-request cost were not
captured by this evaluation run.

The provider follows the documented [Decisions API](https://docs.scaledown.ai/api-reference/decisions)
and [OpenAPI contract](https://docs.scaledown.ai/api-reference/openapi.json). No
credential is included in the report or prediction snapshot.
