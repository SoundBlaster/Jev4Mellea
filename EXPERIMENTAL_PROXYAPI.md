# Temporary ProxyAPI Decisions adapter

This adapter is parked on the `proxyapi-adapter` branch. It is not merged into
`main` or published to PyPI. The branch identifies itself as
`0.2.2.dev0+proxyapi`; the official release remains separate.

## Use in another project

Install the package from the branch (the `mellea` extra enables Requirement hooks):

```bash
python -m pip install 'mellea-jev-adapter[mellea] @ git+https://github.com/SoundBlaster/Jev4Mellea.git@proxyapi-adapter'
```

For reproducible deployments, replace `proxyapi-adapter` in that URL with the
full commit SHA you have reviewed. The distribution name is the same as the
regular adapter: this installation replaces that distribution, so use a project
virtual environment. No repository checkout or editable installation is needed.
Without Mellea hooks, omit `[mellea]` and use the provider directly.

Set `PROXYAPI_API_KEY` in your application's environment and use the explicit
module import in the example below. Supply the key to the provider; it does not
read it implicitly or make requests at import time.

## Contract and composition

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

## Evaluate labeled examples

From a branch checkout, the evaluation runner supports ProxyAPI:

```bash
.venv/bin/python examples/evaluate.py examples/evaluation/museum_opening.jsonl \
  --live --provider proxyapi --provider-label proxyapi-luna \
  --save-predictions /tmp/proxyapi-predictions.jsonl \
  --threshold 0.10,0.90 --threshold 0.20,0.80
```

It reads `PROXYAPI_API_KEY` by default; use `--api-key-env YOUR_KEY_ENV` to select
another variable explicitly. Its destination is fixed, so omit `--base-url`.
Each example produces one request. Threshold sweeps reuse the saved raw probabilities.
Any API failure stops collection; there are no retries.

To reproduce metrics without inference, replace `--live` and connection options
with `--predictions /tmp/proxyapi-predictions.jsonl`. See the
[measured four-example comparison](examples/evaluation/live-proxyapi-benchmark-2026-10-09.md)
for recorded outputs and limitations. The runner and datasets are repository
tools, not wheel-installed CLI commands; the provider itself is packaged.

## Experimental limits

- Import explicitly from `mellea_jev.providers.proxyapi`; no package-root export.
- Supply the ProxyAPI key explicitly; the provider reads no key or URL environment variables.
- Destination is fixed. Environment proxies, redirects, and automatic retries are disabled.
- Failures use the existing safe `JevError` classes; inherited messages may mention TypeSafe.
- Only JSON-object state and the existing shared primitive types are exposed. Shared TypeSafe
  limits apply: 2–255 Choice options and 2–10 Score levels. Images, streaming, and async are absent.
- This bridge is a temporary compatibility layer, not a general endpoint plugin API.
