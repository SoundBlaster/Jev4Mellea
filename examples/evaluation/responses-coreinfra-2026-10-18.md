# Responses categorical compatibility: CoreInfra / Luna low

One explicitly authorized, potentially billable request on **2026-10-18**.
The [JSON receipt](responses-coreinfra-2026-10-18.json) preserves the submitted
request, bounded response, source commit, task, client settings and metadata.
No API credentials or authorization headers are stored.

## Configuration

- Endpoint: `https://hub.coreinfra.ai/openai/api/v1/responses`.
- Provider: `ResponsesChoiceProvider` from commit
  `b3d150b40effa6cb1739e2f73fdd4a20aa63b913`.
- OpenAI Python SDK: **3.31.0**.
- Requested model: `gpt-6-luna`; requested reasoning effort: `low`.
- Output budget: **1024 tokens**, including reasoning.
- Timeout: **30 seconds**; automatic retries: **0**.
- One shared ticket state, two Choice questions, one strict JSON Schema request.
- No fallback, repair, or repeated live call.

The route follows CoreInfra's [API documentation](https://coreinfra.ru/docs/api).
This is the generative Responses endpoint, separate from Decisions API.

## Observed result

| Field | Value |
| --- | --- |
| Task | Checkout page goes blank after clicking Pay |
| `team` | `frontend` |
| `kind` | `bug` |
| Response status | `completed` |
| Returned model | `gpt-6-luna` |
| Request ID | `req_6cc3703393544dbfb10184036b8d8a47` |
| Input tokens | 202 |
| Output tokens | 41, including 19 reasoning tokens reported in raw usage |
| Total tokens | 243 |
| Client elapsed time | 3720.41125 ms |
| Cost | Unknown; provider did not report a price |

The elapsed time covers client construction, the call, validation and closure.
It is neither pure model inference latency nor a latency distribution.
The response echoes `reasoning.effort="low"` and the strict schema.
This does not independently establish internal model execution settings.

## Interpretation and limits

The configured route accepted the structured Responses request, returned both
configured labels, and passed the adapter's local response validation. The
answers are plausible for the ticket. One example without a labeled reference
set cannot establish accuracy, false-acceptance/rejection rates, decision
coverage, calibration, or comparative speed against native decision APIs.

No probabilities or confidence values are synthesized from these labels.
Existing native requirements retain their probability-based contracts.
This receipt records the implementation before the subsequent offline-only
fix that suppresses malformed JSON evidence; no second live call was made.
