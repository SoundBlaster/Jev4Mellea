# Live synthetic visual comparison — October 15, 2026

One bounded capture of twelve procedural scenes per route, **24 successful calls**
in total. No retries, warmup, parallel requests, model changes, or failed calls.
These are six correlated scene pairs, with 6 expected accepts and 6 rejects.
Labels are generated from geometry, not human adjudication. This is a small
spatial-overlap experiment; it does not establish photographic accuracy,
parking-law compliance, calibrated probabilities, or a general model ranking.

## Capture provenance

- Source commit: `9c5e03bf8c0f69ef6c899a1dd2ae411081f752c0` (merged PR #61).
- Reference: `crosswalk-overlap-synthetic` version `1.0.0`.
- Reference SHA-256: `14cc36787109356fc79bca813405b3680dcbb337a5c6946a574ef1f80934fbb0`.
- Jev used the direct TypeSafe System One API; Luna used CoreInfra Decisions.
- The same claim, requirement, criteria, and per-scene image were used for both.
  Only those fields were submitted; labels, IDs, geometry, pairs, and hashes
  remained outside the model context. Each image was checked before inference.
- No direct OpenAI key was available. The routes have distinct provider labels;
  latency therefore compares end-to-end deployments, not isolated model speed.
- Both threshold pairs below were computed offline from the same raw outputs.
  There was no extra inference for threshold sweeps and no held-out calibration.
- Token usage and billed cost were not captured; request counts are not a bill.

| Route | Requested / returned model | Started (UTC) | Successful calls | Request IDs available |
| --- | --- | --- | ---: | ---: |
| `typesafe-direct-jev` | `jev-1.14.0` / `jev-1.14.0` | 2026-10-15T11:45:44.735886+00:00 | 12 | 12 |
| `coreinfra-decisions-luna` | `gpt-6-luna` / `gpt-6-luna` | 2026-10-15T11:45:53.607190+00:00 | 12 | 12 |

Snapshots contain runner/metrics and adapter-source hashes, request IDs where
available, UTC start times, raw probabilities, per-call latency, and SDK versions.
Adapter version was `0.6.0` from the working checkout; source hashes identify the
post-release code. TypeSafe SDK `0.7.5`, httpx2 `2.13.1`; Luna additionally used
`openai 3.31.0`.

## Quality and automatic-decision coverage

FAR = false accepts / 6 expected rejects; FRR = false rejects / 6 expected accepts.
Uncertain rate = uncertain predictions / 12. Uncertain outcomes do not count as
false accepts or false rejects. Coverage counts accepts plus rejects / 12.

| Route | reject / accept | FAR | FRR | Uncertain | Coverage | Accepted | Rejected |
| --- | --- | --- | --- | --- | --- | ---: | ---: |
| `coreinfra-decisions-luna` | 0.10 / 0.90 | 1/6 (16.7%) | 0/6 (0.0%) | 1/12 (8.3%) | 11/12 (91.7%) | 6 | 5 |
| `coreinfra-decisions-luna` | 0.20 / 0.80 | 1/6 (16.7%) | 0/6 (0.0%) | 1/12 (8.3%) | 11/12 (91.7%) | 6 | 5 |
| `typesafe-direct-jev` | 0.10 / 0.90 | 0/6 (0.0%) | 0/6 (0.0%) | 7/12 (58.3%) | 5/12 (41.7%) | 0 | 5 |
| `typesafe-direct-jev` | 0.20 / 0.80 | 0/6 (0.0%) | 0/6 (0.0%) | 3/12 (25.0%) | 9/12 (75.0%) | 3 | 6 |

At 0.10/0.90, Jev rejected five negatives and accepted **no** positives:
all six positives and one negative were uncertain. Its zero FAR/FRR must be
read together with that low coverage. At 0.20/0.80 it accepted three positives
and rejected all six negatives, leaving three positives uncertain.

Luna made more automatic decisions, but falsely accepted **v06** (`p_yes=0.91`):
the car is separated from the crossing band by a 16-pixel gap. It left the
positive two-car case **v08** uncertain (`p_yes=0.76`). Both threshold pairs
produce the same Luna outcomes. Neither route is established as generally
better by twelve correlated scenes.

## Per-scene outputs

Outcomes below use reject/accept thresholds 0.10/0.90.

| Scene | Expected | Jev P(yes) | Jev outcome | Luna P(yes) | Luna outcome |
| --- | --- | ---: | --- | ---: | --- |
| [v01](assets/v01.png) | accept | 0.74 | uncertain | 1.00 | accept |
| [v02](assets/v02.png) | reject | 0.05 | reject | 0.00 | reject |
| [v03](assets/v03.png) | reject | 0.04 | reject | 0.00 | reject |
| [v04](assets/v04.png) | accept | 0.81 | uncertain | 0.99 | accept |
| [v05](assets/v05.png) | accept | 0.80 | uncertain | 1.00 | accept |
| [v06](assets/v06.png) | reject | 0.09 | reject | 0.91 | accept |
| [v07](assets/v07.png) | reject | 0.14 | uncertain | 0.00 | reject |
| [v08](assets/v08.png) | accept | 0.76 | uncertain | 0.76 | uncertain |
| [v09](assets/v09.png) | reject | 0.08 | reject | 0.00 | reject |
| [v10](assets/v10.png) | accept | 0.66 | uncertain | 0.96 | accept |
| [v11](assets/v11.png) | accept | 0.84 | uncertain | 0.99 | accept |
| [v12](assets/v12.png) | reject | 0.02 | reject | 0.00 | reject |

## Client-observed latency

Milliseconds per successful `JevVerifier.evaluate` call, including serialization,
transport, and response validation. Image loading, provider setup, receipt I/O,
and report generation are excluded. First-call connections remain included.
All twelve observations per route were measured, with no missing values.

| Route | Mean | Stddev | Min | Median | p90 | p95 | p99 | Max |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `coreinfra-decisions-luna` | 947.4 | 643.3 | 531.8 | 653.7 | 1531.8 | 2140.1 | 2703.0 | 2843.8 |
| `typesafe-direct-jev` | 288.7 | 173.8 | 202.6 | 214.3 | 313.9 | 554.8 | 790.2 | 849.1 |

Population standard deviation; percentiles use linear interpolation at
`(n - 1) * p`. The first calls were 849.1 ms for Jev and 2843.8 ms for Luna.
No warm/cold inference claim is made. The direct Jev route had lower latency
in this capture, but TLS/network/gateway differences are confounded with the
model. Twelve sequential measurements do not provide stable production tail
latency estimates; the two captures were not interleaved or randomized.

## Saved evidence and offline reproduction

| Artifact | SHA-256 |
| --- | --- |
| [jev-live-2026-10-15.jsonl](jev-live-2026-10-15.jsonl) | `fbe86896ded3e69326563680d60aff203db668c30e5ddda2f92622dd27a1b3db` |
| [luna-coreinfra-live-2026-10-15.jsonl](luna-coreinfra-live-2026-10-15.jsonl) | `5125efb7a04a6556b64efaab3238ba37de15cf9642dae08535105c7dd9832f07` |
| [live-metrics-2026-10-15.json](live-metrics-2026-10-15.json) | `e073b9f153ee57c57f8d664943e13dbec7d186f226d8544f96b011c8058e8935` |

From the repository root, with no credentials or new provider calls:

```bash
.venv/bin/python examples/evaluate_visual.py \
  --predictions examples/evaluation/visual/jev-live-2026-10-15.jsonl \
  --predictions examples/evaluation/visual/luna-coreinfra-live-2026-10-15.jsonl \
  --threshold 0.10,0.90 --threshold 0.20,0.80
```

The saved metrics were generated in offline mode (`provider_requests: 0`).
They summarize the preceding 24 live calls; this field does not mean that the
original captures were mocked. Compare JSON values, not whitespace/key ordering.

**Next:** add a separate, rights-cleared photographic reference with human
labels for observable spatial predicates before making real-photo claims.
