# Temporary ProxyAPI Decisions adapter

ProxyAPI's [Decisions API](https://proxyapi.ru/docs/decisions) uses `state`, a
mapping of named `questions`, and the `noul` / `choice` / `score` primitives.
The native OpenAI SDK uses a different wire contract (`input`, question arrays,
and `predicate`). Setting `OpenAIProvider.base_url` alone does not bridge them.

`ProxyAPIProvider` is an experimental composition of `TypeSafeProvider` and a
small transport bridge. It reuses the official TypeSafe SDK and our existing
strict answer validation. The bridge changes `/v1/systemone` to `/v1/decisions`
on the fixed `https://api.proxyapi.ru` host and maps response `id` into
`request_id`. SDK types do not enter the Mellea interface.

```python
import os

from mellea_jev import JevClassifier, JevScorer, JevVerifier
from mellea_jev.providers.proxyapi import ProxyAPIProvider

with ProxyAPIProvider(api_key=os.environ["PROXYAPI_API_KEY"]) as provider:
    verifier = JevVerifier(provider, "The candidate describes a product bug.")
    classifier = JevClassifier(
        provider,
        "Which team owns this ticket?",
        criteria={"payments": "Billing and checkout", "frontend": "UI rendering"},
    )
    scorer = JevScorer(
        provider, "Rate urgency.", criteria=["Can wait", "This week", "Blocked today"]
    )
    # Each invocation sends a separate request.
    verdict = verifier.evaluate("Checkout shows a blank page.")
    category = classifier.classify("Checkout shows a blank page.")
    urgency = scorer.evaluate("Checkout shows a blank page.")
```

Existing `.as_requirement()` hooks and client-configured thresholds still work.
For independent questions about the same state, use `provider.system_one()`
with `NoulQuestion`, `ChoiceQuestion`, and `ScoreQuestion` to share one request;
see [the smoke example](examples/live_proxyapi_check.py).

## Run one opt-in live check

Set `PROXYAPI_API_KEY` locally, then run:

```bash
make proxyapi-live-check
# Equivalent after installation:
.venv/bin/python examples/live_proxyapi_check.py --live
```

This sends one mixed request using `openai/gpt-6-luna-decisions`. It prints
validated answers, model, request ID, usage, and elapsed time. It proves the
response contract, not accuracy on a representative dataset. Ordinary CI uses
mock transport and makes no live calls.

The [recorded live smoke check](examples/evaluation/live-proxyapi-smoke-2026-10-09.md)
passed all three primitives through this adapter with model, request ID, and usage.

## Experimental limits

- Import explicitly from `mellea_jev.providers.proxyapi`; no package-root export.
- Supply the ProxyAPI key explicitly; the provider reads no key or URL environment variables.
- Destination is fixed. Environment proxies, redirects, and automatic retries are disabled.
- Failures use the existing safe `JevError` classes; inherited messages may mention TypeSafe.
- Only JSON-object state and the existing shared primitive types are exposed. Shared TypeSafe
  limits apply: 2–255 Choice options and 2–10 Score levels. Images, streaming, and async are absent.
- This bridge is a temporary compatibility layer, not a general endpoint plugin API.
