# Mellea × Jev — a small adapter for semantic validation

Unofficial Python prototype `0.1.0`, prepared on September 17, 2026.
**Jev checks the generated result; Mellea manages generation and retries.**
This is not a new agent framework or a replacement for the generation backend.

**Validation status:** local unit/contract tests and the offline demo have passed.
The real Mellea package is unavailable in the build environment; its dependencies
could not be installed. No live Jev request or end-to-end
`Mellea → generator → Jev → repair` run was performed. See `TEST_REPORT.md` for
details and actual results. Do not treat this archive as a production-verified
integration or as an evaluation of model quality.

## Quick start without an API key

Python 3.11 or newer. From the unpacked project root:

```bash
make install
make demo
make test
```

The Makefile contains the regular install, test, demo, integration, and opt-in
live-check commands. Run `make help` for the full list. Set `PYTHON=python3.11`
or another Python version >=3.11 when `python3.13` is unavailable.

The offline example uses the real HTTPX client and HTTP contract serialization,
but replaces the network with `MockTransport`. The values `0.98`, `0.02`, and
`0.55` are predefined fixtures, **not model responses**. After dependencies are
installed, the example requires no network access, Ollama, Mellea, or API keys.

## One live Jev request

Create an API key in the [TypeSafe console](https://console.typesafe.ai/).
The request may incur a charge. Do not share the key or put it in source code.

```bash
export TYPESAFE_API_KEY='your-key'
.venv/bin/python examples/live_check.py \
  --candidate 'Hello! Thank you for your message.' \
  --requirement 'The candidate contains a polite greeting.'
```

To check against a reference source:

```bash
.venv/bin/python examples/live_check.py \
  --candidate 'The museum opens at 10:00.' \
  --requirement 'The museum opening time in the candidate matches the reference.' \
  --reference-file ./source.txt
```

## Classify into a fixed set of categories

TypeSafe `Choice` selects one category from the supplied criteria and returns
the selected label, its confidence, and probabilities for all labels. This is
separate from the yes/no `Noul` verifier above.

```python
from mellea_jev import JevClient, JevClassifier

criteria = {
    "billing": "Payments, invoices, and refunds",
    "technical": "Product errors and usage problems",
    "other": "Anything outside the other categories",
}

with JevClient() as jev:
    classifier = JevClassifier(
        jev,
        "Choose the best category for this support message.",
        criteria=criteria,
    )
    result = classifier.classify("I was charged twice for my subscription.")
    print(result.choice, result.confidence, result.probabilities)
```

Each criteria key is a class label; its string value describes that class.
Descriptions can also be `None` when the label is self-explanatory, or a JSON
object or array when a class needs more guidance. Object fields are chosen by
the caller; for example, TypeSafe does not reserve names such as `what`,
`not_for`, or `examples`. Nested values must be JSON-compatible, and criteria
are copied when the question is created. TypeSafe allows up to 255 classes per
Choice question. To require a generated Mellea
candidate to fit a particular class, use
`classifier.as_requirement("billing", minimum_confidence=0.75)` in the
`requirements` list. The optional confidence floor is application policy, not
an accuracy guarantee.

Exit codes: `0` — accepted, `1` — rejected, `2` — uncertain,
`3` — validation did not complete. `.env` is not loaded automatically; see
`.env.example` for sample settings. Do not pass sensitive text as CLI arguments:
it may end up in shell history or the process list.

## Rate against an ordered scale

TypeSafe `Score` evaluates text against ordered level descriptions. Its result
includes a fractional score, a probability for each level, and confidence. The
score is a probability-weighted position on the scale, so it can fall between
levels; it is not a discrete class.

```python
from mellea_jev import JevClient, JevScorer

levels = [
    "Cosmetic; no impact to functionality",
    "Feature is degraded, but a workaround exists",
    "Blocking issue; no workaround exists",
]

with JevClient() as jev:
    scorer = JevScorer(
        jev,
        "How severe is the reported issue?",
        criteria=levels,
    )
    result = scorer.evaluate("The export button crashes in Safari.")
    print(result.score, result.confidence, result.probabilities)
```

To use a Score as a Mellea `Requirement`, set an inclusive numeric bound. The
score policy is application logic; the Mellea `ValidationResult` carries the
Jev numeric score as its optional `score` field.

```python
requirement = scorer.as_requirement(maximum_score=0.75)
# Or accept a range:
requirement = scorer.as_requirement(
    minimum_score=0.5,
    maximum_score=1.25,
    minimum_confidence=0.6,
)
```

TypeSafe supports 2–10 ordered levels. The adapter currently accepts string
level descriptions; structured descriptions are not yet supported.

## Ask several questions in one request

`JevClient.system_one()` accepts a mapping of your question IDs to typed
`NoulQuestion`, `ChoiceQuestion`, or `ScoreQuestion` values and returns the
corresponding typed results. The questions share one state and one HTTP request.

```python
from mellea_jev import ChoiceQuestion, JevClient, NoulQuestion

with JevClient() as jev:
    result = jev.system_one(
        state={"candidate": "I was charged twice and cannot log in."},
        questions={
            "urgent": NoulQuestion("Does the message convey urgency?"),
            "team": ChoiceQuestion(
                "Which team should handle this?",
                {"billing": "Payments and invoices", "technical": "Product errors"},
            ),
        },
    )
    print(result.answers["urgent"].p_yes)
    print(result.answers["team"].choice)
```

The single-primitive methods `noul()`, `choice()`, and `score()` use the same
typed request path. Mellea requirements still validate independently; batch
questions explicitly when the application needs one shared TypeSafe request.

## Connect to Mellea

```bash
make install
```

The package targets **Mellea 0.7.0**. The integration uses its public
`Requirement`, `ValidationResult`, and synchronous `validation_fn`; the source
contract was also checked against the `v0.7.0` tag. Source and documentation
links are in `API_NOTES.md`.

For an existing Mellea session `m`, connect the adapter as follows:

```python
from mellea.stdlib.sampling import RepairTemplateStrategy
from mellea_jev import JevClient, JevVerifier, accepted_text

source = 'The museum opens at 10:00 and closes at 18:00.'

with JevClient() as jev:
    verifier = JevVerifier(
        jev,
        'The museum opening time stated in the candidate matches the reference.',
        reference=source,
        criteria={
            "true": "The candidate gives the opening time from the reference.",
            "false": "The candidate omits or contradicts the opening time.",
        },
        accept_at=0.90,
        reject_at=0.10,
        repair_hint='State only the opening time supported by the reference.',
    )

    sampled = m.instruct(
        'State the museum opening time using this source: {{source}}',
        user_variables={'source': source},
        requirements=[verifier.as_requirement()],
        strategy=RepairTemplateStrategy(loop_budget=3, concurrency_budget=1),
        return_sampling_results=True,
    )
    print(accepted_text(sampled))
```

This snippet assumes an existing session. For a complete example, including
session setup and exception handling, see `examples/mellea_ollama.py`. It uses an
already-running Ollama instance with a model already loaded:

```bash
export TYPESAFE_API_KEY='your-key'
export OLLAMA_MODEL='your-installed-model-tag'
.venv/bin/python examples/mellea_ollama.py
```

This example makes live Jev checks and may incur charges. The choice of
generator is independent of the choice of Jev as verifier.
`RepairTemplateStrategy` is used specifically to pass rejection reasons into
the next generation attempt instead of simply repeating the original request.

## Result semantics

For a positively phrased requirement, `p_yes` is the probability that it is
satisfied. TypeSafe `Noul` has **no separate confidence field**. See the
[Noul description](https://docs.typesafe.ai/primitives/noul).

| Outcome | Default policy | Adapter callback behavior |
|---|---|---|
| `pass` | `p_yes >= 0.90` | `ValidationResult(True, score=p_yes)` |
| `fail` | `p_yes <= 0.10` | `ValidationResult(False, reason=repair_hint, score=p_yes)` |
| `uncertain` | between the thresholds | `ReviewRequired`; the current sampling branch stops |
| empty text | no Jev request | `ValidationResult(False, score=None)` |
| HTTP/network/contract error | do not accept | raises `JevError` or a subclass |

`evaluate(text)` returns all three semantic outcomes as a `Verdict`. The
`ReviewRequired` exception is raised only when using the `as_requirement()`
bridge. It contains `.verdict` and `.candidate`, so the application can send an
uncertain candidate to another verifier or a human. There is no automatic
S2 fallback, SOFAI connection, or hidden extra request.

**Mellea 0.7.0 caveat:** if an attempt has already failed validation before an
error or uncertain result occurs, the strategy may log the exception and return
`SamplingResult(success=False)` with the previous candidate instead of
propagating `ReviewRequired` or `JevError`. Therefore, do not rely only on
`except`: always check `accepted_text()`, and route `GenerationRejected` to the
handler for incomplete tasks as well. The returned `SamplingResult` may not
expose the precise rejection reason. The example uses `concurrency_budget=1`;
with multiple branches, an exception in one branch is not guaranteed to stop the
others. Guaranteed S2 routing by error type requires a separate controller or
an explicit `evaluate()` call outside sampling. This prototype does not modify
Mellea.

**Thresholds are configurable prototype policy, not measured guarantees.**
`0.90` does not mean that accuracy on your task has been measured at 90%.
Before deployment, use your own labeled examples to measure false acceptance
and tune the thresholds. Measure the `uncertain` rate and retry costs separately.
Do not phrase a hazard as a positive condition: for an accepting validator, use
the requirement “The candidate does not disclose secrets” instead of “Is there
a leak?”.

`accepted_text()` checks both `success` and the final validation results.
**Do not return `sampled.result` to users without this check:** a fallback
candidate may exist even when sampling has failed.

## Size and structure

The main implementation fits in two files:

- `src/mellea_jev/client.py`: Noul HTTP contract, API key, timeout, and strict response parsing.
- `src/mellea_jev/verifier.py`: thresholds, `Verdict`, the `Requirement` bridge, and safe result access.

The rest consists of tests, three examples, and documentation. Mellea is imported
only when `as_requirement()` is called, so the client and policy can be tested
without installing the larger framework.

The adapter uses TypeSafe's documented HTTP endpoint directly; it does **not**
invent `jev.decide()` or emulate Jev with another LLM. The official
`typesafe-sdk` is not required: HTTPX is sufficient for a single Noul request.
The client can be replaced through the structural `NoulClient` interface. When
`JevVerifier.criteria` is supplied, that client must accept the optional
`criteria` keyword; without criteria the verifier retains the original call
shape.

## Prototype limits

Only text is supported. `JevClient.system_one()` accepts one or more Noul,
Choice, and Score questions per request; Choice criteria accept class labels
with string, object, array, or `None` descriptions, and Score criteria accept
2–10 ordered string descriptions. Noul accepts optional `true` and `false`
outcome descriptions. Streaming, async client, signed receipts,
telemetry, and a full S2 router are not implemented. Each Mellea requirement
makes its own request on every attempt. The order of requirements in the Mellea
list **does not guarantee** that a cheap check will cancel the other paid checks.

The synchronous Mellea 0.7 callback runs inline, so the network request may
block its event loop. A high-concurrency server needs a separate async variant
with a different extension point. This package does not claim to support that.

There are no automatic network retries. For example, an outer layer should
handle 429/529 responses with a bounded budget and backoff; changing the text
does not fix API overload. The HTTPX `timeout` limits network operations but is
not a hard deadline for the entire task. Cancelling local waiting must not be
treated as proof that server-side work or billing was cancelled.

Only `candidate`, an explicitly supplied `reference`, and the requirement are
sent to TypeSafe. This adapter does not send the full session history. However,
even with a local generator, the text being checked is sent to a cloud service.
Do not submit secrets or confidential documents without appropriate
authorization. The instruction “treat state as data” is not a proven defense
against prompt injection.

The adapter does not log request bodies or API keys. HTTP errors are redacted
to the status code, without the server response body; Mellea or external
telemetry may have its own logs. You provide `repair_hint`: Jev Noul does not
return a textual explanation of the failure. The `model` and `request_id` fields
in `Verdict` are diagnostic metadata, not signed proof of correctness.
`jev-latest` is a mutable alias; for reproducible measurements, specify a
version available to your account.

The HTTP client uses only the official HTTPS endpoint, does not follow
redirects, and does not pick up proxy/CA settings from the environment
(`trust_env=False`). A corporate proxy requires deliberate transport
configuration.

## Checks

```bash
# Local tests; with Mellea installed, its real hook test is included.
.venv/bin/python -m pytest -q

# Integration with the real Requirement.validate, without live models.
.venv/bin/python -m pytest -q tests/test_mellea_integration.py

# Optional real Mellea + local Ollama repair flow; Jev HTTP is mocked.
OLLAMA_MODEL='gemma3n:e2b' RUN_LOCAL_OLLAMA=1 \
  .venv/bin/python -m pytest -q tests/test_mellea_ollama.py

# Explicit opt-in only: sends potentially billable Jev requests.
RUN_LIVE_JEV=1 .venv/bin/python -m pytest -q tests/test_live_jev.py
```

The local Ollama integration requires `.[mellea,dev]`, a running Ollama server,
and the selected model already installed. It does not need a TypeSafe key and
never calls Jev: a mock HTTP transport rejects the first candidate and accepts
the repair attempt. The mock checks integration control flow, not Jev's
semantic judgment. GitHub Actions installs `.[mellea,dev]`, so its full test run
exercises the real Mellea `Requirement.validate` hook with Jev HTTP mocked.

`test_bridge_contract.py` intentionally uses doubles, as its name indicates. It
does not replace `test_mellea_integration.py`. The latter tests the real hook,
but not the full generation cycle. Having an API key alone does not enable the
billable smoke test; the additional flag is required.

The adapter source code is licensed under MIT. This project is not affiliated
with IBM or TypeSafe.
