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
