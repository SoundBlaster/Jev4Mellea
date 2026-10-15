# CoreInfra protocol compatibility — October 15, 2026

One bounded opt-in run completed **13/13 calls** through the integrated providers:
twelve text primitive calls and one image Noul. The
[normalized receipt](coreinfra-compatibility-2026-10-15.json) retains model,
protocol, available request IDs, usage, and client elapsed seconds.

Environment: macOS, Python 3.13.15, TypeSafe SDK 0.7.5, OpenAI SDK 3.31.0,
HTTPX2 2.13.1, Mellea 0.8.0. The adapter includes unreleased image/connection
changes in this PR stack; this run does not describe the published 0.6.0 package.

## Observed results

The synthetic support ticket reports a duplicate subscription charge and asks
for a refund today. The Noul request supplies explicit true/false criteria;
Choice uses billing/technical labels; Score uses three ordered urgency levels.

| Requested model | Protocol | Returned model | Noul P(yes) | Choice | Score |
| --- | --- | --- | --- | --- | --- |
| `jev-preview` | System One | `jev-1.14.0` | 0.99 | billing | 2.0 / 2 |
| `jev-preview` | Decisions | `jev-1.14.0` | 0.99 | billing | 2.0 / 2 |
| `gpt-6-luna` | System One | `gpt-6-luna` | 1.0 | billing | 2.0 / 2 |
| `gpt-6-luna` | Decisions | `gpt-6-luna` | 1.0 | billing | 2.0 / 2 |

All distributions, score legends, probabilities, and other result fields passed
the adapters' existing strict validation. These outputs on a single simple
ticket do not establish equivalent probabilities or calibrated thresholds.
The Hub documentation explains differences in confidence and Noul conversion.

The additional image call used `gpt-6-luna` via Decisions and returned
`p_yes=1.0` for whether a marked pedestrian crossing is visible. Its usage was
434 input / 0 output tokens. The image was the procedural `v01` diagram from
the [visual reference at a pinned commit](https://github.com/SoundBlaster/Jev4Mellea/blob/b6d14af570b3ade35b1fc46047749b55dbf72c56/examples/evaluation/visual/assets/v01.png),
under the repository's MIT license; no user photo was uploaded in this run.

Request IDs were present for native Jev/System One and native Luna/Decisions
calls. They were absent for the converted routes, and remain `null` in those
results. Total reported usage was **3395 input / 150 output tokens**. No USD
charge was supplied, so no price estimate is presented as a billing receipt.

Client elapsed times are included per call. Each group has only three different
questions, with a fresh provider connection per route. These measurements include
network, connection, Hub conversion, and provider time; they are not a latency
benchmark or a distribution of model inference speeds. No retries were enabled.

## Reproduce explicitly

Set `COREINFRA_API_KEY` locally, prepare the same reference PNG, and select a
new report filename:

```bash
make coreinfra-live-check COREINFRA_JEV_MODEL=jev-preview \
  COREINFRA_IMAGE=/path/to/v01.png COREINFRA_REPORT=/tmp/new-coreinfra-capture.json
```

This may incur charges. Model aliases and provider availability may change.
The [Hub decision contract](https://coreinfra.ru/docs/decisions) was checked on
October 15. Unsupported image routes (Jev Decisions or any System One route)
were not probed; their limitations are documented upstream. Image Choice/Score
and batched requests were covered by mocks where implemented, not by this live
run. No FAR/FRR/uncertainty quality comparison is claimed.

## Provenance

SHA-256 values identify the exact capture, image, and local source files used:

| Artifact | SHA-256 |
| --- | --- |
| Normalized JSON capture | `2142643dd2f1d7606a5a042194876db6b66120f3722802a22226eab022ee8c2f` |
| `v01.png` | `747e8693d458a96b03be7ecd5000b0725c4a6ffb865bf3467ca19be6ad0948e8` |
| `examples/coreinfra_check.py` | `011fd81df9a8b895b41f603d67513a03e7870d5d40b121229ee5f106c22b83b8` |
| `providers/coreinfra.py` | `4c595a1e8d8519e9f32fbb18ac025f8a9c792ad5fa259aec7a3ab3cb2b39d4d8` |
| `providers/openai.py` | `9e8b07af803ec8960e653e8a786af98bb8dd61e3e6f634598be7d2a855db628e` |
| `providers/typesafe.py` | `79ebe7dd83a0d2c0fb47ae57b1623e00c277b940ae8f291d187dde1933ec9187` |
| `images.py` | `4161780d13b04bac71c852e198b6e098970791cb014b827c2041a3cefa267ea2` |

Provider source paths above are under `src/mellea_jev/`. The JSON is an adapter
receipt, not a raw wire dump; it excludes credentials, URLs, and image bytes.
