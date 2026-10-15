# CoreInfra Hub

`coreinfra_provider` configures an existing SDK provider for the documented
[CoreInfra decision endpoints](https://coreinfra.ru/docs/decisions). Protocol and
model are separate choices. The Hub owns any protocol conversion.

```python
from mellea_jev import JevVerifier, coreinfra_provider

with coreinfra_provider(model="gpt-6-luna", protocol="systemone") as provider:
    verdict = JevVerifier(
        provider,
        "The candidate gives the opening time supported by the reference.",
        reference="The museum opens at 10:00.",
    ).evaluate("The museum opens at 10:00.")
    print(verdict.outcome, verdict.p_yes, verdict.model)
```

Set `COREINFRA_API_KEY` locally or pass `api_key` explicitly. The factory never
uses `TYPESAFE_API_KEY` or `OPENAI_API_KEY` as a fallback. API keys are sent only
to the selected fixed Hub operation URL:

| `protocol` | Returned provider | Exact operation URL |
| --- | --- | --- |
| `systemone` (default) | `TypeSafeProvider` | `https://hub.coreinfra.ai/typesafe/api/v1/systemone` |
| `decisions` | `OpenAIProvider` | `https://hub.coreinfra.ai/openai/api/v1/decisions` |

For `decisions`, install the optional SDK with
`pip install 'mellea-jev-adapter[openai]'`. Both returned types retain their usual
Noul, Choice, Score, Mellea Requirement, and context-manager interfaces. Errors
remain the underlying provider's safe error types. Redirects, environment proxies,
and retries remain disabled. `timeout` and the test `transport` are configurable.

The default model is `jev-latest`. The current Hub documentation lists
`jev-1.13.0`, `jev-latest`, `jev-preview`, and `gpt-6-luna` for both protocols.
Availability and model aliases are controlled by the Hub and account settings;
the factory does not query `/models`, rewrite model IDs, or fall back to another
protocol. Inspect the returned model metadata and evaluate thresholds per route.

For another gateway or a custom operation URL, construct `TypeSafeProvider` or
`OpenAIProvider` directly with their existing URL arguments.

## Conversion and thresholds

The Hub performs protocol conversion when needed. Its documentation says that
Luna System One Noul with outcome criteria becomes a boolean Choice internally,
and Choice/Score confidence is recomputed using TypeSafe formulas. Jev confidence
is retained when converted to Decisions. Calibrate policies per model **and
protocol**. Identical thresholds do not establish equivalent quality.

The adapter checks distributions, labels, score bounds, and metadata after any
Hub conversion. It does not renormalize malformed replies or convert failures
into accepted judgments. An OpenAI refusal converted to System One becomes a
Hub HTTP 502; the Decisions route preserves refusals as explicit refusal errors.
The application can handle the underlying provider's error types as usual.

The TypeSafe provider also exposes mixed `system_one` batches. Our OpenAI
provider sends one question per primitive call; that adapter boundary remains
independent of whether the Hub supports multiple questions upstream.

## Images

The Hub currently documents base64 image support only for `gpt-6-luna` through
the `decisions` route. Jev through Decisions and all System One routes are
documented as text-only. The factory keeps model/protocol selection explicit.

```python
from mellea_jev import ImageInput, coreinfra_provider

with coreinfra_provider(model="gpt-6-luna", protocol="decisions") as provider:
    result = provider.noul(
        state={},
        images={"scene": ImageInput.from_file("scene.png")},
        question="Is a pedestrian crossing visible in `images.scene`?",
    )
```

This explicitly uploads the selected image to the Hub. `WithImages` can bind
the same input to the existing Mellea verifier, classifier, or scorer. Inputs
must be prepared PNG/JPEG bytes; URL fetching, resizing, EXIF rotation, and
automatic route fallback are outside these helpers. Image support in direct
TypeSafe Jev does not establish image support through a gateway.

## Explicit compatibility smoke run

From a development checkout with the optional OpenAI SDK installed:

```bash
make coreinfra-live-check
```

This sends at most **12 billable text requests**: Noul, Choice, and Score for
both models (`jev-latest`, `gpt-6-luna`) through both protocols. Each method is
one request, with no automatic retries. The command stops at the first error.
`COREINFRA_API_KEY` is required, and ordinary CI uses mocked HTTP.

Select the documented preview alias and save receipts to a new local file:

```bash
make coreinfra-live-check COREINFRA_JEV_MODEL=jev-preview \
  COREINFRA_REPORT=/tmp/coreinfra-capture.json
```

Add one prepared image to send **one additional Luna Decisions Noul request**:

```bash
make coreinfra-live-check COREINFRA_JEV_MODEL=jev-preview \
  COREINFRA_IMAGE=/path/to/prepared-scene.png \
  COREINFRA_REPORT=/tmp/coreinfra-image-capture.json
```

The image is read and the report file is exclusively created before any request;
missing/invalid files, unwritable destinations, and existing report paths fail
without paid calls. The report preserves partial receipts on provider errors.
It contains requested model/protocol, normalized results, available model/request
ID/usage, and client elapsed seconds. Keys, endpoint URLs, and image bytes are
excluded. `cost_usd` remains unavailable; token counts alone are not a billing
receipt. `elapsed_seconds` includes client/network/Hub time and is not isolated
model inference latency.

The direct equivalent is:

```bash
python examples/coreinfra_check.py --live --jev-model jev-preview \
  --image /path/to/prepared-scene.png --report /tmp/coreinfra-capture.json
```

Without `--live`, the script exits before constructing a provider. This is a
contract smoke check, with one synthetic text and optional image; it does not
establish FAR/FRR, comparative accuracy, or latency distributions. See the
[October 15 live receipt](../examples/evaluation/coreinfra-compatibility-2026-10-15.md).
