# Categorical classification through Responses

`ResponsesChoiceProvider` uses ordinary generation with strict Structured Outputs
to select labels for one or several named Choice questions. It implements the new
`CategoricalProvider.classify(task)` contract. The existing `OpenAIProvider` still
uses Decisions; the API format is never inferred from a model's name.

Install the existing optional dependency:

```bash
pip install 'mellea-jev-adapter[openai]>=0.8.0'
```

This feature is available starting with version 0.8.0. No additional
mandatory dependency is introduced. Importing the package does not import the
OpenAI SDK; construction requires it but does not send a request or probe a route.

For native Choice wrappers and the optional Mellea policy bridge (since 0.9.0), see
[native categorical providers and Requirements](categorical_requirement.md).

## Contract review decisions

- Reuse `ChoiceQuestion` for definitions. Keep `CategoricalTask`,
  `CategoricalResult`, and `CategoricalProvider` separate from native results.
- One `classify` call is one Responses request, including a shared-state batch.
- Preserve labels, question IDs, their order, and structured descriptions.
- Return label-only answers. There are no generated probabilities, confidence,
  one-hot distributions, implicit abstention labels, repair, or partial salvage.
- Keep existing Noul/Choice/Score result validators and Mellea threshold policies.
  A label-only provider fails at a probability consumer's constructor, before
  dispatch, with `CapabilityMismatchError`.
- Keep native projection explicit; it does not perform inference or claim batch
  execution. Live compatibility and downstream migration are separate work.

## One question

The following call explicitly sends the state to the configured provider and
may incur charges. Set `OPENAI_API_KEY` outside source code.

```python
from mellea_jev import CategoricalTask, ChoiceQuestion, ResponsesChoiceProvider

task = CategoricalTask(
    state={"ticket": "The checkout page goes blank when I click Pay."},
    questions={
        "team": ChoiceQuestion(
            instructions="Which team should handle this ticket?",
            criteria={
                "frontend": {"description": "Page rendering", "examples": ["Blank page"]},
                "payments": "Payment processing or billing.",
                "unknown": "The evidence does not establish a team.",
            },
        ),
    },
)

with ResponsesChoiceProvider(
    model="YOUR_RESPONSES_MODEL",
    max_output_tokens=512,
    # reasoning_effort="low",  # Only when the selected model/route supports it.
) as provider:
    result = provider.classify(task)

print(result.answers["team"])
```

`state` is a JSON-compatible object. The task takes a deep JSON snapshot at
construction and exposes detached `state`, `questions`, and `to_dict()` views.
Files, URLs, conversation history, images, and non-JSON objects are not fetched
or interpreted. A caller-defined `unknown` is a regular category, not an API error.

## Several questions in one request

```python
batch = CategoricalTask(
    state=task.state,
    questions={
        **task.questions,
        "kind": ChoiceQuestion(
            "What kind of request is this?",
            {"bug": "Broken behavior", "feature": "New functionality", "unknown": None},
        ),
    },
)
with ResponsesChoiceProvider(model="YOUR_RESPONSES_MODEL") as provider:
    result = provider.classify(batch)
```

The generated schema requires an object with precisely these keys:

```json
{"answers":{"team":"frontend","kind":"bug"}}
```

Each question ID is required, each value is constrained to that question's enum,
and extra keys are prohibited at both object levels. Local validation additionally
rejects duplicate JSON keys, missing questions, invalid labels, multiple output
texts, non-finite values, malformed envelopes, and unfinished generations.
The example labels illustrate the format; no semantic accuracy is claimed.

Definitions/criteria are serialized into `instructions` as JSON; source state is
separately serialized as `input` JSON under `state`. Structured descriptions are
preserved as JSON objects/arrays rather than discarded or flattened. There are no
tools, previous-response IDs, shared conversation, or implicit truncation.

## URLs, settings, and capabilities

```python
with ResponsesChoiceProvider(
    model="YOUR_RESPONSES_MODEL",
    endpoint_url="https://proxy.example/custom/responses-operation",
    api_key_env="PROXY_API_KEY",
    reasoning_effort="low",
    max_output_tokens=800,
    timeout=20.0,
    max_response_bytes=1_048_576,
) as provider:
    result = provider.classify(task)
```

`base_url` selects an API prefix before `/responses`; `endpoint_url` selects the
exact operation URL without appending a path. They are mutually exclusive and
reuse the SDK routing/URL validation used by other providers. The default is
`https://api.openai.com/v1`. `OPENAI_BASE_URL` and environment proxies are ignored;
redirects and automatic retries are disabled. Only the selected `api_key_env`
(default `OPENAI_API_KEY`) is read when no explicit key is supplied; no other
provider's key is used as a fallback. Keys and URLs are not included in evidence.

Model selection is required. Reasoning effort is omitted unless explicitly set;
unsupported settings are errors, not grounds for changing model or API format.
Defaults are 512 output tokens (including reasoning), a 10-second per-HTTP-operation
timeout, and a 1 MiB response-body cap. A timeout is not an experiment deadline.
`store=False`, `stream=False`, and `truncation="disabled"` are explicitly sent.
Identity encoding is requested; unexpected compressed responses fail explicitly.
The byte cap applies before SDK buffering, including error responses.

`capabilities` declares `strict_schema=True`, `shared_state_batch=True`, and
`native_distribution=False`. This describes the implementation's request format,
not verified support by an arbitrary gateway/model. A live compatibility probe
must be explicitly authorized for the selected route; construction never probes.

## Metadata and raw evidence

| Field | Meaning |
| --- | --- |
| `answers` | Read-only mapping of question IDs to selected labels, in task order |
| `requested_model` | Explicit configured model |
| `returned_model` | Model reported by the provider, or `None`; no alias fallback |
| `request_id` | HTTP `x-request-id`, or `None`; response object ID remains in raw evidence |
| `usage` | Available input/output token counts; missing counts stay `None` |
| `adapter_revision` | Stable builder/parser revision, initially `responses-choice-v1` |
| `settings` | Settings sent by this client, plus timeout/response-size/retry limits |
| `evidence.request_json` | Actual submitted JSON body when available; intended payload on pre-response transport failure |
| `evidence.response_body` | Bounded JSON response bytes; invalid JSON is replaced by an omission marker, unavailable data is `None` |
| `native_results` | Present only for an explicit native projection |

Settings are client-applied configuration, not an attestation that a Proxy or
model honored them. The original task remains available through `task.to_dict()`.
Evidence excludes HTTP headers/URLs and redacts the configured API key, including
JSON-escaped copies. Otherwise wire content is preserved. Request state and raw
outputs can contain sensitive text. They are excluded from default `repr`; the
library does not log or persist them. The application chooses storage and access.
Caller-configured SDK/HTTP logging is a separate application responsibility.

`ResponsesProviderError.evidence` exposes the same explicit diagnostic data when
available. Failure messages omit provider bodies/credentials. Error categories:

- `ResponsesHTTPError`: non-success HTTP response, retaining only status in text.
- `ResponsesRefusalError`: explicit refusal; never mapped to `unknown`.
- `ResponsesIncompleteError`: incomplete generation, including token exhaustion.
- `ResponsesProtocolError`: invalid schema/envelope or unsupported response encoding/size.
- `ResponsesProviderError`: transport/SDK failure; validation did not complete.

There is no partial-answer salvage, model switching, hidden repair call, JSON
mode fallback, or Chat Completions fallback. The whole batch either validates or
raises an error. Unavailable usage is not a zero-cost claim.

## Explicit native projection

```python
from mellea_jev import project_choice_results

# native_choices comes from an already executed native Choice call/batch.
view = project_choice_results(task, {"team": native_choice_result})
assert view.answers["team"] == native_choice_result.choice
assert view.native_results["team"] is native_choice_result
```

IDs and complete native label sets must match the task. The original native
results/distributions are retained separately. A common actual model is retained;
mixed models produce `returned_model=None`. Requested model, request ID, and usage
are not inferred or aggregated; supply them only from actual request metadata.
Projection does not attest single-request batching and never loops over providers.
It cannot turn a categorical result into a probability-based result/Requirement.

## Opt-in compatibility example

The example contains a non-sensitive ticket and two questions in **one** request:

```bash
make responses-choice-live-check RESPONSES_MODEL=YOUR_RESPONSES_MODEL

# Explicit Proxy route and key locator:
make responses-choice-live-check RESPONSES_MODEL=YOUR_RESPONSES_MODEL \
  RESPONSES_ENDPOINT_URL=https://proxy.example/custom/responses-operation \
  RESPONSES_API_KEY_ENV=PROXY_API_KEY RESPONSES_REASONING_EFFORT=low
```

The script requires `--live`, model, and credentials. It prints normalized labels
and metadata, without raw evidence. Ordinary CI uses the actual SDK over mocked
transport.

One [live compatibility probe](../examples/evaluation/responses-coreinfra-2026-10-18.md)
passed on 2026-10-18 through CoreInfra's Responses route with `gpt-6-luna`,
`reasoning_effort="low"`, and two questions in one request. This establishes
that specific route/configuration worked once, without measuring accuracy,
latency distributions, or support by other routes.

## Downstream comparison boundary

NormLab/SpecificationMetrics can construct the same `CategoricalTask` from their
existing state and `ChoiceQuestion` definitions, then consume `result.answers`.
They do not need to copy request builders, schemas, or parsers. Their ontology,
source preparation, semantic consistency checks, abstention policies, budgets,
repeats, reference/adjudication, scoring, and archives remain in those projects.

Keep exact question grouping, definitions, source and brief across comparison
arms. A shared-state batch and independent calls are different conditions.
Refusals, incomplete outputs, malformed JSON, transport failures, domain
consistency, reference agreement and decision coverage are separate outcomes.
Strict JSON does not establish semantic consistency or calibrated probabilities.
Preserve old execution pins; migration/live experiments require separate protocol
revisions after this API is available. No downstream frozen artifacts are edited.

Official references: [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
[Responses create](https://developers.openai.com/api/reference/python/resources/responses/methods/create).
