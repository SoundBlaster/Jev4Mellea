# ProxyAPI Decisions smoke check — 2026-10-09

Run on 2026-10-08 around 22:25–22:30 UTC (2026-10-09 in Europe/Moscow).
This is a small contract check, not a labeled evaluation or latency benchmark.

## Request and scope

- Endpoint: `https://api.proxyapi.ru/v1/decisions`.
- Requested model: `openai/gpt-6-luna-decisions`.
- State: the Russian checkout-error ticket from the
  [ProxyAPI model example](https://proxyapi.ru/models/openai/gpt-6-luna-decisions).
- Three independent questions sharing that state: product bug (Noul), owning
  team (Choice), and urgency (Score).
- Two requests total: one direct HTTP check, then one through the temporary
  `ProxyAPIProvider`, official TypeSafe SDK, and shared result validation.
- No retries, redirects, or request to the official OpenAI/TypeSafe endpoints.
- Temporary credential supplied through a non-echoing prompt; no credential persisted.

## Observed results

Both calls returned the same normalized values:

| Primitive | Result | Distribution / confidence |
| --- | --- | --- |
| Noul | `p_yes=1.0` | No separate confidence |
| Choice | `payments` | account `0.0`, frontend `0.01`, payments `0.99`; confidence `0.99` |
| Score | `1.65` on levels 0–2 | probabilities `0.01`, `0.33`, `0.66`; confidence `0.47` |

Response model: `openai/gpt-6-luna-decisions-20261006`.
Each request reported `input_tokens=503`, `output_tokens=0` (1006 input tokens total).
Account balance and the actual charged amount were not inspected.

| Path | Request ID | Observed elapsed time |
| --- | --- | --- |
| Direct HTTP | `gen-dec-1791498329-bBYRQutIl7FrsfMcRwsX` | 0.532 s |
| Temporary adapter | `gen-dec-1791498621-BtVsQpttocDUVEUI8OOC` | 0.494 s |

The adapter preserved model, request ID, and usage. Shared validation accepted
the complete Choice labels, Score legend, probability sums, bounds, and
probability-weighted score (`0×0.01 + 1×0.33 + 2×0.66 = 1.65`).
The examples are not assertions about the correct urgency or calibrated confidence.

## Mellea evidence and reproducibility

The live call used `provider.system_one()` to evaluate the three questions in
one request. Separately, mocked HTTP tests exercised the real SDK with
`JevVerifier`, `JevClassifier`, `JevScorer`, and all three real Mellea
`Requirement.validate()` hooks. Live Mellea generation/repair was not run.

From a checkout containing the temporary adapter, set `PROXYAPI_API_KEY` locally
and run `make proxyapi-live-check`. This sends one potentially billable request.
